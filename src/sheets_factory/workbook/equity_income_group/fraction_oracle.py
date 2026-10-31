"""Independent exact-rational oracle for the synthetic equity-income group.

This implementation enumerates the complete tax-regime space. It does not
import the Decimal implementation, workbook formulas, or an Excel evaluator.
Financial state remains unrounded; ``display`` is the only rounding boundary.
"""
from fractions import Fraction

from .spec import ENTITY_METRICS, GROUP_METRICS, canonical_sha256, validate


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _fraction(value):
    _require(type(value) in (str, int, Fraction), "Use exact decimal strings, integers or Fractions")
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError("Invalid exact rational input") from error


def display(value):
    """Return two decimal places with exact round-half-up, including negatives."""
    value = _fraction(value)
    magnitude = abs(value) * 100
    whole, remainder = divmod(magnitude.numerator, magnitude.denominator)
    cents = whole + (2 * remainder >= magnitude.denominator)
    sign = "-" if value < 0 else ""
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def _solve_linear_system(matrix, rhs):
    """Solve a square rational system by exact pivoted Gauss-Jordan elimination."""
    size = len(rhs)
    rows = [list(matrix[i]) + [rhs[i]] for i in range(size)]
    for column in range(size):
        pivot = next((i for i in range(column, size) if rows[i][column] != 0), None)
        _require(pivot is not None, "A tax-regime system is singular")
        rows[column], rows[pivot] = rows[pivot], rows[column]
        divisor = rows[column][column]
        rows[column] = [item / divisor for item in rows[column]]
        for i in range(size):
            if i == column:
                continue
            factor = rows[i][column]
            if factor:
                rows[i] = [left - factor * right for left, right in zip(rows[i], rows[column])]
    solution = tuple(row[-1] for row in rows)
    _require(all(sum(matrix[i][j] * solution[j] for j in range(size)) == rhs[i]
                 for i in range(size)), "An exact tax-regime linear residual is nonzero")
    return solution


def solve_simultaneous(base_earnings, ownership, tax_rates, opening_losses):
    """Solve one quarter, testing all 2**N canonical active/inactive tax regimes.

    A regime is active precisely when pretax profit exceeds opening loss. At
    equality it is inactive, even at a zero tax rate, so one canonical regime
    remains. The row-sum bound makes every regime matrix nonsingular.
    """
    base = tuple(map(_fraction, base_earnings))
    rates = tuple(map(_fraction, tax_rates))
    losses = tuple(map(_fraction, opening_losses))
    weights = tuple(tuple(map(_fraction, row)) for row in ownership)
    size = len(base)
    _require(1 <= size <= 8 and len(rates) == len(losses) == len(weights) == size
             and all(len(row) == size for row in weights), "Complete bounded simultaneous dimensions required")
    _require(all(0 <= item <= 1 for item in rates) and all(item >= 0 for item in losses),
             "Tax rates or opening losses are outside their public domains")
    _require(all(weights[i][i] == 0 and all(value >= 0 for value in weights[i])
                 and sum(weights[i]) <= Fraction(35, 100) for i in range(size)),
             "Ownership needs zero diagonal and row sums at most .35")
    _require(all(sum(weights[i][j] for i in range(size)) <= 1 for j in range(size)),
             "An investee cannot have ownership above 100 percent")
    valid = []
    checks = []
    for mask in range(1 << size):
        active = tuple(bool(mask & (1 << i)) for i in range(size))
        slopes = tuple(1 - rates[i] if active[i] else Fraction(1) for i in range(size))
        matrix = tuple(tuple((Fraction(1) if i == j else Fraction(0)) - slopes[i] * weights[i][j]
                             for j in range(size)) for i in range(size))
        rhs = tuple(slopes[i] * base[i] + (rates[i] * losses[i] if active[i] else 0)
                    for i in range(size))
        net = _solve_linear_system(matrix, rhs)
        equity = tuple(sum(weights[i][j] * net[j] for j in range(size)) for i in range(size))
        pretax = tuple(base[i] + equity[i] for i in range(size))
        canonical = tuple(pretax[i] > losses[i] for i in range(size))
        accepted = canonical == active
        checks.append({"mask": mask, "linear_system_exact": True, "canonical_regime_matches": accepted})
        if accepted:
            taxable = tuple(max(Fraction(0), pretax[i] - losses[i]) for i in range(size))
            taxes = tuple(rates[i] * taxable[i] for i in range(size))
            closing_losses = tuple(max(Fraction(0), losses[i] - pretax[i]) for i in range(size))
            _require(all(net[i] == pretax[i] - taxes[i] for i in range(size)),
                     "An exact net-income fixed-point residual is nonzero")
            valid.append({"pretax_profit": pretax, "equity_income": equity, "taxable_profit": taxable,
                          "current_tax": taxes, "net_income": net, "closing_loss": closing_losses,
                          "tax_active": active, "mask": mask})
    _require(len(checks) == 1 << size and len(valid) == 1,
             "The complete tax-regime enumeration must have exactly one valid solution")
    answer = valid[0]
    answer["solver"] = {"method": "complete_exact_fraction_tax_regime_enumeration",
                        "regime_count": 1 << size, "regimes_checked": len(checks),
                        "valid_regime_count": len(valid), "valid_regime_mask": answer["mask"],
                        "canonical_tax_active": list(answer["tax_active"]),
                        "regime_checks": checks, "internal_rounding": False}
    return answer


