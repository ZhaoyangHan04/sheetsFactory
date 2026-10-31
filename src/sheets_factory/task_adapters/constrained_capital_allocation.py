"""D02 binding of frozen ordinary financial task behavior.

Each template is compiled in a separate namespace. Only declared provider
identities/imports change. The original D01 modules and public solver remain
unchanged; complete AST parity and source hashes are checked before use.
"""
from __future__ import annotations

import ast as _binding_ast
from copy import deepcopy as _binding_copy
import hashlib as _binding_hashlib
from pathlib import Path as _BindingPath

_BINDING_ROOT=_BindingPath(__file__).resolve().parents[3]
TEMPLATE_PATH=_BINDING_ROOT/'src/sheets_factory/task_adapters/scaled_capital_allocation.py'
TEMPLATE_SHA256='e32c4386e8d9679c8e42b6eed71214acf6e2a8099a2df1b17112a1a871a0cff1'
RECOVERY_TEMPLATE_PATH=_BINDING_ROOT/'src/sheets_factory/workbook/capital_allocation_scaled/public_recovery.py'
RECOVERY_TEMPLATE_SHA256='8013d20345ad929b909c688f8c0c36d19861f713ad86caa4ca2e19295df0cb84'

_LITERAL_BINDINGS={
    '30-D01':'30-D02',
    'scaled_capital_common_plan_FM_v1':'constrained_capital_common_plan_FM_v1',
    'sheets_factory.pipelines.scaled_capital_admission':'sheets_factory.pipelines.constrained_capital_admission',
    'src/sheets_factory/workbook/capital_allocation_scaled/catalog.py':'src/sheets_factory/workbook/capital_allocation_scaled/constrained_catalog.py',
    '_scaled_admission_session':'_constrained_admission_session',
}
_NODE_BINDINGS={
    'ScaledCapitalAllocation'+kind+'Node':'ConstrainedCapitalAllocation'+kind+'Node'
    for kind in ('Plan','Profile','Construct','Diagnose','Export')}


def _binding_source(path,expected):
    data=path.read_bytes()
    if _binding_hashlib.sha256(data).hexdigest()!=expected:
        raise ValueError('A frozen constrained task template changed: '+str(path))
    return data.decode('utf-8')


def transformed_adapter_ast():
    """Exact whole-template identity/catalog substitution; no gate rewrite."""
    tree=_binding_ast.parse(_binding_source(TEMPLATE_PATH,TEMPLATE_SHA256))
    counts={key:0 for key in _LITERAL_BINDINGS};counts.update(catalog_import=0,class_names=0,node_references=0)
    class Bind(_binding_ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value) is str and node.value in _LITERAL_BINDINGS:
                counts[node.value]+=1;node.value=_LITERAL_BINDINGS[node.value]
            return node
        def visit_ClassDef(self,node):
            if node.name in _NODE_BINDINGS:counts['class_names']+=1;node.name=_NODE_BINDINGS[node.name]
            return self.generic_visit(node)
        def visit_Name(self,node):
            if node.id in _NODE_BINDINGS:counts['node_references']+=1;node.id=_NODE_BINDINGS[node.id]
            return node
        def visit_ImportFrom(self,node):
            if node.module=='workbook.capital_allocation_scaled.catalog' and node.level==2:
                counts['catalog_import']+=1;node.module='workbook.capital_allocation_scaled.constrained_catalog'
            return node
    tree=Bind().visit(tree)
    expected={key:(4 if key=='30-D01' else 1) for key in _LITERAL_BINDINGS}
    expected.update(catalog_import=1,class_names=5,node_references=3)
    if counts!=expected:raise ValueError('Unexpected adapter identity/import substitution coverage: '+repr(counts))
    return _binding_ast.fix_missing_locations(tree),counts


# This exec writes only this NEW module's namespace. Source line positions stay
# on the frozen template so its existing ordinary-method AST guards still work.
_adapter_tree,ADAPTER_BINDING_COUNTS=transformed_adapter_ast()
exec(compile(_adapter_tree,str(TEMPLATE_PATH),'exec'),globals())
_template_setting=setting


def setting(runtime_profile=PROFILE):
    _binding_source(TEMPLATE_PATH,TEMPLATE_SHA256)
    _binding_source(RECOVERY_TEMPLATE_PATH,RECOVERY_TEMPLATE_SHA256)
    value=_template_setting(runtime_profile)
    value['constrained_template_binding']={
        'adapter_template':reference(TEMPLATE_PATH),
        'recovery_template':reference(RECOVERY_TEMPLATE_PATH),
        'identity_only_ast_substitution':True,
        'ordinary_gates_unchanged':True}
    return value


def transformed_recovery_ast():
    """Clone only the host node; keep the public compiler/math/witness intact."""
    tree=_binding_ast.parse(_binding_source(RECOVERY_TEMPLATE_PATH,RECOVERY_TEMPLATE_SHA256))
    selected=[node for node in tree.body if isinstance(node,_binding_ast.ClassDef)
              and node.name=='ScaledCapitalAllocationRecoveryNode']
    if len(selected)!=1:raise ValueError('Exactly one frozen recovery class is required')
    selected=_binding_copy(selected[0]);selected.name='ConstrainedCapitalAllocationRecoveryNode'
    counts={'admission_import':0,'session_key':0}
    class Bind(_binding_ast.NodeTransformer):
        def visit_ImportFrom(self,node):
            if node.module=='pipelines.scaled_capital_admission' and node.level==3:
                counts['admission_import']+=1;node.module='pipelines.constrained_capital_admission'
            return node
        def visit_Constant(self,node):
            if node.value=='_scaled_admission_session':
                counts['session_key']+=1;node.value='_constrained_admission_session'
            return node
    selected=Bind().visit(selected)
    if counts!={'admission_import':1,'session_key':1}:
        raise ValueError('Unexpected recovery host-admission substitution coverage')
    return _binding_ast.fix_missing_locations(_binding_ast.Module(body=[selected],type_ignores=[])),counts


# Relative imports in the cloned host node use its original package. Its class
# is exported from this NEW adapter, while all generic helpers remain exactly
# the old frozen implementations. No original module dictionary is mutated.
_recovery_module=public_recovery()
_recovery_namespace=dict(vars(_recovery_module))
_recovery_namespace['__name__']=__name__
_recovery_tree,RECOVERY_BINDING_COUNTS=transformed_recovery_ast()
exec(compile(_recovery_tree,str(RECOVERY_TEMPLATE_PATH),'exec'),_recovery_namespace)
ConstrainedCapitalAllocationRecoveryNode=_recovery_namespace['ConstrainedCapitalAllocationRecoveryNode']
