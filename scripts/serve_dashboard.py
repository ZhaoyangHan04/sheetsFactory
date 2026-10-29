#!/usr/bin/env python3
"""Serve a live or completed run without starting a pipeline or loading secrets."""
from __future__ import annotations

import argparse
from pathlib import Path
import signal
import sqlite3
import sys
import threading
import webbrowser

# Work directly from a checkout without installing model or spreadsheet deps.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sheets_factory.dashboard import DashboardServer
from sheets_factory.dashboard.read_only import ReadOnlyAuditView


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only live/historical sheetsFactory run viewer")
    parser.add_argument("--run", required=True, type=Path, help="Directory containing run.sqlite")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args(argv)
    try:
        view = ReadOnlyAuditView(args.run)
        view.snapshot()  # Validate the existing database without updating it.
        server = DashboardServer(view.snapshot, view.events, host=args.host, port=args.port)
        url = server.start()
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(2, "Cannot open run viewer: " + str(error) + "\n")
    print("Read-only run dashboard: " + url, flush=True)
    print("Run: " + str(view.directory) + " — Ctrl+C to stop viewing", flush=True)
    if args.open_browser:
        webbrowser.open(url)
    stopping = threading.Event()
    previous = {}

    def request_stop(signum, frame):
        stopping.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, request_stop)
    try:
        stopping.wait()
    finally:
        server.stop()
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
