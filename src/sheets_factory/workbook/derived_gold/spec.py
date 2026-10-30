"""Resolve documented public source anchors and explicit hypothetical inputs.

This module contains data extraction and contract validation only. Financial
forecast calculations belong to the separately implemented emitter and ledger.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import json
from pathlib import Path

import openpyxl


ANCHORS = {
    "revenue": ("Master Inputs Start here", "B18", "Current Revenues"),
    "ebit": ("Master Inputs Start here", "B12", "Current Operating Income"),
    "da": ("Master Inputs Start here", "B15", "Current Depreciation and Amortization"),
    "tax_rate": ("Master Inputs Start here", "B17", "Marginal tax rate benchmark"),
    "debt_rate": ("Master Inputs Start here", "B46", "Borrowing rate benchmark"),
    "equity_rate": ("Valuation Model", "D27", "Calculated cost of equity benchmark"),
    "growth": ("Master Inputs Start here", "B78", "Stable growth benchmark"),
}

PUBLIC_CONTRACT_VERSION = 4
COVENANT_CONTRACT_VERSION = 6
ADVANCED_TAX_CONTRACT_VERSION = 7
COVENANT_FIELDS = ("covenant_enabled", "covenant_first_test_month", "covenant_dscr_threshold",
                   "dsra_normal_payment_months", "dsra_trap_payment_months")
ADVANCED_TAX_FIELDS = ("advanced_tax_enabled", "initial_tax_rate_y1", "initial_tax_rate_y2",
                      "initial_tax_rate_y3", "refresh_tax_rate_y1", "refresh_tax_rate_y2",
                      "refresh_tax_rate_y3", "interest_deduction_ebitda_fraction",
                      "nol_carryforward_years")

RULES = [
    "This is a hypothetical project calibrated to a public workbook's cash EBITDA margin and rate benchmarks; it is not a forecast of that workbook's named company.",
    "All project money is nominal USD. Source company financial units are used only in dimensionless ratios. Derived benchmark ratios and annual rates are rounded to 12 decimal places. Treat each monetary line or scalar as a posted cent amount: round it half up to cents before another calculation uses it. Do not round intermediate products within that line unless another rule explicitly requires it. Keep derived monthly rates and IRR rates unrounded. The owner NPV convention is specified separately below. Standalone cost, expense, depreciation, interest, tax, capex, debt-draw, principal-payment, dividend and seller-fee lines use nonnegative magnitudes; accumulated depreciation is also positive and is deducted from gross assets. In particular the Cash Flow sheet's scheduled Loan A principal and Loan B principal helper rows are positive payment magnitudes. Net operating, investing and financing cash flows are signed: investing cash flow is negative capex, and financing cash flow is draws less repayments and distributions. Owner cash flow uses negative month-zero equity and positive distributions and sale proceeds. Annual summaries inherit these conventions.",
    "The project begins on January 1. The initial equipment and opening cash are funded before month 1 by the two initial loans and paid-in equity; do not charge the initial equipment a second time in forecast cash flow.",
    "Annualized steady sales grow each calendar year. Divide by 12 and apply the public monthly commissioning ramp. Before commissioning sales are zero. Other operating expense has fraction one minus cash COGS fraction minus cash EBITDA margin. Round sales, cash COGS and other operating expense separately, then subtract these posted expenses and startup expense from sales to obtain EBITDA. Additional startup expenses are spread across the construction months, with the last month receiving the cent residual.",
    "Receivables equal current monthly sales divided by that month's actual calendar days times DSO. Inventory and payables similarly use monthly cash COGS and DIO/DPO. Opening receivables, inventory and payables are zero. Each working-capital delta is closing balance minus opening balance, positive for an increase; the indirect cash flow subtracts increases in receivables and inventory and adds increases in payables.",
    "Each equipment vintage receives a full month of straight-line depreciation from its stated service month, with zero residual value. First round cost divided by useful-life months half up to cents to obtain the fixed monthly charge. Each month charge the smaller of that fixed charge and remaining undepreciated basis; charge zero once basis is exhausted. Do not use cumulative-schedule rounding to redistribute cents across months. The initial asset includes construction in progress before service. The refresh asset is paid in its payment month and depreciated only from its service month.",
    "Interest uses each facility's opening monthly balance times its nominal annual rate divided by 12 and is paid in cash once. Round each facility's interest to cents separately before adding total interest; do not first round the monthly rate. A same-month end draw starts accruing interest next month.",
    "Loan A pays interest only before its amortization start. Its original level payment is an ordinary end-of-month annuity based on the original principal, nominal annual rate divided by 12 and stated number of amortizing payments, rounded to cents; the first such payment is in its amortization-start month. At zero interest the level payment is original principal divided by the number of payments, rounded to cents. Early principal repayments shorten the term without re-amortizing. Scheduled principal is the smaller of opening principal and the nonnegative difference between the original cent-rounded payment and posted monthly interest. The last payment is capped at principal plus interest. Optional prepayment is additional principal after scheduled principal.",
    "Loan B pays monthly interest and its entire remaining principal in the stated bullet month. The revolving facility has a finite limit. Its draws and repayments occur at month end.",
    "Tax is recognized and paid only at each calendar year end, using that year's total pretax income. Losses add to NOL; positive annual income can use opening NOL only up to the stated fraction. Round that positive-income utilization cap to cents before taking the smaller of it and opening NOL. Compute and round cash tax on positive annual income after this posted NOL use. No NOL expires within the horizon. Interest is fully deductible. No deferred tax assets or liabilities are recognized in this simplified scenario; these are hypothetical rules, not a claim about current tax law.",
    "Cash before allocation is the cash balance after operations, cash interest, tax, refresh capex and scheduled principal, but before any revolver draw, revolver repayment, optional Loan A prepayment or dividend. Draw the revolver only to maintain minimum cash, subject to its limit. Cash gap means the remaining unmet minimum-cash shortfall after the permitted draw; it is not the funding requirement before that draw. Repay the revolver from excess cash before optional Loan A prepayment. Available excess is the cash remaining above minimum cash after revolver repayment, before optional prepayment and dividends. Optional prepayment and distributions begin only in the public allocation-start month. Round available excess times the sweep fraction to cents before capping optional prepayment at remaining Loan A principal; distribute all other excess. Unused sweep after Loan A is repaid is also distributed.",
    "Operating cash flow includes cash interest once; financing cash flow includes loan principal only, not the full level payment again. Financing cash flow also includes revolver draws, revolver repayments and dividend distributions, with inflows positive and payments negative. Retained earnings roll forward as prior retained earnings plus net income less dividends; never force the balance sheet to balance with a plug.",
    "At the horizon the owners sell their shares. Obtain next year's steady annual sales, its EBITDA using the cash EBITDA margin, and enterprise value using the stated EBITDA multiple in that order, rounding each named monetary result to cents. Seller fees equal enterprise value times exit_fee_fraction, rounded half up to cents; the fee base is enterprise value before adding cash or subtracting debt. Seller proceeds add closing cash to enterprise value and subtract all closing debt and these fees. Do not add a separate liquidation of working capital or equipment. Share-sale proceeds are owner cash flow outside the entity's accounts.",
    "Owner cash flow starts with negative paid-in equity at month zero, then dividends at each month end and the final share-sale proceeds at month 36 end. The annual discount rate is effective; monthly rate is (1+annual rate)^(1/12)-1, retained at full calculation precision. Discount month t's posted owner cash flow over t months for t=1 through 36. For owner NPV, sum those 36 unrounded discounted amounts and add the month-zero equity outflow exactly once, then round only the final total half up to cents. The monthly PV row displays each discounted amount rounded separately to cents; do not sum that rounded display row to calculate NPV. Use periodic monthly IRR and annualize it as (1+monthly IRR)^12-1.",
    "No additional inflation, foreign exchange, financing fees, interest capitalization, debt penalties, new equity injections or unlisted cash sources are assumed. In Annual Statements, each opening balance is the January opening value and each closing balance is the December closing value. Asset initial gross, asset refresh gross, accumulated depreciation, net PPE, assets, liabilities, equity and balance check are December snapshots. Cash before allocation is also the December pre-allocation snapshot. Every other monetary annual line is the sum of its twelve monthly amounts; in particular cash gap is the sum of monthly unmet shortfalls, not their maximum or the December value. Annual owner cash flow excludes the pre-forecast month-zero equity investment. These annual columns are summaries of posted monthly amounts, not a separate annual model.",
]


def covenant_parameters(config: dict) -> dict | None:
    """Validate an explicit opt-in contract, without computing a forecast."""
    c = config.get("covenant_parameters")
    if c is None:
        return None
    if not isinstance(c, dict) or set(c) != set(COVENANT_FIELDS):
        raise ValueError("Covenant opt-in requires exactly five explicit covenant parameters")
    values = {key: _decimal(value) for key, value in c.items()}
    for key in set(COVENANT_FIELDS) - {"covenant_dscr_threshold"}:
        if values[key] != values[key].to_integral_value():
            raise ValueError("Covenant period counts and enabled flag must be integers")
    if values["covenant_enabled"] not in (0, 1):
        raise ValueError("covenant_enabled must be numeric zero or one")
    first = values["covenant_first_test_month"]
    if not 3 <= first <= 36 or first % 3:
        raise ValueError("Covenant first test must be a quarter end from month 3 through 36")
    if not 0 <= values["covenant_dscr_threshold"] <= 100:
        raise ValueError("Covenant DSCR threshold must be between zero and 100")
    if not 0 <= values["dsra_normal_payment_months"] <= values["dsra_trap_payment_months"] <= 36:
        raise ValueError("DSRA coverage must satisfy 0 <= normal <= trapped <= 36")
    return dict(c)


def covenant_rules() -> list[str]:
    """The enabled contract replaces incompatible base allocation instructions."""
    rules = list(RULES)
    rules[1] += " DSRA funding, surplus release and support withdrawals use positive magnitudes; the net transfer to operating cash is release plus support minus funding. Covenant flags and streaks are integers, not money."
    rules[2] += " Opening DSRA cash, distribution lock and consecutive successful-test count are all zero. The segregated DSRA earns no interest. Operating cash means the original cash account and may be retained above minimum cash while owner distributions are blocked. Minimum cash applies only to operating cash, not DSRA cash."
    rules[8] += " The opt-in covenant inputs are in Scenario rows 55 through 59. Monthly cash available for debt service (CFADS) equals posted operating cash flow plus total posted cash interest minus refresh capex. Contractual debt service equals total cash interest on all three facilities plus Loan A scheduled principal plus Loan B bullet principal; it excludes revolver principal, optional prepayment, dividends and reserve transfers. Accumulate both from the first month of each calendar quarter. Test only at quarter ends on or after covenant_first_test_month. Required CFADS is quarter service times covenant_dscr_threshold rounded half up to cents; a test passes when quarter CFADS is at least that cent requirement. Zero service always passes, even with negative CFADS. Display DSCR rounded to six decimals, or numeric zero for zero service, but never use that displayed ratio for the decision. Non-test months carry state and streak unchanged. A failed test sets the distribution lock to one and resets consecutive passes to zero. A passed test increments the streak, capped at two; an existing lock clears only on the second consecutive passed test. Current closing state applies to this same month-end allocation. There is no loan acceleration, extra fee or automatic state reset at Loan A payoff. In every month, including non-test months and months before the first covenant test, quarter CFADS and quarter service are quarter-to-date sums from the first month of that calendar quarter through the current month inclusive, resetting in January, April, July and October. Calculate required CFADS and displayed DSCR from those quarter-to-date amounts every month. Test due is numeric one only for an eligible quarter end, otherwise zero. Test passed is numeric one only when test due is one and the stated coverage test passes; it is numeric zero in every other month, even if quarter-to-date coverage exceeds the threshold. Do not carry the prior test-passed flag. Opening lock and opening consecutive passes equal the preceding month's closing values, both zero in month one. On every passed eligible test the closing streak increments and caps at two even when the opening lock is already zero. In a non-test month, closing lock and streak equal their opening values."
    rules[10] = (
        "Cash before allocation is operating cash after CFO, refresh capex, Loan A scheduled principal and Loan B bullet principal, before DSRA transfers, revolver principal, optional prepayment and dividends. Before covenant_first_test_month the DSRA target is zero. Thereafter target is the smaller of Loan A opening principal less scheduled principal and the original cent-rounded Loan A payment times dsra_trap_payment_months when the current closing lock is one, otherwise dsra_normal_payment_months. Measure this target before optional principal and hold it for this month; optional payoff affects the next month's target, not the current target. Apply this exact priority: (1) release DSRA cash above target to operating cash; (2) transfer DSRA support to operating cash equal to the smallest of remaining DSRA cash, the operating minimum-cash shortfall and this month's contractual debt service; (3) draw the revolver for any remaining operating minimum-cash shortfall, capped at unused limit; (4) fund any DSRA target deficit from operating cash above minimum; (5) repay the opening revolver from remaining excess; (6) from the allocation-start month, prepay the stated sweep fraction of remaining excess, rounded to cents and capped at remaining Loan A principal; (7) distribute excess after optional prepayment only when allocation is allowed, the closing lock is zero and the DSRA funding shortfall is zero. Otherwise retain that cash in operating cash for later use. Optional prepayment is allowed while distributions are locked. Never draw merely to fund DSRA. DSRA shortfall is target less closing DSRA floored at zero and does not by itself cause default. Cash gap is the unmet operating minimum after reserve support and permitted revolver draw, not the reserve shortfall. Available excess is operating cash above minimum after DSRA transfers and revolver repayment but before optional prepayment and dividends. The Cash Flow sheet's optional-allocation-allowed flag is numeric one exactly from cash_allocation_start onward and zero before; it is independent of distribution lock and reserve shortfall and is not a distribution-permission flag."
    )
    rules[11] += " DSRA funding and withdrawals are balanced internal transfers between operating cash and DSRA cash; exclude them from CFO, CFI and CFF. Operating closing cash equals opening operating cash plus CFO plus CFI plus CFF plus net DSRA transfer to operating cash. Total closing cash includes operating and DSRA cash and equals opening total cash plus CFO plus CFI plus CFF. Include DSRA cash as a separate balance-sheet asset."
    rules[12] = rules[12].replace("Seller proceeds add closing cash to enterprise value", "Seller proceeds add closing operating cash and closing DSRA cash to enterprise value")
    rules[12] += " The buyer acquires the remaining DSRA cash asset at par with no restriction discount. Do not liquidate it into a separate owner dividend or change closing entity accounts because of the share sale; include it exactly once in the sale bridge after this month's ordinary covenant and allocation steps."
    rules[14] += " Annual operating-cash opening/closing fields retain their operating-cash meaning. The separate DSRA open and close fields use January opening and December closing values; DSRA funding, support and surplus release are monthly sums, and total cash close including DSRA is a December snapshot. Never sum covenant flags, streaks, ratios or reserve targets as annual money."
    return rules


def advanced_tax_parameters(config: dict, parameters: dict) -> dict | None:
    """Validate the optional stated tax contract without calculating a forecast."""
    tax = config.get("advanced_tax_parameters")
    if tax is None:
        return None
    if not isinstance(tax, dict) or set(tax) != set(ADVANCED_TAX_FIELDS):
        raise ValueError("Advanced tax requires exactly nine explicit parameters")
    values = {key: _decimal(value) for key, value in tax.items()}
    if values["advanced_tax_enabled"] not in (0, 1):
        raise ValueError("advanced_tax_enabled must be numeric zero or one")
    if values["nol_carryforward_years"] not in (1, 2):
        raise ValueError("nol_carryforward_years must be the integer one or two")
    for prefix in ("initial", "refresh"):
        rates = [values[f"{prefix}_tax_rate_y{year}"] for year in (1, 2, 3)]
        if any(rate < 0 or rate > 1 for rate in rates) or sum(rates) != 1:
            raise ValueError("Tax depreciation fractions must be nonnegative and sum exactly to one")
    if not 0 <= values["interest_deduction_ebitda_fraction"] <= 1:
        raise ValueError("Interest deduction fraction must be between zero and one")
    if values["advanced_tax_enabled"] and any(_decimal(parameters[key]) != 0 for key in ("opening_nol", "opening_retained")):
        raise ValueError("Advanced tax requires zero opening NOL and retained earnings")
    return dict(tax)


def advanced_tax_rules(rules: list[str]) -> list[str]:
    """Replace incompatible simple-tax clauses while retaining all other rules."""
    result = list(rules)
    result[1] = result[1].replace("interest, tax, capex", "interest, current cash tax, capex")
    result[1] += " Total book income-tax expense and deferred tax expense are signed; negative means a tax benefit. All NOL and interest-vintage helpers, tax depreciation, DTA and DTL are nonnegative magnitudes. Future vintage helpers are zero. Tax Vintages year columns contain posted cents, not ratios."
    result[9] = (
        "The advanced tax inputs are in Scenario rows 63 through 71. These are explicit hypothetical management-model rules, not tax law or accounting standards. Initial deferred tax, interest carry and tax depreciation are zero. Tax calculations and payments occur only at each December month end. Between December events, NOL, carried interest, DTA and DTL retain their last posted closing balances; there is no January write-off. Annual EBITDA, book depreciation and cash interest are sums of posted monthly amounts, and annual book EBT is EBITDA minus book depreciation minus cash interest. Tax Vintages reports model years 1, 2 and 3, not calendar dates. "
        "Tax depreciation uses each asset's calendar-year service vintage: in its first and second service calendar years deduct asset cost times the corresponding stated fraction, rounded to cents and capped at remaining tax basis; in its third service calendar year deduct all remaining basis to exhaust cent residuals. Use the full annual fraction in the first service year without monthly proration. Before service or after exhaustion charge zero. The initial cost is acquired at month zero; refresh cost enters tax basis only in its payment month, and pre-service cost remains in basis. Closing tax basis equals acquired cost less cumulative tax depreciation. Never deduct capex separately from taxable income. "
        "Annual interest capacity is positive annual EBITDA times interest_deduction_ebitda_fraction, rounded to cents. Deduct carried-interest vintages oldest first within capacity, then current-year cash interest within remaining capacity. Interest_cf_used includes old carry only; current_interest_deducted includes current-year interest only. Interest_deduction is their sum. Unused current cash interest creates the current-year interest carry vintage, which never expires in this horizon. Never deduct interest twice. "
        "Taxable_before_nol equals annual EBITDA minus tax depreciation minus allowed interest. At this December event first discard old NOL vintages whose current model year minus creation year exceeds nol_carryforward_years. Carry years one permits year-1 loss at year-2 December and expires it before year-3 use. Then use eligible old NOL vintages oldest first up to the smaller of their total and positive taxable_before_nol times nol_utilization_cap rounded to cents. A negative taxable_before_nol creates a current-year NOL; it is never used during its creation year. For each vintage, opening means last December's closing, zero in its creation year; current-year new loss or new carried interest enters only that vintage's closing. NOL closing equals opening less expiry less use plus new loss. Cash current tax is positive taxable income after NOL times tax rate, rounded to cents. "
        "Recognize gross deferred taxes in full without a valuation allowance or netting: DTA is the SUM of three separately cent-rounded components, closing NOL times tax rate, closing interest carry times tax rate, and positive closing tax basis minus book net PPE times tax rate. DTL is positive book net PPE minus tax basis times tax rate, rounded to cents. Deferred tax expense equals the change in DTL minus the change in DTA; total book income-tax expense equals cash current tax plus deferred tax expense. NOL expiry writes off the corresponding deferred benefit. Neither deferred tax nor book tax determines taxable income. Operations total book tax may therefore be negative. Tax year-to-date pretax income remains year-to-date BOOK EBT. Monthly Tax row 7 is current cash tax, row 8 NOL expiry, row 9 closing interest carry, row 10 signed deferred tax expense, row 11 closing DTA and row 12 closing DTL."
    )
    result[11] += " In advanced mode net income subtracts total book tax; direct CFO deducts current cash tax only. Indirect CFO adds the signed deferred tax expense back to net income, together with book depreciation and the stated working-capital bridge. The deferred adjustment is noncash; changes in gross DTA and DTL never enter CFO, CFI, CFF or the reserve waterfall as entity cash flows. Record DTA as a separate asset and DTL as a separate liability, with balanced noncash tax journal entries and no equity plug."
    result[12] += " The sale multiple already incorporates the purchaser's view of tax attributes: do not add DTA or subtract DTL again in the owner sale bridge."
    result[14] += " New annual advanced-tax lines sum current cash tax, signed deferred tax expense and NOL expiry; DTA, DTL and interest carry are December closing snapshots. The original annual tax line is total book tax. Tax Vintages depreciation and FIFO calculations are annual tax events; they do not replace the original monthly book depreciation."
    return result


def _decimal(value) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a financial number")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Scenario numbers must be finite")
    return result


def validate_parameters(p: dict) -> None:
    if p["months"] != 36 or date.fromisoformat(p["start_date"]).month != 1 or date.fromisoformat(p["start_date"]).day != 1:
        raise ValueError("Prototype requires 36 months starting January 1")
    if len(p["ramp_factors"]) != 6:
        raise ValueError("Prototype requires six explicit commissioning ramp factors")
    for key, value in p.items():
        if key == "start_date":
            continue
        if isinstance(value, list):
            for item in value:
                _decimal(item)
        else:
            _decimal(value)
    for key in ("loan_a_annual_rate", "loan_b_annual_rate", "revolver_annual_rate", "tax_rate", "nol_utilization_cap", "cash_sweep_fraction", "cash_cogs_fraction"):
        if not 0 <= _decimal(p[key]) <= 1:
            raise ValueError(f"Out-of-range rate or fraction: {key}")
    if not 0 < _decimal(p["cash_ebitda_margin"]) < 1 - _decimal(p["cash_cogs_fraction"]):
        raise ValueError("Cash EBITDA margin leaves negative other operating expense")
    if _decimal(p["annual_equity_discount_rate"]) <= -1:
        raise ValueError("Effective discount rate must exceed -1")
    for key in ("initial_asset_life", "refresh_life", "loan_a_amort_payments"):
        if int(p[key]) < 1:
            raise ValueError(f"Positive period count required: {key}")
    for key in ("steady_annual_sales", "initial_asset_cost", "opening_cash", "equity_paid_in", "revolver_limit", "minimum_cash"):
        if _decimal(p[key]) < 0:
            raise ValueError(f"Negative funding or asset input: {key}")
    funding = _decimal(p["equity_paid_in"]) + _decimal(p["opening_retained"]) + _decimal(p["loan_a_principal"]) + _decimal(p["loan_b_principal"])
    assets = _decimal(p["initial_asset_cost"]) + _decimal(p["opening_cash"])
    if funding != assets:
        raise ValueError("Initial balance sheet does not balance without a plug")


def resolve_spec(project_root: Path, config_path: Path) -> dict:
    config = json.loads(config_path.read_text())
    source = Path(config["source"]["local_path"])
    if not source.is_absolute():
        source = project_root / source
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != config["source"]["sha256"]:
        raise ValueError("Source SHA256 differs from the declared lineage")
    book = openpyxl.load_workbook(source, data_only=True, keep_links=False)
    anchors = {}
    for name, (sheet, cell, label) in ANCHORS.items():
        value = _decimal(book[sheet][cell].value)
        anchors[name] = {"sheet": sheet, "cell": cell, "label": label, "value": str(value)}
    book.close()
    p = dict(config["hypothetical_parameters"])
    precision = Decimal("0.000000000001")
    with localcontext() as ctx:
        ctx.prec = 60
        p["cash_ebitda_margin"] = str(((_decimal(anchors["ebit"]["value"]) + _decimal(anchors["da"]["value"])) / _decimal(anchors["revenue"]["value"])).quantize(precision, rounding=ROUND_HALF_UP))
        p["annual_sales_growth"] = anchors["growth"]["value"]
        p["tax_rate"] = anchors["tax_rate"]["value"]
        for facility in ("loan_a", "loan_b", "revolver"):
            p[facility + "_annual_rate"] = str((_decimal(anchors["debt_rate"]["value"]) + _decimal(p[facility + "_spread"])).quantize(precision, rounding=ROUND_HALF_UP))
        p["annual_equity_discount_rate"] = str((_decimal(anchors["equity_rate"]["value"]) + _decimal(p["equity_risk_premium"])).quantize(precision, rounding=ROUND_HALF_UP))
    validate_parameters(p)
    covenant = covenant_parameters(config)
    enabled = covenant is not None and _decimal(covenant["covenant_enabled"]) == 1
    tax = advanced_tax_parameters(config, p)
    tax_enabled = tax is not None and _decimal(tax["advanced_tax_enabled"]) == 1
    rules = covenant_rules() if enabled else list(RULES)
    if tax_enabled:
        rules = advanced_tax_rules(rules)
    return {
        "schema_version": 1, "public_contract_version": ADVANCED_TAX_CONTRACT_VERSION if tax_enabled else COVENANT_CONTRACT_VERSION if enabled else PUBLIC_CONTRACT_VERSION,
        "scenario_id": config["scenario_id"],
        "title": "Hypothetical project: commissioning, financing and equity returns",
        "status": "experimental_seed_not_a_qualified_task",
        "source_lineage": {"source_url": config["source"]["source_url"],
                           "download_url": config["source"]["download_url"],
                           "sha256": digest, "anchors": anchors,
                           "derivation": "Cash EBITDA margin = (unadjusted operating income + D&A) / revenue; reused as a hypothetical project benchmark, not as company-specific future facts."},
        "parameters": p, "covenant_parameters": covenant, "advanced_tax_parameters": tax,
        "public_rules": rules,
        "qualification": "No task or difficulty qualification. Every future task must pass all existing quality, recovery, Harbor and specified strong-agent difficulty gates.",
    }
