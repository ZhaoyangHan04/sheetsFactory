"""Small exact matrices and real tiny SCIP calls; never solve production 240."""
from collections import Counter
from copy import deepcopy
import importlib.util
from itertools import product
import json
from pathlib import Path
import subprocess

import pytest

from sheets_factory.workbook.linear_capital_portfolio import candidate_a,model_a as m
from test_linear_capital_candidate_a import toy

ROOT=Path(__file__).resolve().parents[1]
SOLVER_PYTHON=ROOT/'outputs/tmp/linear-solver-914-py312/bin/python'


def matrix(objective=(7,5),*,capacity=1):
    count=len(objective)
    return {'kind':m.KIND,'version':1,'project_ids':[f'P{i:03d}' for i in range(1,count+1)],
        'objective_pence':list(objective),'rows':[{'id':'initial_sponsor_equity','family':'initial_sponsor_equity',
            'scenario_id':None,'year':None,'coefficients':[1]*count,'limit':capacity}],
        'specification_sha256':'a'*64,'universe_sha256':'b'*64}


def test_direct_matrix_matches_every_A_integer_business_constraint_on_four_small_plans():
    s=toy(years=3,projects=2,scenarios=2)
    s['projects'][0].update(t0_ltv_bp=5000,bank_rate_bp=1000,base_annual_revenue_pence=80)
    s['projects'][1].update(base_annual_revenue_pence=65,base_annual_opex_pence=10)
    s['prerequisites']=[{'id':'access','dependent':'P002','prerequisite':'P001','business_reason':'P002 requires P001 access'}]
    s['exclusivity_groups']=[{'id':'site','description':'One permitted site configuration','project_ids':['P001','P002']}]
    model=m.build_model(s)
    assert [r['id'] for r in model['rows']]==sorted(r['id'] for r in model['rows'])
    assert all(len(r['coefficients'])==2 for r in model['rows'])
    for bits in product((0,1),repeat=2):
        plan=dict(zip(s['project_ids'],bits));checked=m.check_plan(model,plan)
        financial=candidate_a.simulate(s,plan)
        expected={r['id']:(r['lhs'],r['limit'],r['passed']) for r in financial['constraints']}
        assert {r['id']:(r['lhs'],r['limit'],r['passed']) for r in checked['rows']}==expected
        assert checked['feasible']==financial['feasible']
        if checked['feasible']:assert checked['objective_pence']==financial['objective_pence']


def test_supplied_universe_is_recomputed_not_trusted():
    s=toy();universe=candidate_a.simulate_universe(s)
    original=m.build_model(s,universe)
    changed=deepcopy(universe);changed['projects']['P001']['scenarios']['S01']['npv_pence']+=1
    with pytest.raises(ValueError,match='differs'):m.build_model(s,changed)
    assert original==m.build_model(s)


def test_any_infeasible_candidate_is_retained_and_rejects_model():
    s=toy(projects=2);s['projects'][1]['lp_commitment_pence']=0
    with pytest.raises(ValueError,match='Every provided candidate'):m.build_model(s)


def test_cross_scenario_NBV_must_be_identical(monkeypatch):
    s=toy(scenarios=2);u=candidate_a.simulate_universe(s)
    u['projects']['P001']['scenarios']['S02']['annual'][0]['asset_nbv_close']+=1
    monkeypatch.setattr(candidate_a,'simulate_universe',lambda _:u)
    with pytest.raises(ValueError,match='NBV'):m.build_model(s)


