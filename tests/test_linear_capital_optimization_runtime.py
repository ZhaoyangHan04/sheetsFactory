"""Tiny matrices and mocked Docker only; no production financial optimization."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from sheets_factory.workbook.linear_capital_portfolio import optimization_runtime as runtime


def matrix():
    return {'kind': 'linear_capital_portfolio_direct_binary_integer_model', 'version': 1,
        'project_ids': ['P001', 'P002'], 'objective_pence': [7, 4],
        'rows': [{'id': 'capacity', 'family': 'initial_equity', 'scenario_id': None,
            'year': 0, 'coefficients': [2, 1], 'limit': 2}],
        'specification_sha256': '1' * 64, 'universe_sha256': '2' * 64}


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    vendor = tmp_path / 'approved_site_packages'; vendor.mkdir()
    (vendor / 'dummy.py').write_text('EXACT_APPROVED_BYTES = True\n')
    cache = vendor / '__pycache__'; cache.mkdir(); (cache / 'dummy.pyc').write_bytes(b'never copy cache')
    code = tmp_path / 'pure_solver_sources'; code.mkdir()
    for name in runtime.CODE_FILES:
        (code / name).write_text('# Test-only source placeholder; no financial or solver call.\n')
    monkeypatch.setattr(runtime, 'VENDOR_SITE_PACKAGES', vendor)
    monkeypatch.setattr(runtime, 'VENDOR_ROOTS', {'dummy.py'})
    monkeypatch.setattr(runtime, '_source_files', lambda: {name: code / name for name in runtime.CODE_FILES})
    model = tmp_path / 'model.json'; model.write_text(json.dumps(matrix()))
    def make(*, backend='scip', excluded=None, name='job'):
        output = tmp_path / name
        receipt = runtime.prepare(model, output, backend=backend, time_limit_seconds=3,
            exclude_plan=excluded, vendor_site_packages=vendor)
        return output, receipt
    make.vendor, make.code, make.model = vendor, code, model
    return make


def services(monkeypatch):
    import sheets_factory.core.audit as audit
    import sheets_factory.dashboard as dashboard
    import sheets_factory.resume as resume
    state = {'leased': False, 'released': False, 'closed': False}
    class Lease:
        def __init__(self, output): pass
        def acquire(self): state['leased'] = True; return self
        def release(self): state['released'] = True
    class Audit:
        def __init__(self, *args): self.db = self
        def update_run(self, **kwargs): state.update(kwargs)
        def emit(self, *args, **kwargs): pass
        def export(self): pass
        def record(self, table, record): state['node'] = dict(record); return 1
        def update_record(self, table, record_id, values): state['node'].update(values)
        def snapshot(self): return {}
        def events(self): return []
        def close(self): state['closed'] = True
    class Dashboard:
        def __init__(self, *args, **kwargs): pass
        def start(self): return 'http://127.0.0.1:12345/'
        def stop(self): state['stopped'] = True
    monkeypatch.setattr(resume, 'ProducerLease', Lease)
    monkeypatch.setattr(audit, 'AuditStore', Audit)
    monkeypatch.setattr(dashboard, 'DashboardServer', Dashboard)
    return state


def mock_execution(output, monkeypatch, *, limited=False, fault=None):
    state = services(monkeypatch)
    frozen = runtime.validate_prepared(output)
    bundle = output / 'job_bundle'
    cid = 'a' * 64
    def actual():
        return {'Id': cid, 'Name': '/sf-private-integer-' + frozen['request']['nonce'],
            'Image': runtime.IMAGE_ID, 'NanoCpus': 2 * 10**9, 'Memory': 32 * 1024**3,
            'PidsLimit': 256, 'NetworkMode': 'none', 'Privileged': False,
            'CapDrop': ['ALL'], 'CapAdd': ['DAC_OVERRIDE'], 'SecurityOpt': ['no-new-privileges'],
            'Mounts': [{'Type': 'bind', 'Source': str(bundle), 'Destination': '/app', 'RW': True}],
            'User': '0', 'WorkingDir': '/app', 'Entrypoint': ['/usr/bin/python3'], 'Cmd': ['/app/run.py'],
            'State': {'Status': 'exited' if state.get('attached') else 'created',
                'Running': not state.get('attached') if state.get('timeout') else False,
                'ExitCode': 137 if state.get('timeout') else 0, 'OOMKilled': fault == 'oom'}}
    commands = []
    def command(args, *, timeout=30):
        commands.append(args)
        if args[:3] == ['docker', 'image', 'inspect']:
            if fault == 'daemon' and state.get('cleaned'):
                return subprocess.CompletedProcess(args, 1, '', 'Cannot connect to Docker daemon')
            return subprocess.CompletedProcess(args, 0, runtime.IMAGE_ID + '\n', '')
        if args[:2] == ['docker', 'create']:
            return subprocess.CompletedProcess(args, 0, cid + '\n', '')
        if args[:2] == ['docker', 'inspect']:
            if state.get('cleaned'):
                if fault == 'absence': return subprocess.CompletedProcess(args, 0, cid, '')
                return subprocess.CompletedProcess(args, 1, '', 'Error: no such object: ' + cid)
            value = actual()
            if fault == 'resources': value['Memory'] = 2 * 1024**3
            return subprocess.CompletedProcess(args, 0, json.dumps(value), '')
        if args[:2] == ['docker', 'kill']:
            state['attached'] = True
            return subprocess.CompletedProcess(args, 0, cid, '')
        if args[:2] == ['docker', 'rm']:
            state['cleaned'] = fault != 'cleanup'
            return subprocess.CompletedProcess(args, int(fault == 'cleanup'), cid, '')
        raise AssertionError(args)
    def attach(args, stdout, stderr, timeout):
        assert state['leased'] and (output / 'started.json').is_file()
        assert timeout == 123
        state['attached'] = True
        stdout.write_text('complete native stdout\n'); stderr.write_text('complete native stderr\n')
        if fault == 'timeout':
            state['timeout'] = True
            raise subprocess.TimeoutExpired(args, timeout)
        if fault == 'exit': return subprocess.CompletedProcess(args, 1)
        result = {'checked_optimal': not limited, 'plan': {'P001': 1, 'P002': 0}, 'objective_pence': 7,
            'exclude_plan': frozen['request']['exclude_plan'],
            'model_sha256': frozen['model_canonical_sha256'],
            'specification_sha256': matrix()['specification_sha256'], 'universe_sha256': matrix()['universe_sha256']}
        if frozen['request']['backend'] == 'scip':
            result.update(raw_status='timelimit' if limited else 'optimal', completed=True,
                parameters={'limits/time': 3.0, 'limits/gap': 0.0, 'limits/absgap': 0.0,
                    'parallel/maxnthreads': 2, 'lp/threads': 2}, feasibility_tolerance_changed=False)
        else:
            result.update(status='FEASIBLE' if limited else 'OPTIMAL', gap_parameters={'relative': 0, 'absolute': 0},
                threads=2, time_limit_seconds=3)
            (bundle / 'native_model.pbtxt.parameters.pbtxt').write_text('num_search_workers: 2\n')
        (bundle / runtime.BACKENDS[frozen['request']['backend']][2]).write_text('native tiny model\n')
        (bundle / 'solver.log').write_text('complete native solver log\n')
        (bundle / 'solver_result.json').write_text(json.dumps(result))
        result_runtime = {'completed': True, 'backend': frozen['request']['backend'],
            'financial_forward_executed': False, 'model_canonical_sha256': frozen['model_canonical_sha256'],
            'threads': 2, 'gap_requested': 0, 'distribution_versions': runtime.DISTRIBUTIONS}
        (bundle / 'runtime_result.json').write_text(json.dumps(result_runtime))
        if fault == 'mutation': (bundle / 'model.json').write_text('{}')
        if fault == 'extra': (bundle / 'unexpected_private_file').write_text('not allowed')
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(runtime, '_command', command)
    monkeypatch.setattr(runtime, '_attach', attach)
    return state, commands


def test_prepare_is_copy_only_and_preserves_exact_bytes(prepared, monkeypatch):
    monkeypatch.setattr(runtime, '_command', lambda *a, **k: pytest.fail('Preparation must not execute Docker'))
    output, receipt = prepared()
    proof = runtime.validate_prepared(output)
    assert receipt == runtime.reference(output / 'preparation.json')
    assert proof['solver_calls'] == proof['model_calls'] == 0
    assert not (output / 'started.json').exists()
    assert (output / 'job_bundle/vendor/dummy.py').read_bytes() == (prepared.vendor / 'dummy.py').read_bytes()
    assert not list((output / 'job_bundle').rglob('*.pyc'))
    assert set(proof['source_code']) == set(runtime.CODE_FILES)
    assert (output / 'job_bundle/portfolio/__init__.py').read_bytes() == b''


def test_partial_prepare_preserved_on_vendor_symlink(prepared):
    (prepared.vendor / 'dummy.py').unlink()
    (prepared.vendor / 'dummy.py').symlink_to(prepared.model)
    with pytest.raises(ValueError, match='symlink'):
        prepared()
    failure = json.loads((prepared.vendor.parent / 'job/preparation_failure.json').read_text())
    assert failure['actual_solver_calls'] == 0 and failure['partial_files_preserved']


@pytest.mark.parametrize('change', ['source', 'vendor', 'input', 'bundle', 'extra'])
def test_any_frozen_byte_change_blocks_execution(prepared, change):
    output, _ = prepared()
    paths = {'source': prepared.code / 'spec.py', 'vendor': prepared.vendor / 'dummy.py',
        'input': prepared.model, 'bundle': output / 'job_bundle/model.json', 'extra': output / 'job_bundle/new'}
    paths[change].write_text('changed')
    with pytest.raises(ValueError): runtime.validate_prepared(output)
    assert not (output / 'started.json').exists()


@pytest.mark.parametrize('backend', ['scip', 'cp_sat'])
@pytest.mark.parametrize('limited', [False, True])
def test_normal_and_limited_native_results_are_distinct(prepared, monkeypatch, backend, limited):
    output, _ = prepared(backend=backend)
    state, commands = mock_execution(output, monkeypatch, limited=limited)
    result = runtime.execute_prepared(output)
    proof = json.loads(Path(result['path']).read_text())
    assert proof['status'] == ('reference_not_proven_optimal' if limited else 'reference_optimal_checked')
    assert proof['matrix_result_check']['checked_optimal'] is (not limited)
    assert proof['stdout']['bytes'] > 0 and proof['stderr']['bytes'] > 0
    assert proof['qualified'] is False and proof['model_calls'] == 0
    assert state['released'] and state['closed'] and state['stopped']
    assert state['node']['duration_ms'] >= 0 and state['node']['status'] == proof['status']
    assert proof['progress']['interval_seconds'] == 15 and proof['progress']['thread_stopped'] is True
    assert proof['progress']['solver_text_interpreted'] is False
    cleanup = json.loads(Path(proof['cleanup']['path']).read_text())
    assert cleanup['removed_and_absent_with_daemon_reachable'] is True
    assert len([c for c in commands if c[:2] == ['docker', 'create']]) == 1
    assert [c for c in commands if c[:2] == ['docker', 'rm']] == [['docker', 'rm', '--force', 'a' * 64]]
    assert commands[-1] == ['docker', 'image', 'inspect', runtime.IMAGE_ID, '--format', '{{.Id}}']
    with pytest.raises(ValueError): runtime.execute_prepared(output)


@pytest.mark.parametrize('fault', ['resources', 'timeout', 'exit', 'oom', 'mutation', 'extra', 'cleanup', 'absence', 'daemon'])
def test_failures_keep_receipts_and_cleanup_only_owned_id(prepared, monkeypatch, fault):
    output, _ = prepared()
    state, commands = mock_execution(output, monkeypatch, fault=fault)
    with pytest.raises(runtime.OptimizationRuntimeError) as caught:
        runtime.execute_prepared(output)
    receipt = json.loads(Path(caught.value.receipt['path']).read_text())
    assert receipt['status'] == 'execution_failed'
    assert (output / 'started.json').exists() and (output / 'owned_cleanup.json').exists()
    assert state['released'] and state['stopped']
    assert [c for c in commands if c[:2] == ['docker', 'rm']] == [['docker', 'rm', '--force', 'a' * 64]]
    assert commands[-1] == ['docker', 'image', 'inspect', runtime.IMAGE_ID, '--format', '{{.Id}}']
    if fault == 'timeout': assert ['docker', 'kill', 'a' * 64] in commands
    if fault != 'resources': assert receipt['stdout']['bytes'] > 0


@pytest.mark.parametrize('mutation', ['bool_coefficient', 'duplicate_rows', 'wrong_ids', 'noninteger', 'overflow'])
def test_reject_noncanonical_or_inexact_models(mutation):
    model = matrix()
    if mutation == 'bool_coefficient': model['rows'][0]['coefficients'][0] = True
    if mutation == 'duplicate_rows': model['rows'].append(deepcopy(model['rows'][0]))
    if mutation == 'wrong_ids': model['project_ids'] = ['P002', 'P001']
    if mutation == 'noninteger': model['objective_pence'][0] = 7.0
    if mutation == 'overflow': model['objective_pence'][0] = 2**53
    with pytest.raises(ValueError): runtime.validate_model(model)


@pytest.mark.parametrize('plan', [{'P001': True, 'P002': 0}, {'P001': 1}, {'P001': 2, 'P002': 0}])
def test_exclude_plan_must_be_complete_integer_binary(prepared, plan):
    with pytest.raises(ValueError, match='complete integer binary'):
        prepared(excluded=plan)


def test_result_does_not_promote_limit_or_accept_violating_or_excluded_plan():
    result = {'raw_status': 'timelimit', 'checked_optimal': False,
        'plan': {'P001': 1, 'P002': 0}, 'objective_pence': 7}
    assert runtime.check_result(matrix(), result)['checked_optimal'] is False
    wrong = deepcopy(result); wrong['checked_optimal'] = True
    with pytest.raises(ValueError, match='limited'): runtime.check_result(matrix(), wrong)
    wrong = deepcopy(result); wrong['plan']['P002'] = 1; wrong['objective_pence'] = 11
    with pytest.raises(ValueError, match='violates'): runtime.check_result(matrix(), wrong)
    with pytest.raises(ValueError, match='excluded'):
        runtime.check_result(matrix(), result, result['plan'])


def test_runner_calls_only_matrix_solve_and_no_financial_builder():
    tree = ast.parse(runtime.RUNNER)
    text = ast.dump(tree)
    assert 'build_model' not in runtime.RUNNER and 'simulate' not in runtime.RUNNER
    assert 'dont_write_bytecode' in runtime.RUNNER
    assert "'portfolio.'+module" in runtime.RUNNER
    assert "'solver.log').open('x')" not in runtime.RUNNER
    assert 'financial_forward_executed' in text


@pytest.mark.parametrize('time_limit', [True, 0, -1, 7201, 3.0])
def test_time_limit_is_private_explicit_and_bounded(prepared, time_limit):
    with pytest.raises(ValueError, match='1..7200'):
        runtime.prepare(prepared.model, prepared.vendor.parent / 'bad', backend='scip',
            time_limit_seconds=time_limit, vendor_site_packages=prepared.vendor)


def test_copied_source_must_match_bound_implementation(prepared, monkeypatch):
    real = runtime.shutil.copyfile
    def wrong(source, destination):
        result = real(source, destination)
        if Path(destination).name == 'spec.py': Path(destination).write_text('different bytes')
        return result
    monkeypatch.setattr(runtime.shutil, 'copyfile', wrong)
    with pytest.raises(ValueError, match='Copied solver source'):
        prepared()
    assert not (prepared.vendor.parent / 'job/started.json').exists()


@pytest.mark.parametrize('field,value', [('threads', 1), ('relative_gap', 1), ('absolute_gap', 1),
    ('time_limit_seconds', True), ('financial_forward_permitted', True)])
def test_prepare_request_cannot_be_rebound_to_weaker_settings(prepared, field, value):
    output, _ = prepared()
    proof = json.loads((output / 'preparation.json').read_text())
    proof['request'][field] = value
    (output / 'preparation.json').write_text(json.dumps(proof))
    with pytest.raises(ValueError, match='settings'):
        runtime.validate_prepared(output)


def test_duplicate_json_model_keys_are_rejected(prepared):
    raw = prepared.model.read_text()
    prepared.model.write_text(raw[:-1] + ',"version":1}')
    with pytest.raises(ValueError, match='Duplicate'):
        prepared()


def test_named_vendor_library_folders_are_in_the_declared_allowlist():
    assert {'numpy.libs', 'ortools.libs', 'pyscipopt.libs'} <= runtime.VENDOR_ROOTS
    assert len(runtime.DISTRIBUTIONS) == 11
    assert runtime.DISTRIBUTIONS['ortools'] == '9.14.6206'


def test_resource_validation_rejects_extra_mount_and_extra_capability(prepared):
    output, _ = prepared()
    frozen = runtime.validate_prepared(output)
    actual = {'Id': 'a' * 64, 'Image': runtime.IMAGE_ID, 'NanoCpus': 2 * 10**9,
        'Memory': 32 * 1024**3, 'PidsLimit': 256, 'NetworkMode': 'none', 'Privileged': False,
        'User': '0', 'CapDrop': ['ALL'], 'CapAdd': ['CAP_DAC_OVERRIDE'],
        'SecurityOpt': ['no-new-privileges'], 'WorkingDir': '/app', 'Entrypoint': ['/usr/bin/python3'],
        'Cmd': ['/app/run.py'], 'Mounts': [{'Type': 'bind', 'Source': frozen['bundle'], 'Destination': '/app', 'RW': True}]}
    assert runtime.validate_resources(actual, 'a' * 64, Path(frozen['bundle']))
    wrong = deepcopy(actual); wrong['CapAdd'].append('SYS_ADMIN')
    with pytest.raises(ValueError): runtime.validate_resources(wrong, 'a' * 64, Path(frozen['bundle']))
    wrong = deepcopy(actual); wrong['Mounts'].append({'Source': '/private_goal'})
    with pytest.raises(ValueError): runtime.validate_resources(wrong, 'a' * 64, Path(frozen['bundle']))
    wrong = deepcopy(actual); wrong['PidsLimit'] = 256.0
    with pytest.raises(ValueError): runtime.validate_resources(wrong, 'a' * 64, Path(frozen['bundle']))


def test_progress_reports_only_sizes_elapsed_backend_stage_and_joins_within_one_second(tmp_path, monkeypatch):
    record = {'waits': [], 'pulses': [], 'joins': []}
    class Event:
        def __init__(self): self.done = False
        def wait(self, seconds):
            record['waits'].append(seconds)
            return len(record['waits']) > 1 or self.done
        def set(self): self.done = True
    class Thread:
        def __init__(self, *, target, name, daemon):
            self.target = target; assert daemon is True; self.alive = False
        def start(self): self.alive = True
        def join(self, timeout): record['joins'].append(timeout); self.alive = False
        def is_alive(self): return self.alive
    class Audit:
        def update_run(self, **values): record['pulses'].append(values)
        def update_record(self, *args): pass
        def emit(self, *args, **kwargs): pass
        def export(self): pass
    monkeypatch.setattr(runtime.threading, 'Event', Event)
    monkeypatch.setattr(runtime.threading, 'Thread', Thread)
    (tmp_path / 'job_bundle').mkdir()
    (tmp_path / 'stdout.log').write_text('OPTIMAL incumbent objective42\n')
    (tmp_path / 'job_bundle/solver.log').write_text('LIMIT gap unknown\n')
    progress = runtime._Progress(Audit(), tmp_path, 'cp_sat', runtime.time.monotonic(), 1,
        {'value': 'private_solver_running'})
    progress.start()
    progress._run()
    assert progress.stop()
    assert record['waits'] == [15, 15] and record['joins'] == [1]
    assert len(record['pulses']) == 2
    for pulse in record['pulses']:
        assert set(pulse) == {'elapsed_seconds', 'backend', 'stdout_log_bytes', 'solver_log_bytes', 'actual_solver_stage'}
        assert pulse['backend'] == 'cp_sat' and pulse['actual_solver_stage'] == 'private_solver_running'
        assert pulse['stdout_log_bytes'] == (tmp_path / 'stdout.log').stat().st_size
        assert 'optimal' not in pulse and 'incumbent' not in pulse


def test_execution_prints_panel_and_stops_progress_on_failure(prepared, monkeypatch, capsys):
    output, _ = prepared()
    mock_execution(output, monkeypatch, fault='exit')
    with pytest.raises(runtime.OptimizationRuntimeError): runtime.execute_prepared(output)
    event = json.loads(capsys.readouterr().out.strip())
    assert event['dashboard_url'] == 'http://127.0.0.1:12345/'
    assert event['backend'] == 'scip' and event['started']['sha256']
    proof = json.loads((output / 'terminal.json').read_text())
    assert proof['progress']['thread_stopped'] is True and proof['progress']['join_timeout_seconds'] == 1
