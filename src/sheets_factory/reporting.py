"""Read-only run accounting and portable Chinese reports.

Reports never update task state or infer model cost from undocumented prices.
Provider-reported token subsets and credential-wide billing stay separate.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html import escape
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo
from urllib.parse import quote

import yaml


MODES = {'financial_modeling': 'Financial Modeling', 'debugging': 'Debugging'}
FINAL_RUN_STATUSES = frozenset({'completed', 'shortfall', 'failed', 'cancelled'})
STOPPED_RUN_STATUSES = FINAL_RUN_STATUSES | {'interrupted', 'paused', 'checkpointed', 'stopped'}


def _read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _instant(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _display_time(value):
    parsed = _instant(value)
    return parsed.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S +08:00') if parsed else None


def _run_is_live(run):
    return run.get('status') not in STOPPED_RUN_STATUSES and run.get('producer_active') is not False


def _time_measures(run, now):
    """Keep lifecycle elapsed time separate from producer execution phases."""
    live = _run_is_live(run)
    started = _instant(run.get('started_at'))
    phase_started = _instant(run.get('execution_phase_started_at'))
    resumed = _instant(run.get('resumed_at'))
    finished = _instant(run.get('finished_at'))
    # A resumed producer retains the previous phase's finished_at until it exits.
    # It is not the end of the current lifecycle or the current active phase.
    boundary = max((stamp for stamp in (phase_started, resumed) if stamp), default=None)
    elapsed_end = now if live else finished
    elapsed_scope = 'started_at_to_report_time' if live else 'started_at_to_finished_at'
    elapsed_status, elapsed = ('live' if live else 'known'), None
    if not started:
        elapsed_status, elapsed_scope = 'unknown', 'unknown_missing_started_at'
    elif not elapsed_end:
        elapsed_status, elapsed_scope = 'unknown', 'unknown_missing_finished_at'
    elif elapsed_end < started or (not live and boundary and elapsed_end < boundary):
        elapsed_status, elapsed_scope = 'unknown', 'unknown_invalid_or_stale_end_timestamp'
    else:
        elapsed = (elapsed_end - started).total_seconds()

    def valid_seconds(value):
        return _number(value) and Decimal(str(value)).is_finite() and value >= 0

    recorded = run.get('wall_seconds')
    active = recorded if valid_seconds(recorded) else None
    active_status = 'known' if active is not None else 'unknown'
    active_scope = 'recorded_run_wall_seconds' if active is not None else 'unknown_not_recorded'
    if live and phase_started:
        previous = run.get('previous_wall_seconds') if run.get('resume_count') else 0
        if phase_started > now or (resumed and phase_started < resumed):
            active, active_status, active_scope = None, 'unknown', 'unknown_current_phase_start'
        elif not valid_seconds(previous):
            active, active_status, active_scope = None, 'unknown', 'unknown_previous_phase_seconds'
        else:
            active = previous + (now - phase_started).total_seconds()
            active_status, active_scope = 'live', 'previous_phase_seconds_plus_current_phase_elapsed'
    # Preserve the legacy projection for existing consumers; reports below use
    # the two explicit measures instead of calling this value end-to-end time.
    wall, wall_scope = recorded, 'recorded_run_wall_time'
    if not _number(wall):
        if live and started:
            if run.get('resume_count') and phase_started:
                wall = (run.get('previous_wall_seconds') or 0) + max(0, (now - phase_started).total_seconds())
                wall_scope = 'live_accumulated_execution_phase_wall_time'
            else:
                wall, wall_scope = max(0, (now - started).total_seconds()), 'live_elapsed_since_run_start'
        else:
            wall, wall_scope = None, 'unknown_not_recorded'
    return {
        'wall_seconds': wall, 'wall_scope': wall_scope,
        'end_to_end_elapsed_seconds': elapsed, 'end_to_end_elapsed_status': elapsed_status,
        'end_to_end_elapsed_scope': elapsed_scope,
        'end_to_end_elapsed_ended_at': elapsed_end.isoformat() if elapsed is not None else None,
        'active_producer_cumulative_phase_seconds': active,
        'active_producer_cumulative_phase_status': active_status,
        'active_producer_cumulative_phase_scope': active_scope,
        'time_measures_additive': False,
    }


def read_run(run_dir):
    """Read one SQLite transaction without changing the authoritative audit."""
    path = Path(run_dir).resolve() / 'run.sqlite'
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    connection.execute('PRAGMA query_only=ON')
    connection.execute('BEGIN')
    try:
        row = connection.execute("SELECT value FROM state WHERE key='run'").fetchone()
        result = {'run': json.loads(row[0]) if row else {}}
        for name in ('tasks', 'nodes', 'calls'):
            result[name] = [json.loads(row[0]) for row in connection.execute(f'SELECT payload FROM {name} ORDER BY rowid')]
        result['events'] = []
        for row in connection.execute("SELECT id,timestamp,kind,payload FROM events WHERE kind IN "
                "('checker.result','task.revised','task.rejected','run.finished','run.amended','run.resumed',"
                "'llm.started','llm.completed','llm.failed') ORDER BY id"):
            payload = json.loads(row[3])
            # Older direct audit inserts may use a payload `kind` to describe
            # the amendment. It must not overwrite the authoritative event kind.
            result['events'].append({**payload, 'payload_kind': payload.get('kind'),
                                     'id': row[0], 'timestamp': row[1], 'kind': row[2]})
        return result
    finally:
        connection.rollback()
        connection.close()


def _usage_value(call, name):
    aliases = {
        'input_tokens': ('input_tokens', 'prompt_tokens'),
        'cached_input_tokens': ('cached_input_tokens', 'cache_read_input_tokens'),
        'output_tokens': ('output_tokens', 'completion_tokens'),
        'reasoning_output_tokens': ('reasoning_output_tokens', 'reasoning_tokens'),
    }
    usage = call.get('usage') or {}
    for source in (call, usage):
        for key in aliases[name]:
            value = source.get(key)
            if _number(value) and value >= 0:
                return value
    details = usage.get('input_tokens_details' if name == 'cached_input_tokens' else 'output_tokens_details') or {}
    fallback = details.get('cached_tokens' if name == 'cached_input_tokens' else 'reasoning_tokens')
    if name in {'cached_input_tokens', 'reasoning_output_tokens'} and _number(fallback) and fallback >= 0:
        return fallback
    return None


def summarize_usage(calls):
    fields = {}
    for name in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens'):
        values = [_usage_value(call, name) for call in calls]
        known = [value for value in values if value is not None]
        fields[name] = {'known_sum': sum(known), 'known_call_count': len(known),
                        'unknown_call_count': len(values) - len(known),
                        'all_calls_known': len(known) == len(values)}
    core_unknown = sum(_usage_value(call, 'input_tokens') is None or _usage_value(call, 'output_tokens') is None
                       for call in calls)
    durations = [call.get('duration_ms') for call in calls]
    return {'call_count': len(calls), 'fields': fields, 'unknown_core_usage_calls': core_unknown,
            'known_total_tokens': fields['input_tokens']['known_sum'] + fields['output_tokens']['known_sum'],
            'exact_total_available': core_unknown == 0,
            'cumulative_seconds': sum(value for value in durations if _number(value)) / 1000,
            'unknown_duration_calls': sum(not _number(value) for value in durations),
            'status_counts': dict(Counter(call.get('status', 'unknown') for call in calls)),
            'reasoning_note': 'reasoning_output_tokens 为 output_tokens 的子集；缓存输入为 input_tokens 的子集，均不重复相加。',
            'by_role': {role: {'calls': len(group), 'known_total_tokens': sum(
                (_usage_value(call, 'input_tokens') or 0) + (_usage_value(call, 'output_tokens') or 0) for call in group)}
                for role, group in _group(calls, 'role').items()}}


def _group(items, key):
    result = defaultdict(list)
    for item in items:
        result[item.get(key, 'unknown')].append(item)
    return dict(result)


def _observed_calls(calls, events, run, now):
    """Include recorded request starts without inventing their token usage."""
    known = {call.get('call_id') for call in calls if call.get('call_id')}
    pending = {}
    live = _run_is_live(run)
    for event in events:
        call_id = event.get('call_id')
        if not call_id or call_id in known:
            continue
        if event['kind'] == 'llm.started':
            pending[call_id] = {**event, 'status': 'running' if live else 'unknown',
                'usage': None, 'input_tokens': None, 'output_tokens': None,
                'projected_from_events': True, 'completion_missing': not live,
                'started_at': event.get('started_at', event.get('timestamp'))}
        elif event['kind'] in {'llm.completed', 'llm.failed'} and call_id in pending:
            pending[call_id].update(event)
            pending[call_id].update(status='completed' if event['kind'] == 'llm.completed' else 'failed',
                                    finished_at=event.get('timestamp'), completion_missing=False)
    for call in pending.values():
        start = _instant(call.get('started_at'))
        end = _instant(call.get('finished_at'))
        if start and (end or call['status'] == 'running'):
            call.setdefault('duration_ms', max(0, ((end or now) - start).total_seconds() * 1000))
    return calls + list(pending.values())


def _stage_accounting(nodes, calls, now):
    """Group actual stage-tagged calls and completed node attempts separately."""
    stages = {}
    for node in nodes:
        name = node.get('node') or node.get('node_id') or 'unknown'
        stages.setdefault(name, {'nodes': [], 'calls': []})['nodes'].append(node)
    for call in calls:
        name = call.get('stage') or 'unassigned_llm'
        stages.setdefault(name, {'nodes': [], 'calls': []})['calls'].append(call)
    output = {}
    for name, group in stages.items():
        attempts, stage_calls = group['nodes'], group['calls']
        usage = summarize_usage(stage_calls)
        active = [node for node in attempts if node.get('status') == 'running']
        output[name] = {
            'attempts': len(attempts), 'completed_attempts': sum(node.get('status') == 'completed' for node in attempts),
            'failed_attempts': sum(node.get('status') == 'failed' for node in attempts),
            'recorded_running_attempts': len(active),
            'completed_cumulative_seconds': sum(node['duration_ms'] for node in attempts
                if node.get('status') != 'running' and _number(node.get('duration_ms'))) / 1000,
            'active_elapsed_seconds': sum(max(0, (now - _instant(node['started_at'])).total_seconds())
                for node in active if _instant(node.get('started_at'))),
            'llm_calls': len(stage_calls),
            'input_tokens_known': usage['fields']['input_tokens']['known_sum'],
            'cached_input_tokens_known': usage['fields']['cached_input_tokens']['known_sum'],
            'output_tokens_known': usage['fields']['output_tokens']['known_sum'],
            'known_total_tokens': usage['known_total_tokens'],
            'unknown_core_usage_calls': usage['unknown_core_usage_calls'],
        }
    return output


def _task_presentation(run_dir, task, oracle, nop):
    """Expose only selected public files and Harbor result JSON as links."""
    root = Path(run_dir).resolve()
    revision = _task_directory(root, task) / 'revisions' / f"{int(task.get('revision', 0) or 0):03d}"
    plan = _read_json(revision / 'private/plan.json', {})
    artifacts = {}
    for label, filename in [('instruction', 'instruction.md'), ('input', 'input.xlsx')]:
        candidate = (revision / 'public' / filename).resolve()
        if (candidate.is_file() and candidate.is_relative_to(root)
                and candidate.is_relative_to((revision / 'public').resolve())
                and not {part.lower() for part in candidate.relative_to(root).parts} & {'private', '.secrets'}):
            artifacts[label] = str(candidate)
    for label, record in [('oracle', oracle), ('nop', nop)]:
        candidate = Path(record.get('result_file') or '').resolve()
        if (candidate.is_file() and candidate.name == 'result.json' and candidate.is_relative_to(root)
                and not {part.lower() for part in candidate.relative_to(root).parts} & {'private', '.secrets'}):
            artifacts[label] = str(candidate)
    return {'title': task.get('title') or plan.get('title') or task['id'], 'artifacts': artifacts}


def _extra_calls(directories, excluded_ids):
    calls, seen, records = [], set(excluded_ids), []
    for location in directories or []:
        directory = Path(location).resolve()
        if (directory / 'run.sqlite').is_file():
            candidates = read_run(directory)['calls']
        else:
            candidates = [_read_json(path, {}) for path in directory.rglob('result.json')]
            candidates = [record for record in candidates if record.get('call_id') and record.get('model')]
        selected = []
        for call in candidates:
            key = call.get('call_id')
            if key and key not in seen:
                seen.add(key)
                selected.append(call)
        calls.extend(selected)
        records.append({'directory': str(directory), 'exists': directory.is_dir(), 'deduplicated_calls': len(selected)})
    status = ('not_requested' if not directories else
              'partial_missing_directories' if any(not item['exists'] for item in records) else 'collected')
    return {'directories': records, 'status': status, 'usage': summarize_usage(calls),
            'scope': '显式提供的工程或试跑目录；按 call_id 去重，排除正式运行调用，不与正式运行相加归因。'}


def _request_log_window(run_dir):
    """Copy only approved aggregate fields, never the private billing ledger."""
    raw = _read_json(Path(run_dir) / 'private/billing_snapshots/summary.json')
    result = {'status': 'unavailable',
              'attribution': 'shared_api_key_created_at_window_not_exact_run_attribution',
              'production_cost_usd': None, 'window': {}, 'quota_per_usd': None,
              'totals': {}, 'by_model': {}, 'coverage': {}, 'capture': {},
              'notes': [
                  '按服务端请求 created_at 选择同 key 时间窗，会纳入窗口内 pilot、工程试跑和其他重叠请求；不能精确归因本次 run。',
                  '运行中请求、延迟入账或尚未返回的日志可能遗漏；观察区间覆盖不等于账单完整或已结算。',
                  '服务端请求数不同于 CLI 调用数，一次 agent 调用可以发起多次请求。']}
    if not isinstance(raw, dict):
        result['notes'].append('请求日志汇总尚不可用，未将缺失费用记为零。')
        return result

    def nonnegative(value):
        return value if _number(value) and Decimal(str(value)).is_finite() and value >= 0 else None

    def totals(value):
        if not isinstance(value, dict):
            return {}
        return {name: nonnegative(value.get(name)) for name in (
            'requests', 'quota', 'usd', 'prompt_tokens', 'completion_tokens',
            'cache_read_tokens', 'uncached_prompt_tokens', 'total_tokens')}

    window = raw.get('window') or {}
    for name in ('start', 'end_exclusive'):
        stamp = _instant(window.get(name)) if isinstance(window, dict) else None
        if stamp:
            result['window'][name] = stamp.isoformat()
    unit = nonnegative(raw.get('quota_per_usd'))
    result['quota_per_usd'] = unit if unit else None
    result['totals'] = totals(raw.get('totals'))
    models = raw.get('by_model') or {}
    for model, value in (models if isinstance(models, dict) else {}).items():
        if isinstance(model, str):
            result['by_model'][model] = totals(value)
    coverage = raw.get('coverage') or {}
    coverage = coverage if isinstance(coverage, dict) else {}
    for name in ('observed_intervals_cover_window', 'window_start_observed', 'server_total_unknown',
                 'in_flight_or_delayed_logs_may_be_missing', 'exact_billing_completeness_certified'):
        value = coverage.get(name)
        if isinstance(value, bool):
            result['coverage'][name] = value
    capture = raw.get('capture') or {}
    capture = capture if isinstance(capture, dict) else {}
    stamp = _instant(capture.get('captured_at'))
    if stamp:
        result['capture']['captured_at'] = stamp.isoformat()
    for name in ('duration_seconds', 'unique_ledger_events', 'snapshots'):
        result['capture'][name] = nonnegative(capture.get(name))
    result['status'] = ('measured_request_log_window' if result['totals'].get('usd') is not None
                        else 'summary_available_cost_unknown')
    quota, dollars = result['totals'].get('quota'), result['totals'].get('usd')
    if quota is not None and unit and dollars is not None:
        derived = Decimal(str(quota)) / Decimal(str(unit))
        if abs(derived - Decimal(str(dollars))) > Decimal('0.000001'):
            result['totals']['usd'] = None
            result['status'] = 'summary_available_cost_unknown'
            result['notes'].append('汇总美元数与 quota / quota_per_usd 不一致，未展示未经证实的美元费用。')
    for model, values in result['by_model'].items():
        quota, dollars = values.get('quota'), values.get('usd')
        if quota is not None and unit and dollars is not None:
            if abs(Decimal(str(quota)) / Decimal(str(unit)) - Decimal(str(dollars))) > Decimal('0.000001'):
                values['usd'] = None
                result['notes'].append('某模型的美元汇总与 quota 换算不一致，该模型费用保持未知。')
    return result


def billing_window(run_dir, run, scope_note=None):
    private = Path(run_dir) / 'private'
    start = _read_json(private / 'billing_start.json')
    end = _read_json(private / 'billing_end.json')
    context = _read_json(private / 'billing_context.json', {})
    notes = [scope_note or context.get('scope_note') or
        '该凭据计费窗口可能包含并行工程、试跑和未记录的取消请求；没有逐调用账单，不能等同正式管线费用。']
    overlap_end = context.get('overlap_ended_at')
    if overlap_end:
        notes.append('已知最初一段工程或试跑重叠至 ' + (_display_time(overlap_end) or str(overlap_end))
                     + '；这不证明此后没有其他共享凭据流量。')
    result = {'scope': 'credential_time_window_only', 'production_cost_usd': None,
              'quota_delta': None, 'cost_usd': None, 'quota_per_usd': None,
              'start_captured_at': start.get('captured_at') if start else None,
              'end_captured_at': end.get('captured_at') if end else None,
              'notes': notes, 'status': 'unavailable',
              'request_log_window': _request_log_window(run_dir),
              'methods_additive': False,
              'methods_note': '快照差额与请求日志时间窗是两种不同观察方法，不能相加，也不能混作精确 run 归因。'}
    if not start or not end:
        notes.append('缺少开始或结束账单快照，快照差额费用未知。')
        return result
    before = (start.get('usage') or {}).get('data') or {}
    after = (end.get('usage') or {}).get('data') or {}
    initial, final = before.get('total_used'), after.get('total_used')
    currency = start.get('currency_metadata') or {}
    end_currency = end.get('currency_metadata') or currency
    unit = currency.get('quota_per_unit')
    end_unit = end_currency.get('quota_per_unit')
    display = str(currency.get('quota_display_type', '')).upper()
    if not (_number(initial) and _number(final) and final >= initial and _number(unit) and unit > 0
            and unit == end_unit and display == 'USD'
            and str(end_currency.get('quota_display_type', '')).upper() == 'USD'):
        result['status'] = 'invalid_or_unsupported_snapshot'
        notes.append('快照计数、币种或换算单位不一致，未推算美元费用。')
        return result
    delta = Decimal(str(final)) - Decimal(str(initial))
    result.update(status='measured_key_window', quota_delta=int(delta) if delta == int(delta) else float(delta),
                  quota_per_usd=unit, cost_usd=float(delta / Decimal(str(unit))))
    started, captured = _instant(run.get('started_at')), _instant(start.get('captured_at'))
    if started and captured and captured > started:
        notes.append(f'开始快照晚于管线启动 {(captured - started).total_seconds():.1f} 秒，未覆盖这一段正式运行。')
    result['formula'] = 'cost_usd = (end.total_used - start.total_used) / quota_per_unit；不乘 usd_exchange_rate。'
    return result


def _harbor_entry(task, all_controls, agent):
    entry = (task.get('harbor_controls') or {}).get(agent)
    if not isinstance(entry, dict):
        per_task = all_controls.get('per_task', {})
        entry = per_task.get('sheetsfactory/' + task['id'], per_task.get(task['id'], {})).get(agent)
    expected = 1 if agent == 'oracle' else 0
    if not isinstance(entry, dict):
        return {'reward': None, 'matched': False, 'evidence_available': False}
    reward = entry.get('reward')
    valid = (_number(reward) and reward == expected and entry.get('matched') is True
             and not entry.get('exception_info'))
    return {'reward': reward, 'matched': valid, 'evidence_available': True,
            'result_file': entry.get('result_file'), 'has_exception': bool(entry.get('exception_info'))}


def _task_directory(run_dir, task):
    root = Path(run_dir).resolve()
    candidate = (root / 'tasks' / task['id']).resolve()
    if not candidate.is_relative_to(root / 'tasks'):
        raise ValueError('Task ID escapes the task artifact directory')
    return candidate


def _recovery(run_dir, task):
    revision = int(task.get('revision', 0) or 0)
    path = _task_directory(run_dir, task) / 'revisions' / f'{revision:03d}' / 'private/independent_recovery.json'
    record = _read_json(path)
    if not record:
        return {'verified': False, 'artifact_available': False, 'artifact': str(path)}
    replay = record.get('replay') or {}
    valid = (record.get('verified') is True and record.get('public_information_only') is True
             and (record.get('comparison') or {}).get('reward') == 1 and replay.get('returncode') == 0)
    return {'verified': valid, 'artifact_available': True, 'artifact': str(path),
            'status': record.get('status', 'verified' if valid else 'unverified'),
            'public_information_only': record.get('public_information_only'),
            'replay_returncode': replay.get('returncode'),
            'comparison_reward': (record.get('comparison') or {}).get('reward')}


def _reference_file(path, base):
    path, base = Path(path).absolute(), Path(base).resolve()
    if (not path.is_relative_to(base) or not path.resolve().is_relative_to(base)
            or any(part.is_symlink() for part in (path, *path.parents) if part.is_relative_to(base))):
        raise ValueError('Reference evidence escapes its revision directory')
    return path.read_bytes()


def _reference_review(run_dir, task):
    """Check current review receipts without inventing a public recovery proof."""
    # Local import keeps the reporting module usable during pipeline/node import.
    from types import SimpleNamespace
    from .nodes.quality import reference_revision_binding, reference_review_assessments
    base = _task_directory(run_dir, task) / 'revisions' / f"{int(task.get('revision', 0) or 0):03d}"
    path = base / 'private/reference_review.json'
    result = {'method': 'reference_review', 'verified': False, 'status': 'unverified',
              'independent_public_recovery': False, 'artifact': str(path), 'artifact_available': path.is_file()}
    try:
        public = _reference_file(base / 'public/input.xlsx', base)
        instruction = _reference_file(base / 'public/instruction.md', base)
        goal = _reference_file(base / 'private/goal.xlsx', base)
        revision_hash = hashlib.sha256(public + instruction).hexdigest()
        binding = reference_revision_binding(SimpleNamespace(task_id=task['id'], revision=int(task.get('revision', 0) or 0),
            data={'input': base / 'public/input.xlsx', 'goal': base / 'private/goal.xlsx',
                  'instruction': instruction.decode(), 'revision_hash': revision_hash}))
        diagnosis = json.loads(_reference_file(base / 'private/diagnosis.json', base))
        recovery = json.loads(_reference_file(base / 'private/independent_recovery.json', base))
        receipt = json.loads(_reference_file(path, base))
        support = reference_review_assessments(diagnosis, binding)
        if not (support['passed'] and diagnosis.get('reference_evidence_policy') == 'reference_review'
                and diagnosis.get('reference_validation_method') == 'reference_review'
                and diagnosis.get('reference_binding') == binding
                and diagnosis.get('task_revision_hash') == revision_hash
                and (not task.get('revision_hash') or task['revision_hash'] == revision_hash)
                and len(diagnosis.get('enabled_check_ids', [])) == 12
                and set(diagnosis['enabled_check_ids']) == {f'Q{n:02d}' for n in range(1, 13)}
                and not diagnosis.get('disabled_check_ids')
                and receipt == diagnosis.get('reference_review') and receipt.get('passed') is True
                and receipt.get('binding') == binding and receipt.get('q04_receipt') == support['q04_receipt']
                and receipt.get('diagnostic_run_id') == diagnosis.get('diagnostic_run_id')
                and receipt.get('check_plan_hash') == diagnosis.get('check_plan_hash')
                and recovery.get('verified') is False and recovery.get('public_information_only') is False
                and recovery.get('status') == 'not_applicable' and recovery.get('binding') == binding):
            raise ValueError('Current supported reference-review binding is missing or stale')
        names = {'edit_validation.json', 'expected_delta.json', 'native_error_probe.json',
                 'native_risk_guard.json', 'local_controls.json', 'reference_evidence_context.json'}
        if set(receipt.get('artifacts', {})) != names:
            raise ValueError('Reference-review evidence artifacts are incomplete')
        artifacts = {}
        for name, recorded in receipt['artifacts'].items():
            artifact = base / 'private' / name
            raw = _reference_file(artifact, base)
            if recorded != {'path': str(artifact.resolve()), 'sha256': hashlib.sha256(raw).hexdigest()}:
                raise ValueError('Reference-review evidence artifact changed: ' + name)
            artifacts[name] = json.loads(raw)
        context = artifacts['reference_evidence_context.json']
        native = artifacts['native_error_probe.json']
        financial = context.get('financial_validation', {})
        controls = artifacts['local_controls.json']
        if not (context.get('binding') == binding
                and any(context.get('source_business_evidence', {}).get(k) for k in ('source_assessment', 'finance_evidence'))
                and financial.get('construction') == artifacts['edit_validation.json']
                and financial.get('local_controls') == controls
                and all(financial.get('engine_report', {}).get(k) is True for k in ('normalization_ok', 'recalculation_ok', 'stable'))
                and native.get('blocking') is False and native.get('goal_sha256') == binding['goal_sha256']
                and native.get('revision') == binding['revision']
                and set(native.get('required_delta', [])) == set(artifacts['expected_delta.json'].get('expected_changes', []))
                and artifacts['native_risk_guard.json'].get('blocking') is False
                and all(controls.get(k, {}).get('reward') == value for k, value in
                        (('oracle', 1), ('nop', 0), ('equivalent', 1), ('missed_root', 0), ('extra_change', 0)))):
            raise ValueError('Reference-review business, financial or native-error evidence is incomplete')
        batches = diagnosis.get('llm_batches', [])
        public_checks, private_checks = set(), set()
        for batch in batches:
            visibility = batch.get('visibility')
            if batch.get('status') != 'completed' or visibility not in {'public_only', 'review'}:
                raise ValueError('Reference-review diagnostic batch did not complete')
            origin = batch.get('origin_diagnostic_run_id') if batch.get('cache_hit') is True else diagnosis.get('diagnostic_run_id')
            matched = False
            pattern = 'diagnostic_public-*/evidence.json' if visibility == 'public_only' else 'diagnostic_private-*/evidence.json'
            for evidence_path in base.glob(pattern):
                evidence = json.loads(_reference_file(evidence_path, base))
                if not (evidence.get('visibility') == visibility and evidence.get('diagnostic_run_id') == origin
                        and evidence.get('task_revision_hash') == revision_hash
                        and evidence.get('check_plan_hash') == diagnosis.get('check_plan_hash')
                        and evidence.get('assigned_check_ids') == batch.get('assigned_check_ids')):
                    continue
                stable = {key: value for key, value in evidence.items() if key != 'diagnostic_run_id'}
                digest = hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
                if (batch.get('payload_digest') != digest
                        or _reference_file(evidence_path.parent / 'input.xlsx', base) != public
                        or _reference_file(evidence_path.parent / 'instruction.md', base) != instruction):
                    raise ValueError('Diagnostic batch public evidence differs from current revision')
                if visibility == 'review':
                    private = evidence.get('private', {})
                    if not (private.get('goal_sha256') == binding['goal_sha256']
                            and private.get('independent_recovery') == recovery
                            and private.get('reference_review_context') == context
                            and _reference_file(evidence_path.parent / 'reference.xlsx', base) == goal):
                        raise ValueError('Diagnostic reference evidence differs from current goal')
                (public_checks if visibility == 'public_only' else private_checks).update(batch['assigned_check_ids'])
                matched = True
                break
            if not matched:
                raise ValueError('Matching actual diagnostic batch evidence is missing')
        if not public_checks >= {'Q01', 'Q02', 'Q03'} or 'Q04' not in private_checks:
            raise ValueError('Public sufficiency and private financial review receipts are missing')
        result.update(verified=True, status='passed', binding=binding,
            financial_check_count=len(support['q04_receipt']['financial_validation_checks']),
            verification_scope='current_hash_bound_diagnostic_review')
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        result['reason'] = str(error)
    return result


def _quality_diagnosis(run_dir, task):
    path = _task_directory(run_dir, task) / 'revisions' / f"{int(task.get('revision', 0) or 0):03d}" / 'private/diagnosis.json'
    record = _read_json(path)
    if not record:
        return {'verified': False, 'artifact_available': False, 'artifact': str(path), 'scope': None}
    enabled = record.get('enabled_check_ids', [])
    assessments = record.get('assessments') or {}
    complete = bool(enabled) and all(assessments.get(check, {}).get('state') in
                                    {'clear', 'flagged', 'not_applicable'} for check in enabled)
    coverage = record.get('coverage') or {}
    valid = (record.get('releasable') is True and complete and not coverage.get('blocking_issue_ids')
             and not coverage.get('unknown_check_ids') and not coverage.get('undispositioned_warning_ids'))
    return {'verified': valid, 'artifact_available': True, 'artifact': str(path),
            'scope': record.get('scope'), 'enabled_check_count': len(enabled)}


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def generate_report(run_dir, *, project_root=None, engineering_dirs=None, billing_scope_note=None, now=None):
    run_dir = Path(run_dir).resolve()
    project_root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[2]
    snapshot = read_run(run_dir)
    run, tasks, nodes, calls = (snapshot[key] for key in ('run', 'tasks', 'nodes', 'calls'))
    now = now or datetime.now(timezone.utc)
    if not now.tzinfo:
        now = now.replace(tzinfo=timezone.utc)
    recorded_call_count = len(calls)
    calls = _observed_calls(calls, snapshot['events'], run, now)
    usage = summarize_usage(calls)
    usage.update(recorded_call_count=recorded_call_count,
                 active_call_count=sum(call.get('status') == 'running' for call in calls),
                 completion_missing_count=sum(call.get('completion_missing', False) for call in calls),
                 note='调用数包含审计中已记录的请求开始；未完成或缺失结束记录的调用用量保持未知。')
    stages = _stage_accounting(nodes, calls, now)
    config_path = run_dir / 'resolved_config.yaml'
    config = yaml.safe_load(config_path.read_text()) if config_path.is_file() else {}
    from .nodes.quality import validate_reference_policy_selection
    try:
        policy = validate_reference_policy_selection(config)
    except (OSError, ValueError, TypeError):
        policy = 'invalid'
    manifest_path = Path((config.get('run') or {}).get('seed_manifest', 'data/manifests/euses_financial.json'))
    if not manifest_path.is_absolute():
        manifest_path = project_root / manifest_path
    manifest = _read_json(manifest_path, {})
    preparation = (_read_json(project_root / 'data/manifests/source_preparation_usage.json', {})
                   if manifest_path.resolve() == (project_root / 'data/manifests/euses_financial.json').resolve() else {})
    prep = preparation.get('all_source_preparation') or {}
    controls = _read_json(run_dir / 'harbor_controls.json', {})
    details, warnings = [], []
    for task in tasks:
        oracle, nop = _harbor_entry(task, controls, 'oracle'), _harbor_entry(task, controls, 'nop')
        recovery = _recovery(run_dir, task)
        diagnosis = _quality_diagnosis(run_dir, task)
        reference = (_reference_review(run_dir, task) if policy == 'reference_review' else
            {'method': policy, 'verified': recovery['verified'] if policy == 'independent_public_recovery' else False,
             'status': 'passed' if policy == 'independent_public_recovery' and recovery['verified'] else 'unverified'})
        verified = (task.get('status') == 'qualified' and oracle['matched'] and nop['matched']
                    and reference['verified'] and diagnosis['verified'])
        if task.get('status') == 'qualified' and not verified:
            warnings.append({'task_id': task['id'], 'code': 'QUALIFIED_EVIDENCE_MISMATCH',
                             'reason': '已标记 qualified，但 Harbor、诊断或参考验证证据不完整；未计入已核验产量。'})
        details.append({'task_id': task['id'], 'mode': task.get('mode'), 'source_id': task.get('source_id'),
                        'source': task.get('source'), 'status': task.get('status'), 'verified_qualified': verified,
                        'revision': int(task.get('revision', 0) or 0), 'variant': int(task.get('variant', 0) or 0),
                        **_task_presentation(run_dir, task, oracle, nop), 'error': task.get('error'),
                        'oracle': oracle, 'nop': nop, 'independent_recovery': recovery, 'diagnosis': diagnosis,
                        'reference_validation_method': policy, 'reference_validation': reference})
    qualified = [task for task in details if task['verified_qualified']]
    used_sources = {task['source_id'] for task in details if task.get('source_id')}
    productive_sources = {task['source_id'] for task in qualified if task.get('source_id')}
    constructed_tasks = {node.get('task_id') for node in nodes if node.get('node', node.get('node_id')) == 'construct'}
    built_sources = {task['source_id'] for task in details if task['task_id'] in constructed_tasks and task.get('source_id')}
    targets = (config.get('run') or {}).get('targets') or {
        'financial_modeling': run.get('financial_target', 20), 'debugging': run.get('debugging_target', 20)}
    actual = {mode: sum(task['mode'] == mode for task in qualified) for mode in targets}
    amendments = [event for event in snapshot['events'] if event['kind'] == 'run.amended']
    resumptions = [event for event in snapshot['events'] if event['kind'] == 'run.resumed']
    final_issue_counts, historical_issue_counts = Counter(), Counter()
    for task in tasks:
        final_issue_counts.update(issue.get('problem_id', 'unknown') for issue in task.get('issues', []))
        for path in _task_directory(run_dir, task).glob('revisions/*/private/diagnosis.json'):
            report = _read_json(path, {})
            historical_issue_counts.update(issue.get('problem_id', 'unknown') for issue in report.get('issues', []))
    rejection_codes = Counter()
    for task in details:
        if task['status'] == 'rejected':
            codes = set(re.findall(r'Q\d{2}|INFRA_FAILED|UNRESOLVED|EXHAUSTED', task.get('error') or ''))
            if not codes:
                message = (task.get('error') or '').lower()
                category = next((name for pattern, name in [
                    ('cross-sheet', 'NO_CROSS_SHEET'), ('planner rejected', 'PLAN_UNSUITABLE'),
                    ('source lacks', 'SOURCE_STRUCTURE'), ('repeats an existing', 'DUPLICATE_MODULE'),
                    ('duplicate', 'DUPLICATE_MODULE'), ('no evidence-supported repair', 'UNREPAIRABLE'),
                    ('unsupported', 'ENGINE_UNSUPPORTED')] if pattern in message), 'OTHER_OR_UNCLASSIFIED')
                codes = {category}
            rejection_codes.update(codes)
    revision_counts = Counter(task['revision'] for task in details)
    time_measures = _time_measures(run, now)
    node_seconds = sum(stage['completed_cumulative_seconds'] for stage in stages.values())
    return {
        'schema_version': '1.0', 'generated_at': now.isoformat(), 'generated_at_shanghai': _display_time(now.isoformat()),
        'run': {'id': run.get('id', run_dir.name), 'status': run.get('status'), 'directory': str(run_dir),
                'started_at': run.get('started_at'), 'started_at_shanghai': _display_time(run.get('started_at')),
                'code_revision': run.get('code_revision'), 'model': run.get('model'),
                'code_history': run.get('code_history', []), 'resume_count': run.get('resume_count', 0),
                'reasoning_effort': run.get('reasoning_effort'), 'difficulty_status': run.get('difficulty_status', 'unknown'),
                'reference_evidence_policy': policy,
                'difficulty_score': None, 'difficulty_note': '本轮只验题目质量，难度评测及低通过率目标延后；未报告正式模型 Pass@1。',
                'targets': targets, 'actual_verified_counts': actual,
                'target_met': all(actual[mode] >= count for mode, count in targets.items()),
                'is_final_snapshot': run.get('status') in FINAL_RUN_STATUSES,
                'is_live_snapshot': _run_is_live(run)},
        'sources': {'archive_scanned': manifest.get('unique_workbooks_inspected', run.get('discovered_sources')),
                    'selected_seed_pool': manifest.get('selected_count'), 'eligible_seed_pool': manifest.get('eligible_count'),
                    'additional_selected_seed_pool': run.get('additional_selected_sources', 0),
                    'merged_selected_seed_pool': run.get('selected_sources', manifest.get('selected_count')),
                    'preparation_attempted': prep.get('attempted_unique_sources', run.get('preprocess_attempted_sources')),
                    'preparation_readable_profiled': prep.get('readable_profiled'),
                    'preparation_zero_cached_errors': prep.get('zero_cached_errors'),
                    'construction_attempted_unique_seeds': len(used_sources),
                    'construct_node_reached_unique_seeds': len(built_sources),
                    'productive_unique_seeds': len(productive_sources),
                    'archive_sha256': manifest.get('archive_sha256', run.get('source_archive_sha256')),
                    'archive_url': manifest.get('download_url', run.get('source_archive')),
                    'manifest': str(manifest_path),
                    'used_seed_definition': '在正式运行中创建过任务候选的不同 source_id，包含早期拒绝；与构造节点实际到达数分列。'},
        'yield': {'candidates': len(tasks), 'reported_qualified': sum(task.get('status') == 'qualified' for task in tasks),
                  'verified_qualified': len(qualified), 'rejected': sum(task['status'] == 'rejected' for task in details),
                  'ready_pending_validation': sum(task['status'] == 'ready' for task in details),
                  'candidate_conversion': _ratio(len(qualified), len(tasks)),
                  'productive_source_conversion': _ratio(len(productive_sources), len(used_sources)),
                  'tasks_per_used_seed': _ratio(len(qualified), len(used_sources)),
                  'by_mode': {mode: {'target': targets[mode], 'qualified': actual[mode],
                      'candidates': sum(task['mode'] == mode for task in details)} for mode in targets}},
        'timing': {**time_measures, 'cumulative_node_seconds': node_seconds,
                   'node_attempt_count': len(nodes), 'running_node_count': sum(node.get('status') == 'running' for node in nodes),
                   'preparation_cumulative_seconds': prep.get('normalization_and_profile_cumulative_seconds'),
                   'preparation_wall_seconds': prep.get('first_survey_wall_seconds'),
                   'note': '端到端经过时间按 started_at 至当前结束时间或报告时间计算，包含阶段间停顿；'
                           'Producer 活跃阶段累计使用已记录的 run.wall_seconds，运行中仅在阶段起点与此前累计已知时补当前阶段。'
                           '两者不能相加，缺少所需时间证据时保持未知。旧 wall_seconds/wall_scope 仅保留兼容。'
                           '节点累计仅包含已结束尝试的记录耗时，运行中已过时间另列；并发累计不等于端到端经过时间，'
                           '也不用于反推它。阶段 Token 按调用 stage 归属，包含重试；只相加已知输入与输出，缓存已包含在输入中。预处理与正式运行分列。',
                   'by_node': {name: {'attempts': stage['attempts'],
                                     'cumulative_seconds': stage['completed_cumulative_seconds']}
                               for name, stage in stages.items() if stage['attempts']}},
        'stages': stages,
        'tokens': usage,
        'engineering_usage': _extra_calls(engineering_dirs, {call.get('call_id') for call in calls}),
        'billing': billing_window(run_dir, run, billing_scope_note),
        'diagnostics': {'final_issue_instances_by_code': dict(sorted(final_issue_counts.items())),
                        'revision_report_issue_observations_by_code': dict(sorted(historical_issue_counts.items())),
                        'rejected_candidates_by_reason': dict(sorted(rejection_codes.items())),
                        'candidate_final_revision_histogram': {str(key): value for key, value in sorted(revision_counts.items())},
                        'content_repair_revision_total': sum(task['revision'] for task in details),
                        'checker_execution_states': dict(Counter(event.get('state', 'unknown') for event in snapshot['events']
                            if event.get('kind') == 'checker.result')),
                        'qualified_diagnosis_scopes': dict(Counter(task['diagnosis'].get('scope') or 'unknown' for task in qualified)),
                        'note': '最终问题实例与各版本诊断观测分列；同一问题跨版本出现不当作多个独立根因。'},
        'change_history': {'amendments': amendments, 'resumptions': resumptions,
                           'note': '保留提示词澄清、代码阶段和来源池扩展的实际事件，不将多阶段运行伪装成单一冻结版本。'},
        'tasks': details, 'consistency_warnings': warnings,
    }


def _fmt(value, digits=2):
    if value is None:
        return '未知'
    if isinstance(value, float):
        return f'{value:,.{digits}f}'
    return str(value)


def _pct(value):
    return '未知' if value is None else f'{value:.2%}'


def _md(value):
    return escape(str(value if value is not None else '未知'), quote=False).replace('|', '\\|').replace('\n', ' ')


def _links_for_task(report, task, report_dir=None):
    root = Path(report['run']['directory']).resolve()
    directory = Path(report_dir).resolve() if report_dir else root / 'reports'
    links = []
    for key, label in [('instruction', '题面'), ('input', '输入'), ('oracle', 'Oracle 证据'), ('nop', 'Nop 证据')]:
        value = task.get('artifacts', {}).get(key)
        if not value:
            continue
        path = Path(value).resolve()
        if (not path.is_file() or not path.is_relative_to(root)
                or {part.lower() for part in path.relative_to(root).parts} & {'private', '.secrets'}):
            continue
        links.append((label, quote(os.path.relpath(path, directory), safe='/._-')))
    return links


def _snapshot_note(report):
    tokens = report['tokens']
    prefix = ('结束运行报告' if report['run']['is_final_snapshot'] else
              '进度快照，运行尚未结束' if report['run']['is_live_snapshot'] else '中断或暂停快照，Producer 未运行')
    return (prefix + f"；活动调用 {tokens.get('active_call_count', 0)} 次，已记录结束结果 "
            f"{tokens.get('recorded_call_count', tokens['call_count'])} 次，"
            f"核心用量未知 {tokens['unknown_core_usage_calls']} 次。已知 Token 不代表未完成请求的最终消耗。")


def _reference_status(task):
    method = task.get('reference_validation_method', 'independent_public_recovery')
    if method == 'reference_review':
        status = '通过' if task.get('reference_validation', {}).get('verified') else '未证实'
        return '参考复核：' + status + '（独立恢复未执行）'
    if method == 'independent_public_recovery':
        return '独立恢复：' + ('通过' if task['independent_recovery']['verified'] else '未证实')
    return '参考验证策略无效；未核验'


def markdown_report(report, report_dir=None):
    run, sources, output = report['run'], report['sources'], report['yield']
    lines = ['# sheetsFactory 运行报告', '', _snapshot_note(report), '',
             f"运行 `{run['id']}`；状态 **{run['status']}**；报告时间 {report['generated_at_shanghai']}。", '',
             f"已核验产出 **{output['verified_qualified']} 道**，候选 {output['candidates']} 道。"
             f"目标题量是否达到：{'是' if run['target_met'] else '否'}。", '', run['difficulty_note'], '',
             '## 题量与转化率', '', '| 指标 | 数值 |', '| --- | ---: |']
    for label, value in [
        ('归档中扫描的不同工作簿', sources['archive_scanned']), ('筛选进入种子池', sources['selected_seed_pool']),
        ('续跑显式补充种子数', sources['additional_selected_seed_pool']), ('合并后的种子池', sources['merged_selected_seed_pool']),
        ('预处理尝试种子数', sources['preparation_attempted']), ('预处理可读取并画像', sources['preparation_readable_profiled']),
        ('正式运行使用的不同种子', sources['construction_attempted_unique_seeds']),
        ('实际到达构造节点的不同种子', sources['construct_node_reached_unique_seeds']),
        ('贡献合格题目的种子', sources['productive_unique_seeds']), ('候选任务', output['candidates']),
        ('已核验合格任务', output['verified_qualified']), ('待 Harbor 验证', output['ready_pending_validation']),
        ('已拒绝候选', output['rejected']),
        ('候选转化率：合格题 / 候选题', _pct(output['candidate_conversion'])),
        ('源转化率：产题种子 / 使用种子', _pct(output['productive_source_conversion'])),
        ('平均每个使用种子的合格题数', _fmt(output['tasks_per_used_seed']))]:
        lines.append(f'| {label} | {_md(value)} |')
    lines += ['', sources['used_seed_definition'], '', '| 类别 | 目标 | 已核验合格 | 候选 |', '| --- | ---: | ---: | ---: |']
    for mode, row in output['by_mode'].items():
        lines.append(f"| {MODES.get(mode, mode)} | {row['target']} | {row['qualified']} | {row['candidates']} |")
    lines += ['', '## 时间与 Token', '',
              f"端到端经过时间：{_fmt(report['timing']['end_to_end_elapsed_seconds'])} 秒"
              f"（{report['timing']['end_to_end_elapsed_status']}）；Producer 活跃阶段累计："
              f"{_fmt(report['timing']['active_producer_cumulative_phase_seconds'])} 秒"
              f"（{report['timing']['active_producer_cumulative_phase_status']}）；节点累计："
              f"{_fmt(report['timing']['cumulative_node_seconds'])} 秒。", '', report['timing']['note'], '',
              '| 阶段 | 尝试次数 | 运行中 | 完成累计秒数 | 已知输入 | 输入中缓存 | 已知输出 | 用量未知调用 |',
              '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for stage, values in report.get('stages', {}).items():
        lines.append(f"| {_md(stage)} | {values['attempts']} | {values['recorded_running_attempts']} | "
                     f"{_fmt(values['completed_cumulative_seconds'])} | {values['input_tokens_known']:,} | "
                     f"{values['cached_input_tokens_known']:,} | {values['output_tokens_known']:,} | "
                     f"{values['unknown_core_usage_calls']} |")
    lines += ['', '| 用量 | 已知合计 | 用量未知的调用数 |', '| --- | ---: | ---: |']
    for name, value in report['tokens']['fields'].items():
        lines.append(f"| {name} | {value['known_sum']:,} | {value['unknown_call_count']} |")
    lines += ['', f"正式运行调用 {report['tokens']['call_count']} 次；已知输入加输出 "
              f"{report['tokens']['known_total_tokens']:,} token；核心用量不完整的调用 "
              f"{report['tokens']['unknown_core_usage_calls']} 次。", '', report['tokens']['reasoning_note'], '',
              '如存在未知用量，已知合计只是已记录部分，不代表总消耗为零或已完整计量。', '',
              (f"单列工程/试跑调用 {report['engineering_usage']['usage']['call_count']} 次，已知 token "
               f"{report['engineering_usage']['usage']['known_total_tokens']:,}；未混入正式运行统计。"
               if report['engineering_usage']['status'] != 'not_requested' else
               '未提供工程/试跑审计目录，额外用量未知；没有把它当成零消耗。'), '',
              '## 费用口径', '',
              f"方法一，凭据起止快照差额：{('$' + _fmt(report['billing']['cost_usd'], 6)) if report['billing']['cost_usd'] is not None else '未知'}。", '']
    lines += ['- ' + note for note in report['billing']['notes']]
    log = report['billing'].get('request_log_window') or {}
    log_totals = log.get('totals') or {}
    log_window = log.get('window') or {}
    log_dollars = log_totals.get('usd')
    lines += ['', f"方法二，同 key 按请求 created_at 时间窗：{('$' + _fmt(log_dollars, 6)) if log_dollars is not None else '未知'}。", '',
              '窗口：' + (_display_time(log_window.get('start')) or '未知') + ' 至 '
              + (_display_time(log_window.get('end_exclusive')) or '未知') + '（结束不含）。', '',
              f"服务端请求 {_fmt(log_totals.get('requests'))} 次；quota {_fmt(log_totals.get('quota'))}；"
              f"输入 {_fmt(log_totals.get('prompt_tokens'))}，其中缓存 {_fmt(log_totals.get('cache_read_tokens'))}；"
              f"输出 {_fmt(log_totals.get('completion_tokens'))} token。缓存不重复相加。", '']
    lines += ['- ' + note for note in log.get('notes', [])]
    if log.get('by_model'):
        lines += ['', '| 日志窗口模型 | 请求 | 美元 | 输入 Token | 其中缓存 | 输出 Token |',
                  '| --- | ---: | ---: | ---: | ---: | ---: |']
        for model, totals in log['by_model'].items():
            lines.append(f"| {_md(model)} | {_fmt(totals.get('requests'))} | {_fmt(totals.get('usd'), 6)} | "
                         f"{_fmt(totals.get('prompt_tokens'))} | {_fmt(totals.get('cache_read_tokens'))} | "
                         f"{_fmt(totals.get('completion_tokens'))} |")
    lines += ['', report['billing'].get('methods_note', ''), '正式管线的精确归因费用：未知。', '']
    lines += ['', '## 诊断与修复', '', '| 问题编号 | 最终实例 | 版本诊断观测 |', '| --- | ---: | ---: |']
    diagnostics = report['diagnostics']
    for code in sorted(set(diagnostics['final_issue_instances_by_code']) | set(diagnostics['revision_report_issue_observations_by_code'])):
        lines.append(f"| {code} | {diagnostics['final_issue_instances_by_code'].get(code, 0)} | "
                     f"{diagnostics['revision_report_issue_observations_by_code'].get(code, 0)} |")
    lines += ['', f"累计内容修复版本数：{diagnostics['content_repair_revision_total']}。", '',
              '合格任务的诊断范围：`' + json.dumps(diagnostics['qualified_diagnosis_scopes'], ensure_ascii=False) + '`。', '',
              '拒绝原因计数：`' + json.dumps(diagnostics['rejected_candidates_by_reason'], ensure_ascii=False) + '`。', '',
              '## 逐题证据', '', '| 任务 / 题目 | 类别 | 状态 | Oracle | Nop | 参考验证 | 核验合格 | 文件 |',
              '| --- | --- | --- | ---: | ---: | --- | --- | --- |']
    for task in report['tasks']:
        title = _md(task.get('title', task['task_id'])).replace('[', '\\[').replace(']', '\\]')
        links = ' · '.join(f'[{label}]({href})' for label, href in _links_for_task(report, task, report_dir))
        lines.append(f"| {_md(task['task_id'])} / {title} | {_md(task['mode'])} | {_md(task['status'])} | "
            f"{_md(task['oracle']['reward'])} | {_md(task['nop']['reward'])} | "
            f"{_md(_reference_status(task))} | {'是' if task['verified_qualified'] else '否'} | {links} |")
    failures = [task for task in report['tasks'] if task.get('error')]
    if failures:
        lines += ['', '## 拒绝与失败样例', '']
        lines += [f"- `{task['task_id']}`：{_md(task['error'])}" for task in failures[:12]]
    if report['consistency_warnings']:
        lines += ['', '## 证据一致性警告', '']
        lines += [f"- `{item['task_id']}`：{item['reason']}" for item in report['consistency_warnings']]
    lines += ['', '## 复现与范围', '',
              f"代码版本：`{run.get('code_revision') or '未知'}`；模型 `{run.get('model') or '未知'}`，"
              f"reasoning `{run.get('reasoning_effort') or '未知'}`。", '',
              '```bash', 'harbor run -p "' + str(Path(run['directory']) / 'SpreadsheetEval') + '" -a oracle',
              'harbor run -p "' + str(Path(run['directory']) / 'SpreadsheetEval') + '" -a nop', '```', '',
              '报告仅从审计数据库与产物读取，不修改题目状态；真实执行结果见逐题 Harbor 证据。'
              '未执行的控制、缺失用量和延期难度评测均不补造通过结论。', '']
    changes = report.get('change_history') or {}
    if changes.get('amendments') or changes.get('resumptions'):
        lines += ['## 运行修订与续跑记录', '', changes['note'], '']
        for event in changes.get('amendments', []):
            lines.append(f"- {_display_time(event.get('timestamp'))}：{_md(event.get('reason', event.get('amendment', '显式修订')))}")
            if event.get('before_sha256') or event.get('after_sha256'):
                lines.append(f"  文件 `{_md(event.get('file'))}`；SHA `{event.get('before_sha256')}` → `{event.get('after_sha256')}`。")
        for event in changes.get('resumptions', []):
            lines.append(f"- {_display_time(event.get('timestamp'))}：同一运行续跑，保留 {event.get('preserved_task_count')} 个任务记录；"
                         f"代码 `{event.get('previous_code_revision')}` → `{event.get('current_code_revision')}`。")
        lines += ['']
    return '\n'.join(lines)


def html_report(report, report_dir=None):
    run, output = report['run'], report['yield']
    rows = []
    for task in report['tasks']:
        title = escape(str(task.get('title') or task['task_id']))
        links = ' · '.join('<a href="' + escape(href, quote=True) + '">' + label + '</a>'
                           for label, href in _links_for_task(report, task, report_dir))
        cells = ['<td>' + escape(str(task['task_id'])) + '<br><small>' + title + '</small></td>']
        cells.extend('<td>' + escape(str(value)) + '</td>' for value in [
            MODES.get(task['mode'], task['mode']), task['status'],
            _fmt(task['oracle']['reward']), _fmt(task['nop']['reward']),
            _reference_status(task),
            '是' if task['verified_qualified'] else '否', task.get('error') or ''])
        cells.append('<td>' + links + '</td>')
        rows.append('<tr>' + ''.join(cells) + '</tr>')
    rows = ''.join(rows)
    cards = [('已核验题量', str(output['verified_qualified'])), ('候选数', str(output['candidates'])),
             ('候选转化率', _pct(output['candidate_conversion'])),
             ('使用种子数', str(report['sources']['construction_attempted_unique_seeds'])),
             ('端到端经过秒数', _fmt(report['timing']['end_to_end_elapsed_seconds'])),
             ('Producer 活跃阶段累计秒数', _fmt(report['timing']['active_producer_cumulative_phase_seconds'])),
             ('已知 Token', f"{report['tokens']['known_total_tokens']:,}"),
             ('待 Harbor 验证', str(output['ready_pending_validation']))]
    for mode, values in output['by_mode'].items():
        cards.append((MODES.get(mode, mode), str(values['qualified']) + ' / ' + str(values['target'])))
    cards_html = ''.join(f'<article><span>{escape(label)}</span><strong>{escape(value)}</strong></article>' for label, value in cards)
    notes = ''.join('<li>' + escape(note) + '</li>' for note in report['billing']['notes'])
    billing_log = report['billing'].get('request_log_window') or {}
    billing_log_totals = billing_log.get('totals') or {}
    billing_log_dollars = billing_log_totals.get('usd')
    billing_log_window = billing_log.get('window') or {}
    log_notes = ''.join('<li>' + escape(note) + '</li>' for note in billing_log.get('notes', []))
    log_range = ((_display_time(billing_log_window.get('start')) or '未知') + ' 至 '
                 + (_display_time(billing_log_window.get('end_exclusive')) or '未知') + '（结束不含）')
    log_models = ''.join('<tr>' + ''.join('<td>' + escape(str(value)) + '</td>' for value in [
        model, _fmt(values.get('requests')), _fmt(values.get('usd'), 6),
        _fmt(values.get('prompt_tokens')), _fmt(values.get('cache_read_tokens')),
        _fmt(values.get('completion_tokens'))]) + '</tr>' for model, values in billing_log.get('by_model', {}).items())
    stage_rows = ''.join('<tr>' + ''.join('<td>' + escape(str(value)) + '</td>' for value in [
        name, stage['attempts'], stage['recorded_running_attempts'], _fmt(stage['completed_cumulative_seconds']),
        f"{stage['input_tokens_known']:,}", f"{stage['cached_input_tokens_known']:,}",
        f"{stage['output_tokens_known']:,}", stage['unknown_core_usage_calls']]) + '</tr>'
        for name, stage in report.get('stages', {}).items())
    # Embed an escaped text report for full offline inspection, not raw JSON in
    # an executable script. No CDN, network request or remote font is needed.
    return f'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>sheetsFactory 运行报告</title><style>
body{{font:15px/1.6 system-ui,sans-serif;margin:32px auto;padding:0 20px;max-width:1400px;color:#17212f;background:#f5f7fa}}
h1{{font-size:28px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}
article{{background:white;border:1px solid #dce2e8;border-radius:12px;padding:20px}}article span{{display:block;color:#536171}}strong{{font-size:26px}}
.notice{{padding:14px;background:#fff5da;border-left:4px solid #b78a00}}section{{margin:24px 0}}input{{padding:10px;min-width:280px}}
.table{{overflow:auto}}table{{border-collapse:collapse;background:white;width:100%}}td,th{{padding:10px;border-bottom:1px solid #e3e8ed;text-align:left;vertical-align:top}}th{{white-space:nowrap}}td:last-child{{min-width:240px}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:20px;border:1px solid #dce2e8}}small{{color:#536171}}
</style><h1>sheetsFactory 运行报告</h1><p>{escape(str(run['id']))} · {escape(str(run['status']))} · {escape(report['generated_at_shanghai'] or '')}</p>
<p class="notice">{escape(_snapshot_note(report))}</p><div class="cards">{cards_html}</div><p>{escape(run['difficulty_note'])}</p>
<section><h2>阶段耗时与用量</h2><p><small>{escape(report['timing']['note'])}</small></p><div class="table"><table><thead><tr>
<th>阶段</th><th>尝试</th><th>运行中</th><th>完成累计秒数</th><th>已知输入 Token</th><th>输入中缓存</th><th>已知输出</th><th>用量未知调用</th></tr></thead><tbody>{stage_rows}</tbody></table></div></section>
<section><h2>费用口径</h2>
<p>方法一，凭据起止快照差额：{escape('$' + _fmt(report['billing']['cost_usd'], 6) if report['billing']['cost_usd'] is not None else '未知')}。</p><ul>{notes}</ul>
<p>方法二，同 key 按请求 created_at 时间窗：<b>{escape('$' + _fmt(billing_log_dollars, 6) if billing_log_dollars is not None else '未知')}</b>。</p>
<p><small>{escape(log_range)}；服务端请求 {escape(_fmt(billing_log_totals.get('requests')))} 次。</small></p><ul>{log_notes}</ul>
<div class="table"><table><thead><tr><th>日志窗口模型</th><th>请求</th><th>美元</th><th>输入 Token</th><th>其中缓存</th><th>输出 Token</th></tr></thead><tbody>{log_models}</tbody></table></div>
<p class="notice">{escape(report['billing'].get('methods_note', ''))} 正式管线精确归因费用：未知。</p></section>
<section><h2>逐题证据</h2><input id="filter" placeholder="筛选任务、类别、状态或错误" aria-label="筛选任务"><div class="table"><table id="tasks"><thead><tr>
<th>任务 / 题目</th><th>类别</th><th>状态</th><th>Oracle</th><th>Nop</th><th>参考验证</th><th>核验合格</th><th>失败原因</th><th>公开文件与控制证据</th></tr></thead><tbody>{rows}</tbody></table></div></section>
<details><summary>完整统计、指标定义和复现命令</summary><pre>{escape(markdown_report(report, report_dir))}</pre></details>
<script>document.getElementById('filter').addEventListener('input',function(){{let q=this.value.toLowerCase();document.querySelectorAll('#tasks tbody tr').forEach(function(r){{r.hidden=!r.textContent.toLowerCase().includes(q);}});}});</script>
</html>'''


def write_reports(run_dir, output_dir=None, **kwargs):
    report = generate_report(run_dir, **kwargs)
    directory = Path(output_dir) if output_dir else Path(run_dir) / 'reports'
    directory.mkdir(parents=True, exist_ok=True)
    paths = {'json': directory / 'report.json', 'markdown': directory / 'report.zh-CN.md', 'html': directory / 'report.html'}
    paths['json'].write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    paths['markdown'].write_text(markdown_report(report, directory))
    paths['html'].write_text(html_report(report, directory))
    return {'paths': {name: str(path.resolve()) for name, path in paths.items()}, 'report': report}
