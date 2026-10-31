#!/usr/bin/env python3
"""Own-family ten-call native engineering gate; default CLI only cold-prepares."""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import openpyxl
import yaml
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.workbook import independent_controls_candidate as candidate
from sheets_factory.workbook import independent_controls_oracle as oracle
from sheets_factory.workbook.thread_capped_resource_engine import ThreadCappedResourceLibreOfficeEngine, validate_capped_call
from sheets_factory.workbook.heterogeneous_contracts.validate import compare_typed_caches
from sheets_factory.workbook.linear_capital_portfolio.formula_identity import formula_signature
from sheets_factory.evaluation.streaming_verifier import compare_files

KIND = "prepared_independent_controls_shared_engineering"
TERMINAL_KIND = "independent_controls_actual_shared_engineering_validation"
VERSION = 1
PROFILE = ROOT / "config/runtime_profiles/entity_group_large_v2.yaml"
IMAGE = "sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043"
STAGES = ("goal1", "goal2", "FM_input1", "FM_input2", "DBG_input1", "DBG_input2", "equivalent", "FM_missed_root", "DBG_missed_root", "extra_change")
SUPPORT = ROOT / "scripts/build_heterogeneous_source.py"
SUPPORT_SHA256 = "0d8abfe960901da24c76fbdc3fbaaebb9bc37b973f6fa326904517ae495d7fba"
ABSENCE_SOURCE = ROOT / "scripts/validate_period_boundary_candidate_v2.py"
ABSENCE_SHA256 = "0b974c2d7b45ae8f9b844663a06f147c95570094f56e514db15b6b5661b99e48"
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def require(value, message):
    if not value: raise ValueError(message)


def now(): return datetime.now(timezone.utc).isoformat()


def reference(path):
    p = Path(path).absolute(); require(p == p.resolve() and p.is_file(), "Use a real regular file")
    return candidate.reference(p)


def checked(value):
    require(reference(value["path"]) == value, "Frozen reference changed"); return Path(value["path"])


def read(value): return json.loads((checked(value) if isinstance(value, dict) else Path(value)).read_text())


def write(path, value): return candidate.write_new(path, value)


def resource_support():
    require(reference(SUPPORT)["sha256"] == SUPPORT_SHA256, "Reviewed resource helper changed")
    spec = importlib.util.spec_from_file_location("_independent_controls_resource_support", SUPPORT)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def owned_absence(calls):
    """Use only the pinned pure absence function, without period admission code."""
    require(reference(ABSENCE_SOURCE)["sha256"] == ABSENCE_SHA256, "Reviewed owned-absence helper changed")
    tree = ast.parse(ABSENCE_SOURCE.read_bytes(), filename=str(ABSENCE_SOURCE))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "owned_absence"]
    require(len(functions) == 1, "One exact reviewed owned-absence function required")
    namespace = {"re": re, "subprocess": subprocess}
    exec(compile(ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[])), str(ABSENCE_SOURCE), "exec"), namespace)
    return namespace["owned_absence"](calls)


def recipes():
    from sheets_factory.workbook import resource_engine, thread_capped_resource_engine, engine
    from sheets_factory.workbook.heterogeneous_contracts import validate
    from sheets_factory.workbook.linear_capital_portfolio import formula_identity
    from sheets_factory.evaluation import streaming_verifier
    from sheets_factory.task_adapters import heterogeneous_formula_identity
    from sheets_factory.core import audit
    from sheets_factory.dashboard import server
    from sheets_factory import resume
    paths = [Path(__file__), ROOT / "tests/test_independent_controls_validation.py", PROFILE, SUPPORT, ABSENCE_SOURCE,
        ROOT / "src/sheets_factory/workbook/uno_recalculate.py"]
    paths += [Path(m.__file__) for m in (resource_engine, thread_capped_resource_engine, engine, validate, formula_identity, streaming_verifier, heterogeneous_formula_identity, audit, server, resume)]
    result = {str(p.resolve()): reference(p) for p in paths}
    result.update({v["path"]: v for v in candidate.recipes().values()})
    return result


def typed(value):
    if value is None or value == "": return ["empty", None]
    if type(value) is bool: return ["boolean", value]
    if isinstance(value, (date, datetime)): return ["date", value.isoformat()]
    if type(value) in (int, float, Decimal):
        number = Decimal(str(value)); require(number.is_finite(), "Finite workbook number required")
        return ["number", format(number.normalize(), "f") if number else "0"]
    require(type(value) is str, "Unsupported workbook value type")
    return ["text", value]


