"""Independent integer/Fraction waterfall postings; no spreadsheet or A arithmetic."""
from __future__ import annotations

from datetime import date
from fractions import Fraction

from . import schema


def _integer(value, label, *, nonnegative=True):
    if type(value) is not int or (nonnegative and value < 0):
        raise ValueError(f'{label} must be an exact {"nonnegative " if nonnegative else ""}integer')
    return value


def round_pence(value):
    """Round an exact rational to a whole penny, ties away from zero."""
    if type(value) is int:
        return value
    if type(value) is not Fraction:
        raise ValueError('A posting requires int or Fraction, never a float or Boolean')
    sign = -1 if value < 0 else 1
    numerator = abs(value.numerator)
    return sign * ((2 * numerator + value.denominator) // (2 * value.denominator))


def capped_tier(cash, remaining_lp_threshold, gp_bp):
    """Find the largest whole-penny cash endpoint by monotone binary search."""
    _integer(cash, 'tier cash'); _integer(remaining_lp_threshold, 'remaining LP threshold')
    _integer(gp_bp, 'GP basis points')
    if gp_bp >= 10000:
        raise ValueError('A capped tier needs a strictly positive LP share')
    if not cash or not remaining_lp_threshold:
        return (0, 0, 0)
    lp_bp = 10000 - gp_bp
    low, high = 0, cash
    while low < high:
        candidate = (low + high + 1) // 2
        if round_pence(Fraction(candidate * lp_bp, 10000)) <= remaining_lp_threshold:
            low = candidate
        else:
            high = candidate - 1
    lp = round_pence(Fraction(low * lp_bp, 10000))
    if lp > remaining_lp_threshold or (low < cash and
            round_pence(Fraction((low + 1) * lp_bp, 10000)) <= remaining_lp_threshold):
        raise ArithmeticError('The independently searched tier endpoint is invalid')
    return low, lp, low - lp


def calculate_period(fund, period, opening, *, historical=False):
    """Post one period from exogenous cash and seven independently carried balances."""
    state_fields = ('cash', 'unreturned_capital', 'unpaid_preference', 'cumulative_lp_paid_in',
                    'cumulative_lp_distributions', 'cumulative_lp_profit', 'cumulative_gp_profit')
    if set(opening) != set(state_fields):
        raise ValueError('The opening state must contain exactly seven balance fields')
    for key in state_fields:
        _integer(opening[key], key)
    cash_fields = ('lp_call', 'asset_investment', 'operating_receipts', 'realization_receipts',
                   'management_fee', 'operating_cost', 'reserve')
    for key in cash_fields:
        _integer(period[key + '_pence'], key)
    year = _integer(period['year'], 'year'); start = date(year, 1, 1); end = date(year + 1, 1, 1)
    call_date = date.fromisoformat(period['call_date'])
    if not start <= call_date < end:
        raise ValueError('The capital call date must lie in its stated calendar year')
    if type(historical) is not bool or type(fund['compound_unpaid_preference']) is not bool:
        raise ValueError('Historical and compound flags must be Boolean')
    lp1_bp = _integer(fund['lp1_share_bp'], 'LP1 participation')
    carry = _integer(fund['base_gp_carry_bp'], 'base GP carry')
    rate = 0 if historical else _integer(fund['preferred_rate_bp'], 'preference basis points')
    if not 0 < lp1_bp < 10000 or not 0 <= carry < 10000:
        raise ValueError('Invalid LP participation or base carry')
    promote = fund['promote_gp_bp']; multiple = fund['lp_distribution_multiple_threshold_bp']
    if (type(promote) is not list or len(promote) != 3 or
            any(type(v) is not int or not 0 <= v < 10000 for v in promote) or
            type(multiple) is not list or len(multiple) != 2 or
            any(type(v) is not int or v <= 0 for v in multiple) or multiple != sorted(set(multiple))):
        raise ValueError('Three promote percentages and two increasing thresholds are required')

    result = {key: period[key + '_pence'] for key in cash_fields}
    result.update(opening_cash=opening['cash'], opening_unreturned_capital=opening['unreturned_capital'],
                  opening_unpaid_preference=opening['unpaid_preference'])
    result['cash_before_distribution'] = (opening['cash'] + result['lp_call'] + result['operating_receipts'] +
        result['realization_receipts'] - result['asset_investment'] - result['management_fee'] - result['operating_cost'])
    if result['cash_before_distribution'] < 0:
        raise ValueError('Negative fund cash: do not invent debt or replacement receipts')
    result['available_cash'] = max(0, result['cash_before_distribution'] - result['reserve'])
    result['cumulative_lp_paid_in'] = opening['cumulative_lp_paid_in'] + result['lp_call']
    if not result['cumulative_lp_paid_in']:
        raise ValueError('The LP distribution multiple requires positive contributed capital')
    full_days = (end - start).days; called_days = (end - call_date).days
    pence_days = opening['unreturned_capital'] * full_days + result['lp_call'] * called_days
    if fund['compound_unpaid_preference']:
        pence_days += opening['unpaid_preference'] * full_days
    result['preference_accrual'] = round_pence(Fraction(rate * pence_days, 3650000))
    result['capital_entitlement'] = opening['unreturned_capital'] + result['lp_call']
    result['preference_entitlement'] = opening['unpaid_preference'] + result['preference_accrual']
    result['capital_paid'] = min(result['capital_entitlement'], result['available_cash'])
    result['after_capital_cash'] = result['available_cash'] - result['capital_paid']
    result['preference_paid'] = min(result['preference_entitlement'], result['after_capital_cash'])
    result['after_preference_cash'] = result['after_capital_cash'] - result['preference_paid']
    result['lp_profit_before_catchup'] = opening['cumulative_lp_profit'] + result['preference_paid']
    result['gp_profit_before_catchup'] = opening['cumulative_gp_profit']
    target = round_pence(Fraction(result['lp_profit_before_catchup'] * carry, 10000 - carry))
    result['catchup_entitlement'] = max(0, target - opening['cumulative_gp_profit'])
    result['catchup_paid'] = min(result['after_preference_cash'], result['catchup_entitlement'])
    result['after_catchup_cash'] = result['after_preference_cash'] - result['catchup_paid']

    thresholds = [round_pence(Fraction(result['cumulative_lp_paid_in'] * bp, 10000)) for bp in multiple]
    paid_to_lp = opening['cumulative_lp_distributions'] + result['capital_paid'] + result['preference_paid']
    remaining = result['after_catchup_cash']; tier_search_cash_limits = []
    for index in range(3):
        tier_search_cash_limits.append(remaining)
        if index < 2:
            total, lp, gp = capped_tier(remaining, max(0, thresholds[index] - paid_to_lp), promote[index])
        else:
            total = remaining; lp = round_pence(Fraction(total * (10000 - promote[index]), 10000)); gp = total - lp
        prefix = 'tier' + str(index + 1)
        result[prefix + '_cash'] = total; result[prefix + '_lp'] = lp; result[prefix + '_gp'] = gp
        remaining -= total; paid_to_lp += lp
    if remaining:
        raise ArithmeticError('The uncapped final tier must distribute the entire remaining cash')
    result['lp_promote_cash'] = sum(result[f'tier{i}_lp'] for i in (1, 2, 3))
    result['gp_promote_cash'] = sum(result[f'tier{i}_gp'] for i in (1, 2, 3))
    result['lp_total_distribution'] = result['capital_paid'] + result['preference_paid'] + result['lp_promote_cash']
    result['gp_total_distribution'] = result['catchup_paid'] + result['gp_promote_cash']
    result['fund_total_distribution'] = result['lp_total_distribution'] + result['gp_total_distribution']
    result['closing_cash'] = result['cash_before_distribution'] - result['fund_total_distribution']
    result['closing_unreturned_capital'] = result['capital_entitlement'] - result['capital_paid']
    result['closing_unpaid_preference'] = result['preference_entitlement'] - result['preference_paid']
    result['cumulative_lp_distributions'] = paid_to_lp
    result['cumulative_lp_profit'] = result['lp_profit_before_catchup'] + result['lp_promote_cash']
    result['cumulative_gp_profit'] = opening['cumulative_gp_profit'] + result['gp_total_distribution']
    result['lp1_call'] = round_pence(Fraction(result['lp_call'] * lp1_bp, 10000))
    result['lp2_call'] = result['lp_call'] - result['lp1_call']
    result['lp1_distribution'] = round_pence(Fraction(result['lp_total_distribution'] * lp1_bp, 10000))
    result['lp2_distribution'] = result['lp_total_distribution'] - result['lp1_distribution']
    result['lp1_net_cashflow'] = result['lp1_distribution'] - result['lp1_call']
    result['lp2_net_cashflow'] = result['lp2_distribution'] - result['lp2_call']
    result['gp_net_cashflow'] = result['gp_total_distribution']
    result['fund_cash_residual'] = result['cash_before_distribution'] - result['closing_cash'] - result['lp_total_distribution'] - result['gp_total_distribution']
    result['recipient_cash_residual'] = result['fund_total_distribution'] - result['lp1_distribution'] - result['lp2_distribution'] - result['gp_net_cashflow']
    result['principal_residual'] = opening['unreturned_capital'] + result['lp_call'] - result['capital_paid'] - result['closing_unreturned_capital']
    result['preference_residual'] = opening['unpaid_preference'] + result['preference_accrual'] - result['preference_paid'] - result['closing_unpaid_preference']
    if set(result) != set(schema.ROW_FIELDS) or any(type(result[k]) is not int for k in schema.ROW_FIELDS):
        raise ArithmeticError('All 56 monetary fields must be present as exact integer pence')
    if any(result[k] for k in schema.INVARIANT_FIELDS):
        raise ArithmeticError('A cash, recipient, principal or preference conservation identity failed')
    if result['closing_cash'] != min(result['reserve'], result['cash_before_distribution']):
        raise ArithmeticError('Closing retained cash is not the affordable required reserve')
    result['lp_distribution_multiple'] = {'numerator':result['cumulative_lp_distributions'], 'denominator':result['cumulative_lp_paid_in']}
    result['capital_and_pref_shortfall'] = bool(result['closing_unreturned_capital'] or result['closing_unpaid_preference'])
    next_state = {'cash':result['closing_cash'], 'unreturned_capital':result['closing_unreturned_capital'],
        'unpaid_preference':result['closing_unpaid_preference'], 'cumulative_lp_paid_in':result['cumulative_lp_paid_in'],
        'cumulative_lp_distributions':result['cumulative_lp_distributions'], 'cumulative_lp_profit':result['cumulative_lp_profit'],
        'cumulative_gp_profit':result['cumulative_gp_profit']}
    intermediate = [pence_days, rate * pence_days, opening['unreturned_capital'] * full_days,
        result['lp_call'] * called_days, opening['unpaid_preference'] * full_days,
        result['lp_profit_before_catchup'] * carry, *(result['cumulative_lp_paid_in'] * bp for bp in multiple),
        result['lp_call'] * lp1_bp, result['lp_total_distribution'] * lp1_bp,
        *(result[f'tier{i}_cash'] * (10000 - promote[i - 1]) for i in (1, 2, 3)), 2 * result['after_catchup_cash'] + 1]
    rounding_bounds = [(rate * pence_days, 3650000), (result['lp_profit_before_catchup'] * carry, 10000 - carry),
        *((result['cumulative_lp_paid_in'] * bp, 10000) for bp in multiple),
        (result['lp_call'] * lp1_bp, 10000), (result['lp_total_distribution'] * lp1_bp, 10000),
        *(((limit + 1) * (10000 - promote[i]), 10000) for i, limit in enumerate(tier_search_cash_limits))]
    # Raw numerators bound the reduced Fractions too. Include every doubling/addition
    # in nearest-penny rounding, and the binary-search next-penny endpoint check.
    intermediate.extend(max(2 * abs(numerator) + denominator, 2 * denominator) for numerator, denominator in rounding_bounds)
    proof = {'days_in_period':full_days, 'called_capital_days':called_days,
        'max_integer_intermediate_abs':max(abs(v) for v in intermediate), 'tier_thresholds_pence':thresholds}
    return result, next_state, proof


def solve(public):
    """Run only when the caller has authorization for this frozen raw specification."""
    schema.validate_spec(public)
    rows = {}; row_order = []; period_proofs = {}; aggregate_order = []
    aggregates = {}
    for scenario in public['scenario_ids']:
        for year in public['years']:
            key = f'{scenario}/{year}'; aggregate_order.append(key)
            aggregates[key] = {field:0 for field in schema.AGGREGATE_FIELDS}
    for fund in public['funds']:
        for scenario in fund['scenarios']:
            state = {key:fund['opening_' + key + '_pence'] for key in
                ('cash','unreturned_capital','unpaid_preference','cumulative_lp_paid_in',
                 'cumulative_lp_distributions','cumulative_lp_profit','cumulative_gp_profit')}
            for period in scenario['periods']:
                key = f"{fund['id']}/{scenario['id']}/{period['year']}"; row_order.append(key)
                row, state, period_proofs[key] = calculate_period(fund, period, state, historical=period['year'] in public['historical_years'])
                rows[key] = row; group = aggregates[f"{scenario['id']}/{period['year']}"]
                for field in schema.AGGREGATE_FIELDS:
                    group[field] += row[field]
    amount_count = len(rows) * len(schema.ROW_FIELDS)
    max_posted = max([abs(row[f]) for row in rows.values() for f in schema.ROW_FIELDS] +
                     [abs(row[f]) for row in aggregates.values() for f in schema.AGGREGATE_FIELDS], default=0)
    max_intermediate = max((p['max_integer_intermediate_abs'] for p in period_proofs.values()), default=0)
    return {'kind':'hypothetical_multi_fund_waterfall_independent_values','version':1,'implementation':'B',
        'specification_sha256':schema.canonical_sha256(public),'row_order':row_order,'rows':rows,
        'aggregate_order':aggregate_order,'aggregates':aggregates,
        'proof':{'kind':'independent_integer_fraction_waterfall_posting_proof','version':1,
            'posting_method':'exact_integer_Fraction_half_away_from_zero', 'tier_endpoint_method':'monotone_whole_penny_binary_search',
            'row_count':len(rows),'aggregate_count':len(aggregates),'row_monetary_value_count':amount_count,
            'aggregate_monetary_value_count':len(aggregates) * len(schema.AGGREGATE_FIELDS),
            'all_four_conservation_residuals_zero':True,'max_posted_abs_pence':max_posted,
            'max_declared_integer_intermediate_abs':max_intermediate,
            'all_posted_and_declared_integer_intermediates_below_2_to_53':max(max_posted,max_intermediate) < 2**53,
            'periods':period_proofs,'new_solver_LO_model_Harbor_calls':0,'qualified':False}}
