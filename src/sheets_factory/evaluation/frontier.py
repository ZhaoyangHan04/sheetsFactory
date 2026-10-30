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
import fcntl
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
from .tool_time import account_trial_tool_time


MODEL = 'gpt-6.1-sol'
EFFORT = 'xhigh'
TOOL_TIME_POLICY = {'budget_seconds': 1800, 'strict_less_than': True,
                    'exclude_model_response_time': True, 'parallel_executions': 'sum',
                    'measurement': 'native_tool_events_and_wrapper_intervals'}
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
          'when needed and verify your work before finishing. Cumulative tool execution '
          'time must be strictly less than 1800 seconds. Model reasoning and response '
          'generation do not count; parallel tool executions add separately. Reaching '
          'or exceeding this tool budget makes the attempt unsuccessful.')


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
                  'tool_time_parser': {'path': str(Path(__file__).with_name('tool_time.py').resolve()),
                                       'sha256': _sha(Path(__file__).with_name('tool_time.py'))},
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
            'task_checksum': dirhash(target, 'sha256'), 'timeout_seconds': timeout_seconds,
            'tool_time_policy': dict(TOOL_TIME_POLICY)})
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
        'tool_time_policy': dict(TOOL_TIME_POLICY),
        'n_attempts': 1, 'prompt': PROMPT, 'prompt_sha256': sha256(PROMPT.encode()).hexdigest(),
        'infrastructure_retry_policy': {'max_retries': 2, 'scored_attempts_per_task': 1,
                                        'never_retry_scored': True},
        'execution_provenance': execution_provenance,
        'prior_selections': prior,
        'selection_policy': 'All declared source tasks or explicit IDs frozen before observing these attempts.',
        'confirmation_policy': 'Development tasks may be reused with fresh single attempts. Freeze selection before any confirmation results; never reuse development rewards or select by confirmation outcomes. Do not silently repeat unchanged prior confirmation tasks.'}
    _write(run_dir / 'selection_manifest.json', selection)
    return selection


def _matches_execution(result, task):
    actual = (result.get('config') or {}).get('agent') or {}
    return not (actual.get('model_name') != MODEL or (actual.get('kwargs') or {}).get('reasoning_effort') != EFFORT
            or actual.get('import_path') != 'sheets_factory.evaluation.frontier:LocalCodex'
            or actual.get('override_timeout_sec') != task.get('timeout_seconds', 1800)
            or ((result.get('agent_info') or {}).get('model_info') or {}).get('name') != MODEL
            or result.get('task_checksum') != task['task_checksum']
            or Path(((result.get('config') or {}).get('task') or {}).get('path', '')).resolve()
                != Path(task['task_directory']).resolve()
            or Path((result.get('task_id') or {}).get('path', '')).resolve()
                != Path(task['task_directory']).resolve()
            or result.get('task_name') != task['harbor_export_binding']['task_name'])


def _ordinary_verifier_result(diagnostics):
    return ((diagnostics or {}).get('reason') != 'verification_error'
            or diagnostics.get('error_type') in {'ValueError', 'BadZipFile', 'InvalidFileException', 'KeyError'})


