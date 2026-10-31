"""Independent ledger and hand-calculated checks of the Excel expression graph.

These tests do not launch LibreOffice or create a production source artifact.
"""
import ast
from copy import deepcopy
from datetime import date
from fractions import Fraction
import inspect
import json
import math
from pathlib import Path
import re
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from openpyxl import Workbook
from openpyxl.utils.datetime import MAC_EPOCH, from_excel

from sheets_factory.workbook.heterogeneous_contracts import excel
from sheets_factory.workbook.heterogeneous_contracts.ledger import simulate
from sheets_factory.workbook.heterogeneous_contracts.spec import (ASSET_FIELDS,
    ENTITY_FIELDS, GROUP_FIELDS, LOAN_FIELDS, SCALE, canonical_sha256, load_spec)
from sheets_factory.workbook.heterogeneous_contracts.validate import (
    ValidationError, _evaluate, _matches, _observed, expected_values)

ROOT=Path(__file__).resolve().parents[1]


def toy(*, loan_type='BULLET_MONTHLY', tax_policy='ACCRUAL_MONTHLY',
        dscr_policy='MONTHLY_CURRENT', year=2027, entities=1, scenarios=1):
    months=[f'{year}-{month:02d}-01' for month in [1,2,3]]
    ids=[f'E{i:02d}' for i in range(1,entities+1)]
    s={'schema_version':1,'kind':'hypothetical_heterogeneous_contracts_private_construction_spec',
       'dimension_mode':'toy','start_month':months[0],'months':months,
       'scenario_ids':[f'S{i:02d}' for i in range(1,scenarios+1)],'currency':'GBP','rate_scale':SCALE,
       'entities':[],'loans':[],'assets':[],'operating_inputs':{},'scenarios':[],
       'group':{'name':'Toy public portfolio','bank_funding_priority':ids,
           'shared_margin_priority':ids,'lp_funding_priority':ids,
           'additional_lp_commitment_pence':100000000,
           'shared_bank_limit_schedule':[{'effective_month':months[0],'limit_pence':3000000*entities}]}}
    for index,eid in enumerate(ids,1):
        s['entities'].append({'id':eid,'name':'Public entity '+eid,'functional_currency':'GBP',
            'opening_cash_pence':2000000,'opening_restricted_cash_pence':0,
            'opening_paid_in_capital_pence':1000000,'opening_retained_earnings_pence':0,
            'opening_tax_payable_pence':0,'opening_interest_carry':[],'opening_tax_losses':[],
            'minimum_cash_pence':100000,'reserve_target_pence':200000,
            'additional_lp_commitment_pence':100000000,'tax_policy':tax_policy,
            'tax_rate_p12':250000000000,'interest_cap_fraction_p12':300000000000,
            'interest_carry_months':2,'loss_carry_months':2,'dscr_policy':dscr_policy,
            'dscr_threshold_p12':1150000000000,'opening_trap':False,'opening_cure_count':0})
        lid=f'L{index:02d}'
        s['loans'].append({'id':lid,'entity_id':eid,'type':loan_type,
            'opening_principal_pence':1000000,'opening_accrued_interest_pence':0,
            'terms':[{'id':lid+'@'+months[0],'effective_month':months[0],
                'annual_rate_p12':120000000000,'day_count':'ACT_365F',
                'local_limit_pence':3000000,'maturity_date':f'{year+1}-12-31',
                'draw_cutoff_month':None if loan_type=='LEVEL_PRINCIPAL_MONTHLY' else f'{year+1}-09-01',
                'optional_repayment_fraction_p12':0,
                'next_coupon_month':months[2] if loan_type=='BULLET_QUARTERLY_ACCRUAL' else None}]})
        s['operating_inputs'][eid]=[{'month':month,'base_cash_revenue_pence':1000000,'base_cash_opex_pence':600000} for month in months]
    for sid in s['scenario_ids']:
        s['scenarios'].append({'id':sid,'name':'Public scenario '+sid,
            'monthly_schedule':[{'month':month,'revenue_factor_p12':SCALE,
                'opex_factor_p12':SCALE,'annual_rate_spread_p12':0} for month in months]})
    return load_spec(s)


