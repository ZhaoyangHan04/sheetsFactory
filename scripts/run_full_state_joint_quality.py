#!/usr/bin/env python3
"""Prepare a fixed mixed20 quality run. Execution requires explicit --run."""
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
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.pipelines import full_state_joint_factory as mixed
from sheets_factory.task_adapters import full_state_joint_cohort as dispatch
from sheets_factory.task_adapters import composite_full_state_fm as fullstate
from sheets_factory.nodes import joint_controls
from sheets_factory.resume import PROTECTED_BUDGETS
from sheets_factory.task_adapters.public_input_priority import RULE
from sheets_factory.task_adapters.public_workbook_scope import (
    CLAUSES, canonical, checked_bytes, read as read_ref, reference, require, write_new)

KIND = 'prepared_fixed_ten_full_state_joint_quality'
REGISTRY = ROOT / 'config/task_adapters/full_state_joint_cohort_nodes.yaml'
FM_POLICY = ROOT / 'config/task_adapters/composite_full_state_fm_v1.json'
JOINT_PROMPT = ROOT / 'prompts/diagnosis_joint_financial.md'
TARGETS = {'financial_modeling': 10, 'debugging': 10}


def support(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    require(spec is not None and spec.loader is not None, 'Missing frozen mixed-cohort support entry')
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


cohort = support('_mixed_original_source_support', 'run_composite_quality_cohort.py')
finalization = support('_mixed_finalization_support', 'run_adapted_debug_quality.py')


def read(path):
    return json.loads(Path(path).read_bytes())


def verify(mapping):
    for path, expected in mapping.items():
        require(reference(path)['sha256'] == expected, 'Frozen mixed-cohort artifact changed: ' + path)


def track(value, mapping):
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            actual = reference(value['path']); checked_bytes({**actual, **value})
            mapping[actual['path']] = actual['sha256']
        for child in value.values(): track(child, mapping)
    elif isinstance(value, list):
        for child in value: track(child, mapping)


def debug_admission(path, backend):
    path = Path(path).resolve()
    if backend == 'semantic_graph_v3':
        helper = support('_mixed_complete_semantic_batch', 'prepare_semantic_graph_batch.py')
        frozen = helper.validate_completed(path)
        require(frozen.get('kind') == 'semantic_graph_v3_fixed_ten_engineering_seed_pool'
                and frozen.get('status') == 'completed' and type(frozen.get('count')) is int
                and frozen['count'] == 10, 'The complete fixed-ten V3 engineering pool is required')
        setting = frozen['semantic_graph_mutation']
        seeds_ref = frozen['seed_manifest']
    else:
        helper = support('_mixed_complete_v2_batch', 'run_full_graph_quality.py')
        frozen = helper.validate_prepared(path)
        require(frozen.get('kind') == 'prepared_full_graph_joint_quality'
                and type(frozen.get('count')) is int and frozen['count'] == 10,
                'The complete prepared ten-source V2 joint pool is required')
        config = yaml.safe_load(checked_bytes({**reference(frozen['resolved_config']['path']), **frozen['resolved_config']}))
        setting = config[mixed.v2.JOINT_SETTING]
        seeds_ref = frozen['prepared_seed_manifest']
    seeds = read_ref({**reference(seeds_ref['path']), **seeds_ref})['selected']
    require(len(seeds) == 10 and all(seed.get('modes') == ['debugging'] for seed in seeds),
            'The DBG admission must contain the complete ordered ten DBG-only sources')
    return frozen, seeds, setting


def original_source_sha(seed, backend):
    binding = seed['semantic_graph_binding'] if backend == 'semantic_graph_v3' else seed['scc_activity_binding']
    admission = read_ref({**reference(binding['financial_admission']['path']), **binding['financial_admission']})
    if seed.get('original_source'):
        record = seed['original_source']; track(record, {})
        require(record['sha256'] == admission['original_source']['sha256'],
                'The DBG profile lineage differs from its complete financial admission')
    return admission['original_source']['sha256']


def prepare(fm_admission, dbg_admission, output, *, debug_backend, offline_admission, pilot_probe,
            pilot_development_selection=None, workers=1):
    output = Path(output).absolute(); fm_admission = Path(fm_admission).resolve()
    require(output == output.resolve() and not output.exists(), 'Use a fresh non-symlink mixed20 preparation directory')
    require(debug_backend in dispatch.BACKENDS and type(workers) is int and 1 <= workers <= 2,
            'Choose one explicit backend and one or two prospective source workers')
    original = read(fm_admission / 'preflight_manifest.json')
    require(original.get('kind') == 'prepared_normal_quality_cohort'
            and original.get('mode') == 'financial_modeling' and original.get('source_count') == 10,
            'The original complete ten-source FM admission is required')
    for key in ('recipe_sha256', 'source_artifacts_sha256'): verify(original[key])
    fm_seed_ref = {**reference(original['prepared_seed_manifest']['path']), **original['prepared_seed_manifest']}
    fm_seeds = read_ref(fm_seed_ref)['selected']
    require(len(fm_seeds) == 10 and len({s['sha256'] for s in fm_seeds}) == 10
            and all(s.get('modes') == ['financial_modeling'] for s in fm_seeds),
            'Keep the original complete ordered ten FM-only sources')
    batch = read_ref({**reference(original['source_batch_manifest']['path']), **original['source_batch_manifest']})
    fm_order = [seed['sha256'] for seed in fm_seeds]
    require(fm_order == [seed['sha256'] for seed in batch['selected']] and batch.get('model_scores_consulted') is False,
            'The original source order must be independent of model outcomes')
    offline_ref = reference(offline_admission); offline = read_ref(offline_ref)
    require(offline.get('kind') == 'prospective_full_state_FM_fixed_ten_offline_admission'
            and offline.get('source_selection_order') == fm_order
            and offline.get('all_ten_financial_target_sets_preserved_exactly') is True
            and offline.get('all_13854_added_states_per_source_originally_audited_and_publicly_recomputable') is True,
            'The full-state source coverage does not bind the original ten-source order')
    debug, dbg_seeds, debug_setting = debug_admission(dbg_admission, debug_backend)
    require([original_source_sha(seed, debug_backend) for seed in dbg_seeds] == fm_order,
            'The ordered DBG pool must descend from the same complete predeclared ten original sources')
    seeds = [deepcopy(seed) for seed in [*fm_seeds, *dbg_seeds]]
    require(len({seed['sha256'] for seed in seeds}) == 20,
            'Original FM sources and admitted DBG presentations must retain distinct identities')
    base_config_file = fm_admission / 'resolved_config.yaml'
    base_config = yaml.safe_load(base_config_file.read_text())
    require(base_config['run']['targets'] == TARGETS and base_config['agents']['model'] == 'gpt-6-sol'
            and base_config['agents']['reasoning_effort'] == 'high', 'Original delivery quotas or quality model changed')
    config = deepcopy(base_config)
    for name in ('continuation_id', 'resume_existing_task_ids', 'external_repair_manifest', 'additional_seed_manifests'):
        config['run'].pop(name, None)
    config.update(project_root=str(ROOT), run_dir=str(output))
    config['run'].update(name='fixed-full-state-FM-and-joint-DBG20', seed_manifest=str(output / 'seed_manifest.json'),
        targets=deepcopy(TARGETS), max_sources=20, max_parallel_sources=workers,
        source_ordering='manifest', max_candidates_per_seed=1)
    config['agents']['max_parallel_calls'] = workers
    config['construction'].update(authoring_backend='composite_template', planning_scope='per_mode')
    config['construction'].setdefault('max_edit_count', {}).update(financial_modeling=100000, debugging=100000)
    config['construction'].setdefault('analysis_limits', {}).update(max_dependency_closure_cells=500000,
        max_profile_cells=500000, per_formula_reference_cells=50000, max_mask_ranges=1024)
    config['pipeline'] = {**config.get('pipeline', {}), 'node_registry': str(REGISTRY)}
    config[fullstate.POLICY] = {'version': 1, 'policy': reference(FM_POLICY)}
    config[dispatch.SETTING] = dispatch.setting(debug_backend=debug_backend)
    config[joint_controls.SETTING] = joint_controls.setting()
    config.pop('scc_activity', None)
    if debug_backend == 'semantic_graph_v3':
        config.pop(mixed.v2.JOINT_SETTING, None); config[mixed.v3.SETTING] = debug_setting
    else:
        config.pop(mixed.v3.SETTING, None); config[mixed.v2.JOINT_SETTING] = debug_setting
    config['prompt_overrides'] = {**config.get('prompt_overrides', {}), 'diagnosis.md': JOINT_PROMPT.name}
    require(config['diagnosis']['selection'] == {'include': 'all', 'exclude': []}
            and config['recovery']['compiler_backend'] == 'composite_journal'
            and config['harbor']['execute_controls'] is True,
            'All twelve diagnostics, independent public recovery, and actual Harbor controls are required')
    protected = {key: base_config['run'].get(key) for key in PROTECTED_BUDGETS}
    require(protected == {key: config['run'].get(key) for key in PROTECTED_BUDGETS}, 'Protected repair or evidence budgets changed')
    artifacts = deepcopy(original['source_artifacts_sha256'])
    track(offline_ref, artifacts); track(offline, artifacts)
    for seed in seeds:
        proof = mixed.validate_seed(seed, config, cohort.validate_seed)
        track(proof, artifacts); track(seed, artifacts)
    pilot_ref = reference(pilot_probe); pilot = read_ref(pilot_ref)
    require(len(pilot.get('tasks', [])) == 1 and pilot['tasks'][0].get('source_id') == fm_order[0]
            and pilot.get('physical_missing_formula_count') == 60193,
            'The development relay must be the original first-source full-state prototype')
    track(pilot_ref, artifacts)
    relay = {'version': 1, 'source_id': fm_order[0], 'task_id': pilot['tasks'][0]['task_id'], 'probe': pilot_ref,
        'development_selection': reference(pilot_development_selection) if pilot_development_selection else None,
        'requires_separate_structure_typed_formula_instruction_equivalence': True,
        'repeat_development_for_equivalent_task_permitted': False,
        'old_QA_nodes_or_scores_imported_into_new_DB': False, 'whole_frozen20_confirmation_count': 1}
    if relay['development_selection']: track(relay['development_selection'], artifacts)
    config['pilot_development_relay'] = relay
    output.mkdir(parents=True)
    host = cohort.host_runtime_settings(output); config['host_runtime'] = host
    # Legacy priority-repair records are retained only for their original FM
    # schema. DBG numeric timing remains in its separate provider admission.
    old_priority_ref = base_config['public_input_priority']['manifest']
    old_priority = read_ref({**reference(old_priority_ref['path']), **old_priority_ref})
    priority = deepcopy(old_priority); priority['tasks'] = {}
    priority['sources'] = {key: value for key, value in priority['sources'].items() if key in fm_order}
    require(set(priority['sources']) == set(fm_order), 'Original FM numeric-priority evidence is incomplete')
    priority_ref = write_new(output / 'public_input_priority_binding.json', priority)
    config['public_input_priority'] = {**base_config['public_input_priority'], 'manifest': priority_ref}
    scope_ref = write_new(output / 'public_workbook_scope_binding.json', {
        'kind': 'public_workbook_scope_binding', 'version': 1, 'clauses': CLAUSES,
        'sources': {seed['sha256']: {'source': reference(seed['local_path'])} for seed in seeds},
        'tasks': {}, 'quality_or_difficulty_certified': False})
    config['public_workbook_scope'] = {'version': 1, 'manifest': scope_ref}
    seed_ref = write_new(output / 'seed_manifest.json', {'kind': 'fixed_ten_FM_and_fixed_ten_DBG_sources',
        'unique_workbooks_inspected': 20, 'download_url': 'local:fixed-admitted-FM-and-DBG-sources',
        'archive_sha256': None,
        'selected': seeds, 'qualified': False, 'task_count': 0, 'source_ancestor_unique_count': 2,
        'derived_scenarios_are_independent_observed_companies': False})
    recipes = {**original['recipe_sha256'], **debug.get('recipe_sha256', {})}
    artifacts.update(debug.get('source_artifacts_sha256', {}))
    for path in (Path(__file__).resolve(), Path(mixed.__file__), Path(dispatch.__file__), REGISTRY,
            FM_POLICY, JOINT_PROMPT, Path(cohort.__file__), Path(finalization.__file__), Path(joint_controls.__file__)):
        recipes[str(path.resolve())] = reference(path)['sha256']
    for path in (fm_admission / 'preflight_manifest.json', Path(dbg_admission) / 'preflight_manifest.json', base_config_file):
        if path.is_file(): artifacts[str(path.resolve())] = reference(path)['sha256']
    track(debug, artifacts); track(priority_ref, artifacts); track(scope_ref, artifacts); track(old_priority_ref, artifacts)
    with cohort.host_temporary_environment(output, host) as receipt:
        (output / 'resolved_config.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
        frozen = {'kind': KIND, 'version': 1, 'prepared_at': cohort.utcnow(), 'targets': TARGETS,
            'source_count': 20, 'FM_count': 10, 'DBG_count': 10, 'debug_backend': debug_backend,
            'original_FM_source_order': fm_order, 'DBG_original_source_order': fm_order,
            'DBG_presented_source_order': [seed['sha256'] for seed in dbg_seeds],
            'ordered_profile_ids': [seed['profile_id'] for seed in fm_seeds],
            'prepared_seed_manifest': seed_ref, 'resolved_config': reference(output / 'resolved_config.yaml'),
            'recipe_sha256': recipes, 'source_artifacts_sha256': artifacts, 'host_runtime': host,
            'preparation_host_runtime': receipt, 'protected_task_budgets': protected,
            'offline_full_state_admission': offline_ref, 'pilot_development_relay': relay,
            'source_selection_uses_model_outcomes': False, 'old_runs_or_quotas_modified': False,
            'all_normal_nodes_and_all12_checks_required': True, 'actual_Harbor_controls_required': True,
            'new_LO_calls': 0, 'new_model_calls': 0, 'qualified': False, 'task_count': 0}
        verify(recipes); verify(artifacts)
        return write_new(output / 'preflight_manifest.json', frozen)


def validate_prepared(output):
    output = Path(output).resolve(); frozen = read(output / 'preflight_manifest.json')
    require(frozen.get('kind') == KIND and type(frozen.get('version')) is int and frozen['version'] == 1
            and frozen.get('targets') == TARGETS and frozen.get('source_count') == 20,
            'A complete fixed mixed20 preparation is required')
    verify(frozen['recipe_sha256']); verify(frozen['source_artifacts_sha256'])
    config = yaml.safe_load(checked_bytes(frozen['resolved_config']))
    seeds = read_ref(frozen['prepared_seed_manifest'])['selected']
    fm = [seed for seed in seeds if seed.get('modes') == ['financial_modeling']]
    dbg = [seed for seed in seeds if seed.get('modes') == ['debugging']]
    require(len(seeds) == 20 and len(fm) == len(dbg) == 10
            and [seed['sha256'] for seed in fm] == frozen['original_FM_source_order']
            and [seed['sha256'] for seed in dbg] == frozen['DBG_presented_source_order']
            and [original_source_sha(seed, frozen['debug_backend']) for seed in dbg] == frozen['DBG_original_source_order'],
            'The complete frozen source orders changed')
    require(config['run']['targets'] == TARGETS and config['pipeline']['node_registry'] == str(REGISTRY)
            and {key: config['run'].get(key) for key in PROTECTED_BUDGETS} == frozen['protected_task_budgets'],
            'The frozen node routing, quotas, or protected budgets changed')
    require(dispatch.validate_setting(config) == frozen['debug_backend'], 'The selected DBG backend changed')
    fullstate.load_policy(config[fullstate.POLICY]['policy'])
    for name in ('public_input_priority', 'public_workbook_scope'):
        require(read_ref(config[name]['manifest'])['tasks'] == {}, 'Old task repair authorizations must not enter a fresh run')
    require(config['pilot_development_relay'] == frozen['pilot_development_relay'], 'The first-source observation relay changed')
    return frozen, config


def execute_prepared(output, *, port=0):
    output = Path(output).resolve(); frozen, config = validate_prepared(output)
    settings, legacy = cohort.prepared_host_runtime(output)
    with cohort.host_temporary_environment(output, settings, legacy_preparation=legacy) as host:
        require(not (output / 'run.sqlite').exists(), 'A fresh mixed20 run must not overwrite or replay an existing producer')
        lease = cohort.ProducerLease(output).acquire()
        try:
            audit = cohort.AuditStore(output, {'id': output.name, 'target_count': 20,
                'financial_target': 10, 'debugging_target': 10, 'model': config['agents']['model'],
                'reasoning_effort': config['agents']['reasoning_effort'], 'status': 'preflight', 'difficulty_status': 'pending'})
        except BaseException:
            lease.release(); raise
        server, result, started = None, 1, time.monotonic()
        try:
            server = cohort.DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port)
            url = server.start()
            revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
            audit.update_run(dashboard_url=url, producer_pid=os.getpid(), producer_active=True, code_revision=revision,
                host_temporary_directory=host['temporary_directory'], host_runtime_receipt=host)
            llm = cohort.CohortCodex(ROOT, output, audit, config['agents']); llm._credentials()
            engine = cohort.LibreOfficeEngine(ROOT, cohort.IMAGE, config['engine']['timeout_seconds'])
            require(engine.metadata()['image_id'] == cohort.IMAGE_ID, 'Mixed20 runtime differs from its source audits')
            print(json.dumps({'run_dir': str(output), 'dashboard_url': url, 'targets': TARGETS}), flush=True)
            result = 0 if mixed.FullStateJointFactory(config, audit, llm, engine, fm_validator=cohort.validate_seed).run() else 2
            verify(frozen['recipe_sha256']); verify(frozen['source_artifacts_sha256'])
            return result
        finally:
            finalization.finalize_execution(audit, server, None, lease,
                phase_wall=round(time.monotonic() - started, 3), previous_wall=0, status=result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fm-admission', type=Path); parser.add_argument('--dbg-admission', type=Path)
    parser.add_argument('--debug-backend', choices=dispatch.BACKENDS)
    parser.add_argument('--offline-admission', type=Path); parser.add_argument('--pilot-probe', type=Path)
    parser.add_argument('--pilot-development-selection', type=Path)
    parser.add_argument('--output', type=Path); parser.add_argument('--prepared', type=Path)
    parser.add_argument('--workers', type=int, default=1); parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    if args.prepared:
        require(not any((args.fm_admission, args.dbg_admission, args.output)), 'Choose a fresh preparation or an existing prepared run')
        if args.run: return execute_prepared(args.prepared, port=args.port)
        validate_prepared(args.prepared); result = {'prepared': str(args.prepared), 'models_started': 0, 'LO_calls': 0}
    else:
        require(not args.run and all((args.fm_admission, args.dbg_admission, args.debug_backend,
            args.offline_admission, args.pilot_probe, args.output)), 'Prepare all twenty admitted sources before explicit --run')
        result = {'preparation': prepare(args.fm_admission, args.dbg_admission, args.output,
            debug_backend=args.debug_backend, offline_admission=args.offline_admission, pilot_probe=args.pilot_probe,
            pilot_development_selection=args.pilot_development_selection, workers=args.workers), 'models_started': 0, 'LO_calls': 0}
    print(json.dumps(result, indent=2)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
