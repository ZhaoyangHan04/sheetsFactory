"""Independent forward quarterly ledger, with rational root enclosures."""
from __future__ import annotations

from fractions import Fraction as F
from math import isqrt

from . import spec


def display(value):
    """Decimal half away from zero, retaining the sign of tiny negatives."""
    value = F(value)
    cents, remainder = divmod(abs(value.numerator) * 100, value.denominator)
    cents += 2 * remainder >= value.denominator
    sign = "-" if value < 0 else ""
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def cagr_display(ratio):
    """Certify the displayed two-year rate without a floating-point root."""
    ratio = F(ratio)
    if ratio <= 0:
        raise ValueError("CAGR endpoints must be positive")
    n, d = isqrt(ratio.numerator), isqrt(ratio.denominator)
    if n * n == ratio.numerator and d * d == ratio.denominator:
        root = F(n, d)
        return display(100 * (root - 1)), {"method": "rational_root_or_forward_bisection", "root_lower": root, "root_upper": root, "iterations": 0}
    low, high = F(0), max(F(1), ratio)
    for iteration in range(1, 2049):
        midpoint = (low + high) / 2
        if midpoint * midpoint < ratio:
            low = midpoint
        else:
            high = midpoint
        left, right = display(100 * (low - 1)), display(100 * (high - 1))
        if left == right:
            return left, {"method": "rational_root_or_forward_bisection", "root_lower": low, "root_upper": high, "iterations": iteration}
    raise ValueError("CAGR display could not be certified")


def _metrics(revenues, i):
    current = revenues[i]
    yoy = current / revenues[i - 4] if i >= 4 else None
    return {"yoy_percent": 100 * (yoy - 1) if yoy is not None else spec.NA,
        "qoq_percent": 100 * (current / revenues[i - 1] - 1) if i else spec.NA,
        "prior_year_multiple": yoy if yoy is not None else spec.NA,
        "prior_year_index": 100 * yoy if yoy is not None else spec.NA}


def _annual(rows, year_index):
    block = rows[year_index * 4:year_index * 4 + 4]
    return {**{field: sum((r[field] for r in block), F(0)) for field in spec.FLOW_FIELDS},
        **{field: block[-1][field] for field in spec.STOCK_FIELDS}}


