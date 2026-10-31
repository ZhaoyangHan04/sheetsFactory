"""Direct project-binary model from independent financial forward A.

This module neither reads B nor consumes B's matrix. Building a model performs
only the provided financial forward; solving requires an explicit separate call.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import time

from .spec import EXACT_LIMIT, load_spec

KIND = 'linear_capital_portfolio_direct_binary_integer_model'
FAMILIES = ('initial_sponsor_equity','annual_new_lp','annual_debt_close','resource',
            'region_exposure','sector_exposure','exclusivity','prerequisite')
PRODUCTION_COUNTS = dict(zip(FAMILIES,(1,60,60,360,120,160,40,80)))


def _require(condition, message):
    if not condition: raise ValueError(message)


def _sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
        ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def _integer(value):
    _require(type(value) is int and abs(value) < EXACT_LIMIT,
        'An exact model integer is outside the public arithmetic domain')
    return value


def _vector(values, count):
    _require(isinstance(values,list) and len(values)==count,'A complete project coefficient vector is required')
    magnitude=0
    for value in values:
        magnitude += abs(_integer(value))
        _require(magnitude < EXACT_LIMIT,'An aggregate model LHS or objective can exceed the exact integer domain')


def validate_model(model):
    _require(isinstance(model,dict) and set(model)=={'kind','version','project_ids','objective_pence',
        'rows','specification_sha256','universe_sha256'},'The complete canonical model schema is required')
    _require(model['kind']==KIND and type(model['version']) is int and model['version']==1,'Unknown model identity')
    ids=model['project_ids']
    _require(isinstance(ids,list) and len(ids) in (1,2,3,4,240)
        and ids==[f'P{i:03d}' for i in range(1,len(ids)+1)],'Canonical complete project identities are required')
    for field in ('specification_sha256','universe_sha256'):
        digest=model[field]
        _require(type(digest) is str and len(digest)==64 and all(c in '0123456789abcdef' for c in digest),
            'An exact public input and financial universe SHA is required')
    _vector(model['objective_pence'],len(ids))
    rows=model['rows']
    _require(isinstance(rows,list) and rows,'All business capacity rows are required')
    seen=set()
    for row in rows:
        _require(isinstance(row,dict) and set(row)=={'id','family','scenario_id','year','coefficients','limit'},
            'A complete integer LE row is required')
        _require(type(row['id']) is str and row['id'] and row['id'] not in seen
            and row['family'] in FAMILIES,'Business row identities must be unique')
        seen.add(row['id'])
        _require(row['scenario_id'] is None or row['scenario_id'] in ('S01','S02','S03'),'An unknown scenario is not permitted')
        _require(row['year'] is None or type(row['year']) is int and 1 <= row['year'] <= 20,'An invalid FY is not permitted')
        _vector(row['coefficients'],len(ids));_integer(row['limit'])
    _require([r['id'] for r in rows]==sorted(seen),'Canonical rows must be sorted by unique identity')
    if len(ids)==240:
        _require(Counter(r['family'] for r in rows)==PRODUCTION_COUNTS and len(rows)==881,
            'The complete production model requires all 881 business constraints')
    return model


def build_model(specification, universe=None):
    """Build every integer row from a freshly checked A financial universe.

    A supplied serialized universe is compared with a fresh own forward. It is
    never trusted as a caller-provided coefficient or optimal-plan cache.
    """
    from . import candidate_a
    public=load_spec(specification)
    actual=candidate_a.simulate_universe(public)
    if universe is not None:
        _require(universe==actual,'A supplied financial universe differs from fresh independent A')
    _require(actual['specification_sha256']==_sha(public)
        and actual['project_order']==public['project_ids']
        and actual['all_standalone_feasible'] is True,'Every provided candidate in every scenario must be feasible')
    ids=public['project_ids'];scenarios=public['scenario_ids'];years=public['years']
    projects=public['projects'];limits=public['shared_limits'];first=scenarios[0]
    def result(pid,sid): return actual['projects'][pid]['scenarios'][sid]
    for pid in ids:
        baseline=[r['asset_nbv_close'] for r in result(pid,first)['annual']]
        _require(all([r['asset_nbv_close'] for r in result(pid,sid)['annual']]==baseline for sid in scenarios),
            'Regional and sector NBV must agree across every scenario')
        _require(all(result(pid,sid)['feasible'] is True and type(result(pid,sid)['npv_pence']) is int
            for sid in scenarios),'An infeasible or incomplete standalone candidate cannot be dropped')
    rows=[]
    def add(identity,family,values,limit,scenario=None,year=None):
        row={'id':identity,'family':family,'scenario_id':scenario,'year':year,
            'coefficients':list(values),'limit':limit}
        _vector(row['coefficients'],len(ids));_integer(limit);rows.append(row)
    add('initial_sponsor_equity','initial_sponsor_equity',
        (result(pid,first)['t0']['lp_call'] for pid in ids),limits['initial_sponsor_equity_pence'])
    for sid in scenarios:
        for index,year in enumerate(years):
            add(f'annual_new_lp:{sid}:{year}','annual_new_lp',
                (result(pid,sid)['annual'][index]['lp_call'] for pid in ids),limits['annual_new_lp_pence'][sid][str(year)],sid,year)
            add(f'annual_debt_close:{sid}:{year}','annual_debt_close',
                (result(pid,sid)['annual'][index]['debt_close'] for pid in ids),limits['annual_debt_close_pence'][sid][str(year)],sid,year)
            for resource in public['resource_ids']:
                add(f'resource:{resource}:{sid}:{year}','resource',
                    (p['resource_usage_units'][resource][sid][str(year)] for p in projects),
                    limits['resource_capacity_units'][resource][sid][str(year)],sid,year)
    for index,year in enumerate(years):
        for family,labels,attribute,limit_field in (
            ('region_exposure',public['region_ids'],'region','region_exposure_pence'),
            ('sector_exposure',public['sector_ids'],'sector','sector_exposure_pence')):
            for label in labels:
                add(f'{family}:{label}:{year}',family,
                    (result(p['id'],first)['annual'][index]['asset_nbv_close'] if p[attribute]==label else 0 for p in projects),
                    limits[limit_field][label][str(year)],None,year)
    for group in public['exclusivity_groups']:
        add('exclusivity:'+group['id'],'exclusivity',(int(pid in group['project_ids']) for pid in ids),1)
    for edge in public['prerequisites']:
        add('prerequisite:'+edge['id'],'prerequisite',
            (int(pid==edge['dependent'])-int(pid==edge['prerequisite']) for pid in ids),0)
    model={'kind':KIND,'version':1,'project_ids':list(ids),
        'objective_pence':[result(pid,first)['npv_pence'] for pid in ids],
        'rows':sorted(rows,key=lambda row:row['id']),'specification_sha256':_sha(public),'universe_sha256':_sha(actual)}
    return validate_model(model)


def _plan(model,plan):
    _require(isinstance(plan,dict) and set(plan)==set(model['project_ids'])
        and all(type(value) is int and value in (0,1) for value in plan.values()),'A complete exact integer binary plan is required')
    return {pid:plan[pid] for pid in model['project_ids']}


def _nogood(model,excluded):
    excluded=_plan(model,excluded)
    coefficients=[1 if excluded[pid] else -1 for pid in model['project_ids']]
    return coefficients,sum(excluded.values())-1


def check_plan(model,plan,*,exclude_plan=None):
    """Recompute the objective and every LE row with Python integers."""
    validate_model(model);plan=_plan(model,plan)
    values=list(plan.values());checks=[]
    def dot(vector):
        total=0
        for coefficient,value in zip(vector,values):total=_integer(total+coefficient*value)
        return total
    for row in model['rows']:
        lhs=dot(row['coefficients'])
        checks.append({'id':row['id'],'lhs':lhs,'limit':row['limit'],
            'slack':_integer(row['limit']-lhs),'passed':lhs <= row['limit']})
    if exclude_plan is not None:
        vector,limit=_nogood(model,exclude_plan);lhs=dot(vector)
        checks.append({'id':'__full_plan_hamming_exclusion__','lhs':lhs,'limit':limit,
            'slack':_integer(limit-lhs),'passed':lhs <= limit})
    return {'plan':plan,'objective_pence':dot(model['objective_pence']),
        'complete':True,'constraints_checked':len(checks),'rows':checks,
        'feasible':all(row['passed'] for row in checks),'integer_arithmetic':True}


def _fresh_artifact(path):
    if path is None:return None
    path=Path(path).absolute()
    _require(path==path.resolve() and not path.exists(),'Use a fresh nonsymlink solver artifact path')
    path.parent.mkdir(parents=True,exist_ok=True)
    return path


def _file(path):
    if path is None or not path.is_file():return None
    data=path.read_bytes()
    return {'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}


def solve_scip(model,*,time_limit_seconds,threads=2,exclude_plan=None,log_path=None,model_path=None):
    """One explicit SCIP optimization; no retry, tuning or production selection.

    The native optimal status is retained. ``checked_optimal`` additionally
    requires an exact binary primal, integer checks of every row (including the
    full-plan exclusion), and agreement with the native objective and bounds.
    This is native MIP evidence plus exact primal audit, not a rational dual proof.
    """
    validate_model(model)
    _require(type(time_limit_seconds) in (int,float) and math.isfinite(time_limit_seconds)
        and time_limit_seconds > 0,'An explicit positive finite solver time limit is required')
    _require(type(threads) is int and 1 <= threads <= 2,'One or two solver threads are required')
    excluded=None if exclude_plan is None else _plan(model,exclude_plan)
    log_path,model_path=_fresh_artifact(log_path),_fresh_artifact(model_path)
    _require(log_path is None or model_path is None or log_path!=model_path,'Solver log and model artifacts must be distinct')
    import pyscipopt
    native=pyscipopt.Model('independent_A_direct_project_binary')
    native.hideOutput(True)
    default_tolerance=native.getParam('numerics/feastol')
    settings={'limits/time':float(time_limit_seconds),'limits/gap':0.0,'limits/absgap':0.0,
        'parallel/maxnthreads':threads,'lp/threads':threads}
    for name,value in settings.items():native.setParam(name,value)
    if log_path is not None:native.setLogfile(str(log_path))
    variables=[native.addVar(name=pid,vtype='B') for pid in model['project_ids']]
    native.setObjective(pyscipopt.quicksum(c*v for c,v in zip(model['objective_pence'],variables)),'maximize')
    for index,row in enumerate(model['rows']):
        native.addCons(pyscipopt.quicksum(c*v for c,v in zip(row['coefficients'],variables)) <= row['limit'],name='business_'+str(index))
    if excluded is not None:
        vector,limit=_nogood(model,excluded)
        native.addCons(pyscipopt.quicksum(c*v for c,v in zip(vector,variables)) <= limit,name='full_plan_hamming_exclusion')
    if model_path is not None:native.writeProblem(str(model_path),trans=False)
    started=time.monotonic()
    result={'kind':'independent_A_SCIP_single_attempt','version':1,'model_sha256':_sha(model),
        'specification_sha256':model['specification_sha256'],'universe_sha256':model['universe_sha256'],
        'solver_version':pyscipopt.__version__,'parameters':settings,
        'default_feasibility_tolerance':default_tolerance,'feasibility_tolerance_changed':False,
        'exclude_plan':excluded,'optimizer_calls':1,'retry_count':0,'checked_optimal':False,
        'completed':False,'plan':None,'objective_pence':None,'exact_integer_check':None,
        'raw_status':None,'primal_bound':None,'dual_bound':None,'gap':None,
        'proof_scope':'native_MIP_optimal_status_plus_exact_integer_primal_audit'}
    try:
        native.optimize()
        result.update(completed=True,raw_status=str(native.getStatus()),
            primal_bound=float(native.getPrimalbound()),dual_bound=float(native.getDualbound()),
            gap=float(native.getGap()),native_nodes=int(native.getNNodes()),native_seconds=float(native.getSolvingTime()))
        # At a pre-solve time limit PySCIPOpt can return an invalid Solution
        # wrapper from getBestSol(). A zero solution count means no primal.
        best=native.getBestSol() if native.getNSols() > 0 else None
        if best is not None:
            raw=[float(native.getSolVal(best,var)) for var in variables]
            result['native_solution_values']=raw
            result['native_objective']=float(native.getSolObjVal(best,original=True))
            if all(value in (0.0,1.0) for value in raw):
                plan={pid:int(value) for pid,value in zip(model['project_ids'],raw)}
                checked=check_plan(model,plan,exclude_plan=excluded)
                result.update(plan=plan,objective_pence=checked['objective_pence'],exact_integer_check=checked)
                objective=float(checked['objective_pence'])
                result['checked_optimal']=(result['raw_status']=='optimal' and checked['complete']
                    and checked['feasible'] and result['native_objective']==objective
                    and result['primal_bound']==objective and result['dual_bound']==objective and result['gap']==0.0)
            else:result['incomplete_reason']='The native primal is not exactly binary'
        if native.getParam('numerics/feastol') != default_tolerance:
            result.update(checked_optimal=False,incomplete_reason='The default feasibility tolerance changed')
    except Exception as exc:
        result.update(checked_optimal=False,completed=False,solver_error_type=type(exc).__name__,solver_error=str(exc))
        try:result['raw_status']=str(native.getStatus())
        except Exception:pass
    finally:
        result.update(elapsed_seconds=time.monotonic()-started,log_artifact=_file(log_path),model_artifact=_file(model_path))
        native.freeProb()
    return result
