"""Exact toy enumeration and mocked native/resource lifecycle; zero actual solves."""
from copy import deepcopy
import importlib.util
from itertools import product
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sheets_factory.workbook.linear_capital_portfolio import unique_feasibility_research as query
from test_linear_capital_optimization_runtime import services

ROOT = Path(__file__).resolve().parents[1]


def matrix(*, tied=False):
    return {'kind': 'linear_capital_portfolio_direct_binary_integer_model', 'version': 1,
        'project_ids': ['P001', 'P002', 'P003'], 'objective_pence': [5, 5 if tied else 4, -2],
        'rows': [{'id': 'capacity:cash', 'family': 'capacity', 'scenario_id': None,
            'year': None, 'coefficients': [1, 1, 0], 'limit': 1}],
        'specification_sha256': '1'*64, 'universe_sha256': '2'*64}


WINNER = {'P001': 1, 'P002': 0, 'P003': 0}


def reported(model, status, plan=None):
    return {'query': query.query(model, WINNER), 'status': status, 'checked_optimal': False,
        'plan': plan, 'objective_pence': None if plan is None else sum(c*plan[p] for c, p in zip(model['objective_pence'], model['project_ids']))}


@pytest.mark.parametrize('tied', [False, True])
def test_exact_enumeration_matches_all_original_rows_threshold_and_only_one_full_exclusion(tied):
    model = matrix(tied=tied); before = deepcopy(model); declaration = query.query(model, WINNER)
    actual = []; expected = []
    for bits in product((0, 1), repeat=3):
        plan = dict(zip(model['project_ids'], bits))
        original_ok = all(sum(c*b for c, b in zip(row['coefficients'], bits)) <= row['limit'] for row in model['rows'])
        threshold_ok = sum(c*b for c, b in zip(model['objective_pence'], bits)) >= 5
        if original_ok and threshold_ok and plan != WINNER: expected.append(plan)
        if all(sum(c*b for c, b in zip(row['coefficients'], bits)) <= row['limit'] for row in [*model['rows'], *declaration['added_le_rows']]): actual.append(plan)
        nogood = declaration['added_le_rows'][1]
        assert (sum(c*b for c, b in zip(nogood['coefficients'], bits)) <= nogood['limit']) == (plan != WINNER)
    assert model == before and actual == expected
    assert len(actual) == int(tied)
    assert declaration['objective_optimization'] is False and len(declaration['added_le_rows']) == 2


def test_native_infeasible_is_unique_research_evidence_and_unknown_never_proves_anything():
    for status in ('INFEASIBLE', 'UNKNOWN', 'MODEL_INVALID'):
        checked = query.check_result(matrix(), reported(matrix(), status), WINNER)
        assert checked['unique_by_native_infeasibility'] is (status == 'INFEASIBLE')
        assert checked['ambiguous_tied_optimum'] is False
        assert checked['exact_runner_objective'] is checked['exact_gap_pence'] is None
        assert checked['original_v1_reference_passed'] is checked['formal_global_certificate'] is checked['qualified'] is False


@pytest.mark.parametrize('status', ['FEASIBLE', 'OPTIMAL'])
def test_cp_sat_feasibility_optimal_status_only_means_tied_alternative(status):
    model = matrix(tied=True); other = {'P001': 0, 'P002': 1, 'P003': 0}
    checked = query.check_result(model, reported(model, status, other), WINNER)
    assert checked['ambiguous_tied_optimum'] is True and checked['unique_by_native_infeasibility'] is False
    assert checked['checked_optimal'] is False and checked['exact_matrix_plan_check']['all_integer_rows_checked'] == 1


