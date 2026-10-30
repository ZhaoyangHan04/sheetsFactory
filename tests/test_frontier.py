"""Offline checks of selection fairness and persisted Harbor score bindings."""
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path

from openpyxl import Workbook
import pytest

from sheets_factory.evaluation.frontier import (
    EFFORT, MODEL, FrontierError, LocalCodex, _execution_environment, _job_config, _persist_failure,
    assess_infrastructure_retry, classify_result, collect_attempts, freeze_selection,
    resume_infrastructure, review_agent_timeout, run_evaluation, summarize,
)
from sheets_factory.evaluation.harbor import export_harbor, inspect_export
from sheets_factory.llm.codex import CodexCLI


def make_release(tmp_path, count=2):
    source = tmp_path / 'authoring'
    (source / 'public').mkdir(parents=True)
    (source / 'private').mkdir()
    workbook = Workbook()
    workbook.active['A1'] = 1
    workbook.save(source / 'public/input.xlsx')
    workbook.active['A1'] = 2
    workbook.save(source / 'private/goal.xlsx')
    (source / 'public/instruction.md').write_text('Restore Model A1 from the public rules.')
    release = tmp_path / 'release'
    tasks = []
    for index in range(count):
        task = {'task_id': f'task-{index:02}',
                'mode': 'financial_modeling' if index % 2 == 0 else 'debugging',
                'revision': 1, 'revision_hash': f'{index:064x}', 'source_id': f'source-{index:02}'}
        directory = export_harbor(source, release / 'SpreadsheetEval' / task['task_id'], task)
        task['harbor_export_binding'] = inspect_export(directory)
        tasks.append(task)
    manifest = release / 'release_manifest.json'
    manifest.write_text(json.dumps({'selected_task_ids': [task['task_id'] for task in tasks], 'tasks': tasks}))
    return manifest


def actual_result(task, reward=0):
    return {'task_name': task['harbor_export_binding']['task_name'],
            'task_id': {'path': task['task_directory']}, 'task_checksum': task['task_checksum'],
            'config': {'task': {'path': task['task_directory']}, 'agent': {
                'model_name': MODEL, 'import_path': 'sheets_factory.evaluation.frontier:LocalCodex',
                'override_timeout_sec': task.get('timeout_seconds', 1800),
                'kwargs': {'reasoning_effort': EFFORT}}},
            'agent_info': {'model_info': {'name': MODEL}}, 'agent_result': {'n_output_tokens': 17},
            'verifier_result': {'rewards': {'reward': reward}}, 'exception_info': None,
            'started_at': '2026-10-30T00:00:00+00:00', 'finished_at': '2026-10-30T00:00:01+00:00'}


def persist_result(run_dir, task, reward=0, trial='trial', job_name='frontier-pass1'):
    path = run_dir / 'harbor_jobs' / job_name / (task['task_id'] + '-' + trial) / 'result.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(actual_result(task, reward)))
    return path


def test_freeze_binds_exact_bytes_and_budget_before_execution(tmp_path):
    manifest = make_release(tmp_path)
    original = (manifest.parent / 'SpreadsheetEval/task-00/instruction.md').read_bytes()
    selection = freeze_selection(manifest, tmp_path / 'evaluation', phase='development', timeout_seconds=900)
    assert selection['n_attempts'] == 1
    assert selection['model'] == MODEL and selection['reasoning_effort'] == EFFORT
    assert all(task['timeout_seconds'] == 900 for task in selection['tasks'])
    assert all(Path(task['task_directory']).is_relative_to(tmp_path / 'evaluation') for task in selection['tasks'])
    assert selection['source_manifest']['sha256'] == sha256(manifest.read_bytes()).hexdigest()
    assert (manifest.parent / 'SpreadsheetEval/task-00/instruction.md').read_bytes() == original
    with pytest.raises(FrontierError, match='already exists'):
        freeze_selection(manifest, tmp_path / 'evaluation', phase='development')


@pytest.mark.parametrize('problem', ['extra', 'symlink', 'unknown', 'budget', 'count'])
def test_freeze_rejects_invalid_selection(tmp_path, problem):
    manifest = make_release(tmp_path)
    directory = manifest.parent / 'SpreadsheetEval/task-00'
    kwargs = {'phase': 'development'}
    if problem == 'extra':
        (directory / 'private-plan.json').write_text('{}')
    elif problem == 'symlink':
        (directory / 'private-link').symlink_to(manifest)
    elif problem == 'unknown':
        kwargs['task_ids'] = ['unknown']
    elif problem == 'budget':
        kwargs['timeout_seconds'] = 30
    else:
        kwargs['phase'] = 'confirmation'
    with pytest.raises(FrontierError):
        freeze_selection(manifest, tmp_path / 'evaluation', **kwargs)


