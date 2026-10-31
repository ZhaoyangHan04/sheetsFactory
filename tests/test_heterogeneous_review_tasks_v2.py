"""Focused v2 text-cache correction; no native calculation or model calls."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from sheets_factory.workbook import heterogeneous_review_tasks_v2 as task


@pytest.fixture
def v():
    path=task.ROOT/"scripts/validate_heterogeneous_review_task_pair_v2.py"
    spec=importlib.util.spec_from_file_location("heterogeneous_pair_v2_test",path);v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v);return v


@pytest.fixture(scope="module")
def source():
    config=task.read(task.ROOT/"config/heterogeneous_review_tasks_v2.json")
    snapshot=task.helper().snapshot(task.checked(config["source"]))
    prior=task.read(config["prior_failure_lineage"][0]["terminal"])
    prepared=task.read(prior["preparation"])
    literals=task.read(prepared["presentation_patch_proof"])["edits"]
    return config,snapshot,literals


def test_exact_two_cache_transfers_have_direct_identity_and_approved_text(source):
    config,snapshot,literals=source;edits=task._alias_edits(config,snapshot,literals)
    assert [(e["cell"],e["source_cell"]) for e in edits]==[("H6","G10"),("K6","G12")]
    assert [e["unchanged_direct_formula"] for e in edits]==["'DCF - Stories to Numbers'!G10","'DCF - Stories to Numbers'!G12"]
    assert edits[0]["value"]=="Operating margin remains at the stated base-year level."
    assert edits[1]["value"]=="Given industry sales / capital; terminal reinvestment rate."


@pytest.mark.parametrize("mutation",["wrong_formula","nonidentity_formula","different_cache","third_alias","missing_literal"])
def test_no_other_formula_cache_or_alias_is_accepted(source,mutation):
    config,snapshot,literals=deepcopy(source)
    if mutation=="wrong_formula":snapshot["cells"]["DCF - Valuation as picture"]["H6"]["formula"]="'DCF - Stories to Numbers'!G12"
    elif mutation=="nonidentity_formula":snapshot["cells"]["DCF - Valuation as picture"]["H6"]["formula"]="IF(TRUE,'DCF - Stories to Numbers'!G10,0)"
    elif mutation=="different_cache":snapshot["cells"]["DCF - Valuation as picture"]["H6"]["primary"]={"type":"number","value":"1.00"}
    elif mutation=="third_alias":config["text_alias_cache_transfers"].append(dict(config["text_alias_cache_transfers"][0],cell="L6"))
    elif mutation=="missing_literal":literals[:]=[e for e in literals if e["cell"]!="G10"]
    with pytest.raises(ValueError):task._alias_edits(config,snapshot,literals)


def test_cache_transfer_preserves_formula_style_and_every_other_part(source,tmp_path):
    config,snapshot,literals=source;edits=literals+task._alias_edits(config,snapshot,literals)
    original=task.checked(config["source"]);output=tmp_path/"presentation_v2.xlsx"
    proof=task.surgery(original,output,edits);task.verify_surgery(original,output,edits)
    comparison=task.helper().compare_snapshots(snapshot,task.helper().snapshot(output))
    assert comparison["primary_value_mismatch_count"]==8 and comparison["formula_or_literal_identity_mismatch_count"]==0 and comparison["raw_numeric_difference_count"]==0
    assert sum(len(r["actually_changed_cells"]) for r in proof["part_cell_audits"])==8
    assert proof["all_other_parts_byte_identical"] and any(r.get("only_direct_text_caches_changed") for r in proof["part_cell_audits"])
    bad=deepcopy(edits);bad[-1]["unchanged_direct_formula"]="1+1"
    with pytest.raises(ValueError,match="formula/cache"):task.surgery(original,tmp_path/"bad.xlsx",bad)


@pytest.fixture(scope="module")
def pair(tmp_path_factory):
    output=tmp_path_factory.mktemp("v2pair")/"prepared";ref=task.prepare_pair(output);return output,ref


def test_fresh_v2_pair_has_all_evidence_and_keeps_independent766_unchanged(pair,source):
    output,pair_ref=pair;assert task.read(pair_ref)["version"]==2
    config,snapshot,literals=source
    for label in ("FM","DBG"):
        f,plan=task.validate_prepared(output/label);proof=task.read(f["text_alias_cache_proof"])
        assert f["version"]==task.read(f["material"])["version"]==proof["version"]==2
        assert proof["kind"]=="declared_two_direct_text_alias_cache_transfers" and proof["numeric_caches_changed"]==0
        assert proof["source"]==config["source"] and proof["presentation"]==f["source_presentation"]
        assert len(proof["aliases"])==2 and all(r["outside_financial_scope766"] and r["formula_preserved"] for r in proof["aliases"])
        assert len(plan["financial_scope"])==766 and f["maximum_external_LO_calls"]==7 and f["outer_retries"]==0
        assert {r["source_cell"] for r in proof["aliases"]}=={"G10","G12"}
        old=task.read(config["prior_failure_lineage"][0]["terminal"]);old_prep=task.read(old["preparation"])
        assert task.read(f["independent_scope_coverage"])["expected_typed_values"]==task.read(old_prep["independent_scope_coverage"])["expected_typed_values"]
        assert not (output/label/"execution_started.json").exists()


def test_v1_bytes_and_three_call_failure_are_retained(source):
    for path,sha in task.UPSTREAM.items():assert task.ref(task.ROOT/path)["sha256"]==sha
    config,_,_=source;old=task.read(config["prior_failure_lineage"][0]["terminal"])
    assert old["version"]==1 and old["status"]=="held" and old["LO_calls_started"]==old["LO_calls_completed"]==3
    assert old["controls"] is None and old["model_calls"]==0


def test_v2_cold_rejects_changed_alias_proof(pair,tmp_path):
    output,_=pair;f=task.read(output/"FM/preparation.json");proof=task.read(f["text_alias_cache_proof"]);proof["aliases"][0]["expected_typed_cache"]["value"]="Wrong label"
    f["text_alias_cache_proof"]=task.write(tmp_path/"wrongproof.json",proof);r=task.write(tmp_path/"changed_preparation.json",f)
    with pytest.raises(ValueError,match="alias cache proof"):task.validate_prepared(r["path"])


def test_v2_full_D_numerical_and_error_contract_matches_frozen_v1(v,tmp_path):
    path=task.ROOT/"scripts/validate_heterogeneous_review_task_pair.py";spec=importlib.util.spec_from_file_location("_v1_math_comparison",path);old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    a={"sheets":[str(i) for i in range(8)],"cells":{str(i):{"A1":{"primary":{"type":"number","value":"0.00"}}} for i in range(8)}};b=deepcopy(a)
    expected=[]
    for i in range(8):b["cells"][str(i)]["A1"]["primary"]["value"]="1.00";expected.append({"sheet":str(i),"cell":"A1","expected":{"type":"number","value":"1.00"}})
    for i in range(12):
        for snapshot in (a,b):snapshot["cells"]["7"]["F"+str(i+1)]={"primary":{"type":"error","value":"#DIV/0!"}}
    frozen={"mode":"financial_modeling","independent_scope_coverage":task.write(tmp_path/"expected.json",{"expected_typed_values":expected}),"known_protected_points":task.write(tmp_path/"protected.json",{"points":[]})};plan={"family_counts":{str(i):1 for i in range(8)},"component_namespaces":{str(i):str(i) for i in range(8)}}
    one=old.actual_D(frozen,plan,a,b);two=v.actual_D(frozen,plan,a,b)
    assert two==dict(one,version=2)


def test_v2_prior_start_blocks_every_service_without_reusing_attempt(v,pair,monkeypatch):
    output,_=pair;fm=output/"FM";task.write(fm/"execution_started.json",{"first_attempt_only":True})
    class Lease:
        def __init__(self,*a):pass
        def acquire(self):return self
        def release(self):pass
    # Patch only the isolated adapter namespace, never the frozen v1 module.
    monkeypatch.setitem(v._ns,"ProducerLease",Lease)
    monkeypatch.setitem(v._ns,"DashboardServer",lambda *a,**kw:pytest.fail("No UI for prior attempt"))
    with pytest.raises(RuntimeError,match="preserve"):v.execute_prepared(fm)
    terminal=task.read(next((fm/"private/attempts").glob("*/terminal.json")))
    assert terminal["LO_calls_started"]==0 and terminal["version"]==2 and terminal["status"]=="held"
    assert terminal["text_alias_cache_proof"]==task.read(fm/"preparation.json")["text_alias_cache_proof"]
