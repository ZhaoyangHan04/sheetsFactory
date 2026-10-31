"""Complete typed comparison of independent financial A/B outputs.

The plan helpers only aggregate already posted standalone values. They are not
a third financial posting implementation, optimizer, source or workbook audit.
All differences and infeasible candidates are returned without truncation.
"""
from __future__ import annotations

import hashlib
import json
import time

from .spec import (EXACT_LIMIT, T0_FIELDS, ANNUAL_FIELDS, VINTAGE_FIELDS,
                   GROUP_FIELDS, load_spec, validate_plan)


_MISSING=object()


def _sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
        ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def _value(value):
    return '__missing_field__' if value is _MISSING else value


def _same(a,b):
    if type(a) is not type(b):return False
    if isinstance(a,dict):return set(a)==set(b) and all(_same(a[k],b[k]) for k in a)
    if isinstance(a,list):return len(a)==len(b) and all(_same(x,y) for x,y in zip(a,b))
    return a==b


def _get(value,*keys):
    for key in keys:
        if not isinstance(value,dict) or key not in value:return _MISSING
        value=value[key]
    return value


def _sum(values):
    values=list(values)
    if any(type(v) is not int for v in values) or sum(abs(v) for v in values)>=EXACT_LIMIT:
        raise ValueError('A complete integer aggregation exceeds the exact domain')
    return sum(values)


