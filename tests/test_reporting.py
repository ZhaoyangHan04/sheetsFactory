from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import unquote

import pytest
import yaml

from sheets_factory.core.audit import AuditStore
from sheets_factory.reporting import billing_window, generate_report, summarize_usage, write_reports, markdown_report


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


def test_resumed_live_elapsed_and_producer_phases_are_separate_with_offsets(tmp_path):
    root, run, audit = fixture_run(tmp_path)
    audit.update_run(status='constructing', producer_active=True, resume_count=1,
                     started_at='2026-10-29T20:00:00+08:00',
                     resumed_at='2026-10-29T12:09:00Z',
                     execution_phase_started_at='2026-10-29T20:10:00+08:00',
                     finished_at='2026-10-29T12:05:00Z',
                     wall_seconds=None, previous_wall_seconds=90)
    report = generate_report(run, project_root=root, now=datetime(2026, 10, 29, 12, 15, tzinfo=timezone.utc))
    timing = report['timing']
    assert timing['end_to_end_elapsed_seconds'] == 900
    assert timing['end_to_end_elapsed_status'] == 'live'
    assert timing['end_to_end_elapsed_ended_at'] == report['generated_at']
    assert timing['active_producer_cumulative_phase_seconds'] == 390
    assert timing['active_producer_cumulative_phase_status'] == 'live'
    assert timing['wall_seconds'] == 390  # Legacy field remains available.
    assert timing['time_measures_additive'] is False
    text = markdown_report(report)
    assert '端到端经过时间：900.00 秒' in text
    assert 'Producer 活跃阶段累计：390.00 秒' in text
    assert '正式运行墙钟' not in text


@pytest.mark.parametrize('status', ['completed', 'cancelled', 'interrupted'])
def test_stopped_elapsed_uses_finish_and_does_not_grow_producer_time(tmp_path, status):
    root, run, audit = fixture_run(tmp_path)
    audit.update_run(status=status, producer_active=False, wall_seconds=100,
                     execution_phase_started_at='2026-10-29T12:00:00Z',
                     finished_at='2026-10-29T20:05:00+08:00')
    report = generate_report(run, project_root=root, now=datetime(2026, 10, 29, 13, tzinfo=timezone.utc))
    timing = report['timing']
    assert timing['end_to_end_elapsed_seconds'] == 300
    assert timing['end_to_end_elapsed_status'] == 'known'
    assert timing['active_producer_cumulative_phase_seconds'] == 100
    assert timing['active_producer_cumulative_phase_status'] == 'known'
    assert not report['run']['is_live_snapshot']


@pytest.mark.parametrize('finished_at', [None, 'invalid', '2026-10-29T11:59:00Z'])
def test_missing_or_invalid_terminal_finish_stays_unknown(tmp_path, finished_at):
    root, run, audit = fixture_run(tmp_path)
    audit.update_run(status='failed', producer_active=False, finished_at=finished_at)
    timing = generate_report(run, project_root=root)['timing']
    assert timing['end_to_end_elapsed_seconds'] is None
    assert timing['end_to_end_elapsed_status'] == 'unknown'
    assert timing['active_producer_cumulative_phase_seconds'] == 100


def test_live_resumption_with_unknown_prior_duration_does_not_assume_zero(tmp_path):
    root, run, audit = fixture_run(tmp_path)
    audit.update_run(status='constructing', producer_active=True, resume_count=1,
                     wall_seconds=None, previous_wall_seconds=None,
                     execution_phase_started_at='2026-10-29T12:10:00Z')
    timing = generate_report(run, project_root=root,
                             now=datetime(2026, 10, 29, 12, 15, tzinfo=timezone.utc))['timing']
    assert timing['end_to_end_elapsed_seconds'] == 900
    assert timing['active_producer_cumulative_phase_seconds'] is None
    assert timing['active_producer_cumulative_phase_status'] == 'unknown'
    assert timing['active_producer_cumulative_phase_scope'] == 'unknown_previous_phase_seconds'


