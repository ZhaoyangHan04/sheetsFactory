"""Independent Decimal LP/GP state machine. No workbook or financial-library imports."""
from copy import deepcopy
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext

D = Decimal
ZERO = D(0)
CENT = D('.01')
POLICY_KEYS = {'version', 'years', 'opening_date', 'opening_capital', 'lp_capital_fraction',
               'preference_rate', 'initial_carry_rate', 'flipped_carry_rate', 'lp_xirr_hurdle'}


def _decimal(value):
    result = D(str(value))
    if not result.is_finite():
        raise ValueError('Waterfall inputs must be finite')
    return result


def money(value):
    return _decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _posted(value):
    result = _decimal(value)
    if result != money(result) or result < 0:
        raise ValueError('Waterfall cash and capital inputs must be nonnegative posted cents')
    return result


def _policy(policy):
    if set(policy) != POLICY_KEYS:
        raise ValueError('Waterfall policy has missing or unknown fields')
    if policy['version'] != 1 or policy['years'] != list(range(2024, 2044)):
        raise ValueError('Waterfall requires version 1 and FY2024–2043')
    if policy['opening_date'] != '2023-04-01':
        raise ValueError('Opening capital must retain its actual 1 April 2023 date')
    rates = {k: _decimal(policy[k]) for k in (
        'lp_capital_fraction', 'preference_rate', 'initial_carry_rate',
        'flipped_carry_rate', 'lp_xirr_hurdle')}
    if not ZERO < rates['lp_capital_fraction'] < 1:
        raise ValueError('Both partners must have positive capital participation')
    if not ZERO <= rates['preference_rate'] <= 1 or not ZERO <= rates['lp_xirr_hurdle'] <= 1:
        raise ValueError('Preference and hurdle must be between zero and one')
    if not ZERO <= rates['initial_carry_rate'] <= rates['flipped_carry_rate'] < 1:
        raise ValueError('Carry rates must be ordered and below one')
    if _posted(policy['opening_capital']) <= 0:
        raise ValueError('Opening paid-in capital must be positive')
    return rates


def _flows(cashflows):
    combined = {}
    for row in cashflows:
        when = date.fromisoformat(str(row['date']))
        combined[when] = combined.get(when, ZERO) + _decimal(row['amount'])
    return [(when, amount) for when, amount in sorted(combined.items()) if amount]


def _qualifying_flows(cashflows):
    flows = _flows(cashflows)
    signs = [1 if value > 0 else -1 for _, value in flows]
    changes = sum(a != b for a, b in zip(signs, signs[1:]))
    eligible = bool(signs and signs[0] == -1 and signs[-1] == 1 and changes == 1)
    return flows, changes, eligible


def xnpv(rate, cashflows):
    """Actual/365 dated NPV, with no rate or intermediate-product rounding."""
    with localcontext() as context:
        context.prec = 60
        rate = _decimal(rate)
        if rate <= -1:
            raise ValueError('XNPV rate must exceed -100%')
        flows = _flows(cashflows)
        if not flows:
            return ZERO
        first = flows[0][0]
        return sum((amount / ((1 + rate) ** (D((when-first).days) / D(365)))
                    for when, amount in flows), ZERO)


def xirr(cashflows):
    """Unique annual root for a dated sequence with one negative-to-positive change.

    At a date between the last negative and first positive flow, multiply NPV by
    its positive discount factor. Every negative term then weakly decreases with
    rate and every positive term strictly decreases. Opposite endpoint signs
    prove existence and uniqueness, independent of any spreadsheet IRR guess.
    Multiple-sign-change streams are deliberately not assigned an arbitrary root.
    """
    flows, _, eligible = _qualifying_flows(cashflows)
    if not eligible:
        return None
    with localcontext() as context:
        context.prec = 60
        rows = [{'date': when.isoformat(), 'amount': amount} for when, amount in flows]
        low = D('-.9999999999999999999999999999999999999999')
        high = D(1)
        while xnpv(high, rows) > 0:
            high = high * 2 + 1
            if high > D('1e30'):
                raise ValueError('Unique XIRR exceeds supported explicit rate range')
        if xnpv(low, rows) < 0:
            raise ValueError('Unique XIRR lies below supported lower rate bound')
        for _ in range(220):
            middle = (low + high) / 2
            if xnpv(middle, rows) > 0:
                low = middle
            else:
                high = middle
        return (low + high) / 2


def initial_state(policy):
    rates = _policy(policy)
    opening = _posted(policy['opening_capital'])
    lp = money(opening * rates['lp_capital_fraction'])
    gp = opening - lp
    return {'next_year': 2024, 'lp_unreturned': lp, 'gp_unreturned': gp,
            'unpaid_preference': ZERO, 'lp_profit': ZERO, 'gp_profit': ZERO,
            'lp_contributed': lp, 'gp_contributed': gp, 'lp_capital_returned': ZERO,
            'gp_capital_returned': ZERO, 'flip_effective_year': None,
            'lp_cashflows': [{'date': policy['opening_date'], 'amount': -lp}],
            'gp_cashflows': [{'date': policy['opening_date'], 'amount': -gp}]}


