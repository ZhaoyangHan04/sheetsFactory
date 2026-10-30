"""Offline capital snapshot guards. No financial, LO, or model executions."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('_capital_development_probe_test', ROOT / 'scripts/prepare_capital_allocation_development_probe.py')
probe = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(probe)


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value)); return probe.reference(path)


@pytest.fixture(scope='module')
def full_plan():
    financial = [{'sheet': 'Finance', 'cell': 'C' + str(index)} for index in range(1, 19032)]
    decisions = [{'sheet': 'Investment Plan', 'cell': 'B' + str(index)} for index in range(3, 21)]
    support = [{'sheet': 'Arithmetic', 'cell': 'B3', 'plan_dependent': True},
               {'sheet': 'Arithmetic', 'cell': 'B4', 'plan_dependent': False}]
    binding = {'financial_bindings': financial, 'decision_bindings': decisions, 'arithmetic_bindings': support}
    proof = {'source_manifest': {'fixture': 'source-manifest'}, 'workbook': {'sha256': 'offline-source'},
             'bindings': {'fixture': 'complete-source-bindings'}}
    edits = [{**item, 'before': '=1', 'after': None} for item in financial + decisions]
    physical = [{key: item[key] for key in ('sheet', 'cell', 'before', 'after')} for item in edits]
    plan = {'edits': edits, 'public_instruction': 'Complete the common investment plan. ' + probe.CLAUSES['financial_modeling'],
        'public_rules': ['One shared investment plan.'], 'scenario_inputs': [], 'family_adapter': {
            'id': 'capital_allocation_fm_v1', 'source_manifest': proof['source_manifest'],
            'source_sha256': 'offline-source', 'bindings': proof['bindings'], 'financial_target_count': 19031,
            'decision_target_count': 18, 'physical_target_count': 19049, 'provided_arithmetic_count': 2,
            'plan_dependent_support_count': 1, 'helper_values_are_protected': False, 'full_workbook_D_required': True}}
    application = {'source_manifest': proof['source_manifest'], 'source': proof['workbook'],
        'physical_edits_sha256': probe.canonical(physical), 'physical_target_count': 19049,
        'quality_or_difficulty_certified': False}
    scope = {'passed': True, 'masked_financial_and_decision_count': 19049, 'provided_helper_formula_count': 2,
        'plan_dependent_caches_cleared_count': 1, 'cleared_support_coordinates_sha256': probe.canonical(['Arithmetic!B3']),
        'unselected_definitions_and_public_primitives_unchanged': True, 'helpers_physically_masked': False,
        'helper_values_protected': False, 'no_helper_values_excluded_from_required_D': True,
        'actual_recalculation_delegated_to_ordinary_construct': True,
        'normal_construct_implementation': probe.reference(ROOT / 'src/sheets_factory/nodes/construction.py')}
    return plan, application, scope, proof, binding


def test_exact_financial_and_eighteen_decision_scope(full_plan):
    targets, helpers = probe.validate_plan_binding(*full_plan)
    assert len(targets) == 19049 and len(helpers) == 2 and not targets & helpers


@pytest.mark.parametrize('case', ['count', 'duplicate', 'after', 'source', 'helper_protected', 'scope',
    'cleared_count', 'cleared_hash', 'full_D', 'application_hash', 'mask_ranges', 'decision_count'])
def test_scope_and_actual_cache_proofs_cannot_be_reduced(full_plan, case):
    plan, app, scope, proof, binding = deepcopy(full_plan)
    if case == 'count': plan['edits'].pop()
    elif case == 'duplicate': plan['edits'][-1] = deepcopy(plan['edits'][0])
    elif case == 'after': plan['edits'][0]['after'] = '=2'
    elif case == 'source': plan['family_adapter']['source_sha256'] = 'changed'
    elif case == 'helper_protected': scope['helper_values_protected'] = True
    elif case == 'scope': plan['public_instruction'] = 'Preserve structure'
    elif case == 'cleared_count': scope['plan_dependent_caches_cleared_count'] = 0
    elif case == 'cleared_hash': scope['cleared_support_coordinates_sha256'] = 'changed'
    elif case == 'full_D': scope['no_helper_values_excluded_from_required_D'] = False
    elif case == 'application_hash': app['physical_edits_sha256'] = 'changed'
    elif case == 'mask_ranges': plan['mask_ranges'] = []
    elif case == 'decision_count': binding['decision_bindings'].pop()
    with pytest.raises(ValueError): probe.validate_plan_binding(plan, app, scope, proof, binding)


def nodes(task_id='task'):
    return [{'task_id': task_id, 'revision': 0, 'node': name, 'status': 'completed'} for name in probe.NORMAL_NODES]


@pytest.mark.parametrize('change', ['missing', 'running', 'revision', 'later_failure'])
def test_all_six_actual_current_node_completions_required(change):
    records = nodes()
    if change == 'missing': records.pop()
    elif change == 'running': records[-1]['status'] = 'running'
    elif change == 'revision': records[-1]['revision'] = 1
    else: records.append({**records[-1], 'status': 'failed'})
    with pytest.raises(ValueError, match='has not completed'): probe.require_completed_nodes({'nodes': records}, 'task', 0)


def test_revision_history_rejects_resampling_without_reading_scores(tmp_path):
    record = dump(tmp_path / 'selection_manifest.json', {'tasks': [{'revision_hash': 'original', 'reward': 1}]})
    assert probe.development_history('new', [tmp_path, record['path']]) == [record]
    with pytest.raises(ValueError, match='already have a model selection'):
        probe.development_history('original', [tmp_path])


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    run = tmp_path / 'run'; run.mkdir(); task_id = 'fm-offline-capital'
    directory = run / 'tasks' / task_id / 'revisions/000'
    public, private = directory / 'public', directory / 'private'
    public.mkdir(parents=True); private.mkdir()
    original = tmp_path / 'source.xlsx'; original.write_bytes(b'Offline source placeholder; not a financial workbook')
    goal, source = private / 'goal.xlsx', public / 'input.xlsx'
    goal.write_bytes(original.read_bytes()); source.write_bytes(b'Offline actual input placeholder')
    identity = probe.sha(original)
    plan = {'edits': [{'sheet': 'Finance', 'cell': 'C3', 'before': '=1', 'after': None}],
            'public_instruction': 'Complete common plan. ' + probe.CLAUSES['financial_modeling'], 'public_rules': ['Shared choices.']}
    config = {'construction': {'instruction_style': 'business_brief'}, 'engine': {'image': 'offline-runtime-fixture'}, 'run_dir': str(run)}
    probe.InstructionNode().execute(SimpleNamespace(data={'plan': plan, 'input': source}, mode='financial_modeling', config=config, revision_dir=directory))
    common = {'structure_ok': True, 'expected_change_count': 2, 'expected_changes': ['Finance!C3', 'Arithmetic!B3']}
    controls = {key: {**common, 'reward': reward} for key, reward in probe.CONTROL_REWARDS.items()}
    dump(private / 'local_controls.json', controls); dump(private / 'expected_delta.json', controls['oracle'])
    dump(private / 'plan.json', plan); dump(private / 'capital_allocation_plan_binding.json', {})
    dump(private / 'capital_allocation_actual_input_scope.json', {'input': probe.reference(source), 'goal': probe.reference(goal),
        'complete_required_D_count': 2, 'changed_helper_count': 1})
    for name in ('native_risk_guard.json', 'native_error_probe.json'): dump(private / name, {'blocking': False})
    for name in ('edit_validation.json', 'root_impacts.json'): dump(private / name, {})
    dump(public / 'profile.json', {}); (private / 'mutated_unrecalculated.xlsx').write_bytes(b'Offline draft')
    scope = probe.read(private / 'capital_allocation_actual_input_scope.json')
    scope['actual_normal_draft'] = probe.reference(private / 'mutated_unrecalculated.xlsx')
    dump(private / 'capital_allocation_actual_input_scope.json', scope)
    for name in ('equivalent', 'missed_root', 'extra_change'):
        for suffix in ('_raw.xlsx', '.xlsx'):
            path = private / 'controls' / (name + suffix); path.parent.mkdir(exist_ok=True); path.write_bytes(b'Offline control')
    for name in ('preflight_manifest.json', 'resolved_config.yaml', 'seed_manifest.json'): (run / name).write_text('{}')
    binding = dump(tmp_path / 'bindings.json', {'fixture': 'scope validation is mocked'})
    proof = {'workbook': probe.reference(original), 'bindings': binding}
    seed = {'sha256': identity, 'local_path': str(original)}
    state = {'tasks': [{'id': task_id, 'mode': 'financial_modeling', 'source_id': identity, 'revision': 0}],
             'nodes': nodes(task_id), 'run': {'status': 'running'}}
    monkeypatch.setattr(probe, 'validate_preparation', lambda *a: ({'recipe_sha256': {}, 'source_artifacts_sha256': {}}, config, seed, proof))
    monkeypatch.setattr(probe, 'read_run', lambda *a: state)
    monkeypatch.setattr(probe, 'validate_plan_binding', lambda *a: ({('Finance', 'C3')}, {('Arithmetic', 'B3')}))
    monkeypatch.setattr(probe, 'development_history', lambda *a: [])
    compared, exported = [], []
    def compare(source, goal, candidate):
        name = 'oracle' if Path(candidate) == goal else 'nop' if Path(candidate) == source else Path(candidate).stem
        compared.append(name); return deepcopy(controls[name])
    monkeypatch.setattr(probe, 'compare_workbooks', compare)
    def export(self, context):
        exported.append(context); target = Path(context.config['run_dir']) / 'SpreadsheetEval' / task_id
        (target / 'environment').mkdir(parents=True); (target / 'tests').mkdir()
        shutil.copyfile(public / 'instruction.md', target / 'instruction.md')
        shutil.copyfile(source, target / 'environment/input.xlsx'); shutil.copyfile(goal, target / 'tests/reference.xlsx')
        return {'export_dir': target}
    monkeypatch.setattr(probe.ExportNode, 'execute', export)
    monkeypatch.setattr(probe, 'inspect_export', lambda *a: {'offline': 'normal export boundary fixture'})
    return SimpleNamespace(run=run, task_id=task_id, output=tmp_path / 'probe', private=private,
        state=state, exported=exported, compared=compared, controls=controls)


def test_snapshot_binds_actual_instruction_export_controls_fullD_and_pendingQA(snapshot):
    f = snapshot; record = probe.freeze_probe(f.run, f.task_id, 0, f.output)
    manifest = probe.read_ref(record)
    assert f.compared == list(probe.CONTROL_REWARDS) and len(f.exported) == 1
    assert manifest['new_model_calls_during_preparation'] == manifest['new_LO_calls_during_preparation'] == 0
    assert manifest['qualified'] is False and manifest['task_count'] == 0
    assert manifest['changed_arithmetic_helper_count'] == 1 and manifest['all_changed_helper_values_in_required_D']
    assert manifest['diagnosis_status_at_snapshot'] == manifest['independent_recovery_status'] == 'pending'
    assert probe.validate_selection_execution_budget(manifest) == probe.BUDGET


def test_running_precheck_is_not_inferred_complete_from_existing_files(snapshot):
    f = snapshot; f.state['nodes'][-1]['status'] = 'running'
    with pytest.raises(ValueError, match='has not completed'): probe.freeze_probe(f.run, f.task_id, 0, f.output)
    assert not f.output.exists() and not f.compared and not f.exported


def test_missing_changed_helper_from_completeD_blocks_export(snapshot):
    f = snapshot; delta = probe.read(f.private / 'expected_delta.json')
    delta['expected_changes'].remove('Arithmetic!B3'); dump(f.private / 'expected_delta.json', delta)
    with pytest.raises(ValueError, match='complete actual required D'): probe.freeze_probe(f.run, f.task_id, 0, f.output)
    assert not f.output.exists() and not f.exported


def test_control_failure_and_snapshot_reuse_fail_closed(snapshot, monkeypatch):
    f = snapshot; monkeypatch.setattr(probe, 'compare_workbooks', lambda *a: {'reward': 1})
    with pytest.raises(ValueError, match='control failed or changed'): probe.freeze_probe(f.run, f.task_id, 0, f.output)
    assert not f.output.exists() and not f.exported
    f.output.mkdir(); marker = f.output / 'keep'; marker.write_text('original')
    with pytest.raises(ValueError, match='fresh'): probe.freeze_probe(f.run, f.task_id, 0, f.output)
    assert marker.read_text() == 'original'
