#!/usr/bin/env python3
"""Prepare or execute one cold, three-call operating-report source sequence."""
from __future__ import annotations
import ast
from decimal import Decimal
import hashlib
from pathlib import Path
import shutil
import sys
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import openpyxl
from sheets_factory.workbook.operating_metrics_regime import spec,oracle_a,oracle_b,excel,audit as business_audit

UPSTREAM=ROOT/'scripts/build_equity_income_group_source.py'
UPSTREAM_SHA='1b6e3374a98e39a5708543af4e796026262d9d782a461d6ec29ad10d11ac3690'
KIND='prepared_operating_metrics_regime_cold_start_source'
SOURCE_KIND='independently_checked_operating_metrics_regime_source'


def _lifecycle_namespace():
    raw=UPSTREAM.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=UPSTREAM_SHA:raise ValueError('Frozen source3 lifecycle changed')
    tree=ast.parse(raw);counts={'import':0,'validate':0,'title':0,'events':0}
    class BindDomain(ast.NodeTransformer):
        def visit_ImportFrom(self,node):
            if node.module=='sheets_factory.workbook.equity_income_group':
                counts['import']+=1;node.module='sheets_factory.workbook.operating_metrics_regime'
                node.names=[ast.alias(name='spec'),ast.alias(name='oracle_a',asname='decimal_oracle'),ast.alias(name='oracle_b',asname='fraction_oracle'),ast.alias(name='excel')]
            return node
        def visit_Attribute(self,node):
            if isinstance(node.value,ast.Name) and node.value.id=='spec' and node.attr=='validate':node.attr='validate_spec';counts['validate']+=1
            return self.generic_visit(node)
        def visit_Constant(self,node):
            if node.value=='Equity-income cold-start source':node.value='Operating-metrics cold-start source';counts['title']+=1
            elif node.value in ('equity_source.stage_started','equity_source.stage_terminal'):node.value=node.value.replace('equity_source.','operating_metrics_source.');counts['events']+=1
            return node
    tree=BindDomain().visit(tree)
    if counts!={'import':1,'validate':3,'title':1,'events':2}:raise ValueError('The bounded source3 adaptation changed: '+str(counts))
    namespace={'__name__':'_isolated_operating_metrics_source3','__file__':__file__}
    exec(compile(ast.fix_missing_locations(tree),__file__,'exec'),namespace)
    namespace.update(KIND=KIND,SOURCE_KIND=SOURCE_KIND,__doc__=__doc__)
    return namespace


_ns=_lifecycle_namespace()
require,reference,checked,read,write,typed=(_ns[n] for n in ('require','reference','checked','read','write','typed'))
PROFILE=_ns['PROFILE'];STAGES=_ns['STAGES'];runtime=_ns['runtime']
_base_recipes=_ns['recipes']


def recipes():
    require(reference(UPSTREAM)['sha256']==UPSTREAM_SHA,'Frozen source3 lifecycle changed')
    return {**_base_recipes(),str(UPSTREAM):reference(UPSTREAM),str(Path(business_audit.__file__).resolve()):reference(business_audit.__file__)}


def _target(value):
    if value['type']=='string':return {'type':'text','value':value['value']}
    if value['type']=='boolean':return value
    n=Decimal(value['value']);return {'type':'number','value':'0' if not n else format(n.normalize(),'f')}


def crosscheck(public,bindings):
    a,b=oracle_a.solve(public),oracle_b.solve(public);comparison=business_audit.compare_results(public,a,b)
    require(comparison['passed'],'Complete independent A/B business values disagree')
    rows=bindings['bindings'];keys=[r['key'] for r in rows];points=[r['sheet']+'!'+r['cell'] for r in rows]
    require(len(keys)==len(set(keys))==len(set(points))==2052 and set(keys)==business_audit.expected_keys(public),'All 2052 independent typed fields must have unique physical bindings')
    expected={}
    for row,point in zip(rows,points,strict=True):
        require(row['key']=='/'.join((row['entity'],row['period'],row['metric'])) and row['expected_typed']==b['display_values'][row['key']],'Business binding or prepared expectation changed')
        expected[point]=_target(b['display_values'][row['key']])
    return expected,{'kind':'complete_independent_operating_metrics_business_comparison','version':1,'passed':True,
        'complete_AB_financial_fields':2052,'complete_typed_bindings':2052,'independent_exact_values_agree':True,
        'rounding':'two decimal places for all financial numerics; no intermediate financial rounding',
        'shared_financial_implementation':False,'qualified':False}


