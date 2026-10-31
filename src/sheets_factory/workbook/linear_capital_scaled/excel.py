"""Versioned N360 rendering with the original financial formulas unchanged.

The frozen emitter executes in this module's separate namespace. Its relative
spec import resolves to the N360 contract. No original module is patched.
Emission creates an uncached workbook; it certifies no finance or task quality.
"""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

UPSTREAM = _Path(__file__).resolve().parents[1]/'linear_capital_portfolio/excel.py'
UPSTREAM_SHA256 = '3a0ec72daf5ac7c307bcea359c0a100fbaf1e36be890e2536260e50e9dac689d'
BINDING_KIND = 'linear_capital_scaled_native_excel_bindings'


def adapted_ast():
    raw = UPSTREAM.read_bytes()
    if UPSTREAM != UPSTREAM.resolve() or _hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('The frozen native financial emitter changed')
    tree = _ast.parse(raw, filename=str(UPSTREAM))
    counts = {'binding_kind': 0, 'default_cap': 0}
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Constant) and node.value == 'linear_capital_portfolio_native_excel_bindings':
            node.value = BINDING_KIND; counts['binding_kind'] += 1
        if isinstance(node, _ast.FunctionDef) and node.name == 'emit_workbook':
            index = node.args.kwonlyargs.index(next(a for a in node.args.kwonlyargs if a.arg == 'max_formulas'))
            if _ast.dump(node.args.kw_defaults[index]) != _ast.dump(_ast.Constant(1_000_000)):
                raise ValueError('The original complete-emission cap default changed')
            node.args.kw_defaults[index] = _ast.Constant(1_500_000); counts['default_cap'] += 1
    if counts != {'binding_kind': 1, 'default_cap': 1}:
        raise ValueError('The exact N360 emitter substitutions changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(), __file__, 'exec'), globals())
