"""Prospective first-profile pair and mocked API lifecycle; zero actual services."""
from contextlib import contextmanager
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]
loader=importlib.util.spec_from_file_location('_scaled_view_pair_test',ROOT/'scripts/prepare_linear_capital_scaled_view_pair.py')
entry=importlib.util.module_from_spec(loader);loader.loader.exec_module(entry)


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value)+'\n')
    return entry.reference(path)


@pytest.fixture
def boundary(tmp_path,monkeypatch):
    """Only real-file protocol and orchestration; finance and LO APIs are mocks."""
    helper=entry.support('source');validator=entry.support('validator');events=[];state={'failure':None}
    primitives=dump(tmp_path/'specification.json',{'explicit_mock_financial_boundary':True})
    binding=dump(tmp_path/'bindings.json',{'explicit_mock_binding_boundary':True})
    raw=dump(tmp_path/'raw_preparation.json',{'kind':'prepared_linear_capital_scaled_raw_assumptions','version':2,
        'profile_id':'L360-P01','seed':202701361,'revenue_jitter_pence':150000,'specification':primitives,
        'prospective_profile_order':[f'L360-P{i:02d}' for i in range(1,21)]})
    independent=dump(tmp_path/'reference.json',{'kind':'linear_capital_scaled_producer16_best_runner_dual_financial_reference',
        'passed':True,'raw_preparation':raw,'explicit_mock_optimization_boundary':True})
    workbook=tmp_path/'source.xlsx';workbook.write_bytes(b'Explicit mock audited workbook, not a production source')
    source={'kind':'independently_verified_linear_capital_scaled_native_source','version':1,
        'status':'source_verified_not_task_or_difficulty_qualified','source_financially_verified':True,'qualified':False,
        'workbook':entry.reference(workbook),'public_specification':primitives,'bindings':binding,
        'independent_reference':independent,'runtime_profile':entry.reference(helper.DEFAULT_PROFILE)}
    manifest=dump(tmp_path/'source_manifest.json',source)
    def validate_source(record):
        events.append('cold_source');value=deepcopy(helper.read(record))
        helper.checked(value['workbook'])
        return value
    monkeypatch.setattr(helper,'validate_source',validate_source)
    class Server:
        def __init__(self,*args,**kwargs):events.append('server_created')
        def start(self):events.append('server_started');return 'mock://no-http-service'
        def stop(self):events.append('server_stopped')
    monkeypatch.setattr(entry,'DashboardServer',Server)
    @contextmanager
    def temporary(output):
        events.append('temporary_entered');(output/'temporary').mkdir()
        try:yield {'temporary_directory':str(output/'temporary')}
        finally:events.append('temporary_exited')
    monkeypatch.setattr(helper,'_resource_support',lambda:SimpleNamespace(data_temporary=temporary))
    def plan(source_path,specification,bindings,*,mode):
        events.append('plan_'+mode)
        assert source_path==source['workbook']['path'] and specification==primitives['path'] and bindings==binding['path']
        return {'mode':mode,'explicit_mock_plan':True}
    monkeypatch.setattr(entry.task_views,'plan_task_view',plan)
    def materialize(plan,destination):
        mode=plan['mode'];events.append('materialize_'+mode)
        if state['failure']=='materialize_'+mode:raise ValueError('Explicit materialization fixture failure')
        path=Path(destination)/'private/view_manifest.json'
        return dump(path,{'mode':mode,'explicit_mock_materialization':True})
    monkeypatch.setattr(entry.task_views,'materialize_view',materialize)
    def prepare(source_ref,view_ref,output,*,source_provider):
        mode=helper.read(view_ref)['mode'];events.append('prepare_'+mode)
        assert source_ref==manifest and source_provider=='scaled360'
        if state['failure']=='prepare_'+mode:raise ValueError('Explicit validator preparation fixture failure')
        return dump(Path(output)/'preparation.json',{'mode':mode,'source_admission':source_ref,'materialized_view':view_ref})
    monkeypatch.setattr(validator,'prepare',prepare)
    def execute(output):
        output=Path(output);frozen=helper.read(output/'preparation.json');mode=frozen['mode'];events.append('execute_'+mode)
        pair=output.parents[1]
        prior=helper.read(pair/'both_validator_preparations_before_LO.json')
        assert list(prior['validator_preparations'])==['financial_modeling','debugging']
        assert all(Path(ref['path']).is_file() for ref in prior['validator_preparations'].values())
        calls=7 if mode=='financial_modeling' else 11
        result={'passed':True,'mode':mode,'source_provider':'scaled360','source_admission':manifest,
            'materialized_view':frozen['materialized_view'],'qualified':False,
            'actual_LO_calls':[{'explicit_mock_LO_not_actual':True,'index':i} for i in range(calls)]}
        if state['failure']=='execute_'+mode:
            result['passed']=False;result['actual_LO_calls']=result['actual_LO_calls'][:2]
        receipt=dump(output/'terminal.json',result)
        if not result['passed']:raise ValueError('Explicit actual-API fixture failure; no real LO')
        return receipt
    monkeypatch.setattr(validator,'execute_prepared',execute)
    def complete(receipt):
        value=helper.read(receipt);events.append('complete_'+value['mode'])
        if state['failure']=='cold_identity':value['source_provider']='old'
        return value
    monkeypatch.setattr(validator,'validate_completed',complete)
    return tmp_path,manifest,source,events,state


