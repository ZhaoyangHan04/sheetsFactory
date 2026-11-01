"""Cohort selection must not turn unknown runs into failed-model evidence."""
import importlib.util
import json
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


def test_frozen_root_inventory_is_accepted_by_the_exact_control_runner(tmp_path):
    from openpyxl import Workbook
    from sheets_factory.evaluation.resource_harbor import export_resource_harbor, inspect_resource_export
    control_path = PATH.with_name('run_exact_root_harbor_controls.py')
    loader = importlib.util.spec_from_file_location('factory_cohort_control_test', control_path)
    controls = importlib.util.module_from_spec(loader); loader.loader.exec_module(controls)
    tasks = []; results = []
    for mode in ('financial_modeling', 'debugging'):
        for i in range(10):
            task_id = mode+str(i); material = tmp_path/'original'/task_id
            (material/'public').mkdir(parents=True); (material/'private').mkdir()
            for value, path in ((i, material/'public/input.xlsx'), (100, material/'private/goal.xlsx')):
                book = Workbook(); book.active['A1'] = value; book.save(path); book.close()
            (material/'public/instruction.md').write_text('Complete the report in /app/output.xlsx.\n')
            export = export_resource_harbor(material, tmp_path/'exports'/task_id,
                {'task_id': task_id, 'mode': mode, 'revision': 0, 'revision_hash': task_id})
            evidence = material/'engineering.json'; evidence.write_text(json.dumps({'complete_primary_difference_count': 1}))
            tasks.append({'task_id': task_id, 'mode': mode, 'variant_id': str(i), 'revision': 0,
                'revision_hash': task_id, 'task_directory': str(export), 'harbor_export_binding': inspect_resource_export(export),
                'individual_engineering': module.reference(evidence)})
            results.append({'task_id': task_id, 'actual_attempt': {'reward': 0}, 'resources': {'passed': True, 'complete': True},
                            'score': {'state': 'complete', 'effective_reward': 0}})
    batch = tmp_path/'batch.json'; batch.write_text(json.dumps({'kind': 'individually_engineered_operating_report_batch', 'tasks': tasks}))
    development = tmp_path/'development.json'; development.write_text(json.dumps({'kind': 'operating_reports_factory_frontier_terminal_v6', 'phase': 'development', 'results': results}))
    final = tmp_path/'delivered'; final.mkdir()
    module.freeze(development, [batch], tmp_path/'cohort', final/'SpreadsheetEval')
    inventory = controls.dataset_inventory(final)
    assert len(inventory['task_ids']) == 20
    manifest = json.loads((final/'SpreadsheetEval/dataset_manifest.json').read_text())
    assert all(row['revision'] == 0 and row['revision_hash'] == row['task_id'] for row in manifest['tasks'])
