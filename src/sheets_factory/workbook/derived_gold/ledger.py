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


def _covenant_config(spec: dict) -> dict | None:
    raw = spec.get("covenant_parameters")
    if raw is None:
        return None
    names = {"covenant_enabled", "covenant_first_test_month", "covenant_dscr_threshold",
             "dsra_normal_payment_months", "dsra_trap_payment_months"}
    if not isinstance(raw, dict) or set(raw) != names:
        raise ValueError("Five explicit covenant parameters are required")
    c = {k: _decimal(v, k) if k == "covenant_dscr_threshold" else _integer(v, k)
         for k, v in raw.items()}
    if c["covenant_enabled"] not in (0, 1):
        raise ValueError("Covenant enabled flag must be zero or one")
    if not 3 <= c["covenant_first_test_month"] <= 36 or c["covenant_first_test_month"] % 3:
        raise ValueError("Covenant first test must be a quarter end")
    if not 0 <= c["covenant_dscr_threshold"] <= 100:
        raise ValueError("Covenant threshold is out of range")
    if not 0 <= c["dsra_normal_payment_months"] <= c["dsra_trap_payment_months"] <= 36:
        raise ValueError("Invalid reserve coverage")
    return c if c["covenant_enabled"] else None


def _advanced_tax_config(spec: dict, parameters: dict) -> dict | None:
    """Validate the optional tax contract without using emitter calculations."""
    raw = spec.get("advanced_tax_parameters")
    if raw is None:
        return None
    names = {"advanced_tax_enabled", "initial_tax_rate_y1", "initial_tax_rate_y2",
             "initial_tax_rate_y3", "refresh_tax_rate_y1", "refresh_tax_rate_y2",
             "refresh_tax_rate_y3", "interest_deduction_ebitda_fraction",
             "nol_carryforward_years"}
    if not isinstance(raw, dict) or set(raw) != names:
        raise ValueError("Nine explicit advanced tax parameters are required")
    integer_names = {"advanced_tax_enabled", "nol_carryforward_years"}
    tax = {name: (_integer(value, name) if name in integer_names else _decimal(value, name))
           for name, value in raw.items()}
    if tax["advanced_tax_enabled"] not in (0, 1):
        raise ValueError("Advanced tax enabled flag must be zero or one")
    if tax["nol_carryforward_years"] not in (1, 2):
        raise ValueError("NOL carryforward years must be one or two")
    for name in names - integer_names:
        if not _ZERO <= tax[name] <= _ONE:
            raise ValueError(f"{name} must be between zero and one")
    for asset in ("initial", "refresh"):
        if sum((tax[f"{asset}_tax_rate_y{year}"] for year in (1, 2, 3)), _ZERO) != _ONE:
            raise ValueError(f"{asset} tax depreciation fractions must sum exactly to one")
    if not tax["advanced_tax_enabled"]:
        return None
    if parameters["opening_nol"] != 0 or parameters["opening_retained"] != 0:
        raise ValueError("Advanced tax requires zero opening NOL and retained earnings")
    return tax


