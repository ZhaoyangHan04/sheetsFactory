from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from sheets_factory.workbook.associate_bridge_v1 import spec as bridge
from sheets_factory.workbook.tax_vintage_bridge_v2 import spec

module_spec = importlib.util.spec_from_file_location('_tax_vintage_raw_fixture', Path(__file__).with_name('test_associate_bridge_spec.py'))
fixture = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(fixture)


def toy(case_id='T01', count=3):
    return spec.build(bridge.build(fixture.toy(count), spec.bridge_case(case_id)), case_id)


def test_eight_raw_policies_are_deterministic_distinct_and_preserve_bridge():
    cases = []
    for case_id in spec.CASE_IDS:
        raw_bridge = bridge.build(fixture.toy(), spec.bridge_case(case_id))
        before = deepcopy(raw_bridge)
        public = spec.build(raw_bridge, case_id)
        assert raw_bridge == before == public['bridge']
        assert public == spec.build(raw_bridge, case_id)
        assert spec.validate(public) is public
        cases.append(public)
    # The bridge and vintage policy jointly define the financial material.
    assert len({spec.canonical_sha256({'bridge': x['bridge'], 'tax_policies': x['tax_policies']}) for x in cases}) == 8


def test_closed_vocabulary_scope_and_term_change_are_explicit():
    public = toy()
    assert len(spec.LOT_IDS) == 16 and len(spec.LOT_FIELDS) == 64
    assert len(spec.NEW_FLOWS+spec.NEW_STOCKS) == 14
    assert len(dict(spec.points(public))) == 3*450 + 2*390 + 5*15*14 + 3*12*64
    assert len(list(spec.points(public))) == len(dict(spec.points(public)))
    for policy in public['tax_policies'].values():
        assert len(policy['opening_lots']) == 4
        assert policy['terms'][0]['effective_index'] == 0
        assert policy['terms'][1]['effective_index'] in (6, 8)
        assert {t['cash_tax_lag'] for t in policy['terms']} == {1, 2}
        assert all(x['origin_index'] < 0 <= x['last_eligible_index'] for x in policy['opening_lots'])


@pytest.mark.parametrize('mutate', [
    lambda p: p['tax_policies']['E001']['opening_lots'][0].__setitem__('ordinary', '-1'),
    lambda p: p['tax_policies']['E001']['opening_lots'][0].__setitem__('ordinary', 'NaN'),
    lambda p: p['tax_policies']['E001']['opening_lots'][0].__setitem__('origin_index', True),
    lambda p: p['tax_policies']['E001']['opening_lots'][0].__setitem__('last_eligible_index', 99),
    lambda p: p['tax_policies']['E001']['terms'][0].__setitem__('ordinary_cap_bp', True),
    lambda p: p['tax_policies']['E001']['terms'][0].__setitem__('cash_tax_lag', 0),
    lambda p: p['tax_policies']['E001']['terms'][1].__setitem__('carry_quarters', 2),
    lambda p: p['tax_policies'].pop('E001'),
    lambda p: p.__setitem__('case_id', 'T02'),
])
def test_changed_raw_assignments_and_unknown_inputs_reject(mutate):
    public = toy()
    mutate(public)
    with pytest.raises(ValueError):
        spec.validate(public)


def test_builder_rejects_an_undeclared_bridge_case():
    with pytest.raises(ValueError):
        spec.build(bridge.build(fixture.toy(), 'B04'), 'T01')
