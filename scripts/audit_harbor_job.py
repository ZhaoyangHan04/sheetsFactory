#!/usr/bin/env python3
"""Read-only audit of a completed final-dataset Harbor oracle or nop job.

This verifies persisted evidence. It never executes Harbor, models or Docker.
Detailed receipts contain local paths and must be kept in private outputs/.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlparse
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sheets_factory.evaluation.harbor import inspect_export


EXPORT_FILES = frozenset({'instruction.md', 'task.toml', 'export_manifest.json',
    'environment/Dockerfile', 'environment/input.xlsx', 'environment/recalculate',
    'solution/solve.sh', 'solution/reference.xlsx', 'tests/Dockerfile',
    'tests/original_input.xlsx', 'tests/reference.xlsx', 'tests/verify.py', 'tests/test.sh'})


class AuditError(ValueError):
    def __init__(self, code, reason):
        super().__init__(reason)
        self.code = code


def require(value, code, reason):
    if not value:
        raise AuditError(code, reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_file(path, within, tracked):
    path, within = Path(path).absolute(), Path(within).resolve()
    require(path.is_relative_to(within) and path.is_file(), 'missing_evidence', 'A required evidence file is missing.')
    require(not any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(within)),
            'symlink_evidence', 'Symlinks are not accepted in audit evidence.')
    raw = path.read_bytes()
    digest = sha(raw)
    require(tracked.setdefault(str(path), digest) == digest, 'evidence_changed', 'Evidence changed during this audit.')
    return raw


def read_json(path, within, tracked):
    value = json.loads(read_file(path, within, tracked))
    require(isinstance(value, dict), 'invalid_json_shape', 'Expected a JSON evidence object.')
    return value


def path_from_command(raw, cwd):
    require(isinstance(raw, str) and bool(raw.strip()), 'missing_task_path', 'Trial lacks its local task path.')
    path = Path(raw).expanduser()
    return (path if path.is_absolute() else cwd / path).resolve()


def trial_uri_path(raw):
    parsed = urlparse(raw if isinstance(raw, str) else '')
    require(parsed.scheme == 'file' and parsed.netloc in ('', 'localhost') and not parsed.query
            and not parsed.fragment and bool(parsed.path), 'trial_job_binding',
            'Trial URI does not identify a local Harbor trial directory.')
    return Path(unquote(parsed.path)).resolve()


def payload(path, expected, tracked):
    entries = list(path.rglob('*'))
    require(not path.is_symlink() and not any(p.is_symlink() for p in entries),
            'symlink_payload', 'Task payload must contain real files and directories.')
    names = {p.relative_to(path).as_posix() for p in entries if p.is_file()}
    directories = {p.relative_to(path).as_posix() for p in entries if p.is_dir()}
    require(names == EXPORT_FILES and directories == {'environment', 'solution', 'tests'},
            'payload_file_set', 'Task files differ from the fixed delivered-task allowlist.')
    require(isinstance(expected, dict) and set(expected) == names,
            'payload_file_set', 'Dataset manifest payload file set differs from the task.')
    actual = {}
    for name in sorted(names):
        actual[name] = sha(read_file(path / name, path, tracked))
        require(actual[name] == expected[name], 'payload_hash', 'A delivered task file differs from its recorded hash.')
    return actual


def reward(record):
    verifier = record.get('verifier_result')
    require(isinstance(verifier, dict), 'reward_contract', 'Trial lacks its verifier result object.')
    rewards = verifier.get('rewards')
    require(isinstance(rewards, dict) and set(rewards) == {'reward'},
            'reward_contract', 'Trial lacks the single binary reward contract.')
    value = rewards['reward']
    require(type(value) in (int, float) and math.isfinite(value) and value in (0, 1),
            'reward_contract', 'Trial reward must be a finite binary number.')
    return value


def _output_path(output, dataset, job):
    if output is None:
        return None
    output = Path(output).absolute()
    require(not output.exists() and not output.is_symlink(), 'output_exists', 'Audit output already exists; overwrite is refused.')
    require('outputs' in output.parts and not output.resolve().is_relative_to(dataset)
            and not output.resolve().is_relative_to(job), 'output_not_private',
            'Detailed audit receipts must be written to a separate private outputs/ location.')
    require(not any(p.is_symlink() for p in output.parents), 'symlink_output', 'Audit output parents must be real directories.')
    return output


def audit_harbor_job(dataset_dir, job_dir, *, agent, command_cwd, output=None):
    """Return a private evidence receipt; refuse any incomplete or mismatched job."""
    require(agent in {'oracle', 'nop'}, 'agent_choice', 'Expected agent must be oracle or nop.')
    cwd = Path(command_cwd).expanduser().resolve()
    require(cwd.is_dir(), 'command_cwd', 'The explicit original command directory does not exist.')
    dataset = path_from_command(str(dataset_dir), cwd)
    job = path_from_command(str(job_dir), cwd)
    require(dataset.is_dir() and job.is_dir(), 'missing_directory', 'Dataset or job directory is missing.')
    destination = _output_path(output, dataset, job)
    tracked = {}
    manifest_path = dataset / 'dataset_manifest.json'
    manifest = read_json(manifest_path, dataset, tracked)
    tasks, selected = manifest.get('tasks'), manifest.get('selected_task_ids')
    require(isinstance(tasks, list) and tasks and isinstance(selected, list),
            'dataset_manifest', 'Dataset manifest lacks its frozen task set.')
    ids = [item.get('task_id') for item in tasks if isinstance(item, dict)]
    require(len(ids) == len(tasks) and all(isinstance(i, str) and re.fullmatch(r'[A-Za-z0-9._-]+', i)
            and i not in {'.', '..'} for i in ids) and len(set(ids)) == len(ids),
            'dataset_task_ids', 'Dataset task IDs must be safe and unique.')
    require(all(isinstance(i, str) for i in selected) and len(selected) == len(ids)
            and len(set(selected)) == len(selected) and set(selected) == set(ids)
            and type(manifest.get('task_count')) is int and manifest['task_count'] == len(ids),
            'dataset_task_set', 'Dataset selected IDs or count differ from its task records.')
    require({p.name for p in dataset.iterdir()} == set(ids) | {'dataset_manifest.json'},
            'dataset_directory_set', 'Actual dataset entries differ from the manifest task set.')
    from dirhash import dirhash
    from harbor.models.task.task import Task
    expected, by_name = {}, {}
    for item in tasks:
        task_id = item['task_id']
        directory = dataset / task_id
        require(directory.is_dir(), 'missing_task', 'A manifest task directory is missing.')
        files = payload(directory, item.get('payload_files'), tracked)
        binding = inspect_export(directory)
        require(binding == item.get('harbor_export_binding') and binding.get('task_id') == task_id
                and binding.get('revision') == item.get('revision')
                and bool(binding.get('revision_hash')) and binding['revision_hash'] == item.get('revision_hash'),
                'export_binding', 'Dataset task export or revision binding differs.')
        require(binding['task_name'] not in by_name, 'duplicate_task_name', 'Dataset task names must be unique.')
        plain_checksum = dirhash(directory, 'sha256')
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', message=r'Task\.checksum will be deprecated', category=DeprecationWarning)
            harbor_checksum = Task(directory).checksum
        require(plain_checksum == harbor_checksum, 'checksum_filter', 'Harbor checksum excludes part of the delivered payload.')
        expected[task_id] = {'task_id': task_id, 'mode': item.get('mode'), 'task_directory': str(directory),
            'harbor_export_binding': binding, 'payload_files': files,
            'task_checksum': harbor_checksum, 'dirhash_sha256': plain_checksum}
        by_name[binding['task_name']] = task_id
    counts_by_mode = dict(Counter(item.get('mode') for item in tasks))
    require(manifest.get('counts_by_mode') == counts_by_mode, 'dataset_mode_counts', 'Dataset mode counts differ.')
    aggregate = read_json(job / 'result.json', job, tracked)
    require(isinstance(aggregate.get('id'), str) and bool(aggregate['id'])
            and bool(aggregate.get('finished_at')) and aggregate.get('n_total_trials') == len(tasks)
            and isinstance(aggregate.get('stats'), dict), 'job_incomplete', 'Job aggregate is unfinished or its total trial count differs.')
    stats = aggregate['stats']
    require(stats.get('n_completed_trials') == len(tasks)
            and all(stats.get(key, 0) == 0 for key in ('n_errored_trials', 'n_running_trials',
                'n_pending_trials', 'n_cancelled_trials', 'n_retries')),
            'job_incomplete', 'Job aggregate contains incomplete, errored, cancelled or repeated trials.')
    # Only direct child trial directories are Harbor trial records. Artifacts
    # and agent outputs may legitimately contain unrelated result.json files.
    directories = sorted((p for p in job.iterdir() if p.is_dir()), key=lambda p: p.name)
    trials, raw_records, trial_ids = [], {}, set()
    for directory in directories:
        result_file = directory / 'result.json'
        actual = read_json(result_file, job, tracked)
        name = actual.get('task_name')
        require(name in by_name, 'unknown_task', 'Job contains an unknown task result.')
        task_id = by_name[name]
        require(task_id not in raw_records, 'duplicate_trial', 'Job contains more than one trial for a dataset task.')
        config = actual.get('config') or {}
        require(isinstance(config, dict), 'trial_config', 'Trial config must be an object.')
        require(config.get('job_id') == aggregate['id']
                and path_from_command(config.get('trials_dir'), cwd) == job
                and trial_uri_path(actual.get('trial_uri')) == directory.resolve(),
                'trial_job_binding', 'Trial does not belong to the audited Harbor job and directory.')
        require(isinstance(actual.get('id'), str) and bool(actual['id']) and actual['id'] not in trial_ids,
                'duplicate_trial_id', 'Trial identifiers must be present and unique within the job.')
        trial_ids.add(actual['id'])
        require(actual.get('trial_name') == directory.name and config.get('trial_name') == directory.name,
                'trial_identity', 'Trial directory and recorded trial names differ.')
        require(bool(actual.get('finished_at')) and actual.get('exception_info') is None
                and actual.get('step_results') in (None, []),
                'trial_exception', 'Trial is unfinished, has an exception or uses an unexpected multi-step result.')
        config_agent = config.get('agent') or {}
        agent_info = actual.get('agent_info') or {}
        require(isinstance(config_agent, dict) and isinstance(agent_info, dict),
                'agent_identity', 'Trial agent config and identity must be objects.')
        require(config_agent.get('name') == agent and agent_info.get('name') == agent
                and not config_agent.get('import_path') and not config_agent.get('model_name'),
                'agent_identity', 'Actual trial agent identity differs from the requested built-in control.')
        verifier = config.get('verifier') or {}
        require(isinstance(verifier, dict), 'verification_contract', 'Trial verifier config must be an object.')
        require(not config.get('install_only') and not verifier.get('disable')
                and not verifier.get('import_path') and not verifier.get('kwargs')
                and not config.get('extra_instructions') and not config.get('extra_instruction_paths'),
                'verification_contract', 'Trial changed or disabled the delivered verification/instruction contract.')
        config_task, identity = config.get('task') or {}, actual.get('task_id') or {}
        require(isinstance(config_task, dict) and isinstance(identity, dict),
                'task_path_binding', 'Trial task config and identity must be local-task objects.')
        config_path = path_from_command(config_task.get('path'), cwd)
        id_path = path_from_command(identity.get('path'), cwd)
        require(config_path == id_path == (dataset / task_id).resolve(),
                'task_path_binding', 'Actual trial task paths do not identify the delivered dataset task.')
        require(actual.get('task_checksum') == expected[task_id]['task_checksum'],
                'task_checksum', 'Actual trial checksum differs from the delivered task payload.')
        value = reward(actual)
        require(value == (1 if agent == 'oracle' else 0), 'unexpected_reward', 'A control trial has an unexpected reward.')
        raw_records[task_id] = actual
        trials.append({'task_id': task_id, 'task_name': name, 'trial_name': directory.name,
            'trial_id': actual['id'], 'job_id': aggregate['id'], 'trial_uri': actual['trial_uri'],
            'result_file': str(result_file), 'result_sha256': tracked[str(result_file)],
            'config_task_path_raw': (config.get('task') or {}).get('path'),
            'task_id_path_raw': (actual.get('task_id') or {}).get('path'),
            'resolved_task_path': str(config_path), 'agent': agent, 'agent_info_name': agent,
            'task_checksum': actual['task_checksum'], 'reward': value, 'exception_info': None})
    require(set(raw_records) == set(ids), 'missing_trial', 'Job does not contain exactly one result for every dataset task.')
    summaries = aggregate.get('trial_results') or []
    if summaries:
        require(isinstance(summaries, list) and len(summaries) == len(trials),
                'aggregate_trial_set', 'Aggregate trial summaries differ from independent trial records.')
        seen = set()
        for summary in summaries:
            task_id = by_name.get(summary.get('task_name')) if isinstance(summary, dict) else None
            require(task_id in raw_records and task_id not in seen, 'aggregate_trial_set', 'Aggregate trial summaries contain unknown or duplicate tasks.')
            seen.add(task_id)
            raw = raw_records[task_id]
            require(all(summary.get(key) == raw.get(key) for key in ('task_name', 'trial_name', 'task_id',
                'task_checksum', 'config', 'agent_info', 'verifier_result', 'exception_info')),
                'aggregate_trial_binding', 'Aggregate trial summary differs from its raw trial result.')
    for path, digest in tracked.items():
        require(Path(path).is_file() and sha(Path(path).read_bytes()) == digest,
                'evidence_changed', 'Evidence changed during this audit.')
    for task_id in ids:
        payload(dataset / task_id, expected[task_id]['payload_files'], tracked)
    require({p.name for p in dataset.iterdir()} == set(ids) | {'dataset_manifest.json'},
            'evidence_changed', 'Dataset entries changed during this audit.')
    require({p.name for p in job.iterdir() if p.is_dir()} == {p.name for p in directories},
            'evidence_changed', 'Job trial directory set changed during this audit.')
    job_version = None
    if (job / 'lock.json').exists():
        lock = read_json(job / 'lock.json', job, tracked)
        job_version = (lock.get('harbor') or {}).get('version')
    receipt = {'schema_version': 1, 'status': 'passed', 'audited_at': datetime.now(timezone.utc).isoformat(),
        'audit_method': 'Read-only final dataset and completed Harbor job evidence; no execution performed.',
        'agent': agent, 'expected_reward': 1 if agent == 'oracle' else 0,
        'dataset_directory': str(dataset), 'job_directory': str(job), 'command_cwd': str(cwd),
        'dataset_manifest_sha256': tracked[str(manifest_path)], 'job_result_sha256': tracked[str(job / 'result.json')],
        'job_id': aggregate['id'], 'installed_harbor_version': version('harbor'),
        'recorded_job_harbor_version': job_version,
        'counts': {'dataset_tasks': len(tasks), 'trial_results': len(trials),
            'matched_rewards': len(trials), 'exceptions': 0, 'missing': 0, 'unknown': 0, 'duplicates': 0},
        'counts_by_mode': counts_by_mode, 'tasks': [expected[i] for i in ids],
        'trials': trials, 'evidence_files': tracked}
    if destination is not None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('x', encoding='utf-8') as stream:
            json.dump(receipt, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True, type=Path, dest='dataset_dir')
    parser.add_argument('--job', required=True, type=Path, dest='job_dir')
    parser.add_argument('--agent', required=True, choices=('oracle', 'nop'))
    parser.add_argument('--command-cwd', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        receipt = audit_harbor_job(**vars(args))
    except AuditError as exc:
        print(json.dumps({'status': 'failed', 'code': exc.code, 'reason': str(exc)}), file=sys.stderr)
        return 2
    except Exception:
        print(json.dumps({'status': 'failed', 'code': 'unreadable_evidence',
            'reason': 'Required JSON, task evidence, or the installed Harbor dependency could not be verified.'}), file=sys.stderr)
        return 2
    print(json.dumps({'status': receipt['status'], 'agent': receipt['agent'], 'counts': receipt['counts'],
                      'dataset_manifest_sha256': receipt['dataset_manifest_sha256']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
