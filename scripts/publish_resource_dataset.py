#!/usr/bin/env python3
"""Freeze complete resource cohorts or validate an explicit final publication.

Both subcommands perform zero model, LO, Docker and Harbor executions. Publishing
is opt-in; validation is the default. External original evidence remains required
to revalidate the release. The 17-file oracle tasks themselves are standalone.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import publish_dataset as legacy
from sheets_factory.evaluation.resource_publication import (
    BUDGET, KIND, ResourcePublicationBackend, checked, publication_recipe, read, reference, require, self_families)
from sheets_factory.reporting import read_run


def _write(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def _confirmation_history(rows, roots):
    history, seen = [], set()
    for directory in roots:
        directory = Path(directory)
        for path in ([directory] if directory.is_file() else sorted(directory.rglob('selection_manifest.json'))):
            if str(path.absolute()) in seen: continue
            seen.add(str(path.absolute())); manifest = read(path)
            require(isinstance(manifest, dict) and isinstance(manifest.get('tasks'), list),
                    'A historical selection is malformed')
            if manifest.get('phase') == 'confirmation':
                for task in manifest['tasks']:
                    require(not any(task.get('revision_hash') == row['revision_hash']
                        or (task.get('task_id') == row['task_id'] and task.get('revision') == row['revision'])
                        for row in rows), 'A declared revision already belongs to a confirmation; do not resample it')
            history.append(reference(path))
    return history


def freeze_cohort(task_sources, output, *, project_root=ROOT, history_roots=()):
    """Bind the complete declared set before any of its confirmation outcomes.