@pytest.mark.parametrize('fault', ['winner', 'original_row', 'threshold', 'above_best', 'incomplete', 'bool', 'query', 'objective', 'infeasible_primal', 'feasible_missing'])
def test_false_primal_or_status_claims_are_rejected(fault):
    model = matrix(tied=True); other = {'P001': 0, 'P002': 1, 'P003': 0}
    if fault == 'above_best': model['objective_pence'][1] = 6
    if fault == 'winner': other = WINNER
    if fault == 'original_row': other = {'P001': 1, 'P002': 1, 'P003': 0}
    if fault == 'threshold': other = {'P001': 0, 'P002': 0, 'P003': 1}
    result = reported(model, 'FEASIBLE', other)
    if fault == 'incomplete': del result['plan']['P003']
    if fault == 'bool': result['plan']['P003'] = False
    if fault == 'query': result['query']['threshold_pence'] -= 1
    if fault == 'objective': result['objective_pence'] += 1
    if fault == 'infeasible_primal': result['status'] = 'INFEASIBLE'
    if fault == 'feasible_missing': result['plan'] = result['objective_pence'] = None
    with pytest.raises(ValueError): query.check_result(model, result, WINNER)


def test_native_query_code_has_no_optimizer_objective_and_every_original_row_is_iterated():
    import ast
    tree = ast.parse(Path(query.__file__).read_text())
    solver = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'solve_query')
    calls = [n for n in ast.walk(solver) if isinstance(n, ast.Call)]
    assert not any(isinstance(n.func, ast.Attribute) and n.func.attr in {'maximize', 'minimize', 'setObjective'} for n in calls)
    assert sum(isinstance(n, ast.For) and ast.unparse(n.iter) == "[*model['rows'], *declaration['added_le_rows']]" for n in ast.walk(solver)) == 1
    assert sum(isinstance(n, ast.For) and ast.unparse(n.iter) == "enumerate([*model['rows'], *declaration['added_le_rows']])" for n in ast.walk(solver)) == 1


@pytest.mark.parametrize('seconds,workers', [(899, 16), (900, 2), (True, 16), (900, True)])
def test_bad_limits_fail_before_native_import(tmp_path, monkeypatch, seconds, workers):
    monkeypatch.setattr(query.importlib.metadata, 'version', lambda *_: pytest.fail('No native import before request validation'))
    with pytest.raises(ValueError): query.solve_query(matrix(), backend='cp_sat', time_limit_seconds=seconds,
        threads=workers, exclude_plan=WINNER, log_path=tmp_path/'solver.log', model_path=tmp_path/'model.pbtxt')


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    runtime = query.make_runtime(); vendor = tmp_path/'vendor'; vendor.mkdir(); (vendor/'dummy.py').write_text('# Mock only\n')
    monkeypatch.setattr(runtime, 'VENDOR_SITE_PACKAGES', vendor); monkeypatch.setattr(runtime, 'VENDOR_ROOTS', {'dummy.py'})
    source = tmp_path/'model.json'; source.write_text(json.dumps(matrix(tied=True)))
    def make(backend):
        output = tmp_path/backend
        receipt = runtime.prepare(source, output, backend=backend, time_limit_seconds=900,
            exclude_plan=WINNER, vendor_site_packages=vendor)
        return output, receipt
    return runtime, make


