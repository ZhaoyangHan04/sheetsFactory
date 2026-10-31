"""Append-only, trial-scoped Harbor resource evidence; never a scoring input.

Only exact known trial names are queried. No environment fields are requested,
no container is modified, and missing observation cannot become model failure.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid

from ..workbook.resource_engine import load_runtime_profile

SCHEMA = 1
ROLE_SUFFIXES = {'agent': '__env-main-1', 'verifier': '__verifier__trial-main-1'}
CONTAINER_FORMAT = ('{"Id":{{json .Id}},"Name":{{json .Name}},"Image":{{json .Image}},'
                    '"NanoCpus":{{.HostConfig.NanoCpus}},"Memory":{{.HostConfig.Memory}}}')
IMAGE_FORMAT = '{"Id":{{json .Id}},"RootFSLayers":{{json .RootFS.Layers}}}'
IMAGE_ID = re.compile(r'sha256:[0-9a-f]{64}')
FULL_ID = re.compile(r'[0-9a-f]{64}')
TRIAL = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,180}')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _reference(path):
    path = Path(path).absolute()
    _require(path == path.resolve() and path.is_file(), 'A real regular evidence file is required')
    before = path.stat(); digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''): digest.update(block)
    after = path.stat()
    _require((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)
             == (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),
             'An observation artifact changed during hashing')
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': after.st_size}


def _read(record):
    if isinstance(record, (str, Path)):
        record = _reference(record)
    _require(isinstance(record, dict) and set(record) == {'path','sha256','bytes'}
             and _reference(record['path']) == record, 'A referenced resource artifact changed')
    value = json.loads(Path(record['path']).read_text())
    _require(isinstance(value, dict), 'A resource evidence JSON object is required')
    return value


def _write_new(path, value):
    path = Path(path)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False); stream.write('\n')
    return _reference(path)


def _canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _profile_for_task(task):
    task = Path(task).absolute()
    _require(task == task.resolve() and task.is_dir(), 'The actual trial task directory must be real')
    environment = _reference(task / 'environment/runtime_profile.json')
    verifier = _reference(task / 'tests/runtime_profile.json')
    value = _read(environment); profile = load_runtime_profile(value)
    _require(_read(verifier) == profile and profile['id'] == 'entity_group_large_v2'
        and profile['docker_resources']['agent'] == profile['docker_resources']['verifier']
        and profile['docker_resources']['agent']['cpus'] == 2
        and profile['docker_resources']['agent']['memory_bytes'] == 32 * 1024**3,
        'The observed family requires the exact pinned 2-CPU 32-GiB profile')
    manifest = _reference(task / 'export_manifest.json'); export = _read(manifest)
    contract = export.get('metadata', {}).get('resource_runtime')
    _require(isinstance(contract, dict) and contract.get('profile') == profile
             and contract.get('required_local_base_image_id') == profile['image']['id'],
             'The trial resource profile must match its frozen export contract')
    binding = contract.get('profile_binding')
    if isinstance(binding, dict) and 'path' in binding:
        _require(_reference(binding['path']) == binding and load_runtime_profile(binding['path']) == profile,
                 'The pinned source runtime profile changed')
    else:
        _require(binding == {'canonical_sha256': _canonical(profile)}, 'The runtime profile canonical identity changed')
    return {'value': profile, 'canonical_sha256': _canonical(profile), 'environment_profile': environment,
        'verifier_profile': verifier, 'export_manifest': manifest, 'pinned_profile': binding}


def _trial(config_file):
    reference = _reference(config_file); config = _read(reference)
    trial = config.get('trial_name')
    _require(type(trial) is str and TRIAL.fullmatch(trial) is not None and '__' in trial
        and Path(config_file).parent.name == trial, 'An exact safe persisted trial name is required')
    task = Path(config.get('task', {}).get('path', '')).absolute()
    return {'trial_name': trial, 'config': reference, 'task_directory': str(task),
            'profile': _profile_for_task(task)}


def _layers(value):
    return isinstance(value, list) and bool(value) and all(type(v) is str and IMAGE_ID.fullmatch(v) for v in value)


class ResourceObserver:
    """Observe one run's explicit trials, including selection created later.

    ``job_dirs`` defaults to ``run_dir/harbor_jobs`` and may specify exact job
    roots within this run for ordinary oracle/nop controls. ``receipt`` becomes
    an immutable artifact reference at exit. It is not a resource pass flag.
    """
    def __init__(self, run_dir, *, selection=None, job_dirs=None, command_runner=None):
        self.run_dir = Path(run_dir).absolute()
        _require(self.run_dir == self.run_dir.resolve(), 'The observed run cannot pass through a symlink')
        self.selection = selection
        self.job_dirs = tuple(Path(p).absolute() for p in (job_dirs or [self.run_dir / 'harbor_jobs']))
        _require(bool(self.job_dirs) and all(p == p.resolve() and p.is_relative_to(self.run_dir) for p in self.job_dirs),
                 'Only explicit job roots in this run may be observed')
        self.runner = command_runner or subprocess.run
        self.directory = self.run_dir / 'resource_observations' / (_now().replace(':','').replace('+','_') + '-' + uuid.uuid4().hex)
        self.stop = threading.Event(); self.thread = None; self.receipt = None
        self.errors = []; self.observations = []; self.trials = {}; self.image_cache = {}
        self.started = _now(); self.elapsed_start = time.monotonic(); self.finalization_error = None

    def _ensure_directory(self):
        if not self.run_dir.is_dir(): return False
        _require(self.run_dir == self.run_dir.resolve() and self.directory == self.directory.resolve(),
                 'The observation directory changed into a symlink')
        self.directory.mkdir(parents=True, exist_ok=True)
        return True

    def _error(self, operation, category, **safe):
        # Never retain daemon stdout/stderr, arbitrary config fields or Env.
        value = {'observed_at': _now(), 'operation': operation, 'error_category': category, **safe}
        if self._ensure_directory():
            self.errors.append(_write_new(self.directory / ('error-' + uuid.uuid4().hex + '.json'), value))

    def _command(self, command, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= .01: raise TimeoutError('Single-poll resource observation budget exhausted')
        result = self.runner(command, capture_output=True, text=True, timeout=min(5, remaining))
        if result.returncode != 0: raise RuntimeError('Scoped Docker observation command failed')
        return result.stdout

    def _image(self, identity, deadline):
        _require(type(identity) is str and IMAGE_ID.fullmatch(identity), 'Only exact immutable image IDs may be inspected')
        if identity not in self.image_cache:
            value = json.loads(self._command(['docker','image','inspect',identity,'--format',IMAGE_FORMAT], deadline))
            _require(set(value) == {'Id','RootFSLayers'} and value['Id'] == identity and _layers(value['RootFSLayers']),
                     'The actual image identity or complete RootFS layers are missing')
            self.image_cache[identity] = {'image_id': identity, 'rootfs_layers': value['RootFSLayers'], 'observed_at': _now()}
        return self.image_cache[identity]

    def poll_once(self):
        """At most five seconds of scoped commands per poll, without cleanup."""
        deadline = time.monotonic() + 5
        if not self.run_dir.is_dir(): return
        for root in self.job_dirs:
            if not root.is_dir(): continue
            _require(root == root.resolve(), 'A job root became a symlink')
            for config in sorted(root.rglob('config.json')):
                if time.monotonic() >= deadline or self.stop.is_set(): return
                try:
                    # A job config is not a trial. Read only the trial_name key
                    # before requiring the exact parent name and public task.
                    raw = json.loads(config.read_text())
                    if 'trial_name' not in raw: continue
                    trial = _trial(config)
                    previous = self.trials.get(str(config))
                    _require(previous is None or previous['config'] == trial['config'], 'A persisted trial config changed')
                    self.trials[str(config)] = trial
                    prefix = '^/' + re.escape(trial['trial_name'].lower()) + '__'
                    listing = self._command(['docker','ps','-a','--no-trunc','--filter','name=' + prefix,
                                             '--format','{{.ID}}\t{{.Names}}'], deadline)
                    allowed = {'/' + trial['trial_name'].lower() + suffix: role for role,suffix in ROLE_SUFFIXES.items()}
                    for line in listing.splitlines():
                        fields = line.split('\t')
                        if len(fields) != 2: continue
                        identity, name = fields; name = '/' + name.lstrip('/')
                        if name not in allowed: continue
                        _require(FULL_ID.fullmatch(identity) is not None, 'A full sixty-four-character container ID is required')
                        observed = json.loads(self._command(['docker','inspect',identity,'--format',CONTAINER_FORMAT], deadline))
                        _require(set(observed) == {'Id','Name','Image','NanoCpus','Memory'}, 'Unexpected container inspection fields')
                        evidence = {'kind': 'actual_trial_container_resource_observation', 'version': SCHEMA,
                            'observed_at': _now(), 'trial_name': trial['trial_name'], 'trial_config': trial['config'],
                            'task_directory': trial['task_directory'], 'role': allowed[name], 'queried_container_id': identity,
                            'expected_container_name': name, 'container': observed, 'profile': trial['profile'],
                            'base_image': None, 'derived_image': None, 'image_evidence_error': None,
                            'observation_is_not_solver_tool_execution': True, 'score_or_reward_changed': False}
                        try:
                            evidence['base_image'] = self._image(trial['profile']['value']['image']['id'], deadline)
                            evidence['derived_image'] = self._image(observed['Image'], deadline)
                        except (OSError, ValueError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as error:
                            evidence['image_evidence_error'] = type(error).__name__
                        if self._ensure_directory():
                            self.observations.append(_write_new(self.directory / ('container-' + uuid.uuid4().hex + '.json'), evidence))
                except (OSError, ValueError, KeyError, TypeError, RuntimeError, TimeoutError, subprocess.TimeoutExpired) as error:
                    self._error('trial_resource_poll', type(error).__name__, trial_config_path=str(config))

    def _loop(self):
        while not self.stop.is_set():
            try: self.poll_once()
            except Exception as error:
                try: self._error('observer_poll', type(error).__name__)
                except Exception: pass
            self.stop.wait(1)

    def __enter__(self):
        _require(self.thread is None, 'An observer context cannot be restarted')
        # Do not create run_dir: the unchanged runner requires a fresh output.
        self.thread = threading.Thread(target=self._loop, name='scoped-resource-observer', daemon=True)
        self.thread.start(); return self

    def __exit__(self, exc_type, exc, traceback):
        self.stop.set()
        if self.thread is not None: self.thread.join(timeout=6)
        try:
            if not self._ensure_directory(): return False
            bound_trials = []
            for trial in self.trials.values():
                config = Path(trial['config']['path']); result = config.with_name('result.json')
                bound_trials.append({'trial_name': trial['trial_name'], 'config': trial['config'],
                    'config_unchanged_at_exit': _reference(config) == trial['config'],
                    'result': _reference(result) if result.is_file() else None,
                    'task_directory': trial['task_directory']})
            selection_file = self.run_dir / 'selection_manifest.json'
            if not selection_file.is_file() and isinstance(self.selection, (str,Path)):
                selection_file = Path(self.selection)
            evaluation_file = self.run_dir / 'evaluation_manifest.json'
            snapshots = {}
            for label, path in (('selection', selection_file), ('evaluation', evaluation_file)):
                if path.is_file():
                    raw = path.read_bytes()
                    copied = self.directory / (label + '-at-exit.json')
                    with copied.open('xb') as stream: stream.write(raw)
                    snapshots[label] = _reference(copied)
                    _require(snapshots[label]['sha256'] == _reference(path)['sha256'],
                             'A final manifest changed while its observation snapshot was written')
            self.receipt = _write_new(self.directory / 'receipt.json', {
                'kind': 'scoped_harbor_resource_observation_session', 'version': SCHEMA,
                'run_directory': str(self.run_dir), 'started_at': self.started, 'finished_at': _now(),
                'elapsed_seconds': time.monotonic() - self.elapsed_start,
                'implementation': _reference(__file__), 'job_directories': [str(p) for p in self.job_dirs],
                'selection': _reference(selection_file) if selection_file.is_file() else None,
                'evaluation': _reference(evaluation_file) if evaluation_file.is_file() else None,
                'selection_snapshot': snapshots.get('selection'), 'evaluation_snapshot': snapshots.get('evaluation'),
                'trials': bound_trials, 'observations': self.observations, 'observation_errors': self.errors,
                'observer_thread_stopped': self.thread is None or not self.thread.is_alive(),
                'wrapped_operation_exception_category': exc_type.__name__ if exc_type else None,
                'observer_does_not_modify_model_results': True, 'solver_tool_execution_seconds_attributed': 0,
                'observation_wall_time_is_not_solver_tool_execution': True,
                'missing_evidence_is_not_a_model_failure': True, 'resource_completeness_must_be_validated_separately': True})
        except Exception as error:
            self.finalization_error = type(error).__name__
        return False


def _as_reference(record):
    return _reference(record) if isinstance(record,(str,Path)) else record


def validate_trial_observations(trial_config, result, *, receipts, expected_profile=None, expected_task_directory=None):
    """Validate actual both-role evidence, independent of rewards or scores."""
    problems = []; covered = set(); evidence = []; mismatched = False
    try:
        config_ref, result_ref = _as_reference(trial_config), _as_reference(result)
        config, actual_result = _read(config_ref), _read(result_ref)
        trial = _trial(config_ref['path']); task = Path(trial['task_directory'])
        _require(actual_result.get('trial_name') == trial['trial_name']
            and Path(result_ref['path']).parent == Path(config_ref['path']).parent
            and Path(actual_result.get('config',{}).get('task',{}).get('path','')).absolute() == task,
            'The actual result and config belong to different trials or tasks')
        if expected_task_directory is not None:
            _require(task == Path(expected_task_directory).absolute(), 'The actual result uses another staged task')
        profile = trial['profile']['value']
        if expected_profile is not None:
            if isinstance(expected_profile,dict) and set(expected_profile)=={'path','sha256','bytes'}:
                _require(_reference(expected_profile['path']) == expected_profile, 'The expected runtime profile changed')
                expected_profile = load_runtime_profile(expected_profile['path'])
            else: expected_profile = load_runtime_profile(expected_profile)
            _require(profile == expected_profile, 'The expected pinned runtime profile differs')
        # Publication verifies the complete export; polling only reads its small
        # profile/manifest so it cannot repeatedly hash huge workbook inputs.
        from .resource_harbor import inspect_resource_export
        export_binding = inspect_resource_export(task)
        _require(actual_result.get('task_name') == export_binding['task_name'], 'The actual result task name differs')
        for receipt_ref in receipts:
            receipt_ref = _as_reference(receipt_ref); session = _read(receipt_ref)
            _require(session.get('kind') == 'scoped_harbor_resource_observation_session'
                and type(session.get('version')) is int and session['version'] == SCHEMA
                and session.get('implementation') == _reference(__file__)
                and session.get('observer_thread_stopped') is True
                and session.get('observer_does_not_modify_model_results') is True
                and session.get('missing_evidence_is_not_a_model_failure') is True,
                'An immutable stopped resource-observer session is required')
            bound = [t for t in session['trials'] if t['config'] == config_ref]
            if not bound: continue
            _require(len(bound) == 1 and bound[0].get('result') == result_ref
                and bound[0].get('config_unchanged_at_exit') is True,
                'The observer session lacks the exact final config/result SHA binding')
            receipt_root = Path(receipt_ref['path']).parent
            _require(receipt_root.is_relative_to(Path(session['run_directory']) / 'resource_observations'),
                     'An observer receipt escaped its run')
            _require(any(Path(config_ref['path']).is_relative_to(Path(root))
                and Path(root).is_relative_to(Path(session['run_directory']))
                for root in session['job_directories']), 'The actual trial escaped the explicitly observed job roots')
            for error_ref in session['observation_errors']:
                _require(Path(error_ref['path']).parent == receipt_root, 'A poll error escaped its immutable session')
                _read(error_ref)
            for observation_ref in session['observations']:
                _require(Path(observation_ref['path']).parent == receipt_root, 'An observation escaped its immutable session')
                observation = _read(observation_ref)
                if observation.get('trial_config') != config_ref: continue
                role = observation.get('role'); actual = observation.get('container',{})
                _require(role in ROLE_SUFFIXES and observation.get('trial_name') == trial['trial_name']
                    and observation.get('task_directory') == str(task)
                    and observation.get('profile') == trial['profile'], 'An observation is bound to another profile or trial')
                expected_name = '/' + trial['trial_name'].lower() + ROLE_SUFFIXES[role]
                capacity = profile['docker_resources'][role]
                valid = (observation.get('kind') == 'actual_trial_container_resource_observation'
                    and type(observation.get('version')) is int and observation['version'] == SCHEMA
                    and set(actual) == {'Id','Name','Image','NanoCpus','Memory'}
                    and FULL_ID.fullmatch(observation.get('queried_container_id',''))
                    and IMAGE_ID.fullmatch(actual.get('Image',''))
                    and observation.get('observation_is_not_solver_tool_execution') is True
                    and observation.get('score_or_reward_changed') is False
                    and actual.get('Id') == observation['queried_container_id']
                    and actual.get('Name') == observation.get('expected_container_name') == expected_name
                    and type(actual.get('NanoCpus')) is int and actual['NanoCpus'] == capacity['cpus'] * 10**9
                    and type(actual.get('Memory')) is int and actual['Memory'] == capacity['memory_bytes'])
                if not valid:
                    mismatched = True; problems.append('Actual container identity/name/CPU/RAM mismatch for ' + role); continue
                base, image = observation.get('base_image'), observation.get('derived_image')
                if not isinstance(base,dict) or not isinstance(image,dict): continue
                ancestry = (base.get('image_id') == profile['image']['id'] and _layers(base.get('rootfs_layers'))
                    and image.get('image_id') == actual.get('Image') and _layers(image.get('rootfs_layers'))
                    and image['rootfs_layers'][:len(base['rootfs_layers'])] == base['rootfs_layers'])
                if not ancestry:
                    mismatched = True; problems.append('Actual image RootFS ancestry mismatch for ' + role); continue
                covered.add(role); evidence.append(observation_ref)
        missing = sorted(set(ROLE_SUFFIXES) - covered)
        problems += ['Missing actual ' + role + ' resource/ancestry evidence' for role in missing]
        complete = not missing
        return {'passed': complete and not problems, 'complete': complete,
            'status': 'resource_mismatch' if mismatched else 'complete' if not problems else 'resource_evidence_incomplete',
            'problems': problems, 'trial_name': trial['trial_name'], 'trial_config': config_ref, 'result': result_ref,
            'roles_observed': sorted(covered), 'observations': evidence, 'runtime_profile': trial['profile'],
            'raw_reward_or_score_modified': False, 'missing_evidence_is_not_a_model_failure': True}
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as error:
        problems.append('Resource evidence binding incomplete: ' + type(error).__name__)
        return {'passed': False, 'complete': False, 'status': 'resource_evidence_incomplete', 'problems': problems,
                'raw_reward_or_score_modified': False, 'missing_evidence_is_not_a_model_failure': True}


def validate_observation_receipt(run_dir, selection, evaluation):
    """Require both roles for every persisted actual selected-task result."""
    run_dir = Path(run_dir).absolute(); problems = []; validations = []
    try:
        selection_ref = _reference(run_dir / 'selection_manifest.json')
        evaluation_ref = _reference(run_dir / 'evaluation_manifest.json')
        selected = _read(selection_ref); assessed = _read(evaluation_ref)
        _require((selection if isinstance(selection,dict) and 'tasks' in selection else _read(_as_reference(selection))) == selected
            and (evaluation if isinstance(evaluation,dict) and 'attempts' in evaluation else _read(_as_reference(evaluation))) == assessed,
            'The current selection or evaluation differs from publication inputs')
        tasks = {t['task_id']:t for t in selected['tasks']}
        receipts = []
        # A resume preserves every old evaluation in the runner's existing
        # immutable history chain. Old observation sessions remain usable only
        # through those actual previous-manifest hashes, never a claimed alias.
        allowed_evaluations = {evaluation_ref['sha256']}
        for previous in assessed.get('infrastructure_retries', []):
            prior = _reference(previous['previous_manifest_file'])
            _require(prior['sha256'] == previous['previous_manifest_sha256']
                and Path(prior['path']).is_relative_to(run_dir / 'private/evaluation_history'),
                'A runner-preserved previous evaluation changed')
            allowed_evaluations.add(prior['sha256'])
        current_anchor = False
        for path in sorted((run_dir / 'resource_observations').glob('*/receipt.json')):
            ref = _reference(path); session = _read(ref)
            if session.get('selection') != selection_ref: continue
            bound_evaluation = session.get('evaluation') or {}
            if bound_evaluation.get('sha256') not in allowed_evaluations: continue
            _require(bound_evaluation.get('path') == str(run_dir / 'evaluation_manifest.json'),
                     'An evaluation observation points outside the actual run')
            for label, expected in (('selection', selection_ref), ('evaluation', bound_evaluation)):
                snap = session[label + '_snapshot']
                _require(Path(snap['path']).parent == path.parent
                    and _reference(snap['path']) == snap
                    and snap['sha256'] == expected['sha256'] and snap['bytes'] == expected['bytes'],
                    'An immutable observer manifest snapshot changed')
            receipts.append(ref)
            current_anchor |= bound_evaluation == evaluation_ref
        _require(bool(receipts) and current_anchor, 'No observation session binds this exact final evaluation')
        results = {}
        for attempt in assessed.get('attempts',[]) + assessed.get('infra_history',[]):
            if attempt.get('result_file') and attempt.get('task_id') in tasks:
                results[str(Path(attempt['result_file']).absolute())] = attempt
        _require(bool(results), 'No actual selected trial result is recorded')
        for path, attempt in results.items():
            result_ref = _reference(path)
            _require(result_ref['sha256'] == attempt['result_sha256'], 'An actual evaluated result changed')
            expected = tasks[attempt['task_id']]
            checked = validate_trial_observations(Path(path).with_name('config.json'), result_ref,
                receipts=receipts, expected_task_directory=expected['task_directory'])
            validations.append(checked)
        complete = all(v['complete'] for v in validations)
        passed = complete and all(v['passed'] for v in validations)
        return {'passed':passed,'complete':complete,'status':'complete' if passed else 'resource_evidence_incomplete',
            'problems':[p for v in validations for p in v['problems']], 'trials':validations,
            'selection':selection_ref,'evaluation':evaluation_ref,'observation_receipts':receipts,
            'raw_reward_or_score_modified':False,'missing_evidence_is_not_a_model_failure':True}
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as error:
        problems.append('Resource evidence binding incomplete: ' + type(error).__name__)
        return {'passed':False,'complete':False,'status':'resource_evidence_incomplete','problems':problems,
            'raw_reward_or_score_modified':False,'missing_evidence_is_not_a_model_failure':True}
