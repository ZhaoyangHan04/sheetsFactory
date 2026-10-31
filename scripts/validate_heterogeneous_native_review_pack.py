#!/usr/bin/env python3
"""Bounded native equivalence experiment for an emitted eight-business pack.

Numeric primary equivalence uses the taskbook's two-decimal ROUND_HALF_UP rule.
Raw decimal differences are separately retained. This is an engineering check,
not a whole-workbook financial certificate or task/source admission.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time as daytime
from decimal import Decimal, localcontext
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import traceback
from uuid import uuid4
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from openpyxl.styles.numbers import BUILTIN_FORMATS, is_date_format
from openpyxl.utils.datetime import CALENDAR_MAC_1904, CALENDAR_WINDOWS_1900, from_excel
from sheets_factory.core.audit import AuditStore, utcnow
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.workbook import heterogeneous_native_merge as merge
from sheets_factory.workbook.compare import normalize_value
from sheets_factory.workbook.resource_engine import load_runtime_profile
from sheets_factory.workbook.thread_capped_resource_engine import ThreadCappedResourceLibreOfficeEngine, validate_capped_call

KIND = "heterogeneous_native_review_pack_equivalence_engineering"
PREPARED_KIND = "prepared_" + KIND
VERSION = 1
PROFILE = ROOT / "config/runtime_profiles/entity_group_large_v2.yaml"
IMAGE = "sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043"
COMPOSER_SHA256 = "38bf2e1ad2f961af08e8f9138094c88c2b14dde0d216f4c5eaced3433b1fc701"
CONTRACT = {
    "version": 1,
    "numeric_primary": "Every numeric cell: Decimal ROUND_HALF_UP to0.01; negative rounded zero becomes0.00, matching taskbook normalize_value.",
    "numeric_raw_diagnostics": "Retain every exact Decimal inequality; a raw-only difference does not fail primary equivalence.",
    "date_time_text_boolean_error_primary": "Exact taskbook semantic values; datetime/time at millisecond resolution; each workbook's epoch resolves numeric date serials.",
    "empty_primary": "Missing cell, no cached value, and empty text normalize to the taskbook empty value; this is explicit semantic normalization, not raw XML equality.",
    "formula_identity": "Every original formula stays a formula at the mapped coordinate; parsed RANGE/FUNC tokens may differ only by case and sheet quoting after declared namespace mapping.",
    "literal_identity": "Every literal stays literal; compare its complete primary typed value. Numeric raw equality is reported separately.",
    "scope": "Full sparse cell union over all50sheets, no truncation; all12 fixed source errors must remain exactly at their mapped coordinates, and no new errors are accepted.",
    "date_normalization": "Only the three composer-declared NYU date caches change serial by+1462; ISO calendar meaning must match all original donors.",
    "sequence": "At most3externalLO calls: first complete equivalence PASS gates second; second complete equivalence/stability PASS gates third. Failure stops; no retries.",
    "financial_scope": "421 selected legacy source-address identities and112 separateNYU main-module identities are partial historical audits, not a4430formula financial certificate.",
}
EMPTY = {"type": "empty", "value": ""}


def require(value, message):
    if not value:
        raise ValueError(message)


def reference(path):
    return support().reference(path)


def checked(ref):
    return support().checked(ref)


def read(ref):
    return support().read(ref)


def write(path, value):
    return support().write_new(path, value)


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


_SUPPORT = None
_COMPOSER_DRIVER = None


def support():
    global _SUPPORT
    if _SUPPORT is None:
        _SUPPORT = module(ROOT / "scripts/build_heterogeneous_source.py", "_heterogeneous_review_pack_resource_support")
    return _SUPPORT


def composer_driver():
    global _COMPOSER_DRIVER
    require(merge.file_ref(merge.__file__)["sha256"] == COMPOSER_SHA256, "Frozen composer changed")
    if _COMPOSER_DRIVER is None:
        _COMPOSER_DRIVER = module(ROOT / "scripts/prepare_heterogeneous_native_review_pack.py", "_heterogeneous_review_pack_frozen_composer_driver")
    return _COMPOSER_DRIVER


def recipes():
    paths = [Path(__file__), ROOT / "tests/test_heterogeneous_native_review_pack_validation.py", ROOT / "docs/heterogeneous_native_review_pack.md", ROOT / "scripts/build_heterogeneous_source.py", ROOT / "scripts/prepare_heterogeneous_native_review_pack.py"]
    paths += [ROOT / "src/sheets_factory" / name for name in ("workbook/heterogeneous_native_merge.py", "workbook/compare.py", "workbook/resource_engine.py", "workbook/thread_capped_resource_engine.py", "workbook/engine.py", "workbook/uno_recalculate.py", "core/audit.py", "dashboard/server.py", "resume.py")]
    return {str(p.relative_to(ROOT)): reference(p) for p in paths}


def _texts(node):
    if node is None:
        return ""
    # Rich strings' phonetic annotations are metadata, not the displayed text.
    if node.tag.rsplit("}", 1)[-1] in {"si", "is"}:
        result = []
        for child in node:
            local = child.tag.rsplit("}", 1)[-1]
            if local == "t":
                result.append(child.text or "")
            elif local == "r":
                result.extend(t.text or "" for t in child.findall("{*}t"))
        return "".join(result)
    return node.text or ""


def _primary(value, kind):
    if kind == "number":
        number = Decimal(value)
        require(number.is_finite(), "Nonfinite numeric cache")
        result = normalize_value(number)
    elif kind in {"datetime", "time"}:
        result = (kind, value)
    elif kind == "boolean":
        result = normalize_value(value)
    elif kind == "error":
        result = normalize_value(value, "e")
    else:
        result = normalize_value(value)
    return {"type": result[0], "value": result[1]}


def snapshot(path):
    """Read complete cached values from OOXML without executing the workbook."""
    path = Path(path)
    with ZipFile(path) as z:
        names = z.namelist()
        require(len(set(names)) == len(names), "Duplicate ZIP member")
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        props = workbook.find("{*}workbookPr")
        mac = props is not None and props.get("date1904", "false") in {"true", "1"}
        epoch = CALENDAR_MAC_1904 if mac else CALENDAR_WINDOWS_1900
        rels = {r.get("Id"): r for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        strings = [_texts(n) for n in ET.fromstring(z.read("xl/sharedStrings.xml"))] if "xl/sharedStrings.xml" in names else []
        styles = ET.fromstring(z.read("xl/styles.xml"))
        formats = dict(BUILTIN_FORMATS)
        for n in styles.findall("{*}numFmts/{*}numFmt"):
            formats[int(n.get("numFmtId"))] = n.get("formatCode")
        xfs = list(styles.find("{*}cellXfs"))
        sheets = []
        cells = {}
        objects = {"comments": [], "chart_formula_references": [], "images": []}
        for descriptor in workbook.find("{*}sheets"):
            title = descriptor.get("name");sheets.append(title);cells[title] = {}
            rel = rels[descriptor.get("{" + merge.R + "}id")]
            part = merge._resolve("xl/workbook.xml", rel.get("Target"))
            tree = ET.fromstring(z.read(part))
            for c in tree.findall("{*}sheetData/{*}row/{*}c"):
                address = c.get("r");require(address not in cells[title], "Duplicate physical cell")
                t = c.get("t", "n");v = c.find("{*}v");formula = c.find("{*}f")
                require(formula is None or formula.get("t", "normal") in {"normal"}, "Native output introduced shared/array/dataTable formulas")
                style = int(c.get("s", "0"));require(style < len(xfs), "Invalid cell style")
                raw = None if v is None else (v.text or "")
                if t == "s" and raw not in {None, ""}:
                    value = strings[int(raw)];kind = "text"
                elif t == "inlineStr":
                    value = _texts(c.find("{*}is"));kind = "text"
                elif t == "str":
                    value = raw or "";kind = "text"
                elif t == "e":
                    require(raw not in {None, ""}, "Error cache has no error code")
                    value = raw;kind = "error"
                elif t == "b":
                    require(raw in {"0", "1"}, "Invalid Boolean cache")
                    value = raw == "1";kind = "boolean"
                elif t == "d":
                    value = datetime.fromisoformat(raw.replace("Z", "+00:00")) if "T" in raw else datetime.combine(date.fromisoformat(raw), daytime())
                    value = normalize_value(value)[1];kind = "datetime"
                elif raw not in {None, ""}:
                    require(t in {"n", ""}, "Unknown numeric cache type: " + t)
                    require(Decimal(raw).is_finite(), "Nonfinite native number")
                    if is_date_format(formats.get(int(xfs[style].get("numFmtId", "0")), "")):
                        converted = from_excel(float(raw), epoch)
                        primary = normalize_value(converted)
                        require(primary[0] in {"datetime", "time", "duration"}, "Unknown date/time semantic type")
                        value = primary[1];kind = primary[0]
                    else:
                        value = raw;kind = "number"
                else:
                    value = "";kind = "empty"
                primary = _primary(value, kind)
                cells[title][address] = {"primary": primary, "raw_numeric_text": raw if kind == "number" else None, "formula": None if formula is None else formula.text or "", "is_formula": formula is not None}
        for part in names:
            if re.search(r"(?:/comments\d+\.xml|/comments/comment\d+\.xml)$", part):
                tree = ET.fromstring(z.read(part))
                objects["comments"].extend({"part": part, "cell": n.get("ref"), "text": "".join(n.itertext())} for n in tree.findall("{*}commentList/{*}comment"))
            if "/charts/" in part and part.endswith(".xml") and "/_rels/" not in part:
                tree = ET.fromstring(z.read(part))
                objects["chart_formula_references"].extend(n.text or "" for n in tree.findall(".//{" + merge.CHART + "}f"))
            if "/media/" in part:
                b = z.read(part);objects["images"].append({"part": part, "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)})
    return {"kind": "complete_native_review_pack_typed_snapshot", "version": 1, "workbook": reference(path), "sheets": sheets, "date1904": mac, "cells": cells, "physical_cell_count": sum(map(len, cells.values())), "physical_formula_count": sum(c["is_formula"] for row in cells.values() for c in row.values()), "object_inventory_diagnostic_only": objects, "calculation_executed_by_snapshot": False}


def expected_from_donors(config):
    sheets = []
    cells = {}
    refs = []
    used = set()
    for spec in config["donors"]:
        donor = merge._load(spec, used)
        original = snapshot(checked(spec["workbook"]))
        refs.append(spec["workbook"])
        for old in donor.sheets:
            new = donor.sheet_map[old];sheets.append(new);cells[new] = {}
            for address, value in original["cells"][old].items():
                row = dict(value)
                if row["is_formula"]:
                    row["formula"] = merge.rewrite_formula(row["formula"], donor.sheet_map, donor.names, donor.tables, local_sheet=old)
                cells[new][address] = row
    return {"kind": "original_eight_donors_mapped_typed_expectation", "version": 1, "sheets": sheets, "cells": cells, "original_donors": refs, "date_comparison": "Original epoch resolved toISO calendar semantics before mapping; only declared3numeric date caches shift in emitted raw XML", "whole_source_financial_certified": False}


def compare_snapshots(expected, actual):
    mismatches = []
    formula_mismatches = []
    raw_differences = []
    error_expected = []
    error_actual = []
    checked_count = 0
    for title in sorted(set(expected["cells"]) | set(actual["cells"])):
        left = expected["cells"].get(title, {});right = actual["cells"].get(title, {})
        for address in sorted(set(left) | set(right)):
            checked_count += 1
            a = left.get(address, {});b = right.get(address, {})
            ap = a.get("primary", EMPTY);bp = b.get("primary", EMPTY)
            if ap != bp:
                mismatches.append({"sheet": title, "cell": address, "expected": ap, "actual": bp})
            if a.get("is_formula", False) != b.get("is_formula", False) or (a.get("is_formula") and merge._formula_tokens(a["formula"]) != merge._formula_tokens(b.get("formula") or "")):
                formula_mismatches.append({"sheet": title, "cell": address, "expected": a.get("formula"), "actual": b.get("formula")})
            if ap["type"] == "error":
                error_expected.append({"sheet": title, "cell": address, "error": ap["value"]})
            if bp["type"] == "error":
                error_actual.append({"sheet": title, "cell": address, "error": bp["value"]})
            if a.get("raw_numeric_text") is not None and b.get("raw_numeric_text") is not None:
                av = Decimal(a["raw_numeric_text"]);bv = Decimal(b["raw_numeric_text"])
                if av != bv:
                    with localcontext() as context:
                        context.prec = max(len(av.as_tuple().digits),len(bv.as_tuple().digits))+abs(av.as_tuple().exponent-bv.as_tuple().exponent)+8
                        difference = str(bv-av)
                    raw_differences.append({"sheet": title, "cell": address, "expected_raw": a["raw_numeric_text"], "actual_raw": b["raw_numeric_text"], "exact_decimal_difference": difference, "primary_equal": ap == bp})
    structure_ok = expected["sheets"] == actual["sheets"]
    return {"kind": "full_mapped_review_pack_primary_typed_equivalence", "version": 1, "passed": structure_ok and not mismatches and not formula_mismatches and error_expected == error_actual, "structure_ok": structure_ok, "full_sparse_union_cells_checked": checked_count, "primary_value_mismatch_count": len(mismatches), "primary_value_mismatches": mismatches, "formula_or_literal_identity_mismatch_count": len(formula_mismatches), "formula_or_literal_identity_mismatches": formula_mismatches, "expected_errors": error_expected, "actual_errors": error_actual, "error_coordinates_and_codes_unchanged": error_expected == error_actual, "raw_numeric_difference_count": len(raw_differences), "raw_numeric_differences": raw_differences, "raw_numeric_equality": not raw_differences, "primary_contract": CONTRACT, "exact_numeric_equivalence_claimed": False, "financial_certified": False}


def _runtime(profile):
    ref = reference(profile);value = load_runtime_profile(profile)
    require(value["id"] == "entity_group_large_v2" and value["image"]["id"] == IMAGE, "Pinned v2 resource profile required")
    require(all(v == {"cpus": 2, "memory_bytes": 32*1024**3, "pids_limit": 256} for v in value["docker_resources"].values()), "2CPU/32GiB/P256 required")
    require(value["timeouts"] == {"workbook_file_seconds": 600, "verifier_total_seconds": 2400}, "Frozen600s/file and2400s total profile required")
    return ref, value


def prepare(emission_terminal, output, *, profile=PROFILE):
    output = support()._output(output)
    require(not output.exists(), "Use a fresh validation directory")
    terminal_ref = reference(emission_terminal);terminal = read(terminal_ref)
    require(terminal["kind"] == merge.KIND and terminal["version"] == 1 and terminal["all_other_typed_cached_values_preserved"] and terminal["all_internal_relationships_resolved"], "A complete pure emission is required")
    checked(terminal["workbook"]);composer_prepared = checked(terminal["prepared"])
    bound = composer_driver().validate_prepared(composer_prepared.parent)
    require(bound["preflight"]["passed"] and len(bound["config"]["donors"]) == 8, "Frozen eight-donor preflight required")
    profile_ref, value = _runtime(profile)
    expected = expected_from_donors(bound["config"])
    emitted = snapshot(terminal["workbook"]["path"])
    before = compare_snapshots(expected, emitted)
    require(before["passed"], "Donor→emission primary equivalence failed before any service")
    require(len(before["expected_errors"]) == 12, "Exact12expected source errors must be frozen")
    output.mkdir(parents=True)
    originals = write(output/"original_donors_mapped_typed_expectation.json", expected)
    emission_snapshot = write(output/"emission_typed_snapshot.json", emitted)
    emission_comparison = write(output/"donor_to_emission_equivalence.json", before)
    manifest = {"kind": PREPARED_KIND, "version": VERSION, "emission_terminal": terminal_ref, "emission_workbook": terminal["workbook"], "composer_preparation": terminal["prepared"], "runtime_profile": profile_ref, "runtime_profile_value": value, "recipe": recipes(), "equivalence_contract": CONTRACT, "mapped_donors": originals, "emission_snapshot": emission_snapshot, "donor_to_emission_comparison": emission_comparison, "maximum_external_LO_calls": 3, "sequence_requires_each_prior_full_PASS": True, "outer_retries": 0, "model_solver_Harbor_calls": 0, "financial_certified": False, "source_admitted": False, "mapped_risk_lineage": [{"id":d["id"], "mapped_risk_lineage":d["mapped_risk_lineage"], "retained_cached_error_lineage":d["retained_cached_error_lineage"], "scoped_audits":d["scoped_audits"]} for d in bound["preflight"]["donors"]]}
    result = write(output/"prospective.json", manifest)
    validate_prepared(output)
    return result


def validate_prepared(output):
    output = support()._output(output)
    frozen = read(output/"prospective.json")
    require(frozen["kind"] == PREPARED_KIND and frozen["version"] == VERSION and frozen["recipe"] == recipes(), "Validation recipe/identity changed")
    require(frozen["equivalence_contract"] == CONTRACT and frozen["maximum_external_LO_calls"] == 3 and frozen["outer_retries"] == 0, "Frozen equivalence/count contract changed")
    checked(frozen["emission_terminal"]);checked(frozen["emission_workbook"])
    prepared = checked(frozen["composer_preparation"])
    composer = composer_driver().validate_prepared(prepared.parent)
    require(_runtime(checked(frozen["runtime_profile"])) == (frozen["runtime_profile"], frozen["runtime_profile_value"]), "Frozen runtime changed")
    originals = read(frozen["mapped_donors"]);emitted = read(frozen["emission_snapshot"])
    require(originals == expected_from_donors(composer["config"]) and emitted == snapshot(frozen["emission_workbook"]["path"]), "Frozen full typed inventory changed")
    require(read(frozen["donor_to_emission_comparison"]) == compare_snapshots(originals, emitted), "Frozen donor/emission comparison changed")
    return frozen, originals, emitted


def owned_cleanup(container_id):
    require(re.fullmatch(r"[0-9a-f]{64}", container_id), "Full owned CID required for cleanup proof")
    command = ["docker", "inspect", container_id, "--format", "{{.Id}}"]
    first = subprocess.run(command, capture_output=True, text=True, timeout=20)
    removal = None
    if first.returncode == 0:
        require(first.stdout.strip() == container_id, "Cleanup CID identity changed")
        result = subprocess.run(["docker", "rm", "--force", container_id], capture_output=True, text=True, timeout=20)
        removal = {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    absent = subprocess.run(command, capture_output=True, text=True, timeout=20)
    daemon = subprocess.run(["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"], capture_output=True, text=True, timeout=20)
    passed = absent.returncode != 0 and container_id in absent.stderr and "no such" in absent.stderr.lower() and daemon.returncode == 0 and daemon.stdout.strip() == IMAGE
    return {"owned_container_id": container_id, "owned_removal_if_needed": removal, "absence_inspect": {"returncode": absent.returncode, "stdout": absent.stdout, "stderr": absent.stderr}, "daemon_image_check": {"returncode": daemon.returncode, "stdout": daemon.stdout, "stderr": daemon.stderr}, "removed_and_absent_with_daemon_reachable": passed}


class ObservedEngine(ThreadCappedResourceLibreOfficeEngine):
    """Observe delegated commands; calculation/resource algorithms stay unchanged."""
    def __init__(self, *args, observer, transcript_directory, **kwargs):
        super().__init__(*args, **kwargs)
        self.observer = observer
        self.transcript_directory = transcript_directory

    def _run(self, command, timeout):
        result = super()._run(command, timeout)
        record = getattr(self._local, "record", None)
        if command[:2] == ["docker", "create"] and record:
            evidence = {"call_id": record["call_id"], "container_id": record["container_id"], "actual_resources": record["actual_resources"], "thread_cap_before": record["thread_cap_before"], "actual_resources_verified": record["actual_resources_verified"]}
            ref = write(self.transcript_directory/(record["call_id"]+".container_started.json"), evidence)
            self.observer(evidence, ref)
        if command[:2] == ["docker", "start"] and record:
            path = self.transcript_directory/(record["call_id"]+".native_stdout.txt")
            with path.open("x", encoding="utf-8") as stream:
                stream.write(result)
            record["engineering_native_stdout"] = reference(path)
        return result


def comparison_sequence(frozen, originals, emitted, attempt, perform_call, stage_callback=lambda _: None):
    """Small deterministic first-PASS gate, independently tested with fake calls."""
    current = Path(frozen["emission_workbook"]["path"])
    first = None
    comparisons = []
    for index in (1, 2, 3):
        stage_callback("actual_LO_"+str(index))
        destination = attempt/("pass"+str(index)+".xlsx")
        perform_call(index, current, destination)
        actual = snapshot(destination)
        snapshot_ref = write(attempt/("pass"+str(index)+"_typed_snapshot.json"), actual)
        donor_comparison = compare_snapshots(originals, actual)
        emission_comparison = compare_snapshots(emitted, actual)
        stable = compare_snapshots(first, actual) if first else None
        report = {"index": index, "native_output": reference(destination), "typed_snapshot": snapshot_ref, "original_donors_to_native": donor_comparison, "emission_to_native": emission_comparison, "pass1_to_current_stability": stable, "passed": donor_comparison["passed"] and emission_comparison["passed"] and (stable is None or stable["passed"]), "primary_numeric_quantized_to_two_decimals": True, "exact_numeric_equivalence_claimed": False, "financial_certified": False}
        ref = write(attempt/("pass"+str(index)+"_full_equivalence.json"), report)
        comparisons.append(ref)
        require(report["passed"], "Full primary typed/formula/error equivalence HOLD after LO"+str(index)+"; no downstream call")
        if first is None:
            first = actual
        current = destination
    return comparisons


def execute_prepared(output, *, port=0):
    output = support()._output(output)
    lease = ProducerLease(output).acquire()
    attempt = output/"private/attempts"/uuid4().hex
    audit = server = heartbeat_thread = None
    stop = threading.Event();clock = time.monotonic();calls = [];records = {};status = "held";failure = None;active = {"stage": "cold_validation"}
    try:
        require(not (output/"execution_started.json").exists(), "First attempt only; preserve prior execution and do not retry")
        frozen, originals, emitted = validate_prepared(output)
        attempt.mkdir(parents=True)
        audit = AuditStore(attempt/"audit", {"id": attempt.name, "name": "Eight-business native equivalence engineering", "status": "running", "producer_active": True, "producer_pid": os.getpid(), "qualified": 0, "target_count": 0})
        server = DashboardServer(audit.snapshot, audit.events, host="127.0.0.1", port=port);url = server.start()
        started = write(output/"execution_started.json", {"kind": KIND+"_started", "version": VERSION, "prospective": reference(output/"prospective.json"), "started_at": utcnow(), "producer_pid": os.getpid(), "dashboard_url": url, "first_attempt_only": True, "maximum_external_LO_calls": 3, "prior_PASS_gated": True})
        records["started"] = started
        audit.update_run(dashboard_url=url, actual_LO_calls_started=0, actual_LO_calls_completed=0)
        print(json.dumps({"dashboard_url":url,"producer_pid":os.getpid(),"attempt":str(attempt),"started":started}),flush=True)
        def heartbeat():
            while not stop.wait(15):
                audit.update_run(elapsed_seconds=time.monotonic()-clock, active_stage=active["stage"]);audit.export()
        heartbeat_thread=threading.Thread(target=heartbeat,daemon=True);heartbeat_thread.start()
        def observe(evidence, ref):
            audit.update_run(owned_container_id=evidence["container_id"], actual_resources=evidence["actual_resources"], actual_container_started=ref);audit.export()
            print(json.dumps({"owned_container_id":evidence["container_id"],"actual_resources":evidence["actual_resources"],"resource_started":ref}),flush=True)
        engine = ObservedEngine(ROOT, frozen["runtime_profile"]["path"], role="source", receipt_directory=attempt/"engine_resources", observer=observe, transcript_directory=attempt)
        def actual_call(index, source, destination):
            require(len(calls)==index-1 and index<=3, "External LO call count changed")
            require(frozen["recipe"] == recipes(), "Frozen validation implementation changed before a native call")
            checked(frozen["emission_terminal"]);checked(frozen["emission_workbook"]);checked(frozen["runtime_profile"])
            for original in originals["original_donors"]:
                checked(original)
            require(time.monotonic()-clock < frozen["runtime_profile_value"]["timeouts"]["verifier_total_seconds"], "Frozen2400s total guard reached")
            call={"index":index,"input":reference(source),"destination":str(destination),"started_at":utcnow(),"completed":False};calls.append(call)
            call["started_receipt"]=write(attempt/("LO"+str(index)+"_started.json"),dict(call));audit.update_run(actual_LO_calls_started=len(calls));audit.export()
            runtime_record = None
            try:
                tick=time.monotonic();result=engine.recalculate(source,destination)
                call.update(completed=True, output=reference(result),elapsed_seconds=time.monotonic()-tick)
                history=engine.metadata()["actual_resource_receipts"]
                require(len(history)==index,"Extra/missing actual LO resource receipt")
                runtime_record=history[-1]
                call["actual_resource_evidence"]=validate_capped_call(call,runtime_record,frozen,resource_validator=support().validate_actual_call)
            finally:
                # metadata() can probe the pinned image, so failures read the
                # already-written history directly rather than start any work.
                history=list(engine._history)
                if runtime_record is None and len(history)==index:
                    runtime_record=history[-1]
                if runtime_record:
                    actual=read(runtime_record);call["runtime_terminal"]=runtime_record
                    cid=actual.get("container_id")
                    if cid:
                        proof=owned_cleanup(cid);call["owned_cleanup"]=write(attempt/("LO"+str(index)+"_owned_cleanup.json"),proof)
                        require(proof["removed_and_absent_with_daemon_reachable"],"Owned cleanup could not be proved; stop before another call")
                call["finished_at"]=utcnow();call["terminal_receipt"]=write(attempt/("LO"+str(index)+"_terminal.json"),dict(call))
                audit.update_run(actual_LO_calls_started=len(calls),actual_LO_calls_completed=sum(c["completed"] for c in calls));audit.export()
        def stage(name):
            active["stage"]=name;audit.update_run(active_stage=name);audit.export()
        with support().data_temporary(output):
            records["comparisons"]=comparison_sequence(frozen,originals,emitted,attempt,actual_call,stage)
        validate_prepared(output)
        require(len(calls)==3 and all(c["completed"] and "owned_cleanup" in c for c in calls),"All three recorded owned calls required")
        status="primary_equivalence_and_two_chained_stability_checks_passed"
    except BaseException as error:
        failure=error
        attempt.mkdir(parents=True,exist_ok=True)
        records["failure"]=write(attempt/"failure.json",{"error_type":type(error).__name__,"error":str(error),"traceback":traceback.format_exc()})
    finally:
        stop.set()
        if heartbeat_thread:heartbeat_thread.join(timeout=1)
        terminal=write(attempt/"terminal.json",{"kind":KIND+"_terminal","version":VERSION,"status":status,"finished_at":utcnow(),"elapsed_seconds":time.monotonic()-clock,"prospective":reference(output/"prospective.json"),"actual_LO_calls":calls,"LO_calls_started":len(calls),"LO_calls_completed":sum(c["completed"] for c in calls),"records":records,"equivalence_contract":CONTRACT,"exact_numeric_equivalence_claimed":False,"financial_certified":False,"source_admitted":False,"task_count":0,"qualified":False,"model_solver_Harbor_calls":0,"outer_retries":0,"all_partial_and_failed_artifacts_preserved":True})
        if audit:audit.update_run(status=status,producer_active=False,terminal=terminal);audit.export()
        if server:server.stop()
        if audit:audit.db.close()
        lease.release()
    print(json.dumps({"terminal":terminal,"status":status,"LO_calls_started":len(calls)}),flush=True)
    if failure:
        raise RuntimeError("Engineering validation HOLD; preserve "+terminal["path"]) from failure
    return terminal


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest="action",required=True)
    p=sub.add_parser("prepare");p.add_argument("--emission-terminal",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    for action in ("validate-prepared","run"):
        p=sub.add_parser(action);p.add_argument("--prepared",type=Path,required=True)
        if action=="run":p.add_argument("--port",type=int,default=0)
    args=parser.parse_args()
    if args.action=="prepare":result=prepare(args.emission_terminal,args.output)
    elif args.action=="run":result=execute_prepared(args.prepared,port=args.port)
    else:validate_prepared(args.prepared);result={"passed":True}
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
