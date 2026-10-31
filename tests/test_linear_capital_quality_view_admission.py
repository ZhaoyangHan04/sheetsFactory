"""Tiny actual-value protocols with fake financial/engine boundaries only."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import openpyxl
import pytest

from sheets_factory.pipelines import linear_capital_quality as q
from sheets_factory.workbook.linear_capital_portfolio import task_views
from sheets_factory.workbook.heterogeneous_contracts.validate import compare_typed_caches
from sheets_factory.evaluation.streaming_delta import compare_workbooks
from sheets_factory.evaluation.streaming_verifier import compare_files

loader=importlib.util.spec_from_file_location('_linear_admission_fixture_boundary',Path(__file__).with_name('test_linear_capital_quality_admission.py'))
fixture_module=importlib.util.module_from_spec(loader);loader.loader.exec_module(fixture_module)
provider=fixture_module.provider
write=fixture_module.write


def book(path,*,missing=False,extra=False):
    b=openpyxl.Workbook();s=b.active;s['A1']='changed' if extra else 'Business title';s['A2']=None if missing else 1;s['A3']=0
    b.save(path);b.close();return q.reference(path)


def _binding(i,g,o):return {'input':i,'goal':g,'output':o}


@pytest.fixture
def completed_view(provider,monkeypatch):
    root,manifest,registry,_=provider
    actual_source=book(root/'source.xlsx')
    source=json.loads(Path(manifest['path']).read_text());source['workbook']=actual_source
    audits=[write(root/f'audit{i}.json',{'passed':True,'bindings_sha256':'d'*64,'specification_sha256':'e'*64}) for i in range(3)]
    source['financial_audits']=audits;manifest=write(Path(manifest['path']),source)
    session=q.LinearSourceAdmission(manifest,provider_id='fixture',provider_registry=registry)
    monkeypatch.setattr(session.helper,'runtime',lambda path:(source['runtime_profile'],{'fixture':True}))
    monkeypatch.setattr(session.helper,'recipes',lambda:{},raising=False)
    monkeypatch.setattr(session.helper,'require',q.require,raising=False)
    monkeypatch.setattr(session.helper,'read',lambda ref:json.loads(Path(ref['path'] if isinstance(ref,dict) else ref).read_text()),raising=False)
    monkeypatch.setattr(session.helper,'checked',lambda record:session.references.check(record),raising=False)
    monkeypatch.setattr(session.helper,'reference',q.reference,raising=False)
    calls_checked=[]
    def actual(call,terminal,frozen):
        calls_checked.append(call['role']);return call['actual_resource_evidence']
    monkeypatch.setattr(session.helper,'validate_actual_call',actual)
    plan={'kind':'planned_unverified_linear_capital_task_view','version':1,'mode':'financial_modeling',
        'source':actual_source,'bindings':source['bindings'],'bindings_canonical_sha256':'d'*64,
        'specification_sha256':'e'*64,'sheetnames':['Sheet'],'recipe':task_views._recipe(),'instruction':'Complete the business model.',
        'masked_targets':[{'sheet':'Sheet','cell':'A2','before':1}],'formula_edits':[],'choice_edits':[],
        'provided_cells':[{'sheet':'Sheet','cell':'A1','value':'Business title'}]}
    plan['plan_sha256']=task_views.canonical_sha256(plan)
    plan_ref=write(root/'plan.json',plan);raw_input=book(root/'raw_input.xlsx',missing=True)
    brief=root/'instruction.md';brief.write_text(plan['instruction'])
    view={'kind':'materialized_unverified_linear_capital_task_view','version':1,'mode':'financial_modeling',
        'source':actual_source,'plan':plan_ref,'input':raw_input,'goal':actual_source,'instruction':q.reference(brief),
        'specification_sha256':'e'*64,'sheetnames':['Sheet'],'plan_sha256':plan['plan_sha256'],
        'recipe':plan['recipe'],'temporary_plan_only':None,'family_inputs':{}}
    view_ref=write(root/'view_manifest.json',view)
    required=['goal_reference','input_pass1','input_pass2','input_pass3','control_equivalent','control_missed_root','control_extra_change']
    frozen={'kind':'prepared_linear_capital_task_view_actual_validation','version':1,'source_provider':'fixture',
        'source_admission':manifest,'materialized_view':view_ref,'mode':'financial_modeling',
        'recipe':q._current_view_recipe(session.helper),'runtime_profile':source['runtime_profile'],
        'runtime_profile_value':{'fixture':True},'required_stage_roles':required,'model_calls':0,'LO_calls':0,'qualified':False}
    prepared=write(root/'preparation.json',frozen)
    goal=book(root/'goal.xlsx');public=book(root/'input.xlsx',missing=True)
    second=book(root/'input2.xlsx',missing=True);third=book(root/'input3.xlsx',missing=True)
    controls={'oracle':goal,'nop':public,'equivalent':book(root/'equivalent.xlsx'),
        'missed_root':book(root/'missed_root.xlsx',missing=True),'extra_change':book(root/'extra_change.xlsx',extra=True)}
    raw_controls={n:book(root/(n+'_raw.xlsx'),missing=n=='missed_root',extra=n=='extra_change')
        for n in ('equivalent','missed_root','extra_change')}
    pairs=[(actual_source,goal),(raw_input,public),(public,second),(second,third)]
    pairs += [(raw_controls[n],controls[n]) for n in ('equivalent','missed_root','extra_change')]
    calls=[]
    for index,(role,(i,o)) in enumerate(zip(required,pairs),1):
        evidence={'terminal':write(root/f'engine{index}.json',{'fixture':'not an actual engine'})}
        call={'index':index,'role':role,'input':i,'output':o,'completed':True,'actual_resource_evidence':evidence}
        call['terminal_receipt']=write(root/f'LO{index}_terminal.json',deepcopy(call));calls.append(call)
    delta=compare_workbooks(public['path'],goal['path'],goal['path']);delta['workbook_binding']=_binding(public,goal,goal)
    delta_ref=write(root/'complete_D.json',delta)
    stable_goal={**compare_typed_caches(actual_source['path'],goal['path']),'left':actual_source,'right':goal}
    stabilities=[write(root/f'stable{i}.json',{'left':public,'right':r,
        'comparison':compare_typed_caches(public['path'],r['path'])}) for i,r in enumerate((second,third),2)]
    reports={}
    for n,o in controls.items():
        report=compare_files(public['path'],goal['path'],o['path']);report['workbook_binding']=_binding(public,goal,o)
        reports[n]=write(root/(n+'_comparison.json'),report)
    control_ref=write(root/'controls.json',{'rewards':q.REWARDS,'workbooks':controls,'reports':reports,'raw_control_inputs':raw_controls})
    result={'kind':'linear_capital_task_view_actual_validation','version':1,'passed':True,'source_provider':'fixture',
        'preparation':prepared,'source_admission':manifest,'materialized_view':view_ref,'mode':'financial_modeling',
        'required_stage_roles':required,'actual_LO_calls':calls,'input':public,'goal':goal,'complete_D':delta_ref,
        'typed_stabilities':stabilities,'goal_stability':write(root/'goal_stable.json',stable_goal),
        'controls_evidence':control_ref,'local_controls':q.REWARDS,'individual_effects':{},'temporary_plan_baseline':None,
        'instruction':view['instruction'],'source_goal_copy':actual_source,'source_workbook':actual_source,
        'source_original_unchanged':True,'qualified':False,'model_calls':0,'actual_Harbor_jobs':0,
        'all_twelve_quality_checks_passed':False,'difficulty_certified':False}
    terminal=write(root/'terminal.json',result)
    return root,session,terminal,result,calls_checked


def test_one_cold_source_then_complete_actual_view_value_checks(completed_view):
    _,source,terminal,_,checked=completed_view
    live=q.LinearViewAdmission(source,terminal,provider_id='fixture')
    assert source.helper.calls==source.cold_source_validation_count==1
    assert checked==['goal_reference','input_pass1','input_pass2','input_pass3','control_equivalent','control_missed_root','control_extra_change']
    p=q.require_view_admission(live)
    assert p['full_D_count']==1 and p['all_twelve_quality_checks_passed'] is p['qualified'] is False
    assert p['normal_factory_nodes_previously_executed'] is p['prior_difficulty_transferred'] is False
    for _ in range(3):live.guard()
    assert source.helper.calls==1


def test_frozen_protocol_namespace_never_mutates_original_module(completed_view):
    _,source,terminal,_,_=completed_view
    module=q._task_validator(q.References());before=dict(vars(module))
    q.LinearViewAdmission(source,terminal,provider_id='fixture')
    assert vars(module)==before


def test_forged_flag_or_opaque_object_rejected():
    with pytest.raises(ValueError,match='Persisted'):q.require_view_admission({'admitted':True})
    with pytest.raises(ValueError,match='Persisted'):q.require_view_admission(object.__new__(q.LinearViewAdmission))


@pytest.mark.parametrize('attack',['wrong_provider','missing_call','wrong_control','wrong_canonical_binding','false_source_goal'])
def test_incomplete_or_different_actual_protocol_fails_closed(completed_view,attack):
    root,source,terminal,result,_=completed_view
    if attack=='wrong_provider':result['source_provider']='other'
    elif attack=='missing_call':result['actual_LO_calls'].pop()
    elif attack=='wrong_control':result['local_controls']={**q.REWARDS,'missed_root':1}
    elif attack=='false_source_goal':result['source_original_unchanged']=False
    else:
        plan_path=root/'plan.json';plan=json.loads(plan_path.read_text());plan['bindings_canonical_sha256']='0'*64
        plan['plan_sha256']=task_views.canonical_sha256({k:v for k,v in plan.items() if k!='plan_sha256'})
        changed=write(plan_path,plan);vp=root/'view_manifest.json';view=json.loads(vp.read_text());view['plan']=changed
        view['plan_sha256']=plan['plan_sha256'];write(vp,view)
    terminal=write(Path(terminal['path']),result)
    with pytest.raises(ValueError):q.LinearViewAdmission(source,terminal,provider_id='fixture')


def test_cold_value_comparison_rejects_rebound_false_delta(completed_view):
    root,source,terminal,result,_=completed_view
    delta=json.loads(Path(result['complete_D']['path']).read_text());delta['expected_changes']=['Sheet!A3'];delta['actual_changes']=['Sheet!A3']
    result['complete_D']=write(root/'forged_D.json',delta);terminal=write(Path(terminal['path']),result)
    with pytest.raises(ValueError,match='entire input/goal delta'):q.LinearViewAdmission(source,terminal,provider_id='fixture')


def test_admitted_guard_rejects_late_control_artifact_tamper(completed_view):
    root,source,terminal,_,_=completed_view
    live=q.LinearViewAdmission(source,terminal,provider_id='fixture')
    (root/'extra_change.xlsx').write_bytes(b'late corruption')
    with pytest.raises(ValueError,match='changed'):live.guard()
