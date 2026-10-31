#!/usr/bin/env python3
"""Prepare, then explicitly execute ten shared engineering calculations, not QA."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import date,datetime,timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import openpyxl
import yaml
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.workbook.thread_capped_resource_engine import ThreadCappedResourceLibreOfficeEngine,validate_capped_call
from sheets_factory.workbook.heterogeneous_contracts.validate import compare_typed_caches
from sheets_factory.workbook.linear_capital_portfolio.formula_identity import formula_signature
from sheets_factory.evaluation.streaming_verifier import compare_files
from sheets_factory.workbook.period_boundary_portfolio import spec,oracle,excel

PROFILE=ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'
IMAGE='sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
KIND='prepared_period_boundary_shared_engineering'
STAGES=('goal1','goal2','FM_input1','FM_input2','DBG_input1','DBG_input2','equivalent','FM_missed_root','DBG_missed_root','extra_change')
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def require(ok,message):
    if not ok:raise ValueError(message)


def now():return datetime.now(timezone.utc).isoformat()


def reference(path):
    p=Path(path).absolute();require(p==p.resolve() and p.is_file(),'Use a regular, real file')
    h=hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024**2),b''):h.update(block)
    return {'path':str(p),'sha256':h.hexdigest(),'bytes':p.stat().st_size}


def checked(value):
    require(reference(value['path'])==value,'Frozen reference changed');return Path(value['path'])


def read(value):return json.loads((checked(value) if isinstance(value,dict) else Path(value)).read_text())


def write(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as f:json.dump(value,f,indent=2,allow_nan=False,default=lambda x:x.isoformat() if isinstance(x,(date,datetime)) else str(x));f.write('\n')
    return reference(p)


def load(path,name):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def builder():return load(ROOT/'scripts/build_period_boundary_candidate.py','_period_candidate_builder')


def resource_support():return load(ROOT/'scripts/build_heterogeneous_source.py','_period_resource_support')


def recipes():
    from sheets_factory.workbook import resource_engine,thread_capped_resource_engine,engine
    from sheets_factory.evaluation import streaming_verifier
    from sheets_factory.workbook.heterogeneous_contracts import validate
    from sheets_factory.workbook.linear_capital_portfolio import formula_identity
    from sheets_factory.task_adapters import heterogeneous_formula_identity
    from sheets_factory.core import audit
    from sheets_factory.dashboard import server
    from sheets_factory import resume
    modules=[spec,oracle,excel,resource_engine,thread_capped_resource_engine,engine,streaming_verifier,validate,
        formula_identity,heterogeneous_formula_identity,audit,server,resume]
    paths=[Path(__file__),PROFILE,ROOT/'scripts/build_period_boundary_candidate.py',ROOT/'scripts/build_heterogeneous_source.py',
        ROOT/'src/sheets_factory/workbook/period_boundary_portfolio/__init__.py',
        ROOT/'src/sheets_factory/workbook/uno_recalculate.py',*[Path(m.__file__) for m in modules]]
    return {str(p.resolve()):reference(p) for p in paths}


def typed(value):
    if value is None or value=='':return ('empty',None)
    if type(value) is bool:return ('boolean',value)
    if isinstance(value,(date,datetime)):
        if isinstance(value,datetime):require(value.time().isoformat()=='00:00:00','A date contains a time component')
        return ('date',value.isoformat()[:10])
    if type(value) in (int,float):return ('number',Decimal(str(value)))
    return ('text',value)


def literal_inventory(path,bindings):
    points={(b['sheet'],b['cell']) for b in bindings['derived']};book=openpyxl.load_workbook(path,data_only=False)
    try:return {(s.title,c.coordinate):typed(c.value) for s in book for c in s._cells.values() if (s.title,c.coordinate) not in points and c.value is not None}
    finally:book.close()


def audit_workbook(path,bindings,result,raw_literals,*,blank_derived=False):
    expected=builder().expected_values(bindings,result);f=openpyxl.load_workbook(path,data_only=False);v=openpyxl.load_workbook(path,data_only=True)
    problems=[];native_errors=[];points=set(expected);definitions={(b['sheet'],b['cell']):b for b in bindings['derived']}
    try:
        require(f.sheetnames==v.sheetnames==bindings['sheetnames'],'Worksheet order changed')
        actual_formulas={(s.title,c.coordinate):c.value for s in f for c in s._cells.values() if c.data_type=='f'}
        expected_formulas={} if blank_derived else {p:b['formula'] for p,b in definitions.items()}
        require(set(actual_formulas)==set(expected_formulas) and all(formula_signature(actual_formulas[p])==formula_signature(text) for p,text in expected_formulas.items()),'Complete formula scope or lexical definitions changed')
        for point,wanted in expected.items():
            actual=v[point[0]][point[1]].value;kind=definitions[point]['kind']
            if blank_derived:matches=actual is None
            elif kind=='date':matches=typed(actual)==('date',wanted.isoformat())
            elif kind=='money_pence':matches=type(actual) in (int,float) and Decimal(str(actual))*100==wanted
            else:matches=type(actual) is int and actual==wanted
            if not matches:problems.append({'sheet':point[0],'cell':point[1],'kind':kind,'expected':None if blank_derived else wanted,'actual':actual})
        observed={}
        for s in v:
            for c in s._cells.values():
                if c.data_type=='e':native_errors.append([s.title,c.coordinate,c.value])
                if c.value is not None:observed[s.title,c.coordinate]=typed(c.value)
        expected_nonempty=set(raw_literals) | (set() if blank_derived else points)
        require(set(observed)==expected_nonempty,'Nonempty scope has extra or missing public/derived cells')
        for point,wanted in raw_literals.items():
            if observed.get(point)!=wanted:problems.append({'sheet':point[0],'cell':point[1],'claim':'Provided literal, date, unit or policy changed'})
        return {'kind':'complete_period_boundary_independent_oracle_cache_audit','passed':not problems and not native_errors,
            'workbook':reference(path),'all_derived_values_checked':len(expected),'formula_count':len(actual_formulas),
            'public_literals_checked':len(raw_literals),'mismatches':problems,'native_errors':native_errors,
            'money_equality':'exact_decimal_pence_without_tolerance','oracle_did_not_execute_workbook_formulas':True,'qualified':False}
    finally:f.close();v.close()


def patch_cells(source,destination,changes):
    """Edit selected cell XML only; unedited member/cell bytes remain intact."""
    with zipfile.ZipFile(source) as zin:
        wb=ET.fromstring(zin.read('xl/workbook.xml'));rels=ET.fromstring(zin.read('xl/_rels/workbook.xml.rels'))
        targets={r.get('Id'):r.get('Target') for r in rels};sheets={}
        for s in wb.find('{'+NS+'}sheets'):
            target=targets[s.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')]
            sheets[s.get('name')]=target.lstrip('/') if target.startswith('/') else 'xl/'+target
        by_member={sheets[s]:{} for s,c in changes}
        for (s,c),value in changes.items():by_member[sheets[s]][c]=value
        touched=[]
        with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                raw=zin.read(item.filename);before=raw
                for coord,(kind,value) in by_member.get(item.filename,{}).items():
                    pattern=rb'<(?P<pre>(?:[A-Za-z_][\w.-]*:)?)c\b(?=[^>]*\br="'+coord.encode()+rb'")[^>]*?(?:/>|>.*?</(?P=pre)c>)'
                    matches=list(re.finditer(pattern,raw,re.S));require(len(matches)==1,'Control cell must exist exactly once')
                    match=matches[0];old=match.group();prefix=match.group('pre');opening=old[:old.index(b'>')+1].replace(b'/>',b'>')
                    opening=re.sub(rb'\s+t="[^"]*"',b'',opening)
                    if kind=='formula':body=b'<'+prefix+b'f>'+escape(value.lstrip('=')).encode()+b'</'+prefix+b'f><'+prefix+b'v></'+prefix+b'v>'
                    elif kind=='blank':body=b''
                    elif kind=='text':
                        opening=opening[:-1]+b' t="inlineStr">';body=b'<'+prefix+b'is><'+prefix+b't>'+escape(value).encode()+b'</'+prefix+b't></'+prefix+b'is>'
                    else:raise ValueError('Unsupported control edit')
                    replacement=opening+body+b'</'+prefix+b'c>';raw=raw[:match.start()]+replacement+raw[match.end():]
                if raw!=before:touched.append(item.filename)
                zout.writestr(item,raw)
    return {'source':reference(source),'output':reference(destination),'changed_members':touched,
        'exact_cell_changes':[{'sheet':s,'cell':c,'kind':v[0],'value':v[1]} for (s,c),v in changes.items()],
        'all_other_member_and_unedited_cell_bytes_preserved':True,'actual_recalculation_performed':False}


def prepare(candidate_manifest,output):
    output=Path(output).absolute();require(output==output.resolve() and not output.exists(),'Use a fresh engineering directory')
    m=read(candidate_manifest);require(m['kind']=='offline_synthetic_period_boundary_candidate' and m['version']==1 and not m['qualified'],'Use this distinct unqualified synthetic candidate')
    for r in m['recipe'].values():checked(r)
    require(m['recipe']==builder().recipes(),'Candidate financial/emitter recipe changed')
    public=spec.load_spec(checked(m['source_specification']));parent=checked(candidate_manifest).parent if isinstance(candidate_manifest,dict) else Path(candidate_manifest).resolve().parent
    bindings=read(parent/'bindings.private.json');plan=read(m['plan'])
    correct=oracle.simulate(public);wrong=oracle.simulate(public,faults=spec.FAULTS)
    profile=yaml.safe_load(PROFILE.read_text());require(profile['image']['id']==IMAGE and profile['docker_resources']['source']=={'cpus':2,'memory_bytes':34359738368,'pids_limit':256} and profile['timeouts']['workbook_file_seconds']==600,'Pinned 2CPU32GiB source profile required')
    raw_literals=literal_inventory(checked(m['gold']),bindings)
    wrong_bindings=json.loads(json.dumps(bindings));by={(x['sheet'],x['cell']):x for x in wrong_bindings['derived']}
    for edit in plan['DBG_formula_edits']:by[edit['sheet'],edit['cell']]['formula']=edit['before']
    for label,b,result,blank in [('gold',bindings,correct,False),('FM_input',bindings,correct,True),('DBG_input',wrong_bindings,wrong,False)]:
        report=audit_workbook(checked(m[label]),b,result,raw_literals,blank_derived=blank)
        require(report['passed'],'Offline candidate cache/formula/primitive integrity failed')
    output.mkdir(parents=True);p=output/'planned';p.mkdir();control_edits=[]
    points={'goal':m['gold'],'FM_input':m['FM_input'],'DBG_input':m['DBG_input']}
    for key,r in points.items():shutil.copyfile(checked(r),p/(key+'.xlsx'))
    equity=next(b for b in bindings['derived'] if b['expected_path']==['valuation','equity_value_pence'])
    maturity_point=next((b['sheet'],b['cell']) for b in bindings['derived'] if b['expected_path'][0]=='facilities'
        and b['expected_path'][-1]=='accrual_days'
        and 0<correct['facilities'][b['expected_path'][1]][b['expected_path'][2]]['accrual_days']<correct['periods'][b['expected_path'][2]]['days'])
    clipped=next(e for e in plan['DBG_formula_edits'] if (e['sheet'],e['cell'])==maturity_point)
    cases={'equivalent':{(equity['sheet'],equity['cell']):('formula','0+'+equity['formula'].lstrip('='))},
        'FM_missed_root':{(equity['sheet'],equity['cell']):('blank',None)},
        'DBG_missed_root':{(clipped['sheet'],clipped['cell']):('formula',clipped['before'])},
        'extra_change':{('Business Policies','A1'):('text','Synthetic financial forecast — business policies [control]')}}
    for name,edits in cases.items():control_edits.append(patch_cells(p/'goal.xlsx',p/(name+'.xlsx'),edits))
    planned={key:reference(p/(key+'.xlsx')) for key in [*points,*cases]}
    stage_inputs={}
    for stage in STAGES:stage_inputs[stage]=planned['goal'] if stage=='goal1' else 'goal1' if stage=='goal2' else planned[stage[:-1]] if stage in ['FM_input1','DBG_input1'] else stage[:-1]+'1' if stage in ['FM_input2','DBG_input2'] else planned[stage]
    return write(output/'preparation.json',{'kind':KIND,'version':1,'candidate_manifest':reference(candidate_manifest['path'] if isinstance(candidate_manifest,dict) else candidate_manifest),
        'candidate_bindings':reference(parent/'bindings.private.json'),'runtime_profile':reference(PROFILE),'runtime_profile_value':profile,
        'recipe':recipes(),'mode_order':['financial_modeling','debugging'],'stage_order':list(STAGES),'planned_inputs':planned,
        'stage_inputs':stage_inputs,'control_edits':control_edits,'shared_goal_and_equivalent_and_extra_change_explicit':True,
        'required_actual_LO_calls':10,'expected_FM_D':m['FM_D_count'],'expected_DBG_D':m['DBG_D_count'],
        'all_mode_and_control_plans_frozen_before_first_actual_call':True,'actual_LO_calls':0,'model_calls':0,'solver_calls':0,'Harbor_calls':0,'qualified':False})


def validate_prepared(output):
    f=read(Path(output)/'preparation.json');require(f['kind']==KIND and f['version']==1 and f['recipe']==recipes() and f['stage_order']==list(STAGES) and f['required_actual_LO_calls']==10,'Prepared recipe or stage order changed')
    checked(f['candidate_manifest']);checked(f['candidate_bindings']);checked(f['runtime_profile'])
    for r in f['planned_inputs'].values():checked(r)
    return f


def validate_call(call,runtime,frozen):
    return validate_capped_call(call,runtime,frozen,resource_validator=resource_support().validate_actual_call)


def owned_absence(calls):
    ids=[c['actual_resource_evidence']['container_id'] for c in calls];require(len(ids)==len(set(ids)) and all(re.fullmatch('[0-9a-f]{64}',x) for x in ids),'Distinct full owned IDs required')
    rows=[]
    for cid in ids:
        p=subprocess.run(['docker','inspect',cid,'--format','{{.Id}}'],capture_output=True,text=True,timeout=15)
        rows.append({'full_id':cid,'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'absent':p.returncode==1 and not p.stdout.strip() and ('No such object' in p.stderr or 'No such container' in p.stderr)})
    daemon=subprocess.run(['docker','version','--format','{{.Server.Version}}'],capture_output=True,text=True,timeout=15)
    return {'all_owned_containers_absent':all(x['absent'] for x in rows),'daemon_reachable':daemon.returncode==0 and bool(daemon.stdout.strip()),'owned':rows,'daemon_version':daemon.stdout.strip(),'cleanup_mutations_by_validator':False}


@contextmanager
def stage(audit,name):
    start=time.monotonic();r=audit.record('nodes',{'node':name,'status':'running','started_at':now()});audit.update_run(active_stage=name);audit.export();status='failed'
    try:yield;status='completed'
    finally:audit.update_record('nodes',r,{'status':status,'finished_at':now(),'duration_ms':1000*(time.monotonic()-start)});audit.export()


def execute_prepared(output):
    output=Path(output).absolute();f=validate_prepared(output);require(not (output/'started.json').exists(),'No retries; preserve the first attempt')
    lease=ProducerLease(output).acquire();audit=server=heartbeat=None;calls=[];results={};records={};stop=threading.Event();clock=time.monotonic()
    old_tmp=os.environ.get('TMPDIR');old_cache=tempfile.tempdir;tmp=output/'temporary';tmp.mkdir();os.environ['TMPDIR']=str(tmp);tempfile.tempdir=str(tmp)
    status='failed';failure=None;engine=None
    try:
        audit=AuditStore(output/'audit',{'id':output.name,'name':'Period-boundary shared engineering','status':'running','target_count':0,'qualified':False,'producer_pid':os.getpid()})
        server=DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=0);url=server.start()
        records['started']=write(output/'started.json',{'at':now(),'preparation':reference(output/'preparation.json'),'dashboard_url':url,'pid':os.getpid(),'retry':0})
        print(json.dumps({'dashboard_url':url,'pid':os.getpid(),'started':records['started']}),flush=True)
        def pulse():
            while not stop.wait(15):audit.update_run(elapsed_seconds=time.monotonic()-clock,actual_LO_calls_started=len(calls),actual_LO_calls_completed=sum(c['completed'] for c in calls));audit.export()
        heartbeat=threading.Thread(target=pulse,daemon=True);heartbeat.start()
        m=read(f['candidate_manifest']);public=spec.load_spec(checked(m['source_specification']));bindings=read(f['candidate_bindings']);correct=oracle.simulate(public);wrong=oracle.simulate(public,faults=spec.FAULTS)
        literals=literal_inventory(checked(m['gold']),bindings);wrong_bindings=json.loads(json.dumps(bindings));by={(b['sheet'],b['cell']):b for b in wrong_bindings['derived']}
        for e in read(m['plan'])['DBG_formula_edits']:by[e['sheet'],e['cell']]['formula']=e['before']
        engine=ThreadCappedResourceLibreOfficeEngine(ROOT,f['runtime_profile']['path'],role='source',receipt_directory=output/'engine_resources');engine.ensure_image()
        for index,name in enumerate(STAGES,1):
            source=f['stage_inputs'][name];source=Path(results[source]['path']) if isinstance(source,str) else checked(source);destination=output/(name+'.xlsx')
            call={'index':index,'role':name,'input':reference(source),'started_at':now(),'completed':False};calls.append(call);call['started_receipt']=write(output/(name+'_started.json'),dict(call))
            with stage(audit,'actual_'+name):
                try:
                    tick=time.monotonic();actual=Path(engine.recalculate(source,destination));call.update(output=reference(actual),completed=True,elapsed_seconds=time.monotonic()-tick)
                    history=engine.metadata()['actual_resource_receipts'];require(len(history)==index,'An extra or missing actual call occurred')
                    call['actual_resource_evidence']=validate_call(call,history[-1],f)
                finally:call['finished_at']=now();call['terminal_receipt']=write(output/(name+'_terminal.json'),dict(call))
            results[name]=call['output']
            print(json.dumps({'actual_call_completed':name,'completed_calls':index,'elapsed_seconds':call['elapsed_seconds'],'output_sha256':call['output']['sha256']}),flush=True)
            if name in ['goal1','goal2','FM_input1','FM_input2','DBG_input1','DBG_input2','equivalent']:
                b=wrong_bindings if name.startswith('DBG_input') else bindings;r=wrong if name.startswith('DBG_input') else correct
                if name=='equivalent':
                    b=json.loads(json.dumps(bindings));equity=next(x for x in b['derived'] if x['expected_path']==['valuation','equity_value_pence']);equity['formula']='=0+'+equity['formula'].lstrip('=')
                report=audit_workbook(actual,b,r,literals,blank_derived=name.startswith('FM_input'))
                records[name+'_audit']=write(output/(name+'_audit.json'),report);require(report['passed'],'Independent complete financial/date/literal cache audit failed')
        for label,left,right in [('goal','goal1','goal2'),('FM','FM_input1','FM_input2'),('DBG','DBG_input1','DBG_input2')]:
            comparison=compare_typed_caches(results[left]['path'],results[right]['path']);records[label+'_stability']=write(output/(label+'_stability.json'),{'left':results[left],'right':results[right],'comparison':comparison})
            require(comparison['passed'] and comparison['typed_value_mismatches']==0,'Typed fixed point failed')
        modes={}
        for mode,prefix in [('financial_modeling','FM'),('debugging','DBG')]:
            scores={};proofs={};input=results[prefix+'_input2'];goal=results['goal2']
            for control,key in [('oracle','goal2'),('nop',prefix+'_input2'),('equivalent','equivalent'),('missed_root',prefix+'_missed_root'),('extra_change','extra_change')]:
                result=compare_files(input['path'],goal['path'],results[key]['path']);proofs[control]=write(output/(prefix+'_'+control+'_full_D.json'),{'input':input,'goal':goal,'output':results[key],'comparison':result});scores[control]=result['reward']
                require(result['expected_change_count']==f['expected_'+prefix+'_D'],'Actual complete D differs from the independent prepared plan')
            require(scores=={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0},'Actual five-control pattern failed')
            modes[mode]={'controls':scores,'full_D_controls':proofs,'complete_D_count':f['expected_'+prefix+'_D'],'input':input,'goal':goal}
        records['cleanup']=write(output/'owned_containers_absence.json',owned_absence(calls));cleanup=read(records['cleanup'])
        require(cleanup['all_owned_containers_absent'] and cleanup['daemon_reachable'],'Owned cleanup is incomplete or unknown')
        require(validate_prepared(output)==f and len(calls)==10,'Recipe changed or call count differs')
        records['modes']=modes;status='passed'
    except BaseException as error:
        failure={'type':type(error).__name__,'message':str(error)}
        records['failure']=write(output/'failure.json',failure)
    finally:
        if status!='passed' and engine is not None and calls:
            try:
                owned=[]
                for runtime in engine.metadata()['actual_resource_receipts']:
                    actual=read(runtime)
                    require(any(actual.get('source')==c['input'] for c in calls),'Failure cleanup identity is not an owned call')
                    cid=actual.get('container_id')
                    if cid:owned.append({'actual_resource_evidence':{'container_id':cid}})
                if owned:records['failure_cleanup']=write(output/'owned_containers_absence_after_failure.json',owned_absence(owned))
            except Exception as error:
                records['failure_cleanup']=write(output/'owned_cleanup_unknown.json',{'passed':False,'state':'unknown','error_type':type(error).__name__})
        stop.set()
        if heartbeat:heartbeat.join(timeout=1)
        if audit:audit.update_run(status=status,producer_active=False,elapsed_seconds=time.monotonic()-clock);audit.export()
        if server:server.stop()
        if audit:audit.db.close()
        lease.release()
        if old_tmp is None:os.environ.pop('TMPDIR',None)
        else:os.environ['TMPDIR']=old_tmp
        tempfile.tempdir=old_cache
    terminal=write(output/'terminal.json',{'kind':'period_boundary_actual_shared_engineering_validation','version':1,'passed':status=='passed','failure':failure,
        'preparation':reference(output/'preparation.json'),'actual_calls':calls,'records':records,'actual_LO_calls_started':len(calls),'actual_LO_calls_completed':sum(c['completed'] for c in calls),
        'elapsed_seconds':time.monotonic()-clock,'model_calls':0,'solver_calls':0,'Harbor_calls':0,'task_count':0,'qualified':False,'normal_all12_QA_passed':False,'difficulty_claimed':False,'retry':0})
    if status!='passed':raise RuntimeError('Engineering failed; preserve terminal.json without retry')
    return terminal


def validate_completed(value):
    """Cold-check this exact actual attempt without services or recalculation."""
    terminal=read(value);require(terminal['kind']=='period_boundary_actual_shared_engineering_validation' and terminal['version']==1
        and terminal['passed'] is True and terminal['failure'] is None and terminal['actual_LO_calls_started']==terminal['actual_LO_calls_completed']==10
        and terminal['qualified'] is False and terminal['normal_all12_QA_passed'] is False and terminal['difficulty_claimed'] is False
        and terminal['model_calls']==terminal['solver_calls']==terminal['Harbor_calls']==terminal['retry']==0,
        'A complete, original ten-call engineering attempt is required')
    p=checked(terminal['preparation']).parent;f=validate_prepared(p);results={};calls=terminal['actual_calls'];require(len(calls)==10,'Complete actual call inventory required')
    m=read(f['candidate_manifest']);public=spec.load_spec(checked(m['source_specification']));bindings=read(f['candidate_bindings'])
    correct=oracle.simulate(public);wrong=oracle.simulate(public,faults=spec.FAULTS);literals=literal_inventory(checked(m['gold']),bindings)
    wrong_bindings=json.loads(json.dumps(bindings));by={(b['sheet'],b['cell']):b for b in wrong_bindings['derived']}
    for e in read(m['plan'])['DBG_formula_edits']:by[e['sheet'],e['cell']]['formula']=e['before']
    for index,(name,call) in enumerate(zip(STAGES,calls,strict=True),1):
        source=f['stage_inputs'][name];source=results[source] if isinstance(source,str) else source
        require(call['index']==index and call['role']==name and call['input']==source and call['completed'] is True,'Actual stage order or input/output chain differs')
        checked(call['input']);checked(call['output']);saved=read(call['terminal_receipt'])
        require(saved=={k:v for k,v in call.items() if k!='terminal_receipt'},'The original call terminal changed')
        require(validate_call(call,call['actual_resource_evidence']['terminal'],f)==call['actual_resource_evidence'],'Complete actual resources/cap evidence changed')
        results[name]=call['output']
        if name in ['goal1','goal2','FM_input1','FM_input2','DBG_input1','DBG_input2','equivalent']:
            b=wrong_bindings if name.startswith('DBG_input') else bindings;r=wrong if name.startswith('DBG_input') else correct
            if name=='equivalent':
                b=json.loads(json.dumps(bindings));e=next(x for x in b['derived'] if x['expected_path']==['valuation','equity_value_pence']);e['formula']='=0+'+e['formula'].lstrip('=')
            actual=audit_workbook(call['output']['path'],b,r,literals,blank_derived=name.startswith('FM_input'))
            require(actual['passed'] and read(terminal['records'][name+'_audit'])==actual,'Complete independent financial/date audit no longer agrees')
    for label,left,right in [('goal','goal1','goal2'),('FM','FM_input1','FM_input2'),('DBG','DBG_input1','DBG_input2')]:
        old=read(terminal['records'][label+'_stability']);current=compare_typed_caches(results[left]['path'],results[right]['path'])
        require(current['passed'] and old=={'left':results[left],'right':results[right],'comparison':current},'Typed fixed-point evidence changed')
    for mode,prefix in [('financial_modeling','FM'),('debugging','DBG')]:
        proof=terminal['records']['modes'][mode];scores={}
        require(proof['input']==results[prefix+'_input2'] and proof['goal']==results['goal2'],'Mode evidence is bound to another physical pair')
        for control,key in [('oracle','goal2'),('nop',prefix+'_input2'),('equivalent','equivalent'),('missed_root',prefix+'_missed_root'),('extra_change','extra_change')]:
            result=compare_files(proof['input']['path'],proof['goal']['path'],results[key]['path']);saved=read(proof['full_D_controls'][control])
            require(saved=={'input':proof['input'],'goal':proof['goal'],'output':results[key],'comparison':result}
                and result['expected_change_count']==f['expected_'+prefix+'_D'],'Complete D/control evidence changed')
            scores[control]=result['reward']
        require(scores==proof['controls']=={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0},'Five controls are not complete')
    cleanup=read(terminal['records']['cleanup']);require(cleanup['all_owned_containers_absent'] and cleanup['daemon_reachable']
        and len(cleanup['owned'])==10 and {x['full_id'] for x in cleanup['owned']}=={c['actual_resource_evidence']['container_id'] for c in calls}
        and all(x['absent'] for x in cleanup['owned']),'Cleanup observations do not cover the actual ten owned IDs')
    return terminal


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--candidate',type=Path);p.add_argument('--output',type=Path);p.add_argument('--prepared',type=Path);p.add_argument('--run',action='store_true');a=p.parse_args()
    if a.prepared:require(a.candidate is None and a.output is None,'Keep the existing frozen preparation');r=execute_prepared(a.prepared) if a.run else validate_prepared(a.prepared)
    else:
        require(a.candidate is not None and a.output is not None,'Supply candidate and fresh output');r=prepare(a.candidate,a.output)
        if a.run:r=execute_prepared(a.output)
    print(json.dumps(r));return 0


if __name__=='__main__':raise SystemExit(main())
