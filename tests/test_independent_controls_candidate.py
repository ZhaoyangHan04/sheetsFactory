"""Hand arithmetic and pure formula replay; no model, native office or services."""
from copy import deepcopy
from decimal import Decimal, localcontext
import ast
import importlib.util
from pathlib import Path
import re
import socket
import subprocess
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import openpyxl
from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils.cell import get_column_letter, range_boundaries
import pytest

from sheets_factory.workbook import independent_controls_candidate as candidate
from sheets_factory.workbook import independent_controls_oracle as oracle


@pytest.fixture(autouse=True)
def no_services(monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError("Prototype tests may not execute services")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def driver():
    path = candidate.ROOT / "scripts/prepare_independent_controls_candidate.py"
    spec = importlib.util.spec_from_file_location("_independent_control_preparation", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def tiny():
    value = candidate.load(); value["periods"] = 1
    value["operating"] = value["operating"][:2]; value["financing"] = value["financing"][:2]
    value["default_financing"] = "F02"
    for row in value["operating"]: row.update(growth="0", ebitda_margin="0.20")
    value["financing"][0].update(interest_rate="0.10", facility_limit="50", sweep_fraction="1")
    value["financing"][1].update(interest_rate="0", facility_limit="100", sweep_fraction="0.5")
    value["entities"][0].update(opening_revenue="100", opening_cash="10", opening_debt="50", minimum_cash="5", annual_principal="10", tax_rate="0.25", working_capital_fraction="0.1", enterprise_multiple="5", capex=["20"])
    return candidate.validate(value)


def row(result, operating="O01", financing="F01", year=2027):
    return next(r["values"] for r in result["rows"] if r["operating"] == operating and r["financing"] == financing and r["year"] == year)


def test_hand_arithmetic_binding_facility_and_sponsor_cure():
    r = row(oracle.compute(tiny()))
    expected = {"revenue": "100", "ebitda": "20", "interest": "5", "cash_tax": "3.75", "mandatory_principal": "10", "cash_before_funding": "-8.75", "borrowing_capacity": "10", "new_borrowing": "10", "sponsor_cure": "3.75", "cash_sweep": "0", "closing_debt": "50", "closing_cash": "5", "enterprise_value": "100", "residual_equity": "55", "cumulative_sponsor_cures": "3.75", "contribution_adjusted_residual": "51.25"}
    assert {k: Decimal(r[k]) for k in expected} == {k: Decimal(v) for k, v in expected.items()}


def test_hand_arithmetic_surplus_sweep_stops_at_zero_debt():
    value = tiny(); value["entities"][0].update(opening_cash="100", capex=["0"])
    r = row(oracle.compute(value))
    assert Decimal(r["cash_before_funding"]) == Decimal("101.25")
    assert Decimal(r["new_borrowing"]) == Decimal(r["sponsor_cure"]) == 0
    assert Decimal(r["cash_sweep"]) == 40
    assert Decimal(r["closing_debt"]) == 0
    assert Decimal(r["closing_cash"]) == Decimal("61.25")
    assert Decimal(r["residual_equity"]) == Decimal("161.25")


def test_loss_tax_and_enterprise_boundaries_and_working_capital_release():
    value = tiny(); value["operating"][0].update(growth="-0.1", ebitda_margin="-0.1")
    r = row(oracle.compute(value))
    assert Decimal(r["revenue"]) == 90
    assert Decimal(r["ebitda"]) == -9
    assert Decimal(r["working_capital_change"]) == -1
    assert Decimal(r["cash_tax"]) == Decimal(r["enterprise_value"]) == 0
    assert Decimal(r["closing_cash"]) >= 5


def test_control_fault_passes_diagonal_but_fails_mixed_states():
    value = candidate.load(); good = oracle.compute(value); bad = oracle.compute(value, couple_controls=True)
    diagonal = mixed = 0
    for reference, actual in zip(good["rows"], bad["rows"]):
        if reference["operating"][1:] == reference["financing"][1:]:
            diagonal += 1; assert reference["values"] == actual["values"]
        else:
            mixed += reference["values"] != actual["values"]
        assert all(actual["invariants"].values())
    assert diagonal == 9 and mixed == 18
    default_good = row(good, financing="F03"); default_bad = row(bad, financing="F03")
    assert Decimal(default_good["interest"]) == Decimal("21.60")
    assert Decimal(default_bad["interest"]) == Decimal("12.60")
    assert default_good != default_bad


def test_bridge_double_count_is_exactly_new_draw_and_later_cure_adjustment():
    public = tiny(); good = row(oracle.compute(public)); bad = row(oracle.compute(public, double_count_new_debt=True))
    assert Decimal(good["residual_equity"]) - Decimal(bad["residual_equity"]) == Decimal(good["new_borrowing"]) == 10
    assert good["closing_debt"] == bad["closing_debt"] and good["closing_cash"] == bad["closing_cash"]
    assert Decimal(good["contribution_adjusted_residual"]) - Decimal(bad["contribution_adjusted_residual"]) == 10


def evaluate_formula_book(path):
    """Test-only interpreter for the emitted arithmetic subset, no office engine.

    This third path reads actual serialized formulas. It does not use business
    equations or expected values from either production implementation.
    """
    workbook = openpyxl.load_workbook(path, data_only=False); cache = {}; pending = set()
    def reference(sheet, text):
        if "!" in text:
            sheet, text = text.rsplit("!", 1); sheet = sheet.strip("'").replace("''", "'")
        text = text.replace("$", "")
        if ":" not in text: return cell(sheet, text)
        left, top, right, bottom = range_boundaries(text)
        return [cell(sheet, get_column_letter(col) + str(row)) for row in range(top, bottom + 1) for col in range(left, right + 1)]
    def index(values, position):
        assert position == int(position) and 1 <= position <= len(values)
        return values[int(position) - 1]
    def cell(sheet, address):
        key = sheet, address
        if key in cache: return cache[key]
        assert key not in pending, "Unexpected circular prototype formula"
        value = workbook[sheet][address].value
        if isinstance(value, (int, float)) and not isinstance(value, bool): return Decimal(str(value))
        if not isinstance(value, str) or not value.startswith("="): return value
        pending.add(key); pieces = []
        for token in Tokenizer(value).items:
            if token.type == "WSPACE": continue
            if token.type == "OPERAND" and token.subtype == "RANGE": pieces.append("REF(" + repr(token.value) + ")")
            elif token.type == "OPERAND" and token.subtype == "NUMBER": pieces.append("DEC(" + repr(token.value) + ")")
            elif token.type == "FUNC":
                if token.subtype == "OPEN":
                    name = token.value[:-1].upper(); assert name in {"INDEX", "MAX", "MIN"}; pieces.append(name + "(")
                else: pieces.append(")")
            elif token.type in {"PAREN", "SEP", "OPERATOR-INFIX", "OPERATOR-PREFIX"}:
                assert token.value in {"(", ")", ",", "+", "-", "*", "/", "^"}; pieces.append("**" if token.value == "^" else token.value)
            else: raise AssertionError((token.type, token.subtype, token.value))
        expression = "".join(pieces); tree = ast.parse(expression, mode="eval")
        assert all(isinstance(node, (ast.Expression, ast.Call, ast.Name, ast.Load, ast.Constant, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.UAdd, ast.USub)) for node in ast.walk(tree))
        with localcontext() as context:
            context.prec = 50
            result = eval(compile(tree, "<prototype-formula-test>", "eval"), {"__builtins__": {}}, {"REF": lambda x: reference(sheet, x), "DEC": Decimal, "INDEX": index, "MIN": min, "MAX": max})
        cache[key] = result; pending.remove(key); return result
    return workbook, cell


@pytest.mark.parametrize("variant", ["reference", "control", "bridge", "combined"])
def test_actual_emitted_formulas_match_independent_business_oracle(tmp_path, variant):
    public = candidate.load(); emitted = candidate.emit(public, tmp_path / "gold.xlsx")
    edits = [e for e in emitted["debug_mutations"] if variant == "combined" or variant == "control" and e["family"] == "independent_financing_control" or variant == "bridge" and e["family"] == "enterprise_equity_bridge"]
    path = tmp_path / "gold.xlsx"
    if edits: path = tmp_path / "mutated.xlsx"; candidate.materialize(emitted["source"]["path"], path, edits)
    ledger = oracle.compute(public, couple_controls=variant in {"control", "combined"}, double_count_new_debt=variant in {"bridge", "combined"})
    expected = driver().expected_targets(emitted["financial_targets"], ledger)
    workbook, read_cell = evaluate_formula_book(path)
    for target in expected:
        actual = read_cell(target["sheet"], target["cell"])
        assert abs(actual - Decimal(target["expected"]["value"])) < Decimal("0.00000001"), target
    workbook.close()


def test_emitter_and_oracle_have_no_shared_financial_import_or_official_seed():
    emitter = Path(candidate.__file__).read_text(); oracle_source = Path(oracle.__file__).read_text()
    imports = [node for node in ast.walk(ast.parse(emitter)) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert all("independent_controls_oracle" not in ast.unparse(node) for node in imports)
    oracle_imports = [ast.unparse(node) for node in ast.walk(ast.parse(oracle_source)) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert oracle_imports == ["from __future__ import annotations", "from decimal import Decimal, localcontext"]
    assert "load_workbook" not in emitter and "SpreadsheetEval" not in emitter


def test_pair_preparation_freezes_both_plans_masks_all_aliases_and_does_not_plant_caches(tmp_path):
    receipt = driver().prepare(candidate.load(), tmp_path / "prototype")
    import json
    prepared = json.loads(Path(receipt["path"]).read_text()); private = tmp_path / "prototype/private"
    assert prepared["dimensions"]["financial_output_targets"] == 546
    assert prepared["dimensions"]["crossed_states_per_entity"] == 9
    assert prepared["actual_LO_model_solver_Harbor_network_calls"] == 0
    assert prepared["qualified"] is prepared["hardness_validated"] is False
    fm_plan = json.loads((private / "FM_plan.json").read_text()); dbg_plan = json.loads((private / "DBG_plan.json").read_text())
    assert len(fm_plan["edits"]) == 546
    assert dbg_plan["fault_families"] == {"independent_financing_control": 81, "enterprise_equity_bridge": 27}
    fm = openpyxl.load_workbook(tmp_path / "prototype/FM/input.xlsx")
    assert all(fm[e["sheet"]][e["cell"]].value is None for e in fm_plan["edits"])
    assert not any(c.data_type == "f" for s in fm for row in s for c in row)
    fm.close()
    dbg = openpyxl.load_workbook(tmp_path / "prototype/DBG/input.xlsx")
    assert all(dbg[e["sheet"]][e["cell"]].value == e["after"] for e in dbg_plan["edits"])
    assert all(re.search(r"\$D[0-9]", e["after"]) is None for e in dbg_plan["edits"] if e["family"] == "independent_financing_control")
    dbg.close()
    for path in [private / "formula_gold.xlsx", tmp_path / "prototype/DBG/input.xlsx"]:
        with ZipFile(path) as archive:
            for part in archive.namelist():
                if not part.startswith("xl/worksheets/sheet") or not part.endswith(".xml"): continue
                root = ET.fromstring(archive.read(part))
                assert all(c.find("{*}v") is None or not c.find("{*}v").text for c in root.findall("{*}sheetData/{*}row/{*}c") if c.find("{*}f") is not None)
    for mode in ["FM", "DBG"]:
        brief = (tmp_path / "prototype" / mode / "instruction.txt").read_text()
        assert "independent" in brief and "every listed entity" in brief
        assert "Restricted liquidity" in brief and "Steady demand" in brief
        assert all(word not in brief for word in ["double-count", "wrong lookup", "L5", "$D", "Cash-flow!"])


def test_configuration_dimensions_are_real_crossed_states_and_independent_entities(tmp_path):
    value = tiny(); value["periods"] = 2; value["entities"][0]["capex"] = ["20", "0"]
    extra = deepcopy(value["entities"][0]); extra.update(id="E02", name="South business", opening_revenue="200", opening_cash="12", opening_debt="40", capex=["10", "25"])
    value["entities"].append(extra); value = candidate.validate(value)
    emitted = candidate.emit(value, tmp_path / "gold.xlsx"); result = oracle.compute(value)
    assert len(result["rows"]) == 2 * 2 * 2 * 2
    assert len(emitted["layout"]) == len(result["rows"])
    assert len(emitted["financial_targets"]) == len(result["rows"]) * 20 + 12
    expected = driver().expected_targets(emitted["financial_targets"], result)
    workbook, read_cell = evaluate_formula_book(tmp_path / "gold.xlsx")
    for target in expected: assert abs(read_cell(target["sheet"], target["cell"]) - Decimal(target["expected"]["value"])) < Decimal("1e-8")
    workbook.close()


def test_cold_edit_guards_preserve_original_and_duplicate_targets_are_rejected(tmp_path):
    emitted = candidate.emit(tiny(), tmp_path / "gold.xlsx"); original = candidate.reference(tmp_path / "gold.xlsx")
    edit = emitted["debug_mutations"][0]
    with pytest.raises(ValueError, match="Duplicate"): candidate.materialize(tmp_path / "gold.xlsx", tmp_path / "duplicate.xlsx", [edit, edit])
    wrong = {**edit, "before": "=1"}
    with pytest.raises(ValueError, match="Cold cell"): candidate.materialize(tmp_path / "gold.xlsx", tmp_path / "wrong.xlsx", [wrong])
    assert candidate.reference(tmp_path / "gold.xlsx") == original
    with pytest.raises(ValueError, match="Fresh"): candidate.emit(tiny(), tmp_path / "gold.xlsx")


@pytest.mark.parametrize("change", ["unknown", "old_kind", "boolean", "diagonal", "period", "capex", "rate", "opening_debt", "id"])
def test_assumption_identity_and_domain_guards(change):
    value = tiny()
    if change == "unknown": value["old_gold"] = "forbidden"
    elif change == "old_kind": value["kind"] = "official_workbook"
    elif change == "boolean": value["version"] = True
    elif change == "diagonal": value["default_financing"] = "F01"
    elif change == "period": value["periods"] = 7
    elif change == "capex": value["entities"][0]["capex"] = []
    elif change == "rate": value["financing"][0]["interest_rate"] = "NaN"
    elif change == "opening_debt": value["entities"][0]["opening_debt"] = "51"
    elif change == "id": value["entities"][0]["id"] = "E02"
    with pytest.raises(ValueError): candidate.validate(value)
