#!/usr/bin/env python3
"""Prepare or run four isolated semantic reviews of one new bridge source."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import yaml
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard.server import DashboardServer
from sheets_factory.llm.codex import CodexCLI
from sheets_factory.llm.schemas import diagnosis_output_schema

PUBLIC = ["Q01", "Q02", "Q03", "Q07", "Q08"]
PRIVATE = ["Q04", "Q05", "Q06", "Q09", "Q10", "Q11", "Q12"]
ALL = [f"Q{i:02d}" for i in range(1, 13)]
SEMANTIC = ["Q01", "Q02", "Q03", "Q04", "Q07"]
MODES = ("financial_modeling", "debugging")
PROMPT = ROOT / "prompts/diagnosis_professional_review_v1.md"
PROFILE = ROOT / "config/runtime_profiles/entity_group_large_v2.yaml"
INSPECT = ('{"Id":{{json .Id}},"Name":{{json .Name}},"Image":{{json .Image}},'
           '"NanoCpus":{{.HostConfig.NanoCpus}},"Memory":{{.HostConfig.Memory}},'
           '"PidsLimit":{{.HostConfig.PidsLimit}}}')


def require(value, message):
    if not value:
        raise ValueError(message)


def ref(path):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_file() and not path.is_symlink(), "Use a real evidence file")
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def read(record):
    if isinstance(record, (str, Path)):
        record = ref(record)
    require(ref(record["path"]) == record, "A new-source evidence binding changed")
    return json.loads(Path(record["path"]).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
    return ref(path)


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def prepare(batch_path, output):
    """Require actual completed engineering; prepare workspaces without a call."""
    output = Path(output).absolute()
    require(output == output.resolve() and not output.exists(), "Use a fresh review namespace")
    batch_ref = ref(batch_path)
    batch = read(batch_ref)
    require(batch.get("kind") == "individually_engineered_business_revision_batch"
        and batch.get("count") == 2 and batch.get("actual_LO_calls_completed") == 5,
        "Require the actual completed two-mode new-source engineering batch")
    source_ref = batch["source"]
    source = read(source_ref)
    require(source.get("kind") == "independently_verified_associate_bridge_business_source_v1"
        and source.get("passed") is True and source.get("actual_LO_calls_completed") == 3
        and source.get("complete_AB_financial_fields") == 93510,
        "Do not inherit the previous source or its healthy-reference qualification")
    specification = read(source["specification"])
    require(specification.get("kind") == "associate_bridge_business_spec_v1"
        and specification.get("case_id") == source.get("case_id"), "Bind the new public bridge contract")
    records = source["independent_records"]
    a, b = read(records["A"]), read(records["B"])
    for result in (a, b):
        require(result.get("kind") == "associate_bridge_values_v1"
            and result.get("specification_sha256") == canonical(specification)
            and len(result.get("typed_2dp_values", {})) == 93510
            and result.get("reconciliation_checks", {}).get("passed") is True,
            "Each complete independent oracle must bind this new bridge specification")
    require(all(a[layer] == b[layer] for layer in
        ("economic_exact_values", "raw_cell_exact_values", "typed_2dp_values"))
        and read(records["independent_comparison"]).get("passed") is True,
        "The new source requires actual full-scope independent agreement")
    require(len(source["actual_LO_calls"]) == 3, "Retain each of the three actual source calls")
    for index, call in enumerate(source["actual_LO_calls"], 1):
        checked = read(call["audit"])
        require(call["index"] == index and checked.get("passed") is True
            and checked.get("all_financial_fields_checked") == 93510
            and not checked.get("native_errors") and not checked.get("unresolved_mismatches")
            and isinstance(call.get("native_metadata"), dict), "A source call lacks its actual full audit")
        require(ref(call["workbook"]["path"]) == call["workbook"], "An actual source workbook changed")
    require(ref(source["goal"]["path"]) == source["goal"], "The new healthy reference changed")
    tasks = batch["tasks"]
    require(len(tasks) == 2 and {t["mode"] for t in tasks} == set(MODES), "Require one task per mode")
    bindings = []
    for task in tasks:
        require(task["source_id"] == source["goal"]["sha256"], "A task points at a different goal")
        engineering = read(task["individual_engineering"])
        require(engineering.get("passed") is True and engineering.get("source") == source_ref
            and engineering.get("native_error_count") == 0 and engineering.get("given_literals_unchanged") is True
            and engineering.get("sheet_structure_unchanged") is True
            and engineering.get("complete_primary_difference_count", 0) > 0,
            "Each reviewed material needs its actual native and protected-fact evidence")
        task_dir = Path(task["task_directory"])
        input_ref, brief_ref = ref(task_dir / "environment/input.xlsx"), ref(task_dir / "instruction.md")
        require(ref(task_dir / "solution/reference.xlsx")["sha256"] == source["goal"]["sha256"],
            "The actual export must contain this new reference")
        bound = task["harbor_export_binding"]["resource_runtime"]["source_artifacts"]
        for key, actual in (("input", input_ref), ("instruction", brief_ref), ("goal", source["goal"])):
            require((bound[key]["sha256"], bound[key]["bytes"]) == (actual["sha256"], actual["bytes"]),
                "The public or private task material differs from its export binding")
        bindings.append({"mode": task["mode"], "task_id": task["task_id"], "input": input_ref,
            "instruction": brief_ref, "goal": source["goal"], "individual_engineering": task["individual_engineering"],
            "plan_freeze": task["plan_freeze"]})
    output.mkdir(parents=True)
    for item in bindings:
        for role in ("public", "reference"):
            workspace = output / "workspaces" / item["mode"] / role
            workspace.mkdir(parents=True)
            for name, record in (("input.xlsx", item["input"]), ("instruction.md", item["instruction"])):
                shutil.copyfile(record["path"], workspace / name)
            if role == "reference":
                shutil.copyfile(item["goal"]["path"], workspace / "reference.xlsx")
                private = {"source_manifest.private.json": source_ref,
                    "specification.private.json": source["specification"], "oracle_A.private.json": records["A"],
                    "oracle_B.private.json": records["B"], "independent_comparison.private.json": records["independent_comparison"],
                    "bindings.private.json": source["bindings"], "individual_engineering.private.json": item["individual_engineering"],
                    "plan_freeze.private.json": item["plan_freeze"]}
                private.update({f"source{c['index']}_audit.private.json": c["audit"] for c in source["actual_LO_calls"]})
                for name, record in private.items():
                    read(record)
                    shutil.copyfile(record["path"], workspace / name)
    inventory = {str(p.relative_to(output)): ref(p) for p in sorted((output / "workspaces").rglob("*")) if p.is_file()}
    return write(output / "prepared.json", {"kind": "prepared_associate_bridge_shared_semantic_review", "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(), "batch": batch_ref, "source": source_ref,
        "tasks": bindings, "workspace_inventory": inventory, "implementation": ref(__file__), "prompt": ref(PROMPT),
        "runtime_profile": ref(PROFILE), "model": "gpt-6-sol", "reasoning_effort": "high", "outer_retries": 0,
        "model_calls_permitted": 4, "model_calls_started": 0, "all_enabled_check_ids": ALL,
        "individual_controls_and_business_difficulty_pending": True, "whole_family_qualified": False})


def prompt(mode, role):
    common = f"""Review the actual {mode} task in input.xlsx and instruction.md.
