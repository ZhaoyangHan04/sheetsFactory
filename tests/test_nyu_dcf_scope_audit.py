"""Independent tiny cash/capital/return examples; no engine or formula replay."""
from decimal import Decimal
from copy import deepcopy

import pytest

from sheets_factory.workbook import nyu_dcf_scope_audit as audit
from sheets_factory.workbook.compare import normalize_value

D = Decimal


@pytest.fixture
def tiny():
    inputs = {key: 'No' for key in audit.NO_FLAGS}
    inputs.update({'B11': 100, 'B12': 20, 'B14': 100, 'B15': 50, 'B18': 50,
        'B19': 0, 'B20': 0, 'B21': 10, 'B22': 5, 'B23': D('.2'),
        'B24': D('.25'), 'B34': D('.02'), 'B54': D('.5'), 'B53': 'V', 'B57': 1})
    anchors = {}
    for year, col in enumerate(audit.YEARS, 1):
        revenue, ebit = D(100+5*year), D(20+year)
        nopat, reinvestment = ebit*D('.8'), D(2)
        discount = D('.9')**year
        rows = {2: D('.05'), 3: revenue, 5: ebit, 6: D('.2'), 7: nopat,
            8: reinvestment, 9: nopat-reinvestment, 12: D('.1'),
            13: discount, 14: (nopat-reinvestment)*discount}
        anchors.update({audit.address(audit.V, col+str(row)): value for row, value in rows.items()})
    tails = {'M7': D('22.95'), 'M8': D('4.59'), 'M9': D('18.36'), 'B16': D('18.36'),
        'B18': D(500), 'B19': D(200), 'B20': D(800), 'B21': D(1000), 'B24': D(1000),
        'B29': D(1000), 'B31': D(1000), 'B33': D(100)}
    anchors.update({audit.address(audit.V, cell): value for cell, value in tails.items()})
    assert len(anchors) == 112
    return inputs, anchors


def test_full97_census_and_business_capital_returns_have_correct_timing(tiny):
    inputs, anchors = tiny
    result = audit.derive_business(inputs, anchors)
    assert len(result) == 97 and set(result) == audit.business_addresses()
    assert result['Valuation output!C39'] == 102
    assert result['Valuation output!L39'] == 120
    assert result['Valuation output!C40'] == D('.168')
    assert normalize_value(result['Valuation output!L40']) == normalize_value(D(24)/118)
    assert result['Diagnostics!C27'] == D('.4')
    assert result['Input sheet!J36'] == result['Valuation output!L40']
    assert result['Valuation as picture!E29'] == result['Valuation output!C40']


def test_terminal_year_and_equity_bridge_use_business_inputs_not_formula_strings(tiny):
    result = audit.derive_business(*tiny)
    assert result['Valuation output!M3'] == 153  # Year-ten revenue150, stable growth2%.
    assert result['Valuation output!M5'] == D('30.60')
    assert result['Input sheet!J34'] == 153 and result['Input sheet!J35'] == D('30.60')
    assert result['Stories to Numbers!D36'] == 1000
    assert result['Stories to Numbers!D39'] == 100
    assert result['Stories to Numbers!F12'] == D('.2')
    assert result['Valuation as picture!P10'] == D('.2')
    assert result['Valuation output!B23'] == 500  # Proceeds exist even with zero probability.
    assert result['Valuation output!B35'] == D('.05')
    assert result['Valuation as picture!B30'] == D('-.95')


def test_cash_decomposition_and_story_displays_reconcile_without_replaying_formulas(tiny):
    _, anchors = tiny
    result = audit.derive_business(*tiny)
    independent_cash_pv = sum((anchors[f'Valuation output!{col}9']*anchors[f'Valuation output!{col}13']
        for col in audit.YEARS), D(0))
    assert result['Diagnostics!B21']-result['Diagnostics!B22'] == independent_cash_pv
    assert result['Diagnostics!C22']+result['Diagnostics!C23'] == 1
    assert result['Stories to Numbers!D17'] == 21
    assert result['Stories to Numbers!G17'] == D('14.8')
    assert result['Stories to Numbers!D27'] == D('30.60')
    assert result['Stories to Numbers!G27'] == D('18.36')
    assert result['Valuation output!N8'] == D('24.59')


