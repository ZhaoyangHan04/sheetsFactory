"""Explicit offline boundaries: no Gurobi, Docker or financial production run."""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from test_linear_capital_optimization_runtime import services

ROOT = Path(__file__).resolve().parents[1]
definition = importlib.util.spec_from_file_location('_gurobi_reference_test', ROOT/'scripts/run_linear_capital_gurobi_research.py')
entry = importlib.util.module_from_spec(definition); definition.loader.exec_module(entry)


def test_exact_frozen_gates_reused_and_old_namespace_unchanged():
    before = ast.parse(entry.UPSTREAM.read_text()); after = entry.adapted_ast()
    names = {'_financial', '_checked_finance', '_checked_job', 'validate_completed'}
    originals = {n.name: n for n in before.body if isinstance(n, ast.FunctionDef)}
    adapted = {n.name: n for n in after.body if isinstance(n, ast.FunctionDef)}
    for name in names-{'_checked_finance', '_checked_job'}:
        assert ast.dump(originals[name]) == ast.dump(adapted[name])
    # This constant identifies independent matrices; it is not a second search.
    assert entry.BACKENDS == {'A': 'scip', 'B': 'cp_sat'}
    assert entry.KIND == 'linear_capital_gurobi_restricted_research_best_runner_reference'
    assert entry._profile()['cpus'] == entry._profile()['threads'] == 16
    assert entry._profile()['agent_and_verifier_cpus_unchanged'] == 2
    assert entry._profile()['commercial_or_production_use_authorized'] is False
    assert entry.reference(entry.UPSTREAM)['sha256'] == entry.PRODUCER_HARNESS_SHA256
    assert str(entry.UPSTREAM) in entry.recipes()


def test_unauthorized_finance_rejected_before_preparation(tmp_path, monkeypatch):
    value = tmp_path/'other.json'; value.write_text('{}')
    monkeypatch.setattr(entry, '_base_prepare', lambda *_: pytest.fail('No preparation for another source'))
    with pytest.raises(ValueError, match='authorized original C01'):
        entry.prepare(value, tmp_path/'new')


def test_declaration_frozen_before_any_execute_and_tampering_rejected(tmp_path, monkeypatch):
    finance = tmp_path/'finance.json'; finance.write_text('{"explicit_fake_finance":true}')
    ref = entry.reference(finance); monkeypatch.setattr(entry, 'AUTHORIZED_FINANCE_SHA256', ref['sha256'])
    output = tmp_path/'prepared'
    def prepare(*_):
        output.mkdir()
        return entry.write(output/'preparation.json', {'financial_crosscheck': ref,
            'best_preparation': ref, 'recipe': {str(finance): ref},
            'private_density_gate': {'minimum': 80, 'maximum': 160, 'public_cardinality_constraint': False}})
    monkeypatch.setattr(entry, '_base_prepare', prepare)
    monkeypatch.setattr(entry.runtime, 'execute_prepared', lambda *_: pytest.fail('Preparation cannot execute'))
    record = entry.prepare(finance, output); frozen = entry.read(record)
    monkeypatch.setattr(entry, '_base_validate_prepared', lambda _: (frozen, {'terminal': ref}))
    assert entry.validate_prepared(output)[0] == frozen
    declaration = entry.read(output/'prospective_declaration.json')
    assert declaration['actual_solver_calls_at_declaration'] == declaration['model_calls'] == 0
    assert declaration['best_then_complete_winner_excluded_runner_only_after_checked_OPTIMAL'] is True
    assert declaration['global_search_implementation_count'] == 1
    declaration['MIPGap'] = 0.001
    (output/'prospective_declaration.json').write_text(json.dumps(declaration))
    with pytest.raises(ValueError, match='prospective'):
        entry.validate_prepared(output)


