"""Offline financial-contract tests; the integration check uses real LO separately."""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import json
from pathlib import Path

import openpyxl
import pytest

from sheets_factory.workbook.derived_gold.excel import emit_workbook
from sheets_factory.workbook.derived_gold.ledger import simulate, _Book, _covenant_state, _covenant_test, _reserve_waterfall
from sheets_factory.workbook.derived_gold.spec import ANCHORS, RULES, resolve_spec
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


def test_public_cash_helpers_define_their_position_in_the_waterfall(contract):
    # Keep all definitions in one existing rule so worksheet row placement is stable.
    assert len(RULES) == 15
    rule = next(rule for rule in contract[0]["public_rules"] if "Cash before allocation" in rule)
    assert "before any revolver draw, revolver repayment, optional Loan A prepayment or dividend" in rule
    assert "remaining unmet minimum-cash shortfall after the permitted draw" in rule
    assert "not the funding requirement before that draw" in rule
    assert "above minimum cash after revolver repayment, before optional prepayment and dividends" in rule
    # This specifies business semantics, not target coordinates or a numerical answer.
    assert "Cash Flow!" not in rule and "500000" not in rule


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


def test_public_contract_resolves_fee_base_and_npv_rounding(contract):
    spec = contract[0]
    result = simulate(spec)
    valuation, closing = result["valuation"], result["monthly"][-1]
    cent = lambda value: value.quantize(D(".01"), rounding=ROUND_HALF_UP)
    gross_equity = (valuation["enterprise_value"] + closing["cash_close"]
                    - closing["loan_a_close"] - closing["loan_b_close"] - closing["revolver_close"])
    alternative_fee = cent(gross_equity * D(spec["parameters"]["exit_fee_fraction"]))
    assert valuation["exit_fee"] != alternative_fee
    assert valuation["equity_exit"] != gross_equity - alternative_fee
    with localcontext() as context:
        context.prec = 60
        flows, rate = valuation["owner_cashflows"], valuation["monthly_discount_rate"]
        displayed_pv_sum = sum((cent(flow / (1 + rate) ** t) for t, flow in enumerate(flows)), D(0))
    assert valuation["equity_npv"] == D("13410828.42")
    assert displayed_pv_sum == D("13410828.41")
    rules = " ".join(spec["public_rules"])
    assert spec["public_contract_version"] >= 4
    assert "fee base is enterprise value" in rules
    assert "do not sum that rounded display row" in rules
    assert "helper rows are positive payment magnitudes" in rules
    assert "delta is closing balance minus opening balance" in rules


def test_public_contract_resolves_depreciation_and_annual_snapshot(contract):
    spec = contract[0]
    result = simulate(spec)
    # Rounding cumulative exact straight-line amounts gives a different third
    # charge. The contract explicitly selects a fixed cent charge, then a cap.
    exact_charge = D(spec["parameters"]["initial_asset_cost"]) / D(spec["parameters"]["initial_asset_life"])
    cent = lambda value: value.quantize(D(".01"), rounding=ROUND_HALF_UP)
    assert result["monthly"][8]["depreciation_initial"] == D("238095.24")
    assert cent(3 * exact_charge) - cent(2 * exact_charge) == D("238095.23")
    first_year = result["monthly"][:12]
    annual = result["annual"][0]
    assert annual["cash_before_allocation"] == first_year[-1]["cash_before_allocation"]
    assert annual["cash_before_allocation"] != sum(row["cash_before_allocation"] for row in first_year)
    assert annual["owner_cashflow"] == sum(row["owner_cashflow"] for row in first_year)
    rules = " ".join(spec["public_rules"])
    assert "fixed monthly charge" in rules
    assert "December pre-allocation snapshot" in rules


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


def _enable_covenant(spec):
    result = deepcopy(spec)
    result["covenant_parameters"] = {
        "covenant_enabled": 1, "covenant_first_test_month": 9,
        "covenant_dscr_threshold": "1.30", "dsra_normal_payment_months": 1,
        "dsra_trap_payment_months": 3,
    }
    return result


def test_opt_in_disabled_preserves_the_complete_original_ledger(contract):
    base = simulate(contract[0])
    disabled = _enable_covenant(contract[0])
    disabled["covenant_parameters"]["covenant_enabled"] = 0
    assert simulate(disabled) == base


def test_enabled_contract_is_public_and_preserves_old_scenario_addresses(contract, tmp_path):
    _, path = contract
    config = json.loads(path.read_text())
    config["covenant_parameters"] = _enable_covenant(contract[0])["covenant_parameters"]
    path.write_text(json.dumps(config))
    spec = resolve_spec(path.parent, path)
    assert spec["public_contract_version"] == 6
    assert len(spec["public_rules"]) == 15
    rules = " ".join(spec["public_rules"])
    for wording in ("second consecutive passed test", "this same month-end", "after DSRA transfers",
                    "internal transfers", "quarter service", "before optional principal",
                    "seller", "at par", "not the reserve shortfall",
                    "Do not carry the prior test-passed flag", "including non-test months",
                    "not a distribution-permission flag"):
        assert wording.lower() in rules.lower()
    bindings = emit_workbook(spec, tmp_path / "enabled.xlsx")
    book = openpyxl.load_workbook(tmp_path / "enabled.xlsx")
    assert bindings["payment_row"] == 52
    assert bindings["parameter_rows"]["cash_ebitda_margin"] == 44
    assert bindings["covenant_parameter_rows"]["covenant_enabled"] == 55
    assert bindings["covenant_parameter_rows"]["dsra_trap_payment_months"] == 59
    assert len(book.sheetnames) == 13
    assert "'Covenants'!" in book["Equity Value"]["B9"].value
    audit = audit_workbook(tmp_path / "enabled.xlsx", spec, simulate(spec), bindings)
    assert audit["all_formula_cells_independently_covered"]
    assert not audit["passed"]  # Formula emission alone cannot self-certify values.


