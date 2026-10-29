from datetime import datetime
import os
from pathlib import Path

import openpyxl
import pytest

from sheets_factory.workbook import (LibreOfficeEngine, compare_workbooks,
                                     formula_references, normalize_value, profile_workbook)


def save_book(path, values, hidden=False):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Forecast"
    for address, value in values.items():
        sheet[address] = value
    extra = book.create_sheet("Inputs")
    extra["A1"] = 4
    if hidden:
        extra.sheet_state = "hidden"
    book.save(path)
    return path


def test_typed_normalization():
    assert normalize_value(2.675) == ("number", "2.68")
    assert normalize_value(-2.675) == ("number", "-2.68")
    assert normalize_value(-0.0001) == normalize_value(0)
    assert normalize_value(True) != normalize_value(1)
    assert normalize_value("001") != normalize_value(1)
    assert normalize_value(None) == normalize_value("")
    assert normalize_value(" ") != normalize_value("")
    assert normalize_value(datetime(2024, 1, 1, 12)) != normalize_value(datetime(2024, 1, 1))


def test_exact_delta_and_unrelated_changes(tmp_path):
    initial = save_book(tmp_path/"input.xlsx", {"A1": "Revenue", "B1": None})
    goal = save_book(tmp_path/"goal.xlsx", {"A1": "Revenue", "B1": 12.345})
    equivalent = save_book(tmp_path/"equivalent.xlsx", {"A1": "Revenue", "B1": 12.349})
    wrong = save_book(tmp_path/"wrong.xlsx", {"A1": "Revenue", "B1": 12.345, "XFD500": "extra"})
    assert compare_workbooks(initial, goal, goal)["reward"] == 1
    assert compare_workbooks(initial, goal, initial)["reward"] == 0
    assert compare_workbooks(initial, goal, equivalent)["reward"] == 1
    result = compare_workbooks(initial, goal, wrong)
    assert result["reward"] == 0
    assert result["extra_changes"] == ["Forecast!XFD500"]


def test_hidden_and_new_sheet_cannot_escape_compare(tmp_path):
    initial = save_book(tmp_path/"input.xlsx", {"A1": 1}, hidden=True)
    goal = save_book(tmp_path/"goal.xlsx", {"A1": 2}, hidden=True)
    output = save_book(tmp_path/"output.xlsx", {"A1": 2}, hidden=True)
    book = openpyxl.load_workbook(output)
    book["Inputs"]["A1"] = 9
    book.save(output)
    assert compare_workbooks(initial, goal, output)["reward"] == 0
    book["Inputs"]["A1"] = 4
    book.create_sheet("Extra")
    book.save(output)
    assert compare_workbooks(initial, goal, output)["structure_ok"] is False


def test_output_format_cannot_redefine_numeric_value(tmp_path):
    initial = save_book(tmp_path/"input.xlsx", {"A1": 45000, "B1": None})
    goal = save_book(tmp_path/"goal.xlsx", {"A1": 45000, "B1": 2})
    output = save_book(tmp_path/"output.xlsx", {"A1": 45000, "B1": 2})
    book = openpyxl.load_workbook(output)
    book["Forecast"]["A1"].number_format = "yyyy-mm-dd"
    book.save(output)
    assert compare_workbooks(initial, goal, output)["reward"] == 1


def test_profile_context_and_conservative_dependencies(tmp_path):
    path = save_book(tmp_path/"model.xlsx", {"A1": "Revenue", "B1": "=Inputs!$A$1*3", "A2": "Cost", "B2": "=SUM(B1:B1)"})
    profile = profile_workbook(path)
    assert profile["formula_count"] == 2
    assert profile["sheet_count"] == 2
    formula = next(c for c in profile["sheets"][0]["cells"] if c["cell"] == "B1")
    assert formula["row_labels"] == [{"cell": "A1", "value": "Revenue"}]
    assert formula["dependencies"]["references"] == [{"sheet": "Inputs", "cell": "A1"}]
    assert formula_references('=INDIRECT("B1")', "Forecast")["fully_supported"] is False
    assert formula_references("=MyNamedRange*2", "Forecast")["fully_supported"] is False
    assert formula_references("='Input Data'!A1:B2", "Forecast")["fully_supported"] is True
    limited = profile_workbook(path, max_cells=1)
    assert limited["truncated"] is True
    assert limited["formula_count"] == 2


def test_array_formula_profile_is_serializable_and_marked_unsupported(tmp_path):
    import json
    from openpyxl.worksheet.formula import ArrayFormula
    path = save_book(tmp_path/"array.xlsx", {"A1": 1, "A2": 2})
    book = openpyxl.load_workbook(path)
    book["Forecast"]["B1"] = ArrayFormula(ref="B1:B2", text="=A1:A2*2")
    book.save(path)
    profile = profile_workbook(path)
    json.dumps(profile)
    cell = next(c for c in profile["sheets"][0]["cells"] if c["cell"] == "B1")
    assert cell["dependencies"]["fully_supported"] is False
    assert cell["formula_group"]["ref"] == "B1:B2"


@pytest.mark.skipif(os.environ.get("SF_TEST_LIBREOFFICE") != "1", reason="Requires Docker LibreOffice image")
def test_real_libreoffice_recalculates_and_rejects_false_cache(tmp_path):
    root = Path(__file__).resolve().parents[1]
    engine = LibreOfficeEngine(root)
    path = save_book(tmp_path/"model.xlsx", {"A1": "Revenue", "B1": "=Inputs!A1*3"})
    result = engine.recalculate(path, tmp_path/"calculated.xlsx")
    book = openpyxl.load_workbook(result, data_only=True)
    assert book["Forecast"]["B1"].value == 12
    stable = engine.check_stable(result, tmp_path/"stability")
    assert stable["stable"]
    formulas = openpyxl.load_workbook(result)
    formulas["Forecast"]["B1"] = "=Inputs!A1*4"
    formulas.save(tmp_path/"wrong_formula.xlsx")
    wrong = engine.recalculate(tmp_path/"wrong_formula.xlsx", tmp_path/"wrong_calc.xlsx")
    assert compare_workbooks(path, result, wrong)["reward"] == 0
    assert engine.metadata()["version"].startswith("LibreOffice 24.2.7")