def test_initial_live_phase_uses_its_own_start_and_does_not_sum_preparation(tmp_path):
    root, run, audit = fixture_run(tmp_path)
    audit.update_run(status='constructing', producer_active=True, wall_seconds=None,
                     execution_phase_started_at='2026-10-29T12:01:00Z')
    timing = generate_report(run, project_root=root,
                             now=datetime(2026, 10, 29, 12, 2, tzinfo=timezone.utc))['timing']
    assert timing['end_to_end_elapsed_seconds'] == 120
    assert timing['active_producer_cumulative_phase_seconds'] == 60
    assert timing['preparation_cumulative_seconds'] == 619.22
    assert timing['cumulative_node_seconds'] == 12
    audit.update_run(started_at=None, execution_phase_started_at=None)
    unknown = generate_report(run, project_root=root)['timing']
    assert unknown['end_to_end_elapsed_seconds'] is None
    assert unknown['active_producer_cumulative_phase_seconds'] is None


def test_terminal_resumption_does_not_use_a_stale_previous_finish(tmp_path):
    root, run, audit = fixture_run(tmp_path)
    audit.update_run(status='completed', producer_active=False, resume_count=1,
                     resumed_at='2026-10-29T12:09:00Z',
                     execution_phase_started_at='2026-10-29T12:10:00Z',
                     finished_at='2026-10-29T12:05:00Z')
    timing = generate_report(run, project_root=root)['timing']
    assert timing['end_to_end_elapsed_seconds'] is None
    assert timing['end_to_end_elapsed_scope'] == 'unknown_invalid_or_stale_end_timestamp'
    assert timing['active_producer_cumulative_phase_seconds'] == 100


def test_inactive_interruption_without_finish_does_not_become_a_live_snapshot(tmp_path):
    root, run, audit = fixture_run(tmp_path)
    audit.update_run(status='constructing', producer_active=False, wall_seconds=None,
                     execution_phase_started_at='2026-10-29T12:00:00Z')
    audit.emit('llm.started', call_id='interrupted-call', role='trace_agent')
    report = generate_report(run, project_root=root,
                             now=datetime(2026, 10, 29, 13, tzinfo=timezone.utc))
    assert report['timing']['end_to_end_elapsed_seconds'] is None
    assert report['timing']['active_producer_cumulative_phase_seconds'] is None
    assert report['tokens']['active_call_count'] == 0
    assert report['tokens']['completion_missing_count'] == 1
    assert '中断或暂停快照' in markdown_report(report)


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
    assert any('最初一段' in note and '此后' in note for note in result['notes'])


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
    assert '端到端经过秒数' in html and 'Producer 活跃阶段累计秒数' in html
    assert audit.snapshot()['tasks'] == before
    assert Path(result['paths']['json']).is_file()


def test_prompt_amendment_and_continuation_are_visible_in_final_metadata(tmp_path):
    root, run, audit = fixture_run(tmp_path)
    payload = {'kind': 'prompt_context_clarification', 'file': 'prompts/diagnosis.md',
               'before_sha256': 'old-hash', 'after_sha256': 'new-hash',
               'reason': 'Clarify temporary workspace versus final Harbor path', 'requires_final_review': True}
    audit.db.execute('INSERT INTO events(timestamp,kind,payload) VALUES (?,?,?)',
                     ('2026-10-29T12:26:00Z', 'run.amended', json.dumps(payload)))
    audit.db.commit()
    audit.emit('run.resumed', preserved_task_count=3, previous_code_revision='phase1', current_code_revision='phase2')
    result = write_reports(run, project_root=root)
    event = result['report']['change_history']['amendments'][0]
    assert event['kind'] == 'run.amended'
    assert event['payload_kind'] == 'prompt_context_clarification'
    text = Path(result['paths']['markdown']).read_text()
    assert 'old-hash' in text and 'new-hash' in text and '同一运行续跑' in text


