#!/usr/bin/env python3
"""Validate a frozen confirmation set and materialize a reproducible dataset.

--dry-run only reads evidence. Publication copies a fixed task-file allowlist to
the checkout's real SpreadsheetEval directory; it never links into outputs or
copies private traces. This command does not run models, Docker, or Harbor.
"""
from __future__ import annotations

import argparse
from collections import Counter
import ctypes
from datetime import datetime, timezone
import errno
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import sys
import tomllib
from uuid import uuid4
import zipfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
import package_release as release
from sheets_factory.reporting import read_run


MIN_PER_MODE = 10
MODEL = 'gpt-6.1-sol'
EFFORT = 'xhigh'
MAX_PASS_AT_ONE = 0.2
RUNTIME_DIRECTORY = 'benchmark_runtime'
PublishError = release.ReleaseError


def _require(condition, message):
    if not condition:
        raise PublishError(message)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json_file(path, tracked):
    path = Path(path).absolute()
    return release._json(path, path.parent, tracked)


def _timestamp(value, label):
    _require(isinstance(value, str), f'{label} must include a timestamp')
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise PublishError(f'{label} has an invalid timestamp') from error
    _require(stamp.tzinfo is not None, f'{label} must include a timezone')
    return stamp


def _credential_values(root):
    key_file = root / '.secrets/api_key'
    values = [key_file.read_bytes().strip()] if key_file.is_file() else []
    return [value for value in values if len(value) >= 12]


def _check_credentials(raw, secret_values):
    # Do not include the matched bytes in exceptions or publication receipts.
    _require(not any(value in raw for value in secret_values), 'Credential found in publishable files')
    _require(not re.search(rb'\bsk-[A-Za-z0-9_-]{20,}', raw), 'Credential-shaped token found in publishable files')


def _task_contract(export, within, tracked, secret_values):
    binding = release._check_payload(export, within, tracked, secret_values)
    config = tomllib.loads((export / 'task.toml').read_text())
    _require(config.get('schema_version') == '1.3'
             and config.get('verifier', {}).get('environment_mode') == 'separate',
             'Publication requires Harbor schema 1.3 and a separate verifier')
    _require(config.get('artifacts') == ['/app/output.xlsx'], 'Unexpected task output artifact contract')
    for relative in release.EXPORT_FILES:
        raw = (export / relative).read_bytes()
        _check_credentials(raw, secret_values)
        if relative.endswith('.xlsx'):
            with zipfile.ZipFile(export / relative) as book:
                for item in book.infolist():
                    _check_credentials(book.read(item), secret_values)
    # Root references are expected benchmark ground truth. The agent image may
    # only build from its three public environment files, never solution/tests.
    recipe = (export / 'environment/Dockerfile').read_text()
    _require('reference.xlsx' not in recipe and '../' not in recipe
             and re.search(r'(?im)^\s*(?:COPY|ADD)\s+[^\n]*\s/solution\b', recipe) is None,
             'Agent image recipe exposes reference material')
    return binding


