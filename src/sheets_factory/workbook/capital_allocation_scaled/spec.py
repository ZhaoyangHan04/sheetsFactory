"""Public typed capital contract; no financial calculation or enumeration.

The original eighteen-project schema remains accepted byte-for-byte. Larger
prospective specifications use the same pence, FIFO, funding and NPV policy.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

SCALE = 10**12
YEARS = tuple(range(2024, 2044))
PROJECT_COUNTS = (18, 26, 28, 30)
SCENARIO_IDS = ('S01', 'S02', 'S03')
RAW_ANCESTORS = {
    'NYU': 'df8f9e91cc53afe2bdb33cf39b8f2719206ac03b6a5031f1858f82235ea944c9',
    'Ofgem': '2f02bfdf2c4c85449129add05038fb1cbc10ad4ea716e9571a7dba0ea3642ce8',
}
RECORD_FORMAT = '<IIqqq'
RECORD_BYTES = 32
CHUNK_RECORDS = 65536
NULL_NPV = -(2**63)
CONTRACT = (
    'One shared binary plan governs all three independent scenario states. Money is integer GBP pence; rates and factors are integer numerators over10^12.',
    'Post nearest pence with half ties away from zero. Pay capex in commission FY; operations/depreciation start next FY, include sale FY, and sale follows depreciation. Round original cost/life, clamp to remaining basis, and use final-life residual. NAV is a collateral memo only.',
    'Interest uses opening bank principal. Base=min(facility,prior certified NAV*advance*(1-haircut)), rounded once; FY2043 base/minimum are zero. First mandatory margin, then optional repayment from excess cash, then base-limited draw, then bounded cumulative LP call. Funding gaps are infeasible.',
    'Expire losses before v+N+1 activity; use surviving prior losses FIFO, then current tax; negative taxable profit creates current-year loss. No deferred tax asset. Equity-capped cash distribution returns capital first and then retained profit; calls permanently consume commitment.',
    'Every project sells by FY2043; feasible terminal cash, bank and project book are zero. The only objective is the lowest of three feasible LP NPVs. Round once after summing all annual (distribution-call)*discount numerators AND subtracting opening_cash*10^12; never round annual PV or move t0 outside final rounding.',
    'No hidden tie-break: a source requires one best plan and at least one penny gap to the next feasible plan. Sorting masks can order records, never choose among tied economic optima.',
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def project_ids(count):
    require(type(count) is int and count in PROJECT_COUNTS, 'Unsupported public project dimension')
    return tuple(f'P{i:02d}' for i in range(1, count + 1))


def _keys(value, names, label):
    require(isinstance(value, dict) and set(value) == set(names), label + ' fields differ')


def _int(value, lo, hi, label):
    require(type(value) is int and lo <= value <= hi, label + ' requires a bounded literal integer')


def _annual(value, lo, hi, label):
    _keys(value, (str(y) for y in YEARS), label)
    for year in YEARS:
        _int(value[str(year)], lo, hi, label + '/' + str(year))


def load_spec(value):
    public = json.loads(Path(value).read_text()) if isinstance(value, (str, Path)) else deepcopy(value)
    _keys(public, ('schema_version', 'currency', 'monetary_unit', 'years', 'opening_cash_pence',
        'minimum_cash_pence', 'lp_commitment_pence', 'facility_limit_pence', 'advance_rate_p12',
        'tax_rate_p12', 'tax_loss_carry_years', 'discount_factors_p12', 'projects', 'scenarios', 'provenance'), 'Public specification')
    require(type(public['schema_version']) is int and public['schema_version'] == 1
            and public['currency'] == 'GBP' and public['monetary_unit'] == 'pence'
            and public['years'] == list(YEARS) and all(type(y) is int for y in public['years']),
            'Unsupported public calendar or units')
    for key in ('opening_cash_pence', 'minimum_cash_pence', 'lp_commitment_pence', 'facility_limit_pence'):
        _int(public[key], 0, 10**11, key)
    require(public['opening_cash_pence'] >= public['minimum_cash_pence'], 'Opening cash must meet its minimum')
    for key in ('advance_rate_p12', 'tax_rate_p12'):
        _int(public[key], 0, SCALE, key)
    _int(public['tax_loss_carry_years'], 1, 20, 'tax_loss_carry_years')
    _annual(public['discount_factors_p12'], 1, SCALE, 'discount_factors_p12')
    discounts = [public['discount_factors_p12'][str(y)] for y in YEARS]
    require(discounts == sorted(discounts, reverse=True), 'Discount factors must not increase')
    projects = public['projects']
    require(isinstance(projects, list) and len(projects) in PROJECT_COUNTS
            and all(isinstance(p, dict) for p in projects), 'Supported complete project records are required')
    require([p.get('id') for p in projects] == list(project_ids(len(projects))), 'Project IDs must be complete and ordered')
    for p in projects:
        _keys(p, ('id', 'commission_year', 'sale_year', 'acquisition_cost_pence', 'depreciation_years',
            'annual_revenue_pence', 'annual_opex_pence', 'sale_proceeds_pence'), p['id'])
        _int(p['commission_year'], 2024, 2042, 'commission_year')
        _int(p['sale_year'], p['commission_year'] + 1, 2043, 'sale_year')
        _int(p['acquisition_cost_pence'], 1, 10**9, 'acquisition_cost_pence')
        _int(p['sale_proceeds_pence'], 0, 10**9, 'sale_proceeds_pence')
        _int(p['depreciation_years'], 1, 20, 'depreciation_years')
        for field in ('annual_revenue_pence', 'annual_opex_pence'):
            _annual(p[field], 0, 10**9, field)
            require(all(p[field][str(y)] == 0 for y in YEARS if not p['commission_year'] < y <= p['sale_year']),
                    'Operating primitives must be zero outside the project operating period')
    scenarios = public['scenarios']
    require(isinstance(scenarios, list) and all(isinstance(s, dict) for s in scenarios)
            and [s.get('id') for s in scenarios] == list(SCENARIO_IDS), 'All three ordered scenarios are required')
    for s in scenarios:
        _keys(s, ('id', 'revenue_factors_p12', 'opex_factors_p12', 'nav_factors_p12',
            'sale_factors_p12', 'bank_rates_p12', 'haircuts_p12'), s['id'])
        for field in ('revenue_factors_p12', 'opex_factors_p12', 'nav_factors_p12', 'sale_factors_p12'):
            _annual(s[field], 0, 3 * SCALE, field)
        for field in ('bank_rates_p12', 'haircuts_p12'):
            _annual(s[field], 0, SCALE, field)
    _keys(public['provenance'], ('kind', 'raw_ancestors'), 'provenance')
    require(public['provenance']['kind'] == 'synthetic_capital_allocation_extension'
            and public['provenance']['raw_ancestors'] == RAW_ANCESTORS,
            'Raw ancestors are provenance only, with exact immutable identities')
    return public


def active_indices(public, active_project_ids=None):
    ids = project_ids(len(public['projects']))
    if active_project_ids is None:
        return list(range(len(ids)))
    chosen = list(active_project_ids)
    require(1 <= len(chosen) <= 8 and all(type(p) is str and p in ids for p in chosen)
            and chosen == [p for p in ids if p in chosen],
            'Toy enumeration requires one to eight distinct project IDs in public order')
    return [ids.index(p) for p in chosen]
