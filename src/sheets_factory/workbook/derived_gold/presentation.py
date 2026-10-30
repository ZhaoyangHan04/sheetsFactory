"""Project a public business brief without changing financial assumptions.

This module changes presentation only. It does not calculate a forecast, alter
input values or carry the longer full-contract text into the projected spec.
"""
from __future__ import annotations

from copy import deepcopy


BASE_BRIEF = (
    "This hypothetical project uses Scenario assumptions and source margin/rate benchmarks, without forecasting the source company. Money is nominal USD; round named monetary amounts half up to cents before reuse. Costs, payments, principal helpers and distributions are positive; net flows are signed. Book/deferred tax may be negative benefits.",
    "Opening funding buys initial equipment and cash before month one. Apply the stated commissioning ramp and calendar-year sales growth. Round sales and expenses separately. Startup expense spans construction months with final cent residual. Working capital uses actual calendar days; deltas are closing less opening.",
    "Book depreciation starts with a full service month: fixed cent-rounded cost/life charge capped at remaining basis, without cumulative-rounding redistribution. Refresh spending follows payment month. Cash interest uses opening balances, rounded separately per facility; draws accrue next month. Loan A retains its original cent-rounded ordinary-annuity payment after prepayment, with principal capped. Loan B repays at its bullet month.",
    "Cash gap is unmet operating minimum after permitted funding. Allocation begins at the stated month; sweep uses excess after revolving repayment, with unused sweep distributable after payoff. Retained earnings follow income less dividends; no plugs or unlisted financing.",
    "Share-sale EV uses next-year steady EBITDA and the multiple; fees apply to EV. Add closing cash and subtract debt once without separately liquidating other assets. Owners invest equity at month zero. Effective annual discounting converts monthly; NPV rounds the final unrounded discounted-flow sum, not monthly PV displays. Annualize periodic monthly IRR.",
    "Annual openings are January and stocks December; other amounts sum months. Cash before allocation is December's pre-allocation snapshot; cash gap sums monthly gaps. Annual owner flows exclude month-zero equity.",
)

COVENANT_BRIEF = (
    "Quarter-end tests start as stated. CFADS is cash CFO plus all interest less refresh spending; service covers all interest, scheduled Loan A and Loan B bullet principal. Compare quarter-to-date coverage against the cent-rounded requirement; zero service passes. Failure locks distributions/resets streak; two consecutive passes cure. The cure streak saturates at two. Non-tests carry state; initial lock/streak/reserve are zero without payoff resets.",
    "Reserve target is original payment times normal/trapped coverage, capped at Loan A after scheduled/before optional repayment, from first test using closing lock. Cash priority is surplus reserve release, support capped by operating shortfall/service, limited draw, reserve funding from excess, revolving repayment, sweep, then dividends if unlocked/fully funded. Sweep remains allowed while locked. Internal transfers separate operating/reserve/total cash; sale includes reserve once at par.",
)

SIMPLE_TAX_BRIEF = (
    "Tax is recognized and paid at December only. Annual book losses create NOL; positive income uses opening NOL up to the stated cent-rounded utilization fraction. NOL does not expire, interest is fully deductible, and there are no deferred taxes.",
)

ADVANCED_TAX_BRIEF = (
    "The tax assumptions are hypothetical. December tax events alone update NOL, interest carry and gross deferred balances; intervening months carry balances without January expiry. Opening attributes are zero. Tax depreciation uses full annual service-vintage fractions without first-year proration; the third service year exhausts remaining basis. Refresh cost enters basis when paid; pre-service cost remains in basis.",
    "Interest deductions use positive annual EBITDA's stated cent-rounded capacity: oldest carry first, then current interest; unused current interest carries without expiry. Taxable income uses EBITDA less tax depreciation and allowed interest. At December, expire NOL older than the stated carry years, then use eligible older vintages FIFO within the cent-rounded positive-income utilization cap. New losses enter their creation-year closing vintage only; future vintages are zero.",
    "Recognize gross DTA fully, without allowance or netting, from separately cent-rounded NOL, interest carry and positive tax-basis-over-book-PPE components; opposite basis differences create DTL. Deferred expense is the DTL change less DTA change. Book tax includes current cash tax and deferred expense; cash CFO deducts current tax only and indirect CFO adds deferred expense back. DTA/DTL are noncash assets/liabilities, with no additional owner-sale adjustment.",
)


def project_business_brief(spec: dict) -> dict:
    """Return a policy brief with unchanged inputs, lineage and financial rules."""
    result = deepcopy(spec)
    covenant = spec.get("covenant_parameters")
    tax = spec.get("advanced_tax_parameters")
    rules = list(BASE_BRIEF)
    if covenant is not None and int(covenant["covenant_enabled"]) == 1:
        rules.extend(COVENANT_BRIEF)
    if tax is not None and int(tax["advanced_tax_enabled"]) == 1:
        rules.extend(ADVANCED_TAX_BRIEF)
    else:
        rules.extend(SIMPLE_TAX_BRIEF)
    # This bound is part of the presentation contract, not a data truncation.
    if len(" ".join(rules).split()) > 600:
        raise ValueError("Business brief exceeds its 600-word presentation budget")
    result["public_rules"] = rules
    result["presentation_style"] = "business_brief"
    result["presentation_version"] = 2
    return result


def apply_public_presentation(spec: dict, style: str | None = None) -> dict:
    """Preserve absent/full behavior and reject unknown presentation names."""
    if style is None or style == "full":
        return spec
    if style == "business_brief":
        return project_business_brief(spec)
    raise ValueError(f"Unknown public presentation style: {style}")
