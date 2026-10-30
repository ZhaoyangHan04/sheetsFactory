"""Offline authoring tests. Injected numeric caches are fixtures, not LO proof."""

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import openpyxl
from openpyxl.utils.cell import range_boundaries
import pytest

from sheets_factory.nodes.construction import compile_mask_ranges, validate_plan
from sheets_factory.workbook.derived_gold.excel import emit_workbook
from sheets_factory.workbook.derived_gold.ledger import simulate
from sheets_factory.workbook.derived_gold.spec import ANCHORS, resolve_spec
from sheets_factory.workbook.derived_gold.task_templates import propose_project_task
from sheets_factory.workbook.derived_gold.validate import audit_workbook


ROOT = Path(__file__).resolve().parents[1]
CONSTRUCTION = {"construction": {"max_edit_count": {"financial_modeling": 8192, "debugging": 300}}}
TAX = {"advanced_tax_enabled": 1, "initial_tax_rate_y1": ".50", "initial_tax_rate_y2": ".30",
       "initial_tax_rate_y3": ".20", "refresh_tax_rate_y1": ".60", "refresh_tax_rate_y2": ".30",
       "refresh_tax_rate_y3": ".10", "interest_deduction_ebitda_fraction": ".30", "nol_carryforward_years": 1}


def _write_fixture_caches(path, cell_checks):
    """Fixture-only numeric caches from independent test ledger bindings."""
    numeric = {item["address"]: item["expected_independent"] for item in cell_checks
               if item["kind"] != "date"}
    book = openpyxl.load_workbook(path)
    sheets = list(book.sheetnames)
    book.close()
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    output = path.with_suffix(".cached.xlsx")
    with ZipFile(path) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            match = re.fullmatch(r"xl/worksheets/sheet([0-9]+)\.xml", item.filename)
            if match:
                sheet = sheets[int(match.group(1)) - 1]
                xml = ET.fromstring(data)
                for cell in xml.iter(ns + "c"):
                    address = sheet + "!" + cell.attrib["r"]
                    formula = cell.find(ns + "f")
                    if formula is not None and formula.text:
                        # LO canonicalizes redundant same-sheet qualifiers on
                        # range endpoints.  This fixture makes only that lexical
                        # transformation, without claiming an actual LO run.
                        formula.text = re.sub(r"('Scenario'!\$B\$[0-9]+):'Scenario'!(\$B\$[0-9]+)",
                                              r"\1:\2", formula.text)
                    if formula is None or address not in numeric:
                        continue
                    value = cell.find(ns + "v")
                    if value is None:
                        value = ET.SubElement(cell, ns + "v")
                    value.text = numeric[address]
                    cell.attrib.pop("t", None)
                data = ET.tostring(xml, encoding="utf-8", xml_declaration=True)
            target.writestr(item, data)
    output.replace(path)


@pytest.fixture
def build_project(tmp_path):
    sequence = 0

    def build(version="v7", *, reorder=False, identical_pricing=False, caches=True):
        nonlocal sequence
        sequence += 1
        folder = tmp_path / str(sequence)
        folder.mkdir()
        config = json.loads((ROOT / "config/derived_covenant_project_v1.json").read_text())
        if version == "disabled":
            config["covenant_parameters"]["covenant_enabled"] = 0
        if version == "v7":
            config["advanced_tax_parameters"] = deepcopy(TAX)
        if identical_pricing:
            config["hypothetical_parameters"]["loan_b_spread"] = config["hypothetical_parameters"]["loan_a_spread"]
        values = {"revenue": 34124, "ebit": 7040, "da": 1527, "tax_rate": .25,
                  "debt_rate": .0509, "equity_rate": .09110305231829893, "growth": .04}
        source = openpyxl.Workbook()
        source.remove(source.active)
        for key, (sheet, cell, _) in ANCHORS.items():
            if sheet not in source:
                source.create_sheet(sheet)
            source[sheet][cell] = values[key]
        anchor = folder / "test_anchor_fixture.xlsx"
        source.save(anchor)
        source.close()
        config["source"]["local_path"] = str(anchor)
        config["source"]["sha256"] = hashlib.sha256(anchor.read_bytes()).hexdigest()
        recipe = folder / "scenario.json"
        recipe.write_text(json.dumps(config))
        spec = resolve_spec(folder, recipe)
        if reorder:
            items = list(spec["parameters"].items())
            spec["parameters"] = dict(items[-7:] + items[:-7])
        path = folder / "project_fixture.xlsx"
        bindings = emit_workbook(spec, path)
        if caches:
            ledger = simulate(spec)
            checks = audit_workbook(path, spec, ledger, bindings)["cell_checks"]
            _write_fixture_caches(path, checks)
        return path
    return build