def test_loss_carryforwards_consume_earnings_then_stop_at_zero(tiny):
    inputs, anchors = tiny
    anchors.update({'Valuation output!C5': D(-5), 'Valuation output!D5': D(2), 'Valuation output!E5': D(10)})
    result = audit.derive_business(inputs, anchors)
    assert [result[f'Valuation output!{col}10'] for col in 'CDEF'] == [5, 3, 0, 0]


@pytest.mark.parametrize('quoted_price,expected', [(5, 'Value seems high. See below'),
    (1000, 'Value seems low. See below'), (100, ' ')])
def test_reporting_classification_is_an_explicit_typed_display_convention(tiny, quoted_price, expected):
    inputs, anchors = tiny
    inputs['B22'] = quoted_price
    assert audit.derive_business(inputs, anchors)['Diagnostics!B37'] == expected


@pytest.mark.parametrize('mutation', ['flag', 'missing_input', 'extra_input', 'bool_amount', 'nan_amount', 'zero_shares', 'zero_capital', 'zero_return_capital'])
def test_unsupported_or_undefined_business_inputs_fail_closed(tiny, mutation):
    inputs, anchors = tiny
    if mutation == 'flag': inputs['B48'] = 'Yes'
    if mutation == 'missing_input': inputs.pop('B11')
    if mutation == 'extra_input': inputs['other'] = 1
    if mutation == 'bool_amount': inputs['B11'] = True
    if mutation == 'nan_amount': inputs['B11'] = float('nan')
    if mutation == 'zero_shares': inputs['B21'] = 0
    if mutation == 'zero_capital': inputs['B14'] = inputs['B15'] = inputs['B18'] = 0
    if mutation == 'zero_return_capital': anchors['Valuation output!L12'] = 0
    with pytest.raises(ValueError): audit.derive_business(inputs, anchors)


def test_alias_chain_transfers_exact_anchor_scalar_with_explicit_proof():
    rows = [{'sheet': 'Display', 'cell': 'A2', 'formula': '=A1', 'alias_of': {'sheet': 'Financial anchors', 'cell': 'C7'}}]
    formulas = {'Display!A2': '=A1', 'Display!A1': "='Financial anchors'!$C$7"}
    values, proof = audit.identity_transfers(rows, {'Financial anchors!C7': D('123.456')}, formulas.__getitem__)
    assert values == {'Display!A2': D('123.456')}
    assert len(proof[0]['exact_scalar_chain']) == 2 and proof[0]['identity_transfer_only']
    assert proof[0]['financial_expression_evaluated'] is False


@pytest.mark.parametrize('formula', ['=A1+0', '=SUM(A1)', '=IF(TRUE,A1,A1)', '=A1:A2', '=1', '=A1*1'])
def test_arithmetic_or_function_aliases_never_receive_identity_coverage(formula):
    with pytest.raises(ValueError): audit.scalar_alias(formula, 'Display')


def test_alias_cycle_wrong_anchor_and_duplicate_rows_fail_closed():
    row = {'sheet': 'Display', 'cell': 'A2', 'alias_of': {'sheet': 'Financial anchors', 'cell': 'C7'}}
    with pytest.raises(ValueError, match='circular'):
        audit.identity_transfers([row], {'Financial anchors!C7': 1}, {'Display!A2': '=A1', 'Display!A1': '=A2'}.__getitem__)
    with pytest.raises(ValueError, match='exact independently'):
        audit.identity_transfers([row], {'Display!A1': 1}, {'Display!A2': '=A1'}.__getitem__)
    with pytest.raises(ValueError, match='Duplicate'):
        audit.identity_transfers([row, row], {'Financial anchors!C7': 1},
            {'Display!A2': "='Financial anchors'!C7"}.__getitem__)


def test_same_two_decimal_and_type_semantics_as_the_actual_verifier():
    assert normalize_value(D('1.005')) == ('number', '1.01')
    assert normalize_value(D('-0.004')) == ('number', '0.00')
    assert normalize_value(True) != normalize_value(1)
    assert normalize_value('1.00') != normalize_value(1)
    assert normalize_value('Value seems low. See below') == ('string', 'Value seems low. See below')
