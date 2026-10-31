"""N360 ordinary normal nodes, with unchanged financial and QA gate semantics."""
from __future__ import annotations
import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

UPSTREAM=_Path(__file__).with_name('linear_capital_portfolio.py')
UPSTREAM_SHA256='ae1810d4ff04977e5fe25d6922e153f4e109aee1323c8fcf068c5b2677b44283'


def adapted_ast():
    raw=UPSTREAM.read_bytes()
    if UPSTREAM!=UPSTREAM.resolve() or _hashlib.sha256(raw).hexdigest()!=UPSTREAM_SHA256:
        raise ValueError('The frozen original normal node implementation changed')
    tree=_ast.parse(raw,filename=str(UPSTREAM));counts={}
    strings={'complete_native_linear_capital_normal_quality_v1':'complete_native_linear_capital_scaled_normal_quality_v2',
        'config/task_adapters/linear_capital_portfolio_nodes.yaml':'config/task_adapters/linear_capital_scaled_nodes.yaml',
        '_linear_admission':'_linear_scaled_admission'}
    def mark(name):counts[name]=counts.get(name,0)+1
    class Adapt(_ast.NodeTransformer):
        def visit_ImportFrom(self,node):
            changes={'pipelines.linear_capital_quality':'pipelines.linear_capital_scaled_quality',
                'workbook.linear_capital_portfolio':'workbook.linear_capital_scaled'}
            if node.level==2 and node.module in changes:
                before=node.module;node.module=changes[before];mark('import:'+before)
            elif node.level==2 and node.module=='workbook':
                if [(x.name,x.asname) for x in node.names]!=[('linear_capital_public_recovery','recovery')]:
                    raise ValueError('The original recovery import changed')
                node.names=[_ast.alias(name='linear_capital_scaled_public_recovery',asname='recovery')];mark('recovery_import')
            return node
        def visit_Constant(self,node):
            if type(node.value) is str and node.value in strings:
                before=node.value;node.value=strings[before];mark('string:'+before)
            return node
        def visit_Compare(self,node):
            if _ast.unparse(node)=="value['version'] == 1":
                node.comparators[0]=_ast.Constant(2);mark('setting_version_guard')
            return self.generic_visit(node)
        def visit_Dict(self,node):
            keys={k.value:i for i,k in enumerate(node.keys) if isinstance(k,_ast.Constant)}
            if {'version','enabled','adapter','implementation','node_registry'}<=keys.keys():
                if node.values[keys['version']].value!=1:raise ValueError('The original setting version changed')
                node.values[keys['version']]=_ast.Constant(2);mark('setting_version')
            return self.generic_visit(node)
        def visit_Attribute(self,node):
            if _ast.unparse(node)=='recovery.valid_linear_capital_recovery_witness':
                node.attr='valid_linear_capital_scaled_recovery_witness';mark('strict_scaled_witness')
            return self.generic_visit(node)
    tree=Adapt().visit(tree)
    expected={**{'string:'+key:1 for key in strings},'string:_linear_admission':4,
        'import:pipelines.linear_capital_quality':1,'import:workbook.linear_capital_portfolio':1,
        'recovery_import':1,'setting_version_guard':1,'setting_version':1,'strict_scaled_witness':1}
    if counts!=expected:raise ValueError('The exact normal N360 route substitutions changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(),str(UPSTREAM),'exec'),globals())
_validate_setting=validate_setting


def validate_setting(value):
    adapted_ast()
    return _validate_setting(value)
