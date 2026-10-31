#!/usr/bin/env python3
"""Actual scoped heterogeneous task validation: seven calls per mode, no retry."""
from __future__ import annotations
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from sheets_factory.workbook import heterogeneous_review_tasks as task
from sheets_factory.core.audit import AuditStore,utcnow
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.workbook.thread_capped_resource_engine import validate_capped_call

ACTUAL_KIND="heterogeneous_review_task_view_actual_validation"
PAIR_KIND="heterogeneous_review_task_pair_actual_validation"
validate_prepared=task.validate_prepared
STAGES=("input1","input2","goal1","goal2","equivalent","missed_root","extra_change")


def _values_equal(left,right):
    report=task.helper().compare_snapshots(left,right)
    return {"passed":report["structure_ok"] and report["primary_value_mismatch_count"]==0,"full_sparse_union_cells_checked":report["full_sparse_union_cells_checked"],"primary_value_mismatches":report["primary_value_mismatches"],"raw_numeric_difference_count":report["raw_numeric_difference_count"],"raw_numeric_differences":report["raw_numeric_differences"],"numeric_primary_two_decimals":True,"exact_numeric_equivalence_claimed":False}


def actual_D(frozen,plan,input_snapshot,goal_snapshot):
    rows=task.delta(input_snapshot,goal_snapshot);points={(r["sheet"],r["cell"]) for r in rows}
    coverage=task.read(frozen["independent_scope_coverage"])
    known={(r["sheet"],r["cell"]):r["expected"] for r in coverage["expected_typed_values"]}
    if frozen["mode"]=="debugging":known[("Budget - Summary","F12")]=task.helper().EMPTY
    task.merge.require(points and points<=set(known),"ActualfullD is not independently covered")
    for point in points:task.merge.require(goal_snapshot["cells"].get(point[0],{}).get(point[1],{}).get("primary",task.helper().EMPTY)==known[point],"ActualD goal does not match independent financial expectation")
    protected={tuple(p) for p in task.read(frozen["known_protected_points"])["points"]}
    task.merge.require(not points&protected,"ActualfullD intersects confirmed unsafe/fixederror points")
    families={donor:0 for donor in plan["family_counts"]}
    for row in rows:families[plan["component_namespaces"][row["sheet"]]]+=1
    task.merge.require(all(families.values()),"Every independent business family needs actual nonempty impact")
    expected_errors=[(s,a,c["primary"]["value"]) for s,values in goal_snapshot["cells"].items() for a,c in values.items() if c["primary"]["type"]=="error"]
    input_errors=[(s,a,c["primary"]["value"]) for s,values in input_snapshot["cells"].items() for a,c in values.items() if c["primary"]["type"]=="error"]
    task.merge.require(sorted(input_errors)==sorted(expected_errors) and len(expected_errors)==12,"Only exact12expected fixed errors may remain")
    return {"kind":"complete_heterogeneous_review_task_actual_D","version":1,"mode":frozen["mode"],"expected_changes":rows,"actual_change_count":len(rows),"all_independently_covered":True,"family_effect_counts":families,"all_eight_families_nonempty":True,"known_protected_points_disjoint":True,"expected_fixed_errors":[list(p) for p in sorted(expected_errors)],"full_sparse_union_compared":True,"numeric_primary_two_decimals":True,"financial_scope_certificate_only":True,"whole4430_formula_financial_certificate":False}


def _financial_goal(frozen,observed):
    scope=task.read(frozen["independent_scope_coverage"]);bad=[]
    for row in scope["expected_typed_values"]:
        point=(row["sheet"],row["cell"]);actual=observed["cells"].get(point[0],{}).get(point[1],{}).get("primary",task.helper().EMPTY)
        if actual!=row["expected"]:bad.append({"sheet":point[0],"cell":point[1],"expected":row["expected"],"actual":actual})
    task.merge.require(not bad,"Independent766 goal financial scope failed: "+json.dumps(bad[:5]))
    return {"passed":True,"independent_typed_financial_fields_checked":766,"whole4430_formula_financial_certificate":False}


def _input_identity(frozen,observed):
    original=task.helper().snapshot(task.checked(frozen["input"]))
    comparison=task.helper().compare_snapshots(original,observed)
    literal_changes=[(s,a) for s,row in original["cells"].items() for a,c in row.items() if not c["is_formula"] and c["primary"]!=observed["cells"].get(s,{}).get(a,{}).get("primary",task.helper().EMPTY)]
    task.merge.require(comparison["structure_ok"] and comparison["formula_or_literal_identity_mismatch_count"]==0 and not literal_changes,"Input formula/literal identity changed during native calculation")


