from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import pytest
import yaml

from sheets_factory.core.audit import AuditStore
from sheets_factory.reporting import billing_window, generate_report, summarize_usage, write_reports


def fixture_run(tmp_path):
    root = tmp_path / 'project'
    run = root / 'outputs/runs/fixture'
    manifests = root / 'data/manifests'
    manifests.mkdir(parents=True)
    (manifests / 'euses_financial.json').write_text(json.dumps({
        'unique_workbooks_inspected': 720, 'selected_count': 70, 'eligible_count': 99,
        'archive_sha256': 'archivehash', 'download_url': 'https://example.test/financial.zip'}))
    (manifests / 'source_preparation_usage.json').write_text(json.dumps({'all_source_preparation': {
        'attempted_unique_sources': 70, 'readable_profiled': 68, 'zero_cached_errors': 57,
        'normalization_and_profile_cumulative_seconds': 619.22, 'first_survey_wall_seconds': None}}))
    audit = AuditStore(run, {'id': 'fixture', 'status': 'completed', 'wall_seconds': 100,
        'started_at': '2026-10-29T12:00:00+00:00', 'financial_target': 20, 'debugging_target': 20,
        'difficulty_status': 'deferred', 'model': 'gpt-6-sol', 'reasoning_effort': 'high'})
    (run / 'resolved_config.yaml').write_text(yaml.safe_dump({'run': {
        'seed_manifest': 'data/manifests/euses_financial.json',
        'targets': {'financial_modeling': 20, 'debugging': 20}}}))
    for task_id, source, mode, status in [('fm-a', 'source-a', 'financial_modeling', 'qualified'),
                                         ('dbg-a', 'source-a', 'debugging', 'qualified'),
                                         ('fm-b', 'source-b', 'financial_modeling', 'rejected')]:
        audit.task(task_id, source_id=source, mode=mode, status=status, revision=0,
                   error='Q01/Q02: missing rules' if status == 'rejected' else None)
        audit.record('nodes', {'task_id': task_id, 'node': 'construct', 'duration_ms': 4000, 'status': 'completed'})
        private = run / 'tasks' / task_id / 'revisions/000/private'
        private.mkdir(parents=True)
        (private / 'independent_recovery.json').write_text(json.dumps({
            'verified': True, 'public_information_only': True, 'replay': {'returncode': 0}, 'comparison': {'reward': 1}}))
        (private / 'diagnosis.json').write_text(json.dumps({'releasable': True, 'scope': 'all',
            'enabled_check_ids': ['Q01'], 'assessments': {'Q01': {'state': 'clear'}}, 'issues': []}))
    controls = {'per_task': {f'sheetsfactory/{name}': {
        'oracle': {'reward': 1.0, 'matched': True, 'exception_info': None},
        'nop': {'reward': 0.0, 'matched': True, 'exception_info': None}} for name in ['fm-a', 'dbg-a']}}
    (run / 'harbor_controls.json').write_text(json.dumps(controls))
    audit.record('calls', {'call_id': 'formal-call', 'role': 'planner', 'status': 'completed', 'duration_ms': 1000,
        'usage': {'input_tokens': 100, 'cached_input_tokens': 40, 'output_tokens': 30, 'reasoning_output_tokens': 20}})
    return root, run, audit


def test_distinct_denominators_and_no_double_counting(tmp_path):
    root, run, audit = fixture_run(tmp_path)
    report = generate_report(run, project_root=root)
    assert report['sources']['archive_scanned'] == 720
    assert report['sources']['selected_seed_pool'] == 70
    assert report['sources']['preparation_attempted'] == 70
    assert report['sources']['construction_attempted_unique_seeds'] == 2
    assert report['sources']['productive_unique_seeds'] == 1
    assert report['yield']['verified_qualified'] == 2
    assert report['yield']['candidate_conversion'] == pytest.approx(2 / 3)
    assert report['yield']['productive_source_conversion'] == 0.5
    assert report['yield']['tasks_per_used_seed'] == 1
    assert not report['run']['target_met']
    assert report['tokens']['known_total_tokens'] == 130
    assert report['tokens']['fields']['cached_input_tokens']['known_sum'] == 40
    assert report['tokens']['fields']['reasoning_output_tokens']['known_sum'] == 20
    assert report['timing']['wall_seconds'] == 100
    assert report['timing']['cumulative_node_seconds'] == 12
    assert report['diagnostics']['rejected_candidates_by_reason'] == {'Q01': 1, 'Q02': 1}
    assert report['run']['started_at_shanghai'].startswith('2026-10-29 20:00:00')


