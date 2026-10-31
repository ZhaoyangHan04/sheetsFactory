"""Pure/mocked recovery checks; no model, Harbor, Docker or engine invocation."""
import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import fcntl
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from threading import Barrier

import pytest

from sheets_factory.evaluation import clock_resource_frontier as clock
from sheets_factory.evaluation import native_transport_frontier as native

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    descriptor = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(descriptor); descriptor.loader.exec_module(value)
    return value


recovery = module('_transport_recovery_tests', ROOT/'scripts/prepare_linear_capital_transport_recovery.py')
legacy = module('_first_attempt_offline_fixtures', ROOT/'tests/test_linear_capital_development.py')
@pytest.fixture
def case(tmp_path, monkeypatch):
    return legacy.case.__wrapped__(tmp_path, monkeypatch, SimpleNamespace(param='debugging'))


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2)+'\n')
    return recovery.reference(path)


@pytest.fixture
def failed(case, monkeypatch):
    probe = legacy.probe
    monkeypatch.setattr(recovery, 'first', probe)
    monkeypatch.setattr(recovery, 'HISTORY_ROOTS', probe.HISTORY_ROOTS)
    manifest_ref = legacy.prepare(case); frozen = recovery.read(manifest_ref)
    evaluation = case.root/'history/difficulty/first/evaluation'
    binary = case.root/'explicit-offline-native-binary'; binary.write_bytes(b'not-executed')
    binary_ref = recovery.reference(binary)
    selection = clock.freeze_selection(manifest_ref['path'], evaluation, phase='development',
        execution_provenance={'native_cli': {'path':str(binary),'sha256':binary_ref['sha256'],
            'version':'explicit_offline_mock_binary_never_executed'}})
    task = selection['tasks'][0]
    trial = evaluation/'harbor_jobs/frontier-pass1/native-failure'
    (trial/'agent').mkdir(parents=True); (trial/'verifier').mkdir()
    (trial/'agent/codex.txt').write_text(json.dumps({'type':'turn.failed', 'error':{
        'message':'stream disconnected before completion: error sending request'}})+'\n')
    session = dump(trial/'agent/sessions/rollout.jsonl', {'type':'explicit_offline_mock_session'})
    dump(trial/'verifier/diagnostics.json', {'reward':0, 'reason':'verification_error',
        'error_type':'ValueError', 'error':'Submitted workbook is missing or a symlink', 'recalculation_calls':[]})
    (trial/'verifier/reward.txt').write_text('0\n')
    usage = {'n_input_tokens':46773, 'n_output_tokens':549, 'n_cache_tokens':42112,
        'model_usage': {'gpt-6.1-sol': {'n_input_tokens':46773, 'n_output_tokens':549}}}
    result = {'task_name': task['harbor_export_binding']['task_name'], 'trial_name':trial.name,
        'task_checksum':task['task_checksum'], 'task_id':{'path':task['task_directory']},
        'config':{'task':{'path':task['task_directory']}, 'agent':{
            'model_name':clock.MODEL, 'import_path':'sheets_factory.evaluation.clock_resource_frontier:LocalCodex',
            'override_timeout_sec':14400, 'kwargs':{'reasoning_effort':clock.EFFORT}}},
        'agent_info':{'model_info':{'name':clock.MODEL}}, 'agent_result':usage,
        'started_at':'2026-10-31T10:00:00Z', 'finished_at':'2026-10-31T10:01:00Z',
        'agent_execution':{'started_at':'2026-10-31T10:00:01Z', 'finished_at':'2026-10-31T10:00:59Z'},
        'exception_info':{'exception_type':'NonZeroAgentExitCodeError'},
        'verifier_result':{'rewards':{'reward':0.0}}}
    dump(trial/'result.json', result)
    started = dump(case.output/'development_started.json', {'kind':probe.KIND+'_first_attempt_started',
        'prepared_snapshot':manifest_ref, 'material_task_version':frozen['material_task_version'],
        'evaluation_output':str(evaluation), 'model':clock.MODEL,'reasoning_effort':clock.EFFORT,
        'phase':'development','concurrency':1,'effective_infrastructure_retries':0})
    state = SimpleNamespace(case=case, probe=probe, frozen=frozen, evaluation=evaluation,
        selection=selection, trial=trial, started=started, session=session,
        terminal=case.output/'development_terminal.json', diagnostic=case.output/'transport_diagnostic.json',
        prepared=case.root/'history/difficulty/recovery/prepared', output=case.root/'history/difficulty/recovery/evaluation')
    def refresh(*, evaluation_updates=None, terminal_updates=None, diagnostic_updates=None):
        selected = recovery.read(evaluation/'selection_manifest.json')
        attempts, history = clock.collect_attempts(evaluation, selected, include_infrastructure_history=True)
        score, _ = clock.summarize(selected, attempts)
        record = {'schema_version':1,'phase':'development','status':'infrastructure_failed',
            'finished_at':'2026-10-31T10:01:01Z','failure_kind':None,
            'selection_manifest':{k:v for k,v in recovery.reference(evaluation/'selection_manifest.json').items() if k!='bytes'},
            'model':clock.MODEL,'reasoning_effort':clock.EFFORT,'n_attempts':1,
            'execution_budget':deepcopy(probe.BUDGET), 'timeout_seconds':14400,
            'tool_time_policy':deepcopy(clock.POLICY_V3), 'prompt_sha256':selected['prompt_sha256'],
            'attempts':attempts,'infra_history':history,'infrastructure_retries':[], 'score':score,'gate_passed':False}
        record.update(evaluation_updates or {})
        evaluation_ref = dump(evaluation/'evaluation_manifest.json', record)
        terminal = {'kind':probe.KIND+'_first_attempt_terminal','started':started,
            'evaluation_manifest':evaluation_ref, 'selection_manifest':recovery.reference(evaluation/'selection_manifest.json'),
            'status':'infrastructure_failed','score':record['score'],'phase':'development',
            'qualified':False,'effective_infrastructure_retries':0}
        terminal.update(terminal_updates or {})
        terminal_ref = dump(state.terminal, terminal)
        diagnostic = {'completed_attempt_terminal':terminal_ref,
            'actual_harbor_result':recovery.reference(trial/'result.json'),
            'native_public_event_stream':recovery.reference(trial/'agent/codex.txt'),
            'native_session':session,'harbor_exception_type':'NonZeroAgentExitCodeError',
            'local_source_bindings':[recovery.reference(p) for p in
                [ROOT/'src/sheets_factory/evaluation/frontier.py',Path(clock.__file__),
                ROOT/'src/sheets_factory/llm/codex.py',Path(__import__('sys').modules[clock.Codex.__module__].__file__)]]}
        diagnostic.update(diagnostic_updates or {})
        diagnostic_ref = dump(state.diagnostic, diagnostic)
        monkeypatch.setattr(recovery, 'PARENT_TERMINAL_SHA256', terminal_ref['sha256'])
        monkeypatch.setattr(recovery, 'PARENT_DIAGNOSTIC_SHA256', diagnostic_ref['sha256'])
        monkeypatch.setattr(recovery, 'PARENT_PROBE_SHA256', manifest_ref['sha256'])
        return terminal_ref, diagnostic_ref
    state.refresh = refresh; refresh()
    return state


