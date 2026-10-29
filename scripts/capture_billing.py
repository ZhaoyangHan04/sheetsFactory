#!/usr/bin/env python3
"""Capture private provider billing snapshots without exposing credentials.

Attribution is deliberately a shared-key time window, not exact run attribution.
The provider's response `id` can be a presentation ordinal and is never used
for de-duplication. Quota is authoritative; token equivalents are diagnostic.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid


UTC = timezone.utc
CONSUMPTION_TYPE = 2


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_time(value: str | int | float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp requires an explicit timezone")
    return parsed.timestamp()


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value))
        return parsed if parsed.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def numeric_json(value):
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


def other_fields(row: dict) -> dict:
    value = row.get("other", {})
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def extract_rows(response) -> list[dict]:
    if isinstance(response, list):
        rows = response
    elif isinstance(response, dict):
        rows = response.get("data", [])
        if isinstance(rows, dict):
            rows = rows.get("items", rows.get("logs", []))
    else:
        raise ValueError("Unsupported billing log response")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Billing log data must be a list of records")
    return rows


def event_identity(row: dict) -> tuple[str, str]:
    # `id` and account-facing names are intentionally absent. Request IDs may
    # repeat between an error and a later successful charge.
    stable = {key: row.get(key) for key in ("created_at", "type", "model_name")}
    request_id = row.get("request_id")
    if request_id:
        stable["request_id"] = request_id
        quality = "request_identity"
    else:
        stable.update({key: row.get(key) for key in (
            "quota", "prompt_tokens", "completion_tokens", "use_time")})
        stable["cache_tokens"] = other_fields(row).get("cache_tokens")
        quality = "content_fingerprint"
    digest = hashlib.sha256(json.dumps(stable, sort_keys=True,
                                      separators=(",", ":"), default=str).encode()).hexdigest()
    return digest, quality


def accounting_signature(row: dict) -> str:
    value = {key: row.get(key) for key in ("quota", "prompt_tokens", "completion_tokens")}
    value["other"] = other_fields(row)
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def merge_snapshot(ledger: dict, rows: list[dict], snapshot: dict) -> dict:
    events = ledger.setdefault("events", {})
    counts = {"new_events": 0, "duplicate_events": 0, "changed_event_versions": 0}
    for row in rows:
        key, quality = event_identity(row)
        existing = events.get(key)
        if existing:
            counts["duplicate_events"] += 1
            if accounting_signature(existing["record"]) != accounting_signature(row):
                existing.setdefault("previous_versions", []).append({
                    "record": existing["record"], "last_seen_at": existing["last_seen_at"]})
                counts["changed_event_versions"] += 1
            existing["record"] = row
            existing["last_seen_at"] = snapshot["captured_at"]
            existing["observations"] += 1
        else:
            counts["new_events"] += 1
            events[key] = {"record": row, "identity_quality": quality,
                           "first_seen_at": snapshot["captured_at"],
                           "last_seen_at": snapshot["captured_at"], "observations": 1}
    observed_times = [number(row.get("created_at")) for row in rows]
    observed_times = [float(t) for t in observed_times if t is not None]
    snapshot = {**snapshot, **counts, "returned_records": len(rows),
                "oldest_created_at": min(observed_times) if observed_times else None,
                "newest_created_at": max(observed_times) if observed_times else None}
    ledger.setdefault("snapshots", []).append(snapshot)
    return counts


def find_quota_per_unit(status) -> Decimal | None:
    if isinstance(status, dict):
        if "quota_per_unit" in status:
            result = number(status["quota_per_unit"])
            if result is not None and result > 0:
                return result
        for child in status.values():
            result = find_quota_per_unit(child)
            if result is not None:
                return result
    return None


def coverage_report(snapshots: list[dict], start: float, end: float) -> dict:
    intervals = []
    for item in snapshots:
        lower = item.get("oldest_created_at")
        if lower is None:
            continue
        upper = parse_time(item["captured_at"])
        if upper >= lower:
            intervals.append((float(lower), upper))
    merged = []
    for lower, upper in sorted(intervals):
        if merged and lower <= merged[-1][1]:
            merged[-1][1] = max(upper, merged[-1][1])
        else:
            merged.append([lower, upper])
    gaps, cursor = [], start
    for lower, upper in merged:
        if upper < start or lower > end:
            continue
        if lower > cursor:
            gaps.append([cursor, min(lower, end)])
        cursor = max(cursor, min(upper, end))
    if cursor < end:
        gaps.append([cursor, end])
    return {
        "observed_intervals_cover_window": not gaps,
        "window_start_observed": any(lower <= start <= upper for lower, upper in merged),
        "gaps_epoch_seconds": gaps,
        "intervals_epoch_seconds": merged,
        "coverage_basis": "Union of latest-log snapshot observation intervals; server pagination total is unknown.",
        "server_total_unknown": True,
        "in_flight_or_delayed_logs_may_be_missing": True,
        "exact_billing_completeness_certified": False,
    }


def summarize(ledger: dict, start: float, end: float,
              quota_per_unit: Decimal | None) -> dict:
    if end <= start:
        raise ValueError("Window end must be after its start")
    selected, invalid_timestamps = [], 0
    for event in ledger.get("events", {}).values():
        stamp = number(event["record"].get("created_at"))
        if stamp is None:
            invalid_timestamps += 1
        elif start <= float(stamp) < end:
            selected.append(event)

    def aggregate(events):
        totals = {key: Decimal(0) for key in (
            "quota", "prompt_tokens", "completion_tokens", "cache_read_tokens",
            "uncached_prompt_tokens", "weighted_token_equivalents")}
        unknown = Counter()
        for event in events:
            row = event["record"]
            details = other_fields(row)
            quota, prompt, completion, cached = [number(value) for value in (
                row.get("quota"), row.get("prompt_tokens"), row.get("completion_tokens"),
                details.get("cache_tokens"))]
            for key, value in (("quota", quota), ("prompt_tokens", prompt),
                               ("completion_tokens", completion)):
                if value is None:
                    unknown[key] += 1
                else:
                    totals[key] += value
            cache_valid = cached is not None and cached >= 0 and prompt is not None and 0 <= cached <= prompt
            if cache_valid:
                totals["cache_read_tokens"] += cached
                totals["uncached_prompt_tokens"] += prompt-cached
            else:
                unknown["cache_read_tokens"] += 1
                unknown["uncached_prompt_tokens"] += 1
            cache_ratio, completion_ratio = number(details.get("cache_ratio")), number(details.get("completion_ratio"))
            if cache_valid and completion is not None and cache_ratio is not None and completion_ratio is not None:
                totals["weighted_token_equivalents"] += prompt-cached + cached*cache_ratio + completion*completion_ratio
            else:
                unknown["weighted_token_equivalents"] += 1
        result = {key: numeric_json(value) for key, value in totals.items()}
        result.update({"requests": len(events),
                       "total_tokens": result["prompt_tokens"]+result["completion_tokens"],
                       "usd": numeric_json(totals["quota"]/quota_per_unit) if quota_per_unit else None,
                       "unknown_or_invalid_fields_requests": dict(unknown)})
        return result

    charged = [item for item in selected if item["record"].get("type") == CONSUMPTION_TYPE]
    models = defaultdict(list)
    for event in charged:
        models[str(event["record"].get("model_name", "unknown"))].append(event)
    non_consumption_quota = sum((number(item["record"].get("quota")) or Decimal(0)
                                 for item in selected if item["record"].get("type") != CONSUMPTION_TYPE), Decimal(0))
    return {
        "attribution": "shared_api_key_created_at_window_not_exact_run_attribution",
        "attribution_note": "Pilot or unrelated requests using the same key during this window are included. Requests are filtered by provider created_at, not attributed from CLI task IDs.",
        "window": {"start": iso(datetime.fromtimestamp(start, UTC)),
                   "end_exclusive": iso(datetime.fromtimestamp(end, UTC))},
        "quota_per_usd": numeric_json(quota_per_unit),
        "totals": aggregate(charged),
        "by_model": {model: aggregate(events) for model, events in sorted(models.items())},
        "event_type_counts": dict(Counter(str(item["record"].get("type")) for item in selected)),
        "non_consumption_quota_not_in_spend_total": numeric_json(non_consumption_quota),
        "unclassified_quota_requires_review": non_consumption_quota != 0,
        "invalid_timestamp_events": invalid_timestamps,
        "fallback_identity_events": sum(item["identity_quality"] == "content_fingerprint" for item in selected),
        "changed_event_versions": sum(len(item.get("previous_versions", [])) for item in selected),
        "deduplication": "request_id + created_at + type + model_name; content fingerprint if request_id absent; response ordinal id excluded",
        "token_accounting": "Prompt tokens include cached input. Total tokens = prompt + completion; cache is not added twice. Weighted equivalents apply cache/completion ratios before model/group factors and are not raw token counts. Quota is authoritative.",
        "coverage": coverage_report(ledger.get("snapshots", []), start, end),
    }


def private_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def fetch_json(base: str, path: str, key: str, timeout: int = 30):
    # urllib does not implement SOCKS transports. Honor this host's proxy
    # configuration through curl, passing credentials on stdin, never argv.
    proxies = urllib.request.getproxies()
    if any(urllib.parse.urlparse(value).scheme.startswith("socks")
           for name, value in proxies.items() if name in {"http", "https", "all"}):
        return fetch_json_curl(base, path, key, timeout)
    request = urllib.request.Request(base.rstrip("/")+path,
                                     headers={"Authorization": "Bearer "+key,
                                              "User-Agent": "sheetsFactory-billing/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
        if isinstance(result, dict) and result.get("success") is False:
            return {"ok": False, "http_status": 200, "response": result}
        return {"ok": True, "http_status": 200, "response": result}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "http_status": exc.code}
    except Exception:
        # Exception text can contain a private endpoint. Never surface it.
        return {"ok": False, "http_status": 0}


def fetch_json_curl(base: str, path: str, key: str, timeout: int = 30):
    if shutil.which("curl") is None:
        return {"ok": False, "http_status": 0, "transport_support_missing": 1}
    configuration = "\n".join([
        "url = "+json.dumps(base.rstrip("/")+path),
        "header = "+json.dumps("Authorization: Bearer "+key),
        "user-agent = \"sheetsFactory-billing/1.0\"",
    ])+"\n"
    try:
        result = subprocess.run([
            "curl", "--silent", "--show-error", "--max-time", str(timeout),
            "--config", "-", "--write-out", "\n%{http_code}",
        ], input=configuration, capture_output=True, text=True, timeout=timeout+5)
        if result.returncode:
            return {"ok": False, "http_status": 0}
        body, code = result.stdout.rsplit("\n", 1)
        status = int(code)
        # This provider canonicalizes the usage route with a trailing slash.
        # Retry only this known same-origin path; never forward a Bearer token
        # to an arbitrary Location header or another host.
        if status in {301, 302, 307, 308} and path == "/api/usage/token":
            return fetch_json_curl(base, path+"/", key, timeout)
        if status < 200 or status >= 300:
            return {"ok": False, "http_status": status}
        payload = json.loads(body)
        ok = not (isinstance(payload, dict) and payload.get("success") is False)
        return {"ok": ok, "http_status": status, "response": payload}
    except Exception:
        return {"ok": False, "http_status": 0}


def capture(project_root: Path, run_dir: Path, start: str, end: str | None = None,
            imports: list[Path] | None = None, timeout: int = 30) -> dict:
    project_root, run_dir = project_root.resolve(), run_dir.resolve()
    directory = run_dir/"private"/"billing_snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    key = (project_root/".secrets"/"api_key").read_text().strip()
    metadata = json.loads((project_root/".secrets"/"metadata.json").read_text())
    base = metadata["urls"][0].rstrip("/")
    if not key or urllib.parse.urlparse(base).scheme not in ("http", "https"):
        raise ValueError("Invalid private billing configuration")
    fingerprint = hashlib.sha256(key.encode()).hexdigest()[:24]
    captured_at = utc_now()
    snapshot_id = captured_at.strftime("%Y%m%dT%H%M%S%fZ")+"-"+uuid.uuid4().hex[:8]
    responses = {
        "usage": fetch_json(base, "/api/usage/token", key, timeout),
        "status": fetch_json(base, "/api/status", key, timeout),
        "logs": fetch_json(base, "/api/log/token?p=0&page_size=100", key, timeout),
    }
    finished_at = utc_now()
    raw_path = directory/"snapshots"/(snapshot_id+".json")
    private_json(raw_path, {"captured_at": iso(finished_at), "requested_at": iso(captured_at),
                            "credential_fingerprint": fingerprint, "responses": responses})
    ledger_path = directory/"ledger.json"
    lock_fd = os.open(directory/".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {
            "schema_version": 1, "credential_fingerprint": fingerprint, "events": {}, "snapshots": []}
        if ledger.get("credential_fingerprint") != fingerprint:
            raise ValueError("Billing directory belongs to a different credential")
        imported = set(ledger.setdefault("imported_snapshot_hashes", []))
        for path in imports or []:
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if digest in imported:
                continue
            payload = json.loads(data)
            captured = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            destination = directory/"imports"/(digest+".json")
            private_json(destination, payload)
            merge_snapshot(ledger, extract_rows(payload), {
                "snapshot_id": digest, "captured_at": iso(captured), "capture_time_source": "import_file_mtime",
                "raw_path": str(destination.relative_to(directory))})
            imported.add(digest)
        ledger["imported_snapshot_hashes"] = sorted(imported)
        if responses["logs"]["ok"]:
            merge_snapshot(ledger, extract_rows(responses["logs"]["response"]), {
                "snapshot_id": snapshot_id, "captured_at": iso(finished_at),
                "capture_time_source": "capture_finished_at", "requested_page_size": 100,
                "raw_path": str(raw_path.relative_to(directory))})
        quota_per_unit = find_quota_per_unit(responses["status"].get("response"))
        if quota_per_unit is not None:
            ledger["quota_per_usd"] = numeric_json(quota_per_unit)
        else:
            quota_per_unit = number(ledger.get("quota_per_usd"))
        ledger["updated_at"] = iso(finished_at)
        private_json(ledger_path, ledger)
        summary = summarize(ledger, parse_time(start), parse_time(end) if end else finished_at.timestamp(), quota_per_unit)
        summary["capture"] = {"captured_at": iso(finished_at),
                              "duration_seconds": (finished_at-captured_at).total_seconds(),
                              "endpoint_success": {name: result["ok"] for name, result in responses.items()},
                              "unique_ledger_events": len(ledger["events"]), "snapshots": len(ledger["snapshots"])}
        private_json(directory/"summary.json", summary)
        private_json(directory/"summaries"/(snapshot_id+".json"), summary)
        return summary
    finally:
        os.close(lock_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--start", default="2026-10-29T12:11:33Z")
    parser.add_argument("--end")
    parser.add_argument("--import-log-snapshot", type=Path, action="append", default=[])
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()
    try:
        result = capture(args.project_root, args.run_dir, args.start, args.end,
                         args.import_log_snapshot, args.timeout)
        totals = result["totals"]
        # Numeric-only stdout. Full attribution, coverage and model breakdowns
        # are private artifacts consumed explicitly by the reporting layer.
        print(json.dumps({"capture_success": int(all(result["capture"]["endpoint_success"].values())),
                          "requests_in_window": totals["requests"], "quota": totals["quota"],
                          "usd": totals["usd"], "prompt_tokens": totals["prompt_tokens"],
                          "completion_tokens": totals["completion_tokens"],
                          "cache_read_tokens": totals["cache_read_tokens"],
                          "observed_window_covered": int(result["coverage"]["observed_intervals_cover_window"]),
                          "ledger_events": result["capture"]["unique_ledger_events"]}))
        return 0 if all(result["capture"]["endpoint_success"].values()) else 2
    except Exception:
        print(json.dumps({"capture_success": 0, "error_count": 1}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