def prove(spec):
    # The emitter receives only primitives. The journal is supplied to a separate auditor.
    independent=simulate(spec)
    book=Workbook()
    binding=excel.emit_heterogeneous_workbook(book,spec)
    checked=expected_values(spec,independent,binding)
    return independent,book,binding,checked


def entity(result,index=0,eid='E01',sid='S01'):
    return result['scenarios'][sid]['entities'][eid]['monthly'][index]


class _Binary64(ast.NodeTransformer):
    def visit_Constant(self,node):
        return ast.copy_location(ast.Constant(float(node.value)),node) if type(node.value) is int else node

    def visit_Call(self,node):
        node=self.generic_visit(node)
        if isinstance(node.func,ast.Name) and node.func.id=='IF':
            return ast.copy_location(ast.IfExp(node.args[0],node.args[1],node.args[2]),node)
        return node


def _float_formula(formula,values):
    """Offline binary64 check of actual formula text, not an Excel execution."""
    pattern=re.compile(r"'(?:[^']|'')+'!\$[A-Z]+\$[1-9][0-9]*")
    text=pattern.sub(lambda m:repr(values[m.group()]),formula[1:])
    text=re.sub(r'(?<![<>=!])=(?!=)','==',text.replace('<>','!='))
    tree=_Binary64().visit(ast.parse(text,mode='eval'));ast.fix_missing_locations(tree)
    functions={'ABS':abs,'INT':math.floor,'MOD':lambda a,b:a%b,'MIN':min,'MAX':max,
        'AND':lambda *args:all(args),'OR':lambda *args:any(args),
        'ROUND':lambda value,digits:math.copysign(math.floor(abs(value)+.5),value),
        'YEAR':lambda serial:from_excel(serial).year,'MONTH':lambda serial:from_excel(serial).month}
    return eval(compile(tree,'<offline formula text>','eval'),{'__builtins__':{}},functions)


@pytest.mark.parametrize('loan_type',['BULLET_MONTHLY','LEVEL_PRINCIPAL_MONTHLY','BULLET_QUARTERLY_ACCRUAL'])
def test_complete_formula_text_binary64_matches_independent_fields(loan_type):
    _,_,binding,checked=prove(toy(loan_type=loan_type,tax_policy='CASH_COUPON_QUARTERLY'))
    values={}
    for row in binding['input_bindings']:
        values[excel._ref(row['sheet'],int(re.search(r'\d+',row['cell'])[0]),re.match(r'[A-Z]+',row['cell'])[0])]='' if row['stored_value'] is None else row['stored_value']
    for row in binding['literal_bindings']:
        values[excel._ref(row['sheet'],int(re.search(r'\d+',row['cell'])[0]),re.match(r'[A-Z]+',row['cell'])[0])]=row['value']
    for row in binding['arithmetic_bindings']:
        key=row['sheet'],row['cell'];actual=_float_formula(row['formula'],values)
        assert type(actual) is not bool,(key,'A numeric helper became an Excel boolean')
        financial=checked['financial'].get(key)
        assert _matches(_observed(actual),checked['values'][key],financial),(key,actual,checked['values'][key])
        values[excel._ref(row['sheet'],int(re.search(r'\d+',row['cell'])[0]),re.match(r'[A-Z]+',row['cell'])[0])]=actual


@pytest.mark.parametrize('loan_type',['BULLET_MONTHLY','LEVEL_PRINCIPAL_MONTHLY','BULLET_QUARTERLY_ACCRUAL'])
@pytest.mark.parametrize('tax_policy',['ACCRUAL_MONTHLY','CASH_COUPON_QUARTERLY'])
@pytest.mark.parametrize('dscr_policy',['MONTHLY_CURRENT','QUARTERLY_LAGGED'])
def test_all_heterogeneous_policy_crossings_match_independent_journal(loan_type,tax_policy,dscr_policy):
    result,book,bindings,checked=prove(toy(loan_type=loan_type,tax_policy=tax_policy,dscr_policy=dscr_policy))
    assert len(checked['definitions'])==bindings['formula_count']
    assert len(checked['financial'])==len(bindings['financial_bindings'])
    assert result['specification_sha256']==bindings['specification_sha256']
    assert all(entity(result,t)['balance_sheet_check']==0 for t in range(3))
    assert book['Entity Policies']['J2'].number_format==excel.MONEY_FORMAT