def test_complete_production_shape_has_881_rows_with_explicit_fake_finance_boundary(monkeypatch):
    # Only a serialization/coverage fixture. No 240-project finance forward,
    # native optimizer, production source or workbook is evaluated.
    s=toy(years=20,projects=1,scenarios=3);s['dimension_mode']='production'
    s['project_ids']=[f'P{i:03d}' for i in range(1,241)]
    s['resource_ids']=[f'U{i:02d}' for i in range(1,7)]
    s['region_ids']=[f'R{i:02d}' for i in range(1,7)]
    s['sector_ids']=[f'C{i:02d}' for i in range(1,9)]
    p=s['projects'][0];usage=p['resource_usage_units']['U01']
    s['projects']=[]
    for index,pid in enumerate(s['project_ids']):
        row=deepcopy(p);row.update(id=pid,name='Shape fixture '+pid,
            region=s['region_ids'][index%6],sector=s['sector_ids'][index%8],
            resource_usage_units={resource:deepcopy(usage) for resource in s['resource_ids']})
        s['projects'].append(row)
    limits=s['shared_limits']
    limits['resource_capacity_units']={resource:deepcopy(limits['resource_capacity_units']['U01']) for resource in s['resource_ids']}
    limits['region_exposure_pence']={region:deepcopy(limits['region_exposure_pence']['R01']) for region in s['region_ids']}
    limits['sector_exposure_pence']={sector:deepcopy(limits['sector_exposure_pence']['C01']) for sector in s['sector_ids']}
    s['exclusivity_groups']=[{'id':f'G{i:02d}','description':'Declared alternative site fixture',
        'project_ids':s['project_ids'][2*i:2*i+2]} for i in range(40)]
    s['prerequisites']=[{'id':f'E{i:02d}','dependent':s['project_ids'][i+1],
        'prerequisite':s['project_ids'][i],'business_reason':'Declared earlier access fixture'} for i in range(80)]
    def fake(public):
        r={'t0':{'lp_call':1},'annual':[{'asset_nbv_close':1 if y<20 else 0,'lp_call':0,'debt_close':0}
            for y in public['years']],'feasible':True,'npv_pence':1}
        return {'specification_sha256':m._sha(public),'project_order':public['project_ids'],
            'all_standalone_feasible':True,'explicit_fake_shape_fixture':True,
            'projects':{pid:{'scenarios':{sid:deepcopy(r) for sid in public['scenario_ids']}} for pid in public['project_ids']}}
    monkeypatch.setattr(candidate_a,'simulate_universe',fake)
    model=m.build_model(s)
    assert len(model['rows'])==881
    assert Counter(r['family'] for r in model['rows'])==m.PRODUCTION_COUNTS
    assert len(model['objective_pence'])==240 and all(len(r['coefficients'])==240 for r in model['rows'])
    assert m.check_plan(model,{pid:0 for pid in s['project_ids']})['constraints_checked']==881


@pytest.mark.parametrize('change',['missing_column','duplicate_id','bool_coefficient','large_aggregate','large_limit','unsorted','bool_version','bad_hash'])
def test_matrix_tamper_fails_closed(change):
    model=matrix()
    if change=='missing_column':model['rows'][0]['coefficients'].pop()
    elif change=='duplicate_id':model['rows'].append(deepcopy(model['rows'][0]))
    elif change=='bool_coefficient':model['objective_pence'][0]=True
    elif change=='large_aggregate':model['rows'][0]['coefficients']=[m.EXACT_LIMIT-1,1]
    elif change=='large_limit':model['rows'][0]['limit']=m.EXACT_LIMIT
    elif change=='unsorted':
        another=deepcopy(model['rows'][0]);another['id']='aaa';model['rows'].append(another)
    elif change=='bool_version':model['version']=True
    else:model['universe_sha256']='not-a-hash'
    with pytest.raises(ValueError):m.validate_model(model)


@pytest.mark.parametrize('excluded',[(0,0),(0,1),(1,0),(1,1)])
def test_full_Hamming_exclusion_rejects_only_exact_original_plan(excluded):
    model=matrix(capacity=2);old=dict(zip(model['project_ids'],excluded))
    for bits in product((0,1),repeat=2):
        check=m.check_plan(model,dict(zip(model['project_ids'],bits)),exclude_plan=old)
        assert check['constraints_checked']==2
        assert check['feasible']==(bits!=excluded)


def test_negative_objectives_and_exact_integer_plan_validation():
    model=matrix((-5,-7),capacity=2)
    assert m.check_plan(model,{'P001':0,'P002':0})['objective_pence']==0
    assert m.check_plan(model,{'P001':1,'P002':1})['objective_pence']==-12
    for plan in ({'P001':True,'P002':0},{'P001':1.0,'P002':0},{'P001':0}):
        with pytest.raises(ValueError):m.check_plan(model,plan)


