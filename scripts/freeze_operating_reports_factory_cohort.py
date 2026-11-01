#!/usr/bin/env python3
"""Select a fixed 10+10 cohort using development evidence only."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

from sheets_factory.evaluation.resource_harbor import inspect_resource_export


def reference(path):
    path = Path(path).absolute()
    if path != path.resolve() or not path.is_file():
        raise ValueError('Use a real retained file')
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def checked(value):
    if reference(value['path']) != value:
        raise ValueError('A retained reference changed')
    return json.loads(Path(value['path']).read_text())


def choose(development, tasks):
    if development.get('kind') != 'operating_reports_factory_frontier_terminal_v6' or development.get('phase') != 'development':
        raise ValueError('Selection may use development evidence only')
    results = {row['task_id']: row for row in development['results']}
    if len(results) != len(development['results']) or len({row['task_id'] for row in tasks}) != len(tasks):
        raise ValueError('Task and result identities must be unique')
    selected = []
    for mode in ('financial_modeling', 'debugging'):
        eligible = []
        for task in tasks:
            row = results.get(task['task_id'], {})
            score = row.get('score', {})
            if task['mode'] != mode or score.get('state') not in ('complete', 'known_tool_budget_failure') or score.get('effective_reward') not in (0, 1):
                continue
            if not row.get('actual_attempt') or not row.get('resources', {}).get('passed') or not row.get('resources', {}).get('complete'):
                continue
            # Within each measured outcome, prefer the larger predeclared scope.
            size = task.get('primary_difference_count', 0)
            eligible.append((score['effective_reward'], -size, task['variant_id'], task['task_id'], task))
        eligible.sort(key=lambda row: row[:-1])
        if len(eligible) < 10:
            raise ValueError('Fewer than ten completed resource-bound development attempts for '+mode)
        selected.extend(row[-1] for row in eligible[:10])
    return selected


def freeze(development_path, batches, output, root_destination):
    output = Path(output).absolute(); destination = Path(root_destination).absolute()
    if output.exists() or destination.exists() or output != output.resolve() or destination != destination.resolve():
        raise ValueError('Use fresh real cohort and root dataset directories')
    dev_ref = reference(development_path); development = checked(dev_ref)
    batch_refs = [reference(path) for path in batches]; tasks = []
    for record in batch_refs:
        batch = checked(record)
        if batch['kind'] != 'individually_engineered_operating_report_batch':
            raise ValueError('Require individually engineered source batches')
        for row in batch['tasks']:
            evidence = checked(row['individual_engineering'])
            tasks.append({**row, 'primary_difference_count': evidence['complete_primary_difference_count']})
    selected = choose(development, tasks)
    if Counter(row['mode'] for row in selected) != Counter({'financial_modeling': 10, 'debugging': 10}):
        raise ValueError('The final candidate cohort must contain exactly ten tasks per category')
    output.mkdir(parents=True)
    record = {'kind': 'frozen_operating_report_factory_confirmation_cohort', 'version': 1,
        'development': dev_ref, 'batches': batch_refs, 'tasks': selected,
        'selected_task_ids': [row['task_id'] for row in selected], 'count': 20,
        'selection_uses_confirmation_results': False, 'fresh_confirmation_attempts_started': 0,
        'actual_root_controls_pending': True, 'qualified': False,
        'selection_rule': 'Within each category, prefer valid development zeros, then larger predeclared primary scope; ties use variant ID.',
        'root_directory': str(destination), 'shared_source_count': 1}
    path = output/'cohort_frozen.json'
    with path.open('x') as stream:
        json.dump(record, stream, indent=2); stream.write('\n')
    # Selection is persisted before copying or requesting any confirmation.
    destination.mkdir()
    inventory = {}
    for row in selected:
        source = Path(row['task_directory'])
        if inspect_resource_export(source) != row['harbor_export_binding']:
            raise ValueError('A selected source export changed')
        target = destination/row['task_id']; shutil.copytree(source, target)
        if inspect_resource_export(target) != row['harbor_export_binding']:
            raise ValueError('The final root copy differs from the frozen selected task')
        files = {str(p.relative_to(target)): reference(p) for p in target.rglob('*') if p.is_file()}
        if len(files) != 17:
            raise ValueError('Keep exactly seventeen task files')
        inventory[row['task_id']] = files
    dataset_manifest = {'kind': 'frozen_operating_report_factory_dataset', 'version': 1,
        'task_count': 20, 'counts_by_mode': {'financial_modeling': 10, 'debugging': 10},
        'selected_task_ids': record['selected_task_ids'], 'cohort_freeze': reference(path),
        'shared_source_count': 1, 'tasks': [
            {'task_id': row['task_id'], 'mode': row['mode'], 'variant_id': row['variant_id'],
             'harbor_export_binding': row['harbor_export_binding'],
             'payload_files': {name: value['sha256'] for name, value in inventory[row['task_id']].items()}}
            for row in selected]}
    with (destination/'dataset_manifest.json').open('x') as stream:
        json.dump(dataset_manifest, stream, indent=2); stream.write('\n')
    with (output/'root_copy.json').open('x') as stream:
        json.dump({'cohort': reference(path), 'files': inventory, 'count': 20,
                   'dataset_manifest': reference(destination/'dataset_manifest.json'),
                   'byte_identical_copy': True, 'actual_root_controls_pending': True}, stream, indent=2); stream.write('\n')
    return reference(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--development', required=True, type=Path); parser.add_argument('--batch', action='append', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path); parser.add_argument('--root-destination', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(freeze(args.development, args.batch, args.output, args.root_destination)))