def test_opening_principal_act_leap_days_and_single_posting():
    result,_,_,_=prove(toy(year=2028))
    feb=entity(result,1)
    expected=(1000000*120000000000*29*2+SCALE*365)//(2*SCALE*365)
    assert feb['interest_accrual']==expected==9534
    assert result['scenarios']['S01']['loans']['L01']['monthly'][1]['days']==29


def test_fixed_level_principal_reset_and_maturity_remainder():
    s=toy(loan_type='LEVEL_PRINCIPAL_MONTHLY');s['loans'][0]['terms'][0]['maturity_date']='2027-03-31'
    s['entities'][0]['dscr_threshold_p12']=0  # Isolate scheduled instalments from the contractual trapped-cash sweep.
    result,_,_,_=prove(s)
    assert [entity(result,t)['scheduled_principal'] for t in range(3)]==[333333,333333,333334]
    assert entity(result,2)['facility_closed_next']==1


def test_amendment_recasts_remaining_principal_only_on_its_effective_month():
    s=toy(loan_type='LEVEL_PRINCIPAL_MONTHLY')
    s['entities'][0]['dscr_threshold_p12']=0
    s['loans'][0]['terms'][0]['maturity_date']='2027-05-31'
    amendment=deepcopy(s['loans'][0]['terms'][0]);amendment.update(id='L01@2027-02-01',effective_month='2027-02-01',maturity_date='2027-03-31')
    s['loans'][0]['terms'].append(amendment)
    result,_,binding,_=prove(s)
    assert [entity(result,t)['scheduled_principal'] for t in range(3)]==[200000,400000,400000]
    loan=result['scenarios']['S01']['loans']['L01']['monthly']
    assert [row['recast_due'] for row in loan]==[1,1,0]
    assert any('effective_month' in row['path'] for row in binding['input_bindings'])


def test_quarter_coupon_reset_preserves_prior_accrual():
    s=toy(loan_type='BULLET_QUARTERLY_ACCRUAL',tax_policy='CASH_COUPON_QUARTERLY')
    amendment=deepcopy(s['loans'][0]['terms'][0]);amendment.update(id='L01@2027-02-01',effective_month='2027-02-01',next_coupon_month='2027-04-01')
    s['loans'][0]['terms'].append(amendment)
    result,_,_,_=prove(s)
    assert [entity(result,t)['cash_coupon'] for t in range(3)]==[0,0,0]
    assert entity(result,2)['interest_payable_close']==sum(entity(result,t)['interest_accrual'] for t in range(3))
    assert entity(result,1)['interest_payable_open']==entity(result,0)['interest_accrual']


def test_off_cycle_maturity_pays_accrual_and_releases_reserve_once_then_no_test():
    s=toy(loan_type='BULLET_QUARTERLY_ACCRUAL')
    e=s['entities'][0];e['opening_restricted_cash_pence']=200000;e['opening_paid_in_capital_pence']=1200000
    s['loans'][0]['terms'][0]['maturity_date']='2027-02-28'
    result,_,_,_=prove(s)
    feb=entity(result,1);march=entity(result,2)
    # The January ordinary release can consume the opening reserve; only current reserve is released at maturity.
    assert feb['cash_coupon']==feb['interest_payable_open']+feb['interest_accrual']
    assert feb['reserve_released']==feb['reserve_open']
    assert feb['reserve_locked']==0
    assert march['facility_closed_open']==1 and march['test_applicable']==0
    assert march['test_pass'] is None and march['dscr_ratio_millionths'] is None
    assert result['scenarios']['S01']['loans']['L01']['monthly'][2]['recast_instalment']==0


