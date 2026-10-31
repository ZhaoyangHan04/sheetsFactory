"""Native ring-fenced project schedules, with private independent audit locators.

This module translates the public contract into formulas. It does not run a
financial implementation, read a financial cache, optimize, or find a plan.
Every physical formula has a private journal locator or an input-only derivation.
"""
from __future__ import annotations

from pathlib import Path
import re

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.workbook.properties import CalcProperties
from openpyxl.worksheet.datavalidation import DataValidation

from .spec import (ANNUAL_FIELDS, GROUP_FIELDS, RULES, T0_FIELDS, VINTAGE_FIELDS,
                   canonical_sha256, load_spec, require, validate_plan)

PUBLIC_RULES = RULES + (
    'Project sheets show standalone candidate forecasts even when a project is not selected. Portfolio totals and capacity usage include only selected projects under the same choice in all scenarios.',
    'All monetary cells are GBP pence; rates and factors are basis points, with10000 meaning100%. Financial zeroes, including inactive periods and unused or expired loss-vintage amounts, are zero amounts. Loss-vintage slots with an origin before FY1 are not applicable and intentionally blank. A blank scenario NPV means that candidate is infeasible.',
    'Complete every project choice with integer0 or1. Portfolio totals and tests are blank until all choices are supplied. All displayed project, tax-vintage, NPV, portfolio and capacity schedules form part of the financial model; supplied assumptions and explanatory text remain provided.',
)

_REFERENCE = re.compile(r"^'(?:[^']|'')+'!\$[A-Z]+\$[1-9][0-9]*(?::\$[A-Z]+\$[1-9][0-9]*)?$")
_BLUE = PatternFill('solid', fgColor='17365D')
_WHITE = Font(color='FFFFFF', bold=True)
_INPUT = PatternFill('solid', fgColor='EAF2F8')
_CHOICE = PatternFill('solid', fgColor='FFF2CC')
_MONEY = '#,##0;[Red](#,##0);0'


def _ref(sheet, row, column):
    return "'" + sheet.replace("'", "''") + "'!$" + get_column_letter(column) + '$' + str(row)


def _range(sheet, first_row, column, last_row):
    return _ref(sheet, first_row, column) + ':$' + get_column_letter(column) + '$' + str(last_row)


def _expression(value):
    if isinstance(value, str):
        return value if _REFERENCE.fullmatch(value) else '"' + value.replace('"', '""') + '"'
    if type(value) is int:
        return str(value)
    require(isinstance(value, (tuple, list)) and bool(value), 'An explicit formula expression is required')
    op, *args = value
    rendered = [_expression(item) for item in args]
    binary = {'sub':'-', 'mul':'*', 'div':'/', 'power':'^', 'eq':'=', 'lt':'<', 'le':'<=', 'ge':'>=', 'gt':'>'}
    if op in binary:
        require(len(rendered) == 2, 'A binary expression needs two operands')
        return '(' + rendered[0] + binary[op] + rendered[1] + ')'
    if op == 'flag':
        require(len(rendered) == 1, 'A flag coercion needs one operand')
        return '--(' + rendered[0] + ')'
    functions = {'sum':'SUM', 'min':'MIN', 'max':'MAX', 'if':'IF', 'and':'AND',
                 'or':'OR', 'round':'ROUND', 'sumproduct':'SUMPRODUCT', 'count':'COUNT', 'countif':'COUNTIF'}
    require(op in functions, 'An unsupported formula operation was requested')
    return functions[op] + '(' + ','.join(rendered) + ')'


