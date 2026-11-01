#!/usr/bin/env python3
"""Publish a compact release receipt after fresh confirmation and root controls."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

from dirhash import dirhash
from sheets_factory.evaluation.resource_harbor import inspect_resource_export

ROOT = Path(__file__).resolve().parents[1]


def require(value, message):
    if not value:
        raise ValueError(message)


def ref(path):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_file(), 'Use an existing real evidence file')
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def read_ref(record):
    require(ref(record['path']) == record, 'A retained evidence file changed')
    return json.loads(Path(record['path']).read_text())


def read_path(path):
    return read_ref(ref(path))


def confirmation_scores(terminal, selected):
    require(terminal.get('kind') == 'operating_reports_factory_frontier_terminal_v6'
            and terminal.get('phase') == 'confirmation' and terminal.get('outer_retries') == 0,
            'Require a genuine fresh confirmation phase with zero outer retries')
    results = terminal['results']; by_id = {row['task_id']: row for row in results}
    require(len(results) == len(by_id) == len(selected) == 20 and set(by_id) == set(selected),
            'Confirmation must cover every frozen task exactly once')
    rows = []
    for task_id in selected:
        row = by_id[task_id]; attempt = row['actual_attempt']; score = row['score']; resources = row['resources']
        require(resources.get('passed') is resources.get('complete') is True and attempt.get('status') == 'scored',
                'Every final attempt requires actual complete resource and scoring evidence')
        raw = attempt.get('raw_verifier_reward', attempt.get('reward')); clock = attempt.get('tool_time') or {}
        if not attempt.get('failure_kind') and clock.get('passed') is True and type(raw) in (int, float) and raw in (0, 1):
            expected, state = raw, 'complete'
        elif attempt.get('failure_kind') == 'cumulative_tool_budget_exhausted' and clock.get('passed') is False:
            expected, state = 0, 'known_tool_budget_failure'
        else:
            raise ValueError('Infrastructure, missing timing or an incomplete attempt cannot supply a zero')
        require(score.get('effective_reward') == expected and score.get('state') == state,
                'The effective reward must reproduce the original attempt and tool policy')
        rows.append({'task_id': task_id, 'mode': row['mode'], 'variant_id': row['variant_id'],
            'reward': expected, 'raw_verifier_reward': raw, 'state': state,
            'tool_seconds': clock.get('cumulative_tool_seconds'),
            'tool_lower_seconds': clock.get('cumulative_lower_bound_seconds'),
            'tool_upper_seconds': clock.get('cumulative_upper_bound_seconds'),
            'result_sha256': attempt['result_sha256'], 'task_checksum': attempt['task_checksum'],
            'material_identity_sha256': row['material_identity']['sha256']})
    require(Counter(row['mode'] for row in rows) == Counter({'financial_modeling': 10, 'debugging': 10}),
            'Require exactly ten tasks per category')
    passed = sum(row['reward'] for row in rows)
    require(passed <= 4, 'The frozen fresh confirmation exceeds Overall Pass@1 of 0.2')
    return rows, passed/20


def usage(attempts):
    records = [a.get('agent_result') or {} for a in attempts]
    return {'attempts': len(records), 'known_input_tokens': sum(r.get('n_input_tokens') or 0 for r in records),
        'known_output_tokens': sum(r.get('n_output_tokens') or 0 for r in records),
        'known_cached_input_tokens': sum(r.get('n_cache_tokens') or 0 for r in records),
        'unknown_usage_attempts': sum(type(r.get('n_input_tokens')) is not int or type(r.get('n_output_tokens')) is not int for r in records),
        'provider_paid_cost': None, 'provider_paid_cost_status': 'not available',
        'cached_input_tokens_are_a_subset': True}


def finalize(cohort_path, confirmation_path, quality_path, controls_path, output):
    cohort_ref, confirmation_ref, quality_ref, controls_ref = map(ref, (cohort_path, confirmation_path, quality_path, controls_path))
    cohort, confirmation, quality, controls = map(read_ref, (cohort_ref, confirmation_ref, quality_ref, controls_ref))
    selected = cohort['selected_task_ids']
    require(cohort['kind'] == 'frozen_operating_report_factory_confirmation_cohort'
            and cohort['count'] == 20 and cohort['selection_uses_confirmation_results'] is False,
            'The cohort must be frozen independently of confirmation results')
    prepared = read_ref(confirmation['prepared'])
    require(prepared['development'] == cohort['development']
            and set(row['task_id'] for row in prepared['tasks']) == set(selected),
            'Fresh confirmation must use the selected development materials')
    rows, overall = confirmation_scores(confirmation, selected)
    evaluation = read_ref(confirmation['evaluation']); selection = read_ref(confirmation['selection'])
    require(evaluation['status'] == 'completed' and evaluation['model'] == selection['model'] == 'gpt-6.1-sol'
            and evaluation['reasoning_effort'] == selection['reasoning_effort'] == 'xhigh'
            and selection['phase'] == 'confirmation' and selection['n_attempts'] == 1
            and selection['tool_time_policy_version'] == 6 and set(selection['selected_task_ids']) == set(selected),
            'Retain the exact native model and fresh one-attempt v6 selection')
    global_resources = read_ref(confirmation['resources'])
    require(global_resources['passed'] is global_resources['complete'] is True, 'Require all actual confirmation role observations')
    require(quality['kind'] == 'operating_report_factory_final_quality_join' and quality['passed'] is True
            and quality['task_count'] == 20 and len(quality['tasks']) == 20
            and {row['task_id'] for row in quality['tasks']} == set(selected), 'Require completed quality evidence for every final material')
    for row in quality['tasks']:
        require(row['passed'] is True and set(row['assessments']) == {f'Q{i:02d}' for i in range(1, 13)}
                and all(item['state'] in ('clear', 'not_applicable') and item.get('evidence') for item in row['assessments'].values()),
                'Every enabled check needs supported final evidence')
    require(controls['kind'] == 'complete_exact_twenty_root_controls' and controls['passed'] is True
            and controls['oracle_all20_reward'] == 1 and controls['nop_all20_reward'] == 0
            and controls['actual_role_resources_checked'] is True, 'Require actual complete root oracle/nop controls')
    dataset = ROOT/'SpreadsheetEval'; manifest_ref = ref(dataset/'dataset_manifest.json'); manifest = read_ref(manifest_ref)
    require(manifest_ref == controls['dataset_manifest'] and set(manifest['selected_task_ids']) == set(selected),
            'The actual root controls must bind the delivered frozen cohort')
    by_id = {row['task_id']: row for row in rows}
    for task in manifest['tasks']:
        directory = dataset/task['task_id']
        require(inspect_resource_export(directory) == task['harbor_export_binding']
                and dirhash(directory, 'sha256') == by_id[task['task_id']]['task_checksum'],
                'Every delivered task must equal its actual confirmed snapshot')
    for role, expected in (('oracle', 1), ('nop', 0)):
        command = read_ref(controls['command_receipts'][role]); actual = read_ref(command['whole_job_audit'])
        require(command['argv'] == ['harbor', 'run', '-p', 'SpreadsheetEval', '-a', role]
                and command['cwd'] == str(ROOT) and command['returncode'] == 0
                and actual['status'] == 'passed' and len(actual['trials']) == 20
                and {row['task_id'] for row in actual['trials']} == set(selected)
                and all(row['reward'] == expected for row in actual['trials']), 'Require each exact full-directory command and actual per-task reward')
    development = read_ref(cohort['development'])
    attempts = [row['actual_attempt'] for terminal in (development, confirmation) for row in terminal['results'] if row.get('actual_attempt')]
    consumption = usage(attempts)
    consumption['known_total_tokens'] = consumption['known_input_tokens']+consumption['known_output_tokens']
    result = {'kind': 'qualified_operating_report_factory_release', 'version': 1,
        'created_at': datetime.now(timezone.utc).isoformat(), 'qualified': True, 'task_count': 20,
        'counts_by_mode': {'financial_modeling': 10, 'debugging': 10}, 'overall_pass_at_1': overall,
        'model': 'gpt-6.1-sol', 'reasoning_effort': 'xhigh', 'native_codex_cli': True,
        'strict_cumulative_tool_budget_seconds': 1800, 'model_response_time_included': False,
        'shared_source_count': 1, 'candidate_count': len(development['results']),
        'candidate_conversion': 20/len(development['results']),
        'cohort': cohort_ref, 'confirmation': confirmation_ref, 'quality': quality_ref, 'controls': controls_ref,
        'dataset_manifest': manifest_ref, 'tasks': rows, 'strongest_model_consumption': consumption,
        'ordinary_semantic_review_consumption_reported_separately': True,
        'historical_production_and_official_study_consumption_excluded': True}
    output = Path(output).absolute(); require(output == output.resolve() and not output.exists(), 'Use a new public summary file')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False); stream.write('\n')
    return ref(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('cohort', 'confirmation', 'quality', 'controls', 'output'):
        parser.add_argument('--'+name, required=True, type=Path)
    args = parser.parse_args(); print(json.dumps(finalize(args.cohort, args.confirmation, args.quality, args.controls, args.output)))
