#!/usr/bin/env python3
"""Build explicit covenant source cases with real LibreOffice, not benchmark tasks.

Only the default real builder can populate selected. Dependency injection is
strictly an offline-test path and can never create a production planning seed.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import time
import uuid

from sheets_factory.workbook.derived_gold.ledger import simulate
from sheets_factory.workbook.derived_gold.validate import audit_workbook
from sheets_factory.workbook.engine import LibreOfficeEngine


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_common = _module(Path(__file__).with_name("build_derived_scenarios.py"), "_covenant_shared_source_checks")
_sha, _json, _write = _common._sha, _common._json, _common._write
_number, _same = _common._number, _common._same_parameter
COVENANT_REGIMES = {
    "lock_enter", "one_pass_still_locked", "binding_one_pass_lock", "two_pass_cure",
    "interrupted_cure", "dsra_funding", "dsra_support", "dsra_release", "dsra_shortfall",
    "nonterminal_dividend", "payoff_followed_by_reserve_release", "zero_normal_reserve",
    "terminal_positive_reserve", "terminal_lock", "post_cure_dividend",
}
TAX_REGIMES = {
    "tax_nol_creation", "tax_nol_use", "tax_nol_expiry", "tax_interest_carry_creation",
    "tax_interest_carry_use", "tax_basis_difference", "tax_deferred_benefit",
    "tax_deferred_expense", "tax_cash_book_difference", "tax_nol_fifo_competition",
    "tax_interest_fifo_competition",
}
ADVANCED_TAX_FIELDS = {"advanced_tax_enabled", "initial_tax_rate_y1", "initial_tax_rate_y2",
    "initial_tax_rate_y3", "refresh_tax_rate_y1", "refresh_tax_rate_y2", "refresh_tax_rate_y3",
    "interest_deduction_ebitda_fraction", "nol_carryforward_years"}
TAX_CHECKS = ("tax_vintage_rollforwards_ok", "tax_interest_capacity_ok", "tax_nol_fifo_ok",
              "tax_interest_fifo_ok", "tax_bridge_ok", "tax_depreciation_basis_ok")
REGIMES = _common.REGIME_KEYS | COVENANT_REGIMES | TAX_REGIMES
EVIDENCE_FILES = (*_common.AUDIT_FILES, "private/model_unrecalculated.xlsx", "private/first_recalculation.xlsx")
RECIPE_FILES = (
    "scripts/build_covenant_sources.py", "scripts/build_derived_scenarios.py", "scripts/build_derived_gold.py",
    "src/sheets_factory/workbook/derived_gold/spec.py", "src/sheets_factory/workbook/derived_gold/excel.py",
    "src/sheets_factory/workbook/derived_gold/ledger.py", "src/sheets_factory/workbook/derived_gold/validate.py",
    "src/sheets_factory/workbook/derived_gold/presentation.py",
    "src/sheets_factory/workbook/engine.py", "src/sheets_factory/workbook/uno_recalculate.py",
    "src/sheets_factory/workbook/compare.py", "src/sheets_factory/workbook/profile.py",
    "tests/test_covenant_sources.py",
    "tests/test_advanced_tax_sources.py",
)


def _ref(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": _sha(path), "bytes": path.stat().st_size}


def load_catalog(project_root, catalog_path, case_ids=None):
    root = Path(project_root).resolve()
    path = Path(catalog_path)
    path = path if path.is_absolute() else root / path
    catalog = _json(path)
    if catalog.get("schema_version") != 1 or not isinstance(catalog.get("cases"), list) or not catalog["cases"]:
        raise ValueError("A nonempty schema-version-one covenant catalog is required")
    base_path = Path(catalog["base_config"])
    base_path = base_path if base_path.is_absolute() else root / base_path
    base = _json(base_path)
    if not isinstance(base.get("covenant_parameters"), dict) or set(base["covenant_parameters"]) != {
            "covenant_enabled", "covenant_first_test_month", "covenant_dscr_threshold",
            "dsra_normal_payment_months", "dsra_trap_payment_months"}:
        raise ValueError("Base config must expose all five covenant parameters")
    advanced = base.get("advanced_tax_parameters")
    if advanced is not None and (not isinstance(advanced, dict) or set(advanced) != ADVANCED_TAX_FIELDS):
        raise ValueError("Advanced base must expose all nine advanced tax parameters")
    seen = set()
    for case in catalog["cases"]:
        identifier = case.get("id")
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", identifier):
            raise ValueError("Unsafe covenant case ID")
        if identifier in seen:
            raise ValueError("Duplicate covenant case ID")
        seen.add(identifier)
        patch_fields = [("hypothetical_patch", "hypothetical_parameters"),
                        ("covenant_patch", "covenant_parameters")]
        if "advanced_tax_patch" in case:
            if advanced is None:
                raise ValueError("advanced_tax_patch requires an advanced-tax base config")
            patch_fields.append(("advanced_tax_patch", "advanced_tax_parameters"))
        for field, base_field in patch_fields:
            patch = case.get(field)
            if not isinstance(patch, dict) or set(patch) - set(base[base_field]):
                raise ValueError("Unknown or missing " + field + " in " + identifier)
            for key, value in patch.items():
                if key == "start_date":
                    if not isinstance(value, str):
                        raise ValueError("start_date must be explicit ISO text")
                elif isinstance(value, list):
                    for item in value:
                        _number(item)
                else:
                    _number(value)
        if not case.get("name") or not case.get("mechanism"):
            raise ValueError("Every case needs a public name and mechanism")
        required = case.get("required_regimes")
        if (not isinstance(required, list) or not required or len(required) != len(set(required))
                or any(key not in REGIMES for key in required)
                or not set(required) & COVENANT_REGIMES):
            raise ValueError("Invalid or non-covenant required regimes")
    if case_ids is not None and (not case_ids or len(case_ids) != len(set(case_ids)) or set(case_ids) - seen):
        raise ValueError("Unknown, empty or duplicate requested covenant case IDs")
    selected = [case for case in catalog["cases"] if case_ids is None or case["id"] in case_ids]
    return catalog, base, selected, base_path


def _tax_regimes(public, ledger):
    tax = public.get("advanced_tax_parameters")
    enabled = tax is not None and _number(tax["advanced_tax_enabled"]) == 1
    records = ledger.get("tax_annual", []) if enabled else []
    if enabled and ([row.get("year") for row in records] != [1, 2, 3]
                    or any(type(row.get("year")) is not int for row in records)):
        raise ValueError("Enabled advanced tax requires three ordered annual records")
    out = {}
    def record(key, years, explanation, details=None):
        out[key] = {"observed":bool(years), "periods":[year*12 for year in years],
                    "years":years, "evidence":explanation}
        if details is not None:
            out[key]["vintage_evidence"] = details
    fields = {"tax_nol_creation":"nol_new", "tax_nol_use":"nol_used", "tax_nol_expiry":"nol_expired",
              "tax_interest_carry_creation":"current_interest_carried", "tax_interest_carry_use":"interest_cf_used"}
    for key, field in fields.items():
        record(key,[r["year"] for r in records if _number(r[field])>0],"Actual positive annual posted "+field)
    for key, predicate, explanation in (
        ("tax_basis_difference",lambda r:_number(r["tax_basis_close"])!=_number(r["book_net_ppe"]),"Closing acquired-cost tax basis differs from book net PPE"),
        ("tax_deferred_benefit",lambda r:_number(r["deferred_tax_expense"])<0,"Actual negative signed deferred expense"),
        ("tax_deferred_expense",lambda r:_number(r["deferred_tax_expense"])>0,"Actual positive signed deferred expense"),
        ("tax_cash_book_difference",lambda r:_number(r["current_tax"])!=_number(r["book_tax"]),"Current cash tax differs from total book tax"),
    ):
        record(key,[r["year"] for r in records if predicate(r)],explanation)
    for prefix, regime in (("nol","tax_nol_fifo_competition"),("interest","tax_interest_fifo_competition")):
        years, details = [], []
        for row in records:
            year = row["year"]
            available = {v:_number(row[f"{prefix}_v{v}_open"]) - (_number(row[f"nol_v{v}_expired"]) if prefix=="nol" else 0)
                         for v in range(1,year)}
            if prefix=="nol":
                available = {v:amount if year-v<=int(tax["nol_carryforward_years"]) else Decimal(0)
                             for v,amount in available.items()}
            used = {v:_number(row[f"{prefix}_v{v}_used"]) for v in range(1,year)}
            total = sum(available.values(),Decimal(0))
            capacity = _number(row["nol_use_cap" if prefix=="nol" else "interest_capacity"])
            allocation = sum(used.values(),Decimal(0))
            fifo = all(not used[v] or all(available[older]-used[older]==0 for older in range(1,v)) for v in used)
            eligible = [v for v,value in available.items() if value>0]
            aggregate_use = _number(row["nol_used" if prefix=="nol" else "interest_cf_used"])
            if len(eligible)>=2 and 0<capacity<total and allocation==capacity==aggregate_use and fifo and all(0<=used[v]<=available[v] for v in used):
                years.append(year)
                details.append({"year":year,"eligible_old_vintages":eligible,
                    "available":{str(k):str(v) for k,v in available.items()},
                    "used":{str(k):str(v) for k,v in used.items()},"capacity":str(capacity)})
        record(regime,years,"At least two positive eligible OLD vintages compete for insufficient positive capacity, actually consumed FIFO",details)
    return out


def observed_regimes(public, ledger):
    out = _common.observed_regimes(public, ledger)
    rows = ledger["monthly"]
    value = lambda r, k: _number(r[k])
    periods = lambda predicate: [int(r["period"]) for r in rows if predicate(r)]

    def record(key, found, explanation):
        out[key] = {"observed": bool(found), "periods": sorted(set(found)), "evidence": explanation}

    record("lock_enter", periods(lambda r:r["lock_open"] == 0 and r["lock_close"] == 1), "Actual 0-to-1 closing distribution-lock transitions")
    record("one_pass_still_locked", periods(lambda r:r["test_due"] == 1 and r["test_passed"] == 1 and r["passes_close"] == 1 and r["lock_close"] == 1), "One successful test does not cure a lock")
    allocation_start = int(public["parameters"]["cash_allocation_start"])
    record("binding_one_pass_lock", periods(lambda r:r["period"] >= allocation_start and r["test_due"] == 1 and r["test_passed"] == 1 and r["passes_close"] == 1 and r["lock_close"] == 1 and value(r,"dsra_shortfall") == 0 and value(r,"allocation_excess") > value(r,"loan_a_extra_principal") and value(r,"dividend") == 0), "After allocation has begun and DSRA is fully funded, a one-pass lock actually withholds positive otherwise-distributable excess")
    record("two_pass_cure", periods(lambda r:r["lock_open"] == 1 and r["lock_close"] == 0 and r["passes_close"] == 2), "Actual two-consecutive-pass lock releases")
    record("interrupted_cure", periods(lambda r:r["test_due"] == 1 and r["test_passed"] == 0 and r["lock_open"] == 1 and r["passes_open"] == 1 and r["passes_close"] == 0), "A failed eligible test interrupts a one-pass cure streak")
    for key in ("dsra_funding", "dsra_support", "dsra_release", "dsra_shortfall"):
        record(key, periods(lambda r,k=key:value(r,k)>0), "Actual positive posted " + key)
    record("nonterminal_dividend", periods(lambda r:r["period"]<36 and value(r,"dividend")>0), "An actual owner distribution before terminal sale")
    payoff = [r["period"] for r in rows if value(r,"loan_a_open")>0 and value(r,"loan_a_close")==0]
    record("payoff_followed_by_reserve_release", periods(lambda r:any(t<r["period"] for t in payoff) and value(r,"dsra_release")>0 and value(r,"dsra_target")==0), "Reserve release after an actual prior-period Loan A payoff")
    zero_normal = _number(public["covenant_parameters"]["dsra_normal_payment_months"]) == 0
    first = int(public["covenant_parameters"]["covenant_first_test_month"])
    record("zero_normal_reserve", periods(lambda r:zero_normal and r["period"]>=first and r["lock_close"]==0 and value(r,"loan_a_open")>0 and value(r,"dsra_target")==0), "An unlocked active month has positive Loan A but an explicitly zero normal reserve")
    record("terminal_positive_reserve", [36] if value(rows[-1],"dsra_close")>0 else [], "Positive closing DSRA is included in share-sale value at par")
    record("terminal_lock", [36] if rows[-1]["lock_close"]==1 else [], "The final month remains distribution-locked after its actual test")
    cures = [r["period"] for r in rows if r["lock_open"]==1 and r["lock_close"]==0]
    record("post_cure_dividend", periods(lambda r:any(t<=r["period"] for t in cures) and r["period"]<36 and value(r,"dividend")>0 and r["lock_close"]==0), "An actual nonterminal dividend after a measured cure")
    out.update(_tax_regimes(public,ledger))
    if public.get("advanced_tax_parameters") is not None and _number(public["advanced_tax_parameters"]["advanced_tax_enabled"])==1:
        binding = [row["year"]*12 for row in ledger["tax_annual"] if 0<_number(row["nol_used"])==_number(row["nol_use_cap"])
                   and _number(row["nol_open"])-_number(row["nol_expired"])>_number(row["nol_used"])]
        record("nol_utilization_cap_binding",binding,"Actual advanced-tax NOL use equals the taxable-income-based cap while eligible old NOL remains")
    return out


def _inspect(directory, config, returned, *, offline):
    manifest, public, ledger = _common._inspect_case(directory, config, returned)
    if public.get("public_contract_version", 0) < 6 or manifest.get("public_contract_version") != public["public_contract_version"]:
        raise ValueError("Covenant source must use public contract version six or later")
    if _number(config["covenant_parameters"]["covenant_enabled"]) != 1:
        raise ValueError("This adapter requires explicit enabled covenants")
    if set(public.get("covenant_parameters", {})) != set(config["covenant_parameters"]) or any(
            not _same(public["covenant_parameters"][key], value) for key,value in config["covenant_parameters"].items()):
        raise ValueError("Public covenant inputs differ from requested contract")
    if ledger.get("checks", {}).get("covenant_enabled") is not True:
        raise ValueError("Independent ledger did not execute the enabled covenant")
    if [r.get("period") for r in ledger.get("monthly", [])] != list(range(1, 37)):
        raise ValueError("Complete ordered 36-month covenant ledger is required")
    requested_tax = config.get("advanced_tax_parameters")
    public_tax = public.get("advanced_tax_parameters")
    if ((requested_tax is None)!=(public_tax is None)
            or requested_tax is not None and (not isinstance(public_tax,dict) or set(public_tax)!=set(requested_tax)
                or any(not _same(public_tax[key],value) for key,value in requested_tax.items()))):
        raise ValueError("Public advanced tax inputs differ from requested contract")
    if requested_tax is not None and _number(requested_tax["advanced_tax_enabled"])==1:
        if public["public_contract_version"]<7:
            raise ValueError("Enabled advanced tax needs public contract version seven or later")
        for checks in (ledger.get("checks",{}),_json(directory/"private/financial_audit.json").get("independent_ledger_checks",{})):
            if checks.get("advanced_tax_enabled") is not True or any(checks.get(key) is not True for key in TAX_CHECKS):
                raise ValueError("Missing or failing independent advanced-tax checks")
        annual = ledger.get("tax_annual",[])
        if ([row.get("year") for row in annual] != [1,2,3] or any(type(row.get("year")) is not int for row in annual)
                or not _json(directory/"private/bindings.json").get("tax_annual")):
            raise ValueError("Complete advanced tax annual ledger and formula bindings are required")
    if config.get("public_presentation")=="business_brief" and public.get("presentation_style")!="business_brief":
        raise ValueError("Public presentation differs from requested business brief")
    for name in EVIDENCE_FILES:
        if not (directory / name).is_file():
            raise ValueError("Missing covenant proof: " + name)
    if not offline:
        # Reproduce the independent ledger and cached-cell checks from the public
        # spec. Persisted receipts alone cannot certify a modified workbook.
        replay = simulate(public)
        if json.loads(json.dumps(replay, default=str)) != ledger:
            raise ValueError("Persisted ledger differs from independent public-spec replay")
        audit = audit_workbook(directory / "project_model.xlsx", public, replay, _json(directory / "private/bindings.json"))
        saved = _json(directory / "private/financial_audit.json")
        normalized = json.loads(json.dumps(audit, default=str))
        if not audit["passed"] or any(saved.get(key) != value for key,value in normalized.items()):
            raise ValueError("Cached workbook differs from independent fresh financial audit")
    return manifest, public, ledger


def _entry(case, config, base, directory, seed, public, regimes, proofs, *, production):
    digest = seed["derived_workbook_sha256"]
    evidence = {"classification":"derived_covenant_project_financing", "financial_modeling_eligible":production,
                "debugging_eligible":production, "finance_eligible":production, "scenario_required":False,
                "financial_seed_verified":production, "task_business_correctness_certified":False,
                "public_contract_version":public["public_contract_version"], "evidence":case["mechanism"],
                "source_business_issues":[], "actual_regimes":regimes, "audit_proofs":proofs,
                "safe_modules":[{"case_id":"covenant-and-liquidity-state", "business_goal":"Build or repair the covenant state, DSRA and integrated cash waterfall",
                    "candidate_regions":["Covenants!C2:AL21","Debt!C2:AL15","Cash Flow!C8:AL18","Balance Sheet!C9:AL20"],
                    "required_public_rules":public["public_rules"]}]}
    advanced = public.get("advanced_tax_parameters") is not None and _number(public["advanced_tax_parameters"]["advanced_tax_enabled"])==1
    if advanced:
        evidence["classification"] = "derived_advanced_tax_covenant_financing"
        evidence["advanced_tax_enabled"] = True
        evidence["presentation_style"] = public.get("presentation_style","full")
        evidence["safe_modules"].append({"case_id":"annual-tax-vintage-integration", "business_goal":"Build or repair vintage tax, deferred tax and their cash/financing integration",
            "candidate_regions":["Tax Vintages!C3:E54","Tax!C2:AL12","Operations!C13:AL14","Cash Flow!C19:AL19","Balance Sheet!C21:AL22"],
            "required_public_rules":public["public_rules"]})
    return {"sha256":digest,"source_sha256":digest,"local_path":str((directory/"project_model.xlsx").resolve()),
            "source_kind":"derived_hypothetical_advanced_tax_model" if advanced else "derived_hypothetical_covenant_model","source_url":base["source"]["source_url"],
            "source_url_scope":"Ancestor attribution; this derived file is not downloaded from that URL",
            "ancestor_download_url":base["source"].get("download_url"),"source_ancestor_sha256":base["source"]["sha256"],
            "source_lineage":public["source_lineage"],"scenario_id":config["scenario_id"],"case_id":case["id"],
            "sheet_count":seed["sheet_count"],"nonempty_sheet_count":seed["nonempty_sheet_count"],"formula_count":seed["formula_count"],
            "public_contract_version":public["public_contract_version"],"modes":["financial_modeling","debugging"],
            "finance_eligible":production,"financial_modeling_eligible":production,"debugging_eligible":production,
            "scenario_required":False,"qualified":False,"task_count":0,"finance_evidence":evidence,
            "verification_backend":"independent_Decimal_and_real_LibreOffice" if production else "offline_test_fixture_not_real_LO"}


def build_sources(project_root, catalog_path, output, case_ids=None, *, builder=None):
    root, output = Path(project_root).resolve(), Path(output).resolve()
    catalog_path = Path(catalog_path)
    catalog_path = catalog_path if catalog_path.is_absolute() else root / catalog_path
    catalog, base, cases, base_path = load_catalog(root, catalog_path, case_ids)
    advanced_base = base.get("advanced_tax_parameters") is not None and _number(base["advanced_tax_parameters"]["advanced_tax_enabled"])==1
    if output.exists():
        raise ValueError("Output already exists; choose a new immutable source batch")
    offline = builder is not None
    recipe_paths = {name:root/name for name in RECIPE_FILES}
    recipe_paths.update({"catalog":catalog_path,"base_config":base_path})
    recipe = {name:_ref(path) for name,path in recipe_paths.items() if path.is_file()}
    if not offline and len(recipe) != len(recipe_paths):
        raise ValueError("Production source adapter recipe is incomplete")
    output.mkdir(parents=True)
    backend = "offline_test_fixture_not_real_LO" if offline else "independent_Decimal_and_real_LibreOffice"
    manifest = {"schema_version":1,"dataset":"derived_advanced_tax_planning_seeds" if advanced_base else "derived_covenant_planning_seeds","status":"building",
        "created_at":datetime.now(timezone.utc).isoformat(),"qualified":False,"task_count":0,
        "selected":[],"unique_workbooks_inspected":0,"download_url":"derived-seed-pool:advanced-tax-explicit-hypothetical-cases" if advanced_base else "derived-seed-pool:covenant-explicit-hypothetical-cases",
        "archive_sha256":None,"verification_backend":backend,"recipe":recipe,"catalog":_ref(catalog_path),
        "base_config":_ref(base_path),"source_ancestor":base["source"],"source_ancestor_sha256":base["source"]["sha256"],
        "ancestor_unique_count":1,"verified_ancestor_unique_count":0,"selected_ancestor_unique_count":0,
        "selected_derived_workbook_count":0,"requested_case_ids":[case["id"] for case in cases],"cases":[],
        "api_calls":0,"llm_tokens":0,"requirements_before_task_admission":"Every Q gate, public recovery, actual Harbor oracle/nop and specified strongest-agent difficulty gates remain required."}
    _write(output/"manifest.json", manifest)
    builder = builder or _common._load_builder(root)
    started = time.monotonic()
    runtime = None
    for case in cases:
        start = time.monotonic()
        directory = output/"cases"/case["id"]
        directory.mkdir(parents=True)
        config = deepcopy(base)
        config["scenario_id"] = base["scenario_id"] + "-" + case["id"].lower()
        for field, key in (("hypothetical_patch","hypothetical_parameters"),("covenant_patch","covenant_parameters")):
            config[key].update(deepcopy(case[field]))
        if "advanced_tax_patch" in case:
            config["advanced_tax_parameters"].update(deepcopy(case["advanced_tax_patch"]))
        config["case_description"] = {key:case[key] for key in ("id","name","mechanism")}
        requested = directory/"requested_config.json"
        _write(requested, config)
        result = {"id":case["id"],"name":case["name"],"mechanism":case["mechanism"],"status":"rejected",
            "qualified":False,"task_count":0,"required_regimes":case["required_regimes"],"financial_checks_passed":False,
            "requested_config":_ref(requested),"hypothetical_patch":case["hypothetical_patch"],"covenant_patch":case["covenant_patch"],
            "verification_backend":backend,"recipe":recipe}
        if "advanced_tax_patch" in case:
            result["advanced_tax_patch"] = case["advanced_tax_patch"]
        build_dir = directory/"build"
        try:
            source = Path(config["source"]["local_path"])
            source = source if source.is_absolute() else root/source
            if _sha(source) != config["source"]["sha256"]:
                raise ValueError("Original ancestor SHA256 mismatch")
            manifest["verified_ancestor_unique_count"] = 1
            if any(_sha(Path(proof["path"])) != proof["sha256"] for proof in recipe.values()):
                raise ValueError("Source recipe changed after batch started")
            if not offline and runtime is None:
                runtime = LibreOfficeEngine(root).metadata()
                manifest["runtime"] = runtime
            returned = builder(root, requested, build_dir)
            if not offline and LibreOfficeEngine(root).ensure_image() != runtime["image_id"]:
                raise ValueError("LibreOffice image changed during source construction")
            seed, public, ledger = _inspect(build_dir, config, returned, offline=offline)
            result["financial_checks_passed"] = True
            regimes = observed_regimes(public, ledger)
            result["actual_regimes"] = regimes
            result["untriggered_required_regimes"] = [key for key in case["required_regimes"] if not regimes[key]["observed"]]
            result["audit_proofs"] = {name:_ref(build_dir/name) for name in EVIDENCE_FILES}
            if result["untriggered_required_regimes"]:
                raise ValueError("Required mechanisms did not occur: " + ", ".join(result["untriggered_required_regimes"]))
            if any(_sha(Path(proof["path"])) != proof["sha256"] for proof in recipe.values()):
                raise ValueError("Source recipe changed during case build")
            entry = _entry(case, config, base, build_dir, seed, public, regimes, result["audit_proofs"], production=not offline)
            entry["finance_evidence"].update(recipe_proofs=recipe, requested_config=_ref(requested), runtime=runtime)
            if offline:
                result["status"] = "accepted_offline_test_fixture"
                result["offline_fixture_entry"] = entry
            else:
                result["status"] = "financially_verified_planning_seed"
                manifest["selected"].append(entry)
        except Exception as exc:
            result["error"] = {"type":type(exc).__name__,"message":str(exc)[:4000]}
        result["retained_evidence"] = {str(path.relative_to(directory)):_ref(path) for path in sorted(directory.rglob("*")) if path.is_file()}
        result["elapsed_seconds"] = round(time.monotonic()-start, 6)
        _write(directory/"case_result.json", result)
        manifest["cases"].append({**result,"case_result":_ref(directory/"case_result.json")})
        manifest["unique_workbooks_inspected"] += int((build_dir/"project_model.xlsx").is_file())
        manifest["selected_count"] = manifest["selected_derived_workbook_count"] = len(manifest["selected"])
        manifest["selected_ancestor_unique_count"] = len({row["source_ancestor_sha256"] for row in manifest["selected"]})
        _write(output/"manifest.json",manifest)
    manifest.update(status="completed_offline_test_fixtures" if offline else "completed",
        elapsed_seconds=round(time.monotonic()-started,6),attempted_scenario_count=len(cases),
        rejected_scenario_count=sum(row["status"]=="rejected" for row in manifest["cases"]),
        accepted_offline_fixture_count=sum(row["status"]=="accepted_offline_test_fixture" for row in manifest["cases"]))
    _write(output/"manifest.json",manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root",type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config",type=Path,default=Path("config/derived_covenant_scenarios.json"))
    parser.add_argument("--caseid",action="append",help="Repeatable or comma-separated case IDs; default all explicit cases")
    parser.add_argument("--output",type=Path)
    args = parser.parse_args(argv)
    ids = [item.strip() for group in args.caseid for item in group.split(",") if item.strip()] if args.caseid else None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or args.project_root/"outputs/research"/("covenant_sources_"+stamp+"-"+uuid.uuid4().hex[:6])
    result = build_sources(args.project_root,args.config,output,ids)
    print(json.dumps({"manifest":str((output/"manifest.json").resolve()),**{key:result[key] for key in (
        "status","attempted_scenario_count","rejected_scenario_count","ancestor_unique_count",
        "selected_derived_workbook_count","qualified","task_count","api_calls","llm_tokens")}}))
    return 0 if result["selected_derived_workbook_count"]==result["attempted_scenario_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
