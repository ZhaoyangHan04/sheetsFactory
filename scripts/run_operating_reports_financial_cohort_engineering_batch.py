#!/usr/bin/env python3
"""One fixed nine-case source/task engineering batch; no financial forwards."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.workbook.operating_reports_financial_cohort_v1 import schema,raw
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease

KIND='fixed_nine_operating_reports_financial_cohort_engineering'
ORDER=[f'FM-C{i:02d}' for i in range(1,10)]
SOURCE=ROOT/'scripts/build_operating_reports_financial_cohort_source.py'
SOURCE_SHA='701a277f0b20ebe448fef3957735a37f117b1fe3acdc2c2c103def2351f851e0'
TASK=ROOT/'scripts/validate_operating_reports_financial_cohort_tasks.py'
TASK_SHA='8188d2add6e96660f8b7401114d4d6af6bc46ffd6f01647971daa50eefd77b91'
RESERVATIONS=ROOT/'outputs/research/.operating_reports_financial_cohort_engineering_v1'
_APIS=None


def require(value,message):
    if not value:raise ValueError(message)


def reference(path):return schema.reference(path)
def checked(row):
    require(reference(row['path'])==row,'An immutable batch artifact changed');return Path(row['path'])
def read(value):return json.loads((checked(value) if isinstance(value,dict) else Path(value)).read_text())
def ref(value):return dict(value) if isinstance(value,dict) else reference(value)
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as stream:json.dump(value,stream,indent=2,allow_nan=False);stream.write('\n')
    return reference(path)
def now():return datetime.now(timezone.utc).isoformat()


def apis():
    global _APIS
    require(reference(SOURCE)['sha256']==SOURCE_SHA and reference(TASK)['sha256']==TASK_SHA,'The reviewed genuine source/task providers changed')
    if _APIS is None:
        modules=[]
        for label,path in [('source',SOURCE),('task',TASK)]:
            loader=importlib.util.spec_from_file_location('_cohort_engineering_'+label,path)
            module=importlib.util.module_from_spec(loader);loader.loader.exec_module(module);modules.append(module)
        _APIS=tuple(modules)
    return _APIS


def recipes():
    source,task=apis()
    return {**source.recipes(),**task.recipes(),str(Path(__file__).resolve()):reference(__file__)}


@contextmanager
def monitor(output,phase):
    audit=AuditStore(output/phase,{'id':output.name+'-'+phase,'name':'Nine-case financial cohort engineering','status':'running','producer_active':True,'qualified':False,'target_count':0})
    server=DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=0)
    failure=True
    try:
        url=server.start();write(output/(phase+'_panel.json'),{'dashboard_url':url,'pid':os.getpid(),'at':now()})
        print(json.dumps({'dashboard_url':url,'phase':phase,'pid':os.getpid()}),flush=True)
        yield audit,url
        failure=False
    finally:
        audit.update_run(status='failed' if failure else 'completed',producer_active=False);audit.export();server.stop();audit.db.close()


def inventory(reference_batch,reused,output,reused_task=None):
    batch=read(reference_batch);all_raw=raw.validate_all(batch['raw_inventory'])
    require(batch['kind']=='complete_once_financial_cohort_reference_and_emission_batch' and batch['version']==1
        and batch['passed'] is True and batch['passed_cases']==9 and batch['new_raw_attempts']==9
        and batch['financial_forwards_started']==18 and batch['outer_retries']==0
        and batch['actual_LO_calls']==batch['actual_model_calls']==0 and batch['qualified'] is False
        and [row['case_id'] for row in batch['cases']]==ORDER,'Freeze the complete fixed nine-case actual reference batch without filtering')
    rows=[]
    for row in batch['cases']:
        identity=row['case_id'];require(row['passed'] is True and set(row['forwards'])=={'A','B'},'A retained case failed before engineering')
        for record in [row['candidate'],row['comparison'],row['specification'],*row['forwards'].values()]:checked(record)
        require(read(row['candidate'])['candidate_id']==identity and read(row['comparison'])['case_id']==identity
            and read(row['candidate'])['specification_sha256']==schema.canonical_sha256(all_raw['specifications'][identity]),
            'A candidate or stored financial comparison belongs to another case')
        rows.append({'case_id':identity,'candidate':row['candidate'],'specification':row['specification'],
            'forward_A':row['forwards']['A'],'forward_B':row['forwards']['B'],'comparison':row['comparison'],
            'source_directory':str(output/'cases'/identity/'source'),'task_directory':str(output/'cases'/identity/'task'),
            'reuse_source':reused if identity=='FM-C01' else None,'reuse_task':reused_task if identity=='FM-C01' else None})
    # This batch follows the one separately authorized C01 source pilot.
    require(reused is not None,'Reuse the original completed C01 source pilot; do not repeat its source3 calls')
    source=read(reused);preparation=read(source['preparation'])
    require(source['kind']==apis()[0].SOURCE_KIND and source['passed'] is True
        and preparation['case_id']=='FM-C01' and preparation['candidate_manifest']==rows[0]['candidate']
        and preparation['raw_inventory']==batch['raw_inventory'],'The immutable original C01 source pilot belongs to another case')
    if reused_task:
        task=read(reused_task);tf=read(task['preparation'])
        require(task['kind']==apis()[1].TERMINAL_KIND and task['passed'] is True
            and tf['case_id']=='FM-C01' and tf['source_manifest']==reused and tf['raw_inventory']==batch['raw_inventory'],
            'The immutable C01 task pilot belongs to another case or source')
    return rows,batch['raw_inventory']


def prepare(reference_batch,output,*,reuse_C01_source,reuse_C01_task=None):
    output=Path(output).absolute();require(output==output.resolve() and not output.exists(),'Use a fresh batch preparation')
    output.mkdir(parents=True)
    try:
        with monitor(output,'prepare_audit'):
            source,task=apis();reused_task=ref(reuse_C01_task) if reuse_C01_task else None
            rows,raw_inventory=inventory(ref(reference_batch),ref(reuse_C01_source),output,reused_task)
            # Full genuine replay; a passed field alone cannot confer reuse.
            actual=source.validate_source(ref(reuse_C01_source));sf=source.read(actual['preparation'])
            require(sf['case_id']=='FM-C01' and sf['raw_inventory']==raw_inventory and sf['candidate_manifest']==rows[0]['candidate'],
                'Cold-validated C01 source does not match the fixed cohort')
            if reused_task:
                complete=task.validate_completed(reused_task);tf=task.read(complete['preparation'])
                require(tf['case_id']=='FM-C01' and tf['source_manifest']==ref(reuse_C01_source) and tf['raw_inventory']==raw_inventory,
                    'Cold-validated C01 task does not match its original source')
            return write(output/'prospective.json',{'kind':KIND,'version':1,'reference_batch':ref(reference_batch),
                'raw_inventory':raw_inventory,'reuse_C01_source':ref(reuse_C01_source),'reuse_C01_task':reused_task,'case_order':ORDER,'cases':rows,
                'recipe':recipes(),'contract':reference(schema.CONTRACT),'runtime_profile':reference(source.PROFILE),
                'max_parallel_cases':2,'new_source_calls':24,'task_calls':40 if reused_task else 45,'reused_original_source_calls':3,
                'reused_original_task_calls':5 if reused_task else 0,
                'max_new_actual_LO_calls':64 if reused_task else 69,'all_nine_frozen_before_first_native':True,'outer_retries':0,
                'new_financial_forwards':0,'actual_LO_calls':0,'model_calls':0,'Harbor_calls':0,'qualified':False})
    except BaseException as error:
        write(output/'preparation_failure.json',{'type':type(error).__name__,'error':str(error),'retry_permitted':False});raise


def validate_prepared(output):
    output=Path(output).absolute();f=read(output/'prospective.json')
    rows,raw_inventory=inventory(f['reference_batch'],f['reuse_C01_source'],output,f['reuse_C01_task'])
    require(f['kind']==KIND and f['version']==1 and f['case_order']==ORDER and f['cases']==rows and f['raw_inventory']==raw_inventory
        and f['recipe']==recipes() and f['contract']==reference(schema.CONTRACT)
        and f['runtime_profile']==reference(apis()[0].PROFILE) and f['max_parallel_cases']==2
        and f['all_nine_frozen_before_first_native'] is True and f['new_source_calls']==24 and f['task_calls']==(40 if f['reuse_C01_task'] else 45)
        and f['reused_original_task_calls']==(5 if f['reuse_C01_task'] else 0)
        and f['reused_original_source_calls']==3 and f['max_new_actual_LO_calls']==(64 if f['reuse_C01_task'] else 69)
        and f['outer_retries']==f['new_financial_forwards']==f['actual_LO_calls']==f['model_calls']==f['Harbor_calls']==0
        and f['qualified'] is False,'The fixed full-cohort resources, identities or prospective changed')
    return f


def worker(output,case_id):
    output=Path(output).absolute();require((output/'started.json').exists(),'The master dashboard must start before child cold work')
    f=validate_prepared(output);require(case_id in ORDER,'No case selection or rename is permitted')
    row=next(r for r in f['cases'] if r['case_id']==case_id);folder=output/'cases'/case_id;folder.mkdir(parents=True,exist_ok=True)
    write(folder/'worker_started.json',{'case_id':case_id,'pid':os.getpid(),'at':now(),'prospective':reference(output/'prospective.json')})
    source,task=apis();records={};stages=[];clock=time.monotonic();failure=None
    def stage(name,operation):
        start=write(folder/'stages'/(name+'_started.json'),{'at':now(),'stage':name});tick=time.monotonic()
        try:return operation()
        finally:
            stages.append({'stage':name,'started':start,'passed':sys.exc_info()[0] is None,
                'terminal':write(folder/'stages'/(name+'_terminal.json'),{'stage':name,'passed':sys.exc_info()[0] is None,'elapsed_seconds':time.monotonic()-tick})})
    try:
        if row['reuse_source']:
            actual=stage('genuine_original_C01_source_replay',lambda:source.validate_source(row['reuse_source']))
            sf=source.read(actual['preparation'])
            require(sf['case_id']==case_id and sf['candidate_manifest']==row['candidate'] and sf['raw_inventory']==f['raw_inventory'],'The reused whole source changed identity')
            records['source_manifest']=row['reuse_source']
        else:
            records['source_preparation']=stage('source_prepare',lambda:source.prepare(row['candidate'],row['source_directory'],
                raw_inventory=f['raw_inventory'],case_id=case_id,forward_A=row['forward_A'],forward_B=row['forward_B'],comparison=row['comparison']))
            records['source_manifest']=stage('source3_complete_native',lambda:source.execute_prepared(row['source_directory']))
        if row['reuse_task']:
            records['task_terminal']=row['reuse_task']
        else:
            records['task_preparation']=stage('FM_five_controls_prepare',lambda:task.prepare(records['source_manifest'],row['task_directory']))
            records['task_terminal']=stage('FM_task5_complete_native',lambda:task.execute_prepared(row['task_directory']))
        complete=stage('genuine_complete_FM_task_replay',lambda:task.validate_completed(records['task_terminal']))
        tf=task.read(complete['preparation'])
        require(tf['case_id']==case_id and tf['raw_inventory']==f['raw_inventory']
            and tf['source_manifest']==records['source_manifest'],'The completed task belongs to another source or case')
    except BaseException as error:
        failure={'type':type(error).__name__,'error':str(error)}
        for key,path in (('source_manifest',Path(row['source_directory'])/'source_manifest.json'),
                         ('task_terminal',Path(row['task_directory'])/'terminal.json')):
            if key not in records and path.exists():records[key]=reference(path)
    counts={'started':0,'completed':0,'complete':True}
    for key,stage_name in (('source_manifest','source3_complete_native'),('task_terminal','FM_task5_complete_native')):
        if key=='source_manifest' and row['reuse_source']:continue
        if key=='task_terminal' and row['reuse_task']:continue
        if key in records:
            retained=read(records[key]);counts['started']+=retained['actual_LO_calls_started'];counts['completed']+=retained['actual_LO_calls_completed']
        elif any(stage['stage']==stage_name for stage in stages):counts['complete']=False
    terminal=write(folder/'worker_terminal.json',{'kind':KIND+'_case_terminal','version':1,'case_id':case_id,
        'passed':failure is None,'failure':failure,'records':records,'stages':stages,'prospective':reference(output/'prospective.json'),
        'elapsed_seconds':time.monotonic()-clock,'reused_C01_source3':row['reuse_source'] is not None,'reused_C01_task5':row['reuse_task'] is not None,
        'actual_new_LO_calls':counts,'outer_retries':0,'new_financial_forwards':0,'model_calls':0,'Harbor_calls':0,'qualified':False})
    print(json.dumps(terminal),flush=True);return 0 if failure is None else 1


def execute_prepared(output):
    output=Path(output).absolute();metadata=read(output/'prospective.json')
    require(metadata['kind']==KIND and metadata['version']==1 and not (output/'started.json').exists(),'Preserve the first batch execution; retries are disabled')
    lease=ProducerLease(output).acquire();active={};completed={};clock=time.monotonic()
    try:
        with monitor(output,'run_audit') as (audit,url):
            write(output/'started.json',{'prospective':reference(output/'prospective.json'),'pid':os.getpid(),'dashboard_url':url,'at':now()})
            f=validate_prepared(output)
            RESERVATIONS.mkdir(parents=True,exist_ok=True);require(RESERVATIONS==RESERVATIONS.resolve(),'Use the real permanent cohort reservation directory')
            write(RESERVATIONS/(schema.CONTRACT_SHA256+'.json'),{'prospective':reference(output/'prospective.json'),'at':now(),'outer_retries':0})
            pending=list(f['cases']);last_live=0.0
            while pending or active:
                while pending and len(active)<2:
                    row=pending.pop(0);identity=row['case_id'];folder=output/'cases'/identity;folder.mkdir(parents=True,exist_ok=True)
                    stdout=(folder/'stdout.log').open('x');stderr=(folder/'stderr.log').open('x')
                    argv=[sys.executable,str(Path(__file__).resolve()),'--prepared',str(output),'--worker',identity]
                    process=subprocess.Popen(argv,cwd=ROOT,stdout=stdout,stderr=stderr)
                    launcher=write(folder/'launcher.json',{'pid':process.pid,'at':now(),'argv':argv})
                    audit.task(identity,mode='financial_modeling',source_id=identity,status='engineering',node='source_and_task_engineering')
                    node=audit.record('nodes',{'node':identity,'task_id':identity,'status':'running','started_at':now(),'duration_ms':0})
                    active[identity]=(process,stdout,stderr,launcher,node,time.monotonic())
                tick=time.monotonic()
                if tick-last_live>=3:
                    for identity,(_,_,_,_,node,started) in active.items():
                        audit.update_record('nodes',node,{'status':'running','duration_ms':1000*(tick-started)})
                    last_live=tick
                for identity,(process,stdout,stderr,launcher,node,started) in list(active.items()):
                    code=process.poll()
                    if code is None:continue
                    stdout.close();stderr.close();folder=output/'cases'/identity;path=folder/'worker_terminal.json'
                    terminal=reference(path) if path.exists() else None
                    completed[identity]={'case_id':identity,'passed':code==0 and terminal is not None and read(terminal)['passed'] is True,
                        'returncode':code,'terminal':terminal,'launcher':launcher,'stdout':reference(folder/'stdout.log'),'stderr':reference(folder/'stderr.log')}
                    audit.update_record('nodes',node,{'status':'completed' if completed[identity]['passed'] else 'failed',
                        'duration_ms':1000*(time.monotonic()-started),'terminal':terminal,'finished_at':now()})
                    audit.task(identity,status='engineering_passed' if completed[identity]['passed'] else 'rejected',node='source_and_task_engineering')
                    del active[identity]
                audit.update_run(active_cases={key:row[0].pid for key,row in active.items()},completed_cases=len(completed),
                    elapsed_seconds=time.monotonic()-clock,producer_active=True);audit.export();time.sleep(.5)
            require(validate_prepared(output)==f,'The immutable complete cohort changed during execution')
            call_counts=[]
            for row in completed.values():
                call_counts.append(read(row['terminal']).get('actual_new_LO_calls',{'complete':False}) if row['terminal'] else {'complete':False})
            known=all(row.get('complete') is True for row in call_counts)
            return write(output/'terminal.json',{'kind':KIND+'_terminal','version':1,'cases':[completed[key] for key in ORDER],
                'passed':all(row['passed'] for row in completed.values()),'prospective':reference(output/'prospective.json'),
                'actual_new_LO_calls':{'complete':known,'started':sum(row['started'] for row in call_counts) if known else None,
                    'completed':sum(row['completed'] for row in call_counts) if known else None},
                'outer_retries':0,'max_parallel_cases':2,'new_financial_forwards':0,'model_calls':0,'Harbor_calls':0,'qualified':False})
    except BaseException as error:
        write(output/'orchestration_failure.json',{'type':type(error).__name__,'error':str(error),'completed':completed,
            'active_owned_pids':{key:row[0].pid for key,row in active.items()},'retry_permitted':False});raise
    finally:
        for process,stdout,stderr,_,_,_ in active.values():process.wait();stdout.close();stderr.close()
        lease.release()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('reference-batch','reuse-C01-source','reuse-C01-task','output','prepared'):parser.add_argument('--'+key,type=Path)
    parser.add_argument('--run',action='store_true');parser.add_argument('--worker',choices=ORDER);args=parser.parse_args(argv)
    if args.prepared:
        require(not any((args.output,args.reference_batch,args.reuse_C01_source,args.reuse_C01_task)),'Do not override a frozen batch')
        if args.worker:return worker(args.prepared,args.worker)
        result=execute_prepared(args.prepared) if args.run else validate_prepared(args.prepared)
    else:
        require(args.reference_batch and args.reuse_C01_source and args.output and not args.run and not args.worker,'Prepare all nine and reuse the genuine C01 source before actual batch dispatch')
        result=prepare(args.reference_batch,args.output,reuse_C01_source=args.reuse_C01_source,reuse_C01_task=args.reuse_C01_task)
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())

