#!/usr/bin/env python3
"""Opt-in source precision revision: reuse one real call, then two fresh calls.

This changes source correctness reconciliation only. E05/E06, financial rules,
facts, formulae and native caches remain unchanged. Old failed attempts remain
failed. Preparation performs no financial forward or native calculation.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.workbook.operating_reports_financial_cohort_v1 import source_precision as precision

BASE=ROOT/'scripts/build_operating_reports_financial_cohort_source.py'
BASE_SHA='701a277f0b20ebe448fef3957735a37f117b1fe3acdc2c2c103def2351f851e0'
PRECISION_SHA='5814086002296a1dd4a333a62bdf0630301ce62a5de41258f6f0e8fa6c10b68a'
POLICY_SHA='76c8c2e0895f68fce6a1288fcac7817bf33a3cb2123995f8ac25e0ea9d43b210'
FAILED_BATCH=ROOT/'outputs/research/operating_reports_financial_cohort_engineering_batch_20261101T012800Z/terminal.json'
FAILED_BATCH_REF={'path':str(FAILED_BATCH),'sha256':'faa125c7c0ab5ce20f5b86d69fbf9c053870fcd6d035fc773c8d7563f84123db','bytes':11913}
KIND='prepared_operating_reports_financial_cohort_source_precision_revision2'
SOURCE_KIND='independently_checked_operating_reports_financial_cohort_source_precision_revision2'
STAGES=('source1','source2','source3');VERSION=2

if hashlib.sha256(BASE.read_bytes()).hexdigest()!=BASE_SHA:raise ValueError('The frozen original cohort source changed')
_loader=importlib.util.spec_from_file_location('_precision_v2_frozen_source',BASE)
base=importlib.util.module_from_spec(_loader);_loader.loader.exec_module(base)
# This is a new facade. No original helper's globals or namespace is modified.
_N=dict(base._N)
for _name in ('require','reference','checked','read','write','runtime','compare_typed','owned_absence','validate_call','stage'):
    globals()[_name]=getattr(base,_name)


def recipes():
    require(reference(BASE)['sha256']==BASE_SHA and reference(precision.__file__)['sha256']==PRECISION_SHA
        and precision.policy_sha256()==POLICY_SHA,'The original workflow or new fixed precision policy changed')
    return {**base.recipes(),**{str(p.resolve()):reference(p) for p in (Path(__file__),BASE,Path(precision.__file__))}}


def _cleanup(record,calls):
    ids=[c['actual_resource_evidence']['container_id']for c in calls]
    require(record['all_owned_containers_absent'] is True and record['daemon_reachable'] is True
        and record['cleanup_mutations_by_validator'] is False and len(record['owned'])==len(calls)
        and len(set(ids))==len(ids) and type(record['daemon_version'])is str and bool(record['daemon_version'].strip())
        and all(row['absent'] is True and type(row['returncode'])is int and row['returncode']==1 and not row['stdout'].strip()
            and re.fullmatch(r'(?i:(?:error:\s*)?no such (?:object|container):\s*)'+re.escape(row['full_id']),row['stderr'].strip())
            and re.fullmatch('[0-9a-f]{64}',row['full_id'])for row in record['owned'])
        and {row['full_id'] for row in record['owned']}==set(ids),
        'The retained owned-container absence must cover every exact call')


def _call(call,index,previous,frozen):
    require(type(call['index'])is int and call['index']==index and call['role']==STAGES[index-1]
        and call['input']==previous and call['completed'] is True,'The complete source call chain changed')
    checked(call['output'])
    require(read(call['terminal_receipt'])=={k:v for k,v in call.items() if k!='terminal_receipt'},'Original source call terminal changed')
    started=read(call['started_receipt'])
    require(started=={k:v for k,v in call.items() if k in ('index','role','input','started_at','completed') and k!='completed'}|{'completed':False},
        'The original call reservation changed')
    require(validate_call(call,call['actual_resource_evidence']['terminal'],frozen)==call['actual_resource_evidence'],
        'A complete genuine capped native resource receipt is required')


def _reconcile(path,frozen,*,stored=None):
    """Run all old construction checks, then the complete new raw-value audit."""
    public,left,right,_=stored or base._stored(frozen)
    definition=read(frozen['definition']);expected=read(frozen['expected']);bindings=read(frozen['bindings'])
    strict=base.audit_workbook(path,definition,expected)
    require(strict['all_financial_fields_checked']==strict['all_derived_values_checked']==93510
        and strict['physical_formulas_checked']==88676 and strict['provided_financial_input_fields_checked']==11200
        and strict['protected_public_literals_checked']==len(definition['literals'])
        and strict['native_errors']==[] and strict['all_formula_caches_empty'] is False and strict['qualified'] is False,
        'All original structural, formula, fact, type and error checks remain mandatory')
    raw_a=precision.audit_workbook(strict['workbook'],public,bindings,left)
    raw_b=precision.audit_workbook(strict['workbook'],public,bindings,right)
    require(all(row['passed'] is True and row['checked_financial_fields']==row['declared_financial_fields']==93510
        and row['policy_sha256']==POLICY_SHA for row in (raw_a,raw_b)),'The complete fixed source-only numeric reconciliation failed')
    boundaries_a={row['point']:row for row in raw_a['round_boundary_differences']}
    boundaries_b={row['point']:row for row in raw_b['round_boundary_differences']}
    require(boundaries_a==boundaries_b,'Stored independent primary values disagree on actual round boundaries')
    seen=set()
    for mismatch in strict['mismatches']:
        point=mismatch['point']
        require(set(mismatch)=={'point','expected','actual'} and point not in seen and point in expected
            and mismatch['expected']==expected[point] and mismatch['expected']['type']==mismatch['actual']['type']=='number'
            and point in boundaries_a and boundaries_a[point]['within_source_bound'] is True,
            'A nonnumeric, supplied-context, type or unaccounted mismatch cannot use the precision policy')
        seen.add(point)
    require(seen==set(boundaries_a) and strict['passed'] is (not strict['mismatches']),
        'Preserve and account for every original two-decimal mismatch')
    return {'kind':'complete_independent_cohort_source_precision_audit','version':VERSION,'passed':True,
        'workbook':strict['workbook'],'original_strict_audit':strict,'raw_independent_A':raw_a,'raw_independent_B':raw_b,
        'retained_round_boundary_count':len(seen),'all_financial_fields_checked':93510,'policy_sha256':POLICY_SHA,
        'E05_E06_grader_changed':False,'new_financial_forwards':0,'qualified':False,'difficulty_certified':False}


def _retained(failed_source):
    """Bind an original fixed-cohort failure; JSON pass flags never admit reuse."""
    ref=base._ref(failed_source);terminal=read(ref);batch=read(FAILED_BATCH_REF)
    require(batch['passed'] is False and batch['outer_retries']==batch['new_financial_forwards']==batch['model_calls']==0,
        'Preserve the original complete fixed-nine failed engineering batch')
    worker_rows=[row for row in batch['cases'] if row['case_id'] in tuple(f'FM-C{i:02d}' for i in range(2,10))]
    matches=[]
    for row in worker_rows:
        worker=read(row['terminal'])
        if worker['records'].get('source_manifest')==ref:matches.append((row,worker))
    require(len(worker_rows)==8 and len(matches)==1,'Reuse exactly one of the original eight failed source1 attempts')
    row,worker=matches[0]
    require(row['passed'] is False and worker['passed'] is False and worker['case_id']==row['case_id']
        and worker['actual_new_LO_calls']=={'started':1,'completed':1,'complete':True},'The original failed worker must contain exactly one complete actual call')
    require(terminal['kind']==base.SOURCE_KIND and type(terminal['version'])is int and terminal['version']==1
        and terminal['passed'] is False and terminal['failure']=={'type':'ValueError','message':'Complete independent financial/type/literal audit failed'}
        and all(type(terminal[k])is int for k in ('actual_LO_calls_started','actual_LO_calls_completed','retry','new_financial_forwards','model_calls','solver_calls','Harbor_calls','task_count'))
        and terminal['actual_LO_calls_started']==terminal['actual_LO_calls_completed']==1 and len(terminal['actual_calls'])==1
        and terminal['cold_start_is_unseeded'] is True and terminal['memoized_independent_ledgers'] is True
        and terminal['retry']==terminal['new_financial_forwards']==terminal['model_calls']==terminal['solver_calls']==terminal['Harbor_calls']==terminal['task_count']==0
        and terminal['qualified'] is terminal['normal_all12_QA_passed'] is terminal['difficulty_claimed'] is False,
        'Only the original source1 numeric-audit failure can enter this new protocol')
    frozen=base.validate_prepared(checked(terminal['preparation']).parent)
    require(frozen['case_id']==row['case_id'] and worker['records']['source_preparation']==terminal['preparation']
        and terminal['specification']==frozen['specification'] and terminal['specification_sha256']==frozen['specification_sha256']
        and terminal['bindings']==frozen['bindings'],'The original whole preparation/raw identity changed')
    call=terminal['actual_calls'][0];_call(call,1,frozen['cold_start'],frozen)
    require(terminal['source']==call['output'] and read(terminal['records']['failure'])==terminal['failure'],
        'The retained failed source output or failure record changed')
    _cleanup(read(terminal['records']['failure_cleanup']),[call])
    reconciliation=_reconcile(checked(call['output']),frozen)
    require(reconciliation['original_strict_audit']==read(terminal['records']['source1_audit'])
        and reconciliation['original_strict_audit']['passed'] is False and reconciliation['retained_round_boundary_count']>0,
        'The original false audit must replay exactly; never relabel it passed')
    return ref,terminal,frozen,reconciliation


def _shape(ref,terminal,original,audit_ref):
    return {**deepcopy(original),'kind':KIND,'version':VERSION,'recipe':recipes(),
        'original_preparation':terminal['preparation'],'retained_failed_source':ref,'retained_failed_batch':FAILED_BATCH_REF,
        'source_only_policy':deepcopy(precision.POLICY),'source_only_policy_sha256':POLICY_SHA,
        'reused_source1_call':deepcopy(terminal['actual_calls'][0]),'reused_source1_audit':audit_ref,
        'required_new_native_calls':2,'required_reused_native_calls':1,'E05_E06_grader_changed':False,
        'old_failure_reclassified':False}


def _metadata_prepared(output):
    frozen=read(Path(output)/'preparation.json')
    require(frozen['kind']==KIND and type(frozen['version'])is int and frozen['version']==VERSION,'Use this new source-only precision preparation')
    return frozen


def prepare(failed_source,output):
    output=Path(output).absolute();require(output==output.resolve() and not output.exists(),'Use a fresh revision2 source directory')
    output.mkdir(parents=True);audit=_N['AuditStore'](output/'prepare_audit',{'id':output.name+'-prepare','name':'Source precision v2; reuse one genuine call,0 new calls in prepare','status':'running','qualified':False,'target_count':0})
    server=_N['DashboardServer'](audit.snapshot,audit.events,host='127.0.0.1',port=0);failure=None
    try:
        url=server.start();write(output/'prepare_started.json',{'at':_N['now'](),'pid':_N['os'].getpid(),'dashboard_url':url,'native_calls':0})
        print(json.dumps({'dashboard_url':url,'phase':'source_precision_prepare','pid':_N['os'].getpid()}),flush=True)
        with stage(audit,'genuine_original_source1_and_full_stored_AB_reconciliation'):
            ref,terminal,original,reconciliation=_retained(failed_source)
            audit_ref=write(output/'retained_source1_reconciliation.json',reconciliation)
            return write(output/'preparation.json',_shape(ref,terminal,original,audit_ref))
    except BaseException as error:
        failure={'type':type(error).__name__,'message':str(error)};write(output/'preparation_failure.json',failure);raise
    finally:
        audit.update_run(status='failed' if failure else 'passed',producer_active=False);audit.export();server.stop();audit.db.close()


def validate_prepared(output):
    frozen=_metadata_prepared(output);base._check_refs(frozen)
    ref,terminal,original,reconciliation=_retained(frozen['retained_failed_source'])
    require(read(frozen['reused_source1_audit'])==reconciliation and frozen==_shape(ref,terminal,original,frozen['reused_source1_audit']),
        'The complete original artifacts, policy, code closure or reused-call reconciliation changed')
    return frozen


def execute_prepared(output):
    output=Path(output).absolute();f=_metadata_prepared(output)
    require(not(output/'execution_reserved.json').exists(),'No retries; preserve the first revision2 attempt')
    lease=_N['ProducerLease'](output).acquire();audit=server=pulse=engine=None;stop=threading.Event();calls=[];records={};failure=None;clock=time.monotonic()
    old_tmp=_N['os'].environ.get('TMPDIR');cached_tmp=tempfile.tempdir
    try:
        write(output/'execution_reserved.json',{'at':_N['now'](),'preparation':reference(output/'preparation.json'),'pid':_N['os'].getpid(),'retry':0})
        temporary=output/'temporary';temporary.mkdir();_N['os'].environ['TMPDIR']=str(temporary);tempfile.tempdir=str(temporary)
        audit=_N['AuditStore'](output/'audit',{'id':output.name,'name':'Source precision v2:1 reused +2 fresh native calls','status':'running','qualified':False,'target_count':0,'model_calls':0,'solver_calls':0})
        server=_N['DashboardServer'](audit.snapshot,audit.events,host='127.0.0.1',port=0);url=server.start()
        write(output/'started.json',{'at':_N['now'](),'preparation':reference(output/'preparation.json'),'dashboard_url':url,'pid':_N['os'].getpid(),'retry':0})
        print(json.dumps({'dashboard_url':url,'pid':_N['os'].getpid()}),flush=True)
        def heartbeat():
            while not stop.wait(15):
                audit.update_run(elapsed_seconds=time.monotonic()-clock,reused_native_calls=int(bool(calls)),new_native_calls_started=max(0,len(calls)-1));audit.export()
        pulse=threading.Thread(target=heartbeat,daemon=True);pulse.start()
        with stage(audit,'genuine_reused_source1_cold_replay'):
            f=validate_prepared(output);calls=[deepcopy(f['reused_source1_call'])];records['source1_audit']=f['reused_source1_audit']
            stored=base._stored(f)
        engine=_N['ThreadCappedResourceLibreOfficeEngine'](ROOT,f['runtime_profile']['path'],role='source',receipt_directory=output/'engine_resources')
        with stage(audit,'pinned_native_image_check'):engine.ensure_image()
        previous=calls[0]['output']
        for index,name in enumerate(STAGES[1:],2):
            call={'index':index,'role':name,'input':previous,'started_at':_N['now'](),'completed':False};calls.append(call)
            call['started_receipt']=write(output/(name+'_started.json'),dict(call))
            with stage(audit,name):
                try:
                    tick=time.monotonic();actual=Path(engine.recalculate(checked(previous),output/(name+'.xlsx')))
                    call.update(output=reference(actual),completed=True,elapsed_seconds=time.monotonic()-tick)
                    history=engine.metadata()['actual_resource_receipts'];require(len(history)==index-1,'Exactly two fresh native calls; original source1 is reused')
                    call['actual_resource_evidence']=validate_call(call,history[-1],f)
                finally:
                    call['finished_at']=_N['now']();call['terminal_receipt']=write(output/(name+'_terminal.json'),dict(call))
            with stage(audit,name+'_full_source_only_reconciliation'):
                records[name+'_audit']=write(output/(name+'_audit.json'),_reconcile(actual,f,stored=stored))
            previous=call['output'];print(json.dumps({'actual_call_completed':name,'elapsed_seconds':call['elapsed_seconds'],'new_native_calls':index-1}),flush=True)
        for left,right in zip(calls,calls[1:]):
            key=left['role']+'_to_'+right['role']
            with stage(audit,key+'_strict_typed_stability'):
                report=compare_typed(left['output']['path'],right['output']['path'],read(f['expected']))
                records[key]=write(output/(key+'.json'),{'left':left['output'],'right':right['output'],'comparison':report})
                require(report['passed'] is True,'Both original strict typed stability comparisons remain mandatory')
        with stage(audit,'all_three_owned_containers_absent'):
            clean=owned_absence(calls);records['cleanup']=write(output/'owned_containers_absence.json',clean);_cleanup(clean,calls)
        require(validate_prepared(output)==f,'The full original and revision2 source closure changed')
    except BaseException as error:
        failure={'type':type(error).__name__,'message':str(error)};records['failure']=write(output/'failure.json',failure)
    finally:
        if failure is not None and engine is not None:
            try:
                owned=[]
                for row in engine.metadata()['actual_resource_receipts']:
                    actual=read(row);require(any(actual.get('source')==c['input'] for c in calls[1:]),'Cleanup receipt is not an owned new input')
                    if actual.get('container_id'):owned.append({'actual_resource_evidence':{'container_id':actual['container_id']}})
                if owned:records['failure_cleanup']=write(output/'failure_owned_absence.json',owned_absence(owned))
            except Exception as error:records['failure_cleanup']=write(output/'failure_cleanup_unknown.json',{'state':'unknown','error_type':type(error).__name__})
        stop.set()
        if pulse:pulse.join(timeout=1)
        for close in ((lambda:audit.update_run(status='failed' if failure else 'passed',producer_active=False,elapsed_seconds=time.monotonic()-clock)),
            (lambda:audit.export()),(lambda:server.stop()),(lambda:audit.db.close())):
            try:
                if audit is not None:close()
            except Exception as error:
                if failure is None:failure={'type':type(error).__name__,'message':'Final dashboard/cleanup failed: '+str(error)}
        lease.release()
        if old_tmp is None:_N['os'].environ.pop('TMPDIR',None)
        else:_N['os'].environ['TMPDIR']=old_tmp
        tempfile.tempdir=cached_tmp
    terminal=write(output/'source_manifest.json',{'kind':SOURCE_KIND,'version':VERSION,'passed':failure is None,'failure':failure,
        'preparation':reference(output/'preparation.json'),'source':calls[-1].get('output')if calls else None,
        'specification':f['specification'],'specification_sha256':f['specification_sha256'],'bindings':f['bindings'],'actual_calls':calls,'records':records,
        'actual_LO_calls_started':len(calls),'actual_LO_calls_completed':sum(c['completed']for c in calls),
        'reused_native_calls':int(bool(calls)),'new_native_calls_started':max(0,len(calls)-1),'new_native_calls_completed':sum(c['completed']for c in calls[1:]),
        'cold_start_is_unseeded':True,'memoized_independent_ledgers':True,'new_financial_forwards':0,'policy_sha256':POLICY_SHA,
        'retained_failed_source':f['retained_failed_source'],'old_failure_reclassified':False,'E05_E06_grader_changed':False,
        'model_calls':0,'solver_calls':0,'Harbor_calls':0,'task_count':0,'qualified':False,'normal_all12_QA_passed':False,'difficulty_claimed':False,'retry':0,
        'elapsed_seconds':time.monotonic()-clock})
    if failure is not None:raise RuntimeError('Revision2 source failed; preserve its new terminal without retry')
    return terminal


def validate_source(value):
    terminal=read(value)
    require(terminal['kind']==SOURCE_KIND and type(terminal['version'])is int and terminal['version']==VERSION
        and terminal['passed'] is True and terminal['failure']is None
        and all(type(terminal[k])is int for k in ('actual_LO_calls_started','actual_LO_calls_completed','reused_native_calls','new_native_calls_started','new_native_calls_completed','retry','new_financial_forwards','model_calls','solver_calls','Harbor_calls','task_count'))
        and terminal['actual_LO_calls_started']==terminal['actual_LO_calls_completed']==3
        and terminal['reused_native_calls']==1 and terminal['new_native_calls_started']==terminal['new_native_calls_completed']==2
        and terminal['cold_start_is_unseeded'] is terminal['memoized_independent_ledgers'] is True
        and terminal['old_failure_reclassified'] is terminal['E05_E06_grader_changed'] is terminal['qualified'] is terminal['normal_all12_QA_passed'] is terminal['difficulty_claimed'] is False
        and terminal['retry']==terminal['new_financial_forwards']==terminal['model_calls']==terminal['solver_calls']==terminal['Harbor_calls']==terminal['task_count']==0
        and terminal['policy_sha256']==POLICY_SHA,'A genuine complete1-reused plus2-fresh source revision is required')
    f=validate_prepared(checked(terminal['preparation']).parent);stored=base._stored(f);calls=terminal['actual_calls']
    require(len(calls)==3 and calls[0]==f['reused_source1_call'] and terminal['retained_failed_source']==f['retained_failed_source'],
        'The original completed source1 cannot be replaced or recreated')
    previous=f['cold_start']
    for index,call in enumerate(calls,1):
        _call(call,index,previous,f)
        report=_reconcile(checked(call['output']),f,stored=stored)
        require(read(terminal['records'][STAGES[index-1]+'_audit'])==report,'The complete independent source audit changed')
        previous=call['output']
    for left,right in zip(calls,calls[1:]):
        report=compare_typed(left['output']['path'],right['output']['path'],read(f['expected']))
        require(report['passed'] is True and read(terminal['records'][left['role']+'_to_'+right['role']])==
            {'left':left['output'],'right':right['output'],'comparison':report},'Both full strict typed stabilities must replay')
    _cleanup(read(terminal['records']['cleanup']),calls)
    require(terminal['source']==previous and terminal['specification']==f['specification'] and terminal['specification_sha256']==f['specification_sha256']
        and terminal['bindings']==f['bindings'],'The admitted source output and original facts changed')
    return terminal


validate_completed=validate_source
_N.update(KIND=KIND,SOURCE_KIND=SOURCE_KIND,recipes=recipes,validate_prepared=validate_prepared,validate_source=validate_source,
    execute_prepared=execute_prepared,_metadata_prepared=_metadata_prepared,_crosscheck_prepared=base._crosscheck_prepared)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('failed-source','output','prepared','manifest'):parser.add_argument('--'+name,type=Path)
    parser.add_argument('--run',action='store_true');args=parser.parse_args(argv)
    if args.manifest:
        require(not any((args.failed_source,args.output,args.prepared,args.run)),'Validate one new complete source manifest');result=validate_source(args.manifest)
    elif args.prepared:
        require(not any((args.failed_source,args.output)),'Use the exact frozen new preparation');result=execute_prepared(args.prepared)if args.run else validate_prepared(args.prepared)
    else:
        require(args.failed_source and args.output,'Supply an original failed source manifest and fresh output');result=prepare(args.failed_source,args.output)
        if args.run:result=execute_prepared(args.output)
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