def compare_universes(specification,universe_a,universe_b):
    public=load_spec(specification);differences=[];issues=[];infeasible=[];details=[]
    counts={'project_scenarios':0,'t0_fields':0,'annual_fields':0,'vintage_fields':0,'posted_NPV':0}
    digest=_sha(public)
    def issue(side,path,claim,value):issues.append({'implementation':side,'path':path,'claim':claim,'value':_value(value)})
    def equal(path,a,b):
        if not _same(a,b):differences.append({'path':path,'A':_value(a),'B':_value(b),
            'A_type':'missing' if a is _MISSING else type(a).__name__,'B_type':'missing' if b is _MISSING else type(b).__name__})
    def integer(side,path,value,nonnegative=False,flag=False):
        valid=type(value) is int and abs(value)<EXACT_LIMIT and (not nonnegative or value>=0) and (not flag or value in (0,1))
        if not valid:issue(side,path,'An exact typed financial integer is required',value)
        return valid
    def index(side,path,rows,*,vintage=False):
        result={}
        if not isinstance(rows,list):issue(side,path,'A complete row list is required',rows);return result
        if not vintage and [r.get('year') if isinstance(r,dict) else None for r in rows]!=public['years']:
            issue(side,path,'Every ordered FY row is required',rows)
        for position,row in enumerate(rows):
            if not isinstance(row,dict):issue(side,path+'/'+str(position),'A typed row is required',row);continue
            year=row.get('year');origin=row.get('origin_year') if vintage else None
            valid=type(year) is int and year in public['years'] and (not vintage or type(origin) is int and 1<=origin<=year)
            if not valid:issue(side,path+'/'+str(position),'An in-scope row identity is required',row);continue
            key=(year,origin) if vintage else year
            if key in result:issue(side,path+'/'+str(key),'Duplicate row identity',row);continue
            result[key]=row
            expected=public['fiscal_year_start']+year-1
            if type(row.get('fiscal_year')) is not int or row['fiscal_year']!=expected:
                issue(side,path+'/'+str(key)+'/fiscal_year','The public fiscal-year label differs',row.get('fiscal_year'))
        return result
    for side,u in (('A',universe_a),('B',universe_b)):
        for key,expected in (('kind','linear_capital_portfolio_standalone_universe'),('version',1),('specification_sha256',digest),('project_order',public['project_ids']),
                ('scenario_ids',public['scenario_ids']),('years',public['years'])):
            if not _same(_get(u,key),expected):issue(side,key,'The complete public universe identity differs',_get(u,key))
        projects=_get(u,'projects')
        if not isinstance(projects,dict) or set(projects)!=set(public['project_ids']):
            issue(side,'projects','No candidate can be omitted or substituted',list(projects) if isinstance(projects,dict) else projects)
        if _get(u,'all_standalone_feasible') is not True:issue(side,'all_standalone_feasible','Every candidate/scenario must be feasible',_get(u,'all_standalone_feasible'))
    for pid in public['project_ids']:
        for side,u in (('A',universe_a),('B',universe_b)):
            scenarios=_get(u,'projects',pid,'scenarios')
            if not isinstance(scenarios,dict) or set(scenarios)!=set(public['scenario_ids']):
                issue(side,'projects/'+pid+'/scenarios','Every scenario is required',scenarios)
        for sid in public['scenario_ids']:
            counts['project_scenarios']+=1;path='projects/'+pid+'/scenarios/'+sid
            a=_get(universe_a,'projects',pid,'scenarios',sid);b=_get(universe_b,'projects',pid,'scenarios',sid)
            start=len(differences);schema_start=len(issues);maximum={'A':0,'B':0}
            for key,expected in (('project_id',pid),('scenario_id',sid)):
                for side,r in (('A',a),('B',b)):
                    if not _same(_get(r,key),expected):issue(side,path+'/'+key,'The result identity differs',_get(r,key))
            for side,r in (('A',a),('B',b)):
                if _get(r,'feasible') is not True:
                    infeasible.append({'implementation':side,'project_id':pid,'scenario_id':sid,'feasible':_value(_get(r,'feasible'))})
                values=_get(r,'t0')
                if not isinstance(values,dict) or set(values)!=set(T0_FIELDS):issue(side,path+'/t0','Complete T0 field coverage is required',values)
                for field in ('balance_check','funding_gap','cash_close'):
                    if _get(r,'t0',field)!=0:issue(side,path+'/t0/'+field,'The required feasible time-zero state is not zero',_get(r,'t0',field))
            for field in T0_FIELDS:
                av,bv=_get(a,'t0',field),_get(b,'t0',field);equal(path+'/t0/'+field,av,bv);counts['t0_fields']+=1
                for side,value in (('A',av),('B',bv)):
                    if integer(side,path+'/t0/'+field,value):maximum[side]=max(maximum[side],abs(value))
            annual_a=index('A',path+'/annual',_get(a,'annual'));annual_b=index('B',path+'/annual',_get(b,'annual'))
            fields=(*ANNUAL_FIELDS,'operating_active','feasible')
            for year in public['years']:
                for side,annual in (('A',annual_a),('B',annual_b)):
                    row=annual.get(year,{})
                    if set(row)!=set(fields)|{'year','fiscal_year'}:issue(side,path+'/annual/'+str(year),'Complete annual field coverage is required',row)
                for field in fields:
                    av,bv=_get(annual_a.get(year,{}),field),_get(annual_b.get(year,{}),field)
                    equal(path+'/annual/'+str(year)+'/'+field,av,bv);counts['annual_fields']+=1
                    for side,value in (('A',av),('B',bv)):
                        if integer(side,path+'/annual/'+str(year)+'/'+field,value,flag=field in ('operating_active','feasible')):
                            maximum[side]=max(maximum[side],abs(value))
                for side,annual in (('A',annual_a),('B',annual_b)):
                    row=annual.get(year,{})
                    for field in ('balance_check','cash_check','asset_check','debt_check','loss_check'):
                        if _get(row,field)!=0:issue(side,path+'/annual/'+str(year)+'/'+field,'An accounting bridge is nonzero',_get(row,field))
                    if _get(row,'funding_gap')!=0 or _get(row,'feasible')!=1:
                        issue(side,path+'/annual/'+str(year),'A standalone FY is not feasible',row)
                    if year==public['years'][-1]:
                        for field in ('cash_close','asset_nbv_close','debt_close'):
                            if _get(row,field)!=0:issue(side,path+'/annual/'+str(year)+'/'+field,'The terminal financial state is not zero',_get(row,field))
            vintage_a=index('A',path+'/tax_vintages',_get(a,'tax_vintages'),vintage=True)
            vintage_b=index('B',path+'/tax_vintages',_get(b,'tax_vintages'),vintage=True)
            for side,rows in (('A',vintage_a),('B',vintage_b)):
                for identity,row in rows.items():
                    if set(row)!=set(VINTAGE_FIELDS)|{'year','fiscal_year','origin_year'}:issue(side,path+'/tax_vintages/'+str(identity),'Complete vintage fields are required',row)
                    for field in VINTAGE_FIELDS:integer(side,path+'/tax_vintages/'+str(identity)+'/'+field,_get(row,field),nonnegative=True)
            # Missing sparse events mean zero. Compare the entire finite FY×origin
            # grid, including all-zero origins, rather than intersecting records.
            for year in public['years']:
                for origin in range(1,year+1):
                    for field in VINTAGE_FIELDS:
                        av=vintage_a.get((year,origin),{}).get(field,0);bv=vintage_b.get((year,origin),{}).get(field,0)
                        equal(path+'/tax_vintages/'+str((year,origin))+'/'+field,av,bv);counts['vintage_fields']+=1
            equal(path+'/feasible',_get(a,'feasible'),_get(b,'feasible'))
            av,bv=_get(a,'npv_pence'),_get(b,'npv_pence');equal(path+'/npv_pence',av,bv);counts['posted_NPV']+=1
            for side,r,value in (('A',a,av),('B',b,bv)):
                if _get(r,'feasible') is True:integer(side,path+'/npv_pence',value)
                elif value is not None:issue(side,path+'/npv_pence','Infeasible diagnostics cannot have a valid NPV',value)
            bounds={}
            for side,r in (('A',a),('B',b)):
                name='arithmetic_safety' if side=='A' else 'arithmetic_bounds';record=_get(r,name);bounds[side]=_value(record)
                if not isinstance(record,dict):issue(side,path+'/'+name,'The arithmetic-bound receipt is required',record);continue
                if side=='A':
                    valid=(record.get('passed') is True and record.get('exclusive_integer_limit')==str(EXACT_LIMIT)
                        and type(record.get('checked_integer_operations')) is int and record['checked_integer_operations']>0
                        and type(record.get('maximum_absolute_integer')) is int and maximum[side]<=record['maximum_absolute_integer']<EXACT_LIMIT)
                else:
                    metrics=[record.get(k) for k in ('maximum_absolute_amount_times_bp','maximum_sum_of_absolute_terms','maximum_absolute_posted_value')]
                    valid=(record.get('all_postings_products_and_sums_below_2_to_53') is True
                        and all(type(v) is int and 0<=v<EXACT_LIMIT for v in metrics)
                        and max(metrics,default=-1)>=maximum[side])
                if not valid:issue(side,path+'/'+name,'Arithmetic bounds are incomplete or outside the exact domain',record)
            details.append({'project_id':pid,'scenario_id':sid,'npv_pence_A':_value(av),'npv_pence_B':_value(bv),
                'feasible_A':_get(a,'feasible') is True,'feasible_B':_get(b,'feasible') is True,
                'difference_count':len(differences)-start,'schema_issue_count':len(issues)-schema_start,'arithmetic_bounds':bounds})
    return {'kind':'complete_linear_capital_A_B_financial_crosscheck','version':1,'specification_sha256':digest,
        'universe_A_sha256':_sha(universe_a),'universe_B_sha256':_sha(universe_b),'counts':counts,
        'project_scenarios':details,'differences':differences,'schema_issues':issues,'infeasible_candidates':infeasible,
        'passed':not differences and not issues and not infeasible,'differences_truncated':False,
        'unrounded_NPV_and_implementation_metadata_compared':False,
        'financial_forward_implementations':2,'third_financial_implementation_claimed':False}


