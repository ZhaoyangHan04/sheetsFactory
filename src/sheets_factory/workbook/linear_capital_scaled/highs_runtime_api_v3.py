"""Thin isolated API-v3 identity/portable closure over the frozen API-v2 runtime."""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

V2_PATH=_Path(__file__).with_name('highs_runtime_api_v2.py')
V2_SHA256='b293edfe8f4ffdddfe5f804c1f40563879e68955d92bfb2a412ae42be32124ea'


def _v2_source():
    raw=V2_PATH.read_bytes()
    if V2_PATH!=V2_PATH.resolve() or _hashlib.sha256(raw).hexdigest()!=V2_SHA256:
        raise ValueError('The frozen API-v2 HiGHS runtime changed')
    return raw


exec(compile(_v2_source(),__file__,'exec'),globals())
_v2_adapted_ast=adapted_ast
from . import highs_engineering_api_v3 as engineering

PREPARATION_KIND='prepared_private_linear_capital_scaled_highs2_engineering_api_v3'
TERMINAL_KIND='private_linear_capital_scaled_highs2_engineering_execution_api_v3'
SOURCE_NAMES=SOURCE_NAMES|{'highs_engineering_api_v2.py'}


def _source_files():
    model_a.adapted_ast();engineering.adapted_ast()
    files={name+'.py':path for name,path in model_a.source_files().items()}
    files.update({'highs_engineering.py':_Path(engineering.__file__),
        'highs_engineering_api_v2.py':engineering.api_v2_path(),
        'frozen_highs_engineering.py':engineering.upstream_path()})
    engineering.require(set(files)==SOURCE_NAMES,'The complete portable API-v3 matrix-only closure changed')
    return files


def adapted_ast():
    _v2_source();tree=_v2_adapted_ast();counts={'versions':0,'gate':0,'names':0}
    class Identity(_ast.NodeTransformer):
        def visit_Constant(self,node):
            if node.value in ('sf-scaled-highs2-engineering-api-v2-','/sf-scaled-highs2-engineering-api-v2-'):
                node.value=node.value.replace('-api-v2-','-api-v3-');counts['names']+=1
            return node
    tree=Identity().visit(tree)
    for node in tree.body:
        if not isinstance(node,_ast.FunctionDef):continue
        if node.name in ('prepare','execute_prepared'):
            marker='prepared_at' if node.name=='prepare' else 'requested_resources'
            for item in _ast.walk(node):
                if isinstance(item,_ast.Dict) and any(isinstance(key,_ast.Constant) and key.value==marker for key in item.keys):
                    for key,value in zip(item.keys,item.values):
                        if isinstance(key,_ast.Constant) and key.value=='version':
                            if not isinstance(value,_ast.Constant) or value.value!=2:raise ValueError('The API-v2 runtime envelope changed')
                            value.value=3;counts['versions']+=1
        elif node.name=='validate_prepared':
            for item in _ast.walk(node):
                if isinstance(item,_ast.Compare) and _ast.unparse(item)=="frozen.get('version') == 2":
                    item.comparators[0]=_ast.Constant(3);counts['gate']+=1
    if counts!={'versions':2,'gate':1,'names':2}:raise ValueError('The exact API-v3 runtime identities changed: '+str(counts))
    return _ast.fix_missing_locations(tree)
