# Heterogeneous debt and tax contracts — prototype contract v1

Status: design only. No forward result, source workbook, feasibility claim, oracle, quality result, or difficulty result exists. `config/heterogeneous_contracts/prototype_v1.json` is a PRIVATE construction configuration; neither its JSON nor an executable reader/join map is an agent-facing artifact.

## 1. Fixed scope and APIs

First source: six GBP legal entities, January 2027–December 2028 (24 calendar months), three independent scenarios. Each entity has one external bank facility and two operating assets. The three facility types each occur twice, crossed with two tax policies and two covenant policies. Group bank capacity and group/individual limited equity commitments connect otherwise separate entity closes. All monthly operating/financing settlements occur at month end; provisional negative cash used to size finance is not an authorized overdraft. Finance receipts settle before the closing obligations they fund. Only a fully funded month-end close is feasible; no intramonth liquidity claim is made without an intramonth schedule. No FX, intercompany loans, optimization, deferred tax, receivables, or working-capital timing is added to this first prototype. Revenue and operating costs are collected/paid in their stated month.

A prospective later dimension is twelve entities × sixty months × the same three scenarios, using the same policies with distinct contracts, amendment dates and business profiles. It is not generated or executed by this design. More cells are not a difficulty claim.

Planned interfaces (not implemented):

```python
load_spec(raw: dict | Path) -> dict  # strict private schema, raw primitives only
simulate(specification: dict) -> dict  # independent Decimal forward journal; no search
emit_heterogeneous_workbook(book, specification, *, max_formulas, allow_production=False) -> bindings
expected_values(specification, result, bindings) -> mapping  # private field/scale/type projection
```

The Excel implementation must not import the Decimal ledger or its financial helpers. The builder/auditor consumes their separate outputs. Business assumptions appear as ordinary native tables and short legal-policy notes. Private bindings may contain machine paths. Nothing publishes a complete prejoined JSON copy, row-path dictionary or recovery program.

## 2. Units, dates and exact measurement

Private money is signed integer GBP pence; rates/factors are integer numerators over `S=10^12`. `R(x)` means nearest integer, exact halves away from zero, applied only at the stated posting boundary. No intermediate annual/monthly rate rounding is permitted. Primitive absolute amounts are at most `10^11` pence; quoted annual rates are 0..S, scenario spreads are within ±0.2S, and every effective rate must be 0..1.2S. No negative interest rate is supported. Every posted balance, financial flow and displayed DSCR-millionths integer must remain an integer with absolute value <2^53; otherwise fail, never clip. Rate/factor primitives use a 10^6 numerator grid so native percent inputs round-trip exactly.

Public money input/output cells contain GBP numeric values displayed to two decimals, not pence integers. Rates are fractional numeric values displayed as percentages; DSCR is shown in times. Private bindings declare `ledger_unit`, `worksheet_scale`, and exact round-trip conversion. Internal arithmetic can use visible integer calculation support, but primary input tables and business statements do not present P12 numerators as analyst assumptions. All public numeric primitives must reproduce their exact private pence/rate integer with `R(GBP*100)` or `R(rate_fraction*S)`; no tolerance substitutes for this identity.

Months are ISO first-of-month dates. Contract amendments take effect on a month start; maturities are actual month-end dates. Month day counts use the calendar, including February 2028. ACT/365F always divides by 365; ACT/360 divides by 360. Event dates and effective terms are public. The latest term effective no later than the month start governs that month. Amendment fields are COMPLETE replacement terms, not unspecified patches. Old accrued interest, tax balances, vintages, equity and cash survive an amendment unchanged.

## 3. Facility contracts

All facilities accrue interest on **opening principal only**:

`interest_accrual = R(opening_principal * (quoted_annual_rate + scenario_spread) * actual_month_days / (S * day_basis))`.

This is one final posting. Principal paid or drawn during the month does not change this month's accrual. New drawings occur at month end and first bear interest next month. Effective rates/day-count may differ between entities and amendment periods.

* **BULLET_MONTHLY:** cash coupon is all opening accrued interest plus current accrual every month; scheduled principal is zero before maturity and all opening principal at maturity.
* **LEVEL_PRINCIPAL_MONTHLY:** not annuity/PMT. At the initial term and each amendment reset, set the fixed monthly principal instalment to `R(opening principal / number of inclusive month-end instalments from this month through maturity)`. Before maturity pay the lesser of this fixed instalment and opening principal. At maturity pay all remaining opening principal. Voluntary or group-cap repayments do not automatically recast the fixed instalment; only a disclosed amendment resets it. Additional bank drawings are prohibited for this facility type. Cash interest is paid monthly as above.
* **BULLET_QUARTERLY_ACCRUAL:** accrue monthly but pay cash only in the disclosed next-coupon month and every third month thereafter, or at maturity. Cash coupon then equals all opening accrued interest plus current accrual; otherwise it is zero. Coupon reset on amendment establishes a new prospective next-coupon month; it does not erase accrued interest, pay it early, or double count the prior coupon calendar. The next date must not precede the effective month. Maturity pays the entire unpaid interest and opening principal even when off cycle.

