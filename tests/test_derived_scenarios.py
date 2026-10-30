"""Offline catalog and observed-regime tests using explicit synthetic records.

The saved-ledger-shaped fixtures below are mechanism probes, not financially
audited models. Batch orchestration tests use explicitly labeled dummy files
and an injected stub builder. They never emit a real workbook, recalculate in
LibreOffice, or provide evidence of financial validity or qualification.
"""

from copy import deepcopy
import importlib.util
import hashlib
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
REGIMES = {
    "revolver_draw", "revolver_repayment", "loan_a_extra_principal",
    "annual_nol_added", "annual_nol_used", "loan_a_zero_rate", "loan_a_paid_off",
    "year_one_bullet", "commissioning_crosses_tax_year", "nol_utilization_cap_binding",
    "initial_basis_exhausted", "refresh_payment_service_cross_tax_year",
    "refresh_basis_exhausted", "full_sweep_allocation",
}


@pytest.fixture
def api(monkeypatch):
    """Import the guarded script without executing its command-line entry point."""
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    path = ROOT / "scripts/build_derived_scenarios.py"
    module_spec = importlib.util.spec_from_file_location("_offline_derived_scenarios", path)
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    monkeypatch.setitem(sys.modules, module_spec.name, module)
    module_spec.loader.exec_module(module)
    return module


@pytest.fixture
def catalog_files(tmp_path):
    """Config-only fixture: the declared source workbook intentionally does not exist."""
    directory = tmp_path / "config"
    directory.mkdir()
    base = json.loads((ROOT / "config/derived_gold_project_v1.json").read_text())
    base["scenario_id"] = "explicit-offline-catalog-fixture"
    base["source"]["local_path"] = "missing-fixture-source.xlsx"
    base["source"]["sha256"] = "0" * 64
    (directory / "base.json").write_text(json.dumps(base))
    catalog = {
        "schema_version": 1,
        "base_config": "config/base.json",
        "verification_status": "not_verified",
        "cases": [
            {"id": "S01", "name": "Offline baseline fixture", "mechanism": "Catalog probe only",
             "parameter_patch": {}, "required_regimes": ["revolver_draw"]},
            {"id": "S02", "name": "Offline bullet fixture", "mechanism": "Catalog probe only",
             "parameter_patch": {"loan_b_bullet_month": 12, "revolver_limit": 8000000},
             "required_regimes": ["year_one_bullet"]},
            {"id": "S03", "name": "Offline rate fixture", "mechanism": "Catalog probe only",
             "parameter_patch": {"loan_a_spread": "-0.0509"},
             "required_regimes": ["loan_a_zero_rate"]},
        ],
    }
    path = directory / "cases.json"
    path.write_text(json.dumps(catalog))
    return tmp_path, path, catalog, base


@pytest.fixture
def saved_regime_fixture():
    """Thirty-six JSON-compatible rows, with every observed mechanism inactive."""
    parameters = json.loads((ROOT / "config/derived_gold_project_v1.json").read_text())["hypothetical_parameters"]
    parameters.update({
        "loan_a_annual_rate": "0.06", "loan_b_annual_rate": "0.08",
        "revolver_annual_rate": "0.09", "annual_equity_discount_rate": "0.12",
        "cash_ebitda_margin": "0.25",
    })
    monthly = []
    for period in range(1, 37):
        year, month = (period - 1) // 12 + 1, (period - 1) % 12 + 1
        monthly.append({
            "period": period, "year": year, "date": f"{2026 + year}-{month:02d}-01",
            "sales": "0", "loan_a_open": "100.00", "loan_a_close": "100.00",
            "loan_a_interest": "0.50", "loan_a_extra_principal": "0",
            "loan_b_principal": "0", "revolver_draw": "0", "revolver_repayment": "0",
            "ebt": "0", "nol_add": "0", "nol_use": "0", "nol_open": "0", "nol_close": "0",
            "depreciation_initial": "0", "depreciation_refresh": "0", "capex": "0",
            "cash_before_allocation": "500000", "cash_close": "500000", "dividend": "0",
        })
    return {"parameters": parameters}, {"monthly": monthly, "annual": []}


