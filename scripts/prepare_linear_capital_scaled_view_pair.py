#!/usr/bin/env python3
"""Freeze both N360 views; only --run materializes and validates them."""
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
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.workbook.linear_capital_scaled import task_views

CONFIG=ROOT/'config/pipelines/linear_capital_scaled_view_pair_v2.json'
CONFIG_SHA256='e8dd5d8ed7e3c22e795c8fd0e0e6d24578110a92f260a2a5bfea12a6d0578ef9'
PREPARED='prepared_linear_capital_scaled_first_view_pair'
KIND='linear_capital_scaled_first_view_pair_actual_validation'
ZERO_FIELDS=('LO_calls','model_calls','solver_calls','Harbor_calls','task_count')
_MODULES={}


def require(condition,message):
    if not condition:raise ValueError(message)


def support(name):
    paths={'source':'build_linear_capital_scaled_source.py','validator':'validate_linear_capital_scaled_task_view.py'}
    require(name in paths,'Only the two frozen N360 support APIs are permitted')
    if name not in _MODULES:
        path=ROOT/'scripts'/paths[name]
        loader=importlib.util.spec_from_file_location('_scaled_pair_support_'+name,path)
        module=importlib.util.module_from_spec(loader);loader.loader.exec_module(module);_MODULES[name]=module
    return _MODULES[name]


def reference(value):return support('source').reference(value)
def read(value):return support('source').read(value)
def write(path,value):return support('source').write(path,value)
def now():return datetime.now(timezone.utc).isoformat()


def policy(path=CONFIG):
    record=reference(path)
    require(record['sha256']==CONFIG_SHA256,'The complete fixed first-profile pair policy changed')
    return record,read(record)


def recipes():
    from sheets_factory.core import audit
    from sheets_factory import dashboard,resume
    helper,validator=support('source'),support('validator')
    paths=[Path(__file__),CONFIG,Path(helper.__file__),Path(validator.__file__),
        Path(task_views.__file__),task_views.UPSTREAM,Path(audit.__file__),Path(dashboard.__file__),Path(resume.__file__)]
    return {**helper.recipes(),**validator.recipes('scaled360'),
        **{str(p.resolve()):reference(p)['sha256'] for p in paths}}


def guard(mapping):
    require(mapping==recipes(),'The complete fixed source/view validation code recipe changed')


def checked_source(value,configuration):
    helper=support('source');record=value if isinstance(value,dict) else reference(value)
    source=helper.validate_source(record)
    require(source.get('kind')==configuration['source_kind'] and type(source.get('version')) is int and source['version']==1
        and source.get('status')=='source_verified_not_task_or_difficulty_qualified'
        and source.get('source_financially_verified') is True and source.get('qualified') is False,
        'An actual complete N360 source admission is required; pending or old sources do not qualify')
    # The real source validator checked the complete reference. These exact
    # raw identities choose the prospectively fixed member, never its filename.
    independent=read(source['independent_reference']);raw=read(independent['raw_preparation'])
    first=configuration['first_profile']
    require(independent.get('kind')==configuration['reference_kind'] and independent.get('passed') is True
        and raw.get('kind')=='prepared_linear_capital_scaled_raw_assumptions' and raw.get('version')==2
        and raw.get('profile_id')==first['id'] and type(raw.get('seed')) is int and raw['seed']==first['seed']
        and type(raw.get('revenue_jitter_pence')) is int and raw['revenue_jitter_pence']==first['revenue_jitter_pence']
        and raw.get('prospective_profile_order')==[f'L360-P{i:02d}' for i in range(1,21)],
        'Only the original first fixed-order P01 reference/source can enter this pair')
    require((source['public_specification']['sha256'],source['public_specification']['bytes'])==
        (raw['specification']['sha256'],raw['specification']['bytes']), 'The source primitives differ from the original P01 raw bytes')
    profile,value=helper.runtime(source['runtime_profile']['path'])
    require(profile==source['runtime_profile']==reference(ROOT/configuration['runtime_profile'])
        and value['image']['id']==configuration['image_id']
        and all(value['docker_resources'][role]==configuration['resources'] for role in ('source','agent','verifier')),
        'All source/calculation and configured verifier resources must retain the same pinned 2CPU32 profile')
    return record,source


