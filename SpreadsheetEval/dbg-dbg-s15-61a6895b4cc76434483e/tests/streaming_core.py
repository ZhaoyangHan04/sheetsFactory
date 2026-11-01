"""Sparse streaming Harbor grader. Recalculates all three files before comparison."""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

from openpyxl import load_workbook
from openpyxl.worksheet._reader import WorkSheetParser
from openpyxl.utils.cell import get_column_letter, range_boundaries
from openpyxl.xml.functions import iterparse
from openpyxl.utils.datetime import from_excel, to_excel


def normalize(value, expected_date=False, epoch=None, expected_duration=False):
    if value is None or value == "":
        return ("empty", None)
    if isinstance(value, bool):
        return ("bool", value)
    if expected_date and isinstance(value, (int, float, Decimal)):
        value = from_excel(float(value), epoch=epoch, timedelta=expected_duration)
    if isinstance(value, datetime):
        return ("datetime", value.isoformat(timespec="milliseconds"))
    if isinstance(value, date):
        return ("datetime", datetime.combine(value, time()).isoformat(timespec="milliseconds"))
    if isinstance(value, time):
        return ("time", value.isoformat(timespec="milliseconds"))
    if isinstance(value, timedelta):
        return ("duration", round(value.total_seconds(), 3))
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("NaN or infinity is not a valid workbook result")
        try:
            number = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except InvalidOperation:
            raise ValueError("Numeric result exceeds supported decimal range") from None
        return ("number", str(number.copy_abs() if number == 0 else number))
    if isinstance(value, str):
        return ("text", value)
    raise ValueError(f"Unsupported cell value type: {type(value).__name__}")


def _merged_ranges(sheet):
    """Read merge boundaries without creating every covered blank cell."""
    ranges, stack = [], []
    with sheet._get_source() as source:
        for event, element in iterparse(source, events=('start', 'end')):
            if event == 'start':
                stack.append(element)
                continue
            if element.tag == '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}mergeCell':
                left, top, right, bottom = range_boundaries(element.attrib['ref'])
                ranges.append((top, bottom, left, right))
            if len(stack) > 1:
                stack[-2].remove(element)
            element.clear()
            stack.pop()
    return sorted(ranges)


def _sparse_cells(sheet):
    """Read actual XML cells without padding a distant cell into a rectangle.

    LibreOffice has already canonicalized these worksheets. The pinned
    openpyxl parser applies the same shared-string, epoch and style-based date
    decoding as its normal reader. Only one physical row is retained.
    """
    if sheet is None:
        return
    merges, pending, active = _merged_ranges(sheet), 0, []
    previous = (0, 0)
    with sheet._get_source() as source:
        parser = WorkSheetParser(source, sheet._shared_strings,
            data_only=sheet.parent.data_only, epoch=sheet.parent.epoch,
            date_formats=sheet.parent._date_formats,
            timedelta_formats=sheet.parent._timedelta_formats)
        for _, cells in parser.parse():
            # Match the normal reader's last cell at a repeated coordinate.
            row = {(cell['row'], cell['column']): cell for cell in cells}
            for key in sorted(row):
                cell = row[key]
                if key <= previous:
                    raise ValueError("Recalculated worksheet cells are not in canonical order")
                previous = key
                while pending < len(merges) and merges[pending][0] <= key[0]:
                    active.append(merges[pending]); pending += 1
                active = [bounds for bounds in active if bounds[1] >= key[0]]
                if any(left <= key[1] <= right and key != (top, left)
                       for top, bottom, left, right in active):
                    continue
                if cell['value'] is not None:
                    yield key, cell


def _normalized_cell(cell, reference_value, epoch):
    if cell is not None and cell['data_type'] == 'e':
        return ('error', cell['value'])
    raw = cell['value'] if cell is not None else None
    if isinstance(reference_value, (int, float, Decimal)) and not isinstance(reference_value, bool):
        if isinstance(raw, (datetime, date, time, timedelta)):
            raw = to_excel(raw, epoch=epoch)
    expected_date = isinstance(reference_value, (datetime, date, time, timedelta))
    return normalize(raw, expected_date, epoch, isinstance(reference_value, timedelta))


