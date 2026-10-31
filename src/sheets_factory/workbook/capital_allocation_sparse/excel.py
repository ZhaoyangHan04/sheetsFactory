"""Sparse-dimension binding of the frozen forward Excel implementation.

The complete financial AST is unchanged. Relative schema imports resolve in
this new package; original module globals remain untouched. The exact integer
arithmetic compiler is the same SHA-bound implementation as before. No search,
winner, journal result, or target value is an input to formula generation.
"""
from __future__ import annotations

import ast as _dimension_ast
import hashlib as _dimension_hashlib
from pathlib import Path as _DimensionPath

DIMENSION_TEMPLATE_PATH = _DimensionPath(__file__).resolve().parent.parent / 'capital_allocation_scaled/excel.py'
DIMENSION_TEMPLATE_SHA256 = 'aa03b2315b5225dd73a0b51400148e87f6d467288d0247e136ae2abc84010469'


def _dimension_source():
    data = DIMENSION_TEMPLATE_PATH.read_bytes()
    if _dimension_hashlib.sha256(data).hexdigest() != DIMENSION_TEMPLATE_SHA256:
        raise ValueError('The frozen dynamic financial emitter template changed')
    return data.decode('utf-8')


def dimension_template_ast():
    """Return the entire original AST; no node is rewritten or removed."""
    return _dimension_ast.parse(_dimension_source())


exec(compile(dimension_template_ast(), str(DIMENSION_TEMPLATE_PATH), 'exec'), globals())
_dimension_original_assert_recipe = assert_upstream_recipe
_dimension_original_emit = emit_capital_allocation_workbook


def dimension_template_binding():
    _dimension_source()
    return {'template': _reference(DIMENSION_TEMPLATE_PATH),
            'new_namespace': __package__, 'financial_AST_changes': 0,
            'original_module_globals_changed': False}


def assert_upstream_recipe():
    """Bind both the new namespace and the unchanged source of its full loop."""
    binding = dimension_template_binding()
    return {**_dimension_original_assert_recipe(), 'sparse_dimension_template': binding}


def emit_capital_allocation_workbook(book, spec, plan=None):
    """Emit only formulas from raw public primitives and a supplied plan."""
    dimension_template_binding()
    return _dimension_original_emit(book, spec, plan)
