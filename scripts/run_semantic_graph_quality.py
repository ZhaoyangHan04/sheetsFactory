#!/usr/bin/env python3
"""Prepare a V3 normal Factory candidate; models run only with explicit --run."""
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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.pipelines.semantic_graph_admission import (
    SETTING,SOURCE_KIND,SOURCE_ADAPTER,PROVIDER_ID,JOINT_METHOD,node_binding,
    validate_seed,validate_setting,validate_engineering)
from sheets_factory.pipelines.semantic_graph_factory import SemanticGraphFactory
from sheets_factory.task_adapters.public_input_priority import checked,read,ref,require,sha,write
from sheets_factory.task_adapters.public_workbook_scope import POLICY,VERSION,CLAUSES,reference
from sheets_factory.pipelines.adapted_factory import collect_references,HistoricalRecipeUnavailable
from sheets_factory.resume import PROTECTED_BUDGETS

spec=importlib.util.spec_from_file_location('_semantic_frozen_normal_support',ROOT/'scripts/run_adapted_debug_quality.py')
adapted=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapted)
cohort=adapted.cohort
REGISTRY=ROOT/'config/task_adapters/semantic_graph_nodes_v3.yaml'
PROMPT=ROOT/'prompts/diagnosis_joint_financial.md'


def recipe_files():
    result=adapted.recipe_files()
    for p in (Path(__file__).resolve(),REGISTRY,PROMPT):result[str(p)]=sha(p)
    return result


