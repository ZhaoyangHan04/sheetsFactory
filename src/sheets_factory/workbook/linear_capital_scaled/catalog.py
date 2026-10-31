"""Fresh N360 business assumptions and globally shared board capacities.

This generator calls no financial ledger, matrix compiler or optimizer. All
360 projects are generated independently from one explicit seed; it never
copies or tiles an earlier 240-project specification. The common capacities
span the whole new universe. Cost, contractual financing and provided physical
usage determine those capacities before any NPV or selected plan exists.
"""
from __future__ import annotations

from copy import deepcopy
import random

from . import spec

SEED = 202701360
PROFILE_ID = 'L360-N01'
GENERATION_POLICY = 'fresh_n360_standard_contracts_global_capacities_v1'
COMPETITIVE_POLICY = 'fresh_n360_correlated_contracts_independent_revenue_jitter_v1'
HUB_COUNT = 60
UNGROUPED_COUNT = 180
SITE_COUNT = 60
PREREQUISITE_COUNT = 120
REVENUE_JITTER_PENCE = 150_000
MIN_PROJECT_COST_PENCE = 20_000_000
MAX_PROJECT_COST_PENCE = 100_000_000
# This follows the minimum raw revenue, so every allowed spread preserves the
# unchanged nonnegative monetary domain for every possible generator draw.
MAX_REVENUE_JITTER_PENCE = MIN_PROJECT_COST_PENCE*3000//spec.BP
SECTORS = ('Solar park', 'Wind farm', 'Battery storage', 'District heating',
    'Water treatment', 'Freight terminal', 'Charging network', 'Biogas plant')
REGIONS = ('Northern', 'Eastern', 'Central', 'Western', 'Southern', 'Coastal')
CAPACITY_POLICY = {
    'kind': GENERATION_POLICY, 'projects': 360, 'scenarios': 3, 'years': 20,
    'independent_connection_hubs': HUB_COUNT,
    'ungrouped_projects_including_hubs': UNGROUPED_COUNT,
    'alternative_sites': SITE_COUNT, 'options_per_site': 3,
    'acyclic_links_to_global_hubs': PREREQUISITE_COUNT,
    'opening_equity_capacity_bp_of_raw_equity_proxy': 4500,
    'annual_new_lp_capacity_bp_of_total_raw_cost': 500,
    'annual_debt_capacity_bp_of_contractual_unamortized_proxy': 4600,
    'physical_resource_capacity_bp_of_complete_provided_usage': [4400, 4500],
    'region_and_sector_capacity_bp_of_raw_cost_remaining_life_proxy': 4600,
    'remaining_life_proxy_years': 15,
    'financial_forwards_or_NPV_or_optimized_plan_used': False,
    'previous_project_blocks_copied_or_tiled': False,
    'all_capacities_are_provided_board_assumptions_not_financial_certificates': True,
}


def generation_policy():
    return deepcopy(CAPACITY_POLICY)