def review_agent_timeout(result, task, *, result_file, diagnostics=None):
    """Reproduce a narrow, file-bound review of normal agent budget exhaustion.

    A timeout alone never supplies a score. The actual separate verifier must
    finish and report a binary reward after a productive, healthy agent run.
    Ordinary failed tool commands are valid agent activity, not provider errors.
    """
    if ((result.get('exception_info') or {}).get('exception_type') != 'AgentTimeoutError'
            or not _matches_execution(result, task)):
        return None
    reward = ((result.get('verifier_result') or {}).get('rewards') or {}).get('reward')
    usage = result.get('agent_result') or {}
    multiplier = (result.get('config') or {}).get('agent_timeout_multiplier')
    # Harbor serializes an unset override as null; the task's original budget
    # applies in that case, just as when the field is absent.
    multiplier = 1 if multiplier is None else multiplier
    if (type(reward) not in (int, float) or reward not in (0, 1)
            or type(usage.get('n_input_tokens')) is not int or usage['n_input_tokens'] <= 0
            or type(usage.get('n_output_tokens')) is not int or usage['n_output_tokens'] <= 0
            or multiplier != 1):
        return None
    timing, verification = result.get('agent_execution') or {}, result.get('verifier') or {}
    try:
        times = [datetime.fromisoformat(value) for value in [timing['started_at'], timing['finished_at'],
                 verification['started_at'], verification['finished_at']]]
        if any(stamp.tzinfo is None for stamp in times):
            return None
        elapsed = (times[1] - times[0]).total_seconds()
        budget = task.get('timeout_seconds', 1800)
        if elapsed < budget - 1 or not times[1] <= times[2] <= times[3]:
            return None
        path = Path(result_file).resolve()
        if json.loads(path.read_text()) != result:
            return None
        log = path.parent / 'agent/codex.txt'
        diagnostic_file = path.parent / 'verifier/diagnostics.json'
        actual_diagnostics = json.loads(diagnostic_file.read_text())
        if diagnostics is not None and diagnostics != actual_diagnostics:
            return None
        if (actual_diagnostics.get('reward') != reward or not _ordinary_verifier_result(actual_diagnostics)
                or actual_diagnostics.get('reason') not in {'matched', 'value_or_modified_set_mismatch',
                                                           'sheet_structure_mismatch', 'verification_error'}
                or float((path.parent / 'verifier/reward.txt').read_text().strip()) != reward):
            return None
        events = []
        for line in log.read_text(errors='replace').splitlines():
            try:
                event = json.loads(line)
                if isinstance(event, dict):
                    events.append(event)
            except ValueError:
                continue
    except (OSError, ValueError, KeyError, TypeError):
        return None
    completed, last_activity, last_provider_error = 0, -1, -1
    for index, event in enumerate(events):
        kind = event.get('type')
        if kind in {'turn.failed', 'response.failed'}:
            return None
        if kind == 'error' and re.search(r'reconnect|stream disconnect|error sending request|'
                r'network|connection|service unavailable|rate limit|unauthorized|authentication|'
                r'API key|request timed out|HTTP\s*(?:429|500|502|503|504)\b',
                str(event.get('message', '')), re.I):
            last_provider_error = index
        item = event.get('item') or {}
        if kind == 'item.completed' and item.get('type') == 'command_execution':
            completed += 1
            last_activity = index
            if re.search(r'(?:recalculate[^\n]{0,120}(?:Permission denied|command not found|No such file))|'
                         r'(?:Permission denied[^\n]{0,120}recalculate)',
                         str(item.get('aggregated_output', '')), re.I):
                return None
    if not completed or last_provider_error > last_activity:
        return None
    return {'classification': 'normal_agent_budget_exhaustion', 'budget_seconds': budget,
            'agent_elapsed_seconds': round(elapsed, 3), 'model_output_tokens': usage['n_output_tokens'],
            'completed_command_events': completed, 'reward': int(reward),
            'result_file': str(path), 'result_sha256': _sha(path),
            'native_log_file': str(log), 'native_log_sha256': _sha(log),
            'diagnostics_file': str(diagnostic_file), 'diagnostics_sha256': _sha(diagnostic_file)}


def classify_result(result, task, *, diagnostics=None, timeout_review=None):
    """Infrastructure never contributes a zero to a difficulty score."""
    if not _matches_execution(result, task):
        return 'infrastructure_error', None, 'execution_binding_mismatch'
    if result.get('exception_info'):
        exception_type = result['exception_info'].get('exception_type') or 'harbor_exception'
        if not (exception_type == 'AgentTimeoutError' and timeout_review
                and timeout_review.get('classification') == 'normal_agent_budget_exhaustion'):
            return 'infrastructure_error', None, exception_type
    rewards = (result.get('verifier_result') or {}).get('rewards') or {}
    reward = rewards.get('reward')
    if type(reward) not in (int, float) or reward not in (0, 1):
        return 'infrastructure_error', None, 'missing_or_nonbinary_reward'
    if not _ordinary_verifier_result(diagnostics):
        return 'infrastructure_error', None, 'verifier_execution_error'
    return 'scored', int(reward), None


