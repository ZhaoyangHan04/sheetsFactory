"""Offline publication composition tests; all service/financial witnesses are fake.

Real file inventories, payload isolation, replay bytes, native timing parsing,
source-run routing and atomic staging are exercised. These fixtures certify no
source, task, model result, Docker resource enforcement or twenty-task cohort.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

from dirhash import dirhash
import openpyxl
import pytest

from sheets_factory.core.audit import AuditStore
from sheets_factory.evaluation import resource_publication as resource
from sheets_factory.evaluation import resource_frontier, frontier
from sheets_factory.evaluation.resource_harbor import export_resource_harbor, inspect_resource_export
from sheets_factory.evaluation.tool_time_bounds import POLICY_V2
from sheets_factory.workbook.resource_engine import load_runtime_profile
from test_frontier import persist_timing
from test_package_release import fixture_task, write_json, compact_private_fixture
from test_publish_dataset import fixture_publication, confirmation, invoke

ROOT = Path(__file__).parents[1]
PROFILE = ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml'


def script(name):
    spec = importlib.util.spec_from_file_location('_test_resource_' + name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


publish = script('publish_dataset')
cli = script('publish_resource_dataset')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cohort_row(run, task, family):
    return {'task_id': task['id'], 'source_run': str(run), 'family': family,
            'audited_harbor_export_binding': task.get('harbor_export_binding'),
            **{key: task.get(key) for key in ('mode', 'revision', 'revision_hash', 'source_id', 'harbor_export_binding')}}


def cohort(rows):
    return {'kind': resource.KIND, 'version': 1, 'status': 'frozen_for_fresh_confirmation',
            'selected_task_ids': [row['task_id'] for row in rows], 'tasks': rows,
            'frozen_at': '2026-10-29T11:59:00Z', 'execution_budget': dict(resource.BUDGET),
            'tool_time_policy_version': 2, 'selection_uses_confirmation_outcomes': False,
            'publication_recipe': resource.publication_recipe(ROOT)}


@pytest.fixture
def offline(tmp_path, monkeypatch):
    monkeypatch.setattr(resource, 'MIN_PER_MODE', 1)
    monkeypatch.setattr(publish, 'MIN_PER_MODE', 1)
    root = tmp_path / 'checkout'; recipe = root / 'src/sheets_factory/workbook'
    recipe.mkdir(parents=True)
    for name in publish.release.RUNTIME_FILES:
        shutil.copy2(ROOT / 'src/sheets_factory/workbook' / name, recipe / name)
    shutil.copy2(ROOT / 'uv.lock', root / 'uv.lock')
    audits, rows = [], []
    for mode, family in [('financial_modeling', 'scaled_capital'), ('debugging', 'entity')]:
        run = root / 'outputs/runs' / mode
        audit = AuditStore(run, {'id': mode, 'status': 'completed'})
        task_id, base, export = fixture_task(run, audit, mode, source='a' * 64)
        old = json.loads((export / 'export_manifest.json').read_text())['metadata']
        shutil.rmtree(export)
        export_resource_harbor(base, export, old, runtime_profile=PROFILE)
        binding = inspect_resource_export(export)
        task = audit.snapshot()['tasks'][0]
        for agent in ('oracle', 'nop'):
            result_path = Path(task['harbor_controls'][agent]['result_file'])
            result = json.loads(result_path.read_text()); result['task_checksum'] = dirhash(export, 'sha256')
            write_json(result_path, result)
            write_json(result_path.parent / 'config.json', result['config'])
        audit.task(task_id, revision_hash=binding['revision_hash'], harbor_export_binding=binding)
        task = audit.snapshot()['tasks'][0]
        rows.append(cohort_row(run, task, family)); audits.append(audit)
    source = root / 'outputs/cohort/cohort_manifest.json'; write_json(source, cohort(rows))
    backend = resource.ResourcePublicationBackend(source, project_root=ROOT)
    backend.root = root
    # These two boundaries explicitly stand in for expensive actual production
    # source admission and strict family witness checks. They are tested below
    # for rejection independently, and no fixture pretends to be real evidence.
    profile = load_runtime_profile(PROFILE)
    def admitted(run, family, tracked):
        return {'family': family, 'config': {}, 'profile': profile}
    monkeypatch.setattr(backend, '_run', admitted)
    def family_boundary(run, task, tracked):
        row = backend._mapping(task['id'])
        resource.require(row['source_run'] == str(run) and task['revision_hash'] == row['revision_hash'], 'fixture source mapping differs')
        backend.tasks[task['id']] = {'source_run': str(run), 'family': row['family'], 'task': deepcopy(task),
            'runtime_profile': resource.reference(PROFILE), 'runtime': profile,
            'actual_calculation_resource_bindings': 'MOCKED — no actual calculation or enforcement'}
    monkeypatch.setattr(backend, 'validate_task', family_boundary)
    observation = {'passed': True, 'complete': True, 'offline_fixture_not_actual_enforcement': True}
    monkeypatch.setitem(sys.modules, 'sheets_factory.evaluation.resource_observer', SimpleNamespace(
        validate_observation_receipt=lambda *args: deepcopy(observation),
        validate_trial_observations=lambda *args, **kwargs: deepcopy(observation)))
    selection_path = root / 'outputs/difficulty/confirmation/selection_manifest.json'
    entries = []
    for row in rows:
        directory = Path(row['source_run']) / 'SpreadsheetEval' / row['task_id']
        entries.append({key: row[key] for key in ('task_id', 'mode', 'revision', 'revision_hash', 'harbor_export_binding')} | {
            'task_directory': str(directory), 'task_checksum': dirhash(directory, 'sha256'),
            'timeout_seconds': 14400, 'execution_budget': dict(resource.BUDGET), 'tool_time_policy': dict(POLICY_V2)})
    selection = {'schema_version': 1, 'phase': 'confirmation', 'model': publish.MODEL, 'reasoning_effort': publish.EFFORT,
        'frozen_at': '2026-10-29T12:00:00Z', 'timeout_seconds': 14400, 'execution_budget': dict(resource.BUDGET),
        'tool_time_policy': dict(POLICY_V2), 'tool_time_policy_version': 2,
        'source_manifest': {'path': str(source), 'sha256': sha(source)},
        'selected_task_ids': [row['task_id'] for row in rows], 'tasks': entries}
    write_json(selection_path, selection)
    evaluation_path = selection_path.parent / 'evaluation_manifest.json'
    attempts = []
    for entry in entries:
        result = evaluation_path.parent / 'harbor_jobs/frontier-pass1' / entry['task_id'] / 'result.json'
        actual = {'offline_fixture': True, 'task_name': entry['harbor_export_binding']['task_name'],
            'task_checksum': entry['task_checksum'], 'task_id': {'path': entry['task_directory']},
            'config': {'task': {'path': entry['task_directory']}, 'agent': {'model_name': publish.MODEL,
                'kwargs': {'reasoning_effort': publish.EFFORT}, 'override_timeout_sec': 14400,
                'import_path': resource.agent_import_path if hasattr(resource, 'agent_import_path') else backend.agent_import_path}},
            'agent_info': {'name': 'codex', 'model_info': {'name': publish.MODEL}}, 'exception_info': None,
            'verifier_result': {'rewards': {'reward': 0}},
            'agent_execution': {'started_at': '2026-10-29T12:01:01Z', 'finished_at': '2026-10-29T12:01:02Z'},
            'started_at': '2026-10-29T12:01:01Z', 'finished_at': '2026-10-29T12:01:02Z'}
        write_json(result, actual); persist_timing(result)
        attempt = {**entry, 'status': 'scored', 'reward': 0, 'result_file': str(result), 'result_sha256': sha(result)}
        resource_frontier.apply_tool_time_policy(attempt, selection); attempts.append(attempt)
    write_json(evaluation_path, {'schema_version': 1, 'phase': 'confirmation', 'status': 'completed',
        'model': publish.MODEL, 'reasoning_effort': publish.EFFORT, 'timeout_seconds': 14400,
        'execution_budget': dict(resource.BUDGET), 'tool_time_policy': dict(POLICY_V2), 'tool_time_policy_version': 2,
        'selection_manifest': {'path': str(selection_path), 'sha256': sha(selection_path)},
        'started_at': '2026-10-29T12:01:00Z', 'finished_at': '2026-10-29T12:02:00Z', 'attempts': attempts,
        'gate_passed': True, 'score': {'total_tasks': 2, 'scored_tasks': 2, 'overall_pass_at_1': 0,
            'infrastructure_errors': 0, 'by_mode': {mode: {'tasks': 1, 'scored': 1, 'successes': 0, 'pass_at_1': 0}
                for mode in resource.MODES}}})
    yield SimpleNamespace(root=root, rows=rows, audits=audits, source=source, backend=backend,
                          selection=selection_path, evaluation=evaluation_path, entries=entries)
    for audit in audits:
        audit.db.close()


def invoke_resource(fixture, **kwargs):
    return publish.publish_dataset(run_dir=fixture.rows[0]['source_run'], selection_manifest=fixture.selection,
        evaluation_manifest=fixture.evaluation, project_root=fixture.root, backend=fixture.backend, **kwargs)


def test_actual_seventeen_file_inventory_and_legacy_thirteen_are_distinct(offline, tmp_path):
    export = Path(offline.entries[0]['task_directory'])
    with pytest.raises(publish.release.ReleaseError, match='Unexpected or missing'):
        publish.release._check_payload(export, export, {})
    assert publish.release._check_payload(export, export, {}, backend=offline.backend) == offline.rows[0]['harbor_export_binding']
    copy = tmp_path / 'copy'
    publish.release._copy_payload(export, copy, backend=offline.backend)
    assert {p.relative_to(copy).as_posix() for p in copy.rglob('*') if p.is_file()} == resource_frontier.TASK_FILES
    assert dirhash(copy, 'sha256') == dirhash(export, 'sha256')
    (copy / 'environment/helper.txt').write_text('private boundary fixture')
    with pytest.raises(publish.release.ReleaseError, match='Unexpected or missing'):
        publish.release._check_payload(copy, copy, {}, backend=offline.backend)


def test_two_original_runs_publish_with_real_inventory_timing_and_staging_but_fake_financial_boundary(offline):
    dry = invoke_resource(offline, dry_run=True)
    assert dry['status'] == 'validated_dry_run' and dry['task_count'] == 2
    assert dry['manifest']['confirmation']['infrastructure_history']['scored_attempts_per_task'] == 1
    assert all(len(task['payload_files']) == 17 for task in dry['manifest']['tasks'])
    assert all(item['libreoffice_version'] is None and item['version_probe_performed'] is False
               for item in dry['manifest']['runtime']['recorded_run_images'])
    assert not (offline.root / 'SpreadsheetEval').exists()
    result = invoke_resource(offline)
    assert result['status'] == 'published'
    for row in offline.rows:
        target = offline.root / 'SpreadsheetEval' / row['task_id']
        assert inspect_resource_export(target) == row['harbor_export_binding']
        assert 'streaming_core.py' in (target / 'tests/verify.py').read_text()
        assert set(json.loads((target / 'export_manifest.json').read_text())['files']) | {'export_manifest.json'} == resource_frontier.TASK_FILES
    assert '/app/output.xlsx' in (offline.root / 'SpreadsheetEval' / offline.rows[0]['task_id'] / 'solution/solve.sh').read_text()


def test_resource_runner_matching_is_not_a_string_allowlist(offline):
    selection = json.loads(offline.selection.read_text())
    new = resource_frontier.collect_attempts(offline.evaluation.parent, selection)
    old = frontier.collect_attempts(offline.evaluation.parent, selection)
    assert {entry['status'] for entry in new} == {'scored'}
    assert {entry['failure_kind'] for entry in old} == {'execution_binding_mismatch'}


def test_original_normal_H_five_field_receipt_is_preserved_while_full_resource_contract_is_verified(offline):
    for index, row in enumerate(offline.rows):
        basic = {key: row['harbor_export_binding'][key] for key in resource.STANDARD_BINDING_KEYS}
        row['audited_harbor_export_binding'] = basic
        offline.backend.cohort['tasks'][index]['audited_harbor_export_binding'] = basic
        offline.audits[index].task(row['task_id'], harbor_export_binding=basic)
        write_json(Path(row['source_run']) / 'SpreadsheetEval/batch_manifest.json', {
            'finished_at': '2026-10-29T11:58:00Z', 'export_bindings': {basic['task_name']: basic}})
    write_json(offline.source, offline.backend.cohort)
    selection = json.loads(offline.selection.read_text()); selection['source_manifest']['sha256'] = sha(offline.source)
    write_json(offline.selection, selection)
    evaluation = json.loads(offline.evaluation.read_text()); evaluation['selection_manifest']['sha256'] = sha(offline.selection)
    write_json(offline.evaluation, evaluation)
    result = invoke_resource(offline, dry_run=True)
    assert all('resource_runtime' in task['harbor_export_binding'] for task in result['manifest']['tasks'])
    assert all(set(audit.snapshot()['tasks'][0]['harbor_export_binding']) == resource.STANDARD_BINDING_KEYS
               for audit in offline.audits)


def test_audited_binding_compatibility_rejects_any_arbitrary_subset_or_changed_manifest(offline):
    complete = offline.rows[0]['harbor_export_binding']
    basic = {key: complete[key] for key in resource.STANDARD_BINDING_KEYS}
    assert resource.audit_binding_matches(complete, basic)
    assert not resource.audit_binding_matches(complete, {'task_id': complete['task_id']})
    assert not resource.audit_binding_matches(complete, basic | {'unknown': True})
    assert not resource.audit_binding_matches(complete, basic | {'export_manifest_sha256': '0' * 64})


@pytest.mark.parametrize('mutation', ['old_agent', 'timing', 'mode_score', 'sha', 'reward', 'subset', 'late_mapping', 'changed_mapping'])
def test_confirmation_fail_closed(offline, mutation):
    selection = json.loads(offline.selection.read_text()); evaluation = json.loads(offline.evaluation.read_text())
    if mutation == 'old_agent':
        path = Path(evaluation['attempts'][0]['result_file']); result = json.loads(path.read_text())
        result['config']['agent']['import_path'] = 'sheets_factory.evaluation.frontier:LocalCodex'
        write_json(path, result); evaluation['attempts'][0]['result_sha256'] = sha(path)
    elif mutation == 'timing': evaluation['attempts'][0]['tool_time']['cumulative_tool_seconds'] = 0
    elif mutation == 'mode_score': evaluation['score']['by_mode']['debugging']['tasks'] = 2
    elif mutation == 'sha': evaluation['attempts'][0]['result_sha256'] = '0' * 64
    elif mutation == 'reward': evaluation['attempts'][0]['reward'] = 1
    elif mutation == 'subset':
        selection['tasks'] = selection['tasks'][:1]; selection['selected_task_ids'] = selection['selected_task_ids'][:1]
        write_json(offline.selection, selection); evaluation['selection_manifest']['sha256'] = sha(offline.selection)
    elif mutation == 'late_mapping':
        offline.backend.cohort['frozen_at'] = '2026-10-29T12:01:30Z'
        write_json(offline.source, offline.backend.cohort)
        selection['source_manifest']['sha256'] = sha(offline.source); write_json(offline.selection, selection)
        evaluation['selection_manifest']['sha256'] = sha(offline.selection)
    else:
        offline.source.write_text(offline.source.read_text() + '\n')
    write_json(offline.evaluation, evaluation)
    with pytest.raises((ValueError, KeyError)):
        invoke_resource(offline, dry_run=True)
    assert not (offline.root / 'SpreadsheetEval').exists()


@pytest.mark.parametrize('field,value', [('passed', False), ('complete', False)])
def test_missing_actual_role_observations_are_not_inferred_from_toml(offline, monkeypatch, field, value):
    receipt = {'passed': True, 'complete': True}; receipt[field] = value
    monkeypatch.setitem(sys.modules, 'sheets_factory.evaluation.resource_observer', SimpleNamespace(
        validate_observation_receipt=lambda *args: receipt))
    with pytest.raises(resource.ResourcePublicationError, match='complete actual coverage'):
        invoke_resource(offline, dry_run=True)


@pytest.mark.parametrize('mutation', ['version_bool', 'duplicate', 'wrong_family', 'relative_run', 'missing_mode'])
def test_cohort_shape_rejects_malformed_mapping(offline, mutation):
    value = deepcopy(offline.backend.cohort)
    if mutation == 'version_bool': value['version'] = True
    elif mutation == 'duplicate': value['selected_task_ids'][1] = value['selected_task_ids'][0]
    elif mutation == 'wrong_family': value['tasks'][0]['family'] = 'entity'
    elif mutation == 'relative_run': value['tasks'][0]['source_run'] = 'outputs/run'
    else:
        value['tasks'] = value['tasks'][:1]; value['selected_task_ids'] = value['selected_task_ids'][:1]
    with pytest.raises(resource.ResourcePublicationError): resource.ResourcePublicationBackend.validate_cohort_shape(value)


def test_production_cohort_still_requires_ten_per_mode(offline, monkeypatch):
    monkeypatch.setattr(resource, 'MIN_PER_MODE', 10)
    with pytest.raises(resource.ResourcePublicationError, match='ten tasks per mode'):
        resource.ResourcePublicationBackend.validate_cohort_shape(offline.backend.cohort)


def test_source_run_mapping_cannot_silently_follow_a_different_task(offline):
    offline.backend.cohort['tasks'][0]['source_run'] = offline.backend.cohort['tasks'][1]['source_run']
    with pytest.raises(resource.ResourcePublicationError, match='mapped source task is missing'):
        invoke_resource(offline, dry_run=True)


def test_external_complete_private_artifact_rechecked_after_copy_on_legacy_path(fixture_publication, monkeypatch):
    """Regression for the existing audited_summary staging gap; no fake new task."""
    f = fixture_publication; confirmation(f)
    base = f['run'] / 'tasks' / f['entries'][0]['task_id'] / 'revisions/000'
    _, _, artifact = compact_private_fixture(f['root'], base)
    import test_publish_dataset as old_tests
    original = old_tests.publish.release._copy_payload
    def copy_then_change(*args):
        original(*args); artifact.write_text(artifact.read_text() + '\n')
    monkeypatch.setattr(old_tests.publish.release, '_copy_payload', copy_then_change)
    with pytest.raises(old_tests.publish.PublishError, match='Scoped complete private evidence changed'):
        invoke(f)
    assert not (f['root'] / 'SpreadsheetEval').exists()


def test_final_recheck_rejects_source_mapping_and_large_file_changes(offline, tmp_path):
    evidence = tmp_path / 'big'; evidence.write_bytes(b'complete bytes')
    offline.backend.extra_tracked[str(evidence)] = sha(evidence)
    evidence.write_bytes(b'changed bytes')
    with pytest.raises(resource.ResourcePublicationError, match='changed during staging'):
        offline.backend.final_recheck()


def test_cli_publication_is_read_only_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, 'publish', lambda *args, **kwargs: calls.append(kwargs) or {'offline_fixture': True})
    cli.main(['publish', '--cohort', '/fake/cohort', '--selection-manifest', '/fake/selection', '--evaluation-manifest', '/fake/evaluation'])
    assert calls == [{'publish_files': False}]


def strict_fixture(offline, monkeypatch):
    """Real tiny full-value controls; deliberately mocked source/financial kernel."""
    row = offline.rows[1]; run = Path(row['source_run']); audit = offline.audits[1]
    write_json(run / 'preflight_manifest.json', {'offline_mock_boundary_not_source_admission': True})
    base = run / 'tasks' / row['task_id'] / 'revisions/000'; private, public = base / 'private', base / 'public'
    goal, source = private / 'goal.xlsx', public / 'input.xlsx'
    task = deepcopy(audit.snapshot()['tasks'][0]); task['source_id'] = sha(goal); row['source_id'] = sha(goal)
    offline.backend.cohort['tasks'][1]['source_id'] = sha(goal)
    for name in ('normalize', 'profile', 'plan', 'construct', 'instruction', 'precheck', 'independent_recovery', 'diagnose', 'export'):
        audit.record('nodes', {'task_id': task['id'], 'revision': 0, 'node': name, 'status': 'completed'})
    controls = private / 'controls'; controls.mkdir()
    for name in ('equivalent', 'missed_root', 'extra_change'):
        path = controls / (name + '.xlsx')
        shutil.copy2(source if name == 'missed_root' else goal, path)
        if name == 'extra_change':
            book = openpyxl.load_workbook(path); book.active['A2'] = 3; book.save(path); book.close()
        shutil.copy2(path, controls / (name + '_raw.xlsx'))
    shutil.copy2(source, private / 'mutated_unrecalculated.xlsx')
    values = {}
    for name in resource.CONTROL_REWARDS:
        candidate = goal if name == 'oracle' else source if name == 'nop' else controls / (name + '.xlsx')
        values[name] = resource.compare_workbooks(source, goal, candidate)
    write_json(private / 'local_controls.json', values); write_json(private / 'expected_delta.json', values['oracle'])
    write_json(private / 'plan.json', {'edits': [{'sheet': 'Sheet', 'cell': 'A1'}]})
    write_json(private / 'entity_group_policy_inventory.json', {})
    write_json(private / 'joint_repair_certificate.json', {'engine_calls': []})
    write_json(private / 'joint_control_selection.json', {'offline_mock_boundary': True})
    for name in ('native_risk_guard', 'native_error_probe'): write_json(private / (name + '.json'), {'blocking': False})
    write_json(public / 'profile.json', {})
    diagnosis = json.loads((private / 'diagnosis.json').read_text())
    ids = [f'Q{number:02d}' for number in range(1, 13)]
    diagnosis['enabled_check_ids'] = ids
    diagnosis['llm_batches'] = [{'status': 'completed', 'visibility': 'public_only', 'assigned_check_ids': ids[:3]},
                               {'status': 'completed', 'visibility': 'review', 'assigned_check_ids': ids[3:]}]
    write_json(private / 'diagnosis.json', diagnosis)
    state = {'phase': SimpleNamespace(adapter=SimpleNamespace(SETTING='entity_group_task')),
        'config': {'entity_group_task': {'runtime_profile': resource.reference(PROFILE)}},
        'proof': {'workbook': resource.reference(goal), 'runtime_profile': resource.reference(PROFILE)},
        'profile': load_runtime_profile(PROFILE)}
    monkeypatch.setattr(offline.backend, '_run', lambda *args: state)
    calls = []
    monkeypatch.setattr(offline.backend.probe, 'validate_family_plan', lambda *args: set())
    monkeypatch.setattr(offline.backend.probe, 'resource_receipts', lambda *args: calls.append('actual_resource_gate') or [])
    monkeypatch.setattr(offline.backend, 'validate_control_observations', lambda *args: calls.append('actual_harbor_gate'))
    from sheets_factory.workbook import entity_group_public_recovery as recovery
    monkeypatch.setattr(recovery, 'valid_entity_group_recovery_witness', lambda *args: calls.append('strict_witness') or True)
    return task, base, calls, recovery


def test_strict_family_dispatch_keeps_actual_full_control_and_resource_gates(offline, monkeypatch):
    task, base, calls, _ = strict_fixture(offline, monkeypatch)
    resource.ResourcePublicationBackend.validate_task(offline.backend, Path(offline.rows[1]['source_run']), task, {})
    assert calls == ['actual_resource_gate', 'strict_witness', 'actual_harbor_gate']
    assert offline.backend.tasks[task['id']]['version_probe_performed'] is False


@pytest.mark.parametrize('mutation', ['witness', 'missing_check', 'unfinished_batch', 'missed_control', 'reduced_D', 'native_guard', 'pending_node'])
def test_strict_family_rejects_missing_witness_or_scope_even_if_qualified(offline, monkeypatch, mutation):
    task, base, calls, recovery = strict_fixture(offline, monkeypatch)
    private = base / 'private'
    if mutation == 'witness': monkeypatch.setattr(recovery, 'valid_entity_group_recovery_witness', lambda *args: False)
    elif mutation in ('missing_check', 'unfinished_batch'):
        path = private / 'diagnosis.json'; value = json.loads(path.read_text())
        if mutation == 'missing_check': value['enabled_check_ids'].pop()
        else: value['llm_batches'][0]['status'] = 'running'
        write_json(path, value)
    elif mutation == 'missed_control':
        path = private / 'local_controls.json'; value = json.loads(path.read_text()); del value['missed_root']; write_json(path, value)
    elif mutation == 'reduced_D':
        path = private / 'expected_delta.json'; value = json.loads(path.read_text()); value['expected_changes'] = []; write_json(path, value)
    elif mutation == 'native_guard': write_json(private / 'native_error_probe.json', {'blocking': True})
    else: offline.audits[1].record('nodes', {'task_id': task['id'], 'revision': 0, 'node': 'precheck', 'status': 'running'})
    with pytest.raises(ValueError):
        resource.ResourcePublicationBackend.validate_task(offline.backend, Path(offline.rows[1]['source_run']), task, {})


def test_control_observer_requires_both_passed_and_complete_and_exact_result_refs(offline, monkeypatch, tmp_path):
    row = deepcopy(offline.rows[1]); task = offline.audits[1].snapshot()['tasks'][0]
    receipt = tmp_path / 'observer.json'; write_json(receipt, {'offline_fixture_not_enforcement': True})
    row['control_observation_receipts'] = {name: [resource.reference(receipt)] for name in ('oracle', 'nop')}
    calls = []
    def observe(config, result, **kwargs):
        calls.append((config, result, kwargs)); return {'passed': True, 'complete': True}
    monkeypatch.setitem(sys.modules, 'sheets_factory.evaluation.resource_observer', SimpleNamespace(validate_trial_observations=observe))
    resource.ResourcePublicationBackend.validate_control_observations(offline.backend, row, task, load_runtime_profile(PROFILE), {})
    assert len(calls) == 2
    assert all(Path(config['path']).name == 'config.json' and Path(result['path']).name == 'result.json'
               and args['expected_profile']['image']['id'] == resource.IMMUTABLE_IMAGE for config, result, args in calls)
    monkeypatch.setitem(sys.modules, 'sheets_factory.evaluation.resource_observer', SimpleNamespace(
        validate_trial_observations=lambda *args, **kwargs: {'passed': True, 'complete': False}))
    with pytest.raises(resource.ResourcePublicationError, match='coverage is incomplete'):
        resource.ResourcePublicationBackend.validate_control_observations(offline.backend, row, task, load_runtime_profile(PROFILE), {})


def fake_freeze_environment(offline, monkeypatch):
    """Wire only the normal quality/kernel boundary; actual byte gates remain."""
    monkeypatch.setattr(cli, 'ResourcePublicationBackend', lambda **kwargs: offline.backend)
    for relative in resource.RECIPE_FILES:
        target = offline.root / relative; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    return [{'task_id': row['task_id'], 'family': row['family'], 'source_run': row['source_run']}
            for row in reversed(offline.rows)]


def test_freeze_full_declaration_before_confirmation_retains_mapping_order_and_seventeen_files(offline, monkeypatch):
    sources = fake_freeze_environment(offline, monkeypatch)
    # The fake previous confirmation is removed only inside this disposable
    # fixture. Production code has no history removal or reward filtering path.
    shutil.rmtree(offline.selection.parent)
    output = offline.root / 'outputs/fresh-before-confirmation'
    ref = cli.freeze_cohort(sources, output, project_root=offline.root)
    frozen = resource.checked(ref)
    assert frozen['selected_task_ids'] == [row['task_id'] for row in sources]
    assert frozen['selection_uses_confirmation_outcomes'] is False
    assert frozen['original_checkout_and_external_evidence_required'] is True
    for row in frozen['tasks']:
        assert row['source_run'] in {item['source_run'] for item in sources}
        target = Path(row['task_directory'])
        assert inspect_resource_export(target) == row['harbor_export_binding']
        assert len([path for path in target.rglob('*') if path.is_file()]) == 17
    with pytest.raises(resource.ResourcePublicationError, match='fresh real cohort'):
        cli.freeze_cohort(sources, output, project_root=offline.root)


def test_previous_confirmation_is_never_filtered_by_reward_during_freeze(offline, monkeypatch):
    sources = fake_freeze_environment(offline, monkeypatch)
    output = offline.root / 'outputs/disallowed-reconfirmation'
    with pytest.raises(resource.ResourcePublicationError, match='already belongs to a confirmation'):
        cli.freeze_cohort(sources, output, project_root=offline.root)
    assert not output.exists()


def test_supplemental_same_export_resource_controls_do_not_overwrite_canonical_job(offline, monkeypatch, tmp_path):
    row = deepcopy(offline.rows[1]); task = offline.audits[1].snapshot()['tasks'][0]
    session = tmp_path / 'mock-observer.json'; write_json(session, {'offline_fixture_not_enforcement': True})
    supplemental = {}
    originals = {}
    for agent in ('oracle', 'nop'):
        canonical = Path(task['harbor_controls'][agent]['result_file']); originals[canonical] = canonical.read_bytes()
        result = json.loads(canonical.read_text()); result['trial_name'] = 'offline_new_' + agent
        result_path = tmp_path / ('supplemental-' + agent) / 'result.json'
        write_json(result_path, result); config_path = result_path.with_name('config.json')
        write_json(config_path, result['config'])
        supplemental[agent] = {'result': resource.reference(result_path), 'config': resource.reference(config_path),
                               'observation_receipts': [resource.reference(session)]}
    row['supplemental_resource_controls'] = supplemental
    monkeypatch.setitem(sys.modules, 'sheets_factory.evaluation.resource_observer', SimpleNamespace(
        validate_trial_observations=lambda *args, **kwargs: {'passed': True, 'complete': True}))
    result = resource.ResourcePublicationBackend.validate_control_observations(
        offline.backend, row, task, load_runtime_profile(PROFILE), {})
    assert all(item['evidence_source'] == 'explicit_additional_same_export_control'
               and item['canonical_job_or_reward_overwritten'] is False
               and item['resource_evidenced_result']['path'] != item['canonical_quality_result']['path'] for item in result)
    assert all(path.read_bytes() == raw for path, raw in originals.items())
    wrong = json.loads(Path(supplemental['oracle']['result']['path']).read_text())
    wrong['task_checksum'] = '0' * 64
    write_json(Path(supplemental['oracle']['result']['path']), wrong)
    supplemental['oracle']['result'] = resource.reference(supplemental['oracle']['result']['path'])
    with pytest.raises(resource.ResourcePublicationError, match='another exact export'):
        resource.ResourcePublicationBackend.validate_control_observations(
            offline.backend, row, task, load_runtime_profile(PROFILE), {})


def test_new_unmanifested_file_during_staging_aborts_resource_publication(offline, monkeypatch):
    original = publish.release._copy_payload
    changed = False
    def copy_then_add(*args, **kwargs):
        nonlocal changed
        original(*args, **kwargs)
        if not changed:
            Path(offline.entries[0]['task_directory']).joinpath('unmanifested-private.txt').write_text('offline fixture')
            changed = True
    monkeypatch.setattr(publish.release, '_copy_payload', copy_then_add)
    with pytest.raises(resource.ResourcePublicationError, match='inventory changed'):
        invoke_resource(offline)
    assert not (offline.root / 'SpreadsheetEval').exists()


def test_reference_dedup_is_local_to_one_proof_and_never_trusts_metadata_for_later_calls(offline, monkeypatch, tmp_path):
    path = tmp_path / 'full-artifact'; path.write_bytes(b'original bytes')
    ref = resource.reference(path); table = {}; original = resource.reference; calls = []
    def count(value):
        calls.append(str(value)); return original(value)
    monkeypatch.setattr(resource, 'reference', count)
    offline.backend._bind([ref, ref], table)
    assert calls == [str(path)]
    offline.backend._bind(ref, table)
    assert calls == [str(path), str(path)]
    path.write_bytes(b'changed! bytes')
    with pytest.raises(resource.ResourcePublicationError, match='artifact changed'):
        offline.backend._bind(ref, table)
    assert len(calls) == 3 and table[str(path)] == ref['sha256']


def test_recipe_reference_cannot_disguise_other_bytes_as_current_implementation(offline, tmp_path):
    value = deepcopy(offline.backend.cohort)
    path = tmp_path / 'different_observer.py'; path.write_text('# explicit offline invalid fixture')
    value['publication_recipe']['src/sheets_factory/evaluation/resource_observer.py'] = resource.reference(path)
    write_json(offline.source, value)
    with pytest.raises(resource.ResourcePublicationError, match='actually loaded checkout'):
        resource.ResourcePublicationBackend(offline.source, project_root=ROOT)


def test_old_infrastructure_resource_gap_is_an_explicit_hold_not_a_reward_change(offline, monkeypatch):
    selected = json.loads(offline.selection.read_text()); evaluation = json.loads(offline.evaluation.read_text())
    original = deepcopy(evaluation); old_result = str(offline.root / 'old-infra/result.json')
    evaluation['infra_history'] = [{'result_file': old_result, 'status': 'infrastructure_error', 'reward': None}]
    observer = {'passed': False, 'complete': False, 'trials': [
        {'passed': False, 'complete': False, 'result': {'path': old_result}, 'problems': ['Missing verifier']} ]}
    monkeypatch.setitem(sys.modules, 'sheets_factory.evaluation.resource_observer', SimpleNamespace(
        validate_observation_receipt=lambda *args: observer))
    with pytest.raises(resource.ResourcePublicationError, match='missing_old_infrastructure_resource_evidence'):
        offline.backend.validate_confirmation_source(offline.selection, selected, evaluation, {})
    assert evaluation['attempts'] == original['attempts'] and evaluation['score'] == original['score']
