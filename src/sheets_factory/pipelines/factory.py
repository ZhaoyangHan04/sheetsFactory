from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
import threading
import time

from ..core.node import TaskContext, TaskRejected
from ..core.pipeline import BasePipeline
from ..checkers import DiagnosisRunner
from ..checkers.router import route_issues
from ..checkers.unsafe_regions import evaluate_native_risk_guard
from ..evaluation.harbor import run_controls
from ..resume import candidate_task_id, restore_target_claims, validate_scheduler
from ..reporting import read_run


def diagnostic_action(report):
    """Select an action from numbered evidence, never solver completion/reward."""
    routes = [route for route in report.get('routes', []) if route.get('disposition') != 'deferred_by_run_scope']
    issues = {issue['issue_id']: issue for issue in report.get('issues', [])}
    infrastructure = [route for route in routes if route['route_class'] == 'infrastructure_retry']
    repairs = [route for route in routes if route['route_class'] == 'repair'
               and issues.get(route['issue_id'], {}).get('certainty') == 'confirmed']
    evidence = [route for route in routes if route['route_class'] == 'evidence_collection']
    if infrastructure:
        return 'infrastructure_retry', infrastructure
    # Known defects can prevent a recovery witness. Repair only those confirmed
    # instances and retain unknown/suspected findings for the next diagnosis.
    if repairs:
        return 'repair', repairs
    if evidence or report.get('coverage', {}).get('unknown_check_ids') or not report.get('releasable'):
        return 'evidence', evidence
    return 'export', []


class _ExternalRepairContext(TaskContext):
    @property
    def revision_dir(self):
        # Repair proposals must not overwrite artifacts in a closed revision.
        return self.directory / 'external_repairs' / self.config['run']['continuation_id']


