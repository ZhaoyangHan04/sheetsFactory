"""Real large dependency graphs and explicit scope limits, without LO/models."""

from datetime import datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import openpyxl
import pytest

from sheets_factory.checkers.native_error_dependencies import dependency_error_reach
from sheets_factory.checkers.native_error_probe import probe_native_errors
from sheets_factory.core.node import TaskRejected
from sheets_factory.nodes.construction import (
    ProfileNode, compile_mask_ranges, construction_contract, validate_plan,
)
from sheets_factory.workbook.profile import formula_references, profile_workbook


LARGE = {"construction": {"max_edit_count": {"financial_modeling": 100000},
    "analysis_limits": {"max_dependency_closure_cells": 500000, "max_profile_cells": 500000,
                        "per_formula_reference_cells": 50000, "max_mask_ranges": 256}}}


def _caches(path, value_for):
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    replacement = path.with_suffix(".cached.xlsx")
    with ZipFile(path) as source, ZipFile(replacement, "w", ZIP_DEFLATED) as output:
        for item in source.infolist():
            raw = source.read(item.filename)
            if item.filename.startswith("xl/worksheets/sheet") and item.filename.endswith(".xml"):
                xml = ET.fromstring(raw)
                for cell in xml.iter(ns + "c"):
                    if cell.find(ns + "f") is not None:
                        cached = cell.find(ns + "v")
                        if cached is None:
                            cached = ET.SubElement(cell, ns + "v")
                        cached.text = str(value_for(item.filename, cell.attrib["r"]))
                raw = ET.tostring(xml, encoding="utf-8", xml_declaration=True)
            output.writestr(item, raw)
    replacement.replace(path)


@pytest.fixture(scope="module", params=[30000, 78000])
def chain(request, tmp_path_factory):
    size = request.param
    folder = tmp_path_factory.mktemp("long_financial_dependency_chain")
    path = folder / "explicit_cached_graph_fixture.xlsx"
    book = openpyxl.Workbook()
    book.active.title = "Inputs"
    book["Inputs"]["A1"] = 1
    hours = book.create_sheet("Hourly")
    for row in range(1, size + 1):
        hours.cell(row, 1, "='Inputs'!A1+1" if row == 1 else "=A" + str(row - 1) + "+1")
    summary = book.create_sheet("Summary")
    for row in range(1, 7):
        summary.cell(row, 1, "='Hourly'!A" + str(size - row + 1))
    book.create_sheet("Notes")["A1"] = "Explicit synthetic cache fixture; no actual calculation is implied."
    book.save(path)
    book.close()
    _caches(path, lambda sheet, address: int(address[1:]) + 1 if sheet.endswith("sheet2.xml")
            else size - int(address[1:]) + 2)
    plan = {"public_instruction": "Restore the stated connected forecast.", "public_rules": ["Use the public inputs."],
            "reference_evidence": ["The complete dependency chain is present in this test fixture."],
            "edits": [{"sheet": "Summary", "cell": "A" + str(row),
                       "before": "='Hourly'!A" + str(size - row + 1), "after": None}
                      for row in range(1, 7)]}
    return size, path, plan


def test_default_limits_are_preserved_and_opt_in_bounds_are_explicit():
    default = construction_contract()
    assert default["modes"]["financial_modeling"]["edit_count"]["max"] == 80
    assert default["dependency_requirements"]["max_dependency_closure_cells"] == 20000
    assert default["dependency_requirements"]["per_formula_reference_cells"] == 5000
    assert default["source_requirements"]["max_profile_cells"] == 200000
    assert default["range_authoring"]["max_ranges"] == 64
    expanded = construction_contract(config=LARGE)
    assert expanded["dependency_requirements"]["max_dependency_closure_cells"] == 500000
    assert expanded["source_requirements"]["max_profile_cells"] == 500000
    assert expanded["dependency_requirements"]["per_formula_reference_cells"] == 50000
    assert expanded["range_authoring"]["max_ranges"] == 256
    assert construction_contract(config={"construction": {"max_edit_count": {"financial_modeling": 200000}}})[
        "modes"]["financial_modeling"]["edit_count"]["max"] == 200000


