"""Prospective, conservative timing bounds for contained static pending tools.

The legacy exact parser is unchanged. A bound needs an identity captured while
the exact trial container was alive and an authoritative later stop observation.
Missing native durations remain unknown; they are never replaced with zero.
"""
from datetime import datetime, timezone
from collections import Counter
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

from .tool_time import (ToolTimingError, _CALLS, _OUTPUTS, _MODEL_ITEMS, _number,
                        _timestamp, _wrapper_arguments, account_tool_time,
                        account_trial_tool_time)

POLICY_V2 = {'version': 2, 'budget_seconds': 1800, 'strict_less_than': True,
    'exclude_model_response_time': True, 'parallel_executions': 'sum',
    'measurement': 'native_exact_or_static_pending_container_stop_bounds',
    'unknown_fanout': 'reject', 'pending_prefix_overlap': 'reject',
    'exact_unknown_retained': True, 'stop_identity': 'full_container_id_captured_while_running'}
_INSPECT = ('{"Id":{{json .Id}},"Name":{{json .Name}},"Image":{{json .Image}},'
            '"Running":{{json .State.Running}},"Restarting":{{json .State.Restarting}},'
            '"Status":{{json .State.Status}},"StartedAt":{{json .State.StartedAt}},'
            '"FinishedAt":{{json .State.FinishedAt}}}')
_PENDING = {'inprogress', 'running', 'pending'}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')
    return _ref(path)


def _observe(arguments):
    before = _now()
    result = subprocess.run(['docker', *arguments], capture_output=True, text=True, timeout=10)
    return {'command': ['docker', *arguments], 'utc_before': before, 'utc_after': _now(),
            'returncode': result.returncode, 'stdout': result.stdout.strip(), 'stderr': result.stderr.strip()}


def _daemon(observation):
    if observation['command'] != ['docker', 'info', '--format', '{{json .ID}}'] or observation['returncode'] != 0:
        raise ToolTimingError('A responsive identified Docker daemon is required')
    identity = json.loads(observation['stdout'])
    if not isinstance(identity, str) or not identity:
        raise ToolTimingError('Docker daemon identity is missing')
    return identity


def _container(observation, target, *, absent_ok=False):
    if observation['command'] != ['docker', 'inspect', '--type', 'container', target, '--format', _INSPECT]:
        raise ToolTimingError('Container observation command does not bind its exact target')
    if observation['returncode'] == 0:
        return json.loads(observation['stdout'])
    if (absent_ok and observation['returncode'] == 1
            and re.search(r'(?:No such container:|No such object:)\s*' + re.escape(target) + r'\s*$', observation['stderr'], re.I)):
        return None
    raise ToolTimingError('Container stop is not proven by an authoritative inspect response')


def capture_trial_container_identity(trial_directory, container_name, output_file):
    """Call at Harbor agent-start, after its environment is running. No broad ps."""
    trial = Path(trial_directory).resolve()
    expected_name = trial.name.lower() + '__env-main-1'
    if container_name != expected_name:
        raise ToolTimingError('Only the exact trial-derived main container name is supported')
    config = _ref(trial / 'config.json')
    daemon = _observe(['info', '--format', '{{json .ID}}'])
    observation = _observe(['inspect', '--type', 'container', container_name, '--format', _INSPECT])
    record = _container(observation, container_name)
    if (not re.fullmatch(r'[a-f0-9]{64}', record.get('Id', '')) or record.get('Name', '').lstrip('/') != container_name
            or record.get('Running') is not True or record.get('Restarting') is not False):
        raise ToolTimingError('Capture requires the full unique identity of the running trial container')
    return _write_new(output_file, {'schema_version': 2, 'kind': 'live_trial_container_identity',
        'trial_directory': str(trial), 'trial_config': config, 'container_name': container_name,
        'container_id': record['Id'], 'daemon_id': _daemon(daemon),
        'captured_at': observation['utc_after'], 'daemon_observation': daemon,
        'running_observation': observation, 'scope': 'native command tools in this trial main container'})


