#!/usr/bin/env python3
"""One five-calculation FM engineering attempt after genuine cohort source3."""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
from types import FunctionType, SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
ANCESTOR=ROOT/'scripts/validate_equity_income_group_tasks.py'
ANCESTOR_SHA='bcc07848ed5b868c9cb943e3058aa10980b9399d4d53a8d17220d60748a85f0c'
SOURCE_SCRIPT=ROOT/'scripts/build_operating_reports_financial_cohort_source.py'
SOURCE_SHA='701a277f0b20ebe448fef3957735a37f117b1fe3acdc2c2c103def2351f851e0'
SOURCE_KIND='independently_checked_operating_reports_financial_cohort_source_v1'
KIND='prepared_operating_reports_financial_cohort_FM_task_engineering'
TERMINAL_KIND='complete_operating_reports_financial_cohort_FM_task_engineering'
STAGES=('FM_input1','FM_input2','equivalent','FM_missed_root','extra_change')
COUNTS={'business':93510,'formulas':88676,'forecast':62322,'NA':4834}

if hashlib.sha256(ANCESTOR.read_bytes()).hexdigest()!=ANCESTOR_SHA:
    raise ValueError('The frozen original task workflow changed')
loader=importlib.util.spec_from_file_location('_cohort_FM_frozen_workflow',ANCESTOR)
base=importlib.util.module_from_spec(loader);loader.loader.exec_module(base)
_N={**vars(base),'__file__':str(Path(__file__).resolve()),'__name__':'_private_cohort_FM_workflow',
    'KIND':KIND,'TERMINAL_KIND':TERMINAL_KIND,'STAGES':STAGES}
for name,value in vars(base).items():
    if isinstance(value,FunctionType) and value.__globals__ is vars(base):
        _N[name]=FunctionType(value.__code__,_N,value.__name__,value.__defaults__,value.__closure__)
reference,checked,read,write,require=(_N[name] for name in ('reference','checked','read','write','require'))
source=None


def _activate():
    global source
    require(SOURCE_SHA!='PENDING_COHORT_SOURCE_PIN' and reference(SOURCE_SCRIPT)['sha256']==SOURCE_SHA,
        'The final genuine cohort source provider must be pinned before admission')
    if source is None:
        loader=importlib.util.spec_from_file_location('_cohort_FM_genuine_source',SOURCE_SCRIPT)
        module=importlib.util.module_from_spec(loader);loader.loader.exec_module(module)
        source=SimpleNamespace(**{**module._N,**vars(module)})
    require(source.SOURCE_KIND==SOURCE_KIND,'An unrelated source family cannot enter the FM cohort')
    _N.update(source=source,AuditStore=source.AuditStore,DashboardServer=source.DashboardServer,
        ProducerLease=source.ProducerLease,ThreadCappedResourceLibreOfficeEngine=source.ThreadCappedResourceLibreOfficeEngine)
    return source


def recipes():
    s=_activate();require(reference(ANCESTOR)['sha256']==ANCESTOR_SHA,'The original task workflow changed')
    return {**s.recipes(),**{str(Path(p).resolve()):reference(p) for p in
        (__file__,ANCESTOR,base.streaming_verifier.__file__)}}


def forecast_keys(public):
    return [key for key,kind in _activate().schema.points(public) if kind!='text'
        and key.split('/')[1].startswith(('2026','2027','FY2026','FY2027'))]


def verify_definitions(path,definition,*,blank=False):
    s=_activate();book=s._book(path)
    try:
        require(book.sheetnames==definition['sheetnames'] and book.calculation.iterate is not True,
            'Task sheets or the noncircular calculation policy changed')
        mask=set(definition['FM_mask_points'])
        wanted={p:f for p,f in definition['formulas'].items() if not blank or p not in mask}
        formulas={ws.title+'!'+c.coordinate:c.value for ws in book for c in ws._cells.values() if c.data_type=='f'}
        require(set(formulas)==set(wanted) and all(s.formula_signature(formulas[p])==s.formula_signature(wanted[p]) for p in wanted),
            'The exact financial formula inventory or complete FM scope changed')
        literals={ws.title+'!'+c.coordinate:s.typed(c.value) for ws in book for c in ws._cells.values()
            if c.value is not None and c.data_type!='f'}
        require(literals==definition['literals'],'Provided inputs, public policies, historical literals or NA changed')
    finally:book.close()