def test_fixed_policy_and_default_preparation_do_not_emit_or_execute(boundary):
    root,manifest,source,events,_=boundary;output=root/'pair'
    receipt=entry.prepare(manifest,output);frozen=entry.read(receipt)
    assert events==['cold_source'] and not (output/'financial_modeling').exists()
    assert frozen['mode_order']==['financial_modeling','debugging'] and frozen['profile_id']=='L360-P01'
    assert frozen['required_actual_LO_calls']=={'financial_modeling':7,'debugging':11}
    assert all(frozen[key]==0 for key in (*entry.ZERO_FIELDS,'workbooks_emitted'))
    assert not frozen['qualified'] and frozen['source_workbook']==source['workbook']
    assert all(str(output) in row['view_directory'] and str(output) in row['validation_directory'] for row in frozen['modes'])
    entry.validate_prepared(output);assert events==['cold_source','cold_source']


@pytest.mark.parametrize('attack',['different_profile','changed_seed','changed_width','old_reference','old_source','unverified_source','different_raw_bytes'])
def test_only_actual_original_first_profile_source_can_prepare(boundary,attack):
    root,manifest,source,events,_=boundary
    independent=entry.read(source['independent_reference']);raw=entry.read(independent['raw_preparation'])
    if attack=='different_profile':raw['profile_id']='L360-P02'
    if attack=='changed_seed':raw['seed']=202701362
    if attack=='changed_width':raw['revenue_jitter_pence']=100000
    if attack=='old_reference':independent['kind']='linear_capital_producer16_best_runner_dual_financial_reference'
    if attack=='old_source':source['kind']='independently_verified_linear_capital_producer16_native_source'
    if attack=='unverified_source':source['source_financially_verified']=False
    if attack=='different_raw_bytes':source['public_specification']=dump(root/'other_raw.json',{'changed':True})
    independent['raw_preparation']=dump(root/'changed_raw_preparation.json',raw)
    source['independent_reference']=dump(root/'changed_reference.json',independent)
    manifest=dump(root/'changed_source_manifest.json',source);output=root/'failed_pair'
    with pytest.raises(ValueError):entry.prepare(manifest,output)
    failure=entry.read(output/'preparation_failure.json')
    assert failure['workbooks_emitted']==failure['LO_calls']==failure['model_calls']==0
    assert not (output/'preparation.json').exists() and events==['cold_source']


