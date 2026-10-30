"""Prospective operational guards cannot become elapsed-time model failures."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from sheets_factory.evaluation.budget import (
    ExecutionBudgetError, resolve_execution_budget, validate_execution_budget,
    validate_selection_execution_budget,
)
from sheets_factory.evaluation.frontier import (
    FrontierError, _job_config, assess_infrastructure_retry, classify_result,
    collect_attempts, freeze_selection, resume_infrastructure, review_agent_timeout,
    run_evaluation, summarize,
)
from test_frontier import make_release, persist_result, persist_timing, timeout_result


BUDGET = {'version': 1, 'elapsed_policy': 'operational_guard',
          'elapsed_guard_seconds': 14400, 'tool_budget_seconds': 1800}


def guarded_source(tmp_path):
    manifest = make_release(tmp_path)
    source = json.loads(manifest.read_text())
    source['execution_budget'] = dict(BUDGET)
    manifest.write_text(json.dumps(source))
    return manifest


@pytest.fixture
def guarded(tmp_path):
    return freeze_selection(guarded_source(tmp_path), tmp_path / 'evaluation', phase='development')


def persist_guard(run_dir, task, *, seconds=1, reward=0, trial='trial'):
    path = persist_result(run_dir, task, reward=reward, trial=trial)
    result = json.loads(path.read_text())
    result['exception_info'] = {'exception_type': 'AgentTimeoutError'}
    result['agent_execution']['finished_at'] = '2026-10-30T04:00:00+00:00'
    result['finished_at'] = '2026-10-30T04:00:02+00:00'
    path.write_text(json.dumps(result))
    persist_timing(path, seconds=seconds)
    return path, result


def test_long_elapsed_guard_requires_explicit_source_contract_and_binds_every_task(tmp_path, guarded):
    assert guarded['execution_budget'] == BUDGET
    assert guarded['timeout_seconds'] == 14400
    assert all(task['execution_budget'] == BUDGET and task['timeout_seconds'] == 14400
               for task in guarded['tasks'])
    assert validate_selection_execution_budget(guarded) == BUDGET
    config = _job_config(tmp_path, guarded, concurrency=1, binary='/usr/bin/codex', base_url='https://test.invalid/v1')
    assert config.agents[0].override_timeout_sec == 14400
    with pytest.raises(ExecutionBudgetError, match='900–1800'):
        resolve_execution_budget({}, 14400)
    with pytest.raises(ExecutionBudgetError, match='conflicts'):
        resolve_execution_budget({'execution_budget': BUDGET}, 1800)


@pytest.mark.parametrize('budget', [
    None, [], {}, BUDGET | {'version': True}, BUDGET | {'version': 2},
    BUDGET | {'elapsed_policy': 'model_deadline'}, BUDGET | {'elapsed_guard_seconds': True},
    BUDGET | {'elapsed_guard_seconds': 1799}, BUDGET | {'elapsed_guard_seconds': 14400.0},
    BUDGET | {'tool_budget_seconds': 1801}, BUDGET | {'tool_budget_seconds': 1800.0},
    BUDGET | {'extra': 'ambiguous'},
])
def test_malformed_explicit_budget_is_rejected_without_snapshot(tmp_path, budget):
    manifest = make_release(tmp_path)
    source = json.loads(manifest.read_text())
    source['execution_budget'] = budget
    manifest.write_text(json.dumps(source))
    with pytest.raises(ExecutionBudgetError):
        validate_execution_budget(budget)
    with pytest.raises(FrontierError, match='execution_budget'):
        freeze_selection(manifest, tmp_path / 'evaluation', phase='development')
    assert not (tmp_path / 'evaluation').exists()


@pytest.mark.parametrize('defect', ['task_budget', 'task_missing', 'task_timeout', 'task_policy',
                                    'selection_timeout', 'selection_policy', 'selection_missing'])
def test_selection_and_task_contract_must_agree_before_execution_or_collection(tmp_path, guarded, defect):
    selected = deepcopy(guarded)
    task = selected['tasks'][0]
    if defect == 'task_budget':
        task['execution_budget']['elapsed_guard_seconds'] = 14401
    elif defect == 'task_missing':
        del task['execution_budget']
    elif defect == 'task_timeout':
        task['timeout_seconds'] = 1800
    elif defect == 'task_policy':
        task['tool_time_policy']['measurement'] = 'different'
    elif defect == 'selection_timeout':
        selected['timeout_seconds'] = 1800
    elif defect == 'selection_policy':
        selected['tool_time_policy']['exclude_model_response_time'] = False
    else:
        del selected['execution_budget']
    with pytest.raises(ExecutionBudgetError):
        validate_selection_execution_budget(selected)
    with pytest.raises(FrontierError):
        collect_attempts(tmp_path, selected)
    with pytest.raises(FrontierError):
        _job_config(tmp_path, selected, concurrency=1, binary='/usr/bin/codex', base_url='https://test.invalid/v1')


@pytest.mark.parametrize('defect', ['missing', 'budget', 'timeout', 'policy', 'attempt_missing', 'attempt_budget'])
def test_evaluation_contract_must_agree_with_selection(guarded, defect):
    evaluation = {key: deepcopy(guarded[key]) for key in ('execution_budget', 'timeout_seconds', 'tool_time_policy')}
    assert validate_selection_execution_budget(guarded, evaluation) == BUDGET
    if defect == 'missing':
        del evaluation['execution_budget']
    elif defect == 'budget':
        evaluation['execution_budget']['elapsed_guard_seconds'] = 14401
    elif defect == 'timeout':
        evaluation['timeout_seconds'] = 1800
    elif defect == 'policy':
        evaluation['tool_time_policy']['measurement'] = 'different'
    elif defect == 'attempt_missing':
        evaluation['attempts'] = [{'task_id': guarded['tasks'][0]['task_id']}]
    else:
        evaluation['attempts'] = [{'execution_budget': BUDGET | {'elapsed_guard_seconds': 14401}}]
    with pytest.raises(ExecutionBudgetError):
        validate_selection_execution_budget(guarded, evaluation)


def test_guard_stop_reserves_attempt_without_zero_or_blind_retry(tmp_path, guarded):
    path, result = persist_guard(tmp_path, guarded['tasks'][0])
    review = review_agent_timeout(result, guarded['tasks'][0], result_file=path)
    assert review['classification'] == 'operational_elapsed_guard_reached'
    assert review['agent_elapsed_seconds'] == 14400
    assert classify_result(result, guarded['tasks'][0], timeout_review=review) == (
        'evidence_incomplete', None, 'operational_elapsed_guard_reached')
    before = path.read_bytes()
    entry = collect_attempts(tmp_path, guarded)[0]
    assert entry['status'] == 'evidence_incomplete' and entry['reward'] is None
    assert entry['failure_kind'] == 'operational_elapsed_guard_reached'
    assert entry['raw_verifier_reward'] == 0 and entry['tool_time']['passed'] is True
    assert entry['execution_budget'] == BUDGET
    assert path.read_bytes() == before
    assert summarize(guarded, [entry])[0]['overall_pass_at_1'] is None
    with pytest.raises(FrontierError, match='never be retried'):
        assess_infrastructure_retry(entry)
    assert assess_infrastructure_retry(entry | {'status': 'infrastructure_error'})['eligible'] is False
    persist_result(tmp_path, guarded['tasks'][0], trial='replacement')
    with pytest.raises(FrontierError, match='Multiple scored attempts'):
        collect_attempts(tmp_path, guarded)


@pytest.mark.parametrize('measured', [1799, 1800, 1801])
def test_only_proven_tool_exhaustion_scores_guard_timeout_zero(tmp_path, guarded, measured):
    path, result = persist_guard(tmp_path, guarded['tasks'][0], seconds=measured, reward=1)
    # A true tool-budget failure needs no fabricated verifier outcome.
    result['verifier_result'] = None
    path.write_text(json.dumps(result))
    entry = collect_attempts(tmp_path, guarded)[0]
    assert entry['tool_time']['cumulative_tool_seconds'] == measured
    assert entry['raw_verifier_reward'] is None
    if measured >= 1800:
        assert (entry['status'], entry['reward'], entry['failure_kind']) == (
            'scored', 0, 'cumulative_tool_budget_exhausted')
    else:
        assert entry['status'] == 'evidence_incomplete' and entry['reward'] is None


def test_unknown_timing_at_guard_cannot_be_zero(tmp_path, guarded):
    path, _ = persist_guard(tmp_path, guarded['tasks'][0])
    (path.parent / 'agent/sessions/fixture.jsonl').unlink()
    entry = collect_attempts(tmp_path, guarded)[0]
    assert entry['tool_time']['passed'] is None
    assert entry['reward'] is None and entry['status'] == 'evidence_incomplete'
    assert entry['failure_kind'] == 'operational_elapsed_guard_reached'


def test_completed_wrong_answer_after_legacy_deadline_is_still_valid_under_new_contract(tmp_path, guarded):
    path = persist_result(tmp_path, guarded['tasks'][0], reward=0)
    result = json.loads(path.read_text())
    result['agent_execution']['finished_at'] = '2026-10-30T02:00:00+00:00'
    path.write_text(json.dumps(result))
    entry = collect_attempts(tmp_path, guarded)[0]
    assert entry['status'] == 'scored' and entry['reward'] == 0 and entry['failure_kind'] is None


def test_new_evaluation_persists_contract_and_guard_evidence_without_resampling(tmp_path):
    manifest = guarded_source(tmp_path)

    async def execute(directory, selection, audit, **kwargs):
        for task in selection['tasks']:
            persist_guard(directory, task)

    directory = tmp_path / 'evaluation'
    result = run_evaluation(manifest, directory, phase='development', project_root=tmp_path, execute=execute)
    selection = json.loads((directory / 'selection_manifest.json').read_text())
    assert validate_selection_execution_budget(selection, result) == BUDGET
    assert result['status'] == 'evidence_incomplete' and result['score']['overall_pass_at_1'] is None
    assert result['score']['operational_guard_stops'] == 2
    assert result['gate_passed'] is False and not result['infrastructure_retries']
    original = {attempt['result_file']: Path(attempt['result_file']).read_bytes() for attempt in result['attempts']}
    with pytest.raises(FrontierError, match='ended infrastructure failure'):
        resume_infrastructure(directory, project_root=tmp_path, execute=execute)
    assert all(Path(path).read_bytes() == raw for path, raw in original.items())


def test_new_infrastructure_resume_replaces_only_service_failure_and_preserves_guard(tmp_path):
    manifest = guarded_source(tmp_path)

    async def initial(directory, selection, audit, **kwargs):
        persist_guard(directory, selection['tasks'][0])
        path = persist_result(directory, selection['tasks'][1])
        result = json.loads(path.read_text())
        result['exception_info'] = {'exception_type': 'ServiceUnavailableError'}
        path.write_text(json.dumps(result))

    directory = tmp_path / 'evaluation'
    before = run_evaluation(manifest, directory, phase='development', project_root=tmp_path, execute=initial)
    guard = next(attempt for attempt in before['attempts'] if attempt['status'] == 'evidence_incomplete')
    guard_raw = Path(guard['result_file']).read_bytes()
    seen = []

    async def recovery(directory, selection, audit, *, job_name, **kwargs):
        seen.extend(selection['selected_task_ids'])
        for task in selection['tasks']:
            persist_result(directory, task, job_name=job_name)

    assert before['status'] == 'infrastructure_failed'
    result = resume_infrastructure(directory, project_root=tmp_path, execute=recovery)
    assert seen == ['task-01']
    assert result['status'] == 'evidence_incomplete' and result['score']['overall_pass_at_1'] is None
    assert Path(guard['result_file']).read_bytes() == guard_raw
    validate_selection_execution_budget(json.loads((directory / 'selection_manifest.json').read_text()), result)


def test_absent_contract_preserves_legacy_timeout_review_and_frozen_bytes(tmp_path):
    manifest = make_release(tmp_path)
    selection = freeze_selection(manifest, tmp_path / 'evaluation', phase='development')
    assert 'execution_budget' not in selection and all('execution_budget' not in task for task in selection['tasks'])
    assert selection['timeout_seconds'] == 1800
    path, result = timeout_result(tmp_path, selection, reward=0)
    files = [manifest, tmp_path / 'evaluation/selection_manifest.json', path]
    hashes = {file: sha256(file.read_bytes()).hexdigest() for file in files}
    review = review_agent_timeout(result, selection['tasks'][0], result_file=path)
    assert review['classification'] == 'normal_agent_budget_exhaustion'
    entry = collect_attempts(tmp_path, selection)[0]
    assert (entry['status'], entry['reward'], entry['failure_kind']) == ('scored', 0, None)
    assert 'execution_budget' not in entry
    assert {file: sha256(file.read_bytes()).hexdigest() for file in files} == hashes
