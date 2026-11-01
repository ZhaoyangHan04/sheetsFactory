#!/usr/bin/env python3
"""Build a planned operating-report batch with individual native input checks."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import time

from openpyxl import load_workbook
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard.server import DashboardServer
from sheets_factory.evaluation.streaming_verifier import _sparse_cells, normalize
from sheets_factory.evaluation.thread_capped_harbor_export import export_resource_harbor, inspect_resource_export
from sheets_factory.workbook.thread_capped_resource_engine import ThreadCappedResourceLibreOfficeEngine

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT/'outputs/research/operating_reports_200_task8_revision2_prepared_20261031T223700Z/prepared/terminal.json'
ORIGINAL_SHA = 'fba1c365aeead7902953dd1b8c6877ece8687fd35e757ec3e5286a53e3cf67aa'
GOAL_SHA = '5f38a984cf7fc689e030602aab0f0bc95a51b05d54711d4a79207f04445936ef'
BUDGET = {'version': 1, 'elapsed_policy': 'operational_guard', 'tool_budget_seconds': 1800, 'elapsed_guard_seconds': 14400}


def ref(path):
    path = Path(path).absolute()
    if path != path.resolve() or not path.is_file():
        raise ValueError('Use an existing real file')
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def checked(record):
    if ref(record['path']) != record:
        raise ValueError('A retained input changed')
    return Path(record['path'])


def read(record):
    return json.loads(checked(record).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return ref(path)


def values(path):
    """Read the full sparse primary-value union, including native errors."""
    book = load_workbook(path, data_only=True, read_only=True, keep_links=False)
    result = {}
    errors = []
    try:
        names = book.sheetnames
        for sheet in book:
            for _, cell in _sparse_cells(sheet):
                from openpyxl.utils.cell import get_column_letter
                point = sheet.title+'!'+get_column_letter(cell['column'])+str(cell['row'])
                if cell['data_type'] == 'e':
                    value = ('error', cell['value']); errors.append(point)
                else:
                    value = normalize(cell['value'])
                if value[0] != 'empty':
                    result[point] = value
        return names, result, errors
    finally:
        book.close()


def primary_difference(left, right):
    empty = ('empty', None)
    return sorted(point for point in left.keys() | right.keys() if left.get(point, empty) != right.get(point, empty))


def load_source():
    if ref(ORIGINAL)['sha256'] != ORIGINAL_SHA:
        raise ValueError('The original completed task engineering changed')
    actual = json.loads(ORIGINAL.read_text()); prepared = read(actual['preparation'])
    source = read(prepared['source_manifest'])
    if not actual['passed'] or not source['passed'] or ref(checked(prepared['genuine_goal']))['sha256'] != GOAL_SHA:
        raise ValueError('Require the unchanged independently verified healthy source')
    candidate = read(prepared['candidate_preparation'])
    return prepared, read(prepared['specification']), read(prepared['bindings']), read(prepared['source_definition']), read(candidate['view_plans'])


def check_native_input(mode, plan, names, observed, errors, healthy_names, healthy, definition):
    if names != healthy_names or errors:
        raise ValueError('Native input changed sheet structure or contains errors: '+str(errors[:10]))
    difference = primary_difference(observed, healthy)
    if not difference or not set(difference) <= set(definition['formulas']):
        raise ValueError('Require financial formula effects and unchanged supplied facts')
    if mode == 'financial_modeling':
        if not set(plan['mask_points']) <= set(difference):
            raise ValueError('Every masked formula must have a primary value impact')
    return {'passed': True, 'complete_primary_difference_count': len(difference),
            'complete_primary_difference': difference, 'native_error_count': 0,
            'given_literals_unchanged': True, 'sheet_structure_unchanged': True,
            'programmatic_oracle_reward': 1, 'programmatic_nop_reward': 0,
            'actual_Harbor_controls_pending': True}


def build(output, *, count=20, concurrency=4, modes=('financial_modeling', 'debugging'), port=0):
    output = Path(output).absolute()
    if output != output.resolve() or output.exists() or not output.is_relative_to(ROOT/'outputs'):
        raise ValueError('Use a fresh private output directory')
    if count < 1 or count > 20 or concurrency < 1 or concurrency > 8:
        raise ValueError('Use one through twenty variants and one through eight workers')
    audit = AuditStore(output, {'id': output.name, 'status': 'running', 'stage': 'planning', 'target_candidates': count*len(modes)})
    dashboard = DashboardServer(audit.snapshot, audit.events, port=port)
    url = dashboard.start()
    write(output/'dashboard.json', {'url': url}); print(json.dumps({'dashboard': url}), flush=True)
    try:
        prepared, public, bindings, definition, original_plans = load_source()
        goal = checked(prepared['genuine_goal'])
        names, healthy, errors = values(goal)
        if errors:
            raise ValueError('Healthy source contains a native error')
        names_by_mode = {'financial_modeling': 'factory_fm_scaling', 'debugging': 'factory_debug_scaling'}
        modules = {mode: importlib.import_module('sheets_factory.workbook.operating_reports_200.'+names_by_mode[mode]) for mode in modes}
        plans = []
        for mode in modes:
            for plan in modules[mode].design_all(public, bindings, definition, original_plans)[:count]:
                plans.append({'mode': mode, 'plan': plan})
        freeze = write(output/'plans_frozen.json', {'kind': 'planned_operating_report_factory_batch', 'version': 1,
            'frozen_at': datetime.now(timezone.utc).isoformat(), 'original_engineering': ref(ORIGINAL),
            'source_manifest': prepared['source_manifest'], 'goal': prepared['genuine_goal'],
            'specification': prepared['specification'], 'bindings': prepared['bindings'],
            'source_definition': prepared['source_definition'], 'runtime_profile': prepared['runtime_profile'],
            'plans': plans, 'shared_source_count': 1, 'independent_source_count': 1,
            'execution_budget': BUDGET, 'implementation': ref(__file__),
            'scalers': {mode: ref(modules[mode].__file__) for mode in modes},
            'difficulty_status': 'unmeasured', 'actual_Harbor_controls_pending': True})
        audit.update_run(stage='native_input_checks', dashboard_url=url)

        def one(row):
            start = time.monotonic(); mode, plan = row['mode'], row['plan']; key = plan['variant_id']
            audit.task(key, mode=mode, status='running', source_id=GOAL_SHA, stage='emission')
            folder = output/'private'/key
            emitted = modules[mode].emit(goal, public, bindings, definition, original_plans, plan, folder/'emitted')
            write(folder/'emission.json', emitted)
            audit.task(key, stage='native_input_recalculation')
            engine = ThreadCappedResourceLibreOfficeEngine(ROOT, prepared['runtime_profile']['path'], role='source', receipt_directory=folder/'native_receipts')
            native = engine.recalculate(folder/'emitted/input.xlsx', folder/'input.native.xlsx')
            observed_names, observed, native_errors = values(native)
            checks = check_native_input(mode, plan, observed_names, observed, native_errors, names, healthy, definition)
            checks['native_call_metadata'] = engine.metadata()
            check_ref = write(folder/'individual_engineering.json', checks)
            material = folder/'materialized'
            (material/'public').mkdir(parents=True); (material/'private').mkdir()
            shutil.copyfile(native, material/'public/input.xlsx'); shutil.copyfile(goal, material/'private/goal.xlsx')
            instruction = (folder/'emitted/instruction.md').read_bytes()+b'\nRead /app/input.xlsx and save the completed workbook to /app/output.xlsx.\n'
            (material/'public/instruction.md').write_bytes(instruction)
            signature = hashlib.sha256(mode.encode()+native.read_bytes()+instruction).hexdigest()
            task_id = ('fm-' if mode == 'financial_modeling' else 'dbg-')+key.lower()+'-'+signature[:20]
            cap_audit = folder/'worker_cap.json'
            export = export_resource_harbor(material, output/'SpreadsheetEval'/task_id,
                {'task_id': task_id, 'mode': mode, 'source_kind': 'hypothetical_operating_report_factory',
                 'revision': 0, 'revision_hash': signature, 'difficulty_status': 'development_pending',
                 'shared_source_id': GOAL_SHA, 'variant_id': key}, ROOT,
                runtime_profile=prepared['runtime_profile']['path'], audit_path=cap_audit)
            record = {'task_id': task_id, 'mode': mode, 'revision': 0, 'revision_hash': signature,
                'source_id': GOAL_SHA, 'task_directory': str(export),
                'harbor_export_binding': inspect_resource_export(export, audit_path=cap_audit),
                'execution_budget': BUDGET, 'variant_id': key, 'individual_engineering': check_ref,
                'worker_cap_audit': ref(cap_audit), 'plan_freeze': freeze}
            write(folder/'task_record.json', record)
            audit.task(key, status='ready', stage='engineering_complete', harbor_task_id=task_id,
                       primary_difference_count=len(checks['complete_primary_difference']))
            audit.record('nodes', {'node': 'individual_engineering', 'task_id': task_id, 'duration_ms': round(1000*(time.monotonic()-start)), 'status': 'completed'})
            audit.emit('candidate_engineered', task_id=task_id, mode=mode, variant=key)
            audit.export()
            return record

        tasks = []; failures = []
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(one, row): row for row in plans}
            for future in as_completed(futures):
                row = futures[future]
                try:
                    tasks.append(future.result())
                except Exception as error:
                    failure = {'variant_id': row['plan']['variant_id'], 'mode': row['mode'], 'error_type': type(error).__name__, 'error': str(error)}
                    failures.append(failure); write(output/'failures'/(failure['variant_id']+'.json'), failure)
                    audit.task(failure['variant_id'], status='rejected', stage='engineering_failed', failure=failure)
                audit.export()
        tasks.sort(key=lambda row: (row['mode'], row['variant_id']))
        manifest = write(output/'engineered_batch.json', {'kind': 'individually_engineered_operating_report_batch', 'version': 1,
            'plans_frozen': freeze, 'tasks': tasks, 'selected_task_ids': [row['task_id'] for row in tasks],
            'failures': failures, 'count': len(tasks), 'candidate_count': len(plans),
            'by_mode': {mode: sum(row['mode'] == mode for row in tasks) for mode in modes},
            'shared_source_count': 1, 'execution_budget': BUDGET,
            'difficulty_status': 'unmeasured', 'actual_Harbor_controls_pending': True,
            'shared_semantic_review_pending': True, 'qualified': False})
        audit.update_run(status='completed', stage='engineered', engineered=len(tasks), failures=len(failures)); audit.export()
        print(json.dumps(manifest), flush=True)
        return manifest
    except BaseException as error:
        write(output/'failure.json', {'error_type': type(error).__name__, 'error': str(error)})
        audit.update_run(status='failed', error=str(error)); audit.export()
        raise
    finally:
        dashboard.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path); parser.add_argument('--count', type=int, default=20)
    parser.add_argument('--concurrency', type=int, default=4); parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--mode', choices=('all', 'financial_modeling', 'debugging'), default='all')
    args = parser.parse_args()
    modes = ('financial_modeling', 'debugging') if args.mode == 'all' else (args.mode,)
    build(args.output, count=args.count, concurrency=args.concurrency, modes=modes, port=args.port)


if __name__ == '__main__':
    main()
