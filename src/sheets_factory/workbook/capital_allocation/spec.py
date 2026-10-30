"""Public contract and validation; no search or financial calculations."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

SCALE = 10**12
YEARS = tuple(range(2024, 2044))
OPENING_DATE = '2023-04-01'
PROJECT_IDS = tuple(f'P{i:02d}' for i in range(1, 19))
SCENARIO_IDS = ('S01', 'S02', 'S03')
RAW_ANCESTORS = {
    'NYU': 'df8f9e91cc53afe2bdb33cf39b8f2719206ac03b6a5031f1858f82235ea944c9',
    'Ofgem': '2f02bfdf2c4c85449129add05038fb1cbc10ad4ea716e9571a7dba0ea3642ce8',
}
PROJECT_FIELDS = (
    'capex', 'revenue', 'opex', 'depreciation', 'sale_proceeds',
    'sale_carrying', 'sale_gain', 'closing_book_value', 'certified_nav',
)
ANNUAL_FIELDS = (
    'cash_open', 'bank_open', 'capital_open', 'retained_open', 'lp_called_open',
    'prior_certified_nav', 'revenue', 'opex', 'capex', 'depreciation',
    'sale_proceeds', 'sale_carrying', 'sale_gain', 'bank_interest',
    'taxable_before_losses', 'loss_open', 'loss_expired', 'loss_used', 'loss_created',
    'loss_close', 'taxable_after_losses', 'current_tax', 'net_income',
    'borrowing_base', 'cash_before_financing', 'mandatory_margin',
    'cash_after_margin', 'optional_repayment', 'cash_after_optional',
    'bank_draw', 'lp_required', 'lp_call', 'funding_gap',
    'cash_before_distribution', 'equity_before_distribution', 'distribution',
    'return_of_capital', 'profit_distribution', 'net_lp_cashflow',
    'lp_called_close', 'lp_remaining', 'cash_close', 'bank_close',
    'capital_close', 'retained_close', 'project_book_value', 'certified_nav',
    'total_assets', 'total_liabilities', 'total_equity',
    'balance_check', 'cash_check', 'bank_check', 'capital_check', 'loss_check',
)
VINTAGE_FIELDS = ('opening', 'expired', 'used', 'created', 'closing')

RULES = (
    'The same eighteen binary investment choices apply to all three scenarios. '
    'Choices are committed before FY2024; there is no later scenario-dependent investment decision.',
    'Amounts are integer GBP pence. Every factor and rate is its supplied integer numerator '
    'over 1,000,000,000,000. Each posted amount uses nearest-penny rounding, with half ties '
    'away from zero. Products are not rounded before their stated posting.',
    'Each selected project pays its acquisition cost at the end of its commissioning FY. '
    'Operating revenue, cash expenses and depreciation begin in the following FY. '
    'The supplied annual revenue and expense forecasts are nominal base-scenario inputs; '
    'multiply each by that FY scenario factor and round each project amount separately.',
    'Annual depreciation is the smaller of remaining cost and the rounded original cost '
    'divided by depreciation years. The final depreciation year uses the remaining cost; '
    'later depreciation is zero. Financial and tax depreciation are identical.',
    'A project operates and depreciates for its entire sale FY, then sells at the supplied '
    'sale price times that FY sale factor, rounded to pence. Remove its remaining book '
    'and tax carrying value; sale gain or loss is proceeds less that value. '
    'Every project sells by the end of FY2043.',
    'Closing certified NAV is each unsold project closing book value times that FY NAV '
    'factor, rounded separately. It is a lender certificate only: it does not revalue '
    'the financial balance sheet or create income.',
    'The annual bank borrowing base is the smaller of facility limit and prior FY total '
    'certified NAV times advance rate times one minus current FY haircut, rounded once. '
    'Opening FY2024 certified NAV is zero. The facility matures in FY2043, when its base is zero.',
    'Bank interest is opening bank principal times current FY bank rate, rounded to pence. '
    'New draws first incur interest in the following FY. There is no intrayear liquidity '
    'test: all annual cash flows settle at FY end, with required financing raised before '
    'settling the annual net payment obligation.',
    'Taxable profit before losses is revenue minus cash operating expense, depreciation '
    'and bank interest, plus sale gain or loss. A loss created in FY v is available '
    'in FY v+1 through v+N inclusive, where N is the supplied carry years; it expires '
    'before FY v+N+1 activity. Use surviving prior losses FIFO before charging current '
    'tax. Negative current profit creates a new current-year vintage. No loss carryback '
    'or deferred-tax asset is recognised in this cash-tax financial forecast.',
    'Cash before financing equals opening cash plus revenue and sale proceeds, less '
    'cash operating expense, acquisition cost, bank interest and current tax. First '
    'repay opening debt above the borrowing base. Next repay remaining debt using cash '
    'above the required minimum. Draw remaining base headroom only to restore the minimum. '
    'Then call LP capital only for the remaining deficiency, limited by the remaining '
    'cumulative additional commitment. A remaining funding gap makes the plan infeasible; '
    'it is not an extra source of funds.',
    'After financing, distribute cash above the minimum, capped at nonnegative book equity '
    'before distribution. Distributions first return outstanding paid-in capital; the '
    'remainder is a profit distribution reducing retained earnings. Neither distribution '
    'is an expense. Initial paid-in capital equals opening cash; additional calls increase '
    'paid-in capital. Calls consume commitment permanently, even after capital is returned.',
    'FY2043 required minimum cash is zero. All project assets sell and the bank matures '
    'under the same stated priority. A feasible terminal state has zero bank debt, zero '
    'project book assets and zero cash; no implicit terminal NAV or collateral recovery '
    'is added to LP value.',
    'For each feasible scenario, LP net present value is rounded exactly once after '
    'combining the annual (actual LP distributions minus additional LP calls) times '
    'supplied discount factors AND the negative opening-cash contribution at time zero. '
    'Subtract the time-zero contribution before that sole rounding, not afterwards. '
    'Do not round annual discounted amounts before summation. LP partner-level taxes are outside this '
    'hypothetical scope; project/fund corporate tax is already paid in the cash flows.',
    'A plan is feasible only if all three scenarios meet every funding and terminal '
    'condition. Maximise the lowest of their LP net present values. There is no hidden '
    'tie-break: source admission requires a unique best plan and a gap of at least '
    'one penny to the next feasible plan. Infeasible plans have no objective value.',
    'This is a synthetic capital-allocation extension. The retained NYU and Ofgem raw '
    'ancestor hashes document provenance, not a claim that these investment forecasts '
    'or optimisation policies occur in either original workbook.',
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _integer(value, minimum, maximum, label):
    _require(type(value) is int and minimum <= value <= maximum,
             label + ' must be an integer within its declared bounds')


def _keys(value, keys, label):
    _require(isinstance(value, dict) and set(value) == set(keys), label + ' fields differ')


def _annual(value, minimum, maximum, label):
    _keys(value, map(str, YEARS), label)
    for year in YEARS:
        _integer(value[str(year)], minimum, maximum, label + '/' + str(year))


def load_spec(value):
    """Return JSON-shaped public primitives after strict dimension/bound checks."""
    spec = json.loads(Path(value).read_text()) if isinstance(value, (str, Path)) else deepcopy(value)
    _keys(spec, ('schema_version', 'currency', 'monetary_unit', 'years',
        'opening_cash_pence', 'minimum_cash_pence', 'lp_commitment_pence',
        'facility_limit_pence', 'advance_rate_p12', 'tax_rate_p12',
        'tax_loss_carry_years', 'discount_factors_p12', 'projects', 'scenarios', 'provenance'), 'Specification')
    _require(type(spec['schema_version']) is int and spec['schema_version'] == 1
             and spec['currency'] == 'GBP' and spec['monetary_unit'] == 'pence'
             and spec['years'] == list(YEARS) and all(type(y) is int for y in spec['years']),
             'Unsupported public dimensions or units')
    for key in ('opening_cash_pence', 'minimum_cash_pence', 'lp_commitment_pence', 'facility_limit_pence'):
        _integer(spec[key], 0, 10**11, key)
    _require(spec['opening_cash_pence'] >= spec['minimum_cash_pence'], 'Opening cash is below the contractual minimum')
    for key in ('advance_rate_p12', 'tax_rate_p12'):
        _integer(spec[key], 0, SCALE, key)
    _integer(spec['tax_loss_carry_years'], 1, 20, 'tax_loss_carry_years')
    _annual(spec['discount_factors_p12'], 1, SCALE, 'discount_factors_p12')
    factors = [spec['discount_factors_p12'][str(y)] for y in YEARS]
    _require(factors == sorted(factors, reverse=True), 'Discount factors must not increase with reporting year')
    projects = spec['projects']
    _require(isinstance(projects, list) and all(isinstance(p, dict) for p in projects)
             and [p.get('id') for p in projects] == list(PROJECT_IDS),
             'Exactly the eighteen ordered project IDs are required')
    for project in projects:
        _keys(project, ('id', 'commission_year', 'sale_year', 'acquisition_cost_pence',
            'depreciation_years', 'annual_revenue_pence', 'annual_opex_pence', 'sale_proceeds_pence'), project['id'])
        _integer(project['commission_year'], YEARS[0], YEARS[-1] - 1, 'commission_year')
        _integer(project['sale_year'], project['commission_year'] + 1, YEARS[-1], 'sale_year')
        _integer(project['acquisition_cost_pence'], 1, 10**9, 'acquisition_cost_pence')
        _integer(project['sale_proceeds_pence'], 0, 10**9, 'sale_proceeds_pence')
        _integer(project['depreciation_years'], 1, 20, 'depreciation_years')
        for key in ('annual_revenue_pence', 'annual_opex_pence'):
            _annual(project[key], 0, 10**9, project['id'] + '/' + key)
            _require(all(project[key][str(y)] == 0 for y in YEARS
                         if not project['commission_year'] < y <= project['sale_year']),
                     'Project operating forecasts must be zero outside its operating years')
    scenarios = spec['scenarios']
    _require(isinstance(scenarios, list) and all(isinstance(s, dict) for s in scenarios)
             and [s.get('id') for s in scenarios] == list(SCENARIO_IDS),
             'Exactly the three ordered scenario IDs are required')
    for scenario in scenarios:
        _keys(scenario, ('id', 'revenue_factors_p12', 'opex_factors_p12',
            'nav_factors_p12', 'sale_factors_p12', 'bank_rates_p12', 'haircuts_p12'), scenario['id'])
        for key in ('revenue_factors_p12', 'opex_factors_p12', 'nav_factors_p12', 'sale_factors_p12'):
            _annual(scenario[key], 0, 3 * SCALE, scenario['id'] + '/' + key)
        for key in ('bank_rates_p12', 'haircuts_p12'):
            _annual(scenario[key], 0, SCALE, scenario['id'] + '/' + key)
    provenance = spec['provenance']
    _keys(provenance, ('kind', 'raw_ancestors'), 'provenance')
    _require(provenance['kind'] == 'synthetic_capital_allocation_extension'
             and provenance['raw_ancestors'] == RAW_ANCESTORS,
             'The two immutable raw ancestors must be retained without an unchanged-source claim')
    return spec


def validate_plan(plan):
    _keys(plan, PROJECT_IDS, 'Common investment plan')
    for identifier, choice in plan.items():
        _integer(choice, 0, 1, identifier + ' choice')
    return dict(plan)
