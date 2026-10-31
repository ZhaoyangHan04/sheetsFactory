"""Prospective, conservative bounds for complete native clock disagreements.

This module does not replace the exact timer or change any historical result.
It accepts a deliberately small static wrapper language. All primitive clocks
and every outer exec interval are added, including all overlap, in integer ns.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
import shlex

from .tool_time import account_trial_tool_time

NS = 1_000_000_000
ENDPOINT_MARGIN_NS = 2_000_000
FROZEN_CLOCK_TOLERANCE_NS = 5_000_000
METHOD = 'complete_dual_clock_envelope_with_fully_added_exec_wrappers_v3'
_MODEL_NATIVE = {'Reasoning', 'AgentMessage', 'UserMessage', 'ContextCompaction',
                 'TurnSummary', 'Plan'}
_MODEL_STREAM = {'reasoning', 'agent_message', 'user_message', 'context_compaction',
                 'turn_summary', 'plan'}
_CALLS = {'function_call', 'custom_tool_call'}
_OUTPUTS = {'function_call_output', 'custom_tool_call_output'}
_TOOL_TYPES = {'command_execution': 'CommandExecution', 'file_change': 'FileChange'}


class ClockEvidenceError(ValueError):
    """The complete conservative bound is not established."""


def _require(condition, message):
    if not condition:
        raise ClockEvidenceError(message)


def _integer(value, label, *, minimum=0):
    _require(type(value) is int and value >= minimum, 'Invalid ' + label)
    return value


def _identity(value):
    _require(type(value) in (str, int) and str(value) != '', 'Invalid tool identity')
    return str(value)


def _stamp(value):
    _require(isinstance(value, str) and re.fullmatch(
        r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)', value),
        'Invalid timestamp or unsupported timestamp precision')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    delta = dt.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * NS + delta.microseconds * 1000


def _read(path):
    path = Path(path).resolve()
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    _require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
             (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'Evidence changed while reading')
    return raw, {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def _records(raw, *, stream=False):
    lines = raw.decode('utf-8').splitlines()
    _require(bool(lines), 'Empty event file')
    result = []
    for line, text in enumerate(lines, 1):
        if not text.strip():
            continue
        if stream and line == 1 and text == 'Reading additional input from stdin...':
            continue
        record = _json(text)
        _require(isinstance(record, dict), 'Event is not an object')
        result.append((line, record))
    _require(bool(result), 'No events')
    return result


def _json(text):
    def pairs(values):
        result = {}
        for key, value in values:
            _require(key not in result, 'Duplicate JSON object key')
            result[key] = value
        return result

    def number(value):
        parsed = float(value)
        _require(math.isfinite(parsed), 'Nonfinite JSON number')
        return parsed

    def constant(_):
        raise ClockEvidenceError('Nonfinite JSON constant')

    return json.loads(text, object_pairs_hook=pairs, parse_float=number, parse_constant=constant)


def _duration(item, span):
    value = item.get('duration')
    if value is None:
        _require(item['type'] == 'FileChange', 'Command duration is missing')
        return None, 'span_only_file_change'
    _require(isinstance(value, dict) and set(value) == {'secs', 'nanos'}, 'Invalid duration structure')
    seconds = _integer(value['secs'], 'duration seconds')
    nanos = _integer(value['nanos'], 'duration nanoseconds')
    _require(nanos < NS, 'Duration nanoseconds overflow')
    return seconds * NS + nanos, 'dual_clock'


# This is a recognizer, not a JavaScript evaluator. Dynamic expressions are not
# accepted even if a particular execution happened to produce finite tool calls.
_TOKEN = re.compile(r'\s+|//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|'
                    r"'(?:\\.|[^'\\])*'|[A-Za-z_$][\w$]*|\d+(?:\.\d+)?|\.\.\.|=>|\+\+|[^\s]", re.S)
_META = re.compile(
    r'text\s*\(\s*ALL_TOOLS\.filter\(\s*([A-Za-z_$][\w$]*)\s*=>\s*'
    r'/[A-Za-z0-9_| -]+/\.test\(\s*\1\.name\s*\+\s*(?:" "|\' \')\s*\+\s*\1\.description\s*\)\s*\)'
    r'(?:\.map\(\s*([A-Za-z_$][\w$]*)\s*=>\s*\(\s*\{\s*name\s*:\s*\2\.name\s*,\s*'
    r'description\s*:\s*\2\.description\.slice\(\s*0\s*,\s*\d+\s*\)\s*\}\s*\)\s*\))?\s*\)\s*;?')


class _StaticExec:
    def __init__(self, code):
        _require(isinstance(code, str), 'exec input must be code text')
        # Only this read-only metadata statement may use callbacks. It cannot
        # dispatch tools or return executable function references.
        code = _META.sub('', code)
        self.tokens = [m.group() for m in _TOKEN.finditer(code)
                       if not m.group().isspace() and not m.group().startswith(('//', '/*'))]
        self.at = 0
        self.calls = []

    def take(self, value=None):
        _require(self.at < len(self.tokens), 'Truncated static exec program')
        result = self.tokens[self.at]
        self.at += 1
        _require(value is None or result == value, 'Unsupported static exec syntax')
        return result

    def peek(self, value):
        return self.at < len(self.tokens) and self.tokens[self.at] == value

    def literal(self):
        token = self.take()
        if token.startswith(('"', "'")):
            try:
                return json.loads(token) if token[0] == '"' else ast.literal_eval(token)
            except (ValueError, SyntaxError) as exc:
                raise ClockEvidenceError('Invalid literal string') from exc
        if token in ('true', 'false', 'null'):
            return {'true': True, 'false': False, 'null': None}[token]
        if re.fullmatch(r'\d+(?:\.\d+)?', token):
            return int(token) if '.' not in token else Decimal(token)
        if token == '-':
            number = self.literal()
            _require(type(number) in (int, Decimal), 'Invalid negative literal')
            return -number
        if token == '{':
            out = {}
            while not self.peek('}'):
                key = self.take()
                if key.startswith(('"', "'")):
                    key = json.loads(key) if key[0] == '"' else ast.literal_eval(key)
                _require(isinstance(key, str) and key not in out, 'Invalid or duplicate literal key')
                self.take(':')
                out[key] = self.literal()
                if self.peek('}'):
                    break
                self.take(',')
            self.take('}')
            return out
        if token == '[':
            out = []
            while not self.peek(']'):
                out.append(self.literal())
                if self.peek(']'):
                    break
                self.take(',')
            self.take(']')
            return out
        raise ClockEvidenceError('Dynamic tool arguments are unsupported')

    def tool(self):
        self.take('tools'); self.take('.')
        name = self.take()
        _require(name in {'exec_command', 'apply_patch', 'write_stdin'}, 'Unsupported inner tool')
        self.take('(')
        args = self.literal()
        self.take(')')
        if name == 'apply_patch':
            _require(isinstance(args, str) and args.startswith('*** Begin Patch\n') and
                     args.rstrip().endswith('*** End Patch'), 'Nonliteral or malformed patch')
            changes = []
            for kind, path in re.findall(r'^\*\*\* (Add|Update|Delete) File: (.+)$', args, re.M):
                changes.append((path, {'Add': 'add', 'Update': 'update', 'Delete': 'delete'}[kind]))
            _require(changes and len({x[0] for x in changes}) == len(changes) and
                     '\n*** Move to:' not in args, 'Unsupported patch paths or move')
            call = {'kind': 'FileChange', 'changes': sorted(changes)}
        else:
            _require(isinstance(args, dict), 'Tool arguments must be a literal object')
            if name == 'exec_command':
                _require(isinstance(args.get('cmd'), str), 'Command is not literal')
                call = {'kind': 'CommandExecution', 'command': args['cmd']}
            else:
                _require('session_id' in args and 'process_id' not in args,
                         'Poll must name one literal session_id')
                call = {'kind': 'poll', 'process_id': _identity(args['session_id'])}
        self.calls.append(call)

    def parse(self):
        while self.at < len(self.tokens):
            if self.peek(';'):
                self.take(); continue
            if self.peek('text'):
                self.take(); self.take('('); self.take('await'); self.tool(); self.take(')')
            elif self.peek('const'):
                self.take(); variable = self.take()
                _require(re.fullmatch(r'[A-Za-z_$][\w$]*', variable), 'Invalid local variable')
                self.take('='); self.take('await')
                if self.peek('Promise'):
                    self.take(); self.take('.')
                    _require(self.take() in {'all', 'allSettled'}, 'Unsupported fanout')
                    self.take('('); self.take('[')
                    first = len(self.calls)
                    while not self.peek(']'):
                        self.tool()
                        if self.peek(']'):
                            break
                        self.take(',')
                    self.take(']'); self.take(')')
                    _require(0 < len(self.calls) - first <= 32, 'Static fanout exceeds supported bound')
                else:
                    self.tool()
                if self.peek(';'):
                    self.take()
                # Only these exact read-only logging suffixes can consume the
                # result. Their loops cannot execute another tool.
                endings = [f'{variable}.forEach(text);', f'text({variable});',
                    f'for(let i=0;i<{variable}.length;i++)text({{i,result:{variable}[i]}});',
                    f'for(let i=0;i<{variable}.length;i++)text({{i,...{variable}[i]}});']
                for ending in endings:
                    expected = [m.group() for m in _TOKEN.finditer(ending) if not m.group().isspace()]
                    if self.tokens[self.at:self.at+len(expected)] == expected:
                        self.at += len(expected)
                        break
                else:
                    raise ClockEvidenceError('Unsupported local result use or callback')
            else:
                raise ClockEvidenceError('Unsupported exec control flow or dynamic dispatch')
            if self.peek(';'):
                self.take()
        _require(self.calls, 'Exec wrapper contains no supported tool calls')
        return self.calls


def _signature(item, *, stream):
    kind = _TOOL_TYPES.get(item.get('type')) if stream else item.get('type')
    _require(kind in {'CommandExecution', 'FileChange'}, 'Unknown native or stream tool type')
    if kind == 'CommandExecution':
        command = shlex.split(item['command']) if stream else item.get('command')
        _require(isinstance(command, list) and command and all(isinstance(x, str) for x in command),
                 'Invalid command signature')
        return (kind, tuple(command))
    changes = item.get('changes')
    if stream:
        _require(isinstance(changes, list) and changes, 'Invalid stream file change')
        pairs = [(x['path'], x['kind']) for x in changes]
    else:
        _require(isinstance(changes, dict) and changes, 'Invalid native file change')
        _require(all(isinstance(x, dict) and not x.get('move_path') for x in changes.values()),
                 'Unsupported file move')
        pairs = [(path, x['type']) for path, x in changes.items()]
    _require(all(isinstance(path, str) and path and kind in {'add', 'update', 'delete'} for path, kind in pairs)
             and len({x[0] for x in pairs}) == len(pairs), 'Invalid file change signature')
    return (kind, tuple(sorted(pairs)))


def _native(records, window):
    calls, outputs, tools, terminals, starts = {}, {}, [], [], []
    all_ids = set()
    threads, turns = set(), set()
    for line, record in records:
        payload = record.get('payload')
        _require(isinstance(payload, dict), 'Invalid native payload')
        kind = payload.get('type')
        if record.get('type') == 'response_item' and kind in _CALLS | _OUTPUTS:
            identity = _identity(payload.get('call_id'))
            target = calls if kind in _CALLS else outputs
            _require(identity not in target, 'Duplicate native wrapper identity')
            target[identity] = {'line': line, 'time': _stamp(record.get('timestamp')), 'payload': payload}
        elif record.get('type') == 'response_item':
            _require(kind in {'message', 'reasoning'}, 'Unknown native response item')
        if record.get('type') != 'event_msg':
            _require(record.get('type') in {'response_item', 'session_meta', 'world_state',
                     'turn_context', 'token_usage_record'}, 'Unknown native record type')
            continue
        if kind == 'task_complete':
            terminals.append((line, _stamp(record.get('timestamp')), payload))
        elif kind == 'task_started':
            starts.append((line, _stamp(record.get('timestamp')), payload))
        elif kind in {'turn_aborted', 'task_failed', 'turn_failed', 'error'}:
            raise ClockEvidenceError('Native task did not terminate normally')
        elif kind == 'item_completed':
            item = payload.get('item')
            _require(isinstance(item, dict), 'Invalid completed native item')
            if item.get('type') in _MODEL_NATIVE:
                continue
            threads.add(_identity(payload.get('thread_id')))
            turns.add(_identity(payload.get('turn_id')))
            signature = _signature(item, stream=False)
            identity = _identity(item.get('id'))
            _require(identity not in all_ids, 'Duplicate native primitive identity')
            all_ids.add(identity)
            start = _integer(payload.get('started_at_ms'), 'primitive start ms') * 1_000_000
            end = _integer(payload.get('completed_at_ms'), 'primitive end ms') * 1_000_000
            _require(window[0] <= start <= end <= window[1], 'Primitive outside agent window or reversed')
            duration, clock_kind = _duration(item, end-start)
            _require(item.get('status') in {'completed', 'failed'}, 'Native primitive is not terminal')
            if signature[0] == 'CommandExecution':
                _require(type(item.get('exit_code')) is int, 'Command exit code is missing')
            else:
                _require(item.get('exit_code') is None, 'Unexpected file-change exit code')
            clocks = [end-start] + ([] if duration is None else [duration])
            tools.append({'id': identity, 'type': signature[0], 'native_line': line,
                'start_epoch_ns': start, 'end_epoch_ns': end, 'span_ns': end-start,
                'reported_duration_ns': duration, 'clock_kind': clock_kind,
                'clock_disagreement_above_frozen_5ms': duration is not None and
                    abs(duration-(end-start)) > FROZEN_CLOCK_TOLERANCE_NS,
                'lower_ns': max(0, min(clocks)-ENDPOINT_MARGIN_NS),
                'upper_ns': max(clocks)+ENDPOINT_MARGIN_NS, 'status': item['status'],
                'exit_code': item.get('exit_code'), 'process_id':
                    None if item.get('process_id') is None else _identity(item['process_id']),
                '_signature': signature})
        else:
            _require(kind == 'token_count', 'Unknown or pending native event')
    _require(len(terminals) == 1, 'Exactly one native task_complete is required')
    _require(len(starts) == 1, 'Exactly one native task_started is required')
    terminal_line, terminal_time, terminal = terminals[0]
    started_line, started_time, started = starts[0]
    _require(window[0] <= terminal_time <= window[1] and tools and calls.keys() == outputs.keys(),
             'Native tail or wrapper results are incomplete')
    _require(all(x['native_line'] < terminal_line for x in tools) and
             all(v['line'] < terminal_line for v in outputs.values()), 'Tools after native terminal')
    _require(terminal.get('turn_id') and terminal.get('root_turn_id') == terminal['turn_id'],
             'Unexpected native terminal identity')
    _require(started.get('turn_id') == terminal['turn_id'] == started.get('root_turn_id')
             and turns == {terminal['turn_id']} and len(threads) == 1 and
             window[0] <= started_time <= terminal_time and started_line < terminal_line,
             'Native turn identities or task start do not match')
    wrappers = []
    for identity, call in calls.items():
        output = outputs[identity]
        _require(call['payload'].get('name') == 'exec', 'Only outer exec wrappers are supported')
        _require(window[0] <= call['time'] <= output['time'] <= window[1]
                 and started_line < call['line'] < output['line'], 'Invalid wrapper interval')
        blocks = output['payload'].get('output')
        _require(isinstance(blocks, list) and blocks and all(isinstance(b, dict) and
                 b.get('type') == 'input_text' and isinstance(b.get('text'), str) for b in blocks)
                 and blocks[0]['text'].startswith('Script completed\n'),
                 'Wrapper did not return a completed static exec result')
        code = call['payload'].get('input', call['payload'].get('arguments'))
        static = _StaticExec(code).parse()
        wrappers.append({'call_id': identity, 'native_call_line': call['line'],
            'native_output_line': output['line'], 'start_epoch_ns': call['time'],
            'end_epoch_ns': output['time'], 'full_wall_ns': output['time']-call['time'],
            'upper_ns': output['time']-call['time']+ENDPOINT_MARGIN_NS,
            'static_calls': static})
    _require(wrappers, 'No exec wrappers')
    return tools, wrappers, {'line': terminal_line, 'timestamp_epoch_ns': terminal_time,
                             'turn_id': terminal['turn_id'], 'thread_id': next(iter(threads))}


def _stream(records):
    completed, started, tools, turns, threads, finished = set(), {}, [], [], [], False
    for line, record in records:
        kind = record.get('type')
        _require(not finished, 'Events after stream terminal')
        if kind == 'thread.started':
            threads.append(record.get('thread_id'))
        elif kind == 'turn.started':
            turns.append(line)
        elif kind == 'turn.completed':
            _require(len(turns) == 1, 'Invalid stream turn count')
            finished = True
        elif kind in {'item.started', 'item.completed'}:
            item = record.get('item')
            _require(isinstance(item, dict), 'Invalid stream item')
            identity = _identity(item.get('id'))
            if item.get('type') in _MODEL_STREAM:
                continue
            signature = _signature(item, stream=True)
            if kind == 'item.started':
                _require(identity not in started, 'Duplicate stream tool start')
                started[identity] = signature
            else:
                _require(identity in started and identity not in completed and started[identity] == signature,
                         'Unbalanced or changed stream primitive')
                _require(item.get('status') in {'completed', 'failed'}, 'Nonterminal stream primitive')
                completed.add(identity)
                tools.append({'id': identity, 'stream_line': line, 'type': signature[0],
                    'status': item['status'], 'exit_code': item.get('exit_code'), '_signature': signature})
        else:
            raise ClockEvidenceError('Unknown or failed stream event')
    _require(finished and len(threads) == 1 and isinstance(threads[0], str) and threads[0]
             and len(turns) == 1 and set(started) == completed,
             'Stream terminal or tool tail is incomplete')
    return tools, {'thread_id': threads[0], 'turn_started_line': turns[0]}


def _ownership(tools, wrappers):
    launches = []
    polls = []
    for wrapper in wrappers:
        for index, call in enumerate(wrapper['static_calls']):
            entry = (wrapper, index, call)
            (polls if call['kind'] == 'poll' else launches).append(entry)
    _require(len(launches) == len(tools), 'Static launch and native primitive coverage differ')
    used = set()
    for tool in tools:
        matches = []
        for number, (wrapper, index, call) in enumerate(launches):
            if number in used or call['kind'] != tool['type']:
                continue
            # Native endpoints are millisecond-quantized; call stamps have us.
            if not wrapper['start_epoch_ns']-1_000_000 <= tool['start_epoch_ns'] <= wrapper['end_epoch_ns']+1_000_000:
                continue
            signature = tool['_signature']
            if tool['type'] == 'CommandExecution':
                match = signature[1][-1] == call['command']
            else:
                match = tuple(call['changes']) == signature[1]
            if match:
                matches.append((number, wrapper, index))
        _require(len(matches) == 1, 'Missing or ambiguous static primitive ownership')
        number, wrapper, index = matches[0]
        used.add(number)
        tool['owner_call_id'] = wrapper['call_id']
        tool['owner_static_call_index'] = index
    process_owners = {}
    for tool in tools:
        if tool['process_id'] is not None:
            _require(tool['process_id'] not in process_owners, 'Duplicate native process identity')
            process_owners[tool['process_id']] = tool
    for wrapper, index, call in polls:
        owner = process_owners.get(call['process_id'])
        _require(owner is not None and owner['owner_call_id'] != wrapper['call_id'] and
                 owner['start_epoch_ns'] <= wrapper['start_epoch_ns']+1_000_000,
                 'Poll does not identify an owned completed native process')
        call['owner_native_id'] = owner['id']
    return {'static_launch_count': len(launches), 'owned_poll_count': len(polls),
            'unknown_dispatch_count': 0, 'all_primitives_uniquely_owned': True}


def account_complete_clock_disagreement(result_file, *, budget_seconds=1800):
    """Bound one complete normal terminal trial; unsupported evidence stays unknown.

    The result is timing evidence only. It never reads reward and never grants a
    task, difficulty, or release qualification. A bound at the budget is unknown,
    because this route cannot turn an upper bound into proof of budget failure.
    """
    receipt = {'kind': 'complete_native_clock_disagreement_bound', 'version': 3,
        'method': METHOD, 'state': 'unknown', 'exact_state': 'unknown', 'passed': None,
        'complete': False,
        'cumulative_tool_seconds': None, 'cumulative_exact_ns': None,
        'cumulative_lower_bound_ns': None, 'cumulative_upper_bound_ns': None,
        'budget_seconds': None, 'strict_less_than': True,
        'model_response_time_included': False, 'overlap_credit_ns': 0,
        'parallel_executions': 'sum', 'wrapper_time': 'all complete walls added again',
        'endpoint_margin_per_interval_ns': ENDPOINT_MARGIN_NS,
        'historical_result_modified': False, 'qualification_claimed': False,
        'clock_envelope_assumption': 'Each primitive is bounded by its larger observed clock plus two 1ms endpoint margins',
        'problems': [], 'artifacts': [], 'tools': [], 'wrappers': []}
    try:
        budget = Decimal(str(budget_seconds))
        _require(not isinstance(budget_seconds, bool) and budget.is_finite() and budget > 0
                 and budget*NS == (budget*NS).to_integral_value(), 'Invalid timing budget')
        receipt['budget_seconds'] = int(budget) if budget == budget.to_integral_value() else float(budget)
        path = Path(result_file).resolve()
        raw, reference = _read(path)
        receipt['result_file'] = reference; receipt['artifacts'].append(reference)
        actual = _json(raw)
        _require(isinstance(actual, dict) and 'exception_info' in actual and actual['exception_info'] is None,
                 'Only normal terminal trials are eligible')
        execution = actual.get('agent_execution')
        _require(isinstance(execution, dict) and actual.get('finished_at'), 'Result terminal is missing')
        window = (_stamp(execution.get('started_at')), _stamp(execution.get('finished_at')))
        _require(window[0] <= window[1] <= _stamp(actual['finished_at']), 'Invalid actual agent window')
        files = sorted((path.parent/'agent/sessions').rglob('*.jsonl'))
        _require(len(files) == 1, 'Exactly one complete native session is supported')
        native_raw, native_ref = _read(files[0]); receipt['artifacts'].append(native_ref)
        stream_raw, stream_ref = _read(path.parent/'agent/codex.txt'); receipt['artifacts'].append(stream_ref)
        receipt['implementation'] = _read(__file__)[1]
        receipt['upstream_exact_parser'] = _read(Path(__file__).with_name('tool_time.py'))[1]
        receipt['artifacts'].extend([receipt['implementation'], receipt['upstream_exact_parser']])
        exact = account_trial_tool_time(path, budget_seconds=budget_seconds, allow_mixed_file_change_polls=True)
        receipt['original_exact_receipt'] = exact
        tools, wrappers, terminal = _native(_records(native_raw), window)
        stream_tools, stream_terminal = _stream(_records(stream_raw, stream=True))
        _require(terminal['thread_id'] == stream_terminal['thread_id'], 'Native/stream thread identity mismatch')
        _require(len(tools) == len(stream_tools), 'Ordered native/stream coverage differs')
        for native, stream in zip(tools, stream_tools):
            _require(native['_signature'] == stream['_signature'] and native['status'] == stream['status']
                     and native['exit_code'] == stream['exit_code'], 'Ordered native/stream signature, status or exit mismatch')
            native['stream_id'] = stream['id']; native['stream_line'] = stream['stream_line']
            native['signature_sha256'] = hashlib.sha256(json.dumps(native['_signature'],
                ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        _require(any(t['clock_disagreement_above_frozen_5ms'] for t in tools),
                 'No native dual-clock disagreement above frozen 5ms threshold')
        _require(exact.get('state') == 'unknown', 'This route is only for unresolved exact timing')
        coverage = _ownership(tools, wrappers)
        lower = sum(t['lower_ns'] for t in tools)
        primitive_upper = sum(t['upper_ns'] for t in tools)
        wrapper_upper = sum(w['upper_ns'] for w in wrappers)
        upper = primitive_upper + wrapper_upper
        for tool in tools:
            tool.pop('_signature')
        receipt.update(tools=tools, wrappers=wrappers, coverage={**coverage,
            'native_tool_count': len(tools), 'stream_tool_count': len(stream_tools),
            'wrapper_call_count': len(wrappers), 'wrapper_output_count': len(wrappers),
            'native_stream_ordered_signatures_status_and_exits_equal': True,
            'all_intervals_in_agent_window': True, 'normal_native_terminal': terminal,
            'normal_stream_terminal': stream_terminal},
            primitive_upper_sum_ns=primitive_upper, wrapper_upper_sum_ns=wrapper_upper,
            cumulative_lower_bound_ns=lower, cumulative_upper_bound_ns=upper,
            cumulative_lower_bound_seconds=str(Decimal(lower)/NS),
            cumulative_upper_bound_seconds=str(Decimal(upper)/NS))
        # Recheck every original file, including exact parser inputs, after all
        # independent parsing. A concurrent writer cannot certify a prefix.
        _require(all(_read(a['path'])[1] == a for a in receipt['artifacts']), 'Evidence changed during accounting')
        receipt['complete'] = True
        receipt['clock_disagreement_count'] = sum(t['clock_disagreement_above_frozen_5ms'] for t in tools)
        if upper < int(budget*NS):
            receipt.update(state='verified_conservative_bound', passed=True)
        else:
            receipt['problems'].append('Conservative upper bound does not prove strict under-budget execution')
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError, ArithmeticError) as exc:
        receipt['problems'].append(str(exc))
    return receipt
