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
    write_json(base / 'private/expected_delta.json', {'expected_changes': ['Sheet!A1']})
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


def native_registry(root, *, source='a' * 64, cell='A1', path='data/manifests/native_risks.json'):
    registry = root / path
    write_json(registry, {'sources': [{'source_sha256': source, 'risks': [{
        'risk_id': 'offline-native-fact', 'certainty': 'confirmed',
        'unsafe_regions': [f'Sheet!{cell}'], 'evidence': ['Observed offline fixture defect']}]}]})
    return registry


def test_new_native_fact_refuses_unchanged_old_harbor_proofs(fixture_run):
    root, run, audit = fixture_run
    tasks = [fixture_task(run, audit, mode, source='a' * 64) for mode in release.MODES]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
              for directory in [run / 'SpreadsheetEval', run / 'offline_control_fixtures']
              for path in directory.rglob('*') if path.is_file()}
    assert release.package_release(run, 1, root / 'before-fact', project_root=root)['task_count'] == 2
    native_registry(root)
    with pytest.raises(release.ReleaseError, match='latest native-risk registry confirms'):
        release.package_release(run, 1, root / 'after-fact', project_root=root)
    assert not (root / 'after-fact').exists()
    assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in before.items())
    assert all(task['status'] == 'qualified' for task in audit.snapshot()['tasks'])


@pytest.mark.parametrize('risk_source,cell,state,count', [
    ('a' * 64, 'B1', 'clear', 1), ('b' * 64, 'A1', 'not_applicable', 0)],
    ids=['same-source-disjoint-region', 'other-exact-source'])
def test_native_risk_check_respects_configured_registry_and_exact_intersections(
        fixture_run, risk_source, cell, state, count):
    root, run, audit = fixture_run
    tasks = [fixture_task(run, audit, mode, source='a' * 64) for mode in release.MODES]
    native_registry(root)  # The default would block; explicit configuration must win.
    registry = native_registry(root, source=risk_source, cell=cell, path='config/native-fixture.json')
    write_json(run / 'resolved_config.yaml', {'native_risks': {'registry_path': 'config/native-fixture.json'}})
    result = release.package_release(run, 1, root / 'release', project_root=root)
    manifest = json.loads(Path(result['manifest']).read_text())
    for task, (_, base, export) in zip(manifest['tasks'], tasks):
        receipt = task['native_risk_check']
        assert receipt['state'] == state and receipt['registered_risk_count'] == count
        assert receipt['source_sha256'] == 'a' * 64
        assert receipt['registry_sha256'] == hashlib.sha256(registry.read_bytes()).hexdigest()
        assert receipt['expected_delta_sha256'] == hashlib.sha256((base / 'private/expected_delta.json').read_bytes()).hexdigest()
        assert receipt['expected_delta_artifact_status'] == 'verified'
        assert receipt['goal_sha256'] == hashlib.sha256((export / 'tests/reference.xlsx').read_bytes()).hexdigest()
        assert receipt['baseline_business_correctness_certified'] is False


@pytest.mark.parametrize('artifact_status', ['missing', 'unavailable'])
def test_missing_or_damaged_private_delta_cannot_bypass_actual_native_intersection(fixture_run, artifact_status):
    root, run, audit = fixture_run
    tasks = [fixture_task(run, audit, mode, source='a' * 64) for mode in release.MODES]
    native_registry(root)
    for _, base, _ in tasks:
        path = base / 'private/expected_delta.json'
        if artifact_status == 'missing':
            path.unlink()
        else:
            path.write_text('{broken')
    with pytest.raises(release.ReleaseError, match='latest native-risk registry confirms'):
        release.package_release(run, 1, root / 'release', project_root=root)
    assert not (root / 'release').exists()


@pytest.mark.parametrize('artifact_status', ['missing', 'unavailable'])
def test_absent_private_delta_without_known_risk_keeps_separate_artifact_status(fixture_run, artifact_status):
    root, run, audit = fixture_run
    tasks = [fixture_task(run, audit, mode, source='a' * 64) for mode in release.MODES]
    write_json(root / 'data/manifests/native_risks.json', {'sources': []})
    for _, base, _ in tasks:
        path = base / 'private/expected_delta.json'
        if artifact_status == 'missing':
            path.unlink()
        else:
            path.write_text('{broken')
    result = release.package_release(run, 1, root / 'release', project_root=root)
    manifest = json.loads(Path(result['manifest']).read_text())
    for task in manifest['tasks']:
        receipt = task['native_risk_check']
        assert receipt['state'] == 'not_applicable' and receipt['evidence_request_count'] == 0
        assert receipt['expected_delta_artifact_status'] == artifact_status
        assert (receipt['expected_delta_sha256'] is None) == (artifact_status == 'missing')
        assert receipt['computed_delta_sha256'] == hashlib.sha256(b'["Sheet!A1"]').hexdigest()
        assert receipt['baseline_business_correctness_certified'] is False


