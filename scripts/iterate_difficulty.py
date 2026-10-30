#!/usr/bin/env python3
"""Construct, measure, iterate and publish a confirmation-gated dataset."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import threading
from uuid import uuid4

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.pipelines.difficulty import DifficultyPipeline


def load_config(path, root=ROOT):
    root = Path(root)
    value = yaml.safe_load(Path(path).read_text())
    llm = yaml.safe_load((root / 'config/llm.yaml').read_text())
    agents = yaml.safe_load((root / 'config/agents.yaml').read_text())
    value['agents'] = {**llm, 'roles': agents.get('roles', {}), **value.get('agents', {})}
    value['prompt_overrides'] = {**agents.get('prompts', {}), **value.get('prompt_overrides', {})}
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/pipelines/hard20.yaml')
    parser.add_argument('--seed-manifest', required=True, type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--max-rounds', type=int)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--exit-on-finish', action='store_true')
    args = parser.parse_args(argv)
    pipeline = None
    try:
        config = load_config(args.config)
        if args.max_rounds is not None:
            config.setdefault('difficulty', {})['max_rounds'] = args.max_rounds
        output = args.output_dir or ROOT / 'outputs/difficulty' / (
            datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
        pipeline = DifficultyPipeline(config, args.seed_manifest, output, project_root=ROOT, headless=args.headless)
        result = pipeline.run()
        print(json.dumps({key: result[key] for key in ('status', 'reason', 'wall_seconds', 'usage')}
                         | {'directory': str(output.resolve()), 'rounds': len(result['rounds']),
                            'final_publication': result['final_publication']}, ensure_ascii=False, indent=2), flush=True)
        if not args.exit_on_finish:
            print('Run finished. Dashboards remain available; Ctrl+C closes viewers.', flush=True)
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                pass
        return {'completed': 0, 'cancelled': 130, 'budget_exhausted': 3}.get(result['status'], 2)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'not_started', 'error_type': type(exc).__name__}), file=sys.stderr)
        return 2
    finally:
        if pipeline:
            pipeline.close()


if __name__ == '__main__':
    raise SystemExit(main())
