#!/usr/bin/env python3
"""Freeze actual resource-family task bytes after six normal nodes and controls.

This helper performs no LO, model, or Harbor job. A pre-quality snapshot is not
an executed normal ExportNode or a qualified release.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import sys
from types import SimpleNamespace

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.evaluation.budget import validate_execution_budget,validate_selection_execution_budget
from sheets_factory.evaluation.tool_time_bounds import POLICY_V2
from sheets_factory.evaluation.streaming_delta import compare_workbooks
from sheets_factory.evaluation.resource_harbor import export_resource_harbor,inspect_resource_export,verify_local_base_image
from sheets_factory.evaluation.resource_frontier import TASK_FILES,MODEL,EFFORT
from sheets_factory.nodes.construction import InstructionNode
from sheets_factory.reporting import read_run
from sheets_factory.task_adapters.public_workbook_scope import CLAUSES,canonical,read as read_ref,reference,require,write_new
from sheets_factory.workbook.resource_engine import load_runtime_profile
from sheets_factory.pipelines.joint_repair_activity import validate_joint_certificate

NORMAL_NODES=('normalize','profile','plan','construct','instruction','precheck')
CONTROL_REWARDS={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}
BUDGET={'version':1,'elapsed_policy':'operational_guard','elapsed_guard_seconds':14400,'tool_budget_seconds':1800}
FAMILIES={'entity':('run_entity_group_quality.py','debugging','entity_group_policy_inventory.json'),
          'scaled_capital':('run_scaled_capital_quality.py','financial_modeling','scaled_capital_plan_binding.json')}


def read(path):return json.loads(Path(path).read_bytes())


def stream_reference(path):
    path=Path(path).absolute()
    require(path==path.resolve() and path.is_file(),'Probe artifact must be a regular real file')
    before=path.stat();digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024**2),b''):digest.update(block)
    after=path.stat()
    require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)
            ==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),
            'A probe artifact changed while it was hashed')
    return {'path':str(path),'sha256':digest.hexdigest(),'bytes':after.st_size}


def verify_files(mapping):
    for path,digest in mapping.items():
        require(stream_reference(path)['sha256']==digest,'A frozen resource-probe artifact changed: '+path)


def bind_receipt_references(value,mapping,visited=None):
    """Bind actual control-history leaves; never open the financial binding table."""
    visited=set() if visited is None else visited
    if isinstance(value,dict):
        if 'path' in value and 'sha256' in value:
            actual=stream_reference(value['path'])
            require(actual['sha256']==value['sha256']
                    and ('bytes' not in value or actual['bytes']==value['bytes']),
                    'A declared actual control-history artifact changed')
            require(actual['path'] not in mapping or mapping[actual['path']]==actual['sha256'],
                    'Conflicting actual control-history artifact identities')
            mapping[actual['path']]=actual['sha256']
            if actual['path'] not in visited and Path(actual['path']).suffix=='.json':
                visited.add(actual['path']);bind_receipt_references(read(actual['path']),mapping,visited)
        for child in value.values():bind_receipt_references(child,mapping,visited)
    elif isinstance(value,list):
        for child in value:bind_receipt_references(child,mapping,visited)


def phase_module(family):
    require(family in FAMILIES,'Choose the explicit entity or scaled_capital family')
    file=ROOT/'scripts'/FAMILIES[family][0]
    spec=importlib.util.spec_from_file_location('_resource_probe_'+family+'_phase',file)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def require_completed_nodes(snapshot,task_id,revision):
    latest={}
    for record in snapshot['nodes']:
        if record.get('task_id')==task_id and record.get('revision')==revision:
            latest[record.get('node',record.get('node_id'))]=record
    for name in NORMAL_NODES:
        require(latest.get(name,{}).get('status')=='completed',
                'A normal current-revision node has not completed: '+name)
    return latest


def model_selection_history(revision_hash,task_id,revision,directories):
    result=[];seen=set()
    for root in directories:
        root=Path(root)
        paths=[root] if root.is_file() else sorted(root.rglob('selection_manifest.json'))
        for path in paths:
            path=path.absolute()
            if str(path) in seen:continue
            seen.add(str(path));manifest=read(path)
            require(isinstance(manifest,dict) and isinstance(manifest.get('tasks'),list),
                    'A prior model selection is malformed; preserve and resolve it before a new selection')
            for task in manifest['tasks']:
                require(isinstance(task,dict),'Malformed historical selected task')
                same_hash=task.get('revision_hash')==revision_hash
                same_revision=task.get('task_id')==task_id and task.get('revision')==revision
                require(not same_hash and not same_revision,
                        'This task revision already has a model selection; do not resample it')
            result.append(stream_reference(path))
    return result


def validate_preparation(run,family):
    phase=phase_module(family);frozen,config,proof=phase.validate_prepared(run)
    seeds=read_ref(frozen['prepared_seed_manifest'])['selected']
    require(len(seeds)==1 and seeds[0].get('modes')==[FAMILIES[family][1]]
            and seeds[0]['finance_evidence']['audited_source_binding']==proof,
            'The normal family preparation must retain its complete single-source financial admission')
    return phase,frozen,config,seeds[0],proof


def validate_family_plan(family,phase,plan,application,scope,proof,goal,private):
    adapter=phase.adapter if hasattr(phase,'adapter') else __import__(
        'sheets_factory.task_adapters.entity_group',fromlist=['entity_group'])
    if family=='entity':expected=adapter.propose_from_checked_proof(goal,proof)
    else:expected=adapter._propose_from_checked_proof(goal,proof)
    require(plan.get('family_adapter')==expected['family_adapter']
            and adapter._physical(plan.get('edits',[]))==adapter._physical(expected['edits'])
            and application==plan['family_adapter'] and not plan.get('scenario_inputs') and 'mask_ranges' not in plan,
            'The complete normal family financial target or mutation inventory changed')
    require(CLAUSES[FAMILIES[family][1]] in plan.get('public_instruction',''),
            'The exact public worksheet and existing-cell scope is absent')
    helpers=set()
    if family=='entity':
        certificate=read(private/'joint_repair_certificate.json')
        summary=validate_joint_certificate(certificate,goal,private.parent/'public/input.xlsx',plan['edits'],scope)
        require(summary['complete_required_D_count']==scope['expected_change_count'],
                'The actual joint construction proof lacks complete D')
    else:
        binding=read_ref(proof['bindings'])
        adapter.audit_input_helper_caches(goal,private/'mutated_unrecalculated.xlsx',binding)
        helpers={row['sheet']+'!'+row['cell'] for row in binding['arithmetic_bindings']}
        count=sum(row.get('plan_dependent') is True for row in binding['arithmetic_bindings'])
        labels=[row['sheet']+'!'+row['cell'] for row in binding['arithmetic_bindings'] if row.get('plan_dependent') is True]
        require(scope.get('passed') is True and scope.get('masked_financial_and_decision_count')==25541
                and scope.get('provided_helper_formula_count')==51972
                and scope.get('plan_dependent_caches_cleared_count')==count
                and scope.get('cleared_support_coordinates_sha256')==canonical(labels)
                and scope.get('unselected_definitions_and_public_primitives_unchanged') is True
                and scope.get('helpers_physically_masked') is False and scope.get('helper_values_protected') is False
                and scope.get('no_helper_values_excluded_from_required_D') is True,
                'Actual normal masking, helper-cache clearance or complete scope is unproved')
        markdown=Path(proof['public_contract_artifacts']['candidate_contract_markdown']['path']).read_text()
        require(markdown in plan['public_instruction'],'The complete candidate/field contract is not public')
    return helpers


def resource_receipts(run,revision_dir,profile_ref,pairs):
    """Bind actual calculations, allowing byte-identical canonical control copies."""
    profile=load_runtime_profile(profile_ref['path']);requested=profile['docker_resources']['source']
    required={'cpus_nanoseconds':requested['cpus']*10**9,'memory_bytes':requested['memory_bytes'],'pids_limit':requested['pids_limit']}
    all_records=[]
    for path in sorted((run/'resource_receipts').glob('*.terminal.json')):
        record=read(path)
        if record.get('status')!='completed':continue
        output=record.get('output',{});destination=Path(record.get('destination','/nonexistent')).absolute()
        if not destination.is_relative_to(revision_dir):continue
        require(record.get('kind')=='resource_bound_libreoffice_call'
                and record.get('profile')==profile_ref and record.get('role')=='source'
                and record.get('image_id')==profile['image']['id']
                and isinstance(record.get('container_id'),str) and re.fullmatch(r'[0-9a-f]{64}',record['container_id'])
                and record.get('implementation')==reference(ROOT/'src/sheets_factory/workbook/resource_engine.py')
                and record.get('upstream_engine')==reference(ROOT/'src/sheets_factory/workbook/engine.py')
                and record.get('actual_resources_verified') is True and record.get('actual_resources')==required
                and record.get('requested_resources')==requested
                and record.get('workbook_file_timeout_seconds')==profile['timeouts']['workbook_file_seconds'],
                'An actual task calculation resource receipt differs from the approved profile')
        require(stream_reference(output['path'])==output
                and stream_reference(record['source']['path'])==record['source'],
                'An actual task calculation input or output artifact changed')
        all_records.append((stream_reference(path),record))
    matched=[]
    for name,raw,output in pairs:
        before,after=stream_reference(raw),stream_reference(output)
        matches=[ref for ref,record in all_records if record['source']['sha256']==before['sha256']
                 and record['output']['sha256']==after['sha256']]
        require(matches,'No actual inspected resource calculation binds this current normal artifact: '+name)
        matched.append({'name':name,'raw':before,'output':after,'actual_calculation_receipts':matches,
            'canonical_control_copy_may_have_a_different_path_but_exact_same_bytes':True})
    return matched


def _freeze_probe(run,task_id,revision,output,*,family,history_roots=()):
    require(family in FAMILIES,'Choose the explicit resource family')
    run,output=Path(run).absolute(),Path(output).absolute()
    require(run==run.resolve() and output==output.resolve() and not output.exists(),'Use a fresh real snapshot directory')
    require(isinstance(task_id,str) and Path(task_id).name==task_id and task_id not in ('.','..')
            and type(revision) is int and revision>=0,'Unsafe task identity or revision')
    snapshot=read_run(run);nodes=require_completed_nodes(snapshot,task_id,revision)
    phase,frozen,config,seed,proof=validate_preparation(run,family)
    tasks=[row for row in snapshot['tasks'] if row['id']==task_id]
    mode=FAMILIES[family][1]
    require(len(tasks)==1 and tasks[0].get('revision')==revision and tasks[0].get('mode')==mode
            and tasks[0].get('source_id')==seed['sha256'],'The actual current normal source/task identity differs')
    directory=run/'tasks'/task_id/'revisions'/f'{revision:03d}';public,private=directory/'public',directory/'private'
    source,goal=public/'input.xlsx',private/'goal.xlsx';instruction=(public/'instruction.md').read_text()
    require(stream_reference(goal)['sha256']==proof['workbook']['sha256']==seed['sha256'],
            'The normal goal differs from the actual audited source')
    plan=read(private/'plan.json');application=read(private/FAMILIES[family][2])
    delta=read(private/'expected_delta.json')
    scope=delta if family=='entity' else read(private/'scaled_capital_actual_input_scope.json')
    helpers=validate_family_plan(family,phase,plan,application,scope,proof,goal,private)
    if family=='scaled_capital':
        require(scope['input']==stream_reference(source) and scope['goal']==stream_reference(goal)
                and scope['actual_normal_draft']==stream_reference(private/'mutated_unrecalculated.xlsx'),
                'The full-D input cache audit is bound to another revision')
    revision_hash=hashlib.sha256(source.read_bytes()+instruction.encode()).hexdigest()
    require(tasks[0].get('revision_hash',revision_hash)==revision_hash,'The saved task revision binding changed')
    history=model_selection_history(revision_hash,task_id,revision,[ROOT/'outputs/difficulty',*history_roots])
    stored=read(private/'local_controls.json')
    require(set(stored)==set(CONTROL_REWARDS),'All five actual normal local controls are required')
    pairs=[('normal_input',private/'mutated_unrecalculated.xlsx',source)]
    for name,reward in CONTROL_REWARDS.items():
        candidate=goal if name=='oracle' else source if name=='nop' else private/'controls'/(name+'.xlsx')
        actual=compare_workbooks(source,goal,candidate)
        require(actual==stored[name] and type(actual.get('reward')) is int and actual['reward']==reward,
                'An actual normal full-workbook control failed or changed: '+name)
        if name not in ('oracle','nop'):pairs.append((name,private/'controls'/(name+'_raw.xlsx'),candidate))
    require(delta==stored['oracle'] and delta.get('structure_ok') is True
            and type(delta.get('expected_change_count')) is int and delta['expected_change_count']>0
            and len(delta['expected_changes'])==len(set(delta['expected_changes']))==delta['expected_change_count'],
            'The complete actual D is absent, inconsistent or reduced')
    if family=='scaled_capital':
        labels={e['sheet']+'!'+e['cell'] for e in plan['edits']}
        require(labels<=set(delta['expected_changes']) and scope.get('complete_required_D_count')==delta['expected_change_count']
                and scope.get('changed_helper_count')==len(helpers&set(delta['expected_changes'])),
                'Complete D omits a financial target or a changed arithmetic helper')
    require(read(private/'native_risk_guard.json')['blocking'] is False
            and read(private/'native_error_probe.json')['blocking'] is False,'A native calculation guard remains blocking')
    if family=='entity':
        for index,call in enumerate(read(private/'joint_repair_certificate.json')['engine_calls']):
            pairs.append(('joint_actual_'+str(index),Path(call['input']['path']),Path(call['output']['path'])))
    actual_resources=resource_receipts(run,directory,config[phase.adapter.SETTING]['runtime_profile'],pairs)
    fixed=[source,goal,public/'instruction.md',public/'profile.json',private/'plan.json',private/FAMILIES[family][2],
        private/'mutated_unrecalculated.xlsx',*[private/name for name in ('local_controls.json','expected_delta.json',
        'edit_validation.json','root_impacts.json','native_risk_guard.json','native_error_probe.json')],
        *[path for _,raw,candidate in pairs[1:] for path in (raw,candidate)],
        run/'preflight_manifest.json',run/'resolved_config.yaml',run/'seed_manifest.json',Path(__file__).resolve(),
        ROOT/'src/sheets_factory/evaluation/resource_frontier.py',ROOT/'src/sheets_factory/evaluation/frontier.py',
        ROOT/'src/sheets_factory/evaluation/resource_harbor.py',
        ROOT/'src/sheets_factory/evaluation/resource_streaming_verifier.py']
    if family=='entity':fixed.extend((private/'joint_repair_certificate.json',private/'joint_control_selection.json'))
    else:fixed.append(private/'scaled_capital_actual_input_scope.json')
    bindings={str(path):stream_reference(path)['sha256'] for path in fixed}
    bindings.update(frozen['recipe_sha256']);bindings.update(frozen['source_artifacts_sha256'])
    if family=='entity':
        bind_receipt_references([read(private/'joint_control_selection.json'),read(private/'joint_repair_certificate.json')],bindings)
    for row in actual_resources:
        for ref in row['actual_calculation_receipts']:bindings[ref['path']]=ref['sha256']
    output.mkdir(parents=True)
    normal=write_new(output/'normal_node_receipts.json',{'as_of':datetime.now(timezone.utc).isoformat(),
        'family':family,'task_id':task_id,'revision':revision,'run_status':snapshot['run']['status'],'nodes':nodes,
        'actual_calculation_resource_bindings':actual_resources,'new_LO_calls':0,'new_model_calls':0})
    replay=output/'normal_instruction_replay';(replay/'public').mkdir(parents=True)
    regenerated=InstructionNode().execute(SimpleNamespace(data={'plan':plan,'input':source},mode=mode,config=config,revision_dir=replay))
    require(regenerated['instruction'].encode()==(public/'instruction.md').read_bytes()
            and regenerated['revision_hash']==revision_hash,'Actual public instruction bytes differ from normal InstructionNode replay')
    actual_base=write_new(output/'actual_local_base_image.json',verify_local_base_image(config[phase.adapter.SETTING]['runtime_profile']['path']))
    target=output/'SpreadsheetEval'/task_id
    export_resource_harbor(directory,target,{'task_id':task_id,'mode':mode,'source_id':seed['sha256'],
        'source_file':Path(seed['local_path']).name,'revision':revision,'revision_hash':revision_hash,
        'difficulty_status':'prequality_development_probe','base_image':config['engine']['image']},
        config['project_root'],runtime_profile=config[phase.adapter.SETTING]['runtime_profile']['path'])
    export_binding=inspect_resource_export(target)
    require(export_binding.get('task_id')==task_id and export_binding.get('revision')==revision
            and export_binding.get('revision_hash')==revision_hash,'The resource export identity or revision differs')
    require((target/'instruction.md').read_bytes()==(public/'instruction.md').read_bytes()
            and stream_reference(target/'environment/input.xlsx')['sha256']==stream_reference(source)['sha256']
            and stream_reference(target/'tests/reference.xlsx')['sha256']==stream_reference(goal)['sha256'],
            'The resource snapshot export differs from actual normal task bytes')
    inventory={path.relative_to(target).as_posix():stream_reference(path) for path in target.rglob('*') if path.is_file()}
    require(set(inventory)==set(TASK_FILES) and len(inventory)==17,'The frozen resource task inventory is incomplete or contains extra files')
    for row in [normal,actual_base,stream_reference(replay/'public/instruction.md'),*inventory.values()]:bindings[row['path']]=row['sha256']
    verify_files(bindings)
    current=read_run(run)
    current_task=next(row for row in current['tasks'] if row['id']==task_id)
    require(current_task['revision']==revision and current_task['source_id']==seed['sha256']
            and current_task['mode']==mode,'The normal task identity or revision advanced during snapshot')
    require_completed_nodes(current,task_id,revision)
    history=model_selection_history(revision_hash,task_id,revision,[ROOT/'outputs/difficulty',*history_roots])
    budget=validate_execution_budget(BUDGET)
    task={'task_id':task_id,'mode':mode,'source_id':seed['sha256'],'revision':revision,'revision_hash':revision_hash,
        'source_kind':'prequality_development_probe','difficulty_status':'prequality_development_probe',
        'base_image':config['engine']['image'],'task_directory':str(target),'harbor_export_binding':export_binding,
        'local_controls':CONTROL_REWARDS,'execution_budget':budget,'timeout_seconds':budget['elapsed_guard_seconds'],
        'tool_time_policy':dict(POLICY_V2)}
    manifest={'kind':'prequality_development_probe','schema_version':1,'source_kind':'prequality_development_probe',
        'family':family,'frozen_at':datetime.now(timezone.utc).isoformat(),'selected_task_ids':[task_id],'tasks':[task],
        'model':MODEL,'reasoning_effort':EFFORT,'execution_budget':budget,'timeout_seconds':budget['elapsed_guard_seconds'],
        'tool_time_policy':dict(POLICY_V2),'tool_time_policy_version':2,'source_artifacts_sha256':bindings,
        'main_quality_run':str(run),'normal_node_receipts':normal,'complete_source_admission':proof,
        'normal_InstructionNode_replay_exact':True,'normal_ExportNode_called_on_actual_task':False,
        'same_frozen_resource_export_helper_called':True,'resource_task_inventory':inventory,
        'complete_changed_value_set_count':delta['expected_change_count'],'physical_formula_edit_count':len(plan['edits']),
        'prior_model_selection_inventory':history,'public_recovery_status_at_snapshot':nodes.get('independent_recovery',{}).get('status','pending'),
        'diagnosis_status_at_snapshot':nodes.get('diagnose',{}).get('status','pending'),
        'quality_status':'Prequality development only; recovery, all twelve diagnostics, actual Harbor controls and formal confirmation retain separate required gates.',
        'actual_local_base_image':actual_base,'requested_agent_and_verifier_resources_not_claimed_applied':True,
        'qualified':False,'task_count':0,'model_evaluation_performed':False,'new_LO_calls_during_preparation':0,
        'new_model_calls_during_preparation':0,'new_harbor_control_jobs_launched_during_preparation':False}
    validate_selection_execution_budget(manifest)
    return write_new(output/'probe_manifest.json',manifest)


def freeze_probe(run,task_id,revision,output,*,family,history_roots=()):
    original_output_existed=Path(output).exists()
    try:
        return _freeze_probe(run,task_id,revision,output,family=family,history_roots=history_roots)
    except BaseException as error:
        out=Path(output)
        if not original_output_existed and out.is_dir() and not (out/'probe_manifest.json').exists():
            write_new(out/'snapshot_failure.json',{'kind':'resource_development_snapshot_failure',
                'family':family,'task_id':task_id,'revision':revision,'error_type':type(error).__name__,
                'error':str(error),'all_partial_artifacts_preserved':True,
                'new_LO_calls':0,'new_model_calls':0,'new_Harbor_jobs':0,'qualified':False})
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--family',choices=tuple(FAMILIES),required=True)
    parser.add_argument('--run',type=Path,required=True);parser.add_argument('--task-id',required=True)
    parser.add_argument('--revision',type=int,default=0);parser.add_argument('--output',type=Path)
    parser.add_argument('--freeze',action='store_true');parser.add_argument('--history-root',type=Path,action='append',default=[])
    args=parser.parse_args(argv)
    if args.freeze:
        require(args.output is not None,'A fresh output is required for explicit --freeze')
        result=freeze_probe(args.run,args.task_id,args.revision,args.output,family=args.family,history_roots=args.history_root)
    else:
        require(args.output is None,'Use explicit --freeze to create a snapshot')
        snapshot=read_run(args.run)
        try:require_completed_nodes(snapshot,args.task_id,args.revision);ready=True
        except ValueError:ready=False
        result={'family':args.family,'six_normal_nodes_completed':ready,'all_other_snapshot_checks_still_required':True,
            'run_status':snapshot['run']['status'],'LO_calls':0,'model_calls':0}
    print(json.dumps(result,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