class FactoryPipeline(BasePipeline):
    """Template-driven quota controller with distinct bounded repair budgets."""

    def __init__(self, config, audit, llm, engine):
        super().__init__(config)
        self.audit, self.llm, self.engine = audit, llm, engine
        self.targets = config['run']['targets']
        self.scheduler = validate_scheduler(config['run'].get('scheduler', 'source_batches'))
        self.lock = threading.RLock()
        self.active = {mode: 0 for mode in self.targets}
        self.inflight_tasks = {}
        self.busy_sources = set()
        self.target_claims = (restore_target_claims(config['run_dir'], read_run(config['run_dir']))
                              if config['run'].get('continuation_id') else {})
        self.route_catalog = DiagnosisRunner(config['project_root']).catalog

    def counts(self):
        tasks = self.audit.snapshot()['tasks']
        return {mode: sum(task.get('mode') == mode and task.get('status') in {'ready', 'qualified'} for task in tasks)
                for mode in self.targets}

    def _quota_used_locked(self, tasks=None):
        tasks = self.audit.snapshot()['tasks'] if tasks is None else tasks
        return {mode: len({task['id'] for task in tasks if task.get('mode') == mode
                          and task.get('status') in {'ready', 'qualified'}} |
                         {task_id for task_id, current in self.inflight_tasks.items() if current == mode})
                for mode in self.targets}

    def reserve(self, mode, task_id):
        with self.lock:
            tasks = self.audit.snapshot()['tasks']
            if task_id in self.inflight_tasks or any(task['id'] == task_id for task in tasks):
                return False
            if self._quota_used_locked(tasks)[mode] >= self.targets[mode]:
                return False
            self.inflight_tasks[task_id] = mode
            self.active[mode] += 1
            return True

    def _release_task(self, mode, task_id):
        with self.lock:
            if self.inflight_tasks.get(task_id) == mode:
                del self.inflight_tasks[task_id]
                self.active[mode] -= 1

    def goal_ready(self):
        return all(self.counts()[mode] >= count for mode, count in self.targets.items())

    def _context(self, seed, mode):
        source = Path(seed['local_path'])
        variant = int(seed.get('variant', 0))
        task_id = candidate_task_id(seed, mode)
        folder = Path(self.config['run_dir']) / 'tasks' / task_id
        folder.mkdir(parents=True, exist_ok=True)
        context = TaskContext(self.audit.run['id'], task_id, mode, source, folder,
                              self.config, self.audit, self.llm, self.engine)
        context.data.update(survey=seed.get('survey', {}), variant=variant,
                            finance_evidence=seed.get('finance_evidence', {}),
                            source_business_issues=seed.get('finance_evidence', {}).get('source_business_issues', []))
        self.audit.task(task_id, mode=mode, source_id=seed['sha256'], source=source.name,
                        variant=variant, status='scheduled', difficulty_status='deferred')
        return context

    def _claim_targets(self, context):
        targets = frozenset((edit['sheet'], edit['cell']) for edit in context.data['plan'].get('edits', []))
        if not targets:
            raise TaskRejected('Q06: task plan contains no target cells')
        source_id = context.data.get('source_id', '')
        overlap_limit = self.config['run'].get('max_target_overlap', 0.8)
        with self.lock:
            states = {task['id']: task.get('status') for task in self.audit.snapshot()['tasks']}
            for (source, mode, prior_targets), owner in self.target_claims.items():
                if owner == context.task_id or source != source_id or mode != context.mode:
                    continue
                if states.get(owner) == 'rejected':
                    continue
                overlap = len(targets & prior_targets) / len(targets | prior_targets)
                if overlap >= overlap_limit:
                    raise TaskRejected(f'Q08: duplicate or substantially overlapping target module with {owner}')
            self.target_claims[(source_id, context.mode, targets)] = context.task_id
        fingerprint = hashlib.sha256(json.dumps(sorted(targets)).encode()).hexdigest()
        context.data['target_fingerprint'] = fingerprint
        self.audit.task(context.task_id, target_fingerprint=fingerprint, targets=sorted(targets))

    def _construction_report(self, context, error):
        problem_ids = list(dict.fromkeys(re.findall(r'Q\d{2}', str(error)))) or ['Q06']
        known = {problem['problem_id'] for problem in self.route_catalog['problems']}
        issues = [{'issue_id': f'{context.task_id}-{problem}-construction', 'problem_id': problem,
                   'certainty': 'confirmed', 'severity': 'blocker', 'claim': str(error),
                   'evidence': [{'kind': 'program_gate', 'node': 'construction_or_precheck', 'error': str(error)}],
                   'revision_hash': context.data.get('revision_hash', ''), 'depends_on_issue_ids': []}
                  for problem in problem_ids if problem in known]
        return {'releasable': False, 'issues': issues, 'assessments': {},
                'coverage': {'unknown_check_ids': [], 'blocking_issue_ids': [issue['issue_id'] for issue in issues]},
                'routes': route_issues(issues, self.route_catalog)}

    def process_task(self, seed, mode):
        task_id = candidate_task_id(seed, mode)
        with self.lock:
            existing = task_id in self.inflight_tasks or any(
                task['id'] == task_id for task in self.audit.snapshot()['tasks'])
            admitted = False if existing else self.reserve(mode, task_id)
        if existing:
            self.audit.emit('task.skipped_existing', task_id=task_id, mode=mode,
                            reason='Continuation preserves existing terminal/ready tasks and all budgets')
            return {'task_id': task_id, 'status': 'skipped_existing'}
        if not admitted:
            self.audit.emit('scheduler.quota_deferred', task_id=task_id, mode=mode,
                            source_id=seed['sha256'], variant=seed.get('variant', 0))
            return {'task_id': task_id, 'status': 'quota_deferred'}
        try:
            context = self._context(seed, mode)
            self.run_phase(context, 'preparation')
            self._execute_context(context)
        except Exception as exc:
            self.audit.task(task_id, mode=mode, source_id=seed['sha256'], source=Path(seed['local_path']).name,
                            variant=seed.get('variant', 0), status='rejected', error=str(exc)[:2400], node='rejected')
            self.audit.emit('task.rejected', task_id=task_id, mode=mode, reason=str(exc)[:2400])
        finally:
            self._release_task(mode, task_id)
            self.audit.export()
        return {'task_id': task_id, 'status': 'processed'}

    def _apply_repair(self, context, routes):
        if context.revision >= int(self.config['run']['max_steps']):
            raise TaskRejected('EXHAUSTED: content repair budget exhausted')
        context.data['repair_routes'] = routes
        self.run_phase(context, 'repair')
        proposed = context.data.pop('next_plan', None)
        if not proposed:
            raise TaskRejected('No evidence-supported repair available')
        old_plan = context.data['plan']
        if proposed == old_plan:
            raise TaskRejected('Repair made no change; stopping repeated no-progress cycle')
        if {route['problem_id'] for route in routes} == {'Q03'}:
            old_other = {key: value for key, value in old_plan.items() if key != 'public_instruction'}
            new_other = {key: value for key, value in proposed.items() if key != 'public_instruction'}
            if old_other != new_other or not proposed.get('public_instruction'):
                raise TaskRejected('Q03: instruction-only repair changed business rules or workbook construction')
        context.data['plan'] = proposed
        context.revision += 1

    def _execute_context(self, context, phase='revision', evidence_rounds=0, infrastructure_retries=0):
        max_steps = int(self.config['run']['max_steps'])
        while True:
            context.data.pop('construction_error', None)
            try:
                if phase == 'revision':
                    self._claim_targets(context)
                    context.data.pop('diagnosis', None)
                self.run_phase(context, phase)
            except TaskRejected as exc:
                context.data['construction_error'] = str(exc)
                context.data['diagnosis'] = self._construction_report(context, exc)
            report = context.data.get('diagnosis')
            if report is None:
                raise TaskRejected('UNRESOLVED: pipeline phase did not produce a diagnosis')
            action, routes = diagnostic_action(report)
            self.audit.emit('task.route', task_id=context.task_id, revision=context.revision,
                            action=action, issue_ids=[route['issue_id'] for route in routes])
            if action == 'export':
                self.run_phase(context, 'export')
                self.audit.task(context.task_id, status='ready', node='harbor_pending',
                                title=context.data['plan']['title'], revision=context.revision,
                                export_dir=str(context.data['export_dir']), independent_recovery=True, error=None,
                                harbor_controls=None)
                self.audit.emit('task.ready', task_id=context.task_id, mode=context.mode, revision=context.revision)
                break
            if action == 'infrastructure_retry':
                budget = self.config['run'].get('infrastructure_retries_per_stage', 2)
                if infrastructure_retries >= budget:
                    raise TaskRejected('INFRA_FAILED: same-revision infrastructure retry budget exhausted')
                infrastructure_retries += 1
                issues = {issue['issue_id']: issue for issue in report.get('issues', [])}
                diagnosis_only = bool(routes) and all(
                    issues.get(route['issue_id'], {}).get('fault_stage') == 'diagnose' for route in routes)
                phase = 'diagnosis_retry' if diagnosis_only else 'infrastructure_retry'
            elif action == 'evidence':
                budget = self.config['run'].get('max_evidence_rounds_per_revision', 2)
                if evidence_rounds >= budget:
                    raise TaskRejected('UNRESOLVED: same-revision evidence budget exhausted')
                evidence_rounds += 1
                phase = 'evidence'
            else:
                if context.revision >= max_steps:
                    raise TaskRejected('EXHAUSTED: content repair budget exhausted')
                self._apply_repair(context, routes)
                evidence_rounds = infrastructure_retries = 0
                phase = 'revision'
                self.audit.emit('task.revised', task_id=context.task_id, next_revision=context.revision)
            self.audit.task(context.task_id, evidence_rounds=evidence_rounds,
                            infrastructure_retries=infrastructure_retries, content_repairs=context.revision)

    def process_external_repair(self, specification):
        """Reopen only an explicitly authorized task; consume its next revision."""
        task_id, mode = specification['task_id'], specification['mode']
        previous = specification['previous_task']
        revision = specification['revision']
        state = next(task for task in self.audit.snapshot()['tasks'] if task['id'] == task_id)
        if state.get('status') != 'repair_pending' or int(state.get('revision', 0)) != revision:
            raise TaskRejected('External repair authorization is not pending at the recorded revision')
        with self.lock:
            self.active[mode] += 1
            self.inflight_tasks[task_id] = mode
        folder = Path(self.config['run_dir']) / 'tasks' / task_id
        seed = specification['seed']
        finance_evidence = seed.get('finance_evidence') or self._finance_evidence().get(previous['source_id'], {})
        context = _ExternalRepairContext(self.audit.run['id'], task_id, mode, Path(seed['local_path']),
            folder, self.config, self.audit, self.llm, self.engine, revision=revision)
        context.data.update(variant=int(seed.get('variant', 0)), survey=seed.get('survey', {}),
            finance_evidence=finance_evidence,
            source_business_issues=finance_evidence.get('source_business_issues', []))
        try:
            if hashlib.sha256(context.source.read_bytes()).hexdigest() != previous['source_id']:
                raise TaskRejected('Immutable repair source changed after authorization')
            for artifact in specification['artifacts'].values():
                if hashlib.sha256(Path(artifact['path']).read_bytes()).hexdigest() != artifact['sha256']:
                    raise TaskRejected('Closed task artifact changed after external repair authorization')
            context.data['plan'] = json.loads(Path(specification['artifacts']['plan']['path']).read_text())
            report = json.loads(Path(specification['artifacts']['diagnosis']['path']).read_text())
            existing = {issue['issue_id']: issue for issue in report.get('issues', [])}
            existing.update({issue['issue_id']: issue for issue in specification['issues']})
            report.update(issues=list(existing.values()), releasable=False,
                          routes=route_issues(list(existing.values()), self.route_catalog))
            if {route['problem_id'] for route in specification['routes']} == {'Q03'}:
                report['external_repair_contract'] = {'permitted_changed_plan_fields': ['public_instruction'],
                    'keep_all_other_plan_fields_exactly': True, 'normalized_baseline_must_not_change': True,
                    'reason': 'Instruction-only mismatch; preserve existing target, mutation, assumptions and reference.'}
            context.data['diagnosis'] = report
            # Rebuild only source facts. Planning again would silently replace
            # the closed task and discard the externally numbered issue.
            for node in ('normalize', 'profile'):
                self.load_node(node).run(context)
            if context.data['source_id'] != previous['source_id']:
                raise TaskRejected('Restored source identity does not match the original task')
            cached_plan = Path(context.data.get('source_cache', context.data['baseline'].parent)) / f'task_plans_v{context.data["variant"]}.json'
            if cached_plan.is_file():
                context.data['source_assessment'] = json.loads(cached_plan.read_text()).get('source_assessment', {})
            self.audit.emit('task.external_repair_started', task_id=task_id, revision=revision,
                previous_evidence_rounds=previous.get('evidence_rounds'),
                previous_infrastructure_retries=previous.get('infrastructure_retries'),
                issue_ids=[issue['issue_id'] for issue in specification['issues']])
            self._apply_repair(context, specification['routes'])
            self.audit.task(task_id, revision=context.revision, content_repairs=context.revision,
                            evidence_rounds=0, infrastructure_retries=0, harbor_controls=None,
                            independent_recovery=False, external_repair_pending=False)
            if hashlib.sha256(Path(context.data['baseline']).read_bytes()).hexdigest() != specification['artifacts']['baseline']['sha256']:
                raise TaskRejected('Instruction/task repair changed the immutable normalized baseline')
            self.audit.emit('task.revised', task_id=task_id, next_revision=context.revision,
                            reason='explicit_confirmed_external_repair')
            ordinary = TaskContext(context.run_id, context.task_id, context.mode, context.source,
                context.directory, context.config, context.audit, context.llm, context.engine,
                revision=context.revision, data=context.data)
            self._execute_context(ordinary)
        except Exception as exc:
            self.audit.task(task_id, status='rejected', node='external_repair_failed', error=str(exc)[:2400])
            self.audit.emit('task.rejected', task_id=task_id, mode=mode, reason=str(exc)[:2400],
                            external_repair=True)
        finally:
            self._release_task(mode, task_id)
            self.audit.export()

    def process_source(self, seed):
        result = {'attempted_task_ids': [], 'quota_deferred_modes': [], 'skipped_existing': []}
        for mode in self.targets:
            if mode in seed.get('modes', list(self.targets)):
                outcome = self.process_task(seed, mode)
                if outcome['status'] == 'processed':
                    result['attempted_task_ids'].append(outcome['task_id'])
                elif outcome['status'] == 'quota_deferred':
                    result['quota_deferred_modes'].append(mode)
                else:
                    result['skipped_existing'].append(outcome['task_id'])
        return result

    def _finance_evidence(self):
        path = Path(self.config['project_root']) / 'data/manifests/finance_model_evidence.json'
        if not path.is_file():
            return {}
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            if 'sources' in data or 'models' in data:
                data = data.get('sources', data.get('models'))
            else:
                return data
        return {item.get('source_sha256', item.get('sha256', item.get('source_id', item.get('filename', '')))): item
                for item in data}

    def load_seeds(self):
        root = Path(self.config['project_root'])
        path = Path(self.config['run']['seed_manifest'])
        manifest = json.loads((path if path.is_absolute() else root / path).read_text())
        seeds = manifest['selected']
        original_pool_count = len(seeds)
        merged = {seed['sha256']: seed for seed in seeds}
        additional_entries = []
        additional_manifests = self.config['run'].get('additional_seed_manifests', [])
        for additional in additional_manifests:
            additional_path = Path(additional)
            if not additional_path.is_absolute():
                additional_path = root / additional_path
            entries = json.loads(additional_path.read_text()).get('selected', [])
            additional_entries.extend(entries)
            for entry in entries:
                merged[entry['sha256']] = {**merged.get(entry['sha256'], {}), **entry}
        seeds = list(merged.values())
        custom_seed_path = self.config['run'].get('seed_path')
        custom_unknown_sources = set()
        if custom_seed_path:
            seed_path = Path(custom_seed_path)
            if not seed_path.exists():
                raise ValueError('Configured seed path does not exist')
            files = [seed_path] if seed_path.is_file() else sorted(seed_path.rglob('*'))
            existing = {item['sha256']: item for item in seeds}
            discovered = {}
            for file in files:
                if not file.is_file() or file.suffix.lower() not in {'.xls', '.xlsx'}:
                    continue
                source_hash = hashlib.sha256(file.read_bytes()).hexdigest()
                discovered[source_hash] = {**existing.get(source_hash, {}), 'sha256': source_hash,
                    'local_path': str(file.resolve()), 'rank_score': existing.get(source_hash, {}).get('rank_score', 0)}
                if source_hash not in existing:
                    custom_unknown_sources.add(source_hash)
            for entry in additional_entries:
                discovered[entry['sha256']] = {**discovered.get(entry['sha256'], {}), **entry}
            seeds = list(discovered.values())
            manifest = {**manifest, 'unique_workbooks_inspected': len(files), 'selected': seeds,
                        'download_url': 'local-seed-directory:' + str(seed_path), 'archive_sha256': None}
        survey_file = root / 'data/manifests/euses_financial_survey.json'
        survey = {item['source_sha256']: item for item in json.loads(survey_file.read_text())} if survey_file.exists() else {}
        finance = self._finance_evidence()
        for seed in seeds:
            seed['survey'] = survey.get(seed['sha256'], {})
            seed['finance_evidence'] = seed.get('finance_evidence') or finance.get(seed['sha256'], finance.get(Path(seed['local_path']).name,
                {'financial_modeling_eligible': False, 'reason': 'No positive finance-module evidence'} if finance else {}))
            if seed['sha256'] in custom_unknown_sources:
                # General seed inputs receive semantic assessment; the EUSES-only
                # first-run whitelist must not forbid unrelated future sources.
                seed['finance_evidence'] = {}
            evidence = seed['finance_evidence']
            eligibility = evidence.get('financial_modeling_eligible', evidence.get('eligible')) if isinstance(evidence, dict) else None
            if eligibility is False:
                seed['modes'] = [mode for mode in self.targets if mode != 'financial_modeling']
        seeds.sort(key=lambda seed: (
            0 if seed['finance_evidence'].get('financial_modeling_eligible') is True else 1,
            0 if seed['survey'].get('status') == 'ok' and seed['survey'].get('error_count') == 0 else 1,
            -seed.get('rank_score', 0)))
        if self.config['run'].get('source_filter'):
            seeds = [seed for seed in seeds if self.config['run']['source_filter'].lower() in seed['local_path'].lower()]
        self.audit.update_run(discovered_sources=manifest['unique_workbooks_inspected'], selected_sources=len(seeds),
                              original_selected_sources=original_pool_count,
                              additional_selected_sources=len(merged) - original_pool_count,
                              additional_seed_manifests=additional_manifests,
                              preprocess_attempted_sources=len(survey), source_archive=manifest['download_url'],
                              source_archive_sha256=manifest['archive_sha256'])
        return seeds[:self.config['run']['max_sources']]

    def variant_candidates(self, seeds, variant):
        if variant >= self.config['run'].get('max_candidates_per_seed', 3):
            return []
        states = self.audit.snapshot()['tasks']
        enabled_modes = self.config['run'].get('variant_modes', ['financial_modeling'])
        if not isinstance(enabled_modes, list) or any(mode not in self.targets for mode in enabled_modes):
            raise ValueError('run.variant_modes must list configured task modes')
        counts = self.counts()
        candidates = []
        structural_errors = (
            'Source lacks four nonempty sheets or a usable formula model',
            'Full profile exceeds the configured coverage limit',
            'Source contains no genuine cross-sheet formula dependency',
        )
        unusable = {task.get('source_id') for task in states
                    if str(task.get('error') or '').startswith(structural_errors)}
        for seed in seeds:
            if seed['sha256'] in unusable:
                continue
            evidence = seed.get('finance_evidence', {})
            modes = []
            for mode in enabled_modes:
                if counts[mode] >= self.targets[mode]:
                    continue
                explicit = (evidence.get('financial_modeling_eligible', evidence.get('eligible'))
                    if mode == 'financial_modeling' else seed.get('debugging_eligible', evidence.get('debugging_eligible')))
                productive = any(task.get('source_id') == seed['sha256'] and task.get('mode') == mode
                    and task.get('status') in {'ready', 'qualified'} for task in states)
                if explicit is True or productive:
                    modes.append(mode)
            if modes:
                candidates.append({**seed, 'variant': variant, 'modes': modes})
        return candidates

    def _construct_batch(self, seeds):
        workers = int(self.config['run']['max_parallel_sources'])
        cursor = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = set()
            while cursor < len(seeds) and len(pending) < workers and not self.goal_ready():
                pending.add(pool.submit(self.process_source, seeds[cursor])); cursor += 1
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    future.result()
                while cursor < len(seeds) and len(pending) < workers and not self.goal_ready():
                    pending.add(pool.submit(self.process_source, seeds[cursor])); cursor += 1
        return cursor

    def _eligible_source_jobs(self, seeds, states=None, busy_sources=None):
        """Derive intentions from existing IDs; a quota skip consumes no variant."""
        with self.lock:
            states = self.audit.snapshot()['tasks'] if states is None else states
            used = self._quota_used_locked(states)
            existing = {task['id'] for task in states} | set(self.inflight_tasks)
        available = {mode for mode, target in self.targets.items() if used[mode] < target}
        occupied = set(self.busy_sources if busy_sources is None else busy_sources)
        jobs = []
        rounds = [seeds] + [self.variant_candidates(seeds, variant) for variant in
                            range(1, self.config['run'].get('max_candidates_per_seed', 3))]
        for candidates in rounds:
            for seed in candidates:
                source = seed['sha256']
                if source in occupied:
                    continue
                modes = [mode for mode in seed.get('modes', list(self.targets))
                         if mode in available and candidate_task_id(seed, mode) not in existing]
                if modes:
                    jobs.append({**seed, 'modes': modes})
                    occupied.add(source)
        return jobs

    def _construct_rolling(self, seeds):
        """One future per source, with no barrier between unrelated variants."""
        workers = int(self.config['run']['max_parallel_sources'])
        submitted = 0
        pending = {}
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                while True:
                    while len(pending) < workers and not self.goal_ready():
                        candidates = self._eligible_source_jobs(seeds)
                        if not candidates:
                            break
                        seed = candidates[0]
                        source = seed['sha256']
                        self.busy_sources.add(source)
                        self.audit.emit('scheduler.source_dispatched', source_id=source,
                                        variant=seed.get('variant', 0), modes=seed['modes'])
                        started = time.monotonic()
                        try:
                            future = pool.submit(self.process_source, seed)
                        except BaseException:
                            self.busy_sources.remove(source)
                            self.audit.emit('scheduler.source_dispatch_failed', source_id=source,
                                            variant=seed.get('variant', 0))
                            raise
                        pending[future] = (seed, started)
                        submitted += 1
                        self.audit.update_run(source_jobs_inflight=len(pending))
                    if not pending:
                        self.audit.emit('scheduler.drain_started', reason='no_pending_source_jobs', pending=0)
                        break
                    done, _ = wait(tuple(pending), return_when=FIRST_COMPLETED)
                    for future in done:
                        seed, started = pending.pop(future)
                        try:
                            result = future.result()
                        except BaseException as exc:
                            self.audit.emit('scheduler.source_failed', source_id=seed['sha256'],
                                            variant=seed.get('variant', 0), error=str(exc)[:2400])
                            raise
                        finally:
                            self.busy_sources.remove(seed['sha256'])
                            self.audit.update_run(source_jobs_inflight=len(pending))
                        self.audit.emit('scheduler.source_completed', source_id=seed['sha256'],
                                        variant=seed.get('variant', 0),
                                        duration_ms=round((time.monotonic() - started) * 1000), **result)
        finally:
            # Executor shutdown drains submitted jobs, including on interruption.
            self.busy_sources.clear()
            self.audit.update_run(source_jobs_inflight=0)
        return submitted

    def _validate_exports(self):
        """All main/sidecar validators share one retained file-lock inode."""
        path = Path(self.config['run_dir']) / 'harbor_validation.lock'
        with path.open('a+') as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                return self._validate_exports_locked()
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _preharbor_native_risks(self, task, binding):
        """Re-read current facts against this revision's full D, never ancestry.

        Receipts live outside closed revisions. Missing evidence is unknown,
        not a newly confirmed business defect or a baseline certification.
        """
        from openpyxl import load_workbook
        from ..core.audit import utcnow

        run_dir = Path(self.config['run_dir'])
        delta_path = (run_dir / 'tasks' / task['id'] / 'revisions' /
                      f"{int(task.get('revision', 0)):03d}" / 'private/expected_delta.json')
        goal_path = run_dir / 'SpreadsheetEval' / task['id'] / 'tests/reference.xlsx'
        changes, sheet_names, hashes, unavailable = [], [], {}, []
        try:
            raw = delta_path.read_bytes()
            hashes['expected_delta_sha256'] = hashlib.sha256(raw).hexdigest()
            delta = json.loads(raw)
            changes = delta['expected_changes']
            if not isinstance(changes, (dict, list)):
                raise ValueError('Final expected_changes must contain computed cell addresses')
            hashes['goal_sha256'] = hashlib.sha256(goal_path.read_bytes()).hexdigest()
            book = load_workbook(goal_path, read_only=True, data_only=True, keep_links=False)
            try:
                sheet_names = list(book.sheetnames)
            finally:
                book.close()
        except (OSError, ValueError, TypeError, KeyError) as exc:
            changes = []  # Incomplete evidence must never create an intersection.
            unavailable.append({'source': 'final_revision_artifacts', 'reason': str(exc)})
        result = evaluate_native_risk_guard(changes, task.get('source_id'),
            project_root=self.config['project_root'], sheet_names=sheet_names,
            registry_path=self.config.get('native_risks', {}).get('registry_path'))
        if unavailable:
            result.update(state='unknown', blocking=False)
            result['evidence_requests'].extend(unavailable)
        result.update(task_id=task['id'], revision=int(task.get('revision', 0)),
            revision_hash=binding['revision_hash'], export_binding=binding,
            goal_sheet_names=sheet_names, **hashes)
        receipt_id = hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()
        previous = task.get('preharbor_native_risk_guard') or {}
        if previous.get('receipt_id') == receipt_id:
            return previous
        receipt_path = run_dir / 'private/preharbor_native_checks' / task['id'] / (receipt_id + '.json')
        result.update(receipt_id=receipt_id, checked_at=utcnow(), receipt_path=str(receipt_path))
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        self.audit.task(task['id'], preharbor_native_risk_guard=result)
        self.audit.emit('preharbor.native_risk_checked', task_id=task['id'],
            revision=result['revision'], revision_hash=result['revision_hash'],
            registry_sha256=result['registry_sha256'], state=result['state'],
            blocking=result['blocking'], receipt_path=str(receipt_path))
        return result

    def _withdraw_native_risk_export(self, task, binding, result, cumulative):
        """Withdraw current credit while retaining every historical control file."""
        from ..core.audit import utcnow

        issues = [{**issue, 'issue_id': issue['issue_id'] + '-preharbor-' + result['receipt_id'][:16],
                   'task_id': task['id'], 'revision': result['revision'],
                   'revision_hash': result['revision_hash'], 'registry_sha256': result['registry_sha256']}
                  for issue in result['issues'] if issue.get('certainty') == 'confirmed']
        reason = 'Q09/R09: latest confirmed native unsafe region intersects final expected delta: ' + ', '.join(
            sorted({cell for issue in issues for cell in issue['affected_cells']}))
        history = {'task_id': task['id'], 'previous_status': task['status'],
            'withdrawn_at': utcnow(), 'receipt_path': result['receipt_path'],
            'revision': result['revision'], 'revision_hash': result['revision_hash'],
            'registry_sha256': result['registry_sha256'], 'issues': issues,
            'harbor_controls': task.get('harbor_controls'),
            'harbor_export_binding': task.get('harbor_export_binding'),
            'cumulative_controls': cumulative['per_task'].pop(binding['task_name'], None),
            'cumulative_export_binding': cumulative['export_bindings'].pop(binding['task_name'], None)}
        cumulative.setdefault('native_risk_withdrawals', []).append(history)
        cumulative['complete'] = False
        values = {'status': 'rejected', 'node': 'preharbor_native_risk', 'error': reason,
            'issues': task.get('issues', []) + issues, 'harbor_controls': None,
            'harbor_export_binding': None,
            'native_risk_withdrawals': task.get('native_risk_withdrawals', []) + [history]}
        if task.get('harbor_controls'):
            values.update(historical_harbor_controls=task['harbor_controls'],
                          historical_harbor_export_binding=task.get('harbor_export_binding'))
        self.audit.task(task['id'], **values)
        export = Path(self.config['run_dir']) / 'SpreadsheetEval' / task['id']
        quarantine = (Path(self.config['run_dir']) / 'rejected_exports' /
                      (task['id'] + '-native-' + result['receipt_id'][:16]))
        if export.exists():
            quarantine.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(export), quarantine)
        self.audit.emit('task.rejected', task_id=task['id'], mode=task['mode'],
            reason=reason, problem_id='Q09', route_id='R09', revision=result['revision'],
            revision_hash=result['revision_hash'], registry_sha256=result['registry_sha256'],
            receipt_path=result['receipt_path'], quarantine_path=str(quarantine))

    def _validate_exports_locked(self):
        from uuid import uuid4
        import time
        from ..core.audit import utcnow
        from ..evaluation.harbor import inspect_export, matched_controls, control_summary_paths

        run_dir = Path(self.config['run_dir'])
        export_root = run_dir / 'SpreadsheetEval'
        summary_file = run_dir / 'harbor_controls.json'
        cumulative = json.loads(summary_file.read_text()) if summary_file.is_file() else {}
        if not isinstance(cumulative, dict):
            raise ValueError('Cumulative Harbor summary must be a JSON object')
        cumulative.setdefault('per_task', {})
        cumulative.setdefault('export_bindings', {})
        cumulative.setdefault('batches', [])
        cumulative.setdefault('summary_paths', [])
        selected, invalid = [], []
        for task in self.audit.snapshot()['tasks']:
            if task.get('status') not in {'ready', 'qualified'}:
                continue
            try:
                binding = inspect_export(export_root / task['id'])
                if binding['task_id'] != task['id'] or binding['revision'] != int(task.get('revision', 0)):
                    raise ValueError('Export identity/revision differs from the current audited task')
                if not binding.get('revision_hash'):
                    raise ValueError('Export has no immutable revision hash')
                if task.get('revision_hash') and task['revision_hash'] != binding['revision_hash']:
                    raise ValueError('Export revision hash differs from the audited task')
                native_risks = self._preharbor_native_risks(task, binding)
                if native_risks['blocking']:
                    self._withdraw_native_risk_export(task, binding, native_risks, cumulative)
                    continue
                proof = task.get('harbor_controls', {})
                if (task['status'] == 'qualified' and matched_controls(proof, task_name=binding['task_name'])
                    and task.get('harbor_export_binding') == binding):
                    # Also project separately validated early batches into the
                    # cumulative file, without rerunning or replacing the proof.
                    cumulative['per_task'][binding['task_name']] = proof
                    cumulative['export_bindings'][binding['task_name']] = binding
                    cumulative['summary_paths'] = sorted(set(cumulative['summary_paths']) |
                        set(control_summary_paths(proof, binding['task_name'])))
                    continue
                selected.append((task, binding))
            except (OSError, ValueError, TypeError, KeyError) as exc:
                invalid.append((task, str(exc)))
        if not selected and not invalid:
            if cumulative['per_task'] or cumulative.get('native_risk_withdrawals'):
                summary_file.write_text(json.dumps(cumulative, indent=2, default=str))
            return

        batch_id = uuid4().hex[:12]
        batch_dir = run_dir / 'harbor_batches' / batch_id
        staging = batch_dir / 'SpreadsheetEval'
        staging.mkdir(parents=True)
        jobs = run_dir / 'harbor_jobs' / batch_id
        jobs.mkdir(parents=True)
        started, stamp = time.monotonic(), utcnow()
        node_record = self.audit.record('nodes', {'node': 'harbor_validation', 'node_id': 'harbor_validation',
            'batch_id': batch_id, 'started_at': stamp, 'status': 'running'})
        self.audit.emit('node.started', node='harbor_validation', batch_id=batch_id)
        self.audit.update_run(status='harbor_validation')
        # Preserve a pre-batch projection as history before current task entries
        # are replaced or removed. Actual per-batch Harbor summaries stay intact.
        (batch_dir / 'cumulative_before.json').write_text(json.dumps(cumulative, indent=2, default=str))
        batch = {'batch_id': batch_id, 'staging': str(staging), 'jobs_dir': str(jobs),
                 'started_at': stamp, 'task_ids': [task['id'] for task, _ in selected + invalid],
                 'export_bindings': {binding['task_name']: binding for _, binding in selected},
                 'summary_path': None, 'complete': False, 'errors': []}
        staged = []

        def reject(task, reason, proof=None):
            self.audit.task(task['id'], status='rejected', node='harbor_failed', error=reason,
                            harbor_controls=proof or {}, harbor_export_binding=None)
            self.audit.emit('task.rejected', task_id=task['id'], mode=task['mode'],
                            reason=reason, harbor_batch_id=batch_id)
            failed = export_root / task['id']
            if failed.exists():
                quarantine = run_dir / 'rejected_exports' / (task['id'] + '-harbor-' + batch_id)
                quarantine.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(failed), quarantine)
            batch['errors'].append({'task_id': task['id'], 'reason': reason})

        try:
            for task, error in invalid:
                reject(task, 'Current Harbor output is missing or invalid: ' + error)
            for task, binding in selected:
                name = binding['task_name']
                cumulative['per_task'].pop(name, None)
                cumulative['export_bindings'].pop(name, None)
                if task['status'] == 'qualified':
                    self.audit.task(task['id'], status='ready', node='harbor_pending',
                        historical_harbor_controls=task.get('harbor_controls'),
                        historical_harbor_export_binding=task.get('harbor_export_binding'),
                        harbor_controls=None, harbor_export_binding=None)
                try:
                    shutil.copytree(export_root / task['id'], staging / task['id'])
                    if inspect_export(staging / task['id']) != binding:
                        raise ValueError('Staged export changed while it was copied')
                    staged.append((task, binding))
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    reject(task, 'Could not stage the current immutable Harbor output: ' + str(exc))
            (batch_dir / 'batch_manifest.json').write_text(json.dumps(batch, indent=2, default=str))
            controls = {'per_task': {}, 'complete': False}
            if staged:
                controls = run_controls(staging, jobs, concurrency=self.config['harbor']['concurrency'],
                    event_callback=lambda event: self.audit.emit(event.get('type', 'harbor.event'),
                        **{key: value for key, value in event.items() if key != 'type'}))
                actual_summary = jobs / 'control_summary.json'
                # run_controls writes this path; a returned in-memory mapping
                # alone is not represented as a persisted real summary.
                if actual_summary.is_file():
                    batch['summary_path'] = str(actual_summary)
                else:
                    batch['errors'].append({'reason': 'Harbor did not persist its control summary'})
            for task, binding in staged:
                name = binding['task_name']
                proof = controls.get('per_task', {}).get(name, {})
                good = matched_controls(proof, task_name=name) and batch['summary_path'] is not None
                try:
                    if inspect_export(export_root / task['id']) != binding or inspect_export(staging / task['id']) != binding:
                        raise ValueError('Export changed while controls were executing')
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    good = False
                    batch['errors'].append({'task_id': task['id'], 'reason': str(exc)})
                if proof:
                    cumulative['per_task'][name] = proof
                    cumulative['export_bindings'][name] = binding
                if good:
                    self.audit.task(task['id'], status='qualified', node='complete', error=None,
                        harbor_controls=proof, harbor_export_binding=binding, harbor_summary_path=batch['summary_path'])
                    self.audit.emit('task.qualified', task_id=task['id'], mode=task['mode'],
                        revision=task.get('revision', 0), harbor_batch_id=batch_id,
                        summary_path=batch['summary_path'])
                else:
                    reject(task, 'Actual Harbor oracle/nop validation failed or lacks current-version evidence', proof)
            batch['complete'] = bool(staged) and not batch['errors'] and controls.get('complete') is True
        except Exception as exc:
            batch['errors'].append({'reason': str(exc)})
            for task, _ in staged:
                current = next(row for row in self.audit.snapshot()['tasks'] if row['id'] == task['id'])
                if current.get('status') in {'ready', 'qualified'}:
                    reject(task, 'Harbor control batch failed: ' + str(exc))
        finally:
            duration_ms = round((time.monotonic() - started) * 1000)
            status = 'completed' if batch['complete'] else 'failed'
            batch.update(status=status, duration_ms=duration_ms, finished_at=utcnow())
            cumulative['batches'].append(batch)
            if batch['summary_path']:
                cumulative['summary_paths'] = sorted(set(cumulative['summary_paths']) | {batch['summary_path']})
            cumulative.update(schema_version=2, latest_batch_id=batch_id, complete=batch['complete'])
            summary_file.write_text(json.dumps(cumulative, indent=2, default=str))
            (batch_dir / 'batch_manifest.json').write_text(json.dumps(batch, indent=2, default=str))
            self.audit.update_record('nodes', node_record, {'status': status, 'duration_ms': duration_ms,
                'summary_path': batch['summary_path'], 'error': batch['errors'] or None})
            self.audit.emit('node.' + status, node='harbor_validation', batch_id=batch_id,
                duration_ms=duration_ms, summary_path=batch['summary_path'])

    def run(self):
        # Existing ready exports must be checked before provisional credit can
        # suppress construction in a continuation.
        if self.config['run'].get('continuation_id'):
            self._validate_exports()
        seeds = self.load_seeds()
        self.audit.update_run(status='constructing', scheduler=self.scheduler)
        self.audit.emit('run.construction_started', sources=len(seeds), targets=self.targets,
                        scheduler=self.scheduler)
        repair_manifest = self.config['run'].get('external_repair_manifest')
        if repair_manifest:
            specifications = json.loads(Path(repair_manifest).read_text())
            if specifications:
                workers = min(len(specifications), int(self.config['run']['max_parallel_sources']))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(self.process_external_repair, item) for item in specifications]
                    for future in futures:
                        future.result()
            self._validate_exports()
        self.audit.update_run(status='constructing')
        attempted_jobs = 0
        if self.scheduler == 'rolling':
            while True:
                self.audit.update_run(status='constructing')
                attempted_jobs += self._construct_rolling(seeds)
                self._validate_exports()
                tasks = self.audit.snapshot()['tasks']
                qualified = {mode: sum(task.get('mode') == mode and task['status'] == 'qualified'
                                       for task in tasks) for mode in self.targets}
                if all(qualified[mode] >= target for mode, target in self.targets.items()):
                    break
                deficits = {mode: max(0, target - qualified[mode]) for mode, target in self.targets.items()}
                if not self._eligible_source_jobs(seeds):
                    self.audit.emit('scheduler.exhausted', deficits=deficits, pending=0)
                    break
                self.audit.emit('scheduler.refill_after_harbor', deficits=deficits)
        else:
            attempted_jobs = self._construct_batch(seeds)
            self._validate_exports()
            # Legacy source batches retain the full first-pass/variant barriers.
            for variant in range(1, self.config['run'].get('max_candidates_per_seed', 3)):
                if self.goal_ready():
                    break
                candidates = self.variant_candidates(seeds, variant)
                if not candidates:
                    break
                self.audit.update_run(status='constructing', variant_round=variant)
                attempted_jobs += self._construct_batch(candidates)
                self._validate_exports()
        tasks = self.audit.snapshot()['tasks']
        unique_sources = {task['source_id'] for task in tasks if task.get('source_id')}
        complete = all(sum(task.get('mode') == mode and task['status'] == 'qualified' for task in tasks) >= count
                       for mode, count in self.targets.items())
        self.audit.update_run(status='completed' if complete else 'shortfall',
                              sources_attempted=len(unique_sources), source_variant_jobs=attempted_jobs)
        self.audit.emit('run.finished', complete=complete, sources_attempted=len(unique_sources), source_variant_jobs=attempted_jobs)
        self.audit.export()
        return complete
