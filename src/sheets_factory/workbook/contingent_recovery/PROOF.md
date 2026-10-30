# Same-year contingent recovery on the contractual fee grid

For the scalar callback, `E0` is the non-variable recovery entitlement basis. It
already includes the fixed-lease allowance, but excludes current tax and the
separately posted variable allowance. `B0` is the taxable base before variable
rent, rather than a tax amount. Available old losses, the utilization cap, tax
rate and variable eligibility fraction are explicit current-year inputs.

Let `Q` post to pennies with half-up rounding. For proposed total variable rent
`v`, the separately posted variable allowance is `A(v) = Q(a v)`. The taxable
base is `B(v) = B0 + A(v) - v`. Current tax and loss use follow the existing
regulatory expression, with continuous loss use calculated first and tax and
loss use then posted separately. Total recovery entitlement is
`E(v) = E0 + A(v) + tax(B(v))`.

For contract `i`, its cash fee is its stated rate times
`max(0, E(v) - threshold_i)`, rounded half up to its stated £100 or £1000 unit,
then capped. Each cap is an integer number of that contract's rounding units.
Let `F(v)` sum the resulting fees. There is no fee, allowance or tax amount
embedded in the supplied contract terms.

## A bound that includes the penny postings

Before posting, tax is zero at nonpositive taxable bases. At positive bases it
is continuous and piecewise affine. The old-loss-limited slope is `r/(1-r)`;
the utilization-limited slope is `r(1-c)/(1-r(1-c))`. Both are nonnegative and
the latter is no larger than the former. Thus `L = r/(1-r)` bounds the tax
increase per unit of taxable base across both regimes and their boundary.

Let `h` be the greatest common divisor of all supplied contract fee units.
Every possible total fee lies on the finite grid from zero through the sum
of the caps, in increments of `h`. At every adjacent pair of grid points,
half-up penny posting gives the global allowance increment bound

`dA >= a_min = £0.01 * floor(a h / £0.01)`.

Since `0 < a < 1` and `h` is a whole number of pennies, `dA <= h`. The taxable
base therefore decreases by `h-dA`, which is at most `h-a_min`. Posting the tax
once gives the global posted tax-decrease bound

`tax_drop <= t_max = £0.01 * ceil(L (h-a_min) / £0.01)`.

The solver computes both the floor and ceiling using exact integer rational
arithmetic. It rejects unless `a_min > t_max`. For an accepted input, recovery
entitlement increases by at least `a_min-t_max > 0` at every adjacent grid
pair. Each fee's positive part, rate multiplication, contractual half-up
rounding and cap are nondecreasing functions of entitlement. Their sum `F`
is therefore nondecreasing across the entire grid. This argument includes
rounding and the tax-loss regime changes; a continuous feedback slope alone
does not establish a unique rounded solution.

## Whole-grid uniqueness from both endpoints

Write `C` for the sum of the contractual caps. The rounded, capped fee map
sends the finite grid `[0,C]` into itself. Starting with `l0=0` and `u0=C`,
iterate `l(k+1)=F(lk)` and `u(k+1)=F(uk)`. Monotonicity gives

`lk <= l(k+1) <= u(k+1) <= uk`.

Every fixed point `p` satisfies `lk <= p <= uk` at every iteration. If both
sequences meet, the solver explicitly verifies that the common amount maps
to itself. That amount is the only fixed point on the entire contractual
grid. If the sequences stabilize at different amounts, the contract has
multiple fixed points and is rejected. If they do not meet within 128 steps,
the year is rejected without a uniqueness claim.

The exception retains both endpoint traces and the posting bound. Successful
results retain the same proof, the per-lease fees, tax, loss use, loss addition,
posted variable allowance and total recovery entitlement. They do not certify
workbook formulas, later years, source qualification or model difficulty.