@pytest.mark.parametrize("name,value", [
    ("max_dependency_closure_cells", 500001), ("max_profile_cells", 500001),
    ("per_formula_reference_cells", 50001), ("max_mask_ranges", 1025),
    ("max_profile_cells", True), ("max_mask_ranges", 0), ("unknown_limit", 1),
])
def test_unsupported_or_boolean_scope_limits_are_not_silently_accepted(name, value):
    with pytest.raises(ValueError, match="analysis limit"):
        construction_contract(config={"construction": {"analysis_limits": {name: value}}})


def test_deep_30k_and_78k_graphs_need_explicit_scope_and_never_use_python_recursion(chain):
    size, path, plan = chain
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(TaskRejected, match="closure exceeds supported analysis scope"):
        validate_plan(plan, path, "financial_modeling")
    result = validate_plan(plan, path, "financial_modeling", LARGE)
    assert result["dependency_closure_cells"] == size + 7
    assert result["dependency_sheets"] == ["Hourly", "Inputs", "Summary"]
    assert result["meaningful_nonzero_targets"] == 6
    assert len(result["cross_sheet_edges"]) == 7
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_actual_78k_masked_roots_are_compiled_and_validated_without_modifying_inputs(chain):
    size, path, seed = chain
    if size != 78000:
        pytest.skip("The separate closure test covers the smaller graph")
    plan = {key: value for key, value in seed.items() if key != "edits"}
    plan.update(edits=[], mask_ranges=[{"sheet": name, "range": "A1:A" + str(count),
        "reason": "Complete the calculation family", "business_rule": "Use the preserved public input."}
        for name, count in (("Hourly", size), ("Summary", 6))])
    before = path.read_bytes()
    with pytest.raises(TaskRejected, match="maximum=80"):
        compile_mask_ranges(plan, path, "financial_modeling")
    expanded = compile_mask_ranges(plan, path, "financial_modeling", LARGE)
    assert len(expanded["edits"]) == 78006
    assert all(edit["sheet"] != "Inputs" and edit["after"] is None for edit in expanded["edits"])
    assert validate_plan(expanded, path, "financial_modeling", LARGE)["dependency_closure_cells"] == 78007
    assert path.read_bytes() == before


def test_full_actual_required_D_is_kept_in_large_native_probe_receipt(chain, tmp_path):
    size, path, _ = chain
    labels = ["Hourly!A" + str(row) for row in range(1, size + 1)] + ["Summary!A" + str(row) for row in range(1, 7)]
    class NoCalculation:
        def recalculate(self, *args):
            raise AssertionError("No error candidates exist; this test must not invoke a calculator")
    receipt = probe_native_errors(goal=path, required_delta=labels, candidates=[], engine=NoCalculation(),
        directory=tmp_path / "native_probe", source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        plan={"fixture": True}, revision=0, max_dependency_cells=500000, per_formula_reference_cells=50000)
    assert receipt["blocking"] is False
    assert receipt["state"] == "not_applicable"
    assert receipt["full_dependency_closure_cells"] == size + 7
    assert len(receipt["required_delta"]) == size + 6
    assert set(receipt["required_delta"]) == set(labels)
    assert receipt["immutable_unchanged"] is True
    assert receipt["analysis_limits"] == {"max_dependency_closure_cells": 500000,
                                           "per_formula_reference_cells": 50000}


def test_profile_node_regenerates_incomplete_cache_using_actual_configured_coverage(chain, tmp_path):
    size, path, _ = chain
    if size != 78000:
        pytest.skip("The profile test uses the larger source")
    small = profile_workbook(path, max_cells=100)
    assert small["truncated"]
    cache = tmp_path / "profile_cache"
    cache.mkdir()
    (cache / "profile.json").write_text(json.dumps(small))
    context = SimpleNamespace(mode="financial_modeling", config=LARGE,
        data={"source_cache": cache, "baseline": path})
    full = ProfileNode().execute(context)["profile"]
    assert not full["truncated"]
    assert full["cells_emitted"] == size + 8
    assert full["formula_count"] == size + 6
    assert full["analysis_limits"] == {"max_profile_cells": 500000, "per_formula_reference_cells": 50000}


