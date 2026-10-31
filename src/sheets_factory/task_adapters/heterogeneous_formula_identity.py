"""Narrow lexical identity after Calc reserializes a formula.

This does not evaluate formulas or recognize financial equivalence. Number
tokens use exact Decimal values. Only redundant quotes around a simple sheet
name in a single valid cross-sheet A1 reference are removed. Every address,
operator, other operand and whitespace token remains unchanged.
"""
from __future__ import annotations

from decimal import Decimal
import re

from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils.cell import column_index_from_string

METHOD = 'exact_formula_tokens_decimal_numbers_and_redundant_simple_sheet_quotes_v1'
_QUOTED_POINT = re.compile(
    r"'(?P<sheet>[A-Za-z_][A-Za-z0-9_.]*)'!(?P<column>\$?[A-Za-z]{1,3})(?P<row>\$?[1-9][0-9]*)\Z")


def _range_operand(value):
    match = _QUOTED_POINT.fullmatch(value)
    if match is None:
        return value
    column, row = match['column'], match['row']
    if column_index_from_string(column.lstrip('$')) > 16384 or int(row.lstrip('$')) > 1048576:
        return value
    return match['sheet'] + '!' + column + row


def formula_signature(formula):
    """Return a token signature, not a computed-value or algebraic signature.

    Quoted names containing spaces, apostrophes or external/3D syntax, ranges,
    named/structured references and invalid A1 coordinates retain exact text.
    """
    if type(formula) is not str or not formula.startswith('=') or len(formula) == 1:
        raise ValueError('A nonempty formula beginning with = is required')
    result = []
    for token in Tokenizer(formula).items:
        value = token.value
        if token.type == 'OPERAND' and token.subtype == 'NUMBER':
            value = Decimal(value)
            if not value.is_finite():
                raise ValueError('A finite exact number token is required')
        elif token.type == 'OPERAND' and token.subtype == 'RANGE':
            value = _range_operand(value)
        result.append((token.type, token.subtype, value))
    return result
