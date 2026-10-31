"""Typed public contract only; no financial forward, search or workbook I/O."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

BP = 10000
EXACT_LIMIT = 2**53
PROJECT_MONEY_LIMIT = 100_000_000
PORTFOLIO_MONEY_LIMIT = 10**12
PROJECT_IDS = tuple(f'P{i:03d}' for i in range(1, 241))
SCENARIO_IDS = ('S01', 'S02', 'S03')
YEARS = tuple(range(1, 21))
RESOURCE_IDS = tuple(f'U{i:02d}' for i in range(1, 7))
REGION_IDS = tuple(f'R{i:02d}' for i in range(1, 7))
SECTOR_IDS = tuple(f'C{i:02d}' for i in range(1, 9))
T0_FIELDS = ('asset_cost', 'bank_draw', 'lp_required', 'lp_call', 'lp_remaining',
    'funding_gap', 'cash_close', 'asset_nbv_close', 'debt_close', 'book_equity_close', 'balance_check')
ANNUAL_FIELDS = ('cash_open', 'asset_nbv_open', 'revenue_base', 'opex_base', 'revenue', 'opex',
    'depreciation', 'sale_proceeds', 'sale_carrying', 'sale_gain', 'asset_nbv_close',
    'debt_open', 'bank_interest', 'principal_repayment', 'debt_close', 'taxable_before_losses',
    'loss_open', 'loss_expired', 'loss_used', 'loss_created', 'loss_close', 'taxable_after_losses',
    'current_tax', 'net_income', 'lp_required', 'lp_call', 'lp_distribution', 'lp_called_cumulative',
    'lp_remaining', 'cash_close', 'cumulative_net_income', 'cumulative_distributions',
    'book_equity_close', 'net_lp_cashflow', 'funding_gap', 'balance_check', 'cash_check',
    'asset_check', 'debt_check', 'loss_check')
VINTAGE_FIELDS = ('opening', 'expired', 'used', 'created', 'closing')
GROUP_FIELDS = ('new_lp_calls', 'year_end_debt', 'lp_distributions', 'net_lp_cashflow', 'asset_nbv')
RULES = (
    'One complete binary project plan applies to all scenarios. Projects are ring-fenced; no cash, tax loss, debt or collateral is transferred between them.',
    'Amounts are integer GBP pence and rates/factors integer basis points over10000. Round only each specified posting to the nearest penny, halves away from zero.',
    'At time zero buy the asset, draw rounded cost times provided LTV, and call the remaining cost from LPs. Lifetime gross LP commitment includes this opening call and is not restored by distributions.',
    'Revenue, operating expense and depreciation start in the supplied first operating FY. Posted unshocked bases grow independently each later FY; scenario factors then apply independently once per amount and FY.',
    'Depreciate original cost/life from the first operating FY, capped at remaining NBV, with an exact final life-year catchup. Life is at most20 years.',
    'Interest is rounded opening debt times effective annual BP. Level principal uses rounded original draw/maturity FY from FY1 with final maturity catchup; bullet principal is paid at maturity. There are no later bank draws.',
    'In the final FY operate and depreciate, sell the entire asset at its scenario-adjusted provided price, derecognise remaining NBV, include sale gain/loss in tax profit, and repay any remaining debt.',
    'Expire a tax loss when current FY minus origin FY exceeds3. Apply old losses oldest first to positive current profit, then create a current loss for negative profit. Interest is fully deductible; current corporate tax is paid in the same FY. No group relief, carryback or deferred tax is included.',
    'After operating receipts, sale receipts, expense, interest, principal and tax, distribute all positive cash to LPs; call for a deficiency only within remaining lifetime commitment. A residual gap is infeasible, not funding. Feasible retained cash is zero.',
    'An infeasible diagnostic path carries unpaid negative cash and remains infeasible. A feasible final state has zero cash, asset NBV and debt. Each project has its own finite commitment in each supplied scenario.',
    'NPV combines negative time-zero LP paid in and all annual net LP flows discounted by(10000/(10000+discount BP))^FY, then rounds once with halves away from zero. The objective sums individually posted S01 NPVs with no group rounding; S02/S03 are feasibility stresses.',
    'Shared limits mean opening sponsor equity, gross new annual LP calls, year-end debt principal, dated physical resources and annual region/sector asset NBV. Provided site alternatives permit at most one; a dependent requires its separately funded enabler.',
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _integer(value, minimum, maximum, label):
    require(type(value) is int and minimum <= value <= maximum, 'Invalid integer '+label)


def _keys(value, expected, label):
    require(isinstance(value, dict) and set(value) == set(expected), 'Incomplete or extra fields: '+label)


def _ids(value, expected, label):
    require(isinstance(value, list) and value == list(expected)
        and all(type(actual) is type(wanted) for actual,wanted in zip(value,expected)),
        'The complete ordered '+label+' differs')


def _annual(value, years, minimum, maximum, label):
    _keys(value, map(str, years), label)
    for year in years:
        _integer(value[str(year)], minimum, maximum, label)


def _scenario_annual(value, scenarios, years, maximum, label):
    _keys(value, scenarios, label)
    for scenario in scenarios:
        _annual(value[scenario], years, 0, maximum, label)


def load_spec(value):
    """Validate complete raw inputs; explicit small fixtures cannot be sources."""
    if isinstance(value, (str, Path)):
        def unique(pairs):
            result = {}
            for key, child in pairs:
                require(key not in result, 'Duplicate JSON key')
                result[key] = child
            return result
        def nonfinite(_):
            raise ValueError('Nonfinite JSON number')
        value = json.loads(Path(value).read_text(), object_pairs_hook=unique, parse_constant=nonfinite)
    s = deepcopy(value)
    _keys(s, ('version', 'kind', 'dimension_mode', 'fiscal_year_start', 'years', 'project_ids', 'scenario_ids',
        'resource_ids', 'region_ids', 'sector_ids', 'projects', 'scenarios', 'shared_limits',
        'exclusivity_groups', 'prerequisites', 'provenance'), 'root')
    require(type(s['version']) is int and s['version'] == 1 and s['kind'] == 'hypothetical_ringfenced_linear_capital_portfolio', 'Unknown portfolio specification')
    require(s['dimension_mode'] in ('production', 'toy'), 'An explicit dimension mode is required')
    _integer(s['fiscal_year_start'], 1900, 2200, 'fiscal year start')
    if s['dimension_mode'] == 'production':
        dimensions = (PROJECT_IDS, SCENARIO_IDS, YEARS, RESOURCE_IDS, REGION_IDS, SECTOR_IDS)
    else:
        for key, low, high in [('project_ids', 1, 4), ('scenario_ids', 1, 3), ('years', 1, 20),
            ('resource_ids', 1, 6), ('region_ids', 1, 6), ('sector_ids', 1, 8)]:
            require(isinstance(s[key], list) and low <= len(s[key]) <= high, 'Invalid toy dimensions')
        dimensions = (PROJECT_IDS[:len(s['project_ids'])], SCENARIO_IDS[:len(s['scenario_ids'])], YEARS[:len(s['years'])],
            RESOURCE_IDS[:len(s['resource_ids'])], REGION_IDS[:len(s['region_ids'])], SECTOR_IDS[:len(s['sector_ids'])])
    for key, expected in zip(('project_ids','scenario_ids','years','resource_ids','region_ids','sector_ids'), dimensions):
        _ids(s[key], expected, key)
    years, scenarios, ids = s['years'], s['scenario_ids'], s['project_ids']
    require(isinstance(s['projects'], list) and len(s['projects']) == len(ids), 'Every project is required')
    project_keys = ('id','name','region','sector','asset_cost_pence','t0_ltv_bp','operating_start_year','depreciation_years',
        'base_annual_revenue_pence','base_annual_opex_pence','revenue_growth_factor_bp','opex_growth_factor_bp',
        'bank_rate_bp','debt_policy','debt_maturity_year','tax_rate_bp','discount_rate_bp',
        'terminal_sale_proceeds_pence','lp_commitment_pence','resource_usage_units')
    for project, pid in zip(s['projects'], ids):
        _keys(project, project_keys, 'project')
        require(project['id'] == pid and type(project['name']) is str and bool(project['name'].strip()), 'Project identity differs')
        require(project['region'] in s['region_ids'] and project['sector'] in s['sector_ids'], 'Unknown region or sector')
        for field in ('asset_cost_pence','base_annual_revenue_pence','base_annual_opex_pence','terminal_sale_proceeds_pence'):
            _integer(project[field], int(field == 'asset_cost_pence'), PROJECT_MONEY_LIMIT, field)
        _integer(project['lp_commitment_pence'], 0, PORTFOLIO_MONEY_LIMIT, 'lifetime LP commitment')
        for field, low, high in [('t0_ltv_bp',0,9000),('operating_start_year',1,len(years)),('depreciation_years',1,20),
            ('revenue_growth_factor_bp',0,11000),('opex_growth_factor_bp',0,11000),('bank_rate_bp',0,5000),
            ('debt_maturity_year',1,len(years)),('tax_rate_bp',0,5000),('discount_rate_bp',0,3000)]:
            _integer(project[field], low, high, field)
        require(project['debt_policy'] in ('LEVEL_PRINCIPAL','BULLET'), 'Unknown debt policy')
        usage = project['resource_usage_units']
        _keys(usage, s['resource_ids'], 'physical resource usage')
        for resource in s['resource_ids']:
            _scenario_annual(usage[resource], scenarios, years, 10**6, 'physical resource usage')
    require(isinstance(s['scenarios'], list) and len(s['scenarios']) == len(scenarios), 'Every scenario is required')
    for scenario, sid in zip(s['scenarios'], scenarios):
        _keys(scenario, ('id','name','revenue_factors_bp','opex_factors_bp','sale_factors_bp','interest_spread_bp'), 'scenario')
        require(scenario['id'] == sid and type(scenario['name']) is str and bool(scenario['name'].strip()), 'Scenario identity differs')
        for field in ('revenue_factors_bp','opex_factors_bp','sale_factors_bp'):
            _annual(scenario[field], years, 0, 15000, field)
        _annual(scenario['interest_spread_bp'], years, -5000, 5000, 'interest spread')
        require(all(0 <= p['bank_rate_bp'] + scenario['interest_spread_bp'][str(y)] <= 5000 for p in s['projects'] for y in years), 'An effective bank rate is outside the public domain')
    limits = s['shared_limits']
    _keys(limits, ('initial_sponsor_equity_pence','annual_new_lp_pence','annual_debt_close_pence',
        'resource_capacity_units','region_exposure_pence','sector_exposure_pence'), 'shared limits')
    _integer(limits['initial_sponsor_equity_pence'], 0, PORTFOLIO_MONEY_LIMIT, 'opening equity budget')
    for field in ('annual_new_lp_pence','annual_debt_close_pence'):
        _scenario_annual(limits[field], scenarios, years, PORTFOLIO_MONEY_LIMIT, field)
    _keys(limits['resource_capacity_units'], s['resource_ids'], 'resource capacities')
    for resource in s['resource_ids']:
        _scenario_annual(limits['resource_capacity_units'][resource], scenarios, years, 10**9, 'resource capacity')
    for field, labels in [('region_exposure_pence',s['region_ids']),('sector_exposure_pence',s['sector_ids'])]:
        _keys(limits[field], labels, field)
        for label in labels:
            _annual(limits[field][label], years, 0, PORTFOLIO_MONEY_LIMIT, field)
    groups, seen, grouped = s['exclusivity_groups'], set(), set()
    require(isinstance(groups, list) and (len(groups) == 40 if s['dimension_mode'] == 'production' else len(groups) <= 2), 'The fixed site-group count differs')
    for group in groups:
        _keys(group, ('id','description','project_ids'), 'site alternatives')
        require(type(group['id']) is str and group['id'] and group['id'] not in seen and type(group['description']) is str and bool(group['description'].strip()), 'Site identity or business description differs')
        seen.add(group['id'])
        members = group['project_ids']
        require(isinstance(members, list) and 2 <= len(members) <= 3 and len(set(members)) == len(members)
            and set(members) <= set(ids) and not set(members) & grouped, 'Site alternatives overlap or reference unknown projects')
        grouped.update(members)
    edges = s['prerequisites']
    require(isinstance(edges, list) and (len(edges) == 80 if s['dimension_mode'] == 'production' else len(edges) <= 6), 'The fixed prerequisite count differs')
    successors = {pid: [] for pid in ids};indegree = {pid:0 for pid in ids};seen_edges=set();edge_ids=set()
    for edge in edges:
        _keys(edge, ('id','dependent','prerequisite','business_reason'), 'prerequisite')
        pair = edge['prerequisite'],edge['dependent']
        require(all(pid in ids for pid in pair) and pair[0] != pair[1] and pair not in seen_edges
            and type(edge['id']) is str and edge['id'] and edge['id'] not in edge_ids
            and type(edge['business_reason']) is str and bool(edge['business_reason'].strip()), 'Invalid prerequisite business relationship')
        seen_edges.add(pair);edge_ids.add(edge['id']);successors[pair[0]].append(pair[1]);indegree[pair[1]]+=1
    queue = [pid for pid in ids if indegree[pid] == 0];count=0
    while queue:
        pid=queue.pop();count+=1
        for child in successors[pid]:
            indegree[child]-=1
            if indegree[child] == 0:queue.append(child)
    require(count == len(ids), 'Prerequisites must form an acyclic graph')
    provenance=s['provenance']
    _keys(provenance, ('hypothetical','description','ancestor_sha256'), 'provenance')
    require(provenance['hypothetical'] is True and type(provenance['description']) is str and provenance['description'].strip()
        and isinstance(provenance['ancestor_sha256'], list) and all(type(h) is str and len(h) == 64 and all(c in '0123456789abcdef' for c in h) for h in provenance['ancestor_sha256']), 'Hypothetical lineage must be explicit')
    return s


def validate_plan(specification, plan):
    require(isinstance(plan, dict) and set(plan) == set(specification['project_ids'])
        and all(type(value) is int and value in (0,1) for value in plan.values()), 'A complete integer binary plan is required')
    return {pid:plan[pid] for pid in specification['project_ids']}
