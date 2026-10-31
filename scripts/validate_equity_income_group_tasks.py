#!/usr/bin/env python3
"""Eight shared FM/DBG engineering calls after genuine family source3 proof."""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
import time
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'));sys.dont_write_bytecode=True
SOURCE_SCRIPT=ROOT/'scripts/build_equity_income_group_source.py'
SOURCE_SHA256='1b6e3374a98e39a5708543af4e796026262d9d782a461d6ec29ad10d11ac3690'
if hashlib.sha256(SOURCE_SCRIPT.read_bytes()).hexdigest()!=SOURCE_SHA256:raise ValueError('Frozen family source gate changed')
_spec=importlib.util.spec_from_file_location('_equity_income_source_for_tasks',SOURCE_SCRIPT)
source=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(source)
from sheets_factory.evaluation import streaming_verifier
reference,checked,read,write,require=source.reference,source.checked,source.read,source.write,source.require
AuditStore,DashboardServer,ProducerLease=source.AuditStore,source.DashboardServer,source.ProducerLease
ThreadCappedResourceLibreOfficeEngine=source.ThreadCappedResourceLibreOfficeEngine
KIND='prepared_equity_income_group_task_engineering'
TERMINAL_KIND='complete_equity_income_group_task_engineering'
STAGES=('FM_input1','FM_input2','DBG_input1','DBG_input2','equivalent','FM_missed_root','DBG_missed_root','extra_change')
S=source.NS

def recipes():return {**source.recipes(),str(Path(__file__).resolve()):reference(__file__),
    str(Path(streaming_verifier.__file__).resolve()):reference(streaming_verifier.__file__)}

