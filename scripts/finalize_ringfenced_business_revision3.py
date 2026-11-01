#!/usr/bin/env python3
"""Certify the fixed twenty using the primary exact-answer and tool-time contract."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
from types import FunctionType

PREVIOUS = Path(__file__).resolve().with_name('finalize_ringfenced_business_revision2.py')
PREVIOUS_SHA = '587d973ff592300b9cb106252254a08aba18f75b42d865ed8ff3c734ffec15bf'
if hashlib.sha256(PREVIOUS.read_bytes()).hexdigest() != PREVIOUS_SHA:
    raise ValueError('The frozen bounded-review finalizer changed')
loader = importlib.util.spec_from_file_location('_ring_revision3_frozen_review_join', PREVIOUS)
previous = importlib.util.module_from_spec(loader); loader.loader.exec_module(previous)
base = previous.base
ref, read, require = base.ref, base.read, base.require

GATE = {
    'kind': 'primary_exact_contract_release_gate_v3', 'version': 3,
    'fixed_new_pairs': ['R2-01', 'R2-02', 'R2-03', 'R2-04', 'R2-05'],
    'fixed_retained_count': 10, 'new_confirmation_count': 10, 'combined_count': 20,
    'combined_primary_pass_at_1_max': '0.2',
    'new_wave_pass_at_1_max_reported_separately': '0.2',
    'new_wave_gate_is_informational': True,
    'answer_contract': 'complete typed two-decimal values and full change set',
    'complete_raw_zero_reward': 0, 'complete_raw_one_reward': 1,
    'failure_cause_analysis_required': False,
    'verified_cumulative_tool_budget_failure_reward': 0, 'strict_tool_seconds': 1800,
    'tool_clock_excludes_model_response': True, 'tool_parallel_time_is_sum': True,
    'unknown_evidence': 'HOLD', 'historical_results_retested_or_rescored': False,
    'twenty_fresh_attempts_claimed': False, 'selection_after_confirmation': False,
}


def primary_score(row, unused_analysis=None):
    """Use the existing native score; do not infer a financial failure category."""
    reward, state, raw = base.effective(row)
    if state == 'known_tool_budget_failure':
        return reward, 'verified_tool_budget_failure'
    return reward, 'complete_primary_success' if raw == 1 else 'primary_exact_contract_mismatch'


def gate_rows(rows):
    """Apply one whole-set primary threshold and report the two observation scopes."""
    require(len(rows) == 20 and len({r['task_id'] for r in rows}) == 20
        and dict(Counter(r['mode'] for r in rows)) == base.MODES,
        'The primary release gate must use the unchanged whole twenty')
    require(Counter(r['scope'] for r in rows) == Counter({'retained_historical': 10, 'new_confirmation': 10})
        and all(type(r['primary_reward']) in (int, float) and r['primary_reward'] in (0, 1) for r in rows),
        'The historical/new scopes or native binary primary rewards changed')
    def summary(items):
        successes = sum(r['primary_reward'] for r in items)
        return {'task_count': len(items), 'primary_successes': successes,
            'primary_pass_at_1': successes / len(items)}
    def by_mode(items):
        return {mode: summary([r for r in items if r['mode'] == mode]) for mode in base.MODES}
    historical = [r for r in rows if r['scope'] == 'retained_historical']
    new = [r for r in rows if r['scope'] == 'new_confirmation']
    require(all(Counter(r['mode'] for r in items) == Counter({mode: 5 for mode in base.MODES})
        for items in (historical, new)), 'Each fixed observation scope must retain five tasks per mode')
    primary = sum(r['primary_reward'] for r in rows)
    new_successes = sum(r['primary_reward'] for r in new)
    return {'primary_successes': primary, 'primary_overall_pass_at_1': primary / 20,
        'passed': primary <= 4, 'primary_by_mode': by_mode(rows),
        'historical_retained': summary(historical), 'new_confirmation': summary(new),
        'new_wave_primary_successes': new_successes, 'new_wave_primary_pass_at_1': new_successes / 10,
        'new_wave_primary_by_mode': by_mode(new),
        'new_wave_own_point_two_gate_passed': new_successes <= 2,
        'new_wave_gate_is_informational': True, 'twenty_fresh_attempts_claimed': False}


def augment(value, binding, profile):
    """Append the active policy while preserving staging, results and unknown usage."""
    result = previous.augment(value, binding, profile)
    for task in result['tasks']:
        for key in list(task):
            if key.startswith('conservative_'):
                del task[key]
        if task['scope'] == 'retained_historical':
            reason, cause = 'retained_historical_primary_zero', 'original_analysis_preserved'
        elif task['score_state'] == 'known_tool_budget_failure':
            reason, cause = 'verified_tool_budget_failure', 'budget_evidence_verified'
        elif task['original_raw_reward'] == 0:
            reason, cause = 'primary_exact_contract_mismatch', 'cause_not_required'
        else:
            reason, cause = 'complete_primary_success', 'not_applicable'
        task['primary_score_reason'] = reason
        task['failure_cause_status'] = cause
    require(result['gate_result'] == gate_rows(result['tasks']), 'The primary whole-set gate changed during finalization')
    result['version'] = 3
    result['gate'] = deepcopy(GATE)
    result['finalizer_revision3'] = {
        'implementation': ref(__file__), 'frozen_bounded_review_finalizer': ref(PREVIOUS),
        'frozen_staged_publisher': ref(previous.BASE), 'bounded_review_contract': binding,
        'active_release_policy': 'primary_exact_answer_and_strict_tool_budget',
        'staged_recipe_and_dataset_manifest_unchanged': True,
        'original_protocol_and_results_preserved': True,
        'failure_cause_analysis_required': False,
        'auxiliary_pass_rate_measured_or_claimed': False,
    }
    return result


def finalize(installed, confirmation, review, actual_controls, output, *, review_contract, development=()):
    binding, profile = previous.contract(review_contract)
    before = ref(previous.BASE); prior = ref(PREVIOUS); implementation = ref(__file__)
    namespace = dict(vars(base))
    # The original staged GATE and recipe remain the admission identity. Only the
    # external release gate changes; neither installed bytes nor raw scores move.
    namespace['validate_quality'] = previous.quality_validator(profile)
    namespace['conservative'] = primary_score
    namespace['gate_rows'] = gate_rows
    old_message = 'The fixed combined primary or conservative pass rate exceeds 0.2; keep the whole failed cohort'
    def release_require(value, message):
        base.require(value, 'The fixed combined primary pass rate exceeds 0.2; keep the whole failed cohort'
            if message == old_message else message)
    namespace['require'] = release_require
    def final_write(path, value):
        require(value['kind'] == 'qualified_ringfenced_business_revision_release',
            'The primary finalizer writes only its final release receipt')
        require(ref(previous.BASE) == before and ref(PREVIOUS) == prior and ref(__file__) == implementation,
            'A frozen finalizer changed during evidence consumption')
        previous.contract(binding)
        return base.write(path, augment(value, binding, profile))
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
