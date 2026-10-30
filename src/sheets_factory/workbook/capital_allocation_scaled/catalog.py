"""Prospective public capital inputs, with no optimisation or outcome selection.

The catalog fixes the development profile before any model call. Its monetary
forecasts are synthetic; the two retained raw hashes identify source ancestry.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP, localcontext
import json
from pathlib import Path
import random

from ..capital_allocation.spec import ANNUAL_FIELDS, PROJECT_FIELDS, VINTAGE_FIELDS, RULES
from .spec import RAW_ANCESTORS, SCALE, YEARS, canonical_sha, load_spec

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CATALOG = ROOT / 'config/capital_allocation_scaled_catalog_v1.json'
BENCHMARK_ORDER = ('26-B01', '28-B01', '30-D01')
CONFIRMATION_ORDER = tuple(f'30-G{i:02d}' for i in range(1, 11))
PROFILE_ORDER = ('26-B01', '28-B01', '30-D01', *CONFIRMATION_ORDER)
COHORTS = (
    'contracted_long_life', 'collateral_carry', 'early_loss_rebuild',
    'merchant_cycle', 'short_refurbishment', 'delayed_delivery',
)
COHORT_DESCRIPTIONS = {
    'contracted_long_life': 'Long operating lives, modest growth and relatively stable margins.',
    'collateral_carry': 'Thin operating cash margins with long-lived book collateral and material exit proceeds.',
    'early_loss_rebuild': 'Two initial operating-loss years followed by a separately supplied revenue ramp.',
    'merchant_cycle': 'Calendar-sensitive revenue cycles, shorter asset lives and varying exit exposure.',
    'short_refurbishment': 'Later commissioning, short operating holds and low residual exit proceeds.',
    'delayed_delivery': 'Deferred commissioning with staged revenue delivery and persistent early cash expense.',
}
PROFILE_FIELDS = {
    'id', 'project_count', 'seed', 'cohort_counts', 'opening_cash_pence',
    'minimum_cash_pence', 'lp_commitment_pence', 'facility_limit_pence',
    'advance_rate_bp', 'tax_rate_bp', 'discount_rate_bp', 'loss_carry_years',
    'early_stress_start', 'late_cost_peak_start', 'stress_depth_bp',
    'rate_shape_id', 'description',
}
CATALOG_FIELDS = {
    'version', 'kind', 'currency', 'years', 'benchmark_profile_order',
    'confirmation_profile_order', 'profile_order', 'prospective_first_strong_profile',
    'benchmark_only_no_rollout', 'raw_ancestors', 'profiles',
}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _bounded(value, low, high, name):
    _require(type(value) is int and low <= value <= high, name + ' requires a bounded integer')


def load_catalog(value=DEFAULT_CATALOG):
    """Validate all thirteen prospective profiles and their immutable roles."""
    catalog = json.loads(Path(value).read_text()) if isinstance(value, (str, Path)) else deepcopy(value)
    _require(isinstance(catalog, dict) and set(catalog) == CATALOG_FIELDS,
             'The complete prospective catalog fields are required')
    _require(type(catalog['version']) is int and catalog['version'] == 1
             and catalog['kind'] == 'predeclared_scaled_capital_allocation_catalog'
             and catalog['currency'] == 'GBP' and catalog['years'] == [2024, 2043],
             'Unsupported catalog version, currency or calendar')
    for key, expected in (
        ('benchmark_profile_order', BENCHMARK_ORDER),
        ('confirmation_profile_order', CONFIRMATION_ORDER), ('profile_order', PROFILE_ORDER),
        ('benchmark_only_no_rollout', BENCHMARK_ORDER[:2]),
    ):
        _require(catalog[key] == list(expected), 'The prospective ' + key + ' must remain complete and ordered')
    _require(catalog['prospective_first_strong_profile'] == '30-D01'
             and catalog['raw_ancestors'] == RAW_ANCESTORS,
             'The first development profile and both raw ancestors must be explicit')
    profiles = catalog['profiles']
    _require(isinstance(profiles, list) and all(isinstance(p, dict) for p in profiles)
             and [p.get('id') for p in profiles] == list(PROFILE_ORDER),
             'All thirteen distinct profiles are required in prospective order')
    for profile in profiles:
        _require(set(profile) == PROFILE_FIELDS, 'Unexpected public profile fields')
        _require(type(profile['project_count']) is int
                 and profile['project_count'] == int(profile['id'].split('-')[0]),
                 'The public project count must match its declared profile')
        _bounded(profile['seed'], 0, 2**31 - 1, 'seed')
        counts = profile['cohort_counts']
        _require(isinstance(counts, list) and len(counts) == len(COHORTS)
                 and all(type(n) is int and 2 <= n <= 8 for n in counts)
                 and sum(counts) == profile['project_count'],
                 'Six complete economic cohorts must account for every project')
        for name in ('opening_cash_pence', 'minimum_cash_pence',
                     'lp_commitment_pence', 'facility_limit_pence'):
            _bounded(profile[name], 0, 10**11, name)
        _require(profile['opening_cash_pence'] >= profile['minimum_cash_pence'],
                 'Opening cash is below its contractual minimum')
        for name in ('advance_rate_bp', 'tax_rate_bp'):
            _bounded(profile[name], 1, 10000, name)
        _bounded(profile['discount_rate_bp'], 1, 3000, 'discount_rate_bp')
        _bounded(profile['loss_carry_years'], 1, 20, 'loss_carry_years')
        _bounded(profile['early_stress_start'], 2025, 2030, 'early_stress_start')
        _bounded(profile['late_cost_peak_start'], 2033, 2039, 'late_cost_peak_start')
        _bounded(profile['stress_depth_bp'], 1000, 4500, 'stress_depth_bp')
        _bounded(profile['rate_shape_id'], 0, 3, 'rate_shape_id')
        _require(isinstance(profile['description'], str) and bool(profile['description'].strip()),
                 'Each profile needs a public economic description')
    _require(len({p['seed'] for p in profiles}) == len(profiles), 'Every profile needs a distinct declared seed')
    return catalog


def _round(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _money(cost, bp, growth_bp=0, years=0):
    return _round(Decimal(cost) * Decimal(bp) / 10000
                  * (1 + Decimal(growth_bp) / 10000) ** years)


def _project(identifier, cohort, rng):
    # The role changes the shape and dates of primitive schedules, not merely a
    # scalar applied to a common investment template.
    if cohort == 'contracted_long_life':
        commission = rng.randint(2024, 2028)
        sale = min(2043, commission + rng.randint(10, 16))
        life, cost = rng.randint(12, 19), rng.randint(2200, 6400) * 100000
        rev, expense, growth, residual = rng.randint(2000, 2700), rng.randint(850, 1350), rng.randint(40, 210), rng.randint(2800, 6100)
    elif cohort == 'collateral_carry':
        commission = rng.randint(2024, 2029)
        sale = rng.randint(max(2037, commission + 9), 2043)
        life, cost = rng.randint(15, 20), rng.randint(3200, 8200) * 100000
        rev, expense, growth, residual = rng.randint(1250, 1700), rng.randint(1000, 1450), rng.randint(20, 120), rng.randint(7200, 10800)
    elif cohort == 'early_loss_rebuild':
        commission = rng.randint(2024, 2029)
        sale = min(2043, commission + rng.randint(8, 13))
        life, cost = rng.randint(6, 12), rng.randint(1800, 5600) * 100000
        rev, expense, growth, residual = rng.randint(3300, 4400), rng.randint(1350, 2050), rng.randint(40, 180), rng.randint(2000, 5200)
    elif cohort == 'merchant_cycle':
        commission = rng.randint(2024, 2030)
        sale = min(2043, commission + rng.randint(5, 10))
        life, cost = rng.randint(4, 10), rng.randint(1600, 6800) * 100000
        rev, expense, growth, residual = rng.randint(2450, 3750), rng.randint(1550, 2250), rng.randint(0, 140), rng.randint(2000, 7000)
    elif cohort == 'short_refurbishment':
        commission = rng.randint(2025, 2033)
        sale = min(2043, commission + rng.randint(3, 6))
        life, cost = rng.randint(3, 6), rng.randint(900, 4500) * 100000
        rev, expense, growth, residual = rng.randint(2900, 3900), rng.randint(1700, 2400), rng.randint(0, 90), rng.randint(500, 2500)
    else:
        _require(cohort == 'delayed_delivery', 'Unknown economic cohort')
        commission = rng.randint(2027, 2033)
        sale = min(2043, commission + rng.randint(7, 10))
        life, cost = rng.randint(6, 12), rng.randint(2600, 7600) * 100000
        rev, expense, growth, residual = rng.randint(3500, 4700), rng.randint(1600, 2350), rng.randint(50, 170), rng.randint(3800, 7200)
    revenues, expenses = {}, {}
    cycle = rng.randrange(4)
    for year in YEARS:
        age = year - commission
        if not commission < year <= sale:
            revenues[str(year)] = expenses[str(year)] = 0
            continue
        revenue_bp, expense_bp = rev, expense
        if cohort == 'early_loss_rebuild' and age <= 2:
            revenue_bp = rng.randint(550, 950) if age == 1 else rng.randint(900, 1300)
            expense_bp = max(expense, rng.randint(1700, 2200))
        elif cohort == 'merchant_cycle':
            revenue_bp = rev * (130, 62, 108, 82)[(year + cycle) % 4] // 100
            expense_bp += (0, 180, 390, 110)[(year + cycle) % 4]
        elif cohort == 'delayed_delivery':
            revenue_bp = rev * (28 if age == 1 else 64 if age == 2 else 100) // 100
            expense_bp += 170 if age <= 2 else 0
        elif cohort == 'short_refurbishment' and age == 2:
            expense_bp += rng.randint(450, 950)
        revenues[str(year)] = _money(cost, revenue_bp, growth, age - 1)
        expenses[str(year)] = _money(cost, expense_bp, max(0, growth - 30), age - 1)
    return {'id': identifier, 'commission_year': commission, 'sale_year': sale,
            'acquisition_cost_pence': cost, 'depreciation_years': life,
            'annual_revenue_pence': revenues, 'annual_opex_pence': expenses,
            'sale_proceeds_pence': _money(cost, residual)}


def _scenario_rows(profile):
    rows = []
    keys = ('revenue_factors_p12', 'opex_factors_p12', 'nav_factors_p12',
            'sale_factors_p12', 'bank_rates_p12', 'haircuts_p12')
    for scenario in range(3):
        row = {'id': f'S{scenario + 1:02d}', **{key: {} for key in keys}}
        for index, year in enumerate(YEARS):
            early = profile['early_stress_start'] <= year < profile['early_stress_start'] + 3
            late = profile['late_cost_peak_start'] <= year < profile['late_cost_peak_start'] + 4
            cycle = (index + profile['rate_shape_id']) % 5
            depth = profile['stress_depth_bp']
            if scenario == 0:
                values = (10000 + (-450, 150, 500, -200, 250)[cycle],
                          10000 + (100, 350, 0, 250, 150)[cycle],
                          10000 - (900 if early else 150), 9600 + (index % 3) * 250,
                          560 + 45 * cycle, 2100 if early else 950 + 75 * cycle)
            elif scenario == 1:
                values = (10000 - depth if early else 10800 - 65 * cycle,
                          10100 - 650 if early else 10500 + 90 * cycle,
                          10000 - depth - 700 if early else 9500 - 120 * cycle,
                          10000 - depth if early else 9100 + 170 * cycle,
                          850 + 55 * cycle if early else 640 + 35 * cycle,
                          3000 + depth // 3 if early else 1650 + 90 * cycle)
            else:
                values = (11300 - 100 * cycle if not late else 10000 - depth // 2,
                          10400 + 80 * cycle if not late else 11200 + depth // 3,
                          10600 - 100 * cycle if not late else 8200 - depth // 5,
                          11000 - 180 * cycle if not late else 8000 - depth // 6,
                          650 + 45 * cycle if not late else 1000 + 60 * cycle,
                          1150 + 60 * cycle if not late else 3300 + depth // 4)
            for key, bp in zip(keys, values):
                row[key][str(year)] = bp * (SCALE // 10000)
        rows.append(row)
    return rows


def _profile(catalog, profile_id):
    _require(profile_id in PROFILE_ORDER, 'Unknown prospectively declared profile')
    return next(p for p in catalog['profiles'] if p['id'] == profile_id)


def _build(profile):
    rng = random.Random(profile['seed'])
    roles = [role for role, count in zip(COHORTS, profile['cohort_counts']) for _ in range(count)]
    rng.shuffle(roles)
    with localcontext() as context:
        context.prec = 70
        projects = [_project(f'P{i + 1:02d}', role, rng) for i, role in enumerate(roles)]
        discount = 1 + Decimal(profile['discount_rate_bp']) / 10000
        spec = {'schema_version': 1, 'currency': 'GBP', 'monetary_unit': 'pence', 'years': list(YEARS),
            **{key: profile[key] for key in ('opening_cash_pence', 'minimum_cash_pence',
                                            'lp_commitment_pence', 'facility_limit_pence')},
            'advance_rate_p12': profile['advance_rate_bp'] * (SCALE // 10000),
            'tax_rate_p12': profile['tax_rate_bp'] * (SCALE // 10000),
            'tax_loss_carry_years': profile['loss_carry_years'],
            'discount_factors_p12': {str(year): _round(Decimal(SCALE) / discount ** (i + 1))
                                     for i, year in enumerate(YEARS)},
            'projects': projects, 'scenarios': _scenario_rows(profile),
            'provenance': {'kind': 'synthetic_capital_allocation_extension',
                           'raw_ancestors': dict(RAW_ANCESTORS)}}
    return load_spec(spec), roles


def build_spec(profile_id, catalog=DEFAULT_CATALOG):
    """Build one raw public specification in memory; never evaluate its plans."""
    checked = load_catalog(catalog)
    return _build(_profile(checked, profile_id))[0]


def generate_specs(catalog=DEFAULT_CATALOG):
    """Return every profile in the fixed order, with no outcome-based filtering."""
    checked = load_catalog(catalog)
    return [{'profile_id': p['id'], 'spec': _build(p)[0]} for p in checked['profiles']]


def describe_profile(profile_id, catalog=DEFAULT_CATALOG):
    checked = load_catalog(catalog)
    profile = _profile(checked, profile_id)
    public, roles = _build(profile)
    return {'profile_id': profile_id, 'project_count': len(roles),
        'prospective_role': 'engineering_benchmark_only' if profile_id in BENCHMARK_ORDER[:2]
            else 'first_development' if profile_id == '30-D01' else 'confirmation_candidate',
        'description': profile['description'], 'public_spec_sha256': canonical_sha(public),
        'candidate_cohorts': [{'id': p['id'], 'cohort': role} for p, role in zip(public['projects'], roles)],
        'cohort_descriptions': dict(COHORT_DESCRIPTIONS),
        'standalone_candidate_schedules_before_choice': True,
        'source_original_ancestors': len(RAW_ANCESTORS), 'source_workbooks': 0,
        'optimisation_performed': False, 'unique_optimum_claimed': False,
        'qualified': False, 'task_count': 0}


ANNUAL_MEANINGS = {
    'cash_open': 'Cash carried from the previous FY close; FY2024 equals the time-zero LP contribution.',
    'bank_open': 'Opening external bank principal, before current-year repayment or draw.',
    'capital_open': 'Opening outstanding paid-in LP capital, after previous returns of capital.',
    'retained_open': 'Opening retained earnings after previous profit distributions; may be negative.',
    'lp_called_open': 'Cumulative additional LP calls before this FY; never reduced by distributions.',
    'prior_certified_nav': 'Total prior-FY closing collateral certificate; FY2024 is zero.',
    'revenue': 'Sum of selected candidates\' separately posted scenario revenue.',
    'opex': 'Positive sum of selected candidates\' separately posted cash operating expense.',
    'capex': 'Positive acquisition cash paid for selected candidates commissioning this FY.',
    'depreciation': 'Positive sum of selected candidates\' annual book and tax depreciation.',
    'sale_proceeds': 'Selected candidate exit cash after scenario adjustment, positive.',
    'sale_carrying': 'Book and tax carrying value removed on selected candidate sales, positive.',
    'sale_gain': 'Sale proceeds less carrying value removed; may be negative.',
    'bank_interest': 'Positive interest on opening bank principal at this FY rate.',
    'taxable_before_losses': 'Revenue minus cash opex, depreciation and bank interest plus sale gain; signed.',
    'loss_open': 'Total carried tax loss before this FY expiry and FIFO use.',
    'loss_expired': 'Positive opening-vintage amounts that expire before this FY activity.',
    'loss_used': 'Positive surviving prior-vintage losses used FIFO against this FY positive taxable profit.',
    'loss_created': 'Positive new current-FY vintage from negative taxable profit; unavailable this FY.',
    'loss_close': 'Total after opening losses, expiry, use and creation.',
    'taxable_after_losses': 'Nonnegative taxable profit remaining after eligible prior FIFO losses.',
    'current_tax': 'Positive rounded corporate cash tax on taxable profit after losses.',
    'net_income': 'Signed taxable profit before losses less current cash tax; no deferred tax.',
    'borrowing_base': 'Current debt ceiling from prior NAV, advance, current haircut and facility cap; zero at maturity.',
    'cash_before_financing': 'Opening cash plus revenue and sale proceeds less opex, capex, interest and cash tax; before all financing.',
    'mandatory_margin': 'Positive repayment of opening bank principal above the current borrowing base.',
    'cash_after_margin': 'Cash before financing less mandatory margin; before optional repayment.',
    'optional_repayment': 'Positive repayment of remaining debt from cash above the current minimum.',
    'cash_after_optional': 'Cash after margin less optional repayment; before bank draws and LP calls.',
    'bank_draw': 'Positive base-limited new bank draw to restore the minimum after repayments.',
    'lp_required': 'Nonnegative cash deficiency after bank draw, before applying the finite remaining LP commitment.',
    'lp_call': 'Actual positive additional LP contribution, capped by unused cumulative commitment.',
    'funding_gap': 'Unfunded remainder after actual bank draw and finite LP call; positive makes the scenario infeasible.',
    'cash_before_distribution': 'Cash after all repayments, bank draws and LP calls; before distribution.',
    'equity_before_distribution': 'Opening paid-in capital plus actual new call plus opening retained earnings and current net income.',
    'distribution': 'Actual positive cash above the minimum, capped by nonnegative equity before distribution.',
    'return_of_capital': 'Distribution allocated first against outstanding paid-in capital including current calls.',
    'profit_distribution': 'Distribution after return of capital, reducing retained earnings without changing net income.',
    'net_lp_cashflow': 'Signed FY-end distribution minus actual additional call; excludes the separate time-zero contribution.',
    'lp_called_close': 'Cumulative additional calls including this FY; return of capital does not restore commitment.',
    'lp_remaining': 'Unused cumulative additional LP commitment after this FY call.',
    'cash_close': 'Cash after actual distribution; feeds next FY opening cash.',
    'bank_close': 'Opening bank principal less mandatory and optional repayments plus actual new draw.',
    'capital_close': 'Opening outstanding capital plus call less return of capital.',
    'retained_close': 'Opening retained earnings plus net income less profit distribution; signed.',
    'project_book_value': 'Sum of selected unsold candidates\' closing book assets.',
    'certified_nav': 'Sum of selected unsold candidates\' separately rounded closing collateral certificates; no book revaluation.',
    'total_assets': 'Closing cash plus selected closing project book assets.',
    'total_liabilities': 'Closing external bank principal.',
    'total_equity': 'Closing outstanding capital plus retained earnings.',
    'balance_check': 'Assets minus liabilities minus equity; must be zero even on a diagnostic infeasible continuation.',
    'cash_check': 'Closing cash less the complete opening-to-closing cash flow bridge; zero.',
    'bank_check': 'Closing bank less opening bank plus repayments less draws; zero.',
    'capital_check': 'Closing outstanding capital less opening capital less calls plus capital returns; zero.',
    'loss_check': 'Closing loss less opening loss plus expiry and use less creation; zero.',
}
PROJECT_MEANINGS = {
    'capex': 'Full candidate acquisition cash in its commissioning FY, irrespective of the investment choice.',
    'revenue': 'Standalone candidate base revenue times this FY scenario factor, separately rounded.',
    'opex': 'Standalone candidate base cash expense times this FY scenario factor, separately rounded and positive.',
    'depreciation': 'Standalone candidate depreciation under the stated rounded, clamped cost schedule.',
    'sale_proceeds': 'Full candidate exit cash in sale FY after the scenario factor, separately rounded.',
    'sale_carrying': 'Candidate remaining book and tax value after sale-FY depreciation, removed on sale.',
    'sale_gain': 'Candidate sale proceeds minus sale carrying value, signed.',
    'closing_book_value': 'Candidate book value after depreciation and any sale; zero before commissioning or after sale.',
    'certified_nav': 'Unsold candidate book value times scenario NAV factor, separately rounded; memo only.',
}
VINTAGE_MEANINGS = {
    'opening': 'This origin vintage carried from last FY before expiry or use; future/current origins open at zero.',
    'expired': 'Opening amount removed at the start of the first FY later than origin plus carry years.',
    'used': 'Surviving prior-origin amount used FIFO in this FY; current-year creations cannot be used.',
    'created': 'Only the current-origin row receives this FY newly created loss.',
    'closing': 'Opening less expired and used plus created, including provided zero cells for inactive/future origins.',
}
SUMMARY_MEANINGS = {
    'feasible': 'Numeric 1 only if no FY funding gap and terminal bank principal, project book assets and cash are all zero; otherwise numeric 0.',
    'npv_pence': 'Sole-round net LP present value if this scenario is feasible; blank if infeasible.',
    'diagnostic_npv_pence': 'The same sole-round net LP cash-flow calculation on the fully continued annual accounting path, even if infeasible; never an objective for an infeasible plan.',
    'objective_pence': 'Minimum of all three feasible scenario NPVs; blank unless all three are feasible.',
    'overall_feasible': 'Numeric 1 only when all three scenario feasible flags are 1; otherwise numeric 0.',
}


def public_contract(profile_id, catalog=DEFAULT_CATALOG):
    """Complete business/field contract, without a plan, solver or target values."""
    checked = load_catalog(catalog)
    profile = _profile(checked, profile_id)
    _require(set(ANNUAL_MEANINGS) == set(ANNUAL_FIELDS)
             and set(PROJECT_MEANINGS) == set(PROJECT_FIELDS)
             and set(VINTAGE_MEANINGS) == set(VINTAGE_FIELDS), 'Public financial field dictionary is incomplete')
    rules = [RULES[0].replace('eighteen', str(profile['project_count'])), *RULES[1:]]
    return {'kind': 'public_scaled_capital_candidate_and_accounting_contract', 'version': 1,
        'profile_id': profile_id, 'project_count': profile['project_count'],
        'calendar': {'opening_date': '2023-04-01', 'fy_end': '31 March', 'years': list(YEARS)},
        'units': 'All monetary inputs and outputs are integer GBP pence; factors and rates are integer numerators over 10^12. Numeric flags are literal 0/1, not booleans.',
        'candidate_schedule_policy': 'Every project worksheet is a standalone candidate schedule before the investment choice. Compute every candidate in every scenario, including candidates with choice 0. Apply the common choices only when aggregating candidate amounts into scenario annual accounts; do not zero an unselected candidate worksheet.',
        'diagnostic_continuation_policy': 'A funding gap makes the scenario infeasible but is never a financing source. Continue the accounting path with actual capped financing, even if cash becomes negative, to populate all FY fields and diagnostic NPV. Infeasible paths do not participate in the objective.',
        'opening_cashflow_policy': 'The time-zero LP contribution is exactly negative opening_cash_pence on 2023-04-01, inside the single final NPV rounding. FY2024 net_lp_cashflow contains only FY2024 distribution minus additional call; do not subtract initial capital twice.',
        'blank_policy': 'Only infeasible scenario npv_pence and an infeasible overall objective_pence are blank. Diagnostic NPV and all supplied annual, project and vintage numeric fields remain numeric, including required zero amounts.',
        'rules': rules, 'annual_fields': dict(ANNUAL_MEANINGS), 'project_fields': dict(PROJECT_MEANINGS),
        'vintage_fields': dict(VINTAGE_MEANINGS), 'summary_fields': dict(SUMMARY_MEANINGS),
        'unique_optimum': 'A unique best common plan with at least one penny gap must be established by independent complete search before source admission. Catalog generation does not assert that it exists.',
        'source_scope': 'These are synthetic hypothetical investment and financing primitives. The NYU and Ofgem hashes retain ancestry only; no source financial forecast, optimum or task qualification is claimed.'}


def contract_markdown(contract):
    paragraphs = ['# Capital allocation contract', contract['units'],
                  contract['candidate_schedule_policy'], contract['diagnostic_continuation_policy'],
                  contract['opening_cashflow_policy'], contract['blank_policy'], *contract['rules']]
    for title, key in (('Annual accounts', 'annual_fields'), ('Standalone candidates', 'project_fields'),
                       ('Tax loss vintages', 'vintage_fields'), ('Summary', 'summary_fields')):
        paragraphs.append('## ' + title)
        paragraphs.extend(f'- `{name}`: {meaning}' for name, meaning in contract[key].items())
    paragraphs.extend((contract['unique_optimum'], contract['source_scope']))
    return '\n\n'.join(paragraphs) + '\n'


def fixed_plans(profile_id, catalog=DEFAULT_CATALOG):
    """A fixed, named diagnostic set, never an optimisation result."""
    checked = load_catalog(catalog)
    public, roles = _build(_profile(checked, profile_id))
    ids = [p['id'] for p in public['projects']]
    return {'empty': dict.fromkeys(ids, 0), 'all': dict.fromkeys(ids, 1),
        'first8': {pid: int(i < 8) for i, pid in enumerate(ids)},
        **{'cohort_' + cohort: {pid: int(role == cohort) for pid, role in zip(ids, roles)}
           for cohort in COHORTS}}


def diagnose_fixed_plans(profile_id, catalog=DEFAULT_CATALOG):
    """Forward-only optional diagnostics; no ranking or hidden best-plan field."""
    from .ledger import simulate
    public = build_spec(profile_id, catalog)
    results = []
    for name, plan in fixed_plans(profile_id, catalog).items():
        result = simulate(public, plan)
        results.append({'name': name, 'feasible': result['feasible'],
            'objective_pence': result['objective_pence'],
            'scenarios': {sid: {'feasible': row['feasible'], 'npv_pence': row['npv_pence'],
                'first_violation': row['first_violation']} for sid, row in result['scenarios'].items()}})
    return {'profile_id': profile_id, 'kind': 'predeclared_fixed_plan_forward_diagnostics',
        'results': results, 'optimisation_performed': False, 'unique_optimum_claimed': False,
        'source_admission_claimed': False, 'qualified': False}