def mock_lifecycle(runtime, output, monkeypatch, status, fault):
    state = services(monkeypatch); commands = []; frozen = runtime.validate_prepared(output)
    backend = frozen['request']['backend']; bundle = output/'job_bundle'; cid = 'c'*64
    def actual():
        return {'Id': cid, 'Name': '/sf-unique-query-'+frozen['request']['nonce'], 'Image': runtime.IMAGE_ID,
            'NanoCpus': (2 if fault == 'cpu' else 16)*10**9, 'Memory': 32*1024**3, 'PidsLimit': 256,
            'NetworkMode': 'none', 'Privileged': False, 'User': '0', 'WorkingDir': '/app',
            'CapDrop': ['ALL'], 'CapAdd': ['DAC_OVERRIDE'], 'SecurityOpt': ['no-new-privileges'],
            'Entrypoint': ['/usr/bin/python3'], 'Cmd': ['/app/run.py'],
            'Mounts': [{'Type': 'bind', 'Source': str(bundle), 'Destination': '/app', 'RW': True}],
            'State': {'Status': 'exited' if state.get('attached') else 'created', 'Running': False,
                'ExitCode': 0, 'OOMKilled': fault == 'oom'}}
    def command(args, *, timeout=30):
        commands.append(args)
        if args[:3] == ['docker', 'image', 'inspect']: return subprocess.CompletedProcess(args, 0, runtime.IMAGE_ID+'\n', '')
        if args[:2] == ['docker', 'create']:
            assert args[args.index('--cpus')+1] == '16'; return subprocess.CompletedProcess(args, 0, cid+'\n', '')
        if args[:2] == ['docker', 'inspect']:
            return subprocess.CompletedProcess(args, 1, '', 'No such object') if state.get('cleaned') else subprocess.CompletedProcess(args, 0, json.dumps(actual()), '')
        if args[:2] == ['docker', 'rm']:
            assert args[-1] == cid; state['cleaned'] = fault != 'cleanup'; return subprocess.CompletedProcess(args, int(fault == 'cleanup'), cid, '')
        raise AssertionError(args)
    def attach(args, stdout, stderr, timeout):
        assert args == ['docker', 'start', '--attach', cid] and timeout == 1020
        state['attached'] = True; stdout.write_text('Mock only\n'); stderr.write_text('')
        model = matrix(tied=True)
        result = reported(model, status, {'P001': 0, 'P002': 1, 'P003': 0} if status == 'FEASIBLE' else None)
        result.update(model_sha256=frozen['model_canonical_sha256'], specification_sha256=model['specification_sha256'],
            universe_sha256=model['universe_sha256'], exclude_plan=WINNER, threads=16, time_limit_seconds=900,
            gap_parameters={'relative': 0, 'absolute': 0}, feasibility_tolerance_changed=False,
            parameters={'limits/time': 900.0, 'limits/gap': 0.0, 'limits/absgap': 0.0, 'parallel/maxnthreads': 16, 'lp/threads': 16})
        (bundle/'solver_result.json').write_text(json.dumps(result))
        (bundle/'runtime_result.json').write_text(json.dumps({'completed': True, 'backend': backend,
            'financial_forward_executed': False, 'model_canonical_sha256': frozen['model_canonical_sha256'],
            'threads': 16, 'gap_requested': 0, 'distribution_versions': runtime.DISTRIBUTIONS}))
        native_name = runtime.BACKENDS[backend][2]
        for name in ['solver.log', native_name, *([native_name+'.parameters.pbtxt'] if backend == 'cp_sat' else [])]:
            (bundle/name).write_text('Mock only\n')
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(runtime, '_command', command); monkeypatch.setattr(runtime, '_attach', attach)
    return state, commands


@pytest.mark.parametrize('backend', ['cp_sat', 'scip'])
@pytest.mark.parametrize('status', ['INFEASIBLE', 'FEASIBLE', 'UNKNOWN'])
def test_mocked_native_lifecycle_preserves_status_resource_evidence_cleanup_and_no_retry(prepared, monkeypatch, backend, status):
    runtime, make = prepared; output, _ = make(backend)
    state, commands = mock_lifecycle(runtime, output, monkeypatch, status, None)
    receipt = runtime.execute_prepared(output); value = runtime._read(receipt['path'])
    assert value['matrix_result_check']['unique_by_native_infeasibility'] is (status == 'INFEASIBLE')
    assert value['matrix_result_check']['ambiguous_tied_optimum'] is (status == 'FEASIBLE')
    assert state['cleaned'] and state['released'] and state['stopped'] and state['closed']
    assert len([c for c in commands if c[:2] == ['docker', 'create']]) == 1
    assert len([c for c in commands if c[:2] == ['docker', 'rm']]) == 1
    with pytest.raises(ValueError): runtime.execute_prepared(output)


