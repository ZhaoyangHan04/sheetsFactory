"""Contract, formula independence and complete independent-audit coverage.

These offline checks cannot certify evaluated Excel amounts. The source builder
must separately run real LibreOffice, the independent ledger and a stability run.
"""
from copy import deepcopy
from decimal import Decimal
from graphlib import TopologicalSorter
import hashlib
import json
from pathlib import Path

import openpyxl
from openpyxl.formula import Tokenizer
from openpyxl.utils.cell import range_boundaries
import pytest

from sheets_factory.workbook.derived_gold.excel import (
    emit_workbook, TAX_AGGREGATE_KEYS, TAX_VINTAGE_KEYS, TAX_ANNUAL_BINDINGS,
)
from sheets_factory.workbook.derived_gold.spec import ANCHORS, resolve_spec
from sheets_factory.workbook.derived_gold.validate import ledger_invariants_pass
from sheets_factory.workbook.derived_gold.ledger import simulate
from sheets_factory.workbook.derived_gold.validate import audit_workbook

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def tax_contract(tmp_path):
    config = json.loads((ROOT / "config/derived_advanced_tax_project_v1.json").read_text())
    values = {"revenue": 34124, "ebit": 7040, "da": 1527,
              "tax_rate": .25, "debt_rate": .0509,
              "equity_rate": .09110305231829893, "growth": .04}
    book = openpyxl.Workbook()
    book.remove(book.active)
    for key, (sheet, cell, _) in ANCHORS.items():
        if sheet not in book:
            book.create_sheet(sheet)
        book[sheet][cell] = values[key]
    source = tmp_path / "public_test_anchor_fixture.xlsx"
    book.save(source)
    config["source"]["local_path"] = str(source)
    config["source"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(config))
    return resolve_spec(tmp_path, path), path


def test_public_tax_contract_replaces_old_conflicting_instructions(tax_contract):
    spec, _ = tax_contract
    rules = " ".join(spec["public_rules"])
    assert spec["public_contract_version"] == 7
    assert len(spec["public_rules"]) == 15
    for conflict in ("No NOL expires", "Interest is fully deductible", "No deferred tax assets"):
        assert conflict not in rules
    for required in ("oldest first", "no January write-off", "without monthly proration",
                     "negative means a tax benefit", "no valuation allowance", "without a valuation allowance",
                     "current-year new loss", "positive payment magnitudes", "do not add DTA",
                     "current cash tax only", "separately cent-rounded", "SUM"):
        if required == "no valuation allowance":
            continue  # The exact wording includes the article "a".
        assert required in rules


@pytest.mark.parametrize("patch", [
    {"advanced_tax_enabled": True}, {"advanced_tax_enabled": 2},
    {"nol_carryforward_years": "1.5"}, {"nol_carryforward_years": 0},
    {"initial_tax_rate_y1": ".51"}, {"refresh_tax_rate_y1": "-.1"},
    {"interest_deduction_ebitda_fraction": "1.1"},
    {"interest_deduction_ebitda_fraction": "NaN"},
])
def test_invalid_tax_inputs_fail_before_emitting_a_source(tax_contract, patch):
    _, path = tax_contract
    config = json.loads(path.read_text())
    config["advanced_tax_parameters"].update(patch)
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        resolve_spec(path.parent, path)


@pytest.mark.parametrize("key", ["opening_nol", "opening_retained"])
def test_advanced_tax_rejects_unfunded_opening_tax_attributes(tax_contract, key):
    _, path = tax_contract
    config = json.loads(path.read_text())
    config["hypothetical_parameters"][key] = 1
    if key == "opening_retained":
        config["hypothetical_parameters"]["equity_paid_in"] -= 1
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="zero opening"):
        resolve_spec(path.parent, path)


def _cells(path):
    book = openpyxl.load_workbook(path, data_only=False)
    result = {ws.title: {c.coordinate: (c.value, c.number_format) for c in ws._cells.values()}
              for ws in book}
    book.close()
    return result


def test_disabled_tax_preserves_every_old_formula_label_and_format(tax_contract, tmp_path):
    _, path = tax_contract
    config = json.loads(path.read_text())
    config.pop("advanced_tax_parameters")
    path.write_text(json.dumps(config))
    base = resolve_spec(path.parent, path)
    config["advanced_tax_parameters"] = json.loads((ROOT / "config/derived_advanced_tax_project_v1.json").read_text())["advanced_tax_parameters"]
    config["advanced_tax_parameters"]["advanced_tax_enabled"] = 0
    path.write_text(json.dumps(config))
    disabled = resolve_spec(path.parent, path)
    assert disabled["public_rules"] == base["public_rules"]
    assert disabled["public_contract_version"] == base["public_contract_version"] == 6
    first, second = tmp_path / "base.xlsx", tmp_path / "disabled.xlsx"
    emit_workbook(base, first)
    emit_workbook(disabled, second)
    assert _cells(first) == _cells(second)


