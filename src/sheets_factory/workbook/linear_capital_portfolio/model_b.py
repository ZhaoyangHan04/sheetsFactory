"""Independent capacity-first integer compiler and lazy CP-SAT adapter.

Only this family's Decimal forward is consumed. No A compiler, A financial
function, optimization output, LP or MPS is read. Solver-reported optimality is
programmatic evidence, not an independently checked formal global certificate.
"""
from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
import hashlib
from importlib.metadata import version as installed_version
import math
from pathlib import Path
import threading
import time

from . import ledger
from .spec import (ANNUAL_FIELDS, EXACT_LIMIT, PROJECT_IDS, SCENARIO_IDS,
    canonical_sha256, load_spec, require, validate_plan)

MODEL_KIND = 'linear_capital_portfolio_direct_binary_integer_model'
SOLVER_VERSION = '9.14.6206'


def _integer(value, label):
    require(type(value) is int and abs(value) < EXACT_LIMIT, 'An exact bounded integer is required: '+label)
    return value


def build_model(specification, universe=None):
    """Build all business rows, then fill each project column independently.

    A supplied universe is checked against this implementation's own complete
    forward, not admitted on the strength of a financial-implementation flag.
    This function performs finance but never imports or executes a solver.
    """
    public = load_spec(specification)
    actual = ledger.simulate_universe(public)
    if universe is not None:
        require(isinstance(universe, dict) and canonical_sha256(universe) == canonical_sha256(actual),
                'The supplied B universe differs from the independent Decimal forward')
    require(actual['specification_sha256'] == canonical_sha256(public)
        and actual['financial_implementation'] == 'Decimal'
        and actual['project_order'] == public['project_ids'] and actual['scenario_ids'] == public['scenario_ids']
        and actual['years'] == public['years'] and actual['all_standalone_feasible'] is True,
        'Every candidate in every scenario must be independently feasible; none may be dropped')
    ids, years, scenarios = public['project_ids'],public['years'],public['scenario_ids']
    limits=public['shared_limits'];rows={}
    def capacity(name, family, sid, year, limit):
        require(name not in rows, 'A capacity identity is duplicated')
        rows[name]={'id':name,'family':family,'scenario_id':sid,'year':year,
                    'coefficients':[0]*len(ids),'limit':_integer(limit,name)}
    capacity('initial_sponsor_equity','initial_sponsor_equity',None,None,limits['initial_sponsor_equity_pence'])
    for sid in scenarios:
        for year in years:
            capacity(f'annual_new_lp:{sid}:{year}','annual_new_lp',sid,year,limits['annual_new_lp_pence'][sid][str(year)])
            capacity(f'annual_debt_close:{sid}:{year}','annual_debt_close',sid,year,limits['annual_debt_close_pence'][sid][str(year)])
            for resource in public['resource_ids']:
                capacity(f'resource:{resource}:{sid}:{year}','resource',sid,year,
                         limits['resource_capacity_units'][resource][sid][str(year)])
    for region in public['region_ids']:
        for year in years:
            capacity(f'region_exposure:{region}:{year}','region_exposure',None,year,
                     limits['region_exposure_pence'][region][str(year)])
    for sector in public['sector_ids']:
        for year in years:
            capacity(f'sector_exposure:{sector}:{year}','sector_exposure',None,year,
                     limits['sector_exposure_pence'][sector][str(year)])
    for group in public['exclusivity_groups']:
        capacity('exclusivity:'+group['id'],'exclusivity',None,None,1)
    for edge in public['prerequisites']:
        capacity('prerequisite:'+edge['id'],'prerequisite',None,None,0)
    objective=[]
    for column, project in enumerate(public['projects']):
        pid=project['id'];paths=actual['projects'][pid]['scenarios'];base=paths['S01']
        require(set(paths)==set(scenarios) and all(path['feasible'] is True for path in paths.values()),
                'The complete candidate scenario set is required')
        objective.append(_integer(base['npv_pence'], 'posted S01 NPV'))
        rows['initial_sponsor_equity']['coefficients'][column]=_integer(base['t0']['lp_call'], 't0 LP')
        for sid in scenarios:
            path=paths[sid]
            require(path['t0']==base['t0'] and len(path['annual'])==len(years), 'Opening financing or annual scope differs')
            for index, year in enumerate(years):
                row=path['annual'][index]
                require(row['year']==year and set(ANNUAL_FIELDS)<=set(row)
                    and all(type(row[field]) is int for field in ANNUAL_FIELDS), 'An annual financial field is missing or untyped')
                rows[f'annual_new_lp:{sid}:{year}']['coefficients'][column]=_integer(row['lp_call'],'annual gross LP')
                rows[f'annual_debt_close:{sid}:{year}']['coefficients'][column]=_integer(row['debt_close'],'year-end principal')
                require(row['asset_nbv_close']==base['annual'][index]['asset_nbv_close'],
                        'Region/sector NBV must be scenario independent under the public contract')
                for resource in public['resource_ids']:
                    rows[f'resource:{resource}:{sid}:{year}']['coefficients'][column]=_integer(
                        project['resource_usage_units'][resource][sid][str(year)],'dated physical resource')
        for index,year in enumerate(years):
            exposure=_integer(base['annual'][index]['asset_nbv_close'],'asset NBV exposure')
            rows[f'region_exposure:{project["region"]}:{year}']['coefficients'][column]=exposure
            rows[f'sector_exposure:{project["sector"]}:{year}']['coefficients'][column]=exposure
        for group in public['exclusivity_groups']:
            if pid in group['project_ids']:rows['exclusivity:'+group['id']]['coefficients'][column]=1
        for edge in public['prerequisites']:
            if pid==edge['dependent']:rows['prerequisite:'+edge['id']]['coefficients'][column]=1
            elif pid==edge['prerequisite']:rows['prerequisite:'+edge['id']]['coefficients'][column]=-1
    expected=1+2*len(scenarios)*len(years)+len(public['resource_ids'])*len(scenarios)*len(years)
    expected+=(len(public['region_ids'])+len(public['sector_ids']))*len(years)
    expected+=len(public['exclusivity_groups'])+len(public['prerequisites'])
    require(len(rows)==expected and (public['dimension_mode']!='production' or expected==881),
            'The complete portfolio constraint set differs')
    model={'kind':MODEL_KIND,'version':1,'project_ids':list(ids),'objective_pence':objective,
        'rows':[rows[name] for name in sorted(rows)],'specification_sha256':canonical_sha256(public),
        'universe_sha256':canonical_sha256(actual)}
    return validate_model(model)


