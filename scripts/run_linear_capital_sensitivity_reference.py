#!/usr/bin/env python3
"""Prepare/validate all nine references without services; run is explicit."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.workbook.linear_capital_sensitivity import reference


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--prospective', type=Path, required=True)
    prepare.add_argument('--output', type=Path, required=True)
    for command in ('validate', 'run', 'validate-completed'):
        p = sub.add_parser(command)
        p.add_argument('--receipt' if command == 'validate-completed' else '--prepared', type=Path, required=True)
        if command == 'run': p.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    if args.command == 'prepare': result = reference.prepare(args.prospective, args.output)
    elif args.command == 'validate':
        reference.validate_prepared(args.prepared); result = {'validated': str(args.prepared), 'native_calls': 0}
    elif args.command == 'run': result = reference.execute_prepared(args.prepared, port=args.port)
    else: result = reference.validate_completed(args.receipt)
    print(json.dumps(result)); return 0


if __name__ == '__main__': raise SystemExit(main())
