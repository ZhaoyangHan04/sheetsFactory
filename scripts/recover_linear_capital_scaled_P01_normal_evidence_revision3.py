#!/usr/bin/env python3
"""Verify bound audited-summary transport in a private fixed-P01 reporter."""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
import mmap
from pathlib import Path
from types import FunctionType, SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
FROZEN=ROOT/'scripts/recover_linear_capital_scaled_P01_normal_evidence_revision2.py'
FROZEN_SHA='bb443d195b576b249ffcfe71eb49c3631db1334dfb5988333af89743c5e5b295'
REPORTER=ROOT/'src/sheets_factory/reporting.py'
REPORTER_SHA='ac347bb3b5ad637267effa3b81cba79f272c53a4d258c1ad314ab930510d606f'
PRODUCER=ROOT/'src/sheets_factory/checkers/reference_evidence.py'
PRODUCER_SHA='520e7b3cec6e69f7798cf906e78480e8a919b658e94e3ac9a3f0272045ee599e'
ADDITIONAL_LINEAGE={
    'approved_revision3':{'path':str(ROOT/'outputs/research/P01_normal_recovery_audited_summary_revision3_proposal_20261101T003914Z/prospective.json'),
        'sha256':'53607f8e1711b7f3e9b001f58a3ccb772ab2b81465ac8b88ece5148808bf4caf','bytes':4052},
    'retained_v2_failure':{'path':str(ROOT/'outputs/research/P01_normal_append_only_recovery_revision2_20261101T002955Z/prepared/failure.json'),
        'sha256':'df29449ad91a646adfee610592b0ce80b82abce311a2523b5f02297307e02dcd','bytes':249335},
    'retained_v2_prospective':{'path':str(ROOT/'outputs/research/P01_normal_append_only_recovery_revision2_20261101T002955Z/prepared/prospective.json'),
        'sha256':'751466d28f123a0bef8adf3761931a9d9bf3b1862cc1e24bd3cd8fce7420e96a','bytes':23815},
    'audited_summary_readonly_cause':{'path':str(ROOT/'outputs/research/P01_reference_review_audited_summary_readonly_20261101T003542Z/receipt.json'),
        'sha256':'aff8bbd3edd4bf13fe8c33722beb59764e668e79fb7ec71d7857fb4844357309','bytes':5658},
}


def inherited_ast():
    if hashlib.sha256(FROZEN.read_bytes()).hexdigest()!=FROZEN_SHA:
        raise ValueError('The complete frozen empty-WAL recovery revision changed')
    counts={}
    def mark(key):counts[key]=counts.get(key,0)+1
    class Identity(ast.NodeTransformer):
        def visit_Constant(self,node):
            changes={'prepared_fixed_P01_normal_append_only_evidence_recovery_revision2':'prepared_fixed_P01_normal_append_only_evidence_recovery_revision3',
                'fixed_P01_normal_append_only_evidence_recovery_certificate_revision2':'fixed_P01_normal_append_only_evidence_recovery_certificate_revision3'}
            if type(node.value)is str and node.value in changes:
                old=node.value;node.value=changes[old];mark(old)
            return node
        def visit_Assign(self,node):
            if ast.unparse(node)=='value.value = 2':node.value=ast.Constant(3);mark('prepared_certificate_version')
            elif ast.unparse(node)=='node.comparators[0] = ast.Constant(2)':node.value=ast.parse('ast.Constant(3)').body[0].value;mark('validator_version')
            return self.generic_visit(node)
    tree=Identity().visit(ast.parse(FROZEN.read_bytes()))
    if len(counts)!=4 or any(value!=1 for value in counts.values()):
        raise ValueError('Only the exact revision3 identity seams may change: '+str(counts))
    return ast.fix_missing_locations(tree)


_V2={'__file__':__file__,'__name__':'_isolated_fixed_P01_recovery_revision3'}
exec(compile(inherited_ast(),str(FROZEN),'exec'),_V2)
_N=_V2['_N'];require,reference=_N['require'],_N['reference']
for _path,_sha in ((REPORTER,REPORTER_SHA),(PRODUCER,PRODUCER_SHA)):
    require(reference(_path)['sha256']==_sha,'The frozen reporter or audited-summary producer changed')
from sheets_factory.checkers.reference_evidence import _bytes, _compact

_V2['LINEAGE'].update(deepcopy(ADDITIONAL_LINEAGE))
_V2['LINEAGE'].update(frozen_revision2=reference(FROZEN),frozen_reporter=reference(REPORTER),frozen_summary_producer=reference(PRODUCER))
_first_review=_N['_review'];_first_recover=_N['_recover']
_real_reporting=_N['reporting']


