"""Pure nine-case research contract over one retained hypothetical N360 source.

This module performs no financial forward, optimisation, workbook or service call.
The fixed cases reuse the completed source's independent A/B financial matrices.
Each alternative has its own complete binary plan; decisions do not carry over.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json

from ..linear_capital_scaled import spec, model_a, model_b

KIND = 'hypothetical_reused_N360_independent_budget_capacity_sensitivity'
VERSION = 1
BASE_LOGICAL_SPEC_SHA = '98661c3a275599edb96ab33fd97ba2131e7db16fcb807076742e23ee82eb29cc'
FACTORS = (90, 100, 110)
CASES = tuple({'id': f'B{budget}_C{capacity}', 'budget_percent': budget,
               'capacity_percent': capacity} for budget in FACTORS for capacity in FACTORS)
POLICY = {
    'business': 'Nine alternative board approvals for the same hypothetical project portfolio. Each alternative independently chooses projects to maximise the original investor NPV.',
    'budget': 'The budget percentage changes only initial sponsor equity. It does not change annual new LP funding, debt, regional or sector exposure limits.',
    'capacity': 'The capacity percentage changes all six physical resource limits in every scenario and year. Project usage is unchanged.',
    'integers': 'Apply the percentage to each original integer limit and round down once to whole pence or resource units. All other constraints and financial contracts are unchanged.',
    'independence': 'Each alternative has its own 360 binary choices, all 941 constraints and scenario cash reports. There is no shared funding or carried decision between alternatives.',
    'finance': 'Compute the common project financial ledgers and objective coefficients once. Reuse them in all nine alternatives; do not copy nine project ledgers.',
    'totals': 'Report each alternative separately. Do not average ratios or optimise the sum of alternative objectives. Identical optimal plans across alternatives are allowed.',
}
PROVENANCE = 'Explicit hypothetical reuse of completed L360-P02; not a new independent project source'
GOLD_POLICY = 'Each of all nine fixed cases requires a unique exact optimal best, a complete-winner-excluded exact optimal runner with an integer objective gap of at least one penny, and independent selected-plan financial checks; no case filtering.'
GEOMETRY = {'project_financial_ledgers': 1, 'case_plan_binary_cells': 360 * 9,
            'cases': 9, 'constraints_per_case': 941, 'scenario_year_reports': 9 * 3 * 20}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def expected_rows(public):
    """The complete row identity, RHS and metadata census; no coefficients computed."""
    limits = public['shared_limits']; rows = {}
    def put(identity, family, limit, scenario=None, year=None):
        rows[identity] = (family, scenario, year, limit)
    put('initial_sponsor_equity', 'initial_sponsor_equity', limits['initial_sponsor_equity_pence'])
    for sid in public['scenario_ids']:
        for year in public['years']:
            for family, field in (('annual_new_lp', 'annual_new_lp_pence'),
                                  ('annual_debt_close', 'annual_debt_close_pence')):
                put(f'{family}:{sid}:{year}', family, limits[field][sid][str(year)], sid, year)
            for resource in public['resource_ids']:
                put(f'resource:{resource}:{sid}:{year}', 'resource',
                    limits['resource_capacity_units'][resource][sid][str(year)], sid, year)
    for year in public['years']:
        for family, ids, field in (('region_exposure', public['region_ids'], 'region_exposure_pence'),
                                    ('sector_exposure', public['sector_ids'], 'sector_exposure_pence')):
            for identity in ids:
                put(f'{family}:{identity}:{year}', family, limits[field][identity][str(year)], None, year)
    for group in public['exclusivity_groups']:
        put('exclusivity:' + group['id'], 'exclusivity', 1)
    for edge in public['prerequisites']:
        put('prerequisite:' + edge['id'], 'prerequisite', 0)
    return rows


def validate_base(public, model, implementation):
    public = spec.load_spec(public)
    require(public['dimension_mode'] == 'production' and len(public['project_ids']) == 360,
            'This research contract requires the complete N360 source')
    (model_a if implementation == 'A' else model_b).validate_model(model)
    require(implementation in ('A', 'B') and model['project_ids'] == public['project_ids']
            and model['specification_sha256'] == spec.canonical_sha256(public),
            'Bind the retained matrix to its exact original public specification')
    expected = expected_rows(public)
    require(len(expected) == len(model['rows']) == 941
            and Counter(r['family'] for r in model['rows']) == spec.PRODUCTION_COUNTS
            and set(expected) == {r['id'] for r in model['rows']},
            'All 941 original business rows are required, including their exact identities')
    for row in model['rows']:
        require((row['family'], row['scenario_id'], row['year'], row['limit']) == expected[row['id']],
                'The original business row metadata or provided capacity differs')
    return public


def build_contract(public, base_a, base_b):
    """Freeze all nine case identities before any future native search."""
    public = validate_base(public, base_a, 'A'); validate_base(public, base_b, 'B')
    require(spec.canonical_sha256(public) == BASE_LOGICAL_SPEC_SHA,
            'This prospective reuse binds the original completed L360-P02 public assumptions')
    require({k: v for k, v in base_a.items() if k != 'universe_sha256'} ==
            {k: v for k, v in base_b.items() if k != 'universe_sha256'},
            'Retained independent A/B project coefficients and all original rows must agree')
    return {'kind': KIND, 'version': VERSION,
        'base_specification_sha256': spec.canonical_sha256(public),
        'base_model_sha256': {'A': canonical_sha256(base_a), 'B': canonical_sha256(base_b)},
        'cases': deepcopy(list(CASES)), 'case_order': [c['id'] for c in CASES],
        'public_policy': dict(POLICY),
        'output_geometry': dict(GEOMETRY), 'source_provenance': PROVENANCE,
        'future_gold_policy': GOLD_POLICY,
        'different_winner_required': False, 'reference_admission': False, 'checked_optimal': False,
        'financial_forward_calls': 0, 'optimizer_calls': 0, 'LO_calls': 0, 'model_calls': 0,
        'qualified': False, 'difficulty_claimed': False}


def validate_contract(public, contract, model=None, implementation=None):
    require(isinstance(contract, dict) and contract.get('kind') == KIND
            and type(contract.get('version')) is int and contract['version'] == VERSION,
            'Unknown two-axis research contract')
    require(set(contract) == {'kind', 'version', 'base_specification_sha256', 'base_model_sha256',
            'cases', 'case_order', 'public_policy', 'output_geometry', 'source_provenance',
            'future_gold_policy', 'different_winner_required', 'reference_admission', 'checked_optimal',
            'financial_forward_calls', 'optimizer_calls', 'LO_calls', 'model_calls', 'qualified', 'difficulty_claimed'}
            and set(contract['base_model_sha256']) == {'A', 'B'}
            and contract['output_geometry'] == GEOMETRY and contract['source_provenance'] == PROVENANCE
            and contract['future_gold_policy'] == GOLD_POLICY
            and contract['difficulty_claimed'] is False
            and all(type(contract[k]) is int and contract[k] == 0
                    for k in ('financial_forward_calls', 'optimizer_calls', 'LO_calls', 'model_calls')),
            'Keep the pure hypothetical scope and complete declared output geometry')
    require(contract['base_specification_sha256'] == BASE_LOGICAL_SPEC_SHA
            == spec.canonical_sha256(spec.load_spec(public))
            and contract['cases'] == list(CASES) and contract['case_order'] == [c['id'] for c in CASES]
            and contract['public_policy'] == POLICY and contract['reference_admission'] is False
            and contract['checked_optimal'] is False and contract['qualified'] is False
            and contract['different_winner_required'] is False,
            'Keep the complete fixed independent nine-case business policy')
    if model is not None:
        validate_base(public, model, implementation)
        require(canonical_sha256(model) == contract['base_model_sha256'][implementation],
                'A retained matrix changed after prospective case freezing')
    return contract
