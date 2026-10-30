#!/usr/bin/env python3
"""Build one experimental source-linked seed; never qualify or publish a task."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from sheets_factory.workbook.derived_gold.spec import resolve_spec
from sheets_factory.workbook.derived_gold.excel import emit_workbook
from sheets_factory.workbook.derived_gold.ledger import simulate
from sheets_factory.workbook.derived_gold.validate import audit_workbook
from sheets_factory.workbook.engine import LibreOfficeEngine
from sheets_factory.workbook.compare import compare_workbooks
from sheets_factory.workbook.profile import profile_workbook


def build(project_root: Path, config_path: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("Output already exists; use a new immutable prototype directory")
    spec = resolve_spec(project_root, config_path)
    # The emitter receives no numeric journal or expected financial outputs.
    ledger = simulate(spec)
    output.mkdir(parents=True)
    private = output / "private"
    private.mkdir(mode=0o700)
    raw = private / "model_unrecalculated.xlsx"
    bindings = emit_workbook(spec, raw)
    engine = LibreOfficeEngine(project_root)
    first, final = private / "first_recalculation.xlsx", output / "project_model.xlsx"
    engine.recalculate(raw, first)
    engine.recalculate(first, final)
    stable = compare_workbooks(first, first, final)
    audit = audit_workbook(final, spec, ledger, bindings)
    profile = profile_workbook(final, max_cells=30000)
    digest = hashlib.sha256(final.read_bytes()).hexdigest()
    audit["two_recalculations_typed_stable"] = stable["reward"] == 1
    passed = audit["passed"] and stable["reward"] == 1 and not profile["errors"] and not profile["truncated"]
    manifest = {
        "scenario_id": spec["scenario_id"], "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "independently_verified_experimental_seed" if passed else "failed_experimental_seed",
        "qualified": False, "task_count": 0, "integrated_in_hard20": False,
        "source_ancestor_sha256": spec["source_lineage"]["sha256"],
        "source_lineage": spec["source_lineage"], "derived_workbook_sha256": digest,
        "local_path": str(final.resolve()), "financial_audit_passed": bool(passed),
        "sheet_count": profile["sheet_count"], "nonempty_sheet_count": profile["nonempty_sheet_count"],
        "formula_count": profile["formula_count"], "cached_errors": len(profile["errors"]),
        "independent_checked_cells": audit["checked_cells"], "all_formula_cells_covered": audit["all_formula_cells_independently_covered"],
        "requirements_before_task_admission": "All existing Q diagnosis, public-only recovery, actual Harbor oracle/nop and specified strong-agent difficulty evaluation remain required.",
    }
    (output / "public_scenario.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n")
    for name, value in (("ledger.json", ledger), ("bindings.json", bindings), ("financial_audit.json", audit), ("profile.json", profile), ("stability.json", stable)):
        (private / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")
    (output / "derived_seed_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config", type=Path, default=Path("config/derived_gold_project_v1.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    config = args.config if args.config.is_absolute() else args.project_root / args.config
    result = build(args.project_root, config, args.output)
    print(json.dumps({k: result[k] for k in ("status", "qualified", "task_count", "financial_audit_passed", "nonempty_sheet_count", "formula_count", "independent_checked_cells", "cached_errors", "local_path")}))
    return 0 if result["financial_audit_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