def prep(failed):
    return recovery.prepare(failed.terminal, failed.diagnostic, failed.prepared)


def test_cold_preparation_retains_full_first_history_tokens_and_exact_material(failed, monkeypatch):
    monkeypatch.setattr(native, 'run_evaluation', lambda *a,**k:pytest.fail('Cold preparation cannot evaluate'))
    before = recovery._tree(failed.evaluation)
    ref = prep(failed); frozen = recovery.read(ref)
    assert frozen['tasks'] == failed.frozen['tasks']
    assert frozen['material_task_version'] == failed.frozen['material_task_version']
    assert len(frozen['resource_task_inventory']) == 17
    assert frozen['parent']['evaluation_artifact_inventory'] == before == recovery._tree(failed.evaluation)
    assert frozen['parent']['first_attempt_usage']['n_input_tokens'] == 46773
    assert frozen['parent']['first_attempt_usage']['n_output_tokens'] == 549
    assert frozen['parent']['native_cli_binary']['sha256'] == failed.selection['execution_provenance']['native_cli']['sha256']
    assert frozen['recovery_index'] == frozen['effective_infrastructure_retries'] == 1
    assert frozen['recovery_policy'] == recovery.POLICY
    assert frozen['native_transport_profile']['provider_overrides'] == {'stream_max_retries':8}
    assert frozen['new_model_calls'] == frozen['new_Harbor_jobs'] == frozen['new_LO_calls'] == 0
    assert frozen['task_count'] == 0 and frozen['qualified'] is False
    assert recovery.read(failed.terminal)['effective_infrastructure_retries'] == 0
    validated, current = recovery.validate_prepared(failed.prepared)
    assert validated == frozen and current == frozen['selection_history_inventory']


