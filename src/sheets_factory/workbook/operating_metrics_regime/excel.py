"""Pure synthetic reports and two task views; oracle caches are unverified."""
from __future__ import annotations

from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.workbook.properties import CalcProperties

from . import spec, oracle_a, oracle_b, audit

S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
LABELS = {
    "revenue": "Sales revenue", "direct_cost": "Direct cost analysis, positive amount",
    "operating_expense": "Cash operating expense analysis, positive amount",
    "operating_profit": "Operating profit", "interest": "Interest expense analysis, positive amount",
    "pretax_before_associate": "Earnings before tax and associate result",
    "current_tax": "Current tax analysis, positive amount", "core_net_income": "After-tax earnings before associate result",
    "associate_income": "Associate result analysis, income-positive",
    "net_income": "Net income", "dividend": "Owner distribution", "operating_cash_flow": "Cash from operations, before owner distribution",
    "closing_cash": "Closing cash", "closing_investment": "Closing associate investment",
    "closing_retained_earnings": "Closing retained earnings", "debt": "Debt outstanding",
    "contributed_capital": "Contributed capital", "total_assets": "Total assets",
    "total_liabilities_equity": "Total liabilities and equity", "net_margin_percent": "Net income margin, percent units",
    "yoy_percent": "Sales change from same quarter last year, percent units",
    "qoq_percent": "Sales change from preceding quarter, percent units",
    "prior_year_multiple": "Sales multiple, prior year = 1x", "prior_year_index": "Sales index, prior year = 100",
    "cagr_percent": "Annualised sales growth since FY2025, percent units",
    "distribution_eligible": "Eligible for year-end owner distribution",
    "reported_direct_cost": "Direct operating costs", "reported_operating_expense": "Cash operating expenses",
    "reported_interest": "Cash interest", "reported_current_tax": "Current tax",
    "reported_associate_line": "Associate profit / (loss), after investee tax",
}
QUARTER_ORDER = ("revenue", "reported_direct_cost", "reported_operating_expense", "operating_profit",
    "reported_interest", "pretax_before_associate", "reported_current_tax", "core_net_income",
    "reported_associate_line", "net_income", "dividend", "operating_cash_flow",
    *spec.STOCK_FIELDS, *spec.QUARTER_METRICS, "direct_cost", "operating_expense", "interest", "current_tax", "associate_income")
TERM_FIELDS = ("id", "name", "layout", "money_unit", "sales_basis", "direct_cost_percent",
    "annual_interest_percent", "tax_percent", "cash", "investment", "debt", "capital", "retained_earnings")


def reference(path):
    path = Path(path).resolve(); raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False); stream.write("\n")
    return reference(path)


def _rewrite(source, destination, edits=None, *, clear_all_formula_caches=False):
    """Change only declared OOXML cells in a fresh archive; never recalculate."""
    edits = edits or {}
    with ZipFile(source) as original, ZipFile(destination, "x", ZIP_DEFLATED) as target:
        sheets = ET.fromstring(original.read("xl/workbook.xml")).find("{*}sheets")
        parts = {s.get("name"): f"xl/worksheets/sheet{i+1}.xml" for i, s in enumerate(sheets)}
        by_part = {parts[sheet]: cells for sheet, cells in edits.items()}
        changed = 0
        for item in original.infolist():
            raw = original.read(item.filename)
            if item.filename in by_part or (clear_all_formula_caches and item.filename in parts.values()):
                root = ET.fromstring(raw)
                for cell in root.findall("{*}sheetData/{*}row/{*}c"):
                    if clear_all_formula_caches and cell.find("{*}f") is not None:
                        _no_cache(cell); cell.attrib.pop("t", None); changed += 1
                    operation = by_part.get(item.filename, {}).get(cell.get("r"))
                    if operation is not None: operation(cell)
                raw = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            target.writestr(item, raw)
    return changed


def _no_cache(cell):
    for child in list(cell):
        if child.tag.rsplit("}", 1)[-1] == "v": cell.remove(child)


def _blank(cell):
    for child in list(cell):
        if child.tag.rsplit("}", 1)[-1] in ("f", "v", "is"): cell.remove(child)
    cell.attrib.pop("t", None)