def _prepare_runtime(root, run_dir, validated, tracked, secrets):
    payload, metadata = release._prepare_runtime(root, run_dir, validated, tracked, secrets)
    # Do not copy the old release README: its deferred-difficulty statement is
    # not true of a confirmation-gated publication. Root README is maintained
    # separately. Runtime material sits outside Harbor's task enumeration.
    files = {f'{RUNTIME_DIRECTORY}/{name}': payload[f'runtime/{name}']
             for name in release.RUNTIME_FILES}
    tag = metadata['image_tag']
    files['prepare_runtime.sh'] = (
        '#!/bin/sh\nset -eu\n'
        'dataset_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        f'docker build --network host -t {shlex.quote(tag)} "$dataset_root/{RUNTIME_DIRECTORY}"\n'
    ).encode()
    lock = release._file(root / 'uv.lock', root, tracked)
    locked = [package for package in tomllib.loads(lock.decode()).get('package', [])
              if package.get('name') == 'harbor']
    _require(len(locked) == 1 and locked[0].get('version') == '0.25.0',
             'Publication requires uv.lock with Harbor 0.25.0')
    return files, {'image_tag': tag, 'harbor_version': '0.25.0', 'uv_lock_sha256': _sha(lock),
        'context_directory': RUNTIME_DIRECTORY,
        'recipe_files': {name: _sha(raw) for name, raw in sorted(files.items())},
        'recorded_run_images': metadata['recorded_run_images'],
        'bit_identical_rebuild_guaranteed': False,
        'prepare_command': './prepare_runtime.sh',
        'oracle_command': 'harbor run -p SpreadsheetEval -a oracle',
        'nop_command': 'harbor run -p SpreadsheetEval -a nop',
        'setup_commands': ['uv sync --frozen --extra test --python 3.12',
                           'source .venv/bin/activate', './prepare_runtime.sh'],
        'command_working_directory': 'repository root'}