def apply_tool_time_policy(entry, selection):
    """Preserve raw verifier rewards; missing timing cannot authorize resampling."""
    policy = selection.get('tool_time_policy')
    if not policy or entry['status'] != 'scored':
        return entry
    _require(policy == TOOL_TIME_POLICY, 'Unsupported cumulative tool-time policy')
    entry['raw_verifier_reward'] = entry['reward']
    receipt = account_trial_tool_time(entry['result_file'], budget_seconds=policy['budget_seconds'])
    entry['tool_time'] = receipt
    if receipt['state'] != 'verified':
        entry.update(status='evidence_incomplete', reward=None, failure_kind='native_tool_timing_incomplete')
    elif receipt['passed'] is False:
        entry.update(reward=0, failure_kind='cumulative_tool_budget_exhausted')
    return entry


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
    timed = [attempt['tool_time']['cumulative_tool_seconds'] for attempt in attempts
             if (attempt.get('tool_time') or {}).get('state') == 'verified']
    score = {'overall_pass_at_1': overall, 'by_mode': by_mode, 'total_tasks': len(selection['tasks']),
             'scored_tasks': len(scored), 'infrastructure_errors': sum(
                 attempt['status'] == 'infrastructure_error' for attempt in attempts),
             'incomplete_timing_evidence': sum(attempt['status'] == 'evidence_incomplete' for attempt in attempts),
             'tool_budget_failures': sum(attempt.get('failure_kind') == 'cumulative_tool_budget_exhausted'
                                         for attempt in attempts),
             'timed_attempts': len(timed), 'known_tool_seconds': sum(timed),
             'cumulative_tool_seconds': sum(timed) if timed and len(timed) == len(attempts) else None}
    passed = (selection['phase'] == 'confirmation' and overall is not None and overall <= .2
              and all(by_mode[mode]['tasks'] >= 10 for mode in MODES))
    return score, passed


def collect_attempts(run_dir, selection, *, include_infrastructure_history=False):
    run_dir = Path(run_dir)
    found = {}
    records = {task['task_id']: task for task in selection['tasks']}
    for path in sorted((run_dir / 'harbor_jobs').glob('*/*/result.json')):
        raw = path.read_bytes()
        result = json.loads(raw)
        name = Path(((result.get('config') or {}).get('task') or {}).get('path', '')).name
        if name not in records:
            continue
        diagnostic_path = path.parent / 'verifier/diagnostics.json'
        diagnostic = json.loads(diagnostic_path.read_text()) if diagnostic_path.is_file() else None
        timeout_review = review_agent_timeout(result, records[name], result_file=path, diagnostics=diagnostic)
        status, reward, failure = classify_result(result, records[name], diagnostics=diagnostic,
                                                  timeout_review=timeout_review)
        entry = {'task_id': name, 'mode': records[name]['mode'], 'status': status,
            'reward': reward, 'failure_kind': failure, 'harbor_export_binding': records[name]['harbor_export_binding'],
            'task_checksum': result.get('task_checksum'), 'result_file': str(path.resolve()),
            'result_sha256': sha256(raw).hexdigest(), 'started_at': result.get('started_at'),
            'finished_at': result.get('finished_at'), 'agent_result': result.get('agent_result'),
            'job_name': path.parent.parent.name, 'trial_name': path.parent.name}
        if timeout_review is not None:
            entry['exception_resolution'] = timeout_review
        apply_tool_time_policy(entry, selection)
        found.setdefault(name, []).append(entry)
    selected, history = [], []
    for entries in found.values():
        scored = [entry for entry in entries if entry['status'] in {'scored', 'evidence_incomplete'}]
        _require(len(scored) <= 1, 'Multiple scored attempts found for a Pass@1 task')
        _require(len({entry['job_name'] for entry in entries}) == len(entries),
                 'Multiple attempts for one task in a Harbor job')
        selected.append(scored[0] if scored else sorted(entries, key=lambda entry: (
            entry.get('finished_at') or '', entry['result_file']))[-1])
        history.extend(entry for entry in entries if entry['status'] == 'infrastructure_error')
    return (selected, history) if include_infrastructure_history else selected