def test_progress_report_includes_active_started_calls_as_unknown_usage(tmp_path):
    root, run, audit = fixture_run(tmp_path)
    audit.update_run(status='constructing')
    audit.emit('llm.started', call_id='active-call', role='trace_agent', stage='trajectory',
               started_at='2026-10-29T12:01:00Z')
    report = generate_report(run, project_root=root, now=datetime(2026, 10, 29, 12, 2, tzinfo=timezone.utc))
    assert report['tokens']['call_count'] == 2
    assert report['tokens']['recorded_call_count'] == 1
    assert report['tokens']['active_call_count'] == 1
    assert report['tokens']['unknown_core_usage_calls'] == 1
    assert report['tokens']['known_total_tokens'] == 130
    assert not report['tokens']['exact_total_available']
    text = markdown_report(report)
    assert '进度快照' in text and '活动调用 1 次' in text
    assert report['stages']['trajectory']['unknown_core_usage_calls'] == 1


def test_finished_orphan_calls_stay_unknown_and_existing_records_deduplicate(tmp_path):
    root, run, audit = fixture_run(tmp_path)
    audit.emit('llm.started', call_id='formal-call', role='planner')
    audit.emit('llm.started', call_id='orphan-call', role='trace_agent')
    report = generate_report(run, project_root=root)
    assert report['tokens']['call_count'] == 2
    assert report['tokens']['completion_missing_count'] == 1
    assert report['tokens']['active_call_count'] == 0
    assert report['tokens']['unknown_core_usage_calls'] == 1
    assert '结束运行报告' in markdown_report(report)


def test_phase_table_matches_totals_and_excludes_active_node_duration(tmp_path):
    root, run, audit = fixture_run(tmp_path)
    audit.record('nodes', {'node': 'plan', 'status': 'running', 'duration_ms': 999999,
                          'started_at': '2026-10-29T12:00:00Z'})
    audit.record('calls', {'call_id': 'plan-call', 'stage': 'plan', 'role': 'planner',
                         'input_tokens': 50, 'cached_input_tokens': 20, 'output_tokens': 5})
    report = generate_report(run, project_root=root, now=datetime(2026, 10, 29, 12, 0, 10, tzinfo=timezone.utc))
    assert report['stages']['plan']['known_total_tokens'] == 55
    assert report['stages']['plan']['cached_input_tokens_known'] == 20
    assert report['stages']['plan']['completed_cumulative_seconds'] == 0
    assert report['stages']['plan']['active_elapsed_seconds'] == 10
    assert sum(stage['known_total_tokens'] for stage in report['stages'].values()) == report['tokens']['known_total_tokens']
    assert report['timing']['cumulative_node_seconds'] == 12
    assert '完成累计秒数' in markdown_report(report)


def test_public_artifact_links_and_titles_are_safe_and_relative(tmp_path):
    root, run, audit = fixture_run(tmp_path)
    revision = run / 'tasks/fm-a/revisions/000'
    public = revision / 'public'
    public.mkdir()
    (public / 'instruction.md').write_text('Complete the public financial model.')
    (revision / 'private/plan.json').write_text(json.dumps({'title': '<img onerror="bad"> Forecast revenue'}))
    secret = root / '.secrets/api_key'
    secret.parent.mkdir()
    secret.write_text('do-not-expose-this')
    (public / 'input.xlsx').symlink_to(secret)
    safe_result = run / 'harbor_control_jobs/oracle/result.json'
    safe_result.parent.mkdir(parents=True)
    safe_result.write_text('{}')
    private_result = revision / 'private/result.json'
    private_result.write_text('{}')
    controls = json.loads((run / 'harbor_controls.json').read_text())
    controls['per_task']['sheetsfactory/fm-a']['oracle']['result_file'] = str(safe_result)
    controls['per_task']['sheetsfactory/fm-a']['nop']['result_file'] = str(private_result)
    (run / 'harbor_controls.json').write_text(json.dumps(controls))
    output = tmp_path / 'deliverables'
    result = write_reports(run, output_dir=output, project_root=root)
    html = Path(result['paths']['html']).read_text()
    assert '<img onerror=' not in html
    assert '&lt;img onerror=' in html
    assert 'Forecast revenue' in html
    hrefs = re.findall(r'<a href="([^"]+)"', html)
    targets = {(output / unquote(href)).resolve() for href in hrefs}
    assert (public / 'instruction.md').resolve() in targets
    assert safe_result.resolve() in targets
    assert secret.resolve() not in targets
    assert private_result.resolve() not in targets
    assert all('file:' not in href and 'https:' not in href and '.secrets' not in href and '/private/' not in href for href in hrefs)
    assert 'do-not-expose-this' not in html
    assert '待 Harbor 验证' in html and 'Financial Modeling' in html and 'Debugging' in html


