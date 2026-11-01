"""First-attempt pair admission and the frozen native-v6 lifecycle, service free."""
from contextlib import contextmanager
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def entry():
    loader=importlib.util.spec_from_file_location('_test_ringfenced_pair_first_v6',ROOT/'scripts/prepare_ringfenced_pair_development.py')
    module=importlib.util.module_from_spec(loader);loader.loader.exec_module(module);return module


@pytest.fixture
def material(entry,monkeypatch,tmp_path):
    e=entry;ref=e._N['ref'];writes={}
    def artifact(name,value):
        p=tmp_path/name;p.write_text(json.dumps(value));return ref(p)
    public={'kind':'synthetic_two_ringfenced_capital_mandates','version':1,'pair_id':'R2-01',
        'group_projects':720,'group_local_integer_rows':1882,'local_projects':360,'local_integer_rows':941,
        'mandates':[{'id':'M01','local_profile_id':'L360-P01'},{'id':'M02','local_profile_id':'L360-P02'}],
        'coupled_720_project_MIP_claimed':False,'TEST_ONLY':True}
    contract=artifact('public_contract.json',public)
    certificate={'kind':'cold_composed_two_ringfenced_capital_best_runner_certificate','version':1,
        'pair_id':'R2-01','contract':contract}
    cert=artifact('certificate.json',certificate)
    goal={'path':'TEST_ONLY/source3.xlsx','sha256':'a'*64,'bytes':1}
    source_ref={'path':'TEST_ONLY/source_manifest'};sf_ref={'path':'TEST_ONLY/source_preparation'};prep_ref={'path':'TEST_ONLY/task_preparation'}
    views={'path':'TEST_ONLY/complete_views_contract'};profile=ref(e.PROFILE);profile_value={'TEST_ONLY':'real profile hash is separately guarded'}
    modes={};briefs={}
    for mode in e.MODES:
        p=tmp_path/(mode+'.md');p.write_text('Public '+mode+' business request.\n');brief=ref(p);briefs[mode]=p.read_text()
        modes[mode]={'goal':goal,'instruction':brief,'complete_D_count':e.COUNTS['targets']if mode=='financial_modeling'else 180000,
            'controls':{'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}}
    actual={'kind':'complete_ringfenced_pair_task_engineering_revision2','version':1,'passed':True,
        'actual_LO_calls_started':8,'actual_LO_calls_completed':8,'source_LO_calls_reused':3,
        'qualified':False,'normal_all12_QA_passed':False,'difficulty_claimed':False,'preparation':prep_ref,
        'source_manifest':source_ref,'records':{'modes':modes}}
    frozen={'kind':'prepared_complete_ringfenced_pair_task_engineering_revision2','version':1,'pair_id':'R2-01',
        'source_manifest':source_ref,'source_preparation':sf_ref,'genuine_goal':goal,'mode_order':list(e.MODES),
        'required_actual_LO_calls':8,'financial_target_count':e.COUNTS['targets'],'source_formula_count':e.COUNTS['formulas'],
        'DBG_formula_root_count':172800,'provisional_choice_count':720,'all720choices_and_two_completion_gates_masked':True,
        'candidate_preparation':views,'whole_views_contract':views,'runtime_profile':profile,'runtime_profile_value':profile_value,
        'instruction_bytes':{mode:row['instruction']for mode,row in modes.items()}}
    source={'kind':e.SOURCE_KIND,'version':1,'passed':True,'actual_calls_started':3,'actual_calls_completed':3,'LO_calls':3,
        'preparation':sf_ref,'source':goal,'actual_calls':[{'output':goal}]}
    sf={'geometry':{k:e.COUNTS[k]for k in ('formulas','nonempty','targets')},'runtime_profile':profile,
        'runtime_profile_value':profile_value,'public_contract':contract,'certificate':cert}
    rows={prep_ref['path']:frozen,source_ref['path']:source,sf_ref['path']:sf}
    old_read=e._N['read'];calls=[]
    def read(row):return rows[row['path']]if row['path']in rows else old_read(row)
    def validate(value):calls.append(value);return actual
    driver=SimpleNamespace(validate_completed=validate,views=SimpleNamespace(FM_BRIEF=briefs['financial_modeling'],DBG_BRIEF=briefs['debugging']))
    monkeypatch.setitem(e._N,'read',read);monkeypatch.setitem(e._N,'validation_driver',lambda:driver)
    return SimpleNamespace(e=e,actual=actual,frozen=frozen,source=source,sf=sf,modes=modes,public=public,
        public_path=Path(contract['path']),certificate=certificate,certificate_path=Path(cert['path']),driver=driver,calls=calls)


def test_real_provider_pin_import_and_new_profile(entry):
    driver=entry.validation_driver()
    assert entry._N['VALIDATOR']==entry.TASK and entry._N['VALIDATOR_SHA']==entry.TASK_SHA
    assert entry._N['ref'](entry.TASK)['sha256']==entry.TASK_SHA
    assert driver.KIND=='prepared_complete_ringfenced_pair_task_engineering_revision2'
    assert driver.TERMINAL_KIND=='complete_ringfenced_pair_task_engineering_revision2'
    assert driver.SOURCE_KIND==entry.SOURCE_KIND
    assert driver.STAGES==('FM_input1','FM_input2','DBG_input1','DBG_input2','equivalent','FM_missed_root','DBG_missed_root','extra_change')
    assert entry._N['PROFILE']==entry.PROFILE
    assert entry._N['ref'](entry.PROFILE)['sha256']==entry.PROFILE_SHA


def test_genuine_hook_keeps_both_modes_without_private_answer_payload(material):
    f=material;saved=deepcopy((f.actual,f.frozen,f.source,f.sf))
    actual,candidate=f.e._checked_engineering('TEST_ONLY/actual_terminal')
    assert actual is f.actual and f.calls==['TEST_ONLY/actual_terminal']
    assert (f.actual,f.frozen,f.source,f.sf)==saved
    assert set(candidate)=={'specification','views','instructions'}
    assert candidate['specification']==f.sf['public_contract']
    assert all(candidate['views'][m]['instruction']==f.modes[m]['instruction']for m in f.e.MODES)


@pytest.mark.parametrize('problem',['old_task','partial_calls','source_reuse','one_mode','qualification','wrong_pair',
    'FM_scope','formula_count','roots','choices','completion_gates','old_source','partial_source','foreign_goal',
    'source_geometry','runtime_profile','views_lineage','FM_D','DBG_D','DBG_D_boolean','controls','brief',
    'public_kind','mandate_assignment','coupled_claim','certificate_contract'])
def test_wrong_material_provider_scope_or_control_rejected(material,problem):
    f=material
    if problem=='old_task':f.actual['kind']='complete_ringfenced_pair_task_engineering'
    elif problem=='partial_calls':f.actual['actual_LO_calls_completed']=7
    elif problem=='source_reuse':f.actual['source_LO_calls_reused']=2
    elif problem=='one_mode':f.actual['records']['modes'].pop('debugging')
    elif problem=='qualification':f.actual['normal_all12_QA_passed']=True
    elif problem=='wrong_pair':f.frozen['pair_id']='R2-02'
    elif problem=='FM_scope':f.frozen['financial_target_count']-=1
    elif problem=='formula_count':f.frozen['source_formula_count']-=1
    elif problem=='roots':f.frozen['DBG_formula_root_count']-=1
    elif problem=='choices':f.frozen['provisional_choice_count']=719
    elif problem=='completion_gates':f.frozen['all720choices_and_two_completion_gates_masked']=False
    elif problem=='old_source':f.source['kind']='completed_two_ringfenced_pair_source_same_process_session'
    elif problem=='partial_source':f.source['actual_calls_completed']=2
    elif problem=='foreign_goal':f.source['source']={'path':'foreign_goal'}
    elif problem=='source_geometry':f.sf['geometry']={**f.sf['geometry'],'nonempty':1}
    elif problem=='runtime_profile':f.frozen['runtime_profile']={'path':'old_profile'}
    elif problem=='views_lineage':f.frozen['candidate_preparation']={'path':'different_views'}
    elif problem=='FM_D':f.modes['financial_modeling']['complete_D_count']-=1
    elif problem=='DBG_D':f.modes['debugging']['complete_D_count']=0
    elif problem=='DBG_D_boolean':f.modes['debugging']['complete_D_count']=True
    elif problem=='controls':f.modes['debugging']['controls']['missed_root']=1
    elif problem=='brief':Path(f.modes['debugging']['instruction']['path']).write_text('Changed business request')
    elif problem=='public_kind':f.public['kind']='fixed_hypothetical_operating_reports_200'
    elif problem=='mandate_assignment':f.public['mandates'][1]['local_profile_id']='L360-P07'
    elif problem=='coupled_claim':f.public['coupled_720_project_MIP_claimed']=True
    else:f.certificate['contract']={'path':'different_contract'}
    if problem in ('public_kind','mandate_assignment','coupled_claim'):
        f.public_path.write_text(json.dumps(f.public))
    if problem=='certificate_contract':f.certificate_path.write_text(json.dumps(f.certificate))
    with pytest.raises((ValueError,KeyError)):f.e._checked_engineering('TEST_ONLY/actual_terminal')


def test_unchanged_v6_resource_history_reservation_and_two_process_bytecode(entry):
    loader=importlib.util.spec_from_file_location('_pair_original_v6_compare',entry.FROZEN)
    old=importlib.util.module_from_spec(loader);loader.loader.exec_module(old)
    assert entry.MODES==('financial_modeling','debugging')
    for name in ('reserve','content_identity','run_development','run_pair','effective_score'):
        assert entry._N[name].__code__.co_code==getattr(old,name).__code__.co_code
        assert entry._N[name].__globals__ is entry._N
        assert entry._N[name].__globals__ is not getattr(old,name).__globals__
    assert entry.runner.POLICY_V6==old.runner.POLICY_V6
    assert entry.BUDGET=={'version':1,'elapsed_policy':'operational_guard','elapsed_guard_seconds':14400,'tool_budget_seconds':1800}
    assert any(isinstance(value,tuple)and 'prior_model_selection_inventory'in value for value in entry.reserve.__code__.co_consts)
    assert entry._N['PROFILE']!=old.PROFILE


def test_budget_failure_zero_and_infrastructure_unknown_preserved(entry):
    known={'status':'scored','raw_verifier_reward':1,'failure_kind':'cumulative_tool_budget_exhausted','tool_time':{'passed':False}}
    resources={'passed':True,'complete':True}
    assert entry.effective_score(known,{'status':'completed'},resources)['effective_reward']==0
    unknown={**known,'failure_kind':None,'tool_time':{'passed':None}}
    assert entry.effective_score(unknown,{'status':'completed'},resources)['effective_reward']is None


def test_main_panel_precedes_cold_work(entry,monkeypatch):
    events=[]
    @contextmanager
    def monitor(phase):events.append(('panel',phase));yield;events.append(('closed',phase))
    monkeypatch.setattr(entry,'admission_monitor',monitor);monkeypatch.setattr(entry.sys,'argv',['entry','prepare'])
    monkeypatch.setitem(entry._N,'main',lambda:events.append(('cold','begin'))or 0)
    assert entry.main()==0 and events==[('panel','prepare'),('cold','begin'),('closed','prepare')]


def test_help_does_not_start_panel(entry,monkeypatch):
    monkeypatch.setattr(entry.sys,'argv',['entry','--help']);monkeypatch.setitem(entry._N,'main',lambda:7)
    monkeypatch.setattr(entry,'admission_monitor',lambda phase:pytest.fail('Help started a dashboard'))
    assert entry.main()==7
