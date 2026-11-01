from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


m = load('ring_budget_upper_bound_v4', 'scripts/finalize_ringfenced_business_revision4.py')
fixtures = load('ring_budget_v4_legacy_fixtures', 'tests/test_finalize_ringfenced_business_revision3.py')
fixtures.m = m.previous
fixtures.legacy_tests.m = m.base
fixtures.review_tests.m = m.review_join


def actual_row(tmp_path, raw=0, unknown=True, budget=False, name='native'):
    row = fixtures.legacy_tests.row(raw, budget)
    row['task_id'] = name
    actual = m.base.write(tmp_path / (name + '.json'), {'task_checksum': 'same-checksum',
        'exception_info': None, 'finished_at': '2026-11-01T09:00:00Z', 'verifier_result': {'rewards': {'reward': float(raw)}}})
    row['actual_attempt'].update(result_file=actual['path'], result_sha256=actual['sha256'], task_checksum='same-checksum')
    if unknown:
        row['actual_attempt'].update(status='evidence_incomplete', failure_kind='native_tool_timing_incomplete', reward=None)
        row['actual_attempt']['tool_time'].update(passed=None, complete=False, state='unknown', cumulative_tool_seconds=None)
        row['score'].update(raw_verifier_reward=raw, effective_reward=None, state='unknown', infrastructure_unknown_is_not_model_zero=True)
    return row


@pytest.mark.parametrize('raw,interval', [(0, [0, 0]), (1, [0, 1])])
def test_unknown_timing_preserves_original_unknown_and_uses_model_favorable_interval(tmp_path, raw, interval):
    row = actual_row(tmp_path, raw); before = deepcopy(row)
    projection = m.project_attempt(row)
    assert projection['budget_adjusted_reward_interval'] == interval
    assert projection['original_native_score'] == before['score']
    assert projection['original_native_score']['effective_reward'] is None
    assert projection['tool_clock_evidence_state'] == 'unknown' and row == before


@pytest.mark.parametrize('raw,budget,interval', [(0, False, [0, 0]), (1, False, [1, 1]), (1, True, [0, 0])])
def test_verified_native_budget_still_supplies_exact_interval(tmp_path, raw, budget, interval):
    assert m.project_attempt(actual_row(tmp_path, raw, unknown=False, budget=budget))['budget_adjusted_reward_interval'] == interval


@pytest.mark.parametrize('mutation', ['exception', 'missing_verifier', 'raw_mismatch', 'unfinished', 'checksum',
    'resources', 'infra', 'score_rewritten', 'clock_policy', 'missing_raw'])
def test_upper_bound_cannot_convert_infrastructure_or_incomplete_verifier_to_zero(tmp_path, mutation):
    row = actual_row(tmp_path)
    if mutation in ('exception', 'missing_verifier', 'raw_mismatch', 'unfinished', 'checksum'):
        result = m.read(row['actual_attempt']['result_file'])
        if mutation == 'exception': result['exception_info'] = {'type': 'infra'}
        if mutation == 'missing_verifier': result['verifier_result'] = None
        if mutation == 'raw_mismatch': result['verifier_result']['rewards']['reward'] = 1
        if mutation == 'unfinished': result['finished_at'] = None
        if mutation == 'checksum': result['task_checksum'] = 'different'
        changed = m.base.write(tmp_path / 'changed.json', result)
        row['actual_attempt'].update(result_file=changed['path'], result_sha256=changed['sha256'])
    if mutation == 'resources': row['resources']['complete'] = False
    if mutation == 'infra': row['actual_attempt']['failure_kind'] = 'infrastructure'
    if mutation == 'score_rewritten': row['score']['effective_reward'] = 0
    if mutation == 'clock_policy': row['actual_attempt']['tool_time']['parallel_executions'] = 'max'
    if mutation == 'missing_raw': row['actual_attempt']['raw_verifier_reward'] = None
    with pytest.raises(ValueError, match='HOLD'): m.project_attempt(row)


def twenty(successes=1):
    result = fixtures.rows(successes)
    for row in result:
        row['raw_primary_reward'] = row.pop('primary_reward')
        row['budget_adjusted_reward_interval'] = [0, row['raw_primary_reward']]
    return result


