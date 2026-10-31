#!/usr/bin/env python3
"""Eight actual task-view/control calls after genuine operating-report source3."""
from __future__ import annotations
import ast
from copy import deepcopy
import hashlib
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
UPSTREAM=ROOT/'scripts/validate_equity_income_group_tasks.py'
UPSTREAM_SHA='bcc07848ed5b868c9cb943e3058aa10980b9399d4d53a8d17220d60748a85f0c'
SOURCE_SHA='cf1f977b76f8b76bc224f7160287eda091a1c1a21c97797aa8cbe904796ac249'
KIND='prepared_operating_metrics_regime_task_engineering'
TERMINAL_KIND='complete_operating_metrics_regime_task_engineering'
PRIOR_FAILED_SOURCE=ROOT/'outputs/research/operating_metrics_regime_source3_prepared_20261031T200046Z/source_manifest.json'
PRIOR_FAILED_SOURCE_SHA='531233705a5d4123aba41cf2f2f2be3f8730ac147953b7b18c3bb18ae3ee56c4'


def _source_facade(native):
    """Expose frozen sequence helpers without changing the source module globals."""
    return SimpleNamespace(**{**native._ns,**vars(native)})


def _namespace():
    raw=UPSTREAM.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=UPSTREAM_SHA:raise ValueError('Frozen task8 lifecycle changed')
    tree=ast.parse(raw);counts={'source_path':0,'source_sha':0,'loader_name':0,'facade':0,'kind':0,'terminal':0,'title':0,'cache_calls':0}
    class Domain(ast.NodeTransformer):
        def visit_Constant(self,node):
            table={'scripts/build_equity_income_group_source.py':('scripts/build_operating_metrics_regime_source.py','source_path'),
                '1b6e3374a98e39a5708543af4e796026262d9d782a461d6ec29ad10d11ac3690':(SOURCE_SHA,'source_sha'),
                '_equity_income_source_for_tasks':('_operating_metrics_source_for_tasks','loader_name'),
                'prepared_equity_income_group_task_engineering':(KIND,'kind'),
                'complete_equity_income_group_task_engineering':(TERMINAL_KIND,'terminal'),
                'Equity-income FM/DBG engineering':('Operating-metrics FM/DBG engineering','title')}
            if type(node.value) is str and node.value in table:
                node.value,key=table[node.value];counts[key]+=1
            return node
        def visit_Expr(self,node):
            node=self.generic_visit(node)
            if ast.unparse(node)=='_spec.loader.exec_module(source)':
                counts['facade']+=1
                return [node,*ast.parse('source=_new_source_facade(source)').body]
            return node
        def visit_Call(self,node):
            node=self.generic_visit(node)
            if isinstance(node.func,ast.Name) and node.func.id=='verify_input_caches':
                node.keywords.append(ast.keyword(arg='definition',value=ast.Name(id='definition',ctx=ast.Load())));counts['cache_calls']+=1
            return node
    tree=Domain().visit(tree)
    if counts!={'source_path':1,'source_sha':1,'loader_name':1,'facade':1,'kind':1,'terminal':1,'title':1,'cache_calls':4}:
        raise ValueError('Bounded task8 domain adaptation changed: '+str(counts))
    namespace={'__name__':'_isolated_operating_metrics_task8','__file__':__file__,'_new_source_facade':_source_facade}
    exec(compile(ast.fix_missing_locations(tree),__file__,'exec'),namespace)
    namespace['__doc__']=__doc__
    return namespace


_ns=_namespace();source=_ns['source'];STAGES=_ns['STAGES']
reference,checked,read,write,require=(_ns[n] for n in ('reference','checked','read','write','require'))
transform=_ns['transform'];snapshot=_ns['snapshot'];compare_complete=_ns['compare_complete']
_base_recipes=_ns['recipes'];_base_validate_prepared=_ns['validate_prepared']


def recipes():
    require(reference(UPSTREAM)['sha256']==UPSTREAM_SHA,'Frozen task8 lifecycle changed')
    return {**_base_recipes(),str(UPSTREAM):reference(UPSTREAM)}


def prior_source_failure(public_sha):
    require(reference(PRIOR_FAILED_SOURCE)['sha256']==PRIOR_FAILED_SOURCE_SHA,'Original failed source attempt changed')
    failed=read(PRIOR_FAILED_SOURCE)
    require(failed['kind']=='independently_checked_operating_metrics_regime_source' and failed['passed'] is False
        and failed['specification_sha256']==public_sha and failed['actual_LO_calls_completed']==1
        and failed['model_calls']==failed['solver_calls']==failed['Harbor_calls']==0,'Retain the original unscored source type failure')
    cleanup=read(failed['records']['failure_cleanup'])
    require(cleanup['all_owned_containers_absent'] and cleanup['daemon_reachable'],'Original failed source owned cleanup is unknown')
    return {'source_manifest':reference(PRIOR_FAILED_SOURCE),'failure_audit':failed['records']['source1_audit'],
        'owned_cleanup':failed['records']['failure_cleanup'],'model_score_inferred':False}