def prepare(source_manifest,output,*,configuration=CONFIG):
    output=support('source')._output(output,fresh=True);output.mkdir(parents=True)
    started=write(output/'preparation_started.json',{'created_at':now(),'source_manifest_path':
        source_manifest.get('path') if isinstance(source_manifest,dict) else str(source_manifest),
        **{key:0 for key in ZERO_FIELDS},'workbooks_emitted':0,'qualified':False})
    try:
        config_ref,config=policy(configuration);recipe=recipes();source_ref,source=checked_source(source_manifest,config)
        rows=[{'mode':mode,'view_directory':str(output/mode/'view'),
            'validation_directory':str(output/mode/'actual_validation')} for mode in config['mode_order']]
        guard(recipe)
        return write(output/'preparation.json',{'kind':PREPARED,'version':2,'created_at':now(),'started':started,
            'configuration':config_ref,'source_manifest':source_ref,'source_workbook':source['workbook'],
            'source_provider':config['source_provider'],'profile_id':config['first_profile']['id'],
            'runtime_profile':source['runtime_profile'],'mode_order':config['mode_order'],'modes':rows,
            'required_actual_LO_calls':config['required_actual_LO_calls'],'recipe_sha256':recipe,
            'both_modes_fixed_before_any_materialization':True,'both_validator_preparations_required_before_first_LO':True,
            **{key:0 for key in ZERO_FIELDS},'workbooks_emitted':0,'qualified':False})
    except BaseException as error:
        write(output/'preparation_failure.json',{'error_type':type(error).__name__,'error':str(error),
            'traceback':traceback.format_exc(),'started':started,**{key:0 for key in ZERO_FIELDS},
            'workbooks_emitted':0,'qualified':False});raise


def validate_prepared(output):
    output=support('source')._output(output);frozen=read(output/'preparation.json')
    config_ref,config=policy(frozen['configuration']['path']);guard(frozen['recipe_sha256'])
    require(frozen.get('kind')==PREPARED and type(frozen.get('version')) is int and frozen['version']==2
        and frozen['configuration']==config_ref and frozen.get('qualified') is False
        and frozen['mode_order']==config['mode_order'] and frozen['profile_id']==config['first_profile']['id']
        and frozen['source_provider']==config['source_provider'] and frozen['required_actual_LO_calls']==config['required_actual_LO_calls']
        and frozen['both_modes_fixed_before_any_materialization'] is True
        and frozen['both_validator_preparations_required_before_first_LO'] is True
        and all(type(frozen.get(key)) is int and frozen[key]==0 for key in (*ZERO_FIELDS,'workbooks_emitted')),
        'A complete fixed zero-execution pair preparation is required')
    expected=[{'mode':mode,'view_directory':str(output/mode/'view'),
        'validation_directory':str(output/mode/'actual_validation')} for mode in config['mode_order']]
    require(frozen['modes']==expected,'The complete paired output mapping changed')
    _,source=checked_source(frozen['source_manifest'],config)
    require(source['workbook']==frozen['source_workbook'] and source['runtime_profile']==frozen['runtime_profile'],
        'The admitted source or resource profile changed')
    return frozen,source