@pytest.mark.parametrize('fault', ['cpu', 'oom', 'cleanup'])
def test_mocked_resource_exit_or_cleanup_failure_cannot_prove_uniqueness(prepared, monkeypatch, fault):
    runtime, make = prepared; output, _ = make('cp_sat')
    state, _ = mock_lifecycle(runtime, output, monkeypatch, 'INFEASIBLE', fault)
    with pytest.raises(runtime.OptimizationRuntimeError) as error: runtime.execute_prepared(output)
    assert runtime._read(error.value.receipt['path'])['status'] == 'execution_failed'
    assert state['released'] and state['stopped']


def entry_module():
    definition = importlib.util.spec_from_file_location('_unique_query_entry_test', ROOT/'scripts/run_linear_capital_unique_feasibility_research.py')
    entry = importlib.util.module_from_spec(definition); definition.loader.exec_module(entry)
    return entry


def test_root_review_hash_must_match_before_validation_or_any_native_call(tmp_path, monkeypatch):
    entry = entry_module()
    (tmp_path/'freeze.json').write_text('{}\n')
    monkeypatch.setattr(entry, 'validate_prepared', lambda *_: pytest.fail('Must reject an unreviewed freeze first'))
    with pytest.raises(ValueError, match='reviewed'): entry.execute_prepared(tmp_path, '0'*64)


@pytest.mark.parametrize('fault', [None, 'native', 'validation', 'dashboard_start', 'dashboard_stop'])
def test_run_panel_lease_backend_progress_and_cleanup_on_success_and_failure(tmp_path, monkeypatch, fault):
    import sheets_factory.dashboard as dashboard
    entry = entry_module(); state = services(monkeypatch); calls = []
    freeze = {'probe_order': ['cp_sat', 'scip']}
    freeze_ref = entry.runtime._write(tmp_path/'freeze.json', freeze)
    monkeypatch.setattr(entry, 'validate_prepared', lambda *_: (freeze, {}))
    original_server = dashboard.DashboardServer
    class Server(original_server):
        def start(self):
            state['start_attempted'] = True
            if fault == 'dashboard_start': raise RuntimeError('Mock dashboard start failure')
            return super().start()
        def stop(self):
            super().stop()
            if fault == 'dashboard_stop': raise RuntimeError('Mock dashboard stop failure')
    monkeypatch.setattr(dashboard, 'DashboardServer', Server)
    def execute(folder):
        backend = folder.name; calls.append(backend)
        assert state['leased'] and state['start_attempted'] and (tmp_path/'dashboard.json').exists()
        assert state['active_stage'] == 'research_query_'+backend and state['node']['status'] == 'running'
        assert state['backend_statuses'][backend] == 'running'
        receipt = {'path': str(folder/'mock_native_terminal.json'), 'sha256': '0'*64, 'bytes': 0}
        if fault == 'native': raise entry.runtime.OptimizationRuntimeError('Mock native failure', receipt)
        return receipt
    def validate(_freeze, _finance, backend, receipt):
        if fault == 'validation': raise ValueError('Mock native validation failure')
        return {'checks': {'A': {'status': 'research_unique_by_native_infeasibility',
            'unique_by_native_infeasibility': True, 'ambiguous_tied_optimum': False}}}
    monkeypatch.setattr(entry.runtime, 'execute_prepared', execute)
    monkeypatch.setattr(entry, 'validate_actual', validate)
    terminal_ref = entry.execute_prepared(tmp_path, freeze_ref['sha256']); terminal = entry.read(terminal_ref)
    assert state['released'] and state['closed'] and state['stopped']
    assert terminal['execution_failed'] is (fault is not None)
    assert terminal['unique_by_native_infeasibility'] is (fault is None)
    assert terminal['ambiguous_tied_optimum'] is False
    assert terminal['elapsed_seconds'] >= 0
    if fault == 'dashboard_start':
        assert calls == [] and terminal['dashboard_url'] is None
        assert terminal['backend_statuses'] == {'cp_sat': 'pending', 'scip': 'pending'}
    else:
        assert terminal['dashboard_url'] == 'http://127.0.0.1:12345/'
        assert calls == (['cp_sat'] if fault in ('native', 'validation') else ['cp_sat', 'scip'])
        assert set(terminal['backend_duration_seconds']) == set(calls)
        assert all(v >= 0 for v in terminal['backend_duration_seconds'].values())
        assert all(v['thread_stopped'] and not v['errors'] for v in terminal['backend_progress'].values())
    if fault in ('native', 'validation'):
        assert terminal['backend_statuses'] == {'cp_sat': 'execution_failed', 'scip': 'pending'}
    if fault == 'native': assert set(terminal['solver_receipts']) == {'cp_sat'}
    if fault == 'dashboard_stop': assert terminal['lifecycle_cleanup_errors'][0]['stage'] == 'dashboard_stop'
    before = (tmp_path/'terminal.json').read_bytes()
    with pytest.raises(ValueError, match='first research attempt'): entry.execute_prepared(tmp_path, freeze_ref['sha256'])
    assert (tmp_path/'terminal.json').read_bytes() == before