@pytest.mark.parametrize('change', ['completed','score_zero','score_one','unknown_timing','active','retry_history',
    'terminal_effective_retry','terminal_score','terminal_anchor','diagnostic_anchor','diagnostic_wrong_parent'])
def test_parent_state_fail_closed(failed, change):
    evaluation, terminal, diagnostic = {}, {}, {}
    if change == 'completed': evaluation['status'] = 'completed'
    if change in {'score_zero','score_one','unknown_timing'}:
        score = deepcopy(recovery.read(failed.terminal)['score'])
        if change == 'unknown_timing': score['incomplete_timing_evidence'] = 1
        else: score.update(overall_pass_at_1=0 if change=='score_zero' else 1,scored_tasks=1)
        evaluation['score'] = score
    if change == 'active': evaluation['finished_at'] = None
    if change == 'retry_history': evaluation['infrastructure_retries'] = [{'index':1}]
    if change == 'terminal_effective_retry': terminal['effective_infrastructure_retries'] = 1
    if change == 'terminal_score': terminal['score'] = {}
    if change == 'diagnostic_wrong_parent': diagnostic['completed_attempt_terminal'] = failed.started
    failed.refresh(evaluation_updates=evaluation,terminal_updates=terminal,diagnostic_updates=diagnostic)
    if change in {'terminal_anchor','diagnostic_anchor'}:
        path = failed.terminal if change=='terminal_anchor' else failed.diagnostic
        path.write_text(path.read_text()+'\n')
    with pytest.raises((ValueError, KeyError)):
        prep(failed)
    assert not (failed.prepared/'recovery_manifest.json').exists()


@pytest.mark.parametrize('change', ['raw_one','scored_zero','scored_one','guard_only','unknown_failure',
    'missing_stream_failure','other_stream_failure','raw_output','reward_file_one','normal_verifier',
    'unfinished_agent','changed_model','changed_task_path'])
def test_actual_trial_evidence_fail_closed(failed, change):
    result_path = failed.trial/'result.json'; result = recovery.read(result_path)
    if change == 'raw_one': result['verifier_result']['rewards']['reward'] = 1
    if change in {'scored_zero','scored_one'}:
        result['exception_info'] = None
        result['verifier_result']['rewards']['reward'] = 0 if change=='scored_zero' else 1
    if change == 'guard_only': result['exception_info']['exception_type'] = 'AgentTimeoutError'
    if change == 'unknown_failure': result['exception_info']['exception_type'] = 'RuntimeError'
    if change == 'missing_stream_failure': (failed.trial/'agent/codex.txt').write_text('{}\n')
    if change == 'other_stream_failure':
        (failed.trial/'agent/codex.txt').write_text(json.dumps({'type':'turn.failed', 'error':{'message':'HTTP 503'}}))
    if change == 'raw_output': (failed.trial/'agent/output.xlsx').write_bytes(b'potential valid answer')
    if change == 'reward_file_one': (failed.trial/'verifier/reward.txt').write_text('1\n')
    if change == 'normal_verifier': dump(failed.trial/'verifier/diagnostics.json',{'reward':0,'reason':'value_or_modified_set_mismatch'})
    if change == 'unfinished_agent': result['agent_execution']['finished_at'] = None
    if change == 'changed_model': result['config']['agent']['model_name'] = 'other-model'
    if change == 'changed_task_path': result['config']['task']['path'] = '/other-task'
    dump(result_path, result); failed.refresh()
    with pytest.raises((ValueError, KeyError)):
        prep(failed)


