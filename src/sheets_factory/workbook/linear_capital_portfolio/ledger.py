"""Independent Decimal forward ledger; no optimizer or other finance imports."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, localcontext

from .spec import (ANNUAL_FIELDS, BP, EXACT_LIMIT, GROUP_FIELDS, T0_FIELDS,
    VINTAGE_FIELDS, canonical_sha256, load_spec, require, validate_plan)


class _Bounds:
    def __init__(self):
        self.product_max = self.sum_max = self.posting_max = 0

    def integer(self, value):
        require(type(value) is int and abs(value) < EXACT_LIMIT, 'A posted amount exceeds the exact integer envelope')
        self.posting_max = max(self.posting_max, abs(value))
        return value

    def sum(self, *values):
        require(all(type(v) is int for v in values), 'A financial sum contains a noninteger')
        absolute = sum(abs(v) for v in values)
        self.sum_max = max(self.sum_max, absolute)
        require(absolute < EXACT_LIMIT, 'A financial/group sum exceeds the exact integer envelope')
        return self.integer(sum(values))

    def divide(self, numerator, denominator):
        require(type(numerator) is int and type(denominator) is int and denominator > 0
            and abs(numerator) < EXACT_LIMIT, 'A rounded posting numerator exceeds the exact integer envelope')
        with localcontext() as context:
            context.prec = 160
            return self.integer(int((Decimal(numerator) / Decimal(denominator)).to_integral_value(rounding=ROUND_HALF_UP)))

    def product(self, amount, factor):
        require(type(amount) is int and type(factor) is int, 'A BP posting requires exact integers')
        product = amount * factor
        self.product_max = max(self.product_max, abs(product))
        require(abs(product) < EXACT_LIMIT, 'An amount times BP exceeds the exact integer envelope')
        return self.divide(product, BP)

    def result(self):
        return {'maximum_absolute_amount_times_bp':self.product_max,
            'maximum_sum_of_absolute_terms':self.sum_max,'maximum_absolute_posted_value':self.posting_max,
            'all_postings_products_and_sums_below_2_to_53':True}


def _npv(initial_call, net_flows, discount_bp):
    """Decimal valuation, with an exact local integer check of final half ties.

    This check uses only this ledger's own net flows. It imports neither A nor
    Fraction and is not another candidate financial posting implementation.
    """
    with localcontext() as context:
        context.prec = 160
        base = Decimal(BP) / Decimal(BP + discount_bp)
        value = -Decimal(initial_call)
        for year, amount in enumerate(net_flows, 1):
            value += Decimal(amount) * base**year
        # The complete exact numerator is valuation metadata, not a worksheet
        # money/BP posting or a shared financial-flow helper. It resolves exact
        # half ties that a repeating Decimal sum can approach from either side.
        n = len(net_flows);d = BP + discount_bp;denominator = d**n
        numerator = -initial_call * denominator
        for year, amount in enumerate(net_flows, 1):
            numerator += amount * BP**year * d**(n-year)
        whole, remainder = divmod(abs(numerator), denominator)
        exact_posted = (-1 if numerator < 0 else 1) * (whole + int(2*remainder >= denominator))
        if 2*remainder == denominator:
            value = Decimal(-1 if numerator < 0 else 1) * (Decimal(whole) + Decimal('0.5'))
        posted = int(value.to_integral_value(rounding=ROUND_HALF_UP))
        require(posted == exact_posted, 'Decimal NPV precision is insufficient for the final posted penny')
        return posted, str(value)


def _project(s, project, scenario):
    bounds = _Bounds();years = s['years'];last = years[-1]
    cost = project['asset_cost_pence'];commitment = project['lp_commitment_pence']
    original_debt = bounds.product(cost, project['t0_ltv_bp'])
    initial_required = bounds.sum(cost, -original_debt)
    initial_call = min(initial_required, commitment)
    cash = bounds.sum(original_debt, initial_call, -cost)
    debt = original_debt;nbv = cost;called = initial_call
    ever_gap = cash < 0
    t0 = {'asset_cost':cost,'bank_draw':original_debt,'lp_required':initial_required,'lp_call':initial_call,
        'lp_remaining':bounds.sum(commitment,-called),'funding_gap':max(0,-cash),'cash_close':cash,
        'asset_nbv_close':nbv,'debt_close':debt,'book_equity_close':bounds.sum(nbv,cash,-debt),
        'balance_check':bounds.sum(nbv,cash,-debt,-called)}
    require(set(t0) == set(T0_FIELDS) and t0['balance_check'] == 0, 'Time-zero acquisition does not balance')
    instalment = bounds.divide(original_debt, project['debt_maturity_year'])
    depreciation_charge = bounds.divide(cost, project['depreciation_years'])
    losses = {};annual = [];vintages = [];cumulative_profit = cumulative_distributions = 0
    revenue_base = opex_base = 0
    for year in years:
        calendar_year = s['fiscal_year_start'] + year - 1
        cash_open,debt_open,nbv_open = cash,debt,nbv
        active = year >= project['operating_start_year']
        if year == project['operating_start_year']:
            revenue_base = project['base_annual_revenue_pence'];opex_base = project['base_annual_opex_pence']
        elif active:
            revenue_base = bounds.product(revenue_base, project['revenue_growth_factor_bp'])
            opex_base = bounds.product(opex_base, project['opex_growth_factor_bp'])
        revenue = bounds.product(revenue_base, scenario['revenue_factors_bp'][str(year)])
        opex = bounds.product(opex_base, scenario['opex_factors_bp'][str(year)])
        age = year - project['operating_start_year'] + 1
        depreciation = (nbv if age >= project['depreciation_years'] else min(nbv,depreciation_charge)) if active else 0
        nbv = bounds.sum(nbv,-depreciation)
        interest = bounds.product(debt_open, bounds.sum(project['bank_rate_bp'],scenario['interest_spread_bp'][str(year)]))
        if year >= project['debt_maturity_year'] or year == last:
            principal = debt
        elif project['debt_policy'] == 'LEVEL_PRINCIPAL':
            principal = min(debt, instalment)
        else:
            principal = 0
        debt = bounds.sum(debt,-principal)
        sale = bounds.product(project['terminal_sale_proceeds_pence'],scenario['sale_factors_bp'][str(year)]) if year == last else 0
        carrying = nbv if year == last else 0
        nbv = bounds.sum(nbv,-carrying)
        gain = bounds.sum(sale,-carrying)
        profit = bounds.sum(revenue,-opex,-depreciation,-interest,gain)
        opening_loss = bounds.sum(*losses.values())
        events = {origin:{'origin_year':origin,'opening':amount,'expired':0,'used':0,'created':0,'closing':amount}
                  for origin,amount in losses.items()}
        expired = used = 0
        for origin in sorted(tuple(losses)):
            if year-origin > 3:
                expired = bounds.sum(expired,losses[origin]);events[origin]['expired']=losses[origin]
                events[origin]['closing']=0;del losses[origin]
        taxable = max(0,profit)
        for origin in sorted(tuple(losses)):
            take = min(taxable,losses[origin]);taxable -= take
            used = bounds.sum(used,take);losses[origin] -= take;events[origin]['used']=take
            events[origin]['closing']=losses[origin]
            if losses[origin] == 0:del losses[origin]
        created = max(0,-profit)
        if created:
            losses[year] = created;events[year]={'origin_year':year,'opening':0,'expired':0,'used':0,'created':created,'closing':created}
        closing_loss = bounds.sum(*losses.values())
        current_tax = bounds.product(taxable,project['tax_rate_bp'])
        net_income = bounds.sum(profit,-current_tax)
        available = bounds.sum(cash_open,revenue,-opex,sale,-interest,-principal,-current_tax)
        required = max(0,-available)
        actual_call = min(required,bounds.sum(commitment,-called))
        distribution = max(0,available)
        called = bounds.sum(called,actual_call)
        cash = bounds.sum(available,actual_call,-distribution)
        gap = max(0,-cash);ever_gap = ever_gap or gap>0
        cumulative_profit = bounds.sum(cumulative_profit,net_income)
        cumulative_distributions = bounds.sum(cumulative_distributions,distribution)
        equity = bounds.sum(nbv,cash,-debt)
        row = {'year':year,'fiscal_year':calendar_year,'operating_active':int(active),'feasible':int(not ever_gap),
            'cash_open':cash_open,'asset_nbv_open':nbv_open,'revenue_base':revenue_base,'opex_base':opex_base,
            'revenue':revenue,'opex':opex,'depreciation':depreciation,'sale_proceeds':sale,'sale_carrying':carrying,
            'sale_gain':gain,'asset_nbv_close':nbv,'debt_open':debt_open,'bank_interest':interest,
            'principal_repayment':principal,'debt_close':debt,'taxable_before_losses':profit,
            'loss_open':opening_loss,'loss_expired':expired,'loss_used':used,'loss_created':created,
            'loss_close':closing_loss,'taxable_after_losses':taxable,'current_tax':current_tax,'net_income':net_income,
            'lp_required':required,'lp_call':actual_call,'lp_distribution':distribution,'lp_called_cumulative':called,
            'lp_remaining':bounds.sum(commitment,-called),'cash_close':cash,'cumulative_net_income':cumulative_profit,
            'cumulative_distributions':cumulative_distributions,'book_equity_close':equity,
            'net_lp_cashflow':bounds.sum(distribution,-actual_call),'funding_gap':gap,
            'balance_check':bounds.sum(equity,-called,-cumulative_profit,cumulative_distributions),
            'cash_check':bounds.sum(cash_open,revenue,-opex,sale,-interest,-principal,-current_tax,actual_call,-distribution,-cash),
            'asset_check':bounds.sum(nbv_open,-depreciation,-carrying,-nbv),
            'debt_check':bounds.sum(debt_open,-principal,-debt),
            'loss_check':bounds.sum(opening_loss,-expired,-used,created,-closing_loss)}
        require(set(row) == set(ANNUAL_FIELDS)|{'year','fiscal_year','operating_active','feasible'}, 'A financial field is missing')
        require(all(type(v) is int for v in row.values()) and all(row[key] == 0 for key in
            ('balance_check','cash_check','asset_check','debt_check','loss_check')), 'An independent financial bridge failed')
        for event in events.values():
            require(all(type(event[key]) is int and event[key] >= 0 for key in VINTAGE_FIELDS), 'Invalid sparse FIFO event')
            if any(event[key] for key in VINTAGE_FIELDS):
                vintages.append({'year':year,'fiscal_year':calendar_year,**event})
        annual.append(row)
    feasible = not ever_gap and called <= commitment and cash == debt == nbv == 0
    npv, decimal = _npv(initial_call,[r['net_lp_cashflow'] for r in annual],project['discount_rate_bp']) if feasible else (None,None)
    return {'project_id':project['id'],'scenario_id':scenario['id'],'t0':t0,'annual':annual,
        'tax_vintages':vintages,'feasible':feasible,'npv_pence':npv,'npv_unrounded_decimal':decimal,
        'arithmetic_bounds':bounds.result()}


def simulate_project(specification, project_id, scenario_id):
    s = load_spec(specification)
    require(project_id in s['project_ids'] and scenario_id in s['scenario_ids'], 'Unknown project or scenario')
    return _project(s,next(p for p in s['projects'] if p['id']==project_id),next(c for c in s['scenarios'] if c['id']==scenario_id))


def _universe(s):
    projects = {p['id']:{'scenarios':{c['id']:_project(s,p,c) for c in s['scenarios']}} for p in s['projects']}
    return {'kind':'linear_capital_portfolio_standalone_universe','version':1,
        'specification_sha256':canonical_sha256(s),'project_order':list(s['project_ids']),
        'scenario_ids':list(s['scenario_ids']),'years':list(s['years']),'projects':projects,
        'all_standalone_feasible':all(c['feasible'] for p in projects.values() for c in p['scenarios'].values()),
        'financial_implementation':'Decimal','optimization_performed':False,'source_or_difficulty_certified':False}


def simulate_universe(specification):
    return _universe(load_spec(specification))


def simulate(specification, plan):
    """Forward every candidate and check one provided common plan; never search."""
    s=load_spec(specification);plan=validate_plan(s,plan);result=_universe(s);bounds=_Bounds()
    selected=[p for p in s['projects'] if plan[p['id']]];limits=s['shared_limits'];checks=[];group={}
    def check(name,family,scenario,year,lhs,limit):
        bounds.integer(lhs);bounds.integer(limit)
        checks.append({'id':name,'family':family,'scenario_id':scenario,'year':year,'lhs':lhs,
            'limit':limit,'slack':bounds.sum(limit,-lhs),'passed':lhs<=limit})
    initial = bounds.sum(*(result['projects'][p['id']]['scenarios']['S01']['t0']['lp_call'] for p in selected))
    check('initial_sponsor_equity','initial_sponsor_equity',None,None,initial,limits['initial_sponsor_equity_pence'])
    for sid in s['scenario_ids']:
        rows=[]
        for year in s['years']:
            annual=[result['projects'][p['id']]['scenarios'][sid]['annual'][year-1] for p in selected]
            row={'year':year,'fiscal_year':s['fiscal_year_start']+year-1,
                **{key:bounds.sum(*(r[source] for r in annual)) for key,source in
                    [('new_lp_calls','lp_call'),('year_end_debt','debt_close'),('lp_distributions','lp_distribution'),
                     ('net_lp_cashflow','net_lp_cashflow'),('asset_nbv','asset_nbv_close')]}}
            require(set(row)==set(GROUP_FIELDS)|{'year','fiscal_year'}, 'A group field is missing')
            rows.append(row)
            check(f'annual_new_lp:{sid}:{year}','annual_new_lp',sid,year,row['new_lp_calls'],limits['annual_new_lp_pence'][sid][str(year)])
            check(f'annual_debt_close:{sid}:{year}','annual_debt_close',sid,year,row['year_end_debt'],limits['annual_debt_close_pence'][sid][str(year)])
            for resource in s['resource_ids']:
                usage=bounds.sum(*(p['resource_usage_units'][resource][sid][str(year)] for p in selected))
                check(f'resource:{resource}:{sid}:{year}','resource',sid,year,usage,limits['resource_capacity_units'][resource][sid][str(year)])
        group[sid]={'annual':rows}
    for label,limit_name in [('region','region_exposure_pence'),('sector','sector_exposure_pence')]:
        for category in s[label+'_ids']:
            for year in s['years']:
                exposure=bounds.sum(*(result['projects'][p['id']]['scenarios']['S01']['annual'][year-1]['asset_nbv_close'] for p in selected if p[label]==category))
                check(f'{label}_exposure:{category}:{year}',label+'_exposure',None,year,exposure,limits[limit_name][category][str(year)])
    for alternatives in s['exclusivity_groups']:
        check('exclusivity:'+alternatives['id'],'exclusivity',None,None,sum(plan[pid] for pid in alternatives['project_ids']),1)
    for edge in s['prerequisites']:
        check('prerequisite:'+edge['id'],'prerequisite',None,None,plan[edge['dependent']]-plan[edge['prerequisite']],0)
    feasible=all(check['passed'] for check in checks) and all(result['projects'][p['id']]['scenarios'][sid]['feasible'] for p in selected for sid in s['scenario_ids'])
    objective=bounds.sum(*(result['projects'][p['id']]['scenarios']['S01']['npv_pence'] for p in selected)) if feasible else None
    result.update(plan=plan,group={'scenarios':group},constraints=checks,feasible=feasible,objective_pence=objective,
        group_arithmetic_bounds=bounds.result(),unselected_project_flows_zero_in_group=True,
        objective_policy='sum_individually_posted_S01_NPV_no_group_rounding')
    return result
