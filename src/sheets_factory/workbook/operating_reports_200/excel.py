"""Six natural report layouts and native formulas; no oracle imports/caches."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter, quote_sheetname
from openpyxl.workbook.properties import CalcProperties
from . import schema as s

LABELS = {
    "revenue":"Sales", "direct_cost":"Direct operating costs", "operating_expense":"Cash operating expenses", "operating_profit":"Operating profit", "interest":"Cash interest", "pretax_before_associate":"Earnings before parent tax and associate", "current_tax":"Current parent tax", "core_net_income":"After-tax earnings before associate", "associate_income":"Associate profit / (loss), after investee tax", "net_income":"Net income", "dividend":"Owner distribution", "operating_cash_flow":"Cash from operations", "closing_cash":"Closing cash", "closing_investment":"Associate investment", "closing_retained_earnings":"Retained earnings", "debt":"Fixed debt", "contributed_capital":"Contributed capital", "total_assets":"Total assets", "total_liabilities_equity":"Total liabilities and equity", "net_margin_percent":"Net profit margin", "yoy_percent":"Same-quarter year-on-year sales change", "qoq_percent":"Previous-quarter sales change", "prior_year_multiple":"Prior-year sales multiple (base 1)", "prior_year_index":"Prior-year sales index (base 100)", "yoy_sales_delta":"Same-quarter year-on-year sales monetary change", "qoq_sales_delta":"Previous-quarter sales monetary change", "cagr_percent":"Sales CAGR from FY2025", "annual_sales_delta":"Annual sales monetary change", "distribution_eligible":"Distribution policy eligibility", "reported_direct_cost":"Presented direct costs", "reported_operating_expense":"Presented cash operating expenses", "reported_interest":"Presented cash interest", "reported_current_tax":"Presented current tax", "reported_associate_line":"Presented associate profit / (loss)",
}
MONEY_LABEL = {"GBP":"GBP", "GBP_thousands":"GBP thousands", "GBP_millions":"GBP millions"}
RATE_LABEL = {"fraction":"fraction", "percent_units":"%", "basis_points":"bp"}
INPUT_FONT = Font(color="0000A0")
OUTPUT_FILL = PatternFill("solid", fgColor="F0F4FA")


def _sheet_name(e):
    return (e["id"]+" "+e["name"])[:31]


def _ordered_fields(e, entity=True):
    flows=list(s.FLOWS)
    stocks=list(s.STOCKS)
    metrics=list(s.QUARTER_METRICS)+(list(s.REPORTED) if entity else [])
    order=e.get("line_order", "statement_first")
    if order == "cash_first":
        flows[1],flows[2]=flows[2],flows[1]
        stocks=stocks[3:]+stocks[:3]
        return stocks+flows+metrics
    if order == "performance_first":
        return metrics+flows+stocks
    return flows+stocks+metrics


def _label(field, e, annual=False):
    text=LABELS[field]
    if annual and field == "yoy_percent": text="Year-on-year annual sales change"
    if field.endswith("_percent"):
        text+=" ("+RATE_LABEL[e.get("rate_unit","percent_units")]+")"
    elif field not in ("prior_year_multiple","prior_year_index","distribution_eligible"):
        text+=" ("+MONEY_LABEL[e.get("money_unit","GBP")]+")"
    return text


def _allocate(ws, e, entity, bindings):
    identity=e["id"]
    fields=_ordered_fields(e,entity)
    layout=e.get("layout","quarter_columns")
    ws["A1"]=e["name"]
    ws["A2"]="Calendar reporting | FY2025 actual; FY2026–FY2027 forecast"
    ws["A3"]=MONEY_LABEL[e.get("money_unit","GBP")]+" | rates "+RATE_LABEL[e.get("rate_unit","percent_units")]
    if entity:
        ws["A4"]="Costs shown as positive deductions" if e["statement_sign"] == "positive_deductions" else "Expense contributions shown negative"
        ws["A5"]="From FY2026 associate result is income-positive; FY2025 associate charge/(credit) is zero."
    positions={}
    if layout in ("quarter_columns","reverse_chronology_dashboard"):
        periods=list(s.QUARTERS)
        if layout == "reverse_chronology_dashboard": periods.reverse()
        for c,p in enumerate(periods,2):ws.cell(8,c,p+ (" actual" if p.startswith("2025") else " forecast"))
        for r,f in enumerate(fields,9):
            ws.cell(r,1,_label(f,e))
            for c,p in enumerate(periods,2):positions[p,f]=(r,c)
        annual_start=55
    elif layout == "quarter_rows":
        start=8
        for section in (s.FLOWS,s.STOCKS,tuple(f for f in fields if f not in s.FLOWS+s.STOCKS)):
            ordered=[f for f in fields if f in section]
            for c,f in enumerate(ordered,2):ws.cell(start,c,_label(f,e))
            for r,p in enumerate(s.QUARTERS,start+1):
                ws.cell(r,1,p)
                for c,f in enumerate(ordered,2):positions[p,f]=(r,c)
            start+=16
        annual_start=65
    elif layout == "year_panels":
        for yi,year in enumerate(s.YEARS):
            start=8+yi*39
            ws.cell(start,1,f"FY{year} "+("actual" if year==2025 else "forecast"))
            for q in range(1,5):ws.cell(start+1,q+1,f"{year}Q{q}")
            for r,f in enumerate(fields,start+2):
                ws.cell(r,1,_label(f,e))
                for q in range(1,5):positions[f"{year}Q{q}",f]=(r,q+1)
        annual_start=130
    elif layout == "quarter_cards":
        for i,p in enumerate(s.QUARTERS):
            top=8+(i//4)*39; left=1+(i%4)*17
            ws.cell(top,left,p)
            for r,f in enumerate(fields,top+1):
                ws.cell(r,left,_label(f,e));positions[p,f]=(r,left+12)
        annual_start=130
    elif layout == "split_reporting_sections":
        for c,p in enumerate(s.QUARTERS,2):ws.cell(8,c,p)
        for r,f in enumerate(s.FLOWS,9):
            ws.cell(r,1,_label(f,e))
            for c,p in enumerate(s.QUARTERS,2):positions[p,f]=(r,c)
        for c,f in enumerate(s.STOCKS,2):ws.cell(26,c,_label(f,e))
        for r,p in enumerate(s.QUARTERS,27):
            ws.cell(r,1,p)
            for c,f in enumerate(s.STOCKS,2):positions[p,f]=(r,c)
        extra=[f for f in fields if f not in s.FLOWS+s.STOCKS]
        for c,p in enumerate(s.QUARTERS,2):ws.cell(43,c,p)
        for r,f in enumerate(extra,44):
            ws.cell(r,1,_label(f,e))
            for c,p in enumerate(s.QUARTERS,2):positions[p,f]=(r,c)
        annual_start=65
    else:raise ValueError("Unsupported natural report layout")
    for p in s.QUARTERS:
        for f in fields:
            r,c=positions[p,f]
            bindings[f"{identity}/{p}/{f}"]={"sheet":ws.title,"cell":ws.cell(r,c).coordinate,"role":"report","money_unit":e.get("money_unit","GBP"),"rate_unit":e.get("rate_unit","percent_units")}
    annual_fields=s.FLOWS+s.STOCKS+s.ANNUAL_METRICS+("distribution_eligible",)
    ws.cell(annual_start,1,"Full-year management report")
    for c,y in enumerate(s.YEARS,2):ws.cell(annual_start+1,c,f"FY{y}")
    for r,f in enumerate(annual_fields,annual_start+2):
        ws.cell(r,1,_label(f,e,True))
        for c,y in enumerate(s.YEARS,2):
            bindings[f"{identity}/FY{y}/{f}"]={"sheet":ws.title,"cell":ws.cell(r,c).coordinate,"role":"report","money_unit":e.get("money_unit","GBP"),"rate_unit":e.get("rate_unit","percent_units")}
    ws.freeze_panes="B9"
    ws.sheet_view.showGridLines=False
    ws.column_dimensions["A"].width=55
    for col in range(2,81):ws.column_dimensions[get_column_letter(col)].width=15
    return annual_start+34


def emit(public_specification, output_directory):
    public=s.validate_spec(public_specification)
    output=Path(output_directory);output.mkdir(parents=True,exist_ok=False)
    wb=Workbook();readme=wb.active;readme.title="ReadMe"
    wb.calculation=CalcProperties(calcId=0,fullCalcOnLoad=True,forceFullCalc=True,calcMode="auto")
    readme["A1"]="Hypothetical service-business management reports"
    for row,paragraph in enumerate(public["public_policy"].strip().split("\n\n"),3):
        readme.cell(row,1,paragraph);readme.cell(row,1).alignment=Alignment(wrap_text=True);readme.row_dimensions[row].height=75
    readme.column_dimensions["A"].width=125
    index=wb.create_sheet("Index");index.append(["Business code","Business name","Management division","Report"])
    bindings={};facts={};sheet_by_id={};entities={e["id"]:e for e in public["entities"]}
    for e in public["entities"]:
        ws=wb.create_sheet(_sheet_name(e));sheet_by_id[e["id"]]=ws.title
        input_start=_allocate(ws,e,True,bindings)
        index.append([e["id"],e["name"],e["division"],"Open report"])
        index.cell(index.max_row,4).hyperlink="#"+quote_sheetname(ws.title)+"!A1"
        _inputs(ws,e,input_start,facts)
    members={"DIV_"+d.upper():[e["id"]for e in public["entities"]if e["division"]==d]for d in public["divisions"]}
    members["PORTFOLIO"]=list(members)
    for identity, ids in members.items():
        name="Master portfolio" if identity=="PORTFOLIO" else identity[4:].title()+" division"
        ws=wb.create_sheet(name);sheet_by_id[identity]=name
        _allocate(ws,{"id":identity,"name":name},False,bindings)
        ws["A4"]="Member businesses: "+", ".join(entities[i]["name"] for i in ids) if identity!="PORTFOLIO" else "Eight management divisions; every business included once."
        ws["A4"].alignment=Alignment(wrap_text=True);ws.row_dimensions[4].height=60
    def ref(identity,period,field):
        binding=bindings[f"{identity}/{period}/{field}"]
        return quote_sheetname(binding["sheet"])+"!"+binding["cell"]
    def fact(identity,field,period=None):
        item=facts[identity+"/"+field+("/"+period if period else "")]
        return quote_sheetname(item["sheet"])+"!"+item["cell"]
    kinds=dict(s.points(public))
    entity_scales={e["id"]:{"GBP":1,"GBP_thousands":1000,"GBP_millions":1000000}[e["money_unit"]]for e in public["entities"]}
    source_formulas={}
    for key,binding in bindings.items():
        identity,period,field=key.split("/");e=entities.get(identity)
        cell=wb[binding["sheet"]][binding["cell"]]
        cell.fill=OUTPUT_FILL
        cell.number_format="General" if kinds[key]=="boolean" else "0.00;[Red](0.00)"
        if kinds[key]=="text":
            cell.value=s.GROUP_NA if field=="distribution_eligible" else s.NA;binding["role"]="given_NA";continue
        cell.value="="+_formula(identity,period,field,e,members,ref,fact,entity_scales)
        source_formulas[key]=cell.value
        if len(cell.value)>8192:raise ValueError("Formula exceeds native workbook limit")
    point_count=len(bindings);formula_count=sum(cell.data_type=="f"for ws in wb for cell in ws._cells.values())
    nonempty=sum(cell.value is not None for ws in wb for cell in ws._cells.values())
    expected_formulas=sum(t!="text"for t in kinds.values())
    if point_count!=len(kinds) or formula_count!=expected_formulas:raise ValueError("Incomplete financial report binding/formula census")
    if formula_count>100000 or nonempty>250000 or len(wb.sheetnames)>250 or any(ws.max_row>1000 or ws.max_column>80 for ws in wb):raise ValueError("Approved pure construction cap exceeded")
    wb.save(output/"source_uncalculated.xlsx")
    _exact_numeric_inputs(output/"source_uncalculated.xlsx",facts)
    # Save FM/DBG by native package surgery, preserving every other ZIP member.
    _views(output/"source_uncalculated.xlsx",output,public,bindings,ref,fact,source_formulas)
    financial_cells={(b["sheet"],b["cell"])for b in bindings.values()}
    fact_values={(b["sheet"],b["cell"]):b["value"]for b in facts.values()}
    context={}
    for ws in wb:
        for cell in ws._cells.values():
            if cell.value is None or(ws.title,cell.coordinate)in financial_cells:continue
            context[ws.title+"!"+cell.coordinate]={"sheet":ws.title,"cell":cell.coordinate,"role":"provided_context","value":fact_values.get((ws.title,cell.coordinate),cell.value),"cell_type":cell.data_type,"number_format":cell.number_format,"style_id":cell.style_id,"hyperlink":cell.hyperlink.target if cell.hyperlink else None}
    private={"kind":"private_operating_reports_200_bindings","version":1,"specification_sha256":s.canonical_sha256(public),"financial":bindings,"provided_facts":facts,"provided_context":context}
    (output/"private_bindings.json").write_text(json.dumps(private,ensure_ascii=False,indent=2)+"\n")
    receipt={"kind":"pure_operating_reports_200_emission","version":1,"specification_sha256":s.canonical_sha256(public),"report_positions":point_count,"formulas":formula_count,"nonempty":nonempty,"sheets":len(wb.sheetnames),"max_rows":max(ws.max_row for ws in wb),"max_columns":max(ws.max_column for ws in wb),"all_report_NA_nonempty":sum(t=="text"for t in kinds.values()),"all_driver_NA_nonempty":12*len(entities),"source_caches_seeded":False,"native_calculations":0,"source_or_difficulty_certified":False}
    (output/"receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    return receipt


def _inputs(ws,e,start,facts):
    identity=e["id"];ws.cell(start,1,"Opening facts and supplied assumptions")
    def put(field,label,value,period=None):
        nonlocal start
        start+=1;ws.cell(start,1,label);cell=ws.cell(start,2)
        ws.cell(start,1).alignment=Alignment(wrap_text=True)
        ws.row_dimensions[start].height=33
        cell.value=value if isinstance(value,str)and value.startswith("n/a")else float(value)
        cell.font=INPUT_FONT;cell.number_format="0.###############"
        facts[identity+"/"+field+("/"+period if period else "")]={"sheet":ws.title,"cell":cell.coordinate,"value":value,"role":"provided_fact"}
    for field,value in e["opening"].items():put("opening_"+field,"Opening "+field.replace("_"," ")+" ("+MONEY_LABEL[e["money_unit"]]+")",value)
    for field,label in (("direct_cost_rate","Direct cost rate"),("annual_interest_rate","Annual cash-interest rate"),("parent_tax_rate","Current parent-tax rate")):
        put(field,label+" ("+RATE_LABEL[e["rate_unit"]]+")",e[field])
    for p in s.QUARTERS:
        put("actual_sales",p+" actual sales ("+MONEY_LABEL[e["money_unit"]]+")",e["actual_sales"].get(p,s.FORECAST_ACTUAL_NA),p)
        year=p[:4]
        if p.startswith("2025"):label=p+" forecast assumption";value=s.ACTUAL_DRIVER_NA
        else:
            form=e["driver_form_by_year"][year]
            measure={"change_rate":"sales change ("+RATE_LABEL[e["rate_unit"]]+")","level_multiple":"sales level multiple (base 1)","base100_index":"sales level index (base 100)","money_delta":"sales monetary change ("+MONEY_LABEL[e["money_unit"]]+")"}[form]
            basis="same quarter last year" if e["forecast_reference"]=="same_quarter_last_year"else"previous calendar quarter"
            label=p+" "+measure+" versus "+basis;value=e["forecast_sales"][p]
        put("forecast_sales",label,value,p)
        put("cash_opex",p+" supplied cash operating expenses ("+MONEY_LABEL[e["money_unit"]]+")",e["cash_opex"][p],p)
        put("associate_results",p+" associate income-positive result ("+MONEY_LABEL[e["money_unit"]]+")",e["associate_results"][p],p)
    ws.column_dimensions["A"].width=70
    ws.column_dimensions["B"].width=25


def _formula(identity,period,field,e,members,ref,fact,entity_scales):
    r=lambda p,f:ref(identity,p,f)
    money={"GBP":1,"GBP_thousands":1000,"GBP_millions":1000000}[e["money_unit"]]if e else 1
    rate={"fraction":"100","percent_units":"1","basis_points":"0.01"}[e["rate_unit"]]if e else "1"
    group=e is None
    annual=period.startswith("FY")
    if annual:
        year=int(period[2:]);previous=f"FY{year-1}"
        if field in s.FLOWS:return "SUM("+",".join(r(f"{year}Q{q}",field)for q in range(1,5))+")"
        if field in s.STOCKS:return r(f"{year}Q4",field)
        if field=="distribution_eligible":
            if year!=2027:return "FALSE()"
            return "AND("+r("FY2027","revenue")+"*625>="+r("FY2025","revenue")+"*729,"+r("2027Q4","revenue")+"*20>="+r("2026Q4","revenue")+"*21)"
        if field=="cagr_percent":return "100*(("+r(period,"revenue")+"/"+r("FY2025","revenue")+")^(1/"+str(year-2025)+")-1)/"+rate
    else:
        i=s.QUARTERS.index(period)
        previous=s.QUARTERS[i-1]if i else None
        if group and field in s.FLOWS+s.STOCKS:
            args=[]
            for member in members[identity]:
                conversion=1
                if not member.startswith("DIV_"):
                    # All local entity monetary reports are converted once to GBP.
                    conversion=entity_scales[member]
                args.append(ref(member,period,field)+("*"+str(conversion)if conversion!=1 else ""))
            return "SUM("+",".join(args)+")"
        if not group:
            if field=="revenue":
                if i<4:return fact(identity,"actual_sales",period)
                basis=r(s.QUARTERS[i-(4 if e["forecast_reference"]=="same_quarter_last_year"else 1)],"revenue")
                driver=fact(identity,"forecast_sales",period);form=e["driver_form_by_year"][period[:4]]
                return basis+"+"+driver if form=="money_delta"else basis+"*(1+"+driver+"*"+rate+"/100)"if form=="change_rate"else basis+"*"+driver if form=="level_multiple"else basis+"*"+driver+"/100"
            if field=="direct_cost":return r(period,"revenue")+"*"+fact(identity,"direct_cost_rate")+"*"+rate+"/100"
            if field=="operating_expense":return fact(identity,"cash_opex",period)
            if field=="interest":return fact(identity,"opening_debt")+"*"+fact(identity,"annual_interest_rate")+"*"+rate+"/400"
            if field=="associate_income":return fact(identity,"associate_results",period)
            if field=="operating_profit":return r(period,"revenue")+"-"+r(period,"direct_cost")+"-"+r(period,"operating_expense")
            if field=="pretax_before_associate":return r(period,"operating_profit")+"-"+r(period,"interest")
            if field=="current_tax":return "MAX(0,"+r(period,"pretax_before_associate")+")*"+fact(identity,"parent_tax_rate")+"*"+rate+"/100"
            if field=="core_net_income":return r(period,"pretax_before_associate")+"-"+r(period,"current_tax")
            if field=="net_income":return r(period,"core_net_income")+"+"+r(period,"associate_income")
            if field=="operating_cash_flow":return r(period,"net_income")+"-"+r(period,"associate_income")
            if field=="dividend":return "IF("+r("FY2027","distribution_eligible")+",MAX(0,"+r("FY2027","net_income")+")*20/100,0)"if period=="2027Q4"else"0"
            if field=="debt":return fact(identity,"opening_debt")
            if field=="contributed_capital":return fact(identity,"opening_capital")
            if field in ("closing_cash","closing_investment","closing_retained_earnings"):
                opening={"closing_cash":"cash","closing_investment":"investment","closing_retained_earnings":"retained_earnings"}[field]
                prior=r(previous,field)if previous else fact(identity,"opening_"+opening)
                return prior+"+"+r(period,"operating_cash_flow")+"-"+r(period,"dividend")if field=="closing_cash"else prior+"+"+r(period,"associate_income")if field=="closing_investment"else prior+"+"+r(period,"net_income")+"-"+r(period,"dividend")
            if field=="total_assets":return r(period,"closing_cash")+"+"+r(period,"closing_investment")
            if field=="total_liabilities_equity":return r(period,"debt")+"+"+r(period,"contributed_capital")+"+"+r(period,"closing_retained_earnings")
            if field.startswith("reported_"):
                base="associate_income"if field=="reported_associate_line"else field[9:]
                negative=(base=="associate_income"and i<4 and e["statement_sign"]=="positive_deductions")or(base!="associate_income"and e["statement_sign"]=="signed_contributions")
                return ("-"if negative else "")+r(period,base)
    if field=="net_margin_percent":return r(period,"net_income")+"/"+r(period,"revenue")+"*100/"+rate
    if annual:
        compare=previous
    else:compare=s.QUARTERS[s.QUARTERS.index(period)-4]
    ratio=r(period,"revenue")+"/"+r(compare,"revenue")
    if field=="yoy_percent":return "("+ratio+"-1)*100/"+rate
    if field=="prior_year_multiple":return ratio
    if field=="prior_year_index":return ratio+"*100"
    if field in ("annual_sales_delta","yoy_sales_delta"):return r(period,"revenue")+"-"+r(compare,"revenue")
    if field=="qoq_percent":return "("+r(period,"revenue")+"/"+r(previous,"revenue")+"-1)*100/"+rate
    if field=="qoq_sales_delta":return r(period,"revenue")+"-"+r(previous,"revenue")
    raise ValueError("No native formula for declared report field: "+field)


def _views(source,out,public,bindings,ref,fact,source_formulas):
    from zipfile import ZipFile,ZIP_DEFLATED
    import xml.etree.ElementTree as ET
    ns="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    kinds=dict(s.points(public));edits={};fm=[]
    design_path=Path(__file__).resolve().parents[4]/"config/operating_reports_200_frozen_design_v1.json"
    axes=json.loads(design_path.read_text())["artifacts"]["axis_assignment.json"]["value"]["entities"]
    axes={e["id"]:e for e in axes}
    entity_by_id={e["id"]:e for e in public["entities"]}
    for key,b in bindings.items():
        if kinds[key]!="text"and(key.split("/")[1].startswith("2026")or key.split("/")[1].startswith("2027")or key.split("/")[1]in("FY2026","FY2027")):fm.append(key)
    for identity,e in entity_by_id.items():
        family=axes[identity]["fault_family"]
        period="2027Q4"if family=="ratio_as_change"else"2026Q1"
        field="net_income"if family=="associate_sign"else"yoy_percent"if family=="ratio_as_change"else"revenue"
        key=f"{identity}/{period}/{field}";binding=bindings[key]
        if family=="associate_sign":formula=ref(identity,period,"core_net_income")+"-"+ref(identity,period,"associate_income")
        elif family=="ratio_as_change":
            rate={"fraction":"100","percent_units":"1","basis_points":"0.01"}[e["rate_unit"]]
            formula=ref(identity,period,"revenue")+"/"+ref(identity,"2026Q4","revenue")+"*100/"+rate
        elif family=="money_scale":formula="("+source_formulas[key][1:]+")/1000"
        else:
            actual="2025Q1"if e["forecast_reference"]=="previous_calendar_quarter"else"2025Q4"
            original="2025Q4"if actual=="2025Q1"else"2025Q1"
            formula=source_formulas[key][1:].replace(ref(identity,original,"revenue"),ref(identity,actual,"revenue"))
            if formula==source_formulas[key][1:]:raise ValueError("Declared reference-quarter fault made no definition change")
        edits[key]={"family":family,"sheet":binding["sheet"],"cell":binding["cell"],"healthy_formula":source_formulas[key],"faulty_formula":"="+formula}
    _surgery(source,out/"financial_modeling_input.xlsx",bindings,{key:None for key in fm})
    _surgery(source,out/"debugging_input.xlsx",bindings,{key:item["faulty_formula"]for key,item in edits.items()})
    (out/"view_plans.json").write_text(json.dumps({"kind":"pure_operating_reports_200_view_plans","version":1,"FM_mask":fm,"DBG_faults":edits,"actual_D_unknown":True,"native_calls":0},indent=2)+"\n")


def _surgery(source,destination,bindings,edits):
    from zipfile import ZipFile,ZIP_DEFLATED
    import xml.etree.ElementTree as ET
    ns="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with ZipFile(source)as incoming:
        workbook=ET.fromstring(incoming.read("xl/workbook.xml"));rels=ET.fromstring(incoming.read("xl/_rels/workbook.xml.rels"))
        relationships={r.attrib["Id"]:r.attrib["Target"].lstrip("/")for r in rels}
        sheets={node.attrib["name"]:relationships[node.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]for node in workbook.find(ns+"sheets")}
        by_part={}
        for key,value in edits.items():
            b=bindings[key];part=sheets[b["sheet"]]
            if not part.startswith("xl/"):part="xl/"+part
            by_part.setdefault(part,{})[b["cell"]]=value
        with ZipFile(destination,"x",ZIP_DEFLATED)as outgoing:
            for item in incoming.infolist():
                data=incoming.read(item.filename)
                if item.filename in by_part:
                    tree=ET.fromstring(data);pending=dict(by_part[item.filename])
                    for cell in tree.iter(ns+"c"):
                        address=cell.attrib.get("r")
                        if address not in pending:continue
                        value=pending.pop(address)
                        for child in list(cell):
                            if child.tag in(ns+"f",ns+"v",ns+"is"):cell.remove(child)
                        cell.attrib.pop("t",None)
                        if value is not None:ET.SubElement(cell,ns+"f").text=value[1:]
                    if pending:raise ValueError("A planned view edit addressed a missing physical cell")
                    data=ET.tostring(tree,encoding="utf-8",xml_declaration=True)
                outgoing.writestr(item,data)


def _exact_numeric_inputs(source,facts):
    """Write the approved finite-decimal facts verbatim, without binary noise."""
    from zipfile import ZipFile,ZIP_DEFLATED
    import xml.etree.ElementTree as ET
    ns="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    destination=source.with_name("exact_numeric_input_construction.xlsx")
    with ZipFile(source)as incoming:
        workbook=ET.fromstring(incoming.read("xl/workbook.xml"));rels=ET.fromstring(incoming.read("xl/_rels/workbook.xml.rels"))
        relationships={r.attrib["Id"]:r.attrib["Target"].lstrip("/")for r in rels}
        sheets={node.attrib["name"]:relationships[node.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]for node in workbook.find(ns+"sheets")}
        edits={}
        for fact in facts.values():
            if fact["value"].startswith("n/a"):continue
            part=sheets[fact["sheet"]];part=part if part.startswith("xl/")else"xl/"+part
            edits.setdefault(part,{})[fact["cell"]]=fact["value"]
        with ZipFile(destination,"x",ZIP_DEFLATED)as outgoing:
            for item in incoming.infolist():
                data=incoming.read(item.filename)
                if item.filename in edits:
                    tree=ET.fromstring(data);pending=dict(edits[item.filename])
                    for cell in tree.iter(ns+"c"):
                        if cell.attrib.get("r")not in pending:continue
                        value=pending.pop(cell.attrib["r"])
                        if cell.find(ns+"f")is not None:raise ValueError("Provided input unexpectedly contains a formula")
                        node=cell.find(ns+"v")
                        if node is None:raise ValueError("Provided input lost its native numeric node")
                        node.text=value
                    if pending:raise ValueError("Exact input patch addressed an absent native cell")
                    data=ET.tostring(tree,encoding="utf-8",xml_declaration=True)
                outgoing.writestr(item,data)
    destination.replace(source)


