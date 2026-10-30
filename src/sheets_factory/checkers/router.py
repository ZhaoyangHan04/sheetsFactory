"""Deterministic issue routing; solve completion is deliberately absent."""

from __future__ import annotations


def route_issues(issues: list[dict], catalog: dict, difficulty_deferred: bool = False) -> list[dict]:
    specs = {p["problem_id"]: p for p in catalog["problems"]}
    issue_ids = {i["issue_id"] for i in issues}
    pending = {i["issue_id"]: i for i in issues}
    routes = []
    resolved = set()
    while pending:
        ready = []
        for key, issue in pending.items():
            dependencies = set(issue.get("depends_on_issue_ids", []))
            if dependencies - issue_ids:
                raise ValueError(f"Unknown issue dependencies for {key}: {dependencies - issue_ids}")
            if dependencies <= resolved:
                ready.append(issue)
        if not ready:
            raise ValueError("Cyclic issue dependencies")
        ready.sort(key=lambda i: (specs[i["problem_id"]]["priority"], i["issue_id"]))
        for issue in ready:
            spec = specs[issue["problem_id"]]
            suspected = issue.get("certainty") != "confirmed"
            destination = (specs["Q12"] if suspected else
                           specs["Q11"] if issue.get('attribution') == 'environment_failure' else spec)
            deferred = difficulty_deferred and issue["problem_id"] == "Q08"
            routes.append({
                "issue_id": issue["issue_id"],
                "problem_id": issue["problem_id"],
                "route_id": destination["route_id"],
                "route_class": destination["route_class"],
                "owner_stage": destination["owner_stage"],
                "allowed_actions": destination["allowed_actions"],
                "invalidated_artifacts": destination["invalidated_artifacts"],
                "required_rechecks": destination["required_rechecks"],
                "depends_on_issue_ids": issue.get("depends_on_issue_ids", []),
                "disposition": "deferred_by_run_scope" if deferred else "action_required",
            })
            resolved.add(issue["issue_id"])
            del pending[issue["issue_id"]]
    return routes
