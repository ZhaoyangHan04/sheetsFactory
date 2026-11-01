"""Run the unchanged v1 guard suite against the private corrected namespace."""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
_old_tests = ROOT/'tests/test_cached_ringfenced_pair_task_batch.py'
_text = _old_tests.read_text()
_needle = "ROOT/'scripts/build_cached_ringfenced_pair_task_batch.py'"
assert _text.count(_needle) == 1
_text = _text.replace(_needle, "ROOT/'scripts/build_cached_ringfenced_pair_task_batch_revision2.py'")
# The v1 native fixture is explicitly synthetic. Give its cleanup the same
# daemon contract required by the new production namespace.
_cleanup = "{'passed': True, 'all_owned_containers_absent': True, 'owned': values}"
assert _text.count(_cleanup) == 1
_text = _text.replace(_cleanup, "{'passed': True, 'all_owned_containers_absent': True, 'owned': values, 'daemon_id': 'fixture-daemon'}")
_set = "monkeypatch.setattr(m, 'recipes', lambda: {'frozen_fixture': True})"
assert _text.count(_set) == 1
_text = _text.replace(_set, _set+"\n    monkeypatch.setattr(m, '_daemon_id', lambda: 'fixture-daemon')")
exec(compile(ast.parse(_text), str(_old_tests), 'exec'), globals())


def test_revision2_namespace_binds_new_provider_and_keeps_original_functions_unchanged():
    original = m._original
    assert m.SOURCE_BUILDER.name == 'build_cached_ringfenced_pair_source_revision2.py'
    assert original.SOURCE_BUILDER.name == 'build_cached_ringfenced_pair_source.py'
    assert m.SOURCE_BUILDER_SHA == '08b6e3055178f5516de71eaeb4e5cbb82f56adfe78f394a7a70e0c5bff5ed855'
    assert m.admit.__code__ is original.admit.__code__ and m.admit.__globals__ is vars(m)
    assert original.admit.__globals__ is vars(original)
    assert m.ref(m._BASE)['sha256'] == m._BASE_SHA
    assert m.recipes()['original_task_builder'] == m.ref(m._BASE)
    assert m.recipes()['same_daemon_before_after_required'] is True


def test_actual_daemon_command_is_read_only_and_nonempty(monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs)); return SimpleNamespace(stdout='same-daemon\n')
    monkeypatch.setattr(m.subprocess, 'run', run)
    assert m._daemon_id() == 'same-daemon'
    assert calls[0][0] == ['docker', 'info', '--format', '{{.ID}}'] and calls[0][1]['check'] is True
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout='  '))
    with pytest.raises(ValueError, match='unknown'): m._daemon_id()


def test_same_daemon_receipt_is_required_and_bound_into_final_batch(flow):
    _, source, output, _ = flow
    result = m.read(m.run(source, output)); before = m.read(result['native_daemon_before'])
    cleanup = m.read(result['owned_resource_cleanup'])
    assert before['daemon_before_id'] == cleanup['daemon_id'] == cleanup['daemon_before_id'] == 'fixture-daemon'
    assert cleanup['same_daemon_before_after'] is True


@pytest.mark.parametrize('observed', ['different-daemon', None])
def test_changed_or_unknown_cleanup_daemon_retains_failure_no_repeat(flow, monkeypatch, observed):
    _, source, output, state = flow
    monkeypatch.setattr(m.dual, 'owned_cleanup', lambda rows: {'passed': True, 'all_owned_containers_absent': True,
        'owned': rows, 'daemon_id': observed})
    with pytest.raises(ValueError, match='Docker daemon'): m.run(source, output)
    failure = m.read(output/'failure.json')
    assert state['count'] == 2 and failure['daemon_before_id'] == 'fixture-daemon'
    assert failure['outer_retries'] == 0 and not (output/'engineered_batch.json').exists()
    assert m.read(failure['owned_cleanup'])['type'] == 'ValueError'


def test_unknown_initial_daemon_stops_before_any_native_call(flow, monkeypatch):
    _, source, output, state = flow
    monkeypatch.setattr(m, '_daemon_id', lambda: '')
    # The actual helper rejects empty IDs; emulate its failure before calling LO.
    def unknown(): raise ValueError('initial Docker identity unknown')
    monkeypatch.setattr(m, '_daemon_id', unknown)
    with pytest.raises(ValueError, match='unknown'): m.run(source, output)
    assert state['count'] == 0 and m.read(output/'failure.json')['actual_LO_calls_started'] == 0
