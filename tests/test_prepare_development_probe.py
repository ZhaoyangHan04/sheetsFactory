"""Probe preparation orchestration with explicit fake LO/control nodes."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import openpyxl
import pytest
import yaml

from sheets_factory.core.node import BaseNode


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("prepare_development_probe_script", ROOT / "scripts/prepare_development_probe.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2))


def files(directory):
    return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in directory.rglob("*") if path.is_file()}


@pytest.fixture
def source_run(tmp_path):
    run = tmp_path / "original_run"
    run.mkdir()
    source = tmp_path / "original_raw.xlsx"
    book = openpyxl.Workbook()
    book.active.title = "Operating"
    book.create_sheet("Financing")
    for sheet in book:
        for row in range(1, 4):
            sheet.cell(row, 1, "=1+1")
    book.save(source)
    book.close()
    identity = hashlib.sha256(source.read_bytes()).hexdigest()
    cache = run / "sources" / identity[:12]
    cache.mkdir(parents=True)
    shutil.copy2(source, cache / "baseline.xlsx")
    manifest = tmp_path / "seed_manifest.json"
    write_json(manifest, {"selected": [{"sha256": identity, "source_sha256": identity,
                "local_path": str(source), "finance_evidence": {"source_business_issues": []}}]})
    config = {"project_root": str(ROOT), "run_dir": str(run),
              "run": {"seed_manifest": str(manifest)}, "engine": {"image": "fixture-image"},
              "construction": {"authoring_backend": "llm", "planning_scope": "per_mode"}}
    (run / "resolved_config.yaml").write_text(yaml.safe_dump(config))
    write_json(run / "summary.json", {"tasks": [{"id": "fm-" + identity[:12],
        "source_id": identity, "source": source.name, "mode": "financial_modeling"}]})
    # This is deliberately not a valid model result. Preparation may not read it.
    (run / "evaluation_manifest.json").write_text("not-a-model-score")
    plan = {"title": "Fixture project workflow", "business_context": "Fixture context",
            "public_instruction": "Restore the financial workflow using the supplied public business assumptions.",
            "public_rules": ["Use the stated public policies."], "reference_evidence": ["Fixture formula assertions"],
            "scenario_inputs": [], "edits": [], "protected_inputs": [], "native_issues": []}
    for mode in probe.MODES:
        chosen = deepcopy(plan)
        chosen["title"] = mode + " exact cached proposal"
        if mode == "financial_modeling":
            chosen["mask_ranges"] = [{"sheet": sheet, "range": "A1:A3", "reason": "Fixture full family",
                "business_rule": "Fixture public policy"} for sheet in ("Operating", "Financing")]
        else:
            chosen["edits"] = [{"sheet": sheet, "cell": "A" + str(row), "before": "=1+1", "after": "=1+2",
                "reason": "Fixture mutation", "business_rule": "Fixture public policy"}
                for sheet in ("Operating", "Financing") for row in range(1, 4)]
        write_json(cache / ("task_plans_v0_" + mode + ".json"), {mode: chosen, "source_assessment": {"fixture": True}})
    return {"run": run, "source": source, "identity": identity, "cache": cache,
            "manifest": manifest, "output": tmp_path / "new_probe"}


@pytest.fixture
def stub_nodes(monkeypatch):
    observed = {"engines": [], "plans": [], "controls": deepcopy(probe.CONTROL_REWARDS)}

    class Engine:
        def __init__(self, root, image, timeout_seconds):
            observed["engines"].append({"root": root, "image": image, "timeout": timeout_seconds})

        def metadata(self):
            return {"backend": "offline_test_fixture_not_libreoffice"}

    class Construct(BaseNode):
        node_id = "construct"

        def execute(self, context):
            assert context.source.is_relative_to(Path(context.config["run_dir"]))
            assert context.data["baseline"].is_relative_to(Path(context.config["run_dir"]))
            observed["plans"].append(deepcopy(context.data["plan"]))
            public = context.revision_dir / "public"
            private = context.revision_dir / "private"
            public.mkdir(parents=True)
            private.mkdir()
            goal = private / "goal.xlsx"
            input_file = public / "input.xlsx"
            shutil.copy2(context.data["baseline"], goal)
            book = openpyxl.load_workbook(goal)
            for edit in context.data["plan"]["edits"]:
                book[edit["sheet"]][edit["cell"]] = edit["after"]
            book.save(input_file)
            book.close()
            context.save("plan.json", context.data["plan"])
            return {"goal": goal, "input": input_file}

    class Controls(BaseNode):
        node_id = "precheck"

        def execute(self, context):
            return {"controls": {name: {"reward": reward, "fixture": True}
                                 for name, reward in observed["controls"].items()}}

    monkeypatch.setattr(probe, "LibreOfficeEngine", Engine)
    monkeypatch.setattr(probe, "ConstructNode", Construct)
    monkeypatch.setattr(probe, "ControlsNode", Controls)
    return observed


@pytest.mark.parametrize("mode", probe.MODES)
@pytest.mark.parametrize("full_identity", [True, False])
def test_prepares_exact_cached_proposal_without_touching_original_or_reading_scores(source_run, stub_nodes, mode, full_identity):
    item = source_run
    before = files(item["run"])
    original_source = item["source"].read_bytes()
    selector = item["identity"] if full_identity else item["identity"][:12]
    manifest = probe.prepare_probe(item["run"], selector, mode, item["output"])
    assert stub_nodes["plans"][0]["title"] == mode + " exact cached proposal"
    assert len(stub_nodes["plans"][0]["edits"]) == 6
    assert files(item["run"]) == before
    assert item["source"].read_bytes() == original_source
    assert manifest["kind"] == manifest["source_kind"] == "prequality_development_probe"
    assert manifest["model_evaluation_performed"] is False
    assert manifest["llm_calls"] == 0
    assert manifest["local_controls"] == probe.CONTROL_REWARDS
    assert "pending" in manifest["quality_status"]
    assert "qualified" not in manifest["quality_status"]
    task = manifest["tasks"][0]
    assert task["mode"] == mode and task["source_id"] == item["identity"]
    assert task["harbor_export_binding"] == probe.inspect_export(task["task_directory"])
    assert Path(task["task_directory"]).is_relative_to(item["output"] / "SpreadsheetEval")
    origin = manifest["planning_origin"]
    assert origin["path"].endswith("task_plans_v0_" + mode + ".json")
    assert origin["sha256"] == probe._sha(origin["path"])
    assert manifest["baseline_origin"]["sha256"] == probe._sha(item["cache"] / "baseline.xlsx")
    summary = json.loads((item["output"] / "summary.json").read_text())
    assert summary["run"]["status"] == "prepared"
    assert summary["metrics"]["qualified"] == summary["metrics"]["llm_calls"] == 0
    assert len(summary["nodes"]) == 3


def test_existing_output_is_never_overwritten(source_run, stub_nodes):
    item = source_run
    item["output"].mkdir()
    marker = item["output"] / "marker.txt"
    marker.write_text("immutable existing output")
    with pytest.raises(FileExistsError):
        probe.prepare_probe(item["run"], item["identity"], "financial_modeling", item["output"])
    assert files(item["output"]) == {"marker.txt": hashlib.sha256(marker.read_bytes()).hexdigest()}
    assert not stub_nodes["engines"]


def test_output_inside_source_run_is_rejected_without_writing(source_run, stub_nodes):
    item = source_run
    before = files(item["run"])
    with pytest.raises(ValueError, match="outside the original"):
        probe.prepare_probe(item["run"], item["identity"], "financial_modeling", item["run"] / "probe")
    assert files(item["run"]) == before


def test_actual_raw_source_hash_mismatch_is_audited_before_any_node(source_run, stub_nodes):
    item = source_run
    item["source"].write_bytes(item["source"].read_bytes() + b"changed")
    with pytest.raises(ValueError, match="Actual raw source SHA256"):
        probe.prepare_probe(item["run"], item["identity"], "financial_modeling", item["output"])
    failure = json.loads((item["output"] / "preparation_failure.json").read_text())
    assert "SHA256" in failure["error"]
    summary = json.loads((item["output"] / "summary.json").read_text())
    assert summary["run"]["status"] == "failed" and not summary["nodes"]
    assert not stub_nodes["engines"]
    assert not (item["output"] / "probe_manifest.json").exists()


def test_wrong_before_assertion_is_not_repaired_or_generated_inline(source_run, stub_nodes):
    item = source_run
    path = item["cache"] / "task_plans_v0_debugging.json"
    cached = json.loads(path.read_text())
    cached["debugging"]["edits"][0]["before"] = "=999"
    write_json(path, cached)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="before assertion differs"):
        probe.prepare_probe(item["run"], item["identity"], "debugging", item["output"])
    assert path.read_bytes() == before
    assert not stub_nodes["engines"]
    assert (item["output"] / "preparation_failure.json").exists()


def test_missing_exact_mode_proposal_has_no_other_file_fallback(source_run, stub_nodes):
    item = source_run
    (item["cache"] / "task_plans_v0_debugging.json").unlink()
    with pytest.raises(ValueError, match="exact cached mode proposal"):
        probe.prepare_probe(item["run"], item["identity"], "debugging", item["output"])
    assert not stub_nodes["engines"]


def test_failed_control_is_audited_and_cannot_freeze_export(source_run, stub_nodes):
    item = source_run
    stub_nodes["controls"]["nop"] = 1
    with pytest.raises(ValueError, match="Local control.*nop"):
        probe.prepare_probe(item["run"], item["identity"], "financial_modeling", item["output"])
    assert not (item["output"] / "probe_manifest.json").exists()
    assert not (item["output"] / "SpreadsheetEval").exists()
    summary = json.loads((item["output"] / "summary.json").read_text())
    assert summary["run"]["status"] == "failed"
    assert summary["metrics"]["qualified"] == summary["metrics"]["llm_calls"] == 0


def test_source_audit_identity_must_match_manifest_and_actual_file(source_run, stub_nodes):
    item = source_run
    summary = json.loads((item["run"] / "summary.json").read_text())
    summary["tasks"][0]["source"] = "another.xlsx"
    write_json(item["run"] / "summary.json", summary)
    with pytest.raises(ValueError, match="audit does not match"):
        probe.prepare_probe(item["run"], item["identity"], "financial_modeling", item["output"])
    assert not stub_nodes["engines"]


@pytest.mark.parametrize("selector", ["../sources", "abcd", "f" * 63, "x" * 64])
def test_source_selector_cannot_be_an_arbitrary_path(source_run, stub_nodes, selector):
    item = source_run
    with pytest.raises(ValueError, match="explicit full SHA256"):
        probe.prepare_probe(item["run"], selector, "financial_modeling", item["output"])
    assert not stub_nodes["engines"]


def test_ambiguous_twelve_character_hash_prefix_is_rejected(source_run, stub_nodes):
    item = source_run
    document = json.loads(item["manifest"].read_text())
    other = deepcopy(document["selected"][0])
    other["sha256"] = item["identity"][:12] + ("0" * 52 if item["identity"][12:] != "0" * 52 else "1" * 52)
    document["selected"].append(other)
    write_json(item["manifest"], document)
    with pytest.raises(ValueError, match="uniquely identify"):
        probe.prepare_probe(item["run"], item["identity"][:12], "financial_modeling", item["output"])
    assert not stub_nodes["engines"]


def test_accidental_model_call_is_forbidden_without_backend_instantiation():
    with pytest.raises(RuntimeError, match="must not invoke a model"):
        probe._NoModelCalls().complete("forbidden")
