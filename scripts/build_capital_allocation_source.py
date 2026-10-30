#!/usr/bin/env python3
"""Prepare one capital-allocation source; actual calculation requires --run.

Preparation never searches, recalculates, or writes a winning decision. A
separately completed exhaustive-search certificate is required for execution.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import openpyxl
from sheets_factory.task_adapters.public_workbook_scope import checked_bytes, reference, require, write_new
from sheets_factory.task_adapters.lease_family import compare_exact_typed
from sheets_factory.workbook.capital_allocation.excel import emit_capital_allocation_workbook
from sheets_factory.workbook.capital_allocation.ledger import simulate
from sheets_factory.workbook.capital_allocation.spec import RAW_ANCESTORS, load_spec, validate_plan
from sheets_factory.workbook.capital_allocation.validate import audit_capital_allocation_workbook
from sheets_factory.workbook.engine import LibreOfficeEngine
from sheets_factory.core.audit import AuditStore, utcnow
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease

IMAGE = 'sheetsfactory-lo:24.2-iterative-openpyxl315-v1'
IMAGE_ID = 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
KIND = 'prepared_single_hypothetical_capital_allocation_source'


def read(record):
    value = json.loads(checked_bytes(record))
    require(isinstance(value, dict), 'A source receipt must contain a JSON object')
    return value


def recipes():
    directory = ROOT / 'src/sheets_factory/workbook/capital_allocation'
    paths = [Path(__file__).resolve(), ROOT / 'src/sheets_factory/workbook/engine.py',
             ROOT / 'src/sheets_factory/task_adapters/lease_family.py',
             ROOT / 'src/sheets_factory/core/audit.py', ROOT / 'src/sheets_factory/dashboard/server.py',
             ROOT / 'src/sheets_factory/resume.py']
    paths.extend(path for path in sorted(directory.iterdir()) if path.suffix in ('.py', '.cpp'))
    return {str(path.resolve()): reference(path)['sha256'] for path in paths}


def check_recipes(expected):
    require(expected == recipes(), 'The frozen capital-allocation execution recipe changed')


def _track_references(value):
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            checked_bytes(value)
        for child in value.values(): _track_references(child)
    elif isinstance(value, list):
        for child in value: _track_references(child)


def validate_independent_optimum(spec, proof, independent_verification):
    """Require complete raw-spec replay, not merely a matching winning NPV."""
    record = reference(independent_verification)
    verified = read(record); _track_references(verified)
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode()).hexdigest()
    require(verified.get('passed') is True and verified.get('full_enumeration') is True
            and verified.get('toy_only') is False and verified.get('unique_best') is True
            and type(verified.get('plan_count')) is int and verified['plan_count'] == 2**18
            and type(verified.get('scenario_year_evaluations')) is int
            and verified['scenario_year_evaluations'] == 2**18 * 3 * 20
            and type(verified.get('gap_pence')) is int and verified['gap_pence'] >= 1
            and type(verified.get('objective_pence')) is int,
            'A complete independent eighteen-bit state-path verification is required')
    require(proof.get('verification') == record
            and verified.get('spec_sha256') == proof.get('spec_sha256') == digest
            and read(verified['public_spec']) == spec
            and verified.get('best_plan') == proof.get('best_plan')
            and verified.get('objective_pence') == proof.get('objective_pence')
            and verified.get('cpp_plans') == proof.get('plans_csv')
            and verified['cpp_plans']['sha256'] == verified['python_plans']['sha256']
            and verified['cpp_plans']['bytes'] == verified['python_plans']['bytes'],
            'The independent enumeration does not bind this exact public spec, result CSV and unique best plan')
    implementation = reference(ROOT / 'src/sheets_factory/workbook/capital_allocation/verify.py')
    require(verified.get('implementation') == implementation, 'The independent verification implementation changed')
    return record


@contextmanager
def source_phase(audit, identity):
    started = time.monotonic()
    audit.task('capital-allocation-source', mode='source_build', status='running', node=identity)
    node = audit.record('nodes', {'task_id': 'capital-allocation-source', 'revision': 0,
        'node_id': identity, 'status': 'running', 'started_at': utcnow(), 'model_calls': 0, 'tokens': 0})
    audit.emit('source.phase.started', node_id=identity, model_calls=0, tokens=0)
    try:
        yield
    except BaseException as error:
        duration = round((time.monotonic() - started) * 1000)
        audit.update_record('nodes', node, {'status': 'failed', 'duration_ms': duration,
            'error_type': type(error).__name__, 'error': str(error)})
        audit.emit('source.phase.failed', node_id=identity, duration_ms=duration, error=str(error))
        raise
    else:
        duration = round((time.monotonic() - started) * 1000)
        audit.update_record('nodes', node, {'status': 'completed', 'duration_ms': duration})
        audit.emit('source.phase.completed', node_id=identity, duration_ms=duration, model_calls=0, tokens=0)


@contextmanager
def data_temporary(output):
    directory = Path(output).absolute() / 'temporary'
    require(directory == directory.resolve(), 'The source temporary directory cannot use symlinks')
    directory.mkdir(parents=True, exist_ok=True)
    previous, existed, previous_cache = os.environ.get('TMPDIR'), 'TMPDIR' in os.environ, tempfile.tempdir
    try:
        os.environ['TMPDIR'] = str(directory); tempfile.tempdir = str(directory)
        with tempfile.TemporaryFile(dir=directory) as stream: stream.write(b'capital-allocation-write-check')
        yield directory
    finally:
        if existed: os.environ['TMPDIR'] = previous
        else: os.environ.pop('TMPDIR', None)
        tempfile.tempdir = previous_cache


def prepare(specification, output, raw_ancestors):
    output = Path(output).absolute()
    require(output == output.resolve() and not output.exists(), 'Use a fresh non-symlink source directory')
    spec_ref = reference(specification); spec = load_spec(json.loads(checked_bytes(spec_ref)))
    require(set(raw_ancestors) == set(RAW_ANCESTORS), 'Both original raw ancestors must be explicitly supplied')
    ancestry = {name: reference(path) for name, path in raw_ancestors.items()}
    require(all(ancestry[name]['sha256'] == digest for name, digest in RAW_ANCESTORS.items()),
            'A raw ancestor differs from its immutable original hash')
    frozen_recipe = recipes()
    output.mkdir(parents=True)
    with data_temporary(output):
        public_spec = write_new(output / 'public/spec.json', spec)
        book = openpyxl.Workbook(); book.remove(book.active)
        try:
            binding = emit_capital_allocation_workbook(book, spec)
            template = output / 'public/template.xlsx'
            book.save(template)
        finally: book.close()
        binding_ref = write_new(output / 'private/template_bindings.json', binding)
        require(binding['gold_plan_supplied'] is False and len(binding['decision_bindings']) == 18,
                'Preparation cannot provide a winning investment plan')
        check_recipes(frozen_recipe)
        return write_new(output / 'preparation.json', {'kind': KIND, 'version': 1,
            'specification': spec_ref, 'public_specification': public_spec, 'public_template': reference(template),
            'template_bindings': binding_ref, 'raw_ancestors': ancestry, 'recipe_sha256': frozen_recipe,
            'source_ancestor_unique_count': 2, 'hypothetical_forecasts_and_policy': True,
            'unchanged_original_source_claimed': False, 'decision_count': 18, 'scenario_count': 3, 'year_count': 20,
            'winning_plan_written': False, 'actual_LO_recalculations': 0, 'actual_enumerated_plans': 0,
            'model_calls': 0, 'quality_or_difficulty_certified': False, 'qualified': False, 'task_count': 0})


def validate_prepared(output):
    output = Path(output).absolute()
    require(output == output.resolve(), 'A source directory cannot use symlinks')
    frozen = read(reference(output / 'preparation.json'))
    require(frozen.get('kind') == KIND and type(frozen.get('version')) is int and frozen['version'] == 1
            and frozen.get('decision_count') == 18 and frozen.get('scenario_count') == 3
            and frozen.get('year_count') == 20 and frozen.get('winning_plan_written') is False
            and frozen.get('actual_LO_recalculations') == frozen.get('actual_enumerated_plans') == frozen.get('model_calls') == 0,
            'An unchanged zero-call source preparation is required')
    check_recipes(frozen['recipe_sha256'])
    spec = load_spec(read(frozen['specification']))
    require(read(frozen['public_specification']) == spec, 'The public specification differs')
    for name, record in frozen['raw_ancestors'].items():
        checked_bytes(record)
        require(RAW_ANCESTORS.get(name) == record['sha256'], 'A raw ancestor changed')
    require(set(frozen['raw_ancestors']) == set(RAW_ANCESTORS), 'Original provenance is incomplete')
    checked_bytes(frozen['public_template']); binding = read(frozen['template_bindings'])
    require(binding['public_spec'] == spec and binding['gold_plan_supplied'] is False
            and all(item.get('target_eligible') is False for item in binding['arithmetic_bindings']),
            'The prepared template or its arithmetic-support scope changed')
    return frozen, spec


def _execute_prepared(output, certificate, independent_verification, frozen, spec, attempt, audit):
    """Use a separately verified complete optimum; never start a search here."""
    from sheets_factory.workbook.capital_allocation.search import validate_certificate
    with source_phase(audit, 'complete_optimisation_proof'):
        certificate_ref = reference(certificate)
        proof = validate_certificate(certificate_ref, spec)
        require(isinstance(proof, dict) and proof.get('unique_best') is True
                and type(proof.get('plan_count')) is int and proof['plan_count'] == 2**18
                and type(proof.get('gap_pence')) is int and proof['gap_pence'] >= 1
                and type(proof.get('objective_pence')) is int,
                'The complete eighteen-decision unique-best proof is required')
        verification_ref = validate_independent_optimum(spec, proof, independent_verification)
        plan = validate_plan(proof['best_plan'])
    with source_phase(audit, 'independent_forward_journal'):
        ledger = simulate(spec, plan)
        require(ledger['feasible'] is True and ledger['objective_pence'] == proof['objective_pence'],
                'The independently posted winning forecast differs from the exhaustive-search proof')
    calls, started = [], time.monotonic()
    try:
        with data_temporary(output):
            private_ledger = write_new(attempt / 'independent_ledger.json', ledger)
            proof_ref = write_new(attempt / 'validated_search_proof.json', proof)
            with source_phase(audit, 'emit_forward_financial_workbook'):
                book = openpyxl.Workbook(); book.remove(book.active)
                try:
                    binding = emit_capital_allocation_workbook(book, spec, plan)
                    raw = attempt / 'raw_goal.xlsx'; book.save(raw)
                finally: book.close()
            binding_ref = write_new(attempt / 'bindings.json', binding)
            engine = LibreOfficeEngine(ROOT, IMAGE, 300)
            require(engine.ensure_image() == IMAGE_ID, 'The source requires the exact pinned financial runtime')
            runtime = engine.metadata()
            require(runtime.get('image_id') == IMAGE_ID and runtime.get('network') == 'none', 'The actual runtime differs')
            current, audits, versions = raw, [], []
            for index in range(3):
                destination = attempt / ('calculated_pass' + str(index + 1) + '.xlsx')
                call_started = time.monotonic()
                call = {'index': index + 1, 'input': reference(current), 'destination': str(destination),
                    'started_at': utcnow(), 'completed': False, 'image_id': IMAGE_ID, 'network': 'none'}
                calls.append(call)
                call['started_receipt'] = write_new(attempt / ('engine_call' + str(index + 1) + '_started.json'), call)
                with source_phase(audit, 'actual_LO_pass' + str(index + 1)):
                    try:
                        actual = engine.recalculate(current, destination)
                        call.update(output=reference(actual), completed=True)
                    except BaseException as error:
                        call.update(exception_type=type(error).__name__, error=str(error))
                        raise
                    finally:
                        call['seconds'] = time.monotonic() - call_started
                        call['terminal_receipt'] = write_new(attempt / ('engine_call' + str(index + 1) + '_terminal.json'), call)
                with source_phase(audit, 'independent_financial_audit_pass' + str(index + 1)):
                    financial_audit = audit_capital_allocation_workbook(actual, spec, plan, ledger, binding)
                    audits.append(write_new(attempt / ('financial_audit_pass' + str(index + 1) + '.json'),
                        {'workbook': reference(actual), **financial_audit}))
                    require(financial_audit['passed'], 'Actual source financial formulas or public primitives failed their independent audit')
                versions.append(actual); current = actual
            stability = {'first_against_goal': compare_exact_typed(versions[0], versions[1]),
                         'second_against_goal': compare_exact_typed(versions[0], versions[2])}
            stability['stable'] = all(row['passed'] for row in stability.values())
            stability_ref = write_new(attempt / 'stability.json', stability)
            require(stability['stable'], 'The complete actual financial source is not stable in both further recalculations')
            validate_prepared(output); checked_bytes(certificate_ref); checked_bytes(verification_ref)
            _track_references(proof); _track_references(read(verification_ref))
            manifest = {'kind': 'independently_verified_hypothetical_capital_allocation_source', 'version': 1,
                'status': 'source_verified_not_task_or_difficulty_qualified', 'local_path': str(versions[0]),
                'derived_workbook_sha256': reference(versions[0])['sha256'], 'workbook': reference(versions[0]),
                'public_specification': frozen['public_specification'], 'raw_ancestors': frozen['raw_ancestors'],
                'source_ancestor_unique_count': 2, 'hypothetical_forecasts_and_policy': True,
                'source_preparation': reference(output / 'preparation.json'), 'search_certificate': certificate_ref,
                'independent_complete_enumeration': verification_ref,
                'validated_search_proof': proof_ref, 'independent_ledger': private_ledger, 'bindings': binding_ref,
                'financial_audit_passed': True, 'financial_audits': audits, 'stability': stability_ref,
                'runtime': runtime, 'engine_calls': calls, 'actual_LO_recalculations': len(calls),
                'model_calls': 0, 'source_recipe_sha256': frozen['recipe_sha256'],
                'five_controls_recovery_quality_Harbor_pending': True, 'quality_or_difficulty_certified': False,
                'task_input_and_complete_D_not_built': True,
                'plan_dependent_helper_caches_require_clearing_and_actual_input_recalculation': True,
                'complete_required_D_must_include_changed_arithmetic_helpers': True,
                'qualified': False, 'task_count': 0}
            receipt = write_new(output / 'seed_manifest.json', manifest)
            write_new(attempt / 'terminal.json', {'status': 'source_verified', 'manifest': receipt, 'calls': calls,
                'seconds': time.monotonic() - started, 'engineering_time_excluded_from_solver_trial': True})
            return receipt
    except BaseException as error:
        write_new(attempt / 'terminal.json', {'status': 'failed', 'exception_type': type(error).__name__,
            'error': str(error), 'calls': calls, 'seconds': time.monotonic() - started,
            'all_partial_artifacts_preserved': True, 'qualified': False, 'task_count': 0})
        raise


def execute_prepared(output, certificate, independent_verification, *, port=0):
    output = Path(output).absolute(); frozen, spec = validate_prepared(output)
    lease = ProducerLease(output).acquire()
    attempt = output / 'private/build_attempts' / uuid.uuid4().hex
    audit, server, status, started = None, None, 'failed', time.monotonic()
    try:
        require(not (output / 'seed_manifest.json').exists(), 'An actual source already exists; never overwrite it')
        attempt.mkdir(parents=True)
        audit = AuditStore(attempt / 'audit', {'id': attempt.name, 'name': 'Capital allocation source engineering',
            'target_count': 0, 'status': 'running', 'producer_pid': os.getpid(), 'producer_active': True,
            'model_calls': 0, 'tokens': 0, 'quality_or_difficulty_certified': False})
        server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port)
        url = server.start(); audit.update_run(dashboard_url=url)
        print(json.dumps({'dashboard_url': url, 'source_attempt': str(attempt), 'model_calls': 0, 'tokens': 0}), flush=True)
        result = _execute_prepared(output, certificate, independent_verification, frozen, spec, attempt, audit)
        status = 'source_verified'
        audit.task('capital-allocation-source', mode='source_build', status=status, node='completed')
        return result
    except BaseException as error:
        if attempt.exists() and not (attempt / 'terminal.json').exists():
            write_new(attempt / 'terminal.json', {'status': 'failed', 'exception_type': type(error).__name__,
                'error': str(error), 'model_calls': 0, 'qualified': False, 'task_count': 0})
        raise
    finally:
        try:
            if audit is not None:
                audit.update_run(status=status, producer_active=False, wall_seconds=time.monotonic() - started)
                audit.export()
        finally:
            try:
                if server is not None: server.stop()
            finally:
                try:
                    if audit is not None: audit.db.close()
                finally: lease.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path); parser.add_argument('--output', type=Path)
    parser.add_argument('--ancestor', action='append', default=[], metavar='NAME=PATH')
    parser.add_argument('--prepared', type=Path); parser.add_argument('--certificate', type=Path)
    parser.add_argument('--independent-verification', type=Path)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    if args.prepared:
        require(not args.spec and not args.output and not args.ancestor, 'Choose one fresh preparation or an existing preparation')
        if args.run:
            require(args.certificate is not None and args.independent_verification is not None,
                    'Complete search and independent enumeration receipts are required')
            result = execute_prepared(args.prepared, args.certificate, args.independent_verification, port=args.port)
        else:
            require(args.certificate is None and args.independent_verification is None, 'Certificate consumption requires explicit --run')
            validate_prepared(args.prepared); result = {'validated': str(args.prepared), 'LO_calls': 0, 'search_calls': 0}
    else:
        require(not args.run and args.spec and args.output and not args.certificate and not args.independent_verification,
                'Prepare first; actual execution requires explicit --prepared --run')
        ancestors = {}
        for argument in args.ancestor:
            require('=' in argument, 'An ancestor must use NAME=PATH')
            name, path = argument.split('=', 1)
            require(name not in ancestors, 'Duplicate raw ancestor')
            ancestors[name] = Path(path)
        result = prepare(args.spec, args.output, ancestors)
    print(json.dumps(result, indent=2)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