This is one shared semantic review of the new hypothetical associate-bridge source.
Read full workbook policies and labels. Its investment method, tax class, posting
currency scale, yearly posting direction and receipt classification are business inputs.
The new bridge policy replaces the old investment and tax treatment; do not inherit
an old source qualification or assume a previously used reference is still valid.
Review whether the public request and workbook determine the missing/repaired reports.
Do not solve or submit, and do not ask for a finance tutorial or formula recipe.
Keep genuine conflicting information separate from ordinary financial conventions.
Use compact aggregates. Do not start LibreOffice, Harbor, another model, containers,
a solver or network requests. Do not print the full financial maps.
All twelve checks remain enabled across the public and private calls. Report missing
individual evidence as unknown, not as an executed pass or as a proven task defect.
The primary two-decimal/full-modification-set score is unchanged. A future business
failure-evidence gate is separate and is not established by this semantic review.
Return exactly the assigned assessment schema; each assigned ID occurs once.
"""
    if role == "public":
        details = """Public-only visibility: only input.xlsx and instruction.md are provided.
Check public assumptions, conflicting interpretations, task scope and answer exposure.
Treat /workspace as the review copy of the final /app input/output convention.
Q08 concerns an observable executable shortcut; if none is established use
not_applicable and state that separate frozen difficulty confirmation is pending.
"""
        ids = PUBLIC
    else:
        details = """Reference-review visibility also includes reference.xlsx and private evidence.
