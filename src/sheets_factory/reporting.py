"""Read-only run accounting and portable Chinese reports.

Reports never update task state or infer model cost from undocumented prices.
Provider-reported token subsets and credential-wide billing stay separate.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html import escape
import json
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo

import yaml


MODES = {'financial_modeling': 'Financial Modeling', 'debugging': 'Debugging'}


def _read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _instant(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _display_time(value):
    parsed = _instant(value)
    return parsed.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S +08:00') if parsed else None


def read_run(run_dir):
    """Read one SQLite transaction without changing the authoritative audit."""
    path = Path(run_dir).resolve() / 'run.sqlite'
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    connection.execute('PRAGMA query_only=ON')
    connection.execute('BEGIN')
    try:
        row = connection.execute("SELECT value FROM state WHERE key='run'").fetchone()
        result = {'run': json.loads(row[0]) if row else {}}
        for name in ('tasks', 'nodes', 'calls'):
            result[name] = [json.loads(row[0]) for row in connection.execute(f'SELECT payload FROM {name} ORDER BY rowid')]
        result['events'] = [{'id': row[0], 'timestamp': row[1], 'kind': row[2], **json.loads(row[3])}
            for row in connection.execute("SELECT id,timestamp,kind,payload FROM events WHERE kind IN "
                "('checker.result','task.revised','task.rejected','run.finished') ORDER BY id")]
        return result
    finally:
        connection.rollback()
        connection.close()


def _usage_value(call, name):
    aliases = {
        'input_tokens': ('input_tokens', 'prompt_tokens'),
        'cached_input_tokens': ('cached_input_tokens', 'cache_read_input_tokens'),
        'output_tokens': ('output_tokens', 'completion_tokens'),
        'reasoning_output_tokens': ('reasoning_output_tokens', 'reasoning_tokens'),
    }
    usage = call.get('usage') or {}
    for source in (call, usage):
        for key in aliases[name]:
            value = source.get(key)
            if _number(value) and value >= 0:
                return value
    details = usage.get('input_tokens_details' if name == 'cached_input_tokens' else 'output_tokens_details') or {}
    fallback = details.get('cached_tokens' if name == 'cached_input_tokens' else 'reasoning_tokens')
    if name in {'cached_input_tokens', 'reasoning_output_tokens'} and _number(fallback) and fallback >= 0:
        return fallback
    return None


def summarize_usage(calls):
    fields = {}
    for name in ('input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens'):
        values = [_usage_value(call, name) for call in calls]
        known = [value for value in values if value is not None]
        fields[name] = {'known_sum': sum(known), 'known_call_count': len(known),
                        'unknown_call_count': len(values) - len(known),
                        'all_calls_known': len(known) == len(values)}
    core_unknown = sum(_usage_value(call, 'input_tokens') is None or _usage_value(call, 'output_tokens') is None
                       for call in calls)
    durations = [call.get('duration_ms') for call in calls]
    return {'call_count': len(calls), 'fields': fields, 'unknown_core_usage_calls': core_unknown,
            'known_total_tokens': fields['input_tokens']['known_sum'] + fields['output_tokens']['known_sum'],
            'exact_total_available': core_unknown == 0,
            'cumulative_seconds': sum(value for value in durations if _number(value)) / 1000,
            'unknown_duration_calls': sum(not _number(value) for value in durations),
            'status_counts': dict(Counter(call.get('status', 'unknown') for call in calls)),
            'reasoning_note': 'reasoning_output_tokens 为 output_tokens 的子集；缓存输入为 input_tokens 的子集，均不重复相加。',
            'by_role': {role: {'calls': len(group), 'known_total_tokens': sum(
                (_usage_value(call, 'input_tokens') or 0) + (_usage_value(call, 'output_tokens') or 0) for call in group)}
                for role, group in _group(calls, 'role').items()}}


def _group(items, key):
    result = defaultdict(list)
    for item in items:
        result[item.get(key, 'unknown')].append(item)
    return dict(result)


def _extra_calls(directories, excluded_ids):
    calls, seen, records = [], set(excluded_ids), []
    for location in directories or []:
        directory = Path(location).resolve()
        if (directory / 'run.sqlite').is_file():
            candidates = read_run(directory)['calls']
        else:
            candidates = [_read_json(path, {}) for path in directory.rglob('result.json')]
            candidates = [record for record in candidates if record.get('call_id') and record.get('model')]
        selected = []
        for call in candidates:
            key = call.get('call_id')
            if key and key not in seen:
                seen.add(key)
                selected.append(call)
        calls.extend(selected)
        records.append({'directory': str(directory), 'exists': directory.is_dir(), 'deduplicated_calls': len(selected)})
    status = ('not_requested' if not directories else
              'partial_missing_directories' if any(not item['exists'] for item in records) else 'collected')
    return {'directories': records, 'status': status, 'usage': summarize_usage(calls),
            'scope': '显式提供的工程或试跑目录；按 call_id 去重，排除正式运行调用，不与正式运行相加归因。'}


def billing_window(run_dir, run, scope_note=None):
    private = Path(run_dir) / 'private'
    start = _read_json(private / 'billing_start.json')
    end = _read_json(private / 'billing_end.json')
    context = _read_json(private / 'billing_context.json', {})
    notes = [scope_note or context.get('scope_note') or
        '该凭据计费窗口可能包含并行工程、试跑和未记录的取消请求；没有逐调用账单，不能等同正式管线费用。']
    overlap_end = context.get('overlap_ended_at')
    if overlap_end:
        notes.append('已知工程或试跑重叠至 ' + (_display_time(overlap_end) or str(overlap_end)) + '。')
    result = {'scope': 'credential_time_window_only', 'production_cost_usd': None,
              'quota_delta': None, 'cost_usd': None, 'quota_per_usd': None,
              'start_captured_at': start.get('captured_at') if start else None,
              'end_captured_at': end.get('captured_at') if end else None,
              'notes': notes, 'status': 'unavailable'}
    if not start or not end:
        notes.append('缺少开始或结束账单快照，费用未知。')
        return result
    before = (start.get('usage') or {}).get('data') or {}
    after = (end.get('usage') or {}).get('data') or {}
    initial, final = before.get('total_used'), after.get('total_used')
    currency = start.get('currency_metadata') or {}
    end_currency = end.get('currency_metadata') or currency
    unit = currency.get('quota_per_unit')
    end_unit = end_currency.get('quota_per_unit')
    display = str(currency.get('quota_display_type', '')).upper()
    if not (_number(initial) and _number(final) and final >= initial and _number(unit) and unit > 0
            and unit == end_unit and display == 'USD'
            and str(end_currency.get('quota_display_type', '')).upper() == 'USD'):
        result['status'] = 'invalid_or_unsupported_snapshot'
        notes.append('快照计数、币种或换算单位不一致，未推算美元费用。')
        return result
    delta = Decimal(str(final)) - Decimal(str(initial))
    result.update(status='measured_key_window', quota_delta=int(delta) if delta == int(delta) else float(delta),
                  quota_per_usd=unit, cost_usd=float(delta / Decimal(str(unit))))
    started, captured = _instant(run.get('started_at')), _instant(start.get('captured_at'))
    if started and captured and captured > started:
        notes.append(f'开始快照晚于管线启动 {(captured - started).total_seconds():.1f} 秒，未覆盖这一段正式运行。')
    result['formula'] = 'cost_usd = (end.total_used - start.total_used) / quota_per_unit；不乘 usd_exchange_rate。'
    return result


def _harbor_entry(task, all_controls, agent):
    entry = (task.get('harbor_controls') or {}).get(agent)
    if not isinstance(entry, dict):
        per_task = all_controls.get('per_task', {})
        entry = per_task.get('sheetsfactory/' + task['id'], per_task.get(task['id'], {})).get(agent)
    expected = 1 if agent == 'oracle' else 0
    if not isinstance(entry, dict):
        return {'reward': None, 'matched': False, 'evidence_available': False}
    reward = entry.get('reward')
    valid = (_number(reward) and reward == expected and entry.get('matched') is True
             and not entry.get('exception_info'))
    return {'reward': reward, 'matched': valid, 'evidence_available': True,
            'result_file': entry.get('result_file'), 'has_exception': bool(entry.get('exception_info'))}


def _task_directory(run_dir, task):
    root = Path(run_dir).resolve()
    candidate = (root / 'tasks' / task['id']).resolve()
    if not candidate.is_relative_to(root / 'tasks'):
        raise ValueError('Task ID escapes the task artifact directory')
    return candidate


def _recovery(run_dir, task):
    revision = int(task.get('revision', 0) or 0)
    path = _task_directory(run_dir, task) / 'revisions' / f'{revision:03d}' / 'private/independent_recovery.json'
    record = _read_json(path)
    if not record:
        return {'verified': False, 'artifact_available': False, 'artifact': str(path)}
    replay = record.get('replay') or {}
    valid = (record.get('verified') is True and record.get('public_information_only') is True
             and (record.get('comparison') or {}).get('reward') == 1 and replay.get('returncode') == 0)
    return {'verified': valid, 'artifact_available': True, 'artifact': str(path),
            'replay_returncode': replay.get('returncode'),
            'comparison_reward': (record.get('comparison') or {}).get('reward')}


def _quality_diagnosis(run_dir, task):
    path = _task_directory(run_dir, task) / 'revisions' / f"{int(task.get('revision', 0) or 0):03d}" / 'private/diagnosis.json'
    record = _read_json(path)
    if not record:
        return {'verified': False, 'artifact_available': False, 'artifact': str(path), 'scope': None}
    enabled = record.get('enabled_check_ids', [])
    assessments = record.get('assessments') or {}
    complete = bool(enabled) and all(assessments.get(check, {}).get('state') in
                                    {'clear', 'flagged', 'not_applicable'} for check in enabled)
    coverage = record.get('coverage') or {}
    valid = (record.get('releasable') is True and complete and not coverage.get('blocking_issue_ids')
             and not coverage.get('unknown_check_ids') and not coverage.get('undispositioned_warning_ids'))
    return {'verified': valid, 'artifact_available': True, 'artifact': str(path),
            'scope': record.get('scope'), 'enabled_check_count': len(enabled)}


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def generate_report(run_dir, *, project_root=None, engineering_dirs=None, billing_scope_note=None, now=None):
    run_dir = Path(run_dir).resolve()
    project_root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[2]
    snapshot = read_run(run_dir)
    run, tasks, nodes, calls = (snapshot[key] for key in ('run', 'tasks', 'nodes', 'calls'))
    now = now or datetime.now(timezone.utc)
    if not now.tzinfo:
        now = now.replace(tzinfo=timezone.utc)
    config_path = run_dir / 'resolved_config.yaml'
    config = yaml.safe_load(config_path.read_text()) if config_path.is_file() else {}
    manifest_path = Path((config.get('run') or {}).get('seed_manifest', 'data/manifests/euses_financial.json'))
    if not manifest_path.is_absolute():
        manifest_path = project_root / manifest_path
    manifest = _read_json(manifest_path, {})
    preparation = (_read_json(project_root / 'data/manifests/source_preparation_usage.json', {})
                   if manifest_path.resolve() == (project_root / 'data/manifests/euses_financial.json').resolve() else {})
    prep = preparation.get('all_source_preparation') or {}
    controls = _read_json(run_dir / 'harbor_controls.json', {})
    details, warnings = [], []
    for task in tasks:
        oracle, nop = _harbor_entry(task, controls, 'oracle'), _harbor_entry(task, controls, 'nop')
        recovery = _recovery(run_dir, task)
        diagnosis = _quality_diagnosis(run_dir, task)
        verified = (task.get('status') == 'qualified' and oracle['matched'] and nop['matched']
                    and recovery['verified'] and diagnosis['verified'])
        if task.get('status') == 'qualified' and not verified:
            warnings.append({'task_id': task['id'], 'code': 'QUALIFIED_EVIDENCE_MISMATCH',
                             'reason': '已标记 qualified，但 Harbor、诊断或独立恢复证据不完整；未计入已核验产量。'})
        details.append({'task_id': task['id'], 'mode': task.get('mode'), 'source_id': task.get('source_id'),
                        'source': task.get('source'), 'status': task.get('status'), 'verified_qualified': verified,
                        'revision': int(task.get('revision', 0) or 0), 'variant': int(task.get('variant', 0) or 0),
                        'title': task.get('title'), 'error': task.get('error'),
                        'oracle': oracle, 'nop': nop, 'independent_recovery': recovery, 'diagnosis': diagnosis})
    qualified = [task for task in details if task['verified_qualified']]
    used_sources = {task['source_id'] for task in details if task.get('source_id')}
    productive_sources = {task['source_id'] for task in qualified if task.get('source_id')}
    constructed_tasks = {node.get('task_id') for node in nodes if node.get('node', node.get('node_id')) == 'construct'}
    built_sources = {task['source_id'] for task in details if task['task_id'] in constructed_tasks and task.get('source_id')}
    targets = (config.get('run') or {}).get('targets') or {
        'financial_modeling': run.get('financial_target', 20), 'debugging': run.get('debugging_target', 20)}
    actual = {mode: sum(task['mode'] == mode for task in qualified) for mode in targets}
    final_issue_counts, historical_issue_counts = Counter(), Counter()
    for task in tasks:
        final_issue_counts.update(issue.get('problem_id', 'unknown') for issue in task.get('issues', []))
        for path in _task_directory(run_dir, task).glob('revisions/*/private/diagnosis.json'):
            report = _read_json(path, {})
            historical_issue_counts.update(issue.get('problem_id', 'unknown') for issue in report.get('issues', []))
    rejection_codes = Counter()
    for task in details:
        if task['status'] == 'rejected':
            codes = set(re.findall(r'Q\d{2}|INFRA_FAILED|UNRESOLVED|EXHAUSTED', task.get('error') or ''))
            if not codes:
                message = (task.get('error') or '').lower()
                category = next((name for pattern, name in [
                    ('cross-sheet', 'NO_CROSS_SHEET'), ('planner rejected', 'PLAN_UNSUITABLE'),
                    ('source lacks', 'SOURCE_STRUCTURE'), ('repeats an existing', 'DUPLICATE_MODULE'),
                    ('duplicate', 'DUPLICATE_MODULE'), ('no evidence-supported repair', 'UNREPAIRABLE'),
                    ('unsupported', 'ENGINE_UNSUPPORTED')] if pattern in message), 'OTHER_OR_UNCLASSIFIED')
                codes = {category}
            rejection_codes.update(codes)
    revision_counts = Counter(task['revision'] for task in details)
    started = _instant(run.get('started_at'))
    wall = run.get('wall_seconds')
    wall_scope = 'recorded_run_wall_time'
    if not _number(wall):
        if run.get('status') not in {'completed', 'shortfall', 'failed', 'cancelled'} and started:
            wall = max(0, (now - started).total_seconds())
            wall_scope = 'live_elapsed_since_run_start'
        else:
            wall, wall_scope = None, 'unknown_not_recorded'
    node_seconds = sum(node.get('duration_ms', 0) for node in nodes if _number(node.get('duration_ms'))) / 1000
    return {
        'schema_version': '1.0', 'generated_at': now.isoformat(), 'generated_at_shanghai': _display_time(now.isoformat()),
        'run': {'id': run.get('id', run_dir.name), 'status': run.get('status'), 'directory': str(run_dir),
                'started_at': run.get('started_at'), 'started_at_shanghai': _display_time(run.get('started_at')),
                'code_revision': run.get('code_revision'), 'model': run.get('model'),
                'reasoning_effort': run.get('reasoning_effort'), 'difficulty_status': run.get('difficulty_status', 'unknown'),
                'difficulty_score': None, 'difficulty_note': '本轮只验题目质量，难度评测及低通过率目标延后；未报告正式模型 Pass@1。',
                'targets': targets, 'actual_verified_counts': actual,
                'target_met': all(actual[mode] >= count for mode, count in targets.items()),
                'is_final_snapshot': run.get('status') in {'completed', 'shortfall', 'failed', 'cancelled'}},
        'sources': {'archive_scanned': manifest.get('unique_workbooks_inspected', run.get('discovered_sources')),
                    'selected_seed_pool': manifest.get('selected_count'), 'eligible_seed_pool': manifest.get('eligible_count'),
                    'preparation_attempted': prep.get('attempted_unique_sources', run.get('preprocess_attempted_sources')),
                    'preparation_readable_profiled': prep.get('readable_profiled'),
                    'preparation_zero_cached_errors': prep.get('zero_cached_errors'),
                    'construction_attempted_unique_seeds': len(used_sources),
                    'construct_node_reached_unique_seeds': len(built_sources),
                    'productive_unique_seeds': len(productive_sources),
                    'archive_sha256': manifest.get('archive_sha256', run.get('source_archive_sha256')),
                    'archive_url': manifest.get('download_url', run.get('source_archive')),
                    'manifest': str(manifest_path),
                    'used_seed_definition': '在正式运行中创建过任务候选的不同 source_id，包含早期拒绝；与构造节点实际到达数分列。'},
        'yield': {'candidates': len(tasks), 'reported_qualified': sum(task.get('status') == 'qualified' for task in tasks),
                  'verified_qualified': len(qualified), 'rejected': sum(task['status'] == 'rejected' for task in details),
                  'ready_pending_validation': sum(task['status'] == 'ready' for task in details),
                  'candidate_conversion': _ratio(len(qualified), len(tasks)),
                  'productive_source_conversion': _ratio(len(productive_sources), len(used_sources)),
                  'tasks_per_used_seed': _ratio(len(qualified), len(used_sources)),
                  'by_mode': {mode: {'target': targets[mode], 'qualified': actual[mode],
                      'candidates': sum(task['mode'] == mode for task in details)} for mode in targets}},
        'timing': {'wall_seconds': wall, 'wall_scope': wall_scope, 'cumulative_node_seconds': node_seconds,
                   'node_attempt_count': len(nodes), 'running_node_count': sum(node.get('status') == 'running' for node in nodes),
                   'preparation_cumulative_seconds': prep.get('normalization_and_profile_cumulative_seconds'),
                   'preparation_wall_seconds': prep.get('first_survey_wall_seconds'),
                   'note': '并发节点累计时间不等于运行墙钟时间；预处理时间与正式运行分列，不补造缺失墙钟时间。',
                   'by_node': {name: {'attempts': len(group), 'cumulative_seconds': sum(
                       node.get('duration_ms', 0) for node in group if _number(node.get('duration_ms'))) / 1000}
                       for name, group in _group(nodes, 'node').items()}},
        'tokens': summarize_usage(calls),
        'engineering_usage': _extra_calls(engineering_dirs, {call.get('call_id') for call in calls}),
        'billing': billing_window(run_dir, run, billing_scope_note),
        'diagnostics': {'final_issue_instances_by_code': dict(sorted(final_issue_counts.items())),
                        'revision_report_issue_observations_by_code': dict(sorted(historical_issue_counts.items())),
                        'rejected_candidates_by_reason': dict(sorted(rejection_codes.items())),
                        'candidate_final_revision_histogram': {str(key): value for key, value in sorted(revision_counts.items())},
                        'content_repair_revision_total': sum(task['revision'] for task in details),
                        'checker_execution_states': dict(Counter(event.get('state', 'unknown') for event in snapshot['events']
                            if event.get('kind') == 'checker.result')),
                        'qualified_diagnosis_scopes': dict(Counter(task['diagnosis'].get('scope') or 'unknown' for task in qualified)),
                        'note': '最终问题实例与各版本诊断观测分列；同一问题跨版本出现不当作多个独立根因。'},
        'tasks': details, 'consistency_warnings': warnings,
    }


def _fmt(value, digits=2):
    if value is None:
        return '未知'
    if isinstance(value, float):
        return f'{value:,.{digits}f}'
    return str(value)


def _pct(value):
    return '未知' if value is None else f'{value:.2%}'


def _md(value):
    return escape(str(value if value is not None else '未知'), quote=False).replace('|', '\\|').replace('\n', ' ')


def markdown_report(report):
    run, sources, output = report['run'], report['sources'], report['yield']
    lines = ['# sheetsFactory 运行报告', '',
             f"运行 `{run['id']}`；状态 **{run['status']}**；报告时间 {report['generated_at_shanghai']}。", '',
             f"已核验产出 **{output['verified_qualified']} 道**，候选 {output['candidates']} 道。"
             f"目标题量是否达到：{'是' if run['target_met'] else '否'}。", '', run['difficulty_note'], '',
             '## 题量与转化率', '', '| 指标 | 数值 |', '| --- | ---: |']
    for label, value in [
        ('归档中扫描的不同工作簿', sources['archive_scanned']), ('筛选进入种子池', sources['selected_seed_pool']),
        ('预处理尝试种子数', sources['preparation_attempted']), ('预处理可读取并画像', sources['preparation_readable_profiled']),
        ('正式运行使用的不同种子', sources['construction_attempted_unique_seeds']),
        ('实际到达构造节点的不同种子', sources['construct_node_reached_unique_seeds']),
        ('贡献合格题目的种子', sources['productive_unique_seeds']), ('候选任务', output['candidates']),
        ('已核验合格任务', output['verified_qualified']), ('已拒绝候选', output['rejected']),
        ('候选转化率：合格题 / 候选题', _pct(output['candidate_conversion'])),
        ('源转化率：产题种子 / 使用种子', _pct(output['productive_source_conversion'])),
        ('平均每个使用种子的合格题数', _fmt(output['tasks_per_used_seed']))]:
        lines.append(f'| {label} | {_md(value)} |')
    lines += ['', sources['used_seed_definition'], '', '| 类别 | 目标 | 已核验合格 | 候选 |', '| --- | ---: | ---: | ---: |']
    for mode, row in output['by_mode'].items():
        lines.append(f"| {MODES.get(mode, mode)} | {row['target']} | {row['qualified']} | {row['candidates']} |")
    lines += ['', '## 时间与 Token', '',
              f"正式运行墙钟：{_fmt(report['timing']['wall_seconds'])} 秒；节点累计："
              f"{_fmt(report['timing']['cumulative_node_seconds'])} 秒。", '', report['timing']['note'], '',
              '| 用量 | 已知合计 | 用量未知的调用数 |', '| --- | ---: | ---: |']
    for name, value in report['tokens']['fields'].items():
        lines.append(f"| {name} | {value['known_sum']:,} | {value['unknown_call_count']} |")
    lines += ['', f"正式运行调用 {report['tokens']['call_count']} 次；已知输入加输出 "
              f"{report['tokens']['known_total_tokens']:,} token；核心用量不完整的调用 "
              f"{report['tokens']['unknown_core_usage_calls']} 次。", '', report['tokens']['reasoning_note'], '',
              '如存在未知用量，已知合计只是已记录部分，不代表总消耗为零或已完整计量。', '',
              (f"单列工程/试跑调用 {report['engineering_usage']['usage']['call_count']} 次，已知 token "
               f"{report['engineering_usage']['usage']['known_total_tokens']:,}；未混入正式运行统计。"
               if report['engineering_usage']['status'] != 'not_requested' else
               '未提供工程/试跑审计目录，额外用量未知；没有把它当成零消耗。'), '',
              '## 费用口径', '',
              f"凭据计费窗口费用：{('$' + _fmt(report['billing']['cost_usd'], 6)) if report['billing']['cost_usd'] is not None else '未知'}。"
              '正式管线的精确归因费用：未知。', '']
    lines += ['- ' + note for note in report['billing']['notes']]
    lines += ['', '## 诊断与修复', '', '| 问题编号 | 最终实例 | 版本诊断观测 |', '| --- | ---: | ---: |']
    diagnostics = report['diagnostics']
    for code in sorted(set(diagnostics['final_issue_instances_by_code']) | set(diagnostics['revision_report_issue_observations_by_code'])):
        lines.append(f"| {code} | {diagnostics['final_issue_instances_by_code'].get(code, 0)} | "
                     f"{diagnostics['revision_report_issue_observations_by_code'].get(code, 0)} |")
    lines += ['', f"累计内容修复版本数：{diagnostics['content_repair_revision_total']}。", '',
              '合格任务的诊断范围：`' + json.dumps(diagnostics['qualified_diagnosis_scopes'], ensure_ascii=False) + '`。', '',
              '拒绝原因计数：`' + json.dumps(diagnostics['rejected_candidates_by_reason'], ensure_ascii=False) + '`。', '',
              '## 逐题证据', '', '| 任务 | 类别 | 状态 | Oracle | Nop | 独立恢复 | 核验合格 |',
              '| --- | --- | --- | ---: | ---: | --- | --- |']
    for task in report['tasks']:
        lines.append(f"| {_md(task['task_id'])} | {_md(task['mode'])} | {_md(task['status'])} | "
            f"{_md(task['oracle']['reward'])} | {_md(task['nop']['reward'])} | "
            f"{'通过' if task['independent_recovery']['verified'] else '未证实'} | {'是' if task['verified_qualified'] else '否'} |")
    failures = [task for task in report['tasks'] if task.get('error')]
    if failures:
        lines += ['', '## 拒绝与失败样例', '']
        lines += [f"- `{task['task_id']}`：{_md(task['error'])}" for task in failures[:12]]
    if report['consistency_warnings']:
        lines += ['', '## 证据一致性警告', '']
        lines += [f"- `{item['task_id']}`：{item['reason']}" for item in report['consistency_warnings']]
    lines += ['', '## 复现与范围', '',
              f"代码版本：`{run.get('code_revision') or '未知'}`；模型 `{run.get('model') or '未知'}`，"
              f"reasoning `{run.get('reasoning_effort') or '未知'}`。", '',
              '```bash', 'harbor run -p "' + str(Path(run['directory']) / 'SpreadsheetEval') + '" -a oracle',
              'harbor run -p "' + str(Path(run['directory']) / 'SpreadsheetEval') + '" -a nop', '```', '',
              '报告仅从审计数据库与产物读取，不修改题目状态；真实执行结果见逐题 Harbor 证据。'
              '未执行的控制、缺失用量和延期难度评测均不补造通过结论。', '']
    return '\n'.join(lines)


def html_report(report):
    run, output = report['run'], report['yield']
    rows = ''.join('<tr>' + ''.join('<td>' + escape(str(value)) + '</td>' for value in [
        task['task_id'], MODES.get(task['mode'], task['mode']), task['status'],
        _fmt(task['oracle']['reward']), _fmt(task['nop']['reward']),
        '通过' if task['independent_recovery']['verified'] else '未证实',
        '是' if task['verified_qualified'] else '否', task.get('error') or '']) + '</tr>' for task in report['tasks'])
    cards = [('已核验题量', str(output['verified_qualified'])), ('候选数', str(output['candidates'])),
             ('候选转化率', _pct(output['candidate_conversion'])),
             ('使用种子数', str(report['sources']['construction_attempted_unique_seeds'])),
             ('墙钟秒数', _fmt(report['timing']['wall_seconds'])),
             ('已知 Token', f"{report['tokens']['known_total_tokens']:,}")]
    cards_html = ''.join(f'<article><span>{escape(label)}</span><strong>{escape(value)}</strong></article>' for label, value in cards)
    notes = ''.join('<li>' + escape(note) + '</li>' for note in report['billing']['notes'])
    # Embed an escaped text report for full offline inspection, not raw JSON in
    # an executable script. No CDN, network request or remote font is needed.
    return f'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>sheetsFactory 运行报告</title><style>
body{{font:15px/1.6 system-ui,sans-serif;margin:32px auto;padding:0 20px;max-width:1400px;color:#17212f;background:#f5f7fa}}
h1{{font-size:28px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}
article{{background:white;border:1px solid #dce2e8;border-radius:12px;padding:20px}}article span{{display:block;color:#536171}}strong{{font-size:26px}}
.notice{{padding:14px;background:#fff5da;border-left:4px solid #b78a00}}section{{margin:24px 0}}input{{padding:10px;min-width:280px}}
.table{{overflow:auto}}table{{border-collapse:collapse;background:white;width:100%}}td,th{{padding:10px;border-bottom:1px solid #e3e8ed;text-align:left;vertical-align:top}}th{{white-space:nowrap}}td:last-child{{min-width:240px}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:20px;border:1px solid #dce2e8}}small{{color:#536171}}
</style><h1>sheetsFactory 运行报告</h1><p>{escape(str(run['id']))} · {escape(str(run['status']))} · {escape(report['generated_at_shanghai'] or '')}</p>
<div class="cards">{cards_html}</div><p class="notice">{escape(run['difficulty_note'])}</p>
<section><h2>费用口径</h2><p>凭据计费窗口：{escape('$' + _fmt(report['billing']['cost_usd'], 6) if report['billing']['cost_usd'] is not None else '未知')}；正式管线精确归因费用：未知。</p><ul>{notes}</ul></section>
<section><h2>逐题证据</h2><input id="filter" placeholder="筛选任务、类别、状态或错误" aria-label="筛选任务"><div class="table"><table id="tasks"><thead><tr>
<th>任务</th><th>类别</th><th>状态</th><th>Oracle</th><th>Nop</th><th>独立恢复</th><th>核验合格</th><th>失败原因</th></tr></thead><tbody>{rows}</tbody></table></div></section>
<details><summary>完整统计、指标定义和复现命令</summary><pre>{escape(markdown_report(report))}</pre></details>
<script>document.getElementById('filter').addEventListener('input',function(){{let q=this.value.toLowerCase();document.querySelectorAll('#tasks tbody tr').forEach(function(r){{r.hidden=!r.textContent.toLowerCase().includes(q);}});}});</script>
</html>'''


def write_reports(run_dir, output_dir=None, **kwargs):
    report = generate_report(run_dir, **kwargs)
    directory = Path(output_dir) if output_dir else Path(run_dir) / 'reports'
    directory.mkdir(parents=True, exist_ok=True)
    paths = {'json': directory / 'report.json', 'markdown': directory / 'report.zh-CN.md', 'html': directory / 'report.html'}
    paths['json'].write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    paths['markdown'].write_text(markdown_report(report))
    paths['html'].write_text(html_report(report))
    return {'paths': {name: str(path.resolve()) for name, path in paths.items()}, 'report': report}
