"""Pure full-geometry integer fixtures, never a financial or reference admission."""
from copy import deepcopy
import inspect

import pytest

from sheets_factory.workbook.linear_capital_sensitivity import contract, oracle_b


@pytest.fixture
def mathematical_case(monkeypatch):
    ids = list(oracle_b.spec.PROJECT_IDS)
    assert len(ids) == 360
    scenarios = ['S01', 'S02', 'S03']
    years = list(range(1, 21))
    resources = [f'U{i:02}' for i in range(1, 7)]
    regions = [f'R{i:02}' for i in range(1, 7)]
    sectors = [f'C{i:02}' for i in range(1, 9)]
    grid = lambda names, amount: {name: {str(y): amount for y in years} for name in names}
    public = {'dimension_mode': 'production', 'project_ids': ids,
              'scenario_ids': scenarios, 'years': years, 'resource_ids': resources,
              'region_ids': regions, 'sector_ids': sectors,
              'exclusivity_groups': [{'id': f'G{i:02}'} for i in range(1, 61)],
              'prerequisites': [{'id': f'E{i:03}'} for i in range(1, 121)],
              'shared_limits': {'initial_sponsor_equity_pence': 101,
                  'annual_new_lp_pence': grid(scenarios, 1003),
                  'annual_debt_close_pence': grid(scenarios, 1007),
                  'resource_capacity_units': {u: grid(scenarios, 101) for u in resources},
                  'region_exposure_pence': grid(regions, 1013),
                  'sector_exposure_pence': grid(sectors, 1019)},
              'untouched_public_policy': 'Pure integer matrix fixture, not a source proof'}
    # Replace only the full raw-spec schema boundary. All retained B matrix
    # validation,941 metadata identities and exact integers remain real.
    monkeypatch.setattr(oracle_b.spec, 'load_spec', lambda value: deepcopy(value))
    monkeypatch.setattr(contract, 'BASE_LOGICAL_SPEC_SHA', contract.canonical_sha256(public))
    expected = contract.expected_rows(public)
    rows = []
    for identity, (family, scenario, year, limit) in sorted(expected.items()):
        coefficients = [0] * 360
        if identity == 'initial_sponsor_equity':
            coefficients[:2] = [60, 41]
        if identity == 'resource:U01:S01:1':
            coefficients[:2] = [95, 10]
        if identity == 'prerequisite:E001':
            coefficients[:2] = [1, -1]
        rows.append({'id': identity, 'family': family, 'scenario_id': scenario,
                     'year': year, 'coefficients': coefficients, 'limit': limit})
    model = {'kind': oracle_b.model_b.MODEL_KIND, 'version': 2, 'project_ids': ids,
             'objective_pence': [7, -3, 13] + [0]*357, 'rows': rows,
             'specification_sha256': contract.canonical_sha256(public), 'universe_sha256': 'b'*64}
    declaration = {'kind': contract.KIND, 'version': 1,
        'base_specification_sha256': contract.BASE_LOGICAL_SPEC_SHA,
        'base_model_sha256': {'A': 'a'*64, 'B': contract.canonical_sha256(model)},
        'cases': deepcopy(list(contract.CASES)), 'case_order': [c['id'] for c in contract.CASES],
        'public_policy': dict(contract.POLICY), 'output_geometry': dict(contract.GEOMETRY),
        'source_provenance': contract.PROVENANCE, 'future_gold_policy': contract.GOLD_POLICY,
        'different_winner_required': False, 'reference_admission': False, 'checked_optimal': False,
        'financial_forward_calls': 0, 'optimizer_calls': 0, 'LO_calls': 0, 'model_calls': 0,
        'qualified': False, 'difficulty_claimed': False}
    oracle_b.model_b.validate_model(model)
    return public, model, declaration


def plans_for(public, declaration, selected=()):
    return {case_id: {pid: int(pid in selected) for pid in public['project_ids']}
            for case_id in declaration['case_order']}


def test_all_nine_models_floor_public_limits_and_preserve_every_other_field(mathematical_case):
    public, base, declaration = mathematical_case
    before = deepcopy(mathematical_case)
    result = oracle_b.build_cases(public, base, declaration)
    assert result['kind'] == oracle_b.KIND and result['version'] == 1
    assert result['contract_sha256'] == contract.canonical_sha256(declaration)
    assert len(result['cases']) == 9
    assert [a['case']['id'] for a in result['cases']] == declaration['case_order']
    for alternative in result['cases']:
        case, model = alternative['case'], alternative['model']
        assert len(model['rows']) == 941 and model['project_ids'] == base['project_ids']
        assert model['objective_pence'] == base['objective_pence']
        assert model['universe_sha256'] == base['universe_sha256']
        modified_public = deepcopy(public)
        modified_public['shared_limits']['initial_sponsor_equity_pence'] = 101 * case['budget_percent']//100
        for u in public['resource_ids']:
            for s in public['scenario_ids']:
                for y in public['years']:
                    modified_public['shared_limits']['resource_capacity_units'][u][s][str(y)] = 101*case['capacity_percent']//100
        assert model['specification_sha256'] == contract.canonical_sha256(modified_public)
        for original, revised in zip(base['rows'], model['rows']):
            assert {k: v for k, v in original.items() if k != 'limit'} == {k: v for k, v in revised.items() if k != 'limit'}
            factor = case['budget_percent'] if original['id'] == 'initial_sponsor_equity' else case['capacity_percent'] if original['family'] == 'resource' else 100
            assert revised['limit'] == original['limit']*factor//100
    assert result['cases'][4]['model'] == base  #100%/100% is identity, not rescaling twice.
    assert mathematical_case == before
    assert result['reference_admission'] is False and result['checked_optimal'] is False
    assert result['optimizer_calls'] == 0


