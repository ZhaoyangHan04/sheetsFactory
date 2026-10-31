"""Public synthetic business assumptions; no workbook or masked-cell recipe."""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import re

KIND = "synthetic_operating_metrics_regime_business_spec"
NA = "n/a (no comparative)"
YEARS = (2025, 2026, 2027)
FLOW_FIELDS = ("revenue", "direct_cost", "operating_expense", "operating_profit",
    "interest", "pretax_before_associate", "current_tax", "core_net_income",
    "associate_income", "net_income", "dividend", "operating_cash_flow")
STOCK_FIELDS = ("closing_cash", "closing_investment", "closing_retained_earnings",
    "debt", "contributed_capital", "total_assets", "total_liabilities_equity")
QUARTER_METRICS = ("net_margin_percent", "yoy_percent", "qoq_percent",
    "prior_year_multiple", "prior_year_index")
ANNUAL_METRICS = ("net_margin_percent", "yoy_percent", "prior_year_multiple",
    "prior_year_index", "cagr_percent")
REPORTED_FIELDS = ("reported_direct_cost", "reported_operating_expense",
    "reported_interest", "reported_current_tax", "reported_associate_line")

PUBLIC_POLICY = {
    "periods": "Calendar quarters. FY2025 is actual; FY2026 and FY2027 are forecasts.",
    "units": "Money uses each report's labeled GBP or GBP thousands. Percent units store 8 for 8%; multiples store 1.08 for 1.08x.",
    "sales": "YoY assumptions refer to the same quarter last year; sequential multiples refer to the immediately preceding calendar quarter, including Q4 to Q1.",
    "signs": "Expense-column reports show costs as positive deductions; signed-account rows show expense debits as negative. Historical associate charge/(credit) uses expense basis; from FY2026 associate profit/(loss) is income-positive. Signed rows always use signed income contributions.",
    "associate": "Minority investments are already held at the opening date. They contribute zero profit in FY2025 and signed profits or losses thereafter. Contributions are after investee tax, exempt from the synthetic parent's current tax, noncash and retained in the investment. No acquisition or associate cash dividend occurs.",
    "tax_and_interest": "Fixed debt accrues its stated annual cash-interest rate evenly over four quarters. Current tax applies only to positive earnings before associate income; losses have no tax credit or carryforward.",
    "cash_and_balance": "Revenue is collected and operating costs, interest and current tax are paid in the same quarter. No working-capital movement, capital expenditure or depreciation. Fixed debt and contributed capital; owner distributions reduce cash and retained earnings. Opening balances reconcile; closing cash and investments cannot be negative.",
    "metrics": "YoY change uses the same quarter last year; QoQ change uses the preceding quarter. Prior-year multiples use 1 as base and indices use 100. Annual change uses full-year sales. FY2025-to-FY2027 CAGR spans two annual intervals. Unavailable comparisons display n/a (no comparative).",
    "distribution": "Only FY2027 Q4 may distribute 20% of positive full-year net income, when unrounded two-year sales CAGR is at least 8% and unrounded Q4 YoY sales change is at least 5%. Equality qualifies. Other periods distribute zero.",
    "portfolio": "Each independent entity enters the management portfolio once, with no FX, intercompany balances or ownership weights. Monetary totals use GBP. Margins and growth derive from aggregate amounts, not averages of individual ratios. This is not statutory consolidation.",
    "precision": "No intermediate rounding. Final numeric values use two decimals, half away from zero; displayed values do not determine eligibility.",
}


