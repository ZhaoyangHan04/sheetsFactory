"""Hand-calculated public-only tests for the independent report oracle B."""
from copy import deepcopy
from fractions import Fraction as F
import ast
import inspect

import pytest

from sheets_factory.workbook.operating_reports_200 import oracle_b as b, schema


def entity(identity='E001', **changes):
    value = {
        'id': identity, 'name': 'Illustrative independent service business',
        'division': 'Advisory', 'layout': 'quarter_columns',
        'line_order': 'statement_first', 'money_unit': 'GBP',
        'rate_unit': 'percent_units', 'statement_sign': 'positive_deductions',
        'forecast_reference': 'same_quarter_last_year',
        'driver_form_by_year': {'2026': 'change_rate', '2027': 'change_rate'},
        'opening': {'cash': '1000', 'investment': '200', 'debt': '100',
                    'capital': '1000', 'retained_earnings': '100'},
        'actual_sales': dict.fromkeys(schema.QUARTERS[:4], '100'),
        'forecast_sales': dict.fromkeys(schema.QUARTERS[4:], '0'),
        'direct_cost_rate': '25', 'annual_interest_rate': '4', 'parent_tax_rate': '20',
        'cash_opex': dict.fromkeys(schema.QUARTERS, '10'),
        'associate_results': {q: '0' if q.startswith('2025') else '5' for q in schema.QUARTERS},
    }
    value.update(changes)
    return value


def public(*members, divisions=None):
    return {'kind': schema.KIND, 'version': 1, 'dimension_mode': 'toy', 'seed': schema.SEED,
            'years': [2025, 2026, 2027], 'base_currency': 'GBP',
            'provenance': 'new hypothetical service businesses; no official workbook seed',
            'public_policy': 'All labelled units and the frozen distribution policy apply.',
            'distribution': {'year': 2027, 'profit_percent': '20', 'cagr_percent': '8', 'q4_yoy_percent': '5'},
            'divisions': ['Advisory'] if divisions is None else divisions,
            'entities': list(members or (entity(),))}


def exact(result, key, layer='economic_exact_values'):
    item = result[layer][key]
    assert item['kind'] == 'rational'
    return F(item['value'])


def test_complete_hand_calculated_financial_endpoints_and_input_preservation():
    data = public(); before = deepcopy(data); out = b.solve(data)
    assert data == before
    expected = {'revenue':100, 'direct_cost':25, 'operating_expense':10,
                'operating_profit':65, 'interest':1, 'pretax_before_associate':64,
                'current_tax':F(64,5), 'core_net_income':F(256,5),
                'associate_income':5, 'net_income':F(281,5), 'operating_cash_flow':F(256,5),
                'closing_cash':1256, 'closing_investment':205,
                'closing_retained_earnings':361, 'total_assets':1461,
                'total_liabilities_equity':1461}
    for name, value in expected.items():
        assert exact(out, 'E001/2026Q1/'+name) == value
    assert exact(out, 'E001/FY2027/closing_cash') == F(8072,5)
    assert exact(out, 'E001/FY2027/closing_investment') == 240
    assert exact(out, 'E001/FY2027/closing_retained_earnings') == F(3772,5)
    assert exact(out, 'E001/FY2027/dividend') == 0
    checks = out['reconciliation_checks']
    assert checks['opening_balance_residuals'] == {'E001':'0'}
    assert all(v == '0' for name, rows in checks.items() if name.endswith('_residuals') for v in rows.values())
    assert len(checks['quarter_balance_residuals']) == 36
    assert set(out['typed_2dp_values']) == {key for key,_ in schema.points(data)}
    assert len(out['cagr_proofs']) == 6


@pytest.mark.parametrize('form,measure', [('change_rate','10'),('level_multiple','1.1'),
                                         ('base100_index','110'),('money_delta','2')])
@pytest.mark.parametrize('reference,base', [('same_quarter_last_year',10),('previous_calendar_quarter',40)])
def test_each_labelled_driver_and_comparison_period_is_independent(form,measure,reference,base):
    e = entity(actual_sales=dict(zip(schema.QUARTERS[:4], ['10','20','30','40'])),
               forecast_reference=reference,
               driver_form_by_year={'2026':form,'2027':form},
               forecast_sales=dict.fromkeys(schema.QUARTERS[4:], measure))
    out = b.solve(public(e))
    value = F(base)+2 if form=='money_delta' else F(base)*F(11,10)
    assert exact(out,'E001/2026Q1/revenue') == value
    if reference=='same_quarter_last_year':
        value2 = value+2 if form=='money_delta' else value*F(11,10)
        assert exact(out,'E001/2027Q1/revenue') == value2
    else:
        value2 = 40+8*2 if form=='money_delta' else 40*F(11,10)**8
        assert exact(out,'E001/2027Q4/revenue') == value2


