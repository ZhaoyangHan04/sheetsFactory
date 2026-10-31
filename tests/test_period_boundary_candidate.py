"""Hand calculations and a separate offline formula-graph diagnostic; no LO."""
import ast
import calendar
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP, localcontext
import importlib.util
import json
from pathlib import Path

import openpyxl
from openpyxl import Workbook
from openpyxl.formula import Tokenizer
from openpyxl.utils.cell import range_boundaries
from openpyxl.utils.datetime import to_excel, from_excel
import pytest

from sheets_factory.workbook.period_boundary_portfolio import spec, oracle, excel

ROOT=Path(__file__).resolve().parents[1]


def builder():
    s=importlib.util.spec_from_file_location('period_candidate_builder',ROOT/'scripts/build_period_boundary_candidate.py')
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def test_hand_leap_day_maturity_quarter_repayment_and_cash_bridge():
    r=oracle.simulate(spec.prototype())
    assert r['periods'][2]=={'start':date(2028,2,1),'end':date(2028,2,29),'days':29}
    a=r['facilities']['F01'];b=r['facilities']['F02']
    assert a[0]['interest_pence']==99370
    assert a[2]['accrual_days']==14 and a[2]['interest_pence']==44877
    assert a[2]['principal_paid_pence']==18000000 and a[2]['closing_principal_pence']==0
    assert a[3]['accrual_days']==a[3]['interest_pence']==0
    assert b[0]['interest_pence']==53733 and b[0]['principal_paid_pence']==2000000
    assert b[2]['accrual_days']==29 and b[2]['interest_pence']==41889
    assert b[8]['accrual_days']==16 and b[8]['interest_pence']==13867
    assert b[8]['principal_paid_pence']==6000000
    assert r['cashflows'][0]['investment_pence']==606557
    assert r['cashflows'][0]['tax_pence']==1371724
    assert r['cashflows'][0]['equity_cash_pence']==1508616
    assert all(x['cash_check_pence']==0 for x in r['cashflows'])
    assert all(x['balance_check_pence']==0 for rows in r['facilities'].values() for x in rows)


def test_distinct_fiscal_year_growth_and_terminal_actual_date():
    r=oracle.simulate(spec.prototype());a=r['businesses']['B01'];b=r['businesses']['B02']
    assert a[0]['fiscal_year_days']==b[0]['fiscal_year_days']==366
    assert b[3]['growth_years']==0 and b[4]['growth_years']==1
    assert b[4]['revenue_pence']==9540000 and b[4]['fiscal_year_days']==365
    assert a[6]['growth_years']==0 and a[7]['growth_years']==1
    assert a[7]['revenue_pence']==14040000
    v=r['valuation'];assert v['opening_equity_cash_pence']==-32000000
    assert v['valuation_date']==date(2027,11,30) and v['settlement_date']==date(2029,1,14)
    assert v['items'][-1]['elapsed_days']==411
    assert v['equity_value_pence']==4003561


def test_posting_rounds_signed_half_pence_away_from_zero():
    assert oracle.posted(Decimal('0.5'))==1 and oracle.posted(Decimal('-0.5'))==-1


@pytest.mark.parametrize('fault',spec.FAULTS)
def test_each_boundary_fault_changes_money_not_just_a_header(fault):
    a=oracle.simulate(spec.prototype());b=oracle.simulate(spec.prototype(),faults=[fault])
    assert a['valuation']['equity_value_pence']!=b['valuation']['equity_value_pence']
    if fault=='unclipped_maturity':assert a['facilities']['F01'][2]['interest_pence']!=b['facilities']['F01'][2]['interest_pence']
    if fault=='immediate_terminal_settlement':
        assert a['valuation']['terminal_working_capital_pence']==b['valuation']['terminal_working_capital_pence']
        assert a['valuation']['items'][-1]['pv_pence']!=b['valuation']['items'][-1]['pv_pence']