def prepare(output,engineering_receipt):
    output=Path(output).resolve();require(not output.exists(),'Prepare into a fresh directory')
    receipt_ref=ref(engineering_receipt);probe=read(receipt_ref)
    require(probe.get('kind')=='semantic_graph_v3_joint_engineering_probe',
            'The V3 entry requires its own actual two-pass engineering evidence')
    binding=deepcopy(probe['source_binding'])
    binding.update(kind='financial_source_with_separate_semantic_mutation_provider',
        source_presentation_adapter=SOURCE_ADAPTER,mutation_provider=deepcopy(probe['mutation_provider']),
        root_count=probe['root_count'],edits_sha256=probe['edits_sha256'],
        engineering_execution_recipe=ref(Path(engineering_receipt).resolve().parent/'recipe_start.json'))
    identity=binding['source']['sha256'];output.mkdir(parents=True)
    host=cohort.host_runtime_settings(output)
    with cohort.host_temporary_environment(output,host)as host_receipt:
        write(output/'mutation_source_bindings.json',{'kind':'semantic_graph_v3_source_and_provider_bindings',
            'version':1,'sources':{identity:binding},'qualified':False,'task_count':0})
        setting={'enabled':True,'version':1,'contract':JOINT_METHOD,'nodes':node_binding(),
            'bindings':ref(output/'mutation_source_bindings.json')}
        entry={'source_kind':SOURCE_KIND,'local_path':str(checked(binding['source'])),'sha256':identity,
            'modes':['debugging'],'variant':0,'source_manifest':binding['source_manifest'],
            'mutation_provider':binding['mutation_provider'],'semantic_graph_binding':binding,
            'engineering_probe':receipt_ref,'profile_id':'single-primary-semantic-v3-development',
            'finance_evidence':{'ancestor_recipe_snapshots':{}}}
        proof=validate_seed(entry,setting)
        financial=read(binding['financial_admission']);source_manifest=read(binding['source_manifest'])
        entry['finance_evidence'].update(financial_seed_verified=True,financial_modeling_eligible=False,
            debugging_eligible=True,source_business_issues=[],source_presentation_adapter=SOURCE_ADAPTER,
            mutation_provider=binding['mutation_provider'],semantic_graph_binding=binding,
            audited_source_binding=proof,full_graph_financial_admission=binding['financial_admission'],
            source_manifest=binding['source_manifest'],public_scenarios=source_manifest['public_scenarios'],
            source_stability=financial['actual_stability'],
            independent_financial_audits=financial['original_independent_audits'],
            complete_independent_reference_audits=financial['original_independent_audits'],
            financial_validation_method=financial['financial_validation_method'])
        artifacts={};resolutions=[]
        while True:
            try:
                collect_references(entry,artifacts,historical_recipe_snapshots=entry['finance_evidence']['ancestor_recipe_snapshots'])
                break
            except HistoricalRecipeUnavailable as error:
                resolved=adapted.snapshot_ancestor_recipe(error.reference,output);resolutions.append(resolved)
                entry['finance_evidence']['ancestor_recipe_snapshots'][str(Path(error.reference['path']).resolve())]=resolved['exact_snapshot']
        if resolutions:write(output/'historical_recipe_resolution.json',{'resolutions':resolutions,'original_references_modified':False})
        config=yaml.safe_load((ROOT/'config/pipelines/composite_quality20.yaml').read_text())
        llm=yaml.safe_load((ROOT/'config/llm.yaml').read_text());agents=yaml.safe_load((ROOT/'config/agents.yaml').read_text())
        config['agents']={**llm,**config['agents'],'roles':{**agents.get('roles',{}),**config['agents'].get('roles',{})}}
        config['prompt_overrides']={**agents.get('prompts',{}),**config.get('prompt_overrides',{}),'diagnosis.md':PROMPT.name}
        config.update(project_root=str(ROOT),run_dir=str(output),host_runtime=host)
        config['pipeline']={**config.get('pipeline',{}),'node_registry':str(REGISTRY)}
        config[SETTING]=setting;config.pop('scc_activity',None);config.pop('joint_repair_activity',None)
        config['construction']['max_edit_count']['debugging']=100000
        config['run'].update(targets={'financial_modeling':0,'debugging':1},seed_manifest=str(output/'seed_manifest.json'),
            max_sources=1,max_parallel_sources=1,max_candidates_per_seed=1)
        config['agents']['max_parallel_calls']=1
        write(output/'public_scope_binding.json',{'kind':'public_workbook_scope_binding','version':VERSION,
            'clauses':CLAUSES,'sources':{identity:{'source':reference(checked(binding['source']))}},
            'quality_or_difficulty_certified':False})
        config[POLICY]={'version':VERSION,'manifest':reference(output/'public_scope_binding.json')}
        write(output/'seed_manifest.json',{'schema_version':1,'kind':'semantic_graph_v3_factory_seed_pool',
            'selected':[entry],'unique_workbooks_inspected':1,'download_url':'derived-semantic-provider-v3-pool',
            'archive_sha256':None,'development_only':True,'model_scores_consulted':False,
            'source_original_ancestors':source_manifest['source_original_ancestors'],
            'derived_presentation_source_count':1,'qualified':False,'task_count':0})
        (output/'resolved_config.yaml').write_text(yaml.safe_dump(config,sort_keys=False))
        artifacts.update({str(checked(receipt_ref)):receipt_ref['sha256'],
            str(output/'public_scope_binding.json'):sha(output/'public_scope_binding.json'),
            str(output/'mutation_source_bindings.json'):sha(output/'mutation_source_bindings.json')})
        for path,digest in artifacts.items():require(sha(path)==digest,'A bound source artifact changed during preparation: '+path)
        frozen={'kind':'prepared_separate_semantic_graph_v3_normal_quality','prepared_at':cohort.utcnow(),
            'development_only':True,'count':1,'source_order':[identity],'provider_id':PROVIDER_ID,
            'source_presentation_adapter':SOURCE_ADAPTER,'engineering_probe':receipt_ref,
            'prepared_seed_manifest':ref(output/'seed_manifest.json'),'resolved_config':ref(output/'resolved_config.yaml'),
            'source_artifacts_sha256':artifacts,'recipe_sha256':recipe_files(),
            'host_runtime':host,'preparation_host_runtime':host_receipt,
            'protected_budgets':{key:config['run'].get(key)for key in PROTECTED_BUDGETS},
            'actual_LO_calls':0,'actual_model_calls':0,'qualified':False,'task_count':0,
            'normal_construct_five_controls_recovery_12QA_Harbor_required':True}
        write(output/'preflight_manifest.json',frozen)
        return ref(output/'preflight_manifest.json')