def test_confirmation_allows_development_tasks_but_rejects_repeated_confirmation(tmp_path):
    manifest = make_release(tmp_path, 20)
    development = tmp_path / 'development'
    freeze_selection(manifest, development, phase='development')
    confirmation = tmp_path / 'confirmation'
    selected = freeze_selection(manifest, confirmation, phase='confirmation',
                                prior_selections=[development / 'selection_manifest.json'])
    assert selected['prior_selections'][0]['phase'] == 'development'
    assert selected['selected_task_ids'] == [f'task-{index:02}' for index in range(20)]
    with pytest.raises(FrontierError, match='prior confirmation'):
        freeze_selection(manifest, tmp_path / 'repeat', phase='confirmation',
                         prior_selections=[confirmation / 'selection_manifest.json'])


@pytest.fixture
def frozen(tmp_path):
    return freeze_selection(make_release(tmp_path), tmp_path / 'evaluation', phase='development')


@pytest.mark.parametrize('field,value', [
    ('model', 'gpt-6-sol'), ('effort', 'high'), ('installer', 'unrelated:Agent'),
    ('budget', 1), ('checksum', '0' * 64), ('task_path', '/another-task'),
    ('task_id', '/another-task'), ('task_name', 'another-task'), ('reported_model', 'gpt-6-sol'),
])
def test_result_must_bind_actual_strongest_execution(frozen, field, value):
    task = frozen['tasks'][0]
    result = actual_result(task)
    if field == 'model':
        result['config']['agent']['model_name'] = value
    elif field == 'effort':
        result['config']['agent']['kwargs']['reasoning_effort'] = value
    elif field == 'installer':
        result['config']['agent']['import_path'] = value
    elif field == 'budget':
        result['config']['agent']['override_timeout_sec'] = value
    elif field == 'checksum':
        result['task_checksum'] = value
    elif field == 'task_path':
        result['config']['task']['path'] = value
    elif field == 'task_id':
        result['task_id']['path'] = value
    elif field == 'task_name':
        result['task_name'] = value
    else:
        result['agent_info']['model_info']['name'] = value
    assert classify_result(result, task) == ('infrastructure_error', None, 'execution_binding_mismatch')


def test_infrastructure_is_never_a_model_failure(frozen):
    task = frozen['tasks'][0]
    result = actual_result(task)
    assert classify_result(result, task) == ('scored', 0, None)
    result['exception_info'] = {'exception_type': 'AgentTimeoutError'}
    assert classify_result(result, task) == ('infrastructure_error', None, 'AgentTimeoutError')
    result['exception_info'] = None
    assert classify_result(result, task, diagnostics={'reason': 'verification_error', 'error_type': 'RuntimeError'})[0] == 'infrastructure_error'
    assert classify_result(result, task, diagnostics={'reason': 'verification_error', 'error_type': 'BadZipFile'}) == ('scored', 0, None)
    result['verifier_result']['rewards']['reward'] = None
    assert classify_result(result, task)[0] == 'infrastructure_error'


def test_overall_threshold_does_not_impose_per_category_threshold():
    tasks = [{'task_id': f'{mode}-{i}', 'mode': mode} for mode in ('financial_modeling', 'debugging') for i in range(10)]
    selection = {'tasks': tasks, 'phase': 'confirmation'}
    attempts = [dict(task, status='scored', reward=int(index < 4)) for index, task in enumerate(tasks)]
    score, passed = summarize(selection, attempts)
    assert passed and score['overall_pass_at_1'] == .2
    assert score['by_mode']['financial_modeling']['pass_at_1'] == .4
    selection['phase'] = 'development'
    assert summarize(selection, attempts)[1] is False
    selection['phase'] = 'confirmation'
    attempts[0].update(status='infrastructure_error', reward=None)
    score, passed = summarize(selection, attempts)
    assert score['overall_pass_at_1'] is None and not passed and score['infrastructure_errors'] == 1


