#!/usr/bin/env python3
"""Run the exact whole-root oracle/nop commands with actual role observations.

This produces control evidence, not a quality, difficulty or release verdict.
The delivered twenty-task manifest and every payload byte remain immutable.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from functools import lru_cache

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard.server import DashboardServer
from sheets_factory.evaluation.resource_harbor import inspect_resource_export
from sheets_factory.evaluation.resource_observer import ResourceObserver, validate_trial_observations

AUDITOR=ROOT/'scripts/audit_harbor_job.py'
AUDITOR_SHA='2b1e7b6189d1efd7affea50cec49e8994c8e69ec7489043b652580b495990e08'
COMMANDS={role:['harbor','run','-p','SpreadsheetEval','-a',role] for role in ('oracle','nop')}
FILES=frozenset({'instruction.md','task.toml','export_manifest.json','environment/Dockerfile',
 'environment/input.xlsx','environment/recalculate','environment/resource_runner.py','environment/runtime_profile.json',
 'solution/solve.sh','solution/reference.xlsx','tests/Dockerfile','tests/original_input.xlsx','tests/reference.xlsx',
 'tests/verify.py','tests/test.sh','tests/runtime_profile.json','tests/streaming_core.py'})


def require(condition,message):
    if not condition:raise ValueError(message)


def now():return datetime.now(timezone.utc).isoformat()


def reference(path):
    path=Path(path).absolute()
    require(path==path.resolve() and path.is_file() and not path.is_symlink(),'Use an exact regular file')
    raw=path.read_bytes();return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}


def read(path):return json.loads(Path(path).read_text())


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as stream:json.dump(value,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n')
    return reference(path)


def dataset_inventory(root):
    root=Path(root).absolute();dataset=root/'SpreadsheetEval';manifest_ref=reference(dataset/'dataset_manifest.json')
    manifest=read(manifest_ref['path']);tasks=manifest['tasks'];ids=[r['task_id'] for r in tasks]
    require(manifest['task_count']==20 and len(ids)==len(set(ids))==20
        and manifest['counts_by_mode']==dict(Counter(r['mode'] for r in tasks))=={'financial_modeling':10,'debugging':10}
        and set(ids)==set(manifest['selected_task_ids']) and len(manifest['selected_task_ids'])==20,
        'Require the entire fixed twenty-task cohort, ten tasks per mode')
    require({p.name for p in dataset.iterdir()}==set(ids)|{'dataset_manifest.json'},'Dataset entries differ from the complete manifest')
    inventories={}
    for row in tasks:
        task=dataset/row['task_id'];require(task==task.resolve() and task.is_dir(),'A task path escaped the real dataset')
        require(not any(p.is_symlink() for p in task.rglob('*')),'Symlink payloads are forbidden')
        inventory={str(p.relative_to(task)):reference(p)['sha256'] for p in sorted(task.rglob('*')) if p.is_file()}
        require(set(inventory)==FILES and inventory==row['payload_files'],'All seventeen exact payload bytes are required')
        require(inspect_resource_export(task)==row['harbor_export_binding'],'A delivered export binding changed')
        inventories[row['task_id']]=inventory
    return {'manifest':manifest_ref,'payload_files':inventories,'task_ids':ids,'counts_by_mode':manifest['counts_by_mode']}


@lru_cache(maxsize=1)
def auditor():
    require(reference(AUDITOR)['sha256']==AUDITOR_SHA,'The frozen complete-job auditor changed')
    loader=importlib.util.spec_from_file_location('_private_exact_root_resource_job_auditor',AUDITOR)
    module=importlib.util.module_from_spec(loader);loader.loader.exec_module(module)
    # These are the same explicit resource-file/inspector adaptations as the
    # existing resource finalizer. The original auditor module is not mutated.
    module.EXPORT_FILES=FILES;module.inspect_export=inspect_resource_export
    return module.audit_harbor_job


def _new_job(jobs,baseline,role,root):
    candidates=[p for p in jobs.iterdir() if p.is_dir() and p.name!='resource_observations' and p.name not in baseline]
    require(len(candidates)<=1,'More than one new default job exists; ownership is ambiguous')
    if not candidates:return None
    job=candidates[0]
    require(job==job.resolve() and not job.is_symlink(),'The new job must be a real owned directory')
    config=job/'config.json'
    if not config.is_file():return None
    value=read(config)
    # Harbor persists exclude_defaults=True. Its built-in default agent is
    # oracle, and even the timestamp job name can be omitted in the same second.
    # Reconstruct only the installed public config schema, then require rich
    # trial/result identity again in the unchanged complete-job auditor.
    from harbor.models.job.config import JobConfig
    resolved=JobConfig.model_validate(value)
    name_ok=(value['job_name']==job.name if 'job_name' in value else
             re.fullmatch(r'\d{4}-\d{2}-\d{2}__\d{2}-\d{2}-\d{2}',job.name) is not None)
    require(name_ok and len(resolved.agents)==1 and resolved.agents[0].name==role
        and not resolved.agents[0].import_path and not resolved.agents[0].model_name,
        'The new persisted job belongs to another control role')
    datasets=resolved.datasets
    require(len(datasets)==1 and datasets[0].path is not None
        and (root/datasets[0].path).resolve()==root/'SpreadsheetEval'
        and not datasets[0].task_names and not datasets[0].exclude_task_names and datasets[0].n_tasks is None
        and not resolved.tasks and resolved.n_attempts==1 and resolved.retry.max_retries==0 and not resolved.install_only,
        'The exact root command must target the whole delivered dataset once')
    return job


class OwnedJobObserver(ResourceObserver):
    """Discover only this command's newly persisted default job, before polling."""
    def __init__(self,jobs,baseline,role,root):
        self.jobs=jobs;self.baseline=set(baseline);self.control_role=role;self.root=root;self.owned_job=None
        # No pre-existing root or trial is ever observed. A placeholder performs
        # no Docker queries until the exact newly persisted job is bound.
        super().__init__(jobs,job_dirs=[jobs/'.unassigned-exact-root-control'])

    def poll_once(self):
        job=_new_job(self.jobs,self.baseline,self.control_role,self.root)
        if job is None:return
        require(self.owned_job is None or self.owned_job==job,'The command changed its owned job directory')
        self.owned_job=job;self.job_dirs=(job,)
        super().poll_once()