def solve(public):
    spec.validate_spec(public)
    exact, roots = {}, {}
    entities = {}
    distribution = public["distribution"]
    for e in public["entities"]:
        revenue = [F(v) for v in e["actual_revenue"]]
        for index, assumption in enumerate(e["forecast_sales_assumptions"], 4):
            if e["sales_basis"] == "yoy_percent":
                revenue.append(revenue[index - 4] * (1 + F(assumption) / 100))
            else:
                revenue.append(revenue[index - 1] * F(assumption))
        raw = []
        debt = F(e["opening"]["debt"])
        for i, sales in enumerate(revenue):
            cost = sales * F(e["direct_cost_percent"]) / 100
            expense = F(e["quarterly_fixed_opex"][i])
            operating = sales - cost - expense
            interest = debt * F(e["annual_interest_percent"]) / 400
            pretax = operating - interest
            tax = max(F(0), pretax) * F(e["tax_percent"]) / 100
            associate = F(e["associate_results"][i])
            raw.append({"revenue": sales, "direct_cost": cost, "operating_expense": expense,
                "operating_profit": operating, "interest": interest,
                "pretax_before_associate": pretax, "current_tax": tax,
                "core_net_income": pretax - tax, "associate_income": associate,
                "net_income": pretax - tax + associate})
        annual_sales = [sum(revenue[i:i + 4], F(0)) for i in (0, 4, 8)]
        annual_profit = sum((r["net_income"] for r in raw[8:12]), F(0))
        eligible = (annual_profit > 0
            and annual_sales[2] / annual_sales[0] >= (1 + F(distribution["cagr_percent"]) / 100) ** 2
            and revenue[11] / revenue[7] >= 1 + F(distribution["q4_yoy_percent"]) / 100)
        cash, investment, retained = (F(e["opening"][k]) for k in ("cash", "investment", "retained_earnings"))
        capital = F(e["opening"]["capital"])
        rows = []
        for i, row in enumerate(raw):
            dividend = annual_profit * F(distribution["profit_percent"]) / 100 if eligible and i == 11 else F(0)
            operating_cash = row["net_income"] - row["associate_income"]
            cash += operating_cash - dividend
            investment += row["associate_income"]
            retained += row["net_income"] - dividend
            if cash < 0 or investment < 0:
                raise ValueError("Closing cash or investment is negative")
            row.update(dividend=dividend, operating_cash_flow=operating_cash,
                closing_cash=cash, closing_investment=investment, closing_retained_earnings=retained,
                debt=debt, contributed_capital=capital, total_assets=cash + investment,
                total_liabilities_equity=debt + capital + retained,
                net_margin_percent=100 * row["net_income"] / row["revenue"], **_metrics(revenue, i))
            if row["total_assets"] != row["total_liabilities_equity"]:
                raise ValueError("Quarterly statement does not reconcile")
            expense_sign = 1 if e["layout"] == "expense_columns" else -1
            for field in ("direct_cost", "operating_expense", "interest", "current_tax"):
                row["reported_" + field] = expense_sign * row[field]
            row["reported_associate_line"] = -row["associate_income"] if e["layout"] == "expense_columns" and i < 4 else row["associate_income"]
            period = f"{2025 + i // 4}Q{i % 4 + 1}"
            for field, value in row.items():
                exact[f'{e["id"]}/{period}/{field}'] = value
            rows.append(row)
        entities[e["id"]] = (e, rows)
        for j, year in enumerate(spec.YEARS):
            row = _annual(rows, j)
            previous = annual_sales[j - 1] if j else None
            ratio = annual_sales[j] / previous if previous is not None else None
            row.update(net_margin_percent=100 * row["net_income"] / row["revenue"],
                yoy_percent=100 * (ratio - 1) if ratio is not None else spec.NA,
                prior_year_multiple=ratio if ratio is not None else spec.NA,
                prior_year_index=100 * ratio if ratio is not None else spec.NA,
                cagr_percent=spec.NA if j == 0 else 100 * (annual_sales[j] / annual_sales[0] - 1) if j == 1 else ("cagr_percent", annual_sales[j] / annual_sales[0], 2),
                distribution_eligible=bool(eligible and j == 2))
            exact.update({f'{e["id"]}/FY{year}/{k}': v for k, v in row.items()})
    portfolio = []
    for i in range(12):
        row = {field: sum((rows[i][field] * (1000 if e["money_unit"] == "GBP_thousands" else 1)
            for e, rows in entities.values()), F(0)) for field in (*spec.FLOW_FIELDS, *spec.STOCK_FIELDS)}
        portfolio.append(row)
    totals = [r["revenue"] for r in portfolio]
    for i, row in enumerate(portfolio):
        row.update(net_margin_percent=100 * row["net_income"] / row["revenue"], **_metrics(totals, i))
        period = f"{2025 + i // 4}Q{i % 4 + 1}"
        exact.update({f"PORTFOLIO/{period}/{k}": v for k, v in row.items()})
    annual_totals = [sum(totals[j:j + 4], F(0)) for j in (0, 4, 8)]
    for j, year in enumerate(spec.YEARS):
        row = _annual(portfolio, j)
        ratio = annual_totals[j] / annual_totals[j - 1] if j else None
        row.update(net_margin_percent=100 * row["net_income"] / row["revenue"],
            yoy_percent=100 * (ratio - 1) if ratio is not None else spec.NA,
            prior_year_multiple=ratio if ratio is not None else spec.NA,
            prior_year_index=100 * ratio if ratio is not None else spec.NA,
            cagr_percent=spec.NA if j == 0 else 100 * (annual_totals[j] / annual_totals[0] - 1) if j == 1 else ("cagr_percent", annual_totals[j] / annual_totals[0], 2))
        exact.update({f"PORTFOLIO/FY{year}/{k}": v for k, v in row.items()})
    typed = {}
    for key, value in exact.items():
        if isinstance(value, tuple):
            rendered, proof = cagr_display(value[1])
            typed[key] = {"type": "number", "value": rendered}; roots[key] = proof
        elif type(value) is bool:
            typed[key] = {"type": "boolean", "value": value}
        elif type(value) is str:
            typed[key] = {"type": "string", "value": value}
        else:
            typed[key] = {"type": "number", "value": display(value)}
    return {"kind": "operating_metrics_regime_oracle_values", "version": 1, "implementation": "A",
        "specification_sha256": spec.canonical_sha256(public), "exact_values": exact,
        "display_values": typed, "cagr_proofs": roots}