def _cyclic_financing_config(spec: dict, parameters: dict) -> dict | None:
    raw = spec.get("cyclic_financing_parameters")
    if raw is None:
        return None
    names = {"enabled", "bankcap", "target_dscr", "tranche"}
    if not isinstance(raw, dict) or set(raw) != names:
        raise ValueError("Cyclic financing requires exactly four explicit parameters")
    c = {name: _integer(value, name) if name == "enabled" else _decimal(value, name)
         for name, value in raw.items()}
    if c["enabled"] not in (0, 1):
        raise ValueError("Cyclic financing enabled flag must be zero or one")
    if any(c[name] <= 0 for name in ("bankcap", "target_dscr", "tranche")):
        raise ValueError("Cyclic financing limits, DSCR and tranche must be positive")
    if c["bankcap"] != _q(c["bankcap"]) or c["tranche"] != _q(c["tranche"]):
        raise ValueError("Cyclic financing amounts must be posted cents")
    if not c["enabled"]:
        return None
    gap = parameters["initial_asset_cost"] + parameters["opening_cash"] - parameters["loan_b_principal"]
    if c["bankcap"] > gap or c["tranche"] > c["bankcap"]:
        raise ValueError("Cyclic bank cap cannot exceed the opening equity funding gap")
    if (parameters["covenant"] or parameters["cash_sweep_fraction"] != 0
            or parameters["cash_allocation_start"] <= parameters["months"] or parameters["opening_retained"] != 0):
        raise ValueError("Certified cyclic prototype requires no covenant/sweep and allocation after the horizon")
    if int(c["bankcap"] // c["tranche"]) > 100000:
        raise ValueError("Cyclic financing tranche grid exceeds the independently certified bound")
    return c


class _AnnualTaxState:
    """Independent year-end vintage subledger; no workbook or forecast imports.

    Vintage balances are held between December postings.  This object performs
    no journal postings: the entity ledger posts its calculated current and
    deferred tax movements as separately balanced entries.
    """

    def __init__(self, parameters: dict, tax: dict) -> None:
        self.p, self.tax = parameters, tax
        self.nol = {year: _ZERO for year in (1, 2, 3)}
        self.interest = {year: _ZERO for year in (1, 2, 3)}
        self.depreciated = {"initial": _ZERO, "refresh": _ZERO}
        self.dta = self.dtl = _ZERO
        self.records: list[dict] = []
        self.checks = {"tax_vintage_rollforwards_ok": True, "tax_interest_capacity_ok": True,
                       "tax_nol_fifo_ok": True, "tax_interest_fifo_ok": True,
                       "tax_bridge_ok": True, "tax_depreciation_basis_ok": True}

    def _depreciation(self, asset: str, year: int) -> Decimal:
        p = self.p
        cost = _q(p["initial_asset_cost" if asset == "initial" else "refresh_capex"])
        service_month = p["initial_asset_service_month" if asset == "initial" else "refresh_service_month"]
        if asset == "refresh" and p["refresh_paid_month"] > year * 12:
            return _ZERO
        service_year = (service_month - 1) // 12 + 1
        age = year - service_year + 1
        remaining = cost - self.depreciated[asset]
        if age < 1 or age > 3:
            charge = _ZERO
        elif age == 3:
            charge = remaining
        else:
            charge = min(remaining, _q(cost * self.tax[f"{asset}_tax_rate_y{age}"]))
        self.depreciated[asset] += charge
        return charge

    @staticmethod
    def _fifo(balances: dict[int, Decimal], remaining: Decimal, year: int) -> dict[int, Decimal]:
        used = {vintage: _ZERO for vintage in (1, 2, 3)}
        for vintage in range(1, year):
            used[vintage] = min(balances[vintage], remaining)
            balances[vintage] -= used[vintage]
            remaining -= used[vintage]
        return used

    @staticmethod
    def _fifo_valid(opening: dict, excluded: dict, used: dict, year: int) -> bool:
        # If any newer old vintage is used, every eligible older vintage is
        # exhausted.  This invariant is separate from the consumption loop.
        return all(not used[newer] or all(opening[older] - excluded[older] - used[older] == 0
                                         for older in range(1, newer))
                   for newer in range(1, year))

    def close_year(self, year: int, *, ebitda: Decimal, book_depreciation: Decimal,
                   cash_interest: Decimal, book_net_ppe: Decimal,
                   acquired_cost: Decimal) -> dict:
        nol_open = dict(self.nol)
        interest_open = dict(self.interest)
        initial_dep = self._depreciation("initial", year)
        refresh_dep = self._depreciation("refresh", year)
        tax_dep = initial_dep + refresh_dep
        basis = acquired_cost - sum(self.depreciated.values(), _ZERO)
        capacity = _q(max(ebitda, _ZERO) * self.tax["interest_deduction_ebitda_fraction"])
        interest_used = self._fifo(self.interest, capacity, year)
        old_interest_used = sum(interest_used.values(), _ZERO)
        current_interest_deducted = min(cash_interest, capacity - old_interest_used)
        current_interest_carried = cash_interest - current_interest_deducted
        self.interest[year] += current_interest_carried
        deduction = old_interest_used + current_interest_deducted
        taxable_before = ebitda - tax_dep - deduction
        nol_expired = {vintage: _ZERO for vintage in (1, 2, 3)}
        for vintage in range(1, year):
            if year - vintage > self.tax["nol_carryforward_years"]:
                nol_expired[vintage] = self.nol[vintage]
                self.nol[vintage] = _ZERO
        positive_income = max(taxable_before, _ZERO)
        use_cap = _q(positive_income * self.p["nol_utilization_cap"])
        nol_used = self._fifo(self.nol, use_cap, year)
        use = sum(nol_used.values(), _ZERO)
        new_loss = max(-taxable_before, _ZERO)
        self.nol[year] += new_loss
        closing_nol = sum(self.nol.values(), _ZERO)
        closing_interest = sum(self.interest.values(), _ZERO)
        current_tax = _q((positive_income - use) * self.p["tax_rate"])
        dta_nol = _q(closing_nol * self.p["tax_rate"])
        dta_interest = _q(closing_interest * self.p["tax_rate"])
        dta_basis = _q(max(basis - book_net_ppe, _ZERO) * self.p["tax_rate"])
        dta = dta_nol + dta_interest + dta_basis
        dtl = _q(max(book_net_ppe - basis, _ZERO) * self.p["tax_rate"])
        deferred = (dtl - self.dtl) - (dta - self.dta)
        record = {
            "year": year, "ebitda": ebitda, "book_depreciation": book_depreciation,
            "cash_interest": cash_interest, "book_ebt": ebitda - book_depreciation - cash_interest,
            "initial_tax_depreciation": initial_dep, "refresh_tax_depreciation": refresh_dep,
            "tax_depreciation": tax_dep, "tax_basis_close": basis,
            "interest_capacity": capacity, "interest_cf_open": sum(interest_open.values(), _ZERO),
            "interest_cf_used": old_interest_used,
            "current_interest_deducted": current_interest_deducted,
            "current_interest_carried": current_interest_carried, "interest_deduction": deduction,
            "interest_cf_close": closing_interest, "taxable_before_nol": taxable_before,
            "nol_open": sum(nol_open.values(), _ZERO), "nol_expired": sum(nol_expired.values(), _ZERO),
            "nol_use_cap": use_cap, "nol_used": use, "nol_new": new_loss, "nol_close": closing_nol,
            "current_tax": current_tax, "book_net_ppe": book_net_ppe, "dta_nol": dta_nol,
            "dta_interest": dta_interest, "dta_basis": dta_basis, "dta_close": dta,
            "dtl_close": dtl, "deferred_tax_expense": deferred, "book_tax": current_tax + deferred,
        }
        for vintage in (1, 2, 3):
            record.update({f"nol_v{vintage}_open": nol_open[vintage],
                           f"nol_v{vintage}_expired": nol_expired[vintage],
                           f"nol_v{vintage}_used": nol_used[vintage],
                           f"nol_v{vintage}_close": self.nol[vintage],
                           f"interest_v{vintage}_open": interest_open[vintage],
                           f"interest_v{vintage}_used": interest_used[vintage],
                           f"interest_v{vintage}_close": self.interest[vintage]})
        self.checks["tax_vintage_rollforwards_ok"] &= all(
            self.nol[v] == nol_open[v] - nol_expired[v] - nol_used[v] + (new_loss if v == year else 0)
            and self.interest[v] == interest_open[v] - interest_used[v] + (current_interest_carried if v == year else 0)
            for v in (1, 2, 3))
        self.checks["tax_interest_capacity_ok"] &= (
            0 <= deduction <= capacity and 0 <= current_interest_deducted <= cash_interest
            and closing_interest == record["interest_cf_open"] + cash_interest - deduction)
        self.checks["tax_nol_fifo_ok"] &= self._fifo_valid(nol_open, nol_expired, nol_used, year)
        self.checks["tax_interest_fifo_ok"] &= self._fifo_valid(
            interest_open, {v: _ZERO for v in (1, 2, 3)}, interest_used, year)
        self.checks["tax_bridge_ok"] &= record["book_tax"] == current_tax + (dtl - self.dtl) - (dta - self.dta)
        self.checks["tax_depreciation_basis_ok"] &= basis >= 0 and all(
            _ZERO <= self.depreciated[asset] <= _q(self.p["initial_asset_cost" if asset == "initial" else "refresh_capex"])
            for asset in ("initial", "refresh"))
        self.dta, self.dtl = dta, dtl
        self.records.append(record)
        return record


def _covenant_state(lock: int, passes: int, due: bool, passed: bool) -> tuple[int, int]:
    if not due:
        return lock, passes
    if not passed:
        return 1, 0
    streak = min(2, passes + 1)
    return (int(lock and streak < 2), streak)


def _covenant_test(cfads: Decimal, service: Decimal, threshold: Decimal) -> tuple[Decimal, bool]:
    requirement = _q(service * threshold)
    return requirement, service == 0 or cfads >= requirement


def _reserve_waterfall(book: _Book, period: int, *, target: Decimal,
                       minimum: Decimal, service: Decimal, revolver_open: Decimal,
                       revolver_limit: Decimal, loan_a_remaining: Decimal,
                       sweep: Decimal, allocation_allowed: bool, locked: int) -> dict:
    """Post ledger events in contractual priority; no spreadsheet code is used."""
    reserve_open = book.get("dsra_cash")
    release = max(_ZERO, reserve_open - target)
    book.move(period, "Release surplus DSRA", "cash_transfer", "cash", "dsra_cash", release)
    support = min(book.get("dsra_cash"), max(_ZERO, minimum - book.get("cash")), service)
    book.move(period, "DSRA debt-service support", "cash_transfer", "cash", "dsra_cash", support)
    draw = min(max(_ZERO, minimum - book.get("cash")), max(_ZERO, revolver_limit - revolver_open))
    book.move(period, "Draw revolver for minimum cash", "financing", "cash", "revolver", draw)
    gap = max(_ZERO, minimum - book.get("cash"))
    if gap:
        raise ValueError(f"Infeasible funding in period {period}: revolver shortfall {gap}")
    funding = min(max(_ZERO, target - book.get("dsra_cash")), max(_ZERO, book.get("cash") - minimum))
    book.move(period, "Fund DSRA from operating excess", "cash_transfer", "dsra_cash", "cash", funding)
    repayment = min(revolver_open, max(_ZERO, book.get("cash") - minimum))
    book.move(period, "Repay revolver after DSRA funding", "financing", "revolver", "cash", repayment)
    excess = max(_ZERO, book.get("cash") - minimum)
    extra_a = min(loan_a_remaining, _q(excess * sweep)) if allocation_allowed else _ZERO
    book.move(period, "Sweep excess to loan A principal", "financing", "loan_a", "cash", extra_a)
    shortfall = max(_ZERO, target - book.get("dsra_cash"))
    dividend = excess - extra_a if allocation_allowed and not locked and not shortfall else _ZERO
    book.move(period, "Distribute permitted cash excess", "financing", "retained", "cash", dividend)
    return {"dsra_open": reserve_open, "dsra_target": target, "dsra_release": release,
            "dsra_support": support, "dsra_funding": funding, "dsra_close": book.get("dsra_cash"),
            "dsra_shortfall": shortfall, "dsra_net_transfer": release + support - funding,
            "revolver_draw": draw, "revolver_repayment": repayment, "cash_gap": gap,
            "loan_a_extra_principal": extra_a, "dividend": dividend, "allocation_excess": excess}


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
    result["covenant"] = _covenant_config(spec)
    result["advanced_tax"] = _advanced_tax_config(spec, result)
    result["cyclic_financing"] = _cyclic_financing_config(spec, result)
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
        return _simulate_cyclic(p) if p["cyclic_financing"] else _simulate(p)


def _unit_annuity_factor(rate: Decimal, periods: int) -> Decimal:
    """Unrounded unit payment, independently solved by the debt recurrence."""
    if rate == 0:
        return _ONE / periods
    low, high = _ZERO, _ONE + rate
    for _ in range(256):
        middle = (low + high) / 2
        if middle == low or middle == high:
            break
        balance = _ONE
        for _ in range(periods):
            balance = balance * (_ONE + rate) - middle
        if balance > 0:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def _simulate_cyclic(p: dict[str, Any]) -> dict[str, Any]:
    """Certify the entire finite underwriting grid, then post the full journal.

    The restricted prototype has no optional repayment, distributions or other
    facility feedback.  A reduced debt/current-tax recurrence is consequently
    exact. Every permitted tranche is examined for feasibility and fixed points;
    endpoint iteration alone is never presented as a uniqueness proof.
    """
    c = p["cyclic_financing"]
    tranche, cap = c["tranche"], (c["bankcap"] // c["tranche"]) * c["tranche"]
    funding_gap = _q(p["initial_asset_cost"] + p["opening_cash"] - p["loan_b_principal"])
    rate = p["loan_a_annual_rate"] / 12
    unit = _unit_annuity_factor(rate, p["loan_a_amort_payments"])
    factor = unit * 12
    def parameters_at(principal):
        return {**p, "cyclic_financing": None, "loan_a_principal": principal,
                "equity_paid_in": funding_gap - principal}
    base = _simulate(parameters_at(_ZERO))
    if any(row["revolver_open"] or row["revolver_draw"] for row in base["monthly"]):
        raise ValueError("The cyclic proof requires no revolving borrowing across the certified grid")
    advanced = p["advanced_tax"] is not None
    cash_tax_field = "current_tax" if advanced else "tax"
    gross_cfo = [row["cfo_direct"] + row[cash_tax_field] for row in base["monthly"]]
    annual_ebit = [sum((row["ebit"] for row in base["monthly"][i:i + 12]), _ZERO) for i in (0, 12, 24)]
    annual_b = [sum((row["loan_b_interest"] for row in base["monthly"][i:i + 12]), _ZERO) for i in (0, 12, 24)]
    gross_cfads = sum((row["cfo_direct"] + row["interest"] - row["capex"] for row in base["monthly"][24:]), _ZERO) + base["monthly"][-1][cash_tax_field]
    def project(principal):
        payment = _q(principal * unit)
        balance = principal
        interests, scheduled = [], []
        for period in range(1, 37):
            interest = _q(balance * rate)
            amort = min(balance, max(_ZERO, payment - interest)) if period >= p["loan_a_amort_start"] else _ZERO
            balance -= amort
            interests.append(interest)
            scheduled.append(amort)
        nol = _q(p["opening_nol"])
        taxes = []
        tax_state = _AnnualTaxState(p, p["advanced_tax"]) if advanced else None
        for year in range(3):
            cash_interest = annual_b[year] + sum(interests[year * 12:year * 12 + 12], _ZERO)
            if tax_state:
                yearly = base["monthly"][year * 12:year * 12 + 12]
                closing = yearly[-1]
                record = tax_state.close_year(year + 1,
                    ebitda=sum((row["ebitda"] for row in yearly), _ZERO),
                    book_depreciation=sum((row["depreciation"] for row in yearly), _ZERO),
                    cash_interest=cash_interest, book_net_ppe=closing["net_ppe"],
                    acquired_cost=closing["asset_initial_gross"] + closing["asset_refresh_gross"])
                taxes.append(record["current_tax"])
            else:
                ebt = annual_ebit[year] - cash_interest
                positive = max(ebt, _ZERO)
                use = min(nol, _q(positive * p["nol_utilization_cap"]))
                taxes.append(_q((positive - use) * p["tax_rate"]))
                nol += max(-ebt, _ZERO) - use
        cash = _q(p["opening_cash"])
        balances = []
        for index, row in enumerate(base["monthly"]):
            tax = taxes[index // 12] if (index + 1) % 12 == 0 else _ZERO
            cash += gross_cfo[index] - interests[index] - tax - row["capex"] - scheduled[index] - row["loan_b_principal"]
            balances.append(cash)
        cfads = gross_cfads - taxes[2]
        capacity = _q(max(cfads, _ZERO) / (c["target_dscr"] * factor))
        sized = (min(capacity, c["bankcap"]) // tranche) * tranche
        result = {"mapped": sized, "capacity": capacity, "cfads": cfads, "taxes": taxes,
                  "interest": interests, "scheduled": scheduled, "cash": balances}
        if tax_state:
            result["tax_annual"] = tax_state.records
        return result
    grid = {}
    fixed = []
    monotone = feasible = True
    previous = -tranche
    for index in range(int(cap / tranche) + 1):
        principal = tranche * index
        projection = project(principal)
        mapped = projection["mapped"]
        monotone &= mapped >= previous
        feasible &= min(projection["cash"]) >= p["minimum_cash"]
        grid[principal] = mapped
        if mapped == principal:
            fixed.append(principal)
        previous = mapped
    if not monotone or not feasible:
        raise ValueError("Cyclic financing grid is nonmonotone or requires unsupported revolving funding")
    if len(fixed) != 1:
        raise ValueError(f"Cyclic financing has {len(fixed)} fixed points; a unique reachable tranche is required")
    chosen = fixed[0]
    if not _ZERO < chosen < cap:
        raise ValueError("Cyclic financing must have an interior, genuinely capacity-limited principal")
    paths = []
    for start in (_ZERO, cap):
        path, visited = [start], {start}
        while grid[path[-1]] != path[-1]:
            following = grid[path[-1]]
            if following in visited or len(path) >= 10000:
                raise ValueError("Cyclic financing endpoint iteration cycles or fails to converge")
            path.append(following)
            visited.add(following)
        if path[-1] != chosen:
            raise ValueError("Cyclic financing endpoints reach different solutions")
        paths.append(path)
    adjacent_low, adjacent_high = project(chosen - tranche), project(chosen + tranche)
    tax_response = abs(adjacent_high["taxes"][2] - adjacent_low["taxes"][2])
    cfads_response = abs(adjacent_high["cfads"] - adjacent_low["cfads"])
    if tax_response == 0 or cfads_response == 0:
        raise ValueError("Cyclic financing lacks effective current-tax/CFADS feedback at the selected tranche")
    # Check the reduced projection against independently posted full journals at
    # both endpoints, the chosen tranche and its two neighbours.
    reports = {_ZERO: base}
    for principal in sorted({_ZERO, cap, chosen - tranche, chosen, chosen + tranche}):
        full = reports.setdefault(principal, None)
        if full is None:
            full = reports[principal] = _simulate(parameters_at(principal))
        projection = project(principal)
        for index, row in enumerate(full["monthly"]):
            cash_tax = projection["taxes"][index // 12] if (index + 1) % 12 == 0 else _ZERO
            if (row["loan_a_interest"] != projection["interest"][index]
                    or row["loan_a_scheduled_principal"] != projection["scheduled"][index]
                    or row[cash_tax_field] != cash_tax or row["cash_close"] != projection["cash"][index]
                    or row["revolver_open"] or row["revolver_draw"]):
                raise ArithmeticError("Reduced cyclic proof differs from the full independent financial journal")
        if advanced and full["tax_annual"] != projection["tax_annual"]:
            raise ArithmeticError("Reduced cyclic tax vintages differ from the full independent journal")
    result = reports[chosen]
    projection = project(chosen)
    result["debt_sizing"] = {"year3_cfads": projection["cfads"], "unit_monthly_payment_factor": unit,
        "annual_service_factor": factor, "target_dscr": c["target_dscr"],
        "debt_capacity": projection["capacity"], "bankcap": c["bankcap"],
        "sized_principal": chosen, "equity_paid_in": funding_gap - chosen,
        "year3_cash_tax": projection["taxes"][2], "principal_check": _ZERO, "funding_check": _ZERO}
    result["cyclic_financing_proof"] = {"grid_points_checked": len(grid), "fixed_points": fixed,
        "mapping_monotone": monotone, "all_tranches_feasible": feasible, "endpoint_paths": paths,
        "projection_full_journal_comparisons": len(reports), "principal_interior": True,
        "adjacent_tranche_year3_cash_tax_response": tax_response,
        "adjacent_tranche_year3_cfads_response": cfads_response}
    if advanced:
        result["cyclic_financing_proof"]["projection_tax_vintage_records_compared"] = len(reports) * 3
    result["checks"].update({"cyclic_financing_enabled": True, "cyclic_financing_unique_fixed_point": True,
        "cyclic_financing_endpoint_convergence": True, "cyclic_financing_grid_feasible": True,
        "cyclic_financing_tax_feedback": True, "cyclic_financing_projection_matches": True,
        "max_debt_sizing_error": _ZERO})
    return result


def _simulate(p: dict[str, Any]) -> dict[str, Any]:
    money = lambda name: _q(p[name])
    opening = {
        "cash": money("opening_cash"), "ar": _ZERO, "inventory": _ZERO,
        "initial_ppe": money("initial_asset_cost"), "refresh_ppe": _ZERO,
        "accumulated_depreciation": _ZERO, "ap": _ZERO, "tax_payable": _ZERO,
        "loan_a": -money("loan_a_principal"), "loan_b": -money("loan_b_principal"),
        "revolver": _ZERO, "paid_in": -money("equity_paid_in"),
        "retained": -money("opening_retained"),
    }
    covenant = p["covenant"]
    if covenant:
        opening["dsra_cash"] = _ZERO
    advanced_tax = p["advanced_tax"]
    tax_state = _AnnualTaxState(p, advanced_tax) if advanced_tax else None
    if tax_state:
        opening.update({"deferred_tax_asset": _ZERO, "deferred_tax_liability": _ZERO})
    book = _Book(opening)
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
    year_ebitda = year_depreciation = year_interest = _ZERO
    rows: list[dict[str, Any]] = []
    minimum_cash = money("minimum_cash")
    limit = money("revolver_limit")
    cfo_errors: list[Decimal] = []
    cash_errors: list[Decimal] = []
    income_errors: list[Decimal] = []
    total_cash_errors: list[Decimal] = []
    reserve_errors: list[Decimal] = []
    transfer_errors: list[Decimal] = []
    covenant_constraints: list[bool] = []
    lock, passes = 0, 0
    quarter_cfads = quarter_service = _ZERO

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
            year_ebitda = year_depreciation = year_interest = _ZERO

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
        year_ebitda += ebitda
        year_depreciation += depreciation
        year_interest += interest
        tax = nol_use = nol_add = _ZERO
        current_tax = deferred_tax = nol_expired = _ZERO
        if month == 12 and tax_state:
            old_dta, old_dtl = tax_state.dta, tax_state.dtl
            tax_record = tax_state.close_year(
                year, ebitda=year_ebitda, book_depreciation=year_depreciation,
                cash_interest=year_interest,
                book_net_ppe=(book.get("initial_ppe") + book.get("refresh_ppe")
                              + book.get("accumulated_depreciation")),
                acquired_cost=book.get("initial_ppe") + book.get("refresh_ppe"))
            current_tax, deferred_tax, tax = (tax_record[key] for key in
                                             ("current_tax", "deferred_tax_expense", "book_tax"))
            nol_use, nol_add, nol_expired, nol = (tax_record[key] for key in
                                                 ("nol_used", "nol_new", "nol_expired", "nol_close"))
            book.move(period, "Accrue annual current tax", "noncash", "tax", "tax_payable", current_tax)
            book.move(period, "Pay annual current tax", "operating", "tax_payable", "cash", current_tax)
            book.move(period, "Remeasure deferred tax asset", "noncash", "deferred_tax_asset", "tax",
                      tax_state.dta - old_dta)
            book.move(period, "Remeasure deferred tax liability", "noncash", "tax", "deferred_tax_liability",
                      tax_state.dtl - old_dtl)
        elif month == 12:
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
        cv = {}
        draw = repayment = extra_a = dividend = _ZERO
        gap = _ZERO
        if covenant:
            cfads = book.cash_flow(period, "operating") + interest - capex
            service = interest + sched_a + bullet_b
            if (month - 1) % 3 == 0:
                quarter_cfads = quarter_service = _ZERO
            quarter_cfads += cfads
            quarter_service += service
            required, measurement_passed = _covenant_test(quarter_cfads, quarter_service, covenant["covenant_dscr_threshold"])
            due = period >= covenant["covenant_first_test_month"] and period % 3 == 0
            passed = due and measurement_passed
            old_lock, old_passes = lock, passes
            lock, passes = _covenant_state(lock, passes, due, passed)
            coverage = covenant["dsra_trap_payment_months"] if lock else covenant["dsra_normal_payment_months"]
            target = min(a_open - sched_a, _q(payment * coverage)) if period >= covenant["covenant_first_test_month"] else _ZERO
            wf = _reserve_waterfall(book, period, target=target, minimum=minimum_cash,
                                   service=service, revolver_open=r_open, revolver_limit=limit,
                                   loan_a_remaining=a_open - sched_a, sweep=p["cash_sweep_fraction"],
                                   allocation_allowed=period >= p["cash_allocation_start"], locked=lock)
            draw, repayment = wf["revolver_draw"], wf["revolver_repayment"]
            extra_a, dividend, gap = wf["loan_a_extra_principal"], wf["dividend"], wf["cash_gap"]
            cv = {"cfads": cfads, "quarter_cfads": quarter_cfads, "contractual_service": service,
                  "quarter_service": quarter_service, "required_cfads": required,
                  "dscr_display": ((quarter_cfads / quarter_service).quantize(Decimal(".000001"), rounding=ROUND_HALF_UP) if quarter_service else _ZERO),
                  "test_due": int(due), "test_passed": int(passed), "lock_open": old_lock,
                  "passes_open": old_passes, "passes_close": passes, "lock_close": lock, **wf}
            covenant_constraints.append(
                (not dividend or (not lock and not wf["dsra_shortfall"] and period >= p["cash_allocation_start"]))
                and not (draw and repayment) and wf["dsra_support"] <= service
                and all(wf[k] >= 0 for k in ("dsra_open", "dsra_close", "dsra_release", "dsra_support", "dsra_funding"))
                and wf["dsra_funding"] <= max(_ZERO, cash_before + wf["dsra_release"] + wf["dsra_support"] + draw - minimum_cash))
            reserve_errors.append(abs(wf["dsra_close"] - wf["dsra_open"] + wf["dsra_net_transfer"]))
            transfer_errors.append(abs(book.cash_flow(period, "cash_transfer") - wf["dsra_net_transfer"]))
        elif cash_before < minimum_cash:
            need = minimum_cash - cash_before
            draw = min(need, max(_ZERO, limit - r_open))
            gap = need - draw
            if gap:
                raise ValueError(f"Infeasible funding in period {period}: revolver shortfall {gap}")
            book.move(period, "Draw revolver for minimum cash", "financing", "cash", "revolver", draw)
        else:
            repayment = min(r_open, cash_before - minimum_cash)
            book.move(period, "Repay revolver from cash excess", "financing", "revolver", "cash", repayment)
        if not covenant and period >= p["cash_allocation_start"]:
            excess = max(_ZERO, book.get("cash") - minimum_cash)
            extra_a = min(-book.get("loan_a"), _q(excess * p["cash_sweep_fraction"]))
            dividend = excess - extra_a
            book.move(period, "Sweep excess to loan A principal", "financing", "loan_a", "cash", extra_a)
            book.move(period, "Distribute remaining cash excess", "financing", "retained", "cash", dividend)

        cfo = book.cash_flow(period, "operating")
        cfi = book.cash_flow(period, "investing")
        cff = book.cash_flow(period, "financing")
        cfo_indirect = net_income + depreciation - delta_ar - delta_inv + delta_ap + deferred_tax
        cash_close = book.get("cash")
        reserve_close = book.get("dsra_cash") if covenant else _ZERO
        reserve_net = cv.get("dsra_net_transfer", _ZERO)
        accumulated_dep = -book.get("accumulated_depreciation")
        net_ppe = book.get("initial_ppe") + book.get("refresh_ppe") - accumulated_dep
        assets = (cash_close + reserve_close + book.get("ar") + book.get("inventory") + net_ppe
                  + book.get("deferred_tax_asset"))
        liabilities = -sum((book.get(a) for a in
                            ("ap", "loan_a", "loan_b", "revolver", "tax_payable", "deferred_tax_liability")), _ZERO)
        equity = -book.get("paid_in") - book.get("retained")
        cfo_errors.append(abs(cfo - cfo_indirect))
        cash_errors.append(abs(cash_close - cash_open - cfo - cfi - cff - reserve_net))
        if covenant:
            total_cash_errors.append(abs(cash_close + reserve_close - cash_open - cv["dsra_open"] - cfo - cfi - cff))
            cv["total_cash_close"] = cash_close + reserve_close
        if (book.get("ar"), book.get("inventory"), -book.get("ap")) != (ar_target, inv_target, ap_target):
            raise ArithmeticError(f"Working-capital postings do not reconcile in period {period}")
        tax_fields = ({"current_tax": current_tax, "deferred_tax_expense": deferred_tax,
                       "dta_close": tax_state.dta, "dtl_close": tax_state.dtl,
                       "nol_expired": nol_expired,
                       "interest_cf_close": sum(tax_state.interest.values(), _ZERO)} if tax_state else {})
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
            "balance_check": assets - liabilities - equity, "owner_cashflow": dividend, **cv, **tax_fields,
        })

    next_sales = _q(p["steady_annual_sales"] * (_ONE + p["annual_sales_growth"]) ** 3)
    next_ebitda = _q(next_sales * p["cash_ebitda_margin"])
    enterprise_value = _q(next_ebitda * p["exit_multiple"])
    exit_fee = _q(enterprise_value * p["exit_fee_fraction"])
    closing = rows[-1]
    equity_exit = (enterprise_value + closing["cash_close"] + closing.get("dsra_close", _ZERO) - closing["loan_a_close"]
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
        if covenant:
            record.update({"dsra_open": first["dsra_open"], "dsra_close": last["dsra_close"],
                           "total_cash_close": last["total_cash_close"]})
            record.update({key: sum((row[key] for row in periods), _ZERO)
                           for key in ("dsra_funding", "dsra_support", "dsra_release")})
        if tax_state:
            record.update({key: sum((row[key] for row in periods), _ZERO)
                           for key in ("current_tax", "deferred_tax_expense", "nol_expired")})
            record.update({key: last[key] for key in ("dta_close", "dtl_close", "interest_cf_close")})
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
    if covenant:
        checks.update({"covenant_enabled": True, "covenant_constraints_ok": all(covenant_constraints),
                       "max_total_cash_reconciliation_error": max(total_cash_errors),
                       "max_reserve_reconciliation_error": max(reserve_errors),
                       "max_transfer_reconciliation_error": max(transfer_errors)})
    if tax_state:
        checks.update({"advanced_tax_enabled": True, **tax_state.checks})
    result = {
        "monthly": rows,
        "annual": annual,
        "valuation": valuation,
        "checks": checks,
        "opening_trial_balance": book.opening_trial_balance,
        "journal": book.journal,
    }
    if tax_state:
        result["tax_annual"] = tax_state.records
    return result
