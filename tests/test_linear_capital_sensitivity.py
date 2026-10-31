"""Complete-geometry mathematical fixtures; no finance forward or services."""
from copy import deepcopy

import pytest

from sheets_factory.workbook.linear_capital_sensitivity import contract, oracle_a


@pytest.fixture(scope='module')
def source():
    ids = [f'P{i:03d}' for i in range(1, 361)]
    scenarios = ['S01', 'S02', 'S03']; years = list(range(1, 21))
    resources = [f'U{i:02d}' for i in range(1, 7)]
    regions = [f'R{i:02d}' for i in range(1, 7)]; sectors = [f'C{i:02d}' for i in range(1, 9)]
    public = {'dimension_mode': 'production', 'project_ids': ids, 'scenario_ids': scenarios,
        'years': years, 'resource_ids': resources, 'region_ids': regions, 'sector_ids': sectors,
        'exclusivity_groups': [{'id': f'SITE{i+1:02d}', 'project_ids': ids[i*3:i*3+3]} for i in range(60)],
        'prerequisites': [{'id': f'LINK{i+1:03d}', 'dependent': ids[240+i], 'prerequisite': ids[i]} for i in range(120)],
        'shared_limits': {'initial_sponsor_equity_pence': 10001,
            'annual_new_lp_pence': {s: {str(y): 1001+y for y in years} for s in scenarios},
            'annual_debt_close_pence': {s: {str(y): 2003+y for y in years} for s in scenarios},
            'resource_capacity_units': {r: {s: {str(y): 10000+y for y in years} for s in scenarios} for r in resources},
            'region_exposure_pence': {r: {str(y): 8000+y for y in years} for r in regions},
            'sector_exposure_pence': {r: {str(y): 9000+y for y in years} for r in sectors}}}
    rows = []
    for identity, (family, scenario, year, limit) in sorted(contract.expected_rows(public).items()):
        coefficients = [0] * 360
        if family == 'initial_sponsor_equity': coefficients = [101+i % 7 for i in range(360)]
        if family == 'resource': coefficients = [3+i % 5 for i in range(360)]
        if family == 'annual_new_lp': coefficients = [1] * 360
        if family == 'exclusivity':
            group = next(g for g in public['exclusivity_groups'] if identity == 'exclusivity:' + g['id'])
            coefficients = [int(pid in group['project_ids']) for pid in ids]
        if family == 'prerequisite':
            edge = next(e for e in public['prerequisites'] if identity == 'prerequisite:' + e['id'])
            coefficients = [int(pid == edge['dependent']) - int(pid == edge['prerequisite']) for pid in ids]
        rows.append({'id': identity, 'family': family, 'scenario_id': scenario, 'year': year,
                     'coefficients': coefficients, 'limit': limit})
    model = {'kind': 'linear_capital_scaled_direct_binary_integer_model', 'version': 2,
        'project_ids': ids, 'objective_pence': [1000+i for i in range(360)], 'rows': rows,
        'specification_sha256': contract.spec.canonical_sha256(public), 'universe_sha256': 'a' * 64}
    other = {**model, 'universe_sha256': 'b' * 64}
    # Only the upstream public financial-schema boundary is mocked: this fixture
    # supplies known exact mathematical coefficients, never claims finance proof.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(contract.spec, 'load_spec', lambda raw: deepcopy(raw))
        patch.setattr(contract, 'BASE_LOGICAL_SPEC_SHA', model['specification_sha256'])
        declaration = contract.build_contract(public, model, other)
        yield public, model, other, declaration


@pytest.fixture(scope='module')
def matrix(source):
    public, model, _, declaration = source
    return oracle_a.build_cases(public, model, declaration)


def plans(source, value=0):
    public, _, _, declaration = source
    return {c: {p: value for p in public['project_ids']} for c in declaration['case_order']}


def test_complete_independent_fixed_inventory_and_honest_geometry(source):
    declaration = source[3]
    assert declaration['case_order'] == [f'B{b}_C{c}' for b in (90, 100, 110) for c in (90, 100, 110)]
    assert declaration['output_geometry'] == {'project_financial_ledgers': 1, 'case_plan_binary_cells': 3240,
        'cases': 9, 'constraints_per_case': 941, 'scenario_year_reports': 540}
    assert not declaration['different_winner_required']
    assert not declaration['reference_admission'] and not declaration['checked_optimal']
    assert not declaration['qualified'] and not declaration['difficulty_claimed']


