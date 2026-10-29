"""Program checks only conclude from supplied execution evidence."""

from __future__ import annotations

from .base import Assessment


def verifier_controls(controls: dict) -> Assessment:
    required = {"oracle": 1, "nop": 0, "equivalent": 1, "missed_root": 0, "extra_change": 0}
    missing = [name for name in required if name not in controls]
    if missing:
        return Assessment("Q05", "unknown", f"Missing verifier controls: {missing}", ["local_control_results"])
    bad = []
    for name, expected in required.items():
        value = controls[name]
        if isinstance(value, dict):
            actual = value.get("actual", value.get("reward"))
            if value.get("error"):
                actual = None
        else:
            actual = value
        if actual != expected:
            bad.append({"control": name, "actual": actual, "expected": expected})
    if bad:
        return Assessment("Q05", "flagged", "Verifier regression controls failed", bad)
    return Assessment("Q05", "clear", "All required positive and negative controls matched", [
        {"control": k, "result": v} for k, v in controls.items() if k in required
    ])


def engine_compatibility(bundle: dict) -> Assessment:
    report = bundle.get("engine_report", bundle.get("private", {}).get("engine_report", {}))
    required = ("normalization_ok", "recalculation_ok", "stable")
    missing = [key for key in required if key not in report]
    if missing:
        return Assessment("Q10", "unknown", f"Missing engine evidence: {missing}", ["engine_report"])
    if any(report[key] is not True for key in required):
        return Assessment("Q10", "flagged", "Normalization, recalculation or stability failed", [report])
    if report.get("unresolved_external_links") or report.get("unsupported_target_dependencies"):
        return Assessment("Q10", "flagged", "Unresolved dependencies affect target scope", [report])
    return Assessment("Q10", "clear", "Recorded normalization, full recalculation and stability succeeded", [report])


def infrastructure(bundle: dict, traces: list[dict]) -> Assessment:
    health = bundle.get("infrastructure_health_report", {})
    errors = []
    for trial in traces:
        if trial.get("infrastructure_error"):
            errors.append({"trial_id": trial.get("trial_id"), "error": trial["infrastructure_error"]})
        for event in trial.get("events", []):
            if event.get("error_category") in {"infrastructure", "service", "mount", "process_failure"}:
                errors.append(event)
    if errors or health.get("healthy") is False:
        return Assessment("Q11", "flagged", "Observed infrastructure failure", errors or [health])
    if health.get("healthy") is True and health.get("checks"):
        return Assessment("Q11", "clear", "Explicit infrastructure probes succeeded; no observed infra errors", [health])
    return Assessment("Q11", "unknown", "Infrastructure health probes are not available", ["infrastructure_health_report"])


def diagnostic_coverage(assessments: dict, enabled: list[str], issues: list[dict]) -> Assessment:
    others = [check for check in enabled if check != "Q12"]
    unknown = [check for check in others if check not in assessments or assessments[check]["state"] == "unknown"]
    empty = [check for check in others if check in assessments
             and assessments[check]["state"] in {"clear", "flagged"}
             and not assessments[check].get("evidence")]
    if unknown or empty:
        return Assessment("Q12", "flagged", "Enabled diagnosis has unresolved evidence gaps", [
            {"unknown_checks": unknown, "unsupported_assessments": empty}
        ])
    return Assessment("Q12", "clear", "All enabled non-meta checks returned supported assessments", [
        {"checked_ids": others, "issue_count": len(issues)}
    ])
