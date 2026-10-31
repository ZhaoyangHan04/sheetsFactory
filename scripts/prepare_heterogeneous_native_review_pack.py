#!/usr/bin/env python3
"""Freeze/preflight or emit the fixed eight-business OOXML review pack.

No service, calculation, model, solver, or admission action is available here.
The preflight is durable before emission; a failed emission cannot be retried in
the same directory. Native equivalence remains a separate future requirement.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sheets_factory.workbook import heterogeneous_native_merge as merge

PREPARED_KIND = "prepared_fixed_eight_heterogeneous_native_review_pack"
DONOR_IDS = ("statements", "estate", "social", "registry", "wind", "nyu_simple", "budget", "meeting")


def _write(path, data):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(data, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return merge.file_ref(path)


def recipes():
    paths = [Path(__file__), ROOT / "src/sheets_factory/workbook/heterogeneous_native_merge.py", ROOT / "tests/test_heterogeneous_native_merge.py"]
    return {str(p.relative_to(ROOT)): merge.file_ref(p) for p in paths}


def _all_refs(value):
    if isinstance(value, dict):
        if set(value) == {"path", "sha256", "bytes"}:
            yield value
        else:
            for item in value.values():
                yield from _all_refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_refs(item)


def _checked_config(path):
    config = json.loads(Path(path).read_text())
    merge.require(config.get("kind") == "fixed_eight_heterogeneous_native_review_pack_recipe" and config.get("version") == 1, "Unsupported review-pack recipe")
    merge.require(tuple(d["id"] for d in config["donors"]) == DONOR_IDS, "Fixed eight distinct business donors are required in declared order")
    for ref in _all_refs(config):
        merge.checked_ref(ref)
    return config


def prepare(config_path, output):
    output = Path(output).resolve()
    merge.require(not output.exists(), "Preparation output must be fresh")
    config = _checked_config(config_path)
    preflight = merge.inspect_donors(config["donors"])
    output.mkdir(parents=True)
    snapshot = _write(output / "donor_preflight.json", preflight)
    manifest = {"kind": PREPARED_KIND, "version": 1, "config": merge.file_ref(config_path), "recipe": recipes(), "preflight": snapshot, "ready_for_noncalculating_emission": preflight["passed"], "actual_native_equivalence": "not_executed", "qualified": False, "source_admitted": False, "financial_certified": False, "LO_model_solver_Harbor_calls": 0, "one_fresh_emission_only": True}
    result = _write(output / "prepared.json", manifest)
    validate_prepared(output)
    return result


def validate_prepared(output):
    output = Path(output).resolve()
    manifest = json.loads((output / "prepared.json").read_text())
    merge.require(manifest.get("kind") == PREPARED_KIND and manifest.get("version") == 1, "Prepared review-pack identity mismatch")
    merge.require(manifest["recipe"] == recipes(), "Review-pack compiler recipe changed")
    config = _checked_config(merge.checked_ref(manifest["config"]))
    frozen = json.loads(merge.checked_ref(manifest["preflight"]).read_text())
    current = merge.inspect_donors(config["donors"])
    merge.require(current == frozen, "Frozen donor preflight changed")
    merge.require(manifest["ready_for_noncalculating_emission"] == frozen["passed"], "Prepared readiness does not match preflight")
    return {"manifest": manifest, "config": config, "preflight": frozen}


def emit(output):
    output = Path(output).resolve()
    checked = validate_prepared(output)
    merge.require(checked["preflight"]["passed"], "Unsupported donor content holds emission")
    _write(output / "emission_started.json", {"kind": "one_fresh_heterogeneous_native_review_pack_emission", "version": 1, "prepared": merge.file_ref(output / "prepared.json"), "no_retries": True, "calculation_executed": False})
    result = merge.compose(checked["config"]["donors"], output / "review_pack.xlsx")
    result["prepared"] = merge.file_ref(output / "prepared.json")
    result["started"] = merge.file_ref(output / "emission_started.json")
    return _write(output / "emission_terminal.json", result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--config", type=Path, default=ROOT / "config/heterogeneous_native_review_pack_v1.json")
    p.add_argument("--output", type=Path, required=True)
    for action in ("validate-prepared", "emit"):
        p = sub.add_parser(action);p.add_argument("--prepared", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare(args.config, args.output)
    elif args.action == "emit":
        result = emit(args.prepared)
    else:
        result = {"passed": True, "ready_for_noncalculating_emission": validate_prepared(args.prepared)["preflight"]["passed"]}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
