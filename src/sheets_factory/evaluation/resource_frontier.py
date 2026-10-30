"""Isolated resource-export adapter for the frozen one-attempt frontier runner.

The existing runner and its old task inventory remain unchanged. This namespace
executes the exact same runner AST with only the export inspector, full file
inventory and installed-agent import path adapted to the resource format.
"""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

UPSTREAM_SHA256 = 'f507f738726347f61c27c3cf866d701e722690a87951b38d349b7d046d34df36'
RESOURCE_EXTRA_FILES = frozenset({'environment/resource_runner.py', 'environment/runtime_profile.json',
                                  'tests/streaming_core.py', 'tests/runtime_profile.json'})


def adapted_ast():
    location = _Path(__file__).with_name('frontier.py')
    raw = location.read_bytes()
    if _hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('The resource runner requires the exact independently tested upstream runner')
    tree = _ast.parse(raw, filename=str(location))
    counts = {'inspector': 0, 'inventory': 0, 'agent_path': 0}
    for node in tree.body:
        if isinstance(node, _ast.ImportFrom) and node.module == 'harbor' and node.level == 1:
            if [(item.name, item.asname) for item in node.names] != [('inspect_export', None)]:
                raise ValueError('The upstream export-inspector import changed')
            node.module = 'resource_harbor'
            node.names = [_ast.alias(name='inspect_resource_export', asname='inspect_export')]
            counts['inspector'] += 1
        if isinstance(node, _ast.Assign) and any(isinstance(target, _ast.Name) and target.id == 'TASK_FILES'
                                               for target in node.targets):
            value = node.value
            if not (isinstance(value, _ast.Call) and isinstance(value.func, _ast.Name)
                    and value.func.id == 'frozenset' and len(value.args) == 1
                    and isinstance(value.args[0], _ast.Set)):
                raise ValueError('The exact upstream task-inventory declaration changed')
            value.args[0].elts += [_ast.Constant(name) for name in sorted(RESOURCE_EXTRA_FILES)]
            counts['inventory'] += 1
    class AgentPath(_ast.NodeTransformer):
        def visit_Constant(self, node):
            if node.value == 'sheets_factory.evaluation.frontier:LocalCodex':
                counts['agent_path'] += 1
                return _ast.copy_location(_ast.Constant('sheets_factory.evaluation.resource_frontier:LocalCodex'), node)
            return node
    tree = AgentPath().visit(tree)
    if counts != {'inspector': 1, 'inventory': 1, 'agent_path': 2}:
        raise ValueError('An expected isolated resource-runner substitution is missing or repeated')
    return _ast.fix_missing_locations(tree)


# This module has its own globals. No function, constant, registry, scoring rule
# or execution environment in the existing frontier module is monkey-patched.
exec(compile(adapted_ast(), __file__, 'exec'), globals())
