#!/usr/bin/env python3
"""Freeze and run full independent finance and matrix checks, without solving."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.workbook.linear_capital_portfolio import spec


def reference(path):
    path = Path(path).resolve(strict=True)
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'bytes': path.stat().st_size}


def read(record):
    spec.require(reference(record['path']) == record, 'A frozen input changed')
    return json.loads(Path(record['path']).read_text())


def write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return reference(path)


def prepare(raw_preparation, output):
    raw_ref = reference(raw_preparation)
    raw = read(raw_ref)
    public = spec.load_spec(read(raw['specification']))
    spec.require(raw['kind'] == 'prepared_linear_240_project_raw_assumptions'
        and public['dimension_mode'] == 'production'
        and raw['specification_sha256'] == spec.canonical_sha256(public),
        'A frozen complete production raw universe is required')
    for path, digest in raw['recipe_sha256'].items():
        spec.require(reference(path)['sha256'] == digest, 'An original raw generation recipe changed')
    from sheets_factory.workbook.linear_capital_portfolio import (
        candidate_a, ledger, finance_crosscheck, model_a, model_b)
    files = [Path(__file__), Path(spec.__file__), *(Path(module.__file__) for module in
        (candidate_a, ledger, finance_crosscheck, model_a, model_b))]
    output = Path(output).absolute()
    spec.require(output == output.resolve() and output.is_relative_to(ROOT / 'outputs')
        and not output.exists(), 'Use a fresh output directory under outputs')
    output.mkdir(parents=True)
    return write(output / 'preparation.json', {
        'kind': 'prepared_linear_capital_full_financial_crosscheck', 'version': 1,
        'created_at': datetime.now(timezone.utc).isoformat(), 'raw_preparation': raw_ref,
        'recipe': {str(path): reference(path) for path in files},
        'diagnostic_plan_ids': [row['id'] for row in raw['diagnostic_plans']],
        'all_standalone_scenarios_must_be_feasible': True,
        'fixed_plan_group_violations_are_diagnostics': True,
        'optimizer_calls': 0, 'LO_calls': 0, 'model_calls': 0,
        'qualified': False, 'task_count': 0})


def validate(output):
    output = Path(output).resolve(strict=True)
    frozen = json.loads((output / 'preparation.json').read_text())
    for record in frozen['recipe'].values():
        spec.require(reference(record['path']) == record, 'A financial crosscheck recipe changed')
    raw = read(frozen['raw_preparation'])
    public = spec.load_spec(read(raw['specification']))
    spec.require(public['dimension_mode'] == 'production'
        and raw['specification_sha256'] == spec.canonical_sha256(public), 'The raw universe changed')
    for path, digest in raw['recipe_sha256'].items():
        spec.require(reference(path)['sha256'] == digest, 'An original raw recipe changed')
    spec.require(frozen['diagnostic_plan_ids'] == [row['id'] for row in raw['diagnostic_plans']],
        'The complete predeclared diagnostic inventory changed')
    return frozen, raw, public


def execute(output):
    from sheets_factory.workbook.linear_capital_portfolio import (
        candidate_a, ledger, finance_crosscheck, model_a, model_b)
    output = Path(output).absolute()
    frozen, raw, public = validate(output)
    spec.require(not (output / 'started.json').exists(), 'Preserve the first actual finance attempt')
    lease = ProducerLease(output).acquire()
    audit = server = thread = None
    stop = threading.Event()
    started = time.monotonic()
    stage = 'starting'
    records = {}
    failure = None
    try:
        audit = AuditStore(output / 'audit', {'id': output.name, 'name': 'Independent project financial crosscheck',
            'status': 'running', 'target_count': 0, 'producer_pid': os.getpid(), 'producer_active': True})
        server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=0)
        url = server.start()
        records['started'] = write(output / 'started.json', {'preparation': reference(output / 'preparation.json'),
            'started_at': datetime.now(timezone.utc).isoformat(), 'dashboard_url': url, 'producer_pid': os.getpid()})
        audit.update_run(dashboard_url=url)
        print(json.dumps({'dashboard_url': url, 'output': str(output)}), flush=True)

        def heartbeat():
            while not stop.wait(5):
                audit.update_run(active_stage=stage, elapsed_seconds=time.monotonic() - started)
                audit.export()

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()

        def run(name, operation):
            nonlocal stage
            stage = name
            tick = time.monotonic()
            audit.update_run(active_stage=name)
            audit.emit('financial_crosscheck.stage_started', stage=name)
            value = operation()
            records[name] = write(output / (name + '.json'), value)
            audit.record('nodes', {'node': name, 'status': 'completed',
                'duration_ms': (time.monotonic() - tick) * 1000, 'receipt': records[name]})
            audit.emit('financial_crosscheck.stage_completed', stage=name, receipt=records[name])
            audit.export()
            print(json.dumps({'completed_stage': name, 'receipt': records[name]}), flush=True)
            return value

        a = run('Fraction_A_universe', lambda: candidate_a.simulate_universe(public))
        b = run('Decimal_B_universe', lambda: ledger.simulate_universe(public))
        comparison = run('complete_financial_comparison', lambda: finance_crosscheck.compare_universes(public, a, b))
        spec.require(comparison['passed'] is True, 'Independent financial postings differ or source feasibility fails')
        probes = run('all_predeclared_plan_comparison',
            lambda: finance_crosscheck.compare_plans(public, a, b, raw['diagnostic_plans']))
        spec.require(probes['passed'] is True, 'The complete fixed-plan portfolio results differ')
        ma = run('model_A', lambda: model_a.build_model(public, a))
        mb = run('model_B', lambda: model_b.build_model(public, b))
        # Distinct universe metadata has intentionally distinct hashes. All
        # optimization coefficients, capacities, row identities and objective
        # values must agree exactly, without comparing those metadata hashes.
        numerical_keys = ('kind', 'version', 'project_ids', 'objective_pence', 'rows', 'specification_sha256')
        differences = [key for key in numerical_keys if ma[key] != mb[key]]
        matrix_comparison = run('complete_matrix_comparison', lambda: {
            'passed': not differences, 'different_sections': differences,
            'project_count': len(ma['project_ids']), 'all_business_rows': len(ma['rows']),
            'all_integer_coefficients_compared': len(ma['rows']) * len(ma['project_ids']),
            'distinct_universe_metadata_hashes_allowed': True})
        spec.require(matrix_comparison['passed'], 'The independently compiled integer models differ')
        validate(output)
    except BaseException as error:
        failure = error
        records['failure'] = write(output / 'failure.json', {'stage': stage, 'error_type': type(error).__name__,
            'error': str(error), 'traceback': traceback.format_exc()})
    finally:
        stop.set()
        if thread:
            thread.join(timeout=1)
        terminal = write(output / 'terminal.json', {
            'kind': 'linear_capital_full_financial_crosscheck', 'version': 1,
            'passed': failure is None, 'completed_at': datetime.now(timezone.utc).isoformat(),
            'elapsed_seconds': time.monotonic() - started, 'records': records,
            'host_financial_computation': True, 'container_resource_claimed': False,
            'optimizer_calls': 0, 'LO_calls': 0, 'model_calls': 0,
            'source_admission_or_quality_or_difficulty_certified': False,
            'qualified': False, 'task_count': 0})
        if audit:
            audit.update_run(status='passed' if failure is None else 'failed', producer_active=False,
                terminal_receipt=terminal, elapsed_seconds=time.monotonic() - started)
            audit.export()
        if server:
            server.stop()
        if audit:
            audit.db.close()
        lease.release()
    print(json.dumps({'terminal': terminal, 'passed': failure is None}), flush=True)
    if failure is not None:
        raise RuntimeError('Financial crosscheck failed; preserve ' + terminal['path']) from failure
    return terminal


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('prepare')
    command.add_argument('--raw-preparation', required=True, type=Path)
    command.add_argument('--output', required=True, type=Path)
    command = commands.add_parser('run')
    command.add_argument('--prepared', required=True, type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        print(json.dumps(prepare(args.raw_preparation, args.output)), flush=True)
    else:
        execute(args.prepared)
