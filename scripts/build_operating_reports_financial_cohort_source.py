#!/usr/bin/env python3
"""Cold cohort source3; replay stored independent evidence without forwards."""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
from datetime import datetime,timedelta
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import FunctionType,SimpleNamespace
from xml.etree import ElementTree as X
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.workbook.operating_reports_financial_cohort_v1 import schema,raw,excel

KIND='prepared_operating_reports_financial_cohort_cold_source_v1'
SOURCE_KIND='independently_checked_operating_reports_financial_cohort_source_v1'
PROFILE=ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'
SCAFFOLD=ROOT/'scripts/build_waterfall_portfolios_source.py'
SCAFFOLD_SHA='09223a654ce5231d83d15b292f299d6ffab9f0b0e1151dbe24eba9af187cc69e'
AUDITOR=ROOT/'scripts/build_operating_reports_200_source.py'
AUDITOR_SHA='1e8319d0ba6975348b4c188e92a04d2eb2d730c21e9022a1accd885b05406ef1'
BUSINESS=ROOT/'src/sheets_factory/workbook/operating_reports_200/audit.py'
BUSINESS_SHA='0cd0924a5b9fbe48edfcc6f751941df7b510425fba27330e7d15d23479dbb805'
PRODUCER_PINS={'schema.py':'cf5732f4e2a8a17ec3d9e339791c3f372ed04a22665815951c79f6a31ed53be4',
    'raw.py':'0b6e96062fd2b9b4a07ac9fecf9edf15d360306ca28ad92b7791c0e06665b87c',
    'oracles.py':'92c8032c551427899ae5414c4d7ab4535beda5cf2d5c9540d76989a92e29e951',
    'excel.py':'dd9efa7800934ecc394cb6811b07d35a90159e9c996332e3823e563c3f556a63'}


def _load(path,sha,name):
    if hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('A complete frozen source helper changed: '+path.name)
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


_scaffold=_load(SCAFFOLD,SCAFFOLD_SHA,'_cohort_frozen_source_scaffold')
_auditor=_load(AUDITOR,AUDITOR_SHA,'_cohort_frozen_full_source_auditor')


def _lifecycle():
    tree=ast.parse(SCAFFOLD.read_bytes());function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='_load_ancestor')
    changes={'waterfall_source.':'financial_cohort_source.','_waterfall_resource_support':'_financial_cohort_resource_support',
        'Waterfall stored-ledger cold-start source':'Financial cohort stored-evidence cold source',
        'full_independent_waterfall_native_cache_audit':'full_independent_financial_cohort_native_cache_audit'};counts=[]
    class Labels(ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value)is str and node.value in changes:counts.append(node.value);node.value=changes[node.value]
            return node
    function=Labels().visit(function)
    if sorted(counts)!=sorted(changes):raise ValueError('Only the exact source lifecycle display labels may change')
    namespace={**vars(_scaffold),'__file__':__file__,'KIND':KIND,'SOURCE_KIND':SOURCE_KIND}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),str(SCAFFOLD),'exec'),namespace)
    return namespace['_load_ancestor']()


_N=_lifecycle()
for _name in ('require','reference','checked','read','write','typed','runtime','clear_all_formula_caches',
    'compare_typed','owned_absence','validate_call','stage','_book','formula_signature'):
    globals()[_name]=_N[_name]
_audit_namespace={**vars(_auditor),'schema':schema,'_ns':_N}
for _name in ('target','provided_facts','source_definition','_formula_cache_count','audit_workbook'):
    _value=getattr(_auditor,_name)
    _cloned=FunctionType(_value.__code__,_audit_namespace,_name,_value.__defaults__,_value.__closure__)
    _cloned.__kwdefaults__=deepcopy(_value.__kwdefaults__);_audit_namespace[_name]=_cloned;globals()[_name]=_cloned