def money(value):
    require(type(value) in (int, float, Decimal), "A numeric target cannot be blank, text or Boolean")
    number = Decimal(str(value)); require(number.is_finite(), "Finite numeric target required")
    return number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _expectations(targets, ledger):
    lookup = {(r["entity"], r["operating"], r["financing"], r["year"]): r["values"] for r in ledger["rows"]}
    result = {}
    for target in targets:
        point = target["sheet"], target["cell"]
        require(point not in result and target["field"] in candidate.FIELDS, "Unique complete financial target required")
        result[point] = Decimal(lookup[target["entity"], target["operating"], target["financing"], target["year"]][target["field"]])
    return result


def _snapshot(path, points):
    book = openpyxl.load_workbook(path, data_only=False); literals = {}; formulas = {}
    try:
        for sheet in book:
            for cell in sheet._cells.values():
                point = sheet.title, cell.coordinate
                if cell.data_type == "f": formulas[point] = cell.value
                elif cell.value is not None and cell.value != "": literals[point] = typed(cell.value)
        require(set(formulas) == points and not (set(literals) & points), "Formula gold must contain precisely the complete target family")
        return {"sheetnames": book.sheetnames, "epoch": book.epoch.isoformat(), "literals": literals, "formulas": formulas}
    finally: book.close()


def context(manifest):
    m = read(manifest)
    require(m.get("kind") == "prepared_independent_controls_financial_candidate_pair" and m.get("version") == 1 and m.get("qualified") is False and m.get("actual_LO_model_solver_Harbor_network_calls") == 0, "Use the distinct cold synthetic control-family preparation")
    require(m.get("recipes") == candidate.recipes(), "Frozen synthetic financial/emitter recipe changed")
    for ref in m["recipes"].values(): checked(ref)
    public = candidate.validate(read(m["public_assumptions"]))
    targets = read(m["target_inventory"])["targets"]
    correct = _expectations(targets, oracle.compute(public))
    wrong = _expectations(targets, oracle.compute(public, couple_controls=True, double_count_new_debt=True))
    require(len(correct) == m["dimensions"]["financial_output_targets"] == len(targets), "Complete financial target dimensions changed")
    snapshot = _snapshot(checked(m["gold"]), set(correct))
    expected_formulas = {p: f for p, f in snapshot["formulas"].items()}
    require(expected_formulas == {(t["sheet"], t["cell"]): t["before"] for t in targets}, "Gold formula definitions differ from prospective target inventory")
    dbg_plan = read(m["plans"]["DBG"]); fm_plan = read(m["plans"]["FM"])
    require(dbg_plan["kind"] == fm_plan["kind"] == "independent_controls_candidate_view_plan" and dbg_plan["source"] == fm_plan["source"] == m["gold"], "Both genuine plans must bind this source")
    require(fm_plan["mode"] == "FM" and dbg_plan["mode"] == "DBG" and len(fm_plan["edits"]) == len(targets), "Full mode plans required")
    for edit in fm_plan["edits"]: require(edit["after"] is None and expected_formulas.get((edit["sheet"], edit["cell"])) == edit["before"], "FM must mask every and only financial target")
    require({(e["sheet"], e["cell"]) for e in fm_plan["edits"]} == set(correct), "No FM family or summary alias may be omitted")
    wrong_formulas = dict(expected_formulas)
    require(len({(e["sheet"], e["cell"]) for e in dbg_plan["edits"]}) == len(dbg_plan["edits"]), "Unique DBG roots required")
    for edit in dbg_plan["edits"]:
        point = edit["sheet"], edit["cell"]
        require(expected_formulas.get(point) == edit["before"] and edit["family"] in {"independent_financing_control", "enterprise_equity_bridge"}, "Prospective genuine fault family changed")
        wrong_formulas[point] = edit["after"]
    wanted = {(r["sheet"], r["cell"]): Decimal(r["expected"]["value"]) for r in read(m["expected_typed_targets"])["targets"]}
    require(wanted == correct, "Prepared expectations no longer equal the independent Decimal ledger")
    expected_d = {"FM": len(correct), "DBG": sum(money(a) != money(wrong[p]) for p, a in correct.items())}
    require(expected_d["DBG"] > 0, "Nonempty numeric DBG impact required")
    for mode in ("FM", "DBG"):
        material = m["materials"][mode]
        require(material["kind"] == "uncalculated_independent_controls_candidate_view" and material["mode"] == mode and material["qualified"] is False, "Own-family candidate material required")
        checked(material["public_instruction"]); checked(material["public_input"])
    return {"manifest": m, "public": public, "targets": targets, "correct": correct, "wrong": wrong,
        "snapshot": snapshot, "wrong_formulas": wrong_formulas, "expected_D": expected_d, "DBG_edits": dbg_plan["edits"]}


