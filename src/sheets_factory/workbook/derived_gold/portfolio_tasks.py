"""Whole-portfolio task proposals from the actual documented entity layouts.

Proposals are unqualified. Source audits, construction, observed value changes,
diagnosis, controls and strongest-model evaluation run independently afterwards.
"""
from __future__ import annotations

from pathlib import Path
import re
from datetime import date, datetime

import openpyxl

from .task_templates import _formula_rectangles, _modeling_ranges, _recognize, _rows


class _EntityView:
    def __init__(self, book, prefix):
        self.book, self.prefix = book, prefix
        self.sheetnames = [name[len(prefix) + 1:] for name in book.sheetnames
                           if name.startswith(prefix + " ")]

    def __getitem__(self, name):
        return self.book[self.prefix + " " + name]

    def __contains__(self, name):
        return name in self.sheetnames


def _entities(book):
    if not {"Portfolio Index", "Group Statements", "Group Summary"}.issubset(book.sheetnames):
        raise ValueError("Portfolio task template requires the documented consolidation sheets")
    entities = sorted({name.split(" ", 1)[0] for name in book.sheetnames
                       if re.fullmatch(r"T\d{2} Scenario", name)})
    if len(entities) < 2:
        raise ValueError("A portfolio must contain multiple documented entities")
    recognized = []
    for entity in entities:
        view = _EntityView(book, entity)
        rows, columns, policies = _recognize(view)
        recognized.append((entity, view, rows, columns, policies))
    return recognized


def _rate_reference(formula, sheet, row):
    options = ("'" + sheet.replace("'", "''") + "'", sheet)
    for name in options:
        for address in (f"$B${row}", f"B{row}", f"$B{row}", f"B${row}"):
            value = name + "!" + address
            if value in formula:
                return value
    raise ValueError("Loan B family lacks its documented public rate reference")


def propose_portfolio_task(baseline: Path, mode: str) -> dict:
    if mode not in {"financial_modeling", "debugging"}:
        raise ValueError("Unsupported portfolio task mode")
    book = openpyxl.load_workbook(baseline, keep_links=False)
    # Formula cells do not reliably report is_date until their caches are read.
    values = openpyxl.load_workbook(baseline, data_only=True, keep_links=False)
    try:
        entities = _entities(book)
        masks, edits, policies, target_sheets = [], [], [], []
        for entity, view, rows, columns, public_policies in entities:
            policies.extend({"sheet": entity + " Read Me", "cell": coordinate, "policy": rule}
                            for coordinate, rule in public_policies)
            if mode == "financial_modeling":
                for group in _modeling_ranges(view, rows):
                    masks.append({**group, "sheet": entity + " " + group["sheet"]})
                    target_sheets.append(entity + " " + group["sheet"])
                continue
            debt, scenario = view["Debt"], view["Scenario"]
            row = rows["Debt"]["loan b interest"]
            correct_rate = rows["Scenario"]["loan b annual rate"]
            wrong_rate = rows["Scenario"]["loan a annual rate"]
            if scenario.cell(correct_rate, 2).value == scenario.cell(wrong_rate, 2).value:
                raise ValueError("Portfolio debugging needs distinct documented facility rates")
            for column in columns:
                cell = debt.cell(row, column)
                observed = values[debt.title][cell.coordinate].value
                if not isinstance(observed, (int, float)) or isinstance(observed, bool) or abs(observed) < .01:
                    continue
                if cell.data_type != "f" or not isinstance(cell.value, str):
                    raise ValueError("Loan B interest is not an actual scalar formula")
                correct = _rate_reference(cell.value, scenario.title, correct_rate)
                qualifier, address = correct.rsplit('!', 1)
                wrong = qualifier + '!' + re.sub(r'\d+$', str(wrong_rate), address)
                after = cell.value.replace(correct, wrong)
                if after == cell.value:
                    raise ValueError("Portfolio bug proposal made no change")
                edits.append({"sheet": debt.title, "cell": cell.coordinate,
                              "before": cell.value, "after": after,
                              "reason": "A copied facility-rate reference applies another debt facility's pricing.",
                              "business_rule": "Each facility uses its own documented annual rate and monthly accrual convention."})
                target_sheets.append(debt.title)
        if mode == "financial_modeling":
            for name in ("Group Statements", "Group Summary"):
                cells = {(cell.row, cell.column) for cell in book[name]._cells.values()
                         if cell.data_type == "f" and not cell.is_date and cell.row != 1
                         and not values[name][cell.coordinate].is_date
                         and not isinstance(values[name][cell.coordinate].value, (date, datetime))}
                if cells:
                    masks.extend(_formula_rectangles(name, cells))
                    target_sheets.append(name)
            instruction = (
                "Complete the missing financial calculations for this investment portfolio across all subsidiaries "
                "and the group reports. Reconstruct the monthly forecasts and annual summaries, including the "
                "connected operating, asset, debt, tax, cash, balance-sheet, covenant and owner-return schedules. "
                "Use Portfolio Index to navigate each entity's own assumptions and documented policies. Restore "
                "consistent group statements from the subsidiary results. Preserve supplied inputs, period headers "
                "and existing formulas outside the requested scope.")
        else:
            if not edits:
                raise ValueError("No active portfolio financial bug family")
            instruction = (
                "Audit and repair this investment portfolio model across its subsidiaries and group reports. "
                "Financing costs and the resulting tax, cash, balance-sheet and return schedules may disagree "
                "with the documented contracts. Use Portfolio Index and the entity-specific assumptions and "
                "policies to identify the underlying formula defects. Preserve supplied inputs, period headers "
                "and unaffected formulas; allow connected subsidiary and group calculations to update.")
        task = {"title": ("Complete" if mode == "financial_modeling" else "Repair") + " the consolidated investment portfolio",
                "business_context": "An explicitly hypothetical portfolio of wholly owned project companies with separately documented financial contracts.",
                "target_sheets": list(dict.fromkeys(target_sheets)),
                "public_instruction": instruction,
                "public_rules": ["Apply each entity's own supplied scenario and business policies; use the consolidation basis stated in Portfolio Index."],
                "scenario_inputs": [], "edits": edits, "native_issues": [],
                "reference_evidence": policies,
                "protected_inputs": [f"'{entity} {name}'!{view[name].calculate_dimension()}"
                                     for entity, view, *_ in entities
                                     for name in ("Read Me", "Source Inputs", "Scenario", "Calendar")],
                "involved_sheets": book.sheetnames,
                "portfolio_authoring": {"entity_count": len(entities), "source_workbook_modified": False,
                                        "difficulty_measured": False}}
        if mode == "financial_modeling":
            task["mask_ranges"] = masks
        return task
    finally:
        book.close()
        if values is not None:
            values.close()
