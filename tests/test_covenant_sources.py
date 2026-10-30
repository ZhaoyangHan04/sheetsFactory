"""Offline adapter tests. Fake financial receipts never enter production selected."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

from sheets_factory.pipelines.factory import FactoryPipeline
from sheets_factory.workbook.derived_gold.spec import ANCHORS, resolve_spec
from sheets_factory.workbook.derived_gold.ledger import simulate
from sheets_factory.workbook.derived_gold.excel import emit_workbook

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("_test_covenant_sources", ROOT/"scripts/build_covenant_sources.py")
API = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(API)


@pytest.fixture
def environment(tmp_path):
    (tmp_path/"config").mkdir()
    cfg = json.loads((ROOT/"config/derived_covenant_project_v1.json").read_text())
    book = openpyxl.Workbook()
    book.remove(book.active)
    values = {"revenue":34124,"ebit":7040,"da":1527,"tax_rate":.25,"debt_rate":.0509,
              "equity_rate":.09110305231829893,"growth":.04}
    for key,(sheet,cell,_) in ANCHORS.items():
        if sheet not in book:
            book.create_sheet(sheet)
        book[sheet][cell] = values[key]
    source = tmp_path/"offline_test_anchor_fixture.xlsx"
    book.save(source)
    cfg["source"]["local_path"] = str(source)
    cfg["source"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    (tmp_path/"config/base.json").write_text(json.dumps(cfg))
    catalog = json.loads((ROOT/"config/derived_covenant_scenarios.json").read_text())
    catalog["base_config"] = "config/base.json"
    catalog["cases"] = [catalog["cases"][0]]
    path = tmp_path/"config/cases.json"
    path.write_text(json.dumps(catalog))
    return tmp_path,path,catalog,cfg


def fixture_builder(root, config_path, output):
    """Real Decimal ledger, deliberately fake LO receipts: tests ONLY."""
    cfg = json.loads(config_path.read_text())
    spec = resolve_spec(root,config_path)
    ledger = simulate(spec)
    output.mkdir(parents=True)
    (output/"private").mkdir()
    model = output/"project_model.xlsx"
    bindings = emit_workbook(spec,model)
    for name in ("model_unrecalculated.xlsx","first_recalculation.xlsx"):
        (output/"private"/name).write_bytes(model.read_bytes())
    seed = {"fixture_only":True,"scenario_id":cfg["scenario_id"],"financial_audit_passed":True,
        "source_ancestor_sha256":cfg["source"]["sha256"],"source_lineage":spec["source_lineage"],
        "derived_workbook_sha256":hashlib.sha256(model.read_bytes()).hexdigest(),
        "sheet_count":13,"nonempty_sheet_count":13,"formula_count":1,"public_contract_version":spec["public_contract_version"]}
    audit = {"fixture_only":True,"passed":True,"checked_cells":1,"formula_count":1,
        "all_formula_cells_independently_covered":True,"all_ledger_invariants_passed":True,
        "two_recalculations_typed_stable":True,"mismatches":[],"uncovered_formulas":[],"invalid_formula_values":[],
        "independent_ledger_checks":ledger["checks"],"cell_checks":[{"address":"OfflineFixture!A1","passed":True}]}
    objects = {"derived_seed_manifest.json":seed,"public_scenario.json":spec,"private/ledger.json":ledger,
        "private/bindings.json":bindings,"private/financial_audit.json":audit,
        "private/profile.json":{"fixture_only":True,"nonempty_sheet_count":13,"formula_count":1,"truncated":False,"errors":[]},
        "private/stability.json":{"fixture_only":True,"reward":1}}
    for name,obj in objects.items():
        (output/name).write_text(json.dumps(obj,default=str))
    return seed


def test_catalog_has_ten_distinct_explicit_cases_and_subset(environment):
    root,path,catalog,_ = environment
    actual,base,selected,_ = API.load_catalog(ROOT,"config/derived_covenant_scenarios.json",["C07","C01"])
    assert len(actual["cases"]) == 10
    assert [case["id"] for case in selected] == ["C01","C07"]
    assert all("hypothetical_patch" in case and "covenant_patch" in case for case in actual["cases"])
    assert base["covenant_parameters"]["covenant_enabled"] == 1


@pytest.mark.parametrize("change", ["unknown_economic","unknown_contract","duplicate_id","unsafe_id","unknown_regime"])
def test_catalog_rejects_ambiguous_or_unsafe_requests(environment,change):
    root,path,catalog,_ = environment
    c = catalog["cases"][0]
    if change=="unknown_economic":c["hypothetical_patch"]["covenant_dscr_threshold"] = 2
    if change=="unknown_contract":c["covenant_patch"]["opening_cash"] = 1
    if change=="duplicate_id":catalog["cases"].append(deepcopy(c))
    if change=="unsafe_id":c["id"] = "../bad"
    if change=="unknown_regime":c["required_regimes"].append("assumed_success")
    path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError):API.load_catalog(root,path)


def test_unknown_and_duplicate_case_subsets_rejected_before_output(environment):
    root,path,_,_ = environment
    for ids in (["C99"],["C01","C01"],[]):
        with pytest.raises(ValueError):API.build_sources(root,path,root/"no_output",ids,builder=fixture_builder)
    assert not (root/"no_output").exists()


def test_fixture_admission_cannot_populate_production_selected(environment):
    root,path,_,_ = environment
    result = API.build_sources(root,path,root/"out",builder=fixture_builder)
    assert result["selected"] == [] and result["accepted_offline_fixture_count"] == 1
    assert result["ancestor_unique_count"] == 1 and result["selected_ancestor_unique_count"] == 0
    assert result["selected_derived_workbook_count"] == 0
    assert result["unique_workbooks_inspected"] == 1
    assert result["archive_sha256"] is None and result["download_url"].startswith("derived-seed-pool:")
    assert result["api_calls"] == result["llm_tokens"] == result["task_count"] == 0
    entry = result["cases"][0]["offline_fixture_entry"]
    for key in ("finance_eligible","financial_modeling_eligible","debugging_eligible"):
        assert entry[key] is False and entry["finance_evidence"][key] is False
    for proof in result["cases"][0]["audit_proofs"].values():
        assert hashlib.sha256(Path(proof["path"]).read_bytes()).hexdigest() == proof["sha256"]


def test_incomplete_stability_proof_rejected_even_for_offline_fixture(environment):
    root,path,_,_ = environment
    def bad_builder(root,cfg,out):
        seed = fixture_builder(root,cfg,out)
        (out/"private/stability.json").write_text(json.dumps({"fixture_only":True,"reward":0}))
        return seed
    result = API.build_sources(root,path,root/"out",builder=bad_builder)
    assert result["rejected_scenario_count"] == 1 and not result["selected"]
    assert "stability" in result["cases"][0]["error"]["message"].lower()


def test_missing_source_is_a_persisted_rejection_not_a_silent_empty_run(environment):
    root,path,_,cfg = environment
    Path(cfg["source"]["local_path"]).unlink()
    result = API.build_sources(root,path,root/"out",builder=fixture_builder)
    assert result["rejected_scenario_count"] == 1 and result["verified_ancestor_unique_count"] == 0
    assert result["cases"][0]["error"]["type"] == "FileNotFoundError"
    assert (root/"out/cases/C01/requested_config.json").is_file()
    assert (root/"out/cases/C01/case_result.json").is_file()


def test_untriggered_required_mechanism_retains_financial_proof_and_rejects(environment):
    root,path,catalog,_ = environment
    catalog["cases"][0]["required_regimes"].append("loan_a_paid_off")
    path.write_text(json.dumps(catalog))
    result = API.build_sources(root,path,root/"out",builder=fixture_builder)
    case = result["cases"][0]
    assert case["financial_checks_passed"]
    assert case["untriggered_required_regimes"] == ["loan_a_paid_off"]
    assert case["status"] == "rejected" and case["audit_proofs"]
    assert result["selected"] == []


def test_requested_parameters_are_not_repaired_and_output_cannot_be_overwritten(environment):
    root,path,catalog,cfg = environment
    catalog["cases"][0]["hypothetical_patch"] = {"revolver_limit":0}
    path.write_text(json.dumps(catalog))
    result = API.build_sources(root,path,root/"out",builder=fixture_builder)
    assert result["rejected_scenario_count"] == 1
    requested = json.loads((root/"out/cases/C01/requested_config.json").read_text())
    assert requested["hypothetical_parameters"]["revolver_limit"] == 0
    assert requested["hypothetical_parameters"]["equity_paid_in"] == cfg["hypothetical_parameters"]["equity_paid_in"]
    with pytest.raises(ValueError,match="already exists"):
        API.build_sources(root,path,root/"out",builder=fixture_builder)


def test_real_factory_load_seeds_consumes_adapter_contract(environment):
    root,path,_,_ = environment
    result = API.build_sources(root,path,root/"out",builder=fixture_builder)
    # Exercise the actual loader, not a second JSON-schema imitation. The fixture
    # stays explicitly ineligible and is added only to this temporary loader test.
    result["selected"] = [result["cases"][0]["offline_fixture_entry"]]
    manifest = root/"offline_loader_fixture.json"
    manifest.write_text(json.dumps(result))
    updates = []
    pipeline = object.__new__(FactoryPipeline)
    pipeline.config = {"project_root":str(root),"run":{"seed_manifest":str(manifest),"max_sources":10}}
    pipeline.targets = {"financial_modeling":1,"debugging":1}
    pipeline.audit = SimpleNamespace(update_run=lambda **kwargs:updates.append(kwargs))
    seeds = pipeline.load_seeds()
    assert len(seeds) == 1 and seeds[0]["modes"] == ["debugging"]
    assert seeds[0]["finance_evidence"]["financial_modeling_eligible"] is False
    assert updates[-1]["discovered_sources"] == 1
    assert updates[-1]["source_archive_sha256"] is None


def test_real_production_audit_rejects_fake_lo_receipts(environment):
    root,path,_,cfg = environment
    out = root/"fixture"
    seed = fixture_builder(root,root/"config/base.json",out)
    with pytest.raises(ValueError,match="fresh financial audit"):
        API._inspect(out,cfg,seed,offline=False)


def test_fresh_audit_decimal_checks_compare_in_persisted_json_form(environment,monkeypatch):
    root,_,_,cfg = environment
    out = root/"serialization_fixture"
    seed = fixture_builder(root,root/"config/base.json",out)
    saved = json.loads((out/"private/financial_audit.json").read_text())
    public = json.loads((out/"public_scenario.json").read_text())
    fresh = deepcopy(saved)
    fresh["independent_ledger_checks"] = simulate(public)["checks"]
    assert fresh["independent_ledger_checks"] != saved["independent_ledger_checks"]
    monkeypatch.setattr(API,"audit_workbook",lambda *args:fresh)
    checked,_,_ = API._inspect(out,cfg,seed,offline=False)
    assert checked["fixture_only"]  # No selected list or production batch is created.