class FormulaDiagnostic:
    """Test-only independent parser of the emitted native scalar formula subset."""
    PRECEDENCE={'=':1,'>':1,'<':1,'>=':1,'<=':1,'+':2,'-':2,'*':3,'/':3,'^':4}
    def __init__(self,book):self.book=book;self.cache={};self.active=set()
    def cell(self,sheet,coord):
        coord=coord.replace('$','');key=(sheet,coord)
        if key in self.cache:return self.cache[key]
        assert key not in self.active,'Formula cycle';self.active.add(key)
        value=self.book[sheet][coord].value
        if isinstance(value,str) and value.startswith('='):
            tokens=[x for x in Tokenizer(value).items if x.type!='WHITE-SPACE'];value,pos=self.expression(tokens,0,sheet)
            assert pos==len(tokens)
        elif isinstance(value,(date,datetime)):value=Decimal(str(to_excel(value)))
        elif isinstance(value,(int,float)):value=Decimal(str(value))
        self.active.remove(key);self.cache[key]=value;return value
    def refs(self,text,sheet):
        if '!' in text:sheet,text=text.rsplit('!',1);sheet=sheet.strip("'")
        if ':' not in text:return self.cell(sheet,text)
        a,b,c,d=range_boundaries(text.replace('$',''))
        return [self.cell(sheet,openpyxl.utils.get_column_letter(x)+str(y)) for y in range(b,d+1) for x in range(a,c+1)]
    def expression(self,tokens,pos,sheet,minimum=0):
        token=tokens[pos];pos+=1
        if token.type=='OPERATOR-PREFIX':
            left,pos=self.expression(tokens,pos,sheet,4);left=-left if token.value=='-' else left
        elif token.type=='PAREN' and token.subtype=='OPEN':
            left,pos=self.expression(tokens,pos,sheet);assert tokens[pos].subtype=='CLOSE';pos+=1
        elif token.type=='FUNC' and token.subtype=='OPEN':
            args=[]
            while tokens[pos].subtype!='CLOSE':
                value,pos=self.expression(tokens,pos,sheet);args.append(value)
                if tokens[pos].type=='SEP':pos+=1
                else:break
            assert tokens[pos].subtype=='CLOSE';pos+=1;left=self.function(token.value[:-1].upper(),args)
        elif token.type=='OPERAND':
            left=Decimal(token.value) if token.subtype=='NUMBER' else token.value[1:-1] if token.subtype=='TEXT' else self.refs(token.value,sheet)
        else:raise AssertionError(token)
        while pos<len(tokens) and tokens[pos].type=='OPERATOR-INFIX' and self.PRECEDENCE[tokens[pos].value]>=minimum:
            op=tokens[pos].value;prec=self.PRECEDENCE[op];right,pos=self.expression(tokens,pos+1,sheet,prec if op=='^' else prec+1)
            if op=='+':left=left+right
            elif op=='-':left=left-right
            elif op=='*':left=left*right
            elif op=='/':left=left/right
            elif op=='^':left=left**right
            elif op=='=':left=left==right
            elif op=='>':left=left>right
            elif op=='<':left=left<right
            elif op=='>=':left=left>=right
            elif op=='<=':left=left<=right
        return left,pos
    def function(self,name,args):
        flatten=[v for a in args for v in (a if isinstance(a,list) else [a])]
        if name=='ROUND':return args[0].quantize(Decimal(10)**-int(args[1]),rounding=ROUND_HALF_UP)
        if name=='SUM':return sum(flatten,Decimal(0))
        if name=='MIN':return min(flatten)
        if name=='MAX':return max(flatten)
        if name=='IF':return args[1] if args[0] else args[2]
        if name=='AND':return all(args)
        if name=='MOD':return args[0]%args[1]
        if name in ['YEAR','MONTH']:
            d=from_excel(float(args[0]));return Decimal(d.year if name=='YEAR' else d.month)
        if name=='DATE':
            serial=int(args[0])*12+int(args[1])-1;d=date(serial//12,serial%12+1,1)+timedelta(days=int(args[2])-1)
            return Decimal(str(to_excel(d)))
        if name in ['EDATE','EOMONTH']:
            d=from_excel(float(args[0]));serial=d.year*12+d.month-1+int(args[1]);y,m=serial//12,serial%12+1
            day=calendar.monthrange(y,m)[1] if name=='EOMONTH' else min(d.day,calendar.monthrange(y,m)[1])
            return Decimal(str(to_excel(date(y,m,day))))
        raise AssertionError(name)


@pytest.mark.parametrize('faults',[(),*[(x,) for x in spec.FAULTS],spec.FAULTS])
def test_every_emitted_derived_value_matches_independent_forward_oracle(faults):
    public=spec.prototype();book=Workbook();bindings=excel.emit_workbook(book,public,faults=faults)
    expected=builder().expected_values(bindings,oracle.simulate(public,faults=faults));diagnostic=FormulaDiagnostic(book)
    assert len(expected)==657 and book.sheetnames==list(excel.SHEETS)
    with localcontext() as ctx:
        ctx.prec=50
        for b in bindings['derived']:
            v=expected[b['sheet'],b['cell']]
            target=Decimal(str(to_excel(v))) if b['kind']=='date' else Decimal(v)/100 if b['kind']=='money_pence' else Decimal(v)
            assert diagnostic.cell(b['sheet'],b['cell'])==target,(faults,b)


def test_financial_implementations_have_no_cross_import_or_cached_gold_reader():
    emitter=ast.parse(Path(excel.__file__).read_text());reference=ast.parse(Path(oracle.__file__).read_text())
    imports=lambda tree:[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    assert not any(x and ('oracle' in x or 'openpyxl' in x) for x in imports(reference))
    assert not any(x and 'oracle' in x for x in imports(emitter))
    assert 'openpyxl' not in Path(oracle.__file__).read_text().lower()


def test_configurable_horizon_and_module_count_preserve_full_oracle_mapping():
    s=spec.prototype();s['months']=6;s['businesses']=s['businesses'][:1];s['facilities']=s['facilities'][:1]
    book=Workbook();bindings=excel.emit_workbook(book,s)
    result=oracle.simulate(s);expected=builder().expected_values(bindings,result);diagnostic=FormulaDiagnostic(book)
    assert len(result['periods'])==6 and len(result['businesses'])==len(result['facilities'])==1
    assert len(expected)<657
    with localcontext() as ctx:
        ctx.prec=50
        for b in bindings['derived']:
            v=expected[b['sheet'],b['cell']]
            target=Decimal(str(to_excel(v))) if b['kind']=='date' else Decimal(v)/100 if b['kind']=='money_pence' else Decimal(v)
            assert diagnostic.cell(b['sheet'],b['cell'])==target


def test_offline_pair_all_derived_FM_blank_DBG_joint_and_native_units(tmp_path):
    m=builder();manifest=m.build(spec.prototype(),tmp_path/'pair');v=json.loads(Path(manifest['path']).read_text())
    assert v['formula_count']==v['FM_D_count']==657 and v['sheet_count']==7
    assert v['DBG_formula_edit_count']==85 and v['DBG_D_count']>100
    assert v['model_calls']==v['actual_LO_calls']==v['solver_calls']==v['Harbor_calls']==0
    assert v['oracle_seeded_caches_not_actual_calculation'] and not v['qualified']
    assert not v['evidence_transfer']['transfer_hypothesis_validated']
    assert not v['evidence_transfer']['official_workbook_or_gold_or_task_used_as_seed']
    books={k:openpyxl.load_workbook(v[k]['path'],data_only=False) for k in ['gold','FM_input','DBG_input']}
    values=openpyxl.load_workbook(v['gold']['path'],data_only=True)
    plan=json.loads(Path(v['plan']['path']).read_text())
    for row in plan['FM_all_derived_masks']:assert books['FM_input'][row['sheet']][row['cell']].value is None
    for row in plan['DBG_formula_edits']:
        assert books['DBG_input'][row['sheet']][row['cell']].value==row['before']
        assert books['gold'][row['sheet']][row['cell']].value==row['after']
    assert values['Valuation']['B7'].value==40035.61
    assert values['Fiscal Calendar']['B7'].value==datetime(2028,2,29)
    assert books['gold']['Assumptions']['C12'].value==130000 and books['gold']['Assumptions']['D12'].number_format=='0.00%'
    assert all('{' not in str(c.value) for ws in books['gold'] for c in ws._cells.values() if isinstance(c.value,str) and not c.value.startswith('='))
    targets={(x['sheet'],x['cell']) for x in plan['FM_all_derived_masks']}
    for ws in books['gold']:
        for cell in ws._cells.values():
            if (ws.title,cell.coordinate) in targets:continue
            for k in ['FM_input','DBG_input']:
                actual=books[k][ws.title][cell.coordinate]
                assert actual.value==cell.value and actual.number_format==cell.number_format
    for w in [*books.values(),values]:w.close()


@pytest.mark.parametrize('bad',['boolean_months','outside_maturity','basis','negative_lag'])
def test_scope_and_financial_contract_reject_invalid_primitives(bad):
    s=spec.prototype()
    if bad=='boolean_months':s['months']=True
    if bad=='outside_maturity':s['facilities'][0]['maturity_date']='2035-01-01'
    if bad=='basis':s['facilities'][0]['day_count_basis']=364
    if bad=='negative_lag':s['terminal_settlement_lag_days']=-1
    with pytest.raises((AssertionError,ValueError)):spec.load_spec(s)
