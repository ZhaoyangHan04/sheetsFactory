#!/usr/bin/env python3
"""Review the unchanged first eight-business FM task through normal quality."""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from types import FunctionType,SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'scripts'))
from sheets_factory.pipelines import heterogeneous_native_quality as original
from sheets_factory.task_adapters import heterogeneous_native_quality as original_nodes
from sheets_factory.task_adapters import reference_receipt_diagnosis as receipt
from sheets_factory.task_adapters.linear_capital_scaled_reference_review import validate_reference_export
from sheets_factory.core.node import TaskRejected

reference,require=original.reference,original.require
KIND='prepared_fixed_native_business_FM_recovery_normal_quality'
DEFAULT_CONFIG=ROOT/'config/pipelines/native_business_recovery_quality_v1.yaml'
REGISTRY=ROOT/'config/task_adapters/native_business_recovery_quality_nodes.yaml'
FROZEN=ROOT/'scripts/run_operating_reports_financial_cohort_quality.py'
FROZEN_SHA='9955d2e4da4af0ed2cba54bf635a89db1a9c20fef83d6122adb2b7c48651fb7d'
ACTUAL_SHA='182baab641aeb5f452c4b2756f236aa6747a3953d83b983282ef0c0246a9d97d'
INPUT_SHA='32b2393fbdbc60dfbee7b516ad4488bd7142dd5367a71032cb7b121aa48ef991'
GOAL_SHA='0bd227e0c110ba5bfdd3f59c99c390f850a9b713d641ba8eec06aa8563af6fd3'
INSTRUCTION_SHA='49e10509880a9205aef5c8324053f365b8c4d888db3c13367d1b5a806a7235f4'
DEV_PROBE=ROOT/'outputs/difficulty/heterogeneous-native-FM-first-development-20261031T152500Z/prepared/probe_manifest.json'
DEV_SHA='65ff46a57c40df0b5bcd22689b8cf61135fe47a0ad50ae0baa21cf21436d8a09'
PINS={original.__file__:'ac87f3544c1e14f42827b93e895e59015554d93fc6c59b054f54084beeff1b86',
 original_nodes.__file__:'7e9ea8f0ba72b7e91297d3c4a8646ac0d63348a8feb59e6d1c4b5b54a1d991fc',
 str(original.BOUNDARY):'1331f978f13844a9ceef3f3c3f949a79e7e082859b29303a47fba865130d9896',
 receipt.__file__:'076089b9f473bde64b5749b81d0459b8c97e00121553789c57afb605098953dc',
 str(ROOT/'prompts/diagnosis_professional_review_v1.md'):'0c9ef8e30421cd212c2f430f0197c45c28f73e61b62c12d36fc18abba6c2cf43'}
for path,digest in PINS.items():require(reference(path)['sha256']==digest,'A frozen native normal dependency changed')
require(reference(FROZEN)['sha256']==FROZEN_SHA,'The repaired normal resource/reporting implementation changed')
loader=importlib.util.spec_from_file_location('_fixed_native_recovery_normal_helpers',FROZEN)
frozen=importlib.util.module_from_spec(loader);loader.loader.exec_module(frozen)
generic,resource_entry=frozen.generic,frozen.resource_entry
reporting,reference_evidence=frozen.reporting,frozen.reference_evidence


def _clone(function,namespace):
    copied=FunctionType(function.__code__,namespace,function.__name__,function.__defaults__,function.__closure__)
    copied.__kwdefaults__=deepcopy(function.__kwdefaults__)
    if copied.__kwdefaults__ and 'config_path' in copied.__kwdefaults__:copied.__kwdefaults__['config_path']=DEFAULT_CONFIG
    return copied


def admission(value):
    proof=original.admission(value)
    require(proof['mode']=='financial_modeling' and proof['actual_validation']['sha256']==ACTUAL_SHA
        and proof['independent_scope_count']==766 and proof['input']['sha256']==INPUT_SHA
        and proof['goal']['sha256']==GOAL_SHA and proof['instruction']['sha256']==INSTRUCTION_SHA
        and proof['instruction']['bytes']==1247,'Only the exact original eight-business FM766 material may enter this route')
    require(value.evidence['delta']['actual_change_count']==766,'The complete original actual D must contain766 fields')
    return proof


def native_admission(terminal):
    row=reference(terminal['path'] if isinstance(terminal,dict) else terminal)
    require(row['sha256']==ACTUAL_SHA,'Select the exact completed seven-call eight-business FM task')
    if isinstance(terminal,dict):require(row==terminal,'The declared actual task reference changed')
    live=original.NativeScopeAdmission(row);proof=admission(live)
    dev_ref=reference(DEV_PROBE);require(dev_ref['sha256']==DEV_SHA,'The original spent FM snapshot changed')
    dev=live.references.read(dev_ref)
    require(dev['actual_task_validation']==row and dev['complete_changed_value_set_count']==766
        and dev['material_task_version']['sha256']=='3b26ea9e5605ca452a462a37ffea412c789bd5bb3fe9f73c662280813748a737'
        and len(dev['tasks'])==1,'Preserve the original first FM task identity and completeD')
    leaves=dev['tasks'][0]['harbor_export_binding']['resource_runtime']['source_artifacts']
    for key in ('input','goal','instruction'):
        require((leaves[key]['sha256'],leaves[key]['bytes'])==(proof[key]['sha256'],proof[key]['bytes']),
            'The normal input, goal or brief differs from the actual first-model material')
        live.references.check(leaves[key])
    return live


