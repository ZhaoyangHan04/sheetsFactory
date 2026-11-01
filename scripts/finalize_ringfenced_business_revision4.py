#!/usr/bin/env python3
"""Certify a fixed cohort using complete raw results and a budget-adjusted upper bound."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
from types import FunctionType

PREVIOUS = Path(__file__).resolve().with_name('finalize_ringfenced_business_revision3.py')
PREVIOUS_SHA = '8847951b0a72e7a80bef99e3aee786b90b919c103882bd595d052c6bd8809966'
if hashlib.sha256(PREVIOUS.read_bytes()).hexdigest() != PREVIOUS_SHA:
    raise ValueError('The frozen primary finalizer changed')
loader = importlib.util.spec_from_file_location('_ring_revision4_frozen_primary_join', PREVIOUS)
previous = importlib.util.module_from_spec(loader); loader.loader.exec_module(previous)
review_join = previous.previous
base = previous.base
ref, read, require = base.ref, base.read, base.require

GATE = {
    'kind': 'raw_answer_budget_upper_bound_release_gate_v4', 'version': 4,
    'fixed_new_pairs': ['R2-01', 'R2-02', 'R2-03', 'R2-04', 'R2-05'],
    'fixed_retained_count': 10, 'new_confirmation_count': 10, 'combined_count': 20,
    'combined_budget_adjusted_pass_at_1_upper_bound_max': '0.2',
    'answer_contract': 'complete typed two-decimal values and full change set',
    'effective_success_definition': 'raw_verifier_reward * indicator(cumulative_tool_seconds < 1800)',
    'raw_zero_budget_adjusted_interval': [0, 0], 'raw_one_unknown_budget_adjusted_interval': [0, 1],
    'strict_tool_seconds': 1800, 'tool_clock_excludes_model_response': True,
    'tool_parallel_time_is_sum': True, 'unknown_tool_time_is_not_failure_evidence': True,
    'complete_tool_clock_for_every_attempt_claimed': False,
    'incomplete_verifier_or_resources': 'HOLD', 'failure_cause_analysis_required': False,
    'historical_results_retested_or_rescored': False, 'twenty_fresh_attempts_claimed': False,
    'selection_after_confirmation': False, 'new_wave_gate_is_informational': True,
}


def project_attempt(row):
    """Bind a completed actual verifier and preserve the original native score."""
    attempt = row['actual_attempt']; clock = attempt.get('tool_time') or {}
    raw = attempt.get('raw_verifier_reward')
    require(row['resources'].get('passed') is row['resources'].get('complete') is True,
        'HOLD: actual resources are incomplete')
    require(type(raw) in (int, float) and raw in (0, 1), 'HOLD: a complete binary raw verifier result is required')
    result_ref = ref(attempt['result_file']); result = read(result_ref)
    actual_raw = ((result.get('verifier_result') or {}).get('rewards') or {}).get('reward')
    require(result_ref['sha256'] == attempt['result_sha256'] and result.get('exception_info') is None
        and result.get('finished_at') and result.get('task_checksum') == attempt['task_checksum']
        and type(actual_raw) in (int, float) and actual_raw == raw,
        'HOLD: the actual verifier is incomplete, exceptional or differs from the bound result')
    require(clock.get('budget_seconds') == 1800 and clock.get('strict_less_than') is True
        and clock.get('model_response_time_included') is False and clock.get('parallel_executions') == 'sum',
        'HOLD: the original clock uses a different tool-budget contract')
    if clock.get('passed') is None:
        require(attempt.get('status') == 'evidence_incomplete'
            and attempt.get('failure_kind') == 'native_tool_timing_incomplete'
            and row['score'].get('state') == 'unknown' and row['score'].get('effective_reward') is None
            and row['score'].get('raw_verifier_reward') == raw,
            'HOLD: only unresolved tool timing may use a raw-result upper bound')
        interval, clock_state = [0, raw], 'unknown'
    else:
        effective, state, original_raw = base.effective(row)
        require(original_raw == raw, 'The actual raw score changed')
        interval, clock_state = [effective, effective], state
    return {'raw_primary_reward': raw, 'budget_adjusted_reward_interval': interval,
        'tool_clock_evidence_state': clock_state, 'original_native_score': deepcopy(row['score']),
        'original_native_attempt_status': attempt['status'],
        'original_native_failure_kind': attempt.get('failure_kind'), 'actual_result': result_ref,
        'raw_zero_is_wrong_answer_independent_of_tool_time': raw == 0}


def decorate(rows, projections):
    result = deepcopy(rows)
    for task in result:
        for key in list(task):
            if key.startswith('conservative_') or key in ('primary_reward', 'score_state'):
                del task[key]
        if task['scope'] == 'new_confirmation':
            task.update(deepcopy(projections[task['task_id']]))
        else:
            original = task['original_release_result']
            task.update(raw_primary_reward=original['raw_verifier_reward'], budget_adjusted_reward_interval=[0, 0],
                tool_clock_evidence_state='retained_original_complete', original_native_score=deepcopy(original))
        task['primary_score_reason'] = 'primary_exact_contract_mismatch' if task['raw_primary_reward'] == 0 else 'complete_raw_primary_success'
        task['failure_cause_status'] = 'cause_not_required' if task['raw_primary_reward'] == 0 else 'not_applicable'
    return result


def gate_rows(rows):
    require(len(rows) == 20 and len({r['task_id'] for r in rows}) == 20
        and dict(Counter(r['mode'] for r in rows)) == base.MODES,
        'The release upper bound must use the unchanged whole twenty')
    require(Counter(r['scope'] for r in rows) == Counter({'retained_historical': 10, 'new_confirmation': 10}),
        'The fixed historical and new observation scopes changed')
    for row in rows:
        raw = row['raw_primary_reward']; interval = row['budget_adjusted_reward_interval']
        require(type(raw) in (int, float) and raw in (0, 1) and len(interval) == 2
            and all(type(v) in (int, float) and v in (0, 1) for v in interval)
            and 0 <= interval[0] <= interval[1] <= raw,
            'A budget-adjusted interval cannot exceed its complete binary raw result')
    def summary(items):
        count = len(items); raw = sum(r['raw_primary_reward'] for r in items)
        low = sum(r['budget_adjusted_reward_interval'][0] for r in items)
        high = sum(r['budget_adjusted_reward_interval'][1] for r in items)
        return {'task_count': count, 'raw_successes': raw, 'raw_pass_at_1': raw / count,
            'budget_adjusted_successes_interval': [low, high],
            'budget_adjusted_pass_at_1_interval': [low / count, high / count]}
    new = [r for r in rows if r['scope'] == 'new_confirmation']
    historical = [r for r in rows if r['scope'] == 'retained_historical']
    require(all(Counter(r['mode'] for r in items) == Counter({mode: 5 for mode in base.MODES})
        for items in (new, historical)), 'Retain five tasks per mode in each observation scope')
    whole = summary(rows); upper = whole['budget_adjusted_pass_at_1_interval'][1]
    return {'raw_successes': whole['raw_successes'], 'raw_overall_pass_at_1': whole['raw_pass_at_1'],
        'budget_adjusted_successes_interval': whole['budget_adjusted_successes_interval'],
        'budget_adjusted_overall_pass_at_1_interval': whole['budget_adjusted_pass_at_1_interval'],
        'budget_adjusted_overall_pass_at_1_upper_bound': upper,
        'passed': whole['budget_adjusted_successes_interval'][1] <= 4,
        'by_mode': {mode: summary([r for r in rows if r['mode'] == mode]) for mode in base.MODES},
        'historical_retained': summary(historical), 'new_confirmation': summary(new),
        'new_confirmation_by_mode': {mode: summary([r for r in new if r['mode'] == mode]) for mode in base.MODES},
        'new_wave_own_point_two_upper_bound_gate_passed': summary(new)['budget_adjusted_successes_interval'][1] <= 2,
        'new_wave_gate_is_informational': True, 'twenty_fresh_attempts_claimed': False}


def finalize(installed, confirmation, review, actual_controls, output, *, review_contract, development=()):
    binding, profile = review_join.contract(review_contract)
    frozen = [ref(PREVIOUS), ref(previous.PREVIOUS), ref(review_join.BASE), ref(__file__)]
    namespace = dict(vars(base)); projections = {}
    def raw_effective(row):
        projection = project_attempt(row); projections[row['task_id']] = projection
        raw = projection['raw_primary_reward']
        return raw, 'complete_raw_verifier_budget_reported_separately', raw
    def raw_score(row, unused_analysis=None):
        raw, _, _ = raw_effective(row)
        return raw, 'complete_raw_verifier'
    namespace.update(effective=raw_effective, conservative=raw_score,
        validate_quality=review_join.quality_validator(profile),
        gate_rows=lambda rows: gate_rows(decorate(rows, projections)))
    old_message = 'The fixed combined primary or conservative pass rate exceeds 0.2; keep the whole failed cohort'
    def release_require(value, message):
        base.require(value, 'The fixed combined budget-adjusted pass-rate upper bound exceeds 0.2; retain the whole cohort'
            if message == old_message else message)
    namespace['require'] = release_require
    def final_write(path, value):
        require(value['kind'] == 'qualified_ringfenced_business_revision_release', 'Write only the final release receipt')
        require([ref(PREVIOUS), ref(previous.PREVIOUS), ref(review_join.BASE), ref(__file__)] == frozen,
            'A frozen finalizer changed during evidence consumption')
        review_join.contract(binding)
        result = review_join.augment(value, binding, profile)
        result['version'] = 4; result['tasks'] = decorate(result['tasks'], projections)
        require(result['gate_result'] == gate_rows(result['tasks']), 'The whole-set upper bound changed')
        result['gate'] = deepcopy(GATE)
        known = sum(p['tool_clock_evidence_state'] != 'unknown' for p in projections.values())
        result['tool_time_evidence'] = {'new_confirmation_attempts': 10, 'complete_tool_clocks': known,
            'unknown_tool_clocks': 10 - known, 'all_tool_clocks_complete': known == 10,
            'unknown_original_native_scores_preserved': True,
            'difficulty_uses_model_favorable_budget_adjusted_upper_bound': True,
            'unknown_timing_used_as_model_failure': False}
        result['finalizer_revision4'] = {'implementation': ref(__file__), 'frozen_primary_finalizer': ref(PREVIOUS),
            'frozen_bounded_review_finalizer': ref(previous.PREVIOUS), 'frozen_staged_publisher': ref(review_join.BASE),
            'bounded_review_contract': binding, 'original_protocol_and_results_preserved': True,
            'staged_recipe_and_dataset_manifest_unchanged': True,
            'mathematical_bound': 'E=raw*I(SUM<1800); 0<=E<=raw',
            'complete_budget_adjusted_point_scores_claimed': known == 10,
            'failure_cause_analysis_required': False, 'auxiliary_pass_rate_measured_or_claimed': False}
        return base.write(path, result)
    namespace['write'] = final_write
    original = base.finalize
    adapted = FunctionType(original.__code__, namespace, original.__name__, original.__defaults__, original.__closure__)
    adapted.__kwdefaults__ = original.__kwdefaults__
    return adapted(installed, confirmation, review, actual_controls, output, analyses=(), development=development)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('installed', 'confirmation', 'review', 'actual-controls', 'output', 'review-contract'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--development', action='append', type=Path, default=[])
    args = parser.parse_args()
    print(base.json.dumps(finalize(args.installed, args.confirmation, args.review, args.actual_controls,
        args.output, review_contract=args.review_contract, development=args.development)))


if __name__ == '__main__':
    main()