def test_whole_twenty_raw_one_of_twenty_has_budget_adjusted_upper_bound_point_zero_five():
    result = m.gate_rows(twenty())
    assert result['raw_overall_pass_at_1'] == .05
    assert result['budget_adjusted_overall_pass_at_1_interval'] == [0, .05]
    assert result['passed'] and result['new_confirmation']['raw_pass_at_1'] == .1
    assert result['new_confirmation']['budget_adjusted_pass_at_1_interval'] == [0, .1]
    assert m.gate_rows(twenty(4))['passed'] and not m.gate_rows(twenty(5))['passed']
    assert not m.gate_rows(twenty(4))['new_wave_own_point_two_upper_bound_gate_passed']


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'wrong_mode', 'scope', 'raw_zero_upper_one', 'negative', 'reversed'])
def test_no_selection_or_invalid_interval_can_reduce_the_release_upper_bound(mutation):
    rows = twenty()
    if mutation == 'missing': rows.pop()
    if mutation == 'duplicate': rows[1]['task_id'] = rows[0]['task_id']
    if mutation == 'wrong_mode': rows[0]['mode'] = 'debugging'
    if mutation == 'scope': rows[0]['scope'] = 'new_confirmation'
    if mutation == 'raw_zero_upper_one': rows[0]['budget_adjusted_reward_interval'] = [0, 1]
    if mutation == 'negative': rows[0]['budget_adjusted_reward_interval'] = [-1, 0]
    if mutation == 'reversed': rows[10]['budget_adjusted_reward_interval'] = [1, 0]
    with pytest.raises(ValueError): m.gate_rows(rows)


def integration_fixture(tmp_path, monkeypatch, successes=1):
    args, root, terminal, calls = fixtures.final_fixture(tmp_path, monkeypatch, successes=successes)
    for i, row in enumerate(terminal['results']):
        attempt = row['actual_attempt']; raw = attempt['raw_verifier_reward']
        actual = m.base.write(root / f'complete_native_result{i}.json', {'task_checksum': attempt['task_checksum'],
            'exception_info': None, 'finished_at': '2026-11-01T09:00:00Z', 'verifier_result': {'rewards': {'reward': raw}}})
        attempt.update(result_file=actual['path'], result_sha256=actual['sha256'])
        if i < 8:
            attempt.update(status='evidence_incomplete', failure_kind='native_tool_timing_incomplete', reward=None)
            attempt['tool_time'].update(passed=None, complete=False, state='unknown', cumulative_tool_seconds=None)
            row['score'].update(raw_verifier_reward=raw, effective_reward=None, state='unknown', infrastructure_unknown_is_not_model_zero=True)
    args['confirmation'] = m.base.write(root / 'complete_confirmation.json', terminal)
    return args, root, terminal, calls


def test_full_frozen_flow_preserves_eight_unknowns_while_certifying_a_safe_upper_bound(tmp_path, monkeypatch):
    args, root, terminal, calls = integration_fixture(tmp_path, monkeypatch)
    before = m.ref(root / 'SpreadsheetEval/dataset_manifest.json'); original = deepcopy(terminal)
    record = m.read(m.finalize(**args))
    assert record['qualified'] and record['version'] == 4
    assert record['gate_result']['raw_overall_pass_at_1'] == .05
    assert record['gate_result']['budget_adjusted_overall_pass_at_1_interval'] == [0, .05]
    assert record['tool_time_evidence']['complete_tool_clocks'] == 2
    assert record['tool_time_evidence']['unknown_tool_clocks'] == 8
    assert not record['tool_time_evidence']['all_tool_clocks_complete']
    assert not record['tool_time_evidence']['unknown_timing_used_as_model_failure']
    new = [t for t in record['tasks'] if t['scope'] == 'new_confirmation']
    unknown = [t for t in new if t['original_native_score']['state'] == 'unknown']
    assert len(unknown) == 8 and all(t['original_native_score']['effective_reward'] is None for t in unknown)
    assert all('primary_reward' not in t and 'score_state' not in t for t in record['tasks'])
    assert all(not k.startswith('conservative_') for t in record['tasks'] for k in t)
    assert sorted(calls) == ['controls', 'engineering', 'quality']
    assert record['consumption']['unknown_usage_calls'] == 4
    assert m.ref(root / 'SpreadsheetEval/dataset_manifest.json') == before
    assert m.read(args['confirmation']) == original


def test_raw_upper_bound_above_threshold_keeps_the_whole_failed_cohort(tmp_path, monkeypatch):
    args, _, _, _ = integration_fixture(tmp_path, monkeypatch, successes=5)
    with pytest.raises(ValueError, match='upper bound exceeds'): m.finalize(**args)
    assert not args['output'].exists()


@pytest.mark.parametrize('failure', ['quality', 'engineering', 'controls'])
def test_upper_bound_does_not_bypass_other_hard_gates(tmp_path, monkeypatch, failure):
    args, _, _, _ = integration_fixture(tmp_path, monkeypatch)
    def reject(*a): raise ValueError('HOLD: ' + failure)
    if failure == 'quality': monkeypatch.setattr(m.review_join, 'quality_validator', lambda profile: reject)
    if failure == 'engineering': monkeypatch.setattr(m.base, 'engineering', reject)
    if failure == 'controls': monkeypatch.setattr(m.base, 'validate_controls', reject)
    with pytest.raises(ValueError): m.finalize(**args)
    assert not args['output'].exists()
