"""Independent Decimal/date forward oracle; never reads Excel formulas or caches."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, localcontext
import calendar

from .spec import load_spec, FAULTS


def posted(x):
    return int(Decimal(x).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def simulate(value, *, faults=()):
    s = load_spec(value); faults = set(faults)
    assert faults <= set(FAULTS)
    first = date.fromisoformat(s['start_month']); periods=[]
    for i in range(s['months']):
        serial=first.year*12+first.month-1+i; year,month=serial//12,serial%12+1
        start=date(year,month,1); end=date(year,month,calendar.monthrange(year,month)[1])
        if 'next_month_start' in faults: end += timedelta(days=1)
        periods.append({'start':start,'end':end,'days':(end-start).days+1})
    result={'periods':periods,'businesses':{},'facilities':{},'cashflows':[]}
    with localcontext() as ctx:
        ctx.prec=50
        for b in s['businesses']:
            rows=[]; previous=b['opening_working_capital_pence']
            fiscal=b['fiscal_end_month']; initial_fy=first.year+(first.month>fiscal)
            if 'calendar_year_fiscal_basis' in faults: initial_fy=first.year
            for p in periods:
                fy=p['end'].year+(p['end'].month>fiscal); fm=fiscal
                if 'calendar_year_fiscal_basis' in faults:fy=p['end'].year;fm=12
                finish=date(fy,fm,calendar.monthrange(fy,fm)[1]); prior=date(fy-1,fm,calendar.monthrange(fy-1,fm)[1]); days=(finish-prior).days
                growth=fy-initial_fy
                revenue=posted(Decimal(b['monthly_revenue_pence'])*(1+Decimal(b['annual_growth']))**growth)
                profit=posted(Decimal(revenue)*Decimal(b['operating_margin'])); costs=revenue-profit
                receivables=posted(Decimal(revenue)*12*b['receivable_days']/days)
                payables=posted(Decimal(costs)*12*b['payable_days']/days);wc=receivables-payables
                rows.append({'period_end':p['end'],'fiscal_year_end':finish,'fiscal_year_days':days,'growth_years':growth,
                    'revenue_pence':revenue,'costs_pence':costs,'profit_pence':profit,'receivables_pence':receivables,
                    'payables_pence':payables,'working_capital_pence':wc,'investment_pence':wc-previous})
                previous=wc
            result['businesses'][b['id']]=rows
        for f in s['facilities']:
            principal=f['opening_principal_pence'];maturity=date.fromisoformat(f['maturity_date']);rows=[]
            for p in periods:
                opening=principal
                days=max(0,(min(p['end']+timedelta(days=1),maturity)-p['start']).days) if opening else 0
                if 'unclipped_maturity' in faults:days=p['days'] if opening else 0
                interest=posted(Decimal(opening)*Decimal(f['annual_rate'])*days/f['day_count_basis'])
                repayment=opening if maturity<=p['end'] else min(opening,f['quarterly_principal_pence']) if f['type']=='Quarterly principal' and p['end'].month%3==0 else 0
                principal=opening-repayment
                rows.append({'period_end':p['end'],'opening_principal_pence':opening,'accrual_days':days,'interest_pence':interest,
                    'principal_paid_pence':repayment,'closing_principal_pence':principal,'cash_service_pence':interest+repayment,
                    'balance_check_pence':principal-opening+repayment})
            result['facilities'][f['id']]=rows
        for i,p in enumerate(periods):
            revenue=sum(rows[i]['revenue_pence'] for rows in result['businesses'].values())
            profit=sum(rows[i]['profit_pence'] for rows in result['businesses'].values())
            interest=sum(rows[i]['interest_pence'] for rows in result['facilities'].values())
            principal=sum(rows[i]['principal_paid_pence'] for rows in result['facilities'].values())
            investment=sum(rows[i]['investment_pence'] for rows in result['businesses'].values())
            tax=posted(Decimal(max(0,profit-interest))*Decimal(s['tax_rate']))
            cash=profit-interest-tax-principal-investment
            result['cashflows'].append({'date':p['end'],'revenue_pence':revenue,'profit_pence':profit,'interest_pence':interest,
                'tax_pence':tax,'principal_pence':principal,'investment_pence':investment,'equity_cash_pence':cash,'cash_check_pence':0})
        valuation_date=first-timedelta(days=1)
        opening=-(s['initial_project_expenditure_pence']+sum(b['opening_working_capital_pence'] for b in s['businesses'])-sum(f['opening_principal_pence'] for f in s['facilities']))
        settlement=periods[-1]['end']+timedelta(days=s['terminal_settlement_lag_days'])
        if 'immediate_terminal_settlement' in faults:settlement=periods[-1]['end']
        terminal_wc=sum(rows[-1]['working_capital_pence'] for rows in result['businesses'].values())
        items=[{'date':x['date'],'cash_pence':x['equity_cash_pence']} for x in result['cashflows']]+[{'date':settlement,'cash_pence':terminal_wc}]
        for x in items:
            x['elapsed_days']=(x['date']-valuation_date).days
            x['pv_pence']=posted(Decimal(x['cash_pence'])/(1+Decimal(s['discount_rate']))**(Decimal(x['elapsed_days'])/365))
        result['valuation']={'valuation_date':valuation_date,'opening_equity_cash_pence':opening,'settlement_date':settlement,
            'terminal_working_capital_pence':terminal_wc,'items':items,'equity_value_pence':opening+sum(x['pv_pence'] for x in items)}
    return result