@pytest.mark.parametrize('rate_unit,rates,growth', [
    ('fraction',('.25','.04','.20'),'.08'),
    ('percent_units',('25','4','20'),'8'),
    ('basis_points',('2500','400','2000'),'800')])
@pytest.mark.parametrize('money_unit,multiplier', [('GBP',1),('GBP_thousands',1000),('GBP_millions',1000000)])
def test_unit_decoding_and_raw_display_preserve_local_units(rate_unit,rates,growth,money_unit,multiplier):
    rates = tuple('0'+x if x.startswith('.') else x for x in rates)
    growth = '0'+growth if growth.startswith('.') else growth
    e = entity(money_unit=money_unit,rate_unit=rate_unit,
               direct_cost_rate=rates[0],annual_interest_rate=rates[1],parent_tax_rate=rates[2],
               forecast_sales=dict.fromkeys(schema.QUARTERS[4:],growth))
    out = b.solve(public(e))
    assert exact(out,'E001/2026Q1/revenue') == 108*multiplier
    assert exact(out,'E001/2026Q1/current_tax') == 14*multiplier
    assert exact(out,'E001/2026Q1/revenue','raw_cell_exact_values') == 108
    assert exact(out,'E001/2026Q1/yoy_percent') == 8
    raw_percent = {'fraction':F(2,25),'percent_units':F(8),'basis_points':F(800)}[rate_unit]
    assert exact(out,'E001/2026Q1/yoy_percent','raw_cell_exact_values') == raw_percent
    assert out['typed_2dp_values']['E001/FY2027/cagr_percent']['value'] == b.rounded(raw_percent)
    assert out['raw_cell_exact_values']['E001/FY2026/cagr_percent']['kind']=='cagr'
    assert out['cagr_proofs']['E001/FY2026/cagr_percent']['years']==1


@pytest.mark.parametrize('sign,multiplier', [('positive_deductions',1),('signed_contributions',-1)])
def test_cost_reporting_sign_does_not_reverse_forecast_associate_income(sign,multiplier):
    e = entity(statement_sign=sign)
    out = b.solve(public(e))
    for name,value in [('direct_cost',25),('operating_expense',10),('interest',1),('current_tax',F(64,5))]:
        assert exact(out,'E001/2026Q1/reported_'+name)==value*multiplier
    assert exact(out,'E001/2025Q1/reported_associate_line')==0
    assert exact(out,'E001/2026Q1/reported_associate_line')==5
    assert exact(out,'E001/2026Q1/net_income')==F(281,5)


def gate_entity(**changes):
    e=entity(direct_cost_rate='0',parent_tax_rate='0',annual_interest_rate='0',
             cash_opex=dict.fromkeys(schema.QUARTERS,'0'),
             associate_results=dict.fromkeys(schema.QUARTERS,'0'),
             forecast_sales=dict.fromkeys(schema.QUARTERS[4:],'8'))
    e.update(changes)
    return e


def test_exact_cagr_gate_equality_pays_and_previous_years_never_pay():
    out=b.solve(public(gate_entity()))
    assert exact(out,'E001/FY2027/revenue')==F(11664,25)
    assert exact(out,'E001/2027Q4/dividend')==F(11664,125)
    assert out['typed_2dp_values']['E001/FY2027/distribution_eligible']=={'type':'boolean','value':True}
    for year in (2025,2026):
        assert out['typed_2dp_values'][f'E001/FY{year}/distribution_eligible']['value'] is False
        assert exact(out,f'E001/FY{year}/dividend')==0
    assert out['cagr_proofs']['E001/FY2027/cagr_percent']['rounded']=='8.00'
    assert exact(out,'E001/FY2027/closing_cash')==1000+400+432+F(11664,25)-F(11664,125)


