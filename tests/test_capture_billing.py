"""Offline billing accounting tests. No provider requests are made here."""
from datetime import datetime, timezone
from decimal import Decimal
import importlib.util
import json
import os
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1]/"scripts"/"capture_billing.py"
SPEC = importlib.util.spec_from_file_location("capture_billing", SCRIPT)
billing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(billing)


def row(**changes):
    result = {"id": 1, "request_id": "request-a", "created_at": 100,
              "type": 2, "model_name": "model-a", "quota": 200,
              "prompt_tokens": 100, "completion_tokens": 20,
              "other": json.dumps({"cache_tokens": 60, "cache_ratio": 0.1,
                                   "completion_ratio": 5})}
    result.update(changes)
    return result


def snapshot(stamp=150):
    return {"snapshot_id": str(stamp), "captured_at": billing.iso(
        datetime.fromtimestamp(stamp, timezone.utc))}


def test_presentation_id_changes_do_not_duplicate_and_error_is_separate():
    ledger = {}
    billing.merge_snapshot(ledger, [row(id=14)], snapshot())
    counts = billing.merge_snapshot(ledger, [row(id=99), row(id=100, type=5, quota=0,
                                                           prompt_tokens=0, completion_tokens=0)], snapshot(160))
    assert len(ledger["events"]) == 2
    assert counts["duplicate_events"] == 1
    assert counts["new_events"] == 1
    assert counts["changed_event_versions"] == 0


def test_changed_accounting_event_is_replaced_with_audit_not_double_counted():
    ledger = {}
    billing.merge_snapshot(ledger, [row(quota=200)], snapshot())
    billing.merge_snapshot(ledger, [row(quota=300, id=82)], snapshot(160))
    summary = billing.summarize(ledger, 90, 160, Decimal(500000))
    assert summary["totals"]["requests"] == 1
    assert summary["totals"]["quota"] == 300
    assert summary["changed_event_versions"] == 1


def test_window_attribution_model_breakdown_and_cache_not_double_counted():
    ledger = {}
    billing.merge_snapshot(ledger, [row(), row(request_id="old", created_at=89),
                                   row(request_id="other", model_name="model-b", created_at=110),
                                   row(request_id="end", created_at=120)], snapshot())
    summary = billing.summarize(ledger, 90, 120, Decimal(500000))
    assert summary["totals"]["requests"] == 2
    assert summary["totals"]["quota"] == 400
    assert summary["totals"]["usd"] == 0.0008
    assert summary["totals"]["prompt_tokens"] == 200
    assert summary["totals"]["completion_tokens"] == 40
    assert summary["totals"]["total_tokens"] == 240
    assert summary["totals"]["cache_read_tokens"] == 120
    assert summary["totals"]["uncached_prompt_tokens"] == 80
    assert summary["totals"]["weighted_token_equivalents"] == 292
    assert set(summary["by_model"]) == {"model-a", "model-b"}
    assert summary["attribution"] == "shared_api_key_created_at_window_not_exact_run_attribution"


def test_missing_cache_usage_and_conversion_are_marked_unknown():
    ledger = {}
    billing.merge_snapshot(ledger, [row(other="{}")], snapshot())
    result = billing.summarize(ledger, 90, 120, None)
    assert result["totals"]["usd"] is None
    assert result["totals"]["unknown_or_invalid_fields_requests"]["cache_read_tokens"] == 1
    assert result["totals"]["unknown_or_invalid_fields_requests"]["uncached_prompt_tokens"] == 1


def test_coverage_merges_overlaps_and_reports_retention_gaps():
    captures = [{**snapshot(150), "oldest_created_at": 80},
                {**snapshot(200), "oldest_created_at": 140}]
    assert billing.coverage_report(captures, 90, 190)["observed_intervals_cover_window"]
    captures.append({**snapshot(300), "oldest_created_at": 250})
    result = billing.coverage_report(captures, 90, 290)
    assert not result["observed_intervals_cover_window"]
    assert result["gaps_epoch_seconds"] == [[200.0, 250.0]]
    assert result["in_flight_or_delayed_logs_may_be_missing"]
    assert not result["exact_billing_completeness_certified"]


