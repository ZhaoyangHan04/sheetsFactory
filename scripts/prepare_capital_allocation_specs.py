#!/usr/bin/env python3
"""Freeze hypothetical public inputs. No search, LibreOffice or model calls."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from sheets_factory.task_adapters.public_input_priority import ref, require, write
from sheets_factory.workbook.capital_allocation import catalog as generation


def prepare(catalog_path, output):
    import json
    catalog_path, output = Path(catalog_path).resolve(), Path(output).resolve()
    require(not output.exists(), 'Use a fresh immutable public-specification directory')
    rows = generation.generate_specs(json.loads(catalog_path.read_text()))
    recipe = [Path(__file__).resolve(), Path(generation.__file__), Path(generation.__file__).with_name('spec.py')]
    output.mkdir(parents=True)
    specifications = []
    for row in rows:
        path = output / (row['profile_id'] + '.json')
        write(path, row['spec'])
        specifications.append({'profile_id': row['profile_id'], 'spec': ref(path)})
    write(output / 'catalog_manifest.json', {
        'kind': 'generated_hypothetical_public_capital_allocation_specs', 'version': 1,
        'catalog': ref(catalog_path), 'recipe': {str(path): ref(path) for path in recipe},
        'count': len(rows), 'specifications': specifications, 'selection_uses_model_outcomes': False,
        'source_workbooks': 0, 'actual_enumerated_plans': 0, 'LO_calls': 0, 'model_calls': 0,
        'financial_correctness_or_unique_optimum_claimed': False, 'qualified': False, 'task_count': 0})
    return ref(output / 'catalog_manifest.json')


def main():
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=ROOT / 'config/capital_allocation_catalog_v1.json')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.catalog, args.output), indent=2))


if __name__ == '__main__':
    main()
