"""Offline diagnostics reliability: protocol failures are infrastructure, not business defects."""
from copy import deepcopy
from pathlib import Path

import pytest

from sheets_factory.checkers import DiagnosisRunner
from sheets_factory.core.audit import AuditStore
from sheets_factory.pipelines.factory import FactoryPipeline, diagnostic_action

ROOT = Path(__file__).resolve().parents[1]
CONFIG = {'difficulty_deferred': True}
CONTROLS = {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}


def bundle():
    return {'task_id': 'fixture', 'revision': 0, 'revision_hash': 'r0',
        'public': {'instruction': 'Use the public forecast rule.', 'input_sha256': 'input0'},
        'private': {'expected_delta': ['Forecast!A1'], 'goal_sha256': 'goal0'},
        'reviewer_context_hash': 'prompt-and-model0',
        'engine_report': {'normalization_ok': True, 'recalculation_ok': True, 'stable': True},
        'infrastructure_health_report': {'healthy': True, 'checks': ['explicit fixture backend probe']}}


def clear(payload):
    return {'assessments': {check: {'state': 'clear', 'reason': 'Checked fixture rule and cells',
        'evidence': ['independent fixture probe']} for check in payload['assigned_check_ids']},
        'issues': [], 'evidence_requests': []}


@pytest.mark.parametrize('failure', ['timeout', 'missing_Q09'])
def test_failed_private_batch_routes_infra_and_retries_without_repeating_public(failure):
    runner, cache, calls = DiagnosisRunner(), {}, []
    def first(payload):
        calls.append(payload['visibility'])
        if payload['visibility'] == 'public_only':
            return clear(payload)
        if failure == 'timeout':
            raise TimeoutError('600-second private reviewer execution timeout')
        result = clear(payload)
        del result['assessments']['Q09']
        return result
    report = runner.diagnose(bundle(), [], CONTROLS, first, CONFIG, batch_cache=cache)
    assert len(report['assessments']) == 12
    assert report['assessments']['Q09']['state'] == 'unknown'
    assert report['assessments']['Q09']['execution_status'] == 'failed'
    assert report['assessments']['Q11']['state'] == 'flagged'
    assert report['assessments']['Q12']['state'] == 'flagged'
    assert diagnostic_action(report)[0] == 'infrastructure_retry'
    assert all(issue['problem_id'] in {'Q11', 'Q12'} for issue in report['issues'])
    assert report['execution_failures'][0]['fault_stage'] == 'diagnose'
    def success(payload):
        calls.append(payload['visibility'])
        return clear(payload)
    retry = runner.diagnose(bundle(), [], CONTROLS, success, CONFIG, batch_cache=cache)
    assert retry['diagnostic_run_id'] != report['diagnostic_run_id']
    assert calls == ['public_only', 'review', 'review']
    assert retry['llm_batches'][0]['cache_hit'] is True
    assert retry['llm_batches'][1]['cache_hit'] is False
    assert retry['releasable'] and not retry['execution_failures']
    assert retry['assessments']['Q12']['state'] == 'clear'
    runner.diagnose(bundle(), [], CONTROLS,
        lambda _: pytest.fail('Every identical successful batch should now be cached'), CONFIG, batch_cache=cache)


def test_private_payload_changes_invalidate_only_private_but_trace_or_prompt_changes_invalidate_both():
    runner, cache, calls = DiagnosisRunner(), {}, []
    def review(payload):
        calls.append(payload['visibility'])
        return clear(payload)
    original = bundle()
    runner.diagnose(original, [], CONTROLS, review, CONFIG, batch_cache=cache)
    changed = deepcopy(original)
    changed['private']['goal_sha256'] = 'different-goal-even-with-same-public-input'
    runner.diagnose(changed, [], CONTROLS, review, CONFIG, batch_cache=cache)
    assert calls == ['public_only', 'review', 'review']
    runner.diagnose(changed, [{'events': [{'kind': 'new relevant source probe'}]}], CONTROLS,
                    review, CONFIG, batch_cache=cache)
    assert calls[-2:] == ['public_only', 'review']
    changed['reviewer_context_hash'] = 'changed-prompt-model-or-schema'
    runner.diagnose(changed, [], CONTROLS, review, CONFIG, batch_cache=cache)
    assert calls[-2:] == ['public_only', 'review']
    assert len(calls) == 7


def test_revision_and_check_selection_are_part_of_cache_identity():
    runner, cache, calls = DiagnosisRunner(), {}, []
    def review(payload):
        calls.append(payload['assigned_check_ids'])
        return clear(payload)
    original = bundle()
    runner.diagnose(original, [], CONTROLS, review, CONFIG, batch_cache=cache)
    changed = deepcopy(original)
    changed['revision'] = 1  # Even identical hash must not reuse another revision's conclusions.
    runner.diagnose(changed, [], CONTROLS, review, CONFIG, batch_cache=cache)
    runner.diagnose(changed, [], CONTROLS, review, {'selection': {'include': ['Q02']}}, batch_cache=cache)
    assert len(calls) == 5 and calls[-1] == ['Q02']


