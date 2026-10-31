#!/usr/bin/env python3
"""Prepare one source-bound business FM quality run; services require --run."""
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

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.task_adapters import heterogeneous_business_modeling as adapter
from sheets_factory.pipelines.heterogeneous_business_quality import (
    ProjectionAdmission, HeterogeneousBusinessFactory, TARGETS, METHOD, SOURCE_KIND,
    validate_configuration, validate_seed)
from sheets_factory.resume import PROTECTED_BUDGETS
from sheets_factory.workbook.resource_engine import ResourceLibreOfficeEngine
from sheets_factory.evaluation.resource_observer import ResourceObserver

KIND = 'prepared_first_heterogeneous_v3_business_FM_normal_quality'
reference, require = adapter.reference, adapter.require
BUSINESS_PROMPT = ROOT / 'prompts/diagnosis_business.md'
APPROVED_PROMPT_OLD_SHA = '094145b533e9d59e178d0565d5457272d85d93e7deaba1f5dd11a2616d250a45'
APPROVED_PROMPT_CURRENT_SHA = 'c8dd6123a6fc3847037fdc6e070867d9174ca9ee01f89bfcf61521c938a96e48'


def support(filename):
    path = ROOT / 'scripts' / filename
    definition = importlib.util.spec_from_file_location('_business_quality_' + path.stem, path)
    module = importlib.util.module_from_spec(definition); definition.loader.exec_module(module)
    return module


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream: json.dump(value, stream, ensure_ascii=False, indent=2); stream.write('\n')
    return reference(path)


def verify_files(mapping):
    for path, digest in mapping.items():
        require(reference(path)['sha256'] == digest, 'A frozen quality dependency changed: ' + path)


def checked_base_configuration(base_run):
    """Admit the frozen configuration with one explicit approved prompt rebase.

    This does not transfer any old source or task quality. Every other recipe
    dependency retains its original exact-SHA requirement.
    """
    base_run = Path(base_run).absolute()
    preflight = reference(base_run/'preflight_manifest.json')
    original = adapter.base._read(preflight['path'])
    require(reference(BUSINESS_PROMPT)['sha256'] == APPROVED_PROMPT_CURRENT_SHA,
        'The explicitly approved current business diagnosis prompt changed')
    rebases = []
    for path, expected in original['recipe_sha256'].items():
        actual = reference(path)
        if actual['sha256'] == expected: continue
        require(path == str(BUSINESS_PROMPT) and expected == APPROVED_PROMPT_OLD_SHA
            and actual['sha256'] == APPROVED_PROMPT_CURRENT_SHA,
            'A nonapproved frozen base recipe dependency changed: '+path)
        rebases.append({'path':path,'old_expected_sha256':expected,
            'new_actual_sha256':actual['sha256'],'current_artifact':actual,
            'scope':'configuration_and_normal_recipe_only',
            'historical_source_or_task_quality_transferred':False})
    config_ref = reference(base_run/'resolved_config.yaml')
    config = yaml.safe_load(Path(config_ref['path']).read_text())
    require(config['agents']['model'] == 'gpt-6-sol' and config['agents']['reasoning_effort'] == 'high'
        and config['diagnosis']['selection'] == {'include':'all','exclude':[]}
        and config['harbor']['execute_controls'] is True,
        'The original normal configuration, full checks and actual Harbor controls are required')
    return preflight,original,config_ref,config,rebases


