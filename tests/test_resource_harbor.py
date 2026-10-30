"""Offline export, standalone packaging and real timeout wiring; no Docker/LO."""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import signal
import subprocess
import sys
import tomllib

from openpyxl import Workbook, load_workbook
import pytest

from sheets_factory.evaluation import harbor
from sheets_factory.evaluation import resource_harbor as export
from sheets_factory.evaluation import resource_streaming_verifier as runner
from sheets_factory.workbook.resource_engine import load_runtime_profile


def _book(path, target):
    book = Workbook()
    book.active.title = 'Model'
    book.active['A1'] = 'Provided contract'
    book.active['B2'] = target
    hidden = book.create_sheet('Hidden')
    hidden.sheet_state = 'hidden'
    hidden['A1'] = 100
    book.save(path)
    book.close()


@pytest.fixture
def task(tmp_path):
    task = tmp_path / 'revision'
    (task / 'public').mkdir(parents=True)
    (task / 'private').mkdir()
    _book(task / 'public/input.xlsx', 10)
    _book(task / 'private/goal.xlsx', 20)
    (task / 'public/instruction.md').write_text('Restore the financial formulas. Preserve existing structure.')
    (task / 'private/do-not-export.txt').write_text('private construction evidence')
    return task


@pytest.fixture
def exported(task, tmp_path):
    return export.export_resource_harbor(task, tmp_path / 'export', {
        'task_id': 'entity-G01', 'mode': 'debugging', 'revision': 0,
        'revision_hash': 'a' * 64, 'difficulty_status': 'pending'})


def _rewrite_manifest(path):
    manifest = json.loads((path / 'export_manifest.json').read_text())
    manifest['files'] = {str(file.relative_to(path)): hashlib.sha256(file.read_bytes()).hexdigest()
                         for file in path.rglob('*') if file.is_file() and file.name != 'export_manifest.json'}
    (path / 'export_manifest.json').write_text(json.dumps(manifest))


def test_explicit_capacity_profile_is_consistent_in_agent_and_verifier(task, tmp_path):
    from sheets_factory.workbook.resource_engine import DEFAULT_PROFILE
    profile = DEFAULT_PROFILE.with_name('entity_group_large_v2.yaml')
    path = export.export_resource_harbor(task, tmp_path / 'capacity_export', runtime_profile=profile)
    binding = export.inspect_resource_export(path)
    config = tomllib.loads((path / 'task.toml').read_text())
    assert config['environment']['memory_mb'] == 32768
    assert config['verifier']['environment']['memory_mb'] == 32768
    assert config['agent']['timeout_sec'] == 14400 and config['verifier']['timeout_sec'] == 2400
    assert binding['resource_runtime']['actual_container_resources_verified'] is False
    for relative in ('environment/runtime_profile.json', 'tests/runtime_profile.json'):
        actual = runner.load_profile(path / relative)
        assert actual == load_runtime_profile(profile)
        assert actual['solver_tool_budget']['seconds'] == 1800


@pytest.mark.parametrize('actual,code', ((None, 1), ('sha256:' + '0' * 64, 0), ('expected', 0)))
def test_actual_local_base_tag_identity_requires_success_and_exact_config_id(monkeypatch, actual, code):
    from types import SimpleNamespace
    profile = load_runtime_profile()
    commands = []
    def inspect(command, **kwargs):
        commands.append(command)
        assert kwargs['timeout'] == 30 and kwargs['capture_output'] is True
        value = profile['image']['id'] if actual == 'expected' else actual
        return SimpleNamespace(returncode=code, stdout=(value or '') + '\n', stderr='')
    monkeypatch.setattr(export.subprocess, 'run', inspect)
    if actual == 'expected':
        record = export.verify_local_base_image(profile)
        assert record['actual_local_image_verified'] is True
        assert record['actual_container_resources_verified'] is False
        assert record['actual_image_id'] == profile['image']['id']
    else:
        with pytest.raises(ValueError, match='exact approved image ID'):
            export.verify_local_base_image(profile)
    assert commands == [['docker', 'image', 'inspect', profile['image']['tag'], '--format', '{{.Id}}']]


