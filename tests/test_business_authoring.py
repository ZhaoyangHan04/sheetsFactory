from pathlib import Path
from types import SimpleNamespace

import pytest

from sheets_factory.nodes.construction import InstructionNode, PlanNode, construction_contract
from sheets_factory.core.node import TaskRejected


def test_business_instruction_preserves_scope_without_calculation_tutorial(tmp_path):
    (tmp_path / 'public').mkdir()
    source = tmp_path / 'input.xlsx'
    source.write_bytes(b'fixture input binding')
    context = SimpleNamespace(
        config={'construction': {'instruction_style': 'business_brief'}},
        revision_dir=tmp_path, mode='debugging',
        data={'input': source, 'plan': {
            'public_instruction': 'Audit and repair the financing model for the investment committee.',
            'public_rules': ['Use the existing assumptions and model policies.'],
            'edits': [],
        }})
    result = InstructionNode().execute(context)
    assert result['instruction_path'].read_text() == result['instruction']
    assert 'Model context:' in result['instruction']
    assert 'Public calculation rules' not in result['instruction']
    assert 'allow dependent results to recalculate' in result['instruction']
    assert '/app/input.xlsx' in result['instruction'] and '/app/output.xlsx' in result['instruction']
    assert 'Missing formula cells' not in result['instruction']
    assert len(result['instruction'].split()) < 100
    assert len(result['revision_hash']) == 64


def test_extended_mask_capacity_is_explicit_and_bounded():
    assert construction_contract()['modes']['financial_modeling']['edit_count']['max'] == 80
    assert construction_contract(config={'construction': {'max_edit_count': {'financial_modeling': 8192}}})[
        'modes']['financial_modeling']['edit_count']['max'] == 8192
    with pytest.raises(ValueError):
        construction_contract(config={'construction': {'max_edit_count': {'financial_modeling': 200001}}})


def test_template_backend_rejects_unverified_source_before_authoring(tmp_path):
    context = SimpleNamespace(mode='financial_modeling',
        config={'construction': {'authoring_backend': 'project_template', 'planning_scope': 'per_mode'}},
        data={'variant': 0, 'source_cache': tmp_path, 'finance_evidence': {}})
    with pytest.raises(TaskRejected, match='verified financial source'):
        PlanNode().execute(context)
    assert not list(tmp_path.glob('task_plans*'))


def test_template_backend_rejects_unsupported_backend_before_work():
    context = SimpleNamespace(config={'construction': {'authoring_backend': 'unknown'}}, data={})
    with pytest.raises(ValueError, match='authoring_backend'):
        PlanNode().execute(context)
