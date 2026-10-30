"""Adapter tax-policy observations and admission guards; no real LO or model calls."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path

import openpyxl
import pytest

from sheets_factory.workbook.derived_gold.spec import ANCHORS, resolve_spec
from sheets_factory.workbook.derived_gold.presentation import apply_public_presentation
from sheets_factory.workbook.derived_gold.ledger import simulate

ROOT = Path(__file__).resolve().parents[1]


def module(name,path):
    spec = importlib.util.spec_from_file_location(name,path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


API = module("_advanced_source_adapter",ROOT/"scripts/build_covenant_sources.py")
OLD = module("_advanced_source_fixture_helpers",ROOT/"tests/test_covenant_sources.py")


@pytest.fixture
def environment(tmp_path):
    (tmp_path/"config").mkdir()
    base = json.loads((ROOT/"config/derived_advanced_tax_brief_v1.json").read_text())
    book = openpyxl.Workbook()
    book.remove(book.active)
    values = {"revenue":34124,"ebit":7040,"da":1527,"tax_rate":.25,"debt_rate":.0509,
              "equity_rate":.09110305231829893,"growth":.04}
    for key,(sheet,cell,_) in ANCHORS.items():
        if sheet not in book:
            book.create_sheet(sheet)
        book[sheet][cell] = values[key]
    source = tmp_path/"explicit_offline_tax_anchor_fixture.xlsx"
    book.save(source)
    base["source"]["local_path"] = str(source)
    base["source"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    (tmp_path/"config/base.json").write_text(json.dumps(base))
    catalog = json.loads((ROOT/"config/derived_advanced_tax_scenarios_v1.json").read_text())
    catalog["base_config"] = "config/base.json"
    catalog["cases"] = [catalog["cases"][0]]
    path = tmp_path/"config/cases.json"
    path.write_text(json.dumps(catalog))
    return tmp_path,path,catalog,base


def fixture_builder(root,path,out):
    """Fake LO receipts are explicitly inherited from the offline-only fixture."""
    seed = OLD.fixture_builder(root,path,out)
    public_path = out/"public_scenario.json"
    public = json.loads(public_path.read_text())
    public_path.write_text(json.dumps(apply_public_presentation(public,"business_brief")))
    return seed


def test_old_catalog_stays_valid_without_new_patch_fields():
    _,base,cases,_ = API.load_catalog(ROOT,"config/derived_covenant_scenarios_v2.json")
    assert len(cases)==10 and "advanced_tax_parameters" not in base
    assert all("advanced_tax_patch" not in case for case in cases)


@pytest.mark.parametrize("kind",["unknown_key","no_advanced_base","boolean_value","infinite_value"])
def test_advanced_patch_requires_a_known_finite_opt_in_base(environment,kind):
    root,path,catalog,base = environment
    patch = catalog["cases"][0]["advanced_tax_patch"]
    if kind=="unknown_key":patch["hidden_loss_injection"]=1
    if kind=="no_advanced_base":
        base.pop("advanced_tax_parameters")
        (root/"config/base.json").write_text(json.dumps(base))
    if kind=="boolean_value":patch["advanced_tax_enabled"]=True
    if kind=="infinite_value":patch["interest_deduction_ebitda_fraction"]="Infinity"
    path.write_text(json.dumps(catalog))
    with pytest.raises(ValueError):API.load_catalog(root,path)


def test_omitted_advanced_patch_preserves_all_base_parameters(environment):
    root,path,catalog,base = environment
    catalog["cases"][0].pop("advanced_tax_patch")
    path.write_text(json.dumps(catalog))
    seen = []
    def builder(root,cfg,out):
        seen.append(json.loads(cfg.read_text()))
        return fixture_builder(root,cfg,out)
    result = API.build_sources(root,path,root/"out",builder=builder)
    assert seen[0]["advanced_tax_parameters"]==base["advanced_tax_parameters"]
    assert result["selected"]==[] and result["accepted_offline_fixture_count"]==1


def test_advanced_patch_is_explicit_and_fixture_cannot_be_selected(environment):
    root,path,catalog,_ = environment
    case = catalog["cases"][0]
    case["advanced_tax_patch"]={"nol_carryforward_years":2}
    case["required_regimes"]=["lock_enter","tax_nol_fifo_competition"]
    path.write_text(json.dumps(catalog))
    result = API.build_sources(root,path,root/"out",builder=fixture_builder)
    assert result["selected"]==[] and result["accepted_offline_fixture_count"]==1
    entry = result["cases"][0]["offline_fixture_entry"]
    assert entry["source_kind"]=="derived_hypothetical_advanced_tax_model"
    assert entry["finance_evidence"]["presentation_style"]=="business_brief"
    assert entry["finance_evidence"]["advanced_tax_enabled"] is True
    assert entry["finance_eligible"] is entry["finance_evidence"]["finance_eligible"] is False
    assert entry["finance_evidence"]["actual_regimes"]["tax_nol_fifo_competition"]["periods"]==[36]
    requested = json.loads((root/"out/cases/T01/requested_config.json").read_text())
    assert requested["advanced_tax_parameters"]["nol_carryforward_years"]==2


@pytest.mark.parametrize("tamper",["public_param","missing_ledger_flag","missing_audit_flag","missing_fifo_check","missing_records","missing_bindings","wrong_brief"])
def test_enabled_tax_requires_actual_public_params_checks_bindings_and_presenter(environment,tamper):
    root,_,_,base = environment
    out = root/"fixture"
    seed = fixture_builder(root,root/"config/base.json",out)
    relative = {"public_param":"public_scenario.json","missing_ledger_flag":"private/ledger.json",
        "missing_audit_flag":"private/financial_audit.json","missing_fifo_check":"private/ledger.json",
        "missing_records":"private/ledger.json","missing_bindings":"private/bindings.json","wrong_brief":"public_scenario.json"}[tamper]
    path = out/relative
    data = json.loads(path.read_text())
    if tamper=="public_param":data["advanced_tax_parameters"]["nol_carryforward_years"]=2
    if tamper=="missing_ledger_flag":data["checks"].pop("advanced_tax_enabled")
    if tamper=="missing_audit_flag":data["independent_ledger_checks"].pop("advanced_tax_enabled")
    if tamper=="missing_fifo_check":data["checks"].pop("tax_interest_fifo_ok")
    if tamper=="missing_records":data["tax_annual"].pop()
    if tamper=="missing_bindings":data.pop("tax_annual")
    if tamper=="wrong_brief":data.pop("presentation_style")
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):API._inspect(out,base,seed,offline=True)


def tax_record_fixture():
    public={"advanced_tax_parameters":{"advanced_tax_enabled":1,"nol_carryforward_years":2}}
    fields=("nol_new","nol_used","nol_expired","current_interest_carried","interest_cf_used",
            "tax_basis_close","book_net_ppe","deferred_tax_expense","current_tax","book_tax",
            "nol_use_cap","interest_capacity")
    rows=[]
    for year in [1,2,3]:
        row={key:"0" for key in fields};row["year"]=year
        for v in [1,2,3]:
            for key in (f"nol_v{v}_open",f"nol_v{v}_expired",f"nol_v{v}_used",f"interest_v{v}_open",f"interest_v{v}_used"):
                row[key]="0"
        rows.append(row)
    return public,{"tax_annual":rows}


def test_zero_filled_and_current_year_attributes_are_not_fifo_competition():
    public,ledger=tax_record_fixture()
    assert not any(item["observed"] for item in API._tax_regimes(public,ledger).values())
    row=ledger["tax_annual"][-1]
    row.update(nol_v3_open="100",interest_v3_open="100",nol_use_cap="10",interest_capacity="10",
               nol_used="10",interest_cf_used="10",nol_v3_used="10",interest_v3_used="10")
    report=API._tax_regimes(public,ledger)
    assert not report["tax_nol_fifo_competition"]["observed"]
    assert not report["tax_interest_fifo_competition"]["observed"]


@pytest.mark.parametrize("prefix",["nol","interest"])
@pytest.mark.parametrize("variant",["valid","single_old_bucket","unlimited_capacity","no_actual_use","reversed_fifo","aggregate_disagrees"])
def test_fifo_competition_requires_two_old_buckets_and_actual_partial_fifo_allocation(prefix,variant):
    public,ledger=tax_record_fixture();r=ledger["tax_annual"][-1]
    r.update({f"{prefix}_v1_open":"10",f"{prefix}_v2_open":"20",
              f"{prefix}_v1_used":"10",f"{prefix}_v2_used":"5"})
    cap="nol_use_cap" if prefix=="nol" else "interest_capacity"
    total="nol_used" if prefix=="nol" else "interest_cf_used"
    r[cap]=r[total]="15"
    if variant=="single_old_bucket":r.update({f"{prefix}_v1_open":"0",f"{prefix}_v1_used":"0",f"{prefix}_v2_used":"15"})
    if variant=="unlimited_capacity":r[cap]=r[total]="30";r[f"{prefix}_v2_used"]="20"
    if variant=="no_actual_use":r[total]="0";r[f"{prefix}_v1_used"]=r[f"{prefix}_v2_used"]="0"
    if variant=="reversed_fifo":r[f"{prefix}_v1_used"]="5";r[f"{prefix}_v2_used"]="10"
    if variant=="aggregate_disagrees":r[total]="14.99"
    result=API._tax_regimes(public,ledger)[f"tax_{prefix}_fifo_competition"]
    assert result["observed"] is (variant=="valid")
    if variant=="valid":assert result["vintage_evidence"][0]["eligible_old_vintages"]==[1,2]


def test_expired_nol_is_not_an_eligible_competing_old_bucket():
    public,ledger=tax_record_fixture();public["advanced_tax_parameters"]["nol_carryforward_years"]=1
    r=ledger["tax_annual"][-1]
    r.update(nol_v1_open="10",nol_v1_expired="10",nol_v2_open="20",nol_v2_used="15",nol_used="15",nol_use_cap="15")
    assert not API._tax_regimes(public,ledger)["tax_nol_fifo_competition"]["observed"]


def test_advanced_nol_cap_observation_uses_taxable_income_not_book_ebt(environment):
    root,_,_,_ = environment
    public=resolve_spec(root,root/"config/base.json")
    public["advanced_tax_parameters"]["nol_carryforward_years"]=2
    ledger=simulate(public)
    report=API.observed_regimes(public,ledger)
    third=ledger["tax_annual"][-1]
    assert third["nol_used"]==third["nol_use_cap"]>0
    assert third["nol_used"]!=(max(third["book_ebt"],0)*Decimal('.8')).quantize(Decimal('.01'))
    assert report["nol_utilization_cap_binding"]["periods"]==[36]


def test_all_ten_catalog_mechanisms_are_attainable_in_the_explicit_fixture_ledger(environment):
    root,_,_,base = environment
    catalog,_,cases,_ = API.load_catalog(ROOT,"config/derived_advanced_tax_scenarios_v1.json")
    assert len(cases)==10 and catalog["base_config"]=="config/derived_advanced_tax_brief_v1.json"
    for case in cases:
        cfg=deepcopy(base)
        for patch,target in (("hypothetical_patch","hypothetical_parameters"),("covenant_patch","covenant_parameters"),("advanced_tax_patch","advanced_tax_parameters")):
            cfg[target].update(case.get(patch,{}))
        path=root/"config"/(case["id"]+".json");path.write_text(json.dumps(cfg))
        public=resolve_spec(root,path);ledger=simulate(public);observed=API.observed_regimes(public,ledger)
        assert all(observed[key]["observed"] for key in case["required_regimes"]),case["id"]
