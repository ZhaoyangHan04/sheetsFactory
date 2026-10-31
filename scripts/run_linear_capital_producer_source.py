#!/usr/bin/env python3
"""Run the frozen producer-reference source APIs through a separate CLI.

The existing source adapter remains byte-identical for active preparations.
This entry point does not certify task quality or measured difficulty.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _provider():
    path = ROOT / 'scripts/build_linear_capital_producer_source.py'
    definition = importlib.util.spec_from_file_location('_linear_producer_source_cli_provider', path)
    module = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(module)
    return module


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    if args.prepared is not None:
        if any(v is not None for v in (args.spec, args.reference, args.output, args.profile)):
            parser.error('Use --prepared alone; new source inputs and profile cannot replace a frozen preparation.')
    elif any(v is None for v in (args.spec, args.reference, args.output)):
        parser.error('A new source requires --spec, --reference and --output together.')
    if not 0 <= args.port <= 65535:
        parser.error('--port must be between 0 and 65535.')
    provider = _provider()
    if args.prepared is not None:
        if args.run:
            result = provider.execute_prepared(args.prepared, port=args.port)
        else:
            provider.validate_prepared(args.prepared)
            result = provider.reference(args.prepared / 'preparation.json')
    else:
        result = provider.prepare(args.spec, args.reference, args.output,
                                  profile=args.profile if args.profile is not None else provider.DEFAULT_PROFILE)
        if args.run:
            result = provider.execute_prepared(args.output, port=args.port)
    print(json.dumps(result), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
