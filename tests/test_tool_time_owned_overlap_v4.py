"""Prospective v4: no services; adversarial overlap, ownership and tail cases."""
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket
import subprocess

import openpyxl
import pytest

from sheets_factory.evaluation import clock_resource_frontier as v3
from sheets_factory.evaluation import clock_resource_frontier_v4 as v4
from sheets_factory.evaluation import native_transport_frontier as native3
from sheets_factory.evaluation import native_transport_frontier_v4 as native4
from sheets_factory.evaluation import tool_time_clock_bounds as old
from sheets_factory.evaluation import tool_time_clock_bounds_v4 as clock
from sheets_factory.evaluation.resource_harbor import export_resource_harbor, inspect_resource_export

ROOT = Path(__file__).resolve().parents[1]
BUDGET = {'version': 1, 'elapsed_policy': 'operational_guard', 'elapsed_guard_seconds': 14400, 'tool_budget_seconds': 1800}
spec = importlib.util.spec_from_file_location('_frozen_clock_fixture', ROOT / 'tests/test_tool_time_clock_bounds.py')
fixture_helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture_helper)


@pytest.fixture(autouse=True)
def no_services(monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('Clock tests may not start processes or network services')
    monkeypatch.setattr(subprocess, 'run', forbidden); monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)


def scenario(tmp_path):
    paths, data = fixture_helper.fixture(tmp_path, parallel=True)
    # n0 has a20ms disagreement; n1 exactly agrees. Only n1 may earn credit.
    fixture_helper.tools(data)[1]['item']['duration'] = fixture_helper.duration(1_000_000_000)
    return paths, data


def run(paths, data, **kwargs):
    fixture_helper.save(paths, data)
    return clock.account_complete_clock_overlap(paths['result'], **kwargs)


def unknown(receipt, text=None):
    assert receipt['state'] == 'unknown' and receipt['passed'] is None
    assert receipt['cumulative_tool_seconds'] is receipt['cumulative_exact_ns'] is None
    assert receipt['problems']
    if text: assert any(text in p for p in receipt['problems']), receipt['problems']


def test_full_native_sum_and_only_owned_common_interior_credit_with_uncovered_time(tmp_path):
    paths, data = scenario(tmp_path); fixture_helper.save(paths, data)
    before = {p: p.read_bytes() for p in paths.values()}; receipt = run(paths, data)
    assert receipt['passed'] and receipt['state'] == 'verified_owned_overlap_bound'
    assert receipt['primitive_upper_sum_ns'] == 2_024_000_000
    assert receipt['wrapper_upper_sum_ns'] == 1_192_000_000
    assert receipt['overlap_credit_ns'] == 996_000_000
    assert receipt['cumulative_upper_bound_ns'] == 2_220_000_000
    assert receipt['tools'][0]['credit_eligible_common_interior_ns'] is None
    assert receipt['wrappers'][0]['uncovered_upper_ns'] == 196_000_000
    assert {p: p.read_bytes() for p in paths.values()} == before
    assert receipt['coverage']['all_parallel_primitive_uppers_summed']
    assert receipt['coverage']['all_uncovered_wrapper_time_retained']
    assert not receipt['historical_result_modified'] and not receipt['qualification_claimed']
    assert all('command' not in call for w in receipt['wrappers'] for call in w['static_calls'])


def test_parallel_credit_is_wrapper_union_not_sum_of_overlapping_children(tmp_path):
    paths, data = scenario(tmp_path)
    # A third parallel command agrees too; it must add a full primitive while
    # earning no second credit for the already covered wrapper interior.
    first = deepcopy(fixture_helper.tools(data)[1]); first['item'].update(id='n2', process_id='44', command=['/bin/bash', '-lc', 'echo third'])
    data['native'].insert(-2, fixture_helper.native_event('item_completed', fixture_helper.BASE_MS + 1100, **{k: v for k, v in first.items() if k != 'type'}))
    code = data['native'][1]['payload']['input']; code = code.replace(']);r.forEach', ',tools.exec_command({cmd:"echo third"})]);r.forEach')
    data['native'][1]['payload']['input'] = code
    tool = {'id': 's2', 'type': 'command_execution', 'command': "/bin/bash -lc 'echo third'"}
    data['stream'][-1:-1] = [{'type': 'item.started', 'item': tool}, {'type': 'item.completed', 'item': {**tool, 'status': 'completed', 'exit_code': 0}}]
    receipt = run(paths, data)
    assert receipt['passed'] and receipt['primitive_upper_sum_ns'] == 3_026_000_000
    assert receipt['overlap_credit_ns'] == 996_000_000
    assert receipt['cumulative_upper_bound_ns'] == 3_222_000_000
    assert len(receipt['wrappers'][0]['credited_native_intersections']) == 2


