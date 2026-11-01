#!/usr/bin/env python3
"""Prepare the unchanged SG4000 material for all twelve normal quality checks."""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from types import FunctionType

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.pipelines import operating_reports_debug_classes_quality as pipeline
from sheets_factory.task_adapters import operating_reports_debug_classes_quality as nodes

KIND='prepared_operating_reports_SG4000_debugging_normal_quality'
DEFAULT_CONFIG=pipeline.CONFIG
FROZEN=ROOT/'scripts/run_operating_reports_financial_cohort_quality.py'
FROZEN_SHA='9955d2e4da4af0ed2cba54bf635a89db1a9c20fef83d6122adb2b7c48651fb7d'
reference,require=pipeline.reference,pipeline.require
require(reference(FROZEN)['sha256']==FROZEN_SHA,'The repaired normal resource/reporting frontend changed')
loader=importlib.util.spec_from_file_location('_SG4000_frozen_normal_frontend',FROZEN)
frozen=importlib.util.module_from_spec(loader);loader.loader.exec_module(frozen)
generic,resource_entry=frozen.generic,frozen.resource_entry
UPSTREAM,RESOURCE_ENTRY=frozen.UPSTREAM,frozen.RESOURCE_ENTRY
REPORTER_SHA,SUMMARY_SHA=frozen.REPORTER_SHA,frozen.SUMMARY_SHA
reporting,reference_evidence=frozen.reporting,frozen.reference_evidence


def _clone(function,namespace):
    value=FunctionType(function.__code__,namespace,function.__name__,function.__defaults__,function.__closure__)
    value.__kwdefaults__=deepcopy(function.__kwdefaults__)
    if value.__kwdefaults__ and 'config_path' in value.__kwdefaults__:value.__kwdefaults__['config_path']=DEFAULT_CONFIG
    return value


_namespace={**vars(generic),'__file__':__file__,'__name__':'_SG4000_private_normal',
    'pipeline':pipeline,'KIND':KIND,'DEFAULT_CONFIG':DEFAULT_CONFIG,'_SESSIONS':{}}
for name,function in vars(generic).items():
    if isinstance(function,FunctionType) and function.__globals__ is vars(generic):
        _namespace[name]=_clone(function,_namespace)


def _adapt():
    counts={'scope':0,'url':0,'financial_modeling':0};functions=[]
    class Debugging(ast.NodeTransformer):
        def visit_Dict(self,node):
            node=self.generic_visit(node)
            for key,value in zip(node.keys,node.values):
                if isinstance(key,ast.Constant) and key.value=='financial_modeling_eligible':
                    require(isinstance(value,ast.Constant) and value.value is True,'The exact mode eligibility seam changed')
                    value.value=False;counts['financial_modeling']+=1
            return node
        def visit_Constant(self,node):
            if node.value=='766 audited task outputs':
                node.value='93510 independently checked business fields; full SG4000 actual changed set';counts['scope']+=1
            elif node.value=='local:scoped-native-business-views':
                node.value='local:fixed-SG4000-debugging-view';counts['url']+=1
            return node
    for node in ast.parse(UPSTREAM.read_bytes()).body:
        if isinstance(node,ast.FunctionDef) and node.name in ('prepare','validate_prepared'):
            functions.append(Debugging().visit(node))
    require(counts=={'scope':1,'url':1,'financial_modeling':1},'The exact generic preparation seams changed')
    exec(compile(ast.fix_missing_locations(ast.Module(body=functions,type_ignores=[])),str(UPSTREAM),'exec'),_namespace)
    return counts


ADAPTATION_COUNTS=_adapt();_prepare=_namespace['prepare'];_validate=_namespace['validate_prepared']
# The complete original trial observer, sparse/rich identity check and export
# checks are retained in a fresh namespace. No original module globals change.
_front={**vars(frozen),**globals()}
_inspected_binding=_clone(frozen._inspected_binding,_front)
_namespace['_trial_agent_identity']=_clone(resource_entry._trial_agent_identity,_namespace)
_front['_namespace']=_namespace
_front['_inspected_binding']=_inspected_binding
RESOURCE_ADAPTATION_COUNTS=_clone(frozen._resource_gate,_front)()
_bound_audited_context=_clone(frozen._bound_audited_context,_front)
_front['_bound_audited_context']=_bound_audited_context
_reporting=_clone(frozen._reporter,_front)()
reference_review=_reporting['_reference_review']
generate_report=_reporting['generate_report'];write_reports=_reporting['write_reports']


