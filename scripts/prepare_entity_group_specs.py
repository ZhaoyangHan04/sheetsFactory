#!/usr/bin/env python3
"""Freeze ten public hypothetical entity-group specifications, without execution."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from sheets_factory.workbook.entity_group import catalog
from sheets_factory.workbook.entity_group.spec import require


def ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}


def checked(reference):
    path = Path(reference['path'])
    require(ref(path) == reference, 'A frozen specification or recipe artifact changed: ' + str(path))
    return path


def write(path, value):
    with Path(path).open('x') as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def recipe_paths(catalog_path):
    return [Path(__file__).resolve(), Path(catalog.__file__),
        Path(catalog.__file__).with_name('spec.py'), Path(catalog.__file__).with_name('ledger.py'),
        Path(catalog.__file__).with_name('__init__.py'), Path(catalog_path).resolve()]


def prepare(catalog_path, output):
    catalog_path = Path(catalog_path).resolve()
    output = Path(output).absolute()
    require(not output.exists() and not output.is_symlink(), 'Use a fresh immutable specification directory')
    settings = catalog.load_catalog(catalog_path)
    specifications = [(identity, catalog.build_spec(identity, settings)) for identity in catalog.PROFILE_IDS]
    structures = [catalog.structural_evidence(public) for _, public in specifications]
    require(len({r['structure_sha256'] for r in structures}) == 10,
            'All ten prospective profiles must have different dated funding graphs or priorities')
    output.mkdir(parents=True)
    recipe = []
    for index, original in enumerate(recipe_paths(catalog_path)):
        snapshot = output / 'frozen_recipe' / f'{index:02d}-{original.name}'
        snapshot.parent.mkdir(exist_ok=True)
        shutil.copyfile(original, snapshot)
        recipe.append({'original': ref(original), 'snapshot': ref(snapshot)})
    records = []
    for (identity, public), structure in zip(specifications, structures):
        path = output / f'{identity}.json'
        write(path, public)
        records.append({'profile_id': identity, 'spec': ref(path), 'declared_structure': structure})
    manifest = {'kind': 'predeclared_entity_group_public_specs', 'version': 1,
        'created_at': datetime.now(timezone.utc).isoformat(), 'catalog': ref(catalog_path), 'recipe': recipe,
        'profile_order': list(catalog.PROFILE_IDS), 'specifications': records, 'provenance': catalog.PROVENANCE,
        'selection_uses_model_outcomes': False, 'same_provided_plan_shared_across_scenarios': True,
        'scenario_financing_states_are_independent': True, 'ledger_executions': 0,
        'workbook_engine_calls': 0, 'model_calls': 0, 'source_workbooks': 0,
        'selected': [], 'task_count': 0, 'qualified': False,
        'financial_correctness_or_actual_mechanism_activation_claimed': False}
    write(output / 'catalog_manifest.json', manifest)
    return ref(output / 'catalog_manifest.json')


def validate_prepared(output):
    output = Path(output).resolve()
    manifest = json.loads((output / 'catalog_manifest.json').read_text())
    require(manifest['kind'] == 'predeclared_entity_group_public_specs'
            and manifest['profile_order'] == list(catalog.PROFILE_IDS)
            and [r['profile_id'] for r in manifest['specifications']] == list(catalog.PROFILE_IDS),
            'The complete ordered prospective set must remain fixed')
    checked(manifest['catalog'])
    require([row['original']['path'] for row in manifest['recipe']]
            == [str(p.resolve()) for p in recipe_paths(manifest['catalog']['path'])],
            'The complete generation and financial recipe identities are required')
    for row in manifest['recipe']:
        checked(row['original'])
        snapshot = checked(row['snapshot'])
        require(snapshot.is_relative_to(output / 'frozen_recipe')
                and row['snapshot']['sha256'] == row['original']['sha256'], 'Recipe snapshot mismatch')
    settings = catalog.load_catalog(checked(manifest['catalog']))
    for row in manifest['specifications']:
        path = checked(row['spec'])
        require(path == output / (row['profile_id'] + '.json'), 'A public spec escaped its preparation')
        public = json.loads(path.read_text())
        require(public == catalog.build_spec(row['profile_id'], settings)
                and row['declared_structure'] == catalog.structural_evidence(public),
                'Public primitives differ from their predeclared profile')
    require(manifest['ledger_executions'] == manifest['workbook_engine_calls'] == manifest['model_calls'] == 0
            and manifest['selected'] == [] and manifest['qualified'] is False,
            'Static preparation cannot claim execution or question admission')
    return manifest


def attach_first_ledger(output, attempt):
    """Bind an existing authorized G01 result; never execute or repair a ledger."""
    output, attempt = Path(output).resolve(), Path(attempt).resolve()
    manifest = validate_prepared(output)
    require(not (output / 'first_ledger_addendum.json').exists()
            and not (output / 'first_ledger_evidence.json').exists(), 'Preserve the first ledger attachment')
    terminal_path = attempt / 'terminal.json'
    terminal = json.loads(terminal_path.read_text())
    source = checked(terminal['source'])
    require(terminal['kind'] == 'entity_group_G01_authorized_integer_attempt'
            and terminal['completed'] is True and terminal['workbook_engine_calls'] == terminal['model_calls'] == 0
            and terminal['production_workbook_created'] is False
            and terminal['other_profiles_executed'] is False, 'Only the explicit existing first-source integer attempt is attachable')
    public = json.loads(checked(manifest['specifications'][0]['spec']).read_text())
    require(json.loads(source.read_text()) == public, 'The first-source actual ledger used different public primitives')
    for name in ('spec.py', 'ledger.py', '__init__.py'):
        historical = checked(terminal['recipe'][name])
        require(ref(Path(catalog.__file__).with_name(name))['sha256'] == ref(historical)['sha256'],
                'The actual integer ledger used a different frozen financial implementation')
    result_path = checked(terminal['result'])
    result = json.loads(result_path.read_text())
    evidence = catalog.reachability_evidence(public, result)
    write(output / 'first_ledger_evidence.json', evidence)
    write(output / 'first_ledger_addendum.json', {
        'kind': 'entity_group_existing_G01_integer_attempt_attachment', 'version': 1,
        'catalog_manifest': ref(output / 'catalog_manifest.json'), 'original_attempt': ref(terminal_path),
        'original_source': ref(source), 'prepared_source': manifest['specifications'][0]['spec'],
        'result': ref(result_path), 'reachability_evidence': ref(output / 'first_ledger_evidence.json'),
        'attachment_performs_new_ledger_execution': False, 'other_profiles_executed': False,
        'passed': evidence['passed'], 'financial_source_certified': False,
        'workbook_engine_calls': 0, 'model_calls': 0, 'task_count': 0, 'qualified': False})
    return ref(output / 'first_ledger_addendum.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=catalog.CONFIG)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--ledger-attempt', type=Path, help='Attach an existing first-source integer attempt, with no new calculation')
    args = parser.parse_args()
    if args.prepared is not None:
        if args.ledger_attempt is None or args.output:
            parser.error('--prepared requires --ledger-attempt and excludes --output')
        result = attach_first_ledger(args.prepared, args.ledger_attempt)
    else:
        if args.output is None or args.ledger_attempt:
            parser.error('--output is required and --ledger-attempt requires --prepared')
        result = prepare(args.catalog, args.output)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
