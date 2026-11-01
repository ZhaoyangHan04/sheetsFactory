#!/usr/bin/env python3
"""Prepare or execute current FM cohort normal quality without prior scores."""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import mmap
import os
from pathlib import Path
import sys
import threading
import time
from types import FunctionType
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.pipelines import operating_reports_financial_cohort_quality as pipeline
from sheets_factory.task_adapters import operating_reports_financial_cohort_quality as nodes
from sheets_factory import reporting
from sheets_factory.checkers import reference_evidence
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease

KIND='prepared_operating_reports_financial_cohort_normal_quality'
DEFAULT_CONFIG=ROOT/'config/pipelines/operating_reports_financial_cohort_quality_v1.yaml'
UPSTREAM=ROOT/'scripts/run_heterogeneous_native_quality.py'
UPSTREAM_SHA='e16991e7950e6cc3a9948d59507b768cb2c6fe90d7c098e32a644596cc7d3de4'
RESOURCE_ENTRY=ROOT/'scripts/run_operating_reports_200_quality_revision2.py'
RESOURCE_ENTRY_SHA='bbcdbe4d4aee43fa7897c744fa24218c499a41c4eb4971b0d83b1da79ea8670b'
REPORTER_SHA='ac347bb3b5ad637267effa3b81cba79f272c53a4d258c1ad314ab930510d606f'
SUMMARY_SHA='520e7b3cec6e69f7798cf906e78480e8a919b658e94e3ac9a3f0272045ee599e'
reference,require=pipeline.reference,pipeline.require


def _load(path,sha,name):
    require(reference(path)['sha256']==sha,'A frozen normal implementation changed')
    loader=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module);return module


generic=_load(UPSTREAM,UPSTREAM_SHA,'_cohort_FM_generic_normal')
resource_entry=_load(RESOURCE_ENTRY,RESOURCE_ENTRY_SHA,'_cohort_FM_strict_resource_gate')
_namespace={**vars(generic),'__file__':__file__,'__name__':'_isolated_FM_cohort_normal',
    'pipeline':pipeline,'KIND':KIND,'DEFAULT_CONFIG':DEFAULT_CONFIG,'_SESSIONS':{}}


def _clone(function,namespace):
    copied=FunctionType(function.__code__,namespace,function.__name__,function.__defaults__,function.__closure__)
    copied.__kwdefaults__=deepcopy(function.__kwdefaults__)
    if copied.__kwdefaults__ and 'config_path' in copied.__kwdefaults__:copied.__kwdefaults__['config_path']=DEFAULT_CONFIG
    return copied


for name,value in vars(generic).items():
    if isinstance(value,FunctionType) and value.__globals__ is vars(generic):_namespace[name]=_clone(value,_namespace)


def _adapt():
    counts={'prepare_admission':0,'cold_admission':0,'scope':0,'url':0,'debugging':0};functions=[]
    class Adapt(ast.NodeTransformer):
        def __init__(self,preparing):self.preparing=preparing
        def visit_Call(self,node):
            node=self.generic_visit(node)
            if ast.unparse(node.func)=='pipeline.NativeScopeAdmission':
                key='prepare_admission' if self.preparing else 'cold_admission';counts[key]+=1
                node.keywords.extend([ast.keyword(arg='artifact_directory',value=ast.parse("out/'private/admission_material'",mode='eval').body),
                    ast.keyword(arg='create',value=ast.Constant(self.preparing))])
            return node
        def visit_Dict(self,node):
            node=self.generic_visit(node)
            for key,value in zip(node.keys,node.values):
                if isinstance(key,ast.Constant) and key.value=='debugging_eligible':
                    require(isinstance(value,ast.Constant) and value.value is True,'The exact FM seed eligibility changed')
                    value.value=False;counts['debugging']+=1
            return node
        def visit_Constant(self,node):
            if node.value=='766 audited task outputs':node.value='93510 complete independently checked cohort business fields';counts['scope']+=1
            elif node.value=='local:scoped-native-business-views':node.value='local:predeclared-financial-cohort-FM-views';counts['url']+=1
            return node
    for node in ast.parse(UPSTREAM.read_bytes()).body:
        if isinstance(node,ast.FunctionDef) and node.name in ('prepare','validate_prepared'):
            functions.append(Adapt(node.name=='prepare').visit(node))
    require(counts=={'prepare_admission':1,'cold_admission':1,'scope':1,'url':1,'debugging':1},
        'The exact private instruction artifact or cohort preparation seams changed')
    exec(compile(ast.fix_missing_locations(ast.Module(body=functions,type_ignores=[])),str(UPSTREAM),'exec'),_namespace)
    return counts


ADAPTATION_COUNTS=_adapt();_prepare=_namespace['prepare'];_validate=_namespace['validate_prepared']
_namespace['_trial_agent_identity']=_clone(resource_entry._trial_agent_identity,_namespace)


