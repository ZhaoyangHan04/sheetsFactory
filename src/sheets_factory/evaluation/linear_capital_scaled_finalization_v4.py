"""Read-only whole-root checks before an append-only final qualification receipt.

This module never executes Harbor. Root controls must already have completed
under the exact recorded commands, with genuine actual role observations.
The delivered pending manifest is retained as historical evidence.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from functools import lru_cache
from types import ModuleType

from . import linear_capital_scaled_publication_v4 as publication
from .resource_observer import validate_trial_observations
from ..reporting import read_run

require, reference, checked, read = publication.require, publication.reference, publication.checked, publication.read
ROOT = Path(__file__).resolve().parents[3]
AUDITOR_SHA256 = '2b1e7b6189d1efd7affea50cec49e8994c8e69ec7489043b652580b495990e08'
COMMANDS={a:['harbor','run','-p','SpreadsheetEval','-a',a] for a in ('oracle','nop')}
PENDING_TEXT = '''
## N360 prospective v4 release status

Confirmation passed. Final twenty-task qualification is pending the complete
root oracle and nop jobs, their actual resource evidence, and finalization.
`final20_qualified=False` remains in the retained delivery manifest.

Run from the repository root:

```sh
harbor run -p SpreadsheetEval -a oracle
harbor run -p SpreadsheetEval -a nop
```

A zero exit code alone does not qualify the release. Every one of the twenty
task results, delivered byte hashes and actual agent/verifier resource records
must pass the final read-only audit.
'''


@lru_cache(maxsize=1)
def resource_auditor():
    """Keep the entire existing root-job audit with the explicit17-file export.

    The original auditor is for standard13-file tasks. Its full trial, checksum,
    aggregate and error checks run unchanged in this private resource namespace.
    """
    tree=publication.template._frozen_ast(ROOT/'scripts/audit_harbor_job.py',AUDITOR_SHA256)
    module=ModuleType('_N360_v4_resource_root_job_auditor');module.__file__=str(ROOT/'scripts/audit_harbor_job.py')
    exec(compile(tree,module.__file__,'exec'),module.__dict__)
    module.EXPORT_FILES=publication.native.TASK_FILES
    module.inspect_export=publication.inspect_resource_export
    return module.audit_harbor_job


def _check_command(record,agent,root,dataset_ref):
    value=checked(record)
    require(value.get('kind')=='executed_exact_root_harbor_control' and type(value.get('version')) is int and value['version']==1
        and value.get('argv')==COMMANDS[agent] and value.get('cwd')==str(root)
        and type(value.get('returncode')) is int and value['returncode']==0
        and value.get('dataset_manifest')==dataset_ref,
        'The exact completed root command, zero exit and original delivery manifest must be recorded')
    start=datetime.fromisoformat(value['started_at'].replace('Z','+00:00'));finish=datetime.fromisoformat(value['finished_at'].replace('Z','+00:00'))
    require(start.tzinfo is not None and finish.tzinfo is not None and start<=finish,'Root command time window is incomplete')
    receipts=value.get('resource_observation_receipts')
    require(isinstance(receipts,list) and receipts,'Actual root-control resource observations are required')
    for receipt in receipts:checked(receipt)
    job=Path(value.get('job_directory','')).absolute()
    require(job==job.resolve() and job.is_dir(),'The exact completed root job must remain available')
    require(value.get('job_result')==reference(job/'result.json'),'The recorded command names a different actual root job')
    return value,start,finish


def validate_root_controls(root,command_records,*,auditor=None,resource_validator=None):
    """Reopen all20 results/bytes and both actual roles; no exit-code shortcut."""
    root=Path(root).absolute();require(root==root.resolve(),'A real repository root is required')
    dataset=root/'SpreadsheetEval';manifest_ref=reference(dataset/'dataset_manifest.json');manifest=checked(manifest_ref)
    require(manifest.get('final20_qualified') is False and manifest.get('final_root_controls_pending') is True
        and manifest.get('reference_evidence_policy')=='reference_review'
        and manifest.get('task_count')==20 and manifest.get('counts_by_mode')=={'financial_modeling':10,'debugging':10},
        'The exact pending twenty-task N360 delivery is required')
    require(set(command_records)=={'oracle','nop'},'Both exact root command receipts are required')
    if auditor is None:
        auditor=resource_auditor()
    resource_validator=resource_validator or validate_trial_observations
    results=[];all_refs=[manifest_ref]
    task_map={t['task_id']:t for t in manifest['tasks']}
    require(len(task_map)==20 and set(task_map)==set(manifest['selected_task_ids']),'The full delivery task set differs')
    for agent in ('oracle','nop'):
        record=command_records[agent]
        if not isinstance(record,dict):record=reference(record)
        command,start,finish=_check_command(record,agent,root,manifest_ref)
        job=Path(command['job_directory'])
        audit=auditor(dataset,job,agent=agent,command_cwd=root,output=None)
        require(audit.get('status')=='passed' and audit.get('agent')==agent
            and audit.get('dataset_manifest_sha256')==manifest_ref['sha256']
            and audit.get('counts')=={'dataset_tasks':20,'trial_results':20,'matched_rewards':20,'exceptions':0,'missing':0,'unknown':0,'duplicates':0}
            and audit.get('counts_by_mode')==manifest['counts_by_mode'], 'The actual root job does not completely pass all twenty delivered tasks')
        trials=audit.get('trials',[])
        require(len(trials)==20 and {t['task_id'] for t in trials}==set(task_map),'Root trial set differs from the complete declared cohort')
        observations=[]
        for trial in trials:
            result=reference(trial['result_file']);actual=checked(result);config=reference(Path(result['path']).parent/'config.json')
            actual_start=datetime.fromisoformat(actual['started_at'].replace('Z','+00:00'));actual_finish=datetime.fromisoformat(actual['finished_at'].replace('Z','+00:00'))
            require(start<=actual_start<=actual_finish<=finish,'The actual trial is outside its recorded root command window')
            expected=root/'SpreadsheetEval'/trial['task_id']
            observation=resource_validator(config,result,receipts=command['resource_observation_receipts'],expected_task_directory=expected)
            require(observation.get('passed') is True and observation.get('complete') is True,
                'An actual root oracle/nop agent or verifier resource proof is missing or mismatched')
            observations.append({'task_id':trial['task_id'],'result':result,'configuration':config,'resources':observation})
            all_refs.extend([result,config])
        all_refs.extend([record,command['job_result'],*command['resource_observation_receipts']])
        results.append({'agent':agent,'command':record,'whole_job_audit':audit,'actual_role_observations':observations})
    for record in all_refs:require(reference(record['path'])==record,'Original root-control evidence changed during finalization')
    return {'kind':'linear_capital_scaled_v4_complete_root_control_check','version':1,'passed':True,
        'dataset_manifest':manifest_ref,'task_count':20,'counts_by_mode':manifest['counts_by_mode'],
        'exact_commands':COMMANDS,'root_controls':results,'evidence':all_refs,'services_started':0}


def revalidate_confirmation(backend,selection_path,evaluation_path):
    """Repeat the generic all12/Harbor/full-trace gates after root jobs finish."""
    root=backend.root;tracked={};private_scopes={};publisher=backend.publisher
    _,frozen_path,frozen,validated,sources,_=backend.load_selection(root,None,None,selection_path,tracked,
        publisher._credential_values(root),private_scopes)
    confirmation=publisher._validate_confirmation(evaluation_path,frozen_path,frozen,validated,tracked,backend=backend)
    require(len(validated)==20 and confirmation['task_count']==20 and confirmation['overall_pass_at_1']<=.2,
        'The original whole20 fresh confirmation must still pass without unknowns')
    path=root/'SpreadsheetEval/dataset_manifest.json';manifest=checked(reference(path))
    require(manifest['confirmation']==confirmation and manifest['selected_task_ids']==[v['task_id'] for v in validated],
        'The delivered confirmation manifest differs from freshly recomputed original evidence')
    for item in validated:
        actual=next(t for t in manifest['tasks'] if t['task_id']==item['task_id'])
        require(all(actual[k]==item[k] for k in ('mode','source_id','revision','revision_hash','harbor_export_binding','payload_files')),
            'Delivered task metadata differs from its original normal qualification')
        require(backend.inspect_export(root/'SpreadsheetEval'/item['task_id'])==item['harbor_export_binding'],
            'Delivered root payload differs from the confirmed exact seventeen files')
    runtime,_=publisher._prepare_runtime(root,Path(backend.cohort['tasks'][0]['source_run']),validated,tracked,
        publisher._credential_values(root),backend=backend)
    require(all((root/name).read_bytes()==raw for name,raw in runtime.items()),'The delivered pinned runtime changed')
    for scope,files in private_scopes.items():
        for file,digest in files.items():require(hashlib.sha256(backend.release._file(file,scope,{})).hexdigest()==digest,'Complete private quality evidence changed')
    backend.recheck_tracked(tracked);backend.final_recheck()
    return confirmation


def finalize(cohort,selection,evaluation,command_records,output,*,project_root=ROOT,write_receipt=False):
    """Default is read-only. An explicit finalize writes only a new receipt.

