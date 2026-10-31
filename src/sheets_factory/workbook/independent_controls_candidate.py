"""New synthetic independent-control source and paired candidate preparation.

This emitter writes formulas from explicit public assumptions. It never imports
the independent oracle and never inserts expected answers into formula caches.
No official workbook, existing task, finance kernel, model or service is used.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils.cell import get_column_letter
from openpyxl.workbook.properties import CalcProperties

KIND = "synthetic_independent_controls_financial_candidate"
VERSION = 1
ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config/independent_controls_candidate_v1.json"
FIELDS = ("opening_revenue", "opening_cash", "opening_debt", "revenue", "ebitda", "interest", "cash_tax", "working_capital_change", "mandatory_principal", "cash_before_funding", "borrowing_capacity", "new_borrowing", "sponsor_cure", "cash_sweep", "closing_debt", "closing_cash", "enterprise_value", "residual_equity", "cumulative_sponsor_cures", "contribution_adjusted_residual")
ENTITY_FIELDS = ("opening_revenue", "opening_cash", "opening_debt", "minimum_cash", "annual_principal", "tax_rate", "working_capital_fraction", "enterprise_multiple")
POLICIES = (
    "Operating and financing scenarios are independent. Each listed crossed state is a separate plan; no state changes another state's assumptions.",
    "All money is in the stated currency unit; annual periods end on the labeled year. Entities are financially separate.",
    "Interest is charged on opening drawn debt. Cash tax applies to positive EBITDA after interest; there is no depreciation deduction or loss carryforward in this planning model.",
    "Contracted principal is paid before new funding. Borrowing cannot exceed the remaining facility limit. Sponsors supply any remaining minimum-cash requirement.",
    "After funding, the contractual fraction of cash above the minimum reserve repays debt, limited to the remaining debt balance.",
    "Enterprise value uses nonnegative period EBITDA at the stated multiple. Report residual equity and the residual after cumulative sponsor cash contributions; debt is valued at par.",
)


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def reference(path):
    p = Path(path).resolve(); data = p.read_bytes()
    return {"path": str(p), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def write_new(path, value):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("x") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False); stream.write("\n")
    return reference(p)


def _number(value, low, high):
    require(isinstance(value, str) and re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", value), "Assumptions must be plain finite decimal strings")
    number = Decimal(value)
    require(Decimal(str(low)) <= number <= Decimal(str(high)), "Assumption outside bounded business domain")
    return number


def validate(value):
    public = deepcopy(value)
    require(set(public) == {"kind", "version", "currency_unit", "first_year", "periods", "default_operating", "default_financing", "operating", "financing", "entities"}, "Unknown or missing synthetic assumptions")
    require(public["kind"] == KIND and type(public["version"]) is int and public["version"] == VERSION, "New synthetic identity required")
    require(public["currency_unit"] == "USD thousands" and type(public["first_year"]) is int and 2020 <= public["first_year"] <= 2100, "Explicit units and annual periods required")
    require(type(public["periods"]) is int and 1 <= public["periods"] <= 6, "Use one to six periods")
    require(isinstance(public["operating"], list) and isinstance(public["financing"], list) and 2 <= len(public["operating"]) == len(public["financing"]) <= 5, "Two to five independent scenarios per axis required")
    require(isinstance(public["entities"], list) and 1 <= len(public["entities"]) <= 5, "Use one to five entities")
    for family, prefix, fields in (("operating", "O", {"growth", "ebitda_margin"}), ("financing", "F", {"interest_rate", "facility_limit", "sweep_fraction"})):
        for i, row in enumerate(public[family], 1):
            require(set(row) == {"id", "name"} | fields and row["id"] == f"{prefix}{i:02d}", "Scenario fields and sequential identities required")
            require(isinstance(row["name"], str) and 1 <= len(row["name"]) <= 80 and not row["name"].startswith("="), "Readable scenario name required")
            for key in fields:
                bounds = {"growth": (-.5, .5), "ebitda_margin": (-.5, .6), "interest_rate": (0, .5), "facility_limit": (0, 1_000_000), "sweep_fraction": (0, 1)}[key]
                _number(row[key], *bounds)
    for i, row in enumerate(public["entities"], 1):
        require(set(row) == {"id", "name", "capex"} | set(ENTITY_FIELDS) and row["id"] == f"E{i:02d}", "Entity fields and sequential identity required")
        require(isinstance(row["name"], str) and 1 <= len(row["name"]) <= 80 and not row["name"].startswith("="), "Readable entity name required")
        for field in ENTITY_FIELDS:
            _number(row[field], 0, 1 if field in {"tax_rate", "working_capital_fraction"} else 20 if field == "enterprise_multiple" else 1_000_000)
        require(_number(row["opening_revenue"], 0, 1_000_000) > 0, "Positive opening revenue required")
        require(isinstance(row["capex"], list) and len(row["capex"]) == public["periods"], "Every annual capital-spend assumption required")
        for amount in row["capex"]:
            _number(amount, 0, 1_000_000)
    oi = [r["id"] for r in public["operating"]]; fi = [r["id"] for r in public["financing"]]
    require(public["default_operating"] in oi and public["default_financing"] in fi and oi.index(public["default_operating"]) != fi.index(public["default_financing"]), "Default plan must be an explicit mixed state")
    require(all(Decimal(e["opening_debt"]) <= Decimal(f["facility_limit"]) for e in public["entities"] for f in public["financing"]), "Opening drawn debt must fit every supplied facility")
    return public


def load(path=CONFIG):
    return validate(json.loads(Path(path).read_text()))


def public_brief(public, mode):
    require(mode in {"FM", "DBG"}, "Explicit candidate mode required")
    operation = next(r["name"] for r in public["operating"] if r["id"] == public["default_operating"])
    finance = next(r["name"] for r in public["financing"] if r["id"] == public["default_financing"])
    action = "Complete the cash-flow and valuation planning model" if mode == "FM" else "Audit and repair the cash-flow and valuation planning model"
    return (f"{action} for every listed entity, annual period and operating/financing combination. "
        "The two scenario controls are independent; retain the complete crossed-state comparison as well as the default-plan summary. "
        f"The default plan combines {operation} with {finance}. Follow the financing term sheet and preserve the provided assumptions, labels, units and layout.\n")


def _layout(public):
    result = []; row = 5
    for ei, entity in enumerate(public["entities"]):
        for oi, operation in enumerate(public["operating"]):
            for fi, finance in enumerate(public["financing"]):
                for period in range(public["periods"]):
                    result.append({"row": row, "entity_index": ei, "operating_index": oi, "financing_index": fi, "period_index": period, "entity": entity["id"], "operating": operation["id"], "financing": finance["id"], "year": public["first_year"] + period})
                    row += 1
    return result


def _style(sheet):
    sheet.freeze_panes = "G5"; sheet.sheet_view.showGridLines = False
    for row in sheet:
        for cell in row:
            cell.font = Font(name="Aptos", size=10, color="000000" if cell.data_type == "f" else "0000AA")
            if cell.row == 4:
                cell.fill = PatternFill("solid", fgColor="17365D"); cell.font = Font(name="Aptos", bold=True, color="FFFFFF")
            if isinstance(cell.value, (int, float)) or cell.data_type == "f": cell.number_format = '#,##0.00;[Red](#,##0.00);–'
    for col in range(1, sheet.max_column + 1): sheet.column_dimensions[get_column_letter(col)].width = 20
    integer_columns = {"Crossed plans": (2, 4, 6), "Operating scenarios": (1,), "Financing scenarios": (1,), "Capital spending": (2,)}.get(sheet.title, ())
    percentage_columns = {"Operating scenarios": (3, 4), "Financing scenarios": (3, 5), "Entities": (8, 9)}.get(sheet.title, ())
    for row in range(5, sheet.max_row + 1):
        for col in integer_columns: sheet.cell(row, col).number_format = "0"
        for col in percentage_columns: sheet.cell(row, col).number_format = "0.0%"
        if sheet.title == "Entities": sheet.cell(row, 10).number_format = '0.0"x"'
    sheet.auto_filter.ref = f"A4:{get_column_letter(sheet.max_column)}{sheet.max_row}"


def emit(public, output):
    """Emit one uncalculated formula gold. Expected numeric caches are absent."""
    public = validate(public); output = Path(output); require(not output.exists(), "Fresh formula workbook required")
    workbook = Workbook(); workbook.remove(workbook.active)
    policy = workbook.create_sheet("Read me")
    policy.append(["Independent scenario cash-flow planning"]); policy.append([public["currency_unit"]])
    for statement in POLICIES: policy.append([statement])
    policy.column_dimensions["A"].width = 115
    for row in policy:
        row[0].alignment = Alignment(wrap_text=True); policy.row_dimensions[row[0].row].height = 34
    operating = workbook.create_sheet("Operating scenarios"); financing = workbook.create_sheet("Financing scenarios"); entities = workbook.create_sheet("Entities"); capex = workbook.create_sheet("Capital spending")
    for sheet, headers in ((operating, ["Code", "Operating scenario", "Annual revenue growth", "EBITDA margin"]), (financing, ["Code", "Financing scenario", "Opening-debt interest rate", "Facility limit", "Cash-sweep fraction"]), (entities, ["Entity", "Business", *ENTITY_FIELDS]), (capex, ["Entity", "Annual period", "Capital expenditure"])):
        sheet.cell(1, 1, public["currency_unit"])
        for col, value in enumerate(headers, 1): sheet.cell(4, col, value.replace("_", " "))
    for i, row in enumerate(public["operating"], 5): operating.append([i - 4, row["name"], float(row["growth"]), float(row["ebitda_margin"])])
    for i, row in enumerate(public["financing"], 5): financing.append([i - 4, row["name"], float(row["interest_rate"]), float(row["facility_limit"]), float(row["sweep_fraction"])])
    for entity in public["entities"]:
        entities.append([entity["id"], entity["name"], *[float(entity[k]) for k in ENTITY_FIELDS]])
        for period, amount in enumerate(entity["capex"]): capex.append([entity["id"], public["first_year"] + period, float(amount)])
    cash = workbook.create_sheet("Crossed plans"); cash.cell(1, 1, public["currency_unit"])
    headers = ["Entity", "Operating code", "Operating scenario", "Financing code", "Financing scenario", "Annual period", *FIELDS]
    for col, value in enumerate(headers, 1): cash.cell(4, col, value.replace("_", " "))
    layout = _layout(public); targets = []; mutations = []
    n = len(public["financing"]); operation_end = len(public["operating"]) + 4
    for item in layout:
        r = item["row"]; ei = item["entity_index"]; oi = item["operating_index"]; fi = item["financing_index"]; period = item["period_index"]
        er = ei + 5; cr = ei * public["periods"] + period + 5
        for col, val in enumerate([item["entity"], oi + 1, public["operating"][oi]["name"], fi + 1, public["financing"][fi]["name"], item["year"]], 1): cash.cell(r, col, val)
        finance_index = f"$D{r}"; wrong_index = f"$B{r}"
        rate = f"INDEX('Financing scenarios'!$C$5:$C${n+4},{finance_index})"; limit = f"INDEX('Financing scenarios'!$D$5:$D${n+4},{finance_index})"; fraction = f"INDEX('Financing scenarios'!$E$5:$E${n+4},{finance_index})"
        formulas = [
            f"='Entities'!C{er}" if period == 0 else f"=J{r-1}",
            f"='Entities'!D{er}" if period == 0 else f"=V{r-1}",
            f"='Entities'!E{er}" if period == 0 else f"=U{r-1}",
            f"=G{r}*(1+INDEX('Operating scenarios'!$C$5:$C${operation_end},$B{r}))",
            f"=J{r}*INDEX('Operating scenarios'!$D$5:$D${operation_end},$B{r})",
            f"=I{r}*{rate}", f"=MAX(0,K{r}-L{r})*'Entities'!H{er}",
            f"=(J{r}-G{r})*'Entities'!I{er}", f"=MIN(I{r},'Entities'!G{er})",
            f"=H{r}+K{r}-L{r}-M{r}-'Capital spending'!C{cr}-N{r}-O{r}",
            f"=MAX(0,{limit}-(I{r}-O{r}))", f"=MIN(MAX(0,'Entities'!F{er}-P{r}),Q{r})",
            f"=MAX(0,'Entities'!F{er}-P{r}-R{r})",
            f"=MIN(I{r}-O{r}+R{r},MAX(0,P{r}+R{r}+S{r}-'Entities'!F{er})*{fraction})",
            f"=I{r}-O{r}+R{r}-T{r}", f"=P{r}+R{r}+S{r}-T{r}",
            f"=MAX(0,K{r})*'Entities'!J{er}", f"=W{r}-U{r}+V{r}",
            f"=S{r}" if period == 0 else f"=Y{r-1}+S{r}", f"=X{r}-Y{r}",
        ]
        for col, (field, formula) in enumerate(zip(FIELDS, formulas), 7):
            address = f"{get_column_letter(col)}{r}"; cash.cell(r, col, formula)
            targets.append({"sheet": cash.title, "cell": address, "field": field, "before": formula, **{k: item[k] for k in ("entity", "operating", "financing", "year")}})
            if col in {12, 17, 20}: mutations.append({"family": "independent_financing_control", "sheet": cash.title, "cell": address, "before": formula, "after": formula.replace(finance_index, wrong_index)})
            elif col == 24: mutations.append({"family": "enterprise_equity_bridge", "sheet": cash.title, "cell": address, "before": formula, "after": formula + f"-R{r}"})
    summary = workbook.create_sheet("Default plan")
    summary.append(["Independent default plan", public["default_operating"], public["default_financing"]]); summary.append([public["currency_unit"]])
    for col, text in enumerate(["Entity", "Closing cash", "Closing debt", "Enterprise value", "Residual equity", "Sponsor cures", "Contribution-adjusted residual"], 1): summary.cell(4, col, text)
    for ei, entity in enumerate(public["entities"], 5):
        item = next(x for x in layout if x["entity"] == entity["id"] and x["operating"] == public["default_operating"] and x["financing"] == public["default_financing"] and x["period_index"] == public["periods"] - 1)
        summary.cell(ei, 1, entity["name"])
        for col, field in enumerate(("closing_cash", "closing_debt", "enterprise_value", "residual_equity", "cumulative_sponsor_cures", "contribution_adjusted_residual"), 2):
            source_col = get_column_letter(FIELDS.index(field) + 7); address = f"{get_column_letter(col)}{ei}"; summary.cell(ei, col, f"='Crossed plans'!{source_col}{item['row']}")
            targets.append({"sheet": summary.title, "cell": address, "field": field, "before": summary[address].value, **{k: item[k] for k in ("entity", "operating", "financing", "year")}})
    for sheet in workbook:
        if sheet.title != "Read me": _style(sheet)
    workbook.calculation = CalcProperties(calcMode="auto", fullCalcOnLoad=True, forceFullCalc=True, iterate=False)
    output.parent.mkdir(parents=True, exist_ok=True); workbook.save(output)
    return {"source": reference(output), "layout": layout, "financial_targets": targets, "debug_mutations": mutations,
        "all_crossed_states_scored": True, "formula_caches_calculated": False,
        "actual_LO_model_solver_Harbor_calls": 0, "financial_or_difficulty_qualification": False}


def materialize(source, output, edits):
    """Change only declared cell definitions in a fresh synthetic workbook."""
    output = Path(output); require(not output.exists(), "Fresh candidate workbook required")
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"; relns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with ZipFile(source) as z:
        rels = {v.get("Id"): v.get("Target") for v in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        paths = {s.get("name"): rels[s.get("{" + relns + "}id")].lstrip("/") for s in ET.fromstring(z.read("xl/workbook.xml")).find("{*}sheets")}
        by_part = {}
        for edit in edits:
            part = paths[edit["sheet"]]; part = part if part.startswith("xl/") else "xl/" + part
            require((part, edit["cell"]) not in by_part, "Duplicate cell edit")
            by_part[(part, edit["cell"])] = edit
        changed = set(); output.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(output, "x", ZIP_DEFLATED) as out:
            for member in z.infolist():
                payload = z.read(member.filename)
                selected = {cell: edit for (part, cell), edit in by_part.items() if part == member.filename}
                if selected:
                    tree = ET.fromstring(payload)
                    for cell in tree.findall("{*}sheetData/{*}row/{*}c"):
                        if cell.get("r") not in selected: continue
                        edit = selected[cell.get("r")]; formula = cell.find("{*}f")
                        require(formula is not None and "=" + (formula.text or "") == edit["before"], "Cold cell definition does not match frozen plan")
                        for child in list(cell): cell.remove(child)
                        cell.attrib.pop("t", None)
                        if edit["after"] is not None: ET.SubElement(cell, "{" + ns + "}f").text = edit["after"].removeprefix("=")
                        changed.add((member.filename, cell.get("r")))
                    payload = ET.tostring(tree, encoding="utf-8")
                out.writestr(member, payload)
        require(changed == set(by_part), "Every declared edit must be applied")
    return reference(output)


def recipes():
    paths = [Path(__file__), Path(__file__).with_name("independent_controls_oracle.py"), ROOT / "scripts/prepare_independent_controls_candidate.py", CONFIG, ROOT / "tests/test_independent_controls_candidate.py", ROOT / "docs/independent_controls_candidate.md"]
    return {str(p.relative_to(ROOT)): reference(p) for p in paths}
