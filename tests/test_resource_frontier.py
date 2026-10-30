"""The resource gate accepts its complete inventory without changing scoring."""
import ast
from copy import deepcopy
import inspect
import json
from pathlib import Path

import openpyxl
import pytest

from sheets_factory.evaluation import frontier, resource_frontier as resource
from sheets_factory.evaluation.resource_harbor import export_resource_harbor, inspect_resource_export

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml'
BUDGET = {'version': 1, 'elapsed_policy': 'operational_guard', 'elapsed_guard_seconds': 14400, 'tool_budget_seconds': 1800}


@pytest.fixture
def exported(tmp_path):
    task = tmp_path / 'actual'; (task / 'public').mkdir(parents=True); (task / 'private').mkdir()
    book = openpyxl.Workbook(); book.active['A1'] = 10
    book.save(task / 'public/input.xlsx'); book.active['A1'] = 20
    book.save(task / 'private/goal.xlsx'); book.close()
    (task / 'public/instruction.md').write_text('Set the supplied number to twenty. Save /app/output.xlsx.')
    output = tmp_path / 'export/task-one'
    export_resource_harbor(task, output, {'task_id': 'task-one', 'revision': 0, 'revision_hash': 'fixture',
        'mode': 'debugging'}, runtime_profile=PROFILE)
    manifest = {'selected_task_ids': ['task-one'], 'execution_budget': deepcopy(BUDGET),
        'tool_time_policy_version': 2, 'tasks': [{'task_id': 'task-one', 'mode': 'debugging',
            'task_directory': str(output), 'revision': 0, 'revision_hash': 'fixture',
            'harbor_export_binding': inspect_resource_export(output), 'execution_budget': deepcopy(BUDGET)}]}
    path = tmp_path / 'source.json'; path.write_text(json.dumps(manifest))
    return path, output


def test_resource_snapshot_validates_all_seventeen_files_and_strict_original_budget(exported, tmp_path):
    path, output = exported
    selected = resource.freeze_selection(path, tmp_path / 'resource', phase='development')
    assert len(resource.TASK_FILES) == 17
    assert selected['n_attempts'] == 1 and selected['timeout_seconds'] == 14400
    assert selected['execution_budget'] == BUDGET
    assert selected['tool_time_policy']['strict_less_than'] is True
    assert selected['tool_time_policy']['parallel_executions'] == 'sum'
    snapshot = Path(selected['tasks'][0]['task_directory'])
    assert inspect_resource_export(snapshot) == inspect_resource_export(output)
    assert len(frontier.TASK_FILES) == 13
    with pytest.raises(frontier.FrontierError, match='unexpected or missing files'):
        frontier.freeze_selection(path, tmp_path / 'old', phase='development')


def test_resource_adapter_changes_only_inventory_inspection_and_class_identity():
    before = ast.parse(Path(frontier.__file__).read_bytes())
    after = resource.adapted_ast()
    changes = []
    assert len(before.body) == len(after.body)
    for left, right in zip(before.body, after.body):
        if ast.dump(left) != ast.dump(right):
            changes.append((getattr(left, 'name', None), type(left).__name__))
    assert changes == [(None, 'ImportFrom'), (None, 'Assign'),
                       ('_matches_execution', 'FunctionDef'), ('_job_config', 'FunctionDef')]
    # Complete trial classification, retries, timing bounds, selection provenance,
    # score aggregation and publication gates are the exact frozen upstream AST.
    for name in ('classify_result', 'apply_tool_time_policy', 'summarize', 'assess_infrastructure_retry',
                 'execute_evaluation', 'run_evaluation', 'resume_infrastructure'):
        left = next((n for n in before.body if getattr(n, 'name', None) == name), None)
        right = next((n for n in after.body if getattr(n, 'name', None) == name), None)
        assert left is not None and ast.dump(left) == ast.dump(right)


def test_added_public_artifact_is_rejected_even_if_export_inventory_were_extended(exported, tmp_path):
    path, output = exported
    (output / 'environment/extra.bin').write_bytes(b'unapproved input')
    with pytest.raises(resource.FrontierError, match='unexpected or missing files'):
        resource.freeze_selection(path, tmp_path / 'extra', phase='development')


def test_confirmation_still_requires_ten_per_mode(exported, tmp_path):
    with pytest.raises(resource.FrontierError, match='at least ten tasks per category'):
        resource.freeze_selection(exported[0], tmp_path / 'confirmation', phase='confirmation')


def test_job_keeps_native_model_single_attempt_and_isolated_class_path(exported, tmp_path):
    selected = resource.freeze_selection(exported[0], tmp_path / 'resource', phase='development')
    job = resource._job_config(tmp_path / 'resource', selected, concurrency=1,
        binary=Path('/native/codex'), base_url='http://localhost.invalid/v1')
    actual = job.model_dump(mode='json')
    assert actual['n_attempts'] == 1 and actual['retry']['max_retries'] == 0
    assert actual['agents'][0]['import_path'] == 'sheets_factory.evaluation.resource_frontier:LocalCodex'
    assert actual['agents'][0]['model_name'] == 'gpt-6.1-sol'
    assert actual['agents'][0]['kwargs']['reasoning_effort'] == 'xhigh'
    assert actual['agents'][0]['override_timeout_sec'] == 14400
