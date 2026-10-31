"""Exact formula tokens with redundant quotes on native A1 ranges removed."""
import re

from openpyxl.utils.cell import column_index_from_string

from ...task_adapters.heterogeneous_formula_identity import formula_signature as _point_signature

METHOD = 'linear_exact_decimal_tokens_and_redundant_simple_A1_point_or_range_sheet_quotes_v1'
_QUOTED_RANGE = re.compile(
    r"'(?P<sheet>[A-Za-z_][A-Za-z0-9_.]*)'!"
    r"(?P<c1>\$?[A-Za-z]{1,3})(?P<r1>\$?[1-9][0-9]*):"
    r"(?P<c2>\$?[A-Za-z]{1,3})(?P<r2>\$?[1-9][0-9]*)\Z")


def formula_signature(formula):
    """Normalize sheet quotes only; preserve exact numbers and all operators.

    The existing single-point implementation remains unchanged. Native Calc
    also removes redundant quotes in same-sheet rectangular range operands.
    External, 3D, named, structured and invalid A1 references retain exact text.
    """
    signature = _point_signature(formula)
    result = []
    for kind, subtype, value in signature:
        if kind == 'OPERAND' and subtype == 'RANGE':
            match = _QUOTED_RANGE.fullmatch(value)
            if match and all(column_index_from_string(match[key].lstrip('$')) <= 16384 for key in ('c1', 'c2')) \
                    and all(int(match[key].lstrip('$')) <= 1048576 for key in ('r1', 'r2')):
                value = match['sheet']+'!'+match['c1']+match['r1']+':'+match['c2']+match['r2']
        result.append((kind, subtype, value))
    return result
