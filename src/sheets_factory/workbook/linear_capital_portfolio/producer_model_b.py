"""Private producer CP-SAT adapter; only its declared worker ceiling changes.

The original B compiler and financial implementation remain frozen. In a job
bundle the exact original text is the sibling frozen_model_b.py, not a host
path or extra mount. No solver is imported or executed by this module.
"""
import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

UPSTREAM_SHA256 = '972e640060ba14d545e20907014a892be76c83675c9d00a354ee7098f693e6c4'


def upstream_path():
    folder = _Path(__file__).resolve().parent
    bundled = folder/'frozen_model_b.py'
    return bundled if bundled.is_file() else folder/'model_b.py'


def adapted_ast():
    path = upstream_path(); raw = path.read_bytes()
    if _hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('The frozen independent CP-SAT model adapter changed')
    tree = _ast.parse(raw, filename=str(path)); changes = 0
    old = _ast.parse("require(type(threads) is int and 1<=threads<=2, 'The reference uses at most the declared two CPU workers')").body[0]
    new = _ast.parse("require(type(threads) is int and 1<=threads<=16, 'The private producer uses at most the declared sixteen CPU workers')").body[0]
    for function in tree.body:
        if isinstance(function, _ast.FunctionDef) and function.name == 'solve_cp_sat':
            for index, node in enumerate(function.body):
                if _ast.dump(node) == _ast.dump(old):
                    function.body[index] = new; changes += 1
    if changes != 1:
        raise ValueError('The exact private CP-SAT worker-ceiling substitution changed')
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(), __file__, 'exec'), globals())
