#!/usr/bin/env python3
"""Cold-start three actual iterative source calculations, never task QA or models."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import openpyxl
import yaml
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.workbook.thread_capped_resource_engine import ThreadCappedResourceLibreOfficeEngine,validate_capped_call
from sheets_factory.workbook.linear_capital_portfolio.formula_identity import formula_signature
from sheets_factory.workbook.equity_income_group import spec,decimal_oracle,fraction_oracle,excel

KIND='prepared_equity_income_group_cold_start_source'
SOURCE_KIND='independently_checked_equity_income_group_iterative_source'
PROFILE=ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'
IMAGE='sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
STAGES=('source1','source2','source3')
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'

def require(ok,message):
    if not ok:raise ValueError(message)

def now():return datetime.now(timezone.utc).isoformat()

def reference(path):
    p=Path(path).absolute();require(p==p.resolve() and p.is_file(),'Use a real regular file')
    h=hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024**2),b''):h.update(block)
    return {'path':str(p),'sha256':h.hexdigest(),'bytes':p.stat().st_size}

def checked(value):
    require(reference(value['path'])==value,'Frozen reference changed');return Path(value['path'])

def read(value):return json.loads((checked(value) if isinstance(value,dict) else Path(value)).read_text())

def write(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as stream:json.dump(value,stream,indent=2,allow_nan=False);stream.write('\n')
    return reference(p)

def resource_support():
    p=ROOT/'scripts/build_heterogeneous_source.py';s=importlib.util.spec_from_file_location('_equity_group_resource_support',p)
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def recipes():
    from sheets_factory.workbook import resource_engine,thread_capped_resource_engine,engine
    from sheets_factory.workbook.linear_capital_portfolio import formula_identity
    from sheets_factory.task_adapters import heterogeneous_formula_identity
    from sheets_factory.core import audit
    from sheets_factory.dashboard import server
    from sheets_factory import resume
    modules=(spec,decimal_oracle,fraction_oracle,excel,resource_engine,thread_capped_resource_engine,
             engine,formula_identity,heterogeneous_formula_identity,audit,server,resume)
    paths=[Path(__file__),PROFILE,ROOT/'scripts/build_heterogeneous_source.py',
           ROOT/'src/sheets_factory/workbook/uno_recalculate.py',*[Path(m.__file__) for m in modules]]
    return {str(p.resolve()):reference(p) for p in paths}

def runtime(path):
    r=reference(path);p=yaml.safe_load(checked(r).read_text())
    require(p['id']=='entity_group_large_v2' and p['image']['id']==IMAGE
        and all(p['docker_resources'][role]=={'cpus':2,'memory_bytes':32*1024**3,'pids_limit':256} for role in ('source','agent','verifier'))
        and p['timeouts']['workbook_file_seconds']==600,'Require the pinned 2CPU32GiB/PID256/600-second profile')
    return r,p

def typed(value,*,financial=False):
    if value is None or value=='':return {'type':'empty','value':''}
    if type(value) is bool:return {'type':'boolean','value':value}
    if type(value) in (int,float):
        require(math.isfinite(value),'Nonfinite native number')
        number=Decimal(str(value))
        if financial:number=number.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
        return {'type':'number','value':'0' if not number else format(number.normalize(),'f')}
    require(type(value) is str,'Unsupported workbook value type')
    return {'type':'text','value':value}

def crosscheck(public,bindings):
    """Call independent A and B only through their frozen public solve APIs."""
    a,b=decimal_oracle.solve(public),fraction_oracle.solve(public)
    ids=[e['id'] for e in public['entities']];sids=[s['id'] for s in public['scenarios']];periods=public['periods']
    for result in (a,b):
        require(result['specification_sha256']==spec.canonical_sha256(public) and result['entity_order']==ids
            and result['scenario_order']==sids and result['period_order']==periods,'Complete independent result identity changed')
    lookup={};all_fields=0
    for sa,sb in zip(a['scenarios'],b['scenarios'],strict=True):
        require(sa['id']==sb['id'] and len(sa['periods'])==len(sb['periods'])==len(periods),'Scenario/period coverage changed')
        for qa,qb in zip(sa['periods'],sb['periods'],strict=True):
            require(qa['period']==qb['period'] and set(qa['entities'])==set(qb['entities'])==set(ids),'Independent entity coverage changed')
            for eid in [*ids,None]:
                left=qa['entities'][eid] if eid is not None else qa['group'];right=qb['entities'][eid] if eid is not None else qb['group']
                fields=spec.ENTITY_METRICS if eid is not None else spec.GROUP_METRICS
                require(set(left)==set(right)==set(fields),'Complete financial field coverage required')
                for field in fields:
                    va=Decimal(decimal_oracle.display(left[field]));vb=Decimal(fraction_oracle.display(right[field]))
                    require(va==vb,'The independent Decimal/Fraction financial results disagree')
                    lookup[sa['id'],qa['period'],eid,field]={'type':'number','value':'0' if not vb else format(vb.normalize(),'f')};all_fields+=1
    expected={}
    for row in bindings['bindings']:
        point=row['sheet']+'!'+row['cell'];key=row['scenario'],row['period'],row['entity'],row['metric']
        require(point not in expected and (row['entity'] is None or row['metric'] not in spec.INPUT_FIELDS),
            'Duplicated or non-derived financial binding')
        expected[point]=lookup[key]
    n,q,z=len(ids),len(periods),len(sids)
    require(len(expected)==z*q*((len(spec.ENTITY_METRICS)-len(spec.INPUT_FIELDS))*n+len(spec.GROUP_METRICS))
        and all_fields==z*q*(len(spec.ENTITY_METRICS)*n+len(spec.GROUP_METRICS)),'The whole financial scope must be checked')
    return expected,{'kind':'complete_independent_equity_income_financial_comparison','passed':True,
        'complete_AB_financial_fields':all_fields,'derived_financial_bindings':len(expected),'provided_operating_input_fields':z*q*n*len(spec.INPUT_FIELDS),
        'rounding':'display-only exact half-up two decimals; internal state unrounded','shared_financial_implementation':False,'qualified':False}

def _book(path):return openpyxl.load_workbook(path,data_only=False)

def source_definition(path,bindings,public):
    book=_book(path);points={r['sheet']+'!'+r['cell'] for r in bindings['bindings']};formulas={};literals={}
    try:
        require([book['Read Me'].cell(i+2,1).value for i in range(len(spec.POLICY))]==list(spec.POLICY),'The public business policies differ')
        require(book.calculation.iterate is True and book.calculation.iterateCount==excel.ITERATIONS
            and book.calculation.iterateDelta==excel.ITERATION_DELTA,'Explicit native iteration settings required')
        for sheet in book:
            for cell in sheet._cells.values():
                point=sheet.title+'!'+cell.coordinate
                if cell.data_type=='f':formulas[point]=cell.value
                elif cell.value is not None:literals[point]=typed(cell.value)
        require(set(formulas)==points and all(len(f)<=8192 for f in formulas.values()),'Complete bounded formula scope differs from bindings')
        inputs={};anchors={}
        for binding in bindings['bindings']:
            if binding['entity'] is None:continue
            cell=book[binding['sheet']][binding['cell']]
            key=binding['scenario'],binding['period'],binding['entity']
            anchor=(binding['sheet'],cell.column,cell.row-spec.ENTITY_METRICS.index(binding['metric']))
            require(key not in anchors or anchors[key]==anchor,'Entity financial row mapping is inconsistent')
            anchors[key]=anchor
        for scenario in public['scenarios']:
            for q,period in enumerate(public['periods']):
                for entity in public['entities']:
                    sheet,col,base=anchors[scenario['id'],period,entity['id']]
                    for metric in spec.INPUT_FIELDS:
                        cell=book[sheet].cell(base+spec.ENTITY_METRICS.index(metric),col)
                        wanted=Decimal(scenario['inputs'][entity['id']][q][metric]).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
                        key=sheet+'!'+cell.coordinate
                        inputs[key]={'type':'number','value':'0' if not wanted else format(wanted.normalize(),'f')}
                        require(typed(cell.value,financial=True)==inputs[key],'A supplied operating field differs from the public specification')
        return {'sheetnames':book.sheetnames,'formulas':formulas,'literals':literals,
                'provided_financial_inputs':inputs,
                'iteration_settings':{'enabled':True,'count':excel.ITERATIONS,'delta':excel.ITERATION_DELTA}}
    finally:book.close()

def clear_all_formula_caches(source,destination):
    """Remove every formula cache, preserving formulas/literals/styles and other ZIP members."""
    count=0;changed=[]
    with ZipFile(source) as original,ZipFile(destination,'x',ZIP_DEFLATED) as output:
        for item in original.infolist():
            raw=original.read(item.filename)
            if re.fullmatch(r'xl/worksheets/sheet\d+\.xml',item.filename):
                def clear(match):
                    nonlocal count
                    cell=match.group()
                    if re.search(rb'<(?:\w+:)?f(?:\s|>)',cell):
                        count+=1
                        return re.sub(rb'<(?P<p>(?:\w+:)?)v\b[^>]*(?:/>|>.*?</(?P=p)v>)',b'',cell,flags=re.S)
                    return cell
                before=raw;raw=re.sub(rb'<(?P<p>(?:\w+:)?)c\b[^>]*?(?:/>|>.*?</(?P=p)c>)',clear,raw,flags=re.S)
                if raw!=before:changed.append(item.filename)
            output.writestr(item,raw)
    return {'source':reference(source),'output':reference(destination),'all_formula_caches_cleared':count,
            'changed_members':changed,'financial_formula_or_literal_edits':0,'oracle_seeded_cache_is_not_native_evidence':True}

def audit_workbook(path,definition,expected,*,empty_caches=False):
    f=_book(path);v=openpyxl.load_workbook(path,data_only=True);mismatches=[];observed={};formulas={};errors=[]
    try:
        require(f.sheetnames==v.sheetnames==definition['sheetnames'],'Worksheet order changed')
        require(f.calculation.iterate is True and f.calculation.iterateCount==definition['iteration_settings']['count']
            and f.calculation.iterateDelta==definition['iteration_settings']['delta'],'Native iteration settings changed')
        for sheet in f:
            for cell in sheet._cells.values():
                if cell.data_type=='f':formulas[sheet.title+'!'+cell.coordinate]=cell.value
        require(set(formulas)==set(definition['formulas']) and all(formula_signature(text)==formula_signature(definition['formulas'][p])
            for p,text in formulas.items()),'The complete financial formula definitions changed')
        for sheet in v:
            for cell in sheet._cells.values():
                point=sheet.title+'!'+cell.coordinate
                if cell.data_type=='e':errors.append({'point':point,'error':cell.value})
                if cell.value is not None:observed[point]=typed(cell.value,financial=point in expected)
        for point,wanted in expected.items():
            actual=observed.get(point,{'type':'empty','value':''})
            if actual!=({'type':'empty','value':''} if empty_caches else wanted):mismatches.append({'point':point,'expected':None if empty_caches else wanted,'actual':actual})
        for point,wanted in definition['literals'].items():
            if observed.get(point)!=wanted:mismatches.append({'point':point,'claim':'Provided input, policy or label changed'})
        for point,wanted in definition['provided_financial_inputs'].items():
            sheet,cell=point.rsplit('!',1)
            if typed(v[sheet][cell].value,financial=True)!=wanted:mismatches.append({'point':point,'claim':'Independent provided financial input differs'})
        require(set(observed)==set(definition['literals']) | (set() if empty_caches else set(expected)),
            'Unexpected extra or missing populated cells')
        return {'kind':'full_independent_equity_income_native_cache_audit','passed':not mismatches and not errors,
            'workbook':reference(path),'all_derived_values_checked':len(expected),'physical_formulas_checked':len(formulas),
            'provided_financial_input_fields_checked':len(definition['provided_financial_inputs']),
            'all_financial_fields_checked':len(expected)+len(definition['provided_financial_inputs']),
            'protected_public_literals_checked':len(definition['literals']),'mismatches':mismatches,'native_errors':errors,
            'normalization':'financial bindings half-up2dp; all supplied literals exact and booleans distinct',
            'all_formula_caches_empty':empty_caches,'qualified':False}
    finally:f.close();v.close()

def compare_typed(left,right,financial_points):
    def values(path):
        book=openpyxl.load_workbook(path,data_only=True)
        try:return {'sheetnames':book.sheetnames,'values':{s.title+'!'+c.coordinate:typed(c.value,financial=s.title+'!'+c.coordinate in financial_points)
            for s in book for c in s._cells.values() if c.value is not None}}
        finally:book.close()
    a,b=values(left),values(right);bad=[p for p in sorted(set(a['values'])|set(b['values'])) if a['values'].get(p)!=b['values'].get(p)]
    return {'passed':a['sheetnames']==b['sheetnames'] and not bad,'typed_value_mismatches':len(bad),'mismatched_points':bad,
        'whole_populated_grid_compared':True,'financial_2dp_only':True,'provided_values_exact':True}

def prepare(candidate_manifest,output,*,profile=PROFILE):
    output=Path(output).absolute();require(output==output.resolve() and not output.exists(),'Use a fresh source directory')
    m=read(candidate_manifest);require(m['kind']=='prepared_unverified_synthetic_equity_income_group_pair' and m['version']==1
        and m['actual_LO_calls']==m['model_calls']==0 and m['qualified'] is False and m['official_workbook_seed_used'] is False,
        'Use this family\'s unverified synthetic pair, never another family admission')
    require(m['recipe_sha256']=={str(Path(x.__file__).resolve()):reference(x.__file__)['sha256'] for x in (spec,decimal_oracle,fraction_oracle)}
        and m['emitter']==reference(excel.__file__),'Frozen independent mathematics/emitter changed')
    for r in (m['specification'],m['goal'],m['bindings'],m['independent_expected'],*[r for view in m['views'].values() for r in view.values()]):checked(r)
    public=spec.validate(read(m['specification']));bindings=read(m['bindings']);expected,comparison=crosscheck(public,bindings)
    require(expected=={p:{'type':'number','value':'0' if not Decimal(v['value']) else format(Decimal(v['value']).normalize(),'f')} for p,v in read(m['independent_expected']).items()},'The complete prepared independent target map changed')
    definition=source_definition(checked(m['goal']),bindings,public);r,p=runtime(profile)
    output.mkdir(parents=True);cold=output/'cold_start.xlsx';clear=clear_all_formula_caches(checked(m['goal']),cold)
    require(clear['all_formula_caches_cleared']==len(expected),'Every formula must receive the same declared cold start')
    cold_audit=audit_workbook(cold,definition,expected,empty_caches=True);require(cold_audit['passed'],'Cold formula/literal/cache preservation failed')
    refs={'definition':write(output/'definition.private.json',definition),'expected':write(output/'expected.private.json',expected),
        'independent_comparison':write(output/'independent_AB_comparison.json',comparison),
        'cold_start_audit':write(output/'cold_start_audit.json',cold_audit)}
    return write(output/'preparation.json',{'kind':KIND,'version':1,'candidate_manifest':reference(candidate_manifest['path'] if isinstance(candidate_manifest,dict) else candidate_manifest),
        'specification':m['specification'],'bindings':m['bindings'],'specification_sha256':spec.canonical_sha256(public),'cold_start':reference(cold),
        **refs,'cache_clearance':clear,'runtime_profile':r,'runtime_profile_value':p,'recipe':recipes(),'stage_order':list(STAGES),
        'required_actual_LO_calls':3,'cold_start_is_unseeded':True,'actual_LO_calls':0,'model_calls':0,'qualified':False})

def validate_prepared(output):
    f=read(Path(output)/'preparation.json')
    require(f['kind']==KIND and f['version']==1 and f['recipe']==recipes() and f['stage_order']==list(STAGES)
        and f['required_actual_LO_calls']==3 and f['cold_start_is_unseeded'] is True,'Prepared family/recipe/stages changed')
    for key in ('candidate_manifest','specification','bindings','cold_start','definition','expected','independent_comparison','cold_start_audit','runtime_profile'):checked(f[key])
    require(runtime(checked(f['runtime_profile']))==(f['runtime_profile'],f['runtime_profile_value']),'Runtime profile changed')
    cold=audit_workbook(checked(f['cold_start']),read(f['definition']),read(f['expected']),empty_caches=True)
    require(cold['passed'] and cold==read(f['cold_start_audit']) and f['cache_clearance']['output']==f['cold_start']
        and f['cache_clearance']['all_formula_caches_cleared']==len(read(f['expected'])),
        'The first actual input must still have every formula cache absent')
    return f

def validate_call(call,record,frozen):return validate_capped_call(call,record,frozen,resource_validator=resource_support().validate_actual_call)

def owned_absence(calls):
    ids=[c['actual_resource_evidence']['container_id'] for c in calls]
    require(len(ids)==len(set(ids)) and all(re.fullmatch('[0-9a-f]{64}',cid) for cid in ids),'Distinct full owned IDs required')
    rows=[]
    for cid in ids:
        p=subprocess.run(['docker','inspect',cid,'--format','{{.Id}}'],capture_output=True,text=True,timeout=15)
        missing=re.fullmatch(r'(?i:(?:error:\s*)?no such (?:object|container):\s*)'+re.escape(cid),p.stderr.strip()) is not None
        rows.append({'full_id':cid,'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'absent':p.returncode==1 and not p.stdout.strip() and missing})
    daemon=subprocess.run(['docker','version','--format','{{.Server.Version}}'],capture_output=True,text=True,timeout=15)
    return {'all_owned_containers_absent':all(r['absent'] for r in rows),'daemon_reachable':daemon.returncode==0 and bool(daemon.stdout.strip()),
        'owned':rows,'daemon_version':daemon.stdout.strip(),'cleanup_mutations_by_validator':False}

@contextmanager
def stage(audit,name):
    started=time.monotonic();record=audit.record('nodes',{'node':name,'status':'running','started_at':now()});audit.update_run(active_stage=name);audit.export()
    audit.emit('equity_source.stage_started',stage=name)
    status='failed'
    try:yield;status='completed'
    finally:
        audit.update_record('nodes',record,{'status':status,'finished_at':now(),'duration_ms':1000*(time.monotonic()-started)})
        audit.emit('equity_source.stage_terminal',stage=name,status=status);audit.export()

def execute_prepared(output):
    output=Path(output).absolute();f=validate_prepared(output);require(not (output/'started.json').exists(),'No retries; preserve the first attempt')
    lease=ProducerLease(output).acquire();audit=server=pulse=None;stop=threading.Event();calls=[];records={};clock=time.monotonic();failure=None;engine=None
    old_tmp=os.environ.get('TMPDIR');cached_tmp=tempfile.tempdir;tmp=output/'temporary'
    try:
        tmp.mkdir();os.environ['TMPDIR']=str(tmp);tempfile.tempdir=str(tmp)
        audit=AuditStore(output/'audit',{'id':output.name,'name':'Equity-income cold-start source','status':'running','target_count':0,
            'qualified':False,'producer_pid':os.getpid(),'model_calls':0,'solver_calls':0,'Harbor_calls':0})
        server=DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=0);url=server.start()
        write(output/'started.json',{'at':now(),'preparation':reference(output/'preparation.json'),'dashboard_url':url,'pid':os.getpid(),'retry':0})
        print(json.dumps({'dashboard_url':url,'pid':os.getpid()}),flush=True)
        def heartbeat():
            while not stop.wait(15):audit.update_run(elapsed_seconds=time.monotonic()-clock,actual_LO_calls_started=len(calls),actual_LO_calls_completed=sum(c['completed'] for c in calls));audit.export()
        pulse=threading.Thread(target=heartbeat,daemon=True);pulse.start()
        with stage(audit,'independent_AB_financial_check'):
            expected,comparison=crosscheck(spec.validate(read(f['specification'])),read(f['bindings']))
            require(expected==read(f['expected']) and comparison==read(f['independent_comparison']),'Independent financial expectations changed')
        definition=read(f['definition']);engine=ThreadCappedResourceLibreOfficeEngine(ROOT,f['runtime_profile']['path'],role='source',receipt_directory=output/'engine_resources')
        with stage(audit,'pinned_native_image_check'):engine.ensure_image()
        previous=f['cold_start']
        for index,name in enumerate(STAGES,1):
            call={'index':index,'role':name,'input':previous,'started_at':now(),'completed':False};calls.append(call)
            call['started_receipt']=write(output/(name+'_started.json'),dict(call))
            with stage(audit,name):
                try:
                    tick=time.monotonic();actual=Path(engine.recalculate(checked(previous),output/(name+'.xlsx')))
                    call.update(output=reference(actual),completed=True,elapsed_seconds=time.monotonic()-tick)
                    history=engine.metadata()['actual_resource_receipts'];require(len(history)==index,'Extra/missing actual call')
                    call['actual_resource_evidence']=validate_call(call,history[-1],f)
                finally:call['finished_at']=now();call['terminal_receipt']=write(output/(name+'_terminal.json'),dict(call))
            with stage(audit,name+'_complete_independent_audit'):
                report=audit_workbook(actual,definition,expected);records[name+'_audit']=write(output/(name+'_audit.json'),report)
                require(report['passed'],'Complete independent financial/type/literal audit failed')
            previous=call['output'];print(json.dumps({'actual_call_completed':name,'elapsed_seconds':call['elapsed_seconds']}),flush=True)
        for left,right in zip(calls,calls[1:]):
            key=left['role']+'_to_'+right['role']
            with stage(audit,key+'_full_typed_stability'):
                report=compare_typed(left['output']['path'],right['output']['path'],expected)
                records[key]=write(output/(key+'.json'),{'left':left['output'],'right':right['output'],'comparison':report})
                require(report['passed'],'Whole-grid financial2dp/protected-exact typed stability failed')
        with stage(audit,'owned_container_cleanup_observation'):
            records['cleanup']=write(output/'owned_containers_absence.json',owned_absence(calls))
            clean=read(records['cleanup']);require(clean['all_owned_containers_absent'] and clean['daemon_reachable'],'Owned cleanup is incomplete or unknown')
        require(validate_prepared(output)==f,'Recipe or initial artifacts changed')
    except BaseException as error:
        failure={'type':type(error).__name__,'message':str(error)};records['failure']=write(output/'failure.json',failure)
    finally:
        if failure is not None and engine is not None:
            try:
                owned=[]
                for r in engine.metadata()['actual_resource_receipts']:
                    actual=read(r);require(any(actual.get('source')==c['input'] for c in calls),'Cleanup receipt is not an owned input')
                    if actual.get('container_id'):owned.append({'actual_resource_evidence':{'container_id':actual['container_id']}})
                if owned:records['failure_cleanup']=write(output/'failure_owned_absence.json',owned_absence(owned))
            except Exception as error:records['failure_cleanup']=write(output/'failure_cleanup_unknown.json',{'state':'unknown','error_type':type(error).__name__})
        stop.set()
        if pulse:pulse.join(timeout=1)
        if audit:audit.update_run(status='passed' if failure is None else 'failed',producer_active=False,elapsed_seconds=time.monotonic()-clock);audit.export()
        if server:server.stop()
        if audit:audit.db.close()
        lease.release()
        if old_tmp is None:os.environ.pop('TMPDIR',None)
        else:os.environ['TMPDIR']=old_tmp
        tempfile.tempdir=cached_tmp
    terminal=write(output/'source_manifest.json',{'kind':SOURCE_KIND,'version':1,'passed':failure is None,'failure':failure,
        'preparation':reference(output/'preparation.json'),'source':calls[-1].get('output') if calls else None,
        'specification':f['specification'],'specification_sha256':f['specification_sha256'],'bindings':f['bindings'],
        'actual_calls':calls,'records':records,'actual_LO_calls_started':len(calls),'actual_LO_calls_completed':sum(c['completed'] for c in calls),
        'cold_start_is_unseeded':True,'elapsed_seconds':time.monotonic()-clock,'model_calls':0,'solver_calls':0,'Harbor_calls':0,
        'task_count':0,'qualified':False,'normal_all12_QA_passed':False,'difficulty_claimed':False,'retry':0})
    if failure is not None:raise RuntimeError('Source engineering failed; preserve the first source_manifest without retry')
    return terminal

def validate_source(value):
    terminal=read(value);require(terminal['kind']==SOURCE_KIND and terminal['version']==1 and terminal['passed'] is True
        and terminal['failure'] is None and terminal['actual_LO_calls_started']==terminal['actual_LO_calls_completed']==3
        and terminal['cold_start_is_unseeded'] is True and terminal['qualified'] is False and terminal['normal_all12_QA_passed'] is False
        and terminal['difficulty_claimed'] is False and terminal['retry']==terminal['model_calls']==terminal['solver_calls']==terminal['Harbor_calls']==0,
        'A genuine complete source3 attempt is required')
    f=validate_prepared(checked(terminal['preparation']).parent);expected,comparison=crosscheck(spec.validate(read(f['specification'])),read(f['bindings']))
    require(expected==read(f['expected']) and comparison==read(f['independent_comparison']),'Complete independent source evidence changed')
    previous=f['cold_start'];calls=terminal['actual_calls'];require(len(calls)==3,'Complete three-call source evidence required')
    for index,(name,call) in enumerate(zip(STAGES,calls,strict=True),1):
        require(call['index']==index and call['role']==name and call['input']==previous and call['completed'] is True,'Actual cold source chain changed')
        checked(call['output']);require(read(call['terminal_receipt'])=={k:v for k,v in call.items() if k!='terminal_receipt'},'Original call terminal changed')
        require(validate_call(call,call['actual_resource_evidence']['terminal'],f)==call['actual_resource_evidence'],'Actual source resources/cap changed')
        report=audit_workbook(call['output']['path'],read(f['definition']),expected)
        require(report['passed'] and read(terminal['records'][name+'_audit'])==report,'Independent full financial/type source audit changed')
        previous=call['output']
    for left,right in zip(calls,calls[1:]):
        report=compare_typed(left['output']['path'],right['output']['path'],expected)
        require(report['passed'] and read(terminal['records'][left['role']+'_to_'+right['role']])=={'left':left['output'],'right':right['output'],'comparison':report},'Whole-grid typed stability changed')
    clean=read(terminal['records']['cleanup']);require(clean['all_owned_containers_absent'] and clean['daemon_reachable']
        and len(clean['owned'])==3 and all(r['absent'] for r in clean['owned'])
        and {r['full_id'] for r in clean['owned']}=={c['actual_resource_evidence']['container_id'] for c in calls},'Actual owned cleanup does not cover all three calls')
    require(terminal['source']==previous and terminal['specification']==f['specification'] and terminal['bindings']==f['bindings'],'Source manifest identity changed')
    return terminal

validate_completed=validate_source

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--candidate',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--profile',type=Path,default=PROFILE);parser.add_argument('--prepared',type=Path);parser.add_argument('--run',action='store_true');args=parser.parse_args(argv)
    if args.prepared:
        require(args.candidate is None and args.output is None,'Use the exact existing preparation')
        result=execute_prepared(args.prepared) if args.run else validate_prepared(args.prepared)
    else:
        require(args.candidate is not None and args.output is not None,'Supply candidate and fresh output')
        result=prepare(args.candidate,args.output,profile=args.profile)
        if args.run:result=execute_prepared(args.output)
    print(json.dumps(result));return 0

if __name__=='__main__':raise SystemExit(main())
