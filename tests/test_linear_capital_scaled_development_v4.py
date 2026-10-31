"""Unused-material development v4: pure policy and opaque-boundary tests."""
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace

import pytest

from sheets_factory.evaluation import linear_capital_scaled_frontier_v4 as runner
from sheets_factory.evaluation import native_transport_frontier_v4 as previous
from sheets_factory.pipelines import linear_capital_scaled_reference_review as admission

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('_N360_development_v4_test',ROOT/'scripts/prepare_linear_capital_scaled_development_v4.py')
dev=importlib.util.module_from_spec(spec);spec.loader.exec_module(dev)


@pytest.fixture(autouse=True)
def no_services(monkeypatch):
    def forbidden(*a,**k):raise AssertionError('Development tests may not launch any process or service')
    monkeypatch.setattr(subprocess,'run',forbidden);monkeypatch.setattr(subprocess,'Popen',forbidden)
    monkeypatch.setattr(socket,'create_connection',forbidden)


def test_prospective_policy_changes_without_changing_actual_version_or_global_reservation():
    assert dev.VERSION==2 and dev.KIND=='prequality_linear_capital_scaled_native_development_v4'
    source=ast.unparse(dev._v4_ast())
    assert "actual['version'] == 2" in source
    assert "'tool_time_policy_version': 4" in source
    assert "frozen['tool_time_policy_version'] == 4" in source
    assert dev._run_once.__globals__['POLICY_V4']==runner.POLICY_V4
    assert "'.scaled_development_reservations'" in ast.unparse(dev._entry_ast())
    assert dev._reserve_first_attempt.__code__.co_code==dev._old._reserve_first_attempt.__code__.co_code
    assert dev._reserve_first_attempt.__code__.co_consts==dev._old._reserve_first_attempt.__code__.co_consts
    assert 'public_only_recovery' not in dev.PENDING and 'supported_Q01_Q04_reference_review' in dev.PENDING


def test_frozen_base_admission_and_history_bytes_unchanged():
    assert dev.reference(dev._SCALED)['sha256']==dev._SHA
    assert dev.selection_history.__code__.co_code==dev._old.selection_history.__code__.co_code
    assert dev.material_identity.__code__.co_code==dev._old.material_identity.__code__.co_code
    assert not hasattr(dev,'resume_infrastructure')


def test_recipe_binds_real_opaque_admission_new_policy_and_old_immutable_entry():
    recipe=dev.recipes()
    for path in (dev._SCALED,Path(dev.__file__),Path(runner.__file__),Path(admission.__file__),Path(admission.source.__file__),admission.source.UPSTREAM):
        assert recipe[str(path.resolve())]==dev.reference(path)['sha256']
    assert len(recipe)>40


def test_forged_admission_cannot_replace_active_opaque_classes(tmp_path,monkeypatch):
    refs=[]
    for name in ('source','view','terminal'):
        path=tmp_path/(name+'.json');path.write_text('{}');refs.append(dev.reference(path))
    monkeypatch.setattr(admission,'LinearSourceAdmission',lambda *a,**k:SimpleNamespace(provider_id='scaled360'))
    monkeypatch.setattr(admission,'ReferenceViewAdmission',lambda *a,**k:SimpleNamespace())
    with pytest.raises(ValueError,match='live cold source|live opaque|Persisted JSON'):
        dev.checked_material(*refs)


@pytest.mark.parametrize('lower,upper,complete,expected',[
    (1_800_000_000_000,1_801_000_000_000,True,False),
    (1_800_000_000_001,1_801_000_000_000,True,False),
    (1_799_999_999_999,1_800_000_000_000,True,None),
    (1_800_000_000_000,1_801_000_000_000,False,None)])
def test_complete_interval_classification_declared_before_freeze(monkeypatch,lower,upper,complete,expected):
    old={'measurement_branch':'complete_proven_owned_overlap','state':'unknown','passed':None,
        'complete_owned_overlap_receipt':{'complete':complete,'cumulative_lower_bound_ns':lower,'cumulative_upper_bound_ns':upper}}
    monkeypatch.setattr(previous,'account_trial_tool_time_v4',lambda *a,**k:deepcopy(old))
    result=runner.account_trial_tool_time_v4('unused')
    assert result['passed'] is expected
    if expected is False:assert result['retained_general_v4_receipt']==old
    else:assert result==old


def test_verified_exact1826seconds_raw_one_counts_as_valid_model_zero(monkeypatch,tmp_path):
    receipt={'state':'verified','passed':False,'cumulative_tool_seconds':1826.290321299,
        'cumulative_tool_nanoseconds':1826290321299}
    monkeypatch.setitem(runner._namespace,'account_trial_tool_time_v4',lambda *a,**k:deepcopy(receipt))
    output=runner.apply_tool_time_policy({'status':'scored','reward':1,'result_file':str(tmp_path/'result.json')},
        {'tool_time_policy':runner.POLICY_V4})
    assert output['status']=='scored' and output['raw_verifier_reward']==1 and output['reward']==0
    assert output['failure_kind']=='cumulative_tool_budget_exhausted'


def test_zero_outer_retry_prospective_declaration_and_negative_state_recognition():
    tree=runner.adapted_ast();freeze=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='freeze_selection')
    assert "'max_retries': 0" in ast.unparse(freeze)
    apply=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='apply_tool_time_policy')
    assert "'verified_tool_budget_lower_bound'" in ast.unparse(apply)
    assert runner.POLICY_V4!=previous.POLICY_V4
