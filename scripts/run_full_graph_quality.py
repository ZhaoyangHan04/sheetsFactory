#!/usr/bin/env python3
"""Prepare full-graph joint DBG quality; execute full Factory only with --run."""
from __future__ import annotations

import argparse
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.pipelines.scc_activity_admission import (
    ADAPTER, SOURCE_KIND, JOINT_SETTING, JOINT_METHOD, SCCActivityFactory,
    canonical, checked, read, ref, require, sha, upstream_binding, validate_joint_seed)
from sheets_factory.resume import PROTECTED_BUDGETS
from sheets_factory.task_adapters.public_input_priority import write
from sheets_factory.pipelines.adapted_factory import collect_references, HistoricalRecipeUnavailable


def load_script(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/filename)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


adapted=load_script('_full_graph_support','run_adapted_debug_quality.py')
cohort=adapted.cohort
REGISTRY=ROOT/'config/task_adapters/scc_activity_nodes.yaml'
JOINT_PROMPT=ROOT/'prompts/diagnosis_joint_financial.md'


def recipe_files():
    result=adapted.recipe_files()
    for path in (Path(__file__).resolve(),REGISTRY,JOINT_PROMPT):result[str(path)]=sha(path)
    return result


def selected_specs(*,source_handoff=None,compiler_handoff=None,joint_probe=None,source_selection=None,count=1):
    require(type(count) is int and count in {1,10},'Prepare one development candidate or a complete ten-source cohort addition')
    if count==1:
        require(source_handoff and compiler_handoff and joint_probe and source_selection is None,
                'One-candidate development preparation requires explicit source, compiler and joint-probe handoffs')
        return [{'source_handoff':ref(source_handoff),'compiler_handoff':ref(compiler_handoff),
                 'joint_engineering_probe':ref(joint_probe),'joint_engine_calls':ref(Path(joint_probe).parent/'engine_calls.json')}],None
    require(source_selection and not any((source_handoff,compiler_handoff,joint_probe)),
            'A final-cohort addition requires its complete frozen ten-source selection')
    selection=read(ref(source_selection))
    require(selection.get('kind')=='full_graph_joint_quality_source_selection'
            and selection.get('model_scores_consulted') is False
            and len(selection.get('selected',[]))==10,'Ten-source selection must be complete and frozen before models')
    return selection['selected'],ref(source_selection)


