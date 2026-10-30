"""Compare the calculated workbook with the independent financial journal."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext
import math
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter as L


def posted_money_matches(observed: Decimal, expected: Decimal) -> bool:
    """A float residue may not change the contract's half-up posted cent."""
    cent = Decimal(".01")
    return (observed.is_finite() and expected.is_finite()
            and abs(observed - expected) < Decimal(".005")
            and observed.quantize(cent, rounding=ROUND_HALF_UP)
            == expected.quantize(cent, rounding=ROUND_HALF_UP))


def ledger_invariants_pass(checks: dict) -> bool:
    """A balanced BS alone cannot certify cash, tax or event bookkeeping."""
    zero_keys = ("max_balance_error", "max_cfo_reconciliation_error",
                 "max_cash_reconciliation_error", "max_income_reconciliation_error",
                 "minimum_cash_gap", "max_journal_error")
    try:
        return (checks["feasible"] is True and checks["all_balanced"] is True
                and all(Decimal(str(checks[key])) == 0 for key in zero_keys)
                and abs(Decimal(str(checks["loan_a_payment_residual"]))) < Decimal("1e-30")
                and checks["irr_exists"] is True and checks["irr_sign_changes"] == 1)
    except (KeyError, ArithmeticError, ValueError, TypeError):
        return False


