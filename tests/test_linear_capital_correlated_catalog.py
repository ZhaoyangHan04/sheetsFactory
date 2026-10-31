import pytest

from sheets_factory.workbook.linear_capital_portfolio import catalog_correlated as catalog, spec


def test_standardized_contracts_are_frozen_raw_assumptions_not_financial_outcomes():
    s = catalog.build_spec()
    assert spec.canonical_sha256(s) == spec.canonical_sha256(catalog.build_spec())
    assert len(s['projects']) == 240
    for field in ('t0_ltv_bp', 'operating_start_year', 'depreciation_years', 'bank_rate_bp',
                  'debt_policy', 'debt_maturity_year', 'tax_rate_bp', 'discount_rate_bp'):
        assert len({p[field] for p in s['projects']}) == 1
    assert all(abs(p['base_annual_revenue_pence'] - p['asset_cost_pence']*3000//spec.BP) <= 50 for p in s['projects'])
    assert s['provenance']['ancestor_sha256'] == []


def test_complete_dated_resource_capacity_geometry_and_maturity():
    s = catalog.build_spec()
    limits = s['shared_limits']
    for sid in s['scenario_ids']:
        assert limits['annual_debt_close_pence'][sid]['9'] > 0
        assert limits['annual_debt_close_pence'][sid]['10'] == limits['annual_debt_close_pence'][sid]['20'] == 0
        for resource in s['resource_ids']:
            for year in s['years']:
                total = sum(p['resource_usage_units'][resource][sid][str(year)] for p in s['projects'])
                value = limits['resource_capacity_units'][resource][sid][str(year)]
                assert total*4400//spec.BP <= value <= total*4500//spec.BP
    for field in ('region_exposure_pence', 'sector_exposure_pence'):
        assert all(row['15'] == row['20'] == 0 for row in limits[field].values())


@pytest.mark.parametrize('seed', [True, -1, 2**32, '20261101'])
def test_noninteger_or_out_of_range_seed_rejects(seed):
    with pytest.raises(ValueError, match='bounded integer'):
        catalog.build_spec(seed)
