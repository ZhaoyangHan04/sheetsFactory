"""Full sparse value comparison. Callers must recalculate files first."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
import math
from pathlib import Path

import openpyxl
from openpyxl.utils.datetime import from_excel, to_excel


def normalize_value(value, data_type: str | None = None):
    if value is None or value == "":
        return ("empty", "")
    if data_type == "e":
        return ("error", str(value))
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, (int, float, Decimal)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Nonfinite numeric cell")
        rounded = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return ("number", "0.00" if rounded == 0 else str(rounded))
    if isinstance(value, datetime):
        return ("datetime", value.isoformat(timespec="milliseconds"))
    if isinstance(value, date):
        return ("datetime", datetime.combine(value, time()).isoformat(timespec="milliseconds"))
    if isinstance(value, time):
        return ("time", value.isoformat(timespec="milliseconds"))
    if isinstance(value, timedelta):
        return ("duration", round(value.total_seconds(), 3))
    return ("string", str(value))


def _raw_values(path: Path):
    book = openpyxl.load_workbook(path, data_only=True, keep_links=False)
    values = {}
    names = book.sheetnames[:]
    epoch = book.epoch
    for sheet in book.worksheets:
        for cell in sheet._cells.values():
            if cell.value is not None and cell.value != "":
                values[(sheet.title, cell.coordinate)] = (cell.value, cell.data_type)
    book.close()
    return values, names, epoch


def _normalized_values(raw, epoch, hints=None):
    result = {}
    for key, (value, data_type) in raw.items():
        hint = (hints or {}).get(key)
        if hint is not None:
            reference = hint[0]
            reference_is_number = isinstance(reference, (int, float, Decimal)) and not isinstance(reference, bool)
            reference_is_date = isinstance(reference, (date, datetime, time, timedelta))
            if reference_is_number and isinstance(value, (date, datetime, time, timedelta)):
                value = to_excel(value, epoch)
            elif reference_is_date and isinstance(value, (int, float)) and not isinstance(value, bool):
                value = from_excel(value, epoch, timedelta=isinstance(reference, timedelta))
        result[key] = normalize_value(value, data_type)
    return result


def workbook_values(path: Path) -> tuple[dict, list[str]]:
    raw, names, epoch = _raw_values(path)
    return _normalized_values(raw, epoch), names


def _label(key):
    return key[0] + "!" + key[1]


def compare_workbooks(input: Path, goal: Path, output: Path) -> dict:
    """Compare already-recalculated cached values with exact observable deltas."""
    try:
        original_raw, original_sheets, original_epoch = _raw_values(Path(input))
        expected_raw, goal_sheets, goal_epoch = _raw_values(Path(goal))
        actual_raw, output_sheets, output_epoch = _raw_values(Path(output))
        # Expected cell types come from trusted input/goal; an output style may
        # not redefine a numeric cell as a date or vice versa.
        hints = expected_raw | original_raw
        original = _normalized_values(original_raw, original_epoch, hints)
        expected = _normalized_values(expected_raw, goal_epoch, hints)
        actual = _normalized_values(actual_raw, output_epoch, hints)
        empty = ("empty", "")
        expected_delta = {key for key in original.keys() | expected.keys()
                          if original.get(key, empty) != expected.get(key, empty)}
        actual_delta = {key for key in original.keys() | actual.keys()
                        if original.get(key, empty) != actual.get(key, empty)}
        wrong = {key for key in expected_delta
                 if expected.get(key, empty) != actual.get(key, empty)}
        structure_ok = original_sheets == goal_sheets == output_sheets
        reward = int(structure_ok and expected_delta == actual_delta and not wrong)
        return {"reward": reward, "structure_ok": structure_ok,
                "expected_change_count": len(expected_delta), "actual_change_count": len(actual_delta),
                "expected_changes": sorted(map(_label, expected_delta)),
                "actual_changes": sorted(map(_label, actual_delta)),
                "missing_changes": sorted(map(_label, expected_delta-actual_delta)),
                "extra_changes": sorted(map(_label, actual_delta-expected_delta)),
                "wrong_values": sorted(map(_label, wrong)),
                "input_sheets": original_sheets, "goal_sheets": goal_sheets,
                "output_sheets": output_sheets}
    except Exception as exc:
        return {"reward": 0, "error": type(exc).__name__, "detail": str(exc)[:500]}