def test_registry_changed_during_copy_prevents_publication(fixture_run, monkeypatch):
    root, run, audit = fixture_run
    [fixture_task(run, audit, mode, source='a' * 64) for mode in release.MODES]
    native_registry(root, cell='B1')
    copy_payload = release._copy_payload

    def copy_then_register_new_fact(*args, **kwargs):
        copy_payload(*args, **kwargs)
        native_registry(root)

    monkeypatch.setattr(release, '_copy_payload', copy_then_register_new_fact)
    with pytest.raises(release.ReleaseError, match='Native-risk evidence changed during packaging'):
        release.package_release(run, 1, root / 'release', project_root=root)
    assert not (root / 'release').exists()
    assert not list(root.glob('.*.partial-*'))


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


@pytest.mark.parametrize('unfinished', [{}, {'finished_at': None}, {'finished_at': ''}],
                         ids=['missing-finish-time', 'null-finish-time', 'empty-finish-time'])
def test_unfinished_ancestor_batch_refuses_even_qualified_tasks(fixture_run, unfinished):
    root, run, audit = fixture_run
    tasks = pair(run, audit)
    bindings = {binding['task_name']: binding for _, _, export in tasks
                for binding in [inspect_export(export)]}
    write_json(run / 'SpreadsheetEval/batch_manifest.json', {
        'offline_fixture': True, 'export_bindings': bindings,
        'status': 'completed', 'complete': True, **unfinished})

    with pytest.raises(release.ReleaseError, match='batch manifest is not finalized'):
        release.package_release(run, 1, root / 'release', project_root=root)
    assert not (root / 'release').exists()
    assert not list(root.glob('.*.partial-*'))


@pytest.mark.parametrize('final_state', [{}, {'status': 'failed', 'complete': False}],
                         ids=['manual-without-status', 'partially-failed-batch'])
def test_finalized_ancestor_batch_allows_qualified_tasks(fixture_run, final_state):
    root, run, audit = fixture_run
    tasks = pair(run, audit)
    bindings = {binding['task_name']: binding for _, _, export in tasks
                for binding in [inspect_export(export)]}
    batch_path = run / 'SpreadsheetEval/batch_manifest.json'
    write_json(batch_path, {
        'offline_fixture': True, 'export_bindings': bindings,
        'finished_at': '2026-10-29T00:00:00+00:00', **final_state})

    result = release.package_release(run, 1, root / 'release', project_root=root)
    assert result['task_count'] == 2
    manifest = json.loads(Path(result['manifest']).read_text())
    expected_receipt = {'path': str(batch_path),
                        'sha256': hashlib.sha256(batch_path.read_bytes()).hexdigest()}
    for task in manifest['tasks']:
        for control in task['controls'].values():
            assert control['batch_manifests'] == [expected_receipt]


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
            {'visibility': 'review', 'cache_hit': True, 'origin_diagnostic_run_id': 'offline-fixture'}]})
    result = release.package_release(run, 1, root / 'release', project_root=root)
    assert result['task_count'] == 2


