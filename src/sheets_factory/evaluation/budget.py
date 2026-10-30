"""Validate prospective execution budgets without rewriting legacy protocols.

The elapsed guard bounds runner occupancy. Only cumulative tool execution is a
model budget in the explicit operational-guard contract. An absent contract
retains the original elapsed-deadline protocol.
"""
from __future__ import annotations


class ExecutionBudgetError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise ExecutionBudgetError(message)


def validate_execution_budget(value):
    """Return a copy of the exact, supported source-manifest contract."""
    _require(isinstance(value, dict), 'execution_budget must be an object')
    _require(set(value) == {'version', 'elapsed_policy', 'elapsed_guard_seconds', 'tool_budget_seconds'},
             'execution_budget has missing or unsupported fields')
    _require(type(value['version']) is int and value['version'] == 1,
             'execution_budget version must be 1')
    _require(value['elapsed_policy'] == 'operational_guard',
             'execution_budget elapsed_policy must be operational_guard')
    _require(type(value['tool_budget_seconds']) is int and value['tool_budget_seconds'] == 1800,
             'execution_budget tool_budget_seconds must be 1800')
    _require(type(value['elapsed_guard_seconds']) is int and value['elapsed_guard_seconds'] >= 1800,
             'execution_budget elapsed_guard_seconds must be an integer of at least 1800')
    return dict(value)


def resolve_execution_budget(source, timeout_seconds=None):
    """Resolve the runner timeout; a new contract must be explicit in source."""
    if 'execution_budget' not in source:
        timeout = 1800 if timeout_seconds is None else timeout_seconds
        _require(type(timeout) is int and 900 <= timeout <= 1800,
                 'Use a fair 900–1800 second per-task budget')
        return None, timeout
    budget = validate_execution_budget(source['execution_budget'])
    guard = budget['elapsed_guard_seconds']
    _require(timeout_seconds is None or (type(timeout_seconds) is int and timeout_seconds == guard),
             'Explicit timeout_seconds conflicts with execution_budget elapsed_guard_seconds')
    return budget, guard


def validate_selection_execution_budget(selection, evaluation=None):
    """Bind the prospective contract to selection, tasks and evaluation.

    Legacy selections do not acquire a contract through this read-only check.
    A partial or inconsistent opt-in is always rejected.
    """
    explicit = 'execution_budget' in selection
    budget = validate_execution_budget(selection['execution_budget']) if explicit else None
    if explicit:
        _require(type(selection.get('timeout_seconds')) is int
                 and selection['timeout_seconds'] == budget['elapsed_guard_seconds'],
                 'Selection timeout does not match execution_budget elapsed guard')
        policy = selection.get('tool_time_policy') or {}
        _require(type(policy.get('budget_seconds')) is int
                 and policy['budget_seconds'] == budget['tool_budget_seconds']
                 and policy.get('strict_less_than') is True
                 and policy.get('exclude_model_response_time') is True
                 and policy.get('parallel_executions') == 'sum',
                 'Selection tool-time policy does not match execution_budget')
    for task in selection.get('tasks', []):
        _require(('execution_budget' in task) == explicit,
                 'Task execution_budget presence differs from selection')
        if explicit:
            _require(validate_execution_budget(task['execution_budget']) == budget,
                     'Task execution_budget differs from selection')
            _require(type(task.get('timeout_seconds')) is int
                     and task['timeout_seconds'] == budget['elapsed_guard_seconds'],
                     'Task timeout does not match execution_budget elapsed guard')
            _require(task.get('tool_time_policy') == selection.get('tool_time_policy'),
                     'Task tool-time policy differs from selection')
    if evaluation is not None:
        _require(('execution_budget' in evaluation) == explicit,
                 'Evaluation execution_budget presence differs from selection')
        if explicit:
            _require(validate_execution_budget(evaluation['execution_budget']) == budget,
                     'Evaluation execution_budget differs from selection')
            _require(type(evaluation.get('timeout_seconds')) is int
                     and evaluation['timeout_seconds'] == budget['elapsed_guard_seconds'],
                     'Evaluation timeout does not match execution_budget elapsed guard')
            _require(evaluation.get('tool_time_policy') == selection.get('tool_time_policy'),
                     'Evaluation tool-time policy differs from selection')
        for attempt in evaluation.get('attempts', []) + evaluation.get('infra_history', []):
            _require(('execution_budget' in attempt) == explicit,
                     'Attempt execution_budget presence differs from selection')
            if explicit:
                _require(validate_execution_budget(attempt['execution_budget']) == budget,
                         'Attempt execution_budget differs from selection')
    return budget
