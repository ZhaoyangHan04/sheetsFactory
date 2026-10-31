# Independent projects with a common portfolio choice

This is a new hypothetical family. The production universe is 240 ring-fenced
projects, three scenarios S01–S03 and 20 financial years. One binary project
choice applies to all scenarios. FY numbers 1–20 are discount periods; the raw
`fiscal_year_start` supplies their displayed calendar-year labels. An unselected
project contributes zero investment, finance, profit, resource use and exposure.
Projects do not lend cash, share tax losses or change each other's financing.

## Public financial contract

All posted amounts are integer GBP pence. Rates and multiplicative factors are
integer basis points over 10,000. Round each stated posting to the nearest penny,
with exact half ties away from zero. Do not round an intermediate rate.

1. At time zero acquire the asset for its supplied cost. Draw the bank amount
   `R(cost × t0_ltv_bp / 10000)` and call the remaining acquisition cost from LPs.
   The LP commitment is a lifetime gross-call limit **including** this time-zero
   call; repayments or distributions never restore commitment. There is no
   later bank draw. Feasible cash immediately after acquisition is zero.
2. Before `operating_start_year`, operating revenue, operating expense and
   depreciation are zero. In that first operating FY use the supplied base
   revenue and expense. In every subsequent FY independently grow each prior
   **posted unshocked base** by its supplied project growth factor and round.
   Apply that FY's scenario revenue/expense factor to the resulting base and
   round each amount once. Scenario shocks do not feed back into next FY's base.
3. From the first operating FY depreciate original cost straight-line over the
   supplied life (at most 20 years): `R(original cost / life)` each year capped at
   remaining NBV, with the final life-year taking the exact remaining balance.
   There is no revaluation or implicit salvage value in depreciation.
4. Bank interest is `R(opening principal × (bank_rate_bp + scenario spread_bp)
   / 10000)`; the effective rate cannot be negative. `LEVEL_PRINCIPAL` repays
   `R(original draw / debt_maturity_year)` from FY1, capped at remaining debt,
   and the maturity FY repays the exact remainder. `BULLET` repays all principal
   in the maturity FY. Both policies pay interest before the year-end repayment.
5. In FY20, after the full year's operations and depreciation, sell the entire
   asset for `R(terminal_sale_proceeds_pence × that scenario's sale_factor_bp /
   10000)`. Derecognise its **remaining post-depreciation NBV** and include
   proceeds minus that NBV in profit and the tax base. Repay any remaining bank
   debt. No extra terminal NAV, debt recovery or retained-cash value is added.
6. Profit before tax is revenue minus cash operating expense, depreciation and
   bank interest, plus the disposal gain/loss. Bank interest is fully deductible.
   At each year opening expire a loss from origin FY v iff `current FY − v > 3`:
   it is usable in v+1, v+2 and v+3. Apply remaining old losses oldest first to
   positive current profit. Negative current profit creates a current-year loss
   after old-loss processing. Tax the remaining nonnegative profit at the project
   tax rate and pay the rounded current tax in the same FY. There is no loss
   carryback, group relief, deferred tax or LP-level tax in this contract.
7. Available cash is opening cash plus revenue and sale receipts, less operating
   expense, interest, principal repayment and current tax. Distribute every
   positive remainder to LPs; call LPs for a deficiency, limited by unused lifetime
   commitment. No positive cash is retained. A shortfall is a funding gap and
   makes that scenario infeasible, rather than providing another source of funds.
   For diagnostics only, unpaid negative cash carries forward and the scenario
   remains infeasible even if a later receipt covers it. The same rule applies
   to a shortfall in the time-zero acquisition. Cash-sweep distributions include
   capital returns; no separate legal-book-profit distribution restriction is
   implied by this hypothetical contract.
8. A feasible project has no funding gap at any date, cumulative gross LP calls
   within commitment, and final cash, asset NBV and bank debt all zero. Accounting
   bridges include diagnostic negative cash; they must balance independently of
   feasibility. Every one of the 240 projects must be independently feasible in
   all three scenarios for a source to be admitted. Do not remove an infeasible
   candidate or equate a feasible selected subset with that source requirement.
