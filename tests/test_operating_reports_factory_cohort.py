"""Cohort selection must not turn unknown runs into failed-model evidence."""
import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1]/'scripts/freeze_operating_reports_factory_cohort.py'
spec = importlib.util.spec_from_file_location('factory_cohort_test', PATH)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


def fixture():
    tasks = []; results = []
    for mode in ('financial_modeling', 'debugging'):
        for i in range(12):
            key = mode+str(i)
            tasks.append({'task_id': key, 'mode': mode, 'variant_id': str(i), 'primary_difference_count': i*100})
            results.append({'task_id': key, 'actual_attempt': {'reward': 0}, 'resources': {'passed': True, 'complete': True},
                            'score': {'state': 'complete', 'effective_reward': 0 if i < 10 else 1}})
    return {'kind': 'operating_reports_factory_frontier_terminal_v6', 'phase': 'development', 'results': results}, tasks


def test_fixes_ten_each_using_development_results():
    development, tasks = fixture(); chosen = module.choose(development, tasks)
    assert len(chosen) == 20
    assert all(int(task['variant_id']) < 10 for task in chosen)
    assert chosen[0]['primary_difference_count'] == 900


def test_confirmation_results_cannot_select_the_cohort():
    development, tasks = fixture(); development['phase'] = 'confirmation'
    with pytest.raises(ValueError, match='development evidence only'):
        module.choose(development, tasks)


def test_unknown_zero_and_missing_resource_evidence_are_not_eligible():
    development, tasks = fixture()
    for row in development['results'][:3]:
        row['score']['state'] = 'unknown'; row['score']['effective_reward'] = None
    with pytest.raises(ValueError, match='Fewer than ten'):
        module.choose(development, tasks)


def test_known_tool_budget_failure_retains_zero():
    development, tasks = fixture(); development['results'][0]['score']['state'] = 'known_tool_budget_failure'
    assert 'financial_modeling0' in {row['task_id'] for row in module.choose(development, tasks)}