def compare_files(original: str | Path, goal: str | Path, output: str | Path) -> dict:
    """Compare the complete sparse value union using a three-way merge.

    Correct submissions retain no cell maps or changed-coordinate sets.
    Failure diagnostics retain only their actual mismatching coordinates.
    Sheet dimensions never truncate data or expand missing blank cells.
    """
    workbooks = []
    try:
        for path in (original, goal, output):
            workbooks.append(load_workbook(path, data_only=True, read_only=True, keep_links=False))
        original_wb, goal_wb, output_wb = workbooks
        if output_wb.sheetnames != goal_wb.sheetnames:
            return {'reward': 0, 'reason': 'sheet_structure_mismatch', 'output_sheets': output_wb.sheetnames}
        expected_count = actual_count = 0
        missing, extra, wrong = [], [], []
        names = set().union(*(book.sheetnames for book in workbooks))
        worksheet_names = [{sheet.title for sheet in book.worksheets} for book in workbooks]
        for title in sorted(names):
            iterators = [iter(_sparse_cells(book[title] if title in worksheets else None))
                         for book, worksheets in zip(workbooks, worksheet_names)]
            try:
                heads = [next(iterator, None) for iterator in iterators]
                while any(head is not None for head in heads):
                    key = min(head[0] for head in heads if head is not None)
                    cells = []
                    for index, iterator in enumerate(iterators):
                        head = heads[index]
                        if head is not None and head[0] == key:
                            cells.append(head[1]); heads[index] = next(iterator, None)
                        else:
                            cells.append(None)
                    reference = cells[1] if cells[1] is not None else cells[0]
                    reference_value = reference['value'] if reference is not None else None
                    baseline, expected, actual = [_normalized_cell(cell, reference_value, book.epoch)
                        for cell, book in zip(cells, workbooks)]
                    needed, changed = baseline != expected, baseline != actual
                    expected_count += needed; actual_count += changed
                    coordinate = (title, get_column_letter(key[1]) + str(key[0]))
                    if needed and not changed:
                        missing.append(coordinate)
                    if changed and not needed:
                        extra.append(coordinate)
                    if needed and actual != expected:
                        wrong.append(coordinate)
            finally:
                for iterator in iterators:
                    iterator.close()
        success = not (missing or extra or wrong)
        coordinates = lambda values: [f"{sheet}!{cell}" for sheet, cell in sorted(values)]
        return {'reward': int(success), 'reason': 'matched' if success else 'value_or_modified_set_mismatch',
            'expected_change_count': expected_count, 'actual_change_count': actual_count,
            'missing_changes': coordinates(missing), 'extra_changes': coordinates(extra),
            'wrong_values': coordinates(wrong)}
    finally:
        for workbook in workbooks:
            workbook.close()


def recalculate(source: Path, destination: Path, timeout: int = 180):
    completed = subprocess.run(["/usr/bin/python3", "/opt/uno_recalculate.py", str(source), str(destination)],
                               capture_output=True, text=True, timeout=timeout)
    if completed.returncode or not destination.is_file():
        raise RuntimeError(f"LibreOffice recalculation failed: {completed.stderr[-2000:]}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--goal", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reward", type=Path, default=Path("/logs/verifier/reward.txt"))
    parser.add_argument("--report", type=Path, default=Path("/logs/verifier/diagnostics.json"))
    args = parser.parse_args(argv)
    try:
        if not args.output.is_file() or args.output.is_symlink():
            raise ValueError("Submitted workbook is missing or a symlink")
        with tempfile.TemporaryDirectory(prefix="sheetsfactory-verify-") as temporary:
            paths = [Path(temporary) / f"{name}.xlsx" for name in ("input", "goal", "output")]
            for source, destination in zip((args.input, args.goal, args.output), paths):
                recalculate(source.resolve(), destination)
            result = compare_files(*paths)
    except Exception as exc:
        result = {"reward": 0, "reason": "verification_error", "error_type": type(exc).__name__, "error": str(exc)}
    args.reward.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    args.reward.write_text(str(result["reward"]) + "\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
