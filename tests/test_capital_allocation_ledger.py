from copy import deepcopy
from decimal import Decimal
import json

import pytest

from sheets_factory.workbook.capital_allocation.spec import (
    ANNUAL_FIELDS, PROJECT_IDS, RAW_ANCESTORS, SCALE, SCENARIO_IDS, YEARS, load_spec,
)
from sheets_factory.workbook.capital_allocation.ledger import Journal, simulate


def annual(value):
    return {str(year): value for year in YEARS}


def specification():
    projects = []
    for identifier in PROJECT_IDS:
        projects.append({'id': identifier, 'commission_year': 2024, 'sale_year': 2026,
            'acquisition_cost_pence': 100, 'depreciation_years': 2,
            'annual_revenue_pence': {**annual(0), '2025': 80, '2026': 80},
            'annual_opex_pence': {**annual(0), '2025': 10, '2026': 10},
            'sale_proceeds_pence': 0})
    scenarios = [{'id': identifier, 'revenue_factors_p12': annual(SCALE),
        'opex_factors_p12': annual(SCALE), 'nav_factors_p12': annual(SCALE),
        'sale_factors_p12': annual(SCALE), 'bank_rates_p12': annual(0),
        'haircuts_p12': annual(0)} for identifier in SCENARIO_IDS]
    return {'schema_version': 1, 'currency': 'GBP', 'monetary_unit': 'pence', 'years': list(YEARS),
        'opening_cash_pence': 1000, 'minimum_cash_pence': 0, 'lp_commitment_pence': 1000,
        'facility_limit_pence': 1000, 'advance_rate_p12': SCALE, 'tax_rate_p12': 0,
        'tax_loss_carry_years': 2, 'discount_factors_p12': annual(SCALE),
        'projects': projects, 'scenarios': scenarios,
        'provenance': {'kind': 'synthetic_capital_allocation_extension', 'raw_ancestors': deepcopy(RAW_ANCESTORS)}}


def plan(*identifiers):
    return {identifier: int(identifier in identifiers) for identifier in PROJECT_IDS}


def scenario(result, identifier='S01'):
    return result['scenarios'][identifier]


def year(result, number, identifier='S01'):
    return next(row for row in scenario(result, identifier)['annual'] if row['year'] == number)


def test_hand_calculated_project_profit_capital_returns_and_double_entry():
    spec = specification()
    spec['tax_rate_p12'] = SCALE // 4
    before = deepcopy(spec)
    result = simulate(spec, plan('P01'))
    assert spec == before
    assert result['feasible'] is True and result['objective_pence'] == 30
    assert result['optimisation_performed'] is False and result['unique_optimum_claimed'] is False
    assert year(result, 2024)['distribution'] == 900
    first, last = year(result, 2025), year(result, 2026)
    assert (first['depreciation'], first['current_tax'], first['net_income']) == (50, 5, 15)
    assert (first['distribution'], first['return_of_capital'], first['profit_distribution']) == (65, 65, 0)
    assert (last['distribution'], last['return_of_capital'], last['profit_distribution']) == (65, 35, 30)
    assert last['capital_close'] == last['retained_close'] == last['project_book_value'] == 0
    for item in result['scenarios'].values():
        assert len(item['annual']) == 20 and len(item['tax_vintages']) == 400
        assert item['all_journals_balance']
        assert item['lp_cashflows'][0] == {'date': '2023-04-01', 'amount_pence': -1000}
        assert all(set(row) == {'year', *ANNUAL_FIELDS} for row in item['annual'])
        for transaction in item['journal']:
            assert sum(transaction['debits'].values()) == sum(transaction['credits'].values())
        assert all(row[field] == 0 for row in item['annual'] for field in
                   ('balance_check', 'cash_check', 'bank_check', 'capital_check', 'loss_check'))