def actual_gate_fixture(tmp_path, monkeypatch):
    bundle = tmp_path/'bundle'; license_path = bundle/'vendor/gurobipy/.libs/gurobi.lic'
    license_path.parent.mkdir(parents=True); license_path.write_bytes(b'X'*90)
    license_sha = hashlib.sha256(license_path.read_bytes()).hexdigest()
    monkeypatch.setattr(entry, 'EMBEDDED_LICENSE_SHA256', license_sha)
    (bundle/'solver.log').write_text('Restricted license - for non-production use only\n')
    prep = entry.write(tmp_path/'job.json', {'bundle': str(bundle)})
    solver = {'backend': 'gurobi_restricted_research', 'solver_version': '13.0.0',
        'research_evaluation_only': True, 'personal_or_remote_license_used': False,
        'formal_global_certificate': False, 'second_solve_automatically_started': False,
        'feasibility_tolerances_changed': False,
        'parameters': {'Threads': 16, 'TimeLimit': 3600.0, 'MIPGap': 0.0, 'MIPGapAbs': 0.0},
        'embedded_public_license': {'path': '/app/vendor/gurobipy/.libs/gurobi.lic', 'sha256': license_sha, 'bytes': 90},
        'native_variables': 240, 'native_linear_constraints': 881, 'raw_status': 2}
    monkeypatch.setattr(entry, '_base_validate_solver_receipt', lambda *_a, **_k: {'checked_optimal': True, 'solver': solver})
    return prep, solver, bundle


@pytest.mark.parametrize('bad', ['threads', 'gap', 'license', 'personal', 'scope', 'missing_row', 'missing_banner', 'status'])
def test_actual_native_license_parameters_and_complete_scope_failclosed(tmp_path, monkeypatch, bad):
    prep, solver, bundle = actual_gate_fixture(tmp_path, monkeypatch)
    if bad == 'threads': solver['parameters']['Threads'] = 2
    elif bad == 'gap': solver['parameters']['MIPGap'] = .001
    elif bad == 'license': solver['embedded_public_license']['sha256'] = '0'*64
    elif bad == 'personal': solver['personal_or_remote_license_used'] = True
    elif bad == 'scope': solver['research_evaluation_only'] = False
    elif bad == 'missing_row': solver['native_linear_constraints'] = 880
    elif bad == 'missing_banner': (bundle/'solver.log').write_text('No restricted banner')
    elif bad == 'status': solver['raw_status'] = 9
    with pytest.raises(ValueError):
        entry.validate_solver_receipt(prep, prep, model=prep, backend='gurobi')


def test_actual_runner_requires_full_no_good_row(tmp_path, monkeypatch):
    prep, solver, _ = actual_gate_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='881'):
        entry.validate_solver_receipt(prep, prep, model=prep, backend='gurobi', exclude_plan={'fixture': 1})
    solver['native_linear_constraints'] = 882
    assert entry.validate_solver_receipt(prep, prep, model=prep, backend='gurobi', exclude_plan={'fixture': 1})['checked_optimal'] is True


