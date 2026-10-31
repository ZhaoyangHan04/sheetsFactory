"""Independent Decimal business ledger for a new synthetic control prototype.

No workbook/formula parser, emitter, Excel engine, evaluator or official source is
imported. Values are not inserted into formula caches. This is a business oracle,
not evidence that a spreadsheet engine or a model has passed.
"""
from __future__ import annotations

from decimal import Decimal, localcontext


def _d(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Oracle assumptions require explicit decimal strings or integers")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("Oracle assumption must be finite")
    return result


def _text(value):
    return format(value, "f") if value else "0"


def compute(public, *, couple_controls=False, double_count_new_debt=False):
    """Compute every crossed state and retain the independent financing identity.

    Optional fault counterfactuals are pure business hypotheses, not workbook
    executions. All rows still identify the requested independent state pair.
    """
    if public.get("kind") != "synthetic_independent_controls_financial_candidate" or type(public.get("version")) is not int or public.get("version") != 1:
        raise ValueError("Explicit new synthetic assumptions required")
    operating, financing = public["operating"], public["financing"]
    if len(operating) != len(financing) or not 2 <= len(operating) <= 5:
        raise ValueError("Use two to five independent scenarios on each axis")
    if not 1 <= public["periods"] <= 6 or not 1 <= len(public["entities"]) <= 5:
        raise ValueError("Bounded entities and annual periods required")
    rows = []
    with localcontext() as context:
        context.prec = 50
        for entity in public["entities"]:
            for oi, operation in enumerate(operating):
                for fi, requested_finance in enumerate(financing):
                    finance = financing[oi] if couple_controls else requested_finance
                    revenue, cash, debt = (_d(entity[k]) for k in ("opening_revenue", "opening_cash", "opening_debt"))
                    cumulative_cures = Decimal(0)
                    for period in range(public["periods"]):
                        opening_revenue, opening_cash, opening_debt = revenue, cash, debt
                        revenue *= 1 + _d(operation["growth"])
                        ebitda = revenue * _d(operation["ebitda_margin"])
                        interest = opening_debt * _d(finance["interest_rate"])
                        tax = max(Decimal(0), ebitda - interest) * _d(entity["tax_rate"])
                        working_capital_change = (revenue - opening_revenue) * _d(entity["working_capital_fraction"])
                        mandatory = min(opening_debt, _d(entity["annual_principal"]))
                        before = opening_cash + ebitda - interest - tax - _d(entity["capex"][period]) - working_capital_change - mandatory
                        capacity = max(Decimal(0), _d(finance["facility_limit"]) - (opening_debt - mandatory))
                        draw = min(max(Decimal(0), _d(entity["minimum_cash"]) - before), capacity)
                        cure = max(Decimal(0), _d(entity["minimum_cash"]) - before - draw)
                        available = max(Decimal(0), before + draw + cure - _d(entity["minimum_cash"]))
                        sweep = min(opening_debt - mandatory + draw, available * _d(finance["sweep_fraction"]))
                        debt = opening_debt - mandatory + draw - sweep
                        cash = before + draw + cure - sweep
                        enterprise = max(Decimal(0), ebitda) * _d(entity["enterprise_multiple"])
                        residual = enterprise - debt + cash - (draw if double_count_new_debt else Decimal(0))
                        cumulative_cures += cure
                        values = dict(zip(
                            ("opening_revenue", "opening_cash", "opening_debt", "revenue", "ebitda", "interest", "cash_tax", "working_capital_change", "mandatory_principal", "cash_before_funding", "borrowing_capacity", "new_borrowing", "sponsor_cure", "cash_sweep", "closing_debt", "closing_cash", "enterprise_value", "residual_equity", "cumulative_sponsor_cures", "contribution_adjusted_residual"),
                            (opening_revenue, opening_cash, opening_debt, revenue, ebitda, interest, tax, working_capital_change, mandatory, before, capacity, draw, cure, sweep, debt, cash, enterprise, residual, cumulative_cures, residual - cumulative_cures)))
                        checks = {
                            "cash_floor": cash >= _d(entity["minimum_cash"]),
                            "debt_nonnegative": debt >= 0,
                            "draw_within_available_facility": 0 <= draw <= capacity,
                            "sweep_cannot_exceed_debt": 0 <= sweep <= opening_debt - mandatory + draw,
                            "cash_rollforward": cash == before + draw + cure - sweep,
                            "debt_rollforward": debt == opening_debt - mandatory + draw - sweep,
                        }
                        if not all(checks.values()):
                            raise ValueError("Independent ledger invariant failed")
                        rows.append({"entity": entity["id"], "operating": operation["id"], "financing": requested_finance["id"], "effective_financing": finance["id"], "year": public["first_year"] + period, "values": {k: _text(v) for k, v in values.items()}, "invariants": checks})
    return {"kind": "independent_controls_decimal_business_oracle", "version": 1,
        "rows": rows, "crossed_states": len(operating) * len(financing),
        "fault_counterfactual": {"coupled_controls": couple_controls, "double_counted_new_debt": double_count_new_debt},
        "workbook_formulas_evaluated": False, "formula_caches_written": False,
        "actual_LO_model_solver_Harbor_calls": 0, "source_financial_or_model_qualification": False}