@pytest.mark.parametrize('change', ['export_file','extra_file','original_recipe','original_instruction','selection_material','early_stop','duplicate_trial','native_binary'])
def test_unchanged_first_task_and_lineage_required(failed, change):
    task = Path(failed.frozen['tasks'][0]['task_directory'])
    if change == 'export_file': (task/'environment/input.xlsx').write_bytes(b'changed')
    if change == 'extra_file': (task/'extra.txt').write_text('unexpected')
    if change in {'original_recipe','original_instruction'}:
        manifest = recovery.read(failed.case.output/'probe_manifest.json')
        if change == 'original_recipe': manifest['recipe_sha256'] = {}
        else: manifest['material_task_version']['instruction_sha256'] = 'f'*64
        dump(failed.case.output/'probe_manifest.json', manifest)
    if change == 'selection_material':
        selection = recovery.read(failed.evaluation/'selection_manifest.json')
        selection['tasks'][0]['revision_hash'] = 'f'*64
        dump(failed.evaluation/'selection_manifest.json',selection);failed.refresh()
    if change == 'early_stop': dump(failed.evaluation/'private/early_stop.json', {'reason':'intentional'})
    if change == 'native_binary':
        native_ref=failed.selection['execution_provenance']['native_cli']
        Path(native_ref['path']).write_bytes(b'changed')
    if change == 'duplicate_trial':
        result = recovery.read(failed.trial/'result.json')
        dump(failed.evaluation/'harbor_jobs/other-job/duplicate/result.json', result)
    with pytest.raises((ValueError, KeyError, FileNotFoundError)):
        prep(failed)


def test_all_history_retained_other_material_allowed_but_parent_cannot_disappear(failed):
    other = deepcopy(failed.frozen['material_task_version']); other['instruction_sha256'] = 'f'*64
    other['sha256'] = recovery.canonical({k:v for k,v in other.items() if k!='sha256'})
    source = dump(failed.case.root/'history/research/other/source.json', {'material_task_version':other})
    extra = dump(failed.case.root/'history/research/other/selection_manifest.json', {'phase':'development',
        'source_manifest':source,'tasks':[{'mode':'debugging','task_checksum':'c'*64,'task_id':'other'}]})
    frozen = recovery.read(prep(failed))
    assert extra in frozen['selection_history_inventory']
    Path(extra['path']).unlink()
    with pytest.raises(ValueError):
        recovery.validate_prepared(failed.prepared)


@pytest.mark.parametrize('kind',['same_identity','renamed','legacy_same_workbooks'])
def test_no_same_material_history_skipping_even_renamed(failed, kind):
    selection = {'phase':'development','tasks':[{'mode':'debugging','task_checksum':'c'*64,'task_id':'renamed'}]}
    if kind == 'legacy_same_workbooks': selection['tasks'][0]['task_directory'] = failed.frozen['tasks'][0]['task_directory']
    else:
        selection['source_manifest'] = dump(failed.case.root/'history/research/other/source.json',
            {'material_task_version':failed.frozen['material_task_version']})
    dump(failed.case.root/'history/research/other/selection_manifest.json',selection)
    with pytest.raises(ValueError, match='Another selection'):
        prep(failed)


def test_only_one_reservation_and_no_second_parent(failed):
    prep(failed)
    with pytest.raises(ValueError,match='already has a recovery reservation'):
        recovery.prepare(failed.terminal,failed.diagnostic,failed.prepared.parent/'another-prepared')
    with pytest.raises(ValueError,match='fresh recovery'):
        prep(failed)
    duplicate = failed.prepared.parent/'other/recovery_manifest.json'
    dump(duplicate, recovery.read(failed.prepared/'recovery_manifest.json'))
    with pytest.raises(ValueError,match='multiple parents'):
        recovery.validate_prepared(failed.prepared)


