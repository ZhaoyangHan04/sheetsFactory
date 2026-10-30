"""Registry-driven diagnosis with isolated public and private LLM batches."""

from __future__ import annotations

import hashlib
from copy import deepcopy
import importlib
import json
from pathlib import Path
from typing import Callable
from uuid import uuid4

import yaml

from .base import Assessment
from .program import diagnostic_coverage, engine_compatibility, infrastructure, verifier_controls
from .router import route_issues

_STATES = {"clear", "flagged", "unknown", "not_applicable"}
_BANNED_OBSERVATION_KEYS = {"reward", "solved", "completed_successfully", "completion_status", "pass_at_1"}
_ATTRIBUTIONS = {"task_defect", "reference_defect", "agent_behavior", "environment_failure", "unresolved"}
_ARTIFACT_SCOPES = {"public_input", "public_instruction", "reference_goal", "verifier",
                    "runtime", "solver_output", "solver_trace", "unknown"}
_AGENT_ARTIFACTS = {"solver_output", "solver_trace"}
FINDING_ATTRIBUTION_CONTRACT = 1


def _clean_trace(value):
    if isinstance(value, dict):
        return {k: _clean_trace(v) for k, v in value.items() if k not in _BANNED_OBSERVATION_KEYS}
    if isinstance(value, list):
        return [_clean_trace(v) for v in value]
    return value


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


