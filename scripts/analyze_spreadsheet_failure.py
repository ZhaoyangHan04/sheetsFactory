#!/usr/bin/env python3
"""Read completed artifacts and append offline diagnosis evidence; execute nothing."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sheets_factory.evaluation import spreadsheet_failure_analysis as analysis


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    case = commands.add_parser("case", help="Analyze an explicit manifest or one frozen inventory case")
    identity = case.add_mutually_exclusive_group(required=True)
    identity.add_argument("--manifest", type=Path)
    identity.add_argument("--inventory", type=Path)
    case.add_argument("--case", dest="case_key")
    for field in ("output-workbook", "trajectory", "result", "official-score", "baseline-cache", "instruction", "case-terminal", "reviewed-findings", "verified-tool-time"):
        case.add_argument("--" + field, type=Path)
    case.add_argument("--analysis-numeric-quantum", help="Optional cache diagnostic rounding; never an official score")
    case.add_argument("--output", type=Path, required=True, help="Append-only analysis root")
    scan = commands.add_parser("scan", help="Read one snapshot of terminal cohort/evaluation artifacts")
    scan.add_argument("--inventory", type=Path, required=True)
    scan.add_argument("--evaluation", type=Path, required=True, help="Cohort root or one evaluation directory")
    scan.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "scan":
        receipt = analysis.scan_completed(args.inventory, args.evaluation, args.output)
    else:
        fields = {key: getattr(args, key) for key in ("trajectory", "result", "official_score", "baseline_cache", "instruction", "case_terminal", "reviewed_findings", "verified_tool_time")}
        fields.update(output=args.output_workbook, analysis_numeric_quantum=args.analysis_numeric_quantum)
        if args.manifest:
            parser.error("A manifest fixes all case inputs; do not combine it with --case or artifact overrides") if args.case_key or any(v is not None for v in fields.values()) else None
            manifest = analysis.read(args.manifest)
        else:
            if not args.case_key: parser.error("--inventory requires --case")
            manifest = analysis.case_from_inventory(args.inventory, args.case_key, **fields)
        receipt = analysis.save_analysis(manifest, args.output)
    print(json.dumps({"receipt": receipt, "new_model_LO_solver_network_calls": 0}, sort_keys=True))
    return receipt


if __name__ == "__main__":
    main()