@pytest.mark.parametrize('change',['policy','transport','task','guard','budget','model','effort','phase','recipe','history','parent_byte'])
def test_recovery_contract_and_parent_immutability(failed, change):
    ref = prep(failed); frozen = recovery.read(ref)
    if change == 'policy': frozen['recovery_policy']['max_documented_recoveries_per_material']=2
    if change == 'transport': frozen['native_transport_profile']['provider_overrides']['stream_max_retries']=9
    if change == 'task': frozen['tasks'][0]['task_id']='renamed'
    if change == 'guard': frozen['timeout_seconds']=20000
    if change == 'budget': frozen['execution_budget']['tool_budget_seconds']=1801
    if change == 'model': frozen['model']='other'
    if change == 'effort': frozen['reasoning_effort']='high'
    if change == 'phase': frozen['phase']='confirmation'
    if change == 'recipe': frozen['recipe_sha256']={}
    if change == 'history': frozen['selection_history_inventory']=[]
    if change == 'parent_byte':
        (failed.trial/'agent/codex.txt').write_text('changed after preparation')
    dump(Path(ref['path']), frozen)
    with pytest.raises((ValueError, KeyError)):
        recovery.validate_prepared(failed.prepared)


def fake_runtime(monkeypatch, failed, *, failure=False):
    import sheets_factory.evaluation.resource_observer as observations
    calls = []
    class Observer:
        receipt = None; finalization_error = None
        def __init__(self, output): self.output=output
        def __enter__(self): return self
        def __exit__(self,*args): return False
    def evaluate(source, output, **kwargs):
        calls.append((source,output,kwargs))
        assert (failed.prepared/'recovery_started.json').is_file()
        if failure: raise RuntimeError('Explicit mocked launch failure')
        dump(output/'evaluation_manifest.json',{'status':'infrastructure_failed'})
        dump(output/'selection_manifest.json',{'phase':'development'})
        return {'status':'infrastructure_failed','score':{'overall_pass_at_1':None,'scored_tasks':0}}
    monkeypatch.setattr(observations,'ResourceObserver',Observer)
    monkeypatch.setattr(native,'run_evaluation',evaluate)
    return calls


@pytest.mark.parametrize('failure',[False,True])
def test_explicit_mocked_launch_spends_exactly_one_and_preserves_parent(failed,monkeypatch,failure):
    prep(failed); before=recovery._tree(failed.evaluation)
    calls=fake_runtime(monkeypatch,failed,failure=failure)
    if failure:
        with pytest.raises(RuntimeError,match='mocked launch'):
            recovery.run_development(failed.prepared,failed.output)
        assert (failed.prepared/'recovery_failure.json').exists()
    else:
        ref=recovery.run_development(failed.prepared,failed.output)
        assert recovery.read(ref)['further_recovery_authorized'] is False
    assert len(calls)==1 and calls[0][2]['phase']=='development' and calls[0][2]['concurrency']==1
    assert calls[0][2]['backend_config']['binary']==failed.selection['execution_provenance']['native_cli']['path']
    assert str(failed.evaluation/'selection_manifest.json') in calls[0][2]['prior_selections']
    assert recovery._tree(failed.evaluation)==before
    with pytest.raises(ValueError,match='already reserved'):
        recovery.run_development(failed.prepared,failed.output.parent/'second')
    assert len(calls)==1


def test_invalid_cold_checks_start_no_observer_or_runner(failed,monkeypatch):
    prep(failed); calls=fake_runtime(monkeypatch,failed)
    (failed.trial/'agent/codex.txt').write_text('changed')
    with pytest.raises(ValueError): recovery.run_development(failed.prepared,failed.output)
    assert calls==[] and not (failed.prepared/'recovery_started.json').exists()


def test_concurrent_launchers_cannot_reserve_two_recoveries(failed,monkeypatch):
    prep(failed);calls=fake_runtime(monkeypatch,failed);barrier=Barrier(2)
    def launch(index):
        barrier.wait(timeout=5)
        try:
            return recovery.run_development(failed.prepared,failed.output.parent/str(index))
        except ValueError as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(launch,[1,2]))
    assert len(calls)==1
    assert sum(isinstance(result,dict) for result in results)==1
    assert any(isinstance(result,str) and ('active' in result or 'already reserved' in result) for result in results)
    assert (failed.prepared/'recovery_started.json').exists()


def test_global_lock_blocks_preparation_before_reserving_material(failed):
    root=Path(recovery.HISTORY_ROOTS[0]);root.mkdir(parents=True,exist_ok=True)
    with (root/'.bounded_native_transport_recovery.lock').open('a') as handle:
        fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(ValueError,match='active'):prep(failed)
    assert not failed.prepared.exists()