def _retained_public_objects(before,after):
    a=before["object_inventory_diagnostic_only"];b=after["object_inventory_diagnostic_only"]
    def inventory(value):
        return {"notes":Counter((r["cell"],r["text"]) for r in value["comments"]),"chart_references":Counter(tuple(task.merge._formula_tokens(f)) for f in value["chart_formula_references"]),"images":Counter((r["sha256"],r["bytes"]) for r in value["images"])}
    task.merge.require(inventory(a)==inventory(b),"Native calculation changed retained public notes/chart references/image bytes")


def run_sequence(frozen,plan,attempt,call,stage=lambda _:None):
    h=task.helper();files={};snapshots={};records={};stability=[]
    schedule=[("input1",frozen["input"]),("input2",None),("goal1",frozen["goal"]),("goal2",None),("equivalent",frozen["control_raw_inputs"]["equivalent"]),("missed_root",frozen["control_raw_inputs"]["missed_root"]),("extra_change",frozen["control_raw_inputs"]["extra_change"])]
    for index,(name,source_ref) in enumerate(schedule,1):
        if name=="input2":source_ref=files["input1"]
        if name=="goal2":source_ref=files["goal1"]
        stage(name);destination=attempt/(name+".xlsx");call(index,name,Path(source_ref["path"]),destination)
        files[name]=task.ref(destination);snapshots[name]=h.snapshot(destination)
        _retained_public_objects(h.snapshot(source_ref["path"]),snapshots[name])
        records[name+"_snapshot"]=task.write(attempt/(name+"_typed_snapshot.json"),snapshots[name])
        if name=="input1":
            _input_identity(frozen,snapshots[name])
        if name=="goal1":
            comparison=h.compare_snapshots(h.snapshot(frozen["goal"]["path"]),snapshots[name]);task.merge.require(comparison["passed"],"New presentation goal differs from approved source beyond six text clarifications")
            records["financial_goal_scope"]=task.write(attempt/"independent766_goal_audit.json",_financial_goal(frozen,snapshots[name]))
        if name in {"input2","goal2"}:
            prior="input1" if name=="input2" else "goal1";comparison=_values_equal(snapshots[prior],snapshots[name]);stability.append({"left":files[prior],"right":files[name],"comparison":comparison})
            task.merge.require(comparison["passed"],"Fulltyped native stability failed")
        if name=="goal2":
            full=actual_D(frozen,plan,snapshots["input1"],snapshots["goal1"]);records["complete_actual_D"]=task.write(attempt/"complete_actual_D.json",full)
            controls={"oracle":task.judge(snapshots["input1"],snapshots["goal1"],snapshots["goal1"]),"nop":task.judge(snapshots["input1"],snapshots["goal1"],snapshots["input1"])}
            task.merge.require(controls["oracle"]["reward"]==1 and controls["nop"]["reward"]==0,"Oracle/nop controls failed")
        if name in {"equivalent","missed_root","extra_change"}:
            controls[name]=task.judge(snapshots["input1"],snapshots["goal1"],snapshots[name])
            task.merge.require(controls[name]["reward"]==int(name=="equivalent"),"Five-control check failed: "+name)
    records["controls"]=task.write(attempt/"five_controls.json",{"kind":"heterogeneous_review_five_actual_controls","version":1,"passed":True,"controls":controls,"rewards":{k:v["reward"] for k,v in controls.items()},"actual_native_control_calls":3,"oracle_nop_reuse_recalculated_files":True})
    records["stability"]=task.write(attempt/"full_typed_stability.json",{"passed":True,"comparisons":stability,"full_sparse_union_compared":True})
    return records,files


