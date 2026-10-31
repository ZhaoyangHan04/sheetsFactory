"""Independent native-table Excel close for the heterogeneous public contracts.

This module compiles raw contract primitives to formulas. It never imports or
calls the independent forward journal, and never populates cached answers.
"""
from __future__ import annotations

import calendar
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from openpyxl.utils.datetime import WINDOWS_EPOCH, to_excel

# Frozen arithmetic infrastructure only; none of the old business close is used.
from ..entity_group.excel import _parts
from .spec import (ASSET_FIELDS, ENTITY_FIELDS, FLAG_FIELDS, GROUP_FIELDS,
                   GROUP_SUM_FIELDS, LOAN_FIELDS, MONEY_FIELDS, PHASES, RULES,
                   SCALE, canonical_sha256, load_spec)

MAX_INTEGER = 2**53
REF = re.compile(r"^'(?:[^']|'')+'!\$[A-Z]+\$[1-9][0-9]*$")
MONEY_FORMAT = '#,##0.00;[Red](#,##0.00);0.00'
PUBLIC_NOTES = (*RULES, 'Closed facilities have no current coupon, principal instalment or DSCR test. A blank non-applicable covenant display is intentional.')


def _ref(sheet, row, column='B'):
    return "'" + sheet.replace("'", "''") + "'!$" + column + '$' + str(row)


def _sum(*values): return ('sum', *values)
def _sub(a, b): return ('sub', a, b)
def _mul(a, b): return ('mul', a, b)
def _div(a, b): return ('div', a, b)
def _min(*a): return ('min', *a)
def _max(*a): return ('max', *a)
def _if(c, a, b): return ('if', c, a, b)
def _eq(a, b): return ('eq', a, b)
def _le(a, b): return ('le', a, b)
def _lt(a, b): return ('lt', a, b)
def _ge(a, b): return ('ge', a, b)
def _and(*a): return ('and', *a)
def _or(*a): return ('or', *a)
def _not(a): return _eq(a, 0)
def _round(a, b): return ('rounddiv', a, b)
def _period(d): return _sum(_mul(('year', d), 12), ('month', d))


def expression_formula(expression):
    """Render the small exact-expression interface shared with the auditor."""
    if type(expression) is bool: return '1' if expression else '0'
    if type(expression) is int: return str(expression)
    if isinstance(expression, str):
        return expression if REF.fullmatch(expression) else '"' + expression.replace('"', '""') + '"'
    if not isinstance(expression, (tuple, list)) or not expression:
        raise ValueError('An explicit heterogeneous-contract expression is required')
    op, *values = expression
    args = [expression_formula(value) for value in values]
    operators = {'sub':'-', 'mul':'*', 'div':'/', 'lt':'<', 'le':'<=', 'eq':'=', 'ge':'>='}
    if op == 'sum': return '(' + '+'.join(args) + ')' if args else '0'
    if op in operators and len(args) == 2: return '(' + args[0] + operators[op] + args[1] + ')'
    if op in {'if','min','max','and','or','abs','mod','year','month'}:
        return op.upper() + '(' + ','.join(args) + ')'
    if op in {'floordiv','ceildiv','rounddiv'} and len(args) == 2:
        return {'floordiv':f'INT({args[0]}/{args[1]})',
                'ceildiv':f'(-INT(-{args[0]}/{args[1]}))',
                'rounddiv':f'ROUND({args[0]}/{args[1]},0)'}[op]
    if op in {'round_product','product_whole','product_remainder'} and len(args) == 2:
        whole, remainder, negative = _parts(*args)
        if op == 'round_product':
            return f'(IF({negative},-1,1)*({whole}+IF({remainder}>={SCALE//2},1,0)))'
        if op == 'product_whole':
            return f'IF({negative},-{whole}-IF({remainder}>0,1,0),{whole})'
        return f'IF({negative},IF({remainder}=0,0,{SCALE}-{remainder}),{remainder})'
    raise ValueError('Unsupported heterogeneous-contract expression: ' + str(op))


def _date(value): return int(to_excel(datetime.fromisoformat(value)))