def test_monthly_two_pass_cure_only_clears_next_month():
    s=toy();s['entities'][0]['opening_trap']=True
    result,_,_,_=prove(s)
    assert [entity(result,t)['trap_operative'] for t in range(3)]==[1,1,0]
    assert [entity(result,t)['trap_next'] for t in range(3)]==[1,0,0]


def test_quarterly_failure_does_not_restrict_the_current_test_month():
    s=toy(dscr_policy='QUARTERLY_LAGGED')
    s['entities'][0]['dscr_threshold_p12']=5*SCALE
    s['loans'][0]['terms'][0]['annual_rate_p12']=SCALE
    for row in s['operating_inputs']['E01']:row['base_cash_revenue_pence']=620000
    result,_,_,_=prove(s)
    assert entity(result,0)['test_pass'] is None and entity(result,1)['test_pass'] is None
    assert entity(result,2)['test_pass']==0
    assert entity(result,2)['trap_operative']==0 and entity(result,2)['trap_next']==1


def test_zero_debt_service_ratio_blank_but_test_pass_is_numeric():
    s=toy();s['loans'][0]['opening_principal_pence']=0;s['entities'][0]['opening_paid_in_capital_pence']=2000000
    result,_,binding,_=prove(s)
    assert entity(result)['mandatory_debt_service']==0
    assert entity(result)['dscr_ratio_millionths'] is None and entity(result)['test_pass']==1
    rows=[r for r in binding['financial_bindings'] if r['expected_path'][-1]=='dscr_ratio_millionths']
    assert rows and all(r['kind']=='nullable_ratio_micro' for r in rows)


def test_undefined_ratio_does_not_evaluate_a_wide_dummy_division():
    s=toy();s['loans'][0]['opening_principal_pence']=0;s['entities'][0]['opening_paid_in_capital_pence']=2000000
    for row in s['operating_inputs']['E01']:
        row['base_cash_revenue_pence']=100000000000;row['base_cash_opex_pence']=0
    result,_,_,checked=prove(s)
    assert entity(result)['dscr_ratio_millionths'] is None
    assert all(not isinstance(value,Fraction) or abs(value)<2**53 for value in checked['values'].values())


def test_voluntary_repayment_does_not_recast_an_active_level_instalment():
    s=toy(loan_type='LEVEL_PRINCIPAL_MONTHLY');s['loans'][0]['terms'][0]['maturity_date']='2027-03-31'
    s['loans'][0]['terms'][0]['optional_repayment_fraction_p12']=SCALE//4
    s['entities'][0].update(opening_cash_pence=500000,opening_paid_in_capital_pence=500000,dscr_threshold_p12=0)
    s['assets']=[{'id':'A01','entity_id':'E01','description':'Existing equipment',
        'commission_month':'2026-01-01','original_cost_pence':1000000,
        'opening_accumulated_depreciation_pence':0,'useful_life_months':120,'capex_category':'GROWTH'}]
    result,_,_,_=prove(s)
    loan=result['scenarios']['S01']['loans']['L01']['monthly']
    assert entity(result)['voluntary_principal']>0
    assert loan[1]['recast_due']==0 and loan[1]['recast_instalment']==333333
    assert loan[1]['scheduled_principal']==333333


def test_full_fifo_window_expiry_and_current_origin_not_reused():
    s=toy();e=s['entities'][0];e['interest_carry_months']=e['loss_carry_months']=1
    e['opening_interest_carry']=[{'origin_month':'2026-12-01','amount_pence':100000}]
    e['opening_tax_losses']=[{'origin_month':'2026-12-01','amount_pence':200000}]
    for row in s['operating_inputs']['E01']:row['base_cash_revenue_pence']=0
    result,_,bindings,_=prove(s)
    assert entity(result,1)['interest_expired']==100000
    assert entity(result,1)['loss_expired']==200000
    assert entity(result,0)['interest_current_allowed']==0
    assert entity(result,0)['interest_old_used']==0
    assert any(row.get('vintage_origin')=='2026-12-01' and row.get('vintage_field')=='expired' for row in bindings['financial_bindings'])


