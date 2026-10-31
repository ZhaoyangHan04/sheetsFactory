"""HiGHS API-v2 compatibility: one status-returning objective-sense call.

All coefficients, scaling, parameters, exact audits and nonadmission semantics
are the frozen original implementation. Only the Python API call changes.
"""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

API_VERSION = 2
UPSTREAM_SHA256 = 'd9c2c42e01475232b024c09a3d353d5e7ad14bcf679be17398ce24b5fd78b2cd'


def upstream_path():
    local = _Path(__file__).with_name('frozen_highs_engineering.py')
    return local if local.is_file() else _Path(__file__).with_name('highs_engineering.py')


def adapted_ast():
    path = upstream_path(); raw = path.read_bytes()
    if path != path.resolve() or _hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('The frozen pre-API-v2 HiGHS engineering implementation changed')
    tree = _ast.parse(raw, filename=str(path)); count = 0
    target = _ast.parse('native.setMaximize()', mode='eval').body
    class API(_ast.NodeTransformer):
        def visit_Call(self, node):
            nonlocal count
            if _ast.dump(node) == _ast.dump(target):
                count += 1
                return _ast.parse('native.changeObjectiveSense(hs.ObjSense.kMaximize)', mode='eval').body
            return self.generic_visit(node)
    tree = API().visit(tree)
    if count != 1: raise ValueError('The exact objective-sense API-v2 substitution changed')
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(), __file__, 'exec'), globals())