def capture_trial_stop_receipt(result_file, identity_file, output_file):
    """Call after a trial ends, and again after Harbor returns if still running."""
    result_file, identity_file = Path(result_file).resolve(), Path(identity_file).resolve()
    identity = json.loads(identity_file.read_text())
    if str(result_file.parent) != identity['trial_directory'] or _ref(identity['trial_config']['path']) != identity['trial_config']:
        raise ToolTimingError('Live container capture does not bind this unchanged trial')
    before = _observe(['info', '--format', '{{json .ID}}'])
    if _daemon(before) != identity['daemon_id']:
        raise ToolTimingError('Docker daemon differs from the live identity capture')
    observations = []
    for target in [identity['container_id'], identity['container_name']]:
        observation = _observe(['inspect', '--type', 'container', target, '--format', _INSPECT])
        record = _container(observation, target, absent_ok=True)
        if record is not None and (record.get('Id') != identity['container_id']
                or record.get('Running') is not False or record.get('Restarting') is not False
                or record.get('Status') not in {'exited', 'dead'}):
            raise ToolTimingError('The captured trial container is still running or its name was reused')
        observations.append(observation)
    after = _observe(['info', '--format', '{{json .ID}}'])
    if _daemon(after) != identity['daemon_id']:
        raise ToolTimingError('Docker daemon identity changed during stop capture')
    return _write_new(output_file, {'schema_version': 2, 'kind': 'authoritative_trial_container_stop_bound',
        'exact_stop_time': None, 'identity_file': _ref(identity_file), 'result_file': _ref(result_file),
        'daemon_before': before, 'container_observations': observations, 'daemon_after': after,
        'stop_upper_utc': max(o['utc_after'] for o in observations),
        'scope': 'all statically bounded native command tools in the captured trial container'})