def source_definition(path,bindings,public):
    book=openpyxl.load_workbook(path,data_only=False);formulas={};literals={}
    try:
        require(book.calculation.iterate is not True,'This source has no circular calculations')
        require([book['Read Me'].cell(i+2,2).value for i in range(len(spec.PUBLIC_POLICY))]==list(spec.PUBLIC_POLICY.values()),'Public business policies changed')
        for sheet in book:
            for cell in sheet._cells.values():
                point=sheet.title+'!'+cell.coordinate
                if cell.data_type=='f':formulas[point]=cell.value
                elif cell.value is not None:literals[point]=typed(cell.value)
        scope={r['sheet']+'!'+r['cell'] for r in bindings['bindings']}
        require(len(scope)==2052 and len(formulas)==1967 and set(formulas)<=scope and all(len(f)<=8192 for f in formulas.values()),'Complete bounded financial formula scope changed')
        raw_facts=[]
        for entity in public['entities']:
            for field in ('id','name','layout','money_unit','sales_basis','direct_cost_percent','annual_interest_percent','tax_percent','cash','investment','debt','capital','retained_earnings'):
                raw_facts.append((field,entity['opening'][field] if field in entity['opening'] else entity[field]))
        raw_facts.extend((field,public['distribution'][field]) for field in ('profit_percent','cagr_percent','q4_yoy_percent'))
        for entity in public['entities']:
            for i in range(12):
                raw_facts.append(('actual_revenue',entity['actual_revenue'][i]) if i<4 else ('forecast_sales_assumptions',entity['forecast_sales_assumptions'][i-4]))
                raw_facts.extend((field,entity[field][i]) for field in ('quarterly_fixed_opex','associate_results'))
        require([(f['field'],f['provided_value']) for f in bindings['provided_facts']]==raw_facts,'Every original public fact must be bound exactly once in its declared order')
        provided={}
        for fact in bindings['provided_facts']:
            point=fact['sheet']+'!'+fact['cell'];wanted=_target(fact['expected_literal'])
            if wanted['type']=='number':require(Decimal(wanted['value'])==Decimal(fact['provided_value']),'A raw numerical assumption was rescaled or changed')
            require(point not in provided and literals.get(point)==wanted,'Provided business fact differs from its original specification')
            provided[point]=wanted
        return {'sheetnames':book.sheetnames,'formulas':formulas,'literals':literals,'provided_financial_inputs':provided,
            'non_circular':True,'financial_scope':sorted(scope),'specification_sha256':spec.canonical_sha256(public)}
    finally:book.close()


def _formula_cache_count(path):
    count=0
    with ZipFile(path) as archive:
        for name in archive.namelist():
            if name.startswith('xl/worksheets/sheet') and name.endswith('.xml'):
                count+=sum(c.find('{*}f') is not None and c.find('{*}v') is not None for c in ET.fromstring(archive.read(name)).findall('{*}sheetData/{*}row/{*}c'))
    return count


def audit_workbook(path,definition,expected,*,empty_caches=False):
    f=openpyxl.load_workbook(path,data_only=False);v=openpyxl.load_workbook(path,data_only=True)
    mismatches=[];errors=[];observed={};formulas={}
    try:
        require(f.sheetnames==v.sheetnames==definition['sheetnames'] and f.calculation.iterate is not True,'Worksheet order or non-circular calculation policy changed')
        for sheet in f:
            for cell in sheet._cells.values():
                if cell.data_type=='f':formulas[sheet.title+'!'+cell.coordinate]=cell.value
        require(set(formulas)==set(definition['formulas']) and all(_ns['formula_signature'](text)==_ns['formula_signature'](definition['formulas'][p]) for p,text in formulas.items()),'Complete financial formula definitions changed')
        for sheet in v:
            for cell in sheet._cells.values():
                point=sheet.title+'!'+cell.coordinate
                if cell.data_type=='e':errors.append({'point':point,'error':cell.value})
                if cell.value is not None:observed[point]=typed(cell.value,financial=point in expected)
        for point,wanted in expected.items():
            target={'type':'empty','value':''} if empty_caches and point in formulas else wanted
            actual=observed.get(point,{'type':'empty','value':''})
            if actual!=target:mismatches.append({'point':point,'expected':target,'actual':actual})
        for point,wanted in definition['literals'].items():
            if observed.get(point)!=wanted:mismatches.append({'point':point,'claim':'Provided input, policy or label changed'})
        require(set(observed)==set(definition['literals']) | (set() if empty_caches else set(expected)),'Unexpected missing or extra populated cells')
        if empty_caches:require(_formula_cache_count(path)==0,'Every formula cache must be absent before the first actual call')
        return {'kind':'full_independent_operating_metrics_native_cache_audit','passed':not mismatches and not errors,
            'workbook':reference(path),'all_financial_fields_checked':len(expected),'all_derived_values_checked':len(expected),
            'physical_formulas_checked':len(formulas),'protected_public_literals_checked':len(definition['literals']),
            'provided_financial_input_fields_checked':len(definition['provided_financial_inputs']),
            'mismatches':mismatches,'native_errors':errors,'all_formula_caches_empty':empty_caches,
            'normalization':'all financial numerics half-up2dp; supplied construction literals exact; booleans distinct','qualified':False}
    finally:f.close();v.close()