def assess_infrastructure_retry(attempt):
    """Authorize replacement only for evidence of a service or environment failure."""
    _require(attempt.get('status') == 'infrastructure_error', 'Scored attempts must never be retried')
    path = Path(attempt['result_file'])
    _require(_sha(path) == attempt['result_sha256'], 'Infrastructure result changed after collection')
    failure = attempt.get('failure_kind')
    receipt = {'eligible': False, 'reason': 'unresolved_failure',
               'result_file': str(path), 'result_sha256': attempt['result_sha256']}
    result = json.loads(path.read_text())
    bootstrap_message = str((result.get('exception_info') or {}).get('exception_message', ''))
    if (failure == 'RuntimeError' and not result.get('agent_execution')
            and 'Docker compose command failed for environment ' in bootstrap_message
            and 'failed to create endpoint' in bootstrap_message
            and 'docker0 failed: Device does not exist' in bootstrap_message):
        receipt.update(eligible=True, reason='docker_default_bridge_missing_before_agent')
    elif failure in {'NonZeroAgentExitCodeError', 'AgentTimeoutError'}:
        log = path.parent / 'agent/codex.txt'
        if log.is_file():
            messages = []
            for line in log.read_text(errors='replace').splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get('type') == 'turn.failed':
                    messages.append(str((event.get('error') or {}).get('message', '')))
            if any(re.search(r'stream disconnected|error sending request|connection (?:reset|refused)|'
                             r'network (?:error|unreachable)|service unavailable|rate limit|'
                             r'HTTP\s*(?:429|500|502|503|504)\b|insufficient.quota|'
                             r'unauthorized|authentication|API key|request timed out', message, re.I)
                   for message in messages):
                receipt.update(eligible=True, reason='terminal_provider_failure',
                               evidence_file=str(log.resolve()), evidence_sha256=_sha(log))
    elif failure in {'AgentSetupTimeoutError', 'EnvironmentStartTimeoutError', 'VerifierTimeoutError',
                      'ServiceUnavailableError', 'ConnectionError', 'APIConnectionError',
                      'RateLimitError', 'verifier_execution_error', 'missing_or_nonbinary_reward'}:
        receipt.update(eligible=True, reason='service_or_environment_failure')
    return receipt


def _job_config(run_dir, selection, *, concurrency, binary, base_url, job_name='frontier-pass1'):
    return JobConfig.model_validate({'job_name': job_name, 'jobs_dir': str(Path(run_dir) / 'harbor_jobs'),
        'n_attempts': 1, 'n_concurrent_trials': concurrency, 'quiet': True,
        'retry': {'max_retries': 0}, 'environment': {'type': 'docker'},
        'tasks': [{'path': task['task_directory']} for task in selection['tasks']],
        'extra_instructions': [selection['prompt']],
        'agents': [{'import_path': 'sheets_factory.evaluation.frontier:LocalCodex',
            'model_name': MODEL, 'base_url': base_url, 'model_api_key_name': 'SHEETS_FACTORY_API_KEY',
            'model_api_format': 'openai_responses',
            'skip_model_parsing': True,
            'override_timeout_sec': selection['timeout_seconds'], 'override_setup_timeout_sec': 180,
            'kwargs': {'reasoning_effort': EFFORT, 'native_binary': str(binary),
                'config': {'model_provider': 'factory', 'model_providers': {'factory': {
                    'name': 'factory', 'base_url': base_url, 'env_key': 'OPENAI_API_KEY', 'wire_api': 'responses'}}}}}]})