def prepare(projection_manifest, base_run, output, *, runtime_profile=adapter.PROFILE):
    out = Path(output).absolute()
    require(out == out.resolve() and not out.exists(), 'Use a fresh private quality output directory')
    admission = ProjectionAdmission(projection_manifest); proof = admission.guard()
    require(reference(runtime_profile) == proof['runtime_profile'], 'Source, projection and task resource profiles must match')
    base_ref, original, base_config_ref, config, rebases = checked_base_configuration(base_run)
    protected = {key: config['run'].get(key) for key in PROTECTED_BUDGETS}
    for key in ('continuation_id','resume_existing_task_ids','external_repair_manifest','additional_seed_manifests','seed_path','source_filter'):
        config['run'].pop(key, None)
    for key in list(config):
        if key in ('project_root','run_dir') or key.startswith(('capital_', 'entity_group_', 'composite_',
                'full_state_', 'semantic_graph_', 'scc_', 'joint_', 'public_input_', 'pilot_')):
            config.pop(key, None)
    config.pop('public_workbook_scope', None)
    config[adapter.SETTING] = adapter.setting(runtime_profile)
    config.update(project_root=str(ROOT), run_dir=str(out))
    config['run'].update(name='first-heterogeneous-v3-business-FM-normal-quality', targets=deepcopy(TARGETS),
        seed_manifest=str(out/'seed_manifest.json'), max_sources=1, max_parallel_sources=1,
        max_candidates_per_seed=1, source_ordering='manifest', variant_modes=['financial_modeling'])
    config['agents'].update(max_parallel_calls=1, container_memory='32g', container_cpus=2)
    config['engine'].update(image='sheetsfactory-lo:24.2-iterative-openpyxl315-v1', timeout_seconds=600)
    config['construction'].update(instruction_style='business_brief')
    config['construction'].setdefault('max_edit_count', {})['financial_modeling'] = 200000
    config['construction']['analysis_limits'] = {'max_profile_cells':500000,'max_dependency_closure_cells':500000,
        'per_formula_reference_cells':5000,'max_mask_ranges':1024}
    config['pipeline'] = {**config.get('pipeline', {}),'node_registry':str(adapter.REGISTRY)}
    config['recovery'].update(compiler_backend=adapter.BACKEND,replay_timeout_seconds=7200)
    config['diagnosis'].update(reference_evidence_policy='independent_public_recovery',difficulty_deferred=False)
    config['diagnosis'].setdefault('execution', {})['reference_evidence_transport'] = 'audited_summary'
    config.setdefault('prompt_overrides', {})['diagnosis.md'] = 'diagnosis_business.md'
    require({key:config['run'].get(key) for key in PROTECTED_BUDGETS} == protected, 'Normal content/evidence/infrastructure budgets changed')
    validate_configuration(config)
    seed = {'local_path':proof['native_source']['path'],'sha256':proof['native_source']['sha256'],
        'source_kind':SOURCE_KIND,'source_manifest':proof['source_manifest'],'profile_id':'H01',
        'variant':0,'modes':['financial_modeling'],'finance_evidence':{
            'financial_seed_verified':True,'financial_modeling_eligible':True,'reference_method':METHOD,
            'source_manifest':proof['source_manifest'],'business_projection_admission':proof,
            'description':'Audited native financial model with a complete literal-valued public business forecast projection; all normal task quality remains pending.'}}
    validate_seed(seed, proof)
    out.mkdir(parents=True)
    proof_ref = write(out/'private/source_and_projection_admission.json',proof)
    seeds = write(out/'seed_manifest.json',{'unique_workbooks_inspected':1,'download_url':'local:audited-heterogeneous-business-projection',
        'archive_sha256':None,'selected':[seed],'qualified':False,'task_count':0})
    cohort = support('run_composite_quality_cohort.py')
    config['host_runtime'] = cohort.host_runtime_settings(out)
    recipes = deepcopy(original['recipe_sha256'])
    recipes.update({str(p):reference(p)['sha256'] for p in [Path(__file__),Path(adapter.__file__),adapter.REGISTRY,
        ROOT/'src/sheets_factory/pipelines/heterogeneous_business_quality.py',
        ROOT/'src/sheets_factory/workbook/heterogeneous_business_view_replay.py',
        ROOT/'src/sheets_factory/evaluation/resource_observer.py', ROOT/'scripts/run_adapted_debug_quality.py',
        BUSINESS_PROMPT,
        ROOT/'scripts/run_composite_quality_cohort.py', ROOT/'scripts/run_entity_group_quality.py']})
    recipes.update({value['path']:value['sha256'] for value in config[adapter.SETTING].values()
        if isinstance(value,dict) and {'path','sha256'} <= set(value)})
    with cohort.host_temporary_environment(out,config['host_runtime']) as host:
        (out/'resolved_config.yaml').write_text(yaml.safe_dump(config,sort_keys=False))
        admission.guard(); verify_files(recipes)
        return write(out/'preflight_manifest.json',{'kind':KIND,'version':1,'development_only':True,
            'projection_manifest':reference(projection_manifest),'source_admission':proof_ref,'prepared_seed_manifest':seeds,
            'resolved_config':reference(out/'resolved_config.yaml'),'protected_task_budgets':protected,
            'base_configuration_provenance':{'preflight':base_ref,'resolved_config':base_config_ref,
                'scope':'configuration_and_normal_recipe_only','prior_source_or_task_quality_transferred':False,
                'explicit_approved_recipe_rebases':rebases},
            'targets':TARGETS,'delivery_targets':{'financial_modeling':10,'debugging':10},'count':1,
            'recipe_sha256':recipes,'host_runtime':config['host_runtime'],'preparation_host_runtime':host,
            'runtime_profile':proof['runtime_profile'],'existing_development_score_transferred':False,
            'actual_models':0,'actual_LO_calls':0,'qualified':False,'task_count':0})