@pytest.mark.parametrize("version", ["disabled", "v6", "v7"])
def test_modeling_masks_complete_families_without_inputs_dates_or_literals(build_project, version):
    path = build_project(version)
    plan = propose_project_task(path, "financial_modeling")
    assert plan["edits"] == []
    assert plan["scenario_inputs"] == []
    book = openpyxl.load_workbook(path)
    seen = set()
    for group in plan["mask_ranges"]:
        assert group["sheet"] not in {"Read Me", "Source Inputs", "Scenario", "Calendar"}
        left, top, right, bottom = range_boundaries(group["range"])
        for row in book[group["sheet"]].iter_rows(min_row=top, max_row=bottom, min_col=left, max_col=right):
            for cell in row:
                key = (group["sheet"], cell.coordinate)
                assert key not in seen
                seen.add(key)
                assert cell.data_type == "f"
                assert not cell.is_date
                assert cell.row != 1
    expected = set()
    for sheet in plan["target_sheets"]:
        for row in book[sheet]:
            for cell in row:
                if cell.data_type != "f" or cell.is_date or cell.row == 1:
                    continue
                if sheet == "Equity Value" and cell.row == 15:
                    continue
                if sheet == "Annual Statements" and cell.row in {4, 5}:
                    continue
                expected.add((sheet, cell.coordinate))
    assert seen == expected
    assert len(seen) <= 8192
    assert len(plan["mask_ranges"]) <= 64
    compiled = compile_mask_ranges(plan, path, "financial_modeling", CONSTRUCTION)
    assert validate_plan(compiled, path, "financial_modeling", CONSTRUCTION)["before_assertions_passed"]
    assert all(edit["after"] is None for edit in compiled["edits"])
    book.close()


@pytest.mark.parametrize("mode", ["financial_modeling", "debugging"])
def test_public_brief_has_business_scope_without_answers_or_debug_coordinates(build_project, mode):
    plan = propose_project_task(build_project(), mode)
    instruction = plan["public_instruction"]
    assert 60 <= len(instruction.split()) <= 100
    assert "/app/input.xlsx" in instruction and "/app/output.xlsx" in instruction
    assert len(plan["public_rules"]) == 1
    public = instruction + " ".join(plan["public_rules"])
    assert not re.search(r"\b[A-Z]{1,3}[0-9]+\b", public)
    assert "=ROUND" not in public and "=IF" not in public
    assert not re.search(r"\d+\.\d+", public)
    assert "Read Me" in public and "Scenario" in public and "Source Inputs" in public


@pytest.mark.parametrize("version", ["v6", "v7"])
def test_debugging_changes_complete_populated_financing_and_asset_families(build_project, version):
    path = build_project(version)
    plan = propose_project_task(path, "debugging")
    assert "mask_ranges" not in plan
    assert 100 <= len(plan["edits"]) <= 300
    edits = plan["edits"]
    assert len({(edit["sheet"], edit["cell"]) for edit in edits}) == len(edits)
    book = openpyxl.load_workbook(path)
    values = openpyxl.load_workbook(path, data_only=True)
    for edit in edits:
        assert book[edit["sheet"]][edit["cell"]].value == edit["before"]
        assert edit["after"].startswith("=") and edit["after"] != edit["before"]
        assert edit["after"].count("IF(") == edit["before"].count("IF(")
        assert edit["after"] != "=(" + edit["before"][1:] + ")+1"
        assert isinstance(values[edit["sheet"]][edit["cell"]].value, (int, float))
    counts = Counter(edit["sheet"] for edit in edits)
    assert counts["Debt"] == 72
    assert counts["Assets"] == 47
    assert counts["Covenants"] == 1
    if version == "v7":
        assert counts["Tax Vintages"] == 2
    assert validate_plan(plan, path, "debugging", CONSTRUCTION)["before_assertions_passed"]
    book.close()
    values.close()


def test_real_parameter_labels_allow_different_scenario_row_order(build_project):
    ordinary = propose_project_task(build_project(), "debugging")
    moved = propose_project_task(build_project(reorder=True), "debugging")
    assert [(e["sheet"], e["cell"]) for e in ordinary["edits"]] == [(e["sheet"], e["cell"]) for e in moved["edits"]]
    assert ordinary["edits"][0]["before"] != moved["edits"][0]["before"]
    assert ordinary["edits"][0]["after"] != moved["edits"][0]["after"]


def test_equal_pricing_does_not_create_value_equivalent_bug_family(build_project):
    with pytest.raises(ValueError, match="100.*300.*locally evidenced"):
        propose_project_task(build_project(identical_pricing=True), "debugging")


def test_unrecalculated_workbook_cannot_support_debug_impact_claims(build_project):
    path = build_project(caches=False)
    with pytest.raises(ValueError, match="recalculated numeric"):
        propose_project_task(path, "debugging")


def test_business_policy_is_required_and_not_reconstructed_from_private_answers(build_project):
    path = build_project()
    book = openpyxl.load_workbook(path)
    for row in book["Read Me"]:
        for cell in row:
            cell.value = None
    book.save(path)
    book.close()
    with pytest.raises(ValueError, match="public business policies"):
        propose_project_task(path, "financial_modeling")


def test_shorter_business_policy_paragraphs_do_not_artificially_reject_documented_model(build_project):
    path = build_project()
    book = openpyxl.load_workbook(path)
    existing = [cell.value for row in book["Read Me"] for cell in row
                if isinstance(cell.value, str) and len(cell.value) >= 60]
    for row in book["Read Me"]:
        for cell in row:
            if isinstance(cell.value, str) and len(cell.value) >= 60:
                cell.value = None
    groups = [existing[i::5] for i in range(5)]
    for index, group in enumerate(groups, 4):
        book["Read Me"].cell(index, 2, " ".join(group))
    book.save(path)
    book.close()
    assert propose_project_task(path, "financial_modeling")["mask_ranges"]


def test_arbitrary_workbooks_and_modes_are_rejected(tmp_path):
    path = tmp_path / "arbitrary.xlsx"
    openpyxl.Workbook().save(path)
    with pytest.raises(ValueError, match="Unrecognized"):
        propose_project_task(path, "financial_modeling")
    with pytest.raises(ValueError, match="Unsupported"):
        propose_project_task(path, "invented_mode")
