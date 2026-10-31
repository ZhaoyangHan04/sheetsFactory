#!/usr/bin/env python3
"""Freeze one unused N360 development material under its prospective v4 policy.

The existing shared material reservation is retained. Earlier selections and
UNKNOWN results cannot be relaunched under this entry. Actual view schema stays
version two; only this development policy/entry is new.
"""
from __future__ import annotations
import ast as _ast
import hashlib as _hashlib
import importlib.util as _util
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parents[1]
_SCALED = _ROOT/'scripts/prepare_linear_capital_scaled_development.py'
_SHA = '29a575da6dde372a1290af0737c77433ded3515202f8e3f8e8db9f6d3e525329'
if _hashlib.sha256(_SCALED.read_bytes()).hexdigest() != _SHA:
    raise ValueError('The frozen N360 first-development implementation changed')
_spec = _util.spec_from_file_location('_frozen_N360_development_v2',_SCALED)
_old = _util.module_from_spec(_spec); _spec.loader.exec_module(_old)


def _v4_ast():
    tree = _old.adapted_ast(); counts = {'import':0,'name':0,'version_dict':0,'version_guard':0,'kind':0}
    class Adapt(_ast.NodeTransformer):
        def visit_ImportFrom(self,node):
            if node.module == 'sheets_factory.evaluation.native_transport_frontier':
                node.module = 'sheets_factory.evaluation.linear_capital_scaled_frontier_v4'; counts['import'] += 1
                for name in node.names:
                    if name.name == 'POLICY_V3': name.name = 'POLICY_V4'
            return node
        def visit_Name(self,node):
            if node.id == 'POLICY_V3': node.id = 'POLICY_V4'; counts['name'] += 1
            return node
        def visit_Dict(self,node):
            for key,value in zip(node.keys,node.values):
                if isinstance(key,_ast.Constant) and key.value == 'tool_time_policy_version':
                    if not isinstance(value,_ast.Constant) or value.value != 3: raise ValueError('The frozen prospective policy version changed')
                    value.value=4; counts['version_dict'] += 1
            return self.generic_visit(node)
        def visit_Compare(self,node):
            if _ast.unparse(node) == "frozen['tool_time_policy_version'] == 3":
                node.comparators[0]=_ast.Constant(4); counts['version_guard'] += 1
            return self.generic_visit(node)
        def visit_Constant(self,node):
            if node.value == 'prequality_linear_capital_scaled_native_development':
                node.value = 'prequality_linear_capital_scaled_native_development_v4'; counts['kind'] += 1
            return node
    tree=Adapt().visit(tree)
    if counts != {'import':2,'name':3,'version_dict':1,'version_guard':1,'kind':1}:
        raise ValueError('The narrow prospective N360 development-v4 adaptation changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


def _entry_ast():
    tree = _ast.parse(_SCALED.read_bytes()); counts={'exec':0,'import':0}
    tree.body=[n for n in tree.body if not (isinstance(n,_ast.FunctionDef) and n.name=='adapted_ast')
        and not (isinstance(n,_ast.If) and _ast.unparse(n.test)=="__name__ == '__main__'")]
    class Adapt(_ast.NodeTransformer):
        def visit_Call(self,node):
            if isinstance(node.func,_ast.Name) and node.func.id=='adapted_ast':
                node.func.id='_v4_ast'; counts['exec'] += 1
            return self.generic_visit(node)
        def visit_ImportFrom(self,node):
            if node.module=='sheets_factory.evaluation.native_transport_frontier':
                node.module='sheets_factory.evaluation.linear_capital_scaled_frontier_v4'; counts['import'] += 1
            return node
        def visit_Import(self,node):
            if node.names[0].name=='sheets_factory.evaluation' and node.names[0].asname is None: return node
            return node
    tree=Adapt().visit(tree)
    # The recipes function imports the provider module using a from-import.
    for node in _ast.walk(tree):
        if isinstance(node,_ast.ImportFrom) and node.module=='sheets_factory.evaluation':
            for alias in node.names:
                if alias.name=='native_transport_frontier': alias.name='linear_capital_scaled_frontier_v4';alias.asname='native_transport_frontier';counts['import'] += 1
    if counts!={'exec':2,'import':2}:raise ValueError('The frozen development entry boundaries changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(_entry_ast(), __file__, 'exec'), globals())
_recipes_v4_base=recipes
_checked_material_v4_base=checked_material
PENDING=['supported_Q01_Q04_reference_review' if item=='public_only_recovery' else item for item in PENDING]
_ADMITTED_MATERIALS={}


def checked_material(source_manifest,view_manifest,validation_manifest):
    """One genuine opaque cold source/view check, then unchanged byte checks."""
    from sheets_factory.pipelines import linear_capital_scaled_reference_review as admission
    from types import FunctionType,SimpleNamespace
    refs=tuple(checked(value) for value in (source_manifest,view_manifest,validation_manifest))
    key=tuple((r['path'],r['sha256'],r['bytes']) for r in refs)
    if key not in _ADMITTED_MATERIALS:
        source=admission.LinearSourceAdmission(refs[0],provider_id='scaled360',provider_registry=admission.DEFAULT_PROVIDERS)
        view=admission.ReferenceViewAdmission(source,refs[2],provider_id='scaled360')
        _ADMITTED_MATERIALS[key]=(source,view)
    source,view=_ADMITTED_MATERIALS[key]
    source_proof=admission.require_source_admission(source);proof=admission.require_view_admission(view)
    require(type(source) is admission.LinearSourceAdmission and type(view) is admission.ReferenceViewAdmission
        and source.provider_id=='scaled360' and proof['source_manifest']==refs[0]
        and proof['view_manifest']==refs[1] and proof['actual_validation_terminal']==refs[2]
        and proof['source_financial_evidence']==source_proof
        and proof['kind']=='admitted_complete_native_linear_capital_scaled_reference_review_view'
        and proof['version']==2,
        'Development v4 requires the genuine original N360 source and complete forty-recipe reference view')
    actual=read(refs[2])
    # The opaque view just ran the entire original actual-call/D/control/typed
    # protocol. The frozen development bytecode repeats all material bindings
    # with that exact completed result, without a second source validation.
    namespace=dict(globals());namespace['validation_driver']=lambda:SimpleNamespace(validate_completed=lambda ref:
        actual if checked(ref)==refs[2] else require(False,'Another terminal was requested'))
    base=_base_checked_material
    copied=FunctionType(base.__code__,namespace,base.__name__,base.__defaults__,base.__closure__)
    copied.__kwdefaults__=base.__kwdefaults__;namespace['_base_checked_material']=copied
    wrapper=_checked_material_v4_base
    checked_wrapper=FunctionType(wrapper.__code__,namespace,wrapper.__name__,wrapper.__defaults__,wrapper.__closure__)
    checked_wrapper.__kwdefaults__=wrapper.__kwdefaults__
    result=checked_wrapper(*refs)
    require(result[6]==actual and result[4]['mode']==proof['mode'],'The admitted task or mode changed')
    admission.require_source_admission(source);admission.require_view_admission(view)
    return result


def recipes():
    from sheets_factory.evaluation import linear_capital_scaled_frontier_v4 as runner
    from sheets_factory.evaluation import native_transport_frontier_v4, clock_resource_frontier_v4, tool_time_clock_bounds_v4
    runner.adapted_ast()
    from sheets_factory.pipelines import linear_capital_scaled_reference_review as admission
    files=[_SCALED, _Path(runner.__file__),_Path(native_transport_frontier_v4.__file__),
        _Path(clock_resource_frontier_v4.__file__),_Path(tool_time_clock_bounds_v4.__file__),
        _Path(admission.__file__),_Path(admission.source.__file__),admission.source.UPSTREAM,
        admission.DEFAULT_PROVIDERS]
    return {**_recipes_v4_base(),**{str(p.resolve()):reference(p)['sha256'] for p in files}}


if __name__=='__main__':raise SystemExit(main())
