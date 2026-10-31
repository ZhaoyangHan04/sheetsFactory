"""Scoped heterogeneous FM/DBG task construction; no calculation or admission."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from . import heterogeneous_native_merge as merge

ROOT = Path(__file__).resolve().parents[3]
KIND = "prepared_heterogeneous_review_task_pair"
VIEW_KIND = "prepared_heterogeneous_review_task_view"
MATERIAL_KIND = "materialized_unverified_heterogeneous_review_task_view"
VERSION = 1
HELPER_SHA256 = "8974d289ead7f50d74de932aa901e7e15c7c32cb5dafddc83e3b20f64b634d6f"
MODES = {"financial_modeling": "FM", "debugging": "DBG"}
_HELPER = None


def helper():
    global _HELPER
    path = ROOT / "scripts/validate_heterogeneous_native_review_pack.py"
    merge.require(merge.file_ref(path)["sha256"] == HELPER_SHA256, "Frozen native snapshot/resource helper changed")
    if _HELPER is None:
        spec = importlib.util.spec_from_file_location("_heterogeneous_review_frozen_engineering_helper", path)
        _HELPER = importlib.util.module_from_spec(spec);spec.loader.exec_module(_HELPER)
    return _HELPER


def read(value):
    return helper().read(value)


def ref(path):
    return helper().reference(path)


def write(path, value):
    return helper().write(path, value)


def checked(value):
    return helper().checked(value)


def recipes():
    paths = [Path(__file__), ROOT/"scripts/prepare_heterogeneous_review_task_pair.py", ROOT/"scripts/validate_heterogeneous_review_task_pair.py", ROOT/"tests/test_heterogeneous_review_tasks.py", ROOT/"config/heterogeneous_review_tasks_v1.json"]
    return {str(p.relative_to(ROOT)): ref(p) for p in paths} | helper().recipes()


def all_refs(value):
    if isinstance(value, dict):
        if set(value)=={"path","sha256","bytes"}:
            yield value
        else:
            for v in value.values():yield from all_refs(v)
    elif isinstance(value,list):
        for v in value:yield from all_refs(v)


def _parts(path):
    with ZipFile(path) as z:
        names=z.namelist();merge.require(len(names)==len(set(names)),"Duplicate ZIP member")
        return {n:z.read(n) for n in names}


def _sheet_parts(parts):
    w=merge._xml(parts["xl/workbook.xml"])
    rels={n.getAttribute("Id"):n for n in merge._elements(merge._xml(parts["xl/_rels/workbook.xml.rels"]).documentElement)}
    return {n.getAttribute("name"):merge._resolve("xl/workbook.xml",rels[n.getAttributeNS(merge.R,"id")].getAttribute("Target")) for n in merge._children(merge._one(w.documentElement,"sheets"),"sheet")}


def _edited_parts(parts, edits):
    mapping=_sheet_parts(parts);grouped={};seen=set()
    for edit in edits:
        point=(edit["sheet"],edit["cell"]);merge.require(point not in seen,"Duplicate declared edit");seen.add(point)
        merge.require(edit["sheet"] in mapping,"Unknown surgery sheet")
        grouped.setdefault(mapping[edit["sheet"]],[]).append(edit)
    changed={};audits=[]
    for part, selected in grouped.items():
        doc=merge._xml(parts[part]);data=merge._one(doc.documentElement,"sheetData")
        def element(name):
            prefix=doc.documentElement.prefix
            return doc.createElementNS(merge.S,(prefix+":" if prefix else "")+name)
        before={n.getAttribute("r"):merge._semantic(n) for n in merge._all(doc) if n.localName=="c" and n.namespaceURI==merge.S}
        cells={n.getAttribute("r"):n for n in merge._all(doc) if n.localName=="c" and n.namespaceURI==merge.S}
        allowed={e["cell"] for e in selected}
        for edit in selected:
            address=edit["cell"];cell=cells.get(address)
            if cell is None:
                from openpyxl.utils.cell import coordinate_to_tuple
                row_number,column=coordinate_to_tuple(address);rows=merge._children(data,"row")
                row=next((r for r in rows if int(r.getAttribute("r"))==row_number),None)
                if row is None:
                    row=element("row");row.setAttribute("r",str(row_number))
                    following=next((r for r in rows if int(r.getAttribute("r"))>row_number),None)
                    data.insertBefore(row,following) if following else data.appendChild(row)
                cell=element("c");cell.setAttribute("r",address)
                following=next((c for c in merge._children(row,"c") if coordinate_to_tuple(c.getAttribute("r"))[1]>column),None)
                row.insertBefore(cell,following) if following else row.appendChild(cell);cells[address]=cell
            for child in list(cell.childNodes):
                if child.nodeType==child.ELEMENT_NODE and child.localName in {"f","v","is"}:cell.removeChild(child)
            action=edit["action"]
            if action=="clear":cell.setAttribute("t","n")
            elif action=="formula":
                cell.setAttribute("t","n");f=element("f");merge._set_text(f,edit["value"].removeprefix("="));cell.appendChild(f)
            elif action=="text":
                cell.setAttribute("t","inlineStr");inline=element("is");t=element("t");merge._set_text(t,edit["value"]);inline.appendChild(t);cell.appendChild(inline)
            else:raise ValueError("Unknown OOXML cell action")
        after={n.getAttribute("r"):merge._semantic(n) for n in merge._all(doc) if n.localName=="c" and n.namespaceURI==merge.S}
        actual={a for a in set(before)|set(after) if before.get(a)!=after.get(a)}
        merge.require(actual<=allowed,"Undeclared cell mutation")
        changed[part]=merge._bytes(doc)
        audits.append({"part":part,"declared_cells":sorted(allowed),"actually_changed_cells":sorted(actual),"all_other_cell_subtrees_identical":True})
    return parts | changed, audits


def surgery(source, destination, edits):
    """Change declared cells only; retain every unrelated cell and ZIP part."""
    parts=_parts(source);expected,audits=_edited_parts(parts,edits)
    changed={n for n in parts if parts[n]!=expected[n]}
    output=Path(destination);output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("xb") as stream:
        with ZipFile(stream,"w",ZIP_DEFLATED) as z:
            for name,data in sorted(parts.items()):
                info=ZipInfo(name,(2000,1,1,0,0,0));info.compress_type=ZIP_DEFLATED;z.writestr(info,expected[name])
    observed=_parts(output)
    merge.require(set(observed)==set(parts) and all(observed[n]==b for n,b in parts.items() if n not in changed),"Unrelated ZIP part changed")
    return {"source":ref(source),"output":ref(output),"edits":edits,"part_cell_audits":audits,"unchanged_parts":len(parts)-len(changed),"all_other_parts_byte_identical":True,"openpyxl_save_used":False}


def verify_surgery(source, destination, edits):
    """Reconstruct all expected OOXML parts without writing or calculating."""
    expected,_=_edited_parts(_parts(source),edits)
    merge.require(_parts(destination)==expected,"Declared surgery/source identity differs")


def delta(left,right):
    result=[]
    for sheet in sorted(set(left["cells"])|set(right["cells"])):
        a=left["cells"].get(sheet,{});b=right["cells"].get(sheet,{})
        for cell in sorted(set(a)|set(b)):
            av=a.get(cell,{}).get("primary",helper().EMPTY);bv=b.get(cell,{}).get("primary",helper().EMPTY)
            if av!=bv:result.append({"sheet":sheet,"cell":cell,"input":av,"goal":bv})
    return result


def judge(original,goal,candidate):
    expected=delta(original,goal);actual=delta(original,candidate)
    expected_points={(r["sheet"],r["cell"]) for r in expected};actual_points={(r["sheet"],r["cell"]) for r in actual}
    wrong=[r for r in actual if r["goal"]!=goal["cells"].get(r["sheet"],{}).get(r["cell"],{}).get("primary",helper().EMPTY)]
    structure=original["sheets"]==goal["sheets"]==candidate["sheets"]
    return {"reward":int(structure and expected_points==actual_points and not wrong),"structure_ok":structure,"expected_change_count":len(expected),"actual_change_count":len(actual),"missing_changes":[list(p) for p in sorted(expected_points-actual_points)],"extra_changes":[list(p) for p in sorted(actual_points-expected_points)],"wrong_values":wrong,"full_sparse_union_compared":True,"numeric_primary_two_decimals":True}


def _load_config(config):
    value=read(config)
    merge.require(value["kind"]=="fixed_scoped_heterogeneous_review_tasks_recipe" and value["version"]==1,"New task recipe identity required")
    merge.require(value==read(ROOT/"config/heterogeneous_review_tasks_v1.json"),"Only the frozen fixed-eight recipe is supported")
    for binding in all_refs(value):checked(binding)
    return value


def _coverage(config,source_snapshot,preflight,scope):
    base=read(config["original_donor_config"]);expected={};evidence=[]
    mapped=helper().expected_from_donors(base)
    for row in scope["rows"]:
        if row["id"]=="nyu_simple":continue
        for sheet,address in row["audited_points"]:
            a=mapped["cells"][sheet][address]["primary"];b=source_snapshot["cells"][sheet][address]["primary"]
            merge.require(a==b,"Accepted historical scoped value transfer changed")
            expected[(sheet,address)]=a
        evidence.append({"donor":row["id"],"historical_financial_addresses":row["audited"],"scoped_audits":next(d["scoped_audits"] for d in base["donors"] if d["id"]==row["id"])})
    audit=read(config["NYU_scope_audit"])
    merge.require(audit["kind"]=="independent_NYU_fixed343_scoped_numeric_business_audit" and audit["all_scoped_numeric_checks_passed"] and not audit["whole1231_or4430_formula_certificate"] and len(audit["expected_typed_by_original_address"])==343,"Independent343 scoped NYU audit required")
    nyu=next(d for d in preflight["donors"] if d["id"]=="nyu_simple")
    for point,typed in audit["expected_typed_by_original_address"].items():
        sheet,address=point.rsplit("!",1);mapped_sheet=nyu["sheet_map"][sheet];value={"type":typed[0],"value":typed[1]}
        merge.require(source_snapshot["cells"][mapped_sheet][address]["primary"]==value,"IndependentNYU343 value differs")
        expected[(mapped_sheet,address)]=value
    fs=[]
    for address,base_address in (("N20","E20"),("N36","E36")):
        c=source_snapshot["cells"]["FS - BS"][address];base=source_snapshot["cells"]["FS - BS"][base_address]
        merge.require(c["formula"].replace("$","").removeprefix("=")==base_address+"/"+base_address and base["primary"]["type"]=="number" and float(base["primary"]["value"])!=0,"Common-size total needs its same nonzero base")
        value={"type":"number","value":"1.00"};merge.require(c["primary"]==value,"Common-size total must beone")
        expected[("FS - BS",address)]=value;fs.append({"sheet":"FS - BS","cell":address,"independent_expected":value,"business_identity":"Nonzero total expressed as a proportion of itself", "nonzero_total":base["primary"]})
    targets={tuple(p) for row in scope["rows"] for p in row["reverse_closure_points"]}
    merge.require(len(expected)==len(targets)==766 and set(expected)==targets,"Complete766 financial scope coverage required")
    merge.require(source_snapshot["cells"]["Budget - Summary"].get("F12",{}).get("primary",helper().EMPTY)==helper().EMPTY,"Intentional committee-allocation blank differs")
    return {"kind":"independent_scoped_heterogeneous_review_task_financial_coverage","version":1,"passed":True,"expected_typed_values":[{"sheet":s,"cell":a,"expected":v} for (s,a),v in sorted(expected.items())],"legacy421_evidence_transfer":evidence,"NYU343_independent_audit":config["NYU_scope_audit"],"two_additional_FS_common_size_checks":fs,"intentional_budget_blank":{"sheet":"Budget - Summary","cell":"F12","expected":helper().EMPTY,"evidence":"Originalcommitteeallocationinstruction explicitly preservesF12:F14 blank"},"whole4430_formula_financial_certificate":False}


def _instructions(config,mode):
    lead=("Complete the omitted calculated financial families in the nominated business schedules. Preserve genuine intentional blanks." if mode=="financial_modeling" else "Review and repair the nominated business schedules for financial inconsistencies. Preserve valid neighboring calculations and genuine intentional blanks.")
    return lead+"\n\n"+config["public_policy_brief"]+"\n\nSupplied current numeric assumptions and periods govern; legacy example commentary does not introduce new assumptions.\n\nRead /app/input.xlsx and save /app/output.xlsx. The workbook will be fully recalculated before values are checked.\n"


def _namespace_proof(snapshot,preflight,faults):
    from openpyxl.formula.tokenizer import Tokenizer
    owners={s:d["id"] for d in preflight["donors"] for s in d["sheet_map"].values()}
    table_owners={n:d["id"] for d in preflight["donors"] for n in d["table_map"].values()}
    formulas=[(s,c["formula"]) for s,row in snapshot["cells"].items() for c in row.values() if c["is_formula"]]+[(f["sheet"],f["replacement"]) for f in faults]
    qualified=0
    for sheet,formula in formulas:
        for token in Tokenizer("="+formula.removeprefix("=")).items:
            if token.type!="OPERAND" or token.subtype!="RANGE":continue
            if "!" in token.value:
                qualifier=merge._unquote(token.value.rsplit("!",1)[0]);merge.require(owners.get(qualifier)==owners[sheet],"Interbusiness dependency requires separate component proof");qualified+=1
            else:
                table=token.value.split("[",1)[0]
                merge.require(table not in table_owners or table_owners[table]==owners[sheet],"Interbusiness table dependency")
    return {"original_donor_count":8,"original_physical_formulas_checked":len(formulas)-len(faults),"declared_mutant_formulas_checked":len(faults),"qualified_reference_operands_checked":qualified,"all_qualified_formula_edges_remain_in_original_donor":True,"translated_name_table_and_metadata_roundtrips_bound_by_preflight":True,"joint_native_full_D_requires_all_eight_family_effects":True}


def prepare_pair(output,config=None):
    config=Path(config or ROOT/"config/heterogeneous_review_tasks_v1.json");c=_load_config(config)
    output=helper().support()._output(output);merge.require(not output.exists(),"Use a fresh pair preparation")
    source=checked(c["source"]);snapshot=helper().snapshot(source);pre=read(c["donor_preflight"]);scope=read(c["closure"])
    coverage=_coverage(c,snapshot,pre,scope)
    points=sorted((tuple(p) for row in scope["rows"] for p in row["reverse_closure_points"]))
    sheet_owner={s:d["id"] for d in pre["donors"] for s in d["sheet_map"].values()}
    faults=c["faults"];merge.require(len(faults)==8 and len({f["donor"] for f in faults})==8,"One genuine fault in each different business required")
    for f in faults:merge.require(sheet_owner[f["sheet"]]==f["donor"],"Fault namespace differs")
    namespace_proof=_namespace_proof(snapshot,pre,faults)
    protected={(r["mapped_sheet"],r["cell"]) for d in pre["donors"] for r in d["retained_cached_error_lineage"]}|{("Agent - Entry","B28"),("Agent - Entry","C28")}
    merge.require(not set(points)&protected and not {(f["sheet"],f["cell"]) for f in faults}&protected,"Knownunsafe/error root intersection")
    output.mkdir(parents=True);private=output/"private";private.mkdir()
    patches=[]
    for binding in c["text_patch_allowlists"]:
        patch=read(binding)
        selected=patch["patches"] if "patches" in patch else [patch["additional_patch"]]
        for p in selected:
            smap=next(d["sheet_map"] for d in pre["donors"] if d["id"]=="nyu_simple");sheet=smap[p["sheet"]]
            merge.require(snapshot["cells"][sheet][p["cell"]]["primary"]=={"type":"string","value":p["original_typed_text"]},"Presentation source label differs")
            patches.append({"sheet":sheet,"cell":p["cell"],"action":"text","value":p["new_minimal_text"]})
    merge.require(len(patches)==6,"Exactly six approved presentation corrections required")
    presentation=private/"presentation_v2.xlsx";patch_proof=surgery(source,presentation,patches);presentation_snapshot=helper().snapshot(presentation)
    comparison=helper().compare_snapshots(snapshot,presentation_snapshot)
    merge.require(comparison["primary_value_mismatch_count"]==6 and comparison["formula_or_literal_identity_mismatch_count"]==0 and comparison["raw_numeric_difference_count"]==0,"Onlysix literalpresentation values maychange")
    patch_ref=write(private/"presentation_patch_proof.json",patch_proof);coverage_ref=write(private/"independent_scope_coverage.json",coverage)
    protected_ref=write(private/"known_protected_points.json",{"points":[list(p) for p in sorted(protected)],"source_preflight":c["donor_preflight"],"wholefinancialcertified":False})
    extra=next((s,a,v) for s,row in presentation_snapshot["cells"].items() for a,v in row.items() if not v["is_formula"] and v["primary"]["type"]=="string" and v["primary"]["value"] and (s,a) not in set(points)|{(p["sheet"],p["cell"]) for p in patches}|protected)
    views={}
    for mode,label in MODES.items():
        directory=output/label;public=directory/"public";hidden=directory/"private";public.mkdir(parents=True);hidden.mkdir()
        edits=([{"sheet":s,"cell":a,"action":"clear"} for s,a in points] if mode=="financial_modeling" else [{"sheet":f["sheet"],"cell":f["cell"],"action":"formula","value":f["replacement"]} for f in faults])
        input_path=public/"input.xlsx";input_proof=surgery(presentation,input_path,edits)
        instruction=public/"instruction.md";instruction.write_text(_instructions(c,mode))
        goal=hidden/"goal.xlsx";surgery(presentation,goal,[])
        root=("FS - IS","E7") if mode=="financial_modeling" else (faults[0]["sheet"],faults[0]["cell"])
        equivalent=hidden/"equivalent_raw.xlsx"
        equivalent_root=("FS - IS","E7")
        body=presentation_snapshot["cells"][equivalent_root[0]][equivalent_root[1]]["formula"].removeprefix("=")
        surgery(presentation,equivalent,[{"sheet":equivalent_root[0],"cell":equivalent_root[1],"action":"formula","value":"("+body+")"}])
        missed=hidden/"missed_root_raw.xlsx"
        root_edit={"sheet":root[0],"cell":root[1],"action":"clear"} if mode=="financial_modeling" else {"sheet":root[0],"cell":root[1],"action":"formula","value":faults[0]["replacement"]}
        surgery(presentation,missed,[root_edit])
        extra_path=hidden/"extra_change_raw.xlsx"
        surgery(presentation,extra_path,[{"sheet":extra[0],"cell":extra[1],"action":"text","value":extra[2]["primary"]["value"]+" [changed]"}])
        plan={"mode":mode,"financial_scope":[list(p) for p in points],"healthy_review_region":[list(p) for p in sorted(set(points)|{("Budget - Summary","F12")})],"faults":faults if mode=="debugging" else [],"missed_root":list(root),"extra_change":{"sheet":extra[0],"cell":extra[1],"original":extra[2]["primary"]["value"],"replacement":extra[2]["primary"]["value"]+" [changed]"},"component_namespaces":sheet_owner,"component_independence_proof":namespace_proof,"family_counts":{r["id"]:r["reverse_closure_formulas"] for r in scope["rows"]},"donor_context_disclosure":c["donor_context_disclosure"],"input_surgery":input_proof,"known_protected_points":protected_ref}
        plan_ref=write(hidden/"plan.json",plan);expected_ref=write(hidden/"expected_delta.json",{"kind":"prospective_pending_actual_full_D","version":1,"actual_D_computed":False,"mode":mode})
        content_identity=helper().support().canonical({"mode":mode,"source":ref(presentation)["sha256"],"input":ref(input_path)["sha256"],"instruction":ref(instruction)["sha256"]})
        material={"kind":MATERIAL_KIND,"version":1,"mode":mode,"material_content_identity":content_identity,"public_input":ref(input_path),"instruction":ref(instruction),"private_goal":ref(goal),"expected_delta":expected_ref,"review_scope":plan_ref,"source_presentation":ref(presentation),"source_lineage":c["native_source_terminal"],"module_count":8,"qualified":False,"source_admitted":False}
        material_ref=write(hidden/"material.json",material)
        frozen={"kind":VIEW_KIND,"version":1,"mode":mode,"phase":"development","config":ref(config),"recipe":recipes(),"source":c["source"],"source_presentation":ref(presentation),"presentation_patch_proof":patch_ref,"independent_scope_coverage":coverage_ref,"known_protected_points":protected_ref,"material":material_ref,"input":material["public_input"],"instruction":material["instruction"],"goal":material["private_goal"],"expected_delta":expected_ref,"plan":plan_ref,"control_raw_inputs":{"equivalent":ref(equivalent),"missed_root":ref(missed),"extra_change":ref(extra_path)},"runtime_profile":c["runtime_profile"],"runtime_profile_value":helper()._runtime(checked(c["runtime_profile"]))[1],"maximum_external_LO_calls":7,"outer_retries":0,"qualified":False,"model_solver_Harbor_calls":0}
        views[mode]=write(directory/"preparation.json",frozen)
    return write(output/"pair_preparation.json",{"kind":KIND,"version":1,"views":views,"config":ref(config),"recipe":recipes(),"maximum_external_LO_calls":14,"source_presentation":ref(presentation),"source_qualified":False,"qualified":False})


def validate_prepared(value):
    path=Path(value);path=path/"preparation.json" if path.is_dir() else path
    frozen=read(path);merge.require(frozen["kind"]==VIEW_KIND and frozen["version"]==1 and frozen["mode"] in MODES and frozen["recipe"]==recipes(),"Frozen new view identity/recipe changed")
    c=_load_config(checked(frozen["config"]))
    for binding in all_refs(frozen):checked(binding)
    merge.require(frozen["phase"]=="development" and frozen["maximum_external_LO_calls"]==7 and frozen["outer_retries"]==0 and frozen["qualified"] is False and frozen["model_solver_Harbor_calls"]==0,"New scopedcoverage/seven-call contract required")
    merge.require(frozen["source"]==c["source"] and frozen["runtime_profile"]==c["runtime_profile"] and helper()._runtime(checked(c["runtime_profile"]))==(frozen["runtime_profile"],frozen["runtime_profile_value"]),"Frozen source/resource profile differs")
    scope=read(c["closure"]);pre=read(c["donor_preflight"]);source=helper().snapshot(checked(c["source"]))
    merge.require(read(frozen["independent_scope_coverage"])==_coverage(c,source,pre,scope),"Independent financial coverage changed")
    points=sorted(tuple(p) for row in scope["rows"] for p in row["reverse_closure_points"])
    owner={s:d["id"] for d in pre["donors"] for s in d["sheet_map"].values()}
    protected={(r["mapped_sheet"],r["cell"]) for d in pre["donors"] for r in d["retained_cached_error_lineage"]}|{("Agent - Entry","B28"),("Agent - Entry","C28")}
    merge.require(read(frozen["known_protected_points"])=={"points":[list(p) for p in sorted(protected)],"source_preflight":c["donor_preflight"],"wholefinancialcertified":False},"Known risk lineage differs")
    patches=[];smap=next(d["sheet_map"] for d in pre["donors"] if d["id"]=="nyu_simple")
    for binding in c["text_patch_allowlists"]:
        patch=read(binding)
        for p in patch["patches"] if "patches" in patch else [patch["additional_patch"]]:
            merge.require(source["cells"][smap[p["sheet"]]][p["cell"]]["primary"]=={"type":"string","value":p["original_typed_text"]},"Original presentation label differs")
            patches.append({"sheet":smap[p["sheet"]],"cell":p["cell"],"action":"text","value":p["new_minimal_text"]})
    merge.require(len(patches)==6,"Six presentation corrections required")
    verify_surgery(checked(c["source"]),checked(frozen["source_presentation"]),patches)
    proof=read(frozen["presentation_patch_proof"])
    merge.require(proof["source"]==c["source"] and proof["output"]==frozen["source_presentation"] and proof["edits"]==patches and proof["all_other_parts_byte_identical"] and not proof["openpyxl_save_used"],"Presentation patch evidence differs")
    p=read(frozen["plan"]);mode=frozen["mode"];presentation=helper().snapshot(checked(frozen["source_presentation"]))
    extra=next((s,a,v) for s,row in presentation["cells"].items() for a,v in row.items() if not v["is_formula"] and v["primary"]["type"]=="string" and v["primary"]["value"] and (s,a) not in set(points)|{(x["sheet"],x["cell"]) for x in patches}|protected)
    root=("FS - IS","E7") if mode=="financial_modeling" else (c["faults"][0]["sheet"],c["faults"][0]["cell"])
    edits=[{"sheet":s,"cell":a,"action":"clear"} for s,a in points] if mode=="financial_modeling" else [{"sheet":f["sheet"],"cell":f["cell"],"action":"formula","value":f["replacement"]} for f in c["faults"]]
    merge.require(p["mode"]==mode and p["financial_scope"]==[list(v) for v in points] and p["healthy_review_region"]==[list(v) for v in sorted(set(points)|{("Budget - Summary","F12")})] and p["faults"]==(c["faults"] if mode=="debugging" else []) and p["component_namespaces"]==owner and p["family_counts"]=={r["id"]:r["reverse_closure_formulas"] for r in scope["rows"]} and p["known_protected_points"]==frozen["known_protected_points"] and p["missed_root"]==list(root) and p["donor_context_disclosure"]==c["donor_context_disclosure"],"Scope/fault/component plan changed")
    merge.require(p["component_independence_proof"]==_namespace_proof(source,pre,c["faults"]),"Component namespace proof changed")
    verify_surgery(checked(frozen["source_presentation"]),checked(frozen["input"]),edits)
    verify_surgery(checked(frozen["source_presentation"]),checked(frozen["goal"]),[])
    merge.require(p["input_surgery"]["source"]==frozen["source_presentation"] and p["input_surgery"]["output"]==frozen["input"] and p["input_surgery"]["edits"]==edits,"Input surgery binding differs")
    eq={"sheet":"FS - IS","cell":"E7","action":"formula","value":"("+presentation["cells"]["FS - IS"]["E7"]["formula"].removeprefix("=")+")"}
    missed={"sheet":root[0],"cell":root[1],"action":"clear"} if mode=="financial_modeling" else {"sheet":root[0],"cell":root[1],"action":"formula","value":c["faults"][0]["replacement"]}
    extra_edit={"sheet":extra[0],"cell":extra[1],"action":"text","value":extra[2]["primary"]["value"]+" [changed]"}
    merge.require(p["extra_change"]=={"sheet":extra[0],"cell":extra[1],"original":extra[2]["primary"]["value"],"replacement":extra_edit["value"]},"Extra-change control differs")
    for name,edit in (("equivalent",eq),("missed_root",missed),("extra_change",extra_edit)):verify_surgery(checked(frozen["source_presentation"]),checked(frozen["control_raw_inputs"][name]),[edit])
    merge.require(checked(frozen["instruction"]).read_text()==_instructions(c,mode),"Public business policy brief differs")
    merge.require(read(frozen["expected_delta"])=={"kind":"prospective_pending_actual_full_D","version":1,"actual_D_computed":False,"mode":mode},"A prospective view must not invent actual D")
    material={"kind":MATERIAL_KIND,"version":1,"mode":mode,"material_content_identity":helper().support().canonical({"mode":mode,"source":frozen["source_presentation"]["sha256"],"input":frozen["input"]["sha256"],"instruction":frozen["instruction"]["sha256"]}),"public_input":frozen["input"],"instruction":frozen["instruction"],"private_goal":frozen["goal"],"expected_delta":frozen["expected_delta"],"review_scope":frozen["plan"],"source_presentation":frozen["source_presentation"],"source_lineage":c["native_source_terminal"],"module_count":8,"qualified":False,"source_admitted":False}
    merge.require(read(frozen["material"])==material,"Material/source/content identity differs")
    return frozen,p
