#!/usr/bin/env python3
"""Prepare every frozen composite source with five controls and no model calls.

This is preparation only. Public-only recovery, private diagnosis, and fresh
difficulty evaluation remain separate requirements.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))

from sheets_factory.core.audit import AuditStore, utcnow
from sheets_factory.dashboard import DashboardServer
from sheets_factory.evaluation.harbor import inspect_export
from build_composite_sources import verify_built_source
from prepare_composite_probe import (CONTROL_REWARDS, prepare, validate_preparation_options,
                                     validate_source_manifest)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    """The batch owns only new paths; never replace existing evidence."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha(path)}


def checked_reference(value, label):
    if (not isinstance(value, dict) or not isinstance(value.get('path'), str)
            or not isinstance(value.get('sha256'), str)
            or not re.fullmatch(r'[a-f0-9]{64}', value['sha256'])):
        raise ValueError('Explicit SHA256 reference required: ' + label)
    path = Path(value['path']).resolve()
    if not path.is_file() or sha(path) != value['sha256']:
        raise ValueError('Changed or missing source evidence: ' + label)
    return path


def track_references(value, tracked):
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            path = checked_reference(value, 'actual source verification')
            tracked[path] = value['sha256']
        for child in value.values():
            track_references(child, tracked)
    elif isinstance(value, list):
        for child in value:
            track_references(child, tracked)


def assert_unchanged(tracked):
    for path, digest in tracked.items():
        if not path.is_file() or sha(path) != digest:
            raise ValueError('Frozen source evidence changed during preparation: ' + str(path))


def freeze_sources(source_batch_manifest, output, mode, options):
    """Validate the complete declared order before the first prepare call."""
    source_batch_manifest = Path(source_batch_manifest).resolve()
    raw = source_batch_manifest.read_bytes()
    source = json.loads(raw)
    selected = source.get('selected')
    if (source.get('status') != 'independently_verified_composed_financial_seed_batch'
            or source.get('mode') != 'build' or source.get('recipe_unchanged') is not True
            or not isinstance(selected, list) or len(selected) < 10
            or source.get('verified_derived_workbook_count') != len(selected)
            or source.get('target_derived_workbook_count') != len(selected)
            or source.get('model_scores_consulted') is not False):
        raise ValueError('A complete unchanged composite source build batch with at least ten selected sources is required')
    tracked = {source_batch_manifest: hashlib.sha256(raw).hexdigest()}
    for name in ('source_selection', 'plan', 'scenario_config'):
        path = checked_reference(source.get(name), name)
        tracked[path] = source[name]['sha256']
    original_selection = json.loads(Path(source['source_selection']['path']).read_text())
    if (original_selection.get('profiles') != [item.get('profile_id') for item in selected]
            or original_selection.get('model_results_consulted') is not False):
        raise ValueError('Source selected order differs from its predeclared source selection')
    records, identities, task_ids = [], set(), set()
    for index, item in enumerate(selected):
        identity = item.get('sha256')
        if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{64}', identity) or identity in identities:
            raise ValueError('Selected source SHA256 values must be explicit and distinct')
        task_id = ('fm-' if mode == 'financial_modeling' else 'dbg-') + identity[:12]
        if task_id in task_ids:
            raise ValueError('Selected source hash prefixes create duplicate task IDs')
        identities.add(identity)
        task_ids.add(task_id)
        source_path = checked_reference(item.get('source_manifest'), 'selected source manifest')
        one, entry, source_tracked = validate_source_manifest(source_path)
        if (entry['sha256'] != identity or item.get('source_sha256') != identity
                or one.get('derived_workbook_sha256') != identity
                or Path(entry['local_path']).resolve() != Path(item.get('local_path', '')).resolve()
                or entry.get('finance_evidence', {}).get('financial_seed_verified') is not True):
            raise ValueError('Selected workbook and actual source manifest SHA256 bindings differ')
        proof = verify_built_source(one, source_path.parent)
        tracked.update(source_tracked)
        tracked[source_path] = item['source_manifest']['sha256']
        track_references(proof, tracked)
        records.append({'index': index, 'profile_id': item['profile_id'], 'source_id': identity,
            'task_id': task_id,
            'source_manifest': {'path': str(source_path), 'sha256': item['source_manifest']['sha256']},
            'workbook': reference(entry['local_path']), 'verification': proof})
    assert_unchanged(tracked)
    selection = {'schema_version': 1, 'kind': 'composite_preparation_selection', 'frozen_at': utcnow(),
        'source_batch_manifest': {'path': str(source_batch_manifest), 'sha256': tracked[source_batch_manifest]},
        'source_selected_order': [record['profile_id'] for record in records], 'sources': records,
        'selected_task_ids': [record['task_id'] for record in records], 'mode': mode,
        'construction': deepcopy(options), 'model_results_consulted': False,
        'selection_policy': 'Prepare every selected source in its original frozen order. No task or model result may alter this selection.',
        'qualified': False, 'task_count': 0, 'llm_calls': 0}
    write(Path(output) / 'selection_manifest.json', selection)
    tracked[Path(output) / 'selection_manifest.json'] = sha(Path(output) / 'selection_manifest.json')
    return selection, tracked