def validate_prepared(output):
    out = Path(output).absolute()
    frozen = json.loads((out/'preflight_manifest.json').read_text())
    require(frozen.get('kind') == KIND and type(frozen.get('version')) is int and frozen['version'] == 1
        and frozen.get('targets') == TARGETS and type(frozen.get('count')) is int and frozen['count'] == 1,
        'The fixed first normal business quality preparation is required')
    verify_files(frozen['recipe_sha256'])
    provenance = frozen['base_configuration_provenance']
    for key in ('preflight','resolved_config'):
        require(reference(provenance[key]['path']) == provenance[key], 'The frozen base configuration provenance changed')
    base_result = checked_base_configuration(Path(provenance['preflight']['path']).parent)
    require(base_result[4] == provenance['explicit_approved_recipe_rebases'],
        'The explicitly approved configuration-only recipe rebase changed')
    for key in ('resolved_config','source_admission','prepared_seed_manifest','projection_manifest'):
        require(reference(frozen[key]['path']) == frozen[key], 'A frozen preparation artifact changed')
    config = yaml.safe_load(Path(frozen['resolved_config']['path']).read_text())
    admission = ProjectionAdmission(frozen['projection_manifest'])
    require(json.loads(Path(frozen['source_admission']['path']).read_text()) == admission.guard(),
        'The full native source and actual projection admission changed')
    require(config['run_dir'] == str(out) and config['run']['seed_manifest'] == str(out/'seed_manifest.json')
        and config['pipeline']['node_registry'] == str(adapter.REGISTRY)
        and {key:config['run'].get(key) for key in PROTECTED_BUDGETS} == frozen['protected_task_budgets'],
        'The fresh routing, output or original normal budgets changed')
    validate_configuration(config)
    seeds = json.loads(Path(frozen['prepared_seed_manifest']['path']).read_text())['selected']
    require(len(seeds) == 1, 'Only the first fixed source is permitted')
    validate_seed(seeds[0],admission.proof)
    return frozen,config,admission


def execute_prepared(output, *, port=0):
    out = Path(output).absolute(); frozen,config,admission = validate_prepared(out)
    cohort, cleanup = support('run_composite_quality_cohort.py'), support('run_adapted_debug_quality.py')
    settings,legacy = cohort.prepared_host_runtime(out)
    with cohort.host_temporary_environment(out,settings,legacy_preparation=legacy) as host:
        require(not (out/'run.sqlite').exists(), 'A started producer requires an explicit reviewed continuation')
        lease = cohort.ProducerLease(out).acquire()
        try:
            require(not (out/'run.sqlite').exists(), 'Never reinitialize a previous audit')
            audit = cohort.AuditStore(out,{'id':out.name,'target_count':1,'financial_target':1,'debugging_target':0,
                'status':'preflight','model':config['agents']['model'],'reasoning_effort':config['agents']['reasoning_effort'],'development_only':True})
        except BaseException:
            lease.release(); raise
        server,status,started = None,1,time.monotonic()
        try:
            server = cohort.DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=port); url = server.start()
            audit.update_run(dashboard_url=url,producer_pid=os.getpid(),producer_active=True,
                host_temporary_directory=host['temporary_directory'],host_runtime_receipt=host)
            engine = ResourceLibreOfficeEngine(ROOT,frozen['runtime_profile']['path'],role='source',receipt_directory=out/'resource_receipts')
            engine.ensure_image()
            llm = cohort.CohortCodex(ROOT,out,audit,config['agents']); llm._credentials()
            print(json.dumps({'run_dir':str(out),'dashboard_url':url,'development_only':True}),flush=True)
            with ResourceObserver(out,job_dirs=[out/'harbor_jobs']) as observer:
                status = 0 if HeterogeneousBusinessFactory(config,audit,llm,engine,admission=admission).run() else 2
            if observer.receipt: write(out/'normal_Harbor_resource_observation.json',{'receipt':observer.receipt})
            admission.guard(); verify_files(frozen['recipe_sha256'])
            return status
        finally:
            try:
                cleanup.finalize_execution(audit,server,None,lease,phase_wall=round(time.monotonic()-started,3),previous_wall=0,status=status)
            finally: audit.db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--projection-manifest',type=Path); parser.add_argument('--base-run',type=Path)
    parser.add_argument('--output',type=Path); parser.add_argument('--prepared',type=Path)
    parser.add_argument('--runtime-profile',type=Path,default=adapter.PROFILE)
    parser.add_argument('--run',action='store_true'); parser.add_argument('--port',type=int,default=0)
    args = parser.parse_args(argv)
    if args.prepared:
        require(not any((args.projection_manifest,args.base_run,args.output)), 'Choose frozen validation or fresh preparation')
        if args.run: return execute_prepared(args.prepared,port=args.port)
        validate_prepared(args.prepared); result = {'validated':str(args.prepared),'models':0,'LO_calls':0}
    else:
        require(not args.run and all((args.projection_manifest,args.base_run,args.output)), 'Prepare and review before explicit --run')
        result = {'preflight':prepare(args.projection_manifest,args.base_run,args.output,runtime_profile=args.runtime_profile),'models':0,'LO_calls':0}
    print(json.dumps(result,indent=2)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
