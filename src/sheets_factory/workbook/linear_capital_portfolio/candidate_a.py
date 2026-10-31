"""Independent exact-rational financial forward A; no optimization or workbook I/O.

Only the public schema is shared with forward B. Every posting and accounting
bridge below is implemented here; no ledger, coefficient or posting helper is
imported. Fraction represents discounting exactly until the single final round.
"""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json

from .spec import (BP, EXACT_LIMIT, T0_FIELDS, ANNUAL_FIELDS, VINTAGE_FIELDS,
                   GROUP_FIELDS, load_spec, validate_plan)


def _canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _round(value):
    """Round an exact rational to integer pence, ties away from zero."""
    value = Fraction(value)
    whole, remainder = divmod(abs(value.numerator), value.denominator)
    return (-1 if value < 0 else 1) * (whole + int(2 * remainder >= value.denominator))


class _IntegerScope:
    """Check every posted integer, amount×BP product and additive intermediate."""
    def __init__(self):
        self.maximum = 0
        self.checked = 0

    def integer(self, value):
        if type(value) is not int or abs(value) >= EXACT_LIMIT:
            raise ValueError('A financial integer or intermediate is outside the exact arithmetic domain')
        self.checked += 1
        self.maximum = max(self.maximum, abs(value))
        return value

    def add(self, *values):
        total = 0
        for value in values:
            total = self.integer(total + self.integer(value))
        return total

    def total(self, values):
        total = 0
        for value in values:
            total = self.add(total, value)
        return total

    def posting(self, numerator, denominator=1):
        numerator, denominator = self.integer(numerator), self.integer(denominator)
        if denominator <= 0:
            raise ValueError('A posting denominator must be positive')
        return self.integer(_round(Fraction(numerator, denominator)))

    def factor(self, amount, factor):
        return self.posting(self.integer(self.integer(amount) * self.integer(factor)), BP)

    def report(self):
        return {'passed': True, 'exclusive_integer_limit': str(EXACT_LIMIT),
            'checked_integer_operations': self.checked, 'maximum_absolute_integer': self.maximum,
            'NPV_discount_fraction_uses_exact_arithmetic_not_binary64': True}


