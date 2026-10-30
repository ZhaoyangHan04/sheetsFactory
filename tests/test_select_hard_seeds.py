"""Meaningful invariants for offline seed selection; no Docker or model calls."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import openpyxl


_PATH = Path(__file__).resolve().parents[1] / "scripts/select_hard_seeds.py"
_SPEC = importlib.util.spec_from_file_location("select_hard_seeds", _PATH)
selector = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(selector)


def workbook(path, kind="integrated", copies=2, blank_sheets=0):
    book = openpyxl.Workbook()
    book.active.title = "Assumptions"
    book.active["A1"] = 10
    if kind == "integrated":
        book.create_sheet("Sales")["A1"] = "=Assumptions!A1*3"
        book.create_sheet("Income")["A1"] = "=Sales!A1-7"
        book.create_sheet("Cash Flow")["A1"] = "=Income!A1+2"
    elif kind == "copies":
        ws = book.create_sheet("Report")
        for r in range(1, copies + 1):
            book["Assumptions"].cell(r, 1, r)
            ws.cell(r, 1, f"=Assumptions!A{r}*3")
    elif kind == "cycle":
        book.create_sheet("Sales")["A1"] = "=Income!A1"
        book.create_sheet("Income")["A1"] = "=Sales!A1"
        book.create_sheet("Cash Flow")["A1"] = "=Income!A1+2"
    for idx in range(blank_sheets):
        book.create_sheet(f"Empty {idx}")
    book.save(path)
    return path


def args(inventory_path, **kwargs):
    defaults = dict(inventory=[inventory_path], evidence=[], risk_registry=None,
                    existing_run=None, mode="both", limit=20, min_sheets=1,
                    normalize_dir=None, project_root=_PATH.parents[1], used_policy="prefer")
    return SimpleNamespace(**(defaults | kwargs))


def test_copied_formula_growth_does_not_create_hardness(tmp_path):
    small = selector.analyse_workbook(workbook(tmp_path / "small.xlsx", "copies", copies=2))
    huge = selector.analyse_workbook(workbook(tmp_path / "huge.xlsx", "copies", copies=1000))
    integrated = selector.analyse_workbook(workbook(tmp_path / "integrated.xlsx"))
    assert small["distinct_relative_formula_patterns"] == huge["distinct_relative_formula_patterns"] == 1
    # More copies actually increase the repetition cost, never a cell-count bonus.
    for mode in ("financial_modeling", "debugging"):
        assert selector.score_potential(huge, mode)["score"] <= selector.score_potential(small, mode)["score"]
        assert selector.score_potential(integrated, mode)["score"] > selector.score_potential(huge, mode)["score"]


def test_empty_worksheets_do_not_enlarge_dependency_or_score(tmp_path):
    original = selector.analyse_workbook(workbook(tmp_path / "original.xlsx"))
    padded = selector.analyse_workbook(workbook(tmp_path / "padded.xlsx", blank_sheets=30))
    assert original["nonempty_sheet_count"] == padded["nonempty_sheet_count"] == 4
    assert original["cross_sheet_edges"] == padded["cross_sheet_edges"]
    assert selector.score_potential(original, "debugging") == selector.score_potential(padded, "debugging")


def test_graph_depth_and_cycles_are_distinguished(tmp_path):
    valid = selector.analyse_workbook(workbook(tmp_path / "valid.xlsx"))
    cyclic = selector.analyse_workbook(workbook(tmp_path / "cyclic.xlsx", "cycle"))
    assert valid["max_cross_sheet_depth"] == 3
    assert valid["not_topologically_resolved_formula_count"] == 0
    assert cyclic["not_topologically_resolved_formula_count"] == 3
    assert selector.score_potential(cyclic, "financial_modeling")["components"]["unresolved_dependency_penalty"] < 0


def test_formula_signature_preserves_anchors_and_reduces_translations():
    assert selector.relative_signature("=B2*$D$1", "A2") == selector.relative_signature("=B3*$D$1", "A3")
    assert selector.relative_signature("=B2*$D$1", "A2") != selector.relative_signature("=B2*D1", "A2")
    assert selector.relative_signature('=IF(A2="A99",B2,0)', "C2") == selector.relative_signature('=IF(A3="A99",B3,0)', "C3")


def test_array_formula_is_not_silently_certified_as_complete_graph(tmp_path):
    from openpyxl.worksheet.formula import ArrayFormula
    path = workbook(tmp_path / "array.xlsx")
    book = openpyxl.load_workbook(path)
    book["Sales"]["A1"] = ArrayFormula(ref="A1:A2", text="=Assumptions!A1:A2*3")
    book.save(path)
    result = selector.analyse_workbook(path)
    assert result["formula_count"] == 3
    assert any("formula_group:ArrayFormula" in item["references"] for item in result["unsupported_references"])


def test_known_risks_are_preserved_without_blanket_source_ban(tmp_path):
    path = workbook(tmp_path / "source.xlsx")
    digest = selector.file_sha256(path)
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps([{"sha256": digest, "local_path": str(path)}]))
    registry = tmp_path / "risks.json"
    risk = {"certainty": "confirmed", "unsafe_regions": [{"sheet": "Other", "range": "A1:A2"}]}
    registry.write_text(json.dumps({"sources": [{"source_sha256": digest, "risks": [risk]}]}))
    result = selector.select(args(inventory, risk_registry=registry))
    row = result["candidates"][0]
    assert row["known_native_risks"] == [risk]
    assert result["selected"]["financial_modeling"] == [digest]
    assert row["requires_business_review"] is True
    assert row["requires_full_D_quality_gate"] is True
    assert row["generation_approval"] is False


def test_wrong_source_hash_is_never_ranked(tmp_path):
    path = workbook(tmp_path / "source.xlsx")
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps([{"sha256": "f" * 64, "local_path": str(path)}]))
    result = selector.select(args(inventory))
    assert result["candidates"][0]["analysis_status"] == "source_hash_mismatch"
    assert result["selected"]["financial_modeling"] == []


def test_four_disconnected_reports_are_not_cross_sheet_models(tmp_path):
    path = tmp_path / "disconnected.xlsx"
    book = openpyxl.Workbook()
    for idx in range(4):
        ws = book.active if idx == 0 else book.create_sheet()
        ws["A1"], ws["A2"] = idx, "=SUM(A1:A1)"
    book.save(path)
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps([{"sha256": selector.file_sha256(path), "local_path": str(path)}]))
    result = selector.select(args(inventory, min_sheets=4))
    assert result["candidates"][0]["analysis_status"] == "no_cross_sheet_dependency"
    assert result["selected"]["debugging"] == []


def test_require_reviewed_evidence_does_not_confuse_filename_with_eligibility(tmp_path):
    path = workbook(tmp_path / "financial_model.xlsx")
    digest = selector.file_sha256(path)
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps([{"sha256": digest, "local_path": str(path)}]))
    result = selector.select(args(inventory, require_business_evidence=True))
    assert result["selected"]["financial_modeling"] == []
    # A research ranking for debugging remains possible; neither mode is approved.
    assert result["selected"]["debugging"] == [digest]


def test_positive_inline_module_evidence_is_preserved_without_task_approval(tmp_path):
    path = workbook(tmp_path / "reviewed.xlsx")
    digest = selector.file_sha256(path)
    evidence = {"financial_modeling_eligible": True,
                "safe_modules": [{"candidate_regions": ["Income!A1"]}],
                "business_correctness_certified": False}
    inv = tmp_path / "inventory.json"
    inv.write_text(json.dumps({"selected": [{"sha256": digest, "local_path": str(path),
                                             "finance_evidence": evidence}]}))
    result = selector.select(args(inv, require_business_evidence=True))
    assert result["selected"]["financial_modeling"] == [digest]
    assert result["candidates"][0]["business_evidence"] == evidence
    assert result["candidates"][0]["generation_approval"] is False


def test_original_and_normalized_hashes_are_not_confused(tmp_path):
    raw = tmp_path / "original.xls"
    raw.write_bytes(b"original source bytes, not opened in this fixture")
    normalized = workbook(tmp_path / "normalized.xlsx")
    digest = selector.file_sha256(raw)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(json.dumps({"selected": [{"sha256": digest, "local_path": str(raw), "archive_member": "financial/processed/example.xls"}]}))
    second.write_text(json.dumps([{"source_sha256": digest, "normalized_path": str(normalized)}]))
    result = selector.select(args(first, inventory=[first, second]))
    assert result["source_count"] == 1
    row = result["candidates"][0]
    assert row["analysis_status"] == "profiled"
    assert row["features"]["normalized_sha256"] != digest
    assert row["source_sha256"] == digest


def test_stable_order_and_explicit_used_policy():
    def candidate(digest, score, used):
        return {"source_sha256": digest, "analysis_status": "profiled", "used_in_final_tasks": used,
                "potential": {"debugging": {"score": score}}}
    rows = [candidate("b", 4, False), candidate("a", 4, False), candidate("c", 100, True)]
    assert [r["source_sha256"] for r in selector.rank_candidates(rows, "debugging")] == ["a", "b", "c"]
    assert [r["source_sha256"] for r in selector.rank_candidates(rows[::-1], "debugging")] == ["a", "b", "c"]
    assert [r["source_sha256"] for r in selector.rank_candidates(rows, "debugging", "allow")] == ["c", "a", "b"]
    assert [r["source_sha256"] for r in selector.rank_candidates(rows, "debugging", "exclude")] == ["a", "b"]


def test_legacy_xls_requires_explicit_normalization_and_output_is_immutable(tmp_path):
    raw = tmp_path / "raw.xls"
    raw.write_bytes(b"legacy source fixture")
    inv = tmp_path / "inventory.json"
    inv.write_text(json.dumps([{"source_sha256": selector.file_sha256(raw), "source_path": str(raw)}]))
    output = tmp_path / "selection.json"
    assert selector.main(["--inventory", str(inv), "--output", str(output)]) == 0
    assert json.loads(output.read_text())["analysis_status_counts"] == {"needs_normalized_workbook": 1}
    import pytest
    with pytest.raises(SystemExit):
        selector.main(["--inventory", str(inv), "--output", str(output)])