def prepare_batch(source_batch_manifest, output, mode='financial_modeling', *, workers=1,
                  root_impact_validation='strict', composite_activity=False, port=0):
    validate_preparation_options(mode, root_impact_validation, composite_activity)
    if type(workers) is not int or not 1 <= workers <= 2:
        raise ValueError('Composite preparation workers must be one or two')
    source_batch_manifest, output = Path(source_batch_manifest).resolve(), Path(output).resolve()
    if output == source_batch_manifest.parent or source_batch_manifest.parent in output.parents:
        raise ValueError('Preparation output must be outside the original source batch')
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    options = {'root_impact_validation': root_impact_validation, 'composite_activity': composite_activity}
    audit = AuditStore(output / 'audit', {'id': output.name, 'kind': 'composite_prequality_preparation_batch',
        'status': 'validating_sources', 'mode': mode, 'workers': workers, 'producer_active': True,
        'llm_calls_permitted': False, 'qualified': 0})
    server = DashboardServer(audit.snapshot, audit.events, port=port)
    url = server.start()
    audit.update_run(dashboard_url=url)
    print(json.dumps({'output': str(output), 'dashboard_url': url, 'mode': mode, 'workers': workers}), flush=True)
    try:
        selection, tracked = freeze_sources(source_batch_manifest, output, mode, options)
        records = selection['sources']
        audit.update_run(status='preparing', target_count=len(records))
        audit.emit('composite_preparation.selection_frozen', selected_task_ids=selection['selected_task_ids'],
                   selection_manifest=reference(output / 'selection_manifest.json'), llm_calls=0)
        for record in records:
            audit.task(record['task_id'], status='scheduled', mode=mode, source_id=record['source_id'],
                       profile_id=record['profile_id'], source_order=record['index'])
        audit.export()

        def one(record):
            task_id = record['task_id']
            directory = output / 'probes' / (f"{record['index']:02d}-" + task_id)
            node_records = {}

            def progress(*, task_id, node, status, **values):
                if task_id != record['task_id']:
                    raise ValueError('Preparation progress differs from its frozen task ID')
                if status == 'running':
                    node_records[node] = audit.record('nodes', {'task_id': task_id, 'node': node,
                        'node_id': node, 'status': status, 'started_at': utcnow()})
                elif node in node_records:
                    audit.update_record('nodes', node_records[node], {'status': status, **values})
                audit.task(task_id, status='preparing', node=node)
                audit.emit('composite_preparation.node', task_id=task_id, node=node, status=status, **values)
                audit.export()

            began = time.monotonic()
            try:
                assert_unchanged({Path(record['source_manifest']['path']): record['source_manifest']['sha256'],
                                  Path(record['workbook']['path']): record['workbook']['sha256'],
                                  source_batch_manifest: selection['source_batch_manifest']['sha256']})
                result = prepare(record['source_manifest']['path'], directory, mode,
                    root_impact_validation=root_impact_validation, composite_activity=composite_activity,
                    progress=progress)
                if (result.get('selected_task_ids') != [task_id] or len(result.get('tasks', [])) != 1
                        or result.get('local_controls') != CONTROL_REWARDS
                        or result.get('source_manifest') != record['source_manifest']
                        or result.get('qualified') is not False or result.get('task_count') != 0
                        or result.get('llm_calls') != 0 or result.get('model_evaluation_performed') is not False):
                    raise ValueError('Prepared probe lacks its bound five-control, unqualified result')
                task = deepcopy(result['tasks'][0])
                if task.get('source_id') != record['source_id'] or task.get('task_id') != task_id or task.get('mode') != mode:
                    raise ValueError('Prepared task differs from frozen source or mode')
                binding = inspect_export(task['task_directory'])
                if binding != task.get('harbor_export_binding'):
                    raise ValueError('Prepared export binding changed')
                target = output / 'SpreadsheetEval' / task_id
                shutil.copytree(task['task_directory'], target)
                if inspect_export(target) != binding:
                    raise ValueError('Aggregated export differs from prepared probe')
                task['task_directory'] = str(target)
                task['probe_manifest'] = reference(directory / 'probe_manifest.json')
                audit.task(task_id, status='probe_prepared', node='complete',
                           revision_hash=task.get('revision_hash'), local_controls=result['local_controls'])
                return {'task_id': task_id, 'profile_id': record['profile_id'], 'source_id': record['source_id'],
                        'status': 'prepared', 'task': task, 'probe_manifest': task['probe_manifest'],
                        'duration_seconds': round(time.monotonic() - began, 3)}
            except Exception as exc:
                failure = {'task_id': task_id, 'profile_id': record['profile_id'], 'source_id': record['source_id'],
                    'status': 'failed', 'error': {'type': type(exc).__name__, 'reason': str(exc)},
                    'probe_directory': str(directory), 'duration_seconds': round(time.monotonic() - began, 3)}
                write(output / 'failures' / (task_id + '.json'), failure)
                audit.task(task_id, status='rejected', node='preparation_failed', error=failure['error'])
                return failure
            finally:
                audit.export()

        if workers == 1:
            attempts = [one(record) for record in records]
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                attempts = list(pool.map(one, records))
        assert_unchanged(tracked)
        prepared = [item['task'] for item in attempts if item['status'] == 'prepared']
        manifest = {'schema_version': 1, 'kind': 'composite_prequality_preparation_batch',
            'status': 'prepared' if len(prepared) == len(records) else 'partial_preparation',
            'frozen_at': selection['frozen_at'], 'finished_at': utcnow(), 'mode': mode,
            'source_batch_manifest': selection['source_batch_manifest'],
            'selection_manifest': reference(output / 'selection_manifest.json'),
            'selection_policy': selection['selection_policy'], 'construction': options, 'workers': workers,
            'selected_task_ids': [task['task_id'] for task in prepared], 'tasks': prepared, 'attempts': attempts,
            'selected_source_count': len(records), 'prepared_task_count': len(prepared),
            'failed_preparations': len(records) - len(prepared), 'qualified': False, 'task_count': 0,
            'llm_calls': 0, 'model_evaluation_performed': False, 'model_results_consulted': False,
            'quality_status': 'Source audits and five local construction controls only; public-only recovery, task diagnosis and fresh difficulty evaluation remain pending.',
            'elapsed_seconds': round(time.monotonic() - started, 3)}
        write(output / 'preparation_manifest.json', manifest)
        audit.update_run(status=manifest['status'], prepared_tasks=len(prepared),
                         failed_preparations=manifest['failed_preparations'], qualified=0,
                         elapsed_seconds=manifest['elapsed_seconds'])
        audit.emit('composite_preparation.completed', prepared_tasks=len(prepared),
                   failed_preparations=manifest['failed_preparations'], llm_calls=0, qualified=0)
        return manifest
    except BaseException as exc:
        write(output / 'batch_failure.json', {'type': type(exc).__name__, 'reason': str(exc)})
        audit.update_run(status='failed', error=str(exc), qualified=0)
        raise
    finally:
        audit.update_run(producer_active=False)
        audit.export()
        server.stop()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-batch-manifest', '--source-manifest', dest='source_batch_manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=['financial_modeling', 'debugging'], default='financial_modeling')
    parser.add_argument('--workers', type=int, choices=(1, 2), default=1)
    parser.add_argument('--root-impact-validation', choices=['strict', 'shadow_roots'], default='strict')
    parser.add_argument('--composite-activity', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    result = prepare_batch(args.source_batch_manifest, args.output, args.mode, workers=args.workers,
        root_impact_validation=args.root_impact_validation, composite_activity=args.composite_activity, port=args.port)
    print(json.dumps({'manifest': str(args.output.resolve() / 'preparation_manifest.json'),
        'status': result['status'], 'prepared_tasks': result['prepared_task_count'],
        'failed_preparations': result['failed_preparations'], 'qualified': False, 'llm_calls': 0}), flush=True)
    return 0 if result['status'] == 'prepared' else 2


if __name__ == '__main__':
    raise SystemExit(main())