def test_disagreeing_native_clock_earns_no_overlap_even_if_wrapper_inside_span(tmp_path):
    paths, data = fixture_helper.fixture(tmp_path)
    receipt = run(paths, data)
    assert receipt['passed'] and receipt['overlap_credit_ns'] == 0
    assert receipt['cumulative_upper_bound_ns'] == 2_214_000_000


def test_valid_literal_process_poll_gets_only_its_own_overlap(tmp_path):
    paths, data = scenario(tmp_path); base = fixture_helper.BASE_MS
    data['native'][-1:-1] = [
        {'timestamp': fixture_helper.stamp(base + 500), 'type': 'response_item', 'payload': {'type': 'custom_tool_call', 'call_id': 'poll', 'name': 'exec', 'input': 'text(await tools.write_stdin({session_id:43,chars:""}));'}},
        {'timestamp': fixture_helper.stamp(base + 700), 'type': 'response_item', 'payload': {'type': 'custom_tool_call_output', 'call_id': 'poll', 'output': [{'type': 'input_text', 'text': 'Script completed\n'}]}}]
    receipt = run(paths, data)
    assert receipt['passed'] and receipt['coverage']['owned_poll_count'] == 1
    assert receipt['wrappers'][1]['overlap_credit_ns'] == 196_000_000
    assert receipt['wrappers'][1]['uniquely_owned_or_polled_native_ids'] == ['n1']


def test_unrelated_running_primitive_cannot_credit_metadata_only_poll_of_other_process(tmp_path):
    paths, data = scenario(tmp_path); base = fixture_helper.BASE_MS
    # n0 disagrees. Polling n0 cannot take credit from concurrently running n1.
    data['native'][-1:-1] = [
        {'timestamp': fixture_helper.stamp(base + 500), 'type': 'response_item', 'payload': {'type': 'custom_tool_call', 'call_id': 'poll', 'name': 'exec', 'input': 'text(await tools.write_stdin({session_id:42,chars:""}));'}},
        {'timestamp': fixture_helper.stamp(base + 700), 'type': 'response_item', 'payload': {'type': 'custom_tool_call_output', 'call_id': 'poll', 'output': [{'type': 'input_text', 'text': 'Script completed\n'}]}}]
    receipt = run(paths, data)
    assert receipt['passed'] and receipt['wrappers'][1]['overlap_credit_ns'] == 0
    assert receipt['wrappers'][1]['uncovered_upper_ns'] == 202_000_000


@pytest.mark.parametrize('budget', [2.22, 2.219999999, 1, True, 0, 'nan', '0.00000000001'])
def test_upper_at_or_across_threshold_unknown_never_false_or_wall_shortcut(tmp_path, budget):
    paths, data = scenario(tmp_path); receipt = run(paths, data, budget_seconds=budget)
    unknown(receipt)


def test_strict_threshold_one_ns_above_bound_passes_as_bound_not_exact(tmp_path):
    paths, data = scenario(tmp_path); receipt = run(paths, data, budget_seconds='2.220000001')
    assert receipt['passed'] and receipt['complete']
    assert receipt['cumulative_tool_seconds'] is receipt['cumulative_exact_ns'] is None