def execute_prepared(output,*,port=0):
    h=task.helper();output=h.support()._output(output);lease=ProducerLease(output).acquire();attempt=output/"private/attempts"/uuid4().hex
    calls=[];records={};audit=server=thread=None;stop=threading.Event();clock=time.monotonic();failure=None;status="held";active={"stage":"cold_validation"}
    try:
        task.merge.require(not (output/"execution_started.json").exists(),"First attempt only; no view retries")
        frozen,plan=validate_prepared(output);attempt.mkdir(parents=True)
        audit=AuditStore(attempt/"audit",{"id":attempt.name,"name":"Scoped heterogeneous "+frozen["mode"],"status":"running","producer_active":True,"producer_pid":os.getpid(),"qualified":0,"target_count":0})
        server=DashboardServer(audit.snapshot,audit.events,host="127.0.0.1",port=port);url=server.start()
        records["started"]=task.write(output/"execution_started.json",{"kind":"heterogeneous_review_view_started","version":1,"preparation":task.ref(output/"preparation.json"),"dashboard_url":url,"producer_pid":os.getpid(),"mode":frozen["mode"],"maximum_external_LO_calls":7,"first_attempt_only":True,"started_at":utcnow()})
        audit.update_run(dashboard_url=url,actual_LO_calls_started=0,actual_LO_calls_completed=0);print(json.dumps({"mode":frozen["mode"],"dashboard_url":url,"producer_pid":os.getpid(),"attempt":str(attempt),"started":records["started"]}),flush=True)
        def heartbeat():
            while not stop.wait(15):audit.update_run(active_stage=active["stage"],elapsed_seconds=time.monotonic()-clock);audit.export()
        thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
        def observe(evidence,ref):
            audit.update_run(owned_container_id=evidence["container_id"],actual_resources=evidence["actual_resources"]);audit.export();print(json.dumps({"mode":frozen["mode"],"owned_container_id":evidence["container_id"],"resource_started":ref}),flush=True)
        engine=h.ObservedEngine(ROOT,frozen["runtime_profile"]["path"],role="source",receipt_directory=attempt/"engine_resources",observer=observe,transcript_directory=attempt)
        def call(index,name,source,destination):
            task.merge.require(len(calls)==index-1 and index<=7,"Newseven-call view contract exceeded")
            task.merge.require(frozen["recipe"]==task.recipes(),"Task validation code changed")
            for r in (frozen["input"],frozen["goal"],frozen["source_presentation"],frozen["source"],frozen["runtime_profile"]):task.checked(r)
            row={"index":index,"stage":name,"input":task.ref(source),"destination":str(destination),"started_at":utcnow(),"completed":False};calls.append(row)
            row["started_receipt"]=task.write(attempt/(name+"_started.json"),dict(row));audit.update_run(actual_LO_calls_started=len(calls));audit.export()
            try:
                tick=time.monotonic();engine.recalculate(source,destination);row.update(completed=True,output=task.ref(destination),elapsed_seconds=time.monotonic()-tick)
                history=engine.metadata()["actual_resource_receipts"];task.merge.require(len(history)==index,"Missing/extra actual LO receipt")
                row["runtime_terminal"]=history[-1];row["actual_resource_evidence"]=validate_capped_call(row,history[-1],frozen,resource_validator=h.support().validate_actual_call)
            finally:
                history=list(engine._history)
                if len(history)==index:
                    row["runtime_terminal"]=history[-1];runtime=task.read(history[-1])
                    if runtime.get("container_id"):
                        cleanup=h.owned_cleanup(runtime["container_id"]);row["owned_cleanup"]=task.write(attempt/(name+"_owned_cleanup.json"),cleanup)
                        task.merge.require(cleanup["removed_and_absent_with_daemon_reachable"],"SameCID owned cleanup failed")
                row["finished_at"]=utcnow();row["terminal_receipt"]=task.write(attempt/(name+"_terminal.json"),dict(row));audit.update_run(actual_LO_calls_started=len(calls),actual_LO_calls_completed=sum(r["completed"] for r in calls));audit.export()
        def stage(name):active["stage"]=name;audit.update_run(active_stage=name);audit.export()
        with h.support().data_temporary(output):records["validation"],files=run_sequence(frozen,plan,attempt,call,stage)
        validate_prepared(output);task.merge.require(len(calls)==7 and all(c["completed"] and "owned_cleanup" in c for c in calls),"Exactlyseven owned actual calls required")
        material=task.read(frozen["material"]);material.update(public_input=files["input1"],raw_public_input=frozen["input"],private_goal=files["goal1"],expected_delta=records["validation"]["complete_actual_D"],actual_validation_completed=True)
        records["material"]=task.write(attempt/"material_completed.json",material);status="passed"
    except BaseException as error:
        failure=error;attempt.mkdir(parents=True,exist_ok=True);records["failure"]=task.write(attempt/"failure.json",{"type":type(error).__name__,"error":str(error),"traceback":traceback.format_exc()})
    finally:
        stop.set()
        if thread:thread.join(timeout=1)
        frozen=task.read(output/"preparation.json");val=records.get("validation",{})
        terminal={"kind":ACTUAL_KIND,"version":1,"mode":frozen["mode"],"status":status,"passed":status=="passed","preparation":task.ref(output/"preparation.json"),"material":records.get("material",frozen["material"]),"source_presentation":frozen["source_presentation"],"raw_input":frozen["input"],"input":files["input1"] if status=="passed" else frozen["input"],"instruction":frozen["instruction"],"goal":files["goal1"] if status=="passed" else frozen["goal"],"expected_delta":val.get("complete_actual_D",frozen["expected_delta"]),"independent_scope_coverage":frozen["independent_scope_coverage"],"complete_actual_D":val.get("complete_actual_D"),"controls":val.get("controls"),"stability":val.get("stability"),"runtime_profile":frozen["runtime_profile"],"actual_LO_calls":calls,"LO_calls_started":len(calls),"LO_calls_completed":sum(c["completed"] for c in calls),"records":records,"elapsed_seconds":time.monotonic()-clock,"finished_at":utcnow(),"outer_retries":0,"qualified":False,"source_admitted":False,"normal_12QA_passed":False,"public_recovery_passed":False,"Harbor_passed":False,"final20_qualified":False,"model_calls":0,"solver_calls":0,"Harbor_calls":0}
        result=task.write(attempt/"terminal.json",terminal)
        if audit:audit.update_run(status=status,producer_active=False,terminal=result);audit.export()
        if server:server.stop()
        if audit:audit.db.close()
        lease.release()
    print(json.dumps({"mode":frozen["mode"],"terminal":result,"status":status,"actual_LO_calls":len(calls)}),flush=True)
    if failure:raise RuntimeError("Actual view HOLD; preserve "+result["path"]) from failure
    validate_completed(result)
    return result