The original pending delivery manifest remains immutable. The final receipt is
the qualification authority and binds the root README containing exact commands.
"""
    root=Path(project_root).resolve();backend=publication.ResourcePublicationBackend(cohort,project_root=root)
    confirmation=revalidate_confirmation(backend,selection,evaluation)
    controls=validate_root_controls(root,command_records)
    readme_ref=reference(root/'README.md');text=(root/'README.md').read_text()
    require(all(' '.join(argv) in text for argv in COMMANDS.values()),'Root README must contain both exact delivered-dataset commands')
    receipt={'kind':'linear_capital_scaled_v4_final_twenty_qualification','version':1,'final20_qualified':True,
        'qualified_at':datetime.now(timezone.utc).isoformat(),'cohort':reference(cohort),'selection':reference(selection),
        'evaluation':reference(evaluation),'confirmation':confirmation,'root_controls':controls,'root_README':readme_ref,
        'retained_pending_dataset_manifest':reference(root/'SpreadsheetEval/dataset_manifest.json'),
        'reference_evidence_policy':'reference_review','public_solver_required':False,'historical_scores_migrated':False,'services_started':0}
    backend.final_recheck();require(reference(root/'README.md')==readme_ref,'The final README changed during finalization')
    if write_receipt:
        output=Path(output).absolute();require(output==output.resolve() and not output.is_relative_to(root/'SpreadsheetEval'),
            'Write the append-only qualification receipt outside the immutable dataset')
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('x') as stream:json.dump(receipt,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n')
        return reference(output)
    return {'status':'validated_read_only','final20_qualified':False,'qualification_ready':True,
        'qualification_receipt_not_written':True,'prospective_receipt':receipt}
