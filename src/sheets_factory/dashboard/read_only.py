"""Observe live or finished audit databases without changing their state."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from .server import DashboardServer


_TERMINAL = {
    "completed", "complete", "done", "shortfall", "failed", "cancelled",
    "partial", "exhausted", "infra_failed", "qualified", "accepted",
}


def _milliseconds(started_at: str | None, finished_at: str | None = None) -> int | None:
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finish = datetime.fromisoformat(finished_at.replace("Z", "+00:00")) if finished_at else datetime.now(timezone.utc)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if finish.tzinfo is None:
            finish = finish.replace(tzinfo=timezone.utc)
        return max(0, round((finish - start).total_seconds() * 1000))
    except (AttributeError, TypeError, ValueError):
        return None


class ReadOnlyAuditView:
    """Thread-safe callbacks opening a fresh read-only transaction per request.

    Live WAL changes remain visible; ``immutable=1`` must not be used for an
    active SQLite database. No schema creation, checkpoint, or run-state update
    is performed. Call projections expose recorded starts, never invented usage.
    """

    def __init__(self, directory: Path):
        self.directory = Path(directory).expanduser().resolve()
        self.database = self.directory / "run.sqlite"
        if not self.database.is_file():
            raise FileNotFoundError("Run audit database not found: " + str(self.database))

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=10)
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _events(connection: sqlite3.Connection, after: int = 0) -> list[dict]:
        rows = connection.execute(
            "SELECT id,timestamp,kind,payload FROM events WHERE id>? ORDER BY id LIMIT 1000",
            (max(0, int(after)),),
        ).fetchall()
        return [{"id": row[0], "timestamp": row[1], "kind": row[2], **json.loads(row[3])}
                for row in rows]

    def events(self, after: int = 0) -> list[dict]:
        with self._connect() as connection:
            return self._events(connection, after)

    @staticmethod
    def _project_calls(connection: sqlite3.Connection, calls: list[dict], run: dict) -> list[dict]:
        known = {call.get("call_id") for call in calls if call.get("call_id")}
        projected: dict[str, dict[str, Any]] = {}
        live = str(run.get("status", "")).lower() not in _TERMINAL
        events = connection.execute(
            "SELECT timestamp,kind,payload FROM events WHERE kind IN "
            "('llm.started','llm.completed','llm.failed') ORDER BY id"
        ).fetchall()
        for stamp, kind, raw in events:
            payload = json.loads(raw)
            call_id = payload.get("call_id")
            if not call_id or call_id in known:
                continue
            if kind == "llm.started":
                projected[call_id] = {
                    **payload, "call_id": call_id, "started_at": payload.get("started_at", stamp),
                    "status": "running" if live else "unknown", "usage": None,
                    "input_tokens": None, "output_tokens": None, "cached_input_tokens": None,
                    "usage_pending": True, "projected_from_events": True,
                    "completion_missing": not live,
                }
            elif call_id in projected:
                value = projected[call_id]
                value.update(payload)
                value.update({"status": "completed" if kind == "llm.completed" else "failed",
                              "finished_at": stamp, "usage_pending": False,
                              "completion_missing": False})
        for value in projected.values():
            if value["status"] == "running":
                value["duration_ms"] = _milliseconds(value.get("started_at"))
            elif value.get("finished_at"):
                value.setdefault("duration_ms", _milliseconds(value.get("started_at"), value["finished_at"]))
            else:
                # The last saved run duration does not establish a call's end.
                value["duration_ms"] = None
        return calls + list(projected.values())

    def snapshot(self) -> dict:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM state WHERE key='run'").fetchone()
            if row is None:
                raise ValueError("Audit database has no saved run state")
            saved_run = json.loads(row[0])
            tables = {
                table: [json.loads(row[0]) for row in connection.execute(
                    f"SELECT payload FROM {table} ORDER BY rowid")]
                for table in ("tasks", "nodes", "calls")
            }
            maximum = connection.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
            recent_events = self._events(connection, max(0, maximum - 100))
            calls = self._project_calls(connection, tables["calls"], saved_run)
            transitions = {}
            for stamp, kind, payload in connection.execute(
                    "SELECT timestamp,kind,payload FROM events WHERE kind IN "
                    "('task.ready','task.qualified','task.rejected') ORDER BY id"):
                task_id = json.loads(payload).get("task_id")
                if task_id:
                    transitions[task_id] = {"timestamp": stamp, "kind": kind}

        tasks = []
        for original in tables["tasks"]:
            task = dict(original)
            task_id = task.get("id", task.get("task_id"))
            if task.get("error") and not task.get("rejection_reason"):
                task["rejection_reason"] = task["error"]
            transition = transitions.get(task_id)
            if transition and transition["kind"] == "task." + str(task.get("status")):
                task["duration_ms"] = _milliseconds(task.get("created_at"), transition["timestamp"])
                task["duration_scope"] = "creation_to_recorded_state_transition"
            elif str(task.get("status", "")).lower() == "running" and str(saved_run.get("status", "")).lower() not in _TERMINAL:
                task["duration_ms"] = _milliseconds(task.get("created_at"))
                task["duration_scope"] = "live_since_task_creation"
            tasks.append(task)
        qualified = [task for task in tasks if task.get("status") == "qualified"]
        source_ids = {task["source_id"] for task in tasks if task.get("source_id")}
        productive = {task["source_id"] for task in qualified if task.get("source_id")}
        inputs = sum(call.get("input_tokens") or 0 for call in calls)
        outputs = sum(call.get("output_tokens") or 0 for call in calls)
        issues = [{"task_id": task.get("id"), **issue}
                  for task in tasks for issue in task.get("issues", [])]
        metrics = {
            "input_tokens": inputs, "output_tokens": outputs, "total_tokens": inputs + outputs,
            "cached_input_tokens": sum(call.get("cached_input_tokens") or 0 for call in calls),
            "llm_calls": len(calls), "unknown_usage_calls": sum(call.get("input_tokens") is None for call in calls),
            "active_llm_calls": sum(call.get("status") == "running" for call in calls),
            "unfinished_llm_calls": sum(call.get("completion_missing", False) for call in calls),
            "estimated_cost": None, "cost_status": "provider billing unavailable",
            "candidates": len(tasks), "unique_seeds": len(source_ids),
            "ready": sum(task.get("status") == "ready" for task in tasks),
            "productive_seeds": len(productive), "qualified": len(qualified),
            "rejected": sum(task.get("status") == "rejected" for task in tasks),
            "candidate_conversion": len(qualified) / len(tasks) if tasks else None,
            "source_conversion": len(productive) / len(source_ids) if source_ids else None,
            "tasks_per_seed": len(qualified) / len(source_ids) if source_ids else None,
            "cumulative_node_seconds": sum(node.get("duration_ms", 0) or 0 for node in tables["nodes"]) / 1000,
            "open_issues": sum(issue.get("status") not in {"resolved", "closed"} for issue in issues),
            "repair_rounds": sum(task.get("revision", 0) or 0 for task in tasks),
        }
        run = {
            **saved_run, "qualified": len(qualified),
            **{mode: sum(task.get("mode") == mode for task in qualified)
               for mode in ("financial_modeling", "debugging")},
        }
        stage_nodes = self._stages(tables["nodes"], calls)
        return {"run": run, "metrics": metrics, "tasks": tasks, "nodes": stage_nodes,
                "node_attempts": tables["nodes"],
                "llm_calls": calls, "issues": issues, "events": recent_events,
                "viewer": {"read_only": True, "source": "sqlite", "directory": str(self.directory),
                           "stage_time_scope": "Sum of completed recorded node durations; active elapsed time is separate.",
                           "stage_token_scope": "Known input plus output from all calls with matching stage, including retries. Cached input is a subset, not added again."}}

    @staticmethod
    def _stages(nodes: list[dict], calls: list[dict]) -> list[dict]:
        stages = {}
        for node in nodes:
            stage = node.get("node_id", node.get("node", "unknown"))
            group = stages.setdefault(stage, {"node_id": stage, "node": stage, "attempts": [], "calls": []})
            group["attempts"].append(node)
        for call in calls:
            stage = call.get("stage") or "unassigned_llm"
            group = stages.setdefault(stage, {"node_id": stage, "node": stage, "attempts": [], "calls": []})
            group["calls"].append(call)
        result = []
        for group in stages.values():
            attempts, stage_calls = group.pop("attempts"), group.pop("calls")
            active = [node for node in attempts if node.get("status") == "running"]
            active_calls = [call for call in stage_calls if call.get("status") == "running"]
            inputs = sum(call.get("input_tokens") or 0 for call in stage_calls)
            outputs = sum(call.get("output_tokens") or 0 for call in stage_calls)
            group.update({
                "count": len(attempts), "completed": sum(node.get("status") == "completed" for node in attempts),
                "failed_count": sum(node.get("status") == "failed" for node in attempts),
                "running_count": len(active), "active_llm_calls": len(active_calls),
                "status": "running" if active or active_calls else "completed",
                "cumulative_ms": sum(node.get("duration_ms") or 0 for node in attempts if node.get("status") != "running"),
                "running_elapsed_ms": sum(_milliseconds(node.get("started_at")) or 0 for node in active),
                "input_tokens": inputs, "output_tokens": outputs,
                "cached_input_tokens": sum(call.get("cached_input_tokens") or 0 for call in stage_calls),
                "total_tokens": inputs + outputs, "llm_call_count": len(stage_calls),
                "unknown_usage_calls": sum(call.get("input_tokens") is None or call.get("output_tokens") is None for call in stage_calls),
                "started_at": max((node.get("started_at", "") for node in active), default=None),
                "task_id": ", ".join(dict.fromkeys(str(node.get("task_id")) for node in active if node.get("task_id"))),
            })
            result.append(group)
        return result


class HistoricalDashboardServer(DashboardServer):
    """Use the existing offline page with an independent read-only viewer UI."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        extension = Path(__file__).with_name("static").joinpath("history.js").read_text()
        self._html = self._html.replace(b"</body>", ("<script>\n" + extension + "\n</script>\n</body>").encode())
