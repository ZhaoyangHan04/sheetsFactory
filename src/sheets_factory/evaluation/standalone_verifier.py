"""Self-contained Harbor grader. Recalculates all three files before comparison."""

from __future__ import annotations

import argparse
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel, to_excel


def normalize(value, expected_date=False, epoch=None):
    if value is None or value == "":
        return ("empty", None)
    if isinstance(value, bool):
        return ("bool", value)
    if expected_date and isinstance(value, (int, float, Decimal)):
        value = from_excel(float(value), epoch=epoch)
    if isinstance(value, datetime):
        return ("datetime", value.isoformat(timespec="milliseconds"))
    if isinstance(value, date):
        return ("datetime", datetime.combine(value, time()).isoformat(timespec="milliseconds"))
    if isinstance(value, time):
        return ("time", value.isoformat(timespec="milliseconds"))
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


def _cells(workbook):
    cells = {}
    for sheet in workbook.worksheets:
        for cell in sheet._cells.values():
            if cell.value is not None:
                cells[(sheet.title, cell.coordinate)] = cell
    return cells


def compare_files(original: str | Path, goal: str | Path, output: str | Path) -> dict:
    """Compare already recalculated files; callers must supply trusted recalc outputs."""
    workbooks = [load_workbook(path, data_only=True, read_only=False, keep_links=False)
                 for path in (original, goal, output)]
    try:
        original_wb, goal_wb, output_wb = workbooks
        if output_wb.sheetnames != goal_wb.sheetnames:
            return {"reward": 0, "reason": "sheet_structure_mismatch", "output_sheets": output_wb.sheetnames}
        maps = [_cells(book) for book in workbooks]
        keys = set().union(*(m.keys() for m in maps))
        normalized = [dict() for _ in maps]
        for key in keys:
            reference = maps[1].get(key) or maps[0].get(key)
            reference_value = reference.value if reference is not None else None
            expected_date = isinstance(reference_value, (datetime, date, time))
            for index, (book, cells) in enumerate(zip(workbooks, maps)):
                cell = cells.get(key)
                if cell is not None and cell.data_type == "e":
                    value = ("error", cell.value)
                else:
                    raw = cell.value if cell is not None else None
                    # A candidate number format must not redefine the expected
                    # value type. openpyxl decodes date-formatted numerics eagerly.
                    if isinstance(reference_value, (int, float, Decimal)) and not isinstance(reference_value, bool):
                        if isinstance(raw, (datetime, date, time)):
                            raw = to_excel(raw, epoch=book.epoch)
                    value = normalize(raw, expected_date, book.epoch)
                normalized[index][key] = value
        baseline, expected, actual = normalized
        goal_delta = {key for key in keys if baseline[key] != expected[key]}
        output_delta = {key for key in keys if baseline[key] != actual[key]}
        wrong = {key for key in goal_delta if actual[key] != expected[key]}
        success = goal_delta == output_delta and not wrong
        coord = lambda values: [f"{sheet}!{cell}" for sheet, cell in sorted(values)]
        return {"reward": int(success), "reason": "matched" if success else "value_or_modified_set_mismatch",
                "expected_change_count": len(goal_delta), "actual_change_count": len(output_delta),
                "missing_changes": coord(goal_delta - output_delta),
                "extra_changes": coord(output_delta - goal_delta), "wrong_values": coord(wrong)}
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
