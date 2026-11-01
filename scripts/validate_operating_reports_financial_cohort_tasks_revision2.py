#!/usr/bin/env python3
"""Five original FM engineering calls using a genuine precision-v2 source.

Source independent expectations remain unchanged. Task primary expectations are
the unchanged two-decimal typed values of the genuine native goal, never values
written back to a workbook. The complete original grader and controls remain.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import FunctionType,SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'scripts/validate_operating_reports_financial_cohort_tasks.py'
BASE_SHA='8188d2add6e96660f8b7401114d4d6af6bc46ffd6f01647971daa50eefd77b91'
SOURCE_SCRIPT=ROOT/'scripts/build_operating_reports_financial_cohort_source_revision2.py'
SOURCE_SHA='8dda220e8b7077e2c8a0bebc5c98d6b82fd633c72cddf82bd0956e3c6278f4d0'
SOURCE_KIND='independently_checked_operating_reports_financial_cohort_source_precision_revision2'
POLICY_SHA='76c8c2e0895f68fce6a1288fcac7817bf33a3cb2123995f8ac25e0ea9d43b210'
KIND='prepared_operating_reports_financial_cohort_FM_task_engineering_revision2'
TERMINAL_KIND='complete_operating_reports_financial_cohort_FM_task_engineering_revision2'
VERSION=2
if hashlib.sha256(BASE.read_bytes()).hexdigest()!=BASE_SHA:raise ValueError('The frozen original five-call task protocol changed')
_loader=importlib.util.spec_from_file_location('_precision_v2_original_FM_task',BASE)
previous=importlib.util.module_from_spec(_loader);_loader.loader.exec_module(previous)
STAGES=previous.STAGES;COUNTS=deepcopy(previous.COUNTS)
_P={**vars(previous),'__file__':str(Path(__file__).resolve()),'__name__':'_private_precision_v2_FM_task',
    'KIND':KIND,'TERMINAL_KIND':TERMINAL_KIND,'SOURCE_SCRIPT':SOURCE_SCRIPT,'SOURCE_SHA':SOURCE_SHA,'SOURCE_KIND':SOURCE_KIND,'source':None}
_N={**previous._N,'__file__':str(Path(__file__).resolve()),'__name__':'_private_precision_v2_FM_workflow',
    'KIND':KIND,'TERMINAL_KIND':TERMINAL_KIND,'source':None}
for _namespace,_old in ((_P,vars(previous)),(_N,previous._N)):
    for _name,_value in _old.items():
        if isinstance(_value,FunctionType)and _value.__globals__ is _old:
            _new=FunctionType(_value.__code__,_namespace,_name,_value.__defaults__,_value.__closure__)
            _new.__kwdefaults__=deepcopy(_value.__kwdefaults__);_namespace[_name]=_new
_P['_N']=_N
reference,checked,read,write,require=(_N[k]for k in ('reference','checked','read','write','require'))
source=None


def _activate():
    global source
    require(reference(BASE)['sha256']==BASE_SHA and reference(SOURCE_SCRIPT)['sha256']==SOURCE_SHA,
        'Use the exact frozen task and precision-v2 source provider')
    if source is None:
        loader=importlib.util.spec_from_file_location('_precision_v2_genuine_source_provider',SOURCE_SCRIPT)
        module=importlib.util.module_from_spec(loader);loader.loader.exec_module(module)
        source=SimpleNamespace(**{**vars(module.base),**module._N,**vars(module)})
    require(source.SOURCE_KIND==SOURCE_KIND and source.VERSION==2 and source.POLICY_SHA==POLICY_SHA,
        'A foreign or legacy source provider cannot enter task revision2')
    _P['source']=source
    _N.update(source=source,AuditStore=source.AuditStore,DashboardServer=source.DashboardServer,
        ProducerLease=source.ProducerLease,ThreadCappedResourceLibreOfficeEngine=source.ThreadCappedResourceLibreOfficeEngine)
    return source


def recipes():
    s=_activate();require(reference(previous.ANCESTOR)['sha256']==previous.ANCESTOR_SHA,'The original complete task lifecycle changed')
    return {**s.recipes(),**{str(Path(path).resolve()):reference(path)for path in
        (Path(__file__),BASE,previous.ANCESTOR,previous.base.streaming_verifier.__file__)}}


def _typed(row):
    require(type(row)is dict and set(row)=={'type','value'} and row['type']in ('number','boolean','text')
        and type(row['value'])is (bool if row['type']=='boolean'else str),
        'Task expectation values must preserve canonical numeric, Boolean and text types')


def _primary_expected(goal,independent_ref):
    """Read a physical goal; perform no calculation or workbook mutation."""
    _activate();independent=read(independent_ref)
    require(type(independent)is dict and len(independent)==COUNTS['business'],'Bind the complete original independent financial scope')
    snapshot=_N['snapshot'](checked(goal),independent);observed=snapshot['values']
    require(not any(row['type']=='error'for row in observed.values()),'The genuine goal contains a native error')
    result={}
    for point,original in independent.items():
        actual=observed.get(point)
        _typed(original)
        if actual is not None:_typed(actual)
        require(actual is not None and actual['type']==original['type'] and actual['type']in ('number','boolean','text'),
            'Every original financial position must preserve its exact type')
        require(actual['type']=='number'or actual==original,'Boolean and supplied NA values remain exact')
        result[point]=deepcopy(actual)
    checked(goal);checked(independent_ref)
    return result


def _check_primary(f,sf,actual,expected):
    require(actual['kind']==SOURCE_KIND and type(actual['version'])is int and actual['version']==2
        and actual['passed'] is True and actual['source']==f['genuine_goal']==f['actual_primary_expected_from_genuine_goal_ref']
        and f['source_independent_expected']==sf['expected'] and f['source_precision_policy_sha256']==sf['source_only_policy_sha256']==POLICY_SHA,
        'Retain the original independent expectation and exact genuine source-v2 goal lineage')
    checked(f['source_independent_expected'])
    require(type(expected)is dict,'The complete task primary expectation map is required')
    for row in expected.values():_typed(row)
    require(expected==_primary_expected(f['genuine_goal'],f['source_independent_expected']),
        'The task primary map must equal all actual goal values; no substituted financial answer map')


def _prepare_and_validation():
    counts={'source_version':0,'primary_map':0,'expected_ref':0,'prepared_version':0,'validation_version':0,'lineage_tuple':0,'primary_recheck':0}
    class Adapt(ast.NodeTransformer):
        scope=None
        def visit_FunctionDef(self,node):
            old=self.scope;self.scope=node.name;node=self.generic_visit(node);self.scope=old;return node
        def visit_Compare(self,node):
            text=ast.unparse(node)
            if self.scope=='prepare'and text=="actual['version'] == 1":counts['source_version']+=1;node.comparators[0]=ast.Constant(2)
            elif self.scope=='validate_prepared'and text=="f['version'] == 1":counts['validation_version']+=1;node.comparators[0]=ast.Constant(VERSION)
            return self.generic_visit(node)
        def visit_Assign(self,node):
            node=self.generic_visit(node)
            if self.scope=='prepare'and len(node.targets)==1 and isinstance(node.targets[0],ast.Tuple)and [getattr(n,'id',None)for n in node.targets[0].elts]==['candidate','public','bindings','original','expected']:
                counts['primary_map']+=1
                return [node,ast.parse("expected = _primary_expected(actual['source'], sf['expected'])").body[0]]
            return node
        def visit_Dict(self,node):
            if self.scope=='prepare'and any(isinstance(k,ast.Constant)and k.value=='kind'and isinstance(v,ast.Name)and v.id=='KIND'for k,v in zip(node.keys,node.values)):
                for index,key in enumerate(node.keys):
                    if isinstance(key,ast.Constant)and key.value=='version':counts['prepared_version']+=1;node.values[index]=ast.Constant(VERSION)
                    if isinstance(key,ast.Constant)and key.value=='expected':
                        require(ast.unparse(node.values[index])=="sf['expected']",'Unexpected original independent expectation assignment')
                        counts['expected_ref']+=1;node.values[index]=ast.parse("write(output / 'expected.private.json', expected)",mode='eval').body
                for key,value in (('source_independent_expected',"sf['expected']"),('actual_primary_expected_from_genuine_goal_ref',"actual['source']"),('source_precision_policy_sha256',"sf['source_only_policy_sha256']")):
                    node.keys.append(ast.Constant(key));node.values.append(ast.parse(value,mode='eval').body)
            return self.generic_visit(node)
        def visit_Tuple(self,node):
            if self.scope=='validate_prepared'and ast.unparse(node)=="('specification', 'bindings', 'expected', 'raw_inventory', 'runtime_profile', 'runtime_profile_value')":
                counts['lineage_tuple']+=1;node.elts=[v for v in node.elts if not(isinstance(v,ast.Constant)and v.value=='expected')]
            return self.generic_visit(node)
        def visit_Return(self,node):
            if self.scope=='validate_prepared'and isinstance(node.value,ast.Name)and node.value.id=='f':
                counts['primary_recheck']+=1;return [ast.parse('_check_primary(f, sf, actual, expected)').body[0],node]
            return self.generic_visit(node)
    nodes=[node for node in ast.parse(BASE.read_bytes()).body if isinstance(node,ast.FunctionDef)and node.name in ('prepare','validate_prepared')]
    nodes=Adapt().visit(ast.Module(body=nodes,type_ignores=[]))
    require(counts==dict.fromkeys(counts,1),'The exact task source/primary-map adaptation sites changed: '+str(counts))
    exec(compile(ast.fix_missing_locations(nodes),str(BASE),'exec'),_P)
    return counts


def _workflow_tree():
    """Only protocol-version metadata differs from the full original lifecycle."""
    tree=ast.parse(previous.ANCESTOR.read_bytes());counts={'terminal_version':0,'validation_version':0}
    for function in tree.body:
        if not isinstance(function,ast.FunctionDef):continue
        for node in ast.walk(function):
            if function.name=='execute_prepared'and isinstance(node,ast.Dict)and any(isinstance(k,ast.Constant)and k.value=='kind'and isinstance(v,ast.Name)and v.id=='TERMINAL_KIND'for k,v in zip(node.keys,node.values)):
                for index,key in enumerate(node.keys):
                    if isinstance(key,ast.Constant)and key.value=='version':
                        require(isinstance(node.values[index],ast.Constant)and node.values[index].value==1,'Unexpected terminal protocol version')
                        counts['terminal_version']+=1;node.values[index]=ast.Constant(VERSION)
            if function.name=='validate_completed'and isinstance(node,ast.Compare)and ast.unparse(node)=="t['version'] == 1":
                counts['validation_version']+=1;node.comparators[0]=ast.Constant(VERSION)
    require(counts=={'terminal_version':1,'validation_version':1},'Only the two original terminal protocol version sites may change')
    return tree


def _workflow():
    node=next(n for n in ast.parse(BASE.read_bytes()).body if isinstance(n,ast.FunctionDef)and n.name=='_adapt_workflow');changed=[]
    class Tree(ast.NodeTransformer):
        def visit_Call(self,node):
            if ast.unparse(node)=='ast.parse(ANCESTOR.read_bytes())':changed.append(True);return ast.Call(func=ast.Name('_workflow_tree',ast.Load()),args=[],keywords=[])
            return self.generic_visit(node)
    node=Tree().visit(node);require(len(changed)==1,'The original exact FM workflow compiler changed')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(BASE),'exec'),_P)
    return _P['_adapt_workflow']()


_P.update(_activate=_activate,recipes=recipes,_primary_expected=_primary_expected,_check_primary=_check_primary,_workflow_tree=_workflow_tree)
ADAPTATION_COUNTS=_prepare_and_validation();WORKFLOW_COUNTS=_workflow()
prepare=_P['prepare'];validate_prepared=_P['validate_prepared']
for _name in ('forecast_keys','verify_definitions','verify_input_caches','_control_target'):
    globals()[_name]=_P[_name]
_N.update(recipes=recipes,validate_prepared=validate_prepared,verify_definitions=verify_definitions,verify_input_caches=verify_input_caches)


def execute_prepared(output):_activate();return _N['_execute_prepared_FM'](output)
def validate_completed(value):_activate();return _N['_validate_completed_FM'](value)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source-manifest','output','prepared'):parser.add_argument('--'+name,type=Path)
    parser.add_argument('--run',action='store_true');args=parser.parse_args(argv)
    if args.prepared:
        require(not(args.source_manifest or args.output),'Use the exact frozen new task preparation')
        result=execute_prepared(args.prepared)if args.run else validate_prepared(args.prepared)
    else:
        require(not args.run and args.source_manifest and args.output,'Prepare and review before the separate original five-call attempt')
        result=prepare(args.source_manifest,args.output)
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