The NEW specification and independently implemented A/B maps bind every one of 93,510
business fields. Three NEW source audits and each current actual input audit are
present. Inspect the method, recognized income, tax base, receipt classification,
cash/investment/retained-earnings bridges, annual owner distribution, monetary/rate
scales and entity/division/group aggregation. Check the public recoverability and
business meaning of the new reference, rather than just trusting a passed label.
The individual task audit supports current facts, full D and zero native errors.
No independent public solver ran. Final actual Harbor oracle/nop and the strongest
model are not part of this review: Q05/Q11/Q12 must name any missing evidence, and
cannot inherit these gates from an earlier source. Q10 can use the three current
healthy-source calculations; do not demand repeated cold sources for every input.
"""
        ids = PRIVATE
    return PROMPT.read_text() + "\n\n" + common + details + "\nassigned_check_ids=" + json.dumps(ids)


def _valid_resource(row, name, image):
    return (isinstance(row, dict) and set(row) == {"Id", "Name", "Image", "NanoCpus", "Memory", "PidsLimit"}
        and isinstance(row["Id"], str) and len(row["Id"]) == 64 and row["Name"] == "/" + name
        and row["Image"] == image and row["NanoCpus"] == 2_000_000_000
        and row["Memory"] == 32 * 1024**3 and row["PidsLimit"] == 256)


class ObservedReviewCLI(CodexCLI):
    """Observe only the exact ordinary-review container created by this call."""
    def _build_command(self, workspace, endpoint, isolated, name, **kwargs):
        command = super()._build_command(workspace, endpoint, isolated, name, **kwargs)
        require(isolated, "Semantic review must use an isolated workspace")
        stop, observations = threading.Event(), []
        def observe():
            while not stop.is_set():
                try:
                    completed = subprocess.run(["docker", "inspect", name, "--format", INSPECT],
                        capture_output=True, text=True, timeout=3)
                    if completed.returncode == 0:
                        row = json.loads(completed.stdout)
                        observations.append({"at": datetime.now(timezone.utc).isoformat(), "container": row,
                            "passed": _valid_resource(row, name, self.image)})
                        return
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
                stop.wait(0.1)
        thread = threading.Thread(target=observe, daemon=True)
        thread.start()
        self._review_local.observer = (name, stop, thread, observations)
        return command

    def _invoke_slot(self, *args, **kwargs):
        self._review_local.observer = None
        try:
            return super()._invoke_slot(*args, **kwargs)
        finally:
            observed = getattr(self._review_local, "observer", None)
            if observed:
                name, stop, thread, rows = observed
                stop.set(); thread.join(timeout=4)
                write(self.run_dir / "resources" / (name + ".json"), {
                    "kind": "actual_scoped_shared_review_container_resources", "container_name": name,
                    "passed": bool(rows) and all(row["passed"] for row in rows),
                    "observations": rows, "expected_image_id": self.image,
                    "only_owned_container_name_inspected": True, "environment_fields_requested": False})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._review_local = threading.local()


def run(prepared_path):
    prepared_ref = ref(prepared_path)
    prepared = read(prepared_ref)
    require(prepared["implementation"] == ref(__file__) and prepared["prompt"] == ref(PROMPT)
        and prepared["runtime_profile"] == ref(PROFILE), "The reviewed dispatch recipe changed")
    output = Path(prepared_path).absolute().parent
    require(not (output / "dispatch.json").exists(), "A review attempt is never restarted")
    for record in prepared["workspace_inventory"].values():
        require(ref(record["path"]) == record, "A prepared review workspace changed")
    current = {str(p.relative_to(output)): ref(p) for p in sorted((output / "workspaces").rglob("*")) if p.is_file()}
    require(current == prepared["workspace_inventory"], "A review workspace gained an undeclared file")
    profile = yaml.safe_load(PROFILE.read_text())
    config = yaml.safe_load((ROOT / "config/llm.yaml").read_text())
    config.update(model="gpt-6-sol", reasoning_effort="high", container_image=profile["image"]["id"],
        container_memory="32g", container_cpus=2, max_parallel_calls=4, timeout_seconds=720, roles={})
    dispatch = write(output / "dispatch.json", {"prepared": prepared_ref,
        "at": datetime.now(timezone.utc).isoformat(), "calls_authorized": 4, "outer_retries": 0,
        "implementation": ref(__file__), "prompt": ref(PROMPT), "runtime_profile": ref(PROFILE)})
    audit = AuditStore(output, {"id": output.name, "name": "New associate bridge shared semantic review",
        "status": "running", "target_count": 0, "model": "gpt-6-sol", "reasoning_effort": "high"})
    panel = DashboardServer(audit.snapshot, audit.events, port=0)
    url = panel.start(); audit.update_run(dashboard_url=url)
    print(json.dumps({"dashboard_url": url, "output": str(output)}), flush=True)
    backend = ObservedReviewCLI(ROOT, output, audit, config)
    started = time.monotonic(); results, failures = {}, {}
    def review(mode, role):
        ids = PUBLIC if role == "public" else PRIVATE
        task_id = mode + "-shared-" + role
        audit.task(task_id, mode=mode, status="reviewing", node=role, enabled_check_ids=ids)
        result = backend.complete(prompt(mode, role), role="shared_" + role + "_review", task_id=task_id,
            stage="associate_bridge_shared_semantic_review", workspace=output / "workspaces" / mode / role,
            isolated=True, timeout=720, output_schema=diagnosis_output_schema(ids))
        artifact = write(output / (mode + "_" + role + "_review.json"), result)
        audit.task(task_id, status="reviewed", node="complete", review_artifact=artifact)
        audit.export()
        return artifact, result
    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            pending = {executor.submit(review, mode, role): (mode, role) for mode in MODES for role in ("public", "reference")}
            for future in as_completed(pending):
                key = pending[future]
                try:
                    results[key] = future.result()
                except BaseException as error:
                    failures["/".join(key)] = {"error_type": type(error).__name__,
                        "call_id": getattr(error, "call_id", None), "record_path": getattr(error, "record_path", None)}
        modes = {}
        for mode in MODES:
            assessments = {}; issues = []
            for role in ("public", "reference"):
                pair = results.get((mode, role))
                if pair:
                    assessments.update(pair[1]["assessments"]); issues.extend(pair[1]["issues"])
                else:
                    for check in PUBLIC if role == "public" else PRIVATE:
                        assessments[check] = {"check_id": check, "state": "unknown",
                            "reason": "The assigned isolated review call did not complete; no task conclusion is inferred.",
                            "evidence": [], "origin": "program_missing_review"}
            modes[mode] = {"assessments": assessments, "issues": issues,
                "shared_semantic_passed": all(assessments[k]["state"] == "clear" for k in SEMANTIC)
                    and not any(issue.get("severity") == "blocker" for issue in issues),
                "whole_family_qualified": False}
        resources = [ref(p) for p in sorted((output / "resources").glob("*.json"))]
        native_calls = [ref(p) for p in sorted((output / "llm_calls/private").glob("*/result.json"))]
        resource_passed = len(resources) == len(native_calls) == 4 and all(read(p)["passed"] for p in resources)
        for call_ref in native_calls:
            call = read(call_ref)
            resource_path = output / "resources" / ("sf-codex-" + call["call_id"][:20] + ".json")
            observation = read(resource_path) if resource_path.is_file() else None
            resource_passed = resource_passed and bool(observation) and (
                call.get("status") == "completed" and call.get("model") == "gpt-6-sol"
                and call.get("reasoning_effort") == "high" and call.get("isolated") is True
                and all(datetime.fromisoformat(call["started_at"]) <= datetime.fromisoformat(row["at"])
                    <= datetime.fromisoformat(call["finished_at"]) for row in observation["observations"]))
        audit.update_run(status="completed" if not failures else "infrastructure_failed")
        snapshot = audit.export()
        terminal = write(output / "terminal.json", {"kind": "actual_associate_bridge_shared_semantic_review", "version": 1,
            "dispatch": dispatch, "source": prepared["source"], "tasks": prepared["tasks"], "all_enabled_check_ids": ALL,
            "modes": modes, "review_results": {"/".join(k): v[0] for k, v in results.items()}, "failures": failures,
            "ordinary_review_resources": resources, "ordinary_review_native_calls": native_calls,
            "ordinary_review_resources_passed": bool(resource_passed),
            "shared_semantic_passed": not failures and resource_passed and all(m["shared_semantic_passed"] for m in modes.values()),
            "usage": snapshot["metrics"], "wall_seconds": time.monotonic() - started,
            "individual_controls_and_business_difficulty_pending": True, "whole_family_qualified": False,
            "independent_public_solver_executed": False, "outer_retries": 0, "new_LO_or_Harbor_calls": 0,
            "dashboard_url": url})
        print(json.dumps({"terminal": terminal, "resource_passed": resource_passed, "failures": failures}), flush=True)
        return terminal
    finally:
        audit.export(); panel.stop(); audit.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    prepared = prepare(args.batch, args.output)
    print(json.dumps({"prepared": prepared}), flush=True)
    if args.run:
        run(prepared["path"])


if __name__ == "__main__":
    main()
