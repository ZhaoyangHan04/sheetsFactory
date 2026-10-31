"""Dimension and hand-posting tests; no optimisation, workbook, LO or models."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from sheets_factory.workbook.capital_allocation import ledger as original_journal
from sheets_factory.workbook.capital_allocation import spec as original_schema
from sheets_factory.workbook.capital_allocation_scaled import catalog as frozen_catalog
from sheets_factory.workbook.capital_allocation_scaled import ledger as frozen_thirty
from sheets_factory.workbook.capital_allocation_scaled import spec as frozen_schema
from sheets_factory.workbook.capital_allocation_sparse import ledger, spec


def annual(value): return {str(year): value for year in spec.YEARS}


def specification(n=40):
    projects = [{'id': pid, 'commission_year': 2024, 'sale_year': 2026,
        'acquisition_cost_pence': 100, 'depreciation_years': 2,
        'annual_revenue_pence': {**annual(0), '2025': 80, '2026': 80},
        'annual_opex_pence': {**annual(0), '2025': 10, '2026': 10},
        'sale_proceeds_pence': 0} for pid in spec.project_ids(n)]
    scenarios = [{'id': sid, 'revenue_factors_p12': annual(spec.SCALE),
        'opex_factors_p12': annual(spec.SCALE), 'nav_factors_p12': annual(spec.SCALE),
        'sale_factors_p12': annual(spec.SCALE), 'bank_rates_p12': annual(0),
        'haircuts_p12': annual(0)} for sid in spec.SCENARIO_IDS]
    return {'schema_version': 1, 'currency': 'GBP', 'monetary_unit': 'pence', 'years': list(spec.YEARS),
        'opening_cash_pence': 1000, 'minimum_cash_pence': 0, 'lp_commitment_pence': 1000,
        'facility_limit_pence': 1000, 'advance_rate_p12': spec.SCALE, 'tax_rate_p12': 0,
        'tax_loss_carry_years': 2, 'discount_factors_p12': annual(spec.SCALE),
        'projects': projects, 'scenarios': scenarios,
        'provenance': {'kind': 'synthetic_capital_allocation_extension', 'raw_ancestors': deepcopy(spec.RAW_ANCESTORS)}}


def plan(public, *chosen):
    return {p['id']: int(p['id'] in chosen) for p in public['projects']}


def row(result, year, sid='S01'):
    return next(r for r in result['scenarios'][sid]['annual'] if r['year'] == year)


def assert_conserved(result):
    for scenario in result['scenarios'].values():
        assert scenario['all_journals_balance'] is True and len(scenario['annual']) == 20
        assert len(scenario['tax_vintages']) == 400
        for transaction in scenario['journal']:
            assert sum(transaction['debits'].values()) == sum(transaction['credits'].values())
        for value in scenario['annual']:
            assert set(value) == {'year', *original_schema.ANNUAL_FIELDS}
            assert all(value[field] == 0 for field in ('balance_check', 'cash_check', 'bank_check', 'capital_check', 'loss_check'))


@pytest.mark.parametrize('n', [40, 48, 56])
def test_last_project_hand_postings_have_full_dimension_and_conserved_terminal(n):
    public = specification(n); before = deepcopy(public); last = public['projects'][-1]['id']
    public['tax_rate_p12'] = spec.SCALE // 4; before = deepcopy(public)
    result = ledger.simulate(public, plan(public, last))
    assert public == before and result['feasible'] is True and result['objective_pence'] == 30
    assert len(result['plan']) == n and result['plan'][last] == 1
    assert (row(result, 2024)['capex'], row(result, 2024)['distribution']) == (100, 900)
    assert (row(result, 2025)['depreciation'], row(result, 2025)['current_tax'], row(result, 2025)['net_income']) == (50, 5, 15)
    assert (row(result, 2026)['return_of_capital'], row(result, 2026)['profit_distribution']) == (35, 30)
    assert all(row(result, 2043)[field] == 0 for field in ('bank_close', 'cash_close', 'project_book_value', 'capital_close', 'retained_close'))
    assert result['optimisation_performed'] is False and result['unique_optimum_claimed'] is False
    assert_conserved(result)


@pytest.mark.parametrize('n', [40, 48, 56])
def test_exact_selected_plan_parity_with_frozen_30_after_extra_unselected_candidates(n):
    original = frozen_catalog.build_spec('30-D01')
    public = deepcopy(original)
    public['projects'] += [{**deepcopy(original['projects'][index % 30]), 'id': pid}
                           for index, pid in enumerate(spec.project_ids(n)[30:])]
    chosen = ('P01', 'P15', 'P30')
    expected = frozen_thirty.simulate(original, plan(original, *chosen))
    actual = ledger.simulate(public, plan(public, *chosen))
    assert actual['feasible'] == expected['feasible'] and actual['objective_pence'] == expected['objective_pence']
    assert {key: actual[key] for key in actual if key not in ('plan', 'scenarios')} == \
           {key: expected[key] for key in expected if key not in ('plan', 'scenarios')}
    for sid in spec.SCENARIO_IDS:
        extra = actual['scenarios'][sid]['project_flows']
        assert len(extra) == n and all(len(extra[pid]) == 20 for pid in extra)
        comparison = deepcopy(actual['scenarios'][sid])
        comparison['project_flows'] = {pid: extra[pid] for pid in frozen_schema.project_ids(30)}
        assert comparison == expected['scenarios'][sid]
    assert all(actual['plan'][pid] == 0 for pid in spec.project_ids(n)[30:])
    assert_conserved(actual)


@pytest.mark.parametrize('n', [40, 48, 56])
def test_canonical_uint64_strings_cover_last_bits_and_do_not_use_numeric_masks(n):
    public = specification(n); selected = plan(public, 'P01', f'P{n:02d}')
    encoded = spec.mask_hex(public, dict(reversed(list(selected.items()))))
    assert encoded == '0x' + format(1 | (1 << (n - 1)), '016x')
    assert type(encoded) is str and len(encoded) == 18
    assert spec.plan_from_mask_hex(public, encoded) == selected
    assert spec.plan_from_mask_hex(public, '0x0000000000000000') == plan(public)
    assert spec.plan_space_count_string(public) == str(1 << n)
    assert type(spec.plan_space_count_string(public)) is str
    assert json.loads(json.dumps({'mask': encoded, 'combinatorial_plan_count': spec.plan_space_count_string(public)})) == \
           {'mask': encoded, 'combinatorial_plan_count': str(1 << n)}
    if n == 56:
        assert int(encoded, 16) > 2**53 and float(int(encoded, 16)) != int(encoded, 16)


@pytest.mark.parametrize('bad', [True, 1, 0.0, None, '', '0x1', '0X0000000000000001',
    '0x000000000000000A', '0x000000000000000g', '0x00000000000000001',
    ' 0x0000000000000001', '0x0000000000000001\n', '-0x000000000000001'])
def test_mask_decoder_rejects_noncanonical_types_and_formats(bad):
    with pytest.raises(ValueError, match='canonical uint64'):
        spec.plan_from_mask_hex(specification(56), bad)


@pytest.mark.parametrize('n', [40, 48, 56])
def test_unused_bits_and_64bit_overflow_are_not_silent_or_truncated(n):
    public = specification(n)
    for mask in (1 << n, (1 << 64) - 1):
        with pytest.raises(ValueError, match='unused high bits'):
            spec.plan_from_mask_hex(public, '0x' + format(mask, '016x'))
    with pytest.raises(ValueError, match='canonical uint64'):
        spec.plan_from_mask_hex(public, '0x10000000000000000')


@pytest.mark.parametrize('bad', [True, 0.0, 1.0, 2, -1, '1'])
def test_complete_plan_uses_literal_binary_integers(bad):
    public = specification(); selected = plan(public, 'P01'); selected['P40'] = bad
    for operation in (spec.validate_plan, spec.mask_hex, ledger.simulate):
        with pytest.raises(ValueError, match='binary integer'): operation(public, selected)


@pytest.mark.parametrize('kind', ['partial', 'additional', 'scenario-specific'])
def test_no_partial_extra_or_scenario_specific_choice_sets(kind):
    public = specification(); selected = plan(public, 'P01')
    if kind == 'partial': selected.pop('P40')
    elif kind == 'additional': selected['P41'] = 0
    else: selected = {sid: selected for sid in spec.SCENARIO_IDS}
    with pytest.raises(ValueError, match='complete common plan'): ledger.simulate(public, selected)


@pytest.mark.parametrize('change', ['old30', 'unsupported', 'float_count', 'reorder', 'missing', 'repeat', 'bool',
    'float', 'rate', 'money_bound', 'inactive_revenue', 'scenario', 'calendar', 'discount', 'ancestry'])
def test_dimension_only_loader_keeps_every_original_primitive_guard(change):
    public = specification()
    if change == 'old30': public['projects'] = public['projects'][:30]
    elif change == 'unsupported': public['projects'].pop()
    elif change == 'float_count':
        with pytest.raises(ValueError): spec.project_ids(40.0)
        return
    elif change == 'reorder': public['projects'][0:2] = reversed(public['projects'][0:2])
    elif change == 'missing': public['projects'][0].pop('sale_proceeds_pence')
    elif change == 'repeat': public['projects'][-1]['id'] = 'P01'
    elif change == 'bool': public['opening_cash_pence'] = True
    elif change == 'float': public['projects'][0]['annual_opex_pence']['2025'] = 1.0
    elif change == 'rate': public['scenarios'][0]['bank_rates_p12']['2024'] = spec.SCALE + 1
    elif change == 'money_bound': public['projects'][-1]['acquisition_cost_pence'] = 10**9 + 1
    elif change == 'inactive_revenue': public['projects'][0]['annual_revenue_pence']['2024'] = 1
    elif change == 'scenario': public['scenarios'][0]['id'] = 'other'
    elif change == 'calendar': public['years'][0] = 2024.0
    elif change == 'discount': public['discount_factors_p12']['2024'] = spec.SCALE - 1
    else: public['provenance']['raw_ancestors']['NYU'] = '0' * 64
    with pytest.raises(ValueError): spec.load_spec(public)


def test_schema_JSON_path_copies_and_retains_exact_contract_without_original_mutation(tmp_path):
    public = specification(48); path = tmp_path / 'public.json'; path.write_text(json.dumps(public))
    assert spec.load_spec(path) == public
    parsed = spec.load_spec(public); parsed['projects'][0]['acquisition_cost_pence'] = 999
    assert public['projects'][0]['acquisition_cost_pence'] == 100
    assert spec.CONTRACT == frozen_schema.CONTRACT
    with pytest.raises(ValueError): frozen_schema.load_spec(public)
    assert frozen_schema.PROJECT_COUNTS == (18, 26, 28, 30)


@pytest.mark.parametrize('second,factor,numerator,expected', [
    (1, 10**12 // 4, -(10**12 // 2), -1),
    (2, 10**12 // 2, 10**12 // 2, 1),
    (1, 10**12 // 2, 0, 0),
])
def test_original_signed_half_penny_NPV_includes_time_zero_inside_only_round(second, factor, numerator, expected):
    public = specification(56); public['opening_cash_pence'] = 1; public['discount_factors_p12'] = annual(factor)
    project = public['projects'][-1]
    project.update(acquisition_cost_pence=1, depreciation_years=1,
        annual_revenue_pence={**annual(0), '2025': 1, '2026': second}, annual_opex_pence=annual(0))
    result = ledger.simulate(public, plan(public, 'P56'))
    assert result['objective_pence'] == expected
    assert result['scenarios']['S01']['net_npv_numerator'] == str(numerator)
    assert_conserved(result)


def test_last_project_FIFO_uses_two_prior_origins_then_expires_residue():
    public = specification(56); public.update(facility_limit_pence=0, tax_rate_p12=spec.SCALE // 2)
    project = public['projects'][-1]
    project.update(acquisition_cost_pence=1, depreciation_years=1, sale_year=2029,
        annual_revenue_pence={**annual(0), '2027': 15, '2029': 20},
        annual_opex_pence={**annual(0), '2025': 9, '2026': 20})
    result = ledger.simulate(public, plan(public, 'P56')); assert result['feasible']
    vintages = {(r['year'], r['vintage']): r for r in result['scenarios']['S01']['tax_vintages']}
    assert (row(result, 2025)['loss_created'], row(result, 2026)['loss_created']) == (10, 20)
    assert (vintages[2027, 2025]['used'], vintages[2027, 2026]['used']) == (10, 5)
    assert vintages[2029, 2026]['expired'] == 15 and row(result, 2029)['current_tax'] == 10
    assert_conserved(result)


def financed(public):
    public.update(opening_cash_pence=100, minimum_cash_pence=10, lp_commitment_pence=200, facility_limit_pence=1000)
    public['projects'][-1].update(acquisition_cost_pence=180, depreciation_years=3, sale_year=2027,
        annual_revenue_pence=annual(0), annual_opex_pence={**annual(0), '2025': 50}, sale_proceeds_pence=150)
    for scenario in public['scenarios']:
        scenario['bank_rates_p12'] = annual(spec.SCALE // 10)
        scenario['haircuts_p12']['2026'] = spec.SCALE * 9 // 10
    return public


@pytest.mark.parametrize('commitment,feasible,gap', [(200, True, 0), (100, False, 33)])
def test_last_project_funding_priority_caps_call_and_never_plugs_gap(commitment, feasible, gap):
    public = financed(specification(48)); public['lp_commitment_pence'] = commitment
    result = ledger.simulate(public, plan(public, 'P48'))
    assert result['feasible'] is feasible and row(result, 2024)['lp_call'] == 90
    assert (row(result, 2025)['bank_draw'], row(result, 2025)['bank_interest']) == (50, 0)
    assert (row(result, 2026)['prior_certified_nav'], row(result, 2026)['borrowing_base']) == (120, 12)
    assert (row(result, 2026)['bank_interest'], row(result, 2026)['mandatory_margin']) == (5, 38)
    assert row(result, 2026)['funding_gap'] == gap
    if not feasible:
        assert result['objective_pence'] is None and result['scenarios']['S01']['npv_pence'] is None
        assert row(result, 2026)['cash_close'] == -23 and row(result, 2026)['lp_call'] == 10
        assert result['scenarios']['S01']['first_violation']['year'] == 2026
    assert_conserved(result)


def test_terminal_maturity_has_zero_base_and_no_extra_NAV_recovery():
    public = specification(40); public.update(opening_cash_pence=200, minimum_cash_pence=20)
    public['projects'][-1].update(sale_year=2043, acquisition_cost_pence=180, depreciation_years=20,
        annual_revenue_pence=annual(0), annual_opex_pence={**annual(0), '2025': 20}, sale_proceeds_pence=200)
    result = ledger.simulate(public, plan(public, 'P40')); last = row(result, 2043)
    assert result['feasible'] and last['borrowing_base'] == 0 and last['mandatory_margin'] > 0
    assert last['sale_proceeds'] == 200 and last['cash_close'] == last['bank_close'] == last['project_book_value'] == 0
    assert last['distribution'] == last['return_of_capital'] + last['profit_distribution']
    assert_conserved(result)


def test_loaded_financial_validation_AST_has_no_policy_changes_or_optimizer_dependency():
    current = ast.parse(Path(spec.__file__).read_text()); previous = ast.parse(Path(frozen_schema.__file__).read_text())
    names = ('require', 'canonical_sha', 'project_ids', '_keys', '_int', '_annual', 'load_spec')
    for name in names:
        one = next(n for n in current.body if isinstance(n, ast.FunctionDef) and n.name == name)
        two = next(n for n in previous.body if isinstance(n, ast.FunctionDef) and n.name == name)
        assert ast.dump(one, include_attributes=False) == ast.dump(two, include_attributes=False)
    assert ledger.original is original_journal and ledger.original_spec is original_schema
    for name, module in [('ledger', original_journal), ('spec', original_schema)]:
        assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() == ledger.UPSTREAM[name]
    for path in (spec.__file__, ledger.__file__):
        tree = ast.parse(Path(path).read_text())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        assert all(not any(word in ast.unparse(n).lower() for word in ('search', 'optim', 'excel', 'subprocess')) for n in imports)
