"""Isolated API-v2 identity and portable closure over the frozen HiGHS runtime."""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

ADAPTER_UPSTREAM = _Path(__file__).with_name('highs_runtime.py')
ADAPTER_UPSTREAM_SHA256 = 'b37ca2f1ad1a9eb98fc2bb527de9c67b8a3b35a2c331e6e1b7a2bf16881de0b3'


def _wrapper_ast():
    raw = ADAPTER_UPSTREAM.read_bytes()
    if ADAPTER_UPSTREAM != ADAPTER_UPSTREAM.resolve() or _hashlib.sha256(raw).hexdigest() != ADAPTER_UPSTREAM_SHA256:
        raise ValueError('The frozen pre-API-v2 HiGHS lifecycle changed')
    tree = _ast.parse(raw, filename=str(ADAPTER_UPSTREAM)); counts = {}
    def changed(key): counts[key] = counts.get(key, 0)+1
    identities = {
        'prepared_private_linear_capital_scaled_highs2_engineering':'prepared_private_linear_capital_scaled_highs2_engineering_api_v2',
        'private_linear_capital_scaled_highs2_engineering_execution':'private_linear_capital_scaled_highs2_engineering_execution_api_v2',
        'sf-scaled-highs2-engineering-':'sf-scaled-highs2-engineering-api-v2-',
        '/sf-scaled-highs2-engineering-':'/sf-scaled-highs2-engineering-api-v2-',
    }
    class API(_ast.NodeTransformer):
        def visit_ImportFrom(self,node):
            if node.level == 1 and node.module is None:
                for alias in node.names:
                    if alias.name == 'highs_engineering' and alias.asname == 'engineering':
                        alias.name = 'highs_engineering_api_v2'; changed('engine_import')
            return node
        def visit_Constant(self,node):
            if type(node.value) is str and node.value in identities:
                before=node.value;node.value=identities[before];changed(before)
            return node
        def visit_Assign(self,node):
            if len(node.targets)==1 and isinstance(node.targets[0],_ast.Name) and node.targets[0].id=='SOURCE_NAMES':
                node.value.elts.append(_ast.Constant('frozen_highs_engineering.py'));changed('source_names')
            return self.generic_visit(node)
        def visit_FunctionDef(self,node):
            node=self.generic_visit(node)
            if node.name=='_source_files':
                target=_ast.parse("files['highs_engineering.py'] = Path(engineering.__file__)").body[0]
                for index,item in enumerate(node.body):
                    if _ast.dump(item)==_ast.dump(target):
                        node.body.insert(index+1,_ast.parse("files['frozen_highs_engineering.py'] = engineering.upstream_path()").body[0]);changed('portable_engine')
                        break
            return node
    tree=API().visit(tree)
    expected={key:1 for key in identities};expected.update(engine_import=1,source_names=1,portable_engine=1)
    if counts!=expected:raise ValueError('The exact API-v2 runtime substitutions changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(_wrapper_ast(), __file__, 'exec'),globals())
_base_adapted_ast = adapted_ast


def adapted_ast():
    _wrapper_ast(); engineering.adapted_ast()
    tree=_base_adapted_ast();counts={'envelopes':0,'version_gate':0}
    for node in tree.body:
        if not isinstance(node,_ast.FunctionDef):continue
        if node.name in ('prepare','execute_prepared'):
            marker='prepared_at' if node.name=='prepare' else 'requested_resources'
            for item in _ast.walk(node):
                if isinstance(item,_ast.Dict) and any(isinstance(key,_ast.Constant) and key.value==marker for key in item.keys):
                    for key,value in zip(item.keys,item.values):
                        if isinstance(key,_ast.Constant) and key.value=='version':
                            if not isinstance(value,_ast.Constant) or value.value!=1:raise ValueError('The runtime version envelope changed')
                            value.value=2;counts['envelopes']+=1
        elif node.name=='validate_prepared':
            for item in _ast.walk(node):
                if isinstance(item,_ast.Compare) and _ast.unparse(item)=="frozen.get('version') == 1":
                    item.comparators[0]=_ast.Constant(2);counts['version_gate']+=1
    if counts!={'envelopes':2,'version_gate':1}:raise ValueError('The exact API-v2 runtime versions changed')
    return _ast.fix_missing_locations(tree)
