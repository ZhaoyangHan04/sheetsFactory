#!/usr/bin/env python3
"""Freeze the fixed raw cohort, compute each reference once, and render FM inputs."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from types import FunctionType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard.server import DashboardServer
from sheets_factory.workbook.operating_reports_200 import audit as original_audit
from sheets_factory.workbook.operating_reports_financial_cohort_v1 import schema, raw, oracles, excel

RESERVATION_ROOT = ROOT / 'outputs/research/.operating_reports_financial_cohort_v1'


def now():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return schema.reference(path)


def full_compare(public, left, right):
    namespace = {**vars(original_audit), 's': schema}
    for key, value in vars(original_audit).items():
        if isinstance(value, FunctionType) and value.__globals__ is vars(original_audit):
            namespace[key] = FunctionType(value.__code__, namespace, value.__name__,
                                         value.__defaults__, value.__closure__)
    return namespace['compare'](public, left, right)


def run(output, *, port=0):
    # Resolve the full feature closure before consuming the permanent reservation.
    recipe = schema.recipes()
    rendering_recipe = excel.recipes()
    comparison_recipe = schema.reference(original_audit.__file__)
    driver = schema.reference(__file__)
    output = Path(output).absolute()
    if output != output.resolve():
        raise ValueError('Use a real fresh output directory')
    output.mkdir(parents=True, exist_ok=False)
    audit = AuditStore(output/'audit', {
        'id': output.name, 'stage': 'prospective', 'status': 'running',
        'producer_active': True, 'target_financial_modeling': 10,
        'new_raw_cases_planned': 9, 'new_financial_forwards_planned': 18,
        'actual_LO_calls': 0, 'actual_model_calls': 0, 'formal_released': 0,
    })
    panel = DashboardServer(audit.snapshot, audit.events, port=port)
    url = panel.start()
    start = time.monotonic()
    raw_inventory = None
    results = []
    forward_count = 0
    node = None
    try:
        prospective = write(output/'prospective.json', {
            'kind': 'prospective_financial_cohort_once_reference_batch', 'version': 1,
            'at': now(), 'contract': schema.reference(schema.CONTRACT),
            'recipe': recipe, 'rendering_recipe': rendering_recipe,
            'comparison_recipe': comparison_recipe,
            'orchestration_recipe': driver, 'dashboard': url,
            'new_raw_cases': 9, 'independent_forwards_per_case': {'A': 1, 'B': 1},
            'all_raws_before_any_financial_forward': True,
            'outer_retries': 0, 'actual_LO_calls': 0, 'model_calls': 0,
            'final_confirmation': False, 'qualified': False,
        })
        print(json.dumps({'dashboard': url, 'output': str(output), 'prospective': prospective}), flush=True)
        RESERVATION_ROOT.mkdir(parents=True, exist_ok=True)
        if RESERVATION_ROOT != RESERVATION_ROOT.resolve():
            raise ValueError('The permanent cohort reservation must use a real directory')
        write(RESERVATION_ROOT/(schema.CONTRACT_SHA256+'.json'), {
            'kind': 'permanent_financial_cohort_once_raw_and_reference_reservation',
            'version': 1, 'prospective': prospective, 'reserved_at': now(),
            'output': str(output), 'outer_retries': 0,
        })
        node = audit.record('nodes', {'node': 'freeze_all_nine_raws', 'status': 'running', 'started_at': now()})
        clock = time.monotonic()
        audit.update_run(stage='freeze_all_nine_raws')
        raw_inventory = raw.freeze_all(output/'raw')
        frozen = raw.validate_all(raw_inventory)
        audit.update_record('nodes', node, {'status': 'completed', 'duration_ms': 1000*(time.monotonic()-clock), 'raw_inventory': raw_inventory})
        audit.emit('all_nine_raws_frozen_before_financial_forwards', raw_inventory=raw_inventory)
        audit.export()
        node = None
        for case in frozen['inventory']['cases']:
            identity = case['candidate_id']
            public = frozen['specifications'][identity]
            folder = output/identity
            folder.mkdir()
            audit.task(identity, mode='financial_modeling', source_id=identity, status='constructing_reference')
            receipts = {}
            values = {}
            for implementation, solve in [('A', oracles.solve_A), ('B', oracles.solve_B)]:
                node = audit.record('nodes', {'node': 'independent_'+implementation, 'task_id': identity,
                                             'status': 'running', 'started_at': now()})
                clock = time.monotonic()
                target = folder/('independent_'+implementation)
                target.mkdir()
                started = write(target/'started.json', {
                    'kind': 'once_operating_reports_financial_cohort_forward_started',
                    'version': 1, 'implementation': implementation, 'case_id': identity,
                    'raw_inventory': raw_inventory, 'specification': case['specification'],
                    'recipe': recipe, 'orchestration_recipe': driver,
                    'financial_forward_limit': 1, 'outer_retries': 0, 'started_at': now(),
                })
                audit.update_run(stage='independent_'+implementation, current_candidate=identity)
                audit.emit('financial_forward_started', case_id=identity, implementation=implementation, started=started)
                audit.export()
                try:
                    # This is the only production financial call for this case/implementation.
                    forward_count += 1
                    result = solve(deepcopy(public), raw_inventory=raw_inventory)
                    result_ref = write(target/'result.json', result)
                    elapsed = time.monotonic()-clock
                    receipt = write(target/'receipt.json', {
                        'kind': 'complete_once_operating_reports_financial_cohort_forward',
                        'version': 1, 'implementation': implementation, 'case_id': identity,
                        'raw_inventory': raw_inventory, 'specification': case['specification'],
                        'result': result_ref, 'started': started, 'recipe': recipe,
                        'orchestration_recipe': driver, 'financial_forward_calls': 1,
                        'outer_retries': 0, 'qualified': False, 'elapsed_seconds': elapsed,
                    })
                    receipts[implementation] = receipt
                    values[implementation] = result
                    audit.update_record('nodes', node, {'status': 'completed', 'duration_ms': 1000*elapsed, 'receipt': receipt})
                except Exception as error:
                    failure = write(target/'failure.json', {
                        'kind': 'retained_once_financial_cohort_forward_failure',
                        'case_id': identity, 'implementation': implementation,
                        'started': started, 'error_type': type(error).__name__,
                        'error': str(error), 'financial_forward_calls': 1, 'retry_permitted': False,
                    })
                    audit.update_record('nodes', node, {'status': 'failed', 'duration_ms': 1000*(time.monotonic()-clock), 'failure': failure})
                audit.update_run(financial_forwards_started=forward_count)
                audit.export()
                node = None
            if set(receipts) != {'A', 'B'}:
                row = {'case_id': identity, 'passed': False, 'forwards': receipts, 'reason': 'independent_forward_failed'}
            else:
                node = audit.record('nodes', {'node': 'full_stored_comparison_and_FM_render', 'task_id': identity,
                                             'status': 'running', 'started_at': now()})
                clock = time.monotonic()
                try:
                    comparison = full_compare(public, values['A'], values['B'])
                    if comparison['passed'] is not True or comparison['differences']:
                        raise ValueError('The full stored independent values disagree')
                    comparison_ref = write(folder/'comparison.json', {
                        'kind': 'stored_operating_reports_financial_cohort_AB_comparison',
                        'version': 1, 'case_id': identity, 'raw_inventory': raw_inventory,
                        'specification': case['specification'], 'A': receipts['A'], 'B': receipts['B'],
                        'comparison': comparison, 'new_financial_forwards': 0,
                        'comparison_recipe': comparison_recipe,
                        'orchestration_recipe': driver,
                    })
                    candidate = excel.emit(public, folder/'emission')
                    row = {'case_id': identity, 'passed': True, 'forwards': receipts,
                           'comparison': comparison_ref, 'candidate': candidate,
                           'specification': case['specification']}
                    audit.update_record('nodes', node, {'status': 'completed', 'duration_ms': 1000*(time.monotonic()-clock), 'candidate': candidate})
                except Exception as error:
                    failure = write(folder/'comparison_or_emission_failure.json', {
                        'case_id': identity, 'error_type': type(error).__name__, 'error': str(error),
                        'independent_forwards': receipts, 'retry_permitted': False,
                    })
                    row = {'case_id': identity, 'passed': False, 'forwards': receipts, 'failure': failure}
                    audit.update_record('nodes', node, {'status': 'failed', 'duration_ms': 1000*(time.monotonic()-clock), 'failure': failure})
                node = None
            results.append(row)
            write(folder/'terminal.json', row)
            audit.task(identity, status='reference_ready' if row['passed'] else 'rejected', **row)
            audit.export()
        terminal = write(output/'terminal.json', {
            'kind': 'complete_once_financial_cohort_reference_and_emission_batch',
            'version': 1, 'raw_inventory': raw_inventory, 'cases': results,
            'new_raw_attempts': 9, 'financial_forwards_started': forward_count,
            'passed_cases': sum(row['passed'] for row in results),
            'passed': len(results) == 9 and all(row['passed'] for row in results),
            'actual_LO_calls': 0, 'actual_model_calls': 0, 'outer_retries': 0,
            'elapsed_seconds': time.monotonic()-start, 'qualified': False,
        })
        audit.update_run(status='completed', stage='reference_and_emission_complete', producer_active=False,
                         reference_ready=sum(row['passed'] for row in results), terminal=terminal)
        audit.export()
        return terminal
    except BaseException as error:
        failure = write(output/'batch_failure.json', {
            'kind': 'retained_financial_cohort_batch_failure', 'error_type': type(error).__name__,
            'error': str(error), 'financial_forwards_started': forward_count,
            'raw_inventory': raw_inventory, 'elapsed_seconds': time.monotonic()-start,
            'retry_permitted': False,
        })
        if node is not None:
            audit.update_record('nodes', node, {'status': 'failed', 'failure': failure})
        audit.update_run(status='failed', stage='retained_batch_failure', producer_active=False, failure=failure)
        audit.export()
        raise
    finally:
        panel.stop()
        audit.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    print(json.dumps(run(args.output, port=args.port)))


if __name__ == '__main__':
    main()