@pytest.mark.parametrize("patch", [
    {"covenant_first_test_month": 8}, {"covenant_first_test_month": 39},
    {"covenant_enabled": True}, {"covenant_enabled": 2},
    {"dsra_normal_payment_months": 4}, {"dsra_trap_payment_months": "2.5"},
    {"covenant_dscr_threshold": "NaN"}, {"covenant_dscr_threshold": -1},
])
def test_invalid_covenant_inputs_rejected_by_both_paths(contract, patch):
    spec, path = contract
    config = json.loads(path.read_text())
    cov = _enable_covenant(spec)["covenant_parameters"]
    cov.update(patch)
    config["covenant_parameters"] = cov
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        resolve_spec(path.parent, path)
    bad = deepcopy(spec)
    bad["covenant_parameters"] = cov
    with pytest.raises(ValueError):
        simulate(bad)


def test_covenant_state_requires_two_passes_and_failure_resets_the_cure():
    lock = passes = 0
    states = []
    for passed in (False, True, False, True, True):
        lock, passes = _covenant_state(lock, passes, True, passed)
        states.append((lock, passes))
        assert _covenant_state(lock, passes, False, False) == (lock, passes)
    assert states == [(1, 0), (1, 1), (1, 0), (1, 1), (0, 2)]


@pytest.mark.parametrize("cfads,service,threshold,want_requirement,passed", [
    ("130.00", "100", "1.3", "130.00", True),
    ("129.99", "100", "1.3", "130.00", False),
    ("-1", "100", "1.3", "130.00", False),
    ("-1", "0", "1.3", "0.00", True),
    ("1.01", "1", "1.005", "1.01", True),
    ("1.00", "1", "1.005", "1.01", False),
])
def test_covenant_comparison_uses_posted_requirement_not_display_ratio(cfads, service, threshold, want_requirement, passed):
    assert _covenant_test(D(cfads), D(service), D(threshold)) == (D(want_requirement), passed)


def test_reserve_support_then_funding_are_internal_cash_transfers():
    book = _Book({"cash": D("40"), "dsra_cash": D("80"), "retained": D("-120")})
    support = _reserve_waterfall(book, 1, target=D("80"), minimum=D("100"), service=D("100"),
                                 revolver_open=D(0), revolver_limit=D("200"), loan_a_remaining=D(0),
                                 sweep=D(".5"), allocation_allowed=True, locked=1)
    assert support["dsra_support"] == D("60")
    assert support["dsra_shortfall"] == D("60")
    assert book.get("cash") == D("100") and book.get("dsra_cash") == D("20")
    assert book.cash_flow(1, "cash_transfer") == D("60")
    assert book.cash_flow(1, "financing") == book.cash_flow(1, "operating") == 0
    # Separate hand-posted month: funding takes priority over revolving repayment.
    book = _Book({"cash": D("260"), "dsra_cash": D("20"), "revolver": D("-20"),
                  "loan_a": D("-300"), "retained": D("40")})
    funding = _reserve_waterfall(book, 2, target=D("80"), minimum=D("100"), service=D("100"),
                                 revolver_open=D("20"), revolver_limit=D("200"), loan_a_remaining=D("300"),
                                 sweep=D(".5"), allocation_allowed=True, locked=1)
    assert funding["dsra_funding"] == D("60") and funding["revolver_repayment"] == D("20")
    assert funding["loan_a_extra_principal"] == D("40") and funding["dividend"] == 0
    assert book.get("cash") == D("140") and book.get("dsra_cash") == D("80")
    assert book.cash_flow(2, "cash_transfer") == book.cash_flow(2, "financing") == D("-60")
    assert sum(book.accounts.values()) == 0


def test_enabled_covenant_real_regimes_and_three_cash_identities(contract):
    result = simulate(_enable_covenant(contract[0]))
    rows = result["monthly"]
    assert (rows[8]["lock_close"], rows[11]["lock_close"], rows[14]["lock_close"]) == (1, 1, 0)
    assert rows[11]["test_passed"] == 1 and rows[11]["dividend"] == 0
    # Favorable interim coverage is not an actual passed quarterly test.
    interim = rows[12]
    assert interim["quarter_cfads"] == D("525323.58")
    assert interim["required_cfads"] == D("352360.48")
    assert interim["dscr_display"] == D("1.938131")
    assert interim["test_due"] == interim["test_passed"] == 0
    assert rows[0]["required_cfads"] == D("105462.50")
    assert rows[0]["dscr_display"] == D("-4.108885")
    assert any(r["dividend"] > 0 for r in rows[:-1])
    for key in ("dsra_funding", "dsra_support", "dsra_release"):
        assert sum(r[key] for r in rows) > 0
    for r in rows:
        assert r["cash_close"] == r["cash_open"] + r["cfo_direct"] + r["cfi"] + r["cff"] + r["dsra_net_transfer"]
        assert r["dsra_close"] == r["dsra_open"] - r["dsra_net_transfer"]
        assert r["total_cash_close"] == r["cash_open"] + r["dsra_open"] + r["cfo_direct"] + r["cfi"] + r["cff"]
        assert r["assets"] == r["liabilities"] + r["equity"]
        assert not r["dividend"] or (not r["lock_close"] and not r["dsra_shortfall"])
    assert ledger_invariants_pass(result["checks"])
    for key in ("max_total_cash_reconciliation_error", "max_reserve_reconciliation_error", "max_transfer_reconciliation_error"):
        bad = deepcopy(result["checks"])
        bad[key] = D(".01")
        assert not ledger_invariants_pass(bad)
