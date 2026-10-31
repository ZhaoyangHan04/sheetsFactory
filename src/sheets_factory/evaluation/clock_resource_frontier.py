"""Prospective resource runner with the explicit version-three clock policy.

The old runners retain their globals, AST and frozen policies. This namespace
accepts only version-three selections created before an attempt. Publication
support is separate and is not granted by this development runner.
"""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

from .resource_frontier import adapted_ast as _resource_ast
from .tool_time_bounds import POLICY_V2 as _BASE_POLICY, account_trial_tool_time_bounds as _base_bounds
from .tool_time_clock_bounds import METHOD as _CLOCK_METHOD, account_complete_clock_disagreement as _clock_bound

RESOURCE_ADAPTER_SHA256 = 'b6743fa3ee364ca90d5cd961ce1900ee1b84cb50b9797072b27c0376fb40f991'
CLOCK_PARSER_SHA256 = 'cd43938b7c9cdf3f7f6ee6dd38cc9b0cf4b62c50f28c598da9ebcbfd5bf9bb44'
FROZEN_FRONTIER_SHA256 = 'f507f738726347f61c27c3cf866d701e722690a87951b38d349b7d046d34df36'
POLICY_V3 = {**_BASE_POLICY, 'version': 3,
    'measurement': 'native_exact_or_static_pending_stop_or_complete_clock_envelope_v3',
    'complete_clock_measurement': _CLOCK_METHOD,
    'complete_clock_endpoint_margin_ns': 2_000_000,
    'complete_clock_overlap_credit_ns': 0,
    'complete_clock_stream_match': 'ordered signatures statuses exits and unique identities',
    'complete_clock_upper_at_budget': 'unknown_not_failure',
    'complete_clock_requires_normal_terminal': True}


def _bound_ref(path):
    path = _Path(path).resolve()
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': _hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def _v3_provenance():
    refs = {'clock_bound_parser': _bound_ref(_Path(__file__).with_name('tool_time_clock_bounds.py')),
            'resource_ast_adapter': _bound_ref(_Path(__file__).with_name('resource_frontier.py')),
            'frozen_frontier': _bound_ref(_Path(__file__).with_name('frontier.py'))}
    if (refs['clock_bound_parser']['sha256'] != CLOCK_PARSER_SHA256
            or refs['resource_ast_adapter']['sha256'] != RESOURCE_ADAPTER_SHA256
            or refs['frozen_frontier']['sha256'] != FROZEN_FRONTIER_SHA256):
        raise ValueError('The version-three runner dependency changed')
    return refs


def account_trial_tool_time_v3(result_file, *, stop_receipt_file=None, budget_seconds=1800):
    """Keep all original evidence; add a complete clock bound only after unknown."""
    base = _base_bounds(result_file, stop_receipt_file=stop_receipt_file, budget_seconds=budget_seconds)
    if base['state'] != 'unknown':
        return {**base, 'policy_version': 3, 'method': POLICY_V3['measurement'],
                'measurement_branch': 'unchanged_exact_or_stop_bound', 'base_policy_v2_receipt': base}
    clock = _clock_bound(result_file, budget_seconds=budget_seconds)
    return {**clock, 'policy_version': 3, 'method': POLICY_V3['measurement'],
            'measurement_branch': 'complete_clock_disagreement',
            'base_policy_v2_receipt': base, 'complete_clock_receipt': clock}


