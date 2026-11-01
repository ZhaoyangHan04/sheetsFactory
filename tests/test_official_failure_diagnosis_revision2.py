"""Transport-only fixtures: no container, model, evaluator or spreadsheet service."""
import builtins
from contextlib import redirect_stdout
import errno
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
m = load(ROOT / 'scripts/run_official_failure_diagnosis_revision2.py', 'diagnosis_v2_test_module')
oldtests = load(ROOT / 'tests/test_official_failure_diagnosis.py', 'diagnosis_v1_fixture_module')


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    result = oldtests.fixture.__wrapped__(tmp_path, monkeypatch)
    monkeypatch.setitem(m._N, 'REGISTRY', tmp_path / 'v2_registry')
    result['prior'] = result['save']('toy_prior_stop.json', {
        'kind': 'stopped_official_failure_diagnosis_access_failure_v1', 'version': 1,
        'semantic_reviews_completed': 0, 'original_scores_modified': False, 'parent_alive_observed': False})
    return result


def prep(fixture, name='v2', limit=1):
    out = fixture['root'] / name
    m.prepare(*fixture['refs'], out, prior_failure=fixture['prior'], dispatch_limit=limit, _toy=True)
    return out, m.validate_prepared(out)


def observed(expected):
    v = m.read(expected)
    return {k: v[k] for k in ('nonce', 'sha256', 'input_sha256')} | {
        'denied': {k: {'written': False, 'errno': errno.EROFS} for k in ('workspace', 'input', 'rootfs')},
        'allowed': {k: {'written': True, 'errno': None} for k in ('tmp', 'root')}}


def test_v2_namespace_keeps_frozen_v1_and_semantics(fixture):
    assert m.reference(m.FROZEN)['sha256'] == m.FROZEN_SHA
    assert m._N['VERSION'] == 2 and m._N['POLICY']['review_version'] == 2
    assert m._N['REGISTRY'] != oldtests.m.REGISTRY
    assert m._N['validate_review'].__code__.co_code == oldtests.m.validate_review.__code__.co_code
    assert m._N['_ready'].__code__.co_code == oldtests.m._ready.__code__.co_code
    assert m._N['_infra'].__code__.co_code == oldtests.m._infra.__code__.co_code
    assert m.transform.count == 1


def test_only_inner_mode_changes_container_stays_readonly(fixture):
    client = m.ResearchCodex(ROOT, fixture['root'], None, {'model': 'gpt-6-sol', 'reasoning_effort': 'high'})
    work = fixture['root'] / 'evidence'
    cmd = client._build_command(work, 'http://127.0.0.1/v1', True, 'tiny', model='gpt-6-sol', reasoning='high')
    assert '--sandbox' not in cmd and cmd.count('--dangerously-bypass-approvals-and-sandbox') == 1
    assert '--read-only' in cmd and str(work) + ':/workspace:ro' in cmd
    assert cmd[cmd.index('--cap-drop') + 1] == 'ALL'
    assert 'web_search="disabled"' in cmd and 'model_providers.factory.request_max_retries=0' in cmd
    assert 'model_providers.factory.stream_max_retries=0' in cmd
    assert not any('private-test-credential' in c for c in cmd)


def test_schema_exposes_existing_receipt_metadata_obligations(fixture):
    _, frozen = prep(fixture)
    row = frozen['cases'][0]; schema = m.output_schema(row)
    pattern = schema['properties']['causes']['items']['properties']['cause_id']['pattern']
    assert re.fullmatch(pattern, row['case_key'] + ':C01') and not re.fullmatch(pattern, 'EVIDENCE_ACCESS')
    assert schema['properties']['all_misses_accounted_for']['const'] is True
    infra = {**frozen['cases'][4], 'status': 'ready_infrastructure'}; schema = m.output_schema(infra)
    fields = schema['properties']['causes']['items']['properties']
    assert fields['classification']['enum'] == ['infrastructure'] and fields['miss_count']['const'] == 0
    assert schema['properties']['all_misses_accounted_for']['const'] is False


def test_prepare_first_fixed_ready_only_retains_all_cases_no_calls(fixture, monkeypatch):
    import dirhash
    def forbidden(*a, **k): raise AssertionError('No actual process/model during preparation')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    out, v = prep(fixture)
    assert len(v['cases']) == 6 and v['cases'][0]['status'] == 'ready'
    assert v['cases'][4]['status'] == 'deferred_by_frozen_dispatch_limit'
    assert v['cases'][1]['status'] == 'reused_manual_review'
    assert not m._N['REGISTRY'].exists()
    sidecar = m.read(out / 'revision2_provenance.json')
    assert sidecar['prior_stopped_diagnosis'] == fixture['prior'] and sidecar['dispatch_limit'] == 1
    assert sidecar['old_unknowns_not_promoted_to_causes'] and not sidecar['benchmark_solution_repeated']
    assert m.reference(m.FROZEN)['sha256'] == m.FROZEN_SHA


def test_batch_limit_is_frozen_before_dispatch(fixture):
    _, v = prep(fixture, limit=200)
    assert sum(r['status'].startswith('ready') for r in v['cases']) == 2
    with pytest.raises(ValueError): prep(fixture, 'invalid0', 0)
    with pytest.raises(ValueError): prep(fixture, 'invalid_bool', True)


def test_provenance_or_old_failure_change_rejected(fixture):
    out, _ = prep(fixture)
    Path(fixture['prior']['path']).write_text('{}')
    with pytest.raises(ValueError, match='Changed or missing'): m.validate_prepared(out)