task_sources is an ordered JSON file/list of {task_id, source_run, family} rows.
The order and every source identity remain in the source manifest even though
the existing frontier runner uses a deterministic task-ID order for execution.
"""
    root, output = Path(project_root).resolve(), Path(output).absolute()
    require(output == output.resolve() and not output.exists(), 'Use a fresh real cohort directory')
    declaration = reference(task_sources) if isinstance(task_sources, (str, Path)) else None
    sources = checked(declaration) if declaration else task_sources
    require(isinstance(sources, list) and sources, 'Declare the complete ordered task-to-source-run mapping')
    backend = ResourcePublicationBackend(project_root=root)
    rows = []
    for item in sources:
        require(isinstance(item, dict) and item.get('family') in self_families()
                and isinstance(item.get('task_id'), str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', item['task_id'])
                and isinstance(item.get('source_run'), str) and Path(item['source_run']).is_absolute(),
                'Each declared task needs its explicit family and absolute original source run')
        run = Path(item['source_run']); tasks = read_run(run)['tasks']
        require(run == run.resolve() and not output.is_relative_to(run),
                'A fresh cohort must remain outside every original source run')
        matches = [task for task in tasks if task['id'] == item.get('task_id')]
        require(len(matches) == 1 and matches[0].get('status') == 'qualified',
                'Every declared source task must be currently quality-qualified')
        task = matches[0]
        rows.append({key: task.get(key) for key in ('mode', 'revision', 'revision_hash', 'source_id')} | {
            'task_id': task['id'], 'source_run': str(run.absolute()), 'family': item['family'],
            'audited_harbor_export_binding': task.get('harbor_export_binding'),
            'harbor_export_binding': backend.inspect_export(run / 'SpreadsheetEval' / task['id']),
            **({'control_observation_receipts': item['control_observation_receipts']}
               if 'control_observation_receipts' in item else {}),
            **({'supplemental_resource_controls': item['supplemental_resource_controls']}
               if 'supplemental_resource_controls' in item else {})})
    cohort = {'kind': KIND, 'version': 1, 'status': 'frozen_for_fresh_confirmation',
        'frozen_at': datetime.now(timezone.utc).isoformat(), 'selected_task_ids': [row['task_id'] for row in rows],
        'tasks': rows, 'execution_budget': dict(BUDGET), 'timeout_seconds': 14400,
        'tool_time_policy_version': 2, 'selection_uses_confirmation_outcomes': False,
        'original_source_mapping_order_retained': True, 'qualified_set_is_not_difficulty_qualified': True,
        'original_checkout_and_external_evidence_required': True,
        'portable_evidence_inspection_claimed': False, 'publication_recipe': publication_recipe(root)}
    backend.validate_cohort_shape(cohort); backend.cohort = cohort
    tracked, private_scopes = {}, {}
    if declaration: backend._bind(declaration, tracked)
    # Reject every previous confirmation overlap, independently of its score.
    history = _confirmation_history(rows, [root / 'outputs/difficulty', *history_roots])
    for row in rows:
        run = Path(row['source_run']); task = next(task for task in read_run(run)['tasks'] if task['id'] == row['task_id'])
        state = backend._run(run, row['family'], tracked); config = state['config']
        private_root = Path(config.get('diagnosis', {}).get('execution', {}).get(
            'private_evidence_directory', root / 'outputs/diagnostic_private_evidence'))
        if not private_root.is_absolute(): private_root = root / private_root
        require(private_root != Path(private_root.anchor), 'Private evidence root cannot be the filesystem root')
        item = backend.release._validate_task(run, task, tracked, legacy._credential_values(root),
            project_root=root, registry_path=config.get('native_risks', {}).get('registry_path'),
            private_evidence_root=private_root, private_evidence_tracked=private_scopes.setdefault(str(private_root), {}),
            backend=backend)
        require(legacy._task_contract(run / 'SpreadsheetEval' / row['task_id'], run, tracked,
                legacy._credential_values(root), backend=backend) == row['harbor_export_binding'],
                'The original task export differs from its declared revision')
        row['validated_quality_artifacts'] = {key: item[key] for key in (
            'diagnosis', 'independent_recovery', 'controls', 'control_summaries', 'native_risk_check')}
    # All expensive checks precede the first write. A later failure preserves
    # the new partial directory and never changes original source artifacts.
    output.mkdir(parents=True)
    for row in rows:
        original = Path(row['source_run']) / 'SpreadsheetEval' / row['task_id']
        target = output / 'SpreadsheetEval' / row['task_id']
        backend.release._copy_payload(original, target, backend=backend)
        require(legacy._task_contract(target, output, {}, legacy._credential_values(root), backend=backend)
                == row['harbor_export_binding'], 'The complete 17-file cohort copy changed')
        row['task_directory'] = str(target)
        row['execution_budget'] = dict(BUDGET)
    cohort['declaration'] = declaration
    cohort['prior_selection_inventory'] = _confirmation_history(rows, [root / 'outputs/difficulty', *history_roots])
    backend._bind(history, tracked)
    backend._bind(cohort['prior_selection_inventory'], tracked)
    backend._bind(cohort['publication_recipe'], tracked)
    backend.recheck_tracked(tracked)
    backend.recheck_payloads()
    for scope, records in private_scopes.items():
        for path, digest in records.items():
            require(hashlib.sha256(backend.release._file(path, scope, {})).hexdigest() == digest,
                    'Complete scoped private evidence changed during cohort freeze')
    latest = {task['id']: task for task in backend.current_tasks()}
    require(all(latest[row['task_id']] == backend.tasks[row['task_id']]['task'] for row in rows),
            'A source task changed during cohort freeze')
    _write(output / 'cohort_manifest.json', cohort)
    return reference(output / 'cohort_manifest.json')


def publish(cohort_manifest, selection_manifest, evaluation_manifest, *, project_root=ROOT, publish_files=False):
    backend = ResourcePublicationBackend(cohort_manifest, project_root=project_root)
    first = backend.cohort['tasks'][0]['source_run']
    return legacy.publish_dataset(run_dir=first, selection_manifest=selection_manifest,
        evaluation_manifest=evaluation_manifest, project_root=project_root,
        dry_run=not publish_files, backend=backend)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    freeze = commands.add_parser('freeze-cohort')
    freeze.add_argument('--task-sources', type=Path, required=True)
    freeze.add_argument('--output', type=Path, required=True)
    freeze.add_argument('--history-root', type=Path, action='append', default=[])
    publication = commands.add_parser('publish')
    publication.add_argument('--cohort', type=Path, required=True)
    publication.add_argument('--selection-manifest', type=Path, required=True)
    publication.add_argument('--evaluation-manifest', type=Path, required=True)
    publication.add_argument('--publish', action='store_true', help='Actually copy final files; default validates only')
    args = parser.parse_args(argv)
    if args.command == 'freeze-cohort':
        result = freeze_cohort(args.task_sources, args.output, history_roots=args.history_root)
    else:
        result = publish(args.cohort, args.selection_manifest, args.evaluation_manifest,
                         publish_files=args.publish)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
