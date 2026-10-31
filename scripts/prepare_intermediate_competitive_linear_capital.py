#!/usr/bin/env python3
"""Freeze all three intermediate raw profiles before any financial execution."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.workbook.linear_capital_portfolio import (
    catalog, catalog_correlated, catalog_intermediate_competitive as intermediate, spec)

KIND = 'prepared_linear_capital_intermediate_competitive_raw_triple'
ZERO_FIELDS = ('financial_forward_implementation_calls', 'optimizer_calls', 'workbooks', 'LO_calls', 'model_calls', 'task_count')


def reference(path):
    path = Path(path).resolve(strict=True)
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(path), 'sha256': digest, 'bytes': path.stat().st_size}


def write(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return reference(path)


def recipes():
    paths = (Path(__file__), Path(intermediate.__file__), Path(catalog_correlated.__file__),
        Path(catalog.__file__), Path(spec.__file__), ROOT / 'docs/linear_capital_portfolio_contract.md')
    return {str(path.resolve()): reference(path)['sha256'] for path in paths}


def _zero_claims(value):
    return value.get('qualified') is False and all(type(value.get(k)) is int and value[k] == 0 for k in ZERO_FIELDS)


def prepare(output):
    output = Path(output).absolute()
    spec.require(output == output.resolve() and output.is_relative_to(ROOT / 'outputs') and not output.exists(),
        'Use a fresh real output directory; preserve every earlier profile')
    recipe = recipes()
    publics = {pid: intermediate.build_spec(pid) for pid in intermediate.PROFILE_ORDER}
    output.mkdir(parents=True)
    specifications = {}
    for pid in intermediate.PROFILE_ORDER:
        (output / pid).mkdir()
        specifications[pid] = write(output / pid / 'specification.json', publics[pid])
    preparations = {}
    for pid in intermediate.PROFILE_ORDER:
        public, policy = publics[pid], intermediate.PROFILES[pid]
        preparations[pid] = write(output / pid / 'preparation.json', {
            'kind': 'prepared_linear_240_project_raw_assumptions', 'version': 1,
            'created_at': datetime.now(timezone.utc).isoformat(), 'profile_id': pid, 'seed': policy['seed'],
            'specification': specifications[pid], 'specification_sha256': spec.canonical_sha256(public),
            'recipe_sha256': recipe, 'prospective_profile_order': list(intermediate.PROFILE_ORDER),
            'all_specifications_frozen_before_finance': specifications, 'raw_assumption_policy': policy,
            'diagnostic_plans': catalog.diagnostic_plans(public, seed=policy['seed']),
            'selection_density_admission': {'minimum': 80, 'maximum': 160, 'public_cardinality_constraint': False},
            'reference_policy': {'private_solver_seconds_per_job': 3600, 'retries': 0,
                'independent_financial_implementations': ['Fraction_A', 'Decimal_B'],
                'all_candidate_scenarios_must_be_feasible': True,
                'all_financial_fields_and_reduced_coefficients_must_agree': True,
                'best_and_excluded_winner_runner_must_be_OPTIMAL': True,
                'unique_posted_objective_gap_at_least_pence': 1,
                'solver_status_is_not_independently_verified_formal_proof': True},
            'capacity_design_uses_project_NPV_or_optimized_plan': False,
            **{key: 0 for key in ZERO_FIELDS}, 'qualified': False})
    spec.require(recipe == recipes(), 'The raw generation recipe changed during preparation')
    return write(output / 'catalog_manifest.json', {
        'kind': KIND, 'version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
        'profile_order': list(intermediate.PROFILE_ORDER),
        'profiles': [{'profile_id': pid, 'specification': specifications[pid],
            'raw_preparation': preparations[pid], 'assumption_policy': intermediate.PROFILES[pid]}
            for pid in intermediate.PROFILE_ORDER],
        'recipe_sha256': recipe, 'all_profiles_frozen_before_financial_execution': True,
        **{key: 0 for key in ZERO_FIELDS}, 'qualified': False})


def validate_prepared(output):
    output = Path(output).resolve(strict=True)
    value = json.loads((output / 'catalog_manifest.json').read_text())
    spec.require(value.get('kind') == KIND and type(value.get('version')) is int and value['version'] == 1
        and value['profile_order'] == list(intermediate.PROFILE_ORDER) and value['recipe_sha256'] == recipes()
        and value['all_profiles_frozen_before_financial_execution'] is True and _zero_claims(value),
        'The complete prospective raw triple changed')
    spec.require([r['profile_id'] for r in value['profiles']] == list(intermediate.PROFILE_ORDER),
        'No prospective profile may be omitted or reordered')
    all_specs = {row['profile_id']: row['specification'] for row in value['profiles']}
    for row in value['profiles']:
        pid, policy = row['profile_id'], intermediate.PROFILES[row['profile_id']]
        for key in ('specification', 'raw_preparation'):
            spec.require(reference(row[key]['path']) == row[key], 'A frozen raw artifact changed')
        public = spec.load_spec(row['specification']['path'])
        raw = json.loads(Path(row['raw_preparation']['path']).read_text())
        spec.require(public == intermediate.build_spec(pid), 'Raw primitives differ from the predeclared recipe')
        spec.require(raw['kind'] == 'prepared_linear_240_project_raw_assumptions' and raw['version'] == 1
            and raw['profile_id'] == pid and raw['seed'] == policy['seed']
            and row['assumption_policy'] == raw['raw_assumption_policy'] == policy
            and raw['specification'] == row['specification']
            and raw['specification_sha256'] == spec.canonical_sha256(public)
            and raw['recipe_sha256'] == value['recipe_sha256']
            and raw['all_specifications_frozen_before_finance'] == all_specs
            and raw['prospective_profile_order'] == value['profile_order']
            and raw['diagnostic_plans'] == catalog.diagnostic_plans(public, seed=policy['seed'])
            and raw['capacity_design_uses_project_NPV_or_optimized_plan'] is False and _zero_claims(raw),
            'A complete source, policy or fixed diagnostic inventory changed')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.output)))