class _Book:
    def __init__(self, public, plan, max_formulas):
        self.book = openpyxl.Workbook(); self.book.remove(self.book.active)
        self.book.calculation = CalcProperties(calcId=191029, fullCalcOnLoad=True, forceFullCalc=True, calcMode='auto')
        self.public, self.plan, self.max_formulas = public, plan, max_formulas
        self.inputs, self.literals, self.financial, self.arithmetic, self.decisions = [], [], [], [], []
        self.used = set(); self.raw = {}; self.count = 0

    def sheet(self, name):
        sheet = self.book.create_sheet(name)
        sheet.freeze_panes = 'B5'; sheet.sheet_view.showGridLines = False
        sheet.column_dimensions['A'].width = 42
        return sheet

    def literal(self, sheet, row, col, value, *, path=None, header=False):
        address = (sheet.title, row, col)
        require(address not in self.used, 'A physical cell was written twice')
        self.used.add(address); cell = sheet.cell(row, col)
        if value is not None: cell.value = value
        if type(value) is str: cell.data_type = 's'  # Public names are text, including a leading '='.
        cell.number_format = _MONEY if type(value) is int else 'General'
        kind = 'integer' if type(value) is int else 'text'
        record = {'sheet':sheet.title, 'cell':cell.coordinate, 'kind':kind, 'worksheet_scale':1}
        if path is None:
            record['value'] = value; self.literals.append(record)
        else:
            record['path'] = list(path); self.inputs.append(record)
            self.raw[tuple(path)] = _ref(sheet.title, row, col)
            cell.fill = _INPUT
        if header: cell.fill = _BLUE; cell.font = _WHITE
        return _ref(sheet.title, row, col)

    def formula(self, sheet, row, col, expr, *, expected_path=None, kind='money_pence', role,
                derivation=None, **locator):
        address = (sheet.title, row, col)
        require(address not in self.used, 'A physical formula was written twice')
        # A fiscal-grid identity such as an old vintage's created=0 is a literal,
        # not a computed financial cache. It still has a full journal locator.
        if type(expr) is int and expected_path is not None:
            reference=self.literal(sheet,row,col,expr)
            self.financial.append({'sheet':sheet.title,'cell':sheet.cell(row,col).coordinate,
                'formula':None,'expression':expr,'kind':kind,'worksheet_scale':1,
                'semantic_role':role,'expected_path':list(expected_path),**locator})
            return reference
        require(self.count < self.max_formulas, 'The complete workbook exceeds the formula cap; no truncation is allowed')
        self.used.add(address); self.count += 1
        formula = '=' + _expression(expr)
        require(len(formula) <= 8192, 'A complete formula exceeds the Excel length limit')
        cell = sheet.cell(row, col, formula); cell.number_format = _MONEY
        record = {'sheet':sheet.title,'cell':cell.coordinate,'formula':formula,'expression':expr,
                  'kind':kind,'worksheet_scale':1,'semantic_role':role}
        if expected_path is not None:
            record.update(expected_path=list(expected_path), **locator); self.financial.append(record)
        else:
            require(derivation is not None, 'Every formula needs an independent financial locator or input derivation')
            record['expected_derivation'] = derivation
        self.arithmetic.append(record)
        return _ref(sheet.title, row, col)

    def choice(self, sheet, row, col, project_id):
        value = None if self.plan is None else self.plan[project_id]
        self.literal(sheet, row, col, value)
        self.literals.pop()  # Choices are a separate complete audit domain, not supplied primitives.
        cell = sheet.cell(row, col); cell.fill = _CHOICE
        self.decisions.append({'sheet':sheet.title,'cell':cell.coordinate,'project_id':project_id,
                               'value':value,'kind':'binary_decision','worksheet_scale':1})
        return _ref(sheet.title, row, col)


