"""Prospective hypothetical project assumptions and public capacity schedules.

This generator does not call either financial implementation or any optimizer.
Capacity design uses provided costs, contractual maturities and physical usage;
no computed project NPV, best plan or model outcome enters the construction.
"""
from __future__ import annotations

import random

from . import spec

SEED = 20261031
PROFILE_ID = 'L240-H01'
SECTORS = ('Solar park', 'Wind farm', 'Battery storage', 'District heating',
    'Water treatment', 'Freight terminal', 'Charging network', 'Biogas plant')
REGIONS = ('Northern', 'Eastern', 'Central', 'Western', 'Southern', 'Coastal')


def diagnostic_plans(specification, *, seed=SEED):
    """Freeze financial/constraint probes without evaluating or selecting one."""
    s=spec.load_spec(specification);ids=s['project_ids'];rng=random.Random(seed ^ 0x5A17)
    choices=[('empty',set()),('all',set(ids)),('odd_identifiers',set(ids[::2])),
        ('even_identifiers',set(ids[1::2]))]
    for alternative in range(3):
        choices.append(('hubs_and_site_option_'+str(alternative+1),
            set(ids[:40])|{group['project_ids'][alternative] for group in s['exclusivity_groups']}))
    choices += [('independent_first80',set(ids[:80])),('independent_first120',set(ids[:120]))]
    choices += [('seeded_half_'+str(i),set(rng.sample(ids,len(ids)//2))) for i in range(9)]
    return [{'id':name,'plan':spec.validate_plan(s,{pid:int(pid in selected) for pid in ids})}
        for name,selected in choices]


def build_spec(seed=SEED):
    """Generate one full raw universe before any financial/solver evaluation."""
    spec.require(type(seed) is int and 0 <= seed <= 2**32-1, 'Use an explicit bounded integer scenario seed')
    rng = random.Random(seed)
    ids, years, scenarios = list(spec.PROJECT_IDS), list(spec.YEARS), list(spec.SCENARIO_IDS)
    resources, regions, sectors = list(spec.RESOURCE_IDS), list(spec.REGION_IDS), list(spec.SECTOR_IDS)
    projects = []
    group_regions = {i: regions[rng.randrange(len(regions))] for i in range(40)}
    for index, pid in enumerate(ids):
        cost = rng.randint(20_000_000, 100_000_000)
        sector = sectors[index % len(sectors)]
        region = regions[index % len(regions)] if index < 120 else group_regions[(index-120)//3]
        start = rng.choice((1, 1, 1, 2, 2, 3))
        usage = {}
        for resource in resources:
            baseline = rng.randint(8, 70)
            usage[resource] = {}
            for sid in scenarios:
                usage[resource][sid] = {str(year): max(1, baseline*rng.randint(75, 125)//100)
                    if year >= start else max(1, baseline*rng.randint(10, 40)//100) for year in years}
        revenue = cost*rng.randint(2500, 4500)//spec.BP
        expense = revenue*rng.randint(5000, 7800)//spec.BP
        name = ((REGIONS[regions.index(region)]+' connection hub ')
            if index < 40 else (SECTORS[sectors.index(sector)]+' ')) + pid
        projects.append({'id':pid,'name':name,'region':region,'sector':sector,
            'asset_cost_pence':cost,'t0_ltv_bp':rng.randrange(3500,7501,125),
            'operating_start_year':start,'depreciation_years':rng.choice((10,15,20)),
            'base_annual_revenue_pence':revenue,'base_annual_opex_pence':expense,
            'revenue_growth_factor_bp':rng.randrange(10100,10501,25),
            'opex_growth_factor_bp':rng.randrange(10100,10601,25),
            'bank_rate_bp':rng.randrange(300,701,25),
            'debt_policy':rng.choice(('LEVEL_PRINCIPAL','BULLET')),
            'debt_maturity_year':rng.choice((5,7,10,12,15,20)),
            'tax_rate_bp':rng.choice((2000,2500,3000)),
            'discount_rate_bp':rng.randrange(500,1001,25),
            'terminal_sale_proceeds_pence':cost*rng.randint(1500,4500)//spec.BP,
            'lp_commitment_pence':cost*100,'resource_usage_units':usage})
    scenario_rows = []
    for sid, name, rev, expense, spread, sale in (
        ('S01','Operating plan',10000,10000,0,10000),
        ('S02','Lower demand and higher funding cost',9000,11000,150,8000),
        ('S03','Prolonged demand stress',8000,11500,250,6500)):
        scenario_rows.append({'id':sid,'name':name,
            'revenue_factors_bp':{str(y):rev for y in years},
            'opex_factors_bp':{str(y):expense for y in years},
            'sale_factors_bp':{str(y):sale for y in years},
            'interest_spread_bp':{str(y):spread for y in years}})
    # These are public board capacity assumptions, not a candidate selection or
    # a claimed financial forecast. The conservative contractual debt proxy
    # ignores amortisation; the actual constraint uses the independently
    # calculated year-end outstanding principal, never this design proxy.
    total_cost = sum(p['asset_cost_pence'] for p in projects)
    opening_equity_proxy = sum(p['asset_cost_pence']*(spec.BP-p['t0_ltv_bp'])//spec.BP for p in projects)
    limits = {'initial_sponsor_equity_pence':opening_equity_proxy*5000//spec.BP,
        'annual_new_lp_pence':{},'annual_debt_close_pence':{},
        'resource_capacity_units':{},'region_exposure_pence':{},'sector_exposure_pence':{}}
    for sid in scenarios:
        limits['annual_new_lp_pence'][sid] = {str(y):total_cost*rng.randint(300,550)//spec.BP for y in years}
        limits['annual_debt_close_pence'][sid] = {}
        for year in years:
            active_draw_proxy = sum(p['asset_cost_pence']*p['t0_ltv_bp']//spec.BP
                for p in projects if year < p['debt_maturity_year'])
            limits['annual_debt_close_pence'][sid][str(year)] = active_draw_proxy*rng.randint(4500,6000)//spec.BP
    for resource in resources:
        limits['resource_capacity_units'][resource] = {sid:{str(year):
            sum(p['resource_usage_units'][resource][sid][str(year)] for p in projects)
                *rng.randint(4500,6000)//spec.BP for year in years} for sid in scenarios}
    for field, identities, membership in (
        ('region_exposure_pence',regions,'region'),('sector_exposure_pence',sectors,'sector')):
        for identity in identities:
            cost = sum(p['asset_cost_pence'] for p in projects if p[membership] == identity)
            fraction = rng.randint(4500,6000)
            limits[field][identity] = {str(year):cost*fraction*max(2500,10000-400*year)//spec.BP**2 for year in years}
    groups = [{'id':f'SITE{i+1:02d}',
        'description':f'Alternative technology packages for site {i+1:02d}; fund at most one.',
        'project_ids':ids[120+3*i:123+3*i]} for i in range(40)]
    # Each enabled asset has at most one prerequisite, always among the first
    # forty independent hubs. No cycle or site-alternative contradiction is
    # introduced by this construction.
    dependents = rng.sample(ids[40:],80)
    edges = []
    for index, dependent in enumerate(dependents):
        enabler = rng.choice(ids[:40])
        edges.append({'id':f'LINK{index+1:03d}','dependent':dependent,'prerequisite':enabler,
            'business_reason':f'{dependent} requires the separately funded connection capacity supplied by {enabler}.'})
    value = {'version':1,'kind':'hypothetical_ringfenced_linear_capital_portfolio',
        'dimension_mode':'production','fiscal_year_start':2027,'years':years,'project_ids':ids,
        'scenario_ids':scenarios,'resource_ids':resources,'region_ids':regions,'sector_ids':sectors,
        'projects':projects,'scenarios':scenario_rows,'shared_limits':limits,
        'exclusivity_groups':groups,'prerequisites':edges,
        'provenance':{'hypothetical':True,
            'description':f'Prospective {PROFILE_ID} project assumptions; fixed generator seed {seed}. '
                'Board capacities use raw costs, contractual maturity and provided physical usage, without project NPV or optimized plans.',
            'ancestor_sha256':[]}}
    return spec.load_spec(value)
