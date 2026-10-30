#!/usr/bin/env python3
"""Prepare an isolated, unqualified Harbor probe from an existing cached plan."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys
from uuid import uuid4

import openpyxl
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sheets_factory.core.audit import AuditStore, utcnow
from sheets_factory.core.node import TaskContext
from sheets_factory.evaluation.harbor import export_harbor, inspect_export
from sheets_factory.nodes.construction import (
    ConstructNode, ControlsNode, InstructionNode, compile_mask_ranges,
)
from sheets_factory.workbook.engine import LibreOfficeEngine


MODES = ("financial_modeling", "debugging")
CONTROL_REWARDS = {"oracle": 1, "nop": 0, "equivalent": 1, "missed_root": 0, "extra_change": 0}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


class _NoModelCalls:
    def __getattr__(self, name):
        raise RuntimeError("Development-probe preparation must not invoke a model: " + name)


def _audit_tasks(run, source_id):
    summary = run / "summary.json"
    if summary.is_file():
        snapshot = json.loads(summary.read_text())
        tasks = snapshot.get("tasks")
        if isinstance(tasks, list) and any(isinstance(task, dict) and task.get("source_id") == source_id for task in tasks):
            return tasks, {"path": str(summary), "sha256": _sha(summary), "kind": "audit_summary"}
    database = run / "run.sqlite"
    if not database.is_file():
        raise ValueError("Source run lacks an existing source audit")
    # Read-only: never instantiate AuditStore against the source run.
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        tasks = [json.loads(row[0]) for row in connection.execute("SELECT payload FROM tasks")]
    finally:
        connection.close()
    return tasks, {"path": str(database), "kind": "read_only_sqlite_audit"}


def _select_source(config, selector):
    if not isinstance(selector, str) or not re.fullmatch(r"(?:[a-fA-F0-9]{12}|[a-fA-F0-9]{64})", selector):
        raise ValueError("source-id must be an explicit full SHA256 or twelve-character hash prefix")
    selector = selector.lower()
    root = Path(config["project_root"]).resolve()
    locations = [config["run"]["seed_manifest"], *config["run"].get("additional_seed_manifests", [])]
    entries, origins = {}, {}
    manifests = []
    for location in locations:
        path = Path(location)
        path = (path if path.is_absolute() else root / path).resolve()
        document = json.loads(path.read_text())
        selected = document.get("selected")
        if not isinstance(selected, list):
            raise ValueError("Source manifest must contain its explicit selected entries")
        manifests.append({"path": str(path), "sha256": _sha(path)})
        for entry in selected:
            identity = entry.get("sha256") if isinstance(entry, dict) else None
            if not isinstance(identity, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", identity):
                raise ValueError("Selected source manifest entries require an explicit full SHA256")
            identity = identity.lower()
            entries[identity] = {**entries.get(identity, {}), **entry, "sha256": identity}
            origins[identity] = str(path)
    matches = [identity for identity in entries if identity.startswith(selector)]
    if len(matches) != 1:
        raise ValueError("source-id must uniquely identify an existing selected source")
    identity = matches[0]
    entry = entries[identity]
    secondary_identity = entry.get("source_sha256", identity)
    if not isinstance(secondary_identity, str) or secondary_identity.lower() != identity:
        raise ValueError("Source manifest raw SHA256 assertions disagree")
    source = Path(entry["local_path"])
    source = (source if source.is_absolute() else root / source).resolve()
    if source.suffix.lower() not in {".xls", ".xlsx"} or not source.is_file():
        raise ValueError("Selected raw source must be an existing XLS/XLSX workbook")
    if _sha(source) != identity:
        raise ValueError("Actual raw source SHA256 differs from its selected manifest assertion")
    return identity, source, entry, manifests, origins[identity]


def _assert_before(plan, baseline, mode):
    edits = plan.get("edits")
    if not isinstance(edits, list) or not edits:
        raise ValueError("Cached proposal has no compiled formula targets")
    book = openpyxl.load_workbook(baseline, keep_links=False)
    try:
        seen = set()
        for edit in edits:
            if not isinstance(edit, dict) or not isinstance(edit.get("sheet"), str) or not isinstance(edit.get("cell"), str):
                raise ValueError("Cached proposal contains malformed formula targets")
            coordinate = (edit["sheet"], edit["cell"])
            if coordinate in seen or coordinate[0] not in book:
                raise ValueError("Cached proposal repeats a target or names a missing sheet")
            seen.add(coordinate)
            cell = book[coordinate[0]][coordinate[1]]
            if cell.data_type != "f" or cell.value != edit.get("before"):
                raise ValueError("Cached proposal before assertion differs from immutable baseline: " + str(coordinate))
            after = edit.get("after")
            if mode == "financial_modeling" and after is not None:
                raise ValueError("A modeling proposal may only mask existing formulas")
            if mode == "debugging" and (not isinstance(after, str) or not after.startswith("=") or after == cell.value):
                raise ValueError("A debugging proposal requires a different formula")
    finally:
        book.close()
    return {"before_assertions_passed": True, "edit_count": len(edits)}


def prepare_probe(run, source_id, mode, output):
    """Prepare only; never evaluate, qualify, recover or reuse a model score."""
    run, output = Path(run).resolve(), Path(output).resolve()
    if output == run or run in output.parents:
        raise ValueError("Probe output must be outside the original source run")
    output.mkdir(parents=True, exist_ok=False)
    audit = AuditStore(output, {"id": "development-probe-" + uuid4().hex[:12],
        "kind": "prequality_development_probe", "source_kind": "prequality_development_probe",
        "status": "preparing", "source_run": str(run), "llm_calls_permitted": False})
    tracked = {}
    task_id = None
    try:
        if mode not in MODES:
            raise ValueError("Unsupported development-probe mode")
        config_path = run / "resolved_config.yaml"
        config = yaml.safe_load(config_path.read_text())
        if not isinstance(config, dict) or not isinstance(config.get("run"), dict):
            raise ValueError("Source run lacks a resolved pipeline configuration")
        identity, source, entry, manifests, source_manifest = _select_source(config, source_id)
        tasks, audit_origin = _audit_tasks(run, identity)
        source_tasks = [task for task in tasks if isinstance(task, dict) and task.get("source_id") == identity]
        if not source_tasks or any(task.get("source") != source.name for task in source_tasks):
            raise ValueError("Source run audit does not match the selected raw source identity")
        cache = run / "sources" / identity[:12]
        baseline = cache / "baseline.xlsx"
        backend = config.get("construction", {}).get("authoring_backend", "llm")
        suffixes = {"llm": "", "project_template": "_project_template", "portfolio_template": "_portfolio_template",
                    "composite_template": "_composite_template"}
        if backend not in suffixes:
            raise ValueError("Unsupported cached proposal authoring backend")
        proposal = cache / ("task_plans_v0_" + mode + suffixes[backend] + ".json")
        if not baseline.is_file() or not proposal.is_file():
            raise ValueError("Source run lacks the exact cached mode proposal or normalized baseline")
        if not baseline.resolve().is_relative_to(cache.resolve()) or not proposal.resolve().is_relative_to(cache.resolve()):
            raise ValueError("Source cache artifacts must remain within their selected cache directory")
        planning = json.loads(proposal.read_text())
        plan = planning.get(mode) if isinstance(planning, dict) else None
        if not isinstance(plan, dict) or not plan:
            raise ValueError("The exact cached proposal does not contain a task for this mode")
        tracked = {path: _sha(path) for path in (config_path, source, baseline, proposal)}
        tracked.update({Path(item["path"]): item["sha256"] for item in manifests})
        origin = {"path": str(proposal), "sha256": tracked[proposal], "raw_source_sha256": identity,
                  "authoring_backend": config.get("construction", {}).get("authoring_backend", "llm")}
        baseline_origin = {"path": str(baseline), "sha256": tracked[baseline]}
        identity_proof = {"source_id": identity, "raw_source_path": str(source),
            "raw_source_sha256": tracked[source], "source_manifest": source_manifest,
            "manifest_bindings": manifests, "source_audit": audit_origin,
            "matching_source_audit_tasks": [{key: task.get(key) for key in ("id", "mode", "source", "source_id")}
                                             for task in source_tasks]}
        _write(output / "source_identity.json", identity_proof)
        _write(output / "planning_origin.json", origin)
        snapshot = output / "source_snapshot"
        snapshot.mkdir()
        source_copy, baseline_copy = snapshot / source.name, snapshot / "baseline.xlsx"
        if source.name == "baseline.xlsx":
            source_copy = snapshot / ("raw_source" + source.suffix.lower())
        shutil.copy2(source, source_copy)
        shutil.copy2(baseline, baseline_copy)
        shutil.copy2(proposal, snapshot / "cached_planning_proposal.json")
        if _sha(source_copy) != identity or _sha(baseline_copy) != tracked[baseline]:
            raise ValueError("Isolated source snapshot differs from its immutable origin")
        isolated_config = deepcopy(config)
        isolated_config["run_dir"] = str(output)
        isolated_config.setdefault("run", {})["name"] = "prequality-development-probe"
        isolated_config["run"]["source_kind"] = "prequality_development_probe"
        (output / "resolved_config.yaml").write_text(yaml.safe_dump(isolated_config, sort_keys=False))
        plan = compile_mask_ranges(deepcopy(plan), baseline_copy, mode, isolated_config)
        before_assertions = _assert_before(plan, baseline_copy, mode)
        _write(output / "before_assertions.json", before_assertions)
        task_id = ("fm-" if mode == "financial_modeling" else "dbg-") + identity[:12]
        audit.task(task_id, mode=mode, source_id=identity, source=source.name, status="preparing",
                   difficulty_status="prequality_development_probe", source_kind="prequality_development_probe")
        engine_settings = isolated_config.get("engine", {})
        engine = LibreOfficeEngine(Path(isolated_config["project_root"]),
            image=engine_settings.get("image", "sheetsfactory-lo:24.2"),
            timeout_seconds=engine_settings.get("timeout_seconds", 120))
        context = TaskContext(run_id=audit.run["id"], task_id=task_id, mode=mode,
            source=source_copy, directory=output / "tasks" / task_id, config=isolated_config,
            audit=audit, llm=_NoModelCalls(), engine=engine, data={
                "plan": plan, "baseline": baseline_copy, "source_id": identity,
                "source_cache": snapshot, "source_business_issues": entry.get("finance_evidence", {}).get("source_business_issues", []),
                "engine_report": {"engine": engine.metadata()}})
        for node in (ConstructNode(), InstructionNode(), ControlsNode()):
            node.run(context)
        controls = context.data.get("controls", {})
        rewards = {}
        for name, expected in CONTROL_REWARDS.items():
            reward = controls.get(name, {}).get("reward")
            if type(reward) not in (int, float) or reward != expected:
                raise ValueError("Local control did not match its actual required value: " + name)
            rewards[name] = reward
        revision_hash = context.data.get("revision_hash")
        if not isinstance(revision_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", revision_hash):
            raise ValueError("The instruction node did not bind an actual constructed revision")
        export = output / "SpreadsheetEval" / task_id
        metadata = {"task_id": task_id, "mode": mode, "source_id": identity,
            "revision": context.revision, "revision_hash": revision_hash,
            "difficulty_status": "prequality_development_probe", "source_kind": "prequality_development_probe",
            "base_image": engine_settings.get("image", "sheetsfactory-lo:24.2")}
        export_harbor(context.revision_dir, export, metadata=metadata,
                      project_root=isolated_config["project_root"])
        binding = inspect_export(export)
        if any(binding.get(key) != metadata[key] for key in ("task_id", "revision", "revision_hash")):
            raise ValueError("The exported probe differs from its constructed revision binding")
        if any(_sha(path) != expected for path, expected in tracked.items()):
            raise ValueError("An original source-run artifact changed during isolated preparation")
        manifest = {"schema_version": 1, "kind": "prequality_development_probe",
            "source_kind": "prequality_development_probe",
            "quality_status": "construction_and_five_local_controls_verified; independent_recovery_and_full_diagnosis_pending",
            "frozen_at": utcnow(), "selection_policy": "Existing cached source proposal frozen before any model evaluation; development only.",
            "selected_task_ids": [task_id], "tasks": [{**metadata, "harbor_export_binding": binding,
                "task_directory": str(export), "local_controls": rewards}],
            "planning_origin": origin, "baseline_origin": baseline_origin,
            "source_identity": identity_proof, "local_controls": rewards,
            "llm_calls": 0, "model_evaluation_performed": False}
        _write(output / "probe_manifest.json", manifest)
        audit.task(task_id, status="probe_prepared", node="probe_prepared", revision=context.revision,
                   revision_hash=revision_hash, local_controls=rewards, harbor_export_binding=binding)
        audit.update_run(status="prepared", prepared_probe_count=1, qualified=0,
                         probe_manifest=str(output / "probe_manifest.json"))
        audit.emit("probe.prepared", task_id=task_id, revision_hash=revision_hash)
        return manifest
    except Exception as error:
        failure = {"kind": "development_probe_preparation_failed", "timestamp": utcnow(),
                   "source_run": str(run), "requested_source_id": source_id, "mode": mode,
                   "error_type": type(error).__name__, "error": str(error)}
        _write(output / "preparation_failure.json", failure)
        if task_id:
            audit.task(task_id, status="failed", error=str(error))
        audit.update_run(status="failed", error=str(error), qualified=0)
        audit.emit("probe.failed", **{key: value for key, value in failure.items() if key != "kind"},
                   failure_kind=failure["kind"])
        raise
    finally:
        audit.export()
        audit.db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--mode", required=True, choices=MODES)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)
    try:
        manifest = prepare_probe(arguments.run, arguments.source_id, arguments.mode, arguments.output)
    except Exception as error:
        print(json.dumps({"status": "failed", "error": str(error), "output": str(arguments.output)}), file=sys.stderr)
        return 2
    print(json.dumps({"status": "prepared", "probe_manifest": str(arguments.output.resolve() / "probe_manifest.json"),
                      "selected_task_ids": manifest["selected_task_ids"], "llm_calls": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