def adapted_ast():
    """Make a counted, fail-closed adaptation of the exact resource runner AST."""
    _v3_provenance()
    tree = _resource_ast()
    counts = {'version': 0, 'version_guard': 0, 'policy': 0, 'selection_guard': 0,
              'timing_guard': 0, 'timing_branch': 0, 'timing_call': 0,
              'timing_states': 0, 'capture_policy': 0, 'agent_path': 0, 'provenance': 0}
    def parsed(statement):
        return _ast.parse(statement).body[0]
    def same(left, statement):
        return _ast.dump(left) == _ast.dump(parsed(statement))
    for node in tree.body:
        if not isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            continue
        if node.name == 'freeze_selection':
            for i, item in enumerate(node.body):
                if same(item, "timing_version = source.get('tool_time_policy_version', 2)"):
                    node.body[i] = parsed("timing_version = source.get('tool_time_policy_version')")
                    counts['version'] += 1
                elif same(item, "_require(type(timing_version) is int and timing_version in {1, 2}, 'Explicit tool_time_policy_version must be 1 or 2')"):
                    node.body[i] = parsed("_require(type(timing_version) is int and timing_version == 3, 'This runner requires an explicit prospective tool_time_policy_version=3')")
                    counts['version_guard'] += 1
                elif same(item, 'timing_policy = dict(POLICY_V2 if timing_version == 2 else TOOL_TIME_POLICY)'):
                    node.body[i] = parsed('timing_policy = dict(POLICY_V3)')
                    counts['policy'] += 1
        elif node.name == '_selection_execution_budget':
            guard = parsed("_require(type(selection.get('tool_time_policy_version')) is int and selection.get('tool_time_policy_version') == 3 and selection.get('tool_time_policy') == POLICY_V3, 'A frozen version-one or version-two selection cannot be reinterpreted by the version-three runner')")
            node.body.insert(0, guard)
            counts['selection_guard'] += 1
        elif node.name == '_runtime_provenance':
            returns = [i for i, item in enumerate(node.body) if isinstance(item, _ast.Return)]
            if len(returns) != 1:
                raise ValueError('The upstream provenance return changed')
            node.body.insert(returns[0], parsed('provenance.update(_v3_provenance())'))
            counts['provenance'] += 1
        elif node.name == 'apply_tool_time_policy':
            for i, item in enumerate(node.body):
                if same(item, "_require(policy in (TOOL_TIME_POLICY, POLICY_V2), 'Unsupported cumulative tool-time policy')"):
                    node.body[i] = parsed("_require(policy == POLICY_V3, 'Unsupported cumulative tool-time policy for the version-three runner')")
                    counts['timing_guard'] += 1
            class Timing(_ast.NodeTransformer):
                def visit_Compare(self, value):
                    if _ast.dump(value) == _ast.dump(_ast.parse('policy == POLICY_V2', mode='eval').body):
                        counts['timing_branch'] += 1
                        return _ast.parse('policy == POLICY_V3', mode='eval').body
                    return self.generic_visit(value)
                def visit_Call(self, value):
                    if isinstance(value.func, _ast.Name) and value.func.id == 'account_trial_tool_time_bounds':
                        counts['timing_call'] += 1
                        value.func.id = 'account_trial_tool_time_v3'
                    return self.generic_visit(value)
                def visit_Set(self, value):
                    if _ast.dump(value) == _ast.dump(_ast.parse("{'verified', 'bounded'}", mode='eval').body):
                        counts['timing_states'] += 1
                        value.elts.append(_ast.Constant('verified_conservative_bound'))
                    return value
            Timing().visit(node)
        elif node.name == 'execute_evaluation':
            class CapturePolicy(_ast.NodeTransformer):
                def visit_Name(self, value):
                    if value.id == 'POLICY_V2':
                        counts['capture_policy'] += 1
                        value.id = 'POLICY_V3'
                    return value
            CapturePolicy().visit(node)
    class AgentPath(_ast.NodeTransformer):
        def visit_Constant(self, value):
            if value.value == 'sheets_factory.evaluation.resource_frontier:LocalCodex':
                counts['agent_path'] += 1
                value.value = 'sheets_factory.evaluation.clock_resource_frontier:LocalCodex'
            return value
    tree = AgentPath().visit(tree)
    expected = {'version': 1, 'version_guard': 1, 'policy': 1, 'selection_guard': 1,
                'timing_guard': 1, 'timing_branch': 1, 'timing_call': 1,
                'timing_states': 2, 'capture_policy': 3, 'agent_path': 2, 'provenance': 1}
    if counts != expected:
        raise ValueError('The exact version-three AST substitutions changed: ' + str(counts))
    return _ast.fix_missing_locations(tree)


# A distinct globals dictionary: no original module function or policy is edited.
exec(compile(adapted_ast(), __file__, 'exec'), globals())