def prepare(output,*,count=1,source_handoff=None,compiler_handoff=None,joint_probe=None,
            source_selection=None,original_batch=None,parallelism=4):
    require(type(parallelism) is int and 1<=parallelism<=4,'Parallelism must be from one through four')
    output=Path(output).resolve();require(not output.exists(),'Preparation requires a fresh output directory')
    specs,selection_ref=selected_specs(source_handoff=source_handoff,compiler_handoff=compiler_handoff,
        joint_probe=joint_probe,source_selection=source_selection,count=count)
    require(count==1 or original_batch is not None,'Final DBG10 must bind the original frozen six-algorithm source batch')
    host=cohort.host_runtime_settings(output);output.mkdir(parents=True)
    with cohort.host_temporary_environment(output,host) as preparation_host:
        bindings={};entries=[];source_bindings={};resolutions=[];originals=[]
        for index,spec in enumerate(specs):
            source=read(spec['source_handoff']);compiler=read(spec['compiler_handoff'])
            binding=deepcopy(source['source_binding']);probe=read(spec['joint_engineering_probe'])
            require(source.get('status')=='actual_source_financial_and_public_numeric_timing_certificates_complete',
                    'Source financial and projection-aware numeric timing certification is incomplete')
            implementation=compiler['recipe']['src/sheets_factory/task_adapters/composite_full_family_v2.py']
            checked(implementation);policy=read(compiler['policy'])
            binding.update(task_adapter={'id':ADAPTER,'implementation':deepcopy(implementation),
                'policy':policy,'policy_sha256':canonical(policy)},
                edits_sha256=compiler['edits_sha256'],root_count=compiler['root_count'])
            identity=binding['source']['sha256']
            require(identity not in source_bindings,'Repeated presented source identity')
            require(binding['edits_sha256']==probe.get('edits_sha256') and binding['root_count']==probe.get('root_count'),
                    'The source compiler and actual joint engineering edits differ')
            source_bindings[identity]=binding
            entry={'source_kind':SOURCE_KIND,'local_path':str(checked(binding['source'])),'sha256':identity,
                'modes':['debugging'],'variant':0,'source_manifest':binding['source_manifest'],
                'task_adapter':binding['task_adapter'],'scc_activity_binding':binding,
                'joint_engineering_probe':spec['joint_engineering_probe'],'joint_engine_calls':spec['joint_engine_calls'],
                'profile_id':spec.get('profile_id','single-development-base-source'),
                'finance_evidence':{'ancestor_recipe_snapshots':{}}}
            financial=read(binding['financial_admission']);originals.append(financial['original_source']['sha256'])
            # Preserve every original reference. Only exact historical Python
            # leaves may resolve through the already reviewed Git snapshot tool.
            while True:
                try:
                    collect_references(spec,bindings,historical_recipe_snapshots=entry['finance_evidence']['ancestor_recipe_snapshots'])
                    collect_references(binding,bindings,historical_recipe_snapshots=entry['finance_evidence']['ancestor_recipe_snapshots'])
                    break
                except HistoricalRecipeUnavailable as missing:
                    resolution=adapted.snapshot_ancestor_recipe(missing.reference,output)
                    resolutions.append(resolution)
                    entry['finance_evidence']['ancestor_recipe_snapshots'][str(Path(missing.reference['path']).resolve())]=resolution['exact_snapshot']
            entries.append(entry)
        if count==10:
            batch=read(ref(original_batch));declared=cohort.validate_batch(batch,bindings)
            require(len(declared)==10 and originals==[e['sha256'] for e in declared],
                    'Final DBG10 must use all original six-batch profiles in their frozen order; development base source is excluded')
            require([e.get('profile_id') for e in entries]==[e['profile_id'] for e in declared],
                    'Final DBG10 profile identities or order differ')
            bindings[str(Path(original_batch).resolve())]=sha(original_batch)
        setting={'enabled':True,'version':1,'contract':JOINT_METHOD,'upstream_construction':upstream_binding(),
            'bindings':ref(output/'activity_bindings.json') if (output/'activity_bindings.json').exists() else None}
        write(output/'activity_bindings.json',{'kind':'full_graph_joint_repair_source_bindings','version':1,'sources':source_bindings})
        setting['bindings']=ref(output/'activity_bindings.json')
        for entry in entries:
            proof=validate_joint_seed(entry,setting);binding=entry['scc_activity_binding'];financial=read(binding['financial_admission'])
            evidence=entry['finance_evidence']
            evidence.update(financial_seed_verified=True,financial_modeling_eligible=False,source_business_issues=[],
                task_adapter=deepcopy(entry['task_adapter']),audited_source_binding=proof,
                full_graph_financial_admission=binding['financial_admission'],source_manifest=binding['source_manifest'],
                public_scenarios=read(binding['source_manifest'])['public_scenarios'],
                source_stability=financial['actual_stability'],
                independent_financial_audits=financial['original_independent_audits'],
                complete_independent_reference_audits=financial['original_independent_audits'],
                financial_validation_method=financial['financial_validation_method'])
            entry['survey']={'normalized_path':binding['source']['path'],'source_sha256':entry['sha256'],'status':'ok','error_count':0}
        if resolutions:write(output/'historical_recipe_resolution.json',{'resolutions':resolutions,'original_refs_modified':False})
        config=yaml.safe_load((ROOT/'config/pipelines/composite_quality20.yaml').read_text())
        llm=yaml.safe_load((ROOT/'config/llm.yaml').read_text());agents=yaml.safe_load((ROOT/'config/agents.yaml').read_text())
        config['agents']={**llm,**config['agents'],'roles':{**agents.get('roles',{}),**config['agents'].get('roles',{})}}
        config['prompt_overrides']={**agents.get('prompts',{}),**config.get('prompt_overrides',{}),'diagnosis.md':JOINT_PROMPT.name}
        config.update(project_root=str(ROOT),run_dir=str(output),host_runtime=host)
        config['pipeline']={**config.get('pipeline',{}),'node_registry':str(REGISTRY)}
        config[JOINT_SETTING]=setting;config.pop('scc_activity',None)
        config['construction']['max_edit_count']['debugging']=100000
        config['run'].update(targets={'financial_modeling':0,'debugging':1} if count==1 else {'financial_modeling':10,'debugging':10},
            seed_manifest=str(output/'seed_manifest.json'),max_sources=count,max_parallel_sources=parallelism)
        config['agents']['max_parallel_calls']=parallelism
        write(output/'seed_manifest.json',{'schema_version':1,'kind':'full_graph_joint_factory_sources',
            'selected':entries,'source_selection':selection_ref,'model_scores_consulted':False,
            'unique_workbooks_inspected':len(entries),'download_url':'private-full-financial-graph:'+canonical([e['sha256'] for e in entries]),
            'archive_sha256':None,
            'development_only':count==1,'qualified':False,'derived_scenarios_are_independent_observed_companies':False})
        (output/'resolved_config.yaml').write_text(yaml.safe_dump(config,sort_keys=False))
        for entry in entries:
            collect_references(entry,bindings,historical_recipe_snapshots=entry['finance_evidence']['ancestor_recipe_snapshots'])
        for path,expected in bindings.items():require(sha(path)==expected,'A source artifact changed during preparation: '+path)
        frozen={'kind':'prepared_full_graph_joint_quality','prepared_at':cohort.utcnow(),'count':count,
            'development_only':count==1,'targets':config['run']['targets'],'source_artifacts_sha256':bindings,
            'recipe_sha256':recipe_files(),'prepared_seed_manifest':ref(output/'seed_manifest.json'),
            'resolved_config':ref(output/'resolved_config.yaml'),'activity_binding':setting['bindings'],
            'source_order':[e['sha256'] for e in entries],'original_sources':originals,
            'host_runtime':host,'preparation_host_runtime':preparation_host,'parallelism':parallelism,
            'protected_budgets':{key:config['run'].get(key) for key in PROTECTED_BUDGETS},
            'actual_LO_calls':0,'actual_model_calls':0,'qualified':False,
            'normal_construct_controls_recovery_12QA_Harbor_pending':True}
        write(output/'preflight_manifest.json',frozen)
        return frozen


