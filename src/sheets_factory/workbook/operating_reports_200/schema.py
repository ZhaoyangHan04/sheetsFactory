"""Shared input/result vocabulary and shape checks, without financial logic."""
from __future__ import annotations

import hashlib
import json
import re

KIND = "hypothetical_200_entity_operating_report_specification"
RESULT_KIND = "hypothetical_200_entity_operating_report_values"
VERSION = 1
SEED = 202711200
YEARS = (2025, 2026, 2027)
QUARTERS = tuple(f"{year}Q{q}" for year in YEARS for q in range(1, 5))
FLOWS = ("revenue", "direct_cost", "operating_expense", "operating_profit", "interest", "pretax_before_associate", "current_tax", "core_net_income", "associate_income", "net_income", "dividend", "operating_cash_flow")
STOCKS = ("closing_cash", "closing_investment", "closing_retained_earnings", "debt", "contributed_capital", "total_assets", "total_liabilities_equity")
QUARTER_METRICS = ("net_margin_percent", "yoy_percent", "qoq_percent", "prior_year_multiple", "prior_year_index", "yoy_sales_delta", "qoq_sales_delta")
REPORTED = ("reported_direct_cost", "reported_operating_expense", "reported_interest", "reported_current_tax", "reported_associate_line")
ANNUAL_METRICS = ("net_margin_percent", "yoy_percent", "prior_year_multiple", "prior_year_index", "cagr_percent", "annual_sales_delta")
LAYOUTS = ("quarter_columns", "quarter_rows", "year_panels", "quarter_cards", "split_reporting_sections", "reverse_chronology_dashboard")
LINE_ORDERS = ("statement_first", "cash_first", "performance_first")
MONEY_UNITS = ("GBP", "GBP_thousands", "GBP_millions")
RATE_UNITS = ("fraction", "percent_units", "basis_points")
SIGN_BASES = ("positive_deductions", "signed_contributions")
REFERENCES = ("same_quarter_last_year", "previous_calendar_quarter")
DRIVER_FORMS = ("change_rate", "level_multiple", "base100_index", "money_delta")
DIVISIONS = ("Advisory", "Analytics", "Cloud", "Creative", "Engineering", "Facilities", "Logistics", "Software")
NA = "n/a (no comparative)"
GROUP_NA = "n/a (entity-level distribution policy)"
ACTUAL_DRIVER_NA = "n/a (actual quarter)"
FORECAST_ACTUAL_NA = "n/a (forecast quarter)"
DECIMAL_PATTERN = r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?"


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _keys(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError("Unexpected or missing schema fields")


def _decimal(value):
    if type(value) is not str or re.fullmatch(DECIMAL_PATTERN, value) is None:
        raise ValueError("Inputs require finite exact decimal strings")


def validate_spec(public):
    """Check vocabulary/shape only; independent oracles check business validity."""
    _keys(public, ("kind", "version", "dimension_mode", "seed", "years", "base_currency", "provenance", "public_policy", "distribution", "divisions", "entities"))
    if public["kind"] != KIND or type(public["version"]) is not int or public["version"] != 1 or public["seed"] != SEED:
        raise ValueError("Unknown experiment identity")
    if public["dimension_mode"] not in ("production", "toy") or public["years"] != list(YEARS) or public["base_currency"] != "GBP":
        raise ValueError("Unknown period, dimension or currency")
    if public["provenance"] != "new hypothetical service businesses; no official workbook seed" or not isinstance(public["public_policy"], str) or not public["public_policy"]:
        raise ValueError("Missing hypothetical provenance or public business policy")
    if public["distribution"] != {"year": 2027, "profit_percent": "20", "cagr_percent": "8", "q4_yoy_percent": "5"}:
        raise ValueError("Distribution policy differs from the frozen contract")
    entities = public["entities"]
    if type(entities) is not list or not (len(entities) == 200 if public["dimension_mode"] == "production" else 1 <= len(entities) <= 4):
        raise ValueError("Expected exactly200 production entities or1..4 explicit toy entities")
    if type(public["divisions"]) is not list or len(set(public["divisions"])) != len(public["divisions"]) or any(v not in DIVISIONS for v in public["divisions"]):
        raise ValueError("Unknown division inventory")
    if public["dimension_mode"] == "production" and public["divisions"] != list(DIVISIONS):
        raise ValueError("Production requires the fixed eight divisions")
    ids = set()
    for e in entities:
        _keys(e, ("id", "name", "division", "layout", "line_order", "money_unit", "rate_unit", "statement_sign", "forecast_reference", "driver_form_by_year", "opening", "actual_sales", "forecast_sales", "direct_cost_rate", "cash_opex", "annual_interest_rate", "parent_tax_rate", "associate_results"))
        if type(e["id"]) is not str or re.fullmatch(r"E[0-9]{3}", e["id"]) is None or e["id"] in ids or not isinstance(e["name"], str) or not e["name"] or e["division"] not in public["divisions"]:
            raise ValueError("Invalid entity identity")
        ids.add(e["id"])
        for key, values in (("layout", LAYOUTS), ("line_order", LINE_ORDERS), ("money_unit", MONEY_UNITS), ("rate_unit", RATE_UNITS), ("statement_sign", SIGN_BASES), ("forecast_reference", REFERENCES)):
            if e[key] not in values:
                raise ValueError("Unknown labelled report convention: " + key)
        _keys(e["driver_form_by_year"], ("2026", "2027"))
        if any(v not in DRIVER_FORMS for v in e["driver_form_by_year"].values()):
            raise ValueError("Unknown labelled sales measure")
        _keys(e["opening"], ("cash", "investment", "debt", "capital", "retained_earnings"))
        for v in e["opening"].values():
            _decimal(v)
        for key, periods in (("actual_sales", QUARTERS[:4]), ("forecast_sales", QUARTERS[4:]), ("cash_opex", QUARTERS), ("associate_results", QUARTERS)):
            _keys(e[key], periods)
            for v in e[key].values():
                _decimal(v)
        for key in ("direct_cost_rate", "annual_interest_rate", "parent_tax_rate"):
            _decimal(e[key])
    if public["dimension_mode"] == "production":
        if [e["id"] for e in entities] != [f"E{i:03d}" for i in range(1, 201)]:
            raise ValueError("Production entity order changed")
        if any(sum(e["division"] == d for e in entities) != 25 for d in DIVISIONS):
            raise ValueError("Every division must contain25 distinct entities")
    return public


def groups(public):
    """Schema inventory only; each entity has one division and one master."""
    return tuple("DIV_" + v.upper() for v in public["divisions"]) + ("PORTFOLIO",)


def points(public):
    """Yield semantic keys and prescribed value types, without calculations."""
    for identity, entity in [(e["id"], True) for e in public["entities"]] + [(g, False) for g in groups(public)]:
        for period in QUARTERS:
            for field in FLOWS + STOCKS + QUARTER_METRICS + (REPORTED if entity else ()):
                unavailable = (period.startswith("2025") and field in ("yoy_percent", "prior_year_multiple", "prior_year_index", "yoy_sales_delta")) or (period == "2025Q1" and field in ("qoq_percent", "qoq_sales_delta"))
                yield f"{identity}/{period}/{field}", "text" if unavailable else "number"
        for year in YEARS:
            for field in FLOWS + STOCKS + ANNUAL_METRICS + ("distribution_eligible",):
                unavailable = year == 2025 and field in ("yoy_percent", "prior_year_multiple", "prior_year_index", "cagr_percent", "annual_sales_delta")
                kind = "text" if unavailable or (not entity and field == "distribution_eligible") else "boolean" if field == "distribution_eligible" else "number"
                yield f"{identity}/FY{year}/{field}", kind


def validate_result(public, result):
    _keys(result, ("kind", "version", "specification_sha256", "economic_exact_values", "raw_cell_exact_values", "typed_2dp_values", "cagr_proofs", "reconciliation_checks"))
    if result["kind"] != RESULT_KIND or result["version"] != VERSION or result["specification_sha256"] != canonical_sha256(public):
        raise ValueError("Result identity/specification changed")
    expected = dict(points(public))
    for name in ("economic_exact_values", "raw_cell_exact_values", "typed_2dp_values"):
        if type(result[name]) is not dict or set(result[name]) != set(expected):
            raise ValueError("Result does not cover the entire declared report union")
    for key, kind in expected.items():
        item = result["typed_2dp_values"][key]
        _keys(item, ("type", "value"))
        if item["type"] != kind or (kind == "number" and (not isinstance(item["value"], str) or re.fullmatch(r"-?(?:0|[1-9][0-9]*)\.[0-9]{2}", item["value"]) is None)) or (kind == "boolean" and type(item["value"]) is not bool) or (kind == "text" and item["value"] not in (NA, GROUP_NA)):
            raise ValueError("Wrong primary typed result")
    return result
