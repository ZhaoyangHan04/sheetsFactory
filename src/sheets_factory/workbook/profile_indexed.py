"""Workbook profiles with indexed lookups for the last three preceding labels.

The original profiler remains the definition of cell values and dependencies.
This opt-in implementation changes only how preceding labels are selected.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import openpyxl

from .profile import formula_references, json_value
from .static_references import StaticReferenceError, static_formula_text


def _preceding(index, coordinate):
    """Return at most three labels strictly before this row or column."""
    positions, cells = index
    stop = bisect_left(positions, coordinate)
    return cells[max(0, stop - 3):stop]


def _label_indexes(actual):
    rows, columns = defaultdict(list), defaultdict(list)
    for cell in actual:
        if cell.data_type != 'f' and isinstance(cell.value, str):
            rows[cell.row].append(cell)
        if cell.data_type != 'f' and isinstance(cell.value, (str, date, datetime)):
            columns[cell.column].append(cell)
    # actual is sorted by (row, column), so both lists are already ordered.
    return ({row: (tuple(c.column for c in cells), tuple(cells)) for row, cells in rows.items()},
            {column: (tuple(c.row for c in cells), tuple(cells)) for column, cells in columns.items()})


def profile_workbook(path: Path, max_cells: int = 30000, *, per_formula_reference_cells: int = 5000) -> dict:
    """Emit the original complete profile contract using bounded label slices."""
    path = Path(path)
    book = openpyxl.load_workbook(path, data_only=False, keep_links=False)
    cached = None
    try:
        cached = openpyxl.load_workbook(path, data_only=True, keep_links=False)
        sheets, total_cells, total_formulas, emitted = [], 0, 0, 0
        all_errors, all_external = [], []
        reference_cache = {}
        for index, sheet in enumerate(book.worksheets):
            actual = sorted((c for c in sheet._cells.values() if c.value is not None),
                            key=lambda cell: (cell.row, cell.column))
            count = len(actual)
            formula_count = sum(c.data_type == 'f' for c in actual)
            row_indexes, column_indexes = _label_indexes(actual)
            total_cells += count
            total_formulas += formula_count
            errors = [{'cell': c.coordinate, 'value': c.value} for c in cached[sheet.title]._cells.values()
                      if c.data_type == 'e']
            all_errors.extend({'sheet': sheet.title, **error} for error in errors)
            cells = []
            for cell in actual:
                if emitted >= max_cells:
                    break
                row_labels = [{'cell': c.coordinate, 'value': c.value}
                              for c in _preceding(row_indexes.get(cell.row, ((), ())), cell.column)]
                column_labels = [{'cell': c.coordinate, 'value': json_value(c.value)}
                                 for c in _preceding(column_indexes.get(cell.column, ((), ())), cell.row)]
                item = {'cell': cell.coordinate, 'value': json_value(cell.value),
                        'data_type': cell.data_type, 'number_format': cell.number_format,
                        'row_labels': row_labels, 'column_labels': column_labels}
                if cell.data_type == 'f':
                    formula_text = cell.value if isinstance(cell.value, str) else getattr(cell.value, 'text', '')
                    try:
                        formula_text = static_formula_text(cell)
                        dependencies = formula_references(formula_text, sheet.title,
                            max_expansion=per_formula_reference_cells, workbook=book, cache=reference_cache)
                    except StaticReferenceError as error:
                        dependencies = {'references': [], 'unsupported': [str(error)], 'fully_supported': False}
                    if not isinstance(cell.value, str):
                        item['formula_group'] = json_value(cell.value)
                    item.update({'formula': formula_text,
                                 'cached_value': json_value(cached[sheet.title][cell.coordinate].value),
                                 'dependencies': dependencies})
                    all_external.extend({'sheet': sheet.title, 'cell': cell.coordinate, 'reference': ref}
                                        for ref in dependencies['unsupported'] if '[' in ref)
                cells.append(item)
                emitted += 1
            sheets.append({'sheet_id': f'sheet-{index}', 'name': sheet.title,
                           'state': sheet.sheet_state, 'nonempty_cells': count,
                           'formula_count': formula_count, 'max_row': sheet.max_row,
                           'max_column': sheet.max_column,
                           'merged_ranges': [str(value) for value in sheet.merged_cells.ranges],
                           'cells': cells, 'errors': errors})
        return {'path': str(path.resolve()), 'sheet_count': len(sheets),
                'nonempty_sheet_count': sum(s['nonempty_cells'] > 0 for s in sheets),
                'nonempty_cells': total_cells, 'formula_count': total_formulas,
                'cells_emitted': emitted, 'truncated': total_cells > emitted,
                'sheets': sheets, 'errors': all_errors,
                'external_references': all_external,
                'analysis_limits': {'max_profile_cells': max_cells,
                                    'per_formula_reference_cells': per_formula_reference_cells},
                'defined_names': {name: str(value.attr_text) for name, value in book.defined_names.items()}}
    finally:
        try:
            if cached is not None:
                cached.close()
        finally:
            book.close()
