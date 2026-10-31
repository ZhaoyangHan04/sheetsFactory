"""Mocked native lifecycle and real pure integer gates; no services."""
from copy import deepcopy
import json
from pathlib import Path
import threading
import time

import pytest

from sheets_factory.workbook.linear_capital_sensitivity import reference as ref, runtime600


def matrix():
    rows = []
    for family, count in ref.spec.PRODUCTION_COUNTS.items():
        for i in range(count):
            rows.append({'id': family + ':' + str(i).zfill(3), 'family': family,
                'scenario_id': None, 'year': None, 'coefficients': [0] * 360, 'limit': 100})
    return {'kind': 'linear_capital_scaled_direct_binary_integer_model', 'version': 2,
        'project_ids': [f'P{i:03d}' for i in range(1, 361)], 'objective_pence': [-1] * 360,
        'rows': sorted(rows, key=lambda r: r['id']), 'specification_sha256': 'a' * 64, 'universe_sha256': 'b' * 64}


def store(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    return ref.write(path, value)


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setattr(ref, 'ROOT', tmp_path)
    model = matrix()
    rows = [{'case': dict(c), 'A': model, 'B': model} for c in ref.contract.CASES]
    incoming = {'prospective': store(tmp_path / 'prospective.json', {'test_only': True}),
        'declaration': {'test_only': True}, 'shared': {}, 'cases': rows}
    monkeypatch.setattr(ref, '_checked_input', lambda _: incoming)
    monkeypatch.setattr(ref, 'recipes', lambda: {})
    return tmp_path / 'outputs/prepared', incoming


def test_real_resource_policy_ast_vendor_root_and_no_original_mutation():
    prior = runtime600.base.prepare
    runtime600.adapted_ast()
    assert runtime600.base.prepare is prior
    assert runtime600.ROOT == Path(__file__).resolve().parents[1]
    assert runtime600.VENDOR_SITE_PACKAGES == runtime600.ROOT / 'outputs/tmp/linear-solver-914-py312/lib/python3.12/site-packages'
    assert runtime600.DISTRIBUTIONS['ortools'] == '9.14.6206'
    assert runtime600.DISTRIBUTIONS['numpy'] == '1.26.4'
    assert set(runtime600.BACKENDS) == {'cp_sat'}
    assert len(runtime600._source_files()) == 6
    p = runtime600.policy()
    assert p['producer'] == {'cpus': 16, 'memory_bytes': 32 * 1024**3, 'pids_limit': 256,
        'threads': 16, 'network': 'none', 'backend': 'cp_sat', 'solver_seconds_per_attempt': 600,
        'operational_timeout_seconds': 720, 'relative_gap': 0, 'absolute_gap': 0, 'automatic_retries': 0}
    assert p['max_parallel_cases'] == 2 and p['maximum_native_job_invocations'] == 18
    assert p['cardinality_admission'] is False and p['prior_incumbent_or_warm_hint'] is False
    runtime600.profile_reference()


def test_profile_rejects_boolean_zero_and_any_resource_drift(tmp_path, monkeypatch):
    for change in ('cpu', 'bool_gap', 'retries'):
        p = runtime600.policy()
        if change == 'cpu': p['producer']['cpus'] = 2
        elif change == 'bool_gap': p['producer']['relative_gap'] = False
        else: p['producer']['automatic_retries'] = 1
        path = tmp_path / (change + '.json'); path.write_text(json.dumps(p))
        monkeypatch.setattr(runtime600, 'PROFILE', path)
        with pytest.raises(ValueError): runtime600.profile_reference()


def test_runtime_rejects_incomplete_or_wrong_family_census():
    m = matrix(); runtime600.validate_model(m)
    for key in ('rows', 'project_ids'):
        wrong = deepcopy(m); wrong[key].pop()
        with pytest.raises(ValueError): runtime600.validate_model(wrong)


def test_all18_case_model_hashes_exist_before_first_native_preparation(context, monkeypatch):
    output, inputs = context; calls = []
    monkeypatch.setattr(runtime600, 'execute_prepared', lambda *_: pytest.fail('prepare cannot execute native'))
    def prepare(model, folder, **kwargs):
        inventory = ref.read(output / 'all_nine_model_inventory.json')
        assert len(inventory['cases']) == 9 and inventory['native_preparations_started'] == 0
        for row in inventory['cases']:
            for side in ('A', 'B'):
                assert ref._sha(ref.read(row['models'][side])) == row['model_logical_sha256'][side]
        assert kwargs == {'backend': 'cp_sat', 'time_limit_seconds': 600}
        calls.append(model)
        return store(folder / 'preparation.json', {'test_only': True})
    monkeypatch.setattr(runtime600, 'prepare', prepare)
    result = ref.read(ref.prepare(inputs['prospective'], output))
    assert len(calls) == 9 and set(result['best_preparations']) == set(result['case_order'])
    assert result['native_solver_calls'] == result['model_calls'] == 0
    assert not (output / 'started.json').exists()
    with pytest.raises(ValueError): ref.prepare(inputs['prospective'], output)


def case_fixture(tmp_path):
    output = tmp_path; folder = output / 'cases/B90_C90'; model = matrix()
    row = {'case': dict(ref.contract.CASES[0]), 'models': {side: store(folder / ('model_' + side + '.json'), model) for side in ('A', 'B')}}
    store(output / 'preparation.json', {'test_only': True})
    job = store(folder / 'jobs/best/preparation.json', {'test_only': True})
    return output, row, {'best_preparations': {'B90_C90': job}}, model


@pytest.mark.parametrize('optimal', [False, True])
def test_native_optimal_and_every_independent_integer_row_are_required(tmp_path, monkeypatch, optimal):
    _, row, frozen, model = case_fixture(tmp_path)
    plan = dict.fromkeys(model['project_ids'], 0)
    receipt = store(tmp_path / 'native.json', {'private_reference_time_limit_seconds': 600, 'operational_timeout_seconds': 720})
    monkeypatch.setattr(ref, '_job_preparation', lambda *args: None)
    monkeypatch.setattr(ref, 'validate_solver_receipt', lambda *args, **kwargs:
        {'checked_optimal': optimal, 'solver': {'plan': plan, 'objective_pence': 0}})
    if optimal:
        result = ref._checked_job(frozen['best_preparations']['B90_C90'], receipt, row, None)
        assert len(result['independent_integer_checks']['A']['rows']) == 941
        assert len(result['independent_integer_checks']['B']['rows']) == 941
        monkeypatch.setattr(ref, 'validate_solver_receipt', lambda *args, **kwargs:
            {'checked_optimal': True, 'solver': {'plan': plan, 'objective_pence': 1}})
        with pytest.raises(ValueError): ref._checked_job(None, receipt, row, None)
    else:
        with pytest.raises(ValueError): ref._checked_job(None, receipt, row, None)


@pytest.mark.parametrize('failure', ['best_feasible', 'runner_feasible', 'zero_gap', 'pass_empty_best'])
def test_conditional_runner_full_exclusion_positive_gap_and_no_density(tmp_path, monkeypatch, failure):
    output, row, frozen, model = case_fixture(tmp_path); invocations = []; preparations = []
    winner = dict.fromkeys(model['project_ids'], 0); runner = dict(winner); runner['P001'] = 1
    def native(folder):
        invocations.append(folder)
        return store(folder / 'terminal.json', {'test_only': True})
    def prepare(path, folder, **kwargs):
        preparations.append(kwargs)
        assert kwargs == {'backend': 'cp_sat', 'time_limit_seconds': 600, 'exclude_plan': winner}
        return store(folder / 'preparation.json', {'test_only': True})
    def checked(job, receipt, _, excluded):
        if failure == 'best_feasible' or failure == 'runner_feasible' and excluded is not None:
            raise ValueError('FEASIBLE is not OPTIMAL')
        solver = {'plan': winner if excluded is None else runner,
                  'objective_pence': 0 if excluded is None or failure == 'zero_gap' else -1}
        return {'native': {'solver': solver}}
    monkeypatch.setattr(runtime600, 'execute_prepared', native); monkeypatch.setattr(runtime600, 'prepare', prepare)
    monkeypatch.setattr(ref, '_checked_job', checked)
    monkeypatch.setattr(ref, '_financial_projection', lambda *_: {'comparison': {'plans': [
        {'A': {'objective_pence': 0}, 'B': {'objective_pence': 0}},
        {'A': {'objective_pence': -1}, 'B': {'objective_pence': -1}}]}})
    result = ref.read(ref._case(output, frozen, {}, row))
    assert len(invocations) == result['native_job_invocations'] == (1 if failure == 'best_feasible' else 2)
    assert len(preparations) == (0 if failure == 'best_feasible' else 1)
    assert result['passed'] is (failure == 'pass_empty_best')
    assert result['solver_receipts'] and not result['qualified']
    if result['passed']: assert sum(result['winner_plan'].values()) == 0 and result['gap_pence'] == 1
    with pytest.raises(ValueError): ref._case(output, frozen, {}, row)


@pytest.mark.parametrize('worker_exception', [False, True])
def test_parent_runs_fixed_whole_pool_max_two_and_retains_rejection(context, monkeypatch, worker_exception):
    from sheets_factory.core import audit as audit_module
    from sheets_factory import dashboard, resume
    output, inputs = context; output.mkdir(parents=True)
    store(output / 'preparation.json', {'test_only': True})
    inventory = {'cases': [{'case': c} for c in ref.contract.CASES]}
    frozen = {'case_order': [c['id'] for c in ref.contract.CASES]}
    monkeypatch.setattr(ref, 'validate_prepared', lambda _: (frozen, inputs, inventory))
    state = {'active': 0, 'max': 0, 'called': [], 'server': False}; lock = threading.Lock()
    class Audit:
        def __init__(self, *args): self.db = self
        def close(self): pass
        def snapshot(self): return {}
        def events(self): return []
        def update_run(self, **kwargs): pass
        def export(self): pass
        def record(self, *args): pass
    class Server:
        def __init__(self, *args, **kwargs): pass
        def start(self): state['server'] = True; return 'mock://no-network'
        def stop(self): pass
    class Lease:
        def __init__(self, *args): pass
        def acquire(self): return self
        def release(self): pass
    monkeypatch.setattr(audit_module, 'AuditStore', Audit); monkeypatch.setattr(dashboard, 'DashboardServer', Server)
    monkeypatch.setattr(resume, 'ProducerLease', Lease)
    def worker(output, frozen, inputs, row, audit):
        identity = row['case']['id']; assert state['server']
        with lock:
            state['active'] += 1; state['max'] = max(state['max'], state['active']); state['called'].append(identity)
        time.sleep(.01)
        with lock: state['active'] -= 1
        folder = output / 'cases' / identity; folder.mkdir(parents=True)
        if worker_exception and identity == frozen['case_order'][0]: raise RuntimeError('retained mock worker defect')
        return store(folder / 'terminal.json', {'passed': identity != frozen['case_order'][0], 'native_job_invocations': 1})
    monkeypatch.setattr(ref, '_case', worker)
    result = ref.read(ref.execute_prepared(output))
    assert len(state['called']) == len(set(state['called'])) == 9 and state['max'] == 2
    assert result['passed'] is False and result['all_cases_retained'] is True and len(result['cases']) == 9
    assert result['native_job_invocations'] == (None if worker_exception else 9)
    assert result['automatic_retries'] == 0
    with pytest.raises(ValueError): ref.execute_prepared(output)
    with pytest.raises(ValueError): ref.validate_completed(output / 'terminal.json')


def test_json_claim_of_success_cannot_replace_genuine_completed_protocol(tmp_path):
    record = store(tmp_path / 'fabricated.json', {'kind': ref.KIND, 'version': 1, 'passed': True,
        'all_cases_retained': True, 'qualified': False, 'automatic_retries': 0,
        'reference_is_not_source_or_quality_or_difficulty': True, 'financial_forwards': 0, 'LO_calls': 0, 'model_calls': 0,
        'preparation': {'path': str(tmp_path / 'absent.json'), 'sha256': 'a' * 64, 'bytes': 1}})
    with pytest.raises((ValueError, OSError)): ref.validate_completed(record)


@pytest.mark.parametrize('mutation', ['none', 'omitted_case', 'case_order', 'gap', 'same_runner', 'case_qualified', 'extra_receipt'])
def test_completed_join_rechecks_both_phases_finance_and_whole_nine_inventory(tmp_path, monkeypatch, mutation):
    output = tmp_path; prep = store(output / 'preparation.json', {'test_only': True})
    order = [c['id'] for c in ref.contract.CASES]
    winner = {'P001': 0}; runner = {'P001': 1}  # Complete-matrix/native gates explicitly mocked here.
    projected = {'comparison': {'plans': [{'A': {'objective_pence': 0}, 'B': {'objective_pence': 0}},
                                          {'A': {'objective_pence': -1}, 'B': {'objective_pence': -1}}]}}
    calls = []; projections = []
    def checked(job, receipt, row, excluded):
        calls.append((row['case']['id'], excluded))
        return {'native': {'solver': {'plan': winner if excluded is None else runner,
                                     'objective_pence': 0 if excluded is None else -1}}}
    def project(inputs, row, a, b):
        projections.append(row['case']['id']); assert a == winner and b == runner
        return projected
    monkeypatch.setattr(ref, '_checked_job', checked); monkeypatch.setattr(ref, '_financial_projection', project)
    rows = []; receipts = []; jobs = {}
    for case in ref.contract.CASES:
        identity = case['id']; folder = output / 'cases' / identity
        row = {'case': dict(case), 'models': {'A': None, 'B': None}}; rows.append(row)
        jobs[identity] = store(folder / 'best_job.json', {'test_only': True})
        values = {'kind': ref.CASE_KIND, 'version': 1, 'passed': True, 'case': dict(case),
            'models': row['models'], 'native_job_invocations': 2, 'qualified': False,
            'reference_is_not_source_or_quality_or_difficulty': True, 'financial_forwards': 0, 'LO_calls': 0, 'model_calls': 0,
            'solver_receipts': {phase: store(folder / (phase + '_native.json'), {'test_only': True}) for phase in ('best', 'runner')},
            'validations': {'best': store(folder / 'best_check.json', {'native': {'solver': {'plan': winner, 'objective_pence': 0}}}),
                            'runner': store(folder / 'runner_check.json', {'native': {'solver': {'plan': runner, 'objective_pence': -1}}})},
            'runner_preparation': store(folder / 'runner_job.json', {'test_only': True}),
            'winner_plan': winner, 'winner_objective_pence': 0, 'runner_plan': runner, 'runner_objective_pence': -1,
            'gap_pence': 1, 'financial_projection': store(folder / 'financial.json', projected)}
        if identity == order[0]:
            if mutation == 'gap': values['gap_pence'] = 0
            elif mutation == 'same_runner': values['runner_plan'] = winner
            elif mutation == 'case_qualified': values['qualified'] = True
            elif mutation == 'extra_receipt': values['solver_receipts']['retry'] = values['solver_receipts']['best']
        receipts.append(store(folder / 'terminal.json', values))
    monkeypatch.setattr(ref, 'validate_prepared', lambda _: ({'case_order': order, 'best_preparations': jobs}, {}, {'cases': rows}))
    terminal = {'kind': ref.KIND, 'version': 1, 'passed': True, 'preparation': prep, 'case_order': order,
        'cases': receipts[:-1] if mutation == 'omitted_case' else receipts, 'native_job_invocations': 18,
        'known_native_job_invocations': 18, 'all_cases_retained': True, 'automatic_retries': 0,
        'qualified': False, 'reference_is_not_source_or_quality_or_difficulty': True,
        'financial_forwards': 0, 'LO_calls': 0, 'model_calls': 0}
    if mutation == 'case_order': terminal['case_order'] = list(reversed(order))
    record = store(output / 'terminal.json', terminal)
    if mutation == 'none':
        assert ref.validate_completed(record) == terminal
        assert len(calls) == 18 and projections == order
        assert calls == [(identity, excluded) for identity in order for excluded in (None, winner)]
    else:
        with pytest.raises(ValueError): ref.validate_completed(record)
