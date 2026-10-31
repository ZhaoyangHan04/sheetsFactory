"""Independent B coefficient tests; only tiny CP-SAT solves are executed."""
import ast
from collections import Counter
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from sheets_factory.workbook.linear_capital_portfolio import ledger, spec, model_b

ROOT=Path(__file__).resolve().parents[1]
loader=importlib.util.spec_from_file_location('raw_hand_inputs_for_model_B',ROOT/'tests/test_linear_capital_portfolio_ledger.py')
inputs=importlib.util.module_from_spec(loader);loader.loader.exec_module(inputs)


def tiny_model():
    return {'kind':model_b.MODEL_KIND,'version':1,'project_ids':['P001','P002','P003'],
        'objective_pence':[5,4,3], 'rows':[{'id':'capacity:cash','family':'capacity','scenario_id':None,
            'year':None,'coefficients':[2,2,1],'limit':3}],
        'specification_sha256':'0'*64,'universe_sha256':'1'*64}


def test_capacity_first_coefficients_match_hand_financial_and_resource_values(monkeypatch):
    public=inputs.fixture(projects=2,scenarios=3)
    monkeypatch.setattr(model_b,'_solver',lambda:pytest.fail('Building imported a solver'))
    before=deepcopy(public)
    model=model_b.build_model(public)
    assert public==before
    assert model['objective_pence']==[394,394]
    assert model['project_ids']==['P001','P002']
    rows={r['id']:r for r in model['rows']}
    assert rows['initial_sponsor_equity']['coefficients']==[500,500]
    assert rows['annual_new_lp:S01:1']['coefficients']==[100,100]
    assert rows['annual_debt_close:S02:1']['coefficients']==[250,250]
    assert rows['region_exposure:R01:1']['coefficients']==[500,500]
    assert rows['sector_exposure:C01:1']['coefficients']==[500,500]
    assert rows['resource:U01:S03:3']['coefficients']==[7,7]
    assert [r['id'] for r in model['rows']]==sorted(rows)
    assert model['specification_sha256']==spec.canonical_sha256(spec.load_spec(public))


def test_exact_projection_of_every_tiny_plan_matches_the_independent_B_group_checks():
    public=inputs.fixture(projects=2)
    public['shared_limits']['annual_new_lp_pence']['S01']['1']=150
    model=model_b.build_model(public)
    for bits in range(4):
        plan={'P001':bits&1,'P002':(bits>>1)&1}
        source=ledger.simulate(public,plan);actual=model_b.check_plan(model,plan)
        expected={r['id']:(r['lhs'],r['limit'],r['passed']) for r in source['constraints']}
        assert {r['id']:(r['lhs'],r['limit'],r['passed']) for r in actual['rows']}==expected
        assert actual['passed']==source['feasible']
        if source['feasible']:assert actual['objective_pence']==source['objective_pence']


@pytest.mark.parametrize('change',['tag','NPV','annual','missing_scenario','forged_flag'])
def test_provided_universe_is_replayed_not_trusted_by_tag_or_flags(change):
    public=inputs.fixture(scenarios=2);universe=ledger.simulate_universe(public)
    if change=='tag':universe['financial_implementation']='Fraction'
    elif change=='NPV':universe['projects']['P001']['scenarios']['S01']['npv_pence']+=1
    elif change=='annual':universe['projects']['P001']['scenarios']['S01']['annual'][0]['lp_call']+=1
    elif change=='missing_scenario':del universe['projects']['P001']['scenarios']['S02']
    else:universe['all_standalone_feasible']=False
    with pytest.raises(ValueError,match='supplied B universe'):
        model_b.build_model(public,universe)


def test_even_an_unselected_infeasible_candidate_blocks_model_build():
    public=inputs.fixture(projects=2);public['projects'][1]['lp_commitment_pence']=0
    with pytest.raises(ValueError,match='Every candidate'):
        model_b.build_model(public)


def test_site_choice_and_prerequisite_have_distinct_exact_integer_columns():
    public=inputs.fixture(projects=3)
    public['exclusivity_groups']=[{'id':'SITE','description':'Two technology alternatives at one site','project_ids':['P001','P002']}]
    public['prerequisites']=[{'id':'ACCESS','prerequisite':'P001','dependent':'P003','business_reason':'The operating site requires this funded connection'}]
    rows={r['id']:r for r in model_b.build_model(public)['rows']}
    assert rows['exclusivity:SITE']['coefficients']==[1,1,0] and rows['exclusivity:SITE']['limit']==1
    assert rows['prerequisite:ACCESS']['coefficients']==[-1,0,1] and rows['prerequisite:ACCESS']['limit']==0


