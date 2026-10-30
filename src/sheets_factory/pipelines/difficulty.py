"""Bounded, evidence-driven difficulty iteration over unchanged quality gates.

Every generation/evaluation is a new immutable child run. Development and
confirmation always execute their own model attempts. An infrastructure failure
never supplies a zero and does not silently cause a second Pass@1 attempt.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import threading
import time
from types import SimpleNamespace
from uuid import uuid4
import webbrowser

import yaml
from openpyxl import load_workbook

from ..core.audit import AuditStore, utcnow
from ..dashboard import DashboardServer
from ..dashboard.read_only import ReadOnlyAuditView, HistoricalDashboardServer
from ..llm import CodexCLI
from ..resume import ProducerLease
from ..workbook import LibreOfficeEngine
from .factory import FactoryPipeline


MODES = ('financial_modeling', 'debugging')


class DifficultyError(ValueError):
    pass


class _BudgetExhausted(DifficultyError):
    pass


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')
    temporary.replace(path)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _script(root, name):
    path = Path(root) / 'scripts' / (name + '.py')
    spec = importlib.util.spec_from_file_location('difficulty_' + name, path)
    if spec is None or spec.loader is None:
        raise DifficultyError('Required local script is unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _redact(value, secrets=()):
    if isinstance(value, dict):
        return {str(key): '[REDACTED]' if re.search(r'api.?key|authorization|password|secret', str(key), re.I)
                else _redact(item, secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, '[REDACTED]')
        return re.sub(r'\bsk-[A-Za-z0-9_-]{16,}', '[REDACTED]', value)
    return value


def semantic_task_fingerprint(export):
    """Ignore XLSX container timestamps, retain actual public/goal content."""
    export = Path(export)
    digest = hashlib.sha256()
    instruction = re.sub(r'\s+', ' ', (export / 'instruction.md').read_text()).strip()
    digest.update(instruction.encode())
    for relative, cached in (('environment/input.xlsx', False), ('tests/reference.xlsx', True)):
        book = load_workbook(export / relative, data_only=cached, keep_links=False)
        try:
            content = []
            for sheet in book.worksheets:
                cells = [(cell.coordinate, type(cell.value).__name__, cell.value,
                          cell.number_format if not cached else None)
                         for cell in sorted(sheet._cells.values(), key=lambda cell: (cell.row, cell.column))
                         if cell.value is not None]
                content.append({'sheet': sheet.title, 'state': sheet.sheet_state, 'cells': cells})
            digest.update(json.dumps(content, ensure_ascii=False, default=str, separators=(',', ':')).encode())
        finally:
            book.close()
    return digest.hexdigest()


def feedback_from_evaluation(quality_dir, release_manifest, evaluation, *, secrets=()):
    """Return observations and source pointers, never an invented failure cause."""
    quality_dir = Path(quality_dir)
    released = json.loads(Path(release_manifest).read_text())
    records = {task['task_id']: task for task in released['tasks']}
    findings = []
    for attempt in evaluation.get('attempts', []):
        item = records.get(attempt.get('task_id'))
        if item is None:
            continue
        private = (quality_dir / 'tasks' / item['task_id'] / 'revisions' /
                   f"{int(item['revision']):03d}" / 'private')
        plan_file = private / 'plan.json'
        plan = json.loads(plan_file.read_text()) if plan_file.is_file() else {}
        result_file = Path(attempt['result_file']) if attempt.get('result_file') else None
        trace = result_file.parent / 'agent/trajectory.json' if result_file else None
        evidence, excerpts, tool_count = [], [], None
        if plan_file.is_file():
            evidence.append({'path': str(plan_file), 'sha256': _sha(plan_file), 'kind': 'final_construction_plan'})
        if trace and trace.is_file():
            evidence.append({'path': str(trace), 'sha256': _sha(trace), 'kind': 'actual_agent_trajectory'})
            try:
                document = json.loads(trace.read_text())
                steps = document.get('steps', [])
                tool_count = sum(len(step.get('tool_calls') or []) for step in steps if isinstance(step, dict))
                for step in steps:
                    if not isinstance(step, dict):
                        continue
                    text = json.dumps({key: step[key] for key in ('source', 'message', 'tool_calls') if key in step},
                                      ensure_ascii=False)
                    if text and len(excerpts) < 10:
                        excerpts.append(text[:1600])
            except (OSError, ValueError, TypeError):
                evidence[-1]['parsing_status'] = 'unavailable'
        if result_file and result_file.is_file():
            evidence.append({'path': str(result_file), 'sha256': _sha(result_file), 'kind': 'actual_harbor_result'})
        cells = sorted({str(edit.get('sheet')) + '!' + str(edit.get('cell'))
                        for edit in plan.get('edits', []) if isinstance(edit, dict)})
        observations = []
        joined = '\n'.join(excerpts)
        if re.search(r'Translator|openpyxl\.formula\.translate|copy.*formula|formula.*cop', joined, re.I):
            observations.append({'kind': 'formula_translation_observed', 'certainty': 'observed',
                                 'basis': 'Actual trajectory excerpt contains formula copying/translation code.'})
        if attempt.get('reward') == 1 and tool_count is not None and tool_count <= 1:
            observations.append({'kind': 'success_with_at_most_one_tool_call', 'certainty': 'observed',
                                 'tool_call_count': tool_count})
        findings.append({'task_id': item['task_id'], 'mode': item['mode'], 'source_id': item['source_id'],
            'revision': item['revision'], 'revision_hash': item['revision_hash'],
            'task_checksum': attempt.get('task_checksum'), 'status': attempt.get('status'),
            'reward': attempt.get('reward'), 'title': plan.get('title'),
            'target_count': len(cells), 'target_cells_sample': cells[:80],
            'target_cells_sha256': hashlib.sha256(json.dumps(cells).encode()).hexdigest(),
            'mask_ranges': plan.get('mask_ranges', []), 'observations': observations,
            'trajectory_excerpts': excerpts, 'evidence': evidence})
    return _redact({'schema_version': 1, 'phase': evaluation.get('phase'),
        'score': evaluation.get('score'), 'tasks': findings,
        'interpretation_policy': 'Observations are evidence, not proof that task size predicts difficulty.',
        'generation_requirements': [
            'Preserve every necessary assumption, unit, period, output contract and independent recovery witness.',
            'Use supported business rules with interacting dependencies; do not merely add copied formula cells.',
            'Explain why the observed shortcut no longer solves the new module and provide public rules for its replacement.',
            'Never add ambiguity, hidden assumptions, leakage, native business errors or gratuitous formatting requirements.',
            'A previously confirmed task checksum must change before it can receive another confirmation attempt.']}, secrets)


class DifficultyPipeline:
    """One-click orchestration. Override stage methods only in offline tests."""

    def __init__(self, config, seed_manifest, output_dir, *, project_root=None, headless=False):
        self.root = Path(project_root or Path(__file__).resolve().parents[3]).resolve()
        self.config = deepcopy(config)
        self.settings = self.config.get('difficulty', {})
        self.per_mode = int(self.settings.get('per_mode', 10))
        self.max_rounds = int(self.settings.get('max_rounds', 4))
        if self.per_mode < 10 or self.max_rounds < 1:
            raise DifficultyError('Difficulty iteration requires at least ten tasks per mode and a positive max_rounds')
        if self.config['run']['targets'] != {mode: self.per_mode for mode in MODES}:
            raise DifficultyError('Quality targets must equal difficulty.per_mode in each mode')
        self.seed_manifest = Path(seed_manifest).resolve()
        self.directory = Path(output_dir).resolve()
        if self.directory.exists():
            raise DifficultyError('Output already exists; completed attempts and old budgets are never overwritten')
        if self.settings.get('timeout_seconds', 1800) != 1800:
            raise DifficultyError('The difficulty gate uses a full 1800-second per-task budget')
        if any(self.settings.get(key) is not None and float(self.settings[key]) <= 0
               for key in ('max_total_tokens', 'max_wall_seconds')):
            raise DifficultyError('Optional stage-boundary budgets must be positive')
        if not 0 <= int(self.settings.get('max_infrastructure_retries', 2)) <= 2:
            raise DifficultyError('Infrastructure recovery is limited to zero, one or two proven infrastructure retries')
        self.headless = headless
        self.directory.mkdir(parents=True)
        try:
            self.code_revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=self.root,
                capture_output=True, text=True, check=False).stdout.strip() or None
        except OSError:
            self.code_revision = None
        self.audit = AuditStore(self.directory, {'id': self.directory.name, 'kind': 'difficulty_iteration',
            'target_count': 2 * self.per_mode, 'financial_target': self.per_mode, 'debugging_target': self.per_mode,
            'status': 'initializing', 'generation_model': 'gpt-6-sol', 'generation_reasoning_effort': 'high',
            'model': 'gpt-6-sol', 'reasoning_effort': 'high', 'code_revision': self.code_revision,
            'gate_model': 'gpt-6.1-sol', 'gate_reasoning_effort': 'xhigh',
            'quality_note': '本面板合格数仅统计最终确认通过题集；各轮质量产量见子面板。'})
        self.manifest = {'schema_version': 1, 'status': 'initializing', 'started_at': self.audit.run['started_at'],
            'seed_manifest': {'path': str(self.seed_manifest), 'sha256': _sha(self.seed_manifest)},
            'config_sha256': hashlib.sha256(yaml.safe_dump(self.config, sort_keys=True).encode()).hexdigest(),
            'code_revision': self.code_revision, 'pipeline_sha256': _sha(Path(__file__)),
            'budget_policy': 'Round limit is exact. Token/wall caps are checked between complete stages; in-flight work is retained.',
            'max_rounds': self.max_rounds, 'rounds': [], 'children': [], 'final_publication': None}
        self.lock = threading.RLock()
        self._sync_lock = threading.RLock()
        self._children = []
        self._servers = []
        self._seen_calls = set()
        self._watch_stop = threading.Event()
        self._watcher = None
        self.started = time.monotonic()
        self.secrets = []
        self.seen_modules = {}

    def _save(self):
        with self.lock:
            _write(self.directory / 'difficulty_manifest.json', self.manifest)
            self.audit.update_run(child_runs=deepcopy(self.manifest['children']))

    def _child(self, directory, kind, number):
        record = {'directory': str(directory), 'kind': kind, 'round': number, 'status': 'running', 'url': None}
        with self.lock:
            self._children.append(record)
            self.manifest['children'].append(record)
        self._save()
        return record

    def _sync_children(self):
        with self._sync_lock:
            self._sync_child_records()

    def _sync_child_records(self):
        with self.lock:
            children = list(self._children)
        for child in children:
            directory = Path(child['directory'])
            if not (directory / 'run.sqlite').is_file():
                continue
            view = ReadOnlyAuditView(directory)
            if not child.get('url'):
                panel = HistoricalDashboardServer(view.snapshot, view.events, port=0)
                child['url'] = panel.start()
                self._servers.append(panel)
                self.audit.emit('difficulty.child_panel', message=f"第{child['round']}轮 {child['kind']}: {child['url']}",
                    child_kind=child['kind'], directory=child['directory'], round=child['round'], url=child['url'])
                self._save()
            try:
                snapshot = view.snapshot()
            except sqlite3.Error:
                continue  # A just-created child database can precede schema commit.
            child['status'] = snapshot['run'].get('status')
            for index, call in enumerate(snapshot.get('llm_calls', [])):
                if call.get('projected_from_events'):
                    continue
                identity = child['directory'] + ':' + str(call.get('call_id') or ('row-' + str(index)))
                with self.lock:
                    if identity in self._seen_calls:
                        continue
                    self._seen_calls.add(identity)
                self.audit.record('calls', {**call, 'call_id': identity, 'source_call_id': call.get('call_id'),
                    'child_directory': child['directory'], 'round': child['round'], 'stage': child['kind']})

    def _watch(self):
        while not self._watch_stop.wait(1):
            try:
                self._sync_children()
            except (OSError, ValueError, sqlite3.Error) as exc:
                self.audit.emit('difficulty.viewer_unavailable', error_type=type(exc).__name__)

    def snapshot(self):
        result = self.audit.snapshot()
        result['run']['child_runs'] = deepcopy(self.manifest['children'])
        quality_tasks = []
        with self.lock:
            children = list(self._children)
        for child in children:
            try:
                current = ReadOnlyAuditView(Path(child['directory'])).snapshot()
            except (OSError, ValueError, sqlite3.Error):
                continue
            if child['kind'] == 'quality':
                quality_tasks.extend(current.get('tasks', []))
            for call in current.get('llm_calls', []):
                if call.get('projected_from_events'):
                    result['llm_calls'].append({**call, 'call_id': child['directory'] + ':' + str(call.get('call_id'))})
        sources = {task['source_id'] for task in quality_tasks if task.get('source_id')}
        productive = {task['source_id'] for task in result['tasks'] if task.get('status') == 'qualified' and task.get('source_id')}
        metrics = result['metrics']
        metrics.update(candidates=len(quality_tasks), unique_seeds=len(sources),
            rejected=sum(task.get('status') == 'rejected' for task in quality_tasks),
            productive_seeds=len(productive),
            candidate_conversion=metrics['qualified'] / len(quality_tasks) if quality_tasks else None,
            source_conversion=len(productive) / len(sources) if sources else None,
            llm_calls=len(result['llm_calls']),
            unknown_usage_calls=sum(call.get('input_tokens') is None for call in result['llm_calls']))
        return result

    def _dashboard(self):
        server = DashboardServer(self.snapshot, self.audit.events,
            host=self.config.get('dashboard', {}).get('host', '127.0.0.1'),
            port=int(self.settings.get('dashboard_port', 0)))
        # Extend this instance only. Existing dashboard assets remain untouched.
        panel = b'<section class="panel tabs-panel"><div class="panelhead"><h2>\xe5\x90\x84\xe8\xbd\xae\xe5\xad\x90\xe8\xbf\x90\xe8\xa1\x8c</h2></div><div id="difficulty-children" class="sidebody"></div></section>'
        script = b'''<script>async function difficultyLinks(){try{const s=await(await fetch('/api/snapshot')).json();const p=document.getElementById('difficulty-children');p.replaceChildren();for(const c of s.run.child_runs||[]){const d=document.createElement('div');d.style.marginBottom='10px';const a=document.createElement('a');const u=new URL(c.url||'',location.href);if(['127.0.0.1','localhost','[::1]'].includes(u.hostname)){a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';}a.textContent='Round '+c.round+' / '+c.kind+' / '+c.status;d.append(a);p.append(d);}}catch(e){}}setInterval(difficultyLinks,2500);difficultyLinks();</script>'''
        server._html = server._html.replace(b'</main>', panel + b'</main>').replace(b'</body>', script + b'</body>')
        url = server.start()
        self._servers.append(server)
        self.audit.update_run(dashboard_url=url)
        self.manifest['dashboard_url'] = url
        self._save()
        print(json.dumps({'difficulty_directory': str(self.directory), 'dashboard_url': url}), flush=True)
        if not self.headless:
            try:
                webbrowser.open(url)
            except Exception:
                self.audit.emit('difficulty.browser_unavailable', dashboard_url=url)

    def _budget(self):
        self._sync_children()
        metrics = self.audit.snapshot()['metrics']
        limit = self.settings.get('max_total_tokens')
        if limit is not None and metrics['total_tokens'] >= int(limit):
            raise _BudgetExhausted('Known recorded token budget exhausted between stages')
        wall = self.settings.get('max_wall_seconds')
        if wall is not None and time.monotonic() - self.started >= float(wall):
            raise _BudgetExhausted('Wall-clock budget exhausted between stages')

    @contextmanager
    def _stage(self, name, number):
        self._budget()
        self.audit.update_run(status='running', current_phase=f'第{number}轮 {name}')
        started = time.monotonic()
        before = self.audit.snapshot()['metrics']['total_tokens']
        node = self.audit.record('nodes', {'node': name, 'label': f'第{number}轮 {name}',
            'round': number, 'status': 'running', 'started_at': utcnow()})
        self.audit.emit('difficulty.stage_started', round=number, stage=name, node=name,
                        message=f'第{number}轮 {name}开始')
        status = 'completed'
        try:
            yield
        except BaseException:
            status = 'failed'
            raise
        finally:
            self._sync_children()
            self.audit.update_record('nodes', node, {'status': status,
                'duration_ms': round((time.monotonic() - started) * 1000),
                'total_tokens': self.audit.snapshot()['metrics']['total_tokens'] - before})
            self.audit.emit('difficulty.stage_' + status, round=number, stage=name,
                            message=f'第{number}轮 {name}: {status}')

    def _preflight(self):
        agents = self.config['agents']
        if agents.get('model') != 'gpt-6-sol' or agents.get('reasoning_effort') != 'high':
            raise DifficultyError('Generation is fixed to gpt-6-sol/high')
        if any(role.get('model', 'gpt-6-sol') != 'gpt-6-sol' or role.get('reasoning_effort', 'high') != 'high'
               for role in agents.get('roles', {}).values()):
            raise DifficultyError('Generation role overrides must remain gpt-6-sol/high')
        backend = CodexCLI(self.root, self.directory, self.audit, agents)
        key, _ = backend._credentials()
        self.secrets = [key]
        if not Path(backend.binary).is_file():
            raise DifficultyError('Configured native Codex executable is unavailable')
        engine = LibreOfficeEngine(self.root, self.config['engine']['image'], self.config['engine']['timeout_seconds'])
        self.audit.emit('difficulty.preflight', engine=engine.metadata(), generation_model=agents['model'],
                        gate_model='gpt-6.1-sol', gate_reasoning_effort='xhigh')
        if any((self.root / name).exists() for name in ('SpreadsheetEval', 'benchmark_runtime', 'prepare_runtime.sh')):
            raise DifficultyError('Final publication destination already exists; choose a clean checkout')

    def _select_seeds(self):
        selector = _script(self.root, 'select_hard_seeds')
        evidence = self.settings.get('seed_evidence', ['data/manifests/finance_model_evidence.json'])
        paths = [self.root / path for path in evidence if (self.root / path).is_file()]
        registry = self.root / (self.config.get('native_risks', {}).get('registry_path') or 'data/manifests/native_risks.json')
        options = SimpleNamespace(inventory=[self.seed_manifest], evidence=paths,
            risk_registry=registry if registry.is_file() else None, existing_run=None,
            mode='both', used_policy='allow', require_business_evidence=bool(self.settings.get('require_business_evidence', False)),
            min_sheets=4, limit=int(self.config['run']['max_sources']), project_root=self.root,
            normalize_dir=self.directory / 'selection/normalized')
        ranked = selector.select(options)
        _write(self.directory / 'selection/ranking.json', ranked)
        originals = {selector.source_digest(row): row for row in selector.inventory_rows(json.loads(self.seed_manifest.read_text()))}
        selected, scores = {}, {}
        for mode, rows in ranked['rankings'].items():
            for row in rows:
                scores[row['source_sha256']] = max(scores.get(row['source_sha256'], 0), row['score'])
        for item in ranked['candidates']:
            source = item['source_sha256']
            if item.get('analysis_status') != 'profiled' or source not in scores:
                continue
            row = deepcopy(originals[source])
            file = Path(item['source_path'])
            if not file.is_file() or _sha(file) != source:
                continue
            finance = item.get('business_evidence') or {'assessment_status': 'unassessed',
                'reason': 'Structural potential only; planner and unchanged quality gates must assess actual business rules.'}
            selected[source] = {**row, 'sha256': source, 'local_path': str(file.resolve()),
                                'rank_score': scores[source], 'finance_evidence': finance}
        if not selected:
            raise DifficultyError('No hash-verified seeds meet structural prerequisites; no tasks were approved')
        return list(selected.values())

    def _round_seeds(self, seeds, number, seen_sources):
        ordered = sorted(seeds, key=lambda seed: (seen_sources.get(seed['sha256'], 0), -seed.get('rank_score', 0), seed['sha256']))
        maximum = int(self.config['run']['max_sources'])
        chosen = [{**seed, 'rank_score': seed.get('rank_score', 0) - 1000 * seen_sources.get(seed['sha256'], 0)}
                  for seed in ordered[:maximum]]
        path = self.directory / f'rounds/{number:03d}/seed_manifest.json'
        _write(path, {'selected': chosen, 'unique_workbooks_inspected': len(seeds),
            'download_url': 'verified-user-seed-manifest', 'archive_sha256': None})
        return path

    def _run_quality(self, config, directory, number):
        directory.mkdir(parents=True)
        audit = AuditStore(directory, {'id': directory.name + '-' + str(number), 'status': 'initializing',
            'target_count': 2 * self.per_mode, 'financial_target': self.per_mode, 'debugging_target': self.per_mode,
            'difficulty_status': 'pending', 'producer_active': True, 'code_revision': self.code_revision,
            'model': config['agents']['model'], 'reasoning_effort': config['agents']['reasoning_effort']})
        self._child(directory, 'quality', number)
        self._sync_children()  # A child panel exists before credentials/runtime preflight.
        config = deepcopy(config)
        config.update(project_root=str(self.root), run_dir=str(directory))
        (directory / 'resolved_config.yaml').write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
        lease = ProducerLease(directory).acquire()
        started = time.monotonic()
        try:
            llm = CodexCLI(self.root, directory, audit, config['agents'])
            llm._credentials()
            engine = LibreOfficeEngine(self.root, config['engine']['image'], config['engine']['timeout_seconds'])
            audit.emit('run.preflight', engine=engine.metadata(), model=llm.model, reasoning_effort=llm.reasoning)
            completed = FactoryPipeline(config, audit, llm, engine).run()
            return {'status': 'completed' if completed else 'shortfall', 'directory': str(directory),
                    'snapshot': audit.snapshot()}
        except BaseException as exc:
            audit.update_run(status='cancelled' if isinstance(exc, KeyboardInterrupt) else 'infrastructure_failed',
                             error_type=type(exc).__name__)
            raise
        finally:
            audit.update_run(producer_active=False, finished_at=utcnow(), wall_seconds=time.monotonic() - started)
            audit.export()
            lease.release()

    def _package(self, quality, directory):
        return _script(self.root, 'package_release').package_release(
            quality, self.per_mode, directory, project_root=self.root)

    def _evaluate(self, manifest, directory, phase, number, priors):
        from ..evaluation.frontier import run_evaluation
        self._child(directory, phase, number)
        return run_evaluation(manifest, directory, phase=phase, timeout_seconds=1800,
            concurrency=int(self.settings.get('evaluation_concurrency', 4)), project_root=self.root,
            backend_config=self._gate_backend(), prior_selections=priors, port=0)

    def _gate_backend(self):
        backend = deepcopy(self.config['agents'])
        backend.update(model='gpt-6.1-sol', reasoning_effort='xhigh',
            roles={'trace_agent': {'model': 'gpt-6.1-sol', 'reasoning_effort': 'xhigh', 'timeout_seconds': 1800}})
        return backend

    def _resume_infrastructure(self, directory):
        from ..evaluation.frontier import resume_infrastructure
        return resume_infrastructure(directory,
            max_infrastructure_retries=int(self.settings.get('max_infrastructure_retries', 2)),
            concurrency=int(self.settings.get('evaluation_concurrency', 4)), project_root=self.root,
            backend_config=self._gate_backend(), port=0)

    def _evaluate_with_recovery(self, manifest, directory, phase, number, priors):
        result = self._evaluate(manifest, directory, phase, number, priors)
        if result.get('failure_kind') == 'evaluation_interrupted':
            raise KeyboardInterrupt
        maximum = int(self.settings.get('max_infrastructure_retries', 2))
        for recovery in range(maximum):
            if result['status'] != 'infrastructure_failed':
                break
            self._budget()
            self.audit.emit('difficulty.infrastructure_recovery', round=number, phase=phase,
                recovery=recovery + 1,
                message='仅恢复已证基础设施故障；保留原选择及所有有效首次结果，最多两轮。')
            try:
                result = self._resume_infrastructure(directory)
            except ValueError as exc:
                # The frontier recovery validator rejects ambiguous timeouts,
                # altered receipts and exhausted/non-eligible retries. It must
                # not cause a fresh full-cohort evaluation here.
                result = {**result, 'orchestration_recovery_stop': type(exc).__name__}
                self.audit.emit('difficulty.infrastructure_not_resumed', round=number, phase=phase,
                                error_type=type(exc).__name__)
                break
            if result.get('failure_kind') == 'evaluation_interrupted':
                raise KeyboardInterrupt
        return result

    def _publish(self, release_dir, confirmation_dir):
        publisher = _script(self.root, 'publish_dataset')
        arguments = {'release_dir': release_dir, 'evaluation_manifest': confirmation_dir / 'evaluation_manifest.json',
                     'project_root': self.root}
        publisher.publish_dataset(**arguments, dry_run=True)
        return publisher.publish_dataset(**arguments)

    def _version_fingerprints(self, packaged):
        from dirhash import dirhash
        directories = [path for path in Path(packaged['task_directory']).iterdir() if path.is_dir()]
        return {'checksums': {dirhash(path, 'sha256') for path in directories},
                'semantic': {semantic_task_fingerprint(path) for path in directories}}

    def _feedback(self, number, quality, packaged, evaluation, reason):
        feedback = feedback_from_evaluation(quality, packaged['manifest'], evaluation, secrets=self.secrets)
        feedback.update(round=number, reason=reason)
        path = self.directory / f'rounds/{number:03d}/feedback.json'
        _write(path, feedback)
        compact = [{key: task.get(key) for key in ('task_id', 'mode', 'source_id', 'revision_hash',
                    'target_count', 'target_cells_sha256', 'observations', 'reward', 'evidence')}
                   for task in feedback['tasks']]
        return {'path': str(path), 'sha256': _sha(path), 'round': number, 'reason': reason,
                'tasks': compact, 'generation_requirements': feedback['generation_requirements'],
                'trace_policy': 'Read the hash-bound feedback file for task-specific trajectory excerpts; do not infer unsaved causes.'}

    def run(self):
        lease = ProducerLease(self.directory).acquire()
        feedback, priors, seen_sources, confirmed_checksums = deepcopy(self.config.get('generation_feedback', {})), [], {}, set()
        confirmed_semantics = set()
        status, reason = 'budget_exhausted', 'max_rounds exhausted without a qualifying confirmation'
        try:
            self._dashboard()
            self._watcher = threading.Thread(target=self._watch, daemon=True)
            self._watcher.start()
            self.manifest['status'] = 'running'
            self._save()
            with self._stage('preflight', 0):
                self._preflight()
            with self._stage('seed_selection', 0):
                seeds = self._select_seeds()
            for number in range(1, self.max_rounds + 1):
                self._budget()
                entry = {'round': number, 'status': 'running', 'started_at': utcnow()}
                self.manifest['rounds'].append(entry)
                config = deepcopy(self.config)
                config['generation_feedback'] = deepcopy(feedback)
                config['generation_feedback']['seen_modules'] = list(self.seen_modules.values())
                config['run']['seed_manifest'] = str(self._round_seeds(seeds, number, seen_sources))
                quality = self.directory / f'rounds/{number:03d}/quality'
                entry.update(quality_directory=str(quality), seed_manifest=config['run']['seed_manifest'])
                self._save()
                with self._stage('quality_generation', number):
                    outcome = self._run_quality(config, quality, number)
                for item in outcome.get('snapshot', {}).get('tasks', []):
                    if item.get('source_id'):
                        seen_sources[item['source_id']] = seen_sources.get(item['source_id'], 0) + 1
                    if item.get('target_fingerprint'):
                        key = (item.get('source_id'), item.get('mode'), item['target_fingerprint'])
                        self.seen_modules[key] = {name: item.get(name) for name in ('source_id', 'mode', 'target_fingerprint')}
                        self.seen_modules[key]['target_cells_sample'] = (item.get('targets') or [])[:12]
                if outcome['status'] != 'completed':
                    entry.update(status='quality_shortfall', finished_at=utcnow())
                    feedback = {'round': number, 'reason': 'quality_shortfall',
                        'requirements': 'Improve seed/module suitability without weakening any quality checks.',
                        'rejected': [{'task_id': item['id'], 'source_id': item.get('source_id'), 'error': item.get('error'),
                                      'issues': item.get('issues', [])}
                                     for item in outcome.get('snapshot', {}).get('tasks', []) if item.get('status') == 'rejected']}
                    feedback = _redact(feedback, self.secrets)
                    path = self.directory / f'rounds/{number:03d}/feedback.json'
                    _write(path, feedback)
                    feedback.update(path=str(path), sha256=_sha(path))
                    entry['feedback'] = {'path': str(path), 'sha256': _sha(path)}
                    self._save()
                    continue
                with self._stage('strict_packaging', number):
                    packaged = self._package(quality, self.directory / f'rounds/{number:03d}/release')
                    versions = self._version_fingerprints(packaged)
                entry['release'] = packaged
                checksums = versions['checksums']
                entry['version_fingerprints'] = {key: sorted(values) for key, values in versions.items()}
                if checksums & confirmed_checksums or versions['semantic'] & confirmed_semantics:
                    entry.update(status='unchanged_confirmation_versions', finished_at=utcnow())
                    feedback = {**feedback, 'reason': 'Previously confirmed task bytes recurred; generate a genuinely changed version.',
                                'forbidden_confirmation_checksums': sorted(confirmed_checksums),
                                'forbidden_confirmation_semantic_fingerprints': sorted(confirmed_semantics)}
                    self._save()
                    continue
                development = self.directory / f'rounds/{number:03d}/development'
                with self._stage('development_evaluation', number):
                    result = self._evaluate_with_recovery(packaged['manifest'], development, 'development', number, priors)
                entry['development'] = {'directory': str(development), 'status': result['status'], 'score': result['score']}
                priors.append(development / 'selection_manifest.json')
                if result['status'] != 'completed' or result['score'].get('overall_pass_at_1') is None:
                    entry['status'] = 'infrastructure_failed'
                    status, reason = 'infrastructure_failed', 'Development has unresolved infrastructure evidence; no score inferred'
                    break
                feedback = self._feedback(number, quality, packaged, result, 'development_result')
                entry['feedback'] = {'path': feedback['path'], 'sha256': feedback['sha256']}
                if result['score']['overall_pass_at_1'] > .2:
                    entry.update(status='development_too_easy', finished_at=utcnow())
                    self._save()
                    continue
                confirmation = self.directory / f'rounds/{number:03d}/confirmation'
                with self._stage('fresh_confirmation', number):
                    result = self._evaluate_with_recovery(packaged['manifest'], confirmation, 'confirmation', number, priors)
                entry['confirmation'] = {'directory': str(confirmation), 'status': result['status'], 'score': result['score']}
                priors.append(confirmation / 'selection_manifest.json')
                confirmed_checksums.update(checksums)
                confirmed_semantics.update(versions['semantic'])
                if result['status'] != 'completed' or result['score'].get('overall_pass_at_1') is None:
                    entry['status'] = 'infrastructure_failed'
                    status, reason = 'infrastructure_failed', 'Confirmation infrastructure unresolved; ordinary zero rewards are not infrastructure'
                    break
                if result.get('gate_passed') is not True or result['score']['overall_pass_at_1'] > .2:
                    feedback = self._feedback(number, quality, packaged, result, 'confirmation_too_easy')
                    entry.update(status='confirmation_too_easy', feedback={'path': feedback['path'], 'sha256': feedback['sha256']},
                                 finished_at=utcnow())
                    self._save()
                    continue
                with self._stage('publication', number):
                    publication = self._publish(packaged['release_directory'], confirmation)
                entry.update(status='published', finished_at=utcnow())
                self.manifest['final_publication'] = publication
                for item in publication['manifest']['tasks']:
                    self.audit.task(item['task_id'], mode=item['mode'], source_id=item['source_id'],
                                    revision=item['revision'], status='qualified')
                status, reason = 'completed', 'Fresh confirmation passed Overall Pass@1 <= 0.2; real dataset published'
                break
        except _BudgetExhausted as exc:
            status, reason = 'budget_exhausted', str(exc)
        except KeyboardInterrupt:
            status, reason = 'cancelled', 'Interrupted; all existing child evidence retained and no attempt replayed'
        except Exception as exc:
            phase = self.audit.run.get('current_phase')
            status = 'infrastructure_failed'
            reason = str(exc) if isinstance(exc, DifficultyError) else f'{type(exc).__name__} during {phase}; inspect retained child evidence'
            self.audit.emit('difficulty.failed', error_type=type(exc).__name__, stage=phase, reason=reason)
        finally:
            self._watch_stop.set()
            if self._watcher:
                self._watcher.join(timeout=3)
            self._sync_children()
            if self.manifest['rounds'] and self.manifest['rounds'][-1].get('status') == 'running':
                self.manifest['rounds'][-1].update(status=status, finished_at=utcnow(), stop_reason=reason)
            self.manifest.update(status=status, reason=reason, finished_at=utcnow(),
                wall_seconds=round(time.monotonic() - self.started, 3), usage=self.snapshot()['metrics'])
            self.audit.update_run(status=status, finished_at=self.manifest['finished_at'],
                                 wall_seconds=self.manifest['wall_seconds'], reason=reason, producer_active=False)
            self.audit.emit('difficulty.finished', status=status, reason=reason)
            self._save()
            self.audit.export()
            lease.release()
        return deepcopy(self.manifest)

    def close(self):
        self._watch_stop.set()
        for server in reversed(self._servers):
            server.stop()
