"""HTTP-level tests for the dependency-free local run dashboard."""

import json
import socket
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sheets_factory.dashboard import DashboardServer


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"id": 1, "type": "run.started", "message": "运行开始"},
            {"id": 2, "type": "node.started", "message": "<script>alert(1)</script>"},
        ]
        self.lock = threading.Lock()

        def snapshot():
            return {
                "run": {"id": "run-test", "qualified": 0, "target_count": 40},
                "metrics": {"input_tokens": 123, "estimated_cost": None},
                "api_key": "do-not-show",
                "provider": {"Authorization": "Bearer do-not-show"},
                "events": self.read_events(0),
            }

        self.dashboard = DashboardServer(snapshot, self.read_events, port=0)
        self.url = self.dashboard.start()

    def read_events(self, after):
        with self.lock:
            return [dict(event) for event in self.records if event["id"] > after]

    def tearDown(self):
        self.dashboard.stop()

    def get_json(self, path):
        with urlopen(self.url + path, timeout=3) as response:
            return json.load(response)

    def test_snapshot_redacts_secrets_without_losing_usage(self):
        data = self.get_json("api/snapshot")
        self.assertEqual(data["run"]["target_count"], 40)
        self.assertEqual(data["api_key"], "[REDACTED]")
        self.assertEqual(data["provider"]["Authorization"], "[REDACTED]")
        self.assertEqual(data["metrics"]["input_tokens"], 123)
        self.assertIsNone(data["metrics"]["estimated_cost"])

    def test_dashboard_is_offline_and_data_is_not_interpolated_into_html(self):
        with urlopen(self.url, timeout=3) as response:
            html = response.read().decode()
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn("题目构造运行面板", html)
        self.assertIn("EventSource", html)
        self.assertIn("textContent", html)
        self.assertNotIn("alert(1)", html)
        self.assertNotIn(".innerHTML", html)
        self.assertNotIn("cdn.", html)

    def test_event_cursor_and_json_text_safety(self):
        data = self.get_json("api/events?after=1")
        self.assertEqual([e["id"] for e in data["events"]], [2])
        self.assertEqual(data["events"][0]["message"], "<script>alert(1)</script>")
        self.assertEqual(self.get_json("api/events?after=2"), {"events": []})

    def test_sse_last_event_id_reconnect(self):
        request = Request(self.url + "api/stream?after=0", headers={"Last-Event-ID": "1"})
        with urlopen(request, timeout=3) as response:
            self.assertEqual(response.headers["Content-Type"], "text/event-stream; charset=utf-8")
            block = []
            for _ in range(15):
                line = response.readline().decode()
                block.append(line)
                if line.startswith("data:"):
                    break
            event = "".join(block)
            self.assertIn("id: 2\n", event)
            self.assertNotIn("id: 1\n", event)
            self.assertIn("event: update\n", event)
            self.assertIn("<script>alert(1)</script>", event)

    def test_sse_observes_new_event_after_connection(self):
        with urlopen(self.url + "api/stream?after=2", timeout=3) as response:
            self.assertTrue(response.readline().startswith(b"retry:"))
            with self.lock:
                self.records.append({"id": 3, "type": "node.completed", "message": "完成\n下一步"})
            block = []
            for _ in range(20):
                line = response.readline().decode()
                block.append(line)
                if line.startswith("data:"):
                    payload = json.loads(line.removeprefix("data:"))
                    self.assertEqual(payload["message"], "完成\n下一步")
                    break
            else:
                self.fail("SSE did not receive new event")
            self.assertIn("id: 3\n", "".join(block))

    def test_port_conflict_falls_back_and_stop_is_idempotent(self):
        parsed_port = int(self.url.split(":")[-1].rstrip("/"))
        second = DashboardServer(lambda: {}, lambda after: [], port=parsed_port)
        try:
            second_url = second.start()
            self.assertNotEqual(second_url, self.url)
            self.assertEqual(second.start(), second_url)
            with urlopen(second_url + "api/snapshot", timeout=3) as response:
                self.assertEqual(json.load(response), {})
        finally:
            second.stop()
            second.stop()

    def test_invalid_cursor_and_files_are_not_exposed(self):
        for path, expected in [("api/events?after=NaN", 400), ("../.secrets/key", 404), ("private/goal.xlsx", 404)]:
            with self.subTest(path=path):
                with self.assertRaises(HTTPError) as error:
                    urlopen(self.url + path, timeout=3)
                self.assertEqual(error.exception.code, expected)

    def test_callback_failure_does_not_disclose_exception(self):
        def fail():
            raise RuntimeError("secret-value-not-for-browser")

        self.dashboard.snapshot = fail
        with self.assertRaises(HTTPError) as error:
            urlopen(self.url + "api/snapshot", timeout=3)
        self.assertEqual(error.exception.code, 503)
        self.assertNotIn("secret-value", error.exception.read().decode())

    def test_safe_event_key_redaction(self):
        with self.lock:
            self.records.append({"id": 3, "api_key": "hidden", "message": "sk-abcdefghijklmnopqrstuv"})
        event = self.get_json("api/events?after=2")["events"][0]
        self.assertEqual(event["api_key"], "[REDACTED]")
        self.assertEqual(event["message"], "[REDACTED]")

    def test_restart_after_stop(self):
        self.dashboard.stop()
        self.assertIsNone(self.dashboard.url)
        self.url = self.dashboard.start()
        self.assertEqual(self.get_json("api/snapshot")["run"]["id"], "run-test")


if __name__ == "__main__":
    unittest.main()
