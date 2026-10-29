"""SQLite is authoritative; JSON exports and the dashboard are projections."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class AuditStore:
    def __init__(self, directory: Path, run: dict):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.directory / 'run.sqlite', check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, kind TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, payload TEXT);
        CREATE TABLE IF NOT EXISTS nodes (id INTEGER PRIMARY KEY, payload TEXT);
        CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY, payload TEXT);
        ''')
        self.run = {'started_at': utcnow(), 'status': 'initializing', **run}
        self._state()

    def _state(self):
        self.db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', ('run', json.dumps(self.run)))
        self.db.commit()

    def update_run(self, **values):
        with self.lock:
            self.run.update(values)
            self._state()

    def emit(self, kind, **payload):
        with self.lock:
            stamp = utcnow()
            cursor = self.db.execute('INSERT INTO events(timestamp,kind,payload) VALUES (?,?,?)',
                                     (stamp, kind, json.dumps(payload, ensure_ascii=False, default=str)))
            self.db.commit()
            return {'id': cursor.lastrowid, 'timestamp': stamp, 'kind': kind, **payload}

    def task(self, task_id, **values):
        with self.lock:
            row = self.db.execute('SELECT payload FROM tasks WHERE id=?', (task_id,)).fetchone()
            data = json.loads(row[0]) if row else {'id': task_id, 'created_at': utcnow()}
            data.update(values)
            self.db.execute('INSERT OR REPLACE INTO tasks VALUES (?,?)', (task_id, json.dumps(data, default=str)))
            self.db.commit()

    def record(self, table, record):
        if table not in {'nodes', 'calls'}:
            raise ValueError('Unsupported audit table')
        with self.lock:
            cursor = self.db.execute(f'INSERT INTO {table}(payload) VALUES (?)', (json.dumps(record, default=str),))
            self.db.commit()
            return cursor.lastrowid

    def update_record(self, table, record_id, values):
        if table not in {'nodes', 'calls'}:
            raise ValueError('Unsupported audit table')
        with self.lock:
            row = self.db.execute(f'SELECT payload FROM {table} WHERE id=?', (record_id,)).fetchone()
            if row is None:
                raise KeyError(record_id)
            value = {**json.loads(row[0]), **values}
            self.db.execute(f'UPDATE {table} SET payload=? WHERE id=?', (json.dumps(value, default=str), record_id))
            self.db.commit()

    def events(self, after=0):
        with self.lock:
            rows = self.db.execute('SELECT id,timestamp,kind,payload FROM events WHERE id>? ORDER BY id LIMIT 1000', (after,)).fetchall()
            return [{'id': r[0], 'timestamp': r[1], 'kind': r[2], **json.loads(r[3])} for r in rows]

    def snapshot(self):
        with self.lock:
            tables = {t: [json.loads(r[0]) for r in self.db.execute(f'SELECT payload FROM {t} ORDER BY rowid')]
                      for t in ['tasks', 'nodes', 'calls']}
            tasks, calls = tables['tasks'], tables['calls']
            qualified = [t for t in tasks if t.get('status') == 'qualified']
            inp = sum(c.get('input_tokens') or 0 for c in calls)
            out = sum(c.get('output_tokens') or 0 for c in calls)
            source_ids = {t['source_id'] for t in tasks if t.get('source_id')}
            productive = {t['source_id'] for t in qualified}
            metrics = {
                'input_tokens': inp, 'output_tokens': out, 'total_tokens': inp + out,
                'cached_input_tokens': sum(c.get('cached_input_tokens') or 0 for c in calls),
                'llm_calls': len(calls), 'unknown_usage_calls': sum(c.get('input_tokens') is None for c in calls),
                'estimated_cost': None, 'cost_status': 'provider billing unavailable',
                'candidates': len(tasks), 'unique_seeds': len(source_ids),
                'ready': sum(t.get('status') == 'ready' for t in tasks),
                'productive_seeds': len(productive), 'qualified': len(qualified),
                'rejected': sum(t.get('status') == 'rejected' for t in tasks),
                'candidate_conversion': len(qualified) / len(tasks) if tasks else None,
                'source_conversion': len(productive) / len(source_ids) if source_ids else None,
                'tasks_per_seed': len(qualified) / len(source_ids) if source_ids else None,
                'cumulative_node_seconds': sum(n.get('duration_ms', 0) or 0 for n in tables['nodes']) / 1000,
            }
            run = {**self.run, 'qualified': len(qualified), **{
                mode: sum(t.get('mode') == mode for t in qualified)
                for mode in ['financial_modeling', 'debugging']}}
            return {'run': run, 'metrics': metrics, 'tasks': tasks, 'nodes': tables['nodes'],
                    'llm_calls': calls, 'issues': [i for t in tasks for i in t.get('issues', [])],
                    'events': self.events(max(0, self.db.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0] - 100))}

    def export(self):
        snapshot = self.snapshot()
        (self.directory / 'summary.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str))
        with self.lock:
            rows = self.db.execute('SELECT id,timestamp,kind,payload FROM events ORDER BY id').fetchall()
        with (self.directory / 'events.jsonl').open('w') as stream:
            for r in rows:
                stream.write(json.dumps({'id': r[0], 'timestamp': r[1], 'kind': r[2], **json.loads(r[3])}, ensure_ascii=False) + '\n')
        return snapshot
