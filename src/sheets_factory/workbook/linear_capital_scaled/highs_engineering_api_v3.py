"""API-v3: retain API-v2 math and capture bounded diagnostic export warnings."""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

from . import highs_engineering_api_v2 as _api_v2

API_VERSION = 3
API_V2_SHA256 = '3301fa3e32542c60a893709ced8a339fcbb2ae00e56a0e0095cd417380a3594b'


def api_v2_path(): return _Path(_api_v2.__file__)
def upstream_path(): return _api_v2.upstream_path()


def adapted_ast():
    path=api_v2_path()
    if path!=path.resolve() or _hashlib.sha256(path.read_bytes()).hexdigest()!=API_V2_SHA256:
        raise ValueError('The frozen API-v2 engineering wrapper changed')
    tree=_api_v2.adapted_ast();counts={'export':0,'result':0}
    target=_ast.parse('configured(native.writeModel(str(model_path)))').body[0]
    for node in tree.body:
        if not isinstance(node,_ast.FunctionDef) or node.name!='solve_highs':continue
        for index,item in enumerate(node.body):
            if _ast.dump(item)==_ast.dump(target):
                node.body[index:index+1]=_ast.parse("""model_export_status = native.writeModel(str(model_path))
require(model_export_status in (hs.HighsStatus.kOk, hs.HighsStatus.kWarning), 'The native diagnostic model export returned ' + str(model_export_status))
require(model_path.is_file() and model_path.stat().st_size > 0, 'The native diagnostic model export is missing or empty; returned ' + str(model_export_status))""").body
                counts['export']+=1;break
        for item in _ast.walk(node):
            if isinstance(item,_ast.Dict) and any(isinstance(key,_ast.Constant) and key.value=='native_run_status' for key in item.keys):
                for key,expression in [('native_model_export_status','str(model_export_status)'),
                    ('native_model_export_bytes','model_path.stat().st_size')]:
                    item.keys.append(_ast.Constant(key));item.values.append(_ast.parse(expression,mode='eval').body)
                counts['result']+=1
    if counts!={'export':1,'result':1}:raise ValueError('The exact diagnostic export API-v3 substitutions changed')
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(),__file__,'exec'),globals())
