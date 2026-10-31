"""Public-policy schema. This module performs no financial calculations."""

from __future__ import annotations

import calendar
import copy
import hashlib
import json
from datetime import date
from pathlib import Path

SCALE = 10**12
MAX_MONEY = 10**11
MAX_INTEGER = 2**53
RATE_GRID = 10**6
SCENARIOS = ("S01", "S02", "S03")
LOAN_TYPES = ("BULLET_MONTHLY", "LEVEL_PRINCIPAL_MONTHLY", "BULLET_QUARTERLY_ACCRUAL")
TAX_POLICIES = ("ACCRUAL_MONTHLY", "CASH_COUPON_QUARTERLY")
DSCR_POLICIES = ("MONTHLY_CURRENT", "QUARTERLY_LAGGED")
PHASES = (
    "Opening states and effective terms",
    "Operating profit, assets, interest accrual, coupon and local principal",
    "Ordered shared-bank margin repayment",
    "Interest and loss FIFO, tax assessment and cash settlement, covenant test",
    "Reserve transfers and voluntary principal",
    "Ordered shared-bank drawings",
    "Finite entity and group LP contributions",
    "Permitted distributions and closing states",
    "Double-entry and group statement reconciliation",
)
RULES = (
    "The three scenarios reset independently; all amounts are GBP and no intramonth liquidity schedule is assumed. Month-end finance settles before the obligations it funds.",
    "Public amounts are GBP to two decimals and rates are percentages. Internal pence and exact rate numerators are calculation encodings, not additional assumptions.",
    "Interest is opening principal times the effective annual rate plus scenario spread times actual month days divided by 365 or 360. Round only the final monthly pence posting, halves away from zero. New month-end drawings first bear interest next month.",
    "Monthly bullet loans pay interest monthly and principal at maturity. Level-principal loans reset equal principal instalments on effective amendments, cannot draw again, and pay the remaining principal at maturity. Quarterly loans accrue monthly, pay all accrued interest on their stated coupon calendar and at maturity, and retain accrued balances when that calendar resets.",
    "The latest complete term effective at month opening governs that month. Maturity pays the outstanding principal and accrued interest and releases the opening reserve; no new drawing is permitted.",
    "Accrual-monthly tax uses accrued interest and pays tax monthly. Cash-coupon-quarterly tax uses cash coupon interest and pays accumulated tax at March, June, September and December ends. Both assess current tax monthly; no deferred tax, refunds, carryback or group relief is recognized.",
    "Old eligible denied interest uses EBITDA capacity FIFO before current interest. Old tax losses use positive taxable income FIFO. Expire an origin only when its age exceeds the stated carry months; a newly created origin is not usable in its creation month.",
    "CFADS is revenue less cash operating costs, cash tax and maintenance capex. Debt service is coupon cash plus all mandatory principal, excluding voluntary principal and new financing.",
    "Monthly-current covenants test the current month and immediately restrict a failure. Quarterly-lagged covenants test three months at March, June, September and December ends and affect the following month. Two consecutive observed passes clear a restriction next month; non-test months do not advance a cure.",
    "Only an active-at-opening facility is tested. The maturity month can report a test; subsequent closed months do not. For a zero debt-service denominator the ratio is blank and the test passes exactly when CFADS is nonnegative. On non-test months both ratio and pass result are blank, not missing work. Decisions use unrounded amounts.",
    "Restricted entities fund their reserve only from cash above minimum, sweep surplus to principal and pay no distributions. Other entities release reserve and use their stated voluntary repayment fraction. Transfers between restricted and unrestricted cash have no profit effect.",
    "Shared margin, bank drawings and limited LP contributions follow their separately stated entity priorities. Contributions cannot exceed either the entity's or the group's unused commitment. An unfunded minimum-cash shortfall is infeasible, not an implicit overdraft.",
    "Distributions cannot exceed cash above minimum or positive book equity. Return paid-in capital first; profit distributions reduce retained earnings. Neither changes net income.",
    "A fully repaid level-principal facility closes at month end and releases reserve next month. Closed facilities cannot reopen through an amendment. Other zero-balance committed facilities remain governed by their contract until maturity.",
    "The forecast ends with a balance-sheet snapshot. No unstated asset sale, debt acceleration, reserve release or use of unused capital occurs at that boundary.",
)