def validate_prepared(output):
    output=Path(output).resolve();frozen=read(ref(output/'preflight_manifest.json'))
    require(frozen.get('kind')=='prepared_full_graph_joint_quality','Unexpected full-graph preparation')
    for group in ('recipe_sha256','source_artifacts_sha256'):
        for path,expected in frozen[group].items():require(sha(path)==expected,'Frozen full-graph artifact changed: '+path)
    config=yaml.safe_load(checked(frozen['resolved_config']).read_text())
    entries=read(frozen['prepared_seed_manifest'])['selected']
    require([e['sha256'] for e in entries]==frozen['source_order'] and len(entries)==frozen['count'], 'Frozen source order changed')
    require(config['run']['targets']==frozen['targets']
            and {k:config['run'].get(k) for k in PROTECTED_BUDGETS}==frozen['protected_budgets'], 'Frozen targets or budgets changed')
    for entry in entries:
        require(validate_joint_seed(entry,config[JOINT_SETTING])==entry['finance_evidence']['audited_source_binding'],
                'Prepared full-graph financial or engineering admission changed')
    return frozen


def execute_prepared(output,*,resume=None,port=0):
    output=Path(output).resolve();frozen=validate_prepared(output)
    require((frozen['count']==10)==bool(resume),'One-candidate development runs are separate; DBG10 requires terminal main continuation')
    run=Path(resume).resolve() if resume else output
    continuation=adapted.validate_continuation(run) if resume else None
    settings,legacy=cohort.prepared_host_runtime(run)
    with cohort.host_temporary_environment(run,settings,legacy_preparation=legacy) as host:
        prepared=yaml.safe_load((output/'resolved_config.yaml').read_text())
        revision=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
        session=None
        if continuation:
            old=yaml.safe_load((run/'resolved_config.yaml').read_text())
            patch={'pipeline':prepared['pipeline'],JOINT_SETTING:prepared[JOINT_SETTING],
                'construction':{'max_edit_count':{'debugging':100000}},
                'prompt_overrides':{'diagnosis.md':JOINT_PROMPT.name},
                'run':{'max_parallel_sources':frozen['parallelism']},'agents':{'max_parallel_calls':frozen['parallelism']}}
            session=cohort.prepare_resume(run,extra_manifest=output/'seed_manifest.json',config_patch=patch,
                current_code_revision=revision,reason='Append full-graph joint DBG10; preserve original 10+10 and every task budget')
            config,audit,lease=session.config,session.audit,session.lease
        else:
            config=prepared;require(not (run/'run.sqlite').exists(),'Prepared development run already started')
            lease=cohort.ProducerLease(run).acquire()
            try:
                audit=cohort.AuditStore(run,{'id':run.name,'target_count':1,'financial_target':0,'debugging_target':1,
                    'model':config['agents']['model'],'reasoning_effort':config['agents']['reasoning_effort'],
                    'development_only':True,'difficulty_status':'pending','status':'preflight'})
            except BaseException:
                lease.release();raise
        server,status,started=None,1,time.monotonic();previous=audit.run.get('wall_seconds',0) or 0
        try:
            if continuation:
                require(config['run']['targets']=={'financial_modeling':10,'debugging':10}
                    and all(config['run'].get(k)==old['run'].get(k) for k in PROTECTED_BUDGETS), 'Continuation changed targets or repair budgets')
                cid=config['run']['continuation_id'];private=run/'private/resume'
                addendum={'kind':'immutable_full_graph_joint_continuation','admission':ref(output/'preflight_manifest.json'),
                    'config_before':ref(private/f'resolved_config_before_{cid}.yaml'),
                    'config_after':ref(private/f'resolved_config_after_{cid}.yaml'),
                    'current_resolved_config':ref(run/'resolved_config.yaml'),'old_config_hashes_are_historical':True,
                    'original_preflight':continuation['original_preflight'],'new_recipe_sha256':frozen['recipe_sha256'],
                    'old_recipe_unchanged':True,'old_task_and_content_evidence_infrastructure_budgets_preserved':True,
                    'prospective_parallel_sources':config['run']['max_parallel_sources'],
                    'prospective_parallel_calls':config['agents']['max_parallel_calls'],'qualified':False}
                path=run/'runtime_supplements'/('full_graph_joint_'+cid+'.json');write(path,addendum)
                audit.emit('run.full_graph_joint_continuation',addendum=ref(path))
            server=cohort.DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=port);url=server.start()
            audit.update_run(dashboard_url=url,producer_pid=os.getpid(),producer_active=True,code_revision=revision,
                host_temporary_directory=host['temporary_directory'],host_runtime_receipt=host)
            llm=cohort.CohortCodex(ROOT,run,audit,config['agents']);llm._credentials()
            engine=cohort.LibreOfficeEngine(ROOT,cohort.IMAGE,config['engine']['timeout_seconds'])
            require(engine.metadata()['image_id']==cohort.IMAGE_ID,'Full-graph quality runtime differs')
            print(json.dumps({'run_dir':str(run),'dashboard_url':url,'development_only':frozen['development_only']}),flush=True)
            status=0 if SCCActivityFactory(config,audit,llm,engine,legacy_validator=cohort.validate_seed).run() else 2
            for path,expected in frozen['recipe_sha256'].items():require(sha(path)==expected,'Full-graph recipe changed during execution')
            if continuation:
                for path,expected in continuation['original_recipe_sha256'].items():require(sha(path)==expected,'Original main recipe changed')
            return status
        finally:
            adapted.finalize_execution(audit,server,session,lease,phase_wall=round(time.monotonic()-started,3),previous_wall=previous,status=status)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('output','source-handoff','compiler-handoff','joint-probe','source-selection','original-batch','prepared','resume'):
        parser.add_argument('--'+name,type=Path)
    parser.add_argument('--count',type=int,choices=(1,10),default=1)
    parser.add_argument('--parallelism',type=int,choices=(1,2,3,4),default=4)
    parser.add_argument('--run',action='store_true');parser.add_argument('--port',type=int,default=0)
    args=parser.parse_args(argv)
    if args.prepared:
        require(not any((args.output,args.source_handoff,args.compiler_handoff,args.joint_probe,args.source_selection,args.original_batch)),
                'Prepared execution cannot replace its frozen inputs')
        output=args.prepared;validate_prepared(output)
    else:
        require(args.output,'Preparation requires a fresh output directory');output=args.output
        prepare(output,count=args.count,source_handoff=args.source_handoff,compiler_handoff=args.compiler_handoff,
            joint_probe=args.joint_probe,source_selection=args.source_selection,original_batch=args.original_batch,parallelism=args.parallelism)
    if args.run:return execute_prepared(output,resume=args.resume,port=args.port)
    print(json.dumps({'prepared':str(output.resolve()),'model_calls_started':0,'LO_calls_started':0,'qualified':False}),flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
