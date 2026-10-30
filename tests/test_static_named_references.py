"""Workbook-aware static dependencies retain strict failures on uncertainty."""
from copy import deepcopy

import openpyxl
from openpyxl.worksheet.formula import ArrayFormula, DataTableFormula
from openpyxl.workbook.defined_name import DefinedName
import pytest

from sheets_factory.workbook.profile import formula_references, profile_workbook
from sheets_factory.workbook.static_references import (
    StaticReferenceError, expand_static_formula, expand_static_formula_details, static_formula_text,
)


@pytest.fixture
def book():
    result = openpyxl.Workbook()
    result.active.title = "Model"
    result.create_sheet("Owner's Inputs")
    result["Owner's Inputs"]["B2"] = 10
    result["Owner's Inputs"]["D5"] = 20
    result["Model"]["A1"] = 3
    result["Model"]["C4"] = 7
    return result


def define(book, name, value, scope=None):
    defined = DefinedName(name, attr_text=value)
    if scope is None:
        book.defined_names.add(defined)
    else:
        book[scope].defined_names.add(defined)


def addresses(result):
    return {(item["sheet"], item["cell"]) for item in result["references"]}


def test_global_names_aliases_and_quoted_sheet_addresses(book):
    define(book, "base_rate", "'Owner''s Inputs'!$B$2")
    define(book, "alias_rate", "base_rate")
    define(book, "second_alias", "=alias_rate")
    result = formula_references("=A1+SECOND_ALIAS", "Model", workbook=book)
    assert result["fully_supported"]
    assert addresses(result) == {("Model", "A1"), ("Owner's Inputs", "B2")}
    assert [entry["name"] for entry in result["resolved_names"]] == ["second_alias", "alias_rate", "base_rate"]
    assert "'Owner''s Inputs'!B2" in expand_static_formula("=second_alias", "Model", book)


def test_local_scope_overrides_global_and_explicit_sheet_uses_local_scope(book):
    define(book, "rate", "'Owner''s Inputs'!$B$2")
    define(book, "rate", "Model!$C$4", scope="Model")
    assert addresses(formula_references("=rate", "Model", workbook=book)) == {("Model", "C4")}
    assert addresses(formula_references("=rate", "Owner's Inputs", workbook=book)) == {("Owner's Inputs", "B2")}
    assert addresses(formula_references("=Model!RATE", "Owner's Inputs", workbook=book)) == {("Model", "C4")}


@pytest.mark.parametrize("literal", ["0.25", "-1.5", "2E-3", '"fixed text"', '"a""b"', "TRUE", "FALSE"])
def test_scalar_constant_names_have_no_invented_cell_dependencies(book, literal):
    define(book, "assumption", literal)
    result = formula_references("=IF(assumption,A1,0)", "Model", workbook=book)
    assert result["fully_supported"]
    assert addresses(result) == {("Model", "A1")}
    assert "(" + literal + ")" in expand_static_formula("=assumption", "Model", book)


def test_static_named_rectangle_expands_all_cells_including_blanks(book):
    define(book, "rectangle", "'Owner''s Inputs'!$B$2:$D$5")
    result = formula_references("=SUM(rectangle)", "Model", workbook=book)
    assert result["fully_supported"] and len(result["references"]) == 12
    assert ("Owner's Inputs", "C3") in addresses(result)  # An intervening blank is still a dependency.


@pytest.mark.parametrize("formula,expected", [
    ("=SUM('Owner''s Inputs'!B:D)", {("Owner's Inputs", f"{c}{r}") for c in "BCD" for r in range(1, 6)}),
    ("=SUM('Owner''s Inputs'!2:3)", {("Owner's Inputs", f"{c}{r}") for c in "ABCD" for r in (2, 3)}),
])
def test_whole_ranges_bound_to_nonempty_used_extent_and_report_blank_omission(book, formula, expected):
    book["Owner's Inputs"].cell(10000, 100).number_format = "0.00"  # Formatting is not a used value.
    result = formula_references(formula, "Model", workbook=book)
    assert result["fully_supported"]
    assert addresses(result) == expected
    metadata = result["bounded_ranges"][0]
    assert metadata["nonempty_used_extent"] == {"max_row": 5, "max_column": 4}
    assert metadata["omitted_coordinates_currently_blank"] is True
    assert metadata["all_currently_used_dependencies_included"] is True
    assert result["analysis_only"] is True