def outer_fixture(tmp_path, monkeypatch, *, limited=False, tie=False, finance_fail=False):
    output = tmp_path/'outer'; output.mkdir()
    ref = entry.write(tmp_path/'boundary.json', {'explicit_fake_boundary': True})
    ids = [f'P{i:03d}' for i in range(1, 241)]
    winner = {pid: int(i < 107) for i, pid in enumerate(ids)}
    runner = deepcopy(winner); runner['P001'] = 0
    finance = {'terminal': ref, 'specification': ref, 'raw_preparation': ref, 'universe_A': ref, 'universe_B': ref,
        'public': {'project_ids': ids}, 'A': {'boundary': 'A'}, 'B': {'boundary': 'B'}, 'models': {'A': ref, 'B': ref}}
    folder = output/'jobs/best'; folder.mkdir(parents=True)
    best = entry.write(folder/'preparation.json', {'phase': 'best'})
    entry.write(output/'preparation.json', {'explicit_fake_preparation': True})
    entry.write(output/'prospective_declaration.json', {'explicit_fake_declaration': True})
    frozen = {'best_preparation': best, 'recipe': {str(tmp_path/'boundary.json'): ref},
        'private_density_gate': {'minimum': 80, 'maximum': 160, 'public_cardinality_constraint': False}}
    monkeypatch.setattr(entry, 'validate_prepared', lambda _: (frozen, finance))
    monkeypatch.setattr(entry.spec, 'validate_plan', lambda _p, value: value)
    calls = []
    def prepare(model, destination, *, backend, time_limit_seconds, exclude_plan):
        assert backend == 'gurobi' and time_limit_seconds == 3600 and exclude_plan == winner
        calls.append('prepare_runner'); destination.mkdir(parents=True)
        return entry.write(destination/'preparation.json', {'phase': 'runner'})
    def execute(folder):
        phase = entry.read(folder/'preparation.json')['phase']; calls.append(phase)
        return entry.write(folder/'terminal.json', {'phase': phase})
    def checked(job, terminal, _finance, excluded):
        phase = entry.read(terminal)['phase']
        if limited and phase == 'best': raise ValueError('Explicit fake native TIME_LIMIT')
        assert excluded == (None if phase == 'best' else winner)
        return {'checked_optimal': True, 'solver': {'plan': winner if phase == 'best' else runner,
            'objective_pence': 1000 if phase == 'best' or tie else 999}}, {'A': {'rows': 881}, 'B': {'rows': 881}}
    def plans(_p, a, b, choices, *, require_feasible):
        assert require_feasible is True and a == finance['A'] and b == finance['B']
        return {'passed': not finance_fail, 'require_group_feasible': True,
            'plans': [{'A': {'objective_pence': 1000 if item['id'] == 'winner' else 999}} for item in choices]}
    monkeypatch.setattr(entry.runtime, 'prepare', prepare); monkeypatch.setattr(entry.runtime, 'execute_prepared', execute)
    monkeypatch.setattr(entry, '_checked_job', checked); monkeypatch.setattr(entry.finance_crosscheck, 'compare_plans', plans)
    state = services(monkeypatch)
    return output, calls, state


def test_mocked_best_runner_uses_one_algorithm_two_finances_and_stays_research(tmp_path, monkeypatch):
    output, calls, state = outer_fixture(tmp_path, monkeypatch)
    ref = entry.execute_prepared(output); result = entry.read(ref)
    assert calls == ['best', 'prepare_runner', 'runner']
    assert result['passed'] is result['research_evaluation_only'] is True
    assert result['global_search_implementation_count'] == 1
    assert result['independent_second_global_search_claimed'] is False
    assert result['gap_pence'] == 1 and result['selected_project_count'] == 107
    assert result['model_calls'] == result['LO_calls'] == result['task_count'] == 0
    assert result['source_or_quality_or_difficulty_certified'] is result['qualified'] is False
    assert entry.validate_completed(ref) == result
    assert state['released'] and state['closed'] and state['stopped']


@pytest.mark.parametrize('case', ['limit', 'tie', 'financial_disagreement'])
def test_no_runner_after_limit_and_no_retry_or_reference_on_failure(tmp_path, monkeypatch, case):
    output, calls, state = outer_fixture(tmp_path, monkeypatch, limited=case == 'limit',
        tie=case == 'tie', finance_fail=case == 'financial_disagreement')
    result = entry.read(entry.execute_prepared(output))
    assert result['passed'] is False and result['research_evaluation_only'] is True
    assert calls == (['best'] if case == 'limit' else ['best', 'prepare_runner', 'runner'])
    assert state['released'] and state['closed'] and state['stopped']
    assert entry.read(output/'failure.json')['failure_is_not_model_zero'] is True
    with pytest.raises(ValueError, match='no retry'):
        entry.execute_prepared(output)
