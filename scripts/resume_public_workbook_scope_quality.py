#!/usr/bin/env python3
"""Prepare a prospective Q03-only continuation; models start only with --run."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.task_adapters.public_workbook_scope import (
    POLICY, VERSION, CLAUSES, canonical, checked_bytes, read, reference,
    registry_nodes, require, write_new)
from sheets_factory.reporting import read_run
from sheets_factory.checkers import DiagnosisRunner
from sheets_factory.resume import (
    PROTECTED_BUDGETS, ProducerLease, assert_resume_allowed,
    plan_external_repairs, prepare_resume)


def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


priority = load_script('_scope_priority_continuation', ROOT / 'scripts/resume_public_contract_quality.py')
cohort, cleanup = priority.cohort, priority.adapted
REGISTRY = ROOT / 'config/task_adapters/public_workbook_scope_nodes.yaml'


def collect_references(value, result):
    """Recheck explicit references, including legacy refs without a byte field."""
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            actual = reference(value['path'])
            require(actual['sha256'] == value['sha256']
                    and ('bytes' not in value or actual['bytes'] == value['bytes']),
                    'A bound source or review artifact changed')
            result[actual['path']] = actual
        else:
            for item in value.values():
                collect_references(item, result)
    elif isinstance(value, list):
        for item in value:
            collect_references(item, result)


def scope_review(review_ref, task_id, revision, revision_hash, instruction_ref, *, verifier_contract):
    review = read(review_ref)
    require(review.get('kind') == 'independent_private_public_instruction_scope_forensic_addendum'
            and review.get('diagnostic_topic') == 'Q03_public_instruction_vs_verifier_scope'
            and review.get('finding') == 'supported_material_ambiguity'
            and review.get('supported_ambiguity') is True,
            'A supported, numbered public-scope review is required')
    checked_bytes(review['public_instruction'])
    require(review['public_instruction']['sha256'] == instruction_ref['sha256'],
            'Scope review concerns different public instruction bytes')
    if review.get('task_id') == task_id:
        require(review.get('revision') == revision and review.get('revision_hash') == revision_hash,
                'Scope review belongs to another task revision')
    else:
        # Only this same-wording scope finding transfers. No score, financial
        # correctness finding, old clear assessment, or change-set proof does.
        require(review['public_instruction']['bytes'] == instruction_ref['bytes'],
                'Transferred scope review requires byte-identical public wording')
    checked_bytes(review['verifier_binding'])
    checked_bytes(verifier_contract)
    require(review['verifier_binding']['sha256'] == verifier_contract['sha256']
            and review['verifier_binding']['bytes'] == verifier_contract['bytes'],
            'Scope review and current frozen grader contract differ')
    return review


def issue_for(task_id, revision, revision_hash, review_ref, instruction_ref):
    return {'issue_id': task_id + '-Q03-EXPLICIT-WORKBOOK-SCOPE',
        'task_id': task_id, 'revision': revision, 'revision_hash': revision_hash,
        'problem_id': 'Q03', 'route_id': 'R03', 'certainty': 'confirmed',
        'severity': 'blocker', 'attribution': 'task_defect',
        'claim': 'The public preservation wording does not unambiguously state the existing exact worksheet-list and no-new-helper-value submission scope. Clarify that scope without changing business rules, formulas, targets or the verifier.',
        'evidence': [review_ref, instruction_ref], 'depends_on_issue_ids': []}


def unknown_repair_basis(task_id, revision, revision_hash, issue):
    ids = [f'Q{i:02d}' for i in range(1, 13)]
    return {'kind': 'program_only_public_scope_repair_basis', 'program_only': True,
        'task_id': task_id, 'revision': revision, 'task_revision_hash': revision_hash,
        'enabled_check_ids': ids, 'releasable': False, 'issues': [issue],
        'assessments': {i: {'state': 'flagged' if i == 'Q03' else 'unknown',
            'reason': 'Independent public-scope review' if i == 'Q03' else 'No quality finding asserted by this repair basis'} for i in ids},
        'coverage': {'enabled_count': 12, 'assessed_count': 1,
            'unknown_check_ids': [i for i in ids if i != 'Q03'],
            'blocking_issue_ids': [issue['issue_id']], 'undispositioned_warning_ids': []},
        'quality_recovery_or_difficulty_pass_claimed': False}


def prepare(run, review_files, output, *, task_ids=()):
    run, output = Path(run).resolve(), Path(output).resolve()
    require(not output.exists(), 'Scope preparation requires a fresh output directory')
    require(review_files, 'Scope preparation requires independent public-scope evidence')
    settings = cohort.host_runtime_settings(output)
    output.mkdir(parents=True)
    with cohort.host_temporary_environment(output, settings) as host:
        return _prepare(run, review_files, output, task_ids=task_ids, preparation_host=host)


def _prepare(run, review_files, output, *, task_ids=(), preparation_host=None):
    old_frozen = priority.original_recipe(run)
    config_path = run / 'resolved_config.yaml'
    config_ref = reference(config_path)
    config = yaml.safe_load(checked_bytes(config_ref))
    snapshot = read_run(run)
    verifier_contract = reference(ROOT / 'src/sheets_factory/evaluation/standalone_verifier.py')
    require(config['run']['targets'] == {'financial_modeling': 10, 'debugging': 10},
            'Scope continuation preserves the original 10+10 quotas')
    checker_plan = DiagnosisRunner(ROOT).resolve(config)
    require(set(checker_plan['enabled_check_ids']) == {f'Q{i:02d}' for i in range(1, 13)},
            'Public scope continuation requires all twelve normal diagnostics')
    reviews = [reference(path) for path in review_files]
    selected_ids = list(dict.fromkeys(task_ids or [read(item)['task_id'] for item in reviews]))
    tasks_by_id = {task['id']: task for task in snapshot['tasks']}
    require(selected_ids and set(selected_ids) <= set(tasks_by_id), 'Scope review names an unknown constructed task')
    base_registry = Path(config.get('pipeline', {}).get('node_registry', 'config/nodes.yaml'))
    if not base_registry.is_absolute():
        base_registry = ROOT / base_registry
    base_ref = reference(base_registry)
    base_nodes = yaml.safe_load(checked_bytes(base_ref))['nodes']
    selected_nodes = registry_nodes(base_nodes)
    # The shipped main registry must match exactly. A future DBG wrapper may
    # instead write this pure composition into its own NEW preparation.
    require(yaml.safe_load(REGISTRY.read_text())['nodes'] == selected_nodes,
            'Main continuation cannot silently replace a custom Construct/provider registry')
    seeds, source_bindings, safeguards = {}, {}, {}
    for filename in [config['run']['seed_manifest'], *config['run'].get('additional_seed_manifests', [])]:
        path = Path(filename)
        if not path.is_absolute():
            path = ROOT / path
        manifest_ref = reference(path)
        safeguards[manifest_ref['path']] = manifest_ref
        for seed in read(manifest_ref)['selected']:
            seeds[seed['sha256']] = seed
    for identity, seed in seeds.items():
        proof = cohort.validate_seed(seed)
        require(proof == seed.get('finance_evidence', {}).get('audited_source_binding'),
                'Original complete financial source admission changed')
        source = reference(seed['local_path'])
        require(source['sha256'] == identity, 'Scope source identity changed')
        source_bindings[identity] = {'source': source, 'audited_source_binding': proof}
        collect_references(proof, safeguards)
    tasks, review_refs, missing = {}, [], []
    for task_id in selected_ids:
        task = tasks_by_id[task_id]
        revision = int(task.get('revision', 0))
        require(revision < config['run']['max_steps'], 'Normal content-repair budget is exhausted')
        source_id = task['source_id']
        require(source_id in seeds, 'Task immutable source is absent from original admissions')
        private = run / 'tasks' / task_id / 'revisions' / f'{revision:03d}' / 'private'
        public = private.parent / 'public'
        paths = {'plan': private / 'plan.json', 'input': public / 'input.xlsx',
            'instruction': public / 'instruction.md', 'goal': private / 'goal.xlsx',
            'baseline': run / 'sources' / source_id[:12] / 'baseline.xlsx'}
        artifacts = {key: reference(path) for key, path in paths.items()}
        require(artifacts['baseline']['sha256'] == artifacts['goal']['sha256'] == source_id,
                'Scope repair cannot change the audited source, baseline or goal')
        revision_hash = hashlib.sha256(checked_bytes(artifacts['input']) + checked_bytes(artifacts['instruction'])).hexdigest()
        matching = []
        for review_ref in reviews:
            try:
                basis = scope_review(review_ref, task_id, revision, revision_hash, artifacts['instruction'],
                                     verifier_contract=verifier_contract)
            except ValueError:
                continue
            matching.append((review_ref, basis))
        require(len(matching) == 1, 'Task needs exactly one current or byte-identical public-scope review')
        review_ref, basis = matching[0]
        issue = issue_for(task_id, revision, revision_hash, review_ref, artifacts['instruction'])
        program_path = output / 'tasks' / task_id / 'program_review.json'
        program_ref = write_new(program_path, {'kind': 'numbered_program_public_scope_review',
            'task_id': task_id, 'revision': revision, 'revision_hash': revision_hash, 'issues': [issue],
            'transferred_same_wording_scope_only': basis['task_id'] != task_id,
            'frozen_verifier_contract': verifier_contract,
            'old_quality_or_financial_findings_transferred': False,
            'source_sha256': source_id, 'quality_or_difficulty_certified': False})
        review_refs.append(program_ref)
        diagnosis_path = private / 'diagnosis.json'
        if diagnosis_path.exists():
            diagnosis_ref = reference(diagnosis_path)
            require(read(diagnosis_ref).get('task_revision_hash') == revision_hash,
                    'Existing diagnosis belongs to another public revision')
        else:
            require(task.get('status') == 'cancelled',
                    'A missing diagnosis is allowed only after a genuine cancelled task is terminal')
            template = write_new(output / 'tasks' / task_id / 'program_only_diagnosis.json',
                unknown_repair_basis(task_id, revision, revision_hash, issue))
            diagnosis_ref = {**template, 'path': str(diagnosis_path.resolve())}
            missing.append({'task_id': task_id, 'revision': revision,
                            'target': diagnosis_ref, 'template': template})
        tasks[task_id] = {'revision': revision, 'revision_hash': revision_hash,
            'source_sha256': source_id, **artifacts, 'diagnosis': diagnosis_ref,
            'program_review': program_ref, 'authorized_issue_ids': [issue['issue_id']]}
        collect_references(basis, safeguards)
        material = basis.get('actual_materiality', {}).get('recalculation_receipt')
        if material:
            collect_references(read(material), safeguards)
        collect_references(artifacts, safeguards)
        if diagnosis_path.exists():
            safeguards[diagnosis_ref['path']] = diagnosis_ref
    manifest_ref = write_new(output / 'policy_binding.json', {
        'kind': 'public_workbook_scope_binding', 'version': VERSION, 'clauses': CLAUSES,
        'sources': source_bindings, 'tasks': tasks, 'quality_or_difficulty_certified': False})
    patch = {'pipeline': {**config.get('pipeline', {}), 'node_registry': str(REGISTRY)},
             POLICY: {'version': VERSION, 'manifest': manifest_ref}}
    patch_ref = write_new(output / 'config_patch.json', patch)
    (output / 'resolved_config_before.yaml').write_bytes(checked_bytes(config_ref))
    recipe_paths = [Path(__file__).resolve(), REGISTRY, base_registry,
        ROOT / 'src/sheets_factory/task_adapters/public_workbook_scope.py',
        ROOT / 'scripts/resume_public_contract_quality.py', Path(cohort.__file__), Path(cleanup.__file__),
        ROOT / 'src/sheets_factory/task_adapters/public_input_priority.py',
        ROOT / 'src/sheets_factory/evaluation/harbor.py',
        ROOT / 'src/sheets_factory/evaluation/standalone_verifier.py',
        ROOT / 'config/checkers.yaml', ROOT / 'config/routes.yaml',
        ROOT / 'src/sheets_factory/resume.py', ROOT / 'src/sheets_factory/pipelines/factory.py']
    prepared = {str(path.resolve()): reference(path) for path in output.rglob('*') if path.is_file()}
    for item in reviews:
        safeguards[item['path']] = item
    priority.original_recipe(run)
    require(reference(config_path) == config_ref, 'Original resolved config changed during preparation')
    frozen = {'kind': 'prepared_public_workbook_scope_continuation',
        'prepared_at': datetime.now(timezone.utc).isoformat(), 'run_directory': str(run),
        'original_preflight': reference(run / 'preflight_manifest.json'),
        'resolved_config_before': config_ref, 'base_node_registry': base_ref,
        'new_recipe': [reference(path) for path in dict.fromkeys(recipe_paths)],
        'original_recipe_sha256': old_frozen['recipe_sha256'],
        'prepared_artifacts': list(prepared.values()), 'safeguard_artifacts': list(safeguards.values()),
        'repair_task_ids': selected_ids, 'review_files': review_refs, 'missing_diagnoses': missing,
        'policy_manifest': manifest_ref, 'config_patch': patch_ref,
        'targets': config['run']['targets'], 'agents': config['agents'],
        'protected_budget_configuration': {key: config['run'].get(key) for key in PROTECTED_BUDGETS},
        'diagnosis_configuration': deepcopy(config.get('diagnosis', {})),
        'checker_plan': checker_plan,
        'preparation_host_runtime': preparation_host, 'old_run_modified_by_preparation': False,
        'actual_models': 0, 'actual_LO_calls': 0, 'qualified': 0,
        'old_official_scores_and_quality_reports_unchanged': True,
        'retest_old_revision': False, 'requires_new_revision_all_normal_gates': True}
    write_new(output / 'preflight_manifest.json', frozen)
    return frozen


def validate_prepared(output):
    output = Path(output).resolve()
    frozen = json.loads((output / 'preflight_manifest.json').read_text())
    require(frozen.get('kind') == 'prepared_public_workbook_scope_continuation', 'Unexpected scope preparation')
    for group in ('new_recipe', 'prepared_artifacts', 'safeguard_artifacts'):
        for record in frozen[group]:
            checked_bytes(record)
    for path, expected in frozen['original_recipe_sha256'].items():
        require(reference(path)['sha256'] == expected, 'Frozen original recipe changed')
    checked_bytes(frozen['original_preflight']); checked_bytes(frozen['resolved_config_before'])
    manifest = read(frozen['policy_manifest'])
    require(manifest.get('clauses') == CLAUSES and type(manifest.get('version')) is int
            and manifest['version'] == VERSION
            and manifest.get('quality_or_difficulty_certified') is False, 'Scope policy changed')
    for task_id, auth in manifest['tasks'].items():
        for key in ('plan', 'baseline', 'goal', 'input', 'instruction', 'program_review'):
            checked_bytes(auth[key])
        missing = next((item for item in frozen['missing_diagnoses'] if item['task_id'] == task_id), None)
        if missing:
            require(not Path(auth['diagnosis']['path']).exists(), 'Diagnosis arrived after preparation; prepare again')
            checked_bytes(missing['template'])
        else:
            checked_bytes(auth['diagnosis'])
    return frozen


def execute(output, *, port=0):
    output = Path(output).resolve()
    frozen = validate_prepared(output)
    run = Path(frozen['run_directory'])
    with ProducerLease(run):
        snapshot = read_run(run)
        assert_resume_allowed(run, snapshot)
        current = {task['id']: task for task in snapshot['tasks']}
        manifest = read(frozen['policy_manifest'])
        for task_id, auth in manifest['tasks'].items():
            require(current[task_id].get('revision') == auth['revision'], 'Task revision changed after scope preparation')
        for item in frozen['missing_diagnoses']:
            require(current[item['task_id']].get('status') == 'cancelled', 'Missing diagnosis task is no longer cancelled')
            target = Path(item['target']['path'])
            require(not target.exists(), 'Never replace a completed diagnosis')
            with target.open('xb') as stream:
                stream.write(checked_bytes(item['template']))
            require(reference(target) == item['target'], 'Program-only repair basis differs')
    settings, legacy = cohort.prepared_host_runtime(run)
    with cohort.host_temporary_environment(run, settings, legacy_preparation=legacy) as host:
        revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True,
                                  text=True, check=True).stdout.strip()
        session = prepare_resume(run, config_patch=read(frozen['config_patch']),
            repair_tasks=frozen['repair_task_ids'], review_files=[item['path'] for item in frozen['review_files']],
            current_code_revision=revision,
            reason='Clarify existing public workbook submission scope through new Q03 revisions; preserve financial source, score policy, quotas and budgets')
        audit, config, lease = session.audit, session.config, session.lease
        server, status, started = None, 1, time.monotonic()
        previous = audit.run.get('previous_wall_seconds')
        if previous is None:
            previous = audit.run.get('wall_seconds', 0) or 0
        try:
            require(config['run']['targets'] == frozen['targets'] and config['agents'] == frozen['agents']
                    and config.get('diagnosis', {}) == frozen['diagnosis_configuration']
                    and all(config['run'].get(key) == value for key, value in frozen['protected_budget_configuration'].items()),
                    'Scope continuation changed quotas, agents, diagnosis checks or budgets')
            cid = config['run']['continuation_id']
            private = run / 'private/resume'
            addendum = {'kind': 'public_workbook_scope_continuation',
                'preparation': reference(output / 'preflight_manifest.json'),
                'config_before': reference(private / f'resolved_config_before_{cid}.yaml'),
                'config_after': reference(private / f'resolved_config_after_{cid}.yaml'),
                'current_resolved_config': reference(run / 'resolved_config.yaml'),
                'preparation_config_hash_is_historical': True,
                'repair_task_ids': frozen['repair_task_ids'], 'clauses': CLAUSES,
                'old_diagnostics_cleared': False, 'old_official_scores_changed': False,
                'new_revisions_consume_normal_content_repair_budget': True,
                'normal_five_controls_recovery_all12_diagnostics_and_actual_harbor_required': True,
                'missing_program_only_bases_created': [item['target'] for item in frozen['missing_diagnoses']],
                'quality_or_difficulty_certified': False}
            addendum_ref = write_new(run / 'runtime_supplements' / ('public_scope_continuation_' + cid + '.json'), addendum)
            audit.emit('run.public_workbook_scope', addendum=addendum_ref)
            server = cohort.DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port)
            url = server.start()
            audit.update_run(dashboard_url=url, host_temporary_directory=host['temporary_directory'], host_runtime_receipt=host)
            llm = cohort.CohortCodex(ROOT, run, audit, config['agents']); llm._credentials()
            engine = cohort.LibreOfficeEngine(ROOT, cohort.IMAGE, config['engine']['timeout_seconds'])
            require(engine.metadata()['image_id'] == cohort.IMAGE_ID, 'Scope continuation runtime differs')
            print(json.dumps({'run_dir': str(run), 'dashboard_url': url, 'phase_addendum': addendum_ref}), flush=True)
            status = 0 if cohort.AuditedSourceFactory(config, audit, llm, engine).run() else 2
            for record in frozen['safeguard_artifacts']:
                checked_bytes(record)
            priority.original_recipe(run)
            return status
        finally:
            cleanup.finalize_execution(audit, server, session, lease,
                phase_wall=round(time.monotonic() - started, 3), previous_wall=previous, status=status)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-directory', type=Path)
    parser.add_argument('--scope-review', type=Path, action='append', default=[])
    parser.add_argument('--task-id', action='append', default=[])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    if args.prepared:
        require(not any((args.run_directory, args.scope_review, args.task_id, args.output)),
                'Prepared continuation cannot replace frozen bindings')
        output = args.prepared
        if not args.run:
            validate_prepared(output)
    else:
        require(args.run_directory and args.scope_review and args.output,
                'Preparation needs a run directory, public-scope review and fresh output')
        output = args.output
        prepare(args.run_directory, args.scope_review, output, task_ids=args.task_id)
    if args.run:
        return execute(output, port=args.port)
    print(json.dumps({'prepared': str(output.resolve()), 'models_started': 0, 'LO_calls': 0, 'qualified': 0}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
