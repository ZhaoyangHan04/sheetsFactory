"""Resolve documented public source anchors and explicit hypothetical inputs.

This module contains data extraction and contract validation only. Financial
forecast calculations belong to the separately implemented emitter and ledger.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import json
from pathlib import Path

import openpyxl


ANCHORS = {
    "revenue": ("Master Inputs Start here", "B18", "Current Revenues"),
    "ebit": ("Master Inputs Start here", "B12", "Current Operating Income"),
    "da": ("Master Inputs Start here", "B15", "Current Depreciation and Amortization"),
    "tax_rate": ("Master Inputs Start here", "B17", "Marginal tax rate benchmark"),
    "debt_rate": ("Master Inputs Start here", "B46", "Borrowing rate benchmark"),
    "equity_rate": ("Valuation Model", "D27", "Calculated cost of equity benchmark"),
    "growth": ("Master Inputs Start here", "B78", "Stable growth benchmark"),
}

RULES = [
    "This is a hypothetical project calibrated to a public workbook's cash EBITDA margin and rate benchmarks; it is not a forecast of that workbook's named company.",
    "All project money is nominal USD. Source company financial units are used only in dimensionless ratios. Derived benchmark ratios and rates are rounded to 12 decimal places; posted money is rounded half up to cents.",
    "The project begins on January 1. The initial equipment and opening cash are funded before month 1 by the two initial loans and paid-in equity; do not charge the initial equipment a second time in forecast cash flow.",
    "Annualized steady sales grow each calendar year. Divide by 12 and apply the public monthly commissioning ramp. Before commissioning sales are zero. Cash COGS and other operating expense use their stated ratios; additional startup expenses are spread across the construction months, with the last month receiving the cent residual.",
    "Receivables equal current monthly sales divided by that month's actual calendar days times DSO. Inventory and payables similarly use monthly cash COGS and DIO/DPO. Opening receivables, inventory and payables are zero.",
    "Each equipment vintage receives a full month of straight-line depreciation from its stated service month, capped at its cost. The initial asset includes construction in progress before service. The refresh asset is paid in its payment month and depreciated only from its service month.",
    "Interest uses each facility's opening monthly balance times its nominal annual rate divided by 12 and is paid in cash once. A same-month end draw starts accruing interest next month.",
    "Loan A pays interest only before its amortization start. Its original level payment is based on the original principal and stated number of amortizing payments, rounded to cents. Early principal repayments shorten the term without re-amortizing. Scheduled principal cannot exceed opening principal, and the last payment is capped at principal plus interest.",
    "Loan B pays monthly interest and its entire remaining principal in the stated bullet month. The revolving facility has a finite limit. Its draws and repayments occur at month end.",
    "Tax is recognized and paid only at each calendar year end, using that year's total pretax income. Losses add to NOL; positive annual income can use opening NOL only up to the stated fraction. No NOL expires within the horizon. Interest is fully deductible. No deferred tax assets or liabilities are recognized in this simplified scenario; these are hypothetical rules, not a claim about current tax law.",
    "After operations, cash interest, tax, refresh capex and scheduled principal, draw the revolver only to maintain minimum cash, subject to its limit. Repay the revolver from excess cash before optional Loan A prepayment. Optional prepayment and distributions begin only in the public allocation-start month. Prepay the stated sweep fraction of remaining excess, capped at remaining Loan A principal, and distribute all other excess. Unused sweep after Loan A is repaid is also distributed.",
    "Operating cash flow includes cash interest once; financing cash flow includes loan principal only, not the full level payment again. Retained earnings roll forward as prior retained earnings plus net income less dividends; never force the balance sheet to balance with a plug.",
    "At the horizon the owners sell their shares. Enterprise value equals next year's steady EBITDA times the stated multiple. Seller proceeds add closing cash, subtract all closing debt and seller fees. Do not add a separate liquidation of working capital or equipment. Share-sale proceeds are owner cash flow outside the entity's accounts.",
    "Owner cash flow starts with negative paid-in equity, then monthly dividends and the final share-sale proceeds. The annual discount rate is effective; monthly rate is (1+annual rate)^(1/12)-1. Use periodic monthly IRR and annualize it as (1+monthly IRR)^12-1.",
    "No additional inflation, foreign exchange, financing fees, interest capitalization, debt penalties, new equity injections or unlisted cash sources are assumed.",
]


def _decimal(value) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a financial number")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Scenario numbers must be finite")
    return result


def validate_parameters(p: dict) -> None:
    if p["months"] != 36 or date.fromisoformat(p["start_date"]).month != 1 or date.fromisoformat(p["start_date"]).day != 1:
        raise ValueError("Prototype requires 36 months starting January 1")
    if len(p["ramp_factors"]) != 6:
        raise ValueError("Prototype requires six explicit commissioning ramp factors")
    for key, value in p.items():
        if key == "start_date":
            continue
        if isinstance(value, list):
            for item in value:
                _decimal(item)
        else:
            _decimal(value)
    for key in ("loan_a_annual_rate", "loan_b_annual_rate", "revolver_annual_rate", "tax_rate", "nol_utilization_cap", "cash_sweep_fraction", "cash_cogs_fraction"):
        if not 0 <= _decimal(p[key]) <= 1:
            raise ValueError(f"Out-of-range rate or fraction: {key}")
    if not 0 < _decimal(p["cash_ebitda_margin"]) < 1 - _decimal(p["cash_cogs_fraction"]):
        raise ValueError("Cash EBITDA margin leaves negative other operating expense")
    if _decimal(p["annual_equity_discount_rate"]) <= -1:
        raise ValueError("Effective discount rate must exceed -1")
    for key in ("initial_asset_life", "refresh_life", "loan_a_amort_payments"):
        if int(p[key]) < 1:
            raise ValueError(f"Positive period count required: {key}")
    for key in ("steady_annual_sales", "initial_asset_cost", "opening_cash", "equity_paid_in", "revolver_limit", "minimum_cash"):
        if _decimal(p[key]) < 0:
            raise ValueError(f"Negative funding or asset input: {key}")
    funding = _decimal(p["equity_paid_in"]) + _decimal(p["opening_retained"]) + _decimal(p["loan_a_principal"]) + _decimal(p["loan_b_principal"])
    assets = _decimal(p["initial_asset_cost"]) + _decimal(p["opening_cash"])
    if funding != assets:
        raise ValueError("Initial balance sheet does not balance without a plug")


def resolve_spec(project_root: Path, config_path: Path) -> dict:
    config = json.loads(config_path.read_text())
    source = Path(config["source"]["local_path"])
    if not source.is_absolute():
        source = project_root / source
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != config["source"]["sha256"]:
        raise ValueError("Source SHA256 differs from the declared lineage")
    book = openpyxl.load_workbook(source, data_only=True, keep_links=False)
    anchors = {}
    for name, (sheet, cell, label) in ANCHORS.items():
        value = _decimal(book[sheet][cell].value)
        anchors[name] = {"sheet": sheet, "cell": cell, "label": label, "value": str(value)}
    book.close()
    p = dict(config["hypothetical_parameters"])
    precision = Decimal("0.000000000001")
    with localcontext() as ctx:
        ctx.prec = 60
        p["cash_ebitda_margin"] = str(((_decimal(anchors["ebit"]["value"]) + _decimal(anchors["da"]["value"])) / _decimal(anchors["revenue"]["value"])).quantize(precision, rounding=ROUND_HALF_UP))
        p["annual_sales_growth"] = anchors["growth"]["value"]
        p["tax_rate"] = anchors["tax_rate"]["value"]
        for facility in ("loan_a", "loan_b", "revolver"):
            p[facility + "_annual_rate"] = str((_decimal(anchors["debt_rate"]["value"]) + _decimal(p[facility + "_spread"])).quantize(precision, rounding=ROUND_HALF_UP))
        p["annual_equity_discount_rate"] = str((_decimal(anchors["equity_rate"]["value"]) + _decimal(p["equity_risk_premium"])).quantize(precision, rounding=ROUND_HALF_UP))
    validate_parameters(p)
    return {
        "schema_version": 1, "scenario_id": config["scenario_id"],
        "title": "Hypothetical project: commissioning, financing and equity returns",
        "status": "experimental_seed_not_a_qualified_task",
        "source_lineage": {"source_url": config["source"]["source_url"],
                           "download_url": config["source"]["download_url"],
                           "sha256": digest, "anchors": anchors,
                           "derivation": "Cash EBITDA margin = (unadjusted operating income + D&A) / revenue; reused as a hypothetical project benchmark, not as company-specific future facts."},
        "parameters": p, "public_rules": RULES,
        "qualification": "No task or difficulty qualification. Every future task must pass all existing quality, recovery, Harbor and specified strong-agent difficulty gates.",
    }
