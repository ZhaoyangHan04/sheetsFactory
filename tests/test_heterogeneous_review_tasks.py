"""Pure construction, full-D and mocked seven-call lifecycle checks."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
from concurrent.futures import ThreadPoolExecutor
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET

import pytest
from openpyxl import Workbook
from openpyxl.styles import PatternFill

from sheets_factory.workbook import heterogeneous_review_tasks as task


@pytest.fixture
def v():
    path=task.ROOT/"scripts/validate_heterogeneous_review_task_pair.py"
    spec=importlib.util.spec_from_file_location("heterogeneous_pair_validation_test",path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


def small_book(path):
    wb=Workbook();ws=wb.active;ws.title="Business"
    ws["A1"]=10;ws["A2"]=20;ws["B1"]="=A1+A2";ws["B1"].fill=PatternFill("solid",fgColor="FFFF00")
    ws["C1"]="Keep this policy";ws["C1"].comment=__import__("openpyxl").comments.Comment("Retain policy note","Finance")
    wb.save(path)
    with ZipFile(path) as z:parts={n:z.read(n) for n in z.namelist()}
    root=ET.fromstring(parts["xl/worksheets/sheet1.xml"])
    cell=next(c for c in root.findall('.//{*}c') if c.get('r')=='B1');cell.find('{*}v').text='30'
    parts["xl/worksheets/sheet1.xml"]=ET.tostring(root)
    with ZipFile(path,"w",ZIP_DEFLATED) as z:
        for name,data in parts.items():z.writestr(name,data)
    return path


def test_declared_ooxml_surgery_preserves_objects_styles_and_unrelated_parts(tmp_path):
    source=small_book(tmp_path/"original.xlsx");out=tmp_path/"edited.xlsx"
    edits=[{"sheet":"Business","cell":"B1","action":"clear"},{"sheet":"Business","cell":"C1","action":"text","value":"Clarified policy"}]
    proof=task.surgery(source,out,edits);task.verify_surgery(source,out,edits)
    before=task._parts(source);after=task._parts(out)
    assert set(before)==set(after) and proof["all_other_parts_byte_identical"] and not proof["openpyxl_save_used"]
    assert all(before[n]==after[n] for n in before if n!="xl/worksheets/sheet1.xml")
    a=task.helper().snapshot(source);b=task.helper().snapshot(out)
    assert b["cells"]["Business"]["B1"]["primary"]==task.helper().EMPTY
    assert b["cells"]["Business"]["C1"]["primary"]=={"type":"string","value":"Clarified policy"}
    xml=ET.fromstring(after["xl/worksheets/sheet1.xml"])
    assert next(c for c in xml.findall('.//{*}c') if c.get('r')=='B1').get('s')=='1'
    assert a["cells"]["Business"]["A1"]==b["cells"]["Business"]["A1"]
    with pytest.raises(ValueError,match="surgery/source"):
        task.verify_surgery(source,out,[edits[0]])


def test_missing_intentional_blank_can_be_inserted_and_restored_without_relocation(tmp_path):
    source=small_book(tmp_path/"original.xlsx");fault=tmp_path/"fault.xlsx";repair=tmp_path/"repair.xlsx"
    task.surgery(source,fault,[{"sheet":"Business","cell":"F12","action":"formula","value":"A1"}])
    task.surgery(fault,repair,[{"sheet":"Business","cell":"F12","action":"clear"}])
    snapshot=task.helper().snapshot(repair)
    assert snapshot["cells"]["Business"]["F12"]["primary"]==task.helper().EMPTY
    assert snapshot["cells"]["Business"]["A1"]["primary"]=={"type":"number","value":"10.00"}
    with pytest.raises(ValueError,match="Duplicate"):
        task.surgery(source,tmp_path/"duplicate.xlsx",[{"sheet":"Business","cell":"F12","action":"clear"}]*2)


@pytest.fixture
def synthetic(tmp_path):
    def make(name,value,*,miss=False,extra=False):
        wb=Workbook();wb.remove(wb.active)
        for i in range(8):
            ws=wb.create_sheet("Family "+str(i))
            for n in range(1,(96 if i<6 else 95)+1):ws.cell(n,1,0 if miss and i==0 and n==1 else value)
            if i==7:
                for n in range(1,13):ws.cell(n,6,"#DIV/0!")
            if extra and i==0:ws["B1"]="Undeclared extra"
        path=tmp_path/(name+".xlsx");wb.save(path);return path
    original=make("input",0);goal=make("goal",1);missed=make("missed",1,miss=True);extra=make("extra",1,extra=True)
    expected=[{"sheet":"Family "+str(i),"cell":"A"+str(n),"expected":{"type":"number","value":"1.00"}} for i in range(8) for n in range(1,(96 if i<6 else 95)+1)]
    coverage=task.write(tmp_path/"coverage.json",{"expected_typed_values":expected})
    protected=task.write(tmp_path/"protected.json",{"points":[["Family 7","F"+str(n)] for n in range(1,13)]})
    frozen={"mode":"financial_modeling","input":task.ref(original),"goal":task.ref(goal),"independent_scope_coverage":coverage,"known_protected_points":protected,"control_raw_inputs":{"equivalent":task.ref(goal),"missed_root":task.ref(missed),"extra_change":task.ref(extra)}}
    plan={"family_counts":{str(i):96 if i<6 else 95 for i in range(8)},"component_namespaces":{"Family "+str(i):str(i) for i in range(8)}}
    return frozen,plan,{"input":original,"goal":goal,"missed":missed,"extra":extra}


def test_full_D_766_and_all_eight_family_effects_are_independently_covered(v,synthetic):
    frozen,plan,paths=synthetic
    source=task.helper().snapshot(paths["input"]);goal=task.helper().snapshot(paths["goal"])
    d=v.actual_D(frozen,plan,source,goal)
    assert d["actual_change_count"]==766 and len(d["family_effect_counts"])==8 and all(d["family_effect_counts"].values())
    assert not d["whole4430_formula_financial_certificate"] and len(d["expected_fixed_errors"])==12
    bad=deepcopy(goal);bad["cells"]["Family 0"]["XFD1048576"]={"primary":{"type":"number","value":"1.00"}}
    with pytest.raises(ValueError,match="independently covered"):v.actual_D(frozen,plan,source,bad)
    missing=deepcopy(source)
    for a,c in goal["cells"]["Family 0"].items():missing["cells"]["Family 0"][a]=c
    with pytest.raises(ValueError,match="Every independent business"):v.actual_D(frozen,plan,missing,goal)


def test_judge_checks_full_union_exact_typed_values_and_all_five_controls(synthetic):
    _,_,p=synthetic;s={k:task.helper().snapshot(v) for k,v in p.items()}
    assert task.judge(s["input"],s["goal"],s["goal"])["reward"]==1
    assert task.judge(s["input"],s["goal"],s["input"])["reward"]==0
    assert task.judge(s["input"],s["goal"],s["missed"])["reward"]==0
    assert task.judge(s["input"],s["goal"],s["extra"])["reward"]==0
    wrong=deepcopy(s["goal"]);wrong["cells"]["Family 0"]["A1"]["primary"]={"type":"string","value":"1.00"}
    assert task.judge(s["input"],s["goal"],wrong)["reward"]==0


@pytest.mark.parametrize("failure_at",[None,1,2,3,4,5,6,7])
def test_seven_call_chain_stops_at_first_failed_gate(v,synthetic,tmp_path,failure_at):
    frozen,plan,p=synthetic;out=tmp_path/"attempt";out.mkdir();calls=[]
    def perform(index,name,source,destination):
        calls.append((index,name,source,destination))
        correct=p["input"] if name.startswith("input") else p["missed"] if name=="missed_root" else p["extra"] if name=="extra_change" else p["goal"]
        if failure_at==index:correct=p["goal"] if name.startswith("input") or name in {"missed_root","extra_change"} else p["input"]
        shutil.copyfile(correct,destination)
    if failure_at:
        with pytest.raises(ValueError):v.run_sequence(frozen,plan,out,perform)
        assert len(calls)==failure_at
    else:
        records,files=v.run_sequence(frozen,plan,out,perform)
        assert len(calls)==7 and task.read(records["controls"])["rewards"]=={"oracle":1,"nop":0,"equivalent":1,"missed_root":0,"extra_change":0}
        assert task.read(records["complete_actual_D"])["actual_change_count"]==766
        assert files["input1"]["path"]==str(calls[1][2]) and files["goal1"]["path"]==str(calls[3][2])


def test_raw_float_diagnostics_do_not_override_two_decimal_primary(v,synthetic):
    _,_,p=synthetic;a=task.helper().snapshot(p["goal"]);b=deepcopy(a)
    b["cells"]["Family 0"]["A1"]["raw_numeric_text"]="1.000000000000001"
    result=v._values_equal(a,b)
    assert result["passed"] and result["raw_numeric_difference_count"]==1 and not result["exact_numeric_equivalence_claimed"]


def test_namespace_proof_checks_mutants_and_rejects_cross_business_edges():
    pre={"donors":[{"id":"a","sheet_map":{"old":"A"},"table_map":{}},{"id":"b","sheet_map":{"old":"B"},"table_map":{}}]}
    snapshot={"cells":{"A":{"C1":{"is_formula":True,"formula":"A1+A2"}},"B":{}}}
    good=task._namespace_proof(snapshot,pre,[{"sheet":"A","replacement":"'A'!A1"}])
    assert good["declared_mutant_formulas_checked"]==1
    with pytest.raises(ValueError,match="Interbusiness"):
        task._namespace_proof(snapshot,pre,[{"sheet":"A","replacement":"'B'!A1"}])


def test_retained_public_note_image_and_chart_counts_cannot_silently_drop(v,tmp_path):
    source=task.helper().snapshot(small_book(tmp_path/"noted.xlsx"));changed=deepcopy(source)
    changed["object_inventory_diagnostic_only"]["comments"].clear()
    with pytest.raises(ValueError,match="retained public"):
        v._retained_public_objects(source,changed)


@pytest.fixture
def completed(v,synthetic,tmp_path,monkeypatch):
    frozen,plan,p=synthetic;frozen=deepcopy(frozen);out=tmp_path/"completed";out.mkdir();calls=[]
    frozen.update(mode="financial_modeling",source_presentation=task.ref(p["goal"]),instruction=task.write(tmp_path/"instruction.json",{"public":"business brief"}),runtime_profile=task.write(tmp_path/"profile.json",{"test_resource_proof":True}),material=task.write(tmp_path/"raw_material.json",{"kind":task.MATERIAL_KIND,"version":1,"mode":"financial_modeling","material_content_identity":"same-raw-content","public_input":frozen["input"],"instruction":{},"private_goal":frozen["goal"],"expected_delta":{},"qualified":False,"source_admitted":False}))
    preparation=task.write(tmp_path/"preparation.json",frozen)
    def perform(index,name,source,destination):
        correct=p["input"] if name.startswith("input") else p["missed"] if name=="missed_root" else p["extra"] if name=="extra_change" else p["goal"]
        row={"index":index,"stage":name,"input":task.ref(source),"destination":str(destination),"started_at":"2026-10-31T15:00:00+00:00","completed":False}
        row["started_receipt"]=task.write(out/(name+"_started.json"),dict(row));shutil.copyfile(correct,destination)
        cid=str(index)*64;row.update(completed=True,output=task.ref(destination),runtime_terminal=task.write(out/(name+"_runtime.json"),{"container_id":cid}),owned_cleanup=task.write(out/(name+"_cleanup.json"),{"owned_container_id":cid,"removed_and_absent_with_daemon_reachable":True}))
        row["terminal_receipt"]=task.write(out/(name+"_call_terminal.json"),dict(row));calls.append(row)
    records,files=v.run_sequence(frozen,plan,out,perform)
    material=task.read(frozen["material"]);material.update(public_input=files["input1"],raw_public_input=frozen["input"],private_goal=files["goal1"],expected_delta=records["complete_actual_D"],actual_validation_completed=True)
    terminal={"kind":v.ACTUAL_KIND,"version":1,"mode":frozen["mode"],"passed":True,"status":"passed","preparation":preparation,"source_presentation":frozen["source_presentation"],"raw_input":frozen["input"],"input":files["input1"],"instruction":frozen["instruction"],"goal":files["goal1"],"expected_delta":records["complete_actual_D"],"complete_actual_D":records["complete_actual_D"],"controls":records["controls"],"stability":records["stability"],"independent_scope_coverage":frozen["independent_scope_coverage"],"runtime_profile":frozen["runtime_profile"],"material":task.write(out/"material_completed.json",material),"records":{"validation":records},"actual_LO_calls":calls,"LO_calls_started":7,"LO_calls_completed":7,"outer_retries":0,"qualified":False,"source_admitted":False,"normal_12QA_passed":False,"public_recovery_passed":False,"Harbor_passed":False,"final20_qualified":False,"model_calls":0,"solver_calls":0,"Harbor_calls":0}
    monkeypatch.setattr(v,"validate_prepared",lambda _: (frozen,plan))
    checked_resources=[]
    monkeypatch.setattr(v,"validate_capped_call",lambda call,*a,**kw:checked_resources.append(call["index"]))
    return terminal,checked_resources


def test_cold_completed_recomputes_actual_D_all_controls_export_and_cleanup(v,completed,tmp_path):
    terminal,checks=completed;r=task.write(tmp_path/"actual_terminal.json",terminal)
    assert v.validate_completed(r)==terminal and checks==list(range(1,8))
    material=task.read(terminal["material"])
    assert material["public_input"]==terminal["input"]!=terminal["raw_input"]
    assert material["raw_public_input"]==terminal["raw_input"]


@pytest.mark.parametrize("mutation",["reordered","raw_export","different_mode","claims","missing_cleanup","wrong_D","control_reward"])
def test_cold_completed_rejects_chain_scope_controls_and_qualification_changes(v,completed,tmp_path,mutation):
    terminal,_=completed;t=deepcopy(terminal)
    if mutation=="reordered":t["actual_LO_calls"][0],t["actual_LO_calls"][1]=t["actual_LO_calls"][1],t["actual_LO_calls"][0]
    elif mutation=="raw_export":t["input"]=t["raw_input"]
    elif mutation=="different_mode":t["mode"]="debugging"
    elif mutation=="claims":t["qualified"]=True
    elif mutation=="missing_cleanup":t["actual_LO_calls"][0].pop("owned_cleanup")
    elif mutation=="wrong_D":
        d=task.read(t["complete_actual_D"]);d["expected_changes"].pop();t["complete_actual_D"]=task.write(tmp_path/"wrong_D.json",d);t["expected_delta"]=t["complete_actual_D"]
    elif mutation=="control_reward":
        c=task.read(t["controls"]);c["rewards"]["missed_root"]=1;t["controls"]=task.write(tmp_path/"wrong_controls.json",c)
    ref=task.write(tmp_path/"mutated_terminal.json",t)
    with pytest.raises((ValueError,KeyError)):v.validate_completed(ref)


@pytest.fixture(scope="module")
def prepared_pair(tmp_path_factory):
    path=tmp_path_factory.mktemp("pair")/"prepared"
    result=task.prepare_pair(path)
    return path,result


def test_real_fixed_eight_cold_preparation_has_exact766_six_patches_and_no_calls(prepared_pair):
    path,pair_ref=prepared_pair;pair=task.read(pair_ref)
    assert pair["maximum_external_LO_calls"]==14 and not pair["qualified"]
    for mode,label in task.MODES.items():
        frozen,plan=task.validate_prepared(path/label)
        coverage=task.read(frozen["independent_scope_coverage"])
        assert len(coverage["expected_typed_values"])==len(plan["financial_scope"])==766
        assert len(coverage["two_additional_FS_common_size_checks"])==2 and coverage["whole4430_formula_financial_certificate"] is False
        assert len(task.read(frozen["presentation_patch_proof"])["edits"])==6
        assert frozen["maximum_external_LO_calls"]==7 and frozen["outer_retries"]==0
        assert len(plan["faults"])==(8 if mode=="debugging" else 0)
        text=Path(frozen["instruction"]["path"]).read_text()
        assert "current numeric assumptions" in text and "F12" not in text and "766" not in text and "eight faults" not in text.lower()
        assert "numeric attendee grid" in text and "change in annual NOPAT through year 10" in text
        assert all(hint not in text for hint in ("uncapped","periodic IRR","kilogram","deduct the host advance once","successive annual cost-of-capital"))
        assert all(f["replacement"] not in text for f in task.read(frozen["config"])["faults"])
        assert not (path/label/"execution_started.json").exists()


def test_cold_preparation_rejects_rebound_scope_and_resource_contract(prepared_pair,tmp_path):
    path,_=prepared_pair;frozen=task.read(path/"FM/preparation.json")
    changed=deepcopy(frozen);changed["maximum_external_LO_calls"]=8
    candidate=task.write(tmp_path/"changed_count.json",changed)
    with pytest.raises(ValueError,match="seven-call"):task.validate_prepared(candidate["path"])
    p=deepcopy(task.read(frozen["plan"]));p["financial_scope"].pop()
    changed=deepcopy(frozen);changed["plan"]=task.write(tmp_path/"changed_plan.json",p)
    candidate=task.write(tmp_path/"changed_preparation.json",changed)
    with pytest.raises(ValueError,match="Scope/fault"):task.validate_prepared(candidate["path"])


def test_durable_open_exclusive_reservation_race_admits_exactly_one(tmp_path):
    target=tmp_path/"once.json"
    def reserve(_):
        try:task.write(target,{"first_attempt_only":True});return True
        except FileExistsError:return False
    with ThreadPoolExecutor(max_workers=8) as pool:assert sum(pool.map(reserve,range(16)))==1


def test_prior_started_blocks_cold_services_and_preserves_new_zero_call_terminal(v,tmp_path,monkeypatch):
    out=tmp_path/"prepared";out.mkdir();(out/"execution_started.json").write_text('{}')
    frozen={"mode":"financial_modeling","material":{},"source_presentation":{},"input":{},"instruction":{},"goal":{},"expected_delta":{},"independent_scope_coverage":{},"runtime_profile":{}}
    (out/"preparation.json").write_text(json.dumps(frozen));events=[]
    class Lease:
        def __init__(self,*a):pass
        def acquire(self):events.append("acquire");return self
        def release(self):events.append("release")
    monkeypatch.setattr(v,"ProducerLease",Lease)
    monkeypatch.setattr(v,"validate_prepared",lambda *a:pytest.fail("No cold read after prior start"))
    monkeypatch.setattr(v,"DashboardServer",lambda *a,**kw:pytest.fail("No UI after prior start"))
    with pytest.raises(RuntimeError,match="preserve"):v.execute_prepared(out)
    terminal=task.read(next((out/"private/attempts").glob("*/terminal.json")))
    assert terminal["LO_calls_started"]==0 and terminal["outer_retries"]==0 and not terminal["passed"] and events==["acquire","release"]
