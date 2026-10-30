"""Offline cache/phase fixtures; no actual LO, financial admission or model claim."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from sheets_factory.evaluation.harbor import inspect_export
from sheets_factory.nodes import joint_controls
from sheets_factory.nodes.construction import InstructionNode
from sheets_factory.task_adapters.public_input_priority import RULE, ref
from sheets_factory.task_adapters.public_workbook_scope import CLAUSES, POLICY, VERSION, reference
from test_joint_controls import fixture_context

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('joint_control_probe_entry', ROOT / 'scripts/prepare_joint_control_development_probe.py')
entry = importlib.util.module_from_spec(spec); spec.loader.exec_module(entry)


def dump(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False))


@pytest.fixture
def revision(tmp_path, monkeypatch, request):
    run = tmp_path / 'run'
    ctx, engine, _ = fixture_context(run / 'tasks', monkeypatch)
    ctx.task_id = 'task'
    ctx.config.update(project_root=str(ROOT), run_dir=str(run),
        construction={'instruction_style': 'business_brief'},
        engine={'image': 'sheetsfactory-lo:24.2-iterative-openpyxl315-v1'},
        diagnosis={'difficulty_deferred': False}, run={'targets': {'financial_modeling': 0, 'debugging': 1}})
    ctx.data['plan'].update(public_instruction='Repair the existing model formulas.\n\n' + CLAUSES['debugging'],
                            public_rules=[RULE])
    if getattr(request, 'param', {}).get('retry'):
        engine.fail_at = 2
        with pytest.raises(RuntimeError): joint_controls.JointObservableControlsNode().execute(ctx)
        engine.fail_at = None
    joint_controls.JointObservableControlsNode().execute(ctx)
    private = ctx.revision_dir / 'private'; public = ctx.revision_dir / 'public'
    dump(private / 'plan.json', ctx.data['plan']); dump(private / 'expected_delta.json', ctx.data['delta'])
    dump(public / 'profile.json', {'offline_fixture': True})
    instruction = InstructionNode().execute(ctx)
    seed = {'sha256': entry.sha(ctx.data['goal']), 'local_path': str(ctx.data['goal']),
            'finance_evidence': {'fixture_financial_admission': 'not a real financial claim'}}
    scope = run / 'scope.json'
    dump(scope, {'version': VERSION, 'clauses': CLAUSES, 'quality_or_difficulty_certified': False,
                 'sources': {seed['sha256']: {'source': reference(seed['local_path'])}}})
    ctx.config[POLICY] = {'version': VERSION, 'manifest': reference(scope)}
    nodes = yaml.safe_load((ROOT / 'config/task_adapters/scc_activity_nodes.yaml').read_text())
    base_registry = run / 'base_nodes.yaml'; base_registry.write_text(yaml.safe_dump(nodes))
    after = deepcopy(nodes); after['nodes']['precheck'] = entry.phase.CONTROL_NODE
    registry = run / 'nodes.yaml'; registry.write_text(yaml.safe_dump(after))
    ctx.config['pipeline'] = {'node_registry': str(registry)}
    config_file = run / 'resolved_config.yaml'; config_file.write_text(yaml.safe_dump(ctx.config))
    dump(run / 'seed_manifest.json', {'selected': [seed], 'development_only': True})
    phase_file = run / 'phase.json'
    dump(phase_file, {'control_setting_name': joint_controls.SETTING, 'control_setting': joint_controls.setting(),
        'base_node_registry': ref(base_registry), 'new_node_registry': ref(registry)})
    frozen = {'kind': 'prepared_full_graph_joint_quality', 'count': 1, 'development_only': True,
        'resolved_config': ref(config_file), 'prepared_seed_manifest': ref(run / 'seed_manifest.json'),
        'source_order': [seed['sha256']], 'recipe_sha256': {
            joint_controls.setting()['implementation']['path']: joint_controls.setting()['implementation']['sha256']},
        'source_artifacts_sha256': {str(scope): entry.sha(scope)}, entry.phase.PHASE_FIELD: ref(phase_file)}
    dump(run / 'preflight_manifest.json', frozen)
    snapshot = {'tasks': [{'id': 'task', 'mode': 'debugging', 'revision': 0, 'source_id': seed['sha256']}],
        'nodes': [{'task_id': 'task', 'revision': 0, 'node': node, 'status': 'completed'}
                  for node in ('normalize', 'profile', 'plan', 'construct', 'instruction', 'precheck')]}
    observed = []
    def validate(path):
        observed.append(Path(path)); return deepcopy(frozen)
    monkeypatch.setattr(entry.phase, 'validate_prepared', validate)
    backend = SimpleNamespace(cohort=entry.generic.factory.cohort)
    monkeypatch.setattr(entry.phase, 'backend_for', lambda kind: ('v3' if 'semantic' in kind else 'v2', backend, object))
    monkeypatch.setattr(entry, 'read_run', lambda path: deepcopy(snapshot))
    monkeypatch.setattr(entry, 'validate_joint_certificate', lambda *args: {'complete_required_D_count': 1, 'offline_fixture': True})
    monkeypatch.setattr(entry, 'development_history', lambda *args: [])
    return SimpleNamespace(run=run, ctx=ctx, private=private, public=public, config=ctx.config,
        frozen=frozen, phase_file=phase_file, snapshot=snapshot, observed=observed, instruction=instruction, engine=engine)


def rewrite_selection(fixture, mutate):
    path = fixture.private / 'joint_control_selection.json'; selection = entry.read(path)
    body = {k: v for k, v in selection.items() if k != 'attempt_receipt'}; mutate(body)
    terminal = Path(selection['attempt_receipt']['path']); dump(terminal, body)
    dump(path, {**body, 'attempt_receipt': ref(terminal)})


def freeze(fixture, output):
    return entry.freeze_probe(fixture.run, 'task', 0, output)


@pytest.mark.parametrize('kind,backend', [('prepared_full_graph_joint_quality', 'v2'),
    ('prepared_separate_semantic_graph_v3_normal_quality', 'v3')])
def test_exact_normal_export_and_public_bytes_for_both_provider_kinds(tmp_path, revision, kind, backend):
    revision.frozen['kind'] = kind
    before = {p: entry.sha(p) for p in revision.run.rglob('*') if p.is_file()}
    fake_calls = len(revision.engine.calls)
    record = freeze(revision, tmp_path / 'probe'); manifest = entry.read(record['path']); task = manifest['tasks'][0]
    assert manifest['provider_backend'] == backend and revision.observed == [revision.run]
    assert task['revision_hash'] == revision.instruction['revision_hash']
    assert (Path(task['task_directory']) / 'instruction.md').read_bytes() == (revision.public / 'instruction.md').read_bytes()
    assert inspect_export(task['task_directory']) == task['harbor_export_binding']
    assert manifest['quality_pending'] and not manifest['qualified'] and manifest['task_count'] == 0
    assert manifest['normal_ExportNode_called_on_actual_revision'] and manifest['new_LO_calls'] == 0
    assert manifest['new_model_calls_during_preparation'] == 0 and len(revision.engine.calls) == fake_calls
    assert task['execution_budget'] == entry.BUDGET and task['timeout_seconds'] == 14400
    assert task['tool_time_policy']['version'] == 2
    assert task['local_controls'] == joint_controls.CONTROL_REWARDS
    assert {p: entry.sha(p) for p in before} == before
    assert not (revision.run / 'SpreadsheetEval').exists() and not (revision.ctx.directory / 'lineage.json').exists()


def test_original_exact_registry_validator_is_never_called(tmp_path, revision, monkeypatch):
    monkeypatch.setattr(entry.generic, 'validate_run_preparation', lambda *args: pytest.fail('Forbidden original exact-registry validator'))
    assert Path(freeze(revision, tmp_path / 'probe')['path']).is_file()


@pytest.mark.parametrize('node', ['normalize', 'profile', 'plan', 'construct', 'instruction', 'precheck'])
def test_all_six_actual_factory_nodes_are_required_at_current_revision(tmp_path, revision, node):
    next(n for n in revision.snapshot['nodes'] if n['node'] == node)['revision'] = 1
    with pytest.raises(ValueError, match='has not completed'):
        freeze(revision, tmp_path / 'probe')
    assert not (tmp_path / 'probe').exists()


def test_no_other_registry_node_can_change(tmp_path, revision):
    config = revision.config; registry = Path(config['pipeline']['node_registry'])
    value = yaml.safe_load(registry.read_text()); value['nodes']['construct'] = 'unapproved:Construct'
    registry.write_text(yaml.safe_dump(value))
    phase = entry.read(revision.phase_file); phase['new_node_registry'] = ref(registry); dump(revision.phase_file, phase)
    revision.frozen[entry.phase.PHASE_FIELD] = ref(revision.phase_file)
    with pytest.raises(ValueError, match='only the normal precheck'):
        freeze(revision, tmp_path / 'probe')


@pytest.mark.parametrize('mutation', ['not_passed', 'wrong_binding', 'wrong_plan', 'wrong_selected_index',
    'prior_zero', 'selected_one', 'changed_edit', 'dropped_attempt', 'fake_call_count', 'incomplete_call',
    'wrong_call_path', 'wrong_call_label', 'call_error', 'backwards_timestamp', 'fake_global_activity', 'fake_quality', 'reordered_eligible',
    'fake_prefilter', 'bad_maximum', 'boolean_setting_version', 'boolean_eligible_indices'])
def test_malformed_successful_receipt_is_rejected_even_when_rehashed(tmp_path, revision, mutation):
    def change(value):
        if mutation == 'not_passed': value['passed'] = False
        elif mutation == 'wrong_binding': value['binding']['input'] = value['binding']['goal']
        elif mutation == 'wrong_plan': value['binding']['edits_sha256'] = '0' * 64
        elif mutation == 'wrong_selected_index': value['selected_plan_edit_index'] = 0
        elif mutation == 'prior_zero': value['attempts'][0]['reward'] = 0
        elif mutation == 'selected_one': value['attempts'][-1]['reward'] = 1
        elif mutation == 'changed_edit': value['attempts'][-1]['edit']['after'] = '=77'
        elif mutation == 'dropped_attempt': value['attempts'].pop(0)
        elif mutation == 'fake_call_count': value['actual_workbook_LO_completed_count'] = 99
        elif mutation == 'incomplete_call': value['engine_calls'][0]['completed'] = False
        elif mutation == 'wrong_call_path': value['engine_calls'][0]['input'] = value['engine_calls'][0]['output']
        elif mutation == 'wrong_call_label': value['engine_calls'][0]['label'] = 'missed_root:0'
        elif mutation == 'call_error': value['engine_calls'][0]['error_type'] = 'RuntimeError'
        elif mutation == 'backwards_timestamp': value['engine_calls'][0]['finished_at'] = '2000-01-01T00:00:00+00:00'
        elif mutation == 'fake_global_activity': value['all_physical_edits_observable_claimed'] = True
        elif mutation == 'fake_quality': value['quality_recovery_difficulty_certified'] = True
        elif mutation == 'reordered_eligible': value['eligible_plan_edit_indices'].reverse()
        elif mutation == 'fake_prefilter': value['skipped_candidates'] = [{'plan_edit_index': 0}]
        elif mutation == 'boolean_setting_version': value['setting']['version'] = True
        elif mutation == 'boolean_eligible_indices': value['eligible_plan_edit_indices'] = [False, True]
        else: value['max_missed_root_attempts'] = 100
    rewrite_selection(revision, change)
    with pytest.raises(ValueError): freeze(revision, tmp_path / 'probe')
    assert not (tmp_path / 'probe').exists()


def test_terminal_receipt_cannot_float_from_canonical_selection(tmp_path, revision):
    selection = entry.read(revision.private / 'joint_control_selection.json')
    selection['passed'] = False; dump(revision.private / 'joint_control_selection.json', selection)
    with pytest.raises(ValueError): freeze(revision, tmp_path / 'probe')


@pytest.mark.parametrize('revision', [{'retry': True}], indirect=True)
def test_actual_failed_retry_history_is_bound_and_preserved(tmp_path, revision):
    selection = entry.read(revision.private / 'joint_control_selection.json')
    previous_ref = selection['prior_failed_attempts'][0]; old = Path(previous_ref['path']).read_bytes()
    result = freeze(revision, tmp_path / 'probe'); manifest = entry.read(result['path'])
    assert Path(previous_ref['path']).read_bytes() == old
    assert manifest['source_artifacts_sha256'][previous_ref['path']] == previous_ref['sha256']
    assert entry.read(previous_ref['path'])['state'] == 'failed'


@pytest.mark.parametrize('revision', [{'retry': True}], indirect=True)
def test_rehashed_wrong_failed_attempt_cannot_enter_the_success_history(tmp_path, revision):
    def change(value):
        previous = Path(value['prior_failed_attempts'][0]['path']); body = entry.read(previous)
        body['task_id'] = 'other-task'; dump(previous, body)
        value['prior_failed_attempts'][0] = ref(previous)
    rewrite_selection(revision, change)
    with pytest.raises(ValueError, match='dropped, rewritten or relabelled'):
        freeze(revision, tmp_path / 'probe')


@pytest.mark.parametrize('revision', [{'retry': True}], indirect=True)
def test_prior_failed_call_artifact_must_remain_hash_bound(tmp_path, revision):
    selection = entry.read(revision.private / 'joint_control_selection.json')
    previous = entry.read(selection['prior_failed_attempts'][0]['path'])
    Path(previous['engine_calls'][0]['input']['path']).unlink()
    with pytest.raises(ValueError, match='Changed public-priority artifact'):
        freeze(revision, tmp_path / 'probe')


@pytest.mark.parametrize('name', list(joint_controls.CONTROL_REWARDS))
def test_every_actual_standard_control_is_regraded(tmp_path, revision, name):
    path = revision.private / 'local_controls.json'; value = entry.read(path); value[name]['reward'] = 1 - value[name]['reward']; dump(path, value)
    def change(selection):
        selection['canonical_local_controls'] = ref(path)
        actual = Path(selection['local_controls']['path']); dump(actual, value); selection['local_controls'] = ref(actual)
    rewrite_selection(revision, change)
    with pytest.raises(ValueError, match='local control failed'):
        freeze(revision, tmp_path / 'probe')


def test_wrong_joint_proof_blocks_probe(tmp_path, revision, monkeypatch):
    def reject(*args): raise ValueError('Real joint source/complete D proof failed')
    monkeypatch.setattr(entry, 'validate_joint_certificate', reject)
    with pytest.raises(ValueError, match='complete D'):
        freeze(revision, tmp_path / 'probe')


def test_normal_instruction_replay_rejects_handwritten_public_text(tmp_path, revision):
    path = revision.public / 'instruction.md'; path.write_text(path.read_text() + '\nUndeclared manual instruction.')
    with pytest.raises(ValueError, match='normal InstructionNode'):
        freeze(revision, tmp_path / 'probe')


def test_history_rejects_same_exact_public_revision_before_output(tmp_path, revision, monkeypatch):
    history = tmp_path / 'history'; dump(history / 'selection_manifest.json',
        {'tasks': [{'revision_hash': revision.instruction['revision_hash']}]})
    monkeypatch.setattr(entry, 'development_history', lambda revision_hash, roots: entry.generic.development_history(revision_hash, [history]))
    with pytest.raises(ValueError, match='never resample'):
        freeze(revision, tmp_path / 'probe')
    assert not (tmp_path / 'probe').exists()


def test_factory_advancing_revision_during_snapshot_blocks_final_manifest(tmp_path, revision, monkeypatch):
    calls = []
    def snapshot(path):
        result = deepcopy(revision.snapshot); calls.append(True)
        if len(calls) > 1: result['tasks'][0]['revision'] = 1
        return result
    monkeypatch.setattr(entry, 'read_run', snapshot)
    with pytest.raises(ValueError, match='advanced to another revision'):
        freeze(revision, tmp_path / 'probe')
    assert not (tmp_path / 'probe/probe_manifest.json').exists()


def test_cli_has_no_run_or_model_generation_mode(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(entry, 'freeze_probe', lambda *args, **kw: calls.append((args, kw)) or {'offline': True})
    argv = ['--quality-run', str(tmp_path / 'run'), '--task-id', 'task', '--output', str(tmp_path / 'probe')]
    assert entry.main(argv) == 0 and len(calls) == 1
    with pytest.raises(SystemExit): entry.main([*argv, '--run'])
