"""Offline publication fixtures; no model, Docker, or real Harbor execution."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from sheets_factory.core.audit import AuditStore
from sheets_factory.evaluation.harbor import inspect_export
from dirhash import dirhash
from test_package_release import fixture_task, write_json


spec = importlib.util.spec_from_file_location('publish_dataset', Path(__file__).parents[1] / 'scripts/publish_dataset.py')
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)
ROOT = Path(__file__).parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def fixture_publication(tmp_path, monkeypatch):
    # Small fixture sizes keep security cases cheap. A separate test verifies
    # the unmodified production minimum of ten tasks in each category.
    monkeypatch.setattr(publish, 'MIN_PER_MODE', 1)
    root = tmp_path / 'checkout'
    run = root / 'outputs/runs/offline-publication'
    audit = AuditStore(run, {'id': 'offline-publication', 'status': 'completed'})
    recipe = root / 'src/sheets_factory/workbook'
    recipe.mkdir(parents=True)
    for name in publish.release.RUNTIME_FILES:
        shutil.copy2(ROOT / 'src/sheets_factory/workbook' / name, recipe / name)
    shutil.copy2(ROOT / 'uv.lock', root / 'uv.lock')
    entries = []
    for mode in publish.release.MODES:
        task_id, _, export = fixture_task(run, audit, mode, source='a' * 64)
        binding = inspect_export(export)
        entries.append({'task_id': task_id, 'mode': mode, 'revision': 0,
                        'revision_hash': binding['revision_hash'], 'harbor_export_binding': binding,
                        'task_directory': str(export), 'task_checksum': dirhash(export, 'sha256')})
    frozen = root / 'outputs/confirmation/frozen_selection.json'
    write_json(frozen, {'schema_version': 1, 'phase': 'confirmation',
                       'model': publish.MODEL, 'reasoning_effort': publish.EFFORT,
                       'timeout_seconds': 1800, 'prompt_sha256': 'c' * 64,
                       'frozen_at': '2026-10-29T12:00:00Z',
                       'selected_task_ids': [entry['task_id'] for entry in entries], 'tasks': entries})
    evaluation = root / 'outputs/confirmation/evaluation_manifest.json'
    return {'root': root, 'run': run, 'audit': audit, 'selection': frozen,
            'evaluation': evaluation, 'entries': entries}


def invoke(fixture, **kwargs):
    return publish.publish_dataset(run_dir=fixture['run'], selection_manifest=fixture['selection'],
        evaluation_manifest=fixture['evaluation'], project_root=fixture['root'], **kwargs)


def file_hashes(directory):
    return {str(path.relative_to(directory)): digest(path)
            for path in directory.rglob('*') if path.is_file() and not path.name.endswith(('-wal', '-shm'))}


def confirmation(fixture, *, rewards=None, phase='confirmation'):
    entries = []
    for index, item in enumerate(fixture['entries']):
        reward = rewards[index] if rewards else 0
        binding = item['harbor_export_binding']
        record = {'task_name': binding['task_name'], 'task_checksum': item['task_checksum'],
            'task_id': {'path': item['task_directory']},
            'config': {'task': {'path': item['task_directory']}, 'agent': {
                'model_name': publish.MODEL, 'kwargs': {'reasoning_effort': publish.EFFORT},
                'override_timeout_sec': 1800, 'import_path': 'sheets_factory.evaluation.frontier:LocalCodex'}},
            'agent_info': {'name': 'codex', 'model_info': {'name': publish.MODEL}},
            'exception_info': None, 'verifier_result': {'rewards': {'reward': reward}},
            'started_at': '2026-10-29T12:01:01Z', 'finished_at': '2026-10-29T12:01:02Z',
            'offline_fixture': True}
        result = fixture['evaluation'].parent / 'results' / (item['task_id'] + '.json')
        write_json(result, record)
        entries.append({**deepcopy(item), 'status': 'scored', 'reward': reward,
                        'result_file': str(result), 'result_sha256': digest(result)})
    by_mode = {mode: {'tasks': sum(item['mode'] == mode for item in entries),
                     'scored': sum(item['mode'] == mode for item in entries),
                     'successes': sum(item['reward'] for item in entries if item['mode'] == mode)}
               for mode in publish.release.MODES}
    for values in by_mode.values():
        values['pass_at_1'] = values['successes'] / values['tasks']
    overall = sum(item['reward'] for item in entries) / len(entries)
    write_json(fixture['evaluation'], {'schema_version': 1, 'phase': phase,
        'status': 'completed', 'model': publish.MODEL, 'reasoning_effort': publish.EFFORT,
        'timeout_seconds': 1800,
        'selection_manifest': {'path': str(fixture['selection']), 'sha256': digest(fixture['selection'])},
        'started_at': '2026-10-29T12:01:00Z', 'finished_at': '2026-10-29T12:02:00Z',
        'attempts': entries, 'threshold': .2, 'gate_passed': overall <= .2,
        'score': {'overall_pass_at_1': overall, 'by_mode': by_mode, 'total_tasks': len(entries),
                  'scored_tasks': len(entries), 'infrastructure_errors': 0}})
    return entries


def test_dry_run_is_read_only_and_real_publication_has_no_output_links(fixture_publication):
    f = fixture_publication
    confirmation(f)
    before = file_hashes(f['root'])
    result = invoke(f, dry_run=True)
    assert result['status'] == 'validated_dry_run'
    assert file_hashes(f['root']) == before
    assert not (f['root'] / 'SpreadsheetEval').exists()
    assert result['manifest']['confirmation']['overall_pass_at_1'] == 0
    result = invoke(f)
    dataset = f['root'] / 'SpreadsheetEval'
    assert result['status'] == 'published'
    assert dataset.is_dir() and not dataset.is_symlink()
    assert {path.name for path in dataset.iterdir() if path.is_dir()} == {'fm-a', 'dbg-a'}
    for entry in f['entries']:
        export = dataset / entry['task_id']
        assert inspect_export(export) == entry['harbor_export_binding']
        assert {str(path.relative_to(export)) for path in export.rglob('*') if path.is_file()} == publish.release.EXPORT_FILES
        assert not any(path.is_symlink() for path in export.rglob('*'))
        assert (export / 'solution/reference.xlsx').is_file()
        assert not (export / 'environment/reference.xlsx').exists()
    metadata = (dataset / 'dataset_manifest.json').read_text()
    assert '/private/' not in metadata and 'result_file' not in metadata
    assert str(f['root']) not in metadata and 'api_key' not in metadata
    assert result['manifest']['runtime']['harbor_version'] == '0.25.0'
    assert (f['root'] / 'prepare_runtime.sh').stat().st_mode & 0o111
    assert {path.name for path in (f['root'] / publish.RUNTIME_DIRECTORY).iterdir()} == publish.release.RUNTIME_FILES
    assert not list(f['root'].glob('.dataset-publish-*'))
    # The source run and all evidence remain byte-identical.
    after = file_hashes(f['root'])
    assert all(after[name] == sha for name, sha in before.items())


def test_runtime_preparation_uses_minimal_context_from_any_cwd(fixture_publication, tmp_path):
    f = fixture_publication
    confirmation(f)
    invoke(f)
    mock_bin = tmp_path / 'mockbin'
    mock_bin.mkdir()
    docker = mock_bin / 'docker'
    docker.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    docker.chmod(0o755)
    import os
    result = subprocess.run([str(f['root'] / 'prepare_runtime.sh')], cwd=tmp_path,
        env={**os.environ, 'PATH': str(mock_bin) + os.pathsep + os.defpath}, capture_output=True, text=True)
    assert result.returncode == 0
    arguments = result.stdout.splitlines()
    assert arguments == ['build', '--network', 'host', '-t', 'sheetsfactory-lo:24.2',
                         str(f['root'] / publish.RUNTIME_DIRECTORY)]


def test_existing_final_or_symlink_is_never_overwritten(fixture_publication, tmp_path):
    f = fixture_publication
    confirmation(f)
    destination = f['root'] / 'SpreadsheetEval'
    destination.symlink_to(tmp_path / 'absent-target')
    with pytest.raises(publish.PublishError, match='already exists'):
        invoke(f)
    assert destination.is_symlink()


def test_changed_frozen_revision_refuses_before_writing(fixture_publication):
    f = fixture_publication
    frozen = json.loads(f['selection'].read_text())
    frozen['tasks'][0]['revision_hash'] = 'f' * 64
    write_json(f['selection'], frozen)
    confirmation(f)
    with pytest.raises(publish.PublishError, match='frozen revision binding'):
        invoke(f)
    assert not (f['root'] / 'SpreadsheetEval').exists()


@pytest.mark.parametrize('unsafe', ['private.log', 'environment/api_key'])
def test_unexpected_files_never_enter_publication(fixture_publication, unsafe):
    f = fixture_publication
    confirmation(f)
    extra = f['run'] / 'SpreadsheetEval/fm-a' / unsafe
    extra.write_text('unexpected data')
    with pytest.raises(publish.PublishError, match='Unexpected or missing Harbor release files'):
        invoke(f)
    assert not (f['root'] / 'SpreadsheetEval').exists()


def test_symlink_payload_is_rejected(fixture_publication, tmp_path):
    f = fixture_publication
    confirmation(f)
    path = f['run'] / 'SpreadsheetEval/fm-a/instruction.md'
    outside = tmp_path / 'instruction.txt'
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(publish.PublishError, match='Symlink'):
        invoke(f)


def test_no_overwrite_race_rolls_back_own_support_files(fixture_publication, monkeypatch):
    f = fixture_publication
    confirmation(f)
    rename = publish._rename_new

    def racing_rename(source, destination):
        if destination.name == 'SpreadsheetEval':
            destination.mkdir()
            (destination / 'other-owner.txt').write_text('preserve')
        return rename(source, destination)

    monkeypatch.setattr(publish, '_rename_new', racing_rename)
    with pytest.raises(publish.PublishError, match='already exists'):
        invoke(f)
    assert (f['root'] / 'SpreadsheetEval/other-owner.txt').read_text() == 'preserve'
    assert not (f['root'] / publish.RUNTIME_DIRECTORY).exists()
    assert not (f['root'] / 'prepare_runtime.sh').exists()
    assert not list(f['root'].glob('.dataset-publish-*'))


def test_minimum_is_ten_per_mode_in_production(fixture_publication, monkeypatch):
    f = fixture_publication
    confirmation(f)
    monkeypatch.setattr(publish, 'MIN_PER_MODE', 10)
    with pytest.raises(publish.PublishError, match='at least 10 tasks in each mode'):
        invoke(f)


def test_evidence_change_during_copy_aborts_without_publishing(fixture_publication, monkeypatch):
    f = fixture_publication
    confirmation(f)
    copy = publish.release._copy_payload

    def copy_then_change_evidence(*args):
        copy(*args)
        f['evaluation'].write_text(f['evaluation'].read_text() + '\n')

    monkeypatch.setattr(publish.release, '_copy_payload', copy_then_change_evidence)
    with pytest.raises(publish.PublishError, match='evidence changed during staging'):
        invoke(f)
    assert not (f['root'] / 'SpreadsheetEval').exists()
    assert not list(f['root'].glob('.dataset-publish-*'))


def test_new_native_fact_during_copy_aborts_without_publishing(fixture_publication, monkeypatch):
    f = fixture_publication
    confirmation(f)
    copy = publish.release._copy_payload

    def copy_then_add_native_fact(*args):
        copy(*args)
        write_json(f['root'] / 'data/manifests/native_risks.json', {'sources': [{
            'source_sha256': 'a' * 64, 'risks': [{'risk_id': 'new-late-fact',
                'certainty': 'confirmed', 'unsafe_regions': ['Sheet!A1'], 'evidence': ['Offline test fact.']}]}]})

    monkeypatch.setattr(publish.release, '_copy_payload', copy_then_add_native_fact)
    with pytest.raises(publish.PublishError, match='Native-risk evidence changed during staging'):
        invoke(f)
    assert not (f['root'] / 'SpreadsheetEval').exists()
    assert not list(f['root'].glob('.dataset-publish-*'))


@pytest.mark.parametrize('field,value,message', [
    ('phase', 'development', 'completed confirmation'),
    ('status', 'running', 'completed confirmation'),
    ('model', 'gpt-6-sol', 'gpt-6.1-sol'),
    ('reasoning_effort', 'high', 'xhigh'),
    ('started_at', '2026-10-29T11:59:59Z', 'frozen before'),
])
def test_unqualified_confirmation_is_refused(fixture_publication, field, value, message):
    f = fixture_publication
    confirmation(f)
    manifest = json.loads(f['evaluation'].read_text())
    manifest[field] = value
    write_json(f['evaluation'], manifest)
    with pytest.raises(publish.PublishError, match=message):
        invoke(f)
    assert not (f['root'] / 'SpreadsheetEval').exists()


def test_high_overall_pass_rate_is_not_publishable(fixture_publication):
    f = fixture_publication
    confirmation(f, rewards=[1, 0])
    with pytest.raises(publish.PublishError, match='Overall confirmation Pass@1 exceeds 0.2'):
        invoke(f)


def test_infrastructure_failure_cannot_count_as_model_failure(fixture_publication):
    f = fixture_publication
    confirmation(f)
    manifest = json.loads(f['evaluation'].read_text())
    manifest['attempts'][0]['status'] = 'infrastructure_error'
    manifest['score']['infrastructure_errors'] = 1
    write_json(f['evaluation'], manifest)
    with pytest.raises(publish.PublishError, match='infrastructure failures'):
        invoke(f)


@pytest.mark.parametrize('tamper', ['result_hash', 'real_model', 'real_reward', 'task_checksum', 'duplicate'])
def test_actual_result_binding_cannot_be_substituted(fixture_publication, tamper):
    f = fixture_publication
    confirmation(f)
    manifest = json.loads(f['evaluation'].read_text())
    entry = manifest['attempts'][0]
    result_file = Path(entry['result_file'])
    actual = json.loads(result_file.read_text())
    if tamper == 'result_hash':
        result_file.write_text(result_file.read_text() + '\n')
    elif tamper == 'real_model':
        actual['config']['agent']['model_name'] = 'gpt-6-sol'
        write_json(result_file, actual)
        entry['result_sha256'] = digest(result_file)
    elif tamper == 'real_reward':
        actual['verifier_result']['rewards']['reward'] = 1
        write_json(result_file, actual)
        entry['result_sha256'] = digest(result_file)
    elif tamper == 'task_checksum':
        entry['task_checksum'] = 'f' * 64
    else:
        manifest['attempts'][1] = deepcopy(entry)
    write_json(f['evaluation'], manifest)
    with pytest.raises(publish.PublishError):
        invoke(f)
    assert not (f['root'] / 'SpreadsheetEval').exists()


def test_current_qualified_status_is_required(fixture_publication):
    f = fixture_publication
    confirmation(f)
    f['audit'].task('fm-a', status='rejected')
    with pytest.raises(publish.PublishError, match='not qualified'):
        invoke(f)


def test_known_credentials_are_not_copied_or_printed(fixture_publication, capsys):
    f = fixture_publication
    confirmation(f)
    secret = 'PRIVATE_API_TOKEN_12345678901234567890'
    key_file = f['root'] / '.secrets/api_key'
    key_file.parent.mkdir()
    key_file.write_text(secret)
    (f['run'] / 'SpreadsheetEval/fm-a/instruction.md').write_text(secret)
    with pytest.raises(publish.PublishError, match='Credential') as error:
        invoke(f)
    assert secret not in str(error.value)
    code = publish.main(['--run', str(f['run']), '--selection-manifest', str(f['selection']),
                         '--evaluation-manifest', str(f['evaluation']), '--project-root', str(f['root'])])
    assert code == 2 and secret not in capsys.readouterr().err
    assert not (f['root'] / 'SpreadsheetEval').exists()


def test_strict_release_can_supply_payload_without_private_file_copy(fixture_publication, monkeypatch):
    f = fixture_publication
    confirmation(f)
    monkeypatch.setattr(publish.release, 'generate_report', lambda *_args, **_kwargs: {
        'tasks': [{'task_id': task['id'], 'verified_qualified': True} for task in f['audit'].snapshot()['tasks']],
        'yield': {}, 'sources': {}, 'run': {'difficulty_status': 'deferred'}})
    packaged = publish.release.package_release(f['run'], 1, f['root'] / 'outputs/offline-release',
                                                project_root=f['root'])
    result = publish.publish_dataset(release_dir=packaged['release_directory'],
        evaluation_manifest=f['evaluation'], project_root=f['root'])
    assert result['status'] == 'published'
    assert not (f['root'] / 'SpreadsheetEval/fm-a/private').exists()
    assert (f['root'] / 'SpreadsheetEval/fm-a/tests/reference.xlsx').is_file()


def test_twenty_task_gate_only_enforces_overall_rate(fixture_publication, monkeypatch):
    f = fixture_publication
    for mode in publish.release.MODES:
        for index in range(1, 10):
            task_id, _, export = fixture_task(f['run'], f['audit'], mode, suffix=str(index), source='a' * 64)
            binding = inspect_export(export)
            f['entries'].append({'task_id': task_id, 'mode': mode, 'revision': 0,
                'revision_hash': binding['revision_hash'], 'harbor_export_binding': binding,
                'task_directory': str(export), 'task_checksum': dirhash(export, 'sha256')})
    frozen = json.loads(f['selection'].read_text())
    frozen.update(selected_task_ids=[item['task_id'] for item in f['entries']], tasks=f['entries'])
    write_json(f['selection'], frozen)
    rewards = [int(item['mode'] == 'financial_modeling' and item['task_id'] in {'fm-a', 'fm-1', 'fm-2'})
               for item in f['entries']]
    confirmation(f, rewards=rewards)
    monkeypatch.setattr(publish, 'MIN_PER_MODE', 10)
    result = invoke(f, dry_run=True)
    score = result['manifest']['confirmation']
    assert result['task_count'] == 20 and result['counts_by_mode'] == {'financial_modeling': 10, 'debugging': 10}
    assert score['overall_pass_at_1'] == .15
    assert score['by_mode']['financial_modeling']['pass_at_1'] == .3
    assert score['by_mode']['debugging']['pass_at_1'] == 0


def test_root_oracle_command_resolves_all_tasks_and_ignores_manifest(fixture_publication):
    f = fixture_publication
    confirmation(f)
    invoke(f)
    import sys
    harbor = Path(sys.executable).with_name('harbor')
    result = subprocess.run([str(harbor), 'run', '-p', 'SpreadsheetEval', '-a', 'oracle', '--print-config'],
                            cwd=f['root'], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    assert len(config['datasets']) == 1
    assert config['datasets'][0]['path'] == 'SpreadsheetEval'
