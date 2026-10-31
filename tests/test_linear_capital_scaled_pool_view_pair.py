"""Fixed-pool identity and original paired lifecycle; all execution APIs mocked."""
import ast
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


entry = load(ROOT/'scripts/prepare_linear_capital_scaled_pool_view_pair.py', '_pool_pair_tests')
base_tests = load(ROOT/'tests/test_linear_capital_scaled_view_pair.py', '_pool_original_fixture')
base_tests.entry = entry  # Only the isolated test fixture namespace uses the new API.


@pytest.fixture
def boundary(tmp_path, monkeypatch):
    root, manifest, source, events, state = base_tests.boundary.__wrapped__(tmp_path, monkeypatch)
    _, configuration = entry.policy()
    order = configuration['profile_order']; rows = []
    for i, identity in enumerate(order):
        specification = base_tests.dump(root/identity/'specification.json', {'explicit_mock_raw_profile':identity})
        raw = base_tests.dump(root/identity/'raw_preparation.json', {
            'kind':'prepared_linear_capital_scaled_raw_assumptions','version':2,
            'profile_id':identity,'seed':202701361+i,'revenue_jitter_pence':150000,
            'specification':specification,'prospective_profile_order':order})
        finance = base_tests.dump(root/identity/'finance.json', {'explicit_mock_finance_profile':identity})
        rows.append({'profile_id':identity,'seed':202701361+i,'revenue_jitter_pence':150000,
            'specification':specification,'raw_preparation':raw,'financial_crosscheck':finance})
    configuration['profiles'] = rows
    configuration['raw_catalog'] = base_tests.dump(root/'catalog.json', {
        'kind':'prepared_scaled_linear_complete_raw_pool','version':2,'profile_order':order,
        'first_development_profile':'L360-P01','all_profiles_frozen_before_financial_execution':True,
        'profiles':[{k:v for k,v in row.items() if k!='financial_crosscheck'} for row in rows]})
    configuration['finance_inventory'] = base_tests.dump(root/'finance_inventory.json', {
        'kind':'completed_scaled_linear_finance_terminal_inventory','version':2,
        'raw_catalog':configuration['raw_catalog'],'profile_order':order,
        'profiles':[{'profile_id':row['profile_id'],'terminal':row['financial_crosscheck']} for row in rows]})
    config_ref = base_tests.dump(root/'policy.json', configuration)
    monkeypatch.setattr(entry,'policy',lambda path=entry.CONFIG:(config_ref, deepcopy(configuration)))

    def select(identity):
        row = next(row for row in rows if row['profile_id']==identity)
        independent = {'kind':configuration['reference_kind'],'passed':True,
            'raw_preparation':row['raw_preparation'],'specification':row['specification'],
            'financial_crosscheck':row['financial_crosscheck'],'explicit_mock_reference':True}
        source['independent_reference'] = base_tests.dump(root/(identity+'_reference.json'), independent)
        source['public_specification'] = row['specification']
        source['financial_crosscheck'] = row['financial_crosscheck']
        updated = base_tests.dump(root/'source_manifest.json', source)
        manifest.clear(); manifest.update(updated)
        return manifest

    def plan(source_path, specification, bindings, *, mode):
        events.append('plan_'+mode)
        assert source_path==source['workbook']['path']
        assert specification==source['public_specification']['path'] and bindings==source['bindings']['path']
        return {'mode':mode,'explicit_mock_plan':True}
    monkeypatch.setattr(entry.task_views,'plan_task_view',plan)
    select('L360-P02')
    return root,manifest,source,events,state,configuration,select


@pytest.mark.parametrize('identity',['L360-P01','L360-P02','L360-P20'])
def test_any_exact_original_member_can_prepare_without_calls(boundary, identity):
    root,manifest,source,events,_,_,select = boundary; select(identity)
    result = entry.read(entry.prepare(manifest,root/'pair'))
    assert result['profile_id']==result['pool_identity']['profile_id']==identity
    assert result['pool_identity']['seed']==202701360+int(identity[-2:])
    assert events==['cold_source'] and result['workbooks_emitted']==result['LO_calls']==0
    assert result['mode_order']==['financial_modeling','debugging'] and not result['qualified']
    checked,_=entry.validate_prepared(root/'pair'); assert checked==result


def test_pool_retains_original_full_lifecycle_and_both_preparations(boundary):
    root,manifest,_,events,_,_,_=boundary;entry.prepare(manifest,root/'pair')
    terminal=entry.read(entry.execute_prepared(root/'pair'))
    first=events.index('execute_financial_modeling')
    assert all(events.index('prepare_'+mode)<first for mode in ('financial_modeling','debugging'))
    assert terminal['kind']==entry.KIND and terminal['profile_id']=='L360-P02'
    assert terminal['passed'] and terminal['LO_call_count_exact']==18 and not terminal['qualified']
    assert terminal['source_LO_calls_performed_by_this_bridge']==terminal['model_calls']==terminal['solver_calls']==0
    assert entry.read(root/'pair/producer.lock')['status']=='released'
    with pytest.raises(ValueError,match='first pair attempt'):entry.execute_prepared(root/'pair')


