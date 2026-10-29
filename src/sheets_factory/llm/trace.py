"""Read isolated rollout receipts without confusing an attempt budget with task quality."""
from __future__ import annotations

import json
from pathlib import Path


def _fatal_provider_event(event):
    kind = event.get('type')
    if isinstance(event.get('item'), dict) and event['item'].get('type') == 'error':
        return True
    if kind == 'turn.failed' or event.get('error_category') in {'infrastructure', 'service', 'mount', 'process_failure'}:
        return True
    if kind != 'error':
        return False
    if event.get('retrying') is True or event.get('will_retry') is True:
        return False
    # A top-level CLI error is backend execution evidence. Errors produced by a
    # command under investigation remain ordinary item events, not root errors.
    return True


def _progress_event(event):
    item = event.get('item')
    if not isinstance(item, dict):
        usage = event.get('usage') or {}
        return event.get('type') == 'turn.completed' and isinstance(usage, dict) and (usage.get('output_tokens') or 0) > 0
    if event.get('type') not in {'item.started', 'item.updated', 'item.completed'}:
        return False
    kind = item.get('type')
    if kind in {'command_execution', 'mcp_tool_call', 'web_search', 'file_change'}:
        return any(item.get(key) for key in ('command', 'tool', 'name', 'query', 'changes', 'arguments', 'aggregated_output'))
    if kind in {'reasoning', 'agent_message', 'todo_list'}:
        return bool(item.get('text') or item.get('summary') or item.get('items'))
    return False


def recover_failed_attempt(error, *, task_id, workspace):
    """Return ungraded partial events only from a matching public isolated call."""
    result = {'events': [], 'call_id': getattr(error, 'call_id', ''), 'observations': []}
    record_path = getattr(error, 'record_path', '')
    if not record_path:
        return {**result, 'infrastructure_error': str(error), 'backend_record_verified': False}
    try:
        directory = Path(record_path)
        record = json.loads((directory / 'result.json').read_text())
        if (record.get('isolated') is not True or record.get('role') != 'trace_agent'
            or record.get('task_id') != task_id or record.get('stage') != 'trajectory'
            or Path(record.get('workspace', '')).resolve() != Path(workspace).resolve()
            or (result['call_id'] and record.get('call_id') != result['call_id'])):
            raise ValueError('Failed-call receipt does not identify this isolated public rollout')
        for line in (directory / 'events.jsonl').read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                result['events'].append(event)
        result.update(call_id=record.get('call_id', result['call_id']), duration_ms=record.get('duration_ms'),
                      backend_failure_kind=record.get('failure_kind'), backend_record_verified=True)
        messages = [event['item'].get('text', '') for event in result['events']
                    if event.get('type') == 'item.completed' and isinstance(event.get('item'), dict)
                    and event['item'].get('type') == 'agent_message']
        if messages:
            result['reply'] = messages[-1]
        progress = sum(_progress_event(event) for event in result['events'])
        fatal = any(_fatal_provider_event(event) for event in result['events'])
        if record.get('failure_kind') == 'timeout' and progress and not fatal:
            result['observations'].append({'kind': 'attempt_budget_exhausted',
                'timeout_seconds': record.get('timeout_seconds'), 'progress_event_count': progress,
                'reason': 'Ungraded rollout reached its execution budget after observable model/tool progress.'})
            result['attempt_budget_exhausted'] = True
        else:
            result['infrastructure_error'] = record.get('error') or str(error)
            result['infrastructure_cause_unknown'] = record.get('failure_kind') == 'timeout' and not progress and not fatal
        return result
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return {**result, 'infrastructure_error': 'Could not verify the failed public rollout record: ' + str(exc),
                'backend_record_verified': False}
