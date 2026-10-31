"""Prospective, bounded diagnostics for explicitly supplied common plans.

Preparation starts no process and performs no financial calculation. Explicit
execution reuses A and B independently, then checks each outcome against the
Decimal forward journal. It does not search, rank, or certify an optimum.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time
import traceback
from uuid import uuid4

from ...core.audit import AuditStore, utcnow
from ...dashboard import DashboardServer
from ...resume import ProducerLease
from . import ledger, search_a, search_b, spec as schema

ROOT = Path(__file__).resolve().parent
MAX_PLANS = 256
KIND = 'prepared_scaled_capital_fixed_plan_diagnostics'
RECORD = struct.Struct(schema.RECORD_FORMAT)
MECHANISM_FIELDS = (
    'capex', 'sale_proceeds', 'depreciation', 'bank_interest', 'loss_created',
    'loss_used', 'loss_expired', 'current_tax', 'mandatory_margin',
    'optional_repayment', 'bank_draw', 'lp_call', 'funding_gap',
    'distribution', 'return_of_capital', 'profit_distribution',
)


def reference(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(2**20), b''):
            digest.update(block)
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}


def _checked(ref):
    schema.require(isinstance(ref, dict) and set(ref) == {'path', 'sha256', 'bytes'},
                   'A complete path/SHA/bytes reference is required')
    schema.require(reference(ref['path']) == ref, 'Frozen fixed-plan artifact changed: ' + str(ref['path']))
    return Path(ref['path'])


def _write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return reference(path)


def _read(ref):
    return json.loads(_checked(ref).read_text(encoding='utf-8'))


def _recipe():
    paths = [Path(__file__), ROOT / 'fixed_plan_probe_a.cpp', ROOT / 'fixed_plan_probe_b.cpp',
             Path(search_a.__file__), search_a.SOURCE, Path(search_b.__file__), search_b.KERNEL,
             Path(schema.__file__), Path(ledger.__file__), Path(ledger.original.__file__),
             Path(ledger.original_spec.__file__)]
    return {str(path.resolve()): reference(path) for path in paths}


def _plans(public, value):
    schema.require(type(value) is list and 1 <= len(value) <= MAX_PLANS,
                   'Supply an ordered list of one to 256 explicit fixed plans')
    ids = [project['id'] for project in public['projects']]
    names, result = set(), []
    for row in value:
        schema.require(type(row) is dict and set(row) == {'id', 'plan'},
                       'Each fixed plan requires only id and complete plan')
        name, plan = row['id'], row['plan']
        schema.require(type(name) is str and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}', name)
                       and name not in names, 'Fixed-plan labels must be distinct, stable safe names')
        schema.require(type(plan) is dict and set(plan) == set(ids),
                       'A fixed plan must explicitly contain every public project')
        schema.require(all(type(plan[key]) is int and plan[key] in (0, 1) for key in ids),
                       'Fixed-plan choices must be integer zero or one')
        names.add(name)
        result.append({'id': name, 'plan': {key: plan[key] for key in ids},
                       'mask': sum(plan[key] << bit for bit, key in enumerate(ids))})
    return result


def _mask_wire(plans):
    return 'CAPITAL_EXPLICIT_FIXED_MASKS_V1\n' + str(len(plans)) + '\n' + ''.join(
        str(row['mask']) + '\n' for row in plans)


def prepare(public_spec, plans, output):
    """Freeze an ordered explicit plan list, with zero process/finance calls."""
    public = schema.load_spec(public_spec)
    declared = _plans(public, plans)
    output = Path(output).absolute()
    schema.require(not output.exists() and not output.is_symlink(),
                   'Fixed-plan preparation requires a fresh output directory')
    output.mkdir(parents=True)
    public_ref = _write(output / 'public_spec.json', public)
    plans_ref = _write(output / 'declared_plans.json', declared)
    wires = {'A': search_a.raw_primitives(public, list(range(len(public['projects'])))),
             'B': search_b.raw_wire(public, None)}
    wire_refs = {}
    for name, text in wires.items():
        path = output / (name + '_raw_primitives.txt')
        with path.open('x', encoding='utf-8') as stream:
            stream.write(text)
        wire_refs[name] = reference(path)
    masks = output / 'explicit_masks.txt'
    with masks.open('x', encoding='utf-8') as stream:
        stream.write(_mask_wire(declared))
    return _write(output / 'preparation.json', {
        'kind': KIND, 'version': 1, 'created_at': utcnow(), 'public_specification': public_ref,
        'spec_sha256': schema.canonical_sha(public), 'declared_plans': plans_ref,
        'plan_count': len(declared), 'project_count': len(public['projects']),
        'raw_wires': wire_refs, 'explicit_masks': reference(masks), 'recipe': _recipe(),
        'compiler_calls': 0, 'kernel_calls': 0, 'Decimal_forward_calls': 0,
        'enumeration_performed': False, 'ranking_performed': False,
        'global_optimum_claimed': False, 'LO_calls': 0, 'model_calls': 0,
        'qualified': False, 'task_count': 0})


def validate_prepared(output):
    """Read all frozen primitives and reproduce both serialization-only wires."""
    if isinstance(output, dict):
        ref = output
    else:
        path = Path(output)
        ref = reference(path / 'preparation.json' if path.is_dir() else path)
    frozen = _read(ref)
    schema.require(frozen.get('kind') == KIND and frozen.get('version') == 1,
                   'An explicit fixed-plan preparation is required')
    schema.require(frozen.get('recipe') == _recipe(), 'Fixed-plan code or its frozen financial cores changed')
    public = schema.load_spec(_read(frozen['public_specification']))
    original = _read(frozen['declared_plans'])
    schema.require(type(original) is list and all(type(row) is dict and set(row) == {'id', 'plan', 'mask'}
                                                for row in original), 'Malformed declared fixed plans')
    declared = _plans(public, [{'id': row['id'], 'plan': row['plan']} for row in original])
    schema.require(declared == original and frozen['plan_count'] == len(declared)
                   and frozen['project_count'] == len(public['projects'])
                   and frozen['spec_sha256'] == schema.canonical_sha(public),
                   'Fixed-plan counts, masks or specification identity changed')
    wires = {'A': search_a.raw_primitives(public, list(range(len(public['projects'])))),
             'B': search_b.raw_wire(public, None)}
    for name, expected in wires.items():
        schema.require(_checked(frozen['raw_wires'][name]).read_text(encoding='utf-8') == expected,
                       'Fixed-plan raw primitive wire differs from its public specification')
    schema.require(_checked(frozen['explicit_masks']).read_text(encoding='utf-8') == _mask_wire(declared),
                   'Explicit masks differ from the declared complete plans')
    return frozen, public, declared


def _process(command, directory, environment, timeout):
    directory.mkdir()
    started, clock = utcnow(), time.monotonic()
    result, error = None, None
    try:
        with (directory / 'stdout.txt').open('x') as stdout, (directory / 'stderr.txt').open('x') as stderr:
            result = subprocess.run(command, stdout=stdout, stderr=stderr,
                                    env=environment, timeout=timeout, check=False)
    except BaseException as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    receipt = _write(directory / 'process.json', {
        'started_at': started, 'completed_at': utcnow(), 'elapsed_seconds': time.monotonic() - clock,
        'command': command, 'timeout_seconds': timeout,
        'returncode': result.returncode if result is not None else None, 'error': error,
        'stdout': reference(directory / 'stdout.txt'), 'stderr': reference(directory / 'stderr.txt')})
    schema.require(error is None and result.returncode == 0,
                   'Fixed-plan process failed; original logs and terminal receipt are preserved: ' + receipt['path'])
    return receipt


def _records(ref, declared):
    path = _checked(ref)
    schema.require(path.stat().st_size == len(declared) * RECORD.size, 'Incomplete explicit fixed-plan record stream')
    result = []
    with path.open('rb') as stream:
        for row in declared:
            mask, flags, *npvs = RECORD.unpack(stream.read(RECORD.size))
            schema.require(mask == row['mask'] and 0 <= flags <= 7,
                           'Fixed-plan records must preserve the declared mask order')
            schema.require(all((value != schema.NULL_NPV) == bool(flags & (1 << index))
                               for index, value in enumerate(npvs)),
                           'Fixed-plan feasibility and null NPV encoding disagree')
            result.append((mask, flags, npvs))
    return result


def _dated_observations(forward):
    """Describe actual positive postings, without requiring a source to trigger them."""
    return {sid: {field: [{'year': row['year'], 'amount_pence': row[field]}
                         for row in state['annual'] if row[field] > 0]
                  for field in MECHANISM_FIELDS}
            for sid, state in forward['scenarios'].items()}


def execute_prepared(output, *, timeout_seconds=120, port=0):
    """Compile two separate wrappers and evaluate only the declared fixed plans."""
    schema.require(type(timeout_seconds) is int and 1 <= timeout_seconds <= 600,
                   'Fixed-plan process timeout must be one to 600 seconds')
    frozen, public, declared = validate_prepared(output)
    output = Path(frozen['public_specification']['path']).parent
    attempt = output / 'attempts' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:12])
    lease = ProducerLease(output).acquire()
    attempt.mkdir(parents=True)
    audit = AuditStore(attempt, {'id': attempt.name, 'kind': 'scaled_capital_fixed_plan_diagnostics',
        'target_count': 0, 'task_count': 0, 'qualified': 0, 'declared_plan_count': len(declared)})
    server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port)
    clock, phase, result_refs = time.monotonic(), 'startup', {}
    try:
        temporary = attempt / 'temporary'; temporary.mkdir()
        schema.require(temporary.resolve().is_relative_to(output.resolve()), 'Fixed-plan temporary files must stay in this run')
        environment = {**os.environ, 'TMPDIR': str(temporary.resolve())}
        url = server.start()
        audit.update_run(status='compiling', producer_pid=os.getpid(), producer_active=True, dashboard_url=url)
        started = _write(attempt / 'started.json', {'kind': 'started_scaled_capital_fixed_plan_diagnostics',
            'started_at': utcnow(), 'preparation': reference(output / 'preparation.json'),
            'dashboard_url': url, 'producer_pid': os.getpid(), 'recipe': frozen['recipe'],
            'plan_count': len(declared), 'temporary_directory': str(temporary.resolve()),
            'full_enumeration': False, 'global_optimum_claimed': False,
            'LO_calls': 0, 'model_calls': 0, 'qualified': False, 'task_count': 0})
        audit.emit('fixed_plan.started', started=started); audit.export()
        compiler = shutil.which('g++')
        schema.require(compiler is not None, 'Fixed-plan native diagnostics require g++')
        binaries, compilations = {}, {}
        for name in ('A', 'B'):
            phase = 'compile_' + name
            binary = attempt / ('fixed_plan_' + name)
            command = [compiler, '-std=c++17', '-O3', '-Wall', '-Wextra',
                       str(ROOT / ('fixed_plan_probe_' + name.lower() + '.cpp')), '-o', str(binary)]
            compilations[name] = _process(command, attempt / ('compile_' + name), environment, timeout_seconds)
            binaries[name] = reference(binary)
            audit.emit('fixed_plan.compiled', kernel=name, receipt=compilations[name]); audit.export()
        audit.update_run(status='evaluating')
        for name in ('A', 'B'):
            phase = 'evaluate_' + name
            records = attempt / (name + '_fixed_records.bin')
            command = [str(_checked(binaries[name])), str(_checked(frozen['raw_wires'][name])),
                       str(_checked(frozen['explicit_masks'])), str(records)]
            process = _process(command, attempt / ('evaluate_' + name), environment, timeout_seconds)
            native = json.loads(Path(_read(process)['stdout']['path']).read_text())
            schema.require(native.get('kind') == 'scaled_fixed_plan_' + name + '_native'
                           and native.get('plan_count') == len(declared)
                           and native.get('scenario_evaluations') == len(declared) * 3
                           and native.get('enumeration_performed') is False
                           and native.get('ranking_performed') is False,
                           'Native fixed-plan count or diagnostic-only contract differs')
            result_refs[name] = {'process': process, 'binary': binaries[name],
                                 'records': reference(records), 'native_statistics': native}
            audit.emit('fixed_plan.native_completed', kernel=name, result=result_refs[name]); audit.export()
        phase = 'compare_A_B_Decimal'
        audit.update_run(status='forward_validating')
        a = _records(result_refs['A']['records'], declared)
        b = _records(result_refs['B']['records'], declared)
        schema.require(result_refs['A']['records']['sha256'] == result_refs['B']['records']['sha256'] and a == b,
                       'A and B fixed-plan outcomes disagree; preserve both streams')
        checks = []
        for index, row in enumerate(declared):
            forward = ledger.simulate(public, row['plan'])
            expected_flags = sum(1 << si for si, sid in enumerate(schema.SCENARIO_IDS)
                                 if forward['scenarios'][sid]['feasible'])
            expected_values = [forward['scenarios'][sid]['npv_pence'] if forward['scenarios'][sid]['feasible']
                               else schema.NULL_NPV for sid in schema.SCENARIO_IDS]
            forward_ref = _write(attempt / ('Decimal_' + str(index).zfill(3) + '.json'), forward)
            observation_ref = _write(attempt / ('dated_' + str(index).zfill(3) + '.json'), _dated_observations(forward))
            matched = a[index] == (row['mask'], expected_flags, expected_values)
            balanced = all(state['all_journals_balance'] is True for state in forward['scenarios'].values())
            check = {'id': row['id'], 'mask': row['mask'], 'plan': row['plan'],
                     'ledger': forward_ref, 'dated_positive_postings': observation_ref,
                     'A_B_Decimal_match': matched, 'all_journals_balance': balanced,
                     'feasible': forward['feasible'], 'objective_pence': forward['objective_pence'],
                     'scenario_npvs_pence': {sid: state['npv_pence'] for sid, state in forward['scenarios'].items()}}
            checks.append(check)
            audit.emit('fixed_plan.forward_checked', id=row['id'], matched=matched, balanced=balanced); audit.export()
            schema.require(matched and balanced, 'Fixed-plan Decimal journal disagrees: ' + row['id'])
        validate_prepared(output)
        terminal = _write(attempt / 'receipt.json', {'kind': 'scaled_capital_explicit_fixed_plan_diagnostics',
            'version': 1, 'status': 'completed', 'passed': True, 'started': started,
            'completed_at': utcnow(), 'elapsed_seconds': time.monotonic() - clock,
            'preparation': reference(output / 'preparation.json'), 'public_specification': frozen['public_specification'],
            'spec_sha256': frozen['spec_sha256'], 'declared_plans': frozen['declared_plans'],
            'plan_count': len(declared), 'project_count': len(public['projects']),
            'compilations': compilations, 'kernel_results': result_refs, 'checks': checks,
            'all_declared_plans_checked': True, 'records_equal_complete_for_declared_list': True,
            'Decimal_scenario_year_evaluations': len(declared) * 3 * len(schema.YEARS),
            'recipe': frozen['recipe'], 'enumeration_performed': False, 'ranking_performed': False,
            'global_optimum_claimed': False, 'financial_source_admission_claimed': False,
            'LO_calls': 0, 'model_calls': 0, 'qualified': False, 'task_count': 0})
        audit.update_run(status='completed', terminal_receipt=terminal, elapsed_seconds=time.monotonic() - clock)
        audit.emit('fixed_plan.completed', receipt=terminal)
        return terminal
    except BaseException as error:
        failure = _write(attempt / 'failure.json', {'kind': 'scaled_capital_fixed_plan_diagnostics_failure',
            'status': 'failed', 'phase': phase, 'completed_at': utcnow(),
            'elapsed_seconds': time.monotonic() - clock, 'preparation': reference(output / 'preparation.json'),
            'error_type': type(error).__name__, 'error': str(error), 'traceback': traceback.format_exc(),
            'kernel_results': result_refs, 'global_optimum_claimed': False,
            'qualified': False, 'task_count': 0, 'LO_calls': 0, 'model_calls': 0})
        audit.update_run(status='failed', failure=failure)
        audit.emit('fixed_plan.failed', failure=failure)
        raise
    finally:
        audit.update_run(producer_active=False, finished_at=utcnow())
        audit.export()
        lease.release()
        server.stop()
        audit.db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec')
    parser.add_argument('--plans', help='JSON ordered list of id/complete-plan objects')
    parser.add_argument('--output', required=True)
    parser.add_argument('--run', action='store_true', help='Explicitly execute the already prepared bounded diagnostics')
    args = parser.parse_args(argv)
    if args.run:
        schema.require(args.spec is None and args.plans is None, 'Execution consumes an existing preparation only')
        result = execute_prepared(args.output)
    else:
        schema.require(args.spec is not None and args.plans is not None, 'Preparation requires --spec and --plans')
        result = prepare(args.spec, json.loads(Path(args.plans).read_text()), args.output)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