For every type, `interest_payable_close = interest_payable_open + interest_accrual - cash_coupon`; book interest expense is accrual, not cash coupon. A facility may draw only before maturity and no later than its disclosed draw-cutoff month, within local and shared limits. Existing principal above a reduced local limit is mandatorily repaid with scheduled principal first and any remaining local excess second. The shared limit then imposes additional ordered margin repayment. These are actual cash flows, not adjustments to book interest.

Voluntary repayment is a disclosed fraction of unrestricted cash above minimum, rounded once and capped by remaining principal; it is made after reserve transfers and before new group bank allocation. A trapped entity sweeps 100% of that surplus to principal; an untrapped entity uses its disclosed fraction. No voluntary payment creates a cash deficit.

Contract expiry: in the maturity month release all opening reserve before paying the loan; no new draw is permitted and cash restrictions cease after the contractual settlement. Outside maturity, reserve/covenant policy remains in force while the facility is contractually outstanding, including a zero-balance committed credit line. For the fully funded LEVEL_PRINCIPAL type, complete repayment with zero accrued interest ends the facility at month end; its reserve is released at the following month's opening, with no current-month circular release. A previously ended facility cannot be reopened by an amendment. An unused facility or amortizing final payment is not a forecast-end deemed liquidation.

## 4. Assets and operating profit

Public operating tables supply each entity's monthly base cash revenue and cash operating cost. Scenario factors are posted separately: each actual revenue/cost equals `R(base * factor/S)`. EBITDA is their difference. Existing asset cost and accumulated depreciation are explicit opening inputs. New approved assets incur cash capex at commissioning, with no pre-commissioning cash or depreciation in this prototype. Each asset's monthly straight-line amount is `R(original cost / useful-life months)`; start depreciation the month after commissioning, clamp every posting to remaining NBV, and take any residual only at the final life month. Residual value is zero. No asset disposal is assumed.

EBIT is EBITDA less book depreciation. Every capital item is classified MAINTENANCE or GROWTH; both are investing cash flows, but only maintenance capex reduces covenant CFADS. Opening cash/restricted cash, asset cost/accumulated depreciation, debt/accrued interest/tax payable, paid-in capital and retained earnings are explicit balanced inputs. Validate the identity before simulation; no balancing plug is permitted.

## 5. Two tax policies, separate expense and cash settlement

These are explicitly stipulated hypothetical SPV tax regimes, not a claim about a named jurisdiction's law. Both use monthly assessments, the entity tax rate and a monthly EBITDA interest-cap fraction. No deferred tax asset/liability is recognized; carry balances are disclosed tax attributes, not book assets.

* **ACCRUAL_MONTHLY:** current eligible interest is this month's book interest accrual; pay the current tax assessment each month.
* **CASH_COUPON_QUARTERLY:** current eligible interest is the actual cash coupon, including prior accrued amounts paid now. Accrue the monthly tax assessment, but settle all opening tax payable plus current assessment at March/June/September/December month ends. Unpaid assessment remains an income-tax payable liability. No implicit December acceleration outside these stated dates.

At month opening, expire a vintage only when `current_month_index - origin_index > carry_months`. Old live denied-interest vintages use current interest capacity FIFO before current eligible interest. Capacity is `R(max(EBITDA,0) * cap_fraction/S)`. Current denied interest is added as a new vintage and cannot be reused that month. Taxable income before loss relief is EBIT minus allowed old and current eligible interest; this can differ from book profit when cash coupons differ from accrual.

Use live old tax-loss vintages FIFO against positive taxable income. Current negative taxable income creates a current vintage and cannot offset itself or another month retrospectively. Current tax expense is `R(max(taxable_after_losses,0) * tax_rate/S)`. `tax_payable_close = opening payable + current expense - cash tax`. Book NI is EBIT minus accrued interest expense minus current tax expense. No tax refund, group tax relief, or carryback is assumed.

Queues must retain all eligible origins: carry window N permits N historical origins plus current creation. Sparse ledger entries and bounded Excel windows are allowed; truncating the oldest eligible vintage is not.

## 6. Two DSCR timing policies and cash restrictions

CFADS is revenue minus cash operating cost, cash tax and maintenance capex. Mandatory debt service is actual cash coupon plus scheduled/local-limit/shared-limit mandatory principal. Exclude new draws, equity calls, reserve transfers and voluntary repayments from the numerator/denominator. The cash amounts are determined before the covenant test, avoiding feedback through the restriction decision.