def _inputs(writer):
    s = writer.public; years = s['years']; ids = s['project_ids']
    notes = writer.sheet('ContractNotes')
    writer.literal(notes, 1, 1, 'Ring-fenced portfolio: public financial contract', header=True)
    for row, rule in enumerate(PUBLIC_RULES, 3):
        writer.literal(notes, row, 1, rule); notes.cell(row, 1).alignment = Alignment(wrap_text=True, vertical='top')
        notes.row_dimensions[row].height = 45
    notes.column_dimensions['A'].width = 125
    writer.literal(notes, len(PUBLIC_RULES)+5, 1, 'Hypothetical portfolio; named projects do not represent newly audited real companies.')
    projects = writer.sheet('Projects'); scalar_fields = [field for field in s['projects'][0] if field != 'resource_usage_units']
    for column, field in enumerate(scalar_fields, 1): writer.literal(projects, 1, column, field.replace('_',' ').title(), header=True)
    project_refs = {}
    for index, p in enumerate(s['projects']):
        project_refs[p['id']] = {field:writer.literal(projects, index+2, col, p[field], path=('projects',index,field))
                               for col,field in enumerate(scalar_fields,1)}
    # Raw fiscal indices are provided independently of every financial schedule.
    writer.literal(projects, len(ids)+4, 1, 'First fiscal calendar year', header=True)
    writer.literal(projects, len(ids)+4, 2, s['fiscal_year_start'], path=('fiscal_year_start',))
    for index, year in enumerate(years):
        writer.literal(projects, len(ids)+6, index+2, year, path=('years',index))
    scenarios = writer.sheet('Scenarios'); scenario_refs = {}
    for column,text in enumerate(['Scenario','Name','Assumption / basis points',*['FY'+str(y) for y in years]],1):
        writer.literal(scenarios,1,column,text,header=True)
    row=2
    for si, scenario in enumerate(s['scenarios']):
        scenario_refs[scenario['id']]={}
        for field in ('revenue_factors_bp','opex_factors_bp','sale_factors_bp','interest_spread_bp'):
            writer.literal(scenarios,row,1,scenario['id']);writer.literal(scenarios,row,2,scenario['name'])
            writer.literal(scenarios,row,3,field.replace('_',' ').title())
            scenario_refs[scenario['id']][field]={year:writer.literal(scenarios,row,index+4,scenario[field][str(year)],
                path=('scenarios',si,field,str(year))) for index,year in enumerate(years)}
            row+=1
    usage=writer.sheet('ResourceUse');writer.literal(usage,1,1,'Project',header=True);usage_columns={};col=2
    for resource in s['resource_ids']:
        for sid in s['scenario_ids']:
            for year in years:
                usage_columns[resource,sid,year]=col
                writer.literal(usage,1,col,f'{resource} {sid} FY{year} / units',header=True)
                for pi,p in enumerate(s['projects']):
                    if col==2:writer.literal(usage,pi+2,1,p['id'])
                    writer.literal(usage,pi+2,col,p['resource_usage_units'][resource][sid][str(year)],
                        path=('projects',pi,'resource_usage_units',resource,sid,str(year)))
                col+=1
    limits=writer.sheet('Limits');writer.literal(limits,1,1,'Provided capacity',header=True);writer.literal(limits,1,2,'Limit / pence or stated units',header=True)
    limit_refs={};row=2
    def limit(path,value):
        nonlocal row
        writer.literal(limits,row,1,' / '.join(str(p).replace('_',' ') for p in path[1:]))
        limit_refs[tuple(path)]=writer.literal(limits,row,2,value,path=path);row+=1
    for name,value in s['shared_limits'].items():
        if type(value) is int:limit(('shared_limits',name),value)
        elif name in ('annual_new_lp_pence','annual_debt_close_pence'):
            for sid in s['scenario_ids']:
                for year in years:limit(('shared_limits',name,sid,str(year)),value[sid][str(year)])
        elif name=='resource_capacity_units':
            for resource in s['resource_ids']:
                for sid in s['scenario_ids']:
                    for year in years:limit(('shared_limits',name,resource,sid,str(year)),value[resource][sid][str(year)])
        else:
            for label,values in value.items():
                for year in years:limit(('shared_limits',name,label,str(year)),values[str(year)])
    sites=writer.sheet('Sites');writer.literal(sites,1,1,'Alternative group',header=True);writer.literal(sites,1,2,'Business purpose',header=True)
    for gi,g in enumerate(s['exclusivity_groups']):
        writer.literal(sites,gi+2,1,g['id'],path=('exclusivity_groups',gi,'id'))
        writer.literal(sites,gi+2,2,g['description'],path=('exclusivity_groups',gi,'description'))
        for j,pid in enumerate(g['project_ids']):writer.literal(sites,gi+2,j+3,pid,path=('exclusivity_groups',gi,'project_ids',j))
    prerequisites=writer.sheet('Prerequisites')
    for col,text in enumerate(['Relationship','Dependent','Enabler','Business purpose'],1):writer.literal(prerequisites,1,col,text,header=True)
    for ei,edge in enumerate(s['prerequisites']):
        for col,key in enumerate(['id','dependent','prerequisite','business_reason'],1):writer.literal(prerequisites,ei+2,col,edge[key],path=('prerequisites',ei,key))
    return project_refs,scenario_refs,usage_columns,limit_refs