def audit_workbook(path, ctx, *, mode="goal", require_calculated=True, equivalent=None):
    expected = ctx["wrong"] if mode == "DBG" else ctx["correct"]
    wanted_formulas = {} if mode == "FM" else dict(ctx["wrong_formulas"] if mode == "DBG" else ctx["snapshot"]["formulas"])
    if equivalent: wanted_formulas.update(equivalent)
    formulas = openpyxl.load_workbook(path, data_only=False); values = openpyxl.load_workbook(path, data_only=True)
    problems = []; raw_numeric = []; errors = []; actual_formulas = {}; observed = {}
    try:
        require(formulas.sheetnames == values.sheetnames == ctx["snapshot"]["sheetnames"] and formulas.epoch.isoformat() == values.epoch.isoformat() == ctx["snapshot"]["epoch"], "Worksheet order or date epoch changed")
        for sheet in formulas:
            for cell in sheet._cells.values():
                if cell.data_type == "f": actual_formulas[sheet.title, cell.coordinate] = cell.value
                elif (sheet.title, cell.coordinate) not in expected and cell.value not in (None, ""):
                    if ctx["snapshot"]["literals"].get((sheet.title, cell.coordinate)) != typed(cell.value): problems.append({"sheet": sheet.title, "cell": cell.coordinate, "reason": "Provided definition changed"})
        require(set(actual_formulas) == set(wanted_formulas) and all(formula_signature(f) == formula_signature(wanted_formulas[p]) for p, f in actual_formulas.items()), "Complete financial formula definitions changed")
        for sheet in values:
            for cell in sheet._cells.values():
                if cell.data_type == "e": errors.append({"sheet": sheet.title, "cell": cell.coordinate, "error": str(cell.value)})
                if cell.value not in (None, ""): observed[sheet.title, cell.coordinate] = typed(cell.value)
        for point, wanted in ctx["snapshot"]["literals"].items():
            if observed.get(point) != wanted: problems.append({"sheet": point[0], "cell": point[1], "reason": "Provided input, policy or label changed"})
        allowed = set(ctx["snapshot"]["literals"]) | (set() if mode == "FM" else set(expected))
        if require_calculated or mode == "FM":
            if set(observed) != allowed: problems.append({"reason": "Complete typed nonempty scope changed", "missing": len(allowed - set(observed)), "extra": len(set(observed) - allowed)})
        for point, wanted in expected.items():
            actual = values[point[0]][point[1]].value
            if mode == "FM": matches = actual in (None, "")
            elif not require_calculated: continue
            else:
                matches = type(actual) in (int, float) and money(actual) == money(wanted)
                if matches and Decimal(str(actual)) != wanted: raw_numeric.append({"sheet": point[0], "cell": point[1], "expected": str(wanted), "actual": str(actual)})
            if not matches: problems.append({"sheet": point[0], "cell": point[1], "reason": "Numeric target differs" if mode != "FM" else "FM target remains nonblank", "expected": None if mode == "FM" else str(wanted), "actual": typed(actual)})
        return {"kind": "independent_controls_complete_decimal_typed_cache_audit", "version": 1, "passed": not problems and not errors,
            "workbook": reference(path), "mode": mode, "financial_targets_checked": len(expected), "public_literals_checked": len(ctx["snapshot"]["literals"]),
            "formula_count": len(actual_formulas), "numeric_equality": "typed_decimal_quantize_0.01_ROUND_HALF_UP", "actual_numeric_caches_required": require_calculated,
            "uncalculated_gold_is_not_numeric_proof": True, "mismatches": problems, "native_errors": errors,
            "raw_numeric_differences_after_primary_match": raw_numeric, "qualified": False}
    finally: formulas.close(); values.close()


