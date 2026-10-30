"""Offline routing/export checks; fixture admission is explicitly mocked."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import openpyxl
import pytest
import yaml

from sheets_factory.evaluation.harbor import inspect_export
from sheets_factory.nodes.construction import InstructionNode
from sheets_factory.task_adapters.public_input_priority import RULE
from sheets_factory.task_adapters.public_workbook_scope import CLAUSES, POLICY, reference
from sheets_factory.workbook import compare_workbooks

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('full_graph_probe_entry', ROOT / 'scripts/prepare_full_graph_development_probe.py')
entry = importlib.util.module_from_spec(spec); spec.loader.exec_module(entry)


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def workbook(path, formula, cached, *, extra=False):
    book = openpyxl.Workbook(); book.active.title = 'Model'
    book.active['A1'] = formula; book.active['B1'] = 'Provided input'
    if extra: book.active['C1'] = 'Extra value'
    book.save(path); book.close()
    with zipfile.ZipFile(path) as archive:
        files = {n: archive.read(n) for n in archive.namelist()}
    text = files['xl/worksheets/sheet1.xml'].decode()
    text = text.replace('<v></v>', '<v />').replace('<v />', '<v>' + str(cached) + '</v>', 1)
    files['xl/worksheets/sheet1.xml'] = text.encode()
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, raw in files.items(): archive.writestr(name, raw)


@pytest.fixture
def actual_revision(tmp_path, monkeypatch):
    run = tmp_path / 'run'; private = run / 'tasks/dbg-unit/revisions/000/private'
    public = private.parent / 'public'
    private.mkdir(parents=True); public.mkdir()
    controls = private / 'controls'; controls.mkdir()
    source = public / 'input.xlsx'; goal = private / 'goal.xlsx'
    workbook(source, '=2', 2); workbook(goal, '=1', 1)
    for name, formula, cached, extra in [('equivalent', '=IF(TRUE(),1,"")', 1, False),
                                         ('missed_root', '=2', 2, False), ('extra_change', '=1', 1, True)]:
        workbook(controls / (name + '.xlsx'), formula, cached, extra=extra)
    config = {'run_dir': str(run), 'project_root': str(ROOT), 'construction': {'instruction_style': 'business_brief'},
        'engine': {'image': 'sheetsfactory-lo:24.2-iterative-openpyxl315-v1'},
        'diagnosis': {'difficulty_deferred': False}, 'run': {'targets': {'financial_modeling': 0, 'debugging': 1}}}
    plan = {'public_instruction': 'Repair the financial formulas.\n\n' + CLAUSES['debugging'],
        'public_rules': [RULE], 'edits': [{'sheet': 'Model', 'cell': 'A1', 'before': '=1', 'after': '=2'}]}
    ctx = type('Context', (), {'data': {'plan': plan, 'input': source}, 'mode': 'debugging',
        'config': config, 'revision_dir': private.parent})()
    instruction = InstructionNode().execute(ctx)
    dump(private / 'plan.json', plan); dump(public / 'profile.json', {'unit_fixture': True})
    dump(private / 'expected_delta.json', compare_workbooks(source, goal, goal))
    dump(private / 'joint_repair_certificate.json', {'unit_fixture': True})
    reports = {name: compare_workbooks(source, goal, goal if name == 'oracle' else source if name == 'nop'
                                      else controls / (name + '.xlsx')) for name in entry.CONTROL_REWARDS}
    dump(private / 'local_controls.json', reports)
    dump(run / 'preflight_manifest.json', {'unit_fixture': True})
    dump(run / 'seed_manifest.json', {'unit_fixture': True})
    (run / 'resolved_config.yaml').write_text(yaml.safe_dump(config))
    seed = {'sha256': entry.digest(goal), 'local_path': str(goal)}
    snapshot = {'tasks': [{'id': 'dbg-unit', 'mode': 'debugging', 'revision': 0, 'source_id': seed['sha256']}],
        'nodes': [{'task_id': 'dbg-unit', 'node': node, 'revision': 0, 'status': 'completed'}
                  for node in ('normalize', 'profile', 'plan', 'construct', 'instruction', 'precheck')]}
    monkeypatch.setattr(entry, 'validate_run_preparation', lambda r: ({'unit_fixture': True}, config, seed))
    monkeypatch.setattr(entry, 'read_run', lambda r: deepcopy(snapshot))
    monkeypatch.setattr(entry, 'validate_joint_certificate', lambda *a: {'unit_fixture': True, 'complete_required_D_count': 1})
    monkeypatch.setattr(entry, 'development_history', lambda *a: [])
    return run, private, public, snapshot, instruction


def test_probe_uses_actual_normal_instruction_and_export_without_touching_run(tmp_path, actual_revision):
    run, private, public, _, instruction = actual_revision
    before = {p: entry.digest(p) for p in run.rglob('*') if p.is_file()}
    result = entry.freeze_probe(run, 'dbg-unit', 0, tmp_path / 'probe')
    manifest = entry.read(result['path']); task = manifest['tasks'][0]
    assert task['revision_hash'] == instruction['revision_hash']
    assert task['local_controls'] == {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}
    assert inspect_export(task['task_directory']) == task['harbor_export_binding']
    assert (Path(task['task_directory']) / 'instruction.md').read_bytes() == (public / 'instruction.md').read_bytes()
    assert manifest['quality_pending'] and not manifest['qualified'] and manifest['task_count'] == 0
    assert manifest['normal_ExportNode_called_on_actual_revision']
    assert manifest['new_model_calls_during_preparation'] == manifest['new_LO_calls'] == 0
    assert task['execution_budget'] == entry.BUDGET and task['tool_time_policy']['version'] == 2
    assert {p: entry.digest(p) for p in before} == before
    assert not (run / 'SpreadsheetEval').exists() and not (run / 'tasks/dbg-unit/lineage.json').exists()


@pytest.mark.parametrize('node', ['normalize', 'profile', 'plan', 'construct', 'instruction', 'precheck'])
def test_incomplete_or_wrong_revision_factory_nodes_cannot_admit_probe(tmp_path, actual_revision, node):
    run, _, _, snapshot, _ = actual_revision
    next(n for n in snapshot['nodes'] if n['node'] == node)['status'] = 'running'
    with pytest.raises(ValueError, match='has not completed'):
        entry.freeze_probe(run, 'dbg-unit', 0, tmp_path / 'probe')
    assert not (tmp_path / 'probe').exists()


@pytest.mark.parametrize('control', list(entry.CONTROL_REWARDS))
def test_missing_or_false_control_blocks_early_model_admission(tmp_path, actual_revision, control):
    run, private, _, _, _ = actual_revision
    reports = entry.read(private / 'local_controls.json'); reports[control]['reward'] = 1 - entry.CONTROL_REWARDS[control]
    dump(private / 'local_controls.json', reports)
    with pytest.raises(ValueError, match='control failed'):
        entry.freeze_probe(run, 'dbg-unit', 0, tmp_path / 'probe')


def test_handwritten_instruction_cannot_replace_normal_public_bytes(tmp_path, actual_revision):
    run, _, public, _, _ = actual_revision
    with (public / 'instruction.md').open('a') as stream: stream.write('\nUndeclared manual instruction.')
    with pytest.raises(ValueError, match='normal InstructionNode'):
        entry.freeze_probe(run, 'dbg-unit', 0, tmp_path / 'probe')


def test_joint_certificate_failure_blocks_probe(tmp_path, monkeypatch, actual_revision):
    def reject(*a): raise ValueError('Actual complete-D certificate differs')
    monkeypatch.setattr(entry, 'validate_joint_certificate', reject)
    with pytest.raises(ValueError, match='complete-D'):
        entry.freeze_probe(actual_revision[0], 'dbg-unit', 0, tmp_path / 'probe')


def test_development_selection_history_rejects_same_public_revision(tmp_path):
    path = tmp_path / 'old/selection_manifest.json'; dump(path, {'tasks': [{'revision_hash': 'already-selected'}]})
    with pytest.raises(ValueError, match='never resample'):
        entry.development_history('already-selected', [tmp_path])
    assert entry.development_history('new-public-revision', [tmp_path]) == [reference(path)]


def test_cli_never_starts_model_or_production(tmp_path, monkeypatch):
    observed = []
    monkeypatch.setattr(entry, 'prepare_scoped_factory', lambda *args: observed.append(args) or {'unit_fixture': True})
    assert entry.main(['--factory-prepared', str(tmp_path / 'old'), '--output', str(tmp_path / 'new')]) == 0
    assert len(observed) == 1
    with pytest.raises(SystemExit): entry.main(['--factory-prepared', str(tmp_path / 'old'), '--output', str(tmp_path / 'new'), '--run'])


def test_scoped_fresh_preparation_preserves_joint_construct_and_old_artifacts(tmp_path, monkeypatch):
    old = tmp_path / 'old'; old.mkdir(); source = old / 'source.xlsx'; source.write_bytes(b'unit-source')
    registry = old / 'nodes.yaml'; nodes = yaml.safe_load((ROOT / 'config/task_adapters/scc_activity_nodes.yaml').read_text())['nodes']
    registry.write_text(yaml.safe_dump({'version': 1, 'nodes': nodes}))
    config = {'pipeline': {'node_registry': str(registry)}, 'run_dir': str(old), 'engine': {'image': 'unit'},
        'run': {'targets': {'financial_modeling': 0, 'debugging': 1}, **{k: 2 for k in entry.factory.PROTECTED_BUDGETS}},
        'agents': {'model': 'gpt-6-sol', 'reasoning_effort': 'high'}, entry.factory.JOINT_SETTING: {'bindings': {}}}
    (old / 'resolved_config.yaml').write_text(yaml.safe_dump(config))
    dump(old / 'seed_manifest.json', {'selected': [{'sha256': entry.digest(source), 'local_path': str(source)}], 'development_only': True})
    dump(old / 'activity_bindings.json', {'unit_fixture': True})
    frozen = {'count': 1, 'development_only': True, 'source_order': [entry.digest(source)], 'recipe_sha256': {},
        'source_artifacts_sha256': {}, 'resolved_config': reference(old / 'resolved_config.yaml')}
    dump(old / 'preflight_manifest.json', frozen)
    monkeypatch.setattr(entry.factory, 'validate_prepared', lambda path: deepcopy(frozen))
    before = {p: entry.digest(p) for p in old.rglob('*') if p.is_file()}
    out = tmp_path / 'new'; result = entry.prepare_scoped_factory(old, out)
    prepared = entry.read(result['path']); after = yaml.safe_load((out / 'resolved_config.yaml').read_text())
    composed = yaml.safe_load(Path(after['pipeline']['node_registry']).read_text())['nodes']
    assert composed['construct'] == nodes['construct']
    assert composed['plan'].endswith(':ScopeFullGraphPlanNode')
    assert {k: v for k, v in composed.items() if k not in ('plan', 'repair')} == {k: v for k, v in nodes.items() if k not in ('plan', 'repair')}
    assert after['agents'] == config['agents'] and after['run']['targets'] == config['run']['targets']
    assert after[POLICY]['version'] == 1 and prepared['scope_preparation_addendum']
    assert {p: entry.digest(p) for p in before} == before and not (out / 'run.sqlite').exists()
