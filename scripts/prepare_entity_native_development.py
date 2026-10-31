#!/usr/bin/env python3
"""Prepare one fresh native-presentation DEVELOPMENT snapshot; never run a model.

The paired presentation is a new task version. Prior source admission, joint
construction, recovery, quality, controls and scores are not its certificates.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time as clock_time, timedelta, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import shutil
import sys
import time

from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.evaluation.resource_frontier import TASK_FILES,MODEL,EFFORT
from sheets_factory.evaluation.resource_harbor import export_resource_harbor,inspect_resource_export,verify_local_base_image
from sheets_factory.evaluation.streaming_verifier import _sparse_cells
from sheets_factory.evaluation.tool_time_bounds import POLICY_V2
from sheets_factory.evaluation.budget import validate_selection_execution_budget
from sheets_factory.workbook.resource_engine import load_runtime_profile

HELPER_SHA='fbf6bd4a5cde1216bf3057dc744f84d5e60fa2fa85c0dbc0f221daa8e54f4062'
ADAPTER_SHA='76f933fba5e5dc0ac7111eba8ed93bb96c09dc99c2c41bbb19467ca434e2c549'
POLICY_SHA='f98ae807d392bcfe79ef9ae7d9df12e226eb55ddc53fd0e5b4579835715fa509'
ORIGINAL_MANIFEST_SHA='f6933fed38237201bcca52f3103021af3f2ae5a79b1f0562ba8adf8a0cead356'
PROFILE=ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'
PINNED_IMAGE_ID='sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
BUDGET={'version':1,'elapsed_policy':'operational_guard','elapsed_guard_seconds':14400,'tool_budget_seconds':1800}
PENDING=('new_source_admission','new_joint_construction','new_input_stability',
         'five_local_controls','native_public_source_recovery','all_12_quality_checks',
         'normal_export','real_Harbor_controls','fresh_20_task_confirmation')
PATCHES=(('under Group Rules and the complete Group Contract.',
          'under Group Rules, the native Group Inputs and the Group Contract locator.'),
         ('- Group Contract contains the complete public primitive JSON; Group Inputs repeats its literal paths.',
          '- Group Inputs contains the native business assumptions identified by legal owner, contract and period; Group Rules contains the complete business policies. Group Contract locates those native inputs and policies.'))


def require(value,message):
    if not value:raise ValueError(message)


def write_new(path,value):
    with Path(path).open('x') as stream:json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False);stream.write('\n')


def helper():
    path=ROOT/'scripts/prepare_entity_early_development.py'
    require(hashlib.sha256(path.read_bytes()).hexdigest()==HELPER_SHA,'The isolated calculation-validator template changed')
    spec=importlib.util.spec_from_file_location('_native_presentation_reference_helpers',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def presentation_cell(sheet,address):
    column=''.join(c for c in address if c.isalpha());row=int(address[len(column):])
    return ((sheet=='Group Inputs' and column=='A')
            or (sheet in ('S01 Close','S02 Close','S03 Close') and column=='A' and row>1)
            or (sheet=='Group Contract' and (address=='A1' or column in ('A','B') and row>=2)))


def exact_type(cell):
    if cell is None:return ('empty',None)
    value=cell['value']
    if value is None or value=='':return ('empty',None)
    if cell['data_type']=='e':return ('error',str(value))
    if type(value) is bool:return ('boolean',value)
    if isinstance(value,(int,float,Decimal)):
        number=Decimal(str(value));require(number.is_finite(),'Nonfinite cached number')
        return ('number',number)
    if isinstance(value,(datetime,date,clock_time)):return (type(value).__name__,value.isoformat())
    if isinstance(value,timedelta):return ('duration',value.total_seconds())
    require(type(value) is str,'Unsupported cached value type')
    return ('string',value)


def compare_pair_deltas(original_input,original_goal,new_input,new_goal):
    """Re-read all four cached books. No recalc, financial solver or cent rounding.

    Confirm pointwise old/new equivalence outside the exact text scope, that
    old and new presentation texts are each equal across their respective
    input/goal pair, and that the complete observable D sets are identical.
    """
    books=[];old_delta=[];new_delta=[];text_count=checked=0
    try:
        books=[load_workbook(p,data_only=True,read_only=True,keep_links=False)
               for p in (original_input,original_goal,new_input,new_goal)]
        names=books[0].sheetnames
        require(all(book.sheetnames==names for book in books),'Paired worksheet names/order differ')
        for title in names:
            streams=[iter(_sparse_cells(book[title])) for book in books]
            try:
                heads=[next(stream,None) for stream in streams]
                while any(head is not None for head in heads):
                    key=min(head[0] for head in heads if head is not None);cells=[]
                    for i,stream in enumerate(streams):
                        if heads[i] is not None and heads[i][0]==key:
                            cells.append(heads[i][1]);heads[i]=next(stream,None)
                        else:cells.append(None)
                    address=get_column_letter(key[1])+str(key[0]);label=title+'!'+address
                    values=[exact_type(cell) for cell in cells];checked+=1
                    if presentation_cell(title,address):
                        require(values[0]==values[1] and values[2]==values[3],
                                'Presentation text differs between an input/goal pair: '+label)
                        text_count+=1
                    else:
                        require(values[0]==values[2] and values[1]==values[3],
                                'A nonpresentation cached value/type differs: '+label)
                    if values[0]!=values[1]:old_delta.append(label)
                    if values[2]!=values[3]:new_delta.append(label)
            finally:
                for stream in streams:stream.close()
        require(old_delta==new_delta,'The complete original and new observable D sets differ')
        return {'kind':'fresh_four_workbook_exact_cached_D_equivalence','version':1,'passed':True,
                'sheet_names':names,'checked_union_cells':checked,'presentation_text_cells':text_count,
                'both_pair_texts_identical':True,'nonpresentation_values_and_types_exact':True,
                'cent_quantization_applied':False,'expected_change_count':len(new_delta),
                'expected_changes':sorted(new_delta),'original_D_recomputed_not_assumed':True,
                'financial_calculation_or_recovery_performed':False}
    finally:
        for book in books:book.close()


def validate_instruction_patch(graph,path,instruction,old_inventory):
    patch=graph.read(path);original=graph.expected(patch['original']);rendered=graph.expected(patch['rendered'])
    require(original==old_inventory['instruction.md'] and rendered==instruction,'Instruction patch identity differs')
    require(patch.get('exact_replacements')==[{'before':a,'after':b} for a,b in PATCHES]
            and patch.get('all_other_bytes_preserved') is True,'Only the exact two obsolete JSON pointers may change')
    raw=Path(original['path']).read_bytes()
    for before,after in PATCHES:
        require(raw.count(before.encode())==1,'The original pointer is absent/ambiguous')
        raw=raw.replace(before.encode(),after.encode())
    require(raw==Path(rendered['path']).read_bytes(),'Additional instruction bytes changed')
    return graph.ref(path)


def validate_transform(graph,role,call,old_inventory,new_book):
    require(call.get('kind')=='pinned_native_presentation_transform' and call.get('role')==role
            and call.get('status')=='passed' and call.get('timeout_seconds')==900
            and call.get('image_id')==PINNED_IMAGE_ID
            and call.get('network')=='none' and type(call.get('calls_LO')) is int and call['calls_LO']==0
            and type(call.get('calls_model')) is int and call['calls_model']==0,
            'A presentation transform is not a completed isolated operation')
    key='solution/reference.xlsx' if role=='goal' else 'environment/input.xlsx'
    require(graph.expected(call['source'])==old_inventory[key],'The original source differs')
    graph.expected(call['output']);graph.expected(call['implementation'])
    require(call['implementation']['sha256']==ADAPTER_SHA,'The presentation implementation changed')
    proof=graph.read(call['preservation_audit'])
    require(proof.get('kind')=='entity_group_native_business_presentation_static_audit'
            and proof.get('mode')=='native_business_tables' and proof.get('native_public_leaf_count')==10620
            and proof.get('explicit_boolean_as_integer_count')==24
            and proof.get('source',{}).get('sha256')==call['source']['sha256']
            and proof.get('destination',{}).get('sha256')==call['output']['sha256']
            and all(proof.get(k) is True for k in ('all_native_primitive_values_preserved',
                'all_original_phases_and_rules_preserved','complete_shared_string_usage_inventory_checked',
                'uneditable_cells_and_formulas_and_cached_values_and_styles_preserved'))
            and proof.get('agent_facing_reconstruction_reader_supplied') is False,
            'The complete native primitive/policy/definition preservation proof differs')
    require(proof.get('static_reference_proof',{}).get('formula_definitions')==1100346
            and proof['static_reference_proof'].get('changed_text_is_unreferenced') is True
            and proof.get('changed_text_cell_count')==1110984,'The complete static text scope differs')
    require(proof['financial_policy']['sha256']==POLICY_SHA,'The public business policy changed')
    allowed=set(proof['allowed_changed_members']);parts=proof['package_members']
    require(allowed<=parts.keys() and allowed=={'xl/worksheets/sheet2.xml','xl/worksheets/sheet3.xml',
                     'xl/worksheets/sheet4.xml','xl/worksheets/sheet5.xml','xl/worksheets/sheet6.xml','xl/sharedStrings.xml'}
            and all(v['allowed_text_member_change']==(name in allowed)
                and (name in allowed or v['before_sha256']==v['after_sha256']) for name,v in parts.items()),
            'A nonallowlisted package member changed')
    before=graph.read(call['container_before']);after=graph.read(call['container_after'])
    require(before['container_id']==after['container_id'] and len(before['container_id'])==64
            and before['image_id']==after['image_id']==call['image_id']
            and before['user']==after['user']=='0' and before['resources']==after['resources']
            and type(after['state']['ExitCode']) is int and after['state']['ExitCode']==0 and after['state']['OOMKilled'] is False
            and after['state']['Running'] is False,'The actual transform container did not complete safely')
    resources=before['resources']
    require(resources['Memory']==32*1024**3 and resources['NanoCpus']==2*10**9
            and resources['PidsLimit']==256 and resources['NetworkMode']=='none'
            and resources['CapAdd']==['DAC_OVERRIDE'] and resources['CapDrop']==['ALL'],
            'The actual transform resources/capabilities differ')
    worker=graph.read(call['worker_runtime'])
    require(worker.get('status')=='passed' and 0<worker['duration_seconds']<=900
            and 0<worker['maxrss_KiB']<=32*1024**2,'The transform duration/memory evidence differs')
    comparison=graph.read(new_book['comparison'])
    require(comparison.get('kind')=='exact_non_presentation_typed_cached_value_comparison'
            and comparison.get('passed') is True and comparison.get('mismatch_count')==0
            and comparison.get('mismatches')==[] and comparison.get('cent_quantization_applied') is False
            and comparison.get('financial_audit_transfer_claimed') is False
            and comparison.get('source')==call['source'] and comparison.get('output')==new_book['output']
            and comparison.get('checked_non_presentation_cells')==1111028
            and comparison.get('excluded_presentation_text_cells')==proof['changed_text_cell_count'],
            'The complete actual cached-value equivalence proof differs')
    graph.expected(new_book['output'])
    return proof


def validate_prototype(path):
    base=helper();graph=base.FrozenFiles();prototype=graph.read(path)
    require(prototype.get('kind')=='actual_entity_group_native_presentation_prototype'
            and prototype.get('status')=='prototype_preservation_passed_new_admission_and_quality_pending'
            and prototype.get('qualified') is False and type(prototype.get('task_count')) is int and prototype['task_count']==0
            and prototype.get('new_LO_calls')==2 and prototype.get('new_model_calls')==0,
            'A complete actual preservation prototype, not source admission, is required')
    for record in prototype['recipe']:graph.expected(record)
    require(graph.ref(ROOT/'src/sheets_factory/workbook/entity_group_presentation.py')['sha256']==ADAPTER_SHA
            and graph.ref(ROOT/'src/sheets_factory/workbook/entity_group/spec.py')['sha256']==POLICY_SHA,
            'The committed presentation/policy implementation changed')
    old_ref=graph.expected(prototype['source_probe_manifest'])
    require(old_ref['sha256']==ORIGINAL_MANIFEST_SHA,'Only the predeclared original G01 presentation is allowed')
    old=graph.read(old_ref);inventory=old['resource_task_inventory']
    require(set(inventory)==set(TASK_FILES) and len(inventory)==17,'The original resource inventory differs')
    for record in inventory.values():graph.expected(record)
    profile=load_runtime_profile(PROFILE)
    require(profile['id']=='entity_group_large_v2' and profile['image']['id']==PINNED_IMAGE_ID,
            'The prospective pinned runtime profile differs')
    calls=prototype['calls'];require(len(calls)==4,'Exactly two transforms and two actual LO comparisons are required')
    transforms={call['role']:call for call in calls[:2]};calculations={call['role']:call for call in calls[2:]}
    require(set(transforms)==set(calculations)=={'input','goal'},'Both sides of the presentation must be complete')
    terminals=prototype['actual_resource_runtime']['actual_resource_receipts']
    require(len(terminals)==2,'Exactly two actual source LO receipts are required')
    actuals={}
    for record in terminals:
        value=graph.read(record);actuals[value['output']['sha256']]=value
    for role in ('input','goal'):
        transform=transforms[role];calculation=calculations[role]
        require(calculation.get('kind')=='actual_LO_and_exact_typed_comparison','Unexpected operation in the actual prototype')
        validate_transform(graph,role,transform,inventory,calculation)
        output=graph.expected(prototype[role]);require(output==calculation['output'],'The new actual output differs')
        actual=actuals.get(output['sha256']);require(actual is not None,'Missing matching actual LO receipt')
        receipt=next(record for record in terminals if graph.read(record)['output']==output)
        base.validate_calculation(graph,receipt,profile,transform['output'],output)
    instruction=graph.expected(prototype['instruction'])
    patch=validate_instruction_patch(graph,Path(path).parent/'instruction_patch.json',instruction,inventory)
    require(prototype['goal']['sha256']!=inventory['solution/reference.xlsx']['sha256']
            and prototype['input']['sha256']!=inventory['environment/input.xlsx']['sha256'],
            'A presentation snapshot requires fresh public and goal bytes')
    graph.finish()
    return {'graph':graph,'prototype':prototype,'prototype_ref':graph.ref(path),'original':old,
            'profile':profile,'instruction_patch':patch}


def selection_history(revision_hash,task_id,roots,graph):
    result=[];seen=set()
    for root in roots:
        root=Path(root);paths=[root] if root.is_file() else sorted(root.rglob('selection_manifest.json'))
        for path in paths:
            path=path.absolute()
            if str(path) in seen:continue
            seen.add(str(path));record=graph.ref(path);value=graph.read(record,max_bytes=16*1024**2)
            require(isinstance(value.get('tasks'),list),'Malformed prior selection')
            for task in value['tasks']:
                require(task.get('revision_hash')!=revision_hash
                        and not(task.get('task_id')==task_id and task.get('revision')==0),
                        'The new public task revision already has a model selection; no resampling')
            result.append(record)
    return result


def runner_command(manifest,output):
    return [str(ROOT/'.venv312/bin/python'),str(ROOT/'scripts/evaluate_resource_difficulty.py'),
            '--release-manifest',str(manifest),'--output-dir',str(output),'--phase','development',
            '--concurrency','1','--max-infrastructure-retries','0']


def prepare(prototype_path,output,*,history_roots=(),port=0):
    output=Path(output).absolute();require(output==output.resolve() and not output.exists(),'Use a fresh real snapshot directory')
    checked=validate_prototype(prototype_path);graph=checked['graph'];prototype=checked['prototype'];original=checked['original']
    output.mkdir(parents=True);lease=ProducerLease(output).acquire();tick=time.monotonic();status='failed'
    audit=AuditStore(output/'audit',{'id':output.name,'name':'Native presentation early snapshot preparation',
        'status':'running','target_count':0,'producer_active':True,'qualified':False,'model_calls':0})
    panel=DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=port);url=panel.start();audit.update_run(dashboard_url=url)
    print(json.dumps({'output':str(output),'dashboard_url':url,'model_calls':0,'LO_calls':0}),flush=True)
    try:
        old_inventory=original['resource_task_inventory']
        delta=compare_pair_deltas(old_inventory['environment/input.xlsx']['path'],old_inventory['solution/reference.xlsx']['path'],
                                  prototype['input']['path'],prototype['goal']['path'])
        require(delta['presentation_text_cells']==1110984,'The exact paired presentation scope changed')
        old_D=graph.read(original['complete_D'],max_bytes=32*1024**2)
        require(delta['expected_change_count']==261457==original['complete_changed_value_count']
                and delta['expected_changes']==old_D['expected_changes'],'The recomputed complete D differs from the original record')
        delta.update(sources={key:prototype[key] for key in ('input','goal')},original_D=original['complete_D'])
        write_new(output/'complete_D.json',delta);d_ref=graph.ref(output/'complete_D.json')
        hasher=hashlib.sha256()
        with Path(prototype['input']['path']).open('rb') as stream:
            for chunk in iter(lambda:stream.read(8*1024**2),b''):hasher.update(chunk)
        hasher.update(Path(prototype['instruction']['path']).read_bytes());revision_hash=hasher.hexdigest()
        task_id='dbg-native-'+prototype['goal']['sha256'][:12]
        history=selection_history(revision_hash,task_id,[ROOT/'outputs/difficulty',*history_roots],graph)
        base=verify_local_base_image(PROFILE);write_new(output/'actual_local_base_image.json',base)
        stage=output/'private/task';(stage/'public').mkdir(parents=True);(stage/'private').mkdir()
        for key,destination in (('input',stage/'public/input.xlsx'),('goal',stage/'private/goal.xlsx'),('instruction',stage/'public/instruction.md')):
            shutil.copyfile(prototype[key]['path'],destination)
        target=output/'SpreadsheetEval'/task_id
        export_resource_harbor(stage,target,{'task_id':task_id,'mode':'debugging','source_id':prototype['goal']['sha256'],
            'revision':0,'revision_hash':revision_hash,'difficulty_status':'native_presentation_early_development_quality_pending',
            'base_image':checked['profile']['image']['tag']},ROOT,runtime_profile=PROFILE)
        binding=inspect_resource_export(target)
        inventory={p.relative_to(target).as_posix():graph.ref(p) for p in target.rglob('*') if p.is_file()}
        require(set(inventory)==set(TASK_FILES) and len(inventory)==17,'The complete resource export differs')
        require(inventory['environment/input.xlsx']['sha256']==prototype['input']['sha256']
                and inventory['tests/reference.xlsx']['sha256']==prototype['goal']['sha256']
                and inventory['instruction.md']['sha256']==prototype['instruction']['sha256'],
                'The actual exported public/goal/instruction bytes differ')
        for path in (Path(__file__),ROOT/'scripts/prepare_entity_early_development.py',ROOT/'scripts/evaluate_resource_difficulty.py',
                     ROOT/'src/sheets_factory/evaluation/resource_frontier.py',ROOT/'src/sheets_factory/evaluation/frontier.py',
                     ROOT/'src/sheets_factory/evaluation/resource_observer.py',ROOT/'src/sheets_factory/evaluation/resource_harbor.py'):
            graph.ref(path)
        task={'task_id':task_id,'mode':'debugging','source_id':prototype['goal']['sha256'],'revision':0,
              'revision_hash':revision_hash,'task_directory':str(target),'harbor_export_binding':binding,
              'source_kind':'early_unqualified_development_probe','execution_budget':dict(BUDGET),
              'timeout_seconds':14400,'tool_time_policy':dict(POLICY_V2)}
        manifest={'kind':'early_native_entity_presentation_development_probe','schema_version':1,
            'source_kind':'early_unqualified_development_probe','development_only':True,'count':1,
            'confirmation_allowed':False,'publication_allowed':False,'qualified':False,'task_count':0,
            'selected_task_ids':[task_id],'tasks':[task],'model':MODEL,'reasoning_effort':EFFORT,
            'execution_budget':dict(BUDGET),'timeout_seconds':14400,'tool_time_policy':dict(POLICY_V2),
            'tool_time_policy_version':2,'source_artifacts_sha256':{p:r['sha256'] for p,r in graph.files.items()},
            'resource_task_inventory':inventory,'current_input':prototype['input'],'presentation_goal':prototype['goal'],
            'public_instruction':prototype['instruction'],'complete_D':d_ref,'complete_changed_value_count':261457,
            'presentation_prototype':checked['prototype_ref'],'instruction_patch':checked['instruction_patch'],
            'original_task_lineage_only':prototype['source_probe_manifest'],'old_certificates_inherited':False,
            'fresh_pointwise_typed_equivalence_is_not_source_financial_admission':True,
            'old_JSON_recovery_compatible':False,'native_public_source_recovery_pending':True,
            'pending_normal_gates':list(PENDING),'joint_input_stability_certified':False,
            'five_local_controls_certified':False,'independent_recovery_certified':False,'all_12_QA_certified':False,
            'actual_Harbor_controls_certified':False,'actual_agent_verifier_resources_certified':False,
            'prior_model_selection_inventory':history,'zero_is_provisional_until_same_version_full_normal_quality':True,
            'success_may_reject_candidate_early':True,'no_resampling_authorized':True,
            'new_LO_calls':0,'new_model_calls':0,'new_Harbor_jobs':0,'frozen_at':datetime.now(timezone.utc).isoformat()}
        validate_selection_execution_budget(manifest)
        graph.finish();require(selection_history(revision_hash,task_id,[ROOT/'outputs/difficulty',*history_roots],graph)==history,
                               'The selection history changed during snapshot preparation')
        write_new(output/'probe_manifest.json',manifest)
        command=runner_command(output/'probe_manifest.json',output/'evaluation')
        (output/'run_development.sh').write_text('#!/bin/sh\nset -eu\n# Dormant: execution needs separate authorization.\nexec '+shlex.join(command)+'\n')
        status='prepared_development_snapshot_no_model_executed'
        return graph.ref(output/'probe_manifest.json')
    except BaseException as error:
        write_new(output/'snapshot_failure.json',{'error_type':type(error).__name__,'error':str(error),
                  'all_partial_artifacts_preserved':True,'model_calls':0,'LO_calls':0,'qualified':False})
        raise
    finally:
        audit.update_run(status=status,producer_active=False,wall_seconds=time.monotonic()-tick);audit.export()
        panel.stop();audit.db.close();lease.release()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prototype',type=Path,required=True);parser.add_argument('--output',type=Path)
    parser.add_argument('--freeze',action='store_true');parser.add_argument('--port',type=int,default=0)
    args=parser.parse_args(argv)
    if args.freeze:
        require(args.output is not None,'Explicit snapshot creation needs a fresh output')
        result=prepare(args.prototype,args.output,port=args.port)
    else:
        require(args.output is None,'Use --freeze for snapshot creation');checked=validate_prototype(args.prototype)
        result={'prototype':checked['prototype_ref'],'snapshot_created':False,'model_calls':0,'LO_calls':0,'all_quality_pending':True}
    print(json.dumps(result,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