def test_collect_only_persisted_trials_and_refuses_duplicate_attempts(tmp_path, frozen):
    task = frozen['tasks'][0]
    path = persist_result(tmp_path, task, reward=1)
    attempts = collect_attempts(tmp_path, frozen)
    assert attempts[0]['result_sha256'] == sha256(path.read_bytes()).hexdigest()
    assert attempts[0]['reward'] == 1 and attempts[0]['status'] == 'scored'
    persist_result(tmp_path, task, trial='second')
    with pytest.raises(FrontierError, match='Multiple scored attempts'):
        collect_attempts(tmp_path, frozen)


def test_job_uses_actual_harbor_agent_and_no_retries(tmp_path, frozen):
    config = _job_config(tmp_path, frozen, concurrency=4, binary='/usr/bin/codex', base_url='https://test.invalid/v1')
    assert config.n_attempts == 1 and config.retry.max_retries == 0
    assert config.agents[0].import_path == 'sheets_factory.evaluation.frontier:LocalCodex'
    assert config.agents[0].override_timeout_sec == 1800
    assert config.agents[0].kwargs['reasoning_effort'] == EFFORT
    assert config.agents[0].skip_model_parsing is True
    assert config.agents[0].model_api_format.value == 'openai_responses'
    LocalCodex.preflight(config.agents[0].kwargs)
    assert all(str(task.path) == frozen['tasks'][index]['task_directory'] for index, task in enumerate(config.tasks))


def test_local_install_only_uploads_native_tools(tmp_path):
    binary = tmp_path / 'codex'
    binary.write_text('native fixture')
    binary.with_name('codex-code-mode-host').write_text('code host fixture')
    agent = object.__new__(LocalCodex)
    agent.native_binary = binary
    uploaded, commands = [], []

    class Environment:
        async def upload_file(self, origin, target):
            uploaded.append((origin.name, target))

    async def run_root(environment, *, command):
        commands.append(command)

    agent.exec_as_root = run_root
    asyncio.run(agent.install(Environment()))
    assert uploaded == [('codex', '/usr/local/bin/codex'), ('codex-code-mode-host', '/usr/local/bin/codex-code-mode-host')]
    assert commands == ['chmod 755 /usr/local/bin/codex /usr/local/bin/codex-code-mode-host']


def test_error_diagnostics_keep_cause_without_credentials(tmp_path, monkeypatch):
    secret = 'fixture-credential-value'
    monkeypatch.setenv('TEST_API_KEY', secret)
    try:
        raise ValueError('Unknown native_binary option; Bearer ' + secret)
    except ValueError as error:
        _persist_failure(tmp_path, error)
    raw = (tmp_path / 'private/evaluation_error.json').read_text()
    report = json.loads(raw)
    assert secret not in raw
    assert report['exception_type'] == 'ValueError'
    assert 'Unknown native_binary option' in report['message']
    assert 'ValueError' in report['traceback'] and '[REDACTED]' in report['traceback']


@pytest.mark.parametrize('failure', [False, True])
def test_worker_environment_bypasses_proxy_and_restores_on_error(tmp_path, monkeypatch, failure):
    for name in ['HTTPS_PROXY', 'all_proxy', 'NO_PROXY', 'PROXY']:
        monkeypatch.setenv(name, 'fixture-inherited-proxy')
    monkeypatch.setenv('SHEETS_FACTORY_API_KEY', 'fixture-original-credential')
    monkeypatch.setenv('UNRELATED_SETTING', 'preserved')
    original = dict(os.environ)
    backend = CodexCLI(tmp_path, tmp_path, None, {})
    try:
        with _execution_environment(backend, 'fixture-runtime-credential'):
            assert not any(name.upper().endswith('_PROXY') or name.upper() == 'PROXY' for name in os.environ)
            assert os.environ['SHEETS_FACTORY_API_KEY'] == 'fixture-runtime-credential'
            assert os.environ['UNRELATED_SETTING'] == 'preserved'
            if failure:
                raise RuntimeError('fixture setup error')
    except RuntimeError:
        assert failure
    assert dict(os.environ) == original


def test_explicit_protocol_resolves_credentials_without_litellm_catalog(tmp_path, frozen, monkeypatch):
    import harbor.agents.agent_auth_resolution as auth
    from harbor.agents.factory import AgentFactory

    def forbidden_catalog(provider):
        raise AssertionError('Explicit native protocol must not require the LiteLLM provider catalog')

    monkeypatch.setattr(auth, '_is_litellm_provider', forbidden_catalog)
    monkeypatch.setenv('SHEETS_FACTORY_API_KEY', 'fixture-preflight-credential')
    config = _job_config(tmp_path, frozen, concurrency=1, binary='/usr/bin/codex', base_url='https://test.invalid/v1')
    AgentFactory.run_preflight(config.agents[0], skip_credential_checks=False)