def setting():
    return {'version':1,'scope':'unchanged_original_eight_business_FM766_reference_review',
        'pipeline':reference(__file__),'nodes':reference(__file__),'registry':reference(REGISTRY),
        'runtime_profile':reference(original.PROFILE),'actual_task_boundary':reference(original.BOUNDARY)}


_pns={**vars(original),'REGISTRY':REGISTRY,'setting':setting,'admission':admission,'__file__':__file__}
_validate_config=_clone(original.validate_configuration,_pns)


def validate_configuration(config):
    profile=_validate_config(config)
    require(config['run']['targets']=={'financial_modeling':1,'debugging':0}
        and config['run']['max_sources']==config['run']['max_parallel_sources']==1
        and config['agents']['model']=='gpt-6-sol' and config['agents']['reasoning_effort']=='high'
        and config['prompt_overrides']['diagnosis.md']=='diagnosis_professional_review_v1.md',
        'Keep the one unchanged FM task, ordinary quality model and professional review profile')
    return profile


class NativeQualityFactory(original.NativeQualityFactory):pass


_pns.update(validate_configuration=validate_configuration)
for name in ('__init__','load_seeds','run_phase','_claim_targets'):
    setattr(NativeQualityFactory,name,_clone(getattr(original.NativeQualityFactory,name),_pns))
pipeline=SimpleNamespace(**{**vars(original),'__file__':__file__,'REGISTRY':REGISTRY,'setting':setting,
    'NativeScopeAdmission':native_admission,'admission':admission,'validate_configuration':validate_configuration,
    'NativeQualityFactory':NativeQualityFactory,'base':original})


def context(ctx):
    require(ctx.config.get(original.SETTING)==setting(),'The exact fixed recovery route changed')
    value=ctx.data.get('_native_scope_admission');proof=admission(value)
    require(ctx.mode=='financial_modeling' and reference(ctx.source)==proof['workbook'],'The admitted mode/source changed')
    for key in ('input','goal','baseline'):
        if ctx.data.get(key):
            row=reference(ctx.data[key]);wanted=proof['goal' if key=='baseline' else key]
            require((row['sha256'],row['bytes'])==(wanted['sha256'],wanted['bytes']),'The immutable copied task material changed')
    if ctx.data.get('plan'):
        require(ctx.data['plan']['public_instruction'].encode()==Path(proof['instruction']['path']).read_bytes(),
            'The original 1247-byte business brief cannot change during this review')
    return value,proof


_nns={**vars(original_nodes),'setting':setting,'context':context,'admission':admission}
for name,value in vars(original_nodes).items():
    if isinstance(value,FunctionType) and value.__globals__ is vars(original_nodes):_nns[name]=_clone(value,_nns)
_nns.update(context=context,admission=admission,setting=setting)
for new,old in [('NormalizeNode','NativeNormalizeNode'),('ProfileNode','NativeProfileNode'),('PlanNode','NativePlanNode'),
    ('ConstructNode','NativeConstructNode'),('InstructionNode','NativeInstructionNode'),('ControlsNode','NativeControlsNode')]:
    cls=getattr(original_nodes,old);globals()[new]=type(new,(cls,),{'__module__':__name__,'execute':_clone(cls.execute,_nns)})


class DiagnoseNode(frozen.nodes.frozen.DiagnoseNode):
    def execute(self,ctx):
        context(ctx)
        require(original_nodes.quality.validate_reference_policy_selection(ctx.config)=='reference_review'
            and ctx.config['diagnosis']['execution']['reference_evidence_transport']=='audited_summary',
            'Keep the complete supported reference receipt protocol')
        receipt.verify_dependencies()
        return receipt.ReferenceReceiptDiagnosisNode._execute_diagnose(self,ctx)


class RepairNode(original_nodes.NativeRepairNode):
    def execute(self,ctx):
        context(ctx);raise TaskRejected('This recovery review preserves the spent task bytes; a content repair needs an explicit new checked revision')


_export=_clone(original_nodes.NativeExportNode.execute,_nns)


class ExportNode(original_nodes.NativeExportNode):
    def execute(self,ctx):
        _,proof=context(ctx);validate_reference_export(ctx);result=_export(self,ctx)
        for name,key in [('environment/input.xlsx','input'),('tests/original_input.xlsx','input'),
            ('solution/reference.xlsx','goal'),('tests/reference.xlsx','goal'),('instruction.md','instruction')]:
            row=reference(result['export_dir']/name);wanted=proof[key]
            require((row['sha256'],row['bytes'])==(wanted['sha256'],wanted['bytes']),'The seventeen-file export changed original task bytes')
        return result


