"""Independent high-precision contraction oracle; never reads spreadsheet formulas."""
from decimal import Decimal, ROUND_HALF_UP, localcontext

from . import spec


def display(value):
    with localcontext() as context:
        context.prec = 100
        return format(Decimal(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP), '.2f')


def _fixed_point(base, ownership, rates, losses):
    count = len(base); zero = Decimal(0)
    modulus = max(sum(row, zero) for row in ownership)
    current = [zero]*count
    for iteration in range(1, 10001):
        equity = [sum((ownership[i][j]*current[j] for j in range(count)), zero) for i in range(count)]
        pretax = [base[i]+equity[i] for i in range(count)]
        tax = [rates[i]*max(zero, pretax[i]-losses[i]) for i in range(count)]
        following = [pretax[i]-tax[i] for i in range(count)]
        step = max(abs(following[i]-current[i]) for i in range(count))
        current = following
        if step <= Decimal('1e-60'): break
    else: raise ValueError('The bounded contraction did not converge')
    equity = [sum((ownership[i][j]*current[j] for j in range(count)), zero) for i in range(count)]
    pretax = [base[i]+equity[i] for i in range(count)]
    taxable = [max(zero, pretax[i]-losses[i]) for i in range(count)]
    tax = [rates[i]*taxable[i] for i in range(count)]
    residual = max(abs(pretax[i]-tax[i]-current[i]) for i in range(count))
    return {'equity':equity, 'pretax':pretax, 'taxable':taxable, 'tax':tax, 'net':current,
        'loss':[max(zero, losses[i]-pretax[i]) for i in range(count)],
        'solver':{'method':'independent_Decimal_contraction','iterations':iteration,
            'after_tax_scalar_lipschitz_bound':'1','contraction_modulus':modulus,
            'mapping_residual':residual,'fixed_point_error_bound_given_prior_state':residual/(1-modulus)+Decimal('1e-70'),
            'internal_money_rounding':False,'arithmetic_precision':100}}


def solve(public):
    public = spec.validate(public)
    with localcontext() as context:
        context.prec = 100
        zero = Decimal(0); entities = public['entities']; ids = [row['id'] for row in entities]
        h = [[Decimal(v) for v in row] for row in public['ownership']]
        tax_rates = [Decimal(row['tax_rate']) for row in entities]
        interest = [Decimal(row['debt'])*Decimal(row['annual_interest_rate'])/4 for row in entities]
        scenarios = []
        for scenario in public['scenarios']:
            losses = [Decimal(row['opening_loss']) for row in entities]
            cash = [Decimal(row['opening_cash']) for row in entities]
            ppe = [Decimal(row['opening_ppe']) for row in entities]
            investments = [Decimal(row['opening_investment']) for row in entities]
            retained = [Decimal(row['opening_retained']) for row in entities]
            periods = []
            for quarter, label in enumerate(public['periods']):
                inputs = [{key:Decimal(value) for key,value in scenario['inputs'][eid][quarter].items()} for eid in ids]
                operating = [row['revenue']-row['cash_opex']-row['depreciation'] for row in inputs]
                base = [operating[i]-interest[i] for i in range(len(ids))]
                fixed = _fixed_point(base, h, tax_rates, losses)
                result = {}
                for i,eid in enumerate(ids):
                    given = inputs[i]; ni = fixed['net'][i]; equity = fixed['equity'][i]
                    cfo = ni-equity+given['depreciation']
                    closed_cash = cash[i]+cfo-given['capex']; closed_ppe = ppe[i]+given['capex']-given['depreciation']
                    closed_investment = investments[i]+equity; closed_retained = retained[i]+ni
                    debt = Decimal(entities[i]['debt']); capital = Decimal(entities[i]['paid_in_capital'])
                    assets = closed_cash+closed_ppe+closed_investment
                    claims = debt+capital+closed_retained
                    spec.require(min(closed_cash,closed_ppe,closed_investment) >= 0, 'A supplied case exhausts cash, PPE or investment carrying value')
                    row = {**given, 'interest':interest[i], 'operating_profit':operating[i], 'standalone_pretax':base[i],
                        'equity_income':equity, 'pretax_profit':fixed['pretax'][i], 'opening_loss':losses[i],
                        'taxable_profit':fixed['taxable'][i], 'current_tax':fixed['tax'][i], 'net_income':ni,
                        'closing_loss':fixed['loss'][i], 'opening_cash':cash[i], 'operating_cashflow':cfo,
                        'closing_cash':closed_cash, 'opening_ppe':ppe[i], 'closing_ppe':closed_ppe,
                        'opening_investment':investments[i], 'closing_investment':closed_investment,
                        'opening_retained':retained[i], 'closing_retained':closed_retained,
                        'paid_in_capital':capital, 'debt':debt, 'assets':assets, 'liabilities_and_equity':claims,
                        'balance_residual':assets-claims}
                    spec.require(set(row) == set(spec.ENTITY_METRICS), 'Incomplete Decimal entity statement')
                    result[eid] = row
                def total(key): return sum((row[key] for row in result.values()), zero)
                group = {key:total(key) for key in ('revenue','cash_opex','depreciation','interest','standalone_pretax',
                    'current_tax','operating_cashflow','capex','opening_cash','closing_cash','closing_ppe','debt')}
                group.update(entity_equity_income=total('equity_income'), equity_income_elimination=-total('equity_income'),
                    reported_entity_net_income=total('net_income'), external_net_income=total('net_income')-total('equity_income'),
                    entity_investments=total('closing_investment'), investment_elimination=-total('closing_investment'),
                    combined_capital=total('paid_in_capital')+total('closing_retained')-total('closing_investment'),
                    assets=total('closing_cash')+total('closing_ppe'))
                group['liabilities_and_capital'] = group['debt']+group['combined_capital']
                group['balance_residual'] = group['assets']-group['liabilities_and_capital']
                group['profit_reconciliation_residual'] = group['external_net_income']-(group['standalone_pretax']-group['current_tax'])
                group['cash_reconciliation_residual'] = (group['closing_cash']-group['opening_cash'])-(group['operating_cashflow']-group['capex'])
                spec.require(set(group) == set(spec.GROUP_METRICS), 'Incomplete Decimal group statement')
                periods.append({'period':label,'entities':result,'group':group,'solver':fixed['solver']})
                losses = [result[eid]['closing_loss'] for eid in ids]
                cash = [result[eid]['closing_cash'] for eid in ids]; ppe = [result[eid]['closing_ppe'] for eid in ids]
                investments = [result[eid]['closing_investment'] for eid in ids]; retained = [result[eid]['closing_retained'] for eid in ids]
            scenarios.append({'id':scenario['id'],'periods':periods})
        return {'kind':'equity_income_group_Decimal_contraction','version':1,
            'specification_sha256':spec.canonical_sha256(public),'scenario_order':[s['id'] for s in public['scenarios']],
            'entity_order':ids,'period_order':list(public['periods']),'scenarios':scenarios,
            'source_type':'new_synthetic','actual_LO_calls':0,'model_calls':0,'qualified':False}