@pytest.mark.parametrize('flag,accepted', [('', True), ('i', True), ('g', False), ('m', False), ('ii', False), ('ig', False)])
def test_metadata_only_finite_regex_flags_and_frozen_parser_unchanged(flag, accepted):
    prefix = 'text(ALL_TOOLS.filter(x=>/file/' + flag + '.test(x.name+" "+x.description)));'
    code = prefix + 'text(await tools.exec_command({cmd:"x"}));'
    if accepted: assert clock.static_calls(code) == [{'kind': 'CommandExecution', 'command': 'x'}]
    else:
        with pytest.raises(clock.ClockEvidenceError): clock.static_calls(code)
    if flag:
        with pytest.raises(old.ClockEvidenceError): old._StaticExec(code).parse()


@pytest.mark.parametrize('code', [
    'text(ALL_TOOLS.filter(x=>tools.exec_command({cmd:"x"})));text(await tools.exec_command({cmd:"x"}));',
    'const r=await Promise.all([1,2].map(x=>tools.exec_command({cmd:"x"})));r.forEach(text);',
    'for(let i=0;i<2;i++)text(await tools.exec_command({cmd:"x"}));',
    'text(await tools.exec_command({cmd:command}));',
    'text(await tools.write_stdin({session_id:r.session_id}));',
    'const r=await tools.exec_command({cmd:"x"});r.forEach(x=>tools.exec_command({cmd:"y"}));',
    'text(await tools["exec_command"]({cmd:"x"}));'])
def test_dynamic_dispatch_or_ownership_still_refuses(code):
    with pytest.raises(clock.ClockEvidenceError): clock.static_calls(code)


def test_literal_fanout_bound_not_expanded():
    good = 'const r=await Promise.all([' + ','.join('tools.exec_command({cmd:"c' + str(i) + '"})' for i in range(32)) + ']);r.forEach(text);'
    assert len(clock.static_calls(good)) == 32
    with pytest.raises(clock.ClockEvidenceError): clock.static_calls(good.replace(']);r.', ',tools.exec_command({cmd:"overflow"})]);r.'))


@pytest.mark.parametrize('mutate,problem', [
    (lambda d: d['native'].pop(), 'task_complete'),
    (lambda d: d['stream'].pop(), 'Stream terminal'),
    (lambda d: d['native'].pop(-2), 'wrapper results'),
    (lambda d: fixture_helper.tools(d)[1]['item'].update(id='n0'), 'Duplicate native primitive'),
    (lambda d: fixture_helper.tools(d)[1]['item'].update(process_id='42'), 'Duplicate native process'),
    (lambda d: d['native'][1]['payload'].update(input=d['native'][1]['payload']['input'].replace('echo second', 'echo first')), 'primitive ownership'),
    (lambda d: d['native'][1]['payload'].update(input=d['native'][1]['payload']['input'] + 'text(await tools.write_stdin({session_id:999,chars:""}));'), 'owned completed native process'),
    (lambda d: d['native'][1]['payload'].update(input=d['native'][1]['payload']['input'] + 'text(await tools.write_stdin({session_id:42,chars:""}));'), 'owned completed native process'),
    (lambda d: d['stream'].insert(3, deepcopy(d['stream'][2])), 'Duplicate stream tool'),
    (lambda d: fixture_helper.completed(d)[1].update(exit_code=2), 'exit mismatch'),
    (lambda d: d['native'][-2]['payload']['output'][0].update(text='Script running with cell ID12'), 'completed static'),
    (lambda d: d['result'].update(exception_info={'exception_type': 'Timeout'}), 'normal terminal')])
def test_incomplete_ambiguous_or_different_events_never_earn_credit(tmp_path, mutate, problem):
    paths, data = scenario(tmp_path); mutate(data); unknown(run(paths, data), problem)


