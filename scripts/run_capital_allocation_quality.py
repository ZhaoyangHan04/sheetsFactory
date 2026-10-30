#!/usr/bin/env python3
"""Prepare the predeclared first capital-allocation FM normal quality run."""
from __future__ import annotations

import argparse
from copy import deepcopy
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import yaml

from sheets_factory.pipelines import capital_allocation_admission as admission
from sheets_factory.resume import PROTECTED_BUDGETS
from sheets_factory.task_adapters.public_workbook_scope import CLAUSES, checked_bytes, read, reference, require, write_new
from sheets_factory.workbook.capital_allocation.catalog import generate_specs
from sheets_factory.workbook.capital_allocation.spec import load_spec

KIND = 'prepared_first_capital_allocation_FM_normal_quality'
TARGETS = {'financial_modeling': 1, 'debugging': 0}
REGISTRY = ROOT / 'config/task_adapters/capital_allocation_nodes.yaml'
CATALOG = ROOT / 'config/capital_allocation_catalog_v1.json'


def support(name, filename):
    location = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(location); location.loader.exec_module(module)
    return module


cohort = support('_capital_normal_cohort_support', 'run_composite_quality_cohort.py')
finalization = support('_capital_normal_finalization', 'run_adapted_debug_quality.py')


def bind_transitive(value, artifacts=None, visited=None):
    """Bind each actual artifact once; follow declared JSON proof references."""
    artifacts = {} if artifacts is None else artifacts
    visited = set() if visited is None else visited
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            path = value['path']
            require(path not in artifacts or artifacts[path] == value['sha256'], 'Conflicting financial proof identities')
            if path not in visited:
                actual = reference(path)
                raw = checked_bytes({**actual, **value})
                artifacts[path] = value['sha256']; visited.add(path)
                if Path(path).suffix == '.json':
                    bind_transitive(json.loads(raw), artifacts, visited)
        for child in value.values(): bind_transitive(child, artifacts, visited)
    elif isinstance(value, list):
        for child in value: bind_transitive(child, artifacts, visited)
    return artifacts


def verify_files(mapping):
    for path, digest in mapping.items():
        require(reference(path)['sha256'] == digest, 'A frozen normal-quality dependency changed: ' + path)


def validate_first_catalog(catalog_manifest, spec):
    catalog_ref = reference(catalog_manifest); manifest = read(catalog_ref)
    require(manifest.get('kind') == 'generated_hypothetical_public_capital_allocation_specs'
            and type(manifest.get('version')) is int and manifest['version'] == 1
            and type(manifest.get('count')) is int and manifest['count'] == 10
            and manifest.get('selection_uses_model_outcomes') is False
            and all(type(manifest.get(key)) is int and manifest[key] == 0
                    for key in ('actual_enumerated_plans', 'LO_calls', 'model_calls')),
            'The original zero-call fixed-ten public specification declaration is required')
    rows = manifest['specifications']
    require([row.get('profile_id') for row in rows] == ['K' + str(index).zfill(2) for index in range(1, 11)],
            'The complete predeclared capital-allocation order changed')
    declared = json.loads(checked_bytes({**reference(manifest['catalog']['path']), **manifest['catalog']}))
    require(Path(manifest['catalog']['path']).absolute() == CATALOG
            and manifest['catalog']['sha256'] == reference(CATALOG)['sha256'],
            'The original version-one fixed capital-allocation catalog is required')
    generated = generate_specs(declared)
    require(isinstance(generated, list) and len(generated) == 10, 'The public catalog no longer generates ten specifications')
    for row, candidate in zip(rows, generated):
        identifier, public = candidate['profile_id'], candidate['spec']
        actual = load_spec(json.loads(checked_bytes({**reference(row['spec']['path']), **row['spec']})))
        require(row['profile_id'] == identifier and actual == public, 'A frozen public specification differs from the declared financial primitives')
    require(spec == load_spec(json.loads(checked_bytes({**reference(rows[0]['spec']['path']), **rows[0]['spec']}))),
            'This development run must use the predeclared first specification K01')
    return catalog_ref


