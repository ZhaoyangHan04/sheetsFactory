#!/usr/bin/env python3
"""Prepare a frozen search, then explicitly execute one complete search child."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.workbook.capital_allocation import search
from sheets_factory.workbook.capital_allocation.spec import PROJECT_IDS, load_spec

KIND = 'prepared_single_full_capital_allocation_search'
MODULE = 'sheets_factory.workbook.capital_allocation.search'
POLL_SECONDS = 1.0
reference, checked, write_new, require = search.reference, search._checked, search._write, search._require


def _now():
    return datetime.now(timezone.utc).isoformat()


def _safe_directory(value):
    directory = Path(value).absolute()
    require(directory.is_relative_to('/data') and directory != Path('/data'),
            'Search output must be a task-specific directory on /data')
    require(directory == directory.resolve() and not any(p.is_symlink() for p in (directory, *directory.parents)),
            'Search output cannot contain symbolic links')
    return directory


def recipes():
    paths = [Path(__file__).resolve(), ROOT / 'tests/test_capital_allocation_search_entry.py',
             ROOT / 'tests/test_capital_allocation_search.py', search.CPP, Path(search.__file__),
             search.DIRECTORY / 'verify.py', search.DIRECTORY / 'spec.py',
             ROOT / 'src/sheets_factory/core/audit.py', ROOT / 'src/sheets_factory/dashboard/server.py',
             ROOT / 'src/sheets_factory/resume.py']
    return {str(path.resolve()): reference(path) for path in paths}


def prepare(specification, output):
    output = _safe_directory(output)
    require(not output.exists(), 'Search preparation requires a fresh directory')
    source = reference(specification)
    spec = load_spec(checked(source))
    recipe = recipes()
    output.mkdir(parents=True)
    public = output / 'public_spec.json'
    public.write_bytes(checked(source).read_bytes())
    frozen = {
        'kind': KIND, 'version': 1, 'prepared_at': _now(), 'run_directory': str(output),
        'specification': source, 'public_specification': reference(public),
        'spec_sha256': search.canonical_spec_sha256(spec), 'recipe': recipe,
        'interpreter': reference(Path(sys.executable).resolve()),
        'execution_interpreter': sys.executable,
        'execution_module': MODULE, 'active_project_ids': list(PROJECT_IDS),
        'full_enumeration_required': True, 'expected_plan_count': 2**18,
        'expected_scenario_year_evaluations': 2**18 * 3 * 20,
        'temporary_directory': str(output / 'temporary'),
        'search_child_processes_started': 0, 'actual_enumerated_plans': 0,
        'LO_calls': 0, 'model_calls': 0, 'tokens': 0,
        'quality_or_difficulty_certified': False, 'qualified': False, 'task_count': 0,
    }
    require(recipe == recipes(), 'Search recipe changed during preparation')
    require(load_spec(checked(source)) == spec, 'Public primitives changed during preparation')
    return write_new(output / 'preparation.json', frozen)


def validate_prepared(output):
    output = _safe_directory(output)
    frozen = json.loads((output / 'preparation.json').read_text())
    require(frozen.get('kind') == KIND and type(frozen.get('version')) is int and frozen['version'] == 1
            and frozen.get('run_directory') == str(output)
            and frozen.get('recipe') == recipes()
            and frozen.get('interpreter') == reference(Path(sys.executable).resolve())
            and frozen.get('execution_interpreter') == sys.executable,
            'Prepared search identity, recipe or interpreter changed')
    spec = load_spec(checked(frozen['specification']))
    require(load_spec(checked(frozen['public_specification'])) == spec
            and frozen['public_specification']['path'] == str(output / 'public_spec.json')
            and frozen.get('spec_sha256') == search.canonical_spec_sha256(spec),
            'Prepared search public primitives changed')
    require(frozen.get('execution_module') == MODULE
            and frozen.get('active_project_ids') == list(PROJECT_IDS)
            and frozen.get('full_enumeration_required') is True
            and type(frozen.get('expected_plan_count')) is int and frozen['expected_plan_count'] == 2**18
            and type(frozen.get('expected_scenario_year_evaluations')) is int
            and frozen['expected_scenario_year_evaluations'] == 2**18 * 3 * 20
            and frozen.get('temporary_directory') == str(output / 'temporary'),
            'A prepared search must cover all eighteen choices and all three twenty-year paths')
    for key in ('search_child_processes_started', 'actual_enumerated_plans', 'LO_calls', 'model_calls', 'tokens', 'task_count'):
        require(type(frozen.get(key)) is int and frozen[key] == 0, 'Preparation must remain a zero-call artifact')
    require(frozen.get('quality_or_difficulty_certified') is False and frozen.get('qualified') is False,
            'Search preparation cannot claim task quality or difficulty')
    return frozen


@contextmanager
def data_temporary(output):
    directory = _safe_directory(output) / 'temporary'
    require(not directory.is_symlink(), 'Host temporary directory cannot be a symbolic link')
    directory.mkdir(exist_ok=True)
    previous, present, cache = os.environ.get('TMPDIR'), 'TMPDIR' in os.environ, tempfile.tempdir
    try:
        os.environ['TMPDIR'] = str(directory)
        tempfile.tempdir = str(directory)
        with tempfile.TemporaryFile(dir=directory) as stream:
            stream.write(b'capital allocation search write check')
        yield directory
    finally:
        if present:
            os.environ['TMPDIR'] = previous
        else:
            os.environ.pop('TMPDIR', None)
        tempfile.tempdir = cache


class ObservedCSV:
    """Read only appended bytes.  A newline is an observation, never a proof."""
    def __init__(self, path):
        self.path, self.offset, self.lines = Path(path), 0, 0

    def observe(self):
        if self.path.exists():
            require(self.path.stat().st_size >= self.offset, 'A search CSV was truncated during observation')
            with self.path.open('rb') as stream:
                stream.seek(self.offset)
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    self.lines += block.count(b'\n')
                self.offset = stream.tell()
        return {'observed_complete_rows': max(0, self.lines - 1), 'observed_bytes': self.offset}


def _progress(directory, cpp, python, started):
    if (directory / 'independent_verification/verification_receipt.json').exists():
        phase = 'certificate_pending'
    elif (directory / 'cpp_enumeration.json').exists():
        phase = 'independent_verification'
    else:
        phase = 'cpp_enumeration'
    return {'phase': phase, 'elapsed_seconds': round(time.monotonic() - started, 3),
            'cpp_csv': cpp.observe(), 'python_csv': python.observe(),
            'row_counts_are_observations_only': True, 'certified_complete': False,
            'expected_plan_count': 2**18, 'LO_calls': 0, 'model_calls': 0, 'tokens': 0}


def _stop_owned_child(child):
    if child is None or child.poll() is not None:
        return
    # Popen creates this dedicated process group; no existing producer joins it.
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(child.pid, sig)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            continue


def execute_prepared(output, *, port=0):
    output = _safe_directory(output)
    frozen = validate_prepared(output)
    audit = server = lease = child = node = None
    attempt = None
    started = time.monotonic()
    status, result, error = 'failed', None, None
    with data_temporary(output) as temporary:
        try:
            lease = ProducerLease(output).acquire()
            require(not (output / 'run.sqlite').exists() and not (output / 'attempts').exists(),
                    'This preparation already started; never repeat its enumeration')
            attempt = output / 'attempts' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:12])
            attempt.mkdir(parents=True)
            enumeration = attempt / 'enumeration'
            command = [sys.executable, '-m', MODULE, '--spec',
                       frozen['public_specification']['path'], '--output', str(enumeration)]
            write_new(attempt / 'attempt.json', {
                'kind': 'capital_allocation_full_search_attempt', 'version': 1, 'created_at': _now(),
                'preparation': reference(output / 'preparation.json'), 'command': command,
                'dedicated_child_process_group': True, 'temporary_directory': str(temporary),
                'expected_plan_count': 2**18, 'models': 0, 'LO_calls': 0, 'tokens': 0,
            })
            audit = AuditStore(output, {'id': output.name, 'name': 'Capital allocation exhaustive search',
                'status': 'running', 'target_count': 0, 'producer_kind': 'capital_allocation_search',
                'producer_pid': os.getpid(), 'producer_active': True, 'model_calls': 0, 'LO_calls': 0,
                'tokens': 0, 'quality_or_difficulty_certified': False, 'host_temporary_directory': str(temporary)})
            server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port)
            url = server.start()
            audit.update_run(dashboard_url=url)
            node = audit.record('nodes', {'node_id': 'full_integer_search', 'task_id': 'capital-allocation-search',
                'name': 'CPP enumeration and independent Python verification', 'status': 'running',
                'started_at': _now(), 'model_calls': 0, 'tokens': 0})
            audit.emit('search.attempt.before_start', attempt=str(attempt), command=command, model_calls=0, LO_calls=0)
            print(json.dumps({'dashboard_url': url, 'search_attempt': str(attempt),
                              'models': 0, 'tokens': 0, 'LO_calls': 0}), flush=True)
            environment = dict(os.environ)
            environment.update(TMPDIR=str(temporary), PYTHONPATH=str(ROOT / 'src'), PYTHONDONTWRITEBYTECODE='1')
            with (attempt / 'stdout.txt').open('xb') as stdout, (attempt / 'stderr.txt').open('xb') as stderr:
                child = subprocess.Popen(command, cwd=ROOT, env=environment,
                    stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True)
                write_new(attempt / 'child_started.json', {
                    'pid': child.pid, 'started_at': _now(), 'command': command,
                    'process_start_ticks': (Path('/proc') / str(child.pid) / 'stat').read_text().rsplit(')', 1)[1].split()[19],
                })
                audit.update_run(search_child_pid=child.pid, search_child_processes_started=1)
                cpp = ObservedCSV(enumeration / 'all_plans.csv')
                python = ObservedCSV(enumeration / 'independent_verification/python_plans.csv')
                while True:
                    progress = _progress(enumeration, cpp, python, started)
                    message = (progress['phase'] + ': CPP observed rows '
                        + str(progress['cpp_csv']['observed_complete_rows']) + '/262144; Python observed rows '
                        + str(progress['python_csv']['observed_complete_rows']) + '/262144; '
                        + str(progress['elapsed_seconds']) + 's; models/tokens/LO=0; completion unverified')
                    audit.update_run(**progress)
                    audit.task('capital-allocation-search', mode='engineering_search', status='running',
                               node=progress['phase'], current_node=message, duration_ms=round(progress['elapsed_seconds'] * 1000), **progress)
                    audit.update_record('nodes', node, {'name': message, 'phase': progress['phase'],
                        'duration_ms': round(progress['elapsed_seconds'] * 1000)})
                    audit.emit('search.observed_progress', message=message, **progress)
                    audit.export()
                    try:
                        code = child.wait(timeout=POLL_SECONDS)
                        break
                    except subprocess.TimeoutExpired:
                        pass
            audit.update_run(**_progress(enumeration, cpp, python, started))
            require(code == 0, 'Search child exited with status ' + str(code) + '; all outputs preserved')
            audit.update_run(phase='read_only_certificate_validation')
            audit.emit('search.certificate.validation_started')
            certificate = reference(enumeration / 'certificate.json')
            proof = search.validate_certificate(certificate, checked(frozen['public_specification']))
            validate_prepared(output)
            result = {'certificate': certificate, 'verification': proof['verification'],
                      'plans_csv': proof['plans_csv'], 'objective_pence': proof['objective_pence'],
                      'best_plan': proof['best_plan'], 'gap_pence': proof['gap_pence'],
                      'completed_plan_count': proof['plan_count'], 'certified_complete': True}
            status = 'completed'
            audit.task('capital-allocation-search', mode='engineering_search', status='search_verified',
                       node='completed', **result)
            audit.emit('search.completed', **result, model_calls=0, LO_calls=0, tokens=0)
            return write_new(output / 'search_result.json', {
                'kind': 'capital_allocation_monitored_search_result', 'version': 1, 'created_at': _now(),
                'preparation': reference(output / 'preparation.json'), 'attempt': reference(attempt / 'attempt.json'),
                **result, 'model_calls': 0, 'LO_calls': 0, 'tokens': 0,
                'qualified': False, 'task_count': 0, 'quality_or_difficulty_certified': False,
            })
        except BaseException as exception:
            error = {'type': type(exception).__name__, 'message': str(exception)}
            status = 'cancelled' if isinstance(exception, KeyboardInterrupt) else 'failed'
            raise
        finally:
            try:
                _stop_owned_child(child)
            finally:
                try:
                    if attempt is not None:
                        write_new(attempt / 'terminal.json', {
                            'kind': 'capital_allocation_search_terminal', 'status': status, 'finished_at': _now(),
                            'elapsed_seconds': round(time.monotonic() - started, 3), 'error': error,
                            'search_child_returncode': None if child is None else child.returncode,
                            'stdout': reference(attempt / 'stdout.txt') if (attempt / 'stdout.txt').exists() else None,
                            'stderr': reference(attempt / 'stderr.txt') if (attempt / 'stderr.txt').exists() else None,
                            'result': result, 'partial_artifacts_preserved': True,
                            'model_calls': 0, 'LO_calls': 0, 'tokens': 0, 'qualified': False, 'task_count': 0,
                        })
                finally:
                    try:
                        if audit is not None:
                            if node is not None:
                                audit.update_record('nodes', node, {'status': status,
                                    'duration_ms': round((time.monotonic() - started) * 1000), 'error': error})
                            audit.update_run(status=status, producer_active=False, elapsed_seconds=round(time.monotonic() - started, 3),
                                certified_complete=status == 'completed', model_calls=0, LO_calls=0, tokens=0)
                            audit.export()
                    finally:
                        try:
                            if server is not None:
                                server.stop()
                        finally:
                            try:
                                if audit is not None:
                                    audit.db.close()
                            finally:
                                if lease is not None:
                                    lease.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    if args.prepared:
        if args.spec or args.output:
            parser.error('--prepared cannot be combined with --spec or --output')
        if args.run:
            print(json.dumps(execute_prepared(args.prepared, port=args.port)), flush=True)
        else:
            validate_prepared(args.prepared)
            print(json.dumps({'validated': str(args.prepared), 'models': 0, 'LO_calls': 0, 'search_calls': 0}), flush=True)
    else:
        if not args.spec or not args.output or args.run:
            parser.error('Prepare with --spec --output; execute separately with --prepared --run')
        print(json.dumps(prepare(args.spec, args.output)), flush=True)


if __name__ == '__main__':
    main()