def test_real_harbor_schema_exact_resources_and_original_control_binding(exported):
    from harbor.models.task.task import Task
    task = Task(exported)
    assert task.is_valid_dir(exported)
    config = tomllib.loads((exported / 'task.toml').read_text())
    assert config['agent']['timeout_sec'] == 14400
    assert config['verifier']['timeout_sec'] == 2400
    assert config['verifier']['environment_mode'] == 'separate'
    for role in (config['environment'], config['verifier']['environment']):
        assert role == {'cpus': 2, 'memory_mb': 8192, 'storage_mb': 2048, 'network_mode': 'no-network'}
    binding = export.inspect_resource_export(exported)
    original = harbor.inspect_export(exported)
    assert {key: binding[key] for key in original} == original
    assert binding['required_controls'] == ['oracle', 'nop']
    assert binding['revision'] == 0 and binding['revision_hash'] == 'a' * 64
    contract = binding[export.RESOURCE_FIELD]
    assert contract['actual_container_resources_verified'] is False
    assert contract['harbor_pid_limit_configured'] is False
    assert contract['quality_or_difficulty_certified'] is False
    assert contract['execution_budget'] == {'version': 1, 'elapsed_policy': 'operational_guard',
        'elapsed_guard_seconds': 14400, 'tool_budget_seconds': 1800}
    assert contract['operational_guard_is_model_failure'] is False
    assert contract['profile']['solver_tool_budget'] == {
        'seconds': 1800, 'strict_less_than': True, 'exclude_model_response_time': True, 'parallel_executions': 'sum'}


def test_agent_boundary_and_same_immutable_image_and_real_oracle(exported, task):
    environment = exported / 'environment'
    assert sorted(path.name for path in environment.iterdir()) == [
        'Dockerfile', 'input.xlsx', 'recalculate', 'resource_runner.py', 'runtime_profile.json']
    assert (environment / 'input.xlsx').read_bytes() == (task / 'public/input.xlsx').read_bytes()
    for relative in ('solution/reference.xlsx', 'tests/reference.xlsx'):
        assert (exported / relative).read_bytes() == (task / 'private/goal.xlsx').read_bytes()
    assert 'cp /solution/reference.xlsx /app/output.xlsx' in (exported / 'solution/solve.sh').read_text()
    assert not list(exported.rglob('do-not-export.txt'))
    image = load_runtime_profile()['image']['tag']
    for folder in ('environment', 'tests'):
        assert (exported / folder / 'Dockerfile').read_text().startswith('FROM ' + image + '\n')
    recalculate = (environment / 'recalculate').read_text()
    assert 'resource_runner.py recalculate "$@" --profile' in recalculate
    assert '--profile /tests/runtime_profile.json' in (exported / 'tests/test.sh').read_text()
    for relative in ('environment/recalculate', 'solution/solve.sh', 'tests/test.sh'):
        assert (exported / relative).stat().st_mode & 0o111 == 0o111


def test_fresh_only_and_symlink_escape_rejected(exported, task, tmp_path):
    frozen = (exported / 'export_manifest.json').read_bytes()
    with pytest.raises(ValueError, match='fresh'):
        export.export_resource_harbor(task, exported)
    assert (exported / 'export_manifest.json').read_bytes() == frozen
    alias = tmp_path / 'alias'
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        export.export_resource_harbor(task, alias / 'new')
    input_path = task / 'public/input.xlsx'
    outside = tmp_path / 'outside.xlsx'
    input_path.rename(outside)
    input_path.symlink_to(outside)
    with pytest.raises(ValueError, match='real files'):
        export.export_resource_harbor(task, tmp_path / 'second')


@pytest.mark.parametrize('mutation', ['cpu', 'verifier_timeout', 'image', 'core', 'wrapper', 'public_goal',
                                     'actual_claim', 'quality_claim', 'pid_claim'])
