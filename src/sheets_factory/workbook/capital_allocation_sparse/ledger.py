"""Forward-only dimension adapter to the frozen original Decimal journal.

All financial postings are executed by the unchanged SHA-bound original
_scenario. This module evaluates one supplied plan and does not optimise,
rank plans, verify search coverage, or establish uniqueness.
"""
from copy import deepcopy
import hashlib
from pathlib import Path

from ..capital_allocation import ledger as original
from ..capital_allocation import spec as original_spec
from .spec import load_spec, require, validate_plan

UPSTREAM = {
    'ledger': '7e4079b311050e57371ac343967f3ed3e69912d4f70c67472342103c4a74ebf7',
    'spec': 'e943eac9e5f139b8957a86e4e5c1c679be5a5be7aa596cf17e9b1f9aa8eb0f94',
}


def validate_upstream():
    for name, module in (('ledger', original), ('spec', original_spec)):
        require(hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() == UPSTREAM[name],
                'The independent Decimal journal changed; review its sparse dimension adapter')


def simulate(specification, plan):
    """Evaluate a supplied plan; never search, rank, or select a plan."""
    validate_upstream()
    public = load_spec(specification)
    choices = validate_plan(public, plan)
    scenarios = {scenario['id']: original._scenario(public, scenario, choices)
                 for scenario in public['scenarios']}
    feasible = all(row['feasible'] for row in scenarios.values())
    return {'schema_version': 1, 'plan': deepcopy(choices), 'feasible': feasible,
            'scenarios': scenarios,
            'objective_pence': min(row['npv_pence'] for row in scenarios.values()) if feasible else None,
            'objective_kind': 'maximin_LP_net_present_value_pence',
            'optimisation_performed': False, 'unique_optimum_claimed': False}
