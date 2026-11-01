#!/usr/bin/env python3
"""Reuse one pinned pure export; retain every genuine cold and source3 gate."""
from __future__ import annotations

import argparse
import ast
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
UPSTREAM=ROOT/'scripts/run_ringfenced_pair_session_revision2.py'
UPSTREAM_SHA='2e47ce7e09b6565d5ee0388efbde31ff98618c0d92c213930cfea457b939a6eb'
FROZEN=ROOT/'scripts/run_ringfenced_pair_session.py'
FROZEN_SHA='c600139d90e4d23edcc665de847be2c713d3d342abf104f267aa314b1d0b9f14'
KIND='prepared_two_ringfenced_pair_source_same_process_session_revision3'
TERMINAL_KIND='completed_two_ringfenced_pair_source_same_process_session_revision3'
FAILED=ROOT/'outputs/research/ringfenced_pair_R2_01_same_process_source_revision2_20261101T021000Z_same_process_genuine_prepare_audit/failure.json'
FAILED_SHA='52c8fc291e073b5687e1bbd4ab6356466462f4877c843c0c2a5bb955472bdc4c'
for path,digest in ((UPSTREAM,UPSTREAM_SHA),(FROZEN,FROZEN_SHA)):
    if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('A frozen complete pair session changed')
_P={'__file__':str(UPSTREAM),'__name__':'_private_ringfenced_pair_complete_session_revision3'}
exec(compile(UPSTREAM.read_bytes(),str(UPSTREAM),'exec'),_P)
_N=_P['_N'];c=_P['c'];stream=_N['stream'];_REUSE=ContextVar('root_pinned_complete_pair_export',default=None)
_N.update(KIND=KIND,TERMINAL_KIND=TERMINAL_KIND)


def _general_zero(styles):
    """Resolve the actual existing format; never rewrite a style or workbook."""
    xfs=styles.find('{*}cellXfs');c.require(xfs is not None and len(xfs)>0,'Style0 must exist')
    value=xfs[0].get('numFmtId','0')
    c.require(value.isdigit(),'A valid numeric format identity is required')
    formats=styles.find('{*}numFmts')
    matches=[] if formats is None else [r for r in formats if r.get('numFmtId')==value]
    if value=='0':return not matches
    return len(matches)==1 and matches[0].get('formatCode')=='General'


def _report_namespace(module):
    old=module._N;ns=dict(old);ns['_general_zero']=_general_zero
    tree=ast.parse(Path(module.ancestor.__file__).read_bytes())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='append_report');changed=0
    class General(ast.NodeTransformer):
        def visit_Compare(self,n):
            nonlocal changed
            if ast.unparse(n)=="zero.get('numFmtId', '0') == '0'":
                changed+=1;return ast.parse('_general_zero(styles)',mode='eval').body
            return self.generic_visit(n)
    node=General().visit(node);c.require(changed==1,'Unknown frozen General-format guard sites')
    tree=ast.Module(body=[node],type_ignores=[]);ast.fix_missing_locations(tree)
    exec(compile(tree,str(module.ancestor.__file__),'exec'),ns)
    return SimpleNamespace(**{**vars(module),'append_report':ns['append_report']})


_old_source=_P['_source']
def _source(admission,pilot):
    ns=_old_source(admission,pilot);old=ns['recipes']
    ns['stream_composition']=SimpleNamespace(**{**vars(stream),'syntax':stream._N['syntax']})
    ns['group_report']=_report_namespace(ns['group_report'])
    ns['recipes']=lambda:{**old(),str(UPSTREAM):c.reference(UPSTREAM),str(FROZEN):c.reference(FROZEN),
        str(Path(__file__).resolve()):c.reference(__file__)}
    return ns


def _checked_inputs(certificate,certificate_sha,composition,composition_sha):
    refs=[]
    for value,digest in ((certificate,certificate_sha),(composition,composition_sha)):
        ref=value if isinstance(value,dict) else c.reference(value)
        c.require(type(digest)is str and len(digest)==64 and ref['sha256']==digest,
            'Supply the separate Root pin for each original complete pure artifact')
        c.checked(ref);refs.append(ref)
    cert_ref,local_ref=refs;cert,local=c.read(cert_ref),c.read(local_ref)
    c.require(c.reference(FAILED)['sha256']==FAILED_SHA and c.read(FAILED)==
        {'type':'ValueError','message':'Report style0 must retain General, including Boolean results'},
        'Preserve the original naturally completed zero-native metadata failure')
    summary=c.read(FAILED.parent/'summary.json')['run']
    c.require(summary['status']=='failed' and summary['producer_active'] is False
        and summary['model_calls']==summary['solver_calls']==0
        and not (Path(local_ref['path']).parent/'source/started.json').exists(),
        'A previous actual source attempt cannot become a pure-export reuse')
    c.require(cert['pair_id']=='R2-01' and cert['cold_local_reference_count']==cert['cold_original_source_count']==2
        and local['ancestry']=={'composition_certificate':cert_ref,'native_source_or_quality_inherited':False}
        and local['kind']=='uncalculated_ringfenced_group_stream_composition' and local['version']==1
        and local['mode']=='goal' and local['prototype_toy_only'] is False and local['sheet_count']==740
        and local['geometry']=={'formulas':2494656,'nonempty':3547132,'targets':3044376}
        and local['exact_expected_census']=={'sheets':740,'formulas':2494656,'nonempty':3547132}
        and local['geometry_limits']==stream.LIMITS and local['coordinates_relocated'] is False
        and local['all_derived_formula_caches_cleared'] is local['retained_given_literals_NA_booleans_unchanged'] is True
        and local['new_group_source_admitted'] is local['financial_quality_or_difficulty_inherited'] is False
        and local['LO_model_solver_Harbor_calls']==local['new_financial_forwards']==0,
        'Only the original complete uncalculated R2-01 pure emission may be reused')
    c.checked(local['output'])
    return {'certificate':cert_ref,'composition':local_ref,'original_workbook':local['output'],
        'failed_attempt':c.reference(FAILED),'failed_summary':c.reference(FAILED.parent/'summary.json')}


