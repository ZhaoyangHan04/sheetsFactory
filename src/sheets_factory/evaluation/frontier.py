"""One-attempt frontier evaluation of immutable Harbor task snapshots.

Harbor's installed Codex agent and the task's actual separate verifier perform
execution and grading. This module changes only how the local CLI is installed.
Development observations never qualify a dataset for confirmation publication.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import traceback
from uuid import uuid4

from dirhash import dirhash
from harbor.agents.installed.codex import Codex, CodexOptions
from harbor.job import Job
from harbor.models.job.config import JobConfig

from ..core.audit import AuditStore
from ..dashboard.server import DashboardServer
from ..llm.codex import CodexCLI, NATIVE_CODEX
from .harbor import inspect_export


MODEL = 'gpt-6.1-sol'
EFFORT = 'xhigh'
MODES = ('financial_modeling', 'debugging')
TASK_FILES = frozenset({
    'instruction.md', 'task.toml', 'export_manifest.json', 'environment/Dockerfile',
    'environment/input.xlsx', 'environment/recalculate', 'solution/solve.sh',
    'solution/reference.xlsx', 'tests/Dockerfile', 'tests/original_input.xlsx',
    'tests/reference.xlsx', 'tests/verify.py', 'tests/test.sh',
})
PROMPT = ('Complete the spreadsheet task using the public instruction and input workbook. '
          'Inspect the workbook with the available tools, implement your solution, and save '
          'the final workbook to the output path required by the task. You may use Python '
          'and the installed recalculate command. Work independently; no reference answer '
          'or private construction evidence is available. Use your full allotted budget '
          'when needed and verify your work before finishing.')


class FrontierError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise FrontierError(message)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def _runtime_provenance(project_root, binary):
    """Bind the runner and native CLI without inspecting any credential file."""
    root, binary = Path(project_root), Path(binary)
    provenance = {'runner': {'path': str(Path(__file__).resolve()), 'sha256': _sha(__file__)},
                  'native_cli': {'path': str(binary), 'sha256': _sha(binary) if binary.is_file() else None}}
    for name, arguments in [('revision', ['rev-parse', 'HEAD']), ('dirty_status', ['status', '--porcelain'])]:
        try:
            result = subprocess.run(['git', '-C', str(root), *arguments], capture_output=True, text=True, timeout=10)
            provenance[name] = result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            provenance[name] = None
    try:
        result = subprocess.run([str(binary), '--version'], capture_output=True, text=True, timeout=10)
        provenance['native_cli']['version'] = result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        provenance['native_cli']['version'] = None
    return provenance


def _persist_failure(run_dir, exc, *, secrets=()):
    """Keep useful setup diagnostics while removing runtime credential values."""
    values = [str(value) for value in secrets if value]
    values += [value for name, value in os.environ.items()
               if re.search(r'(KEY|TOKEN|SECRET|PASSWORD)', name, re.I) and len(value) >= 8]

    def redact(value):
        for secret in sorted(set(values), key=len, reverse=True):
            value = value.replace(secret, '[REDACTED]')
        value = re.sub(r'(?i)(bearer\s+)[^\s\"\']+', r'\1[REDACTED]', value)
        value = re.sub(r'\bsk-[A-Za-z0-9_-]+', '[REDACTED]', value)
        value = re.sub(r'(https?://)[^/@\s]+:[^/@\s]+@', r'\1[REDACTED]@', value)
        return value

    _write(Path(run_dir) / 'private/evaluation_error.json', {
        'exception_type': type(exc).__name__, 'message': redact(str(exc)),
        'traceback': redact(''.join(traceback.format_exception(exc)))})


@contextmanager
def _execution_environment(backend, key):
    """Use backend direct-connect rules for this worker and restore its environment."""
    clean = backend._environment(key)
    clean['SHEETS_FACTORY_API_KEY'] = key
    changed = {name for name in os.environ if name not in clean}
    changed.update({backend.env_key, 'SHEETS_FACTORY_API_KEY'})
    original = {name: os.environ.get(name) for name in changed}
    try:
        for name in changed:
            if name in clean:
                os.environ[name] = clean[name]
            else:
                os.environ.pop(name, None)
        yield
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class LocalCodexOptions(CodexOptions):
    native_binary: str = NATIVE_CODEX


class LocalCodex(Codex):
    """Official Harbor Codex execution with an audited native local installer."""

    options_model = LocalCodexOptions

    def __init__(self, *args, native_binary=NATIVE_CODEX, **kwargs):
        self.native_binary = Path(native_binary).expanduser().resolve()
        super().__init__(*args, **kwargs)

    async def install(self, environment):
        _require(self.native_binary.is_file(), 'Native Codex executable is unavailable')
        await environment.upload_file(self.native_binary, '/usr/local/bin/codex')
        executables = ['/usr/local/bin/codex']
        code_host = self.native_binary.with_name('codex-code-mode-host')
        if code_host.is_file():
            await environment.upload_file(code_host, '/usr/local/bin/codex-code-mode-host')
            executables.append('/usr/local/bin/codex-code-mode-host')
        await self.exec_as_root(environment, command='chmod 755 ' + ' '.join(executables))


def freeze_selection(source_manifest, run_dir, *, phase, task_ids=None, task_root=None,
                     timeout_seconds=1800, model=MODEL, reasoning_effort=EFFORT,
                     prior_selections=(), execution_provenance=None):
    """Freeze all selection decisions before constructing a model request."""
    _require(phase in {'development', 'confirmation'}, 'Explicit evaluation phase is required')
    _require(model == MODEL and reasoning_effort == EFFORT, 'The frontier gate requires gpt-6.1-sol/xhigh')
    _require(900 <= timeout_seconds <= 1800, 'Use a fair 900–1800 second per-task budget')
    source_manifest, run_dir = Path(source_manifest).resolve(), Path(run_dir).resolve()
    source_raw = source_manifest.read_bytes()
    source = json.loads(source_raw)
    requested = set(task_ids or source['selected_task_ids'])
    _require(bool(requested) and len(requested) == len(task_ids or source['selected_task_ids']),
             'Selection must contain distinct task IDs')
    records = {task['task_id']: task for task in source['tasks']}
    _require(requested <= records.keys(), 'Selection contains an unknown task')
    selected = [records[name] for name in sorted(requested)]
    counts = Counter(task['mode'] for task in selected)
    _require(set(counts) <= set(MODES), 'Unexpected task category')
    if phase == 'confirmation':
        _require(all(counts[mode] >= 10 for mode in MODES), 'Confirmation requires at least ten tasks per category')
    _require(not (run_dir / 'selection_manifest.json').exists(), 'Evaluation snapshot already exists; do not rerun Pass@1')
    snapshot = run_dir / 'snapshot/SpreadsheetEval'
    _require(not snapshot.exists(), 'Snapshot directory already exists')
    tasks = []
    for task in selected:
        task_id = task['task_id']
        _require(Path(task_id).name == task_id and task_id not in {'.', '..'}, 'Unsafe task ID')
        origin = (Path(task_root) / task_id if task_root else
                  Path(task.get('task_directory') or source_manifest.parent / 'SpreadsheetEval' / task_id)).resolve()
        _require(origin.is_dir() and not any(path.is_symlink() for path in origin.rglob('*')),
                 'Task must be a real directory without symlinks')
        _require({str(path.relative_to(origin)) for path in origin.rglob('*') if path.is_file()} == TASK_FILES,
                 'Task contains unexpected or missing files')
        binding = inspect_export(origin)
        _require(binding == task['harbor_export_binding'], 'Task differs from its frozen export binding')
        target = snapshot / task_id
        shutil.copytree(origin, target)
        _require(inspect_export(target) == binding and dirhash(origin, 'sha256') == dirhash(target, 'sha256'),
                 'Snapshot copy differs from source')
        tasks.append({key: task.get(key) for key in ('task_id', 'mode', 'revision', 'revision_hash', 'source_id')} | {
            'harbor_export_binding': binding, 'task_directory': str(target),
            'task_checksum': dirhash(target, 'sha256'), 'timeout_seconds': timeout_seconds})
    prior = []
    for location in prior_selections:
        path = Path(location).resolve()
        previous = json.loads(path.read_text())
        checksums = {task['task_checksum'] for task in previous['tasks']}
        overlap = checksums & {task['task_checksum'] for task in tasks}
        _require(phase != 'confirmation' or previous.get('phase') != 'confirmation' or not overlap,
                 'Confirmation may not silently repeat task bytes from a prior confirmation')
        prior.append({'path': str(path), 'sha256': _sha(path), 'phase': previous.get('phase'),
                      'overlapping_task_checksums': sorted(overlap)})
    selection = {'schema_version': 1, 'phase': phase, 'frozen_at': _now(),
        'source_manifest': {'path': str(source_manifest), 'sha256': sha256(source_raw).hexdigest()},
        'selected_task_ids': [task['task_id'] for task in tasks], 'tasks': tasks,
        'model': model, 'reasoning_effort': reasoning_effort, 'timeout_seconds': timeout_seconds,
        'n_attempts': 1, 'prompt': PROMPT, 'prompt_sha256': sha256(PROMPT.encode()).hexdigest(),
        'execution_provenance': execution_provenance,
        'prior_selections': prior,
        'selection_policy': 'All declared source tasks or explicit IDs frozen before observing these attempts.',
        'confirmation_policy': 'Development tasks may be reused with fresh single attempts. Freeze selection before any confirmation results; never reuse development rewards or select by confirmation outcomes. Do not silently repeat unchanged prior confirmation tasks.'}
    _write(run_dir / 'selection_manifest.json', selection)
    return selection


def classify_result(result, task, *, diagnostics=None):
    """Infrastructure never contributes a zero to a difficulty score."""
    actual = (result.get('config') or {}).get('agent') or {}
    if (actual.get('model_name') != MODEL or (actual.get('kwargs') or {}).get('reasoning_effort') != EFFORT
            or actual.get('import_path') != 'sheets_factory.evaluation.frontier:LocalCodex'
            or actual.get('override_timeout_sec') != task.get('timeout_seconds', 1800)
            or ((result.get('agent_info') or {}).get('model_info') or {}).get('name') != MODEL
            or result.get('task_checksum') != task['task_checksum']
            or Path(((result.get('config') or {}).get('task') or {}).get('path', '')).resolve()
                != Path(task['task_directory']).resolve()
            or Path((result.get('task_id') or {}).get('path', '')).resolve()
                != Path(task['task_directory']).resolve()
            or result.get('task_name') != task['harbor_export_binding']['task_name']):
        return 'infrastructure_error', None, 'execution_binding_mismatch'
    if result.get('exception_info'):
        return 'infrastructure_error', None, (result['exception_info'].get('exception_type') or 'harbor_exception')
    rewards = (result.get('verifier_result') or {}).get('rewards') or {}
    reward = rewards.get('reward')
    if type(reward) not in (int, float) or reward not in (0, 1):
        return 'infrastructure_error', None, 'missing_or_nonbinary_reward'
    if (diagnostics or {}).get('reason') == 'verification_error' and diagnostics.get('error_type') not in {
            'ValueError', 'BadZipFile', 'InvalidFileException', 'KeyError'}:
        return 'infrastructure_error', None, 'verifier_execution_error'
    return 'scored', int(reward), None


def summarize(selection, attempts):
    scored = [attempt for attempt in attempts if attempt['status'] == 'scored']
    all_scored = len(scored) == len(selection['tasks']) and len(attempts) == len(selection['tasks'])
    overall = sum(attempt['reward'] for attempt in scored) / len(scored) if all_scored and scored else None
    by_mode = {}
    for mode in MODES:
        group = [task for task in selection['tasks'] if task['mode'] == mode]
        results = [attempt for attempt in scored if attempt['mode'] == mode]
        by_mode[mode] = {'tasks': len(group), 'scored': len(results),
            'successes': sum(attempt['reward'] for attempt in results),
            'pass_at_1': sum(attempt['reward'] for attempt in results) / len(results)
                if results and len(results) == len(group) else None}
    score = {'overall_pass_at_1': overall, 'by_mode': by_mode, 'total_tasks': len(selection['tasks']),
             'scored_tasks': len(scored), 'infrastructure_errors': sum(
                 attempt['status'] == 'infrastructure_error' for attempt in attempts)}
    passed = (selection['phase'] == 'confirmation' and overall is not None and overall <= .2
              and all(by_mode[mode]['tasks'] >= 10 for mode in MODES))
    return score, passed


def collect_attempts(run_dir, selection):
    run_dir = Path(run_dir)
    found = {}
    records = {task['task_id']: task for task in selection['tasks']}
    for path in sorted((run_dir / 'harbor_jobs').glob('*/*/result.json')):
        raw = path.read_bytes()
        result = json.loads(raw)
        name = Path(((result.get('config') or {}).get('task') or {}).get('path', '')).name
        if name not in records:
            continue
        _require(name not in found, 'Multiple attempts found for a Pass@1 task')
        diagnostic_path = path.parent / 'verifier/diagnostics.json'
        diagnostic = json.loads(diagnostic_path.read_text()) if diagnostic_path.is_file() else None
        status, reward, failure = classify_result(result, records[name], diagnostics=diagnostic)
        found[name] = {'task_id': name, 'mode': records[name]['mode'], 'status': status,
            'reward': reward, 'failure_kind': failure, 'harbor_export_binding': records[name]['harbor_export_binding'],
            'task_checksum': result.get('task_checksum'), 'result_file': str(path.resolve()),
            'result_sha256': sha256(raw).hexdigest(), 'started_at': result.get('started_at'),
            'finished_at': result.get('finished_at'), 'agent_result': result.get('agent_result')}
    return list(found.values())


def _job_config(run_dir, selection, *, concurrency, binary, base_url):
    return JobConfig.model_validate({'job_name': 'frontier-pass1', 'jobs_dir': str(Path(run_dir) / 'harbor_jobs'),
        'n_attempts': 1, 'n_concurrent_trials': concurrency, 'quiet': True,
        'retry': {'max_retries': 0}, 'environment': {'type': 'docker'},
        'tasks': [{'path': task['task_directory']} for task in selection['tasks']],
        'extra_instructions': [PROMPT],
        'agents': [{'import_path': 'sheets_factory.evaluation.frontier:LocalCodex',
            'model_name': MODEL, 'base_url': base_url, 'model_api_key_name': 'SHEETS_FACTORY_API_KEY',
            'model_api_format': 'openai_responses',
            'skip_model_parsing': True,
            'override_timeout_sec': selection['timeout_seconds'], 'override_setup_timeout_sec': 180,
            'kwargs': {'reasoning_effort': EFFORT, 'native_binary': str(binary),
                'config': {'model_provider': 'factory', 'model_providers': {'factory': {
                    'name': 'factory', 'base_url': base_url, 'env_key': 'OPENAI_API_KEY', 'wire_api': 'responses'}}}}}]})


async def execute_evaluation(run_dir, selection, audit, *, concurrency=4, backend_config=None):
    """Execute exactly one official Harbor attempt for each frozen task."""
    run_dir = Path(run_dir).resolve()
    backend = CodexCLI(Path(__file__).resolve().parents[3], run_dir, audit, backend_config or {})
    key, endpoint = backend._credentials()
    environment = _execution_environment(backend, key)
    environment.__enter__()
    try:
        config = _job_config(run_dir, selection, concurrency=concurrency, binary=backend.binary, base_url=endpoint)
        _write(run_dir / 'harbor_job_config.json', json.loads(config.model_dump_json()))
        job = await Job.create(config)

        async def progress(event):
            task_id = event.config.task.path.name
            audit.task(task_id, status='running', node='frontier_' + event.event.value,
                       last_progress_at=event.timestamp.isoformat())
            audit.emit('frontier.progress', task_id=task_id, event=event.event.value)
            if event.event.value == 'agent-start':
                audit.emit('llm.started', call_id='frontier-' + str(event.result.id),
                    role='trace_agent', task_id=task_id, stage='frontier', model=MODEL,
                    reasoning_effort=EFFORT, started_at=event.timestamp.isoformat())

        async def completed(event):
            task_id = event.config.task.path.name
            task = next(task for task in selection['tasks'] if task['task_id'] == task_id)
            record = event.result.model_dump(mode='json')
            status, reward, error = classify_result(record, task)
            audit.task(task_id, status='evaluated' if status == 'scored' else 'infrastructure_error',
                       reward=reward, failure_kind=error, node='frontier_finished')
            audit.emit('frontier.task_finished', task_id=task_id, reward=reward, status=status, failure_kind=error)
            usage = record.get('agent_result') or {}
            timing = record.get('agent_execution') or {}
            start = datetime.fromisoformat(timing['started_at']) if timing.get('started_at') else None
            end = datetime.fromisoformat(timing['finished_at']) if timing.get('finished_at') else None
            call = {'call_id': 'frontier-' + str(event.result.id), 'role': 'trace_agent', 'stage': 'frontier',
                'task_id': task_id, 'model': MODEL, 'reasoning_effort': EFFORT,
                'status': 'completed' if status == 'scored' else 'failed',
                'input_tokens': usage.get('n_input_tokens'), 'output_tokens': usage.get('n_output_tokens'),
                'cached_input_tokens': usage.get('n_cache_tokens'),
                'duration_ms': (end - start).total_seconds() * 1000 if start and end else None,
                'source': 'Harbor AgentContext, cumulative across this one attempt'}
            audit.record('calls', call)
            audit.emit('llm.completed' if status == 'scored' else 'llm.failed', **call)

        job.on_agent_started(progress).on_verification_started(progress).on_trial_ended(completed)
        await job.run()
    except Exception as exc:
        _persist_failure(run_dir, exc, secrets=(key,))
        raise
    finally:
        environment.__exit__(None, None, None)


def run_evaluation(source_manifest, run_dir, *, phase, task_ids=None, task_root=None,
                   timeout_seconds=1800, concurrency=4, project_root=None,
                   backend_config=None, prior_selections=(), port=0, execute=None):
    root = Path(project_root or Path(__file__).resolve().parents[3]).resolve()
    run_dir = Path(run_dir).resolve()
    _require(concurrency >= 1, 'Concurrency must be positive')
    _require(not run_dir.exists(), 'Evaluation output directory already exists; never overwrite attempts')
    if phase == 'confirmation':
        # Preserve development provenance while preventing repeated unchanged
        # confirmation gates from being silently sampled until a low score.
        known = set(Path(path).resolve() for path in prior_selections)
        for path in (root / 'outputs').rglob('selection_manifest.json'):
            try:
                prior = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if prior.get('phase') in {'development', 'confirmation'} and prior.get('model') == MODEL:
                known.add(path.resolve())
        prior_selections = sorted(known)
    provenance = _runtime_provenance(root, (backend_config or {}).get('binary', NATIVE_CODEX))
    selection = freeze_selection(source_manifest, run_dir, phase=phase, task_ids=task_ids,
        task_root=task_root, timeout_seconds=timeout_seconds, prior_selections=prior_selections,
        execution_provenance=provenance)
    selection_path = run_dir / 'selection_manifest.json'
    selection_sha = _sha(selection_path)
    started, clock = _now(), time.monotonic()
    audit = AuditStore(run_dir, {'id': run_dir.name, 'status': 'evaluating', 'started_at': started,
        'kind': 'frontier_evaluation', 'phase': phase, 'model': MODEL, 'reasoning_effort': EFFORT,
        'execution_provenance': provenance,
        'financial_target': sum(task['mode'] == 'financial_modeling' for task in selection['tasks']),
        'debugging_target': sum(task['mode'] == 'debugging' for task in selection['tasks'])})
    for task in selection['tasks']:
        audit.task(task['task_id'], mode=task['mode'], source_id=task.get('source_id'),
                   status='scheduled', task_checksum=task['task_checksum'])
    manifest = {'schema_version': 1, 'phase': phase, 'status': 'running', 'started_at': started,
        'finished_at': None, 'selection_manifest': {'path': str(selection_path), 'sha256': selection_sha},
        'model': MODEL, 'reasoning_effort': EFFORT, 'timeout_seconds': timeout_seconds,
        'n_attempts': 1, 'prompt_sha256': selection['prompt_sha256'], 'attempts': [],
        'threshold': .2, 'score': summarize(selection, [])[0], 'gate_passed': False}
    _write(run_dir / 'evaluation_manifest.json', manifest)
    server = DashboardServer(audit.snapshot, audit.events, port=port)
    url = server.start()
    audit.update_run(dashboard_url=url)
    print(json.dumps({'run_directory': str(run_dir), 'dashboard_url': url,
                      'selection_manifest': str(selection_path)}, ensure_ascii=False), flush=True)
    failure = None
    try:
        asyncio.run((execute or execute_evaluation)(run_dir, selection, audit,
                    concurrency=concurrency, backend_config=backend_config))
    except KeyboardInterrupt:
        failure = 'evaluation_interrupted'
    except Exception as exc:
        failure = type(exc).__name__
        if not (run_dir / 'private/evaluation_error.json').is_file():
            _persist_failure(run_dir, exc)
    finally:
        try:
            attempts = collect_attempts(run_dir, selection)
        except (OSError, ValueError, KeyError) as exc:
            attempts, failure = [], type(exc).__name__
        score, passed = summarize(selection, attempts)
        try:
            unchanged = (_sha(selection_path) == selection_sha and all(
                inspect_export(Path(task['task_directory'])) == task['harbor_export_binding']
                and dirhash(task['task_directory'], 'sha256') == task['task_checksum'] for task in selection['tasks']))
        except (OSError, ValueError, KeyError):
            unchanged = False
        complete = score['scored_tasks'] == score['total_tasks'] and not failure and unchanged
        manifest.update(status='completed' if complete else 'infrastructure_failed', finished_at=_now(),
            attempts=attempts, score=score, gate_passed=bool(complete and passed),
            failure_kind=failure or (None if unchanged else 'snapshot_changed'),
            duration_seconds=round(time.monotonic() - clock, 3))
        _write(run_dir / 'evaluation_manifest.json', manifest)
        audit.update_run(status=manifest['status'], finished_at=manifest['finished_at'],
                         wall_seconds=manifest['duration_seconds'], frontier_score=score,
                         gate_passed=manifest['gate_passed'], producer_active=False)
        audit.export()
        server.stop()
    return manifest