def static_pending_commands(payload):
    """Prove a finite literal launch count; reject dynamic/repeated dispatch."""
    leaf = str(payload.get('name') or '').split('.')[-1]
    arguments, code = _wrapper_arguments(payload)
    if leaf == 'exec_command':
        if not isinstance(arguments.get('cmd'), str):
            raise ToolTimingError('A pending command needs a literal command argument')
        return [arguments['cmd']]
    if leaf != 'exec' or not code or '`' in code:
        raise ToolTimingError('Pending tool is not a supported static command wrapper')
    # Preserve offsets while masking quoted strings and comments. Keywords and
    # tool-looking text inside shell commands are not JavaScript dispatch.
    token = re.compile(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|//[^\n]*|/\*[\s\S]*?\*/''')
    masked = token.sub(lambda match: ' ' * len(match.group()), code)
    if (re.search(r'\b(?:for|while|do|function|class|eval|Function|import|setTimeout|setInterval|load|get|set)\b|=>', masked)
            or re.search(r'\b[A-Za-z_$][\w$]*\s*\([^{}]*\)\s*\{', masked)
            or re.search(r'\btools\s*\[', masked)):
        raise ToolTimingError('Unknown or repeated pending tool fanout is unsupported')
    names = re.findall(r'\btools\s*\.\s*([A-Za-z_$][\w$]*)', masked)
    if not names or any(name != 'exec_command' for name in names) or len(re.findall(r'\btools\b', masked)) != len(names):
        raise ToolTimingError('Unknown pending tool dispatch or remote/poll ownership')
    starts = list(re.finditer(r'\btools\s*\.\s*exec_command\s*\(\s*\{', masked))
    if len(starts) != len(names) or len(starts) > 32:
        raise ToolTimingError('Pending native command launch count is not statically bounded')
    commands = []
    for match in starts:
        begin, depth, end = match.end() - 1, 0, None
        for index in range(begin, len(masked)):
            if masked[index] == '{':
                depth += 1
            elif masked[index] == '}':
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end is None:
            raise ToolTimingError('Incomplete pending command argument object')
        body = code[begin:end]
        body_masked = masked[begin:end]
        values = list(re.finditer(r'''\bcmd\s*:\s*("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')(?=\s*[,}])''', body, re.S))
        if len(values) != 1 or len(re.findall(r'\bcmd\s*:', body_masked)) != 1 or '...' in body_masked:
            raise ToolTimingError('A pending command string is dynamic or ambiguous')
        try:
            command = ast.literal_eval(values[0].group(1))
        except (ValueError, SyntaxError) as error:
            raise ToolTimingError('A pending command literal cannot be decoded') from error
        if not isinstance(command, str):
            raise ToolTimingError('A pending command literal must be text')
        commands.append(command)
    return commands


def _validated_stop(result_file, receipt_file):
    receipt_file = Path(receipt_file).resolve()
    receipt = json.loads(receipt_file.read_text())
    if receipt.get('schema_version') != 2 or receipt.get('kind') != 'authoritative_trial_container_stop_bound':
        raise ToolTimingError('A prospective version 2 stop receipt is required')
    if receipt['result_file'] != _ref(result_file):
        raise ToolTimingError('Stop receipt result bytes differ from this trial')
    identity_ref = receipt['identity_file']
    if _ref(identity_ref['path']) != identity_ref:
        raise ToolTimingError('Live identity receipt bytes changed')
    identity = json.loads(Path(identity_ref['path']).read_text())
    if (identity.get('kind') != 'live_trial_container_identity' or identity.get('schema_version') != 2
            or identity['trial_directory'] != str(Path(result_file).resolve().parent)
            or _ref(identity['trial_config']['path']) != identity['trial_config']
            or not re.fullmatch(r'[a-f0-9]{64}', identity['container_id'])):
        raise ToolTimingError('The exact live identity does not bind this trial')
    live = _container(identity['running_observation'], identity['container_name'])
    if live['Id'] != identity['container_id'] or live.get('Running') is not True or live.get('Restarting') is not False:
        raise ToolTimingError('Container identity was not captured while running')
    if identity['captured_at'] != identity['running_observation']['utc_after']:
        raise ToolTimingError('Live identity capture time is inconsistent')
    for observation in [identity['daemon_observation'], receipt['daemon_before'], receipt['daemon_after']]:
        if _daemon(observation) != identity['daemon_id']:
            raise ToolTimingError('Stop evidence belongs to a different or unresponsive Docker daemon')
    targets = [identity['container_id'], identity['container_name']]
    observations = receipt['container_observations']
    if len(observations) != 2:
        raise ToolTimingError('Both original full ID and trial name require stop observations')
    for target, observation in zip(targets, observations):
        record = _container(observation, target, absent_ok=True)
        if record is not None and (record.get('Id') != identity['container_id'] or record.get('Running') is not False
                or record.get('Restarting') is not False or record.get('Status') not in {'exited', 'dead'}):
            raise ToolTimingError('A live, restarting or reused trial container is not a stop bound')
        if _timestamp(observation['utc_before']) > _timestamp(observation['utc_after']):
            raise ToolTimingError('Stop observation clock order is invalid')
    stop = max(_timestamp(o['utc_after']) for o in observations)
    if _timestamp(receipt['stop_upper_utc']) != stop:
        raise ToolTimingError('The stop upper endpoint differs from authoritative observations')
    return stop, _timestamp(identity['captured_at']), _ref(receipt_file)


def account_trial_tool_time_bounds(result_file, *, stop_receipt_file=None, budget_seconds=1800):
    """A future policy may certify a budget from a safe upper bound, never exactify it."""
    exact = account_trial_tool_time(result_file, budget_seconds=budget_seconds)
    if exact['state'] == 'verified':
        return {**exact, 'policy_version': 2, 'exact_timing_state': 'verified',
                'lower_bound_seconds': exact['cumulative_tool_seconds'],
                'upper_bound_seconds': exact['cumulative_tool_seconds']}
    result = {**exact, 'policy_version': 2, 'method': POLICY_V2['measurement'],
        'state': 'unknown', 'exact_timing_state': 'unknown', 'passed': None,
        'cumulative_tool_seconds': None, 'cumulative_tool_nanoseconds': None,
        'lower_bound_seconds': None, 'upper_bound_seconds': None,
        'exact_parser_problems': exact['problems'], 'problems': []}
    try:
        result_file = Path(result_file).resolve()
        raw_result = json.loads(result_file.read_text())
        window = raw_result['agent_execution']
        started, finished = _timestamp(window['started_at']), _timestamp(window['finished_at'])
        if stop_receipt_file is None:
            raise ToolTimingError('The exact timing is incomplete and no prospective stop receipt exists')
        stop, captured, stop_ref = _validated_stop(result_file, stop_receipt_file)
        if not started <= captured <= finished <= stop:
            raise ToolTimingError('Live capture, agent execution and stop bound are out of order')
        records, calls, outputs, native = [], {}, {}, []
        fingerprints = set()
        for path in sorted((result_file.parent / 'agent/sessions').rglob('*.jsonl')):
            raw = path.read_bytes()
            if not raw.strip():
                raise ToolTimingError('Native session timing evidence is empty')
            for line in raw.decode().splitlines():
                if not line.strip() or line in fingerprints:
                    continue
                fingerprints.add(line)
                record = json.loads(line)
                payload = record.get('payload', {})
                if not isinstance(payload, dict):
                    raise ToolTimingError('Invalid native event structure')
                kind = payload.get('type')
                if record.get('type') == 'response_item' and kind in _CALLS | _OUTPUTS:
                    destination = calls if kind in _CALLS else outputs
                    key = payload.get('call_id')
                    if not isinstance(key, str) or key in destination:
                        raise ToolTimingError('Invalid or conflicting native wrapper identity')
                    destination[key] = record
                if record.get('type') == 'event_msg' and kind == 'item_completed':
                    item = payload.get('item') or {}
                    if item.get('type') not in _MODEL_ITEMS:
                        native.append(record)
                records.append(record)
        if not records or set(outputs) - set(calls):
            raise ToolTimingError('Native evidence is missing or has orphan outputs')
        pending = set(calls) - set(outputs)
        if not pending:
            raise ToolTimingError('Incomplete exact timing is not a supported missing-output tail')
        cutoff = min(_timestamp(calls[key]['timestamp']) for key in pending)
        if captured > cutoff:
            raise ToolTimingError('Container identity was captured after pending execution began')
        prefix, pending_items = [], []
        for record in records:
            payload = record.get('payload', {})
            kind = payload.get('type')
            if record.get('type') == 'response_item' and kind in _CALLS | _OUTPUTS:
                if payload['call_id'] in pending:
                    continue
                if _timestamp(record['timestamp']) > cutoff:
                    raise ToolTimingError('Completed wrappers overlap the pending tail; ownership is unresolved')
            if record in native:
                item = payload['item']
                status = str(item.get('status', 'completed')).lower().replace('_', '')
                start = _number(payload['started_at_ms']) / 1000
                if status in _PENDING:
                    if start < cutoff:
                        raise ToolTimingError('An earlier unresolved process overlaps the pending tail')
                    pending_items.append(record)
                    continue
                end = _number(payload['completed_at_ms']) / 1000
                if end > cutoff:
                    raise ToolTimingError('Completed native work overlaps the pending bound; no double-count credit is inferred')
            prefix.append(record)
        prefix_raw = ''.join(json.dumps(record, separators=(',', ':')) + '\n' for record in prefix).encode()
        if prefix:
            with tempfile.TemporaryDirectory(prefix='sheetsfactory-timing-prefix-') as directory:
                path = Path(directory) / 'derived-prefix.jsonl'
                path.write_bytes(prefix_raw)
                completed = account_tool_time([path], budget_seconds=budget_seconds, execution_window=window)
            if completed['state'] != 'verified':
                raise ToolTimingError('Completed-prefix timing is incomplete: ' + '; '.join(completed['problems']))
            # The raw sessions are the durable evidence; no deleted temp path is
            # represented as a persistent receipt artifact.
            completed.pop('session_files', None)
            lower = _number(completed['cumulative_tool_nanoseconds']) / 1_000_000_000
        else:
            completed = {'state': 'verified', 'tools': [], 'wrapper_call_count': 0, 'cumulative_tool_seconds': 0}
            lower = _number(0)  # Known empty completed prefix; NEVER an assigned pending duration.
        pending_bounds, all_commands = [], []
        for key in sorted(pending):
            record = calls[key]
            start = _timestamp(record['timestamp'])
            if not started <= start <= finished or stop < start:
                raise ToolTimingError('Pending call is outside its actual attempt execution window')
            commands = static_pending_commands(record['payload'])
            interval = stop - start
            pending_bounds.append({'call_id': key, 'call_started_at': record['timestamp'],
                'independent_primitive_launch_upper_count': len(commands),
                'entire_wrapper_interval_upper_seconds': str(interval),
                'primitive_and_uncovered_wrapper_upper_seconds': str(interval * len(commands)),
                'command_sha256': [hashlib.sha256(command.encode()).hexdigest() for command in commands]})
            all_commands += commands
        pending_processes = {}
        for record in pending_items:
            identity = record['payload']['item'].get('id')
            if not isinstance(identity, str) or not identity:
                raise ToolTimingError('Pending native execution has no unique identity')
            command = record['payload']['item'].get('command')
            command = command[-1] if isinstance(command, list) and command else command
            if command not in all_commands:
                raise ToolTimingError('Pending native process is not owned by a declared static command')
            if identity in pending_processes and pending_processes[identity] != command:
                raise ToolTimingError('Conflicting pending native process command')
            pending_processes[identity] = command
        if Counter(pending_processes.values()) - Counter(all_commands):
            raise ToolTimingError('Observed pending process fanout exceeds the static launch bound')
        # Every completed item in the public native stream must have exact
        # prefix timing. Pending stream starts are not invented completions.
        mappings = {'command_execution': 'CommandExecution', 'file_change': 'FileChange',
                    'mcp_tool_call': 'McpToolCall', 'web_search': 'WebSearch'}
        stream = result_file.parent / 'agent/codex.txt'
        expected = set()
        for line in stream.read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                if line.lstrip().startswith('{'):
                    raise ToolTimingError('Truncated native execution stream JSON')
                continue
            item = event.get('item') or {}
            if event.get('type') == 'item.completed' and item.get('type') in mappings:
                expected.add((mappings[item['type']], item.get('id')))
        expected_counts = {kind: sum(item[0] == kind for item in expected) for kind in mappings.values()}
        actual_counts = {kind: sum(item['type'] == kind for item in completed['tools']) for kind in mappings.values()}
        if expected_counts != actual_counts:
            raise ToolTimingError('Native completed stream and exact prefix coverage differ')
        upper = lower + sum((_number(item['primitive_and_uncovered_wrapper_upper_seconds']) for item in pending_bounds), _number(0))
        budget = _number(budget_seconds)
        result.update(state='bounded', passed=True if upper < budget else (False if lower >= budget else None),
            lower_bound_seconds=float(lower), upper_bound_seconds=float(upper), stop_receipt=stop_ref,
            lower_bound_nanoseconds=int(lower * 1_000_000_000), upper_bound_nanoseconds=int(upper * 1_000_000_000),
            completed_prefix={**completed, 'derived_event_subset_sha256': hashlib.sha256(prefix_raw).hexdigest()},
            pending_bounds=pending_bounds, native_stream=_ref(stream),
            upper_bound_may_include_idle_cleanup_time=True,
            proof='Each of m contained primitive intervals and uncovered wrapper time share one interval; their sum is at most m times that interval. Sum all independent pending wrappers; the exact prefix is disjoint.',
            stream_coverage={'expected': expected_counts, 'actual': actual_counts, 'matched': True})
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError) as error:
        result['problems'].append(str(error))
    return result
