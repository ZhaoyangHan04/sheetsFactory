from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import uuid
import webbrowser
import subprocess
import os

import yaml

from .core.audit import AuditStore
from .dashboard import DashboardServer
from .llm import CodexCLI
from .workbook import LibreOfficeEngine
from .pipelines import FactoryPipeline
from .resume import ProducerLease, ResumeError, prepare_resume


def main(argv=None):
    parser = argparse.ArgumentParser(description='Construct auditable spreadsheet tasks and start the live dashboard.')
    parser.add_argument('--config', help='New-run configuration or an explicit continuation amendment')
    parser.add_argument('--resume', help='Continue a terminal run directory or run ID without resetting tasks or budgets')
    parser.add_argument('--extra-manifest', help='Hash-verified additional seed manifest for --resume')
    parser.add_argument('--repair-task', action='append', default=[], help='Explicitly repair a terminal task with confirmed external issues; repeatable, requires --resume')
    parser.add_argument('--repair-review', action='append', default=[], help='External review JSON for --repair-task; otherwise use each task external_quality_review.json')
    parser.add_argument('--resume-reason', default='Continue the terminal run with additional source candidates')
    parser.add_argument('--count', type=int)
    parser.add_argument('--seeds', help='Directory or .xls/.xlsx file to use instead of the manifest selection')
    parser.add_argument('--max-sources', type=int)
    parser.add_argument('--max-candidates-per-seed', type=int)
    parser.add_argument('--source-filter')
    parser.add_argument('--port', type=int)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--exit-on-finish', action='store_true')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    if args.extra_manifest and not args.resume:
        parser.error('--extra-manifest is only valid with --resume')
    if (args.repair_task or args.repair_review) and not args.resume:
        parser.error('--repair-task/--repair-review are only valid with --resume')
    if args.repair_review and not args.repair_task:
        parser.error('--repair-review requires at least one explicit --repair-task')
    if args.resume and (args.count is not None or args.seeds):
        parser.error('Continuation preserves quotas and source identity; use --extra-manifest instead of --count/--seeds')
    if args.max_sources is not None and args.max_sources <= 0:
        parser.error('--max-sources must be positive')
    if args.max_candidates_per_seed is not None and args.max_candidates_per_seed <= 0:
        parser.error('--max-candidates-per-seed must be positive')
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, text=True, capture_output=True).stdout.strip()
    session = None
    if args.resume:
        candidate = Path(args.resume)
        run_dir = (candidate if candidate.is_dir() else root / 'outputs/runs' / candidate).resolve()
        patch = {}
        if args.config:
            path = Path(args.config)
            patch = yaml.safe_load((path if path.is_absolute() else root / path).read_text())
        patch.setdefault('run', {})
        if args.max_sources is not None:
            patch['run']['max_sources'] = args.max_sources
        if args.max_candidates_per_seed is not None:
            patch['run']['max_candidates_per_seed'] = args.max_candidates_per_seed
        if args.source_filter:
            patch['run']['source_filter'] = args.source_filter
        try:
            session = prepare_resume(run_dir, config_patch=patch, extra_manifest=args.extra_manifest,
                                     current_code_revision=revision, reason=args.resume_reason,
                                     repair_tasks=args.repair_task, review_files=args.repair_review)
        except (ResumeError, OSError, ValueError) as exc:
            parser.error(str(exc))
        config, audit = session.config, session.audit
        run_id = audit.run['id']
        previous_wall = audit.run.get('previous_wall_seconds')
        lease = session.lease
    else:
        path = Path(args.config or 'config/pipelines/quality40.yaml')
        config = yaml.safe_load((path if path.is_absolute() else root / path).read_text())
        llm_file = root / 'config/llm.yaml'
        llm_settings = yaml.safe_load(llm_file.read_text()) if llm_file.exists() else {}
        agent_file = root / 'config/agents.yaml'
        agent_settings = yaml.safe_load(agent_file.read_text()) if agent_file.exists() else {}
        config['agents'] = {**llm_settings, 'roles': agent_settings.get('roles', {}), **config.get('agents', {})}
        config['prompt_overrides'] = {**agent_settings.get('prompts', {}), **config.get('prompt_overrides', {})}
        if args.count is not None:
            if args.count < 2:
                parser.error('--count must be at least 2 to include both task modes')
            config['run']['targets'] = {'financial_modeling': (args.count + 1) // 2, 'debugging': args.count // 2}
        if args.max_sources is not None:
            config['run']['max_sources'] = args.max_sources
        if args.max_candidates_per_seed is not None:
            config['run']['max_candidates_per_seed'] = args.max_candidates_per_seed
        if args.source_filter:
            config['run']['source_filter'] = args.source_filter
        if args.seeds:
            config['run']['seed_path'] = str(Path(args.seeds).resolve())
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
        run_dir = root / 'outputs/runs' / run_id
        run_dir.mkdir(parents=True)
        config.update(project_root=str(root), run_dir=str(run_dir))
        (run_dir / 'resolved_config.yaml').write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
        lease = ProducerLease(run_dir).acquire()
        audit = AuditStore(run_dir, {'id': run_id, 'target_count': sum(config['run']['targets'].values()),
            'financial_target': config['run']['targets']['financial_modeling'],
            'debugging_target': config['run']['targets']['debugging'], 'difficulty_status': (
                'deferred' if config.get('diagnosis', {}).get('difficulty_deferred', True) else 'pending'),
            'model': config['agents']['model'], 'reasoning_effort': config['agents']['reasoning_effort']})
        audit.update_run(code_revision=revision, producer_pid=os.getpid(), producer_active=True,
                         code_history=[{'code_revision': revision, 'started_at': audit.run['started_at'], 'phase': 'initial'}])
        previous_wall = 0
    try:
        server = DashboardServer(audit.snapshot, audit.events, host=config['dashboard']['host'],
                                 port=args.port if args.port is not None else config['dashboard']['port'])
        url = server.start()
        audit.update_run(dashboard_url=url)
        (run_dir / 'dashboard.json').write_text(json.dumps({'url': url, 'run_id': run_id}))
        (root / 'outputs').mkdir(parents=True, exist_ok=True)
        (root / 'outputs/latest_run.json').write_text(json.dumps({'run_id': run_id, 'directory': str(run_dir), 'url': url}))
    except BaseException as exc:
        audit.update_run(status='failed', error=str(exc), producer_active=False, wall_seconds=previous_wall)
        if session:
            session.close()
        else:
            lease.release()
        raise
    print(f'Run: {run_id}\nDashboard: {url}\nAudit: {run_dir}', flush=True)
    if not args.headless:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    started = time.monotonic()
    audit.update_run(execution_phase_started_at=datetime.now(timezone.utc).isoformat())
    code = 1
    try:
        llm = CodexCLI(root, run_dir, audit, config['agents'])
        llm._credentials()
        engine = LibreOfficeEngine(root, config['engine']['image'], config['engine']['timeout_seconds'])
        audit.emit('run.preflight', engine=engine.metadata(), model=llm.model, reasoning_effort=llm.reasoning)
        code = 0 if FactoryPipeline(config, audit, llm, engine).run() else 2
    except KeyboardInterrupt:
        audit.update_run(status='cancelled'); code = 130
    except Exception as exc:
        audit.update_run(status='failed', error=str(exc)); audit.emit('run.failed', error=str(exc))
        print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr, flush=True)
    finally:
        phase_wall = round(time.monotonic() - started, 3)
        cumulative_wall = round(previous_wall + phase_wall, 3) if isinstance(previous_wall, (int, float)) else None
        audit.update_run(wall_seconds=cumulative_wall, last_phase_wall_seconds=phase_wall,
                         finished_at=datetime.now(timezone.utc).isoformat(), exit_code=code, producer_active=False)
        if session:
            session.close()
        else:
            lease.release()
        report = audit.export()
        print(json.dumps({'status': report['run']['status'], 'metrics': report['metrics']}, ensure_ascii=False), flush=True)
    if not args.exit_on_finish:
        print('Dashboard remains available. Press Ctrl+C to close.', flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    server.stop()
    return code


if __name__ == '__main__':
    raise SystemExit(main())
