#!/usr/bin/env python3
"""Prepare a public-precedence continuation; execute only with explicit --run."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
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
from sheets_factory.task_adapters.public_input_priority import (
    POLICY, RULE, audit_source, canonical, checked, read, ref, require, sha, validate_source_record, write)
from sheets_factory.reporting import read_run
from sheets_factory.resume import ProducerLease, assert_resume_allowed, prepare_resume, PROTECTED_BUDGETS
from sheets_factory.evaluation.harbor import inspect_export


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/filename)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


cohort = load_script('_priority_cohort', 'run_composite_quality_cohort.py')
adapted = load_script('_priority_cleanup', 'run_adapted_debug_quality.py')
REGISTRY = ROOT/'config/task_adapters/public_input_priority_nodes.yaml'
DEFAULT_STRONG_MANIFESTS = (
    ROOT/'outputs/research/financial_cohort_early_probe_20261030T164013Z/probe_manifest.json',
    ROOT/'outputs/research/lease_family_v2_evaluation_contract_20261030T164650Z/probe_manifest.json')


def validate_registry():
    original = yaml.safe_load((ROOT/'config/nodes.yaml').read_text())['nodes']
    selected = yaml.safe_load(REGISTRY.read_text())['nodes']
    require(set(original) == set(selected), 'Priority registry omitted or added nodes')
    require(all(original[k] == selected[k] for k in original if k not in {'plan','repair'}),
            'Priority registry changed a mandatory node')
    require(selected['plan'] == 'sheets_factory.task_adapters.public_input_priority:PriorityPlanNode'
            and selected['repair'] == 'sheets_factory.task_adapters.public_input_priority:PriorityRepairNode',
            'Priority registry wrappers differ')


def original_recipe(run):
    frozen = json.loads((run/'preflight_manifest.json').read_text())
    for group in ('recipe_sha256','source_artifacts_sha256'):
        for path, expected in frozen[group].items():
            require(sha(path) == expected, 'Original main recipe or source changed: '+path)
    checked(frozen['prepared_seed_manifest'])
    return frozen


def strong_bindings(manifests):
    result, exports = {}, []
    for path in manifests:
        path = Path(path).resolve();result[str(path)] = sha(path)
        document = json.loads(path.read_text())
        for location, expected in document.get('source_artifacts_sha256',{}).items():
            require(sha(location) == expected, 'Existing strong snapshot artifact changed: '+location)
            result[location] = expected
        for task in document.get('tasks',[]):
            directory = Path(task['task_directory']).resolve()
            require(inspect_export(directory) == task['harbor_export_binding'], 'Existing strong task export changed')
            for artifact in directory.rglob('*'):
                if artifact.is_file():result[str(artifact)] = sha(artifact)
            exports.append({'task_directory':str(directory),'binding':task['harbor_export_binding']})
    return result,exports


def review_issue(task, revision, revision_hash, record_ref):
    return {'issue_id':task+'-Q02-PUBLIC-INPUT-PRIORITY','task_id':task,'revision':revision,
        'revision_hash':revision_hash,'problem_id':'Q02','certainty':'confirmed','severity':'blocker',
        'attribution':'task_defect','route_id':'R02','claim':'The labelled and JSON claim-lag input differs from the narrative default; an explicit public precedence rule is required.',
        'evidence':[record_ref], 'depends_on_issue_ids':[]}


def program_only_diagnosis(task, revision, revision_hash, issue):
    ids = [f'Q{i:02d}' for i in range(1,13)]
    return {'kind':'program_only_public_contract_repair_basis','program_only':True,
        'task_id':task,'revision':revision,'task_revision_hash':revision_hash,'releasable':False,
        'diagnostic_stage':'program_only_repair_basis','issues':[issue],
        'assessments':{i:{'state':'flagged' if i=='Q02' else 'unknown',
            'reason':'Program-confirmed public claim-lag conflict' if i=='Q02' else 'No quality finding is asserted by this repair basis'} for i in ids},
        'coverage':{'enabled_count':12,'assessed_count':1,'unknown_check_ids':[i for i in ids if i!='Q02'],
                    'blocking_issue_ids':[issue['issue_id']],'undispositioned_warning_ids':[]},
        'quality_recovery_or_difficulty_pass_claimed':False}


def counterexample_authorization(task, diagnosis_ref, source_sha, audits, output):
    diagnosis = read(diagnosis_ref)
    related = [i['issue_id'] for i in diagnosis.get('issues',[]) if i.get('problem_id')=='Q04' and i.get('certainty')=='confirmed'
               and any(t in i.get('claim','').lower() for t in ('fixed point','fixed-point','non-unique','nonunique'))]
    if not related:return None
    matches = []
    for path in audits:
        document = json.loads(Path(path).read_text())
        inputs = document.get('inputs_and_implementations',[])
        if document.get('kind') == 'readonly_C01_economic_counterexample_audit' and diagnosis_ref in [
                {'path':i['path'],'sha256':i['sha256']} for i in inputs] and any(
                i['sha256']==source_sha and Path(i['path']).name=='goal.xlsx' for i in inputs):
            residuals = document.get('2036_claim_residuals_JSON',{})
            require(document.get('source_JSON_lag1_twenty_years_recomputed_and_equal_original_full_proofs') is True
                    and len(residuals)==2 and all(float(v)!=0 for v in residuals.values()), 'Counterexample audit is incomplete')
            for record in inputs:checked(record)
            for record in document.get('outputs',{}).values():checked(record)
            matches.append(ref(path))
    require(len(matches)==1, 'Existing Q04 requires an exact source/revision/diagnosis-bound numeric counterexample review')
    review = {'source_sha256':source_sha,'diagnosis_sha256':diagnosis_ref['sha256'],'related_issue_ids':related,
        'Q04_counterexample_does_not_establish_source_nonuniqueness':True,'numeric_counterexample_audit':matches[0],
        'old_Q04_cleared':False,'new_revision_full_reference_review_required':True}
    path=output/'tasks'/task/'counterexample_review.json';write(path,review)
    return ref(path)


def prepare(run, source_scan, output, *, counterexample_audits=(), strong_manifests=()):
    output=Path(output).resolve()
    require(not output.exists(),'Public-priority preparation requires a fresh output directory')
    settings=cohort.host_runtime_settings(output)
    output.mkdir(parents=True)
    with cohort.host_temporary_environment(output,settings) as host:
        return _prepare(run,source_scan,output,counterexample_audits=counterexample_audits,
                        strong_manifests=strong_manifests,preparation_host=host)


def _prepare(run, source_scan, output, *, counterexample_audits=(), strong_manifests=(),preparation_host=None):
    run=Path(run).resolve();output=Path(output).resolve();source_scan=ref(source_scan)
    validate_registry();old_frozen=original_recipe(run)
    config_path=run/'resolved_config.yaml';config_text=config_path.read_text();config=yaml.safe_load(config_text)
    require(config['run']['targets']=={'financial_modeling':10,'debugging':10},'Keep the original10+10 targets')
    snapshot=read_run(run)
    source_entries={}
    for location in [config['run']['seed_manifest'],*config['run'].get('additional_seed_manifests',[])]:
        location=Path(location);location=location if location.is_absolute() else ROOT/location
        for seed in json.loads(location.read_text())['selected']:source_entries[seed['sha256']]=seed
    strong,export_bindings=strong_bindings([*DEFAULT_STRONG_MANIFESTS,*strong_manifests])
    sources={}
    for identity,seed in source_entries.items():
        proof=cohort.validate_seed(seed)
        require(proof==seed.get('finance_evidence',{}).get('audited_source_binding'),'Original source admission binding changed')
        sources[identity]=audit_source(seed,source_scan,output/'sources'/identity[:12])
    tasks,missing,reviews={},[],[]
    for task in snapshot['tasks']:
        identity=task.get('source_id');record=validate_source_record(sources[identity])
        if not record['confirmed_conflict']:continue
        task_id=task['id'];revision=int(task.get('revision',0));private=run/'tasks'/task_id/'revisions'/f'{revision:03d}'/'private'
        public=private.parent/'public';baseline=run/'sources'/identity[:12]/'baseline.xlsx'
        artifacts={'plan':private/'plan.json','baseline':baseline,'goal':private/'goal.xlsx',
                   'input':public/'input.xlsx','instruction':public/'instruction.md'}
        require(all(p.is_file() for p in artifacts.values()),'A created task lacks complete construction artifacts: '+task_id)
        require(sha(baseline)==sha(artifacts['goal'])==identity,'Priority clarification cannot change financial inputs or goal')
        revision_hash=hashlib.sha256(artifacts['input'].read_bytes()+artifacts['instruction'].read_bytes()).hexdigest()
        issue=review_issue(task_id,revision,revision_hash,sources[identity])
        review_path=output/'tasks'/task_id/'program_review.json';write(review_path,{'task_id':task_id,'revision':revision,
            'kind':'numbered_program_public_contract_review','issues':[issue],'rule':RULE,
            'source_sha256':identity,'numeric_reference_proof':record['numeric_reference_proof'],
            'quality_or_difficulty_certified':False})
        reviews.append(ref(review_path));diagnosis_path=private/'diagnosis.json'
        if diagnosis_path.exists():
            diagnosis_ref=ref(diagnosis_path)
            report=read(diagnosis_ref)
            require(report.get('task_revision_hash')==revision_hash,'Existing diagnostic public revision differs')
        else:
            template=output/'tasks'/task_id/'program_only_diagnosis.json'
            write(template,program_only_diagnosis(task_id,revision,revision_hash,issue))
            diagnosis_ref={'path':str(diagnosis_path),'sha256':sha(template)}
            missing.append({'target':diagnosis_ref,'template':ref(template),'task_id':task_id,'revision':revision})
            report=json.loads(template.read_text())
        counter=counterexample_authorization(task_id,diagnosis_ref,identity,counterexample_audits,output) if diagnosis_path.exists() else None
        allowed=[issue['issue_id']]
        for old_issue in report.get('issues',[]):
            if old_issue.get('certainty')!='confirmed':continue
            if old_issue.get('problem_id')=='Q02' and (counter or any(t in old_issue.get('claim','').lower()
                    for t in ('claim lag','collection lag','one-year','two-year'))):allowed.append(old_issue['issue_id'])
        auth={'revision':revision,'source_sha256':identity,'revision_hash':revision_hash,
            **{k:ref(v) for k,v in artifacts.items()},'diagnosis':diagnosis_ref,'program_review':ref(review_path),
            'authorized_issue_ids':list(dict.fromkeys(allowed))}
        if counter:auth['counterexample_review']=counter
        tasks[task_id]=auth
    require(tasks,'No created task has a program-confirmed public claim-lag conflict')
    manifest={'kind':'public_input_priority_binding','version':1,'rule':RULE,'sources':sources,'tasks':tasks,
              'source_scan':source_scan,'quality_or_difficulty_certified':False}
    write(output/'policy_binding.json',manifest)
    patch={'pipeline':{**config.get('pipeline',{}),'node_registry':str(REGISTRY)},
           POLICY:{'version':1,'rule':RULE,'manifest':ref(output/'policy_binding.json')}}
    write(output/'config_patch.json',patch)
    (output/'resolved_config_before.yaml').write_text(config_text)
    recipe={str(p):sha(p) for p in [Path(__file__).resolve(),REGISTRY,
        ROOT/'src/sheets_factory/task_adapters/public_input_priority.py',Path(cohort.__file__),Path(adapted.__file__)]}
    artifacts={str(p):sha(p) for p in output.rglob('*') if p.is_file()}
    require(config_path.read_text()==config_text,'Original configuration changed during preparation')
    original_recipe(run)
    frozen={'kind':'prepared_public_input_priority_continuation','prepared_at':datetime.now(timezone.utc).isoformat(),
        'run_directory':str(run),'original_preflight':ref(run/'preflight_manifest.json'),
        'resolved_config_before':ref(config_path),'new_recipe_sha256':recipe,'prepared_artifacts_sha256':artifacts,
        'original_recipe_sha256':old_frozen['recipe_sha256'],'strong_artifacts_sha256':strong,
        'strong_export_bindings':export_bindings,'repair_task_ids':list(tasks),'review_files':reviews,
        'missing_diagnoses':missing,'config_patch':ref(output/'config_patch.json'),
        'policy_manifest':ref(output/'policy_binding.json'),'targets':config['run']['targets'],
        'protected_budget_configuration':{k:config['run'].get(k) for k in PROTECTED_BUDGETS},
        'agents':config['agents'],'actual_models':0,'actual_LO_calls':0,'qualified':0,
        'preparation_host_runtime':preparation_host,
        'run_status_at_preparation':snapshot['run'].get('status'),'old_run_modified_by_preparation':False}
    write(output/'preflight_manifest.json',frozen)
    return frozen


def validate_prepared(output):
    output=Path(output).resolve();frozen=json.loads((output/'preflight_manifest.json').read_text())
    require(frozen.get('kind')=='prepared_public_input_priority_continuation','Unexpected public priority preparation')
    for group in ('new_recipe_sha256','prepared_artifacts_sha256','original_recipe_sha256','strong_artifacts_sha256'):
        for path,expected in frozen[group].items():require(sha(path)==expected,'Frozen priority continuation artifact changed: '+path)
    checked(frozen['resolved_config_before']);checked(frozen['original_preflight']);validate_registry()
    for item in frozen['strong_export_bindings']:
        require(inspect_export(item['task_directory'])==item['binding'],'Original strong export binding changed')
    manifest=read(frozen['policy_manifest'])
    for record in manifest['sources'].values():validate_source_record(record)
    for task,auth in manifest['tasks'].items():
        for key in ('plan','baseline','goal','input','instruction','program_review'):checked(auth[key])
        missing=next((m for m in frozen['missing_diagnoses'] if m['task_id']==task),None)
        if missing:require(not Path(auth['diagnosis']['path']).exists(),'Prepared missing diagnosis now exists; prepare a new admission')
        else:checked(auth['diagnosis'])
    return frozen


def execute(output, *, port=0):
    output=Path(output).resolve();frozen=validate_prepared(output);run=Path(frozen['run_directory'])
    # Preparation never takes the lease. Explicit execution must find a drained
    # terminal producer before even materializing a previously absent diagnosis.
    with ProducerLease(run):
        snapshot=read_run(run);assert_resume_allowed(run,snapshot)
        current={t['id']:t for t in snapshot['tasks']}
        manifest=read(frozen['policy_manifest'])
        for task,auth in manifest['tasks'].items():
            require(current[task].get('revision',0)==auth['revision'],'Task revision changed after preparation')
        for missing in frozen['missing_diagnoses']:
            require(current[missing['task_id']].get('status')=='cancelled','Only cancelled tasks may get a missing program-only diagnosis')
            target=Path(missing['target']['path']);require(not target.exists(),'Never overwrite an existing diagnosis')
            raw=checked(missing['template']).read_bytes()
            with target.open('xb') as stream:stream.write(raw)
            require(sha(target)==missing['target']['sha256'],'New program-only diagnosis bytes differ')
        materialization=run/'runtime_supplements'/('priority_program_basis_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
        write(materialization,{'kind':'new_program_only_repair_bases','preparation':ref(output/'preflight_manifest.json'),
            'created':[m['target'] for m in frozen['missing_diagnoses']],'old_diagnoses_overwritten':False})
    settings,legacy=cohort.prepared_host_runtime(run)
    with cohort.host_temporary_environment(run,settings,legacy_preparation=legacy) as host:
        patch=read(frozen['config_patch'])
        revision=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
        session=prepare_resume(run,config_patch=patch,repair_tasks=frozen['repair_task_ids'],
            review_files=[r['path'] for r in frozen['review_files']],current_code_revision=revision,
            reason='Clarify public numerical-input precedence through new revisions; preserve original financial source, targets and budgets')
        audit,config,lease=session.audit,session.config,session.lease
        server,status,started=None,1,time.monotonic();previous=audit.run.get('wall_seconds',0) or 0
        try:
            require(config['run']['targets']==frozen['targets'] and config['agents']==frozen['agents']
                and all(config['run'].get(k)==v for k,v in frozen['protected_budget_configuration'].items()),'Continuation changed quota, agents or budget configuration')
            private=run/'private/resume';cid=config['run']['continuation_id']
            before=private/f'resolved_config_before_{cid}.yaml';after=private/f'resolved_config_after_{cid}.yaml'
            addendum={'kind':'public_input_priority_continuation','rule':RULE,'preparation':ref(output/'preflight_manifest.json'),
                'config_before':ref(before),'config_after':ref(after),'current_resolved_config':ref(run/'resolved_config.yaml'),
                'original_preparation_config_hash_is_historical':True,'repair_task_ids':frozen['repair_task_ids'],
                'original_recipe_unchanged':True,'strong_snapshots_unchanged':True,'budget_configuration_unchanged':True,
                'new_revisions_consume_normal_content_repair_budget':True,'old_diagnostics_cleared':False,'qualified':0}
            path=run/'runtime_supplements'/('public_priority_continuation_'+cid+'.json');write(path,addendum)
            audit.emit('run.public_input_priority',addendum=ref(path))
            server=cohort.DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=port);url=server.start()
            audit.update_run(dashboard_url=url,host_temporary_directory=host['temporary_directory'],host_runtime_receipt=host)
            llm=cohort.CohortCodex(ROOT,run,audit,config['agents']);llm._credentials()
            engine=cohort.LibreOfficeEngine(ROOT,cohort.IMAGE,config['engine']['timeout_seconds'])
            require(engine.metadata()['image_id']==cohort.IMAGE_ID,'Public priority phase runtime differs')
            print(json.dumps({'run_dir':str(run),'dashboard_url':url,'phase_addendum':str(path)}),flush=True)
            status=0 if cohort.AuditedSourceFactory(config,audit,llm,engine).run() else 2
            original_recipe(run)
            for path,expected in frozen['strong_artifacts_sha256'].items():require(sha(path)==expected,'Original strong snapshot changed')
            return status
        finally:
            adapted.finalize_execution(audit,server,session,lease,phase_wall=round(time.monotonic()-started,3),previous_wall=previous,status=status)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory',type=Path);parser.add_argument('--source-audit',type=Path)
    parser.add_argument('--output',type=Path);parser.add_argument('--prepared',type=Path)
    parser.add_argument('--counterexample-audit',type=Path,action='append',default=[])
    parser.add_argument('--strong-manifest',type=Path,action='append',default=[])
    parser.add_argument('--run',action='store_true');parser.add_argument('--port',type=int,default=0)
    args=parser.parse_args(argv)
    if args.prepared:
        require(not any((args.run_directory,args.source_audit,args.output,args.counterexample_audit,args.strong_manifest)),
            'Prepared continuation cannot replace its frozen bindings')
        output=args.prepared;validate_prepared(output)
    else:
        require(args.run_directory and args.source_audit and args.output,'Preparation requires run directory, source audit and fresh output')
        output=args.output;prepare(args.run_directory,args.source_audit,output,
            counterexample_audits=args.counterexample_audit,strong_manifests=args.strong_manifest)
    if args.run:return execute(output,port=args.port)
    print(json.dumps({'prepared':str(output.resolve()),'models_started':0,'qualified':0}),flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
