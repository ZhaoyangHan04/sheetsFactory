#!/usr/bin/env python3
"""Run the unchanged strict strongest-model gate on explicit resource exports."""
import argparse
import json
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.evaluation.resource_frontier import resume_infrastructure, run_evaluation
from sheets_factory.evaluation.resource_observer import ResourceObserver


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--release-manifest', type=Path)
    source.add_argument('--resume-infrastructure', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--phase', choices=['development', 'confirmation'])
    parser.add_argument('--task-id', action='append')
    parser.add_argument('--prior-selection', type=Path, action='append', default=[])
    parser.add_argument('--concurrency', type=int, default=1)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--max-infrastructure-retries', type=int, default=2)
    args = parser.parse_args(argv)
    if args.resume_infrastructure:
        if args.output_dir or args.phase or args.task_id or args.prior_selection:
            parser.error('Infrastructure recovery must retain the original frozen directory, phase and selection')
    elif not args.output_dir or not args.phase:
        parser.error('A new evaluation requires --output-dir and --phase')
    backend_path = ROOT / 'config/llm.yaml'
    backend = yaml.safe_load(backend_path.read_text()) if backend_path.is_file() else {}
    backend.update(model='gpt-6.1-sol', reasoning_effort='xhigh',
        roles={'trace_agent': {'model': 'gpt-6.1-sol', 'reasoning_effort': 'xhigh'}})
    directory = args.resume_infrastructure or args.output_dir
    with ResourceObserver(directory) as observer:
        if args.resume_infrastructure:
            result = resume_infrastructure(directory, concurrency=args.concurrency,
                project_root=ROOT, backend_config=backend, port=args.port,
                max_infrastructure_retries=args.max_infrastructure_retries)
        else:
            result = run_evaluation(args.release_manifest, directory, phase=args.phase,
                task_ids=args.task_id, concurrency=args.concurrency, project_root=ROOT,
                backend_config=backend, prior_selections=args.prior_selection, port=args.port)
    print(json.dumps({'evaluation_manifest': str(directory.resolve() / 'evaluation_manifest.json'),
        'status': result['status'], 'score': result['score'], 'gate_passed': result['gate_passed'],
        'resource_observation_receipt': observer.receipt,
        'resource_observation_finalization_error': observer.finalization_error}, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'completed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
