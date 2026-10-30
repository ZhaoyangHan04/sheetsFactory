#!/usr/bin/env python3
"""Rank spreadsheet *potential*, without running a model or approving a task.

The score describes formula variety, dependencies, periods, and business
evidence. It is not a prediction of Pass@1. Every proposed task still needs
the normal public-assumption, independent-recovery, native-risk and controls
checks. In particular, a large workbook with copied SUM formulas is not hard.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

import openpyxl
from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils.cell import coordinate_to_tuple

from sheets_factory.workbook.profile import formula_references


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_signature(formula: str, origin: str) -> str:
    """Collapse translated formulas while preserving constants and anchors."""
    row, col = coordinate_to_tuple(origin)

    def cell_signature(match: re.Match) -> str:
        col_anchor, letters, row_anchor, digits = match.groups()
        cell_row, cell_col = coordinate_to_tuple(letters + digits)
        rr = "=" + digits if row_anchor else str(cell_row - row)
        cc = "=" + letters.upper() if col_anchor else str(cell_col - col)
        return "R[" + rr + "]C[" + cc + "]"

    try:
        tokens = Tokenizer(formula).items
        parts = []
        for token in tokens:
            value = token.value
            if token.type == "OPERAND" and token.subtype == "RANGE":
                if "!" in value:
                    sheet, address = value.rsplit("!", 1)
                    value = sheet + "!" + re.sub(
                        r"(\$?)([A-Za-z]{1,3})(\$?)(\d+)", cell_signature, address
                    )
                else:
                    value = re.sub(
                        r"(\$?)([A-Za-z]{1,3})(\$?)(\d+)", cell_signature, value
                    )
            if token.type != "WSPACE":
                parts.append(value)
        return "".join(parts)
    except Exception:
        return "UNPARSED:" + formula


def analyse_workbook(path: Path) -> dict:
    """Read every populated cell. Never use a truncated profile as a graph."""
    book = openpyxl.load_workbook(path, data_only=False, keep_links=False)
    values = openpyxl.load_workbook(path, data_only=True, keep_links=False)
    formulas, refs, patterns, functions = {}, {}, Counter(), Counter()
    populated_sheets, labels, errors, unsupported = [], [], [], []
    for ws in book.worksheets:
        cells = [c for c in ws._cells.values() if c.value is not None]
        if cells:
            populated_sheets.append(ws.title)
        for cell in cells:
            address = ws.title + "!" + cell.coordinate
            if cell.data_type == "f":
                formula = cell.value
                if not isinstance(formula, str):
                    unsupported.append({"address": address,
                                        "references": ["formula_group:" + type(formula).__name__]})
                    formula = getattr(formula, "text", None)
                    if not isinstance(formula, str):
                        formulas[address], refs[address] = "", set()
                        patterns["UNSUPPORTED_FORMULA_GROUP"] += 1
                        continue
                formulas[address] = formula
                patterns[relative_signature(formula, cell.coordinate)] += 1
                parsed = formula_references(formula, ws.title)
                refs[address] = {
                    r["sheet"] + "!" + r["cell"] for r in parsed["references"]
                }
                if parsed["unsupported"]:
                    unsupported.append({"address": address, "references": parsed["unsupported"]})
                functions.update(re.findall(r"\b([A-Z][A-Z0-9_.]*)\s*\(", formula.upper()))
            elif isinstance(cell.value, (str, date, datetime)):
                labels.append(str(cell.value))
        for cell in values[ws.title]._cells.values():
            if cell.data_type == "e":
                errors.append({"sheet": ws.title, "cell": cell.coordinate, "error": cell.value})

    sheet_edges = set()
    dependents, indegree = defaultdict(set), {}
    for address in formulas:
        parents = refs[address] & formulas.keys()
        indegree[address] = len(parents)
        for parent in parents:
            dependents[parent].add(address)
        sheet = address.rsplit("!", 1)[0]
        for parent in refs[address]:
            other = parent.rsplit("!", 1)[0]
            if other != sheet:
                sheet_edges.add((other, sheet))

    queue = deque(sorted(a for a in formulas if not indegree[a]))
    depth, cross_depth, resolved = {}, {}, []
    while queue:
        address = queue.popleft()
        sheet = address.rsplit("!", 1)[0]
        depth[address] = 1 + max((depth.get(p, 0) for p in refs[address]), default=0)
        cross_depth[address] = max(
            (cross_depth.get(p, 0) + (p.rsplit("!", 1)[0] != sheet) for p in refs[address]),
            default=0,
        )
        resolved.append(address)
        for child in sorted(dependents[address]):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    # Count independent sheet-level components with formula links. Blank and
    # isolated report sheets do not enlarge this count or the dependency score.
    adjacency = defaultdict(set)
    for left, right in sheet_edges:
        adjacency[left].add(right)
        adjacency[right].add(left)
    components, seen = [], set()
    for sheet in sorted(adjacency):
        if sheet in seen:
            continue
        pending, component = [sheet], set()
        while pending:
            item = pending.pop()
            if item in component:
                continue
            component.add(item)
            pending.extend(adjacency[item] - component)
        seen.update(component)
        components.append(sorted(component))

    years = sorted({int(y) for label in labels for y in re.findall(r"\b(?:19|20)\d{2}\b", label)})
    period_labels = sorted({label for label in labels if re.search(
        r"\b(?:Q[1-4]|FY\s*\d|YEAR\s*\d|MONTH\s*\d|JAN(?:UARY)?|FEB(?:RUARY)?|"
        r"MAR(?:CH)?|APR(?:IL)?|MAY|JUN(?:E)?|JUL(?:Y)?|AUG(?:UST)?|SEP(?:TEMBER)?|"
        r"OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)\b", label, re.I
    )})
    text = " ".join(populated_sheets + labels).lower()
    families = {
        "revenue_volume_price": r"revenue|sales|contract|commission|price",
        "operating_costs": r"operating|expense|payroll|salary|cost",
        "working_capital": r"receivable|payable|inventory|working capital|deferred",
        "debt_financing": r"loan|debt|interest|lease|financing|amortiz",
        "capital_depreciation": r"depreciation|capital expenditure|fixed asset|equipment",
        "tax": r"\btax\b|taxation",
        "valuation_returns": r"valuation|terminal value|discount|\bnpv\b|\birr\b|\broi\b",
        "cash_equity": r"cash flow|cashflow|balance sheet|equity|retained|deficit",
    }
    mechanisms = [k for k, pattern in families.items() if re.search(pattern, text)]
    financial_functions = sorted(set(functions) & {
        "PMT", "IPMT", "PPMT", "PV", "FV", "NPV", "XNPV", "IRR", "XIRR",
        "RATE", "NPER", "SLN", "DB", "DDB", "VDB", "CUMIPMT", "CUMPRINC",
    })
    result = {
        "normalized_path": str(path.resolve()), "normalized_sha256": file_sha256(path),
        "sheet_count": len(book.sheetnames), "nonempty_sheet_count": len(populated_sheets),
        "nonempty_sheets": populated_sheets, "formula_count": len(formulas),
        "distinct_relative_formula_patterns": len(patterns),
        "formula_repetition_fraction": round(1 - len(patterns) / max(1, len(formulas)), 6),
        "cross_sheet_edges": [{"from": a, "to": b} for a, b in sorted(sheet_edges)],
        "cross_sheet_formula_count": sum(any(p.rsplit("!", 1)[0] != a.rsplit("!", 1)[0]
                                                 for p in refs[a]) for a in formulas),
        "linked_sheet_count": len(adjacency), "linked_sheet_components": components,
        "max_formula_depth": max(depth.values(), default=0),
        "max_cross_sheet_depth": max(cross_depth.values(), default=0),
        "not_topologically_resolved_formula_count": len(formulas) - len(resolved),
        "unresolved_note": "Includes cycles and their downstream dependents; not a count of cycle roots.",
        "function_names": sorted(functions), "financial_function_names": financial_functions,
        "mechanism_label_hints": mechanisms, "distinct_year_labels": years,
        "period_label_count": len(period_labels), "cached_errors": errors,
        "unsupported_references": unsupported,
    }
    book.close()
    values.close()
    return result


def score_potential(features: dict, mode: str, business_evidence: dict | None = None) -> dict:
    """Bound repeated-cell and long-rollforward contributions to small values."""
    evidence = business_evidence or {}
    f = features
    parts = {
        "cross_sheet_integration": min(f["linked_sheet_count"], 8) * 2,
        "cross_sheet_reasoning_depth": min(f["max_cross_sheet_depth"], 5) * 4,
        "distinct_formula_patterns": min(f["distinct_relative_formula_patterns"], 40) / 2,
        "business_mechanism_hints": min(len(f["mechanism_label_hints"]), 6) * 2,
        "time_periods": min(len(f["distinct_year_labels"]), 4) + min(f["period_label_count"], 8) / 2,
        "financial_functions": min(len(f["financial_function_names"]), 4) * 2,
        "formula_depth_capped": min(f["max_formula_depth"], 8) / 2,
        "reviewed_business_evidence": 6 if evidence.get("financial_modeling_eligible") else 0,
        "repetition_penalty": -6 * f["formula_repetition_fraction"],
        "unsupported_reference_penalty": -min(len(f["unsupported_references"]), 5) * 3,
        "unresolved_dependency_penalty": -12 if f["not_topologically_resolved_formula_count"] else 0,
    }
    if mode == "debugging":
        parts["multiple_linked_modules"] = min(len(f["cross_sheet_edges"]), 10)
    # Cached errors are surfaced, not taken as evidence of a successful injected
    # bug or automatically repaired. A later module can be disjoint from them.
    parts["native_error_review_cost"] = -min(len(f["cached_errors"]), 5)
    return {
        "score": round(max(0.0, sum(parts.values())), 3),
        "components": {k: round(v, 3) for k, v in parts.items()},
        "meaning": "Structural/business potential only; not measured difficulty or predicted Pass@1.",
    }


def inventory_rows(document) -> list[dict]:
    if isinstance(document, list):
        return [r for r in document if isinstance(r, dict)]
    if isinstance(document, dict):
        if any(k in document for k in ("source_sha256", "sha256")):
            return [document]
        for key in ("selected", "sources", "candidates"):
            if isinstance(document.get(key), list):
                return inventory_rows(document[key])
    return []


def source_digest(row: dict) -> str | None:
    digest = row.get("source_sha256", row.get("sha256"))
    return digest.lower() if isinstance(digest, str) and re.fullmatch(r"[a-fA-F0-9]{64}", digest) else None


def evidence_rows(document) -> list[dict]:
    if isinstance(document, dict):
        found = []
        for key in ("finance_evidence", "sources"):
            if key in document:
                found.extend(evidence_rows(document[key]))
        if source_digest(document):
            found.append(document)
        return found
    if isinstance(document, list):
        return [r for r in document if isinstance(r, dict) and source_digest(r)]
    return []


def merge_inventories(paths: list[Path]) -> list[dict]:
    rows = {}
    for path in paths:
        for row in inventory_rows(json.loads(path.read_text())):
            digest = source_digest(row)
            if not digest:
                continue
            merged = rows.setdefault(digest, {"source_sha256": digest, "inventory_files": []})
            merged.update({k: val for k, val in row.items() if val is not None})
            merged["source_sha256"] = digest
            merged["inventory_files"].append(str(path.resolve()))
    return [rows[k] for k in sorted(rows)]


def rank_candidates(candidates: list[dict], mode: str, used_policy: str = "prefer",
                    require_business_evidence: bool = False) -> list[dict]:
    available = [c for c in candidates if c.get("analysis_status") == "profiled"
                 and (used_policy != "exclude" or not c["used_in_final_tasks"])
                 and (not require_business_evidence or mode != "financial_modeling"
                      or not c.get("requires_business_review", True))]
    return sorted(available, key=lambda c: (
        bool(c["used_in_final_tasks"]) if used_policy == "prefer" else False,
        -c["potential"][mode]["score"], c["source_sha256"],
    ))


def select(args) -> dict:
    inventories = merge_inventories(args.inventory)
    evidence, risks, used = {}, {}, set()
    for path in args.evidence:
        for row in evidence_rows(json.loads(path.read_text())):
            digest = source_digest(row)
            evidence[digest] = {**evidence.get(digest, {}), **row}
    if args.risk_registry:
        for row in evidence_rows(json.loads(args.risk_registry.read_text())):
            risks[source_digest(row)] = row.get("risks", [])
    if args.existing_run:
        summary = json.loads((args.existing_run / "summary.json").read_text())
        used = {t["source_id"] for t in summary["tasks"] if t.get("status") == "qualified"}

    candidates = []
    for row in inventories:
        digest = row["source_sha256"]
        if isinstance(row.get("finance_evidence"), dict):
            evidence[digest] = {**evidence.get(digest, {}), **row["finance_evidence"]}
        raw = row.get("local_path", row.get("source_path", row.get("source")))
        normalized = row.get("normalized_path")
        if not normalized and raw and Path(raw).suffix.lower() == ".xlsx":
            normalized = raw
        item = {
            "source_sha256": digest, "archive_member": row.get("archive_member"),
            "source_path": raw, "used_in_final_tasks": digest in used,
            "inventory_files": row["inventory_files"], "known_native_risks": risks.get(digest, []),
            "business_evidence": evidence.get(digest, {}),
            "safety_policy": "Native risks require exact full-D intersection review; never blanket-ban unrelated modules. Cached-error-free is not business correctness certification.",
        }
        if raw and Path(raw).is_file():
            if file_sha256(Path(raw)) != digest:
                item["analysis_status"] = "source_hash_mismatch"
                candidates.append(item)
                continue
        else:
            item["raw_source_provenance_status"] = "original bytes unavailable locally; do not infer source hash from normalized bytes"
        if (not normalized or not Path(normalized).is_file()) and raw and args.normalize_dir:
            from sheets_factory.workbook.engine import LibreOfficeEngine
            destination = args.normalize_dir / (digest[:16] + ".xlsx")
            destination.parent.mkdir(parents=True, exist_ok=True)
            LibreOfficeEngine(args.project_root).normalize(Path(raw), destination)
            normalized = str(destination)
        if not normalized or not Path(normalized).is_file():
            item["analysis_status"] = "needs_normalized_workbook"
            candidates.append(item)
            continue
        try:
            features = analyse_workbook(Path(normalized))
        except Exception as exc:
            item.update(analysis_status="unreadable_workbook", error_type=type(exc).__name__)
            candidates.append(item)
            continue
        item["features"] = features
        if features["nonempty_sheet_count"] < args.min_sheets or not features["formula_count"]:
            item["analysis_status"] = "insufficient_nonempty_structure"
        elif not features["cross_sheet_edges"]:
            item["analysis_status"] = "no_cross_sheet_dependency"
        else:
            item["analysis_status"] = "profiled"
        item["potential"] = {mode: score_potential(features, mode, evidence.get(digest))
                             for mode in ("financial_modeling", "debugging")}
        item["requires_business_review"] = not bool(evidence.get(digest, {}).get("financial_modeling_eligible"))
        item["requires_full_D_quality_gate"] = True
        item["generation_approval"] = False
        candidates.append(item)

    modes = ("financial_modeling", "debugging") if args.mode == "both" else (args.mode,)
    rankings = {mode: rank_candidates(candidates, mode, args.used_policy,
                                     getattr(args, "require_business_evidence", False))
                for mode in modes}
    return {
        "schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Offline candidate research; no API, model rollout, production manifest edits, or task release.",
        "score_definition": "Bounded formula/dependency/business/period variety; copied cells and blank sheets do not create complexity. Scores are not a Pass@1 estimate.",
        "used_policy": args.used_policy, "requested_per_mode": args.limit,
        "require_business_evidence_for_financial_modeling": getattr(args, "require_business_evidence", False),
        "source_count": len(candidates),
        "analysis_status_counts": dict(Counter(c["analysis_status"] for c in candidates)),
        "selected": {mode: [c["source_sha256"] for c in ranked[:args.limit]]
                     for mode, ranked in rankings.items()},
        "rankings": {mode: [{"rank": idx + 1, "source_sha256": c["source_sha256"],
                              "score": c["potential"][mode]["score"],
                              "requires_business_review": c["requires_business_review"]}
                             for idx, c in enumerate(ranked)] for mode, ranked in rankings.items()},
        "candidates": candidates,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, action="append", required=True)
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    parser.add_argument("--risk-registry", type=Path)
    parser.add_argument("--existing-run", type=Path)
    parser.add_argument("--mode", choices=("both", "financial_modeling", "debugging"), default="both")
    parser.add_argument("--used-policy", choices=("prefer", "exclude", "allow"), default="prefer",
                        help="prefer ranks sources absent from final tasks first")
    parser.add_argument("--require-business-evidence", action="store_true",
                        help="Rank FM sources only with explicit financial_modeling_eligible evidence; still not task approval")
    parser.add_argument("--min-sheets", type=int, default=4)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--normalize-dir", type=Path, help="Opt-in local LibreOffice normalization of legacy XLS")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.limit < 1 or args.min_sheets < 1:
        parser.error("--limit and --min-sheets must be positive")
    if args.output.exists():
        parser.error("--output already exists; choose a new research artifact path")
    result = select(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output.resolve()), "source_count": result["source_count"],
                      "analysis_status_counts": result["analysis_status_counts"],
                      "selected_counts": {k: len(v) for k, v in result["selected"].items()}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