def test_semantic_inspection_rejects_even_rehashed_export(exported, mutation):
    if mutation in ('cpu', 'verifier_timeout'):
        path = exported / 'task.toml'
        text = path.read_text()
        text = text.replace('cpus = 2', 'cpus = 1') if mutation == 'cpu' else text.replace('2400.0', '600.0')
        path.write_text(text)
    elif mutation == 'image':
        path = exported / 'tests/Dockerfile'
        path.write_text(path.read_text().replace(load_runtime_profile()['image']['tag'], 'mutable:tag'))
    elif mutation in ('core', 'wrapper'):
        path = exported / 'tests' / ('streaming_core.py' if mutation == 'core' else 'verify.py')
        path.write_text('raise RuntimeError("different verifier")\n')
    elif mutation == 'public_goal':
        shutil.copy2(exported / 'tests/reference.xlsx', exported / 'environment/reference.xlsx')
    else:
        path = exported / 'export_manifest.json'
        manifest = json.loads(path.read_text())
        field = {'actual_claim': 'actual_container_resources_verified', 'quality_claim': 'quality_or_difficulty_certified',
                 'pid_claim': 'harbor_pid_limit_configured'}[mutation]
        manifest['metadata'][export.RESOURCE_FIELD][field] = True
        path.write_text(json.dumps(manifest))
    _rewrite_manifest(exported)
    with pytest.raises(ValueError):
        export.inspect_resource_export(exported)


def test_original_inventory_still_rejects_unrecorded_files(exported):
    (exported / 'extra.txt').write_text('unbound')
    with pytest.raises(ValueError, match='unrecorded'):
        export.inspect_resource_export(exported)


@pytest.mark.parametrize('kind', ['smaller_memory', 'relaxed_tools', 'profile_time', 'image', 'reserved_contract'])
def test_prepare_rejects_bad_operational_contract_without_output(task, tmp_path, kind):
    profile = load_runtime_profile()
    metadata = {}
    if kind == 'smaller_memory':
        profile['docker_resources']['agent']['memory_bytes'] = 2 * 1024**3
    elif kind == 'relaxed_tools':
        profile['solver_tool_budget']['seconds'] = 2400
    elif kind == 'profile_time':
        profile['timeouts']['workbook_file_seconds'] = 180
    elif kind == 'image':
        metadata['base_image'] = 'other:latest'
    else:
        metadata[export.RESOURCE_FIELD] = {}
    output = tmp_path / 'invalid'
    with pytest.raises(ValueError):
        export.export_resource_harbor(task, output, metadata, runtime_profile=profile)
    assert not output.exists()


def test_changed_upstream_is_fail_closed_before_export(task, tmp_path, monkeypatch):
    monkeypatch.setattr(export, 'UPSTREAM_HARBOR_SHA256', '0' * 64)
    with pytest.raises(ValueError, match='dependency changed'):
        export.export_resource_harbor(task, tmp_path / 'invalid')
    assert not (tmp_path / 'invalid').exists()


def _arguments(exported, output, tmp_path):
    return ['--input', str(exported / 'tests/original_input.xlsx'),
            '--goal', str(exported / 'tests/reference.xlsx'), '--output', str(output),
            '--profile', str(exported / 'tests/runtime_profile.json'),
            '--reward', str(tmp_path / 'reward.txt'), '--report', str(tmp_path / 'report.json')]


@pytest.mark.parametrize('change,expected', [('correct', 1), ('missed', 0), ('extra_hidden', 0)])
def test_exact_copied_wrapper_real_sparse_comparison_and_three_600_calls(exported, tmp_path, change, expected):
    namespace = runpy.run_path(str(exported / 'tests/verify.py'), run_name='copied_resource_verifier')
    main = namespace['main']
    output = tmp_path / 'output.xlsx'
    shutil.copy2(exported / ('tests/original_input.xlsx' if change == 'missed' else 'tests/reference.xlsx'), output)
    if change == 'extra_hidden':
        book = load_workbook(output)
        book['Hidden']['Z200'] = 3
        book.save(output)
        book.close()
    calls = []
    def no_lo(source, destination, timeout):
        calls.append((source, destination, timeout))
        shutil.copy2(source, destination)
    main.__globals__['recalculate'] = no_lo
    assert main(_arguments(exported, output, tmp_path)) == 0
    result = json.loads((tmp_path / 'report.json').read_text())
    assert result['reward'] == expected
    assert len(calls) == 3 and all(call[2] == 600 for call in calls)
    assert all(call['completed'] is True for call in result['recalculation_calls'])
    assert result['resource_contract']['actual_container_resources_verified'] is False
    assert (tmp_path / 'reward.txt').read_text() == str(expected) + '\n'
    assert all(not call[1].exists() for call in calls)
    export.inspect_resource_export(exported)  # no __pycache__ or other hidden mutation


