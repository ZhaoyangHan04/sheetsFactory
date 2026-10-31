#!/usr/bin/env python3
"""Prepare all eleven fixed public specifications. No financial execution mode."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from sheets_factory.workbook.capital_allocation_scaled import constrained_catalog as generation
from sheets_factory.workbook.capital_allocation_scaled import spec
from sheets_factory.workbook.capital_allocation import spec as original_schema


def reference(path):
    path = Path(path).absolute()
    if path != path.resolve() or not path.is_file(): raise ValueError('A regular artifact without symlink components is required')
    data = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def write_new(path, value):
    path = Path(path)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False); stream.write('\n')
    return reference(path)


def prepare(output, *, catalog=generation.DEFAULT_CATALOG):
    """Freeze raw primitives and the full diagnostic inventory, never answers."""
    output, catalog = Path(output).absolute(), Path(catalog).absolute()
    if (output != output.resolve() or not output.is_relative_to(ROOT)
        or not output.is_relative_to(Path('/data')) or output.exists()):
        raise ValueError('Use a fresh real directory under the project /data root')
    config = generation.load_catalog(catalog)
    catalog_ref = reference(catalog)
    paths = [Path(__file__).resolve(), Path(generation.__file__).resolve(), Path(spec.__file__).resolve(),
        Path(original_schema.__file__).resolve(), Path(generation.original.__file__).resolve(),
        generation.original.DEFAULT_CATALOG, ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml']
    recipe = {str(path): reference(path) for path in paths}
    output.mkdir(parents=True)
    write_new(output / 'started.json', {'kind': 'constrained_capital_raw_preparation_started', 'version': 1,
        'created_at': datetime.now(timezone.utc).isoformat(), 'catalog': catalog_ref, 'recipe': recipe,
        'complete_profile_order': list(generation.PROFILE_ORDER), 'selection_uses_model_outcomes': False,
        'ledger_calls': 0, 'optimizer_calls': 0, 'LO_calls': 0, 'model_calls': 0})
    completed, failures, inventory = [], [], []
    for identity in generation.PROFILE_ORDER:
        directory = output / identity; directory.mkdir()
        try:
            public = generation.build_spec(identity, config)
            summary = generation.describe_profile(identity, config)
            contract = generation.public_contract(identity, config)
            diagnostics = generation.engineering_inventory(identity, config)
            record = {'profile_id': identity,
                'spec': write_new(directory / 'public_spec.json', public),
                'public_summary': write_new(directory / 'public_summary.json', summary),
                'candidate_contract': write_new(directory / 'candidate_contract.json', contract),
                'engineering_inventory': write_new(directory / 'engineering_inventory.json', diagnostics)}
            with (directory / 'candidate_contract.md').open('x', encoding='utf-8') as stream:
                stream.write(generation.contract_markdown(contract))
            record['candidate_contract_markdown'] = reference(directory / 'candidate_contract.md')
            completed.append(record)
            inventory.append({'profile_id': identity, 'status': 'public_primitives_prepared',
                'spec_sha256': spec.canonical_sha(public), 'project_count': 30,
                'diagnostic_plan_count': len(diagnostics['plans']), 'engineering_criteria_status': 'predeclared_not_evaluated'})
        except Exception as error:
            failed = {'profile_id': identity, 'error_type': type(error).__name__, 'error': str(error)}
            failures.append(failed); inventory.append({'profile_id': identity, 'status': 'failed', 'failure': failed})
            write_new(directory / 'failure.json', failed)
    if reference(catalog) != catalog_ref or any(reference(path) != record for path, record in recipe.items()):
        failures.append({'profile_id': None, 'error_type': 'FrozenRecipeChanged', 'error': 'A public preparation dependency changed'})
    full_inventory = write_new(output / 'prospective_inventory.json', {'kind': 'complete_constrained_capital_prospective_inventory',
        'version': 1, 'catalog': catalog_ref, 'profile_order': list(generation.PROFILE_ORDER), 'profiles': inventory,
        'failures': failures, 'financial_execution_or_model_outcome_selection': False})
    manifest = {'kind': 'generated_constrained_scaled_capital_public_specs', 'version': 1,
        'status': 'completed_public_primitives_only' if not failures else 'failed_public_preparation',
        'catalog': catalog_ref, 'recipe': recipe, 'prospective_inventory': full_inventory,
        'profile_order': list(generation.PROFILE_ORDER), 'confirmation_profile_order': list(generation.CONFIRMATION_ORDER),
        'prospective_first_strong_profile': generation.DEVELOPMENT_ID, 'requested_profiles': list(generation.PROFILE_ORDER),
        'generated_count': len(completed), 'specifications': completed, 'failures': failures,
        'engineering_criteria_status': 'predeclared_not_evaluated', 'criteria_guaranteed_to_pass': False,
        'fixed_plans_are_diagnostics_not_a_common_plan_answer': True, 'raw_ancestors': dict(spec.RAW_ANCESTORS),
        'raw_ancestry_is_provenance_only': True, 'source_original_ancestors': 2,
        'hypothetical_forecasts_and_policy': True, 'currency': 'GBP', 'monetary_unit': 'pence', 'rate_denominator': spec.SCALE,
        'prospective_runtime_profile': recipe[str(ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml')],
        'requested_resources_are_not_actual_enforcement_evidence': True,
        'prospective_solver_tool_budget': {'seconds': 1800, 'strict_less_than': True,
            'exclude_model_response_time': True, 'parallel_executions': 'sum'},
        'prospective_operational_guard_seconds': 14400, 'optimal_project_count_is_acceptance_criterion': False,
        'financial_feasibility_or_unique_optimum_claimed': False, 'selection_uses_model_outcomes': False,
        'ledger_calls': 0, 'optimizer_calls': 0, 'LO_calls': 0, 'model_calls': 0,
        'source_workbooks': 0, 'quality_or_difficulty_certified': False, 'qualified': False, 'task_count': 0}
    result = write_new(output / 'catalog_manifest.json', manifest)
    if failures: raise ValueError('Raw preparation failures are retained in the complete manifest: ' + result['path'])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=generation.DEFAULT_CATALOG)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.output, catalog=args.catalog), indent=2)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
