"""Decimal chronological bridge A; no workbook, B oracle or cache inputs."""
from __future__ import annotations
from copy import deepcopy
from decimal import Decimal, localcontext, ROUND_HALF_UP
from fractions import Fraction
import hashlib
from pathlib import Path
from . import spec
from ..operating_reports_200 import oracle_a as retained
from ..operating_reports_200 import schema as vocabulary

BASE_ORACLE_SHA = 'a7583bd3125765872c2abdf6d27adf0afa34a776f47f3950b171ab4a22a30079'
ZERO = Decimal(0)


def _amount(encoded):
    if encoded.get('kind') != 'rational':
        raise ValueError('Expected a finite monetary reference amount')
    value = Fraction(encoded['value'])
    amount = Decimal(value.numerator)/Decimal(value.denominator)
    if Fraction(amount) != value:
        raise ValueError('The Decimal precision cannot represent the supplied monetary amount exactly')
    return amount


def _rational(value):
    return {'kind':'rational','value':str(Fraction(value))}


def _render(value):
    value = Fraction(value)
    # Display is the only rounding operation; rational arithmetic preserves the exact ratio.
    scaled = abs(value)*100
    whole, remainder = divmod(scaled.numerator,scaled.denominator)
    if 2*remainder >= scaled.denominator:
        whole += 1
    return ('-' if value < 0 and whole else '')+f'{whole//100}.{whole%100:02d}'


