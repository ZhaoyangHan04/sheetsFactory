"""Lexical unit tests only; no workbook, calculation engine or financial path."""
from decimal import Decimal

import pytest

from sheets_factory.task_adapters.heterogeneous_formula_identity import formula_signature


@pytest.mark.parametrize('sheet,address', [
    ('Calendar', 'A1'), ('Calendar', '$D$2'), ('Facilities', '$C3'),
    ('Facility_Terms', 'G$11'), ('_Native', 'a1'), ('Sheet.One', '$XFD$1048576')])
def test_only_redundant_legal_point_reference_sheet_quotes_are_equivalent(sheet, address):
    assert formula_signature(f"='{sheet}'!{address}") == formula_signature(f'={sheet}!{address}')


def test_decimal_numeric_lexical_forms_are_exact_without_float_rounding():
    assert formula_signature("='Calendar'!$D$2+1e18") == formula_signature('=Calendar!$D$2+1000000000000000000')
    assert formula_signature('=0.1') == [('OPERAND', 'NUMBER', Decimal('0.1'))]
    assert formula_signature('=1E-12') == formula_signature('=0.000000000001')
    assert formula_signature('=9007199254740993') != formula_signature('=9007199254740992')


@pytest.mark.parametrize('other', ['=Facilities!$D$2', '=Calendar!$D$3', '=Calendar!$E$2',
    '=Calendar!D$2', '=Calendar!$D2', '=Calendar!D2', '=calendar!$D$2'])
def test_sheet_cell_and_absolute_relative_identity_are_not_relaxed(other):
    assert formula_signature("='Calendar'!$D$2") != formula_signature(other)


@pytest.mark.parametrize('quoted,unquoted', [
    ("='Calendar'!A1:B2", '=Calendar!A1:B2'),
    ("='Calendar'!A:A", '=Calendar!A:A'),
    ("='Calendar'!1:1", '=Calendar!1:1'),
    ("='Calendar'!Forecast", '=Calendar!Forecast'),
    ("='Calendar'!Table1[Cash]", '=Calendar!Table1[Cash]'),
    ("='Calendar'!XFE1", '=Calendar!XFE1'),
    ("='Calendar'!A1048577", '=Calendar!A1048577'),
    ("='Calendar'!A0", '=Calendar!A0')])
def test_non_point_or_invalid_reference_is_preserved_exactly(quoted, unquoted):
    assert formula_signature(quoted) != formula_signature(unquoted)


@pytest.mark.parametrize('formula,operand', [
    ("='O''Brien'!$A$1", "'O''Brien'!$A$1"),
    ("='Facility Terms'!$A$1", "'Facility Terms'!$A$1"),
    ("='[book.xlsx]Calendar'!$A$1", "'[book.xlsx]Calendar'!$A$1"),
    ("='S01:S03'!$A$1", "'S01:S03'!$A$1"),
    ("='2027'!$A$1", "'2027'!$A$1")])
def test_required_quotes_external_3D_and_quoted_apostrophe_remain_literal(formula, operand):
    assert formula_signature(formula) == [('OPERAND', 'RANGE', operand)]


def test_two_quoted_apostrophe_names_or_text_constants_never_coalesce():
    assert formula_signature("='O''Brien'!A1") != formula_signature("='O''Brion'!A1")
    assert formula_signature('="1e18"') != formula_signature('="1000000000000000000"')
    assert formula_signature('="\'Calendar\'!A1"') != formula_signature('="Calendar!A1"')


def test_no_algebraic_operator_function_or_whitespace_rewrite():
    assert formula_signature('=1+2') != formula_signature('=3')
    assert formula_signature('=SUM(1,2)') != formula_signature('=1+2')
    assert formula_signature('=A1+B1') != formula_signature('=B1+A1')
    assert formula_signature('=+1') != formula_signature('=1')
    assert formula_signature('=SUM(A1 B1)') != formula_signature('=SUM(A1,B1)')
    assert formula_signature('=A1 + B1') != formula_signature('=A1+B1')


def test_mixed_formula_keeps_all_tokens_except_the_two_documented_changes():
    left = '=IF(\'Calendar\'!$D$2=1E0,\'Facilities\'!C$3+0.01,"not a reference")'
    right = '=IF(Calendar!$D$2=1,Facilities!C$3+1E-2,"not a reference")'
    assert formula_signature(left) == formula_signature(right)


@pytest.mark.parametrize('bad', [None, True, 1, '', '=', 'A1+1'])
def test_nonformula_input_fails_closed(bad):
    with pytest.raises(ValueError, match='formula'):
        formula_signature(bad)