def canonical_sha256(public):
    return hashlib.sha256(json.dumps(public, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _number(value):
    if type(value) is not str or re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value) is None:
        raise ValueError("Business inputs must be finite decimal strings")
    return Fraction(value)


def validate_spec(public):
    expected = {"kind", "version", "years", "base_currency", "provenance", "public_policy", "distribution", "entities"}
    if type(public) is not dict or set(public) != expected:
        raise ValueError("Unknown or incomplete business specification")
    if public["kind"] != KIND or type(public["version"]) is not int or public["version"] != 1:
        raise ValueError("Unknown business specification kind/version")
    if public["years"] != list(YEARS) or public["base_currency"] != "GBP":
        raise ValueError("Exactly the three approved calendar years and GBP are required")
    if public["public_policy"] != PUBLIC_POLICY or public["provenance"] != "independent synthetic service-business assumptions; no official workbook seed":
        raise ValueError("The public business contract changed")
    if public["distribution"] != {"year": 2027, "profit_percent": "20", "cagr_percent": "8", "q4_yoy_percent": "5"}:
        raise ValueError("The approved distribution policy changed")
    entities = public["entities"]
    if type(entities) is not list or not 1 <= len(entities) <= 8:
        raise ValueError("One to eight independent entity reports are supported")
    names = set()
    fields = {"id", "name", "layout", "money_unit", "sales_basis", "opening", "actual_revenue", "forecast_sales_assumptions", "direct_cost_percent", "quarterly_fixed_opex", "annual_interest_percent", "tax_percent", "associate_results"}
    for e in entities:
        if type(e) is not dict or set(e) != fields:
            raise ValueError("Unknown or incomplete entity inputs")
        if (type(e["id"]) is not str or re.fullmatch(r"[A-Z][A-Z0-9_]*", e["id"]) is None
            or e["id"] in names or e["id"] == "PORTFOLIO" or type(e["name"]) is not str or not e["name"]):
            raise ValueError("Unique named entity IDs are required")
        names.add(e["id"])
        if e["layout"] not in ("expense_columns", "signed_rows") or e["money_unit"] not in ("GBP", "GBP_thousands") or e["sales_basis"] not in ("yoy_percent", "qoq_multiple"):
            raise ValueError("Unknown report, monetary unit or sales basis")
        opening = e["opening"]
        if type(opening) is not dict or set(opening) != {"cash", "investment", "debt", "capital", "retained_earnings"}:
            raise ValueError("A complete opening balance sheet is required")
        o = {k: _number(v) for k, v in opening.items()}
        if any(o[k] < 0 for k in ("cash", "investment", "debt", "capital")) or o["cash"] + o["investment"] != o["debt"] + o["capital"] + o["retained_earnings"]:
            raise ValueError("Opening balances must reconcile and asset/debt/capital amounts cannot be negative")
        for key, length in (("actual_revenue", 4), ("forecast_sales_assumptions", 8), ("quarterly_fixed_opex", 12), ("associate_results", 12)):
            if type(e[key]) is not list or len(e[key]) != length:
                raise ValueError("Complete quarterly business inputs are required: " + key)
            numbers = [_number(v) for v in e[key]]
            if key == "actual_revenue" and any(v <= 0 for v in numbers):
                raise ValueError("Revenue comparison bases must be strictly positive")
            if key == "quarterly_fixed_opex" and any(v < 0 for v in numbers):
                raise ValueError("Cash operating expenses cannot be negative")
            if key == "associate_results" and any(numbers[:4]):
                raise ValueError("FY2025 associate contributions must be zero")
            if key == "forecast_sales_assumptions" and any(v <= (-100 if e["sales_basis"] == "yoy_percent" else 0) for v in numbers):
                raise ValueError("Forecast sales must remain strictly positive")
        for key in ("direct_cost_percent", "annual_interest_percent", "tax_percent"):
            if not 0 <= _number(e[key]) <= 100:
                raise ValueError("A percentage assumption is outside zero to one hundred")
    return public


def default_spec():
    definitions = (
        ("ALDER", "Alder Advisory", "expense_columns", "GBP_thousands", "yoy_percent", ["100"] * 4,
         ["10", "-10", "5", "-5", "16.64", "16.64", "16.64", "16.64"], "55", "15", "6", "25", ["3", "-2", "4", "-1", "5", "-3", "7", "-2"]),
        ("BEACON", "Beacon Software", "signed_rows", "GBP", "yoy_percent", ["250000", "270000", "240000", "260000"],
         ["2", "4", "-5", "1", "-4", "2", "-1", "1"], "48", "45000", "5", "22", ["1000", "-2000", "1500", "-1000", "2500", "-500", "3000", "-750"]),
        ("CEDAR", "Cedar Analytics", "expense_columns", "GBP", "qoq_multiple", ["300000"] * 4,
         ["1.10", "1.05", "1.02", "1.04", "1.03", "1.02", "1.04", "1.05"], "62", "35000", "7", "25", ["-3000", "2000", "-1000", "4000", "-2000", "5000", "-1500", "6000"]),
        ("DELTA", "Delta Agency", "signed_rows", "GBP_thousands", "qoq_multiple", ["180", "190", "200", "210"],
         ["1.6", "1", "1", "1", "1", "1", "1", "1"], "52", "40", "4", "20", ["-2", "3", "-1", "4", "-3", "5", "-2", "6"]),
    )
    entities = []
    for identity, name, layout, unit, basis, history, assumptions, cost, opex, interest, tax, associate in definitions:
        scale = 1 if unit == "GBP_thousands" else 1000
        entities.append({"id": identity, "name": name, "layout": layout, "money_unit": unit, "sales_basis": basis,
            "opening": {k: str(v * scale) for k, v in {"cash": 500, "investment": 200, "debt": 100, "capital": 500, "retained_earnings": 100}.items()},
            "actual_revenue": history, "forecast_sales_assumptions": assumptions,
            "direct_cost_percent": cost, "quarterly_fixed_opex": [opex] * 12,
            "annual_interest_percent": interest, "tax_percent": tax,
            "associate_results": ["0"] * 4 + associate})
    public = {"kind": KIND, "version": 1, "years": list(YEARS), "base_currency": "GBP",
        "provenance": "independent synthetic service-business assumptions; no official workbook seed",
        "public_policy": deepcopy(PUBLIC_POLICY),
        "distribution": {"year": 2027, "profit_percent": "20", "cagr_percent": "8", "q4_yoy_percent": "5"},
        "entities": entities}
    validate_spec(public)
    return public
