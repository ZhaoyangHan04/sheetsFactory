#!/usr/bin/env python3
"""Prepare a scoped Factory run or snapshot its actual controls; never run models."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.evaluation.harbor import inspect_export
from sheets_factory.evaluation.tool_time_bounds import POLICY_V2
from sheets_factory.nodes.construction import InstructionNode
from sheets_factory.nodes.quality import ExportNode
from sheets_factory.pipelines.joint_repair_activity import validate_joint_certificate
from sheets_factory.reporting import read_run
from sheets_factory.task_adapters.public_workbook_scope import (
    POLICY, VERSION, CLAUSES, FULL_GRAPH_PLAN_NODE, reference, checked_bytes, registry_nodes, write_new, require)
from sheets_factory.task_adapters.public_input_priority import RULE
from sheets_factory.workbook import compare_workbooks

spec = importlib.util.spec_from_file_location('_full_graph_development_support', ROOT / 'scripts/run_full_graph_quality.py')
factory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(factory)

BUDGET = {'version': 1, 'elapsed_policy': 'operational_guard',
          'elapsed_guard_seconds': 14400, 'tool_budget_seconds': 1800}
CONTROL_REWARDS = {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def recheck(mapping):
    for path, expected in mapping.items():
        require(digest(path) == expected, 'A frozen preparation artifact changed: ' + path)


def fresh_output(output):
    output = Path(output).absolute()
    require(output == output.resolve() and not output.exists(), 'A fresh non-symlink output directory is required')
    output.mkdir(parents=True)
    return output


def prepare_scoped_factory(base_prepared, output):
    """New configuration only; normal frozen Factory executes it separately."""
    base_prepared = Path(base_prepared).resolve()
    previous = factory.validate_prepared(base_prepared)
    require(previous['count'] == 1 and previous['development_only'] is True,
            'This entry prepares one development source, never final DBG10')
    output = fresh_output(output)
    host = factory.cohort.host_runtime_settings(output)
    with factory.cohort.host_temporary_environment(output, host) as host_receipt:
        config = yaml.safe_load(checked_bytes({**previous['resolved_config'],
            'bytes': Path(previous['resolved_config']['path']).stat().st_size}))
        seed = read(base_prepared / 'seed_manifest.json')
        require(len(seed['selected']) == 1 and seed.get('development_only') is True,
                'A development source manifest must contain exactly one source')
        before_config = deepcopy(config)
        shutil.copy2(base_prepared / 'resolved_config.yaml', output / 'resolved_config_before_scope.yaml')
        shutil.copy2(base_prepared / 'seed_manifest.json', output / 'seed_manifest.json')
        shutil.copy2(base_prepared / 'activity_bindings.json', output / 'activity_bindings.json')
        base_registry = Path(config['pipeline']['node_registry'])
        nodes = registry_nodes(yaml.safe_load(base_registry.read_text())['nodes'])
        registry = output / 'scope_nodes.yaml'
        registry.write_text(yaml.safe_dump({'version': 1, 'nodes': nodes}, sort_keys=False))
        policy = write_new(output / 'scope_binding.json', {
            'kind': 'public_workbook_scope_binding', 'version': VERSION, 'clauses': CLAUSES,
            'sources': {s['sha256']: {'source': reference(s['local_path'])} for s in seed['selected']},
            'tasks': {}, 'quality_or_difficulty_certified': False})
        config.update(run_dir=str(output), host_runtime=host)
        config['run']['seed_manifest'] = str(output / 'seed_manifest.json')
        config['pipeline']['node_registry'] = str(registry)
        config[factory.JOINT_SETTING]['bindings'] = factory.ref(output / 'activity_bindings.json')
        config[POLICY] = {'version': VERSION, 'manifest': policy}
        require(config['agents'] == before_config['agents']
                and config['run']['targets'] == before_config['run']['targets']
                and all(config['run'].get(k) == before_config['run'].get(k) for k in factory.PROTECTED_BUDGETS),
                'Scope preparation must preserve agents, quotas and all normal budgets')
        (output / 'resolved_config.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
        phase = write_new(output / 'scope_preparation_addendum.json', {
            'kind': 'fresh_development_public_workbook_scope_phase',
            'previous_preparation': reference(base_prepared / 'preflight_manifest.json'),
            'config_before': reference(output / 'resolved_config_before_scope.yaml'),
            'config_after': reference(output / 'resolved_config.yaml'),
            'previous_config_hash_is_historical': True, 'source_order': previous['source_order'],
            'base_node_registry': reference(base_registry), 'composed_node_registry': reference(registry),
            'policy_binding': policy, 'financial_inputs_goals_and_edits_changed': False,
            'old_preparation_modified': False, 'models_started': 0, 'LO_calls': 0,
            'normal_all_nodes_controls_recovery_all12QA_and_actual_Harbor_required': True,
            'quality_or_difficulty_certified': False})
        frozen = deepcopy(previous)
        frozen.update(prepared_at=datetime.now(timezone.utc).isoformat(),
            prepared_seed_manifest=factory.ref(output / 'seed_manifest.json'),
            resolved_config=factory.ref(output / 'resolved_config.yaml'),
            activity_binding=config[factory.JOINT_SETTING]['bindings'],
            host_runtime=host, preparation_host_runtime=host_receipt,
            scope_preparation_addendum=phase)
        for p in (Path(__file__).resolve(),
                  ROOT / 'src/sheets_factory/task_adapters/public_workbook_scope.py', registry):
            frozen['recipe_sha256'][str(p)] = digest(p)
        for p in (output / 'scope_binding.json', output / 'scope_preparation_addendum.json',
                  output / 'resolved_config_before_scope.yaml'):
            frozen['source_artifacts_sha256'][str(p)] = digest(p)
        recheck(previous['recipe_sha256']); recheck(previous['source_artifacts_sha256'])
        write_new(output / 'preflight_manifest.json', frozen)
        return reference(output / 'preflight_manifest.json')


def validate_run_preparation(run):
    """Read immutable admission evidence; Factory already performed deep admission."""
    frozen = read(run / 'preflight_manifest.json')
    require(frozen.get('kind') == 'prepared_full_graph_joint_quality'
            and type(frozen.get('count')) is int and frozen['count'] == 1 and frozen.get('development_only') is True,
            'Only a prepared single-source development Factory run is supported')
    recheck(frozen['recipe_sha256']); recheck(frozen['source_artifacts_sha256'])
    require(digest(run / 'resolved_config.yaml') == frozen['resolved_config']['sha256']
            and digest(run / 'seed_manifest.json') == frozen['prepared_seed_manifest']['sha256'],
            'Factory configuration or source manifest changed')
    config = yaml.safe_load((run / 'resolved_config.yaml').read_text())
    require(config['run']['targets'] == {'financial_modeling': 0, 'debugging': 1}
            and type(config.get(POLICY, {}).get('version')) is int and config[POLICY]['version'] == VERSION,
            'The actual Factory run is not a scoped development DBG candidate')
    policy = read(Path(config[POLICY]['manifest']['path']))
    checked_bytes(config[POLICY]['manifest'])
    require(type(policy.get('version')) is int and policy['version'] == VERSION
            and policy.get('clauses') == CLAUSES and policy.get('quality_or_difficulty_certified') is False,
            'The public scope policy is not bound')
    entries = read(run / 'seed_manifest.json')['selected']
    require(len(entries) == 1 and entries[0]['sha256'] == frozen['source_order'][0], 'Factory source order changed')
    source = reference(entries[0]['local_path'])
    require(source['sha256'] == entries[0]['sha256']
            and policy.get('sources', {}).get(source['sha256'], {}).get('source') == source,
            'The public scope binding is not for the actual admitted financial source')
    registry = Path(config['pipeline']['node_registry'])
    require(str(registry) in frozen['recipe_sha256'], 'The composed registry is not frozen')
    nodes = yaml.safe_load(registry.read_text())['nodes']
    expected_nodes = registry_nodes(yaml.safe_load((ROOT / 'config/task_adapters/scc_activity_nodes.yaml').read_text())['nodes'])
    require(nodes == expected_nodes and nodes['plan'] == FULL_GRAPH_PLAN_NODE,
            'The run must retain every normal full-graph node and the explicit ScopeFullGraphPlanNode')
    return frozen, config, entries[0]


def require_completed_nodes(snapshot, task_id, revision):
    for name in ('normalize', 'profile', 'plan', 'construct', 'instruction', 'precheck'):
        records = [n for n in snapshot['nodes'] if n.get('task_id') == task_id and n.get('node') == name
                   and n.get('revision') == revision]
        require(records and records[-1].get('status') == 'completed',
                'Normal Factory node has not completed at this revision: ' + name)


def development_history(revision_hash, directories):
    history = []
    for directory in directories:
        directory = Path(directory)
        candidates = [directory] if directory.is_file() else sorted(directory.rglob('selection_manifest.json'))
        for path in candidates:
            previous = read(path)
            require(all(t.get('revision_hash') != revision_hash for t in previous.get('tasks', [])),
                    'These public revision bytes already have a model selection; never resample development attempts')
            history.append(reference(path))
    return history


def freeze_probe(run, task_id, revision, output, *, history_roots=None):
    run = Path(run).resolve()
    require(isinstance(task_id, str) and Path(task_id).name == task_id and task_id not in {'.', '..'}
            and type(revision) is int and revision >= 0, 'Unsafe task ID or revision')
    frozen, config, seed = validate_run_preparation(run)
    snapshot = read_run(run)
    matches = [t for t in snapshot['tasks'] if t['id'] == task_id]
    require(len(matches) == 1 and matches[0].get('mode') == 'debugging'
            and matches[0].get('revision') == revision and matches[0].get('source_id') == seed['sha256'],
            'The requested task is not the actual current admitted Factory revision')
    require_completed_nodes(snapshot, task_id, revision)
    original = run / 'tasks' / task_id / 'revisions' / f'{revision:03d}'
    public, private = original / 'public', original / 'private'
    plan = read(private / 'plan.json')
    instruction = (public / 'instruction.md').read_text()
    require(CLAUSES['debugging'] in plan['public_instruction'] and RULE in plan['public_rules'],
            'The normal plan lacks explicit public scope or numeric input precedence')
    source, goal = public / 'input.xlsx', private / 'goal.xlsx'
    require(digest(goal) == seed['sha256'], 'The actual Factory financial goal differs from its admitted source')
    delta = read(private / 'expected_delta.json')
    joint = validate_joint_certificate(read(private / 'joint_repair_certificate.json'), goal, source, plan['edits'], delta)
    stored = read(private / 'local_controls.json')
    require(set(stored) == set(CONTROL_REWARDS), 'Exactly the five normal local controls are required')
    for name, expected in CONTROL_REWARDS.items():
        candidate = goal if name == 'oracle' else source if name == 'nop' else private / 'controls' / (name + '.xlsx')
        result = compare_workbooks(source, goal, candidate)
        require(result == stored[name] and result.get('reward') == expected,
                'Actual normal local control failed or differs from its receipt: ' + name)
    revision_hash = hashlib.sha256(source.read_bytes() + instruction.encode()).hexdigest()
    history = development_history(revision_hash, [ROOT / 'outputs/difficulty', *(history_roots or [])])
    fixed = [source, goal, public / 'instruction.md', public / 'profile.json', private / 'plan.json',
             private / 'expected_delta.json', private / 'local_controls.json', private / 'joint_repair_certificate.json',
             run / 'preflight_manifest.json', run / 'resolved_config.yaml', run / 'seed_manifest.json',
             Path(__file__).resolve(), ROOT / 'src/sheets_factory/nodes/construction.py',
             ROOT / 'src/sheets_factory/nodes/quality.py', ROOT / 'src/sheets_factory/evaluation/harbor.py',
             ROOT / 'src/sheets_factory/evaluation/standalone_verifier.py']
    fixed += [private / 'controls' / (name + '.xlsx') for name in ('equivalent', 'missed_root', 'extra_change')]
    bound = {str(p): digest(p) for p in fixed}
    output = fresh_output(output)
    host = factory.cohort.host_runtime_settings(output)
    with factory.cohort.host_temporary_environment(output, host):
        replay = output / 'normal_instruction_replay'; (replay / 'public').mkdir(parents=True)
        ctx = SimpleNamespace(data={'plan': plan, 'input': source}, mode='debugging', config=config, revision_dir=replay)
        generated = InstructionNode().execute(ctx)
        require(generated['instruction'] == instruction and generated['revision_hash'] == revision_hash,
                'Actual public bytes differ from normal InstructionNode on the actual scoped plan')
        copied_config = deepcopy(config); copied_config['run_dir'] = str(output)
        lineage = output / 'private' / task_id; lineage.mkdir(parents=True)
        exported = ExportNode().execute(SimpleNamespace(task_id=task_id, mode='debugging', source=Path(seed['local_path']),
            revision=revision, revision_dir=original, directory=lineage, config=copied_config,
            data={'source_id': seed['sha256'], 'revision_hash': revision_hash}))['export_dir']
        binding = inspect_export(exported)
        require((exported / 'instruction.md').read_bytes() == (public / 'instruction.md').read_bytes()
                and digest(exported / 'environment/input.xlsx') == digest(source)
                and digest(exported / 'tests/reference.xlsx') == digest(goal),
                'The normal export changed the actual Factory public bytes or goal')
        record = {'task_id': task_id, 'mode': 'debugging', 'source_id': seed['sha256'], 'revision': revision,
            'revision_hash': revision_hash, 'source_kind': 'prequality_development_probe',
            'difficulty_status': 'prequality_development_probe', 'base_image': config['engine']['image'],
            'task_directory': str(exported), 'harbor_export_binding': binding, 'local_controls': CONTROL_REWARDS,
            'execution_budget': BUDGET, 'timeout_seconds': 14400, 'tool_time_policy': dict(POLICY_V2)}
        recheck(bound)
        latest = next(t for t in read_run(run)['tasks'] if t['id'] == task_id)
        require(latest.get('revision') == revision, 'Factory advanced to another revision during snapshot preparation')
        manifest = {'schema_version': 1, 'kind': 'prequality_development_probe', 'source_kind': 'prequality_development_probe',
            'frozen_at': datetime.now(timezone.utc).isoformat(), 'selected_task_ids': [task_id], 'tasks': [record],
            'execution_budget': BUDGET, 'tool_time_policy_version': 2, 'source_artifacts_sha256': bound,
            'main_quality_run': str(run), 'normal_factory_preparation': reference(run / 'preflight_manifest.json'),
            'normal_instruction_replay': reference(replay / 'public/instruction.md'),
            'normal_ExportNode_called_on_actual_revision': True, 'full_joint_delta': joint,
            'quality_status': 'Five actual local controls and joint construction verified; recovery, all12QA and actual Harbor remain normal independent gates, pending or separately recorded.',
            'independent_recovery_required_before_release': True, 'all12_quality_checks_required_before_release': True,
            'actual_Harbor_controls_required_before_release': True, 'quality_pending': True,
            'selection_policy': 'First development attempt on the exact normal Factory scoped revision; no confirmation or final-cohort credit.',
            'prior_selections_checked': history, 'qualified': False, 'task_count': 0,
            'model_evaluation_performed': False, 'new_model_calls_during_preparation': 0, 'new_LO_calls': 0}
        write_new(output / 'probe_manifest.json', manifest)
        return reference(output / 'probe_manifest.json')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--factory-prepared', type=Path)
    group.add_argument('--quality-run', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--task-id'); parser.add_argument('--revision', type=int, default=0)
    parser.add_argument('--history-root', type=Path, action='append')
    args = parser.parse_args(argv)
    if args.factory_prepared:
        result = prepare_scoped_factory(args.factory_prepared, args.output)
    else:
        require(args.task_id and args.revision >= 0, 'A task ID and nonnegative revision are required')
        result = freeze_probe(args.quality_run, args.task_id, args.revision, args.output, history_roots=args.history_root)
    print(json.dumps({'prepared': result, 'models_started': 0, 'LO_calls': 0, 'qualified': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
