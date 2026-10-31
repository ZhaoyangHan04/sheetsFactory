"""Prospective native runner for the frozen complete-clock v6 measurement.

Only fresh selections can use this module. Historical runners, manifests,
reservations and rewards remain unchanged.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from . import linear_capital_scaled_frontier_v5 as prior
from . import tool_time_clock_bounds_v6 as clocks

PRIOR_SHA256 = '8cba897fd4375461b9e2237a0eeb699c4629fdb4937c4363d7dc08e7ac17d8e5'
CLOCK_SHA256 = 'fb6f3a54cf36562eb10d02699e8e8f5b8fe83f8b83f2b0509e84893f9e220cb8'
POLICY_V6 = dict(clocks.POLICY_V6)


def _reference(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def verify_dependencies():
    if (_reference(prior.__file__)['sha256'] != PRIOR_SHA256
            or _reference(clocks.__file__)['sha256'] != CLOCK_SHA256):
        raise ValueError('The frozen native runner or complete-clock v6 changed')
    clocks.dependencies()


def _provenance():
    verify_dependencies()
    return {**prior._provenance(), 'prospective_native_v6': _reference(__file__),
            'prospective_clock_bounds_v6': _reference(clocks.__file__)}


def adapted_ast():
    verify_dependencies()
    tree = prior.adapted_ast()
    counts = {'agent': 0, 'policy': 0, 'account': 0, 'version': 0, 'message': 0}

    class Adapt(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id == 'POLICY_V5':
                node.id = 'POLICY_V6'; counts['policy'] += 1
            elif node.id == 'account_trial_tool_time_v5':
                node.id = 'account_trial_tool_time_v6'; counts['account'] += 1
            return node

        def visit_Compare(self, node):
            if ast.unparse(node) in ("timing_version == 5", "selection.get('tool_time_policy_version') == 5"):
                node.comparators[0] = ast.Constant(6); counts['version'] += 1
            return self.generic_visit(node)

        def visit_Constant(self, node):
            replacements = {
                'sheets_factory.evaluation.linear_capital_scaled_frontier_v5:LocalCodex':
                    'sheets_factory.evaluation.linear_capital_scaled_frontier_v6:LocalCodex',
                'This runner requires an explicit prospective tool_time_policy_version=5':
                    'This runner requires an explicit prospective tool_time_policy_version=6',
                'Unsupported cumulative tool-time policy for the version-five runner':
                    'Unsupported cumulative tool-time policy for the version-six runner',
                'A frozen earlier selection cannot be reinterpreted by the version-five runner':
                    'A frozen earlier selection cannot be reinterpreted by the version-six runner',
            }
            if type(node.value) is str and node.value in replacements:
                counts['agent' if node.value.endswith(':LocalCodex') else 'message'] += 1
                node.value = replacements[node.value]
            return node

    tree = Adapt().visit(tree)
    if counts != {'agent': 2, 'policy': 7, 'account': 1, 'version': 2, 'message': 3}:
        raise ValueError('The narrow prospective v6 runner adaptation changed: ' + str(counts))
    return ast.fix_missing_locations(tree)


_namespace = {**prior._namespace, '__name__': __name__, '__file__': __file__,
              '__package__': __package__, 'POLICY_V6': POLICY_V6,
              'account_trial_tool_time_v6': clocks.account_trial_tool_time_v6,
              '_transport_provenance': _provenance}
exec(compile(adapted_ast(), __file__, 'exec'), _namespace)
for _name in ('freeze_selection', 'run_evaluation', 'execute_evaluation', 'apply_tool_time_policy',
              'LocalCodex', 'collect_attempts', 'classify_retryable', 'assess_infrastructure_retry',
              'review_agent_timeout', 'transport_profile', 'TASK_FILES', 'MODEL', 'EFFORT', 'PROMPT',
              'PROFILE_PATH', 'summarize', '_runtime_provenance'):
    if _name in _namespace:
        globals()[_name] = _namespace[_name]
