"""Complete serialized-oracle comparison and uncalculated package census."""
from __future__ import annotations

from collections import Counter
from fractions import Fraction as F
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile
from . import schema as s


def _quant(value):
    value=F(value);absolute=abs(value)*100+F(1,2)
    n=absolute.numerator//absolute.denominator
    return ("-"if value<0 and n else"")+f"{n//100}.{n%100:02d}"


def compare(public, left, right):
    s.validate_spec(public)
    expected=dict(s.points(public))
    ids=[e["id"]for e in public["entities"]]
    members={"DIV_"+d.upper():[e["id"]for e in public["entities"]if e["division"]==d]for d in public["divisions"]}
    members["PORTFOLIO"]=ids
    quarter_keys={identity+"/"+period for identity in ids+list(members)for period in s.QUARTERS}
    units={e["id"]:(F({"GBP":1,"GBP_thousands":1000,"GBP_millions":1000000}[e["money_unit"]]),{"fraction":F(100),"percent_units":F(1),"basis_points":F(1,100)}[e["rate_unit"]])for e in public["entities"]}
    units.update({identity:(F(1),F(1))for identity in members})
    for result in (left,right):
        s.validate_result(public,result)
        if type(result["version"])is not int:raise ValueError("Result version must be an integer")
        checks=result["reconciliation_checks"]
        if set(checks)!={"passed","opening_balance_residuals","quarter_balance_residuals","cash_bridge_residuals","investment_bridge_residuals","retained_earnings_bridge_residuals","group_membership"}:raise ValueError("Incomplete reconciliation schema")
        if set(checks["opening_balance_residuals"])!=set(ids)or checks["group_membership"]!=members:raise ValueError("Incomplete opening or group membership proof")
        if any(set(checks[name])!=quarter_keys for name in("quarter_balance_residuals","cash_bridge_residuals","investment_bridge_residuals","retained_earnings_bridge_residuals")):raise ValueError("Incomplete quarterly bridge proof")
        for values in result["reconciliation_checks"].values():
            if isinstance(values,dict)and values and all(isinstance(v,str)for v in values.values()):
                if any(F(v)!=0 for v in values.values()):raise ValueError("Nonzero exact reconciliation residual")
        if result["reconciliation_checks"]["passed"]is not True:raise ValueError("Oracle did not reconcile")
        expected_cagr={key for key,kind in s.points(public)if key.endswith("/cagr_percent")and kind=="number"}
        if set(result["cagr_proofs"])!=expected_cagr:raise ValueError("CAGR proof inventory incomplete")
        for key in expected_cagr:
            proof=result["cagr_proofs"][key]
            ratio=F(proof["endpoint_ratio"]);unit=F(proof["percent_units_per_raw_unit"])
            low,high=F(proof["lower_raw"]),F(proof["upper_raw"])
            if low>high or unit<=0 or ratio<=0:raise ValueError("Invalid CAGR interval")
            lo=1+low*unit/100;hi=1+high*unit/100
            if not lo**proof["years"]<=ratio<=hi**proof["years"]:raise ValueError("CAGR interval does not contain the exact root")
            if _quant(low)!=_quant(high)or proof["rounded"]!=_quant(low)or result["typed_2dp_values"][key]["value"]!=_quant(low):raise ValueError("CAGR interval does not certify primary rounding")
            raw=result["raw_cell_exact_values"][key];economic=result["economic_exact_values"][key]
            if raw!={"kind":"cagr","endpoint_ratio":str(ratio),"years":proof["years"],"percent_units_per_raw_unit":str(unit)}or economic!={**raw,"percent_units_per_raw_unit":"1"}or unit!=units[key.split('/')[0]][1]:raise ValueError("CAGR proof is not bound to its economic/raw result")
        for key,kind in expected.items():
            if key in expected_cagr:continue
            raw=result["raw_cell_exact_values"][key];economic=result["economic_exact_values"][key];typed=result["typed_2dp_values"][key]
            if kind!="number":
                if raw!={"kind":kind,"value":typed["value"]}or economic!=raw:raise ValueError("Exact bool/text value differs from its primary result")
            else:
                if set(raw)!={"kind","value"}or set(economic)!={"kind","value"}or raw["kind"]!="rational"or economic["kind"]!="rational":raise ValueError("Numeric value lacks an exact rational")
                identity,period,field=key.split('/')
                money,rate=units[identity]
                unit=rate if field.endswith('_percent')else F(1)if field in('prior_year_multiple','prior_year_index')else money
                if F(economic['value'])/unit!=F(raw['value'])or _quant(raw['value'])!=typed['value']:raise ValueError("Exact unit/primary rounding proof failed")
    differences=[]
    for section in ("economic_exact_values","raw_cell_exact_values","typed_2dp_values"):
        for key in left[section]:
            if left[section][key]!=right[section][key]:differences.append({"section":section,"key":key,"A":left[section][key],"B":right[section][key]})
    if left["reconciliation_checks"]!=right["reconciliation_checks"]:differences.append({"section":"reconciliation_checks"})
    return {"kind":"independent_operating_reports_200_full_crosscheck","version":1,"specification_sha256":s.canonical_sha256(public),"points":len(dict(s.points(public))),"exact_maps_compared":2,"typed_points_compared":len(dict(s.points(public))),"CAGR_proofs_per_oracle":len(left["cagr_proofs"]),"differences":differences,"passed":not differences,"native_calculations":0,"source_or_difficulty_certified":False}


