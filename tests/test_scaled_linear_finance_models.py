"""Small exact financial/matrix parity and standalone transport; no native solve."""
import ast
from copy import deepcopy
import hashlib
import importlib.util
from itertools import product
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sheets_factory.workbook.linear_capital_scaled import finance, model_a, model_b, spec
from sheets_factory.workbook.linear_capital_portfolio import (
    candidate_a as old_a, ledger as old_b, model_a as old_ma, model_b as old_mb, spec as old_spec)

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location('_scaled_finance_small_raw_fixture', ROOT/'tests/test_linear_capital_candidate_a.py')
fixtures = importlib.util.module_from_spec(loader); loader.loader.exec_module(fixtures)


def raw(**kwargs):
    value = fixtures.toy(**kwargs)
    value.update(kind=spec.SPEC_KIND, version=spec.SPEC_VERSION)
    return value


def original(public):
    value = deepcopy(public)
    value.update(kind='hypothetical_ringfenced_linear_capital_portfolio', version=1)
    return value


def tiny_model(n=3):
    return {'kind':model_a.KIND,'version':2,'project_ids':[f'P{i:03d}' for i in range(1,n+1)],
        'objective_pence':[5,4,3][:n], 'rows':[{'id':'resource:U01:S01:1','family':'resource',
            'scenario_id':'S01','year':1,'coefficients':[2,2,1][:n],'limit':3}],
        'specification_sha256':'0'*64,'universe_sha256':'1'*64}


def test_separate_namespaces_preserve_original_globals_and_both_forward_equations():
    public = raw(years=5, projects=3, scenarios=2)
    public['projects'][0].update(asset_cost_pence=101, t0_ltv_bp=5000, bank_rate_bp=1000,
        debt_policy='LEVEL_PRINCIPAL', debt_maturity_year=2)
    before = deepcopy(public); prior = original(public)
    a,b = finance.build_universe_a(public),finance.build_universe_b(public)
    aa,bb = old_a.simulate_universe(prior),old_b.simulate_universe(prior)
    assert a['projects']==aa['projects'] and b['projects']==bb['projects']
    assert a['specification_sha256']==b['specification_sha256']==spec.canonical_sha256(public)
    assert finance.compare_universes(public,a,b)['passed']
    assert public==before and len(old_spec.PROJECT_IDS)==240 and len(spec.PROJECT_IDS)==360
    assert finance._module('candidate_a')._project is not old_a._project
    assert finance._module('ledger')._project is not old_b._project
    assert finance._module('candidate_a')._project.__globals__ is not old_a._project.__globals__
    assert finance._module('ledger')._project.__globals__ is not old_b._project.__globals__
    with pytest.raises(ValueError):old_spec.load_spec(public)


def test_both_complete_models_have_the_old_exact_rows_and_objectives_on_small_inputs():
    public = raw(years=3, projects=3, scenarios=3); prior=original(public)
    a,b = model_a.build_model(public),model_b.build_model(public)
    aa,bb = old_ma.build_model(prior),old_mb.build_model(prior)
    assert a['rows']==aa['rows']==b['rows']==bb['rows']
    assert a['objective_pence']==aa['objective_pence']==b['objective_pence']==bb['objective_pence']
    assert a['kind']==b['kind']==model_a.KIND and a['version']==b['version']==2
    assert len(a['rows'])==spec.expected_constraint_count(public)
    assert a['specification_sha256']==b['specification_sha256']==spec.canonical_sha256(public)
    assert a['universe_sha256']!=b['universe_sha256']


@pytest.mark.parametrize('side,forward',[(model_a,finance.build_universe_a),(model_b,finance.build_universe_b)])
@pytest.mark.parametrize('change',['NPV','missing_project','unselected_infeasible','old_raw_identity'])
def test_model_build_never_trusts_a_supplied_universe_or_silently_drops_candidates(side,forward,change):
    public=raw(years=3,projects=2,scenarios=2)
    if change=='unselected_infeasible':
        public['projects'][1]['lp_commitment_pence']=0
        with pytest.raises(ValueError):side.build_model(public)
        return
    if change=='old_raw_identity':
        with pytest.raises(ValueError):side.build_model(original(public))
        return
    universe=forward(public)
    if change=='NPV':universe['projects']['P001']['scenarios']['S01']['npv_pence']+=1
    else:del universe['projects']['P002']
    with pytest.raises(ValueError):side.build_model(public,universe)


