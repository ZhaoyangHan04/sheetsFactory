"""Prospective complete-clock bounds with proved, uniquely owned overlap.

The frozen v3 parser remains unchanged. This namespace adds only the metadata
regex flag ``i`` and conservative overlap credits with explicit interval proofs.
Parallel primitive durations are always summed. Unknown evidence stays unknown.
"""
from __future__ import annotations

import ast
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
from types import FunctionType

from . import tool_time_clock_bounds as base

BASE_SHA256 = 'cd43938b7c9cdf3f7f6ee6dd38cc9b0cf4b62c50f28c598da9ebcbfd5bf9bb44'
EXACT_SHA256 = 'a32def98182b38b52396439014dffff840a255a5a89131a45d7e990130890c3f'
METHOD = 'complete_dual_clock_envelope_with_proven_owned_overlap_v4'
ENDPOINT_MARGIN_NS = base.ENDPOINT_MARGIN_NS
FROZEN_CLOCK_TOLERANCE_NS = base.FROZEN_CLOCK_TOLERANCE_NS
NS = base.NS
ClockEvidenceError = base.ClockEvidenceError
METADATA_REGEX_FLAGS = ('', 'i')


def _require(condition, message):
    if not condition: raise ClockEvidenceError(message)


def dependencies():
    records = [base._read(base.__file__)[1], base._read(Path(base.__file__).with_name('tool_time.py'))[1]]
    _require(records[0]['sha256'] == BASE_SHA256 and records[1]['sha256'] == EXACT_SHA256,
             'The frozen complete-clock or exact parser changed')
    return records


def _namespace():
    dependencies()
    namespace = dict(base.__dict__)
    pattern = base._META.pattern
    _require(pattern.count(r'/\.test') == 1, 'Unexpected frozen metadata grammar')
    namespace['_META'] = re.compile(pattern.replace(r'/\.test', r'/(?:i)?\.test'))
    tree = ast.parse(Path(base.__file__).read_bytes(), filename=base.__file__)
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == '_StaticExec']
    _require(len(classes) == 1, 'Exactly one frozen static recognizer required')
    exec(compile(ast.fix_missing_locations(ast.Module(body=classes, type_ignores=[])), base.__file__, 'exec'), namespace)
    namespace['_native'] = FunctionType(base._native.__code__, namespace, '_native', base._native.__defaults__, base._native.__closure__)
    return namespace


def static_calls(code):
    """Recognize the bounded literal dispatch grammar; never execute user JS."""
    return _namespace()['_StaticExec'](code).parse()


def _union(intervals):
    merged = []
    for left, right in sorted(intervals):
        _require(type(left) is int and type(right) is int and left <= right, 'Invalid overlap interval')
        if not merged or left > merged[-1][1]: merged.append([left, right])
        else: merged[-1][1] = max(merged[-1][1], right)
    return merged, sum(right - left for left, right in merged)


def _overlap_proofs(tools, wrappers):
    interiors = {}
    for tool in tools:
        duration = tool['reported_duration_ns']
        if duration is None or tool['clock_disagreement_above_frozen_5ms']: continue
        start, end = tool['start_epoch_ns'], tool['end_epoch_ns']
        # Intersect endpoint span and both ways of anchoring the reported
        # duration; shrink each endpoint. Disagreeing clocks earn no credit.
        left = max(start, end - duration) + ENDPOINT_MARGIN_NS
        right = min(end, start + duration) - ENDPOINT_MARGIN_NS
        if left < right: interiors[tool['id']] = [left, right]
    total = 0
    for wrapper in wrappers:
        owned = {tool['id'] for tool in tools if tool['owner_call_id'] == wrapper['call_id']}
        owned.update(call['owner_native_id'] for call in wrapper['static_calls'] if call['kind'] == 'poll')
        intersections = []
        for identity in sorted(owned):
            if identity not in interiors: continue
            left, right = interiors[identity]
            left = max(left, wrapper['start_epoch_ns'] + ENDPOINT_MARGIN_NS)
            right = min(right, wrapper['end_epoch_ns'] - ENDPOINT_MARGIN_NS)
            if left < right: intersections.append({'native_id': identity, 'left_ns': left, 'right_ns': right})
        merged, credit = _union([(r['left_ns'], r['right_ns']) for r in intersections])
        _require(0 <= credit <= wrapper['full_wall_ns'] <= wrapper['upper_ns'], 'Overlap exceeds its own wrapper wall')
        wrapper.update(uniquely_owned_or_polled_native_ids=sorted(owned), credited_native_intersections=intersections,
            guaranteed_overlap_union=merged, overlap_credit_ns=credit, uncovered_upper_ns=wrapper['upper_ns'] - credit)
        total += credit
    for tool in tools: tool['credit_eligible_common_interior_ns'] = interiors.get(tool['id'])
    return total


