"""Bind native-probe goal references without changing task artifacts or scores."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def reporter():
    spec = importlib.util.spec_from_file_location('_test_cohort_goal_ref_reporter',
        ROOT / 'scripts/report_operating_reports_financial_cohort_quality.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def material(tmp_path):
    base = tmp_path / 'current'
    goal = base / 'private/goal.xlsx'
    goal.parent.mkdir(parents=True)
    goal.write_bytes(b'TEST_ONLY goal reference bytes')
    record = {'path': str(goal.resolve()), 'sha256': hashlib.sha256(goal.read_bytes()).hexdigest(), 'bytes': goal.stat().st_size}
    return base, {'goal': record}, {'goal_sha256': record['sha256']}


def test_complete_current_goal_ref_is_verified(reporter, tmp_path):
    base, native, binding = material(tmp_path)
    assert reporter._current_native_goal(native, binding, base) is True
    native['goal_sha256'] = binding['goal_sha256']
    assert reporter._current_native_goal(native, binding, base) is True


@pytest.mark.parametrize('fault', ['missing', 'sha', 'bytes', 'bool_bytes', 'wrong_path', 'binding', 'conflict', 'changed_file'])
def test_goal_alias_cannot_bypass_current_bytes(reporter, tmp_path, fault):
    base, native, binding = material(tmp_path)
    if fault == 'missing':
        native = {'goal_sha256': binding['goal_sha256']}
    elif fault == 'sha':
        native['goal']['sha256'] = '0' * 64
    elif fault == 'bytes':
        native['goal']['bytes'] += 1
    elif fault == 'bool_bytes':
        native['goal']['bytes'] = True
    elif fault == 'wrong_path':
        native['goal']['path'] = str(tmp_path / 'other.xlsx')
    elif fault == 'binding':
        binding['goal_sha256'] = '0' * 64
    elif fault == 'conflict':
        native['goal_sha256'] = '0' * 64
    elif fault == 'changed_file':
        (base / 'private/goal.xlsx').write_bytes(b'TEST_ONLY changed goal')
    with pytest.raises(ValueError):
        reporter._current_native_goal(native, binding, base)


def test_real_completed_C01_run_has_all_bound_quality_evidence(reporter):
    directory = ROOT / 'outputs/research/operating_reports_financial_cohort_C01_normal_pilot_revision2_20261101T014400Z'
    if not (directory / 'summary.json').is_file():
        pytest.skip('The real immutable C01 run is not included in the repository')
    report = reporter.generate_report(directory)
    assert report['yield']['verified_qualified'] == 1
    assert report['consistency_warnings'] == []
    task, = report['tasks']
    assert task['reference_validation']['verified'] is True
    assert task['diagnosis']['enabled_check_count'] == 12
    assert task['oracle']['reward'] == 1 and task['nop']['reward'] == 0