_namespace={**vars(generic),'__file__':__file__,'__name__':'_fixed_native_FM_normal_private',
    'pipeline':pipeline,'KIND':KIND,'DEFAULT_CONFIG':DEFAULT_CONFIG,'_SESSIONS':{}}
for name,value in vars(generic).items():
    if isinstance(value,FunctionType) and value.__globals__ is vars(generic):_namespace[name]=_clone(value,_namespace)


def _adapt():
    function=next(n for n in ast.parse(frozen.UPSTREAM.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='prepare')
    changes=[]
    class Modes(ast.NodeTransformer):
        def visit_Dict(self,node):
            node=self.generic_visit(node)
            for key,value in zip(node.keys,node.values):
                if isinstance(key,ast.Constant) and key.value=='debugging_eligible':
                    require(isinstance(value,ast.Constant) and value.value is True,'The known eligibility seam changed')
                    value.value=False;changes.append('debugging')
            return node
    function=Modes().visit(function);require(changes==['debugging'],'The exact fixed FM-only seed seam changed')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),str(frozen.UPSTREAM),'exec'),_namespace)
    return changes


ADAPTATION_COUNTS=_adapt();_prepare=_namespace['prepare'];_validate=_namespace['validate_prepared']
_front={**vars(frozen),**globals()};_front['_namespace']=_namespace
_namespace['_trial_agent_identity']=_clone(resource_entry._trial_agent_identity,_namespace)
_front['_inspected_binding']=_clone(frozen._inspected_binding,_front)
RESOURCE_ADAPTATION_COUNTS=_clone(frozen._resource_gate,_front)()
_front['_bound_audited_context']=_clone(frozen._bound_audited_context,_front)
_reporting=_clone(frozen._reporter,_front)()
reference_review=_reporting['_reference_review']
generate_report=_reporting['generate_report'];write_reports=_reporting['write_reports']


def recipes(config,admissions):
    rows=generic.runtime.recipes(config,[])
    paths=[__file__,DEFAULT_CONFIG,REGISTRY,FROZEN,frozen.UPSTREAM,frozen.RESOURCE_ENTRY,resource_entry.FROZEN_ENTRY,
        original.__file__,original_nodes.__file__,original.BOUNDARY,receipt.__file__,*receipt.DEPENDENCIES,
        frozen.reporting.__file__,frozen.reference_evidence.__file__]
    for path in paths:
        row=reference(path);rows[row['path']]=row['sha256']
    for live in admissions:rows.update(live.recipe)
    return rows


def prepare(terminals,output,*,config_path=DEFAULT_CONFIG):
    require(type(terminals)is list and len(terminals)==1,'Select only the retained original FM terminal')
    result=_prepare(terminals,output,config_path=config_path);validate_prepared(output);return result


def validate_prepared(output):
    record,config,admissions=_validate(output)
    require(record['kind']==KIND and record['count']==len(admissions)==1
        and record['targets']=={'financial_modeling':1,'debugging':0},'The one exact FM inventory changed')
    admission(admissions[0]);return record,config,admissions


_namespace.update(recipes=recipes,validate_prepared=validate_prepared)
execute_prepared=_namespace['execute_prepared'];validate_normal_resources=_namespace['validate_normal_resources']
write=generic.write


def _monitor():
    function=next(n for n in ast.parse(FROZEN.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='_monitor')
    changes=[]
    class Label(ast.NodeTransformer):
        def visit_Constant(self,node):
            if node.value=='Financial cohort FM normal quality · admission and execution':
                changes.append('name');node.value='Original native business FM · normal admission and review'
            elif node.value=='financial_cohort_FM_normal_admission_outer_monitor':
                changes.append('kind');node.value='native_business_FM_recovery_normal_outer_monitor'
            return node
    function=Label().visit(function);require(sorted(changes)==['kind','name'],'The known early panel labels changed')
    ns={**vars(frozen),**globals()};exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),str(FROZEN),'exec'),ns)
    return ns['_monitor']()


admission_monitor=_monitor()


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--actual-terminal',type=Path);p.add_argument('--output',type=Path)
    p.add_argument('--prepared',type=Path);p.add_argument('--run',action='store_true');p.add_argument('--port',type=int,default=0)
    args=p.parse_args(argv);require(0<=args.port<=65535,'Use a valid local dashboard port')
    if args.prepared:
        require(args.actual_terminal is args.output is None,'Keep the exact frozen prepared selection')
        with admission_monitor(args.prepared,'run' if args.run else 'validate',declared_count=1) as state:
            if args.run:
                code=execute_prepared(args.prepared,port=args.port);state.update(passed=code==0,inner_exit_code=code);return code
            result=validate_prepared(args.prepared)[0];state['passed']=True
    else:
        require(args.actual_terminal is not None and args.output is not None,'Provide the exact retained terminal and a fresh directory')
        with admission_monitor(args.output,'prepare_and_run' if args.run else 'prepare',declared_count=1) as state:
            result=prepare([args.actual_terminal],args.output)
            if args.run:
                code=execute_prepared(args.output,port=args.port);state.update(passed=code==0,inner_exit_code=code);return code
            state['passed']=True
    print(json.dumps(result));return 0


if __name__=='__main__':raise SystemExit(main())