def _sheet_parts(archive):
    wb = ET.fromstring(archive.read("xl/workbook.xml")); rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
    result = {}
    for sheet in wb.find("{" + NS + "}sheets"):
        part = rels[sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")]
        result[sheet.get("name")] = part.lstrip("/") if part.startswith("/") else "xl/" + part
    return result


def _patch_cell(raw, address, change):
    kind, value = change
    pattern = rb'<(?P<pre>(?:[A-Za-z_][\w.-]*:)?)c\b(?=[^>]*\br="' + address.encode() + rb'")[^>]*?(?:/>|>.*?</(?P=pre)c>)'
    matches = list(re.finditer(pattern, raw, re.S)); require(len(matches) == 1, "Control cell must exist exactly once")
    match = matches[0]; prefix = match.group("pre"); opening = match.group()[:match.group().index(b">") + 1].replace(b"/>", b">")
    opening = re.sub(rb'\s+t="[^"]*"', b"", opening)
    if kind == "formula": body = b"<" + prefix + b"f>" + escape(value.lstrip("=")).encode() + b"</" + prefix + b"f><" + prefix + b"v></" + prefix + b"v>"
    elif kind == "blank": body = b""
    elif kind == "text": opening = opening[:-1] + b' t="inlineStr">'; body = b"<" + prefix + b"is><" + prefix + b"t>" + escape(value).encode() + b"</" + prefix + b"t></" + prefix + b"is>"
    else: raise ValueError("Unsupported control edit")
    return raw[:match.start()] + opening + body + b"</" + prefix + b"c>" + raw[match.end():]


def patch_cells(source, destination, changes):
    with zipfile.ZipFile(source) as source_zip:
        sheets = _sheet_parts(source_zip)
        parts = {}
        for (sheet, cell), value in changes.items(): parts.setdefault(sheets[sheet], {})[cell] = value
        touched = []; found = set()
        with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED) as result:
            for member in source_zip.infolist():
                before = raw = source_zip.read(member.filename)
                for address, change in parts.get(member.filename, {}).items():
                    raw = _patch_cell(raw, address, change); found.add((member.filename, address))
                if raw != before: touched.append(member.filename)
                result.writestr(member, raw)
        require(found == {(part, cell) for part, entries in parts.items() for cell in entries}, "Every control edit must be applied")
    return {"source": reference(source), "output": reference(destination), "changed_members": touched,
        "exact_cell_changes": [{"sheet": s, "cell": c, "kind": v[0], "value": v[1]} for (s, c), v in changes.items()], "all_other_member_and_unedited_cell_bytes_preserved": True}


def _control_definitions(ctx):
    default = next(t for t in ctx["targets"] if t["sheet"] == "Crossed plans" and t["entity"] == ctx["public"]["entities"][0]["id"] and t["operating"] == ctx["public"]["default_operating"] and t["financing"] == ctx["public"]["default_financing"] and t["year"] == ctx["public"]["first_year"] and t["field"] == "residual_equity")
    root = next(e for e in ctx["DBG_edits"] if e["family"] == "independent_financing_control" and e["cell"] == "L" + re.search(r"[0-9]+", default["cell"])[0])
    point = default["sheet"], default["cell"]
    require(money(ctx["correct"][root["sheet"], root["cell"]]) != money(ctx["wrong"][root["sheet"], root["cell"]]), "Missed-control root must have active mixed-state numeric impact")
    return {"equivalent": {point: ("formula", "=0+" + default["before"].lstrip("="))}, "FM_missed_root": {point: ("blank", None)}, "DBG_missed_root": {(root["sheet"], root["cell"]): ("formula", root["after"])}, "extra_change": {("Read me", "A1"): ("text", "Independent scenario cash-flow planning [control]")}}


def prepare(candidate_manifest, output):
    output = Path(output).absolute(); require(output == output.resolve() and not output.exists(), "Use a fresh engineering directory")
    ctx = context(candidate_manifest); m = ctx["manifest"]
    profile = yaml.safe_load(PROFILE.read_text())
    require(profile["image"]["id"] == IMAGE and profile["docker_resources"]["source"] == {"cpus": 2, "memory_bytes": 34359738368, "pids_limit": 256} and profile["timeouts"]["workbook_file_seconds"] == 600, "Pinned 2CPU32GiB/P256/600s source profile required")
    for mode, source in (("goal", m["gold"]), ("FM", m["materials"]["FM"]["public_input"]), ("DBG", m["materials"]["DBG"]["public_input"])):
        require(audit_workbook(checked(source), ctx, mode=mode, require_calculated=False)["passed"], "Cold formula/provided-input identity failed")
    output.mkdir(parents=True); planned = output / "planned"; planned.mkdir()
    sources = {"goal": m["gold"], "FM_input": m["materials"]["FM"]["public_input"], "DBG_input": m["materials"]["DBG"]["public_input"]}
    for name, source in sources.items(): shutil.copyfile(checked(source), planned / (name + ".xlsx"))
    cases = _control_definitions(ctx); point, (_, equivalent) = next(iter(cases["equivalent"].items()))
    edits = [patch_cells(planned / "goal.xlsx", planned / (name + ".xlsx"), changes) for name, changes in cases.items()]
    inputs = {name: reference(planned / (name + ".xlsx")) for name in [*sources, *cases]}
    chain = {name: inputs["goal"] if name == "goal1" else "goal1" if name == "goal2" else inputs[name[:-1]] if name in {"FM_input1", "DBG_input1"} else name[:-1] + "1" if name in {"FM_input2", "DBG_input2"} else inputs[name] for name in STAGES}
    return write(output / "preparation.json", {"kind": KIND, "version": VERSION, "candidate_manifest": reference(candidate_manifest["path"] if isinstance(candidate_manifest, dict) else candidate_manifest),
        "runtime_profile": reference(PROFILE), "runtime_profile_value": profile, "recipe": recipes(), "mode_order": ["financial_modeling", "debugging"],
        "stage_order": list(STAGES), "stage_inputs": chain, "planned_inputs": inputs, "control_edits": edits, "required_actual_LO_calls": 10,
        "expected_FM_D": ctx["expected_D"]["FM"], "expected_DBG_D": ctx["expected_D"]["DBG"], "all_financial_targets": len(ctx["correct"]),
        "equivalent_formula": {"sheet": point[0], "cell": point[1], "formula": equivalent},
        "shared_goal_equivalent_extra_are_explicit": True, "all_mode_and_control_plans_frozen_before_first_actual_call": True,
        "numeric_contract": "typed_decimal_2dp_ROUND_HALF_UP_money_all_targets; provided inputs/policies exact; full-union stability unquantized",
        "uncalculated_sources_are_not_numeric_proof": True, "actual_LO_calls": 0, "model_calls": 0, "solver_calls": 0, "Harbor_calls": 0, "qualified": False})


