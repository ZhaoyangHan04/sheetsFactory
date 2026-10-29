"""Historical viewing must neither reopen a run for writing nor invent usage."""
from __future__ import annotations

import json
from pathlib import Path
import select
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from urllib.request import urlopen

from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard import DashboardServer
from sheets_factory.dashboard.read_only import ReadOnlyAuditView


class HistoricalDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="factory history ")
        self.directory = Path(self.temp.name)
        self.audit = AuditStore(self.directory, {"id": "history-test", "status": "constructing", "target_count": 40})
        self.view = ReadOnlyAuditView(self.directory)

    def tearDown(self):
        self.audit.db.close()
        self.temp.cleanup()

    def test_finished_snapshot_metrics_match_saved_audit(self):
        self.audit.task("f-1", source_id="seed-1", mode="financial_modeling", status="qualified", revision=1)
        self.audit.task("d-1", source_id="seed-1", mode="debugging", status="rejected", revision=0)
        self.audit.record("calls", {"call_id": "c1", "status": "completed", "input_tokens": 120, "output_tokens": 30, "cached_input_tokens": 80})
        self.audit.record("nodes", {"node": "plan", "duration_ms": 1300, "status": "completed"})
        self.audit.update_run(status="completed")
        expected = self.audit.snapshot()
        actual = self.view.snapshot()
        self.assertEqual(actual["run"], expected["run"])
        for key, value in expected["metrics"].items():
            self.assertEqual(actual["metrics"][key], value, key)
        self.assertTrue(actual["viewer"]["read_only"])

    def test_live_calls_project_recorded_starts_and_unknown_usage(self):
        self.audit.emit("llm.started", call_id="live-1", role="planner", model="gpt-6-sol", started_at="2026-10-29T00:00:00+00:00")
        result = self.view.snapshot()
        self.assertEqual(result["metrics"]["llm_calls"], 1)
        self.assertEqual(result["metrics"]["active_llm_calls"], 1)
        call = result["llm_calls"][0]
        self.assertEqual(call["status"], "running")
        self.assertIsNone(call["input_tokens"])
        self.assertTrue(call["usage_pending"])
        self.assertIsNone(call["usage"])
        self.assertGreaterEqual(call["duration_ms"], 0)

    def test_projection_deduplicates_when_final_call_record_appears(self):
        self.audit.emit("llm.started", call_id="c1", role="planner")
        self.assertEqual(self.view.snapshot()["metrics"]["active_llm_calls"], 1)
        self.audit.record("calls", {"call_id": "c1", "status": "completed", "input_tokens": 10, "output_tokens": 2})
        result = self.view.snapshot()
        self.assertEqual(result["metrics"]["llm_calls"], 1)
        self.assertEqual(result["metrics"]["active_llm_calls"], 0)
        self.assertEqual(result["metrics"]["total_tokens"], 12)

    def test_terminal_run_does_not_claim_orphan_start_is_still_running(self):
        self.audit.emit("llm.started", call_id="c1", role="planner")
        self.audit.update_run(status="cancelled")
        result = self.view.snapshot()
        self.assertEqual(result["metrics"]["active_llm_calls"], 0)
        self.assertEqual(result["metrics"]["unfinished_llm_calls"], 1)
        self.assertEqual(result["llm_calls"][0]["status"], "unknown")
        self.assertIsNone(result["llm_calls"][0]["duration_ms"])

    def test_read_only_connection_cannot_write_or_replace_saved_run(self):
        before = self.audit.db.execute("SELECT value FROM state WHERE key='run'").fetchone()[0]
        with self.view._connect() as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("UPDATE state SET value='{}'")
        self.view.snapshot()
        self.view.events()
        after = self.audit.db.execute("SELECT value FROM state WHERE key='run'").fetchone()[0]
        self.assertEqual(before, after)

    def test_missing_run_does_not_create_database(self):
        directory = self.directory / "missing"
        with self.assertRaises(FileNotFoundError):
            ReadOnlyAuditView(directory)
        self.assertFalse(directory.exists())

    def test_live_wal_events_visible_without_restarting_view(self):
        self.assertEqual(self.view.events(), [])
        first = self.audit.emit("node.started", node="plan", task_id="task-1")
        self.assertEqual(self.view.events()[0]["id"], first["id"])
        second = self.audit.emit("node.completed", node="plan", task_id="task-1")
        self.assertEqual([event["id"] for event in self.view.events(first["id"])], [second["id"]])

    def test_http_view_observes_current_and_final_status(self):
        with DashboardServer(self.view.snapshot, self.view.events, port=0) as server:
            with urlopen(server.url + "api/snapshot", timeout=3) as response:
                self.assertEqual(json.load(response)["run"]["status"], "constructing")
            self.audit.update_run(status="completed")
            with urlopen(server.url + "api/snapshot", timeout=3) as response:
                self.assertEqual(json.load(response)["run"]["status"], "completed")

    def test_script_starts_without_credentials_and_stops_cleanly(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "serve_dashboard.py"
        process = subprocess.Popen([sys.executable, str(script), "--run", str(self.directory), "--port", "0"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            readable, _, _ = select.select([process.stdout], [], [], 5)
            self.assertTrue(readable, "Viewer did not start")
            line = process.stdout.readline()
            self.assertTrue(line.startswith("Read-only run dashboard: "), line)
            url = line.split(": ", 1)[1].strip()
            with urlopen(url + "api/snapshot", timeout=3) as response:
                self.assertEqual(json.load(response)["run"]["id"], "history-test")
            process.terminate()
            process.wait(timeout=5)
            self.assertEqual(process.returncode, 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
            process.stdout.close()
            process.stderr.close()


if __name__ == "__main__":
    unittest.main()
