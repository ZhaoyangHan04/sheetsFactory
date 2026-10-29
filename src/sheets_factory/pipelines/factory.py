from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import json
from pathlib import Path
import re
import shutil
import threading

from ..core.node import TaskContext, TaskRejected
from ..core.pipeline import BasePipeline
from ..checkers import DiagnosisRunner
from ..checkers.router import route_issues
from ..evaluation.harbor import run_controls
from ..resume import candidate_task_id, restore_target_claims
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
        self.lock = threading.RLock()
        self.active = {mode: 0 for mode in self.targets}
        self.target_claims = (restore_target_claims(config['run_dir'], read_run(config['run_dir']))
                              if config['run'].get('continuation_id') else {})
        self.route_catalog = DiagnosisRunner(config['project_root']).catalog

    def counts(self):
        tasks = self.audit.snapshot()['tasks']
        return {mode: sum(task.get('mode') == mode and task.get('status') in {'ready', 'qualified'} for task in tasks)
                for mode in self.targets}

    def reserve(self, mode):
        with self.lock:
            if self.counts()[mode] + self.active[mode] >= self.targets[mode]:
                return False
            self.active[mode] += 1
            return True

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
        if any(task['id'] == task_id for task in self.audit.snapshot()['tasks']):
            self.audit.emit('task.skipped_existing', task_id=task_id, mode=mode,
                            reason='Continuation preserves existing terminal/ready tasks and all budgets')
            return
        if not self.reserve(mode):
            return
        context = self._context(seed, mode)
        try:
            self.run_phase(context, 'preparation')
            self._execute_context(context)
        except Exception as exc:
            self.audit.task(context.task_id, status='rejected', error=str(exc)[:2400], node='rejected')
            self.audit.emit('task.rejected', task_id=context.task_id, mode=mode, reason=str(exc)[:2400])
        finally:
            with self.lock:
                self.active[mode] -= 1
            self.audit.export()

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
                phase = 'infrastructure_retry'
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
            with self.lock:
                self.active[mode] -= 1
            self.audit.export()

    def process_source(self, seed):
        for mode in self.targets:
            if mode in seed.get('modes', list(self.targets)):
                self.process_task(seed, mode)

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

    def _validate_exports(self):
        export_root = Path(self.config['run_dir']) / 'SpreadsheetEval'
        if not export_root.exists() or not any(export_root.iterdir()):
            return
        self.audit.update_run(status='harbor_validation')
        controls = run_controls(export_root, Path(self.config['run_dir']) / 'harbor_jobs',
            concurrency=self.config['harbor']['concurrency'],
            event_callback=lambda event: self.audit.emit(event.get('type', 'harbor.event'),
                **{key: value for key, value in event.items() if key != 'type'}))
        (Path(self.config['run_dir']) / 'harbor_controls.json').write_text(json.dumps(controls, indent=2, default=str))
        for task in self.audit.snapshot()['tasks']:
            if task['status'] not in {'ready', 'qualified'}:
                continue
            per_task = controls.get('per_task', {}).get('sheetsfactory/' + task['id'], {})
            good = (per_task.get('oracle', {}).get('matched') is True and per_task.get('nop', {}).get('matched') is True)
            if good:
                self.audit.task(task['id'], status='qualified', node='complete', harbor_controls=per_task)
                self.audit.emit('task.qualified', task_id=task['id'], mode=task['mode'])
            else:
                self.audit.task(task['id'], status='rejected', node='harbor_failed',
                                error='Actual Harbor oracle/nop validation failed', harbor_controls=per_task)
                failed = export_root / task['id']
                if failed.exists():
                    quarantine = Path(self.config['run_dir']) / 'rejected_exports' / task['id']
                    quarantine.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(failed), quarantine)

    def run(self):
        seeds = self.load_seeds()
        self.audit.update_run(status='constructing')
        self.audit.emit('run.construction_started', sources=len(seeds), targets=self.targets)
        repair_manifest = self.config['run'].get('external_repair_manifest')
        if repair_manifest:
            for specification in json.loads(Path(repair_manifest).read_text()):
                self.process_external_repair(specification)
            self._validate_exports()
        attempted_jobs = self._construct_batch(seeds)
        self._validate_exports()
        # Variants are fallback work after the first pass, not blind duplicates.
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