def owned_absence(validations,*,runner=subprocess.run):
    owners={}
    for value in validations:
        require(value['passed'] is value['complete'] is True,'Actual complete role observations are required')
        for ref in value['observations']:
            require(reference(ref['path'])==ref,'A retained actual observation changed')
            row=read(ref['path']);cid=row['container']['Id']
            require(re.fullmatch('[0-9a-f]{64}',cid) and cid==row['queried_container_id'],'Only exact observed full owned CIDs may be queried')
            owners[cid]={'id':cid,'trial_name':row['trial_name'],'role':row['role'],'ownership':ref}
    daemon=runner(['docker','info','--format','{{.ServerVersion}}'],capture_output=True,text=True,timeout=20)
    require(daemon.returncode==0 and bool(daemon.stdout.strip()),'A reachable daemon is required; unknown cleanup cannot pass')
    for cid in owners:
        result=runner(['docker','inspect','--type','container',cid],capture_output=True,text=True,timeout=20)
        require(result.returncode!=0 and cid in result.stderr and re.search(r'no such (?:object|container)',result.stderr,re.I),
            'An exact owned container remains present or its absence is unknown')
        owners[cid]['absent']=True
    return {'all_owned_containers_absent':True,'owned':list(owners.values()),'daemon_reachable':True,
        'no_containers_created_changed_or_removed_by_cleanup_audit':True}


