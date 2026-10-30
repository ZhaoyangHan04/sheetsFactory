"""Offline candidate-Q08 contracts; no model or difficulty-score fabrication."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from sheets_factory.checkers import DiagnosisRunner
from sheets_factory.core.node import TaskContext
from sheets_factory.nodes.quality import DiagnoseNode, candidate_difficulty_context
from test_checkers import bundle, controls, reviewer
from test_publish_dataset import fixture_publication, confirmation, invoke


ROOT = Path(__file__).resolve().parents[1]


def stage_bundle(contract=None):
    value = bundle()
    value['public']['difficulty_review_context'] = candidate_difficulty_context({'diagnosis': {
        'difficulty_deferred': False, 'template_complexity_contract': contract or []}})
    return value


def local_na(payload):
    result = reviewer(payload)
    for assessment in result['assessments']:
        if assessment['check_id'] == 'Q08':
            assessment.update(state='not_applicable', reason='No applicable local hard-constraint or shortcut probe; formal cohort gate pending',
                              evidence=['Reviewed supplied public artifacts and trace; no local probe applies'])
    return result


def test_candidate_stage_context_requires_formal_gate_only_when_configured():
    hard = candidate_difficulty_context({'diagnosis': {'difficulty_deferred': False}})
    assert hard['formal_cohort_gate']['required'] and hard['formal_cohort_gate']['status'] == 'pending'
    assert hard['formal_cohort_gate']['model'] == 'gpt-6.1-sol'
    assert hard['formal_cohort_gate']['reasoning_effort'] == 'xhigh'
    assert hard['formal_cohort_gate']['overall_pass_at_1_max'] == .2
    assert not hard['missing_future_cohort_score_is_evidence_gap']
    assert not hard['candidate_assessment_grants_publication']
    assert candidate_difficulty_context({'difficulty': {'max_rounds': 4}})['formal_cohort_gate']['required']
    for config in ({}, {'diagnosis': {'difficulty_deferred': True}},
                   {'diagnosis': {'difficulty_deferred': True}, 'difficulty': {'max_rounds': 4}}):
        assert not candidate_difficulty_context(config)['formal_cohort_gate']['required']
    assert candidate_difficulty_context({'construction': {'planning_preferences_only': {
        'financial_modeling_edit_count': [80, 400]}}})['template_complexity_contract'] == []
    with pytest.raises(ValueError, match='public constraints'):
        candidate_difficulty_context({'diagnosis': {'template_complexity_contract': {'private_path': '/tmp/private/goal.xlsx'}}})
    for value in ('Inspect /data/hzy/outputs/reference.xlsx for targets',
                  'Read ../private/goal.xlsx', 'Use outputs/runs/example/reference.xlsx',
                  'Inspect C:\\private\\goal.xlsx'):
        with pytest.raises(ValueError, match='filesystem paths'):
            candidate_difficulty_context({'diagnosis': {'template_complexity_contract': {'metric': value}}})


def test_default_all_q08_na_does_not_block_q12_and_node_passes_safe_stage_context(tmp_path):
    class Audit:
        def task(self, *args, **kwargs):
            pass
        def emit(self, *args, **kwargs):
            pass
    class Backend:
        model = 'gpt-6-sol'
        def __init__(self):
            self.payloads = []
        def complete(self, text, **kwargs):
            payload = json.loads((kwargs['workspace'] / 'evidence.json').read_text())
            self.payloads.append(payload)
            return local_na(payload)
    backend = Backend()
    source = tmp_path / 'input.xlsx'
    source.write_bytes(b'explicit file-transport fixture; no calculation claimed')
    profile = {'sheet_count': 0, 'nonempty_sheet_count': 0, 'formula_count': 0,
               'errors': [], 'external_references': [], 'sheets': []}
    ctx = TaskContext('fixture', 'fm-fixture', 'financial_modeling', source, tmp_path / 'task',
        {'project_root': str(ROOT), 'agents': {'timeout_seconds': 10},
         'diagnosis': {'difficulty_deferred': False}}, Audit(), backend, None)
    ctx.data.update(input=source, goal=source, instruction='Restore the public model.',
        public_profile=profile, profile=profile, plan={'public_rules': ['Public rule']},
        construction_validation={}, delta={}, root_impacts=[], recovery={'verified': True},
        revision_hash='fixture-revision', traces=[{'events': []}], controls=controls(),
        engine_report={'normalization_ok': True, 'recalculation_ok': True, 'stable': True})
    result = DiagnoseNode().execute(ctx)['diagnosis']
    assert set(result['enabled_check_ids']) == {f'Q{i:02d}' for i in range(1, 13)}
    assert result['assessments']['Q08']['state'] == 'not_applicable'
    assert result['difficulty_review_context']['formal_cohort_gate']['status'] == 'pending'
    assert result['assessments']['Q12']['state'] == 'clear' and result['releasable']
    public = next(p for p in backend.payloads if p['visibility'] == 'public_only')
    assert 'Q08' in public['assigned_check_ids']
    assert public['diagnostic_stage'] == 'candidate_quality'
    assert public['difficulty_review_context']['formal_cohort_gate']['status'] == 'pending'
    assert 'private' not in public and str(tmp_path) not in json.dumps(public)


@pytest.mark.parametrize('clue', ['declared hard constraint lacks measurement', 'concrete shortcut clue lacks verification'])
def test_applicable_local_probe_missing_evidence_stays_unknown_and_blocks(clue):
    def unresolved(payload):
        response = local_na(payload)
        for item in response['assessments']:
            if item['check_id'] == 'Q08':
                item.update(state='unknown', reason=clue, evidence=['specific unresolved local probe'])
        response['evidence_requests'] = [{'check_ids': ['Q08'], 'reason': clue}]
        return response
    report = DiagnosisRunner().diagnose(stage_bundle([{'metric': 'distinct_business_rules', 'minimum': 3}]),
        [], controls(), unresolved, {'difficulty_deferred': False})
    assert report['assessments']['Q08']['state'] == 'unknown'
    assert report['assessments']['Q12']['state'] == 'flagged' and not report['releasable']
    assert report['evidence_requests'] and not report['execution_failures']


def test_verified_shortcut_issue_cannot_be_hidden_by_na_assessment():
    def shortcut(payload):
        result = local_na(payload)
        if 'Q08' in payload['assigned_check_ids']:
            result['issues'] = [{'problem_id': 'Q08', 'certainty': 'confirmed', 'severity': 'blocker',
                'claim': 'Declared fixture executable shortcut solves the module', 'evidence': ['fixture executed shortcut receipt']}]
        return result
    report = DiagnosisRunner().diagnose(stage_bundle(), [], controls(), shortcut, {'difficulty_deferred': False})
    assert report['assessments']['Q08']['state'] == 'flagged' and not report['releasable']
    assert any(route['route_id'] == 'R08' for route in report['routes'])


def test_context_changes_invalidate_cached_batches_and_prompt_has_phase_rule():
    cache, calls, runner = {}, [], DiagnosisRunner()
    def review(payload):
        calls.append(payload)
        return local_na(payload)
    first = stage_bundle()
    runner.diagnose(first, [], controls(), review, {'difficulty_deferred': False}, batch_cache=cache)
    changed = deepcopy(first)
    changed['public']['difficulty_review_context']['template_complexity_contract'] = [{'metric': 'periods', 'minimum': 12}]
    runner.diagnose(changed, [], controls(), review, {'difficulty_deferred': False}, batch_cache=cache)
    assert len(calls) == 4 and all('difficulty_review_context' in p for p in calls)
    text = (ROOT / 'prompts/diagnosis.md').read_text()
    assert 'This iteration explicitly defers difficulty' not in text
    assert 'Q08 candidate-stage contract' in text and 'specific evidence request' in text


def test_candidate_na_does_not_replace_strict_confirmation(fixture_publication):
    confirmation(fixture_publication)
    path = fixture_publication['evaluation']
    evidence = json.loads(path.read_text())
    evidence['phase'] = 'candidate_quality'
    evidence['assessments'] = {'Q08': {'state': 'not_applicable', 'reason': 'formal gate pending'}}
    path.write_text(json.dumps(evidence))
    with pytest.raises(ValueError, match='completed confirmation'):
        invoke(fixture_publication, dry_run=True)