def verify_input_caches(path,expected,*,blank,definition):
    require(blank is True,'This entry admits only financial-modeling inputs')
    observed=_N['snapshot'](path,expected)['values'];mask=set(definition['FM_mask_points'])
    require(not any(v['type']=='error' for v in observed.values()),'The FM input contains a native error')
    for point,target in expected.items():
        require(point not in observed if point in mask else observed.get(point)==target,
            'A forecast cache is present or a retained historical/NA report value changed')


def _control_target(plans,bindings,expected):
    for key in plans['FM_mask']:
        b=bindings['financial'][key];point=b['sheet']+'!'+b['cell'];value=expected[point]
        if value['type']=='number' and Decimal(value['value'])!=0:
            return {'semantic_key':key,'sheet':b['sheet'],'cell':b['cell'],'expected_typed':value,
                'selection_rule':'First declared FM target with a nonzero independently checked primary value; no targets filtered.'}
    raise ValueError('A nonzero positive-control target is required')


def prepare(source_manifest,output):
    s=_activate();output=Path(output).absolute()
    require(output==output.resolve() and output.is_relative_to(ROOT/'outputs') and not output.exists(),
        'Use a fresh private FM task-engineering directory')
    actual=s.validate_source(source_manifest)
    require(actual['kind']==SOURCE_KIND and actual['version']==1 and actual['passed'] is True,
        'Only a genuine completed cohort source3 can enter task engineering')
    sf=s.validate_prepared(checked(actual['preparation']).parent)
    candidate,public,bindings,original,expected=(read(sf[k]) for k in
        ('candidate_manifest','specification','bindings','definition','expected'))
    plans=read(candidate['view_plans']);s.schema.validate_spec(public)
    case_id=s.schema.candidate(public['seed'])['candidate_id']
    require(candidate['kind']=='prepared_unverified_operating_reports_financial_cohort_fm_emission'
        and candidate['version']==1 and candidate['candidate_id']==sf['case_id']==case_id
        and actual['source']==actual['actual_calls'][-1]['output'],
        'Use the genuine source3 physical goal and its exact original cohort identity')
    keys=forecast_keys(public)
    require(plans['FM_mask']==keys and len(keys)==len(set(keys))==COUNTS['forecast']
        and len(expected)==len(bindings['financial'])==COUNTS['business']
        and len(original['formulas'])==COUNTS['formulas']
        and len(expected)-len(original['formulas'])==COUNTS['NA'],
        'The complete report, forecast, historical and NA inventories are required')
    mask=[bindings['financial'][key]['sheet']+'!'+bindings['financial'][key]['cell'] for key in keys]
    require(len(set(mask))==len(mask) and set(mask)<=set(original['formulas']),
        'Every declared forecast target must bind one unique formula cell')
    target=_control_target(plans,bindings,expected);point=target['sheet']+'!'+target['cell'];rp=(target['sheet'],target['cell'])
    definition={**deepcopy(original),'FM_mask_points':sorted(mask)};correct=original['formulas'][point]
    require('ReadMe!A1' not in expected,'The extra-change control must be outside all financial report fields')
    changes={'FM_input':{tuple(p.rsplit('!',1)):('blank',None) for p in mask},
        'equivalent':{rp:('formula','=0+('+correct.lstrip('=')+')')},'FM_missed_root':{rp:('blank',None)},
        'extra_change':{('ReadMe','A1'):('text',definition['literals']['ReadMe!A1']['value']+' [control]')}}
    output.mkdir(parents=True);planned=output/'planned';planned.mkdir();inputs={};edits={};clearances={}
    for name,actions in changes.items():
        intermediate=planned/(name+'.edited.xlsx');edits[name]=_N['transform'](checked(actual['source']),intermediate,actions)
        path=planned/(name+'.xlsx');clearances[name]=s.clear_all_formula_caches(intermediate,path);inputs[name]=reference(path)
    instruction=planned/'financial_modeling_instruction.md';shutil.copyfile(checked(candidate['views']['financial_modeling']['instruction']),instruction)
    verify_definitions(checked(inputs['FM_input']),definition,blank=True)
    return write(output/'preparation.json',{'kind':KIND,'version':1,'source_manifest':reference(source_manifest['path'] if isinstance(source_manifest,dict) else source_manifest),
        'source_preparation':actual['preparation'],'genuine_goal':actual['source'],'candidate_preparation':sf['candidate_manifest'],
        'specification':sf['specification'],'bindings':sf['bindings'],'expected':sf['expected'],'source_definition':sf['definition'],
        'raw_inventory':sf['raw_inventory'],'case_id':case_id,'definition':write(output/'definition.private.json',definition),
        'control_target':target,'planned_inputs':inputs,'instruction_bytes':{'financial_modeling':reference(instruction)},
        'exact_edits':edits,'all_formula_cache_clearances':clearances,'stage_order':list(STAGES),
        'mode_order':['financial_modeling'],'required_actual_LO_calls':5,'all_modes_and_controls_frozen_before_first_actual_call':True,
        'reuse_genuine_source3_goal_and_two_stabilities':True,'independent_business_field_count':COUNTS['business'],
        'financial_target_count':COUNTS['forecast'],'forecast_mask_count':COUNTS['forecast'],'formula_count':COUNTS['formulas'],
        'historical_formula_count':COUNTS['formulas']-COUNTS['forecast'],'report_NA_count':COUNTS['NA'],
        'runtime_profile':sf['runtime_profile'],'runtime_profile_value':sf['runtime_profile_value'],'recipe':recipes(),
        'actual_LO_calls':0,'new_financial_forwards':0,'model_calls':0,'qualified':False,'normal_all12_QA_passed':False})


