"""Exact, optimistic financial bounds; no optimiser or source admission.

For feasible paths, discounting cash conservation gives a minimum-cash
carrying cost. Immediate signed tax refunds dominate FIFO/deferred/expired
loss use. Replacing debt by uncapped project collateral and retaining only
positive discounted funding spreads is optimistic. All candidate postings
are already exact integer pence. Remaining posting error is bounded by

  .5*sum(d) + .5*(1-tax)*sum(d[1:]) + .5*sum(positive_spreads) + .5.

The terms are tax, interest, aggregate collateral and final NPV rounding.
With twenty discounts in (0,1], nonnegative rates, tax in [0,1] and decreasing
discounts, this is at most 20.5p. The declared 100p cushion therefore includes
final NPV rounding before any rational upper bound is floored. Project
ceilings are unnecessary: all arithmetic below is Fraction/integer exact.
"""
from dataclasses import dataclass
from fractions import Fraction
import hashlib
from pathlib import Path
import re

from . import spec as schema

METHOD = 'sparse_capital_exact_optimistic_cash_tax_collateral_bounds_v1'
CUSHION_PENCE = 100


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def rational(value):
    """Accept exact numbers or reduced canonical string rationals, never float."""
    if type(value) is int:
        return Fraction(value)
    if type(value) is Fraction:
        return value
    _require(isinstance(value, dict) and set(value) == {'numerator', 'denominator'},
             'An exact integer, Fraction or canonical rational is required')
    n, d = value['numerator'], value['denominator']
    _require(type(n) is str and re.fullmatch(r'0|-?[1-9][0-9]*', n) is not None
             and type(d) is str and re.fullmatch(r'[1-9][0-9]*', d) is not None,
             'Rational numerator and positive denominator must be canonical strings')
    result = Fraction(int(n), int(d))
    _require(str(result.numerator) == n and str(result.denominator) == d,
             'A rational must be reduced with a positive denominator')
    return result


def encode_rational(value):
    value = rational(value)
    return {'numerator': str(value.numerator), 'denominator': str(value.denominator)}


