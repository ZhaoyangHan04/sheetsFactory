"""Replay the same actual-shaped stopped receipt; all daemon calls are mocks."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from sheets_factory.evaluation import ringfenced_observation_supplement as m
from sheets_factory.evaluation import ringfenced_resource_harbor as ring

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_historical_ring_observation_fixtures', ROOT/'tests/test_resource_observer.py')
fixtures = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixtures)
old = SimpleNamespace(**m.original._namespace)


@pytest.fixture
def family(tmp_path, monkeypatch):
    monkeypatch.setattr(fixtures, 'observer', old)
    monkeypatch.setattr(fixtures, 'PROFILE', ring.PROFILE)
    monkeypatch.setattr(fixtures, 'export_resource_harbor', lambda *a, **kw: ring.export_resource_harbor(*a, **kw, audit_path=tmp_path/'cap.json'))
    return fixtures.family.__wrapped__(tmp_path)


def check(family, watch):
    return m.supplement_trial(family.trial/'config.json', family.trial/'result.json', receipts=[watch.receipt],
        expected_profile=ring.PROFILE, expected_task_directory=family.task)


def test_same_original_ring_receipt_fails_old_import_and_passes_complete_supplement(family):
    watch, daemon = fixtures.collect(family)
    before = {p: old._reference(p) for p in [Path(watch.receipt['path']), family.trial/'config.json', family.trial/'result.json']}
    result = check(family, watch)
    assert result['original_validation']['passed'] is result['original_validation']['complete'] is False
    assert result['original_validation']['problems'] == ['Resource evidence binding incomplete: ValueError']
    new = result['supplemental_validation']
    assert new['passed'] is new['complete'] is True and new['roles_observed'] == ['agent', 'verifier']
    assert result['original_observer_implementation']['sha256'] == m.ORIGINAL_SHA
    assert old._read(watch.receipt)['implementation'] == result['original_observer_implementation']
    assert result['recipe']['supplement_checker'] != result['original_observer_implementation']
    assert result['new_observer_or_container_calls'] == 0 and result['original_results_or_receipts_or_scores_modified'] is False
    assert before == {p: old._reference(p) for p in before}
    assert m.validate_observation_receipt(family.run, family.selection, family.evaluation)['passed'] is True
    assert fixtures.check(family, watch)['passed'] is False
    assert all('Env' not in str(argv) for argv, _ in daemon.commands)


@pytest.mark.parametrize('fault', ['cpu', 'ram', 'image', 'missing_role', 'short_id'])
def test_supplement_preserves_all_actual_capacity_identity_image_and_role_requirements(family, fault):
    daemon = fixtures.Daemon(family)
    if fault == 'cpu': daemon.capacity['agent'] = {'NanoCpus': 4*10**9}
    if fault == 'ram': daemon.capacity['verifier'] = {'Memory': 64*1024**3}
    if fault == 'image': daemon.ancestry = False
    if fault == 'missing_role': daemon.roles = ['agent']
    if fault == 'short_id': daemon.short_id = True
    watch, _ = fixtures.collect(family, daemon)
    assert check(family, watch)['supplemental_validation']['passed'] is False


@pytest.mark.parametrize('fault', ['implementation', 'snapshot', 'result', 'profile', 'observation'])
def test_changed_historical_receipt_recipe_or_export_evidence_is_not_supplemented(family, fault):
    watch, _ = fixtures.collect(family)
    if fault == 'implementation':
        watch.receipt = fixtures.rewrite_receipt(watch, lambda value: value.update(implementation=old._reference(m.__file__)))
    elif fault == 'snapshot':
        snapshot = old._read(watch.receipt)['evaluation_snapshot']; Path(snapshot['path']).write_text('{}')
        assert m.validate_observation_receipt(family.run, family.selection, family.evaluation)['passed'] is False
        return
    elif fault == 'result': (family.trial/'result.json').write_text('{}')
    elif fault == 'profile':
        path = family.task/'environment/runtime_profile.json'; path.write_text(path.read_text()+' ')
    else:
        record = old._read(watch.receipt)['observations'][0]; Path(record['path']).write_text('{}')
    assert check(family, watch)['supplemental_validation']['passed'] is False


def test_original_namespace_and_provider_files_remain_unchanged_and_guarded(monkeypatch):
    assert m._namespace is not m.original._namespace
    assert m._namespace['__file__'] == m.original.__file__
    assert m.original._namespace['validate_trial_observations'] is not m._namespace['validate_trial_observations']
    assert m.reference(m.original.__file__)['sha256'] == m.ORIGINAL_SHA
    assert m.reference(m.base.__file__)['sha256'] == m.BASE_SHA
    monkeypatch.setattr(m, 'ORIGINAL_SHA', '0'*64)
    with pytest.raises(ValueError, match='historical'): m.recipes()
