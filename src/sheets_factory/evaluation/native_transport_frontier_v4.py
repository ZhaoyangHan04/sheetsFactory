"""Prospective v4 clocks and the unchanged factory stream-retry8 mitigation."""
from __future__ import annotations

import ast as _adapter_ast
import hashlib as _adapter_hashlib
from pathlib import Path as _AdapterPath

_NATIVE_V3_PATH = _AdapterPath(__file__).with_name('native_transport_frontier.py')
_NATIVE_V3_SHA256 = '675edf702a989600d5486159768ede7bbf3d37b749e758a38b1a73ce37368c0d'


def _native_v4_upstream_guard():
    raw = _NATIVE_V3_PATH.read_bytes()
    if _adapter_hashlib.sha256(raw).hexdigest() != _NATIVE_V3_SHA256:
        raise ValueError('The frozen native transport adapter changed')
    return {'path': str(_NATIVE_V3_PATH), 'sha256': _NATIVE_V3_SHA256, 'bytes': len(raw)}


def _native_v4_tree():
    _native_v4_upstream_guard()
    tree = _adapter_ast.parse(_NATIVE_V3_PATH.read_bytes(), filename=str(_NATIVE_V3_PATH))
    counts = {'clock_import': 0, 'old_agent_path': 0, 'new_agent_path': 0}
    class ClockNamespace(_adapter_ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module == 'clock_resource_frontier' and node.level == 1:
                if [(a.name, a.asname) for a in node.names] != [('adapted_ast', '_clock_ast'), ('_v3_provenance', None), ('account_trial_tool_time_v3', None), ('POLICY_V3', None)]:
                    raise ValueError('Unexpected frozen native clock imports')
                counts['clock_import'] += 1; node.module = 'clock_resource_frontier_v4'
                for alias in node.names:
                    alias.name = {'_v3_provenance': '_v4_provenance', 'account_trial_tool_time_v3': 'account_trial_tool_time_v4', 'POLICY_V3': 'POLICY_V4'}.get(alias.name, alias.name)
            return node
        def visit_Constant(self, node):
            if node.value == 'sheets_factory.evaluation.clock_resource_frontier:LocalCodex':
                counts['old_agent_path'] += 1
                return _adapter_ast.copy_location(_adapter_ast.Constant('sheets_factory.evaluation.clock_resource_frontier_v4:LocalCodex'), node)
            if node.value == 'sheets_factory.evaluation.native_transport_frontier:LocalCodex':
                counts['new_agent_path'] += 1
                return _adapter_ast.copy_location(_adapter_ast.Constant('sheets_factory.evaluation.native_transport_frontier_v4:LocalCodex'), node)
            return node
    tree = ClockNamespace().visit(tree)
    if counts != {'clock_import': 1, 'old_agent_path': 1, 'new_agent_path': 1}:
        raise ValueError('Unexpected frozen native adapter; no broad v4 fallback')
    return _adapter_ast.fix_missing_locations(tree)


exec(compile(_native_v4_tree(), __file__, 'exec'), globals())
_NATIVE_V4_ORIGINAL_AST = adapted_ast
_NATIVE_V4_ORIGINAL_PROVENANCE = _transport_provenance


def adapted_ast():
    _native_v4_upstream_guard()
    return _NATIVE_V4_ORIGINAL_AST()


def _transport_provenance():
    return {**_NATIVE_V4_ORIGINAL_PROVENANCE(), 'frozen_native_transport_adapter_v3': _native_v4_upstream_guard()}
