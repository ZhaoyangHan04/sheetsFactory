"""Prospective N360 v4 runner with a proved complete negative-bound case.

The frozen general v4 runner remains unchanged. In this namespace only, a
complete normal-tail lower bound at the strict budget proves a scored failure.
Straddling or incomplete evidence remains unknown. No elapsed-wall shortcut.
"""
from __future__ import annotations
import ast as _ast
from copy import deepcopy as _deepcopy
from pathlib import Path as _Path
import hashlib as _hashlib
from . import native_transport_frontier_v4 as _base
from .tool_time_clock_bounds_v4 import account_complete_clock_overlap as _complete

POLICY_V4 = {**_base.POLICY_V4, 'complete_clock_proved_failure':
    'complete original normal native/stream coverage and cumulative primitive lower bound >= strict budget'}


def account_trial_tool_time_v4(result_file, *, stop_receipt_file=None, budget_seconds=1800):
    receipt = _base.account_trial_tool_time_v4(result_file, stop_receipt_file=stop_receipt_file, budget_seconds=budget_seconds)
    bound = receipt.get('complete_owned_overlap_receipt', {})
    if (receipt.get('measurement_branch') == 'complete_proven_owned_overlap'
        and bound.get('complete') is True and type(bound.get('cumulative_lower_bound_ns')) is int
        and bound['cumulative_lower_bound_ns'] >= budget_seconds*10**9):
        return {**receipt, 'state': 'verified_tool_budget_lower_bound', 'passed': False,
            'measurement_branch': 'complete_proven_lower_bound_exhausted',
            'retained_general_v4_receipt': receipt}
    return receipt


def _provenance():
    raw = _Path(__file__).read_bytes()
    return {**_base._transport_provenance(), 'N360_prospective_budget_adapter':
        {'path': str(_Path(__file__).resolve()), 'sha256': _hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}}


def adapted_ast():
    tree = _base.adapted_ast(); counts = {'agent': 0, 'states': 0, 'retry': 0}
    class Adapt(_ast.NodeTransformer):
        def visit_Constant(self, node):
            if node.value == 'sheets_factory.evaluation.native_transport_frontier_v4:LocalCodex':
                node.value = 'sheets_factory.evaluation.linear_capital_scaled_frontier_v4:LocalCodex'; counts['agent'] += 1
            return node
        def visit_Set(self, node):
            if {n.value for n in node.elts if isinstance(n,_ast.Constant)} == {'verified','bounded','verified_conservative_bound','verified_owned_overlap_bound'}:
                node.elts.append(_ast.Constant('verified_tool_budget_lower_bound')); counts['states'] += 1
            return node
        def visit_Dict(self, node):
            keys = [n.value if isinstance(n,_ast.Constant) else None for n in node.keys]
            if keys == ['max_retries','scored_attempts_per_task','never_retry_scored'] and isinstance(node.values[0], _ast.Constant):
                if node.values[0].value != 2: raise ValueError('The frozen outer retry declaration changed')
                node.values[0] = _ast.Constant(0); counts['retry'] += 1
            return self.generic_visit(node)
    tree = Adapt().visit(tree)
    if counts != {'agent': 2, 'states': 2, 'retry': 1}: raise ValueError('The narrow N360 budget adaptation changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


_namespace = {**vars(_base), '__name__': __name__, '__file__': __file__, '__package__': __package__,
    'POLICY_V4': POLICY_V4, 'account_trial_tool_time_v4': account_trial_tool_time_v4,
    '_transport_provenance': _provenance}
exec(compile(adapted_ast(), __file__, 'exec'), _namespace)
for _name in ('freeze_selection', 'run_evaluation', 'execute_evaluation', 'apply_tool_time_policy',
    'LocalCodex', 'collect_attempts', 'classify_retryable', 'assess_infrastructure_retry', 'review_agent_timeout', 'transport_profile',
    'TASK_FILES', 'MODEL', 'EFFORT', 'PROMPT', 'PROFILE_PATH', 'summarize', '_runtime_provenance'):
    if _name in _namespace: globals()[_name] = _namespace[_name]