def test_missing_recovery_or_harbor_exception_cannot_claim_verified_quantity(tmp_path):
    root, run, audit = fixture_run(tmp_path)
    (run / 'tasks/fm-a/revisions/000/private/independent_recovery.json').unlink()
    controls = json.loads((run / 'harbor_controls.json').read_text())
    controls['per_task']['sheetsfactory/dbg-a']['oracle']['exception_info'] = {'exception_type': 'RuntimeError'}
    (run / 'harbor_controls.json').write_text(json.dumps(controls))
    report = generate_report(run, project_root=root)
    assert report['yield']['reported_qualified'] == 2
    assert report['yield']['verified_qualified'] == 0
    assert len(report['consistency_warnings']) == 2


def test_missing_diagnosis_is_not_silently_certified(tmp_path):
    root, run, audit = fixture_run(tmp_path)
    (run / 'tasks/fm-a/revisions/000/private/diagnosis.json').unlink()
    assert generate_report(run, project_root=root)['yield']['verified_qualified'] == 1


def test_unknown_usage_stays_unknown_and_cached_subsets_are_not_added():
    report = summarize_usage([{'usage': {'input_tokens': 100, 'output_tokens': 25,
        'input_tokens_details': {'cached_tokens': 60}, 'output_tokens_details': {'reasoning_tokens': 15}}},
        {'status': 'cancelled', 'usage': None}])
    assert report['known_total_tokens'] == 125
    assert not report['exact_total_available']
    assert report['unknown_core_usage_calls'] == 1
    assert report['fields']['cached_input_tokens']['unknown_call_count'] == 1


def snapshot(used, captured, unit=500000):
    return {'captured_at': captured, 'usage': {'data': {'total_used': used}},
            'currency_metadata': {'quota_per_unit': unit, 'quota_display_type': 'USD', 'usd_exchange_rate': 7.3}}


def test_gateway_quota_delta_is_not_production_cost(tmp_path):
    private = tmp_path / 'private'
    private.mkdir()
    (private / 'billing_start.json').write_text(json.dumps(snapshot(1000000, '2026-10-29T12:00:10+00:00')))
    (private / 'billing_end.json').write_text(json.dumps(snapshot(1250000, '2026-10-29T12:10:00+00:00')))
    (private / 'billing_context.json').write_text(json.dumps({'overlap_ended_at': '2026-10-29T12:14:00+00:00'}))
    result = billing_window(tmp_path, {'started_at': '2026-10-29T12:00:00+00:00'},
                            '包含工程试跑及取消请求，不能归因正式运行。')
    assert result['quota_delta'] == 250000
    assert result['cost_usd'] == 0.5
    assert result['production_cost_usd'] is None
    assert result['scope'] == 'credential_time_window_only'
    assert any('10.0 秒' in note for note in result['notes'])
    assert any('20:14:00' in note for note in result['notes'])


def test_inconsistent_billing_unit_or_missing_end_does_not_invent_cost(tmp_path):
    private = tmp_path / 'private'
    private.mkdir()
    (private / 'billing_start.json').write_text(json.dumps(snapshot(1, '2026-10-29T12:00:00Z')))
    assert billing_window(tmp_path, {})['cost_usd'] is None
    (private / 'billing_end.json').write_text(json.dumps(snapshot(2, '2026-10-29T12:01:00Z', 100000)))
    assert billing_window(tmp_path, {})['status'] == 'invalid_or_unsupported_snapshot'


def test_engineering_usage_is_separate_and_deduplicated(tmp_path):
    root, run, audit = fixture_run(tmp_path)
    extra = tmp_path / 'engineering'
    for folder, call_id in [('a', 'formal-call'), ('b', 'engineering-call'), ('c', 'engineering-call')]:
        path = extra / folder
        path.mkdir(parents=True)
        (path / 'result.json').write_text(json.dumps({'call_id': call_id, 'model': 'gpt-6-sol',
            'usage': {'input_tokens': 10, 'output_tokens': 5}}))
    report = generate_report(run, project_root=root, engineering_dirs=[extra])
    assert report['tokens']['known_total_tokens'] == 130
    assert report['engineering_usage']['usage']['call_count'] == 1
    assert report['engineering_usage']['usage']['known_total_tokens'] == 15


def test_reports_are_portable_escape_untrusted_text_and_do_not_change_state(tmp_path):
    root, run, audit = fixture_run(tmp_path)
    audit.task('fm-b', error='<script>alert("x")</script> | bad')
    before = audit.snapshot()['tasks']
    result = write_reports(run, project_root=root)
    html = Path(result['paths']['html']).read_text()
    markdown = Path(result['paths']['markdown']).read_text()
    assert '<script>alert("x")</script>' not in html
    assert '&lt;script&gt;alert' in html
    assert '<link ' not in html and '<script src=' not in html
    assert '\\| bad' in markdown
    assert '难度' in markdown and '未知' in markdown
    assert audit.snapshot()['tasks'] == before
    assert Path(result['paths']['json']).is_file()