def allocate_year(policy, state, year, capital_called, distributable_cash):
    """Allocate one FY without mutating the caller's policy or previous state.

    The caller supplies already-funded additional capital and available cash
    AFTER the parent debt/fee waterfall. This function never creates financing.
    Return accounting entries are debit-positive, and exclude contributed cash
    (already posted by the parent) to prevent double-counting that cash receipt.
    """
    with localcontext() as context:
        context.prec = 60
        return _allocate(policy, state, year, capital_called, distributable_cash)


def _allocate(policy, state, year, capital_called, distributable_cash):
    rates = _policy(policy)
    if not isinstance(year, int) or year != state['next_year'] or year not in policy['years']:
        raise ValueError('Waterfall years must be processed once in calendar order')
    s = deepcopy(state)
    for key in ('lp_unreturned', 'gp_unreturned', 'unpaid_preference', 'lp_profit', 'gp_profit',
                'lp_contributed', 'gp_contributed', 'lp_capital_returned', 'gp_capital_returned'):
        s[key] = _posted(s[key])
    if s['flip_effective_year'] is not None and s['flip_effective_year'] > year:
        raise ValueError('Flip state cannot start beyond the next reporting year')
    called = _posted(capital_called)
    available = _posted(distributable_cash)
    carry = rates['flipped_carry_rate'] if s['flip_effective_year'] is not None else rates['initial_carry_rate']
    r = {'year': year, 'date': f'{year}-03-31', 'capital_called': called,
         'distributable_cash': available, 'carry_rate': carry,
         'lp_capital_open': s['lp_unreturned'], 'gp_capital_open': s['gp_unreturned'],
         'preference_open': s['unpaid_preference']}
    r['lp_contribution'] = money(called * rates['lp_capital_fraction'])
    r['gp_contribution'] = called - r['lp_contribution']
    r['preference_accrual'] = money(s['lp_unreturned'] * rates['preference_rate'])
    lp_capital = s['lp_unreturned'] + r['lp_contribution']
    gp_capital = s['gp_unreturned'] + r['gp_contribution']
    due = s['unpaid_preference'] + r['preference_accrual']
    r['lp_preference'] = min(available, due)
    remaining = available - r['lp_preference']
    roc = min(remaining, lp_capital + gp_capital)
    lp_roc = money(roc * lp_capital / (lp_capital + gp_capital)) if lp_capital + gp_capital else ZERO
    r['lp_return_of_capital'] = min(lp_capital, max(roc-gp_capital, lp_roc))
    r['gp_return_of_capital'] = roc - r['lp_return_of_capital']
    remaining -= roc
    lp_profit = s['lp_profit'] + r['lp_preference']
    gp_profit = s['gp_profit']
    entitlement = max(ZERO, money((carry*(lp_profit+gp_profit)-gp_profit)/(1-carry)))
    r['gp_catchup'] = min(remaining, entitlement)
    remaining -= r['gp_catchup']
    r['gp_residual'] = money(remaining * carry)
    r['lp_residual'] = remaining - r['gp_residual']
    r['lp_distribution'] = r['lp_preference'] + r['lp_return_of_capital'] + r['lp_residual']
    r['gp_distribution'] = r['gp_return_of_capital'] + r['gp_catchup'] + r['gp_residual']
    r['capital_distribution'] = roc
    r['profit_distribution'] = r['lp_preference'] + r['gp_catchup'] + remaining
    r['total_distribution'] = r['lp_distribution'] + r['gp_distribution']
    r['lp_capital_close'] = lp_capital - r['lp_return_of_capital']
    r['gp_capital_close'] = gp_capital - r['gp_return_of_capital']
    r['preference_close'] = due - r['lp_preference']
    r['lp_cumulative_profit'] = lp_profit + r['lp_residual']
    r['gp_cumulative_profit'] = gp_profit + r['gp_catchup'] + r['gp_residual']
    r['lp_net_cashflow'] = r['lp_distribution'] - r['lp_contribution']
    r['gp_net_cashflow'] = r['gp_distribution'] - r['gp_contribution']
    s['lp_cashflows'].append({'date': r['date'], 'amount': r['lp_net_cashflow']})
    s['gp_cashflows'].append({'date': r['date'], 'amount': r['gp_net_cashflow']})
    _, r['lp_sign_changes'], eligible = _qualifying_flows(s['lp_cashflows'])
    r['lp_xirr_eligible'] = eligible
    nonzero = _flows(s['lp_cashflows'])
    r['lp_last_nonzero_sign'] = 1 if nonzero[-1][1] > 0 else -1
    raw_xirr = xirr(s['lp_cashflows']) if eligible else None
    r['lp_xirr'] = raw_xirr.quantize(D('.000000000001'), rounding=ROUND_HALF_UP) if raw_xirr is not None else None
    r['hurdle_xnpv'] = xnpv(rates['lp_xirr_hurdle'], s['lp_cashflows'])
    r['flip_earned'] = bool(s['flip_effective_year'] is None and eligible
        and r['lp_capital_close'] == 0 and r['gp_capital_close'] == 0 and r['hurdle_xnpv'] >= 0)
    if r['flip_earned']:
        s['flip_effective_year'] = year + 1
    r['flip_effective_year'] = s['flip_effective_year']
    r['next_carry_rate'] = rates['flipped_carry_rate'] if s['flip_effective_year'] is not None else carry
    s.update(next_year=year+1, lp_unreturned=r['lp_capital_close'], gp_unreturned=r['gp_capital_close'],
             unpaid_preference=r['preference_close'], lp_profit=r['lp_cumulative_profit'],
             gp_profit=r['gp_cumulative_profit'], lp_contributed=s['lp_contributed']+r['lp_contribution'],
             gp_contributed=s['gp_contributed']+r['gp_contribution'],
             lp_capital_returned=s['lp_capital_returned']+r['lp_return_of_capital'],
             gp_capital_returned=s['gp_capital_returned']+r['gp_return_of_capital'])
    journal = []
    if roc:
        journal.append({'label': 'Return partner paid-in capital',
                        'debit_positive_entries': {'paid_in_capital': roc, 'cash': -roc}})
    if r['profit_distribution']:
        journal.append({'label': 'Distribute partner profit, not an expense',
                        'debit_positive_entries': {'retained_earnings': r['profit_distribution'],
                                                  'cash': -r['profit_distribution']}})
    checks = {
        'cash_allocated_exactly': r['total_distribution'] == available,
        'capital_profit_split': roc+r['profit_distribution'] == available,
        'contributions_split': r['lp_contribution']+r['gp_contribution'] == called,
        'lp_capital_rollforward': s['lp_contributed']-s['lp_capital_returned'] == s['lp_unreturned'],
        'gp_capital_rollforward': s['gp_contributed']-s['gp_capital_returned'] == s['gp_unreturned'],
        'preference_rollforward': r['preference_open']+r['preference_accrual']-r['lp_preference'] == s['unpaid_preference'],
        'nonnegative_closing_claims': min(s['lp_unreturned'], s['gp_unreturned'], s['unpaid_preference']) >= 0,
        'journal_balanced': all(sum(e['debit_positive_entries'].values(), ZERO) == 0 for e in journal),
    }
    if not all(checks.values()):
        raise ValueError('Waterfall accounting invariant failed')
    return {'state': s, 'annual': r, 'journal': journal, 'checks': checks}