def _reuse_composition(donors,output,*,mode,target_count,expected_census,ancestry):
    refs=_REUSE.get();c.require(refs is not None,'Original pure-export pins must precede any reuse')
    old_cert=c.read(refs['certificate']);local=c.read(refs['composition']);fresh_ref=ancestry['composition_certificate'];fresh=c.read(fresh_ref)
    stable=lambda value:{k:v for k,v in value.items() if k not in ('created_at','prospective')}
    c.require(stable(old_cert)==stable(fresh) and old_cert['prospective']==fresh['prospective']
        and old_cert['pair_id']==fresh['pair_id']=='R2-01'
        and fresh['donors']==donors and [(r['id'],r['workbook']) for r in local['donors']]==
            [(r['id'],r['workbook']) for r in donors]
        and mode=='goal' and target_count==local['geometry']['targets']
        and expected_census==local['exact_expected_census']
        and ancestry=={'composition_certificate':fresh_ref,'native_source_or_quality_inherited':False},
        'The fresh genuine whole proof, fixed pool, pair, order or complete pure census changed')
    c.checked(refs['original_workbook']);c.checked(refs['certificate']);c.checked(refs['composition'])
    # This is a NEW explicit provenance envelope over unchanged original bytes.
    # The unchanged complete cold auditor must still examine every cell.
    return {**deepcopy(local),'ancestry':deepcopy(ancestry),'pure_emission_reuse':deepcopy(refs),
        'full_fresh_cold_audit_still_required':True,'old_source_pass_inherited':False}


def _adapt_prepare():
    tree=ast.parse(FROZEN.read_bytes());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='prepare');count=0
    class Reuse(ast.NodeTransformer):
        def visit_Call(self,n):
            nonlocal count
            n=self.generic_visit(n)
            if ast.unparse(n.func)=='stream._compose':n.func=ast.Name('_reuse_composition',ast.Load());count+=1
            return n
    node=Reuse().visit(node);c.require(count==1,'Unknown frozen pure-composition call sites')
    tree=ast.Module(body=[node],type_ignores=[]);ast.fix_missing_locations(tree)
    _N['_reuse_composition']=_reuse_composition;exec(compile(tree,str(FROZEN),'exec'),_N)
    return _N['prepare']


_P['_original_prepare']=_adapt_prepare();_N['_source']=_source
_legacy_prepare=_P['prepare']
def prepare(prospective,output,*,pair_id='R2-01',parse_cache,expected_cache_sha256,
            prior_certificate,expected_prior_certificate_sha256,prior_composition,expected_prior_composition_sha256):
    c.require(pair_id=='R2-01','Only the fixed first pair has an authorized retained pure export')
    refs=_checked_inputs(prior_certificate,expected_prior_certificate_sha256,prior_composition,expected_prior_composition_sha256)
    token=_REUSE.set(refs)
    try:
        admission=_legacy_prepare(prospective,output,pair_id=pair_id,parse_cache=parse_cache,
            expected_cache_sha256=expected_cache_sha256)
        data=_N['_LIVE'][admission]
        receipt=c.write(Path(output)/'revision3_pure_export_reuse.json',{'kind':'whole_pair_pinned_pure_export_reuse_revision3',
            'version':3,'original':refs,'implementation':c.reference(__file__),'upstream':c.reference(UPSTREAM),
            'frozen_session':c.reference(FROZEN),'old_metadata_failure_not_a_source_pass':True,
            'fresh_genuine_local_reference_validations':2,'fresh_genuine_original_source_validations':2,
            'full_cold_formula_literal_value_audit_preserved':True,'new_financial_forwards':0,'native_calls':0,'qualified':False})
        data['artifacts'].bind([receipt,refs],expand=False);admission.guard();return admission
    finally:_REUSE.reset(token)


_N['prepare']=prepare
execute_prepared=_N['execute_prepared'];validate_completed=_N['validate_completed']


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('prospective','output','parse-cache','prior-certificate','prior-composition'):p.add_argument('--'+name,type=Path,required=True)
    for name in ('expected-cache-sha256','expected-prior-certificate-sha256','expected-prior-composition-sha256'):p.add_argument('--'+name,required=True)
    p.add_argument('--pair',default='R2-01');p.add_argument('--run',action='store_true');a=p.parse_args(argv)
    admission=prepare(a.prospective,a.output,pair_id=a.pair,parse_cache=a.parse_cache,expected_cache_sha256=a.expected_cache_sha256,
        prior_certificate=a.prior_certificate,expected_prior_certificate_sha256=a.expected_prior_certificate_sha256,
        prior_composition=a.prior_composition,expected_prior_composition_sha256=a.expected_prior_composition_sha256)
    result=execute_prepared(admission) if a.run else {'native_calls':0,'preparation':c.reference(a.output/'source/preparation.json')}
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