def verify_definitions(path,definition,*,blank=False):
    book=source._book(path)
    try:
        require(book.sheetnames==definition['sheetnames'] and book.calculation.iterate is not True,'Task sheets or non-circular policy changed')
        mask=set(definition['FM_mask_points'])
        wanted={p:f for p,f in definition['formulas'].items() if not blank or p not in mask}
        formulas={s.title+'!'+c.coordinate:c.value for s in book for c in s._cells.values() if c.data_type=='f'}
        require(set(formulas)==set(wanted) and all(source.formula_signature(formulas[p])==source.formula_signature(wanted[p]) for p in wanted),'Complete construction formula definitions changed')
        literals={s.title+'!'+c.coordinate:source.typed(c.value) for s in book for c in s._cells.values() if c.value is not None and c.data_type!='f'}
        require(literals==definition['literals'],'Given task facts, public labels or historical NA values changed')
    finally:book.close()


def verify_input_caches(path,expected,*,blank,definition):
    observed=snapshot(path,expected)['values'];mask=set(definition['FM_mask_points'])
    require(not any(v['type']=='error' for v in observed.values()),'Native task input has an error value')
    for point,target in expected.items():
        if blank and point in mask:require(point not in observed,'A forecast FM target was not blank')
        elif blank:require(observed.get(point)==target,'An unmasked historical financial value changed')
        else:require(observed.get(point,{}).get('type')==target['type'],'A DBG financial input cache changed its declared value type')


def prepare(source_manifest,output):
    output=Path(output).absolute();require(output==output.resolve() and not output.exists(),'Use a fresh task-engineering directory')
    actual=source.validate_source(source_manifest)
    require(actual['kind']=='independently_checked_operating_metrics_regime_source' and actual['version']==1 and actual['passed'] is True,'Use the new family genuine source3 cold proof')
    sf=source.validate_prepared(checked(actual['preparation']).parent)
    candidate=read(sf['candidate_manifest']);bindings=read(sf['bindings']);original=read(sf['definition']);expected=read(sf['expected'])
    require(actual['source']==actual['actual_calls'][-1]['output'] and len(expected)==2052,'Use the complete genuine source3 physical goal')
    mask=[p['sheet']+'!'+p['cell'] for p in bindings['FM_mask_points']]
    roots=bindings['DBG_root_edits']
    require(len(mask)==len(set(mask))==1368 and set(mask)<=set(original['formulas']) and len(roots)==4
        and {r['mechanism'] for r in roots}=={'associate_sign','growth_ratio_without_minus_one','money_unit','wrong_comparison_quarter'},'Retain the full forecast mask and four declared fault families')
    for row in roots:
        point=row['sheet']+'!'+row['cell']
        require(point in mask and source.formula_signature(original['formulas'][point])==source.formula_signature(row['before']),'Fault root differs from its genuine source definition')
    root=next(r for r in roots if r['key']=='ALDER/2026Q1/net_income')
    require(expected[root['sheet']+'!'+root['cell']]=={'type':'number','value':'27.75'},'The chosen missed root must be a genuinely nonzero propagated amount')
    lineage=prior_source_failure(actual['specification_sha256'])
    definition=deepcopy(original);definition['FM_mask_points']=sorted(mask)
    output.mkdir(parents=True);planned=output/'planned';planned.mkdir();goal=actual['source'];root_point=(root['sheet'],root['cell'])
    correct=definition['formulas'][root['sheet']+'!'+root['cell']]
    require('Read Me!A1' not in expected,'The extra-change control must be outside the financial D scope')
    cases={'FM_input':{tuple(p.rsplit('!',1)):('blank',None) for p in mask},
        'DBG_input':{(r['sheet'],r['cell']):('formula',r['after']) for r in roots},
        'equivalent':{root_point:('formula','=0+('+correct.lstrip('=')+')')},
        'FM_missed_root':{root_point:('blank',None)},'DBG_missed_root':{root_point:('formula',root['after'])},
        'extra_change':{('Read Me','A1'):('text',definition['literals']['Read Me!A1']['value']+' [control]')}}
    plans={};edits={};clearances={}
    for name,changes in cases.items():
        intermediate=planned/(name+'.edited.xlsx');edits[name]=transform(checked(goal),intermediate,changes)
        final=planned/(name+'.xlsx');clearances[name]=source.clear_all_formula_caches(intermediate,final);plans[name]=reference(final)
    instructions={}
    for mode in ('financial_modeling','debugging'):
        r=candidate['views'][mode]['instruction'];target=planned/(mode+'_instruction.md')
        source.shutil.copyfile(checked(r),target);instructions[mode]=reference(target)
    dbg=deepcopy(definition)
    for r in roots:dbg['formulas'][r['sheet']+'!'+r['cell']]=r['after']
    verify_definitions(checked(plans['FM_input']),definition,blank=True);verify_definitions(checked(plans['DBG_input']),dbg)
    return write(output/'preparation.json',{'kind':KIND,'version':1,'source_manifest':reference(source_manifest['path'] if isinstance(source_manifest,dict) else source_manifest),
        'genuine_goal':goal,'source_preparation':actual['preparation'],'candidate_preparation':sf['candidate_manifest'],
        'source_definition':sf['definition'],'definition':write(output/'definition.private.json',definition),
        'expected':sf['expected'],'bindings':sf['bindings'],'DBG_definition':write(output/'DBG_definition.private.json',dbg),
        'planned_inputs':plans,'instruction_bytes':instructions,'exact_edits':edits,'all_formula_cache_clearances':clearances,
        'stage_order':list(STAGES),'mode_order':['financial_modeling','debugging'],'required_actual_LO_calls':8,
        'all_modes_and_controls_frozen_before_first_actual_call':True,'reuse_genuine_source3_goal_and_two_stabilities':True,
        'independent_business_field_count':2052,'financial_target_count':1368,'DBG_formula_root_count':4,
        'complete_D_counts_pending_actual_input_calculation':True,'retained_prior_failed_source':lineage,
        'runtime_profile':sf['runtime_profile'],'runtime_profile_value':sf['runtime_profile_value'],'recipe':recipes(),
        'actual_LO_calls':0,'model_calls':0,'qualified':False,'normal_all12_QA_passed':False})


