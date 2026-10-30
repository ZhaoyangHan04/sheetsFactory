"""Deterministic task proposals for the explicitly documented project model.

Recognition and local cached-value checks are authoring evidence, not seed,
oracle, individual-mutation, combined-marginal or difficulty certification.
The normal pipeline must run all those gates on the returned proposal.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import re

import openpyxl
from openpyxl.utils import get_column_letter as L


_BASE_SHEETS = ("Operations", "Assets", "Debt", "Tax", "Cash Flow", "Balance Sheet",
                "Equity Value", "Annual Statements")
_OPTIONAL_SHEETS = ("Covenants", "Tax Vintages", "DebtSizing")
_CENT = Decimal(".01")


def _label(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _rows(sheet):
    result = {}
    for cells in sheet.iter_rows(min_col=1, max_col=1):
        cell = cells[0]
        key = _label(cell.value)
        if key:
            if key in result:
                raise ValueError(f"Ambiguous project-model row label: {sheet.title}/{key}")
            result[key] = cell.row
    return result


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("Task authoring requires finite recalculated numeric evidence")
    try:
        number = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("Invalid cached project-model value") from error
    if not number.is_finite():
        raise ValueError("Task authoring requires finite recalculated numeric evidence")
    return number


def _cent(value):
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _recognize(book):
    required = {"Read Me", "Source Inputs", "Scenario", "Calendar", *_BASE_SHEETS}
    if not required.issubset(book.sheetnames):
        raise ValueError("Unrecognized documented project model")
    policies = [(cell.coordinate, cell.value) for row in book["Read Me"] for cell in row
                if isinstance(cell.value, str) and len(cell.value) >= 60]
    policy_text = " ".join(value.lower() for _, value in policies)
    if len(policies) < 5 or not all(term in policy_text for term in
                                    ("hypothetical", "month", "nol", "debt", "round")):
        raise ValueError("Project model lacks explicit public business policies")
    rows = {name: _rows(book[name]) for name in (*required, *_OPTIONAL_SHEETS)
            if name in book.sheetnames and name != "Read Me"}
    needed = {
        "Scenario": ("months", "initial asset cost", "initial asset life", "refresh capex",
                     "refresh life", "loan a amort payments", "loan a annual rate", "loan b annual rate"),
        "Calendar": ("period", "date", "year", "month days"),
        "Debt": ("loan a open", "loan a interest", "loan b open", "loan b interest"),
        "Assets": ("initial asset depreciation", "refresh depreciation", "net ppe"),
        "Operations": ("ebitda", "net income"),
        "Cash Flow": ("cfo direct", "cfo indirect", "cash close"),
        "Tax": ("nol open", "nol close"),
    }
    for sheet, names in needed.items():
        if any(name not in rows[sheet] for name in names):
            raise ValueError(f"Unrecognized project-model semantics on {sheet}")
    if _number(book["Scenario"].cell(rows["Scenario"]["months"], 2).value) != 36:
        raise ValueError("This project task template requires the public 36-month model")
    period_row = rows["Calendar"]["period"]
    columns = [cell.column for cell in book["Calendar"][period_row]
               if cell.data_type == "f" and cell.column >= 3]
    if len(columns) != 36 or columns != list(range(columns[0], columns[0] + 36)):
        raise ValueError("Project model must expose a complete contiguous monthly calendar")
    if "Tax Vintages" in book:
        needed_tax = ("nol v1 expired", "nol v1 open", "interest capacity", "deferred tax expense")
        if any(name not in rows["Tax Vintages"] for name in needed_tax):
            raise ValueError("Unrecognized annual tax vintage schema")
        if not all(term in policy_text for term in ("deferred", "vintage", "expire")):
            raise ValueError("Advanced tax model lacks its explicit public tax policy")
    if "DebtSizing" in book:
        required_cyclic = ("cyclic enabled", "cyclic bankcap", "cyclic target dscr", "cyclic tranche",
                           "loan a principal", "equity paid in")
        if any(name not in rows["Scenario"] for name in required_cyclic):
            raise ValueError("Debt underwriting lacks its explicit public financing assumptions")
        if not all(term in policy_text for term in ("underwriting", "capacity", "tranche", "equity")):
            raise ValueError("Debt underwriting lacks its explicit public sizing policy")
        if _number(book["Scenario"].cell(rows["Scenario"]["cyclic enabled"], 2).value) != 1:
            raise ValueError("Debt underwriting template requires an explicitly enabled public contract")
        for key in ("loan a principal", "equity paid in"):
            cell = book["Scenario"].cell(rows["Scenario"][key], 2)
            if cell.data_type != "f" or "DebtSizing" not in cell.value:
                raise ValueError("Endogenous financing must be linked to its public underwriting schedule")
    return rows, columns, policies


def _formula_rectangles(sheet, cells):
    """Compress an exact formula set into disjoint all-formula rectangles."""
    by_row = {}
    for row, column in cells:
        by_row.setdefault(row, []).append(column)
    active, rectangles = {}, []
    last_row = None
    for row, columns in sorted(by_row.items()):
        if last_row is not None and row != last_row + 1:
            rectangles.extend((*span, first, last) for span, (first, last) in active.items())
            active = {}
        runs = []
        for column in sorted(columns):
            if runs and column == runs[-1][1] + 1:
                runs[-1] = (runs[-1][0], column)
            else:
                runs.append((column, column))
        following = {}
        for span in runs:
            following[span] = (active[span][0], row) if span in active else (row, row)
        rectangles.extend((*span, first, last) for span, (first, last) in active.items()
                          if span not in following)
        active, last_row = following, row
    rectangles.extend((*span, first, last) for span, (first, last) in active.items())
    return [{"sheet": sheet, "range": f"{L(left)}{top}:{L(right)}{bottom}",
             "reason": "Restore the complete documented financial calculation family.",
             "business_rule": "Apply the public project assumptions and business policies preserved in the workbook."}
            for left, right, top, bottom in sorted(rectangles, key=lambda item: (item[2], item[0]))]


def _modeling_ranges(book, rows):
    groups, count = [], 0
    for name in (*_BASE_SHEETS, *_OPTIONAL_SHEETS):
        if name not in book:
            continue
        date_rows = {1}
        if name == "Equity Value":
            date_rows = {1, 15}
        elif name == "Annual Statements":
            date_rows |= {rows[name][key] for key in ("start date", "end date") if key in rows[name]}
        cells = {(cell.row, cell.column) for row in book[name] for cell in row
                 if cell.data_type == "f" and cell.row not in date_rows and not cell.is_date}
        count += len(cells)
        groups.extend(_formula_rectangles(name, cells))
    if "DebtSizing" in book:
        endogenous = {(rows["Scenario"][key], 2) for key in ("loan a principal", "equity paid in")}
        count += len(endogenous)
        groups.extend(_formula_rectangles("Scenario", endogenous))
    if not 6 <= count <= 8192 or not 1 <= len(groups) <= 64:
        raise ValueError("Project formula families exceed supported task authoring bounds")
    return groups


def _debug_edits(book, values, rows, columns):
    edits = []
    parameter_rows = rows["Scenario"]

    def parameter(name):
        row = parameter_rows[name.replace("_", " ")]
        return "'Scenario'!$B$" + str(row), _number(values["Scenario"].cell(row, 2).value)

    def actual_ref(formula, reference):
        # LibreOffice removes unnecessary sheet-name quotes on normalization.
        return next((candidate for candidate in (reference, reference.replace("'Scenario'", "Scenario"))
                     if isinstance(formula, str) and candidate in formula), None)

    def add(sheet, row, column, after, expected, reason):
        cell = book[sheet].cell(row, column)
        if cell.data_type != "f" or not isinstance(cell.value, str) or cell.value == after:
            return False
        before_value = _cent(_number(values[sheet][cell.coordinate].value))
        if before_value == _cent(expected):
            return False
        edits.append({"sheet": sheet, "cell": cell.coordinate, "before": cell.value,
                      "after": after, "reason": reason,
                      "business_rule": "The workbook's public business policies specify the correct facility, asset vintage and event timing."})
        return True

    # Wrong facility pricing is a real lookup defect.  Mutate complete populated
    # families; never add a marker constant or wrap every root in the same IF.
    for facility, other in (("a", "b"), ("b", "revolver")):
        prefix = "loan " + facility
        own_name = "loan_" + facility + "_annual_rate"
        other_name = "loan_b_annual_rate" if other == "b" else "revolver_annual_rate"
        old_ref, old_rate = parameter(own_name)
        new_ref, new_rate = parameter(other_name)
        row, basis_row = rows["Debt"][prefix + " interest"], rows["Debt"][prefix + " open"]
        active = []
        for column in columns:
            value = _cent(_number(values["Debt"].cell(row, column).value))
            if value:
                active.append((column, value))
        proposed = []
        for column, value in active:
            original = book["Debt"].cell(row, column).value
            formula_ref = actual_ref(original, old_ref)
            basis = _number(values["Debt"].cell(basis_row, column).value)
            expected_old, expected_new = _cent(basis * old_rate / 12), _cent(basis * new_rate / 12)
            if (not isinstance(original, str) or formula_ref is None
                    or value != expected_old or value == expected_new):
                proposed = []
                break
            proposed.append((column, original.replace(formula_ref, new_ref), expected_new))
        for column, after, expected in proposed:
            add("Debt", row, column, after, expected,
                "Facility interest incorrectly uses another facility's stated pricing assumption.")

    # An existing financing term is a plausible wrong assumption lookup for an
    # asset's depreciation life.  Reject a partial family rather than inserting
    # a defect in a period whose rounded/capped result would remain unchanged.
    for asset, label in (("initial", "initial asset depreciation"), ("refresh", "refresh depreciation")):
        old_ref, old_life = parameter("initial_asset_life" if asset == "initial" else "refresh_life")
        new_ref, new_life = parameter("loan_a_amort_payments")
        _, cost = parameter("initial_asset_cost" if asset == "initial" else "refresh_capex")
        row = rows["Assets"][label]
        prior = Decimal(0)
        proposed = []
        for column in columns:
            value = _cent(_number(values["Assets"].cell(row, column).value))
            if value:
                original = book["Assets"].cell(row, column).value
                formula_ref = actual_ref(original, old_ref)
                expected_old = min(_cent(cost / old_life), max(Decimal(0), cost - prior))
                expected_new = min(_cent(cost / new_life), max(Decimal(0), cost - prior))
                if (not isinstance(original, str) or formula_ref is None
                        or value != expected_old or value == expected_new):
                    proposed = []
                    break
                proposed.append((column, original.replace(formula_ref, new_ref), expected_new))
            prior += value
        for column, after, expected in proposed:
            add("Assets", row, column, after, expected,
                "Asset book depreciation incorrectly takes its life from a financing-term assumption.")

    if "Tax Vintages" in book:
        _, carry_years = parameter("nol_carryforward_years")
        for vintage in (1, 2, 3):
            row = rows["Tax Vintages"][f"nol v{vintage} expired"]
            open_row = rows["Tax Vintages"][f"nol v{vintage} open"]
            for year in range(1, 4):
                column = year + 2
                opening = _number(values["Tax Vintages"].cell(open_row, column).value)
                original = book["Tax Vintages"].cell(row, column).value
                if opening > 0 and year - vintage == carry_years and isinstance(original, str):
                    after, count = re.subn(r"(?<![<>=])>(?!=)", ">=", original)
                    if count == 1:
                        add("Tax Vintages", row, column, after, opening,
                            "An expiry boundary discards an otherwise eligible loss vintage one tax event early.")

    if "Covenants" in book:
        first_ref, first_test = parameter("covenant_first_test_month")
        if first_test == first_test.to_integral_value() and 1 <= first_test <= len(columns):
            column = columns[int(first_test) - 1]
            row = rows["Covenants"]["test due"]
            original = book["Covenants"].cell(row, column).value
            pattern = ">=" + (actual_ref(original, first_ref) or first_ref)
            if isinstance(original, str) and pattern in original:
                add("Covenants", row, column, original.replace(pattern, ">" + first_ref), Decimal(0),
                    "The first eligible covenant measurement is incorrectly deferred beyond the contractual start.")
    if not 100 <= len(edits) <= 300:
        raise ValueError(f"Source does not support 100–300 locally evidenced project bugs: {len(edits)}")
    return edits


def propose_project_task(baseline: Path, mode: str) -> dict:
    """Return a standard uncompiled task plan, or reject unsupported evidence."""
    if mode not in {"financial_modeling", "debugging"}:
        raise ValueError("Unsupported project task mode")
    book = openpyxl.load_workbook(baseline, keep_links=False)
    values = None
    try:
        rows, columns, policies = _recognize(book)
        targets = [name for name in (*_BASE_SHEETS, *_OPTIONAL_SHEETS) if name in book]
        cyclic = "DebtSizing" in book
        if cyclic:
            targets.append("Scenario")
        if mode == "financial_modeling":
            instruction = (
                "Complete the missing formulas in this hypothetical project financing model for all thirty-six monthly periods "
                "and the three annual summaries. Use the assumptions in Scenario, the source benchmarks in Source Inputs, "
                "and the business policies in Read Me. Restore the connected operating forecast, asset schedules, financing, "
                "tax calculations, cash flow, balance sheet, covenant controls where present, and owner valuation. Preserve "
                "existing inputs, labels, dates and unaffected formulas while allowing dependent results to recalculate. "
                "Read /app/input.xlsx and save the completed workbook as /app/output.xlsx.")
            edits, masks = [], _modeling_ranges(book, rows)
            if cyclic:
                instruction = instruction.replace("financing,", "underwriting and financing,")
        else:
            values = openpyxl.load_workbook(baseline, data_only=True, keep_links=False)
            edits, masks = _debug_edits(book, values, rows, columns), None
            instruction = (
                "Review and repair this hypothetical project financing model across the thirty-six monthly periods and "
                "three annual summaries. Financing costs, asset charges, tax outcomes and contractual cash controls may "
                "disagree with the stated business policies. Use Read Me, Scenario and Source Inputs to identify the "
                "underlying formula defects and restore the connected financial statements and owner valuation. Preserve "
                "literal inputs, labels, dates and unaffected formulas; permit dependent calculated results to change. "
                "Read /app/input.xlsx and save the repaired workbook as /app/output.xlsx.")
        task = {
            "title": ("Complete" if mode == "financial_modeling" else "Repair") + " the integrated project financing model",
            "business_context": "An explicitly hypothetical, publicly documented project financing and owner-return model.",
            "target_sheets": targets, "public_instruction": instruction,
            "public_rules": ["Use the inputs and business policies supplied in the workbook to reconstruct the stated financial model."],
            "scenario_inputs": [], "edits": edits,
            "reference_evidence": [
                "Public business policies are preserved in 'Read Me'!" + coordinate + ": " + rule
                for coordinate, rule in policies],
            "protected_inputs": [f"'{name}'!{book[name].calculate_dimension()}"
                                 for name in ("Read Me", "Source Inputs", "Scenario", "Calendar")],
            "native_issues": [], "involved_sheets": list(book.sheetnames),
        }
        if cyclic:
            # Endogenous funding formulas are targets; all primitive inputs and
            # their labels/statuses stay protected. Do not protect a target as
            # if it were an immutable input constant.
            task["protected_inputs"] = [item for item in task["protected_inputs"]
                                        if not item.startswith("'Scenario'!")]
            end = book["Scenario"].max_row
            task["protected_inputs"].extend((f"'Scenario'!A1:A{end}", f"'Scenario'!C1:C{end}"))
            excluded = sorted(rows["Scenario"][key] for key in ("loan a principal", "equity paid in"))
            start = 1
            for row in [*excluded, end + 1]:
                if start < row:
                    task["protected_inputs"].append(f"'Scenario'!B{start}:B{row - 1}")
                start = row + 1
        if masks is not None:
            task["mask_ranges"] = masks
        return task
    finally:
        book.close()
        if values is not None:
            values.close()