@pytest.mark.parametrize('mutate,infra', [(False, False), (True, False), (False, True)])
def test_run_writes_final_audit_and_preserves_infrastructure_status(tmp_path, mutate, infra):
    manifest = make_release(tmp_path)

    async def fake_execute(directory, selection, audit, **kwargs):
        assert (directory / 'selection_manifest.json').is_file()
        for index, task in enumerate(selection['tasks']):
            path = persist_result(directory, task, reward=0)
            if infra and index == 0:
                result = json.loads(path.read_text())
                result['exception_info'] = {'exception_type': 'ServiceUnavailableError'}
                path.write_text(json.dumps(result))
        if mutate:
            Path(selection['tasks'][0]['task_directory'], 'instruction.md').write_text('tampered')

    directory = tmp_path / 'evaluation'
    result = run_evaluation(manifest, directory, phase='development', project_root=tmp_path, execute=fake_execute)
    assert result == json.loads((directory / 'evaluation_manifest.json').read_text())
    assert result['status'] == ('infrastructure_failed' if mutate or infra else 'completed')
    assert result['gate_passed'] is False
    if mutate:
        assert result['failure_kind'] == 'snapshot_changed'
    if infra:
        assert result['score']['overall_pass_at_1'] is None
    with pytest.raises(FrontierError, match='already exists'):
        run_evaluation(manifest, directory, phase='development', project_root=tmp_path, execute=fake_execute)


def make_infra_evaluation(tmp_path, *, failure='NonZeroAgentExitCodeError', provider_error=True, missing=False):
    manifest = make_release(tmp_path)

    async def initial(directory, selection, audit, **kwargs):
        persist_result(directory, selection['tasks'][0], reward=0)
        if missing:
            return
        path = persist_result(directory, selection['tasks'][1], reward=0)
        result = json.loads(path.read_text())
        result['exception_info'] = {'exception_type': failure}
        path.write_text(json.dumps(result))
        if provider_error:
            log = path.parent / 'agent/codex.txt'
            log.parent.mkdir()
            log.write_text(json.dumps({'type': 'turn.failed', 'error': {
                'message': 'stream disconnected before completion: error sending request'}}) + '\n')

    directory = tmp_path / 'evaluation'
    result = run_evaluation(manifest, directory, phase='development', project_root=tmp_path, execute=initial)
    assert result['status'] == 'infrastructure_failed'
    return directory, result


@pytest.mark.parametrize('missing', [False, True])
def test_resume_only_infrastructure_keeps_valid_zero_and_all_raw_evidence(tmp_path, missing):
    directory, before = make_infra_evaluation(tmp_path, missing=missing)
    selection_raw = (directory / 'selection_manifest.json').read_bytes()
    raw_results = {attempt['result_file']: Path(attempt['result_file']).read_bytes() for attempt in before['attempts']}
    manifest_raw = (directory / 'evaluation_manifest.json').read_bytes()
    seen = []

    async def recovery(run_dir, selection, audit, *, job_name, **kwargs):
        seen.extend(selection['selected_task_ids'])
        for task in selection['tasks']:
            persist_result(run_dir, task, reward=1, job_name=job_name)

    result = resume_infrastructure(directory, project_root=tmp_path, execute=recovery)
    assert result['status'] == 'completed' and result['score']['overall_pass_at_1'] == .5
    assert seen == ['task-01']
    assert [(attempt['task_id'], attempt['reward']) for attempt in result['attempts']] == [('task-01', 1), ('task-00', 0)]
    assert (directory / 'selection_manifest.json').read_bytes() == selection_raw
    assert all(Path(path).read_bytes() == raw for path, raw in raw_results.items())
    retry = result['infrastructure_retries'][0]
    assert retry['task_ids'] == ['task-01'] and retry['job_name'] == 'frontier-infra-001'
    assert retry['previous_manifest_sha256'] == sha256(manifest_raw).hexdigest()
    assert Path(retry['previous_manifest_file']).read_bytes() == manifest_raw
    assert len(result['infra_history']) == (0 if missing else 1)
    if not missing:
        proof = retry['authorization'][0]
        assert proof['reason'] == 'terminal_provider_failure'
        assert proof['evidence_sha256'] == sha256(Path(proof['evidence_file']).read_bytes()).hexdigest()
    with pytest.raises(FrontierError, match='ended infrastructure failure'):
        resume_infrastructure(directory, project_root=tmp_path, execute=recovery)


