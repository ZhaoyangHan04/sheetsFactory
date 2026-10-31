#!/usr/bin/env python3
"""Prepare native-linear normal quality; services require explicit --run."""
from __future__ import annotations

import argparse
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

import yaml

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.pipelines import linear_capital_quality as pipeline
from sheets_factory.task_adapters import linear_capital_portfolio as adapter
from sheets_factory.workbook import linear_capital_public_recovery as recovery
from sheets_factory.workbook.thread_capped_resource_engine import ThreadCappedResourceLibreOfficeEngine
from sheets_factory.evaluation.resource_observer import ResourceObserver
from sheets_factory.resume import PROTECTED_BUDGETS

KIND='prepared_complete_native_linear_capital_normal_quality'
DEFAULT_CONFIG=ROOT/'config/pipelines/linear_capital_quality_v1.yaml'
reference,require=pipeline.reference,pipeline.require
_PREPARED_SESSIONS={}


def support(name):
    path=ROOT/'scripts'/name
    definition=importlib.util.spec_from_file_location('_normal_linear_support_'+path.stem,path)
    module=importlib.util.module_from_spec(definition);definition.loader.exec_module(module)
    return module


cohort=support('run_composite_quality_cohort.py')


class LinearCohortCodex(cohort.CohortCodex):
    """Keep the existing backend and add only MAX2 to isolated public roles."""
    def _build_command(self,workspace,endpoint,isolated,name,**kwargs):
        command=super()._build_command(workspace,endpoint,isolated,name,**kwargs)
        if isolated:
            require(command[:2]==['docker','run'],'The ordinary isolated quality backend changed')
            require(not any(value.startswith('MAX_CONCURRENCY=') for value in command),
                'An isolated quality role already contains a competing worker cap')
            command=command[:2]+['--env','MAX_CONCURRENCY=2']+command[2:]
        return command


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as stream:json.dump(value,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n')
    return reference(path)


def recipes(config,admissions):
    from sheets_factory import core
    from sheets_factory.core import node,pipeline as core_pipeline
    from sheets_factory.nodes import construction,quality
    from sheets_factory.checkers import runner,router,reference_evidence
    from sheets_factory.workbook import profile_indexed,static_references
    from sheets_factory.pipelines import factory,entity_group_contract
    from sheets_factory.evaluation import thread_capped_harbor_export,resource_harbor,resource_streaming_verifier,resource_observer,streaming_delta,streaming_verifier
    from sheets_factory.workbook import resource_engine,thread_capped_resource_engine
    paths=[Path(__file__),DEFAULT_CONFIG,adapter.REGISTRY,
        ROOT/'config/llm.yaml',ROOT/'config/agents.yaml',ROOT/'config/checkers.yaml',ROOT/'config/routes.yaml',
        ROOT/'scripts/run_composite_quality_cohort.py',ROOT/'scripts/run_adapted_debug_quality.py',
        *[Path(module.__file__) for module in (pipeline,adapter,recovery,node,core_pipeline,construction,quality,
            runner,router,reference_evidence,profile_indexed,static_references,factory,entity_group_contract,
            thread_capped_harbor_export,resource_harbor,resource_streaming_verifier,resource_observer,
            streaming_delta,streaming_verifier,resource_engine,thread_capped_resource_engine)],
        *[ROOT/'src/sheets_factory/pipelines/templates'/(mode+'.yaml') for mode in config['run']['targets']]]
    paths.extend(ROOT/'prompts'/config.get('prompt_overrides',{}).get(name,name) for name in
        ('diagnosis.md','instruction_repair.md','trajectory.md'))
    paths.extend(ROOT/'prompts'/name for name in ('diagnosis_reference.md',))
    result={str(p.resolve()):reference(p)['sha256'] for p in paths}
    for item in admissions:
        result.update(item.source.helper.recipes())
        result[item.source.providers.reference['path']]=item.source.providers.reference['sha256']
    return result


def guard_recipes(mapping):
    for path,digest in mapping.items():require(reference(path)['sha256']==digest,'A normal quality dependency changed: '+path)


def _configuration(config_path,output,proofs,provider_registry,runtime_preparation):
    config=yaml.safe_load(Path(config_path).read_text())
    llm=yaml.safe_load((ROOT/'config/llm.yaml').read_text());agents=yaml.safe_load((ROOT/'config/agents.yaml').read_text())
    config['agents']={**llm,**config['agents'],'roles':{**agents.get('roles',{}),**config['agents'].get('roles',{})}}
    config['prompt_overrides']={**agents.get('prompts',{}),**config.get('prompt_overrides',{})}
    protected={key:config['run'].get(key) for key in PROTECTED_BUDGETS}
    profiles={json.dumps(p['runtime_profile'],sort_keys=True) for p in proofs}
    require(len(profiles)==1,'The first normal phase requires one explicit task runtime profile')
    profile=proofs[0]['runtime_profile']
    config.update(project_root=str(ROOT),run_dir=str(output))
    config[adapter.SETTING]=adapter.setting(profile['path'],provider_registry['path'])
    config['pipeline']={**config.get('pipeline',{}),'node_registry':str(adapter.REGISTRY)}
    targets={mode:sum(p['mode']==mode for p in proofs) for mode in ('financial_modeling','debugging')}
    source_count=len({p['workbook']['sha256'] for p in proofs})
    parallel_sources=config['run'].get('max_parallel_sources')
    require(type(parallel_sources) is int and parallel_sources>=1,
        'Configure a positive integer source concurrency before preparation')
    config['run'].update(targets=targets,seed_manifest=str(output/'seed_manifest.json'),
        max_sources=source_count,max_parallel_sources=min(parallel_sources,source_count),
        max_candidates_per_seed=1,source_ordering='manifest',variant_modes=[m for m,n in targets.items() if n])
    require(not any(key in config['run'] for key in ('continuation_id','seed_path','additional_seed_manifests','source_filter')),
        'Use a fresh explicit source/view inventory, not an implicit old continuation')
    config['recovery']={'compiler_backend':recovery.BACKEND,'replay_timeout_seconds':7200,
        'offline_public_recovery':recovery.default_offline_configuration(),
        'public_runtime_preparation':runtime_preparation}
    config['host_runtime']=cohort.host_runtime_settings(output)
    require({key:config['run'].get(key) for key in PROTECTED_BUDGETS}==protected,'Protected normal quality budgets changed')
    pipeline.validate_configuration(config)
    return config,protected


def prepare(source_manifest,validation_terminal,output,*,source_provider='standard',
            public_runtime_preparation,provider_registry=pipeline.DEFAULT_PROVIDERS,config_path=DEFAULT_CONFIG):
    return prepare_many([{'source_manifest':source_manifest,'validation_terminal':validation_terminal,
        'source_provider':source_provider}],output,public_runtime_preparation=public_runtime_preparation,
        provider_registry=provider_registry,config_path=config_path)


def prepare_many(selections,output,*,public_runtime_preparation,
                 provider_registry=pipeline.DEFAULT_PROVIDERS,config_path=DEFAULT_CONFIG):
    """Explicit declared inventory only; no engine/model/solver/Harbor startup."""
    out=Path(output).absolute();require(out==out.resolve() and not out.exists(),'Preserve every previous preparation directory')
    require(type(selections) is list and selections,'Provide at least one explicit source/view selection')
    out.mkdir(parents=True)
    from sheets_factory.core.audit import utcnow
    write(out/'preparation_started.json',{'started_at':utcnow(),'input_selection_count':len(selections),
        'models':0,'LO_calls':0,'solver_calls':0,'Harbor_jobs':0})
    try:
        provider_ref=provider_registry if isinstance(provider_registry,dict) else reference(provider_registry)
        runtime_ref=public_runtime_preparation if isinstance(public_runtime_preparation,dict) else reference(public_runtime_preparation)
        recovery.validate_public_runtime(runtime_ref)
        admissions=[];cold={};declared=[]
        for row in selections:
            require(type(row) is dict and set(row)=={'source_manifest','validation_terminal','source_provider'},
                'Every selection must explicitly bind a provider, source and actual validation')
            source_ref=row['source_manifest'] if isinstance(row['source_manifest'],dict) else reference(row['source_manifest'])
            terminal_ref=row['validation_terminal'] if isinstance(row['validation_terminal'],dict) else reference(row['validation_terminal'])
            key=(row['source_provider'],source_ref['path'],source_ref['sha256'])
            if key not in cold:cold[key]=pipeline.LinearSourceAdmission(source_ref,provider_id=row['source_provider'],provider_registry=provider_ref)
            admissions.append(pipeline.LinearViewAdmission(cold[key],terminal_ref,provider_id=row['source_provider']))
            declared.append({'source_provider':row['source_provider'],'source_manifest':source_ref,'validation_terminal':terminal_ref})
        proofs=[item.guard() for item in admissions]
        require(len({(p['workbook']['sha256'],p['mode']) for p in proofs})==len(proofs),'A source/mode view was repeated')
        config,protected=_configuration(config_path,out,proofs,provider_ref,runtime_ref)
        seeds={}
        for proof in proofs:
            identity=proof['workbook']['sha256']
            if identity not in seeds:
                seeds[identity]={'local_path':proof['workbook']['path'],'sha256':identity,'source_kind':pipeline.NORMAL_SOURCE_KIND,
                    'variant':0,'modes':[],'finance_evidence':{'financial_seed_verified':True,'financial_modeling_eligible':True,
                        'linear_view_admissions':{},'source_manifest':proof['source_manifest']}}
            seeds[identity]['modes'].append(proof['mode']);seeds[identity]['finance_evidence']['linear_view_admissions'][proof['mode']]=proof
        admission_map={(p['workbook']['sha256'],p['mode']):a for p,a in zip(proofs,admissions)}
        for seed in seeds.values():pipeline.validate_seed(seed,admission_map)
        proof_refs=[write(out/'private'/('admission_'+str(index)+'.json'),proof) for index,proof in enumerate(proofs)]
        seed_ref=write(out/'seed_manifest.json',{'selected':list(seeds.values()),'unique_workbooks_inspected':len(seeds),
            'download_url':'local:independently-admitted-native-linear-sources','archive_sha256':None,'qualified':False,'task_count':0})
        mapping=recipes(config,admissions);mapping[str(Path(config_path).resolve())]=reference(config_path)['sha256']
        with cohort.host_temporary_environment(out,config['host_runtime']) as host:
            (out/'resolved_config.yaml').write_text(yaml.safe_dump(config,sort_keys=False))
            for item in admissions:item.guard()
            guard_recipes(mapping)
            frozen={'kind':KIND,'version':1,'created_at':utcnow(),'declared_selections':declared,
                'source_provider_registry':provider_ref,'public_runtime_preparation':runtime_ref,
                'source_view_admissions':proof_refs,'prepared_seed_manifest':seed_ref,
                'configuration_input':reference(config_path),'resolved_config':reference(out/'resolved_config.yaml'),
                'protected_task_budgets':protected,'targets':config['run']['targets'],'count':len(proofs),
                'recipe_sha256':mapping,'host_runtime':config['host_runtime'],'preparation_host_runtime':host,
                'cold_source_validations':len(cold),'prior_source_or_task_quality_transferred':False,
                'existing_development_score_transferred':False,'qualified':False,'task_count':0,
                'actual_models':0,'actual_LO_calls':0,'actual_solver_calls':0,'actual_Harbor_jobs':0}
            receipt=write(out/'preflight_manifest.json',frozen)
            refs=pipeline.References();refs.walk(frozen)
            _PREPARED_SESSIONS[(str(out),receipt['sha256'])]=(deepcopy(frozen),deepcopy(config),tuple(admissions),refs)
            return receipt
    except BaseException as error:
        write(out/'preparation_failure.json',{'finished_at':utcnow(),'type':type(error).__name__,'error':str(error),
            'models':0,'LO_calls':0,'solver_calls':0,'Harbor_jobs':0,'qualified':False})
        raise


def validate_prepared(output):
    out=Path(output).absolute();frozen_ref=reference(out/'preflight_manifest.json')
    key=(str(out),frozen_ref['sha256'])
    if key in _PREPARED_SESSIONS:
        frozen,config,admissions,refs=_PREPARED_SESSIONS[key]
        refs.guard();guard_recipes(frozen['recipe_sha256'])
        for item in admissions:item.guard()
        return deepcopy(frozen),deepcopy(config),admissions
    refs=pipeline.References();frozen=refs.read(frozen_ref)
    require(frozen.get('kind')==KIND and type(frozen.get('version')) is int and frozen['version']==1
        and type(frozen.get('count')) is int and frozen['count']>0
        and all(type(frozen.get(k)) is int and frozen[k]==0 for k in
            ('actual_models','actual_LO_calls','actual_solver_calls','actual_Harbor_jobs','task_count'))
        and frozen.get('qualified') is False and frozen.get('prior_source_or_task_quality_transferred') is False
        and frozen.get('existing_development_score_transferred') is False,'A complete zero-service normal preparation is required')
    guard_recipes(frozen['recipe_sha256']);refs.walk(frozen)
    config=yaml.safe_load(Path(frozen['resolved_config']['path']).read_text())
    require(config['run_dir']==str(out) and config['run']['seed_manifest']==str(out/'seed_manifest.json')
        and config['run']['targets']==frozen['targets'] and config['host_runtime']==frozen['host_runtime']
        and {k:config['run'].get(k) for k in PROTECTED_BUDGETS}==frozen['protected_task_budgets'],
        'The output, quotas or normal protected budgets changed')
    pipeline.validate_configuration(config)
    admissions=[];cold={}
    for row in frozen['declared_selections']:
        key_source=(row['source_provider'],row['source_manifest']['path'],row['source_manifest']['sha256'])
        if key_source not in cold:
            cold[key_source]=pipeline.LinearSourceAdmission(row['source_manifest'],provider_id=row['source_provider'],
                provider_registry=frozen['source_provider_registry'])
        admissions.append(pipeline.LinearViewAdmission(cold[key_source],row['validation_terminal'],provider_id=row['source_provider']))
    require(len(admissions)==frozen['count']==len(frozen['source_view_admissions'])
        and len(cold)==frozen['cold_source_validations'],'The exact cold source/view inventory changed')
    for item,record in zip(admissions,frozen['source_view_admissions']):
        require(item.guard()==refs.read(record),'The complete current source/view proof changed')
    proof_map={(p['workbook']['sha256'],p['mode']):item for item in admissions for p in [item.guard()]}
    seeds=refs.read(frozen['prepared_seed_manifest'])['selected']
    for seed in seeds:pipeline.validate_seed(seed,proof_map)
    require({(s['sha256'],m) for s in seeds for m in s['modes']}==set(proof_map),'A selected task was added or omitted')
    _PREPARED_SESSIONS[key]=(deepcopy(frozen),deepcopy(config),tuple(admissions),refs)
    return deepcopy(frozen),deepcopy(config),tuple(admissions)


def execute_prepared(output,*,port=0):
    out=Path(output).absolute();frozen,config,admissions=validate_prepared(out)
    settings,legacy=cohort.prepared_host_runtime(out)
    with cohort.host_temporary_environment(out,settings,legacy_preparation=legacy) as host:
        require(not (out/'run.sqlite').exists() and not (out/'started.json').exists(),
            'Preserve the first normal attempt; use an explicitly reviewed continuation after startup')
        lease=cohort.ProducerLease(out).acquire();audit=server=None;status=1;clock=time.monotonic()
        try:
            require(not (out/'run.sqlite').exists() and not (out/'started.json').exists(),'Another producer already started')
            write(out/'started.json',{'started_at':cohort.utcnow(),'preflight':reference(out/'preflight_manifest.json'),
                'producer_pid':os.getpid(),'target_count':frozen['count']})
            audit=cohort.AuditStore(out,{'id':out.name,'target_count':frozen['count'],
                'financial_target':frozen['targets']['financial_modeling'],'debugging_target':frozen['targets']['debugging'],
                'status':'preflight','model':config['agents']['model'],'reasoning_effort':config['agents']['reasoning_effort']})
            server=cohort.DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=port);url=server.start()
            audit.update_run(dashboard_url=url,producer_pid=os.getpid(),producer_active=True,
                host_temporary_directory=host['temporary_directory'],host_runtime_receipt=host)
            print(json.dumps({'run_dir':str(out),'dashboard_url':url,'models_started':False}),flush=True)
            profile=config[adapter.SETTING]['runtime_profile']
            engine=ThreadCappedResourceLibreOfficeEngine(ROOT,profile['path'],role='source',receipt_directory=out/'resource_receipts')
            engine.ensure_image()
            llm=LinearCohortCodex(ROOT,out,audit,config['agents']);llm._credentials()
            with ResourceObserver(out,job_dirs=[out/'harbor_jobs']) as observer:
                status=0 if pipeline.LinearCapitalQualityFactory(config,audit,llm,engine,admissions=admissions).run() else 2
            if observer.receipt:write(out/'normal_Harbor_resource_observation.json',{'receipt':observer.receipt})
            for item in admissions:item.guard()
            guard_recipes(frozen['recipe_sha256'])
            return status
        finally:
            try:
                if audit is not None:
                    cleanup=support('run_adapted_debug_quality.py')
                    cleanup.finalize_execution(audit,server,None,lease,
                        phase_wall=round(time.monotonic()-clock,3),previous_wall=0,status=status)
                else:lease.release()
            finally:
                if audit is not None:audit.db.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest',type=Path);parser.add_argument('--validation-terminal',type=Path)
    parser.add_argument('--source-provider',default='standard');parser.add_argument('--output',type=Path)
    parser.add_argument('--public-runtime-preparation',type=Path);parser.add_argument('--provider-registry',type=Path,default=pipeline.DEFAULT_PROVIDERS)
    parser.add_argument('--configuration',type=Path,default=DEFAULT_CONFIG)
    parser.add_argument('--prepared',type=Path);parser.add_argument('--run',action='store_true');parser.add_argument('--port',type=int,default=0)
    args=parser.parse_args(argv)
    if args.prepared:
        require(not any((args.source_manifest,args.validation_terminal,args.output,args.public_runtime_preparation)),
            'Choose an existing preparation or an explicit new source/view selection')
        if args.run:return execute_prepared(args.prepared,port=args.port)
        result=validate_prepared(args.prepared)[0]
        print(json.dumps({'validated':str(args.prepared),'count':result['count'],'models':0,'LO_calls':0}));return 0
    require(not args.run and all((args.source_manifest,args.validation_terminal,args.output,args.public_runtime_preparation)),
        'Prepare and review first; services require a later explicit --prepared --run')
    receipt=prepare(args.source_manifest,args.validation_terminal,args.output,source_provider=args.source_provider,
        public_runtime_preparation=args.public_runtime_preparation,provider_registry=args.provider_registry,config_path=args.configuration)
    print(json.dumps({'preflight':receipt,'models':0,'LO_calls':0,'solver_calls':0}));return 0


if __name__=='__main__':raise SystemExit(main())
