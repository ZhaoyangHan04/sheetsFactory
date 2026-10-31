"""Producer16 code and mocked lifecycle only; no actual solve, Docker or finance."""
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sheets_factory.workbook.linear_capital_portfolio import optimization_runtime as old_runtime
from sheets_factory.workbook.linear_capital_portfolio import producer_optimization_runtime as runtime
from sheets_factory.workbook.linear_capital_portfolio import producer_model_b
from test_linear_capital_optimization_runtime import matrix, services

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    definition = importlib.util.spec_from_file_location('_producer_test_'+name, ROOT/'scripts'/name)
    value = importlib.util.module_from_spec(definition); definition.loader.exec_module(value); return value


entry = module('run_linear_capital_producer_reference.py')
builder = module('build_linear_capital_producer_source.py')


def test_original_namespaces_and_all_frozen_upstream_bytes_remain_unchanged():
    assert old_runtime.PREPARATION_KIND == 'prepared_private_linear_capital_integer_solver'
    assert set(old_runtime.BACKENDS) == {'scip', 'cp_sat'}
    assert runtime.PREPARATION_KIND == 'prepared_private_linear_capital_producer16_solver'
    assert set(runtime.BACKENDS) == {'cp_sat'}
    assert runtime.reference(Path(old_runtime.__file__))['sha256'] == runtime.UPSTREAM_SHA256
    assert runtime.reference(producer_model_b.upstream_path())['sha256'] == producer_model_b.UPSTREAM_SHA256
    assert runtime.profile_reference()['path'].endswith('linear_capital_reference_producer_v1.json')
    profile = json.loads(runtime.PROFILE.read_text())
    assert profile['producer']['cpus'] == profile['producer']['threads'] == 16
    assert profile['agent_and_verifier']['cpus'] == 2
    assert profile['agent_and_verifier']['strict_tool_budget_seconds'] == 1800


def test_b_worker_shim_has_exactly_one_guard_change_no_finance_or_matrix_change():
    before = ast.parse(producer_model_b.upstream_path().read_text())
    changes = 0
    for node in ast.walk(before):
        if isinstance(node, ast.Call) and ast.unparse(node) == "require(type(threads) is int and 1 <= threads <= 2, 'The reference uses at most the declared two CPU workers')":
            replacement = ast.parse("require(type(threads) is int and 1<=threads<=16, 'The private producer uses at most the declared sixteen CPU workers')").body[0].value
            node.args = replacement.args; changes += 1
    assert changes == 1 and ast.dump(before) == ast.dump(producer_model_b.adapted_ast())


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    vendor = tmp_path/'approved_vendor'; vendor.mkdir(); (vendor/'dummy.py').write_text('# Offline fixture only\n')
    monkeypatch.setattr(runtime, 'VENDOR_SITE_PACKAGES', vendor)
    monkeypatch.setattr(runtime, 'VENDOR_ROOTS', {'dummy.py'})
    model = tmp_path/'model.json'; model.write_text(json.dumps(matrix()))
    def make(*, excluded=None):
        output = tmp_path/'job'
        ref = runtime.prepare(model, output, backend='cp_sat', time_limit_seconds=3600,
            exclude_plan=excluded, vendor_site_packages=vendor)
        return output, ref
    make.model = model; return make