class DiagnosisRunner:
    def __init__(self, project_root: str | Path | None = None, program_handlers: dict | None = None):
        self.root = Path(project_root) if project_root else Path(__file__).resolve().parents[3]
        self.registry = yaml.safe_load((self.root / "config/checkers.yaml").read_text())
        self.catalog = yaml.safe_load((self.root / "config/routes.yaml").read_text())
        self.specs = {s["id"]: s for s in self.registry["checkers"]}
        if len(self.specs) != len(self.registry["checkers"]):
            raise ValueError("Duplicate checker IDs")
        routes = {s["problem_id"] for s in self.catalog["problems"]}
        if set(self.specs) - routes:
            raise ValueError("Enabled checker has no problem/repair route")
        self.program_handlers = {
            "verifier_controls_check": lambda context, spec, settings: verifier_controls(context["controls"]),
            "engine_compatibility_check": lambda context, spec, settings: engine_compatibility(context["bundle"]),
            "infrastructure_check": lambda context, spec, settings: infrastructure(context["bundle"], context["traces"]),
            "diagnostic_coverage_check": lambda context, spec, settings: diagnostic_coverage(
                context["assessments"], context["enabled"], context["issues"]),
        }
        self.program_handlers.update(program_handlers or {})
        for check_id, spec in self.specs.items():
            if spec["backend"] == "program" and spec["program_handler"] not in self.program_handlers:
                module_name, separator, attribute = spec["program_handler"].partition(":")
                if not separator:
                    raise ValueError(f"No implemented handler for {check_id}: {spec['program_handler']}")
                self.program_handlers[spec["program_handler"]] = getattr(importlib.import_module(module_name), attribute)

    def resolve(self, config: dict | None = None) -> dict:
        config = config or {}
        config = config.get("diagnosis", config)
        selection = config.get("selection", {})
        include = selection.get("include", "all")
        enabled = list(self.specs) if include == "all" else list(include)
        exclude = selection.get("exclude", [])
        if len(enabled) != len(set(enabled)) or len(exclude) != len(set(exclude)):
            raise ValueError("Repeated checker selection")
        unknown = (set(enabled) | set(exclude)) - self.specs.keys()
        if unknown:
            raise ValueError(f"Unknown checker IDs: {sorted(unknown)}")
        enabled = [check for check in enabled if check not in exclude]
        visited, visiting = set(), set()
        def visit(check_id):
            if check_id in visiting:
                raise ValueError("Cyclic checker dependencies")
            if check_id in visited:
                return
            visiting.add(check_id)
            for dependency in self.specs[check_id].get("depends_on", []):
                if dependency not in enabled:
                    raise ValueError(f"Missing enabled dependency {dependency} for {check_id}")
                visit(dependency)
            visiting.remove(check_id)
            visited.add(check_id)
        for check_id in enabled:
            visit(check_id)
        mode = config.get("execution", {}).get("llm_batching", "grouped")
        if mode not in {"grouped", "per_check", "all_in_one"}:
            raise ValueError(f"Unsupported batching mode: {mode}")
        batches: dict[str, list[str]] = {}
        for check_id in enabled:
            spec = self.specs[check_id]
            if spec["backend"] == "program":
                continue
            override = config.get("overrides", {}).get(check_id, {})
            group = override.get("group", spec["group"])
            if mode == "per_check":
                group = check_id
            elif mode == "all_in_one":
                group = "compatible"
            # Visibility and model/tool identity remain hard batching boundaries.
            key = json.dumps([group, spec["visibility"], override.get("model"), override.get("tools")], sort_keys=True)
            batches.setdefault(key, []).append(check_id)
        plan = {"enabled_check_ids": enabled, "disabled_check_ids": [c for c in self.specs if c not in enabled],
                "batches": list(batches.values()), "llm_batching": mode,
                "difficulty_deferred": config.get("difficulty_deferred", False),
                "registry_hash": _digest(self.registry), "route_hash": _digest(self.catalog),
                "overrides": config.get("overrides", {})}
        plan["check_plan_hash"] = _digest(plan)
        return plan

    def diagnose(self, task_bundle: dict, traces: list, controls: dict,
                 reviewer_callable: Callable[[dict], dict] | None, config: dict | None = None,
                 *, batch_cache: dict | None = None) -> dict:
        plan = self.resolve(config)
        enabled = plan["enabled_check_ids"]
        revision = task_bundle.get("revision_hash", _digest(task_bundle.get("public", {})))
        task_id = task_bundle.get("task_id", "task")
        report = {"diagnostic_run_id": str(uuid4()), "task_revision_hash": revision,
                  "diagnostic_stage": "candidate_quality",
                  "difficulty_review_context": deepcopy(task_bundle.get("public", {}).get("difficulty_review_context", {})),
                  "check_plan_hash": plan["check_plan_hash"], "report_scope": "merged",
                  "scope": "all" if not plan["disabled_check_ids"] else "selected",
                  "assigned_check_ids": enabled, "enabled_check_ids": enabled,
                  "disabled_check_ids": plan["disabled_check_ids"], "plan": plan,
                  "assessments": {}, "issues": [], "observations": [], "evidence_requests": [],
                  "finding_attribution_contract": FINDING_ATTRIBUTION_CONTRACT,
                  "llm_batches": [], "execution_failures": []}
        cache_entries = batch_cache.setdefault('entries', {}) if batch_cache is not None else {}
        assessments = report["assessments"]
        for check_id in plan["disabled_check_ids"]:
            assessments[check_id] = Assessment(check_id, "skipped", "disabled_by_config").to_dict()
        for check_id in enabled:
            spec = self.specs[check_id]
            if spec["backend"] != "program" or spec.get("run_after_all_enabled_non_meta"):
                continue
            item = self.program_handlers[spec["program_handler"]](
                {"bundle": task_bundle, "traces": traces, "controls": controls}, spec, {})
            if item.check_id != check_id:
                raise ValueError("Program plugin returned a different checker ID")
            assessments[check_id] = item.to_dict()
            self._program_issue(report, task_id, revision, item)

        for batch in plan["batches"]:
            active = list(batch)
            if "Q08" in active and plan["difficulty_deferred"]:
                assessments["Q08"] = Assessment("Q08", "not_applicable",
                    "current_run_quality_only: difficulty gate deferred by explicit user scope",
                    ["run_config.diagnosis.difficulty_deferred=true"]).to_dict()
                active.remove("Q08")
            if not active:
                continue
            visibility = self.specs[active[0]]["visibility"]
            payload = {"task_id": task_id, "task_revision_hash": revision,
                       "task_revision": task_bundle.get('revision'),
                       "diagnostic_run_id": report["diagnostic_run_id"],
                       "check_plan_hash": plan["check_plan_hash"], "assigned_check_ids": active,
                       "visibility": visibility,
                       "checks": [{"id": c, "instructions": self.specs[c]["instructions"]} for c in active],
                       "public": task_bundle.get("public", {}), "traces": _clean_trace(traces),
                       "diagnostic_stage": "candidate_quality",
                       "finding_attribution_contract": FINDING_ATTRIBUTION_CONTRACT,
                       "difficulty_review_context": task_bundle.get("public", {}).get("difficulty_review_context", {}),
                       "rules": ["Diagnose every assigned check regardless of task completion.",
                                 "Only evidence-backed clear/flagged conclusions; otherwise unknown.",
                                 "Do not output accept/reject or route choices.",
                                 "A solver error alone is not a task defect.",
                                 "Attribute each finding to its actual artifact. Agent-only behavior is an observation, not a task issue.",
                                 "A clear assessment may include agent observations. Flagged requires a task, reference, or environment issue; unknown requires evidence collection.",
                                 "Missing assumptions require a missing public source and result impact.",
                                 "Original formula existence alone is not proof of reference correctness."],
                       "required_output": {"assessments": [{"check_id": "assigned ID", "state":
                            "clear|flagged|unknown|not_applicable", "reason": "explanation", "evidence": ["source/evidence"]}],
                            "issues": [{"problem_id": "assigned ID", "claim": "specific defect", "evidence": ["source"],
                                        "certainty": "confirmed|suspected", "severity": "blocker|warning",
                                        "attribution": "task_defect|reference_defect|agent_behavior|environment_failure|unresolved",
                                        "artifact_scope": ["public_input|public_instruction|reference_goal|verifier|runtime|solver_output|solver_trace|unknown"]}],
                            "evidence_requests": []}}
            if visibility != "public_only":
                payload["private"] = task_bundle.get("private", {})
                payload["public_diagnosis"] = {k: v for k, v in assessments.items()
                                               if self.specs[k]["visibility"] == "public_only"}
            stable_payload = {key: value for key, value in payload.items() if key != 'diagnostic_run_id'}
            payload_digest = _digest(stable_payload)
            fingerprint = _digest({'payload_digest': payload_digest,
                                   'reviewer_context_hash': task_bundle.get('reviewer_context_hash')})
            receipt = {'assigned_check_ids': active, 'visibility': visibility,
                       'batch_fingerprint': fingerprint, 'payload_digest': payload_digest, 'cache_hit': False}
            try:
                cached = cache_entries.get(fingerprint)
                if cached:
                    result = deepcopy(cached['result'])
                    receipt.update(cache_hit=True, origin_diagnostic_run_id=cached['diagnostic_run_id'])
                else:
                    if reviewer_callable is None:
                        raise RuntimeError("No reviewer backend configured")
                    result = reviewer_callable(payload)
                if isinstance(result, str):
                    result = json.loads(result)
                if not isinstance(result, dict):
                    raise ValueError('Reviewer backend must return a JSON object')
                if "payload" in result:
                    result = result["payload"]
                self._merge_batch(report, result, active, task_id, revision)
                receipt['status'] = 'completed'
                report['llm_batches'].append(receipt)
                # Semantic uncertainty remains an evidence request. It must not
                # become a permanent cached answer to a repeated probe.
                cacheable = (all(assessments[check]['state'] != 'unknown' for check in active)
                    and not any(issue.get('certainty', 'suspected') != 'confirmed' for issue in result.get('issues', [])))
                if cacheable:
                    cache_entries[fingerprint] = {'result': deepcopy(result),
                        'diagnostic_run_id': report['diagnostic_run_id'], 'payload_digest': payload_digest,
                        'task_revision_hash': revision, 'check_plan_hash': plan['check_plan_hash'],
                        'visibility': visibility, 'assigned_check_ids': active}
            except Exception as exc:
                cache_entries.pop(fingerprint, None)
                for check_id in active:
                    assessments[check_id] = Assessment(check_id, "unknown", f"Diagnosis batch failed: {type(exc).__name__}: {exc}",
                                                        execution_status="failed").to_dict()
                receipt.update(status='failed', error=str(exc), error_type=type(exc).__name__)
                report['llm_batches'].append(receipt)
                self._backend_failure(report, task_id, revision, receipt)

        for check_id in enabled:
            spec = self.specs[check_id]
            if spec["backend"] == "program" and spec.get("run_after_all_enabled_non_meta"):
                coverage = self.program_handlers[spec["program_handler"]](
                    {"bundle": task_bundle, "traces": traces, "controls": controls,
                     "assessments": assessments, "enabled": enabled, "issues": report["issues"]}, spec, {})
                assessments[check_id] = coverage.to_dict()
                self._program_issue(report, task_id, revision, coverage)
        # Protocol completeness remains mandatory even if Q12 is disabled.
        for check_id in enabled:
            if check_id not in assessments:
                assessments[check_id] = Assessment(check_id, "unknown", "No handler result", execution_status="failed").to_dict()
        report["routes"] = route_issues(report["issues"], self.catalog, plan["difficulty_deferred"])
        blocking = [i["issue_id"] for i in report["issues"] if i.get("severity", "blocker") == "blocker"
                    and not (i["problem_id"] == "Q08" and plan["difficulty_deferred"])]
        warnings = [i["issue_id"] for i in report["issues"] if i.get("severity") == "warning"
                    and not (i["problem_id"] == "Q08" and plan["difficulty_deferred"])]
        unknown = [c for c in enabled if assessments[c]["state"] == "unknown"]
        report["coverage"] = {"enabled_count": len(enabled), "assessed_count": len(enabled) - len(unknown),
                              "unknown_check_ids": unknown, "blocking_issue_ids": blocking,
                              "undispositioned_warning_ids": warnings}
        report["releasable"] = not blocking and not unknown and not warnings
        return report

    def _backend_failure(self, report, task_id, revision, receipt):
        """Execution/protocol failures are Q11, never missing business inputs."""
        issue_id = f"{task_id}-Q11-diagnose-{receipt['batch_fingerprint'][:12]}"
        evidence = {'fault_stage': 'diagnose', 'visibility': receipt['visibility'],
                    'assigned_check_ids': receipt['assigned_check_ids'],
                    'batch_fingerprint': receipt['batch_fingerprint'], 'error_type': receipt['error_type'],
                    'error': receipt['error']}
        report['execution_failures'].append(evidence)
        report['issues'].append({'issue_id': issue_id, 'problem_id': 'Q11', 'certainty': 'confirmed',
            'severity': 'blocker', 'claim': 'Diagnosis backend execution or response protocol failed',
            'evidence': [evidence], 'fault_stage': 'diagnose', 'revision_hash': revision,
            'depends_on_issue_ids': []})
        if 'Q11' in report['enabled_check_ids']:
            assessment = report['assessments']['Q11']
            assessment.update(state='flagged', reason='Diagnosis backend execution or response protocol failed',
                              execution_status='failed')
            assessment.setdefault('evidence', []).append(evidence)
            assessment.setdefault('issue_ids', []).append(issue_id)
        report['evidence_requests'].append({'check_ids': receipt['assigned_check_ids'],
            'reason': 'retry_failed_backend_batch', 'fault_stage': 'diagnose',
            'batch_fingerprint': receipt['batch_fingerprint']})

    def _program_issue(self, report: dict, task_id: str, revision: str, result: Assessment):
        if result.state != "flagged":
            return
        issue_id = f"{task_id}-{result.check_id}-program"
        result_dict = report["assessments"][result.check_id]
        result_dict["issue_ids"] = [issue_id]
        report["issues"].append({"issue_id": issue_id, "problem_id": result.check_id,
            "claim": result.reason, "evidence": result.evidence, "certainty": "confirmed",
            "severity": "blocker", "revision_hash": revision, "depends_on_issue_ids": []})

    def _merge_batch(self, report: dict, result: dict, assigned: list[str], task_id: str, revision: str):
        if any(k in result for k in ("accept", "reject", "releasable", "routes", "next_action")):
            raise ValueError("Reviewer may not make release or routing decisions")
        items = result.get("assessments", [])
        if isinstance(items, dict):
            items = [dict(v, check_id=k) for k, v in items.items()]
        returned = [a.get("check_id", a.get("id")) for a in items]
        if len(returned) != len(set(returned)) or set(returned) != set(assigned):
            raise ValueError("Batch must return exactly its assigned check IDs once")
        parsed = {}
        for item, check_id in zip(items, returned):
            state = item.get("state")
            if state not in _STATES:
                raise ValueError(f"Invalid assessment state: {state}")
            if not item.get("reason"):
                raise ValueError("Assessment requires reason")
            evidence = item.get("evidence", [])
            if state in {"clear", "flagged"} and not evidence:
                state = "unknown"
            parsed[check_id] = Assessment(check_id, state, item["reason"], evidence).to_dict()
        issues, observations = [], []
        for index, issue in enumerate(result.get("issues", []), 1):
            check_id = issue.get("problem_id")
            if check_id not in assigned:
                raise ValueError("Issue problem ID was not assigned to this batch")
            if not issue.get("claim") or not issue.get("evidence"):
                raise ValueError("Issues require a claim and evidence")
            if issue.get("certainty", "suspected") not in {"confirmed", "suspected"}:
                raise ValueError("Invalid issue certainty")
            if issue.get("severity", "blocker") not in {"blocker", "warning"}:
                raise ValueError("Invalid issue severity")
            issue = dict(issue)
            attribution = issue.get('attribution')
            if attribution is not None:
                if attribution not in _ATTRIBUTIONS:
                    raise ValueError('Invalid finding attribution')
                scope = issue.get('artifact_scope')
                if (not isinstance(scope, list) or not scope or len(scope) != len(set(scope))
                        or any(not isinstance(value, str) or value not in _ARTIFACT_SCOPES for value in scope)):
                    raise ValueError('Finding attribution requires a nonempty valid artifact scope')
                agent_only = set(scope) <= _AGENT_ARTIFACTS
                if attribution == 'agent_behavior':
                    if not agent_only:
                        raise ValueError('Agent observations may concern only solver output or solver trace; split mixed findings')
                    observations.append({**issue, 'observation_id': f"{task_id}-{check_id}-agent-{len(report['observations']) + len(observations) + 1:03d}",
                                         'revision_hash': revision, 'disposition': 'record_only'})
                    continue
                if attribution in {'task_defect', 'reference_defect'} and agent_only:
                    raise ValueError('A solver artifact alone cannot establish a task or reference defect')
                if attribution == 'task_defect' and not {'public_input', 'public_instruction', 'reference_goal', 'verifier'}.intersection(scope):
                    raise ValueError('Task defect must identify the affected task artifact')
                if attribution == 'reference_defect' and 'reference_goal' not in scope:
                    raise ValueError('Reference defect must identify the affected reference artifact')
                if attribution == 'environment_failure' and not {'runtime', 'verifier'}.intersection(scope):
                    raise ValueError('Environment failure must identify runtime or verifier evidence')
                if attribution == 'unresolved':
                    issue['certainty'] = 'suspected'
            issue["issue_id"] = f"{task_id}-{check_id}-{len(report['issues']) + index:03d}"
            issue["revision_hash"] = revision
            issue.setdefault("certainty", "suspected")
            issue.setdefault("severity", "blocker")
            issue.setdefault("depends_on_issue_ids", [])
            parsed[check_id]["state"] = "flagged"
            parsed[check_id]["issue_ids"].append(issue["issue_id"])
            issues.append(issue)
        for check_id, item in parsed.items():
            if item["state"] == "flagged" and not item["issue_ids"]:
                raise ValueError(f"Flagged {check_id} requires an issue instance")
        report["assessments"].update(parsed)
        report["issues"].extend(issues)
        report['observations'].extend(observations)
        report["evidence_requests"].extend(result.get("evidence_requests", []))


def diagnose(task_bundle: dict, traces: list, controls: dict, reviewer_callable,
             config: dict | None = None, project_root: str | Path | None = None) -> dict:
    return DiagnosisRunner(project_root).diagnose(task_bundle, traces, controls, reviewer_callable, config)
