#!/usr/bin/env python3
"""One eight-calculation FM/DBG engineering attempt after genuine source3."""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import FunctionType, SimpleNamespace

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'));sys.dont_write_bytecode=True
ANCESTOR=ROOT/'scripts/validate_equity_income_group_tasks.py'
ANCESTOR_SHA='bcc07848ed5b868c9cb943e3058aa10980b9399d4d53a8d17220d60748a85f0c'
SOURCE_SCRIPT=ROOT/'scripts/build_waterfall_portfolios_source_revision2.py'
SOURCE_SHA='c97e9ad53f537a2c3550599a1507d8c1f4654bcad364ba8140276c0287ec7550'
KIND='prepared_waterfall_portfolios_task_engineering'
TERMINAL_KIND='complete_waterfall_portfolios_task_engineering'
COUNTS={'financial':189600,'forecast':170640,'roots':1296,'historical':18960}

if hashlib.sha256(ANCESTOR.read_bytes()).hexdigest()!=ANCESTOR_SHA:raise ValueError('The original eight-stage lifecycle changed')
_spec=importlib.util.spec_from_file_location('_waterfall_task8_frozen_ancestor',ANCESTOR)
base=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(base)
reference,checked,read,write,require=base.reference,base.checked,base.read,base.write,base.require
STAGES=base.STAGES
source=None
_ns={**vars(base),'__file__':str(Path(__file__).resolve()),'__name__':'_isolated_waterfall_task8',
     'KIND':KIND,'TERMINAL_KIND':TERMINAL_KIND}
for _name,_value in vars(base).items():
    if isinstance(_value,FunctionType) and _value.__globals__ is vars(base):
        _ns[_name]=FunctionType(_value.__code__,_ns,_value.__name__,_value.__defaults__,_value.__closure__)


def _activate():
    global source
    require(SOURCE_SHA!='PENDING_SOURCE_REVISION_PIN' and reference(SOURCE_SCRIPT)['sha256']==SOURCE_SHA,
            'A final genuine waterfall source revision must be pinned before any task admission')
    if source is None:
        spec=importlib.util.spec_from_file_location('_waterfall_task8_genuine_source',SOURCE_SCRIPT)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        source=SimpleNamespace(**{**module._N,**vars(module)})
    _ns.update(source=source,AuditStore=source.AuditStore,DashboardServer=source.DashboardServer,
        ProducerLease=source.ProducerLease,ThreadCappedResourceLibreOfficeEngine=source.ThreadCappedResourceLibreOfficeEngine)
    return source


def recipes():
    support=_activate()
    return {**support.recipes(),str(Path(__file__).resolve()):reference(__file__),
        str(ANCESTOR):reference(ANCESTOR),str(Path(base.streaming_verifier.__file__).resolve()):reference(base.streaming_verifier.__file__)}


def _control_root(sf,roots):
    forward=sf['financial_evidence']['forward_A'];a_terminal=read(forward)
    values_ref=a_terminal['result'];values=read(values_ref)
    for index,root in enumerate(roots):
        paid=values['rows'][root['row_key']]['preference_paid']
        require(type(paid) is int and paid>=0,'A stored preference payment must be an exact nonnegative penny amount')
        if paid>0:
            return {'declared_index':index,'root':root,'stored_forward_A':forward,'stored_A_result':values_ref,
                'preference_paid_pence':paid,'expected_local_wrong_delta_pence':2*paid,
                'selection_rule':'First declared root with stored independent A preference_paid>0; all roots retained.',
                'selected_before_any_actual_task_call':True}
    raise ValueError('No declared positive-impact root exists for the required missed-root negative control')


def verify_definitions(path,definition,*,blank=False):
    s=_activate();book=s._book(path)
    try:
        require(book.sheetnames==definition['sheetnames'],'Task worksheet structure changed')
        formulas={ws.title+'!'+c.coordinate:c.value for ws in book for c in ws._cells.values() if c.data_type=='f'}
        mask=set(definition['FM_mask_points'])
        wanted={p:f for p,f in definition['formulas'].items() if not blank or p not in mask}
        require(set(formulas)==set(wanted) and all(s.formula_signature(formulas[p])==s.formula_signature(wanted[p]) for p in wanted),
                'Full waterfall task definitions or partial FM scope changed')
        literals={ws.title+'!'+c.coordinate:s.typed(c.value) for ws in book for c in ws._cells.values() if c.value is not None and c.data_type!='f'}
        require(literals==definition['literals'],'Raw facts, policies, layout labels or protected context changed')
        require(book.calculation is not None and book.calculation.iterate in (None,False),'The noncircular task may not become iterative')
        for point in definition['Boolean_General_points']:
            if point in formulas:
                sheet,cell=point.rsplit('!',1);require(book[sheet][cell].number_format=='General','Boolean business status requires General format')
    finally:book.close()


