"""Explicit mocked proof boundaries and real tiny emission; no services."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path

import pytest

from sheets_factory.workbook.linear_capital_sensitivity import (
    source9 as old,source9_revision2 as source,reference_revision2 as reference)

ROOT=Path(__file__).resolve().parents[1]


def store(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);return reference.write(path,value)


@pytest.fixture(scope='module')
def tiny_join():
    descriptor=importlib.util.spec_from_file_location('_revision2_tiny_ledger_fixture',ROOT/'tests/test_linear_capital_sensitivity_source9.py')
    module=importlib.util.module_from_spec(descriptor);descriptor.loader.exec_module(module)
    return module.joined.__wrapped__()


def test_cloned_functions_and_recipes_do_not_modify_v1_namespace_or_gate():
    old_join=old.join_reference;old_build=old.build_candidate;old_reference=old.reference
    source.adapted_ast();source.guard()
    assert old.join_reference is old_join and old.build_candidate is old_build and old.reference is old_reference
    assert old.build_candidate.__globals__['reference'] is old_reference
    assert source.build_candidate.__globals__ is not old.build_candidate.__globals__
    assert source.build_candidate.__globals__['reference'] is source.reference
    assert source.reference is not old_reference
    recipes=source.recipes()
    for module in (old,source,reference):assert recipes[str(Path(module.__file__))]==reference.reference(module.__file__)
    assert str(reference.runtime.PROFILE) in recipes
    for path,digest in source.PINS.items():assert hashlib.sha256(path.read_bytes()).hexdigest()==digest


def completed_shape(tmp_path,monkeypatch):
    order=[c['id'] for c in reference.contract.CASES]
    root=tmp_path/'reference';prepared=store(root/'preparation.json',{'fixture':True})
    cases=[];retained={};inventory=[]
    for case in reference.contract.CASES:
        identity=case['id'];folder=root/'cases'/identity
        actual=store(folder/'terminal.json',{'kind':reference.CASE_KIND,'version':2,'passed':True,'mock_native_proofs':True})
        cases.append(actual);inventory.append({'case':case})
        if identity!=reference.FIXED_CASE:retained[identity]=actual
    observation=store(root/'original_failed_observation.json',{'fixture_original17retained':True})
    result={'kind':reference.KIND,'version':2,'passed':True,'all_cases_retained':True,'qualified':False,
        'reference_is_not_source_or_quality_or_difficulty':True,'automatic_retries':0,
        'financial_forwards':0,'LO_calls':0,'model_calls':0,'new_native_job_invocations':2,
        'original_native_job_invocations':17,'historical_native_job_invocations':19,'admitted_proofs':18,
        'preparation':prepared,'original_complete_failed_observation':observation,
        'retained_complete_cases':retained,'case_order':order,'cases':cases}
    incoming={'observation':observation,'retained':retained,'frozen':{'case_order':order},
        'inventory':{'cases':inventory},'inputs':{}}
    monkeypatch.setattr(reference,'validate_prepared',lambda _:({},incoming))
    return root,result,incoming


@pytest.mark.parametrize('failure',['wrong_kind','eight_only','failed_last','missing_receipt'])
def test_genuine_whole9_validator_rejects_before_source_winner_reads_or_output(tmp_path,monkeypatch,failure):
    root,result,incoming=completed_shape(tmp_path,monkeypatch)
    if failure=='wrong_kind':result['kind']='complete_fixed_nine_case_CP600_best_runner_reference'
    elif failure=='eight_only':result['cases'].pop()
    elif failure=='failed_last':
        result['cases'][-1]=store(tmp_path/'failed.json',{'kind':reference.CASE_KIND,'version':2,'passed':False})
        # Keep the genuine expected physical path gate: replace the existing
        # mock terminal in a fresh fixture through its exact retained ref.
        last=root/'cases'/reference.FIXED_CASE/'terminal.json'
        last.write_bytes(Path(result['cases'][-1]['path']).read_bytes());result['cases'][-1]=reference.reference(last)
    else:
        last=Path(result['cases'][-1]['path']);last.unlink()
    receipt=store(tmp_path/'complete.json',result)
    monkeypatch.setattr(source.reference,'ROOT',tmp_path)
    monkeypatch.setattr(source.reference,'read',lambda _:pytest.fail('No source winner or financial cache read before actual full-nine admission'))
    output=tmp_path/'outputs/must_not_exist'
    with pytest.raises((ValueError,FileNotFoundError)):
        source.build_candidate(receipt,output)
    assert not output.exists()


def test_v1_default_does_not_start_accepting_revision2_pass_json(tmp_path):
    receipt=store(tmp_path/'v2.json',{'kind':reference.KIND,'version':2,'passed':True})
    with pytest.raises(ValueError):old.join_reference(receipt)


def test_new_reference_cursor_only_exposes_original_matrices_after_genuine_API(tmp_path,monkeypatch):
    prepared=store(tmp_path/'new_prepared.json',{'fixture':True})
    original_preparation=store(tmp_path/'old_prepared.json',{'fixture':True})
    prospective=store(tmp_path/'prospective.json',{'original_preparation':original_preparation})
    # Bind the valid metadata graph in this pure mocked admission fixture.
    graph={prepared['path']:{'prospective':prospective},prospective['path']:{'original_preparation':original_preparation}}
    actual={'kind':reference.KIND,'version':2,'passed':True,'qualified':False,'cases':[{'test':i} for i in range(9)],'preparation':prepared}
    called=[]
    monkeypatch.setattr(reference,'validate_completed',lambda value:(called.append(value),actual)[1])
    def read(value):
        assert called,'The genuine API must return before reading source metadata'
        return graph[value['path']]
    monkeypatch.setattr(source.reference,'read',read)
    value=source._genuine_reference({'explicit_mock_proof_boundary':True})
    assert value['preparation']==original_preparation and actual['preparation']==prepared
    assert len(called)==1 and value['cases']==actual['cases']
    actual['cases'].pop()
    with pytest.raises(ValueError):source._genuine_reference({'explicit_mock_proof_boundary':True})


def test_positive_mocked_whole9_join_retains_new_and_original_failed_lineage(tiny_join,monkeypatch):
    order=tiny_join['case_order'];winner=dict(tiny_join['plans'][order[0]])
    actual={'kind':reference.KIND,'version':2,'passed':True,'qualified':False,
        'cases':['case_'+c for c in order],'case_order':order,'preparation':'new_preparation'}
    values={'new_preparation':{'prospective':'new_prospective'},
        'new_prospective':{'original_preparation':'old_preparation','original_complete_failed_observation':'old_failed_observation'},
        'old_preparation':{'all_nine_models':'inventory','prospective':'old_prospective'},
        'old_prospective':{'financial_terminal':'finance','contract':'contract'},'contract':{},
        'finance':{'specification':'spec','universe_A':'universe_A','universe_B':'universe_B','model_A':'baseA','model_B':'baseB'},
        'spec':tiny_join['public'],'universe_A':{'projects':{}},'universe_B':{'projects':{}}}
    rows=[];projections={};calls=[]
    constraints=[{'id':str(i),'passed':True} for i in range(941)]
    for case in reference.contract.CASES:
        identity=case['id'];models={s:s+'_'+identity for s in ('A','B')}
        rows.append({'case':case,'models':models})
        values.update({v:{'explicit_mock_model':True} for v in models.values()})
        values['case_'+identity]={'case':case,'passed':True,'gap_pence':1,'winner_plan':winner,
            'runner_plan':dict.fromkeys(winner,0),'winner_objective_pence':123,'financial_projection':'projection_'+identity}
        projection={'comparison':{'passed':True,'plan_count':2,'plans':[{'id':'winner','plan':winner,
            'passed':True,'errors':[],'differences':[],**{s:{'feasible':True,'objective_pence':123,'constraints':constraints} for s in ('A','B')}}]}}
        projections[identity]=projection;values['projection_'+identity]=projection
    values['inventory']={'case_order':order,'cases':rows}
    record={'path':'mock_complete_terminal','sha256':'a'*64,'bytes':1};values[record['path']]=actual
    monkeypatch.setattr(reference,'validate_completed',lambda value:(calls.append(value),actual)[1])
    def read(value):
        assert calls,'The real API boundary must precede every source read'
        return values[value['path'] if isinstance(value,dict) else value]
    monkeypatch.setattr(source.reference,'read',read);monkeypatch.setattr(source.reference,'_refs',lambda _:None)
    monkeypatch.setattr(source.reference,'_financial_projection',lambda shared,row,a,b:projections[row['case']['id']])
    result=source.join_reference(record)
    assert calls==[record] and result['version']==2 and len(result['plans'])==9
    assert result['references']['nine_case_reference']==record
    assert result['references']['preparation']=='old_preparation'
    assert result['references']['revision2_preparation']=='new_preparation'
    assert result['references']['revision2_prospective']=='new_prospective'
    assert result['references']['original_failed_observation']=='old_failed_observation'
    assert result['distinct_winner_vectors']==1 and not result['different_winners_required']
    assert not result['source_engine_verified'] and not result['qualified']


def test_clone_build_and_validate_reuse_complete_tiny_emitter_and_independent_AB(tmp_path,monkeypatch,tiny_join):
    original_reference=old.reference;before=old.build_candidate.__globals__['join_reference']
    receipt=store(tmp_path/'mock_complete_reference.json',{'mock_only_not_actual_reference':True})
    joined=deepcopy(tiny_join);joined.update(references={'nine_case_reference':receipt},
        distinct_winner_vectors=2,winner_vector_groups=[joined['case_order'][::2],joined['case_order'][1::2]])
    calls=[]
    def admit(value):calls.append(value);return {'mock_proofs':True}
    monkeypatch.setattr(reference,'validate_completed',admit)
    def join(value):
        reference.validate_completed(value)
        return deepcopy(joined)
    # Only the new private function namespace is patched; the original source
    # remains at its real closed whole-nine CP gate throughout.
    monkeypatch.setitem(source.build_candidate.__globals__,'join_reference',join)
    monkeypatch.setattr(source.reference,'ROOT',tmp_path)
    output=tmp_path/'outputs/candidate'
    result=reference.read(source.build_candidate(receipt,output))
    assert result['kind']==source.KIND and result['version']==2
    assert result['source_engine_verified'] is result['qualified'] is False
    expected=reference.read(result['independent_expected'])
    assert expected['kind']==source.EXPECTED_KIND and expected['version']==2
    assert expected['all_values_checked_against_independent_A_B'] is True
    assert source.validate_candidate(reference.reference(output/'preparation.json'))==result
    assert len(calls)==2 and all(c==receipt for c in calls)
    assert old.reference is original_reference and old.build_candidate.__globals__['join_reference'] is before


def test_algebraic_geometry_matches_every_emitted_tiny_financial_formula_and_mask(tmp_path,tiny_join):
    from sheets_factory.workbook.linear_capital_sensitivity import excel9
    bindings=excel9.emit_workbook(tmp_path/'tiny.xlsx',tiny_join['public'],tiny_join['case_models'],tiny_join['plans'])
    census=source.geometry(tiny_join['public'])
    assert census['formula_points']==bindings['formula_count']
    assert census['independent_numeric_financial_points']==len(bindings['financial_bindings'])
    assert census['decision_numeric_points']==len(bindings['decision_bindings'])
    assert census['worksheet_count']==len(bindings['sheetnames'])
    assert census['case_cash_rows']==bindings['case_cash_rows']
    assert census['case_constraint_rows']==bindings['case_constraint_rows']
    financial={(r['sheet'],r['cell']) for r in bindings['financial_bindings']}
    assert all(type(old.resolve_expected(r,tiny_join['results']['A']))is int for r in bindings['financial_bindings'])
    actual=sum(r['sheet'] in tiny_join['public']['project_ids'] and r['value']==excel9.NA for r in bindings['literal_bindings'])
    assert census['provided_pre_FY1_NA_text_points']==actual
    masks=excel9.view_edits(bindings,tiny_join['public'],mode='financial_modeling')['masked']
    assert census['FM_mask_points']==len(masks)
    assert census['workbook_materializations']==census['optimizer_LO_model_calls']==0
    assert not census['source_engine_verified'] and not census['actual_full_D_count_claimed']