def _row_templates(s):
    rows={};limits=s['shared_limits']
    def add(identity,family,limit,scenario=None,year=None,tag=None):
        if identity in rows:raise ValueError('Duplicate business row identity')
        rows[identity]={'id':identity,'family':family,'scenario_id':scenario,'year':year,'limit':limit,'lhs':0,'_tag':tag}
    add('initial_sponsor_equity','initial_sponsor_equity',limits['initial_sponsor_equity_pence'])
    for sid in s['scenario_ids']:
        for year in s['years']:
            add(f'annual_new_lp:{sid}:{year}','annual_new_lp',limits['annual_new_lp_pence'][sid][str(year)],sid,year)
            add(f'annual_debt_close:{sid}:{year}','annual_debt_close',limits['annual_debt_close_pence'][sid][str(year)],sid,year)
            for resource in s['resource_ids']:add(f'resource:{resource}:{sid}:{year}','resource',limits['resource_capacity_units'][resource][sid][str(year)],sid,year,resource)
    for label,field in (('region','region_exposure_pence'),('sector','sector_exposure_pence')):
        for category in s[label+'_ids']:
            for year in s['years']:add(f'{label}_exposure:{category}:{year}',label+'_exposure',limits[field][category][str(year)],None,year,category)
    for row in s['exclusivity_groups']:add('exclusivity:'+row['id'],'exclusivity',1,tag=row['project_ids'])
    for row in s['prerequisites']:add('prerequisite:'+row['id'],'prerequisite',0,tag=(row['dependent'],row['prerequisite']))
    return rows


