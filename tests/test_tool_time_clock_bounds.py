"""A conservative clock bound must never turn incomplete evidence into zero."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from sheets_factory.evaluation.tool_time_clock_bounds import (
    _StaticExec, ClockEvidenceError, ENDPOINT_MARGIN_NS,
    account_complete_clock_disagreement,
)

BASE_MS = 1_800_000_000_000


def stamp(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def duration(ns):
    return {'secs': ns // 1_000_000_000, 'nanos': ns % 1_000_000_000}


def native_event(kind, ms, **values):
    return {'timestamp': stamp(ms), 'type': 'event_msg', 'payload': {'type': kind, **values}}


def fixture(tmp_path, *, parallel=False, patch=False):
    result = tmp_path/'result.json'
    (tmp_path/'agent/sessions').mkdir(parents=True)
    native = [native_event('task_started', BASE_MS+1, turn_id='turn', root_turn_id='turn')]
    stream = [{'type': 'thread.started', 'thread_id': 'thread'}, {'type': 'turn.started'}]
    commands = ['echo first'] + (['echo second'] if parallel else [])
    if parallel:
        code = 'const r=await Promise.allSettled([' + ','.join(
            'tools.exec_command('+json.dumps({'cmd': x})+')' for x in commands) + ']);r.forEach(text);'
    else:
        code = 'text(await tools.exec_command({cmd:"echo first"}));'
    if patch:
        code += 'text(await tools.apply_patch("*** Begin Patch\\n*** Add File: /app/a.py\\n+1\\n*** End Patch"));'
    native.append({'timestamp': stamp(BASE_MS+10), 'type': 'response_item',
                   'payload': {'type': 'custom_tool_call', 'call_id': 'call', 'name': 'exec', 'input': code}})
    for index, command in enumerate(commands):
        item = {'type': 'CommandExecution', 'id': f'n{index}', 'process_id': str(42+index),
                'command': ['/bin/bash', '-lc', command], 'status': 'completed', 'exit_code': 0,
                'duration': duration(1_020_000_000)}
        native.append(native_event('item_completed', BASE_MS+1100, item=item, thread_id='thread', turn_id='turn',
                                  started_at_ms=BASE_MS+20, completed_at_ms=BASE_MS+1020))
        tool = {'id': f's{index}', 'type': 'command_execution', 'command': "/bin/bash -lc '"+command+"'"}
        stream += [{'type': 'item.started', 'item': deepcopy(tool)},
                   {'type': 'item.completed', 'item': {**tool, 'status': 'completed', 'exit_code': 0}}]
    if patch:
        item = {'type': 'FileChange', 'id': 'patch', 'changes': {'/app/a.py': {'type': 'add'}}, 'status': 'completed'}
        native.append(native_event('item_completed', BASE_MS+1050, item=item, thread_id='thread', turn_id='turn',
                                  started_at_ms=BASE_MS+1021, completed_at_ms=BASE_MS+1025))
        tool = {'id': 's-patch', 'type': 'file_change', 'changes': [{'path': '/app/a.py', 'kind': 'add'}]}
        stream += [{'type': 'item.started', 'item': deepcopy(tool)},
                   {'type': 'item.completed', 'item': {**tool, 'status': 'completed'}}]
    native.append({'timestamp': stamp(BASE_MS+1200), 'type': 'response_item',
                   'payload': {'type': 'custom_tool_call_output', 'call_id': 'call',
                               'output': [{'type': 'input_text', 'text': 'Script completed\nOutput:\n'}]}})
    native.append(native_event('task_complete', BASE_MS+1300, turn_id='turn', root_turn_id='turn'))
    stream.append({'type': 'turn.completed', 'usage': {}})
    actual = {'agent_execution': {'started_at': stamp(BASE_MS), 'finished_at': stamp(BASE_MS+1400)},
              'finished_at': stamp(BASE_MS+1500), 'exception_info': None,
              'verifier_result': {'rewards': {'reward': 1}}}
    paths = {'result': result, 'native': tmp_path/'agent/sessions/rollout.jsonl', 'stream': tmp_path/'agent/codex.txt'}
    data = {'result': actual, 'native': native, 'stream': stream}
    save(paths, data)
    return paths, data


def save(paths, data):
    paths['result'].write_text(json.dumps(data['result']))
    for kind in ['native', 'stream']:
        paths[kind].write_text('\n'.join(json.dumps(r) for r in data[kind])+'\n')


def run(paths, data, **kwargs):
    save(paths, data)
    return account_complete_clock_disagreement(paths['result'], **kwargs)


def tools(data):
    return [r['payload'] for r in data['native'] if r.get('payload', {}).get('type') == 'item_completed']


def completed(data):
    return [r['item'] for r in data['stream'] if r['type'] == 'item.completed']


def assert_unknown(receipt, expected=None):
    assert receipt['state'] == 'unknown'
    assert receipt['passed'] is None
    assert receipt['cumulative_exact_ns'] is None
    assert receipt['cumulative_tool_seconds'] is None
    assert receipt['problems']
    if expected:
        assert any(expected in problem for problem in receipt['problems']), receipt['problems']


def test_complete_larger_clock_plus_full_wrapper_is_a_bound_not_exact(tmp_path):
    paths, data = fixture(tmp_path)
    before = {p: p.read_bytes() for p in paths.values()}
    r = run(paths, data)
    assert r['state'] == 'verified_conservative_bound' and r['passed'] is True
    assert r['exact_state'] == 'unknown' and r['original_exact_receipt']['state'] == 'unknown'
    assert r['cumulative_tool_seconds'] is None and r['cumulative_exact_ns'] is None
    assert r['cumulative_upper_bound_ns'] == 1_020_000_000+ENDPOINT_MARGIN_NS+1_190_000_000+ENDPOINT_MARGIN_NS
    assert r['overlap_credit_ns'] == 0 and r['qualification_claimed'] is False
    assert r['coverage']['native_stream_ordered_signatures_status_and_exits_equal']
    assert {p: p.read_bytes() for p in paths.values()} == before


def test_larger_span_is_used_when_duration_is_smaller(tmp_path):
    paths, data = fixture(tmp_path)
    tools(data)[0]['item']['duration'] = duration(900_000_000)
    r = run(paths, data)
    assert r['passed'] is True
    assert r['tools'][0]['upper_ns'] == 1_002_000_000


def test_parallel_tools_and_wrappers_are_fully_summed_no_union_credit(tmp_path):
    paths, data = fixture(tmp_path, parallel=True)
    r = run(paths, data)
    assert r['passed'] is True
    assert r['primitive_upper_sum_ns'] == 2*1_022_000_000
    assert r['wrapper_upper_sum_ns'] == 1_192_000_000
    assert r['cumulative_upper_bound_ns'] == 3_236_000_000


def test_file_change_without_duration_is_explicit_span_not_zero(tmp_path):
    paths, data = fixture(tmp_path, patch=True)
    r = run(paths, data)
    assert r['passed'] is True
    patch = r['tools'][1]
    assert patch['clock_kind'] == 'span_only_file_change'
    assert patch['reported_duration_ns'] is None and patch['upper_ns'] == 6_000_000


def test_recognized_literal_poll_is_bound_to_owned_native_process(tmp_path):
    paths, data = fixture(tmp_path)
    data['native'][-1:-1] = [
        {'timestamp': stamp(BASE_MS+1220), 'type': 'response_item', 'payload': {
            'type': 'custom_tool_call', 'call_id': 'poll', 'name': 'exec',
            'input': 'text(await tools.write_stdin({session_id:42,chars:""}));'}},
        {'timestamp': stamp(BASE_MS+1240), 'type': 'response_item', 'payload': {
            'type': 'custom_tool_call_output', 'call_id': 'poll',
            'output': [{'type': 'input_text', 'text': 'Script completed\n'}]}}]
    r = run(paths, data)
    assert r['passed'] is True and r['coverage']['owned_poll_count'] == 1
    assert r['wrappers'][1]['static_calls'][0]['owner_native_id'] == 'n0'


def test_poll_cannot_claim_a_process_launched_in_the_same_wrapper(tmp_path):
    paths, data = fixture(tmp_path)
    data['native'][1]['payload']['input'] = (
        'text(await tools.write_stdin({session_id:42,chars:""}));' + data['native'][1]['payload']['input'])
    assert_unknown(run(paths, data), 'owned completed native process')


@pytest.mark.parametrize('budget', [2.214, 2, 0.1])
def test_upper_at_or_above_budget_stays_unknown_never_false(tmp_path, budget):
    paths, data = fixture(tmp_path)
    r = run(paths, data, budget_seconds=budget)
    assert_unknown(r, 'does not prove')
    assert r['cumulative_upper_bound_ns'] == 2_214_000_000


def test_exact_1800_second_upper_is_inconclusive(tmp_path):
    paths, data = fixture(tmp_path)
    tools(data)[0]['item']['duration'] = duration(1_798_806_000_000)
    r = run(paths, data)
    assert r['cumulative_upper_bound_ns'] == 1_800_000_000_000
    assert_unknown(r, 'does not prove')


@pytest.mark.parametrize('budget', [True, 0, -1, 'nan', 'Infinity', {}, '0.00000000001'])
def test_invalid_budgets_fail_closed(tmp_path, budget):
    paths, data = fixture(tmp_path)
    assert_unknown(run(paths, data, budget_seconds=budget))


@pytest.mark.parametrize('mutate,problem', [
    (lambda d: d['result'].update(exception_info={'exception_type': 'Timeout'}), 'normal terminal'),
    (lambda d: d['result'].pop('exception_info'), 'normal terminal'),
    (lambda d: d['result']['agent_execution'].pop('finished_at'), 'timestamp'),
    (lambda d: d['native'].pop(), 'task_complete'),
    (lambda d: d['native'].insert(3, deepcopy(d['native'][2])), 'Duplicate native primitive'),
    (lambda d: d['native'].insert(2, deepcopy(d['native'][1])), 'Duplicate native wrapper'),
    (lambda d: d['native'].pop(-2), 'wrapper results'),
    (lambda d: d['native'][1]['payload'].update(name='other'), 'outer exec'),
    (lambda d: d['native'][-2]['payload']['output'][0].update(text='Script running with cell ID 12'), 'completed static'),
    (lambda d: d['native'][-1]['payload'].update(root_turn_id='other'), 'terminal identity'),
    (lambda d: d['native'][0]['payload'].update(turn_id='other'), 'turn identities'),
    (lambda d: d['stream'].pop(), 'Stream terminal'),
    (lambda d: d['stream'].insert(-1, {'type': 'turn.failed'}), 'failed stream'),
    (lambda d: d['stream'][0].update(thread_id='different'), 'thread identity'),
    (lambda d: d['stream'].insert(3, deepcopy(d['stream'][2])), 'Duplicate stream tool'),
    (lambda d: d['stream'].pop(2), 'Unbalanced'),
    (lambda d: completed(d)[0].update(exit_code=1), 'exit mismatch'),
    (lambda d: completed(d)[0].update(status='failed'), 'status or exit mismatch'),
    (lambda d: tools(d)[0]['item'].update(status='in_progress'), 'not terminal'),
    (lambda d: tools(d)[0]['item'].pop('duration'), 'duration is missing'),
    (lambda d: tools(d)[0]['item'].update(exit_code=None), 'exit code'),
    (lambda d: tools(d)[0].update(started_at_ms=BASE_MS-1), 'outside agent'),
    (lambda d: tools(d)[0].update(completed_at_ms=BASE_MS+19), 'outside agent'),
    (lambda d: tools(d)[0].update(started_at_ms=True), 'start ms'),
    (lambda d: tools(d)[0]['item'].update(duration={'secs': True, 'nanos': 3}), 'duration seconds'),
    (lambda d: tools(d)[0]['item'].update(duration={'secs': 0, 'nanos': 1_000_000_000}), 'overflow'),
    (lambda d: tools(d)[0]['item'].update(duration={'secs': 0, 'nanos': -1}), 'nanoseconds'),
    (lambda d: tools(d)[0]['item'].update(duration=1.2), 'duration structure'),
    (lambda d: tools(d)[0]['item'].update(type='McpToolCall'), 'Unknown native'),
    (lambda d: d['native'].insert(-1, native_event('item_started', BASE_MS+1250)), 'pending native'),
])
def test_missing_malformed_incomplete_and_mismatched_evidence_is_unknown(tmp_path, mutate, problem):
    paths, data = fixture(tmp_path)
    mutate(data)
    assert_unknown(run(paths, data), problem)


def test_ordered_command_match_is_stronger_than_equal_counts(tmp_path):
    paths, data = fixture(tmp_path, parallel=True)
    first, second = completed(data)
    first['command'], second['command'] = second['command'], first['command']
    # Change corresponding starts too. Both streams remain internally balanced.
    starts = [r['item'] for r in data['stream'] if r['type'] == 'item.started']
    starts[0]['command'], starts[1]['command'] = first['command'], second['command']
    assert_unknown(run(paths, data), 'Ordered native/stream')


def test_unknown_or_future_poll_is_not_charged_as_zero(tmp_path):
    paths, data = fixture(tmp_path)
    data['native'][1]['payload']['input'] += 'text(await tools.write_stdin({session_id:999,chars:""}));'
    assert_unknown(run(paths, data), 'owned completed native process')


def test_static_launch_cannot_omit_or_add_a_primitive(tmp_path):
    paths, data = fixture(tmp_path)
    data['native'][1]['payload']['input'] += 'text(await tools.exec_command({cmd:"extra"}));'
    assert_unknown(run(paths, data), 'coverage differ')


def test_static_command_and_patch_paths_must_match_not_just_intervals(tmp_path):
    paths, data = fixture(tmp_path)
    data['native'][1]['payload']['input'] = 'text(await tools.exec_command({cmd:"unrelated"}));'
    assert_unknown(run(paths, data), 'static primitive ownership')


@pytest.mark.parametrize('code', [
    'for(let i=0;i<100;i++)text(await tools.exec_command({cmd:"x"}));',
    'if(true)text(await tools.exec_command({cmd:"x"}));',
    'const r=await Promise.all([1,2].map(x=>tools.exec_command({cmd:"x"})));r.forEach(text);',
    'text(await tools.exec_command({cmd:command}));',
    'text(await tools.exec_command({cmd:`echo x`}));',
    'text(await tools["exec_command"]({cmd:"x"}));',
    'const f=tools.exec_command;text(await f({cmd:"x"}));',
    'text(await tools.exec_command({cmd:"x",cmd:"y"}));',
    'text(await tools.write_stdin({session_id:r.session_id}));',
    'text(await tools.wait({cell_id:"cell"}));',
    'text(await tools.web__run({}));',
    'const r=await tools.exec_command({cmd:"x"});r.forEach(x=>tools.exec_command({cmd:"y"}));',
    'text(await tools.apply_patch(patch));',
    'text(await tools.apply_patch("*** Begin Patch\\n*** Update File: a\\n*** Move to: b\\n*** End Patch"));',
])
def test_dynamic_or_unknown_execution_is_not_in_static_support(code):
    with pytest.raises(ClockEvidenceError):
        _StaticExec(code).parse()


@pytest.mark.parametrize('code,count', [
    ('text(await tools.exec_command({cmd:"x"}));', 1),
    ('const r=await tools.exec_command({cmd:"x"});text(r);', 1),
    ('const r=await Promise.all([tools.exec_command({cmd:"x"}),tools.exec_command({cmd:"y"})]);r.forEach(text);', 2),
    ('const r=await Promise.allSettled([tools.exec_command({cmd:"x"})]);for(let i=0;i<r.length;i++)text({i,...r[i]});', 1),
    ('text(ALL_TOOLS.filter(x=>/exec_command|file/.test(x.name+" "+x.description)));text(await tools.exec_command({cmd:"x"}));', 1),
    ('text(ALL_TOOLS.filter(x=>/file/.test(x.name+" "+x.description)).map(x=>({name:x.name,description:x.description.slice(0,160)})));text(await tools.exec_command({cmd:"x"}));', 1),
    ('// a harmless comment\ntext(await tools.exec_command({cmd:"for i in 1 2; do echo tools.wait; done"}));', 1),
])
def test_explicit_supported_finite_grammar(code, count):
    assert len(_StaticExec(code).parse()) == count


def test_frozen_five_ms_tolerance_is_not_relaxed(tmp_path):
    paths, data = fixture(tmp_path)
    tools(data)[0]['item']['duration'] = duration(1_005_000_000)
    assert_unknown(run(paths, data))
    tools(data)[0]['item']['duration'] = duration(1_005_000_001)
    assert run(paths, data)['passed'] is True


def test_no_missing_duration_or_missing_tail_becomes_zero_even_if_fast(tmp_path):
    paths, data = fixture(tmp_path)
    tools(data)[0]['item'].pop('duration')
    assert_unknown(run(paths, data))
    assert account_complete_clock_disagreement(paths['result'])['cumulative_upper_bound_ns'] is None


def test_malformed_stream_tail_and_additional_native_sessions_reject(tmp_path):
    paths, data = fixture(tmp_path)
    with paths['stream'].open('a') as out:
        out.write('{"type":')
    assert_unknown(account_complete_clock_disagreement(paths['result']))
    save(paths, data)
    (paths['native'].parent/'second.jsonl').write_text('{}\n')
    assert_unknown(account_complete_clock_disagreement(paths['result']), 'one complete native session')


@pytest.mark.parametrize('tail', [
    '{"type":"turn.completed","type":"turn.completed"}\n',
    '{"type":"turn.completed","usage":{"number":NaN}}\n',
    '{"type":"turn.completed","usage":{"number":1e999}}\n',
])
def test_ambiguous_or_nonfinite_json_is_not_accepted(tmp_path, tail):
    paths, data = fixture(tmp_path)
    lines = paths['stream'].read_text().splitlines()
    paths['stream'].write_text('\n'.join(lines[:-1])+'\n'+tail)
    assert_unknown(account_complete_clock_disagreement(paths['result']))


def test_reward_does_not_control_bound_acceptance(tmp_path):
    paths, data = fixture(tmp_path)
    data['result']['verifier_result']['rewards']['reward'] = 0
    zero = run(paths, data)
    data['result']['verifier_result']['rewards']['reward'] = 1
    one = run(paths, data)
    assert zero['state'] == one['state'] == 'verified_conservative_bound'
    assert zero['cumulative_upper_bound_ns'] == one['cumulative_upper_bound_ns']