def test_installed_cp_sat_constructs_actual_query_and_supports_both_objective_fields_without_solve(tmp_path):
    # Exercise the installed 9.14 API and the actual query-building branch. Block
    # solver construction, so neither a toy nor a production native solve can run.
    vendor = ROOT/'outputs/tmp/linear-solver-914-py312/lib/python3.12/site-packages'
    if not vendor.is_dir(): pytest.skip('The approved offline vendor closure is absent')
    data = tmp_path/'input.json'; data.write_text(json.dumps({'model': matrix(tied=True), 'winner': WINNER}))
    program = r'''
import hashlib,json,sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path[:0]=[sys.argv[1],sys.argv[2]]
from ortools.sat.python import cp_model
from sheets_factory.workbook.linear_capital_portfolio import unique_feasibility_research as query
source=Path(cp_model.__file__)
assert hashlib.sha256(source.read_bytes()).hexdigest()=='cce0a7f2eee52b0d42f58c1098d2e1f629c0230e1ac929d89b7d8a964c40592a'
data=json.loads(Path(sys.argv[3]).read_text()); built=[]
original_model=cp_model.CpModel
def model():
    value=original_model(); built.append(value); return value
class NoSolverConstruction(Exception): pass
def forbidden_solver(): raise NoSolverConstruction('No solver or solve permitted')
cp_model.CpModel=model; cp_model.CpSolver=forbidden_solver
try:
    query.solve_query(data['model'],backend='cp_sat',time_limit_seconds=900,threads=16,
        exclude_plan=data['winner'],log_path=Path(sys.argv[4])/'solver.log',model_path=Path(sys.argv[4])/'model.pbtxt')
except NoSolverConstruction: pass
else: raise AssertionError('The actual query must stop before solver construction')
assert len(built)==1
native=built[0]; proto=native.proto
assert not proto.HasField('objective') and not proto.HasField('floating_point_objective') and not native.has_objective()
assert [v.name for v in proto.variables]==data['model']['project_ids']
assert all(list(v.domain)==[0,1] for v in proto.variables)
expected=[*data['model']['rows'],*query.query(data['model'],data['winner'])['added_le_rows']]
assert len(proto.constraints)==len(expected)
for actual,row in zip(proto.constraints,expected):
    coefficients=[0]*len(proto.variables)
    for index,coefficient in zip(actual.linear.vars,actual.linear.coeffs): coefficients[index]=coefficient
    assert actual.name==row['id'] and coefficients==row['coefficients']
    assert actual.linear.domain[-1]==row['limit']
print(json.dumps({'installed_api':'9.14.6206','native_variables':len(proto.variables),'native_le_rows':len(proto.constraints),
    'objective_fields_absent':True,'actual_solver_calls':0}))
'''
    result = subprocess.run([sys.executable, '-I', '-c', program, str(vendor), str(ROOT/'src'), str(data), str(tmp_path)],
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'installed_api': '9.14.6206', 'native_variables': 3,
        'native_le_rows': 3, 'objective_fields_absent': True, 'actual_solver_calls': 0}
