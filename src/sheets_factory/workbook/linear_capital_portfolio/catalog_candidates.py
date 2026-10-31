"""Twenty prospective raw candidates; no finance, optimizer or model results."""
from copy import deepcopy
import json
from pathlib import Path
import random

from . import catalog, catalog_correlated, spec

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CATALOG = ROOT/'config/linear_capital_candidate_catalog_v1.json'
PROFILE_ORDER = tuple(f'P{i:02d}' for i in range(1, 21))
GENERATION_POLICY = 'same_seed_correlated_contracts_and_independent_revenue_jitter_v1'
REFERENCE_POLICY = {
    'private_solver_seconds_per_job': 3600, 'retries': 0,
    'independent_financial_implementations': ['Fraction_A', 'Decimal_B'],
    'independent_integer_matrices_required': 2,
    'all_candidate_scenarios_must_be_feasible': True,
    'all_financial_fields_and_reduced_coefficients_must_agree': True,
    'best_and_excluded_winner_runner_must_be_OPTIMAL': True,
    'runner_excludes_complete_winner_plan': True,
    'unique_posted_objective_gap_at_least_pence': 1,
    'solver_status_is_not_independently_verified_formal_proof': True}
DENSITY_GATE = {'minimum': 80, 'maximum': 160, 'public_cardinality_constraint': False}
CANDIDATE_SCOPE = {'research_candidate_pool_only': True, 'candidate_pool_is_not_release_set': True,
    'future_model_testing_requires_separate_prospective_cohort_freeze': True,
    'model_outcome_based_membership_selection_permitted': False,
    'confirmation_or_publication_authorized': False}


def exact(value, expected):
    """JSON types are significant: True cannot stand in for integer one."""
    return spec.canonical_sha256(value) == spec.canonical_sha256(expected)


def load_catalog(value=DEFAULT_CATALOG):
    result = deepcopy(value) if type(value) is dict else json.loads(Path(value).read_text(encoding='utf-8'))
    expected = {'kind': 'linear_capital_prospective_raw_candidate_catalog', 'version': 1,
        'catalog_id': 'linear_capital_candidates_v1', 'generation_policy': GENERATION_POLICY,
        'profile_order': list(PROFILE_ORDER), 'profiles': [
            {'profile_id': pid, 'seed': 20261201+i, 'revenue_jitter_pence': 150_000 if i < 10 else 100_000}
            for i, pid in enumerate(PROFILE_ORDER)],
        'selection_density_admission': DENSITY_GATE, 'reference_policy': REFERENCE_POLICY,
        'candidate_scope': CANDIDATE_SCOPE}
    spec.require(type(result) is dict and exact(result, expected),
        'Use the complete prospectively fixed P01-P20 catalog; preserve its order, seeds, spreads and gates')
    return result


def profile_order(value=DEFAULT_CATALOG):
    return tuple(load_catalog(value)['profile_order'])


def profile_policy(profile_id, value=DEFAULT_CATALOG):
    configuration = load_catalog(value)
    spec.require(type(profile_id) is str and profile_id in PROFILE_ORDER,
        'Use one of the twenty predeclared raw candidate profiles')
    return deepcopy(configuration['profiles'][PROFILE_ORDER.index(profile_id)])


def build_spec(profile_id, value=DEFAULT_CATALOG):
    policy = profile_policy(profile_id, value)
    public = catalog_correlated.build_spec(policy['seed'])
    rng = random.Random(policy['seed'])
    spread = policy['revenue_jitter_pence']
    for project in public['projects']:
        revenue = project['asset_cost_pence']*3000//spec.BP + rng.randint(-spread, spread)
        project['base_annual_revenue_pence'] = revenue
        project['base_annual_opex_pence'] = revenue*6500//spec.BP
    public['provenance'] = {'hypothetical': True, 'ancestor_sha256': [],
        'description': f'Prospectively fixed raw candidate {profile_id}, seed {policy["seed"]}: same-seed '
        'correlated contracts and capacities are retained. A separate random.Random(seed) instance supplies '
        f'one integer revenue adjustment per ordered project in [-{spread}, {spread}] GBP pence to '
        'cost*3000//10000. Operating expense is updated revenue*6500//10000. These are hypothetical '
        'provided assumptions; no financial forward, posted NPV, selected plan, optimizer result or model '
        'outcome enters their construction.'}
    return spec.load_spec(public)


def diagnostic_plans(profile_id, value=DEFAULT_CATALOG, *, public=None):
    policy = profile_policy(profile_id, value)
    public = build_spec(profile_id, value) if public is None else spec.load_spec(public)
    return catalog.diagnostic_plans(public, seed=policy['seed'])