def _round(numerator, denominator):
    _require(type(numerator) is int and type(denominator) is int and denominator > 0,
             'Posting requires literal integers and a positive denominator')
    return ((numerator + denominator // 2) // denominator if numerator >= 0
            else -((-numerator + denominator // 2) // denominator))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass(frozen=True)
class CandidateYear:
    year: int
    capex: int
    revenue: int
    opex: int
    depreciation: int
    sale_proceeds: int
    sale_carrying: int
    sale_gain: int
    closing_book_value: int
    certified_nav: int

    @property
    def gross_cash(self):
        return self.revenue - self.opex + self.sale_proceeds - self.capex

    @property
    def profit_before_interest(self):
        return self.revenue - self.opex - self.depreciation + self.sale_gain


@dataclass(frozen=True)
class NecessaryCut:
    id: str
    scenario: str
    year: int
    kind: str
    weights: tuple
    capacity: Fraction


@dataclass(frozen=True)
class BoundModel:
    project_ids: tuple
    scenario_ids: tuple
    years: tuple
    candidates: tuple
    constants: tuple
    coefficients: tuple
    cuts: tuple
    rounding_envelopes: tuple
    spec_sha256: str
    math_sha256: str
    schema_sha256: str

    def binding(self):
        return {'method': METHOD, 'public_spec_sha256': self.spec_sha256,
                'math_recipe_sha256': self.math_sha256, 'schema_recipe_sha256': self.schema_sha256,
                'project_count': len(self.project_ids), 'project_order': list(self.project_ids),
                'scenario_order': list(self.scenario_ids), 'years': list(self.years),
                'combinatorial_plan_count': str(1 << len(self.project_ids)),
                'searched_plan_count': '0', 'cushion_pence': str(CUSHION_PENCE),
                'rounding_envelopes': [encode_rational(x) for x in self.rounding_envelopes],
                'optimisation_performed': False, 'feasible_plan_or_optimum_certified': False}


def _candidate(public, scenario, project):
    scale = schema.SCALE
    book = 0
    rows = []
    for year in schema.YEARS:
        key = str(year)
        cost = project['acquisition_cost_pence'] if year == project['commission_year'] else 0
        book += cost
        revenue = opex = depreciation = proceeds = carrying = 0
        if project['commission_year'] < year <= project['sale_year']:
            revenue = _round(project['annual_revenue_pence'][key] * scenario['revenue_factors_p12'][key], scale)
            opex = _round(project['annual_opex_pence'][key] * scenario['opex_factors_p12'][key], scale)
            age = year - project['commission_year']
            if age <= project['depreciation_years']:
                depreciation = (book if age == project['depreciation_years'] else
                                min(book, max(0, _round(project['acquisition_cost_pence'], project['depreciation_years']))))
            book -= depreciation
            if year == project['sale_year']:
                proceeds = _round(project['sale_proceeds_pence'] * scenario['sale_factors_p12'][key], scale)
                carrying, book = book, 0
        nav = _round(book * scenario['nav_factors_p12'][key], scale)
        rows.append(CandidateYear(year, cost, revenue, opex, depreciation, proceeds,
                                  carrying, proceeds - carrying, book, nav))
    return tuple(rows)


def prepare_bounds(value):
    """Build only public candidate flows, safe bounds and necessary conditions."""
    public = schema.load_spec(value)
    scale, years = schema.SCALE, schema.YEARS
    discount = tuple(Fraction(public['discount_factors_p12'][str(y)], scale) for y in years)
    tax = Fraction(public['tax_rate_p12'], scale)
    _require(0 <= tax <= 1 and all(0 < d <= 1 for d in discount)
             and all(a >= b for a, b in zip(discount, discount[1:])),
             'The exact tax/discount proof prerequisites are not satisfied')
    constants, coefficients, candidates, cuts, envelopes = [], [], [], [], []
    for scenario in public['scenarios']:
        rates = tuple(Fraction(scenario['bank_rates_p12'][str(y)], scale) for y in years)
        haircuts = tuple(Fraction(scenario['haircuts_p12'][str(y)], scale) for y in years)
        _require(all(0 <= x <= 1 for x in rates + haircuts),
                 'Nonnegative bounded bank rates and haircuts are proof prerequisites')
        projects = tuple(_candidate(public, scenario, p) for p in public['projects'])
        candidates.append(projects)
        spread = tuple(max(Fraction(0), discount[t] - discount[t + 1]
                           - (1 - tax) * rates[t + 1] * discount[t + 1]) for t in range(1, len(years) - 1))
        envelope = (sum(discount) / 2 + (1 - tax) * sum(discount[1:]) / 2
                    + sum(spread) / 2 + Fraction(1, 2))
        _require(envelope <= Fraction(41, 2) < CUSHION_PENCE,
                 'The fixed cushion does not cover the proved posting envelope')
        envelopes.append(envelope)
        constants.append(-public['opening_cash_pence'] * (1 - discount[0])
                         - public['minimum_cash_pence'] * (discount[0] - discount[-1]) + CUSHION_PENCE)
        coeff = []
        for flow in projects:
            value = sum(discount[t] * (r.gross_cash - tax * r.profit_before_interest)
                        for t, r in enumerate(flow))
            value += sum(spread[t - 1] * flow[t - 1].certified_nav
                         * Fraction(public['advance_rate_p12'], scale) * (1 - haircuts[t])
                         for t in range(1, len(years) - 1))
            coeff.append(value)
        coefficients.append(tuple(coeff))
        cumulative = [0] * len(projects)
        for t, year in enumerate(years):
            last = t == len(years) - 1
            floor = 0 if last else public['minimum_cash_pence']
            facility = 0 if last else public['facility_limit_pence']
            for j, flow in enumerate(projects):
                cumulative[j] += flow[t].gross_cash
            common = public['opening_cash_pence'] + public['lp_commitment_pence'] - floor
            cuts.append(NecessaryCut(scenario['id'] + '.' + str(year) + '.facility', scenario['id'], year,
                                     'facility', tuple(Fraction(-x) for x in cumulative), Fraction(common + facility)))
            collateral = [Fraction(0) if t == 0 or last else
                          Fraction(flow[t - 1].certified_nav * public['advance_rate_p12'], scale)
                          * (1 - haircuts[t]) for flow in projects]
            # Opening collateral and maturity base are exactly zero, with no rounding allowance.
            rounding = Fraction(0) if t == 0 or last else Fraction(1, 2)
            cuts.append(NecessaryCut(scenario['id'] + '.' + str(year) + '.collateral', scenario['id'], year,
                                     'collateral', tuple(-c - nav for c, nav in zip(cumulative, collateral)),
                                     Fraction(common) + rounding))
    return BoundModel(schema.project_ids(len(public['projects'])), schema.SCENARIO_IDS, years,
                      tuple(candidates), tuple(constants), tuple(coefficients), tuple(cuts), tuple(envelopes),
                      schema.canonical_sha(public), _sha(__file__), _sha(schema.__file__))


def _fixed(model, fixed_decisions):
    _require(type(model) is BoundModel, 'A freshly prepared exact bound model is required')
    fixed = {} if fixed_decisions is None else fixed_decisions
    _require(isinstance(fixed, dict) and set(fixed) <= set(model.project_ids)
             and all(type(x) is int and x in (0, 1) for x in fixed.values()),
             'Fixed decisions must be known project IDs and literal binary integers')
    selected = {i: fixed[p] for i, p in enumerate(model.project_ids) if p in fixed}
    return selected, tuple(i for i in range(len(model.project_ids)) if i not in selected)


def prefix_binding(model, fixed_decisions=None):
    fixed, free = _fixed(model, fixed_decisions)
    return {'known_mask_hex': '0x' + format(sum(1 << i for i in fixed), '016x'),
            'value_mask_hex': '0x' + format(sum(x << i for i, x in fixed.items()), '016x'),
            'combinatorial_region_count': str(1 << len(free)), 'proof_of_region_coverage': False}


def validate_binding(model, value):
    _require(value == model.binding(), 'The public specification or bound recipe binding changed')
    return True


def _region(model, fixed_decisions):
    fixed, free = _fixed(model, fixed_decisions)
    constants = tuple(c + sum(a[i] * x for i, x in fixed.items())
                      for c, a in zip(model.constants, model.coefficients))
    capacity = tuple(c.capacity - sum(c.weights[i] * x for i, x in fixed.items()) for c in model.cuts)
    return free, constants, capacity


def additive_upper_bound(model, fixed_decisions=None):
    free, constants, _ = _region(model, fixed_decisions)
    return min(c + sum(max(Fraction(0), a[i]) for i in free)
               for c, a in zip(constants, model.coefficients))


def _contradicting_cut(model, free, capacity):
    return next((c.id for c, b in zip(model.cuts, capacity)
                 if sum(min(Fraction(0), c.weights[i]) for i in free) > b), None)


def fractional_knapsack_upper_bound(model, fixed_decisions=None):
    """Relax each necessary cut separately; None means a proved contradiction."""
    free, constants, capacity = _region(model, fixed_decisions)
    if _contradicting_cut(model, free, capacity) is not None:
        return None
    upper = additive_upper_bound(model, fixed_decisions)
    for c, a in zip(constants, model.coefficients):
        for cut, b in zip(model.cuts, capacity):
            # Grant every negative resource weight independently of its objective.
            # This enlarges the region; fixed negative objective terms stay in c.
            room = b - sum(min(Fraction(0), cut.weights[i]) for i in free)
            value = c + sum(max(Fraction(0), a[i]) for i in free if cut.weights[i] <= 0)
            items = sorted(((a[i] / cut.weights[i], cut.weights[i], a[i]) for i in free
                            if cut.weights[i] > 0 and a[i] > 0), reverse=True)
            for _, weight, benefit in items:
                use = min(Fraction(1), room / weight)
                value += benefit * use
                room -= weight * use
                if room == 0:
                    break
            upper = min(upper, value)
    return upper


def _multipliers(model, values):
    _require(isinstance(values, dict) and set(values) <= {c.id for c in model.cuts},
             'A multiplier refers to an unknown necessary cut')
    result = {key: rational(value) for key, value in values.items()}
    _require(all(x >= 0 for x in result.values()), 'Cut multipliers must be nonnegative')
    return tuple(result.get(c.id, Fraction(0)) for c in model.cuts)


def dual_upper_bound(model, scenario_weights, cut_multipliers, fixed_decisions=None):
    """Check exact dual coefficients; never trust a floating optimiser claim."""
    _require(isinstance(scenario_weights, dict) and set(scenario_weights) == set(model.scenario_ids),
             'All scenario weights must be explicit')
    weights = tuple(rational(scenario_weights[s]) for s in model.scenario_ids)
    _require(all(x >= 0 for x in weights) and sum(weights) == 1,
             'Scenario weights must be nonnegative and sum exactly to one')
    multipliers = _multipliers(model, cut_multipliers)
    free, constants, capacity = _region(model, fixed_decisions)
    value = sum(w * c for w, c in zip(weights, constants)) + sum(m * b for m, b in zip(multipliers, capacity))
    for i in free:
        adjusted = sum(w * a[i] for w, a in zip(weights, model.coefficients))
        adjusted -= sum(m * c.weights[i] for m, c in zip(multipliers, model.cuts))
        value += max(Fraction(0), adjusted)
    return value


def verify_dual_bound(model, scenario_weights, cut_multipliers, claimed_upper, fixed_decisions=None):
    actual = dual_upper_bound(model, scenario_weights, cut_multipliers, fixed_decisions)
    return {'passed': rational(claimed_upper) == actual, 'rational_upper': encode_rational(actual),
            'integer_upper': str(actual.numerator // actual.denominator),
            'binding': model.binding(), 'region': prefix_binding(model, fixed_decisions)}


def verify_infeasibility_witness(model, cut_multipliers, fixed_decisions=None):
    multipliers = _multipliers(model, cut_multipliers)
    free, _, capacity = _region(model, fixed_decisions)
    right = sum(m * b for m, b in zip(multipliers, capacity))
    lower = sum(min(Fraction(0), sum(m * c.weights[i] for m, c in zip(multipliers, model.cuts))) for i in free)
    return {'passed': right < lower, 'weighted_capacity': encode_rational(right),
            'minimum_possible_weighted_left': encode_rational(lower),
            'binding': model.binding(), 'region': prefix_binding(model, fixed_decisions)}


def evaluate_bounds(model, fixed_decisions=None):
    free, _, capacity = _region(model, fixed_decisions)
    additive = additive_upper_bound(model, fixed_decisions)
    upper = fractional_knapsack_upper_bound(model, fixed_decisions)
    return {'binding': model.binding(), 'region': prefix_binding(model, fixed_decisions),
            'additive_upper': encode_rational(additive),
            'fractional_knapsack_upper': None if upper is None else encode_rational(upper),
            'integer_upper': None if upper is None else str(upper.numerator // upper.denominator),
            'necessary_conditions_infeasible': upper is None,
            'contradicting_cut': _contradicting_cut(model, free, capacity),
            'actual_feasibility_or_optimum_certified': False}
