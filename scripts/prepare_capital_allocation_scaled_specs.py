#!/usr/bin/env python3
"""Describe the prospective catalog; --generate writes fresh public inputs only."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from sheets_factory.workbook.capital_allocation_scaled import catalog as generation
from sheets_factory.workbook.capital_allocation_scaled import spec as schema
from sheets_factory.workbook.capital_allocation import spec as original_schema


def reference(path):
    path = Path(path).resolve(strict=True)
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def _write(path, value):
    # Exclusive writes make a mistaken repeat fail instead of overwriting evidence.
    with Path(path).open('x', encoding='utf-8') as handle:
        handle.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def _chosen(profiles):
    chosen = list(generation.PROFILE_ORDER) if profiles is None else list(profiles)
    if (not chosen or any(p not in generation.PROFILE_ORDER for p in chosen)
            or chosen != [p for p in generation.PROFILE_ORDER if p in chosen]):
        raise ValueError('Requested profiles must be distinct and retain the prospective catalog order')
    return chosen


def describe(catalog_path=generation.DEFAULT_CATALOG, profiles=None):
    catalog = generation.load_catalog(catalog_path)
    chosen = _chosen(profiles)
    return {'kind': 'scaled_capital_allocation_public_catalog_plan', 'version': 1,
        'prospective_first_strong_profile': catalog['prospective_first_strong_profile'],
        'profile_order': catalog['profile_order'], 'benchmark_profile_order': catalog['benchmark_profile_order'],
        'confirmation_profile_order': catalog['confirmation_profile_order'],
        'requested_profiles': chosen, 'source_original_ancestors': len(schema.RAW_ANCESTORS),
        'planned_raw_specifications': len(catalog['profiles']), 'derived_workbook_count': 0,
        'source_workbooks': 0, 'actual_enumerated_plans': 0, 'LO_calls': 0, 'model_calls': 0,
        'selection_uses_model_outcomes': False, 'financial_or_unique_optimum_claimed': False,
        'qualified': False, 'task_count': 0}


def prepare(catalog_path, output, *, profiles=None, include_diagnostics=False):
    """Generate public primitives, never a source workbook or an optimal choice.

    A requested subset is an operational selection from the already frozen
    complete inventory. It never becomes the catalog's confirmation order.
    """
    catalog_path, output = Path(catalog_path).resolve(strict=True), Path(output).resolve()
    if output.exists():
        raise ValueError('Use a fresh immutable scaled public-specification directory')
    catalog_reference = reference(catalog_path)
    catalog = generation.load_catalog(catalog_path)
    chosen = _chosen(profiles)
    recipe_paths = (Path(__file__).resolve(), Path(generation.__file__).resolve(),
                    Path(schema.__file__).resolve(), Path(original_schema.__file__).resolve())
    if include_diagnostics:
        from sheets_factory.workbook.capital_allocation_scaled import ledger
        from sheets_factory.workbook.capital_allocation import ledger as original_ledger
        recipe_paths += (Path(ledger.__file__).resolve(), Path(original_ledger.__file__).resolve())
    recipe = {str(path): reference(path) for path in recipe_paths}
    # Build every raw specification in memory before any artifact is written.
    # No failed profile is silently removed from this complete inventory.
    rows = generation.generate_specs(catalog)
    inventory = [{'profile_id': r['profile_id'], 'spec_sha256': schema.canonical_sha(r['spec']),
                  'project_count': len(r['spec']['projects']),
                  'requested': r['profile_id'] in chosen} for r in rows]
    output.mkdir(parents=True)
    _write(output / 'prospective_inventory.json', {'kind': 'fixed_scaled_public_specification_inventory',
        'version': 1, 'catalog': catalog_reference, 'recipe': recipe,
        'profile_order': list(generation.PROFILE_ORDER), 'profiles': inventory,
        'source_original_ancestors': len(schema.RAW_ANCESTORS),
        'raw_ancestors': dict(schema.RAW_ANCESTORS), 'selection_uses_model_outcomes': False})
    completed = []
    failure = None
    try:
        for row in rows:
            identifier = row['profile_id']
            if identifier not in chosen:
                continue
            directory = output / identifier
            directory.mkdir()
            _write(directory / 'public_spec.json', row['spec'])
            _write(directory / 'public_summary.json', generation.describe_profile(identifier, catalog))
            contract = generation.public_contract(identifier, catalog)
            _write(directory / 'candidate_contract.json', contract)
            with (directory / 'candidate_contract.md').open('x', encoding='utf-8') as handle:
                handle.write(generation.contract_markdown(contract))
            record = {'profile_id': identifier, 'spec': reference(directory / 'public_spec.json'),
                'public_summary': reference(directory / 'public_summary.json'),
                'candidate_contract': reference(directory / 'candidate_contract.json'),
                'candidate_contract_markdown': reference(directory / 'candidate_contract.md')}
            if include_diagnostics:
                private_directory = output / 'private' / 'fixed_plan_diagnostics'
                private_directory.mkdir(parents=True, exist_ok=True)
                diagnostic_path = private_directory / (identifier + '.json')
                _write(diagnostic_path, generation.diagnose_fixed_plans(identifier, catalog))
                record['private_fixed_plan_diagnostics'] = reference(diagnostic_path)
            completed.append(record)
        if reference(catalog_path) != catalog_reference or any(reference(path) != recipe[str(path)] for path in recipe_paths):
            raise ValueError('The generation recipe changed during this preparation')
    except Exception as error:
        failure = {'type': type(error).__name__, 'message': str(error)}
    manifest = {**describe(catalog_path, profiles),
        'kind': 'generated_scaled_capital_allocation_public_specs',
        'status': 'completed_public_primitives_only' if failure is None else 'failed',
        'catalog': catalog_reference, 'recipe': recipe,
        'prospective_inventory': reference(output / 'prospective_inventory.json'),
        'generated_count': len(completed), 'specifications': completed,
        'fixed_plan_diagnostics_included': include_diagnostics, 'failure': failure}
    _write(output / 'catalog_manifest.json', manifest)
    if failure is not None:
        raise ValueError('Public-specification preparation failed; immutable failure manifest retained: ' + str(output))
    return reference(output / 'catalog_manifest.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=generation.DEFAULT_CATALOG)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--profile', action='append', help='Explicit prospective IDs, in catalog order')
    parser.add_argument('--generate', action='store_true', help='Write public primitives to a fresh directory; no search or workbook')
    parser.add_argument('--diagnostics', action='store_true', help='Forward-evaluate only nine fixed named plans; no optimisation')
    args = parser.parse_args()
    if args.generate:
        if args.output is None:
            parser.error('--generate requires --output')
        result = prepare(args.catalog, args.output, profiles=args.profile, include_diagnostics=args.diagnostics)
    else:
        if args.output is not None or args.diagnostics:
            parser.error('--output and --diagnostics require explicit --generate')
        result = describe(args.catalog, args.profile)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
