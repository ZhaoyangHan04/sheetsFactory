"""Real financial feedback checks, independent of the Excel implementation."""
from copy import deepcopy
from decimal import Decimal as D

import pytest

from sheets_factory.workbook.contingent_recovery.contract import ACCOUNTING, ITERATION
from sheets_factory.workbook.derived_regulatory.ledger import simulate, annual_bridge, LEASE_FIELDS
from sheets_factory.workbook.derived_regulatory.schema import CONTINGENT_ANNUAL_FIELDS


def example():
    years = list(range(2024, 2044))
    spec = {'years': years, 'batches': [{'id': 'A', 'paid_year': 2024,
        'commission_year': 2024, 'regulatory_life': 10, 'tax_pool': 'General',
        'real_cost': '100000', 'nominal_cost': '100000'}],
        'parameters': {'gearing': '0', 'loss_carry_years': 1, 'loss_use_cap': '.8',
            'claim_lag_years': 2, 'structures_tax_life': 11, 'lease_allowable_fraction': '.85'},
        'annual_inputs': [{'year': year, 'price_index': '1', 'real_wacc': '0',
            'tax_rate': '.25', 'claim_carry_rate': '0', 'debt_rate': '.05',
            'collection_cap_nominal': '1000000', 'disallowance_real': '0',
            'general_rate': '0', 'special_rate': '0', 'general_transfer_fraction': '0'}
            for year in years]}
    contracts = [{'lease_id': f'P0{i}', 'active': i == 1, 'rate': '.01' if i == 1 else '0',
                  'threshold': '0', 'annual_cap': '10000' if i == 1 else '0',
                  'rounding_quantum': '100', 'rounding_mode': 'ROUND_HALF_UP'}
                 for i in range(1, 5)]
    contingent = {'schema_version': 1, 'scenario_id': 'hand-calculated-contingent-example',
        'currency': 'GBP_nominal', 'feedback_basis': 'same_year_total_recovery_entitlement',
        'accounting': deepcopy(ACCOUNTING), 'iteration_policy': deepcopy(ITERATION),
        'public_rules': ['Explicit example terms, current cash expense excluded from fixed lease PV.'],
        'annual_terms': [{'year': year, 'eligible_fraction': '.85', 'contracts': deepcopy(contracts)}
                         for year in years]}
    lease = {year: {field: D(0) for field in LEASE_FIELDS} for year in years}
    return spec, contingent, lease


def test_hand_calculated_same_year_rent_tax_and_claim_change_actual_economics():
    spec, contingent, lease = example()
    plain = simulate(spec, external_lease_annual=lease)
    result = simulate(spec, external_lease_annual=lease, contingent_spec=contingent)
    row = result['annual'][0]
    assert row['variable_lease_cash'] == D(100)
    assert row['variable_lease_allowance'] == D(85)
    assert row['pre_allowance_taxable_profit'] == D(4985)
    assert row['current_tax_allowance'] == D('1661.67')
    assert row['capital_entitlement'] == D('6746.67')
    assert row['owner_capital'] == D('101761.67')
    assert row['net_income'] == D(-15)
    assert row['total_assets'] == row['total_equity'] == D('101746.67')
    assert row['owner_capital'] - plain['annual'][0]['owner_capital'] == D(95)
    assert row['lease_cash_rent'] == row['lease_rou_close'] == row['lease_liability_close'] == 0
    assert result['contingent_recovery']['annual'][2024]['year'] == 2024
    assert result['contingent_recovery']['all_years_unique']
    assert all(result['checks'].values())


def test_variable_cash_is_operating_and_journal_has_no_unclosed_expense_account():
    spec, contingent, lease = example()
    result = simulate(spec, external_lease_annual=lease, contingent_spec=contingent)
    bridge = annual_bridge(spec, result)
    expense_balance = D(0)
    for entry in result['journal']:
        assert sum(entry['debit_positive_entries'].values(), D(0)) == 0
        expense_balance += entry['debit_positive_entries'].get('variable_lease_expense', D(0))
    assert expense_balance == 0
    assert set(result['annual'][0]) == set(CONTINGENT_ANNUAL_FIELDS)
    for year, row in bridge.items():
        assert row['cfo'] == (row['claims_receipts'] - row['debt_interest']
                             - row['current_tax_allowance'] - row['lease_cash_rent']
                             - row['variable_lease_cash'])
        assert row['cfo'] + row['cfi'] + row['cff'] == row['cash_close'] == 0


def test_default_none_preserves_the_original_complete_result():
    spec, _, lease = example()
    assert simulate(spec) == simulate(spec, contingent_spec=None)
    assert simulate(spec, external_lease_annual=lease) == simulate(spec, external_lease_annual=lease, contingent_spec=None)


def test_contingent_recovery_rejects_missing_base_lease_or_different_horizon():
    spec, contingent, lease = example()
    with pytest.raises(ValueError, match='base-lease'):
        simulate(spec, contingent_spec=contingent)
    spec['years'] = spec['years'][:-1]
    with pytest.raises(ValueError, match='every programme reporting year'):
        simulate(spec, external_lease_annual=lease, contingent_spec=contingent)


def test_public_policy_explains_total_entitlement_and_no_double_counted_lease_bridge():
    from sheets_factory.workbook.derived_regulatory.policy import public_policy
    assert public_policy(include_leases=True) == public_policy(include_leases=True, include_contingent=False)
    text = public_policy(include_leases=True, include_contingent=True)
    assert 'TOTAL current-year claim' in text
    assert 'do not enter the fixed-lease payment schedule' in text
    assert 'additional CFO outflow' in text
    with pytest.raises(ValueError, match='base-lease'):
        public_policy(include_contingent=True)


def test_explicit_collection_case_changes_supplied_inputs_without_altering_original_rows():
    from sheets_factory.workbook.derived_regulatory.source import apply_annual_overrides
    spec, _, _ = example()
    original=deepcopy(spec['annual_inputs'])
    result=apply_annual_overrides(original,{'2032':{'collection_cap_nominal':'50000000.00'}})
    assert original==spec['annual_inputs']
    assert result[8]['collection_cap_nominal']=='50000000.00'
    assert result[:8]==original[:8] and result[9:]==original[9:]


@pytest.mark.parametrize('patch',[
    {'2044':{'collection_cap_nominal':'50000000'}},
    {'2032':{'net_income':'50000000'}},
    {'2032':{'year':'2033'}},
    {'2032':{'collection_cap_nominal':'NaN'}},
    {'2032':{'collection_cap_nominal':'1.001'}},
    {'2032':{'tax_rate':'1'}},
    {'2032':{'price_index':'0'}},
    {'2032':{'collection_cap_nominal':True}},
])
def test_annual_case_rejects_hidden_results_wrong_dates_and_invalid_terms(patch):
    from sheets_factory.workbook.derived_regulatory.source import apply_annual_overrides
    spec, _, _ = example()
    with pytest.raises(ValueError):apply_annual_overrides(spec['annual_inputs'],patch)
