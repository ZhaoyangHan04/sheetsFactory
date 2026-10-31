"""Private, resource-bound execution of an already compiled integer model.

Preparation copies exact approved package bytes. Execution never builds a
financial universe, changes the image, installs packages, or calls a model API.
A solver limit is retained as an unproved result, not an optimality claim.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import traceback
import uuid

ROOT = Path(__file__).resolve().parents[4]
IMAGE_ID = 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
VENDOR_SITE_PACKAGES = ROOT / 'outputs/tmp/linear-solver-914-py312/lib/python3.12/site-packages'
PREPARATION_KIND = 'prepared_private_linear_capital_integer_solver'
TERMINAL_KIND = 'private_linear_capital_integer_solver_execution'
BACKENDS = {'scip': ('model_a', 'solve_scip', 'native_model.cip'),
            'cp_sat': ('model_b', 'solve_cp_sat', 'native_model.pbtxt')}
CODE_FILES = ('spec.py', 'candidate_a.py', 'ledger.py', 'model_a.py', 'model_b.py')
DISTRIBUTIONS = {'absl_py': '2.5.1', 'immutabledict': '4.3.1', 'numpy': '1.26.4',
    'ortools': '9.14.6206', 'pandas': '3.0.6', 'protobuf': '6.31.1',
    'pyscipopt': '6.0.0', 'python_dateutil': '3.0.0', 'six': '1.17.0',
    'typing_extensions': '4.16.0', 'tzdata': '2026.6'}
VENDOR_ROOTS = {'absl', 'dateutil', 'google', 'immutabledict', 'numpy', 'numpy.libs',
    'ortools', 'ortools.libs', 'pandas', 'pybind11_abseil', 'pyscipopt', 'pyscipopt.libs',
    'six.py', 'typing_extensions.py', 'tzdata'} | {
        name + '-' + version + '.dist-info' for name, version in DISTRIBUTIONS.items()}
INSPECT_FORMAT = '{"Id":{{json .Id}},"Name":{{json .Name}},"Image":{{json .Image}},"NanoCpus":{{.HostConfig.NanoCpus}},"Memory":{{.HostConfig.Memory}},"PidsLimit":{{.HostConfig.PidsLimit}},"NetworkMode":{{json .HostConfig.NetworkMode}},"Privileged":{{json .HostConfig.Privileged}},"CapDrop":{{json .HostConfig.CapDrop}},"CapAdd":{{json .HostConfig.CapAdd}},"SecurityOpt":{{json .HostConfig.SecurityOpt}},"Mounts":{{json .Mounts}},"State":{{json .State}},"User":{{json .Config.User}},"WorkingDir":{{json .Config.WorkingDir}},"Entrypoint":{{json .Config.Entrypoint}},"Cmd":{{json .Config.Cmd}}}'


class OptimizationRuntimeError(RuntimeError):
    def __init__(self, message, receipt=None):
        super().__init__(message)
        self.receipt = receipt


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _real(path, *, exists=True):
    path = Path(path).absolute()
    _require(path == path.resolve() and not path.is_symlink(), 'Use a real path without symlink ancestors')
    if exists:
        _require(path.is_file(), 'A regular file is required')
    return path


def reference(path):
    path = _real(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024**2), b''):
            digest.update(chunk)
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def _read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(_real(path).read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON number')))


def _write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
    return reference(path)


def _integer(value):
    return type(value) is int and abs(value) < 2**53


def validate_model(model):
    """Check only matrix representation; do not reconstruct financial amounts."""
    _require(isinstance(model, dict) and set(model) == {'kind', 'version', 'project_ids',
        'objective_pence', 'rows', 'specification_sha256', 'universe_sha256'}, 'Incomplete canonical integer model')
    _require(model['kind'] == 'linear_capital_portfolio_direct_binary_integer_model'
        and type(model['version']) is int and model['version'] == 1, 'Unknown matrix format')
    ids = model['project_ids']
    _require(isinstance(ids, list) and 1 <= len(ids) <= 240
        and ids == [f'P{i:03d}' for i in range(1, len(ids) + 1)], 'Complete ordered project IDs are required')
    for field in ('specification_sha256', 'universe_sha256'):
        _require(type(model[field]) is str and re.fullmatch('[0-9a-f]{64}', model[field]), 'Bind exact model ancestry')
    _require(isinstance(model['objective_pence'], list) and len(model['objective_pence']) == len(ids)
        and all(_integer(v) for v in model['objective_pence']), 'Exact integer objective coefficients are required')
    _require(sum(abs(v) for v in model['objective_pence']) < 2**53, 'Objective sum exceeds the exact numeric domain')
    rows = model['rows']
    _require(isinstance(rows, list), 'All matrix rows are required')
    names = []
    for row in rows:
        _require(isinstance(row, dict) and set(row) == {'id', 'family', 'scenario_id', 'year', 'coefficients', 'limit'}, 'Incomplete matrix row')
        _require(type(row['id']) is str and row['id'] and type(row['family']) is str and row['family'], 'A matrix row needs a stable identity')
        _require(row['scenario_id'] is None or row['scenario_id'] in ('S01', 'S02', 'S03'), 'Unknown row scenario')
        _require(row['year'] is None or type(row['year']) is int and 0 <= row['year'] <= 20, 'Unknown row year')
        _require(isinstance(row['coefficients'], list) and len(row['coefficients']) == len(ids)
            and all(_integer(v) for v in row['coefficients']) and _integer(row['limit'])
            and sum(abs(v) for v in row['coefficients']) < 2**53, 'Row coefficients must be exact bounded integers')
        names.append(row['id'])
    _require(names == sorted(set(names)), 'Rows must have unique sorted IDs')
    return model


def _plan(ids, value):
    _require(isinstance(value, dict) and set(value) == set(ids)
        and all(type(v) is int and v in (0, 1) for v in value.values()), 'Use a complete integer binary plan')
    return {pid: value[pid] for pid in ids}


def check_result(model, result, exclude_plan=None):
    """Recheck a reported choice against every integer row, not financial code."""
    validate_model(model)
    _require(isinstance(result, dict) and type(result.get('checked_optimal')) is bool, 'Missing explicit solver optimality status')
    candidate = result.get('plan')
    exact = None
    if candidate is not None:
        candidate = _plan(model['project_ids'], candidate)
        values = [candidate[pid] for pid in model['project_ids']]
        violations = [row['id'] for row in model['rows']
            if sum(a * b for a, b in zip(row['coefficients'], values)) > row['limit']]
        objective = sum(a * b for a, b in zip(model['objective_pence'], values))
        _require(not violations, 'The solver plan violates an integer matrix row')
        _require(exclude_plan is None or candidate != exclude_plan, 'The excluded complete plan was returned')
        _require(type(result.get('objective_pence')) is int and result['objective_pence'] == objective,
                 'The reported objective differs from the exact integer objective')
        exact = {'passed': True, 'all_integer_rows_checked': len(model['rows']), 'objective_pence': objective,
                 'excluded_plan_not_returned': True}
    else:
        _require(result.get('objective_pence') is None, 'An absent plan has no objective')
    native = result.get('status', result.get('raw_status'))
    _require(type(native) is str or result.get('completed') is False and type(result.get('solver_error_type')) is str,
        'Missing native terminal solver status or explicit solver error')
    if result['checked_optimal']:
        _require(native in ('OPTIMAL', 'optimal') and exact is not None, 'An incomplete or limited solve cannot be optimal')
    return {'native_status': native, 'checked_optimal': result['checked_optimal'], 'exact_matrix_plan_check': exact,
        'status': ('reference_solver_error' if result.get('completed') is False else
            'reference_optimal_checked' if result['checked_optimal'] else 'reference_not_proven_optimal')}


def _source_files():
    folder = Path(__file__).resolve().parent
    return {name: _real(folder / name) for name in CODE_FILES}


def _walk_files(root, *, exclude_pycache=False):
    root = Path(root).absolute()
    _require(root == root.resolve() and root.is_dir() and not root.is_symlink(), 'Use a real package directory')
    files = {}
    for current, directories, names in os.walk(root, followlinks=False):
        for name in list(directories):
            path = Path(current) / name
            _require(not path.is_symlink(), 'Package directory symlinks are forbidden')
            if exclude_pycache and name == '__pycache__':
                directories.remove(name)
        for name in names:
            path = Path(current) / name
            _require(not path.is_symlink() and path.is_file(), 'Package file symlinks and special files are forbidden')
            if exclude_pycache and (name.endswith('.pyc') or name.endswith('.pyo')):
                continue
            files[str(path.relative_to(root))] = path
    return dict(sorted(files.items()))


def _inventory(root):
    return {relative: reference(path) for relative, path in _walk_files(root).items()}


def _copy_vendor(source, destination):
    source = Path(source).absolute()
    _require(source == VENDOR_SITE_PACKAGES.absolute() and source == source.resolve(), 'Use only the approved isolated solver environment')
    _require(set(p.name for p in source.iterdir() if p.name != '__pycache__') == VENDOR_ROOTS, 'The approved eleven-package solver environment changed')
    inventory = _walk_files(source, exclude_pycache=True)
    destination.mkdir()
    source_refs = {}
    for relative, path in inventory.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        original, copied = reference(path), reference(target)
        _require(original['sha256'] == copied['sha256'] and original['bytes'] == copied['bytes'], 'Vendor copy changed package bytes')
        source_refs[relative] = original
    return source_refs


RUNNER = r'''import sys
sys.dont_write_bytecode = True
from pathlib import Path
import hashlib,importlib,importlib.metadata,json,time,traceback
root=Path('/app')
sys.path.insert(0,str(root/'vendor'))
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4194304),b''):h.update(b)
 return h.hexdigest()
def inventory_check():
 inv=json.loads((root/'inventory.json').read_text())
 for name,r in inv.items():
  p=root/name
  if not p.is_file() or p.is_symlink() or sha(p)!=r['sha256'] or p.stat().st_size!=r['bytes']:raise ValueError('Private solver input/code/vendor changed')
 actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
 if actual != set(inv)|{'inventory.json'}:raise ValueError('Unexpected private solver input file')
 return inv
start=time.monotonic()
try:
 inv=inventory_check()
 job=json.loads((root/'job.json').read_text());model=json.loads((root/'model.json').read_text())
 module,function,model_file={'scip':('model_a','solve_scip','native_model.cip'),'cp_sat':('model_b','solve_cp_sat','native_model.pbtxt')}[job['backend']]
 versions={name:importlib.metadata.version(name) for name in job['distribution_versions']}
 if versions!=job['distribution_versions']:raise ValueError('Solver distribution version changed')
 backend=importlib.import_module('portfolio.'+module)
 result=getattr(backend,function)(model,time_limit_seconds=job['time_limit_seconds'],threads=2,exclude_plan=job['exclude_plan'],log_path=root/'solver.log',model_path=root/model_file)
 (root/'solver_result.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
 for name,r in inv.items():
  p=root/name
  if sha(p)!=r['sha256'] or p.stat().st_size!=r['bytes']:raise ValueError('Private solver input/code/vendor changed during execution')
 runtime={'completed':True,'backend':job['backend'],'model_canonical_sha256':hashlib.sha256(canonical(model)).hexdigest(),'elapsed_seconds':time.monotonic()-start,'distribution_versions':versions,'financial_forward_executed':False,'gap_requested':0,'threads':2,'solver_result':'solver_result.json'}
 (root/'runtime_result.json').write_text(json.dumps(runtime,indent=2,allow_nan=False)+'\n')
 print(json.dumps(runtime),flush=True)
except BaseException as error:
 (root/'runtime_error.json').write_text(json.dumps({'type':type(error).__name__,'error':str(error),'elapsed_seconds':time.monotonic()-start},indent=2)+'\n')
 traceback.print_exc();sys.exit(1)
'''


def prepare(model_json, output, *, backend, time_limit_seconds, exclude_plan=None,
            vendor_site_packages=VENDOR_SITE_PACKAGES):
    """Freeze a fresh private job. No solver, Docker or financial forward runs."""
    _require(backend in BACKENDS, 'Choose scip or cp_sat explicitly')
    _require(type(time_limit_seconds) is int and 1 <= time_limit_seconds <= 7200, 'The private reference limit must be 1..7200 seconds')
    original = reference(model_json)
    model = validate_model(_read(model_json))
    excluded = None if exclude_plan is None else _plan(model['project_ids'], exclude_plan)
    output = _real(output, exists=False)
    _require(not output.exists(), 'Preserve every existing preparation and attempt')
    output.mkdir(parents=True)
    try:
        bundle = output / 'job_bundle'; bundle.mkdir()
        package = bundle / 'portfolio'; package.mkdir(); (package / '__init__.py').write_bytes(b'')
        code = _source_files()
        source_refs = {}
        for name, source in code.items():
            shutil.copyfile(source, package / name)
            source_refs[name] = reference(source)
            copied = reference(package / name)
            _require(copied['sha256'] == source_refs[name]['sha256'] and copied['bytes'] == source_refs[name]['bytes'],
                'Copied solver source differs from its frozen implementation')
        vendor = _copy_vendor(vendor_site_packages, bundle / 'vendor')
        (bundle / 'model.json').write_bytes(_canonical(model))
        job = {'backend': backend, 'time_limit_seconds': time_limit_seconds, 'threads': 2,
            'exclude_plan': excluded, 'relative_gap': 0, 'absolute_gap': 0,
            'distribution_versions': DISTRIBUTIONS, 'nonce': uuid.uuid4().hex,
            'financial_forward_permitted': False}
        (bundle / 'job.json').write_bytes(_canonical(job)); (bundle / 'run.py').write_text(RUNNER)
        initial = _inventory(bundle)
        _write(bundle / 'inventory.json', {k: {'sha256': r['sha256'], 'bytes': r['bytes']} for k, r in initial.items()})
        result = {'kind': PREPARATION_KIND, 'version': 1, 'prepared_at': _now(), 'model_input': original,
            'model_canonical_sha256': hashlib.sha256(_canonical(model)).hexdigest(),
            'request': job, 'bundle': str(bundle), 'bundle_inventory': _inventory(bundle),
            'source_code': source_refs, 'vendor_source': str(Path(vendor_site_packages).absolute()),
            'vendor_inventory': vendor, 'implementation': reference(__file__),
            'image_id': IMAGE_ID, 'resources': {'cpus': 2, 'memory_bytes': 32 * 1024**3, 'pids_limit': 256},
            'network': 'none', 'operational_timeout_seconds': time_limit_seconds + 120,
            'agent_tool_budget_changed': False, 'solver_calls': 0, 'model_calls': 0, 'qualified': False}
        _require(original == reference(model_json), 'Input matrix changed during preparation')
        _require(all(reference(p) == source_refs[n] for n, p in code.items()), 'Source solver code changed during preparation')
        return _write(output / 'preparation.json', result)
    except BaseException as error:
        _write(output / 'preparation_failure.json', {'at': _now(), 'type': type(error).__name__, 'error': str(error),
            'actual_solver_calls': 0, 'model_calls': 0, 'partial_files_preserved': True})
        raise


def validate_prepared(output):
    output = _real(output, exists=False)
    frozen = _read(output / 'preparation.json')
    _require(frozen.get('kind') == PREPARATION_KIND and type(frozen.get('version')) is int and frozen.get('version') == 1
        and frozen['implementation'] == reference(__file__) and frozen['image_id'] == IMAGE_ID,
        'The private solver preparation identity changed')
    request = frozen['request']
    _require(set(request) == {'backend', 'time_limit_seconds', 'threads', 'exclude_plan', 'relative_gap',
        'absolute_gap', 'distribution_versions', 'nonce', 'financial_forward_permitted'}
        and request['backend'] in BACKENDS and type(request['time_limit_seconds']) is int
        and 1 <= request['time_limit_seconds'] <= 7200 and type(request['threads']) is int
        and request['threads'] == 2 and type(request['relative_gap']) is int and request['relative_gap'] == 0
        and type(request['absolute_gap']) is int and request['absolute_gap'] == 0
        and request['distribution_versions'] == DISTRIBUTIONS and request['financial_forward_permitted'] is False
        and type(request['nonce']) is str and re.fullmatch('[0-9a-f]{32}', request['nonce']), 'The frozen request settings changed')
    _require(frozen['resources'] == {'cpus': 2, 'memory_bytes': 32*1024**3, 'pids_limit': 256}
        and frozen['network'] == 'none' and frozen['operational_timeout_seconds'] == request['time_limit_seconds'] + 120
        and frozen['agent_tool_budget_changed'] is False and frozen['solver_calls'] == 0
        and frozen['model_calls'] == 0 and frozen['qualified'] is False, 'The resource or claim boundary changed')
    _require(frozen['source_code'] == {name: reference(path) for name, path in _source_files().items()},
        'The exact source solver closure changed')
    _require(Path(frozen['vendor_source']) == VENDOR_SITE_PACKAGES.absolute(), 'The approved vendor path changed')
    _require(frozen['vendor_inventory'] == {name: reference(path) for name, path in _walk_files(VENDOR_SITE_PACKAGES, exclude_pycache=True).items()},
        'The approved complete vendor closure changed')
    _require(Path(frozen['bundle']) == output / 'job_bundle', 'The private bundle path changed')
    _require(_inventory(output / 'job_bundle') == frozen['bundle_inventory'], 'The private job inventory changed')
    _require(reference(frozen['model_input']['path']) == frozen['model_input'], 'The original canonical model changed')
    _require(all(reference(r['path']) == r for r in frozen['source_code'].values())
        and all(reference(r['path']) == r for r in frozen['vendor_inventory'].values()), 'A source code or vendor byte changed')
    model = validate_model(_read(output / 'job_bundle/model.json'))
    _require(hashlib.sha256(_canonical(model)).hexdigest() == frozen['model_canonical_sha256'], 'Canonical model identity changed')
    if request['exclude_plan'] is not None:
        _plan(model['project_ids'], request['exclude_plan'])
    _require(_read(output / 'job_bundle/job.json') == request, 'The private execution request changed')
    return frozen


def _command(command, *, timeout=30):
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def _attach(command, stdout, stderr, timeout):
    with stdout.open('xb') as out, stderr.open('xb') as err:
        return subprocess.run(command, stdout=out, stderr=err, timeout=timeout)


def _inspect(container_id):
    result = _command(['docker', 'inspect', container_id, '--format', INSPECT_FORMAT])
    _require(result.returncode == 0, 'Cannot inspect the exact owned solver container')
    return json.loads(result.stdout)


def validate_resources(actual, container_id, bundle):
    _require(actual['Id'] == container_id and actual['Image'] == IMAGE_ID
        and actual['NanoCpus'] == 2 * 10**9 and actual['Memory'] == 32 * 1024**3
        and actual['PidsLimit'] == 256
        and all(type(actual[k]) is int for k in ('NanoCpus', 'Memory', 'PidsLimit'))
        and actual['NetworkMode'] == 'none'
        and actual['Privileged'] is False and actual['User'] == '0'
        and actual['CapDrop'] == ['ALL'] and actual['CapAdd'] in (['DAC_OVERRIDE'], ['CAP_DAC_OVERRIDE'])
        and actual['SecurityOpt'] == ['no-new-privileges'] and actual['WorkingDir'] == '/app'
        and actual['Entrypoint'] == ['/usr/bin/python3'] and actual['Cmd'] == ['/app/run.py'],
        'Actual solver identity, resources or isolation changed')
    mounts = actual['Mounts']
    _require(len(mounts) == 1 and mounts[0]['Type'] == 'bind' and mounts[0]['Source'] == str(bundle)
        and mounts[0]['Destination'] == '/app' and mounts[0]['RW'] is True, 'Only the private job bundle may be mounted')
    return True



class _Progress:
    """Report file sizes and elapsed wall time without interpreting solver text."""
    def __init__(self, audit, output, backend, started_clock, node_id, stage):
        self.audit, self.output, self.backend = audit, Path(output), backend
        self.started_clock, self.node_id, self.stage = started_clock, node_id, stage
        self.event = threading.Event()
        self.errors = []
        self.thread = threading.Thread(target=self._run, name='private-solver-progress', daemon=True)

    def pulse(self):
        try:
            elapsed = time.monotonic() - self.started_clock
            def size(path):
                return path.stat().st_size if path.is_file() else None
            data = {'elapsed_seconds': elapsed, 'backend': self.backend,
                'stdout_log_bytes': size(self.output / 'stdout.log'),
                'solver_log_bytes': size(self.output / 'job_bundle/solver.log'),
                'actual_solver_stage': self.stage['value']}
            self.audit.update_run(**data)
            self.audit.update_record('nodes', self.node_id, {'duration_ms': round(elapsed * 1000),
                'status': 'running', 'stage': data['actual_solver_stage']})
            self.audit.emit('reference.progress', **data)
            self.audit.export()
        except Exception as error:
            self.errors.append({'at': _now(), 'type': type(error).__name__, 'error': str(error)})

    def _run(self):
        while not self.event.wait(15):
            self.pulse()

    def start(self):
        self.pulse()
        self.thread.start()

    def stop(self):
        self.event.set()
        self.thread.join(timeout=1)
        return not self.thread.is_alive()


def _cleanup_owned(container_id):
    """Remove this full ID and prove absence while the daemon is reachable."""
    before = _now()
    removed = _command(['docker', 'rm', '--force', container_id])
    absent = _command(['docker', 'inspect', container_id, '--format', '{{.Id}}'])
    reachable = _command(['docker', 'image', 'inspect', IMAGE_ID, '--format', '{{.Id}}'])
    verified = (removed.returncode == 0 and absent.returncode != 0
        and 'no such object' in absent.stderr.lower()
        and reachable.returncode == 0 and reachable.stdout.strip() == IMAGE_ID)
    return {'owned_container_id': container_id, 'observed_before': before, 'observed_after': _now(),
        'returncode': removed.returncode, 'stdout': removed.stdout, 'stderr': removed.stderr,
        'absence_inspect': {'returncode': absent.returncode, 'stdout': absent.stdout, 'stderr': absent.stderr},
        'daemon_image_check': {'returncode': reachable.returncode, 'stdout': reachable.stdout, 'stderr': reachable.stderr},
        'removed_and_absent_with_daemon_reachable': verified}


def execute_prepared(output):
    """Execute one immutable job; preserve unsuccessful and limited solves."""
    frozen = validate_prepared(output); output = Path(output).absolute()
    _require(not (output / 'started.json').exists(), 'No automatic retry or overwrite is allowed')
    from ...core.audit import AuditStore
    from ...dashboard import DashboardServer
    from ...resume import ProducerLease
    lease = ProducerLease(output).acquire()
    audit = server = progress = None; owned = None; failure = None; node_id = None
    stage = {'value': 'starting_private_reference_job'}
    terminal = {'kind': TERMINAL_KIND, 'version': 1, 'status': 'execution_failed',
        'preparation': reference(output / 'preparation.json'), 'started_at': _now(),
        'requested_resources': frozen['resources'], 'image_id': IMAGE_ID,
        'private_reference_time_limit_seconds': frozen['request']['time_limit_seconds'],
        'operational_timeout_seconds': frozen['operational_timeout_seconds'],
        'agent_tool_budget_changed': False, 'model_calls': 0, 'financial_forward_executed': False,
        'formal_global_certificate_claimed': False, 'qualified': False}
    start = time.monotonic()
    try:
        audit = AuditStore(output / 'audit', {'id': output.name, 'name': 'Private integer reference solve',
            'status': 'running', 'target_count': 0, 'producer_active': True, 'producer_pid': os.getpid()})
        server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=0)
        terminal['dashboard_url'] = server.start()
        audit.update_run(dashboard_url=terminal['dashboard_url'], active_stage='private_reference_solver')
        _write(output / 'started.json', {**terminal, 'producer_pid': os.getpid()})
        audit.emit('reference.started', backend=frozen['request']['backend']); audit.export()
        node_id = audit.record('nodes', {'node': 'private_integer_reference_solver', 'status': 'running',
            'started_at': terminal['started_at'], 'duration_ms': 0, 'backend': frozen['request']['backend']})
        print(json.dumps({'dashboard_url': terminal['dashboard_url'], 'producer_pid': os.getpid(),
            'started': reference(output / 'started.json'), 'backend': frozen['request']['backend']}), flush=True)
        stage['value'] = 'checking_pinned_image_and_creating_container'
        progress = _Progress(audit, output, frozen['request']['backend'], start, node_id, stage)
        progress.start()
        pinned = _command(['docker', 'image', 'inspect', IMAGE_ID, '--format', '{{.Id}}'])
        _require(pinned.returncode == 0 and pinned.stdout.strip() == IMAGE_ID, 'The exact approved base image is unavailable')
        bundle = output / 'job_bundle'; nonce = frozen['request']['nonce']
        command = ['docker', 'create', '--name', 'sf-private-integer-' + nonce, '--user', '0',
            '--network', 'none', '--cap-drop', 'ALL', '--cap-add', 'DAC_OVERRIDE', '--security-opt', 'no-new-privileges',
            '--cpus', '2', '--memory', str(32 * 1024**3), '--pids-limit', '256',
            '--volume', str(bundle) + ':/app:rw', '--workdir', '/app', '--entrypoint', '/usr/bin/python3', IMAGE_ID, '/app/run.py']
        terminal['create_command'] = command
        created = _command(command)
        _write(output / 'create_result.json', {'returncode': created.returncode, 'stdout': created.stdout, 'stderr': created.stderr})
        _require(created.returncode == 0 and re.fullmatch('[0-9a-f]{64}', created.stdout.strip()), 'No unique owned container was created')
        owned = created.stdout.strip(); terminal['container_id'] = owned
        before = _inspect(owned); _write(output / 'host_before.json', before); validate_resources(before, owned, bundle)
        _require(before['Name'] == '/sf-private-integer-' + nonce and before['State']['Status'] == 'created'
            and before['State']['Running'] is False, 'The first-attempt container was already running or renamed')
        terminal['actual_resources_verified'] = True
        stage['value'] = 'private_solver_running'
        completed = _attach(['docker', 'start', '--attach', owned], output / 'stdout.log', output / 'stderr.log', frozen['operational_timeout_seconds'])
        stage['value'] = 'verifying_completed_solver_artifacts'
        after = _inspect(owned); _write(output / 'host_after.json', after); validate_resources(after, owned, bundle)
        _require(after['Name'] == before['Name'], 'The owned solver container was renamed')
        terminal['exit_code'] = after['State']['ExitCode']; terminal['oom_killed'] = after['State']['OOMKilled']
        _require(completed.returncode == 0 and after['State']['Status'] == 'exited'
            and type(after['State']['ExitCode']) is int and after['State']['ExitCode'] == 0
            and after['State']['Running'] is False and after['State']['OOMKilled'] is False, 'Private reference solver execution failed')
        current = _inventory(bundle)
        _require(all(current.get(name) == r for name, r in frozen['bundle_inventory'].items()), 'A private input or code byte changed')
        model_name = BACKENDS[frozen['request']['backend']][2]
        allowed = {'solver.log', model_name, 'solver_result.json', 'runtime_result.json'}
        if frozen['request']['backend'] == 'cp_sat':
            allowed.add(model_name + '.parameters.pbtxt')
        _require(set(current) - set(frozen['bundle_inventory']) <= allowed, 'The solver wrote an unexpected job file')
        _require(all((bundle / name).is_file() for name in allowed), 'A complete solver result, native model, settings and log are required')
        runtime = _read(bundle / 'runtime_result.json')
        _require(runtime.get('completed') is True and runtime.get('financial_forward_executed') is False
            and runtime.get('model_canonical_sha256') == frozen['model_canonical_sha256']
            and runtime.get('backend') == frozen['request']['backend'] and runtime.get('threads') == 2
            and runtime.get('gap_requested') == 0 and runtime.get('distribution_versions') == DISTRIBUTIONS,
            'The matrix-only runtime did not complete with the frozen settings')
        model_ancestry = _read(bundle / 'model.json')
        solver = _read(bundle / 'solver_result.json')
        _require(solver.get('model_sha256') == frozen['model_canonical_sha256']
            and solver.get('specification_sha256') == model_ancestry['specification_sha256']
            and solver.get('universe_sha256') == model_ancestry['universe_sha256']
            and solver.get('exclude_plan') == frozen['request']['exclude_plan'],
            'The solver result is not bound to the exact matrix and full-plan exclusion')
        if frozen['request']['backend'] == 'scip':
            _require(solver.get('parameters') == {'limits/time': float(frozen['request']['time_limit_seconds']),
                'limits/gap': 0.0, 'limits/absgap': 0.0, 'parallel/maxnthreads': 2, 'lp/threads': 2}
                and solver.get('feasibility_tolerance_changed') is False, 'The native SCIP settings changed')
        else:
            _require(solver.get('gap_parameters') == {'relative': 0, 'absolute': 0}
                and solver.get('threads') == 2 and solver.get('time_limit_seconds') == frozen['request']['time_limit_seconds'],
                'The native CP-SAT settings changed')
        matrix_check = check_result(model_ancestry, solver, frozen['request']['exclude_plan'])
        _require(reference(__file__) == frozen['implementation']
            and reference(frozen['model_input']['path']) == frozen['model_input']
            and all(reference(r['path']) == r for r in frozen['source_code'].values())
            and all(reference(r['path']) == r for r in frozen['vendor_inventory'].values()),
            'The frozen input, solver or vendor implementation changed')
        terminal.update(status=matrix_check['status'], matrix_result_check=matrix_check,
            solver_result=reference(bundle / 'solver_result.json'), runtime_result=reference(bundle / 'runtime_result.json'),
            complete_job_inventory=current, stdout=reference(output / 'stdout.log'), stderr=reference(output / 'stderr.log'))
    except BaseException as error:
        failure = error
        stage['value'] = 'retaining_failed_execution_evidence'
        terminal.update(error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
        if owned is not None:
            try:
                if isinstance(error, subprocess.TimeoutExpired):
                    stopped = _command(['docker', 'kill', owned]); terminal['timeout_owned_kill_returncode'] = stopped.returncode
                after = _inspect(owned); _write(output / 'host_failed_after.json', after)
                terminal['failed_container_state'] = after['State']
            except BaseException as inspect_error:
                terminal['failure_inspect_error'] = str(inspect_error)
    finally:
        stage['value'] = 'cleaning_up_owned_container'
        if owned is not None:
            try:
                cleanup = _cleanup_owned(owned)
                terminal['cleanup'] = _write(output / 'owned_cleanup.json', cleanup)
                if not cleanup['removed_and_absent_with_daemon_reachable']:
                    terminal['status'] = 'execution_failed'; failure = failure or RuntimeError('Owned container cleanup or absence verification failed')
            except BaseException as cleanup_error:
                terminal['status'] = 'execution_failed'; terminal['cleanup_error'] = str(cleanup_error); failure = failure or cleanup_error
        stopped = True
        if progress is not None:
            stopped = progress.stop()
            terminal['progress'] = {'interval_seconds': 15, 'thread_stopped': stopped,
                'join_timeout_seconds': 1, 'errors': progress.errors, 'solver_text_interpreted': False}
            if not stopped:
                terminal['status'] = 'execution_failed'; failure = failure or RuntimeError('Progress thread did not stop within one second')
        for name in ('stdout.log', 'stderr.log'):
            if (output / name).is_file():
                terminal[name.removesuffix('.log')] = reference(output / name)
        try:
            terminal['retained_job_inventory'] = _inventory(output / 'job_bundle')
        except BaseException as inventory_error:
            terminal['retained_inventory_error'] = str(inventory_error)
        terminal['finished_at'] = _now(); terminal['elapsed_seconds'] = time.monotonic() - start
        receipt = _write(output / 'terminal.json', terminal)
        if audit:
            if node_id is not None:
                audit.update_record('nodes', node_id, {'status': terminal['status'], 'finished_at': terminal['finished_at'],
                    'duration_ms': round(terminal['elapsed_seconds'] * 1000)})
            audit.update_run(status=terminal['status'], producer_active=False, finished_at=terminal['finished_at']); audit.export()
        if server: server.stop()
        if audit and stopped: audit.db.close()
        lease.release()
    if failure is not None:
        raise OptimizationRuntimeError(str(failure), receipt) from failure
    return receipt