def validate_completed(value):
    terminal=task.read(value);task.merge.require(terminal["kind"]==ACTUAL_KIND and terminal["version"]==1 and terminal["passed"] and terminal["status"]=="passed","Complete new heterogeneous actual view required")
    frozen,plan=validate_prepared(task.checked(terminal["preparation"]))
    for r in task.all_refs(terminal):task.checked(r)
    calls=terminal["actual_LO_calls"];task.merge.require(len(calls)==terminal["LO_calls_started"]==terminal["LO_calls_completed"]==7,"Actualseven-call history required")
    task.merge.require(terminal["mode"]==frozen["mode"] and terminal["source_presentation"]==frozen["source_presentation"] and terminal["raw_input"]==frozen["input"] and terminal["instruction"]==frozen["instruction"] and terminal["runtime_profile"]==frozen["runtime_profile"] and terminal["independent_scope_coverage"]==frozen["independent_scope_coverage"],"Actual view/source binding differs")
    task.merge.require(terminal["outer_retries"]==0 and all(terminal[k] is False for k in ("qualified","source_admitted","normal_12QA_passed","public_recovery_passed","Harbor_passed","final20_qualified")) and all(terminal[k]==0 for k in ("model_calls","solver_calls","Harbor_calls")),"Unsupported qualification/call claim")
    for index,(stage,call) in enumerate(zip(STAGES,calls),1):
        task.merge.require(call["completed"],"Incomplete actual call")
        source=(frozen["input"] if stage=="input1" else calls[0]["output"] if stage=="input2" else frozen["goal"] if stage=="goal1" else calls[2]["output"] if stage=="goal2" else frozen["control_raw_inputs"][stage])
        task.merge.require(call["index"]==index and call["stage"]==stage and call["input"]==source and call["destination"]==call["output"]["path"],"Seven-role order/input chain changed")
        task.merge.require(task.read(call["started_receipt"])=={"index":index,"stage":stage,"input":source,"destination":call["destination"],"started_at":call["started_at"],"completed":False},"Started receipt changed")
        task.merge.require(task.read(call["terminal_receipt"])=={k:v for k,v in call.items() if k!="terminal_receipt"},"Actual call terminal receipt changed")
        validate_capped_call(call,call["runtime_terminal"],frozen,resource_validator=task.helper().support().validate_actual_call)
        cleanup=task.read(call["owned_cleanup"]);runtime=task.read(call["runtime_terminal"])
        task.merge.require(cleanup["owned_container_id"]==runtime["container_id"] and cleanup["removed_and_absent_with_daemon_reachable"],"Cold sameCID cleanup binding failed")
    snapshots={c["stage"]:task.helper().snapshot(c["output"]["path"]) for c in calls}
    for call in calls:_retained_public_objects(task.helper().snapshot(call["input"]["path"]),snapshots[call["stage"]])
    task.merge.require(terminal["input"]==calls[0]["output"] and terminal["goal"]==calls[2]["output"] and terminal["expected_delta"]==terminal["complete_actual_D"],"Export must bind exact recalculated input/goal/fullD")
    _input_identity(frozen,snapshots["input1"])
    task.merge.require(task.helper().compare_snapshots(task.helper().snapshot(task.checked(frozen["goal"])),snapshots["goal1"])["passed"],"Cold presentation goal identity changed")
    records=terminal["records"]["validation"]
    for stage in STAGES:task.merge.require(task.read(records[stage+"_snapshot"])==snapshots[stage],"Frozen typed snapshot changed")
    expected=actual_D(frozen,plan,snapshots["input1"],snapshots["goal1"])
    task.merge.require(task.read(terminal["complete_actual_D"])==expected,"Cold completefullD binding failed")
    task.merge.require(task.read(records["financial_goal_scope"])==_financial_goal(frozen,snapshots["goal1"]),"Independent goal receipt changed")
    comparisons=[]
    for a,b in (("input1","input2"),("goal1","goal2")):
        comparison=_values_equal(snapshots[a],snapshots[b]);task.merge.require(comparison["passed"],"Cold fulltyped stability failed")
        comparisons.append({"left":next(c["output"] for c in calls if c["stage"]==a),"right":next(c["output"] for c in calls if c["stage"]==b),"comparison":comparison})
    task.merge.require(task.read(terminal["stability"])=={"passed":True,"comparisons":comparisons,"full_sparse_union_compared":True},"Stability receipt changed")
    expected_rewards={"oracle":1,"nop":0,"equivalent":1,"missed_root":0,"extra_change":0}
    candidates={"oracle":"goal1","nop":"input1","equivalent":"equivalent","missed_root":"missed_root","extra_change":"extra_change"}
    controls={name:task.judge(snapshots["input1"],snapshots["goal1"],snapshots[stage]) for name,stage in candidates.items()}
    task.merge.require({k:v["reward"] for k,v in controls.items()}==expected_rewards,"Cold actualcontrol failed")
    task.merge.require(task.read(terminal["controls"])=={"kind":"heterogeneous_review_five_actual_controls","version":1,"passed":True,"controls":controls,"rewards":expected_rewards,"actual_native_control_calls":3,"oracle_nop_reuse_recalculated_files":True},"Controlreceipt changed")
    task.merge.require(all(records[k]==terminal[k] for k in ("complete_actual_D","controls","stability")),"Terminal validation record binding differs")
    material=task.read(frozen["material"]);material.update(public_input=terminal["input"],raw_public_input=frozen["input"],private_goal=terminal["goal"],expected_delta=terminal["complete_actual_D"],actual_validation_completed=True)
    task.merge.require(task.read(terminal["material"])==material,"Completedmaterial/source/task binding changed")
    return terminal


