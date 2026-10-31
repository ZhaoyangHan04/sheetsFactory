"""Opt-in LibreOffice worker cap around the unchanged resource engine.

The calculation, timeout and cleanup stay in the pinned base implementations.
Only container creation receives MAX_CONCURRENCY=2. Filtered inspections of the
same full container ID verify that value before start and after the exit check.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re

from . import resource_engine as base
from .engine import WorkbookEngineError

RESOURCE_ENGINE_SHA256 = 'cc4fb863740a0fc403a5947a52fa1c2e644b81b75c358e2a3cbf47e7d33a9c8d'
VARIABLE = 'MAX_CONCURRENCY'
VALUE = '2'
ENV_FORMAT = '{{.Id}}\n{{range .Config.Env}}{{if eq (index (split . "=") 0) "MAX_CONCURRENCY"}}{{println .}}{{end}}{{end}}'


def _require(value, message):
    if not value:
        raise WorkbookEngineError(message)


def _adapter_reference():
    _require(base._reference(base.__file__)['sha256'] == RESOURCE_ENGINE_SHA256,
             'The resource engine changed; review the thread-cap adapter')
    return base._reference(__file__)


def _cap_assignments(command):
    result = []
    for index, token in enumerate(command):
        if token in ('--env', '-e'):
            _require(index+1 < len(command), 'An environment option has no value')
            value = command[index+1]
        elif token.startswith('--env='):
            value = token[len('--env='):]
        elif token.startswith('-e') and token != '-e':
            value = token[2:]
        else:
            continue
        if value.split('=', 1)[0] == VARIABLE:
            result.append(value)
    return result


def _inspect_command(container_id):
    return ['docker', 'inspect', container_id, '--format', ENV_FORMAT]


class ThreadCappedResourceLibreOfficeEngine(base.ResourceLibreOfficeEngine):
    def __init__(self, *args, **kwargs):
        _adapter_reference()
        super().__init__(*args, **kwargs)

    def _inspect_cap(self, record, stage, exit_code=None):
        container_id = record.get('container_id', '')
        _require(re.fullmatch(r'[0-9a-f]{64}', container_id), 'A full owned container ID is required')
        command = _inspect_command(container_id)
        text = super()._run(command, timeout=15)
        lines = text.splitlines()
        evidence = {'stage': stage, 'inspected_at': datetime.now(timezone.utc).isoformat(),
                    'container_id': lines[0] if lines else '', 'variable': VARIABLE,
                    'values': lines[1:], 'inspect_command': command}
        if exit_code is not None:
            evidence['exit_code_observed'] = exit_code
        record['thread_cap_'+stage] = evidence
        _require(evidence['container_id'] == container_id and evidence['values'] == [VARIABLE+'='+VALUE],
                 'The actual owned container must have exactly one MAX_CONCURRENCY=2')

    def _run(self, command, timeout):
        if command[:2] == ['docker', 'create']:
            record = getattr(self._local, 'record', None)
            _require(record is not None, 'Thread-capped creation requires an active resource call')
            _require(not _cap_assignments(command), 'The upstream create command already supplies the worker cap')
            adapted = list(command)
            image = self.profile['image']['id']
            _require(adapted.count(image) == 1, 'The exact create image position changed')
            index = adapted.index(image)
            adapted[index:index] = ['--env', VARIABLE+'='+VALUE]
            record['thread_cap_adapter'] = _adapter_reference()
            record['thread_cap_verified'] = False
            result = super()._run(adapted, timeout)
            self._inspect_cap(record, 'before')
            return result
        if command[:2] == ['docker', 'inspect'] and command[-1:] == ['{{.State.ExitCode}}']:
            record = getattr(self._local, 'record', None)
            _require(record is not None and 'thread_cap_before' in record,
                     'The exit inspection needs the verified worker-cap creation')
            create = record['create_command']
            name = create[create.index('--name')+1]
            _require(command == ['docker', 'inspect', name, '--format', '{{.State.ExitCode}}'],
                     'The exit inspection must belong to the current container')
            result = super()._run(command, timeout)
            self._inspect_cap(record, 'after', result.strip())
            record['thread_cap_verified'] = True
            return result
        return super()._run(command, timeout)


def validate_capped_call(call, runtime_record, frozen, *, resource_validator):
    """Require the existing complete resource proof and this extra cap proof."""
    evidence = resource_validator(call, runtime_record, frozen)
    _require(base._reference(runtime_record['path']) == runtime_record, 'The thread-cap runtime receipt changed')
    actual = json.loads(Path(runtime_record['path']).read_text())
    adapter = _adapter_reference()
    _require(actual.get('thread_cap_adapter') == adapter and actual.get('thread_cap_verified') is True
             and _cap_assignments(actual.get('create_command', [])) == [VARIABLE+'='+VALUE],
             'A current verified thread-cap adapter and exact create assignment are required')
    container_id = actual.get('container_id', '')
    _require(re.fullmatch(r'[0-9a-f]{64}', container_id), 'The capped proof needs a full owned container ID')
    start = datetime.fromisoformat(actual['started_at'])
    finish = datetime.fromisoformat(actual['finished_at'])
    previous = start
    for stage in ('before', 'after'):
        item = actual.get('thread_cap_'+stage, {})
        _require(item.get('stage') == stage and item.get('container_id') == container_id
                 and item.get('variable') == VARIABLE and item.get('values') == [VARIABLE+'='+VALUE]
                 and item.get('inspect_command') == _inspect_command(container_id),
                 'Both filtered worker-cap inspections must bind the same full container ID')
        timestamp = datetime.fromisoformat(item['inspected_at'])
        _require(all(t.tzinfo is not None for t in (start, timestamp, finish))
                 and previous <= timestamp <= finish, 'Worker-cap inspection order or timestamps changed')
        previous = timestamp
    _require(actual['thread_cap_after'].get('exit_code_observed') == '0',
             'A normal exit must precede the final worker-cap inspection')
    return {**evidence, 'thread_cap_adapter': adapter, 'thread_cap_before': actual['thread_cap_before'],
            'thread_cap_after': actual['thread_cap_after'], 'thread_cap_verified': True}
