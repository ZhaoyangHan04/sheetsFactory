"""Private cohort bindings over the unchanged twelve-check normal nodes."""
from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
from types import FunctionType

from ..pipelines import operating_reports_financial_cohort_quality as pipeline
from . import operating_reports_200_quality as frozen

ROOT,SETTING,PROFILE,REGISTRY=pipeline.ROOT,pipeline.SETTING,pipeline.PROFILE,pipeline.REGISTRY
reference,require,admission,setting=pipeline.reference,pipeline.require,pipeline.admission,pipeline.setting
FROZEN_SHA='d4e37353164ed1647ccd9564297a48bf1bebb86edd374ff964e9a50f7e5b4d44'
require(reference(frozen.__file__)['sha256']==FROZEN_SHA,'The complete fixed-report normal nodes changed')
base,receipt=frozen.base,frozen.receipt
REWARDS,TaskRejected=frozen.REWARDS,frozen.TaskRejected
validate_reference_export=frozen.validate_reference_export
_namespace={**frozen._namespace,**vars(frozen),**globals(),'pipeline':pipeline}


def _clone(function):
    value=FunctionType(function.__code__,_namespace,function.__name__,function.__defaults__,function.__closure__)
    value.__kwdefaults__=deepcopy(function.__kwdefaults__);return value


for name in ('context','independent_evidence','_export'):
    _namespace[name]=_clone(getattr(frozen,name));globals()[name]=_namespace[name]


def _plan():
    node=next(n for n in ast.parse(Path(frozen.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='canonical_plan')
    counts={'material':0,'label':0}
    class Dynamic(ast.NodeTransformer):
        def visit_Attribute(self,node):
            if ast.unparse(node)=='pipeline.FIRST_MATERIAL':
                counts['material']+=1;return ast.copy_location(ast.parse("proof['material_identity']",mode='eval').body,node)
            return self.generic_visit(node)
        def visit_Constant(self,node):
            if node.value=='first_development_material_identity':node.value='material_identity';counts['label']+=1
            return node
    node=Dynamic().visit(node)
    require(counts=={'material':1,'label':1},'The exact fixed material metadata seam changed')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(Path(frozen.__file__)),'exec'),_namespace)
    return counts


PLAN_ADAPTATION_COUNTS=_plan();canonical_plan=_namespace['canonical_plan']
for name in ('NormalizeNode','ProfileNode','PlanNode','ConstructNode','InstructionNode',
    'ControlsNode','DiagnoseNode','RepairNode','ExportNode'):
    old=getattr(frozen,name)
    globals()[name]=type(name,(old,),{'__module__':__name__,'execute':_clone(old.execute)})
