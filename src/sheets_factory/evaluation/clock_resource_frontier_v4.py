"""Separate prospective version-four resource runner; earlier selections refuse.

Model, effort, resources, execution guard and strict SUM budget remain unchanged.
Only a prospectively frozen v4 selection can use proved owned-overlap bounds.
"""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

from . import clock_resource_frontier as _v3
from .tool_time_clock_bounds_v4 import (METHOD as _CLOCK_METHOD_V4,
    account_complete_clock_overlap as _clock_bound_v4, dependencies as _clock_dependencies_v4)

V3_RUNNER_SHA256 = 'ef104371ac76f84fd3658857b754beecf07c3cfc7d9f21c3546c30670aaf935f'
POLICY_V4 = {key: value for key, value in _v3.POLICY_V3.items() if key != 'complete_clock_overlap_credit_ns'}
POLICY_V4.update(version=4, measurement='native_exact_or_static_pending_stop_or_complete_owned_overlap_v4',
    complete_clock_measurement=_CLOCK_METHOD_V4,
    complete_clock_overlap_credit='union of proved common interiors within uniquely launching or literal-owned-poll wrappers',
    complete_clock_credit_agreement_ns=5_000_000, complete_clock_credit_endpoint_shrink_ns=2_000_000,
    complete_clock_metadata_regex_flags=['', 'i'])


def _bound_ref_v4(path):
    path = _Path(path).resolve(); raw = path.read_bytes()
    return {'path': str(path), 'sha256': _hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def _v4_provenance():
    old = _bound_ref_v4(_v3.__file__)
    if old['sha256'] != V3_RUNNER_SHA256: raise ValueError('The frozen v3 resource runner changed')
    _clock_dependencies_v4()
    return {**_v3._v3_provenance(), 'frozen_clock_runner_v3': old,
        'clock_bound_parser_v4': _bound_ref_v4(_Path(__file__).with_name('tool_time_clock_bounds_v4.py')),
        'clock_resource_runner_v4': _bound_ref_v4(__file__)}


def account_trial_tool_time_v4(result_file, *, stop_receipt_file=None, budget_seconds=1800):
    """Retain the complete v3 receipt; add the separately declared v4 bound."""
    _v4_provenance()
    old = _v3.account_trial_tool_time_v3(result_file, stop_receipt_file=stop_receipt_file, budget_seconds=budget_seconds)
    if old['state'] != 'unknown':
        return {**old, 'policy_version': 4, 'method': POLICY_V4['measurement'],
            'measurement_branch': 'unchanged_v3_exact_or_bound', 'base_policy_v3_receipt': old}
    bound = _clock_bound_v4(result_file, budget_seconds=budget_seconds)
    return {**bound, 'policy_version': 4, 'method': POLICY_V4['measurement'],
        'measurement_branch': 'complete_proven_owned_overlap', 'base_policy_v3_receipt': old,
        'complete_owned_overlap_receipt': bound}


def adapted_ast():
    """Counted adaptation of the frozen v3 AST, never its module globals."""
    _v4_provenance(); tree = _v3.adapted_ast()
    names = {'POLICY_V3': ('POLICY_V4', 7), 'account_trial_tool_time_v3': ('account_trial_tool_time_v4', 1), '_v3_provenance': ('_v4_provenance', 1)}
    counts = {key: 0 for key in names}; other = {'selection_version': 0, 'source_version': 0, 'timing_states': 0, 'agent_path': 0}
    old_states = _ast.dump(_ast.parse("{'verified','bounded','verified_conservative_bound'}", mode='eval').body)
    messages = {
        'This runner requires an explicit prospective tool_time_policy_version=3': 'This runner requires an explicit prospective tool_time_policy_version=4',
        'A frozen version-one or version-two selection cannot be reinterpreted by the version-three runner': 'A frozen earlier selection cannot be reinterpreted by the version-four runner',
        'Unsupported cumulative tool-time policy for the version-three runner': 'Unsupported cumulative tool-time policy for the version-four runner'}
    class Prospective(_ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id in names:
                counts[node.id] += 1; return _ast.copy_location(_ast.Name(id=names[node.id][0], ctx=node.ctx), node)
            return node
        def visit_Compare(self, node):
            if _ast.dump(node) == _ast.dump(_ast.parse("selection.get('tool_time_policy_version') == 3", mode='eval').body):
                other['selection_version'] += 1; node.comparators[0] = _ast.Constant(4)
            elif _ast.dump(node) == _ast.dump(_ast.parse('timing_version == 3', mode='eval').body):
                other['source_version'] += 1; node.comparators[0] = _ast.Constant(4)
            return self.generic_visit(node)
        def visit_Set(self, node):
            if _ast.dump(node) == old_states:
                other['timing_states'] += 1; node.elts.append(_ast.Constant('verified_owned_overlap_bound'))
            return self.generic_visit(node)
        def visit_Constant(self, node):
            if node.value == 'sheets_factory.evaluation.clock_resource_frontier:LocalCodex':
                other['agent_path'] += 1
                return _ast.copy_location(_ast.Constant('sheets_factory.evaluation.clock_resource_frontier_v4:LocalCodex'), node)
            if isinstance(node.value, str) and node.value in messages:
                return _ast.copy_location(_ast.Constant(messages[node.value]), node)
            return node
    tree = Prospective().visit(tree)
    if counts != {key: value[1] for key, value in names.items()} or other != {'selection_version': 1, 'source_version': 1, 'timing_states': 2, 'agent_path': 2}:
        raise ValueError('Unexpected frozen v3 AST; no broad v4 fallback')
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(), __file__, 'exec'), globals())
