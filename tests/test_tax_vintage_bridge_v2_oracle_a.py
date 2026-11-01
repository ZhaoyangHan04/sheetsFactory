from fractions import Fraction as F
import importlib.util
from pathlib import Path

import pytest

from sheets_factory.workbook.associate_bridge_v1 import spec as bridge
from sheets_factory.workbook.tax_vintage_bridge_v2 import spec, oracle_a as a

fixture_spec = importlib.util.spec_from_file_location('_tax_vintage_A_raw_fixture', Path(__file__).with_name('test_tax_vintage_bridge_v2_spec.py'))
fixture = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(fixture)


def value(result, period, field, identity='E001', raw=False):
    return F(result['raw_cell_exact_values' if raw else 'economic_exact_values'][f'{identity}/{period}/{field}']['value'])


def test_fifo_expiry_current_inclusive_and_cash_lag_hand_journal():
    result = a.solve(fixture.toy(count=1))
    expected = {'tax_ordinary_before_losses': 38, 'loss_ordinary_used': F('15.2'),
                'tax_ordinary_after_losses': F('22.8'), 'current_tax': F('5.7'),
                'cash_tax_paid': 0, 'tax_payable_close': F('5.7'),
                'tax_lot_O01_ordinary_used': F('15.2'), 'tax_lot_O01_ordinary_close': F('24.8'),
                'loss_ordinary_close': F('204.8'), 'closing_cash': 10038,
                'net_income': F('32.3'), 'total_assets': 11038, 'total_liabilities_equity': 11038}
    for field, amount in expected.items():
        assert value(result, '2025Q1', field) == amount, field
    assert value(result, '2025Q2', 'loss_ordinary_expired') == F('24.8')
    assert value(result, '2025Q2', 'tax_lot_O02_ordinary_used') == F('17.2')
    assert value(result, '2025Q2', 'cash_tax_paid') == F('5.7')
    assert value(result, '2025Q3', 'tax_lot_O02_ordinary_used') == F('19.2')
    assert value(result, '2025Q4', 'loss_ordinary_expired') == F('13.6')


def test_two_pools_negative_creation_and_fifo_future_use_are_separate():
    result = a.solve(fixture.toy(count=1))
    assert value(result, '2026Q2', 'tax_investment_before_losses') == -3
    assert value(result, '2026Q2', 'tax_investment_after_losses') == 0
    assert value(result, '2026Q2', 'loss_investment_created') == 3
    assert value(result, '2026Q2', 'tax_lot_C05_investment_used') == 0
    assert value(result, '2026Q2', 'tax_lot_C05_investment_close') == 3
    assert value(result, '2026Q3', 'tax_lot_O04_investment_used') == F('1.3')
    assert value(result, '2026Q3', 'tax_lot_C05_investment_used') == F('1.5')
    assert value(result, '2026Q3', 'tax_lot_C05_investment_close') == F('1.5')
    assert value(result, '2026Q2', 'current_tax') == value(result, '2026Q2', 'tax_ordinary_after_losses') / 4


def test_assessment_due_does_not_move_when_cash_lag_changes():
    result = a.solve(fixture.toy(count=1))
    # At index6 the lag changes from1 to2. The index5 tax stays due at6;
    # new index6 tax is due at8, leaving no payment at7.
    assert value(result, '2026Q3', 'cash_tax_paid') == value(result, '2026Q2', 'current_tax')
    assert value(result, '2026Q4', 'cash_tax_paid') == 0
    assert value(result, '2027Q1', 'cash_tax_paid') == value(result, '2026Q3', 'current_tax')
    assert value(result, '2027Q4', 'tax_payable_close') == value(result, '2027Q3', 'current_tax') + value(result, '2027Q4', 'current_tax')


def test_current_loss_expires_only_after_its_inclusive_birth_term():
    base = fixture.fixture.toy(1)
    base['entities'][0]['cash_opex']['2025Q1'] = '100'
    public = spec.build(bridge.build(base, 'B05'), 'T01')
    result = a.solve(public)
    assert value(result, '2025Q1', 'loss_ordinary_created') == 52
    assert value(result, '2025Q1', 'tax_lot_C00_ordinary_used') == 0
    assert value(result, '2026Q1', 'tax_lot_C00_ordinary_close') == 52
    assert value(result, '2026Q2', 'loss_ordinary_expired') == 52


@pytest.mark.parametrize('case_id', spec.CASE_IDS)
def test_complete_scope_units_annual_closing_group_sums_and_all_bridges(case_id):
    public = fixture.toy(case_id)
    result = a.solve(public)
    assert result['kind'] == spec.RESULT_KIND and result['specification_sha256'] == spec.canonical_sha256(public)
    assert result['reconciliation_checks']['passed'] is True
    expected = set(dict(spec.points(public)))
    for name in ('economic_exact_values', 'raw_cell_exact_values', 'typed_2dp_values'):
        assert set(result[name]) == expected
    assert all(v == '0' for k, checks in result['reconciliation_checks'].items() if k.endswith('_residuals') for v in checks.values())
    for field in spec.NEW_FLOWS+spec.NEW_STOCKS:
        for period in (*spec.QUARTERS, 'FY2025', 'FY2026', 'FY2027'):
            assert value(result, period, field, 'PORTFOLIO') == sum(value(result, period, field, f'E{i:03d}') for i in range(1, 4))
        assert value(result, 'FY2027', field) == (sum(value(result, '2027Q'+str(q), field) for q in range(1, 5)) if field in spec.NEW_FLOWS else value(result, '2027Q4', field))
    assert value(result, '2026Q2', 'current_tax', 'E003') == value(result, '2026Q2', 'current_tax', 'E003', raw=True)*1000000
