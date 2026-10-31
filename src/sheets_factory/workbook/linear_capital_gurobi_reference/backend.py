"""Matrix-only Gurobi 13.0.3 research backend; importing starts no native API.

Even an internally checked OPTIMAL result is not reference admission. In
particular, the historical P07 counterexample requires independent proof.
"""
from __future__ import annotations
from collections import Counter
from fractions import Fraction
import hashlib
import json
import math
import struct
from pathlib import Path
import time

VERSION = '13.0.3'
PARAMETERS = {'Threads':16,'MIPGap':0.0,'MIPGapAbs':0.0,'NumericFocus':3,
    **{name:1e-9 for name in ('FeasibilityTol','IntFeasTol','OptimalityTol',
        'BarConvTol','BarQCPConvTol','PSDTol')}}
MODEL_KEYS = {'kind','version','project_ids','objective_pence','rows',
    'specification_sha256','universe_sha256'}
ROW_KEYS = {'id','family','scenario_id','year','coefficients','limit'}


def require(condition, message):
    if not condition: raise ValueError(message)


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def sha(value): return hashlib.sha256(canonical(value)).hexdigest()


def integer(value): return type(value) is int and abs(value)<2**53


def validate_model(model):
    require(type(model) is dict and set(model)==MODEL_KEYS,'Complete canonical integer matrix required')
    ids=model['project_ids'];require(type(ids) is list and ids==[f'P{i:03d}' for i in range(1,len(ids)+1)],'Complete ordered project identities required')
    n=len(ids);require(n in (1,2,3,4,360,720,1080),'Unsupported declared matrix dimension')
    kind='linear_capital_scaled_direct_binary_integer_model' if n<=360 else f'linear_capital_dimension_probe_direct_binary_integer_model_n{n}'
    require(model['kind']==kind and type(model['version']) is int and model['version']==(2 if n<=360 else 3),'Unknown matrix identity/version')
    for key in ('specification_sha256','universe_sha256'):
        v=model[key];require(type(v) is str and len(v)==64 and all(x in '0123456789abcdef' for x in v),'Exact ancestry SHA required')
    obj=model['objective_pence'];require(type(obj) is list and len(obj)==n and all(integer(x) for x in obj) and sum(map(abs,obj))<2**53,'Integer objective outside exact domain')
    rows=model['rows'];require(type(rows) is list and len(rows)+(1 if n else 0)<=2000,'Restricted native constraint cap exceeded')
    names=[]
    for r in rows:
        require(type(r) is dict and set(r)==ROW_KEYS,'Incomplete original integer row')
        require(type(r['id']) is str and r['id'] and type(r['family']) is str and r['family'],'Stable row identity required')
        require(r['scenario_id'] is None or r['scenario_id'] in ('S01','S02','S03'),'Unknown scenario')
        require(r['year'] is None or type(r['year']) is int and 0<=r['year']<=20,'Unknown fiscal year')
        a=r['coefficients'];require(type(a) is list and len(a)==n and all(integer(x) for x in a) and integer(r['limit']) and sum(map(abs,a))<2**53,'Original row outside exact integer domain')
        names.append(r['id'])
    require(names==sorted(set(names)),'All row identities must be unique and sorted')
    if n>=360:
        counts=dict(zip(('initial_sponsor_equity','annual_new_lp','annual_debt_close','resource',
            'region_exposure','sector_exposure','exclusivity','prerequisite'),(1,60,60,360,120,160,n//6,n//3)))
        require(Counter(r['family'] for r in rows)==Counter(counts) and len(rows)==sum(counts.values()),'Complete original business family census required')
    return model


def plan_values(model,plan):
    require(type(plan) is dict and set(plan)==set(model['project_ids']) and all(type(x) is int and x in (0,1) for x in plan.values()),'Complete strict integer binary plan required')
    return [plan[p] for p in model['project_ids']]


def check_plan(model,plan,exclude_plan=None):
    validate_model(model);x=plan_values(model,plan)
    if exclude_plan is not None: plan_values(model,exclude_plan)
    rows=[{'id':r['id'],'lhs':sum(a*b for a,b in zip(r['coefficients'],x)),
        'limit':r['limit']} for r in model['rows']]
    for r in rows:r.update(slack=r['limit']-r['lhs'],passed=r['lhs']<=r['limit'])
    return {'feasible':all(r['passed'] for r in rows) and plan!=exclude_plan,
        'all_integer_rows_checked':len(rows),'rows':rows,'objective_pence':sum(a*b for a,b in zip(model['objective_pence'],x)),
        'selected_project_count':sum(x),'excluded_complete_plan_not_returned':plan!=exclude_plan}


def compare_models(a,b):
    validate_model(a);validate_model(b)
    require({k:v for k,v in a.items() if k!='universe_sha256'}=={k:v for k,v in b.items() if k!='universe_sha256'},'Independent A/B raw matrices disagree')
    return {'passed':True,'complete_rows':len(a['rows']),'projects':len(a['project_ids']),
        'model_A_sha256':sha(a),'model_B_sha256':sha(b),'only_universe_identity_may_differ':True}


def representation(model,scaling='none'):
    validate_model(model);require(scaling in ('none','integer_gcd'),'Unknown algebraic representation')
    def divisor(values):
        d=0
        for v in values:d=math.gcd(d,abs(v))
        return max(1,d) if scaling=='integer_gcd' else 1
    objective_scale=divisor(model['objective_pence'])
    rows=[]
    for r in model['rows']:
        d=divisor(r['coefficients']+[r['limit']])
        rows.append({'id':r['id'],'coefficients':[x//d for x in r['coefficients']],
            'limit':r['limit']//d,'positive_integer_divisor':d})
    return {'kind':'exact_positive_integer_divisor_representation','version':1,'scaling':scaling,
        'objective_coefficients':[x//objective_scale for x in model['objective_pence']],
        'objective_positive_integer_divisor':objective_scale,'rows':rows,'omitted_original_rows':0}


def strict_evidence(model,result,exclude_plan=None,known_feasible_plans=None):
    """Independently recompute native-candidate consistency; never admit gold."""
    validate_model(model);known_feasible_plans={} if known_feasible_plans is None else known_feasible_plans
    require(type(known_feasible_plans) is dict,'Named known feasible plans must be a dictionary')
    failures=[];exact=None;raw=result.get('native',{});plan=result.get('plan')
    if result.get('exclude_plan')!=exclude_plan:failures.append('complete_exclusion_binding_changed')
    if plan is not None:
        exact=check_plan(model,plan,exclude_plan)
        if not exact['feasible']:failures.append('original_integer_feasibility_or_full_exclusion')
        if result.get('objective_pence')!=exact['objective_pence'] or type(result.get('objective_pence')) is not int:failures.append('raw_objective')
    if raw.get('status')!=2 or type(raw.get('status')) is not int:failures.append('native_not_OPTIMAL')
    if type(raw.get('sol_count')) is not int or raw.get('sol_count',0)<1:failures.append('no_native_solution')
    x=raw.get('X');n=len(model['project_ids'])
    if not (type(x) is list and len(x)==n and all(type(v) in (int,float) and v in (0,1) for v in x)):
        failures.append('native_X_not_strict_binary')
    elif plan is None or [plan[p] for p in model['project_ids']]!=x:failures.append('native_X_plan_disagreement')
    rep=representation(model,result.get('scaling','none'));factor=rep['objective_positive_integer_divisor']
    if result.get('solver_representation')!=rep:failures.append('representation_changed')
    for key in ('ObjVal','ObjBound','ObjBoundC'):
        v=raw.get(key)
        if not(type(v) in (int,float) and math.isfinite(v) and exact is not None and Fraction(v)*factor==exact['objective_pence']):failures.append('native_'+key+'_not_exact_raw_objective')
    if type(raw.get('MIPGap')) not in (int,float) or raw.get('MIPGap')!=0:failures.append('native_gap_not_zero')
    if type(result.get('time_limit_seconds')) is not int or not 1<=result.get('time_limit_seconds',0)<=3600 or type(result.get('threads')) is not int or result.get('threads')!=16:failures.append('declared_limits_changed')
    expected={**PARAMETERS,'TimeLimit':float(result.get('time_limit_seconds',0))}
    if result.get('applied_parameters')!=expected:failures.append('applied_parameters_changed')
    full=result.get('full_native_parameters')
    if not (type(full) is dict and set(expected)<=set(full) and all(type(full[k]) is dict and full[k].get('value')==v for k,v in expected.items())):failures.append('full_native_parameters_missing_or_changed')
    if raw.get('NumVars')!=n or type(raw.get('NumVars')) is not int or raw.get('NumConstrs')!=len(model['rows'])+(exclude_plan is not None) or type(raw.get('NumConstrs')) is not int:failures.append('native_geometry_changed')
    if result.get('reference_admission') is not False or result.get('independent_CP_exact_proof_pending') is not True:failures.append('reference_claim_boundary_changed')
    if result.get('solver_version')!=VERSION:failures.append('native_version_changed')
    if type(raw.get('C')) is not list or not all(type(v) in (int,float) and math.isfinite(v) for v in raw['C']) or raw['C']!=rep['objective_coefficients']:failures.append('native_C_changed')
    for name,p in known_feasible_plans.items():
        require(type(name) is str and name,'Known plan name required');proof=check_plan(model,p)
        require(proof['feasible'],'Declared counterexample is not feasible')
        if p!=exclude_plan and exact is not None and proof['objective_pence']>exact['objective_pence']:
            failures.append('known_feasible_counterexample:'+name)
    return {'passed':not failures,'checked_optimal':not failures,'failures':failures,
        'exact_integer_check':exact,'native_status_alone_is_not_reference_proof':True,
        'reference_admission':False,'independent_CP_exact_proof_pending':True}



def check_best_runner(model,best,runner,known_feasible_plans=None):
    """A positive penny gap is necessary but never opens reference admission."""
    first=strict_evidence(model,best,None,known_feasible_plans)
    require(first['passed'] and best.get('checked_optimal') is True,'Best candidate is not internally exact')
    require(runner.get('exclude_plan')==best['plan'],'Runner must exclude the complete exact winner')
    second=strict_evidence(model,runner,best['plan'],known_feasible_plans)
    require(second['passed'] and runner.get('checked_optimal') is True,'Runner candidate is not internally exact')
    gap=best['objective_pence']-runner['objective_pence']
    require(gap>=1,'Unique-best positive integer penny gap required')
    return {'native_best_runner_consistent':True,'winner_plan':best['plan'],
        'winner_objective_pence':best['objective_pence'],'runner_objective_pence':runner['objective_pence'],
        'gap_pence':gap,'reference_admission':False,'independent_CP_exact_proof_pending':True,
        'source_quality_difficulty_inherited':False}



def _parameter_inventory_value(value):
    """Tag only nonfinite inventory scalars; requested finite values stay numeric."""
    if type(value) is float and not math.isfinite(value):
        classification=('nan' if math.isnan(value) else 'positive_infinity' if value>0 else 'negative_infinity')
        return {'kind':'nonfinite_native_parameter_float','classification':classification,
            'float_hex':value.hex(),'ieee754_binary64_hex':struct.pack('>d',value).hex()}
    return value


def _parameters(model,gp):
    values={}
    for name in dir(gp.GRB.Param):
        if name.startswith('_'):continue
        key=getattr(gp.GRB.Param,name)
        if not isinstance(key,str):continue
        info=model.getParamInfo(key)
        values[key]={'name':info[0],'type':getattr(info[1],'__name__',str(info[1])),
            'value':_parameter_inventory_value(info[2]),'minimum':_parameter_inventory_value(info[3]),
            'maximum':_parameter_inventory_value(info[4]),'default':_parameter_inventory_value(info[5])}
    require(set(PARAMETERS)|{'TimeLimit'}<=set(values),'Full native parameter inventory is incomplete')
    return values


def solve_gurobi(model,*,time_limit_seconds,threads=16,exclude_plan=None,warm_start=None,
                 known_feasible_plans=None,scaling='none',log_path=None,model_path=None):
    """One optimize call. Only an explicit container runner may call this API."""
    validate_model(model);require(type(time_limit_seconds) is int and 1<=time_limit_seconds<=3600 and type(threads) is int and threads==16,'Frozen producer limits required')
    if exclude_plan is not None:plan_values(model,exclude_plan)
    known_feasible_plans={} if known_feasible_plans is None else known_feasible_plans
    require(type(known_feasible_plans) is dict,'Named known feasible plans must be a dictionary')
    for p in known_feasible_plans.values():require(check_plan(model,p)['feasible'],'Invalid known feasible plan')
    if warm_start is not None:require(check_plan(model,warm_start,exclude_plan)['feasible'],'Invalid warm start')
    require(log_path is not None and model_path is not None,'Native artifacts must be preserved')
    import gurobipy as gp  # Deliberately lazy; never imported by host preparation/tests.
    version='.'.join(map(str,gp.gurobi.version()));require(version==VERSION,'Pinned Gurobi version changed')
    env=gp.Env(empty=True);native=None;start=time.monotonic()
    result={'backend':'gurobi','solver_version':version,'model_sha256':sha(model),
        'specification_sha256':model['specification_sha256'],'universe_sha256':model['universe_sha256'],
        'exclude_plan':exclude_plan,'warm_start':warm_start,'known_feasible_plans':known_feasible_plans,
        'threads':threads,'time_limit_seconds':time_limit_seconds,'gap_parameters':{'relative':0,'absolute':0},
        'checked_optimal':False,'plan':None,'objective_pence':None,'scaling':scaling,
        'reference_admission':False,'independent_CP_exact_proof_pending':True}
    try:
        env.setParam('LogFile',str(log_path));env.start()
        native=gp.Model('private_integer_research',env=env)
        requested={**PARAMETERS,'TimeLimit':float(time_limit_seconds)}
        for key,value in requested.items():native.setParam(key,value)
        result['applied_parameters']={key:native.getParamInfo(key)[2] for key in requested}
        rep=representation(model,scaling);result['solver_representation']=rep
        x=[native.addVar(vtype=gp.GRB.BINARY,name=pid) for pid in model['project_ids']]
        native.update();native.setObjective(gp.LinExpr(rep['objective_coefficients'],x),gp.GRB.MAXIMIZE)
        for i,r in enumerate(rep['rows']):native.addConstr(gp.LinExpr(r['coefficients'],x)<=r['limit'],name=f'r{i:04d}')
        if exclude_plan is not None:
            ex=plan_values(model,exclude_plan)
            native.addConstr(gp.LinExpr([1 if v else -1 for v in ex],x)<=sum(ex)-1,name='complete_winner_no_good')
        if warm_start is not None:
            for v,flag in zip(x,plan_values(model,warm_start)):v.Start=flag
        native.update();native.write(str(model_path));native.write(str(model_path)+'.parameters.prm')
        result['full_native_parameters']=_parameters(native,gp)
        native.optimize()  # Exactly one native search, with no retry.
        attrs={'status':int(native.Status),'sol_count':int(native.SolCount),'NumVars':int(native.NumVars),
            'NumConstrs':int(native.NumConstrs),'Runtime':float(native.Runtime),'NodeCount':float(native.NodeCount),
            'C':[float(v.Obj) for v in x]}
        if native.SolCount:
            attrs.update(X=[float(v.X) for v in x],ObjVal=float(native.ObjVal),
                ObjBound=float(native.ObjBound),ObjBoundC=float(native.ObjBoundC),MIPGap=float(native.MIPGap))
            if all(v in (0,1) for v in attrs['X']):
                result['plan']={p:int(v) for p,v in zip(model['project_ids'],attrs['X'])}
                result['objective_pence']=check_plan(model,result['plan'])['objective_pence']
        result['native']=attrs;result['status']='OPTIMAL' if attrs['status']==2 else 'NOT_PROVEN_OPTIMAL'
        result['completed']=True;result['strict_check']=strict_evidence(model,result,exclude_plan,known_feasible_plans)
        result['checked_optimal']=result['strict_check']['passed']
    finally:
        result['elapsed_seconds']=time.monotonic()-start
        if native is not None:native.dispose()
        env.dispose()
    return result