def _project(writer, project, assumptions, scenarios):
    public=writer.public;years=public['years'];pid=project['id'];last=years[-1]
    sheet=writer.sheet(pid);writer.literal(sheet,1,1,project['name']+' / standalone candidate',header=True)
    writer.literal(sheet,2,1,'Amounts: integer GBP pence. All scenarios are standalone forecasts; choices only weight portfolio totals.')
    result={}
    for scenario_index,sid in enumerate(public['scenario_ids']):
        top=5+scenario_index*175;row_refs={};vintages={};s=scenarios[sid]
        writer.literal(sheet,top,1,sid+' / standalone financial forecast',header=True)
        path=['projects',pid,'scenarios',sid]
        def financial(row,col,field,expr,part,kind='money_pence',**locator):
            return writer.formula(sheet,row,col,expr,expected_path=path+part,kind=kind,
                role={'project_id':pid,'scenario_id':sid,'field':field,'schedule':part[0]},**locator)
        for index,field in enumerate(T0_FIELDS):writer.literal(sheet,top+2+index,1,'Time zero / '+field.replace('_',' '))
        t={field:_ref(pid,top+2+i,2) for i,field in enumerate(T0_FIELDS)}
        cost=assumptions['asset_cost_pence'];commitment=assumptions['lp_commitment_pence']
        texpr={'asset_cost':cost,'bank_draw':('round',('div',('mul',cost,assumptions['t0_ltv_bp']),10000),0),
            'lp_required':('sub',cost,t['bank_draw']),'lp_call':('min',t['lp_required'],commitment),
            'lp_remaining':('sub',commitment,t['lp_call']),
            'cash_close':('sub',('sum',t['bank_draw'],t['lp_call']),cost),
            'funding_gap':('max',0,('sub',0,t['cash_close'])),'asset_nbv_close':cost,'debt_close':t['bank_draw'],
            'book_equity_close':('sub',('sum',t['asset_nbv_close'],t['cash_close']),t['debt_close']),
            'balance_check':('sub',t['book_equity_close'],t['lp_call'])}
        for index,field in enumerate(T0_FIELDS):financial(top+2+index,2,field,texpr[field],['t0',field])
        annual_start=top+17;fields=['operating_active','feasible',*ANNUAL_FIELDS]
        for index,field in enumerate(fields):writer.literal(sheet,annual_start+index,1,field.replace('_',' ').title())
        for yi,year in enumerate(years):
            col=yi+2;writer.literal(sheet,annual_start-1,col,f'FY{year} / {public["fiscal_year_start"]+year-1}')
            row_refs[year]={field:_ref(pid,annual_start+index,col) for index,field in enumerate(fields)}
        # A bounded origin window includes this year's expired y-4 account.
        vintage_top=annual_start+len(fields)+3
        for age in range(4,-1,-1):
            for fi,field in enumerate(VINTAGE_FIELDS):
                vr=vintage_top+(4-age)*len(VINTAGE_FIELDS)+fi
                writer.literal(sheet,vr,1,f'Loss origin FY minus{age} / '+field)
                for yi,year in enumerate(years):
                    origin=year-age
                    if origin>=1:vintages[year,origin,field]=_ref(pid,vr,yi+2)
        for yi,year in enumerate(years):
            col=yi+2;r=row_refs[year];previous=row_refs.get(year-1);active=('ge',year,assumptions['operating_start_year'])
            prev=lambda field,tfield=None: previous[field] if previous else t[tfield or field]
            opening_cash=prev('cash_close');opening_debt=prev('debt_close');opening_nbv=prev('asset_nbv_close')
            prior_call=previous['lp_called_cumulative'] if previous else t['lp_call']
            origins=list(range(max(1,year-4),year+1))
            for origin in origins:
                opening=vintages.get((year-1,origin,'closing'),0) if origin<year else 0
                expired=opening if year-origin>3 else 0
                older=[vintages[year,o,'used'] for o in origins if o<origin]
                used=('min',opening,('max',0,('sub',r['taxable_before_losses'],('sum',*older)))) if origin<year and year-origin<=3 else 0
                created=r['loss_created'] if origin==year else 0
                closing=created if origin==year else (0 if year-origin>3 else ('sub',opening,vintages[year,origin,'used']))
                expressions=dict(opening=opening,expired=expired,used=used,created=created,closing=closing)
                for field in VINTAGE_FIELDS:
                    reference=vintages[year,origin,field];cell=reference.rsplit('!',1)[1].replace('$','')
                    financial(sheet[cell].row,col,field,expressions[field],['tax_vintages'],
                        vintage_year=year,origin_year=origin,vintage_field=field)
            sums=lambda field:('sum',*(vintages[year,origin,field] for origin in origins))
            def base(field):
                source='base_annual_'+field+'_pence';growth=field+'_growth_factor_bp'
                return ('if',('lt',year,assumptions['operating_start_year']),0,
                        ('if',('eq',year,assumptions['operating_start_year']),assumptions[source],
                         ('round',('div',('mul',previous[field+'_base'] if previous else 0,assumptions[growth]),10000),0)))
            available=('sub',('sum',r['cash_open'],r['revenue'],r['sale_proceeds']),
                       ('sum',r['opex'],r['bank_interest'],r['principal_repayment'],r['current_tax']))
            expr={'operating_active':('if',active,1,0),'cash_open':opening_cash,'asset_nbv_open':opening_nbv,
                'revenue_base':base('revenue'),'opex_base':base('opex'),
                'revenue':('round',('div',('mul',r['revenue_base'],s['revenue_factors_bp'][year]),10000),0),
                'opex':('round',('div',('mul',r['opex_base'],s['opex_factors_bp'][year]),10000),0),
                'depreciation':('if',active,('if',('ge',('sum',('sub',year,assumptions['operating_start_year']),1),assumptions['depreciation_years']),
                    r['asset_nbv_open'],('min',r['asset_nbv_open'],('round',('div',cost,assumptions['depreciation_years']),0))),0),
                'sale_proceeds':('round',('div',('mul',assumptions['terminal_sale_proceeds_pence'],s['sale_factors_bp'][year]),10000),0) if year==last else 0,
                'sale_carrying':('sub',r['asset_nbv_open'],r['depreciation']) if year==last else 0,
                'sale_gain':('sub',r['sale_proceeds'],r['sale_carrying']),
                'asset_nbv_close':('sub',('sub',r['asset_nbv_open'],r['depreciation']),r['sale_carrying']),
                'debt_open':opening_debt,
                'bank_interest':('round',('div',('mul',r['debt_open'],('sum',assumptions['bank_rate_bp'],s['interest_spread_bp'][year])),10000),0),
                'principal_repayment':('if',('or',('ge',year,assumptions['debt_maturity_year']),('eq',year,last)),r['debt_open'],
                    ('if',('eq',assumptions['debt_policy'],'LEVEL_PRINCIPAL'),('min',r['debt_open'],('round',('div',t['bank_draw'],assumptions['debt_maturity_year']),0)),0)),
                'debt_close':('sub',r['debt_open'],r['principal_repayment']),
                'taxable_before_losses':('sub',('sum',r['revenue'],r['sale_gain']),('sum',r['opex'],r['depreciation'],r['bank_interest'])),
                'loss_open':sums('opening'),'loss_expired':sums('expired'),'loss_used':sums('used'),
                'loss_created':('max',0,('sub',0,r['taxable_before_losses'])),'loss_close':sums('closing'),
                'taxable_after_losses':('max',0,('sub',r['taxable_before_losses'],r['loss_used'])),
                'current_tax':('round',('div',('mul',r['taxable_after_losses'],assumptions['tax_rate_bp']),10000),0),
                'net_income':('sub',r['taxable_before_losses'],r['current_tax']),
                'lp_required':('max',0,('sub',0,available)),
                'lp_call':('min',r['lp_required'],('sub',commitment,prior_call)),
                'lp_distribution':('max',0,available),'lp_called_cumulative':('sum',prior_call,r['lp_call']),
                'lp_remaining':('sub',commitment,r['lp_called_cumulative']),
                'cash_close':('sub',('sum',available,r['lp_call']),r['lp_distribution']),
                'cumulative_net_income':('sum',previous['cumulative_net_income'] if previous else 0,r['net_income']),
                'cumulative_distributions':('sum',previous['cumulative_distributions'] if previous else 0,r['lp_distribution']),
                'book_equity_close':('sub',('sum',r['asset_nbv_close'],r['cash_close']),r['debt_close']),
                'net_lp_cashflow':('sub',r['lp_distribution'],r['lp_call']),
                'funding_gap':('max',0,('sub',0,r['cash_close'])),
                'balance_check':('sub',('sum',r['book_equity_close'],r['cumulative_distributions']),('sum',r['lp_called_cumulative'],r['cumulative_net_income'])),
                'cash_check':('sub',('sum',available,r['lp_call']),('sum',r['lp_distribution'],r['cash_close'])),
                'asset_check':('sub',r['asset_nbv_open'],('sum',r['depreciation'],r['sale_carrying'],r['asset_nbv_close'])),
                'debt_check':('sub',r['debt_open'],('sum',r['principal_repayment'],r['debt_close'])),
                'loss_check':('sub',('sum',r['loss_open'],r['loss_created']),('sum',r['loss_expired'],r['loss_used'],r['loss_close'])),
                'feasible':('if',('and',('eq',previous['feasible'] if previous else t['funding_gap'],1 if previous else 0),('eq',r['funding_gap'],0)),1,0)}
            for fi,field in enumerate(fields):
                financial(annual_start+fi,col,field,expr[field],['annual',yi,field],kind='flag' if field in ('operating_active','feasible') else 'money_pence')
        footer=vintage_top+len(VINTAGE_FIELDS)*5+2
        writer.literal(sheet,footer,1,'Candidate feasible /1 yes,0 no')
        rr=row_refs[last]
        feasible=financial(footer,2,'feasible',('if',('and',('eq',rr['feasible'],1),('le',rr['lp_called_cumulative'],commitment),
            ('eq',rr['cash_close'],0),('eq',rr['asset_nbv_close'],0),('eq',rr['debt_close'],0)),1,0),['feasible'],kind='flag')
        writer.literal(sheet,footer+1,1,'LP NPV / GBP pence, whole-stream rounding')
        npv=('round',('sum',('sub',0,t['lp_call']),*(('div',row_refs[y]['net_lp_cashflow'],
            ('power',('sum',1,('div',assumptions['discount_rate_bp'],10000)),y)) for y in years)),0)
        npv_ref=financial(footer+1,2,'npv_pence',('if',('eq',feasible,1),npv,''),['npv_pence'],kind='nullable_money_pence')
        result[sid]={'t0':t,'annual':row_refs,'feasible':feasible,'npv':npv_ref}
    return result