9. For a feasible project/scenario, calculate
   `−t0 LP call + sum((LP distribution − new LP call) ×
   (10000 / (10000 + discount_rate_bp))**FY)` and round **once**, after combining
   the time-zero and all annual contributions, with half ties away from zero.
   There is no annual discounted-value rounding. The portfolio objective is
   the sum of individually posted **S01** NPVs, with no further rounding.
   S02/S03 are mandatory feasibility/capacity stress cases, not a worst-case or
   probability-weighted objective. There is no hidden tie-break or cardinality
   condition. A distinct winner/runner and gap are later optimizer evidence.

## Shared public constraints

The selected projects must satisfy the initial sponsor-LP budget; gross **new**
annual LP-call budgets and **year-end outstanding principal** limits in every
scenario/FY; six dated physical resource capacities in every scenario/FY; and
six-region/eight-sector annual asset-NBV exposure limits. Gross new LP calls are
neither net distributions nor cumulative calls. Bank exposure is not intrayear
peak debt. Region/sector NBV is scenario independent under these policies.
Provided resource usage is an independent physical schedule, not a financial
cache. Forty disjoint site/technology groups (two or three alternatives each)
permit at most one choice. Eighty declared acyclic prerequisite relationships
require the enabler whenever its dependent is selected; an enabler is funded
once. Each relationship has an ordinary business description. No optimizer is
allowed to alter these capacities or relationships after seeing its result.

## Raw schema and arithmetic bounds

`spec.py` is the authoritative typed schema. It contains only validation, public
rules and field constants; it executes no finance. All JSON annual-map keys are
strings of the FY numbers. Production requires all 240 IDs P001–P240, S01–S03,
FY1–FY20, six resources, six regions, eight sectors, 40 choice groups and 80
prerequisites. Explicit `dimension_mode: toy` permits one to four projects and
one to 20 FYs for tests only; its terminal sale is in its last supplied FY.

Project asset/operating/sale raw money inputs are 0–100,000,000p, cost positive;
lifetime LP commitment has a separate maximum of 10^12p. Project growth factors
are 0–11,000bp; scenario operating/sale factors 0–15,000bp; tax and effective
bank rates 0–5,000bp; discount 0–3,000bp; initial LTV 0–9,000bp. Shared portfolio
money limits are bounded by 10^12p. Physical resource values/capacities are bounded
integers. The implementations must check actual posted values, every amount×BP
product, every additive intermediate and every aggregate LHS below 2^53; typed
input limits alone are not a claim of proven Excel arithmetic safety. NPV uses
exact Fraction in A and high-precision Decimal in B, then independent posted-NPV
agreement; it is not a P12 discount-factor helper graph.

## Independent forward interfaces

Both implementations consume the validated raw schema, never the other's flows,
coefficients, winner or posting helpers. A (`candidate_a.py`) uses Fraction; B
(`ledger.py`) uses Decimal. Only `spec.py` may be shared.

* `simulate_project(specification, project_id, scenario_id)` returns time-zero
  postings, all annual fields, sparse FIFO vintage events, feasibility and
  `npv_pence: int | None`. A additionally exposes its exact fraction and B its
  high-precision decimal; unrounded representations need not be identical.
* `simulate_universe(specification)` evaluates every project in every scenario,
  preserving all candidates and a separate `all_standalone_feasible` flag.
* `simulate(specification, plan)` accepts the complete provided 0/1 mapping,
  returns the complete standalone universe, exact selected-portfolio constraints,
  per-scenario aggregates and the S01 objective or None. It performs no search.

`T0_FIELDS`, `ANNUAL_FIELDS`, `VINTAGE_FIELDS` and `GROUP_FIELDS` define common
integer-pence/flag fields. Annual sparse vintage events identify `origin_year`;
absence of an origin means zero, not an omitted account. Equity is asset NBV plus
cash less debt; independently it equals cumulative actual LP paid in plus
cumulative net income less cumulative LP distributions. Literal financial audit,
full independent coefficient agreement, actual workbook recalculation, stability,
quality, recovery, Harbor and strongest-model difficulty remain separate gates.
