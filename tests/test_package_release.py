"""Offline persisted-proof fixtures; these do not run or claim real Harbor jobs."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import tarfile

import openpyxl
import pytest
from dirhash import dirhash

from sheets_factory.core.audit import AuditStore
from sheets_factory.evaluation.harbor import export_harbor, inspect_export

spec = importlib.util.spec_from_file_location('package_release', Path(__file__).parents[1] / 'scripts/package_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def workbook(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    book = openpyxl.Workbook()
    book.active['A1'] = value
    book.save(path)
    book.close()


def fixture_task(run, audit, mode, suffix='a', source='source-a'):
    task_id = ('fm-' if mode == 'financial_modeling' else 'dbg-') + suffix
    base = run / 'tasks' / task_id / 'revisions/000'
    workbook(base / 'public/input.xlsx', 1)
    workbook(base / 'private/goal.xlsx', 2)
    instruction = 'Set A1 to 2 and save /app/output.xlsx. Offline test fixture.\n'
    (base / 'public/instruction.md').write_text(instruction)
    revision_hash = hashlib.sha256((base / 'public/input.xlsx').read_bytes() + instruction.encode()).hexdigest()
    program = 'raise RuntimeError("offline fixture, never execute")\n'
    workspace, replay = base / 'recovery_public-offline-fixture', base / 'recovery_replay-offline-fixture'
    for directory in (workspace, replay):
        directory.mkdir()
        (directory / 'input.xlsx').write_bytes((base / 'public/input.xlsx').read_bytes())
        (directory / 'recovery.py').write_text(program)
    (workspace / 'instruction.md').write_text(instruction)
    (base / 'private/recovered.xlsx').write_bytes((base / 'private/goal.xlsx').read_bytes())
    (replay / 'output.xlsx').write_bytes((base / 'private/goal.xlsx').read_bytes())
    write_json(base / 'private/independent_recovery.json', {
        'offline_fixture': True, 'verified': True, 'public_information_only': True,
        'workspace': str(workspace), 'program': program,
        'compiler': {'code': program, 'assumptions_added': [], 'unresolved_questions': []},
        'replay': {'directory': str(replay), 'returncode': 0}, 'comparison': {'reward': 1}})
    write_json(base / 'private/diagnosis.json', {
        'offline_fixture': True, 'releasable': True, 'task_revision_hash': revision_hash,
        'diagnostic_run_id': 'offline-fixture', 'check_plan_hash': 'offline-check-plan',
        'enabled_check_ids': ['Q01'], 'assessments': {
            'Q01': {'state': 'clear'},
            'Q10': {'state': 'clear', 'evidence': [{'engine': {
                'backend': 'libreoffice_uno_docker', 'image': 'sheetsfactory-lo:24.2',
                'image_id': 'sha256:' + '0' * 64,
                'version': 'LibreOffice 24.2.7.2 offline-fixture'}}]}}, 'coverage': {}})
    evidence = base / 'diagnostic_private-offline-fixture'
    evidence.mkdir()
    (evidence / 'input.xlsx').write_bytes((base / 'public/input.xlsx').read_bytes())
    (evidence / 'instruction.md').write_text(instruction)
    write_json(evidence / 'evidence.json', {
        'diagnostic_run_id': 'offline-fixture', 'task_revision_hash': revision_hash,
        'check_plan_hash': 'offline-check-plan', 'visibility': 'review',
        'private': {'independent_recovery': json.loads((base / 'private/independent_recovery.json').read_text())}})
    export = run / 'SpreadsheetEval' / task_id
    export_harbor(base, export, {'task_id': task_id, 'mode': mode, 'source_id': source,
                              'revision': 0, 'revision_hash': revision_hash})
    binding = inspect_export(export)
    proof = {}
    for agent, reward in [('oracle', 1), ('nop', 0)]:
        result = run / 'offline_control_fixtures' / task_id / agent / 'trial/result.json'
        write_json(result, {'offline_fixture': True, 'task_name': binding['task_name'],
                           'verifier_result': {'rewards': {'reward': reward}}, 'exception_info': None,
                           'task_checksum': dirhash(export, 'sha256'),
                           'task_id': {'path': str(export)}, 'agent_info': {'name': agent},
                           'config': {'agent': {'name': agent}, 'task': {'path': str(export)}}})
        proof[agent] = {'task_name': binding['task_name'], 'reward': reward, 'expected': reward,
                        'matched': True, 'exception_info': None, 'result_file': str(result)}
    write_json(run / 'offline_control_fixtures' / task_id / 'control_summary.json',
               {'offline_fixture': True, 'export_root': str(run / 'SpreadsheetEval'),
                'per_task': {binding['task_name']: proof}})
    audit.task(task_id, mode=mode, source_id=source, source='offline_fixture.xls',
               status='qualified', revision=0, variant=0,
               harbor_controls=proof, harbor_export_binding=binding)
    return task_id, base, export


@pytest.fixture
def fixture_run(tmp_path, monkeypatch):
    root = tmp_path / 'project'
    run = root / 'outputs/runs/offline-fixture'
    audit = AuditStore(run, {'id': 'offline-fixture', 'status': 'completed'})
    recipe = root / 'src/sheets_factory/workbook'
    recipe.mkdir(parents=True)
    actual_recipe = Path(__file__).parents[1] / 'src/sheets_factory/workbook'
    for name in release.RUNTIME_FILES:
        shutil.copy2(actual_recipe / name, recipe / name)

    def report(*args, **kwargs):
        tasks = release.read_run(run)['tasks']
        return {'tasks': [{'task_id': task['id'], 'verified_qualified': True} for task in tasks],
                'yield': {'candidates': len(tasks), 'verified_qualified': len(tasks)},
                'sources': {'construction_attempted_unique_seeds': 7},
                'run': {'difficulty_status': 'deferred'}}

    # The report's verified set is deliberately mocked. All export/hash/control
    # result/recovery checks beneath it still read actual offline fixture files.
    monkeypatch.setattr(release, 'generate_report', report)
    return root, run, audit


def pair(run, audit):
    return [fixture_task(run, audit, mode) for mode in release.MODES]


def test_shortfall_refuses_before_creating_output(fixture_run):
    root, run, audit = fixture_run
    fixture_task(run, audit, 'financial_modeling')
    destination = root / 'release'
    with pytest.raises(release.ReleaseError, match='Insufficient verified debugging'):
        release.package_release(run, 1, destination, project_root=root)
    assert not destination.exists()
    assert not list(root.glob('.*.partial-*'))


def test_fake_qualified_report_does_not_replace_actual_proofs(fixture_run):
    root, run, audit = fixture_run
    pair(run, audit)
    audit.task('fm-a', harbor_controls={})
    with pytest.raises(release.ReleaseError, match='controls are not matched'):
        release.package_release(run, 1, root / 'release', project_root=root)
    assert not (root / 'release').exists()


def test_export_hash_change_refuses(fixture_run):
    root, run, audit = fixture_run
    tasks = pair(run, audit)
    with (tasks[0][2] / 'instruction.md').open('a') as stream:
        stream.write('tampered')
    with pytest.raises(ValueError, match='differs from manifest'):
        release.package_release(run, 1, root / 'release', project_root=root)
    assert not (root / 'release').exists()


@pytest.mark.parametrize('artifact', ['diagnosis', 'recovery', 'control_result', 'goal'])
def test_missing_or_stale_latest_evidence_refuses(fixture_run, artifact):
    root, run, audit = fixture_run
    tasks = pair(run, audit)
    base = tasks[0][1]
    if artifact == 'diagnosis':
        path = base / 'private/diagnosis.json'
        data = json.loads(path.read_text())
        write_json(path, {**data, 'task_revision_hash': 'stale-revision'})
    elif artifact == 'recovery':
        workbook(base / 'recovery_replay-offline-fixture/input.xlsx', 99)
    elif artifact == 'control_result':
        path = run / 'offline_control_fixtures/fm-a/oracle/trial/result.json'
        data = json.loads(path.read_text())
        data['verifier_result']['rewards']['reward'] = 0
        write_json(path, data)
    else:
        workbook(base / 'private/goal.xlsx', 99)
    with pytest.raises(release.ReleaseError):
        release.package_release(run, 1, root / 'release', project_root=root)
    assert not (root / 'release').exists()


def test_ten_plus_ten_selection_is_stable_and_source_diverse():
    tasks = [{'id': f'{mode}-{source}-{variant}', 'mode': mode, 'source_id': source,
              'variant': variant, 'revision': 0}
             for mode in release.MODES for source in ('c', 'a', 'b', 'd') for variant in range(4)]
    expected = release.select_diverse(tasks, 10)
    random.Random(13).shuffle(tasks)
    assert release.select_diverse(tasks, 10) == expected
    assert len(expected) == 20
    for mode in release.MODES:
        group = [task for task in expected if task['mode'] == mode]
        assert len(group) == 10
        assert [task['source_id'] for task in group[:4]] == ['a', 'b', 'c', 'd']
        assert max(sum(task['source_id'] == source for task in group) for source in 'abcd') == 3


def test_payload_is_exact_immutable_and_run_is_not_changed(fixture_run):
    root, run, audit = fixture_run
    pair(run, audit)
    secret = root / '.secrets/api_key'
    secret.parent.mkdir()
    secret.write_text('offline-test-credential-never-package')
    (run / 'private').mkdir()
    (run / 'private/raw_request_log.json').write_text(secret.read_text())
    # SQLite's read-only WAL reader updates transient shared-memory lock bytes;
    # the database, WAL contents and every task/proof artifact must stay exact.
    before = {str(path.relative_to(run)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in run.rglob('*') if path.is_file() and path.name != 'run.sqlite-shm'}
    destination = root / 'release'
    result = release.package_release(run, 1, destination, project_root=root)
    assert result['task_count'] == 2
    assert result['counts_by_mode'] == {'financial_modeling': 1, 'debugging': 1}
    assert Path(result['archive']).is_absolute()
    manifest = json.loads(Path(result['manifest']).read_text())
    assert manifest['selected_task_ids'] == ['fm-a', 'dbg-a']
    assert manifest['run_snapshot']['sources']['construction_attempted_unique_seeds'] == 7
    assert manifest['tasks'][0]['controls']['oracle']['path'].endswith('result.json')
    assert manifest['tasks'][0]['independent_recovery']['current_value_comparison_reward'] == 1
    with tarfile.open(result['archive']) as archive:
        names = archive.getnames()
        assert 'SpreadsheetEval/fm-a/solution/reference.xlsx' in names
        assert 'SpreadsheetEval/fm-a/tests/reference.xlsx' in names
        assert not any('private' in name or '.secrets' in name for name in names)
        assert all(name in {'release_manifest.json', 'prepare_runtime.sh', 'README.md', 'runtime'}
                   or name.startswith(('SpreadsheetEval', 'runtime/')) for name in names)
    assert hashlib.sha256(Path(result['archive']).read_bytes()).hexdigest() == result['sha256']
    after = {str(path.relative_to(run)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in run.rglob('*') if path.is_file() and path.name != 'run.sqlite-shm'}
    assert before == after
    with pytest.raises(release.ReleaseError, match='already exists'):
        release.package_release(run, 1, destination, project_root=root)


def test_changes_during_copy_abort_without_published_release(fixture_run, monkeypatch):
    root, run, audit = fixture_run
    tasks = pair(run, audit)
    copy_payload = release._copy_payload
    changed = False

    def copy_then_mutate(*args, **kwargs):
        nonlocal changed
        copied = copy_payload(*args, **kwargs)
        if not changed:
            changed = True
            with (tasks[0][1] / 'private/diagnosis.json').open('a') as stream:
                stream.write(' ')
        return copied

    monkeypatch.setattr(release, '_copy_payload', copy_then_mutate)
    with pytest.raises(release.ReleaseError, match='changed during packaging'):
        release.package_release(run, 1, root / 'release', project_root=root)
    assert not (root / 'release').exists()
    assert not list(root.glob('.*.partial-*'))


def test_symlink_or_extra_private_files_are_rejected(fixture_run):
    root, run, audit = fixture_run
    tasks = pair(run, audit)
    (tasks[0][2] / 'private').mkdir()
    (tasks[0][2] / 'private/log.json').write_text('{}')
    with pytest.raises(release.ReleaseError, match='Unexpected or missing'):
        release.package_release(run, 1, root / 'release', project_root=root)


def test_known_credential_in_public_payload_is_rejected(fixture_run):
    root, run, audit = fixture_run
    tasks = pair(run, audit)
    secret = root / '.secrets/api_key'
    secret.parent.mkdir()
    secret.write_text('offline-test-credential-never-package')
    (tasks[0][2] / 'instruction.md').write_text(secret.read_text())
    with pytest.raises(release.ReleaseError, match='Credential found'):
        release.package_release(run, 1, root / 'release', project_root=root)


@pytest.mark.parametrize('mutation', ['wrong_agent', 'historical_checksum', 'missing_replay_output'])
def test_actual_execution_identity_and_outputs_are_required(fixture_run, mutation):
    root, run, audit = fixture_run
    tasks = pair(run, audit)
    result_file = run / 'offline_control_fixtures/fm-a/oracle/trial/result.json'
    result = json.loads(result_file.read_text())
    if mutation == 'wrong_agent':
        result['agent_info']['name'] = 'nop'
        write_json(result_file, result)
    elif mutation == 'historical_checksum':
        result['task_checksum'] = '0' * 64
        write_json(result_file, result)
    else:
        (tasks[0][1] / 'recovery_replay-offline-fixture/output.xlsx').unlink()
    with pytest.raises(release.ReleaseError):
        release.package_release(run, 1, root / 'release', project_root=root)
    assert not (root / 'release').exists()


def test_credential_in_release_metadata_is_rejected(fixture_run):
    root, run, audit = fixture_run
    pair(run, audit)
    secret = root / '.secrets/api_key'
    secret.parent.mkdir()
    secret.write_text('offline-test-credential-never-package')
    audit.task('fm-a', source=secret.read_text())
    with pytest.raises(release.ReleaseError, match='Credential found in release metadata'):
        release.package_release(run, 1, root / 'release', project_root=root)
    assert not (root / 'release').exists()


def test_credential_in_compressed_workbook_is_rejected(fixture_run):
    root, run, audit = fixture_run
    tasks = pair(run, audit)
    secret = root / '.secrets/api_key'
    secret.parent.mkdir()
    secret.write_text('offline-test-credential-never-package')
    workbook(tasks[0][2] / 'environment/input.xlsx', secret.read_text())
    with pytest.raises(release.ReleaseError, match='Credential found in workbook payload'):
        release.package_release(run, 1, root / 'release', project_root=root)


def test_new_nested_manifest_during_copy_is_not_packaged(fixture_run, monkeypatch):
    root, run, audit = fixture_run
    tasks = pair(run, audit)
    copy_payload = release._copy_payload
    changed = False

    def add_file_and_copy(source, target):
        nonlocal changed
        if not changed:
            changed = True
            extra = tasks[0][2] / 'private/export_manifest.json'
            extra.parent.mkdir()
            extra.write_text('offline fixture private log; must never enter tar')
        copy_payload(source, target)
        assert not (target / 'private').exists()

    monkeypatch.setattr(release, '_copy_payload', add_file_and_copy)
    with pytest.raises(release.ReleaseError, match='Unexpected or missing'):
        release.package_release(run, 1, root / 'release', project_root=root)
    assert not (root / 'release').exists()
    assert not list(root.glob('.*.partial-*'))


def test_concurrent_destination_creation_is_never_overwritten(fixture_run, monkeypatch):
    root, run, audit = fixture_run
    pair(run, audit)
    copy_payload = release._copy_payload
    destination = root / 'release'

    def copy_and_claim_destination(source, target):
        copy_payload(source, target)
        destination.mkdir(exist_ok=True)

    monkeypatch.setattr(release, '_copy_payload', copy_and_claim_destination)
    with pytest.raises(release.ReleaseError, match='already exists'):
        release.package_release(run, 1, destination, project_root=root)
    assert list(destination.iterdir()) == []
    assert not list(root.glob('.*.partial-*'))


def test_diagnosis_must_have_reviewed_this_recovery_record(fixture_run):
    root, run, audit = fixture_run
    tasks = pair(run, audit)
    path = tasks[0][1] / 'private/independent_recovery.json'
    recovery = json.loads(path.read_text())
    write_json(path, {**recovery, 'evidence_version': 'changed-after-diagnosis'})
    with pytest.raises(release.ReleaseError, match='reviewed different recovery evidence'):
        release.package_release(run, 1, root / 'release', project_root=root)


def test_cached_diagnosis_origin_can_bind_same_recovery(fixture_run):
    root, run, audit = fixture_run
    tasks = pair(run, audit)
    for _, base, _ in tasks:
        path = base / 'private/diagnosis.json'
        diagnosis = json.loads(path.read_text())
        write_json(path, {**diagnosis, 'diagnostic_run_id': 'new-cached-diagnosis', 'llm_batches': [
            {'cache_hit': True, 'origin_diagnostic_run_id': 'offline-fixture'}]})
    result = release.package_release(run, 1, root / 'release', project_root=root)
    assert result['task_count'] == 2


def test_runtime_context_is_minimal_documented_and_prepares_from_any_directory(fixture_run, tmp_path):
    root, run, audit = fixture_run
    tasks = pair(run, audit)
    recipe = root / 'src/sheets_factory/workbook'
    (recipe / 'private').mkdir()
    (recipe / 'private/raw_log.json').write_text('offline private log must not be copied')
    (recipe / 'unrelated.py').write_text('offline unrelated implementation')
    result = release.package_release(run, 1, root / 'release with spaces', project_root=root)
    destination = Path(result['release_directory'])
    runtime = destination / 'runtime'
    assert {path.name for path in runtime.iterdir()} == release.RUNTIME_FILES
    assert release._runtime_copy_sources((runtime / 'Dockerfile').read_bytes()) == {'uno_recalculate.py'}
    manifest = json.loads(Path(result['manifest']).read_text())
    metadata = manifest['runtime']
    assert metadata['image_tag'] == 'sheetsfactory-lo:24.2'
    assert metadata['recorded_run_images'][0]['image_id'] == 'sha256:' + '0' * 64
    assert 'offline-fixture' in metadata['recorded_run_images'][0]['libreoffice_version']
    assert metadata['image_archive_included'] is False
    assert metadata['bit_identical_rebuild_guaranteed'] is False
    for relative, receipt in metadata['recipe_files'].items():
        assert hashlib.sha256((destination / relative).read_bytes()).hexdigest() == receipt['sha256']
    readme = (destination / 'README.md').read_text()
    assert './prepare_runtime.sh' in readme
    assert 'harbor run --path SpreadsheetEval --agent oracle' in readme
    assert 'harbor run --path SpreadsheetEval --agent nop' in readme
    assert '重新构建不保证与原运行相同的 image ID' in readme
    script = destination / 'prepare_runtime.sh'
    assert script.stat().st_mode & 0o111
    # Execute only the wrapper against an offline fake Docker command, never
    # building an image or contacting a registry during the test.
    commands = tmp_path / 'fake-commands'
    commands.mkdir()
    fake = commands / 'docker'
    fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$SHEETS_FACTORY_TEST_DOCKER_ARGS"\n')
    fake.chmod(0o755)
    arguments = tmp_path / 'docker_args.txt'
    env = {**os.environ, 'PATH': str(commands) + os.pathsep + os.environ['PATH'],
           'SHEETS_FACTORY_TEST_DOCKER_ARGS': str(arguments)}
    subprocess.run([str(script)], cwd=tmp_path, env=env, check=True)
    assert arguments.read_text().splitlines() == [
        'build', '--network', 'host', '-t', 'sheetsfactory-lo:24.2', str(runtime)]
    with tarfile.open(result['archive']) as archive:
        runtime_names = {name for name in archive.getnames() if name.startswith('runtime/')}
        assert runtime_names == {'runtime/Dockerfile', 'runtime/uno_recalculate.py'}
        assert 'prepare_runtime.sh' in archive.getnames()
        assert 'README.md' in archive.getnames()
    for task_id, _, export in tasks:
        assert inspect_export(export) == inspect_export(destination / 'SpreadsheetEval' / task_id)


@pytest.mark.parametrize('mutation', ['extra_copy', 'missing_copy_file', 'remote_add', 'missing_image_evidence'])
def test_runtime_incomplete_or_nonallowlisted_context_refuses(fixture_run, mutation):
    root, run, audit = fixture_run
    tasks = pair(run, audit)
    recipe = root / 'src/sheets_factory/workbook'
    if mutation == 'extra_copy':
        with (recipe / 'Dockerfile').open('a') as stream:
            stream.write('\nCOPY private.json /tmp/private.json\n')
        (recipe / 'private.json').write_text('private fixture')
    elif mutation == 'missing_copy_file':
        (recipe / 'uno_recalculate.py').unlink()
    elif mutation == 'remote_add':
        with (recipe / 'Dockerfile').open('a') as stream:
            stream.write('\nADD https://example.test/private.json /tmp/private.json\n')
    else:
        path = tasks[0][1] / 'private/diagnosis.json'
        diagnosis = json.loads(path.read_text())
        diagnosis['assessments'].pop('Q10')
        write_json(path, diagnosis)
    with pytest.raises(release.ReleaseError):
        release.package_release(run, 1, root / 'release', project_root=root)
    assert not (root / 'release').exists()


def test_runtime_recipe_credential_refuses(fixture_run):
    root, run, audit = fixture_run
    pair(run, audit)
    secret = root / '.secrets/api_key'
    secret.parent.mkdir()
    secret.write_text('offline-test-credential-never-package')
    recipe_file = root / 'src/sheets_factory/workbook/uno_recalculate.py'
    with recipe_file.open('a') as stream:
        stream.write('\n# ' + secret.read_text() + '\n')
    with pytest.raises(release.ReleaseError, match='Credential found in runtime release payload'):
        release.package_release(run, 1, root / 'release', project_root=root)
    assert not (root / 'release').exists()
