"""Source boundary checks without any actual solver or spreadsheet engine."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from sheets_factory.workbook.linear_capital_scaled import excel, finance, spec

ROOT=Path(__file__).resolve().parents[1]


def module(name,path):
    definition=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(definition);definition.loader.exec_module(result)
    return result


source=module('_scaled_source_tests',ROOT/'scripts/build_linear_capital_scaled_source.py')
inputs=module('_scaled_source_dimension_fixture',ROOT/'tests/test_linear_capital_scaled_spec.py')
tiny=module('_scaled_source_financial_fixture',ROOT/'tests/test_linear_capital_scaled_excel_views.py')


@pytest.fixture
def proof(tmp_path,monkeypatch):
    public=inputs.fixture(production=True)
    path=tmp_path/'raw.json';path.write_text(source.json.dumps(public))
    reference=source.reference(path)
    plan={pid:int(i<120) for i,pid in enumerate(public['project_ids'])}
    result={'kind':source.REFERENCE_KIND,'passed':True,'specification':reference,
        'specification_sha256':spec.canonical_sha256(public),'winner_plan':plan,
        'unique_best':True,'gap_pence':1,'winner_objective_pence':101,
        'runner_objective_pence':100,'selected_project_count':120,
        'selection_density_passed':True,'solver_status_is_not_formal_certificate':True}
    artifact=tmp_path/'reference.json';artifact.write_text('{}')
    monkeypatch.setattr(source,'_reference_provider',lambda:SimpleNamespace(validate_completed=lambda _:result))
    return public,result,artifact


@pytest.mark.parametrize('selected',[120,240])
def test_only_new_reference_and_prospective_proportional_density_are_accepted(proof,selected):
    public,result,path=proof
    result['winner_plan']={pid:int(i<selected) for i,pid in enumerate(public['project_ids'])}
    result['selected_project_count']=selected
    _,actual=source._validate_reference(path,public)
    assert actual is result and source.spec is spec
    assert source.SOURCE_KIND=='independently_verified_linear_capital_scaled_native_source'


@pytest.mark.parametrize('change',['old_reference','not_passed','not_unique','zero_gap',
    'wrong_gap','below_density','above_density','missing_choice','different_spec'])
def test_invalid_or_relabelled_reference_never_reaches_source_execution(proof,change):
    public,result,path=proof
    if change=='old_reference':result['kind']='linear_capital_producer16_best_runner_dual_financial_reference'
    elif change=='not_passed':result['passed']=False
    elif change=='not_unique':result['unique_best']=False
    elif change=='zero_gap':result['gap_pence']=0
    elif change=='wrong_gap':result['gap_pence']=2
    elif change in {'below_density','above_density'}:
        n=119 if change=='below_density' else 241
        result['winner_plan']={pid:int(i<n) for i,pid in enumerate(public['project_ids'])}
        result['selected_project_count']=n
    elif change=='missing_choice':result['winner_plan'].pop('P360')
    elif change=='different_spec':result['specification_sha256']='0'*64
    with pytest.raises(ValueError):source._validate_reference(path,public)


def test_every_native_source_locator_resolves_against_both_new_financial_forwards(tmp_path):
    _,public=tiny.fixture();plan={'P001':1,'P002':0}
    bindings=excel.emit_workbook(tmp_path/'source.xlsx',public,plan=plan)
    a,b=finance.simulate_a(public,plan),finance.simulate_b(public,plan)
    expected=source.expected_values(public,a,b,bindings,plan)
    assert expected['formula_count']==bindings['formula_count']
    assert expected['financial_locator_count']==len(bindings['financial_bindings'])
    coverage=source.financial_locator_coverage(public,bindings)
    assert coverage['required_distinct_fields']>0
    changed=deepcopy(b);changed['projects']['P001']['scenarios']['S01']['annual'][0]['bank_interest']+=1
    with pytest.raises(ValueError,match='Independent financial expectations disagree'):
        source.expected_values(public,a,changed,bindings,plan)
    wrong=deepcopy(bindings);wrong['kind']='linear_capital_portfolio_native_excel_bindings'
    with pytest.raises(ValueError,match='versioned complete N360'):
        source.expected_values(public,a,b,wrong,plan)


def test_original_two_runner_join_cannot_be_misrepresented_as_new_producer_join(tmp_path):
    u=tmp_path/'universe.json';u.write_text('{}')
    expected={'plan':{'P001':1},'passed':True,'errors':[],'differences':[],
        'A':{'feasible':True,'objective_pence':10},'B':{'feasible':True,'objective_pence':10}}
    crosscheck={'kind':'posted_universe_plan_aggregation_crosscheck','passed':True,
        'require_group_feasible':True,'plan_count':2,'plans':[{'id':'winner',**expected},{'id':'runner'}]}
    path=tmp_path/'comparison.json';path.write_text(source.json.dumps(crosscheck))
    proof={'universe_A':source.reference(u),'universe_B':source.reference(u),
        'reference_validation':source.reference(path),'winner_plan':expected['plan'],
        'winner_objective_pence':10}
    a,b=source.expected_results(proof)
    assert a['plan']==b['plan']==expected['plan']
    crosscheck['plan_count']=3;path.write_text(source.json.dumps(crosscheck))
    proof['reference_validation']=source.reference(path)
    with pytest.raises(ValueError,match='single runner'):source.expected_results(proof)


def test_cli_input_conflicts_stop_before_any_preparation_or_engine(tmp_path,monkeypatch):
    monkeypatch.setattr(source,'prepare',lambda *a,**k:pytest.fail('Invalid CLI must not prepare'))
    monkeypatch.setattr(source,'execute_prepared',lambda *a,**k:pytest.fail('Invalid CLI must not execute'))
    with pytest.raises(SystemExit):source.main(['--prepared',str(tmp_path),'--profile','changed.yaml','--run'])
    with pytest.raises(SystemExit):source.main(['--spec','only.json','--run'])
    with pytest.raises(SystemExit):source.main(['--prepared',str(tmp_path),'--port','65536','--run'])
