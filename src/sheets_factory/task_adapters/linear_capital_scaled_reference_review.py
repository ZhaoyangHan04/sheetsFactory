"""Isolated ordinary N360 nodes with current supported reference assessments."""
from __future__ import annotations
import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

from . import linear_capital_scaled as _source

UPSTREAM_SHA256 = '05102d8b97f50f3cd830e9c7d420e2c421bc2f69d54d9f01b1e55a97a28a43cc'
_SETTING = 'linear_capital_scaled_reference_review'


def adapted_ast():
    if _hashlib.sha256(_Path(_source.__file__).read_bytes()).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('The frozen N360 ordinary nodes changed')
    tree = _source.adapted_ast(); counts = {}
    def mark(key): counts[key] = counts.get(key, 0) + 1
    class Adapt(_ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.level == 2 and node.module == 'pipelines.linear_capital_scaled_quality':
                node.module = 'pipelines.linear_capital_scaled_reference_review'; mark('pipeline')
            elif node.level == 2 and node.module == 'workbook':
                if [(n.name,n.asname) for n in node.names] != [('linear_capital_scaled_public_recovery','recovery')]:
                    raise ValueError('The original public recovery import changed')
                mark('remove_public_solver'); return None
            return node
        def visit_Assign(self, node):
            names = [_ast.unparse(n) for n in node.targets]
            if names == ['SETTING']:
                if _ast.unparse(node.value) != 'recovery.SETTING': raise ValueError('The original setting changed')
                node.value = _ast.Constant(_SETTING); mark('setting')
            return self.generic_visit(node)
        def visit_Constant(self, node):
            names = {'complete_native_linear_capital_scaled_normal_quality_v2':'complete_native_linear_capital_scaled_reference_review_v1',
                'config/task_adapters/linear_capital_scaled_nodes.yaml':'config/task_adapters/linear_capital_scaled_reference_review_nodes.yaml'}
            if type(node.value) is str and node.value in names:
                before=node.value; node.value=names[before]; mark(before)
            return node
        def visit_FunctionDef(self, node):
            if node.name == 'setting':
                node.body = _ast.parse("""from ..pipelines import entity_group_contract
return {'version':2,'enabled':True,'adapter':ADAPTER_ID,'implementation':reference(__file__),
    'node_registry':reference(REGISTRY),'runtime_profile':reference(runtime_profile),
    'provider_registry':reference(provider_registry),
    'reference_evidence_policy':'reference_review','independent_public_recovery':False,
    'large_native_probe':reference(entity_group_contract.__file__)}""").body
                mark('setting_function'); return node
            if node.name == 'valid_linear_capital_recovery_witness':
                node.body = _ast.parse("raise ValueError('Reference review never accepts a public-solving witness')").body
                mark('no_witness'); return node
            return self.generic_visit(node)
        def visit_ClassDef(self, node):
            node = self.generic_visit(node)
            if node.name == 'LinearDiagnoseNode':
                method = next(n for n in node.body if isinstance(n,_ast.FunctionDef) and n.name=='execute')
                method.body.insert(-1, _ast.parse("require(validate_reference_policy_selection(ctx.config)=='reference_review', 'The normal reference-review policy changed')").body[0])
                mark('diagnose_policy')
            if node.name == 'LinearExportNode':
                method = next(n for n in node.body if isinstance(n,_ast.FunctionDef) and n.name=='execute')
                changed=0
                for i, item in enumerate(method.body):
                    if isinstance(item,_ast.Expr) and _ast.unparse(item).startswith('require(valid_linear_capital_recovery_witness('):
                        method.body[i] = _ast.parse('validate_reference_export(ctx)').body[0]; changed+=1
                if changed!=1: raise ValueError('The exact original export witness guard changed')
                mark('export_review')
            return node
    tree = Adapt().visit(tree)
    expected = {'pipeline':1,'remove_public_solver':1,'setting':1,'setting_function':1,'no_witness':1,
        'diagnose_policy':1,'export_review':1,'complete_native_linear_capital_scaled_normal_quality_v2':1,
        'config/task_adapters/linear_capital_scaled_nodes.yaml':1}
    if counts != expected: raise ValueError('The exact normal reference-review substitutions changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(), str(_source.UPSTREAM), 'exec'), globals())


def validate_reference_export(ctx):
    """Never substitute a recovery flag or an earlier revision's review."""
    require(validate_reference_policy_selection(ctx.config) == 'reference_review', 'The reference policy changed')
    binding = reference_revision_binding(ctx); report = ctx.data.get('diagnosis', {})
    receipt = report.get('reference_review', {})
    supported = reference_review_assessments(report, binding)
    require(report.get('releasable') is True
        and set(report.get('enabled_check_ids', [])) == {f'Q{i:02d}' for i in range(1,13)}
        and report.get('reference_evidence_policy') == 'reference_review'
        and report.get('reference_binding') == binding
        and receipt.get('passed') is True and receipt.get('binding') == binding
        and supported['passed'] is True
        and report.get('mandatory_gates',{}).get('reference_review',{}).get('passed') is True,
        'All twelve current quality gates and supported bound Q01–Q04 reference assessments must pass before export')
    return supported