def validate_prepared(output):
    output=Path(output).resolve();frozen=read(ref(output/'preflight_manifest.json'))
    require(frozen.get('kind')=='prepared_separate_semantic_graph_v3_normal_quality'
            and frozen.get('development_only')is True and frozen.get('count')==1,'Unexpected V3 preparation kind')
    for group in ('source_artifacts_sha256','recipe_sha256'):
        for path,digest in frozen[group].items():require(sha(path)==digest,'A frozen V3 artifact changed: '+path)
    config=yaml.safe_load(checked(frozen['resolved_config']).read_text());validate_setting(config[SETTING])
    entries=read(frozen['prepared_seed_manifest'])['selected']
    require(len(entries)==1 and [x['sha256']for x in entries]==frozen['source_order']
            and config['run']['targets']=={'financial_modeling':0,'debugging':1}
            and {k:config['run'].get(k)for k in PROTECTED_BUDGETS}==frozen['protected_budgets'],
            'The V3 source selection, quota or normal repair/evidence budgets changed')
    for entry in entries:
        require(validate_seed(entry,config[SETTING])==entry['finance_evidence']['audited_source_binding'],
                'The V3 source, financial admission or engineering receipt changed')
    return frozen


def execute_prepared(output,*,port=0):
    output=Path(output).resolve();frozen=validate_prepared(output)
    settings,legacy=cohort.prepared_host_runtime(output)
    with cohort.host_temporary_environment(output,settings,legacy_preparation=legacy)as host:
        config=yaml.safe_load((output/'resolved_config.yaml').read_text())
        require(not(output/'run.sqlite').exists(),'This immutable V3 quality run has already started')
        lease=cohort.ProducerLease(output).acquire();audit=None;server=None;started=time.monotonic();status=1
        try:
            audit=cohort.AuditStore(output,{'id':output.name,'target_count':1,'financial_target':0,'debugging_target':1,
                'development_only':True,'model':config['agents']['model'],'reasoning_effort':config['agents']['reasoning_effort'],
                'difficulty_status':'pending','status':'preflight'})
            server=cohort.DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=port);url=server.start()
            revision=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
            audit.update_run(dashboard_url=url,producer_pid=os.getpid(),producer_active=True,code_revision=revision,
                host_temporary_directory=host['temporary_directory'],host_runtime_receipt=host)
            llm=cohort.CohortCodex(ROOT,output,audit,config['agents']);llm._credentials()
            engine=cohort.LibreOfficeEngine(ROOT,cohort.IMAGE,config['engine']['timeout_seconds'])
            require(engine.metadata()['image_id']==cohort.IMAGE_ID,'V3 normal quality runtime differs')
            print(json.dumps({'run_dir':str(output),'dashboard_url':url,'development_only':True,'provider':PROVIDER_ID}),flush=True)
            status=0 if SemanticGraphFactory(config,audit,llm,engine).run()else 2
            for path,digest in frozen['recipe_sha256'].items():require(sha(path)==digest,'V3 recipe changed during execution')
            return status
        finally:
            if audit is not None:
                adapted.finalize_execution(audit,server,None,lease,phase_wall=round(time.monotonic()-started,3),previous_wall=0,status=status)
            else:lease.release()


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path)
    p.add_argument('--engineering-receipt',type=Path);p.add_argument('--prepared',type=Path)
    p.add_argument('--run',action='store_true');p.add_argument('--port',type=int,default=0)
    a=p.parse_args(argv)
    if a.prepared:
        if a.output or a.engineering_receipt:p.error('--prepared cannot be combined with new preparation inputs')
        output=a.prepared
    else:
        if not a.output or not a.engineering_receipt:p.error('Preparation requires --output and --engineering-receipt')
        output=a.output;print(json.dumps(prepare(output,a.engineering_receipt)),flush=True)
    if a.run:raise SystemExit(execute_prepared(output,port=a.port))

if __name__=='__main__':main()
