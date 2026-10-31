#!/usr/bin/env python3
"""Freeze the complete raw candidate pool only; this entry has no run command."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from sheets_factory.workbook.linear_capital_portfolio import catalog, catalog_correlated, catalog_candidates, spec

KIND = 'prepared_linear_capital_twenty_raw_candidate_pool'
ZERO_FIELDS = ('financial_forward_implementation_calls', 'optimizer_calls', 'workbooks',
    'LO_calls', 'model_calls', 'Harbor_jobs', 'task_count')


def reference(path):
    path = Path(path).absolute()
    spec.require(path == path.resolve() and path.is_file() and not path.is_symlink(),
        'Use a real nonsymlink artifact')
    before = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = path.stat()
    spec.require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
        'An artifact changed while hashing')
    return {'path': str(path), 'sha256': digest, 'bytes': after.st_size}


def read(record):
    record = reference(record) if isinstance(record, (str, Path)) else record
    spec.require(reference(record['path']) == record, 'A frozen raw artifact changed')
    result = json.loads(Path(record['path']).read_text(encoding='utf-8'))
    spec.require(reference(record['path']) == record, 'An artifact changed while reading')
    return result


def write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write('\n')
    return reference(path)


def recipes():
    paths = (Path(__file__), Path(catalog_candidates.__file__), catalog_candidates.DEFAULT_CATALOG,
        Path(catalog_correlated.__file__), Path(catalog.__file__), Path(spec.__file__),
        ROOT/'docs/linear_capital_portfolio_contract.md')
    return {str(path.resolve()): reference(path)['sha256'] for path in paths}


def _zero_claims(value):
    return value.get('qualified') is False and all(type(value.get(k)) is int and value[k] == 0 for k in ZERO_FIELDS)


def _shared_declaration(configuration, original, frozen_copy):
    return {'catalog_configuration': original, 'frozen_catalog_configuration': frozen_copy,
        'prospective_profile_order': configuration['profile_order'],
        'selection_density_admission': configuration['selection_density_admission'],
        'reference_policy': configuration['reference_policy'], 'candidate_scope': configuration['candidate_scope'],
        'capacity_design_uses_project_NPV_or_optimized_plan': False,
        'all_specifications_frozen_before_financial_execution': True,
        'all_quality_checks_pending': True, 'difficulty_evidence_pending': True,
        **{key: 0 for key in ZERO_FIELDS}, 'qualified': False}


def prepare(output):
    output = Path(output).absolute()
    spec.require(output == output.resolve() and output.is_relative_to(ROOT/'outputs') and not output.exists(),
        'Use a fresh real output directory; retain every earlier candidate preparation')
    configuration = catalog_candidates.load_catalog(); recipe = recipes()
    original = reference(catalog_candidates.DEFAULT_CATALOG)
    publics = {pid: catalog_candidates.build_spec(pid, configuration) for pid in configuration['profile_order']}
    plans = {pid: catalog_candidates.diagnostic_plans(pid, configuration, public=publics[pid])
        for pid in configuration['profile_order']}
    output.mkdir(parents=True)
    try:
        with (output/'frozen_catalog.json').open('xb') as stream:
            stream.write(Path(original['path']).read_bytes())
        frozen_copy = reference(output/'frozen_catalog.json')
        spec.require((original['sha256'], original['bytes']) == (frozen_copy['sha256'], frozen_copy['bytes']),
            'The catalog changed while copying')
        common = _shared_declaration(configuration, original, frozen_copy)
        specifications = {}
        # All twenty public raw specifications are written before the first
        # per-profile preparation can be consumed by a later finance entry.
        for pid in configuration['profile_order']:
            (output/pid).mkdir()
            specifications[pid] = write(output/pid/'specification.json', publics[pid])
        preparations = {}
        for policy in configuration['profiles']:
            pid = policy['profile_id']
            preparations[pid] = write(output/pid/'preparation.json', {
                'kind': 'prepared_linear_240_project_raw_assumptions', 'version': 1,
                'created_at': datetime.now(timezone.utc).isoformat(), 'profile_id': pid, 'seed': policy['seed'],
                'specification': specifications[pid], 'specification_sha256': spec.canonical_sha256(publics[pid]),
                'recipe_sha256': recipe, 'all_specifications_frozen_before_finance': specifications,
                'raw_assumption_policy': policy, 'diagnostic_plans': plans[pid], **common})
        spec.require(recipe == recipes() and reference(original['path']) == original,
            'The raw generation implementation or catalog changed during preparation')
        return write(output/'catalog_manifest.json', {'kind': KIND, 'version': 1,
            'created_at': datetime.now(timezone.utc).isoformat(), 'profile_order': configuration['profile_order'],
            'profiles': [{'profile_id': p['profile_id'], 'assumption_policy': p,
                'specification': specifications[p['profile_id']], 'raw_preparation': preparations[p['profile_id']]}
                for p in configuration['profiles']], 'recipe_sha256': recipe, **common})
    except BaseException as error:
        write(output/'failure.json', {'kind': 'raw_candidate_preparation_failure', 'error_type': type(error).__name__,
            'error': str(error), 'all_partial_artifacts_retained': True,
            **{key: 0 for key in ZERO_FIELDS}, 'qualified': False})
        raise


def validate_prepared(output):
    output = Path(output).absolute()
    spec.require(output == output.resolve() and output.is_relative_to(ROOT/'outputs'),
        'Use the original real raw preparation directory')
    value = read(output/'catalog_manifest.json')
    configuration = catalog_candidates.load_catalog(); current_recipe = recipes()
    original = reference(catalog_candidates.DEFAULT_CATALOG)
    frozen_copy = reference(output/'frozen_catalog.json')
    spec.require((original['sha256'], original['bytes']) == (frozen_copy['sha256'], frozen_copy['bytes'])
        and catalog_candidates.exact(read(frozen_copy), configuration), 'The frozen catalog configuration changed')
    common = _shared_declaration(configuration, original, frozen_copy)
    spec.require(value.get('kind') == KIND and type(value.get('version')) is int and value['version'] == 1
        and value['profile_order'] == configuration['profile_order'] and value['recipe_sha256'] == current_recipe
        and _zero_claims(value) and catalog_candidates.exact({k:value.get(k) for k in common}, common),
        'The complete prospective raw candidate pool or its unchanged gates differs')
    spec.require([row['profile_id'] for row in value['profiles']] == configuration['profile_order'],
        'All twenty profiles must remain present in their predeclared order')
    all_specs = {row['profile_id']: row['specification'] for row in value['profiles']}
    for row, policy in zip(value['profiles'], configuration['profiles']):
        pid = policy['profile_id']; public = spec.load_spec(read(row['specification']))
        raw = read(row['raw_preparation'])
        spec.require(row['specification']['path'] == str(output/pid/'specification.json')
            and row['raw_preparation']['path'] == str(output/pid/'preparation.json'),
            'A candidate artifact moved outside its original frozen profile')
        spec.require(catalog_candidates.exact(public, catalog_candidates.build_spec(pid, configuration)),
            'The raw primitives differ from the predeclared public-only generation policy')
        spec.require(raw.get('kind') == 'prepared_linear_240_project_raw_assumptions'
            and type(raw.get('version')) is int and raw['version'] == 1
            and raw['profile_id'] == pid and type(raw['seed']) is int and raw['seed'] == policy['seed']
            and catalog_candidates.exact(row['assumption_policy'], policy)
            and catalog_candidates.exact(raw['raw_assumption_policy'], policy)
            and raw['specification'] == row['specification']
            and raw['specification_sha256'] == spec.canonical_sha256(public)
            and raw['recipe_sha256'] == current_recipe
            and raw['all_specifications_frozen_before_finance'] == all_specs
            and catalog_candidates.exact(raw['diagnostic_plans'],
                catalog_candidates.diagnostic_plans(pid, configuration, public=public))
            and _zero_claims(raw) and catalog_candidates.exact({k:raw.get(k) for k in common}, common),
            'A candidate source, diagnostic plan, gate, type or zero-execution declaration changed')
    spec.require(current_recipe == recipes() and reference(original['path']) == original,
        'The raw recipe changed during validation')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()
    if args.validate_only:
        result = validate_prepared(args.output)
        print(json.dumps({'validated': str(args.output), 'profile_count': len(result['profiles']),
            **{key: 0 for key in ZERO_FIELDS}, 'qualified': False}))
    else:
        print(json.dumps(prepare(args.output)))
