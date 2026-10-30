"""Offline resource routing and evidence only; no Docker, LO or model calls."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sheets_factory.workbook import resource_engine as resource
from sheets_factory.workbook.engine import LibreOfficeEngine, WorkbookEngineError


class DockerStub:
    def __init__(self, profile):
        self.profile = profile
        self.events = []
        self.container_id = 'a' * 64
        self.actual = {'NanoCpus': 2 * 10**9, 'Memory': 8 * 1024**3, 'PidsLimit': 256}
        self.image = profile['image']['id']
        self.create_fails = self.start_fails = False

    def run(self, command, timeout):
        self.events.append((list(command), timeout))
        if command[:3] == ['docker', 'image', 'inspect']:
            return self.image + '\n'
        if command[:2] == ['docker', 'create']:
            if self.create_fails:
                raise WorkbookEngineError('Deliberate offline create failure')
            return self.container_id
        if command[:2] == ['docker', 'inspect']:
            if command[-1] == '{{.State.ExitCode}}':
                return '0\n'
            return self.container_id + '\n' + json.dumps(self.actual)
        if command[:2] == ['docker', 'start']:
            if self.start_fails:
                raise WorkbookEngineError('Deliberate offline calculation timeout')
            return 'completed'
        if command[:2] == ['docker', 'cp']:
            if command[2].endswith(':/tmp/result.xlsx'):
                Path(command[3]).write_bytes(b'PK' + b'x' * 200)
            return ''
        raise AssertionError('Unexpected command ' + str(command))

    def cleanup(self, command, **kwargs):
        assert command[:3] == ['docker', 'rm', '--force']
        self.events.append((list(command), kwargs['timeout']))
        return SimpleNamespace(returncode=0, stdout='', stderr='')


@pytest.fixture
def setup(tmp_path, monkeypatch):
    profile = resource.load_runtime_profile()
    stub = DockerStub(profile)
    monkeypatch.setattr(resource.shutil, 'which', lambda name: '/usr/bin/docker' if name == 'docker' else None)
    monkeypatch.setattr(LibreOfficeEngine, '_run', staticmethod(stub.run))
    monkeypatch.setattr(resource.original_engine.subprocess, 'run', stub.cleanup)
    source = tmp_path / 'input.xlsx'
    source.write_bytes(b'PK' + b'i' * 200)
    engine = resource.ResourceLibreOfficeEngine(tmp_path, profile, receipt_directory=tmp_path / 'receipts')
    return engine, stub, source, tmp_path


def test_profile_has_explicit_equal_resources_and_independent_budgets():
    p = resource.load_runtime_profile()
    assert all(p['docker_resources'][role] == {'cpus': 2, 'memory_bytes': 8589934592, 'pids_limit': 256} for role in resource.ROLES)
    assert p['timeouts'] == {'workbook_file_seconds': 600, 'verifier_total_seconds': 2400}
    assert p['solver_tool_budget'] == {'seconds': 1800, 'strict_less_than': True,
        'exclude_model_response_time': True, 'parallel_executions': 'sum'}
    assert resource.docker_resource_flags(p, 'verifier') == ['--memory', '8589934592', '--cpus', '2', '--pids-limit', '256']
    assert p['limits'] == {'source_physical_formulas': 2000000, 'max_profile_cells': 3000000,
        'max_dependency_closure_cells': 3000000, 'full_target_cells': 2000000, 'truncate': False}


@pytest.mark.parametrize('mutate', [
    lambda p: p.update(version=True),
    lambda p: p['docker_resources']['agent'].update(memory_bytes='8g'),
    lambda p: p['docker_resources']['source'].update(memory_bytes=2 * 1024**3),
    lambda p: p['docker_resources']['verifier'].update(cpus=True),
    lambda p: p['docker_resources']['source'].update(pids_limit=0),
    lambda p: p['timeouts'].update(workbook_file_seconds=120),
    lambda p: p['solver_tool_budget'].update(seconds=2400),
    lambda p: p['solver_tool_budget'].update(strict_less_than=False),
    lambda p: p['limits'].update(truncate=True),
    lambda p: p['limits'].update(full_target_cells=3000000),
    lambda p: p['image'].update(id='latest'),
])
def test_malformed_or_implicit_resource_profiles_reject(mutate):
    p = resource.load_runtime_profile()
    mutate(p)
    with pytest.raises(ValueError):
        resource.load_runtime_profile(p)


def test_full_workload_caps_fail_instead_of_truncate():
    p = resource.load_runtime_profile()
    counts = {k: p['limits'][k] for k in resource.LIMIT_KEYS}
    assert resource.validate_workload_counts(p, counts)['truncation_allowed'] is False
    counts['source_physical_formulas'] += 1
    with pytest.raises(ValueError, match='do not truncate'):
        resource.validate_workload_counts(p, counts)
    with pytest.raises(ValueError, match='All four'):
        resource.validate_workload_counts(p, {'source_physical_formulas': 1273134})


def test_actual_create_is_parameterized_inspected_before_start_and_receipted(setup):
    engine, stub, source, directory = setup
    result = engine.normalize(source, directory / 'output.xlsx')
    assert result.is_file()
    create = next(c for c, _ in stub.events if c[:2] == ['docker', 'create'])
    assert create[create.index('--memory') + 1] == '8589934592'
    assert create[create.index('--cpus') + 1] == '2' and create[create.index('--pids-limit') + 1] == '256'
    assert create[create.index('--network') + 1] == 'none'
    assert create[create.index('--cap-drop') + 1] == 'ALL'
    assert create[create.index('--security-opt') + 1] == 'no-new-privileges'
    host_index = next(i for i, (c, _) in enumerate(stub.events) if c[:2] == ['docker', 'inspect'] and 'HostConfig' in c[-1])
    start_index = next(i for i, (c, _) in enumerate(stub.events) if c[:2] == ['docker', 'start'])
    assert host_index < start_index and stub.events[start_index][1] == 600
    assert stub.events[-1][0][:3] == ['docker', 'rm', '--force']
    records = list((directory / 'receipts').glob('*.terminal.json'))
    assert len(records) == 1
    receipt = json.loads(records[0].read_text())
    assert receipt['status'] == 'completed' and receipt['actual_resources_verified'] is True
    assert receipt['actual_resources'] == {'cpus_nanoseconds': 2 * 10**9, 'memory_bytes': 8589934592, 'pids_limit': 256}
    assert receipt['container_id'] == 'a' * 64 and receipt['upstream_engine']['sha256'] == resource.UPSTREAM_SHA256
    assert receipt['output']['path'] == str(result) and receipt['solver_tool_budget']['seconds'] == 1800
    assert not list(directory.glob('*.tmp'))


@pytest.mark.parametrize('field,wrong', [('NanoCpus', 0), ('Memory', 2 * 1024**3), ('PidsLimit', None)])
def test_actual_resource_mismatch_never_starts_and_failure_is_preserved(setup, field, wrong):
    engine, stub, source, directory = setup
    stub.actual[field] = wrong
    with pytest.raises(WorkbookEngineError, match='Actual Docker resources'):
        engine.recalculate(source, directory / 'output.xlsx')
    assert not any(c[:2] == ['docker', 'start'] for c, _ in stub.events)
    assert any(c[:3] == ['docker', 'rm', '--force'] for c, _ in stub.events)
    receipt = json.loads(next((directory / 'receipts').glob('*.terminal.json')).read_text())
    assert receipt['status'] == 'failed' and receipt['actual_resources_verified'] is False
    assert not (directory / 'output.xlsx').exists()


@pytest.mark.parametrize('phase', ['create', 'start'])
def test_failures_keep_append_only_attempts_and_delegate_cleanup(setup, phase):
    engine, stub, source, directory = setup
    setattr(stub, phase + '_fails', True)
    with pytest.raises(WorkbookEngineError):
        engine.recalculate(source, directory / 'failed.xlsx')
    original = next((directory / 'receipts').glob('*.terminal.json'))
    frozen = original.read_bytes()
    setattr(stub, phase + '_fails', False)
    engine.recalculate(source, directory / 'new_attempt.xlsx')
    assert original.read_bytes() == frozen
    assert len(list((directory / 'receipts').glob('*.terminal.json'))) == 2
    assert len(list((directory / 'receipts').glob('*.started.json'))) == 2
    assert getattr(engine._local, 'record', None) is None


def test_missing_or_wrong_image_never_builds_or_falls_back(setup):
    engine, stub, source, directory = setup
    stub.image = 'sha256:' + 'b' * 64
    with pytest.raises(WorkbookEngineError, match='no fallback'):
        engine.recalculate(source, directory / 'output.xlsx')
    assert not any(c[:2] in (['docker', 'build'], ['docker', 'create']) for c, _ in stub.events)
    assert json.loads(next((directory / 'receipts').glob('*.terminal.json')).read_text())['actual_resources_verified'] is False


def test_metadata_does_not_launch_an_unbounded_version_container(setup):
    engine, stub, _, _ = setup
    metadata = engine.metadata()
    assert metadata['actual_calculation_calls_recorded'] == 0
    assert metadata['actual_resource_receipts'] == []
    assert metadata['version_probe_performed'] is False
    assert metadata['agent_and_other_roles_applied_by_this_engine'] is False
    assert all(c[:3] == ['docker', 'image', 'inspect'] for c, _ in stub.events)


def test_explicit_profile_timeout_cannot_silently_revert(setup):
    engine, stub, source, directory = setup
    engine.timeout_seconds = 120
    with pytest.raises(WorkbookEngineError, match='timeout differs'):
        engine.recalculate(source, directory / 'output.xlsx')
    assert stub.events == []


def test_receipt_symlink_escape_and_upstream_drift_reject(tmp_path, monkeypatch):
    profile = resource.load_runtime_profile()
    real = tmp_path / 'real'
    real.mkdir()
    (tmp_path / 'alias').symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match='real directory'):
        resource.ResourceLibreOfficeEngine(tmp_path, profile, receipt_directory=tmp_path / 'alias')
    monkeypatch.setattr(resource, 'UPSTREAM_SHA256', '0' * 64)
    with pytest.raises(ValueError, match='original engine changed'):
        resource.ResourceLibreOfficeEngine(tmp_path, profile, receipt_directory=tmp_path / 'receipts')
