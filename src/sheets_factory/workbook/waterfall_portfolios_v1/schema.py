"""Shape, vocabulary and canonical identity only; no financial arithmetic."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CONTRACT_PATH = ROOT / 'config/waterfall_transfer_frozen_contract_v1.json'
CONTRACT_SHA256 = '64da7a85b93bda660490ef4c10d7085acc798cffc487475ce44029fcb3d10599'
SPEC_KIND = 'hypothetical_waterfall_portfolios_posted_business_spec'
RESULT_KIND = 'hypothetical_multi_fund_waterfall_independent_values'
INTEGER_LIMIT = 2**53
YEARS = tuple(range(2025, 2045))
HISTORICAL_YEARS = (2025, 2026)
SCENARIOS = ('BASE', 'DOWN', 'UP')
FUND_TYPES = ('income_credit', 'real_assets', 'growth', 'mixed_vintage')
LAYOUTS = ('annual_columns', 'transaction_rows', 'scenario_panels', 'investor_bridge')
ROW_FIELDS = tuple('''opening_cash lp_call asset_investment operating_receipts realization_receipts management_fee operating_cost reserve cash_before_distribution available_cash opening_unreturned_capital opening_unpaid_preference cumulative_lp_paid_in preference_accrual capital_entitlement preference_entitlement capital_paid preference_paid after_capital_cash after_preference_cash lp_profit_before_catchup gp_profit_before_catchup catchup_entitlement catchup_paid after_catchup_cash tier1_cash tier1_lp tier1_gp tier2_cash tier2_lp tier2_gp tier3_cash tier3_lp tier3_gp lp_promote_cash gp_promote_cash lp_total_distribution gp_total_distribution fund_total_distribution closing_cash closing_unreturned_capital closing_unpaid_preference cumulative_lp_distributions cumulative_lp_profit cumulative_gp_profit lp1_call lp2_call lp1_distribution lp2_distribution lp1_net_cashflow lp2_net_cashflow gp_net_cashflow fund_cash_residual recipient_cash_residual principal_residual preference_residual'''.split())
AGGREGATE_FIELDS = tuple('''lp_call asset_investment operating_receipts realization_receipts management_fee operating_cost capital_paid preference_paid catchup_paid lp_promote_cash gp_promote_cash lp_total_distribution gp_total_distribution fund_total_distribution closing_cash closing_unreturned_capital closing_unpaid_preference lp1_net_cashflow lp2_net_cashflow gp_net_cashflow'''.split())
INVARIANT_FIELDS = ('fund_cash_residual', 'recipient_cash_residual', 'principal_residual', 'preference_residual')
PERIOD_MONEY_FIELDS = ('lp_call_pence', 'asset_investment_pence', 'operating_receipts_pence', 'realization_receipts_pence',
                       'management_fee_pence', 'operating_cost_pence', 'reserve_pence')
OPENING_FIELDS = ('opening_cash_pence', 'opening_investment_book_cost_pence', 'opening_unreturned_capital_pence',
                  'opening_unpaid_preference_pence', 'opening_cumulative_lp_paid_in_pence',
                  'opening_cumulative_lp_distributions_pence', 'opening_cumulative_lp_profit_pence',
                  'opening_cumulative_gp_profit_pence')
FUND_KEYS = {'id', 'number', 'type', 'layout', 'fund_ledger_sign', 'lp1_share_bp', 'preferred_rate_bp',
    'compound_unpaid_preference', 'base_gp_carry_bp', 'promote_gp_bp', 'lp_distribution_multiple_threshold_bp',
    'call_month', 'commitment_pence', 'scenarios', *OPENING_FIELDS}


def require(condition, message):
    if not condition: raise ValueError(message)


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


def contract():
    raw = CONTRACT_PATH.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == CONTRACT_SHA256, 'The frozen waterfall business contract changed')
    value = json.loads(raw)
    require(tuple(value['results_schema']['row_monetary_fields_pence']) == ROW_FIELDS
            and tuple(value['results_schema']['aggregate_monetary_fields_pence']) == AGGREGATE_FIELDS,
            'The complete waterfall vocabulary changed')
    return value


def _integer(value, *, minimum=0, maximum=INTEGER_LIMIT-1):
    require(type(value) is int and minimum <= value <= maximum, 'Use an exact bounded integer, never a Boolean or float')


def validate_spec(value):
    require(type(value) is dict and set(value) == {'kind', 'version', 'dimension_mode', 'contract', 'contract_sha256',
        'seed', 'years', 'historical_years', 'scenario_ids', 'funds'}, 'The exact public raw schema is required')
    require(value['kind'] == SPEC_KIND and type(value['version']) is int and value['version'] == 1,
            'Use the new waterfall specification identity')
    c = contract()
    require(value['contract_sha256'] == CONTRACT_SHA256 and type(value['contract']) is dict
        and set(value['contract']) == {'path', 'sha256', 'bytes'}
        and value['contract']['sha256'] == CONTRACT_SHA256 and value['contract']['bytes'] == 15174
        and isinstance(value['contract']['path'], str), 'Bind the complete frozen business contract')
    require(value['dimension_mode'] in ('production', 'toy'), 'Declare production or an explicit toy')
    _integer(value['seed'], maximum=2**32-1)
    years, scenarios, funds = value['years'], value['scenario_ids'], value['funds']
    require(isinstance(years, list) and years and all(type(y) is int and y in YEARS for y in years)
        and years == list(range(years[0], years[-1]+1)), 'Use ordered consecutive declared calendar years')
    require(value['historical_years'] == [y for y in years if y in HISTORICAL_YEARS], 'Keep the historical year identity')
    require(isinstance(scenarios, list) and scenarios and len(set(scenarios)) == len(scenarios)
        and all(x in SCENARIOS for x in scenarios), 'Use unique declared scenarios')
    require(isinstance(funds, list) and funds, 'Supply nonempty fund assumptions')
    if value['dimension_mode'] == 'production':
        require(years == list(YEARS) and scenarios == list(SCENARIOS) and len(funds) == 24
            and value['seed'] == c['seed'], 'The complete fixed production pool must be retained')
        require([f['id'] for f in funds] == [f'F{i:03d}' for i in range(1,25)], 'Keep the original fund order')
    else:
        require(len(funds) <= 4 and len(years) <= 4, 'Toys are explicitly limited to four funds and four years')
    require(len({f['id'] for f in funds}) == len(funds), 'Fund identities must be unique')
    for f in funds:
        require(type(f) is dict and set(f) == FUND_KEYS, 'Use the complete fund schema without private answers')
        _integer(f['number'], minimum=1, maximum=24)
        require(f['id'] == f"F{f['number']:03d}" and f['type'] in FUND_TYPES and f['layout'] in LAYOUTS
            and f['fund_ledger_sign'] in ('signed_cash_uses', 'positive_deduction_uses'), 'Unknown fund identity or presentation')
        for key in ('lp1_share_bp', 'base_gp_carry_bp'): _integer(f[key], minimum=1, maximum=9999)
        _integer(f['preferred_rate_bp'], maximum=10000)
        _integer(f['call_month'], minimum=1, maximum=12)
        _integer(f['commitment_pence'], minimum=1)
        require(type(f['compound_unpaid_preference']) is bool and f['promote_gp_bp'] == [2000,3000,4000]
            and f['lp_distribution_multiple_threshold_bp'] == [12500,17500], 'Keep the public promote tiers and compounding flag')
        for key in OPENING_FIELDS: _integer(f[key])
        _integer(f['opening_cumulative_lp_paid_in_pence'], minimum=1)
        require(isinstance(f['scenarios'], list) and [x['id'] for x in f['scenarios']] == scenarios,
                'Each fund requires every ordered scenario')
        for s in f['scenarios']:
            require(set(s) == {'id','periods'} and isinstance(s['periods'],list)
                and [x['year'] for x in s['periods']] == years, 'Every scenario requires every ordered year')
            for p in s['periods']:
                require(type(p) is dict and set(p) == {'year','call_date',*PERIOD_MONEY_FIELDS}, 'Use complete exogenous period facts only')
                require(isinstance(p['call_date'],str) and date.fromisoformat(p['call_date']) == date(p['year'],f['call_month'],1),
                        'The public call date must be the declared first day of its fund month')
                for key in PERIOD_MONEY_FIELDS: _integer(p[key])
    return deepcopy(value)
