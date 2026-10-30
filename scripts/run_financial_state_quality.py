#!/usr/bin/env python3
"""Prepare the first full-state FM development task, then run every normal gate."""
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

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.resume import PROTECTED_BUDGETS
from sheets_factory.task_adapters import composite_full_state_fm as provider
from sheets_factory.task_adapters.public_workbook_scope import reference, write_new


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cohort = load_script('_financial_state_cohort', ROOT / 'scripts/run_composite_quality_cohort.py')
adapted = load_script('_financial_state_finalization', ROOT / 'scripts/run_adapted_debug_quality.py')
require, sha, read, checked = cohort.require, cohort.sha, cohort.read, cohort.checked
REGISTRY = ROOT / 'config/task_adapters/composite_full_state_fm_nodes.yaml'
POLICY_PATH = ROOT / 'config/task_adapters/composite_full_state_fm_v1.json'
KIND = 'prepared_full_state_financial_development_quality'


def verify_files(bindings):
    for path, expected in bindings.items():
        require(sha(path) == expected, 'Frozen financial development artifact changed: ' + path)


def prepare(output, base_run):
    """Retain the original ten-source order; run only its first source as development."""
    output, base_run = Path(output).resolve(), Path(base_run).resolve()
    require(not output.exists(), 'Preparation exists; use a fresh directory')
    original = read(base_run / 'preflight_manifest.json')
    require(original.get('kind') == 'prepared_normal_quality_cohort'
            and original.get('mode') == 'financial_modeling' and original.get('source_count') == 10,
            'Full-state development requires the original complete ten-source FM admission')
    for group in ('recipe_sha256', 'source_artifacts_sha256'):
        verify_files(original[group])
    seed_path = checked(original['prepared_seed_manifest'])
    seed_manifest = read(seed_path)
    selected = seed_manifest.get('selected')
    require(isinstance(selected, list) and len(selected) == 10, 'Original source selection must contain ten sources')
    batch_path = checked(original['source_batch_manifest'])
    batch = read(batch_path)
    require([e['sha256'] for e in selected] == [e['sha256'] for e in batch['selected']],
            'Original source order differs from its frozen build batch')
    require(batch.get('model_scores_consulted') is False, 'Source order cannot be selected from model outcomes')
    source_bindings = deepcopy(original['source_artifacts_sha256'])
    source_bindings.update({str(seed_path): sha(seed_path), str(batch_path): sha(batch_path),
                            str(base_run / 'preflight_manifest.json'): sha(base_run / 'preflight_manifest.json')})
    for entry in selected:
        proof = cohort.validate_seed(entry)
        require(entry.get('finance_evidence', {}).get('audited_source_binding') == proof,
                'Original admitted financial source binding differs')
        cohort.track_references(proof, source_bindings)
    base_config_path = base_run / 'resolved_config.yaml'
    old_config = yaml.safe_load(base_config_path.read_text())
    require(old_config['run']['targets'] == {'financial_modeling': 10, 'debugging': 10},
            'Original delivery targets must remain ten per mode')
    require(old_config['agents']['model'] == 'gpt-6-sol' and old_config['agents']['reasoning_effort'] == 'high',
            'Financial construction model changed')
    source_bindings[str(base_config_path)] = sha(base_config_path)
    config = deepcopy(old_config)
    for key in ('continuation_id', 'resume_existing_task_ids', 'external_repair_manifest', 'additional_seed_manifests'):
        config['run'].pop(key, None)
    host = cohort.host_runtime_settings(output)
    config.update(project_root=str(ROOT), run_dir=str(output), host_runtime=host)
    config['run'].update(name='full-state-financial-development',
                         seed_manifest=str(output / 'seed_manifest.json'),
                         targets={'financial_modeling': 1, 'debugging': 0},
                         max_sources=1, max_parallel_sources=1)
    config['agents']['max_parallel_calls'] = 1
    config['pipeline'] = {**config.get('pipeline', {}), 'node_registry': str(REGISTRY)}
    config[provider.POLICY] = {'version': provider.VERSION, 'policy': reference(POLICY_PATH)}
    provider.load_policy(config[provider.POLICY]['policy'])
    require(config['diagnosis']['selection'] == {'include': 'all', 'exclude': []}, 'All quality checks are required')
    require(config['harbor']['execute_controls'] is True, 'Actual Harbor controls are required')
    output.mkdir(parents=True)
    # Only source bindings carry forward. Old task-specific repair authorizations
    # must never authorize a new task with the same source prefix.
    policies = {}
    for key in ('public_input_priority', 'public_workbook_scope'):
        setting = deepcopy(old_config[key])
        old_path = checked(setting['manifest'])
        policy = read(old_path)
        require(set(policy['sources']) == {e['sha256'] for e in selected}, 'Public policy source coverage differs')
        policy['tasks'] = {}
        new_ref = write_new(output / (key + '_binding.json'), policy)
        setting['manifest'] = new_ref
        config[key] = setting
        source_bindings[str(old_path)] = sha(old_path)
        policies[key] = {'old_binding': reference(old_path), 'new_binding': new_ref,
                         'task_authorizations_retained': 0}
    write_new(output / 'predeclared_source_selection.json', {
        'kind': 'original_ten_financial_sources_full_state_development',
        'original_seed_manifest': reference(seed_path), 'original_batch': reference(batch_path),
        'ordered_source_sha256': [e['sha256'] for e in selected],
        'ordered_profiles': [e['profile_id'] for e in selected],
        'development_source_index': 0, 'selection_uses_new_model_results': False,
        'delivery_targets': {'financial_modeling': 10, 'debugging': 10}, 'qualified': False})
    prepared_seed = deepcopy(seed_manifest)
    prepared_seed.update(selected=[deepcopy(selected[0])], unique_workbooks_inspected=1,
                         qualified=False, task_count=0)
    prepared_seed['selected'][0].update(modes=['financial_modeling'], variant=0)
    write_new(output / 'seed_manifest.json', prepared_seed)
    recipes = deepcopy(original['recipe_sha256'])
    # Freeze relevant new files explicitly. Unrelated in-progress adapters are
    # excluded; the original 94 mandatory implementation files remain bound.
    paths = [Path(__file__).resolve(), Path(provider.__file__).resolve(), REGISTRY, POLICY_PATH,
             ROOT / 'src/sheets_factory/task_adapters/public_input_priority.py',
             ROOT / 'src/sheets_factory/task_adapters/public_workbook_scope.py',
             ROOT / 'scripts/run_adapted_debug_quality.py']
    recipes.update({str(path): sha(path) for path in paths})
    with cohort.host_temporary_environment(output, host) as host_receipt:
        (output / 'resolved_config.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
        frozen = {'kind': KIND, 'prepared_at': cohort.utcnow(), 'count': 1, 'development_only': True,
                  'delivery_targets': {'financial_modeling': 10, 'debugging': 10},
                  'targets': config['run']['targets'], 'source_count': 1,
                  'original_ten_source_order': reference(output / 'predeclared_source_selection.json'),
                  'selected_source_sha256': selected[0]['sha256'],
                  'source_artifacts_sha256': source_bindings, 'recipe_sha256': recipes,
                  'prepared_seed_manifest': reference(output / 'seed_manifest.json'),
                  'resolved_config': reference(output / 'resolved_config.yaml'),
                  'public_policy_bindings': policies, 'full_state_policy': config[provider.POLICY],
                  'host_runtime': host, 'preparation_host_runtime': host_receipt,
                  'protected_task_budgets': {k: config['run'].get(k) for k in PROTECTED_BUDGETS},
                  'plan_route': 'FullStateFMPlanNode with its own policy/source/audit proof',
                  'factory': 'AuditedSourceFactory', 'all_normal_quality_nodes_required': True,
                  'actual_model_calls': 0, 'actual_LO_calls': 0, 'qualified': False}
        verify_files(source_bindings)
        verify_files(recipes)
        write_new(output / 'preflight_manifest.json', frozen)
    return reference(output / 'preflight_manifest.json')


def validate_prepared(output):
    output = Path(output).resolve()
    frozen = read(output / 'preflight_manifest.json')
    require(frozen.get('kind') == KIND and frozen.get('count') == 1 and frozen.get('development_only') is True,
            'Only a separate first-source development candidate is supported')
    for key in ('recipe_sha256', 'source_artifacts_sha256'):
        verify_files(frozen[key])
    for key in ('prepared_seed_manifest', 'resolved_config', 'original_ten_source_order'):
        checked(frozen[key])
    config = yaml.safe_load(checked(frozen['resolved_config']).read_text())
    selection = read(checked(frozen['original_ten_source_order']))
    seeds = read(checked(frozen['prepared_seed_manifest']))['selected']
    require(len(seeds) == 1 and seeds[0]['sha256'] == frozen['selected_source_sha256']
            == selection['ordered_source_sha256'][0], 'Development source is not the original first source')
    require(len(selection['ordered_source_sha256']) == len(set(selection['ordered_source_sha256'])) == 10,
            'The complete original ten-source selection is required')
    require(config['run']['targets'] == {'financial_modeling': 1, 'debugging': 0}
            and config['pipeline']['node_registry'] == str(REGISTRY), 'Development routing or quota changed')
    require({k: config['run'].get(k) for k in PROTECTED_BUDGETS} == frozen['protected_task_budgets'],
            'Protected task budgets changed')
    provider.load_policy(config[provider.POLICY]['policy'])
    for binding in frozen['public_policy_bindings'].values():
        require(read(checked(binding['new_binding']))['tasks'] == {}, 'Stale repair authorizations carried into development')
    require(cohort.validate_seed(seeds[0]) == seeds[0]['finance_evidence']['audited_source_binding'],
            'Financial development source no longer matches its independent audits')
    return frozen


def execute_prepared(output, *, port=0):
    output = Path(output).resolve()
    frozen = validate_prepared(output)
    settings, legacy = cohort.prepared_host_runtime(output)
    with cohort.host_temporary_environment(output, settings, legacy_preparation=legacy) as host:
        require(not (output / 'run.sqlite').exists(), 'Development run already started; do not repeat it')
        config = yaml.safe_load((output / 'resolved_config.yaml').read_text())
        revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True,
                                  text=True, check=True).stdout.strip()
        lease = cohort.ProducerLease(output).acquire()
        try:
            audit = cohort.AuditStore(output, {'id': output.name, 'target_count': 1, 'financial_target': 1,
                'debugging_target': 0, 'model': config['agents']['model'],
                'reasoning_effort': config['agents']['reasoning_effort'], 'development_only': True,
                'difficulty_status': 'pending', 'status': 'preflight'})
        except BaseException:
            lease.release()
            raise
        server, status, started = None, 1, time.monotonic()
        try:
            server = cohort.DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port)
            url = server.start()
            audit.update_run(dashboard_url=url, producer_pid=os.getpid(), producer_active=True,
                code_revision=revision, host_temporary_directory=host['temporary_directory'], host_runtime_receipt=host)
            llm = cohort.CohortCodex(ROOT, output, audit, config['agents'])
            llm._credentials()
            engine = cohort.LibreOfficeEngine(ROOT, cohort.IMAGE, config['engine']['timeout_seconds'])
            require(engine.metadata()['image_id'] == cohort.IMAGE_ID, 'Financial runtime differs from its source audit')
            audit.emit('run.full_state_financial_preflight', admission=reference(output / 'preflight_manifest.json'),
                       all_normal_quality_nodes_required=True, development_only=True)
            print(json.dumps({'run_dir': str(output), 'dashboard_url': url, 'development_only': True}), flush=True)
            status = 0 if cohort.AuditedSourceFactory(config, audit, llm, engine).run() else 2
            verify_files(frozen['recipe_sha256'])
            return status
        finally:
            adapted.finalize_execution(audit, server, None, lease,
                phase_wall=round(time.monotonic() - started, 3), previous_wall=0, status=status)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-run', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    if args.prepared:
        require(not args.base_run and not args.output, 'Choose preparation or a prepared run')
        if args.run:
            return execute_prepared(args.prepared, port=args.port)
        validate_prepared(args.prepared)
        result = {'prepared': str(args.prepared), 'models_started': 0, 'LO_calls': 0}
    else:
        require(args.base_run and args.output and not args.run, 'Prepare a fresh directory before explicit --run')
        result = {'preparation': prepare(args.output, args.base_run), 'models_started': 0, 'LO_calls': 0}
    print(json.dumps(result), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
