#!/usr/bin/env python3
"""Freeze one actual normal joint-control Factory revision; no LO or model call."""
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

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.evaluation.harbor import inspect_export
from sheets_factory.evaluation.tool_time_bounds import POLICY_V2
from sheets_factory.nodes import joint_controls as controls
from sheets_factory.nodes.construction import InstructionNode
from sheets_factory.nodes.quality import ExportNode
from sheets_factory.pipelines.joint_repair_activity import validate_joint_certificate, validate_physical_edits
from sheets_factory.reporting import read_run
from sheets_factory.task_adapters.public_input_priority import RULE, canonical, checked, require, sha
from sheets_factory.task_adapters.public_workbook_scope import CLAUSES, POLICY, VERSION, checked_bytes, reference, write_new
from sheets_factory.workbook import compare_workbooks


def support(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    require(spec is not None and spec.loader is not None, 'A frozen preparation support module cannot be loaded')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


phase = support('_joint_control_development_phase', 'run_joint_control_quality.py')
generic = support('_joint_control_generic_probe_support', 'prepare_full_graph_development_probe.py')
# These pure helpers do not select or validate a node registry.
require_completed_nodes = generic.require_completed_nodes
development_history = generic.development_history
fresh_output = generic.fresh_output
recheck = generic.recheck
BUDGET = {'version': 1, 'elapsed_policy': 'operational_guard',
          'elapsed_guard_seconds': 14400, 'tool_budget_seconds': 1800}
CONTROL_REWARDS = dict(controls.CONTROL_REWARDS)


def read(path):
    return json.loads(Path(path).read_text())


def artifact(record, expected):
    path = checked(record)
    require(path == Path(expected).resolve(), 'A joint-control artifact belongs to another path')
    return path


def validate_preparation(run):
    frozen = phase.validate_prepared(run)
    require(isinstance(frozen, dict) and frozen.get('kind') in phase.BACKENDS
            and type(frozen.get('count')) is int and frozen['count'] == 1
            and frozen.get('development_only') is True, 'Only one actual development source may enter this probe')
    name, backend, _ = phase.backend_for(frozen['kind'])
    config = yaml.safe_load(artifact(frozen['resolved_config'], run / 'resolved_config.yaml').read_text())
    seeds = read(artifact(frozen['prepared_seed_manifest'], run / 'seed_manifest.json'))['selected']
    require(len(seeds) == 1 and [s['sha256'] for s in seeds] == frozen['source_order']
            and config['run']['targets'] == {'financial_modeling': 0, 'debugging': 1},
            'The development source order or quota changed')
    controls.validate_setting(config.get(controls.SETTING))
    addition = read(checked(frozen[phase.PHASE_FIELD]))
    require(addition.get('control_setting_name') == controls.SETTING
            and addition.get('control_setting') == config[controls.SETTING] == controls.setting(),
            'The explicit ordered single-omission controls contract changed')
    before = yaml.safe_load(checked(addition['base_node_registry']).read_text())
    after = yaml.safe_load(artifact(addition['new_node_registry'], config['pipeline']['node_registry']).read_text())
    expected = deepcopy(before)
    require(before['nodes'].get('precheck') == 'sheets_factory.nodes.construction:ControlsNode',
            'The original control node is not the normal Factory implementation')
    expected['nodes']['precheck'] = phase.CONTROL_NODE
    require(after == expected and len(after['nodes']) == 11,
            'The development phase may replace only the normal precheck node')
    identity = seeds[0]['sha256']; source = reference(seeds[0]['local_path'])
    policy = config.get(POLICY, {})
    require(type(policy.get('version')) is int and policy['version'] == VERSION,
            'The development candidate lacks an explicit public workbook scope')
    scope = json.loads(checked_bytes(policy['manifest']))
    require(source['sha256'] == identity and type(scope.get('version')) is int and scope['version'] == VERSION
            and scope.get('clauses') == CLAUSES and scope.get('quality_or_difficulty_certified') is False
            and scope.get('sources', {}).get(identity, {}).get('source') == source,
            'The public scope policy belongs to another admitted financial source')
    for record in (config[controls.SETTING]['implementation'], frozen[phase.PHASE_FIELD]):
        checked(record)
    require(frozen['recipe_sha256'].get(config[controls.SETTING]['implementation']['path'])
            == config[controls.SETTING]['implementation']['sha256'], 'The controls implementation is not frozen')
    return frozen, config, seeds[0], name, backend


def validate_selection(private, *, task_id, revision, source, goal, plan, settings, delta):
    """Independently check the actual successful search, including failed history."""
    maximum = controls.validate_setting(settings)
    selection_file = private / 'joint_control_selection.json'
    selection = read(selection_file)
    require(selection.get('kind') == 'joint_actual_single_omission_controls'
            and type(selection.get('version')) is int and selection['version'] == 1
            and selection.get('method') == controls.METHOD and selection.get('state') == 'verified'
            and selection.get('passed') is True and canonical(selection.get('setting')) == canonical(settings)
            and selection.get('task_id') == task_id and type(selection.get('revision')) is int
            and selection['revision'] == revision, 'The actual joint-control selection did not succeed at this revision')
    attempt_id = selection.get('attempt_id')
    require(isinstance(attempt_id, str) and len(attempt_id) == 32
            and all(c in '0123456789abcdef' for c in attempt_id), 'Unsafe joint-control attempt identity')
    directory = private / 'joint_control_attempts' / attempt_id
    terminal = artifact(selection['attempt_receipt'], directory / 'receipt.json')
    require(canonical(read(terminal)) == canonical({k: v for k, v in selection.items() if k != 'attempt_receipt'}),
            'The successful selection differs from its immutable terminal receipt')
    binding = selection['binding']
    artifact(binding['input'], source); artifact(binding['goal'], goal)
    artifact(binding['joint_certificate'], private / 'joint_repair_certificate.json')
    require(binding.get('plan_sha256') == canonical(plan) and binding.get('edits_sha256') == canonical(plan['edits']),
            'The successful control search belongs to another physical mutation plan')
    require(selection.get('individual_or_marginal_activity_claimed') is False
            and selection.get('all_physical_edits_observable_claimed') is False
            and selection.get('quality_recovery_difficulty_certified') is False,
            'A single negative control cannot certify all root impacts, recovery, quality or difficulty')
    edits = plan['edits']
    skipped = controls.prescreen_equal_goal_references(goal, edits)
    expected_skips = json.loads(json.dumps(list(skipped.values()), default=str))
    eligible = [i for i in range(len(edits)) if i not in skipped]
    require(canonical(selection.get('skipped_candidates')) == canonical(expected_skips)
            and canonical(selection.get('eligible_plan_edit_indices')) == canonical(eligible)
            and type(selection.get('physical_edit_count')) is int and selection['physical_edit_count'] == len(edits)
            and selection.get('prescreened_physical_edit_count') == len(edits)
            and selection.get('max_missed_root_attempts') == maximum,
            'The ordered search changed the complete edit set, prefilter or frozen attempt limit')
    attempts = selection.get('attempts', [])
    require(isinstance(attempts, list) and 1 <= len(attempts) <= maximum
            and [a.get('plan_edit_index') for a in attempts] == eligible[:len(attempts)]
            and type(selection.get('selected_plan_edit_index')) is int
            and selection['selected_plan_edit_index'] == attempts[-1]['plan_edit_index'],
            'The negative control is not the first successful actual omission in frozen edit order')
    bound = {str(selection_file): sha(selection_file), str(terminal): sha(terminal)}

    def bind(record, expected):
        path = artifact(record, expected); bound[str(path)] = sha(path); return path

    cache = {}
    def grade(candidate):
        key = sha(candidate)
        if key not in cache:
            cache[key] = compare_workbooks(source, goal, candidate)
        return cache[key]

    for index, attempt in enumerate(attempts):
        edit_index = attempt['plan_edit_index']; edit = edits[edit_index]
        require(type(edit_index) is int and type(attempt.get('actual_attempt_index')) is int
                and attempt['actual_attempt_index'] == index and canonical(attempt.get('edit')) == canonical(edit)
                and attempt.get('state') == 'graded' and type(attempt.get('reward')) is int
                and attempt['reward'] == (0 if index == len(attempts) - 1 else 1)
                and attempt.get('selected') is (index == len(attempts) - 1),
                'Prior omission grades must be one; only the final actual grade zero may be selected')
        location = directory / 'controls/missed_root_attempts' / f'{index:03d}'
        raw = bind(attempt['raw'], location / 'raw.xlsx')
        output = bind(attempt['output'], location / 'recalculated.xlsx')
        comparison = read(bind(attempt['comparison'], location / 'comparison.json'))
        validate_physical_edits(goal, raw, [edit]); validate_physical_edits(goal, output, [edit])
        actual = grade(output)
        require(actual == comparison and actual.get('reward') == attempt['reward']
                and actual.get('structure_ok') is True and 'error' not in actual
                and actual.get('expected_changes') == delta['expected_changes'],
                'An actual omission comparison differs from its retained normal grade')
    require(any(comparison.get(k) for k in ('missing_changes', 'extra_changes', 'wrong_values')),
            'The selected negative control has no actual value mismatch')
    standard = read(bind(selection['canonical_local_controls'], private / 'local_controls.json'))
    require(read(bind(selection['local_controls'], directory / 'local_controls.json')) == standard
            and set(standard) == set(CONTROL_REWARDS), 'The canonical five controls differ from the actual attempt')
    require(selection.get('control_rewards') == CONTROL_REWARDS, 'The successful five control rewards changed')
    names = {name + suffix for name in ('equivalent', 'missed_root', 'extra_change') for suffix in ('_raw.xlsx', '.xlsx')}
    require(set(selection.get('canonical_control_artifacts', {})) == names,
            'The standard actual control workbook set is incomplete')
    for name in names:
        canonical_file = bind(selection['canonical_control_artifacts'][name], private / 'controls' / name)
        attempt_file = directory / 'controls' / name
        require(sha(canonical_file) == sha(attempt_file), 'A canonical workbook differs from its actual executed attempt')
        bound[str(attempt_file)] = sha(attempt_file)
    selected = attempts[-1]
    require(bind(selection['selected_output'], directory / 'controls/missed_root.xlsx').read_bytes()
            == checked(selected['output']).read_bytes()
            and bind(selection['selected_raw'], directory / 'controls/missed_root_raw.xlsx').read_bytes()
            == checked(selected['raw']).read_bytes(), 'The canonical negative control is another candidate')
    calls = selection.get('engine_calls', [])
    labels = ['equivalent', *['missed_root:' + str(a['plan_edit_index']) for a in attempts], 'extra_change']
    expected_calls = [(directory / 'controls/equivalent_raw.xlsx', directory / 'controls/equivalent.xlsx')]
    expected_calls += [(checked(a['raw']), checked(a['output'])) for a in attempts]
    expected_calls += [(directory / 'controls/extra_change_raw.xlsx', directory / 'controls/extra_change.xlsx')]
    require(isinstance(calls, list) and len(calls) == len(labels)
            and type(selection.get('actual_workbook_LO_started_count')) is int
            and type(selection.get('actual_workbook_LO_completed_count')) is int
            and selection['actual_workbook_LO_started_count'] == selection['actual_workbook_LO_completed_count'] == len(calls),
            'The successful control execution chain is incomplete')
    for call, label, (raw, output) in zip(calls, labels, expected_calls):
        require(call.get('label') == label and call.get('completed') is True
                and 'error' not in call and 'error_type' not in call
                and call.get('output_path') == str(output.resolve())
                and type(call.get('duration_ms')) is int and call['duration_ms'] >= 0,
                'A successful actual control call has another label, path or completion state')
        bind(call['input'], raw); bind(call['output'], output)
        for field in ('started_at', 'finished_at'):
            stamp = datetime.fromisoformat(call[field])
            require(stamp.utcoffset() is not None and stamp.utcoffset().total_seconds() == 0,
                    'An actual control call lacks a UTC timestamp')
        require(datetime.fromisoformat(call['finished_at']) >= datetime.fromisoformat(call['started_at']),
                'An actual control completion precedes its start')
    prior = selection.get('prior_failed_attempts', [])
    require(isinstance(prior, list) and len({str(checked(r)) for r in prior}) == len(prior),
            'The immutable failed control attempt history is malformed')
    for index, record in enumerate(prior):
        previous_file = checked(record)
        require(previous_file.parent.parent == private / 'joint_control_attempts'
                and previous_file.name == 'receipt.json', 'A prior control failure belongs to another task')
        previous = read(previous_file); bound[str(previous_file)] = sha(previous_file)
        require(previous.get('kind') == selection['kind'] and previous.get('state') in {'failed', 'cancelled'}
                and previous.get('task_id') == task_id and previous.get('revision') == revision
                and previous.get('prior_failed_attempts') == prior[:index]
                and previous['binding']['goal'] == binding['goal']
                and previous['binding']['plan_sha256'] == binding['plan_sha256'],
                'A failed actual control attempt was dropped, rewritten or relabelled')
        def collect_refs(value):
            if isinstance(value, dict):
                if 'path' in value and 'sha256' in value:
                    path = checked(value); bound[str(path)] = sha(path)
                for item in value.values():
                    collect_refs(item)
            elif isinstance(value, list):
                for item in value:
                    collect_refs(item)
        collect_refs(previous)
    for name, expected in CONTROL_REWARDS.items():
        candidate = goal if name == 'oracle' else source if name == 'nop' else private / 'controls' / (name + '.xlsx')
        require(grade(candidate) == standard[name] and type(standard[name].get('reward')) is int
                and standard[name]['reward'] == expected,
                'An actual normal local control failed or differs from its receipt: ' + name)
    return selection, bound


def freeze_probe(run, task_id, revision, output, *, history_roots=None):
    run = Path(run).resolve()
    require(isinstance(task_id, str) and Path(task_id).name == task_id and task_id not in {'.', '..'}
            and type(revision) is int and revision >= 0, 'Unsafe task identity or revision')
    frozen, config, seed, backend_name, backend = validate_preparation(run)
    snapshot = read_run(run)
    tasks = [t for t in snapshot['tasks'] if t['id'] == task_id]
    require(len(tasks) == 1 and tasks[0].get('mode') == 'debugging' and tasks[0].get('revision') == revision
            and tasks[0].get('source_id') == seed['sha256'], 'This is not the current actual admitted development revision')
    require_completed_nodes(snapshot, task_id, revision)
    original = run / 'tasks' / task_id / 'revisions' / f'{revision:03d}'
    private, public = original / 'private', original / 'public'
    plan = read(private / 'plan.json'); source, goal = public / 'input.xlsx', private / 'goal.xlsx'
    require(sha(goal) == seed['sha256'] and CLAUSES['debugging'] in plan['public_instruction']
            and RULE in plan['public_rules'], 'The exact financial goal or explicit public scope/precedence changed')
    instruction = (public / 'instruction.md').read_text(); delta = read(private / 'expected_delta.json')
    joint = validate_joint_certificate(read(private / 'joint_repair_certificate.json'), goal, source, plan['edits'], delta)
    selection, control_bound = validate_selection(private, task_id=task_id, revision=revision,
        source=source, goal=goal, plan=plan, settings=config[controls.SETTING], delta=delta)
    revision_hash = hashlib.sha256(source.read_bytes() + instruction.encode()).hexdigest()
    history = development_history(revision_hash, [ROOT / 'outputs/difficulty', *(history_roots or [])])
    fixed = [source, goal, public / 'instruction.md', public / 'profile.json', private / 'plan.json',
        private / 'expected_delta.json', private / 'joint_repair_certificate.json', run / 'preflight_manifest.json',
        run / 'resolved_config.yaml', run / 'seed_manifest.json', Path(__file__).resolve(),
        Path(phase.__file__), Path(generic.__file__), ROOT / 'src/sheets_factory/nodes/construction.py',
        ROOT / 'src/sheets_factory/nodes/quality.py', ROOT / 'src/sheets_factory/evaluation/harbor.py',
        ROOT / 'src/sheets_factory/evaluation/standalone_verifier.py']
    bound = {**frozen['recipe_sha256'], **frozen['source_artifacts_sha256'], **control_bound}
    bound.update({str(p): sha(p) for p in fixed}); recheck(bound)
    output = fresh_output(output); host = backend.cohort.host_runtime_settings(output)
    with backend.cohort.host_temporary_environment(output, host):
        replay = output / 'normal_instruction_replay'; (replay / 'public').mkdir(parents=True)
        generated = InstructionNode().execute(SimpleNamespace(data={'plan': plan, 'input': source}, mode='debugging',
            config=config, revision_dir=replay))
        require(generated['instruction'] == instruction and generated['revision_hash'] == revision_hash,
                'Public bytes differ from normal InstructionNode on the actual scoped plan')
        copied_config = deepcopy(config); copied_config['run_dir'] = str(output)
        lineage = output / 'private' / task_id; lineage.mkdir(parents=True)
        exported = ExportNode().execute(SimpleNamespace(task_id=task_id, mode='debugging', source=Path(seed['local_path']),
            revision=revision, revision_dir=original, directory=lineage, config=copied_config,
            data={'source_id': seed['sha256'], 'revision_hash': revision_hash}))['export_dir']
        export_binding = inspect_export(exported)
        require((exported / 'instruction.md').read_bytes() == (public / 'instruction.md').read_bytes()
                and sha(exported / 'environment/input.xlsx') == sha(source)
                and sha(exported / 'tests/reference.xlsx') == sha(goal), 'Normal ExportNode changed the public bytes or financial goal')
        recheck(bound)
        latest = next(t for t in read_run(run)['tasks'] if t['id'] == task_id)
        require(latest.get('revision') == revision, 'Factory advanced to another revision while this probe was freezing')
        record = {'task_id': task_id, 'mode': 'debugging', 'source_id': seed['sha256'], 'revision': revision,
            'revision_hash': revision_hash, 'source_kind': 'prequality_development_probe',
            'difficulty_status': 'prequality_development_probe', 'base_image': config['engine']['image'],
            'task_directory': str(exported), 'harbor_export_binding': export_binding, 'local_controls': CONTROL_REWARDS,
            'execution_budget': deepcopy(BUDGET), 'timeout_seconds': 14400, 'tool_time_policy': dict(POLICY_V2)}
        manifest = {'schema_version': 1, 'kind': 'prequality_development_probe', 'source_kind': 'prequality_development_probe',
            'frozen_at': datetime.now(timezone.utc).isoformat(), 'selected_task_ids': [task_id], 'tasks': [record],
            'execution_budget': deepcopy(BUDGET), 'tool_time_policy_version': 2, 'source_artifacts_sha256': bound,
            'main_quality_run': str(run), 'normal_factory_preparation': reference(run / 'preflight_manifest.json'),
            'prospective_joint_controls_phase': frozen[phase.PHASE_FIELD], 'provider_backend': backend_name,
            'joint_control_selection': reference(private / 'joint_control_selection.json'),
            'joint_control_attempt_receipt': selection['attempt_receipt'], 'full_joint_delta': joint,
            'normal_instruction_replay': reference(replay / 'public/instruction.md'),
            'normal_ExportNode_called_on_actual_revision': True, 'prior_selections_checked': history,
            'quality_pending': True, 'quality_status': 'Actual joint construction and five local controls verified; public recovery, all12QA and real Harbor remain separate normal gates, pending or separately recorded.',
            'independent_recovery_required_before_release': True, 'all12_quality_checks_required_before_release': True,
            'actual_Harbor_controls_required_before_release': True,
            'selection_policy': 'First development selection on these exact normal Factory public revision bytes; no final-cohort or confirmation credit.',
            'qualified': False, 'task_count': 0, 'model_evaluation_performed': False,
            'new_model_calls_during_preparation': 0, 'new_LO_calls': 0}
        write_new(output / 'probe_manifest.json', manifest)
        return reference(output / 'probe_manifest.json')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quality-run', type=Path, required=True)
    parser.add_argument('--task-id', required=True); parser.add_argument('--revision', type=int, default=0)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--history-root', type=Path, action='append')
    args = parser.parse_args(argv)
    result = freeze_probe(args.quality_run, args.task_id, args.revision, args.output, history_roots=args.history_root)
    print(json.dumps({'prepared': result, 'models_started': 0, 'LO_calls': 0, 'qualified': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