def cached_public_fresh_private(base):
    """Model a public cache hit after a changed recovery required fresh review."""
    diagnosis_path = base / 'private/diagnosis.json'
    diagnosis = json.loads(diagnosis_path.read_text())
    recovery = json.loads((base / 'private/independent_recovery.json').read_text())
    old_path = base / 'diagnostic_private-offline-fixture/evidence.json'
    old_private = json.loads(old_path.read_text())
    old_private['private']['independent_recovery'] = {'verified': False, 'error': 'offline failed old recovery'}
    old_private['assigned_check_ids'] = ['Q04', 'Q09']
    write_json(old_path, old_private)

    common = {key: diagnosis[key] for key in ('task_revision_hash', 'check_plan_hash')}
    public = {**common, 'diagnostic_run_id': 'offline-fixture', 'visibility': 'public_only',
              'assigned_check_ids': ['Q01'], 'public': {
                  'input_sha256': hashlib.sha256((base / 'public/input.xlsx').read_bytes()).hexdigest(),
                  'instruction': (base / 'public/instruction.md').read_text()}}
    private = {**common, 'diagnostic_run_id': 'fresh-review', 'visibility': 'review',
               'assigned_check_ids': ['Q04', 'Q09'], 'private': {'independent_recovery': recovery}}
    locations = []
    for name, evidence in [('diagnostic_public-cache-origin', public), ('diagnostic_private-fresh', private)]:
        directory = base / name
        directory.mkdir()
        for filename in ('input.xlsx', 'instruction.md'):
            shutil.copy2(base / 'public' / filename, directory / filename)
        write_json(directory / 'evidence.json', evidence)
        locations.append(directory / 'evidence.json')

    def receipt(evidence, cached):
        stable = {key: value for key, value in evidence.items() if key != 'diagnostic_run_id'}
        digest = hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
        return {'visibility': evidence['visibility'], 'assigned_check_ids': evidence['assigned_check_ids'],
                'status': 'completed', 'cache_hit': cached, 'payload_digest': digest,
                **({'origin_diagnostic_run_id': evidence['diagnostic_run_id']} if cached else {})}

    diagnosis.update(diagnostic_run_id='fresh-review', llm_batches=[receipt(public, True), receipt(private, False)])
    write_json(diagnosis_path, diagnosis)
    return locations


def test_public_cache_origin_does_not_reuse_its_obsolete_private_review(fixture_run):
    root, run, audit = fixture_run
    tasks = pair(run, audit)
    for _, base, _ in tasks:
        cached_public_fresh_private(base)
    result = release.package_release(run, 1, root / 'release', project_root=root)
    manifest = json.loads(Path(result['manifest']).read_text())
    for task in manifest['tasks']:
        assert len(task['diagnosis']['reviewed_recovery_evidence']) == 1
        assert '/diagnostic_private-fresh/' in task['diagnosis']['reviewed_recovery_evidence'][0]['path']
        assert len(task['diagnosis']['public_diagnosis_evidence']) == 1
        assert '/diagnostic_public-cache-origin/' in task['diagnosis']['public_diagnosis_evidence'][0]['path']


def test_cached_private_review_still_must_bind_current_recovery(fixture_run):
    root, run, audit = fixture_run
    tasks = pair(run, audit)
    for _, base, _ in tasks:
        cached_public_fresh_private(base)
        path = base / 'private/diagnosis.json'
        diagnosis = json.loads(path.read_text())
        diagnosis['llm_batches'][1].update(cache_hit=True, origin_diagnostic_run_id='offline-fixture')
        write_json(path, diagnosis)
    with pytest.raises(release.ReleaseError, match='reviewed different recovery evidence'):
        release.package_release(run, 1, root / 'release', project_root=root)


@pytest.mark.parametrize('mutation', ['missing_input', 'missing_instruction', 'missing_evidence',
    'changed_input', 'changed_instruction', 'wrong_revision', 'wrong_check_plan', 'changed_payload'])
def test_cached_public_provenance_cannot_be_missing_stale_or_tampered(fixture_run, mutation):
    root, run, audit = fixture_run
    tasks = pair(run, audit)
    public_path, _ = cached_public_fresh_private(tasks[0][1])
    if mutation.startswith('missing_'):
        name = {'missing_input': 'input.xlsx', 'missing_instruction': 'instruction.md',
                'missing_evidence': 'evidence.json'}[mutation]
        (public_path.parent / name).unlink()
    elif mutation == 'changed_input':
        workbook(public_path.parent / 'input.xlsx', 99)
    elif mutation == 'changed_instruction':
        (public_path.parent / 'instruction.md').write_text('Changed offline instruction')
    else:
        evidence = json.loads(public_path.read_text())
        key = {'wrong_revision': 'task_revision_hash', 'wrong_check_plan': 'check_plan_hash',
               'changed_payload': 'public'}[mutation]
        evidence[key] = 'tampered'
        write_json(public_path, evidence)
    with pytest.raises(release.ReleaseError):
        release.package_release(run, 1, root / 'release', project_root=root)
    assert not (root / 'release').exists()


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
