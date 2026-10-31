"""Two predeclared raw revenue profiles; no finance or optimization results."""
import random

from . import catalog_correlated, spec

PROFILE_ORDER = ('C02', 'C03')
PROFILES = {
    'C02': {'seed': 20261102, 'revenue_jitter_pence': 50_000},
    'C03': {'seed': 20261103, 'revenue_jitter_pence': 500_000},
}


def build_spec(profile_id):
    spec.require(type(profile_id) is str and profile_id in PROFILES, 'Use one predeclared competitive profile')
    policy = PROFILES[profile_id]
    public = catalog_correlated.build_spec(policy['seed'])
    # This is a separate generator instance from every correlated raw stream.
    rng = random.Random(policy['seed'])
    spread = policy['revenue_jitter_pence']
    for project in public['projects']:
        project['base_annual_revenue_pence'] = project['asset_cost_pence']*3000//spec.BP + rng.randint(-spread, spread)
        project['base_annual_opex_pence'] = project['base_annual_revenue_pence']*6500//spec.BP
    public['provenance'] = {'hypothetical': True, 'ancestor_sha256': [],
        'description': f'Prospectively fixed {profile_id}, seed {policy["seed"]}: the same-seed correlated raw '
        f'contracts and capacities are retained. A separate random.Random(seed) instance supplies one independent '
        f'integer revenue adjustment per ordered project in [-{spread}, {spread}] GBP pence to cost*3000//10000. '
        'Operating expense is updated revenue*6500//10000. These are new raw assumptions; no posted NPV, '
        'financial forward, selected plan, solver result or model outcome enters their construction.'}
    return spec.load_spec(public)
