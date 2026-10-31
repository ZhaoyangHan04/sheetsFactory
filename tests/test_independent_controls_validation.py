"""Pure and mocked engineering-gate tests. No native office or other services."""
from copy import deepcopy
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import openpyxl
import pytest

from sheets_factory.workbook import independent_controls_candidate as candidate


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def no_services(monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError("Validation tests cannot execute services")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture(scope="module")
def gate():
    return load(candidate.ROOT / "scripts/validate_independent_controls_candidate.py", "_test_control_gate")


@pytest.fixture(scope="module")
def prototype(tmp_path_factory):
    driver = load(candidate.ROOT / "scripts/prepare_independent_controls_candidate.py", "_test_control_source")
    return driver.prepare(candidate.load(), tmp_path_factory.mktemp("independent-control-source") / "candidate")


@pytest.fixture(scope="module")
def ctx(gate, prototype): return gate.context(prototype)


@pytest.fixture
def prepared(gate, prototype, tmp_path):
    result = gate.prepare(prototype, tmp_path / "engineering")
    return Path(result["path"]).parent


def rewrite_zip(source, output, transform):
    with ZipFile(source) as before, ZipFile(output, "x", ZIP_DEFLATED) as after:
        for member in before.infolist(): after.writestr(member, transform(member.filename, before.read(member.filename)))


def calculate_fixture(source, output, ctx):
    """Test-only serialized-formula replay; never imports oracle equations.

    The only native-like behavior added here is blank-to-zero when an omitted
    numeric target is used by another formula. No caches enter production prep.
    """
    helper = load(candidate.ROOT / "tests/test_independent_controls_candidate.py", "_test_formula_replay")
    workbook, read_cell = helper.evaluate_formula_book(source)
    try:
        for sheet, cell in ctx["correct"]:
            if workbook[sheet][cell].value is None: workbook[sheet][cell] = 0
        computed = {(s.title, c.coordinate): read_cell(s.title, c.coordinate)
                    for s in workbook for c in s._cells.values() if c.data_type == "f"}
    finally: workbook.close()
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with ZipFile(source) as archive:
        sheets = {v: k for k, v in _sheet_parts(archive).items()}
    def caches(member, raw):
        if member not in sheets: return raw
        root = ET.fromstring(raw)
        for cell in root.findall(ns + "sheetData/" + ns + "row/" + ns + "c"):
            if cell.find(ns + "f") is None: continue
            value = computed[sheets[member], cell.get("r")]
            assert type(value) is Decimal
            cached = cell.find(ns + "v")
            if cached is None: cached = ET.SubElement(cell, ns + "v")
            cached.text = format(value, "f")
        return ET.tostring(root, encoding="utf-8")
    rewrite_zip(source, output, caches)


def _sheet_parts(archive):
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    relationships = {r.get("Id"): r.get("Target") for r in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
    result = {}
    for sheet in ET.fromstring(archive.read("xl/workbook.xml")).find(ns + "sheets"):
        target = relationships[sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")]
        result[sheet.get("name")] = target.lstrip("/") if target.startswith("/") else "xl/" + target
    return result


def replace_cache(source, destination, sheet, address, *, text, cell_type=None):
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with ZipFile(source) as archive: part = _sheet_parts(archive)[sheet]
    def transform(member, raw):
        if member != part: return raw
        root = ET.fromstring(raw)
        cell = next(c for c in root.findall(ns + "sheetData/" + ns + "row/" + ns + "c") if c.get("r") == address)
        if cell_type: cell.set("t", cell_type)
        cache = cell.find(ns + "v")
        if cache is None: cache = ET.SubElement(cell, ns + "v")
        cache.text = text
        return ET.tostring(root, encoding="utf-8")
    rewrite_zip(source, destination, transform)


def test_cold_preparation_freezes_genuine_ten_call_pair_without_services(gate, prototype, prepared, ctx):
    frozen = gate.validate_prepared(prepared)
    assert frozen["kind"] == "prepared_independent_controls_shared_engineering"
    assert frozen["stage_order"] == list(gate.STAGES) and len(gate.STAGES) == 10
    assert frozen["expected_FM_D"] == frozen["all_financial_targets"] == 546
    assert frozen["expected_DBG_D"] == 203
    assert frozen["actual_LO_calls"] == frozen["model_calls"] == 0
    assert frozen["qualified"] is False
    assert frozen["stage_inputs"]["goal2"] == "goal1"
    assert frozen["stage_inputs"]["FM_input2"] == "FM_input1"
    assert frozen["stage_inputs"]["DBG_input2"] == "DBG_input1"
    assert len(frozen["planned_inputs"]) == 7 and len(frozen["control_edits"]) == 4
    roots = {r["output"]["path"]: r["exact_cell_changes"][0] for r in frozen["control_edits"]}
    missed = roots[frozen["planned_inputs"]["DBG_missed_root"]["path"]]
    assert missed["sheet"] == "Crossed plans" and missed["cell"] == "L11"
    assert "$B11" in missed["value"] and "$D11" not in missed["value"]
    assert ctx["correct"]["Crossed plans", "L11"] == Decimal("21.6")
    assert ctx["wrong"]["Crossed plans", "L11"] == Decimal("12.6")
    assert gate.reference(prototype["path"]) == prototype
    assert not any((prepared / name).exists() for name in ("started.json", "attempt.json", "terminal.json", "engine_resources"))


def test_uncalculated_gold_is_explicitly_not_numeric_proof(gate, ctx):
    source = ctx["manifest"]["gold"]["path"]
    cold = gate.audit_workbook(source, ctx, require_calculated=False)
    actual = gate.audit_workbook(source, ctx)
    assert cold["passed"] and cold["actual_numeric_caches_required"] is False
    assert not actual["passed"] and len(actual["mismatches"]) >= 546
    assert actual["uncalculated_gold_is_not_numeric_proof"] is True


@pytest.mark.parametrize("mode,key", [("goal", "gold"), ("FM", "FM"), ("DBG", "DBG")])
def test_all_546_serialized_formula_outputs_or_blanks_checked(gate, ctx, tmp_path, mode, key):
    source = ctx["manifest"]["gold"] if key == "gold" else ctx["manifest"]["materials"][key]["public_input"]
    path = tmp_path / (mode + ".xlsx"); calculate_fixture(source["path"], path, ctx)
    report = gate.audit_workbook(path, ctx, mode=mode)
    assert report["passed"] and report["financial_targets_checked"] == 546
    assert report["formula_count"] == (0 if mode == "FM" else 546)
    assert report["public_literals_checked"] > 100


@pytest.mark.parametrize("value,cell_type", [("1", "b"), ("0", "n"), (None, "n"), ("#VALUE!", "e")])
def test_bad_numeric_cache_boolean_blank_zero_and_error_rejected(gate, ctx, tmp_path, value, cell_type):
    source = tmp_path / "calculated.xlsx"; calculate_fixture(ctx["manifest"]["gold"]["path"], source, ctx)
    bad = tmp_path / "bad.xlsx"; replace_cache(source, bad, "Crossed plans", "X11", text=value, cell_type=cell_type)
    assert not gate.audit_workbook(bad, ctx)["passed"]


def test_primary_two_decimal_contract_retains_raw_noise_diagnostics(gate, ctx, tmp_path):
    source = tmp_path / "calculated.xlsx"; calculate_fixture(ctx["manifest"]["gold"]["path"], source, ctx)
    noisy = tmp_path / "noisy.xlsx"; replace_cache(source, noisy, "Crossed plans", "X11", text="969.000000000001")
    report = gate.audit_workbook(noisy, ctx)
    assert report["passed"]
    assert any(r["cell"] == "X11" for r in report["raw_numeric_differences_after_primary_match"])
    assert gate.money(Decimal("1.005")) == Decimal("1.01")
    with pytest.raises(ValueError): gate.money(True)


def test_unquantized_stability_rejects_drift_even_when_money_audit_passes(gate, ctx, tmp_path):
    first = tmp_path / "first.xlsx"; calculate_fixture(ctx["manifest"]["gold"]["path"], first, ctx)
    second = tmp_path / "second.xlsx"; replace_cache(first, second, "Crossed plans", "X11", text="969.000000000001")
    assert gate.audit_workbook(first, ctx)["passed"] and gate.audit_workbook(second, ctx)["passed"]
    with pytest.raises(ValueError, match="unquantized typed fixed point"):
        gate._stability({"goal1": gate.reference(first), "goal2": gate.reference(second)}, "goal2")


def test_provided_numeric_term_sheet_input_is_exact_even_below_money_quantum(gate, ctx, tmp_path):
    source = tmp_path / "calculated.xlsx"; calculate_fixture(ctx["manifest"]["gold"]["path"], source, ctx)
    changed = tmp_path / "changed.xlsx"
    replace_cache(source, changed, "Financing scenarios", "C5", text="0.070000000001")
    report = gate.audit_workbook(changed, ctx)
    assert not report["passed"]
    assert any(row.get("sheet") == "Financing scenarios" and row.get("cell") == "C5" for row in report["mismatches"])


@pytest.mark.parametrize("tamper", ["provided_literal", "formula", "extra_cell"])
def test_provided_policy_formula_and_extra_scope_protection(gate, ctx, tmp_path, tamper):
    source = tmp_path / "calculated.xlsx"; calculate_fixture(ctx["manifest"]["gold"]["path"], source, ctx)
    bad = tmp_path / "bad.xlsx"
    if tamper == "provided_literal": gate.patch_cells(source, bad, {("Read me", "A1"): ("text", "Changed policy")})
    elif tamper == "formula": gate.patch_cells(source, bad, {("Crossed plans", "X11"): ("formula", "=1")})
    else:
        book = openpyxl.load_workbook(source); book["Read me"]["Z99"] = "unexpected"; book.save(bad); book.close()
    if tamper == "formula":
        with pytest.raises(ValueError, match="formula definitions"): gate.audit_workbook(bad, ctx)
    else: assert not gate.audit_workbook(bad, ctx)["passed"]


def test_patch_preserves_every_unedited_zip_member_and_cell_byte(gate, ctx, tmp_path):
    source = ctx["manifest"]["gold"]["path"]; path = tmp_path / "patched.xlsx"
    receipt = gate.patch_cells(source, path, {("Crossed plans", "X11"): ("formula", "=0+1")})
    assert receipt["all_other_member_and_unedited_cell_bytes_preserved"] is True
    with ZipFile(source) as before, ZipFile(path) as after:
        assert before.namelist() == after.namelist()
        changed = [name for name in before.namelist() if before.read(name) != after.read(name)]
        assert changed == receipt["changed_members"] and len(changed) == 1
        raw_before, raw_after = before.read(changed[0]), after.read(changed[0])
        import re
        strip = lambda raw: re.sub(rb'<c\b(?=[^>]*\br="X11")[^>]*>.*?</c>', b"<target/>", raw)
        assert strip(raw_before) == strip(raw_after)
    with pytest.raises(ValueError, match="exist exactly once"):
        gate.patch_cells(source, tmp_path / "missing.xlsx", {("Read me", "ZZ999"): ("blank", None)})


@pytest.mark.parametrize("tamper", ["kind", "call_count", "stage_chain", "expected_D", "control_description", "equivalent_description", "profile", "mode_order"])
def test_prepared_protocol_and_control_tampering_rejected(gate, prepared, tamper):
    path = prepared / "preparation.json"; frozen = gate.read(path)
    if tamper == "kind": frozen["kind"] = "prepared_period_boundary_shared_engineering_v2"
    elif tamper == "call_count": frozen["required_actual_LO_calls"] = 14
    elif tamper == "stage_chain": frozen["stage_inputs"]["DBG_input2"] = "FM_input1"
    elif tamper == "expected_D": frozen["expected_DBG_D"] = 202
    elif tamper == "control_description": frozen["control_edits"][0]["exact_cell_changes"][0]["cell"] = "Y11"
    elif tamper == "equivalent_description": frozen["equivalent_formula"]["formula"] = "=1"
    elif tamper == "profile": frozen["runtime_profile_value"]["docker_resources"]["source"]["cpus"] = 16
    else: frozen["mode_order"] = ["debugging", "financial_modeling"]
    path.write_text(json.dumps(frozen))
    with pytest.raises(ValueError): gate.validate_prepared(prepared)


def test_rebound_control_with_undeclared_other_member_change_rejected(gate, prepared, tmp_path):
    path = prepared / "preparation.json"; frozen = gate.read(path)
    control = frozen["planned_inputs"]["equivalent"]; current = tmp_path / "new.xlsx"
    rewrite_zip(control["path"], current, lambda member, raw: raw + b" " if member == "docProps/core.xml" else raw)
    Path(control["path"]).write_bytes(current.read_bytes())
    new_ref = gate.reference(control["path"])
    frozen["planned_inputs"]["equivalent"] = new_ref; frozen["stage_inputs"]["equivalent"] = new_ref
    next(c for c in frozen["control_edits"] if c["output"] == control)["output"] = new_ref
    path.write_text(json.dumps(frozen))
    with pytest.raises(ValueError, match="every other member"): gate.validate_prepared(prepared)


class NoNetworkDashboard:
    def __init__(self, *args, **kwargs): pass
    def start(self): return "http://127.0.0.1:12345/TEST_ONLY"
    def stop(self): pass


def install_mock_engine(monkeypatch, gate, ctx, *, fail_at=None, corrupt_at=None):
    class TestOnlyEngine:
        instances = []
        def __init__(self, *args, **kwargs): self.receipts = []; self.instances.append(self)
        def ensure_image(self): pass
        def metadata(self): return {"actual_resource_receipts": self.receipts}
        def recalculate(self, source, output):
            index = len(self.receipts) + 1
            if index == fail_at: raise RuntimeError("TEST_ONLY simulated native failure")
            calculate_fixture(source, output, ctx)
            if index == corrupt_at:
                corrupted = Path(output).with_suffix(".corrupt.xlsx")
                replace_cache(output, corrupted, "Crossed plans", "X11", text="123")
                Path(output).write_bytes(corrupted.read_bytes())
            self.receipts.append(gate.write(Path(output).with_suffix(".TEST_ONLY_resource.json"),
                {"kind": "TEST_ONLY_no_native_call", "container_id": f"{index:064x}", "source": gate.reference(source), "output": gate.reference(output)}))
            return output
    def validate_call(call, runtime, frozen):
        value = gate.read(runtime)
        assert value["kind"] == "TEST_ONLY_no_native_call"
        assert value["source"] == call["input"] and value["output"] == call["output"]
        return {"container_id": value["container_id"], "terminal": runtime, "TEST_ONLY": True}
    def absence(calls):
        return {"all_owned_containers_absent": True, "daemon_reachable": True,
                "owned": [{"full_id": c["actual_resource_evidence"]["container_id"], "absent": True} for c in calls], "TEST_ONLY": True}
    monkeypatch.setattr(gate, "ThreadCappedResourceLibreOfficeEngine", TestOnlyEngine)
    monkeypatch.setattr(gate, "DashboardServer", NoNetworkDashboard)
    monkeypatch.setattr(gate, "validate_call", validate_call)
    monkeypatch.setattr(gate, "owned_absence", absence)
    return TestOnlyEngine


def test_mocked_ten_call_lifecycle_independent_audits_controls_and_cold_graph(gate, ctx, prepared, monkeypatch):
    original_refs = {k: gate.reference(v["path"]) for k, v in gate.validate_prepared(prepared)["planned_inputs"].items()}
    engine = install_mock_engine(monkeypatch, gate, ctx)
    result = gate.execute_prepared(prepared); terminal = gate.validate_completed(result)
    assert terminal["passed"] and terminal["actual_LO_calls_started"] == terminal["actual_LO_calls_completed"] == 10
    assert len(engine.instances) == 1 and len(engine.instances[0].receipts) == 10
    assert terminal["qualified"] is terminal["difficulty_claimed"] is terminal["normal_all12_QA_passed"] is False
    assert {c["role"] for c in terminal["actual_calls"]} == set(gate.STAGES)
    for mode, count in (("financial_modeling", 546), ("debugging", 203)):
        proof = terminal["records"]["modes"][mode]
        assert proof["complete_D_count"] == count
        assert proof["controls"] == {"oracle": 1, "nop": 0, "equivalent": 1, "missed_root": 0, "extra_change": 0}
    assert all(gate.reference(ref["path"]) == ref for ref in original_refs.values())
    assert gate.read(prepared / "producer.lock")["status"] == "released"
    with pytest.raises(ValueError, match="No retries"): gate.execute_prepared(prepared)
    assert len(engine.instances) == 1


@pytest.mark.parametrize("corrupt", [False, True])
def test_native_failure_or_full_numeric_mismatch_stops_before_downstream_no_retry(gate, ctx, prepared, monkeypatch, corrupt):
    engine = install_mock_engine(monkeypatch, gate, ctx, fail_at=None if corrupt else 2, corrupt_at=2 if corrupt else None)
    with pytest.raises(RuntimeError, match="preserve terminal"): gate.execute_prepared(prepared)
    terminal = gate.read(prepared / "terminal.json")
    assert not terminal["passed"] and terminal["actual_LO_calls_started"] == 2
    assert terminal["actual_LO_calls_completed"] == (2 if corrupt else 1)
    assert len(engine.instances[0].receipts) == (2 if corrupt else 1)
    assert (prepared / "failure.json").exists()
    assert gate.read(prepared / "producer.lock")["status"] == "released"
    with pytest.raises(ValueError, match="No retries"): gate.execute_prepared(prepared)


@pytest.mark.parametrize("marker", ["attempt.json", "started.json", "failure.json", "terminal.json"])
def test_any_prior_attempt_marker_blocks_even_before_engine_creation(gate, ctx, prepared, monkeypatch, marker):
    engine = install_mock_engine(monkeypatch, gate, ctx)
    (prepared / marker).write_text('{"retained":"immutable"}')
    with pytest.raises(ValueError, match="No retries"): gate.execute_prepared(prepared)
    assert not engine.instances
    assert (prepared / marker).read_text() == '{"retained":"immutable"}'


def test_race_recheck_under_lease_prevents_second_launch(gate, ctx, prepared, monkeypatch):
    engine = install_mock_engine(monkeypatch, gate, ctx)
    real_lease = gate.ProducerLease
    class RacingLease(real_lease):
        def acquire(self):
            value = super().acquire()
            (prepared / "attempt.json").write_text('{"first_process":"already ended"}')
            return value
    monkeypatch.setattr(gate, "ProducerLease", RacingLease)
    with pytest.raises(ValueError, match="No retries"): gate.execute_prepared(prepared)
    assert not engine.instances and gate.read(prepared / "producer.lock")["status"] == "released"


def test_failed_setup_is_durable_and_releases_lease(gate, ctx, prepared, monkeypatch):
    engine = install_mock_engine(monkeypatch, gate, ctx)
    (prepared / "temporary").mkdir()
    with pytest.raises(RuntimeError, match="preserve terminal"): gate.execute_prepared(prepared)
    assert (prepared / "attempt.json").exists() and (prepared / "failure.json").exists()
    assert gate.read(prepared / "terminal.json")["actual_LO_calls_started"] == 0
    assert gate.read(prepared / "producer.lock")["status"] == "released" and not engine.instances


@pytest.mark.parametrize("tamper", ["own_kind", "count", "duplicate_CID", "cleanup", "mode_proof", "started_receipt", "resource_proof"])
def test_cold_completed_validation_rejects_forged_or_incomplete_evidence(gate, ctx, prepared, monkeypatch, tamper):
    install_mock_engine(monkeypatch, gate, ctx); result = gate.execute_prepared(prepared)
    terminal = gate.read(result)
    if tamper == "own_kind": terminal["kind"] = "period_boundary_actual_shared_engineering_validation_v2"
    elif tamper == "count": terminal["actual_LO_calls_completed"] = 9
    elif tamper == "duplicate_CID": terminal["actual_calls"][1]["actual_resource_evidence"]["container_id"] = terminal["actual_calls"][0]["actual_resource_evidence"]["container_id"]
    elif tamper == "cleanup":
        path = Path(terminal["records"]["cleanup"]["path"]); record = gate.read(path); record["daemon_reachable"] = False
        path.write_text(json.dumps(record)); terminal["records"]["cleanup"] = gate.reference(path)
    elif tamper == "mode_proof": terminal["records"]["modes"]["debugging"]["complete_D_count"] = 202
    elif tamper == "started_receipt":
        path = Path(terminal["actual_calls"][0]["started_receipt"]["path"]); path.write_text("{}")
    else:
        monkeypatch.setattr(gate, "validate_call", lambda *args: (_ for _ in ()).throw(ValueError("TEST_ONLY resource boundary rejected")))
    path = prepared / "tampered_terminal.json"; path.write_text(json.dumps(terminal))
    with pytest.raises(ValueError): gate.validate_completed(path)


@pytest.mark.parametrize("message,code,stdout,daemon_ok,expected", [
    ("Error: No such object: {cid}", 1, "", True, True),
    ("error: no such container: {cid}", 1, "", True, True),
    ("ERROR: NO SUCH OBJECT: {cid}", 1, "", True, True),
    ("Error: No such object: {other}", 1, "", True, False),
    ("Error: No such object: {cid}", 1, "found", True, False),
    ("Error: No such object: {cid}", 0, "", True, False),
    ("permission denied", 1, "", True, False),
    ("Error: No such object: {cid}", 1, "", False, False),
])
def test_owned_absence_exact_ids_case_insensitive_unknown_never_pass(gate, monkeypatch, message, code, stdout, daemon_ok, expected):
    cid = "a" * 64; calls = [{"actual_resource_evidence": {"container_id": cid}}]; observed = []
    def run(command, **kwargs):
        observed.append(command)
        if command[1] == "version": return SimpleNamespace(returncode=0 if daemon_ok else 1, stdout="27.0\n" if daemon_ok else "", stderr="")
        assert command == ["docker", "inspect", cid, "--format", "{{.Id}}"]
        return SimpleNamespace(returncode=code, stdout=stdout, stderr=message.format(cid=cid, other="b" * 64))
    monkeypatch.setattr(subprocess, "run", run)
    result = gate.owned_absence(calls)
    assert (result["all_owned_containers_absent"] and result["daemon_reachable"]) is expected
    assert result["cleanup_mutations_by_validator"] is False and len(observed) == 2


@pytest.mark.parametrize("ids", [["a" * 12], ["a" * 64, "a" * 64], ["Z" * 64]])
def test_owned_absence_rejects_short_unknown_and_duplicate_ids_before_commands(gate, ids):
    with pytest.raises(ValueError, match="Distinct full owned IDs"):
        gate.owned_absence([{"actual_resource_evidence": {"container_id": cid}} for cid in ids])


def test_hash_bound_resource_and_pure_absence_helpers_fail_closed(gate, monkeypatch):
    monkeypatch.setattr(gate, "SUPPORT_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="resource helper changed"): gate.resource_support()
    monkeypatch.setattr(gate, "ABSENCE_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="absence helper changed"): gate.owned_absence([])
    import ast
    functions = [n for n in ast.parse(Path(gate.__file__).read_text()).body if isinstance(n, ast.FunctionDef) and n.name == "owned_absence"]
    text = ast.unparse(functions[0])
    assert 'node.name == \'owned_absence\'' in text and "_namespace" not in text
    assert "_PRIVATE" not in vars(gate)


def test_cli_run_cannot_be_combined_with_fresh_preparation(gate, prototype, tmp_path):
    with pytest.raises(ValueError, match="separate explicit"):
        gate.main(["--candidate", prototype["path"], "--output", str(tmp_path / "cold-only"), "--run"])
    assert not (tmp_path / "cold-only/attempt.json").exists()