def _redact_signature(tool):
    signature = tool.pop('_signature')
    tool['signature_sha256'] = hashlib.sha256(json.dumps(signature, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def account_complete_clock_overlap(result_file, *, budget_seconds=1800):
    """Bound complete normal evidence; never read or reinterpret the reward.

    This is a separately declared policy. An upper bound at the budget is
    unknown, not a tool-budget failure, and never supplies an exact tool time.
    """
    receipt = {'kind': 'complete_native_unique_owned_overlap_clock_bound', 'version': 4, 'method': METHOD,
        'state': 'unknown', 'exact_state': 'unknown', 'passed': None, 'complete': False,
        'cumulative_tool_seconds': None, 'cumulative_exact_ns': None, 'cumulative_lower_bound_ns': None,
        'cumulative_upper_bound_ns': None, 'budget_seconds': None, 'strict_less_than': True,
        'model_response_time_included': False, 'parallel_executions': 'sum', 'overlap_credit_ns': 0,
        'wrapper_time': 'all wrapper upper walls minus proved uniquely owned common-interior unions',
        'endpoint_margin_per_interval_ns': ENDPOINT_MARGIN_NS, 'credit_clock_agreement_threshold_ns': FROZEN_CLOCK_TOLERANCE_NS,
        'metadata_regex_flags': list(METADATA_REGEX_FLAGS), 'historical_result_modified': False, 'qualification_claimed': False,
        'clock_envelope_assumption': 'Primitive upper=max(reported duration,endpoint span)+2ms; credit only the common interior of <=5ms-agreeing clocks with primitive and wrapper endpoints each shrunk by2ms',
        'problems': [], 'artifacts': [], 'tools': [], 'wrappers': []}
    try:
        bound_dependencies = dependencies(); namespace = _namespace()
        budget = Decimal(str(budget_seconds))
        _require(not isinstance(budget_seconds, bool) and budget.is_finite() and budget > 0
                 and budget * NS == (budget * NS).to_integral_value(), 'Invalid timing budget')
        receipt['budget_seconds'] = int(budget) if budget == budget.to_integral_value() else float(budget)
        path = Path(result_file).resolve(); raw, reference = base._read(path)
        receipt['result_file'] = reference; receipt['artifacts'].append(reference)
        actual = base._json(raw)
        _require(isinstance(actual, dict) and 'exception_info' in actual and actual['exception_info'] is None,
                 'Only normal terminal trials are eligible')
        execution = actual.get('agent_execution')
        _require(isinstance(execution, dict) and actual.get('finished_at'), 'Result terminal is missing')
        window = (base._stamp(execution.get('started_at')), base._stamp(execution.get('finished_at')))
        _require(window[0] <= window[1] <= base._stamp(actual['finished_at']), 'Invalid actual agent window')
        files = sorted((path.parent / 'agent/sessions').rglob('*.jsonl'))
        _require(len(files) == 1, 'Exactly one complete native session is supported')
        native_raw, native_ref = base._read(files[0]); stream_raw, stream_ref = base._read(path.parent / 'agent/codex.txt')
        receipt['implementation'] = base._read(__file__)[1]
        receipt['artifacts'].extend([native_ref, stream_ref, receipt['implementation'], *bound_dependencies])
        exact = base.account_trial_tool_time(path, budget_seconds=budget_seconds, allow_mixed_file_change_polls=True)
        receipt['original_exact_receipt'] = exact
        tools, wrappers, terminal = namespace['_native'](base._records(native_raw), window)
        stream_tools, stream_terminal = base._stream(base._records(stream_raw, stream=True))
        _require(terminal['thread_id'] == stream_terminal['thread_id'], 'Native/stream thread identity mismatch')
        _require(len(tools) == len(stream_tools), 'Ordered native/stream coverage differs')
        for native, stream in zip(tools, stream_tools, strict=True):
            _require(native['_signature'] == stream['_signature'] and native['status'] == stream['status']
                     and native['exit_code'] == stream['exit_code'], 'Ordered native/stream signature, status or exit mismatch')
            native['stream_id'] = stream['id']; native['stream_line'] = stream['stream_line']
        _require(any(t['clock_disagreement_above_frozen_5ms'] for t in tools), 'No native dual-clock disagreement above frozen5ms threshold')
        _require(exact.get('state') == 'unknown', 'This route is only for unresolved exact timing')
        coverage = base._ownership(tools, wrappers)
        credit = _overlap_proofs(tools, wrappers)
        lower = sum(t['lower_ns'] for t in tools); primitive_upper = sum(t['upper_ns'] for t in tools)
        wrapper_upper = sum(w['upper_ns'] for w in wrappers); upper = primitive_upper + wrapper_upper - credit
        _require(upper == primitive_upper + sum(w['uncovered_upper_ns'] for w in wrappers), 'Incomplete uncovered wrapper accounting')
        for tool in tools: _redact_signature(tool)
        # Store command hashes, never duplicate shell literals into this receipt.
        for wrapper in wrappers:
            for call in wrapper['static_calls']:
                if 'command' in call:
                    command = call.pop('command'); call['command_sha256'] = hashlib.sha256(command.encode()).hexdigest()
        receipt.update(tools=tools, wrappers=wrappers, coverage={**coverage, 'native_tool_count': len(tools), 'stream_tool_count': len(stream_tools),
            'wrapper_call_count': len(wrappers), 'wrapper_output_count': len(wrappers),
            'native_stream_ordered_signatures_status_and_exits_equal': True, 'all_intervals_in_agent_window': True,
            'normal_native_terminal': terminal, 'normal_stream_terminal': stream_terminal,
            'all_parallel_primitive_uppers_summed': True, 'all_uncovered_wrapper_time_retained': True,
            'disagreeing_clock_items_never_credit_overlap': True},
            primitive_upper_sum_ns=primitive_upper, wrapper_upper_sum_ns=wrapper_upper, overlap_credit_ns=credit,
            cumulative_lower_bound_ns=lower, cumulative_upper_bound_ns=upper,
            cumulative_lower_bound_seconds=str(Decimal(lower) / NS), cumulative_upper_bound_seconds=str(Decimal(upper) / NS))
        _require(all(base._read(item['path'])[1] == item for item in receipt['artifacts']), 'Evidence changed during accounting')
        receipt['complete'] = True
        receipt['clock_disagreement_count'] = sum(t['clock_disagreement_above_frozen_5ms'] for t in tools)
        if upper < int(budget * NS): receipt.update(state='verified_owned_overlap_bound', passed=True)
        else: receipt['problems'].append('Conservative upper bound does not prove strict under-budget execution')
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError, ArithmeticError) as error:
        receipt['problems'].append(str(error))
    return receipt