def test_ambiguous_agent_exit_and_unproven_timeout_are_not_retried(tmp_path):
    directory, before = make_infra_evaluation(tmp_path, provider_error=False)
    attempt = next(attempt for attempt in before['attempts'] if attempt['status'] == 'infrastructure_error')
    assert assess_infrastructure_retry(attempt)['eligible'] is False
    with pytest.raises(FrontierError, match='No certified infrastructure failures'):
        resume_infrastructure(directory, project_root=tmp_path)
    attempt['failure_kind'] = 'AgentTimeoutError'
    assert assess_infrastructure_retry(attempt)['eligible'] is False


def test_resume_has_a_bounded_infrastructure_retry_budget(tmp_path):
    directory, before = make_infra_evaluation(tmp_path)

    async def still_unavailable(run_dir, selection, audit, *, job_name, **kwargs):
        for task in selection['tasks']:
            path = persist_result(run_dir, task, job_name=job_name)
            result = json.loads(path.read_text())
            result['exception_info'] = {'exception_type': 'ServiceUnavailableError'}
            path.write_text(json.dumps(result))

    for index in [1, 2]:
        result = resume_infrastructure(directory, project_root=tmp_path, execute=still_unavailable)
        assert result['status'] == 'infrastructure_failed'
        assert len(result['infrastructure_retries']) == index
        assert result['score']['overall_pass_at_1'] is None
    with pytest.raises(FrontierError, match='No certified infrastructure failures'):
        resume_infrastructure(directory, project_root=tmp_path, execute=still_unavailable)
    assert len(list((directory / 'harbor_jobs').glob('*/*/result.json'))) == 4


@pytest.mark.parametrize('artifact', ['selection', 'task', 'result'])
def test_resume_refuses_changed_evidence_before_calling_model(tmp_path, artifact):
    directory, before = make_infra_evaluation(tmp_path)
    if artifact == 'selection':
        path = directory / 'selection_manifest.json'
    elif artifact == 'task':
        selection = json.loads((directory / 'selection_manifest.json').read_text())
        path = Path(selection['tasks'][0]['task_directory']) / 'instruction.md'
    else:
        path = Path(before['attempts'][0]['result_file'])
    path.write_text(path.read_text() + ' ')
    with pytest.raises((FrontierError, ValueError)):
        resume_infrastructure(directory, project_root=tmp_path)


@pytest.mark.parametrize('bound', [True, False])
def test_resume_never_restarts_an_intentional_early_stop(tmp_path, bound):
    directory, before = make_infra_evaluation(tmp_path)
    path = directory / 'private/early_stop.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({'reason': 'observed_success_lower_bound_exceeds_threshold',
        'selection_manifest_sha256': before['selection_manifest']['sha256'] if bound else '0' * 64}))
    with pytest.raises(FrontierError, match='[Ii]ntentional early.stop'):
        resume_infrastructure(directory, project_root=tmp_path)


def timeout_result(tmp_path, frozen, reward=0, *, command_output='ordinary command exited 1'):
    task = frozen['tasks'][0]
    path = persist_result(tmp_path, task, reward)
    result = json.loads(path.read_text())
    result.update(exception_info={'exception_type': 'AgentTimeoutError'},
        agent_execution={'started_at': '2026-10-30T01:00:00+01:00', 'finished_at': '2026-10-30T01:30:00+01:00'},
        verifier={'started_at': '2026-10-30T00:30:01Z', 'finished_at': '2026-10-30T00:30:02Z'},
        agent_result={'n_input_tokens': 100, 'n_output_tokens': 20})
    path.write_text(json.dumps(result))
    log = path.parent / 'agent/codex.txt'
    log.parent.mkdir()
    log.write_text(json.dumps({'type': 'item.completed', 'item': {'type': 'command_execution',
        'status': 'failed', 'exit_code': 1, 'aggregated_output': command_output}}) + '\n')
    diagnostics = path.parent / 'verifier/diagnostics.json'
    diagnostics.parent.mkdir()
    diagnostics.write_text(json.dumps({'reward': reward,
        'reason': 'matched' if reward else 'value_or_modified_set_mismatch'}))
    (diagnostics.parent / 'reward.txt').write_text(str(reward))
    return path, result