def _run_role(root,out,role,inventory,audit,*,popen=subprocess.Popen):
    jobs=root/'jobs';jobs.mkdir(exist_ok=True)
    baseline={p.name for p in jobs.iterdir()};started=now();tick=time.monotonic()
    environment=dict(os.environ);environment['PATH']=str(root/'.venv312/bin')+os.pathsep+environment.get('PATH','')
    command=COMMANDS[role];audit.update_run(stage=role+'_root_command')
    with (out/(role+'.stdout.log')).open('w') as stdout,(out/(role+'.stderr.log')).open('w') as stderr:
        with OwnedJobObserver(jobs,baseline,role,root) as observer:
            process=popen(command,cwd=root,env=environment,stdout=stdout,stderr=stderr)
            write(out/(role+'_started.json'),{'argv':command,'cwd':str(root),'pid':process.pid,'started_at':started,
                'dataset_manifest':inventory['manifest'],'prior_job_directories':sorted(baseline),'retry_limit':0})
            audit.update_run(control_pid=process.pid)
            while process.poll() is None:
                audit.update_run(control_role=role,control_elapsed_seconds=round(time.monotonic()-tick,3));audit.export();time.sleep(2)
            observer.poll_once()
        finished=now()
    require(process.returncode==0,'The exact '+role+' root command did not complete successfully')
    require(observer.receipt is not None and observer.finalization_error is None and observer.owned_job is not None,
            'The actual stopped observer and unique owned default job are required')
    job=observer.owned_job
    require(dataset_inventory(root)==inventory,'The complete delivered dataset changed while the command ran')
    whole=auditor()(root/'SpreadsheetEval',job,agent=role,command_cwd=root,output=None)
    require(whole['status']=='passed' and whole['counts']=={'dataset_tasks':20,'trial_results':20,'matched_rewards':20,
        'exceptions':0,'missing':0,'unknown':0,'duplicates':0},'Every delivered task must have the exact expected actual control reward')
    validations=[]
    for trial in whole['trials']:
        result=Path(trial['result_file']);validated=validate_trial_observations(result.with_name('config.json'),result,
            receipts=[observer.receipt],expected_task_directory=root/'SpreadsheetEval'/trial['task_id'])
        require(validated['passed'] is validated['complete'] is True,'Actual '+role+' agent/verifier CPU/RAM/image proof is incomplete')
        validations.append(validated)
    controls=write(out/(role+'_whole_job_audit.json'),whole)
    actual_resources=write(out/(role+'_actual_resources.json'),{'passed':True,'validations':validations,
        'owned_cleanup':owned_absence(validations),'agent_PID_limit_schema_supported':False})
    return write(out/(role+'_command_receipt.json'),{'kind':'executed_exact_root_harbor_control','version':1,
        'argv':command,'cwd':str(root),'returncode':0,'dataset_manifest':inventory['manifest'],
        'started_at':started,'finished_at':finished,'job_directory':str(job),'job_result':reference(job/'result.json'),
        'resource_observation_receipts':[observer.receipt],'whole_job_audit':controls,'actual_resources':actual_resources,
        'qualification_claimed':False,'raw_rewards_modified':False})


def run(output,*,root=ROOT,port=0):
    root=Path(root).absolute();out=Path(output).absolute()
    require(root==root.resolve() and out==out.resolve() and out.is_relative_to(root/'outputs') and not out.exists(),
        'Use a fresh private real output directory')
    store=AuditStore(out,{'id':out.name,'status':'running','stage':'freeze_dataset','target_candidates':20})
    dashboard=DashboardServer(store.snapshot,store.events,port=port);url=dashboard.start()
    write(out/'dashboard.json',{'url':url});print(json.dumps({'dashboard':url}),flush=True)
    jobs=root/'jobs';jobs.mkdir(exist_ok=True)
    lock_path=jobs/'.exact_root_controls.lock'
    try:
        with lock_path.open('a') as lock:
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            inventory=dataset_inventory(root)
            prospective=write(out/'prospective.json',{'kind':'prospective_exact_twenty_root_controls','version':1,
                'commands':COMMANDS,'cwd':str(root),'dataset_inventory':inventory,'implementation':reference(__file__),
                'whole_job_auditor':reference(AUDITOR),'observer_implementation':reference(sys.modules[ResourceObserver.__module__].__file__),
                'attempts_per_role':1,'retries':0,'qualification_claimed':False})
            receipts={role:_run_role(root,out,role,inventory,store) for role in ('oracle','nop')}
            require(dataset_inventory(root)==inventory,'The final dataset changed after whole controls')
            terminal=write(out/'terminal.json',{'kind':'complete_exact_twenty_root_controls','version':1,'passed':True,
                'prospective':prospective,'dataset_manifest':inventory['manifest'],'command_receipts':receipts,
                'oracle_all20_reward':1,'nop_all20_reward':0,'actual_role_resources_checked':True,
                'qualification_claimed':False,'new_model_calls':0})
            store.update_run(status='completed',stage='both_complete');store.export();print(json.dumps(terminal),flush=True)
            return terminal
    except BaseException as error:
        write(out/'failure.json',{'error_type':type(error).__name__,'error':str(error),'qualification_claimed':False,
            'retry_performed':False,'raw_rewards_modified':False})
        store.update_run(status='failed',stage='retained_failure',error_type=type(error).__name__);store.export();raise
    finally:dashboard.stop();store.db.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--port',type=int,default=0);args=parser.parse_args();run(args.output,port=args.port)

if __name__=='__main__':main()
