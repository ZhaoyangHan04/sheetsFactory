import copy

import pytest

from sheets_factory.checkers import DiagnosisRunner
from sheets_factory.checkers.router import route_issues


def bundle():
    return {"task_id": "fixture", "revision_hash": "rev-a", "public": {"instruction": "Restore revenue"},
            "private": {"secret_formula": "=B2*C2"},
            "engine_report": {"normalization_ok": True, "recalculation_ok": True, "stable": True},
            "infrastructure_health_report": {"healthy": True, "checks": [{"tool": "docker", "exit_code": 0}]}}


def controls():
    return {"oracle": 1, "nop": 0, "equivalent": 1, "missed_root": 0, "extra_change": 0}


def reviewer(payload):
    return {"assessments": [{"check_id": check, "state": "clear", "reason": "Fixture evidence reviewed",
                              "evidence": ["fixture/public-rule-and-cell-probe"]}
                             for check in payload["assigned_check_ids"]], "issues": []}


def test_default_all_grouped_and_private_isolation():
    runner = DiagnosisRunner()
    seen = []

    def inspect(payload):
        seen.append(payload)
        if payload["visibility"] == "public_only":
            assert "private" not in payload
            assert "secret_formula" not in str(payload)
        return reviewer(payload)

    report = runner.diagnose(bundle(), [{"reward": 1, "completed_successfully": True, "events": []}], controls(), inspect,
                             {"difficulty_deferred": True})
    assert len(seen) == 2
    assert len(report["assessments"]) == 12
    assert report["assessments"]["Q08"]["state"] == "not_applicable"
    assert "reward" not in str(seen[0]["traces"])
    assert report["releasable"]


def test_selected_checks_are_skipped_and_per_check_batched():
    runner = DiagnosisRunner()
    report = runner.diagnose(bundle(), [], {}, reviewer,
        {"selection": {"include": ["Q01", "Q02", "Q07"]}, "execution": {"llm_batching": "per_check"}})
    assert len(report["llm_batches"]) == 3
    assert report["assessments"]["Q05"]["state"] == "skipped"
    assert report["scope"] == "selected"
    assert report["releasable"]


def test_missing_program_evidence_never_defaults_to_clear():
    report = DiagnosisRunner().diagnose({"public": {}}, [], {}, reviewer)
    assert report["assessments"]["Q05"]["state"] == "unknown"
    assert report["assessments"]["Q10"]["state"] == "unknown"
    assert report["assessments"]["Q11"]["state"] == "unknown"
    assert report["assessments"]["Q12"]["state"] == "flagged"
    assert not report["releasable"]


def test_control_failure_is_not_overridden_by_llm():
    values = controls()
    values["extra_change"] = 1
    report = DiagnosisRunner().diagnose(bundle(), [], values, reviewer)
    assert report["assessments"]["Q05"]["state"] == "flagged"
    assert report["routes"][0]["route_id"] == "R05"
    assert not report["releasable"]


@pytest.mark.parametrize("bad_result", [
    {"assessments": []},
    {"assessments": [{"check_id": "Q01", "state": "clear", "reason": "x", "evidence": ["x"]}]},
    {"accept": True, "assessments": []},
])
def test_bad_batch_results_are_unknown_not_success(bad_result):
    report = DiagnosisRunner().diagnose(bundle(), [], controls(), lambda _: bad_result)
    assert not report["releasable"]
    assert report["assessments"]["Q01"]["state"] == "unknown"


def test_suspected_issue_routes_to_evidence_not_content_repair():
    runner = DiagnosisRunner()
    routes = route_issues([{"issue_id": "a", "problem_id": "Q01", "certainty": "suspected"}], runner.catalog)
    assert routes[0]["route_id"] == "R12"


def test_dependency_order_overrides_route_priority():
    runner = DiagnosisRunner()
    routes = route_issues([
        {"issue_id": "a", "problem_id": "Q12", "certainty": "confirmed", "depends_on_issue_ids": ["b"]},
        {"issue_id": "b", "problem_id": "Q08", "certainty": "confirmed"}], runner.catalog)
    assert [r["issue_id"] for r in routes] == ["b", "a"]


def test_unknown_checker_and_duplicate_selection_fail():
    runner = DiagnosisRunner()
    with pytest.raises(ValueError):
        runner.resolve({"selection": {"include": ["Q99"]}})
    with pytest.raises(ValueError):
        runner.resolve({"selection": {"include": ["Q01", "Q01"]}})


def test_all_in_one_still_separates_visibility():
    plan = DiagnosisRunner().resolve({"execution": {"llm_batching": "all_in_one"}})
    assert len(plan["batches"]) == 2


def test_completion_and_reward_do_not_change_routing():
    runner = DiagnosisRunner()
    a = runner.diagnose(bundle(), [{"reward": 0, "completion_status": "partial"}], controls(), reviewer)
    b = runner.diagnose(bundle(), [{"reward": 1, "completion_status": "complete"}], controls(), reviewer)
    assert a["assessments"] == b["assessments"]
    assert a["routes"] == b["routes"]