@pytest.mark.parametrize('change',['float','bool','missing_column','duplicate_row','unsorted','unsafe_sum','wrong_family','missing_sha'])
def test_canonical_integer_model_rejects_wrong_types_coverage_and_arithmetic(change):
    model=tiny_model()
    if change=='float':model['objective_pence'][0]=5.0
    elif change=='bool':model['rows'][0]['coefficients'][0]=True
    elif change=='missing_column':model['rows'][0]['coefficients'].pop()
    elif change=='duplicate_row':model['rows'].append(deepcopy(model['rows'][0]))
    elif change=='unsorted':
        other=deepcopy(model['rows'][0]);other['id']='capacity:aaa';model['rows'].append(other)
    elif change=='unsafe_sum':model['objective_pence']=[2**52,2**52,0]
    elif change=='wrong_family':model['rows'][0]['family']='different'
    else:del model['universe_sha256']
    with pytest.raises(ValueError):model_b.validate_model(model)


def test_complete_integer_plan_and_full_hamming_exclusion_are_checked():
    model=tiny_model();best={'P001':1,'P002':0,'P003':1}
    assert model_b.check_plan(model,best)['objective_pence']==8
    assert not model_b.check_plan(model,best,exclude_plan=best)['passed']
    assert not model_b.check_plan(model,{'P001':1,'P002':1,'P003':1})['all_integer_rows_passed']
    with pytest.raises(ValueError):model_b.check_plan(model,{'P001':1})
    with pytest.raises(ValueError):model_b.check_plan(model,{'P001':True,'P002':0,'P003':1})
    with pytest.raises(ValueError):model_b.check_plan(model,best,exclude_plan={'P001':1})


@pytest.mark.parametrize('limit,threads',[(True,2),(0,2),(-1,2),(float('inf'),2),(1,True),(1,0),(1,3)])
def test_invalid_solver_limits_fail_before_import_or_execution(monkeypatch,limit,threads):
    monkeypatch.setattr(model_b,'_solver',lambda:pytest.fail('Invalid request imported a solver'))
    with pytest.raises(ValueError):model_b.solve_cp_sat(tiny_model(),time_limit_seconds=limit,threads=threads)


def test_solver_artifacts_cannot_overwrite_previous_attempts(tmp_path,monkeypatch):
    model=tmp_path/'existing.pbtxt';model.write_text('UNIT original')
    monkeypatch.setattr(model_b,'_solver',lambda:pytest.fail('Existing artifacts imported a solver'))
    with pytest.raises(ValueError,match='Preserve existing'):
        model_b.solve_cp_sat(tiny_model(),time_limit_seconds=1,model_path=model)
    assert model.read_text()=='UNIT original'


def test_compiler_full_production_geometry_uses_only_an_explicit_mock_finance_universe(monkeypatch):
    public=inputs.production_shape();ids=public['project_ids'];scenarios=public['scenario_ids'];years=public['years']
    def forbidden(*_):pytest.fail('Actual production financial forward is not authorized')
    monkeypatch.setattr(ledger,'_project',forbidden)
    fake={'kind':'UNIT_mock_financial_universe_not_a_source','version':1,'financial_implementation':'Decimal',
        'specification_sha256':spec.canonical_sha256(spec.load_spec(public)),'project_order':ids,
        'scenario_ids':scenarios,'years':years,'all_standalone_feasible':True,'projects':{}}
    for index,pid in enumerate(ids):
        fake['projects'][pid]={'scenarios':{sid:{'t0':{key:0 for key in spec.T0_FIELDS},'feasible':True,
            'npv_pence':index+1,'annual':[{**{key:0 for key in spec.ANNUAL_FIELDS},'year':year} for year in years]}
            for sid in scenarios}}
    monkeypatch.setattr(ledger,'simulate_universe',lambda _:fake)
    model=model_b.build_model(public)
    assert len(model['project_ids'])==len(model['objective_pence'])==240 and model['objective_pence'][-1]==240
    assert len(model['rows'])==881
    assert Counter(r['family'] for r in model['rows'])=={'initial_sponsor_equity':1,'annual_new_lp':60,
        'annual_debt_close':60,'resource':360,'region_exposure':120,'sector_exposure':160,'exclusivity':40,'prerequisite':80}
    assert all(len(r['coefficients'])==240 for r in model['rows'])
    assert next(r for r in model['rows'] if r['id']=='resource:U06:S03:20')['coefficients'][-1]==7


def test_no_A_compiler_or_financial_code_is_imported_or_read():
    tree=ast.parse(Path(model_b.__file__).read_text())
    imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    assert not any(name and ('candidate_a' in name or 'model_a' in name or 'pyscip' in name) for name in imports)
    text=Path(model_b.__file__).read_text()
    assert 'readProblem' not in text and 'readSol' not in text
    assert not any(isinstance(n,ast.ImportFrom) and n.module and n.module.startswith('ortools') for n in tree.body)