def _inspected_binding(path,expected):
    """Validate the complete resource package before matching its known binding shape."""
    from sheets_factory.evaluation.resource_harbor import inspect_resource_export, RESOURCE_FIELD
    full=inspect_resource_export(path)
    base={'task_id','task_name','revision','revision_hash','export_manifest_sha256'}
    rich=base|{'required_controls',RESOURCE_FIELD}
    require(type(expected) is dict and set(expected) in (base,rich) and set(full)==rich,
        'Only exact original five-field or complete seven-field export bindings are supported')
    return full if set(expected)==rich else {key:full[key] for key in base}


def _resource_gate():
    function=next(n for n in ast.parse(UPSTREAM.read_bytes()).body
        if isinstance(n,ast.FunctionDef) and n.name=='validate_normal_resources')
    getter=ast.dump(ast.parse("config['agent']['name']",mode='eval').body,include_attributes=False)
    counts={'agent_identity':0,'resource_binding':0}
    class Gate(ast.NodeTransformer):
        def visit_Subscript(self,node):
            if ast.dump(node,include_attributes=False)==getter:
                counts['agent_identity']+=1
                return ast.copy_location(ast.parse('_trial_agent_identity(config,result,config_path,staged,agent)',mode='eval').body,node)
            return self.generic_visit(node)
        def visit_Call(self,node):
            node=self.generic_visit(node)
            if isinstance(node.func,ast.Name) and node.func.id=='inspect_export':
                require(len(node.args)==1 and not node.keywords,'The exact export inspection seam changed')
                counts['resource_binding']+=1
                return ast.copy_location(ast.Call(func=ast.Name(id='_inspected_binding',ctx=ast.Load()),
                    args=[node.args[0],ast.Name(id='binding',ctx=ast.Load())],keywords=[]),node)
            return node
    function=Gate().visit(function)
    require(counts=={'agent_identity':1,'resource_binding':2},'The strict resource identity seams changed')
    _namespace['_inspected_binding']=_inspected_binding
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),str(UPSTREAM),'exec'),_namespace)
    return counts


RESOURCE_ADAPTATION_COUNTS=_resource_gate()


def recipes(config,admissions):
    rows=generic.runtime.recipes(config,[])
    paths=[__file__,UPSTREAM,RESOURCE_ENTRY,resource_entry.FROZEN_ENTRY,DEFAULT_CONFIG,pipeline.REGISTRY,
        pipeline.__file__,nodes.__file__,nodes.frozen.__file__,nodes.base.__file__,pipeline.base.__file__,
        nodes.receipt.__file__,*nodes.receipt.DEPENDENCIES,reporting.__file__,reference_evidence.__file__]
    for path in paths:
        row=reference(path);rows[row['path']]=row['sha256']
    for value in admissions:rows.update(value.recipe)
    return rows


def prepare(terminals,output,*,config_path=DEFAULT_CONFIG):
    require(type(terminals) is list and 1<=len(terminals)<=9,'Declare one through nine fixed new genuine FM task terminals')
    result=_prepare(terminals,output,config_path=config_path)
    frozen,config,admissions=_validate(output)
    proofs=[pipeline.admission(v) for v in admissions]
    require(len({p['case_id'] for p in proofs})==len(proofs),'A fixed raw case cannot enter the normal cohort twice')
    return result


def validate_prepared(output):
    frozen,config,admissions=_validate(output);proofs=[pipeline.admission(v) for v in admissions]
    require(frozen['kind']==KIND and 1<=frozen['count']<=9 and frozen['count']==len(proofs)
        and frozen['targets']=={'financial_modeling':len(proofs),'debugging':0}
        and len({p['case_id'] for p in proofs})==len(proofs)
        and all(p['mode']=='financial_modeling' and p['original_dev_and_normal_scores_transferred'] is False for p in proofs)
        and frozen['independent_public_solver_attempted'] is frozen['existing_development_score_transferred'] is False,
        'Only the exact genuine new FM inventory can enter normal quality')
    return frozen,config,admissions


_namespace.update(recipes=recipes,validate_prepared=validate_prepared)
execute_prepared=_namespace['execute_prepared'];validate_normal_resources=_namespace['validate_normal_resources']
write=generic.write