def execute_prepared(output,*,port=0):
    output=support('source')._output(output)
    require(not any((output/name).exists() for name in ('started.json','terminal.json','execution_preflight_failure.json')),
        'Preserve the first pair attempt; retries are disabled')
    try:frozen,source=validate_prepared(output)
    except BaseException as error:
        if output.is_dir():write(output/'execution_preflight_failure.json',{'error_type':type(error).__name__,
            'error':str(error),'traceback':traceback.format_exc(),**{key:0 for key in ZERO_FIELDS},'qualified':False})
        raise
    lease=ProducerLease(output).acquire();audit=server=thread=None;stop=threading.Event()
    clock=time.monotonic();stage='starting';failure=None;views={};preparations={};terminals={};call_count=0
    try:
        require(not (output/'started.json').exists(),'Another pair producer already started')
        audit=AuditStore(output/'audit',{'id':output.name,'name':'P01 paired N360 task materialization and actual validation',
            'status':'running','producer_pid':os.getpid(),'producer_active':True,'target_count':0})
        server=DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=port);url=server.start()
        write(output/'started.json',{'created_at':now(),'preparation':reference(output/'preparation.json'),
            'dashboard_url':url,'producer_pid':os.getpid(),'retry_count':0})
        audit.update_run(dashboard_url=url);audit.export();print(json.dumps({'dashboard_url':url,'output':str(output),'pid':os.getpid()}),flush=True)
        def heartbeat():
            while not stop.wait(15):
                audit.update_run(active_stage=stage,elapsed_seconds=time.monotonic()-clock,
                    completed_modes=list(terminals),LO_calls_in_completed_mode_terminals=call_count,
                    current_mode_LO_count_unknown=stage.startswith('actual_'));audit.export()
        thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
        def run(name,operation):
            nonlocal stage
            stage=name;tick=time.monotonic();audit.update_run(active_stage=name);audit.export()
            try:result=operation()
            except BaseException as error:
                audit.record('nodes',{'node':name,'status':'failed','duration_ms':(time.monotonic()-tick)*1000,'error':str(error)});raise
            audit.record('nodes',{'node':name,'status':'completed','duration_ms':(time.monotonic()-tick)*1000});audit.export()
            return result
        helper,validator=support('source'),support('validator')
        with helper._resource_support().data_temporary(output):
            for row in frozen['modes']:
                mode=row['mode'];guard(frozen['recipe_sha256'])
                plan=run('plan_'+mode,lambda:task_views.plan_task_view(source['workbook']['path'],
                    source['public_specification']['path'],source['bindings']['path'],mode=mode))
                run('materialize_'+mode,lambda:task_views.materialize_view(plan,row['view_directory']))
                views[mode]=reference(Path(row['view_directory'])/'private/view_manifest.json')
            for row in frozen['modes']:
                mode=row['mode'];preparations[mode]=run('freeze_validator_'+mode,lambda:validator.prepare(
                    frozen['source_manifest'],views[mode],row['validation_directory'],source_provider='scaled360'))
            before=write(output/'both_validator_preparations_before_LO.json',{'source_manifest':frozen['source_manifest'],
                'view_manifests':views,'validator_preparations':preparations,'mode_order':frozen['mode_order'],
                'source_provider':'scaled360','LO_calls':0,'model_calls':0,'solver_calls':0,'qualified':False})
            print(json.dumps({'both_prepared_before_first_LO':before}),flush=True)
            for row in frozen['modes']:
                mode=row['mode'];guard(frozen['recipe_sha256'])
                receipt=run('actual_'+mode,lambda:validator.execute_prepared(row['validation_directory']))
                result=run('cold_validate_'+mode,lambda:validator.validate_completed(receipt))
                require(result['passed'] is True and result['mode']==mode and result['source_provider']=='scaled360'
                    and result['source_admission']==frozen['source_manifest'] and result['materialized_view']==views[mode]
                    and result['qualified'] is False and len(result['actual_LO_calls'])==frozen['required_actual_LO_calls'][mode],
                    'The complete actual paired validation identity/count changed')
                terminals[mode]=receipt;call_count+=len(result['actual_LO_calls'])
        guard(frozen['recipe_sha256'])
    except BaseException as error:
        failure={'stage':stage,'error_type':type(error).__name__,'error':str(error),
            'traceback':traceback.format_exc(),'all_partial_artifacts_preserved':True,'retry_count':0}
        failure=write(output/'failure.json',failure)
    finally:
        stop.set()
        if thread:thread.join(timeout=1)
        # A failed validator may retain a partial terminal. Record it without
        # calling it successful or adding missing calculations as zero.
        partial={}
        for row in frozen['modes']:
            path=Path(row['validation_directory'])/'terminal.json'
            if path.is_file() and row['mode'] not in terminals:partial[row['mode']]=reference(path)
        try:
            receipt=write(output/'terminal.json',{'kind':KIND,'version':2,'passed':failure is None,
                'completed_at':now(),'elapsed_seconds':time.monotonic()-clock,'preparation':reference(output/'preparation.json'),
                'source_manifest':frozen['source_manifest'],'profile_id':frozen['profile_id'],'source_provider':'scaled360',
                'mode_order':frozen['mode_order'],'view_manifests':views,'validator_preparations':preparations,
                'validation_terminals':terminals,'partial_validation_terminals':partial,'failure':failure,
                'LO_calls_in_complete_validated_modes':call_count,'LO_call_count_exact':call_count if failure is None else None,
                'source_LO_calls_performed_by_this_bridge':0,'model_calls':0,'solver_calls':0,'Harbor_calls':0,
                'task_count':0,'qualified':False,'normal_quality_or_recovery_or_difficulty_certified':False,
                'actual_Harbor_verifier_executed':False,'retry_count':0})
            if audit:
                audit.update_run(status='passed' if failure is None else 'failed',producer_active=False,terminal=receipt);audit.export()
        finally:
            try:
                if server:server.stop()
            finally:
                try:
                    if audit:audit.db.close()
                finally:lease.release()
        print(json.dumps({'terminal':receipt,'passed':failure is None}),flush=True)
    if failure:raise RuntimeError('Preserved failed first pair attempt: '+receipt['path'])
    return receipt


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--configuration',type=Path,default=CONFIG);parser.add_argument('--prepared',type=Path)
    parser.add_argument('--run',action='store_true');parser.add_argument('--port',type=int,default=0);args=parser.parse_args(argv)
    require(0<=args.port<=65535,'Use a valid local dashboard port')
    if args.prepared:
        require(args.source_manifest is None and args.output is None and args.configuration==CONFIG,'A frozen pair cannot receive replacement inputs')
        result=execute_prepared(args.prepared,port=args.port) if args.run else validate_prepared(args.prepared)[0]
    else:
        require(args.source_manifest is not None and args.output is not None,'Provide an actual source manifest and fresh output')
        result=prepare(args.source_manifest,args.output,configuration=args.configuration)
        if args.run:result=execute_prepared(args.output,port=args.port)
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