def recipes(config,admissions):
    rows=generic.runtime.recipes(config,[])
    paths=[__file__,FROZEN,UPSTREAM,RESOURCE_ENTRY,resource_entry.FROZEN_ENTRY,DEFAULT_CONFIG,pipeline.REGISTRY,
        pipeline.__file__,pipeline.base.__file__,nodes.__file__,nodes.frozen.__file__,nodes.base.__file__,
        nodes.receipt.__file__,*nodes.receipt.DEPENDENCIES,reporting.__file__,reference_evidence.__file__]
    for path in paths:
        row=reference(path);rows[row['path']]=row['sha256']
    for value in admissions:rows.update(value.recipe)
    return rows


def prepare(terminals,output,*,config_path=DEFAULT_CONFIG):
    require(type(terminals) is list and len(terminals)==1,'Select exactly the genuine SG4000 task5 terminal')
    result=_prepare(terminals,output,config_path=config_path)
    validate_prepared(output)
    return result


def validate_prepared(output):
    frozen_record,config,admissions=_validate(output)
    proofs=[pipeline.admission(value) for value in admissions]
    require(frozen_record['kind']==KIND and frozen_record['count']==len(proofs)==1
        and frozen_record['targets']=={'financial_modeling':0,'debugging':1}
        and proofs[0]['variant_id']=='SG4000' and proofs[0]['mode']=='debugging'
        and proofs[0]['first_development_material_identity']==pipeline.FIRST_MATERIAL
        and proofs[0]['original_dev_and_normal_scores_transferred'] is False
        and frozen_record['independent_public_solver_attempted'] is frozen_record['existing_development_score_transferred'] is False,
        'Only the unchanged spent SG4000 material can enter fresh normal quality')
    return frozen_record,config,admissions


_namespace.update(recipes=recipes,validate_prepared=validate_prepared)
execute_prepared=_namespace['execute_prepared'];validate_normal_resources=_namespace['validate_normal_resources']
write=generic.write


def _monitor():
    function=next(node for node in ast.parse(FROZEN.read_bytes()).body
        if isinstance(node,ast.FunctionDef) and node.name=='_monitor')
    counts={'name':0,'kind':0}
    class Labels(ast.NodeTransformer):
        def visit_Constant(self,node):
            if node.value=='Financial cohort FM normal quality · admission and execution':
                node.value='SG4000 debugging normal quality · admission and execution';counts['name']+=1
            elif node.value=='financial_cohort_FM_normal_admission_outer_monitor':
                node.value='SG4000_debugging_normal_admission_outer_monitor';counts['kind']+=1
            return node
    function=Labels().visit(function)
    require(counts=={'name':1,'kind':1},'The exact early monitor label seams changed')
    namespace={**vars(frozen),**globals()}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),str(FROZEN),'exec'),namespace)
    return namespace['_monitor']()


admission_monitor=_monitor()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actual-terminal',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--config',type=Path,default=DEFAULT_CONFIG)
    parser.add_argument('--prepared',type=Path);parser.add_argument('--run',action='store_true')
    parser.add_argument('--port',type=int,default=0);args=parser.parse_args(argv)
    require(0<=args.port<=65535,'Use a valid local dashboard port')
    if args.prepared:
        require(args.actual_terminal is None and args.output is None and args.config==DEFAULT_CONFIG,
            'Keep the immutable prepared inputs and configuration')
        with admission_monitor(args.prepared,'run' if args.run else 'validate',declared_count=1) as state:
            if args.run:
                code=execute_prepared(args.prepared,port=args.port);state.update(passed=code==0,inner_exit_code=code);return code
            result=validate_prepared(args.prepared)[0];state['passed']=True
    else:
        require(args.actual_terminal is not None and args.output is not None,'Select the exact task5 terminal and a fresh directory')
        with admission_monitor(args.output,'prepare_and_run' if args.run else 'prepare',declared_count=1) as state:
            result=prepare([args.actual_terminal],args.output,config_path=args.config)
            if args.run:
                code=execute_prepared(args.output,port=args.port);state.update(passed=code==0,inner_exit_code=code);return code
            state['passed']=True
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
