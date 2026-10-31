"""Independent forward rational ledger; does not read workbook bindings."""
from __future__ import annotations

from fractions import Fraction as F
from math import isqrt
from . import schema as s


def rounded(value):
    value = F(value)
    cents = (abs(value).numerator * 200 + abs(value).denominator) // (2 * abs(value).denominator)
    return ("-" if value < 0 and cents else "") + f"{cents // 100}.{cents % 100:02d}"


def _cagr(ratio, years, unit):
    if ratio <= 0 or years not in (1, 2):
        raise ValueError("CAGR needs positive annual sales and one or two intervals")
    if years == 1:
        low = high = ratio
    else:
        n, d = isqrt(ratio.numerator), isqrt(ratio.denominator)
        if n * n == ratio.numerator and d * d == ratio.denominator:
            low = high = F(n, d)
        else:
            low, high = F(0), max(F(1), ratio)
            for _ in range(180):
                middle = (low + high) / 2
                if middle * middle < ratio:
                    low = middle
                else:
                    high = middle
                if rounded(100 * (low - 1) / unit) == rounded(100 * (high - 1) / unit):
                    break
            else:
                raise ValueError("CAGR interval did not certify the primary result")
    lo, hi = 100 * (low - 1) / unit, 100 * (high - 1) / unit
    if rounded(lo) != rounded(hi):
        raise ValueError("Ambiguous CAGR rounding interval")
    return {"endpoint_ratio": str(ratio), "years": years, "percent_units_per_raw_unit": str(unit), "lower_raw": str(lo), "upper_raw": str(hi), "rounded": rounded(lo)}


def _metrics(sales, net_income, index):
    revenue = sales[index]
    result = {"net_margin_percent": 100 * net_income / revenue}
    if index < 4:
        result.update(yoy_percent=s.NA, prior_year_multiple=s.NA, prior_year_index=s.NA, yoy_sales_delta=s.NA)
    else:
        ratio = revenue / sales[index - 4]
        result.update(yoy_percent=100 * (ratio - 1), prior_year_multiple=ratio, prior_year_index=100 * ratio, yoy_sales_delta=revenue - sales[index - 4])
    if index == 0:
        result.update(qoq_percent=s.NA, qoq_sales_delta=s.NA)
    else:
        result.update(qoq_percent=100 * (revenue / sales[index - 1] - 1), qoq_sales_delta=revenue - sales[index - 1])
    return result