def test_reservation_must_stay_in_searched_history(failed):
    with pytest.raises(ValueError,match='standard searched history root'):
        recovery.prepare(failed.terminal,failed.diagnostic,failed.case.root/'outside-history')


def test_transport_adapter_only_counted_changes_and_no_original_policy_mutation():
    before,after=clock.adapted_ast(),native.adapted_ast()
    changed=[left.name for left,right in zip(before.body,after.body) if ast.dump(left)!=ast.dump(right)]
    assert changed==['_selection_execution_budget','_runtime_provenance','freeze_selection','_matches_execution','_job_config']
    assert native.PROMPT==clock.PROMPT and native.POLICY_V3==clock.POLICY_V3
    assert native.TASK_FILES==clock.TASK_FILES and len(native.TASK_FILES)==17
    for name in ['classify_result','summarize','collect_attempts','assess_infrastructure_retry',
                 'execute_evaluation','run_evaluation','resume_infrastructure']:
        left=next(n for n in before.body if getattr(n,'name',None)==name)
        right=next(n for n in after.body if getattr(n,'name',None)==name)
        assert ast.dump(left)==ast.dump(right)


def test_transport_provider_override_exactly_one_key_and_frozen(failed):
    source=deepcopy(failed.frozen);source['native_transport_profile']=native.transport_profile()
    path=dump(failed.case.root/'transport-source.json',source)
    selected=native.freeze_selection(path['path'],failed.case.root/'transport-snapshot',phase='development')
    args=dict(concurrency=1,binary=Path('/native/codex'),base_url='http://invalid')
    actual=native._job_config(failed.case.root,selected,**args).model_dump(mode='json')
    old=deepcopy(selected);old.pop('native_transport_profile')
    previous=clock._job_config(failed.case.root,old,**args).model_dump(mode='json')
    agent=actual['agents'][0]
    assert agent['kwargs']['config']['model_providers']['factory']['stream_max_retries']==8
    assert 'request_max_retries' not in agent['kwargs']['config']['model_providers']['factory']
    assert 'stream_idle_timeout_ms' not in agent['kwargs']['config']['model_providers']['factory']
    agent['kwargs']['config']['model_providers']['factory'].pop('stream_max_retries')
    agent['import_path']=previous['agents'][0]['import_path']
    assert actual==previous
    assert actual['retry']['max_retries']==0 and actual['n_attempts']==1
    selected['native_transport_profile']['provider_overrides']['stream_max_retries']=9
    with pytest.raises(ValueError,match='transport profile changed'):
        native._job_config(failed.case.root,selected,**args)


def test_transport_profile_copies_and_file_drift_fail_closed(tmp_path,monkeypatch):
    profile=native.transport_profile();profile['provider_overrides']['stream_max_retries']=100
    assert native.transport_profile()['provider_overrides']=={'stream_max_retries':8}
    altered=tmp_path/'profile.json';altered.write_bytes(native.PROFILE_PATH.read_bytes()+b'\n')
    monkeypatch.setattr(native,'PROFILE_PATH',altered)
    with pytest.raises(ValueError,match='profile changed'):native.transport_profile()
    with pytest.raises(ValueError,match='profile changed'):native.adapted_ast()


def test_installed_agent_preserves_stream_override_through_actual_toml_merge():
    from harbor.agents.installed.codex import Codex
    import toml
    config={'model_provider':'factory','model_providers':{'factory':{'name':'factory',
        'base_url':'http://invalid/v1','env_key':'OPENAI_API_KEY','wire_api':'responses','stream_max_retries':8}}}
    fake=SimpleNamespace(config_source=config,options=SimpleNamespace(web_search=None),
        _native_model_provider=Codex._native_model_provider,skip_model_parsing=True,
        _execution_base_url=None,_model_api_format='openai_responses',mcp_servers=[])
    fake._base_config=Codex._load_base_config(fake)
    effective=Codex._build_effective_config(fake,'http://invalid/v1')
    assert toml.loads(toml.dumps(effective))==config
    assert effective['model_providers']['factory']['stream_max_retries']==8
