"""C00 nodes over the unchanged twelve-check and receipt machinery."""
from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
import shutil
from types import FunctionType

from ..pipelines import operating_reports_200_debug_quality as pipeline
from . import operating_reports_200_quality as frozen

ROOT,SETTING,PROFILE,REGISTRY=pipeline.ROOT,pipeline.SETTING,pipeline.PROFILE,pipeline.REGISTRY
reference,require,admission,setting=pipeline.reference,pipeline.require,pipeline.admission,pipeline.setting
FROZEN_SHA='d4e37353164ed1647ccd9564297a48bf1bebb86edd374ff964e9a50f7e5b4d44'
require(reference(frozen.__file__)['sha256']==FROZEN_SHA,'The frozen complete-report normal nodes changed')
base,receipt=frozen.base,frozen.receipt
REWARDS,TaskRejected=frozen.REWARDS,frozen.TaskRejected
validate_reference_export=frozen.validate_reference_export
_namespace={**frozen._namespace,**vars(frozen),**globals(),'pipeline':pipeline}


def _clone(function):
    copied=FunctionType(function.__code__,_namespace,function.__name__,function.__defaults__,function.__closure__)
    copied.__kwdefaults__=deepcopy(function.__kwdefaults__);return copied


def context(ctx):
    require(ctx.config.get(SETTING)==setting(),'The exact C00 normal route changed')
    value=ctx.data.get('_native_scope_admission');proof=admission(value)
    require(ctx.mode==proof['mode']=='debugging' and reference(ctx.source)==proof['workbook'],
        'Only the fixed exact C00 debugging task is admitted')
    for key in ('input','goal','baseline'):
        if ctx.data.get(key):
            observed=reference(ctx.data[key]);wanted=proof['goal' if key=='baseline' else key]
            require((observed['sha256'],observed['bytes'])==(wanted['sha256'],wanted['bytes']),
                'An unchanged first-v6 task workbook was replaced: '+key)
    return value,proof


def canonical_plan(value):
    proof=admission(value);helper=value.helper;prepared=value.evidence['preparation']
    definition=helper.read(prepared['source_definition']);faults=value.evidence['plan']['DBG_faults'];edits=[]
    for key,row in sorted(faults.items()):
        point=row['sheet']+'!'+row['cell']
        require(point in definition['formulas'] and point not in definition['literals']
            and definition['formulas'][point]==row['healthy_formula'] and row['healthy_formula']!=row['faulty_formula'],
            'Every original root replaces its healthy formula without touching a given field')
        edits.append({'sheet':row['sheet'],'cell':row['cell'],'before':row['healthy_formula'],
            'after':row['faulty_formula'],'reason':'Repair the forecast management reports.'})
    require(len(edits)==200,'Keep all200 original revised fault roots')
    public=helper.read(prepared['specification'])
    return {'title':'Repair the forecast management reports','mode':'debugging',
        'public_instruction':Path(proof['instruction']['path']).read_text(),
        'public_rules':[public['public_policy']],'scenario_inputs':[],'edits':edits,
        'reference_evidence':[{'kind':'complete_independent_C00_business_fields','expected':proof['independent_expected'],
            'actual_validation':proof['actual_validation'],'specification':proof['specification'],
            'independent_business_fields':93510,'nonzero_root_impacts':value.evidence['lineage']['pure_design_proof']}],
        'family_adapter':{'id':SETTING,'complete_D_count':18240,'independent_business_fields':93510,
            'physical_edit_count':200,'first_development_material_identity':pipeline.FIRST_MATERIAL,
            'normal_quality_or_score_inherited':False}}


independent_evidence=_clone(frozen.independent_evidence)


class PlanNode(frozen.PlanNode):
    def execute(self,ctx):
        _,proof=context(ctx)
        return {'plan':canonical_plan(ctx.data['_native_scope_admission']), 'source_assessment':{
            'actual_task_validation':proof['actual_validation'],'independent_expected':proof['independent_expected'],
            'specification':proof['specification'],'independent_business_fields':93510,'source_manifest':proof['source_manifest'],
            'business_scope':'The complete declared hypothetical 200-entity specification.',
            'source_business_issues':ctx.data.get('source_business_issues',[]),'prior_normal_clear_inherited':False}}


