"""Independent exact endpoint/cumulative oracle for labelled operating reports.

Only the shared schema and public input facts are read.  No A, raw generator,
emitter, financial decoder, workbook, optimiser or service is imported.
"""
from fractions import Fraction
from math import isqrt

from . import schema

_F = Fraction
_MONEY_SCALE = {'GBP': 1, 'GBP_thousands': 1000, 'GBP_millions': 1000000}
_PERCENT_SCALE = {'fraction': _F(100), 'percent_units': _F(1), 'basis_points': _F(1, 100)}
_MONEY_FIELDS = set(schema.FLOWS + schema.STOCKS + schema.REPORTED +
                    ('yoy_sales_delta', 'qoq_sales_delta', 'annual_sales_delta'))


def _require(value, message):
    if not value:
        raise ValueError(message)


def rounded(value):
    """Exact half-away at two decimals, with canonical unsigned zero."""
    value = _F(value)
    cents, remainder = divmod(abs(value.numerator)*100, value.denominator)
    cents += 2*remainder >= value.denominator
    sign = '-' if value < 0 and cents else ''
    return f'{sign}{cents//100}.{cents%100:02d}'


def cagr_proof(endpoint_ratio, years, percent_units_per_raw_unit=1):
    """Certify the raw displayed CAGR using an independently bounded rational root."""
    ratio, scale = _F(endpoint_ratio), _F(percent_units_per_raw_unit)
    _require(ratio > 0 and scale > 0 and type(years) is int and years in (1, 2),
             'CAGR requires positive endpoints/units and one or two annual intervals')
    if years == 1:
        lower = upper = (ratio-1)*100/scale
    else:
        n, d = ratio.numerator, ratio.denominator
        rn, rd = isqrt(n), isqrt(d)
        if rn*rn == n and rd*rd == d:
            lower = upper = (_F(rn,rd)-1)*100/scale
        else:
            denominator = 100
            for _ in range(256):
                floor_root = isqrt(n*denominator*denominator//d)
                lo_root = _F(floor_root,denominator)
                hi_root = _F(floor_root+1,denominator)
                _require(lo_root*lo_root <= ratio <= hi_root*hi_root,
                         'The independent rational square-root bracket failed')
                lower, upper = (lo_root-1)*100/scale, (hi_root-1)*100/scale
                if rounded(lower) == rounded(upper):
                    break
                denominator *= 10
            else:
                raise ValueError('CAGR display could not be certified within the explicit bracket bound')
    _require(rounded(lower) == rounded(upper), 'CAGR endpoints do not certify one displayed value')
    return {'endpoint_ratio':str(ratio), 'years':years,
            'percent_units_per_raw_unit':str(scale), 'lower_raw':str(lower),
            'upper_raw':str(upper), 'rounded':rounded(lower)}


def _entity(entity):
    """Decode labelled local inputs, then reconstruct stocks from complete prefixes."""
    money = _F(_MONEY_SCALE[entity['money_unit']])
    rate = _PERCENT_SCALE[entity['rate_unit']]/100
    opening = {name:_F(value)*money for name,value in entity['opening'].items()}
    _require(all(opening[name] >= 0 for name in ('cash','investment','debt','capital')),
             'Opening monetary asset/funding facts must be nonnegative')
    opening_residual = (opening['cash']+opening['investment']-opening['debt']-
                        opening['capital']-opening['retained_earnings'])
    _require(opening_residual == 0, 'Opening balance sheet does not reconcile')
    cost_rate, interest_rate, tax_rate = (_F(entity[name])*rate for name in
        ('direct_cost_rate','annual_interest_rate','parent_tax_rate'))
    _require(min(cost_rate,interest_rate,tax_rate) >= 0, 'Cost, interest and tax rates must be nonnegative')
    sales = [_F(entity['actual_sales'][period])*money for period in schema.QUARTERS[:4]]
    for index,period in enumerate(schema.QUARTERS[4:],4):
        comparison = index-4 if entity['forecast_reference']=='same_quarter_last_year' else index-1
        original = sales[comparison]
        raw = _F(entity['forecast_sales'][period])
        form = entity['driver_form_by_year'][period[:4]]
        if form == 'money_delta': value = original+raw*money
        elif form == 'level_multiple': value = original*raw
        elif form == 'base100_index': value = original*raw/100
        else:
            _require(form=='change_rate', 'Unknown public forecast measure')
            value = original*(1+raw*rate)
        sales.append(value)
    _require(all(value > 0 for value in sales), 'Every stated sales/comparison base must be positive')
    records=[]
    for index,period in enumerate(schema.QUARTERS):
        revenue=sales[index]; cost=revenue*cost_rate
        expense=_F(entity['cash_opex'][period])*money
        _require(expense >= 0,'Cash operating costs must be nonnegative')
        interest=opening['debt']*interest_rate/4
        operating=revenue-cost-expense; pretax=operating-interest
        tax=max(pretax,0)*tax_rate; core=pretax-tax
        associate=_F(entity['associate_results'][period])*money
        _require(index>=4 or associate==0,'Existing associates have no FY2025 income')
        records.append({'revenue':revenue,'direct_cost':cost,'operating_expense':expense,
            'operating_profit':operating,'interest':interest,'pretax_before_associate':pretax,
            'current_tax':tax,'core_net_income':core,'associate_income':associate,
            'net_income':core+associate,'operating_cash_flow':core,'dividend':_F(0)})
    total_first=sum(sales[:4]);total_last=sum(sales[8:12])
    annual_income=sum(row['net_income'] for row in records[8:12])
    eligible=(annual_income>0 and total_last*625>=total_first*729 and sales[11]*20>=sales[7]*21)
    records[11]['dividend']=annual_income/5 if eligible else _F(0)
    # Prefix reconstruction deliberately does not consume earlier closing cells.
    for end,row in enumerate(records,1):
        prefix=records[:end]
        dividend=sum(v['dividend'] for v in prefix)
        cash=opening['cash']+sum(v['operating_cash_flow'] for v in prefix)-dividend
        investment=opening['investment']+sum(v['associate_income'] for v in prefix)
        retained=opening['retained_earnings']+sum(v['net_income'] for v in prefix)-dividend
        _require(cash>=0 and investment>=0,'A report requires undeclared overdraft or negative investment')
        row.update(closing_cash=cash,closing_investment=investment,
            closing_retained_earnings=retained,debt=opening['debt'],contributed_capital=opening['capital'],
            total_assets=cash+investment,total_liabilities_equity=opening['debt']+opening['capital']+retained)
        sign=-1 if entity['statement_sign']=='signed_contributions' else 1
        for name in ('direct_cost','operating_expense','interest','current_tax'):
            row['reported_'+name]=row[name]*sign
        row['reported_associate_line']=(-row['associate_income'] if end<=4 and sign==1 else row['associate_income'])
    return opening,records,eligible


def _metrics(row, prior_year, prior_quarter=None):
    revenue=row['revenue']
    result={'net_margin_percent':100*row['net_income']/revenue}
    if prior_year is None:
        result.update({key:schema.NA for key in ('yoy_percent','prior_year_multiple','prior_year_index','yoy_sales_delta')})
    else:
        ratio=revenue/prior_year
        result.update(yoy_percent=100*(ratio-1),prior_year_multiple=ratio,
                      prior_year_index=100*ratio,yoy_sales_delta=revenue-prior_year)
    if prior_quarter is None:
        result.update(qoq_percent=schema.NA,qoq_sales_delta=schema.NA)
    else:
        result.update(qoq_percent=100*(revenue/prior_quarter-1),qoq_sales_delta=revenue-prior_quarter)
    return result


def _report(records, entity, eligible):
    report={}
    for index,period in enumerate(schema.QUARTERS):
        row=dict(records[index]);row.update(_metrics(row,records[index-4]['revenue'] if index>=4 else None,
                                                   records[index-1]['revenue'] if index else None))
        report[period]=row
    annual=[]
    for year in range(3):
        quarters=records[4*year:4*year+4]
        row={field:sum(q[field] for q in quarters) for field in schema.FLOWS}
        row.update({field:quarters[-1][field] for field in schema.STOCKS})
        metrics=_metrics(row,annual[year-1]['revenue'] if year else None)
        row.update({field:metrics[field] for field in ('net_margin_percent','yoy_percent','prior_year_multiple','prior_year_index')})
        row['annual_sales_delta']=row['revenue']-annual[year-1]['revenue'] if year else schema.NA
        row['cagr_percent']=(row['revenue']/annual[0]['revenue'],year) if year else schema.NA
        row['distribution_eligible']=(eligible if year==2 else False) if entity else schema.GROUP_NA
        annual.append(row);report['FY'+str(2025+year)]=row
    return report


def solve(public_specification):
    """Produce the complete semantic/raw/typed union using public facts only."""
    public=schema.validate_spec(public_specification)
    entities=public['entities'];membership={}
    for division in public['divisions']:
        members=[e['id'] for e in entities if e['division']==division]
        _require(bool(members),'A declared management division cannot have an empty comparison base')
        membership['DIV_'+division.upper()]=members
    membership['PORTFOLIO']=[e['id'] for e in entities]
    openings={};records={};reports={};units={};opening_residuals={}
    for entity in entities:
        identity=entity['id'];opening,rows,eligible=_entity(entity)
        openings[identity]=opening;records[identity]=rows;reports[identity]=_report(rows,True,eligible)
        units[identity]=(_F(_MONEY_SCALE[entity['money_unit']]),_PERCENT_SCALE[entity['rate_unit']])
        opening_residuals[identity]=str(opening['cash']+opening['investment']-opening['debt']-opening['capital']-opening['retained_earnings'])
    for identity,members in membership.items():
        opening={name:sum(openings[member][name] for member in members) for name in ('cash','investment','debt','capital','retained_earnings')}
        rows=[{field:sum(records[member][index][field] for member in members)
               for field in schema.FLOWS+schema.STOCKS} for index in range(12)]
        openings[identity]=opening;records[identity]=rows;reports[identity]=_report(rows,False,False)
        units[identity]=(_F(1),_F(1))
    checks={'passed':True,'opening_balance_residuals':opening_residuals,
        'quarter_balance_residuals':{},'cash_bridge_residuals':{},
        'investment_bridge_residuals':{},'retained_earnings_bridge_residuals':{},'group_membership':membership}
    for identity,rows in records.items():
        opening=openings[identity]
        for index,row in enumerate(rows):
            previous=rows[index-1] if index else {'closing_cash':opening['cash'],
                'closing_investment':opening['investment'],'closing_retained_earnings':opening['retained_earnings']}
            residuals={'quarter_balance_residuals':row['total_assets']-row['total_liabilities_equity'],
                'cash_bridge_residuals':row['closing_cash']-previous['closing_cash']-row['operating_cash_flow']+row['dividend'],
                'investment_bridge_residuals':row['closing_investment']-previous['closing_investment']-row['associate_income'],
                'retained_earnings_bridge_residuals':row['closing_retained_earnings']-previous['closing_retained_earnings']-row['net_income']+row['dividend']}
            for name,residual in residuals.items():
                _require(residual==0,'Independent report reconciliation failed: '+name)
                checks[name][identity+'/'+schema.QUARTERS[index]]=str(residual)
    economic={};raw={};typed={};proofs={}
    for key,kind in schema.points(public):
        identity,period,field=key.split('/');value=reports[identity][period][field]
        money_scale,percent_scale=units[identity]
        if kind=='text':
            _require(value in (schema.NA,schema.GROUP_NA),'A nonapplicable field lost its public type')
            economic[key]=raw[key]={'kind':'text','value':value};typed[key]={'type':'text','value':value}
        elif kind=='boolean':
            _require(type(value) is bool,'Eligibility must retain its Boolean type')
            economic[key]=raw[key]={'kind':'boolean','value':value};typed[key]={'type':'boolean','value':value}
        elif field=='cagr_percent':
            ratio,years=value
            economic[key]={'kind':'cagr','endpoint_ratio':str(ratio),'years':years,'percent_units_per_raw_unit':'1'}
            raw[key]={'kind':'cagr','endpoint_ratio':str(ratio),'years':years,'percent_units_per_raw_unit':str(percent_scale)}
            proof=cagr_proof(ratio,years,percent_scale);proofs[key]=proof
            typed[key]={'type':'number','value':proof['rounded']}
        else:
            number=_F(value)
            local=number/money_scale if field in _MONEY_FIELDS else number/percent_scale if field.endswith('_percent') else number
            economic[key]={'kind':'rational','value':str(number)};raw[key]={'kind':'rational','value':str(local)}
            typed[key]={'type':'number','value':rounded(local)}
    result={'kind':schema.RESULT_KIND,'version':1,'specification_sha256':schema.canonical_sha256(public),
        'economic_exact_values':economic,'raw_cell_exact_values':raw,'typed_2dp_values':typed,
        'cagr_proofs':proofs,'reconciliation_checks':checks}
    return schema.validate_result(public,result)
