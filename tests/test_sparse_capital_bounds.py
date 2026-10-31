"""Exact bound invariants; only two four-active-bit grids, never 2**40 search."""
import ast
from copy import deepcopy
from fractions import Fraction as F
import itertools
import json
from pathlib import Path

import pytest

from sheets_factory.workbook.capital_allocation_sparse import bounds, ledger, spec


def annual(value):
    return {str(y): value for y in spec.YEARS}


def public(n=40, stress=False):
    projects = []
    for i, pid in enumerate(spec.project_ids(n)):
        commission = (2024, 2025, 2024, 2026)[i] if i < 4 else 2042
        sale = (2029, 2031, 2028, 2032)[i] if i < 4 else 2043
        cost = (90, 70, 50, 60)[i] if i < 4 else 100
        revenue, opex = annual(0), annual(0)
        for y in spec.YEARS:
            if commission < y <= sale:
                revenue[str(y)] = ((15, 40, 25, 65)[i] if y <= commission + 2
                                    else (45, 60, 40, 80)[i]) if i < 4 else 100
                opex[str(y)] = (25, 15, 10, 30)[i] if i < 4 else 20
        projects.append({'id': pid, 'commission_year': commission, 'sale_year': sale,
            'acquisition_cost_pence': cost, 'depreciation_years': (4, 3, 2, 6)[i] if i < 4 else 1,
            'annual_revenue_pence': revenue, 'annual_opex_pence': opex,
            'sale_proceeds_pence': (50, 40, 20, 45)[i] if i < 4 else 10})
    scenarios = []
    for si, sid in enumerate(spec.SCENARIO_IDS):
        scenario = {'id': sid, 'revenue_factors_p12': annual(spec.SCALE),
            'opex_factors_p12': annual(spec.SCALE), 'nav_factors_p12': annual(spec.SCALE),
            'sale_factors_p12': annual(spec.SCALE), 'bank_rates_p12': annual(spec.SCALE // 100),
            'haircuts_p12': annual(spec.SCALE // 5)}
        if si == 1:
            scenario['revenue_factors_p12']['2025'] = spec.SCALE // 2
            scenario['nav_factors_p12']['2025'] = spec.SCALE // 2
            scenario['haircuts_p12']['2026'] = spec.SCALE * 9 // 10
        if si == 2:
            scenario['opex_factors_p12'] = annual(spec.SCALE * 6 // 5)
            scenario['sale_factors_p12'] = annual(spec.SCALE * 3 // 4)
        scenarios.append(scenario)
    return {'schema_version': 1, 'currency': 'GBP', 'monetary_unit': 'pence', 'years': list(spec.YEARS),
        'opening_cash_pence': 40 if stress else 1000, 'minimum_cash_pence': 10,
        'lp_commitment_pence': 100 if stress else 1000, 'facility_limit_pence': 80,
        'advance_rate_p12': spec.SCALE * 3 // 4, 'tax_rate_p12': spec.SCALE // 4,
        'tax_loss_carry_years': 2,
        'discount_factors_p12': {str(y): spec.SCALE * 95 ** (i + 1) // 100 ** (i + 1)
                                 for i, y in enumerate(spec.YEARS)},
        'projects': projects, 'scenarios': scenarios,
        'provenance': {'kind': 'synthetic_capital_allocation_extension',
                       'raw_ancestors': deepcopy(spec.RAW_ANCESTORS)}}


def inactive_fixed(value):
    return {p['id']: 0 for p in value['projects'][4:]}


@pytest.mark.parametrize('numerator,denominator,expected', [(1, 2, 1), (-1, 2, -1),
    (3, 2, 2), (-3, 2, -2), (1, 3, 0), (-1, 3, 0), (2, 3, 1), (-2, 3, -1)])
def test_posting_is_exact_half_away_for_signed_values(numerator, denominator, expected):
    assert bounds._round(numerator, denominator) == expected


@pytest.mark.parametrize('n', [40, 48, 56])
def test_dimension_bindings_use_canonical_large_count_and_mask_strings(n):
    value = public(n); before = deepcopy(value); model = bounds.prepare_bounds(value)
    assert value == before and model.spec_sha256 == spec.canonical_sha(value)
    binding = model.binding(); region = bounds.prefix_binding(model, {'P01': 0, f'P{n:02}': 1})
    assert binding['combinatorial_plan_count'] == str(1 << n) and binding['searched_plan_count'] == '0'
    assert region['combinatorial_region_count'] == str(1 << (n - 2))
    assert region['known_mask_hex'] == '0x' + format(1 | (1 << (n - 1)), '016x')
    assert region['value_mask_hex'] == '0x' + format(1 << (n - 1), '016x')
    assert json.loads(json.dumps(bounds.evaluate_bounds(model, inactive_fixed(value))))['binding'] == binding
    assert all(x <= F(41, 2) < 100 for x in model.rounding_envelopes)
    assert bounds.validate_binding(model, binding)
    for key in ('public_spec_sha256', 'math_recipe_sha256', 'schema_recipe_sha256'):
        bad = deepcopy(binding); bad[key] = '0' * 64
        with pytest.raises(ValueError, match='binding changed'):
            bounds.validate_binding(model, bad)


def test_all_raw_candidate_postings_match_one_independent_Decimal_forward():
    # One fixed plan only. Candidate schedules are complete and unweighted.
    value = public(); value['projects'][0].update(acquisition_cost_pence=2, depreciation_years=4)
    value['projects'][0]['annual_revenue_pence']['2025'] = 1
    value['scenarios'][0]['revenue_factors_p12']['2025'] = spec.SCALE // 2
    model = bounds.prepare_bounds(value)
    actual = ledger.simulate(value, {p['id']: 0 for p in value['projects']})
    names = tuple(bounds.CandidateYear.__dataclass_fields__)
    for si, sid in enumerate(spec.SCENARIO_IDS):
        for j, pid in enumerate(model.project_ids):
            for candidate, expected in zip(model.candidates[si][j], actual['scenarios'][sid]['project_flows'][pid]):
                assert {key: getattr(candidate, key) for key in names} == expected
    assert model.candidates[0][0][1].revenue == 1
    assert [x.depreciation for x in model.candidates[0][0]][:5] == [0, 1, 1, 0, 0]


@pytest.mark.parametrize('stress', [False, True])
def test_only_four_active_bits_all_16_paths_and_prefix_bound_invariants(stress):
    # Exactly 16 forward calls per parameter, 32 total. Others are fixed zero.
    value = public(stress=stress)
    # Economic differences must greatly exceed the 100p posting cushion.
    for key in ('opening_cash_pence', 'minimum_cash_pence', 'lp_commitment_pence', 'facility_limit_pence'):
        value[key] *= 10000
    for p in value['projects']:
        for key in ('acquisition_cost_pence', 'sale_proceeds_pence'):
            p[key] *= 10000
        for key in ('annual_revenue_pence', 'annual_opex_pence'):
            p[key] = {y: v * 10000 for y, v in p[key].items()}
    model = bounds.prepare_bounds(value); fixed = inactive_fixed(value)
    results = []
    for bits in itertools.product((0, 1), repeat=4):
        plan = {**fixed, **dict(zip(model.project_ids[:4], bits))}
        result = ledger.simulate(value, plan)
        results.append((bits, result))
        if result['feasible']:
            for cut in model.cuts:
                assert sum(cut.weights[i] * plan[p] for i, p in enumerate(model.project_ids)) <= cut.capacity
            assert bounds.additive_upper_bound(model, plan) >= result['objective_pence']
            assert bounds.fractional_knapsack_upper_bound(model, plan) >= result['objective_pence']
            assert all(row['all_journals_balance'] for row in result['scenarios'].values())
    assert any(r['feasible'] for _, r in results)
    feasible_rows = [row for _, r in results if r['feasible']
                     for scenario in r['scenarios'].values() for row in scenario['annual']]
    assert any(row['bank_draw'] > 0 for row in feasible_rows)
    assert any(row['loss_used'] > 0 for row in feasible_rows)
    assert any(row['loss_expired'] > 0 for row in feasible_rows)
    if stress:
        assert any(not r['feasible'] for _, r in results)
    for depth in range(5):
        for prefix in itertools.product((0, 1), repeat=depth):
            choices = {**fixed, **dict(zip(model.project_ids[:depth], prefix))}
            feasible = [r['objective_pence'] for bits, r in results if bits[:depth] == prefix and r['feasible']]
            additive = bounds.additive_upper_bound(model, choices)
            knapsack = bounds.fractional_knapsack_upper_bound(model, choices)
            dual = bounds.dual_upper_bound(model, {'S01': F(1, 2), 'S02': F(1, 4), 'S03': F(1, 4)},
                                           {model.cuts[2].id: F(1, 7)}, choices)
            if feasible:
                best = max(feasible)
                assert knapsack is not None and best <= knapsack <= additive
                assert best <= dual
                encoded = bounds.evaluate_bounds(model, choices)
                assert int(encoded['integer_upper']) >= best


def knapsack_model():
    value = public(); value.update(opening_cash_pence=100, minimum_cash_pence=0,
        lp_commitment_pence=0, facility_limit_pence=0, tax_rate_p12=0)
    value['discount_factors_p12'] = annual(spec.SCALE)
    for p in value['projects'][:4]:
        p.update(commission_year=2024, sale_year=2026, acquisition_cost_pence=80, depreciation_years=1,
                 annual_revenue_pence={**annual(0), '2025': 300}, annual_opex_pence=annual(0), sale_proceeds_pence=0)
    for s in value['scenarios']:
        s.update(revenue_factors_p12=annual(spec.SCALE), opex_factors_p12=annual(spec.SCALE),
                 sale_factors_p12=annual(spec.SCALE), bank_rates_p12=annual(0), haircuts_p12=annual(0))
    return bounds.prepare_bounds(value), inactive_fixed(value)


def test_fractional_knapsack_and_non_normalized_cut_dual_have_hand_upper():
    model, fixed = knapsack_model()
    # Four independent gains 220; first-FY capacity100 buys at most 1.25*80.
    assert bounds.additive_upper_bound(model, fixed) == 100 + 4 * 220
    assert bounds.fractional_knapsack_upper_bound(model, fixed) == F(375)
    scenario = {'S01': 1, 'S02': 0, 'S03': 0}
    multipliers = {'S01.2024.facility': F(11, 4)}  # Valid dual; deliberately not sum1.
    assert bounds.dual_upper_bound(model, scenario, multipliers, fixed) == 375
    assert bounds.verify_dual_bound(model, scenario, multipliers, 375, fixed)['passed'] is True
    assert bounds.verify_dual_bound(model, scenario, multipliers, 374, fixed)['passed'] is False


def test_Farkas_checks_strict_inequality_and_cannot_make_a_false_prune():
    model, fixed = knapsack_model()
    impossible = {**fixed, 'P01': 1, 'P02': 1}
    cut = {'S01.2024.collateral': 1}
    assert bounds.fractional_knapsack_upper_bound(model, impossible) is None
    witness = bounds.verify_infeasibility_witness(model, cut, impossible)
    assert witness['passed'] is True
    assert bounds.rational(witness['weighted_capacity']) == -60
    assert bounds.rational(witness['minimum_possible_weighted_left']) == 0
    assert bounds.verify_infeasibility_witness(model, cut, {**fixed, 'P01': 1})['passed'] is False
    assert bounds.verify_infeasibility_witness(model, {}, impossible)['passed'] is False


@pytest.mark.parametrize('bad', [True, False, 0.5, '1/2', None,
    {'numerator': 1, 'denominator': 2}, {'numerator': '01', 'denominator': '2'},
    {'numerator': '-0', 'denominator': '1'}, {'numerator': '1', 'denominator': '0'},
    {'numerator': '2', 'denominator': '4'}, {'numerator': '0', 'denominator': '2'}])
def test_untrusted_rational_types_and_noncanonical_encodings_are_rejected(bad):
    with pytest.raises(ValueError):
        bounds.rational(bad)


def test_large_rational_json_roundtrip_has_only_canonical_strings():
    value = F(-(2**60 + 1), 2**57 + 3)
    encoded = bounds.encode_rational(value)
    assert all(type(x) is str for x in encoded.values())
    assert bounds.rational(json.loads(json.dumps(encoded))) == value


@pytest.mark.parametrize('case', ['negative_rate', 'increasing_discount', 'tax_bool', 'negative_tax', 'rate_float'])
def test_every_financial_proof_prerequisite_is_guarded(case):
    value = public()
    if case == 'negative_rate': value['scenarios'][0]['bank_rates_p12']['2025'] = -1
    elif case == 'increasing_discount': value['discount_factors_p12']['2025'] = spec.SCALE
    elif case == 'tax_bool': value['tax_rate_p12'] = True
    elif case == 'negative_tax': value['tax_rate_p12'] = -1
    else: value['scenarios'][0]['haircuts_p12']['2025'] = 0.5
    with pytest.raises(ValueError):
        bounds.prepare_bounds(value)


@pytest.mark.parametrize('fixed', [{'P01': True}, {'P01': 1.0}, {'P01': 2}, {'P57': 1}, []])
def test_prefixes_cannot_silently_coerce_decisions_or_unused_bits(fixed):
    model, _ = knapsack_model()
    with pytest.raises(ValueError):
        bounds.additive_upper_bound(model, fixed)


def test_exact_dual_and_infeasibility_guards_reject_bad_weights_and_unknown_cuts():
    model, fixed = knapsack_model()
    for weights in ({'S01': 1, 'S02': 0}, {'S01': 1, 'S02': 1, 'S03': 0},
                    {'S01': -1, 'S02': 2, 'S03': 0}, {'S01': True, 'S02': 0, 'S03': 0}):
        with pytest.raises(ValueError):
            bounds.dual_upper_bound(model, weights, {}, fixed)
    for multipliers in ({'S01.2024.facility': -1}, {'unknown': 1}, {'S01.2024.facility': 0.5}):
        with pytest.raises(ValueError):
            bounds.verify_infeasibility_witness(model, multipliers, fixed)


def test_maturity_has_no_bank_or_minimum_cash_or_collateral_rounding_allowance():
    model = bounds.prepare_bounds(public())
    last = [c for c in model.cuts if c.year == 2043 and c.scenario == 'S01']
    assert len(last) == 2 and last[0].capacity == last[1].capacity == 2000
    assert last[0].weights == last[1].weights
    first = next(c for c in model.cuts if c.id == 'S01.2024.collateral')
    assert first.capacity == 1990


def test_integer_upper_is_mathematical_floor_even_for_a_negative_rational():
    value = public(); value['minimum_cash_pence'] = 0
    value['discount_factors_p12'] = annual(spec.SCALE // 3)
    model = bounds.prepare_bounds(value); fixed = {p: 0 for p in model.project_ids}
    upper = bounds.fractional_knapsack_upper_bound(model, fixed)
    assert upper < 0 and upper.denominator > 1
    encoded = bounds.evaluate_bounds(model, fixed)
    assert encoded['integer_upper'] == str(upper.numerator // upper.denominator)
    assert int(encoded['integer_upper']) < int(upper)


def test_bounds_module_contains_no_forward_or_optimization_execution_route():
    source = Path(bounds.__file__).read_text();tree = ast.parse(source)
    imports = [n.module or '' for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    imports += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not any(any(x in name for x in ('ledger', 'subprocess', 'openpyxl', 'scipy', 'ortools')) for name in imports)