if hashlib.sha256(BUSINESS.read_bytes()).hexdigest()!=BUSINESS_SHA:raise ValueError('The complete original business-comparison kernel changed')
_business={'__file__':str(BUSINESS),'__name__':'_private_cohort_full_business_compare','s':schema}
_tree=ast.parse(BUSINESS.read_bytes());_imports=[n for n in _tree.body if isinstance(n,ast.ImportFrom) and n.level==1 and n.module is None]
require(len(_imports)==1 and [(v.name,v.asname) for v in _imports[0].names]==[('schema','s')],'The exact comparison schema import changed')
_tree.body.remove(_imports[0]);exec(compile(ast.fix_missing_locations(_tree),str(BUSINESS),'exec'),_business)
compare_stored=_business['compare']


def _ref(value):return deepcopy(value) if isinstance(value,dict) else reference(value)


def _check_refs(value):
    if type(value)is dict:
        if set(value)=={'path','sha256','bytes'}:checked(value)
        else:
            for child in value.values():_check_refs(child)
    elif type(value)is list:
        for child in value:_check_refs(child)


def recipes():
    for name,sha in PRODUCER_PINS.items():require(reference(Path(schema.__file__).with_name(name))['sha256']==sha,'The final cohort producer or renderer changed')
    require(reference(SCAFFOLD)['sha256']==SCAFFOLD_SHA and reference(AUDITOR)['sha256']==AUDITOR_SHA
        and reference(BUSINESS)['sha256']==BUSINESS_SHA,'The complete source3 helper closure changed')
    # The original waterfall recipe function enumerates the common engine,
    # observer, formula and dashboard dependencies; its domain refs stay provenance.
    inherited=_scaffold.recipes()
    return {**inherited,**excel.recipes(),**{str(p.resolve()):reference(p) for p in (Path(__file__),SCAFFOLD,AUDITOR,BUSINESS)}}


def _forward(row,implementation,case_id,inventory,specification):
    value=read(row);_check_refs(value)
    require(value['kind']=='complete_once_operating_reports_financial_cohort_forward' and value['version']==1
        and type(value['version'])is int and type(value['financial_forward_calls'])is int and type(value['outer_retries'])is int
        and value['implementation']==implementation and value['case_id']==case_id
        and value['raw_inventory']==inventory and value['specification']==specification
        and value['recipe']==schema.recipes() and value['financial_forward_calls']==1
        and value['outer_retries']==0 and value['qualified'] is False
        and type(value['elapsed_seconds'])in (int,float) and 0<=value['elapsed_seconds']<float('inf'),
        'A complete once-only original independent financial forward is required')
    started=read(value['started'])
    require(started['kind']=='once_operating_reports_financial_cohort_forward_started' and started['version']==1
        and type(started['version'])is int and type(started['financial_forward_limit'])is int and type(started['outer_retries'])is int
        and started['implementation']==implementation and started['case_id']==case_id
        and started['raw_inventory']==inventory and started['specification']==specification
        and started['recipe']==value['recipe'] and started['financial_forward_limit']==1 and started['outer_retries']==0,
        'The prior financial-forward reservation differs from the completed evidence')
    date=datetime.fromisoformat(started['started_at'].replace('Z','+00:00'))
    require(date.tzinfo is not None and date.utcoffset()==timedelta(0),'The forward reservation needs its actual UTC start time')
    return value,read(value['result'])


