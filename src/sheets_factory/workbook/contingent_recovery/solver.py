"""Independent penny-posted tax and finite-grid same-year recovery feedback.

No emitter, workbook, hidden reference, operating model or engine is imported.
The gross-up expression and separate tax/loss-use postings exactly match the
existing regulatory journal. Keeping this scalar expression here also prevents
a circular import when that journal calls solve_year.
"""
from decimal import Decimal, ROUND_HALF_UP, localcontext
from functools import reduce
from fractions import Fraction
from math import gcd

from .contract import decimal, posted, validate_contracts

D = Decimal
ZERO, PENNY = D(0), D('.01')


class ContingentRecoveryError(ValueError):
    def __init__(self, message, proof=None):
        super().__init__(message)
        self.proof = proof or {}


class MonotonicityError(ContingentRecoveryError):
    pass


class NonUniqueFixedPointError(ContingentRecoveryError):
    pass


class ConvergenceError(ContingentRecoveryError):
    pass


def money(value):
    return D(value).quantize(PENNY, rounding=ROUND_HALF_UP)


def gross_up_posted(base, available, cap, rate):
    """Exact regulatory policy: solve continuous use, then post tax/use separately."""
    if base <= 0:
        return ZERO, ZERO, money(-base)
    continuous_use = min(available, cap * base / (1 - rate * (1 - cap)))
    return money(rate * (base - continuous_use) / (1 - rate)), money(continuous_use), ZERO


def _parameters(base_nonvariable_entitlement, tax_before_variable, lossesavailable,
                taxrate, lossusecap, eligiblefrac, contracts):
    contracts = validate_contracts(contracts)
    parameters = {'e0': posted(base_nonvariable_entitlement, 'E0', nonnegative=True),
        'b0': posted(tax_before_variable, 'B0'),
        'available': posted(lossesavailable, 'available old losses', nonnegative=True),
        'rate': decimal(taxrate, 'tax rate'), 'loss_cap': decimal(lossusecap, 'loss utilization cap'),
        'eligibility': decimal(eligiblefrac, 'separately posted variable eligibility fraction'),
        'contracts': contracts}
    if not 0 <= parameters['rate'] < 1 or not 0 <= parameters['loss_cap'] <= 1 or not 0 < parameters['eligibility'] < 1:
        raise ValueError('Tax rate, loss use cap and variable eligibility fraction are outside their explicit bounds')
    parameters['grid'] = D(reduce(gcd, [int(D(c['rounding_quantum'])) for c in contracts]))
    parameters['maximum'] = sum((D(c['annual_cap']) for c in contracts), ZERO)
    return parameters


