#!/usr/bin/env python3
"""Freeze one audited G01 DBG quality run; execute services only with --run."""
from __future__ import annotations

import argparse
from copy import deepcopy
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

from sheets_factory.pipelines import entity_group_admission as admission
from sheets_factory.pipelines.entity_group_factory import EntityGroupFactory, TARGETS, REFERENCE_METHOD, validate_configuration, validate_seed
from sheets_factory.resume import PROTECTED_BUDGETS
from sheets_factory.task_adapters import entity_group as adapter
from sheets_factory.nodes.joint_controls import SETTING as CONTROL_SETTING, setting as controls_setting
from sheets_factory.task_adapters.public_workbook_scope import CLAUSES, checked_bytes, read, reference, require, write_new
from sheets_factory.workbook.entity_group.catalog import PROFILE_IDS, CONFIG as CATALOG, build_spec, load_catalog
from sheets_factory.workbook.resource_engine import ResourceLibreOfficeEngine

KIND = 'prepared_first_fixed_plan_entity_group_G01_debugging_normal_quality'
REGISTRY = ROOT / 'config/task_adapters/entity_group_nodes.yaml'
PROFILE = ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml'


def support(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


cohort = support('_entity_normal_cohort_support', 'run_composite_quality_cohort.py')
finalization = support('_entity_normal_cleanup_support', 'run_adapted_debug_quality.py')


def verify_files(mapping):
    for path, digest in mapping.items():
        require(reference(path)['sha256'] == digest, 'A frozen entity-quality dependency changed: ' + path)


def add_references(value, artifacts):
    admission.verify_references(value, artifacts)
    return artifacts


def validate_first_catalog(path, public):
    record = reference(path); manifest = read(record)
    require(manifest.get('kind') == 'predeclared_entity_group_public_specs'
            and type(manifest.get('version')) is int and manifest['version'] == 1
            and manifest.get('profile_order') == list(PROFILE_IDS)
            and manifest.get('selection_uses_model_outcomes') is False
            and manifest.get('same_provided_plan_shared_across_scenarios') is True
            and manifest.get('scenario_financing_states_are_independent') is True
            and manifest.get('selected') == [] and manifest.get('qualified') is False
            and all(type(manifest.get(key)) is int and manifest[key] == 0
                    for key in ('ledger_executions', 'workbook_engine_calls', 'model_calls', 'source_workbooks', 'task_count')),
            'The original predeclared fixed-ten zero-call primitive catalog is required')
    require(manifest['catalog'] == reference(CATALOG), 'The original public financial primitive catalog changed')
    catalog = load_catalog(CATALOG); rows = manifest['specifications']
    require([row.get('profile_id') for row in rows] == list(PROFILE_IDS), 'The full original G01..G10 order changed')
    for row in rows:
        require(read(row['spec']) == build_spec(row['profile_id'], catalog),
                'A predeclared public specification differs from the fixed primitive catalog')
    require(public == read(rows[0]['spec']), 'The first development source must be G01, selected before outcomes')
    admission.verify_references(manifest)
    return record


def _checked_base(base_run):
    preflight = reference(base_run / 'preflight_manifest.json'); original = read(preflight)
    verify_files(original['recipe_sha256'])
    config_ref = reference(base_run / 'resolved_config.yaml')
    config = yaml.safe_load(checked_bytes(config_ref))
    require(config['agents']['model'] == 'gpt-6-sol' and config['agents']['reasoning_effort'] == 'high'
            and config['diagnosis']['selection'] == {'include': 'all', 'exclude': []}
            and config['harbor']['execute_controls'] is True,
            'The normal original quality configuration, full checks and actual Harbor controls are required')
    return preflight, original, config_ref, config


def prepare(source_manifest, catalog_manifest, base_run, output, *, runtime_profile=PROFILE):
    output, base_run = Path(output).absolute(), Path(base_run).absolute()
    require(output == output.resolve() and not output.exists(), 'Use a fresh real entity quality directory')
    source_ref = reference(source_manifest)
    proof = admission.validate_source(source_ref)
    profile_ref = reference(runtime_profile)
    require(profile_ref == proof['runtime_profile'], 'The task and actually audited source need the same explicit v2 profile')
    public = read(proof['public_specification'])
    catalog_ref = validate_first_catalog(catalog_manifest, public)
    base_ref, original, base_config_ref, config = _checked_base(base_run)
    protected = {key: config['run'].get(key) for key in PROTECTED_BUDGETS}
    for key in ('continuation_id', 'resume_existing_task_ids', 'external_repair_manifest', 'additional_seed_manifests', 'seed_path', 'source_filter'):
        config['run'].pop(key, None)
    for key in ('composite_full_state_fm', 'full_state_joint_cohort', 'semantic_graph_mutation', 'scc_activity',
                'joint_repair_activity', 'joint_observable_controls', 'public_input_priority', 'pilot_development_relay',
                'capital_allocation_task', 'capital_public_schema'):
        config.pop(key, None)
    config[adapter.SETTING] = adapter.setting(runtime_profile)
    config[CONTROL_SETTING] = controls_setting()
    config.update(project_root=str(ROOT), run_dir=str(output))
    config['run'].update(name='first-fixed-plan-entity-group-G01-debug-normal-quality',
        targets=deepcopy(TARGETS), seed_manifest=str(output / 'seed_manifest.json'),
        max_sources=1, max_parallel_sources=1, max_candidates_per_seed=1, source_ordering='manifest')
    profile = adapter.load_runtime_profile(runtime_profile)
    config['agents'].update(max_parallel_calls=1,
        container_memory=str(profile['docker_resources']['agent']['memory_bytes'] // 1024**3) + 'g',
        container_cpus=profile['docker_resources']['agent']['cpus'])
    config['engine'].update(image=profile['image']['tag'], timeout_seconds=profile['timeouts']['workbook_file_seconds'])
    config['construction'].update(authoring_backend='composite_template', planning_scope='per_mode', instruction_style='business_brief')
    config['construction'].pop('composite_activity', None)
    config['construction'].setdefault('max_edit_count', {})['debugging'] = 200000
    config['construction'].setdefault('analysis_limits', {}).update(
        max_dependency_closure_cells=profile['limits']['max_dependency_closure_cells'],
        max_profile_cells=profile['limits']['max_profile_cells'], per_formula_reference_cells=50000, max_mask_ranges=1024)
    config['pipeline'] = {**config.get('pipeline', {}), 'node_registry': str(REGISTRY)}
    config['recovery'].update(compiler_backend='entity_group_public_integer_shared_compiler', replay_timeout_seconds=7200)
    config['diagnosis'].update(reference_evidence_policy='independent_public_recovery', difficulty_deferred=False)
    config['diagnosis'].setdefault('execution', {})['reference_evidence_transport'] = 'audited_summary'
    config.setdefault('prompt_overrides', {})['diagnosis.md'] = 'diagnosis_joint_financial.md'
    require({key: config['run'].get(key) for key in PROTECTED_BUDGETS} == protected,
            'The normal content, evidence and infrastructure budgets changed')
    validate_configuration(config)
    seed = {'local_path': proof['workbook']['path'], 'sha256': proof['workbook']['sha256'],
        'source_manifest': source_ref, 'source_kind': admission.SOURCE_KIND, 'profile_id': 'G01',
        'variant': 0, 'modes': ['debugging'], 'finance_evidence': {
            'financial_seed_verified': True, 'debugging_eligible': True, 'reference_method': REFERENCE_METHOD,
            'source_manifest': source_ref, 'audited_source_binding': proof,
            'description': 'Hypothetical fixed-plan legal-entity financial close; full source financial proof; all task quality and difficulty remain pending'}}
    validate_seed(seed, proof)
    output.mkdir(parents=True)
    proof_ref = write_new(output / 'private/source_admission.json', proof)
    scope = write_new(output / 'public_workbook_scope_binding.json', {'kind': 'public_workbook_scope_binding',
        'version': 1, 'clauses': CLAUSES, 'sources': {seed['sha256']: {'source': proof['workbook']}},
        'tasks': {}, 'quality_or_difficulty_certified': False})
    config['public_workbook_scope'] = {'version': 1, 'manifest': scope}
    seeds = write_new(output / 'seed_manifest.json', {'unique_workbooks_inspected': 1,
        'download_url': 'local:predeclared-G01-fixed-plan-financial-source', 'archive_sha256': None,
        'selected': [seed], 'independently_emitted_source_workbooks': 1,
        'raw_ancestor_hashes_are_provenance_only': True, 'qualified': False, 'task_count': 0})
    # Admission already binds every declared source artifact. Hash the complete
    # large binding table; do not parse it again as if its logical paths were files.
    artifacts = deepcopy(proof['artifact_sha256'])
    add_references([source_ref, proof, catalog_ref, read(catalog_ref), proof_ref, scope, seeds, base_ref, base_config_ref], artifacts)
    recipes = deepcopy(original['recipe_sha256'])
    recipes.update(read(source_ref)['source_recipe_sha256'])
    for record in config[adapter.SETTING].values():
        if isinstance(record, dict) and 'path' in record and 'sha256' in record:
            recipes[record['path']] = record['sha256']
    from sheets_factory.pipelines import entity_group_factory as family_factory
    for path in (Path(__file__), Path(family_factory.__file__), Path(admission.__file__), REGISTRY,
                 Path(cohort.__file__), Path(finalization.__file__),
                 ROOT / 'prompts/diagnosis_joint_financial.md', ROOT / 'src/sheets_factory/nodes/joint_controls.py'):
        recipes[str(path.resolve())] = reference(path)['sha256']
    config['host_runtime'] = cohort.host_runtime_settings(output)
    with cohort.host_temporary_environment(output, config['host_runtime']) as host:
        (output / 'resolved_config.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
        verify_files(recipes); verify_files(artifacts)
        return write_new(output / 'preflight_manifest.json', {'kind': KIND, 'version': 1,
            'development_only': True, 'targets': TARGETS, 'delivery_targets': {'financial_modeling': 10, 'debugging': 10},
            'count': 1, 'profile_id': 'G01', 'catalog_manifest': catalog_ref, 'source_manifest': source_ref,
            'base_configuration_provenance': {'preflight': base_ref, 'resolved_config': base_config_ref,
                'scope': 'configuration_budgets_and_normal_recipe_only', 'prior_financial_source_proofs_reused': False},
            'source_admission': proof_ref, 'prepared_seed_manifest': seeds,
            'resolved_config': reference(output / 'resolved_config.yaml'), 'protected_task_budgets': protected,
            'source_artifacts_sha256': artifacts, 'recipe_sha256': recipes,
            'host_runtime': config['host_runtime'], 'preparation_host_runtime': host,
            'runtime_profile': profile_ref, 'source_reference_method': REFERENCE_METHOD,
            'requested_resources_are_not_actual_agent_or_verifier_enforcement_evidence': True,
            'all_normal_quality_nodes_required': True, 'actual_models': 0, 'actual_LO_calls': 0,
            'qualified': False, 'task_count': 0, 'quality_or_difficulty_certified': False})


def validate_prepared(output):
    output = Path(output).absolute(); frozen = read(reference(output / 'preflight_manifest.json'))
    require(frozen.get('kind') == KIND and type(frozen.get('version')) is int and frozen['version'] == 1
            and frozen.get('development_only') is True and frozen.get('targets') == TARGETS
            and type(frozen.get('count')) is int and frozen['count'] == 1 and frozen.get('profile_id') == 'G01'
            and frozen.get('source_reference_method') == REFERENCE_METHOD,
            'Only the frozen first G01 debugging development source is supported')
    verify_files(frozen['recipe_sha256']); verify_files(frozen['source_artifacts_sha256'])
    config = yaml.safe_load(checked_bytes(frozen['resolved_config']))
    proof = admission.verify_admitted_proof(read(frozen['source_admission']))
    seeds = read(frozen['prepared_seed_manifest'])['selected']
    require(len(seeds) == 1 and seeds[0]['source_manifest'] == frozen['source_manifest']
            and config['run']['seed_manifest'] == str(output / 'seed_manifest.json')
            and config['run_dir'] == str(output) and config['pipeline']['node_registry'] == str(REGISTRY)
            and config[adapter.SETTING]['runtime_profile'] == proof['runtime_profile'] == frozen['runtime_profile'],
            'The source, node routing, actual run or profile changed')
    validate_seed(seeds[0], proof); validate_configuration(config)
    require({key: config['run'].get(key) for key in PROTECTED_BUDGETS} == frozen['protected_task_budgets']
            and read(config['public_workbook_scope']['manifest'])['tasks'] == {}
            and config['prompt_overrides']['diagnosis.md'] == 'diagnosis_joint_financial.md',
            'The fresh public scope, normal budgets or full joint-quality review policy changed')
    return frozen, config, proof


def execute_prepared(output, *, port=0):
    output = Path(output).absolute(); frozen, config, proof = validate_prepared(output)
    settings, legacy = cohort.prepared_host_runtime(output)
    with cohort.host_temporary_environment(output, settings, legacy_preparation=legacy) as host:
        require(not (output / 'run.sqlite').exists(), 'This producer already started; use an explicit reviewed continuation')
        lease = cohort.ProducerLease(output).acquire()
        try:
            require(not (output / 'run.sqlite').exists(), 'This producer already started; never reinitialize its audit')
            audit = cohort.AuditStore(output, {'id': output.name, 'target_count': 1, 'financial_target': 0,
                'debugging_target': 1, 'status': 'preflight', 'model': config['agents']['model'],
                'reasoning_effort': config['agents']['reasoning_effort'], 'development_only': True, 'difficulty_status': 'pending'})
        except BaseException:
            lease.release(); raise
        server, status, started = None, 1, time.monotonic()
        try:
            server = cohort.DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port)
            url = server.start()
            revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
            audit.update_run(dashboard_url=url, producer_pid=os.getpid(), producer_active=True, code_revision=revision,
                host_temporary_directory=host['temporary_directory'], host_runtime_receipt=host,
                runtime_profile=frozen['runtime_profile'], requested_resources_only_until_actual_inspection=True)
            engine = ResourceLibreOfficeEngine(ROOT, frozen['runtime_profile']['path'], role='source',
                receipt_directory=output / 'resource_receipts')
            runtime = engine.metadata()
            require(runtime['image_id'] == admission.IMAGE_ID, 'The quality runtime differs from the actual source audits')
            llm = cohort.CohortCodex(ROOT, output, audit, config['agents']); llm._credentials()
            print(json.dumps({'run_dir': str(output), 'dashboard_url': url, 'development_only': True}), flush=True)
            status = 0 if EntityGroupFactory(config, audit, llm, engine, admitted_proof=proof).run() else 2
            verify_files(frozen['recipe_sha256']); verify_files(frozen['source_artifacts_sha256'])
            return status
        finally:
            try:
                finalization.finalize_execution(audit, server, None, lease,
                    phase_wall=round(time.monotonic() - started, 3), previous_wall=0, status=status)
            finally:
                audit.db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', type=Path); parser.add_argument('--catalog-manifest', type=Path)
    parser.add_argument('--base-run', type=Path); parser.add_argument('--output', type=Path)
    parser.add_argument('--runtime-profile', type=Path, default=PROFILE)
    parser.add_argument('--prepared', type=Path); parser.add_argument('--run', action='store_true')
    parser.add_argument('--port', type=int, default=0); args = parser.parse_args(argv)
    if args.prepared:
        require(not any((args.source_manifest, args.catalog_manifest, args.base_run, args.output)),
                'Choose a fresh preparation or a frozen prepared run')
        if args.run: return execute_prepared(args.prepared, port=args.port)
        validate_prepared(args.prepared); result = {'validated': str(args.prepared), 'models': 0, 'LO_calls': 0}
    else:
        require(not args.run and all((args.source_manifest, args.catalog_manifest, args.base_run, args.output)),
                'Prepare and review a source-bound run before explicit --run')
        result = {'preparation': prepare(args.source_manifest, args.catalog_manifest, args.base_run, args.output,
            runtime_profile=args.runtime_profile), 'models': 0, 'LO_calls': 0}
    print(json.dumps(result, indent=2)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
