"""Visibility, recipe and resource boundaries without a model or container."""
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def review():
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location("_bridge_shared_review",root/"scripts/run_associate_bridge_shared_review.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_every_check_is_assigned_once_and_shared_semantics_excludes_individual_runtime(review):
    assert set(review.PUBLIC).isdisjoint(review.PRIVATE)
    assert set(review.PUBLIC+review.PRIVATE)==set(review.ALL)
    assert "Q06" not in review.SEMANTIC and "Q11" not in review.SEMANTIC
    assert "Q08" in review.PUBLIC


@pytest.mark.parametrize("mode",["financial_modeling","debugging"])
def test_public_review_has_no_reference_or_private_construction_artifacts(review,mode):
    text=review.prompt(mode,"public")
    assert "only input.xlsx and instruction.md" in text
    assert "reference.xlsx" not in text and "oracle_A.private.json" not in text
    assert "do not inherit" in text
    assert "separate frozen difficulty confirmation is pending" in text
    private=review.prompt(mode,"reference")
    assert "reference.xlsx" in private and "NEW specification" in private
    assert "No independent public solver ran" in private


def test_previous_source_qualification_is_rejected_even_when_its_counts_match(review,tmp_path):
    old=review.write(tmp_path/"old_source.json",{"kind":"old_source_kind","passed":True,
        "actual_LO_calls_completed":3,"complete_AB_financial_fields":93510})
    batch=review.write(tmp_path/"batch.json",{"kind":"individually_engineered_business_revision_batch",
        "count":2,"actual_LO_calls_completed":5,"source":old})
    with pytest.raises(ValueError,match="previous source"):
        review.prepare(batch["path"],tmp_path/"review")
    assert not (tmp_path/"review").exists()


def test_a_changed_frozen_source_binding_is_rejected_before_model_or_workspace_creation(review,tmp_path):
    bound=review.write(tmp_path/"source.json",{"kind":"independently_verified_associate_bridge_business_source_v1"})
    batch=review.write(tmp_path/"batch.json",{"kind":"individually_engineered_business_revision_batch",
        "count":2,"actual_LO_calls_completed":5,"source":bound})
    Path(bound["path"]).write_text('{}')
    with pytest.raises(ValueError,match="binding changed"):
        review.prepare(batch["path"],tmp_path/"review")
    assert not (tmp_path/"review").exists()


@pytest.mark.parametrize("fault",["memory","cpu","image","name","pids"])
def test_actual_resource_observations_must_match_this_exact_call(review,fault):
    image="sha256:"+"b"*64;name="sf-codex-"+"a"*20
    row={"Id":"c"*64,"Name":"/"+name,"Image":image,"NanoCpus":2_000_000_000,
        "Memory":32*1024**3,"PidsLimit":256}
    assert review._valid_resource(row,name,image)
    if fault=="memory":row["Memory"]=2*1024**3
    elif fault=="cpu":row["NanoCpus"]=1_000_000_000
    elif fault=="image":row["Image"]="sha256:"+"d"*64
    elif fault=="name":row["Name"]="/sf-codex-another-call"
    else:row["PidsLimit"]=0
    assert not review._valid_resource(row,name,image)
    assert not review._valid_resource(None,name,image)


def prepared_for_workspace_test(review,folder):
    workspace=folder/"workspaces/financial_modeling/public";workspace.mkdir(parents=True)
    input_path=workspace/"input.xlsx";input_path.write_bytes(b"public workbook fixture")
    record=review.ref(input_path)
    return review.write(folder/"prepared.json",{"implementation":review.ref(review.__file__),
        "prompt":review.ref(review.PROMPT),"runtime_profile":review.ref(review.PROFILE),
        "workspace_inventory":{str(input_path.relative_to(folder)):record}})


def test_extra_private_file_in_public_workspace_stops_before_a_call(review,tmp_path):
    prepared=prepared_for_workspace_test(review,tmp_path)
    (tmp_path/"workspaces/financial_modeling/public/reference.xlsx").write_bytes(b"must never be mounted")
    with pytest.raises(ValueError,match="undeclared file"):
        review.run(prepared["path"])
    assert not (tmp_path/"dispatch.json").exists()


def test_a_reserved_review_is_never_restarted(review,tmp_path):
    prepared=prepared_for_workspace_test(review,tmp_path)
    (tmp_path/"dispatch.json").write_text(json.dumps({"reserved":True}))
    with pytest.raises(ValueError,match="never restarted"):
        review.run(prepared["path"])
