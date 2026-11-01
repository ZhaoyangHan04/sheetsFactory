"""Single-context v6 and current raw-case admission, with no native calls."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def entry():
    loader=importlib.util.spec_from_file_location('_test_financial_cohort_first_v6',
        ROOT/'scripts/prepare_operating_reports_financial_cohort_development.py')
    value=importlib.util.module_from_spec(loader);loader.loader.exec_module(value);return value


@pytest.fixture
def material(entry,monkeypatch,tmp_path):
    e=entry;public={'kind':e.schema.KIND,'seed':202711201,'dimension_mode':'production','TEST_ONLY':True}
    public_path=tmp_path/'raw_public.json';public_path.write_text(json.dumps(public))
    copy=tmp_path/'emission_public.json';copy.write_bytes(public_path.read_bytes())
    brief=tmp_path/'brief.md';brief.write_bytes(b'B'*403);copy_brief=tmp_path/'emission_brief.md';copy_brief.write_bytes(brief.read_bytes())
    ref=e._N['ref'];spec=ref(public_path);brief_ref=ref(brief)
    inventory={'path':'TEST_ONLY/all_nine_raw_inventory','sha256':e.RAW_INVENTORY_SHA,'bytes':1}
    goal={'path':'TEST_ONLY/source3.xlsx','sha256':'a'*64,'bytes':1}
    source_ref={'path':'TEST_ONLY/source_manifest'};source_preparation={'path':'TEST_ONLY/source_preparation'}
    candidate_ref={'path':'TEST_ONLY/candidate'};task_preparation={'path':'TEST_ONLY/task_preparation'}
    mode={'goal':goal,'complete_D_count':62322,'controls':{'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0},'instruction':brief_ref}
    actual={'kind':'complete_operating_reports_financial_cohort_FM_task_engineering','version':1,'passed':True,
        'actual_LO_calls_started':5,'actual_LO_calls_completed':5,'source_LO_calls_reused':3,
        'qualified':False,'normal_all12_QA_passed':False,'difficulty_claimed':False,
        'preparation':task_preparation,'source_manifest':source_ref,'records':{'modes':{'financial_modeling':mode}}}
    frozen={'kind':'prepared_operating_reports_financial_cohort_FM_task_engineering','version':1,'case_id':'FM-C01',
        'specification':spec,'mode_order':['financial_modeling'],'independent_business_field_count':93510,'formula_count':88676,
        'financial_target_count':62322,'forecast_mask_count':62322,'report_NA_count':4834,'raw_inventory':inventory,
        'source_preparation':source_preparation,'candidate_preparation':candidate_ref,'genuine_goal':goal,
        'instruction_bytes':{'financial_modeling':brief_ref}}
    source={'kind':'independently_checked_operating_reports_financial_cohort_source_v1','version':1,'passed':True,
        'actual_LO_calls_started':3,'actual_LO_calls_completed':3,'preparation':source_preparation,'source':goal,
        'actual_calls':[{'output':goal}],'specification':spec}
    sf={'case_id':'FM-C01','specification':spec,'raw_inventory':inventory,'candidate_manifest':candidate_ref}
    candidate={'kind':'prepared_unverified_operating_reports_financial_cohort_fm_emission','version':1,'candidate_id':'FM-C01',
        'specification':ref(copy),'views':{'financial_modeling':{'instruction':ref(copy_brief)}},
        'historical_provenance':{'path':'TEST_ONLY/stale_global_code.py','sha256':'0'*64,'bytes':1}}
    rows={task_preparation['path']:frozen,source_ref['path']:source,source_preparation['path']:sf,candidate_ref['path']:candidate}
    old_read=e._N['read']
    def read(row):return rows[row['path']] if row['path'] in rows else old_read(row)
    monkeypatch.setitem(e._N,'read',read)
    monkeypatch.setitem(e._N,'validation_driver',lambda:SimpleNamespace(validate_completed=lambda value:actual))
    real_schema=e.schema
    monkeypatch.setattr(e,'schema',SimpleNamespace(candidate=real_schema.candidate,validate_spec=lambda value:value))
    publics={key:{**public,'seed':202711201+i} for i,key in enumerate(e.CASE_IDS)};publics['FM-C01']=public
    monkeypatch.setattr(e,'raw',SimpleNamespace(validate_all=lambda value:{'specifications':publics}))
    monkeypatch.setattr(e,'BRIEF_SHA',brief_ref['sha256'])
    return SimpleNamespace(e=e,actual=actual,frozen=frozen,source=source,sf=sf,candidate=candidate,public=public,
        publics=publics,mode=mode,public_path=public_path,copy_path=copy,brief=brief)


def test_single_FM_only_strict_v6_namespace_and_unchanged_resources(entry):
    e=entry
    assert e.MODES==e._N['MODES']==('financial_modeling',)
    assert 'run_pair' not in e._N and not hasattr(e,'run_pair')
    assert e.runner.POLICY_V6['budget_seconds']==1800 and e.runner.POLICY_V6['strict_less_than'] is True
    assert e.runner.POLICY_V6['exclude_model_response_time'] is True and e.runner.POLICY_V6['parallel_executions']=='sum'
    assert e.BUDGET=={'version':1,'elapsed_policy':'operational_guard','elapsed_guard_seconds':14400,'tool_budget_seconds':1800}
    assert e._N['PROFILE']==ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'
    assert e.run_development.__globals__ is e._N and e.reserve.__globals__ is e._N
    assert 'reserve' in e.run_development.__code__.co_names and 'prior_model_selections' in e.run_development.__code__.co_consts


def test_real_final_task_provider_import_has_no_actual_execution(entry):
    e=entry;driver=e.validation_driver()
    assert e._N['VALIDATOR']==e.TASK and e._N['VALIDATOR_SHA']==e.TASK_SHA
    assert e.TASK_SHA=='8188d2add6e96660f8b7401114d4d6af6bc46ffd6f01647971daa50eefd77b91'
    assert e._N['ref'](e.TASK)['sha256']==e.TASK_SHA
    assert driver.KIND=='prepared_operating_reports_financial_cohort_FM_task_engineering'
    assert driver.STAGES==('FM_input1','FM_input2','equivalent','FM_missed_root','extra_change')
    assert e.SCHEMA_SHA==e._N['ref'](e.SCHEMA)['sha256']
    assert e.BRIEF_SHA=='5d9f8922d806cb3d25ef8bca7355b5061dda372d39da8cc453168ca96894f077'


def test_genuine_hook_accepts_emission_bytecopy_and_preserves_tiny_candidate(material):
    f=material;saved=deepcopy((f.actual,f.frozen,f.source,f.sf,f.candidate))
    actual,candidate=f.e._checked_engineering('TEST_ONLY/terminal')
    assert actual is f.actual and (f.actual,f.frozen,f.source,f.sf,f.candidate)==saved
    assert set(candidate)=={'specification','views','instructions'}
    assert candidate['specification']==f.frozen['specification']
    assert candidate['views']=={'financial_modeling':{'instruction':f.mode['instruction']}}
    assert f.candidate['specification']!=f.frozen['specification']  # Real renderer uses an identical copied JSON.


@pytest.mark.parametrize('identity,seed',[(f'FM-C{i:02d}',202711200+i) for i in range(1,10)])
def test_only_all_nine_predeclared_new_identities(entry,identity,seed):
    assert entry.schema.candidate(identity)['seed']==seed
    assert entry.schema.candidate(seed)['candidate_id']==identity
    assert tuple(row['candidate_id'] for row in entry.schema.contract()['entries'][1:])==entry.CASE_IDS


@pytest.mark.parametrize('identity',['C00','FM-C00','FM-C10',202711200,202711210])
def test_existing_or_unplanned_material_identity_rejected(entry,identity):
    with pytest.raises(ValueError):entry.schema.candidate(identity)


@pytest.mark.parametrize('problem',['task_kind','source_kind','calls','source_calls','mode','scope','D','NA','normal_clear',
    'goal','source_specification','copied_spec_bytes','candidate_kind','candidate_case','raw_inventory','missing_raw_case',
    'different_raw_public','brief_bytes','brief_binding','control'])
def test_current_causal_or_material_mismatch_rejected(material,problem):
    f=material
    if problem=='task_kind':f.actual['kind']='complete_fixed_operating_reports_200_task_engineering'
    elif problem=='source_kind':f.source['kind']='old_C00_source'
    elif problem=='calls':f.actual['actual_LO_calls_completed']=4
    elif problem=='source_calls':f.source['actual_LO_calls_completed']=2
    elif problem=='mode':f.actual['records']['modes']['debugging']=deepcopy(f.mode)
    elif problem=='scope':f.frozen['forecast_mask_count']=62321
    elif problem=='D':f.mode['complete_D_count']=62321
    elif problem=='NA':f.frozen['report_NA_count']=0
    elif problem=='normal_clear':f.actual['normal_all12_QA_passed']=True
    elif problem=='goal':f.mode['goal']={'sha256':'b'*64}
    elif problem=='source_specification':f.source['specification']={'path':'other'}
    elif problem=='copied_spec_bytes':f.copy_path.write_text('{"different":"business fact"}')
    elif problem=='candidate_kind':f.candidate['kind']='prepared_unverified_fixed_operating_reports_200_pair'
    elif problem=='candidate_case':f.candidate['candidate_id']='FM-C02'
    elif problem=='raw_inventory':f.frozen['raw_inventory']={**f.frozen['raw_inventory'],'sha256':'0'*64}
    elif problem=='missing_raw_case':f.publics.pop('FM-C09')
    elif problem=='different_raw_public':f.publics['FM-C01']={**f.public,'TEST_ONLY':'changed'}
    elif problem=='brief_bytes':f.brief.write_bytes(b'X'*403)
    elif problem=='brief_binding':f.frozen['instruction_bytes']['financial_modeling']={'path':'foreign_brief'}
    else:f.mode['controls']['missed_root']=1
    with pytest.raises((ValueError,KeyError)):f.e._checked_engineering('TEST_ONLY/terminal')


def test_no_registry_or_financial_math_state_shared_with_original_entry(entry):
    loader=importlib.util.spec_from_file_location('_cohort_original_first_dev_compare',entry.FROZEN)
    old=importlib.util.module_from_spec(loader);loader.loader.exec_module(old)
    assert old.MODES==('financial_modeling','debugging') and old.VALIDATOR!=entry.VALIDATOR
    assert entry.reserve.__code__.co_code==old.reserve.__code__.co_code
    assert entry.content_identity.__code__.co_code==old.content_identity.__code__.co_code
    assert entry.run_development.__code__.co_code==old.run_development.__code__.co_code
    assert entry.reserve.__globals__ is not old.reserve.__globals__