def _project(public, project, scenario):
    check = _IntegerScope()
    cost = check.integer(project['asset_cost_pence'])
    bank = check.factor(cost, project['t0_ltv_bp'])
    commitment = check.integer(project['lp_commitment_pence'])
    opening_required = check.add(cost, -bank)
    called = min(opening_required, commitment)
    remaining = check.add(commitment, -called)
    cash = check.add(called, -opening_required)
    gap = max(0, -cash)
    asset, debt, equity = cost, bank, called
    t0 = dict(asset_cost=cost, bank_draw=bank, lp_required=opening_required,
        lp_call=called, lp_remaining=remaining, funding_gap=gap, cash_close=cash,
        asset_nbv_close=asset, debt_close=debt, book_equity_close=equity,
        balance_check=check.add(asset, cash, -debt, -equity))
    if set(t0) != set(T0_FIELDS):
        raise ValueError('Forward A time-zero field coverage differs from the public schema')
    for value in t0.values(): check.integer(value)
    feasible = gap == 0
    revenue_base = opex_base = income_total = distributions_total = 0
    loss_balances = {}
    annual, vintage_events = [], []
    original_principal_posting = check.posting(bank, project['debt_maturity_year'])
    regular_depreciation = check.posting(cost, project['depreciation_years'])
    discount = Fraction(BP, check.add(BP, project['discount_rate_bp']))
    discounted_flows = Fraction(-called)
    last = public['years'][-1]

    for year in public['years']:
        key = str(year)
        fiscal = public['fiscal_year_start'] + year - 1
        opening_cash, opening_asset, opening_debt = cash, asset, debt
        active = year >= project['operating_start_year']
        if year == project['operating_start_year']:
            revenue_base, opex_base = project['base_annual_revenue_pence'], project['base_annual_opex_pence']
        elif active:
            revenue_base = check.factor(revenue_base, project['revenue_growth_factor_bp'])
            opex_base = check.factor(opex_base, project['opex_growth_factor_bp'])
        revenue = check.factor(revenue_base, scenario['revenue_factors_bp'][key])
        opex = check.factor(opex_base, scenario['opex_factors_bp'][key])
        age = year - project['operating_start_year'] + 1
        depreciation = (min(opening_asset, regular_depreciation) if 0 < age < project['depreciation_years']
            else opening_asset if age == project['depreciation_years'] else 0)
        after_depreciation = check.add(opening_asset, -depreciation)
        sale = check.factor(project['terminal_sale_proceeds_pence'], scenario['sale_factors_bp'][key]) if year == last else 0
        carrying = after_depreciation if year == last else 0
        gain = check.add(sale, -carrying)
        asset = check.add(after_depreciation, -carrying)
        effective_rate = check.add(project['bank_rate_bp'], scenario['interest_spread_bp'][key])
        interest = check.factor(opening_debt, effective_rate)
        principal = (opening_debt if year >= project['debt_maturity_year'] or year == last else
            min(opening_debt, original_principal_posting) if project['debt_policy'] == 'LEVEL_PRINCIPAL' else 0)
        debt = check.add(opening_debt, -principal)
        profit = check.add(revenue, -opex, -depreciation, -interest, gain)

        losses_open = check.total(loss_balances.values())
        losses_expired = losses_used = 0
        taxable = max(0, profit)
        next_losses = {}
        for origin, opening in sorted(loss_balances.items()):
            expired = opening if year - origin > 3 else 0
            available = check.add(opening, -expired)
            used = min(available, taxable)
            closing = check.add(available, -used)
            taxable = check.add(taxable, -used)
            losses_expired = check.add(losses_expired, expired)
            losses_used = check.add(losses_used, used)
            if closing: next_losses[origin] = closing
            vintage_events.append({'year':year,'fiscal_year':fiscal,'origin_year':origin,
                'opening':opening,'expired':expired,'used':used,'created':0,'closing':closing})
        created = max(0, -profit)
        if created:
            next_losses[year] = created
            vintage_events.append({'year':year,'fiscal_year':fiscal,'origin_year':year,
                'opening':0,'expired':0,'used':0,'created':created,'closing':created})
        loss_balances = next_losses
        losses_close = check.total(loss_balances.values())
        tax = check.factor(taxable, project['tax_rate_bp'])
        income = check.add(profit, -tax)
        income_total = check.add(income_total, income)

        cash_before_LP = check.add(opening_cash, revenue, sale, -opex, -interest, -principal, -tax)
        required = max(0, -cash_before_LP)
        call = min(required, remaining)
        distribution = max(0, cash_before_LP)
        called = check.add(called, call)
        remaining = check.add(commitment, -called)
        distributions_total = check.add(distributions_total, distribution)
        cash = check.add(cash_before_LP, call, -distribution)
        gap = max(0, -cash)
        equity = check.add(called, income_total, -distributions_total)
        net_flow = check.add(distribution, -call)
        feasible = feasible and gap == 0 and called <= commitment
        if year == last: feasible = feasible and asset == debt == cash == 0
        row = dict(cash_open=opening_cash, asset_nbv_open=opening_asset,
            revenue_base=revenue_base, opex_base=opex_base, revenue=revenue, opex=opex,
            depreciation=depreciation, sale_proceeds=sale, sale_carrying=carrying,
            sale_gain=gain, asset_nbv_close=asset, debt_open=opening_debt, bank_interest=interest,
            principal_repayment=principal, debt_close=debt, taxable_before_losses=profit,
            loss_open=losses_open, loss_expired=losses_expired, loss_used=losses_used,
            loss_created=created, loss_close=losses_close, taxable_after_losses=taxable,
            current_tax=tax, net_income=income, lp_required=required, lp_call=call,
            lp_distribution=distribution, lp_called_cumulative=called, lp_remaining=remaining,
            cash_close=cash, cumulative_net_income=income_total,
            cumulative_distributions=distributions_total, book_equity_close=equity,
            net_lp_cashflow=net_flow, funding_gap=gap,
            balance_check=check.add(asset, cash, -debt, -equity),
            cash_check=check.add(cash, -opening_cash, -revenue, -sale, opex, interest, principal, tax, -call, distribution),
            asset_check=check.add(opening_asset, -depreciation, -carrying, -asset),
            debt_check=check.add(opening_debt, -principal, -debt),
            loss_check=check.add(losses_close, -losses_open, losses_expired, losses_used, -created))
        if set(row) != set(ANNUAL_FIELDS):
            raise ValueError('Forward A annual field coverage differs from the public schema')
        for value in row.values(): check.integer(value)
        if any(row[field] != 0 for field in ('balance_check','cash_check','asset_check','debt_check','loss_check')):
            raise ValueError('Forward A accounting bridge failed')
        annual.append({'year':year,'fiscal_year':fiscal,**row,'operating_active':int(active),'feasible':int(feasible)})
        discounted_flows += net_flow * discount**year

    for event in vintage_events:
        if set(event) != {'year','fiscal_year','origin_year',*VINTAGE_FIELDS}:
            raise ValueError('Forward A vintage field coverage differs from the public schema')
        for field in VINTAGE_FIELDS: check.integer(event[field])
    npv = check.integer(_round(discounted_flows)) if feasible else None
    return {'project_id':project['id'],'scenario_id':scenario['id'],'t0':t0,'annual':annual,
        'tax_vintages':vintage_events,'feasible':bool(feasible),'npv_pence':npv,
        'npv_exact':{'numerator':str(discounted_flows.numerator),'denominator':str(discounted_flows.denominator)},
        'arithmetic_safety':check.report()}


def simulate_project(specification, project_id, scenario_id):
    public = load_spec(specification)
    if project_id not in public['project_ids'] or scenario_id not in public['scenario_ids']:
        raise ValueError('A provided project and scenario identity are required')
    return _project(public, next(p for p in public['projects'] if p['id'] == project_id),
        next(s for s in public['scenarios'] if s['id'] == scenario_id))


