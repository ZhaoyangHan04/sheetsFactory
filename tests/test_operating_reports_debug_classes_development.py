"""Check single-context v6 admission without any native or model invocation."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def entry():
    loader=importlib.util.spec_from_file_location('_test_DBG_classes_first_v6',
        ROOT/'scripts/prepare_operating_reports_debug_classes_development.py')
    module=importlib.util.module_from_spec(loader);loader.loader.exec_module(module)
    return module


def material(entry,monkeypatch,variant='S800'):
    actual={'kind':'complete_operating_reports_200_debug_classes_task_engineering',
        'version':1,'passed':True,'actual_LO_calls_started':5,'actual_LO_calls_completed':5,
        'qualified':False,'normal_all12_QA_passed':False,'source_manifest':{'sha256':entry.SOURCE_SHA},
        'preparation':{'path':'TEST_ONLY/preparation'},'records':{'modes':{'debugging':{
            'goal':{'sha256':entry.GOAL_SHA},'complete_D_count':{'S800':800,'SG4000':4000}[variant],
            'controls':{'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0},
            'instruction':{'path':'TEST_ONLY/instruction'}}}}}
    frozen={'kind':'prepared_operating_reports_200_debug_classes_task_engineering','version':1,
        'variant_id':variant,'variant_envelope':{'sha256':entry.ENVELOPE_SHA},
        'source_manifest':actual['source_manifest'],'genuine_goal':actual['records']['modes']['debugging']['goal'],
        'specification':{'path':'TEST_ONLY/specification'},
        'instruction_bytes':{'debugging':actual['records']['modes']['debugging']['instruction']}}
    monkeypatch.setitem(entry._N,'validation_driver',lambda:SimpleNamespace(validate_completed=lambda _:actual))
    monkeypatch.setitem(entry._N,'read',lambda value:frozen if value==actual['preparation'] else {'TEST_ONLY':'public'})
    monkeypatch.setitem(entry._N,'canonical',lambda _:entry._N['_SPECIFICATION_SHA'])
    return actual,frozen


def test_only_one_debug_context_and_unchanged_strict_native_v6(entry):
    assert entry.MODES==('debugging',)
    assert entry._N['MODES']==('debugging',)
    assert entry.runner.POLICY_V6['budget_seconds']==1800
    assert entry.runner.POLICY_V6['strict_less_than'] is True
    assert entry.runner.POLICY_V6['parallel_executions']=='sum'
    assert entry._N['BUDGET']['elapsed_guard_seconds']==14400
    assert entry._N['BUDGET']['tool_budget_seconds']==1800


def test_real_final_task_provider_pin_and_full_recipe_import(entry):
    helper=entry._N['validation_driver']()
    assert Path(helper.__file__).resolve()==entry.TASK
    assert entry._N['ref'](entry.TASK)['sha256']==entry.TASK_SHA
    assert helper.KIND=='prepared_operating_reports_200_debug_classes_task_engineering'
    assert helper.STAGES==('DBG_input1','DBG_input2','equivalent','DBG_missed_root','extra_change')
    recipe=entry.recipes()
    assert recipe[str(entry.TASK)]['sha256']==entry.TASK_SHA
    assert recipe[str(entry.FROZEN)]['sha256']==entry.FROZEN_SHA


@pytest.mark.parametrize('variant',['S800','SG4000'])
def test_genuine_five_call_hook_keeps_original_goal_brief_and_complete_class(entry,monkeypatch,variant):
    actual,frozen=material(entry,monkeypatch,variant)
    original=deepcopy((actual,frozen))
    result,candidate=entry._checked_engineering('TEST_ONLY/terminal')
    assert result is actual and (actual,frozen)==original
    assert set(candidate['views'])=={'debugging'}
    assert candidate['views']['debugging']['instruction']==frozen['instruction_bytes']['debugging']
    assert candidate['specification']==frozen['specification']


@pytest.mark.parametrize('fault',['extra_mode','missing_call','wrong_D','wrong_goal','wrong_source','changed_envelope','changed_brief','normal_clear'])
def test_arbitrary_pass_or_partial_material_cannot_enter(entry,monkeypatch,fault):
    actual,frozen=material(entry,monkeypatch)
    mode=actual['records']['modes']['debugging']
    if fault=='extra_mode':actual['records']['modes']['financial_modeling']=deepcopy(mode)
    elif fault=='missing_call':actual['actual_LO_calls_completed']=4
    elif fault=='wrong_D':mode['complete_D_count']=799
    elif fault=='wrong_goal':mode['goal']={'sha256':'0'*64}
    elif fault=='wrong_source':frozen['source_manifest']={'sha256':'0'*64}
    elif fault=='changed_envelope':frozen['variant_envelope']['sha256']='0'*64
    elif fault=='changed_brief':mode['instruction']={'path':'TEST_ONLY/leaking_brief'}
    else:actual['normal_all12_QA_passed']=True
    with pytest.raises(ValueError):entry._checked_engineering('TEST_ONLY/terminal')