class _Emitter:
    def __init__(self, book, specification, maximum):
        self.book, self.spec, self.maximum = book, specification, maximum
        self.arithmetic, self.financial, self.inputs, self.literals = [], [], [], []
        self.raw, self.encoded, self.rows, self.sheets = {}, {}, {}, {}
        self.support = None

    def sheet(self, name, headers):
        if name not in self.sheets:
            sheet = self.book.create_sheet(name)
            self.sheets[name] = sheet
            self.rows[name] = 1
            for column, text in enumerate(headers, 1): self.literal(sheet, 1, column, text)
        return self.sheets[name]

    def literal(self, sheet, row, column, value, *, kind=None, number_format=None):
        cell = sheet.cell(row, column, value)
        if number_format: cell.number_format = number_format
        self.literals.append({'sheet':sheet.title,'cell':cell.coordinate,'value':value,
                              'kind':kind or ('integer' if type(value) is int else 'text')})
        return _ref(sheet.title, row, cell.column_letter)

    def input(self, sheet, row, column, path, value, kind='text', scale=1, number_format=None):
        if kind == 'date': stored = _date(value)
        elif type(value) is bool: stored = int(value)
        elif isinstance(value, int): stored = value / scale if scale != 1 else value
        elif value is None: stored = None
        else: stored = value
        cell = sheet.cell(row, column, stored)
        if number_format: cell.number_format = number_format
        reference = _ref(sheet.title,row,cell.column_letter)
        self.inputs.append({'sheet':sheet.title,'cell':cell.coordinate,'path':list(path),
            'kind':kind,'worksheet_scale':scale,'stored_value':stored,'epoch':'1900' if kind in ['date','nullable_date'] else None})
        self.raw[tuple(path)] = reference
        return reference

    def primitive(self, path):
        path = tuple(path)
        if path in self.encoded: return self.encoded[path]
        record = next(record for record in self.inputs if tuple(record['path']) == path)
        reference = self.raw[path]
        if record['kind']=='nullable_date':reference=_if(_eq(reference,''),'',reference)
        if record['worksheet_scale'] != 1:
            reference = self.calc(_round(_mul(reference,record['worksheet_scale']),1),
                'Provided input integer conversion', provided_input=list(path))
        self.encoded[path] = reference
        return reference

    def calc(self, expression, label, owner=None, *, expected_path=None, kind='money_pence', scale=1,
             complete=False, provided_input=None, vintage=None):
        if len(self.arithmetic) >= self.maximum:
            raise ValueError('The complete formula budget was exceeded; nothing was truncated')
        sheet = self.support
        self.rows[sheet.title] += 1
        row = self.rows[sheet.title]
        if row > 1048576: raise ValueError('The complete worksheet exceeded the Excel row limit')
        self.literal(sheet,row,1,label)
        formula = '=' + expression_formula(expression)
        if len(formula)>8192: raise ValueError('A formula exceeds the Excel formula-length limit')
        sheet.cell(row,2,formula)
        reference = _ref(sheet.title,row)
        common = {'sheet':sheet.title,'cell':'B'+str(row),'expression':deepcopy(expression),'formula':formula,
            'semantic_owner':deepcopy(owner),'is_complete_answer':bool(complete)}
        if provided_input is not None: common['provided_input'] = provided_input
        self.arithmetic.append(common)
        if expected_path is not None:
            entry = {**deepcopy(common),'expected_path':list(expected_path),'kind':kind,'worksheet_scale':scale}
            if vintage: entry.update(vintage)
            self.financial.append(entry)
        return reference

    def display(self, sheet, identity, month, field, value, path, *, kind='money_pence', owner=None, vintage=None):
        self.rows[sheet.title] += 1
        row = self.rows[sheet.title]
        self.literal(sheet,row,1,identity)
        self.literal(sheet,row,2,_date(month),kind='integer',number_format='mmm-yy')
        self.literal(sheet,row,3,field.replace('_',' ').capitalize())
        scale = 100 if kind == 'money_pence' else SCALE if kind == 'rate_p12' else 1000000 if kind == 'nullable_ratio_micro' else 1
        expression = value if scale == 1 else _if(_eq(value,''),'',_div(value,scale)) if kind.startswith('nullable') else _div(value,scale)
        formula = '=' + expression_formula(expression)
        if len(self.arithmetic)>=self.maximum: raise ValueError('The complete formula budget was exceeded')
        sheet.cell(row,4,formula).number_format = MONEY_FORMAT if kind=='money_pence' else '0.000000' if kind=='nullable_ratio_micro' else '0.00%' if kind=='rate_p12' else 'mmm-yy' if kind=='date' else 'General'
        common={'sheet':sheet.title,'cell':'D'+str(row),'expression':deepcopy(expression),'formula':formula,
            'semantic_owner':deepcopy(owner or path),'is_complete_answer':kind=='money_pence'}
        self.arithmetic.append(common)
        entry={**deepcopy(common),'expected_path':list(path),'kind':kind,'worksheet_scale':scale}
        if vintage: entry.update(vintage)
        self.financial.append(entry)

    def act_interest(self, principal, rate, days, basis, owner, label):
        whole=self.calc(('product_whole',principal,rate),label+' product whole',owner)
        rem=self.calc(('product_remainder',principal,rate),label+' product remainder',owner)
        rem_days=self.calc(_mul(rem,days),label+' remainder days',owner)
        integer=self.calc(_sum(_mul(whole,days),('floordiv',rem_days,SCALE)),label+' day-adjusted whole',owner)
        rem_after=self.calc(('mod',rem_days,SCALE),label+' day-adjusted remainder',owner)
        quotient=self.calc(('floordiv',integer,basis),label+' ACT whole',owner)
        final_rem=self.calc(_sum(_mul(('mod',integer,basis),SCALE),rem_after),label+' ACT remainder',owner)
        return _sum(quotient,_if(_ge(_mul(final_rem,2),_mul(basis,SCALE)),1,0))

    def ratio(self, amount, denominator, owner, label):
        """Exact signed millionths; bounded base100 division, no wide multiply."""
        divisor=self.calc(_max(1,denominator),label+' display divisor',owner)
        absolute=self.calc(('abs',amount),label+' display numerator',owner)
        quotient=remainder=0
        # abs(CFADS)<2^53, eight base100 digits cover it; add 3 digits for 10^6.
        digits=[('mod',('floordiv',absolute,100**index),100) for index in range(7,-1,-1)]+[0,0,0]
        for index,digit in enumerate(digits):
            coefficient=self.calc(_sum(_mul(remainder,100),digit),label+' ratio coefficient '+str(index),owner)
            quotient=self.calc(_sum(_mul(quotient,100),('floordiv',coefficient,divisor)),label+' ratio quotient '+str(index),owner)
            remainder=self.calc(('mod',coefficient,divisor),label+' ratio remainder '+str(index),owner)
        rounded=_sum(quotient,_if(_ge(remainder,('ceildiv',divisor,2)),1,0))
        signed=_if(_lt(amount,0),_sub(0,rounded),rounded)
        return _if(_lt(('abs',signed),MAX_INTEGER),signed,'DISPLAY INTEGER OVERFLOW')