def prepare(source_manifest, catalog_manifest, base_run, output):
    output, base_run = Path(output).absolute(), Path(base_run).absolute()
    require(output == output.resolve() and not output.exists(), 'Use a fresh non-symlink capital quality directory')
    source_ref = reference(source_manifest)
    proof = admission.validate_source(source_ref)
    spec = load_spec(read(proof['public_specification']))
    catalog_ref = validate_first_catalog(catalog_manifest, spec)
    original_ref = reference(base_run / 'preflight_manifest.json'); original = read(original_ref)
    verify_files(original['recipe_sha256'])
    base_ref = reference(base_run / 'resolved_config.yaml')
    config = yaml.safe_load(checked_bytes(base_ref))
    require(config['agents']['model'] == 'gpt-6-sol' and config['agents']['reasoning_effort'] == 'high'
            and config['diagnosis']['selection'] == {'include': 'all', 'exclude': []}
            and config['harbor']['execute_controls'] is True,
            'Normal high-reasoning quality, all twelve checks and actual Harbor controls are required')
    protected = {key: config['run'].get(key) for key in PROTECTED_BUDGETS}
    for key in ('continuation_id', 'resume_existing_task_ids', 'external_repair_manifest', 'additional_seed_manifests', 'seed_path', 'source_filter'):
        config['run'].pop(key, None)
    for key in ('composite_full_state_fm', 'full_state_joint_cohort', 'semantic_graph_mutation', 'scc_activity',
                'joint_repair_activity', 'joint_observable_controls', 'public_input_priority', 'pilot_development_relay'):
        config.pop(key, None)
    provider = importlib.import_module('sheets_factory.task_adapters.capital_allocation')
    config[provider.SETTING] = provider.setting()
    config.update(project_root=str(ROOT), run_dir=str(output))
    config['run'].update(name='first-capital-allocation-FM-normal-quality', targets=deepcopy(TARGETS),
        seed_manifest=str(output / 'seed_manifest.json'), max_sources=1, max_parallel_sources=1,
        source_ordering='manifest', max_candidates_per_seed=1)
    config['agents']['max_parallel_calls'] = 1
    config['engine']['timeout_seconds'] = 300
    config['construction'].update(authoring_backend='composite_template', planning_scope='per_mode', instruction_style='business_brief')
    config['construction'].setdefault('max_edit_count', {}).update(financial_modeling=100000)
    config['construction'].setdefault('analysis_limits', {}).update(max_dependency_closure_cells=500000,
        max_profile_cells=500000, per_formula_reference_cells=50000, max_mask_ranges=1024)
    config['pipeline'] = {**config.get('pipeline', {}), 'node_registry': str(REGISTRY)}
    config['recovery'].update(compiler_backend='capital_allocation_integer', replay_timeout_seconds=1800)
    config['diagnosis'].setdefault('execution', {})['reference_evidence_transport'] = 'audited_summary'
    require({key: config['run'].get(key) for key in PROTECTED_BUDGETS} == protected, 'Protected normal repair and evidence budgets changed')
    seed = {'local_path': proof['workbook']['path'], 'sha256': proof['workbook']['sha256'],
        'source_manifest': source_ref, 'source_kind': admission.SOURCE_KIND, 'profile_id': 'K01',
        'variant': 0, 'modes': ['financial_modeling'], 'finance_evidence': {
            'financial_modeling_eligible': True, 'financial_seed_verified': True,
            'source_manifest': source_ref, 'audited_source_binding': proof,
            'description': 'Synthetic common-plan capital allocation; complete independent source proof; task quality and difficulty remain pending'}}
    output.mkdir(parents=True)
    source_proof = write_new(output / 'private/source_admission.json', proof)
    scope = write_new(output / 'public_workbook_scope_binding.json', {'kind': 'public_workbook_scope_binding',
        'version': 1, 'clauses': CLAUSES, 'sources': {seed['sha256']: {'source': proof['workbook']}},
        'tasks': {}, 'quality_or_difficulty_certified': False})
    config['public_workbook_scope'] = {'version': 1, 'manifest': scope}
    seeds = write_new(output / 'seed_manifest.json', {'unique_workbooks_inspected': 1,
        'download_url': 'local:predeclared-K01-capital-allocation-source', 'archive_sha256': None,
        'selected': [seed], 'qualified': False, 'task_count': 0, 'source_ancestor_unique_count': 2})
    artifacts = bind_transitive([source_ref, proof, catalog_ref, original_ref, base_ref, source_proof, scope])
    recipes = deepcopy(original['recipe_sha256'])
    source = read(source_ref); recipes.update(source['source_recipe_sha256'])
    recovery = importlib.import_module('sheets_factory.workbook.capital_allocation.public_recovery')
    for path in (Path(__file__), Path(admission.__file__), Path(provider.__file__), Path(recovery.__file__), REGISTRY,
                 Path(cohort.__file__), Path(finalization.__file__)):
        recipes[str(path.resolve())] = reference(path)['sha256']
    config['host_runtime'] = cohort.host_runtime_settings(output)
    with cohort.host_temporary_environment(output, config['host_runtime']) as host:
        (output / 'resolved_config.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
        verify_files(recipes); verify_files(artifacts)
        return write_new(output / 'preflight_manifest.json', {'kind': KIND, 'version': 1, 'development_only': True,
            'targets': TARGETS, 'delivery_targets': {'financial_modeling': 10, 'debugging': 10}, 'count': 1,
            'profile_id': 'K01', 'catalog_manifest': catalog_ref, 'source_manifest': source_ref,
            'source_admission': source_proof, 'prepared_seed_manifest': seeds,
            'resolved_config': reference(output / 'resolved_config.yaml'), 'protected_task_budgets': protected,
            'source_artifacts_sha256': artifacts, 'recipe_sha256': recipes, 'host_runtime': config['host_runtime'],
            'preparation_host_runtime': host, 'all_normal_quality_nodes_required': True,
            'actual_models': 0, 'actual_LO_calls': 0, 'actual_full_enumerations': 0,
            'quality_or_difficulty_certified': False, 'qualified': False, 'task_count': 0})


def validate_prepared(output):
    output = Path(output).absolute(); frozen = read(reference(output / 'preflight_manifest.json'))
    require(frozen.get('kind') == KIND and type(frozen.get('version')) is int and frozen['version'] == 1
            and frozen.get('development_only') is True and frozen.get('targets') == TARGETS
            and frozen.get('profile_id') == 'K01', 'Only a frozen first-source capital FM normal quality run is supported')
    verify_files(frozen['recipe_sha256']); verify_files(frozen['source_artifacts_sha256'])
    config = yaml.safe_load(checked_bytes(frozen['resolved_config']))
    proof = read(frozen['source_admission']); seeds = read(frozen['prepared_seed_manifest'])['selected']
    require(len(seeds) == 1 and seeds[0].get('modes') == ['financial_modeling']
            and seeds[0]['source_manifest'] == frozen['source_manifest']
            and seeds[0]['finance_evidence']['audited_source_binding'] == proof
            and seeds[0]['sha256'] == proof['workbook']['sha256']
            and config['run']['targets'] == TARGETS and config['pipeline']['node_registry'] == str(REGISTRY),
            'The exact source, quota or node routing changed')
    require({key: config['run'].get(key) for key in PROTECTED_BUDGETS} == frozen['protected_task_budgets']
            and config['recovery']['compiler_backend'] == 'capital_allocation_integer'
            and config['recovery']['replay_timeout_seconds'] == 1800
            and read(config['public_workbook_scope']['manifest'])['tasks'] == {},
            'The normal budget, independent replay or fresh public scope changed')
    provider = importlib.import_module('sheets_factory.task_adapters.capital_allocation')
    provider.validate_setting(config[provider.SETTING])
    admission.collect_references(proof)
    return frozen, config, proof


def execute_prepared(output, *, port=0):
    output = Path(output).absolute(); frozen, config, proof = validate_prepared(output)
    settings, legacy = cohort.prepared_host_runtime(output)
    with cohort.host_temporary_environment(output, settings, legacy_preparation=legacy) as host:
        require(not (output / 'run.sqlite').exists(), 'This quality producer has already started; never replay it as a fresh run')
        lease = cohort.ProducerLease(output).acquire()
        try:
            audit = cohort.AuditStore(output, {'id': output.name, 'target_count': 1, 'financial_target': 1,
                'debugging_target': 0, 'status': 'preflight', 'model': config['agents']['model'],
                'reasoning_effort': config['agents']['reasoning_effort'], 'development_only': True, 'difficulty_status': 'pending'})
        except BaseException:
            lease.release(); raise
        server, status, started = None, 1, time.monotonic()
        try:
            server = cohort.DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port)
            url = server.start()
            revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
            audit.update_run(dashboard_url=url, producer_pid=os.getpid(), producer_active=True,
                code_revision=revision, host_temporary_directory=host['temporary_directory'], host_runtime_receipt=host)
            llm = cohort.CohortCodex(ROOT, output, audit, config['agents']); llm._credentials()
            engine = cohort.LibreOfficeEngine(ROOT, cohort.IMAGE, 300)
            require(engine.metadata()['image_id'] == admission.IMAGE_ID, 'The quality runtime differs from the source audits')
            print(json.dumps({'run_dir': str(output), 'dashboard_url': url, 'development_only': True}), flush=True)
            status = 0 if admission.CapitalAllocationFactory(config, audit, llm, engine, admitted_proof=proof).run() else 2
            verify_files(frozen['recipe_sha256']); verify_files(frozen['source_artifacts_sha256'])
            return status
        finally:
            finalization.finalize_execution(audit, server, None, lease,
                phase_wall=round(time.monotonic() - started, 3), previous_wall=0, status=status)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', type=Path); parser.add_argument('--catalog-manifest', type=Path)
    parser.add_argument('--base-run', type=Path); parser.add_argument('--output', type=Path)
    parser.add_argument('--prepared', type=Path); parser.add_argument('--run', action='store_true')
    parser.add_argument('--port', type=int, default=0); args = parser.parse_args(argv)
    if args.prepared:
        require(not any((args.source_manifest, args.catalog_manifest, args.base_run, args.output)), 'Choose one fresh preparation or a prepared run')
        if args.run: return execute_prepared(args.prepared, port=args.port)
        validate_prepared(args.prepared); result = {'validated': str(args.prepared), 'models': 0, 'LO_calls': 0}
    else:
        require(not args.run and all((args.source_manifest, args.catalog_manifest, args.base_run, args.output)), 'Prepare a new source-bound run before explicit --run')
        result = {'preparation': prepare(args.source_manifest, args.catalog_manifest, args.base_run, args.output), 'models': 0, 'LO_calls': 0}
    print(json.dumps(result, indent=2)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
