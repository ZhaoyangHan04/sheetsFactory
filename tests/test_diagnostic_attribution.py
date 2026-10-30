from copy import deepcopy

import pytest

from sheets_factory.checkers import DiagnosisRunner
from sheets_factory.llm.schemas import diagnosis_output_schema


CONFIG = {'selection': {'include': ['Q04']}}


def finding(attribution='agent_behavior', scope=None):
    return {'problem_id': 'Q04', 'claim': 'The trial draft contains an incorrect payment.',
            'evidence': ['trial/output.xlsx Debt!C8 differs from the public policy'],
            'certainty': 'confirmed', 'severity': 'warning', 'attribution': attribution,
            'artifact_scope': scope or ['solver_output', 'solver_trace']}


def diagnose(issues, state='clear', cache=None):
    def review(payload):
        return {'assessments': {'Q04': {'state': state, 'reason': 'Reference independently checked.',
                'evidence': ['Public reconstruction and full reference cash/debt identities agree.']}},
                'issues': deepcopy(issues), 'evidence_requests': []}
    return DiagnosisRunner().diagnose({'task_id': 'fixture', 'revision_hash': 'frozen',
        'public': {}, 'private': {}}, [{'attempt_budget_exhausted': True}], {}, review,
        CONFIG, batch_cache=cache)


def test_agent_only_failure_is_retained_as_observation_without_task_route():
    report = diagnose([finding()])
    assert report['assessments']['Q04']['state'] == 'clear'
    assert report['issues'] == [] and report['routes'] == []
    assert report['releasable']
    assert report['observations'][0]['attribution'] == 'agent_behavior'
    assert report['observations'][0]['disposition'] == 'record_only'
    assert report['observations'][0]['revision_hash'] == 'frozen'


def test_agent_observation_cannot_clear_an_unsupported_unknown_check():
    report = diagnose([finding()], state='unknown')
    assert not report['releasable']
    assert report['coverage']['unknown_check_ids'] == ['Q04']
    assert report['issues'] == []


def test_flagged_agent_only_assessment_is_protocol_failure_not_automatic_clear():
    report = diagnose([finding()], state='flagged')
    assert report['assessments']['Q04']['state'] == 'unknown'
    assert report['issues'][0]['problem_id'] == 'Q11'
    assert not report['releasable']


@pytest.mark.parametrize('attribution,scope', [
    ('task_defect', ['public_instruction']),
    ('reference_defect', ['reference_goal']),
    ('environment_failure', ['runtime']),
])
def test_true_non_agent_defects_still_block(attribution, scope):
    report = diagnose([finding(attribution, scope)])
    assert report['assessments']['Q04']['state'] == 'flagged'
    assert report['issues'][0]['attribution'] == attribution
    assert not report['releasable'] and report['routes']
    assert report['routes'][0]['route_id'] == ('R11' if attribution == 'environment_failure' else 'R04')


@pytest.mark.parametrize('attribution,scope', [
    ('agent_behavior', ['solver_trace', 'reference_goal']),
    ('task_defect', ['solver_trace']),
    ('task_defect', ['unknown']),
    ('reference_defect', ['solver_output']),
    ('reference_defect', ['public_instruction']),
    ('environment_failure', ['solver_trace']),
    ('invented', ['runtime']),
])
def test_invalid_or_mixed_attribution_is_fail_closed(attribution, scope):
    report = diagnose([finding(attribution, scope)])
    assert report['assessments']['Q04']['state'] == 'unknown'
    assert report['issues'][0]['problem_id'] == 'Q11'
    assert not report['releasable']


def test_mixed_real_reference_defect_and_agent_failure_keep_reference_route():
    report = diagnose([finding(), finding('reference_defect', ['reference_goal'])])
    assert len(report['observations']) == len(report['issues']) == 1
    assert report['issues'][0]['attribution'] == 'reference_defect'
    assert report['routes'][0]['route_id'] == 'R04'
    assert not report['releasable']


def test_unresolved_attribution_routes_to_evidence_even_when_claimed_confirmed():
    report = diagnose([finding('unresolved', ['unknown'])])
    assert report['issues'][0]['certainty'] == 'suspected'
    assert report['routes'][0]['route_id'] == 'R12'
    assert not report['releasable']


def test_legacy_unattributed_issue_is_not_exempted_by_claim_text():
    issue = finding()
    issue.pop('attribution'); issue.pop('artifact_scope')
    issue['claim'] = 'An agent calculation failure, not a task defect.'
    report = diagnose([issue])
    assert report['issues'] and report['routes'][0]['route_id'] == 'R04'
    assert not report['releasable']


def test_schema_requires_structured_attribution_for_new_model_responses():
    schema = diagnosis_output_schema(['Q04'])
    issue = schema['properties']['issues']['items']
    assert {'attribution', 'artifact_scope'} <= set(issue['required'])
    assert 'agent_behavior' in issue['properties']['attribution']['enum']
    assert 'reference_goal' in issue['properties']['artifact_scope']['items']['enum']


def test_failed_batch_does_not_commit_observations_or_suppress_reference_issue():
    cache = {}
    report = diagnose([finding()], state='flagged', cache=cache)
    assert report['observations'] == []
    assert not cache['entries']