def _public_inputs(out):
    s=out.spec
    notes=out.sheet('Contract Notes',['Heterogeneous debt and tax contracts','Public policy'])
    for index,text in enumerate(PUBLIC_NOTES,2): out.literal(notes,index,1,'Policy '+str(index-1));out.literal(notes,index,2,text)
    for index,text in enumerate(PHASES,len(PUBLIC_NOTES)+3):out.literal(notes,index,1,'Close phase');out.literal(notes,index,2,text)
    calendar_sheet=out.sheet('Calendar',['Month','Month end','Actual days','Quarter end'])
    out.calendar=[]
    for t,month in enumerate(s['months']):
        d=datetime.fromisoformat(month);days=calendar.monthrange(d.year,d.month)[1];row=t+2
        date_ref=out.input(calendar_sheet,row,1,('months',t),month,'date',number_format='mmm-yy')
        end=out.literal(calendar_sheet,row,2,_date(d.replace(day=days).date().isoformat()),kind='integer',number_format='dd-mmm-yyyy')
        day=out.literal(calendar_sheet,row,3,days)
        quarter=out.literal(calendar_sheet,row,4,int(d.month%3==0))
        out.calendar.append((date_ref,end,day,quarter))
    entity_sheet=out.sheet('Entity Policies',['Entity','Name','Tax policy','Tax rate','Interest cap','Interest carry months','Loss carry months','Covenant policy','Minimum DSCR times','Minimum cash GBP','Reserve target GBP','Additional LP GBP','Opening restriction','Opening cure count'])
    entity_columns=[('id','text',1,None),('name','text',1,None),('tax_policy','text',1,None),('tax_rate_p12','rate_p12',SCALE,'0.00%'),('interest_cap_fraction_p12','rate_p12',SCALE,'0.00%'),('interest_carry_months','integer',1,None),('loss_carry_months','integer',1,None),('dscr_policy','text',1,None),('dscr_threshold_p12','rate_p12',SCALE,'0.00'),('minimum_cash_pence','money_pence',100,MONEY_FORMAT),('reserve_target_pence','money_pence',100,MONEY_FORMAT),('additional_lp_commitment_pence','money_pence',100,MONEY_FORMAT),('opening_trap','flag',1,None),('opening_cure_count','integer',1,None)]
    opening=out.sheet('Opening Balances',['Entity','Cash GBP','Restricted cash GBP','Paid-in capital GBP','Retained earnings GBP','Income tax payable GBP'])
    for i,e in enumerate(s['entities']):
        for col,(key,kind,scale,fmt) in enumerate(entity_columns,1):out.input(entity_sheet,i+2,col,('entities',i,key),e[key],kind,scale,fmt)
        out.literal(opening,i+2,1,e['id'])
        for col,key in enumerate(['opening_cash_pence','opening_restricted_cash_pence','opening_paid_in_capital_pence','opening_retained_earnings_pence','opening_tax_payable_pence'],2):out.input(opening,i+2,col,('entities',i,key),e[key],'money_pence',100,MONEY_FORMAT)
    loans=out.sheet('Facilities',['Facility','Entity','Contract type','Opening principal GBP','Opening accrued interest GBP'])
    terms=out.sheet('Facility Terms',['Term','Facility','Effective month','Annual quote','Day-count basis','Local limit GBP','Maturity','Draw cutoff','Voluntary repayment fraction','Next coupon month'])
    row=1
    for i,loan in enumerate(s['loans']):
        for col,key in enumerate(['id','entity_id','type','opening_principal_pence','opening_accrued_interest_pence'],1):out.input(loans,i+2,col,('loans',i,key),loan[key],'money_pence' if key.endswith('pence') else 'text',100 if key.endswith('pence') else 1,MONEY_FORMAT if key.endswith('pence') else None)
        for j,term in enumerate(loan['terms']):
            row+=1
            for col,key in enumerate(['id',None,'effective_month','annual_rate_p12','day_count','local_limit_pence','maturity_date','draw_cutoff_month','optional_repayment_fraction_p12','next_coupon_month'],1):
                if key is None:out.literal(terms,row,col,loan['id']);continue
                value=term[key]
                kind=('date' if value is not None else 'nullable_date') if key.endswith(('month','date')) else 'money_pence' if key.endswith('pence') else 'rate_p12' if key.endswith('p12') else 'text'
                scale=100 if kind=='money_pence' else SCALE if kind=='rate_p12' else 1
                fmt=MONEY_FORMAT if kind=='money_pence' else '0.00%' if kind=='rate_p12' else 'mmm-yy' if kind in ['date','nullable_date'] else None
                out.input(terms,row,col,('loans',i,'terms',j,key),value,kind,scale,fmt)
    assets=out.sheet('Asset Register',['Asset','Entity','Description','Commission month','Original cost GBP','Opening depreciation GBP','Useful life months','Capex class'])
    for i,a in enumerate(s['assets']):
        for col,key in enumerate(['id','entity_id','description','commission_month','original_cost_pence','opening_accumulated_depreciation_pence','useful_life_months','capex_category'],1):
            kind='date' if key=='commission_month' else 'money_pence' if key.endswith('pence') else 'integer' if key=='useful_life_months' else 'text'
            out.input(assets,i+2,col,('assets',i,key),a[key],kind,100 if kind=='money_pence' else 1,MONEY_FORMAT if kind=='money_pence' else 'mmm-yy' if kind=='date' else None)
    ops=out.sheet('Operating Forecast',['Entity','Month','Cash revenue GBP','Cash operating cost GBP']);row=1
    for eid,values in s['operating_inputs'].items():
        for t,value in enumerate(values):
            row+=1;out.literal(ops,row,1,eid)
            for col,key in enumerate(['month','base_cash_revenue_pence','base_cash_opex_pence'],2):out.input(ops,row,col,('operating_inputs',eid,t,key),value[key],'date' if key=='month' else 'money_pence',1 if key=='month' else 100,'mmm-yy' if key=='month' else MONEY_FORMAT)
    scenarios=out.sheet('Scenario Assumptions',['Scenario','Month','Revenue factor','Operating cost factor','Annual rate spread']);row=1
    for z,scenario in enumerate(s['scenarios']):
        for t,value in enumerate(scenario['monthly_schedule']):
            row+=1;out.literal(scenarios,row,1,scenario['id'])
            out.input(scenarios,row,2,('scenarios',z,'monthly_schedule',t,'month'),value['month'],'date',number_format='mmm-yy')
            for col,key in enumerate(['revenue_factor_p12','opex_factor_p12','annual_rate_spread_p12'],3):out.input(scenarios,row,col,('scenarios',z,'monthly_schedule',t,key),value[key],'rate_p12',SCALE,'0.00%')
    group=out.sheet('Portfolio Funding',['Contract item','Effective month','Amount GBP'])
    out.literal(group,2,1,'Additional LP commitment');out.input(group,2,3,('group','additional_lp_commitment_pence'),s['group']['additional_lp_commitment_pence'],'money_pence',100,MONEY_FORMAT)
    for j,term in enumerate(s['group']['shared_bank_limit_schedule']):
        row=j+3;out.literal(group,row,1,'Shared bank limit');out.input(group,row,2,('group','shared_bank_limit_schedule',j,'effective_month'),term['effective_month'],'date',number_format='mmm-yy');out.input(group,row,3,('group','shared_bank_limit_schedule',j,'limit_pence'),term['limit_pence'],'money_pence',100,MONEY_FORMAT)
    priority=out.sheet('Allocation Priorities',['Allocation','Priority','Entity']);row=1
    for key,label in [('shared_margin_priority','Shared margin'),('bank_funding_priority','Bank funding'),('lp_funding_priority','LP funding')]:
        for j,eid in enumerate(s['group'][key]):
            row+=1;out.literal(priority,row,1,label);out.literal(priority,row,2,j+1);out.input(priority,row,3,('group',key,j),eid)
    vintage=out.sheet('Opening Tax Attributes',['Entity','Attribute','Origin month','Amount GBP']);row=1
    for i,e in enumerate(s['entities']):
        for key,label in [('opening_interest_carry','Denied interest'),('opening_tax_losses','Tax loss')]:
            for j,value in enumerate(e[key]):
                row+=1;out.literal(vintage,row,1,e['id']);out.literal(vintage,row,2,label)
                out.input(vintage,row,3,('entities',i,key,j,'origin_month'),value['origin_month'],'date',number_format='mmm-yy')
                out.input(vintage,row,4,('entities',i,key,j,'amount_pence'),value['amount_pence'],'money_pence',100,MONEY_FORMAT)


