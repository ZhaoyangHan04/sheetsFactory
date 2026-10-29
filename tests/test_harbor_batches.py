"""Offline scheduling/provenance tests; no real Harbor, Docker or model calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from openpyxl import Workbook
import pytest

from sheets_factory.core.audit import AuditStore
from sheets_factory.evaluation.harbor import export_harbor, inspect_export
from sheets_factory.pipelines.factory import FactoryPipeline

ROOT = Path(__file__).resolve().parents[1]


def setup_factory(tmp_path):
    config = {'project_root': str(ROOT), 'run_dir': str(tmp_path),
              'run': {'targets': {'financial_modeling': 20, 'debugging': 20}},
              'harbor': {'concurrency': 4}}
    audit = AuditStore(tmp_path, {'id': 'offline-control-scheduling-fixture'})
    return FactoryPipeline(config, audit, None, None), audit


def create_export(run_dir, audit, task_id, revision=0):
    source = run_dir / 'fixture_sources' / task_id / str(revision)
    (source / 'public').mkdir(parents=True)
    (source / 'private').mkdir()
    for name, value in [('public/input.xlsx', 0), ('private/goal.xlsx', 20 + revision)]:
        book = Workbook()
        book.active['A1'] = value
        book.save(source / name)
    text = f'Public fixture instruction revision {revision}. Read /app/input.xlsx and save /app/output.xlsx.'
    (source / 'public/instruction.md').write_text(text)
    revision_hash = hashlib.sha256(text.encode()).hexdigest()
    export = run_dir / 'SpreadsheetEval' / task_id
    export_harbor(source, export, {'task_id': task_id, 'mode': 'financial_modeling',
        'source_id': 'a' * 64, 'revision': revision, 'revision_hash': revision_hash})
    audit.task(task_id, mode='financial_modeling', source_id='a' * 64,
               status='ready', revision=revision, revision_hash=revision_hash)
    return export


def fake_controls(calls, *, omit=(), incorrect_reward=()):
    def run(export_root, output_dir, **kwargs):
        exports = sorted(path for path in export_root.iterdir() if path.is_dir())
        calls.append({'root': export_root, 'tasks': [path.name for path in exports], 'output': output_dir})
        result = {'per_task': {}, 'complete': True, 'expected_task_count': len(exports)}
        output_dir.mkdir(parents=True, exist_ok=True)
        for path in exports:
            binding = inspect_export(path)
            assert binding['task_name'] == 'sheetsfactory/' + path.name  # Staging must preserve the declared name.
            if path.name in omit:
                result['complete'] = False
                continue
            proof = {}
            for agent, reward in [('oracle', 1), ('nop', 0)]:
                result_file = output_dir / (path.name + '-' + agent + '.json')
                record = {'task_name': binding['task_name'], 'verifier_result': {'rewards': {'reward': reward}},
                          'exception_info': None}
                result_file.write_text(json.dumps(record))
                proof[agent] = {'task_name': binding['task_name'], 'reward': reward, 'expected': reward,
                    'matched': True, 'exception_info': None, 'result_file': str(result_file)}
            if path.name in incorrect_reward:
                proof['oracle']['reward'] = 0  # A misleading matched flag alone must not qualify.
            result['per_task'][binding['task_name']] = proof
        (output_dir / 'control_summary.json').write_text(json.dumps(result))
        return result
    return run


def task(audit, task_id):
    return next(item for item in audit.snapshot()['tasks'] if item['id'] == task_id)


def test_two_rounds_validate_only_new_outputs_and_keep_earlier_proof(tmp_path, monkeypatch):
    factory, audit = setup_factory(tmp_path)
    calls = []
    monkeypatch.setattr('sheets_factory.pipelines.factory.run_controls', fake_controls(calls))
    create_export(tmp_path, audit, 'fm-first')
    factory._validate_exports()
    first_proof = deepcopy(task(audit, 'fm-first')['harbor_controls'])
    assert task(audit, 'fm-first')['status'] == 'qualified'
    create_export(tmp_path, audit, 'fm-second')
    factory._validate_exports()
    factory._validate_exports()  # No new versions: no third batch.
    assert [call['tasks'] for call in calls] == [['fm-first'], ['fm-second']]
    assert calls[0]['root'] != calls[1]['root']
    assert task(audit, 'fm-first')['harbor_controls'] == first_proof
    summary = json.loads((tmp_path / 'harbor_controls.json').read_text())
    assert set(summary['per_task']) == {'sheetsfactory/fm-first', 'sheetsfactory/fm-second'}
    assert summary['per_task']['sheetsfactory/fm-first'] == first_proof
    assert len(summary['batches']) == 2
    assert all(Path(batch['summary_path']).is_file() for batch in summary['batches'])
    assert all(Path(batch['staging']).is_dir() for batch in summary['batches'])
    nodes = [node for node in audit.snapshot()['nodes'] if node['node'] == 'harbor_validation']
    assert len(nodes) == 2 and all(node['status'] == 'completed' and node['duration_ms'] >= 0 for node in nodes)
    assert all(node['summary_path'] for node in nodes)


def test_missing_current_batch_result_rejects_without_using_previous_reward(tmp_path, monkeypatch):
    factory, audit = setup_factory(tmp_path)
    calls = []
    monkeypatch.setattr('sheets_factory.pipelines.factory.run_controls', fake_controls(calls))
    create_export(tmp_path, audit, 'fm-first')
    factory._validate_exports()
    original = deepcopy(task(audit, 'fm-first')['harbor_controls'])
    create_export(tmp_path, audit, 'fm-missing')
    # A stale cumulative entry must be removed before looking at this batch.
    path = tmp_path / 'harbor_controls.json'
    summary = json.loads(path.read_text())
    summary['per_task']['sheetsfactory/fm-missing'] = original
    path.write_text(json.dumps(summary))
    monkeypatch.setattr('sheets_factory.pipelines.factory.run_controls', fake_controls(calls, omit=['fm-missing']))
    factory._validate_exports()
    assert task(audit, 'fm-first')['status'] == 'qualified'
    assert task(audit, 'fm-first')['harbor_controls'] == original
    assert task(audit, 'fm-missing')['status'] == 'rejected'
    assert task(audit, 'fm-missing')['harbor_controls'] == {}
    assert 'sheetsfactory/fm-missing' not in json.loads(path.read_text())['per_task']
    assert audit.snapshot()['nodes'][-1]['status'] == 'failed'
    assert list((tmp_path / 'rejected_exports').glob('fm-missing-harbor-*'))


def test_new_revision_cannot_reuse_old_qualified_controls(tmp_path, monkeypatch):
    factory, audit = setup_factory(tmp_path)
    calls = []
    monkeypatch.setattr('sheets_factory.pipelines.factory.run_controls', fake_controls(calls))
    create_export(tmp_path, audit, 'fm-revised', revision=0)
    factory._validate_exports()
    old = deepcopy(task(audit, 'fm-revised'))
    create_export(tmp_path, audit, 'fm-revised', revision=1)
    audit.task('fm-revised', status='qualified', harbor_controls=old['harbor_controls'],
               harbor_export_binding=old['harbor_export_binding'])
    factory._validate_exports()
    current = task(audit, 'fm-revised')
    assert len(calls) == 2
    assert current['status'] == 'qualified'
    assert current['harbor_export_binding']['revision'] == 1
    assert current['harbor_export_binding'] != old['harbor_export_binding']
    assert current['harbor_controls'] != old['harbor_controls']
    assert current['historical_harbor_controls'] == old['harbor_controls']
    summary = json.loads((tmp_path / 'harbor_controls.json').read_text())
    assert len(summary['batches']) == 2
    assert summary['batches'][0]['export_bindings']['sheetsfactory/fm-revised']['revision'] == 0


def test_missing_output_rejects_only_that_task_without_calling_harbor(tmp_path, monkeypatch):
    factory, audit = setup_factory(tmp_path)
    calls = []
    monkeypatch.setattr('sheets_factory.pipelines.factory.run_controls', fake_controls(calls))
    audit.task('fm-unexported', mode='financial_modeling', source_id='a' * 64, status='ready', revision=0)
    factory._validate_exports()
    assert not calls
    assert task(audit, 'fm-unexported')['status'] == 'rejected'
    assert 'missing or invalid' in task(audit, 'fm-unexported')['error']
    assert audit.snapshot()['nodes'][-1]['status'] == 'failed'


def test_changed_file_cannot_hide_behind_unchanged_manifest(tmp_path, monkeypatch):
    factory, audit = setup_factory(tmp_path)
    calls = []
    monkeypatch.setattr('sheets_factory.pipelines.factory.run_controls', fake_controls(calls))
    export = create_export(tmp_path, audit, 'fm-modified')
    factory._validate_exports()
    (export / 'instruction.md').write_text('Different unrecorded task')
    factory._validate_exports()
    assert len(calls) == 1
    assert task(audit, 'fm-modified')['status'] == 'rejected'
    assert 'differs from manifest' in task(audit, 'fm-modified')['error']


def test_matched_flag_without_correct_explicit_rewards_fails(tmp_path, monkeypatch):
    factory, audit = setup_factory(tmp_path)
    calls = []
    create_export(tmp_path, audit, 'fm-wrong-reward')
    monkeypatch.setattr('sheets_factory.pipelines.factory.run_controls', fake_controls(calls, incorrect_reward=['fm-wrong-reward']))
    factory._validate_exports()
    assert task(audit, 'fm-wrong-reward')['status'] == 'rejected'


def test_external_early_controls_with_matching_export_binding_are_reused(tmp_path, monkeypatch):
    factory, audit = setup_factory(tmp_path)
    export = create_export(tmp_path, audit, 'fm-early')
    early_jobs = tmp_path / 'early_control_jobs'
    early_jobs.mkdir()
    # Standalone early validator supplies actual frozen-export binding/proof.
    proof = fake_controls([])(export.parent, early_jobs)['per_task']['sheetsfactory/fm-early']
    audit.task('fm-early', status='qualified', harbor_controls=proof, harbor_export_binding=inspect_export(export))
    monkeypatch.setattr('sheets_factory.pipelines.factory.run_controls', lambda *args, **kwargs: pytest.fail('Unchanged bound early proof must be reused'))
    factory._validate_exports()
    assert task(audit, 'fm-early')['harbor_controls'] == proof
    cumulative = json.loads((tmp_path / 'harbor_controls.json').read_text())
    assert cumulative['per_task']['sheetsfactory/fm-early'] == proof
    assert not cumulative['batches']
    assert str(early_jobs / 'control_summary.json') in cumulative['summary_paths']
