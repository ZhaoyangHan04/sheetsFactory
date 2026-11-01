"""Independent rational journal for the hypothetical associate bridge.

The earlier B oracle supplies unchanged operating facts and comparison metrics.
All new recognition, tax and cash/investment bridges are derived here without
reading another bridge oracle, a workbook, or an Excel formula.
"""
from copy import deepcopy
from fractions import Fraction
import re

from ..operating_reports_200 import oracle_b as operating_b, schema

_F = Fraction
_MONEY = {"GBP": 1, "GBP_thousands": 1000, "GBP_millions": 1000000}
_PERCENT = {"fraction": _F(100), "percent_units": _F(1), "basis_points": _F(1, 100)}
_MONETARY = set(schema.FLOWS + schema.STOCKS + schema.REPORTED +
                ("yoy_sales_delta", "qoq_sales_delta", "annual_sales_delta"))
_POLICY_FIELDS = {"method", "tax_class", "feed_scale", "direction_by_year",
                  "share_postings", "cash_receipts", "receipt_kind"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _decimal(value):
    _require(type(value) is str and re.fullmatch(schema.DECIMAL_PATTERN, value) is not None,
             "Bridge input amounts require finite decimal strings")
    return _F(value)


def _validate(public):
    _require(type(public) is dict and public.get("kind") == "associate_bridge_business_spec_v1",
             "Unknown associate bridge public specification")
    _require(public.get("case_id") in {f"B{i:02d}" for i in range(1, 9)}, "Unknown bridge case")
    base = schema.validate_spec(public["base"])
    policies = public["policies"]
    _require(type(policies) is dict and set(policies) == {e["id"] for e in base["entities"]},
             "Every entity requires exactly one public bridge policy")
    for policy in policies.values():
        _require(type(policy) is dict and set(policy) == _POLICY_FIELDS, "Incomplete bridge policy")
        _require(policy["method"] in {"equity", "cost"}, "Unknown investment method")
        _require(policy["tax_class"] in {"exempt", "recognized", "cash_dividends"}, "Unknown tax class")
        _require(type(policy["feed_scale"]) is int and policy["feed_scale"] in {1, 1000, 1000000},
                 "Unknown associate feed monetary scale")
        directions = policy["direction_by_year"]
        _require(type(directions) is dict and set(directions) == {str(y) for y in schema.YEARS}
                 and all(v in {"income_positive", "charge_credit"} for v in directions.values()),
                 "Each year needs an explicit posting direction")
        for field in ("share_postings", "cash_receipts", "receipt_kind"):
            _require(type(policy[field]) is dict and set(policy[field]) == set(schema.QUARTERS),
                     "Every event series must cover all twelve calendar quarters")
        for quarter in schema.QUARTERS:
            posting = _decimal(policy["share_postings"][quarter])
            receipt = _decimal(policy["cash_receipts"][quarter])
            _require(receipt >= 0, "Cash receipts cannot be negative")
            _require(policy["receipt_kind"][quarter] in {"dividend", "capital_return"},
                     "Unknown cash receipt classification")
            _require(not quarter.startswith("2025") or (posting == 0 and receipt == 0),
                     "FY2025 bridge events must all be zero")
    return base


def _rounded(value):
    value = _F(value)
    quotient, residual = divmod(abs(value.numerator) * 100, value.denominator)
    if residual * 2 >= value.denominator:
        quotient += 1
    return ("-" if value < 0 and quotient else "") + f"{quotient // 100}.{quotient % 100:02d}"


def solve(public):
    """Return the complete base-shaped financial union under the new contract."""
    base = _validate(public)
    result = deepcopy(operating_b.solve(base))
    values = result["economic_exact_values"]

    def old_number(identity, period, field):
        item = values[f"{identity}/{period}/{field}"]
        _require(item["kind"] == "rational", "Expected an unchanged exact operating fact")
        return _F(item["value"])

    entities = {e["id"]: e for e in base["entities"]}
    units = {identity: (_F(_MONEY[e["money_unit"]]), _PERCENT[e["rate_unit"]])
             for identity, e in entities.items()}
    openings = {}
    records = {}
    deltas = {}
    eligibility = {}
    membership = {"DIV_" + division.upper(): [e["id"] for e in base["entities"]
                   if e["division"] == division] for division in base["divisions"]}
    membership["PORTFOLIO"] = list(entities)

    # A complete journal is computed before closing stocks or distributions.
    for identity, entity in entities.items():
        money, percent = units[identity]
        opening = {name: _F(value) * money for name, value in entity["opening"].items()}
        openings[identity] = opening
        policy = public["policies"][identity]
        tax_rate = _F(entity["parent_tax_rate"]) * percent / 100
        rows, investment_changes = [], []
        for quarter in schema.QUARTERS:
            row = {field: old_number(identity, quarter, field) for field in schema.FLOWS}
            direction = -1 if policy["direction_by_year"][quarter[:4]] == "charge_credit" else 1
            # Postings are feed units; receipts are the entity report units.
            share = _F(policy["share_postings"][quarter]) * policy["feed_scale"] * direction
            receipt = _F(policy["cash_receipts"][quarter]) * money
            capital_return = receipt if policy["receipt_kind"][quarter] == "capital_return" else _F(0)
            dividend_cash = receipt - capital_return
            equity = policy["method"] == "equity"
            recognized = share if equity else dividend_cash
            taxable_associate = {"exempt": _F(0), "recognized": recognized,
                                 "cash_dividends": dividend_cash}[policy["tax_class"]]
            pretax = row["pretax_before_associate"]
            tax = max(_F(0), pretax + taxable_associate) * tax_rate
            core = pretax - tax
            net_income = core + recognized
            row.update(current_tax=tax, core_net_income=core, associate_income=recognized,
                       net_income=net_income, operating_cash_flow=net_income - recognized + receipt,
                       dividend=_F(0))
            rows.append(row)
            investment_changes.append((share - receipt) if equity else -capital_return)
        annual_income = sum(row["net_income"] for row in rows[8:])
        first_sales = sum(row["revenue"] for row in rows[:4])
        final_sales = sum(row["revenue"] for row in rows[8:])
        eligible = (annual_income > 0 and final_sales * 625 >= first_sales * 729
                    and rows[11]["revenue"] * 20 >= rows[7]["revenue"] * 21)
        eligibility[identity] = eligible
        rows[11]["dividend"] = annual_income / 5 if eligible else _F(0)
        for index, row in enumerate(rows):
            prefix = rows[:index + 1]
            distributions = sum(item["dividend"] for item in prefix)
            cash = opening["cash"] + sum(item["operating_cash_flow"] for item in prefix) - distributions
            investment = opening["investment"] + sum(investment_changes[:index + 1])
            retained = opening["retained_earnings"] + sum(item["net_income"] for item in prefix) - distributions
            _require(cash >= 0 and investment >= 0, "The bridge requires undeclared funding or negative investment")
            row.update(closing_cash=cash, closing_investment=investment,
                       closing_retained_earnings=retained, debt=opening["debt"],
                       contributed_capital=opening["capital"], total_assets=cash + investment,
                       total_liabilities_equity=opening["debt"] + opening["capital"] + retained)
        records[identity] = rows
        deltas[identity] = investment_changes

    for identity, members in membership.items():
        units[identity] = (_F(1), _F(1))
        openings[identity] = {field: sum(openings[e][field] for e in members)
                              for field in ("cash", "investment", "debt", "capital", "retained_earnings")}
        records[identity] = [{field: sum(records[e][index][field] for e in members)
                              for field in schema.FLOWS + schema.STOCKS} for index in range(12)]
        deltas[identity] = [sum(deltas[e][index] for e in members) for index in range(12)]

    checks = {"passed": True, "group_membership": membership,
              "opening_balance_residuals": {}, "quarter_balance_residuals": {},
              "cash_bridge_residuals": {}, "investment_bridge_residuals": {},
              "retained_earnings_bridge_residuals": {}}

    def put(identity, period, field, number):
        key = f"{identity}/{period}/{field}"
        _require(key in values and values[key]["kind"] == "rational", "Bridge changed the declared point inventory")
        number = _F(number)
        money, percent = units[identity]
        raw = number / money if field in _MONETARY else number / percent if field.endswith("_percent") else number
        values[key] = {"kind": "rational", "value": str(number)}
        result["raw_cell_exact_values"][key] = {"kind": "rational", "value": str(raw)}
        result["typed_2dp_values"][key] = {"type": "number", "value": _rounded(raw)}

    for identity, rows in records.items():
        opening = openings[identity]
        residual = opening["cash"] + opening["investment"] - opening["debt"] - opening["capital"] - opening["retained_earnings"]
        _require(residual == 0, "Opening bridge balance does not reconcile")
        checks["opening_balance_residuals"][identity] = str(residual)
        for index, row in enumerate(rows):
            period = schema.QUARTERS[index]
            previous = rows[index - 1] if index else {"closing_cash": opening["cash"],
                "closing_investment": opening["investment"], "closing_retained_earnings": opening["retained_earnings"]}
            residuals = {"quarter_balance_residuals": row["total_assets"] - row["total_liabilities_equity"],
                "cash_bridge_residuals": row["closing_cash"] - previous["closing_cash"] - row["operating_cash_flow"] + row["dividend"],
                "investment_bridge_residuals": row["closing_investment"] - previous["closing_investment"] - deltas[identity][index],
                "retained_earnings_bridge_residuals": row["closing_retained_earnings"] - previous["closing_retained_earnings"] - row["net_income"] + row["dividend"]}
            for name, residual in residuals.items():
                _require(residual == 0, "Independent associate journal does not reconcile: " + name)
                checks[name][identity + "/" + period] = str(residual)
            for field in schema.FLOWS + schema.STOCKS:
                put(identity, period, field, row[field])
            put(identity, period, "net_margin_percent", row["net_income"] * 100 / row["revenue"])
            if identity in entities:
                sign = -1 if entities[identity]["statement_sign"] == "signed_contributions" else 1
                put(identity, period, "reported_current_tax", sign * row["current_tax"])
                put(identity, period, "reported_associate_line", row["associate_income"] if index >= 4 else 0)
        for year_index, year in enumerate(schema.YEARS):
            period = f"FY{year}"
            quarters = rows[4 * year_index:4 * year_index + 4]
            for field in schema.FLOWS:
                put(identity, period, field, sum(row[field] for row in quarters))
            for field in schema.STOCKS:
                put(identity, period, field, quarters[-1][field])
            revenue = sum(row["revenue"] for row in quarters)
            income = sum(row["net_income"] for row in quarters)
            put(identity, period, "net_margin_percent", 100 * income / revenue)
            if identity in entities:
                key = f"{identity}/{period}/distribution_eligible"
                value = eligibility[identity] if year == 2027 else False
                values[key] = result["raw_cell_exact_values"][key] = {"kind": "boolean", "value": value}
                result["typed_2dp_values"][key] = {"type": "boolean", "value": value}
    result.update(kind="associate_bridge_values_v1", specification_sha256=schema.canonical_sha256(public),
                  reconciliation_checks=checks)
    expected = dict(schema.points(base))
    _require(all(set(result[name]) == set(expected) for name in
                 ("economic_exact_values", "raw_cell_exact_values", "typed_2dp_values")),
             "The full financial union must remain present")
    return result