def test_every_small_plan_and_full_exclusion_match_both_independent_aggregate_paths():
    public=raw(years=3,projects=3,scenarios=2)
    public['exclusivity_groups']=[{'id':'site','description':'Alternative units','project_ids':['P001','P002']}]
    public['prerequisites']=[{'id':'access','dependent':'P003','prerequisite':'P001','business_reason':'Funded access'}]
    a,b=finance.build_universe_a(public),finance.build_universe_b(public)
    ma,mb=model_a.build_model(public,a),model_b.build_model(public,b)
    plans=[]
    for bits in product((0,1),repeat=3):
        plan=dict(zip(public['project_ids'],bits));plans.append({'id':str(bits),'plan':plan})
        fa,fb=finance.simulate_a(public,plan),finance.simulate_b(public,plan)
        ca,cb=model_a.check_plan(ma,plan),model_b.check_plan(mb,plan)
        assert ca['feasible']==cb['passed']==fa['feasible']==fb['feasible']
        assert ca['objective_pence']==cb['objective_pence']
        if fa['feasible']:assert ca['objective_pence']==fa['objective_pence']==fb['objective_pence']
        assert not model_a.check_plan(ma,plan,exclude_plan=plan)['feasible']
        assert not model_b.check_plan(mb,plan,exclude_plan=plan)['passed']
    report=finance.compare_plans(public,a,b,plans)
    assert report['passed'] and report['plan_count']==8 and not report['differences_truncated']


def test_crosscheck_calls_each_independent_forward_once_and_retains_all_financial_differences(monkeypatch):
    public=raw(years=4,projects=2,scenarios=2);counts={'A':0,'B':0}
    a,b=finance._module('candidate_a'),finance._module('ledger')
    original_a,original_b=a.simulate_universe,b.simulate_universe
    def forward_a(s):counts['A']+=1;return original_a(s)
    def forward_b(s):counts['B']+=1;return original_b(s)
    monkeypatch.setattr(a,'simulate_universe',forward_a);monkeypatch.setattr(b,'simulate_universe',forward_b)
    report=finance.crosscheck(public)
    assert counts=={'A':1,'B':1} and report['passed']
    assert report['kind']=='independent_scaled_linear_capital_financial_crosscheck' and report['version']==2
    assert report['financial_universe_calls']=={'A':1,'B':1} and not report['financial_policy_changed']
    changed=deepcopy(report['universe_B'])
    for p in changed['projects'].values():
        for s in p['scenarios'].values():
            for row in s['annual']:row['revenue']+=1
    bad=finance.compare_universes(public,report['universe_A'],changed)
    assert not bad['passed'] and len(bad['differences'])==16 and not bad['differences_truncated']


@pytest.mark.parametrize('side',[model_a,model_b])
@pytest.mark.parametrize('change',['old_kind','old_version','bool_money','missing_column','wrong_order','unsafe_sum','five_projects'])
def test_new_models_reject_old_identity_and_invalid_typed_complete_scope(side,change):
    model=tiny_model()
    if change=='old_kind':model['kind']=old_ma.KIND
    elif change=='old_version':model['version']=1
    elif change=='bool_money':model['objective_pence'][0]=True
    elif change=='missing_column':model['rows'][0]['coefficients'].pop()
    elif change=='wrong_order':model['project_ids'].reverse()
    elif change=='unsafe_sum':model['objective_pence']=[2**52,2**52,0]
    else:
        model['project_ids']=[f'P{i:03d}' for i in range(1,6)]
        model['objective_pence']=[0]*5;model['rows'][0]['coefficients']=[0]*5
    with pytest.raises(ValueError):side.validate_model(model)


