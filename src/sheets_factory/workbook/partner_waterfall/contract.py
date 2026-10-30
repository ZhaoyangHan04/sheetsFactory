"""Public contract text. These are custom partnership terms, not market defaults."""

PUBLIC_RULES = (
    "All amounts are nominal GBP. The parent is a tax-transparent LP/GP partnership; partner-level tax is outside this scenario. Its opening £250,000 paid-in capital is contributed on 1 April 2023. Additional calls use the existing finite parent commitment, not a new funding source. Each opening or additional contribution is split by the stated LP capital fraction: round the LP amount to cents and assign the remainder to GP. Additional calls and all distributions are dated 31 March of the relevant FY; same-date partner cash flows are netted.",
    "The parent first pays its specified fees, interest, mandatory margin repayment and optional debt repayment, and completes any permitted draw and capital call. Only cash above its minimum cash reserve is distributable. The following four tiers use that available cash in order; no tier may borrow or draw additional capital to finance a distribution.",
    "Tier 1 pays LP's accrued unpaid preferred return. Each FY adds the stated annual preference rate times LP's opening unreturned capital, rounded to cents. Current-FY contributions earn no preference in that FY. Unpaid preference accumulates without compounding; neither unpaid preference nor GP capital earns preference. There is no first-year day-count proration.",
    "Tier 2 returns LP and GP capital pari passu in proportion to their respective unreturned capital after current-FY calls. Return the lesser of remaining cash and their combined unreturned capital. LP receives its proportion rounded to cents, capped at LP's unreturned capital, but at least the amount needed to avoid returning more than GP's unreturned capital; GP receives the residual. Neither partner's unreturned capital can become negative.",
    "Tier 3 pays only GP a catch-up. Let L and G be cumulative LP and GP profit distributions to date, including this FY's preference, excluding all returns of capital, and let c be the carry rate active for this FY. GP's additional catch-up entitlement is max(0, round((c*(L+G)-G)/(1-c), 2)); pay its lesser with remaining cash. Tier 4 divides all remaining cash at that carry rate: GP gets round(c*cash, 2), LP the residual. Preference, catch-up and residual amounts are profit distributions; return of capital is not profit.",
    "The initial carry rate applies until a permanent flip takes effect. At a FY end, after that FY's distributions, a flip is earned only if both partners' unreturned capital is zero and LP's dated net cash flows have exactly one sign change, from negative to positive, and LP's XIRR is at least the stated hurdle. Once earned, the higher stated carry rate starts in the NEXT FY and remains in force after any subsequent call. It does not change the triggering FY. Later catch-up uses the new rate against cumulative lifetime profit distributions; no prior LP payment is clawed back.",
    "LP net cash flows are minus contributions plus all LP distributions, including capital returns. XIRR uses actual elapsed days divided by 365 and an annual effective rate greater than -100%; zero dated net cash flows are ignored. A sequence with multiple sign changes, or without both signs, has no qualifying XIRR. With one negative-to-positive sign change the root is unique. Qualification uses unrounded XNPV at the hurdle (nonnegative qualifies), avoiding a display-rounding decision; displayed XIRR is rounded to 12 decimal places.",
    "Every posted monetary line is rounded to cents, halves away from zero; internal rates and products retain precision until the stated posting. Contributions increase parent paid-in capital, returns of capital reduce it, and profit distributions reduce retained earnings. Distributions are financing cash outflows, never expenses; parent net income and OCI are unchanged. Cash falls by total distributions and the resulting closing cash is next FY's opening cash. The programme continues at FY2043: remaining investments and partner capital are carried forward, with no assumed liquidation or final capital return.",
)

FINANCIAL_FIELDS = (
    'capital_called', 'distributable_cash', 'lp_contribution', 'gp_contribution',
    'lp_capital_open', 'gp_capital_open', 'preference_open', 'preference_accrual',
    'lp_preference', 'lp_return_of_capital', 'gp_return_of_capital', 'gp_catchup',
    'lp_residual', 'gp_residual', 'lp_distribution', 'gp_distribution',
    'capital_distribution', 'profit_distribution', 'total_distribution',
    'lp_capital_close', 'gp_capital_close', 'preference_close',
    'lp_cumulative_profit', 'gp_cumulative_profit', 'lp_net_cashflow',
    'gp_net_cashflow', 'lp_xirr',
)

# These explain execution state; they are provided rather than reconstruction targets.
PROVIDED_STATE_FIELDS = ('year', 'date', 'carry_rate', 'next_carry_rate', 'flip_earned',
                         'flip_effective_year', 'lp_sign_changes', 'lp_xirr_eligible',
                         'lp_last_nonzero_sign', 'hurdle_xnpv')