def verify_input_caches(path,expected,*,blank,definition):
    observed=_ns['snapshot'](path,expected)['values'];mask=set(definition['FM_mask_points'])
    for point,wanted in expected.items():
        if blank and point in mask:require(point not in observed,'A masked forecast output has a cached value')
        else:
            require(observed.get(point,{}).get('type')==wanted['type'],'A retained financial cache is missing, an error, or the wrong type')
            if blank:require(observed[point]==wanted,'Provided historical financial results changed in the FM input')


def prepare(source_manifest,output):
    s=_activate();output=Path(output).absolute()
    require(output==output.resolve() and not output.exists(),'Use a fresh task-engineering directory')
    actual=s.validate_source(source_manifest);sf=s.validate_prepared(checked(actual['preparation']).parent)
    candidate=read(sf['candidate_manifest']);bindings=read(sf['bindings']);source_definition=read(sf['definition']);expected=read(sf['expected'])
    roots=bindings['DBG_root_edits'];mask=bindings['FM_mask_points']
    require(len(expected)==len(source_definition['formulas'])==COUNTS['financial'] and len(mask)==len(set(mask))==COUNTS['forecast']
        and len(roots)==COUNTS['roots'] and len(source_definition['formulas'])-len(mask)==COUNTS['historical'],
        'All financial projections, forecast outputs and original fault locations must be retained')
    require(actual['source']==actual['actual_calls'][-1]['output'] and set(mask)<=set(expected),
            'Use only the genuine cold-start source3 goal and declared formula projections')
    for r in roots:
        p=r['sheet']+'!'+r['cell']
        require(r['field']=='after_preference_cash' and p in mask
            and s.formula_signature(source_definition['formulas'][p])==s.formula_signature(r['before']),
            'A predeclared forecast sign root differs from the genuine source')
    selected=_control_root(sf,roots);root=selected['root'];rp=(root['sheet'],root['cell'])
    definition=deepcopy(source_definition);definition['FM_mask_points']=list(mask)
    definition['Boolean_General_points']=[p for p,v in expected.items() if v['type']=='boolean']
    output.mkdir(parents=True);planned=output/'planned';planned.mkdir();goal=actual['source']
    correct=source_definition['formulas'][root['sheet']+'!'+root['cell']]
    cases={'FM_input':{tuple(p.rsplit('!',1)):('blank',None) for p in mask},
        'DBG_input':{(r['sheet'],r['cell']):('formula',r['after']) for r in roots},
        'equivalent':{rp:('formula','=0+('+correct.lstrip('=')+')')},
        'FM_missed_root':{rp:('blank',None)},'DBG_missed_root':{rp:('formula',root['after'])},
        'extra_change':{('Read Me','A1'):('text',definition['literals']['Read Me!A1']['value']+' [control]')}}
    plans={};edits={};clearances={}
    for name,changes in cases.items():
        intermediate=planned/(name+'.edited.xlsx');edits[name]=_ns['transform'](checked(goal),intermediate,changes)
        target=planned/(name+'.xlsx');clearances[name]=s.clear_all_formula_caches(intermediate,target);plans[name]=reference(target)
    instructions={}
    for mode in ('financial_modeling','debugging'):
        target=planned/(mode+'_instruction.md');shutil.copyfile(checked(candidate['views'][mode]['instruction']),target);instructions[mode]=reference(target)
    dbg=deepcopy(definition)
    for r in roots:dbg['formulas'][r['sheet']+'!'+r['cell']]=r['after']
    verify_definitions(checked(plans['FM_input']),definition,blank=True);verify_definitions(checked(plans['DBG_input']),dbg)
    return write(output/'preparation.json',{'kind':KIND,'version':1,'source_manifest':reference(source_manifest['path'] if isinstance(source_manifest,dict) else source_manifest),
        'genuine_goal':goal,'source_preparation':actual['preparation'],'candidate_preparation':sf['candidate_manifest'],
        'specification':sf['specification'],'source_definition':sf['definition'],
        'definition':write(output/'definition.private.json',definition),'expected':sf['expected'],'bindings':sf['bindings'],
        'DBG_definition':write(output/'DBG_definition.private.json',dbg),'control_root_selection':selected,
        'planned_inputs':plans,'instruction_bytes':instructions,'exact_edits':edits,'all_formula_cache_clearances':clearances,
        'stage_order':list(STAGES),'mode_order':['financial_modeling','debugging'],'required_actual_LO_calls':8,
        'all_modes_and_controls_frozen_before_first_actual_call':True,'reuse_genuine_source3_goal_and_two_stabilities':True,
        'financial_target_count':COUNTS['financial'],'forecast_mask_count':COUNTS['forecast'],'historical_formula_count':COUNTS['historical'],
        'DBG_formula_root_count':COUNTS['roots'],'complete_D_counts_pending_actual_input_calculation':True,
        'runtime_profile':sf['runtime_profile'],'runtime_profile_value':sf['runtime_profile_value'],'recipe':recipes(),
        'actual_LO_calls':0,'new_financial_forwards':0,'model_calls':0,'qualified':False,'normal_all12_QA_passed':False})


