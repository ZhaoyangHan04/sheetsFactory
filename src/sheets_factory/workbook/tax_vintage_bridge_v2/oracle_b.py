"""Independent Fraction vintage queues and assessment-date cash journal."""
from copy import deepcopy
from fractions import Fraction
import re

from . import spec
from ..associate_bridge_v1 import oracle_b as bridge_b
from ..operating_reports_200 import schema

F = Fraction
MONEY = {"GBP": 1, "GBP_thousands": 1000, "GBP_millions": 1000000}
PERCENT = {"fraction": F(100), "percent_units": F(1), "basis_points": F(1, 100)}
MONETARY = set(schema.FLOWS + schema.STOCKS + schema.REPORTED +
    ("yoy_sales_delta", "qoq_sales_delta", "annual_sales_delta") + spec.NEW_FLOWS + spec.NEW_STOCKS + spec.LOT_FIELDS)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    require(type(value) is str and re.fullmatch(schema.DECIMAL_PATTERN, value) is not None,
            "Loss amounts require finite decimal strings")
    result = F(value)
    require(result >= 0, "Opening loss balances cannot be negative")
    return result


def validate(public):
    require(type(public) is dict and set(public) == {"kind", "case_id", "bridge", "tax_policies"}
        and public["kind"] == spec.KIND and public["case_id"] in spec.CASE_IDS, "Unknown tax-vintage specification")
    bridge = public["bridge"]
    require(bridge["case_id"] == spec.bridge_case(public["case_id"]), "The bridge case identity changed")
    entities = bridge["base"]["entities"]
    require(type(public["tax_policies"]) is dict and set(public["tax_policies"]) == {e["id"] for e in entities},
            "Each entity requires its own tax pools and assessment terms")
    for policy in public["tax_policies"].values():
        require(type(policy) is dict and set(policy) == {"opening_lots", "terms"}, "Unknown tax policy fields")
        lots = policy["opening_lots"]
        require(type(lots) is list and len(lots) == 4 and {lot["lot_id"] for lot in lots} == set(spec.LOT_IDS[:4]),
                "Four distinct opening vintages are required")
        for lot in lots:
            require(set(lot) == {"lot_id", "origin_index", "last_eligible_index", *spec.POOLS}
                and type(lot["origin_index"]) is int and lot["origin_index"] < 0
                and type(lot["last_eligible_index"]) is int, "Invalid opening vintage identity or eligibility")
            for pool in spec.POOLS:
                number(lot[pool])
        terms = policy["terms"]
        require(type(terms) is list and len(terms) == 2, "Both effective tax terms are required")
        for index, term in enumerate(terms):
            require(type(term) is dict and set(term) == {"effective_index", "ordinary_cap_bp", "investment_cap_bp", "carry_quarters", "cash_tax_lag"}
                and all(type(value) is int for value in term.values())
                and term["effective_index"] in ((0,) if index == 0 else (6, 8))
                and all(0 <= term[pool + "_cap_bp"] <= 10000 for pool in spec.POOLS)
                and term["carry_quarters"] in (4, 6, 8) and term["cash_tax_lag"] in (1, 2),
                "Invalid effective-quarter utilization, carry or payment terms")
    return bridge


def rounded(value):
    value = F(value)
    cents, remainder = divmod(abs(value.numerator) * 100, value.denominator)
    cents += int(2 * remainder >= value.denominator)
    return ("-" if value < 0 and cents else "") + f"{cents // 100}.{cents % 100:02d}"