MONEY_FIELDS = tuple("""
revenue cash_opex ebitda capex_maintenance capex_growth depreciation ebit
interest_accrual cash_coupon current_tax_expense cash_tax net_income
cash_open reserve_open cash_before_financing reserve_locked reserve_released
cash_close reserve_close asset_nbv_open asset_nbv_close
principal_open scheduled_principal local_margin_principal shared_margin_principal
voluntary_principal bank_draw principal_close interest_payable_open interest_payable_close
tax_payable_open tax_payable_close eligible_current_interest interest_capacity
interest_carry_open interest_expired interest_old_used interest_current_allowed
interest_denied_created interest_carry_close taxable_before_losses
loss_open loss_expired loss_used loss_created loss_close taxable_after_losses
cfads mandatory_debt_service dscr_window_cfads dscr_window_debt_service
paid_in_open retained_open lp_call lp_called_cumulative distribution return_of_capital
profit_distribution paid_in_close retained_close total_assets total_liabilities total_equity
cfo cfi cff cash_delta funding_gap
cash_check restricted_cash_check principal_check interest_payable_check tax_payable_check
interest_queue_check loss_queue_check capital_check retained_check balance_sheet_check
""".split())
FLAG_FIELDS = ("test_applicable", "trap_open", "trap_operative", "trap_next", "facility_closed_open", "facility_closed_next")
NULLABLE_FIELDS = ("test_pass", "dscr_ratio_millionths")
ENTITY_FIELDS = ("month", "term_id", "tax_policy", "dscr_policy", *MONEY_FIELDS, *FLAG_FIELDS, *NULLABLE_FIELDS, "cure_open", "cure_next", "feasible")
LOAN_FIELDS = tuple("""month term_id principal_open annual_rate_p12 day_basis days interest_accrual
interest_payable_open coupon_due cash_coupon recast_due recast_instalment scheduled_principal
local_margin_principal shared_margin_principal voluntary_principal bank_draw principal_close
interest_payable_close facility_closed_open facility_closed_next""".split())
ASSET_FIELDS = ("month", "cost_open", "accumulated_depreciation_open", "nbv_open", "capex", "depreciation", "cost_close", "accumulated_depreciation_close", "nbv_close")
GROUP_SUM_FIELDS = tuple("""revenue cash_opex ebitda capex_maintenance capex_growth depreciation ebit
interest_accrual cash_coupon current_tax_expense cash_tax net_income cash_open reserve_open
reserve_locked reserve_released cash_close reserve_close asset_nbv_open asset_nbv_close
principal_open scheduled_principal local_margin_principal shared_margin_principal voluntary_principal
bank_draw principal_close interest_payable_open interest_payable_close tax_payable_open tax_payable_close
paid_in_open retained_open lp_call lp_called_cumulative distribution return_of_capital profit_distribution
paid_in_close retained_close total_assets total_liabilities total_equity cfo cfi cff cash_delta funding_gap""".split())
GROUP_FIELDS = ("month", "shared_bank_limit", "bank_used", "bank_headroom", "lp_commitment", "lp_calls_cumulative", "lp_unused", *GROUP_SUM_FIELDS, "group_cash_check", "group_bank_check", "group_equity_check", "group_balance_sheet_check", "feasible")


def canonical_sha256(specification: dict) -> str:
    return hashlib.sha256(json.dumps(specification, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def month_index(value: str) -> int:
    d = date.fromisoformat(value)
    if d.day != 1:
        raise ValueError("month must be an ISO month-start date")
    return d.year * 12 + d.month - 1


def _integer(value, name, low=0, high=MAX_MONEY):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"invalid integer {name}")


def _rate(value, name, low=0, high=SCALE):
    _integer(value, name, low, high)
    if value % RATE_GRID:
        raise ValueError(f"{name} does not round-trip the public rate grid")


def _keys(value, expected, name):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f"{name} keys differ from the declared contract")


