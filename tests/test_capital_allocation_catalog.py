from copy import deepcopy
import json
from pathlib import Path
import random

import pytest

from sheets_factory.workbook.capital_allocation.catalog import generate_specs
from sheets_factory.workbook.capital_allocation.spec import load_spec

ROOT = Path(__file__).resolve().parents[1]


def catalog():
    return json.loads((ROOT / 'config/capital_allocation_catalog_v1.json').read_text())


def test_all_declared_profiles_generate_bounded_reproducible_public_primitives():
    config = catalog(); before = deepcopy(config)
    first = generate_specs(config)
    random.seed(1337)
    assert generate_specs(config) == first and config == before
    assert [row['profile_id'] for row in first] == [f'K{i:02d}' for i in range(1, 11)]
    assert len({json.dumps(row['spec'], sort_keys=True) for row in first}) == 10
    for row in first:
        spec = load_spec(row['spec'])
        assert len(spec['projects']) == 18 and len(spec['scenarios']) == 3
        assert all(p['sale_year'] <= 2043 and p['annual_revenue_pence'][str(p['commission_year'])] == 0
                   for p in spec['projects'])
        assert any(p['annual_revenue_pence'][str(p['commission_year'] + 1)]
                   < p['annual_opex_pence'][str(p['commission_year'] + 1)] for p in spec['projects'])


@pytest.mark.parametrize('change', ['missing_profile', 'reversed', 'extra_field', 'money_units', 'rate', 'bad_lifetime'])
def test_catalog_rejects_dimension_order_units_and_extra_fields(change):
    config = catalog()
    if change == 'missing_profile': config['profiles'].pop()
    elif change == 'reversed': config['profiles'].reverse()
    elif change == 'extra_field': config['profiles'][0]['best_plan'] = 123
    elif change == 'money_units': config['profiles'][0]['opening_cash_gbp'] = '5000000'
    elif change == 'rate': config['profiles'][0]['tax_rate'] = '1.1'
    elif change == 'bad_lifetime': config['profiles'][0]['loss_carry_years'] = True
    with pytest.raises(ValueError): generate_specs(config)
