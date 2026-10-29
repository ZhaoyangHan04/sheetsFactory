#!/usr/bin/env python3
"""Create read-only JSON, Chinese Markdown and standalone HTML run reports."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sheets_factory.reporting import write_reports


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--project-root', type=Path)
    parser.add_argument('--engineering-dir', type=Path, action='append', default=[])
    parser.add_argument('--billing-scope-note')
    args = parser.parse_args(argv)
    result = write_reports(args.run_dir, args.output_dir, project_root=args.project_root,
                           engineering_dirs=args.engineering_dir, billing_scope_note=args.billing_scope_note)
    print(json.dumps({'paths': result['paths'], 'yield': result['report']['yield'],
                      'billing': result['report']['billing']}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
