"""Offline financial-contract tests; the integration check uses real LO separately."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import openpyxl
import pytest

from sheets_factory.workbook.derived_gold.excel import emit_workbook
from sheets_factory.workbook.derived_gold.ledger import simulate
from sheets_factory.workbook.derived_gold.spec import ANCHORS, resolve_spec
from sheets_factory.workbook.derived_gold.validate import audit_workbook, ledger_invariants_pass, posted_money_matches


ROOT = Path(__file__).resolve().parents[1]
D = Decimal


@pytest.mark.parametrize("observed,expected,passed", [
    ("1.005", "1.00", False), ("1.005000001", "1.00", False),
    ("1.004999999", "1.00", True), ("-1.005", "-1.00", False),
    ("-1.005000001", "-1.00", False), ("1.005", "1.01", False),
    ("55391.7499999996", "55391.75", True),
    ("-55391.7500000004", "-55391.75", True),
    ("55391.7499999996", "55391.74", False),
    ("NaN", "1.00", False), ("Infinity", "1.00", False),
])
def test_posted_cent_requires_identical_half_up_rounding(observed, expected, passed):
    assert posted_money_matches(D(observed), D(expected)) is passed


@pytest.fixture
def contract(tmp_path):
    """Public anchor fixture, not a claim that this synthetic file is the source."""
    config = json.loads((ROOT / "config/derived_gold_project_v1.json").read_text())
    values = {"revenue": 34124, "ebit": 7040, "da": 1527,
              "tax_rate": .25, "debt_rate": .0509,
              "equity_rate": .09110305231829893, "growth": .04}
    book = openpyxl.Workbook()
    book.remove(book.active)
    for key, (sheet, cell, _) in ANCHORS.items():
        if sheet not in book:
            book.create_sheet(sheet)
        book[sheet][cell] = values[key]
    source = tmp_path / "explicit_test_anchor_fixture.xlsx"
    book.save(source)
    config["source"]["local_path"] = str(source)
    config["source"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(config))
    return resolve_spec(tmp_path, path), path


def test_lineage_hash_is_checked_before_using_source(contract, tmp_path):
    _, path = contract
    config = json.loads(path.read_text())
    config["source"]["sha256"] = "0" * 64
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="Source SHA256"):
        resolve_spec(tmp_path, path)


def test_public_benchmarks_and_hypothetical_contract(contract):
    spec, _ = contract
    p = spec["parameters"]
    assert D(p["cash_ebitda_margin"]) == D(".251054975970")
    assert D(p["loan_a_annual_rate"]) == D(".0609")
    assert D(p["annual_equity_discount_rate"]) == D(".121103052318")
    assert all("sheet" in a and "cell" in a for a in spec["source_lineage"]["anchors"].values())
    rules = " ".join(spec["public_rules"]).lower()
    for term in ("hypothetical", "half up", "actual calendar days", "nol", "minimum cash", "share", "no deferred tax", "no additional"):
        assert term in rules


def test_first_month_hand_calculation_and_precommissioning_policy(contract):
    result = simulate(contract[0])
    first = result["monthly"][0]
    # No revenue or working capital. Only startup expense and two cash interests.
    assert first["loan_a_interest"] == D("60900.00")
    assert first["loan_b_interest"] == D("20225.00")
    assert first["startup_expense"] == D("333333.33")
    assert first["ebt"] == D("-414458.33")
    assert first["cash_close"] == D("2585541.67")
    assert all(r["dividend"] == r["loan_a_extra_principal"] == 0 for r in result["monthly"][:6])
    assert sum(r["startup_expense"] for r in result["monthly"]) == D("2000000")
    assert result["monthly"][5]["startup_expense"] == D("333333.35")


def test_vintage_cash_and_depreciation_timing_are_distinct(contract):
    monthly = simulate(contract[0])["monthly"]
    assert sum(r["capex"] for r in monthly) == D("1000000")  # initial funded at time zero
    assert monthly[18]["capex"] == D("1000000")
    assert monthly[18]["depreciation_refresh"] == 0
    assert monthly[19]["depreciation_refresh"] == D("41666.67")
    assert all(r["depreciation_initial"] == 0 for r in monthly[:6])
    assert monthly[6]["depreciation_initial"] == D("238095.24")


def test_annual_tax_and_nol_are_not_monthly_tax_on_positive_months(contract):
    result = simulate(contract[0])
    monthly = result["monthly"]
    assert monthly[11]["nol_close"] == D("1420166.98")
    for i, row in enumerate(monthly, 1):
        if i % 12:
            assert row["tax"] == row["nol_use"] == row["nol_add"] == 0
            assert row["nol_close"] == row["nol_open"]
        else:
            annual_ebt = sum(r["ebt"] for r in monthly[i - 12:i])
            assert row["nol_use"] <= max(annual_ebt, 0) * D(".8") + D(".005")
            assert row["nol_close"] == row["nol_open"] + row["nol_add"] - row["nol_use"]
    assert monthly[23]["tax"] == D("615578.99")
    assert monthly[35]["tax"] == D("1045822.30")


def test_full_cash_debt_accounting_identities_and_bullet(contract):
    result = simulate(contract[0])
    for row in result["monthly"]:
        assert row["assets"] == row["liabilities"] + row["equity"]
        assert row["cfo_direct"] == row["cfo_indirect"]
        assert row["cash_close"] == row["cash_open"] + row["cfo_direct"] + row["cfi"] + row["cff"]
        assert row["loan_a_close"] == row["loan_a_open"] - row["loan_a_scheduled_principal"] - row["loan_a_extra_principal"]
        assert row["revolver_close"] == row["revolver_open"] + row["revolver_draw"] - row["revolver_repayment"]
        assert row["cash_close"] >= D("500000")
    assert all(row["loan_b_principal"] == 0 for row in result["monthly"][:35])
    assert result["monthly"][35]["loan_b_principal"] == D("3000000")
    assert result["checks"]["max_journal_error"] == 0
    assert sum(result["opening_trial_balance"].values()) == 0
    assert len(result["journal"]) == 439
    assert all(sum(entry["debit_positive_entries"].values()) == 0 for entry in result["journal"])


@pytest.mark.parametrize("key", ["max_cfo_reconciliation_error", "max_cash_reconciliation_error",
                                  "max_journal_error", "minimum_cash_gap"])
def test_balanced_balance_sheet_cannot_hide_other_invariant_failure(contract, key):
    checks = simulate(contract[0])["checks"]
    assert ledger_invariants_pass(checks)
    checks[key] = D(".01")
    assert checks["all_balanced"]
    assert not ledger_invariants_pass(checks)


def test_exhausted_revolver_fails_instead_of_balancing_plug(contract):
    spec = deepcopy(contract[0])
    spec["parameters"]["revolver_limit"] = 0
    with pytest.raises(ValueError, match="(?i)(funding|liquidity).*7"):
        simulate(spec)


def test_zero_rate_payment_and_asset_basis_cap(contract):
    spec = deepcopy(contract[0])
    spec["parameters"]["loan_a_annual_rate"] = "0"
    spec["parameters"]["initial_asset_life"] = 1
    result = simulate(spec)
    assert result["valuation"]["loan_a_payment"] == D("200000")
    assert result["monthly"][6]["depreciation_initial"] == D("20000000")
    assert sum(row["depreciation_initial"] for row in result["monthly"]) == D("20000000")
    assert all(row["net_ppe"] >= 0 for row in result["monthly"])


def test_exit_proceeds_remain_outside_entity_books(contract):
    result = simulate(contract[0])
    valuation, last = result["valuation"], result["monthly"][-1]
    assert valuation["equity_exit"] == D("27074301.69")
    assert last["owner_cashflow"] == last["dividend"] + valuation["equity_exit"]
    assert last["cash_close"] == D("500000")
    assert valuation["equity_npv"] == D("13410828.42")
    assert abs(valuation["annual_equity_irr"] - D(".5709221098253903")) < D("1e-15")


def test_formula_emitter_and_unrecalculated_book_cannot_self_certify(contract, tmp_path):
    spec, _ = contract
    path = tmp_path / "unrecalculated.xlsx"
    bindings = emit_workbook(spec, path)
    book = openpyxl.load_workbook(path, data_only=False)
    assert len(book.sheetnames) == 12
    # Retained earnings is income less dividends, never assets minus liabilities.
    assert "'Operations'!C14" in book["Balance Sheet"]["C16"].value
    assert "'Cash Flow'!C10" in book["Balance Sheet"]["C16"].value
    assert "C9" not in book["Balance Sheet"]["C16"].value
    assert "PMT(" in book["Scenario"].cell(bindings["payment_row"], 2).value
    assert "IRR(" in book["Equity Value"]["B11"].value
    assert "ROUND(" in book["Cash Flow"]["S13"].value
    audit = audit_workbook(path, spec, simulate(spec), bindings)
    assert not audit["passed"]
    assert audit["invalid_formula_values"]
    assert audit["all_formula_cells_independently_covered"]
    assert "from .ledger" not in (ROOT / "src/sheets_factory/workbook/derived_gold/excel.py").read_text()
