"""Independent, cent-posted event ledger for the derived financing scenario.

This module deliberately does not read a workbook or use a spreadsheet/finance
library.  All accounts have debit-positive balances.  Income is closed to
retained earnings through balanced journal entries, never through a BS plug.
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Any


_ZERO = Decimal("0")
_ONE = Decimal("1")
_CENT = Decimal("0.01")
_TWELVE = Decimal("12")
_DEFAULTS: dict[str, Any] = {
    "months": 36,
    "start_date": "2027-01-01",
    "steady_annual_sales": "30000000",
    "annual_sales_growth": "0.04",
    "cash_cogs_fraction": "0.55",
    "construction_months": 6,
    "ramp_factors": ["0.5", "0.6", "0.75", "1", "1", "1"],
    "startup_expense": "2000000",
    "initial_asset_cost": "20000000",
    "initial_asset_service_month": 7,
    "initial_asset_life": 84,
    "refresh_capex": "1000000",
    "refresh_paid_month": 19,
    "refresh_service_month": 20,
    "refresh_life": 24,
    "residual": "0",
    "opening_cash": "3000000",
    "equity_paid_in": "8000000",
    "opening_retained": "0",
    "opening_nol": "0",
    "loan_a_principal": "12000000",
    "loan_a_amort_payments": 60,
    "loan_a_amort_start": 7,
    "loan_b_principal": "3000000",
    "loan_b_bullet_month": 36,
    "revolver_limit": "4000000",
    "minimum_cash": "500000",
    "cash_sweep_fraction": "0.5",
    "cash_allocation_start": 7,
    "tax_rate": "0.25",
    "nol_utilization_cap": "0.8",
    "dso": "45",
    "dio": "30",
    "dpo": "40",
    "exit_multiple": "4",
    "exit_fee_fraction": "0.01",
}
_REQUIRED_RESOLVED = (
    "cash_ebitda_margin",
    "annual_equity_discount_rate",
    "loan_a_annual_rate",
    "loan_b_annual_rate",
    "revolver_annual_rate",
)
_INCOME_ACCOUNTS = (
    "revenue", "cogs", "other_opex", "startup", "depreciation", "interest", "tax",
)
_FLOW_FIELDS = (
    "sales", "cogs", "other_opex", "startup_expense", "ebitda",
    "depreciation_initial", "depreciation_refresh", "depreciation", "ebit",
    "loan_a_interest", "loan_a_scheduled_principal", "loan_a_extra_principal",
    "loan_b_interest", "loan_b_principal", "revolver_interest", "revolver_draw",
    "revolver_repayment", "interest", "ebt", "tax", "nol_use", "nol_add",
    "net_income", "delta_ar", "delta_inventory", "delta_ap", "cfo_direct",
    "cfo_indirect", "capex", "cfi", "cff", "dividend", "owner_cashflow",
)
_OPEN_FIELDS = (
    "loan_a_open", "loan_b_open", "revolver_open", "nol_open", "ar_open",
    "inventory_open", "ap_open", "cash_open", "retained_open",
)
_CLOSE_FIELDS = (
    "loan_a_close", "loan_b_close", "revolver_close", "nol_close", "ar_close",
    "inventory_close", "ap_close", "cash_close", "asset_initial_gross",
    "asset_refresh_gross", "accumulated_depreciation", "net_ppe",
    "retained_close", "assets", "liabilities", "equity", "balance_check",
)


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number, not a boolean")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not number.is_finite():
        raise ValueError(f"{name} must be a finite number")
    return number


def _q(amount: Decimal) -> Decimal:
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def _integer(value: Any, name: str) -> int:
    number = _decimal(value, name)
    if number != number.to_integral_value():
        raise ValueError(f"{name} must be an integer")
    return int(number)


def _payment(principal: Decimal, monthly_rate: Decimal, periods: int) -> tuple[Decimal, Decimal]:
    """Solve the unrounded debt recurrence, then round the original payment.

    The terminal balance, rather than the closed-form annuity equation, is the
    objective.  In particular, interest is *not* rounded inside this solver.
    """
    if principal == 0:
        return _q(_ZERO), _ZERO

    def remaining(payment: Decimal) -> Decimal:
        balance = principal
        for _ in range(periods):
            balance = balance + balance * monthly_rate - payment
        return balance

    low, high = _ZERO, principal * (_ONE + monthly_rate)
    for _ in range(256):
        middle = (low + high) / 2
        if middle == low or middle == high:
            break
        if remaining(middle) > 0:
            low = middle
        else:
            high = middle
    theoretical = (low + high) / 2
    return _q(theoretical), remaining(theoretical)


def _present_value(flows: list[Decimal], monthly_rate: Decimal) -> Decimal:
    divisor = _ONE
    value = _ZERO
    for amount in flows:
        value += amount / divisor
        divisor *= _ONE + monthly_rate
    return value


def _irr(flows: list[Decimal]) -> tuple[Decimal | None, int]:
    """Find a unique conventional equity IRR through an NPV root.

    For nonconventional cash flows the ledger still reports NPV, but does not
    silently pick one of potentially multiple IRRs.
    """
    signs = [1 if amount > 0 else -1 for amount in flows if amount != 0]
    changes = sum(left != right for left, right in zip(signs, signs[1:]))
    if not signs or signs[0] >= 0 or changes != 1:
        return None, changes
    low, high = Decimal("-0.999999"), _ONE
    if _present_value(flows, low) <= 0:
        return None, changes
    for _ in range(128):
        if _present_value(flows, high) < 0:
            break
        high = high * 2 + 1
    else:
        return None, changes
    for _ in range(256):
        middle = (low + high) / 2
        if middle == low or middle == high:
            break
        if _present_value(flows, middle) > 0:
            low = middle
        else:
            high = middle
    return (low + high) / 2, changes


class _Book:
    def __init__(self, opening: dict[str, Decimal]) -> None:
        self.accounts = dict(opening)
        self.opening_trial_balance = dict(opening)
        self.journal: list[dict[str, Any]] = []
        self.events: list[tuple[int, str, str, Decimal]] = []
        self.entry_count = 0
        self.max_journal_error = _ZERO
        if sum(self.accounts.values(), _ZERO) != 0:
            raise ValueError("Opening assets, liabilities and contributed/retained equity do not balance")

    def get(self, account: str) -> Decimal:
        return self.accounts.get(account, _ZERO)

    def post(self, period: int, label: str, activity: str, debits: dict[str, Decimal]) -> None:
        entries = {account: _q(amount) for account, amount in debits.items()}
        error = abs(sum(entries.values(), _ZERO))
        self.max_journal_error = max(self.max_journal_error, error)
        if error:
            raise ArithmeticError(f"Unbalanced journal entry in period {period}: {label}")
        for account, amount in entries.items():
            self.accounts[account] = self.get(account) + amount
        self.journal.append({
            "period": period,
            "label": label,
            "activity": activity,
            "debit_positive_entries": dict(entries),
        })
        self.events.append((period, activity, label, entries.get("cash", _ZERO)))
        self.entry_count += 1

    def move(self, period: int, label: str, activity: str,
             debit: str, credit: str, amount: Decimal) -> None:
        amount = _q(amount)
        if amount:
            self.post(period, label, activity, {debit: amount, credit: -amount})

    def close_income(self, period: int) -> Decimal:
        original = {account: self.get(account) for account in _INCOME_ACCOUNTS}
        total = sum(original.values(), _ZERO)
        entries = {account: -amount for account, amount in original.items() if amount}
        entries["retained"] = total
        self.post(period, "Close monthly income", "noncash", entries)
        return -total

    def cash_flow(self, period: int, activity: str) -> Decimal:
        return sum((amount for event_period, kind, _, amount in self.events
                    if event_period == period and kind == activity), _ZERO)


def _parameters(spec: dict[str, Any]) -> dict[str, Any]:
    supplied = spec.get("parameters")
    if not isinstance(supplied, dict):
        raise ValueError("spec.parameters must be a dictionary")
    missing = [name for name in _REQUIRED_RESOLVED if name not in supplied]
    if missing:
        raise ValueError("Missing resolved parameters: " + ", ".join(missing))
    raw = {**_DEFAULTS, **supplied}
    integer_names = {
        "months", "construction_months", "initial_asset_service_month", "initial_asset_life",
        "refresh_paid_month", "refresh_service_month", "refresh_life", "loan_a_amort_payments",
        "loan_a_amort_start", "loan_b_bullet_month", "cash_allocation_start",
    }
    result = {name: _integer(raw[name], name) if name in integer_names else _decimal(raw[name], name)
              for name in set(_DEFAULTS) | set(_REQUIRED_RESOLVED)
              if name not in {"start_date", "ramp_factors"}}
    try:
        result["start_date"] = date.fromisoformat(str(raw["start_date"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("start_date must be an ISO calendar date") from exc
    if result["start_date"].month != 1 or result["start_date"].day != 1:
        raise ValueError("This 36-month calendar-year scenario must start on January 1")
    if result["months"] != 36:
        raise ValueError("This derived scenario requires exactly 36 months")
    if not isinstance(raw["ramp_factors"], (list, tuple)):
        raise ValueError("ramp_factors must be a list of finite numbers")
    result["ramp_factors"] = [_decimal(x, "ramp_factors") for x in raw["ramp_factors"]]
    for name in integer_names - {"months", "construction_months"}:
        if result[name] < 1:
            raise ValueError(f"{name} must be positive")
    if not 0 <= result["construction_months"] < result["months"]:
        raise ValueError("construction_months must be between zero and 35")
    fractions = ["cash_ebitda_margin", "cash_cogs_fraction", "cash_sweep_fraction", "tax_rate",
                 "nol_utilization_cap", "exit_fee_fraction"]
    for name in fractions:
        if not _ZERO <= result[name] <= _ONE:
            raise ValueError(f"{name} must be between zero and one")
    if result["cash_ebitda_margin"] + result["cash_cogs_fraction"] > 1:
        raise ValueError("Cash EBITDA margin plus cash COGS fraction cannot exceed one")
    for name in ("annual_sales_growth", "annual_equity_discount_rate"):
        if result[name] <= -1:
            raise ValueError(f"{name} must exceed minus one")
    nonnegative = ["steady_annual_sales", "startup_expense", "initial_asset_cost", "refresh_capex",
                   "opening_cash", "equity_paid_in", "opening_nol", "loan_a_principal",
                   "loan_b_principal", "revolver_limit", "minimum_cash", "loan_a_annual_rate",
                   "loan_b_annual_rate", "revolver_annual_rate", "dso", "dio", "dpo", "exit_multiple"]
    for name in nonnegative:
        if result[name] < 0:
            raise ValueError(f"{name} cannot be negative")
    if any(x < 0 for x in result["ramp_factors"]):
        raise ValueError("ramp_factors cannot be negative")
    if result["residual"] != 0:
        raise ValueError("This scenario specifies zero residual value")
    if result["construction_months"] == 0 and result["startup_expense"] != 0:
        raise ValueError("A positive startup expense requires construction months")
    if result["refresh_service_month"] < result["refresh_paid_month"]:
        raise ValueError("Refresh cannot enter service before it is acquired")
    return result


def simulate(spec: dict[str, Any]) -> dict[str, Any]:
    """Return independent monthly events, annual statements and equity value.

    Monetary postings and monetary outputs are Decimal cents with HALF_UP
    rounding.  Derived rates retain Decimal precision.  A funding shortfall is
    an explicit ValueError, not an artificially balanced result.
    """
    with localcontext() as context:
        context.prec = 60
        context.rounding = ROUND_HALF_UP
        p = _parameters(spec)
        return _simulate(p)


def _simulate(p: dict[str, Any]) -> dict[str, Any]:
    money = lambda name: _q(p[name])
    book = _Book({
        "cash": money("opening_cash"), "ar": _ZERO, "inventory": _ZERO,
        "initial_ppe": money("initial_asset_cost"), "refresh_ppe": _ZERO,
        "accumulated_depreciation": _ZERO, "ap": _ZERO, "tax_payable": _ZERO,
        "loan_a": -money("loan_a_principal"), "loan_b": -money("loan_b_principal"),
        "revolver": _ZERO, "paid_in": -money("equity_paid_in"),
        "retained": -money("opening_retained"),
    })
    rate_a, rate_b, rate_r = (p[name] / _TWELVE for name in
                            ("loan_a_annual_rate", "loan_b_annual_rate", "revolver_annual_rate"))
    payment, payment_residual = _payment(money("loan_a_principal"), rate_a, p["loan_a_amort_payments"])
    initial_monthly_dep = _q(money("initial_asset_cost") / p["initial_asset_life"])
    refresh_monthly_dep = _q(money("refresh_capex") / p["refresh_life"])
    startup_total = money("startup_expense")
    startup_monthly = (_q(startup_total / p["construction_months"])
                       if p["construction_months"] else _ZERO)
    startup_posted = initial_dep_posted = refresh_dep_posted = _ZERO
    nol = money("opening_nol")
    year_ebt = _ZERO
    rows: list[dict[str, Any]] = []
    minimum_cash = money("minimum_cash")
    limit = money("revolver_limit")
    cfo_errors: list[Decimal] = []
    cash_errors: list[Decimal] = []
    income_errors: list[Decimal] = []

    for period in range(1, p["months"] + 1):
        year = (period - 1) // 12 + 1
        month = (period - 1) % 12 + 1
        current_date = date(p["start_date"].year + year - 1, month, 1)
        days = calendar.monthrange(current_date.year, month)[1]
        cash_open, ar_open, inv_open = (book.get(a) for a in ("cash", "ar", "inventory"))
        ap_open, a_open, b_open, r_open = (-book.get(a) for a in ("ap", "loan_a", "loan_b", "revolver"))
        retained_open = -book.get("retained")
        nol_open = nol
        if month == 1:
            year_ebt = _ZERO

        operating_month = period - p["construction_months"]
        if operating_month <= 0:
            ramp = _ZERO
        elif operating_month <= len(p["ramp_factors"]):
            ramp = p["ramp_factors"][operating_month - 1]
        else:
            ramp = _ONE
        sales = _q(p["steady_annual_sales"] * (_ONE + p["annual_sales_growth"]) ** (year - 1)
                   / _TWELVE * ramp)
        cogs = _q(sales * p["cash_cogs_fraction"])
        other = _q(sales * (_ONE - p["cash_ebitda_margin"] - p["cash_cogs_fraction"]))
        startup = _ZERO
        if period <= p["construction_months"]:
            startup = (startup_total - startup_posted if period == p["construction_months"]
                       else startup_monthly)
            startup_posted += startup
        ar_target = _q(sales / days * p["dso"])
        inv_target = _q(cogs / days * p["dio"])
        ap_target = _q(cogs / days * p["dpo"])
        delta_ar, delta_inv, delta_ap = ar_target - ar_open, inv_target - inv_open, ap_target - ap_open
        book.move(period, "Accrue sales", "noncash", "ar", "revenue", sales)
        book.move(period, "Collect customer accounts", "operating", "cash", "ar", sales - delta_ar)
        book.move(period, "Inventory purchases on supplier account", "noncash", "inventory", "ap", cogs + delta_inv)
        book.move(period, "Recognise cost of goods sold", "noncash", "cogs", "inventory", cogs)
        book.move(period, "Pay suppliers", "operating", "ap", "cash", cogs + delta_inv - delta_ap)
        book.move(period, "Pay other operating expenses", "operating", "other_opex", "cash", other)
        book.move(period, "Pay startup expenses", "operating", "startup", "cash", startup)

        dep_initial = dep_refresh = _ZERO
        if period >= p["initial_asset_service_month"]:
            dep_initial = min(initial_monthly_dep, money("initial_asset_cost") - initial_dep_posted)
        capex = money("refresh_capex") if period == p["refresh_paid_month"] else _ZERO
        book.move(period, "Acquire refresh asset", "investing", "refresh_ppe", "cash", capex)
        if period >= p["refresh_service_month"]:
            dep_refresh = min(refresh_monthly_dep, book.get("refresh_ppe") - refresh_dep_posted)
        initial_dep_posted += dep_initial
        refresh_dep_posted += dep_refresh
        depreciation = dep_initial + dep_refresh
        book.move(period, "Depreciate initial asset", "noncash", "depreciation", "accumulated_depreciation", dep_initial)
        book.move(period, "Depreciate refresh asset", "noncash", "depreciation", "accumulated_depreciation", dep_refresh)
        interest_a, interest_b, interest_r = (_q(a_open * rate_a), _q(b_open * rate_b), _q(r_open * rate_r))
        for label, amount in (("Loan A cash interest", interest_a), ("Loan B cash interest", interest_b),
                              ("Revolver cash interest", interest_r)):
            book.move(period, label, "operating", "interest", "cash", amount)
        interest = interest_a + interest_b + interest_r
        ebitda = sales - cogs - other - startup
        ebit = ebitda - depreciation
        ebt = ebit - interest
        year_ebt += ebt
        tax = nol_use = nol_add = _ZERO
        if month == 12:
            positive_ebt = max(year_ebt, _ZERO)
            nol_use = min(nol, _q(positive_ebt * p["nol_utilization_cap"]))
            nol_add = max(-year_ebt, _ZERO)
            tax = _q((positive_ebt - nol_use) * p["tax_rate"])
            nol += nol_add - nol_use
            book.move(period, "Accrue annual current tax", "noncash", "tax", "tax_payable", tax)
            book.move(period, "Pay annual current tax", "operating", "tax_payable", "cash", tax)
        net_income = book.close_income(period)
        income_errors.append(abs(net_income - (ebt - tax)))

        sched_a = (min(a_open, max(_ZERO, payment - interest_a))
                   if period >= p["loan_a_amort_start"] else _ZERO)
        bullet_b = b_open if period == p["loan_b_bullet_month"] else _ZERO
        book.move(period, "Loan A scheduled principal", "financing", "loan_a", "cash", sched_a)
        book.move(period, "Loan B maturity principal", "financing", "loan_b", "cash", bullet_b)
        cash_before = book.get("cash")
        draw = repayment = extra_a = dividend = _ZERO
        gap = _ZERO
        if cash_before < minimum_cash:
            need = minimum_cash - cash_before
            draw = min(need, max(_ZERO, limit - r_open))
            gap = need - draw
            if gap:
                raise ValueError(f"Infeasible funding in period {period}: revolver shortfall {gap}")
            book.move(period, "Draw revolver for minimum cash", "financing", "cash", "revolver", draw)
        else:
            repayment = min(r_open, cash_before - minimum_cash)
            book.move(period, "Repay revolver from cash excess", "financing", "revolver", "cash", repayment)
        if period >= p["cash_allocation_start"]:
            excess = max(_ZERO, book.get("cash") - minimum_cash)
            extra_a = min(-book.get("loan_a"), _q(excess * p["cash_sweep_fraction"]))
            dividend = excess - extra_a
            book.move(period, "Sweep excess to loan A principal", "financing", "loan_a", "cash", extra_a)
            book.move(period, "Distribute remaining cash excess", "financing", "retained", "cash", dividend)

        cfo = book.cash_flow(period, "operating")
        cfi = book.cash_flow(period, "investing")
        cff = book.cash_flow(period, "financing")
        cfo_indirect = net_income + depreciation - delta_ar - delta_inv + delta_ap
        cash_close = book.get("cash")
        accumulated_dep = -book.get("accumulated_depreciation")
        net_ppe = book.get("initial_ppe") + book.get("refresh_ppe") - accumulated_dep
        assets = cash_close + book.get("ar") + book.get("inventory") + net_ppe
        liabilities = -sum((book.get(a) for a in ("ap", "loan_a", "loan_b", "revolver", "tax_payable")), _ZERO)
        equity = -book.get("paid_in") - book.get("retained")
        cfo_errors.append(abs(cfo - cfo_indirect))
        cash_errors.append(abs(cash_close - cash_open - cfo - cfi - cff))
        if (book.get("ar"), book.get("inventory"), -book.get("ap")) != (ar_target, inv_target, ap_target):
            raise ArithmeticError(f"Working-capital postings do not reconcile in period {period}")
        rows.append({
            "period": period, "year": year, "date": current_date.isoformat(), "month_days": days,
            "sales": sales, "cogs": cogs, "other_opex": other, "startup_expense": startup,
            "ebitda": ebitda, "depreciation_initial": dep_initial, "depreciation_refresh": dep_refresh,
            "depreciation": depreciation, "ebit": ebit, "loan_a_open": a_open,
            "loan_a_interest": interest_a, "loan_a_scheduled_principal": sched_a,
            "loan_a_extra_principal": extra_a, "loan_a_close": -book.get("loan_a"),
            "loan_b_open": b_open, "loan_b_interest": interest_b, "loan_b_principal": bullet_b,
            "loan_b_close": -book.get("loan_b"), "revolver_open": r_open,
            "revolver_interest": interest_r, "revolver_draw": draw, "revolver_repayment": repayment,
            "revolver_close": -book.get("revolver"), "interest": interest, "ebt": ebt,
            "tax": tax, "nol_open": nol_open, "nol_use": nol_use, "nol_add": nol_add,
            "nol_close": nol, "net_income": net_income, "ar_open": ar_open,
            "ar_close": book.get("ar"), "delta_ar": delta_ar, "inventory_open": inv_open,
            "inventory_close": book.get("inventory"), "delta_inventory": delta_inv,
            "ap_open": ap_open, "ap_close": -book.get("ap"), "delta_ap": delta_ap,
            "cash_open": cash_open, "cfo_direct": cfo, "cfo_indirect": cfo_indirect,
            "capex": capex, "cfi": cfi, "cff": cff, "cash_before_allocation": cash_before,
            "cash_gap": gap, "dividend": dividend, "cash_close": cash_close,
            "asset_initial_gross": book.get("initial_ppe"), "asset_refresh_gross": book.get("refresh_ppe"),
            "accumulated_depreciation": accumulated_dep, "net_ppe": net_ppe,
            "retained_open": retained_open, "retained_close": -book.get("retained"),
            "assets": assets, "liabilities": liabilities, "equity": equity,
            "balance_check": assets - liabilities - equity, "owner_cashflow": dividend,
        })

    next_sales = _q(p["steady_annual_sales"] * (_ONE + p["annual_sales_growth"]) ** 3)
    next_ebitda = _q(next_sales * p["cash_ebitda_margin"])
    enterprise_value = _q(next_ebitda * p["exit_multiple"])
    exit_fee = _q(enterprise_value * p["exit_fee_fraction"])
    closing = rows[-1]
    equity_exit = (enterprise_value + closing["cash_close"] - closing["loan_a_close"]
                   - closing["loan_b_close"] - closing["revolver_close"] - exit_fee)
    closing["owner_cashflow"] += equity_exit
    flows = [-money("equity_paid_in")] + [row["owner_cashflow"] for row in rows]
    monthly_discount = (_ONE + p["annual_equity_discount_rate"]) ** (_ONE / _TWELVE) - _ONE
    monthly_irr, sign_changes = _irr(flows)
    valuation = {
        "loan_a_payment": payment, "monthly_discount_rate": monthly_discount,
        "annual_discount_rate": p["annual_equity_discount_rate"], "next_annual_sales": next_sales,
        "next_ebitda": next_ebitda, "enterprise_value": enterprise_value, "exit_fee": exit_fee,
        "equity_exit": equity_exit, "owner_cashflows": flows,
        "equity_npv": _q(_present_value(flows, monthly_discount)),
        "monthly_equity_irr": monthly_irr,
        "annual_equity_irr": ((_ONE + monthly_irr) ** 12 - _ONE if monthly_irr is not None else None),
    }
    annual: list[dict[str, Any]] = []
    for year in range(1, 4):
        periods = rows[(year - 1) * 12:year * 12]
        first, last = periods[0], periods[-1]
        last_month = date.fromisoformat(last["date"])
        year_end = last_month.replace(day=calendar.monthrange(last_month.year, last_month.month)[1])
        record: dict[str, Any] = {
            "year": year, "start_date": first["date"], "end_date": year_end.isoformat(), "periods": 12,
        }
        record.update({key: sum((row[key] for row in periods), _ZERO) for key in _FLOW_FIELDS})
        record.update({key: first[key] for key in _OPEN_FIELDS})
        record.update({key: last[key] for key in _CLOSE_FIELDS})
        record["cash_before_allocation"] = last["cash_before_allocation"]
        record["cash_gap"] = sum((row["cash_gap"] for row in periods), _ZERO)
        annual.append(record)
    max_balance = max(abs(row["balance_check"]) for row in rows)
    checks = {
        "feasible": True, "all_balanced": max_balance == 0,
        "max_balance_error": max_balance, "max_cfo_reconciliation_error": max(cfo_errors),
        "max_cash_reconciliation_error": max(cash_errors), "max_income_reconciliation_error": max(income_errors),
        "minimum_cash_gap": max(_ZERO, minimum_cash - min(row["cash_close"] for row in rows)),
        "loan_a_payment_residual": payment_residual, "max_journal_error": book.max_journal_error,
        "journal_entry_count": book.entry_count, "irr_exists": monthly_irr is not None,
        "irr_sign_changes": sign_changes,
    }
    return {
        "monthly": rows,
        "annual": annual,
        "valuation": valuation,
        "checks": checks,
        "opening_trial_balance": book.opening_trial_balance,
        "journal": book.journal,
    }