def test_semantic_unknown_and_suspected_remain_evidence_probes_and_are_not_cached():
    runner, cache, calls = DiagnosisRunner(), {}, []
    config = {'selection': {'include': ['Q01']}}
    def unknown(payload):
        calls.append('unknown')
        return {'assessments': {'Q01': {'state': 'unknown', 'reason': 'Need a targeted source probe',
                                        'evidence': []}}, 'issues': []}
    report = runner.diagnose(bundle(), [], {}, unknown, config, batch_cache=cache)
    assert diagnostic_action(report)[0] == 'evidence' and not report['execution_failures']
    runner.diagnose(bundle(), [], {}, unknown, config, batch_cache=cache)
    assert calls == ['unknown', 'unknown'] and not cache['entries']
    def suspected(payload):
        calls.append('suspected')
        return {'assessments': {'Q01': {'state': 'flagged', 'reason': 'Uncertain source interpretation',
                                       'evidence': ['needs independent source check']}},
            'issues': [{'problem_id': 'Q01', 'certainty': 'suspected', 'severity': 'blocker',
                       'claim': 'Possible ambiguity', 'evidence': ['unresolved public observation']}]}
    report = runner.diagnose(bundle(), [], {}, suspected, config, batch_cache=cache)
    assert diagnostic_action(report)[0] == 'evidence' and not report['execution_failures']
    runner.diagnose(bundle(), [], {}, suspected, config, batch_cache=cache)
    assert calls[-2:] == ['suspected', 'suspected'] and not cache['entries']


def test_diagnostic_backend_failures_use_two_diagnose_only_retries_without_content_or_evidence_reset(tmp_path):
    audit = AuditStore(tmp_path / 'run', {'id': 'r'})
    config = {'project_root': str(ROOT), 'run_dir': str(tmp_path / 'run'), 'run': {
        'targets': {'debugging': 1}, 'max_steps': 3,
        'infrastructure_retries_per_stage': 2, 'max_evidence_rounds_per_revision': 2}}
    pipeline = FactoryPipeline(config, audit, None, None)
    seen = []
    def phase(ctx, name):
        seen.append((name, ctx.revision))
        ctx.audit.task(ctx.task_id, revision=ctx.revision)  # BaseNode bookkeeping in this controller stub.
        if name == 'preparation':
            ctx.data.update(plan={'edits': [{'sheet': 'Forecast', 'cell': 'A1'}]}, source_id='a' * 64)
        elif name in {'revision', 'diagnosis_retry'}:
            ctx.data['diagnosis'] = {'issues': [{'issue_id': 'diagnosis-timeout', 'problem_id': 'Q11',
                'certainty': 'confirmed', 'fault_stage': 'diagnose'}], 'routes': [{'issue_id': 'diagnosis-timeout',
                'route_class': 'infrastructure_retry'}], 'releasable': False}
        else:
            pytest.fail('A diagnostic outage must not rerun recovery, trajectories or content repair')
    pipeline.run_phase = phase
    pipeline.process_task({'sha256': 'a' * 64, 'local_path': '/not-read/by-offline-controller.xls'}, 'debugging')
    assert seen == [('preparation', 0), ('revision', 0), ('diagnosis_retry', 0), ('diagnosis_retry', 0)]
    task = audit.snapshot()['tasks'][0]
    assert task['status'] == 'rejected' and 'INFRA_FAILED' in task['error']
    assert task['revision'] == task['content_repairs'] == 0
    assert task['infrastructure_retries'] == 2 and task['evidence_rounds'] == 0


def test_diagnose_node_passes_strict_schema_and_keeps_successful_batch_across_retry(tmp_path):
    import json
    from openpyxl import Workbook
    from sheets_factory.core.node import TaskContext
    from sheets_factory.nodes.quality import DiagnoseNode
    source, goal = tmp_path / 'input.xlsx', tmp_path / 'goal.xlsx'
    book = Workbook()
    book.active['A1'] = 'Fixture only: no spreadsheet calculation is asserted in this test.'
    book.save(source)
    book.save(goal)
    calls = []
    class Backend:
        model = 'fixture-offline-no-api'
        def complete(self, text, **kwargs):
            payload = json.loads((kwargs['workspace'] / 'evidence.json').read_text())
            schema = kwargs['output_schema']
            assert set(schema['properties']['assessments']['required']) == set(payload['assigned_check_ids'])
            assert schema['properties']['assessments']['additionalProperties'] is False
            assert 'assessments as an object' in text
            calls.append(payload['visibility'])
            if calls == ['public_only', 'review']:
                raise TimeoutError('Explicit fake private-backend timeout')
            return clear(payload)
    class Audit:
        def task(self, *args, **kwargs): pass
        def emit(self, *args, **kwargs): pass
    config = {'project_root': str(ROOT), 'run': {'max_steps': 3},
        'agents': {'model': 'fixture-offline-no-api', 'reasoning_effort': 'high', 'timeout_seconds': 1},
        'diagnosis': CONFIG}
    ctx = TaskContext('run', 'fixture', 'debugging', source, tmp_path / 'task', config, Audit(), Backend(), None)
    profile = {'sheet_count': 1, 'nonempty_sheet_count': 1, 'formula_count': 0,
               'errors': [], 'external_references': [], 'sheets': []}
    ctx.data.update(input=source, goal=goal, instruction='Use the fixture public rules.',
        public_profile=profile, profile=profile, plan={'public_rules': ['Fixture public rule.']},
        construction_validation={}, delta={'expected_changes': []}, root_impacts=[],
        recovery={'verified': True}, traces=[], controls=CONTROLS, revision_hash='r0',
        engine_report={'normalization_ok': True, 'recalculation_ok': True, 'stable': True})
    first = DiagnoseNode().execute(ctx)['diagnosis']
    assert diagnostic_action(first)[0] == 'infrastructure_retry'
    retry = DiagnoseNode().execute(ctx)['diagnosis']
    assert calls == ['public_only', 'review', 'review']
    assert retry['llm_batches'][0]['cache_hit'] and retry['releasable']
    assert (ctx.revision_dir / 'private/diagnostic_batch_cache.json').is_file()