def test_v1_or_unbound_sidecar_cannot_be_admitted(fixture):
    out = fixture['root'] / 'original_v1'
    oldtests.m.prepare(*fixture['refs'], out, _toy=True)
    with pytest.raises(ValueError, match='Wrong diagnosis protocol'): m.validate_prepared(out)
    out, _ = prep(fixture)
    (out / 'revision2_provenance.json').unlink()
    with pytest.raises(FileNotFoundError): m.validate_prepared(out)


def test_toy_cannot_start_container_or_provider(fixture, monkeypatch):
    out, _ = prep(fixture)
    def forbidden(*a, **k): raise AssertionError('Toy must not reach runtime')
    monkeypatch.setattr(m, 'container_access_probe', forbidden)
    with pytest.raises(ValueError, match='Toy preparation'): m.execute_prepared(out)


def test_probe_program_really_reads_nonce_and_tests_all_paths(tmp_path):
    work, expected = m.prepare_access_probe(tmp_path / 'probe')
    realpath = Path; attempts = []
    class VirtualPath:
        def __init__(self, path): self.logical = str(path)
        def physical(self):
            if self.logical.startswith('/workspace/'): return work / self.logical.removeprefix('/workspace/')
            return tmp_path / self.logical.lstrip('/')
        def read_bytes(self): return self.physical().read_bytes()
        def write_bytes(self, data):
            attempts.append(self.logical)
            if self.logical.startswith('/workspace/') or self.logical == '/diagnosis_rootfs_probe':
                raise OSError(errno.EROFS, 'read-only permission test')
            p = self.physical(); p.parent.mkdir(parents=True, exist_ok=True); return p.write_bytes(data)
    realimport = builtins.__import__
    def imports(name, *args, **kwargs):
        return SimpleNamespace(Path=VirtualPath) if name == 'pathlib' else realimport(name, *args, **kwargs)
    stream = io.StringIO()
    with redirect_stdout(stream): exec(m.PROBE_PROGRAM, {'__builtins__': {**vars(builtins), '__import__': imports}})
    result = json.loads(stream.getvalue())
    assert m.verify_probe(expected, result) == result
    assert attempts == ['/workspace/blocked', '/workspace/input.xlsx', '/diagnosis_rootfs_probe', '/tmp/diagnosis_probe', '/root/diagnosis_probe']
    assert (tmp_path / 'tmp/diagnosis_probe').read_bytes() == b'controlled permission probe'
    assert m.read(expected)['nonce'] not in m.PROBE_PROGRAM


@pytest.mark.parametrize('change', ['wrong_nonce', 'workspace_writable', 'rootfs_writable', 'tmp_denied', 'input_changed'])
def test_probe_rejects_read_or_permission_gaps(tmp_path, change):
    work, expected = m.prepare_access_probe(tmp_path / 'probe'); v = observed(expected)
    if change == 'wrong_nonce': v['nonce'] = 'not the nonce'
    if change == 'workspace_writable': v['denied']['workspace'] = {'written': True, 'errno': None}
    if change == 'rootfs_writable': v['denied']['rootfs'] = {'written': True, 'errno': None}
    if change == 'tmp_denied': v['allowed']['tmp'] = {'written': False, 'errno': errno.EACCES}
    if change == 'input_changed': (work / 'input.xlsx').write_bytes(b'changed')
    with pytest.raises(ValueError): m.verify_probe(expected, v)


def test_zero_api_probe_command_receipt_and_exact_result(tmp_path, monkeypatch):
    calls = []
    def fake(command, **kwargs):
        calls.append(command)
        mount = command[command.index('--volume') + 1]; work = Path(mount.removesuffix(':/workspace:ro'))
        expected = m.reference(work.parent / 'expected.private.json')
        assert '--network' in command and command[command.index('--network')+1] == 'none'
        assert '--env' not in command and '--read-only' in command
        return subprocess.CompletedProcess(command, 0, json.dumps(observed(expected)), '')
    monkeypatch.setattr(subprocess, 'run', fake)
    receipt = m.container_access_probe(tmp_path / 'mock_probe')
    assert m.validate_access_probe(receipt)['actual_API_calls'] == 0 and len(calls) == 1


def test_failed_zero_api_probe_blocks_provider_dispatch(fixture, monkeypatch):
    out, _ = prep(fixture)
    sidecar = m.read(out / 'revision2_provenance.json'); sidecar['prototype_toy_only'] = False
    # Invocation boundary is mocked; this does not assert genuine provider admission.
    monkeypatch.setattr(m, 'validate_prepared', lambda out: {})
    original_read = m.read
    monkeypatch.setattr(m, 'read', lambda path: sidecar if str(path).endswith('revision2_provenance.json') else original_read(path))
    called = []
    def failed(*args): called.append('zero_API'); raise ValueError('permission smoke rejected')
    monkeypatch.setattr(m, 'container_access_probe', failed)
    monkeypatch.setattr(m, '_execute', lambda *args: called.append('PROVIDER'))
    with pytest.raises(ValueError, match='permission smoke'): m.execute_prepared(out)
    assert called == ['zero_API'] and not m._N['REGISTRY'].exists()


def test_cli_has_no_implicit_prepare_and_run(tmp_path):
    result = subprocess.run([m.sys.executable, str(ROOT / 'scripts/run_official_failure_diagnosis_revision2.py'), '--run'], capture_output=True, text=True)
    assert result.returncode != 0 and 'Prepare first' in result.stderr
