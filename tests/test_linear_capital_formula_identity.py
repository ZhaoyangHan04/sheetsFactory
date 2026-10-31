from decimal import Decimal

import pytest

from sheets_factory.task_adapters.heterogeneous_formula_identity import formula_signature as old
from sheets_factory.workbook.linear_capital_portfolio.formula_identity import formula_signature as signature


@pytest.mark.parametrize('left,right', [
    ("=SUM('Portfolio'!$B$6:$B$245)", '=SUM(Portfolio!$B$6:$B$245)'),
    ("=SUM('P001'!B6:C20)", '=SUM(P001!B6:C20)'),
    ("=SUM('_periods'!$XFD$1:$XFD$1048576)", '=SUM(_periods!$XFD$1:$XFD$1048576)'),
    ("=IF('Projects'!$A$1=1,SUM('Portfolio'!$B$6:$B$245),0)", '=IF(Projects!$A$1=1,SUM(Portfolio!$B$6:$B$245),0)'),
])
def test_only_redundant_quotes_are_removed_for_valid_same_sheet_A1_operands(left, right):
    assert signature(left) == signature(right)


@pytest.mark.parametrize('left,right', [
    ("=SUM('Portfolio'!$B$6:$B$245)", '=SUM(Portfolio!$B$7:$B$245)'),
    ("=SUM('Portfolio'!$B$6:$B$245)", '=SUM(Portfolio!B6:$B$245)'),
    ("=SUM('Portfolio'!$B$6:$B$245)", '=MAX(Portfolio!$B$6:$B$245)'),
    ("=SUM('P 001'!B6:C20)", '=SUM(P001!B6:C20)'),
    ("=SUM('Portfolio'!$XFE$1:$XFE$2)", '=SUM(Portfolio!$XFE$1:$XFE$2)'),
    ("=SUM('Portfolio'!$B$1:$B$1048577)", '=SUM(Portfolio!$B$1:$B$1048577)'),
    ("=SUM('A:B'!B1:C2)", '=SUM(A:B!B1:C2)'),
    ("=SUM('[external]Portfolio'!B1:C2)", '=SUM([external]Portfolio!B1:C2)'),
    ("=IF(A1=\"'Portfolio'!B1:C2\",1,0)", '=IF(A1="Portfolio!B1:C2",1,0)'),
    ('=9007199254740992', '=9.00719925474099E+15'),
])
def test_addresses_operators_strings_and_unequal_numeric_values_remain_different(left, right):
    assert signature(left) != signature(right)


def test_previous_point_parser_is_unchanged_and_exact_decimal_numbers_are_preserved():
    assert old("=SUM('Portfolio'!B1:B2)") != old('=SUM(Portfolio!B1:B2)')
    assert signature('=1.25E+2') == signature('=125')
    assert signature('=9007199254740992')[0][-1] == Decimal(9007199254740992)