def emit_heterogeneous_workbook(book, specification, *, max_formulas=1000000, allow_production=False):
    """Compile the complete stated scope, with no journal, cache or answer input."""
    spec=load_spec(specification)
    if spec['dimension_mode']!='toy' and not allow_production:
        raise ValueError('Full native-table compilation requires explicit allow_production=True')
    if type(max_formulas) is not int or max_formulas<=0: raise ValueError('A positive complete formula budget is required')
    if book.epoch!=WINDOWS_EPOCH:raise ValueError('The native date contract requires the 1900 workbook epoch')
    if book.defined_names or getattr(book,'_external_links',[]):raise ValueError('A fresh workbook cannot contain names or external links')
    if book.sheetnames and not (book.sheetnames==['Sheet'] and book['Sheet'].max_row==book['Sheet'].max_column==1 and all(cell.value is None for cell in book['Sheet']._cells.values())):
        raise ValueError('A fresh empty workbook is required')
    if book.sheetnames:book.remove(book[book.sheetnames[0]])
    out=_Emitter(book,spec,max_formulas)
    _public_inputs(out)
    out.support=out.sheet('Input Calculations',['Provided assumption conversion','Exact integer'])
    # Primitive-only unit conversions are explicitly distinct from financial answers.
    for record in out.inputs:
        if record['worksheet_scale']!=1:out.primitive(record['path'])
    for scenario_index,scenario in enumerate(spec['scenarios']):
        _compile_scenario(out,scenario_index,scenario)
    formulas={(r['sheet'],r['cell']) for r in out.arithmetic}
    assert len(formulas)==len(out.arithmetic)
    assert all((r['sheet'],r['cell']) in formulas for r in out.financial)
    arithmetic_source=Path(__file__).parents[1]/'entity_group/excel.py'
    return {'binding_version':1,'kind':'independent_heterogeneous_contracts_excel_bindings',
        'specification_sha256':canonical_sha256(spec),'sheetnames':book.sheetnames,
        'formula_count':len(out.arithmetic),'financial_bindings':out.financial,
        'arithmetic_bindings':out.arithmetic,'input_bindings':out.inputs,'literal_bindings':out.literals,
        'public_notes':list(PUBLIC_NOTES),'phases':list(PHASES),'cached_financial_values_written':False,
        'independent_ledger_imported':False,'complete_scope':{'entities':len(spec['entities']),'months':len(spec['months']),'scenarios':len(spec['scenarios'])},
        'generic_arithmetic_dependency':{'path':str(arithmetic_source),'sha256':hashlib.sha256(arithmetic_source.read_bytes()).hexdigest()},
        'implementation':{'path':str(Path(__file__).resolve()),'sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}


def _compile_scenario(out, scenario_index, scenario):
    spec=out.spec;sid=scenario['id']
    out.support=out.sheet(sid+' Calculations',['Calculation and legal account','Exact internal amount'])
    reports={name:out.sheet(sid+' '+name,['Entity or facility','Month','Account','GBP / stated unit'])
        for name in ['Entity Close','Loan Close','Asset Close','Interest FIFO','Loss FIFO','Group Close']}
    entities={e['id']:e for e in spec['entities']}
    indices={e['id']:i for i,e in enumerate(spec['entities'])}
    loan_index={l['entity_id']:i for i,l in enumerate(spec['loans'])}
    state={};asset_state={};history={eid:[] for eid in entities}
    interest_queues={};loss_queues={};origins={}
    def ip(*path): return out.primitive(path)
    def owner(eid,t,field):return ['scenarios',sid,'entities',eid,'monthly',t,field]
    def number_kind(field):
        if field in MONEY_FIELDS:return 'money_pence'
        if field=='month':return 'date'
        if field in ['term_id','tax_policy','dscr_policy']:return 'text'
        if field=='test_pass':return 'nullable_flag'
        if field=='dscr_ratio_millionths':return 'nullable_ratio_micro'
        if field=='feasible':return 'flag'
        if field in FLAG_FIELDS:return 'flag'
        return 'integer'
    def field(row,eid,t,name,expression):
        path=owner(eid,t,name)
        result=out.calc(expression,f'{eid} {spec["months"][t]} {name.replace("_"," ")}',path,
            expected_path=path,kind=number_kind(name),complete=name in MONEY_FIELDS)
        row[name]=result
        return result
    def selected(loan_i,key,month):
        terms=spec['loans'][loan_i]['terms']
        result=ip('loans',loan_i,'terms',0,key)
        for j in range(1,len(terms)):
            result=_if(_ge(month,ip('loans',loan_i,'terms',j,'effective_month')),ip('loans',loan_i,'terms',j,key),result)
        return result
    def group_limit(month):
        result=ip('group','shared_bank_limit_schedule',0,'limit_pence')
        for j in range(1,len(spec['group']['shared_bank_limit_schedule'])):
            result=_if(_ge(month,ip('group','shared_bank_limit_schedule',j,'effective_month')),ip('group','shared_bank_limit_schedule',j,'limit_pence'),result)
        return result
    for eid,e in entities.items():
        i=indices[eid];li=loan_index[eid]
        state[eid]={'cash':ip('entities',i,'opening_cash_pence'),
            'reserve':ip('entities',i,'opening_restricted_cash_pence'),
            'principal':ip('loans',li,'opening_principal_pence'),
            'interest':ip('loans',li,'opening_accrued_interest_pence'),
            'tax':ip('entities',i,'opening_tax_payable_pence'),
            'paid':ip('entities',i,'opening_paid_in_capital_pence'),
            'retained':ip('entities',i,'opening_retained_earnings_pence'),'called':0,
            'trap':ip('entities',i,'opening_trap'),'cure':ip('entities',i,'opening_cure_count'),
            'closed':0,'instalment':0,'term_id':''}
        for public_key,queue in [('opening_interest_carry',interest_queues),('opening_tax_losses',loss_queues)]:
            queue[eid]={}
            for j,value in enumerate(e[public_key]):
                origin=value['origin_month'];origins[origin]=ip('entities',i,public_key,j,'origin_month')
                queue[eid][origin]=ip('entities',i,public_key,j,'amount_pence')
    for ai,asset in enumerate(spec['assets']):
        before=_lt(ip('assets',ai,'commission_month'),out.calendar[0][0])
        asset_state[asset['id']]={'cost':_if(before,ip('assets',ai,'original_cost_pence'),0),
            'accumulated':_if(before,ip('assets',ai,'opening_accumulated_depreciation_pence'),0)}

    def vintage_close(eid,t,queue,remaining,current_created,carry,category):
        """Complete finite FIFO origin window; expired current rows remain visible."""
        month=spec['months'][t];month_ref=out.calendar[t][0]
        result={};summary={name:[] for name in ['opening','expired','used','created','closing']}
        path=['scenarios',sid,category,eid,'monthly',t]
        cap=remaining
        for origin,opening in sorted(queue.items()):
            origin_ref=origins[origin]
            expiry=_if(_lt(carry,_sub(_period(month_ref),_period(origin_ref))),opening,0)
            values={'opening':opening,'expired':expiry,'created':0}
            values['used']=_min(_sub(opening,expiry),cap)
            values['closing']=_sub(_sub(opening,expiry),values['used'])
            actual={}
            for name,expression in values.items():
                semantic=[*path,'origin',origin,name]
                metadata={'vintage_origin':origin,'vintage_field':name}
                actual[name]=out.calc(expression,f'{eid} {month} {category} {origin} {name}',semantic,
                    expected_path=path,kind='money_pence',complete=True,vintage=metadata)
                out.display(reports['Interest FIFO' if category=='interest_vintages' else 'Loss FIFO'],
                    eid+' / '+origin,month,name,actual[name],path,owner=semantic,vintage=metadata)
                summary[name].append(actual[name])
            cap=out.calc(_sub(cap,actual['used']),f'{eid} {month} FIFO capacity after {origin}',[*path,'used'])
            # Layout pruning uses only declared dates/window, never a calculated balance.
            age=(int(month[:4])*12+int(month[5:7]))-(int(origin[:4])*12+int(origin[5:7]))
            window=entities[eid]['interest_carry_months' if category=='interest_vintages' else 'loss_carry_months']
            if age<=window:result[origin]=actual['closing']
        if callable(current_created):current_created=current_created(cap)
        values={'opening':0,'expired':0,'used':0,'created':current_created,'closing':current_created}
        for name,expression in values.items():
            semantic=[*path,'origin',month,name];metadata={'vintage_origin':month,'vintage_field':name}
            value=out.calc(expression,f'{eid} {month} {category} current {name}',semantic,
                expected_path=path,kind='money_pence',complete=True,vintage=metadata)
            out.display(reports['Interest FIFO' if category=='interest_vintages' else 'Loss FIFO'],
                eid+' / '+month,month,name,value,path,owner=semantic,vintage=metadata)
            summary[name].append(value)
            if name=='closing':result[month]=value
        totals={}
        for name,values in summary.items():
            totals[name]=out.calc(_sum(*values),f'{eid} {month} {category} total {name}',[*path,name],
                expected_path=[*path,name],kind='money_pence',complete=True)
        return result,totals,cap

    for t,month in enumerate(spec['months']):
        month_ref,month_end,days,quarter=out.calendar[t]
        origins[month]=month_ref
        rows={eid:{} for eid in entities};loans={};assets={}
        capex={eid:{'MAINTENANCE':[],'GROWTH':[]} for eid in entities}
        depreciation={eid:[] for eid in entities};nbv_open={eid:[] for eid in entities};nbv_close={eid:[] for eid in entities}
        # Asset graph is independently derived from the raw register and calendar.
        for ai,asset in enumerate(spec['assets']):
            aid,eid=asset['id'],asset['entity_id'];opening=asset_state[aid]
            path=['scenarios',sid,'assets',aid,'monthly',t]
            a={}
            def asset_field(name,expression):
                a[name]=out.calc(expression,f'{aid} {month} {name}',[*path,name],expected_path=[*path,name],kind='date' if name=='month' else 'money_pence',complete=name!='month')
            asset_field('month',month_ref);asset_field('cost_open',opening['cost']);asset_field('accumulated_depreciation_open',opening['accumulated'])
            asset_field('nbv_open',_sub(a['cost_open'],a['accumulated_depreciation_open']))
            commissioned=ip('assets',ai,'commission_month');life=ip('assets',ai,'useful_life_months');cost=ip('assets',ai,'original_cost_pence')
            age=out.calc(_sub(_period(month_ref),_period(commissioned)),f'{aid} {month} asset age',[*path,'depreciation'])
            asset_field('capex',_if(_eq(month_ref,commissioned),cost,0))
            dep=_if(_and(_lt(commissioned,month_ref),_le(age,life)),
                _min(a['nbv_open'],_if(_eq(age,life),a['nbv_open'],_round(cost,life))),0)
            asset_field('depreciation',dep)
            asset_field('cost_close',_sum(a['cost_open'],a['capex']))
            asset_field('accumulated_depreciation_close',_sum(a['accumulated_depreciation_open'],a['depreciation']))
            asset_field('nbv_close',_sub(a['cost_close'],a['accumulated_depreciation_close']))
            assert set(a)==set(ASSET_FIELDS)
            for name in ASSET_FIELDS:out.display(reports['Asset Close'],aid,month,name,a[name],[*path,name],kind='date' if name=='month' else 'money_pence')
            assets[aid]=a;asset_state[aid]={'cost':a['cost_close'],'accumulated':a['accumulated_depreciation_close']}
            capex[eid]['MAINTENANCE'].append(_if(_eq(ip('assets',ai,'capex_category'),'MAINTENANCE'),a['capex'],0))
            capex[eid]['GROWTH'].append(_if(_eq(ip('assets',ai,'capex_category'),'GROWTH'),a['capex'],0))
            depreciation[eid].append(a['depreciation']);nbv_open[eid].append(a['nbv_open']);nbv_close[eid].append(a['nbv_close'])
        debt={};cash={};terms={};aux={}
        # Phases 1--2: operations, opening-principal interest and local principal.
        for eid,e in entities.items():
            row=rows[eid];i=indices[eid];li=loan_index[eid];loan=spec['loans'][li];previous=state[eid]
            terms[eid]={key:out.calc(selected(li,key,month_ref),f'{loan["id"]} {month} effective {key}',owner(eid,t,'term_id'))
                for key in ['id','annual_rate_p12','day_count','local_limit_pence','maturity_date','draw_cutoff_month','optional_repayment_fraction_p12','next_coupon_month']}
            term=terms[eid];active=_not(previous['closed']);mature=_and(active,_ge(month_end,term['maturity_date']))
            typ=ip('loans',li,'type');level=_eq(typ,'LEVEL_PRINCIPAL_MONTHLY');quarterly=_eq(typ,'BULLET_QUARTERLY_ACCRUAL')
            field(row,eid,t,'month',month_ref);field(row,eid,t,'term_id',term['id'])
            field(row,eid,t,'tax_policy',ip('entities',i,'tax_policy'));field(row,eid,t,'dscr_policy',ip('entities',i,'dscr_policy'))
            for name,key in [('cash_open','cash'),('reserve_open','reserve'),('principal_open','principal'),('interest_payable_open','interest'),('tax_payable_open','tax'),('paid_in_open','paid'),('retained_open','retained'),('trap_open','trap'),('cure_open','cure'),('facility_closed_open','closed')]:field(row,eid,t,name,previous[key])
            field(row,eid,t,'revenue',('round_product',ip('operating_inputs',eid,t,'base_cash_revenue_pence'),ip('scenarios',scenario_index,'monthly_schedule',t,'revenue_factor_p12')))
            field(row,eid,t,'cash_opex',('round_product',ip('operating_inputs',eid,t,'base_cash_opex_pence'),ip('scenarios',scenario_index,'monthly_schedule',t,'opex_factor_p12')))
            field(row,eid,t,'ebitda',_sub(row['revenue'],row['cash_opex']))
            field(row,eid,t,'capex_maintenance',_sum(*capex[eid]['MAINTENANCE']));field(row,eid,t,'capex_growth',_sum(*capex[eid]['GROWTH']))
            field(row,eid,t,'depreciation',_sum(*depreciation[eid]));field(row,eid,t,'asset_nbv_open',_sum(*nbv_open[eid]));field(row,eid,t,'asset_nbv_close',_sum(*nbv_close[eid]))
            field(row,eid,t,'ebit',_sub(row['ebitda'],row['depreciation']))
            rate=out.calc(_sum(term['annual_rate_p12'],ip('scenarios',scenario_index,'monthly_schedule',t,'annual_rate_spread_p12')),f'{eid} {month} effective annual rate',owner(eid,t,'interest_accrual'))
            basis=out.calc(_if(_eq(term['day_count'],'ACT_365F'),365,360),f'{eid} {month} ACT denominator',owner(eid,t,'interest_accrual'))
            accrued=out.act_interest(row['principal_open'],rate,days,basis,owner(eid,t,'interest_accrual'),f'{eid} {month}')
            field(row,eid,t,'interest_accrual',_if(active,accrued,0))
            coupon_calendar=_and(_ge(month_ref,term['next_coupon_month']),_eq(('mod',_sub(_period(month_ref),_period(term['next_coupon_month'])),3),0))
            # IF is intentionally lazy: monthly contracts have no quarterly date.
            coupon_due=out.calc(_if(active,_if(mature,1,_if(quarterly,_if(coupon_calendar,1,0),1)),0),f'{eid} {month} coupon due',owner(eid,t,'cash_coupon'))
            field(row,eid,t,'cash_coupon',_if(coupon_due,_sum(row['interest_payable_open'],row['interest_accrual']),0))
            field(row,eid,t,'interest_payable_close',_sub(_sum(row['interest_payable_open'],row['interest_accrual']),row['cash_coupon']))
            recast=out.calc(_if(_and(active,level,_or(_eq(t,0),_not(_eq(term['id'],previous['term_id'])))),1,0),f'{eid} {month} instalment reset',owner(eid,t,'scheduled_principal'))
            remaining=_max(1,_sum(_sub(_period(term['maturity_date']),_period(month_ref)),1))
            instalment=out.calc(_if(previous['closed'],0,_if(recast,_round(row['principal_open'],remaining),previous['instalment'])),f'{eid} {month} fixed principal instalment',owner(eid,t,'scheduled_principal'))
            field(row,eid,t,'scheduled_principal',_if(active,_if(mature,row['principal_open'],_if(level,_min(instalment,row['principal_open']),0)),0))
            field(row,eid,t,'local_margin_principal',_if(active,_max(0,_sub(_sub(row['principal_open'],row['scheduled_principal']),term['local_limit_pence'])),0))
            early_release=out.calc(_if(_or(mature,previous['closed']),row['reserve_open'],0),f'{eid} {month} contractual opening reserve release',owner(eid,t,'reserve_released'))
            cash[eid]=out.calc(_sub(_sum(row['cash_open'],early_release,row['revenue']),
                _sum(row['cash_opex'],row['capex_maintenance'],row['capex_growth'],row['cash_coupon'],row['scheduled_principal'],row['local_margin_principal'])),f'{eid} {month} cash after local obligations',owner(eid,t,'cash_before_financing'))
            debt[eid]=out.calc(_sub(row['principal_open'],_sum(row['scheduled_principal'],row['local_margin_principal'])),f'{eid} {month} debt after local principal',owner(eid,t,'principal_close'))
            aux[eid]={'active':active,'mature':mature,'level':level,'rate':rate,'basis':basis,'coupon_due':coupon_due,'recast_due':recast,'instalment':instalment,'early_release':early_release}
        shared_limit=out.calc(group_limit(month_ref),f'{month} effective shared bank capacity',['scenarios',sid,'group_monthly',t,'shared_bank_limit'])
        shared_parts={eid:[] for eid in entities}
        for priority in range(len(entities)):
            selected_entity=ip('group','shared_margin_priority',priority)
            excess=out.calc(_max(0,_sub(_sum(*debt.values()),shared_limit)),f'{month} shared margin priority {priority+1} excess',['scenarios',sid,'group_monthly',t,'bank_used'])
            old_debt=debt.copy()
            for eid in entities:
                amount=out.calc(_if(_eq(selected_entity,eid),_min(old_debt[eid],excess),0),f'{eid} {month} shared margin step {priority+1}',owner(eid,t,'shared_margin_principal'))
                shared_parts[eid].append(amount)
                debt[eid]=out.calc(_sub(old_debt[eid],amount),f'{eid} {month} debt after shared margin {priority+1}',owner(eid,t,'principal_close'))
                cash[eid]=out.calc(_sub(cash[eid],amount),f'{eid} {month} cash after shared margin {priority+1}',owner(eid,t,'cash_before_financing'))
        # Phase 4: independent FIFO tax state and exact covenant decisions.
        for eid,e in entities.items():
            row=rows[eid];i=indices[eid];a=aux[eid]
            field(row,eid,t,'shared_margin_principal',_sum(*shared_parts[eid]))
            field(row,eid,t,'eligible_current_interest',_if(_eq(row['tax_policy'],'ACCRUAL_MONTHLY'),row['interest_accrual'],row['cash_coupon']))
            field(row,eid,t,'interest_capacity',('round_product',_max(0,row['ebitda']),ip('entities',i,'interest_cap_fraction_p12')))
            # Create the current denied origin only after the old FIFO consumes capacity.
            def denied_current(capacity):
                field(row,eid,t,'interest_current_allowed',_min(row['eligible_current_interest'],capacity))
                return field(row,eid,t,'interest_denied_created',_sub(row['eligible_current_interest'],row['interest_current_allowed']))
            interest_queues[eid],interest_totals,_=vintage_close(eid,t,interest_queues[eid],row['interest_capacity'],denied_current,ip('entities',i,'interest_carry_months'),'interest_vintages')
            for name,key in [('interest_carry_open','opening'),('interest_expired','expired'),('interest_old_used','used'),('interest_carry_close','closing')]:field(row,eid,t,name,interest_totals[key])
            field(row,eid,t,'taxable_before_losses',_sub(row['ebit'],_sum(row['interest_old_used'],row['interest_current_allowed'])))
            loss_created=_max(0,_sub(0,row['taxable_before_losses']))
            loss_queues[eid],loss_totals,_=vintage_close(eid,t,loss_queues[eid],_max(0,row['taxable_before_losses']),loss_created,ip('entities',i,'loss_carry_months'),'loss_vintages')
            for name,key in [('loss_open','opening'),('loss_expired','expired'),('loss_used','used'),('loss_created','created'),('loss_close','closing')]:field(row,eid,t,name,loss_totals[key])
            field(row,eid,t,'taxable_after_losses',_sub(_max(0,row['taxable_before_losses']),row['loss_used']))
            field(row,eid,t,'current_tax_expense',('round_product',row['taxable_after_losses'],ip('entities',i,'tax_rate_p12')))
            field(row,eid,t,'cash_tax',_if(_eq(row['tax_policy'],'ACCRUAL_MONTHLY'),row['current_tax_expense'],_if(quarter,_sum(row['tax_payable_open'],row['current_tax_expense']),0)))
            field(row,eid,t,'tax_payable_close',_sub(_sum(row['tax_payable_open'],row['current_tax_expense']),row['cash_tax']))
            field(row,eid,t,'net_income',_sub(_sub(row['ebit'],row['interest_accrual']),row['current_tax_expense']))
            field(row,eid,t,'cfads',_sub(_sub(row['revenue'],row['cash_opex']),_sum(row['cash_tax'],row['capex_maintenance'])))
            field(row,eid,t,'mandatory_debt_service',_sum(row['cash_coupon'],row['scheduled_principal'],row['local_margin_principal'],row['shared_margin_principal']))
            monthly=_eq(row['dscr_policy'],'MONTHLY_CURRENT')
            field(row,eid,t,'dscr_window_cfads',_if(monthly,row['cfads'],_sum(*[old['cfads'] for old in history[eid][-2:]],row['cfads'])))
            field(row,eid,t,'dscr_window_debt_service',_if(monthly,row['mandatory_debt_service'],_sum(*[old['mandatory_debt_service'] for old in history[eid][-2:]],row['mandatory_debt_service'])))
            field(row,eid,t,'test_applicable',_if(_and(a['active'],_or(monthly,quarter)),1,0))
            q=out.calc(('product_whole',row['dscr_window_debt_service'],ip('entities',i,'dscr_threshold_p12')),f'{eid} {month} covenant threshold whole',owner(eid,t,'test_pass'))
            r=out.calc(('product_remainder',row['dscr_window_debt_service'],ip('entities',i,'dscr_threshold_p12')),f'{eid} {month} covenant threshold remainder',owner(eid,t,'test_pass'))
            passes=_ge(row['dscr_window_cfads'],_sum(q,_if(_ge(r,1),1,0)))
            field(row,eid,t,'test_pass',_if(row['test_applicable'],_if(passes,1,0),''))
            ratio_due=_and(row['test_applicable'],_lt(0,row['dscr_window_debt_service']))
            # Undefined/non-test displays have no ratio calculation, not an overflowing dummy divide by one.
            ratio=out.ratio(_if(ratio_due,row['dscr_window_cfads'],0),row['dscr_window_debt_service'],owner(eid,t,'dscr_ratio_millionths'),f'{eid} {month}')
            field(row,eid,t,'dscr_ratio_millionths',_if(ratio_due,ratio,''))
            failure=_and(row['test_applicable'],_eq(row['test_pass'],0))
            operative=_if(_or(a['mature'],row['facility_closed_open']),0,_if(monthly,_if(_or(row['trap_open'],failure),1,0),row['trap_open']))
            field(row,eid,t,'trap_operative',operative)
            next_cure=out.calc(_if(row['facility_closed_open'],0,_if(row['test_applicable'],_if(failure,0,_if(row['trap_open'],_min(2,_sum(row['cure_open'],1)),0)),row['cure_open'])),f'{eid} {month} provisional cure next',owner(eid,t,'cure_next'))
            next_trap=out.calc(_if(row['facility_closed_open'],0,_if(row['test_applicable'],_if(failure,1,_if(_and(row['trap_open'],_lt(next_cure,2)),1,0)),row['trap_open'])),f'{eid} {month} provisional restriction next',owner(eid,t,'trap_next'))
            aux[eid].update(next_cure=next_cure,next_trap=next_trap)
            cash[eid]=out.calc(_sub(cash[eid],row['cash_tax']),f'{eid} {month} cash after tax',owner(eid,t,'cash_before_financing'))
            reserve_after=_sub(row['reserve_open'],a['early_release'])
            ordinary_release=out.calc(_if(_or(a['mature'],row['facility_closed_open']),0,_if(row['trap_operative'],0,reserve_after)),f'{eid} {month} ordinary reserve release',owner(eid,t,'reserve_released'))
            field(row,eid,t,'reserve_released',_sum(a['early_release'],ordinary_release))
            field(row,eid,t,'reserve_locked',_if(_and(row['trap_operative'],_not(a['mature']),a['active']),_min(_max(0,_sub(cash[eid],ip('entities',i,'minimum_cash_pence'))),_max(0,_sub(ip('entities',i,'reserve_target_pence'),reserve_after))),0))
            cash[eid]=out.calc(_sub(_sum(cash[eid],ordinary_release),row['reserve_locked']),f'{eid} {month} cash after reserve transfers',owner(eid,t,'cash_before_financing'))
            field(row,eid,t,'reserve_close',_sub(_sum(row['reserve_open'],row['reserve_locked']),row['reserve_released']))
            fraction=_if(row['trap_operative'],SCALE,terms[eid]['optional_repayment_fraction_p12'])
            field(row,eid,t,'voluntary_principal',_min(debt[eid],('round_product',_max(0,_sub(cash[eid],ip('entities',i,'minimum_cash_pence'))),fraction)))
            debt[eid]=out.calc(_sub(debt[eid],row['voluntary_principal']),f'{eid} {month} principal after voluntary payment',owner(eid,t,'principal_close'))
            cash[eid]=out.calc(_sub(cash[eid],row['voluntary_principal']),f'{eid} {month} cash after voluntary payment',owner(eid,t,'cash_before_financing'))
            field(row,eid,t,'cash_before_financing',cash[eid])
        # Phases 6 and 7: public priority identifiers drive each allocation step.
        draws={eid:[] for eid in entities}
        for priority in range(len(entities)):
            selected_entity=ip('group','bank_funding_priority',priority)
            headroom=out.calc(_max(0,_sub(shared_limit,_sum(*debt.values()))),f'{month} bank headroom before priority {priority+1}',['scenarios',sid,'group_monthly',t,'bank_headroom'])
            old_debt=debt.copy()
            for eid in entities:
                i=indices[eid];a=aux[eid]
                eligible=_and(_eq(selected_entity,eid),a['active'],_not(a['mature']),_not(a['level']),_if(a['level'],0,_le(month_ref,terms[eid]['draw_cutoff_month'])))
                amount=out.calc(_if(eligible,_min(_max(0,_sub(ip('entities',i,'minimum_cash_pence'),cash[eid])),_max(0,_sub(terms[eid]['local_limit_pence'],old_debt[eid])),headroom),0),f'{eid} {month} bank drawing step {priority+1}',owner(eid,t,'bank_draw'))
                draws[eid].append(amount)
                debt[eid]=out.calc(_sum(old_debt[eid],amount),f'{eid} {month} bank principal after draw step {priority+1}',owner(eid,t,'principal_close'))
                cash[eid]=out.calc(_sum(cash[eid],amount),f'{eid} {month} cash after draw step {priority+1}',owner(eid,t,'cash_close'))
        calls={eid:[] for eid in entities};called={eid:state[eid]['called'] for eid in entities}
        for priority in range(len(entities)):
            selected_entity=ip('group','lp_funding_priority',priority)
            headroom=out.calc(_max(0,_sub(ip('group','additional_lp_commitment_pence'),_sum(*called.values()))),f'{month} group LP headroom priority {priority+1}',['scenarios',sid,'group_monthly',t,'lp_unused'])
            old_called=called.copy()
            for eid in entities:
                i=indices[eid]
                amount=out.calc(_if(_eq(selected_entity,eid),_min(_max(0,_sub(ip('entities',i,'minimum_cash_pence'),cash[eid])),_max(0,_sub(ip('entities',i,'additional_lp_commitment_pence'),old_called[eid])),headroom),0),f'{eid} {month} LP contribution step {priority+1}',owner(eid,t,'lp_call'))
                calls[eid].append(amount);called[eid]=out.calc(_sum(old_called[eid],amount),f'{eid} {month} LP cumulative step {priority+1}',owner(eid,t,'lp_called_cumulative'))
                cash[eid]=out.calc(_sum(cash[eid],amount),f'{eid} {month} cash after LP contribution {priority+1}',owner(eid,t,'cash_close'))
        for eid,e in entities.items():
            row=rows[eid];i=indices[eid];a=aux[eid];li=loan_index[eid];lid=spec['loans'][li]['id']
            field(row,eid,t,'bank_draw',_sum(*draws[eid]));field(row,eid,t,'lp_call',_sum(*calls[eid]));field(row,eid,t,'lp_called_cumulative',called[eid])
            field(row,eid,t,'funding_gap',_max(0,_sub(ip('entities',i,'minimum_cash_pence'),cash[eid])))
            equity=_sum(row['paid_in_open'],row['retained_open'],row['lp_call'],row['net_income'])
            field(row,eid,t,'distribution',_if(row['trap_operative'],0,_min(_max(0,_sub(cash[eid],ip('entities',i,'minimum_cash_pence'))),_max(0,equity))))
            field(row,eid,t,'return_of_capital',_min(row['distribution'],_sum(row['paid_in_open'],row['lp_call'])))
            field(row,eid,t,'profit_distribution',_sub(row['distribution'],row['return_of_capital']))
            field(row,eid,t,'paid_in_close',_sub(_sum(row['paid_in_open'],row['lp_call']),row['return_of_capital']))
            field(row,eid,t,'retained_close',_sub(_sum(row['retained_open'],row['net_income']),row['profit_distribution']))
            field(row,eid,t,'cash_close',_sub(cash[eid],row['distribution']));field(row,eid,t,'principal_close',debt[eid])
            close=_or(row['facility_closed_open'],a['mature'],_and(a['level'],_eq(row['principal_close'],0),_eq(row['interest_payable_close'],0),_eq(row['funding_gap'],0)))
            field(row,eid,t,'facility_closed_next',_if(close,1,0));field(row,eid,t,'trap_next',_if(close,0,a['next_trap']));field(row,eid,t,'cure_next',_if(close,0,a['next_cure']))
            field(row,eid,t,'total_assets',_sum(row['cash_close'],row['reserve_close'],row['asset_nbv_close']))
            field(row,eid,t,'total_liabilities',_sum(row['principal_close'],row['interest_payable_close'],row['tax_payable_close']))
            field(row,eid,t,'total_equity',_sum(row['paid_in_close'],row['retained_close']))
            payments=_sum(row['scheduled_principal'],row['local_margin_principal'],row['shared_margin_principal'],row['voluntary_principal'])
            field(row,eid,t,'cfo',_sub(_sub(row['revenue'],row['cash_opex']),_sum(row['cash_coupon'],row['cash_tax'])))
            field(row,eid,t,'cfi',_sub(0,_sum(row['capex_maintenance'],row['capex_growth'])))
            field(row,eid,t,'cff',_sub(_sum(row['bank_draw'],row['lp_call']),_sum(payments,row['distribution'])))
            field(row,eid,t,'cash_delta',_sub(_sum(row['cash_close'],row['reserve_close']),_sum(row['cash_open'],row['reserve_open'])))
            field(row,eid,t,'cash_check',_sub(row['cash_close'],_sub(_sum(row['cash_open'],row['reserve_released'],row['cfo'],row['cfi'],row['cff']),row['reserve_locked'])))
            field(row,eid,t,'restricted_cash_check',_sub(_sub(_sum(row['reserve_open'],row['reserve_locked']),row['reserve_released']),row['reserve_close']))
            field(row,eid,t,'principal_check',_sub(_sub(_sum(row['principal_open'],row['bank_draw']),payments),row['principal_close']))
            field(row,eid,t,'interest_payable_check',_sub(_sub(_sum(row['interest_payable_open'],row['interest_accrual']),row['cash_coupon']),row['interest_payable_close']))
            field(row,eid,t,'tax_payable_check',_sub(_sub(_sum(row['tax_payable_open'],row['current_tax_expense']),row['cash_tax']),row['tax_payable_close']))
            field(row,eid,t,'interest_queue_check',_sub(_sum(row['interest_carry_close'],row['interest_expired'],row['interest_old_used']),_sum(row['interest_carry_open'],row['interest_denied_created'])))
            field(row,eid,t,'loss_queue_check',_sub(_sum(row['loss_close'],row['loss_expired'],row['loss_used']),_sum(row['loss_open'],row['loss_created'])))
            field(row,eid,t,'capital_check',_sub(_sum(row['paid_in_close'],row['return_of_capital']),_sum(row['paid_in_open'],row['lp_call'])))
            field(row,eid,t,'retained_check',_sub(_sum(row['retained_close'],row['profit_distribution']),_sum(row['retained_open'],row['net_income'])))
            field(row,eid,t,'balance_sheet_check',_sub(row['total_assets'],_sum(row['total_liabilities'],row['total_equity'])))
            checks=[row[name] for name in MONEY_FIELDS if name.endswith('_check')]
            field(row,eid,t,'feasible',_if(_and(_eq(row['funding_gap'],0),_ge(row['cash_close'],ip('entities',i,'minimum_cash_pence')),_ge(row['reserve_close'],0),*[_eq(value,0) for value in checks]),1,0))
            assert set(row)==set(ENTITY_FIELDS),(set(ENTITY_FIELDS)-set(row),set(row)-set(ENTITY_FIELDS))
            for name in ENTITY_FIELDS:out.display(reports['Entity Close'],eid,month,name,row[name],owner(eid,t,name),kind=number_kind(name))
            l={'month':month_ref,'term_id':row['term_id'],'principal_open':row['principal_open'],'annual_rate_p12':a['rate'],'day_basis':a['basis'],'days':days,'interest_accrual':row['interest_accrual'],'interest_payable_open':row['interest_payable_open'],'coupon_due':a['coupon_due'],'cash_coupon':row['cash_coupon'],'recast_due':a['recast_due'],'recast_instalment':a['instalment']}
            for name in ['scheduled_principal','local_margin_principal','shared_margin_principal','voluntary_principal','bank_draw','principal_close','interest_payable_close','facility_closed_open','facility_closed_next']:l[name]=row[name]
            assert set(l)==set(LOAN_FIELDS)
            for name in LOAN_FIELDS:
                kind='date' if name=='month' else 'text' if name=='term_id' else 'rate_p12' if name=='annual_rate_p12' else 'flag' if name in ['coupon_due','recast_due','facility_closed_open','facility_closed_next'] else 'integer' if name in ['day_basis','days'] else 'money_pence'
                path=['scenarios',sid,'loans',lid,'monthly',t,name]
                account=name if name in row else 'scheduled_principal' if name in ['recast_due','recast_instalment'] else 'cash_coupon' if name=='coupon_due' else 'interest_accrual'
                value=out.calc(l[name],f'{lid} {month} {name}',owner(eid,t,account),expected_path=path,kind=kind,complete=kind=='money_pence')
                out.display(reports['Loan Close'],lid,month,name,value,path,kind=kind,owner=owner(eid,t,account))
            state[eid]={'cash':row['cash_close'],'reserve':row['reserve_close'],'principal':row['principal_close'],'interest':row['interest_payable_close'],'tax':row['tax_payable_close'],'paid':row['paid_in_close'],'retained':row['retained_close'],'called':row['lp_called_cumulative'],'trap':row['trap_next'],'cure':row['cure_next'],'closed':row['facility_closed_next'],'instalment':a['instalment'],'term_id':row['term_id']}
            history[eid].append(row)
        group={};gpath=['scenarios',sid,'group_monthly',t]
        def group_field(name,expression):
            kind='date' if name=='month' else 'flag' if name=='feasible' else 'money_pence'
            group[name]=out.calc(expression,f'Portfolio {month} {name}',[*gpath,name],expected_path=[*gpath,name],kind=kind,complete=kind=='money_pence')
        group_field('month',month_ref)
        for name in GROUP_SUM_FIELDS:group_field(name,_sum(*[rows[eid][name] for eid in entities]))
        group_field('shared_bank_limit',shared_limit);group_field('bank_used',group['principal_close']);group_field('bank_headroom',_sub(shared_limit,group['bank_used']))
        group_field('lp_commitment',ip('group','additional_lp_commitment_pence'));group_field('lp_calls_cumulative',group['lp_called_cumulative']);group_field('lp_unused',_sub(group['lp_commitment'],group['lp_calls_cumulative']))
        group_field('group_cash_check',_sub(group['cash_delta'],_sum(group['cfo'],group['cfi'],group['cff'])))
        group_field('group_bank_check',_sub(_sum(group['principal_close'],group['scheduled_principal'],group['local_margin_principal'],group['shared_margin_principal'],group['voluntary_principal']),_sum(group['principal_open'],group['bank_draw'])))
        group_field('group_equity_check',_sub(_sum(group['total_equity'],group['distribution']),_sum(group['paid_in_open'],group['retained_open'],group['net_income'],group['lp_call'])))
        group_field('group_balance_sheet_check',_sub(group['total_assets'],_sum(group['total_liabilities'],group['total_equity'])))
        group_field('feasible',_if(_and(*[_eq(rows[eid]['feasible'],1) for eid in entities],_ge(group['bank_headroom'],0),_ge(group['lp_unused'],0),*[_eq(group[n],0) for n in ['group_cash_check','group_bank_check','group_equity_check','group_balance_sheet_check']]),1,0))
        assert set(group)==set(GROUP_FIELDS),(set(GROUP_FIELDS)-set(group),set(group)-set(GROUP_FIELDS))
        for name in GROUP_FIELDS:out.display(reports['Group Close'],'Portfolio',month,name,group[name],[*gpath,name],kind='date' if name=='month' else 'flag' if name=='feasible' else 'money_pence')
