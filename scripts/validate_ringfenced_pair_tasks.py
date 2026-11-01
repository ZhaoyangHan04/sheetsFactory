#!/usr/bin/env python3
"""Whole-pair task engineering; only an explicit later run starts eight calls."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys
from types import FunctionType, SimpleNamespace

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'));sys.dont_write_bytecode=True
from sheets_factory.workbook.linear_capital_ringfenced_pairs import task_views as views
from sheets_factory.evaluation import streaming_verifier as sparse

ANCESTOR=ROOT/'scripts/validate_equity_income_group_tasks.py'
ANCESTOR_SHA='bcc07848ed5b868c9cb943e3058aa10980b9399d4d53a8d17220d60748a85f0c'
SOURCE=ROOT/'scripts/run_ringfenced_pair_session_revision2.py'
SOURCE_SHA='2e47ce7e09b6565d5ee0388efbde31ff98618c0d92c213930cfea457b939a6eb'
SOURCE_KIND='completed_two_ringfenced_pair_source_same_process_session'
KIND='prepared_complete_ringfenced_pair_task_engineering'
TERMINAL_KIND='complete_ringfenced_pair_task_engineering'
STAGES=('FM_input1','FM_input2','DBG_input1','DBG_input2','equivalent','FM_missed_root','DBG_missed_root','extra_change')
c=views.c
reference,checked,read,write,require=c.reference,c.checked,c.read,c.write,c.require


def _module(path,digest,name):
    require(reference(path)['sha256']==digest,'A pinned complete lifecycle changed')
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


base=_module(ANCESTOR,ANCESTOR_SHA,'_pair_task_frozen_eight_stage')
session=_module(SOURCE,SOURCE_SHA,'_pair_task_genuine_source_session')
pilot=session._N['_pilot']();helper=pilot._N['support']();cap=pilot._N['engines']()
_N={**vars(base),'__file__':__file__,'__name__':'_private_complete_pair_task_engineering',
    'KIND':KIND,'TERMINAL_KIND':TERMINAL_KIND,'STAGES':STAGES}
for name,value in vars(base).items():
    if isinstance(value,FunctionType) and value.__globals__ is vars(base):
        clone=FunctionType(value.__code__,_N,name,value.__defaults__,value.__closure__)
        clone.__kwdefaults__=deepcopy(value.__kwdefaults__);_N[name]=clone


def _genuine(record):
    terminal=read(record)
    require(terminal['kind']==SOURCE_KIND and terminal['version']==1 and terminal['passed'] is True
        and terminal['actual_calls_started']==terminal['actual_calls_completed']==terminal['LO_calls']==3,
        'Only the genuine completed whole-pair source3 is eligible')
    source_folder=checked(terminal['preparation']).parent
    session_preparation=read(source_folder.parent/'session_preparation.json')
    require(session_preparation['source_preparation']==terminal['preparation']
        and session_preparation['genuine_local_reference_validations']==session_preparation['genuine_original_source_validations']==2,
        'The whole pair source is missing its exact two-reference/two-source admission')
    cache=session_preparation['root_pinned_prior_preflight']
    if cache is None:return session.validate_completed(record)
    return session.validate_completed(record,parse_cache=cache,expected_cache_sha256=cache['sha256'])


def _validate_call(call,record,frozen):
    return cap.validate_capped_call(call,record,frozen,resource_validator=helper.resource_support().validate_actual_call)


def _compare_typed(left,right,unused):
    comparison=sparse.compare_files(left,left,right)
    return {'passed':comparison['reward']==1,'comparison':comparison,'all_numeric_values':'HALF_UP2dp'}


source=SimpleNamespace(validate_source=_genuine,now=pilot._N['now'],stage=helper.stage,
    validate_call=_validate_call,owned_absence=helper.owned_absence,compare_typed=_compare_typed)
_N.update(source=source,AuditStore=pilot._N['AuditStore'],DashboardServer=pilot._N['DashboardServer'],
    ProducerLease=pilot._N['ProducerLease'],ThreadCappedResourceLibreOfficeEngine=cap.ThreadCappedResourceLibreOfficeEngine)


def recipes():
    return {**pilot.recipes(),**views.recipes(),str(ANCESTOR):reference(ANCESTOR),str(SOURCE):reference(SOURCE),
        str(Path(__file__).resolve()):reference(__file__)}


def verify_definitions(path,definition,*,blank=False):return views.verify(path,definition,blank=blank)


def verify_input_caches(path,expected,*,blank):
    return views.verify(path,read(expected['view_plan']),blank=blank,check_caches=True)


def prepare(source_manifest,whole_views_contract,output):
    output=Path(output).absolute();require(output==output.resolve() and output.is_relative_to(ROOT/'outputs')
        and not output.exists(),'Use a fresh complete pair task preparation')
    actual=source.validate_source(source_manifest);sf=read(actual['preparation'])
    whole_views_contract=whole_views_contract if isinstance(whole_views_contract,dict) else reference(whole_views_contract)
    mapped=views.plan(whole_views_contract,actual,actual['preparation']);root=mapped['control_root']
    require(root['before_kind']=='formula' and type(root['before'])is str and root['before'].startswith('='),
        'The original positive/negative control must bind a healthy formula')
    output.mkdir(parents=True);planned=output/'planned';planned.mkdir()
    plan_ref=write(output/'whole_view_plan.private.json',mapped)
    rp={root['sheet']:{root['cell']:('formula','=0+('+root['before'].lstrip('=')+')')}}
    group=views.group_report.SHEET
    # This is a public label, outside every financial target and original fault.
    label=read(sf['report_plan'])['literals']['A1']
    changes={'FM_input':views.actions(mapped,'financial_modeling'),'DBG_input':views.actions(mapped,'debugging'),
        'equivalent':rp,'FM_missed_root':{root['sheet']:{root['cell']:('blank',None)}},
        'DBG_missed_root':{root['sheet']:{root['cell']:('formula',root['after'])}},
        'extra_change':{group:{'A1':('text',label+' [control]')}}}
    inputs={};edits={}
    for name,actions in changes.items():
        path=planned/(name+'.xlsx');edits[name]=views.transform(checked(actual['source']),path,actions);inputs[name]=reference(path)
    instructions={}
    for mode,brief in zip(views.MODES,(views.FM_BRIEF,views.DBG_BRIEF),strict=True):
        path=planned/(mode+'_instruction.md');path.write_text(brief);instructions[mode]=reference(path)
    verify_definitions(checked(inputs['FM_input']),mapped,blank=True);verify_definitions(checked(inputs['DBG_input']),mapped)
    expected=write(output/'complete_scope.private.json',{'kind':'complete_ringfenced_pair_financial_scope','version':1,
        'view_plan':plan_ref,'target_count':mapped['FM_target_count'],'all_numeric_primary':'HALF_UP2dp',
        'all_original_source_context_preserved':True})
    return write(output/'preparation.json',{'kind':KIND,'version':1,'source_manifest':reference(source_manifest['path'] if isinstance(source_manifest,dict) else source_manifest),
        'source_preparation':actual['preparation'],'genuine_goal':actual['source'],'candidate_preparation':whole_views_contract,
        'whole_views_contract':whole_views_contract,'pair_id':mapped['pair_id'],'definition':plan_ref,'DBG_definition':plan_ref,
        'bindings':plan_ref,'expected':expected,'planned_inputs':inputs,'instruction_bytes':instructions,'exact_edits':edits,
        'stage_order':list(STAGES),'mode_order':list(views.MODES),'required_actual_LO_calls':8,
        'all_modes_and_controls_frozen_before_first_actual_call':True,'reuse_genuine_source3_goal_and_two_stabilities':True,
        'financial_target_count':mapped['FM_target_count'],'source_formula_count':views.COUNTS['formulas'],
        'DBG_formula_root_count':mapped['DBG_formula_root_count'],'provisional_choice_count':mapped['DBG_choice_count'],
        'all720choices_and_two_completion_gates_masked':True,'runtime_profile':sf['runtime_profile'],
        'runtime_profile_value':sf['runtime_profile_value'],'recipe':recipes(),'actual_LO_calls':0,
        'new_financial_forwards':0,'model_calls':0,'qualified':False,'normal_all12_QA_passed':False})


def validate_prepared(output):
    f=read(Path(output)/'preparation.json')
    require(f['kind']==KIND and f['version']==1 and f['recipe']==recipes() and f['stage_order']==list(STAGES)
        and f['mode_order']==list(views.MODES) and f['required_actual_LO_calls']==8
        and f['all_modes_and_controls_frozen_before_first_actual_call'] is True
        and f['financial_target_count']==views.COUNTS['targets'] and f['source_formula_count']==views.COUNTS['formulas']
        and f['DBG_formula_root_count']==views.COUNTS['DBG_formula_roots'] and f['provisional_choice_count']==720
        and f['all720choices_and_two_completion_gates_masked'] is True and f['actual_LO_calls']==f['new_financial_forwards']==f['model_calls']==0
        and f['qualified'] is False and f['normal_all12_QA_passed'] is False,'The whole-pair protocol, scope or recipe changed')
    for key in ('source_manifest','source_preparation','genuine_goal','candidate_preparation','whole_views_contract',
                'definition','DBG_definition','expected','bindings','runtime_profile'):checked(f[key])
    declared=views.validate_pool(f['whole_views_contract']);actual,sf,plan=read(f['source_manifest']),read(f['source_preparation']),read(f['definition'])
    require(actual['kind']==SOURCE_KIND and actual['passed'] is True and actual['source']==f['genuine_goal']
        and actual['preparation']==f['source_preparation'] and plan['genuine_goal']==f['genuine_goal']
        and plan['whole_views_contract']==f['whole_views_contract'] and plan['source_preparation']==f['source_preparation']
        and plan['pair_id']==f['pair_id'] and f['DBG_definition']==f['bindings']==f['definition']
        and sf['runtime_profile']==f['runtime_profile'] and sf['runtime_profile_value']==f['runtime_profile_value'],
        'The complete source and task views belong to different material versions')
    require(plan==views.plan(f['whole_views_contract'],actual,f['source_preparation']),
        'A view must exactly reproduce both complete original local masks/fault inventories and all group targets')
    require(plan['recipe']==views.recipes() and plan['FM_target_count']==f['financial_target_count']
        and plan['DBG_formula_root_count']==f['DBG_formula_root_count'] and plan['DBG_choice_count']==720
        and read(sf['certificate'])['prospective']==declared['prospective'],'The original fixed pool or physical target scope changed')
    for mode,brief in zip(views.MODES,(views.FM_BRIEF,views.DBG_BRIEF),strict=True):
        require(checked(f['instruction_bytes'][mode]).read_text()==brief,'The original public business request changed')
    require(set(f['planned_inputs'])=={'FM_input','DBG_input','equivalent','FM_missed_root','DBG_missed_root','extra_change'},
        'A complete shared eight-stage control inventory is required')
    for name,record in f['planned_inputs'].items():
        checked(record);edit=f['exact_edits'][name]
        require(edit['source']==f['genuine_goal'] and edit['output']==record and edit['all_formula_caches_absent'] is True,
            'A task input no longer binds the original cache-free physical edit')
        require(views.cold_cache_census(checked(record))==edit['formulas'],
            'A planned control/input acquired a cached answer or changed formula scope')
    verify_definitions(checked(f['planned_inputs']['FM_input']),plan,blank=True)
    verify_definitions(checked(f['planned_inputs']['DBG_input']),plan)
    return f


_N.update(recipes=recipes,prepare=prepare,validate_prepared=validate_prepared,
    verify_definitions=verify_definitions,verify_input_caches=verify_input_caches)
execute_prepared=_N['execute_prepared'];validate_completed=_N['validate_completed']


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--freeze-pool',action='store_true')
    p.add_argument('--prospective',type=Path);p.add_argument('--source-manifest',type=Path)
    p.add_argument('--whole-views-contract',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--prepared',type=Path);p.add_argument('--run',action='store_true');a=p.parse_args(argv)
    if a.freeze_pool:
        require(not a.run and a.prospective and a.output and not a.prepared,'Freeze the whole pool before any material')
        result=views.freeze_pool(a.prospective,a.output)
    elif a.prepared:
        require(not any((a.source_manifest,a.whole_views_contract,a.output,a.prospective)),'Use the exact existing preparation')
        result=execute_prepared(a.prepared) if a.run else validate_prepared(a.prepared)
    else:
        require(not a.run and a.source_manifest and a.whole_views_contract and a.output,
            'Prepare and review before a separate actual run')
        result=prepare(a.source_manifest,reference(a.whole_views_contract),a.output)
    print(base.json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