class ConstructNode(frozen.ConstructNode):
    def execute(self,ctx):
        value,proof=context(ctx);plan=canonical_plan(value)
        require(ctx.data['plan']==plan,'Preserve the exact task and brief; content repair requires a new checked revision')
        public,private=ctx.revision_dir/'public',ctx.revision_dir/'private'
        public.mkdir(parents=True,exist_ok=True);private.mkdir(parents=True,exist_ok=True)
        source,goal=public/'input.xlsx',private/'goal.xlsx'
        shutil.copyfile(proof['input']['path'],source);shutil.copyfile(proof['goal']['path'],goal)
        delta=base.compare_workbooks(source,goal,goal)
        definition=value.helper.read(value.evidence['preparation']['source_definition'])
        labels=sorted(delta['expected_changes']);roots=sorted(row['sheet']+'!'+row['cell'] for row in plan['edits'])
        require(delta['reward']==1 and labels==value.evidence['full_D'] and len(labels)==len(set(labels))==18240
            and len(roots)==len(set(roots))==200 and set(roots)<=set(labels),
            'The complete actual18240 changed-value closure must preserve all200 original roots')
        require(not set(labels)&set(definition['literals']),'A task output intersects a supplied field')
        guard=base.evaluate_native_risk_guard(labels,proof['workbook']['sha256'],project_root=ctx.config['project_root'],
            sheet_names=definition['sheetnames'],legacy_risks=ctx.data.get('source_business_issues',[]))
        require(not guard['blocking'],'A registered source risk intersects the current complete task')
        probe=independent_evidence(value,proof,goal,labels,ctx.revision)
        witnesses={row['key']:row for row in value.evidence['impact']['witnesses']}
        require(set(witnesses)==set(value.evidence['plan']['DBG_faults']),'Every root needs its independent impact witness')
        impacts=[{'root':row['sheet']+'!'+row['cell'],'semantic_key':key,
            'evidence':{'independent_exact_nonzero_witness':witnesses[key],
                'actual_joint_full_D':proof['full_D_controls'],
                'independent_root_and_joint_closure_are_separate':True}}
            for key,row in sorted(value.evidence['plan']['DBG_faults'].items())]
        validation={'edit_count':200,'before_assertions_passed':True,'full_D_count':18240,
            'physical_edits_checked_by_actual_view_validation':proof['actual_validation'],
            'independent_expected':proof['independent_expected'],
            'actual_family_root_counts':pipeline.FAMILIES,'reference_values_not_modified':True,
            'native_error_candidates':[],'native_error_probe':probe,
            'all_given_facts_protected_by_exact_immutable_bytes':True,'new_LO_calls':0}
        for name,row in [('plan.json',plan),('edit_validation.json',validation),('expected_delta.json',delta),
            ('root_impacts.json',impacts),('native_risk_guard.json',guard),('native_error_probe.json',probe)]:ctx.save(name,row)
        profile=base.profile_workbook(source,max_cells=3000000,per_formula_reference_cells=5000)
        require(not profile['truncated'],'The complete actual public task profile is required')
        return {'input':source,'goal':goal,'delta':delta,'construction_validation':validation,
            'root_impacts':impacts,'native_risk_guard':guard,'public_profile':profile}


def _controls():
    tree=ast.parse(Path(frozen.__file__).read_bytes())
    cls=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='ControlsNode')
    function=next(node for node in cls.body if isinstance(node,ast.FunctionDef) and node.name=='execute');changes=[]
    class Control(ast.NodeTransformer):
        def visit_Constant(self,node):
            if node.value=='FM_missed_root':changes.append('missed_root');node.value='DBG_missed_root'
            return node
    function=Control().visit(function);require(changes==['missed_root'],'The exact missed-root control seam changed')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),str(Path(frozen.__file__)),'exec'),_namespace)
    return _namespace.pop('execute')


_namespace.update(globals())
for name in ('NormalizeNode','ProfileNode','InstructionNode','DiagnoseNode','RepairNode','ExportNode'):
    old=getattr(frozen,name)
    globals()[name]=type(name,(old,),{'__module__':__name__,'execute':_clone(old.execute)})
_namespace['_export']=_clone(frozen._export)
ControlsNode=type('ControlsNode',(frozen.ControlsNode,),{'__module__':__name__,'execute':_controls()})
