from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import uuid
import webbrowser

import yaml

from .core.audit import AuditStore
from .dashboard import DashboardServer
from .llm import CodexCLI
from .workbook import LibreOfficeEngine
from .pipelines import FactoryPipeline


def main(argv=None):
    parser = argparse.ArgumentParser(description='Construct auditable spreadsheet tasks and start the live dashboard.')
    parser.add_argument('--config', default='config/pipelines/quality40.yaml')
    parser.add_argument('--count', type=int)
    parser.add_argument('--max-sources', type=int)
    parser.add_argument('--source-filter')
    parser.add_argument('--port', type=int)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--exit-on-finish', action='store_true')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    path = Path(args.config)
    config = yaml.safe_load((path if path.is_absolute() else root / path).read_text())
    llm_file = root / 'config/llm.yaml'
    llm_settings = yaml.safe_load(llm_file.read_text()) if llm_file.exists() else {}
    agent_file = root / 'config/agents.yaml'
    agent_settings = yaml.safe_load(agent_file.read_text()) if agent_file.exists() else {}
    config['agents'] = {**llm_settings, 'roles': agent_settings.get('roles', {}), **config.get('agents', {})}
    config['prompt_overrides'] = agent_settings.get('prompts', {})
    if args.count is not None:
        if args.count < 2:
            parser.error('--count must be at least 2 to include both task modes')
        config['run']['targets'] = {'financial_modeling': (args.count + 1) // 2, 'debugging': args.count // 2}
    if args.max_sources:
        config['run']['max_sources'] = args.max_sources
    if args.source_filter:
        config['run']['source_filter'] = args.source_filter
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    run_dir = root / 'outputs/runs' / run_id
    run_dir.mkdir(parents=True)
    config.update(project_root=str(root), run_dir=str(run_dir))
    (run_dir / 'resolved_config.yaml').write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True))
    audit = AuditStore(run_dir, {'id': run_id, 'target_count': sum(config['run']['targets'].values()),
        'financial_target': config['run']['targets']['financial_modeling'],
        'debugging_target': config['run']['targets']['debugging'], 'difficulty_status': 'deferred',
        'model': config['agents']['model'], 'reasoning_effort': config['agents']['reasoning_effort']})
    server = DashboardServer(audit.snapshot, audit.events, host=config['dashboard']['host'],
                             port=args.port if args.port is not None else config['dashboard']['port'])
    url = server.start()
    audit.update_run(dashboard_url=url)
    (run_dir / 'dashboard.json').write_text(json.dumps({'url': url, 'run_id': run_id}))
    (root / 'outputs/latest_run.json').write_text(json.dumps({'run_id': run_id, 'directory': str(run_dir), 'url': url}))
    print(f'Run: {run_id}\nDashboard: {url}\nAudit: {run_dir}', flush=True)
    if not args.headless:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    started = time.monotonic()
    code = 1
    try:
        llm = CodexCLI(root, run_dir, audit, config['agents'])
        llm._credentials()  # fail visibly before seed construction
        engine = LibreOfficeEngine(root, config['engine']['image'], config['engine']['timeout_seconds'])
        audit.emit('run.preflight', engine=engine.metadata(), model=llm.model, reasoning_effort=llm.reasoning)
        code = 0 if FactoryPipeline(config, audit, llm, engine).run() else 2
    except KeyboardInterrupt:
        audit.update_run(status='cancelled'); code = 130
    except Exception as exc:
        audit.update_run(status='failed', error=str(exc)); audit.emit('run.failed', error=str(exc))
        print(type(exc).__name__ + ': ' + str(exc), file=sys.stderr, flush=True)
    finally:
        audit.update_run(wall_seconds=round(time.monotonic() - started, 3), exit_code=code)
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
