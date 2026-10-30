"""Typed public contract for a deterministic multi-entity monthly close."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from pathlib import Path

SCALE = 10**12
PRODUCTION_ENTITIES = 24
PRODUCTION_MONTHS = 120
SCENARIOS = ('S01', 'S02', 'S03')
CURRENCIES = ('GBP', 'USD', 'EUR')
PHASES = (
    'asof_contracts_and_project_postings', 'opening_principal_interest',
    'entity_interest_and_tax_FIFO', 'intercompany_mandatory_principal',
    'local_collateral_and_shared_GBP_margin', 'opening_trap_reserve_transfer',
    'ordered_intercompany_funding', 'ordered_shared_bank_funding',
    'bounded_external_capital_calls', 'equity_capped_distributions',
    'current_test_and_next_covenant_state', 'matched_eliminations_and_FX_close',
)
RULES = (
    'The same supplied investment plan is fixed and protected across all three scenarios. Each scenario starts independently from the supplied opening balances and state; cash, debt, covenant state, queues and shared bank usage never transfer between scenarios. This model contains no investment choice, objective or optimisation.',
    'Opening paid-in capital equals supplied unrestricted plus restricted cash. Opening bank and intercompany principal, project carrying assets, retained earnings and both tax/interest vintage queues are zero. Opening covenant trap and its pending cure count are the separately supplied state.',
    'Money is integer minor units of each named functional currency (GBP pence, USD cents, EUR cents). Rates and GBP-pence-per-functional-minor-unit FX are integer numerators over 10^12. Post nearest integer with half ties away from zero. Products are exact until their stated posting.',
    'Each monthly date is its first calendar day. All events in that month apply at monthly close in PHASES order, regardless of input row order. Fiscal years end in March. An event with effective_month equal to the current month applies; future events do not. Duplicate complete keys and effective dates are invalid. Contract maturity may fall up to twenty-four months beyond the last forecast month; the forecast end itself does not create a contractual repayment.',
    'Each project retains its supplied legal owner and functional currency. Selected acquisition cost settles in its commissioning month. Operations and depreciation start next month and include the sale month; sale follows that month depreciation. Ordinary depreciation is rounded original cost/life, capped at remaining basis, with final-life residual. Sale removes remaining book value; certified NAV is a collateral memo, never income.',
    'Bank terms join on entity_id, facility_id and currency; intercompany terms join on loan_id, lender_id, borrower_id and currency. Choose the latest matching effective month not later than the current month. Both ends of an intercompany loan have that same functional currency. First round the applicable term monthly-rate numerator times the scenario rate factor divided by 10^12 to an integer p12 rate numerator; then round opening principal times that posted rate divided by 10^12 to minor units. New draws accrue next month.',
    'Entity interest deduction capacity is rounded max(0, EBITDA) times its limit fraction. After expiry, use old denied-interest vintages FIFO before current expense; deny the remainder as a new current vintage. Taxable profit is EBITDA minus depreciation plus sale gain plus intercompany interest income minus allowed interest. Then expire and use prior tax losses FIFO. A vintage created in month v is usable in v+1 through v+N and expires before v+N+1. There is no deferred-tax asset.',
    'At or after intercompany maturity repay all opening principal; otherwise repay opening principal above the current limit. Transfers post equally to borrower payable and lender receivable, and to their cash. No matching or cash plug is allowed.',
    'Local bank base is the lesser of current local limit and prior-month certified NAV times current advance rate times one minus scenario haircut, rounded once. At or after bank maturity its base is zero. Repay local excess first, then repay shared-limit excess in bank_priority order. Outstanding shared GBP usage is the sum of each entity debt converted at current FX and rounded upward. Mandatory reduction uses upward-rounded local principal sufficient to cover the GBP excess.',
    'Only the opening trap controls this month restricted cash. If trapped, retain opening restricted cash and transfer positive unrestricted cash up to the stated reserve target; restricted cash cannot fund a loan or a distribution. Unrestricted surplus above this reserve and the cash minimum may still fund loans or distributions: trap is not a blanket distribution prohibition. If not trapped, release opening restricted cash. No forced reserve funding is invented.',
    'Fund deficiencies in the supplied loan_priority order using only lender unrestricted cash above its minimum and remaining loan limit, before bank funding. At or after maturity no new loan draw is allowed. Then fund in bank_priority order subject to local base and shared GBP headroom: allowable local minor units are floor(GBP headroom times 10^12 divided by current FX). Recompute shared usage after every draw. These priorities are contractual, not optimised.',
    'Then call external equity only up to each entity remaining cumulative commitment. Calls never regain commitment after capital returns. Any remaining shortfall to minimum cash is a real funding gap; continue diagnostic accounting but mark the scenario infeasible.',
    'Distribute unrestricted cash above minimum capped at nonnegative pre-distribution book equity. Return paid-in capital first, then distribute profit from retained earnings. Both cash classes, project assets and matched intercompany receivables/payables remain in the legal-entity balance sheet.',
    'Current debt service is bank plus intercompany cash interest and mandatory principal repayments, excluding optional new funding. Zero debt service always passes. Otherwise EBITDA times 10^12 must meet debt service times the covenant threshold. A breach sets next trap and resets cure count; two consecutive passes while opening trapped release next month. Current tests never change this month distribution or reserve.',
    'Translate monthly flows at the supplied current closing FX; opening capital uses supplied opening FX. Derive economic translation reserve from opening equity exposure at current versus prior FX. Separately record the explicit rounding difference between translating net postings and their separately posted components. Neither reserve may absorb a nonzero local accounting residual. Consolidate from exact integer FX numerators, eliminate matched same-currency intercompany principal and interest once, and report final GBP rounding separately.',
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _keys(value, keys, label):
    require(isinstance(value, dict) and set(value) == set(keys), label + ' fields differ')


def _int(value, low, high, label):
    require(type(value) is int and low <= value <= high, label + ' requires a bounded literal integer')


def _month(value):
    require(type(value) is str, 'A monthly date must be an ISO string')
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError('Invalid monthly date') from error
    require(parsed.day == 1 and parsed.isoformat() == value, 'Monthly dates must be canonical first-of-month dates')
    return parsed


def _next_month(value):
    return date(value.year + (value.month == 12), value.month % 12 + 1, 1)


def _series(value, months, low, high, label):
    _keys(value, months, label)
    for month in months:
        _int(value[month], low, high, label + '/' + month)


def _maturity(value, effective, months):
    maturity, last = _month(value), _month(months[-1])
    beyond_horizon = (maturity.year - last.year) * 12 + maturity.month - last.month
    return value >= effective and beyond_horizon <= 24


def load_spec(value):
    """Validate public primitives only; no ledger, search or engine calls."""
    raw = json.loads(Path(value).read_text()) if isinstance(value, (str, Path)) else deepcopy(value)
    _keys(raw, ('schema_version', 'dimension_mode', 'months', 'reporting_currency', 'fiscal_year_end_month',
        'opening_fx_gbp_p12', 'shared_bank_limit_gbp_pence', 'entities', 'projects', 'fixed_plan',
        'plan_policy', 'bank_terms', 'intercompany_loans', 'intercompany_terms', 'bank_priority',
        'loan_priority', 'scenarios'), 'Entity group specification')
    require(type(raw['schema_version']) is int and raw['schema_version'] == 1
            and raw['dimension_mode'] in ('production', 'toy')
            and raw['reporting_currency'] == 'GBP'
            and type(raw['fiscal_year_end_month']) is int and raw['fiscal_year_end_month'] == 3,
            'Unsupported public financial contract')
    n, m = (24, 120) if raw['dimension_mode'] == 'production' else (2, 3)
    months = raw['months']
    require(isinstance(months, list) and len(months) == m, 'Public month dimension differs')
    parsed = [_month(month) for month in months]
    require(all(_next_month(a) == b for a, b in zip(parsed, parsed[1:])), 'Public months must be consecutive and ordered')
    _int(raw['shared_bank_limit_gbp_pence'], 0, 10**12, 'Shared bank GBP limit')
    ids = [f'E{i:02d}' for i in range(1, n + 1)]
    entities = raw['entities']
    require(isinstance(entities, list) and all(isinstance(e, dict) for e in entities)
            and [e.get('id') for e in entities] == ids, 'Exactly the ordered legal-entity IDs are required')
    for e in entities:
        _keys(e, ('id', 'currency', 'opening_cash_minor', 'opening_restricted_minor', 'opening_trap',
            'opening_cure_count', 'minimum_cash_minor', 'reserve_target_minor', 'additional_commitment_minor',
            'tax_rate_p12', 'interest_limit_p12', 'tax_carry_months', 'interest_carry_months',
            'covenant_threshold_p12', 'facility_id'), e['id'])
        require(e['currency'] in CURRENCIES and type(e['facility_id']) is str and bool(e['facility_id']), 'Invalid entity currency or facility')
        for key in ('opening_cash_minor', 'opening_restricted_minor', 'minimum_cash_minor',
                    'reserve_target_minor', 'additional_commitment_minor'):
            _int(e[key], 0, 10**11, e['id'] + '/' + key)
        require(e['opening_cash_minor'] >= e['minimum_cash_minor'], 'Opening unrestricted cash is below minimum')
        require(type(e['opening_trap']) is bool, 'Opening trap must be Boolean')
        _int(e['opening_cure_count'], 0, 1, 'Opening cure count')
        require(e['opening_trap'] or e['opening_cure_count'] == 0, 'An untrapped entity has no pending cure count')
        for key in ('tax_rate_p12', 'interest_limit_p12'):
            _int(e[key], 0, SCALE, key)
        _int(e['covenant_threshold_p12'], 1, 4 * SCALE, 'Covenant threshold')
        for key in ('tax_carry_months', 'interest_carry_months'):
            _int(e[key], 1, 24, key)
    currencies = sorted({e['currency'] for e in entities} | {'GBP'})
    _keys(raw['opening_fx_gbp_p12'], currencies, 'Opening FX')
    for currency, rate in raw['opening_fx_gbp_p12'].items():
        _int(rate, SCALE // 100, 10 * SCALE, 'Opening FX/' + currency)
    require(raw['opening_fx_gbp_p12']['GBP'] == SCALE, 'GBP translation must be one')
    if raw['dimension_mode'] == 'production':
        require(len({e['currency'] for e in entities}) >= 2, 'Production requires real cross-currency exposure')
    by_id = {e['id']: e for e in entities}
    projects = raw['projects']
    require(isinstance(projects, list) and all(isinstance(p, dict) for p in projects)
            and [p.get('id') for p in projects] == [f'P{i:02d}' for i in range(1, n + 1)], 'Exactly the ordered fixed projects are required')
    _keys(raw['fixed_plan'], [p['id'] for p in projects], 'Provided fixed plan')
    require(raw['plan_policy'] == 'provided_fixed_not_an_optimisation_task', 'Investment choices must be provided, not repaired or optimised')
    for p in projects:
        _keys(p, ('id', 'entity_id', 'currency', 'commission_month', 'sale_month', 'cost_minor',
            'depreciation_months', 'revenue_minor', 'opex_minor', 'sale_minor'), p['id'])
        require(type(p['entity_id']) is str and p['entity_id'] in by_id
                and p['currency'] == by_id[p['entity_id']]['currency'], 'A project must retain its legal owner functional currency')
        require(p['commission_month'] in months and p['sale_month'] in months
                and p['commission_month'] < p['sale_month'], 'Project dates are outside the public horizon')
        _int(p['cost_minor'], 1, 10**9, 'Project cost')
        _int(p['sale_minor'], 0, 10**9, 'Project sale')
        _int(p['depreciation_months'], 1, 120, 'Depreciation months')
        _int(raw['fixed_plan'][p['id']], 0, 1, 'Provided plan choice')
        for key in ('revenue_minor', 'opex_minor'):
            _series(p[key], months, 0, 10**9, p['id'] + '/' + key)
            require(all(p[key][month] == 0 for month in months
                        if not p['commission_month'] < month <= p['sale_month']), 'Operating flow outside project life')
    require(isinstance(raw['bank_priority'], list) and all(type(v) is str for v in raw['bank_priority'])
            and raw['bank_priority'] == list(dict.fromkeys(raw['bank_priority']))
            and set(raw['bank_priority']) == set(ids), 'Bank priority must contain every entity exactly once')
    require(isinstance(raw['bank_terms'], list), 'Bank terms must be a public event list')
    bank_keys = set()
    for t in raw['bank_terms']:
        _keys(t, ('entity_id', 'facility_id', 'currency', 'effective_month', 'maturity_month',
            'local_limit_minor', 'monthly_rate_p12', 'advance_rate_p12'), 'Bank term')
        require(type(t['entity_id']) is str and t['entity_id'] in by_id, 'Unknown bank entity')
        e = by_id[t['entity_id']]
        require((t['facility_id'], t['currency']) == (e['facility_id'], e['currency']), 'Bank term complete join key differs')
        require(t['effective_month'] in months and _maturity(t['maturity_month'], t['effective_month'], months), 'Invalid bank event dates')
        key = (t['entity_id'], t['facility_id'], t['currency'], t['effective_month'])
        require(key not in bank_keys, 'Duplicate complete bank event key')
        bank_keys.add(key)
        _int(t['local_limit_minor'], 0, 10**11, 'Local bank limit')
        _int(t['monthly_rate_p12'], 0, SCALE // 2, 'Bank monthly rate')
        _int(t['advance_rate_p12'], 0, SCALE, 'Advance rate')
    require(all((e['id'], e['facility_id'], e['currency'], months[0]) in bank_keys for e in entities), 'Every entity needs opening complete bank terms')
    loans = raw['intercompany_loans']
    require(isinstance(loans, list) and len(loans) <= 96, 'Intercompany loan dimension exceeds its bound')
    loan_ids = []
    for loan in loans:
        _keys(loan, ('id', 'lender_id', 'borrower_id', 'currency'), 'Intercompany loan')
        require(all(type(loan[k]) is str for k in ('id', 'lender_id', 'borrower_id', 'currency'))
                and loan['id'] and loan['id'] not in loan_ids
                and loan['lender_id'] in by_id and loan['borrower_id'] in by_id
                and loan['lender_id'] != loan['borrower_id'], 'Invalid bilateral loan identity')
        require(loan['currency'] == by_id[loan['lender_id']]['currency'] == by_id[loan['borrower_id']]['currency'],
                'Both ends of a bilateral loan require the same functional currency')
        loan_ids.append(loan['id'])
    require(isinstance(raw['loan_priority'], list) and len(raw['loan_priority']) == len(loan_ids)
            and set(raw['loan_priority']) == set(loan_ids), 'Loan priority must list every loan exactly once')
    loan_by_id = {loan['id']: loan for loan in loans}
    require(isinstance(raw['intercompany_terms'], list), 'Intercompany terms must be a public event list')
    loan_keys = set()
    for t in raw['intercompany_terms']:
        _keys(t, ('loan_id', 'lender_id', 'borrower_id', 'currency', 'effective_month',
            'maturity_month', 'limit_minor', 'monthly_rate_p12'), 'Intercompany term')
        require(type(t['loan_id']) is str and t['loan_id'] in loan_by_id, 'Unknown loan event')
        loan = loan_by_id[t['loan_id']]
        require(all(t[key] == loan[key] for key in ('lender_id', 'borrower_id', 'currency')), 'Intercompany complete join key differs')
        require(t['effective_month'] in months and _maturity(t['maturity_month'], t['effective_month'], months), 'Invalid intercompany event dates')
        key = (t['loan_id'], t['lender_id'], t['borrower_id'], t['currency'], t['effective_month'])
        require(key not in loan_keys, 'Duplicate complete intercompany event key')
        loan_keys.add(key)
        _int(t['limit_minor'], 0, 10**11, 'Intercompany limit')
        _int(t['monthly_rate_p12'], 0, SCALE // 2, 'Intercompany monthly rate')
    require(all((loan['id'], loan['lender_id'], loan['borrower_id'], loan['currency'], months[0]) in loan_keys for loan in loans), 'Every loan needs opening complete terms')
    if raw['dimension_mode'] == 'production':
        participants = {loan[key] for loan in loans for key in ('lender_id', 'borrower_id')}
        require(participants == set(ids), 'Every production entity must participate in a real intercompany relationship')
    scenarios = raw['scenarios']
    require(isinstance(scenarios, list) and all(isinstance(s, dict) for s in scenarios)
            and [s.get('id') for s in scenarios] == list(SCENARIOS), 'Exactly the three ordered scenarios are required')
    for s in scenarios:
        _keys(s, ('id', 'revenue_factor_p12', 'opex_factor_p12', 'sale_factor_p12', 'nav_factor_p12',
            'haircut_p12', 'rate_factor_p12', 'fx_gbp_p12'), s['id'])
        for key in ('revenue_factor_p12', 'opex_factor_p12', 'sale_factor_p12', 'nav_factor_p12'):
            _series(s[key], months, 0, 3 * SCALE, s['id'] + '/' + key)
        _series(s['haircut_p12'], months, 0, SCALE, 'Haircut')
        _series(s['rate_factor_p12'], months, 0, 2 * SCALE, 'Rate factor')
        _keys(s['fx_gbp_p12'], currencies, 'Scenario functional currencies')
        for currency in currencies:
            _series(s['fx_gbp_p12'][currency], months, SCALE // 100, 10 * SCALE, 'Scenario FX/' + currency)
        require(all(rate == SCALE for rate in s['fx_gbp_p12']['GBP'].values()), 'GBP FX must be one in every month')
    return raw