async def execute_evaluation(run_dir, selection, audit, *, concurrency=4, backend_config=None,
                             job_name='frontier-pass1'):
    """Execute exactly one official Harbor attempt for each frozen task."""
    run_dir = Path(run_dir).resolve()
    backend = CodexCLI(Path(__file__).resolve().parents[3], run_dir, audit, backend_config or {})
    key, endpoint = backend._credentials()
    environment = _execution_environment(backend, key)
    environment.__enter__()
    try:
        config = _job_config(run_dir, selection, concurrency=concurrency, binary=backend.binary,
                             base_url=endpoint, job_name=job_name)
        config_file = (run_dir / 'harbor_job_config.json' if job_name == 'frontier-pass1' else
                       run_dir / 'harbor_job_configs' / (job_name + '.json'))
        _write(config_file, json.loads(config.model_dump_json()))
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
            persisted = run_dir / 'harbor_jobs' / job_name / str(record.get('trial_name', '')) / 'result.json'
            timing_fields = {}
            if persisted.is_file():
                actual = json.loads(persisted.read_text())
                diagnostic_path = persisted.parent / 'verifier/diagnostics.json'
                diagnostic = json.loads(diagnostic_path.read_text()) if diagnostic_path.is_file() else None
                review = review_agent_timeout(actual, task, result_file=persisted, diagnostics=diagnostic)
                status, reward, error = classify_result(actual, task, diagnostics=diagnostic, timeout_review=review)
                measured = apply_tool_time_policy({'status': status, 'reward': reward,
                    'failure_kind': error, 'result_file': str(persisted)}, selection)
                status, reward, error = measured['status'], measured['reward'], measured['failure_kind']
                timing_fields = {key: measured.get(key) for key in ('tool_time', 'raw_verifier_reward')}
            audit.task(task_id, status='evaluated' if status == 'scored' else status,
                       reward=reward, failure_kind=error, node='frontier_finished', **timing_fields)
            audit.emit('frontier.task_finished', task_id=task_id, reward=reward, status=status,
                       failure_kind=error, **timing_fields)
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
        exc._frontier_error_recorded = True
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
        'tool_time_policy': selection['tool_time_policy'],
        'n_attempts': 1, 'prompt_sha256': selection['prompt_sha256'], 'attempts': [],
        'infra_history': [], 'infrastructure_retries': [],
        'infrastructure_retry_policy': selection['infrastructure_retry_policy'],
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
            attempts, history = collect_attempts(run_dir, selection, include_infrastructure_history=True)
        except (OSError, ValueError, KeyError) as exc:
            attempts, history, failure = [], [], type(exc).__name__
        score, passed = summarize(selection, attempts)
        try:
            unchanged = (_sha(selection_path) == selection_sha and all(
                inspect_export(Path(task['task_directory'])) == task['harbor_export_binding']
                and dirhash(task['task_directory'], 'sha256') == task['task_checksum'] for task in selection['tasks']))
        except (OSError, ValueError, KeyError):
            unchanged = False
        complete = score['scored_tasks'] == score['total_tasks'] and not failure and unchanged
        manifest.update(status='completed' if complete else 'infrastructure_failed', finished_at=_now(),
            attempts=attempts, infra_history=history, score=score, gate_passed=bool(complete and passed),
            failure_kind=failure or (None if unchanged else 'snapshot_changed'),
            duration_seconds=round(time.monotonic() - clock, 3))
        _write(run_dir / 'evaluation_manifest.json', manifest)
        for attempt in attempts:
            audit.task(attempt['task_id'], status='evaluated' if attempt['status'] == 'scored' else attempt['status'],
                       reward=attempt['reward'], failure_kind=attempt['failure_kind'],
                       exception_resolution=attempt.get('exception_resolution'),
                       tool_time=attempt.get('tool_time'), raw_verifier_reward=attempt.get('raw_verifier_reward'))
        audit.update_run(status=manifest['status'], finished_at=manifest['finished_at'],
                         wall_seconds=manifest['duration_seconds'], frontier_score=score,
                         gate_passed=manifest['gate_passed'], producer_active=False)
        audit.export()
        server.stop()
    return manifest


