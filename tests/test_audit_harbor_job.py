"""Offline audit fixtures only: these tests do not execute real Harbor jobs."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

from dirhash import dirhash
import pytest

from sheets_factory.core.audit import AuditStore
from sheets_factory.evaluation.harbor import inspect_export
from test_package_release import fixture_task, write_json


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/audit_harbor_job.py'
spec = importlib.util.spec_from_file_location('audit_harbor_job', SCRIPT)
audit_job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_job)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def offline(tmp_path):
    root = tmp_path / 'checkout'
    dataset, job = root / 'SpreadsheetEval', root / 'outputs/jobs/offline-oracle'
    run = root / 'outputs/runs/offline-source'
    store = AuditStore(run, {'id': 'offline-source', 'status': 'completed'})
    tasks, results = [], []
    for index, mode in enumerate(('financial_modeling', 'debugging')):
        task_id, _, source = fixture_task(run, store, mode,
            suffix='long-offline-id-more-than-thirty-two-characters-' + str(index), source='a' * 64)
        target = dataset / task_id
        shutil.copytree(source, target)
        binding = inspect_export(target)
        tasks.append({'task_id': task_id, 'mode': mode, 'revision': binding['revision'],
            'revision_hash': binding['revision_hash'], 'harbor_export_binding': binding,
            'payload_files': {p.relative_to(target).as_posix(): digest(p) for p in target.rglob('*') if p.is_file()}})
        trial_name = f'short-name-{index}__abcdefg'
        path = f'SpreadsheetEval/{task_id}'
        record = {'offline_fixture': True, 'task_name': binding['task_name'], 'trial_name': trial_name,
            'id': f'00000000-0000-0000-0000-00000000000{index+1}',
            'trial_uri': (job / trial_name).as_uri(),
            'task_id': {'path': path}, 'task_checksum': dirhash(target, 'sha256'),
            'finished_at': '2026-10-30T12:00:00Z',
            'config': {'trial_name': trial_name, 'task': {'path': path},
                'job_id': '00000000-0000-0000-0000-000000000009', 'trials_dir': str(job),
                'agent': {'name': 'oracle', 'model_name': None, 'import_path': None},
                'verifier': {'disable': False}, 'install_only': False},
            'agent_info': {'name': 'oracle', 'version': 'offline-fixture'},
            'verifier_result': {'rewards': {'reward': 1}}, 'exception_info': None}
        result_file = job / trial_name / 'result.json'
        write_json(result_file, record)
        results.append(result_file)
    manifest = {'schema_version': 1, 'dataset_name': 'SpreadsheetEval', 'task_count': 2,
        'selected_task_ids': [t['task_id'] for t in tasks], 'tasks': tasks,
        'counts_by_mode': {'financial_modeling': 1, 'debugging': 1}}
    write_json(dataset / 'dataset_manifest.json', manifest)
    write_json(job / 'result.json', {'offline_fixture': True, 'id': '00000000-0000-0000-0000-000000000009',
        'finished_at': '2026-10-30T12:00:01Z',
        'n_total_trials': 2, 'stats': {'n_completed_trials': 2, 'n_errored_trials': 0,
                                    'n_running_trials': 0, 'n_pending_trials': 0, 'n_retries': 0}})
    return {'root': root, 'dataset': dataset, 'job': job, 'results': results, 'tasks': tasks}


def invoke(fixture, **kwargs):
    return audit_job.audit_harbor_job(fixture['dataset'], fixture['job'],
        agent=kwargs.pop('agent', 'oracle'), command_cwd=kwargs.pop('command_cwd', fixture['root']), **kwargs)


def change(path, mutate):
    value = json.loads(path.read_text())
    mutate(value)
    write_json(path, value)


def test_relative_paths_accept_complete_oracle_and_receipt_has_full_hash_bindings(offline):
    output = offline['root'] / 'outputs/validation/oracle-audit.json'
    before = {p: digest(p) for directory in (offline['dataset'], offline['job']) for p in directory.rglob('*') if p.is_file()}
    report = invoke(offline, output=output)
    assert report['status'] == 'passed' and report['counts']['matched_rewards'] == 2
    assert report['dataset_manifest_sha256'] == digest(offline['dataset'] / 'dataset_manifest.json')
    assert len(report['tasks']) == len(report['trials']) == 2
    assert all(t['task_checksum'] == t['dirhash_sha256'] for t in report['tasks'])
    assert all(t['result_sha256'] == digest(Path(t['result_file'])) for t in report['trials'])
    assert json.loads(output.read_text()) == report
    assert all(digest(p) == value for p, value in before.items())


def test_nop_zero_and_semantically_equal_absolute_relative_paths_are_accepted(offline):
    for file in offline['results']:
        def mutate(x):
            x['config']['agent']['name'] = x['agent_info']['name'] = 'nop'
            x['verifier_result']['rewards']['reward'] = 0
            x['task_id']['path'] = str((offline['root'] / x['task_id']['path']).resolve())
        change(file, mutate)
    report = invoke(offline, agent='nop')
    assert report['expected_reward'] == 0 and report['counts']['matched_rewards'] == 2


def test_dataset_job_and_trial_paths_use_original_command_cwd_and_recorded_version(offline):
    for file in offline['results']:
        change(file, lambda x: x['config'].update(trials_dir='outputs/jobs/offline-oracle'))
    write_json(offline['job'] / 'lock.json', {'harbor': {'version': 'offline-fixture-version'}})
    report = audit_job.audit_harbor_job('SpreadsheetEval', 'outputs/jobs/offline-oracle',
        agent='oracle', command_cwd=offline['root'])
    assert report['recorded_job_harbor_version'] == 'offline-fixture-version'
    assert report['installed_harbor_version'] != 'offline-fixture-version'
    assert report['evidence_files'][str(offline['job'] / 'lock.json')] == digest(offline['job'] / 'lock.json')


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'unknown', 'unnamed', 'unfinished', 'extra_directory'])
def test_unique_complete_trial_set_is_required(offline, fault):
    file = offline['results'][0]
    if fault == 'missing':
        shutil.rmtree(file.parent)
    elif fault == 'duplicate':
        shutil.copytree(file.parent, offline['job'] / 'duplicate')
    elif fault == 'unknown':
        change(file, lambda x: x.update(task_name='sheetsfactory/unknown'))
    elif fault == 'unnamed':
        change(file, lambda x: x.pop('task_name'))
    elif fault == 'unfinished':
        change(file, lambda x: x.update(finished_at=None))
    else:
        (offline['job'] / 'incomplete-trial').mkdir()
    with pytest.raises(audit_job.AuditError):
        invoke(offline)


@pytest.mark.parametrize('fault', ['config_agent', 'agent_info', 'exception', 'step_exception',
    'wrong_reward', 'boolean_reward', 'string_reward', 'nan_reward', 'custom_agent',
    'disabled_verifier', 'install_only', 'task_name', 'task_id_path', 'config_path', 'checksum', 'trial_name',
    'job_id', 'trials_dir', 'trial_uri', 'duplicate_trial_id'])
def test_actual_agent_reward_identity_exception_and_payload_binding_are_required(offline, fault):
    def mutate(x):
        if fault == 'config_agent': x['config']['agent']['name'] = 'nop'
        elif fault == 'agent_info': x['agent_info']['name'] = 'nop'
        elif fault == 'exception': x['exception_info'] = {'exception_type': 'RuntimeError'}
        elif fault == 'step_exception': x['step_results'] = [{'exception_info': {'exception_type': 'RuntimeError'}}]
        elif fault == 'wrong_reward': x['verifier_result']['rewards']['reward'] = 0
        elif fault == 'boolean_reward': x['verifier_result']['rewards']['reward'] = True
        elif fault == 'string_reward': x['verifier_result']['rewards']['reward'] = '1'
        elif fault == 'nan_reward': x['verifier_result']['rewards']['reward'] = float('nan')
        elif fault == 'custom_agent': x['config']['agent']['import_path'] = 'other:Oracle'
        elif fault == 'disabled_verifier': x['config']['verifier']['disable'] = True
        elif fault == 'install_only': x['config']['install_only'] = True
        elif fault == 'task_name': x['task_name'] = 'fm-wrong-namespace'
        elif fault == 'task_id_path': x['task_id']['path'] = 'other-task'
        elif fault == 'config_path': x['config']['task']['path'] = 'other-task'
        elif fault == 'checksum': x['task_checksum'] = '0' * 64
        elif fault == 'trial_name': x['trial_name'] = 'wrong'
        elif fault == 'job_id': x['config']['job_id'] = 'different-historical-job'
        elif fault == 'trials_dir': x['config']['trials_dir'] = 'different-job'
        elif fault == 'trial_uri': x['trial_uri'] = 'file:///different-historical-job/trial'
        else: x['id'] = '00000000-0000-0000-0000-000000000002'
    change(offline['results'][0], mutate)
    with pytest.raises(audit_job.AuditError):
        invoke(offline)


@pytest.mark.parametrize('fault', ['mutated_file', 'extra_payload', 'ignore_filter', 'symlink',
    'missing_payload_hash', 'binding', 'revision', 'task_ids', 'count', 'mode_count', 'extra_dataset'])
def test_current_dataset_bytes_and_exact_manifest_task_set_are_required(offline, fault):
    task = offline['tasks'][0]
    directory = offline['dataset'] / task['task_id']
    if fault == 'mutated_file': (directory / 'instruction.md').write_text('changed')
    elif fault == 'extra_payload': (directory / 'unexpected.log').write_text('extra')
    elif fault == 'ignore_filter': (directory / '.harborignore').write_text('tests/')
    elif fault == 'symlink':
        path = directory / 'solution/reference.xlsx'
        path.unlink()
        path.symlink_to(directory / 'tests/reference.xlsx')
    elif fault == 'extra_dataset': (offline['dataset'] / 'unselected').mkdir()
    else:
        def mutate(x):
            if fault == 'missing_payload_hash': x['tasks'][0]['payload_files'].pop('instruction.md')
            elif fault == 'binding': x['tasks'][0]['harbor_export_binding']['export_manifest_sha256'] = '0' * 64
            elif fault == 'revision': x['tasks'][0]['revision'] = 100
            elif fault == 'task_ids': x['selected_task_ids'].append(x['selected_task_ids'][0])
            elif fault == 'count': x['task_count'] = 100
            else: x['counts_by_mode']['debugging'] = 99
        change(offline['dataset'] / 'dataset_manifest.json', mutate)
    with pytest.raises(audit_job.AuditError):
        invoke(offline)


def test_artifact_result_json_is_ignored_but_aggregate_summary_mismatch_rejected(offline):
    write_json(offline['results'][0].parent / 'agent/artifacts/result.json', {'task_name': 'arbitrary-agent-output'})
    assert invoke(offline)['status'] == 'passed'
    summaries = [json.loads(p.read_text()) for p in offline['results']]
    change(offline['job'] / 'result.json', lambda x: x.update(trial_results=summaries))
    assert invoke(offline)['status'] == 'passed'
    summaries[0]['task_checksum'] = '0' * 64
    change(offline['job'] / 'result.json', lambda x: x.update(trial_results=summaries))
    with pytest.raises(audit_job.AuditError, match='Aggregate trial summary differs'):
        invoke(offline)


@pytest.mark.parametrize('fault', ['unfinished', 'count', 'errors', 'retry'])
def test_full_job_aggregate_must_be_finished_without_hidden_extra_attempts(offline, fault):
    def mutate(x):
        if fault == 'unfinished': x['finished_at'] = None
        elif fault == 'count': x['n_total_trials'] = 1
        elif fault == 'errors': x['stats']['n_errored_trials'] = 1
        else: x['stats']['n_retries'] = 1
    change(offline['job'] / 'result.json', mutate)
    with pytest.raises(audit_job.AuditError):
        invoke(offline)


def test_command_cwd_is_explicit_and_output_refuses_overwrite_or_public_paths(offline):
    with pytest.raises(audit_job.AuditError, match='paths do not identify'):
        invoke(offline, command_cwd=offline['root'].parent)
    with pytest.raises(audit_job.AuditError, match='private outputs'):
        invoke(offline, output=offline['dataset'] / 'outputs/receipt.json')
    output = offline['root'] / 'outputs/validation/audit.json'
    invoke(offline, output=output)
    with pytest.raises(audit_job.AuditError, match='overwrite is refused'):
        invoke(offline, output=output)


def test_cli_failure_is_nonzero_and_stdout_never_leaks_private_paths(offline, capsys):
    arguments = ['--dataset', str(offline['dataset']), '--job', str(offline['job']),
                 '--agent', 'oracle', '--command-cwd', str(offline['root'])]
    assert audit_job.main(arguments) == 0
    output = capsys.readouterr()
    assert str(offline['root']) not in output.out and json.loads(output.out)['status'] == 'passed'
    change(offline['results'][0], lambda x: x.update(exception_info={'exception_type': 'ServiceError',
        'exception_message': '/private/path/credential-shaped-text'}))
    assert audit_job.main(arguments) != 0
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err)['status'] == 'failed'
    assert 'credential-shaped-text' not in output.err and str(offline['root']) not in output.err


@pytest.mark.parametrize('field', ['config', 'agent_info', 'verifier_result'])
def test_malformed_records_fail_cleanly_without_raw_traceback(offline, capsys, field):
    change(offline['results'][0], lambda x: x.update({field: ['malformed', '/private/path']}))
    code = audit_job.main(['--dataset', str(offline['dataset']), '--job', str(offline['job']),
                          '--agent', 'oracle', '--command-cwd', str(offline['root'])])
    output = capsys.readouterr()
    assert code != 0 and json.loads(output.err)['status'] == 'failed'
    assert 'Traceback' not in output.err and '/private/path' not in output.err
