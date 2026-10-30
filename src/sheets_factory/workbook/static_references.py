"""Conservative workbook-aware static references for dependency analysis only.

Expansion never edits workbook cells. Whole-row/column dependencies include
every currently used cell in the requested rows/columns and the intervening
blanks. Omitted coordinates outside the nonempty used extent are blank in this
workbook snapshot; the bounded expression is not a replacement Excel formula.
"""
from __future__ import annotations

import re

from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils.cell import get_column_letter, range_boundaries


class StaticReferenceError(ValueError):
    """A dependency cannot be resolved without guessing or evaluating Excel."""


_A1 = re.compile(r"\$?[A-Za-z]{1,3}\$?[1-9]\d*(?::\$?[A-Za-z]{1,3}\$?[1-9]\d*)?$")
_COLUMN = re.compile(r"\$?([A-Za-z]{1,3}):\$?([A-Za-z]{1,3})$")
_ROW = re.compile(r"\$?([1-9]\d*):\$?([1-9]\d*)$")
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?$")
_TEXT = re.compile(r'"(?:[^"]|"")*"$')


def static_formula_text(cell) -> str:
    """Read an ordinary formula or a scalar array formula without mutation."""
    value = cell.value
    if isinstance(value, str) and value.startswith("="):
        return value
    if value.__class__.__name__ == "ArrayFormula" and isinstance(getattr(value, "text", None), str):
        try:
            left, top, right, bottom = range_boundaries(value.ref)
            if left == right == cell.column and top == bottom == cell.row and value.text.startswith("="):
                return value.text
        except (TypeError, ValueError, AttributeError):
            pass
    raise StaticReferenceError("unsupported_formula_group:" + value.__class__.__name__)


