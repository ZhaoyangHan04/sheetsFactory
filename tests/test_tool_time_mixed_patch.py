"""Complete native patch timing with an independent process in the same wrapper."""
from copy import deepcopy
import json

import pytest

from sheets_factory.evaluation.tool_time import account_tool_time, account_trial_tool_time
from sheets_factory.evaluation.tool_time_bounds import account_trial_tool_time_bounds
from test_tool_time import call, item, stamp

PATCH = '*** Begin Patch\n*** Update File: /app/model.py\n@@\n-old\n+new\n*** End Patch'


def fixture_records(code=None):
    code = code or ('await tools.apply_patch(' + json.dumps(PATCH) + '); '
                    'await tools.write_stdin({session_id:7});')
    records = call('launch', 0, 1, name='exec_command', arguments={'cmd': 'slow'})
    records += call('patch-and-poll', 30, 40, code=code)
    records += [item('process', 0, 100, process='7', command='slow')]
    patch = item('patch', 31, 33, kind='FileChange')
    patch['payload']['item'].pop('command')
    patch['payload']['item'].pop('process_id')
    patch['payload']['item']['changes'] = {'/app/model.py': {'type': 'update', 'move_path': None}}
    return records + [patch]


def native_session(tmp_path, records):
    path = tmp_path / 'native.jsonl'
    path.write_text(''.join(json.dumps(record) + '\n' for record in records))
    return path


def test_legacy_unknown_is_preserved_and_explicit_ownership_counts_both_parallel_tools(tmp_path):
    path = native_session(tmp_path, fixture_records())
    legacy = account_tool_time([path])
    assert legacy['state'] == 'unknown'
    assert 'Native execution has no launching wrapper' in legacy['problems']
    exact = account_tool_time([path], allow_mixed_file_change_polls=True)
    assert exact['state'] == 'verified', exact['problems']
    assert exact['cumulative_tool_seconds'] == 102  # Process100 + independent patch2.
    assert [wrapper['uncovered_seconds'] for wrapper in exact['wrappers']] == [0, 0]


@pytest.mark.parametrize('code', [
    'await tools.apply_patch(dynamic); await tools.write_stdin({session_id:7});',
    'text(' + json.dumps('tools.apply_patch(' + json.dumps(PATCH) + ')') + '); await tools.write_stdin({session_id:7});',
    'await tools.apply_patch(' + json.dumps(PATCH.replace('/app/model.py', '/app/other.py')) + '); await tools.write_stdin({session_id:7});',
    'await tools.apply_patch(' + json.dumps(PATCH) + '+suffix); await tools.write_stdin({session_id:7});',
    'await tools.apply_patch(' + json.dumps(PATCH) + '); await tools.apply_patch(' + json.dumps(PATCH) + '); await tools.write_stdin({session_id:7});',
])
def test_ambiguous_dynamic_or_wrong_path_ownership_remains_unknown(tmp_path, code):
    path = native_session(tmp_path, fixture_records(code))
    result = account_tool_time([path], allow_mixed_file_change_polls=True)
    assert result['state'] == 'unknown' and result['passed'] is None


def test_conflicting_patch_paths_cannot_rebind_one_execution(tmp_path):
    records = fixture_records()
    conflicting = deepcopy(records[-1])
    conflicting['payload']['item']['changes'] = {'/app/other.py': {'type': 'update'}}
    result = account_tool_time([native_session(tmp_path, records + [conflicting])],
                              allow_mixed_file_change_polls=True)
    assert result['state'] == 'unknown' and 'Conflicting' in result['problems'][0]


def test_v2_recovers_exact_complete_timing_without_a_stop_bound_and_preserves_v1(tmp_path):
    trial = tmp_path / 'trial'
    (trial / 'agent/sessions').mkdir(parents=True)
    native_session(trial / 'agent/sessions', fixture_records())
    (trial / 'agent/codex.txt').write_text('\n'.join(json.dumps({'type': 'item.completed',
        'item': {'type': kind, 'id': 'stream-' + kind}}) for kind in ('command_execution', 'file_change')) + '\n')
    result = trial / 'result.json'
    result.write_text(json.dumps({'agent_execution': {'started_at': stamp(0), 'finished_at': stamp(110)}}))
    assert account_trial_tool_time(result)['state'] == 'unknown'
    receipt = account_trial_tool_time_bounds(result)
    assert receipt['state'] == 'verified' and receipt['passed'] is True
    assert receipt['cumulative_tool_seconds'] == 102
    assert receipt['stream_coverage']['matched'] is True
    assert receipt['ownership_extension'] == 'single_literal_patch_exact_paths_with_independent_poll'
    assert receipt['legacy_exact_parser_problems']


def test_recovered_ownership_does_not_waive_complete_native_stream_coverage(tmp_path):
    trial = tmp_path / 'trial'
    (trial / 'agent/sessions').mkdir(parents=True)
    native_session(trial / 'agent/sessions', fixture_records())
    (trial / 'agent/codex.txt').write_text('\n'.join(json.dumps({'type': 'item.completed',
        'item': {'type': kind, 'id': identity}}) for kind, identity in (
            ('command_execution', 'c'), ('file_change', 'p'), ('file_change', 'missing'))) + '\n')
    result = trial / 'result.json'
    result.write_text(json.dumps({'agent_execution': {'started_at': stamp(0), 'finished_at': stamp(110)}}))
    receipt = account_trial_tool_time_bounds(result)
    assert receipt['state'] == 'unknown' and receipt['passed'] is None
