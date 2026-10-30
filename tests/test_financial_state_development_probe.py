"""Offline snapshot checks. No financial workbook, LO, provider, or model runs."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_financial_state_probe_test',
    ROOT / 'scripts/prepare_financial_state_development_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')
    return probe.reference(path)


@pytest.fixture(scope='module')
def full_plan():
    edits = [{'sheet': 'Finance', 'cell': 'C' + str(i), 'before': '=1', 'after': None}
             for i in range(1, 60194)]
    keys = [(edit['sheet'], edit['cell']) for edit in edits]
    group = {'sheet': 'Finance', 'range': 'C1:C60193', 'reason': 'Offline fixture', 'business_rule': 'Offline fixture'}
    proposal = {'edits': [], 'mask_ranges': [group], 'public_instruction': probe.provider.INSTRUCTION,
        'public_rules': [probe.RULE, *probe.provider.STATE_RULES], 'full_state_fm_selection': {
            'version': 1, 'target_count': 60193, 'original_financial_target_count': 46339,
            'additional_state_target_count': 13854, 'original_financial_targets_preserved_exactly': True,
            'all_targets_sha256': probe.canonical(sorted(keys)), 'quality_or_difficulty_certified': False}}
    plan = {key: deepcopy(value) for key, value in proposal.items() if key != 'mask_ranges'}
    plan['edits'] = edits
    plan['range_authoring_receipt'] = {'baseline_sha256': 'offline-source', 'source_workbook_modified': False,
        'expanded_edit_count': 60193, 'groups': [{'proposal': group}]}
    application = {'kind': 'full_state_FM_original_audit_target_coverage', 'source': {'sha256': 'offline-source'},
        'target_count': 60193, 'plan_sha256': probe.canonical(proposal),
        'all_targets_independently_audited': True, 'quality_or_difficulty_certified': False,
        'cell_proofs': [{'sheet': sheet, 'cell': cell} for sheet, cell in keys],
        'audits': {name: {} for name in ('lease', 'programme', 'operating', 'holding', 'contingent')}}
    return plan, application


def test_exact_normal_compilation_and_application_binding(full_plan):
    plan, app = full_plan
    assert len(probe.validate_plan_application(plan, app, 'offline-source')) == 60193


@pytest.mark.parametrize('case', ['count', 'duplicate', 'after', 'before', 'scope', 'rules', 'fingerprint',
                                 'source', 'proposal_hash', 'coverage', 'audit_module', 'policy_version'])
def test_full_state_binding_changes_fail_closed(full_plan, case):
    plan, app = deepcopy(full_plan)
    if case == 'count': plan['edits'].pop()
    elif case == 'duplicate': plan['edits'][-1] = deepcopy(plan['edits'][0])
    elif case == 'after': plan['edits'][0]['after'] = '=2'
    elif case == 'before': plan['edits'][0]['before'] = 1
    elif case == 'scope': plan['public_instruction'] = 'Missing explicit scope'
    elif case == 'rules': plan['public_rules'] = [probe.RULE]
    elif case == 'fingerprint': plan['full_state_fm_selection']['all_targets_sha256'] = 'changed'
    elif case == 'source': plan['range_authoring_receipt']['baseline_sha256'] = 'changed'
    elif case == 'proposal_hash': app['plan_sha256'] = 'changed'
    elif case == 'coverage': app['cell_proofs'].pop()
    elif case == 'audit_module': app['audits'].pop('contingent')
    elif case == 'policy_version': plan['full_state_fm_selection']['version'] = True
    with pytest.raises(ValueError):
        probe.validate_plan_application(plan, app, 'offline-source')


def nodes(task='task', revision=0):
    return [{'task_id': task, 'revision': revision, 'node': name, 'status': 'completed'} for name in probe.NORMAL_NODES]


@pytest.mark.parametrize('case', ['missing', 'running', 'wrong_revision', 'later_failure'])
def test_six_current_normal_nodes_are_required(case):
    records = nodes()
    if case == 'missing': records.pop()
    elif case == 'running': records[-1]['status'] = 'running'
    elif case == 'wrong_revision': records[-1]['revision'] = 1
    else: records.append({**records[-1], 'status': 'failed'})
    with pytest.raises(ValueError, match='has not completed'):
        probe.require_completed_nodes({'nodes': records}, 'task', 0)


def test_reused_public_revision_is_rejected_without_score_inspection(tmp_path):
    first = dump(tmp_path / 'first/selection_manifest.json', {'tasks': [{'revision_hash': 'old', 'reward': 1}]})
    assert probe.development_history('new', [tmp_path, first['path']]) == [first]
    with pytest.raises(ValueError, match='already have a model selection'):
        probe.development_history('old', [tmp_path])


def test_changed_and_symlink_evidence_are_rejected(tmp_path):
    path = tmp_path / 'evidence.json'
    ref = dump(path, {'offline': True})
    path.write_text('{"offline": false}')
    with pytest.raises(ValueError, match='bytes or SHA changed'):
        probe.bind_references(ref, {})
    link = tmp_path / 'link'; link.symlink_to(path)
    with pytest.raises(ValueError, match='non-symlink'):
        probe.reference(link)


@pytest.fixture
def snapshot_fixture(tmp_path, monkeypatch):
    run = tmp_path / 'run'; run.mkdir()
    task_id = 'fm-offline-fixture'
    revision = run / 'tasks' / task_id / 'revisions/000'
    public, private = revision / 'public', revision / 'private'
    public.mkdir(parents=True); private.mkdir()
    original = tmp_path / 'source.xlsx'; original.write_bytes(b'Offline placeholder, not a financial workbook')
    source_id = probe.sha(original)
    (private / 'goal.xlsx').write_bytes(original.read_bytes())
    (public / 'input.xlsx').write_bytes(b'Offline masked placeholder')
    policy = probe.reference(ROOT / 'config/task_adapters/composite_full_state_fm_v1.json')
    plan = {'edits': [{'sheet': 'Finance', 'cell': 'C3', 'before': '=1', 'after': None}],
        'public_instruction': probe.provider.INSTRUCTION, 'public_rules': [probe.RULE, *probe.provider.STATE_RULES],
        'full_state_fm_selection': {'fixture': True}}
    config = {'construction': {'instruction_style': 'business_brief'}, 'engine': {'image': 'offline-runtime-fixture'},
        probe.provider.POLICY: {'version': 1, 'policy': policy}, 'run_dir': str(run)}
    probe.InstructionNode().execute(SimpleNamespace(data={'plan': plan, 'input': public / 'input.xlsx'},
        mode='financial_modeling', config=config, revision_dir=revision))
    grade_base = {'structure_ok': True, 'expected_change_count': 1, 'expected_changes': ['Finance!C3']}
    controls = {key: {**grade_base, 'reward': reward} for key, reward in probe.CONTROL_REWARDS.items()}
    dump(private / 'local_controls.json', controls)
    dump(private / 'plan.json', plan)
    dump(private / 'composite_full_state_fm_application.json', {'policy': policy})
    dump(private / 'expected_delta.json', controls['oracle'])
    for name in ('native_risk_guard.json', 'native_error_probe.json'):
        dump(private / name, {'blocking': False})
    for name in ('edit_validation.json', 'root_impacts.json'):
        dump(private / name, {})
    dump(public / 'profile.json', {})
    for name in ('equivalent', 'missed_root', 'extra_change'):
        p = private / 'controls' / (name + '.xlsx'); p.parent.mkdir(exist_ok=True); p.write_bytes(b'Offline control ' + name.encode())
    for name in ('preflight_manifest.json', 'resolved_config.yaml', 'seed_manifest.json'):
        (run / name).write_text('{}')
    dump(run / 'sources' / source_id[:12] / 'stability.json', {'fixture': True})
    offline = dump(tmp_path / 'offline_admission.json', {'fixture': True})
    seed = {'sha256': source_id, 'local_path': str(original), 'finance_evidence': {}}
    snapshot = {'tasks': [{'id': task_id, 'mode': 'financial_modeling', 'revision': 0, 'source_id': source_id}],
        'nodes': nodes(task_id), 'run': {'status': 'running'}}
    monkeypatch.setattr(probe, 'validate_preparation', lambda r: ({'recipe_sha256': {}}, config, seed))
    monkeypatch.setattr(probe, 'read_run', lambda r: snapshot)
    monkeypatch.setattr(probe, 'validate_plan_application', lambda *a: {('Finance', 'C3')})
    monkeypatch.setattr(probe, 'bind_offline_admission', lambda *a: offline)
    monkeypatch.setattr(probe, 'development_history', lambda *a: [])
    compared, exported = [], []
    def compare(source, goal, candidate):
        key = 'oracle' if Path(candidate) == goal else 'nop' if Path(candidate) == source else Path(candidate).stem
        compared.append(key)
        return deepcopy(controls[key])
    monkeypatch.setattr(probe, 'compare_workbooks', compare)
    def export(self, ctx):
        exported.append(ctx)
        target = Path(ctx.config['run_dir']) / 'SpreadsheetEval' / task_id
        (target / 'environment').mkdir(parents=True); (target / 'tests').mkdir()
        shutil.copyfile(public / 'instruction.md', target / 'instruction.md')
        shutil.copyfile(public / 'input.xlsx', target / 'environment/input.xlsx')
        shutil.copyfile(private / 'goal.xlsx', target / 'tests/reference.xlsx')
        return {'export_dir': target}
    monkeypatch.setattr(probe.ExportNode, 'execute', export)
    monkeypatch.setattr(probe, 'inspect_export', lambda target: {'fixture': True})
    return SimpleNamespace(run=run, task_id=task_id, output=tmp_path / 'snapshot', offline=offline,
        snapshot=snapshot, compared=compared, exported=exported, controls=controls, private=private)


def test_snapshot_replays_instruction_exports_actual_bytes_and_launches_no_models(snapshot_fixture):
    f = snapshot_fixture
    ref = probe.freeze_probe(f.run, f.task_id, 0, f.output, offline_admission=f.offline['path'])
    manifest = probe.read_ref(ref)
    assert f.compared == list(probe.CONTROL_REWARDS) and len(f.exported) == 1
    assert manifest['normal_InstructionNode_replay_exact'] and manifest['normal_ExportNode_called_on_actual_task']
    assert manifest['new_model_calls_during_preparation'] == manifest['new_LO_calls_during_preparation'] == 0
    assert manifest['qualified'] is False and manifest['task_count'] == 0
    assert manifest['actual_harbor_control_jobs_launched'] is False
    assert manifest['independent_recovery_verified_at_snapshot'] is False
    assert manifest['execution_budget']['tool_budget_seconds'] == 1800
    assert probe.validate_selection_execution_budget(manifest) == probe.BUDGET


def test_not_ready_does_not_write_snapshot_or_export(snapshot_fixture):
    f = snapshot_fixture; f.snapshot['nodes'][-1]['status'] = 'running'
    with pytest.raises(ValueError, match='has not completed'):
        probe.freeze_probe(f.run, f.task_id, 0, f.output, offline_admission=f.offline['path'])
    assert not f.output.exists() and not f.exported and not f.compared


def test_failed_local_control_blocks_before_export(snapshot_fixture, monkeypatch):
    f = snapshot_fixture
    monkeypatch.setattr(probe, 'compare_workbooks', lambda *a: {'reward': 1})
    with pytest.raises(ValueError, match='control failed or changed'):
        probe.freeze_probe(f.run, f.task_id, 0, f.output, offline_admission=f.offline['path'])
    assert not f.output.exists() and not f.exported


def test_snapshot_is_never_overwritten(snapshot_fixture):
    f = snapshot_fixture; f.output.mkdir(); marker = f.output / 'original'; marker.write_text('keep')
    with pytest.raises(ValueError, match='fresh'):
        probe.freeze_probe(f.run, f.task_id, 0, f.output, offline_admission=f.offline['path'])
    assert marker.read_text() == 'keep' and not f.exported
