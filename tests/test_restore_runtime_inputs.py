"""Offline restoration checks; no native office, agent, service, or Docker calls."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).resolve().parents[1]
definition = importlib.util.spec_from_file_location('runtime_input_restorer',
    ROOT / 'scripts/restore_runtime_inputs.py')
restore = importlib.util.module_from_spec(definition)
definition.loader.exec_module(restore)


@pytest.fixture
def checkout(tmp_path):
    project = tmp_path / 'checkout'
    shutil.copytree(ROOT / restore.ASSET_DIRECTORY, project / restore.ASSET_DIRECTORY)
    return project


def manifest(project):
    return json.loads((project / restore.MANIFEST).read_text())


def write_manifest(project, value):
    (project / restore.MANIFEST).write_text(json.dumps(value))


def test_fresh_checkout_restores_exact_bytes_and_second_run_does_not_write(checkout):
    assert restore.restore_runtime_inputs(checkout) == {'restored': 7, 'unchanged': 0, 'total': 7}
    before = {}
    for entry in manifest(checkout)['entries']:
        target = checkout / entry['target']
        data = target.read_bytes()
        assert data == (checkout / entry['source']).read_bytes()
        assert len(data) == entry['bytes']
        assert hashlib.sha256(data).hexdigest() == entry['sha256']
        before[entry['target']] = (target.stat().st_ino, target.stat().st_mtime_ns)
    assert restore.restore_runtime_inputs(checkout) == {'restored': 0, 'unchanged': 7, 'total': 7}
    assert before == {entry['target']: ((checkout / entry['target']).stat().st_ino,
        (checkout / entry['target']).stat().st_mtime_ns) for entry in manifest(checkout)['entries']}


def test_existing_different_file_refuses_entire_preflight_without_overwrite(checkout):
    entries = manifest(checkout)['entries']
    changed = checkout / entries[-1]['target']
    changed.parent.mkdir(parents=True)
    changed.write_bytes(b'local content must survive')
    with pytest.raises(restore.RestorationError, match='existing runtime input differs'):
        restore.restore_runtime_inputs(checkout)
    assert changed.read_bytes() == b'local content must survive'
    assert all(not (checkout / entry['target']).exists() for entry in entries[:-1])


def test_asset_hash_failure_is_detected_before_any_targets_are_written(checkout):
    entries = manifest(checkout)['entries']
    (checkout / entries[-1]['source']).write_bytes(b'changed asset')
    with pytest.raises(restore.RestorationError, match='bundled runtime input differs'):
        restore.restore_runtime_inputs(checkout)
    assert all(not (checkout / entry['target']).exists() for entry in entries)


def test_manifest_rejects_traversal_duplicates_and_unexpected_targets(checkout):
    original = manifest(checkout)
    for key, value in [('target', '../escape.md'),
                       ('source', restore.ASSET_DIRECTORY + '/../escape.txt'),
                       ('target', 'config/unlisted.md')]:
        changed = deepcopy(original)
        changed['entries'][0][key] = value
        write_manifest(checkout, changed)
        with pytest.raises(restore.RestorationError):
            restore.restore_runtime_inputs(checkout)
    changed = deepcopy(original)
    changed['entries'][-1] = changed['entries'][0]
    write_manifest(checkout, changed)
    with pytest.raises(restore.RestorationError):
        restore.restore_runtime_inputs(checkout)
    assert not (checkout.parent / 'escape.md').exists()


def test_source_target_and_directory_symlinks_are_rejected(checkout, tmp_path):
    entries = manifest(checkout)['entries']
    entry = entries[0]
    outside = tmp_path / 'outside'
    outside.mkdir()
    outside_file = outside / 'payload'
    outside_file.write_bytes((checkout / entry['source']).read_bytes())
    source = checkout / entry['source']
    data = source.read_bytes()
    source.unlink()
    source.symlink_to(outside_file)
    with pytest.raises(restore.RestorationError):
        restore.restore_runtime_inputs(checkout)
    source.unlink()
    source.write_bytes(data)
    target = checkout / entry['target']
    target.parent.mkdir(parents=True)
    target.symlink_to(outside_file)
    with pytest.raises(restore.RestorationError):
        restore.restore_runtime_inputs(checkout)
    target.unlink()
    target.parent.rmdir()
    target.parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(restore.RestorationError):
        restore.restore_runtime_inputs(checkout)
    assert not (outside / target.name).exists()


def test_cli_output_contains_only_counts_and_real_bundle_retains_frozen_hash(checkout, capsys):
    assert restore.main(['--project-root', str(checkout)]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out) == {'restored': 7, 'unchanged': 0, 'total': 7}
    assert output.err == ''
    entries = {entry['target']: entry for entry in manifest(checkout)['entries']}
    assert entries['docs/linear_capital_scaled_highs_screen.md']['sha256'] == (
        '0b59f03622373a23c4f809ff53216de3eb510ceb11884288a528995ae61d04fb')
