#!/usr/bin/env python3
"""Snapshot actual full-state FM artifacts after all five normal local controls."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.evaluation.budget import validate_execution_budget, validate_selection_execution_budget
from sheets_factory.evaluation.harbor import inspect_export
from sheets_factory.evaluation.tool_time_bounds import POLICY_V2
from sheets_factory.nodes.construction import InstructionNode
from sheets_factory.nodes.quality import ExportNode, _valid_recovery_witness
from sheets_factory.reporting import read_run
from sheets_factory.task_adapters import composite_full_state_fm as provider
from sheets_factory.task_adapters.public_workbook_scope import (
    CLAUSES, canonical, checked_bytes, read as read_ref, reference, require, write_new,
)
from sheets_factory.task_adapters.public_input_priority import RULE
from sheets_factory.workbook import compare_workbooks

NORMAL_NODES = ('normalize', 'profile', 'plan', 'construct', 'instruction', 'precheck')
CONTROL_REWARDS = {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}
BUDGET = {'version': 1, 'elapsed_policy': 'operational_guard',
          'elapsed_guard_seconds': 14400, 'tool_budget_seconds': 1800}
EXPECTED_TARGETS = 60193


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return reference(path)['sha256']


def require_completed_nodes(snapshot, task_id, revision):
    latest = {}
    for record in snapshot['nodes']:
        if record.get('task_id') == task_id and record.get('revision') == revision:
            latest[record['node']] = record
    for name in NORMAL_NODES:
        require(latest.get(name, {}).get('status') == 'completed',
                'Normal full-state FM node has not completed at this revision: ' + name)
    return latest


def development_history(revision_hash, directories):
    result = []
    seen = set()
    for root in directories:
        root = Path(root)
        files = [root] if root.is_file() else sorted(root.rglob('selection_manifest.json'))
        for path in files:
            if str(path.resolve()) in seen:
                continue
            seen.add(str(path.resolve()))
            previous = read(path)
            require(all(task.get('revision_hash') != revision_hash for task in previous.get('tasks', [])),
                    'These public revision bytes already have a model selection. Do not resample them.')
            result.append(reference(path))
    return result


def validate_plan_application(plan, application, source_sha):
    edits = plan.get('edits')
    require(isinstance(edits, list) and len(edits) == EXPECTED_TARGETS,
            'The normal full-state FM plan must contain exactly 60193 asserted edits')
    keys = {(edit['sheet'], edit['cell']) for edit in edits}
    require(len(keys) == len(edits) and all(edit.get('after') is None
            and isinstance(edit.get('before'), str) and edit['before'].startswith('=') for edit in edits),
            'The full-state FM edit list is not a unique existing-formula mask')
    selection = plan.get('full_state_fm_selection', {})
    require(type(selection.get('version')) is int and selection['version'] == provider.VERSION
            and selection.get('target_count') == EXPECTED_TARGETS
            and selection.get('original_financial_target_count') == 46339
            and selection.get('additional_state_target_count') == 13854
            and selection.get('original_financial_targets_preserved_exactly') is True
            and selection.get('all_targets_sha256') == canonical(sorted(keys))
            and selection.get('quality_or_difficulty_certified') is False,
            'The actual plan differs from the predeclared full-state target policy')
    receipt = plan.get('range_authoring_receipt', {})
    require(receipt.get('baseline_sha256') == source_sha and receipt.get('source_workbook_modified') is False
            and receipt.get('expanded_edit_count') == EXPECTED_TARGETS,
            'The full-state mask compilation is not bound to the exact source')
    proposal = deepcopy(plan)
    proposal.pop('range_authoring_receipt')
    proposal['edits'] = []
    proposal['mask_ranges'] = [group['proposal'] for group in receipt['groups']]
    require(provider.mask_cells(proposal) == keys, 'Compiled full-state targets differ from their original rectangles')
    require(application.get('kind') == 'full_state_FM_original_audit_target_coverage'
            and application.get('source', {}).get('sha256') == source_sha
            and application.get('target_count') == EXPECTED_TARGETS
            and application.get('plan_sha256') == canonical(proposal)
            and application.get('all_targets_independently_audited') is True
            and application.get('quality_or_difficulty_certified') is False,
            'The normal Plan application proof does not bind the exact compiled plan')
    coverage = application.get('cell_proofs', [])
    require(len(coverage) == EXPECTED_TARGETS
            and {(row['sheet'], row['cell']) for row in coverage} == keys
            and set(application.get('audits', {})) == {'lease', 'programme', 'operating', 'holding', 'contingent'},
            'The normal Plan proof lacks complete original five-audit target coverage')
    require(CLAUSES['financial_modeling'] in plan['public_instruction'] and RULE in plan['public_rules']
            and set(provider.STATE_RULES) <= set(plan['public_rules'])
            and 'existing nonmonetary state helpers' not in plan['public_instruction'],
            'The actual full-state public scope or state encoding rules differ')
    return keys


def validate_preparation(run):
    frozen = read(run / 'preflight_manifest.json')
    require(frozen.get('kind') == 'prepared_full_state_financial_development_quality'
            and type(frozen.get('count')) is int and frozen['count'] == 1
            and frozen.get('development_only') is True, 'A first-source full-state development admission is required')
    for name in ('recipe_sha256', 'source_artifacts_sha256'):
        for path, expected in frozen[name].items():
            require(sha(path) == expected, 'Frozen full-state admission artifact changed: ' + path)
    config = yaml.safe_load(checked_bytes(frozen['resolved_config']))
    seed_manifest = read_ref(frozen['prepared_seed_manifest'])
    selected = seed_manifest['selected']
    require(len(selected) == 1 and selected[0]['sha256'] == frozen['selected_source_sha256']
            and config['run']['targets'] == {'financial_modeling': 1, 'debugging': 0},
            'The development candidate is not the one predeclared FM source')
    policy = config.get(provider.POLICY)
    require(policy == frozen['full_state_policy'], 'The full-state policy changed after admission')
    provider.load_policy(policy['policy'])
    registry = Path(config['pipeline']['node_registry'])
    require(str(registry) in frozen['recipe_sha256']
            and yaml.safe_load(registry.read_text())['nodes'] == yaml.safe_load(
                (ROOT / 'config/task_adapters/composite_full_state_fm_nodes.yaml').read_text())['nodes'],
            'The development run does not retain the normal full-state node registry')
    return frozen, config, selected[0]


def bind_references(value, bindings):
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            actual = reference(value['path'])
            checked_bytes({**actual, **value})
            bindings[actual['path']] = actual['sha256']
        for child in value.values():
            bind_references(child, bindings)
    elif isinstance(value, list):
        for child in value:
            bind_references(child, bindings)


def bind_offline_admission(path, source_sha, plan, bindings):
    admission = read(path)
    require(admission.get('kind') == 'prospective_full_state_FM_fixed_ten_offline_admission'
            and len(admission.get('sources', [])) == 10
            and admission.get('all_ten_financial_target_sets_preserved_exactly') is True
            and admission.get('all_13854_added_states_per_source_originally_audited_and_publicly_recomputable') is True
            and admission.get('quality_or_difficulty_certified') is False,
            'The frozen ten-source offline coverage proof is required')
    bind_references(admission['code'], bindings)
    require(any(ref['path'] == str(Path(provider.__file__).resolve()) and ref['sha256'] == sha(provider.__file__)
                for ref in admission['code']), 'Offline coverage used another full-state provider')
    matches = [row for row in admission['sources'] if row['source']['sha256'] == source_sha]
    require(len(matches) == 1 and matches[0]['selection'] == plan['full_state_fm_selection'],
            'The actual plan differs from its source-specific offline proof')
    bind_references(matches[0], bindings)
    states = read_ref(matches[0]['added_state_cell_proofs'])
    bind_references(states, bindings)
    require(states.get('state_cell_count') == 13854
            and states.get('all_added_states_have_public_independent_ledger_binding_equal_original_audit_expected') is True
            and states.get('all_added_states_match_normalized_source_caches') is True
            and states.get('new_actual_recovery_or_controls_completed') is False,
            'The added state cells lack independent public writer coverage')
    keys = [(row['sheet'], row['cell']) for row in states['cell_proofs']]
    require(len(keys) == len(set(keys)) == 13854
            and canonical(sorted(keys)) == plan['full_state_fm_selection']['additional_state_targets_sha256'],
            'The added state-cell proof has missing, extra or duplicate coordinates')
    bindings[str(Path(path).resolve())] = sha(path)
    return reference(path)


def freeze_probe(run, task_id, revision, output, *, offline_admission, history_roots=None):
    run, output = Path(run).absolute(), Path(output).absolute()
    require(run == run.resolve() and output == output.resolve() and not output.exists(),
            'Use a fresh, non-symlink snapshot directory')
    require(isinstance(task_id, str) and Path(task_id).name == task_id and task_id not in {'.', '..'}
            and type(revision) is int and revision >= 0, 'Unsafe task ID or revision')
    frozen, config, seed = validate_preparation(run)
    snapshot = read_run(run)
    tasks = [task for task in snapshot['tasks'] if task['id'] == task_id]
    require(len(tasks) == 1 and tasks[0].get('mode') == 'financial_modeling'
            and tasks[0].get('revision') == revision and tasks[0].get('source_id') == seed['sha256'],
            'The task is not the actual current predeclared FM candidate')
    nodes = require_completed_nodes(snapshot, task_id, revision)
    directory = run / 'tasks' / task_id / 'revisions' / f'{revision:03d}'
    public, private = directory / 'public', directory / 'private'
    plan = read(private / 'plan.json')
    application = read(private / 'composite_full_state_fm_application.json')
    targets = validate_plan_application(plan, application, seed['sha256'])
    require(application['policy'] == config[provider.POLICY]['policy'], 'The Plan proof used a different policy')
    source, goal = public / 'input.xlsx', private / 'goal.xlsx'
    require(sha(goal) == sha(seed['local_path']) == seed['sha256'], 'The normal goal is not the immutable audited source')
    instruction = (public / 'instruction.md').read_text(encoding='utf-8')
    require(CLAUSES['financial_modeling'] in instruction and RULE in instruction
            and all(rule in instruction for rule in provider.STATE_RULES), 'Actual public instructions omit the frozen state conventions')
    revision_hash = hashlib.sha256(source.read_bytes() + instruction.encode()).hexdigest()
    history = development_history(revision_hash, [ROOT / 'outputs/difficulty', *(history_roots or [])])
    stored = read(private / 'local_controls.json')
    require(set(stored) == set(CONTROL_REWARDS), 'All five normal local controls are required')
    for name, expected in CONTROL_REWARDS.items():
        candidate = goal if name == 'oracle' else source if name == 'nop' else private / 'controls' / (name + '.xlsx')
        result = compare_workbooks(source, goal, candidate)
        require(result == stored[name] and type(result.get('reward')) is int and result['reward'] == expected,
                'The actual normal local control failed or changed: ' + name)
    delta = read(private / 'expected_delta.json')
    require(delta['expected_changes'] == stored['oracle']['expected_changes']
            and {sheet + '!' + cell for sheet, cell in targets} <= set(delta['expected_changes']),
            'The complete required D differs from the actual oracle control or omits a masked target')
    require(read(private / 'native_risk_guard.json')['blocking'] is False
            and read(private / 'native_error_probe.json')['blocking'] is False, 'A normal native calculation guard is blocking')
    fixed = [source, goal, public / 'instruction.md', public / 'profile.json',
        *[private / name for name in ('plan.json', 'expected_delta.json', 'edit_validation.json',
          'root_impacts.json', 'native_risk_guard.json', 'native_error_probe.json',
          'local_controls.json', 'composite_full_state_fm_application.json')],
        *[private / 'controls' / (name + '.xlsx') for name in ('equivalent', 'missed_root', 'extra_change')],
        run / 'preflight_manifest.json', run / 'resolved_config.yaml', run / 'seed_manifest.json',
        run / 'sources' / seed['sha256'][:12] / 'stability.json', Path(__file__).resolve(),
        ROOT / 'src/sheets_factory/nodes/construction.py', ROOT / 'src/sheets_factory/nodes/quality.py',
        ROOT / 'src/sheets_factory/evaluation/harbor.py', ROOT / 'src/sheets_factory/evaluation/standalone_verifier.py']
    bindings = {str(path.resolve()): sha(path) for path in fixed}
    bindings.update(frozen['recipe_sha256'])
    bind_references(seed['finance_evidence'], bindings)
    bind_references(application, bindings)
    offline = bind_offline_admission(offline_admission, seed['sha256'], plan, bindings)
    recovered, recovery_ref = False, None
    if nodes.get('independent_recovery', {}).get('status') == 'completed':
        recovery = read(private / 'independent_recovery.json')
        recovery_ctx = SimpleNamespace(task_id=task_id, revision=revision, revision_dir=directory, config=config,
            data={'input': source, 'goal': goal, 'instruction': instruction, 'revision_hash': revision_hash,
                  'public_profile': read(public / 'profile.json')})
        require(_valid_recovery_witness(recovery_ctx, recovery), 'The completed actual recovery witness does not bind this revision')
        recovered, recovery_ref = True, reference(private / 'independent_recovery.json')
        bind_references(recovery['witness_binding']['artifacts'], bindings)
        bindings[recovery_ref['path']] = recovery_ref['sha256']
    output.mkdir(parents=True)
    node_ref = write_new(output / 'normal_node_receipts.json', {'as_of': datetime.now(timezone.utc).isoformat(),
        'task_id': task_id, 'revision': revision, 'run_status': snapshot['run']['status'], 'nodes': nodes,
        'new_LO_calls': 0, 'new_model_calls': 0})
    replay = output / 'normal_instruction_replay'; (replay / 'public').mkdir(parents=True)
    generated = InstructionNode().execute(SimpleNamespace(data={'plan': plan, 'input': source},
        mode='financial_modeling', config=config, revision_dir=replay))
    require(generated['instruction'] == instruction and generated['revision_hash'] == revision_hash,
            'Normal InstructionNode replay differs from the actual public bytes')
    copied_config = deepcopy(config); copied_config['run_dir'] = str(output)
    lineage = output / 'private' / task_id; lineage.mkdir(parents=True)
    target = ExportNode().execute(SimpleNamespace(task_id=task_id, mode='financial_modeling',
        source=Path(seed['local_path']), revision=revision, revision_dir=directory, directory=lineage,
        config=copied_config, data={'source_id': seed['sha256'], 'revision_hash': revision_hash}))['export_dir']
    export_binding = inspect_export(target)
    require((target / 'instruction.md').read_bytes() == (public / 'instruction.md').read_bytes()
            and sha(target / 'environment/input.xlsx') == sha(source)
            and sha(target / 'tests/reference.xlsx') == sha(goal), 'The normal export differs from actual task bytes')
    for ref in (node_ref, reference(replay / 'public/instruction.md')):
        bindings[ref['path']] = ref['sha256']
    budget = validate_execution_budget(BUDGET)
    record = {'task_id': task_id, 'mode': 'financial_modeling', 'source_id': seed['sha256'],
        'revision': revision, 'revision_hash': revision_hash, 'source_kind': 'prequality_development_probe',
        'difficulty_status': 'prequality_development_probe', 'base_image': config['engine']['image'],
        'task_directory': str(target), 'harbor_export_binding': export_binding, 'local_controls': CONTROL_REWARDS,
        'execution_budget': budget, 'timeout_seconds': budget['elapsed_guard_seconds'], 'tool_time_policy': dict(POLICY_V2)}
    manifest = {'schema_version': 1, 'kind': 'prequality_development_probe', 'source_kind': 'prequality_development_probe',
        'frozen_at': datetime.now(timezone.utc).isoformat(), 'selected_task_ids': [task_id], 'tasks': [record],
        'execution_budget': budget, 'timeout_seconds': budget['elapsed_guard_seconds'],
        'tool_time_policy': dict(POLICY_V2), 'tool_time_policy_version': 2,
        'source_artifacts_sha256': bindings, 'main_quality_run': str(run), 'normal_node_receipts': node_ref,
        'normal_InstructionNode_replay_exact': True, 'normal_ExportNode_called_on_actual_task': True,
        'offline_full_state_admission': offline, 'financial_source_evidence': seed['finance_evidence'],
        'normal_full_state_plan_application': reference(private / 'composite_full_state_fm_application.json'),
        'physical_missing_formula_count': len(plan['edits']), 'complete_changed_value_set_count': delta['expected_change_count'],
        'prior_model_selection_inventory': history, 'selection_policy': 'First predeclared source. First development selection of these new full-state public revision bytes.',
        'independent_recovery_verified_at_snapshot': recovered, 'independent_recovery_receipt': recovery_ref,
        'quality_status': 'Five normal local controls passed. Recovery status is separate. All twelve diagnostics and actual Harbor remain required.',
        'actual_harbor_control_jobs_launched': False, 'qualified': False, 'task_count': 0,
        'model_evaluation_performed': False, 'new_model_calls_during_preparation': 0, 'new_LO_calls_during_preparation': 0}
    validate_selection_execution_budget(manifest)
    require(all(sha(path) == expected for path, expected in bindings.items()), 'A frozen task or supporting artifact changed during snapshot')
    current = read_run(run)
    require(next(t for t in current['tasks'] if t['id'] == task_id)['revision'] == revision,
            'The actual task revision advanced during snapshot')
    return write_new(output / 'probe_manifest.json', manifest)


def status(run, task_id, revision):
    snapshot = read_run(Path(run))
    nodes = {record['node']: record['status'] for record in snapshot['nodes']
             if record.get('task_id') == task_id and record.get('revision') == revision}
    return {'task_id': task_id, 'revision': revision, 'nodes': nodes,
        'snapshot_ready': all(nodes.get(name) == 'completed' for name in NORMAL_NODES),
        'new_LO_calls': 0, 'new_model_calls': 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--revision', type=int, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--offline-admission', type=Path)
    parser.add_argument('--history-root', type=Path, action='append', default=[])
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args(argv)
    if args.freeze:
        require(args.output is not None and args.offline_admission is not None,
                'A fresh output and frozen offline admission are required for snapshot')
        result = freeze_probe(args.run, args.task_id, args.revision, args.output,
            offline_admission=args.offline_admission, history_roots=args.history_root)
    else:
        require(args.output is None and args.offline_admission is None, 'Use --freeze to write a snapshot')
        result = status(args.run, args.task_id, args.revision)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