def test_144_sheet_families_require_explicit_range_budget_and_preserve_literals(tmp_path):
    path = tmp_path / "many_entities_fixture.xlsx"
    book = openpyxl.Workbook()
    book.active.title = "Inputs"
    book["Inputs"]["A1"] = 7
    ranges = []
    for index in range(144):
        sheet = book.create_sheet("Entity" + str(index))
        sheet["A1"] = "='Inputs'!A1+1"
        sheet["B1"] = "preserved literal"
        sheet["C1"] = datetime(2027, 1, 1)
        ranges.append({"sheet": sheet.title, "range": "A1:C1", "reason": "Complete family",
                       "business_rule": "Use public inputs."})
    book.save(path)
    book.close()
    before = path.read_bytes()
    with pytest.raises(TaskRejected, match="1 through 64"):
        compile_mask_ranges({"edits": [], "mask_ranges": ranges}, path, "financial_modeling")
    compiled = compile_mask_ranges({"edits": [], "mask_ranges": ranges}, path, "financial_modeling", LARGE)
    assert len(compiled["edits"]) == 144
    assert all(edit["cell"] == "A1" for edit in compiled["edits"])
    assert path.read_bytes() == before


def test_8760_cell_aggregation_is_explicitly_bounded_without_dropping_leaf_edges(tmp_path):
    path = tmp_path / "hourly_range_fixture.xlsx"
    book = openpyxl.Workbook()
    book.active.title = "Inputs"
    book["Inputs"]["A2"] = "#DIV/0!"
    hours = book.create_sheet("Hours")
    for row in range(1, 8761):
        hours.cell(row, 1, 1)
    summary = book.create_sheet("Summary")
    for row in range(1, 7):
        summary.cell(row, 1, "=SUM('Hours'!A1:A8760)")
    summary["A7"] = "=SUM('Hours'!A1:A8760)+IF(TRUE(),0,'Inputs'!A2)"
    book.save(path)
    book.close()
    _caches(path, lambda *args: 8760)
    plan = {"public_instruction": "Restore the yearly aggregation.", "public_rules": ["Sum all 8760 hours."],
            "reference_evidence": ["Explicit complete hourly source."],
            "edits": [{"sheet": "Summary", "cell": "A" + str(row), "before": "=SUM('Hours'!A1:A8760)", "after": None}
                      for row in range(1, 7)]}
    with pytest.raises(TaskRejected, match="unresolved"):
        validate_plan(plan, path, "financial_modeling")
    report = validate_plan(plan, path, "financial_modeling", LARGE)
    assert report["dependency_closure_cells"] == 8766
    assert len(report["cross_sheet_edges"]) == 6 * 8760
    candidate = {"sheet": "Inputs", "cell": "A2"}
    narrow = dependency_error_reach(path, ["Summary!A7"], [candidate], max_cells=20000,
                                    per_formula_reference_cells=50000)
    assert narrow["state"] == "verified"
    assert narrow["per_delta_errors"] == {"Summary!A7": []}
    assert narrow["closure_cells"] == 8761
    assert any("Inputs!A2" in item["ignored_errors"] for item in narrow["exclusions"])


def test_reference_cache_is_scoped_by_workbook_and_expansion_budget(monkeypatch):
    import sheets_factory.workbook.profile as module
    book = openpyxl.Workbook()
    book.active.title = "Facts"
    book["Facts"]["A8760"] = 1
    calls = []
    original = module.expand_static_formula_details
    def recorded(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "expand_static_formula_details", recorded)
    cache = {}
    formula = "=SUM(A1:A8760)"
    one = formula_references(formula, "Facts", 50000, workbook=book, cache=cache, include_resolved_formula=True)
    two = formula_references(formula, "Facts", 50000, workbook=book, cache=cache, include_resolved_formula=True)
    assert one == two and len(one["references"]) == 8760
    assert len(calls) == 1
    assert not formula_references(formula, "Facts", 5000, workbook=book, cache=cache)["fully_supported"]
    assert len(calls) == 2
    book.close()