def clear_formula_caches(source, destination):
    """Required cold source input: every formula cache removed, inputs retained."""
    count = _rewrite(source, destination, clear_all_formula_caches=True)
    return {"input": reference(source), "output": reference(destination), "all_formula_caches_removed": True,
        "formula_count": count, "actual_LO_calls": 0, "native_validation_claimed": False}


def _number_format(field):
    if field.endswith("percent"): return '0.00"%"'
    if field == "prior_year_multiple": return '0.00"x"'
    return '#,##0.00;[Red](#,##0.00)'


def _qualified(sheet, coordinate):
    return "'" + sheet.replace("'", "''") + "'!" + coordinate


def emit_workbook(path, public, result):
    spec.validate_spec(public)
    if result["specification_sha256"] != spec.canonical_sha256(public):
        raise ValueError("The workbook must bind the exact business specification")
    path = Path(path)
    if path.exists(): raise FileExistsError(path)
    book = openpyxl.Workbook(); readme = book.active; readme.title = "Read Me"
    readme.append(["Synthetic operating businesses: quarterly reports and management portfolio"])
    for heading, policy in public["public_policy"].items(): readme.append([heading.replace("_", " ").title(), policy])
    readme.column_dimensions["A"].width = 26; readme.column_dimensions["B"].width = 135
    readme.freeze_panes = "B2"
    terms = book.create_sheet("Opening and terms"); terms.append(["Opening balances and cash contracts; entity money units apply"])
    terms.append(["Business ID", "Business", "Presentation basis", "Money units", "Sales assumption basis",
        "Direct costs, percent of sales", "Annual cash-interest rate, percent units", "Current tax rate, percent units",
        "Opening cash", "Opening associate investment", "Fixed debt", "Contributed capital", "Opening retained earnings"])
    term_cells = {}; facts = []
    def literal(sheet, row, column, value, label):
        textual = label in ("id", "name", "layout", "money_unit", "sales_basis")
        natural = {"expense_columns":"Positive expense deductions", "signed_rows":"Signed account credits and debits",
            "GBP_thousands":"GBP thousands", "yoy_percent":"YoY change, percent units", "qoq_multiple":"Sequential revenue multiple, x"}
        shown = natural.get(value, value) if textual else float(Fraction(value))
        cell = sheet.cell(row, column, shown)
        cell.font = Font(color="0000AA")
        if not textual: cell.number_format = '0.00"%"' if label.endswith('percent') else '#,##0.00'
        facts.append({"sheet": sheet.title, "cell": cell.coordinate, "field": label, "provided_value": value,
            "expected_literal": {"type":"string" if textual else "number", "value":str(shown)}})
        return _qualified(sheet.title, cell.coordinate)
    for i, e in enumerate(public["entities"], 3):
        for column, field in enumerate(TERM_FIELDS, 1):
            value = e[field] if field not in e["opening"] else e["opening"][field]
            term_cells[e["id"], field] = literal(terms, i, column, value, field)
    distribution_cells = {}
    for i, field in enumerate(("profit_percent", "cagr_percent", "q4_yoy_percent"), len(public["entities"]) + 5):
        terms.cell(i, 1, {"profit_percent": "FY2027 distribution share, percent units", "cagr_percent": "Two-year sales CAGR hurdle, percent units", "q4_yoy_percent": "Q4 sales YoY hurdle, percent units"}[field])
        distribution_cells[field] = literal(terms, i, 2, public["distribution"][field], field)
    drivers = book.create_sheet("Quarterly drivers")
    drivers.append(["Business", "Calendar quarter", "Actual sales, entity money units", "Forecast sales assumption", "Sales assumption basis", "Cash fixed operating expense", "Associate result, income-positive"])
    driver_cells = {}
    for e in public["entities"]:
        for i in range(12):
            row = drivers.max_row + 1; period = f"{2025+i//4}Q{i%4+1}"
            drivers.cell(row, 1, e["id"]); drivers.cell(row, 2, period)
            if i < 4: driver_cells[e["id"], i, "actual"] = literal(drivers, row, 3, e["actual_revenue"][i], "actual_revenue")
            else: driver_cells[e["id"], i, "assumption"] = literal(drivers, row, 4, e["forecast_sales_assumptions"][i-4], "forecast_sales_assumptions")
            drivers.cell(row, 5, "Same quarter last year: change, percent units" if e["sales_basis"] == "yoy_percent" else "Immediately preceding quarter: revenue multiple, x")
            driver_cells[e["id"], i, "opex"] = literal(drivers, row, 6, e["quarterly_fixed_opex"][i], "quarterly_fixed_opex")
            driver_cells[e["id"], i, "associate"] = literal(drivers, row, 7, e["associate_results"][i], "associate_results")
    binding = {}
    def bind(sheet, row, column, identity, period, field):
        key = f"{identity}/{period}/{field}"
        if key in binding: raise ValueError("Duplicate business-field mapping")
        cell = sheet.cell(row, column); cell.number_format = _number_format(field)
        binding[key] = {"key": key, "sheet": sheet.title, "cell": cell.coordinate,
            "entity": identity, "period": period, "metric": field}
    for e in public["entities"]:
        sheet = book.create_sheet(e["id"] + (" Statements" if e["layout"] == "expense_columns" else " Accounts"))
        sheet.cell(1, 1, e["name"] + " — " + e["money_unit"].replace('_',' '))
        sheet.cell(2, 1, "Positive expense deductions" if e["layout"] == "expense_columns" else "Signed account credits / debits")
        sheet.freeze_panes = "B5"
        if e["layout"] == "expense_columns":
            for year_index, year in enumerate(spec.YEARS):
                start = 4 + year_index * (len(QUARTER_ORDER) + 4)
                sheet.cell(start, 1, f"FY{year} " + ("actual" if year == 2025 else "forecast"))
                for q in range(4): sheet.cell(start, q + 2, f"{year}Q{q+1}")
                for offset, field in enumerate(QUARTER_ORDER, 1):
                    label = "Associate charge / (credit), expense basis" if field == "reported_associate_line" and year == 2025 else LABELS[field]
                    sheet.cell(start + offset, 1, label)
                    for q in range(4): bind(sheet, start + offset, q + 2, e["id"], f"{year}Q{q+1}", field)
        else:
            sheet.cell(4, 1, "Calendar quarter")
            for column, field in enumerate(QUARTER_ORDER, 2): sheet.cell(4, column, LABELS[field])
            for i in range(12):
                row = 5 + i; period = f"{2025+i//4}Q{i%4+1}"
                sheet.cell(row, 1, period + (" actual" if i < 4 else " forecast"))
                for column, field in enumerate(QUARTER_ORDER, 2): bind(sheet, row, column, e["id"], period, field)
    portfolio = book.create_sheet("Portfolio quarters"); portfolio.append(["Management portfolio — all monetary amounts GBP"])
    portfolio_fields = (*spec.FLOW_FIELDS, *spec.STOCK_FIELDS, *spec.QUARTER_METRICS)
    portfolio.append(["Calendar quarter"] + [LABELS[k] for k in portfolio_fields])
    for i in range(12):
        period = f"{2025+i//4}Q{i%4+1}"; portfolio.cell(i + 3, 1, period)
        for c, field in enumerate(portfolio_fields, 2): bind(portfolio, i + 3, c, "PORTFOLIO", period, field)
    annual = book.create_sheet("Annual reporting")
    annual_fields = (*spec.FLOW_FIELDS, *spec.STOCK_FIELDS, *spec.ANNUAL_METRICS, "distribution_eligible")
    annual.append(["Business", "Fiscal year", "Money units"] + [LABELS[k].replace("same quarter last year", "previous fiscal year") for k in annual_fields])
    for e in [*public["entities"], {"id": "PORTFOLIO", "money_unit": "GBP"}]:
        for year in spec.YEARS:
            row = annual.max_row + 1; annual.cell(row, 1, e["id"]); annual.cell(row, 2, f"FY{year}"); annual.cell(row, 3, e["money_unit"].replace('_',' '))
            for c, field in enumerate(annual_fields, 4):
                if e["id"] != "PORTFOLIO" or field != "distribution_eligible": bind(annual, row, c, e["id"], f"FY{year}", field)
    if set(binding) != audit.expected_keys(public): raise ValueError("The complete independent field census is not mapped")
    def at(identity, period, field):
        b = binding[f"{identity}/{period}/{field}"]; return _qualified(b["sheet"], b["cell"])
    def expression(identity, period, field):
        h = lambda key: at(identity, period, key)
        if period.startswith("FY"):
            year = int(period[2:]); quarters = [f"{year}Q{q}" for q in range(1,5)]
            if field in spec.FLOW_FIELDS: return "SUM(" + ",".join(at(identity,q,field) for q in quarters) + ")"
            if field in spec.STOCK_FIELDS: return at(identity,quarters[-1],field)
            prior = at(identity,f"FY{year-1}","revenue") if year > 2025 else None
            ratio = f"({h('revenue')}/{prior})" if prior else None
            if field == "net_margin_percent": return f"100*{h('net_income')}/{h('revenue')}"
            if field == "yoy_percent": return f"100*({ratio}-1)" if ratio else None
            if field == "prior_year_multiple": return ratio
            if field == "prior_year_index": return f"100*{ratio}" if ratio else None
            if field == "cagr_percent": return None if year==2025 else f"100*(({h('revenue')}/{at(identity,'FY2025','revenue')})^(1/{year-2025})-1)"
            if field == "distribution_eligible":
                return "FALSE()" if year != 2027 else f"AND({h('net_income')}>0,{h('revenue')}*10000>={at(identity,'FY2025','revenue')}*(100+{distribution_cells['cagr_percent']})^2,{at(identity,'2027Q4','yoy_percent')}>={distribution_cells['q4_yoy_percent']})"
        index = (int(period[:4])-2025)*4+int(period[-1])-1
        prev = f"{2025+(index-1)//4}Q{(index-1)%4+1}"
        prior_year = f"{int(period[:4])-1}Q{period[-1]}"
        if identity == "PORTFOLIO" and field in (*spec.FLOW_FIELDS,*spec.STOCK_FIELDS):
            if field == 'net_income': return h('core_net_income')+'+'+h('associate_income')
            if field == 'operating_cash_flow': return h('net_income')+'-'+h('associate_income')
            return "+".join(at(e['id'],period,field)+("*1000" if e['money_unit']=="GBP_thousands" else "") for e in public['entities'])
        if field == "net_margin_percent": return f"100*{h('net_income')}/{h('revenue')}"
        if field == "yoy_percent": return f"100*({h('revenue')}/{at(identity,prior_year,'revenue')}-1)" if index>=4 else None
        if field == "qoq_percent": return f"100*({h('revenue')}/{at(identity,prev,'revenue')}-1)" if index else None
        if field == "prior_year_multiple": return f"{h('revenue')}/{at(identity,prior_year,'revenue')}" if index>=4 else None
        if field == "prior_year_index": return f"100*{h('prior_year_multiple')}" if index>=4 else None
        e = next(e for e in public['entities'] if e['id']==identity)
        t = lambda key: term_cells[identity,key]
        if field == "revenue":
            if index<4: return driver_cells[identity,index,'actual']
            assumption = driver_cells[identity,index,'assumption']
            return f"{at(identity,prior_year,'revenue')}*(1+{assumption}/100)" if e['sales_basis']=='yoy_percent' else f"{at(identity,prev,'revenue')}*{assumption}"
        if field == "net_income":
            if e['layout']=='signed_rows': return "SUM("+",".join(h(k) for k in ('revenue','reported_direct_cost','reported_operating_expense','reported_interest','reported_current_tax','reported_associate_line'))+")"
            return h('core_net_income')+("-" if index<4 else "+")+h('reported_associate_line')
        if field == "dividend": return f"IF({at(identity,'FY2027','distribution_eligible')},{at(identity,'FY2027','net_income')}*{distribution_cells['profit_percent']}/100,0)" if index==11 else "0"
        if field.startswith('reported_'):
            source = 'associate_income' if field=='reported_associate_line' else field[len('reported_'):]
            negative = (field=='reported_associate_line' and e['layout']=='expense_columns' and index<4) or (field!='reported_associate_line' and e['layout']=='signed_rows')
            return ('-' if negative else '')+h(source)
        opening = lambda key,stock: at(identity,prev,stock) if index else t(key)
        return {'direct_cost':f"{h('revenue')}*{t('direct_cost_percent')}/100",
            'operating_expense':driver_cells[identity,index,'opex'], 'operating_profit':f"{h('revenue')}-{h('direct_cost')}-{h('operating_expense')}",
            'interest':f"{t('debt')}*{t('annual_interest_percent')}/400",'pretax_before_associate':f"{h('operating_profit')}-{h('interest')}",
            'current_tax':f"MAX(0,{h('pretax_before_associate')})*{t('tax_percent')}/100",'core_net_income':f"{h('pretax_before_associate')}-{h('current_tax')}",
            'associate_income':driver_cells[identity,index,'associate'],'operating_cash_flow':f"{h('net_income')}-{h('associate_income')}",
            'closing_cash':f"{opening('cash','closing_cash')}+{h('operating_cash_flow')}-{h('dividend')}",
            'closing_investment':f"{opening('investment','closing_investment')}+{h('associate_income')}",
            'closing_retained_earnings':f"{opening('retained_earnings','closing_retained_earnings')}+{h('net_income')}-{h('dividend')}",
            'debt':t('debt'),'contributed_capital':t('capital'),'total_assets':f"{h('closing_cash')}+{h('closing_investment')}",
            'total_liabilities_equity':f"{h('debt')}+{h('contributed_capital')}+{h('closing_retained_earnings')}"}[field]
    caches = {}; fm = []
    for key, b in binding.items():
        cell = book[b['sheet']][b['cell']]; formula = expression(b['entity'],b['period'],b['metric'])
        if formula is None: cell.value = spec.NA
        else:
            cell.value = '='+formula; caches.setdefault(b['sheet'],{})[b['cell']] = (result['exact_values'][key],result['display_values'][key])
            if '2026' in b['period'] or '2027' in b['period']: fm.append({'key':key,'sheet':b['sheet'],'cell':b['cell']})
        b['expected_typed'] = result['display_values'][key]
    root_cases = [('ALDER/2026Q1/net_income',at('ALDER','2026Q1','core_net_income')+'-'+at('ALDER','2026Q1','reported_associate_line'),'associate_sign'),
        ('DELTA/2027Q4/yoy_percent','100*'+at('DELTA','2027Q4','revenue')+'/'+at('DELTA','2026Q4','revenue'),'growth_ratio_without_minus_one'),
        ('CEDAR/2026Q1/revenue',expression('CEDAR','2026Q1','revenue')+'/1000','money_unit'),
        ('BEACON/2026Q1/revenue',at('BEACON','2025Q4','revenue')+'*(1+'+driver_cells['BEACON',4,'assumption']+'/100)','wrong_comparison_quarter')]
    roots = [{**binding[key],'before':book[binding[key]['sheet']][binding[key]['cell']].value,'after':'='+formula,'mechanism':mechanism} for key,formula,mechanism in root_cases]
    for sheet in book:
        sheet.sheet_view.showGridLines = False
        sheet.column_dimensions['A'].width = 48
        for col in range(2,sheet.max_column+1): sheet.column_dimensions[get_column_letter(col)].width = 22
        for cell in sheet[1]: cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='24415C')
    readme.column_dimensions['B'].width=120
    for row in readme:
        readme.row_dimensions[row[0].row].height=55
        for cell in row:cell.alignment=Alignment(wrap_text=True,vertical='top')
    book.calculation=CalcProperties(calcMode='auto',fullCalcOnLoad=True,forceFullCalc=True)
    temporary=path.with_name(path.name+'.uncached.xlsx');book.save(temporary);book.close()
    edits={}
    for sheet, cells in caches.items():
        for coordinate,(exact,typed) in cells.items():
            def seed(node,exact=exact,typed=typed):
                _no_cache(node);node.attrib.pop('t',None)
                if type(exact) is bool: node.set('t','b');text='1' if exact else '0'
                elif isinstance(exact,tuple): text=typed['value']
                else:
                    with localcontext() as ctx:
                        ctx.prec=80;text=format(Decimal(exact.numerator)/Decimal(exact.denominator),'f')
                ET.SubElement(node,'{'+S+'}v').text=text
            edits.setdefault(sheet,{})[coordinate]=seed
    _rewrite(temporary,path,edits);temporary.unlink()
    return {'bindings':list(binding.values()),'provided_facts':facts,'FM_mask_points':fm,'DBG_root_edits':roots,
        'oracle_seeded_caches_unverified':True,'actual_LO_calls':0,'qualified':False}


