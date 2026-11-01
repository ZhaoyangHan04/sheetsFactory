#!/usr/bin/env python3
"""Display final evidence without changing historical audit stores or scores."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sheets_factory.dashboard.server import DashboardServer


class Reader:
    def __init__(self):
        self.cache = {}

    def read(self, value):
        expected = value if isinstance(value, dict) else None
        path = Path(expected['path'] if expected else value).resolve(strict=True)
        stat = path.stat(); signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
        saved = self.cache.get(path)
        if saved is None or saved[0] != signature:
            raw = path.read_bytes()
            after = path.stat()
            if (after.st_ino, after.st_size, after.st_mtime_ns) != signature:
                raise ValueError('Evidence changed while reading')
            record = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
            saved = (signature, json.loads(raw), record); self.cache[path] = saved
        if expected is not None and saved[2] != expected:
            raise ValueError('A bound evidence file changed')
        return saved[1], saved[2]


def calls_at(directory, phase):
    database = Path(directory) / 'run.sqlite'
    if not database.is_file():
        return []
    connection = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        connection.execute('PRAGMA query_only=ON')
        rows = connection.execute('SELECT id,payload FROM calls ORDER BY id').fetchall()
        fields = ('model', 'role', 'status', 'task_id', 'duration_ms', 'input_tokens',
                  'output_tokens', 'cached_input_tokens', 'started_at', 'finished_at')
        return [{'call_id': phase + ':' + str(i), 'stage': phase,
                 **{k: d.get(k) for k in fields}} for i, raw in rows for d in [json.loads(raw)]]
    finally:
        connection.close()


def timing(row):
    exact = row.get('tool_seconds')
    lower, upper = row.get('tool_lower_seconds'), row.get('tool_upper_seconds')
    if exact is not None:
        return f'{float(exact):.3f}秒'
    if lower is not None and upper is not None:
        return f'[{float(lower):.3f}, {float(upper):.3f}]秒'
    return 'UNKNOWN'


class ResultView:
    def __init__(self, release, development, confirmation, failure_summary):
        self.paths = dict(release=Path(release), development=Path(development),
                          confirmation=Path(confirmation), failure_summary=Path(failure_summary))
        self.reader = Reader()
        self.lock = threading.Lock()

    def snapshot(self):
        with self.lock:
            return self._snapshot()

    def _snapshot(self):
        reader = self.reader
        dev, dev_ref = reader.read(self.paths['development'])
        conf, conf_ref = reader.read(self.paths['confirmation'])
        if dev.get('phase') != 'development' or conf.get('phase') != 'confirmation':
            raise ValueError('Expected separate original development and confirmation records')
        release, release_ref = (reader.read(self.paths['release']) if self.paths['release'].is_file() else ({}, None))
        summary, summary_ref = (reader.read(self.paths['failure_summary']) if self.paths['failure_summary'].is_file() else ({}, None))
        selected = {r['task_id'] for r in conf['results']}
        if len(dev['results']) != 40 or len(conf['results']) != 20 or len(selected) != 20:
            raise ValueError('Expected forty candidates and twenty unique confirmation tasks')
        qualified = release.get('qualified') is True
        if qualified:
            if (release.get('kind') != 'qualified_operating_report_factory_release'
                or release.get('task_count') != 20 or release.get('confirmation') != conf_ref
                or {r['task_id'] for r in release.get('tasks', [])} != selected
                or Counter(r['mode'] for r in release['tasks']) != Counter({'financial_modeling': 10, 'debugging': 10})):
                raise ValueError('Qualified release does not bind the original twenty-task confirmation')
            cohort, _ = reader.read(release['cohort'])
            if cohort['development'] != dev_ref:
                raise ValueError('Release development evidence differs')
        if summary and summary.get('evidence', {}).get('confirmation') != conf_ref:
            raise ValueError('Failure summary belongs to a different confirmation')
        final_rows = {r['task_id']: r for r in release.get('tasks', [])} if qualified else {}
        differences = {r['task_id']: r for r in summary.get('rows', [])}
        tasks = []
        for original in conf['results']:
            ident = original['task_id']; final = final_rows.get(ident, {}); failure = differences.get(ident, {})
            clock = original['actual_attempt'].get('tool_time', {})
            display = final or {'tool_seconds': clock.get('cumulative_tool_seconds'),
                'tool_lower_seconds': clock.get('cumulative_lower_bound_seconds'),
                'tool_upper_seconds': clock.get('cumulative_upper_bound_seconds')}
            pattern = failure.get('pattern', '待汇总')
            detail = f"原始分数 {original['score'].get('raw_verifier_reward')}；工具 {timing(display)}；{pattern}"
            if original['score'].get('state') == 'unknown':
                detail += '；原v6 UNKNOWN保留' + ('，另有完整计时补证' if qualified else '')
            if failure:
                detail += f"；漏改/额外/数值 {failure.get('missing_count')}/{failure.get('extra_count')}/{failure.get('wrong_value_count')}"
                detail += '；字段 ' + ', '.join(f'{k}:{v}' for k, v in failure.get('wrong_fields', {}).items())
            tasks.append({'id': ident, 'task_id': ident, 'mode': original['mode'],
                'source_id': 'one_shared_operating_reports_source', 'status': 'qualified' if qualified else 'evidence_pending',
                'reason': detail, 'raw_reward': original['score'].get('raw_verifier_reward'),
                'original_effective_reward': original['score'].get('effective_reward'),
                'release_reward': final.get('reward'), 'timing': display,
                'wrong_fields': failure.get('wrong_fields', {}), 'boundary_only': failure.get('boundary_only'),
                'resources_passed': original.get('resources', {}).get('passed')})
        calls = []
        for label, terminal in (('development', dev), ('confirmation', conf)):
            reader.read(terminal['evaluation'])
            calls += calls_at(Path(terminal['evaluation']['path']).parent, label)
        if qualified:
            quality, _ = reader.read(release['quality'])
            for i, record in enumerate(quality['shared_semantic_reviews']):
                proof, _ = reader.read(record)
                calls += calls_at(Path(record['path']).parent, 'shared_semantic_' + str(i))
        known_input = sum(c['input_tokens'] or 0 for c in calls)
        known_output = sum(c['output_tokens'] or 0 for c in calls)
        cached = sum(c['cached_input_tokens'] or 0 for c in calls)
        unknown_usage = sum(c['input_tokens'] is None or c['output_tokens'] is None for c in calls)
        usage_consistent = (not qualified or (len(calls) == release['current_batch_model_calls']
                            and known_input + known_output == release['current_batch_known_total_tokens']))
        controls = {}
        if qualified:
            controls, _ = reader.read(release['controls'])
        metrics = {'candidates': len(dev['results']), 'qualified': 20 if qualified else 0,
            'unique_seeds': 1, 'candidate_conversion': 20 / len(dev['results']) if qualified else 0,
            'input_tokens': known_input, 'output_tokens': known_output, 'total_tokens': known_input + known_output,
            'cached_input_tokens': cached, 'llm_calls': len(calls), 'unknown_usage_calls': unknown_usage,
            'estimated_cost': None, 'cost_status': 'provider billing unavailable', 'open_issues': 0,
            'rejected': 0, 'repair_rounds': 0, 'usage_matches_qualified_release': usage_consistent}
        original_counts = Counter('unknown' if r['score'].get('effective_reward') is None else str(r['score']['effective_reward']) for r in conf['results'])
        note = ('只读结果视图。缓存输入是输入token的子集，不重复加总。旧master失败状态和原v6 UNKNOWN不改写。'
                '同一来源的40个候选；边界差异不等于财务推理失败。')
        raw_zero = sum(r['score'].get('raw_verifier_reward') == 0 for r in conf['results'])
        note += f' 确认原始0分 {raw_zero}/20；本轮模型调用 {len(calls)}；缓存输入 {cached:,}（已含于输入）。'
        if controls.get('passed') is True:
            note += f" 实际oracle20题全{controls.get('oracle_all20_reward')}，nop20题全{controls.get('nop_all20_reward')}。"
        return {'run': {'id': 'operating_report_factory_final_evidence', 'status': 'qualified' if qualified else 'partial',
                'target_count': 20, 'qualified': 20 if qualified else 0,
                'financial_modeling': 10 if qualified else 0, 'debugging': 10 if qualified else 0,
                'financial_target': 10, 'debugging_target': 10, 'quality_note': note,
                'current_phase': '最终证据齐全' if qualified else '等待合格release',
                'finished_at': release.get('created_at')}, 'metrics': metrics, 'tasks': tasks,
            'nodes': [{'node_id': 'evidence', 'name': '只读最终证据 / 40候选 → 20准出' if qualified else '只读证据 / 等待准出',
                'status': 'completed' if qualified else 'pending', 'count': len(dev['results']),
                'total_tokens': known_input + known_output}], 'llm_calls': calls, 'issues': [], 'events': [],
            'original_confirmation_effective_counts': dict(original_counts),
            'actual_confirmation_raw_zero_count': raw_zero,
            'actual_root_controls': {'oracle_tasks': 20 if controls.get('passed') is True else None,
                'oracle_reward': controls.get('oracle_all20_reward'), 'nop_tasks': 20 if controls.get('passed') is True else None,
                'nop_reward': controls.get('nop_all20_reward'), 'resources_checked': controls.get('actual_role_resources_checked')},
            'evidence': {'release': release_ref, 'development': dev_ref, 'confirmation': conf_ref, 'failure_summary': summary_ref},
            'viewer': {'read_only': True, 'source': 'bound_result_files_and_query_only_audit_calls',
                'historical_stores_modified': False, 'no_new_model_or_native_calls': True,
                'cached_input_tokens_are_subset': True, 'snapshot_at': datetime.now(timezone.utc).isoformat()}}

    def events(self, after=0):
        return []


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('release', 'development', 'confirmation', 'failure-summary'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    view = ResultView(args.release, args.development, args.confirmation, args.failure_summary)
    snapshot = view.snapshot()
    if args.snapshot:
        args.snapshot.parent.mkdir(parents=True, exist_ok=True)
        with args.snapshot.open('x') as handle:
            json.dump(snapshot, handle, indent=2, ensure_ascii=False, allow_nan=False); handle.write('\n')
    if args.serve:
        server = DashboardServer(view.snapshot, view.events, host='127.0.0.1', port=args.port)
        print(json.dumps({'url': server.start(), 'read_only': True}), flush=True)
        try:
            while True:
                threading.Event().wait(1)
        except KeyboardInterrupt:
            pass
        finally:
            server.stop()
    else:
        print(json.dumps({'qualified': snapshot['run']['qualified'], 'calls': snapshot['metrics']['llm_calls'],
                          'snapshot': str(args.snapshot) if args.snapshot else None}))


if __name__ == '__main__':
    main()