def test_public_shared_bank_priority_has_real_nonlocal_effect():
    s=toy(entities=2)
    s['group']['shared_bank_limit_schedule'][0]['limit_pence']=1500000
    s['group']['shared_margin_priority']=['E02','E01']
    first,_,_,_=prove(s)
    assert entity(first,eid='E02')['shared_margin_principal']==500000
    assert entity(first,eid='E01')['shared_margin_principal']==0
    other=deepcopy(s);other['group']['shared_margin_priority']=['E01','E02']
    second,_,_,_=prove(other)
    assert entity(second,eid='E01')['shared_margin_principal']==500000
    assert entity(second,eid='E02')['shared_margin_principal']==0


def test_finite_shared_lp_commitment_reports_unfunded_shortfall_without_plug():
    s=toy(entities=2);s['group']['additional_lp_commitment_pence']=400000
    s['group']['shared_bank_limit_schedule'][0]['limit_pence']=2000000
    for i,e in enumerate(s['entities'],1):
        e.update(opening_cash_pence=0,opening_paid_in_capital_pence=1000000)
        s['assets'].append({'id':f'A{i:02d}','entity_id':e['id'],'description':'Operating asset',
            'commission_month':'2026-01-01','original_cost_pence':2000000,
            'opening_accumulated_depreciation_pence':0,'useful_life_months':120,'capex_category':'GROWTH'})
        for row in s['operating_inputs'][e['id']]:row.update(base_cash_revenue_pence=0,base_cash_opex_pence=200000)
    result,_,_,_=prove(s)
    assert entity(result,eid='E01')['funding_gap']==0
    assert entity(result,eid='E02')['funding_gap']>0
    assert not result['feasible']
    assert result['scenarios']['S01']['group_monthly'][0]['lp_calls_cumulative']==400000


def test_scenarios_reset_and_adjacent_day_count_and_tax_policies():
    s=toy(scenarios=3)
    s['loans'][0]['terms'][0]['day_count']='ACT_360'
    s['scenarios'][1]['monthly_schedule'][0]['revenue_factor_p12']=900000000000
    s['scenarios'][2]['monthly_schedule'][0]['annual_rate_spread_p12']=10000000000
    result,_,_,_=prove(s)
    assert len({entity(result,sid=sid)['cash_open'] for sid in s['scenario_ids']})==1
    assert entity(result,sid='S02')['revenue']==900000
    assert entity(result,sid='S03')['interest_accrual']>entity(result,sid='S01')['interest_accrual']