def validate_prepared(output):
    f = read(Path(output) / "preparation.json")
    require(f.get("kind") == KIND and f.get("version") == VERSION and f.get("recipe") == recipes() and f.get("stage_order") == list(STAGES) and f.get("required_actual_LO_calls") == 10, "Own-family preparation/recipe/stage order changed")
    checked(f["runtime_profile"]); ctx = context(f["candidate_manifest"])
    require(f["runtime_profile"] == reference(PROFILE) and f["runtime_profile_value"] == yaml.safe_load(PROFILE.read_text()), "Runtime profile changed")
    require(f["expected_FM_D"] == ctx["expected_D"]["FM"] and f["expected_DBG_D"] == ctx["expected_D"]["DBG"] and f["all_financial_targets"] == len(ctx["correct"]), "Independent complete expected D changed")
    require(set(f["planned_inputs"]) == {"goal", "FM_input", "DBG_input", "equivalent", "FM_missed_root", "DBG_missed_root", "extra_change"}
        and f.get("mode_order") == ["financial_modeling", "debugging"] and f.get("qualified") is False
        and f.get("actual_LO_calls") == f.get("model_calls") == f.get("solver_calls") == f.get("Harbor_calls") == 0
        and f.get("all_mode_and_control_plans_frozen_before_first_actual_call") is True, "Complete prospective family and zero-call contract required")
    for source in f["planned_inputs"].values(): checked(source)
    expected_chain = {name: f["planned_inputs"]["goal"] if name == "goal1" else "goal1" if name == "goal2" else f["planned_inputs"][name[:-1]] if name in {"FM_input1", "DBG_input1"} else name[:-1] + "1" if name in {"FM_input2", "DBG_input2"} else f["planned_inputs"][name] for name in STAGES}
    require(f["stage_inputs"] == expected_chain, "Frozen stage chain differs")
    originals = {"goal": ctx["manifest"]["gold"], **{mode + "_input": ctx["manifest"]["materials"][mode]["public_input"] for mode in ("FM", "DBG")}}
    require(all((source["sha256"], source["bytes"]) == (f["planned_inputs"][name]["sha256"], f["planned_inputs"][name]["bytes"]) for name, source in originals.items()), "Prospective source/input copy identity changed")
    require(len(f["control_edits"]) == 4 and {r["output"]["path"] for r in f["control_edits"]} == {f["planned_inputs"][name]["path"] for name in ("equivalent", "FM_missed_root", "DBG_missed_root", "extra_change")}, "Four frozen shared/per-mode control plans required")
    for control in f["control_edits"]:
        checked(control["source"]); checked(control["output"])
        require(control["source"] == f["planned_inputs"]["goal"] and len(control["exact_cell_changes"]) == len(control["changed_members"]) == 1 and control["all_other_member_and_unedited_cell_bytes_preserved"] is True, "Cold control edit closure changed")
    for name, changes in _control_definitions(ctx).items():
        control = next(r for r in f["control_edits"] if r["output"] == f["planned_inputs"][name])
        require(control["exact_cell_changes"] == [{"sheet": s, "cell": c, "kind": v[0], "value": v[1]} for (s, c), v in changes.items()], "Exact active control definition changed")
        with zipfile.ZipFile(checked(control["source"])) as source, zipfile.ZipFile(checked(control["output"])) as destination:
            require(source.namelist() == destination.namelist(), "Control member inventory changed")
            parts = _sheet_parts(source); touched = []
            for member in source.namelist():
                before = wanted = source.read(member)
                for (sheet, cell), change in changes.items():
                    if parts[sheet] == member: wanted = _patch_cell(wanted, cell, change)
                require(destination.read(member) == wanted, "Control must preserve every other member and cell byte")
                if before != wanted: touched.append(member)
            require(control["changed_members"] == touched, "Exact control member proof changed")
    point, (_, formula) = next(iter(_control_definitions(ctx)["equivalent"].items()))
    require(f["equivalent_formula"] == {"sheet": point[0], "cell": point[1], "formula": formula}, "Equivalent-control binding changed")
    return f


