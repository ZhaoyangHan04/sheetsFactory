#!/usr/bin/env python3
"""Prepare one audited 30-D02 FM run; --prepared --run starts normal quality."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import yaml

from sheets_factory.pipelines import constrained_capital_admission as admission
from sheets_factory.task_adapters import constrained_capital_allocation as adapter
from sheets_factory.task_adapters.public_workbook_scope import CLAUSES, read, require, write_new
from sheets_factory.resume import PROTECTED_BUDGETS
from sheets_factory.workbook.resource_engine import ResourceLibreOfficeEngine, load_runtime_profile
from sheets_factory.workbook.capital_allocation_scaled import constrained_catalog as catalog, spec
from sheets_factory.workbook.capital_allocation_scaled import public_recovery

KIND = 'prepared_first_constrained_capital_30_D02_normal_quality'
TARGETS = {'financial_modeling': 1, 'debugging': 0}
PROFILE_ID = '30-D02'
PROFILE = ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml'
REGISTRY = ROOT / 'config/task_adapters/constrained_capital_allocation_nodes.yaml'
CATALOG_SHA256 = 'dc3f5baaf1a5b254155349af45142cc6d0e2521f14b540b610fb191cefeb59ca'


def reference(path):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_file(), 'Use a real regular artifact without symlink components')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}


def verify_files(mapping, *, session=None):
    for path, digest in mapping.items():
        actual = reference(path) if session is None else session.ref(path)
        require(actual['sha256'] == digest, 'A frozen constrained-quality dependency changed: ' + path)


def support(name, filename):
    descriptor = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(descriptor)
    descriptor.loader.exec_module(module)
    return module


cohort = support('_constrained_quality_cohort', 'run_composite_quality_cohort.py')
finalization = support('_constrained_quality_finalization', 'run_adapted_debug_quality.py')


def validate_configuration(config):
    require(adapter.enabled(SimpleNamespace(config=config, mode='financial_modeling')),
            'The explicit scaled financial adapter is required')
    policy = config[adapter.SETTING]
    profile = load_runtime_profile(policy['runtime_profile']['path'])
    run = config['run']
    require(run.get('targets') == TARGETS and all(type(run['targets'].get(k)) is int for k in TARGETS)
            and all(type(run.get(k)) is int and run[k] == 1
                    for k in ('max_sources', 'max_parallel_sources', 'max_candidates_per_seed'))
            and run.get('source_ordering') == 'manifest'
            and not any(run.get(k) for k in ('seed_path', 'source_filter', 'additional_seed_manifests',
                                            'continuation_id', 'resume_existing_task_ids')),
            'Only one fresh prospectively declared 30-D02 development source is supported')
    require(config['diagnosis'].get('selection') == {'include': 'all', 'exclude': []}
            and config['diagnosis'].get('reference_evidence_policy') == 'independent_public_recovery'
            and config['diagnosis'].get('execution', {}).get('reference_evidence_transport') == 'audited_summary'
            and config['diagnosis'].get('difficulty_deferred') is False
            and config['harbor'].get('execute_controls') is True,
            'All twelve quality checks, public recovery and actual Harbor controls are required')
    agents = config['agents']
    require(agents.get('model') == 'gpt-6-sol' and agents.get('reasoning_effort') == 'high'
            and type(agents.get('max_parallel_calls')) is int and agents['max_parallel_calls'] == 1
            and agents.get('trajectory_timeout_seconds') == 600
            and all(agents.get('roles', {}).get(role, {}).get('model') == 'gpt-6-sol'
                    and agents['roles'][role].get('reasoning_effort') == 'high'
                    for role in ('public_diagnostician', 'reference_diagnostician'))
            and agents['roles']['reference_diagnostician'].get('timeout_seconds') == 2400,
            'The original quality roles and explicit trace/private-review budgets are required')
    require(profile['id'] == 'entity_group_large_v2'
            and agents.get('container_memory') == '32g' and agents.get('container_cpus') == 2
            and config['engine'].get('image') == profile['image']['tag']
            and config['engine'].get('timeout_seconds') == 600
            and config['recovery'].get('compiler_backend') == 'scaled_capital_public_A_integer_search_decimal_forward'
            and config['recovery'].get('replay_timeout_seconds') == 7200,
            'Source, public replay and task must bind the same prospective v2 resources')
    public_recovery.validate_kernel_preparation(config['recovery']['public_kernel_preparation'])
    limits = config['construction'].get('analysis_limits', {})
    require(limits.get('max_profile_cells') == limits.get('max_dependency_closure_cells') == 500000
            and limits.get('per_formula_reference_cells') == 50000
            and limits.get('max_mask_ranges') == 1024
            and config['construction'].get('max_edit_count', {}).get('financial_modeling') == 100000,
            'The original complete financial construction bounds must remain explicit')
    return profile


def validate_first_catalog(path, public, *, session=None):
    session = session or admission.ReferenceSession()
    record = session.ref(path)
    require(record['sha256'] == CATALOG_SHA256, 'The full prospective eleven-profile constrained catalog changed')
    manifest = session.read(record)
    require(manifest.get('kind') == 'generated_constrained_scaled_capital_public_specs'
            and type(manifest.get('version')) is int and manifest['version'] == 1
            and manifest.get('status') == 'completed_public_primitives_only'
            and manifest.get('prospective_first_strong_profile') == PROFILE_ID
            and manifest.get('profile_order') == manifest.get('requested_profiles') == list(catalog.PROFILE_ORDER)
            and manifest.get('confirmation_profile_order') == list(catalog.CONFIRMATION_ORDER)
            and type(manifest.get('generated_count')) is int and manifest['generated_count'] == 11
            and manifest.get('failures') == [] and manifest.get('selection_uses_model_outcomes') is False
            and manifest.get('source_original_ancestors') == 2 and manifest.get('raw_ancestors') == spec.RAW_ANCESTORS,
            'The complete prospectively declared D02 and ten separate confirmation profiles are required')
    rows = manifest['specifications']
    require(isinstance(rows, list) and [row.get('profile_id') for row in rows] == list(catalog.PROFILE_ORDER)
            and public == session.read(rows[0]['spec']) and len(spec.load_spec(public)['projects']) == 30,
            'The first development source must be 30-D02; future confirmation sources remain separate')
    inventory = session.read(manifest['prospective_inventory'])
    require(inventory.get('profile_order') == list(catalog.PROFILE_ORDER)
            and [row.get('profile_id') for row in inventory.get('profiles', [])] == list(catalog.PROFILE_ORDER)
            and inventory.get('failures') == []
            and inventory.get('financial_execution_or_model_outcome_selection') is False,
            'The unchanged full eleven-profile prospective inventory is required')
    for row, item in zip(rows, inventory['profiles']):
        require(item.get('spec_sha256') == spec.canonical_sha(spec.load_spec(session.read(row['spec']))),
                'A prospectively declared raw profile changed')
    admission.verify_references([manifest, inventory], session=session)
    return record


def _nested_references(value):
    """Visit complete refs at any nesting depth without reading large files."""
    result = {}
    def walk(item):
        if isinstance(item, dict):
            if 'path' in item and 'sha256' in item:
                require(set(item) == {'path', 'sha256', 'bytes'}, 'A complete nested implementation reference is required')
                prior = result.get(item['path'])
                require(prior is None or prior == item, 'Conflicting nested implementation references')
                result[item['path']] = dict(item)
            else:
                for child in item.values(): walk(child)
        elif isinstance(item, (list, tuple)):
            for child in item: walk(child)
    walk(value)
    return result


def implementation_recipe(policy, *, session=None):
    """Explicit new provider plus frozen ordinary templates and shared helpers."""
    session = session or admission.ReferenceSession()
    adapter.validate_setting(policy)
    records = _nested_references([policy, public_recovery.public_implementation_recipe()])
    paths = (Path(__file__), Path(admission.__file__), Path(admission.shared.__file__),
        ROOT / 'scripts/build_constrained_capital_source.py', ROOT / 'scripts/build_scaled_capital_source.py',
        ROOT / 'scripts/run_constrained_capital_dual.py', ROOT / 'scripts/prepare_constrained_capital_specs.py',
        Path(catalog.__file__), Path(catalog.original.__file__), catalog.DEFAULT_CATALOG,
        catalog.original.DEFAULT_CATALOG, REGISTRY, Path(cohort.__file__), Path(finalization.__file__),
        ROOT / 'src/sheets_factory/pipelines/factory.py', ROOT / 'src/sheets_factory/resume.py',
        ROOT / 'src/sheets_factory/core/audit.py', ROOT / 'src/sheets_factory/dashboard/__init__.py', ROOT / 'src/sheets_factory/dashboard/server.py',
        ROOT / 'src/sheets_factory/llm/__init__.py', ROOT / 'src/sheets_factory/llm/codex.py', ROOT / 'src/sheets_factory/workbook/resource_engine.py',
        ROOT / 'src/sheets_factory/task_adapters/public_workbook_scope.py',
        ROOT / 'prompts/diagnosis_joint_financial.md')
    for path in paths:
        record = session.ref(path)
        require(record['path'] not in records or records[record['path']] == record,
                'A template and its actual implementation disagree')
        records[record['path']] = record
    admission.verify_references(records, session=session)
    return {path: record['sha256'] for path, record in records.items()}


def validate_seed(seed, proof):
    evidence = seed.get('finance_evidence', {})
    require(seed.get('source_kind') == admission.SOURCE_KIND and seed.get('profile_id') == PROFILE_ID
            and seed.get('modes') == ['financial_modeling'] and type(seed.get('variant')) is int and seed['variant'] == 0
            and reference(seed['local_path']) == proof['workbook'] and seed.get('sha256') == proof['workbook']['sha256']
            and seed.get('source_manifest') == evidence.get('source_manifest') == proof['source_manifest']
            and evidence.get('audited_source_binding') == proof
            and evidence.get('financial_seed_verified') is True
            and evidence.get('financial_modeling_eligible') is True
            and evidence.get('reference_method') == admission.METHOD,
            'The complete actually audited first financial source must retain its exact task routing')


def prepare(source_manifest, catalog_manifest, base_run, output, *, public_kernel_preparation, runtime_profile=PROFILE):
    output, base_run = Path(output).absolute(), Path(base_run).absolute()
    require(output == output.resolve() and not output.exists(), 'Use a fresh real quality directory')
    source_ref = reference(source_manifest)
    session = admission.ReferenceSession()
    proof = admission.validate_source(source_ref, session=session)
    profile_ref = reference(runtime_profile)
    require(profile_ref == proof['runtime_profile'], 'The task must bind the actually audited source resource profile')
    kernel_ref = public_kernel_preparation if isinstance(public_kernel_preparation, dict) else reference(public_kernel_preparation)
    kernel = public_recovery.validate_kernel_preparation(kernel_ref)
    catalog_ref = validate_first_catalog(catalog_manifest, read(proof['public_specification']), session=session)
    require(catalog_ref == proof['catalog_manifest'], 'The admitted source and prospective catalog must be identical')
    base_ref, base_config_ref = reference(base_run / 'preflight_manifest.json'), reference(base_run / 'resolved_config.yaml')
    original = read(base_ref)
    verify_files(original['recipe_sha256'])
    config = yaml.safe_load(Path(base_config_ref['path']).read_text())
    require(config['agents']['model'] == 'gpt-6-sol' and config['agents']['reasoning_effort'] == 'high'
            and config['diagnosis']['selection'] == {'include': 'all', 'exclude': []}
            and config['harbor']['execute_controls'] is True,
            'A normal original quality configuration with complete checks is required')
    protected = {key: config['run'].get(key) for key in PROTECTED_BUDGETS}
    for key in ('continuation_id', 'resume_existing_task_ids', 'external_repair_manifest',
                'additional_seed_manifests', 'seed_path', 'source_filter'):
        config['run'].pop(key, None)
    for key in ('composite_full_state_fm', 'full_state_joint_cohort', 'semantic_graph_mutation', 'scc_activity',
                'joint_repair_activity', 'joint_observable_controls', 'public_input_priority', 'pilot_development_relay',
                'capital_allocation_task', 'capital_public_schema', 'entity_group_task'):
        config.pop(key, None)
    config[adapter.SETTING] = adapter.setting(runtime_profile=runtime_profile)
    config.update(project_root=str(ROOT), run_dir=str(output))
    config['run'].update(name='first-constrained-capital-30-D02-FM-normal-quality', targets=deepcopy(TARGETS),
        seed_manifest=str(output / 'seed_manifest.json'), max_sources=1, max_parallel_sources=1,
        max_candidates_per_seed=1, source_ordering='manifest')
    profile = load_runtime_profile(runtime_profile)
    config['agents'].update(max_parallel_calls=1, container_memory='32g', container_cpus=2)
    config['engine'].update(image=profile['image']['tag'], timeout_seconds=600)
    config['construction'].update(authoring_backend='composite_template', planning_scope='per_mode', instruction_style='business_brief')
    config['construction'].pop('composite_activity', None)
    config['construction'].setdefault('max_edit_count', {})['financial_modeling'] = 100000
    config['construction'].setdefault('analysis_limits', {}).update(max_dependency_closure_cells=500000,
        max_profile_cells=500000, per_formula_reference_cells=50000, max_mask_ranges=1024)
    config['pipeline'] = {**config.get('pipeline', {}), 'node_registry': str(REGISTRY)}
    config['recovery'].update(compiler_backend='scaled_capital_public_A_integer_search_decimal_forward',
        replay_timeout_seconds=7200, public_kernel_preparation=kernel_ref)
    config['diagnosis'].update(reference_evidence_policy='independent_public_recovery', difficulty_deferred=False)
    config['diagnosis'].setdefault('execution', {})['reference_evidence_transport'] = 'audited_summary'
    config.setdefault('prompt_overrides', {})['diagnosis.md'] = 'diagnosis_joint_financial.md'
    require({key: config['run'].get(key) for key in PROTECTED_BUDGETS} == protected, 'Normal finite task budgets changed')
    validate_configuration(config)
    seed = {'local_path': proof['workbook']['path'], 'sha256': proof['workbook']['sha256'],
        'source_manifest': source_ref, 'source_kind': admission.SOURCE_KIND, 'profile_id': PROFILE_ID,
        'variant': 0, 'modes': ['financial_modeling'], 'finance_evidence': {
            'financial_seed_verified': True, 'financial_modeling_eligible': True,
            'reference_method': admission.METHOD, 'source_manifest': source_ref, 'audited_source_binding': proof,
            'description': 'Hypothetical common-plan financial source; actual complete source proof; task quality and difficulty pending'}}
    validate_seed(seed, proof)
    output.mkdir(parents=True)
    proof_ref = write_new(output / 'private/source_admission.json', proof)
    scope = write_new(output / 'public_workbook_scope_binding.json', {'kind': 'public_workbook_scope_binding',
        'version': 1, 'clauses': CLAUSES, 'sources': {seed['sha256']: {'source': proof['workbook']}},
        'tasks': {}, 'quality_or_difficulty_certified': False})
    config['public_workbook_scope'] = {'version': 1, 'manifest': scope}
    seeds = write_new(output / 'seed_manifest.json', {'unique_workbooks_inspected': 1,
        'download_url': 'local:prospective-constrained-capital-30-D02', 'archive_sha256': None,
        'selected': [seed], 'independently_emitted_source_workbooks': 1, 'qualified': False, 'task_count': 0})
    artifacts = deepcopy(proof['artifact_sha256'])
    artifacts.update(admission.verify_references([source_ref, proof, catalog_ref, read(catalog_ref), kernel_ref, kernel,
        proof_ref, scope, seeds, base_ref, base_config_ref, config[adapter.SETTING]], session=session))
    recipes = deepcopy(original['recipe_sha256'])
    recipes.update(read(source_ref)['source_recipe_sha256'])
    recipes.update(implementation_recipe(config[adapter.SETTING], session=session))
    config['host_runtime'] = cohort.host_runtime_settings(output)
    with cohort.host_temporary_environment(output, config['host_runtime']) as host:
        (output / 'resolved_config.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
        verify_files(recipes, session=session); verify_files(artifacts, session=session)
        return write_new(output / 'preflight_manifest.json', {'kind': KIND, 'version': 1,
            'development_only': True, 'profile_id': PROFILE_ID, 'targets': TARGETS, 'count': 1,
            'delivery_targets': {'financial_modeling': 10, 'debugging': 10},
            'catalog_manifest': catalog_ref, 'source_manifest': source_ref, 'source_admission': proof_ref,
            'base_configuration_provenance': {'preflight': base_ref, 'resolved_config': base_config_ref,
                'scope': 'normal_configuration_budgets_and_recipe_only', 'prior_source_proofs_reused': False},
            'prepared_seed_manifest': seeds, 'resolved_config': reference(output / 'resolved_config.yaml'),
            'protected_task_budgets': protected, 'source_artifacts_sha256': artifacts, 'recipe_sha256': recipes,
            'host_runtime': config['host_runtime'], 'preparation_host_runtime': host, 'runtime_profile': profile_ref,
            'public_kernel_preparation': kernel_ref, 'kernel_compilation_performed_by_entry': False,
            'requested_resources_are_not_actual_agent_or_verifier_enforcement_evidence': True,
            'all_normal_quality_nodes_required': True,
            'nested_template_and_shared_helpers_recursively_bound': True,
            'model_outcome_selection_or_prior_task_reuse': False, 'actual_models': 0, 'actual_LO_calls': 0,
            'qualified': False, 'task_count': 0, 'quality_or_difficulty_certified': False})


def validate_prepared(output, *, admission_session=None):
    output = Path(output).absolute()
    frozen = read(reference(output / 'preflight_manifest.json'))
    require(frozen.get('kind') == KIND and type(frozen.get('version')) is int and frozen['version'] == 1
            and frozen.get('development_only') is True and frozen.get('profile_id') == PROFILE_ID
            and frozen.get('targets') == TARGETS and type(frozen.get('count')) is int and frozen['count'] == 1,
            'Only the prospectively declared first 30-D02 financial development run is supported')
    session = admission_session or admission.ReferenceSession()
    verify_files(frozen['recipe_sha256'], session=session)
    config = yaml.safe_load(Path(frozen['resolved_config']['path']).read_text())
    require(reference(frozen['resolved_config']['path']) == frozen['resolved_config'], 'Resolved configuration changed')
    proof = admission.verify_admitted_proof(read(frozen['source_admission']), session=session)
    verify_files(frozen['source_artifacts_sha256'], session=session)
    require(frozen.get('nested_template_and_shared_helpers_recursively_bound') is True
            and frozen.get('model_outcome_selection_or_prior_task_reuse') is False,
            'The explicit D02 template/source boundaries changed')
    expected_recipe = {**proof['source_recipe_sha256'],
        **implementation_recipe(config[adapter.SETTING], session=session)}
    require(all(frozen['recipe_sha256'].get(path) == digest for path, digest in expected_recipe.items()),
            'The full source, nested templates or shared normal helpers are not frozen')
    require(frozen['catalog_manifest'] == proof['catalog_manifest']
            == validate_first_catalog(frozen['catalog_manifest']['path'], read(proof['public_specification']), session=session),
            'The exact prospectively frozen D02 catalog changed')
    seeds = read(frozen['prepared_seed_manifest'])['selected']
    require(len(seeds) == 1 and seeds[0]['source_manifest'] == frozen['source_manifest']
            and config['run']['seed_manifest'] == str(output / 'seed_manifest.json')
            and config['run_dir'] == str(output) and config['pipeline']['node_registry'] == str(REGISTRY)
            and config[adapter.SETTING]['runtime_profile'] == proof['runtime_profile'] == frozen['runtime_profile'],
            'The exact source, node routing, run or resource profile changed')
    validate_seed(seeds[0], proof); validate_configuration(config)
    require({key: config['run'].get(key) for key in PROTECTED_BUDGETS} == frozen['protected_task_budgets']
            and config['recovery']['public_kernel_preparation'] == frozen['public_kernel_preparation']
            and read(config['public_workbook_scope']['manifest'])['tasks'] == {}
            and config['prompt_overrides']['diagnosis.md'] == 'diagnosis_joint_financial.md',
            'The normal budgets, fresh scope or complete quality review changed')
    return frozen, config, proof


def execute_prepared(output, *, port=0):
    output = Path(output).absolute()
    session = admission.ReferenceSession()
    frozen, config, proof = validate_prepared(output, admission_session=session)
    settings, legacy = cohort.prepared_host_runtime(output)
    with cohort.host_temporary_environment(output, settings, legacy_preparation=legacy) as host:
        require(not (output / 'run.sqlite').exists(), 'This producer already started; use a reviewed continuation')
        lease = cohort.ProducerLease(output).acquire()
        try:
            require(not (output / 'run.sqlite').exists(), 'Never reinitialize an existing run audit')
            audit = cohort.AuditStore(output, {'id': output.name, 'target_count': 1, 'financial_target': 1,
                'debugging_target': 0, 'status': 'preflight', 'model': config['agents']['model'],
                'reasoning_effort': config['agents']['reasoning_effort'], 'development_only': True, 'difficulty_status': 'pending'})
        except BaseException:
            lease.release()
            raise
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
            require(engine.metadata()['image_id'] == admission.IMAGE_ID, 'Quality runtime differs from actual source audits')
            llm = cohort.CohortCodex(ROOT, output, audit, config['agents'])
            llm._credentials()
            print(json.dumps({'run_dir': str(output), 'dashboard_url': url, 'development_only': True}), flush=True)
            status = 0 if admission.ConstrainedCapitalFactory(config, audit, llm, engine,
                admitted_proof=proof, admission_session=session).run() else 2
            verify_files(frozen['recipe_sha256'], session=session)
            verify_files(frozen['source_artifacts_sha256'], session=session)
            return status
        finally:
            try:
                finalization.finalize_execution(audit, server, None, lease,
                    phase_wall=round(time.monotonic() - started, 3), previous_wall=0, status=status)
            finally:
                audit.db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-manifest', 'catalog-manifest', 'base-run', 'output', 'prepared', 'public-kernel-preparation'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--runtime-profile', type=Path, default=PROFILE)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    if args.prepared:
        require(not any((args.source_manifest, args.catalog_manifest, args.base_run, args.output, args.public_kernel_preparation)),
                'Choose a new preparation or one existing prepared run')
        if args.run:
            return execute_prepared(args.prepared, port=args.port)
        validate_prepared(args.prepared)
        result = {'validated': str(args.prepared), 'models': 0, 'LO_calls': 0}
    else:
        require(not args.run and all((args.source_manifest, args.catalog_manifest, args.base_run, args.output, args.public_kernel_preparation)),
                'Prepare and review the source-bound run before explicit execution')
        result = {'preparation': prepare(args.source_manifest, args.catalog_manifest, args.base_run,
            args.output, public_kernel_preparation=args.public_kernel_preparation,
            runtime_profile=args.runtime_profile), 'models': 0, 'LO_calls': 0}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
