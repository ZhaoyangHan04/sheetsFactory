"""Isolated N360 opaque source/view admissions and the ordinary quality factory.

The frozen original bytecode retains all complete source, value, resource and
five-control checks. Only explicit namespace/identity/version bindings change.
No source validation or service starts at import.
"""
from __future__ import annotations
import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

UPSTREAM=_Path(__file__).with_name('linear_capital_quality.py')
UPSTREAM_SHA256='995e50d28aec160bd4ebb0a3fcfe1356acc945c17026c8694951a74a0e9a9775'
SCALED_TASK_VALIDATOR_SHA256='64af9d3e3b7ba7cfbd460cdad47d30dd9641cdb81e74c298137232d8a3611542'


def adapted_ast():
    raw=UPSTREAM.read_bytes()
    if UPSTREAM!=UPSTREAM.resolve() or _hashlib.sha256(raw).hexdigest()!=UPSTREAM_SHA256:
        raise ValueError('The frozen original normal source/view quality implementation changed')
    tree=_ast.parse(raw,filename=str(UPSTREAM));counts={}
    strings={
        'config/task_adapters/linear_capital_source_providers_v1.json':'config/task_adapters/linear_capital_scaled_source_providers_v2.json',
        'scripts/validate_linear_capital_task_view.py':'scripts/validate_linear_capital_scaled_task_view.py',
        '24decf5b019f1183ef6c7538c4947e9757cd160d1f11c54d9e3fce36582ae974':SCALED_TASK_VALIDATOR_SHA256,
        'linear_capital_source_provider_registry':'linear_capital_scaled_source_provider_registry',
        'linear_capital_task_view_actual_validation':'linear_capital_scaled_task_view_actual_validation',
        'prepared_linear_capital_task_view_actual_validation':'prepared_linear_capital_scaled_task_view_actual_validation',
        'materialized_unverified_linear_capital_task_view':'materialized_unverified_linear_capital_scaled_task_view',
        'admitted_complete_native_linear_capital_task_view':'admitted_complete_native_linear_capital_scaled_task_view',
        'audited_native_linear_capital_source_with_actual_task_views':'audited_native_linear_capital_scaled_source_with_actual_task_views',
        '_linear_admission':'_linear_scaled_admission',
        'linear_view_admissions':'linear_scaled_view_admissions',
        'linear_capital_portfolio':'linear_capital_scaled',
        '_linear_quality_provider_':'_linear_scaled_quality_provider_',
        '_linear_quality_frozen_actual_validator_':'_linear_scaled_quality_frozen_actual_validator_',
    }
    versions={"preparation['version'] == 1","terminal['version'] == 1",
        "registry['version'] == 1","result['version'] == 1","frozen['version'] == 1"}
    def mark(name):counts[name]=counts.get(name,0)+1
    class Adapt(_ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value) is str and node.value in strings:
                before=node.value;node.value=strings[before];mark('string:'+before)
            return node
        def visit_ImportFrom(self,node):
            if node.module=='workbook.linear_capital_portfolio' and node.level==2:
                node.module='workbook.linear_capital_scaled';mark('view_import')
            elif node.module=='task_adapters' and node.level==2:
                if [(x.name,x.asname) for x in node.names]!=[('linear_capital_portfolio','adapter')]:
                    raise ValueError('The original quality adapter import changed')
                node.names=[_ast.alias(name='linear_capital_scaled',asname='adapter')];mark('adapter_import')
            return node
        def visit_Compare(self,node):
            text=_ast.unparse(node)
            if text in versions:
                node.comparators[0]=_ast.Constant(2);mark('version:'+text)
            return self.generic_visit(node)
        def visit_Assign(self,node):
            if [_ast.unparse(x) for x in node.targets]==['kinds']:
                expected={
                    'prepared_private_linear_capital_integer_solver':('private_linear_capital_integer_solver_execution',2),
                    'prepared_private_linear_capital_producer16_solver':('private_linear_capital_producer16_solver_execution',16)}
                if _ast.literal_eval(node.value)!=expected:raise ValueError('The original container artifact protocol changed')
                node.value=_ast.parse(repr({'prepared_private_linear_capital_scaled_producer16_solver':
                    ('private_linear_capital_scaled_producer16_solver_execution',16)}),mode='eval').body
                mark('solver_identity')
            return self.generic_visit(node)
        def visit_Dict(self,node):
            keys={k.value:i for i,k in enumerate(node.keys) if isinstance(k,_ast.Constant)}
            if {'kind','version','source_manifest','source_provider','source_financial_evidence'}<=keys.keys():
                if node.values[keys['version']].value!=1:raise ValueError('The original opaque proof version changed')
                node.values[keys['version']]=_ast.Constant(2);mark('proof_version')
            return self.generic_visit(node)
    tree=Adapt().visit(tree)
    expected={**{'string:'+key:1 for key in strings},'string:_linear_admission':2,
        'string:linear_capital_portfolio':2,'view_import':2,'adapter_import':1,
        **{'version:'+key:1 for key in versions},'solver_identity':1,'proof_version':1}
    if counts!=expected:raise ValueError('The exact isolated N360 quality substitutions changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(),str(UPSTREAM),'exec'),globals())