def test_solver_is_lazy_and_invalid_settings_never_import_or_run_native_solver(tmp_path,monkeypatch):
    import builtins
    original=builtins.__import__
    def controlled(name,*args,**kwargs):
        if name=='pyscipopt':pytest.fail('The invalid request reached the solver')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',controlled)
    for settings in ({'time_limit_seconds':True},{'time_limit_seconds':0},
        {'time_limit_seconds':float('inf')},{'time_limit_seconds':2,'threads':True},
        {'time_limit_seconds':2,'threads':3},{'time_limit_seconds':2,'exclude_plan':{'P001':1}}):
        with pytest.raises(ValueError):m.solve_scip(matrix(),**settings)
    existing=tmp_path/'existing.log';existing.write_text('old immutable result')
    with pytest.raises(ValueError):m.solve_scip(matrix(),time_limit_seconds=2,log_path=existing)
    assert existing.read_text()=='old immutable result'


@pytest.mark.skipif(not SOLVER_PYTHON.exists(),reason='Explicit isolated solver runtime is unavailable')
def test_real_tiny_SCIP_optimal_runner_tie_negative_and_infeasible(tmp_path):
    script=r'''
import json,sys,types
from pathlib import Path
namespace=types.ModuleType('isolated_A')
namespace.__path__=[str(Path(sys.argv[3]))];sys.modules['isolated_A']=namespace
from isolated_A.model_a import solve_scip
root=Path(sys.argv[1]);cases=json.loads(sys.argv[2]);out=[]
for index,case in enumerate(cases):
 out.append(solve_scip(case['model'],time_limit_seconds=case.get('time_limit_seconds',5),threads=1,
  exclude_plan=case.get('exclude_plan'),log_path=root/(str(index)+'.log'),model_path=root/(str(index)+'.cip')))
print(json.dumps(out,allow_nan=False))
'''
    cases=[{'model':matrix()},
        {'model':matrix(),'exclude_plan':{'P001':1,'P002':0}},
        {'model':matrix((5,5))},
        {'model':matrix((5,5)),'exclude_plan':{'P001':1,'P002':0}},
        {'model':matrix((-5,-7),capacity=2)},
        {'model':matrix((-5,-7),capacity=2),'exclude_plan':{'P001':0,'P002':0}},
        {'model':matrix((1,),capacity=0),'exclude_plan':{'P001':0}},
        {'model':matrix(),'time_limit_seconds':1e-12}]
    process=subprocess.run([str(SOLVER_PYTHON),'-c',script,str(tmp_path),json.dumps(cases),str(Path(m.__file__).parent)],
        cwd=tmp_path,env={'PYTHONPATH':str(ROOT/'src'),'PYTHONDONTWRITEBYTECODE':'1','TMPDIR':str(tmp_path)},
        text=True,capture_output=True,timeout=40,check=False)
    assert process.returncode==0,process.stderr
    results=json.loads(process.stdout.splitlines()[-1])
    assert [r['objective_pence'] for r in results[:6]]==[7,5,5,5,0,-5]
    for result in results[:6]:
        assert result['checked_optimal'] is True,result
        assert result['raw_status']=='optimal' and result['exact_integer_check']['feasible'] is True
        assert result['optimizer_calls']==1 and result['retry_count']==0 and result['gap']==0
        assert result['parameters']['limits/gap']==result['parameters']['limits/absgap']==0
        assert result['feasibility_tolerance_changed'] is False
        assert result['default_feasibility_tolerance']==1e-6
        assert result['model_artifact']['bytes']>0 and result['log_artifact']['bytes']>0
    assert results[1]['plan']=={'P001':0,'P002':1}
    assert results[5]['plan']=={'P001':1,'P002':0}
    assert results[6]['raw_status']=='infeasible' and results[6]['checked_optimal'] is False
    assert results[6]['plan'] is None and results[6]['exact_integer_check'] is None
    assert results[7]['raw_status']=='timelimit' and results[7]['checked_optimal'] is False
    assert results[7]['completed'] is True and results[7]['optimizer_calls']==1,results[7].get('solver_error')


def test_matrix_only_module_import_does_not_import_financial_forward(tmp_path):
    script='import sys;from sheets_factory.workbook.linear_capital_portfolio import model_a;assert not any(k.endswith("candidate_a") or k.endswith(".ledger") for k in sys.modules)'
    import sys
    subprocess.run([sys.executable,'-c',script],cwd=tmp_path,
        env={'PYTHONPATH':str(ROOT/'src'),'PYTHONDONTWRITEBYTECODE':'1','TMPDIR':str(tmp_path)},
        text=True,capture_output=True,check=True,timeout=10)