def solve(specification):
    """Replay every scenario and quarter with exact independent Fraction state."""
    public = validate(specification)
    entities = public["entities"]
    ids = [entity["id"] for entity in entities]
    ownership = [[_fraction(item) for item in row] for row in public["ownership"]]
    rates = [_fraction(entity["tax_rate"]) for entity in entities]
    cases = []
    for scenario in public["scenarios"]:
        states = {entity["id"]: {key: _fraction(entity["opening_" + key])
                                 for key in ("cash", "ppe", "investment", "retained", "loss")}
                  for entity in entities}
        periods = []
        for offset, period in enumerate(public["periods"]):
            inputs = [{key: _fraction(value) for key, value in scenario["inputs"][eid][offset].items()}
                      for eid in ids]
            interest = [_fraction(entity["debt"]) * _fraction(entity["annual_interest_rate"]) / 4
                        for entity in entities]
            base = [row["revenue"] - row["cash_opex"] - row["depreciation"] - interest[i]
                    for i, row in enumerate(inputs)]
            simultaneous = solve_simultaneous(base, ownership, rates, [states[eid]["loss"] for eid in ids])
            rows = {}
            for i, entity in enumerate(entities):
                eid = entity["id"]
                opening, operating = states[eid], inputs[i]
                row = dict(operating)
                row.update({"interest": interest[i],
                            "operating_profit": operating["revenue"] - operating["cash_opex"] - operating["depreciation"],
                            "standalone_pretax": base[i], "opening_loss": opening["loss"],
                            "opening_cash": opening["cash"], "opening_ppe": opening["ppe"],
                            "opening_investment": opening["investment"], "opening_retained": opening["retained"],
                            "paid_in_capital": _fraction(entity["paid_in_capital"]), "debt": _fraction(entity["debt"])})
                for field in ("equity_income", "pretax_profit", "taxable_profit", "current_tax", "net_income", "closing_loss"):
                    row[field] = simultaneous[field][i]
                row["operating_cashflow"] = row["net_income"] - row["equity_income"] + row["depreciation"]
                row["closing_cash"] = row["opening_cash"] + row["operating_cashflow"] - row["capex"]
                row["closing_ppe"] = row["opening_ppe"] + row["capex"] - row["depreciation"]
                row["closing_investment"] = row["opening_investment"] + row["equity_income"]
                row["closing_retained"] = row["opening_retained"] + row["net_income"]
                row["assets"] = row["closing_cash"] + row["closing_ppe"] + row["closing_investment"]
                row["liabilities_and_equity"] = row["debt"] + row["paid_in_capital"] + row["closing_retained"]
                row["balance_residual"] = row["assets"] - row["liabilities_and_equity"]
                _require(all(row[field] >= 0 for field in ("closing_cash", "closing_ppe", "closing_investment")),
                         f"Negative ending cash, PPE or investment: {scenario['id']}/{period}/{eid}")
                _require(row["balance_residual"] == 0, f"Entity balance does not close: {scenario['id']}/{period}/{eid}")
                _require(set(row) == set(ENTITY_METRICS) and all(type(value) is Fraction for value in row.values()),
                         "The complete entity result must contain exact Fractions")
                rows[eid] = row
            def total(field):
                return sum((rows[eid][field] for eid in ids), Fraction(0))
            group = {field: total(field) for field in ("revenue", "cash_opex", "depreciation", "interest",
                      "standalone_pretax", "current_tax", "operating_cashflow", "capex", "opening_cash", "closing_cash", "closing_ppe", "debt")}
            group["entity_equity_income"] = total("equity_income")
            group["equity_income_elimination"] = -group["entity_equity_income"]
            group["reported_entity_net_income"] = total("net_income")
            group["external_net_income"] = group["reported_entity_net_income"] + group["equity_income_elimination"]
            group["entity_investments"] = total("closing_investment")
            group["investment_elimination"] = -group["entity_investments"]
            group["combined_capital"] = total("paid_in_capital") + total("closing_retained") + group["investment_elimination"]
            group["assets"] = group["closing_cash"] + group["closing_ppe"]
            group["liabilities_and_capital"] = group["debt"] + group["combined_capital"]
            group["balance_residual"] = group["assets"] - group["liabilities_and_capital"]
            group["profit_reconciliation_residual"] = group["external_net_income"] - (group["standalone_pretax"] - group["current_tax"])
            group["cash_reconciliation_residual"] = (group["closing_cash"] - group["opening_cash"]) - (group["operating_cashflow"] - group["capex"])
            _require(set(group) == set(GROUP_METRICS) and all(type(value) is Fraction for value in group.values()),
                     "The complete group result must contain exact Fractions")
            _require(all(group[field] == 0 for field in ("balance_residual", "profit_reconciliation_residual", "cash_reconciliation_residual")),
                     f"Management-group reconciliation failed: {scenario['id']}/{period}")
            periods.append({"period": period, "entities": rows, "group": group, "solver": simultaneous["solver"]})
            states = {eid: {field: rows[eid]["closing_" + field]
                            for field in ("cash", "ppe", "investment", "retained", "loss")} for eid in ids}
        cases.append({"id": scenario["id"], "periods": periods})
    return {"kind": "independent_fraction_equity_income_group", "version": 1,
            "specification_sha256": canonical_sha256(public), "scenario_order": [item["id"] for item in public["scenarios"]],
            "entity_order": ids, "period_order": list(public["periods"]), "scenarios": cases,
            "source_type": "new_synthetic", "actual_LO_calls": 0, "model_calls": 0, "qualified": False}