def _load_selection(root, run_dir, release_dir, selection_path, tracked, secrets):
    """Validate the selected immutable revisions, not a new post-hoc ranking."""
    frozen_path = Path(selection_path).absolute() if selection_path else release_dir / 'release_manifest.json'
    frozen = _json_file(frozen_path, tracked)
    if release_dir is not None:
        release_manifest = _json_file(release_dir / 'release_manifest.json', tracked)
        source_run = release_manifest.get('source_run_directory')
        _require(isinstance(source_run, str) and Path(source_run).is_absolute(),
                 'Strict release validation requires its original source run')
        run_dir = Path(source_run).resolve()
        release_tasks = {task['task_id']: task for task in release_manifest.get('tasks', [])}
    else:
        release_manifest, release_tasks = None, {}
    _require(run_dir is not None and run_dir.is_dir(), 'Original source run is unavailable')
    _require(isinstance(frozen.get('selected_task_ids'), list) and frozen['selected_task_ids'],
             'Frozen selection must explicitly name selected_task_ids')
    ids = frozen['selected_task_ids']
    _require(all(isinstance(task_id, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', task_id)
                 for task_id in ids) and len(ids) == len(set(ids)), 'Frozen task IDs are unsafe or duplicated')
    frozen_tasks = frozen.get('tasks')
    _require(isinstance(frozen_tasks, list) and len(frozen_tasks) == len(ids),
             'Frozen selection must bind each selected task exactly once')
    records = {record['task_id']: record for record in frozen_tasks}
    _require(set(records) == set(ids), 'Frozen task records differ from selected_task_ids')
    snapshot = read_run(run_dir)
    current = {task['id']: task for task in snapshot['tasks']}
    config_path = run_dir / 'resolved_config.yaml'
    config = yaml.safe_load(release._file(config_path, run_dir, tracked)) if config_path.is_file() else {}
    registry_path = ((config or {}).get('native_risks') or {}).get('registry_path')
    validated, sources = [], {}
    for task_id in ids:
        task = current.get(task_id)
        _require(task is not None and task.get('status') == 'qualified',
                 f'{task_id}: current audited task is not qualified')
        item = release._validate_task(run_dir, task, tracked, secrets,
                                     project_root=root, registry_path=registry_path)
        binding = item['harbor_export_binding']
        record = records[task_id]
        _require(record.get('revision') == item['revision']
                 and record.get('revision_hash') == item['revision_hash']
                 and record.get('harbor_export_binding') == binding,
                 f'{task_id}: frozen revision binding differs from current task')
        _require(record.get('mode') == item['mode'], f'{task_id}: frozen task mode differs')
        export = run_dir / 'SpreadsheetEval' / task_id
        if release_dir is not None:
            packaged = release_tasks.get(task_id)
            _require(packaged is not None and packaged.get('harbor_export_binding') == binding
                     and packaged.get('payload_files') == item['payload_files'],
                     f'{task_id}: release receipt differs from current verified export')
            export = release_dir / 'SpreadsheetEval' / task_id
        _require(_task_contract(export, release_dir or run_dir, tracked, secrets) == binding,
                 f'{task_id}: publication payload differs from frozen binding')
        validated.append(item)
        sources[task_id] = export
    counts = {mode: sum(item['mode'] == mode for item in validated) for mode in release.MODES}
    _require(all(count >= MIN_PER_MODE for count in counts.values())
             and sum(counts.values()) == len(validated),
             f'Publication requires at least {MIN_PER_MODE} tasks in each mode')
    return run_dir, frozen_path, frozen, validated, sources, snapshot


def _rename_new(source, destination):
    """Publish without overwriting even a concurrently created empty directory."""
    rename = getattr(ctypes.CDLL(None, use_errno=True), 'renameat2', None)
    _require(rename is not None, 'Atomic no-overwrite publication is unavailable')
    if rename(-100, bytes(source), -100, bytes(destination), 1):
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise PublishError('Publication destination already exists')
        raise OSError(code, 'Publication rename failed')


def _validate_confirmation_history(evidence, directory, frozen, tracked):
    """Replay retry authorization without counting failed infrastructure as zero."""
    from sheets_factory.evaluation.frontier import collect_attempts, assess_infrastructure_retry

    directory = Path(directory)
    try:
        current, history = collect_attempts(directory, frozen, include_infrastructure_history=True)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise PublishError('Confirmation history has invalid or repeated scored attempts') from error
    supplied = evidence['attempts']
    identity = lambda item: (item['task_id'], item['result_file'], item['result_sha256'], item['status'], item['reward'])
    _require({identity(item) for item in current} == {identity(item) for item in supplied},
             'Final confirmation attempts differ from actual Harbor trial history')
    reported_history = evidence.get('infra_history', [])
    _require(isinstance(reported_history, list)
             and len(reported_history) == len({identity(item) for item in reported_history})
             and {identity(item) for item in history} == {identity(item) for item in reported_history},
             'Raw infrastructure history differs from the manifest')
    for item in current + history:
        raw = release._file(Path(item['result_file']), directory, tracked)
        _require(_sha(raw) == item['result_sha256'], 'Raw trial history changed')
    retries = evidence.get('infrastructure_retries', [])
    _require(isinstance(retries, list), 'Infrastructure retry ledger must be a list')
    selected = set(frozen['selected_task_ids'])
    counts, jobs = Counter(), {}
    actual_history = {item['result_file']: item for item in history}
    for index, retry in enumerate(retries, 1):
        _require(retry.get('index') == index and retry.get('finished_at'), 'Infrastructure retry ledger is unfinished')
        task_ids = retry.get('task_ids')
        _require(isinstance(task_ids, list) and task_ids and len(task_ids) == len(set(task_ids))
                 and set(task_ids) <= selected, 'Retry task IDs differ from the frozen cohort')
        counts.update(task_ids)
        _require(all(count <= 2 for count in counts.values()), 'Per-task infrastructure retry budget exceeds two')
        job = retry.get('job_name')
        _require(isinstance(job, str) and job not in jobs and job != 'frontier-pass1', 'Duplicate or invalid retry job')
        jobs[job] = set(task_ids)
        previous_path = Path(retry.get('previous_manifest_file', ''))
        previous = release._json(previous_path, directory, tracked)
        _require(tracked[str(previous_path.absolute())] == retry.get('previous_manifest_sha256')
                 and previous.get('status') == 'infrastructure_failed'
                 and previous.get('phase') == evidence.get('phase')
                 and previous.get('selection_manifest') == evidence['selection_manifest'],
                 'Previous evaluation manifest receipt differs')
        _require(previous.get('infrastructure_retries', []) == retries[:index - 1],
                 'Infrastructure retry manifests do not form the original ledger chain')
        previous_attempts = {item['task_id']: item for item in previous.get('attempts', [])}
        authorization = retry.get('authorization')
        _require(isinstance(authorization, list), 'Retry authorization evidence is missing')
        authorized = {item['task_id']: item for item in authorization}
        _require(len(authorized) == len(authorization) and set(authorized) <= selected,
                 'Retry authorization IDs are duplicated or outside the frozen cohort')
        for task_id in task_ids:
            old = previous_attempts.get(task_id)
            _require(old is None or old.get('status') == 'infrastructure_error',
                     'A previously scored model attempt was retried')
            if old is None:
                expected = {'eligible': True, 'reason': 'no_persisted_attempt', 'result_file': None, 'result_sha256': None}
            else:
                actual = actual_history.get(old.get('result_file'))
                _require(actual is not None and identity(actual) == identity(old),
                         'Previously failed infrastructure record changed classification')
                expected = assess_infrastructure_retry(actual)
            recorded = authorized.get(task_id, {})
            _require(expected.get('eligible') is True and recorded == {**expected, 'task_id': task_id},
                     'Retry lacks exact independently reproduced infrastructure authorization')
            if expected.get('evidence_file'):
                raw = release._file(Path(expected['evidence_file']), directory, tracked)
                _require(_sha(raw) == expected['evidence_sha256'], 'Provider failure evidence changed')
        start = _timestamp(retry.get('started_at'), 'Infrastructure retry start')
        finish = _timestamp(retry.get('finished_at'), 'Infrastructure retry finish')
        _require(_timestamp(previous.get('finished_at'), 'Previous evaluation finish') <= start <= finish
                 <= _timestamp(evidence.get('finished_at'), 'Confirmation finish'),
                 'Infrastructure retry timing differs from the previous and final receipts')
    for attempt in current + history:
        job = attempt['job_name']
        _require(job == 'frontier-pass1' or attempt['task_id'] in jobs.get(job, set()),
                 'Actual trial has no corresponding retry authorization ledger')
    return {'retry_batches': len(retries), 'raw_infrastructure_records': len(history),
            'scored_attempts_per_task': 1, 'maximum_infrastructure_retries_per_task': 2}


def _validate_confirmation(path, frozen_path, frozen, validated, tracked):
    """Check actual first attempts from the predeclared confirmation cohort."""
    from dirhash import dirhash

    path = Path(path).absolute()
    evidence = _json_file(path, tracked)
    selection_sha = tracked[str(frozen_path)]
    _require(evidence.get('phase') == 'confirmation' and evidence.get('status') == 'completed',
             'Only a completed confirmation evaluation can be published')
    _require(evidence.get('model') == MODEL and evidence.get('reasoning_effort') == EFFORT,
             'Confirmation must use gpt-6.1-sol with xhigh reasoning')
    selection = evidence.get('selection_manifest') or {}
    _require(selection.get('sha256') == selection_sha,
             'Confirmation is not bound to the frozen selection')
    declared_path = Path(selection.get('path', ''))
    if not declared_path.is_absolute():
        declared_path = path.parent / declared_path
    _require(declared_path.absolute() == frozen_path, 'Confirmation names a different frozen selection')
    _require(frozen.get('phase') == 'confirmation' and frozen.get('model') == MODEL
             and frozen.get('reasoning_effort') == EFFORT,
             'The frozen cohort must declare the confirmation model and phase')
    frozen_at = _timestamp(frozen.get('frozen_at', frozen.get('created_at')), 'Frozen selection')
    started_at = _timestamp(evidence.get('started_at'), 'Confirmation start')
    finished_at = _timestamp(evidence.get('finished_at'), 'Confirmation finish')
    _require(frozen_at <= started_at <= finished_at,
             'Selection must be frozen before confirmation starts')
    _require((evidence.get('score') or {}).get('infrastructure_errors') == 0,
             'Confirmation has unresolved infrastructure failures')
    entries = evidence.get('attempts')
    _require(isinstance(entries, list) and len(entries) == len(validated),
             'Confirmation must cover the entire frozen cohort exactly once')
    by_id = {item['task_id']: item for item in validated}
    frozen_tasks = {item['task_id']: item for item in frozen['tasks']}
    seen, results = set(), []
    for entry in entries:
        task_id = entry.get('task_id')
        _require(task_id in by_id and task_id not in seen, 'Duplicate or unselected confirmation task')
        seen.add(task_id)
        task = by_id[task_id]
        binding = task['harbor_export_binding']
        _require(entry.get('mode') == task['mode'] and entry.get('harbor_export_binding') == binding,
                 'Confirmation result uses a different frozen revision')
        _require(entry.get('status') == 'scored',
                 'Confirmation needs a completed first attempt without infrastructure error')
        declared = frozen_tasks[task_id]
        task_directory = Path(declared.get('task_directory', ''))
        if not task_directory.is_absolute():
            task_directory = frozen_path.parent / task_directory
        _require(release._check_payload(task_directory, task_directory, tracked) == binding,
                 'Frozen confirmation task payload changed')
        checksum = dirhash(task_directory, 'sha256')
        _require(declared.get('task_checksum') == checksum and entry.get('task_checksum') == checksum,
                 'Confirmation task checksum differs from the frozen payload')
        result_path = Path(entry.get('result_file', ''))
        if not result_path.is_absolute():
            result_path = path.parent / result_path
        actual = _json_file(result_path, tracked)
        result_sha = tracked[str(result_path.absolute())]
        _require(entry.get('result_sha256') == result_sha,
                 'Confirmation result file hash differs')
        config = actual.get('config') or {}
        actual_agent = config.get('agent') or {}
        actual_task = config.get('task') or {}
        agent_info = actual.get('agent_info') or {}
        _require(actual.get('task_name') == binding['task_name'] and actual.get('task_checksum') == checksum
                 and actual_task.get('path') == str(task_directory)
                 and (actual.get('task_id') or {}).get('path') == str(task_directory)
                 and actual_agent.get('model_name') == MODEL
                 and actual_agent.get('import_path') == 'sheets_factory.evaluation.frontier:LocalCodex'
                 and (actual_agent.get('kwargs') or {}).get('reasoning_effort') == EFFORT
                 and actual_agent.get('override_timeout_sec') == frozen.get('timeout_seconds')
                 and (agent_info.get('model_info') or {}).get('name') == MODEL,
                 'Actual confirmation result lacks the required identity or execution binding')
        resolution = None
        if actual.get('exception_info'):
            from sheets_factory.evaluation.frontier import review_agent_timeout
            _require(actual['exception_info'].get('exception_type') == 'AgentTimeoutError',
                     'Actual confirmation trial has an unresolved exception')
            resolution = review_agent_timeout(actual, declared, result_file=result_path)
            _require(resolution is not None and entry.get('exception_resolution') == resolution,
                     'Normal agent timeout lacks an exact reproducible review receipt')
            for label in ('native_log', 'diagnostics'):
                file = Path(resolution[label + '_file'])
                raw = release._file(file, result_path.parent, tracked)
                _require(_sha(raw) == resolution[label + '_sha256'],
                         'Agent timeout review evidence changed')
            release._file(result_path.parent / 'verifier/reward.txt', result_path.parent, tracked)
        rewards = (actual.get('verifier_result') or {}).get('rewards') or {}
        reward = rewards.get('reward')
        if reward is None and isinstance(rewards, dict) and len(rewards) == 1:
            reward = next(iter(rewards.values()))
        _require(type(reward) in (int, float) and reward in (0, 1)
                 and type(entry.get('reward')) in (int, float) and entry['reward'] == reward,
                 'Confirmation first-attempt reward is missing or inconsistent')
        attempt_started = _timestamp(actual.get('started_at'), 'Actual attempt start')
        attempt_finished = _timestamp(actual.get('finished_at'), 'Actual attempt finish')
        _require(started_at <= attempt_started <= attempt_finished <= finished_at,
                 'Actual attempt timestamps differ from the confirmation window')
        public_result = {'task_id': task_id, 'mode': task['mode'], 'reward': reward,
                         'result_sha256': result_sha}
        if resolution:
            public_result['exception_resolution'] = {key: resolution[key] for key in (
                'classification', 'budget_seconds', 'agent_elapsed_seconds', 'model_output_tokens',
                'completed_command_events', 'reward', 'native_log_sha256', 'diagnostics_sha256')}
        results.append(public_result)
    _require(seen == set(by_id), 'Confirmation leaves selected tasks unevaluated')
    passed = sum(item['reward'] for item in results)
    overall = passed / len(results)
    _require(overall <= MAX_PASS_AT_ONE, 'Overall confirmation Pass@1 exceeds 0.2')
    by_mode = {mode: {'tasks': sum(item['mode'] == mode for item in results),
                     'passed': sum(item['reward'] for item in results if item['mode'] == mode)}
               for mode in release.MODES}
    for summary in by_mode.values():
        summary['pass_at_1'] = summary['passed'] / summary['tasks']
    score = evidence.get('score') or {}
    _require(score.get('total_tasks') == len(results) and score.get('scored_tasks') == len(results)
             and score.get('overall_pass_at_1') == overall and evidence.get('gate_passed') is True,
             'Confirmation aggregate differs from actual persisted first-attempt results')
    for mode, computed in by_mode.items():
        declared = (score.get('by_mode') or {}).get(mode) or {}
        _require(declared.get('tasks') == computed['tasks'] and declared.get('scored') == computed['tasks']
                 and declared.get('successes') == computed['passed']
                 and declared.get('pass_at_1') == computed['pass_at_1'],
                 'Reported mode scores differ from actual confirmation results')
    history = _validate_confirmation_history(evidence, path.parent, frozen, tracked)
    return {'phase': 'confirmation', 'status': 'completed', 'model': MODEL,
        'reasoning_effort': EFFORT, 'selection_manifest_sha256': selection_sha,
        'evaluation_manifest_sha256': tracked[str(path)], 'frozen_at': frozen_at.isoformat(),
        'started_at': started_at.isoformat(), 'finished_at': finished_at.isoformat(),
        'task_count': len(results), 'passed': passed, 'overall_pass_at_1': overall,
        'maximum_overall_pass_at_1': MAX_PASS_AT_ONE, 'by_mode': by_mode, 'tasks': results,
        'infrastructure_history': history}


def publish_dataset(*, release_dir=None, run_dir=None, selection_manifest=None,
                    evaluation_manifest, project_root=None, dry_run=False):
    root = Path(project_root or ROOT).resolve()
    _require((release_dir is None) != (run_dir is None), 'Choose exactly one --release or --run')
    _require(release_dir is not None or selection_manifest is not None,
             '--run requires an explicit frozen --selection-manifest')
    release_dir = Path(release_dir).absolute() if release_dir is not None else None
    run_dir = Path(run_dir).absolute() if run_dir is not None else None
    destinations = [root / 'SpreadsheetEval', root / RUNTIME_DIRECTORY, root / 'prepare_runtime.sh']
    _require(not any(path.exists() or path.is_symlink() for path in destinations),
             'Publication destination already exists; existing final data is never overwritten')
    tracked, secrets = {}, _credential_values(root)
    if release_dir is not None and selection_manifest is None:
        evaluation_path = Path(evaluation_manifest).absolute()
        evaluation = _json_file(evaluation_path, tracked)
        selection_manifest = (evaluation.get('selection_manifest') or {}).get('path')
        _require(isinstance(selection_manifest, str) and bool(selection_manifest),
                 'Release publication requires the confirmation frozen selection')
        selection_manifest = Path(selection_manifest)
        if not selection_manifest.is_absolute():
            selection_manifest = evaluation_path.parent / selection_manifest
    run_dir, frozen_path, frozen, validated, sources, snapshot = _load_selection(
        root, run_dir, release_dir, selection_manifest, tracked, secrets)
    evaluation = _validate_confirmation(evaluation_manifest, frozen_path, frozen, validated, tracked)
    runtime_files, runtime = _prepare_runtime(root, run_dir, validated, tracked, secrets)
    manifest = {'schema_version': 1, 'dataset_name': 'SpreadsheetEval',
        'source_run_id': snapshot['run'].get('id'),
        'frozen_selection_sha256': tracked[str(frozen_path)],
        'confirmation': evaluation, 'difficulty_status': 'confirmation_passed', 'task_count': len(validated),
        'counts_by_mode': {mode: sum(item['mode'] == mode for item in validated) for mode in release.MODES},
        'selected_task_ids': [item['task_id'] for item in validated],
        'tasks': [{key: item[key] for key in ('task_id', 'mode', 'source_id', 'revision',
                   'revision_hash', 'harbor_export_binding', 'payload_files')} | {
                     'controls': {agent: {'reward': entry['reward'], 'result_sha256': entry['sha256']}
                                  for agent, entry in item['controls'].items()}}
                  for item in validated], 'runtime': runtime,
        'evidence_policy': 'Only task allowlist and hash-bound aggregate receipts; no private logs or credentials.'}
    raw_manifest = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
    _check_credentials(raw_manifest, secrets)
    for raw in runtime_files.values():
        _check_credentials(raw, secrets)
    result = {'status': 'validated_dry_run' if dry_run else 'published',
        'task_count': len(validated), 'counts_by_mode': manifest['counts_by_mode'],
        'destination': str(destinations[0]), 'manifest_sha256': _sha(raw_manifest), 'manifest': manifest}
    if dry_run:
        return result
    stage = root / ('.dataset-publish-' + uuid4().hex)
    stage.mkdir(mode=0o700)
    published = []
    try:
        for item in validated:
            target = stage / 'SpreadsheetEval' / item['task_id']
            release._copy_payload(sources[item['task_id']], target)
            _require(_task_contract(target, stage, {}, secrets) == item['harbor_export_binding'],
                     'Copied task differs from its frozen confirmation binding')
        for relative, raw in runtime_files.items():
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        (stage / 'prepare_runtime.sh').chmod(0o755)
        (stage / 'SpreadsheetEval/dataset_manifest.json').write_bytes(raw_manifest)
        for path, digest in tracked.items():
            _require(_sha(Path(path).read_bytes()) == digest, 'Publication evidence changed during staging')
        for item in validated:
            native = item['native_risk_check']
            registry = Path(native['registry_path'])
            current_hash = _sha(registry.read_bytes()) if registry.is_file() else None
            _require(current_hash == native['registry_sha256'],
                     'Native-risk evidence changed during staging')
        latest = {task['id']: task for task in read_run(run_dir)['tasks']}
        previous = {task['id']: task for task in snapshot['tasks']}
        _require(all(latest.get(item['task_id']) == previous[item['task_id']] for item in validated),
                 'Selected task audit changed during staging')
        # The real dataset is the final commit point. Runtime files are rolled
        # back on failure; nothing in a pre-existing checkout is replaced.
        for target in destinations[1:] + destinations[:1]:
            _rename_new(stage / target.name, target)
            published.append(target)
    except BaseException:
        for path in reversed(published):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--release', type=Path, dest='release_dir')
    source.add_argument('--run', type=Path, dest='run_dir')
    parser.add_argument('--selection-manifest', type=Path)
    parser.add_argument('--evaluation-manifest', required=True, type=Path)
    parser.add_argument('--project-root', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = publish_dataset(**vars(args))
    except (PublishError, OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile):
        # Do not print document/provider bytes from exceptions. Detailed private
        # evidence stays in its original run; no raw exception goes to stdout.
        print(json.dumps({'error': 'publication_refused',
                          'reason': 'Frozen selection, confirmation evidence, or safe publication prerequisites failed.'}),
              file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
