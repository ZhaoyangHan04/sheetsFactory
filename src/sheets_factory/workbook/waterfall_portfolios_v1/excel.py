"""Cache-free native fund workbooks, with complete private semantic bindings.

This emitter consumes public assumptions only. It imports neither oracle and
never loads independent financial outputs into cells or formula caches.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.workbook.properties import CalcProperties

from . import schema

KIND='pure_waterfall_portfolios_native_emission'
USES={'investment_cash_use':'asset_investment','management_fee_cash_use':'management_fee',
      'operating_cost_cash_use':'operating_cost','capital_cash_use':'capital_paid',
      'preference_cash_use':'preference_paid','catchup_cash_use':'catchup_paid',
      'lp_promote_cash_use':'lp_promote_cash','gp_promote_cash_use':'gp_promote_cash'}
PENCE_FIELDS=(*schema.ROW_FIELDS,*USES)
REPORT_FIELDS=(*PENCE_FIELDS,'lp_distribution_multiple','capital_and_pref_shortfall')
MONEY_FORMAT='#,##0.00;[Red](#,##0.00)'


def reference(path):
    p=Path(path).resolve();b=p.read_bytes()
    return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}


def _write(path,value):
    with Path(path).open('x') as f:json.dump(value,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
    return reference(path)


def _label(field): return field.replace('_',' ').capitalize()


def _parts(x):
    if type(x) is int:return str(x)
    if isinstance(x,str):
        sheet,cell=x.rsplit('!',1);return "'"+sheet.replace("'","''")+"'!"+cell
    op,*args=x; s=[_parts(a) for a in args]
    if op in ('add','mul'):
        return '('+('+' if op=='add' else '*').join(s)+')'
    if op in ('sub','div','gt'):
        return '('+s[0]+{'sub':'-','div':'/','gt':'>'}[op]+s[1]+')'
    names={'round':'ROUND','min':'MIN','max':'MAX','if':'IF','or':'OR','quotient':'QUOTIENT','date':'DATE'}
    schema.require(op in names,'Unknown private native expression operator')
    return names[op]+'('+','.join(s)+')'


def _e(op,*args):return (op,*args)
def _add(*args):return _e('add',*args)
def _sub(a,b):return _e('sub',a,b)
def _mul(a,b):return _e('mul',a,b)
def _post(n,d):return _e('round',_e('div',n,d),0)


class _Book:
    def __init__(self,public):
        self.public=public;self.wb=Workbook();self.wb.remove(self.wb.active)
        self.wb.calculation=CalcProperties(calcMode='auto',fullCalcOnLoad=True,forceFullCalc=True,iterate=False)
        self.wb.properties.creator='Synthetic fund reporting';self.wb.properties.title='Hypothetical fund and investor reports'
        self.wb.properties.created=self.wb.properties.modified=datetime(2025,1,1)
        self.provided={};self.financial={};self.points={};self.facts={};self.periods={};self.forecast=[];self.roots=[]

    def sheet(self,name):
        ws=self.wb.create_sheet(name);ws.freeze_panes='B5';ws.sheet_view.showGridLines=False
        ws.column_dimensions['A'].width=36;return ws

    def literal(self,ws,row,col,value,*,path=None,contextkind='label'):
        cell=ws.cell(row,col,value);point=ws.title+'!'+cell.coordinate
        schema.require(point not in self.provided and point not in self.financial,'A physical cell was assigned twice')
        record={'sheet':ws.title,'cell':cell.coordinate,'value':value}
        if path is None:record['contextkind']=contextkind
        else:record['path']=path
        self.provided[point]=record
        cell.alignment=Alignment(vertical='top',wrap_text=isinstance(value,str))
        cell.number_format='General' if isinstance(value,bool) else ('0' if isinstance(value,int) else '@')
        return point

    def title(self,ws,text):
        point=self.literal(ws,1,1,text,contextkind='layout');ws['A1'].font=Font(size=14,bold=True,color='17365D')
        ws.row_dimensions[1].height=28;return point

    def formula(self,point,expr,*,field,projection,row_key=None,aggregate_key=None,sign=1,unit=None,metric=None):
        sheet,addr=point.rsplit('!',1);cell=self.wb[sheet][addr]
        schema.require(point not in self.provided and point not in self.financial,'Duplicate formula point')
        formula='='+_parts(expr);cell.value=formula
        record={'sheet':sheet,'cell':addr,'formula':formula,'field':field,'projection':projection,'sign':sign,'expression':expr}
        if row_key is not None:record['row_key']=row_key
        if aggregate_key is not None:record['aggregate_key']=aggregate_key
        if unit is not None:record['unit']=unit
        if metric is not None:record['metric']=metric
        self.financial[point]=record
        cell.number_format='General' if projection=='bool' else (MONEY_FORMAT if projection in ('GBP','ratio2dp') or unit=='GBP' else '#,##0')
        if row_key is not None and int(row_key.rsplit('/',1)[1])>=2027:self.forecast.append(point)
        if aggregate_key is not None and int(aggregate_key.rsplit('/',1)[1])>=2027:self.forecast.append(point)
        return formula

    def grid(self,ws,fund,years,scenarios,fields,section):
        mapping={};layout=fund['layout'];self.title(ws,fund['id']+' '+section)
        if layout=='annual_columns':
            for mi,metric in enumerate(fields):self.literal(ws,5+mi,1,_label(metric))
            for si,sid in enumerate(scenarios):
                start=2+si*(len(years)+2);self.literal(ws,3,start,sid,contextkind='layout')
                for yi,year in enumerate(years):
                    self.literal(ws,4,start+yi,year,contextkind='layout')
                    for mi,metric in enumerate(fields):mapping[(f"{fund['id']}/{sid}/{year}",metric)]=ws.title+'!'+ws.cell(5+mi,start+yi).coordinate
        elif layout=='transaction_rows':
            self.literal(ws,4,1,'Year');self.literal(ws,4,2,'Scenario')
            for mi,metric in enumerate(fields):self.literal(ws,4,4+mi,_label(metric))
            for si,sid in enumerate(scenarios):
                for yi,year in enumerate(years):
                    rr=5+si*len(years)+yi;self.literal(ws,rr,1,year,contextkind='layout');self.literal(ws,rr,2,sid,contextkind='layout')
                    for mi,metric in enumerate(fields):mapping[(f"{fund['id']}/{sid}/{year}",metric)]=ws.title+'!'+ws.cell(rr,4+mi).coordinate
        elif layout=='scenario_panels':
            for si,sid in enumerate(scenarios):
                start=3+si*(len(fields)+5);self.literal(ws,start,1,sid,contextkind='layout')
                for yi,year in enumerate(years):self.literal(ws,start+1,2+yi,year,contextkind='layout')
                for mi,metric in enumerate(fields):
                    self.literal(ws,start+2+mi,1,_label(metric))
                    for yi,year in enumerate(years):mapping[(f"{fund['id']}/{sid}/{year}",metric)]=ws.title+'!'+ws.cell(start+2+mi,2+yi).coordinate
        else:
            schema.require(layout=='investor_bridge','Unknown natural layout')
            def group(m):
                if m in schema.ROW_FIELDS[:10] or m in ('closing_cash','fund_cash_residual','investment_cash_use','management_fee_cash_use','operating_cost_cash_use'):return 0
                if m in ('opening_unreturned_capital','opening_unpaid_preference','cumulative_lp_paid_in','preference_accrual','capital_entitlement','preference_entitlement','capital_paid','preference_paid','after_capital_cash','after_preference_cash','closing_unreturned_capital','closing_unpaid_preference','principal_residual','preference_residual','capital_cash_use','preference_cash_use'):return 1
                if 'tier' in m or 'catchup' in m or 'promote' in m or m in ('lp_profit_before_catchup','gp_profit_before_catchup','cumulative_lp_profit','cumulative_gp_profit'):return 2
                return 3
            groups=[[m for m in fields if group(m)==g] for g in range(4)]
            width=max(map(len,groups))+3
            for gi,metrics in enumerate(groups):
                start=3+gi*(len(years)+5);self.literal(ws,start,1,('Fund cash','Capital and preference','Catch-up and promote','Investor bridge')[gi],contextkind='layout')
                for si,sid in enumerate(scenarios):
                    cc=3+si*width;self.literal(ws,start,cc,sid,contextkind='layout')
                    for mi,metric in enumerate(metrics):self.literal(ws,start+1,cc+mi,_label(metric))
                    for yi,year in enumerate(years):
                        self.literal(ws,start+2+yi,cc-1,year,contextkind='layout')
                        for mi,metric in enumerate(metrics):mapping[(f"{fund['id']}/{sid}/{year}",metric)]=ws.title+'!'+ws.cell(start+2+yi,cc+mi).coordinate
        return mapping

    def facts_sheet(self,f,fi):
        ws=self.sheet(f['id']+' Facts');self.title(ws,f['id']+' supplied raw assumptions — money in GBP pence')
        rr=3
        for name,value in f.items():
            if name=='scenarios':continue
            if isinstance(value,list):
                for j,item in enumerate(value):
                    self.literal(ws,rr,1,_label(name)+f' {j+1}');self.facts[(f['id'],name,j)]=self.literal(ws,rr,2,item,path=['funds',fi,name,j]);rr+=1
            else:
                self.literal(ws,rr,1,_label(name));self.facts[(f['id'],name)]=self.literal(ws,rr,2,value,path=['funds',fi,name]);rr+=1
        rr+=2
        columns=('year','scenario','call_date',*schema.PERIOD_MONEY_FIELDS)
        for ci,name in enumerate(columns,1):self.literal(ws,rr,ci,_label(name))
        rr+=1
        for si,scenario in enumerate(f['scenarios']):
            for yi,period in enumerate(scenario['periods']):
                key=f"{f['id']}/{scenario['id']}/{period['year']}"
                for ci,name in enumerate(columns,1):
                    value=scenario['id'] if name=='scenario' else period[name]
                    path=['funds',fi,'scenarios',si,'id'] if name=='scenario' else ['funds',fi,'scenarios',si,'periods',yi,name]
                    self.periods[(key,name)]=self.literal(ws,rr,ci,value,path=path)
                rr+=1
        ws.column_dimensions['C'].width=18

    def ledger(self,f):
        fid=f['id'];scenarios=self.public['scenario_ids'];years=self.public['years']
        current={}
        for name,yy in [('Actual p',[y for y in years if y<=2026]),('Forecast p',[y for y in years if y>=2027])]:
            ws=self.sheet(fid+' '+name)
            current.update(self.grid(ws,f,yy,scenarios,PENCE_FIELDS,name+' posting ledger — integer GBP pence'))
        self.points.update(current)
        fact=lambda name:self.facts[(fid,name)]
        sign=-1 if f['fund_ledger_sign']=='signed_cash_uses' else 1
        use=lambda base,alias:_add(base,alias) if sign<0 else _sub(base,alias)
        for sid in scenarios:
            for yi,year in enumerate(years):
                key=f'{fid}/{sid}/{year}';c=lambda m:current[(key,m)]
                previous=lambda m:fact('opening_'+m+'_pence') if yi==0 else current[(f'{fid}/{sid}/{years[yi-1]}',m)]
                prev_cash=fact('opening_cash_pence') if yi==0 else previous('closing_cash')
                prev_cap=fact('opening_unreturned_capital_pence') if yi==0 else previous('closing_unreturned_capital')
                prev_pref=fact('opening_unpaid_preference_pence') if yi==0 else previous('closing_unpaid_preference')
                prev_paidin=fact('opening_cumulative_lp_paid_in_pence') if yi==0 else previous('cumulative_lp_paid_in')
                prev_lp=fact('opening_cumulative_lp_distributions_pence') if yi==0 else previous('cumulative_lp_distributions')
                prev_lpp=fact('opening_cumulative_lp_profit_pence') if yi==0 else previous('cumulative_lp_profit')
                prev_gpp=fact('opening_cumulative_gp_profit_pence') if yi==0 else previous('cumulative_gp_profit')
                expr={m:self.periods[(key,m+'_pence')] for m in ('lp_call','asset_investment','operating_receipts','realization_receipts','management_fee','operating_cost','reserve')}
                expr.update(opening_cash=prev_cash,opening_unreturned_capital=prev_cap,opening_unpaid_preference=prev_pref,
                    cumulative_lp_paid_in=_add(prev_paidin,c('lp_call')))
                cash_in=_add(c('opening_cash'),c('lp_call'),c('operating_receipts'),c('realization_receipts'))
                expr['cash_before_distribution']=use(cash_in,_add(c('investment_cash_use'),c('management_fee_cash_use'),c('operating_cost_cash_use')))
                expr['available_cash']=_e('max',0,_sub(c('cash_before_distribution'),c('reserve')))
                yref=self.periods[(key,'year')];next_year=_e('date',_add(yref,1),1,1)
                days=_sub(next_year,_e('date',yref,1,1));call_days=_sub(next_year,_e('date',yref,fact('call_month'),1))
                capital_days=_add(_mul(c('opening_unreturned_capital'),days),_mul(c('lp_call'),call_days))
                accrual_base=_e('if',fact('compound_unpaid_preference'),_add(capital_days,_mul(c('opening_unpaid_preference'),days)),capital_days)
                rate=0 if year<=2026 else fact('preferred_rate_bp')
                expr['preference_accrual']=_post(_mul(rate,accrual_base),3650000)
                expr['capital_entitlement']=_add(c('opening_unreturned_capital'),c('lp_call'))
                expr['preference_entitlement']=_add(c('opening_unpaid_preference'),c('preference_accrual'))
                expr['capital_paid']=_e('min',c('available_cash'),c('capital_entitlement'))
                expr['after_capital_cash']=use(c('available_cash'),c('capital_cash_use'))
                expr['preference_paid']=_e('min',c('after_capital_cash'),c('preference_entitlement'))
                expr['after_preference_cash']=use(c('after_capital_cash'),c('preference_cash_use'))
                expr['lp_profit_before_catchup']=_add(prev_lpp,c('preference_paid'))
                expr['gp_profit_before_catchup']=prev_gpp
                target=_post(_mul(c('lp_profit_before_catchup'),fact('base_gp_carry_bp')),_sub(10000,fact('base_gp_carry_bp')))
                expr['catchup_entitlement']=_e('max',0,_sub(target,c('gp_profit_before_catchup')))
                expr['catchup_paid']=_e('min',c('after_preference_cash'),c('catchup_entitlement'))
                expr['after_catchup_cash']=use(c('after_preference_cash'),c('catchup_cash_use'))
                for tier in (1,2,3):
                    rest=_sub(c('after_catchup_cash'),_add(0,*(c(f'tier{i}_cash') for i in range(1,tier))))
                    gp=self.facts[(fid,'promote_gp_bp',tier-1)];lp_share=_sub(10000,gp)
                    if tier<3:
                        threshold=_post(_mul(c('cumulative_lp_paid_in'),self.facts[(fid,'lp_distribution_multiple_threshold_bp',tier-1)]),10000)
                        prior_lp=_add(prev_lp,c('capital_paid'),c('preference_paid'),*(c(f'tier{i}_lp') for i in range(1,tier)))
                        gap=_e('max',0,_sub(threshold,prior_lp))
                        endpoint=_e('quotient',_sub(_mul(_add(_mul(2,gap),1),10000),1),_mul(2,lp_share))
                        expr[f'tier{tier}_cash']=_e('min',rest,_e('max',0,endpoint))
                    else:expr['tier3_cash']=rest
                    expr[f'tier{tier}_lp']=_post(_mul(c(f'tier{tier}_cash'),lp_share),10000)
                    expr[f'tier{tier}_gp']=_sub(c(f'tier{tier}_cash'),c(f'tier{tier}_lp'))
                expr['lp_promote_cash']=_add(*(c(f'tier{i}_lp') for i in (1,2,3)))
                expr['gp_promote_cash']=_add(*(c(f'tier{i}_gp') for i in (1,2,3)))
                expr['lp_total_distribution']=_add(c('capital_paid'),c('preference_paid'),c('lp_promote_cash'))
                expr['gp_total_distribution']=_add(c('catchup_paid'),c('gp_promote_cash'))
                expr['fund_total_distribution']=_add(c('lp_total_distribution'),c('gp_total_distribution'))
                expr['closing_cash']=use(c('cash_before_distribution'),_add(*(c(m) for m in ('capital_cash_use','preference_cash_use','catchup_cash_use','lp_promote_cash_use','gp_promote_cash_use'))))
                expr['closing_unreturned_capital']=_sub(c('capital_entitlement'),c('capital_paid'))
                expr['closing_unpaid_preference']=_sub(c('preference_entitlement'),c('preference_paid'))
                expr['cumulative_lp_distributions']=_add(prev_lp,c('lp_total_distribution'))
                expr['cumulative_lp_profit']=_add(prev_lpp,c('preference_paid'),c('lp_promote_cash'))
                expr['cumulative_gp_profit']=_add(prev_gpp,c('gp_total_distribution'))
                expr['lp1_call']=_post(_mul(c('lp_call'),fact('lp1_share_bp')),10000)
                expr['lp2_call']=_sub(c('lp_call'),c('lp1_call'))
                expr['lp1_distribution']=_post(_mul(c('lp_total_distribution'),fact('lp1_share_bp')),10000)
                expr['lp2_distribution']=_sub(c('lp_total_distribution'),c('lp1_distribution'))
                expr['lp1_net_cashflow']=_sub(c('lp1_distribution'),c('lp1_call'))
                expr['lp2_net_cashflow']=_sub(c('lp2_distribution'),c('lp2_call'))
                expr['gp_net_cashflow']=c('gp_total_distribution')
                expr['fund_cash_residual']=_sub(_sub(c('cash_before_distribution'),c('fund_total_distribution')),c('closing_cash'))
                expr['recipient_cash_residual']=_sub(c('fund_total_distribution'),_add(c('lp1_distribution'),c('lp2_distribution'),c('gp_net_cashflow')))
                expr['principal_residual']=_sub(_sub(c('capital_entitlement'),c('capital_paid')),c('closing_unreturned_capital'))
                expr['preference_residual']=_sub(_sub(c('preference_entitlement'),c('preference_paid')),c('closing_unpaid_preference'))
                schema.require(set(expr)==set(schema.ROW_FIELDS),'Every posted business field needs its native definition')
                for metric in schema.ROW_FIELDS:
                    before=self.formula(c(metric),expr[metric],field=metric,projection='pence',row_key=key)
                    if year>=2027 and metric=='after_preference_cash':
                        faulty=_sub(c('after_capital_cash'),c('preference_cash_use')) if sign<0 else _add(c('after_capital_cash'),c('preference_cash_use'))
                        self.roots.append({'sheet':c(metric).rsplit('!',1)[0],'cell':c(metric).rsplit('!',1)[1],
                            'row_key':key,'field':metric,'before':before,'after':'='+_parts(faulty)})
                for alias,metric in USES.items():self.formula(c(alias),_mul(sign,c(metric)),field=metric,projection='presentation_sign',
                    row_key=key,sign=sign,unit='pence',metric=alias)
        ws=self.sheet(fid+' Reports');reports=self.grid(ws,f,years,scenarios,REPORT_FIELDS,'fund and investor reports — GBP')
        for sid in scenarios:
            for year in years:
                key=f'{fid}/{sid}/{year}'
                for metric in schema.ROW_FIELDS:self.formula(reports[(key,metric)],_e('div',current[(key,metric)],100),
                    field=metric,projection='GBP',row_key=key)
                for alias,metric in USES.items():self.formula(reports[(key,alias)],_e('div',current[(key,alias)],100),
                    field=metric,projection='presentation_sign',row_key=key,sign=sign,unit='GBP',metric=alias)
                self.formula(reports[(key,'lp_distribution_multiple')],_e('round',_e('div',current[(key,'cumulative_lp_distributions')],current[(key,'cumulative_lp_paid_in')]),2),
                    field='lp_distribution_multiple',projection='ratio2dp',row_key=key)
                self.formula(reports[(key,'capital_and_pref_shortfall')],_e('or',_e('gt',current[(key,'closing_unreturned_capital')],0),_e('gt',current[(key,'closing_unpaid_preference')],0)),
                    field='capital_and_pref_shortfall',projection='bool',row_key=key)

    def aggregate(self):
        pence=self.sheet('Aggregate Pence');report=self.sheet('Aggregate GBP')
        for ws in (pence,report):
            self.title(ws,'Management aggregation only — no interfund support')
            self.literal(ws,3,1,'Scenario');self.literal(ws,3,2,'Year')
            for i,m in enumerate(schema.AGGREGATE_FIELDS,3):self.literal(ws,3,i,_label(m))
        rr=4
        for sid in self.public['scenario_ids']:
            for year in self.public['years']:
                key=f'{sid}/{year}'
                for ws in (pence,report):self.literal(ws,rr,1,sid,contextkind='layout');self.literal(ws,rr,2,year,contextkind='layout')
                for ci,metric in enumerate(schema.AGGREGATE_FIELDS,3):
                    pp='Aggregate Pence!'+pence.cell(rr,ci).coordinate;gp='Aggregate GBP!'+report.cell(rr,ci).coordinate
                    self.formula(pp,_add(*(self.points[(f"{f['id']}/{sid}/{year}",metric)] for f in self.public['funds'])),
                        field=metric,projection='pence',aggregate_key=key)
                    self.formula(gp,_e('div',pp,100),field=metric,projection='GBP',aggregate_key=key)
                rr+=1


def _cache_census(path):
    ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'};count=0
    with zipfile.ZipFile(path) as z:
        for member in z.namelist():
            if member.startswith('xl/worksheets/sheet') and member.endswith('.xml'):
                root=ET.fromstring(z.read(member))
                for c in root.findall('.//s:sheetData/s:row/s:c',ns):
                    if c.find('s:f',ns) is None:continue
                    count+=1;v=c.find('s:v',ns)
                    schema.require(v is None or not v.text,'An unverified formula cache must be absent')
    return count


def emit(public,output_directory,*,max_formulas=250000):
    public=schema.validate_spec(public);output=Path(output_directory).absolute()
    schema.require(not output.exists() and output==output.resolve(),'Emit only to a fresh real directory')
    output.mkdir(parents=True);b=_Book(public);c=schema.contract()
    ws=b.sheet('Read Me');b.title(ws,'Hypothetical independent fund and investor scenarios')
    b.literal(ws,3,1,'Each scenario is an independent cash path and restarts the supplied opening balances. FY2025–26 are provided scenario reports; they need not be identical historical cash paths.',contextkind='policy')
    b.literal(ws,4,1,'Posting ledgers and supplied assumptions are integer GBP pence. Reports show GBP. Basis points are explicitly labelled. Ratios are display-only; Boolean status cells use General format.',contextkind='policy')
    for i,text in enumerate(c['business_policies'],6):b.literal(ws,i,1,text,contextkind='policy')
    ws.column_dimensions['A'].width=150
    register=b.sheet('Fund Register');b.title(register,'Declared independent hypothetical funds')
    columns=('id','type','layout','fund_ledger_sign','commitment_pence','lp1_share_bp','preferred_rate_bp','compound_unpaid_preference','base_gp_carry_bp','call_month')
    for i,name in enumerate(columns,1):b.literal(register,3,i,_label(name))
    for fi,f in enumerate(public['funds']):
        for ci,name in enumerate(columns,1):b.literal(register,4+fi,ci,f[name],path=['funds',fi,name])
        b.facts_sheet(f,fi);b.ledger(f)
    b.aggregate()
    block_count=len(public['funds'])*len(public['years'])*len(public['scenario_ids'])
    aggregate_count=len(public['years'])*len(public['scenario_ids'])
    count=block_count*130+aggregate_count*40
    schema.require(len(b.financial)==count<=max_formulas,'The complete formula geometry exceeds the declared cap')
    schema.require(len(b.wb.sheetnames)==len(public['funds'])*4+4,'The complete four-sheet-per-fund geometry changed')
    roots_expected=len(public['funds'])*len(public['scenario_ids'])*len([y for y in public['years'] if y>=2027])
    schema.require(len(b.roots)==roots_expected and len(set(b.forecast))==len(b.forecast),'Duplicate or missing full forecast roots')
    goal=output/'goal_cache_free.xlsx';b.wb.save(goal)
    schema.require(_cache_census(goal)==count,'The cache-free source formula coverage changed')
    literals={p:{'type':'boolean' if isinstance(r['value'],bool) else ('number' if isinstance(r['value'],int) else 'string'),'value':r['value']} for p,r in b.provided.items()}
    bindings={'version':1,'specification_sha256':schema.canonical_sha256(public),'financial':b.financial,
        'provided':b.provided,'FM_mask_points':b.forecast,'DBG_root_edits':b.roots}
    definition={'version':1,'sheetnames':b.wb.sheetnames,'formulas':{p:r['formula'] for p,r in b.financial.items()},
        'literals':literals,'rawfacts':{p:r for p,r in b.provided.items() if 'path' in r},
        'FM_mask_points':b.forecast,'DBG_root_edits':b.roots,'calculation':{'iterate':False,'calcMode':'auto'},
        'formula_count':count,'forecast_formula_count':len(b.forecast),'debug_root_count':len(b.roots)}
    views={}
    for mode in ('financial_modeling','debugging'):
        folder=output/mode;folder.mkdir();wb=load_workbook(goal)
        if mode=='financial_modeling':
            for point in b.forecast:
                name,addr=point.rsplit('!',1);wb[name][addr].value=None
            instruction='Complete the forecast fund and investor reports across all funds, periods and scenarios using the Read Me policies. Preserve the supplied assumptions, provided actual scenario reports and existing layout. Save the completed workbook to /app/output.xlsx.'
        else:
            for edit in b.roots:wb[edit['sheet']][edit['cell']]=edit['after']
            instruction=c['task_views']['public_brief']
        target=folder/'input.xlsx';wb.save(target);wb.close()
        _cache_census(target);brief=folder/'instruction.md';brief.write_text(instruction+'\n')
        views[mode]={'input':reference(target),'instruction':reference(brief)}
    b.wb.close()
    spec=_write(output/'specification.json',public);binding_ref=_write(output/'bindings.json',bindings);definition_ref=_write(output/'definition.json',definition)
    return _write(output/'receipt.json',{'kind':KIND,'version':1,'specification':spec,
        'specification_sha256':schema.canonical_sha256(public),'source':reference(goal),'views':views,
        'bindings':binding_ref,'definition':definition_ref,'sheet_count':len(definition['sheetnames']),
        'formula_count':count,'FM_mask_count':len(b.forecast),'DBG_root_count':len(b.roots),
        'all_formula_caches_absent':True,'actual_D_unknown':True,'independent_financial_expected_in_workbook':False,
        'model_LO_solver_calls':0,'qualified':False})
