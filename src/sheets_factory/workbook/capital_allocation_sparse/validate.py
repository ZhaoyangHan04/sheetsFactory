"""New-namespace binding of the unchanged independent workbook audit.

All financial expected paths still come from the forward journal. Arithmetic
support is evaluated with Python integers, not Excel or stored formula caches.
An unrecalculated workbook cannot pass the actual-value audit.
"""
from __future__ import annotations

import ast as _dimension_ast
import hashlib as _dimension_hashlib
from pathlib import Path as _DimensionPath

DIMENSION_TEMPLATE_PATH = _DimensionPath(__file__).resolve().parent.parent / 'capital_allocation_scaled/validate.py'
DIMENSION_TEMPLATE_SHA256 = '5c43153d4943f8898dedaf7057c8bd184c31347bbba3ca31a6e15f040ad49712'


def _dimension_source():
    data = DIMENSION_TEMPLATE_PATH.read_bytes()
    if _dimension_hashlib.sha256(data).hexdigest() != DIMENSION_TEMPLATE_SHA256:
        raise ValueError('The frozen dynamic financial audit template changed')
    return data.decode('utf-8')


def dimension_template_ast():
    """Return the entire original AST; no financial or type check changes."""
    return _dimension_ast.parse(_dimension_source())


exec(compile(dimension_template_ast(), str(DIMENSION_TEMPLATE_PATH), 'exec'), globals())
_dimension_original_expected = expected_cells
_dimension_original_audit = audit_capital_allocation_workbook


def dimension_template_binding():
    _dimension_source()
    path = DIMENSION_TEMPLATE_PATH
    data = path.read_bytes()
    return {'template': {'path': str(path), 'sha256': _dimension_hashlib.sha256(data).hexdigest(), 'bytes': len(data)},
            'new_namespace': __package__, 'financial_AST_changes': 0,
            'original_module_globals_changed': False}


def expected_cells(spec, plan, ledger, bindings):
    """Require all financial paths and exact unprotected arithmetic support."""
    dimension_template_binding()
    return _dimension_original_expected(spec, plan, ledger, bindings)


def audit_capital_allocation_workbook(path, spec, plan, ledger, bindings):
    """Use actual workbook caches; no synthetic cache or source qualification."""
    dimension_template_binding()
    return _dimension_original_audit(path, spec, plan, ledger, bindings)