def solve(public):
    public = spec.validate_spec(public)
    if hashlib.sha256(Path(retained.__file__).read_bytes()).hexdigest() != BASE_ORACLE_SHA:
        raise ValueError('The retained independent base oracle A changed')
    base = public['base']
    baseline = retained.solve(base)
    output = deepcopy(baseline)
    output.update(kind=spec.RESULT_KIND,specification_sha256=spec.canonical_sha256(public))
    fields = vocabulary.FLOWS+vocabulary.STOCKS
    states, deltas, opening = {}, {}, {}
    checks = {name:{} for name in ('opening_balance_residuals','quarter_balance_residuals',
              'cash_bridge_residuals','investment_bridge_residuals','retained_earnings_bridge_residuals')}
    with localcontext() as context:
        context.prec = 250
        def old(identity, period, field):
            return _amount(baseline['economic_exact_values'][f'{identity}/{period}/{field}'])
        def save(identity, period, field, value, money_scale, rate_scale):
            key = f'{identity}/{period}/{field}'
            exact = Fraction(value)
            divisor = rate_scale if field.endswith('_percent') else Fraction(money_scale)
            output['economic_exact_values'][key] = _rational(exact)
            output['raw_cell_exact_values'][key] = _rational(exact/divisor)
            output['typed_2dp_values'][key] = {'type':'number','value':_render(exact/divisor)}
        def audit(identity, period, row, previous, investment_change):
            point = identity+'/'+period
            checks['quarter_balance_residuals'][point] = row['total_assets']-row['total_liabilities_equity']
            checks['cash_bridge_residuals'][point] = row['closing_cash']-previous[0]-row['operating_cash_flow']+row['dividend']
            checks['investment_bridge_residuals'][point] = row['closing_investment']-previous[1]-investment_change
            checks['retained_earnings_bridge_residuals'][point] = row['closing_retained_earnings']-previous[2]-row['net_income']+row['dividend']
        for entity in base['entities']:
            identity = entity['id']; policy = public['policies'][identity]
            scale = spec.MONEY_SCALES[entity['money_unit']]
            rate_scale = {'fraction':Fraction(100),'percent_units':Fraction(1),'basis_points':Fraction(1,100)}[entity['rate_unit']]
            tax_rate = Decimal(entity['parent_tax_rate'])*{'fraction':Decimal(1),'percent_units':Decimal('.01'),'basis_points':Decimal('.0001')}[entity['rate_unit']]
            begin = {k:Decimal(v)*scale for k,v in entity['opening'].items()};opening[identity] = begin
            checks['opening_balance_residuals'][identity] = begin['cash']+begin['investment']-begin['debt']-begin['capital']-begin['retained_earnings']
            rows, movements = [], []
            for period in vocabulary.QUARTERS:
                row = {field:old(identity,period,field) for field in fields}
                direction = policy['direction_by_year'][period[:4]]
                share = Decimal(policy['share_postings'][period])*policy['feed_scale']*(-1 if direction=='charge_credit' else 1)
                receipt = Decimal(policy['cash_receipts'][period])*scale
                dividend_receipt = receipt if policy['receipt_kind'][period]=='dividend' else ZERO
                recognized = share if policy['method']=='equity' else dividend_receipt
                tax_addition = {'exempt':ZERO,'recognized':recognized,'cash_dividends':dividend_receipt}[policy['tax_class']]
                tax = max(ZERO,row['pretax_before_associate']+tax_addition)*tax_rate
                core = row['pretax_before_associate']-tax
                income = core+recognized
                movement = (share-receipt) if policy['method']=='equity' else (-receipt if policy['receipt_kind'][period]=='capital_return' else ZERO)
                row.update(current_tax=tax,core_net_income=core,associate_income=recognized,
                           net_income=income,operating_cash_flow=income-recognized+receipt,dividend=ZERO)
                rows.append(row);movements.append(movement)
            annual_income = sum((r['net_income'] for r in rows[8:]),ZERO)
            eligible = baseline['typed_2dp_values'][f'{identity}/FY2027/distribution_eligible']['value'] is True
            cash, investment, earnings = begin['cash'],begin['investment'],begin['retained_earnings']
            for index,(period,row,movement) in enumerate(zip(vocabulary.QUARTERS,rows,movements)):
                distribution = max(ZERO,annual_income)/5 if index==11 and eligible else ZERO
                previous = cash,investment,earnings
                cash += row['operating_cash_flow']-distribution
                investment += movement
                earnings += row['net_income']-distribution
                if cash < 0 or investment < 0:
                    raise ValueError('Bridge exhausts supplied cash or investment carrying value')
                row.update(dividend=distribution,closing_cash=cash,closing_investment=investment,
                    closing_retained_earnings=earnings,total_assets=cash+investment,
                    total_liabilities_equity=begin['debt']+begin['capital']+earnings)
                for field in fields:
                    save(identity,period,field,row[field],scale,rate_scale)
                save(identity,period,'net_margin_percent',Fraction(row['net_income'])*100/Fraction(row['revenue']),scale,rate_scale)
                save(identity,period,'reported_current_tax',row['current_tax']*(-1 if entity['statement_sign']=='signed_contributions' else 1),scale,rate_scale)
                save(identity,period,'reported_associate_line',row['associate_income'],scale,rate_scale)
                audit(identity,period,row,previous,movement)
            states[identity] = rows;deltas[identity] = movements
            for year in vocabulary.YEARS:
                block = rows[(year-2025)*4:(year-2025+1)*4]
                for field in fields:
                    value = sum((r[field] for r in block),ZERO) if field in vocabulary.FLOWS else block[-1][field]
                    save(identity,f'FY{year}',field,value,scale,rate_scale)
                sales = sum((r['revenue'] for r in block),ZERO)
                ni = sum((r['net_income'] for r in block),ZERO)
                save(identity,f'FY{year}','net_margin_percent',Fraction(ni)*100/Fraction(sales),scale,rate_scale)
        membership = {'DIV_'+d.upper():[e['id']for e in base['entities']if e['division']==d]for d in base['divisions']}
        membership['PORTFOLIO'] = [e['id']for e in base['entities']]
        for identity,members in membership.items():
            begin = {k:sum((opening[e][k]for e in members),ZERO)for k in base['entities'][0]['opening']}
            checks['opening_balance_residuals'][identity] = begin['cash']+begin['investment']-begin['debt']-begin['capital']-begin['retained_earnings']
            previous = begin['cash'],begin['investment'],begin['retained_earnings']
            rows = []
            for index,period in enumerate(vocabulary.QUARTERS):
                row = {field:sum((states[e][index][field]for e in members),ZERO)for field in fields}
                rows.append(row)
                for field in fields:save(identity,period,field,row[field],1,Fraction(1))
                save(identity,period,'net_margin_percent',Fraction(row['net_income'])*100/Fraction(row['revenue']),1,Fraction(1))
                audit(identity,period,row,previous,sum((deltas[e][index]for e in members),ZERO))
                previous = row['closing_cash'],row['closing_investment'],row['closing_retained_earnings']
            for year in vocabulary.YEARS:
                block = rows[(year-2025)*4:(year-2025+1)*4]
                for field in fields:
                    value = sum((r[field]for r in block),ZERO)if field in vocabulary.FLOWS else block[-1][field]
                    save(identity,f'FY{year}',field,value,1,Fraction(1))
                save(identity,f'FY{year}','net_margin_percent',Fraction(sum((r['net_income']for r in block),ZERO))*100/Fraction(sum((r['revenue']for r in block),ZERO)),1,Fraction(1))
        output['reconciliation_checks'] = {'passed':all(v==0 for values in checks.values()for v in values.values()),
            **{name:{k:str(Fraction(v))for k,v in values.items()}for name,values in checks.items()},'group_membership':membership}
    if not output['reconciliation_checks']['passed']:
        raise ValueError('The complete bridge ledger does not reconcile')
    expected = dict(vocabulary.points(base))
    if any(set(output[k]) != set(expected)for k in ('economic_exact_values','raw_cell_exact_values','typed_2dp_values')):
        raise ValueError('Incomplete business field inventory')
    return output