def _stored(f):
    inventory=f['raw_inventory'];all_raw=raw.validate_all(inventory);case=schema.candidate(f['case_id'])
    public=all_raw['specifications'][case['candidate_id']]
    records=all_raw['inventory']['cases'];original=next(row['specification'] for row in records if row['candidate_id']==case['candidate_id'])
    require(f['specification']==original,'Bind the original frozen raw, not a renderer copy')
    evidence=f['financial_evidence'];envelope=read(evidence['comparison']);_check_refs(envelope)
    require(envelope['kind']=='stored_operating_reports_financial_cohort_AB_comparison' and envelope['version']==1
        and envelope['case_id']==case['candidate_id'] and envelope['raw_inventory']==inventory
        and envelope['specification']==original and envelope['A']==evidence['forward_A'] and envelope['B']==evidence['forward_B']
        and envelope['new_financial_forwards']==0,'Use the exact stored comparison and two completed forwards')
    a,left=_forward(envelope['A'],'A',case['candidate_id'],inventory,original)
    b,right=_forward(envelope['B'],'B',case['candidate_id'],inventory,original)
    require(a['started']!=b['started'] and a['result']!=b['result'],'The two independent implementations need distinct original attempts and result artifacts')
    comparison=compare_stored(public,left,right)
    require(comparison==envelope['comparison'] and comparison['passed'] is True and not comparison['differences'],
        'All stored exact maps, primary values, CAGR bounds and reconciliations must pass the original comparison')
    return public,left,right,comparison


def _crosscheck_prepared(f):
    public,left,right,comparison=_stored(f);bindings=read(f['bindings']);declared=dict(schema.points(public))
    require(set(bindings['financial'])==set(declared),'The entire independent financial union must be bound')
    expected={}
    for key,row in bindings['financial'].items():
        point=row['sheet']+'!'+row['cell'];require(point not in expected and row['role']==('given_NA' if declared[key]=='text' else 'report'),
            'Financial positions must be unique and every NA must remain a given literal')
        expected[point]=target(right['typed_2dp_values'][key])
    return expected,{'kind':'complete_stored_independent_financial_cohort_source_projection','version':1,
        'case_id':f['case_id'],'raw_inventory':f['raw_inventory'],'financial_evidence':f['financial_evidence'],
        'complete_comparison':comparison,'all_financial_fields':len(expected),'new_financial_forwards':0,'qualified':False}


