#!/usr/bin/env python3
"""Isolated third business-view development entry; no predecessor is edited.

Only the view import, version identities and recipe inventory differ from the
frozen original. The seven calculation passes, controls and pending gates keep
the exact predecessor AST. An explicit run remains necessary for execution.
"""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parents[1]
_TEMPLATE = _ROOT / 'scripts/prepare_heterogeneous_view_development.py'
_TEMPLATE_SHA256 = '2dde40a6b1f99e3b140a01e0a99b18c72213069d271da352498a3742d8ab2ef3'


def _recipe_extra_paths():
    return [_TEMPLATE,
        _ROOT / 'scripts/prepare_heterogeneous_view_v2_development.py',
        _ROOT / 'src/sheets_factory/task_adapters/heterogeneous_financial_view.py',
        _ROOT / 'src/sheets_factory/task_adapters/heterogeneous_financial_view_v2.py',
        _ROOT / 'config/task_adapters/heterogeneous_financial_view_v1.json',
        _ROOT / 'config/task_adapters/heterogeneous_financial_view_v2.json']


def adapted_ast():
    raw = _TEMPLATE.read_bytes()
    if _hashlib.sha256(raw).hexdigest() != _TEMPLATE_SHA256:
        raise ValueError('The complete predecessor development builder changed')
    tree = _ast.parse(raw, filename=str(_TEMPLATE))
    counts = {'adapter': 0, 'prepared_kind': 0, 'snapshot_kind': 0, 'task_id': 0, 'recipe': 0}
    for node in tree.body:
        if isinstance(node, _ast.ImportFrom) and node.module == 'sheets_factory.task_adapters':
            if [(item.name, item.asname) for item in node.names] != [('heterogeneous_financial_view', 'view')]:
                raise ValueError('The declared business adapter import changed')
            node.names = [_ast.alias(name='heterogeneous_financial_view_v3', asname='view')]
            counts['adapter'] += 1
        elif isinstance(node, _ast.FunctionDef) and node.name == 'recipes':
            returns = [i for i, item in enumerate(node.body) if isinstance(item, _ast.Return)]
            if len(returns) != 1:
                raise ValueError('The complete recipe inventory function changed')
            node.body.insert(returns[0], _ast.parse('paths.extend(_recipe_extra_paths())').body[0])
            counts['recipe'] += 1
    replacements = {
        'prepared_heterogeneous_business_view_development':
            ('prepared_heterogeneous_business_view_v3_development', 'prepared_kind'),
        'prequality_heterogeneous_business_view_development':
            ('prequality_heterogeneous_business_view_v3_development', 'snapshot_kind'),
        'fm-heterogeneous-H01-': ('fm-heterogeneous-v3-H01-', 'task_id')}

    class Identities(_ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, str) and node.value in replacements:
                replacement, key = replacements[node.value]
                counts[key] += 1
                node.value = replacement
            return node

    tree = Identities().visit(tree)
    if counts != {'adapter': 1, 'prepared_kind': 2, 'snapshot_kind': 1, 'task_id': 1, 'recipe': 1}:
        raise ValueError('An explicit version-three development substitution changed: ' + str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(), __file__, 'exec'), globals())
