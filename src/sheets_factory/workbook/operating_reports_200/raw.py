"""One fixed contract generator; no report calculations or oracle imports."""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path
from . import schema as s

ROOT = Path(__file__).resolve().parents[4]
DESIGN = ROOT / "config/operating_reports_200_frozen_design_v1.json"
DESIGN_SHA256 = "d29f83905e32845a0856a7df0377e2ed6b8cf912869ebcaf059a70d0ef21fd04"


def decimal(value):
    value = Fraction(value)
    sign = "-" if value < 0 else ""
    value = abs(value)
    whole, remainder = divmod(value.numerator, value.denominator)
    digits = []
    while remainder:
        remainder *= 10
        digit, remainder = divmod(remainder, value.denominator)
        digits.append(str(digit))
        if len(digits) > 40:
            raise ValueError("Input design did not yield a finite decimal")
    return sign + str(whole) + (("." + "".join(digits).rstrip("0")) if digits else "")


def _hash(identity, field, period):
    return int.from_bytes(hashlib.sha256(f"{s.SEED}|{identity}|{field}|{period}".encode()).digest(), "big")


def _draw(identity, field, period, low, high):
    return low + _hash(identity, field, period) % (high - low + 1)


def design():
    data = DESIGN.read_bytes()
    if hashlib.sha256(data).hexdigest() != DESIGN_SHA256:
        raise ValueError("Frozen input design bytes changed")
    value = json.loads(data)
    for item in value["artifacts"].values():
        # Original freezes use pretty JSON bytes; semantic binding is also explicit.
        if not isinstance(item["sha256"], str) or len(item["sha256"]) != 64:
            raise ValueError("Missing original immutable design identity")
    return value


def build_spec():
    """Generate the only fixed200 input specimen. No forecast ledger is run."""
    frozen = design()
    axes = frozen["artifacts"]["axis_assignment.json"]["value"]["entities"]
    sentinels = {v["entity_id"]: v for v in frozen["artifacts"]["numeric_generation_addendum.json"]["value"]["sentinels"]}
    entities = []
    for axis in axes:
        identity = axis["id"]
        scale = Fraction({"GBP": 1, "GBP_thousands": 1000, "GBP_millions": 1000000}[axis["money_unit"]])
        rate_scale = {"fraction": Fraction(100), "percent_units": Fraction(1), "basis_points": Fraction(1, 100)}[axis["rate_unit"]]
        R = Fraction(1000000 + 1000 * _draw(identity, "R_GBP", "all", 0, 7000))
        money = lambda v: decimal(v / scale)
        rate = lambda percent: decimal(percent / rate_scale)
        factor = lambda field, period, lo, hi: Fraction(_draw(identity, field, period, lo, hi), 10000)
        opening = {k: R * factor(field, "opening", lo, hi) for k, field, lo, hi in (
            ("cash", "opening_cash", 100000, 140000), ("investment", "opening_investment", 10000, 30000),
            ("debt", "fixed_debt", 5000, 15000), ("capital", "contributed_capital", 80000, 120000))}
        opening["retained_earnings"] = opening["cash"] + opening["investment"] - opening["debt"] - opening["capital"]
        actual = {p: R * factor("actual_sales", p, *( (8000,9600) if p.endswith("Q1") else (10800,12000) if p.endswith("Q4") else (8000,12000))) for p in s.QUARTERS[:4]}
        negative = set(sorted(s.QUARTERS[4:], key=lambda p: (_hash(identity, "associate_sign_order", p), p))[:4])
        opex = {p: R * factor("cash_opex", p, 600, 3200) for p in s.QUARTERS}
        associates = {p: Fraction(0) if p.startswith("2025") else R * factor("associate_magnitude", p, 200, 600) * (-1 if p in negative else 1) for p in s.QUARTERS}
        cost = Fraction(_draw(identity, "direct_cost_rate", "all", 3500, 7200), 100)
        interest = Fraction(_draw(identity, "annual_interest_rate", "all", 300, 1000), 100)
        tax = Fraction(_draw(identity, "parent_tax_rate", "all", 1500, 2800), 100)
        sentinel = sentinels.get(identity)
        if sentinel:
            actual = {p: R * Fraction(v) for p, v in zip(s.QUARTERS[:4], sentinel["actual_FY2025_sales_R_multipliers"], strict=True)}
            cost, interest, tax = Fraction(45), Fraction(6), Fraction(25)
            opex = {p: R / 10 for p in s.QUARTERS}
            associates = {p: Fraction(0) if p.startswith("2025") else R / 50 * (-1 if p in negative else 1) for p in s.QUARTERS}
        drivers = {}
        for i, p in enumerate(s.QUARTERS[4:]):
            year = p[:4]
            form = axis[f"FY{year}_driver_form"]
            if sentinel:
                level = Fraction(sentinel[f"FY{year}_same_quarter_level_factors"][i % 4])
                # A symbolic input-design identity, not a retained report result.
                reference = actual[s.QUARTERS[i % 4]] * (Fraction("1.08") if year == "2027" else 1)
                delta = reference * (level - 1)
            else:
                level = factor("forecast_level_factor", p, 9400, 11400)
                delta = R * factor("forecast_money_delta", p, -400, 1200)
            drivers[p] = rate(100 * (level - 1)) if form == "change_rate" else decimal(level) if form == "level_multiple" else decimal(100 * level) if form == "base100_index" else money(delta)
        entities.append({
            **{k: axis[k] for k in ("id", "name", "division", "layout", "line_order", "money_unit", "rate_unit", "statement_sign", "forecast_reference")},
            "driver_form_by_year": {str(y): axis[f"FY{y}_driver_form"] for y in (2026, 2027)},
            "opening": {k: money(v) for k, v in opening.items()}, "actual_sales": {p: money(v) for p,v in actual.items()},
            "forecast_sales": drivers, "direct_cost_rate": rate(cost), "cash_opex": {p: money(v) for p,v in opex.items()},
            "annual_interest_rate": rate(interest), "parent_tax_rate": rate(tax), "associate_results": {p: money(v) for p,v in associates.items()},
        })
    result = {"kind": s.KIND, "version": 1, "dimension_mode": "production", "seed": s.SEED,
        "years": list(s.YEARS), "base_currency": "GBP", "provenance": "new hypothetical service businesses; no official workbook seed",
        "public_policy": frozen["public_policy"], "distribution": {"year": 2027, "profit_percent": "20", "cagr_percent": "8", "q4_yoy_percent": "5"},
        "divisions": list(s.DIVISIONS), "entities": entities}
    return s.validate_spec(result)


def freeze_spec(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    # Reservation precedes generation; failed artifacts are not replaced.
    (output / "generation_started.json").write_text(json.dumps({"kind": "fixed_operating_reports_200_input_generation_started", "version": 1, "seed": s.SEED}))
    result = build_spec()
    data = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    with (output / "public_specification.json").open("xb") as stream:
        stream.write(data)
    receipt = {"kind": "fixed_operating_reports_200_input_generation", "version": 1, "specification": {"path": str((output / "public_specification.json").resolve()), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}, "canonical_specification_sha256": s.canonical_sha256(result), "entities": 200, "report_points": len(list(s.points(result))), "financial_forwards": 0, "workbooks": 0, "services": 0}
    with (output / "receipt.json").open("x") as stream:
        json.dump(receipt, stream, indent=2); stream.write("\n")
    return receipt