def _universe(public):
    projects = {p['id']:{'scenarios':{s['id']:_project(public,p,s) for s in public['scenarios']}}
        for p in public['projects']}
    return {'kind':'linear_capital_portfolio_standalone_universe','version':1,
        'specification_sha256':_canonical(public),'project_order':list(public['project_ids']),
        'scenario_ids':list(public['scenario_ids']),'years':list(public['years']),'projects':projects,
        'all_standalone_feasible':all(r['feasible'] for p in projects.values() for r in p['scenarios'].values()),
        'financial_implementation':'independent_Fraction_forward_A','optimization_performed':False,
        'source_or_difficulty_certified':False}


def simulate_universe(specification):
    """Evaluate every provided candidate; retain all infeasible diagnostics."""
    return _universe(load_spec(specification))


def simulate(specification, plan):
    """Evaluate a complete provided binary plan and public limits; never search."""
    public = load_spec(specification)
    choices = validate_plan(public,plan)
    universe = _universe(public)
    check = _IntegerScope()
    selected = [p for p in public['projects'] if choices[p['id']]]
    constraints, scenario_groups = [], {}
    limits = public['shared_limits']
    def total(values): return check.total(values)
    def constraint(identity, family, lhs, limit, scenario=None, year=None):
        lhs, limit = check.integer(lhs),check.integer(limit)
        constraints.append({'id':identity,'family':family,'scenario_id':scenario,'year':year,
            'lhs':lhs,'limit':limit,'slack':check.add(limit,-lhs),'passed':lhs <= limit})
    base_scenario = public['scenario_ids'][0]
    opening = total(universe['projects'][p['id']]['scenarios'][base_scenario]['t0']['lp_call'] for p in selected)
    constraint('initial_sponsor_equity','initial_sponsor_equity',opening,limits['initial_sponsor_equity_pence'])
    for sid in public['scenario_ids']:
        group_rows = []
        for index, year in enumerate(public['years']):
            rows = [universe['projects'][p['id']]['scenarios'][sid]['annual'][index] for p in selected]
            fields = dict(new_lp_calls=total(r['lp_call'] for r in rows),
                year_end_debt=total(r['debt_close'] for r in rows),lp_distributions=total(r['lp_distribution'] for r in rows),
                net_lp_cashflow=total(r['net_lp_cashflow'] for r in rows),asset_nbv=total(r['asset_nbv_close'] for r in rows))
            if set(fields) != set(GROUP_FIELDS): raise ValueError('Forward A group field coverage differs')
            group_rows.append({'year':year,'fiscal_year':public['fiscal_year_start']+year-1,**fields})
            constraint(f'annual_new_lp:{sid}:{year}','annual_new_lp',fields['new_lp_calls'],limits['annual_new_lp_pence'][sid][str(year)],sid,year)
            constraint(f'annual_debt_close:{sid}:{year}','annual_debt_close',fields['year_end_debt'],limits['annual_debt_close_pence'][sid][str(year)],sid,year)
            for resource in public['resource_ids']:
                use = total(p['resource_usage_units'][resource][sid][str(year)] for p in selected)
                constraint(f'resource:{resource}:{sid}:{year}','resource',use,limits['resource_capacity_units'][resource][sid][str(year)],sid,year)
        scenario_groups[sid] = {'annual':group_rows}
    for index,year in enumerate(public['years']):
        for family, labels, limit_field, project_field in (
            ('region_exposure',public['region_ids'],'region_exposure_pence','region'),
            ('sector_exposure',public['sector_ids'],'sector_exposure_pence','sector')):
            for label in labels:
                use=total(universe['projects'][p['id']]['scenarios'][base_scenario]['annual'][index]['asset_nbv_close']
                    for p in selected if p[project_field] == label)
                constraint(f'{family}:{label}:{year}',family,use,limits[limit_field][label][str(year)],None,year)
    for group in public['exclusivity_groups']:
        constraint('exclusivity:'+group['id'],'exclusivity',total(choices[pid] for pid in group['project_ids']),1)
    for edge in public['prerequisites']:
        constraint('prerequisite:'+edge['id'],'prerequisite',check.add(choices[edge['dependent']],-choices[edge['prerequisite']]),0)
    selected_feasible = all(universe['projects'][p['id']]['scenarios'][sid]['feasible']
        for p in selected for sid in public['scenario_ids'])
    feasible = selected_feasible and all(row['passed'] for row in constraints)
    objective = total(universe['projects'][p['id']]['scenarios'][base_scenario]['npv_pence'] for p in selected) if feasible else None
    return {**universe,'plan':choices,'group':{'scenarios':scenario_groups},'constraints':constraints,
        'selected_standalone_feasible':selected_feasible,'feasible':bool(feasible),'objective_pence':objective,
        'portfolio_arithmetic_safety':check.report()}