def test_complete_both_preparations_precede_every_mocked_calculation_and_cleanup(boundary):
    root,manifest,_,events,_=boundary;output=root/'pair';entry.prepare(manifest,output)
    terminal_ref=entry.execute_prepared(output);terminal=entry.read(terminal_ref)
    first=events.index('execute_financial_modeling')
    assert all(events.index('prepare_'+mode)<first for mode in ('financial_modeling','debugging'))
    assert events.index('materialize_debugging')<events.index('prepare_financial_modeling')
    assert terminal['passed'] and terminal['LO_call_count_exact']==18
    assert list(terminal['validation_terminals'])==['financial_modeling','debugging']
    assert not terminal['qualified'] and not terminal['normal_quality_or_recovery_or_difficulty_certified']
    assert terminal['source_LO_calls_performed_by_this_bridge']==terminal['model_calls']==terminal['solver_calls']==terminal['Harbor_calls']==0
    assert terminal['actual_Harbor_verifier_executed'] is False
    assert events[-2:]==['temporary_exited','server_stopped']
    assert entry.read(output/'producer.lock')['status']=='released'
    with pytest.raises(ValueError,match='first pair attempt'):entry.execute_prepared(output)


@pytest.mark.parametrize('failure_stage',['materialize_debugging','prepare_debugging','execute_financial_modeling','execute_debugging','cold_identity'])
def test_first_failure_is_scoped_preserved_stops_future_modes_and_releases(boundary,failure_stage):
    root,manifest,_,events,state=boundary;output=root/'pair';entry.prepare(manifest,output);state['failure']=failure_stage
    with pytest.raises(RuntimeError,match='Preserved failed first pair attempt'):entry.execute_prepared(output)
    result=entry.read(output/'terminal.json')
    assert not result['passed'] and result['LO_call_count_exact'] is None and not result['qualified']
    assert result['failure'] and entry.read(output/'producer.lock')['status']=='released'
    assert events[-1]=='server_stopped' and 'temporary_exited' in events
    if failure_stage in ('materialize_debugging','prepare_debugging'):
        assert not any(value.startswith('execute_') for value in events)
    elif failure_stage!='execute_debugging':assert 'execute_debugging' not in events
    if failure_stage.startswith('execute_'):assert result['partial_validation_terminals']
    with pytest.raises(ValueError):entry.execute_prepared(output)


@pytest.mark.parametrize('attack',['mapping','recipe','source','claims'])
def test_cold_guard_failure_is_zero_service_and_immutable(boundary,attack):
    root,manifest,source,events,_=boundary;output=root/'pair';entry.prepare(manifest,output)
    frozen=entry.read(output/'preparation.json')
    if attack=='mapping':frozen['modes'][1]['view_directory']=str(root/'other')
    if attack=='recipe':frozen['recipe_sha256'].pop(next(iter(frozen['recipe_sha256'])))
    if attack=='source':Path(source['workbook']['path']).write_bytes(b'changed')
    if attack=='claims':frozen['LO_calls']=False
    dump(output/'preparation.json',frozen)
    with pytest.raises(ValueError):entry.execute_prepared(output)
    assert 'server_started' not in events
    assert entry.read(output/'execution_preflight_failure.json')['LO_calls']==0
    with pytest.raises(ValueError,match='first pair attempt'):entry.execute_prepared(output)


def test_policy_changes_and_fake_pending_paths_do_not_become_prepared_receipts(boundary):
    root,manifest,_,events,_=boundary
    _,config=entry.policy();config['mode_order'].reverse();changed=dump(root/'changed_config.json',config)
    with pytest.raises(ValueError,match='policy changed'):entry.prepare(manifest,root/'policy_failure',configuration=changed['path'])
    assert not (root/'policy_failure/preparation.json').exists()
    with pytest.raises((ValueError,FileNotFoundError)):entry.prepare(root/'not_yet_a_source.json',root/'pending')
    assert not (root/'pending/preparation.json').exists()


def test_cli_is_zero_execution_without_run_and_preserves_one_command_option(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(entry,'prepare',lambda *a,**k:calls.append('prepare') or {'prepared':True})
    monkeypatch.setattr(entry,'validate_prepared',lambda *a:({'validated':True},{}))
    monkeypatch.setattr(entry,'execute_prepared',lambda *a,**k:calls.append('run') or {'terminal':True})
    argv=['--source-manifest',str(tmp_path/'source.json'),'--output',str(tmp_path/'pair')]
    entry.main(argv);assert calls==['prepare']
    calls.clear();entry.main(argv+['--run']);assert calls==['prepare','run']
    calls.clear();entry.main(['--prepared',str(tmp_path/'pair')]);assert calls==[]
    entry.main(['--prepared',str(tmp_path/'pair'),'--run']);assert calls==['run']