def validate_prepared(output):
    s=_activate();f=read(Path(output)/'preparation.json')
    require(f['kind']==KIND and f['version']==1 and f['recipe']==recipes() and f['stage_order']==list(STAGES)
        and f['required_actual_LO_calls']==8 and f['all_modes_and_controls_frozen_before_first_actual_call'] is True
        and f['financial_target_count']==COUNTS['financial'] and f['forecast_mask_count']==COUNTS['forecast']
        and f['historical_formula_count']==COUNTS['historical'] and f['DBG_formula_root_count']==COUNTS['roots'],
        'The family, exact recipe, complete scope or eight-stage protocol changed')
    for key in ('source_manifest','genuine_goal','source_preparation','candidate_preparation','specification','source_definition','definition','expected','bindings','DBG_definition','runtime_profile'):checked(f[key])
    for group in ('planned_inputs','instruction_bytes'):
        for r in f[group].values():checked(r)
    actual,sf,candidate=read(f['source_manifest']),read(f['source_preparation']),read(f['candidate_preparation'])
    require(actual['source']==f['genuine_goal'] and actual['preparation']==f['source_preparation']
        and sf['candidate_manifest']==f['candidate_preparation'] and sf['definition']==f['source_definition']
        and sf['specification']==f['specification'] and sf['expected']==f['expected'] and sf['bindings']==f['bindings']
        and sf['runtime_profile']==f['runtime_profile'] and sf['runtime_profile_value']==f['runtime_profile_value'],
        'Current source, goal, raw assumptions and complete expectations have different lineage')
    bindings=read(f['bindings']);definition=read(f['definition']);expected=read(f['expected']);dbg=read(f['DBG_definition'])
    wanted=deepcopy(read(f['source_definition']));wanted['FM_mask_points']=bindings['FM_mask_points']
    wanted['Boolean_General_points']=[p for p,v in expected.items() if v['type']=='boolean']
    require(definition==wanted and f['control_root_selection']==_control_root(sf,bindings['DBG_root_edits']),
            'The complete view or deterministic positive-impact control root changed')
    for r in bindings['DBG_root_edits']:wanted['formulas'][r['sheet']+'!'+r['cell']]=r['after']
    require(dbg==wanted,'A declared debugging fault was filtered or changed')
    verify_definitions(checked(f['planned_inputs']['FM_input']),definition,blank=True)
    verify_definitions(checked(f['planned_inputs']['DBG_input']),dbg)
    for mode,r in f['instruction_bytes'].items():
        original=candidate['views'][mode]['instruction'];checked(original)
        require((r['sha256'],r['bytes'])==(original['sha256'],original['bytes']),'The original concise public instruction changed')
    return f


def _adapt_common():
    tree=ast.parse(ANCESTOR.read_bytes());kept=[];cache_calls=0;fm_gate=0
    for node in tree.body:
        if not isinstance(node,ast.FunctionDef) or node.name not in ('execute_prepared','validate_completed'):continue
        original=node.name;node.name='_'+original+'_base'
        class Adapt(ast.NodeTransformer):
            def visit_Call(self,node):
                nonlocal cache_calls
                node=self.generic_visit(node)
                if isinstance(node.func,ast.Name) and node.func.id=='verify_input_caches':
                    require(not any(k.arg=='definition' for k in node.keywords),'The task cache scope seam changed')
                    node.keywords.append(ast.keyword(arg='definition',value=ast.Name(id='definition',ctx=ast.Load())));cache_calls+=1
                return node
            def visit_Subscript(self,node):
                nonlocal fm_gate
                node=self.generic_visit(node)
                if isinstance(node.value,ast.Name) and node.value.id=='f' and isinstance(node.slice,ast.Constant) and node.slice.value=='financial_target_count':
                    require(original=='execute_prepared','Unknown complete FM comparison seam')
                    node.slice.value='forecast_mask_count';fm_gate+=1
                return node
            def visit_Constant(self,node):
                if node.value=='Equity-income FM/DBG engineering':node.value='Waterfall FM/DBG engineering'
                return node
        kept.append(Adapt().visit(node))
    require(cache_calls==4 and fm_gate==1 and len(kept)==2,'The exact eight-stage scope adaptation changed')
    exec(compile(ast.fix_missing_locations(ast.Module(body=kept,type_ignores=[])),str(ANCESTOR),'exec'),_ns)


_adapt_common()
_ns.update(recipes=recipes,validate_prepared=validate_prepared,verify_definitions=verify_definitions,verify_input_caches=verify_input_caches)


def execute_prepared(output):
    _activate();return _ns['_execute_prepared_base'](output)


def validate_completed(value):
    _activate();return _ns['_validate_completed_base'](value)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-manifest',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--prepared',type=Path);p.add_argument('--run',action='store_true');args=p.parse_args(argv)
    if args.prepared:
        require(args.source_manifest is None and args.output is None,'Use the exact existing preparation')
        result=execute_prepared(args.prepared) if args.run else validate_prepared(args.prepared)
    else:
        require(not args.run and args.source_manifest is not None and args.output is not None,'Prepare and review before a separate actual --prepared --run')
        result=prepare(args.source_manifest,args.output)
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
