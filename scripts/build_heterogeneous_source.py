#!/usr/bin/env python3
"""Prepare a native-table contract source; only explicit --run builds it.

Preparation performs no forward finance, workbook emission, Docker or model
call. Execution preserves one immutable attempt and requires three actual
resource-bound recalculations, complete independent audits and two full typed
stability comparisons. A verified source is not a qualified task.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import traceback
from uuid import uuid4

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sheets_factory.core.audit import AuditStore, utcnow
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.workbook.heterogeneous_contracts import spec
from sheets_factory.workbook.resource_engine import ResourceLibreOfficeEngine, load_runtime_profile, validate_workload_counts

PREPARED_KIND = "prepared_heterogeneous_contract_source"
SOURCE_KIND = "independently_verified_heterogeneous_contract_source"
DEFAULT_PROFILE = ROOT / "config/runtime_profiles/entity_group_large_v2.yaml"
IMAGE = {"tag": "sheetsfactory-lo:24.2-iterative-openpyxl315-v1", "id": "sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043"}
REQUIRED_REGIMES = (
    "loan_BULLET_MONTHLY", "loan_LEVEL_PRINCIPAL_MONTHLY", "loan_BULLET_QUARTERLY_ACCRUAL",
    "quarterly_unpaid_accrual", "quarterly_cash_coupon", "coupon_reset_preserves_accrual",
    "off_cycle_maturity_stub", "amendment_principal_recast", "new_draw_no_current_interest",
    "interest_carry_creation", "interest_carry_use", "interest_carry_expiry", "tax_loss_creation",
    "tax_loss_use", "tax_loss_expiry", "monthly_current_breach", "quarterly_next_month_breach",
    "two_observed_pass_cure", "non_test_cure_carry", "shared_bank_margin",
    "shared_bank_draw_competition", "finite_lp_calls", "reserve_lock", "reserve_release",
    "leap_day_ACT_365F", "leap_day_ACT_360",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def reference(value):
    p = Path(value).resolve(strict=True)
    require(p.is_file() and not Path(value).is_symlink(), "Use a regular immutable artifact")
    before = p.stat()
    h = hashlib.sha256()
    with p.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b""):
            h.update(block)
    after = p.stat()
    require((before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns) ==
            (after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns), "Artifact changed during hashing")
    return {"path": str(p), "sha256": h.hexdigest(), "bytes": after.st_size}


def checked(record):
    require(isinstance(record, dict) and set(record) == {"path", "sha256", "bytes"}
            and type(record["bytes"]) is int and record["bytes"] >= 0, "A complete path/SHA/bytes reference is required")
    require(reference(record["path"]) == record, "Artifact identity differs from its frozen reference")
    return Path(record["path"])


def read(record):
    path = checked(record) if isinstance(record, dict) else Path(record).resolve(strict=True)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    def invalid(_): raise ValueError("Nonfinite JSON number")
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique, parse_constant=invalid)
    require(isinstance(value, dict), "An object artifact is required")
    return value


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    return reference(path)


def recipes():
    paths = [Path(__file__).resolve()]
    paths += [ROOT / "src/sheets_factory/workbook/heterogeneous_contracts" / name
              for name in ("__init__.py", "spec.py", "ledger.py", "excel.py", "validate.py")]
    paths += [ROOT / "src/sheets_factory" / name for name in (
        "workbook/entity_group/excel.py", "workbook/entity_group/spec.py",
        "workbook/resource_engine.py", "workbook/engine.py", "workbook/uno_recalculate.py",
        "evaluation/streaming_verifier.py", "core/audit.py", "dashboard/server.py", "resume.py")]
    return {str(p.resolve()): reference(p)["sha256"] for p in paths}


def runtime(value):
    record = reference(value)
    profile = load_runtime_profile(value)
    require(profile["id"] == "entity_group_large_v2" and profile["image"] == IMAGE,
            "This source requires the pinned b3 image and explicit 32-GiB resource profile")
    require(all(r == {"cpus":2,"memory_bytes":32*1024**3,"pids_limit":256}
                for r in profile["docker_resources"].values()), "Every role must declare 2 CPU/32 GiB/PID256")
    return record, profile


def _output(value, fresh=False):
    p = Path(value).absolute()
    require(p == p.resolve() and p.is_relative_to(ROOT / "outputs") and p.is_relative_to(Path("/data")),
            "Use a real output directory under this project's /data/outputs")
    if fresh:
        require(not p.exists(), "Preserve all previous preparations and failures; use a fresh directory")
    return p


def prepare(specification, output, *, profile=DEFAULT_PROFILE, allow_prototype=False):
    """Freeze one source recipe, with zero finance, workbook, engine or model calls."""
    output = _output(output, fresh=True)
    output.mkdir(parents=True)
    try:
        original = reference(specification)
        raw = read(original)
        public = spec.load_spec(raw)
        require(public["dimension_mode"] != "toy", "A toy fixture cannot become a source")
        require(public["dimension_mode"] != "prototype_6_24_3" or allow_prototype is True,
                "The six-entity source requires explicit --allow-prototype")
        profile_ref, value = runtime(profile)
        recipe = recipes()
        private = output / "private"
        private.mkdir()
        copied = private / "specification.json"
        shutil.copyfile(checked(original), copied)
        require(reference(copied)["sha256"] == original["sha256"], "Private primitive copy changed bytes")
        frozen = {"kind":PREPARED_KIND,"version":1,"created_at":utcnow(),
            "original_specification":original,"private_specification":reference(copied),
            "specification_sha256":spec.canonical_sha256(public),"dimension_mode":public["dimension_mode"],
            "scope":{"entities":len(public["entities"]),"months":len(public["months"]),"scenarios":len(public["scenarios"])},
            "allow_prototype":allow_prototype,"runtime_profile":profile_ref,"runtime_profile_value":value,
            "recipe":recipe,"recipe_sha256":canonical(recipe),"required_regimes":list(REQUIRED_REGIMES),
            "source_workbook_materialized":False,"ledger_execution":False,"LO_calls":0,"model_calls":0,
            "task_count":0,"qualified":False}
        return write_new(output / "preparation.json", frozen)
    except BaseException as error:
        write_new(output / "preparation_failure.json", {"kind":"failed_heterogeneous_source_preparation",
            "finished_at":utcnow(),"error_type":type(error).__name__,"error":str(error),
            "source_workbook_materialized":False,"LO_calls":0,"model_calls":0,"task_count":0,"qualified":False})
        raise


def validate_prepared(value):
    path = Path(value).absolute()
    if path.is_dir(): path = path / "preparation.json"
    frozen = read(reference(path))
    require(frozen.get("kind") == PREPARED_KIND and frozen.get("version") == 1, "Unknown source preparation")
    require(frozen["recipe"] == recipes() and frozen["recipe_sha256"] == canonical(frozen["recipe"]),
            "The frozen financial/source execution recipe changed")
    public = spec.load_spec(read(frozen["private_specification"]))
    checked(frozen["original_specification"])
    require(frozen["private_specification"]["sha256"] == frozen["original_specification"]["sha256"]
            and spec.canonical_sha256(public) == frozen["specification_sha256"], "Frozen primitives changed")
    profile_ref, profile = runtime(checked(frozen["runtime_profile"]))
    require(profile_ref == frozen["runtime_profile"] and profile == frozen["runtime_profile_value"], "Frozen resource policy changed")
    require(frozen["scope"] == {"entities":len(public["entities"]),"months":len(public["months"]),"scenarios":len(public["scenarios"])}
            and frozen["required_regimes"] == list(REQUIRED_REGIMES), "Complete scope or prospective regimes changed")
    require(public["dimension_mode"] != "toy" and (public["dimension_mode"] != "prototype_6_24_3" or frozen["allow_prototype"] is True),
            "The prepared source lacks its explicit dimension opt-in")
    return frozen, public


@contextmanager
def data_temporary(output):
    directory = _output(output) / "temporary"
    require(directory == directory.resolve(), "Do not follow a temporary-directory link")
    directory.mkdir(exist_ok=True)
    old, existed, cached = os.environ.get("TMPDIR"), "TMPDIR" in os.environ, tempfile.tempdir
    os.environ["TMPDIR"], tempfile.tempdir = str(directory), str(directory)
    try:
        yield directory
    finally:
        if existed: os.environ["TMPDIR"] = old
        else: os.environ.pop("TMPDIR", None)
        tempfile.tempdir = cached


@contextmanager
def stage(audit, name):
    started, clock = utcnow(), time.monotonic()
    record = audit.record("nodes", {"node":name,"status":"running","started_at":started})
    audit.update_run(active_stage=name)
    audit.emit("source.stage_started",stage=name)
    audit.export()
    status = "failed"
    try:
        yield
        status = "completed"
    finally:
        audit.update_record("nodes",record,{"status":status,"finished_at":utcnow(),"duration_ms":1000*(time.monotonic()-clock)})
        audit.emit("source.stage_terminal",stage=name,status=status)
        audit.export()


def mechanism_coverage(forward):
    require(forward.get("feasible") is True and forward.get("checks",{}).get("all_journals_and_financial_bridges_verified") is True,
            "All independent scenarios must be feasible and journal-balanced")
    scenarios = forward["scenarios"]
    require(all(s.get("feasible") is True for s in scenarios.values()), "An infeasible scenario is not a source")
    coverage = {}
    for name in REQUIRED_REGIMES:
        witnesses = [{"scenario_id":sid,**row} for sid,s in scenarios.items() for row in s["mechanism_activation"].get(name,[])]
        require(all(isinstance(row.get("month"),str) for row in witnesses), "A mechanism needs dated actual observations")
        coverage[name] = {"observed":bool(witnesses),"observation_count":len(witnesses),"first_witness":witnesses[0] if witnesses else None}
    return {"kind":"independent_heterogeneous_contract_regime_coverage","coverage":coverage,
            "all_required_observed":all(v["observed"] for v in coverage.values()),
            "missing_regimes":[k for k,v in coverage.items() if not v["observed"]],
            "feasible":True,"not_a_source_or_difficulty_certificate":True}


def geometry(book, bindings, expected, profile):
    definitions = {(r["sheet"],r["cell"]):r["formula"] for r in bindings["arithmetic_bindings"]}
    require(len(definitions) == len(bindings["arithmetic_bindings"]) == bindings["formula_count"], "Arithmetic coverage is incomplete or duplicated")
    actual, lengths, cells = {}, [], 0
    for sheet in book:
        require(sheet.max_row <= 1048576 and sheet.max_column <= 16384, "Excel worksheet bounds exceeded")
        for cell in sheet._cells.values():
            if cell.value is None: continue
            cells += 1
            if cell.data_type == "f":
                actual[sheet.title,cell.coordinate] = cell.value
                lengths.append(len(cell.value))
            elif isinstance(cell.value,str) and len(cell.value)>256 and cell.value.lstrip().startswith(("{","[")):
                try: payload=json.loads(cell.value)
                except (ValueError,TypeError): continue
                require(not isinstance(payload,(dict,list)), "A prejoined JSON payload cannot be a public source cell")
    require(actual == definitions and bool(lengths) and max(lengths) <= 8192, "Actual raw formula definitions or maximum formula length differ")
    counts = {"source_physical_formulas":len(actual),"max_profile_cells":max(cells,len(expected["values"])),
              "max_dependency_closure_cells":len(expected["values"]),"full_target_cells":len(bindings["financial_bindings"])}
    limits = validate_workload_counts(profile,counts)
    return {"kind":"complete_heterogeneous_source_geometry","complete_scope":bindings["complete_scope"],
        "physical_formula_count":len(actual),"physical_nonempty_cells":cells,
        "maximum_formula_length":max(lengths),"worksheet_rows":{s.title:s.max_row for s in book},
        "defined_graph_cells":len(expected["values"]),"dependency_count_is_full_graph_upper_bound":True,
        "all_financial_bindings":len(bindings["financial_bindings"]),"resource_limits":limits,"truncated":False}


def validate_actual_call(call, runtime_record, frozen):
    actual = read(runtime_record)
    requested = frozen["runtime_profile_value"]["docker_resources"]["source"]
    require(actual.get("kind") == "resource_bound_libreoffice_call" and actual.get("status") == "completed"
        and actual.get("role") == "source" and actual.get("actual_resources_verified") is True,
        "A completed actual resource-bound source call is required")
    require(actual.get("source") == call["input"] and actual.get("output") == call["output"]
        and actual.get("destination") == call["output"]["path"] and actual.get("image_id") == IMAGE["id"]
        and actual.get("profile") == frozen["runtime_profile"] and actual.get("requested_resources") == requested,
        "The actual call is not bound to this input/output/profile/image")
    require(actual.get("implementation") == reference(ROOT/"src/sheets_factory/workbook/resource_engine.py")
        and actual.get("upstream_engine") == reference(ROOT/"src/sheets_factory/workbook/engine.py")
        and actual.get("workbook_file_timeout_seconds") == 600
        and actual.get("actual_resources") == {"cpus_nanoseconds":2*10**9,"memory_bytes":32*1024**3,"pids_limit":256}
        and re.fullmatch(r"[0-9a-f]{64}",actual.get("container_id","")), "Actual source resources or implementation changed")
    command = actual.get("create_command",[])
    for flag,value in (("--network","none"),("--cap-drop","ALL"),("--security-opt","no-new-privileges")):
        require(command.count(flag)==1 and command[command.index(flag)+1]==value,"Source isolation differs")
    start,end = (datetime.fromisoformat(actual[k]) for k in ("started_at","finished_at"))
    require(start.tzinfo is not None and end.tzinfo is not None and end>=start,"Actual source timestamps are incomplete")
    started_ref=reference(Path(runtime_record["path"]).with_name(actual["call_id"]+".started.json"))
    started=read(started_ref)
    require(started.get("call_id")==actual["call_id"] and started.get("source")==call["input"]
        and started.get("started_at")==actual["started_at"],"Actual started/terminal receipts do not match")
    checked(call["input"]);checked(call["output"])
    return {"started":started_ref,"terminal":runtime_record,"container_id":actual["container_id"],
            "actual_resources":actual["actual_resources"],"image_id":actual["image_id"],"network":"none"}


def _audit_pass(report, workbook, bindings, forward, specification):
    require(report.get("passed") is True and report.get("all_values_checked") is True
        and report.get("physical_formulas_checked")==bindings["formula_count"]
        and report.get("financial_journal_fields_checked")==len(bindings["financial_bindings"])
        and report.get("mismatch_count")==report.get("native_error_count")==0
        and report.get("audited_file")==reference(workbook)
        and report.get("bindings_sha256")==canonical(bindings)
        and report.get("independent_result_sha256")==canonical(forward)
        and report.get("specification_sha256")==spec.canonical_sha256(specification),
        "An actual financial, support, input or full-scope cache audit failed")


def execute_prepared(value, *, port=0):
    from sheets_factory.workbook.heterogeneous_contracts import excel,ledger,validate
    import openpyxl
    path=Path(value).absolute()
    output=_output(path if path.is_dir() else path.parent)
    require((output/"preparation.json").is_file(),"An exact source preparation is required")
    lease=ProducerLease(output).acquire()
    attempt=output/"private/attempts"/uuid4().hex
    audit=server=None;calls=[];clock=time.monotonic();status="failed"
    try:
        require(not (output/"execution_started.json").exists(),"This prepared source has already started; preserve it and use a fresh preparation")
        attempt.mkdir(parents=True)
        audit=AuditStore(attempt/"audit",{"id":attempt.name,"name":"Heterogeneous contract source","status":"starting",
            "target_count":0,"producer_active":True,"producer_pid":os.getpid(),"qualified":0})
        server=DashboardServer(audit.snapshot,audit.events,host="127.0.0.1",port=port);url=server.start()
        start=write_new(attempt/"started.json",{"kind":"heterogeneous_source_build_started","started_at":utcnow(),
            "preparation":reference(output/"preparation.json"),"dashboard_url":url,"producer_pid":os.getpid(),
            "model_calls":0,"task_count":0,"qualified":False})
        write_new(output/"execution_started.json",{"started":start,"first_attempt_only":True})
        audit.update_run(dashboard_url=url,status="running",actual_LO_calls_started=0,actual_LO_calls_completed=0)
        print(json.dumps({"dashboard_url":url,"attempt":str(attempt),"started":start}),flush=True)
        with data_temporary(output):
            with stage(audit,"validate_frozen_preparation"):
                frozen,public=validate_prepared(output)
            with stage(audit,"independent_Decimal_journal_and_dated_regimes"):
                forward=ledger.simulate(public)
                forward_ref=write_new(attempt/"independent_ledger.json",forward)
                regimes=mechanism_coverage(forward)
                regime_ref=write_new(attempt/"mechanism_coverage.json",regimes)
                require(regimes["all_required_observed"],"Required business regimes did not occur: "+", ".join(regimes["missing_regimes"]))
            with stage(audit,"independent_native_formula_emission_and_full_mathematical_audit"):
                book=openpyxl.Workbook()
                try:
                    bindings=excel.emit_heterogeneous_workbook(book,public,
                        max_formulas=frozen["runtime_profile_value"]["limits"]["source_physical_formulas"],allow_production=True)
                    require(bindings["public_notes"]==list(spec.RULES) and bindings["phases"]==list(spec.PHASES)
                        and bindings.get("cached_financial_values_written") is False and bindings.get("independent_ledger_imported") is False,
                        "The source must expose the exact policies without copied journal caches")
                    expected=validate.expected_values(public,forward,bindings)
                    shape=geometry(book,bindings,expected,frozen["runtime_profile_value"])
                    raw=attempt/"raw.xlsx";book.save(raw)
                finally:book.close()
                bindings_ref=write_new(attempt/"bindings.json",bindings)
                shape_ref=write_new(attempt/"geometry.json",shape)
                del expected
            engine=ResourceLibreOfficeEngine(ROOT,frozen["runtime_profile"]["path"],role="source",receipt_directory=attempt/"engine_resources")
            engine.ensure_image()
            versions=[];audits=[];current=raw
            for index in range(3):
                destination=output/"source.xlsx" if index==0 else attempt/f"pass{index+1}.xlsx"
                call={"index":index+1,"input":reference(current),"destination":str(destination),"started_at":utcnow(),"completed":False}
                calls.append(call)
                call["started_receipt"]=write_new(attempt/f"LO{index+1}_started.json",dict(call))
                with stage(audit,f"actual_resource_LO_pass{index+1}"):
                    try:
                        t=time.monotonic();actual=engine.recalculate(current,destination)
                        call.update(completed=True,output=reference(actual),elapsed_seconds=time.monotonic()-t)
                        history=engine.metadata()["actual_resource_receipts"]
                        require(len(history)==index+1,"An extra/missing source recalc was recorded")
                        call["actual_resource_evidence"]=validate_actual_call(call,history[-1],frozen)
                    except BaseException as error:
                        call.update(error_type=type(error).__name__,error=str(error));raise
                    finally:
                        call["finished_at"]=utcnow()
                        call["terminal_receipt"]=write_new(attempt/f"LO{index+1}_terminal.json",dict(call))
                        audit.update_run(actual_LO_calls_started=len(calls),actual_LO_calls_completed=sum(c["completed"] for c in calls))
                with stage(audit,f"complete_financial_and_cache_audit_pass{index+1}"):
                    report=validate.audit_workbook(actual,public,forward,bindings)
                    audits.append(write_new(attempt/f"financial_audit_pass{index+1}.json",report))
                    _audit_pass(report,actual,bindings,forward,public)
                versions.append(actual);current=actual
            with stage(audit,"two_full_typed_stability_checks"):
                comparisons=[{"left":reference(versions[0]),"right":reference(v),"comparison":validate.compare_typed_caches(versions[0],v)} for v in versions[1:]]
                stability=write_new(attempt/"stability.json",{"kind":"three_actual_pass_full_typed_stability","comparisons":comparisons,
                    "stable":all(c["comparison"]["passed"] for c in comparisons),"money_quantization_applied":False})
                require(all(c["comparison"].get("passed") is True and c["comparison"].get("entire_value_union_checked") is True
                    and c["comparison"].get("typed_value_mismatches")==0 and c["comparison"].get("union_cells_checked",0)>0 for c in comparisons),
                    "The complete typed source values changed on further actual recalculation")
            with stage(audit,"freeze_verified_source_manifest"):
                require(validate_prepared(output)==(frozen,public),"Financial source recipe or primitives changed during execution")
                actual_runtime=engine.metadata()
                require(actual_runtime["network"]=="none" and actual_runtime["actual_calculation_calls_recorded"]==3,
                    "Exactly three isolated source calculations are required")
                manifest={"kind":SOURCE_KIND,"version":1,"source_kind":"hypothetical_heterogeneous_contracts_source",
                    "status":"source_verified_not_task_quality_or_difficulty_qualified","workbook":reference(versions[0]),
                    "local_path":str(versions[0]),"source_preparation":reference(output/"preparation.json"),
                    "private_specification":frozen["private_specification"],"original_specification":frozen["original_specification"],
                    "specification_sha256":frozen["specification_sha256"],"scope":frozen["scope"],
                    "independent_ledger":forward_ref,"bindings":bindings_ref,"geometry":shape_ref,"mechanism_coverage":regime_ref,
                    "financial_audits":audits,"financial_audit_passed":True,"stability":stability,"engine_calls":calls,
                    "actual_LO_recalculations":3,"runtime_profile":frozen["runtime_profile"],"runtime":actual_runtime,
                    "source_recipe_sha256":frozen["recipe"],"source_recipe_digest":frozen["recipe_sha256"],
                    "public_workbook_contains_prejoined_JSON":False,"public_workbook_contains_recovery_reader":False,
                    "raw_financial_workbook_ancestry":[],"hypothetical_primitive_origin":frozen["original_specification"],
                    "code_reuse_is_not_raw_source_ancestry":True,"agent_and_verifier_resources_actually_verified":False,
                    "no_task_input_or_full_D_built":True,"FM_and_DBG_require_fresh_normal_task_gates":True,
                    "five_controls_public_recovery_twelve_quality_Harbor_and_difficulty_pending":True,
                    "quality_or_difficulty_certified":False,"model_calls":0,"qualified":False,"task_count":0}
                result=write_new(output/"source_manifest.json",manifest)
                status="source_verified"
                write_new(attempt/"terminal.json",{"status":status,"finished_at":utcnow(),"manifest":result,"engine_calls":calls,
                    "elapsed_seconds":time.monotonic()-clock,"LO_calls":3,"model_calls":0,"task_count":0,"qualified":False})
                return result
    except BaseException as error:
        if attempt.is_dir() and not (attempt/"terminal.json").exists():
            write_new(attempt/"terminal.json",{"status":"failed","finished_at":utcnow(),"error_type":type(error).__name__,
                "error":str(error),"traceback":traceback.format_exc(),"engine_calls":calls,"all_partial_artifacts_preserved":True,
                "elapsed_seconds":time.monotonic()-clock,"model_calls":0,"task_count":0,"qualified":False})
        raise
    finally:
        try:
            if audit:
                audit.update_run(status=status,producer_active=False,finished_at=utcnow(),elapsed_seconds=time.monotonic()-clock)
                audit.export()
        finally:
            if server:server.stop()
            if audit:audit.db.close()
            lease.release()


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("spec","output","profile","prepared"):p.add_argument("--"+name,type=Path)
    p.add_argument("--allow-prototype",action="store_true")
    p.add_argument("--run",action="store_true")
    p.add_argument("--port",type=int,default=0)
    args=p.parse_args(argv)
    if args.prepared:
        require(args.spec is None and args.output is None and args.profile is None and not args.allow_prototype,
            "Prepared execution uses its exact frozen options")
        if args.run:answer=execute_prepared(args.prepared,port=args.port)
        else:
            validate_prepared(args.prepared);answer={"validated_preparation":str(args.prepared.resolve()),"LO_calls":0,"model_calls":0}
    else:
        require(args.spec is not None and args.output is not None,"--spec and fresh --output are required")
        answer=prepare(args.spec,args.output,profile=args.profile or DEFAULT_PROFILE,allow_prototype=args.allow_prototype)
        if args.run:answer=execute_prepared(args.output,port=args.port)
    print(json.dumps(answer,ensure_ascii=False),flush=True)
    return answer


if __name__=="__main__":main()
