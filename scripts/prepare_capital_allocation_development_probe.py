#!/usr/bin/env python3
"""Snapshot actual capital FM bytes after normal construction and five controls."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from sheets_factory.evaluation.budget import validate_execution_budget, validate_selection_execution_budget
from sheets_factory.evaluation.harbor import inspect_export
from sheets_factory.evaluation.tool_time_bounds import POLICY_V2
from sheets_factory.nodes.construction import InstructionNode
from sheets_factory.nodes.quality import ExportNode, _valid_recovery_witness
from sheets_factory.reporting import read_run
from sheets_factory.task_adapters.public_workbook_scope import CLAUSES, canonical, read as read_ref, reference, require, write_new
from sheets_factory.workbook import compare_workbooks

_phase_spec = importlib.util.spec_from_file_location('_capital_probe_quality_phase', ROOT / 'scripts/run_capital_allocation_quality.py')
phase = importlib.util.module_from_spec(_phase_spec); _phase_spec.loader.exec_module(phase)
NORMAL_NODES = ('normalize', 'profile', 'plan', 'construct', 'instruction', 'precheck')
CONTROL_REWARDS = {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}
BUDGET = {'version': 1, 'elapsed_policy': 'operational_guard', 'elapsed_guard_seconds': 14400, 'tool_budget_seconds': 1800}
EXPECTED_TARGETS = 19049


def read(path): return json.loads(Path(path).read_bytes())
def sha(path): return reference(path)['sha256']


def require_completed_nodes(snapshot, task_id, revision):
    latest = {}
    for record in snapshot['nodes']:
        if record.get('task_id') == task_id and record.get('revision') == revision:
            latest[record['node']] = record
    for name in NORMAL_NODES:
        require(latest.get(name, {}).get('status') == 'completed', 'Normal capital FM node has not completed at this revision: ' + name)
    return latest


def development_history(revision_hash, directories):
    result, seen = [], set()
    for directory in directories:
        root = Path(directory)
        paths = [root] if root.is_file() else sorted(root.rglob('selection_manifest.json'))
        for path in paths:
            path = path.absolute()
            if str(path) in seen: continue
            seen.add(str(path)); previous = read(path)
            require(all(task.get('revision_hash') != revision_hash for task in previous.get('tasks', [])),
                    'These public revision bytes already have a model selection. Do not resample them.')
            result.append(reference(path))
    return result


def validate_plan_binding(plan, application, scope, proof, binding):
    edits = plan.get('edits')
    required = {(item['sheet'], item['cell']) for item in binding['financial_bindings'] + binding['decision_bindings']}
    helpers = {(item['sheet'], item['cell']) for item in binding['arithmetic_bindings']}
    actual = [(edit['sheet'], edit['cell']) for edit in edits] if isinstance(edits, list) else []
    require(len(binding['financial_bindings']) == 19031 and len(binding['decision_bindings']) == 18
            and len(actual) == len(set(actual)) == len(required) == EXPECTED_TARGETS and set(actual) == required
            and not required & helpers and all(edit.get('after') is None and isinstance(edit.get('before'), str)
                                              and edit['before'].startswith('=') for edit in edits),
            'Exactly all 19031 financial formulas and eighteen shared decisions must be masked')
    physical = [{key: edit[key] for key in ('sheet', 'cell', 'before', 'after')} for edit in edits]
    adapter = plan.get('family_adapter', {})
    require(adapter.get('id') == 'capital_allocation_fm_v1'
            and adapter.get('source_manifest') == proof['source_manifest']
            and adapter.get('source_sha256') == proof['workbook']['sha256']
            and adapter.get('bindings') == proof['bindings']
            and adapter.get('financial_target_count') == 19031 and adapter.get('decision_target_count') == 18
            and adapter.get('physical_target_count') == EXPECTED_TARGETS
            and adapter.get('provided_arithmetic_count') == len(helpers)
            and adapter.get('helper_values_are_protected') is False
            and adapter.get('full_workbook_D_required') is True
            and not plan.get('scenario_inputs') and 'mask_ranges' not in plan,
            'The complete admitted capital source or forward-accounting scope changed')
    require(application.get('source_manifest') == proof['source_manifest'] and application.get('source') == proof['workbook']
            and application.get('physical_edits_sha256') == canonical(physical)
            and application.get('physical_target_count') == EXPECTED_TARGETS
            and application.get('quality_or_difficulty_certified') is False,
            'The normal capital Plan binding differs from this exact source and physical plan')
    required_cleared = sum(item.get('plan_dependent') is True for item in binding['arithmetic_bindings'])
    cleared_labels = [item['sheet'] + '!' + item['cell'] for item in binding['arithmetic_bindings'] if item.get('plan_dependent') is True]
    require(scope.get('passed') is True and scope.get('masked_financial_and_decision_count') == EXPECTED_TARGETS
            and scope.get('provided_helper_formula_count') == len(helpers)
            and scope.get('plan_dependent_caches_cleared_count') == required_cleared
            and scope.get('cleared_support_coordinates_sha256') == canonical(cleared_labels)
            and adapter.get('plan_dependent_support_count') == required_cleared
            and scope.get('unselected_definitions_and_public_primitives_unchanged') is True
            and scope.get('helpers_physically_masked') is False and scope.get('helper_values_protected') is False
            and scope.get('no_helper_values_excluded_from_required_D') is True
            and scope.get('actual_recalculation_delegated_to_ordinary_construct') is True
            and scope.get('normal_construct_implementation') == reference(ROOT / 'src/sheets_factory/nodes/construction.py'),
            'The actual input lacks complete cache-clearance, source-preservation or full-D proof')
    require(CLAUSES['financial_modeling'] in plan.get('public_instruction', ''), 'The actual public capital scope is incomplete')
    return required, helpers


def validate_preparation(run):
    frozen, config, proof = phase.validate_prepared(run)
    seeds = read_ref(frozen['prepared_seed_manifest'])['selected']
    require(frozen.get('kind') == phase.KIND and frozen.get('development_only') is True
            and frozen.get('profile_id') == 'K01' and len(seeds) == 1
            and seeds[0].get('source_kind') == phase.admission.SOURCE_KIND,
            'Only the original first capital-allocation FM development admission is supported')
    return frozen, config, seeds[0], proof


def freeze_probe(run, task_id, revision, output, *, history_roots=None):
    run, output = Path(run).absolute(), Path(output).absolute()
    require(run == run.resolve() and output == output.resolve() and not output.exists(), 'Use a fresh non-symlink snapshot directory')
    require(isinstance(task_id, str) and Path(task_id).name == task_id and task_id not in {'.', '..'}
            and type(revision) is int and revision >= 0, 'Unsafe task ID or revision')
    frozen, config, seed, proof = validate_preparation(run)
    snapshot = read_run(run); tasks = [task for task in snapshot['tasks'] if task['id'] == task_id]
    require(len(tasks) == 1 and tasks[0].get('mode') == 'financial_modeling'
            and tasks[0].get('revision') == revision and tasks[0].get('source_id') == seed['sha256'],
            'This is not the current actual predeclared capital FM candidate')
    nodes = require_completed_nodes(snapshot, task_id, revision)
    directory = run / 'tasks' / task_id / 'revisions' / f'{revision:03d}'
    public, private = directory / 'public', directory / 'private'
    plan = read(private / 'plan.json'); application = read(private / 'capital_allocation_plan_binding.json')
    scope = read(private / 'capital_allocation_actual_input_scope.json'); binding = read_ref(proof['bindings'])
    targets, helpers = validate_plan_binding(plan, application, scope, proof, binding)
    source, goal = public / 'input.xlsx', private / 'goal.xlsx'
    require(sha(goal) == seed['sha256'] == proof['workbook']['sha256'] == sha(seed['local_path']),
            'The actual normal goal is not the independently audited source')
    require(scope['input'] == reference(source) and scope['goal'] == reference(goal)
            and scope['actual_normal_draft'] == reference(private / 'mutated_unrecalculated.xlsx'),
            'The input scope proof belongs to other task bytes')
    instruction = (public / 'instruction.md').read_text(encoding='utf-8')
    require(CLAUSES['financial_modeling'] in instruction, 'Actual public instructions omit the exact worksheet and helper scope')
    revision_hash = hashlib.sha256(source.read_bytes() + instruction.encode()).hexdigest()
    history = development_history(revision_hash, [ROOT / 'outputs/difficulty', *(history_roots or [])])
    stored = read(private / 'local_controls.json')
    require(set(stored) == set(CONTROL_REWARDS), 'All five actual normal local controls are required')
    for name, expected in CONTROL_REWARDS.items():
        candidate = goal if name == 'oracle' else source if name == 'nop' else private / 'controls' / (name + '.xlsx')
        actual = compare_workbooks(source, goal, candidate)
        require(actual == stored[name] and type(actual.get('reward')) is int and actual['reward'] == expected,
                'An actual normal local control failed or changed: ' + name)
    delta = read(private / 'expected_delta.json')
    changed = set(delta['expected_changes']); target_labels = {sheet + '!' + cell for sheet, cell in targets}
    helper_labels = {sheet + '!' + cell for sheet, cell in helpers}
    require(delta == stored['oracle'] and target_labels <= changed
            and scope.get('complete_required_D_count') == delta['expected_change_count']
            and scope.get('changed_helper_count') == len(changed & helper_labels),
            'The complete actual required D was reduced or omits changed arithmetic support')
    require(read(private / 'native_risk_guard.json')['blocking'] is False
            and read(private / 'native_error_probe.json')['blocking'] is False, 'A normal native calculation guard is blocking')
    fixed = [source, goal, public / 'instruction.md', public / 'profile.json',
        *[private / name for name in ('plan.json', 'expected_delta.json', 'edit_validation.json', 'root_impacts.json',
            'native_risk_guard.json', 'native_error_probe.json', 'local_controls.json',
            'capital_allocation_plan_binding.json', 'capital_allocation_actual_input_scope.json', 'mutated_unrecalculated.xlsx')],
        *[private / 'controls' / (name + suffix) for name in ('equivalent', 'missed_root', 'extra_change') for suffix in ('_raw.xlsx', '.xlsx')],
        run / 'preflight_manifest.json', run / 'resolved_config.yaml', run / 'seed_manifest.json',
        Path(__file__).resolve(), ROOT / 'src/sheets_factory/nodes/construction.py',
        ROOT / 'src/sheets_factory/nodes/quality.py', ROOT / 'src/sheets_factory/evaluation/harbor.py',
        ROOT / 'src/sheets_factory/evaluation/standalone_verifier.py']
    bindings = {str(path.resolve()): sha(path) for path in fixed}
    bindings.update(frozen['recipe_sha256']); bindings.update(frozen['source_artifacts_sha256'])
    phase.bind_transitive([proof, application, scope], bindings)
    recovery_ok, recovery_ref, recovery_status = False, None, 'pending'
    if nodes.get('independent_recovery', {}).get('status') == 'completed':
        recovery_ref = reference(private / 'independent_recovery.json'); recovery = read_ref(recovery_ref)
        context = SimpleNamespace(task_id=task_id, revision=revision, revision_dir=directory, config=config,
            data={'input': source, 'goal': goal, 'instruction': instruction, 'revision_hash': revision_hash,
                  'public_profile': read(public / 'profile.json')})
        recovery_ok = _valid_recovery_witness(context, recovery)
        require(recovery.get('verified') is not True or recovery_ok, 'An asserted completed recovery witness has invalid revision or artifact bindings')
        recovery_status = 'verified' if recovery_ok else 'completed_without_verified_witness'
        phase.bind_transitive(recovery_ref, bindings)
    output.mkdir(parents=True)
    node_receipts = write_new(output / 'normal_node_receipts.json', {'as_of': datetime.now(timezone.utc).isoformat(),
        'task_id': task_id, 'revision': revision, 'run_status': snapshot['run']['status'], 'nodes': nodes,
        'new_LO_calls': 0, 'new_model_calls': 0})
    replay = output / 'normal_instruction_replay'; (replay / 'public').mkdir(parents=True)
    generated = InstructionNode().execute(SimpleNamespace(data={'plan': plan, 'input': source}, mode='financial_modeling',
        config=config, revision_dir=replay))
    require(generated['instruction'] == instruction and generated['revision_hash'] == revision_hash,
            'Normal InstructionNode replay differs from the actual task bytes')
    copied = deepcopy(config); copied['run_dir'] = str(output)
    lineage = output / 'private' / task_id; lineage.mkdir(parents=True)
    target = ExportNode().execute(SimpleNamespace(task_id=task_id, mode='financial_modeling', source=Path(seed['local_path']),
        revision=revision, revision_dir=directory, directory=lineage, config=copied,
        data={'source_id': seed['sha256'], 'revision_hash': revision_hash}))['export_dir']
    export_binding = inspect_export(target)
    require((target / 'instruction.md').read_bytes() == (public / 'instruction.md').read_bytes()
            and sha(target / 'environment/input.xlsx') == sha(source) and sha(target / 'tests/reference.xlsx') == sha(goal),
            'The normal export differs from actual public or private task bytes')
    for item in (node_receipts, reference(replay / 'public/instruction.md')): bindings[item['path']] = item['sha256']
    budget = validate_execution_budget(BUDGET)
    task = {'task_id': task_id, 'mode': 'financial_modeling', 'source_id': seed['sha256'], 'revision': revision,
        'revision_hash': revision_hash, 'source_kind': 'prequality_development_probe',
        'difficulty_status': 'prequality_development_probe', 'base_image': config['engine']['image'],
        'task_directory': str(target), 'harbor_export_binding': export_binding, 'local_controls': CONTROL_REWARDS,
        'execution_budget': budget, 'timeout_seconds': budget['elapsed_guard_seconds'], 'tool_time_policy': dict(POLICY_V2)}
    manifest = {'kind': 'prequality_development_probe', 'schema_version': 1, 'source_kind': 'prequality_development_probe',
        'frozen_at': datetime.now(timezone.utc).isoformat(), 'selected_task_ids': [task_id], 'tasks': [task],
        'execution_budget': budget, 'timeout_seconds': budget['elapsed_guard_seconds'], 'tool_time_policy': dict(POLICY_V2),
        'tool_time_policy_version': 2, 'source_artifacts_sha256': bindings, 'main_quality_run': str(run),
        'normal_node_receipts': node_receipts, 'normal_InstructionNode_replay_exact': True,
        'normal_ExportNode_called_on_actual_task': True, 'capital_source_admission': proof,
        'physical_missing_formula_count': len(targets), 'financial_target_count': 19031, 'shared_decision_count': 18,
        'complete_changed_value_set_count': len(changed), 'changed_arithmetic_helper_count': len(changed & helper_labels),
        'all_changed_helper_values_in_required_D': True, 'prior_model_selection_inventory': history,
        'independent_recovery_verified_at_snapshot': recovery_ok, 'independent_recovery_status': recovery_status,
        'independent_recovery_receipt': recovery_ref, 'diagnosis_status_at_snapshot': nodes.get('diagnose', {}).get('status', 'pending'),
        'quality_status': 'Five normal local controls passed; public recovery, all twelve diagnostics and actual Harbor have separate statuses and remain required.',
        'new_harbor_control_jobs_launched_during_preparation': False, 'qualified': False, 'task_count': 0,
        'model_evaluation_performed': False, 'new_model_calls_during_preparation': 0, 'new_LO_calls_during_preparation': 0}
    validate_selection_execution_budget(manifest)
    phase.verify_files(bindings)
    current = read_run(run)
    require(next(item for item in current['tasks'] if item['id'] == task_id)['revision'] == revision,
            'The actual task revision advanced during snapshot')
    return write_new(output / 'probe_manifest.json', manifest)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True); parser.add_argument('--task-id', required=True)
    parser.add_argument('--revision', type=int, default=0); parser.add_argument('--output', type=Path)
    parser.add_argument('--freeze', action='store_true'); parser.add_argument('--history-root', type=Path, action='append', default=[])
    args = parser.parse_args(argv)
    if args.freeze:
        require(args.output is not None, 'A fresh snapshot output is required')
        result = freeze_probe(args.run, args.task_id, args.revision, args.output, history_roots=args.history_root)
    else:
        require(args.output is None, 'Use explicit --freeze to create a snapshot')
        snapshot = read_run(args.run)
        try: require_completed_nodes(snapshot, args.task_id, args.revision); ready = True
        except ValueError: ready = False
        result = {'ready_for_snapshot': ready, 'run_status': snapshot['run']['status'], 'LO_calls': 0, 'model_calls': 0}
    print(json.dumps(result, indent=2)); return 0


if __name__ == '__main__': raise SystemExit(main())
