"""Deterministic public hypothetical inputs, without financial or model search."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP, localcontext
import random

from .spec import PROJECT_IDS, RAW_ANCESTORS, SCALE, YEARS, load_spec

PROFILE_FIELDS = {
    'id', 'opening_cash_gbp', 'minimum_cash_gbp', 'lp_commitment_gbp',
    'facility_limit_gbp', 'advance_rate', 'tax_rate', 'discount_rate', 'loss_carry_years',
}


def _integer(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _p12(value):
    return _integer(Decimal(value) * SCALE)


def validate_catalog(catalog):
    expected = {'schema_version', 'kind', 'seed', 'currency', 'project_count',
                'scenario_count', 'years', 'profiles'}
    if (not isinstance(catalog, dict) or set(catalog) != expected
            or type(catalog['schema_version']) is not int or catalog['schema_version'] != 1
            or catalog['kind'] != 'predeclared_synthetic_capital_allocation_catalog'
            or type(catalog['seed']) is not int
            or catalog['currency'] != 'GBP' or catalog['project_count'] != 18
            or catalog['scenario_count'] != 3 or catalog['years'] != [2024, 2043]):
        raise ValueError('The declared synthetic catalog dimensions or fields differ')
    profiles = catalog['profiles']
    if not isinstance(profiles, list) or [p.get('id') for p in profiles] != [f'K{i:02d}' for i in range(1, 11)]:
        raise ValueError('The complete ordered ten profiles are required')
    for profile in profiles:
        if set(profile) != PROFILE_FIELDS:
            raise ValueError('A public catalog profile has unexpected fields')
        for key in ('opening_cash_gbp', 'minimum_cash_gbp', 'lp_commitment_gbp', 'facility_limit_gbp'):
            if type(profile[key]) is not int or not 0 <= profile[key] <= 10**9:
                raise ValueError('Catalog funding amounts must be bounded integer GBP')
        if profile['opening_cash_gbp'] < profile['minimum_cash_gbp']:
            raise ValueError('Opening cash is below the required minimum')
        for key in ('advance_rate', 'tax_rate', 'discount_rate'):
            if not isinstance(profile[key], str) or not Decimal(0) < Decimal(profile[key]) < Decimal(1):
                raise ValueError('Catalog rates must be finite exact decimal fractions')
        if type(profile['loss_carry_years']) is not int or not 1 <= profile['loss_carry_years'] <= 20:
            raise ValueError('The tax loss lifetime must be an integer year count')
    return deepcopy(catalog)


def _projects(seed):
    # A dedicated random stream makes the public inputs reproducible and
    # independent of every solver, quality verdict and other process RNG.
    rng = random.Random(seed)
    projects = []
    for index, identifier in enumerate(PROJECT_IDS):
        commissioning = 2024 + index % 6
        lifetime = rng.randrange(7, 15)
        sale = min(2043, commissioning + lifetime)
        cost = rng.randrange(1200, 4801) * 100000  # GBP1.2m..GBP4.8m, in pence.
        sales_fraction = Decimal(rng.randrange(38, 63)) / 100
        expense_fraction = Decimal(rng.randrange(19, 36)) / 100
        growth = Decimal(rng.randrange(10, 36)) / 1000
        first_ramp = Decimal(rng.choice((35, 50, 65))) / 100
        second_ramp = Decimal(rng.choice((72, 80, 90))) / 100
        sales, expenses = {}, {}
        for year in YEARS:
            age = year - commissioning
            if not commissioning < year <= sale:
                sales[str(year)] = expenses[str(year)] = 0
                continue
            ramp = first_ramp if age == 1 else second_ramp if age == 2 else Decimal(1)
            inflation = (Decimal(1) + growth) ** (age - 1)
            sales[str(year)] = _integer(Decimal(cost) * sales_fraction * ramp * inflation)
            # The startup operating cost is incurred even before full revenue.
            expenses[str(year)] = _integer(Decimal(cost) * expense_fraction * inflation)
        projects.append({'id': identifier, 'commission_year': commissioning, 'sale_year': sale,
            'acquisition_cost_pence': cost, 'depreciation_years': rng.randrange(4, 13),
            'annual_revenue_pence': sales, 'annual_opex_pence': expenses,
            'sale_proceeds_pence': _integer(Decimal(cost) * Decimal(rng.randrange(35, 86)) / 100)})
    return projects


def _scenarios(profile_index):
    scenarios = []
    for scenario in range(3):
        row = {'id': f'S{scenario + 1:02d}', **{key: {} for key in (
            'revenue_factors_p12', 'opex_factors_p12', 'nav_factors_p12',
            'sale_factors_p12', 'bank_rates_p12', 'haircuts_p12')}}
        for index, year in enumerate(YEARS):
            stress = (index + profile_index) % 7 in (2, 3)
            if scenario == 0:
                values = ('0.94' if index < 4 else '1.08', '1.12' if stress else '1.04',
                          '0.86' if stress else '1.02', '0.93', '0.065', '0.22' if stress else '0.10')
            elif scenario == 1:
                values = ('0.72' if index < 5 else '1.10', '0.97' if index < 5 else '1.06',
                          '0.62' if stress else '0.93', '0.88', '0.080', '0.46' if stress else '0.18')
            else:
                values = ('1.14' if index < 8 else '0.86', '1.05' if index < 8 else '1.18',
                          '1.08' if index < 8 else '0.74', '0.82' if stress else '1.07',
                          '0.095' if stress else '0.070', '0.38' if index >= 8 else '0.12')
            for key, value in zip(list(row)[1:], values):
                row[key][str(year)] = _p12(value)
        scenarios.append(row)
    return scenarios


def generate_specs(catalog):
    """Generate all ten specs in declared order, without selecting a subset.

    These are synthetic GBP forecasts. Ancestor hashes retain the project's
    provenance; no numeric input is claimed to be an observed NYU/Ofgem fact.
    A generated spec is neither a verified source nor an admitted task.
    """
    catalog = validate_catalog(catalog)
    result = []
    with localcontext() as context:
        context.prec = 60
        for index, profile in enumerate(catalog['profiles']):
            discount = Decimal(1) + Decimal(profile['discount_rate'])
            spec = {'schema_version': 1, 'currency': 'GBP', 'monetary_unit': 'pence',
                'years': list(YEARS), **{key.replace('_gbp', '_pence'): profile[key] * 100 for key in (
                    'opening_cash_gbp', 'minimum_cash_gbp', 'lp_commitment_gbp', 'facility_limit_gbp')},
                'advance_rate_p12': _p12(profile['advance_rate']), 'tax_rate_p12': _p12(profile['tax_rate']),
                'tax_loss_carry_years': profile['loss_carry_years'],
                'discount_factors_p12': {str(year): _integer(Decimal(SCALE) / discount ** (i + 1))
                    for i, year in enumerate(YEARS)},
                'projects': _projects(catalog['seed'] + index * 1009), 'scenarios': _scenarios(index),
                'provenance': {'kind': 'synthetic_capital_allocation_extension', 'raw_ancestors': RAW_ANCESTORS.copy()}}
            result.append({'profile_id': profile['id'], 'spec': load_spec(spec)})
    return result