def _assert_observation(report, key, observed, period=None):
    item = report[key]
    assert item["observed"] is observed
    assert isinstance(item["periods"], list)
    assert all(isinstance(value, int) for value in item["periods"])
    assert isinstance(item["evidence"], str) and item["evidence"].strip()
    if period is not None:
        assert period in item["periods"]


def test_catalog_loads_and_selects_subset_without_opening_the_source(api, catalog_files):
    root, path, expected, base = catalog_files
    catalog, loaded_base, all_cases = api.load_catalog(root, path)
    assert catalog["schema_version"] == 1
    assert loaded_base == base
    assert {case["id"] for case in all_cases} == {"S01", "S02", "S03"}
    _, _, selected = api.load_catalog(root, path, ["S03", "S01"])
    assert {case["id"] for case in selected} == {"S01", "S03"}
    assert json.loads(path.read_text()) == expected
    assert not (root / "missing-fixture-source.xlsx").exists()


def test_catalog_rejects_duplicate_case_ids(api, catalog_files):
    root, path, catalog, _ = catalog_files
    catalog["cases"].append(deepcopy(catalog["cases"][0]))
    path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError):
        api.load_catalog(root, path)


@pytest.mark.parametrize("unsafe_id", ["../S01", "S01/child", "S01\\child", "..", "/tmp/S01", "S01\nother"])
def test_catalog_rejects_path_unsafe_case_ids(api, catalog_files, unsafe_id):
    root, path, catalog, _ = catalog_files
    catalog["cases"][0]["id"] = unsafe_id
    path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError):
        api.load_catalog(root, path)


@pytest.mark.parametrize("invalid_field", ["patch", "regime"])
def test_catalog_rejects_unknown_patch_parameters_and_regimes(api, catalog_files, invalid_field):
    root, path, catalog, _ = catalog_files
    if invalid_field == "patch":
        catalog["cases"][0]["parameter_patch"]["unlisted_cash_source"] = 1000000
    else:
        catalog["cases"][0]["required_regimes"].append("automatic_balance_sheet_plug")
    path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError):
        api.load_catalog(root, path)


def test_catalog_rejects_unknown_subset_even_if_other_requested_cases_exist(api, catalog_files):
    root, path, _, _ = catalog_files
    with pytest.raises(ValueError):
        api.load_catalog(root, path, ["S01", "S99"])


def test_regime_profile_does_not_treat_zero_filled_rows_as_activation(api, saved_regime_fixture):
    spec, ledger = saved_regime_fixture
    report = api.observed_regimes(spec, ledger)
    assert set(report) == REGIMES
    for key in REGIMES:
        _assert_observation(report, key, False)


def test_regime_profile_reads_observed_saved_events_and_their_periods(api, saved_regime_fixture):
    spec, ledger = saved_regime_fixture
    events = {
        "revolver_draw": (7, "revolver_draw", "50.00"),
        "revolver_repayment": (8, "revolver_repayment", "20.00"),
        "loan_a_extra_principal": (9, "loan_a_extra_principal", "5.00"),
        "annual_nol_added": (12, "nol_add", "30.00"),
        "annual_nol_used": (24, "nol_use", "10.00"),
    }
    for period, field, value in events.values():
        ledger["monthly"][period - 1][field] = value
    snapshot = deepcopy((spec, ledger))
    report = api.observed_regimes(spec, ledger)
    for key, (period, _, _) in events.items():
        _assert_observation(report, key, True, period)
    assert (spec, ledger) == snapshot


def test_nol_cap_activation_requires_annual_income_and_excess_opening_nol(api, saved_regime_fixture):
    spec, ledger = saved_regime_fixture
    spec["parameters"]["opening_nol"] = "200.00"
    spec["parameters"]["nol_utilization_cap"] = "0.8"
    ledger["monthly"][0]["ebt"] = "70.00"
    ledger["monthly"][1]["ebt"] = "30.00"
    for row in ledger["monthly"][:12]:
        row["nol_open"] = row["nol_close"] = "200.00"
    ledger["monthly"][11].update({"nol_use": "80.00", "nol_close": "120.00"})
    _assert_observation(api.observed_regimes(spec, ledger), "nol_utilization_cap_binding", True, 12)
    # Using all available40 when the annual cap is80 is NOL use, not a binding cap.
    spec["parameters"]["opening_nol"] = "40.00"
    for row in ledger["monthly"][:12]:
        row["nol_open"] = row["nol_close"] = "40.00"
    ledger["monthly"][11].update({"nol_use": "40.00", "nol_close": "0.00"})
    report = api.observed_regimes(spec, ledger)
    _assert_observation(report, "annual_nol_used", True, 12)
    _assert_observation(report, "nol_utilization_cap_binding", False)