def observed_regimes(annual):
    regimes = {name: [] for name in ('preference_paid', 'preference_carry', 'return_of_capital',
        'gp_catchup', 'residual', 'carry_flip_earned', 'flipped_carry_used', 'capital_after_flip')}
    for r in annual:
        predicates = {'preference_paid': r['lp_preference'] > 0,
          'preference_carry': r['preference_close'] > 0,
          'return_of_capital': r['capital_distribution'] > 0,
          'gp_catchup': r['gp_catchup'] > 0,
          'residual': r['lp_residual']+r['gp_residual'] > 0,
          'carry_flip_earned': r['flip_earned'],
          'flipped_carry_used': r['flip_effective_year'] is not None and r['year'] >= r['flip_effective_year'],
          'capital_after_flip': r['flip_effective_year'] is not None
              and r['year'] >= r['flip_effective_year'] and r['capital_called'] > 0}
        for key, observed in predicates.items():
            if observed: regimes[key].append(r['year'])
    return regimes


def simulate(policy, annual_cash, required_regimes=()):
    """Replay explicit funded annual inputs. Missing regimes remain a rejection."""
    state = initial_state(policy)
    annual = []
    journal = []
    rows = list(annual_cash)
    if len(rows) != 20 or [r['year'] for r in rows] != policy['years']:
        raise ValueError('Waterfall replay requires all twenty explicit fiscal-year inputs')
    for source in rows:
        result = allocate_year(policy, state, source['year'], source['capital_called'], source['distributable_cash'])
        state = result['state']; r = result['annual']; annual.append(r)
        journal.extend(dict(e, year=r['year']) for e in result['journal'])
    regimes=observed_regimes(annual)
    if any(key not in regimes for key in required_regimes):
        raise ValueError('Unknown required waterfall regime')
    missing = [key for key in required_regimes if not regimes[key]]
    return {'annual': annual, 'state': state, 'journal': journal,
            'observed_regimes': regimes, 'missing_required_regimes': missing,
            'selected': not missing, 'qualified': False, 'task_count': 0}
