"""Two unchanged local proofs: exact product-set winner and excluded runner."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
import gc
from pathlib import Path
from types import FunctionType

from ..linear_capital_ringfenced_group import composition as ancestor
from . import contract as c, stream_composition

ANCESTOR_SHA='ca00c7b1918510ee5533a5b05f4c4da86e111888687e3185dc5644be9ea8dbd2'
KIND='cold_composed_two_ringfenced_capital_best_runner_certificate'
LOCAL_GEOMETRY=ancestor.LOCAL_GEOMETRY


def _namespace():
    c.require(c.reference(ancestor.__file__)['sha256']==ANCESTOR_SHA,'The original complete proof ancestor changed')
    ns=dict(vars(ancestor));ns['c']=c
    for name in ('_integer','_report','_hydrate'):
        f=getattr(ancestor,name);clone=FunctionType(f.__code__,ns,name,f.__defaults__,f.__closure__);clone.__kwdefaults__=f.__kwdefaults__;ns[name]=clone
    tree=ast.parse(Path(ancestor.__file__).read_bytes());counts={}
    for name in ('compose_values_a','compose_values_b'):
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name);changed=0
        class Pair(ast.NodeTransformer):
            def visit_Constant(self,n):
                nonlocal changed
                if type(n.value) is int and n.value==4:changed+=1;n.value=2
                return n
        node=Pair().visit(node);counts[name]=changed;module=ast.Module(body=[node],type_ignores=[]);ast.fix_missing_locations(module)
        exec(compile(module,str(ancestor.__file__),'exec'),ns)
    c.require(counts=={'compose_values_a':1,'compose_values_b':3},'Unknown frozen product-set arithmetic dimensions')
    return ns


_N=_namespace();compose_values_a=_N['compose_values_a'];compose_values_b=_N['compose_values_b']
_providers=ancestor._providers


def _compose(frozen,pair_id):
    # This is an actual parser replay over all ten donors, not a JSON pass flag.
    preflight=stream_composition.preflight_all(frozen['_reference'])
    contexts=c.pair_contexts(frozen['contexts'],pair_id)
    reference_provider,source_provider=_providers();locals_=[]
    for context in contexts:
        print('Cold validating '+context['profile_id']+' complete reference/source',flush=True)
        locals_.append(_N['_hydrate'](context,reference_provider,source_provider));gc.collect()
    A,B=compose_values_a(locals_),compose_values_b(locals_)
    c.require(A==B,'Independent group sums and exact runner swap disagree')
    contract=frozen['contracts'][pair_id];mandates=c.read(contract)['mandates']
    evidence=[{k:r[k] for k in ('id','profile_id','reference','source_manifest','workbook','specification','model_A','model_B',
        'best_solver_receipt','excluded_runner_solver_receipt','best_solver_validation','runner_solver_validation',
        'whole_financial_validation','gap_pence','geometry')} for r in locals_]
    return {'kind':KIND,'version':1,'pair_id':pair_id,'contract':contract,'composition':A,'local_whole_evidence':evidence,
        'donors':[{'id':r['id'],'display_name':m['display_name'],'prefix':m['sheet_prefix'],'workbook':r['workbook'],
            'source_manifest':r['source_manifest'],'reference':r['reference']} for r,m in zip(locals_,mandates,strict=True)],
        'geometry_before_global_header_and_reports':{k:sum(r['geometry'][k] for r in locals_) for k in LOCAL_GEOMETRY},
        'FM_mask_projection_including_two_completion_gates':3044376,
        'all_ten_pure_preflight':preflight,'proof':{
            'feasible_set':'Cartesian product of two unchanged local feasible sets',
            'bound_and_attainment':'Each local objective is bounded by its certified W; both local winners attain sum(W).',
            'unique_best':'Any changed mandate loses its strictly positive certified local gap.',
            'exact_runner':'Every changed complete tuple loses at least min(gaps); one full local runner attains it.',
            'runner_ties':'Keep all minimum-gap mandate IDs; canonical witness uses the first declared one.',
            'all_possible_global_runner_vectors_enumerated':False},
        'mathematical_composition_certified':True,'cold_local_reference_count':2,'cold_original_source_count':2,
        'independent_group_arithmetic_implementations':2,'original_local_proof_searches_reused':4,
        'new_financial_universe_forwards':0,'new_solver_calls':0,'LO_calls':0,'model_calls':0,'workbooks_written':0,
        'new_group_source_admitted':False,'source_classification_pending':True,'qualified':False,
        'normal_task_quality_passed':False,'difficulty_qualified':False,'local_quality_or_development_inherited':False,
        'coupled_720_project_MIP_claimed':False,'local_reference_recipe':reference_provider.recipes(),
        'local_source_recipe':source_provider.recipes(),'recipe':c.recipes()}


def build_certificate(prospective,output,*,pair_id='R2-01'):
    frozen=c.validate_prospective(prospective);frozen={**frozen,'_reference':prospective if isinstance(prospective,dict) else c.reference(prospective)}
    output=Path(output).absolute()
    c.require(output==output.resolve() and output.is_relative_to(c.ROOT/'outputs') and not output.exists(),'Use a fresh complete pair certificate output')
    value=_compose(frozen,pair_id)
    output.mkdir(parents=True)
    return c.write(output/'certificate.json',{**value,'prospective':frozen['_reference'],'created_at':datetime.now(timezone.utc).isoformat()})


def validate_certificate(record):
    retained=c.read(record)
    c.require(retained['kind']==KIND and retained['version']==1,'Use a genuine complete two-context certificate')
    frozen=c.validate_prospective(retained['prospective']);frozen={**frozen,'_reference':retained['prospective']}
    expected=_compose(frozen,retained['pair_id'])
    c.require({k:v for k,v in retained.items() if k not in ('prospective','created_at')}==expected,
        'Whole local evidence, parser replay or product-set proof changed')
    return retained
