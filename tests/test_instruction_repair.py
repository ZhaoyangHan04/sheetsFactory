"""Instruction patches preserve source-backed plan fields without a model echo."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from sheets_factory.core.node import TaskContext, TaskRejected
from sheets_factory.nodes.quality import (RepairNode, apply_instruction_repair, instruction_repair_receipt,
                                         replay_legacy_instruction_proposal)

ROOT = Path(__file__).resolve().parents[1]


def plan():
    return {'title': 'Original', 'public_instruction': 'Preserve every other value.',
        'target_sheets': ['Forecast', 'Summary'], 'edits': [{'sheet': 'Forecast', 'cell': 'A1', 'before': '=Inputs!A1'}],
        'public_rules': ['Existing public rule'], 'reference_evidence': ['Original evidence'],
        'scenario_inputs': [{'sheet': 'Inputs', 'cell': 'A1', 'after': 100}], 'future_extension': {'keep': [1, 2]}}


def patch(ids=('issue-a',)):
    return {'public_instruction': 'Edit only the listed formulas; allow dependent values to recalculate.',
        'addressed_issue_ids': list(ids), 'changes': ['Clarify preservation of formulas and literal inputs.'],
        'unresolved_questions': []}


def test_minimal_patch_preserves_every_noninstruction_field_and_does_not_alias_original():
    old = plan()
    new = apply_instruction_repair(old, patch(), ['issue-a'])
    assert {k: v for k, v in new.items() if k != 'public_instruction'} == {
           k: v for k, v in old.items() if k != 'public_instruction'}
    new['future_extension']['keep'].append(3)
    assert old['future_extension']['keep'] == [1, 2]


@pytest.mark.parametrize('defect', ['missing_id', 'extra_id', 'duplicate_id', 'empty_instruction',
                                   'missing_field', 'extra_plan_field', 'unresolved'])
def test_invalid_patches_cannot_be_applied(defect):
    p = patch()
    if defect == 'missing_id': p['addressed_issue_ids'] = []
    if defect == 'extra_id': p['addressed_issue_ids'].append('unassigned')
    if defect == 'duplicate_id': p['addressed_issue_ids'] *= 2
    if defect == 'empty_instruction': p['public_instruction'] = '  \n'
    if defect == 'missing_field': del p['changes']
    if defect == 'extra_plan_field': p['target_sheets'] = []
    if defect == 'unresolved': p['unresolved_questions'] = ['Need an unsupported assumption']
    with pytest.raises(TaskRejected):
        apply_instruction_repair(plan(), p, ['issue-a'])


@pytest.mark.parametrize('mixed', [False, True])
def test_repair_node_uses_minimal_contract_only_for_all_q03_routes(tmp_path, mixed):
    observed = []
    old = plan()
    issues = [{'issue_id': 'issue-a', 'problem_id': 'Q03', 'certainty': 'confirmed'}]
    routes = [{'issue_id': 'issue-a', 'problem_id': 'Q03', 'route_class': 'repair'}]
    if mixed:
        issues.append({'issue_id': 'issue-b', 'problem_id': 'Q02', 'certainty': 'confirmed'})
        routes.append({'issue_id': 'issue-b', 'problem_id': 'Q02', 'route_class': 'repair'})
    class LLM:
        def complete(self, text, **kwargs):
            observed.append((text, kwargs))
            if mixed:
                assert 'output_schema' not in kwargs
                return {'repaired_task': {**old, 'reference_evidence': ['Permitted mixed-route change']},
                        'addressed_issue_ids': ['issue-a', 'issue-b']}
            schema = kwargs['output_schema']
            assert set(schema['properties']) == {'public_instruction', 'addressed_issue_ids', 'changes', 'unresolved_questions'}
            assert schema['additionalProperties'] is False
            assert 'Do not return or restate the full task plan' in text
            return patch()
    class Audit:
        def emit(self, *args, **kwargs): pass
    ctx = TaskContext('run', 'task', 'financial_modeling', tmp_path / 'source.xls', tmp_path / 'task',
        {'project_root': str(ROOT), 'run': {'max_steps': 3}, 'agents': {'timeout_seconds': 10}}, Audit(), LLM(), None)
    ctx.data.update(plan=old, diagnosis={'issues': issues}, repair_routes=routes,
        profile={'sheet_count': 4, 'nonempty_sheet_count': 4, 'formula_count': 10,
                 'errors': [], 'external_references': [], 'sheets': []})
    before = deepcopy(old)
    result = RepairNode().execute(ctx)['next_plan']
    assert old == before
    if mixed:
        assert result['reference_evidence'] == ['Permitted mixed-route change']
    else:
        assert result == {**old, 'public_instruction': patch()['public_instruction']}
        assert json.loads((ctx.revision_dir / 'private/instruction_repair_receipt.json').read_text())['requires_full_revision_gates']


def test_legacy_replay_ignores_model_drift_but_requires_matching_source_plan_and_issue_receipts(tmp_path):
    source, baseline = tmp_path / 'source.xls', tmp_path / 'baseline.xlsx'
    source.write_bytes(b'immutable original source fixture')
    baseline.write_bytes(b'immutable normalized fixture')
    old = plan()
    candidate = deepcopy(old)
    del candidate['target_sheets']
    candidate['reference_evidence'] = ['Unrequested model drift']
    candidate['public_instruction'] = patch()['public_instruction']
    proposal = {'repaired_task': candidate, 'addressed_issue_ids': ['issue-a'], 'unresolved_questions': []}
    issues = [{'issue_id': 'issue-a', 'problem_id': 'Q03', 'certainty': 'confirmed',
               'evidence': ['Concrete mismatch'], 'claim': 'Recalculation changes dependents'}]
    receipt = instruction_repair_receipt(task_id='task', revision=0, current_plan=old, assigned_issues=issues,
        source_path=source, baseline_path=baseline, proposal=proposal,
        expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        expected_baseline_sha256=hashlib.sha256(baseline.read_bytes()).hexdigest())
    replay = replay_legacy_instruction_proposal(old, proposal, issues,
        recorded_receipt=receipt, current_receipt=receipt)
    assert replay['next_plan'] == {**old, 'public_instruction': patch()['public_instruction']}
    assert {d['field'] for d in replay['ignored_noninstruction_differences']} == {'target_sheets', 'reference_evidence'}
    assert replay['requires_full_revision_gates'] and not replay['reuse_old_harbor_controls']
    for field in ('source_sha256', 'plan_sha256', 'issues_sha256', 'proposal_sha256', 'revision'):
        changed = deepcopy(receipt)
        changed[field] = 'changed'
        with pytest.raises(TaskRejected):
            replay_legacy_instruction_proposal(old, proposal, issues, recorded_receipt=receipt, current_receipt=changed)
    source.write_bytes(b'new source bytes')
    with pytest.raises(TaskRejected, match='Immutable source'):
        instruction_repair_receipt(task_id='task', revision=0, current_plan=old, assigned_issues=issues,
            source_path=source, baseline_path=baseline, proposal=proposal,
            expected_source_sha256=receipt['source_sha256'], expected_baseline_sha256=receipt['baseline_sha256'])
