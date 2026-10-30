"""Account actual tool execution from native, timestamped Codex rollout events.

Agent messages, reasoning and model-response gaps never contribute. Primitive
tool executions add separately when parallel. Wrapper time contributes only
outside its primitive executions, so nesting is not charged twice. Native
command identifiers identify a process across repeated progress records.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import ast
import hashlib
import json
from pathlib import Path
import re


_MODEL_ITEMS = {'Reasoning', 'AgentMessage', 'UserMessage', 'ContextCompaction', 'TurnSummary'}
_CALLS = {'function_call', 'custom_tool_call'}
_OUTPUTS = {'function_call_output', 'custom_tool_call_output'}
_NS = Decimal(1_000_000_000)


class ToolTimingError(ValueError):
    pass


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ToolTimingError('Missing or invalid native tool duration')
    try:
        value = Decimal(str(value))
    except InvalidOperation as exc:
        raise ToolTimingError('Invalid native tool duration') from exc
    if not value.is_finite() or value < 0:
        raise ToolTimingError('Negative or nonfinite native tool duration')
    return value


def _timestamp(value):
    if not isinstance(value, str):
        raise ToolTimingError('Native tool timestamp is missing')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('Timezone is missing')
        delta = parsed.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
        return Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / 1_000_000
    except ValueError as exc:
        raise ToolTimingError('Invalid native tool timestamp') from exc


def _duration(item, start, end):
    value = item.get('duration')
    if isinstance(value, dict):
        seconds, nanos = _number(value.get('secs')), _number(value.get('nanos'))
        if nanos >= _NS or seconds != seconds.to_integral_value() or nanos != nanos.to_integral_value():
            raise ToolTimingError('Invalid native duration components')
        value = seconds + nanos / _NS
    elif value is not None:
        value = _number(value)
    else:
        value = end - start
    if abs(value - (end - start)) > Decimal('.005'):
        raise ToolTimingError('Native duration and execution timestamps disagree')
    return value


def _union_length(intervals):
    total, end = Decimal(0), None
    for left, right in sorted(intervals):
        if right < left:
            raise ToolTimingError('Native tool completion precedes its start')
        if end is None or left > end:
            total += right - left
        elif right > end:
            total += right - end
        end = right if end is None else max(end, right)
    return total


def _identifier(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value):
        raise ToolTimingError('Invalid native process or cell identity')
    return str(value)


def _wrapper_arguments(payload):
    raw = payload.get('arguments', payload.get('input', {}))
    if isinstance(raw, dict):
        return raw, ''
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed, raw
        except ValueError:
            pass
        return {}, raw
    raise ToolTimingError('Invalid native tool arguments')


def _poll_references(name, arguments, code):
    """Read explicit process/cell references; never subtract unrelated work."""
    leaf = str(name or '').split('.')[-1]
    processes, cells, local_processes = set(), set(), set()
    if leaf == 'write_stdin':
        processes.add(_identifier(arguments.get('session_id', arguments.get('process_id'))))
    elif leaf == 'wait':
        cells.add(_identifier(arguments.get('cell_id')))
    elif leaf == 'exec':
        for function, key, destination in (('write_stdin', 'session_id', processes), ('wait', 'cell_id', cells)):
            calls = re.findall(r'\btools\.' + function + r'\s*\(\s*\{([^{}]*)\}', code, re.S)
            if re.search(r'\btools\.' + function + r'\s*\(', code) and not calls:
                raise ToolTimingError('Cannot bind dynamic nested poll arguments')
            for body in calls:
                match = re.search(r'''(?:\b''' + key + r'''\b|["']''' + key + r'''["'])\s*:\s*(?:["']([^"']+)["']|([0-9]+))(?=\s*[,} ]|\s*$)''', body)
                if match:
                    destination.add(match.group(1) or match.group(2))
                    continue
                # A local execution result can be polled in the same wrapper.
                # Preserve its variable for later binding to an owned primitive;
                # an unrelated dynamic process reference remains unsupported.
                reference = re.search(r'''(?:\bsession_id\b|["']session_id["'])\s*:\s*([A-Za-z_$][\w$]*)\.session_id\b''', body)
                if function == 'write_stdin' and reference:
                    variable = reference.group(1)
                    launch = re.search(r'\b(?:const|let|var)\s+' + re.escape(variable) + r'\s*=\s*await\s+tools\.exec_command\s*\(', code)
                    if launch:
                        local_processes.add(variable)
                        continue
                raise ToolTimingError('Cannot bind dynamic nested poll identity')
    return processes, cells, local_processes


def _returned_cells(payload):
    raw = payload.get('output', '')
    text = raw if isinstance(raw, str) else json.dumps(raw)
    cells = set(re.findall(r'\bScript running with cell ID\s+([A-Za-z0-9_-]+)', text, re.I))
    cells.update(re.findall(r'''["']cell_id["']\s*:\s*["']?([A-Za-z0-9_-]+)''', text))
    return cells


def _matches_command(parent, item):
    command = item.get('command')
    if not command:
        return False
    if parent['arguments'].get('cmd') == command:
        return True
    # Code-mode wrappers may launch several commands. Decode only static string
    # literals; variables are not evidence of ownership.
    for match in re.finditer(r'''\bcmd\s*:\s*((?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'))''', parent['code'], re.S):
        try:
            if ast.literal_eval(match.group(1)) == command:
                return True
        except (ValueError, SyntaxError):
            continue
    return False


def account_tool_time(session_files, *, budget_seconds=1800, execution_window=None):
    """Return a bound receipt; unknown timing never becomes a scored failure."""
    budget = _number(budget_seconds)
    if not budget:
        raise ToolTimingError('Tool execution budget must be positive')
    result = {'schema_version': 1, 'method': 'native_tool_events_and_wrapper_intervals',
              'state': 'unknown', 'budget_seconds': float(budget), 'strict_less_than': True,
              'passed': None, 'cumulative_tool_seconds': None, 'model_response_time_included': False,
              'parallel_executions': 'sum', 'nested_wrapper_time': 'uncovered intervals only',
              'session_files': [], 'tools': [], 'wrappers': [], 'problems': []}
    try:
        files = sorted({Path(path).resolve() for path in session_files})
        if not files:
            raise ToolTimingError('Native session timing evidence is missing')
        bounds = None
        if execution_window is not None:
            bounds = (_timestamp(execution_window.get('started_at')), _timestamp(execution_window.get('finished_at')))
            if bounds[1] < bounds[0]:
                raise ToolTimingError('Agent execution window is reversed')
        calls, outputs, items, duplicates = {}, {}, {}, 0
        events = set()
        for path in files:
            raw = path.read_bytes()
            if not raw.strip():
                raise ToolTimingError('Native session timing evidence is empty')
            result['session_files'].append({'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()})
            for line in raw.decode().splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict) or not isinstance(record.get('payload', {}), dict):
                    raise ToolTimingError('Invalid native event structure')
                payload = record.get('payload', {})
                kind = payload.get('type')
                if kind not in _CALLS | _OUTPUTS | {'item_completed'}:
                    continue
                fingerprint = hashlib.sha256(line.encode()).hexdigest()
                if fingerprint in events:
                    duplicates += 1
                    continue
                events.add(fingerprint)
                if record.get('type') == 'response_item' and kind in _CALLS | _OUTPUTS:
                    identity = payload.get('call_id')
                    if not isinstance(identity, str) or not identity:
                        raise ToolTimingError('Native tool call has no identity')
                    destination = calls if kind in _CALLS else outputs
                    if identity in destination:
                        raise ToolTimingError('Conflicting duplicate native tool call')
                    destination[identity] = {'time': _timestamp(record.get('timestamp')),
                        'name': payload.get('name'), 'call_id': identity, 'payload': payload}
                elif record.get('type') == 'event_msg' and kind == 'item_completed':
                    item = payload.get('item') or {}
                    if item.get('type') in _MODEL_ITEMS:
                        continue
                    identity, item_type = item.get('id'), item.get('type')
                    if not isinstance(identity, str) or not identity or not isinstance(item_type, str):
                        raise ToolTimingError('Native execution item has no identity or type')
                    start = _number(payload.get('started_at_ms')) / 1000
                    status = str(item.get('status', 'completed')).lower().replace('_', '')
                    pending = status in {'inprogress', 'running', 'pending'}
                    end_value = payload.get('completed_at_ms')
                    end = start if pending and end_value is None else _number(end_value) / 1000
                    if end < start:
                        raise ToolTimingError('Native tool completion precedes its start')
                    duration = Decimal(0) if pending and end_value is None else _duration(item, start, end)
                    command = item.get('command')
                    command = command[-1] if isinstance(command, list) and command else command
                    candidate = {'id': identity, 'type': item_type, 'start': start, 'end': end,
                                 'duration': duration, 'status': status, 'command': command,
                                 'process_id': str(item['process_id']) if item.get('process_id') is not None else None}
                    if identity in items:
                        previous = items[identity]
                        if (previous['type'] != item_type or start != previous['start'] or end < previous['end']
                                or previous['process_id'] != candidate['process_id']
                                or previous['command'] != command
                                or (previous['status'] not in {'inprogress', 'running', 'pending'}
                                    and (end != previous['end'] or duration != previous['duration']
                                         or status != previous['status']))):
                            raise ToolTimingError('Conflicting native process timing updates')
                        candidate['duration'] = max(previous['duration'], duration)
                    items[identity] = candidate
        if set(calls) != set(outputs):
            raise ToolTimingError('Native tool calls and completions are incomplete')
        if any(item['status'] in {'inprogress', 'running', 'pending'} for item in items.values()):
            raise ToolTimingError('Native tool process has no final execution timing')
        wrappers = []
        for identity, call in calls.items():
            start, end = call['time'], outputs[identity]['time']
            if end < start:
                raise ToolTimingError('Native tool output precedes its call')
            arguments, code = _wrapper_arguments(call['payload'])
            processes, cells, local_processes = _poll_references(call['name'], arguments, code)
            wrappers.append({'id': identity, 'name': call['name'], 'start': start, 'end': end,
                             'arguments': arguments, 'code': code, 'processes': processes, 'cells': cells,
                             'local_processes': local_processes,
                             'returned_cells': _returned_cells(outputs[identity]['payload'])})
        if bounds:
            for interval in [*wrappers, *items.values()]:
                if interval['start'] < bounds[0] or interval['end'] > bounds[1]:
                    raise ToolTimingError('Native tool timing falls outside actual agent execution')
        # A primitive may continue beyond its launching wrapper. Count its
        # complete native process duration once, including time between polls.
        children = {item['id']: [] for item in wrappers}
        for item in items.values():
            parents = [parent for parent in wrappers if parent['start'] <= item['start'] <= parent['end']]
            if not parents:
                raise ToolTimingError('Native execution cannot be bound to a tool call')
            matched = [parent for parent in parents if _matches_command(parent, item)]
            if matched:
                parents = matched
            else:
                # A poll does not own a process just because another process
                # starts while the poll is waiting.
                parents = [parent for parent in parents if not parent['processes'] and not parent['cells']]
            if not parents:
                raise ToolTimingError('Native execution has no launching wrapper')
            shortest = min(parent['end'] - parent['start'] for parent in parents)
            parents = [parent for parent in parents if parent['end'] - parent['start'] == shortest]
            if len(parents) != 1:
                raise ToolTimingError('Ambiguous parallel native execution ownership')
            parent = parents[0]
            children[parent['id']].append(item)
        cell_owners = {}
        for parent in sorted(wrappers, key=lambda value: value['start']):
            for cell in parent['returned_cells']:
                cell_owners.setdefault(cell, parent['id'])
        by_process = {}
        for item in items.values():
            if item['process_id'] is not None:
                by_process.setdefault(item['process_id'], []).append(item)
        by_id = {parent['id']: parent for parent in wrappers}

        def covered_items(parent, seen=None):
            seen = set() if seen is None else seen
            if parent['id'] in seen:
                raise ToolTimingError('Cyclic asynchronous cell ownership')
            seen.add(parent['id'])
            covered = list(children[parent['id']])
            if parent['local_processes']:
                # The same wrapper's complete native execution already covers
                # its wait. Multiple local launches need finer def-use evidence
                # and must not be guessed from overlapping wall time.
                launches = re.findall(r'\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*await\s+tools\.exec_command\s*\(', parent['code'])
                if len(covered) != 1 or len(launches) != 1 or parent['local_processes'] != set(launches):
                    raise ToolTimingError('Cannot uniquely bind local dynamic process poll')
            for process in parent['processes']:
                if process not in by_process:
                    raise ToolTimingError('Polled native process has no complete timing evidence')
                covered.extend(by_process[process])
            for cell in parent['cells']:
                owner = cell_owners.get(cell)
                if owner is None:
                    raise ToolTimingError('Awaited cell has no launching native wrapper')
                covered.extend(covered_items(by_id[owner], seen.copy()))
            return {item['id']: item for item in covered}.values()

        total = sum((item['duration'] for item in items.values()), Decimal(0))
        for parent in wrappers:
            inside = [(max(parent['start'], child['start']), min(parent['end'], child['start'] + child['duration']))
                      for child in covered_items(parent)
                      if child['start'] < parent['end'] and child['start'] + child['duration'] > parent['start']]
            overhead = parent['end'] - parent['start'] - _union_length(inside)
            total += overhead
            result['wrappers'].append({'call_id': parent['id'], 'name': parent['name'],
                                       'uncovered_seconds': float(overhead)})
        result['tools'] = [{'item_id': item['id'], 'type': item['type'], 'status': item['status'],
                            'execution_seconds': float(item['duration'])} for item in items.values()]
        result.update(state='verified', passed=total < budget, cumulative_tool_seconds=float(total),
                      cumulative_tool_nanoseconds=int(total * _NS), tool_item_count=len(items),
                      wrapper_call_count=len(wrappers), duplicate_event_count=duplicates,
                      threshold_reached=total >= budget)
    except (OSError, UnicodeError, json.JSONDecodeError, ToolTimingError, TypeError, KeyError, AttributeError) as exc:
        result['problems'].append(str(exc))
    return result


def account_trial_tool_time(result_file, *, budget_seconds=1800):
    path = Path(result_file).resolve()
    try:
        result_raw = path.read_bytes()
        execution_window = json.loads(result_raw).get('agent_execution')
        if not isinstance(execution_window, dict):
            raise ToolTimingError('Actual agent execution window is missing')
        receipt = account_tool_time((path.parent / 'agent/sessions').rglob('*.jsonl'),
            budget_seconds=budget_seconds, execution_window=execution_window)
        receipt['result_file'] = {'path': str(path), 'sha256': hashlib.sha256(result_raw).hexdigest()}
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        receipt = account_tool_time([], budget_seconds=budget_seconds)
        receipt['problems'].append(str(exc))
        return receipt
    log = path.parent / 'agent/codex.txt'
    try:
        raw = log.read_bytes()
        receipt['native_stream'] = {'path': str(log), 'sha256': hashlib.sha256(raw).hexdigest()}
        expected = {}
        mappings = {'command_execution': 'CommandExecution', 'file_change': 'FileChange',
                    'mcp_tool_call': 'McpToolCall', 'web_search': 'WebSearch'}
        for line in raw.decode().splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                if line.lstrip().startswith('{'):
                    raise ToolTimingError('Truncated or malformed native execution stream JSON')
                continue
            item = record.get('item') or {}
            if record.get('type') == 'item.completed' and item.get('type') in mappings:
                identity = (mappings[item['type']], item.get('id'))
                expected[identity] = True
        expected_counts = {kind: sum(key[0] == kind for key in expected) for kind in mappings.values()}
        actual_counts = {kind: sum(item['type'] == kind for item in receipt['tools']) for kind in mappings.values()}
        receipt['stream_coverage'] = {'expected': expected_counts, 'actual': actual_counts,
                                     'matched': expected_counts == actual_counts}
        if expected_counts != actual_counts:
            raise ToolTimingError('Native execution stream and timed item coverage differ')
    except (OSError, UnicodeError, TypeError, ToolTimingError) as exc:
        receipt.update(state='unknown', passed=None)
        receipt['problems'].append(str(exc))
    return receipt