def _build_standard_spec(seed):
    """Construct one complete fresh raw specification in memory, with no calls.

    Standard contract terms preserve the existing public financial equations.
    Each cost, revenue adjustment and dated resource observation is drawn anew.
    Region/sector exposure proxies use raw installation cost and remaining
    contractual life; actual financial exposure is independently checked later.
    """
    spec.require(type(seed) is int and 0 <= seed < 2**32,
        'Use an explicit bounded integer raw-assumption seed')
    rng = random.Random(seed)
    ids, years, scenarios = list(spec.PROJECT_IDS), list(spec.YEARS), list(spec.SCENARIO_IDS)
    resources, regions, sectors = list(spec.RESOURCE_IDS), list(spec.REGION_IDS), list(spec.SECTOR_IDS)
    spec.require(len(ids) == 360 and UNGROUPED_COUNT+3*SITE_COUNT == len(ids)
        and HUB_COUNT <= UNGROUPED_COUNT, 'The complete fixed N360 partition changed')
    site_regions = [rng.choice(regions) for _ in range(SITE_COUNT)]
    projects = []
    for index, pid in enumerate(ids):
        cost = rng.randint(MIN_PROJECT_COST_PENCE, MAX_PROJECT_COST_PENCE)
        region = regions[index % len(regions)] if index < UNGROUPED_COUNT else site_regions[(index-UNGROUPED_COUNT)//3]
        sector = sectors[index % len(sectors)]
        revenue = cost*3000//spec.BP
        usage = {resource: {sid: {str(year): cost//1000+rng.randint(0, 5000)
            for year in years} for sid in scenarios} for resource in resources}
        label = REGIONS[regions.index(region)]+' connection hub ' if index < HUB_COUNT else SECTORS[sectors.index(sector)]+' '
        projects.append({'id': pid, 'name': label+pid, 'region': region, 'sector': sector,
            'asset_cost_pence': cost, 't0_ltv_bp': 6000, 'operating_start_year': 1,
            'depreciation_years': 15, 'base_annual_revenue_pence': revenue,
            'base_annual_opex_pence': revenue*6500//spec.BP,
            'revenue_growth_factor_bp': 10000, 'opex_growth_factor_bp': 10000,
            'bank_rate_bp': 500, 'debt_policy': 'LEVEL_PRINCIPAL', 'debt_maturity_year': 10,
            'tax_rate_bp': 2500, 'discount_rate_bp': 700,
            'terminal_sale_proceeds_pence': cost*3000//spec.BP,
            'lp_commitment_pence': cost*100, 'resource_usage_units': usage})
    scenario_rows = []
    for sid, name, revenue, expense, spread, sale in (
        ('S01', 'Operating plan', 10000, 10000, 0, 10000),
        ('S02', 'Lower demand and higher funding cost', 9000, 11000, 150, 8000),
        ('S03', 'Prolonged demand stress', 8000, 11500, 250, 6500)):
        scenario_rows.append({'id': sid, 'name': name,
            'revenue_factors_bp': {str(y): revenue for y in years},
            'opex_factors_bp': {str(y): expense for y in years},
            'sale_factors_bp': {str(y): sale for y in years},
            'interest_spread_bp': {str(y): spread for y in years}})
    total_cost = sum(p['asset_cost_pence'] for p in projects)
    raw_equity = sum(p['asset_cost_pence']*(spec.BP-p['t0_ltv_bp'])//spec.BP for p in projects)
    limits = {'initial_sponsor_equity_pence': raw_equity*4500//spec.BP,
        'annual_new_lp_pence': {}, 'annual_debt_close_pence': {},
        'resource_capacity_units': {}, 'region_exposure_pence': {}, 'sector_exposure_pence': {}}
    for sid in scenarios:
        limits['annual_new_lp_pence'][sid] = {str(y): total_cost*500//spec.BP for y in years}
        limits['annual_debt_close_pence'][sid] = {str(y):
            total_cost*6000*(10-y)*4600//(spec.BP**2*10) if y < 10 else 0 for y in years}
    for resource in resources:
        limits['resource_capacity_units'][resource] = {}
        for sid in scenarios:
            limits['resource_capacity_units'][resource][sid] = {}
            for year in years:
                total = sum(p['resource_usage_units'][resource][sid][str(year)] for p in projects)
                limits['resource_capacity_units'][resource][sid][str(year)] = total*rng.randint(4400, 4500)//spec.BP
    for attribute, field, labels in (('region', 'region_exposure_pence', regions),
        ('sector', 'sector_exposure_pence', sectors)):
        for identity in labels:
            cost = sum(p['asset_cost_pence'] for p in projects if p[attribute] == identity)
            limits[field][identity] = {str(y): cost*4600*max(0, 15-y)//(spec.BP*15) for y in years}
    groups = [{'id': f'SITE{i+1:02d}',
        'description': f'Alternative technology packages for site {i+1:02d}; fund at most one.',
        'project_ids': ids[UNGROUPED_COUNT+3*i:UNGROUPED_COUNT+3*i+3]} for i in range(SITE_COUNT)]
    # All prerequisites point to independent hubs in the same full-universe
    # budget. No hub depends on an enabled asset, so no cycle is introduced.
    dependents = rng.sample(ids[HUB_COUNT:], PREREQUISITE_COUNT)
    edges = []
    for index, dependent in enumerate(dependents):
        hub = rng.choice(ids[:HUB_COUNT])
        edges.append({'id': f'LINK{index+1:03d}', 'dependent': dependent, 'prerequisite': hub,
            'business_reason': f'{dependent} requires the separately funded connection capacity supplied by {hub}.'})
    value = {'kind': spec.SPEC_KIND, 'version': spec.SPEC_VERSION, 'dimension_mode': 'production',
        'fiscal_year_start': 2027, 'years': years, 'project_ids': ids, 'scenario_ids': scenarios,
        'resource_ids': resources, 'region_ids': regions, 'sector_ids': sectors,
        'projects': projects, 'scenarios': scenario_rows, 'shared_limits': limits,
        'exclusivity_groups': groups, 'prerequisites': edges,
        'provenance': {'hypothetical': True, 'ancestor_sha256': [],
            'description': f'Fresh prospective {PROFILE_ID}, seed {seed}, policy {GENERATION_POLICY}: '
                '360 newly generated ring-fenced projects, 60 independent global connection hubs, '
                '60 three-option sites and 120 acyclic enabling links. Standard contract terms and '
                'independent dated physical observations feed common board capacities spanning all '
                '360 projects. Capacities use raw costs, financing terms and physical usage only; '
                'no previous 240-project blocks, financial forward, NPV, optimizer, selected plan '
                'or model outcome is used. All source correctness and difficulty checks remain pending.'}}
    return spec.load_spec(value)


def build_competitive_spec(seed, revenue_jitter_pence):
    """Fresh N360 contracts plus one independent revenue draw per project.

    As in the original competitive catalogs, a separate ``Random(seed)``
    stream supplies the revenue adjustment. Changing only the prospective
    spread changes revenue, its linked operating expense and provenance;
    every raw cost, resource observation, capacity and relationship stays
    identical. No financial result or selected plan enters this construction.
    """
    spec.require(type(revenue_jitter_pence) is int
        and 0 <= revenue_jitter_pence <= MAX_REVENUE_JITTER_PENCE,
        'Use an explicit bounded nonnegative integer revenue spread')
    public = _build_standard_spec(seed)
    rng = random.Random(seed)
    for project in public['projects']:
        revenue = project['asset_cost_pence']*3000//spec.BP + rng.randint(
            -revenue_jitter_pence, revenue_jitter_pence)
        project['base_annual_revenue_pence'] = revenue
        project['base_annual_opex_pence'] = revenue*6500//spec.BP
    public['provenance'] = {'hypothetical': True, 'ancestor_sha256': [],
        'description': f'Fresh prospective {PROFILE_ID}, seed {seed}, policy {COMPETITIVE_POLICY}: '
            f'{GENERATION_POLICY} supplies all 360 newly generated raw contracts, 60 global connection '
            'hubs, 60 three-option sites, 120 acyclic enabling links and complete shared capacities. '
            'A separate random.Random(seed) supplies one independent integer revenue adjustment per '
            f'ordered project in [-{revenue_jitter_pence}, {revenue_jitter_pence}] GBP pence. Revenue '
            'is cost*3000//10000 plus that adjustment; operating expense is revenue*6500//10000. '
            'Capacities use raw costs, financing terms and physical usage only. No previous '
            '240-project blocks, financial forward, NPV, optimizer, selected plan or model outcome '
            'is used. All source correctness and difficulty checks remain pending.'}
    return spec.load_spec(public)


def build_spec(seed=SEED):
    """Default competitive unit fixture; no prospective batch is declared."""
    return build_competitive_spec(seed, REVENUE_JITTER_PENCE)


def diagnostic_plans(specification, *, seed=SEED):
    """Eighteen complete prospective financial/constraint diagnostic plans."""
    public = spec.load_spec(specification); ids = public['project_ids']
    spec.require(type(seed) is int and 0 <= seed < 2**32, 'Use an explicit diagnostic seed')
    rng = random.Random(seed ^ 0x5A17)
    if public['dimension_mode'] == 'toy':
        return [{'id': name, 'plan': spec.validate_plan(public, {pid: value for pid in ids})}
            for name, value in [('empty', 0), ('all', 1)]]
    choices = [('empty', set()), ('all', set(ids)), ('odd_identifiers', set(ids[::2])),
        ('even_identifiers', set(ids[1::2]))]
    for option in range(3):
        choices.append(('hubs_and_site_option_'+str(option+1), set(ids[:HUB_COUNT])
            | {group['project_ids'][option] for group in public['exclusivity_groups']}))
    choices.extend([('independent_first120', set(ids[:120])), ('independent_first180', set(ids[:180]))])
    choices.extend(('seeded_half_'+str(index), set(rng.sample(ids, len(ids)//2))) for index in range(9))
    return [{'id': name, 'plan': spec.validate_plan(public, {pid: int(pid in selected) for pid in ids})}
        for name, selected in choices]