def test_full_sweep_can_be_observed_without_asserting_loan_payoff(api, saved_regime_fixture):
    spec, ledger = saved_regime_fixture
    spec["parameters"]["cash_sweep_fraction"] = "1"
    ledger["monthly"][6].update({
        "cash_before_allocation": "500030.00", "loan_a_extra_principal": "30.00",
        "loan_a_open": "100.00", "loan_a_close": "70.00", "dividend": "0.00",
    })
    report = api.observed_regimes(spec, ledger)
    _assert_observation(report, "full_sweep_allocation", True)
    _assert_observation(report, "loan_a_paid_off", False)


def test_vintage_exhaustion_and_cross_year_service_use_real_ledger_field_names(api, saved_regime_fixture):
    spec, ledger = saved_regime_fixture
    spec["parameters"].update({
        "initial_asset_cost": "100.00", "initial_asset_life": 2,
        "refresh_capex": "60.00", "refresh_paid_month": 15,
        "refresh_service_month": 25, "refresh_life": 6,
    })
    ledger["monthly"][6]["depreciation_initial"] = "50.00"
    ledger["monthly"][7]["depreciation_initial"] = "50.00"
    ledger["monthly"][14]["capex"] = "60.00"
    for row in ledger["monthly"][24:30]:
        row["depreciation_refresh"] = "10.00"
    report = api.observed_regimes(spec, ledger)
    for key in ("initial_basis_exhausted", "refresh_basis_exhausted", "refresh_payment_service_cross_tax_year"):
        _assert_observation(report, key, True)


def test_rate_bullet_and_commissioning_regimes_remain_distinct(api, saved_regime_fixture):
    spec, ledger = saved_regime_fixture
    spec["parameters"].update({
        "loan_a_annual_rate": "0", "loan_b_bullet_month": 12,
        "construction_months": 12, "initial_asset_service_month": 13, "loan_a_amort_start": 13,
    })
    for row in ledger["monthly"]:
        row["loan_a_interest"] = "0"
    ledger["monthly"][11]["loan_b_principal"] = "3000000.00"
    ledger["monthly"][12]["sales"] = "100.00"
    report = api.observed_regimes(spec, ledger)
    for key in ("loan_a_zero_rate", "year_one_bullet", "commissioning_crosses_tax_year"):
        _assert_observation(report, key, True)
    ledger["monthly"][11]["loan_b_principal"] = "0"
    ledger["monthly"][35]["loan_b_principal"] = "3000000.00"
    _assert_observation(api.observed_regimes(spec, ledger), "year_one_bullet", False)


