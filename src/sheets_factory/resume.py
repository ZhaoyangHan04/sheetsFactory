"""Audited continuation after a producer has terminated.

This intentionally supports terminal-run continuation, not guessing how to
restart an interrupted agent. Existing task IDs and their budgets stay frozen.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
from uuid import uuid4

import yaml

from .core.audit import AuditStore
from .reporting import read_run


TERMINAL_RUN_STATES = {'completed', 'shortfall', 'failed', 'cancelled'}
PRESERVED_TASK_STATES = {'qualified', 'ready', 'rejected', 'cancelled'}
PROTECTED_BUDGETS = ('max_steps', 'max_evidence_rounds_per_revision',
                    'infrastructure_retries_per_stage', 'max_additional_trials_per_revision')
SCHEDULERS = frozenset({'source_batches', 'rolling'})


class ResumeError(RuntimeError):
    pass


def validate_scheduler(value):
    if not isinstance(value, str) or value not in SCHEDULERS:
        raise ResumeError('run.scheduler must be source_batches or rolling')
    return value


def _now():
    return datetime.now(timezone.utc).isoformat()


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _pid_start(pid):
    try:
        return (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return None


class ProducerLease:
    """An advisory process lease; the file is retained to avoid unlink races."""

    def __init__(self, run_dir):
        self.run_dir = Path(run_dir).resolve()
        self.path = self.run_dir / 'producer.lock'
        self.stream = None

    def acquire(self):
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open('a+')
        try:
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.stream.close()
            self.stream = None
            raise ResumeError('Another producer holds this run lease') from exc
        self._write('active')
        return self

    def _write(self, status):
        self.stream.seek(0)
        self.stream.truncate()
        self.stream.write(json.dumps({'pid': os.getpid(), 'pid_start_ticks': _pid_start(os.getpid()),
                                     'status': status, 'updated_at': _now()}))
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def release(self):
        if self.stream is not None:
            self._write('released')
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            self.stream.close()
            self.stream = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *args):
        self.release()


def active_producer_pids(run_dir, state=None):
    """Find leased producers and legacy CLI writers holding this SQLite file."""
    run_dir = Path(run_dir).resolve()
    state = state or {}
    found = set()
    recorded = state.get('producer_pid')
    if isinstance(recorded, int) and recorded != os.getpid() and state.get('producer_active', True):
        actual = _pid_start(recorded)
        expected = state.get('producer_start_ticks')
        if actual is not None and (expected is None or str(expected) == actual):
            found.add(recorded)
    database = str(run_dir / 'run.sqlite')
    explicitly_inactive = recorded if state.get('producer_active') is False else None
    for process in Path('/proc').iterdir():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        if int(process.name) == explicitly_inactive:
            continue
        try:
            command = (process / 'cmdline').read_bytes()
            if not any(marker in command for marker in (b'sheets_factory.cli', b'sheets-factory', b'scripts/run.sh')):
                continue
            if any(os.readlink(fd) == database for fd in (process / 'fd').iterdir()):
                found.add(int(process.name))
        except (OSError, PermissionError):
            continue
    return sorted(found)


def assert_resume_allowed(run_dir, snapshot, producer_probe=None):
    run = snapshot['run']
    if run.get('status') not in TERMINAL_RUN_STATES:
        raise ResumeError('Only a terminal run can be continued; the current producer must finish first')
    active_tasks = [task['id'] for task in snapshot['tasks'] if task.get('status') not in PRESERVED_TASK_STATES]
    active_nodes = [node for node in snapshot['nodes'] if node.get('status') in {'running', 'scheduled', 'pending'}]
    active_calls = [call for call in snapshot['calls'] if call.get('status') in {'running', 'scheduled', 'pending'}]
    if active_tasks or active_nodes or active_calls:
        raise ResumeError('Interrupted task context is not resumed automatically; active task/node/call records remain')
    probe = producer_probe or active_producer_pids
    pids = probe(run_dir, run)
    if pids:
        raise ResumeError(f'Producer processes are still alive: {pids}')


def candidate_task_id(seed, mode):
    if mode not in {'financial_modeling', 'debugging'}:
        raise ResumeError(f'Unsupported task mode: {mode}')
    digest = seed.get('sha256') or seed.get('source_sha256')
    if not isinstance(digest, str) or len(digest) != 64:
        raise ResumeError('Seed requires its full source SHA-256')
    variant = seed.get('variant', 0)
    if not isinstance(variant, int) or isinstance(variant, bool) or variant < 0:
        raise ResumeError('Variant must be a nonnegative integer')
    return ('fm-' if mode == 'financial_modeling' else 'dbg-') + digest[:12] + (f'-v{variant}' if variant else '')


def remaining_quotas(snapshot, targets):
    return {mode: max(0, count - sum(task.get('mode') == mode and task.get('status') in {'qualified', 'ready'}
                                   for task in snapshot['tasks'])) for mode, count in targets.items()}


def filter_new_work_items(seeds, snapshot, modes):
    existing = {task['id']: task for task in snapshot['tasks']}
    result = []
    for seed in seeds:
        allowed = [mode for mode in seed.get('modes', list(modes)) if mode in modes
                   and candidate_task_id(seed, mode) not in existing]
        if allowed:
            result.append({**seed, 'modes': allowed})
    return result


def restore_target_claims(run_dir, snapshot):
    claims = {}
    for task in snapshot['tasks']:
        if task.get('status') not in {'qualified', 'ready'}:
            continue
        source = task.get('source_id')
        if not source:
            raise ResumeError('Existing accepted task is missing its original source_id')
        targets = task.get('targets')
        if not targets:
            revision = int(task.get('revision', 0) or 0)
            path = Path(run_dir) / 'tasks' / task['id'] / 'revisions' / f'{revision:03d}' / 'private/plan.json'
            try:
                plan = json.loads(path.read_text())
                targets = [(edit['sheet'], edit['cell']) for edit in plan['edits']]
            except (OSError, ValueError, KeyError) as exc:
                raise ResumeError(f'Cannot restore target deduplication for {task["id"]}') from exc
        key = (source, task['mode'], frozenset(tuple(target) for target in targets))
        if key in claims and claims[key] != task['id']:
            raise ResumeError('Existing accepted tasks have duplicate source/mode target sets')
        claims[key] = task['id']
    return claims


def normalize_extra_manifest(path):
    path = Path(path).resolve()
    data = json.loads(path.read_text())
    entries = data.get('selected', data.get('sources'))
    if not isinstance(entries, list):
        raise ResumeError('Extra manifest requires a selected or sources list')
    # Research manifests keep file-selection metadata and business evidence in
    # separate lists. Preserve that evidence when freezing the selected files.
    business = data.get('finance_evidence', {})
    business = business.get('sources', []) if isinstance(business, dict) else business
    facts = {}
    for record in [*(data.get('sources', []) if isinstance(data.get('sources'), list) else []),
                   *(business if isinstance(business, list) else [])]:
        if isinstance(record, dict):
            digest = record.get('sha256') or record.get('source_sha256')
            if digest:
                facts[digest] = {**facts.get(digest, {}), **record}
    selected, seen = [], set()
    for original in entries:
        item = deepcopy(original)
        location = item.get('local_path', item.get('source_path'))
        if not location:
            raise ResumeError('Extra source entry has no local_path/source_path')
        source = Path(location)
        if not source.is_absolute():
            source = path.parent / source
        source = source.resolve()
        if not source.is_file() or source.suffix.lower() not in {'.xls', '.xlsx'}:
            raise ResumeError(f'Extra source is not an available XLS/XLSX file: {source}')
        actual_hash = _hash(source)
        declared = item.get('sha256', item.get('source_sha256'))
        if declared and declared != actual_hash:
            raise ResumeError(f'Extra source hash mismatch: {source.name}')
        if actual_hash in seen:
            continue
        seen.add(actual_hash)
        item.update(local_path=str(source), sha256=actual_hash)
        if actual_hash in facts:
            item['finance_evidence'] = {**facts[actual_hash], **item.get('finance_evidence', {})}
        if 'finance_evidence' not in item and 'financial_modeling_eligible' in item:
            item['finance_evidence'] = {key: item[key] for key in
                ('financial_modeling_eligible', 'scenario_required', 'safe_modules', 'source_business_issues', 'evidence', 'risk')
                if key in item}
        selected.append(item)
    return {**data, 'selected': selected, 'selected_count': len(selected),
            'parent_manifest_path': str(path), 'parent_manifest_sha256': _hash(path)}


def _merge(base, patch):
    result = deepcopy(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def plan_external_repairs(run_dir, snapshot, config, task_ids, review_files=()):
    """Validate explicit repair requests without mutating existing task records."""
    from .checkers.router import route_issues
    run_dir, root = Path(run_dir), Path(config['project_root'])
    tasks = {task['id']: task for task in snapshot['tasks']}
    catalog = yaml.safe_load((root / 'config/routes.yaml').read_text())
    sources = {}
    for filename in [config['run']['seed_manifest'], *config['run'].get('additional_seed_manifests', [])]:
        path = Path(filename)
        path = path if path.is_absolute() else root / path
        for seed in json.loads(path.read_text()).get('selected', []):
            sources[seed['sha256']] = {**sources.get(seed['sha256'], {}), **seed}
    supplied = [Path(path).resolve() for path in review_files]
    specifications = []
    for task_id in dict.fromkeys(task_ids or []):
        task = tasks.get(task_id)
        if not task or task.get('status') not in PRESERVED_TASK_STATES:
            raise ResumeError(f'External repair requires an existing terminal/ready task: {task_id}')
        revision = int(task.get('revision', 0))
        if revision >= int(config['run']['max_steps']):
            raise ResumeError(f'Content repair budget exhausted for {task_id}: revision {revision}')
        if int(task.get('content_repairs', revision)) > revision:
            raise ResumeError(f'Inconsistent recorded content budget for {task_id}')
        directory = run_dir / 'tasks' / task_id
        paths = [directory / 'external_quality_review.json', *supplied]
        issues, evidence_files = [], []
        for path in dict.fromkeys(paths):
            if not path.is_file():
                continue
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                raise ResumeError(f'External review must be a JSON object: {path}')
            if data.get('task_id') not in (None, task_id):
                continue
            entries = data.get('issues', [data] if data.get('issue_id') else [])
            relevant = []
            for issue in entries:
                if not isinstance(issue, dict):
                    raise ResumeError(f'External issue must be a JSON object: {path}')
                if issue.get('task_id', data.get('task_id', task_id)) != task_id:
                    continue
                reviewed_revision = issue.get('revision', data.get('revision'))
                if reviewed_revision is not None and int(reviewed_revision) != revision:
                    raise ResumeError(f'Stale external review for {task_id}')
                if issue.get('certainty') != 'confirmed':
                    continue
                if not issue.get('issue_id') or not issue.get('evidence') or not issue.get('claim'):
                    raise ResumeError(f'External issue lacks numbered evidence for {task_id}')
                declared_route = issue.get('route_id', issue.get('repair_route'))
                if not declared_route:
                    raise ResumeError(f'External issue lacks an explicit repair route for {task_id}')
                try:
                    route = route_issues([{**issue, 'depends_on_issue_ids': []}], catalog)[0]
                except (KeyError, ValueError) as exc:
                    raise ResumeError(f'Unknown external problem/route for {task_id}') from exc
                if route['route_class'] != 'repair' or declared_route != route['route_id']:
                    raise ResumeError(f'External issue is not a confirmed content-repair route for {task_id}')
                relevant.append({**issue, 'depends_on_issue_ids': []})
            if relevant:
                issues.extend(relevant)
                evidence_files.append({'path': str(path), 'sha256': _hash(path)})
        issues = list({issue['issue_id']: issue for issue in issues}.values())
        if not issues:
            raise ResumeError(f'No confirmed repair issue file available for {task_id}')
        source_id = task.get('source_id')
        seed = deepcopy(sources.get(source_id))
        if not seed:
            raise ResumeError(f'Original source is absent from the run manifests for {task_id}')
        source = Path(seed['local_path'])
        if not source.is_absolute():
            source = root / source
        if not source.is_file() or _hash(source) != source_id:
            raise ResumeError(f'Immutable source hash changed or source missing for {task_id}')
        seed.update(local_path=str(source.resolve()), variant=int(task.get('variant', 0)))
        if candidate_task_id(seed, task['mode']) != task_id:
            raise ResumeError(f'Task ID and immutable source identity disagree for {task_id}')
        private = directory / 'revisions' / f'{revision:03d}' / 'private'
        baseline = run_dir / 'sources' / source_id[:12] / 'baseline.xlsx'
        artifacts = {'plan': private / 'plan.json', 'diagnosis': private / 'diagnosis.json', 'baseline': baseline}
        if any(not path.is_file() for path in artifacts.values()):
            raise ResumeError(f'Cannot restore the last constructed plan/diagnosis/baseline for {task_id}')
        specifications.append({'task_id': task_id, 'mode': task['mode'], 'revision': revision,
            'seed': seed, 'previous_task': task, 'issues': issues,
            'routes': route_issues(issues, catalog), 'review_files': evidence_files,
            'artifacts': {key: {'path': str(path), 'sha256': _hash(path)} for key, path in artifacts.items()}})
    return specifications


@dataclass
class ResumeSession:
    audit: AuditStore
    config: dict
    lease: ProducerLease
    previous_snapshot: dict
    existing_task_ids: set
    target_claims: dict

    def close(self):
        # A dashboard/preflight failure may happen after authorization but before
        # a queued repair starts. Keep it terminal and explicitly repairable;
        # never leave a fictitious interrupted agent context behind.
        for task in self.audit.snapshot()['tasks']:
            if task.get('status') == 'repair_pending':
                self.audit.task(task['id'], status='rejected', node='external_repair_not_started',
                                error='Authorized external repair did not start in this execution phase')
                self.audit.emit('task.external_repair_not_started', task_id=task['id'],
                                revision=task.get('revision'), budget_preserved=True)
        self.audit.update_run(producer_active=False)
        self.lease.release()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def prepare_resume(run_dir, *, config_patch=None, extra_manifest=None, current_code_revision=None,
                   reason='Continue the terminal run with additional verified source candidates', producer_probe=None,
                   repair_tasks=(), review_files=()):
    """Create an audited phase; no existing task or budget record is modified."""
    run_dir = Path(run_dir).resolve()
    if not (run_dir / 'run.sqlite').is_file() or not (run_dir / 'resolved_config.yaml').is_file():
        raise ResumeError('Continuation requires an existing audit database and resolved configuration')
    lease = ProducerLease(run_dir).acquire()
    audit = None
    try:
        snapshot = read_run(run_dir)
        assert_resume_allowed(run_dir, snapshot, producer_probe)
        config_path = run_dir / 'resolved_config.yaml'
        old_text = config_path.read_text()
        old = yaml.safe_load(old_text)
        new = _merge(old, config_patch)
        scheduler_before = validate_scheduler(old['run'].get('scheduler', 'source_batches'))
        scheduler_after = validate_scheduler(new['run'].get('scheduler', 'source_batches'))
        for key in PROTECTED_BUDGETS:
            if new['run'].get(key) != old['run'].get(key):
                raise ResumeError(f'Resumption may not reset or change repair budget: {key}')
        if new['run']['targets'] != old['run']['targets']:
            raise ResumeError('Target quotas cannot change during continuation')
        old_agents, new_agents = deepcopy(old.get('agents', {})), deepcopy(new.get('agents', {}))
        old_parallel, new_parallel = old_agents.pop('max_parallel_calls', None), new_agents.pop('max_parallel_calls', None)
        if old_agents != new_agents:
            raise ResumeError('Agent/provider configuration must remain unchanged for this continuation')
        if new_parallel != old_parallel and (not isinstance(new_parallel, int) or isinstance(new_parallel, bool) or new_parallel <= 0):
            raise ResumeError('max_parallel_calls must be a positive integer')
        if new.get('run_dir') != old.get('run_dir') or new.get('project_root') != old.get('project_root'):
            raise ResumeError('Run and project identity cannot change')
        if any(new['run'].get(key) != old['run'].get(key) for key in ('seed_manifest', 'seed_path')):
            raise ResumeError('Keep the original source manifest; append sources through extra_manifest')
        if int(new['run'].get('max_sources', 0)) < int(old['run'].get('max_sources', 0)):
            raise ResumeError('Continuation cannot truncate the existing source pool')
        repairs = plan_external_repairs(run_dir, snapshot, old, repair_tasks, review_files) if repair_tasks else []
        claims = restore_target_claims(run_dir, snapshot)
        continuation_id = uuid4().hex[:12]
        private = run_dir / 'private/resume'
        private.mkdir(parents=True, exist_ok=True)
        extra = None
        if extra_manifest:
            extra = normalize_extra_manifest(extra_manifest)
            path = private / f'extra_sources_{continuation_id}.json'
            path.write_text(json.dumps(extra, ensure_ascii=False, indent=2) + '\n')
            manifests = list(new['run'].get('additional_seed_manifests', []))
            manifests.append(str(path))
            new['run']['additional_seed_manifests'] = manifests
            # The original source limit must not silently truncate appended seeds.
            new['run']['max_sources'] = int(new['run'].get('max_sources', 0)) + len(extra['selected'])
        new['run']['continuation_id'] = continuation_id
        new['run']['resume_existing_task_ids'] = sorted(task['id'] for task in snapshot['tasks'])
        repair_path = private / f'external_repairs_{continuation_id}.json'
        repair_path.write_text(json.dumps(repairs, ensure_ascii=False, indent=2) + '\n')
        new['run']['external_repair_manifest'] = str(repair_path)
        before = private / f'resolved_config_before_{continuation_id}.yaml'
        after = private / f'resolved_config_after_{continuation_id}.yaml'
        before.write_text(old_text)
        new_text = yaml.safe_dump(new, sort_keys=False, allow_unicode=True)
        after.write_text(new_text)
        config_path.write_text(new_text)
        previous = snapshot['run']
        audit = AuditStore(run_dir, previous)
        for specification in repairs:
            task_id = specification['task_id']
            old_export = run_dir / 'SpreadsheetEval' / task_id
            quarantine = run_dir / 'rejected_exports' / f'{task_id}-r{specification["revision"]:03d}-{continuation_id}'
            if old_export.exists():
                quarantine.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old_export), quarantine)
            audit.task(task_id, status='repair_pending', node='external_repair_pending',
                       external_repair_issues=specification['issues'], harbor_controls=None,
                       historical_export=str(quarantine) if quarantine.exists() else None)
            audit.emit('task.external_repair_authorized', task_id=task_id, revision=specification['revision'],
                       continuation_id=continuation_id, issue_ids=[issue['issue_id'] for issue in specification['issues']],
                       prior_status=specification['previous_task']['status'], review_files=specification['review_files'],
                       old_budget={key: specification['previous_task'].get(key) for key in
                           ('revision', 'content_repairs', 'evidence_rounds', 'infrastructure_retries')},
                       historical_harbor_controls=specification['previous_task'].get('harbor_controls'))
        history = list(previous.get('code_history', []))
        if not history:
            history.append({'code_revision': previous.get('code_revision'),
                            'started_at': previous.get('started_at'), 'phase': 'initial'})
        history.append({'code_revision': current_code_revision, 'started_at': _now(),
                        'phase': 'continuation', 'continuation_id': continuation_id})
        now = _now()
        previous_wall = previous.get('wall_seconds')
        audit.update_run(status='resuming', code_revision=current_code_revision or previous.get('code_revision'),
                         code_history=history, resume_count=int(previous.get('resume_count', 0)) + 1,
                         resumed_at=now, previous_wall_seconds=previous_wall, wall_seconds=None,
                         producer_pid=os.getpid(), producer_start_ticks=_pid_start(os.getpid()), producer_active=True,
                         scheduler=scheduler_after)
        audit.emit('run.amended', amendment='configuration_and_source_pool', reason=reason,
                   continuation_id=continuation_id, config_before_sha256=_digest(old), config_after_sha256=_digest(new),
                   config_before_artifact=str(before), config_after_artifact=str(after),
                   extra_manifest_sha256=extra.get('parent_manifest_sha256') if extra else None,
                   additional_source_count=len(extra['selected']) if extra else 0,
                   max_parallel_calls_before=old_parallel, max_parallel_calls_after=new_parallel,
                   scheduler_before=scheduler_before, scheduler_after=scheduler_after,
                   external_repair_task_ids=[specification['task_id'] for specification in repairs],
                   external_repair_manifest_sha256=_hash(repair_path))
        audit.emit('run.resumed', continuation_id=continuation_id, reason=reason, previous_status=previous.get('status'),
                   preserved_task_count=len(snapshot['tasks']), remaining_quotas=remaining_quotas(audit.snapshot(), new['run']['targets']),
                   previous_code_revision=previous.get('code_revision'), current_code_revision=current_code_revision,
                   original_started_at=previous.get('started_at'), previous_wall_seconds=previous_wall)
        return ResumeSession(audit, new, lease, snapshot, {task['id'] for task in snapshot['tasks']}, claims)
    except Exception:
        if audit is not None:
            audit.db.close()
        lease.release()
        raise
