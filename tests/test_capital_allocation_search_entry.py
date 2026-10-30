"""Real monitoring setup, with the computation child and final verifier stubbed.

No full enumeration, workbook engine or model is invoked by these entry tests.
"""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

import pytest

from test_capital_allocation_search import specification

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_capital_search_entry', ROOT / 'scripts/run_capital_allocation_search.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


@pytest.fixture
def prepared(tmp_path):
    source = tmp_path / 'spec.json'
    source.write_text(json.dumps(specification()))
    output = tmp_path / 'prepared'
    entry.prepare(source, output)
    return output


def child_stub(monkeypatch, *, code=0, before_start=None):
    """Start a real dedicated child that writes test-only partial artifacts."""
    actual = entry.subprocess.Popen
    invocations = []
    body = (
        'from pathlib import Path; import sys; '
        'p=Path(sys.argv[1]); p.mkdir(); '
        '(p/"all_plans.csv").write_text("mask,full_mask\\n0,0\\n"); '
        '(p/"certificate.json").write_text("{}"); '
        '(p/"cpp_enumeration.json").write_text("{}"); '
        'print("test child output"); print("test child stderr",file=sys.stderr); '
        'raise SystemExit(int(sys.argv[2]))'
    )
    def launch(command, **kwargs):
        if before_start:
            before_start(command, kwargs)
        invocations.append((command, kwargs))
        return actual([sys.executable, '-c', body, command[-1], str(code)], **kwargs)
    monkeypatch.setattr(entry.subprocess, 'Popen', launch)
    def verify(certificate, public):
        # The financial interpreter is covered by its separate exhaustive tests.
        # Here only its exact read-only invocation and monitor cleanup are tested.
        assert Path(certificate['path']).name == 'certificate.json'
        assert Path(public).name == 'public_spec.json'
        return {'verification': certificate, 'plans_csv': entry.reference(Path(certificate['path']).with_name('all_plans.csv')),
                'objective_pence': 40, 'best_plan': dict.fromkeys(entry.PROJECT_IDS, 0),
                'gap_pence': 1, 'plan_count': 2**18}
    monkeypatch.setattr(entry.search, 'validate_certificate', verify)
    return invocations


def run_state(output):
    with sqlite3.connect(output / 'run.sqlite') as db:
        return json.loads(db.execute("SELECT value FROM state WHERE key='run'").fetchone()[0])