def prepare(candidate_manifest,output,*,profile=PROFILE):
    output=Path(output).absolute();require(output==output.resolve() and not output.exists(),'Use a fresh source directory')
    m=read(candidate_manifest)
    require(m['kind']=='prepared_unverified_operating_metrics_regime_pair' and m['version']==1 and m['actual_LO_calls']==m['model_calls']==m['optimizer_calls']==0 and m['qualified'] is False and m['official_workbook_seed_used'] is False,'Use the unverified synthetic operating-metrics family only')
    require(m['recipe_sha256']=={str(Path(x.__file__).resolve()):reference(x.__file__)['sha256'] for x in (spec,oracle_a,oracle_b,business_audit)} and m['emitter']==reference(excel.__file__),'Frozen independent mathematics/emitter changed')
    for key in ('specification','goal','cold_source_input','cold_source_cache_clearance','bindings','independent_expected','independent_crosscheck'):checked(m[key])
    for view in m['views'].values():
        for r in view.values():checked(r)
    public=spec.validate_spec(read(m['specification']));bindings=read(m['bindings']);expected,comparison=crosscheck(public,bindings)
    require(expected=={p:_target(v) for p,v in read(m['independent_expected']).items()},'Complete independently prepared targets changed')
    definition=source_definition(checked(m['goal']),bindings,public);r,p=runtime(profile)
    clearance=read(m['cold_source_cache_clearance'])
    require(clearance['input']==m['goal'] and clearance['output']==m['cold_source_input'] and clearance['all_formula_caches_removed'] is True and clearance['formula_count']==1967 and clearance['actual_LO_calls']==0 and clearance['native_validation_claimed'] is False,'Require the declared unseeded first source input')
    output.mkdir(parents=True);cold=output/'cold_start.xlsx';shutil.copyfile(checked(m['cold_source_input']),cold)
    cold_audit=audit_workbook(cold,definition,expected,empty_caches=True);require(cold_audit['passed'],'Cold source formula/literal/cache preservation failed')
    refs={'definition':write(output/'definition.private.json',definition),'expected':write(output/'expected.private.json',expected),
        'independent_comparison':write(output/'independent_AB_comparison.json',comparison),'cold_start_audit':write(output/'cold_start_audit.json',cold_audit)}
    clear={'source':m['goal'],'output':reference(cold),'candidate_cold_source_input':m['cold_source_input'],'all_formula_caches_cleared':1967,'oracle_seeded_cache_is_not_native_evidence':True}
    return write(output/'preparation.json',{'kind':KIND,'version':1,'candidate_manifest':reference(candidate_manifest['path'] if isinstance(candidate_manifest,dict) else candidate_manifest),
        'specification':m['specification'],'bindings':m['bindings'],'specification_sha256':spec.canonical_sha256(public),'cold_start':reference(cold),
        **refs,'cache_clearance':clear,'runtime_profile':r,'runtime_profile_value':p,'recipe':recipes(),'stage_order':list(STAGES),
        'required_actual_LO_calls':3,'cold_start_is_unseeded':True,'actual_LO_calls':0,'model_calls':0,'qualified':False})


def validate_prepared(output):
    f=read(Path(output)/'preparation.json')
    require(f['kind']==KIND and f['version']==1 and f['recipe']==recipes() and f['stage_order']==list(STAGES) and f['required_actual_LO_calls']==3 and f['cold_start_is_unseeded'] is True,'Prepared family/recipe/stages changed')
    for key in ('candidate_manifest','specification','bindings','cold_start','definition','expected','independent_comparison','cold_start_audit','runtime_profile'):checked(f[key])
    require(runtime(checked(f['runtime_profile']))==(f['runtime_profile'],f['runtime_profile_value']),'Runtime profile changed')
    cold=audit_workbook(checked(f['cold_start']),read(f['definition']),read(f['expected']),empty_caches=True)
    c=f['cache_clearance'];declared=read(f['candidate_manifest'])
    require(cold['passed'] and cold==read(f['cold_start_audit']) and c['output']==f['cold_start'] and c['all_formula_caches_cleared']==1967 and c['candidate_cold_source_input']==declared['cold_source_input'] and (f['cold_start']['sha256'],f['cold_start']['bytes'])==(declared['cold_source_input']['sha256'],declared['cold_source_input']['bytes']),'First actual input must remain the exact all-cache-cleared declared source')
    return f


_ns.update(recipes=recipes,crosscheck=crosscheck,source_definition=source_definition,audit_workbook=audit_workbook,prepare=prepare,validate_prepared=validate_prepared)
execute_prepared=_ns['execute_prepared'];validate_source=_ns['validate_source'];validate_completed=validate_source
compare_typed=_ns['compare_typed'];main=_ns['main']

if __name__=='__main__':raise SystemExit(main())
