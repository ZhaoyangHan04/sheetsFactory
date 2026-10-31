"""Three predeclared raw profiles between the earlier competitive spreads."""
import random

from . import catalog_correlated, spec

PROFILE_ORDER = ('M01', 'M02', 'M03')
PROFILES = {
    'M01': {'seed': 20261104, 'revenue_jitter_pence': 100_000},
    'M02': {'seed': 20261105, 'revenue_jitter_pence': 150_000},
    'M03': {'seed': 20261106, 'revenue_jitter_pence': 250_000},
}


def build_spec(profile_id):
    spec.require(type(profile_id) is str and profile_id in PROFILES,
        'Use one of the three predeclared intermediate competitive profiles')
    policy = PROFILES[profile_id]
    public = catalog_correlated.build_spec(policy['seed'])
    rng = random.Random(policy['seed'])
    spread = policy['revenue_jitter_pence']
    for project in public['projects']:
        revenue = project['asset_cost_pence'] * 3000 // spec.BP + rng.randint(-spread, spread)
        project['base_annual_revenue_pence'] = revenue
        project['base_annual_opex_pence'] = revenue * 6500 // spec.BP
    public['provenance'] = {
        'hypothetical': True, 'ancestor_sha256': [],
        'description': f'Prospectively fixed {profile_id}, seed {policy["seed"]}: all same-seed correlated raw '
        'contracts and capacities are retained. A separate random.Random(seed) generator supplies one '
        f'independent integer revenue adjustment per ordered project in [-{spread}, {spread}] GBP pence. '
        'Revenue is cost*3000//10000 plus that adjustment; operating expense is updated revenue*6500//10000. '
        'These are new hypothetical raw assumptions. No NPV, financial forward result, selected plan, '
        'optimizer result or model outcome enters the raw construction.'}
    return spec.load_spec(public)
