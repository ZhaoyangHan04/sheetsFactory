#!/usr/bin/env python3
"""Read actual confirmation artifacts without executing or changing a score."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

BOUNDARIES = frozenset({'E057 Glenmere Facilities!M68', 'E097 Valecrest Analytics!H30'})
MODES = {'financial_modeling', 'debugging'}


def reference(path):
    path = Path(path).resolve(strict=True)
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def read(path_or_ref):
    expected = path_or_ref if isinstance(path_or_ref, dict) else None
    if expected is not None and set(expected) != {'path', 'sha256', 'bytes'}:
        raise ValueError('Expected an exact three-field artifact reference')
    path = Path(expected['path'] if expected else path_or_ref).resolve(strict=True)
    before = reference(path)
    if expected is not None and before != expected:
        raise ValueError('Artifact reference changed')
    raw = path.read_bytes()
    value = json.loads(raw)
    if reference(path) != before or hashlib.sha256(raw).hexdigest() != before['sha256']:
        raise ValueError('Artifact changed during reading')
    return value, before


def binding_index(value):
    financial = value.get('financial')
    if not isinstance(financial, dict) or not financial:
        raise ValueError('Missing financial bindings')
    index = {}
    for key, record in financial.items():
        if not isinstance(record, dict):
            raise ValueError('Invalid financial binding')
        # Retained bindings use semantic keys; physical-key variants carry semantic_key.
        semantic = record.get('semantic_key', key)
        point = f"{record['sheet']}!{record['cell']}" if 'sheet' in record and 'cell' in record else key
        if not isinstance(semantic, str) or '/' not in semantic or point in index:
            raise ValueError('Duplicate or invalid financial binding')
        index[point] = semantic.split('/')[-1]
    return index


def _points(diag, name):
    values = diag.get(name)
    if not isinstance(values, list) or any(not isinstance(p, str) for p in values) or len(values) != len(set(values)):
        raise ValueError('Invalid diagnostic position census')
    return values


def _fields(points, index):
    return dict(sorted(Counter(index.get(p, '__unmapped__') for p in points).items()))


def summarize(confirmation, cohort, bindings):
    terminal, terminal_ref = read(confirmation)
    frozen, cohort_ref = read(cohort)
    bound, bindings_ref = read(bindings)
    descriptor_ref = None
    if isinstance(bound, dict) and set(bound) == {'path', 'sha256', 'bytes'}:
        descriptor_ref = bindings_ref
        bound, bindings_ref = read(bound)
    index = binding_index(bound)
    if terminal.get('kind') != 'operating_reports_factory_frontier_terminal_v6' or terminal.get('phase') != 'confirmation':
        raise ValueError('Only an actual confirmation terminal is accepted')
    tasks = frozen.get('tasks', [])
    ids = [t['task_id'] for t in tasks]
    selected = frozen.get('selected_task_ids')
    if frozen.get('kind') != 'frozen_operating_report_factory_confirmation_cohort' or len(ids) != 20 or len(set(ids)) != 20 or len(selected or []) != 20 or set(ids) != set(selected or []):
        raise ValueError('Expected the exact frozen twenty-task cohort')
    if Counter(t['mode'] for t in tasks) != Counter({'financial_modeling': 10, 'debugging': 10}):
        raise ValueError('Expected ten tasks per mode')
    results = terminal.get('results', [])
    by_id = {r['task_id']: r for r in results}
    if len(results) != 20 or len(by_id) != 20 or set(by_id) != set(ids):
        raise ValueError('Confirmation identities differ from the frozen cohort')
    rows = []
    patterns = Counter()
    for task in tasks:
        result = by_id[task['task_id']]
        attempt = result['actual_attempt']
        if result['mode'] != task['mode'] or attempt['task_id'] != task['task_id'] or attempt['mode'] != task['mode']:
            raise ValueError('Attempt identity mismatch')
        native, native_ref = read(Path(attempt['result_file']))
        if native_ref['sha256'] != attempt['result_sha256'] or native.get('trial_name') != attempt['trial_name'] or native.get('task_name') != task['harbor_export_binding']['task_name']:
            raise ValueError('Actual result binding mismatch')
        native_reward = ((native.get('verifier_result') or {}).get('rewards') or {}).get('reward')
        if native_reward != result['score'].get('raw_verifier_reward'):
            raise ValueError('Native reward differs from the retained raw score')
        diag_path = Path(native_ref['path']).parent / 'verifier' / 'diagnostics.json'
        row = {'task_id': task['task_id'], 'mode': task['mode'], 'variant_id': task['variant_id'],
               'score': result['score'], 'actual_result': native_ref,
               'resources_passed': result.get('resources', {}).get('passed'),
               'tool_time_passed': attempt.get('tool_time', {}).get('passed'),
               'boundary_only': False, 'trace_causality_established': False}
        if diag_path.is_file():
            diag, diag_ref = read(diag_path)
            missing, extra, wrong = (_points(diag, k) for k in ('missing_changes', 'extra_changes', 'wrong_values'))
            boundary = sorted(set(wrong) & BOUNDARIES)
            row.update({'diagnostics': diag_ref, 'expected_D': diag.get('expected_change_count'),
                        'actual_D': diag.get('actual_change_count'), 'missing_count': len(missing),
                        'extra_count': len(extra), 'wrong_value_count': len(wrong),
                        'wrong_fields': _fields(wrong, index), 'missing_fields': _fields(missing, index),
                        'extra_fields': _fields(extra, index), 'known_boundary_positions': boundary,
                        'boundary_only': not missing and not extra and set(wrong) == BOUNDARIES})
            pattern = 'boundary_only' if row['boundary_only'] else 'other_observed_field_differences'
        else:
            row.update({'diagnostics': None, 'expected_D': None, 'actual_D': None,
                        'missing_count': None, 'extra_count': None, 'wrong_value_count': None,
                        'wrong_fields': {}, 'missing_fields': {}, 'extra_fields': {}, 'known_boundary_positions': []})
            pattern = 'diagnostics_missing_unknown'
        row['pattern'] = pattern
        patterns[(task['mode'], pattern)] += 1
        rows.append(row)
    def scores(subset):
        return dict(sorted(Counter('unknown' if r['score'].get('raw_verifier_reward') is None else str(r['score']['raw_verifier_reward']) for r in subset).items()))
    return {'kind': 'actual_operating_reports_factory_confirmation_failure_summary', 'version': 1,
            'evidence': {'confirmation': terminal_ref, 'cohort': cohort_ref, 'bindings': bindings_ref,
                         'bindings_descriptor': descriptor_ref}, 'count': 20,
            'raw_rewards': scores(rows), 'by_mode': {m: {'count': sum(r['mode'] == m for r in rows),
                'raw_rewards': scores([r for r in rows if r['mode'] == m])} for m in sorted(MODES)},
            'patterns': [{'mode': m, 'pattern': p, 'count': n} for (m, p), n in sorted(patterns.items())],
            'rows': rows, 'new_model_calls': 0, 'new_native_calls': 0, 'scores_modified': False,
            'financial_trace_cause_inferred': False,
            'interpretation': 'Boundary-only rows do not establish financial reasoning failure. Other rows report observed field differences, not inferred trace causality. All original scores remain unchanged.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('confirmation', 'cohort', 'bindings', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    summary = summarize(args.confirmation, args.cohort, args.bindings)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')
    print(json.dumps(reference(args.output)))


if __name__ == '__main__':
    main()
