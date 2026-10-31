"""Complete N360 task views with the frozen mutation and masking semantics.

Only namespace identities change. All financial targets, zeroes, primary fault
definitions, provisional-plan controls and brief instructions are preserved.
"""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

UPSTREAM = _Path(__file__).resolve().parents[1]/'linear_capital_portfolio/task_views.py'
UPSTREAM_SHA256 = 'afe7041fde69ae914367befb21dc777d333ddb7c771a1913a3b81fc79342692f'
_KINDS = {
    'linear_capital_portfolio_native_excel_bindings': ('linear_capital_scaled_native_excel_bindings', 1),
    'planned_unverified_linear_capital_task_view': ('planned_unverified_linear_capital_scaled_task_view', 2),
    'materialized_unverified_linear_capital_task_view': ('materialized_unverified_linear_capital_scaled_task_view', 1),
}


def adapted_ast():
    raw = UPSTREAM.read_bytes()
    if UPSTREAM != UPSTREAM.resolve() or _hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('The frozen complete task-view implementation changed')
    tree = _ast.parse(raw, filename=str(UPSTREAM)); counts = dict.fromkeys(_KINDS, 0)
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Constant) and type(node.value) is str and node.value in _KINDS:
            before = node.value; node.value = _KINDS[before][0]; counts[before] += 1
    if counts != {key:value[1] for key,value in _KINDS.items()}:
        raise ValueError('The exact N360 task-view identities changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(), __file__, 'exec'), globals())
_base_recipe = _recipe


def _recipe():
    """Bind the original implementations as well as their versioned adapters."""
    from ..linear_capital_portfolio import formula_identity as original_identity
    rows = _base_recipe()
    for path in (UPSTREAM, excel.UPSTREAM, original_identity.__file__):
        row = _reference(path)
        if not any(item['path'] == row['path'] for item in rows): rows.append(row)
    return rows
