#!/usr/bin/env python3
"""Five DBG calculations for one prospectively frozen complete fault class."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
from types import FunctionType, SimpleNamespace
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
ANCESTOR=ROOT/'scripts/validate_equity_income_group_tasks.py'
ANCESTOR_SHA='bcc07848ed5b868c9cb943e3058aa10980b9399d4d53a8d17220d60748a85f0c'
SOURCE_SCRIPT=ROOT/'scripts/build_operating_reports_200_source_revision2.py'
SOURCE_SHA='e0ed07a1954c40cfe3db67a5ef709e40708bd9244a6cf755b77ccc5a9031dfe7'
SOURCE_KIND='independently_checked_fixed_operating_reports_200_source_revision2'
DESIGN=ROOT/'src/sheets_factory/workbook/operating_reports_200/debug_class_variants.py'
DESIGN_SHA='8d4b23e252ed5b29bda6589a5ee66d09f94f99f313a9b3554927c4373a7d11c1'
ENVELOPE_SHA='de584267929f5d9f3d7abd71efb566a97b69aa191f7814266f6fd7a6eee5b95b'
KIND='prepared_operating_reports_200_debug_classes_task_engineering'
TERMINAL_KIND='complete_operating_reports_200_debug_classes_task_engineering'
STAGES=('DBG_input1','DBG_input2','equivalent','DBG_missed_root','extra_change')
COUNTS={'business':93510,'formulas':88676,'NA':4834,'S800':800,'SG4000':4000,'growth':3200}

if hashlib.sha256(ANCESTOR.read_bytes()).hexdigest()!=ANCESTOR_SHA:raise ValueError('The frozen original task workflow changed')
loader=importlib.util.spec_from_file_location('_class_DBG_frozen_workflow',ANCESTOR)
base=importlib.util.module_from_spec(loader);loader.loader.exec_module(base)
_N={**vars(base),'__file__':str(Path(__file__).resolve()),'__name__':'_private_full_class_DBG_workflow',
    'KIND':KIND,'TERMINAL_KIND':TERMINAL_KIND,'STAGES':STAGES}
for name,value in vars(base).items():
    if isinstance(value,FunctionType) and value.__globals__ is vars(base):
        copied=FunctionType(value.__code__,_N,value.__name__,value.__defaults__,value.__closure__)
        copied.__kwdefaults__=deepcopy(value.__kwdefaults__);_N[name]=copied
reference,checked,read,write,require=(_N[name] for name in ('reference','checked','read','write','require'))
source=variants=None


def _activate():
    global source,variants
    require(len(DESIGN_SHA)==64 and reference(DESIGN)['sha256']==DESIGN_SHA,
        'The final complete-class design must be frozen before admission')
    require(reference(SOURCE_SCRIPT)['sha256']==SOURCE_SHA,'The original genuine healthy source3 provider changed')
    if source is None:
        spec=importlib.util.spec_from_file_location('_class_DBG_healthy_source',SOURCE_SCRIPT)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        source=SimpleNamespace(**{**module._ns,**vars(module)})
    if variants is None:
        from sheets_factory.workbook.operating_reports_200 import debug_class_variants
        variants=debug_class_variants
    require(source.SOURCE_KIND==SOURCE_KIND,'An unrelated source cannot provide the unchanged C00 goal')
    _N.update(source=source,AuditStore=source.AuditStore,DashboardServer=source.DashboardServer,
        ProducerLease=source.ProducerLease,ThreadCappedResourceLibreOfficeEngine=source.ThreadCappedResourceLibreOfficeEngine)
    return source,variants


def recipes():
    s,v=_activate();require(reference(ANCESTOR)['sha256']==ANCESTOR_SHA,'The original task workflow changed')
    return {**s.recipes(),**v.recipes(),**{str(Path(p).resolve()):reference(p) for p in
        (__file__,ANCESTOR,SOURCE_SCRIPT,DESIGN,base.streaming_verifier.__file__)}}


def verify_definitions(path,definition,*,blank=False):
    s,_=_activate();require(blank is False,'This task family has no FM mask');book=s._book(path)
    try:
        require(book.sheetnames==definition['sheetnames'] and book.calculation.iterate is not True,
            'Task sheets or the noncircular calculation policy changed')
        formulas={ws.title+'!'+c.coordinate:c.value for ws in book for c in ws._cells.values() if c.data_type=='f'}
        wanted=definition['formulas']
        require(set(formulas)==set(wanted) and all(s.formula_signature(formulas[p])==s.formula_signature(wanted[p]) for p in wanted),
            'The complete declared formula inventory or original healthy history changed')
        literals={ws.title+'!'+c.coordinate:s.typed(c.value) for ws in book for c in ws._cells.values()
            if c.value is not None and c.data_type!='f'}
        require(literals==definition['literals'],'Provided facts, public policies, history or NA literals changed')
    finally:book.close()


def verify_input_caches(path,expected,*,blank,definition):
    require(blank is False,'Only DBG inputs are admitted')
    observed=_N['snapshot'](path,expected)['values']
    require(not any(v['type']=='error' for v in observed.values()),'The DBG input contains a native error')
    require(all(observed.get(p,{}).get('type')==target['type'] for p,target in expected.items()),
        'Complete report type/NA coverage changed')
    require(all(observed.get(p)!=expected[p] for p in definition['DBG_root_points']),
        'Every predeclared fault root must have a nonzero primary2dp value impact')


def _roots(plan,bindings,original):
    variant=plan['variant_id'];faults=plan['DBG_faults']
    require(variant in ('S800','SG4000') and len(faults)==COUNTS[variant],
        'Keep every member of the predeclared complete fault class')
    families={'associate_presentation_sign':COUNTS['S800']}
    if variant=='SG4000':families['ratio_as_quarterly_change']=COUNTS['growth']
    require(Counter(row['family'] for row in faults.values())==families,'The complete class families changed')
    rows=[]
    for key,row in faults.items():
        b=bindings['financial'][key];point=row['sheet']+'!'+row['cell']
        require((row['sheet'],row['cell'])==(b['sheet'],b['cell']) and point in original['formulas']
            and point not in original['literals'] and original['formulas'][point]==row['healthy_formula']
            and row['faulty_formula']!=row['healthy_formula'],'A complete fault root differs from its genuine healthy formula/binding')
        rows.append({'semantic_key':key,**row})
    require(len({r['sheet']+'!'+r['cell'] for r in rows})==len(rows),'Duplicate physical fault roots are forbidden')
    return rows


def _bound_material(envelope,variant):
    s,v=_activate();require(variant in ('S800','SG4000'),'Use a predeclared complete fault class')
    require(envelope['sha256']==ENVELOPE_SHA,'Use the exact jointly frozen original two-variant prospective')
    frozen=v.validate_frozen(envelope)
    require(frozen['variant_order']==['S800','SG4000'] and set(frozen['variants'])=={'S800','SG4000'},
        'Both original complete plans must be frozen before any workbook transformation')
    lineage=frozen['lineage'];plan=read(frozen['variants'][variant]['view_plans'])
    actual=s.validate_source(lineage['source_manifest'])
    require(actual['kind']==SOURCE_KIND and actual['version']==1 and actual['passed'] is True
        and actual['source']==lineage['genuine_healthy_goal'] and actual['source']==actual['actual_calls'][-1]['output'],
        'Only the original genuinely completed healthy C00 source3 may be reused')
    sf=s.validate_prepared(checked(actual['preparation']).parent)
    require(actual['preparation']==lineage['source_preparation'] and sf['candidate_manifest']==lineage['original_candidate']
        and sf['specification']==lineage['specification'] and sf['bindings']==lineage['bindings']
        and sf['definition']==lineage['healthy_definition'],'The original raw/source/goal lineage changed')
    candidate,bindings,definition,expected=(read(sf[k]) for k in ('candidate_manifest','bindings','definition','expected'))
    require(len(expected)==len(bindings['financial'])==COUNTS['business'] and len(definition['formulas'])==COUNTS['formulas']
        and len(expected)-len(definition['formulas'])==COUNTS['NA'],'Complete source business/formula/NA scope is required')
    return frozen,plan,actual,sf,candidate,bindings,definition,expected


def _actions(rows,original):
    root=rows[0];rp=(root['sheet'],root['cell'])
    require('ReadMe!A1' in original['literals'],'Use the original nonfinancial extra-change point')
    return {'DBG_input':{(r['sheet'],r['cell']):('formula',r['faulty_formula']) for r in rows},
        'equivalent':{rp:('formula','=0+('+root['healthy_formula'].lstrip('=')+')')},
        'DBG_missed_root':{rp:('formula',root['faulty_formula'])},
        'extra_change':{('ReadMe','A1'):('text',original['literals']['ReadMe!A1']['value']+' [control]')}}


def prepare(envelope,variant,output):
    output=Path(output).absolute()
    require(output==output.resolve() and output.is_relative_to(ROOT/'outputs') and not output.exists(),
        'Use a fresh private complete-class DBG engineering directory')
    envelope_ref=envelope if isinstance(envelope,dict) else reference(envelope);checked(envelope_ref)
    frozen,plan,actual,sf,candidate,bindings,original,expected=_bound_material(envelope_ref,variant)
    rows=_roots(plan,bindings,original);root=rows[0];point=root['sheet']+'!'+root['cell'];rp=(root['sheet'],root['cell'])
    proof=read(frozen['variants'][variant]['proof'])
    require(proof['all_roots_exact_nonzero_primary_impact'] is True,'The deterministic first control root needs its retained exact nonzero proof')
    definition={**deepcopy(original),'DBG_root_points':[r['sheet']+'!'+r['cell'] for r in rows]}
    dbg=deepcopy(definition)
    for row in rows:dbg['formulas'][row['sheet']+'!'+row['cell']]=row['faulty_formula']
    target={'semantic_key':root['semantic_key'],'sheet':root['sheet'],'cell':root['cell'],
        'healthy_formula':root['healthy_formula'],'faulty_formula':root['faulty_formula'],
        'selection_rule':'First declared root; every root is independently proved nonzero. No roots filtered.'}
    require('ReadMe!A1' in original['literals'] and 'ReadMe!A1' not in expected,'Use the original nonfinancial extra-change point')
    changes=_actions(rows,original)
    s,_=_activate();output.mkdir(parents=True);folder=output/'planned';folder.mkdir();inputs={};edits={};clearances={}
    for name,actions in changes.items():
        intermediate=folder/(name+'.edited.xlsx');edits[name]=_N['transform'](checked(actual['source']),intermediate,actions)
        path=folder/(name+'.xlsx');clearances[name]=s.clear_all_formula_caches(intermediate,path);inputs[name]=reference(path)
    instruction=folder/'debugging_instruction.md';shutil.copyfile(checked(candidate['views']['debugging']['instruction']),instruction)
    verify_definitions(checked(inputs['DBG_input']),dbg)
    return write(output/'preparation.json',{'kind':KIND,'version':1,'variant_id':variant,'variant_envelope':envelope_ref,
        'variant_plans':frozen['variants'][variant],'source_manifest':frozen['lineage']['source_manifest'],
        'source_preparation':actual['preparation'],'genuine_goal':actual['source'],'candidate_preparation':sf['candidate_manifest'],
        'specification':sf['specification'],'bindings':sf['bindings'],'expected':sf['expected'],'source_definition':sf['definition'],
        'definition':write(output/'definition.private.json',definition),'DBG_definition':write(output/'DBG_definition.private.json',dbg),
        'control_target':target,'planned_inputs':inputs,'instruction_bytes':{'debugging':reference(instruction)},
        'exact_edits':edits,'all_formula_cache_clearances':clearances,'stage_order':list(STAGES),'mode_order':['debugging'],
        'required_actual_LO_calls':5,'all_modes_and_controls_frozen_before_first_actual_call':True,
        'reuse_genuine_source3_goal_and_two_stabilities':True,'financial_target_count':COUNTS['business'],
        'independent_business_field_count':COUNTS['business'],'formula_count':COUNTS['formulas'],'report_NA_count':COUNTS['NA'],
        'DBG_formula_root_count':len(rows),'complete_D_counts_pending_actual_input_calculation':True,
        'runtime_profile':sf['runtime_profile'],'runtime_profile_value':sf['runtime_profile_value'],'recipe':recipes(),
        'actual_LO_calls':0,'new_source_LO_calls':0,'new_financial_forwards':0,'model_calls':0,
        'qualified':False,'normal_all12_QA_passed':False,'difficulty_claimed':False})


def validate_prepared(output):
    f=read(Path(output)/'preparation.json')
    require(f['kind']==KIND and f['version']==1 and f['recipe']==recipes() and f['stage_order']==list(STAGES)
        and f['mode_order']==['debugging'] and f['required_actual_LO_calls']==5
        and f['all_modes_and_controls_frozen_before_first_actual_call'] is True
        and f['financial_target_count']==f['independent_business_field_count']==COUNTS['business']
        and f['formula_count']==COUNTS['formulas'] and f['report_NA_count']==COUNTS['NA']
        and f['actual_LO_calls']==f['new_source_LO_calls']==f['new_financial_forwards']==f['model_calls']==0
        and f['qualified'] is f['normal_all12_QA_passed'] is f['difficulty_claimed'] is False,
        'The exact complete-class DBG-only protocol or zero-call preparation changed')
    s,v=_activate();require(f['variant_envelope']['sha256']==ENVELOPE_SHA,'The jointly frozen two-variant prospective changed')
    frozen=v.validate_frozen(f['variant_envelope']);lineage=frozen['lineage'];variant=f['variant_id']
    require(variant in ('S800','SG4000') and f['variant_plans']==frozen['variants'][variant]
        and all(f[key]==lineage[name] for key,name in (('source_manifest','source_manifest'),('source_preparation','source_preparation'),
            ('genuine_goal','genuine_healthy_goal'),('candidate_preparation','original_candidate'),('specification','specification'),
            ('bindings','bindings'),('source_definition','healthy_definition'))),'The selected class or immutable original source lineage changed')
    for key in ('expected','definition','DBG_definition','runtime_profile'):checked(f[key])
    sf=read(f['source_preparation']);candidate=read(f['candidate_preparation']);original=read(f['source_definition'])
    expected=read(f['expected']);bindings=read(f['bindings']);plan=read(f['variant_plans']['view_plans']);rows=_roots(plan,bindings,original)
    require(all(sf[key]==f[key] for key in ('specification','bindings','expected','runtime_profile','runtime_profile_value'))
        and sf['definition']==f['source_definition'] and sf['candidate_manifest']==f['candidate_preparation']
        and len(expected)==COUNTS['business'] and len(original['formulas'])==COUNTS['formulas']
        and len(expected)-len(original['formulas'])==COUNTS['NA'] and f['DBG_formula_root_count']==len(rows),
        'The full genuine report/NA/financial scope or physical source preparation changed')
    definition={**deepcopy(original),'DBG_root_points':[r['sheet']+'!'+r['cell'] for r in rows]};dbg=deepcopy(definition)
    for row in rows:dbg['formulas'][row['sheet']+'!'+row['cell']]=row['faulty_formula']
    require(read(f['definition'])==definition and read(f['DBG_definition'])==dbg,'An unplanned healthy or faulty definition changed')
    root=rows[0]
    require(f['control_target']=={'semantic_key':root['semantic_key'],'sheet':root['sheet'],'cell':root['cell'],
        'healthy_formula':root['healthy_formula'],'faulty_formula':root['faulty_formula'],
        'selection_rule':'First declared root; every root is independently proved nonzero. No roots filtered.'},
        'The fixed first declared nonzero control root changed')
    require(set(f['planned_inputs'])=={'DBG_input','equivalent','DBG_missed_root','extra_change'}
        and set(f['instruction_bytes'])=={'debugging'},'The complete DBG-only input/control inventory changed')
    verify_definitions(checked(f['planned_inputs']['DBG_input']),dbg)
    brief=candidate['views']['debugging']['instruction'];checked(brief);copy=f['instruction_bytes']['debugging'];checked(copy)
    require((brief['sha256'],brief['bytes'])==(copy['sha256'],copy['bytes']),'The original public business brief changed')
    for name,record in f['planned_inputs'].items():
        checked(record);clear=f['all_formula_cache_clearances'][name];edit=f['exact_edits'][name]
        require(clear['output']==record and clear['source']==edit['output'] and edit['source']==f['genuine_goal']
            and s._formula_cache_count(checked(record))==0,'Every planned input needs its exact wholly unseeded cache-clear chain')
        expected_edits=[{'sheet':sheet,'cell':cell,'kind':kind,'value':value}
            for (sheet,cell),(kind,value) in _actions(rows,original)[name].items()]
        require(edit['edits']==expected_edits and edit['all_other_cells_and_members_byte_preserved'] is True
            and clear['financial_formula_or_literal_edits']==0,
            'The complete input/equivalent/missed-root/extra-change surgery plan changed')
        wanted=deepcopy(definition)
        for (sheet,cell),(kind,value) in _actions(rows,original)[name].items():
            if kind=='formula':wanted['formulas'][sheet+'!'+cell]=value
            else:wanted['literals'][sheet+'!'+cell]={'type':'text','value':value}
        verify_definitions(checked(record),wanted)
    return f


def _actual_D_policy(f,count):return type(count) is int and count==COUNTS[f['variant_id']]


def _owned_cleanup_ok(cleanup,calls):
    ids=[call.get('actual_resource_evidence',{}).get('container_id') for call in calls]
    owned=cleanup.get('owned',[])
    return (cleanup.get('all_owned_containers_absent') is True and cleanup.get('daemon_reachable') is True
        and len(calls)==len(owned)==5
        and all(isinstance(cid,str) and re.fullmatch(r'[0-9a-fA-F]{64}',cid) for cid in ids)
        and len({cid.lower() for cid in ids})==5
        and all(row.get('absent') is True and isinstance(row.get('full_id'),str)
            and re.fullmatch(r'[0-9a-fA-F]{64}',row['full_id']) for row in owned)
        and {row['full_id'].lower() for row in owned}=={cid.lower() for cid in ids})


def _adapt_workflow():
    nodes=[];counts={'stability':0,'mode':0,'FM_branch':0,'cache':0,'calls':0,'previous':0,'initial':0,'title':0,'D':0,'cleanup':0}
    dtest=ast.dump(ast.parse("d > 0 and (prefix != 'FM' or d == f['financial_target_count'])",mode='eval').body,include_attributes=False)
    class DBG(ast.NodeTransformer):
        def visit_If(self,node):
            if ast.unparse(node.test)=="name.startswith('FM_input')":
                require(len(node.orelse)==1 and isinstance(node.orelse[0],ast.If),'The exact unused FM branch changed')
                counts['FM_branch']+=1;return self.visit(node.orelse[0])
            return self.generic_visit(node)
        def visit_For(self,node):
            if ast.unparse(node.iter)=="('FM', 'DBG')":node.iter=ast.parse("('DBG',)",mode='eval').body;counts['stability']+=1
            elif ast.unparse(node.iter)=="[('financial_modeling', 'FM'), ('debugging', 'DBG')]":
                node.iter=ast.parse("[('debugging', 'DBG')]",mode='eval').body;counts['mode']+=1
            return self.generic_visit(node)
        def visit_Tuple(self,node):
            if ast.unparse(node)=="('FM_input2', 'DBG_input2')":counts['previous']+=1;return ast.parse("('DBG_input2',)",mode='eval').body
            if ast.unparse(node)=="('FM_input1', 'DBG_input1')":counts['initial']+=1;return ast.parse("('DBG_input1',)",mode='eval').body
            return self.generic_visit(node)
        def visit_Call(self,node):
            node=self.generic_visit(node)
            if isinstance(node.func,ast.Name) and node.func.id=='verify_input_caches':
                counts['cache']+=1;node.keywords.append(ast.keyword(arg='definition',value=ast.Name('definition',ast.Load())))
            if isinstance(node.func,ast.Name) and node.func.id=='require' and len(node.args)==2 and isinstance(node.args[1],ast.Constant):
                if node.args[1].value=='Owned task cleanup incomplete or unknown':
                    counts['cleanup']+=1;node.args[0]=ast.parse('_owned_cleanup_ok(cleanup,calls)',mode='eval').body
                elif node.args[1].value=='Cleanup does not cover five actual owned IDs':
                    counts['cleanup']+=1;node.args[0]=ast.parse("_owned_cleanup_ok(cleanup,t['actual_calls'])",mode='eval').body
            return node
        def visit_BoolOp(self,node):
            if ast.dump(node,include_attributes=False)==dtest:
                counts['D']+=1;return ast.copy_location(ast.parse('d > 0 and _actual_D_policy(f,d)',mode='eval').body,node)
            return self.generic_visit(node)
        def visit_Constant(self,node):
            if type(node.value) is int and node.value==8:counts['calls']+=1;node.value=5
            elif node.value=='Equity-income FM/DBG engineering':counts['title']+=1;node.value='Whole-class report DBG engineering'
            elif node.value=='Cleanup does not cover eight actual owned IDs':node.value='Cleanup does not cover five actual owned IDs'
            return node
    for node in ast.parse(ANCESTOR.read_bytes()).body:
        if isinstance(node,ast.FunctionDef) and node.name in ('execute_prepared','validate_completed','_stage_source'):
            if node.name!='_stage_source':node.name='_'+node.name+'_DBG'
            nodes.append(DBG().visit(node))
    require(counts=={'stability':1,'mode':2,'FM_branch':2,'cache':2,'calls':3,'previous':1,'initial':1,'title':1,'D':1,'cleanup':2},
        'The exact five-stage DBG adaptation changed: '+str(counts))
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),str(ANCESTOR),'exec'),_N)
    return counts


ADAPTATION_COUNTS=_adapt_workflow()
_N.update(recipes=recipes,validate_prepared=validate_prepared,verify_definitions=verify_definitions,
    verify_input_caches=verify_input_caches,_actual_D_policy=_actual_D_policy,_owned_cleanup_ok=_owned_cleanup_ok)


def execute_prepared(output):_activate();return _N['_execute_prepared_DBG'](output)


def validate_completed(value):
    _activate();t=_N['_validate_completed_DBG'](value);f=validate_prepared(checked(t['preparation']).parent)
    count=t['records']['modes']['debugging']['complete_D_count']
    require(set(t['records']['modes'])=={'debugging'} and t['source_LO_calls_reused']==3 and _actual_D_policy(f,count),
        'The complete selected DBG changed set must contain exactly800 or4000 cells')
    return t


@contextmanager
def admission_monitor(output,phase):
    """Start a separate fresh panel before slow, read-only admission checks."""
    output=Path(output).absolute();folder=output.parent/(output.name+'.'+phase+'.monitor.'+uuid4().hex)
    audit=base.AuditStore(folder,{'id':folder.name,'name':'Whole-class DBG admission and engineering',
        'status':'running','phase':phase,'producer_pid':os.getpid(),'producer_active':True,'qualified':False,'model_calls':0})
    server=base.DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=0)
    stop=threading.Event();started=time.monotonic();passed=False
    def heartbeat():
        while not stop.wait(10):audit.update_run(elapsed_seconds=time.monotonic()-started);audit.export()
    pulse=None
    try:
        url=server.start();audit.update_run(dashboard_url=url);audit.export()
        print(json.dumps({'admission_dashboard_url':url,'producer_pid':os.getpid(),'phase':phase}),flush=True)
        pulse=threading.Thread(target=heartbeat,daemon=True);pulse.start()
        yield
        passed=True
    finally:
        stop.set()
        if pulse:pulse.join(timeout=1)
        audit.update_run(status='completed' if passed else 'failed',producer_active=False,elapsed_seconds=time.monotonic()-started)
        audit.export();server.stop();audit.db.close()


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--envelope',type=Path);p.add_argument('--variant',choices=('S800','SG4000'))
    p.add_argument('--output',type=Path);p.add_argument('--prepared',type=Path);p.add_argument('--run',action='store_true');args=p.parse_args(argv)
    if args.prepared:
        require(args.envelope is None and args.variant is None and args.output is None,'Use the exact existing preparation')
        with admission_monitor(args.prepared,'run' if args.run else 'validate'):
            result=execute_prepared(args.prepared) if args.run else validate_prepared(args.prepared)
    else:
        require(not args.run and args.envelope is not None and args.variant is not None and args.output is not None,
            'Prepare and review the frozen complete class before a separate actual run')
        with admission_monitor(args.output,'prepare'):result=prepare(args.envelope,args.variant,args.output)
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
