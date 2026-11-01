from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


m = load('ring_primary_finalizer_v3', 'scripts/finalize_ringfenced_business_revision3.py')
legacy_tests = load('ring_primary_legacy_fixtures', 'tests/test_publish_ringfenced_business_revision.py')
legacy_tests.m = m.base
review_tests = load('ring_primary_review_fixtures', 'tests/test_finalize_ringfenced_business_revision2.py')
review_tests.m = m.previous


@pytest.mark.parametrize('raw', [0, 1])
def test_complete_primary_score_needs_no_failure_analysis_or_extra_recalculation(raw):
    row = legacy_tests.row(raw); before = deepcopy(row)
    assert m.primary_score(row) == (raw, 'complete_primary_success' if raw else 'primary_exact_contract_mismatch')
    assert row == before
    # Even a supplied unrelated optional object is never read by this score seam.
    assert m.primary_score(row, {'path': '/not/an/artifact'})[0] == raw


@pytest.mark.parametrize('raw', [0, 1])
def test_strict_verified_budget_failure_retains_zero_and_original_raw_reward(raw):
    row = legacy_tests.row(raw, budget=True); before = deepcopy(row)
    assert m.primary_score(row) == (0, 'verified_tool_budget_failure')
    assert row == before


@pytest.mark.parametrize('mutation', ['clock', 'resources', 'infra', 'raw', 'effective', 'strict_boundary', 'parallel'])
def test_unknown_or_changed_native_contract_still_holds(mutation):
    row = legacy_tests.row()
    if mutation == 'clock': row['actual_attempt']['tool_time']['passed'] = None
    if mutation == 'resources': row['resources']['complete'] = False
    if mutation == 'infra': row['actual_attempt']['failure_kind'] = 'infrastructure'
    if mutation == 'raw': row['actual_attempt']['raw_verifier_reward'] = None
    if mutation == 'effective': row['score']['effective_reward'] = 1
    if mutation == 'strict_boundary': row['actual_attempt']['tool_time']['cumulative_tool_seconds'] = 1800
    if mutation == 'parallel': row['actual_attempt']['tool_time']['parallel_executions'] = 'max'
    with pytest.raises(ValueError): m.primary_score(row)


def rows(successes=0):
    result = legacy_tests.twenty_rows(successes, 10)
    for row in result:
        row.pop('conservative_reward')
    return result


def test_only_primary_whole_twenty_threshold_blocks_release_and_new_wave_is_separate():
    result = m.gate_rows(rows(4))
    assert result['passed'] and result['primary_overall_pass_at_1'] == .2
    assert result['primary_by_mode']['financial_modeling']['primary_pass_at_1'] == .2
    assert result['primary_by_mode']['debugging']['primary_pass_at_1'] == .2
    assert result['new_wave_primary_pass_at_1'] == .4
    assert not result['new_wave_own_point_two_gate_passed'] and result['new_wave_gate_is_informational']
    assert not m.gate_rows(rows(5))['passed']
    assert all('conservative' not in key for key in result)
    assert result['twenty_fresh_attempts_claimed'] is False


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'wrong_mode', 'scope', 'scope_mode', 'unknown_reward', 'boolean'])
def test_no_selection_or_scope_change_can_manufacture_a_primary_pass(mutation):
    values = rows()
    if mutation == 'missing': values.pop()
    if mutation == 'duplicate': values[-1]['task_id'] = values[0]['task_id']
    if mutation == 'wrong_mode': values[0]['mode'] = 'debugging'
    if mutation == 'scope': values[0]['scope'] = 'new_confirmation'
    if mutation == 'scope_mode': values[0]['scope'], values[11]['scope'] = values[11]['scope'], values[0]['scope']
    if mutation == 'unknown_reward': values[0]['primary_reward'] = None
    if mutation == 'boolean': values[0]['primary_reward'] = False
    with pytest.raises(ValueError): m.gate_rows(values)