@pytest.mark.parametrize('kind', ['below_cagr','below_q4','negative_profit'])
def test_unrounded_distribution_gates_cannot_be_satisfied_by_rounded_display(kind):
    e=gate_entity()
    if kind=='below_cagr': e['forecast_sales']['2027Q1']='7.999999999999999999999'
    elif kind=='below_q4':
        e['forecast_sales'].update({'2027Q1':'20','2027Q4':'4.999999999999999999999'})
    else: e['cash_opex']=dict.fromkeys(schema.QUARTERS,'120')
    out=b.solve(public(e))
    assert out['typed_2dp_values']['E001/FY2027/distribution_eligible']['value'] is False
    assert exact(out,'E001/FY2027/dividend')==0


def test_portfolio_weights_money_and_builds_ratios_from_sum_not_mean():
    small=entity(associate_results=dict.fromkeys(schema.QUARTERS,'0'))
    large=entity('E002',money_unit='GBP_thousands',direct_cost_rate='0',parent_tax_rate='0',
                 annual_interest_rate='0',cash_opex=dict.fromkeys(schema.QUARTERS,'0'),
                 associate_results=dict.fromkeys(schema.QUARTERS,'0'))
    out=b.solve(public(small,large))
    assert exact(out,'PORTFOLIO/2026Q1/revenue')==100100
    assert exact(out,'PORTFOLIO/2026Q1/net_income')==100000+F(256,5)
    assert exact(out,'PORTFOLIO/2026Q1/net_margin_percent')==(100000+F(256,5))*100/100100
    assert exact(out,'DIV_ADVISORY/FY2026/revenue')==400400
    assert out['typed_2dp_values']['PORTFOLIO/FY2027/distribution_eligible']=={'type':'text','value':schema.GROUP_NA}
    assert out['reconciliation_checks']['group_membership']=={'DIV_ADVISORY':['E001','E002'],'PORTFOLIO':['E001','E002']}


def test_noncomparatives_are_typed_text_and_zero_is_unsigned():
    out=b.solve(public())
    for field in ('yoy_percent','prior_year_multiple','prior_year_index','yoy_sales_delta','qoq_percent','qoq_sales_delta'):
        assert out['typed_2dp_values']['E001/2025Q1/'+field]=={'type':'text','value':schema.NA}
    assert out['typed_2dp_values']['E001/2025Q2/qoq_percent']=={'type':'number','value':'0.00'}
    assert b.rounded(F(-1,1000))=='0.00'
    assert b.rounded(F(-1,200))=='-0.01'
    assert b.rounded(F(1,200))=='0.01'


@pytest.mark.parametrize('ratio,years,scale', [(F(2),2,1),(F(1,2),2,100),
    (F(11664,10000),2,F(1,100)),(F(10001,10000),1,1),(F(1),2,1)])
def test_cagr_certifies_root_bound_and_both_half_away_displays(ratio,years,scale):
    proof=b.cagr_proof(ratio,years,scale)
    lo,hi=F(proof['lower_raw']),F(proof['upper_raw'])
    assert lo<=hi
    assert (1+lo*scale/100)**years<=ratio<=(1+hi*scale/100)**years
    assert b.rounded(lo)==b.rounded(hi)==proof['rounded']
    assert proof['endpoint_ratio']==str(ratio)


@pytest.mark.parametrize('fault', ['opening','cash','investment','actual_zero','forecast_negative',
                                  'historical_associate','negative_cost','empty_division'])
def test_invalid_business_facts_fail_closed_without_invented_funding(fault):
    data=public(); e=data['entities'][0]
    if fault=='opening': e['opening']['retained_earnings']='101'
    elif fault=='cash': e['cash_opex']=dict.fromkeys(schema.QUARTERS,'1000')
    elif fault=='investment': e['associate_results']['2026Q1']='-201'
    elif fault=='actual_zero': e['actual_sales']['2025Q1']='0'
    elif fault=='forecast_negative': e['forecast_sales']['2026Q1']='-101'
    elif fault=='historical_associate': e['associate_results']['2025Q1']='1'
    elif fault=='negative_cost': e['direct_cost_rate']='-1'
    else: data['divisions'].append('Analytics')
    with pytest.raises(ValueError): b.solve(data)


def test_only_shared_schema_is_imported_no_financial_helpers_or_services():
    tree=ast.parse(inspect.getsource(b))
    imports=[node.module for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
    assert imports==['fractions','math',None]
    assert not any(isinstance(node,ast.Import) for node in ast.walk(tree))
