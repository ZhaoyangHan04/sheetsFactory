#!/usr/bin/env python3
"""Prepare a complete N360 financial crosscheck; execution needs --run."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.workbook.linear_capital_scaled import spec,finance,model_a,model_b
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease

KIND='linear_capital_scaled_full_financial_crosscheck'
PREPARED='prepared_linear_capital_scaled_full_financial_crosscheck'
RAW_KIND='prepared_linear_capital_scaled_raw_assumptions'
ZERO_FIELDS=('optimizer_calls','LO_calls','model_calls','task_count')


def reference(path):
    p=Path(path).absolute();spec.require(p==p.resolve() and p.is_file() and not p.is_symlink(),'A real immutable artifact is required')
    before=p.stat()
    with p.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    after=p.stat();spec.require((before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
        (after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),'Artifact changed during hashing')
    return {'path':str(p),'sha256':digest,'bytes':after.st_size}


def read(value):
    record=value if isinstance(value,dict) else reference(value)
    spec.require(reference(record['path'])==record,'A frozen reference changed')
    return json.loads(Path(record['path']).read_text())


def write(path,value):
    with Path(path).open('x') as stream:json.dump(value,stream,indent=2,allow_nan=False);stream.write('\n')
    return reference(path)


def math_recipes():
    paths={**finance.source_files(),**model_a.source_files(),**model_b.source_files()}
    return {str(p.resolve()):reference(p) for p in paths.values()}


def execution_recipes():
    from sheets_factory.core import audit
    from sheets_factory import dashboard,resume
    paths=[Path(__file__),ROOT/'scripts/prepare_linear_capital_scaled_catalog.py',
        Path(audit.__file__),Path(dashboard.__file__),Path(resume.__file__)]
    return {**math_recipes(),**{str(p.resolve()):reference(p) for p in paths}}


def _checked_raw(value,*,allow_toy=False):
    raw_ref=value if isinstance(value,dict) else reference(value);raw=read(raw_ref)
    spec.require(raw.get('kind')==RAW_KIND and type(raw.get('version')) is int and raw['version']==2,
        'A new version-two raw preparation is required')
    public=spec.load_spec(read(raw['specification']))
    spec.require(type(allow_toy) is bool and (public['dimension_mode']=='production' and len(public['project_ids'])==360
        or allow_toy and public['dimension_mode']=='toy'), 'The complete N360 production universe is required')
    spec.require(raw['specification_sha256']==spec.canonical_sha256(public),'The complete raw identity changed')
    for path,digest in raw['recipe_sha256'].items():spec.require(reference(path)['sha256']==digest,'An original raw recipe changed')
    plans=raw['diagnostic_plans'];spec.require(type(plans) is list and bool(plans)
        and len({p['id'] for p in plans})==len(plans),'The complete fixed plan inventory is required')
    for plan in plans:spec.validate_plan(public,plan['plan'])
    spec.require(public['dimension_mode']=='toy' or len(plans)==18,'All eighteen production fixed plans are required')
    if public['dimension_mode']=='production':
        path=ROOT/'scripts/prepare_linear_capital_scaled_catalog.py'
        loader=importlib.util.spec_from_file_location('_scaled_raw_pool_validation',path)
        support=importlib.util.module_from_spec(loader);loader.loader.exec_module(support)
        declaration=support.validate_declaration(read(raw['declaration']))
        order=[row['id'] for row in declaration['profiles']]
        policies=[row for row in declaration['profiles'] if row['id']==raw['profile_id']]
        specs=raw['all_specifications_frozen_before_finance']
        spec.require(len(policies)==1 and raw['prospective_profile_order']==order and list(specs)==order
            and specs[raw['profile_id']]==raw['specification'] and raw['recipe_sha256']==support.recipes()
            and raw['seed']==policies[0]['seed'] and raw['revenue_jitter_pence']==policies[0]['revenue_jitter_pence']
            and support.zero_claims(raw), 'The full raw pool declaration, recipe or member identity changed')
        for record in specs.values():spec.require(reference(record['path'])==record,'A predeclared peer raw source changed')
        spec.require(plans==support.catalog.diagnostic_plans(public,seed=raw['seed']),
            'The eighteen declared fixed plans changed')
    return raw_ref,raw,public


def prepare(raw_preparation,output,*,allow_toy=False):
    raw_ref,raw,public=_checked_raw(raw_preparation,allow_toy=allow_toy)
    output=Path(output).absolute()
    spec.require(output==output.resolve() and output.is_relative_to(ROOT/'outputs') and not output.exists(),
        'Use a fresh zero-execution finance preparation')
    output.mkdir(parents=True)
    return write(output/'preparation.json',{'kind':PREPARED,'version':2,'created_at':datetime.now(timezone.utc).isoformat(),
        'raw_preparation':raw_ref,'specification':raw['specification'],'recipe':math_recipes(),'execution_recipe':execution_recipes(),
        'diagnostic_plan_ids':[p['id'] for p in raw['diagnostic_plans']],'toy_only':public['dimension_mode']=='toy',
        'allow_toy':allow_toy,'all_standalone_scenarios_must_be_feasible':True,
        'fixed_plan_group_violations_are_diagnostics':True,**{k:0 for k in ZERO_FIELDS},'qualified':False})


def validate_prepared(output):
    frozen=read(Path(output)/'preparation.json')
    spec.require(frozen.get('kind')==PREPARED and type(frozen.get('version')) is int and frozen['version']==2
        and frozen['recipe']==math_recipes() and frozen['execution_recipe']==execution_recipes()
        and frozen['qualified'] is False and all(type(frozen.get(k)) is int and frozen[k]==0 for k in ZERO_FIELDS),
        'The complete zero-execution financial preparation changed')
    _,raw,public=_checked_raw(frozen['raw_preparation'],allow_toy=frozen['allow_toy'])
    spec.require(frozen['specification']==raw['specification'] and frozen['toy_only']==(public['dimension_mode']=='toy')
        and frozen['diagnostic_plan_ids']==[p['id'] for p in raw['diagnostic_plans']],
        'The public source or all fixed plans changed')
    return frozen,raw,public


def execute_prepared(output,*,port=0):
    output=Path(output).absolute();frozen,raw,public=validate_prepared(output)
    spec.require(not (output/'started.json').exists() and not (output/'terminal.json').exists(),
        'Preserve the first finance attempt; retries are not implicit')
    lease=ProducerLease(output).acquire();audit=server=thread=None
    stop=threading.Event();clock=time.monotonic();stage='starting';records={};failure=None
    try:
        spec.require(not (output/'started.json').exists(),'Another producer already started')
        audit=AuditStore(output/'audit',{'id':output.name,'name':'N360 complete independent finance and matrix checks',
            'status':'running','target_count':0,'producer_pid':os.getpid(),'producer_active':True})
        server=DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=port);url=server.start()
        records['started']=write(output/'started.json',{'preparation':reference(output/'preparation.json'),
            'started_at':datetime.now(timezone.utc).isoformat(),'dashboard_url':url,'producer_pid':os.getpid()})
        audit.update_run(dashboard_url=url);print(json.dumps({'dashboard_url':url,'output':str(output)}),flush=True)
        def heartbeat():
            while not stop.wait(15):audit.update_run(active_stage=stage,elapsed_seconds=time.monotonic()-clock);audit.export()
        thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
        def run(name,operation):
            nonlocal stage
            stage=name;tick=time.monotonic();audit.update_run(active_stage=name)
            audit.emit('financial.stage_started',stage=name)
            try:value=operation()
            except BaseException as error:
                audit.record('nodes',{'node':name,'status':'failed','duration_ms':(time.monotonic()-tick)*1000,'error':str(error)})
                raise
            records[name]=write(output/(name+'.json'),value)
            audit.record('nodes',{'node':name,'status':'completed','duration_ms':(time.monotonic()-tick)*1000,'receipt':records[name]})
            audit.emit('financial.stage_completed',stage=name,receipt=records[name]);audit.export()
            print(json.dumps({'completed_stage':name,'receipt':records[name]}),flush=True);return value
        a=run('universe_A',lambda:finance.build_universe_a(public))
        b=run('universe_B',lambda:finance.build_universe_b(public))
        comparison=run('complete_financial_comparison',lambda:finance.compare_universes(public,a,b))
        spec.require(comparison['passed'] is True,'Independent postings differ or a candidate is infeasible')
        plans=run('all_predeclared_plan_comparison',lambda:finance.compare_plans(public,a,b,raw['diagnostic_plans']))
        spec.require(plans['passed'] is True,'The complete fixed-plan aggregate comparison failed')
        ma=run('model_A',lambda:model_a.build_model(public,a));mb=run('model_B',lambda:model_b.build_model(public,b))
        keys=('kind','version','project_ids','objective_pence','rows','specification_sha256')
        changed=[key for key in keys if ma[key]!=mb[key]]
        matrix=run('complete_matrix_comparison',lambda:{'passed':not changed,'different_sections':changed,
            'project_count':len(ma['project_ids']),'all_business_rows':len(ma['rows']),
            'all_integer_coefficients_compared':len(ma['rows'])*len(ma['project_ids']),
            'distinct_universe_metadata_hashes_allowed':True})
        spec.require(matrix['passed'],'The complete independent integer matrices differ')
        validate_prepared(output)
    except BaseException as error:
        failure=error;records['failure']=write(output/'failure.json',{'stage':stage,'error_type':type(error).__name__,
            'error':str(error),'traceback':traceback.format_exc(),'all_partial_artifacts_preserved':True})
    finally:
        stop.set()
        if thread:thread.join(timeout=1)
        terminal={'kind':KIND,'version':2,'passed':failure is None,'completed_at':datetime.now(timezone.utc).isoformat(),
            'elapsed_seconds':time.monotonic()-clock,'preparation':reference(output/'preparation.json'),
            'specification':frozen['specification'],'raw_preparation':frozen['raw_preparation'],
            'recipe':frozen['recipe'],'execution_recipe':frozen['execution_recipe'],'toy_only':frozen['toy_only'],
            'host_financial_computation':True,'container_resource_claimed':False,
            'source_admission_or_quality_or_difficulty_certified':False,**{k:0 for k in ZERO_FIELDS},'qualified':False}
        terminal.update(records)
        receipt=write(output/'terminal.json',terminal)
        if audit:
            audit.update_run(status='passed' if failure is None else 'failed',producer_active=False,terminal_receipt=receipt)
            audit.export()
        if server:server.stop()
        if audit:audit.db.close()
        lease.release()
    print(json.dumps({'terminal':receipt,'passed':failure is None}),flush=True)
    if failure is not None:raise RuntimeError('Preserve the failed first finance attempt: '+receipt['path']) from failure
    return receipt


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-preparation',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--prepared',type=Path);parser.add_argument('--run',action='store_true')
    parser.add_argument('--allow-toy',action='store_true');parser.add_argument('--port',type=int,default=0)
    args=parser.parse_args(argv)
    if args.prepared:
        spec.require(not any((args.raw_preparation,args.output,args.allow_toy)),'Choose a frozen preparation or a new one')
        result=execute_prepared(args.prepared,port=args.port) if args.run else validate_prepared(args.prepared)[0]
    else:
        spec.require(args.raw_preparation is not None and args.output is not None,'Provide explicit raw input and a fresh output')
        result=prepare(args.raw_preparation,args.output,allow_toy=args.allow_toy)
        if args.run:result=execute_prepared(args.output,port=args.port)
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