def _portfolio(writer, schedules, usage_columns, limits):
    s=writer.public;ids=s['project_ids'];years=s['years'];scenarios=s['scenario_ids'];n=len(ids)
    sheet=writer.sheet('Portfolio');writer.literal(sheet,1,1,'Common project choices and standalone candidate values',header=True)
    writer.literal(sheet,2,1,'Choices weight portfolio totals only. Candidate cash, debt and NPVs below remain standalone in every scenario.')
    first=6;last=first+n-1;choices={};flow_columns={};npv_columns={};feasible_columns={};col=3
    writer.literal(sheet,5,1,'Project',header=True);writer.literal(sheet,5,2,'Choose0 or1 / common plan',header=True)
    for sid in scenarios:
        npv_columns[sid]=col;writer.literal(sheet,5,col,sid+' standalone LP NPV / pence',header=True);col+=1
        feasible_columns[sid]=col;writer.literal(sheet,5,col,sid+' candidate feasible /0 or1',header=True);col+=1
    initial_column=col;writer.literal(sheet,5,col,'Opening candidate LP / pence',header=True);col+=1
    group_sources={'new_lp_calls':'lp_call','year_end_debt':'debt_close','lp_distributions':'lp_distribution',
                   'net_lp_cashflow':'net_lp_cashflow','asset_nbv':'asset_nbv_close'}
    for sid in scenarios:
        for year in years:
            for group_field,source in group_sources.items():
                flow_columns[sid,year,group_field]=col
                writer.literal(sheet,5,col,f'{sid} FY{year} standalone '+group_field.replace('_',' ')+' / pence',header=True);col+=1
    for index,pid in enumerate(ids):
        row=first+index;writer.literal(sheet,row,1,pid);choices[pid]=writer.choice(sheet,row,2,pid)
        path=['projects',pid,'scenarios']
        for sid in scenarios:
            for column,field,source,kind in [(npv_columns[sid],'npv_pence',schedules[pid][sid]['npv'],'nullable_money_pence'),
                    (feasible_columns[sid],'feasible',schedules[pid][sid]['feasible'],'flag')]:
                writer.formula(sheet,row,column,source,expected_path=path+[sid,field],kind=kind,
                    role={'project_id':pid,'scenario_id':sid,'field':field,'schedule':'portfolio_candidate_alias'})
        writer.formula(sheet,row,initial_column,schedules[pid]['S01']['t0']['lp_call'],expected_path=path+['S01','t0','lp_call'],
            role={'project_id':pid,'scenario_id':'S01','field':'lp_call','schedule':'portfolio_candidate_alias'})
        for (sid,year,field),column in flow_columns.items():
            source=group_sources[field]
            writer.formula(sheet,row,column,schedules[pid][sid]['annual'][year][source],
                expected_path=path+[sid,'annual',year-1,source],
                role={'project_id':pid,'scenario_id':sid,'year':year,'field':source,'schedule':'portfolio_candidate_alias'})
    validation=DataValidation(type='whole',operator='between',formula1=0,formula2=1,allow_blank=True)
    validation.errorTitle='Binary project choice';validation.error='Enter integer0 or1.';validation.showErrorMessage=True
    validation.errorStyle='stop';sheet.add_data_validation(validation);validation.add(f'B{first}:B{last}')
    decision_range=_range(sheet.title,first,2,last)
    writer.literal(sheet,3,1,'All choices complete /1 yes,0 no')
    complete=writer.formula(sheet,3,2,('if',('and',('eq',('count',decision_range),n),
        ('eq',('sum',('countif',decision_range,0),('countif',decision_range,1)),n)),1,0),
        kind='flag',role={'schedule':'choice_completion','field':'complete_binary_plan'},
        derivation={'kind':'complete_binary_decisions','project_ids':list(ids)})
    gated=lambda expr:('if',('eq',complete,1),expr,'')
    summary=writer.sheet('GroupSummary');writer.literal(summary,1,1,'Selected portfolio / only common-plan contributions',header=True)
    writer.literal(summary,2,1,'Amounts: GBP pence. These totals are choice-weighted; standalone project schedules are not choice-weighted.')
    for column,text in enumerate(['Scenario','FY',*['Selected '+k.replace('_',' ')+' / pence' for k in GROUP_FIELDS]],1):writer.literal(summary,4,column,text,header=True)
    group={};row=5
    for sid in scenarios:
        for year in years:
            writer.literal(summary,row,1,sid);writer.literal(summary,row,2,year)
            for ci,field in enumerate(GROUP_FIELDS,3):
                group[sid,year,field]=writer.formula(summary,row,ci,gated(('sumproduct',decision_range,_range('Portfolio',first,flow_columns[sid,year,field],last))),
                    expected_path=['group','scenarios',sid,'annual',year-1,field],
                    role={'scenario_id':sid,'year':year,'field':field,'schedule':'selected_group'},requires_complete_plan=True)
            row+=1
    constraints=writer.sheet('Constraints')
    for ci,text in enumerate(['Capacity / relationship','Selected usage / pence or units','Provided limit','Remaining capacity','Pass1 / fail0'],1):writer.literal(constraints,1,ci,text,header=True)
    rows=[]
    def add(name,lhs,limit):rows.append((name,lhs,limit))
    add('initial_sponsor_equity',('sumproduct',decision_range,_range('Portfolio',first,initial_column,last)),limits['shared_limits','initial_sponsor_equity_pence'])
    for sid in scenarios:
        for year in years:
            for family,field,limitname in [('annual_new_lp','new_lp_calls','annual_new_lp_pence'),('annual_debt_close','year_end_debt','annual_debt_close_pence')]:
                add(f'{family}:{sid}:{year}',group[sid,year,field],limits['shared_limits',limitname,sid,str(year)])
            for resource in s['resource_ids']:
                add(f'resource:{resource}:{sid}:{year}',('sumproduct',decision_range,_range('ResourceUse',2,usage_columns[resource,sid,year],n+1)),
                    limits['shared_limits','resource_capacity_units',resource,sid,str(year)])
    project_fields=[f for f in s['projects'][0] if f!='resource_usage_units']
    for family,labels,limitname,label_field in [('region_exposure',s['region_ids'],'region_exposure_pence','region'),('sector_exposure',s['sector_ids'],'sector_exposure_pence','sector')]:
        for label in labels:
            for year in years:
                add(f'{family}:{label}:{year}',('sumproduct',decision_range,_range('Portfolio',first,flow_columns['S01',year,'asset_nbv'],last),
                    ('flag',('eq',_range('Projects',2,project_fields.index(label_field)+1,n+1),label))),limits['shared_limits',limitname,label,str(year)])
    for g in s['exclusivity_groups']:add('exclusivity:'+g['id'],('sum',*(choices[pid] for pid in g['project_ids'])),1)
    for edge in s['prerequisites']:add('prerequisite:'+edge['id'],('sub',choices[edge['dependent']],choices[edge['prerequisite']]),0)
    for row,(name,lhs,limit) in enumerate(sorted(rows),2):
        writer.literal(constraints,row,1,name.replace('_',' '))
        for column,field,expr,kind in [(2,'lhs',gated(lhs),'integer'),(3,'limit',limit,'integer'),
                (4,'slack',gated(('sub',_ref('Constraints',row,3),_ref('Constraints',row,2))),'integer'),
                (5,'passed',gated(('if',('le',_ref('Constraints',row,2),_ref('Constraints',row,3)),1,0)),'flag')]:
            writer.formula(constraints,row,column,expr,expected_path=['constraints'],kind=kind,
                role={'constraint_id':name,'field':field,'schedule':'capacity'},constraint_id=name,constraint_field=field,
                requires_complete_plan=field!='limit')
    statusrow=last+4
    writer.literal(sheet,statusrow,1,'Selected portfolio feasible /1 yes,0 no')
    all_selected=[('eq',('sumproduct',decision_range,('sub',1,_range('Portfolio',first,feasible_columns[sid],last))),0) for sid in scenarios]
    feasible=writer.formula(sheet,statusrow,2,gated(('if',('and',('eq',('countif',_range('Constraints',2,5,len(rows)+1),1),len(rows)),*all_selected),1,0)),
        expected_path=['feasible'],kind='flag',role={'schedule':'selected_portfolio','field':'feasible'},requires_complete_plan=True)
    writer.literal(sheet,statusrow+1,1,'Objective / sum of selected, individually posted S01 NPVs / pence')
    writer.formula(sheet,statusrow+1,2,('if',('and',('eq',complete,1),('eq',feasible,1)),
        ('sumproduct',decision_range,_range('Portfolio',first,npv_columns['S01'],last)),''),expected_path=['objective_pence'],
        kind='nullable_money_pence',role={'schedule':'selected_portfolio','field':'objective_pence'},requires_complete_plan=True)
    writer.literal(sheet,statusrow+2,1,'All standalone candidates feasible in every scenario /1 yes,0 no')
    writer.formula(sheet,statusrow+2,2,('if',('and',*(('eq',('countif',_range('Portfolio',first,feasible_columns[sid],last),1),n) for sid in scenarios)),1,0),
        expected_path=['all_standalone_feasible'],kind='flag',role={'schedule':'candidate_universe','field':'all_standalone_feasible'})
    return len(rows)