@pytest.fixture
def exported(tmp_path):
    task = tmp_path / 'actual'; (task / 'public').mkdir(parents=True); (task / 'private').mkdir()
    book = openpyxl.Workbook(); book.active['A1'] = 10; book.save(task / 'public/input.xlsx')
    book.active['A1'] = 20; book.save(task / 'private/goal.xlsx'); book.close()
    (task / 'public/instruction.md').write_text('Set the supplied number to twenty. Save /app/output.xlsx.')
    output = tmp_path / 'export/task-one'
    export_resource_harbor(task, output, {'task_id': 'task-one', 'revision': 0, 'revision_hash': 'fixture', 'mode': 'debugging'}, runtime_profile=ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml')
    value = {'selected_task_ids': ['task-one'], 'execution_budget': deepcopy(BUDGET), 'tool_time_policy_version': 4,
        'native_transport_profile': native4.transport_profile(), 'tasks': [{'task_id': 'task-one', 'mode': 'debugging', 'task_directory': str(output),
        'revision': 0, 'revision_hash': 'fixture', 'harbor_export_binding': inspect_resource_export(output), 'execution_budget': deepcopy(BUDGET)}]}
    path = tmp_path / 'source.json'; path.write_text(json.dumps(value)); return path


def test_prospective_four_selection_same_budget_resources_model_and_retry8(exported, tmp_path):
    before_policy = deepcopy(v3.POLICY_V3); selected = native4.freeze_selection(exported, tmp_path / 'selection', phase='development')
    assert selected['tool_time_policy_version'] == 4 and selected['tool_time_policy'] == native4.POLICY_V4 == v4.POLICY_V4
    assert selected['execution_budget'] == BUDGET and selected['timeout_seconds'] == 14400
    assert selected['n_attempts'] == 1 and selected['model'] == 'gpt-6.1-sol' and selected['reasoning_effort'] == 'xhigh'
    assert len(native4.TASK_FILES) == 17 and native4.TASK_FILES == native3.TASK_FILES
    config = native4._job_config(tmp_path, selected, concurrency=1, binary=Path('/native/codex'), base_url='http://invalid').model_dump(mode='json')
    agent = config['agents'][0]; provider = agent['kwargs']['config']['model_providers']['factory']
    assert agent['import_path'] == 'sheets_factory.evaluation.native_transport_frontier_v4:LocalCodex'
    assert provider['stream_max_retries'] == 8 and 'request_max_retries' not in provider and 'stream_idle_timeout_ms' not in provider
    assert config['retry']['max_retries'] == 0 and config['n_attempts'] == 1
    assert v3.POLICY_V3 == before_policy and v3.POLICY_V3['version'] == 3


@pytest.mark.parametrize('version', [None, 1, 2, 3, True, '4'])
def test_no_reinterpretation_of_old_or_missing_selection_policy(exported, tmp_path, version):
    source = json.loads(exported.read_text())
    if version is None: source.pop('tool_time_policy_version')
    else: source['tool_time_policy_version'] = version
    exported.write_text(json.dumps(source))
    with pytest.raises(native4.FrontierError, match='prospective'): native4.freeze_selection(exported, tmp_path / 'selection', phase='development')
    assert not (tmp_path / 'selection/selection_manifest.json').exists()


@pytest.mark.parametrize('reward', [0, 1])
def test_new_v4_bound_preserves_raw_scored_reward_and_retains_v3_unknown(monkeypatch, tmp_path, reward):
    prior = {'state': 'unknown', 'passed': None, 'problems': ['frozen unsupported metadata']}
    bound = {'state': 'verified_owned_overlap_bound', 'passed': True, 'cumulative_exact_ns': None, 'cumulative_tool_seconds': None, 'cumulative_upper_bound_ns': 1772_694_115_012}
    monkeypatch.setattr(v4._v3, 'account_trial_tool_time_v3', lambda *a, **k: deepcopy(prior))
    monkeypatch.setattr(v4, '_clock_bound_v4', lambda *a, **k: deepcopy(bound))
    entry = {'status': 'scored', 'reward': reward, 'failure_kind': None, 'result_file': str(tmp_path / 'result.json')}
    result = v4.apply_tool_time_policy(entry, {'tool_time_policy': deepcopy(v4.POLICY_V4)})
    assert result['reward'] == result['raw_verifier_reward'] == reward and result['status'] == 'scored'
    assert result['tool_time']['base_policy_v3_receipt'] == prior
    assert result['tool_time']['cumulative_exact_ns'] is result['tool_time']['cumulative_tool_seconds'] is None


def test_unknown_v4_measurement_remains_unscored_and_not_retryable(monkeypatch, tmp_path):
    monkeypatch.setattr(v4._v3, 'account_trial_tool_time_v3', lambda *a, **k: {'state': 'unknown', 'passed': None})
    monkeypatch.setattr(v4, '_clock_bound_v4', lambda *a, **k: {'state': 'unknown', 'passed': None, 'problems': ['missing tail']})
    result = v4.apply_tool_time_policy({'status': 'scored', 'reward': 0, 'failure_kind': None, 'result_file': str(tmp_path / 'result.json')}, {'tool_time_policy': deepcopy(v4.POLICY_V4)})
    assert result['reward'] is None and result['raw_verifier_reward'] == 0 and result['status'] == 'evidence_incomplete'
    with pytest.raises(v4.FrontierError, match='never be retried'): v4.assess_infrastructure_retry(result)


def test_known_exact_budget_failure_cannot_be_replaced_by_overlap_credit(monkeypatch, tmp_path):
    exact = {'state': 'verified', 'passed': False, 'cumulative_tool_seconds': 1800}
    monkeypatch.setattr(v4._v3, 'account_trial_tool_time_v3', lambda *a, **k: deepcopy(exact))
    monkeypatch.setattr(v4, '_clock_bound_v4', lambda *a, **k: pytest.fail('Known exact evidence must not use overlap fallback'))
    result = v4.apply_tool_time_policy({'status': 'scored', 'reward': 1, 'failure_kind': None, 'result_file': str(tmp_path / 'result.json')}, {'tool_time_policy': deepcopy(v4.POLICY_V4)})
    assert result['reward'] == 0 and result['raw_verifier_reward'] == 1
    assert result['failure_kind'] == 'cumulative_tool_budget_exhausted'
    assert result['tool_time']['base_policy_v3_receipt'] == exact


def test_confirmation_still_requires_ten_per_mode(exported, tmp_path):
    with pytest.raises(native4.FrontierError, match='at least ten'):
        native4.freeze_selection(exported, tmp_path / 'confirmation', phase='confirmation')


def test_new_bound_summary_keeps_exact_seconds_unknown():
    selected = {'tasks': [{'task_id': 'one', 'mode': 'financial_modeling'}], 'phase': 'development'}
    attempts = [{'status': 'scored', 'reward': 1, 'mode': 'financial_modeling',
        'tool_time': {'state': 'verified_owned_overlap_bound', 'passed': True, 'cumulative_tool_seconds': None}}]
    score, passed = v4.summarize(selected, attempts)
    assert score['scored_tasks'] == 1 and score['overall_pass_at_1'] == 1 and passed is False
    assert score['cumulative_tool_seconds'] is None and score['timed_attempts'] == 0


def test_earlier_namespaces_global_policies_and_unrelated_ast_functions_unchanged():
    assert v3.POLICY_V3['version'] == 3 and native3.POLICY_V3['version'] == 3
    before, after = v3.adapted_ast(), v4.adapted_ast()
    for name in ('classify_result', 'review_agent_timeout', 'summarize', 'assess_infrastructure_retry', 'collect_attempts', 'run_evaluation', 'resume_infrastructure'):
        left = next(n for n in before.body if getattr(n, 'name', None) == name)
        right = next(n for n in after.body if getattr(n, 'name', None) == name)
        assert ast.dump(left) == ast.dump(right), name


def test_pinned_upstream_drift_fails_closed_before_v4_execution(monkeypatch):
    monkeypatch.setattr(clock, 'BASE_SHA256', '0' * 64)
    with pytest.raises(ValueError, match='parser changed'): clock.static_calls('text(await tools.exec_command({cmd:"x"}));')
    monkeypatch.setattr(v4, 'V3_RUNNER_SHA256', '0' * 64)
    with pytest.raises(ValueError, match='runner changed'): v4.adapted_ast()
    monkeypatch.setattr(native4, '_NATIVE_V3_SHA256', '0' * 64)
    with pytest.raises(ValueError, match='transport adapter changed'): native4.adapted_ast()