def validate_prepared(output):
    s=_activate();f=read(Path(output)/'preparation.json')
    require(f['kind']==KIND and f['version']==1 and f['recipe']==recipes() and f['stage_order']==list(STAGES)
        and f['mode_order']==['financial_modeling'] and f['required_actual_LO_calls']==5
        and f['all_modes_and_controls_frozen_before_first_actual_call'] is True
        and f['financial_target_count']==f['forecast_mask_count']==COUNTS['forecast']
        and f['independent_business_field_count']==COUNTS['business'] and f['formula_count']==COUNTS['formulas']
        and f['historical_formula_count']==COUNTS['formulas']-COUNTS['forecast'] and f['report_NA_count']==COUNTS['NA']
        and f['actual_LO_calls']==f['new_financial_forwards']==f['model_calls']==0
        and f['qualified'] is False and f['normal_all12_QA_passed'] is False,'The fixed FM-only protocol or recipe changed')
    for key in ('source_manifest','source_preparation','genuine_goal','candidate_preparation','specification','bindings',
        'expected','source_definition','raw_inventory','definition','runtime_profile'):checked(f[key])
    for group in ('planned_inputs','instruction_bytes'):
        for record in f[group].values():checked(record)
    actual,sf,candidate,public,bindings,original,expected=(read(f[k]) for k in
        ('source_manifest','source_preparation','candidate_preparation','specification','bindings','source_definition','expected'))
    require(actual['kind']==SOURCE_KIND and actual['passed'] is True and actual['source']==f['genuine_goal']
        and actual['preparation']==f['source_preparation'] and sf['candidate_manifest']==f['candidate_preparation']
        and sf['case_id']==f['case_id']==candidate['candidate_id']==s.schema.candidate(public['seed'])['candidate_id']
        and all(sf[k]==f[k] for k in ('specification','bindings','expected','raw_inventory','runtime_profile','runtime_profile_value'))
        and sf['definition']==f['source_definition'],'The original raw identity, source3 and task lineage changed')
    plans=read(candidate['view_plans']);mask=[bindings['financial'][key]['sheet']+'!'+bindings['financial'][key]['cell'] for key in plans['FM_mask']]
    require(plans['FM_mask']==forecast_keys(public) and len(mask)==len(set(mask))==COUNTS['forecast']
        and len(expected)==COUNTS['business'] and len(original['formulas'])==COUNTS['formulas']
        and f['control_target']==_control_target(plans,bindings,expected),'The complete forecast scope or deterministic control target changed')
    definition=read(f['definition']);require(definition=={**original,'FM_mask_points':sorted(mask)},'A task changed the genuine source definitions')
    verify_definitions(checked(f['planned_inputs']['FM_input']),definition,blank=True)
    require(set(f['planned_inputs'])=={'FM_input','equivalent','FM_missed_root','extra_change'}
        and set(f['instruction_bytes'])=={'financial_modeling'},'A mode or frozen control plan changed')
    brief=candidate['views']['financial_modeling']['instruction'];checked(brief);copy=f['instruction_bytes']['financial_modeling']
    require((copy['sha256'],copy['bytes'])==(brief['sha256'],brief['bytes']),'The original public business brief changed')
    for name,record in f['planned_inputs'].items():
        clear=f['all_formula_cache_clearances'][name];edit=f['exact_edits'][name]
        require(clear['output']==record and clear['source']==edit['output'] and edit['source']==f['genuine_goal']
            and s._formula_cache_count(checked(record))==0,'Every planned input must retain its original unseeded cache-clear chain')
    return f