def test_shared_plan_uses_worst_scenario_not_average_or_scenario_specific_choice():
    spec = specification()
    spec['scenarios'][1]['revenue_factors_p12'] = annual(SCALE // 2)
    result = simulate(spec, plan('P01'))
    assert [scenario(result, identifier)['npv_pence'] for identifier in SCENARIO_IDS] == [40, -40, 40]
    assert result['objective_pence'] == -40
    with pytest.raises(ValueError, match='fields differ'):
        simulate(spec, {identifier: plan('P01') for identifier in SCENARIO_IDS})


def test_fifo_uses_oldest_positive_vintage_and_expires_before_current_profit():
    spec = specification()
    spec['facility_limit_pence'] = 0
    spec['tax_rate_p12'] = SCALE // 2
    project = spec['projects'][0]
    project.update(acquisition_cost_pence=1, depreciation_years=1, sale_year=2029,
        annual_revenue_pence={**annual(0), '2027': 15, '2029': 20},
        annual_opex_pence={**annual(0), '2025': 9, '2026': 20})
    result = simulate(spec, plan('P01'))
    assert result['feasible']
    vintages = {(r['year'], r['vintage']): r for r in scenario(result)['tax_vintages']}
    assert year(result, 2025)['loss_created'] == 10
    assert year(result, 2026)['loss_created'] == 20
    assert vintages[2027, 2025]['used'] == 10
    assert vintages[2027, 2026]['used'] == 5
    assert vintages[2027, 2026]['closing'] == 15
    assert vintages[2029, 2026]['expired'] == 15
    assert year(result, 2029)['taxable_after_losses'] == 20
    assert year(result, 2029)['current_tax'] == 10


def financed_spec():
    spec = specification()
    spec.update(opening_cash_pence=100, minimum_cash_pence=10,
                lp_commitment_pence=200, facility_limit_pence=1000)
    project = spec['projects'][0]
    project.update(acquisition_cost_pence=180, depreciation_years=3, sale_year=2027,
        annual_revenue_pence=annual(0), annual_opex_pence={**annual(0), '2025': 50},
        sale_proceeds_pence=150)
    for item in spec['scenarios']:
        item['bank_rates_p12'] = annual(SCALE // 10)
        item['haircuts_p12']['2026'] = SCALE * 9 // 10
    return spec


def test_previous_nav_interest_margin_and_limited_calls_follow_financing_priority():
    result = simulate(financed_spec(), plan('P01'))
    assert result['feasible']
    first, second, third = (year(result, y) for y in (2024, 2025, 2026))
    assert first['borrowing_base'] == 0 and first['lp_call'] == 90
    assert second['prior_certified_nav'] == 180 and second['borrowing_base'] == 180
    assert second['bank_interest'] == 0 and second['bank_draw'] == 50
    assert second['lp_call'] == 0 and second['cash_close'] == 10
    assert third['bank_interest'] == 5 and third['borrowing_base'] == 12
    assert third['mandatory_margin'] == 38 and third['optional_repayment'] == 0
    assert third['lp_call'] == 43 and third['bank_close'] == 12
    assert third['lp_called_close'] == 133
    assert year(result, 2027)['optional_repayment'] == 12
    assert year(result, 2043)['cash_close'] == year(result, 2043)['bank_close'] == 0


def test_financing_deficiency_is_infeasible_not_silently_filled_or_valued_as_zero():
    spec = financed_spec()
    spec['lp_commitment_pence'] = 100
    result = simulate(spec, plan('P01'))
    assert result['feasible'] is False and result['objective_pence'] is None
    row = year(result, 2026)
    assert row['lp_call'] == 10 and row['funding_gap'] == 33
    assert row['cash_close'] == -23
    assert scenario(result)['npv_pence'] is None
    assert scenario(result)['first_violation'] == {'year': 2026, 'kind': 'unfunded_cash_deficiency', 'amount_pence': 33}
    assert len(scenario(result)['annual']) == 20
    assert all(row['lp_called_close'] <= 100 for row in scenario(result)['annual'])


def test_same_year_three_factor_base_is_rounded_only_once():
    spec = specification()
    project = spec['projects'][0]
    project.update(acquisition_cost_pence=1, depreciation_years=20,
        annual_revenue_pence=annual(0), annual_opex_pence={**annual(0), '2025': 1})
    spec['advance_rate_p12'] = SCALE // 2
    for item in spec['scenarios']:
        item['haircuts_p12'] = annual(SCALE // 2)
    result = simulate(spec, plan('P01'))
    assert year(result, 2025)['prior_certified_nav'] == 1
    assert year(result, 2025)['borrowing_base'] == 0  # round(1 * .5 * .5), not round(round(.5)*.5)
    assert year(result, 2025)['bank_draw'] == 0
    assert year(result, 2025)['lp_call'] == 1


def test_depreciation_clamps_remaining_and_never_posts_negative_final_residual():
    spec = specification()
    project = spec['projects'][0]
    project.update(acquisition_cost_pence=2, depreciation_years=4, sale_year=2029,
        annual_revenue_pence=annual(0), annual_opex_pence=annual(0))
    result = simulate(spec, plan('P01'))
    rows = scenario(result)['project_flows']['P01']
    assert [row['depreciation'] for row in rows[:6]] == [0, 1, 1, 0, 0, 0]
    assert all(row['closing_book_value'] >= 0 for row in rows)


def test_npv_final_sum_rounding_and_time_zero_contribution_are_exact():
    spec = specification()
    spec.update(opening_cash_pence=1, minimum_cash_pence=0)
    spec['discount_factors_p12'] = annual(SCALE // 4)
    project = spec['projects'][0]
    project.update(acquisition_cost_pence=1, depreciation_years=1,
        annual_revenue_pence={**annual(0), '2025': 1, '2026': 1}, annual_opex_pence=annual(0))
    result = simulate(spec, plan('P01'))
    assert scenario(result)['npv_numerator'] == str(SCALE // 2)
    assert scenario(result)['net_npv_numerator'] == str(-SCALE // 2)
    assert result['objective_pence'] == -1  # half-away(.25 + .25 - t0 1), not round(.5)-1.
    project.update(commission_year=2025, sale_year=2026, annual_revenue_pence=annual(0))
    spec.update(opening_cash_pence=0)
    spec['discount_factors_p12'] = annual(SCALE // 2)
    negative = simulate(spec, plan('P01'))
    assert scenario(negative)['npv_numerator'] == str(-SCALE // 2)
    assert negative['objective_pence'] == -1


@pytest.mark.parametrize('revenue_second,factor,expected_net_numerator,expected', [
    (1, SCALE // 4, -SCALE // 2, -1),
    (2, SCALE // 2, SCALE // 2, 1),
    (1, SCALE // 2, 0, 0),
])
def test_time_zero_is_inside_sole_signed_round_on_both_sides_of_zero(
        revenue_second, factor, expected_net_numerator, expected):
    spec = specification()
    spec['opening_cash_pence'] = 1
    spec['discount_factors_p12'] = annual(factor)
    project = spec['projects'][0]
    project.update(acquisition_cost_pence=1, depreciation_years=1,
        annual_revenue_pence={**annual(0), '2025': 1, '2026': revenue_second},
        annual_opex_pence=annual(0))
    result = simulate(spec, plan('P01'))
    assert scenario(result)['net_npv_numerator'] == str(expected_net_numerator)
    assert result['objective_pence'] == expected


def test_sales_remove_book_assets_and_terminal_facility_is_not_rolled_over():
    spec = specification()
    project = spec['projects'][0]
    project.update(sale_year=2043, acquisition_cost_pence=180, depreciation_years=20,
        annual_revenue_pence=annual(0), annual_opex_pence={**annual(0), '2025': 20},
        sale_proceeds_pence=200)
    spec.update(opening_cash_pence=200, minimum_cash_pence=20)
    result = simulate(spec, plan('P01'))
    assert result['feasible']
    final = year(result, 2043)
    assert final['borrowing_base'] == 0 and final['mandatory_margin'] > 0
    assert final['sale_proceeds'] == 200
    assert final['cash_close'] == final['bank_close'] == final['project_book_value'] == 0
    assert final['distribution'] == final['return_of_capital'] + final['profit_distribution']


@pytest.mark.parametrize('change', ['float', 'bool', 'year_float', 'missing_project',
    'different_scenarios', 'nonoperating_revenue', 'too_large', 'ancestry', 'discount_increases'])
def test_public_spec_rejects_ambiguous_or_unsupported_primitives(change):
    spec = specification()
    if change == 'float': spec['tax_rate_p12'] = 0.25
    elif change == 'bool': spec['opening_cash_pence'] = True
    elif change == 'year_float': spec['years'][0] = 2024.0
    elif change == 'missing_project': spec['projects'].pop()
    elif change == 'different_scenarios': spec['scenarios'][0]['id'] = 'other'
    elif change == 'nonoperating_revenue': spec['projects'][0]['annual_revenue_pence']['2024'] = 1
    elif change == 'too_large': spec['projects'][0]['acquisition_cost_pence'] = 10**9 + 1
    elif change == 'ancestry': spec['provenance']['raw_ancestors']['NYU'] = '0' * 64
    else: spec['discount_factors_p12']['2024'] = SCALE - 1
    with pytest.raises(ValueError):
        load_spec(spec)


@pytest.mark.parametrize('choice', [True, 0.0, 2, -1])
def test_plan_requires_literal_binary_integers(choice):
    selected = plan('P01')
    selected['P01'] = choice
    with pytest.raises(ValueError):
        simulate(specification(), selected)


def test_unbalanced_journal_cannot_be_used_as_a_financial_plug():
    journal = Journal()
    with pytest.raises(ArithmeticError, match='Unbalanced'):
        journal.post(2024, 'not_an_allowed_funding_source', {'Cash': 10})
    assert not journal.entries and not journal.accounts


def test_reference_output_is_serialisable_and_all_zero_plan_is_still_evaluated():
    result = simulate(specification(), plan())
    assert result['feasible'] and result['objective_pence'] == 0
    assert year(result, 2024)['distribution'] == 1000
    assert json.loads(json.dumps(result, allow_nan=False)) == result