@pytest.fixture
def stub_environment(catalog_files):
    """Dummy ancestry bytes allow orchestration tests, not source validation."""
    root, catalog_path, catalog, base = catalog_files
    source = root / "dummy_test_ancestor.xlsx"
    source.write_bytes(b"OFFLINE TEST FIXTURE - NOT AN EXCEL FILE")
    base["source"]["local_path"] = str(source)
    base["source"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    (root / "config/base.json").write_text(json.dumps(base))
    return root, catalog_path, catalog, base


def _dummy_receipt_builder(root, config_path, output):
    """Write explicit synthetic receipts to test rejection logic, never real LO."""
    config = json.loads(config_path.read_text())
    output.mkdir(parents=True)
    (output / "private").mkdir()
    model = output / "project_model.xlsx"
    model.write_bytes(b"OFFLINE RECEIPT FIXTURE; NOT A REAL WORKBOOK " + config["scenario_id"].encode())
    p = deepcopy(config["hypothetical_parameters"])
    p.update({"loan_a_annual_rate": "0" if p["loan_a_spread"] == "-0.0509" else ".0609"})
    row = {"period": 12, "loan_a_open": "100", "loan_a_close": "99",
           "loan_a_interest": "0" if p["loan_a_annual_rate"] == "0" else ".5",
           "revolver_draw": "10", "loan_b_principal": "30" if p["loan_b_bullet_month"] == 12 else "0"}
    checks = {"feasible": True, "all_balanced": True, "max_balance_error": "0",
              "max_cfo_reconciliation_error": "0", "max_cash_reconciliation_error": "0",
              "max_income_reconciliation_error": "0", "minimum_cash_gap": "0",
              "max_journal_error": "0", "loan_a_payment_residual": "0",
              "irr_exists": True, "irr_sign_changes": 1}
    source_lineage = {"sha256": config["source"]["sha256"], "fixture_only": True}
    manifest = {"fixture_only": True, "scenario_id": config["scenario_id"],
                "financial_audit_passed": True, "source_ancestor_sha256": config["source"]["sha256"],
                "source_lineage": source_lineage, "derived_workbook_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
                "sheet_count": 4, "nonempty_sheet_count": 4, "formula_count": 1}
    audit = {"fixture_only": True, "passed": True, "checked_cells": 1, "formula_count": 1,
             "all_formula_cells_independently_covered": True, "all_ledger_invariants_passed": True,
             "two_recalculations_typed_stable": True, "mismatches": [], "uncovered_formulas": [],
             "invalid_formula_values": [], "independent_ledger_checks": checks,
             "cell_checks": [{"address": "OfflineFixture!A1", "passed": True}]}
    objects = {"derived_seed_manifest.json": manifest,
               "public_scenario.json": {"fixture_only": True, "scenario_id": config["scenario_id"], "source_lineage": source_lineage,
                                         "parameters": p, "public_rules": ["Offline fixture, not a financial model."]},
               "private/financial_audit.json": audit,
               "private/ledger.json": {"fixture_only": True, "checks": checks, "monthly": [row]},
               "private/bindings.json": {"fixture_only": True},
               "private/profile.json": {"fixture_only": True, "nonempty_sheet_count": 4, "formula_count": 1, "truncated": False, "errors": []},
               "private/stability.json": {"fixture_only": True, "reward": 1}}
    for name, value in objects.items():
        (output / name).write_text(json.dumps(value))
    return manifest


def test_injected_receipts_cannot_enter_production_selected_list(api, stub_environment):
    root, path, _, _ = stub_environment
    result = api.build_scenarios(root, path, root / "output", builder=_dummy_receipt_builder)
    assert result["ancestor_unique_count"] == 1
    assert result["attempted_scenario_count"] == 3
    assert result["accepted_offline_fixture_count"] == 3
    assert result["selected"] == []
    assert result["selected_derived_workbook_count"] == result["selected_ancestor_unique_count"] == 0
    assert not result["qualified"] and result["task_count"] == 0
    assert result["api_calls"] == result["llm_tokens"] == 0
    for case in result["cases"]:
        entry = case["offline_fixture_entry"]
        assert not entry["finance_eligible"] and not entry["finance_evidence"]["financial_modeling_eligible"]
        assert entry["verification_backend"] == "offline_test_fixture_not_real_LO"
        for proof in entry["finance_evidence"]["audit_proofs"].values():
            assert hashlib.sha256(Path(proof["path"]).read_bytes()).hexdigest() == proof["sha256"]


def test_subset_build_passes_only_explicit_case_parameters(api, stub_environment):
    root, path, _, base = stub_environment
    seen = []
    def builder(project_root, config_path, output):
        seen.append(json.loads(config_path.read_text()))
        return _dummy_receipt_builder(project_root, config_path, output)
    result = api.build_scenarios(root, path, root / "output", ["S02"], builder=builder)
    assert result["attempted_scenario_count"] == len(seen) == 1
    assert seen[0]["hypothetical_parameters"]["loan_b_bullet_month"] == 12
    assert seen[0]["hypothetical_parameters"]["equity_paid_in"] == base["hypothetical_parameters"]["equity_paid_in"]
    assert set(result["cases"][0]["parameter_diff"]) == {"loan_b_bullet_month", "revolver_limit"}


def test_case_failure_is_retained_and_does_not_stop_other_cases(api, stub_environment):
    root, path, _, _ = stub_environment
    def builder(project_root, config_path, output):
        if json.loads(config_path.read_text())["scenario_id"].endswith("-s02"):
            raise ValueError("Explicit fixture liquidity failure in period 12")
        return _dummy_receipt_builder(project_root, config_path, output)
    result = api.build_scenarios(root, path, root / "output", builder=builder)
    assert result["rejected_scenario_count"] == 1
    assert result["accepted_offline_fixture_count"] == 2
    rejected = result["cases"][1]
    assert rejected["status"] == "rejected" and not rejected["financial_checks_passed"]
    assert "liquidity failure" in rejected["error"]["message"]
    assert (root / "output/cases/S02/requested_config.json").is_file()
    assert (root / "output/cases/S02/case_result.json").is_file()


@pytest.mark.parametrize("defect", ["missing_audit", "workbook_hash", "failed_identity", "failing_cell", "stability"])
def test_incomplete_or_changed_receipts_are_rejected(api, stub_environment, defect):
    root, path, _, _ = stub_environment
    def builder(project_root, config_path, output):
        seed = _dummy_receipt_builder(project_root, config_path, output)
        if defect == "missing_audit":
            (output / "private/financial_audit.json").unlink()
        elif defect == "workbook_hash":
            (output / "project_model.xlsx").write_bytes(b"CHANGED AFTER FIXTURE RECEIPT")
        else:
            relative = "private/stability.json" if defect == "stability" else "private/financial_audit.json"
            file = output / relative
            value = json.loads(file.read_text())
            if defect == "stability":
                value["reward"] = 0
            elif defect == "failed_identity":
                value["independent_ledger_checks"]["max_cash_reconciliation_error"] = ".01"
            else:
                value["cell_checks"][0]["passed"] = False
            file.write_text(json.dumps(value))
        return seed
    result = api.build_scenarios(root, path, root / "output", ["S01"], builder=builder)
    assert result["rejected_scenario_count"] == 1
    assert result["cases"][0]["status"] == "rejected"
    assert result["cases"][0]["retained_evidence"]


def test_intended_but_unobserved_regime_rejects_even_with_passing_fixture_receipt(api, stub_environment):
    root, path, _, _ = stub_environment
    def builder(project_root, config_path, output):
        seed = _dummy_receipt_builder(project_root, config_path, output)
        file = output / "private/ledger.json"
        value = json.loads(file.read_text())
        value["monthly"][0]["loan_b_principal"] = "0"
        file.write_text(json.dumps(value))
        return seed
    result = api.build_scenarios(root, path, root / "output", ["S02"], builder=builder)
    case = result["cases"][0]
    assert case["financial_checks_passed"]
    assert case["status"] == "rejected"
    assert case["actual_regimes"]["year_one_bullet"]["observed"] is False
    assert case["untriggered_required_regimes"] == ["year_one_bullet"]


def test_existing_output_refused_without_overwriting(api, stub_environment):
    root, path, _, _ = stub_environment
    output = root / "output"
    api.build_scenarios(root, path, output, ["S01"], builder=_dummy_receipt_builder)
    digest = hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="already exists"):
        api.build_scenarios(root, path, output, ["S01"], builder=_dummy_receipt_builder)
    assert hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest() == digest


def test_ancestor_mutation_blocks_before_creating_output(api, stub_environment):
    root, path, _, base = stub_environment
    Path(base["source"]["local_path"]).write_bytes(b"CHANGED ANCESTOR")
    with pytest.raises(ValueError, match="ancestor source SHA256"):
        api.build_scenarios(root, path, root / "output", builder=_dummy_receipt_builder)
    assert not (root / "output").exists()


def test_ten_case_catalog_remains_design_only_and_funding_patch_is_explicit(api):
    catalog, base, cases = api.load_catalog(ROOT, ROOT / "config/derived_financial_scenarios.json")
    assert catalog["verification_status"] == "not_verified"
    assert len(cases) == 10
    assert len({case["mechanism"] for case in cases}) == 10
    nol = next(case for case in cases if case["id"] == "S06")
    assert nol["parameter_patch"]["equity_paid_in"] - base["hypothetical_parameters"]["equity_paid_in"] == 2000000
    assert nol["parameter_patch"]["opening_cash"] - base["hypothetical_parameters"]["opening_cash"] == 2000000