def final_fixture(tmp_path, monkeypatch, successes=0):
    b = m.base
    root, prepared, packet, _ = legacy_tests.fixture(tmp_path, monkeypatch)
    history = b.read(packet['retained_results']); old_results = []
    for i, task in enumerate(history['tasks']):
        actual = b.write(root / f'old_result{i}.json', {'trial': i})
        diagnostic = b.write(root / f'old_diag{i}.json', {'wrong': 800})
        task['original_release_result'].update(task_id=task['task_id'], mode=task['mode'], variant_id=task['variant_id'],
            reward=0, raw_verifier_reward=0, state='complete', result_sha256=actual['sha256'])
        task['original_failure_analysis'] = {'boundary_only': False, 'resources_passed': True, 'tool_time_passed': True,
            'actual_result': actual, 'diagnostics': diagnostic}
        old_results.append(task['original_release_result'])
    history['previous_release'] = b.write(root / 'previous_release.json', {'tasks': old_results})
    packet['retained_results'] = b.write(root / 'retained.json', history)
    packet['materials'] = {t['task_id']: {'sha256': str(i) * 64} for i, t in enumerate(packet['tasks'])}
    prepared = b.write(root / 'outputs/final_confirmation/prepared.json', packet)
    staged = b.stage(prepared, root / 'outputs/release', root=root)
    installed = b.install(staged, root=root)
    selection = b.write(root / 'selection.json', {'model': 'gpt-6.1-sol', 'reasoning_effort': 'xhigh',
        'phase': 'confirmation', 'n_attempts': 1, 'tool_time_policy_version': 6})
    evaluation = b.write(root / 'evaluation.json', {'model': 'gpt-6.1-sol', 'reasoning_effort': 'xhigh'})
    resource = b.write(root / 'resources.json', {'passed': True, 'complete': True})
    attempts = []
    for i, task in enumerate(packet['tasks']):
        actual = b.write(root / f'new_result{i}.json', {'trial': i})
        row = legacy_tests.row(int(i < successes))
        row.update(task_id=task['task_id'], material_identity=packet['materials'][task['task_id']])
        row['actual_attempt'].update(harbor_export_binding=task['harbor_export_binding'],
            task_checksum=b.dirhash(root / 'SpreadsheetEval' / task['task_id'], 'sha256'),
            result_file=actual['path'], result_sha256=actual['sha256'],
            agent_result={'n_input_tokens': 100, 'n_output_tokens': 10, 'n_cache_tokens': 80})
        attempts.append(row)
    terminal_value = {'kind': 'test_confirmation', 'phase': 'confirmation', 'outer_retries': 0, 'prepared': prepared,
        'selection': selection, 'evaluation': evaluation, 'resources': resource, 'results': attempts}
    terminal = b.write(root / 'confirmation.json', terminal_value)
    monkeypatch.setattr(b, 'entry', lambda: SimpleNamespace(TERMINAL_KIND='test_confirmation'))
    monkeypatch.setattr(b.observer, 'validate_observation_receipt', lambda *a: b.read(resource))
    calls = []
    def quality(*args):
        calls.append('quality')
        return {'usage': {'input_tokens': 400, 'output_tokens': 40, 'total_tokens': 440,
            'cached_input_tokens': 300, 'llm_calls': 4, 'unknown_usage_calls': 0}}
    monkeypatch.setattr(m.previous, 'quality_validator', lambda profile: quality)
    monkeypatch.setattr(b, 'engineering', lambda *a: calls.append('engineering') or [{'task_id': t['task_id']} for t in packet['tasks']])
    monkeypatch.setattr(b, 'validate_controls', lambda *a: calls.append('controls') or {'passed': True})
    baseline_calls = [{'actual_result': b.write(root / f'prototype{i}.json', {'prototype': i}), 'total_tokens': 10} for i in range(14)]
    baseline = b.write(root / 'baseline.json', {'kind': 'actual_business_revision_prototype_usage_baseline', 'call_count': 14,
        'calls': baseline_calls, 'total_tokens': 140, 'input_tokens': 126, 'output_tokens': 14, 'unknown_usage_calls': 0})
    monkeypatch.setattr(b, 'BASELINE', Path(baseline['path'])); monkeypatch.setattr(b, 'BASELINE_SHA', baseline['sha256'])
    contract, _ = review_tests.make_contract(root)
    return {'installed': installed, 'confirmation': terminal, 'review': b.write(root / 'review.json', {'review': True}),
        'actual_controls': b.write(root / 'controls.json', {'controls': True}), 'output': root / 'qualified.json',
        'review_contract': contract}, root, terminal_value, calls