def _adapt_workflow():
    nodes=[];counts={'stability':0,'mode':0,'DBG_branch':0,'DBG_read':0,'cache':0,'calls':0,'previous':0,'initial':0,'title':0}
    class FM(ast.NodeTransformer):
        def visit_If(self,node):
            if ast.unparse(node.test)=="name.startswith('DBG_input')":counts['DBG_branch']+=1;return None
            return self.generic_visit(node)
        def visit_Assign(self,node):
            if ast.unparse(node)=="definition, dbg, expected = (read(f['definition']), read(f['DBG_definition']), read(f['expected']))":
                counts['DBG_read']+=1;return ast.parse("definition, expected = read(f['definition']), read(f['expected'])").body[0]
            if ast.unparse(node)=="dbg = read(f['DBG_definition'])":counts['DBG_read']+=1;return None
            return self.generic_visit(node)
        def visit_For(self,node):
            if ast.unparse(node.iter)=="('FM', 'DBG')":node.iter=ast.parse("('FM',)",mode='eval').body;counts['stability']+=1
            elif ast.unparse(node.iter)=="[('financial_modeling', 'FM'), ('debugging', 'DBG')]":
                node.iter=ast.parse("[('financial_modeling', 'FM')]",mode='eval').body;counts['mode']+=1
            return self.generic_visit(node)
        def visit_Tuple(self,node):
            text=ast.unparse(node)
            if text=="('FM_input2', 'DBG_input2')":counts['previous']+=1;return ast.parse("('FM_input2',)",mode='eval').body
            if text=="('FM_input1', 'DBG_input1')":counts['initial']+=1;return ast.parse("('FM_input1',)",mode='eval').body
            return self.generic_visit(node)
        def visit_Call(self,node):
            node=self.generic_visit(node)
            if isinstance(node.func,ast.Name) and node.func.id=='verify_input_caches':
                counts['cache']+=1;node.keywords.append(ast.keyword(arg='definition',value=ast.Name('definition',ast.Load())))
            return node
        def visit_Constant(self,node):
            if type(node.value)is int and node.value==8:node.value=5;counts['calls']+=1
            elif node.value=='Equity-income FM/DBG engineering':node.value='Financial cohort FM engineering';counts['title']+=1
            elif node.value=='Cleanup does not cover eight actual owned IDs':node.value='Cleanup does not cover five actual owned IDs'
            return node
    for node in ast.parse(ANCESTOR.read_bytes()).body:
        if isinstance(node,ast.FunctionDef) and node.name in ('execute_prepared','validate_completed','_stage_source'):
            if node.name!='_stage_source':node.name='_'+node.name+'_FM'
            nodes.append(FM().visit(node))
    wanted={'stability':1,'mode':2,'DBG_branch':2,'DBG_read':2,'cache':2,'calls':3,'previous':1,'initial':1,'title':1}
    require(counts==wanted and len(nodes)==3,'The exact five-stage removal seams changed: '+str(counts))
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),str(ANCESTOR),'exec'),_N)
    return counts


ADAPTATION_COUNTS=_adapt_workflow()
_N.update(recipes=recipes,validate_prepared=validate_prepared,verify_definitions=verify_definitions,verify_input_caches=verify_input_caches)


def execute_prepared(output):
    _activate();return _N['_execute_prepared_FM'](output)


def validate_completed(value):
    _activate();return _N['_validate_completed_FM'](value)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-manifest',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--prepared',type=Path);p.add_argument('--run',action='store_true');args=p.parse_args(argv)
    if args.prepared:
        require(args.source_manifest is None and args.output is None,'Use the exact existing preparation')
        result=execute_prepared(args.prepared) if args.run else validate_prepared(args.prepared)
    else:
        require(not args.run and args.source_manifest is not None and args.output is not None,'Prepare and review before a separate actual run')
        result=prepare(args.source_manifest,args.output)
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
