"""Backend routing and certificate integration, using explicit test doubles."""

from copy import deepcopy
from pathlib import Path
import sys
import types

import openpyxl
import pytest

from sheets_factory.core.node import TaskContext, TaskRejected
from sheets_factory.nodes import construction as module


class Audit:
    def __init__(self):
        self.events = []

    def emit(self, kind, **values):
        self.events.append((kind, values))


class NoModels:
    def complete(self, *args, **kwargs):
        raise AssertionError("No model call is allowed in these integration fixtures")


def test_portfolio_template_uses_verified_source_and_exact_backend_cache(tmp_path, monkeypatch):
    baseline = tmp_path / "baseline.xlsx"
    baseline.write_bytes(b"explicit routing fixture")
    calls = []
    def propose(path, mode):
        calls.append((path, mode))
        return {"title": "Fixture portfolio", "edits": [], "mask_ranges": [{"sheet": "Fixture", "range": "A1:A6"}]}
    fake = types.ModuleType("sheets_factory.workbook.derived_gold.portfolio_tasks")
    fake.propose_portfolio_task = propose
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    ctx = TaskContext("run", "fm-fixture", "financial_modeling", baseline, tmp_path / "task",
        {"construction": {"authoring_backend": "portfolio_template", "planning_scope": "per_mode"}},
        Audit(), NoModels(), None, data={"baseline": baseline, "source_cache": tmp_path,
                                      "finance_evidence": {"financial_seed_verified": True}})
    result = module.PlanNode().execute(ctx)
    assert result["plan"]["title"] == "Fixture portfolio"
    cache = tmp_path / "task_plans_v0_financial_modeling_portfolio_template.json"
    assert cache.is_file()
    assert calls == [(baseline, "financial_modeling")]
    assert ctx.audit.events[0][1]["llm_calls"] == 0
    assert module.PlanNode().execute(ctx) == result
    assert len(calls) == 1


@pytest.mark.parametrize("verified,variant", [(False, 0), (True, 1)])
def test_portfolio_template_does_not_bypass_source_verification_or_variant_identity(tmp_path, verified, variant):
    ctx = types.SimpleNamespace(config={"construction": {"authoring_backend": "portfolio_template"}},
        data={"variant": variant, "finance_evidence": {"financial_seed_verified": verified}})
    with pytest.raises(TaskRejected, match="verified financial source"):
        module.PlanNode().execute(ctx)


@pytest.fixture
def construction_fixture(tmp_path, monkeypatch):
    baseline = tmp_path / "baseline.xlsx"
    book = openpyxl.Workbook()
    book.active.title = "Operating"
    book.create_sheet("Assets")
    edits = []
    for sheet in book:
        for row in range(1, 4):
            sheet.cell(row, 1, "=1+1")
            edits.append({"sheet": sheet.title, "cell": "A" + str(row), "before": "=1+1", "after": "=1+2"})
    book.save(baseline)
    book.close()
    labels = [item["sheet"] + "!" + item["cell"] for item in edits]
    observed = {"calculations": 0, "certificate_calls": [], "profile_kwargs": []}
    class Engine:
        def recalculate(self, source, destination):
            import shutil
            observed["calculations"] += 1
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            return destination
    monkeypatch.setattr(module, "validate_plan", lambda *args, **kwargs: {"native_error_candidates": []})
    monkeypatch.setattr(module, "compare_workbooks", lambda *args, **kwargs: {
        "expected_change_count": len(edits), "expected_changes": labels, "goal_sheets": ["Operating", "Assets"]})
    monkeypatch.setattr(module, "evaluate_native_risk_guard", lambda *args, **kwargs: {
        "state": "fixture", "blocking": False, "issues": []})
    monkeypatch.setattr(module, "probe_native_errors", lambda **kwargs: {
        "state": "not_applicable", "blocking": False, "candidates": [], "probes": [], "duration_ms": 0})
    def profile(*args, **kwargs):
        observed["profile_kwargs"].append(kwargs)
        return {"fixture": True}
    monkeypatch.setattr(module, "profile_workbook", profile)
    impacts = [{"expected_change_count": 1, "expected_changes": [label],
                "combined_marginal": {"expected_change_count": 1, "expected_changes": [label]},
                "proof_method": "separated_dependency_graph_and_actual_combined_value_change",
                "individual_LO_executions": False, "marginal_LO_executions": False}
               for label in labels]
    observed["certificate"] = {"passed": True, "blocking": False, "state": "proven", "root_impacts": impacts,
        "proof_method": "separated_roots_with_actual_combined_LO_values"}
    fake = types.ModuleType("sheets_factory.checkers.separated_roots")
    def certify(**kwargs):
        observed["certificate_calls"].append(kwargs)
        return deepcopy(observed["certificate"])
    fake.certify_separated_roots = certify
    monkeypatch.setitem(sys.modules, fake.__name__, fake)
    config = {"project_root": str(tmp_path), "construction": {"analysis_limits": {
        "max_dependency_closure_cells": 500000, "max_profile_cells": 500000, "per_formula_reference_cells": 50000}}}
    context = TaskContext("run", "dbg-fixture", "debugging", baseline, tmp_path / "task", config,
        Audit(), NoModels(), Engine(), data={"baseline": baseline, "source_id": module.digest(baseline),
        "plan": {"edits": edits}, "engine_report": {"engine": {"backend": "explicit_test_fixture"}}})
    return context, observed