def transform(original,destination,changes):
    """Apply only declared cell edits; preserve all other cell/member bytes."""
    touched=[];found=set()
    with ZipFile(original) as zin,ZipFile(destination,'x',ZIP_DEFLATED) as zout:
        book=ET.fromstring(zin.read('xl/workbook.xml'));rels=ET.fromstring(zin.read('xl/_rels/workbook.xml.rels'))
        targets={r.get('Id'):r.get('Target') for r in rels};parts={}
        for sheet in book.find('{*}sheets'):
            target=targets[sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')]
            parts[sheet.get('name')]=target.lstrip('/') if target.startswith('/') else 'xl/'+target
        by_member={}
        for (sheet,cell),value in changes.items():by_member.setdefault(parts[sheet],{})[cell]=(sheet,value)
        for item in zin.infolist():
            raw=zin.read(item.filename);before=raw
            for address,(sheet,(kind,value)) in by_member.get(item.filename,{}).items():
                pattern=rb'<(?P<p>(?:[A-Za-z_][\w.-]*:)?)c\b(?=[^>]*\br="'+address.encode()+rb'")[^>]*?(?:/>|>.*?</(?P=p)c>)'
                matches=list(re.finditer(pattern,raw,re.S));require(len(matches)==1,'A declared task cell must exist exactly once')
                match=matches[0];old=match.group();prefix=match.group('p');opening=old[:old.index(b'>')+1].replace(b'/>',b'>')
                opening=re.sub(rb'\s+t="[^"]*"',b'',opening)
                if kind=='blank':body=b''
                elif kind=='formula':body=b'<'+prefix+b'f>'+escape(value.lstrip('=')).encode()+b'</'+prefix+b'f>'
                elif kind=='text':opening=opening[:-1]+b' t="inlineStr">';body=b'<'+prefix+b'is><'+prefix+b't>'+escape(value).encode()+b'</'+prefix+b't></'+prefix+b'is>'
                else:raise ValueError('Unknown declared transformation')
                replacement=opening+body+b'</'+prefix+b'c>';raw=raw[:match.start()]+replacement+raw[match.end():];found.add((sheet,address))
            if raw!=before:touched.append(item.filename)
            zout.writestr(item,raw)
    require(found==set(changes),'A declared task edit was not materialized')
    return {'source':reference(original),'output':reference(destination),'changed_members':touched,
        'edits':[{'sheet':s,'cell':c,'kind':v[0],'value':v[1]} for (s,c),v in changes.items()],
        'all_other_cells_and_members_byte_preserved':True}

def snapshot(path,financial_points):
    book=source.openpyxl.load_workbook(path,data_only=True)
    try:
        return {'sheetnames':book.sheetnames,'values':{s.title+'!'+c.coordinate:
            ({'type':'error','value':c.value} if c.data_type=='e' else source.typed(c.value,financial=s.title+'!'+c.coordinate in financial_points))
            for s in book for c in s._cells.values() if c.value is not None}}
    finally:book.close()

def compare_complete(input_path,goal_path,output_path,financial_points):
    # Task reward is the unchanged generic whole-grid grader: ALL numbers2dp.
    # Exact primitive preservation belongs to construction/source auditing only.
    return streaming_verifier.compare_files(input_path,goal_path,output_path)

def verify_definitions(path,definition,*,blank=False):
    book=source._book(path)
    try:
        require(book.sheetnames==definition['sheetnames'],'Task worksheet structure changed')
        formulas={s.title+'!'+c.coordinate:c.value for s in book for c in s._cells.values() if c.data_type=='f'}
        wanted={} if blank else definition['formulas']
        require(set(formulas)==set(wanted) and all(source.formula_signature(formulas[p])==source.formula_signature(wanted[p]) for p in wanted),'Full task formula scope/definitions changed')
        literals={s.title+'!'+c.coordinate:source.typed(c.value) for s in book for c in s._cells.values() if c.value is not None and c.data_type!='f'}
        require(literals==definition['literals'],'Provided task inputs, policies or labels changed')
        require(book.calculation.iterate is True and book.calculation.iterateCount==definition['iteration_settings']['count']
            and book.calculation.iterateDelta==definition['iteration_settings']['delta'],'Task iteration settings changed')
    finally:book.close()

def prepare(source_manifest,output):
    output=Path(output).absolute();require(output==output.resolve() and not output.exists(),'Use a fresh task-engineering directory')
    actual=source.validate_source(source_manifest);sf=source.validate_prepared(checked(actual['preparation']).parent)
    candidate=read(sf['candidate_manifest']);bindings=read(sf['bindings']);definition=read(sf['definition']);expected=read(sf['expected'])
    require(actual['source']==actual['actual_calls'][-1]['output'],'Use the genuine source3 physical goal')
    roots=bindings['DBG_root_edits'];require(roots and all(r['metric']=='net_income' for r in roots),'This declared sign-fault family is required')
    for row in roots:
        point=row['sheet']+'!'+row['cell']
        require(source.formula_signature(definition['formulas'][point])==source.formula_signature(row['before']),
            'A declared fault root does not match the genuine source formula')
    output.mkdir(parents=True);planned=output/'planned';planned.mkdir();goal=actual['source'];root=roots[0];root_point=(root['sheet'],root['cell'])
    correct_formula=definition['formulas'][root['sheet']+'!'+root['cell']]
    all_points=[tuple(p.rsplit('!',1)) for p in expected]
    cases={'FM_input':{p:('blank',None) for p in all_points},
        'DBG_input':{(r['sheet'],r['cell']):('formula',r['after']) for r in roots},
        'equivalent':{root_point:('formula','=0+('+correct_formula.lstrip('=')+')')},
        'FM_missed_root':{root_point:('blank',None)},'DBG_missed_root':{root_point:('formula',root['after'])},
        'extra_change':{('Read Me','A1'):('text',definition['literals']['Read Me!A1']['value']+' [control]')}}
    plans={};edits={};clearances={}
    for name,changes in cases.items():
        intermediate=planned/(name+'.edited.xlsx');edits[name]=transform(checked(goal),intermediate,changes)
        final=planned/(name+'.xlsx');clearances[name]=source.clear_all_formula_caches(intermediate,final);plans[name]=reference(final)
    instructions={}
    for mode in ('financial_modeling','debugging'):
        r=candidate['views'][mode]['instruction'];target=planned/(mode+'_instruction.md');shutil.copyfile(checked(r),target);instructions[mode]=reference(target)
    dbg=deepcopy(definition)
    for r in roots:dbg['formulas'][r['sheet']+'!'+r['cell']]=r['after']
    verify_definitions(checked(plans['FM_input']),definition,blank=True);verify_definitions(checked(plans['DBG_input']),dbg)
    return write(output/'preparation.json',{'kind':KIND,'version':1,'source_manifest':reference(source_manifest['path'] if isinstance(source_manifest,dict) else source_manifest),
        'genuine_goal':goal,'source_preparation':actual['preparation'],'candidate_preparation':sf['candidate_manifest'],
        'definition':sf['definition'],'expected':sf['expected'],'bindings':sf['bindings'],'DBG_definition':write(output/'DBG_definition.private.json',dbg),
        'planned_inputs':plans,'instruction_bytes':instructions,'exact_edits':edits,'all_formula_cache_clearances':clearances,
        'stage_order':list(STAGES),'mode_order':['financial_modeling','debugging'],'required_actual_LO_calls':8,
        'all_modes_and_controls_frozen_before_first_actual_call':True,'reuse_genuine_source3_goal_and_two_stabilities':True,
        'financial_target_count':len(expected),'DBG_formula_root_count':len(roots),'complete_D_counts_pending_actual_input_calculation':True,
        'runtime_profile':sf['runtime_profile'],'runtime_profile_value':sf['runtime_profile_value'],'recipe':recipes(),
        'actual_LO_calls':0,'model_calls':0,'qualified':False,'normal_all12_QA_passed':False})

def validate_prepared(output):
    f=read(Path(output)/'preparation.json')
    require(f['kind']==KIND and f['version']==1 and f['recipe']==recipes() and f['stage_order']==list(STAGES)
        and f['required_actual_LO_calls']==8 and f['all_modes_and_controls_frozen_before_first_actual_call'] is True,'Prepared family/recipe/order changed')
    for key in ('source_manifest','genuine_goal','source_preparation','candidate_preparation','definition','expected','bindings','DBG_definition','runtime_profile'):checked(f[key])
    for refs in (f['planned_inputs'],f['instruction_bytes']):
        for r in refs.values():checked(r)
    actual,sf,candidate=read(f['source_manifest']),read(f['source_preparation']),read(f['candidate_preparation'])
    require(actual['source']==f['genuine_goal'] and actual['preparation']==f['source_preparation']
        and sf['candidate_manifest']==f['candidate_preparation'] and sf['definition']==f['definition']
        and sf['bindings']==f['bindings'] and sf['expected']==f['expected']
        and sf['runtime_profile']==f['runtime_profile'] and sf['runtime_profile_value']==f['runtime_profile_value'],
        'Source, goal and complete financial bindings refer to different originals')
    for mode,r in f['instruction_bytes'].items():
        original=candidate['views'][mode]['instruction']
        require(r['sha256']==original['sha256'] and r['bytes']==original['bytes'],'The original short business instruction changed')
    return f

def verify_input_caches(path,expected,*,blank):
    observed=snapshot(path,expected)['values']
    require(all((p not in observed) if blank else (observed.get(p,{}).get('type')=='number') for p in expected),
        'An input has unexpected derived values or nonnumeric/error financial caches')

def _stage_source(name,f,results):
    if name in ('FM_input2','DBG_input2'):return results[name[:-1]+'1']
    return f['planned_inputs'][name[:-1] if name in ('FM_input1','DBG_input1') else name]

def execute_prepared(output):
    output=Path(output).absolute();f=validate_prepared(output);require(not (output/'started.json').exists(),'No retries; retain the first task attempt')
    lease=ProducerLease(output).acquire();audit=server=pulse=engine=None;stop=threading.Event();clock=time.monotonic();calls=[];records={};results={};failure=None
    old_tmp=os.environ.get('TMPDIR');cached_tmp=tempfile.tempdir
    try:
        temporary=output/'temporary';temporary.mkdir();os.environ['TMPDIR']=str(temporary);tempfile.tempdir=str(temporary)
        audit=AuditStore(output/'audit',{'id':output.name,'name':'Equity-income FM/DBG engineering','status':'running','target_count':0,'qualified':False,'producer_pid':os.getpid(),'model_calls':0})
        server=DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=0);url=server.start()
        write(output/'started.json',{'at':source.now(),'preparation':reference(output/'preparation.json'),'dashboard_url':url,'pid':os.getpid(),'retry':0})
        print(json.dumps({'dashboard_url':url,'pid':os.getpid()}),flush=True)
        def heartbeat():
            while not stop.wait(15):audit.update_run(elapsed_seconds=time.monotonic()-clock,actual_LO_calls_started=len(calls),actual_LO_calls_completed=sum(c['completed'] for c in calls));audit.export()
        pulse=threading.Thread(target=heartbeat,daemon=True);pulse.start()
        with source.stage(audit,'genuine_source3_cold_binding'):source.validate_source(f['source_manifest'])
        definition,dbg,expected=read(f['definition']),read(f['DBG_definition']),read(f['expected'])
        engine=ThreadCappedResourceLibreOfficeEngine(ROOT,f['runtime_profile']['path'],role='source',receipt_directory=output/'engine_resources')
        with source.stage(audit,'pinned_image_check'):engine.ensure_image()
        for index,name in enumerate(STAGES,1):
            original=_stage_source(name,f,results);call={'index':index,'role':name,'input':original,'started_at':source.now(),'completed':False};calls.append(call)
            call['started_receipt']=write(output/(name+'_started.json'),dict(call))
            with source.stage(audit,'actual_'+name):
                try:
                    started=time.monotonic();actual=Path(engine.recalculate(checked(original),output/(name+'.xlsx')))
                    call.update(output=reference(actual),completed=True,elapsed_seconds=time.monotonic()-started)
                    history=engine.metadata()['actual_resource_receipts'];require(len(history)==index,'Extra/missing actual task call')
                    call['actual_resource_evidence']=source.validate_call(call,history[-1],f)
                finally:call['finished_at']=source.now();call['terminal_receipt']=write(output/(name+'_terminal.json'),dict(call))
            results[name]=call['output']
            if name.startswith('FM_input'):verify_definitions(actual,definition,blank=True);verify_input_caches(actual,expected,blank=True)
            elif name.startswith('DBG_input'):verify_definitions(actual,dbg);verify_input_caches(actual,expected,blank=False)
            print(json.dumps({'actual_call_completed':name,'completed_calls':index,'elapsed_seconds':call['elapsed_seconds']}),flush=True)
        for prefix in ('FM','DBG'):
            left,right=results[prefix+'_input1'],results[prefix+'_input2'];comparison=source.compare_typed(left['path'],right['path'],expected)
            records[prefix+'_stability']=write(output/(prefix+'_stability.json'),{'left':left,'right':right,'comparison':comparison})
            require(comparison['passed'],'Complete taskbook2dp/protected-exact typed stability failed')
        modes={}
        for mode,prefix in [('financial_modeling','FM'),('debugging','DBG')]:
            scores={};proofs={};inp=results[prefix+'_input2'];goal=f['genuine_goal']
            for control,result in [('oracle',goal),('nop',inp),('equivalent',results['equivalent']),('missed_root',results[prefix+'_missed_root']),('extra_change',results['extra_change'])]:
                comparison=compare_complete(inp['path'],goal['path'],result['path'],expected)
                proofs[control]=write(output/(prefix+'_'+control+'_complete_D.json'),{'input':inp,'goal':goal,'output':result,'comparison':comparison})
                scores[control]=comparison['reward']
            require(scores=={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0},'Complete actual five-control pattern failed')
            d=read(proofs['oracle'])['comparison']['expected_change_count'];require(d>0 and (prefix!='FM' or d==f['financial_target_count']),'Actual full financial D is absent or incomplete')
            modes[mode]={'input':inp,'goal':goal,'instruction':f['instruction_bytes'][mode],'controls':scores,'full_D_controls':proofs,'complete_D_count':d}
        records['modes']=modes
        with source.stage(audit,'owned_cleanup_observation'):
            records['cleanup']=write(output/'owned_containers_absence.json',source.owned_absence(calls));cleanup=read(records['cleanup'])
            require(cleanup['all_owned_containers_absent'] and cleanup['daemon_reachable'],'Owned task cleanup incomplete or unknown')
        require(validate_prepared(output)==f,'Task recipe or initial inputs changed')
    except BaseException as error:failure={'type':type(error).__name__,'message':str(error)};records['failure']=write(output/'failure.json',failure)
    finally:
        if failure is not None and engine is not None:
            try:
                owned=[]
                for r in engine.metadata()['actual_resource_receipts']:
                    actual=read(r);require(any(actual.get('source')==c['input'] for c in calls),'Failure cleanup is not an owned input')
                    if actual.get('container_id'):owned.append({'actual_resource_evidence':{'container_id':actual['container_id']}})
                if owned:records['failure_cleanup']=write(output/'failure_owned_absence.json',source.owned_absence(owned))
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
    terminal=write(output/'terminal.json',{'kind':TERMINAL_KIND,'version':1,'passed':failure is None,'failure':failure,
        'preparation':reference(output/'preparation.json'),'source_manifest':f['source_manifest'],'actual_calls':calls,'records':records,
        'actual_LO_calls_started':len(calls),'actual_LO_calls_completed':sum(c['completed'] for c in calls),
        'source_LO_calls_reused':3,'model_calls':0,'solver_calls':0,'Harbor_calls':0,'retry':0,'qualified':False,
        'normal_all12_QA_passed':False,'difficulty_claimed':False,'elapsed_seconds':time.monotonic()-clock})
    if failure is not None:raise RuntimeError('Task engineering failed; preserve original terminal without retry')
    return terminal