def test_all_rows_and_columns_reused_only_two_declared_rhs_families_scale(source, matrix):
    public, base, _, declaration = source
    before = deepcopy(public), deepcopy(base)
    for case in matrix['cases']:
        definition = case['case']; model = case['model']
        assert len(model['rows']) == 941 and model['project_ids'] == base['project_ids']
        assert model['objective_pence'] == base['objective_pence']
        assert model['universe_sha256'] == base['universe_sha256']
        for old, new in zip(base['rows'], model['rows'], strict=True):
            assert {k: v for k, v in old.items() if k != 'limit'} == {k: v for k, v in new.items() if k != 'limit'}
            factor = definition['budget_percent'] if old['family'] == 'initial_sponsor_equity' else definition['capacity_percent'] if old['family'] == 'resource' else 100
            assert new['limit'] == old['limit'] * factor // 100
    assert (public, base) == before
    assert matrix['contract_sha256'] == contract.canonical_sha256(declaration)


def test_floor_once_and_center_case_identity(source, matrix):
    base = source[1]
    low = matrix['cases'][0]['model']; center = matrix['cases'][4]['model']
    assert next(r for r in low['rows'] if r['id'] == 'initial_sponsor_equity')['limit'] == 9000
    assert next(r for r in low['rows'] if r['id'] == 'resource:U01:S01:1')['limit'] == 9000
    assert center == base


@pytest.mark.parametrize('change', ['omit', 'reorder', 'extra', 'one_axis_only', 'unknown_field', 'qualification'])
def test_prospective_contract_cannot_omit_or_relabel_case_scope(source, change):
    public, base, _, original = source; value = deepcopy(original)
    if change == 'omit': value['cases'].pop()
    elif change == 'reorder': value['case_order'].reverse()
    elif change == 'extra': value['cases'].append(deepcopy(value['cases'][0]))
    elif change == 'one_axis_only': value['cases'][0]['capacity_percent'] = 100
    elif change == 'unknown_field': value['cached_optimal'] = True
    else: value['qualified'] = True
    with pytest.raises(ValueError): oracle_a.build_cases(public, base, value)


@pytest.mark.parametrize('change', ['missing_row', 'wrong_row_identity', 'changed_limit', 'changed_coefficient', 'changed_source', 'missing_column'])
def test_complete_census_and_prospective_base_digest_are_required(source, change):
    public, base, _, declaration = source; value = deepcopy(base); raw = deepcopy(public)
    if change == 'missing_row': value['rows'].pop()
    elif change == 'wrong_row_identity': value['rows'][0]['id'] += ':replacement'
    elif change == 'changed_limit': value['rows'][0]['limit'] += 1
    elif change == 'changed_coefficient': value['rows'][0]['coefficients'][0] += 1
    elif change == 'changed_source': raw['shared_limits']['initial_sponsor_equity_pence'] += 1
    else: value['objective_pence'].pop()
    with pytest.raises(ValueError): oracle_a.build_cases(raw, value, declaration)


def test_empty_and_overcapacity_plans_audit_every_case_and_every_row(source):
    public, base, _, declaration = source
    empty = oracle_a.check_plans(public, base, declaration, plans(source))
    assert len(empty) == 9 and all(r['feasible'] and r['objective_pence'] == 0 and len(r['rows']) == 941 for r in empty)
    full = oracle_a.check_plans(public, base, declaration, plans(source, 1))
    assert all(not r['feasible'] and r['objective_pence'] == sum(base['objective_pence']) for r in full)
    assert all(not r['checked_optimal'] for r in empty + full)


def test_signed_prerequisite_rows_and_separate_case_choices(source):
    public, base, _, declaration = source; choices = plans(source); first = declaration['case_order'][0]
    edge = public['prerequisites'][0]; choices[first][edge['dependent']] = 1
    result = oracle_a.check_plans(public, base, declaration, choices)
    row = next(r for r in result[0]['rows'] if r['id'] == 'prerequisite:' + edge['id'])
    assert row['lhs'] == 1 and not row['passed']
    assert result[0]['selected_project_count'] == 1 and all(r['selected_project_count'] == 0 for r in result[1:])
    choices[first][edge['prerequisite']] = 1
    repaired = oracle_a.check_plans(public, base, declaration, choices)
    assert next(r for r in repaired[0]['rows'] if r['id'] == row['id'])['lhs'] == 0
    assert repaired[0]['feasible']


@pytest.mark.parametrize('change', ['missing_case', 'extra_case', 'missing_project', 'bool', 'float'])
def test_plan_inventory_and_integer_domains_fail_closed(source, change):
    public, base, _, declaration = source; value = plans(source); first = declaration['case_order'][0]
    if change == 'missing_case': value.pop(first)
    elif change == 'extra_case': value['unknown'] = value[first]
    elif change == 'missing_project': value[first].pop('P001')
    elif change == 'bool': value[first]['P001'] = True
    else: value[first]['P001'] = 1.0
    with pytest.raises(ValueError): oracle_a.check_plans(public, base, declaration, value)