def execute_pair(output,*,port=0):
    output=Path(output).resolve();pair=task.read(output/"pair_preparation.json");task.merge.require(pair["kind"]==task.KIND and pair["recipe"]==task.recipes(),"Frozen pair changed")
    for mode,ref in pair["views"].items():validate_prepared(task.checked(ref))
    task.write(output/"pair_execution_started.json",{"pair_preparation":task.ref(output/"pair_preparation.json"),"first_attempt_only":True,"maximum_external_LO_calls":14})
    views={}
    for mode in ("financial_modeling","debugging"):
        views[mode]=execute_prepared(task.checked(pair["views"][mode]).parent,port=port)
    return task.write(output/"pair_terminal.json",{"kind":PAIR_KIND,"version":1,"views":views,"passed":True,"LO_calls_started":14,"LO_calls_completed":14,"qualified":False,"model_calls":0,"solver_calls":0,"Harbor_calls":0,"normal_12QA_passed":False,"public_recovery_passed":False,"final20_qualified":False})


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("action",choices=["validate-prepared","run","run-pair","validate-completed"]);p.add_argument("--prepared",type=Path);p.add_argument("--terminal",type=Path);p.add_argument("--port",type=int,default=0);a=p.parse_args()
    if a.action=="run":result=execute_prepared(a.prepared,port=a.port)
    elif a.action=="run-pair":result=execute_pair(a.prepared,port=a.port)
    elif a.action=="validate-completed":result={"passed":True,"mode":validate_completed(a.terminal)["mode"]}
    else:validate_prepared(a.prepared);result={"passed":True}
    print(json.dumps(result,sort_keys=True))

if __name__=="__main__":main()