def test_default_preparation_freezes_core_and_performs_zero_calls(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail('Preparation cannot start a child or enumeration')
    monkeypatch.setattr(entry.subprocess, 'Popen', forbidden)
    monkeypatch.setattr(entry.search, 'enumerate_capital_plans', forbidden)
    source = tmp_path / 'source.json'
    source.write_text(json.dumps(specification()))
    output = tmp_path / 'new'
    entry.main(['--spec', str(source), '--output', str(output)])
    frozen = entry.validate_prepared(output)
    assert json.loads(capsys.readouterr().out)['path'] == str(output / 'preparation.json')
    assert frozen['expected_plan_count'] == 262144
    assert frozen['expected_scenario_year_evaluations'] == 15728640
    assert frozen['search_child_processes_started'] == frozen['actual_enumerated_plans'] == 0
    assert len(frozen['recipe']) == 10
    assert str(entry.search.CPP) in frozen['recipe']
    assert str(entry.ROOT / 'tests/test_capital_allocation_search.py') in frozen['recipe']
    assert not (output / 'run.sqlite').exists() and not (output / 'attempts').exists()


def test_real_setup_dashboard_before_child_full_cli_once_and_cleanup(prepared, monkeypatch, capsys):
    old_env, old_cache = os.environ.get('TMPDIR'), tempfile.tempdir
    def before(command, kwargs):
        message = json.loads(capsys.readouterr().out)
        assert message['dashboard_url'].startswith('http://127.0.0.1:')
        assert message['models'] == message['tokens'] == message['LO_calls'] == 0
        assert (Path(message['search_attempt']) / 'attempt.json').is_file()
        assert command == [sys.executable, '-m', entry.MODULE, '--spec', str(prepared / 'public_spec.json'),
                           '--output', str(Path(message['search_attempt']) / 'enumeration')]
        assert '--active-projects' not in command
        assert kwargs['start_new_session'] is True
        assert kwargs['env']['TMPDIR'] == str(prepared / 'temporary')
        assert kwargs['env']['PYTHONPATH'] == str(ROOT / 'src')
        assert tempfile.gettempdir() == str(prepared / 'temporary')
    invoked = child_stub(monkeypatch, before_start=before)
    result = entry.execute_prepared(prepared)
    assert len(invoked) == 1
    receipt = json.loads(Path(result['path']).read_text())
    assert receipt['qualified'] is False and receipt['task_count'] == 0
    assert receipt['quality_or_difficulty_certified'] is False
    state = run_state(prepared)
    assert state['status'] == 'completed' and state['producer_active'] is False
    assert state['certified_complete'] is True
    attempt = next((prepared / 'attempts').iterdir())
    terminal = json.loads((attempt / 'terminal.json').read_text())
    assert terminal['search_child_returncode'] == 0 and terminal['status'] == 'completed'
    assert Path(terminal['stderr']['path']).read_text().strip() == 'test child stderr'
    assert Path(terminal['stdout']['path']).read_text().strip() == 'test child output'
    assert json.loads((prepared / 'summary.json').read_text())['metrics']['llm_calls'] == 0
    assert os.environ.get('TMPDIR') == old_env and tempfile.tempdir == old_cache
    entry.ProducerLease(prepared).acquire().release()
    with pytest.raises(ValueError, match='never repeat'):
        entry.execute_prepared(prepared)
    assert len(invoked) == 1


def test_failed_child_keeps_logs_partial_csv_and_terminal_without_retry(prepared, monkeypatch):
    invoked = child_stub(monkeypatch, code=7)
    with pytest.raises(ValueError, match='status 7'):
        entry.execute_prepared(prepared)
    assert len(invoked) == 1
    attempt = next((prepared / 'attempts').iterdir())
    terminal = json.loads((attempt / 'terminal.json').read_text())
    assert terminal['status'] == 'failed' and terminal['search_child_returncode'] == 7
    assert terminal['partial_artifacts_preserved'] is True
    assert (attempt / 'enumeration/all_plans.csv').is_file()
    assert not (prepared / 'search_result.json').exists()
    assert run_state(prepared)['certified_complete'] is False
    entry.ProducerLease(prepared).acquire().release()


def test_final_certificate_failure_is_preserved_without_completion_claim(prepared, monkeypatch):
    child_stub(monkeypatch)
    def reject(*args, **kwargs):
        raise ValueError('Test-only unique optimum failure')
    monkeypatch.setattr(entry.search, 'validate_certificate', reject)
    with pytest.raises(ValueError, match='unique optimum'):
        entry.execute_prepared(prepared)
    assert run_state(prepared)['status'] == 'failed'
    attempt = next((prepared / 'attempts').iterdir())
    terminal = json.loads((attempt / 'terminal.json').read_text())
    assert terminal['search_child_returncode'] == 0 and terminal['result'] is None
    assert (attempt / 'enumeration/certificate.json').is_file()


@pytest.mark.parametrize('failure', ['audit_export', 'server_stop'])
def test_cleanup_releases_lease_db_and_host_temp_on_monitor_error(prepared, monkeypatch, failure):
    child_stub(monkeypatch)
    old_env, old_cache = os.environ.get('TMPDIR'), tempfile.tempdir
    if failure == 'audit_export':
        monkeypatch.setattr(entry.AuditStore, 'export', lambda self: (_ for _ in ()).throw(RuntimeError('test export failure')))
    else:
        actual = entry.DashboardServer.stop
        def stop(server):
            actual(server)
            raise RuntimeError('test stop failure')
        monkeypatch.setattr(entry.DashboardServer, 'stop', stop)
    with pytest.raises(RuntimeError):
        entry.execute_prepared(prepared)
    assert os.environ.get('TMPDIR') == old_env and tempfile.tempdir == old_cache
    assert run_state(prepared)['producer_active'] is False
    entry.ProducerLease(prepared).acquire().release()
    assert next((prepared / 'attempts').glob('*/terminal.json')).is_file()


def test_observation_counts_only_completed_newlines_and_never_certifies(tmp_path):
    path = tmp_path / 'plans.csv'
    observer = entry.ObservedCSV(path)
    assert observer.observe() == {'observed_complete_rows': 0, 'observed_bytes': 0}
    path.write_bytes(b'header\n0,')
    assert observer.observe()['observed_complete_rows'] == 0
    with path.open('ab') as stream:
        stream.write(b'0\n1,1\n2,')
    assert observer.observe()['observed_complete_rows'] == 2
    assert observer.observe()['observed_complete_rows'] == 2
    progress = entry._progress(tmp_path, observer, entry.ObservedCSV(tmp_path / 'missing.csv'), entry.time.monotonic())
    assert progress['certified_complete'] is False
    assert progress['row_counts_are_observations_only'] is True
    path.write_bytes(b'')
    with pytest.raises(ValueError, match='truncated'):
        observer.observe()


@pytest.mark.parametrize('fault', ['spec', 'recipe', 'toy', 'fake_calls'])
def test_prepared_changes_fail_before_child_launch(prepared, monkeypatch, fault):
    path = prepared / 'preparation.json'
    frozen = json.loads(path.read_text())
    if fault == 'spec':
        public = Path(frozen['specification']['path'])
        changed = json.loads(public.read_text())
        changed['opening_cash_pence'] += 1
        public.write_text(json.dumps(changed))
    elif fault == 'recipe':
        frozen['recipe'][str(entry.search.CPP)]['sha256'] = '0' * 64
    elif fault == 'toy':
        frozen['active_project_ids'] = ['P01']
    elif fault == 'fake_calls':
        frozen['model_calls'] = True
    path.write_text(json.dumps(frozen))
    monkeypatch.setattr(entry.subprocess, 'Popen', lambda *a, **k: pytest.fail('Changed preparation launched child'))
    with pytest.raises(ValueError):
        entry.execute_prepared(prepared)
    assert not (prepared / 'run.sqlite').exists()


def test_run_requires_prepared_and_no_ambiguous_inputs(prepared):
    with pytest.raises(SystemExit):
        entry.main(['--spec', 'source.json', '--output', 'new', '--run'])
    with pytest.raises(SystemExit):
        entry.main(['--prepared', str(prepared), '--spec', 'source.json'])
