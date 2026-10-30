"""Two-entity, three-month hand examples only; no production-scale execution."""
from copy import deepcopy
from datetime import date
import json

import pytest

from sheets_factory.workbook.entity_group.spec import (
    PHASES, PRODUCTION_ENTITIES, PRODUCTION_MONTHS, RULES, SCALE, load_spec,
)
from sheets_factory.workbook.entity_group.ledger import (
    _consume, _expire, _next_covenant, rounded, simulate,
)

MONTHS = ('2024-01-01', '2024-02-01', '2024-03-01')


def series(value, months=MONTHS):
    return dict.fromkeys(months, value)


def specification():
    entities = []
    for identity, cash, minimum in (('E01', 1000, 100), ('E02', 10, 10)):
        entities.append({'id': identity, 'currency': 'GBP', 'opening_cash_minor': cash,
            'opening_restricted_minor': 0, 'opening_trap': False, 'opening_cure_count': 0,
            'minimum_cash_minor': minimum, 'reserve_target_minor': 20,
            'additional_commitment_minor': 0, 'tax_rate_p12': 0 if identity == 'E01' else SCALE // 4,
            'interest_limit_p12': SCALE // 2, 'tax_carry_months': 2, 'interest_carry_months': 2,
            'covenant_threshold_p12': SCALE, 'facility_id': 'BANK'})
    projects = [{'id': 'P01', 'entity_id': 'E01', 'currency': 'GBP',
        'commission_month': MONTHS[0], 'sale_month': MONTHS[-1], 'cost_minor': 1,
        'depreciation_months': 2, 'revenue_minor': series(0), 'opex_minor': series(0), 'sale_minor': 0},
        {'id': 'P02', 'entity_id': 'E02', 'currency': 'GBP',
        'commission_month': MONTHS[0], 'sale_month': MONTHS[-1], 'cost_minor': 100,
        'depreciation_months': 2, 'revenue_minor': {MONTHS[0]: 0, MONTHS[1]: 5, MONTHS[2]: 200},
        'opex_minor': series(0), 'sale_minor': 0}]
    bank = [{'entity_id': e['id'], 'facility_id': 'BANK', 'currency': 'GBP',
        'effective_month': MONTHS[0], 'maturity_month': MONTHS[-1],
        'local_limit_minor': 0, 'monthly_rate_p12': 0, 'advance_rate_p12': SCALE} for e in entities]
    loan = {'id': 'L01', 'lender_id': 'E01', 'borrower_id': 'E02', 'currency': 'GBP'}
    term = {'loan_id': 'L01', 'lender_id': 'E01', 'borrower_id': 'E02', 'currency': 'GBP',
        'effective_month': MONTHS[0], 'maturity_month': MONTHS[-1],
        'limit_minor': 200, 'monthly_rate_p12': SCALE // 10}
    scenarios = [{'id': identity, 'revenue_factor_p12': series(SCALE), 'opex_factor_p12': series(SCALE),
        'sale_factor_p12': series(SCALE), 'nav_factor_p12': series(SCALE), 'haircut_p12': series(0),
        'rate_factor_p12': series(SCALE), 'fx_gbp_p12': {'GBP': series(SCALE)}} for identity in ('S01', 'S02', 'S03')]
    return {'schema_version': 1, 'dimension_mode': 'toy', 'months': list(MONTHS),
        'reporting_currency': 'GBP', 'fiscal_year_end_month': 3, 'opening_fx_gbp_p12': {'GBP': SCALE},
        'shared_bank_limit_gbp_pence': 0, 'entities': entities, 'projects': projects,
        'fixed_plan': {'P01': 0, 'P02': 1}, 'plan_policy': 'provided_fixed_not_an_optimisation_task',
        'bank_terms': bank, 'intercompany_loans': [loan], 'intercompany_terms': [term],
        'bank_priority': ['E01', 'E02'], 'loan_priority': ['L01'], 'scenarios': scenarios}


def s01(result):
    return result['scenarios']['S01']


def entity(result, identifier):
    return s01(result)['entities'][identifier]['monthly']


def no_loans(spec):
    spec['intercompany_loans'] = []
    spec['intercompany_terms'] = []
    spec['loan_priority'] = []


def test_hand_calculated_bilateral_financing_tax_interest_FIFO_and_all_balances():
    spec = specification()
    before = deepcopy(spec)
    result = simulate(spec)
    assert spec == before and result['feasible'] is True
    assert (result['entity_count'], result['month_count'], result['scenario_count']) == (2, 3, 3)
    assert result['fixed_plan'] == {'P01': 0, 'P02': 1}
    assert result['optimisation_performed'] is False
    assert result['financial_source_independently_certified'] is False
    assert result['workbook_engine_calls'] == result['model_calls'] == result['task_count'] == 0
    assert result['quality_or_difficulty_certified'] is False
    lender, borrower = entity(result, 'E01'), entity(result, 'E02')
    assert [r['ic_draw_received'] for r in borrower] == [100, 5, 0]
    assert [r['ic_interest_expense'] for r in borrower] == [0, 10, 11]
    assert [r['ic_principal_paid'] for r in borrower] == [0, 0, 105]
    assert [r['distribution'] for r in lender] == [800, 5, 116]
    assert [r['distribution'] for r in borrower] == [0, 0, 43]
    # February EBITDA5: rounded half of5 is3; interest10 =>7 denied,
    # taxable5-50-3=-48. March allows old7 + current11; 200-50-18-48=84.
    assert (borrower[1]['interest_capacity'], borrower[1]['interest_denied_created']) == (3, 7)
    assert borrower[1]['tax_loss_created'] == 48
    assert borrower[1]['interest_live_vintages'] == [{'vintage_month': MONTHS[1], 'balance_minor': 7}]
    assert borrower[2]['interest_old_used'] == 7 and borrower[2]['tax_loss_used'] == 48
    assert borrower[2]['taxable_after_loss'] == 84 and borrower[2]['current_tax'] == 21
    assert borrower[2]['interest_live_vintages'] == borrower[2]['tax_live_vintages'] == []
    assert [r['net_income'] for r in borrower] == [0, -55, 118]
    assert borrower[-1]['cash_close'] == 10 and borrower[-1]['restricted_close'] == 20
    assert borrower[-1]['capital_close'] == 0 and borrower[-1]['retained_close'] == 30
    assert lender[-1]['cash_close'] == 100 and lender[-1]['capital_close'] == 79 and lender[-1]['retained_close'] == 21
    for scenario in result['scenarios'].values():
        for data in scenario['entities'].values():
            assert len(data['monthly']) == 3
            assert all(v == 0 for row in data['monthly'] for v in row['residuals'].values())
        group = scenario['group_monthly']
        assert [r['intercompany_principal_eliminated_gbp_numerator'] // SCALE for r in group] == [100, 105, 0]
        assert [r['intercompany_interest_eliminated_gbp_numerator'] // SCALE for r in group] == [0, 10, 11]
        assert group[-1]['consolidated_cash_gbp_pence'] == group[-1]['consolidated_net_assets_gbp_pence'] == 130
        assert group[-1]['consolidated_external_bank_gbp_pence'] == group[-1]['consolidated_book_gbp_pence'] == 0
        fiscal = scenario['fiscal_years'][0]
        assert fiscal['cash_external_movement_gbp_numerator'] == -880 * SCALE  # -100+205-21-964
        assert all(fiscal[name + '_residual_gbp_numerator'] == 0 for name in ('cash', 'bank', 'net_assets'))
    assert s01(result)['mechanism_activation']['intercompany_interest']['count'] == 2
    assert s01(result)['all_declared_mechanisms_active'] is False


def test_current_breach_cannot_retroactively_trap_current_cash():
    result = simulate(specification())
    row = entity(result, 'E02')
    assert row[1]['trap_open'] is False and row[1]['covenant_passed'] is False
    assert row[1]['reserve_locked'] == 0 and row[1]['trap_next'] is True
    assert row[2]['trap_open'] is True and row[2]['reserve_locked'] == 20
    assert row[2]['covenant_passed'] is True and row[2]['cure_run_after_test'] == 1
    assert row[2]['trap_next'] is True
    # Reserve is protected; excess unrestricted cash still distributes43.
    assert row[2]['distribution'] == 43


def test_two_passing_tests_release_only_the_following_month_and_zero_service_passes():
    spec = specification()
    no_loans(spec)
    spec['fixed_plan'] = {'P01': 0, 'P02': 0}
    e = spec['entities'][0]
    e.update(opening_cash_minor=100, opening_restricted_minor=20, minimum_cash_minor=10, opening_trap=True)
    rows = entity(simulate(spec), 'E01')
    assert [r['debt_service'] for r in rows] == [0, 0, 0]
    assert [r['covenant_passed'] for r in rows] == [True, True, True]
    assert [r['trap_open'] for r in rows] == [True, True, False]
    assert [r['trap_next'] for r in rows] == [True, False, False]
    assert [r['reserve_released'] for r in rows] == [0, 0, 20]
    assert [r['distribution'] for r in rows] == [90, 0, 20]
    assert rows[-1]['cash_close'] == rows[-1]['capital_close'] == 10
    assert rows[-1]['restricted_close'] == 0


def test_future_event_not_used_early_and_same_day_complete_key_order_is_irrelevant():
    spec = specification()
    future = {**spec['intercompany_terms'][0], 'effective_month': MONTHS[2], 'monthly_rate_p12': 0}
    spec['intercompany_terms'].insert(0, future)
    before = simulate(spec)
    borrower = entity(before, 'E02')
    assert [r['ic_interest_expense'] for r in borrower] == [0, 10, 0]
    assert [r['term_effective_month'] for r in s01(before)['intercompany']['L01']] == [MONTHS[0], MONTHS[0], MONTHS[2]]
    spec['intercompany_terms'].reverse()
    spec['bank_terms'].reverse()
    after = simulate(spec)
    assert before['scenarios'] == after['scenarios']
    assert s01(before)['mechanism_activation']['effective_date_rollover']['active'] is True


def test_public_two_posting_rate_rounding_can_differ_from_single_final_posting():
    # R(999p12 * .5)=500p12, then R(1e9*500/1e12)=1 minor.
    # One final posting would R(.4995 minor)=0. Both are within public bounds.
    spec = specification()
    spec['entities'][0]['opening_cash_minor'] = 10**11
    spec['projects'][1].update(cost_minor=10**9, sale_minor=10**9)
    spec['intercompany_terms'][0].update(limit_minor=10**11, monthly_rate_p12=999)
    for scenario in spec['scenarios']:
        scenario['rate_factor_p12'] = series(SCALE // 2)
    rate = rounded(999 * (SCALE // 2))
    assert rate == 500 and rounded(10**9 * rate) == 1
    assert rounded(10**9 * 999 * (SCALE // 2), SCALE * SCALE) == 0
    result = simulate(spec)
    assert result['feasible'] is True
    assert entity(result, 'E02')[1]['ic_interest_expense'] == 1
    assert any('integer p12 rate numerator' in rule for rule in RULES)


def cross_currency_spec():
    spec = specification()
    no_loans(spec)
    spec['shared_bank_limit_gbp_pence'] = 2
    spec['bank_priority'] = ['E02', 'E01']
    spec['opening_fx_gbp_p12']['USD'] = SCALE
    spec['fixed_plan'] = {'P01': 1, 'P02': 1}
    for i, e in enumerate(spec['entities']):
        currency = 'GBP' if i == 0 else 'USD'
        e.update(currency=currency, opening_cash_minor=1, minimum_cash_minor=0,
            additional_commitment_minor=10, tax_rate_p12=0)
        spec['projects'][i].update(currency=currency, cost_minor=1, depreciation_months=120,
            revenue_minor=series(0), opex_minor={**series(0), MONTHS[1]: 1}, sale_minor=0)
        spec['bank_terms'][i].update(currency=currency, local_limit_minor=100)
    for scenario in spec['scenarios']:
        scenario['fx_gbp_p12']['USD'] = series(3 * SCALE // 2)
    return spec


def test_shared_GBP_limit_floor_and_real_cross_currency_FX_conservation():
    result = simulate(cross_currency_spec())
    e1, e2 = entity(result, 'E01'), entity(result, 'E02')
    assert e2[1]['bank_draw'] == 1  # floor(2GBP /1.5GBP-per-USD-minor)=1
    assert e1[1]['bank_draw'] == 0 and e1[1]['capital_call'] == 1
    assert e2[1]['capital_call'] == 0
    group = s01(result)['group_monthly']
    assert group[1]['shared_bank_usage_gbp_pence'] == 2  # ceil(1*1.5), not1
    assert group[0]['economic_FX_reserve_gbp_pence'] == 1
    assert e2[0]['economic_FX_this_month_gbp'] == 1
    assert all(r['translation_residual_gbp'] == 0 for r in e1 + e2)
    assert all(row[name + '_residual_gbp_numerator'] == 0 for row in group for name in ('cash', 'bank', 'net_assets'))
    assert s01(result)['mechanism_activation']['shared_facility_contention']['active'] is True
    assert s01(result)['mechanism_activation']['currency_translation']['active'] is True


def test_FX_revaluation_can_trigger_real_mandatory_shared_margin():
    spec = cross_currency_spec()
    # March bank is unmatured with local base1. Its prior1-unit USD debt now
    # costs3GBP against shared limit2, so shared margin must actually repay1USD.
    for term in spec['bank_terms']:
        term['maturity_month'] = '2024-04-01'
    for scenario in spec['scenarios']:
        scenario['fx_gbp_p12']['USD'][MONTHS[2]] = 3 * SCALE
    result = simulate(spec)
    row = entity(result, 'E02')[2]
    assert row['bank_local_margin'] == 0 and row['bank_shared_margin'] == 1
    assert s01(result)['group_monthly'][2]['bank_FX_gbp_numerator'] == 3 * SCALE // 2
    assert s01(result)['mechanism_activation']['bank_margin']['active'] is True


def test_genuine_funding_gap_remains_infeasible_without_an_accounting_plug():
    spec = specification()
    spec['intercompany_terms'][0]['limit_minor'] = 50
    result = simulate(spec)
    assert result['feasible'] is False
    first = s01(result)['first_funding_gap']
    assert first == {'month': MONTHS[0], 'entity_id': 'E02', 'amount_minor': 50}
    row = entity(result, 'E02')[0]
    assert row['cash_close'] == -40 and row['capital_call'] == 0
    assert all(v == 0 for data in s01(result)['entities'].values() for r in data['monthly'] for v in r['residuals'].values())
    assert len(entity(result, 'E02')) == 3


def test_sparse_FIFO_unit_events_expire_at_N_plus_1_and_use_oldest_first():
    queue = {0: 7, 1: 5}
    assert _expire(queue, 1, 1, MONTHS) == []
    remaining, used = _consume(queue, 9, MONTHS)
    assert remaining == 0 and used == [
        {'vintage_month': MONTHS[0], 'amount_minor': 7}, {'vintage_month': MONTHS[1], 'amount_minor': 2}]
    assert queue == {1: 3}
    queue = {0: 7, 1: 3}
    expired = _expire(queue, 2, 1, MONTHS)
    assert expired == [{'vintage_month': MONTHS[0], 'amount_minor': 7}]
    assert queue == {1: 3}
    assert all(amount > 0 for amount in queue.values())


def test_bad_cure_and_signed_half_ties_are_explicit():
    assert rounded(1, 2) == 1 and rounded(-1, 2) == -1
    state = _next_covenant(True, 1, 1, 2, SCALE)
    assert state == {'covenant_passed': False, 'cure_run_after_test': 0, 'trap_next': True, 'cure_count_next': 0}
    assert _next_covenant(False, 0, -100, 0, SCALE)['covenant_passed'] is True


@pytest.mark.parametrize('fault', ['bool_money', 'float_rate', 'wrong_currency', 'missing_entity',
    'cross_currency_loan', 'partial_bank_key', 'partial_loan_key', 'duplicate_event',
    'future_opening_terms', 'unordered_months', 'not_first_day', 'missing_month',
    'free_plan', 'bool_plan', 'wrong_fx', 'duplicate_priority', 'outside_operations',
    'too_long_queue', 'fake_production'])
def test_public_schema_rejects_unit_key_date_and_choice_ambiguities(fault):
    spec = specification()
    if fault == 'bool_money': spec['entities'][0]['opening_cash_minor'] = True
    elif fault == 'float_rate': spec['entities'][0]['tax_rate_p12'] = 0.5
    elif fault == 'wrong_currency': spec['projects'][1]['currency'] = 'USD'
    elif fault == 'missing_entity': spec['entities'].pop()
    elif fault == 'cross_currency_loan': spec['entities'][1]['currency'] = 'USD'
    elif fault == 'partial_bank_key': spec['bank_terms'][1]['entity_id'] = 'E01'
    elif fault == 'partial_loan_key': spec['intercompany_terms'][0]['borrower_id'] = 'E01'
    elif fault == 'duplicate_event': spec['bank_terms'].append(deepcopy(spec['bank_terms'][0]))
    elif fault == 'future_opening_terms': spec['intercompany_terms'][0]['effective_month'] = MONTHS[1]
    elif fault == 'unordered_months': spec['months'].reverse()
    elif fault == 'not_first_day': spec['months'][0] = '2024-01-02'
    elif fault == 'missing_month': del spec['scenarios'][0]['haircut_p12'][MONTHS[0]]
    elif fault == 'free_plan': spec['plan_policy'] = 'choose_best_investments'
    elif fault == 'bool_plan': spec['fixed_plan']['P02'] = True
    elif fault == 'wrong_fx': spec['scenarios'][0]['fx_gbp_p12']['GBP'][MONTHS[1]] -= 1
    elif fault == 'duplicate_priority': spec['bank_priority'] = ['E01', 'E01']
    elif fault == 'outside_operations': spec['projects'][1]['revenue_minor'][MONTHS[0]] = 1
    elif fault == 'too_long_queue': spec['entities'][0]['tax_carry_months'] = 120
    elif fault == 'fake_production': spec['dimension_mode'] = 'production'
    with pytest.raises(ValueError):
        load_spec(spec)


def test_toy_dimensions_never_implicitly_scale_and_each_scenario_is_closed_separately(tmp_path):
    spec = specification()
    spec['scenarios'][1]['revenue_factor_p12'] = series(2 * SCALE)
    path = tmp_path / 'public.json'
    path.write_text(json.dumps(spec))
    result = simulate(path)
    assert PRODUCTION_ENTITIES == 24 and PRODUCTION_MONTHS == 120
    assert result['dimension_mode'] == 'toy' and result['phases'] == list(PHASES)
    assert result['scenarios']['S01']['group_monthly'] != result['scenarios']['S02']['group_monthly']
    assert all(len(v['group_monthly']) == 3 for v in result['scenarios'].values())
    assert not result['quality_or_difficulty_certified']


def test_fiscal_March_boundary_telescopes_separately_from_calendar_months():
    mapping = dict(zip(MONTHS, ('2024-02-01', '2024-03-01', '2024-04-01')))
    def rebase(value):
        if isinstance(value, dict):
            return {mapping.get(k, k): rebase(v) for k, v in value.items()}
        if isinstance(value, list):
            return [rebase(v) for v in value]
        return mapping.get(value, value) if isinstance(value, str) else value
    result = simulate(rebase(specification()))
    years = s01(result)['fiscal_years']
    assert [r['fiscal_year'] for r in years] == [2024, 2025]
    assert [len(r['months']) for r in years] == [2, 1]
    assert all(r[name + '_residual_gbp_numerator'] == 0
               for r in years for name in ('cash', 'bank', 'net_assets'))


@pytest.mark.parametrize('fault', ['asset', 'vintage'])
def test_FX_or_reporting_rounding_never_absorbs_a_financial_residual(monkeypatch, fault):
    from sheets_factory.workbook.entity_group import ledger
    if fault == 'asset':
        original = ledger._project
        def corrupt(*args, **kwargs):
            posting = original(*args, **kwargs)
            if args[1]:
                posting['closing_book_minor'] += 1
            return posting
        monkeypatch.setattr(ledger, '_project', corrupt)
    else:
        original = ledger._consume
        def corrupt(*args, **kwargs):
            remaining, events = original(*args, **kwargs)
            if events:
                events[0]['amount_minor'] += 1
            return remaining, events
        monkeypatch.setattr(ledger, '_consume', corrupt)
    with pytest.raises(ValueError, match='Legal-entity accounting residual'):
        simulate(specification())


@pytest.mark.parametrize('maturity', ['2023-12-01', '2026-04-01', '2024-04-02'])
def test_invalid_maturity_bounds_are_public_errors(maturity):
    spec = specification()
    spec['bank_terms'][0]['maturity_month'] = maturity
    with pytest.raises(ValueError):
        load_spec(spec)