def audit_workbook(path: Path, spec: dict, ledger: dict, bindings: dict) -> dict:
    book = openpyxl.load_workbook(path, data_only=True, keep_links=False)
    formulas = openpyxl.load_workbook(path, data_only=False, keep_links=False)
    expected = {}
    kinds = {}
    p = spec["parameters"]
    dec = lambda value: Decimal(str(value))
    def add(sheet, cell, value, kind="money"):
        key = sheet + "!" + cell
        if key in expected and expected[key] != value:
            raise AssertionError("Conflicting independent bindings: " + key)
        expected[key], kinds[key] = value, kind

    for i, row in enumerate(ledger["monthly"]):
        c = L(i + 3)
        for key, binding in bindings["monthly"].items():
            add(binding["sheet"], c + str(binding["row"]), row[key], "date" if key == "date" else "integer" if key in {"year", "period", "month_days"} else "money")
        d = date.fromisoformat(row["date"])
        for sheet in bindings["monthly"].values():
            if sheet["sheet"] != "Calendar":
                add(sheet["sheet"], c + "1", row["date"], "date")
        add("Calendar", c + "6", d.month, "integer")
        add("Calendar", c + "7", int((i + 1) % 12 == 0), "integer")
        j = i + 1 - int(p["construction_months"])
        ramp = 0 if j <= 0 else p["ramp_factors"][j - 1] if j <= len(p["ramp_factors"]) else 1
        add("Calendar", c + "8", ramp, "ratio")
        for rr, key in [(3, "depreciation_initial"), (4, "depreciation_refresh"), (5, "depreciation")]:
            add("Assets", c + str(rr), row[key])
        add("Debt", c + "16", row["interest"])
        add("Debt", c + "17", ledger["valuation"]["loan_a_payment"])
        add("Tax", c + "2", sum(r["ebt"] for r in ledger["monthly"][(i // 12) * 12:i + 1]))
        add("Tax", c + "7", row["tax"])
        add("Cash Flow", c + "6", row["loan_a_scheduled_principal"])
        add("Cash Flow", c + "7", row["loan_b_principal"])
        add("Cash Flow", c + "13", max(Decimal(0), row["cash_before_allocation"] + row["revolver_draw"] - row["revolver_repayment"] - dec(p["minimum_cash"])))
        add("Cash Flow", c + "14", int(i + 1 >= int(p["cash_allocation_start"])), "integer")
        add("Cash Flow", c + "15", row["cash_open"] + row["cfo_direct"] + row["cfi"] + row["cff"] - row["cash_close"])
        for rr, key in [(2, "cash_close"), (3, "ar_close"), (4, "inventory_close"), (5, "asset_initial_gross"), (6, "asset_refresh_gross"), (7, "accumulated_depreciation"), (8, "net_ppe"), (10, "ap_close"), (11, "loan_a_close"), (12, "loan_b_close"), (13, "revolver_close")]:
            add("Balance Sheet", c + str(rr), row[key])
        add("Balance Sheet", c + "17", dec(p["equity_paid_in"]))
        add("Equity Value", c + "15", row["date"], "date")
        add("Equity Value", c + "17", row["dividend"])
        with localcontext() as ctx:
            ctx.prec = 60
            pv = row["owner_cashflow"] / (1 + ledger["valuation"]["monthly_discount_rate"]) ** (i + 1)
        add("Equity Value", c + "18", pv.quantize(Decimal(".01"), rounding=ROUND_HALF_UP))

    for i, row in enumerate(ledger["annual"]):
        c = L(i + 3)
        add("Annual Statements", c + "2", row["year"], "integer")
        add("Annual Statements", c + "3", row["periods"], "integer")
        add("Annual Statements", c + "4", row["start_date"], "date")
        add("Annual Statements", c + "5", row["end_date"], "date")
        for key, rr in bindings["annual"].items():
            add("Annual Statements", c + str(rr), row[key])
    for key, address in bindings["valuation"].items():
        add("Equity Value", address, ledger["valuation"][key], "ratio" if "rate" in key or "irr" in key else "money")
    add("Equity Value", "B16", -dec(p["equity_paid_in"]))
    for key, rr in bindings["source_anchor_rows"].items():
        add("Source Inputs", "B" + str(rr), spec["source_lineage"]["anchors"][key]["value"], "ratio" if "rate" in key or key == "growth" else "source_number")
    add("Source Inputs", "B10", p["cash_ebitda_margin"], "ratio")
    flattened = {}
    for key, value in p.items():
        if isinstance(value, list):
            flattened.update({f"ramp_{j}": item for j, item in enumerate(value, 1)})
        else:
            flattened[key] = value
    for key, rr in bindings["parameter_rows"].items():
        value = flattened[key]
        kind = "date" if key == "start_date" else "ratio" if any(token in key for token in ("rate", "fraction", "margin", "spread", "premium", "growth", "cap", "ramp_", "multiple")) else "source_number"
        add("Scenario", "B" + str(rr), value, kind)
    add("Scenario", "B" + str(bindings["payment_row"]), ledger["valuation"]["loan_a_payment"])

    checks, failed = [], []
    for address, want in sorted(expected.items()):
        sheet, cell = address.rsplit("!", 1)
        got = book[sheet][cell].value
        kind = kinds[address]
        error = None
        try:
            if kind == "date":
                observed = got.date().isoformat() if isinstance(got, datetime) else got.isoformat() if isinstance(got, date) else str(got)
                passed = observed == str(want)
            else:
                if isinstance(got, bool) or not isinstance(got, (int, float)) or not math.isfinite(got):
                    raise ValueError("Calculated value is not finite numeric")
                error = abs(dec(got) - dec(want))
                if kind in {"money", "source_number"}:
                    passed = posted_money_matches(dec(got), dec(want))
                else:
                    tolerance = Decimal("0.0000000001") if kind == "ratio" else Decimal("0.000001")
                    passed = error <= tolerance
        except (ValueError, TypeError, ArithmeticError):
            passed = False
        item = {"address": address, "expected_independent": str(want), "observed": str(got),
                "kind": kind, "absolute_error": str(error) if error is not None else None, "passed": passed}
        checks.append(item)
        if not passed:
            failed.append(item)
    uncovered, invalid = [], []
    formula_count = 0
    for ws in formulas:
        for cell in ws._cells.values():
            if cell.data_type != "f":
                continue
            formula_count += 1
            address = ws.title + "!" + cell.coordinate
            if address not in expected:
                uncovered.append(address)
            cached = book[ws.title][cell.coordinate]
            if cached.value is None or cached.data_type == "e":
                invalid.append({"address": address, "value": cached.value})
    invariant_passed = ledger_invariants_pass(ledger["checks"])
    passed = not failed and not uncovered and not invalid and invariant_passed
    book.close()
    formulas.close()
    return {"passed": bool(passed), "checked_cells": len(checks), "formula_count": formula_count,
            "all_formula_cells_independently_covered": not uncovered, "uncovered_formulas": uncovered,
            "invalid_formula_values": invalid, "mismatches": failed, "cell_checks": checks,
            "all_ledger_invariants_passed": invariant_passed,
            "independent_ledger_checks": ledger["checks"],
            "qualification": "Financial seed validation only. No constructed task, quality gate or difficulty result is implied."}