def validate_call(call, runtime, frozen): return validate_capped_call(call, runtime, frozen, resource_validator=resource_support().validate_actual_call)


@contextmanager
def stage(audit, name):
    started = time.monotonic(); row = audit.record("nodes", {"node": name, "status": "running", "started_at": now()}); audit.update_run(active_stage=name); audit.export(); status = "failed"
    try: yield; status = "completed"
    finally: audit.update_record("nodes", row, {"status": status, "finished_at": now(), "duration_ms": 1000 * (time.monotonic() - started)}); audit.export()


def _actual_audit(name, path, ctx, frozen):
    mode = "DBG" if name.startswith("DBG_input") else "FM" if name.startswith("FM_input") else "goal"
    equivalent = frozen["equivalent_formula"] if name == "equivalent" else None
    return audit_workbook(path, ctx, mode=mode, equivalent={(equivalent["sheet"], equivalent["cell"]): equivalent["formula"]} if equivalent else None)


def _stability(results, second):
    first = {"goal2": "goal1", "FM_input2": "FM_input1", "DBG_input2": "DBG_input1"}[second]
    comparison = compare_typed_caches(results[first]["path"], results[second]["path"])
    require(comparison["passed"] and comparison["typed_value_mismatches"] == 0, "Complete unquantized typed fixed point failed")
    return {"left": results[first], "right": results[second], "comparison": comparison}


def _mode_proofs(output, frozen, results):
    modes = {}
    for mode, prefix in (("financial_modeling", "FM"), ("debugging", "DBG")):
        original, goal = results[prefix + "_input2"], results["goal2"]; scores = {}; proofs = {}
        for control, key in (("oracle", "goal2"), ("nop", prefix + "_input2"), ("equivalent", "equivalent"), ("missed_root", prefix + "_missed_root"), ("extra_change", "extra_change")):
            comparison = compare_files(original["path"], goal["path"], results[key]["path"])
            require(comparison["expected_change_count"] == frozen["expected_" + prefix + "_D"], "Complete actual D differs from independent Decimal prediction")
            proofs[control] = write(output / (prefix + "_" + control + "_full_D.json"), {"input": original, "goal": goal, "output": results[key], "comparison": comparison}); scores[control] = comparison["reward"]
        require(scores == {"oracle": 1, "nop": 0, "equivalent": 1, "missed_root": 0, "extra_change": 0}, "Actual five-control pattern failed")
        modes[mode] = {"controls": scores, "full_D_controls": proofs, "complete_D_count": frozen["expected_" + prefix + "_D"], "input": original, "goal": goal}
    return modes


