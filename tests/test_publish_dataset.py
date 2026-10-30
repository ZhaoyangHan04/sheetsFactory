"""Offline publication fixtures; no model, Docker, or real Harbor execution."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from sheets_factory.core.audit import AuditStore
from sheets_factory.evaluation.harbor import inspect_export
from dirhash import dirhash
from test_package_release import fixture_task, write_json
from test_frontier import persist_timing
from sheets_factory.evaluation.frontier import TOOL_TIME_POLICY, apply_tool_time_policy
from sheets_factory.evaluation.tool_time_bounds import POLICY_V2


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
                        'tool_time_policy': dict(TOOL_TIME_POLICY),
                        'task_directory': str(export), 'task_checksum': dirhash(export, 'sha256')})
    frozen = root / 'outputs/confirmation/frozen_selection.json'
    write_json(frozen, {'schema_version': 1, 'phase': 'confirmation',
                       'model': publish.MODEL, 'reasoning_effort': publish.EFFORT,
                       'timeout_seconds': 1800, 'prompt_sha256': 'c' * 64,
                       'tool_time_policy': dict(TOOL_TIME_POLICY),
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
    policy = json.loads(fixture['selection'].read_text())['tool_time_policy']
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
            'agent_execution': {'started_at': '2026-10-29T12:01:01Z', 'finished_at': '2026-10-29T12:01:02Z'},
            'started_at': '2026-10-29T12:01:01Z', 'finished_at': '2026-10-29T12:01:02Z',
            'offline_fixture': True}
        result = fixture['evaluation'].parent / 'harbor_jobs/frontier-pass1' / item['task_id'] / 'result.json'
        write_json(result, record)
        persist_timing(result)
        entry = {**deepcopy(item), 'status': 'scored', 'reward': reward,
                 'result_file': str(result), 'result_sha256': digest(result)}
        apply_tool_time_policy(entry, {'tool_time_policy': policy})
        entries.append(entry)
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
        'tool_time_policy': dict(policy),
        'selection_manifest': {'path': str(fixture['selection']), 'sha256': digest(fixture['selection'])},
        'started_at': '2026-10-29T12:01:00Z', 'finished_at': '2026-10-29T12:02:00Z',
        'attempts': entries, 'threshold': .2, 'gate_passed': overall <= .2,
        'score': {'overall_pass_at_1': overall, 'by_mode': by_mode, 'total_tasks': len(entries),
                  'scored_tasks': len(entries), 'infrastructure_errors': 0}})
    return entries


def set_timing_policy(fixture, policy):
    frozen = json.loads(fixture['selection'].read_text())
    frozen['tool_time_policy'] = deepcopy(policy)
    frozen['tool_time_policy_version'] = policy.get('version', 1)
    for entry in fixture['entries']:
        entry['tool_time_policy'] = deepcopy(policy)
    frozen['tasks'] = deepcopy(fixture['entries'])
    write_json(fixture['selection'], frozen)


def bounded_confirmation(fixture, *, stop_seconds=100, pending=None):
    """Offline full publisher fixture with an unresolved static native tail."""
    from test_tool_time_bounds import fixture as stop_fixture, ref, stamp

    set_timing_policy(fixture, POLICY_V2)
    confirmation(fixture)
    manifest = json.loads(fixture['evaluation'].read_text())
    entry = manifest['attempts'][0]
    original = Path(entry['result_file'])
    actual = json.loads(original.read_text())
    result, stop, session = stop_fixture(original.parent.parent, stop=stop_seconds, pending=pending)
    actual.update(agent_execution={'started_at': stamp(0), 'finished_at': stamp(20)},
                  started_at=stamp(0), finished_at=stamp(20))
    write_json(result, actual)
    receipt = json.loads(stop.read_text())
    receipt['result_file'] = ref(result)
    write_json(stop, receipt)
    shutil.rmtree(original.parent)
    entry.update(result_file=str(result), result_sha256=digest(result))
    apply_tool_time_policy(entry, {'tool_time_policy': POLICY_V2})
    manifest['finished_at'] = stamp(max(stop_seconds, 21))
    write_json(fixture['evaluation'], manifest)
    return manifest, result, stop, session


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
    assert result['manifest']['runtime']['expected_image_id'] == 'sha256:' + '0' * 64
    assert result['manifest']['runtime']['pinned_preload_supported'] is True
    assert result['manifest']['runtime']['bit_identical_rebuild_guaranteed'] is False
    assert result['manifest']['runtime']['setup_commands'] == [
        'UV_PROJECT_ENVIRONMENT=.venv312 uv sync --frozen --extra test --python 3.12',
        'source .venv312/bin/activate', './prepare_runtime.sh']
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
    result = subprocess.run([str(f['root'] / 'prepare_runtime.sh')], cwd=tmp_path,
        env={**os.environ, 'PATH': str(mock_bin) + os.pathsep + os.defpath}, capture_output=True, text=True)
    assert result.returncode == 0
    arguments = result.stdout.splitlines()
    assert arguments == ['build', '--network', 'host', '-t', 'sheetsfactory-lo:24.2',
                         str(f['root'] / publish.RUNTIME_DIRECTORY)]


def _run_preparation_with_fake_docker(script, tmp_path, image_id):
    """Execute only the generated shell and a local Docker substitute."""
    mock_bin = tmp_path / 'fake-docker-bin'
    mock_bin.mkdir()
    calls = tmp_path / 'fake-docker-calls.jsonl'
    docker = mock_bin / 'docker'
    docker.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
with open(os.environ['FAKE_DOCKER_CALLS'], 'a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
if sys.argv[1:3] == ['image', 'inspect']:
    image_id = os.environ['FAKE_DOCKER_IMAGE_ID']
    if not image_id:
        sys.exit(1)
    print(image_id)
    sys.exit(0)
if sys.argv[1:2] != ['build']:
    sys.exit(9)
''')
    docker.chmod(0o755)
    result = subprocess.run([str(script)], cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, 'PATH': str(mock_bin) + os.pathsep + os.defpath,
             'FAKE_DOCKER_CALLS': str(calls), 'FAKE_DOCKER_IMAGE_ID': image_id or ''})
    recorded = [json.loads(line) for line in calls.read_text().splitlines()]
    return result, recorded


def test_preloaded_exact_recorded_image_skips_build(fixture_publication, tmp_path):
    f = fixture_publication
    confirmation(f)
    result = invoke(f)
    expected_id = result['manifest']['runtime']['expected_image_id']
    prepared, calls = _run_preparation_with_fake_docker(
        f['root'] / 'prepare_runtime.sh', tmp_path, expected_id)
    assert prepared.returncode == 0
    assert calls == [['image', 'inspect', '--format', '{{.Id}}', 'sheetsfactory-lo:24.2']]
    assert 'skipping rebuild' in prepared.stdout
    assert not prepared.stderr


@pytest.mark.parametrize('local_image_id', ['sha256:' + '1' * 64, None])
def test_different_or_absent_local_image_uses_existing_build_path(
        fixture_publication, tmp_path, local_image_id):
    f = fixture_publication
    confirmation(f)
    invoke(f)
    prepared, calls = _run_preparation_with_fake_docker(
        f['root'] / 'prepare_runtime.sh', tmp_path, local_image_id)
    assert prepared.returncode == 0
    assert calls == [
        ['image', 'inspect', '--format', '{{.Id}}', 'sheetsfactory-lo:24.2'],
        ['build', '--network', 'host', '-t', 'sheetsfactory-lo:24.2',
         str(f['root'] / publish.RUNTIME_DIRECTORY)]]
    assert 'recorded image identity is not guaranteed' in prepared.stderr
    assert 'skipping rebuild' not in prepared.stdout


def test_runtime_tag_is_a_literal_shell_argument(fixture_publication, tmp_path, monkeypatch):
    f = fixture_publication
    confirmation(f)
    sentinel = tmp_path / 'must-not-be-created'
    unusual_tag = f'fixture:24.2; $(touch {sentinel})'
    original = publish.release._prepare_runtime

    def metadata_with_unusual_tag(*args, **kwargs):
        # Upstream validation already excludes shell metacharacters. Exercise
        # the generated shell defensively even if that validation later changes.
        payload, metadata = original(*args, **kwargs)
        return payload, {**metadata, 'image_tag': unusual_tag}

    monkeypatch.setattr(publish.release, '_prepare_runtime', metadata_with_unusual_tag)
    invoke(f)
    prepared, calls = _run_preparation_with_fake_docker(
        f['root'] / 'prepare_runtime.sh', tmp_path, None)
    assert prepared.returncode == 0
    assert calls[0] == ['image', 'inspect', '--format', '{{.Id}}', unusual_tag]
    assert calls[1] == ['build', '--network', 'host', '-t', unusual_tag,
                        str(f['root'] / publish.RUNTIME_DIRECTORY)]
    assert not sentinel.exists()


def test_multiple_recorded_images_keep_rebuild_without_new_publication_gate(
        fixture_publication, tmp_path):
    f = fixture_publication
    confirmation(f)
    task_id = f['entries'][0]['task_id']
    diagnosis = f['run'] / 'tasks' / task_id / 'revisions/000/private/diagnosis.json'
    content = json.loads(diagnosis.read_text())
    content['assessments']['Q10']['evidence'][0]['engine']['image_id'] = 'sha256:' + '1' * 64
    write_json(diagnosis, content)
    result = invoke(f)
    runtime = result['manifest']['runtime']
    assert len(runtime['recorded_run_images']) == 2
    assert runtime['expected_image_id'] is None
    assert runtime['pinned_preload_supported'] is False
    assert runtime['bit_identical_rebuild_guaranteed'] is False
    prepared, calls = _run_preparation_with_fake_docker(
        f['root'] / 'prepare_runtime.sh', tmp_path, 'sha256:' + '0' * 64)
    assert prepared.returncode == 0
    assert calls == [['build', '--network', 'host', '-t', 'sheetsfactory-lo:24.2',
                      str(f['root'] / publish.RUNTIME_DIRECTORY)]]


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
                'tool_time_policy': dict(TOOL_TIME_POLICY),
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


def normal_timeout(fixture):
    from sheets_factory.evaluation.frontier import review_agent_timeout
    confirmation(fixture)
    manifest = json.loads(fixture['evaluation'].read_text())
    entry = manifest['attempts'][0]
    file = Path(entry['result_file'])
    actual = json.loads(file.read_text())
    actual.update(exception_info={'exception_type': 'AgentTimeoutError'},
        agent_result={'n_input_tokens': 100, 'n_output_tokens': 10},
        agent_execution={'started_at': '2026-10-29T12:01:01Z', 'finished_at': '2026-10-29T12:31:01Z'},
        verifier={'started_at': '2026-10-29T12:31:02Z', 'finished_at': '2026-10-29T12:31:03Z'},
        finished_at='2026-10-29T12:31:04Z')
    write_json(file, actual)
    log = file.parent / 'agent/codex.txt'
    log.parent.mkdir(exist_ok=True)
    log.write_text(json.dumps({'type': 'item.completed', 'item': {
        'type': 'command_execution', 'command': 'python work.py', 'exit_code': 1,
        'aggregated_output': 'An ordinary tool mistake; agent continued reasoning.'}}) + '\n')
    write_json(file.parent / 'verifier/diagnostics.json', {'reward': 0, 'reason': 'value_or_modified_set_mismatch'})
    (file.parent / 'verifier/reward.txt').write_text('0\n')
    entry['result_sha256'] = digest(file)
    entry['exception_resolution'] = review_agent_timeout(actual, fixture['entries'][0], result_file=file)
    assert entry['exception_resolution'] is not None
    apply_tool_time_policy(entry, {'tool_time_policy': TOOL_TIME_POLICY})
    manifest['finished_at'] = '2026-10-29T12:32:00Z'
    write_json(fixture['evaluation'], manifest)
    return manifest, file, log


def test_normal_budget_timeout_requires_the_exact_shared_review(fixture_publication):
    f = fixture_publication
    normal_timeout(f)
    result = invoke(f, dry_run=True)
    reviewed = result['manifest']['confirmation']['tasks'][0]['exception_resolution']
    assert reviewed['classification'] == 'normal_agent_budget_exhaustion'
    assert reviewed['budget_seconds'] == 1800 and reviewed['agent_elapsed_seconds'] == 1800
    assert reviewed['completed_command_events'] == 1  # Ordinary exit=1 remains valid activity.
    assert 'native_log_file' not in reviewed and 'result_file' not in reviewed


def test_tool_budget_failure_retains_raw_success_and_publishes_effective_zero(fixture_publication):
    f = fixture_publication
    confirmation(f)
    manifest = json.loads(f['evaluation'].read_text())
    entry = manifest['attempts'][0]
    path = Path(entry['result_file'])
    raw = json.loads(path.read_text())
    raw['verifier_result']['rewards']['reward'] = 1
    raw['finished_at'] = '2026-10-29T12:31:01Z'
    raw['agent_execution']['finished_at'] = '2026-10-29T12:31:01Z'
    write_json(path, raw)
    persist_timing(path, seconds=1800)
    entry.update(reward=1, result_sha256=digest(path))
    apply_tool_time_policy(entry, {'tool_time_policy': TOOL_TIME_POLICY})
    assert entry['reward'] == 0 and entry['raw_verifier_reward'] == 1
    manifest['finished_at'] = '2026-10-29T12:32:00Z'
    write_json(f['evaluation'], manifest)
    result = invoke(f, dry_run=True)
    task = result['manifest']['confirmation']['tasks'][0]
    assert task['reward'] == 0 and task['raw_verifier_reward'] == 1
    assert task['tool_time']['cumulative_tool_seconds'] == 1800


@pytest.mark.parametrize('problem', ['missing_policy', 'missing_session', 'forged_receipt'])
def test_publication_requires_reproducible_native_tool_timing(fixture_publication, problem):
    f = fixture_publication
    confirmation(f)
    manifest = json.loads(f['evaluation'].read_text())
    entry = manifest['attempts'][0]
    if problem == 'missing_policy':
        manifest.pop('tool_time_policy')
    elif problem == 'missing_session':
        (Path(entry['result_file']).parent / 'agent/sessions/fixture.jsonl').unlink()
    else:
        entry['tool_time']['cumulative_tool_seconds'] = 0
    write_json(f['evaluation'], manifest)
    with pytest.raises(publish.PublishError, match='tool (budget|timing)'):
        invoke(f, dry_run=True)


def test_v2_exact_receipts_publish_under_their_frozen_policy(fixture_publication):
    f = fixture_publication
    set_timing_policy(f, POLICY_V2)
    confirmation(f)
    before = file_hashes(f['root'])
    result = invoke(f, dry_run=True)
    confirmation_receipt = result['manifest']['confirmation']
    assert confirmation_receipt['tool_time_policy'] == POLICY_V2
    for task in confirmation_receipt['tasks']:
        timing = task['tool_time']
        assert timing['state'] == timing['exact_timing_state'] == 'verified'
        assert timing['policy_version'] == 2
        assert timing['lower_bound_seconds'] == timing['upper_bound_seconds'] == 1
    assert file_hashes(f['root']) == before


def test_v2_bounded_receipt_retains_exact_unknown_and_public_hashes_only(fixture_publication):
    f = fixture_publication
    _, _, stop, _ = bounded_confirmation(f)
    result = invoke(f)
    confirmation_receipt = result['manifest']['confirmation']
    timing = confirmation_receipt['tasks'][0]['tool_time']
    assert confirmation_receipt['tool_time_policy'] == POLICY_V2
    assert timing['state'] == 'bounded' and timing['exact_timing_state'] == 'unknown'
    assert timing['cumulative_tool_seconds'] is None and timing['cumulative_tool_nanoseconds'] is None
    assert timing['lower_bound_seconds'] == 2 and timing['upper_bound_seconds'] == 92
    assert timing['lower_bound_nanoseconds'] == 2_000_000_000
    assert timing['upper_bound_nanoseconds'] == 92_000_000_000
    assert timing['passed'] is True and timing['upper_bound_may_include_idle_cleanup_time'] is True
    stop_receipt = json.loads(stop.read_text())
    identity = Path(stop_receipt['identity_file']['path'])
    identity_receipt = json.loads(identity.read_text())
    assert timing['evidence_sha256'] == {
        'stop_receipt_sha256': digest(stop), 'container_identity_sha256': digest(identity),
        'trial_config_sha256': identity_receipt['trial_config']['sha256']}
    public = (f['root'] / 'SpreadsheetEval/dataset_manifest.json').read_text()
    assert str(f['root']) not in public and '"container_id"' not in public
    assert not list((f['root'] / 'SpreadsheetEval').rglob('stop_receipt.json'))


@pytest.mark.parametrize('part', ['evaluation', 'frozen_task', 'attempt', 'version', 'unknown_policy'])
def test_publisher_rejects_mixed_or_unsupported_frozen_policies(fixture_publication, part):
    f = fixture_publication
    set_timing_policy(f, POLICY_V2)
    confirmation(f)
    manifest = json.loads(f['evaluation'].read_text())
    frozen = json.loads(f['selection'].read_text())
    if part == 'evaluation':
        manifest['tool_time_policy'] = dict(TOOL_TIME_POLICY)
    elif part == 'frozen_task':
        frozen['tasks'][0]['tool_time_policy'] = dict(TOOL_TIME_POLICY)
    elif part == 'attempt':
        manifest['attempts'][0]['tool_time_policy'] = dict(TOOL_TIME_POLICY)
    elif part == 'version':
        frozen['tool_time_policy_version'] = 1
    else:
        frozen['tool_time_policy']['unknown_fanout'] = 'allow'
    write_json(f['selection'], frozen)
    manifest['selection_manifest']['sha256'] = digest(f['selection'])
    write_json(f['evaluation'], manifest)
    with pytest.raises(publish.PublishError, match='tool budget'):
        invoke(f, dry_run=True)


def test_v1_frozen_policy_does_not_accept_a_v2_pending_bound(fixture_publication):
    f = fixture_publication
    manifest, _, _, _ = bounded_confirmation(f)
    set_timing_policy(f, TOOL_TIME_POLICY)
    manifest['tool_time_policy'] = dict(TOOL_TIME_POLICY)
    manifest['selection_manifest']['sha256'] = digest(f['selection'])
    for entry in manifest['attempts']:
        entry['tool_time_policy'] = dict(TOOL_TIME_POLICY)
    write_json(f['evaluation'], manifest)
    with pytest.raises(publish.PublishError, match='tool timing is incomplete'):
        invoke(f, dry_run=True)


@pytest.mark.parametrize('problem', ['equal_upper', 'straddle', 'unknown_fanout', 'missing_stop', 'forged_bound'])
def test_v2_publisher_recomputes_bounds_and_rejects_uncertified_timing(fixture_publication, problem):
    from test_tool_time_bounds import wrapper
    f = fixture_publication
    pending = [wrapper('pending', 10, 'for(let i=0;i<n;i++){await tools.exec_command({cmd:"x"});}')] if problem == 'unknown_fanout' else None
    manifest, _, stop, _ = bounded_confirmation(f,
        stop_seconds=1808 if problem == 'equal_upper' else (1810 if problem == 'straddle' else 100),
        pending=pending)
    entry = manifest['attempts'][0]
    if problem == 'missing_stop':
        stop.unlink()
    elif problem == 'forged_bound':
        entry['tool_time']['upper_bound_seconds'] = 0
    # A declared success cannot override an unknown, equal, or straddling bound.
    entry.update(status='scored', reward=0)
    write_json(f['evaluation'], manifest)
    with pytest.raises(publish.PublishError, match='tool timing is incomplete'):
        invoke(f, dry_run=True)


@pytest.mark.parametrize('artifact', ['stop', 'identity', 'config'])
def test_v2_bound_inputs_changed_during_staging_prevent_publication(fixture_publication, monkeypatch, artifact):
    f = fixture_publication
    _, _, stop, _ = bounded_confirmation(f)
    stop_receipt = json.loads(stop.read_text())
    identity = Path(stop_receipt['identity_file']['path'])
    config = Path(json.loads(identity.read_text())['trial_config']['path'])
    target = {'stop': stop, 'identity': identity, 'config': config}[artifact]
    copy = publish.release._copy_payload
    changed = False

    def copy_then_change_bound(*args):
        nonlocal changed
        copy(*args)
        if not changed:
            target.write_text(target.read_text() + '\n')
            changed = True

    monkeypatch.setattr(publish.release, '_copy_payload', copy_then_change_bound)
    with pytest.raises(publish.PublishError, match='evidence changed during staging'):
        invoke(f)
    assert not (f['root'] / 'SpreadsheetEval').exists()


@pytest.mark.parametrize('problem', ['missing_receipt', 'forged_receipt', 'short_budget', 'provider_error',
                                     'missing_diagnostics', 'recalculate_permission'])
def test_incomplete_or_infrastructure_timeouts_are_not_scored_as_failures(fixture_publication, problem):
    f = fixture_publication
    manifest, file, log = normal_timeout(f)
    entry = manifest['attempts'][0]
    if problem == 'missing_receipt':
        entry.pop('exception_resolution')
    elif problem == 'forged_receipt':
        entry['exception_resolution']['completed_command_events'] = 999
    elif problem == 'short_budget':
        actual = json.loads(file.read_text())
        actual['agent_execution']['finished_at'] = '2026-10-29T12:02:00Z'
        write_json(file, actual)
        entry['result_sha256'] = digest(file)
    elif problem == 'provider_error':
        with log.open('a') as stream:
            stream.write(json.dumps({'type': 'turn.failed', 'error': {'message': 'Service unavailable'}}) + '\n')
    elif problem == 'missing_diagnostics':
        (file.parent / 'verifier/diagnostics.json').unlink()
    else:
        log.write_text(json.dumps({'type': 'item.completed', 'item': {
            'type': 'command_execution', 'aggregated_output': 'recalculate: Permission denied'}}) + '\n')
    write_json(f['evaluation'], manifest)
    with pytest.raises(publish.PublishError, match='timeout lacks an exact'):
        invoke(f)
    assert not (f['root'] / 'SpreadsheetEval').exists()


def test_timeout_evidence_changed_during_copy_prevents_publication(fixture_publication, monkeypatch):
    f = fixture_publication
    _, _, log = normal_timeout(f)
    copy = publish.release._copy_payload

    def copy_then_change_log(*args):
        copy(*args)
        log.write_text(log.read_text() + '\n')

    monkeypatch.setattr(publish.release, '_copy_payload', copy_then_change_log)
    with pytest.raises(publish.PublishError, match='evidence changed during staging'):
        invoke(f)
    assert not (f['root'] / 'SpreadsheetEval').exists()


def recovered_confirmation(fixture):
    from sheets_factory.evaluation.frontier import collect_attempts, assess_infrastructure_retry
    confirmation(fixture)
    manifest = json.loads(fixture['evaluation'].read_text())
    frozen = json.loads(fixture['selection'].read_text())
    original = Path(manifest['attempts'][0]['result_file'])
    healthy = json.loads(original.read_text())
    failed = deepcopy(healthy)
    failed.update(exception_info={'exception_type': 'NonZeroAgentExitCodeError'}, verifier_result=None)
    write_json(original, failed)
    log = original.parent / 'agent/codex.txt'
    log.parent.mkdir(exist_ok=True)
    log.write_text(json.dumps({'type': 'turn.failed', 'error': {'message': 'stream disconnected'}}) + '\n')
    old_attempts, old_history = collect_attempts(fixture['evaluation'].parent, frozen, include_infrastructure_history=True)
    before = deepcopy(manifest)
    before.update(status='infrastructure_failed', gate_passed=False, attempts=old_attempts,
                  infra_history=old_history, finished_at='2026-10-29T12:01:02Z')
    previous = fixture['evaluation'].parent / 'private/evaluation_history/resume-001-before.json'
    write_json(previous, before)
    replacement = fixture['evaluation'].parent / 'harbor_jobs/frontier-infra-001/fm-a/result.json'
    healthy.update(started_at='2026-10-29T12:01:03Z', finished_at='2026-10-29T12:01:04Z')
    healthy['agent_execution'] = {'started_at': healthy['started_at'], 'finished_at': healthy['finished_at']}
    write_json(replacement, healthy)
    persist_timing(replacement)
    current, history = collect_attempts(fixture['evaluation'].parent, frozen, include_infrastructure_history=True)
    authorization = assess_infrastructure_retry(old_history[0])
    manifest.update(attempts=current, infra_history=history, infrastructure_retries=[{
        'index': 1, 'started_at': '2026-10-29T12:01:03Z', 'finished_at': '2026-10-29T12:01:05Z',
        'task_ids': ['fm-a'], 'job_name': 'frontier-infra-001',
        'previous_manifest_file': str(previous), 'previous_manifest_sha256': digest(previous),
        'authorization': [{**authorization, 'task_id': 'fm-a'}]}])
    write_json(fixture['evaluation'], manifest)
    return manifest, previous, log


@pytest.mark.parametrize('policy', [TOOL_TIME_POLICY, POLICY_V2])
def test_authorized_infrastructure_replacement_counts_only_one_scored_attempt(fixture_publication, policy):
    f = fixture_publication
    set_timing_policy(f, policy)
    recovered_confirmation(f)
    result = invoke(f, dry_run=True)
    history = result['manifest']['confirmation']['infrastructure_history']
    assert history == {'retry_batches': 1, 'raw_infrastructure_records': 1,
                       'scored_attempts_per_task': 1, 'maximum_infrastructure_retries_per_task': 2}
    assert result['manifest']['confirmation']['task_count'] == 2
    assert result['manifest']['confirmation']['overall_pass_at_1'] == 0
    assert 'stream disconnected' not in json.dumps(result['manifest'])


@pytest.mark.parametrize('problem', ['hidden_history', 'previous_manifest_sha', 'provider_log_sha',
                                     'retried_scored', 'mixed_policy'])
def test_infrastructure_history_requires_independent_proof_chain(fixture_publication, problem):
    f = fixture_publication
    manifest, previous, log = recovered_confirmation(f)
    retry = manifest['infrastructure_retries'][0]
    if problem == 'hidden_history':
        manifest['infra_history'] = []
    elif problem == 'previous_manifest_sha':
        previous.write_text(previous.read_text() + '\n')
    elif problem == 'provider_log_sha':
        log.write_text(log.read_text() + '\n')
    elif problem == 'mixed_policy':
        before = json.loads(previous.read_text())
        before['tool_time_policy'] = dict(POLICY_V2)
        write_json(previous, before)
        retry['previous_manifest_sha256'] = digest(previous)
    else:
        before = json.loads(previous.read_text())
        old = next(item for item in before['attempts'] if item['task_id'] == 'fm-a')
        old.update(status='scored', reward=0)
        write_json(previous, before)
        retry['previous_manifest_sha256'] = digest(previous)
    write_json(f['evaluation'], manifest)
    with pytest.raises(publish.PublishError):
        invoke(f)
    assert not (f['root'] / 'SpreadsheetEval').exists()


def test_unreported_second_scored_attempt_cannot_select_the_lower_reward(fixture_publication):
    f = fixture_publication
    entries = confirmation(f)
    extra = f['evaluation'].parent / 'harbor_jobs/unreported-rerun/fm-a/result.json'
    write_json(extra, json.loads(Path(entries[0]['result_file']).read_text()))
    with pytest.raises(publish.PublishError, match='repeated scored attempts'):
        invoke(f)