def production_matrix_fixture():
    rows=[]
    for family,count in spec.PRODUCTION_COUNTS.items():
        rows.extend({'id':f'{family}:{i:04d}','family':family,'scenario_id':None,'year':None,
            'coefficients':[0]*360,'limit':0} for i in range(count))
    return {'kind':model_a.KIND,'version':2,'project_ids':list(spec.PROJECT_IDS),
        'objective_pence':[0]*360,'rows':sorted(rows,key=lambda r:r['id']),
        'specification_sha256':'0'*64,'universe_sha256':'1'*64}


@pytest.mark.parametrize('side',[model_a,model_b])
def test_full_941_row_360_column_format_census_is_required_without_financial_or_native_execution(side):
    model=production_matrix_fixture();assert len(model['rows'])==941
    side.validate_model(model)
    missing=deepcopy(model);missing['rows'].pop()
    with pytest.raises(ValueError,match='941'):side.validate_model(missing)
    changed=deepcopy(model);changed['rows'][-1]['family']='resource'
    changed['rows'][-1]['id']='resource:zzzz';changed['rows'].sort(key=lambda r:r['id'])
    with pytest.raises(ValueError,match='941'):side.validate_model(changed)


@pytest.mark.parametrize('side,solve',[('A',model_a.solve_scip),('B',model_b.solve_cp_sat)])
def test_resource_worker_cap_default_and_rejections_occur_before_native_import(side,solve):
    import inspect
    assert inspect.signature(solve).parameters['threads'].default==2
    for value in (0,17,True):
        with pytest.raises(ValueError,match='thread|worker'):solve(tiny_model(),time_limit_seconds=1,threads=value)
    tree=model_a.adapted_ast() if side=='A' else model_b.adapted_ast()
    assert any(isinstance(n,ast.Compare) and ast.unparse(n)=='1 <= threads <= 16' for n in ast.walk(tree))


def test_complete_minimal_matrix_only_bundle_has_no_financial_builder_dependency(tmp_path):
    package=tmp_path/'portfolio';package.mkdir();(package/'__init__.py').write_bytes(b'')
    for module in (spec,model_a,model_b):
        (package/(module.__name__.rsplit('.',1)[-1]+'.py')).write_bytes(Path(module.__file__).read_bytes())
    for name,module in [('frozen_spec',spec),('frozen_model_a',model_a),('frozen_model_b',model_b)]:
        (package/(name+'.py')).write_bytes(module.upstream_path().read_bytes())
    model=tiny_model();(tmp_path/'matrix.json').write_text(json.dumps(model))
    program="import json,sys; from portfolio import model_a,model_b; m=json.load(open('matrix.json')); model_a.validate_model(m); model_b.validate_model(m); assert 'portfolio.finance' not in sys.modules; print('matrix-only-ok')"
    done=subprocess.run([sys.executable,'-B','-c',program],cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert done.returncode==0,done.stderr
    assert done.stdout.strip()=='matrix-only-ok'


@pytest.mark.parametrize('module',[model_a,model_b])
def test_pinned_model_source_rejects_any_modified_upstream(module,tmp_path,monkeypatch):
    bad=tmp_path/'changed.py';bad.write_bytes(module.upstream_path().read_bytes()+b'\n# changed\n')
    monkeypatch.setattr(module,'upstream_path',lambda:bad)
    with pytest.raises(ValueError,match='unchanged'):module.adapted_ast()


def test_pinned_financial_source_rejects_changed_bytes_even_with_warm_namespace(tmp_path,monkeypatch):
    finance._module('candidate_a')
    bad=tmp_path/'changed.py';bad.write_bytes(finance.upstream_path('candidate_a').read_bytes()+b'\n# changed\n')
    monkeypatch.setattr(finance,'upstream_path',lambda name:bad)
    with pytest.raises(ValueError,match='unchanged'):finance.build_universe_a(raw())


def test_original_financial_and_model_bytes_remain_the_exact_frozen_inputs():
    paths={**{finance.upstream_path(name):digest for name,digest in finance.UPSTREAMS.items()},
        model_a.upstream_path():model_a.UPSTREAM_SHA256,model_b.upstream_path():model_b.UPSTREAM_SHA256}
    assert all(hashlib.sha256(path.read_bytes()).hexdigest()==digest for path,digest in paths.items())
