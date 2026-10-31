#!/usr/bin/env python3
"""Private, single-attempt independent best/runner reference orchestration."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import traceback

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.workbook.linear_capital_portfolio import spec,finance_crosscheck,optimization_runtime as runtime

KIND='linear_capital_independent_best_runner_reference'
PREPARED='prepared_linear_capital_independent_best_runner_reference'
TIME_LIMIT=3600
BACKENDS={'A':'scip','B':'cp_sat'}
require=spec.require


def reference(path):return runtime.reference(path)
def read(value):
    value=reference(value) if isinstance(value,(str,Path)) else value
    require(reference(value['path'])==value,'A frozen artifact changed')
    return runtime._read(value['path'])
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as stream:json.dump(value,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n')
    return reference(path)
def _sha(value):return hashlib.sha256(runtime._canonical(value)).hexdigest()
def _refs(value,seen=None):
    seen={} if seen is None else seen
    if isinstance(value,dict):
        if set(value)=={'path','sha256','bytes'}:
            key=value['path']
            if key not in seen:seen[key]=reference(key)
            require(seen[key]==value,'An immutable referenced artifact changed: '+key)
        else:
            for child in value.values():_refs(child,seen)
    elif isinstance(value,list):
        for child in value:_refs(child,seen)
    return seen


def _checked_finance(value):
    terminal_ref=reference(value) if isinstance(value,(str,Path)) else value
    terminal=read(terminal_ref)
    require(terminal.get('kind')=='linear_capital_full_financial_crosscheck'
        and type(terminal.get('version')) is int and terminal['version']==1 and terminal.get('passed') is True
        and all(type(terminal.get(k)) is int and terminal[k]==0 for k in ('optimizer_calls','LO_calls','model_calls')),
        'A completed actual independent finance and matrix crosscheck is required')
    _refs(terminal['records'])
    started=read(terminal['records']['started']);preparation=read(started['preparation'])
    for record in preparation['recipe'].values():require(reference(record['path'])==record,'The finance implementation changed')
    raw=read(preparation['raw_preparation']);public=spec.load_spec(read(raw['specification']))
    require(public['dimension_mode']=='production' and raw['specification_sha256']==spec.canonical_sha256(public),
        'The complete frozen production universe is required')
    for path,digest in raw['recipe_sha256'].items():require(reference(path)['sha256']==digest,'A raw preparation recipe changed')
    a_ref,b_ref=(terminal['records'][key] for key in ('Fraction_A_universe','Decimal_B_universe'))
    a,b=read(a_ref),read(b_ref)
    comparison=finance_crosscheck.compare_universes(public,a,b)
    require(comparison['passed'] is True and comparison==read(terminal['records']['complete_financial_comparison']),
        'The full current A/B financial scope differs')
    probes=finance_crosscheck.compare_plans(public,a,b,raw['diagnostic_plans'])
    require(probes['passed'] is True and probes==read(terminal['records']['all_predeclared_plan_comparison']),
        'The complete predeclared diagnostic plan inventory differs')
    models={side:terminal['records']['model_'+side] for side in BACKENDS}
    ma,mb=read(models['A']),read(models['B'])
    for model,universe in ((ma,a),(mb,b)):
        runtime.validate_model(model)
        require(len(model['project_ids'])==240 and len(model['rows'])==881
            and model['specification_sha256']==spec.canonical_sha256(public)
            and model['universe_sha256']==_sha(universe),'The model is not bound to its complete financial universe')
    common=('kind','version','project_ids','objective_pence','rows','specification_sha256')
    require(all(ma[key]==mb[key] for key in common)
        and read(terminal['records']['complete_matrix_comparison'])['passed'] is True,
        'The independent complete integer matrices differ')
    return {'terminal':terminal_ref,'raw_preparation':preparation['raw_preparation'],'specification':raw['specification'],
        'public':public,'A':a,'B':b,'universe_A':a_ref,'universe_B':b_ref,'models':models,
        'model_values':{'A':ma,'B':mb},'finance_preparation':started['preparation']}


def _checked_preparation(record,model,backend,excluded):
    frozen=read(record)
    require(frozen.get('kind')==runtime.PREPARATION_KIND and type(frozen.get('version')) is int and frozen['version']==1
        and frozen['implementation']==reference(runtime.__file__) and frozen['model_input']==model,
        'The declared solver preparation or original matrix changed')
    request=frozen['request']
    if request.get('exclude_plan') is not None:runtime._plan(read(model)['project_ids'],request['exclude_plan'])
    require(request['backend']==backend and type(request['time_limit_seconds']) is int and request['time_limit_seconds']==TIME_LIMIT
        and type(request['threads']) is int and request['threads']==2 and request['exclude_plan']==excluded
        and type(request['relative_gap']) is int and request['relative_gap']==0
        and type(request['absolute_gap']) is int and request['absolute_gap']==0
        and request['financial_forward_permitted'] is False and request['distribution_versions']==runtime.DISTRIBUTIONS,
        'The solver, time, gap, thread or complete-plan exclusion contract changed')
    require(frozen['image_id']==runtime.IMAGE_ID and frozen['resources']=={'cpus':2,'memory_bytes':32*1024**3,'pids_limit':256}
        and frozen['network']=='none' and frozen['agent_tool_budget_changed'] is False,
        'The private solver resource contract changed')
    _refs(frozen['source_code']);_refs(frozen['vendor_inventory']);_refs(frozen['bundle_inventory'])
    require(frozen['source_code']=={name:reference(path) for name,path in runtime._source_files().items()},
        'The current native solver implementation closure changed')
    require(frozen['model_canonical_sha256']==_sha(read(model)),'The canonical solver matrix changed')
    return frozen


def _adopted_best(value,finance):
    record=reference(value) if isinstance(value,(str,Path)) else value
    declared=read(record)
    require(declared.get('kind')=='prospective_first_pair_of_linear_capital_best_jobs'
        and type(declared.get('version')) is int and declared['version']==1
        and declared['financial_crosscheck']==finance['terminal'] and declared['models']==finance['models']
        and type(declared['per_job_limit_seconds']) is int and declared['per_job_limit_seconds']==TIME_LIMIT
        and declared['agent_tool_budget_unchanged'] is True and declared['automatic_retry_or_retune'] is False,
        'The exact prospective first-best declaration changed')
    _refs(declared)
    require(set(declared['best_preparations'])==set(BACKENDS),'Both predeclared first jobs are required')
    return record,declared['best_preparations']


def _recipes():
    modules=[Path(__file__),Path(spec.__file__),Path(finance_crosscheck.__file__),Path(runtime.__file__),*runtime._source_files().values()]
    return {str(p):reference(p) for p in modules}


def validate_solver_receipt(preparation,terminal,*,model,backend,exclude_plan=None):
    """Read-only full runtime, resource, cleanup and exact-matrix validation."""
    frozen=_checked_preparation(preparation,model,backend,exclude_plan)
    value=read(terminal);_refs(value)
    require(value.get('kind')==runtime.TERMINAL_KIND and type(value.get('version')) is int and value['version']==1
        and value['preparation']==preparation and value['image_id']==runtime.IMAGE_ID
        and value.get('actual_resources_verified') is True and value.get('exit_code')==0
        and type(value['exit_code']) is int and value.get('oom_killed') is False
        and value.get('agent_tool_budget_changed') is False,'The actual native execution/resource receipt is incomplete')
    identifier=value['container_id'];require(type(identifier) is str and re.fullmatch('[0-9a-f]{64}',identifier),'A full owned container identity is required')
    folder=Path(preparation['path']).parent;bundle=Path(frozen['bundle'])
    host_before=reference(folder/'host_before.json');host_after=reference(folder/'host_after.json')
    before,after=read(host_before),read(host_after)
    runtime.validate_resources(before,identifier,bundle);runtime.validate_resources(after,identifier,bundle)
    name='/sf-private-integer-'+frozen['request']['nonce']
    require(before['Name']==after['Name']==name and before['State']['Status']=='created'
        and before['State']['Running'] is False and after['State']['Status']=='exited'
        and after['State']['Running'] is False and type(after['State']['ExitCode']) is int
        and after['State']['ExitCode']==0 and after['State']['OOMKilled'] is False,'The exact before/after container state changed')
    cleanup=read(value['cleanup'])
    require(cleanup.get('owned_container_id')==identifier and cleanup.get('removed_and_absent_with_daemon_reachable') is True
        and cleanup['returncode']==0 and cleanup['absence_inspect']['returncode']!=0
        and 'no such object' in cleanup['absence_inspect']['stderr'].lower()
        and cleanup['daemon_image_check']['returncode']==0 and cleanup['daemon_image_check']['stdout'].strip()==runtime.IMAGE_ID,
        'The exact owned container lacks cleanup/absence evidence')
    current=value['retained_job_inventory']
    require(current==value['complete_job_inventory'] and all(current.get(k)==r for k,r in frozen['bundle_inventory'].items()),
        'The original private bundle or completed output inventory changed')
    require(runtime._inventory(bundle)==current,'A completed private job file was added, removed or changed')
    solver,transport=read(value['solver_result']),read(value['runtime_result'])
    require(solver['model_sha256']==frozen['model_canonical_sha256'] and solver['specification_sha256']==read(model)['specification_sha256']
        and solver['universe_sha256']==read(model)['universe_sha256'] and solver['exclude_plan']==exclude_plan,
        'The native result matrix, source universe or full-plan exclusion changed')
    require(transport.get('completed') is True and transport.get('financial_forward_executed') is False
        and transport['backend']==backend and transport['threads']==2 and transport['gap_requested']==0
        and transport['distribution_versions']==runtime.DISTRIBUTIONS and transport['model_canonical_sha256']==frozen['model_canonical_sha256'],
        'The private matrix-only runtime contract changed')
    if backend=='scip':
        require(solver.get('parameters')=={'limits/time':float(TIME_LIMIT),'limits/gap':0.0,'limits/absgap':0.0,
            'parallel/maxnthreads':2,'lp/threads':2} and solver.get('feasibility_tolerance_changed') is False,
            'The actual SCIP gap, time, thread or default tolerance contract changed')
    else:
        require(solver.get('gap_parameters')=={'relative':0,'absolute':0} and type(solver.get('threads')) is int
            and solver['threads']==2 and type(solver.get('time_limit_seconds')) is int and solver['time_limit_seconds']==TIME_LIMIT,
            'The actual CP-SAT gap, time or thread contract changed')
        require(all(type(solver['gap_parameters'][key]) is int for key in ('relative','absolute')),
            'The CP-SAT gap parameters must be exact integer zeros')
    checked=runtime.check_result(read(model),solver,exclude_plan)
    require(checked==value['matrix_result_check'] and value['status']==checked['status'],'The native status/exact integer checks differ')
    return {'preparation':preparation,'terminal':terminal,'host_before':host_before,'host_after':host_after,
        'cleanup':value['cleanup'],'solver_result':value['solver_result'],'runtime_result':value['runtime_result'],
        'checked_optimal':checked['checked_optimal'],'solver':solver,'matrix_result_check':checked}


def _agreement(a,b,ids,*,winner=None):
    require(a['checked_optimal'] is True and b['checked_optimal'] is True,'Both independent native solves must be checked optimal')
    aa,bb=a['solver'],b['solver'];pa,pb=aa['plan'],bb['plan']
    for plan in (pa,pb):
        require(isinstance(plan,dict) and set(plan)==set(ids) and all(type(v) is int and v in (0,1) for v in plan.values()),'A complete exact integer plan is required')
    require(type(aa['objective_pence']) is int and type(bb['objective_pence']) is int
        and aa['objective_pence']==bb['objective_pence'],'The independent optimal objectives differ')
    if winner is None:require(pa==pb,'The independent best plans differ; uniqueness is not established')
    else:require(pa!=winner and pb!=winner,'The complete winner was not excluded from a runner solve')
    return aa['objective_pence'],pa,pb


def prepare(finance_terminal,output,*,best_preparations=None):
    finance=_checked_finance(finance_terminal);output=Path(output).absolute()
    require(output==output.resolve() and output.is_relative_to(ROOT/'outputs') and not output.exists(),'Use a fresh private outputs directory')
    output.mkdir(parents=True);jobs={};adopted=None
    try:
        if best_preparations is not None and (isinstance(best_preparations,(str,Path)) or 'path' in best_preparations):
            adopted,best_preparations=_adopted_best(best_preparations,finance)
        require(best_preparations is None or set(best_preparations)==set(BACKENDS),'Both exact predeclared best preparations are required')
        for side,backend in BACKENDS.items():
            job=(runtime.prepare(finance['models'][side]['path'],output/'jobs'/(side+'_best'),backend=backend,time_limit_seconds=TIME_LIMIT)
                if best_preparations is None else best_preparations[side])
            _checked_preparation(job,finance['models'][side],backend,None);jobs[side]=job
            require(adopted is not None or not (Path(job['path']).parent/'started.json').exists(),
                'Adopting an already started job requires its exact prospective first-pair manifest')
        return write(output/'preparation.json',{'kind':PREPARED,'version':1,'financial_crosscheck':finance['terminal'],
            'best_preparations':jobs,'best_job_origin':'new_preparations' if best_preparations is None else 'exact_predeclared_first_jobs',
            'adopted_first_pair_manifest':adopted,'recipe':_recipes(),'time_limit_seconds':TIME_LIMIT,'threads':2,
            'parallel_backends':2,'relative_gap':0,'absolute_gap':0,'retries':0,
            'private_density_gate':{'minimum':80,'maximum':160,'public_cardinality_constraint':False},
            'solver_calls_by_this_preparation':0,'model_calls':0,'qualified':False})
    except BaseException as error:
        write(output/'preparation_failure.json',{'error_type':type(error).__name__,'error':str(error),
            'prepared_jobs':jobs,'solver_calls_by_this_preparation':0,'partial_files_preserved':True});raise


def validate_prepared(output):
    output=Path(output).absolute();frozen=read(output/'preparation.json')
    require(frozen.get('kind')==PREPARED and type(frozen.get('version')) is int and frozen['version']==1
        and type(frozen.get('time_limit_seconds')) is int and frozen['time_limit_seconds']==TIME_LIMIT
        and type(frozen.get('threads')) is int and frozen['threads']==2
        and type(frozen.get('retries')) is int and frozen['retries']==0
        and frozen.get('parallel_backends')==2 and frozen.get('relative_gap')==0 and frozen.get('absolute_gap')==0
        and frozen.get('private_density_gate')=={'minimum':80,'maximum':160,'public_cardinality_constraint':False},
        'The first fixed private reference preparation changed')
    require(frozen['recipe']==_recipes(),'The complete current reference implementation closure changed')
    finance=_checked_finance(frozen['financial_crosscheck'])
    if frozen.get('adopted_first_pair_manifest') is not None:
        _,jobs=_adopted_best(frozen['adopted_first_pair_manifest'],finance)
        require(jobs==frozen['best_preparations'],'The adopted first-best jobs changed')
    for side,backend in BACKENDS.items():_checked_preparation(frozen['best_preparations'][side],finance['models'][side],backend,None)
    return frozen,finance


def execute_prepared(output):
    from sheets_factory.core.audit import AuditStore
    from sheets_factory.dashboard import DashboardServer
    from sheets_factory.resume import ProducerLease
    output=Path(output).absolute();frozen,finance=validate_prepared(output)
    require(not (output/'started.json').exists(),'Preserve the first reference attempt; no retry or resume is automatic')
    lease=ProducerLease(output).acquire();audit=server=None;records={};validated={};failure=None;clock=time.monotonic()
    envelope={'kind':KIND,'version':1,'passed':False,'financial_crosscheck':finance['terminal'],
        'preparation':reference(output/'preparation.json'),'solver_receipts':records,'source_or_quality_or_difficulty_certified':False}
    try:
        audit=AuditStore(output/'audit',{'id':output.name,'name':'Independent native best and runner reference',
            'status':'running','target_count':0,'producer_pid':os.getpid(),'producer_active':True})
        server=DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=0);url=server.start()
        write(output/'started.json',{'preparation':reference(output/'preparation.json'),'producer_pid':os.getpid(),
            'started_at':datetime.now(timezone.utc).isoformat(),'dashboard_url':url})
        audit.update_run(dashboard_url=url);print(json.dumps({'dashboard_url':url,'output':str(output)}),flush=True)
        def pair(phase,jobs,excluded):
            def one(side,job):
                tick=time.monotonic();name=side+'_'+phase
                node=audit.record('nodes',{'node':name,'status':'running','started_at':datetime.now(timezone.utc).isoformat()})
                write(output/(name+'_dispatch.json'),{'preparation':job,'model':finance['models'][side],
                    'exclude_plan':excluded,'started_at':datetime.now(timezone.utc).isoformat(),'single_attempt':True})
                folder=Path(job['path']).parent
                if (folder/'terminal.json').is_file():receipt=reference(folder/'terminal.json')
                else:
                    require(not (folder/'started.json').exists(),'A declared first job is still active or incomplete; never dispatch it again')
                    receipt=runtime.execute_prepared(folder)
                records[name]=receipt
                value=validate_solver_receipt(job,receipt,model=finance['models'][side],backend=BACKENDS[side],exclude_plan=excluded)
                validation=write(output/(name+'_validation.json'),value);validated[name]=validation
                audit.update_record('nodes',node,{'status':'completed','duration_ms':(time.monotonic()-tick)*1000,
                    'receipt':receipt,'validation':validation});audit.export();return value
            values={};errors=[]
            with ThreadPoolExecutor(max_workers=2) as workers:
                future={workers.submit(one,side,job):side for side,job in jobs.items()}
                for task in as_completed(future):
                    side=future[task]
                    try:values[side]=task.result()
                    except BaseException as error:
                        if getattr(error,'receipt',None):records[side+'_'+phase]=error.receipt
                        errors.append({'side':side,'phase':phase,'error_type':type(error).__name__,'error':str(error)})
            if errors:
                write(output/(phase+'_failures.json'),{'errors':errors,'all_started_jobs_retained':True});raise RuntimeError('A first-attempt private job failed; no replacement will be started')
            return values
        best=pair('best',frozen['best_preparations'],None)
        objective,winner,_=_agreement(best['A'],best['B'],finance['public']['project_ids'])
        selected=sum(winner.values());require(80<=selected<=160,'The unique-reference candidate failed its private density source gate')
        runner_jobs={}
        for side,backend in BACKENDS.items():runner_jobs[side]=runtime.prepare(finance['models'][side]['path'],
            output/'jobs'/(side+'_runner'),backend=backend,time_limit_seconds=TIME_LIMIT,exclude_plan=winner)
        write(output/'runner_preparations.json',runner_jobs)
        runners=pair('runner',runner_jobs,winner)
        runner_objective,runner_a,runner_b=_agreement(runners['A'],runners['B'],finance['public']['project_ids'],winner=winner)
        gap=objective-runner_objective;require(gap>=1,'A positive integer winner-to-runner gap is required')
        plans=[{'id':'winner','plan':winner},{'id':'runner_A','plan':runner_a},{'id':'runner_B','plan':runner_b}]
        financial=finance_crosscheck.compare_plans(finance['public'],finance['A'],finance['B'],plans,require_feasible=True)
        financial_ref=write(output/'reference_validation.json',financial)
        require(financial['passed'] is True,'Full best/runner financial feasibility differs')
        require(financial['plans'][0]['A']['objective_pence']==objective
            and all(row['A']['objective_pence']==runner_objective for row in financial['plans'][1:]),'Native and full financial reference objectives differ')
        envelope={'kind':KIND,'version':1,'passed':True,'specification':finance['specification'],
            'specification_sha256':spec.canonical_sha256(finance['public']),'financial_crosscheck':finance['terminal'],
            'raw_preparation':finance['raw_preparation'],'universe_A':finance['universe_A'],'universe_B':finance['universe_B'],
            'model_A':finance['models']['A'],'model_B':finance['models']['B'],'solver_receipts':records,
            'solver_validations':validated,'winner_plan':winner,'winner_objective_pence':objective,
            'runner_objective_pence':runner_objective,'gap_pence':gap,'unique_best':True,
            'selected_project_count':selected,'selection_density_passed':True,'private_density_gate':frozen['private_density_gate'],
            'reference_validation':financial_ref,'solver_status_is_not_formal_certificate':True,
            'preparation':reference(output/'preparation.json'),'runtime_profile':{'image_id':runtime.IMAGE_ID,
                'cpus':2,'memory_bytes':32*1024**3,'pids_limit':256,'network':'none','private_solver_seconds':TIME_LIMIT},
            'source_or_quality_or_difficulty_certified':False,'model_calls':0,'LO_calls':0,'qualified':False,'task_count':0}
        _refs(frozen['recipe'])
    except BaseException as error:
        failure=error
        write(output/'failure.json',{'error_type':type(error).__name__,'error':str(error),'traceback':traceback.format_exc(),
            'solver_receipts':records,'single_attempts_preserved':True})
        envelope={'kind':KIND,'version':1,'passed':False,'financial_crosscheck':finance['terminal'],
            'preparation':reference(output/'preparation.json'),'solver_receipts':records,'solver_validations':validated,
            'error_type':type(error).__name__,'error':str(error),'source_or_quality_or_difficulty_certified':False,
            'model_calls':0,'LO_calls':0,'qualified':False,'task_count':0}
    finally:
        try:
            envelope.update(finished_at=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-clock)
            terminal=write(output/'terminal.json',envelope)
            if audit:audit.update_run(status='passed' if failure is None else 'failed',producer_active=False,terminal_receipt=terminal);audit.export()
        finally:
            try:
                if server:server.stop()
            finally:
                try:
                    if audit:audit.db.close()
                finally:lease.release()
    return terminal


def validate_completed(value):
    """Source-builder admission helper; performs no solve or financial repost."""
    record=reference(value) if isinstance(value,(str,Path)) else value;result=read(record)
    require(result.get('kind')==KIND and type(result.get('version')) is int and result['version']==1 and result.get('passed') is True,
        'A completed independent best/runner reference is required')
    frozen,finance=validate_prepared(Path(result['preparation']['path']).parent)
    require(reference(result['preparation']['path'])==result['preparation'],'The reference preparation changed')
    require(result['financial_crosscheck']==finance['terminal'] and result['specification']==finance['specification']
        and result['raw_preparation']==finance['raw_preparation']
        and result['specification_sha256']==spec.canonical_sha256(finance['public'])
        and result['universe_A']==finance['universe_A'] and result['universe_B']==finance['universe_B']
        and result['model_A']==finance['models']['A'] and result['model_B']==finance['models']['B'],'The complete financial/model ancestry changed')
    require(set(result['solver_receipts'])=={'A_best','B_best','A_runner','B_runner'}
        and set(result['solver_validations'])==set(result['solver_receipts']),'All four independent native attempts are required')
    checked={}
    runner_jobs=read(Path(record['path']).parent/'runner_preparations.json')
    for name,terminal in result['solver_receipts'].items():
        side,phase=name.split('_');job=frozen['best_preparations'][side] if phase=='best' else runner_jobs[side]
        checked[name]=validate_solver_receipt(job,terminal,model=finance['models'][side],backend=BACKENDS[side],
            exclude_plan=None if phase=='best' else result['winner_plan'])
        require(read(result['solver_validations'][name])==checked[name],'An actual job validation receipt changed')
    objective,winner,_=_agreement(checked['A_best'],checked['B_best'],finance['public']['project_ids'])
    runner,pa,pb=_agreement(checked['A_runner'],checked['B_runner'],finance['public']['project_ids'],winner=winner)
    require(result['winner_plan']==winner and type(result['winner_objective_pence']) is int and result['winner_objective_pence']==objective
        and type(result['runner_objective_pence']) is int and result['runner_objective_pence']==runner
        and type(result['gap_pence']) is int and result['gap_pence']==objective-runner>=1 and result['unique_best'] is True,
        'The exact winner/runner agreement or uniqueness gap changed')
    require(type(result['selected_project_count']) is int and result['selected_project_count']==sum(winner.values())
        and 80<=sum(winner.values())<=160 and result['selection_density_passed'] is True
        and result['private_density_gate']==frozen['private_density_gate'],'The private density source gate changed')
    expected=finance_crosscheck.compare_plans(finance['public'],finance['A'],finance['B'],[
        {'id':'winner','plan':winner},{'id':'runner_A','plan':pa},{'id':'runner_B','plan':pb}],require_feasible=True)
    require(expected['passed'] is True and read(result['reference_validation'])==expected,'The full reference financial validation changed')
    require(result['solver_status_is_not_formal_certificate'] is True
        and result['source_or_quality_or_difficulty_certified'] is False
        and result.get('qualified') is False and all(type(result.get(k)) is int and result[k]==0 for k in ('model_calls','LO_calls','task_count'))
        and result['runtime_profile']=={'image_id':runtime.IMAGE_ID,'cpus':2,'memory_bytes':32*1024**3,
            'pids_limit':256,'network':'none','private_solver_seconds':TIME_LIMIT},'Reference proof scope or actual profile was changed')
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--finance-terminal',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--best-preparations',type=Path,help='JSON mapping A/B to exact predeclared first-job preparation REFs')
    for command in ('validate','run','validate-completed'):
        p=sub.add_parser(command);p.add_argument('--prepared' if command!='validate-completed' else '--receipt',required=True,type=Path)
    args=parser.parse_args(argv)
    if args.command=='prepare':result=prepare(args.finance_terminal,args.output,best_preparations=args.best_preparations)
    elif args.command=='validate':validate_prepared(args.prepared);result={'validated':str(args.prepared),'solver_calls':0}
    elif args.command=='validate-completed':result=validate_completed(args.receipt)
    else:
        result=execute_prepared(args.prepared);print(json.dumps({'terminal':result}),flush=True);return 0 if read(result)['passed'] else 2
    print(json.dumps(result,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