def solve(public_specification):
    public = s.validate_spec(public_specification)
    all_quarters, annual, opening, units = {}, {}, {}, {}
    residuals = {name: {} for name in ("opening_balance_residuals", "quarter_balance_residuals", "cash_bridge_residuals", "investment_bridge_residuals", "retained_earnings_bridge_residuals")}
    for e in public["entities"]:
        identity = e["id"]
        money = F({"GBP": 1, "GBP_thousands": 1000, "GBP_millions": 1000000}[e["money_unit"]])
        rate = {"fraction": F(100), "percent_units": F(1), "basis_points": F(1, 100)}[e["rate_unit"]]
        units[identity] = money, rate
        begin = {k: F(v) * money for k, v in e["opening"].items()}
        opening[identity] = begin
        residuals["opening_balance_residuals"][identity] = begin["cash"] + begin["investment"] - begin["debt"] - begin["capital"] - begin["retained_earnings"]
        cost, interest, tax = (F(e[k]) * rate / 100 for k in ("direct_cost_rate", "annual_interest_rate", "parent_tax_rate"))
        if any(v < 0 or v > 1 for v in (cost, interest, tax)):
            raise ValueError("Financial rate outside zero to one")
        sales = [F(e["actual_sales"][p]) * money for p in s.QUARTERS[:4]]
        for i, p in enumerate(s.QUARTERS[4:], start=4):
            basis = sales[i - (4 if e["forecast_reference"] == "same_quarter_last_year" else 1)]
            value = F(e["forecast_sales"][p])
            form = e["driver_form_by_year"][p[:4]]
            sales.append(basis + value * money if form == "money_delta" else basis * (1 + value * rate / 100) if form == "change_rate" else basis * value if form == "level_multiple" else basis * value / 100)
        if min(sales) <= 0:
            raise ValueError("Sales comparison bases must stay positive")
        rows = []
        for i, p in enumerate(s.QUARTERS):
            revenue = sales[i]
            direct = cost * revenue
            opex = F(e["cash_opex"][p]) * money
            cash_interest = begin["debt"] * interest / 4
            associate = F(e["associate_results"][p]) * money
            if opex < 0 or (i < 4 and associate):
                raise ValueError("Invalid provided operating/associate fact")
            pretax = revenue - direct - opex - cash_interest
            current_tax = max(pretax, F(0)) * tax
            core = pretax - current_tax
            rows.append(dict(revenue=revenue, direct_cost=direct, operating_expense=opex, operating_profit=revenue-direct-opex, interest=cash_interest, pretax_before_associate=pretax, current_tax=current_tax, core_net_income=core, associate_income=associate, net_income=core+associate))
        annual_sales = [sum(sales[j:j+4]) for j in (0,4,8)]
        # Exact squared comparison is equivalent to unrounded two-year CAGR>=8%.
        eligible = annual_sales[2] / annual_sales[0] >= F(27,25)**2 and sales[11] / sales[7] >= F(21,20)
        final_profit = sum(r["net_income"] for r in rows[8:12])
        cash, investment, retained = (begin[k] for k in ("cash", "investment", "retained_earnings"))
        for i, row in enumerate(rows):
            distribution = max(final_profit, F(0))/5 if i == 11 and eligible else F(0)
            cashflow = row["net_income"] - row["associate_income"]
            previous = cash, investment, retained
            cash += cashflow - distribution
            investment += row["associate_income"]
            retained += row["net_income"] - distribution
            if cash < 0 or investment < 0:
                raise ValueError("Closing cash and investment must be nonnegative")
            row.update(dividend=distribution, operating_cash_flow=cashflow, closing_cash=cash, closing_investment=investment, closing_retained_earnings=retained, debt=begin["debt"], contributed_capital=begin["capital"], total_assets=cash+investment, total_liabilities_equity=begin["debt"]+begin["capital"]+retained)
            row.update(_metrics(sales, row["net_income"], i))
            expense_sign = -1 if e["statement_sign"] == "signed_contributions" else 1
            for field in ("direct_cost", "operating_expense", "interest", "current_tax"):
                row["reported_"+field] = expense_sign*row[field]
            row["reported_associate_line"] = -row["associate_income"] if i < 4 and expense_sign == 1 else row["associate_income"]
            _residuals(residuals, identity, s.QUARTERS[i], row, previous)
        all_quarters[identity] = rows
        annual[identity] = _annual(rows, eligible)
    membership = {"DIV_"+division.upper(): [e["id"] for e in public["entities"] if e["division"] == division] for division in public["divisions"]}
    membership["PORTFOLIO"] = [e["id"] for e in public["entities"]]
    for group, members in membership.items():
        units[group] = F(1), F(1)
        begin = {k: sum(opening[m][k] for m in members) for k in ("cash", "investment", "debt", "capital", "retained_earnings")}
        opening[group] = begin
        rows = [{k: sum(all_quarters[m][i][k] for m in members) for k in s.FLOWS+s.STOCKS} for i in range(12)]
        sales = [r["revenue"] for r in rows]
        previous = begin["cash"], begin["investment"], begin["retained_earnings"]
        for i, row in enumerate(rows):
            row.update(_metrics(sales, row["net_income"], i))
            _residuals(residuals, group, s.QUARTERS[i], row, previous)
            previous = row["closing_cash"], row["closing_investment"], row["closing_retained_earnings"]
        all_quarters[group] = rows
        annual[group] = _annual(rows, None)
    economic, raw, typed, proofs = {}, {}, {}, {}
    for key, kind in s.points(public):
        identity, period, field = key.split("/")
        value = annual[identity][int(period[2:])-2025][field] if period.startswith("FY") else all_quarters[identity][s.QUARTERS.index(period)][field]
        money, rate = units[identity]
        if isinstance(value, tuple):
            ratio, years = value
            economic[key] = {"kind": "cagr", "endpoint_ratio": str(ratio), "years": years, "percent_units_per_raw_unit": "1"}
            raw[key] = {**economic[key], "percent_units_per_raw_unit": str(rate)}
            proofs[key] = _cagr(ratio, years, rate)
            typed[key] = {"type": "number", "value": proofs[key]["rounded"]}
        elif kind == "number":
            value = F(value)
            unit = rate if field.endswith("_percent") else F(1) if field in ("prior_year_multiple", "prior_year_index") else money
            economic[key] = {"kind": "rational", "value": str(value)}
            raw[key] = {"kind": "rational", "value": str(value/unit)}
            typed[key] = {"type": "number", "value": rounded(value/unit)}
        else:
            economic[key] = raw[key] = {"kind": kind, "value": value}
            typed[key] = {"type": kind, "value": value}
    checks = {"passed": all(F(v)==0 for values in residuals.values() for v in values.values()), **{name:{key:str(v)for key,v in values.items()}for name,values in residuals.items()}, "group_membership": membership}
    if not checks["passed"]:
        raise ValueError("Independent forward ledger did not reconcile")
    return s.validate_result(public, {"kind": s.RESULT_KIND, "version":1,"specification_sha256":s.canonical_sha256(public),"economic_exact_values":economic,"raw_cell_exact_values":raw,"typed_2dp_values":typed,"cagr_proofs":proofs,"reconciliation_checks":checks})


def _residuals(checks, identity, period, row, previous):
    key = identity+"/"+period
    checks["quarter_balance_residuals"][key] = row["total_assets"]-row["total_liabilities_equity"]
    checks["cash_bridge_residuals"][key] = row["closing_cash"]-previous[0]-row["net_income"]+row["associate_income"]+row["dividend"]
    checks["investment_bridge_residuals"][key] = row["closing_investment"]-previous[1]-row["associate_income"]
    checks["retained_earnings_bridge_residuals"][key] = row["closing_retained_earnings"]-previous[2]-row["net_income"]+row["dividend"]


def _annual(rows, eligible):
    sales = [sum(r["revenue"] for r in rows[i:i+4]) for i in (0,4,8)]
    result=[]
    for year in range(3):
        row={field:sum(r[field] for r in rows[4*year:4*year+4]) for field in s.FLOWS}
        row.update({field:rows[4*year+3][field] for field in s.STOCKS})
        row["net_margin_percent"] = 100*row["net_income"]/row["revenue"]
        if year == 0:
            row.update({field:s.NA for field in ("yoy_percent","prior_year_multiple","prior_year_index","cagr_percent","annual_sales_delta")})
        else:
            ratio=sales[year]/sales[year-1]
            row.update(yoy_percent=100*(ratio-1),prior_year_multiple=ratio,prior_year_index=100*ratio,annual_sales_delta=sales[year]-sales[year-1],cagr_percent=(sales[year]/sales[0],year))
        row["distribution_eligible"] = s.GROUP_NA if eligible is None else bool(year == 2 and eligible)
        result.append(row)
    return result