def billing_log_summary(run, dollars=8.654836):
    directory = run / 'private/billing_snapshots'
    directory.mkdir(parents=True, exist_ok=True)
    totals = {'requests': 287, 'quota': 4327418, 'usd': dollars,
              'prompt_tokens': 9658486, 'completion_tokens': 251621, 'cache_read_tokens': 7321344,
              'api_key': 'private-ledger-secret'}
    record = {
        'attribution': 'shared_api_key_created_at_window_not_exact_run_attribution',
        'window': {'start': '2026-10-29T12:11:33Z', 'end_exclusive': '2026-10-29T12:55:58Z'},
        'quota_per_usd': 500000, 'totals': totals, 'by_model': {'gpt-6-sol': totals},
        'coverage': {'observed_intervals_cover_window': True, 'exact_billing_completeness_certified': False,
                     'in_flight_or_delayed_logs_may_be_missing': True, 'raw': 'private-ledger-secret'},
        'capture': {'captured_at': '2026-10-29T12:56:00Z', 'duration_seconds': 1.8,
                    'snapshots': 3, 'unique_ledger_events': 1101, 'api_key': 'private-ledger-secret'},
        'ledger': [{'request_id': 'private-ledger-secret'}], 'api_key': 'private-ledger-secret',
    }
    (directory / 'summary.json').write_text(json.dumps(record))
    (directory / 'ledger.json').write_text('private-ledger-secret')


def test_request_log_cost_is_available_without_end_snapshot_and_only_allowlisted_aggregates_export(tmp_path):
    root, run, audit = fixture_run(tmp_path)
    billing_log_summary(run)
    report = generate_report(run, project_root=root)
    billing = report['billing']
    logs = billing['request_log_window']
    assert billing['cost_usd'] is None
    assert logs['status'] == 'measured_request_log_window'
    assert logs['totals']['usd'] == 8.654836
    assert logs['totals']['requests'] == 287
    assert billing['production_cost_usd'] is None and logs['production_cost_usd'] is None
    assert billing['methods_additive'] is False
    assert logs['coverage']['exact_billing_completeness_certified'] is False
    assert logs['capture']['snapshots'] == 3
    assert 'private-ledger-secret' not in json.dumps(report)
    result = write_reports(run, project_root=root)
    for name in ['html', 'markdown']:
        text = Path(result['paths'][name]).read_text()
        assert '$8.654836' in text
        assert '不能相加' in text
        assert 'created_at' in text and 'pilot' in text
        assert '未' in text and '结算' in text
        assert 'private-ledger-secret' not in text


def test_snapshot_delta_and_request_window_costs_remain_separate(tmp_path):
    root, run, audit = fixture_run(tmp_path)
    billing_log_summary(run)
    private = run / 'private'
    (private / 'billing_start.json').write_text(json.dumps(snapshot(1000000, '2026-10-29T12:00:00Z')))
    (private / 'billing_end.json').write_text(json.dumps(snapshot(1250000, '2026-10-29T12:10:00Z')))
    report = generate_report(run, project_root=root)
    assert report['billing']['cost_usd'] == .5
    assert report['billing']['request_log_window']['totals']['usd'] == 8.654836
    assert report['billing']['production_cost_usd'] is None
    text = markdown_report(report)
    assert '$0.500000' in text and '$8.654836' in text
    assert '方法一' in text and '方法二' in text
    assert '$9.154836' not in text


def test_inconsistent_request_summary_usd_is_not_reported_as_measured_cost(tmp_path):
    root, run, audit = fixture_run(tmp_path)
    billing_log_summary(run, dollars=999)
    logs = generate_report(run, project_root=root)['billing']['request_log_window']
    assert logs['status'] == 'summary_available_cost_unknown'
    assert logs['totals']['usd'] is None
    assert logs['by_model']['gpt-6-sol']['usd'] is None
    assert any('不一致' in note for note in logs['notes'])