def validate_model(model):
    """Check canonical identity/order and every exact integer arithmetic bound."""
    require(isinstance(model,dict) and set(model)=={'kind','version','project_ids','objective_pence','rows',
        'specification_sha256','universe_sha256'}, 'Unknown canonical integer model fields')
    require(model['kind']==MODEL_KIND and type(model['version']) is int and model['version']==1,
            'Unknown integer portfolio model')
    ids=model['project_ids']
    require(isinstance(ids,list) and 1<=len(ids)<=240 and ids==list(PROJECT_IDS[:len(ids)]),
            'A complete ordered project universe is required')
    require(isinstance(model['objective_pence'],list) and len(model['objective_pence'])==len(ids),
            'Every project objective coefficient is required')
    for value in model['objective_pence']:_integer(value,'objective')
    require(sum(abs(v) for v in model['objective_pence'])<EXACT_LIMIT,
            'The complete objective exceeds the exact aggregate envelope')
    for field in ('specification_sha256','universe_sha256'):
        value=model[field]
        require(type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value),
                'The public/universe identity must be an exact SHA256')
    require(isinstance(model['rows'],list) and bool(model['rows']), 'The complete constraint rows are required')
    row_ids=[]
    for row in model['rows']:
        require(isinstance(row,dict) and set(row)=={'id','family','scenario_id','year','coefficients','limit'},
                'An exact integer constraint row is required')
        require(type(row['id']) is str and row['id'] and type(row['family']) is str
            and row['family']==row['id'].split(':',1)[0], 'The business row identity/family differs')
        require(row['scenario_id'] is None or row['scenario_id'] in SCENARIO_IDS, 'Unknown scenario identity')
        require(row['year'] is None or type(row['year']) is int and 1<=row['year']<=20, 'Unknown FY number')
        require(isinstance(row['coefficients'],list) and len(row['coefficients'])==len(ids),
                'A constraint omits a project column')
        for value in row['coefficients']:_integer(value,'constraint coefficient')
        _integer(row['limit'],'constraint limit')
        require(sum(abs(value) for value in row['coefficients'])<EXACT_LIMIT,
                'A constraint LHS exceeds the exact aggregate envelope')
        row_ids.append(row['id'])
    require(row_ids==sorted(row_ids) and len(set(row_ids))==len(row_ids),
            'Canonical row identities must be unique and lexicographically ordered')
    return deepcopy(model)


def check_plan(model, plan, *, exclude_plan=None):
    """Recompute each exact integer LHS/objective; no solver arithmetic is used."""
    value=validate_model(model);plan=validate_plan(value,plan)
    excluded=validate_plan(value,exclude_plan) if exclude_plan is not None else None
    choice=[plan[pid] for pid in value['project_ids']]
    rows=[]
    for row in value['rows']:
        lhs=sum(a*b for a,b in zip(row['coefficients'],choice))
        rows.append({'id':row['id'],'lhs':lhs,'limit':row['limit'],'slack':row['limit']-lhs,'passed':lhs<=row['limit']})
    distinct=excluded is None or any(plan[pid]!=excluded[pid] for pid in value['project_ids'])
    return {'plan':plan,'objective_pence':sum(a*b for a,b in zip(value['objective_pence'],choice)),
        'rows':rows,'all_integer_rows_passed':all(row['passed'] for row in rows),
        'excluded_plan_distinct':distinct,'passed':all(row['passed'] for row in rows) and distinct}


def _reference(path):
    path=Path(path).resolve()
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}