def reporter_ast():
    require(reference(REPORTER)['sha256']==REPORTER_SHA,'The original reporter changed')
    tree=ast.parse(REPORTER.read_bytes())
    function=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='_reference_review')
    wanted=ast.dump(ast.parse("private.get('reference_review_context') == context").body[0].value,include_attributes=False)
    count=[]
    class ContextTransport(ast.NodeTransformer):
        def visit_Compare(self,node):
            if ast.dump(node,include_attributes=False)==wanted:
                count.append('bound_audited_summary')
                return ast.copy_location(ast.parse('_bound_audited_context(evidence, private, context)').body[0].value,node)
            return self.generic_visit(node)
    function=ContextTransport().visit(function)
    require(count==['bound_audited_summary'],'The exact full-versus-summary reporter comparison changed')
    return ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[]))


def _bound_audited_context(evidence,private,context,access):
    # No writer or financial calculation is invoked. Both functions are the
    # exact pure producer functions that created the original transport.
    access.checked(reference(PRODUCER),'frozen_audited_summary_producer')
    require(reference(PRODUCER)['sha256']==PRODUCER_SHA,'The frozen evidence compaction policy changed')
    transport=evidence.get('private_evidence',{})
    require(transport.get('summary_version')==1 and transport.get('summary_is_not_a_quality_verdict') is True
        and transport.get('private_summary')==private,'The bound private summary transport differs from its actual payload')
    canonical=_bytes(context);canonical_sha=hashlib.sha256(canonical).hexdigest()
    inventory=transport.get('field_inventory',{}).get('reference_review_context')
    require(inventory=={'type':'dict','count':len(context),'sha256':canonical_sha},
        'The complete current reference context differs from the bound field inventory')
    require(private.get('reference_review_context')==_compact(context,'/reference_review_context'),
        'The actual private context is not the exact frozen producer projection')
    full=transport.get('full_artifact',{})
    require(set(full)=={'path','sha256','bytes','complete','encoding'} and full['complete'] is True
        and full['encoding']=='UTF-8 JSON','A complete original private artifact is required')
    record={key:full[key] for key in ('path','sha256','bytes')}
    path=access.checked(record,'complete_original_private_evidence_artifact')
    marker=b'"reference_review_context": '
    with path.open('rb') as handle,mmap.mmap(handle.fileno(),0,access=mmap.ACCESS_READ) as mapped:
        index=mapped.find(marker)
        require(index>=0 and mapped.find(marker,index+len(marker))==-1,
            'The complete artifact requires a unique original reference-context fragment')
        start=index+len(marker)
        require(mapped[start:start+len(canonical)]==canonical
            and mapped[start+len(canonical):start+len(canonical)+1] in (b',',b'}'),
            'The complete private artifact lacks the exact canonical current context')
    access.checked(record,'unchanged_complete_private_evidence_after_read')
    checks=getattr(access,'audited_summary_checks',[])
    checks.append({'task_id':context['binding']['task_id'],'full_artifact':record,'canonical_context_sha256':canonical_sha,
        'field_inventory_checked':True,'unique_complete_context_fragment_checked':True,'exact_frozen_compaction_checked':True,
        'producer':reference(PRODUCER),'new_financial_calculations':0})
    access.audited_summary_checks=checks
    return True


def _review(task,config,access):
    proxy=SimpleNamespace(**vars(_real_reporting))
    proxy._bound_audited_context=lambda evidence,private,context:_bound_audited_context(evidence,private,context,access)
    namespace=dict(vars(proxy))
    exec(compile(reporter_ast(),str(REPORTER),'exec'),namespace)
    proxy._reference_review=namespace['_reference_review']
    # The frozen v1 body makes a second private function namespace to record
    # reads. It carries this closure and changes no reporter module attribute.
    globals_for_call={**_N,'reporting':proxy}
    return FunctionType(_first_review.__code__,globals_for_call,_first_review.__name__)(task,config,access)


def _recover(frozen,access):
    result=_first_recover(frozen,access)
    checks=getattr(access,'audited_summary_checks',[])
    require(len(checks)==2 and {row['task_id'] for row in checks}==set(_N['TASKS']),
        'Both fixed original tasks need complete audited-summary transport verification')
    result['audited_summary_transport_checks']=deepcopy(checks)
    result['original_reporter_module_globals_changed']=False
    return result


_N.update(_review=_review,_recover=_recover)
for _name,_value in _N.items():
    if not _name.startswith('__'):globals().setdefault(_name,_value)

if __name__=='__main__':raise SystemExit(main())