def build_views(output,public=None):
    output=Path(output).resolve()
    if output.exists(): raise FileExistsError(output)
    public=spec.default_spec() if public is None else spec.validate_spec(public)
    left,right=oracle_a.solve(public),oracle_b.solve(public); checked=audit.compare_results(public,left,right)
    if not checked['passed']: raise ValueError('Independent complete business oracles disagree')
    if {e['id'] for e in public['entities']} != {'ALDER','BEACON','CEDAR','DELTA'}:
        raise ValueError('This first emitter uses the complete frozen four-business inventory')
    output.mkdir(parents=True);(output/'private').mkdir()
    raw=write(output/'private/specification.json',public)
    goal=output/'private/goal_seeded_unverified.xlsx'; definition=emit_workbook(goal,public,left)
    expected={r['sheet']+'!'+r['cell']:right['display_values'][r['key']] for r in definition['bindings']}
    cold=clear_formula_caches(goal,output/'private/goal_cold_start.xlsx')
    views={}
    for mode in ('financial_modeling','debugging'):
        folder=output/mode;folder.mkdir();edits={}
        if mode=='financial_modeling':
            for point in definition['FM_mask_points']: edits.setdefault(point['sheet'],{})[point['cell']]=_blank
        else:
            for root in definition['DBG_root_edits']:
                def change(cell,formula=root['after']):cell.find('{*}f').text=formula[1:];_no_cache(cell)
                edits.setdefault(root['sheet'],{})[root['cell']]=change
        _rewrite(goal,folder/'input.xlsx',edits,clear_all_formula_caches=True)
        text=('Complete the FY2026 and FY2027 operating reports and management portfolio for all four businesses.' if mode=='financial_modeling'
            else 'Audit and repair the FY2026 and FY2027 operating reports and management portfolio for all four businesses.')
        instruction=text+' Use the supplied FY2025 actuals, opening balances and operating assumptions. The Read Me sheet and report labels state the business conventions. Preserve supplied facts and make every financial report consistent. The data are synthetic.\n'
        with (folder/'instruction.md').open('x') as stream:stream.write(instruction)
        views[mode]={'input':reference(folder/'input.xlsx'),'instruction':reference(folder/'instruction.md')}
    return write(output/'preparation.json',{'kind':'prepared_unverified_operating_metrics_regime_pair','version':1,
        'specification':raw,'specification_sha256':spec.canonical_sha256(public),'goal':reference(goal),'cold_source_input':cold['output'],
        'cold_source_cache_clearance':write(output/'private/cold_source_cache_clearance.json',cold),
        'bindings':write(output/'private/bindings.json',definition),'independent_expected':write(output/'private/expected_normalized.json',expected),
        'independent_crosscheck':write(output/'private/independent_crosscheck.json',checked),'views':views,
        'dimensions':{'entities':4,'quarters':12,'years':list(spec.YEARS),'layouts':2,'money_units':2,'sales_bases':2},
        'independent_oracle_values_crosschecked':len(expected),'FM_mask_count':len(definition['FM_mask_points']),
        'DBG_root_count':len(definition['DBG_root_edits']),'formula_count':cold['formula_count'],
        'recipe_sha256':{str(Path(m.__file__).resolve()):reference(m.__file__)['sha256'] for m in (spec,oracle_a,oracle_b,audit)},
        'emitter':reference(__file__),'source_type':'new_synthetic','official_workbook_seed_used':False,
        'oracle_seeded_goal_is_not_native_validation':True,'first_source_native_input_requires_all_formula_caches_cleared':True,
        'actual_LO_calls':0,'model_calls':0,'optimizer_calls':0,'qualified':False,'engineering_or_difficulty_certified':False})
