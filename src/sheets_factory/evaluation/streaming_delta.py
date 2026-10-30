"""Complete construction deltas with the existing workbook comparison schema.

Only changed-coordinate lists are retained. Every sparse cell is examined and
normalization uses the original input-first trusted type hints. This module is
an explicit family opt-in; it does not replace the existing comparator.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter
from openpyxl.utils.datetime import from_excel, to_excel

from ..workbook.compare import normalize_value
from .streaming_verifier import _sparse_cells


def _normalize(cell, hint, epoch):
    value = cell['value'] if cell is not None else None
    if hint is not None:
        reference = hint['value']
        number = isinstance(reference, (int, float, Decimal)) and not isinstance(reference, bool)
        calendar = isinstance(reference, (date, datetime, time, timedelta))
        if number and isinstance(value, (date, datetime, time, timedelta)):
            value = to_excel(value, epoch)
        elif calendar and isinstance(value, (int, float)) and not isinstance(value, bool):
            value = from_excel(value, epoch, timedelta=isinstance(reference, timedelta))
    return normalize_value(value, cell['data_type'] if cell is not None else None)


def _nonempty(cell):
    return cell is not None and cell['value'] is not None and cell['value'] != ''


def compare_workbooks(input: Path, goal: Path, output: Path) -> dict:
    """Return every original comparison field, including the complete D lists."""
    books = []
    try:
        for path in (input, goal, output):
            books.append(load_workbook(path, data_only=True, read_only=True, keep_links=False))
        original, expected, actual = books
        expected_changes, actual_changes, missing, extra, wrong = [], [], [], [], []
        worksheets = [{sheet.title for sheet in book.worksheets} for book in books]
        for title in sorted(set().union(*(book.sheetnames for book in books))):
            streams = [iter(_sparse_cells(book[title] if title in names else None))
                       for book, names in zip(books, worksheets)]
            try:
                heads = [next(stream, None) for stream in streams]
                while any(head is not None for head in heads):
                    key = min(head[0] for head in heads if head is not None)
                    cells = []
                    for index, stream in enumerate(streams):
                        if heads[index] is not None and heads[index][0] == key:
                            cells.append(heads[index][1])
                            heads[index] = next(stream, None)
                        else:
                            cells.append(None)
                    # Exactly expected_raw | original_raw from the old path:
                    # a nonempty input controls the type before a goal value.
                    hint = cells[0] if _nonempty(cells[0]) else cells[1] if _nonempty(cells[1]) else None
                    baseline, target, candidate = [_normalize(cell, hint, book.epoch)
                        for cell, book in zip(cells, books)]
                    needed, changed = baseline != target, baseline != candidate
                    label = title + '!' + get_column_letter(key[1]) + str(key[0])
                    if needed:
                        expected_changes.append(label)
                    if changed:
                        actual_changes.append(label)
                    if needed and not changed:
                        missing.append(label)
                    if changed and not needed:
                        extra.append(label)
                    if needed and candidate != target:
                        wrong.append(label)
            finally:
                for stream in streams:
                    stream.close()
        structure_ok = original.sheetnames == expected.sheetnames == actual.sheetnames
        return {'reward': int(structure_ok and not missing and not extra and not wrong),
                'structure_ok': structure_ok,
                'expected_change_count': len(expected_changes), 'actual_change_count': len(actual_changes),
                'expected_changes': sorted(expected_changes), 'actual_changes': sorted(actual_changes),
                'missing_changes': sorted(missing), 'extra_changes': sorted(extra),
                'wrong_values': sorted(wrong), 'input_sheets': original.sheetnames,
                'goal_sheets': expected.sheetnames, 'output_sheets': actual.sheetnames}
    except Exception as error:
        return {'reward': 0, 'error': type(error).__name__, 'detail': str(error)[:500]}
    finally:
        for book in books:
            book.close()