def test_preparation_only_copies_native_code_and_profile_no_execution(prepared, monkeypatch):
    monkeypatch.setattr(runtime, '_command', lambda *_a, **_k: pytest.fail('No Docker during preparation'))
    output, ref = prepared(); frozen = runtime.validate_prepared(output)
    assert frozen['resources'] == {'cpus': 16, 'memory_bytes': 32*1024**3, 'pids_limit': 256}
    assert frozen['request']['threads'] == 16 and frozen['request']['backend'] == 'cp_sat'
    assert frozen['producer_profile'] == runtime.profile_reference()
    assert frozen['solver_calls'] == frozen['model_calls'] == 0
    bundle = output/'job_bundle'
    assert runtime.reference(bundle/'portfolio/frozen_model_b.py')['sha256'] == producer_model_b.UPSTREAM_SHA256
    assert runtime.reference(bundle/'portfolio/model_b.py')['sha256'] == runtime.reference(producer_model_b.__file__)['sha256']
    # A fresh host process tests namespace transport, not financial or solver execution.
    code = "import sys;sys.dont_write_bytecode=True;sys.path.insert(0,sys.argv[1]);import portfolio.model_b as b;print(b.upstream_path().name);print('import_only_no_solver')"
    result = subprocess.run([sys.executable, '-I', '-c', code, str(bundle)], capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout == 'frozen_model_b.py\nimport_only_no_solver\n'
    assert runtime.validate_prepared(output) == frozen


@pytest.mark.parametrize('bad', ['two_cpu', 'two_workers', 'backend_scip', 'changed_profile', 'source_missing'])
def test_preparation_strict_resource_and_closure_guards(prepared, bad):
    output, ref = prepared(); frozen = runtime._read(ref['path'])
    if bad == 'two_cpu': frozen['resources']['cpus'] = 2
    if bad == 'two_workers': frozen['request']['threads'] = 2
    if bad == 'backend_scip': frozen['request']['backend'] = 'scip'
    if bad == 'changed_profile': frozen['producer_profile']['sha256'] = '0'*64
    if bad == 'source_missing': (output/'job_bundle/portfolio/frozen_model_b.py').unlink()
    (output/'preparation.json').write_text(json.dumps(frozen))
    with pytest.raises(ValueError): runtime.validate_prepared(output)


def mocked_runtime(output, monkeypatch, *, fault=None, limited=False):
    state = services(monkeypatch); frozen = runtime.validate_prepared(output); bundle = output/'job_bundle'
    cid = 'a'*64; commands = []
    def actual():
        return {'Id': cid, 'Name': '/sf-producer16-integer-'+frozen['request']['nonce'], 'Image': runtime.IMAGE_ID,
            'NanoCpus': (2 if fault == 'two_cpu' else 16)*10**9, 'Memory': 32*1024**3, 'PidsLimit': 256,
            'NetworkMode': 'none', 'Privileged': False, 'User': '0', 'WorkingDir': '/app',
            'CapDrop': ['ALL'], 'CapAdd': ['CAP_DAC_OVERRIDE'], 'SecurityOpt': ['no-new-privileges'],
            'Entrypoint': ['/usr/bin/python3'], 'Cmd': ['/app/run.py'],
            'Mounts': [{'Type': 'bind', 'Source': str(bundle), 'Destination': '/app', 'RW': True}],
            'State': {'Status': 'exited' if state.get('attached') else 'created', 'Running': False,
                'ExitCode': 0, 'OOMKilled': False}}
    def command(args, *, timeout=30):
        commands.append(args)
        if args[:3] == ['docker', 'image', 'inspect']: return subprocess.CompletedProcess(args, 0, runtime.IMAGE_ID+'\n', '')
        if args[:2] == ['docker', 'create']:
            assert args[args.index('--cpus')+1] == '16'
            assert args[args.index('--memory')+1] == str(32*1024**3)
            return subprocess.CompletedProcess(args, 0, cid+'\n', '')
        if args[:2] == ['docker', 'inspect']:
            return (subprocess.CompletedProcess(args, 1, '', 'Error: no such object') if state.get('cleaned')
                else subprocess.CompletedProcess(args, 0, json.dumps(actual()), ''))
        if args[:2] == ['docker', 'rm']:
            state['cleaned'] = True; return subprocess.CompletedProcess(args, 0, cid, '')
        raise AssertionError(args)
    def attach(args, stdout, stderr, timeout):
        state['attached'] = True; assert timeout == 3720
        stdout.write_text('Offline mock native stdout\n'); stderr.write_text('')
        solver = {'checked_optimal': not limited, 'status': 'FEASIBLE' if limited else 'OPTIMAL',
            'plan': {'P001': 1, 'P002': 0}, 'objective_pence': 7, 'exclude_plan': frozen['request']['exclude_plan'],
            'model_sha256': frozen['model_canonical_sha256'], 'specification_sha256': matrix()['specification_sha256'],
            'universe_sha256': matrix()['universe_sha256'], 'gap_parameters': {'relative': 0, 'absolute': 0},
            'threads': 2 if fault == 'two_workers' else 16, 'time_limit_seconds': 3600}
        for name, value in (('solver_result.json', solver), ('runtime_result.json', {
            'completed': True, 'backend': 'cp_sat', 'financial_forward_executed': False,
            'model_canonical_sha256': frozen['model_canonical_sha256'], 'threads': 16,
            'gap_requested': 0, 'distribution_versions': runtime.DISTRIBUTIONS})):
            (bundle/name).write_text(json.dumps(value))
        for name in ('solver.log', 'native_model.pbtxt', 'native_model.pbtxt.parameters.pbtxt'):
            (bundle/name).write_text('Offline mock native artifact\n')
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(runtime, '_command', command); monkeypatch.setattr(runtime, '_attach', attach)
    return state, commands


def test_mocked_runtime_retains_all_native_resource_cleanup_and_reference_gates(prepared, monkeypatch):
    output, prep = prepared(); state, commands = mocked_runtime(output, monkeypatch)
    terminal = runtime.execute_prepared(output)
    checked = entry.validate_solver_receipt(prep, terminal, model=runtime.reference(prepared.model), backend='cp_sat')
    assert checked['checked_optimal'] is True
    assert checked['matrix_result_check']['exact_matrix_plan_check']['all_integer_rows_checked'] == 1
    assert state['cleaned'] and state['released'] and state['closed'] and state['stopped']
    with pytest.raises(ValueError): runtime.execute_prepared(output)


@pytest.mark.parametrize('fault', ['two_cpu', 'two_workers'])
def test_mocked_runtime_rejects_any_actual_resource_or_worker_mismatch(prepared, monkeypatch, fault):
    output, prep = prepared(); state, _ = mocked_runtime(output, monkeypatch, fault=fault)
    with pytest.raises(runtime.OptimizationRuntimeError) as error: runtime.execute_prepared(output)
    assert runtime._read(error.value.receipt['path'])['status'] == 'execution_failed'
    assert state['cleaned'] and state['released']


def test_limit_preserved_as_nonoptimal_never_a_zero_or_reference(prepared, monkeypatch):
    output, prep = prepared(); mocked_runtime(output, monkeypatch, limited=True)
    terminal = runtime.execute_prepared(output); value = runtime._read(terminal['path'])
    assert value['status'] == 'reference_not_proven_optimal'
    checked = entry.validate_solver_receipt(prep, terminal, model=runtime.reference(prepared.model), backend='cp_sat')
    assert checked['checked_optimal'] is False and value['qualified'] is False


def test_source_adapter_keeps_original_lo_engine_and_all_audit_functions():
    assert builder.SOURCE_KIND == 'independently_verified_linear_capital_producer16_native_source'
    assert builder.DEFAULT_PROFILE.name == 'entity_group_large_v2.yaml'
    assert builder._reference_provider().KIND == entry.KIND
    before = ast.parse((ROOT/'scripts/build_linear_capital_source.py').read_text())
    after = builder.adapted_ast()
    originals = {n.name: ast.dump(n) for n in before.body if isinstance(n, ast.FunctionDef)}
    adapted = {n.name: ast.dump(n) for n in after.body if isinstance(n, ast.FunctionDef)}
    for name in set(originals)-{'_reference_provider', '_validate_reference'}:
        assert originals[name] == adapted[name]
    assert str(runtime.PROFILE) in builder.recipes()
    assert str(ROOT/'scripts/build_linear_capital_source.py') in builder.recipes()


def test_exact_result_crosschecked_against_both_complete_matrices(monkeypatch, tmp_path):
    raw = tmp_path/'job.json'; raw.write_text(json.dumps({'producer_profile': runtime.profile_reference()})); job = runtime.reference(raw)
    a = matrix(); b = deepcopy(a)
    a['rows'] = [dict(a['rows'][0], id=f'capacity{i:04d}') for i in range(881)]
    b['rows'] = deepcopy(a['rows']); b['universe_sha256'] = '3'*64
    solver = {'checked_optimal': True, 'status': 'OPTIMAL', 'plan': {'P001': 1, 'P002': 0}, 'objective_pence': 7}
    monkeypatch.setattr(entry, 'validate_solver_receipt', lambda *_a, **_k: {'checked_optimal': True, 'solver': solver})
    finance = {'models': {'B': job}, 'model_values': {'A': a, 'B': b}}
    checked, cross = entry._checked_job(job, job, finance, None)
    assert set(cross) == {'A', 'B'}
    a['rows'][0]['limit'] = 1
    with pytest.raises(ValueError, match='violates'): entry._checked_job(job, job, finance, None)


def outer_fixture(tmp_path, monkeypatch, *, limited=False, tie=False, finance_fail=False):
    """Explicit fake finance/runtime boundary; never an actual global proof."""
    output = tmp_path/'outer'; output.mkdir()
    ids = [f'P{i:03d}' for i in range(1, 241)]
    winner = {pid: int(i < 107) for i, pid in enumerate(ids)}
    runner = deepcopy(winner); runner['P001'] = 0
    raw = tmp_path/'fixture.json'; raw.write_text('{"explicit_fake_boundary":true}')
    ref = entry.reference(raw)
    finance = {'terminal': ref, 'specification': ref, 'raw_preparation': ref, 'universe_A': ref, 'universe_B': ref,
        'public': {'project_ids': ids}, 'A': {'fixture': 'A'}, 'B': {'fixture': 'B'}, 'models': {'A': ref, 'B': ref}}
    jobdir = output/'jobs/best'; jobdir.mkdir(parents=True)
    best = entry.write(jobdir/'preparation.json', {'phase': 'best', 'producer_profile': runtime.profile_reference()})
    entry.write(output/'preparation.json', {'explicit_fake_boundary': True})
    frozen = {'best_preparation': best, 'private_density_gate': {
        'minimum': 80, 'maximum': 160, 'public_cardinality_constraint': False},
        'recipe': {str(raw): ref}}
    monkeypatch.setattr(entry, 'validate_prepared', lambda _: (frozen, finance))
    monkeypatch.setattr(entry.spec, 'validate_plan', lambda _public, value: value)
    calls = []
    def prepare(model, folder, *, backend, time_limit_seconds, exclude_plan):
        assert model == ref['path'] and backend == 'cp_sat' and time_limit_seconds == 3600 and exclude_plan == winner
        calls.append('prepare_runner'); folder.mkdir(parents=True)
        return entry.write(folder/'preparation.json', {'phase': 'runner', 'producer_profile': runtime.profile_reference()})
    def execute(folder):
        phase = entry.read(folder/'preparation.json')['phase']; calls.append(phase)
        return entry.write(folder/'terminal.json', {'phase': phase, 'explicit_fake_runtime_boundary': True})
    def checked(job, terminal, actual_finance, excluded):
        phase = entry.read(terminal)['phase']
        if limited and phase == 'best': raise ValueError('Explicit fake limited first solve is not optimal')
        assert excluded == (None if phase == 'best' else winner)
        value = {'checked_optimal': True, 'solver': {'plan': winner if phase == 'best' else runner,
            'objective_pence': 1000 if phase == 'best' or tie else 999}}
        return value, {'A': {'rows': 881}, 'B': {'rows': 881}}
    def plans(public, a, b, choices, *, require_feasible):
        assert require_feasible is True and [p['id'] for p in choices] == ['winner', 'runner']
        assert a == finance['A'] and b == finance['B']
        return {'kind': 'posted_universe_plan_aggregation_crosscheck', 'passed': not finance_fail,
            'require_group_feasible': True, 'plan_count': 2,
            'plans': [{'id': p['id'], 'plan': p['plan'], 'passed': True, 'errors': [], 'differences': [],
                'A': {'feasible': True, 'objective_pence': 1000 if p['id'] == 'winner' else 999},
                'B': {'feasible': True, 'objective_pence': 1000 if p['id'] == 'winner' else 999}} for p in choices]}
    monkeypatch.setattr(runtime, 'prepare', prepare); monkeypatch.setattr(runtime, 'execute_prepared', execute)
    monkeypatch.setattr(entry, '_checked_job', checked)
    monkeypatch.setattr(entry.finance_crosscheck, 'compare_plans', plans)
    state = services(monkeypatch)
    return output, calls, state, winner


def test_one_global_best_and_runner_with_dual_finance_complete_envelope(tmp_path, monkeypatch):
    output, calls, state, winner = outer_fixture(tmp_path, monkeypatch)
    terminal = entry.execute_prepared(output); value = entry.read(terminal)
    assert value['passed'] is True and value['winner_plan'] == winner
    assert calls == ['best', 'prepare_runner', 'runner']
    assert value['global_search_implementation_count'] == 1
    assert value['independent_second_global_search_claimed'] is False
    assert value['independent_integer_matrices'] == value['independent_financial_implementations'] == 2
    assert value['gap_pence'] == 1 and value['selected_project_count'] == 107
    assert set(value['solver_receipts']) == {'best', 'runner'}
    assert value['runtime_profile']['cpus'] == value['runtime_profile']['threads'] == 16
    assert value['qualified'] is False and value['LO_calls'] == value['model_calls'] == 0
    assert entry.validate_completed(terminal) == value
    assert state['released'] and state['stopped'] and state['closed']
    value['gap_pence'] = 0; Path(terminal['path']).write_text(json.dumps(value))
    with pytest.raises(ValueError, match='gap'): entry.validate_completed(entry.reference(terminal['path']))


@pytest.mark.parametrize('case', ['limited', 'tie', 'financial_disagreement'])
def test_limit_tie_or_financial_failure_preserved_without_retries(tmp_path, monkeypatch, case):
    output, calls, state, _ = outer_fixture(tmp_path, monkeypatch, limited=case == 'limited',
        tie=case == 'tie', finance_fail=case == 'financial_disagreement')
    terminal = entry.execute_prepared(output); value = entry.read(terminal)
    assert value['passed'] is False and value['qualified'] is False
    assert calls == (['best'] if case == 'limited' else ['best', 'prepare_runner', 'runner'])
    assert state['released'] and state['stopped'] and state['closed']
    assert entry.read(output/'failure.json')['failure_is_not_model_zero'] is True
    with pytest.raises(ValueError, match='no retry'): entry.execute_prepared(output)


def test_terminal_write_failure_still_releases_outer_lease_and_services(tmp_path, monkeypatch):
    output, calls, state, _ = outer_fixture(tmp_path, monkeypatch)
    original = entry.write
    def fail(path, value):
        if Path(path) == output/'terminal.json': raise OSError('Explicit offline filesystem failure')
        return original(path, value)
    monkeypatch.setattr(entry, 'write', fail)
    with pytest.raises(OSError): entry.execute_prepared(output)
    assert state['released'] and state['stopped'] and state['closed']


def test_source_joins_two_named_plan_aggregates_without_second_global_runner(tmp_path):
    p = tmp_path/'universe.json'; p.write_text('{"independent_retained_universe":true}')
    report = {'kind': 'posted_universe_plan_aggregation_crosscheck', 'passed': True, 'require_group_feasible': True,
        'plan_count': 2, 'plans': [{'id': 'winner', 'plan': {'P001': 1}, 'passed': True, 'errors': [], 'differences': [],
            'A': {'feasible': True, 'objective_pence': 7}, 'B': {'feasible': True, 'objective_pence': 7}}, {'id': 'runner'}]}
    q = tmp_path/'plans.json'; q.write_text(json.dumps(report))
    proof = {'universe_A': runtime.reference(p), 'universe_B': runtime.reference(p),
        'reference_validation': runtime.reference(q), 'winner_plan': {'P001': 1}, 'winner_objective_pence': 7}
    a, b = builder.expected_results(proof)
    assert a['plan'] == b['plan'] == {'P001': 1} and a['objective_pence'] == b['objective_pence'] == 7
    report['plan_count'] = 3; q.write_text(json.dumps(report)); proof['reference_validation'] = runtime.reference(q)
    with pytest.raises(ValueError): builder.expected_results(proof)