def _quote_sheet(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def _sheet_address(value: str, default_sheet: str, workbook) -> tuple[str, str]:
    """Split one A1/name operand, respecting quoted sheet-name punctuation."""
    if "[" in value or "]" in value:
        raise StaticReferenceError("external_or_structured_reference:" + value)
    if "!" not in value:
        return default_sheet, value
    if value.startswith("'"):
        match = re.fullmatch(r"'((?:[^']|'')*)'!(.+)", value)
        if not match:
            raise StaticReferenceError("unsupported_sheet_reference:" + value)
        sheet, address = match.group(1).replace("''", "'"), match.group(2)
    else:
        if value.count("!") != 1:
            raise StaticReferenceError("unsupported_sheet_reference:" + value)
        sheet, address = value.split("!", 1)
    if ":" in sheet or sheet not in workbook.sheetnames:
        raise StaticReferenceError("unknown_or_3d_sheet:" + value)
    return sheet, address


def expand_static_formula_details(formula: str, sheet_name: str, workbook, max_expansion: int = 5000) -> dict:
    """Expand static names and bounded whole ranges, or raise on uncertainty."""
    if not isinstance(formula, str) or not formula.startswith("="):
        raise StaticReferenceError("formula_parse_error")
    if sheet_name not in workbook.sheetnames:
        raise StaticReferenceError("unknown_sheet:" + sheet_name)
    if max_expansion < 1:
        raise StaticReferenceError("invalid_max_expansion")
    bounded, resolved = [], []
    count = 0
    extents = {}

    def used_extent(sheet):
        if sheet not in extents:
            cells = (cell for cell in workbook[sheet]._cells.values() if cell.value is not None)
            max_row, max_col = 1, 1
            for cell in cells:
                max_row, max_col = max(max_row, cell.row), max(max_col, cell.column)
            extents[sheet] = max_row, max_col
        return extents[sheet]

    def find_name(name, context):
        # Excel defined names are case-insensitive, with worksheet scope first.
        for scope, names in ((context, workbook[context].defined_names), (None, workbook.defined_names)):
            for key, definition in names.items():
                if key.casefold() == name.casefold():
                    # Some manually assembled workbooks retain localSheetId
                    # entries in the global dictionary; honor their scope too.
                    local_id = getattr(definition, "localSheetId", None)
                    if scope is None and local_id is not None:
                        if not 0 <= local_id < len(workbook.worksheets) or workbook.worksheets[local_id].title != context:
                            continue
                        return context, definition
                    return scope, definition
        raise StaticReferenceError("unresolved_defined_name:" + name)

    def reference(value, context, stack):
        nonlocal count
        sheet, address = _sheet_address(value, context, workbook)
        if _A1.fullmatch(address) or _COLUMN.fullmatch(address) or _ROW.fullmatch(address):
            try:
                left, top, right, bottom = range_boundaries(address)
            except (TypeError, ValueError) as error:
                raise StaticReferenceError("unsupported_static_range:" + value) from error
            whole = top is None or left is None
            if whole:
                max_row, max_col = used_extent(sheet)
                left, right = (1, max_col) if left is None else (left, right)
                top, bottom = (1, max_row) if top is None else (top, bottom)
                bounded.append({"original": value, "sheet": sheet,
                    "bounded_address": f"{get_column_letter(left)}{top}:{get_column_letter(right)}{bottom}",
                    "nonempty_used_extent": {"max_row": max_row, "max_column": max_col},
                    "omitted_coordinates_currently_blank": True,
                    "all_currently_used_dependencies_included": True})
            if not (1 <= left <= right <= 16384 and 1 <= top <= bottom <= 1048576):
                raise StaticReferenceError("invalid_static_range:invalid bounded reference:" + value)
            count += (right - left + 1) * (bottom - top + 1)
            if count > max_expansion:
                raise StaticReferenceError("large_range:" + value)
            address = f"{get_column_letter(left)}{top}" + (f":{get_column_letter(right)}{bottom}" if (left, top) != (right, bottom) else "")
            return _quote_sheet(sheet) + "!" + address
        scope, definition = find_name(address, sheet)
        key = (scope, address.casefold())
        if key in stack or len(stack) >= 64:
            raise StaticReferenceError("cyclic_defined_name:" + address)
        text = getattr(definition, "attr_text", None)
        if not isinstance(text, str) or not text:
            raise StaticReferenceError("empty_defined_name:" + address)
        resolved.append({"name": definition.name, "scope": scope, "definition": text})
        body = text[1:] if text.startswith("=") else text
        if _NUMBER.fullmatch(body) or _TEXT.fullmatch(body) or body.upper() in {"TRUE", "FALSE"}:
            return "(" + body + ")"
        try:
            parts = Tokenizer("=" + body).items
        except Exception as error:
            raise StaticReferenceError("defined_name_parse_error:" + address) from error
        if len(parts) != 1 or parts[0].type != "OPERAND" or parts[0].subtype != "RANGE":
            raise StaticReferenceError("dynamic_or_expression_defined_name:" + address)
        # A relative defined-name coordinate depends on an Excel base position
        # absent from the file interface. Static named A1 ranges must explicitly
        # identify their sheet and absolute coordinates; aliases remain allowed.
        target = parts[0].value
        target_sheet, target_address = _sheet_address(target, scope or sheet, workbook)
        if _A1.fullmatch(target_address):
            if "!" not in target or not re.fullmatch(r"\$[A-Za-z]{1,3}\$[1-9]\d*(?::\$[A-Za-z]{1,3}\$[1-9]\d*)?", target_address):
                raise StaticReferenceError("relative_defined_name:" + address)
        if (_COLUMN.fullmatch(target_address) or _ROW.fullmatch(target_address)) and "!" not in target:
            raise StaticReferenceError("relative_defined_name:" + address)
        return reference(target, scope or sheet, (*stack, key))

    try:
        tokens = Tokenizer(formula).items
    except Exception as error:
        raise StaticReferenceError("formula_parse_error") from error
    if any(token.type == "FUNC" and token.subtype == "OPEN"
           and token.value[:-1].split(".")[-1].upper() in {"INDIRECT", "OFFSET"} for token in tokens):
        raise StaticReferenceError("dynamic_reference")
    values = []
    for token in tokens:
        values.append(reference(token.value, sheet_name, ()) if token.type == "OPERAND" and token.subtype == "RANGE" else token.value)
    return {"formula": "=" + "".join(values), "resolved_names": resolved,
            "bounded_ranges": bounded, "expanded_reference_count": count,
            "analysis_only": True}


def expand_static_formula(formula: str, sheet_name: str, workbook, max_expansion: int = 5000) -> str:
    """Return a conservative expanded analysis expression without editing cells."""
    return expand_static_formula_details(formula, sheet_name, workbook, max_expansion)["formula"]