* **MONTHLY_CURRENT:** test the current month. A failed current test immediately restricts this month's distribution/reserve handling. Cure requires two consecutive monthly passes; a restriction clears only in the month following the second pass.
* **QUARTERLY_LAGGED:** test only March/June/September/December using the sum of the three months' CFADS and mandatory debt service. The first March uses January–March. A failure takes effect next month. Cure requires two consecutive observed quarterly passes; non-test months preserve the counter and state.

Use the exact comparison `window_CFADS*S >= threshold*window_debt_service`. For a tested zero debt-service window, pass iff CFADS is nonnegative. Display DSCR as blank for zero denominator. In a non-test month both displayed ratio and displayed pass/fail are blank and are **not missing fields to fill**; a separate Test due indicator makes the case discoverable. For a positive denominator the displayed ratio is rounded to six decimal places (private millionths); it never drives the covenant test. Public flags are numeric 0/1, not Excel booleans. Non-test and zero-denominator blanks have private nullable encodings only as a projection of these public rules.

Only an active-at-opening facility is tested on its policy calendar. The maturity settlement month is active-at-opening and can therefore report a test. When `facility_closed_open=1`, `test_applicable=0`, ratio/pass are blank, trap/cure are cleared and any remaining opening reserve is released at opening; no post-exit test is invented. This is a public policy note, not merely a private encoding.

State: failure resets cure count to zero and sets next restriction. A tested pass increments a restricted facility's counter up to two; reaching two clears next-month restriction. Unrestricted passing facilities keep counter zero. Monthly operative restriction is opening restriction OR current failure. Quarterly operative restriction is opening restriction. Maturity/contract exit overrides next restriction/counter to clear as described above; current DSCR may still be reported.

When restricted, lock the lesser of positive cash above minimum and the shortfall to the fixed reserve target. Otherwise release the opening reserve. Reserve funding never borrows or consumes the minimum balance. A restricted entity may fund costs and bank debt, but pays no shareholder distribution. Reserve is a separate asset; its transfer has no P&L or total-cash effect.

## 7. One deterministic month close — no circular finance

1. Snapshot all entity, asset, facility, tax-vintage and group commitment opening states. Select the effective terms and scenario factors.
2. Calculate revenue, operating cash cost, commissioning capex, depreciation and opening-principal interest accrual. When the facility was already closed at opening or matures this month, release the opening reserve before settling coupon/principal. Determine coupon cash, scheduled principal, and remaining local-limit mandatory principal. Establish accrued-interest close. Cash before finance is provisional; the final journal places required financing receipts before obligations as stated in section 1.
3. Against the group shared bank limit, allocate any further mandatory principal repayment in the disclosed shared-margin priority. Each step uses the current aggregate debt after preceding payments; debit cash and principal together.
4. Assess interest deductibility/NOL/current tax, determine policy-specific cash tax, and close income-tax payable. Compute each entity NI, CFADS and mandatory debt service. Test the applicable DSCR window and derive operative/next restriction.
5. Apply ordinary reserve lock/release; a maturity reserve was already released in phase 2 and is not transferred again. Then repay voluntary principal from positive cash above minimum. `cash_before_financing` is the unrestricted cash snapshot at the END of this phase, after these transfers/repayments and before phase-6 bank draws. No current interest recomputation occurs here.
6. Allocate new bank drawings in disclosed group funding priority: minimum cash shortfall, local unused limit and remaining shared headroom jointly cap each draw; closed/amortizing/matured/cutoff facilities cannot draw.
7. Allocate LP calls in separate disclosed LP priority, capped by cash shortfall, each entity's unused additional commitment and the group's unused additional commitment. Opening paid-in capital is not an additional call. If a shortfall remains, report that scenario infeasible; do not manufacture finance or count a negative cash state as a valid source.
8. Pay distributions only if unrestricted, capped by cash above minimum and positive book equity after NI and new contributions. Return paid-in capital first; profit distributions reduce retained earnings. Neither is an expense. Close cash, restricted cash, debt, liabilities, equity, cure and commitment states.
9. Close double-entry journals, cash-flow statements and the consolidated group. There is no intercompany elimination in this first six-external-SPV prototype. Group statements sum actual entity cash, book assets, bank, accrued interest, tax payable, paid-in capital and retained earnings; they do not use a balancing line.

Forecast end is a reporting snapshot of all remaining assets/liabilities. Do not invent asset sale proceeds, accelerate loans, release reserve or consume unused capital at the boundary. Explicit contractual maturity still applies normally.

## 8. Result and binding interface

`simulate` returns `{schema_version, specification_sha256, feasible, scenarios, checks, mechanism_activation}`. Scenarios reset independently and share only primitives, never state. `scenarios[S01]` contains:

* `entities[E01].monthly[0..23]` — monetary/entity rows below;
* `loans[L01].monthly[0..23]` — selected terms and principal/interest/coupon/recast components;
* `assets[A01].monthly[0..23]` — cost, capex, depreciation and NBV;
* `interest_vintages[E01].monthly[...]` and `loss_vintages[...]` — origin-month opening/expired/used/created/closing amounts;
* `group_monthly[0..23]`, `journal_entries`, `checks`, `mechanism_activation`.

Entity monetary row fields (integer pence unless stated):

```
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
cfo cfi cff cash_delta
cash_check restricted_cash_check principal_check interest_payable_check tax_payable_check
interest_queue_check loss_queue_check capital_check retained_check balance_sheet_check
```

The DSCR window amount fields always report the actual policy window, including non-test or closed months: current month for the monthly policy, available trailing up-to-three months for the quarterly policy. Those amounts do not activate a test. Level-principal full-repayment closure requires a fully funded close; an infeasible provisional payment is not a completed settlement. Maturity still ends the diagnostic contract state while the scenario remains infeasible.

Private nonmoney row fields: `month`, effective `term_id`, `tax_policy`, `dscr_policy`, `test_applicable` (0/1), `test_pass` (nullable 0/1), `dscr_ratio_millionths` (nullable integer), `trap_open`, `trap_operative`, `trap_next`, `cure_open`, `cure_next`, `facility_closed_open`, `facility_closed_next`, `funding_gap`, `feasible` (private bool). **Funding gap is money**, not a flag; it is listed here only as source-admission status evidence. Formula flags map strictly to public numeric 0/1; nullable encodings do not equate blank/zero/False.

Loan rows expose `principal_open`, `annual_rate_p12`, `day_basis`, `days`, `interest_accrual`, `interest_payable_open`, `coupon_due`, `cash_coupon`, `recast_due`, `recast_instalment`, each principal flow and `principal_close/interest_payable_close`; calculated money aliases may bind the same physical account. Vintage entries expose origin, opening, expired, used, created, closing; no old eligible origin is omitted. Group rows include all entity monetary stock/flow totals, group bank capacity/used/headroom, LP commitment/calls/unused, and independent cash/bank/equity/BS residuals.

Statements use CFO = revenue − cash operating cost − coupon cash − cash tax; CFI = −all capex; CFF = bank draws −all principal payments +LP calls −distributions. CFO+CFI+CFF = change in unrestricted+restricted cash. Separate unrestricted cash and reserve bridges prove internal transfers once. Book BS is cash+restricted+asset NBV = bank principal+interest payable+tax payable+paid-in capital+retained earnings. NI, capital return and profit distribution get separate independent bridges.

Every financial binding declares result path, logical account, worksheet cell, type, display conversion, and semantic ownership of any internal complete monetary answer/helper. A GBP wrapper is not an adequate FM mask if an unchanged pence helper already contains its complete answer. Future FM planning must remove the selected economic calculation families including equivalent complete-answer components; future DBG planning must preserve ordinary legitimate formulas and localized exceptions. Both modes are fresh tasks with full-book D, actual input recalc, all controls and public sufficiency checks; neither inherits a difficulty claim from this design.

## 9. Implementation and first executable smoke

Reusable without editing frozen sources: resource engine/export, streaming typed comparison, AuditStore/ProducerLease/dashboard, ordinary task nodes and quality contracts. Generic exact quotient/remainder expression rendering may be imported at a frozen SHA as arithmetic infrastructure only. Do not import old entity business close, old private source JSON, previous financial oracle results or previous task adapters as economic logic. Independent new financial state updates are required in Decimal and Excel.

After contract review: strict schema+Decimal journal and a few hand-calculated 1–3-month fixtures (including coupon accrued liability, ACT leap day, maturity stub, amendment re-amortization, FIFO expiry and zero-denominator DSCR); independently implement Excel over the same raw primitives. First source smoke is the **full six × twenty-four × three** configuration, not a three-row toy qualification. It needs full per-field audit, no unexpected native errors, actual recalc plus two typed-stability passes and positive dated regime evidence. Preserve any infeasible/missing-regime design as rejected; revise parameters only in a new explicit configuration. Do not silently change the current file or claim all listed regimes are already active.

Estimated first implementation: schema/Decimal 1.5–2.5 hours; independent Excel 2–3 hours in parallel; builder/full audit/fault planning 1–2 hours after stable APIs; actual source proof and first task gate/probe time measured separately. These are planning estimates, not a commitment or elapsed evidence. The minimum source is intended to support both FM reconstruction and genuinely localized formula debugging. Strongest-model success remains possible and must be measured before any ten-profile expansion.