def test_separated_certificate_uses_actual_combined_recalculation_and_never_claims_individual_lo_runs(construction_fixture):
    context, observed = construction_fixture
    context.config["construction"]["root_impact_validation"] = "separated_roots"
    result = module.ConstructNode().execute(context)
    assert observed["calculations"] == 1
    assert len(observed["certificate_calls"]) == 1
    called = observed["certificate_calls"][0]
    assert called["goal"] == result["goal"] and called["combined_input"] == result["input"]
    assert called["max_dependency_cells"] == 500000
    assert called["per_formula_reference_cells"] == 50000
    assert len(result["root_impacts"]) == 6
    assert (context.revision_dir / "private/separated_roots_certificate.json").is_file()
    validation = result["construction_validation"]["root_impact_validation"]
    assert validation["individual_LO_executions"] is False
    assert validation["marginal_LO_executions"] is False
    assert observed["profile_kwargs"] == [{"max_cells": 500000, "per_formula_reference_cells": 50000}]


def test_default_root_validation_retains_all_individual_and_marginal_calculations(construction_fixture):
    context, observed = construction_fixture
    result = module.ConstructNode().execute(context)
    assert observed["calculations"] == 1 + 2 * len(context.data["plan"]["edits"])
    assert not observed["certificate_calls"]
    assert len(result["root_impacts"]) == 6


def test_rejected_separation_proof_is_saved_and_fails_closed_without_strict_fallback(construction_fixture):
    context, observed = construction_fixture
    context.config["construction"]["root_impact_validation"] = "separated_roots"
    observed["certificate"].update(passed=False, blocking=True, state="rejected", reason="A root depends on another root")
    with pytest.raises(TaskRejected, match="separated-root proof rejected"):
        module.ConstructNode().execute(context)
    assert observed["calculations"] == 1
    assert (context.revision_dir / "private/separated_roots_certificate.json").is_file()
    assert not observed["profile_kwargs"]


def test_partial_separation_coverage_cannot_admit_an_unproven_root(construction_fixture):
    context, observed = construction_fixture
    context.config["construction"]["root_impact_validation"] = "separated_roots"
    observed["certificate"]["root_impacts"].pop()
    with pytest.raises(TaskRejected, match="does not prove every declared root"):
        module.ConstructNode().execute(context)
    assert observed["calculations"] == 1


def test_unknown_root_validation_method_is_a_configuration_error():
    with pytest.raises(ValueError, match="root_impact_validation"):
        module.construction_contract(config={"construction": {"root_impact_validation": "skip_checks"}})