def test_advanced_tax_formula_graph_uses_cash_tax_for_cfo_and_book_tax_for_income(tax_contract, tmp_path):
    spec, _ = tax_contract
    path = tmp_path / "tax.xlsx"
    bindings = emit_workbook(spec, path)
    book = openpyxl.load_workbook(path, data_only=False)
    assert len(book.sheetnames) == 14
    assert bindings["tax_parameter_rows"]["advanced_tax_enabled"] == 63
    assert bindings["tax_parameter_rows"]["nol_carryforward_years"] == 71
    assert bindings["covenant_parameter_rows"]["covenant_enabled"] == 55
    assert bindings["payment_row"] == 52
    assert "'Tax'!N7+'Tax'!N10" in book["Operations"]["N13"].value
    assert "'Tax'!N7" in book["Cash Flow"]["N3"].value
    assert "'Operations'!N13" not in book["Cash Flow"]["N3"].value
    assert "+N19" in book["Cash Flow"]["N4"].value
    assert "N21" in book["Balance Sheet"]["N9"].value
    assert "N22" in book["Balance Sheet"]["N14"].value
    assert "21" not in book["Balance Sheet"]["N16"].value
    assert "DTA" not in book["Equity Value"]["B9"].value
    assert book["Tax Vintages"]["C2"].value == 1
    assert book["Tax Vintages"]["E2"].value == 3
    # No inactive branch may introduce a dependency on a future tax event.
    assert "Tax Vintages" not in book["Tax"]["M7"].value
    assert "Tax Vintages" not in book["Tax"]["M10"].value
    assert "Tax Vintages" in book["Tax"]["N7"].value
    assert tuple(bindings["tax_annual"]) == (*TAX_AGGREGATE_KEYS, *TAX_VINTAGE_KEYS)
    assert len(TAX_ANNUAL_BINDINGS) == 52
    # Annual current tax depends on pre-NOL income, not net income or tax expense.
    row = TAX_ANNUAL_BINDINGS["current_tax"]
    assert "Operations" not in book["Tax Vintages"].cell(row, 3).value
    source = (ROOT / "src/sheets_factory/workbook/derived_gold/excel.py").read_text()
    assert "import simulate" not in source and "from .ledger" not in source
    book.close()


def test_independent_ledger_covers_every_formula_but_emission_cannot_self_certify(tax_contract, tmp_path):
    spec, _ = tax_contract
    path = tmp_path / "unrecalculated_advanced_tax.xlsx"
    bindings = emit_workbook(spec, path)
    ledger = simulate(spec)
    result = audit_workbook(path, spec, ledger, bindings)
    assert result["all_formula_cells_independently_covered"]
    assert result["uncovered_formulas"] == []
    assert result["all_ledger_invariants_passed"]
    assert result["formula_count"] > 4800
    assert result["invalid_formula_values"]
    assert not result["passed"]


def test_full_tax_interest_cash_and_covenant_formula_graph_has_no_cycles(tax_contract, tmp_path):
    path = tmp_path / "acyclic.xlsx"
    emit_workbook(tax_contract[0], path)
    book = openpyxl.load_workbook(path, data_only=False)
    graph = {}
    for ws in book:
        for cell in tuple(ws._cells.values()):
            if cell.data_type != "f":
                continue
            dependencies = set()
            for token in Tokenizer(cell.value).items:
                if token.type != "OPERAND" or token.subtype != "RANGE":
                    continue
                value, sheet = token.value, ws.title
                if "!" in value:
                    head, value = value.split("!", 1)
                    sheet = head.strip("'").replace("''", "'")
                    if ":" in value:
                        first, last = value.split(":", 1)
                        value = first + ":" + last.split("!")[-1]
                left, top, right, bottom = range_boundaries(value)
                for row in book[sheet].iter_rows(min_row=top, max_row=bottom, min_col=left, max_col=right):
                    dependencies.update((sheet, target.coordinate) for target in row if target.data_type == "f")
            graph[(ws.title, cell.coordinate)] = dependencies
    # Include all syntactic references, even unused IF branches: the graph must
    # remain a DAG before any evaluator attempts iterative calculation.
    assert len(tuple(TopologicalSorter(graph).static_order())) == len(graph)
    book.close()


def test_each_new_tax_invariant_is_required_for_admission():
    checks = {"feasible": True, "all_balanced": True, "irr_exists": True, "irr_sign_changes": 1,
              "loan_a_payment_residual": Decimal(0), "advanced_tax_enabled": True}
    for key in ("max_balance_error", "max_cfo_reconciliation_error", "max_cash_reconciliation_error",
                "max_income_reconciliation_error", "minimum_cash_gap", "max_journal_error"):
        checks[key] = Decimal(0)
    keys = ("tax_vintage_rollforwards_ok", "tax_interest_capacity_ok", "tax_nol_fifo_ok",
            "tax_interest_fifo_ok", "tax_bridge_ok", "tax_depreciation_basis_ok")
    checks.update({key: True for key in keys})
    assert ledger_invariants_pass(checks)
    for key in keys:
        bad = deepcopy(checks)
        bad[key] = False
        assert not ledger_invariants_pass(bad)
        bad.pop(key)
        assert not ledger_invariants_pass(bad)
