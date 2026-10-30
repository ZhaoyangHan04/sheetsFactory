"""Explicit large-workbook resources, without changing the original engine.

Only Docker resource flags and their actual enforcement are added. Workbook
copy/recalculation, security arguments, output validation and cleanup delegate
to the SHA-bound original LibreOfficeEngine implementation.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import threading
import uuid

import yaml

from . import engine as original_engine
from .engine import LibreOfficeEngine, WorkbookEngineError

UPSTREAM_SHA256 = '0f67176358f45e0d0a73edbafd928b8bde305aec3493a576db9040f823c7b700'
DEFAULT_PROFILE = Path(__file__).resolve().parents[3] / 'config/runtime_profiles/entity_group_large_v1.yaml'
ROLES = ('source', 'agent', 'verifier')
LIMIT_KEYS = ('source_physical_formulas', 'max_profile_cells', 'max_dependency_closure_cells', 'full_target_cells')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}


def _canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _write_new(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + '\n')


def load_runtime_profile(value=DEFAULT_PROFILE):
    """Validate the explicit family profile; never apply limits by truncation."""
    p = yaml.safe_load(Path(value).read_text()) if isinstance(value, (str, Path)) else deepcopy(value)
    _require(isinstance(p, dict) and set(p) == {'version', 'kind', 'id', 'image', 'docker_resources',
            'timeouts', 'solver_tool_budget', 'limits'}, 'Runtime profile fields differ')
    _require(type(p['version']) is int and p['version'] == 1
             and p['kind'] == 'workbook_runtime_resource_profile'
             and p['id'] in ('entity_group_large_v1', 'entity_group_large_v2'),
             'Unsupported prospective runtime profile')
    _require(isinstance(p['image'], dict) and set(p['image']) == {'tag', 'id'}
             and type(p['image']['tag']) is str and bool(p['image']['tag'])
             and type(p['image']['id']) is str and re.fullmatch(r'sha256:[0-9a-f]{64}', p['image']['id']),
             'Bind an existing immutable image ID')
    _require(isinstance(p['docker_resources'], dict) and set(p['docker_resources']) == set(ROLES),
             'Source, agent and verifier resources must all be explicit')
    memory_bytes = (8 if p['id'] == 'entity_group_large_v1' else 32) * 1024**3
    for role in ROLES:
        r = p['docker_resources'][role]
        _require(isinstance(r, dict) and set(r) == {'cpus', 'memory_bytes', 'pids_limit'}
                 and type(r['cpus']) is int and r['cpus'] == 2
                 and type(r['memory_bytes']) is int and r['memory_bytes'] == memory_bytes
                 and type(r['pids_limit']) is int and 64 <= r['pids_limit'] <= 4096,
                 'Every role must use the declared 2 CPU, profile memory and finite PID limit')
    _require(all(p['docker_resources'][role] == p['docker_resources']['source'] for role in ROLES),
             'Source, agent and verifier must use identical resources')
    _require(p['timeouts'] == {'workbook_file_seconds': 600, 'verifier_total_seconds': 2400}
             and all(type(v) is int for v in p['timeouts'].values()),
             'Per-file LO and total-verifier timeouts are distinct and explicit')
    b = p['solver_tool_budget']
    _require(isinstance(b, dict) and set(b) == {'seconds', 'strict_less_than', 'exclude_model_response_time', 'parallel_executions'}
             and type(b['seconds']) is int and b['seconds'] == 1800
             and b['strict_less_than'] is True and b['exclude_model_response_time'] is True
             and b['parallel_executions'] == 'sum', 'The solver cumulative tool budget remains strictly below 1800 seconds')
    limits = p['limits']
    _require(isinstance(limits, dict) and set(limits) == {*LIMIT_KEYS, 'truncate'}
             and all(type(limits[k]) is int for k in LIMIT_KEYS)
             and [limits[k] for k in LIMIT_KEYS] == [2000000, 3000000, 3000000, 2000000]
             and limits['truncate'] is False, 'The entire large-workbook scope must fit explicit bounds without truncation')
    return p


def docker_resource_flags(profile, role):
    p = load_runtime_profile(profile)
    _require(role in ROLES, 'Unknown resource role')
    r = p['docker_resources'][role]
    return ['--memory', str(r['memory_bytes']), '--cpus', str(r['cpus']), '--pids-limit', str(r['pids_limit'])]


def validate_workload_counts(profile, counts):
    p = load_runtime_profile(profile)
    _require(isinstance(counts, dict) and set(counts) == set(LIMIT_KEYS), 'All four complete workload counts are required')
    _require(all(type(counts[k]) is int and 0 <= counts[k] <= p['limits'][k] for k in LIMIT_KEYS),
             'A complete workload exceeded its declared bound; do not truncate it')
    return {'counts': dict(counts), 'limits': deepcopy(p['limits']), 'complete_scope_required': True, 'truncation_allowed': False}


class ResourceLibreOfficeEngine(LibreOfficeEngine):
    """Opt-in resource enforcement around the unchanged calculation algorithm."""

    def __init__(self, project_root, profile=DEFAULT_PROFILE, *, role='source', receipt_directory):
        self.profile = load_runtime_profile(profile)
        _require(role in ROLES, 'Unknown resource role')
        _require(_reference(Path(original_engine.__file__))['sha256'] == UPSTREAM_SHA256,
                 'The original engine changed; review this resource adapter before reuse')
        self.role = role
        self.profile_binding = (_reference(profile) if isinstance(profile, (str, Path))
                                else {'canonical_sha256': _canonical(self.profile)})
        self._local = threading.local()
        self._history, self._history_lock = [], threading.Lock()
        root = Path(project_root).resolve()
        receipts = Path(receipt_directory).absolute()
        _require(receipts.resolve() == receipts and receipts.is_relative_to(root),
                 'Resource receipts must use a real directory under the current project root')
        receipts.mkdir(parents=True, exist_ok=True)
        self.receipt_directory = receipts
        super().__init__(root, self.profile['image']['tag'], self.profile['timeouts']['workbook_file_seconds'])

    def ensure_image(self):
        # The original engine may build a missing tag. This opt-in path binds an
        # already approved exact image and never silently builds or substitutes.
        if self.image_id:
            if self.image_id != self.profile['image']['id']:
                raise WorkbookEngineError('The cached image differs from the explicit runtime profile')
            return self.image_id
        if shutil.which('docker') is None:
            raise WorkbookEngineError('Docker is required for resource-bound LibreOffice calculation')
        resolved = super()._run(['docker', 'image', 'inspect', self.image, '--format', '{{.Id}}'], timeout=30).strip()
        if resolved != self.profile['image']['id']:
            raise WorkbookEngineError('The existing image does not match the immutable runtime profile; no fallback is allowed')
        self.image_id = resolved
        return resolved

    def _run(self, command, timeout):
        if command[:2] != ['docker', 'create']:
            return super()._run(command, timeout)
        record = getattr(self._local, 'record', None)
        if record is None:
            raise WorkbookEngineError('Resource-bound container creation needs an active recorded calculation')
        adapted = list(command)
        requested = self.profile['docker_resources'][self.role]
        for flag, key in (('--memory', 'memory_bytes'), ('--cpus', 'cpus'), ('--pids-limit', 'pids_limit')):
            if adapted.count(flag) != 1:
                raise WorkbookEngineError('The upstream Docker resource command changed')
            adapted[adapted.index(flag) + 1] = str(requested[key])
        name = adapted[adapted.index('--name') + 1]
        record['create_command'] = adapted
        result = super()._run(adapted, timeout)
        actual_text = super()._run(['docker', 'inspect', name, '--format', '{{.Id}}\n{{json .HostConfig}}'], timeout=15)
        try:
            container_id, host_text = actual_text.strip().split('\n', 1)
            actual = json.loads(host_text)
            actual = {'cpus_nanoseconds': actual['NanoCpus'], 'memory_bytes': actual['Memory'], 'pids_limit': actual['PidsLimit']}
        except (ValueError, TypeError, KeyError) as error:
            raise WorkbookEngineError('Cannot verify the actual container resource limits') from error
        record['container_id'], record['actual_resources'] = container_id, actual
        expected = {'cpus_nanoseconds': requested['cpus'] * 10**9,
                    'memory_bytes': requested['memory_bytes'], 'pids_limit': requested['pids_limit']}
        if not re.fullmatch(r'[0-9a-f]{64}', container_id) or actual != expected or any(type(v) is not int for v in actual.values()):
            raise WorkbookEngineError('Actual Docker resources differ from the explicit profile; calculation was not started')
        record['actual_resources_verified'] = True
        return result

    def recalculate(self, source, destination):
        if self.timeout_seconds != self.profile['timeouts']['workbook_file_seconds']:
            raise WorkbookEngineError('The per-file timeout differs from the explicit runtime profile')
        source, destination = Path(source).resolve(), Path(destination).resolve()
        call_id = uuid.uuid4().hex
        record = {'kind': 'resource_bound_libreoffice_call', 'version': 1, 'call_id': call_id,
            'started_at': datetime.now(timezone.utc).isoformat(), 'role': self.role,
            'profile': self.profile_binding, 'profile_canonical_sha256': _canonical(self.profile),
            'implementation': _reference(Path(__file__)), 'upstream_engine': _reference(Path(original_engine.__file__)),
            'source': _reference(source) if source.is_file() else {'path': str(source)}, 'destination': str(destination),
            'requested_resources': deepcopy(self.profile['docker_resources'][self.role]),
            'workbook_file_timeout_seconds': self.timeout_seconds, 'verifier_total_timeout_seconds': self.profile['timeouts']['verifier_total_seconds'],
            'solver_tool_budget': deepcopy(self.profile['solver_tool_budget']),
            'actual_resources_verified': False, 'quality_or_difficulty_certified': False}
        _write_new(self.receipt_directory / (call_id + '.started.json'), record)
        previous = getattr(self._local, 'record', None)
        self._local.record = record
        try:
            result = super().recalculate(source, destination)
            if not record['actual_resources_verified']:
                raise WorkbookEngineError('The calculation has no verified actual container resource receipt')
            record.update(status='completed', output=_reference(result), image_id=self.image_id)
            return result
        except BaseException as error:
            record.update(status='failed', error_type=type(error).__name__, error=str(error), image_id=self.image_id)
            raise
        finally:
            self._local.record = previous
            record['finished_at'] = datetime.now(timezone.utc).isoformat()
            terminal = self.receipt_directory / (call_id + '.terminal.json')
            _write_new(terminal, record)
            with self._history_lock:
                self._history.append(_reference(terminal))

    def metadata(self):
        image_id = self.ensure_image()
        with self._history_lock:
            receipts = deepcopy(self._history)
        return {'backend': 'libreoffice_uno_docker', 'image': self.image, 'image_id': image_id,
            'version': None, 'version_probe_performed': False,
            'network': 'none', 'macro_execution': 'never', 'external_updates': 'never',
            'runtime_profile': deepcopy(self.profile), 'runtime_profile_binding': self.profile_binding,
            'role': self.role, 'requested_resources': deepcopy(self.profile['docker_resources'][self.role]),
            'actual_resource_receipts': receipts, 'actual_calculation_calls_recorded': len(receipts),
            'agent_and_other_roles_applied_by_this_engine': False,
            'quality_or_difficulty_certified': False}
