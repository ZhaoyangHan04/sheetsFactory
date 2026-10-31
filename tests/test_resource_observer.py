"""Scoped daemon fixtures only: no Docker, model, LO or Harbor execution."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

from openpyxl import Workbook
import pytest

from sheets_factory.evaluation import resource_observer as observer
from sheets_factory.evaluation.resource_harbor import export_resource_harbor
from sheets_factory.workbook.resource_engine import DEFAULT_PROFILE, load_runtime_profile

PROFILE = DEFAULT_PROFILE.with_name('entity_group_large_v2.yaml')
BASE = load_runtime_profile(PROFILE)['image']['id']
DERIVED = 'sha256:' + 'd' * 64
LAYERS = ['sha256:' + '1' * 64, 'sha256:' + '2' * 64]
IDS = {'agent': 'a' * 64, 'verifier': 'b' * 64}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + '\n')
    return observer._reference(path)


@pytest.fixture
def family(tmp_path):
    revision = tmp_path / 'revision'
    for folder in ('public', 'private'): (revision / folder).mkdir(parents=True)
    for folder in ('public', 'private'):
        book = Workbook(); book.active['A1'] = 1 if folder == 'public' else 2
        book.save(revision / folder / ('input.xlsx' if folder == 'public' else 'goal.xlsx')); book.close()
    (revision / 'public/instruction.md').write_text('Restore the financial model. Save /app/output.xlsx.')
    task = export_resource_harbor(revision, tmp_path / 'task',
        {'task_id': 'family', 'revision': 0, 'revision_hash': 'c' * 64}, runtime_profile=PROFILE)
    run = tmp_path / 'run'; trial_name = 'Family__Mixed42'
    trial = run / 'harbor_jobs/frontier-pass1' / trial_name
    config = {'trial_name': trial_name, 'task': {'path': str(task)},
              'agent': {'kwargs': {'secret_fixture': 'MUST_NOT_BE_PERSISTED'}}}
    write(trial / 'config.json', config)
    result = {'trial_name': trial_name, 'task_name': 'sheetsfactory/family',
        'config': {'task': {'path': str(task)}}, 'verifier_result': {'rewards': {'reward': 0}}, 'exception_info': None}
    result_ref = write(trial / 'result.json', result)
    selection = {'tasks': [{'task_id': 'family', 'task_directory': str(task)}]}
    evaluation = {'attempts': [{'task_id': 'family', 'result_file': str(trial / 'result.json'),
        'result_sha256': result_ref['sha256']}], 'infra_history': [], 'infrastructure_retries': [], 'score': 0}
    write(run / 'selection_manifest.json', selection); write(run / 'evaluation_manifest.json', evaluation)
    return SimpleNamespace(run=run, trial=trial, name=trial_name, task=task, config=config,
                           result=result, selection=selection, evaluation=evaluation)


class Daemon:
    def __init__(self, family):
        self.family = family; self.commands = []; self.roles = ['agent', 'verifier']
        self.capacity = {}; self.ancestry = True; self.fail = None; self.short_id = False
    def __call__(self, command, **kwargs):
        self.commands.append((command, kwargs))
        assert kwargs['capture_output'] is True and kwargs['text'] is True and 0 < kwargs['timeout'] <= 5
        assert all('Env' not in part for part in command)
        if self.fail: raise self.fail
        if command[:3] == ['docker', 'ps', '-a']:
            assert command == ['docker','ps','-a','--no-trunc','--filter',
                'name=^/' + self.family.name.lower() + '__','--format','{{.ID}}\t{{.Names}}']
            lines = [(IDS[r][:12] if self.short_id else IDS[r]) + '\t' + self.family.name.lower()
                     + observer.ROLE_SUFFIXES[r] for r in self.roles]
            # Prefix-similar and unrelated containers must never be inspected.
            lines += ['e' * 64 + '\t' + self.family.name.lower() + '__other-1']
            return SimpleNamespace(returncode=0, stdout='\n'.join(lines), stderr='')
        if command[:2] == ['docker', 'inspect']:
            assert command[2] in IDS.values() and len(command[2]) == 64
            role = next(r for r in IDS if IDS[r] == command[2])
            value = {'Id': command[2], 'Name': '/' + self.family.name.lower() + observer.ROLE_SUFFIXES[role],
                'Image': DERIVED, 'NanoCpus': 2 * 10**9, 'Memory': 32 * 1024**3}
            value.update(self.capacity.get(role, {}))
            return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr='')
        assert command[:3] == ['docker', 'image', 'inspect'] and command[3] in (BASE, DERIVED)
        layers = LAYERS if command[3] == BASE else (LAYERS + ['sha256:' + '3' * 64] if self.ancestry else ['sha256:' + 'f' * 64])
        return SimpleNamespace(returncode=0, stdout=json.dumps({'Id': command[3], 'RootFSLayers': layers}), stderr='')


def collect(family, daemon=None):
    daemon = daemon or Daemon(family)
    watch = observer.ResourceObserver(family.run, command_runner=daemon)
    watch.poll_once(); watch.__exit__(None, None, None)
    assert watch.receipt is not None and watch.finalization_error is None
    return watch, daemon


def check(family, watch, **kwargs):
    return observer.validate_trial_observations(family.trial / 'config.json', family.trial / 'result.json',
        receipts=[watch.receipt], expected_profile=PROFILE, expected_task_directory=family.task, **kwargs)


def rewrite_receipt(watch, change):
    value = observer._read(watch.receipt); change(value)
    return write(Path(watch.receipt['path']), value)


def test_actual_two_roles_full_ids_cpu_ram_image_ancestry_and_final_bindings(family):
    frozen_result = observer._reference(family.trial / 'result.json')
    watch, daemon = collect(family)
    checked = check(family, watch)
    assert checked['passed'] is True and checked['complete'] is True
    assert checked['roles_observed'] == ['agent', 'verifier']
    assert checked['runtime_profile']['value']['solver_tool_budget']['seconds'] == 1800
    assert frozen_result == observer._reference(family.trial / 'result.json')
    assert checked['raw_reward_or_score_modified'] is False
    session = observer._read(watch.receipt)
    assert session['evaluation']['sha256'] == session['evaluation_snapshot']['sha256']
    saved = '\n'.join(Path(r['path']).read_text() for r in session['observations'])
    assert 'MUST_NOT_BE_PERSISTED' not in saved and '"Env"' not in saved
    inspected = [c[2] for c, _ in daemon.commands if c[:2] == ['docker', 'inspect']]
    assert inspected == [IDS['agent'], IDS['verifier']]
    whole = observer.validate_observation_receipt(family.run, family.selection, family.evaluation)
    assert whole['passed'] is True and whole['complete'] is True


@pytest.mark.parametrize('mutation', ['memory', 'cpu', 'name', 'identity', 'bool_cpu', 'ancestry'])
def test_observed_mismatch_cannot_be_hidden_by_later_correct_frame(family, mutation):
    daemon = Daemon(family)
    changes = {'memory': {'Memory': 8 * 1024**3}, 'cpu': {'NanoCpus': 10**9},
        'name': {'Name': '/wrong__env-main-1'}, 'identity': {'Id': '9' * 64}, 'bool_cpu': {'NanoCpus': True}}
    if mutation == 'ancestry': daemon.ancestry = False
    else: daemon.capacity['agent'] = changes[mutation]
    watch = observer.ResourceObserver(family.run, command_runner=daemon); watch.poll_once()
    daemon.capacity = {}; daemon.ancestry = True; watch.image_cache = {}; watch.poll_once()
    watch.__exit__(None, None, None)
    checked = check(family, watch)
    assert checked['passed'] is False and checked['status'] == 'resource_mismatch'
    assert observer._read(family.trial / 'result.json')['verifier_result']['rewards']['reward'] == 0


@pytest.mark.parametrize('kind', ['missing_role', 'timeout', 'short_id', 'daemon_error'])
def test_missing_evidence_incomplete_never_model_failure(family, kind):
    daemon = Daemon(family)
    if kind == 'missing_role': daemon.roles = ['agent']
    if kind == 'timeout': daemon.fail = subprocess.TimeoutExpired(['docker'], 5)
    if kind == 'daemon_error': daemon.fail = RuntimeError('sensitive daemon output')
    if kind == 'short_id': daemon.short_id = True
    watch, _ = collect(family, daemon)
    checked = check(family, watch)
    assert checked['passed'] is False and checked['complete'] is False
    assert checked['missing_evidence_is_not_a_model_failure'] is True
    assert 'sensitive daemon output' not in '\n'.join(p.read_text() for p in watch.directory.glob('*.json'))


@pytest.mark.parametrize('kind', ['result', 'config', 'profile', 'observation', 'expected_profile_ref'])
def test_binding_tampering_rejected(family, kind):
    watch, _ = collect(family)
    if kind == 'result': write(family.trial / 'result.json', {**family.result, 'changed': True})
    elif kind == 'config': write(family.trial / 'config.json', {**family.config, 'changed': True})
    elif kind == 'profile':
        path = family.task / 'environment/runtime_profile.json'; path.write_text(path.read_text() + ' ')
    elif kind == 'observation':
        item = observer._read(watch.receipt)['observations'][0]
        Path(item['path']).write_text('{}')
    else:
        fake = observer._reference(PROFILE); fake['sha256'] = '0' * 64
        checked = observer.validate_trial_observations(family.trial / 'config.json', family.trial / 'result.json',
            receipts=[watch.receipt], expected_profile=fake)
        assert checked['passed'] is False
        return
    assert check(family, watch)['passed'] is False


def test_append_only_sessions_do_not_overwrite_previous_frames(family):
    first, _ = collect(family); original = observer._reference(first.receipt['path'])
    second, _ = collect(family)
    assert first.directory != second.directory
    assert original == observer._reference(first.receipt['path'])
    assert observer.validate_trial_observations(family.trial / 'config.json', family.trial / 'result.json',
        receipts=[first.receipt, second.receipt])['passed'] is True


def test_resume_uses_only_runner_preserved_history_and_current_final_anchor(family):
    first, _ = collect(family)
    previous = family.run / 'private/evaluation_history/resume-001-before.json'
    previous.parent.mkdir(parents=True); previous.write_bytes((family.run / 'evaluation_manifest.json').read_bytes())
    updated = deepcopy(family.evaluation)
    updated['infrastructure_retries'] = [{'previous_manifest_file': str(previous),
        'previous_manifest_sha256': observer._reference(previous)['sha256']}]
    write(family.run / 'evaluation_manifest.json', updated)
    # Old containers have disappeared; the stopped old session remains evidence.
    daemon = Daemon(family); daemon.roles = []
    second, _ = collect(family, daemon)
    result = observer.validate_observation_receipt(family.run, family.selection, updated)
    assert result['passed'] is True and len(result['observation_receipts']) == 2
    previous.write_text('{}')
    assert observer.validate_observation_receipt(family.run, family.selection, updated)['passed'] is False


def test_old_session_cannot_authorize_an_unrecorded_changed_evaluation(family):
    collect(family)
    updated = {**family.evaluation, 'score': 1}
    write(family.run / 'evaluation_manifest.json', updated)
    checked = observer.validate_observation_receipt(family.run, family.selection, updated)
    assert checked['passed'] is False and checked['complete'] is False
    assert observer._read(family.run / 'evaluation_manifest.json')['score'] == 1


def test_manifest_snapshot_mutation_cannot_be_hidden_by_unchanged_session(family):
    watch, _ = collect(family)
    copied = observer._read(watch.receipt)['evaluation_snapshot']
    Path(copied['path']).write_text('{}')
    assert observer.validate_observation_receipt(family.run, family.selection, family.evaluation)['passed'] is False


def test_poll_total_command_time_is_bounded_even_with_many_roles(family, monkeypatch):
    clock = SimpleNamespace(value=0.0)
    monkeypatch.setattr(observer.time, 'monotonic', lambda: clock.value)
    daemon = Daemon(family)
    def bounded(command, **kwargs):
        remaining = kwargs['timeout']
        clock.value += min(2, remaining)
        if remaining < 2: raise subprocess.TimeoutExpired(command, remaining)
        return daemon(command, **kwargs)
    watch = observer.ResourceObserver(family.run, command_runner=bounded)
    watch.poll_once()
    assert clock.value == 5 and len(daemon.commands) == 2
    watch.__exit__(None, None, None)
    assert check(family, watch)['passed'] is False


def test_observer_does_not_create_fresh_runner_output_and_stops_on_exception(tmp_path):
    root = tmp_path / 'not-created'
    calls = []
    def forbidden(*args, **kwargs): calls.append(args); raise AssertionError('no scoped trial yet')
    with pytest.raises(RuntimeError, match='original operation'):
        with observer.ResourceObserver(root, command_runner=forbidden) as watch:
            assert not root.exists()
            raise RuntimeError('original operation')
    assert not root.exists() and not calls and not watch.thread.is_alive()


def test_selection_created_after_context_entry_is_bound(family, tmp_path):
    run = tmp_path / 'fresh'
    with observer.ResourceObserver(run, command_runner=lambda *a, **k: pytest.fail('no trials')) as watch:
        assert not run.exists()
        write(run / 'selection_manifest.json', family.selection)
        write(run / 'evaluation_manifest.json', {'attempts': []})
    assert observer._read(watch.receipt)['selection'] == observer._reference(run / 'selection_manifest.json')


@pytest.mark.parametrize('kind', ['symlink_run', 'outside_jobs'])
def test_unscoped_paths_rejected(tmp_path, kind):
    run = tmp_path / 'run'; run.mkdir()
    if kind == 'symlink_run':
        alias = tmp_path / 'alias'; alias.symlink_to(run, target_is_directory=True)
        with pytest.raises(ValueError, match='symlink'): observer.ResourceObserver(alias)
    else:
        with pytest.raises(ValueError, match='explicit job roots'): observer.ResourceObserver(run, job_dirs=[tmp_path])


def load_cli():
    path = Path(__file__).parents[1] / 'scripts/evaluate_resource_difficulty.py'
    spec = importlib.util.spec_from_file_location('resource_cli_for_test', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('resume', [False, True])
def test_cli_lifecycle_wraps_exact_existing_runner_without_scoring_changes(tmp_path, monkeypatch, capsys, resume):
    module = load_cli(); events = []; directory = tmp_path / 'run'
    class FakeObserver:
        def __init__(self, run): assert run == directory; self.receipt = None; self.finalization_error = None
        def __enter__(self): events.append('enter'); return self
        def __exit__(self, *args): events.append('exit')
    result = {'status': 'completed', 'score': 1, 'gate_passed': False}
    def execute(*args, **kwargs):
        events.append('execute'); assert kwargs['backend_config']['model'] == 'gpt-6.1-sol'
        assert kwargs['backend_config']['reasoning_effort'] == 'xhigh'
        return result
    monkeypatch.setattr(module, 'ResourceObserver', FakeObserver)
    monkeypatch.setattr(module, 'run_evaluation', execute); monkeypatch.setattr(module, 'resume_infrastructure', execute)
    args = ['--resume-infrastructure', str(directory)] if resume else [
        '--release-manifest', str(tmp_path / 'release.json'), '--output-dir', str(directory), '--phase', 'development']
    assert module.main(args) == 0 and events == ['enter', 'execute', 'exit']
    printed = json.loads(capsys.readouterr().out)
    assert {k: printed[k] for k in result} == result