def resume_infrastructure(run_dir, *, max_infrastructure_retries=2, concurrency=4,
                          project_root=None, backend_config=None, port=0, execute=None):
    """Resume an ended evaluation without replacing any valid scored attempt.

    The immutable selection and all original trial bytes stay in place. Each
    replacement has a new Harbor job and a receipt binding the previous manifest.
    """
    root = Path(project_root or Path(__file__).resolve().parents[3]).resolve()
    run_dir = Path(run_dir).resolve()
    _require(0 < max_infrastructure_retries <= 2, 'Infrastructure retries must be between one and two')
    _require(concurrency >= 1, 'Concurrency must be positive')
    with (run_dir / '.infrastructure_resume.lock').open('a') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise FrontierError('Another infrastructure recovery is already running') from exc
        manifest_path = run_dir / 'evaluation_manifest.json'
        original_raw = manifest_path.read_bytes()
        manifest = json.loads(original_raw)
        _require(manifest.get('status') == 'infrastructure_failed', 'Only an ended infrastructure failure may resume')
        selection_path = run_dir / 'selection_manifest.json'
        selection = json.loads(selection_path.read_text())
        selection_sha = _sha(selection_path)
        _require(selection_sha == manifest['selection_manifest']['sha256'], 'Frozen selection changed')
        early_stop = run_dir / 'private/early_stop.json'
        if early_stop.exists():
            stop_receipt = json.loads(early_stop.read_text())
            stop_sha = stop_receipt.get('selection_manifest_sha256') or (stop_receipt.get('selection_manifest') or {}).get('sha256')
            _require(stop_sha == selection_sha, 'Intentional early-stop receipt has a different selection binding')
            raise FrontierError('An intentional early stop must not be resumed as infrastructure failure')
        _require(selection.get('model') == MODEL and selection.get('reasoning_effort') == EFFORT
                 and selection.get('n_attempts') == 1, 'Recovery must retain the strongest single-attempt contract')
        for task in selection['tasks']:
            _require(inspect_export(task['task_directory']) == task['harbor_export_binding']
                     and dirhash(task['task_directory'], 'sha256') == task['task_checksum'], 'Frozen task changed')
        attempts, history = collect_attempts(run_dir, selection, include_infrastructure_history=True)
        actual_by_file = {attempt['result_file']: attempt for attempt in attempts + history}
        for old in manifest.get('attempts', []) + manifest.get('infra_history', []):
            current = actual_by_file.get(old['result_file'])
            _require(current is not None and current['result_sha256'] == old['result_sha256']
                     and current['status'] == old['status'] and current['reward'] == old['reward'],
                     'Previously recorded attempt changed')
        retries = manifest.get('infrastructure_retries', [])
        known_jobs = {'frontier-pass1'}
        for previous_index, previous_retry in enumerate(retries, 1):
            _require(previous_retry['index'] == previous_index
                     and previous_retry['job_name'] == f'frontier-infra-{previous_index:03}',
                     'Infrastructure recovery sequence changed')
            previous_path = Path(previous_retry['previous_manifest_file'])
            _require(_sha(previous_path) == previous_retry['previous_manifest_sha256'],
                     'Previous evaluation manifest changed')
            previous_manifest = json.loads(previous_path.read_text())
            _require(previous_manifest['selection_manifest']['sha256'] == selection_sha
                     and previous_manifest.get('infrastructure_retries', []) == retries[:previous_index - 1],
                     'Infrastructure recovery provenance changed')
            previous_scored = {item['task_id'] for item in previous_manifest.get('attempts', [])
                               if item['status'] == 'scored'}
            _require(not previous_scored.intersection(previous_retry['task_ids']),
                     'Infrastructure recovery replaced an already scored attempt')
            known_jobs.add(previous_retry['job_name'])
        _require(all(attempt['job_name'] in known_jobs for attempt in attempts + history),
                 'Unrecorded Harbor recovery job found')
        counts = Counter(task_id for retry in retries for task_id in retry['task_ids'])
        previous = {attempt['task_id']: attempt for attempt in attempts}
        eligible, blocked, authorization = [], [], []
        for task in selection['tasks']:
            task_id = task['task_id']
            attempt = previous.get(task_id)
            if attempt and attempt['status'] in {'scored', 'evidence_incomplete'}:
                continue
            receipt = (assess_infrastructure_retry(attempt) if attempt else
                       {'eligible': True, 'reason': 'no_persisted_attempt', 'result_file': None,
                        'result_sha256': None})
            receipt['task_id'] = task_id
            if counts[task_id] >= max_infrastructure_retries:
                receipt.update(eligible=False, reason='infrastructure_retry_budget_exhausted')
            authorization.append(receipt)
            (eligible if receipt['eligible'] else blocked).append(task_id)
        _require(bool(eligible), 'No certified infrastructure failures remain within the retry budget')
        index = len(retries) + 1
        job_name = f'frontier-infra-{index:03}'
        _require(not (run_dir / 'harbor_jobs' / job_name).exists(), 'Recovery job already exists; never overwrite trials')
        previous_file = run_dir / 'private/evaluation_history' / f'resume-{index:03}-before.json'
        _require(not previous_file.exists(), 'Recovery receipt already exists')
        previous_file.parent.mkdir(parents=True, exist_ok=True)
        previous_file.write_bytes(original_raw)
        started, clock = _now(), time.monotonic()
        retry = {'index': index, 'started_at': started, 'finished_at': None, 'task_ids': eligible,
                 'job_name': job_name, 'previous_manifest_file': str(previous_file),
                 'previous_manifest_sha256': sha256(original_raw).hexdigest(),
                 'authorization': authorization,
                 'execution_provenance': _runtime_provenance(root, (backend_config or {}).get('binary', NATIVE_CODEX))}
        manifest.update(status='running', finished_at=None, infrastructure_retries=retries + [retry],
                        infra_history=history, gate_passed=False, blocked_infrastructure_tasks=blocked,
                        infrastructure_retry_policy={'max_retries': max_infrastructure_retries,
                                                     'scored_attempts_per_task': 1, 'never_retry_scored': True})
        _write(manifest_path, manifest)
        audit = AuditStore(run_dir, {'id': run_dir.name, 'status': 'evaluating',
            'started_at': manifest['started_at'], 'kind': 'frontier_evaluation', 'phase': selection['phase'],
            'model': MODEL, 'reasoning_effort': EFFORT, 'infrastructure_retry_index': index,
            'financial_target': sum(task['mode'] == MODES[0] for task in selection['tasks']),
            'debugging_target': sum(task['mode'] == MODES[1] for task in selection['tasks'])})
        for task_id in eligible:
            audit.task(task_id, status='scheduled', node='infrastructure_retry', infrastructure_retry_index=index)
        audit.emit('frontier.infrastructure_resume', task_ids=eligible, index=index, job_name=job_name)
        server = DashboardServer(audit.snapshot, audit.events, port=port)
        url = server.start()
        audit.update_run(dashboard_url=url)
        print(json.dumps({'run_directory': str(run_dir), 'dashboard_url': url,
                          'infrastructure_retry_index': index, 'task_ids': eligible}), flush=True)
        retry_selection = {**selection, 'tasks': [task for task in selection['tasks'] if task['task_id'] in eligible],
                           'selected_task_ids': eligible}
        failure = None
        try:
            asyncio.run((execute or execute_evaluation)(run_dir, retry_selection, audit,
                concurrency=concurrency, backend_config=backend_config, job_name=job_name))
        except KeyboardInterrupt:
            failure = 'evaluation_interrupted'
        except Exception as exc:
            failure = type(exc).__name__
            if not getattr(exc, '_frontier_error_recorded', False):
                _persist_failure(run_dir, exc)
        finally:
            try:
                attempts, history = collect_attempts(run_dir, selection, include_infrastructure_history=True)
            except (OSError, ValueError, KeyError) as exc:
                attempts, history, failure = [], history, type(exc).__name__
            score, passed = summarize(selection, attempts)
            try:
                unchanged = _sha(selection_path) == selection_sha and all(
                    inspect_export(task['task_directory']) == task['harbor_export_binding']
                    and dirhash(task['task_directory'], 'sha256') == task['task_checksum'] for task in selection['tasks'])
            except (OSError, ValueError, KeyError):
                unchanged = False
            finished = _now()
            retry.update(finished_at=finished, failure_kind=failure,
                         duration_seconds=round(time.monotonic() - clock, 3))
            complete = score['scored_tasks'] == score['total_tasks'] and not failure and unchanged
            manifest.update(status='completed' if complete else 'infrastructure_failed', finished_at=finished,
                attempts=attempts, infra_history=history, score=score, gate_passed=bool(complete and passed),
                failure_kind=failure or (None if unchanged else 'snapshot_changed'),
                duration_seconds=round((manifest.get('duration_seconds') or 0) + retry['duration_seconds'], 3))
            _write(manifest_path, manifest)
            for attempt in attempts:
                audit.task(attempt['task_id'], status='evaluated' if attempt['status'] == 'scored' else attempt['status'],
                           reward=attempt['reward'], failure_kind=attempt['failure_kind'],
                           exception_resolution=attempt.get('exception_resolution'),
                           tool_time=attempt.get('tool_time'), raw_verifier_reward=attempt.get('raw_verifier_reward'))
            audit.update_run(status=manifest['status'], finished_at=finished, frontier_score=score,
                             gate_passed=manifest['gate_passed'], producer_active=False)
            audit.export()
            server.stop()
        return manifest