@pytest.mark.parametrize('principal,rate,days,basis',[
    (365,SCALE//2,1,365),(0,120000000000,31,365),
    (10**11,1200000000000,31,360),(12345678901,98765400000,29,365)])
def test_act_exact_helper_large_products_and_half_ties(principal,rate,days,basis):
    out=excel._Emitter(Workbook(),{},1000);out.support=out.sheet('Arithmetic',['Label','Value'])
    expression=out.act_interest(principal,rate,days,basis,['test'],'Exact ACT')
    final=out.calc(expression,'Posting',['test'])
    values={}
    for row in out.arithmetic:values[row['sheet'],row['cell']]=_evaluate(row['expression'],values)
    target=Fraction(principal*rate*days,SCALE*basis)
    expected=(2*target.numerator+target.denominator)//(2*target.denominator)
    match=excel.REF.fullmatch(final);assert match
    assert list(values.values())[-1]==expected
    assert all(abs(value)<2**53 for value in values.values())


@pytest.mark.parametrize('amount,denominator,expected',[(1,2000000,1),(-1,2000000,-1),(400000000000,75000000000,5333333)])
def test_ratio_exact_signed_half_ties_without_wide_product(amount,denominator,expected):
    out=excel._Emitter(Workbook(),{},1000);out.support=out.sheet('Arithmetic',['Label','Value'])
    out.calc(out.ratio(amount,denominator,['test'],'Ratio'),'Rounded',['test'])
    values={}
    for row in out.arithmetic:values[row['sheet'],row['cell']]=_evaluate(row['expression'],values)
    assert list(values.values())[-1]==expected
    assert all(abs(value)<2**53 for value in values.values())


def test_no_private_json_or_cached_answers_and_full_binding_inventory(tmp_path):
    result,book,binding,checked=prove(toy())
    output=tmp_path/'uncached.xlsx';book.save(output)
    assert not binding['cached_financial_values_written'] and not binding['independent_ledger_imported']
    assert not any('contract' in sheet.title.lower() and 'json' in sheet.title.lower() for sheet in book)
    assert not any(isinstance(cell.value,str) and '"schema_version"' in cell.value for sheet in book for row in sheet for cell in row)
    formulas={(sheet.title,cell.coordinate) for sheet in book for row in sheet for cell in row if cell.data_type=='f'}
    assert formulas==set(checked['definitions'])
    assert len(formulas)==binding['formula_count']
    assert all(row['semantic_owner'] is not None for row in binding['financial_bindings'])
    with ZipFile(output) as archive:
        for name in archive.namelist():
            if name.startswith('xl/worksheets/sheet') and name.endswith('.xml'):
                root=ElementTree.fromstring(archive.read(name))
                for cell in root.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c'):
                    if cell.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}f') is not None:
                        cached=cell.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
                        assert cached is None or cached.text is None


def test_implementation_has_no_forward_ledger_or_financial_helper_import():
    tree=ast.parse(inspect.getsource(excel))
    imported=[node.module for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)]
    assert not any(name and ('ledger' in name or 'validate' in name) for name in imported)
    assert not any(isinstance(node,ast.Name) and node.id=='simulate' for node in ast.walk(tree))


def test_formula_budget_and_existing_workbook_fail_closed():
    with pytest.raises(ValueError,match='budget'):excel.emit_heterogeneous_workbook(Workbook(),toy(),max_formulas=1)
    workbook=Workbook();workbook['Sheet']['A1']='prior material'
    with pytest.raises(ValueError,match='fresh'):excel.emit_heterogeneous_workbook(workbook,toy())
    side=Workbook();side['Sheet']['B1']='Existing off-axis value'
    with pytest.raises(ValueError,match='fresh'):excel.emit_heterogeneous_workbook(side,toy())


def test_noncontractual_workbook_date_epoch_is_rejected():
    book=Workbook();book.epoch=MAC_EPOCH
    with pytest.raises(ValueError,match='1900'):excel.emit_heterogeneous_workbook(book,toy())


def test_complete_six_entity_scope_has_all_legal_accounts_and_no_truncation():
    spec=json.loads((ROOT/'config/heterogeneous_contracts/prototype_v2.json').read_text())
    with pytest.raises(ValueError,match='allow_production'):excel.emit_heterogeneous_workbook(Workbook(),spec)
    workbook=Workbook();binding=excel.emit_heterogeneous_workbook(workbook,spec,allow_production=True)
    assert binding['complete_scope']=={'entities':6,'months':24,'scenarios':3}
    paths={tuple(row['expected_path']) for row in binding['financial_bindings']}
    for sid in spec['scenario_ids']:
        for e in spec['entities']:
            for t in range(24):
                assert {('scenarios',sid,'entities',e['id'],'monthly',t,name) for name in ENTITY_FIELDS}<=paths
        for loan in spec['loans']:
            assert {('scenarios',sid,'loans',loan['id'],'monthly',23,name) for name in LOAN_FIELDS}<=paths
        for asset in spec['assets']:
            assert {('scenarios',sid,'assets',asset['id'],'monthly',23,name) for name in ASSET_FIELDS}<=paths
        assert {('scenarios',sid,'group_monthly',23,name) for name in GROUP_FIELDS}<=paths
    assert binding['specification_sha256']==canonical_sha256(spec)
    assert binding['formula_count']<1000000