def execute_prepared(output):
    output = Path(output).absolute(); frozen = validate_prepared(output)
    markers = ("attempt.json", "started.json", "terminal.json", "failure.json")
    require(not any((output / name).exists() for name in markers), "No retries; preserve the original attempt")
    lease = ProducerLease(output).acquire(); audit = server = heartbeat = engine = None; calls = []; results = {}; records = {}; stop = threading.Event(); clock = time.monotonic(); status = "failed"; failure = None
    # Recheck under the exclusive lease, including a process that won and ended
    # between the initial check and acquisition. Never overwrite its receipts.
    if any((output / name).exists() for name in markers):
        lease.release(); raise ValueError("No retries; preserve the original attempt")
    old_temp = os.environ.get("TMPDIR"); old_cache = tempfile.tempdir
    try:
        records["attempt"] = write(output / "attempt.json", {"at": now(), "preparation": reference(output / "preparation.json"), "pid": os.getpid(), "retry": 0})
        temporary = output / "temporary"; temporary.mkdir(); os.environ["TMPDIR"] = str(temporary); tempfile.tempdir = str(temporary)
        audit = AuditStore(output / "audit", {"id": output.name, "name": "Independent-control shared engineering", "status": "running", "target_count": 0, "qualified": False, "producer_pid": os.getpid()})
        server = DashboardServer(audit.snapshot, audit.events, host="127.0.0.1", port=0); url = server.start()
        records["started"] = write(output / "started.json", {"at": now(), "preparation": reference(output / "preparation.json"), "dashboard_url": url, "pid": os.getpid(), "retry": 0})
        print(json.dumps({"dashboard_url": url, "pid": os.getpid(), "started": records["started"]}), flush=True)
        def pulse():
            while not stop.wait(15): audit.update_run(elapsed_seconds=time.monotonic() - clock, actual_LO_calls_started=len(calls), actual_LO_calls_completed=sum(c["completed"] for c in calls)); audit.export()
        heartbeat = threading.Thread(target=pulse, daemon=True); heartbeat.start(); ctx = context(frozen["candidate_manifest"])
        engine = ThreadCappedResourceLibreOfficeEngine(ROOT, frozen["runtime_profile"]["path"], role="source", receipt_directory=output / "engine_resources"); engine.ensure_image()
        for index, name in enumerate(STAGES, 1):
            source = frozen["stage_inputs"][name]; source = Path(results[source]["path"]) if isinstance(source, str) else checked(source)
            call = {"index": index, "role": name, "input": reference(source), "started_at": now(), "completed": False}; calls.append(call); call["started_receipt"] = write(output / (name + "_started.json"), dict(call))
            with stage(audit, "actual_" + name):
                try:
                    tick = time.monotonic(); actual = Path(engine.recalculate(source, output / (name + ".xlsx"))); call.update(output=reference(actual), completed=True, elapsed_seconds=time.monotonic() - tick)
                    history = engine.metadata()["actual_resource_receipts"]; require(len(history) == index, "No extra or missing native call permitted"); call["actual_resource_evidence"] = validate_call(call, history[-1], frozen)
                finally: call["finished_at"] = now(); call["terminal_receipt"] = write(output / (name + "_terminal.json"), dict(call))
            results[name] = call["output"]
            print(json.dumps({"actual_call_completed": name, "completed_calls": index, "output_sha256": call["output"]["sha256"]}), flush=True)
            if name in {"goal1", "goal2", "FM_input1", "FM_input2", "DBG_input1", "DBG_input2", "equivalent"}:
                report = _actual_audit(name, actual, ctx, frozen); records[name + "_audit"] = write(output / (name + "_audit.json"), report); require(report["passed"], "Complete independent Decimal/provided-input/formula audit failed")
            if name in {"goal2", "FM_input2", "DBG_input2"}: records[name + "_stability"] = write(output / (name + "_stability.json"), _stability(results, name))
        records["modes"] = _mode_proofs(output, frozen, results)
        records["cleanup"] = write(output / "owned_containers_absence.json", owned_absence(calls)); cleanup = read(records["cleanup"])
        require(cleanup["all_owned_containers_absent"] and cleanup["daemon_reachable"], "Owned cleanup is incomplete or unknown")
        require(validate_prepared(output) == frozen and len(calls) == 10, "Recipe changed or native call count differs"); status = "passed"
    except BaseException as error:
        failure = {"type": type(error).__name__, "message": str(error)}; records["failure"] = write(output / "failure.json", failure)
    finally:
        if status != "passed" and engine is not None and calls:
            try:
                owned = []
                for runtime in engine.metadata()["actual_resource_receipts"]:
                    actual = read(runtime); require(any(actual.get("source") == c["input"] for c in calls), "Cleanup receipt is not an owned call")
                    if actual.get("container_id"): owned.append({"actual_resource_evidence": {"container_id": actual["container_id"]}})
                if owned: records["failure_cleanup"] = write(output / "owned_containers_absence_after_failure.json", owned_absence(owned))
            except Exception as error: records["failure_cleanup"] = write(output / "owned_cleanup_unknown.json", {"passed": False, "state": "unknown", "error_type": type(error).__name__})
        stop.set()
        if heartbeat: heartbeat.join(timeout=1)
        if audit: audit.update_run(status=status, producer_active=False, elapsed_seconds=time.monotonic() - clock); audit.export()
        if server: server.stop()
        if audit: audit.db.close()
        lease.release()
        if old_temp is None: os.environ.pop("TMPDIR", None)
        else: os.environ["TMPDIR"] = old_temp
        tempfile.tempdir = old_cache
    terminal = write(output / "terminal.json", {"kind": TERMINAL_KIND, "version": VERSION, "passed": status == "passed", "failure": failure,
        "preparation": reference(output / "preparation.json"), "actual_calls": calls, "records": records, "actual_LO_calls_started": len(calls), "actual_LO_calls_completed": sum(c["completed"] for c in calls),
        "elapsed_seconds": time.monotonic() - clock, "model_calls": 0, "solver_calls": 0, "Harbor_calls": 0, "task_count": 0, "qualified": False, "normal_all12_QA_passed": False, "difficulty_claimed": False, "retry": 0})
    if status != "passed": raise RuntimeError("Engineering failed; preserve terminal.json without retry")
    return terminal