def test_real_CP_SAT_tiny_best_runner_infeasible_and_unknown_in_pinned_subprocess(tmp_path):
    python=ROOT/'outputs/tmp/linear-solver-914-py312/bin/python'
    assert python.exists(), 'Root-approved pinned toy solver environment is required'
    path=tmp_path/'tiny_model.json';path.write_text(json.dumps(tiny_model()))
    # Match the standalone private runtime transport. The repository's ordinary
    # workbook.__init__ imports openpyxl; the pure optimizer needs no workbook
    # dependency and must not silently install it in the pinned solver env.
    package=tmp_path/'bundle/sheets_factory/workbook/linear_capital_portfolio'
    package.mkdir(parents=True)
    for directory in [package,package.parent,package.parent.parent]:
        (directory/'__init__.py').write_bytes(b'')
    for name in ['model_b.py','ledger.py','spec.py']:
        shutil.copyfile(ROOT/'src/sheets_factory/workbook/linear_capital_portfolio'/name,package/name)
    script='''
import sys
sys.dont_write_bytecode=True
import json
from pathlib import Path
from types import SimpleNamespace
from sheets_factory.workbook.linear_capital_portfolio import model_b
from ortools.sat.python import cp_model
out=Path(sys.argv[1]);model=json.loads((out/'tiny_model.json').read_text())
best=model_b.solve_cp_sat(model,time_limit_seconds=2,threads=2,log_path=out/'best.log',model_path=out/'best.pbtxt')
assert best['status']=='OPTIMAL' and best['checked_optimal'] and best['objective_pence']==8
assert best['plan']=={'P001':1,'P002':0,'P003':1} and best['exact_plan_check']['passed']
runner=model_b.solve_cp_sat(model,time_limit_seconds=2,threads=2,exclude_plan=best['plan'])
assert runner['status']=='OPTIMAL' and runner['objective_pence']==7 and runner['plan']!=best['plan']
assert runner['exclude_plan']==best['plan'] and runner['exact_plan_check']['excluded_plan_distinct']
unknown=model_b.solve_cp_sat(model,time_limit_seconds=1e-9,threads=2)
assert unknown['status']=='UNKNOWN' and unknown['plan'] is None and unknown['checked_optimal'] is False
bad=json.loads(json.dumps(model));bad['rows'][0]['coefficients']=[0,0,0];bad['rows'][0]['limit']=-1
infeasible=model_b.solve_cp_sat(bad,time_limit_seconds=2,threads=2)
assert infeasible['status']=='INFEASIBLE' and infeasible['plan'] is None and not infeasible['checked_optimal']
# Regression-only mock status: a genuine feasible plan cannot promote FEASIBLE
# to optimal merely because exact arithmetic happens to verify its incumbent.
class FeasibleStatus:
 def __init__(self):self.native=cp_model.CpSolver()
 @property
 def parameters(self):return self.native.parameters
 def solve(self,model):self.native.solve(model);return cp_model.FEASIBLE
 def __getattr__(self,key):return getattr(self.native,key)
model_b._solver=lambda:SimpleNamespace(CpModel=cp_model.CpModel,CpSolver=FeasibleStatus,
 OPTIMAL=cp_model.OPTIMAL,FEASIBLE=cp_model.FEASIBLE,UNKNOWN=cp_model.UNKNOWN,
 INFEASIBLE=cp_model.INFEASIBLE,MODEL_INVALID=cp_model.MODEL_INVALID)
feasible=model_b.solve_cp_sat(model,time_limit_seconds=2)
assert feasible['status']=='FEASIBLE' and feasible['plan'] is not None and not feasible['checked_optimal']
assert best['gap_parameters']=={'relative':0,'absolute':0}
parameters=(out/'best.pbtxt.parameters.pbtxt').read_text()
assert 'relative_gap_limit: 0' in parameters and 'absolute_gap_limit: 0' in parameters
assert 'num_search_workers: 2' in parameters
assert best['model_artifact_format']=='CpModelProto text' and 'floating_point_objective' not in (out/'best.pbtxt').read_text()
assert best['formal_global_certificate'] is best['second_solve_automatically_started'] is False
(out/'results.json').write_text(json.dumps({'best':best,'runner':runner,'unknown':unknown,'infeasible':infeasible,'mock_feasible':feasible}))
print(json.dumps({'best':8,'runner':7,'unknown_status':unknown['status'],'infeasible_status':infeasible['status'],'mock_feasible_checked_optimal':feasible['checked_optimal']}))
'''
    environment=dict(os.environ,PYTHONPATH=str(tmp_path/'bundle'),PYTHONDONTWRITEBYTECODE='1',TMPDIR=str(tmp_path))
    completed=subprocess.run([str(python),'-c',script,str(tmp_path)],env=environment,capture_output=True,text=True,timeout=30)
    assert completed.returncode==0,completed.stdout+'\n'+completed.stderr
    result=json.loads((tmp_path/'results.json').read_text())
    assert result['best']['solver_version']=='9.14.6206'
    assert result['best']['parameters_reference'] and result['best']['model_reference'] and result['best']['log_reference']
    assert result['runner']['objective_pence']==7