def _snapshot(path):
    ns='{'+_N['NS']+'}';result={};formulas=cache=0
    with ZipFile(path) as archive:
        book=X.fromstring(archive.read('xl/workbook.xml'));rels=X.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        targets={row.attrib['Id']:row.attrib['Target'].lstrip('/') for row in rels}
        sheets=book.find(ns+'sheets');names=[]
        for sheet in sheets:
            name=sheet.attrib['name'];names.append(name);part=targets[sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
            if not part.startswith('xl/'):part='xl/'+part
            for cell in X.fromstring(archive.read(part)).iter(ns+'c'):
                f=cell.find(ns+'f');v=cell.find(ns+'v');text=cell.find(ns+'is')
                if f is not None:
                    # Openpyxl emits empty v placeholders. They contain no
                    # answers; the separate cold-clear stage removes every node.
                    formulas+=1;cache+=int(v is not None and v.text is not None or text is not None)
                result[name,cell.attrib['r']]=(cell.attrib.get('t'),f.text if f is not None else None,
                    v.text if v is not None else None,X.tostring(text) if text is not None else None,cell.attrib.get('s'))
    return result,names,formulas,cache


def fm_census(public,candidate,bindings):
    require(bindings['specification_sha256']==schema.canonical_sha256(public),'The physical bindings belong to another raw')
    kinds=dict(schema.points(public));rows=bindings['financial'];require(set(rows)==set(kinds),'Incomplete full financial bindings')
    points={(row['sheet'],row['cell']) for row in rows.values()};require(len(points)==len(rows),'Duplicate financial report position')
    plans=read(candidate['view_plans']);require(plans['kind']==excel.PLAN_KIND and plans['version']==1
        and plans['specification_sha256']==schema.canonical_sha256(public) and plans['mode_order']==['financial_modeling']
        and plans['actual_D_unknown'] is True and plans['native_calls']==0
        and plans['FM_mask']==excel.forecast_keys(public),'The complete FM-only forecast plan changed')
    source,names,n,cache=_snapshot(checked(candidate['source']));fm,fm_names,fm_n,fm_cache=_snapshot(checked(candidate['views']['financial_modeling']['input']))
    require(cache==fm_cache==0 and names==fm_names,'Source and FM view must retain all sheets without populated formula caches')
    context={(row['sheet'],row['cell']) for row in bindings['provided_context'].values()}
    populated={point for point,item in source.items() if any(value is not None for value in item[1:4])}
    require(not points&context and points|context==populated,'Every populated policy, label, fact and report position must be bound')
    mask={(rows[key]['sheet'],rows[key]['cell']) for key in plans['FM_mask']}
    require(set(fm)==set(source) and {point for point in source if source[point]!=fm[point]}==mask,
        'The FM view changed cells outside the complete predeclared mask')
    require(all(fm[point][1:4]==(None,None,None) for point in mask),'Every forecast helper and report must be physically blank in FM')
    require(n==sum(kind!='text' for kind in kinds.values()) and fm_n==n-len(mask),'All source and remaining FM formulas must be retained')
    for key,kind in kinds.items():
        item=source[rows[key]['sheet'],rows[key]['cell']]
        require(rows[key]['role']==('given_NA' if kind=='text' else 'report')
            and (item[0]=='inlineStr' and item[3]is not None if kind=='text' else item[1]is not None),
            'NA fields must be nonempty literals and all applicable reports must be formulas')
    for fact in bindings['provided_facts'].values():
        item=source[fact['sheet'],fact['cell']]
        require(item[1]is None and (item[2]is not None or item[3]is not None),'Provided raw facts cannot be blank or calculated')
        if not fact['value'].startswith('n/a'):require(item[2]is not None and Fraction(item[2])==Fraction(fact['value']),'A supplied decimal fact changed')
    return {'kind':'complete_FM_only_financial_cohort_physical_census','version':1,'passed':True,
        'report_positions':len(rows),'source_formulas':n,'FM_mask':len(mask),'sheets':len(names),'nonempty':len(populated),
        'provided_fact_fields':len(bindings['provided_facts']),'formula_caches':cache,'native_calls':0,'actual_D_unknown':True}


def _renderer(public,candidate,bindings):
    _check_refs(candidate)
    require(candidate['kind']==excel.KIND and candidate['version']==1 and candidate['candidate_id']==schema.candidate(public['seed'])['candidate_id']
        and read(candidate['specification'])==public and candidate['specification_sha256']==schema.canonical_sha256(public)
        and candidate['recipe']==excel.recipes() and set(candidate['views'])=={'financial_modeling'}
        and candidate['source_caches_seeded'] is candidate['old_C00_failure_or_qualification_inherited'] is candidate['qualified'] is False
        and candidate['financial_forwards']==candidate['actual_LO_calls']==candidate['model_calls']==0,
        'Require this complete unverified cohort FM renderer, with no inherited qualification')
    require(checked(candidate['views']['financial_modeling']['instruction']).read_text()==excel.BRIEF,'Preserve the exact original403-byte public brief')
    rules=excel.rules(public)
    for key,rule in rules.items():
        rule['report_binding']=bindings['financial'][key]
        rule['provided_binding']=bindings['provided_facts'][rule['entity']+'/forecast_sales/'+rule['period']]
    proof=read(candidate['rendering_proof'])
    require(proof['kind']=='exact_finite_decimal_matching_growth_rendering' and proof['version']==2
        and proof['specification_sha256']==schema.canonical_sha256(public) and proof['rules']==rules
        and proof['matching_growth_fields']==len(rules) and proof['public_policy_and_facts_changed'] is False
        and proof['financial_intermediate_rounding'] is proof['hidden_epsilon'] is False and proof['native_calculations']==0,
        'The complete exact finite-input growth rendering proof changed')
    census=fm_census(public,candidate,bindings)
    require((census['report_positions'],census['source_formulas'],census['FM_mask'],census['sheets'],census['nonempty'],census['provided_fact_fields'],len(rules))
        ==(93510,88676,62322,211,148176,11200,1600)
        and (candidate['independent_business_field_count'],candidate['formula_count'],candidate['forecast_mask_count'],candidate['sheet_count'],candidate['matching_growth_formulas'])
        ==(93510,88676,62322,211,1600),'Retain the full fixed200 production source and FM geometry')
    return census


def _metadata_prepared(output):
    value=read(Path(output)/'preparation.json');require(value['kind']==KIND and value['version']==1,'Use the genuine cohort source preparation')
    return value


def prepare(candidate_ref,output,*,raw_inventory,case_id,forward_A,forward_B,comparison,profile=PROFILE):
    output=Path(output).absolute();require(output==output.resolve() and not output.exists(),'Use a fresh separate source directory')
    output.mkdir(parents=True);audit=_N['AuditStore'](output/'prepare_audit',{'id':output.name+'-prepare','name':'Financial cohort source preparation; stored outputs,0 forwards','status':'running','qualified':False,'target_count':0})
    server=_N['DashboardServer'](audit.snapshot,audit.events,host='127.0.0.1',port=0);failure=None
    try:
        url=server.start();write(output/'prepare_started.json',{'at':_N['now'](),'dashboard_url':url,'pid':_N['os'].getpid(),'native_LO_calls':0})
        print(json.dumps({'dashboard_url':url,'phase':'source_prepare','pid':_N['os'].getpid()}),flush=True)
        with stage(audit,'stored_full_independent_and_raw_cold_validation'):
            all_raw=raw.validate_all(_ref(raw_inventory));entry=schema.candidate(case_id)
            original=next(row['specification'] for row in all_raw['inventory']['cases'] if row['candidate_id']==entry['candidate_id'])
            public=all_raw['specifications'][entry['candidate_id']];require(public['dimension_mode']=='production','Actual source admission requires all200 entities')
            candidate=read(candidate_ref);bindings=read(candidate['bindings'])
            f={'raw_inventory':_ref(raw_inventory),'case_id':entry['candidate_id'],'specification':original,'bindings':candidate['bindings'],
                'financial_evidence':{'forward_A':_ref(forward_A),'forward_B':_ref(forward_B),'comparison':_ref(comparison)}}
            expected,projected=_crosscheck_prepared(f);census=_renderer(public,candidate,bindings)
            definition=source_definition(checked(candidate['source']),bindings,public)
            require(len(expected)==93510 and len(definition['formulas'])==88676 and len(definition['provided_financial_inputs'])==11200,'The complete source-definition scope changed')
        with stage(audit,'cold_start_all_formula_caches'):
            r,p=runtime(profile);cold=output/'cold_start.xlsx';clear=clear_all_formula_caches(checked(candidate['source']),cold)
            require(clear['all_formula_caches_cleared']==88676 and _formula_cache_count(cold)==0,'Clear every derived formula cache before the first native calculation')
            cold_audit=audit_workbook(cold,definition,expected,empty_caches=True);require(cold_audit['passed'],'Complete cold source audit failed')
            refs={key:write(output/(name+'.json'),value) for key,name,value in (
                ('definition','definition.private',definition),('expected','expected.private',expected),
                ('independent_comparison','stored_AB_projection',projected),('cold_start_audit','cold_start_audit',cold_audit),('pure_emission_census','pure_FM_census',census))}
            return write(output/'preparation.json',{'kind':KIND,'version':1,'candidate_manifest':_ref(candidate_ref),**f,
                'specification_sha256':schema.canonical_sha256(public),'cold_start':reference(cold),**refs,'cache_clearance':clear,
                'runtime_profile':r,'runtime_profile_value':p,'recipe':recipes(),'stage_order':list(_N['STAGES']),
                'required_actual_LO_calls':3,'cold_start_is_unseeded':True,'actual_LO_calls':0,'new_financial_forwards':0,'model_calls':0,'qualified':False})
    except BaseException as error:
        failure={'type':type(error).__name__,'message':str(error)};write(output/'preparation_failure.json',failure);raise
    finally:
        audit.update_run(status='failed' if failure else 'passed',producer_active=False);audit.export();server.stop();audit.db.close()


def validate_prepared(output):
    f=_metadata_prepared(output)
    require(f['recipe']==recipes() and f['stage_order']==list(_N['STAGES']) and f['required_actual_LO_calls']==3
        and f['cold_start_is_unseeded'] is True and f['new_financial_forwards']==f['actual_LO_calls']==f['model_calls']==0
        and f['qualified'] is False,'Exact source3 recipe, stages and stored-evidence policy required')
    _check_refs(f);require(runtime(checked(f['runtime_profile']))==(f['runtime_profile'],f['runtime_profile_value']),'The pinned actual resource contract changed')
    expected,comparison=_crosscheck_prepared(f)
    require(expected==read(f['expected']) and comparison==read(f['independent_comparison']),'The full stored independent projection changed')
    public=schema.validate_spec(read(f['specification']));candidate=read(f['candidate_manifest']);bindings=read(f['bindings'])
    require(candidate['bindings']==f['bindings'] and read(candidate['specification'])==public,'Renderer and original raw binding changed')
    census=_renderer(public,candidate,bindings);definition=source_definition(checked(candidate['source']),bindings,public)
    require(census==read(f['pure_emission_census']) and definition==read(f['definition']),'The whole physical source, labels, facts or formulas changed')
    cold=audit_workbook(checked(f['cold_start']),definition,expected,empty_caches=True)
    require(cold['passed'] and cold==read(f['cold_start_audit']) and f['cache_clearance']['source']==candidate['source']
        and f['cache_clearance']['output']==f['cold_start'] and f['cache_clearance']['all_formula_caches_cleared']==88676
        and _formula_cache_count(f['cold_start']['path'])==0 and f['specification_sha256']==schema.canonical_sha256(public),
        'Original unseeded source clearance or complete independent audit changed')
    return f


_N.update(KIND=KIND,SOURCE_KIND=SOURCE_KIND,recipes=recipes,source_definition=source_definition,audit_workbook=audit_workbook,
    validate_prepared=validate_prepared,_metadata_prepared=_metadata_prepared,_crosscheck_prepared=_crosscheck_prepared,
    spec=SimpleNamespace(validate=schema.validate_spec,canonical_sha256=schema.canonical_sha256))
_N['_formula_cache_count']=_formula_cache_count
execute_prepared=_N['execute_prepared']


def validate_source(value):
    terminal=_N['validate_source'](value)
    require(terminal['memoized_independent_ledgers'] is True and terminal['new_financial_forwards']==0,'A source cannot rerun or replace original independent forwards')
    return terminal


validate_completed=validate_source


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('candidate','output','raw-inventory','forward-A','forward-B','comparison','prepared','manifest'):parser.add_argument('--'+name,type=Path)
    parser.add_argument('--case-id');parser.add_argument('--profile',type=Path,default=PROFILE);parser.add_argument('--run',action='store_true');args=parser.parse_args(argv)
    if args.manifest:
        require(not any((args.candidate,args.output,args.prepared,args.run)),'Validate one retained source manifest')
        result=validate_source(args.manifest)
    elif args.prepared:
        require(not any((args.candidate,args.output,args.raw_inventory,args.forward_A,args.forward_B,args.comparison,args.case_id)),'Use the unchanged frozen source preparation')
        result=execute_prepared(args.prepared) if args.run else validate_prepared(args.prepared)
    else:
        require(all((args.candidate,args.output,args.raw_inventory,args.forward_A,args.forward_B,args.comparison,args.case_id)),'Supply candidate,all-nine raw inventory,both once-forward receipts,full comparison and fresh output')
        result=prepare(args.candidate,args.output,raw_inventory=args.raw_inventory,case_id=args.case_id,forward_A=args.forward_A,forward_B=args.forward_B,comparison=args.comparison,profile=args.profile)
        if args.run:result=execute_prepared(args.output)
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