def solve(public):
    bridge = validate(public)
    result = deepcopy(bridge_b.solve(bridge))
    economic = result["economic_exact_values"]
    base = bridge["base"]
    entities = {e["id"]: e for e in base["entities"]}
    units = {identity: (F(MONEY[e["money_unit"]]), PERCENT[e["rate_unit"]]) for identity, e in entities.items()}
    membership = {"DIV_" + division.upper(): [e["id"] for e in base["entities"] if e["division"] == division]
                  for division in base["divisions"]}
    membership["PORTFOLIO"] = list(entities)

    def old(identity, period, field):
        item = economic[f"{identity}/{period}/{field}"]
        require(item["kind"] == "rational", "Expected an unchanged exact bridge fact")
        return F(item["value"])

    checks = {"passed": True, "group_membership": membership,
        "opening_balance_residuals": {}, "quarter_balance_residuals": {}, "cash_bridge_residuals": {},
        "investment_bridge_residuals": {}, "retained_earnings_bridge_residuals": {},
        "loss_pool_rollforward_residuals": {}, "loss_utilization_cap_residuals": {},
        "fifo_priority_residuals": {}, "tax_payable_rollforward_residuals": {},
        "cash_tax_assessment_due_residuals": {}}
    records, openings, investment_deltas, eligibility, lot_reports = {}, {}, {}, {}, {}
    all_flows = schema.FLOWS + spec.NEW_FLOWS
    all_stocks = schema.STOCKS + spec.NEW_STOCKS

    for identity, entity in entities.items():
        money, percent = units[identity]
        opening = {key: F(value) * money for key, value in entity["opening"].items()}
        openings[identity] = opening
        tax_rate = F(entity["parent_tax_rate"]) * percent / 100
        tax_policy = public["tax_policies"][identity]
        investment_policy = bridge["policies"][identity]
        lots = {lot["lot_id"]: {"origin": lot["origin_index"], "expiry": lot["last_eligible_index"],
                   "ordinary": number(lot["ordinary"]) * money,
                   "investment": number(lot["investment"]) * money} for lot in tax_policy["opening_lots"]}
        assessments, rows, helper_rows = [], [], []
        changes = []
        previous_payable = F(0)
        for index, quarter in enumerate(spec.QUARTERS):
            term = max((t for t in tax_policy["terms"] if t["effective_index"] <= index),
                       key=lambda item: item["effective_index"])
            row = {field: old(identity, quarter, field) for field in schema.FLOWS + schema.STOCKS}
            receipt = F(investment_policy["cash_receipts"][quarter]) * money
            dividend_cash = receipt if investment_policy["receipt_kind"][quarter] == "dividend" else F(0)
            pool_base = {"ordinary": row["pretax_before_associate"],
                "investment": {"exempt": F(0), "recognized": row["associate_income"],
                               "cash_dividends": dividend_cash}[investment_policy["tax_class"]]}
            helpers = {field: F(0) for field in spec.LOT_FIELDS}
            current_lot = {"origin": index, "expiry": index + term["carry_quarters"]}
            for pool in spec.POOLS:
                start = sum(lot[pool] for lot in lots.values())
                expired = F(0)
                for lot in lots.values():
                    if lot["expiry"] < index:
                        expired += lot[pool]
                        lot[pool] = F(0)
                live = sum(lot[pool] for lot in lots.values() if lot["origin"] < index)
                capacity = max(F(0), pool_base[pool]) * term[pool + "_cap_bp"] / 10000
                allowance = min(live, capacity)
                remaining = allowance
                ordered = sorted(lots, key=lambda key: (lots[key]["origin"], key))
                for position, key in enumerate(ordered):
                    lot = lots[key]
                    if lot["origin"] >= index or lot["expiry"] < index:
                        continue
                    used = min(lot[pool], remaining)
                    lot[pool] -= used
                    remaining -= used
                    helpers[f"tax_lot_{key}_{pool}_used"] = used
                    if used:
                        older_left = sum(lots[k][pool] for k in ordered[:position]
                                         if lots[k]["origin"] < index <= lots[k]["expiry"])
                        require(older_left == 0, "A younger loss was used ahead of eligible older losses")
                require(remaining == 0, "FIFO consumption did not reach the permitted allowance")
                created = max(F(0), -pool_base[pool])
                current_lot[pool] = created
                closing = sum(lot[pool] for lot in lots.values()) + created
                row.update({"tax_" + pool + "_before_losses": pool_base[pool],
                    "tax_" + pool + "_after_losses": max(F(0), pool_base[pool] - allowance),
                    "loss_" + pool + "_expired": expired, "loss_" + pool + "_used": allowance,
                    "loss_" + pool + "_created": created, "loss_" + pool + "_close": closing})
                key = identity + "/" + quarter + "/" + pool
                residual = closing - start + expired + allowance - created
                require(residual == 0 and allowance <= capacity and allowance <= live, "Tax loss pool bridge failed")
                checks["loss_pool_rollforward_residuals"][key] = str(residual)
                checks["loss_utilization_cap_residuals"][key] = "0"
                checks["fifo_priority_residuals"][key] = "0"
            lots[f"C{index:02d}"] = current_lot
            for key, lot in lots.items():
                for pool in spec.POOLS:
                    helpers[f"tax_lot_{key}_{pool}_close"] = lot[pool]
            helper_rows.append(helpers)
            expense = tax_rate * (row["tax_ordinary_after_losses"] + row["tax_investment_after_losses"])
            # The immutable assessment ledger stores the due date chosen at birth.
            assessments.append({"assessment": index, "due": index + term["cash_tax_lag"], "amount": expense})
            paid = sum(item["amount"] for item in assessments if item["due"] == index)
            payable = sum(item["amount"] for item in assessments if item["due"] > index)
            residual = payable - previous_payable - expense + paid
            require(residual == 0, "The tax payable and locked assessment due dates do not reconcile")
            checks["tax_payable_rollforward_residuals"][identity + "/" + quarter] = str(residual)
            checks["cash_tax_assessment_due_residuals"][identity + "/" + quarter] = "0"
            previous_payable = payable
            core = row["pretax_before_associate"] - expense
            income = core + row["associate_income"]
            row.update(current_tax=expense, core_net_income=core, net_income=income,
                cash_tax_paid=paid, tax_payable_close=payable, dividend=F(0),
                operating_cash_flow=income - row["associate_income"] + receipt + expense - paid)
            previous_investment = old(identity, spec.QUARTERS[index - 1], "closing_investment") if index else opening["investment"]
            changes.append(row["closing_investment"] - previous_investment)
            rows.append(row)
        annual_income = sum(row["net_income"] for row in rows[8:])
        eligible = (annual_income > 0 and sum(row["revenue"] for row in rows[8:]) * 625
                    >= sum(row["revenue"] for row in rows[:4]) * 729
                    and rows[11]["revenue"] * 20 >= rows[7]["revenue"] * 21)
        eligibility[identity] = eligible
        rows[11]["dividend"] = annual_income / 5 if eligible else F(0)
        for index, row in enumerate(rows):
            prefix = rows[:index + 1]
            distributions = sum(q["dividend"] for q in prefix)
            cash = opening["cash"] + sum(q["operating_cash_flow"] for q in prefix) - distributions
            retained = opening["retained_earnings"] + sum(q["net_income"] for q in prefix) - distributions
            require(cash >= 0 and row["closing_investment"] >= 0, "The new tax contract requires undeclared funding")
            row.update(closing_cash=cash, closing_retained_earnings=retained,
                total_assets=cash + row["closing_investment"],
                total_liabilities_equity=opening["debt"] + opening["capital"] + retained + row["tax_payable_close"])
        records[identity], investment_deltas[identity], lot_reports[identity] = rows, changes, helper_rows

    for identity, members in membership.items():
        units[identity] = (F(1), F(1))
        openings[identity] = {field: sum(openings[e][field] for e in members)
            for field in ("cash", "investment", "debt", "capital", "retained_earnings")}
        records[identity] = [{field: sum(records[e][i][field] for e in members)
            for field in all_flows + all_stocks} for i in range(12)]
        investment_deltas[identity] = [sum(investment_deltas[e][i] for e in members) for i in range(12)]

    def put(identity, period, field, value):
        key = f"{identity}/{period}/{field}"
        value = F(value); money, percent = units[identity]
        raw = value / money if field in MONETARY else value / percent if field.endswith("_percent") else value
        economic[key] = {"kind": "rational", "value": str(value)}
        result["raw_cell_exact_values"][key] = {"kind": "rational", "value": str(raw)}
        result["typed_2dp_values"][key] = {"type": "number", "value": rounded(raw)}

    for identity, rows in records.items():
        opening = openings[identity]
        checks["opening_balance_residuals"][identity] = str(opening["cash"] + opening["investment"]
            - opening["debt"] - opening["capital"] - opening["retained_earnings"])
        require(checks["opening_balance_residuals"][identity] == "0", "Opening tax balance does not reconcile")
        for index, row in enumerate(rows):
            period = spec.QUARTERS[index]
            previous = rows[index - 1] if index else {"closing_cash": opening["cash"],
                "closing_investment": opening["investment"], "closing_retained_earnings": opening["retained_earnings"]}
            residuals = {"quarter_balance_residuals": row["total_assets"] - row["total_liabilities_equity"],
                "cash_bridge_residuals": row["closing_cash"] - previous["closing_cash"] - row["operating_cash_flow"] + row["dividend"],
                "investment_bridge_residuals": row["closing_investment"] - previous["closing_investment"] - investment_deltas[identity][index],
                "retained_earnings_bridge_residuals": row["closing_retained_earnings"] - previous["closing_retained_earnings"] - row["net_income"] + row["dividend"]}
            for name, residual in residuals.items():
                require(residual == 0, "Independent new-tax financial reconciliation failed: " + name)
                checks[name][identity + "/" + period] = str(residual)
            for field in all_flows + all_stocks:
                put(identity, period, field, row[field])
            put(identity, period, "net_margin_percent", row["net_income"] * 100 / row["revenue"])
            if identity in entities:
                sign = -1 if entities[identity]["statement_sign"] == "signed_contributions" else 1
                put(identity, period, "reported_current_tax", sign * row["current_tax"])
                for field, value in lot_reports[identity][index].items():
                    put(identity, period, field, value)
        for year_index, year in enumerate(spec.YEARS):
            quarters = rows[year_index * 4:year_index * 4 + 4];period = f"FY{year}"
            for field in all_flows:
                put(identity, period, field, sum(q[field] for q in quarters))
            for field in all_stocks:
                put(identity, period, field, quarters[-1][field])
            put(identity, period, "net_margin_percent", 100 * sum(q["net_income"] for q in quarters)
                / sum(q["revenue"] for q in quarters))
            if identity in entities:
                key = f"{identity}/{period}/distribution_eligible";value = eligibility[identity] if year == 2027 else False
                economic[key] = result["raw_cell_exact_values"][key] = {"kind": "boolean", "value": value}
                result["typed_2dp_values"][key] = {"type": "boolean", "value": value}
    expected = {key for key, _ in schema.points(base)}
    expected.update(f"{identity}/{period}/{field}" for identity in records
        for period in (*spec.QUARTERS, *(f"FY{y}" for y in spec.YEARS)) for field in spec.NEW_FLOWS + spec.NEW_STOCKS)
    expected.update(f"{identity}/{period}/{field}" for identity in entities for period in spec.QUARTERS for field in spec.LOT_FIELDS)
    require(all(set(result[layer]) == expected for layer in
        ("economic_exact_values", "raw_cell_exact_values", "typed_2dp_values")), "The complete new-tax output union changed")
    result.update(kind=spec.RESULT_KIND, specification_sha256=spec.canonical_sha256(public), reconciliation_checks=checks)
    return result