def validate_completed(value):
    t=read(value);require(t['kind']==TERMINAL_KIND and t['version']==1 and t['passed'] is True and t['failure'] is None
        and t['actual_LO_calls_started']==t['actual_LO_calls_completed']==8 and t['qualified'] is False and t['normal_all12_QA_passed'] is False
        and t['difficulty_claimed'] is False and t['model_calls']==t['solver_calls']==t['Harbor_calls']==t['retry']==0,'A complete original family task attempt is required')
    f=validate_prepared(checked(t['preparation']).parent);require(t['source_manifest']==f['source_manifest'],'Another source is bound')
    source.validate_source(f['source_manifest']);expected=read(f['expected']);definition=read(f['definition']);dbg=read(f['DBG_definition']);results={}
    require(len(t['actual_calls'])==8,'Complete actual call inventory required')
    for index,(name,call) in enumerate(zip(STAGES,t['actual_calls'],strict=True),1):
        require(call['index']==index and call['role']==name and call['input']==_stage_source(name,f,results) and call['completed'] is True,'Actual view/control chain changed')
        checked(call['output']);require(read(call['terminal_receipt'])=={k:v for k,v in call.items() if k!='terminal_receipt'},'Original task call terminal changed')
        require(source.validate_call(call,call['actual_resource_evidence']['terminal'],f)==call['actual_resource_evidence'],'Actual task resources/cap changed')
        results[name]=call['output']
        if name.startswith('FM_input'):verify_definitions(call['output']['path'],definition,blank=True);verify_input_caches(call['output']['path'],expected,blank=True)
        elif name.startswith('DBG_input'):verify_definitions(call['output']['path'],dbg);verify_input_caches(call['output']['path'],expected,blank=False)
    for mode,prefix in [('financial_modeling','FM'),('debugging','DBG')]:
        left,right=results[prefix+'_input1'],results[prefix+'_input2'];comparison=source.compare_typed(left['path'],right['path'],expected)
        require(comparison['passed'] and read(t['records'][prefix+'_stability'])=={'left':left,'right':right,'comparison':comparison},'Complete typed stability changed')
        proof=t['records']['modes'][mode];require(proof['input']==right and proof['goal']==f['genuine_goal'] and proof['instruction']==f['instruction_bytes'][mode],'Mode physical bindings changed')
        scores={}
        for control,result in [('oracle',f['genuine_goal']),('nop',right),('equivalent',results['equivalent']),('missed_root',results[prefix+'_missed_root']),('extra_change',results['extra_change'])]:
            comparison=compare_complete(right['path'],f['genuine_goal']['path'],result['path'],expected)
            require(read(proof['full_D_controls'][control])=={'input':right,'goal':f['genuine_goal'],'output':result,'comparison':comparison}
                and comparison['expected_change_count']==proof['complete_D_count'],'Full D/control proof changed')
            scores[control]=comparison['reward']
        require(scores==proof['controls']=={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0},'Actual five controls changed')
    cleanup=read(t['records']['cleanup']);require(cleanup['all_owned_containers_absent'] and cleanup['daemon_reachable']
        and len(cleanup['owned'])==8 and all(r['absent'] for r in cleanup['owned'])
        and {r['full_id'] for r in cleanup['owned']}=={c['actual_resource_evidence']['container_id'] for c in t['actual_calls']},'Cleanup does not cover eight actual owned IDs')
    return t

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-manifest',type=Path);p.add_argument('--output',type=Path);p.add_argument('--prepared',type=Path);p.add_argument('--run',action='store_true');args=p.parse_args(argv)
    if args.prepared:
        require(args.source_manifest is None and args.output is None,'Keep the existing exact preparation');r=execute_prepared(args.prepared) if args.run else validate_prepared(args.prepared)
    else:
        require(args.source_manifest is not None and args.output is not None,'Supply genuine source and fresh task output');r=prepare(args.source_manifest,args.output)
        if args.run:r=execute_prepared(args.output)
    print(json.dumps(r));return 0

if __name__=='__main__':raise SystemExit(main())
