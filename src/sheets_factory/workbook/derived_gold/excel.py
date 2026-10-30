"""Emit an auditable Excel model from the public contract.

No numeric forecasting or oracle ledger is called here. Excel/LibreOffice
evaluates these formulas; the independent event ledger checks its results.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter as L


MAPPINGS = {
    "Calendar": {"period": 2, "date": 3, "year": 4, "month_days": 5},
    "Operations": {"sales": 2, "cogs": 3, "other_opex": 4, "startup_expense": 5,
                   "ebitda": 6, "depreciation_initial": 7, "depreciation_refresh": 8,
                   "depreciation": 9, "ebit": 10, "interest": 11, "ebt": 12,
                   "tax": 13, "net_income": 14, "ar_open": 15, "ar_close": 16,
                   "delta_ar": 17, "inventory_open": 18, "inventory_close": 19,
                   "delta_inventory": 20, "ap_open": 21, "ap_close": 22, "delta_ap": 23},
    "Assets": {"capex": 2, "asset_initial_gross": 6, "asset_refresh_gross": 7,
               "accumulated_depreciation": 8, "net_ppe": 9},
    "Debt": {"loan_a_open": 2, "loan_a_interest": 3, "loan_a_scheduled_principal": 4,
             "loan_a_extra_principal": 5, "loan_a_close": 6, "loan_b_open": 7,
             "loan_b_interest": 8, "loan_b_principal": 9, "loan_b_close": 10,
             "revolver_open": 11, "revolver_interest": 12, "revolver_draw": 13,
             "revolver_repayment": 14, "revolver_close": 15},
    "Tax": {"nol_open": 3, "nol_use": 4, "nol_add": 5, "nol_close": 6},
    "Cash Flow": {"cash_open": 2, "cfo_direct": 3, "cfo_indirect": 4, "cfi": 5,
                  "cash_before_allocation": 8, "cash_gap": 9, "dividend": 10,
                  "cff": 11, "cash_close": 12},
    "Balance Sheet": {"retained_open": 15, "retained_close": 16, "assets": 9,
                      "liabilities": 14, "equity": 18, "balance_check": 19},
    "Equity Value": {"owner_cashflow": 16},
}
MONTHLY_BINDINGS = {key: {"sheet": sheet, "row": row}
                    for sheet, keys in MAPPINGS.items() for key, row in keys.items()}
OPEN_KEYS = {k for k in MONTHLY_BINDINGS if k.endswith("_open")}
STOCK_KEYS = {k for k in MONTHLY_BINDINGS if k.endswith("_close")} | {
    "asset_initial_gross", "asset_refresh_gross", "accumulated_depreciation", "net_ppe",
    "assets", "liabilities", "equity", "balance_check", "cash_before_allocation",
}
ANNUAL_KEYS = sorted(set(MONTHLY_BINDINGS) - {"period", "date", "year", "month_days"})
VALUATION_BINDINGS = {
    "loan_a_payment": "B2", "annual_discount_rate": "B3", "monthly_discount_rate": "B4",
    "next_annual_sales": "B5", "next_ebitda": "B6", "enterprise_value": "B7",
    "exit_fee": "B8", "equity_exit": "B9", "equity_npv": "B10",
    "monthly_equity_irr": "B11", "annual_equity_irr": "B12",
}


def _sheet_ref(sheet, cell):
    return "'" + sheet.replace("'", "''") + "'!" + cell


def emit_workbook(spec: dict, destination: Path) -> dict:
    p = spec["parameters"]
    n = int(p["months"])
    book = openpyxl.Workbook()
    book.active.title = "Read Me"
    for sheet in ("Source Inputs", "Scenario", "Calendar", "Operations", "Assets", "Debt", "Tax", "Cash Flow", "Balance Sheet", "Equity Value", "Annual Statements"):
        book.create_sheet(sheet)
    readme = book["Read Me"]
    readme["A1"], readme["B1"] = "Model", spec["title"]
    readme["A2"], readme["B2"] = "Scenario", spec["scenario_id"]
    for row, rule in enumerate(spec["public_rules"], 4):
        readme.cell(row, 1, row - 3)
        readme.cell(row, 2, rule)
        readme.row_dimensions[row].height = 64
    readme["B22"] = "Purpose: evaluate commissioning, debt funding, operating cash generation and owner returns for the stated hypothetical project."

    source = book["Source Inputs"]
    source.append(["Anchor", "Source value", "Source sheet/cell", "Meaning"])
    anchor_rows = {}
    for idx, (key, anchor) in enumerate(spec["source_lineage"]["anchors"].items(), 2):
        anchor_rows[key] = idx
        source.cell(idx, 1, key)
        source.cell(idx, 2, float(anchor["value"]))
        source.cell(idx, 3, anchor["sheet"] + "!" + anchor["cell"])
        source.cell(idx, 4, anchor["label"])
    source["A10"] = "Cash EBITDA margin benchmark"
    source["B10"] = f"=ROUND((B{anchor_rows['ebit']}+B{anchor_rows['da']})/B{anchor_rows['revenue']},12)"
    source["A12"], source["B12"] = "Source URL", spec["source_lineage"]["source_url"]
    source["A13"], source["B13"] = "Source SHA256", spec["source_lineage"]["sha256"]
    source["A14"], source["B14"] = "Use", spec["source_lineage"]["derivation"]

    scenario = book["Scenario"]
    scenario.append(["Parameter", "Value", "Units / status"])
    param_rows, flattened = {}, {}
    for key, value in p.items():
        if isinstance(value, list):
            for idx, item in enumerate(value, 1):
                flattened[f"ramp_{idx}"] = item
        else:
            flattened[key] = value
    for idx, (key, value) in enumerate(flattened.items(), 2):
        param_rows[key] = idx
        scenario.cell(idx, 1, key)
        scenario.cell(idx, 2, datetime.fromisoformat(value) if key == "start_date" else float(value))
        scenario.cell(idx, 3, "explicit hypothetical assumption")
    def param(key):
        return _sheet_ref("Scenario", f"$B${param_rows[key]}")
    def source_ref(key):
        return _sheet_ref("Source Inputs", f"$B${anchor_rows[key]}")
    derived = {
        "cash_ebitda_margin": "='Source Inputs'!B10",
        "annual_sales_growth": "=" + source_ref("growth"),
        "tax_rate": "=" + source_ref("tax_rate"),
        "annual_equity_discount_rate": "=ROUND(" + source_ref("equity_rate") + "+" + param("equity_risk_premium") + ",12)",
    }
    for facility in ("loan_a", "loan_b", "revolver"):
        derived[facility + "_annual_rate"] = "=ROUND(" + source_ref("debt_rate") + "+" + param(facility + "_spread") + ",12)"
    for key, formula in derived.items():
        scenario.cell(param_rows[key], 2, formula)
        scenario.cell(param_rows[key], 3, "public source benchmark / stated hypothetical spread")
    payment_row = len(flattened) + 3
    scenario.cell(payment_row, 1, "Original Loan A level payment")
    scenario.cell(payment_row, 2, "=IF(" + param("loan_a_annual_rate") + "=0,ROUND(" + param("loan_a_principal") + "/" + param("loan_a_amort_payments") + ",2),ROUND(-PMT(" + param("loan_a_annual_rate") + "/12," + param("loan_a_amort_payments") + "," + param("loan_a_principal") + "),2))")
    payment = _sheet_ref("Scenario", f"$B${payment_row}")

    for sheet, keys in MAPPINGS.items():
        for key, row in keys.items():
            book[sheet].cell(row, 1, key.replace("_", " "))
            book[sheet].cell(row, 2, "USD" if key not in {"period", "date", "year", "month_days"} else key)
    extra_labels = {"Assets": {3: "Initial asset depreciation", 4: "Refresh depreciation", 5: "Total depreciation"},
                    "Debt": {16: "Total cash interest", 17: "Original level payment"},
                    "Tax": {2: "Year-to-date pretax income", 7: "Year-end cash tax"},
                    "Cash Flow": {6: "Scheduled Loan A principal", 7: "Loan B principal", 13: "Excess after revolver", 14: "Optional allocation allowed", 15: "Cash reconciliation"},
                    "Balance Sheet": {2: "Cash", 3: "Receivables", 4: "Inventory", 5: "Initial asset cost including CIP", 6: "Refresh asset cost", 7: "Accumulated depreciation", 8: "Net fixed assets including CIP", 10: "Payables", 11: "Loan A", 12: "Loan B", 13: "Revolver", 17: "Paid-in equity"},
                    "Calendar": {6: "Calendar month", 7: "Year end", 8: "Ramp factor"}}
    for sheet, labels in extra_labels.items():
        for row, label in labels.items():
            book[sheet].cell(row, 1, label)

    for t in range(1, n + 1):
        col, prev = L(t + 2), L(t + 1)
        def ref(sheet, row):
            return _sheet_ref(sheet, col + str(row))
        def prior(sheet, row):
            return _sheet_ref(sheet, prev + str(row))
        def put(sheet, row, expression):
            # Every posted amount is a cent balance, including subtraction and
            # aggregation. Otherwise binary residue at an exact half-cent can
            # change a later sweep allocation by one cent.
            if sheet != "Calendar" and (sheet, row) != ("Cash Flow", 14):
                expression = "ROUND(" + expression + ",2)"
            book[sheet][col + str(row)] = "=" + expression
        period = ref("Calendar", 2)
        year = ref("Calendar", 4)
        yearend = ref("Calendar", 7)
        year_start_col = L(3 + 12 * ((t - 1) // 12))
        for sheet in MAPPINGS:
            book[sheet][col + "1"] = "=" + ref("Calendar", 3) if sheet != "Calendar" else f"Month {t}"
        put("Calendar", 2, str(t))
        put("Calendar", 3, "EDATE(" + param("start_date") + "," + period + "-1)")
        put("Calendar", 4, "INT((" + period + "-1)/12)+1")
        put("Calendar", 5, "DAY(EOMONTH(" + ref("Calendar", 3) + ",0))")
        put("Calendar", 6, "MONTH(" + ref("Calendar", 3) + ")")
        put("Calendar", 7, "IF(MOD(" + period + ",12)=0,1,0)")
        ramp_first = param("ramp_1")
        ramp_last = param("ramp_6")
        put("Calendar", 8, "IF(" + period + "<=" + param("construction_months") + ",0,IF(" + period + ">" + param("construction_months") + "+6,1,INDEX(" + ramp_first + ":" + ramp_last + "," + period + "-" + param("construction_months") + ")))")

        put("Assets", 2, "IF(" + period + "=" + param("refresh_paid_month") + "," + param("refresh_capex") + ",0)")
        for row, cost, service, life in [(3, "initial_asset_cost", "initial_asset_service_month", "initial_asset_life"), (4, "refresh_capex", "refresh_service_month", "refresh_life")]:
            used = "0" if t == 1 else "SUM($C" + str(row) + ":" + prev + str(row) + ")"
            put("Assets", row, "IF(" + period + "<" + param(service) + ",0,MIN(ROUND(" + param(cost) + "/" + param(life) + ",2),MAX(0," + param(cost) + "-" + used + ")))")
        put("Assets", 5, col + "3+" + col + "4")
        put("Assets", 6, param("initial_asset_cost"))
        put("Assets", 7, ("0" if t == 1 else prev + "7") + "+" + col + "2")
        put("Assets", 8, ("0" if t == 1 else prev + "8") + "+" + col + "5")
        put("Assets", 9, col + "6+" + col + "7-" + col + "8")

        put("Operations", 2, "ROUND(" + param("steady_annual_sales") + "*(1+" + param("annual_sales_growth") + ")^(" + year + "-1)/12*" + ref("Calendar", 8) + ",2)")
        put("Operations", 3, "ROUND(" + col + "2*" + param("cash_cogs_fraction") + ",2)")
        put("Operations", 4, "ROUND(" + col + "2*(1-" + param("cash_ebitda_margin") + "-" + param("cash_cogs_fraction") + "),2)")
        startup_prior = "0" if t == 1 else "SUM($C5:" + prev + "5)"
        put("Operations", 5, "IF(" + period + ">" + param("construction_months") + ",0,IF(" + period + "=" + param("construction_months") + "," + param("startup_expense") + "-" + startup_prior + ",ROUND(" + param("startup_expense") + "/" + param("construction_months") + ",2)))")
        put("Operations", 6, col + "2-" + col + "3-" + col + "4-" + col + "5")
        for row, asset_row in ((7, 3), (8, 4), (9, 5)):
            put("Operations", row, ref("Assets", asset_row))
        put("Operations", 10, col + "6-" + col + "9")
        put("Operations", 11, ref("Debt", 16))
        put("Operations", 12, col + "10-" + col + "11")
        put("Operations", 13, ref("Tax", 7))
        put("Operations", 14, col + "12-" + col + "13")
        for opening, closing, delta, basis, days_key in [(15, 16, 17, col + "2", "dso"), (18, 19, 20, col + "3", "dio"), (21, 22, 23, col + "3", "dpo")]:
            put("Operations", opening, "0" if t == 1 else prev + str(closing))
            put("Operations", closing, "ROUND(" + basis + "/" + ref("Calendar", 5) + "*" + param(days_key) + ",2)")
            put("Operations", delta, col + str(closing) + "-" + col + str(opening))

        put("Debt", 2, param("loan_a_principal") if t == 1 else prev + "6")
        put("Debt", 3, "ROUND(" + col + "2*" + param("loan_a_annual_rate") + "/12,2)")
        put("Debt", 4, "IF(" + period + "<" + param("loan_a_amort_start") + ",0,MIN(" + col + "2,MAX(0," + payment + "-" + col + "3)))")
        put("Debt", 5, "IF(" + ref("Cash Flow", 14) + "=1,MIN(" + col + "2-" + col + "4,ROUND(" + ref("Cash Flow", 13) + "*" + param("cash_sweep_fraction") + ",2)),0)")
        put("Debt", 6, col + "2-" + col + "4-" + col + "5")
        put("Debt", 7, param("loan_b_principal") if t == 1 else prev + "10")
        put("Debt", 8, "ROUND(" + col + "7*" + param("loan_b_annual_rate") + "/12,2)")
        put("Debt", 9, "IF(" + period + "=" + param("loan_b_bullet_month") + "," + col + "7,0)")
        put("Debt", 10, col + "7-" + col + "9")
        put("Debt", 11, "0" if t == 1 else prev + "15")
        put("Debt", 12, "ROUND(" + col + "11*" + param("revolver_annual_rate") + "/12,2)")
        put("Debt", 13, "MIN(MAX(0," + param("minimum_cash") + "-" + ref("Cash Flow", 8) + "),MAX(0," + param("revolver_limit") + "-" + col + "11))")
        put("Debt", 14, "MIN(" + col + "11,MAX(0," + ref("Cash Flow", 8) + "-" + param("minimum_cash") + "))")
        put("Debt", 15, col + "11+" + col + "13-" + col + "14")
        put("Debt", 16, col + "3+" + col + "8+" + col + "12")
        put("Debt", 17, payment)

        put("Tax", 2, "SUM(" + _sheet_ref("Operations", year_start_col + "12:" + col + "12") + ")")
        put("Tax", 3, param("opening_nol") if t == 1 else prev + "6")
        put("Tax", 4, "IF(" + yearend + "=1,MIN(" + col + "3,ROUND(MAX(0," + col + "2)*" + param("nol_utilization_cap") + ",2)),0)")
        put("Tax", 5, "IF(" + yearend + "=1,MAX(0,-" + col + "2),0)")
        put("Tax", 6, col + "3+" + col + "5-" + col + "4")
        put("Tax", 7, "IF(" + yearend + "=1,ROUND((MAX(0," + col + "2)-" + col + "4)*" + param("tax_rate") + ",2),0)")

        put("Cash Flow", 2, param("opening_cash") if t == 1 else prev + "12")
        put("Cash Flow", 3, ref("Operations", 2) + "-" + ref("Operations", 17) + "-" + ref("Operations", 3) + "-" + ref("Operations", 4) + "-" + ref("Operations", 5) + "-" + ref("Operations", 20) + "+" + ref("Operations", 23) + "-" + ref("Operations", 11) + "-" + ref("Operations", 13))
        put("Cash Flow", 4, ref("Operations", 14) + "+" + ref("Operations", 9) + "-" + ref("Operations", 17) + "-" + ref("Operations", 20) + "+" + ref("Operations", 23))
        put("Cash Flow", 5, "-" + ref("Assets", 2))
        put("Cash Flow", 6, ref("Debt", 4))
        put("Cash Flow", 7, ref("Debt", 9))
        put("Cash Flow", 8, col + "2+" + col + "3+" + col + "5-" + col + "6-" + col + "7")
        put("Cash Flow", 9, "MAX(0," + param("minimum_cash") + "-" + col + "8-" + ref("Debt", 13) + ")")
        put("Cash Flow", 10, "IF(" + col + "14=1," + col + "13-" + ref("Debt", 5) + ",0)")
        put("Cash Flow", 11, ref("Debt", 13) + "-" + ref("Debt", 14) + "-" + ref("Debt", 4) + "-" + ref("Debt", 5) + "-" + ref("Debt", 9) + "-" + col + "10")
        put("Cash Flow", 12, col + "2+" + col + "3+" + col + "5+" + col + "11")
        put("Cash Flow", 13, "MAX(0," + col + "8+" + ref("Debt", 13) + "-" + ref("Debt", 14) + "-" + param("minimum_cash") + ")")
        put("Cash Flow", 14, "IF(" + period + ">=" + param("cash_allocation_start") + ",1,0)")
        put("Cash Flow", 15, col + "2+" + col + "3+" + col + "5+" + col + "11-" + col + "12")

        bs_refs = {2: ("Cash Flow", 12), 3: ("Operations", 16), 4: ("Operations", 19),
                   5: ("Assets", 6), 6: ("Assets", 7), 7: ("Assets", 8), 8: ("Assets", 9),
                   10: ("Operations", 22), 11: ("Debt", 6), 12: ("Debt", 10), 13: ("Debt", 15)}
        for row, (sheet, other_row) in bs_refs.items():
            put("Balance Sheet", row, ref(sheet, other_row))
        put("Balance Sheet", 9, col + "2+" + col + "3+" + col + "4+" + col + "8")
        put("Balance Sheet", 14, "SUM(" + col + "10:" + col + "13)")
        put("Balance Sheet", 15, param("opening_retained") if t == 1 else prev + "16")
        put("Balance Sheet", 16, col + "15+" + ref("Operations", 14) + "-" + ref("Cash Flow", 10))
        put("Balance Sheet", 17, param("equity_paid_in"))
        put("Balance Sheet", 18, col + "17+" + col + "16")
        put("Balance Sheet", 19, col + "9-" + col + "14-" + col + "18")

    eq = book["Equity Value"]
    for key, address in VALUATION_BINDINGS.items():
        eq["A" + address[1:]] = key.replace("_", " ")
    last = L(n + 2)
    eq["B2"] = "=" + payment
    eq["B3"] = "=" + param("annual_equity_discount_rate")
    eq["B4"] = "=(1+B3)^(1/12)-1"
    eq["B5"] = "=ROUND(" + param("steady_annual_sales") + "*(1+" + param("annual_sales_growth") + ")^(" + param("months") + "/12),2)"
    eq["B6"] = "=ROUND(B5*" + param("cash_ebitda_margin") + ",2)"
    eq["B7"] = "=ROUND(B6*" + param("exit_multiple") + ",2)"
    eq["B8"] = "=ROUND(B7*" + param("exit_fee_fraction") + ",2)"
    eq["B9"] = "=ROUND(B7+" + _sheet_ref("Cash Flow", last + "12") + "-" + _sheet_ref("Debt", last + "6") + "-" + _sheet_ref("Debt", last + "10") + "-" + _sheet_ref("Debt", last + "15") + "-B8,2)"
    eq["B10"] = "=ROUND(NPV(B4,C16:" + last + "16)+B16,2)"
    eq["B11"] = "=IRR(B16:" + last + "16,0.01)"
    eq["B12"] = "=(1+B11)^12-1"
    eq["A15"], eq["B15"], eq["A16"], eq["A17"], eq["A18"] = "Owner flows outside entity books", "Month 0", "Owner cash flow", "Dividend", "PV of owner cash flow"
    eq["B16"] = "=-" + param("equity_paid_in")
    for t in range(1, n + 1):
        c = L(t + 2)
        eq[c + "15"] = "=" + _sheet_ref("Calendar", c + "3")
        eq[c + "16"] = "=ROUND(" + _sheet_ref("Cash Flow", c + "10") + ("+$B$9" if t == n else "") + ",2)"
        eq[c + "17"] = "=" + _sheet_ref("Cash Flow", c + "10")
        eq[c + "18"] = "=ROUND(" + c + "16/(1+$B$4)^" + str(t) + ",2)"

    annual = book["Annual Statements"]
    annual_rows = {}
    for idx, key in enumerate(ANNUAL_KEYS, 6):
        annual_rows[key] = idx
        annual.cell(idx, 1, key.replace("_", " "))
        annual.cell(idx, 2, "USD")
        for year in range(1, 4):
            binding = MONTHLY_BINDINGS[key]
            row = binding["row"]
            first, final = L(3 + (year - 1) * 12), L(2 + year * 12)
            if key in OPEN_KEYS:
                formula = "=" + _sheet_ref(binding["sheet"], first + str(row))
            elif key in STOCK_KEYS:
                formula = "=" + _sheet_ref(binding["sheet"], final + str(row))
            else:
                formula = "=ROUND(SUM(" + _sheet_ref(binding["sheet"], first + str(row) + ":" + final + str(row)) + "),2)"
            annual.cell(idx, year + 2, formula)
    for year in range(1, 4):
        c, first, final = L(year + 2), L(3 + (year - 1) * 12), L(2 + year * 12)
        annual[c + "1"] = f"Year {year}"
        annual[c + "2"] = year
        annual[c + "3"] = 12
        annual[c + "4"] = "=" + _sheet_ref("Calendar", first + "3")
        annual[c + "5"] = "=EOMONTH(" + _sheet_ref("Calendar", final + "3") + ",0)"
    for row, label in ((2, "Year"), (3, "Periods"), (4, "Start date"), (5, "End date")):
        annual.cell(row, 1, label)

    for ws in book:
        ws.freeze_panes = "C2"
        ws.column_dimensions["A"].width = 35
        ws.column_dimensions["B"].width = 25
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="204E63")
        for cell in ws._cells.values():
            if cell.column >= 3 and cell.data_type == "f":
                cell.number_format = "#,##0.00;[Red](#,##0.00)"
    for t in range(1, n + 1):
        c = L(t + 2)
        for sheet in MAPPINGS:
            book[sheet][c + "1"].number_format = "mmm yyyy" if sheet != "Calendar" else "General"
            book[sheet].column_dimensions[c].width = 18
        book["Calendar"][c + "3"].number_format = "yyyy-mm-dd"
        eq[c + "15"].number_format = "mmm yyyy"
    for year in range(1, 4):
        for row in (4, 5):
            annual.cell(row, year + 2).number_format = "yyyy-mm-dd"
    scenario.cell(param_rows["start_date"], 2).number_format = "yyyy-mm-dd"
    for row in (3, 4, 11, 12):
        eq.cell(row, 2).number_format = "0.000000%"
    readme.column_dimensions["B"].width = 125
    for cell in readme._cells.values():
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    book.calculation = openpyxl.workbook.properties.CalcProperties(calcId=0, fullCalcOnLoad=True, forceFullCalc=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    book.save(destination)
    return {"monthly": MONTHLY_BINDINGS, "annual": annual_rows,
            "valuation": VALUATION_BINDINGS, "parameter_rows": param_rows,
            "source_anchor_rows": anchor_rows, "payment_row": payment_row}
