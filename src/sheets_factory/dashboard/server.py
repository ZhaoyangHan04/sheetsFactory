"""Read-only local dashboard with HTTP snapshots and resumable SSE events."""

from __future__ import annotations

import errno
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit


_SENSITIVE_KEYS = {
    "api_key", "apikey", "access_token", "refresh_token", "authorization",
    "password", "secret", "credentials", "auth_headers", "private_key",
}
_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")


def _safe(value: Any) -> Any:
    """Redact conventional secret fields without hiding token-use statistics."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in _SENSITIVE_KEYS else _safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, str):
        return _KEY_PATTERN.sub("[REDACTED]", value)
    return value


def _event_id(event: dict[str, Any]) -> int | None:
    try:
        result = int(event.get("id", event.get("event_id")))
        return result if result >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class DashboardServer:
    """Serve dashboard data; callbacks remain the application's source of truth.

    ``events(after)`` returns events whose monotonically increasing integer
    ``id`` (or ``event_id``) exceeds ``after``. Both callbacks must be safe to
    call from request threads. No application artifacts are exposed as files.
    """

    def __init__(
        self,
        snapshot: Callable[[], dict],
        events: Callable[[int], list[dict]],
        host: str = "127.0.0.1",
        port: int = 8765,
    ):
        self.snapshot = snapshot
        self.events = events
        self.host = host
        self.port = port
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._html = Path(__file__).with_name("static").joinpath("index.html").read_bytes()

    @property
    def url(self) -> str | None:
        if self._server is None:
            return None
        host = self._server.server_address[0]
        if ":" in host:
            host = f"[{host}]"
        # A wildcard bind is accessed locally through loopback.
        if host == "0.0.0.0":
            host = "127.0.0.1"
        return f"http://{host}:{self._server.server_port}/"

    def _read_events(self, after: int) -> list[dict]:
        rows = self.events(after)
        return sorted(
            [_safe(event) for event in rows if isinstance(event, dict)
             and _event_id(event) is not None and _event_id(event) > after],
            key=lambda event: _event_id(event),
        )

    def start(self) -> str:
        if self._server is not None:
            return self.url  # type: ignore[return-value]
        self._stop.clear()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                # Never send event content, URLs, or credentials to terminal logs.
                return

            def _headers(self, status: int, content_type: str, length: int | None = None) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
                if length is not None:
                    self.send_header("Content-Length", str(length))
                self.end_headers()

            def _json(self, value: Any, status: int = 200) -> None:
                body = json.dumps(_safe(value), ensure_ascii=False, default=str, allow_nan=False).encode("utf-8")
                self._headers(status, "application/json; charset=utf-8", len(body))
                self.wfile.write(body)

            def do_GET(self) -> None:
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query)
                try:
                    after = max(0, int(query.get("after", [self.headers.get("Last-Event-ID", "0")])[0]))
                except (ValueError, TypeError):
                    self._json({"error": "invalid_event_cursor"}, 400)
                    return
                try:
                    if parsed.path == "/":
                        self._headers(200, "text/html; charset=utf-8", len(owner._html))
                        self.wfile.write(owner._html)
                    elif parsed.path == "/api/snapshot":
                        self._json(owner.snapshot())
                    elif parsed.path == "/api/events":
                        self._json({"events": owner._read_events(after)})
                    elif parsed.path == "/api/stream":
                        self._stream(after)
                    else:
                        self._json({"error": "not_found"}, 404)
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    return
                except Exception:
                    # Provider exceptions may contain endpoint keys or file paths.
                    self._json({"error": "dashboard_data_unavailable"}, 503)

            def _stream(self, after: int) -> None:
                self._headers(200, "text/event-stream; charset=utf-8")
                self.wfile.write(b"retry: 2000\n: connected\n\n")
                self.wfile.flush()
                ticks = 0
                while not owner._stop.is_set():
                    try:
                        batch = owner._read_events(after)
                    except Exception:
                        self.wfile.write(b"event: unavailable\ndata: {}\n\n")
                        self.wfile.flush()
                        self.close_connection = True
                        return
                    for event in batch:
                        event_id = _event_id(event)
                        if event_id is None or event_id <= after:
                            continue
                        payload = json.dumps(event, ensure_ascii=False, default=str, allow_nan=False)
                        self.wfile.write(f"id: {event_id}\nevent: update\ndata: {payload}\n\n".encode("utf-8"))
                        after = event_id
                    if batch or ticks % 20 == 0:
                        if not batch:
                            self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                    ticks += 1
                    owner._stop.wait(0.5)
                self.close_connection = True

        try:
            self._server = _Server((self.host, self.port), Handler)
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE:
                raise
            self._server = _Server((self.host, 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="sheets-dashboard", daemon=True)
        self._thread.start()
        return self.url  # type: ignore[return-value]

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
