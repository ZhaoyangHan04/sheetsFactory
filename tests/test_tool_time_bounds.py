"""Prospective stop bounds preserve exact unknown and reject unowned fanout."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from sheets_factory.evaluation.tool_time import account_trial_tool_time
from sheets_factory.evaluation.tool_time_bounds import (POLICY_V2, _INSPECT,
    account_trial_tool_time_bounds, static_pending_commands)

EPOCH = datetime(2026, 10, 30, tzinfo=timezone.utc)


def stamp(seconds):
    return (EPOCH + timedelta(seconds=seconds)).isoformat()


def ref(path):
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def wrapper(identity, seconds, code):
    return {'type': 'response_item', 'timestamp': stamp(seconds),
            'payload': {'type': 'custom_tool_call', 'call_id': identity, 'name': 'exec', 'input': code}}


def fixture(tmp_path, *, stop=100, pending=None):
    trial = tmp_path / 'trial'
    (trial / 'agent/sessions').mkdir(parents=True)
    dump(trial / 'config.json', {'trial_name': 'trial'})
    result = trial / 'result.json'
    dump(result, {'agent_execution': {'started_at': stamp(0), 'finished_at': stamp(20)}})
    records = [wrapper('done', 0, 'await tools.exec_command({cmd:"done"});'),
        {'type': 'response_item', 'timestamp': stamp(2), 'payload': {'type': 'custom_tool_call_output', 'call_id': 'done', 'output': ''}},
        {'type': 'event_msg', 'timestamp': stamp(2), 'payload': {'type': 'item_completed',
            'started_at_ms': int(EPOCH.timestamp()*1000), 'completed_at_ms': int(EPOCH.timestamp()*1000)+2000,
            'item': {'id': 'primitive-done', 'type': 'CommandExecution', 'command': 'done', 'process_id': '1',
                     'status': 'completed', 'duration': {'secs': 2, 'nanos': 0}}}}]
    records += pending or [wrapper('pending', 10, 'await tools.exec_command({cmd:"pending"});')]
    session = trial / 'agent/sessions/native.jsonl'
    session.write_text(''.join(json.dumps(row)+'\n' for row in records))
    (trial / 'agent/codex.txt').write_text(json.dumps({'type': 'item.completed', 'item': {'type': 'command_execution', 'id': 'public-done'}})+'\n')
    def daemon(at):
        return {'command': ['docker', 'info', '--format', '{{json .ID}}'], 'returncode': 0,
                'stdout': '"daemon-one"', 'stderr': '', 'utc_before': stamp(at), 'utc_after': stamp(at)}
    identity = trial / 'private/tool_time/container_identity.json'
    full = 'a' * 64
    name = 'trial__env-main-1'
    observation = {'command': ['docker', 'inspect', '--type', 'container', name, '--format', _INSPECT],
        'returncode': 0, 'stdout': json.dumps({'Id': full, 'Name': '/' + name, 'Running': True, 'Restarting': False}),
        'stderr': '', 'utc_before': stamp(5), 'utc_after': stamp(5)}
    dump(identity, {'schema_version': 2, 'kind': 'live_trial_container_identity', 'trial_directory': str(trial.resolve()),
        'trial_config': ref(trial/'config.json'), 'container_name': name, 'container_id': full,
        'daemon_id': 'daemon-one', 'captured_at': stamp(5), 'daemon_observation': daemon(4), 'running_observation': observation})
    observations = [{'command': ['docker', 'inspect', '--type', 'container', target, '--format', _INSPECT],
        'returncode': 1, 'stdout': '', 'stderr': 'Error response from daemon: No such container: ' + target,
        'utc_before': stamp(stop), 'utc_after': stamp(stop)} for target in [full, name]]
    stop_file = trial / 'private/tool_time/stop_receipt.json'
    dump(stop_file, {'schema_version': 2, 'kind': 'authoritative_trial_container_stop_bound', 'exact_stop_time': None,
        'identity_file': ref(identity), 'result_file': ref(result), 'daemon_before': daemon(stop),
        'container_observations': observations, 'daemon_after': daemon(stop), 'stop_upper_utc': stamp(stop)})
    return result, stop_file, session


def test_pending_bound_never_becomes_an_invented_exact_duration(tmp_path):
    result, stop, session = fixture(tmp_path)
    assert account_trial_tool_time(result)['state'] == 'unknown'
    receipt = account_trial_tool_time_bounds(result, stop_receipt_file=stop)
    assert receipt['state'] == 'bounded', receipt['problems']
    assert receipt['exact_timing_state'] == 'unknown'
    assert receipt['cumulative_tool_seconds'] is None
    assert receipt['lower_bound_seconds'] == 2 and receipt['upper_bound_seconds'] == 92
    assert receipt['passed'] is True and receipt['stream_coverage']['matched']
    assert receipt['completed_prefix']['derived_event_subset_sha256']


def test_live_identity_can_precede_agent_start_within_the_actual_trial_window(tmp_path):
    result, stop, _ = fixture(tmp_path)
    document = json.loads(result.read_text())
    document['started_at'] = stamp(-10)
    document['agent_execution']['started_at'] = stamp(0)
    result.write_text(json.dumps(document))
    bound = json.loads(stop.read_text())
    identity_path = Path(bound['identity_file']['path'])
    identity = json.loads(identity_path.read_text())
    identity['captured_at'] = stamp(-.001)
    identity['running_observation'].update(utc_before=stamp(-.002), utc_after=stamp(-.001))
    identity['daemon_observation'].update(utc_before=stamp(-.003), utc_after=stamp(-.002))
    dump(identity_path, identity)
    bound.update(identity_file=ref(identity_path), result_file=ref(result))
    dump(stop, bound)
    receipt = account_trial_tool_time_bounds(result, stop_receipt_file=stop)
    assert receipt['state'] == 'bounded' and receipt['passed'] is True, receipt['problems']
    assert receipt['upper_bound_seconds'] == 92


def test_capture_before_trial_start_is_still_rejected(tmp_path):
    result, stop, _ = fixture(tmp_path)
    document = json.loads(result.read_text())
    document['started_at'] = stamp(6)  # Capture at5 cannot belong to this trial.
    result.write_text(json.dumps(document))
    bound = json.loads(stop.read_text()); bound['result_file'] = ref(result); dump(stop, bound)
    receipt = account_trial_tool_time_bounds(result, stop_receipt_file=stop)
    assert receipt['state'] == 'unknown' and receipt['passed'] is None


def test_all_parallel_pending_wrappers_and_static_children_add_separately(tmp_path):
    pending = [wrapper('a', 10, 'await Promise.all([tools.exec_command({cmd:"one"}),tools.exec_command({cmd:"two"})]);'),
               wrapper('b', 15, 'await tools.exec_command({cmd:"three"});')]
    result, stop, _ = fixture(tmp_path, pending=pending)
    receipt = account_trial_tool_time_bounds(result, stop_receipt_file=stop)
    assert receipt['state'] == 'bounded', receipt['problems']
    assert receipt['upper_bound_seconds'] == 2 + 2*90 + 85
    assert [p['independent_primitive_launch_upper_count'] for p in receipt['pending_bounds']] == [2, 1]


def test_upper_bound_equal_to_budget_is_not_certified_as_below_it(tmp_path):
    result, stop, _ = fixture(tmp_path, stop=1808)
    receipt = account_trial_tool_time_bounds(result, stop_receipt_file=stop)
    assert receipt['upper_bound_seconds'] == 1800
    assert receipt['passed'] is None  # True duration might still be below 1800.


@pytest.mark.parametrize('code', [
    'for(let i=0;i<n;i++){await tools.exec_command({cmd:"x"});}',
    'await tools[name]({cmd:"x"});',
    'await tools.exec_command({cmd:load("command")});',
    'await tools.exec_command({cmd:"x"+suffix});',
    'await tools.exec_command({cmd:"x",cmd:dynamic});',
    'await tools.exec_command({...options,cmd:"x"});',
    'await tools.write_stdin({session_id:7});',
    'await tools.web__run({search_query:[]});',
])
def test_dynamic_or_external_fanout_rejects(tmp_path, code):
    result, stop, _ = fixture(tmp_path, pending=[wrapper('p', 10, code)])
    receipt = account_trial_tool_time_bounds(result, stop_receipt_file=stop)
    assert receipt['state'] == 'unknown' and receipt['passed'] is None


def test_real_style_destructuring_and_python_loops_inside_literal_are_static():
    code = 'let{output,...rest}=await tools.exec_command({cmd:"python3 -c \'for x in []: pass\'",yield_time_ms:30000});text(output);Object.assign(globalThis,rest);'
    assert static_pending_commands({'name': 'exec', 'input': code}) == ["python3 -c 'for x in []: pass'"]


@pytest.mark.parametrize('mutation', ['daemon_down', 'daemon_changed', 'still_running', 'wrong_result', 'late_identity'])
def test_unproven_container_stop_or_identity_never_authorizes_a_bound(tmp_path, mutation):
    result, stop, _ = fixture(tmp_path)
    value = json.loads(stop.read_text())
    if mutation == 'daemon_down': value['daemon_after']['returncode'] = 1
    elif mutation == 'daemon_changed': value['daemon_after']['stdout'] = '"different"'
    elif mutation == 'still_running':
        o = value['container_observations'][0]
        o.update(returncode=0, stdout=json.dumps({'Id':'a'*64,'Running':True,'Restarting':False,'Status':'running'}))
    elif mutation == 'wrong_result': value['result_file']['sha256'] = 'b'*64
    else:
        identity = Path(value['identity_file']['path'])
        data = json.loads(identity.read_text())
        data['captured_at'] = data['running_observation']['utc_after'] = stamp(15)
        dump(identity, data)
        value['identity_file'] = ref(identity)
    dump(stop, value)
    receipt = account_trial_tool_time_bounds(result, stop_receipt_file=stop)
    assert receipt['state'] == 'unknown' and receipt['passed'] is None


def test_completed_prefix_overlap_is_rejected_without_double_counting(tmp_path):
    result, stop, session = fixture(tmp_path)
    records = [json.loads(line) for line in session.read_text().splitlines()]
    records[1]['timestamp'] = stamp(12)
    session.write_text(''.join(json.dumps(row)+'\n' for row in records))
    receipt = account_trial_tool_time_bounds(result, stop_receipt_file=stop)
    assert receipt['state'] == 'unknown' and 'overlap' in ' '.join(receipt['problems'])
