"""Sparse workbook facts and conservative formula dependencies."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time
from pathlib import Path
import re

import openpyxl
from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils.cell import range_boundaries, get_column_letter

from .static_references import StaticReferenceError, expand_static_formula_details, static_formula_text

_A1 = re.compile(r"\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?$")


def json_value(value):
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if value.__class__.__name__ in {"ArrayFormula", "DataTableFormula"}:
        return {"formula_object_type": value.__class__.__name__,
                "ref": getattr(value, "ref", None), "text": getattr(value, "text", None)}
    return str(value)


def formula_references(formula: str, sheet_name: str, max_expansion: int = 5000, *, workbook=None) -> dict:
    refs, unsupported = [], []
    analysis = None
    if workbook is not None:
        try:
            analysis = expand_static_formula_details(formula, sheet_name, workbook, max_expansion)
            formula = analysis["formula"]
        except StaticReferenceError as error:
            return {"references": [], "unsupported": [str(error)], "fully_supported": False}
    try:
        tokens = Tokenizer(formula).items
    except Exception:
        return {"references": [], "unsupported": ["formula_parse_error"], "fully_supported": False}
    if analysis is None and re.search(r"\b(?:INDIRECT|OFFSET)\s*\(", formula, re.I):
        unsupported.append("dynamic_reference")
    for token in tokens:
        if token.type != "OPERAND" or token.subtype != "RANGE":
            continue
        value = token.value
        if "[" in value or "]" in value:
            unsupported.append(value)
            continue
        if "!" in value:
            sheet, address = value.rsplit("!", 1)
            sheet = sheet.strip("'").replace("''", "'")
            if ":" in sheet:
                unsupported.append(value)
                continue
        else:
            sheet, address = sheet_name, value
        if not _A1.fullmatch(address):
            unsupported.append(value)
            continue
        try:
            min_col, min_row, max_col, max_row = range_boundaries(address)
            if (max_col-min_col+1) * (max_row-min_row+1) > max_expansion:
                unsupported.append("large_range:" + value)
                continue
            for row in range(min_row, max_row+1):
                for col in range(min_col, max_col+1):
                    refs.append({"sheet": sheet, "cell": f"{get_column_letter(col)}{row}"})
        except (TypeError, ValueError):
            unsupported.append(value)
    result = {"references": refs, "unsupported": unsupported, "fully_supported": not unsupported}
    if analysis is not None:
        result["resolved_names"] = analysis["resolved_names"]
        result["bounded_ranges"] = analysis["bounded_ranges"]
        result["analysis_only"] = True
    return result


def profile_workbook(path: Path, max_cells: int = 30000) -> dict:
    path = Path(path)
    book = openpyxl.load_workbook(path, data_only=False, keep_links=False)
    cached = openpyxl.load_workbook(path, data_only=True, keep_links=False)
    sheets, total_cells, total_formulas, emitted = [], 0, 0, 0
    all_errors, all_external = [], []
    for index, sheet in enumerate(book.worksheets):
        actual = sorted((c for c in sheet._cells.values() if c.value is not None),
                        key=lambda cell: (cell.row, cell.column))
        count = len(actual)
        formula_count = sum(c.data_type == "f" for c in actual)
        row_labels_index, column_labels_index = defaultdict(list), defaultdict(list)
        for cell in actual:
            if cell.data_type != "f" and isinstance(cell.value, str):
                row_labels_index[cell.row].append(cell)
            if cell.data_type != "f" and isinstance(cell.value, (str, date, datetime)):
                column_labels_index[cell.column].append(cell)
        total_cells += count
        total_formulas += formula_count
        errors = [{"cell": c.coordinate, "value": c.value} for c in cached[sheet.title]._cells.values()
                  if c.data_type == "e"]
        all_errors.extend({"sheet": sheet.title, **e} for e in errors)
        cells = []
        for cell in actual:
            if emitted >= max_cells:
                break
            row_labels = [{"cell": c.coordinate, "value": c.value}
                          for c in row_labels_index[cell.row] if c.column < cell.column][-3:]
            column_labels = [{"cell": c.coordinate, "value": json_value(c.value)}
                             for c in column_labels_index[cell.column] if c.row < cell.row][-3:]
            item = {"cell": cell.coordinate, "value": json_value(cell.value),
                    "data_type": cell.data_type, "number_format": cell.number_format,
                    "row_labels": row_labels, "column_labels": column_labels}
            if cell.data_type == "f":
                formula_text = cell.value if isinstance(cell.value, str) else getattr(cell.value, "text", "")
                try:
                    formula_text = static_formula_text(cell)
                    dependencies = formula_references(formula_text, sheet.title, workbook=book)
                except StaticReferenceError as error:
                    dependencies = {"references": [], "unsupported": [str(error)], "fully_supported": False}
                if not isinstance(cell.value, str):
                    item["formula_group"] = json_value(cell.value)
                item.update({"formula": formula_text,
                             "cached_value": json_value(cached[sheet.title][cell.coordinate].value),
                             "dependencies": dependencies})
                all_external.extend({"sheet": sheet.title, "cell": cell.coordinate, "reference": ref}
                                    for ref in dependencies["unsupported"] if "[" in ref)
            cells.append(item)
            emitted += 1
        sheets.append({"sheet_id": f"sheet-{index}", "name": sheet.title,
                       "state": sheet.sheet_state, "nonempty_cells": count,
                       "formula_count": formula_count, "max_row": sheet.max_row,
                       "max_column": sheet.max_column,
                       "merged_ranges": [str(x) for x in sheet.merged_cells.ranges],
                       "cells": cells, "errors": errors})
    result = {"path": str(path.resolve()), "sheet_count": len(sheets),
              "nonempty_sheet_count": sum(s["nonempty_cells"] > 0 for s in sheets),
              "nonempty_cells": total_cells, "formula_count": total_formulas,
              "cells_emitted": emitted, "truncated": total_cells > emitted,
              "sheets": sheets, "errors": all_errors,
              "external_references": all_external,
              "defined_names": {name: str(value.attr_text)
                                for name, value in book.defined_names.items()}}
    book.close()
    cached.close()
    return result