def emit_workbook(path, specification, *, plan=None, max_formulas=1_000_000):
    """Write a fresh uncached native workbook; never evaluate finance or search.

    A provided plan is private source-builder input. With plan=None all project
    choices remain blank; every standalone forecast is still fully emitted.
    Financial locators resolve against either independently supplied A/B result.
    All physical formulas are covered by arithmetic_bindings. No expected caches
    or financial values are returned by this formula translator.
    """
    public=load_spec(specification)
    require(type(max_formulas) is int and 0<max_formulas<=2_000_000,'An explicit bounded complete formula cap is required')
    actual_plan=None if plan is None else validate_plan(public,plan)
    destination=Path(path);require(not destination.exists(),'Preserve the existing workbook; use a fresh output path')
    require(destination.suffix.lower()=='.xlsx','A native XLSX destination is required')
    writer=_Book(public,actual_plan,max_formulas)
    assumptions,scenarios,usage,limits=_inputs(writer)
    schedules={project['id']:_project(writer,project,assumptions[project['id']],scenarios) for project in public['projects']}
    count=_portfolio(writer,schedules,usage,limits)
    bindings={'binding_version':1,'kind':'linear_capital_portfolio_native_excel_bindings',
        'specification_sha256':canonical_sha256(public),'sheetnames':writer.book.sheetnames,
        'formula_count':writer.count,'input_bindings':writer.inputs,'literal_bindings':writer.literals,
        'decision_bindings':writer.decisions,'financial_bindings':writer.financial,
        'arithmetic_bindings':writer.arithmetic,'constraint_count':count,
        'public_rules':list(PUBLIC_RULES),'plan_supplied':actual_plan is not None,
        'dimensions':{'projects':len(public['project_ids']),'scenarios':len(public['scenario_ids']),'years':len(public['years'])},
        'financial_expected_values_embedded':False,'financial_implementation_executed':False,
        'optimization_executed':False,'financial_source_or_difficulty_certified':False,
        'scope':'All standalone candidates and scenarios; all selected-portfolio fields and complete public capacities; no truncation'}
    require(len(writer.arithmetic)==writer.count,'The physical formula binding census differs')
    destination.parent.mkdir(parents=True,exist_ok=True)
    writer.book.save(destination);writer.book.close()
    return bindings