def _monotonicity(parameters):
    """A posted bound on every adjacent pair in the ENTIRE finite rent grid.

    The unposted tax function is nondecreasing with global slope at most r/(1-r):
    the loss-limited slope is r/(1-r), the utilization-limited slope is smaller,
    and the nonpositive-base branch has slope zero. For a grid step h, posting
    allowance to pennies gives dA >= floor(a*h/penny)*penny. The corresponding
    base decreases by at most h-dA. Posting tax once means its decrease is at
    most ceil([r/(1-r)]*(h-dA)/penny)*penny. These floor/ceiling bounds include
    BOTH posting noises and are not a continuous-contraction uniqueness claim.
    """
    h, eligibility, rate = parameters['grid'], parameters['eligibility'], parameters['rate']
    # Derive the proof bounds with exact integer rational arithmetic. A rounded
    # Decimal quotient must never underestimate a ceiling at a penny boundary.
    allowance_steps = Fraction(eligibility) * Fraction(h) / Fraction(PENNY)
    allowance_lower = D(allowance_steps.numerator // allowance_steps.denominator) * PENNY
    slope_exact = Fraction(rate) / (1 - Fraction(rate))
    drop_steps = slope_exact * Fraction(h - allowance_lower) / Fraction(PENNY)
    tax_drop_upper = D(-(-drop_steps.numerator // drop_steps.denominator)) * PENNY
    slope = rate / (1 - rate)
    margin = allowance_lower - tax_drop_upper
    proof = {'method': 'posted_adjacent_grid_increment_bound', 'grid_quantum': h,
        'allowance_posting_unit': PENNY, 'tax_posting_unit': PENNY,
        'continuous_tax_slope_upper_bound': slope,
        'continuous_tax_slope_exact_ratio': {'numerator': slope_exact.numerator, 'denominator': slope_exact.denominator},
        'allowance_increment_lower_bound': allowance_lower,
        'tax_drop_upper_bound': tax_drop_upper,
        'entitlement_increment_lower_bound': margin,
        'entire_grid_entitlement_strictly_increasing': margin > 0,
        'contract_rounding_and_cap_nondecreasing': True,
        'entire_grid_rent_map_nondecreasing': margin > 0}
    if margin <= 0:
        raise MonotonicityError('Posted allowance growth does not strictly dominate the worst-case posted tax decline', proof)
    return proof


def monotonicity_proof(base_nonvariable_entitlement, tax_before_variable, lossesavailable,
                       taxrate, lossusecap, eligiblefrac, contracts):
    with localcontext() as context:
        context.prec = 50
        return _monotonicity(_parameters(base_nonvariable_entitlement, tax_before_variable,
                                         lossesavailable, taxrate, lossusecap, eligiblefrac, contracts))


def _evaluate(total_rent, parameters):
    total_rent = posted(total_rent, 'trial total variable rent', nonnegative=True)
    if total_rent > parameters['maximum'] or total_rent % parameters['grid']:
        raise ValueError('A trial must lie on the finite contractual total-rent grid')
    allowance = money(parameters['eligibility'] * total_rent)
    base = parameters['b0'] + allowance - total_rent
    tax, loss_used, loss_added = gross_up_posted(base, parameters['available'], parameters['loss_cap'], parameters['rate'])
    entitlement = parameters['e0'] + allowance + tax
    fees = {}
    for contract in parameters['contracts']:
        raw = D(contract['rate']) * max(ZERO, entitlement - D(contract['threshold']))
        quantum = D(contract['rounding_quantum'])
        rounded = (raw / quantum).quantize(D(1), rounding=ROUND_HALF_UP) * quantum
        fee = min(D(contract['annual_cap']), rounded)
        fees[contract['lease_id']] = {'variable_rent': fee, 'raw_before_contract_rounding': raw,
            'rounded_before_cap': rounded, 'cap_binding': rounded >= D(contract['annual_cap']) and contract['active'],
            'active': contract['active']}
    mapped = sum((row['variable_rent'] for row in fees.values()), ZERO)
    if mapped % parameters['grid'] or not ZERO <= mapped <= parameters['maximum']:
        raise ContingentRecoveryError('Contract map escaped its declared finite grid')
    return {'trial_variable_rent_total': total_rent, 'mapped_variable_rent_total': mapped,
        'variable_rents': {identity: row['variable_rent'] for identity, row in fees.items()},
        'contract_details': fees, 'variable_lease_allowance': allowance,
        'taxable_base': base, 'tax': tax, 'loss_used': loss_used, 'loss_added': loss_added,
        'total_recovery_entitlement': entitlement}


def evaluate_total(total_rent, base_nonvariable_entitlement, tax_before_variable, lossesavailable,
                   taxrate, lossusecap, eligiblefrac, contracts):
    """Evaluate F(v), without claiming that v is a fixed point or uniquely solvable."""
    with localcontext() as context:
        context.prec = 50
        parameters = _parameters(base_nonvariable_entitlement, tax_before_variable, lossesavailable,
                                 taxrate, lossusecap, eligiblefrac, contracts)
        return _evaluate(total_rent, parameters)


def solve_year(base_nonvariable_entitlement, tax_before_variable, lossesavailable,
               taxrate, lossusecap, eligiblefrac, contracts, *, max_iterations=128):
    """Accept only one uniquely certified same-year fixed point on the entire grid.

    E0 excludes this year's gross-up tax and variable allowance, while already
    including fixed-lease allowance. B0 is the pre-variable gross-up TAXABLE
    BASE, not a tax amount. For a proposed total rent v, post A(v)=money(a*v)
    separately from fixed-lease allowance, post the existing gross-up policy at
    B0+A(v)-v, and calculate entitlement E0+A(v)+tax. Each explicitly supplied
    contract rounds its rate times max(0, entitlement-threshold) to its £100 or
    £1000 unit BEFORE applying its annual cap. Current variable cash, expense
    and tax deduction equal v; the fixed-lease PV/ROU/liability are unaffected.

    A finite monotone map sends [0,sum(caps)] into itself. Iteration from zero
    increases and iteration from sum(caps) decreases, bounding EVERY fixed
    point. Their equality at a fixed point proves uniqueness across the whole
    contractual grid. Separate endpoint fixed points reject as multiple
    solutions; failure to coalesce within 128 steps also rejects. No continuous
    derivative or contraction argument is used to claim discrete uniqueness.
    """
    if type(max_iterations) is not int or not 1 <= max_iterations <= 128:
        raise ValueError('The explicit computational bound must be one through 128 endpoint iterations')
    with localcontext() as context:
        context.prec = 50
        parameters = _parameters(base_nonvariable_entitlement, tax_before_variable, lossesavailable,
                                 taxrate, lossusecap, eligiblefrac, contracts)
        monotone = _monotonicity(parameters)
        low, high = ZERO, parameters['maximum']
        lower_trace, upper_trace = [low], [high]
        proof = {'method': 'finite_grid_monotone_extremal_iteration', 'monotonicity': monotone,
            'maximum_total_variable_rent': high, 'grid_quantum': parameters['grid'],
            'grid_point_count': int(high / parameters['grid']) + 1,
            'maximum_iterations': max_iterations, 'lower_trace': lower_trace, 'upper_trace': upper_trace,
            'uniqueness_scope': 'entire finite contractual total-rent grid; no continuous uniqueness claim'}
        for iteration in range(1, max_iterations + 1):
            next_low = _evaluate(low, parameters)['mapped_variable_rent_total']
            next_high = _evaluate(high, parameters)['mapped_variable_rent_total']
            if not low <= next_low <= next_high <= high:
                raise ContingentRecoveryError('Endpoint sequences violate the proved finite-grid order', proof)
            lower_trace.append(next_low)
            upper_trace.append(next_high)
            proof.update(iterations=iteration, lower_endpoint=next_low, upper_endpoint=next_high)
            if next_low == next_high:
                result = _evaluate(next_low, parameters)
                if result['mapped_variable_rent_total'] != next_low:
                    raise ContingentRecoveryError('Coalesced endpoints do not reproduce the identical posted fixed point', proof)
                proof.update(unique_on_entire_contractual_grid=True,
                             lower_fixed_point=next_low, upper_fixed_point=next_high, endpoint_coalescence=True)
                result.update(variable_rent_total=next_low, unique_fixed_point=True, proof=proof)
                result.update(variable_lease_cash=next_low, variable_book_expense=next_low,
                              variable_tax_deduction=next_low)
                return result
            if next_low == low and next_high == high:
                proof.update(unique_on_entire_contractual_grid=False,
                             lower_fixed_point=next_low, upper_fixed_point=next_high, endpoint_coalescence=False)
                raise NonUniqueFixedPointError('Distinct lower and upper contractual fixed points; reject this year', proof)
            low, high = next_low, next_high
        proof.update(unique_on_entire_contractual_grid=False, endpoint_coalescence=False)
        raise ConvergenceError('Contract endpoints did not coalesce within the declared iteration bound; reject this year', proof)