def _bound_audited_context(evidence,private,context):
    require(reference(reference_evidence.__file__)['sha256']==SUMMARY_SHA,'The frozen summary producer changed')
    transport=evidence.get('private_evidence',{})
    require(type(transport.get('summary_version')) is int and transport['summary_version']==1
        and transport.get('summary_is_not_a_quality_verdict') is True
        and transport.get('private_summary')==private,'The actual private summary payload changed')
    canonical=reference_evidence._bytes(context);digest=hashlib.sha256(canonical).hexdigest()
    require(transport.get('field_inventory',{}).get('reference_review_context')=={'type':'dict','count':len(context),'sha256':digest}
        and private.get('reference_review_context')==reference_evidence._compact(context,'/reference_review_context'),
        'The complete current context inventory or exact frozen compaction changed')
    full=transport.get('full_artifact',{})
    require(set(full)=={'path','sha256','bytes','complete','encoding'} and full['complete'] is True and full['encoding']=='UTF-8 JSON',
        'A complete original private evidence artifact is required')
    record={key:full[key] for key in ('path','sha256','bytes')};refs=pipeline.References();path=refs.check(record)
    marker=b'"reference_review_context": '
    with path.open('rb') as handle,mmap.mmap(handle.fileno(),0,access=mmap.ACCESS_READ) as mapped:
        index=mapped.find(marker)
        require(index>=0 and mapped.find(marker,index+len(marker))==-1,'The full artifact needs one unique original current-context fragment')
        start=index+len(marker)
        require(mapped[start:start+len(canonical)]==canonical and mapped[start+len(canonical):start+len(canonical)+1] in (b',',b'}'),
            'The complete private artifact differs from the exact current reference context')
    require(reference(path)==record,'The complete private artifact changed while reading')
    return True


def _reporter():
    require(reference(reporting.__file__)['sha256']==REPORTER_SHA,'The frozen normal reporter changed')
    ns={**vars(reporting),'_bound_audited_context':_bound_audited_context}
    for name,value in vars(reporting).items():
        if isinstance(value,FunctionType) and value.__globals__ is vars(reporting):ns[name]=_clone(value,ns)
    function=next(n for n in ast.parse(Path(reporting.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='_reference_review')
    target=ast.dump(ast.parse("private.get('reference_review_context') == context",mode='eval').body,include_attributes=False);changes=[]
    class Transport(ast.NodeTransformer):
        def visit_Compare(self,node):
            if ast.dump(node,include_attributes=False)==target:
                changes.append('complete_bound_context');return ast.copy_location(ast.parse('_bound_audited_context(evidence, private, context)',mode='eval').body,node)
            return self.generic_visit(node)
    function=Transport().visit(function);require(changes==['complete_bound_context'],'The exact reporter transport comparison changed')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),str(Path(reporting.__file__)),'exec'),ns)
    return ns


_reporting=_reporter()
reference_review=_reporting['_reference_review']
generate_report=_reporting['generate_report']
write_reports=_reporting['write_reports']


def _monitor():
    function=next(n for n in ast.parse(resource_entry.FROZEN_ENTRY.read_bytes()).body
        if isinstance(n,ast.FunctionDef) and n.name=='admission_monitor')
    function.args.kwonlyargs.append(ast.arg(arg='declared_count'));function.args.kw_defaults.append(ast.Constant(0))
    counts={'name':0,'kind':0,'count':0}
    class Monitor(ast.NodeTransformer):
        def visit_Constant(self,node):
            if node.value=='Fixed200 FM normal quality · admission and execution':
                counts['name']+=1;node.value='Financial cohort FM normal quality · admission and execution'
            elif node.value=='fixed200_normal_admission_outer_monitor':
                counts['kind']+=1;node.value='financial_cohort_FM_normal_admission_outer_monitor'
            return node
        def visit_Dict(self,node):
            node=self.generic_visit(node)
            for index,key in enumerate(node.keys):
                if isinstance(key,ast.Constant) and key.value=='target_count':
                    require(isinstance(node.values[index],ast.Constant) and node.values[index].value==1,
                        'The known monitor target-count seam changed')
                    counts['count']+=1;node.values[index]=ast.Name(id='declared_count',ctx=ast.Load())
            return node
    function=Monitor().visit(function)
    require(counts=={'name':1,'kind':1,'count':1},'The exact pre-admission monitor metadata changed')
    ns={**globals(),'_base':generic}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),str(resource_entry.FROZEN_ENTRY),'exec'),ns)
    return ns['admission_monitor']


admission_monitor=_monitor()


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--actual-terminal',type=Path,action='append')
    p.add_argument('--output',type=Path);p.add_argument('--config',type=Path,default=DEFAULT_CONFIG)
    p.add_argument('--prepared',type=Path);p.add_argument('--run',action='store_true');p.add_argument('--port',type=int,default=0)
    args=p.parse_args(argv);require(0<=args.port<=65535,'Use a valid local dashboard port')
    if args.prepared:
        require(not args.actual_terminal and args.output is None and args.config==DEFAULT_CONFIG,'Keep the exact frozen inputs/configuration')
        with admission_monitor(args.prepared,'run' if args.run else 'validate') as state:
            if args.run:
                code=execute_prepared(args.prepared,port=args.port);state.update(passed=code==0,inner_exit_code=code);return code
            result=validate_prepared(args.prepared)[0];state['passed']=True
    else:
        require(args.actual_terminal and args.output is not None,'Provide genuine task5 terminals and a fresh output')
        with admission_monitor(args.output,'prepare_and_run' if args.run else 'prepare',declared_count=len(args.actual_terminal)) as state:
            result=prepare(args.actual_terminal,args.output,config_path=args.config)
            if args.run:
                code=execute_prepared(args.output,port=args.port);state.update(passed=code==0,inner_exit_code=code);return code
            state['passed']=True
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