def load_spec(raw: dict | str | Path) -> dict:
    s = copy.deepcopy(raw) if isinstance(raw, dict) else json.loads(Path(raw).read_text())
    if not isinstance(s, dict) or s.get("schema_version") != 1:
        raise ValueError("unsupported heterogeneous contract schema")
    modes = {"prototype_6_24_3": (6, 24), "candidate_12_60_3": (12, 60)}
    toy = s.get("dimension_mode") == "toy"
    if toy:
        n, periods = len(s["entities"]), len(s["months"])
        if not 1 <= n <= 3 or not 1 <= periods <= 3 or not 1 <= len(s["scenario_ids"]) <= 3:
            raise ValueError("toy dimensions exceed the explicit test contract")
    elif s.get("dimension_mode") not in modes:
        raise ValueError("unsupported dimension mode")
    else:
        n, periods = modes[s["dimension_mode"]]
    months = s["months"]
    if len(months) != periods or month_index(months[0]) % 12 or s["start_month"] != months[0]:
        raise ValueError("forecast must start in January with the declared full horizon")
    if [month_index(m) for m in months] != list(range(month_index(months[0]), month_index(months[0]) + periods)):
        raise ValueError("months are not consecutive")
    if s["scenario_ids"] != list(SCENARIOS[:len(s["scenario_ids"])]) or (not toy and len(s["scenario_ids"]) != 3) or s["currency"] != "GBP" or s["rate_scale"] != SCALE:
        raise ValueError("scenario, currency or rate scale mismatch")
    ids = [f"E{i:02d}" for i in range(1, n + 1)]
    if [e["id"] for e in s["entities"]] != ids:
        raise ValueError("entities must be ordered and complete")
    for e in s["entities"]:
        if e["functional_currency"] != "GBP" or e["tax_policy"] not in TAX_POLICIES or e["dscr_policy"] not in DSCR_POLICIES:
            raise ValueError("unsupported entity policy")
        for k in ("opening_cash_pence", "opening_restricted_cash_pence", "opening_paid_in_capital_pence", "opening_retained_earnings_pence", "opening_tax_payable_pence", "minimum_cash_pence", "reserve_target_pence", "additional_lp_commitment_pence"):
            _integer(e[k], k, -MAX_MONEY if k == "opening_retained_earnings_pence" else 0)
        for k in ("tax_rate_p12", "interest_cap_fraction_p12"):
            _rate(e[k], k)
        _rate(e["dscr_threshold_p12"], "DSCR threshold", 0, 5 * SCALE)
        for k in ("interest_carry_months", "loss_carry_months"):
            _integer(e[k], k, 1, 24)
        if type(e["opening_trap"]) is not bool:
            raise ValueError("opening_trap is a typed public boolean")
        _integer(e["opening_cure_count"], "opening cure", 0, 1)
        if not e["opening_trap"] and e["opening_cure_count"]:
            raise ValueError("unrestricted opening cure must be zero")
        if e["tax_policy"] == "ACCRUAL_MONTHLY" and e["opening_tax_payable_pence"]:
            raise ValueError("monthly-cash tax must open settled")
        for k in ("opening_interest_carry", "opening_tax_losses"):
            origins = []
            for v in e[k]:
                if set(v) != {"origin_month", "amount_pence"} or month_index(v["origin_month"]) >= month_index(months[0]):
                    raise ValueError("opening vintages must precede forecast")
                _integer(v["amount_pence"], "vintage", 1)
                origins.append(v["origin_month"])
            if origins != sorted(set(origins)):
                raise ValueError("opening vintage order or duplicate")
    if len(s["loans"]) != n or {l["entity_id"] for l in s["loans"]} != set(ids) or len({l["id"] for l in s["loans"]}) != n:
        raise ValueError("exactly one unique facility per entity is required")
    if not toy and set(l["type"] for l in s["loans"]) != set(LOAN_TYPES):
        raise ValueError("all three facility policies must be declared")
    for l in s["loans"]:
        _keys(l, ("id","entity_id","type","opening_principal_pence","opening_accrued_interest_pence","terms"), "loan")
        if l["type"] not in LOAN_TYPES:
            raise ValueError("unsupported loan type")
        for k in ("opening_principal_pence", "opening_accrued_interest_pence"):
            _integer(l[k], k)
        terms = l["terms"]
        dates = [t["effective_month"] for t in terms]
        if not dates or dates[0] != months[0] or dates != sorted(set(dates)) or any(d not in months for d in dates):
            raise ValueError("incomplete or unordered effective terms")
        for t in terms:
            _keys(t, ("id","effective_month","annual_rate_p12","day_count","local_limit_pence","maturity_date","draw_cutoff_month","optional_repayment_fraction_p12","next_coupon_month"), "effective term")
            if t["id"] != l["id"] + "@" + t["effective_month"]:
                raise ValueError("term identity mismatch")
            _rate(t["annual_rate_p12"], "annual rate")
            _integer(t["local_limit_pence"], "local limit")
            _rate(t["optional_repayment_fraction_p12"], "voluntary repayment fraction")
            if t["day_count"] not in ("ACT_365F", "ACT_360"):
                raise ValueError("unsupported day basis")
            md = date.fromisoformat(t["maturity_date"])
            if md.day != calendar.monthrange(md.year, md.month)[1] or t["maturity_date"] < t["effective_month"]:
                raise ValueError("maturity must be a future month end")
            if month_index(md.replace(day=1).isoformat()) > month_index(months[-1]) + 24:
                raise ValueError("maturity outside declared supported boundary")
            if l["type"] == "LEVEL_PRINCIPAL_MONTHLY":
                if t["draw_cutoff_month"] is not None:
                    raise ValueError("level principal cannot draw")
            elif t["draw_cutoff_month"] is None or month_index(t["draw_cutoff_month"]) < month_index(months[0]):
                raise ValueError("missing draw cutoff")
            if l["type"] == "BULLET_QUARTERLY_ACCRUAL":
                if t["next_coupon_month"] is None or month_index(t["next_coupon_month"]) < month_index(t["effective_month"]):
                    raise ValueError("invalid prospective coupon reset")
            elif t["next_coupon_month"] is not None:
                raise ValueError("monthly facility cannot carry a quarterly calendar")
        for before, after in zip(terms, terms[1:]):
            if after["effective_month"] > before["maturity_date"]:
                raise ValueError("a matured facility cannot be reopened by amendment")
    if len({a["id"] for a in s["assets"]}) != len(s["assets"]):
        raise ValueError("duplicate asset")
    for a in s["assets"]:
        if a["entity_id"] not in ids or a["capex_category"] not in ("MAINTENANCE", "GROWTH"):
            raise ValueError("invalid asset owner or capex category")
        month_index(a["commission_month"])
        _integer(a["original_cost_pence"], "asset cost", 1)
        _integer(a["opening_accumulated_depreciation_pence"], "opening depreciation", 0, a["original_cost_pence"])
        _integer(a["useful_life_months"], "asset life", 1, 600)
        if a["commission_month"] >= months[0] and a["opening_accumulated_depreciation_pence"]:
            raise ValueError("future asset has an opening book balance")
    for e in ids:
        rows = s["operating_inputs"][e]
        if [r["month"] for r in rows] != months:
            raise ValueError("incomplete operating input calendar")
        for r in rows:
            for k in ("base_cash_revenue_pence", "base_cash_opex_pence"):
                _integer(r[k], k)
    if [z["id"] for z in s["scenarios"]] != s["scenario_ids"]:
        raise ValueError("scenario order mismatch")
    for z in s["scenarios"]:
        if [r["month"] for r in z["monthly_schedule"]] != months:
            raise ValueError("incomplete scenario calendar")
        for r in z["monthly_schedule"]:
            for k in ("revenue_factor_p12", "opex_factor_p12"):
                _rate(r[k], k, 0, 3 * SCALE)
            _rate(r["annual_rate_spread_p12"], "spread", -SCALE // 5, SCALE // 5)
            for l in s["loans"]:
                t = max((t for t in l["terms"] if t["effective_month"] <= r["month"]), key=lambda t: t["effective_month"])
                if not 0 <= t["annual_rate_p12"] + r["annual_rate_spread_p12"] <= 6 * SCALE // 5:
                    raise ValueError("effective rate outside supported positive-rate contract")
    g = s["group"]
    for k in ("bank_funding_priority", "shared_margin_priority", "lp_funding_priority"):
        if len(g[k]) != n or set(g[k]) != set(ids):
            raise ValueError("priority is not a complete entity permutation")
    _integer(g["additional_lp_commitment_pence"], "group LP commitment")
    ds = [v["effective_month"] for v in g["shared_bank_limit_schedule"]]
    if not ds or ds[0] != months[0] or ds != sorted(set(ds)) or any(x not in months for x in ds):
        raise ValueError("invalid shared-bank limit calendar")
    for t in g["shared_bank_limit_schedule"]:
        _integer(t["limit_pence"], "group bank limit")
    return s