def test_copied_script_executes_isolated_without_factory_imports_or_lo(exported, tmp_path):
    command = [sys.executable, '-I', str(exported / 'tests/verify.py'),
               *_arguments(exported, tmp_path / 'missing.xlsx', tmp_path)]
    completed = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr
    result = json.loads((tmp_path / 'report.json').read_text())
    assert result['reason'] == 'verification_error' and result['error_type'] == 'ValueError'
    assert result['recalculation_calls'] == []
    assert result['resource_contract']['workbook_file_timeout_seconds'] == 600


def test_failed_recalculation_keeps_actual_failed_call_and_cleans_temp(exported, tmp_path, monkeypatch):
    calls = []
    def fail(source, destination, timeout):
        calls.append(destination)
        raise subprocess.TimeoutExpired('UNO', timeout)
    monkeypatch.setattr(runner, 'recalculate', fail)
    output = exported / 'tests/reference.xlsx'
    assert runner.main(_arguments(exported, output, tmp_path)) == 0
    report = json.loads((tmp_path / 'report.json').read_text())
    assert report['reward'] == 0 and report['error_type'] == 'TimeoutExpired'
    assert len(report['recalculation_calls']) == 1
    assert report['recalculation_calls'][0]['completed'] is False
    assert report['recalculation_calls'][0]['timeout_seconds'] == 600
    assert not calls[0].parent.exists()


@pytest.mark.parametrize('failure', ['returncode', 'missing_destination', 'timeout'])
def test_real_recalculate_process_contract_and_failure_group_cleanup(tmp_path, monkeypatch, failure):
    calls, killed = [], []
    source, destination = tmp_path / 'source.xlsx', tmp_path / 'destination.xlsx'
    source.write_bytes(b'source')
    class Process:
        pid = 1234567
        returncode = 1 if failure == 'returncode' else 0
        communications = 0
        def communicate(self, timeout=None):
            self.communications += 1
            calls.append(timeout)
            if failure == 'timeout' and self.communications == 1:
                raise subprocess.TimeoutExpired('UNO', timeout)
            return 'ok', 'raw engine error'
    def spawn(command, **kwargs):
        assert command == ['/usr/bin/python3', '/opt/uno_recalculate.py', str(source), str(destination)]
        assert kwargs == {'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE,
                          'text': True, 'start_new_session': True}
        return Process()
    monkeypatch.setattr(runner.subprocess, 'Popen', spawn)
    monkeypatch.setattr(runner.os, 'killpg', lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(subprocess.TimeoutExpired if failure == 'timeout' else RuntimeError):
        runner.recalculate(source, destination, timeout=600)
    assert calls[0] == 600
    assert killed == ([(1234567, signal.SIGKILL)] if failure == 'timeout' else [])


def test_agent_positional_recalculate_uses_same_600_profile(exported, tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(runner, 'recalculate', lambda source, dest, timeout: called.append((source, dest, timeout)) or 'done\n')
    assert runner.main(['recalculate', str(tmp_path / 'i.xlsx'), str(tmp_path / 'o.xlsx'),
                        '--profile', str(exported / 'environment/runtime_profile.json')]) == 0
    assert called == [((tmp_path / 'i.xlsx').resolve(), (tmp_path / 'o.xlsx').resolve(), 600)]


def test_nondefault_file_timeout_is_rejected_without_process(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.subprocess, 'Popen', lambda *a, **kw: pytest.fail('No process may start'))
    with pytest.raises(ValueError, match='600'):
        runner.recalculate(tmp_path / 'in', tmp_path / 'out', timeout=180)
