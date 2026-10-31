"""Offline, evidence-only workbook/trajectory diagnosis. Never executes formulas.

Reports describe existing artifacts, not a new score or a financial certificate.
No model, network, office engine, subprocess, source edit, or automatic retry.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import posixpath
import re
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.formula.translate import Translator
from openpyxl.styles.numbers import BUILTIN_FORMATS, is_date_format
from openpyxl.utils.cell import coordinate_to_tuple, range_boundaries
from openpyxl.utils.datetime import CALENDAR_MAC_1904, CALENDAR_WINDOWS_1900, from_excel

ROOT=Path(__file__).resolve().parents[3]
KIND="offline_spreadsheet_case_failure_analysis"
VERSION=1
CAUSE_LABELS=("location","scope","period","unit","finance_reasoning","incomplete","protocol","scoring_ambiguity","infrastructure","cache","evaluator_formula","evaluator_font","external_answer_retrieval","unknown")
OFFICIAL_EVALUATOR_SHA256="5e31ba8f9cbdd8007eebfb441f9783cfaff280e90225b37ff61702863cb0f8b9"
ARTIFACT_FIELDS=("source","reference","output","instruction","trajectory","result","official_score","baseline_cache","inventory","official_evaluator","case_terminal","reviewed_findings","verified_tool_time")
S="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
EMPTY={"type":"empty","value":""}
MISSING_CACHE={"type":"unknown_cache","value":""}


def require(value,message):
    if not value:raise ValueError(message)


def _safe_path(path):
    p=Path(path).resolve()
    require(not any(x.casefold() in {"auth.json","config.toml",".env","credentials","credentials.json"} for x in p.parts) and p.suffix.casefold() not in {".pem",".key"},"Credential/configuration files are outside offline analysis")
    return p


def reference(path):
    p=_safe_path(path);b=p.read_bytes();return {"path":str(p),"sha256":hashlib.sha256(b).hexdigest(),"bytes":len(b)}


def checked(value):
    if not isinstance(value,dict):return _safe_path(value)
    require(set(value)=={"path","sha256","bytes"} and reference(value["path"])==value,"Bound evidence changed")
    return _safe_path(value["path"])


def read(value):
    def unique(rows):
        result={}
        for k,v in rows:require(k not in result,"Duplicate JSON key");result[k]=v
        return result
    return json.loads(checked(value).read_text(),object_pairs_hook=unique,parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))


def write_new(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("x") as stream:json.dump(value,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write("\n")
    return reference(p)


def recipes():
    paths=[Path(__file__),ROOT/"scripts/analyze_spreadsheet_failure.py",ROOT/"config/spreadsheet_failure_analysis_v1.schema.json",ROOT/"docs/spreadsheet_failure_analysis_prompt.md",ROOT/"tests/test_spreadsheet_failure_analysis.py"]
    return {str(p.relative_to(ROOT)):reference(p) for p in paths}


def _decimal(value):
    d=Decimal(str(value));require(d.is_finite(),"Nonfinite workbook number");return d


def _number(value):
    d=_decimal(value);return "0" if not d else format(d.normalize(),"f")


def _text(node):
    return "" if node is None else "".join(n.text or "" for n in node.iter() if n.tag.rsplit("}",1)[-1]=="t")


def _formula_key(text):
    try:
        result=[]
        for t in Tokenizer("="+text.removeprefix("=")).items:
            if t.type=="WSPACE":continue
            value=t.value
            if t.type=="FUNC":value=value.casefold()
            elif t.type=="OPERAND" and t.subtype=="RANGE":
                if "!" in value:
                    q,a=value.rsplit("!",1)
                    if q.startswith("'") and q.endswith("'"):q=q[1:-1].replace("''", "'")
                    value=q.casefold()+"!"+a.casefold()
                else:value=value.casefold()
            result.append([t.type,t.subtype,value])
        return result,None
    except Exception as e:return [["unparsed",type(e).__name__,text]],type(e).__name__


def _xml_key(node):
    """Canonical XML tree identity; independent of style/font index numbering."""
    if node is None:return None
    return [node.tag,sorted(node.attrib.items()),node.text or "",[_xml_key(c) for c in node]]


def workbook(path):
    """Read physical definitions and cached values only, including shared formulas."""
    path=checked(path);require(path.suffix.casefold() in {".xlsx",".xlsm",".xltx",".xltm"},"Unsupported workbook container")
    with ZipFile(path) as z:
        names=z.namelist();require(len(names)==len(set(names)),"Duplicate OOXML member")
        w=ET.fromstring(z.read("xl/workbook.xml"));props=w.find("{*}workbookPr");mac=props is not None and props.get("date1904","0") in {"1","true"}
        epoch=CALENDAR_MAC_1904 if mac else CALENDAR_WINDOWS_1900
        rels={r.get("Id"):r for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        strings=[_text(n) for n in ET.fromstring(z.read("xl/sharedStrings.xml"))] if "xl/sharedStrings.xml" in names else []
        formats=dict(BUILTIN_FORMATS);xfs=[];fonts=[]
        if "xl/styles.xml" in names:
            style=ET.fromstring(z.read("xl/styles.xml"))
            formats.update({int(n.get("numFmtId")):n.get("formatCode") for n in style.findall("{*}numFmts/{*}numFmt")});xfs=list(style.find("{*}cellXfs"));fonts=list(style.find("{*}fonts"))
        font_keys=[_xml_key(f) for f in fonts];color_keys=[_xml_key(f.find("{*}color")) for f in fonts]
        sheets=[];cells={};holds=[];formula_count=missing_cache=0
        for sheet in w.find("{*}sheets"):
            title=sheet.get("name");require(title not in cells,"Duplicate sheet")
            rel=rels[sheet.get("{"+R+"}id")];require(rel.get("TargetMode")!="External","External worksheet relationship")
            target=rel.get("Target");part=target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl",target))
            require(part in names and not part.startswith("../"),"Unresolved worksheet part")
            tree=ET.fromstring(z.read(part));physical=list(tree.findall("{*}sheetData/{*}row/{*}c"));masters={}
            for c in physical:
                f=c.find("{*}f")
                if f is not None and f.get("t")=="shared" and f.text:masters[f.get("si")]=(c.get("r"),f.text)
            sheets.append(title);cells[title]={}
            for c in physical:
                address=c.get("r");require(address not in cells[title],"Duplicate cell")
                f=c.find("{*}f");v=c.find("{*}v");raw=None if v is None else v.text or "";t=c.get("t","n");kind=f.get("t","normal") if f is not None else None;formula=None;formula_error=None
                if f is not None:
                    formula_count+=1;formula=f.text or ""
                    if kind=="shared" and not formula:
                        try:origin,master=masters[f.get("si")];formula=Translator("="+master,origin=origin).translate_formula(address).removeprefix("=")
                        except Exception as e:formula_error=type(e).__name__;holds.append({"sheet":title,"cell":address,"issue":"unresolved_shared_formula"})
                    elif kind not in {"normal","shared","array"}:holds.append({"sheet":title,"cell":address,"issue":"unhandled_formula_kind","formula_kind":kind})
                if t=="s" and raw not in {None,""}:value={"type":"string","value":strings[int(raw)]}
                elif t=="inlineStr":value={"type":"string","value":_text(c.find("{*}is"))}
                elif t=="str" and v is not None:value={"type":"string","value":raw}
                elif t=="e":value={"type":"error","value":raw or ""}
                elif t=="b":require(raw in {"0","1"},"Invalid Boolean");value={"type":"boolean","value":raw=="1"}
                elif t=="d":value={"type":"datetime","value":datetime.fromisoformat(raw.replace("Z","+00:00")).isoformat()}
                elif raw not in {None,""}:
                    style_index=int(c.get("s","0"));fmt=formats.get(int(xfs[style_index].get("numFmtId","0")),"") if xfs else ""
                    if is_date_format(fmt):
                        d=from_excel(float(raw),epoch);value={"type":"datetime" if isinstance(d,(datetime,date)) else "time" if isinstance(d,time) else "duration","value":d.isoformat() if hasattr(d,"isoformat") else str(d)}
                    else:value={"type":"number","value":_number(raw)}
                elif f is not None:value=dict(MISSING_CACHE);missing_cache+=1
                else:value=dict(EMPTY)
                if value=={"type":"string","value":""}:value=dict(EMPTY)
                key,error=_formula_key(formula) if formula is not None else (None,None)
                if formula is not None:definition={"type":"formula","formula":formula,"formula_key":key,"formula_kind":"array" if kind=="array" else "ordinary","array_range":f.get("ref") if kind=="array" else None,"parse_error":formula_error or error}
                else:definition=dict(value)
                style_index=int(c.get("s","0"));font_id=int(xfs[style_index].get("fontId","0")) if xfs else 0
                cells[title][address]={"definition":definition,"cached":value,"font_key":font_keys[font_id] if fonts else None,"font_color_key":color_keys[font_id] if fonts else None}
    return {"workbook":reference(path),"sheets":sheets,"cells":cells,"formula_count":formula_count,"missing_formula_caches":missing_cache,"holds":holds,"formulas_executed":False}


def _near(a,b):
    return abs(a-b)<=Decimal("1e-12")+Decimal("1e-12")*max(abs(a),abs(b))


def _definition_equal(a,b):
    if a["type"]!=b["type"]:return False
    if a["type"]=="number":return _near(_decimal(a["value"]),_decimal(b["value"]))
    if a["type"]=="formula":return all(a.get(k)==b.get(k) for k in ("formula_key","formula_kind","array_range","parse_error"))
    return a==b


def _value_equal(a,b,quantum):
    if "unknown_cache" in {a["type"],b["type"]}:return None
    if a["type"]!=b["type"]:return False
    if a["type"]=="number":
        x,y=(_decimal(v["value"]) for v in (a,b))
        return (x.quantize(Decimal(quantum),rounding=ROUND_HALF_UP)==y.quantize(Decimal(quantum),rounding=ROUND_HALF_UP)) if quantum else x==y
    return a==b


def _at(book,sheet,cell,field):return book["cells"].get(sheet,{}).get(cell,{}).get(field,EMPTY)


def _points(*books):return sorted({(s,a) for b in books for s,row in b["cells"].items() for a in row})


def definition_diff(a,b):
    changes=[];serialization=[]
    for sheet,cell in _points(a,b):
        x=_at(a,sheet,cell,"definition");y=_at(b,sheet,cell,"definition")
        row={"sheet":sheet,"cell":cell,"before":x,"after":y}
        if not _definition_equal(x,y):changes.append(row)
        elif x["type"]==y["type"]=="number" and x!=y:serialization.append(row)
    return {"changes":changes,"near_numeric_serialization_only":serialization}


def font_diff(a,b,example_limit=100):
    changes=[];count=color_count=0;by_sheet=Counter();digest=hashlib.sha256()
    for sheet,cell in _points(a,b):
        x=a["cells"].get(sheet,{}).get(cell,{});y=b["cells"].get(sheet,{}).get(cell,{})
        if x.get("font_key")!=y.get("font_key"):
            row={"sheet":sheet,"cell":cell,"font_tree_changed":True,"raw_color_tree_changed":x.get("font_color_key")!=y.get("font_color_key"),"before_color":x.get("font_color_key"),"after_color":y.get("font_color_key")}
            count+=1;color_count+=row["raw_color_tree_changed"];by_sheet[sheet]+=1;digest.update((json.dumps(row,sort_keys=True)+"\n").encode())
            if len(changes)<example_limit:changes.append(row)
    return {"changes":changes,"total_font_tree_changes":count,"per_sheet_font_tree_changes":dict(by_sheet),"raw_color_tree_changes":color_count,"example_limit":example_limit,"examples_truncated":count>len(changes),"all_ordered_change_rows_sha256":digest.hexdigest(),"complete_cells_reconstructible_from_bound_workbooks":True,"official_theme_color_equivalence_not_recomputed":True,"does_not_establish_financial_error":True}


def answer_regions(value):
    """Parse rectangles without splitting commas inside quoted sheet names."""
    if not value:return []
    pieces=[];start=0;quoted=False
    for i,c in enumerate(value):
        if c=="'":quoted=not quoted
        elif c=="," and not quoted:pieces.append(value[start:i]);start=i+1
    require(not quoted,"Unclosed sheet quote");pieces.append(value[start:]);result=[]
    for piece in pieces:
        sheet,area=piece.strip().rsplit("!",1)
        if sheet.startswith("'") and sheet.endswith("'"):sheet=sheet[1:-1].replace("''", "'")
        bounds=range_boundaries(area.replace("$",""));require(all(isinstance(n,int) and n>0 for n in bounds),"Finite answer rectangle required")
        result.append({"sheet":sheet,"range":area,"bounds":list(bounds)})
    return result


def _in_regions(sheet,cell,regions):
    row,col=coordinate_to_tuple(cell)
    return any(r["sheet"].casefold()==sheet.casefold() and r["bounds"][0]<=col<=r["bounds"][2] and r["bounds"][1]<=row<=r["bounds"][3] for r in regions)


def evaluator_contract(manifest):
    mode=manifest["mode"];official=manifest.get("official_evaluator")
    if not official:return {"group":mode+"/unspecified_evaluator","source":"not_bound","official_rules_known":False}
    require(reference(checked(official))["sha256"]==OFFICIAL_EVALUATOR_SHA256,"Unsupported official evaluator revision; diagnose as unknown, do not assume grading rules")
    category=manifest.get("category","");path=manifest.get("official_input_path","")
    color="Debugging" in category and "Color" in path;formula="Debugging" in category and "Embedded" in path
    subtype="embedded_formula" if formula else "color_font" if color else "ordinary"
    return {"group":mode+"/"+subtype,"subtype":subtype,"source":official,"official_rules_known":True,"with_formula":formula,"with_font_color":color,"numeric_rule":"Official numeric comparator uses relative tolerance 0.01 (absolute tolerance if either number is zero); this analysis does not recompute it.","formula_rule":"Embedded: remove $, uppercase, and normalize leading =+; no algebraic equivalence. Error cells in other modes can fall back to formula comparison.","font_rule":"Color: cached-value comparison AND official theme-aware font-color equivalence; raw font-tree diagnostics below are not that score.","score_layer_is_not_financial_error_attribution":True}


def _additive_atoms(formula):
    f=formula.removeprefix("=").replace("$","").replace(" ","").upper()
    terms=f[4:-1].split(",") if f.startswith("SUM(") and f.endswith(")") else f.split("+")
    result=[]
    for term in terms:
        if re.fullmatch(r"[A-Z]+[1-9][0-9]*",term):result.append(term)
        elif re.fullmatch(r"[A-Z]+[1-9][0-9]*:[A-Z]+[1-9][0-9]*",term):
            x1,y1,x2,y2=range_boundaries(term);require((x2-x1+1)*(y2-y1+1)<=1000,"Large additive equivalence range")
            from openpyxl.utils.cell import get_column_letter
            result.extend(get_column_letter(x)+str(y) for y in range(y1,y2+1) for x in range(x1,x2+1))
        else:return None
    return sorted(result)


def numeric_additive_equivalence(reference_book,output_book,sheet,cell):
    a=_at(reference_book,sheet,cell,"definition");b=_at(output_book,sheet,cell,"definition")
    if a["type"]!=b["type"] or a["type"]!="formula":return None
    x=_additive_atoms(a["formula"]);y=_additive_atoms(b["formula"])
    if not x or x!=y:return None
    if not all(_at(book,sheet,address,"cached")["type"]=="number" for book in (reference_book,output_book) for address in x):return None
    return {"proof_kind":"same_additive_numeric_operands","operands":x,"current_numeric_operand_types_checked":True,"does_not_prove_upstream_values_correct":True}


def trajectory_summary(value):
    x=read(value);steps=x.get("steps",[]);tools=[];sources=Counter();network=[];answer_requests=[]
    for step in steps:
        sources[step.get("source","unknown")]+=1
        for call in step.get("tool_calls",[]):
            arguments=call.get("arguments",{});text=json.dumps(arguments,ensure_ascii=False);name=str(call.get("function_name","unknown"))
            markers=[m for m in ("curl ","wget ","requests.get(","requests.post(","urlopen(","urllib.request", "httpx.get(","httpx.post(","socket.connect(","git clone ") if m in text]
            if re.search(r"(?:web|search|browse|fetch|download)",name,re.I):markers.append("network-capable tool name")
            if markers:network.append({"step_id":step.get("step_id"),"markers":markers,"interpretation":"request-like syntax; inspect exact bound trace before claiming retrieval"})
            answer_target=bool(markers and re.search(r"(?i)golden|(?:ground.?truth)|spreadsheetbench|huggingface|(?:reference|answer)[-_ ]?(?:workbook|xlsx|file)",text))
            if answer_target:answer_requests.append({"step_id":step.get("step_id"),"status":"request_syntax_targets_possible_benchmark_or_answer_source","successful_download_and_use_not_established":True})
            tools.append({"step_id":step.get("step_id"),"timestamp":step.get("timestamp"),"function_name":name,"arguments_sha256":hashlib.sha256(json.dumps(arguments,sort_keys=True).encode()).hexdigest(),"network_request_syntax_markers":markers,"possible_external_answer_target_syntax":answer_target,"recalculation_command_syntax_present":bool(re.search(r"\brecalculate\s+",text))})
    return {"trajectory":reference(checked(value)),"step_counts":dict(sources),"recorded_step_ids":[s.get("step_id") for s in steps],"recorded_tool_calls":tools,"request_syntax_observations":network,"possible_external_answer_requests":answer_requests,"observed_external_answer_retrieval":"not_established_by_syntax_scan","trace_completeness":"unknown; only this bound trace was scanned","no_request_observed_is_not_proof_of_no_retrieval_or_pretrained_familiarity":True,"raw_commands_arguments_messages_credentials_not_copied":True}


def _score(value):
    if not isinstance(value,dict):return None
    names=("accuracy","modification_accuracy","regression_accuracy","interaction_turns","id")
    return {k:value[k] for k in names if k in value and isinstance(value[k],(int,float,str))} or None


def terminal_layers(manifest):
    """Whitelist fields; never copy Harbor configuration or exception messages."""
    result={"native_terminal":None,"official_raw_scores":None,"project_exact_diagnostic":None,"tool_time":{"status":"unknown","wall_or_model_time_not_substituted":True},"automatic_financial_cause_from_score":False}
    if manifest.get("result"):
        raw=read(manifest["result"]);exception=raw.get("exception_info");etype=exception.get("exception_type") if isinstance(exception,dict) else None
        rewards=(raw.get("verifier_result") or {}).get("rewards",{})
        result["native_terminal"]={"finished_at":raw.get("finished_at"),"exception_type":etype if isinstance(etype,str) and re.fullmatch(r"[A-Za-z0-9_.]+",etype) else "present_redacted" if exception else None,"reward":rewards.get("reward") if isinstance(rewards,dict) else None,"score_is_not_financial_diagnosis":True}
    for field in ("official_score","case_terminal"):
        if not manifest.get(field):continue
        raw=read(manifest[field]);candidate=_score(raw)
        if isinstance(raw.get("official_primary"),dict):candidate=_score(raw["official_primary"].get("result"))
        if isinstance(raw.get("official_scores"),dict):candidate=_score(raw["official_scores"].get("original_official")) or candidate
        if candidate:result["official_raw_scores"]=candidate
        if field=="case_terminal":
            result["protocol"]={k:raw[k] for k in ("disposition","protocol_state","protocol_effective_accuracy","native_run_complete","infrastructure_or_timing_unknown_is_not_model_zero","official_raw_accuracy") if k in raw}
            exact=raw.get("project_exact_diagnostic",{})
            result["project_exact_diagnostic"]={"reward":exact.get("reward") if isinstance(exact,dict) else exact,"separate_from_official":True} if exact is not None else None
            timing=exact.get("tool_time") if isinstance(exact,dict) else None
            if isinstance(timing,dict):result["tool_time"]={"status":"bound_original_diagnostic","evidence":manifest[field],"fields":{k:v for k,v in timing.items() if isinstance(v,(bool,int,float)) or v is None},"interpretation":"These fields retain their original clock contract; no wall/model-time fallback or new eligibility decision."}
    if manifest.get("reported_official_scores") and result["official_raw_scores"] is None:result["official_raw_scores"]=_score(manifest["reported_official_scores"])
    if manifest.get("verified_tool_time"):result["tool_time"]={"status":"bound_caller_supplied_evidence","evidence":manifest["verified_tool_time"],"interpretation":"Inspect the bound clock contract; no wall/model-time fallback."}
    return result


def freeze_manifest(manifest):
    result=dict(manifest)
    require(result.get("kind")=="spreadsheet_failure_analysis_case" and result.get("version")==1,"Explicit offline case manifest required")
    require(isinstance(result.get("case_id"),str) and result["case_id"] and result.get("mode") in {"financial_modeling","debugging","FM","DBG"},"Case identity and mode required")
    for field in ARTIFACT_FIELDS:
        if result.get(field):result[field]=reference(checked(result[field]))
    require(result.get("source") and result.get("reference"),"Original input and reference required")
    quantum=result.get("analysis_numeric_quantum")
    if quantum is not None:require(_decimal(quantum)>0 and -12<=_decimal(quantum).as_tuple().exponent<=6,"Bounded positive decimal analysis quantum required")
    return result


def _cache_comparison(baseline,goal,output,quantum):
    missing=[];extra=[];wrong=[];unknown=[];expected=[];actual=[];raw_only=[]
    for sheet,cell in _points(baseline,goal,output):
        a=_at(baseline,sheet,cell,"cached");g=_at(goal,sheet,cell,"cached");o=_at(output,sheet,cell,"cached")
        eg=_value_equal(a,g,quantum);ao=_value_equal(a,o,quantum);go=_value_equal(g,o,quantum)
        if None in (eg,ao,go):unknown.append({"sheet":sheet,"cell":cell,"baseline":a,"reference":g,"output":o});continue
        row={"sheet":sheet,"cell":cell,"baseline":a,"reference":g,"output":o}
        if not eg:expected.append(row)
        if not ao:actual.append(row)
        if not eg and ao:missing.append(row)
        if eg and not ao:extra.append(row)
        if not eg and not go:wrong.append(row)
        if g["type"]==o["type"]=="number" and _decimal(g["value"])!=_decimal(o["value"]) and go:raw_only.append(row)
    return {"analysis_numeric_quantum":quantum,"official_score_recomputed":False,"expected_changes":expected,"actual_changes":actual,"missing":missing,"extra":extra,"wrong_required":wrong,"unknown_cache_points":unknown,"raw_only_reference_output_differences":raw_only}


def _instruction(manifest):
    if "instruction" in manifest:return checked(manifest["instruction"]).read_text()
    return manifest.get("public_instruction","")


def analyze(manifest):
    """Return one immutable evidence report; incomplete artifacts stay unknown."""
    manifest=freeze_manifest(manifest)
    source=workbook(manifest["source"]);goal=workbook(manifest["reference"]);instruction=_instruction(manifest);intended=definition_diff(source,goal)
    evidence={k:manifest[k] for k in ARTIFACT_FIELDS if manifest.get(k)}
    for value in evidence.values():checked(value)
    report={"kind":KIND,"version":VERSION,"case_id":manifest["case_id"],"mode":manifest["mode"],"evidence":evidence,"analysis_recipe":recipes(),"public_instruction":instruction,"evaluator_contract":evaluator_contract(manifest),"terminal_layers":terminal_layers(manifest),"intended_reference_definition_changes":intended,"font_diagnostics":{"input_reference":font_diff(source,goal)},"source_cache_status":{"physical_formulas":source["formula_count"],"missing_formula_caches":source["missing_formula_caches"]},"holds":source["holds"]+goal["holds"],"observed_business_error_established":False,"automatic_cause_attribution":False,"official_score_recomputed":False,"new_model_LO_solver_network_calls":0}
    try:regions=answer_regions(manifest.get("answer_position"));report["official_answer_regions"]={"regions":regions,"parsed":True,"diagnostic_scope_only_not_official_comparison":True}
    except (ValueError,TypeError) as e:regions=[];report["official_answer_regions"]={"parsed":False,"exception_type":type(e).__name__};report["holds"].append({"issue":"answer_regions_unparsed"})
    causes=[{"label":label,"status":"unknown","business_error_established":False,"evidence_points":[],"required_check":"Review the exact public policy, actual trace and affected cells; score alone is insufficient."} for label in CAUSE_LABELS]
    if manifest.get("trajectory"):report["trajectory"]=trajectory_summary(manifest["trajectory"])
    if manifest.get("reviewed_findings"):report["reviewed_findings"]=read(manifest["reviewed_findings"]);report["reviewed_findings_are_caller_assessments_not_automated_proofs"]=True
    if not manifest.get("output"):
        causes[-1]["required_check"]="No submitted output is bound; distinguish active run, infrastructure failure and missing artifact using actual terminal evidence."
        report.update(cause_findings=causes,completion="no_submitted_output_bound",counterfactuals=[]);return report
    output=workbook(manifest["output"]);report["holds"]+=output["holds"];actual=definition_diff(source,output);report["actual_definition_changes"]=actual
    report["font_diagnostics"].update(input_output=font_diff(source,output),reference_output=font_diff(goal,output))
    original_sheets=set(source["sheets"]);roots={(r["sheet"],r["cell"]) for r in intended["changes"]};changed={(r["sheet"],r["cell"]) for r in actual["changes"]};root_status=[]
    for sheet,cell in sorted(roots):
        g=_at(goal,sheet,cell,"definition");o=_at(output,sheet,cell,"definition");a=_at(source,sheet,cell,"definition")
        proof=numeric_additive_equivalence(goal,output,sheet,cell)
        root_status.append({"sheet":sheet,"cell":cell,"reference_definition":g,"output_definition":o,"exact_formula_text_match":g.get("formula")==o.get("formula") if g["type"]==o["type"]=="formula" else None,"exact_normalized_definition_match":_definition_equal(g,o),"still_original_definition":_definition_equal(a,o),"conditional_additive_equivalence":proof,"reference_output_cache_equal":_value_equal(_at(goal,sheet,cell,"cached"),_at(output,sheet,cell,"cached"),manifest.get("analysis_numeric_quantum"))})
    report["intended_root_output_status"]=root_status
    report["structure"]={"input_sheets":source["sheets"],"reference_sheets":goal["sheets"],"output_sheets":output["sheets"],"added_sheets":sorted(set(output["sheets"])-original_sheets),"missing_sheets":sorted(original_sheets-set(output["sheets"]))}
    report["summary"]={"intended_definition_changes":len(roots),"near_numeric_serialization_only_input_reference":len(intended["near_numeric_serialization_only"]),"actual_existing_sheet_definition_changes":sum(r["sheet"] in original_sheets for r in actual["changes"]),"actual_existing_sheet_formula_definition_changes":sum(r["sheet"] in original_sheets and "formula" in {r["before"]["type"],r["after"]["type"]} for r in actual["changes"]),"extra_existing_definition_changes":len({p for p in changed-roots if p[0] in original_sheets}),"intended_roots_still_original":sum(r["still_original_definition"] for r in root_status),"intended_roots_exact_or_conditional_additive_match":sum(r["exact_normalized_definition_match"] or r["conditional_additive_equivalence"] is not None for r in root_status)}
    baseline=source
    if manifest.get("baseline_cache"):
        baseline=workbook(manifest["baseline_cache"]);difference=definition_diff(source,baseline)
        if difference["changes"] or source["sheets"]!=baseline["sheets"]:
            report["holds"].append({"issue":"baseline_cached_workbook_definitions_differ","count":len(difference["changes"])});baseline=source
    report["cached_value_diagnostics"]=_cache_comparison(baseline,goal,output,manifest.get("analysis_numeric_quantum"))
    report["official_answer_scope_diagnostic_counts"]={name:sum(_in_regions(r["sheet"],r["cell"],regions) for r in rows) for name,rows in report["cached_value_diagnostics"].items() if isinstance(rows,list)} if regions else {"status":"not_available"}
    for finding in causes:
        if finding["label"]=="incomplete" and report["summary"]["intended_roots_still_original"]:
            finding.update(status="observed_reference_edit_omissions",evidence_points=[{"sheet":r["sheet"],"cell":r["cell"]} for r in root_status if r["still_original_definition"]],required_check="Check that omitted outputs were publicly requested and financially identifiable before treating incompleteness as model error.")
        elif finding["label"]=="scope" and report["summary"]["extra_existing_definition_changes"]:
            finding.update(status="observed_edits_beyond_reference_roots",required_check="Read public scope; an open audit can legitimately require extra work. Extra edits alone are not financial error.")
        elif finding["label"]=="protocol" and (report["structure"]["added_sheets"] or report["structure"]["missing_sheets"]):
            finding.update(status="observed_sheet_structure_difference",required_check="Distinguish the actual evaluator rule from economic correctness; check scores on original sheets separately.")
        elif finding["label"]=="scoring_ambiguity" and re.search(r"(?i)audit.*thorough|any other issues|best practice",instruction) and report["summary"]["extra_existing_definition_changes"]:
            finding.update(status="supported_scope_policy_ambiguity_hypothesis",required_check="Identify actual period/sign/base/funding policy witnesses and defensible alternative conventions. No automatic overrepair finding.")
        elif finding["label"]=="cache" and report["cached_value_diagnostics"]["unknown_cache_points"]:
            finding.update(status="observed_unavailable_cached_values",required_check="Keep unavailable values unknown. Existing independently bound recalculated artifacts may be analyzed separately; do not recalculate or infer a model failure.")
        elif finding["label"]=="evaluator_formula" and report["evaluator_contract"].get("with_formula"):
            finding.update(status="formula_grading_mode_applies",required_check="Separate exact official formula normalization from arithmetic equivalence and business correctness. No official score is recomputed here.")
        elif finding["label"]=="evaluator_font" and report["evaluator_contract"].get("with_font_color"):
            finding.update(status="font_color_grading_mode_applies",required_check="Use the actual official font-aware score; raw XML/font differences are not a numerical or business reasoning failure.")
        elif finding["label"]=="external_answer_retrieval" and report.get("trajectory",{}).get("possible_external_answer_requests"):
            finding.update(status="request_syntax_requires_actual_retrieval_review",evidence_points=report["trajectory"]["possible_external_answer_requests"],required_check="Inspect actual tool output and subsequent use. Search/request syntax alone does not prove successful original-gold retrieval, copying, or contamination.")
    report["cause_findings"]=causes
    report["counterfactuals"]=[{"id":"retain_root_repairs_restore_other_definitions","status":"not_executed","check":"Keep submitted repairs at intended roots and restore other source definitions; compare actual official score and independent business invariants separately. No hypothetical score is asserted."},{"id":"scope_policy_clarification","status":"not_executed","check":"Would an explicit realistic scope/sign/base/timing/funding statement select one interpretation without revealing private locations or formulas? Ambiguity is not a hardness mechanism."},{"id":"cache_and_structure_layer_separation","status":"offline_diagnostics_only","check":"Separate raw caches, known normalized baseline, exact/quantized numeric differences, sheet structure and actual evaluator score. Missing caches are unknown, never a model failure."}]
    report["transfer_requirements"]={"observed_trace_and_cell_witness_required":True,"independent_public_policy_witness_required_for_finance_error":True,"augmentation_fields":["source_case_and_evidence_points","observed_shortcut_or_failure","dimension_to_transfer","coupling_or_amplification_hypothesis","financial_policy_invariants","public_scope_and_units","independent_expected_values_and_complete_D","counterfactual_control","unknowns"],"do_not_amplify":["ambiguous instructions","unknown caches","infrastructure failures","evaluator-only formatting quirks"]}
    report["completion"]="offline_evidence_extracted";return report


def case_from_inventory(inventory,case_key,**artifacts):
    data=read(inventory);case=next((c for c in data["cases"] if c["case_key"]==case_key or c["task_id"]==case_key),None)
    require(case is not None,"Case not found in frozen inventory")
    result={"kind":"spreadsheet_failure_analysis_case","version":1,"case_id":case["case_key"],"task_id":case["task_id"],"mode":case["mode"],"category":case["category"],"source":case["input"],"reference":case["goal"],"public_instruction":case["official_record"]["instruction"],"answer_position":case["official_record"].get("answer_position"),"official_input_path":case["official_record"]["spreadsheet_path"],"inventory":reference(checked(inventory)),"official_evaluator":data.get("official_evaluator")}
    previous=case.get("existing_attempt") or {}
    if previous.get("official_scores"):result["reported_official_scores"]=previous["official_scores"]
    for k,v in artifacts.items():
        if v is not None:result[k]=reference(checked(v)) if k in ARTIFACT_FIELDS else v
    return result


def save_analysis(manifest,output):
    manifest=freeze_manifest(manifest);recipe=recipes();identity=hashlib.sha256(json.dumps({"manifest":manifest,"recipe":recipe},sort_keys=True).encode()).hexdigest()
    directory=Path(output)/re.sub(r"[^A-Za-z0-9_.-]","_",manifest["case_id"])/identity
    if (directory/"receipt.json").exists():
        receipt=read(directory/"receipt.json");checked(receipt["report"]);checked(receipt["case_manifest"]);require(receipt["analysis_identity"]==identity,"Analysis identity changed");return reference(directory/"receipt.json")
    report=analyze(manifest)
    for field in ARTIFACT_FIELDS:
        if manifest.get(field):checked(manifest[field])
    require(recipe==report["analysis_recipe"],"Analysis recipe changed")
    directory.parent.mkdir(parents=True,exist_ok=True);directory.mkdir();bound=write_new(directory/"case_manifest.json",manifest);result=write_new(directory/"report.json",report)
    return write_new(directory/"receipt.json",{"kind":"completed_offline_spreadsheet_failure_analysis","version":1,"analysis_identity":identity,"case_manifest":bound,"report":result,"new_model_LO_solver_network_calls":0,"source_and_result_files_unchanged":True,"diagnostic_report_is_not_a_new_score":True})


def _task_name(raw):
    value=raw.get("task_name") or raw.get("task_id")
    if not isinstance(value,str):return None
    return value.removeprefix("sheetsfactory/")


def _trial_manifest(inventory,task_id,result,**extra):
    trial=result.parent;artifact=trial/"artifacts/app/output.xlsx";trajectory=trial/"agent/trajectory.json"
    return case_from_inventory(inventory,task_id,result=result,output=artifact if artifact.is_file() else None,trajectory=trajectory if trajectory.is_file() else None,**extra)


def scan_completed(inventory,evaluation,output):
    """Append reports for terminal cases in a cohort or one evaluation directory.

    This is one snapshot, not a daemon. It never launches, changes, or resumes a run.
    Terminal case reports supersede preliminary native-trial reports in this scan.
    Earlier scan receipts remain unchanged and reference their own exact evidence.
    """
    data=read(inventory);by_task={c["task_id"]:c for c in data["cases"]};reports=[];skipped=[];errors=[];done=set();root=Path(evaluation)
    def retain(manifest):
        receipt=save_analysis(manifest,output);report=read(read(receipt)["report"])
        reports.append({"case_id":manifest["case_id"],"task_id":manifest.get("task_id"),"group":report["evaluator_contract"]["group"],"evidence_stage":manifest.get("evidence_stage"),"receipt":receipt,"official_raw_scores":report["terminal_layers"]["official_raw_scores"],"output_bound":bool(manifest.get("output"))})
    for terminal in sorted(root.glob("cases/*/terminal.json")):
        task_id=terminal.parent.name
        try:
            raw=read(terminal);require(raw.get("task_id")==task_id and task_id in by_task,"Terminal identity not in inventory")
            trials=sorted(terminal.parent.glob("evaluation/harbor_jobs/*/*/result.json"))
            require(len(trials)<=1,"Multiple native trials require explicit manual attribution; do not silently choose")
            if trials:manifest=_trial_manifest(inventory,task_id,trials[0],case_terminal=terminal,evidence_stage="official_case_terminal")
            else:
                previous=by_task[task_id].get("existing_attempt") or {};result=previous.get("result")
                manifest=_trial_manifest(inventory,task_id,checked(result),case_terminal=terminal,evidence_stage="retained_original_case_terminal") if result else case_from_inventory(inventory,task_id,case_terminal=terminal,evidence_stage="case_terminal_without_native_trial")
            retain(manifest);done.add(task_id)
        except Exception as e:errors.append({"task_id":task_id,"artifact":str(terminal.resolve()),"exception_type":type(e).__name__,"status":"analysis_unknown_not_model_failure"})
    results=sorted(set(root.glob("harbor_jobs/*/*/result.json"))|set(root.glob("cases/*/evaluation/harbor_jobs/*/*/result.json")))
    for result in results:
        task_id=None
        try:
            raw=read(result);task_id=_task_name(raw)
            if task_id in done:continue
            if task_id not in by_task:skipped.append({"artifact":str(result.resolve()),"reason":"not_an_inventory_trial"});continue
            if not raw.get("finished_at"):
                skipped.append({"task_id":task_id,"reason":"trial_not_terminal"});continue
            retain(_trial_manifest(inventory,task_id,result,evidence_stage="native_trial_terminal_official_score_may_be_pending"))
        except Exception as e:errors.append({"task_id":task_id,"artifact":str(result.resolve()),"exception_type":type(e).__name__,"status":"analysis_unknown_not_model_failure"})
    groups={}
    for row in reports:
        g=groups.setdefault(row["group"],{"reports":0,"official_score_known":0,"official_raw_zero":0,"official_raw_one":0,"no_output_bound":0,"financial_error_count":"not_automatically_attributed"});g["reports"]+=1
        score=row["official_raw_scores"] or {};accuracy=score.get("accuracy");g["official_score_known"]+=accuracy is not None;g["official_raw_zero"]+=accuracy==0;g["official_raw_one"]+=accuracy==1;g["no_output_bound"]+=not row["output_bound"]
    return write_new(Path(output)/("scan_"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")+"_"+uuid4().hex[:6]+".json"),{"kind":"incremental_offline_spreadsheet_failure_analysis_scan","version":1,"inventory":reference(checked(inventory)),"evaluation_directory":str(root.resolve()),"reports":reports,"groups":groups,"skipped":skipped,"analysis_errors":errors,"inventory_cases":len(data["cases"]),"unreported_cases_not_treated_as_failures":len(data["cases"])-len({r["case_id"] for r in reports}),"cohort_need_not_be_complete":True,"new_model_LO_solver_network_calls":0})
