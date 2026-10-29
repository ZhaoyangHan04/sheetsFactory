"""Partial rollout observations do not infer task solvability or correctness."""
import json
from pathlib import Path

import pytest

from sheets_factory.llm import CodexError
from sheets_factory.llm.trace import recover_failed_attempt
from sheets_factory.checkers.program import infrastructure


def failure(tmp_path, events, *, kind='timeout', isolated=True):
    record = tmp_path / 'record'
    record.mkdir()
    workspace = tmp_path / 'public-workspace'
    workspace.mkdir()
    (record / 'result.json').write_text(json.dumps({'call_id': 'call-a', 'task_id': 'task-a',
        'stage': 'trajectory', 'role': 'trace_agent', 'isolated': isolated,
        'workspace': str(workspace), 'duration_ms': 420000, 'timeout_seconds': 420,
        'failure_kind': kind, 'error': 'Recorded backend execution failure'}))
    (record / 'events.jsonl').write_text(''.join(json.dumps(event) + '\n' for event in events))
    return CodexError('Recorded backend execution failure', 'call-a', str(record)), workspace


def progress():
    return [{'type': 'thread.started', 'thread_id': 'public-thread'},
            {'type': 'item.completed', 'item': {'type': 'reasoning', 'text': 'Inspect the public forecast.'}},
            {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'inspect input.xlsx',
                                               'aggregated_output': 'Public sheet names', 'exit_code': 0}}]


def test_timeout_after_progress_is_an_ungraded_partial_attempt_not_infrastructure_failure(tmp_path):
    events = progress()
    error, workspace = failure(tmp_path, events)
    result = recover_failed_attempt(error, task_id='task-a', workspace=workspace)
    assert result['events'] == events and result['call_id'] == 'call-a'
    assert result['attempt_budget_exhausted']
    assert 'infrastructure_error' not in result
    assert result['observations'][0]['kind'] == 'attempt_budget_exhausted'
    assert not {'solved', 'reward', 'completion_status'} & set(result)
    assessment = infrastructure({'infrastructure_health_report': {'healthy': True, 'checks': ['backend available']}}, [result])
    assert assessment.state == 'clear'


@pytest.mark.parametrize('kind,fatal', [('timeout', True), ('process_exit', False), ('execution_error', False)])
def test_provider_or_process_failure_remains_infrastructure_even_after_progress(tmp_path, kind, fatal):
    events = progress()
    if fatal:
        events.append({'type': 'turn.failed', 'error': {'message': 'Provider transport disconnected'}})
    error, workspace = failure(tmp_path, events, kind=kind)
    result = recover_failed_attempt(error, task_id='task-a', workspace=workspace)
    assert result['infrastructure_error'] and not result.get('attempt_budget_exhausted')
    assert result['events'] == events
    assert infrastructure({}, [result]).state == 'flagged'


def test_timeout_without_progress_preserves_infrastructure_uncertainty(tmp_path):
    error, workspace = failure(tmp_path, [{'type': 'thread.started'}])
    result = recover_failed_attempt(error, task_id='task-a', workspace=workspace)
    assert result['infrastructure_error'] and result['infrastructure_cause_unknown']
    assert not result.get('attempt_budget_exhausted')


def test_private_or_other_task_record_is_not_exposed_as_public_trace(tmp_path):
    error, workspace = failure(tmp_path, progress(), isolated=False)
    result = recover_failed_attempt(error, task_id='task-a', workspace=workspace)
    assert result['events'] == [] and not result['backend_record_verified']
    assert result['infrastructure_error']


def test_trajectory_node_retains_budget_exhausted_events_and_call_receipt(tmp_path):
    from sheets_factory.core.node import TaskContext
    from sheets_factory.nodes.quality import TrajectoryNode
    root = Path(__file__).resolve().parents[1]
    input_file = tmp_path / 'input.xlsx'
    input_file.write_bytes(b'offline transport fixture; no spreadsheet calculations asserted')
    events = progress()
    class Backend:
        def attempt(self, prompt, workspace, **kwargs):
            record = tmp_path / 'call-record'
            record.mkdir()
            (record / 'result.json').write_text(json.dumps({'call_id': 'call-budget',
                'task_id': kwargs['taskid'], 'stage': kwargs['stage'], 'role': 'trace_agent',
                'isolated': True, 'workspace': str(workspace), 'failure_kind': 'timeout',
                'timeout_seconds': 420, 'duration_ms': 420000, 'error': 'Attempt budget exhausted'}))
            (record / 'events.jsonl').write_text(''.join(json.dumps(event) + '\n' for event in events))
            raise CodexError('Attempt budget exhausted', 'call-budget', str(record))
    ctx = TaskContext('run', 'task-a', 'debugging', input_file, tmp_path / 'task',
        {'project_root': str(root), 'agents': {'trajectory_timeout_seconds': 420}}, None, Backend(), None)
    ctx.data.update(input=input_file, instruction='Apply the public workbook rules.')
    trace = TrajectoryNode().execute(ctx)['traces'][0]
    assert trace['events'] == events and trace['call_id'] == 'call-budget'
    assert trace['attempt_budget_exhausted'] and 'infrastructure_error' not in trace
    stored = json.loads((ctx.revision_dir / 'private/trajectory.json').read_text())
    assert stored['observations'][0]['kind'] == 'attempt_budget_exhausted'
    assert 'record_path' not in stored  # No private backend filesystem path enters public diagnostic evidence.