def validate_prepared(output):
    f=read(Path(output)/'preparation.json')
    require(f['kind']==KIND and f['version']==1 and f['recipe']==recipes() and f['stage_order']==list(STAGES)
        and f['required_actual_LO_calls']==8 and f['all_modes_and_controls_frozen_before_first_actual_call'] is True,'Prepared family/recipe/order changed')
    for key in ('source_manifest','genuine_goal','source_preparation','candidate_preparation','source_definition','definition','expected','bindings','DBG_definition','runtime_profile'):checked(f[key])
    for refs in (f['planned_inputs'],f['instruction_bytes'],f['retained_prior_failed_source']):
        for r in refs.values():
            if isinstance(r,dict):checked(r)
    actual,sf,candidate=read(f['source_manifest']),read(f['source_preparation']),read(f['candidate_preparation'])
    require(actual['kind']=='independently_checked_operating_metrics_regime_source' and actual['source']==f['genuine_goal'] and actual['preparation']==f['source_preparation']
        and sf['candidate_manifest']==f['candidate_preparation'] and sf['definition']==f['source_definition'] and sf['bindings']==f['bindings'] and sf['expected']==f['expected']
        and sf['runtime_profile']==f['runtime_profile'] and sf['runtime_profile_value']==f['runtime_profile_value'],'Source/goal/complete field originals differ')
    definition=read(f['definition']);original=read(f['source_definition']);mask=definition.pop('FM_mask_points')
    bindings=read(f['bindings'])
    require(definition==original and mask==sorted(r['sheet']+'!'+r['cell'] for r in bindings['FM_mask_points'])
        and len(mask)==f['financial_target_count']==1368 and len(read(f['expected']))==f['independent_business_field_count']==2052 and f['DBG_formula_root_count']==4,'Full business or forecast mask scope changed')
    require(f['retained_prior_failed_source']==prior_source_failure(actual['specification_sha256']),'Original failed source history changed')
    for mode,r in f['instruction_bytes'].items():
        original=candidate['views'][mode]['instruction'];require(r['sha256']==original['sha256'] and r['bytes']==original['bytes'],'Original short business instruction changed')
    return f


_ns.update(recipes=recipes,verify_definitions=verify_definitions,verify_input_caches=verify_input_caches,prepare=prepare,validate_prepared=validate_prepared)
execute_prepared=_ns['execute_prepared'];validate_completed=_ns['validate_completed'];main=_ns['main']

if __name__=='__main__':raise SystemExit(main())
