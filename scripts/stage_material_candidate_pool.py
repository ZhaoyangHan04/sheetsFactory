#!/usr/bin/env python3
"""Stage private Harbor task names from unchanged workbook material."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.evaluation.material_release_layout import stage_pool


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--declarations', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage_pool(json.loads(args.declarations.read_text()), args.output)))


if __name__ == '__main__':
    main()