def test_named_whole_column_and_empty_column_are_conservative(book):
    define(book, "all_values", "'Owner''s Inputs'!$B:$B")
    result = formula_references("=SUM(all_values)", "Model", workbook=book)
    assert addresses(result) == {("Owner's Inputs", "B" + str(row)) for row in range(1, 6)}
    # A requested column outside the used columns remains explicit, not dropped.
    empty = formula_references("=SUM('Owner''s Inputs'!Z:Z)", "Model", workbook=book)
    assert addresses(empty) == {("Owner's Inputs", "Z" + str(row)) for row in range(1, 6)}


@pytest.mark.parametrize("definition", [
    "OFFSET(Model!$A$1,0,0)", "INDIRECT(\"Model!A1\")", "SUM(Model!$A$1:$C$4)",
    "'[1]Other'!$A$1", "'[external.xlsx]Sheet1'!$A$1", "Missing!$A$1",
    "Model!A1", "$A$1", "unknown_alias", "#REF!",
])
def test_unsupported_names_never_silently_drop_dependencies(book, definition):
    define(book, "unsafe", definition)
    with pytest.raises(StaticReferenceError):
        expand_static_formula("=A1+unsafe", "Model", book)
    result = formula_references("=A1+unsafe", "Model", workbook=book)
    assert not result["fully_supported"] and result["unsupported"]


def test_alias_cycles_and_case_insensitive_cycles_fail(book):
    define(book, "first", "second")
    define(book, "second", "FIRST")
    with pytest.raises(StaticReferenceError, match="cyclic_defined_name"):
        expand_static_formula("=first", "Model", book)


def test_unknown_or_dynamic_formula_and_large_ranges_stay_unsupported(book):
    for formula in ("=missing_name", "=INDIRECT(\"A1\")", "=OFFSET(A1,1,0)", "=Missing!A1", "=SUM(A1:C4)"):
        result = formula_references(formula, "Model", max_expansion=5, workbook=book)
        assert not result["fully_supported"]
    with pytest.raises(StaticReferenceError, match="large_range"):
        expand_static_formula("=SUM(A1:A4)+SUM(B1:B4)", "Model", book, max_expansion=7)


def test_formula_strings_are_not_mistaken_for_dynamic_functions(book):
    result = formula_references('="INDIRECT(A1) [external.xlsx]"', "Model", workbook=book)
    assert result["fully_supported"] and result["references"] == []


def test_no_context_parser_preserves_strict_legacy_behavior(book):
    assert formula_references("=A1+B2", "Model") == {
        "references": [{"sheet": "Model", "cell": "A1"}, {"sheet": "Model", "cell": "B2"}],
        "unsupported": [], "fully_supported": True,
    }
    assert not formula_references("=start_date", "Model")["fully_supported"]
    assert not formula_references("=SUM(A:A)", "Model")["fully_supported"]


def test_single_cell_array_is_analyzable_but_group_objects_stay_original(book, tmp_path):
    ws = book["Model"]
    ws["C2"] = ArrayFormula(ref="C2:C2", text="=SUMPRODUCT(--(ABS(A1:A4)>0.01))=0")
    value = ws["C2"].value
    assert static_formula_text(ws["C2"]) == value.text
    assert ws["C2"].value is value
    path = tmp_path / "array.xlsx"
    book.save(path)
    profile = profile_workbook(path)
    item = next(c for s in profile["sheets"] if s["name"] == "Model" for c in s["cells"] if c["cell"] == "C2")
    assert item["dependencies"]["fully_supported"]
    assert item["formula_group"]["formula_object_type"] == "ArrayFormula"


@pytest.mark.parametrize("value", [
    ArrayFormula(ref="C2:C3", text="=A1:A2"),
    ArrayFormula(ref="D2:D2", text="=A1"),
    DataTableFormula(ref="C2", dt2D=True),
])
def test_multicell_array_misaligned_array_and_data_table_fail(book, value):
    book["Model"]["C2"] = value
    with pytest.raises(StaticReferenceError, match="unsupported_formula_group"):
        static_formula_text(book["Model"]["C2"])


def test_analysis_does_not_mutate_cells_names_formulas_or_dimensions(book):
    define(book, "rate", "'Owner''s Inputs'!$B$2")
    book["Model"]["D4"] = "=SUM(rate,A:A)"
    before = {ws.title: (ws.max_row, ws.max_column, {k: (c.value, c.data_type) for k, c in ws._cells.items()}) for ws in book}
    names = deepcopy({name: value.attr_text for name, value in book.defined_names.items()})
    result = expand_static_formula_details(book["Model"]["D4"].value, "Model", book)
    assert result["formula"] != book["Model"]["D4"].value
    after = {ws.title: (ws.max_row, ws.max_column, {k: (c.value, c.data_type) for k, c in ws._cells.items()}) for ws in book}
    assert before == after
    assert names == {name: value.attr_text for name, value in book.defined_names.items()}