def _finish(s,u,plan,groups,rows):
    finished=[]
    for _,row in sorted(rows.items()):
        row={k:v for k,v in row.items() if k!='_tag'}
        row.update(slack=_sum((row['limit'],-row['lhs'])),passed=row['lhs']<=row['limit']);finished.append(row)
    selected=[pid for pid in s['project_ids'] if plan[pid]]
    standalone=all(u['projects'][pid]['scenarios'][sid]['feasible'] is True for pid in selected for sid in s['scenario_ids'])
    feasible=standalone and all(r['passed'] for r in finished)
    objective=_sum(u['projects'][pid]['scenarios']['S01']['npv_pence'] for pid in selected) if feasible else None
    return {'group':{'scenarios':groups},'constraints':finished,'feasible':feasible,'objective_pence':objective,
        'selected_standalone_feasible':standalone}


def _aggregate_a(s,u,plan):
    """Project-first accumulation of posted A values; no financial reposting."""
    rows=_row_templates(s)
    groups={sid:{'annual':[{'year':y,'fiscal_year':s['fiscal_year_start']+y-1,**{f:0 for f in GROUP_FIELDS}}
        for y in s['years']]} for sid in s['scenario_ids']}
    def add(identity,value):rows[identity]['lhs']=_sum((rows[identity]['lhs'],value))
    for p in s['projects']:
        pid=p['id']
        if not plan[pid]:continue
        result=u['projects'][pid]['scenarios']
        add('initial_sponsor_equity',result['S01']['t0']['lp_call'])
        for sid in s['scenario_ids']:
            for i,y in enumerate(s['years']):
                row=result[sid]['annual'][i];group=groups[sid]['annual'][i]
                for target,source in (('new_lp_calls','lp_call'),('year_end_debt','debt_close'),('lp_distributions','lp_distribution'),('net_lp_cashflow','net_lp_cashflow'),('asset_nbv','asset_nbv_close')):
                    group[target]=_sum((group[target],row[source]))
                add(f'annual_new_lp:{sid}:{y}',row['lp_call']);add(f'annual_debt_close:{sid}:{y}',row['debt_close'])
                for resource in s['resource_ids']:add(f'resource:{resource}:{sid}:{y}',p['resource_usage_units'][resource][sid][str(y)])
        for i,y in enumerate(s['years']):
            nbv=result['S01']['annual'][i]['asset_nbv_close']
            add(f'region_exposure:{p["region"]}:{y}',nbv);add(f'sector_exposure:{p["sector"]}:{y}',nbv)
        for group in s['exclusivity_groups']:
            if pid in group['project_ids']:add('exclusivity:'+group['id'],1)
        for edge in s['prerequisites']:
            if pid==edge['dependent']:add('prerequisite:'+edge['id'],1)
            if pid==edge['prerequisite']:add('prerequisite:'+edge['id'],-1)
    return _finish(s,u,plan,groups,rows)


def _aggregate_b(s,u,plan):
    """Capacity-row-first reduction of posted B values; no financial reposting."""
    selected=[p for p in s['projects'] if plan[p['id']]];groups={};rows=_row_templates(s)
    for sid in s['scenario_ids']:
        groups[sid]={'annual':[]}
        for y in s['years']:
            annual=[u['projects'][p['id']]['scenarios'][sid]['annual'][y-1] for p in selected]
            groups[sid]['annual'].append({'year':y,'fiscal_year':s['fiscal_year_start']+y-1,
                'new_lp_calls':_sum(r['lp_call'] for r in annual),'year_end_debt':_sum(r['debt_close'] for r in annual),
                'lp_distributions':_sum(r['lp_distribution'] for r in annual),'net_lp_cashflow':_sum(r['net_lp_cashflow'] for r in annual),
                'asset_nbv':_sum(r['asset_nbv_close'] for r in annual)})
    for row in rows.values():
        family,sid,y,tag=row['family'],row['scenario_id'],row['year'],row['_tag']
        if family=='initial_sponsor_equity':terms=(u['projects'][p['id']]['scenarios']['S01']['t0']['lp_call'] for p in selected)
        elif family=='annual_new_lp':terms=(u['projects'][p['id']]['scenarios'][sid]['annual'][y-1]['lp_call'] for p in selected)
        elif family=='annual_debt_close':terms=(u['projects'][p['id']]['scenarios'][sid]['annual'][y-1]['debt_close'] for p in selected)
        elif family=='resource':terms=(p['resource_usage_units'][tag][sid][str(y)] for p in selected)
        elif family in ('region_exposure','sector_exposure'):
            attribute='region' if family=='region_exposure' else 'sector'
            terms=(u['projects'][p['id']]['scenarios']['S01']['annual'][y-1]['asset_nbv_close'] for p in selected if p[attribute]==tag)
        elif family=='exclusivity':terms=(plan[pid] for pid in tag)
        else:terms=(plan[tag[0]],-plan[tag[1]])
        row['lhs']=_sum(terms)
    return _finish(s,u,plan,groups,rows)


