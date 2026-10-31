"""Prospective standardized contracts with closely competing investments.

This raw generator uses no financial forward or optimizer. Common financing,
tariff and operating terms create comparable project economics; dated physical
usage and publicly provided capacity schedules still differ by project.
"""
import random

from . import catalog, spec

SEED = 20261101
PROFILE_ID = 'L240-C01'


def build_spec(seed=SEED):
    spec.require(type(seed) is int and 0 <= seed < 2**32, 'Use an explicit bounded integer scenario seed')
    s = catalog.build_spec(seed)
    rng = random.Random(seed ^ 0x4C323430)
    for p in s['projects']:
        cost = p['asset_cost_pence']
        # These are new provided contract assumptions, not adjustments to a
        # calculated NPV or a prior selected plan.
        p.update(t0_ltv_bp=6000, operating_start_year=1, depreciation_years=15,
            base_annual_revenue_pence=cost*3000//spec.BP + rng.randint(-50, 50),
            revenue_growth_factor_bp=10000, opex_growth_factor_bp=10000,
            bank_rate_bp=500, debt_policy='LEVEL_PRINCIPAL', debt_maturity_year=10,
            tax_rate_bp=2500, discount_rate_bp=700,
            terminal_sale_proceeds_pence=cost*3000//spec.BP)
        p['base_annual_opex_pence'] = p['base_annual_revenue_pence']*6500//spec.BP
        # Physical capacity is closely related to installation scale, with
        # dated, independently supplied commissioning/availability variation.
        for resource in s['resource_ids']:
            for sid in s['scenario_ids']:
                for year in s['years']:
                    p['resource_usage_units'][resource][sid][str(year)] = cost//1000 + rng.randint(0, 5000)
    limits = s['shared_limits']
    total_cost = sum(p['asset_cost_pence'] for p in s['projects'])
    initial_equity = sum(p['asset_cost_pence']*4000//spec.BP for p in s['projects'])
    limits['initial_sponsor_equity_pence'] = initial_equity*4500//spec.BP
    for sid in s['scenario_ids']:
        for year in s['years']:
            limits['annual_new_lp_pence'][sid][str(year)] = total_cost*500//spec.BP
            # A contractual outstanding-principal design proxy uses raw
            # maturity, not a computed or optimized project forecast.
            limits['annual_debt_close_pence'][sid][str(year)] = (
                total_cost*6000*(10-year)*4600//(spec.BP**2*10) if year < 10 else 0)
    for resource in s['resource_ids']:
        for sid in s['scenario_ids']:
            for year in s['years']:
                total = sum(p['resource_usage_units'][resource][sid][str(year)] for p in s['projects'])
                limits['resource_capacity_units'][resource][sid][str(year)] = total*rng.randint(4400, 4500)//spec.BP
    for label, field in (('region', 'region_exposure_pence'), ('sector', 'sector_exposure_pence')):
        for identity in s[label+'_ids']:
            cost = sum(p['asset_cost_pence'] for p in s['projects'] if p[label] == identity)
            for year in s['years']:
                limits[field][identity][str(year)] = cost*4600*max(0, 15-year)//(spec.BP*15)
    s['provenance'] = {'hypothetical': True, 'ancestor_sha256': [],
        'description': f'Prospective {PROFILE_ID}, seed {seed}: standardized tariffs, financing and operating terms; '
            'dated physical usage and board capacities are provided raw assumptions. No financial forward or optimized selection is used.'}
    return spec.load_spec(s)