def test_full_frozen_finalizer_flow_accepts_unanalysed_exact_zeros_without_mutating_bytes(tmp_path, monkeypatch):
    args, root, terminal, calls = final_fixture(tmp_path, monkeypatch, successes=4)
    before = {name: m.ref(root / name) for name in ('SpreadsheetEval/dataset_manifest.json', 'confirmation.json')}
    source_files = (m.ref(m.previous.BASE), m.ref(m.PREVIOUS))
    result = m.read(m.finalize(**args))
    assert result['qualified'] and result['version'] == 3 and len(result['tasks']) == 20
    assert result['gate'] == m.GATE and result['gate_result']['primary_overall_pass_at_1'] == .2
    assert result['gate_result']['new_wave_primary_pass_at_1'] == .4
    assert not result['gate_result']['new_wave_own_point_two_gate_passed']
    assert sorted(calls) == ['controls', 'engineering', 'quality']
    assert all(not key.startswith('conservative_') for task in result['tasks'] for key in task)
    assert not any('conservative' in key for key in result['gate_result'])
    zeros = [t for t in result['tasks'] if t['scope'] == 'new_confirmation' and t['primary_reward'] == 0]
    assert len(zeros) == 6 and all(t['primary_score_reason'] == 'primary_exact_contract_mismatch'
        and t['failure_cause_status'] == 'cause_not_required' for t in zeros)
    assert result['consumption']['unknown_usage_calls'] == 4 and result['consumption']['model_calls'] == 32
    assert result['consumption']['known_reported_total_tokens'] == 1680
    assert result['finalizer_revision3']['original_protocol_and_results_preserved']
    assert result['twenty_fresh_attempts_claimed'] is False
    assert all(m.ref(root / name) == value for name, value in before.items())
    assert source_files == (m.ref(m.previous.BASE), m.ref(m.PREVIOUS))
    assert m.base.GATE['combined_conservative_nonboundary_pass_at_1_max'] == '0.2'
    assert m.read(m.read(args['installed'])['staged'])['gate'] == m.base.GATE


def test_primary_five_successes_rejects_the_whole_cohort_without_writing_release(tmp_path, monkeypatch):
    args, _, _, _ = final_fixture(tmp_path, monkeypatch, successes=5)
    with pytest.raises(ValueError, match='combined primary pass rate exceeds'): m.finalize(**args)
    assert not args['output'].exists()


@pytest.mark.parametrize('failure', ['quality', 'engineering', 'controls', 'unknown', 'changed_material'])
def test_primary_policy_does_not_bypass_quality_native_controls_resources_or_material_binding(tmp_path, monkeypatch, failure):
    args, root, terminal, _ = final_fixture(tmp_path, monkeypatch)
    def fail(*a): raise ValueError('HOLD: ' + failure)
    if failure == 'quality': monkeypatch.setattr(m.previous, 'quality_validator', lambda profile: fail)
    if failure == 'engineering': monkeypatch.setattr(m.base, 'engineering', fail)
    if failure == 'controls': monkeypatch.setattr(m.base, 'validate_controls', fail)
    if failure in ('unknown', 'changed_material'):
        if failure == 'unknown': terminal['results'][0]['actual_attempt']['tool_time']['passed'] = None
        else: terminal['results'][0]['material_identity'] = {'sha256': 'changed'}
        args['confirmation'] = m.base.write(root / 'changed_confirmation.json', terminal)
    with pytest.raises(ValueError): m.finalize(**args)
    assert not args['output'].exists()