def _compare_plans(s,a,b,plans,require_feasible):
    if isinstance(plans,dict):plans=[{'id':key,'plan':value} for key,value in plans.items()]
    if not isinstance(plans,list):raise ValueError('Named complete diagnostic or best/runner plans are required')
    results=[];seen=set();problems=[]
    for index,item in enumerate(plans):
        name=item.get('id') if isinstance(item,dict) else None
        errors=[];aa=bb=None
        if type(name) is not str or not name or name in seen:
            errors.append({'claim':'Each plan needs a unique nonempty identity','value':name})
        if type(name) is str:seen.add(name)
        try:plan=validate_plan(s,item.get('plan') if isinstance(item,dict) else None)
        except (ValueError,TypeError) as exc:errors.append({'claim':str(exc)});plan=None
        if plan is not None:
            for label,function in (('A',_aggregate_a),('B',_aggregate_b)):
                try:
                    actual=function(s,a if label=='A' else b,plan)
                    if label=='A':aa=actual
                    else:bb=actual
                except (ValueError,KeyError,TypeError,IndexError) as exc:errors.append({'implementation':label,'claim':str(exc)})
        differences=[]
        if aa is not None and bb is not None:
            for key in ('group','constraints','feasible','objective_pence','selected_standalone_feasible'):
                if not _same(aa[key],bb[key]):differences.append({'field':key,'A':aa[key],'B':bb[key]})
            if require_feasible and (not aa['feasible'] or not bb['feasible']):errors.append({'claim':'A required best/runner plan is not fully feasible'})
        passed=not errors and not differences and aa is not None and bb is not None
        if not passed:problems.append({'index':index,'id':name})
        results.append({'id':name,'plan':plan,'A':aa,'B':bb,'differences':differences,'errors':errors,'passed':passed})
    return {'kind':'posted_universe_plan_aggregation_crosscheck','version':1,'plan_count':len(results),'plans':results,
        'passed':not problems,'failed_plan_identities':problems,'require_group_feasible':require_feasible,
        'differences_truncated':False,'additional_financial_forwards':0,'third_financial_implementation_claimed':False,
        'scope':'Two integer aggregation paths over the respective already-posted financial universes, not financial reposting or optimization'}


def compare_plans(specification,universe_a,universe_b,plans,*,require_feasible=False):
    if type(require_feasible) is not bool:raise ValueError('The plan feasibility policy must be an explicit Boolean')
    s=load_spec(specification);financial=compare_universes(s,universe_a,universe_b)
    result=_compare_plans(s,universe_a,universe_b,plans,require_feasible)
    result.update(financial_universe_check=financial,passed=result['passed'] and financial['passed'])
    return result


def crosscheck(specification,plans=None,*,require_feasible=False,progress=None):
    """Call each financial universe exactly once; return all data for persistence."""
    if progress is not None and not callable(progress):raise ValueError('An optional callable progress hook is required')
    if type(require_feasible) is not bool:raise ValueError('The plan feasibility policy must be an explicit Boolean')
    from . import candidate_a,ledger
    s=load_spec(specification)
    def event(name,**details):
        if progress is not None:progress(name,details)
    started=time.monotonic();event('A_started')
    a=candidate_a.simulate_universe(s);event('A_completed',elapsed_seconds=time.monotonic()-started)
    started=time.monotonic();event('B_started')
    b=ledger.simulate_universe(s);event('B_completed',elapsed_seconds=time.monotonic()-started)
    financial=compare_universes(s,a,b);event('universe_compared',passed=financial['passed'],counts=financial['counts'])
    aggregated=None if plans is None else _compare_plans(s,a,b,plans,require_feasible)
    event('plans_compared',plan_count=0 if aggregated is None else aggregated['plan_count'],passed=aggregated is None or aggregated['passed'])
    return {'kind':'independent_linear_capital_financial_crosscheck','version':1,'specification_sha256':_sha(s),
        'universe_A':a,'universe_B':b,'universe_comparison':financial,'plan_comparison':aggregated,
        'passed':financial['passed'] and (aggregated is None or aggregated['passed']),
        'financial_universe_calls':{'A':1,'B':1},'optimization_performed':False,'source_or_difficulty_certified':False}