@pytest.mark.parametrize('attack',['unknown_member','seed','width','order','raw_ref','specification','finance','private_bytes','old_kind'])
def test_member_provenance_failures_do_not_emit_or_start_services(boundary,attack):
    root,manifest,source,events,_,_,_=boundary
    independent=entry.read(source['independent_reference']);raw=entry.read(independent['raw_preparation'])
    if attack=='unknown_member':raw['profile_id']='L360-P21'
    if attack=='seed':raw['seed']+=1
    if attack=='width':raw['revenue_jitter_pence']=250000
    if attack=='order':raw['prospective_profile_order'].reverse()
    if attack in ('unknown_member','seed','width','order','raw_ref'):
        independent['raw_preparation']=base_tests.dump(root/'different_raw_preparation.json',raw)
    if attack=='specification':independent['specification']=base_tests.dump(root/'other_spec.json',{'not_original':True})
    if attack=='finance':source['financial_crosscheck']=base_tests.dump(root/'other_finance.json',{'wrong':True})
    if attack=='private_bytes':source['public_specification']=base_tests.dump(root/'different_private.json',{'not_original':True})
    if attack=='old_kind':source['kind']='independently_verified_linear_capital_producer16_native_source'
    source['independent_reference']=base_tests.dump(root/'changed_reference.json',independent)
    bad=base_tests.dump(root/'bad_source_manifest.json',source)
    with pytest.raises(ValueError):entry.prepare(bad,root/'failed')
    assert entry.read(root/'failed/preparation_failure.json')['LO_calls']==0
    assert events==['cold_source'] and not (root/'failed/preparation.json').exists()


def test_cold_validation_requires_same_member_not_just_membership(boundary):
    root,manifest,_,events,_,_,select=boundary;entry.prepare(manifest,root/'pair')
    frozen=entry.read(root/'pair/preparation.json'); select('L360-P03')
    frozen['source_manifest']=manifest
    base_tests.dump(root/'pair/preparation.json',frozen)
    with pytest.raises(ValueError,match='admitted source'):entry.execute_prepared(root/'pair')
    assert 'server_started' not in events
    assert entry.read(root/'pair/execution_preflight_failure.json')['LO_calls']==0


@pytest.mark.parametrize('attack',['frozen_profile','frozen_identity','inventory','catalog'])
def test_cold_pool_bindings_cannot_be_replaced(boundary,attack):
    root,manifest,_,events,_,config,_=boundary;entry.prepare(manifest,root/'pair')
    frozen=entry.read(root/'pair/preparation.json')
    if attack=='frozen_profile':frozen['profile_id']='L360-P03'
    if attack=='frozen_identity':frozen['pool_identity']['seed']+=1
    if attack in ('inventory','catalog'):
        key='finance_inventory' if attack=='inventory' else 'raw_catalog'
        Path(config[key]['path']).write_text('{}')
    else:base_tests.dump(root/'pair/preparation.json',frozen)
    with pytest.raises(ValueError):entry.execute_prepared(root/'pair')
    assert 'server_started' not in events


def test_first_actual_api_failure_is_preserved_without_running_later_mode(boundary):
    root,manifest,_,events,state,_,_=boundary;entry.prepare(manifest,root/'pair')
    state['failure']='execute_financial_modeling'
    with pytest.raises(RuntimeError,match='Preserved failed'):entry.execute_prepared(root/'pair')
    terminal=entry.read(root/'pair/terminal.json')
    assert not terminal['passed'] and terminal['LO_call_count_exact'] is None
    assert terminal['partial_validation_terminals'] and 'execute_debugging' not in events
    assert entry.read(root/'pair/producer.lock')['status']=='released'


def test_exact_ast_keeps_execution_and_cli_algorithms_unchanged():
    old=ast.parse(entry.UPSTREAM.read_text());new=entry.adapted_ast()
    def function(tree,name):return next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    class RestorePanel(ast.NodeTransformer):
        def visit_Constant(self,node):
            if node.value=='Fixed-pool N360 paired task materialization and actual validation':
                node.value='P01 paired N360 task materialization and actual validation'
            return node
    for name in ('execute_prepared','main','guard','support'):
        assert ast.dump(function(old,name))==ast.dump(RestorePanel().visit(function(new,name)))


def test_frozen_upstream_and_policy_bytes_are_strict(monkeypatch,tmp_path):
    assert entry.reference(entry.UPSTREAM)['sha256']==entry.UPSTREAM_SHA256
    _,configuration=entry.policy();rows=entry._pool_evidence(configuration)
    assert len(rows)==20 and rows[0]['profile_id']=='L360-P01' and rows[-1]['profile_id']=='L360-P20'
    assert configuration['first_development_profile']=='L360-P01'
    assert configuration['resources']=={'cpus':2,'memory_bytes':34359738368,'pids_limit':256}
    assert configuration['required_actual_LO_calls']=={'financial_modeling':7,'debugging':11}
    changed=tmp_path/'policy.json';changed.write_text('{}')
    with pytest.raises(ValueError,match='policy changed'):entry.policy(changed)
    monkeypatch.setattr(entry,'UPSTREAM_SHA256','0'*64)
    with pytest.raises(ValueError,match='frozen complete'):entry.adapted_ast()