def test_fallback_identity_ignores_response_ordinals():
    first, quality = billing.event_identity(row(request_id="", id=1))
    second, _ = billing.event_identity(row(request_id="", id=999))
    assert first == second
    assert quality == "content_fingerprint"


def test_capture_is_private_repeatable_and_import_is_idempotent(tmp_path, monkeypatch):
    root, run = tmp_path/"project", tmp_path/"run"
    secrets = root/".secrets"
    secrets.mkdir(parents=True)
    key = "test-key-do-not-expose"
    (secrets/"api_key").write_text(key)
    (secrets/"metadata.json").write_text(json.dumps({"urls": ["https://provider.invalid"]}))
    stamp = datetime(2026, 10, 29, 12, 30, tzinfo=timezone.utc)
    event_time = int(stamp.timestamp())-60
    logs = {"success": True, "data": [row(created_at=event_time)]}
    imported = tmp_path/"probe.json"
    imported.write_text(json.dumps({"data": [row(created_at=event_time, id=44)]}))
    os.utime(imported, (stamp.timestamp()-30, stamp.timestamp()-30))

    def fake_fetch(base, path, token, timeout):
        assert token == key
        if path.startswith("/api/log/"):
            value = logs
        elif path == "/api/status":
            value = {"data": {"quota_per_unit": 500000}}
        else:
            value = {"data": {"used_quota": 200, "private_account_name": "private"}}
        return {"ok": True, "http_status": 200, "response": value}

    monkeypatch.setattr(billing, "fetch_json", fake_fetch)
    monkeypatch.setattr(billing, "utc_now", lambda: stamp)
    start = "2026-10-29T12:11:33Z"
    first = billing.capture(root, run, start, imports=[imported])
    second = billing.capture(root, run, start, imports=[imported])
    assert first["totals"]["quota"] == second["totals"]["quota"] == 200
    assert second["capture"]["unique_ledger_events"] == 1
    directory = run/"private"/"billing_snapshots"
    assert directory.stat().st_mode & 0o777 == 0o700
    for path in directory.rglob("*.json"):
        assert path.stat().st_mode & 0o777 == 0o600
        assert key not in path.read_text()
    ledger = json.loads((directory/"ledger.json").read_text())
    assert len(ledger["snapshots"]) == 3  # one import, two fresh snapshots
    assert len(ledger["imported_snapshot_hashes"]) == 1


def test_rejects_timezone_free_window():
    with pytest.raises(ValueError):
        billing.parse_time("2026-10-29T12:11:33")


def test_curl_proxy_transport_keeps_key_out_of_arguments(monkeypatch):
    from types import SimpleNamespace
    key = "credential-never-in-argv"
    monkeypatch.setattr(billing.shutil, "which", lambda name: "/usr/bin/curl")

    def fake_run(arguments, **options):
        assert key not in " ".join(arguments)
        assert key in options["input"]
        assert "--config" in arguments
        return SimpleNamespace(returncode=0, stdout='{"success":true,"data":[]}\n200')

    monkeypatch.setattr(billing.subprocess, "run", fake_run)
    assert billing.fetch_json_curl("https://provider.invalid", "/api/log/token", key)["ok"]


def test_usage_redirect_retries_only_known_same_origin_path(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(billing.shutil, "which", lambda name: "/usr/bin/curl")
    seen = []

    def fake_run(arguments, **options):
        configuration = options["input"]
        seen.append(configuration)
        if len(seen) == 1:
            return SimpleNamespace(returncode=0, stdout="redirect\n301")
        assert '/api/usage/token/"' in configuration
        assert "provider.invalid" in configuration
        return SimpleNamespace(returncode=0, stdout='{"data":{"used_quota":10}}\n200')

    monkeypatch.setattr(billing.subprocess, "run", fake_run)
    assert billing.fetch_json_curl("https://provider.invalid", "/api/usage/token", "secret")["ok"]
    assert len(seen) == 2