def _fresh_path(value):
    if value is None:return None
    path=Path(value).absolute()
    require(path==path.resolve() and not path.exists(), 'Preserve existing solver artifacts; use a fresh real path')
    path.parent.mkdir(parents=True,exist_ok=True)
    return path


def _solver():
    require(installed_version('ortools')==SOLVER_VERSION, 'The prospective CP-SAT version must be pinned exactly')
    from ortools.sat.python import cp_model
    return cp_model


def solve_cp_sat(model, *, time_limit_seconds, threads=2, exclude_plan=None, log_path=None, model_path=None):
    """One solve only; the caller separately drives any no-good runner solve.

    CP-SAT status meanings follow the official integer solver API:
    https://developers.google.com/optimization/cp/cp_solver
    FEASIBLE and UNKNOWN are never promoted to optimality by an incumbent.
    """
    started=time.monotonic();value=validate_model(model)
    require(type(time_limit_seconds) in (int,float) and math.isfinite(time_limit_seconds) and time_limit_seconds>0,
            'A finite positive prospective solver time limit is required')
    require(type(threads) is int and 1<=threads<=2, 'The reference uses at most the declared two CPU workers')
    excluded=validate_plan(value,exclude_plan) if exclude_plan is not None else None
    log_file,model_file=_fresh_path(log_path),_fresh_path(model_path)
    require(log_file is None or model_file is None or log_file!=model_file, 'Solver log and model must be separate artifacts')
    cp_model=_solver();native=cp_model.CpModel()
    variables=[native.new_bool_var(pid) for pid in value['project_ids']]
    for row in value['rows']:
        native.add(sum(c*v for c,v in zip(row['coefficients'],variables) if c)<=row['limit']).with_name(row['id'])
    native.maximize(sum(c*v for c,v in zip(value['objective_pence'],variables) if c))
    if excluded is not None:
        native.add(sum((1-v) if excluded[pid] else v for pid,v in zip(value['project_ids'],variables))>=1).with_name('complete_winner_Hamming_no_good')
    solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=float(time_limit_seconds)
    solver.parameters.num_search_workers=threads
    solver.parameters.relative_gap_limit=0.0;solver.parameters.absolute_gap_limit=0.0
    solver.parameters.log_to_stdout=False;solver.parameters.log_search_progress=log_file is not None
    parameters_file=None
    if model_file is not None:
        parameters_file=_fresh_path(str(model_file)+'.parameters.pbtxt')
        with model_file.open('x',encoding='utf-8') as stream:stream.write(str(native.proto))
        with parameters_file.open('x',encoding='utf-8') as stream:stream.write(str(solver.parameters))
    with ExitStack() as stack:
        if log_file is not None:
            stream=stack.enter_context(log_file.open('x',encoding='utf-8'))
            lock=threading.Lock()
            def log(message):
                with lock:stream.write(message);stream.flush()
            solver.log_callback=log
        raw=solver.solve(native)
    status=solver.status_name(raw)
    result={'backend':'ortools_cp_sat','solver_version':SOLVER_VERSION,'status':status,'raw_status':int(raw),
        'checked_optimal':False,'plan':None,'objective_pence':None,'exact_plan_check':None,
        'reported_objective':None,'reported_best_bound':None,'elapsed_seconds':time.monotonic()-started,
        'solver_wall_seconds':solver.wall_time,'time_limit_seconds':time_limit_seconds,'threads':threads,
        'exclude_plan':excluded,'model_sha256':canonical_sha256(value),'specification_sha256':value['specification_sha256'],
        'universe_sha256':value['universe_sha256'],'gap_parameters':{'relative':0,'absolute':0},
        'log_reference':_reference(log_file) if log_file is not None else None,
        'model_reference':_reference(model_file) if model_file is not None else None,
        'model_artifact_format':'CpModelProto text' if model_file is not None else None,
        'parameters_reference':_reference(parameters_file) if parameters_file is not None else None,
        'branches':solver.num_branches,'conflicts':solver.num_conflicts,'response_statistics':solver.response_stats(),
        'formal_global_certificate':False,'second_solve_automatically_started':False,
        'source_quality_or_difficulty_certified':False}
    if raw in (cp_model.OPTIMAL,cp_model.FEASIBLE):
        plan={pid:int(solver.value(variable)) for pid,variable in zip(value['project_ids'],variables)}
        exact=check_plan(value,plan,exclude_plan=excluded)
        require(exact['passed'], 'The reported solver plan fails an exact public integer row or no-good constraint')
        require(solver.objective_value==exact['objective_pence'], 'The native objective differs from the exact integer objective')
        result.update(plan=plan,objective_pence=exact['objective_pence'],exact_plan_check=exact,
            reported_objective=solver.objective_value,reported_best_bound=solver.best_objective_bound,
            checked_optimal=raw==cp_model.OPTIMAL)
    elif raw not in (cp_model.INFEASIBLE,cp_model.MODEL_INVALID,cp_model.UNKNOWN):
        raise ValueError('Unknown CP-SAT terminal status')
    result['elapsed_seconds']=time.monotonic()-started
    return result
