"""Prospective native runner for the frozen complete-clock v5 measurement.

Only fresh selections can use this module. Historical runners, manifests,
reservations and rewards remain unchanged.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from . import linear_capital_scaled_frontier_v4 as prior
from . import tool_time_clock_bounds_v5 as clocks

PRIOR_SHA256 = '8db68c60c6ae3260c1b4114c394e697e0dad81040ad15d733779242b189e1ce2'
CLOCK_SHA256 = 'f0f8bfeb68c778128a16cfa4753430b76819c963e36106e3735d55c6f56333b2'
POLICY_V5 = dict(clocks.POLICY_V5)


def _reference(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def verify_dependencies():
    if (_reference(prior.__file__)['sha256'] != PRIOR_SHA256
            or _reference(clocks.__file__)['sha256'] != CLOCK_SHA256):
        raise ValueError('The frozen native runner or complete-clock v5 changed')
    clocks.dependencies()


def _provenance():
    verify_dependencies()
    return {**prior._provenance(), 'prospective_native_v5': _reference(__file__),
            'prospective_clock_bounds_v5': _reference(clocks.__file__)}


def adapted_ast():
    verify_dependencies()
    tree = prior.adapted_ast()
    counts = {'agent': 0, 'policy': 0, 'account': 0, 'version': 0, 'message': 0}

    class Adapt(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id == 'POLICY_V4':
                node.id = 'POLICY_V5'; counts['policy'] += 1
            elif node.id == 'account_trial_tool_time_v4':
                node.id = 'account_trial_tool_time_v5'; counts['account'] += 1
            return node

        def visit_Compare(self, node):
            if ast.unparse(node) in ("timing_version == 4", "selection.get('tool_time_policy_version') == 4"):
                node.comparators[0] = ast.Constant(5); counts['version'] += 1
            return self.generic_visit(node)

        def visit_Constant(self, node):
            replacements = {
                'sheets_factory.evaluation.linear_capital_scaled_frontier_v4:LocalCodex':
                    'sheets_factory.evaluation.linear_capital_scaled_frontier_v5:LocalCodex',
                'This runner requires an explicit prospective tool_time_policy_version=4':
                    'This runner requires an explicit prospective tool_time_policy_version=5',
                'Unsupported cumulative tool-time policy for the version-four runner':
                    'Unsupported cumulative tool-time policy for the version-five runner',
                'A frozen earlier selection cannot be reinterpreted by the version-four runner':
                    'A frozen earlier selection cannot be reinterpreted by the version-five runner',
            }
            if type(node.value) is str and node.value in replacements:
                counts['agent' if node.value.endswith(':LocalCodex') else 'message'] += 1
                node.value = replacements[node.value]
            return node

    tree = Adapt().visit(tree)
    if counts != {'agent': 2, 'policy': 7, 'account': 1, 'version': 2, 'message': 3}:
        raise ValueError('The narrow prospective v5 runner adaptation changed: ' + str(counts))
    return ast.fix_missing_locations(tree)


_namespace = {**prior._namespace, '__name__': __name__, '__file__': __file__,
              '__package__': __package__, 'POLICY_V5': POLICY_V5,
              'account_trial_tool_time_v5': clocks.account_trial_tool_time_v5,
              '_transport_provenance': _provenance}
exec(compile(adapted_ast(), __file__, 'exec'), _namespace)
for _name in ('freeze_selection', 'run_evaluation', 'execute_evaluation', 'apply_tool_time_policy',
              'LocalCodex', 'collect_attempts', 'classify_retryable', 'assess_infrastructure_retry',
              'review_agent_timeout', 'transport_profile', 'TASK_FILES', 'MODEL', 'EFFORT', 'PROMPT',
              'PROFILE_PATH', 'summarize', '_runtime_provenance'):
    if _name in _namespace:
        globals()[_name] = _namespace[_name]
