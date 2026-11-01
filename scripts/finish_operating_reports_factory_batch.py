#!/usr/bin/env python3
"""One-shot continuation from existing development to final retained evidence."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard.server import DashboardServer
HELPERS={name:ROOT/'scripts'/filename for name,filename in {
 'freeze':'freeze_operating_reports_factory_cohort.py','frontier':'run_operating_reports_factory_frontier.py',
 'controls':'run_exact_root_harbor_controls.py','quality':'join_operating_reports_factory_final_quality.py',
 'finalize':'finalize_operating_reports_factory_release.py'}.items()}


def require(value,message):
    if not value:raise ValueError(message)


def ref(path):
    path=Path(path).absolute();require(path==path.resolve() and path.is_file(),'Use an exact regular retained file')
    raw=path.read_bytes();return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}


def read(path):return json.loads(Path(path).read_text())


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as stream:json.dump(value,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n')
    return ref(path)


def load(name):
    loader=importlib.util.spec_from_file_location('_factory_finish_'+name,HELPERS[name])
    module=importlib.util.module_from_spec(loader);loader.loader.exec_module(module);return module



def child_summary(paths):
    """Read live counters without importing or duplicating any model call."""
    answer={};totals={'input_tokens':0,'output_tokens':0,'cached_input_tokens':0,'llm_calls':0,'unknown_usage_calls':0}
    for name,path in paths.items():
        path=Path(path)
        if not path.is_file():continue
        try:
            connection=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True,timeout=.2)
            try:
                connection.execute('PRAGMA query_only=ON')
                calls=[json.loads(r[0]) for r in connection.execute('SELECT payload FROM calls')]
                tasks=[json.loads(r[0]) for r in connection.execute('SELECT payload FROM tasks')]
                run=connection.execute("SELECT value FROM state WHERE key='run'").fetchone()
            finally:connection.close()
            values={'input_tokens':sum(c.get('input_tokens') or 0 for c in calls),
                'output_tokens':sum(c.get('output_tokens') or 0 for c in calls),
                'cached_input_tokens':sum(c.get('cached_input_tokens') or 0 for c in calls),'llm_calls':len(calls),
                'unknown_usage_calls':sum(type(c.get('input_tokens')) is not int or type(c.get('output_tokens')) is not int for c in calls),
                'task_count':len(tasks),'task_statuses':{state:sum(t.get('status')==state for t in tasks)
                   for state in sorted({str(t.get('status','unknown')) for t in tasks})}}
            values['total_tokens']=values['input_tokens']+values['output_tokens']
            values['status']=json.loads(run[0]).get('status') if run else 'unknown';answer[name]=values
            for key in totals:totals[key]+=values[key]
        except (OSError,ValueError,sqlite3.Error):answer[name]={'status':'not_yet_readable'}
    return {'phases':answer,'known_totals':{**totals,'total_tokens':totals['input_tokens']+totals['output_tokens']},
            'cached_input_tokens_are_subset':True,'display_only_not_a_score_or_usage_certificate':True}


def wait_file(path,audit,stage):
    tick=time.monotonic();require(path==path.resolve(),'A future producer artifact must use a real path')
    while not path.is_file():
        audit.update_run(stage=stage,waiting_for=str(path),waiting_seconds=round(time.monotonic()-tick,3),
            child_summary=child_summary({ 'development':path.parent/'evaluation/run.sqlite'}));audit.export();time.sleep(3)
    return ref(path)


def commands(development,batches,ids,out,concurrency):
    command=[str(ROOT/'.venv312/bin/python'),str(HELPERS['frontier']),'prepare','--phase','confirmation',
             '--development',str(development),'--output',str(out/'confirmation'),'--run','--concurrency',str(concurrency)]
    for batch in batches:command+=['--batch',str(batch)]
    for task_id in ids:command+=['--task-id',task_id]
    return {'confirmation':command,'root_controls':[str(ROOT/'.venv312/bin/python'),str(HELPERS['controls']),
                                                  '--output',str(out/'root_controls')]}


def child_status(name,out):
    directory=out/name;links=[]
    for path in (directory/'dashboard.json',directory/'preparation_monitor/dashboard.json',directory/'execution_monitor/dashboard.json'):
        if path.is_file():
            try:
                value=read(path);url=value.get('url',value.get('dashboard_url'))
                if url:links.append(url)
            except (OSError,ValueError):pass
    phase='material_admission' if name=='confirmation' else 'freeze_root_dataset'
    if name=='confirmation' and (directory/'started.json').exists():phase='native_confirmation'
    if name=='root_controls':
        for role in ('oracle','nop'):
            if (directory/(role+'_started.json')).exists():phase=role+'_root_command'
    if (directory/'terminal.json').is_file():phase='terminal'
    return {'phase':phase,'dashboard_urls':links}


def parallel(commands_by_name,out,audit,*,popen=subprocess.Popen,development=None):
    """A failed sibling never cancels or restarts a healthy process."""
    children={};handles=[];launch_error=None;environment=dict(os.environ)
    environment['PATH']=str(ROOT/'.venv312/bin')+os.pathsep+environment.get('PATH','')
    try:
        for name,argv in commands_by_name.items():
            stdout=(out/(name+'.stdout.log')).open('w');stderr=(out/(name+'.stderr.log')).open('w');handles += [stdout,stderr]
            try:process=popen(argv,cwd=ROOT,env=environment,stdout=stdout,stderr=stderr)
            except Exception as error:launch_error=error;break
            children[name]={'process':process,'tick':time.monotonic(),'argv':argv,
                'node_id':audit.record('nodes',{'task_id':name,'node':name,'status':'running','duration_ms':0})}
            write(out/(name+'_launched.json'),{'pid':process.pid,'argv':argv,'started_at':datetime.now(timezone.utc).isoformat(),'retries':0})
            audit.task(name,status='running',node=name,pid=process.pid)
        while True:
            active=False
            for name,row in children.items():
                result=row['process'].poll();active |= result is None;current_tick=time.monotonic()
                if result is not None:row.setdefault('finished_tick',current_tick)
                duration=round(1000*(row.get('finished_tick',current_tick)-row['tick']))
                state='running' if result is None else 'completed' if result==0 else 'failed'
                detail=child_status(name,out)
                audit.task(name,status=state,node=name,duration_ms=duration,pid=row['process'].pid,**detail)
                audit.update_record('nodes',row['node_id'],{'status':state,'duration_ms':duration,**detail})
            metrics={'confirmation':out/'confirmation/evaluation/run.sqlite'}
            if development is not None:metrics['development']=development.parent/'evaluation/run.sqlite'
            audit.update_run(stage='parallel_confirmation_and_root_controls',active_children=[n for n,r in children.items() if r['process'].poll() is None],
                child_summary=child_summary(metrics));audit.export()
            if not active:break
            time.sleep(3)
        if launch_error is not None:raise launch_error
        require(len(children)==2 and all(r['process'].returncode==0 for r in children.values()),'A child failed; original evidence is retained and no child was retried')
    finally:
        for handle in handles:handle.close()


def master_snapshot(audit):
    value=audit.snapshot();run=value.get('run',{});totals=run.get('child_summary',{}).get('known_totals',{})
    value.setdefault('metrics',{}).update(totals)
    if 'candidate_count' in run:value['metrics']['candidates']=run['candidate_count']
    return value


def finish(development_terminal,batches,fm_join,debug_join,output,*,confirmation_concurrency=20,dataset_root=ROOT/'SpreadsheetEval',port=0):
    development=Path(development_terminal).absolute();batches=[Path(b).absolute() for b in batches]
    fm_join,debug_join=Path(fm_join).absolute(),Path(debug_join).absolute();out=Path(output).absolute()
    require(Path(dataset_root).absolute()==ROOT/'SpreadsheetEval','The delivered dataset must be the repository root SpreadsheetEval')
    require(confirmation_concurrency==20,'This prospective continuation fixes twenty independent confirmation contexts')
    require(out==out.resolve() and out.is_relative_to(ROOT/'outputs') and not out.exists(),'Use a fresh private continuation directory')
    audit=AuditStore(out,{'id':out.name,'status':'running','stage':'wait_existing_development','target_candidates':20})
    server=DashboardServer(lambda:master_snapshot(audit),audit.events,port=port);url=server.start()
    write(out/'dashboard.json',{'url':url});print(json.dumps({'dashboard':url}),flush=True)
    try:
        recipe={name:ref(path) for name,path in HELPERS.items()};batch_refs=[ref(b) for b in batches]
        audit.update_run(candidate_count=sum(len(read(b)['tasks']) for b in batches),selected_count=0)
        guard=lambda:require(all(ref(r['path'])==r for r in [*recipe.values(),*batch_refs]),'A frozen helper or engineered batch changed')
        write(out/'prospective.json',{'kind':'one_shot_factory_batch_continuation','version':1,'future_development_terminal':str(development),
            'batches':batch_refs,'shared_joins':[str(fm_join),str(debug_join)],'dataset_root':str(ROOT/'SpreadsheetEval'),
            'confirmation_concurrency':20,'recipe':recipe,'implementation':ref(__file__),'outer_retries':0,'qualified':False})
        dev_ref=wait_file(development,audit,'wait_existing_development');dev=read(development)
        require(dev.get('kind')=='operating_reports_factory_frontier_terminal_v6' and dev.get('phase')=='development'
                and dev.get('outer_retries')==0,'Only the existing genuine development terminal can select the cohort')
        guard();cohort_ref=load('freeze').freeze(development,batches,out/'cohort',ROOT/'SpreadsheetEval');cohort=read(cohort_ref['path'])
        require(ref(development)==dev_ref and cohort['development']==dev_ref and cohort['count']==20,'The frozen cohort must bind this completed development phase')
        audit.update_run(candidate_count=sum(len(read(b)['tasks']) for b in batches),selected_count=20)
        parallel(commands(development,batches,cohort['selected_task_ids'],out,confirmation_concurrency),out,audit,development=development)
        confirmation=out/'confirmation/terminal.json';controls=out/'root_controls/terminal.json'
        require(confirmation.is_file() and controls.is_file(),'Both successful children must retain actual terminals')
        wait_file(fm_join,audit,'wait_completed_FM_shared_review');wait_file(debug_join,audit,'wait_completed_DBG_shared_review');guard()
        audit.update_run(stage='join_final_quality');audit.export()
        quality=load('quality').build(cohort_ref['path'],fm_join,debug_join,controls,confirmation,ROOT/'SpreadsheetEval')
        quality_ref=write(out/'quality.json',quality);require(quality.get('passed') is True,'Final quality evidence did not pass; the complete report is retained')
        audit.update_run(stage='final_release_checks');audit.export();guard()
        release=load('finalize').finalize(cohort_ref['path'],confirmation,quality_ref['path'],controls,ROOT/'reports/operating_report_factory_release.json')
        terminal=write(out/'terminal.json',{'kind':'complete_one_shot_factory_batch_continuation','version':1,'passed':True,
            'development':dev_ref,'cohort':cohort_ref,'quality':quality_ref,'confirmation':ref(confirmation),'root_controls':ref(controls),
            'release':release,'outer_retries':0,'README_or_git_publication_changed':False})
        audit.update_run(status='completed',stage='final_receipt_written');audit.export();print(json.dumps(terminal),flush=True);return terminal
    except BaseException as error:
        write(out/'failure.json',{'error_type':type(error).__name__,'error':str(error),'retries':0,'healthy_children_not_cancelled':True,'qualified':False})
        audit.update_run(status='failed',stage='retained_failure',error_type=type(error).__name__);audit.export();raise
    finally:server.stop();audit.db.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('development-terminal','fm-join','debug-join','output'):parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--batch',type=Path,action='append',required=True);parser.add_argument('--confirmation-concurrency',type=int,default=20)
    parser.add_argument('--dataset-root',type=Path,default=ROOT/'SpreadsheetEval');parser.add_argument('--port',type=int,default=0)
    args=parser.parse_args();finish(args.development_terminal,args.batch,args.fm_join,args.debug_join,args.output,
        confirmation_concurrency=args.confirmation_concurrency,dataset_root=args.dataset_root,port=args.port)

if __name__=='__main__':main()