def test_model_results_do_not_alias_inputs_or_other_alternatives(mathematical_case):
    public, base, declaration = mathematical_case
    result = oracle_b.build_cases(public, base, declaration)
    result['cases'][0]['model']['objective_pence'][0] = 999
    result['cases'][0]['case']['budget_percent'] = 999
    assert base['objective_pence'][0] == result['cases'][1]['model']['objective_pence'][0] == 7
    assert declaration['cases'][0]['budget_percent'] == 90


def test_crossed_feasibility_and_exact_signed_objective(mathematical_case):
    public, base, declaration = mathematical_case
    plans = plans_for(public, declaration, public['project_ids'][:2])
    checks = oracle_b.check_plans(public, base, declaration, plans)
    assert [r['case_id'] for r in checks if r['feasible']] == ['B100_C110', 'B110_C110']
    for result in checks:
        assert result['objective_pence'] == 4 and result['selected_project_count'] == 2
        assert len(result['rows']) == 941 and result['checked_optimal'] is False
        rows = {r['id']: r for r in result['rows']}
        assert rows['prerequisite:E001']['lhs'] == 0
        assert rows['initial_sponsor_equity']['lhs'] == 101
        assert rows['resource:U01:S01:1']['lhs'] == 105
        for row in result['rows']:
            assert row['slack'] == row['limit']-row['lhs']
            assert row['passed'] is (row['lhs'] <= row['limit'])


def test_negative_prerequisite_coefficient_and_empty_plan(mathematical_case):
    public, base, declaration = mathematical_case
    assert all(r['feasible'] and r['objective_pence'] == 0 for r in oracle_b.check_plans(public, base, declaration, plans_for(public, declaration)))
    result = oracle_b.check_plans(public, base, declaration, plans_for(public, declaration, public['project_ids'][:1]))
    assert all(not r['feasible'] for r in result)
    row = next(r for r in result[4]['rows'] if r['id'] == 'prerequisite:E001')
    assert row == {'id': 'prerequisite:E001', 'lhs': 1, 'limit': 0, 'slack': -1, 'passed': False}


@pytest.mark.parametrize('bad', [True, False, 0.0, 1.0, -1, 2, '1', None])
def test_complete_plans_reject_non_integer_binary_choices(mathematical_case, bad):
    public, base, declaration = mathematical_case
    plans = plans_for(public, declaration)
    plans[declaration['case_order'][0]][public['project_ids'][0]] = bad
    with pytest.raises(ValueError, match='integer zero or one'):
        oracle_b.check_plans(public, base, declaration, plans)


@pytest.mark.parametrize('mutation', ['missing_case','extra_case','missing_project','extra_project'])
def test_plan_inventory_cannot_filter_cases_or_project_columns(mathematical_case, mutation):
    public, base, declaration = mathematical_case
    plans = plans_for(public, declaration)
    if mutation == 'missing_case': plans.pop(declaration['case_order'][0])
    elif mutation == 'extra_case': plans['unfixed'] = plans[declaration['case_order'][0]]
    elif mutation == 'missing_project': plans[declaration['case_order'][0]].pop(public['project_ids'][0])
    else: plans[declaration['case_order'][0]]['unknown'] = 0
    with pytest.raises(ValueError): oracle_b.check_plans(public, base, declaration, plans)


@pytest.mark.parametrize('mutation', ['wrong_order','floating_factor','mutated_model','changed_public','fake_admission'])
def test_exact_prospective_binding_cannot_be_relaxed(mathematical_case, mutation):
    public, base, declaration = deepcopy(mathematical_case)
    if mutation == 'wrong_order': declaration['case_order'].reverse()
    elif mutation == 'floating_factor': declaration['cases'][0]['capacity_percent'] = 90.0
    elif mutation == 'mutated_model': base['rows'][0]['coefficients'][0] += 1
    elif mutation == 'changed_public': public['shared_limits']['initial_sponsor_equity_pence'] += 1
    else: declaration['reference_admission'] = True
    with pytest.raises(ValueError): oracle_b.build_cases(public, base, declaration)


def test_no_financial_compiler_solver_or_shared_plan_checker(mathematical_case, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('No financial forward or optimisation is permitted')
    monkeypatch.setattr(oracle_b.model_b, 'build_model', forbidden)
    monkeypatch.setattr(oracle_b.model_b, 'solve_cp_sat', forbidden)
    monkeypatch.setattr(oracle_b.model_b, 'check_plan', forbidden)
    public, base, declaration = mathematical_case
    assert len(oracle_b.check_plans(public, base, declaration, plans_for(public, declaration))) == 9
    source = inspect.getsource(oracle_b)
    assert 'oracle_a' not in source and 'finance.' not in source and 'ledger.' not in source
