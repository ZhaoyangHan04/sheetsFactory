"""Batch binding/routing fixtures; no LibreOffice or model execution occurs."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import threading
import time

from openpyxl import Workbook
import pytest

from sheets_factory.evaluation.harbor import export_harbor, inspect_export


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('prepare_composite_batch_fixture', ROOT / 'scripts/prepare_composite_batch.py')
batch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch)


def write(path, value):
    path.write_text(json.dumps(value, indent=2))
    return batch.reference(path)


def snapshot(directory):
    return {str(path.relative_to(directory)): batch.sha(path) for path in directory.rglob('*') if path.is_file()}


@pytest.fixture
def source_batch(tmp_path):
    directory = tmp_path / 'source_batch'
    directory.mkdir()
    selected = []
    for index in range(10):
        source = directory / ('source-' + str(index))
        private = source / 'private'
        private.mkdir(parents=True)
        workbook = source / 'model.xlsx'
        book = Workbook()
        book.active['A1'] = index
        book.active['B1'] = '=A1+1'
        book.save(workbook)
        book.close()
        identity = batch.sha(workbook)
        config = write(source / 'config.json', {})
        audits = {name: {'passed': True, 'checked_cells': 1, 'fixture_only': True}
                  for name in ('lease', 'programme', 'operating', 'holding')}
        for name in audits:
            write(private / (name + '_financial_audit.json'), {**audits[name], 'workbook': {'sha256': identity}})
        proofs = {name: write(source / (name + '.json'), {'fixture_only': True})
                  for name in ('financial_audit', 'public_scenarios')}
        first, second = private / 'first.xlsx', private / 'second.xlsx'
        shutil.copy2(workbook, first)
        shutil.copy2(workbook, second)
        proofs['stability'] = write(private / 'stability.json', {'stable': True, 'fixture_only': True,
            'comparison': {'reward': 1}, 'first_against_goal': {'reward': 1},
            'second_against_goal': {'reward': 1}, 'first': str(first), 'second': str(second)})
        entry = {'sha256': identity, 'source_sha256': identity, 'local_path': str(workbook),
                 'finance_evidence': {'financial_seed_verified': True}}
        manifest = source / 'seed_manifest.json'
        write(manifest, {'status': 'independently_verified_composed_financial_seed', 'fixture_only': True,
            'financial_audit_passed': True, 'financial_audits': audits, 'config': config,
            'runtime': {'image_id': batch.verify_built_source.__globals__['RUNTIME_ID']},
            'local_path': str(workbook), 'derived_workbook_sha256': identity, **proofs, 'selected': [entry]})
        selected.append({**entry, 'profile_id': f'C{index + 1:02d}-fixture',
                         'source_manifest': batch.reference(manifest)})
    selection = write(directory / 'source_selection.json', {
        'profiles': [item['profile_id'] for item in selected], 'model_results_consulted': False})
    plan = write(directory / 'plan.json', {'fixture_only': True})
    scenario = write(directory / 'scenario.json', {'fixture_only': True})
    manifest = directory / 'seed_manifest.json'
    write(manifest, {'status': 'independently_verified_composed_financial_seed_batch', 'mode': 'build',
        'fixture_only': True, 'recipe_unchanged': True, 'verified_derived_workbook_count': 10,
        'target_derived_workbook_count': 10, 'model_scores_consulted': False, 'selected': selected,
        'source_selection': selection, 'plan': plan, 'scenario_config': scenario})
    return manifest


@pytest.fixture
def offline_prepare(monkeypatch):
    observed = {'calls': [], 'fail_index': None, 'during': None, 'active': 0, 'maximum': 0}
    lock = threading.Lock()

    def prepare(source_manifest, output, mode, **options):
        source_manifest, output = Path(source_manifest), Path(output)
        source = json.loads(source_manifest.read_text())
        identity = source['selected'][0]['sha256']
        task_id = ('fm-' if mode == 'financial_modeling' else 'dbg-') + identity[:12]
        # Every source, not only this task, must be frozen before any work.
        frozen = json.loads((output.parents[1] / 'selection_manifest.json').read_text())
        assert len(frozen['sources']) == 10 and frozen['model_results_consulted'] is False
        with lock:
            observed['active'] += 1
            observed['maximum'] = max(observed['maximum'], observed['active'])
            observed['calls'].append({'source': str(source_manifest), 'mode': mode,
                'options': {k: v for k, v in options.items() if k != 'progress'}})
        try:
            output.mkdir(parents=True)
            if observed['during']:
                observed['during']()
            if source_manifest.parent.name == 'source-' + str(observed['fail_index']):
                write(output / 'preparation_failure.json', {'fixture_only': True, 'error': 'fixture controls failed'})
                raise ValueError('fixture controls failed')
            options['progress'](task_id=task_id, node='fixture_node', status='running')
            time.sleep(.01)
            revision = output / 'revision'
            (revision / 'public').mkdir(parents=True)
            (revision / 'private').mkdir()
            shutil.copy2(source['local_path'], revision / 'public/input.xlsx')
            shutil.copy2(source['local_path'], revision / 'private/goal.xlsx')
            (revision / 'public/instruction.md').write_text('Explicit offline batch fixture.')
            task = {'task_id': task_id, 'mode': mode, 'source_id': identity,
                    'revision': 0, 'revision_hash': identity, 'fixture_only': True}
            export = export_harbor(revision, output / 'SpreadsheetEval' / task_id, task, ROOT)
            task.update(task_directory=str(export), harbor_export_binding=inspect_export(export))
            result = {'selected_task_ids': [task_id], 'tasks': [task],
                'source_manifest': batch.reference(source_manifest), 'qualified': False, 'task_count': 0,
                'llm_calls': 0, 'model_evaluation_performed': False,
                'local_controls': dict(batch.CONTROL_REWARDS), 'fixture_only': True}
            write(output / 'probe_manifest.json', result)
            options['progress'](task_id=task_id, node='fixture_node', status='completed', duration_ms=0)
            return result
        finally:
            with lock:
                observed['active'] -= 1

    monkeypatch.setattr(batch, 'prepare', prepare)
    return observed


def test_default_batch_freezes_every_source_in_original_order_then_prepares_sequentially(tmp_path, source_batch, offline_prepare):
    before = snapshot(source_batch.parent)
    result = batch.prepare_batch(source_batch, tmp_path / 'prepared')
    selected = json.loads(source_batch.read_text())['selected']
    assert [call['source'] for call in offline_prepare['calls']] == [item['source_manifest']['path'] for item in selected]
    assert all(call['mode'] == 'financial_modeling' and call['options'] == {
        'root_impact_validation': 'strict', 'composite_activity': False} for call in offline_prepare['calls'])
    assert offline_prepare['maximum'] == 1
    assert result['prepared_task_count'] == 10 and result['failed_preparations'] == 0
    assert result['status'] == 'prepared' and result['qualified'] is False
    assert result['task_count'] == result['llm_calls'] == 0
    assert result['model_evaluation_performed'] is False and 'pending' in result['quality_status']
    assert [task['source_id'] for task in result['tasks']] == [item['sha256'] for item in selected]
    assert all(Path(task['task_directory']).parent == tmp_path / 'prepared/SpreadsheetEval' for task in result['tasks'])
    assert all(inspect_export(task['task_directory']) == task['harbor_export_binding'] for task in result['tasks'])
    assert snapshot(source_batch.parent) == before
    summary = json.loads((tmp_path / 'prepared/audit/summary.json').read_text())
    assert summary['run']['producer_active'] is False and summary['metrics']['qualified'] == 0
    assert summary['metrics']['llm_calls'] == 0 and len(summary['nodes']) == 10


def test_explicit_debugging_routes_activity_and_shadow_with_at_most_two_workers(tmp_path, source_batch, offline_prepare):
    result = batch.prepare_batch(source_batch, tmp_path / 'prepared', 'debugging', workers=2,
        root_impact_validation='shadow_roots', composite_activity=True)
    assert 1 <= offline_prepare['maximum'] <= 2
    assert all(call['mode'] == 'debugging' and call['options'] == {
        'root_impact_validation': 'shadow_roots', 'composite_activity': True} for call in offline_prepare['calls'])
    assert [attempt['source_id'] for attempt in result['attempts']] == [
        entry['sha256'] for entry in json.loads(source_batch.read_text())['selected']]
    assert result['prepared_task_count'] == 10


def test_failed_preparation_preserves_failure_and_continues_remaining_frozen_sources(tmp_path, source_batch, offline_prepare):
    offline_prepare['fail_index'] = 3
    output = tmp_path / 'prepared'
    result = batch.prepare_batch(source_batch, output)
    assert len(offline_prepare['calls']) == 10
    assert result['status'] == 'partial_preparation' and result['prepared_task_count'] == 9
    assert result['failed_preparations'] == 1 and result['qualified'] is False
    failed = result['attempts'][3]
    assert failed['status'] == 'failed' and 'fixture controls failed' in failed['error']['reason']
    assert (output / 'failures' / (failed['task_id'] + '.json')).is_file()
    assert (Path(failed['probe_directory']) / 'preparation_failure.json').is_file()
    assert not (output / 'SpreadsheetEval' / failed['task_id']).exists()
    assert json.loads((output / 'audit/summary.json').read_text())['metrics']['rejected'] == 1


@pytest.mark.parametrize('defect', ['partial_status', 'under_ten', 'duplicate_sha', 'source_sha', 'source_manifest_sha',
    'order', 'changed_workbook', 'changed_component_proof', 'recipe_changed'])
def test_invalid_or_changed_source_batch_is_rejected_before_any_prepare(tmp_path, source_batch, offline_prepare, defect):
    document = json.loads(source_batch.read_text())
    if defect == 'partial_status':
        document['status'] = 'partial_source_batch'
    elif defect == 'under_ten':
        document['selected'] = document['selected'][:9]
    elif defect == 'duplicate_sha':
        document['selected'][1] = deepcopy(document['selected'][0])
    elif defect == 'source_sha':
        document['selected'][0]['source_sha256'] = 'f' * 64
    elif defect == 'source_manifest_sha':
        document['selected'][0]['source_manifest']['sha256'] = 'f' * 64
    elif defect == 'order':
        document['selected'].reverse()
    elif defect == 'changed_workbook':
        Path(document['selected'][-1]['local_path']).write_bytes(b'changed')
    elif defect == 'changed_component_proof':
        path = Path(document['selected'][-1]['source_manifest']['path']).parent / 'private/holding_financial_audit.json'
        proof = json.loads(path.read_text())
        proof['passed'] = False
        write(path, proof)
    else:
        document['recipe_unchanged'] = False
    write(source_batch, document)
    output = tmp_path / 'prepared'
    with pytest.raises(ValueError):
        batch.prepare_batch(source_batch, output)
    assert not offline_prepare['calls'] and not (output / 'selection_manifest.json').exists()
    assert (output / 'batch_failure.json').is_file()


def test_source_manifest_mutation_after_freeze_invalidates_batch_success(tmp_path, source_batch, offline_prepare):
    def mutate():
        source_batch.write_text(source_batch.read_text() + ' ')
        offline_prepare['during'] = None

    offline_prepare['during'] = mutate
    output = tmp_path / 'prepared'
    with pytest.raises(ValueError, match='changed during preparation'):
        batch.prepare_batch(source_batch, output)
    assert (output / 'selection_manifest.json').is_file()
    assert not (output / 'preparation_manifest.json').exists()
    assert (output / 'batch_failure.json').is_file()


def test_source_manifest_changed_while_validating_cannot_replace_declared_sha(tmp_path, source_batch, offline_prepare, monkeypatch):
    actual_validate = batch.validate_source_manifest
    changed = False

    def mutate_before_read(path):
        nonlocal changed
        if not changed:
            path.write_text(path.read_text() + ' ')
            changed = True
        return actual_validate(path)

    monkeypatch.setattr(batch, 'validate_source_manifest', mutate_before_read)
    output = tmp_path / 'prepared'
    with pytest.raises(ValueError, match='changed during preparation'):
        batch.prepare_batch(source_batch, output)
    assert not offline_prepare['calls'] and not (output / 'selection_manifest.json').exists()
    assert (output / 'batch_failure.json').is_file()


@pytest.mark.parametrize('workers', [0, 3, True])
def test_unsupported_worker_count_rejects_before_output_or_prepare(tmp_path, source_batch, offline_prepare, workers):
    output = tmp_path / 'prepared'
    with pytest.raises(ValueError, match='one or two'):
        batch.prepare_batch(source_batch, output, workers=workers)
    assert not output.exists() and not offline_prepare['calls']


def test_existing_output_and_output_inside_source_are_never_modified(tmp_path, source_batch, offline_prepare):
    output = tmp_path / 'prepared'
    output.mkdir()
    (output / 'keep').write_text('existing evidence')
    with pytest.raises(FileExistsError):
        batch.prepare_batch(source_batch, output)
    assert (output / 'keep').read_text() == 'existing evidence'
    before = snapshot(source_batch.parent)
    with pytest.raises(ValueError, match='outside the original'):
        batch.prepare_batch(source_batch, source_batch.parent / 'new')
    assert snapshot(source_batch.parent) == before and not offline_prepare['calls']
