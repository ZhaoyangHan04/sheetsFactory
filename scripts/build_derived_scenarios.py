#!/usr/bin/env python3
"""Build explicit hypothetical financial seeds, never qualified tasks.

Each requested case uses the existing independent-ledger/real-LibreOffice
builder. Financially invalid cases and unobserved intended mechanisms are
retained as rejections. No assumptions are repaired or invented here.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import time
import uuid

from sheets_factory.workbook.derived_gold.validate import ledger_invariants_pass


REGIME_KEYS = {
    "revolver_draw", "revolver_repayment", "loan_a_extra_principal",
    "annual_nol_added", "annual_nol_used", "loan_a_zero_rate", "loan_a_paid_off",
    "year_one_bullet", "commissioning_crosses_tax_year", "nol_utilization_cap_binding",
    "initial_basis_exhausted", "refresh_payment_service_cross_tax_year",
    "refresh_basis_exhausted", "full_sweep_allocation",
}
CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
AUDIT_FILES = ("project_model.xlsx", "public_scenario.json", "derived_seed_manifest.json",
               "private/financial_audit.json", "private/ledger.json", "private/bindings.json",
               "private/profile.json", "private/stability.json")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path):
    return json.loads(path.read_text())


def _write(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def _number(value) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a financial number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("A finite financial number is required") from exc
    if not result.is_finite():
        raise ValueError("A finite financial number is required")
    return result


def _same_parameter(left, right) -> bool:
    if isinstance(left, list) or isinstance(right, list):
        return (isinstance(left, list) and isinstance(right, list) and len(left) == len(right)
                and all(_same_parameter(a, b) for a, b in zip(left, right)))
    try:
        return _number(left) == _number(right)
    except ValueError:
        return isinstance(left, str) and isinstance(right, str) and left == right


def load_catalog(project_root: Path, catalog_path: Path, case_ids: list[str] | None = None):
    """Validate all configuration before creating any output directory."""
    project_root = Path(project_root).resolve()
    catalog_path = Path(catalog_path)
    if not catalog_path.is_absolute():
        catalog_path = project_root / catalog_path
    catalog = _json(catalog_path)
    if catalog.get("schema_version") != 1 or not isinstance(catalog.get("cases"), list) or not catalog["cases"]:
        raise ValueError("A schema_version=1 catalog with nonempty cases is required")
    base_path = Path(catalog["base_config"])
    if not base_path.is_absolute():
        base_path = project_root / base_path
    base = _json(base_path)
    allowed = set(base["hypothetical_parameters"])
    seen = set()
    for case in catalog["cases"]:
        identifier = case.get("id")
        if not isinstance(identifier, str) or not CASE_ID.fullmatch(identifier):
            raise ValueError("Unsafe or invalid case ID")
        if identifier in seen:
            raise ValueError("Duplicate case ID: " + identifier)
        seen.add(identifier)
        patch = case.get("parameter_patch")
        if not isinstance(patch, dict) or set(patch) - allowed:
            raise ValueError("Unknown or invalid parameter patch for " + identifier)
        if not case.get("name") or not case.get("mechanism"):
            raise ValueError("Every case needs a public name and mechanism")
        required = case.get("required_regimes")
        if (not isinstance(required, list) or not required
                or any(not isinstance(k, str) or k not in REGIME_KEYS for k in required)
                or len(required) != len(set(required))):
            raise ValueError("Unknown, duplicate or empty required_regimes for " + identifier)
        # All keys must be explicit; the builder will validate financial feasibility.
        for key, value in patch.items():
            if key == "start_date":
                if not isinstance(value, str):
                    raise ValueError("start_date must be explicit ISO text")
            elif isinstance(value, list):
                for item in value:
                    _number(item)
            else:
                _number(value)
    if case_ids is not None:
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Duplicate requested case ID")
        if not case_ids or set(case_ids) - seen:
            raise ValueError("Unknown or empty requested case subset")
        chosen = set(case_ids)
        cases = [case for case in catalog["cases"] if case["id"] in chosen]
    else:
        cases = catalog["cases"][:]
    return catalog, base, cases


def observed_regimes(spec: dict, ledger: dict) -> dict:
    """Describe observed independent-ledger events, never intentions alone."""
    p, rows = spec["parameters"], ledger["monthly"]
    value = lambda row, key: _number(row.get(key, 0))
    period = lambda row: int(row["period"])
    out = {}

    def record(key, periods, explanation):
        periods = sorted(set(periods))
        out[key] = {"observed": bool(periods), "periods": periods, "evidence": explanation}

    for key in ("revolver_draw", "revolver_repayment", "loan_a_extra_principal"):
        record(key, [period(r) for r in rows if value(r, key) > 0], "Actual positive posted " + key)
    for label, key in (("annual_nol_added", "nol_add"), ("annual_nol_used", "nol_use")):
        record(label, [period(r) for r in rows if period(r) % 12 == 0 and value(r, key) > 0],
               "Actual year-end NOL ledger posting")
    zero_rate = _number(p.get("loan_a_annual_rate", 0)) == 0
    record("loan_a_zero_rate", [period(r) for r in rows if zero_rate and value(r, "loan_a_open") > 0
           and value(r, "loan_a_interest") == 0], "Zero stated rate, positive opening debt and zero cash interest")
    record("loan_a_paid_off", [period(r) for r in rows if value(r, "loan_a_open") > 0
           and value(r, "loan_a_close") == 0], "Positive opening Loan A reaches zero closing principal")
    record("year_one_bullet", [period(r) for r in rows if period(r) <= 12
           and value(r, "loan_b_principal") > 0], "Actual Loan B principal payment in year one")
    sales_periods = [period(r) for r in rows if value(r, "sales") > 0]
    record("commissioning_crosses_tax_year", sales_periods[:1] if sales_periods and min(sales_periods) > 12 else [],
           "First positive operating sales occur after the first tax year")
    cap_periods = []
    cap = _number(p.get("nol_utilization_cap", 0))
    for row in rows:
        t = period(row)
        if t % 12:
            continue
        ebt = sum((value(r, "ebt") for r in rows if t - 12 < period(r) <= t), Decimal(0))
        capped = (max(ebt, Decimal(0)) * cap).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        used = value(row, "nol_use")
        if 0 < cap < 1 and used > 0 and value(row, "nol_open") > used and used == capped:
            cap_periods.append(t)
    record("nol_utilization_cap_binding", cap_periods, "Actual use equals income-based cap while opening NOL remains unused")

    def exhausted(key, cost):
        cumulative = Decimal(0)
        result = []
        for row in rows:
            cumulative += value(row, key)
            if cost > 0 and cumulative == cost and value(row, key) > 0 and any(
                    period(later) > period(row) and value(later, key) == 0 for later in rows):
                result.append(period(row))
        return result

    record("initial_basis_exhausted", exhausted("depreciation_initial", _number(p.get("initial_asset_cost", 0))),
           "Posted initial depreciation reaches cost and a later period stops depreciation")
    record("refresh_basis_exhausted", exhausted("depreciation_refresh", _number(p.get("refresh_capex", 0))),
           "Posted refresh depreciation reaches cost and a later period stops depreciation")
    paid = [period(r) for r in rows if value(r, "capex") > 0]
    serviced = [period(r) for r in rows if value(r, "depreciation_refresh") > 0]
    cross_year = bool(paid and serviced and (min(paid) - 1) // 12 != (min(serviced) - 1) // 12)
    record("refresh_payment_service_cross_tax_year", [min(paid), min(serviced)] if cross_year else [],
           "Actual refresh capex payment and first depreciation posting occur in different tax years")
    record("full_sweep_allocation", [period(r) for r in rows if _number(p.get("cash_sweep_fraction", 0)) == 1
           and value(r, "loan_a_extra_principal") > 0], "100% stated sweep has actual optional principal allocations")
    return out


def _load_builder(project_root):
    location = project_root / "scripts/build_derived_gold.py"
    spec = importlib.util.spec_from_file_location("sheets_factory_frozen_derived_builder", location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build


def _inspect_case(directory: Path, config: dict, returned: dict) -> tuple[dict, dict, dict]:
    """Check complete persisted receipts from the frozen real-LO builder."""
    for relative in AUDIT_FILES:
        if not (directory / relative).is_file():
            raise ValueError("Missing financial evidence: " + relative)
    manifest = _json(directory / "derived_seed_manifest.json")
    audit = _json(directory / "private/financial_audit.json")
    ledger = _json(directory / "private/ledger.json")
    profile = _json(directory / "private/profile.json")
    stability = _json(directory / "private/stability.json")
    public = _json(directory / "public_scenario.json")
    expected_source = config["source"]["sha256"]
    if public.get("scenario_id") != config["scenario_id"] or manifest.get("scenario_id") != config["scenario_id"]:
        raise ValueError("Financial evidence belongs to a different scenario")
    if (manifest.get("source_ancestor_sha256") != expected_source
            or manifest.get("source_lineage", {}).get("sha256") != expected_source
            or public.get("source_lineage", {}).get("sha256") != expected_source):
        raise ValueError("Financial evidence source lineage mismatch")
    if manifest.get("derived_workbook_sha256") != _sha(directory / "project_model.xlsx"):
        raise ValueError("Derived workbook hash differs from financial evidence")
    for key, expected in config["hypothetical_parameters"].items():
        if key not in public.get("parameters", {}) or not _same_parameter(public["parameters"][key], expected):
            raise ValueError("Public parameter differs from explicit case config: " + key)
    checks = audit.get("cell_checks", [])
    if (not isinstance(checks, list) or not checks
            or len(checks) != audit.get("checked_cells")
            or len({r.get("address") for r in checks}) != len(checks)
            or any(r.get("passed") is not True for r in checks)):
        raise ValueError("Incomplete or failing independent cell checks")
    if (returned.get("financial_audit_passed") is not True
            or manifest.get("financial_audit_passed") is not True
            or audit.get("passed") is not True
            or audit.get("all_formula_cells_independently_covered") is not True
            or audit.get("all_ledger_invariants_passed") is not True
            or audit.get("two_recalculations_typed_stable") is not True
            or audit.get("mismatches") != [] or audit.get("uncovered_formulas") != []
            or audit.get("invalid_formula_values") != []
            or not ledger_invariants_pass(audit.get("independent_ledger_checks", {}))
            or not ledger_invariants_pass(ledger.get("checks", {}))):
        raise ValueError("Independent financial validation did not pass completely")
    if (profile.get("nonempty_sheet_count", 0) < 4 or profile.get("truncated") is not False
            or profile.get("errors") != [] or stability.get("reward") != 1
            or isinstance(stability.get("reward"), bool)
            or audit.get("formula_count", 0) <= 0
            or audit["formula_count"] != profile.get("formula_count")
            or len(checks) < audit["formula_count"]):
        raise ValueError("Workbook profile, formula coverage or LO stability is invalid")
    return manifest, public, ledger


def _proofs(directory):
    return {name: {"path": str((directory / name).resolve()), "sha256": _sha(directory / name)}
            for name in AUDIT_FILES}


def build_scenarios(project_root: Path, catalog_path: Path, output: Path,
                    case_ids: list[str] | None = None, *, builder=None) -> dict:
    """Create a new batch. ``builder`` injection is for explicit offline tests only."""
    project_root, output = Path(project_root).resolve(), Path(output).resolve()
    catalog_path = Path(catalog_path)
    if not catalog_path.is_absolute():
        catalog_path = project_root / catalog_path
    catalog, base, cases = load_catalog(project_root, catalog_path, case_ids)
    source = Path(base["source"]["local_path"])
    if not source.is_absolute():
        source = project_root / source
    if _sha(source) != base["source"]["sha256"]:
        raise ValueError("Original ancestor source SHA256 does not match base config")
    if output.exists():
        raise ValueError("Output already exists; use a new immutable batch directory")
    output.mkdir(parents=True)
    injected = builder is not None
    builder = builder or _load_builder(project_root)
    backend = "offline_test_fixture_not_real_LO" if injected else "independent_Decimal_and_real_LibreOffice"
    manifest = {"schema_version": 1, "dataset": "derived_financial_scenarios_planning_seeds",
                "created_at": datetime.now(timezone.utc).isoformat(), "status": "building",
                "verification_backend": backend, "qualified": False, "task_count": 0,
                "catalog": {"path": str(catalog_path.resolve()), "sha256": _sha(catalog_path)},
                "base_config": catalog["base_config"], "source_ancestor_sha256": base["source"]["sha256"],
                "builder_recipe": {"path": str((project_root / "scripts/build_derived_gold.py").resolve()),
                                   "sha256": _sha(project_root / "scripts/build_derived_gold.py") if not injected else None},
                "source_ancestor": base["source"], "requested_case_ids": [c["id"] for c in cases],
                "selected": [], "cases": [], "ancestor_unique_count": 1,
                "selected_ancestor_unique_count": 0, "selected_derived_workbook_count": 0,
                "source_finance_eligible_meaning": "May be planned only; no task, quality, controls or difficulty qualification.",
                "requirements_before_task_admission": "All normal Q checks, public-only recovery, actual Harbor oracle/nop and specified strongest-agent difficulty gates remain mandatory."}
    _write(output / "manifest.json", manifest)
    started = time.monotonic()
    for case in cases:
        case_started = time.monotonic()
        directory = output / "cases" / case["id"]
        directory.mkdir(parents=True)
        config = deepcopy(base)
        config["scenario_id"] = base["scenario_id"] + "-" + case["id"].lower()
        config["hypothetical_parameters"].update(deepcopy(case["parameter_patch"]))
        config["case_description"] = {k: case[k] for k in ("id", "name", "mechanism")}
        config_path = directory / "requested_config.json"
        _write(config_path, config)
        result = {"id": case["id"], "name": case["name"], "mechanism": case["mechanism"],
                  "qualified": False, "task_count": 0, "status": "rejected",
                  "financial_checks_passed": False,
                  "actual_regimes_status": "unavailable_until_financial_audit_passes",
                  "required_regimes": case["required_regimes"],
                  "parameter_diff": {k: {"before": base["hypothetical_parameters"][k], "after": v}
                                     for k, v in case["parameter_patch"].items()},
                  "requested_config": {"path": str(config_path), "sha256": _sha(config_path)},
                  "source_ancestor_sha256": base["source"]["sha256"],
                  "verification_backend": backend}
        build_dir = directory / "build"
        try:
            returned = builder(project_root, config_path, build_dir)
            seed, public, ledger = _inspect_case(build_dir, config, returned)
            result["financial_checks_passed"] = True
            regimes = observed_regimes(public, ledger)
            result["actual_regimes_status"] = "observed_in_financially_verified_ledger" if not injected else "observed_offline_fixture_only"
            result["actual_regimes"] = regimes
            result["untriggered_regimes"] = sorted(k for k, v in regimes.items() if not v["observed"])
            result["untriggered_required_regimes"] = [k for k in case["required_regimes"] if not regimes[k]["observed"]]
            result["audit_proofs"] = _proofs(build_dir)
            result["resolved_public_parameters"] = public["parameters"]
            if result["untriggered_required_regimes"]:
                raise ValueError("Required mechanism was not actually triggered: " + ", ".join(result["untriggered_required_regimes"]))
            result["status"] = "financially_verified_planning_seed" if not injected else "accepted_offline_test_fixture"
            digest = seed["derived_workbook_sha256"]
            entry = {"sha256": digest, "source_sha256": digest,
                     "local_path": str((build_dir / "project_model.xlsx").resolve()),
                     "source_kind": "derived_hypothetical_financial_model",
                     "source_url": base["source"]["source_url"],
                     "source_url_scope": "Ancestor public workbook attribution, not a download URL for this derived file",
                     "ancestor_download_url": base["source"].get("download_url"),
                     "source_ancestor_sha256": base["source"]["sha256"],
                     "source_lineage": public["source_lineage"], "scenario_id": config["scenario_id"],
                     "case_id": case["id"], "parameter_diff": result["parameter_diff"],
                     "sheet_count": seed["sheet_count"], "nonempty_sheet_count": seed["nonempty_sheet_count"],
                     "formula_count": seed["formula_count"], "modes": ["financial_modeling", "debugging"],
                     "finance_eligible": not injected, "financial_modeling_eligible": not injected,
                     "debugging_eligible": not injected, "scenario_required": False,
                     "qualified": False, "task_count": 0, "verification_backend": backend,
                     "finance_evidence": {"classification": "derived_multi_statement_project_financing",
                         "financial_modeling_eligible": not injected, "scenario_required": False,
                         "financial_seed_verified": not injected, "task_business_correctness_certified": False,
                         "evidence": case["mechanism"], "source_business_issues": [],
                         "safe_modules": [{"case_id": "full-debt-liquidity-family",
                             "business_goal": "Rebuild the complete 36-month debt and liquidity waterfall",
                             "candidate_regions": ["Debt!C2:AL15", "Cash Flow!C8:AL14"],
                             "required_public_rules": public["public_rules"]}],
                         "actual_regimes": regimes, "audit_proofs": result["audit_proofs"]}}
            if not injected:
                manifest["selected"].append(entry)
            else:
                # Unit-test fixtures exercise decision paths but never enter a
                # production-compatible selected list or claim real LO evidence.
                result["offline_fixture_entry"] = entry
        except Exception as exc:
            result["error"] = {"type": type(exc).__name__, "message": str(exc)[:4000]}
            result["retained_evidence"] = [str(p.resolve()) for p in sorted(build_dir.rglob("*")) if p.is_file()] if build_dir.exists() else []
        result["elapsed_seconds"] = round(time.monotonic() - case_started, 6)
        _write(directory / "case_result.json", result)
        manifest["cases"].append(result)
        manifest["selected_count"] = manifest["selected_derived_workbook_count"] = len(manifest["selected"])
        manifest["selected_ancestor_unique_count"] = len({r["source_ancestor_sha256"] for r in manifest["selected"]})
        _write(output / "manifest.json", manifest)
    manifest.update(status="completed" if not injected else "completed_offline_test_fixtures",
                    elapsed_seconds=round(time.monotonic() - started, 6),
                    attempted_scenario_count=len(cases),
                    rejected_scenario_count=sum(c["status"] == "rejected" for c in manifest["cases"]),
                    accepted_offline_fixture_count=sum(c["status"] == "accepted_offline_test_fixture" for c in manifest["cases"]),
                    api_calls=0, llm_tokens=0)
    _write(output / "manifest.json", manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config", type=Path, default=Path("config/derived_financial_scenarios.json"))
    parser.add_argument("--caseid", action="append", help="Case ID, repeatable or comma-separated; default requests all configured cases")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    identifiers = [v.strip() for group in args.caseid for v in group.split(",") if v.strip()] if args.caseid else None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or args.project_root / "outputs/research" / ("derived_scenarios_" + stamp + "-" + uuid.uuid4().hex[:6])
    result = build_scenarios(args.project_root, args.config, output, identifiers)
    print(json.dumps({"manifest": str((output / "manifest.json").resolve()),
                      **{k: result[k] for k in ("status", "ancestor_unique_count", "selected_derived_workbook_count", "attempted_scenario_count", "rejected_scenario_count", "qualified", "task_count", "api_calls", "llm_tokens")}}))
    return 0 if result["selected_derived_workbook_count"] == result["attempted_scenario_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