def validate_completed(value):
    terminal = read(value)
    require(terminal.get("kind") == TERMINAL_KIND and terminal.get("version") == VERSION and terminal.get("passed") is True and terminal.get("failure") is None
        and terminal.get("actual_LO_calls_started") == terminal.get("actual_LO_calls_completed") == 10 and terminal.get("qualified") is False and terminal.get("normal_all12_QA_passed") is False and terminal.get("difficulty_claimed") is False
        and terminal.get("model_calls") == terminal.get("solver_calls") == terminal.get("Harbor_calls") == terminal.get("retry") == 0, "A genuine own-family complete ten-call engineering terminal is required")
    output = checked(terminal["preparation"]).parent; frozen = validate_prepared(output); ctx = context(frozen["candidate_manifest"]); results = {}; calls = terminal["actual_calls"]
    attempt, started = read(terminal["records"]["attempt"]), read(terminal["records"]["started"])
    require(attempt["preparation"] == started["preparation"] == terminal["preparation"] and attempt["pid"] == started["pid"]
        and attempt["retry"] == started["retry"] == 0 and started["dashboard_url"].startswith("http://127.0.0.1:"), "Durable attempt/UI binding changed")
    require(len(calls) == 10 and len({c.get("actual_resource_evidence", {}).get("container_id") for c in calls}) == 10, "Complete original distinct-owned actual call inventory required")
    for index, (name, call) in enumerate(zip(STAGES, calls, strict=True), 1):
        source = frozen["stage_inputs"][name]; source = results[source] if isinstance(source, str) else source
        require(call["index"] == index and call["role"] == name and call["input"] == source and call["completed"] is True, "Actual input/output stage chain changed")
        checked(call["input"]); checked(call["output"])
        require(read(call["started_receipt"]) == {k: call[k] for k in ("index", "role", "input", "started_at", "completed")} | {"completed": False}, "Original call start changed")
        require(read(call["terminal_receipt"]) == {k: v for k, v in call.items() if k != "terminal_receipt"}, "Original call terminal changed")
        require(validate_call(call, call["actual_resource_evidence"]["terminal"], frozen) == call["actual_resource_evidence"], "Genuine resource/cap evidence changed")
        results[name] = call["output"]
        if name in {"goal1", "goal2", "FM_input1", "FM_input2", "DBG_input1", "DBG_input2", "equivalent"}:
            current = _actual_audit(name, call["output"]["path"], ctx, frozen)
            require(current["passed"] and read(terminal["records"][name + "_audit"]) == current, "Independent full financial/provided-input audit changed")
        if name in {"goal2", "FM_input2", "DBG_input2"}: require(read(terminal["records"][name + "_stability"]) == _stability(results, name), "Complete typed stability evidence changed")
    for mode, prefix in (("financial_modeling", "FM"), ("debugging", "DBG")):
        saved_mode = terminal["records"]["modes"][mode]; original, goal = results[prefix + "_input2"], results["goal2"]; scores = {}
        require(saved_mode["input"] == original and saved_mode["goal"] == goal, "Mode proof binds a different pair")
        for control, key in (("oracle", "goal2"), ("nop", prefix + "_input2"), ("equivalent", "equivalent"), ("missed_root", prefix + "_missed_root"), ("extra_change", "extra_change")):
            comparison = compare_files(original["path"], goal["path"], results[key]["path"])
            require(comparison["expected_change_count"] == frozen["expected_" + prefix + "_D"] and read(saved_mode["full_D_controls"][control]) == {"input": original, "goal": goal, "output": results[key], "comparison": comparison}, "Complete actual D/control evidence changed")
            scores[control] = comparison["reward"]
        require(saved_mode["complete_D_count"] == frozen["expected_" + prefix + "_D"] and scores == saved_mode["controls"] == {"oracle": 1, "nop": 0, "equivalent": 1, "missed_root": 0, "extra_change": 0}, "Five-control proof incomplete")
    cleanup = read(terminal["records"]["cleanup"])
    require(cleanup["all_owned_containers_absent"] and cleanup["daemon_reachable"] and len(cleanup["owned"]) == 10 and {r["full_id"] for r in cleanup["owned"]} == {c["actual_resource_evidence"]["container_id"] for c in calls} and all(r["absent"] for r in cleanup["owned"]), "Cleanup must cover exactly the ten full owned IDs; unknown is not pass")
    return terminal


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--candidate", type=Path); parser.add_argument("--output", type=Path); parser.add_argument("--prepared", type=Path); parser.add_argument("--run", action="store_true"); parser.add_argument("--completed", type=Path); args = parser.parse_args(argv)
    if args.completed:
        require(args.candidate is args.output is args.prepared is None and not args.run, "Cold completed validation cannot execute services"); result = validate_completed(args.completed)
    elif args.prepared:
        require(args.candidate is args.output is None, "Keep the frozen preparation"); result = execute_prepared(args.prepared) if args.run else validate_prepared(args.prepared)
    else:
        require(args.candidate is not None and args.output is not None, "Supply genuine candidate and fresh engineering output")
        require(not args.run, "Prepare and review before a separate explicit --prepared --run")
        result = prepare(args.candidate, args.output)
    print(json.dumps(result)); return 0


if __name__ == "__main__": raise SystemExit(main())
