"""Small exact math and mocked raw-pool lifecycle; no production generation/services."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    loader = importlib.util.spec_from_file_location('_test_' + name, ROOT/'scripts'/(name+'.py'))
    value = importlib.util.module_from_spec(loader); loader.loader.exec_module(value)
    return value


pool = script('prepare_linear_capital_scaled_catalog')
driver = script('run_linear_capital_scaled_finance')
fixtures = script('../tests/test_linear_capital_candidate_a')


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value)+'\n')
    return driver.reference(path)


def tiny_raw(tmp_path):
    public = fixtures.toy(years=3, projects=3, scenarios=2)
    public.update(kind=driver.spec.SPEC_KIND, version=2)
    public['projects'][0].update(asset_cost_pence=101, t0_ltv_bp=5000,
        bank_rate_bp=1000, debt_policy='LEVEL_PRINCIPAL', debt_maturity_year=2)
    source = dump(tmp_path/'raw/specification.json', public)
    recipe = tmp_path/'raw/raw_recipe.txt'; recipe.write_text('Explicit toy fixture, not a catalog source.\n')
    plans = [{'id':'empty','plan':{pid:0 for pid in public['project_ids']}},
             {'id':'all','plan':{pid:1 for pid in public['project_ids']}}]
    raw = dump(tmp_path/'raw/preparation.json', {'kind':driver.RAW_KIND,'version':2,
        'specification':source,'specification_sha256':driver.spec.canonical_sha256(public),
        'recipe_sha256':{str(recipe):driver.reference(recipe)['sha256']},'diagnostic_plans':plans})
    return raw, public


@pytest.fixture
def services(monkeypatch):
    state = {'started':0,'stopped':0}
    class Dashboard:
        def __init__(self,*args,**kwargs): pass
        def start(self): state['started'] += 1; return 'mock://no-network-service'
        def stop(self): state['stopped'] += 1
    monkeypatch.setattr(driver,'DashboardServer',Dashboard)
    monkeypatch.setattr(driver.model_a,'solve_scip',lambda *a,**k:pytest.fail('No optimization'))
    monkeypatch.setattr(driver.model_b,'solve_cp_sat',lambda *a,**k:pytest.fail('No optimization'))
    return state


@pytest.fixture
def raw_pool(monkeypatch):
    """Exercise the full twenty-ref protocol with synthetic format-only dictionaries."""
    calls = []
    def build(seed, width):
        calls.append((seed,width))
        return {'dimension_mode':'production','project_ids':[f'P{i:03d}' for i in range(1,361)],
            'explicit_mock_raw_format_only':True,'seed':seed,'width':width}
    def plans(public,*,seed):
        return [{'id':f'fixed-{index:02d}','plan':{pid:int((i+index)%2==0)
            for i,pid in enumerate(public['project_ids'])}} for index in range(18)]
    monkeypatch.setattr(pool.catalog,'build_competitive_spec',build)
    monkeypatch.setattr(pool.catalog,'diagnostic_plans',plans)
    monkeypatch.setattr(pool.spec,'load_spec',lambda value:deepcopy(value))
    return calls


@pytest.mark.parametrize('change',['short','duplicate_id','duplicate_coordinate','bool_seed',
    'bool_width','negative_width','excess_width','first_member','unknown_field'])
def test_complete_prospective_declaration_rejects_subset_ambiguity_and_typed_changes(change):
    value = deepcopy(pool.PROPOSED_DECLARATION)
    if change=='short': value['profiles'].pop()
    if change=='duplicate_id': value['profiles'][1]['id']=value['profiles'][0]['id']
    if change=='duplicate_coordinate':
        value['profiles'][1].update(seed=value['profiles'][0]['seed'],
            revenue_jitter_pence=value['profiles'][0]['revenue_jitter_pence'])
    if change=='bool_seed': value['profiles'][0]['seed']=True
    if change=='bool_width': value['profiles'][0]['revenue_jitter_pence']=False
    if change=='negative_width': value['profiles'][0]['revenue_jitter_pence']=-1
    if change=='excess_width': value['profiles'][0]['revenue_jitter_pence']=pool.catalog.MAX_REVENUE_JITTER_PENCE+1
    if change=='first_member': value['first_development_profile']=value['profiles'][1]['id']
    if change=='unknown_field': value['winner']='P001'
    with pytest.raises(ValueError): pool.validate_declaration(value)


def test_proposal_is_only_a_complete_ordered_declaration_not_generated_raw():
    declared = pool.validate_declaration(pool.PROPOSED_DECLARATION)
    assert [row['seed'] for row in declared['profiles']]==list(range(202701361,202701381))
    assert [row['id'] for row in declared['profiles']]==[f'L360-P{i:02d}' for i in range(1,21)]
    assert all(row['revenue_jitter_pence']==150000 for row in declared['profiles'])
    declared['profiles'][0]['seed']=0
    assert pool.PROPOSED_DECLARATION['profiles'][0]['seed']==202701361


def test_all_raw_refs_and_fixed_plans_are_frozen_before_finance(tmp_path,raw_pool,monkeypatch):
    output=tmp_path/'pool'; original=pool.catalog.build_competitive_spec
    def build(seed,width):
        assert pool.read(output/'started.json')['all_profiles_declared_before_generation'] is True
        assert pool.read(output/'declaration.json')==pool.PROPOSED_DECLARATION
        return original(seed,width)
    monkeypatch.setattr(pool.catalog,'build_competitive_spec',build)
    receipt=pool.prepare(output); manifest=pool.validate_prepared(output)
    assert pool.read(receipt)==manifest and len(raw_pool)==20
    assert len(manifest['profiles'])==20 and pool.zero_claims(manifest)
    all_specs={row['profile_id']:row['specification'] for row in manifest['profiles']}
    for row in manifest['profiles']:
        raw=pool.read(row['raw_preparation'])
        assert raw['all_specifications_frozen_before_finance']==all_specs
        assert len(raw['diagnostic_plans'])==18 and pool.zero_claims(raw)
    # Finance preparation recognizes the exact same complete-pool transport, without forward math.
    raw=manifest['profiles'][0]['raw_preparation']
    monkeypatch.setattr(driver.finance,'build_universe_a',lambda *a:pytest.fail('Prepare is zero-forward'))
    prepared=driver.prepare(raw,tmp_path/'finance')
    assert driver.read(prepared)['diagnostic_plan_ids']==[f'fixed-{i:02d}' for i in range(18)]


def test_raw_pool_failure_retains_declared_whole_pool_and_all_partial_sources(tmp_path,raw_pool,monkeypatch):
    original=pool.catalog.build_competitive_spec
    def build(seed,width):
        if len(raw_pool)==2: raise RuntimeError('Explicit mock source failure')
        return original(seed,width)
    monkeypatch.setattr(pool.catalog,'build_competitive_spec',build)
    output=tmp_path/'pool'
    with pytest.raises(RuntimeError): pool.prepare(output)
    failure=pool.read(output/'failure.json')
    assert failure['all_partial_profiles_preserved'] and not failure['selected_subset_produced']
    assert len(pool.read(output/'declaration.json')['profiles'])==20
    assert len(list(output.glob('*/specification.json')))==2
    assert not list(output.glob('*/preparation.json')) and not (output/'catalog_manifest.json').exists()
    with pytest.raises(ValueError): pool.prepare(output)


@pytest.mark.parametrize('change',['peer_source','fixed_plan','model_claim'])
def test_cold_raw_pool_validation_rejects_changed_peer_or_inventory(tmp_path,raw_pool,change):
    output=tmp_path/'pool';pool.prepare(output);manifest=pool.validate_prepared(output)
    row=manifest['profiles'][0]
    if change=='peer_source':
        Path(manifest['profiles'][-1]['specification']['path']).write_text('{}')
    else:
        path=Path(row['raw_preparation']['path']);raw=json.loads(path.read_text())
        if change=='fixed_plan':raw['diagnostic_plans'].pop()
        else:raw['model_calls']=True
        path.write_text(json.dumps(raw))
        row['raw_preparation']=pool.reference(path)
        (output/'catalog_manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):pool.validate_prepared(output)
    with pytest.raises(ValueError):driver.prepare(row['raw_preparation'],tmp_path/'finance')


def test_zero_forward_preparation_and_exact_tiny_direct_nine_ref_finance(tmp_path,services,monkeypatch):
    raw,public=tiny_raw(tmp_path)
    with pytest.raises(ValueError): driver.prepare(raw,tmp_path/'production_required')
    original=driver.finance.build_universe_a
    monkeypatch.setattr(driver.finance,'build_universe_a',lambda *a:pytest.fail('Prepare cannot run financial math'))
    output=tmp_path/'finance';prepared=driver.prepare(raw,output,allow_toy=True)
    assert services['started']==0 and not (output/'started.json').exists()
    monkeypatch.setattr(driver.finance,'build_universe_a',original)
    terminal_ref=driver.execute_prepared(output);terminal=driver.read(terminal_ref)
    assert terminal['kind']=='linear_capital_scaled_full_financial_crosscheck' and terminal['version']==2
    assert terminal['passed'] and terminal['toy_only'] and terminal['qualified'] is False
    assert services=={'started':1,'stopped':1}
    direct=('specification','raw_preparation','universe_A','universe_B','model_A','model_B',
        'complete_financial_comparison','all_predeclared_plan_comparison','complete_matrix_comparison')
    assert all(driver.reference(terminal[key]['path'])==terminal[key] for key in direct)
    assert 'records' not in terminal and all(terminal[key]==0 for key in driver.ZERO_FIELDS)
    assert terminal['specification']==driver.read(raw)['specification']
    assert driver.read(terminal['complete_financial_comparison'])['passed']
    assert driver.read(terminal['all_predeclared_plan_comparison'])['plan_count']==2
    matrix=driver.read(terminal['complete_matrix_comparison'])
    assert matrix['passed'] and matrix['project_count']==3
    assert matrix['all_integer_coefficients_compared']==matrix['all_business_rows']*3
    from sheets_factory.workbook.linear_capital_scaled import reference
    assert terminal['recipe']==reference.finance_recipes() and len(terminal['recipe'])==10
    assert driver.read(prepared)['recipe']==terminal['recipe']
    assert json.loads((output/'producer.lock').read_text())['status']=='released'
    with sqlite3.connect(output/'audit/run.sqlite') as db:
        nodes=[json.loads(row[0]) for row in db.execute('SELECT payload FROM nodes')]
    assert len(nodes)==7 and all(row['status']=='completed' and row['duration_ms']>=0 for row in nodes)
    before=terminal_ref.copy()
    with pytest.raises(ValueError,match='first finance attempt'):driver.execute_prepared(output)
    assert driver.reference(before['path'])==before


@pytest.mark.parametrize('failure_stage',['universe_B','comparison','matrix'])
def test_first_failure_is_terminal_with_partial_outputs_and_no_retries(tmp_path,services,monkeypatch,failure_stage):
    raw,_=tiny_raw(tmp_path);output=tmp_path/'finance';driver.prepare(raw,output,allow_toy=True)
    if failure_stage=='universe_B':
        def fail(*args): raise RuntimeError('Explicit fixture failure')
        monkeypatch.setattr(driver.finance,'build_universe_b',fail)
    elif failure_stage=='comparison':
        original=driver.finance.compare_universes
        monkeypatch.setattr(driver.finance,'compare_universes',lambda *a:{**original(*a),'passed':False})
    else:
        original=driver.model_b.build_model
        def wrong(*args):
            model=original(*args);model['objective_pence'][0]+=1;return model
        monkeypatch.setattr(driver.model_b,'build_model',wrong)
    with pytest.raises(RuntimeError,match='failed first finance attempt'):driver.execute_prepared(output)
    terminal=driver.read(output/'terminal.json')
    assert not terminal['passed'] and terminal['qualified'] is False
    assert 'universe_A' in terminal and 'failure' in terminal
    assert services=={'started':1,'stopped':1}
    assert json.loads((output/'producer.lock').read_text())['status']=='released'
    with pytest.raises(ValueError):driver.execute_prepared(output)


@pytest.mark.parametrize('change',['raw_input','recipe','plan_ids','zero_bool'])
def test_cold_preflight_refuses_tampered_identity_before_any_execution(tmp_path,services,change):
    raw,_=tiny_raw(tmp_path);output=tmp_path/'finance';driver.prepare(raw,output,allow_toy=True)
    path=output/'preparation.json';frozen=json.loads(path.read_text())
    if change=='raw_input':Path(driver.read(raw)['specification']['path']).write_text('{}')
    if change=='recipe':frozen['execution_recipe'].pop(next(iter(frozen['execution_recipe'])))
    if change=='plan_ids':frozen['diagnostic_plan_ids'].pop()
    if change=='zero_bool':frozen['LO_calls']=False
    path.write_text(json.dumps(frozen))
    with pytest.raises(ValueError):driver.execute_prepared(output)
    assert services['started']==0 and not (output/'started.json').exists()


def test_cli_defaults_zero_execution_and_runs_only_when_explicit(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(driver,'prepare',lambda *a,**k:calls.append(('prepare',a,k)) or {'prepared':True})
    monkeypatch.setattr(driver,'validate_prepared',lambda *a:({'validated':True},{},{}))
    monkeypatch.setattr(driver,'execute_prepared',lambda *a,**k:calls.append(('execute',a,k)) or {'done':True})
    argv=['--raw-preparation',str(tmp_path/'raw'),'--output',str(tmp_path/'finance')]
    assert driver.main(argv)==0 and [c[0] for c in calls]==['prepare']
    calls.clear();assert driver.main(argv+['--run'])==0
    assert [c[0] for c in calls]==['prepare','execute']
    calls.clear();assert driver.main(['--prepared',str(tmp_path/'finance')])==0 and not calls
    assert driver.main(['--prepared',str(tmp_path/'finance'),'--run'])==0
    assert [c[0] for c in calls]==['execute']