def census(public,directory):
    directory=Path(directory)
    binding=json.loads((directory/"private_bindings.json").read_text())
    plans=json.loads((directory/"view_plans.json").read_text())
    if binding["specification_sha256"]!=s.canonical_sha256(public):raise ValueError("Wrong specification binding")
    expected=dict(s.points(public));financial=binding["financial"]
    if set(financial)!=set(expected):raise ValueError("Financial bindings incomplete")
    physical=[(v["sheet"],v["cell"])for v in financial.values()]
    if len(set(physical))!=len(physical):raise ValueError("Duplicate report-cell binding")
    ns="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    def snapshot(path):
        result={};formulas=0;cached=0
        with ZipFile(path)as archive:
            workbook=ET.fromstring(archive.read("xl/workbook.xml"));rels=ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            relationships={v.attrib["Id"]:v.attrib["Target"].lstrip("/")for v in rels}
            for sheet in workbook.find(ns+"sheets"):
                part=relationships[sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]
                if not part.startswith("xl/"):part="xl/"+part
                tree=ET.fromstring(archive.read(part))
                for cell in tree.iter(ns+"c"):
                    f=cell.find(ns+"f");v=cell.find(ns+"v");text=cell.find(ns+"is")
                    if f is not None:
                        formulas+=1
                        if v is not None and v.text is not None:cached+=1
                    result[sheet.attrib["name"],cell.attrib["r"]]=(cell.attrib.get("t"),f.text if f is not None else None,v.text if v is not None else None,ET.tostring(text)if text is not None else None,cell.attrib.get("s"))
        return result,formulas,cached
    source,n,cache=snapshot(directory/"source_uncalculated.xlsx")
    fm,_,_=snapshot(directory/"financial_modeling_input.xlsx");dbg,_,_=snapshot(directory/"debugging_input.xlsx")
    if cache:raise ValueError("Source formulas contain seeded cached answers")
    context={(v["sheet"],v["cell"])for v in binding["provided_context"].values()}
    nonempty={key for key,item in source.items()if item[1]is not None or item[2]is not None or item[3]is not None}
    if set(physical)&context or set(physical)|context!=nonempty:raise ValueError("Provided policy/label/context binding census is incomplete")
    expected_formula=sum(kind!="text"for kind in expected.values())
    if n!=expected_formula:raise ValueError("Unexpected source formula inventory")
    fm_edits={(financial[key]["sheet"],financial[key]["cell"])for key in plans["FM_mask"]}
    dbg_edits={(v["sheet"],v["cell"])for v in plans["DBG_faults"].values()}
    for observed,allowed in ((fm,fm_edits),(dbg,dbg_edits)):
        if set(observed)!=set(source):raise ValueError("View changed the physical provided-cell inventory")
        changed={key for key in source if source[key]!=observed[key]}
        if changed!=allowed:raise ValueError("View changed cells outside its frozen edit plan")
    for key,kind in expected.items():
        cell=financial[key];item=source[cell["sheet"],cell["cell"]]
        if kind=="text"and(item[0]!="inlineStr"or item[3]is None):raise ValueError("Declared NA report is empty")
        if kind!="text"and item[1]is None:raise ValueError("Applicable report lacks native formula")
    # Every provided input, including all actual/forecast NA positions, is nonempty.
    for fact in binding["provided_facts"].values():
        item=source[fact["sheet"],fact["cell"]]
        if item[1]is not None or(item[2]is None and item[3]is None):raise ValueError("Provided fact is blank or calculated")
        if not fact["value"].startswith("n/a")and(item[2]is None or F(item[2])!=F(fact["value"])):raise ValueError("Provided numeric fact differs from the exact approved decimal input")
    family_counts=Counter(v["family"]for v in plans["DBG_faults"].values())
    return {"kind":"pure_operating_reports_200_package_census","version":1,"passed":True,"report_positions":len(expected),"provided_context_positions":len(context),"source_formulas":n,"formula_caches":cache,"FM_mask":len(fm_edits),"DBG_roots":len(dbg_edits),"fault_families":dict(family_counts),"source_and_views_provided_identity_preserved":True,"actual_D_unknown":True,"native_calls":0}