@pytest.mark.parametrize('reward', [0, 1])
def test_normal_exhausted_budget_uses_actual_verifier_reward_and_bound_review(tmp_path, frozen, reward):
    path, result = timeout_result(tmp_path, frozen, reward)
    task = frozen['tasks'][0]
    review = review_agent_timeout(result, task, result_file=path)
    assert review['classification'] == 'normal_agent_budget_exhaustion'
    assert review['reward'] == reward and review['agent_elapsed_seconds'] == 1800
    assert review['native_log_sha256'] == sha256(Path(review['native_log_file']).read_bytes()).hexdigest()
    assert review['diagnostics_sha256'] == sha256(Path(review['diagnostics_file']).read_bytes()).hexdigest()
    assert classify_result(result, task, timeout_review=review) == ('scored', reward, None)
    attempts = collect_attempts(tmp_path, frozen)
    assert attempts[0]['status'] == 'scored' and attempts[0]['exception_resolution'] == review
    assert attempts[0]['reward'] == reward


@pytest.mark.parametrize('defect', ['short', 'no_usage', 'missing_log', 'no_tools', 'provider_failure',
    'provider_pending', 'recalculate_permissions', 'verifier_runtime', 'missing_reward', 'wrong_reward',
    'missing_verifier_timing', 'wrong_exception', 'multiplier', 'naive_timestamp'])
def test_timeout_without_healthy_budget_and_verifier_proof_stays_infrastructure(tmp_path, frozen, defect):
    path, result = timeout_result(tmp_path, frozen)
    log = path.parent / 'agent/codex.txt'
    diagnostics = path.parent / 'verifier/diagnostics.json'
    if defect == 'short':
        result['agent_execution']['finished_at'] = '2026-10-30T01:00:10+01:00'
    elif defect == 'no_usage':
        result['agent_result']['n_output_tokens'] = 0
    elif defect == 'missing_log':
        log.unlink()
    elif defect == 'no_tools':
        log.write_text(json.dumps({'type': 'turn.started'}))
    elif defect in {'provider_failure', 'provider_pending'}:
        event = ({'type': 'turn.failed', 'error': {'message': 'stream disconnected'}} if defect == 'provider_failure'
                 else {'type': 'error', 'message': 'Reconnecting after stream disconnected'})
        log.write_text(log.read_text() + json.dumps(event) + '\n')
    elif defect == 'recalculate_permissions':
        log.write_text(log.read_text().replace('ordinary command exited 1', '/usr/local/bin/recalculate: Permission denied'))
    elif defect == 'verifier_runtime':
        diagnostics.write_text(json.dumps({'reward': 0, 'reason': 'verification_error', 'error_type': 'RuntimeError'}))
    elif defect == 'missing_reward':
        (diagnostics.parent / 'reward.txt').unlink()
    elif defect == 'wrong_reward':
        (diagnostics.parent / 'reward.txt').write_text('1')
    elif defect == 'missing_verifier_timing':
        result['verifier'] = None
    elif defect == 'wrong_exception':
        result['exception_info']['exception_type'] = 'AgentSetupTimeoutError'
    elif defect == 'multiplier':
        result['config']['agent_timeout_multiplier'] = 2
    else:
        result['agent_execution']['started_at'] = '2026-10-30T00:00:00'
    path.write_text(json.dumps(result))
    assert review_agent_timeout(result, frozen['tasks'][0], result_file=path) is None
    assert collect_attempts(tmp_path, frozen)[0]['status'] == 'infrastructure_error'


def test_ordinary_solver_tool_errors_are_neither_provider_failure_nor_infra_retry(tmp_path, frozen):
    path, result = timeout_result(tmp_path, frozen,
        command_output='My diagnostic script printed: stream disconnected; subprocess.TimeoutExpired')
    review = review_agent_timeout(result, frozen['tasks'][0], result_file=path)
    assert review is not None
    assert collect_attempts(tmp_path, frozen)[0]['status'] == 'scored'
    result['exception_info']['exception_type'] = 'NonZeroAgentExitCodeError'
    path.write_text(json.dumps(result))
    attempt = collect_attempts(tmp_path, frozen)[0]
    assert assess_infrastructure_retry(attempt)['eligible'] is False
