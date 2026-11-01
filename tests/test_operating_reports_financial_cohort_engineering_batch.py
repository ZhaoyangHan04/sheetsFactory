"""Mocked durable nine-case scheduling only; no native workers or services."""
from contextlib import contextmanager
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def m(tmp_path,monkeypatch):
    loader=importlib.util.spec_from_file_location('_test_cohort_engineering_batch',ROOT/'scripts/run_operating_reports_financial_cohort_engineering_batch.py')
    module=importlib.util.module_from_spec(loader);loader.loader.exec_module(module)
    monkeypatch.setattr(module,'RESERVATIONS',tmp_path/'TEST_ONLY_reservations')
    return module


def store(m,path,value):return m.write(path,value)


@pytest.fixture
def fixed(m,tmp_path,monkeypatch):
    calls=[];events=[];nodes=[];node_updates=[];task_updates=[];raw=store(m,tmp_path/'raw_inventory.json',{'TEST_ONLY':True})
    candidate_rows=[];publics={}
    for index,identity in enumerate(m.ORDER,1):
        public={'TEST_ONLY_case':identity};publics[identity]=public
        spec=store(m,tmp_path/(identity+'_raw.json'),public)
        candidate=store(m,tmp_path/(identity+'_candidate.json'),{'candidate_id':identity,'specification_sha256':m.schema.canonical_sha256(public)})
        comparison=store(m,tmp_path/(identity+'_comparison.json'),{'case_id':identity})
        forwards={name:store(m,tmp_path/(identity+'_'+name+'.json'),{'TEST_ONLY':name}) for name in ('A','B')}
        candidate_rows.append({'case_id':identity,'passed':True,'candidate':candidate,'specification':spec,'comparison':comparison,'forwards':forwards})
    batch=store(m,tmp_path/'reference_batch.json',{'kind':'complete_once_financial_cohort_reference_and_emission_batch','version':1,
        'raw_inventory':raw,'cases':candidate_rows,'passed':True,'passed_cases':9,'new_raw_attempts':9,
        'financial_forwards_started':18,'actual_LO_calls':0,'actual_model_calls':0,'outer_retries':0,'qualified':False})
    prep=store(m,tmp_path/'C01_source_preparation.json',{'case_id':'FM-C01','candidate_manifest':candidate_rows[0]['candidate'],'raw_inventory':raw})
    source_kind='independently_checked_operating_reports_financial_cohort_source_v1'
    reused=store(m,tmp_path/'C01_source_manifest.json',{'kind':source_kind,'passed':True,'preparation':prep,'actual_LO_calls_started':3,'actual_LO_calls_completed':3})
    def genuine_source(value):
        calls.append(('source_validate',m.read(m.read(value)['preparation'])['case_id']))
        return m.read(value)
    def source_prepare(candidate,out,**kwargs):
        calls.append(('source_prepare',kwargs['case_id']));out=Path(out)
        return store(m,out/'preparation.json',{'case_id':kwargs['case_id'],'candidate_manifest':candidate,'raw_inventory':kwargs['raw_inventory']})
    def source_execute(out):
        case=m.read(Path(out)/'preparation.json')['case_id'];calls.append(('source_execute',case))
        return store(m,Path(out)/'source_manifest.json',{'kind':source_kind,'passed':True,'preparation':m.reference(Path(out)/'preparation.json'),
            'actual_LO_calls_started':3,'actual_LO_calls_completed':3})
    def task_prepare(manifest,out):
        sf=m.read(m.read(manifest)['preparation']);calls.append(('task_prepare',sf['case_id']))
        return store(m,Path(out)/'preparation.json',{'case_id':sf['case_id'],'raw_inventory':sf['raw_inventory'],'source_manifest':manifest})
    def task_execute(out):
        tf=m.read(Path(out)/'preparation.json');calls.append(('task_execute',tf['case_id']))
        return store(m,Path(out)/'terminal.json',{'preparation':m.reference(Path(out)/'preparation.json'),'passed':True,
            'actual_LO_calls_started':5,'actual_LO_calls_completed':5})
    profile=ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'
    source=SimpleNamespace(SOURCE_KIND=source_kind,PROFILE=profile,read=m.read,
        recipes=lambda:{str(profile):m.reference(profile)},validate_source=genuine_source,prepare=source_prepare,execute_prepared=source_execute)
    task=SimpleNamespace(read=m.read,recipes=lambda:{},prepare=task_prepare,execute_prepared=task_execute,validate_completed=lambda value:m.read(value))
    monkeypatch.setattr(m,'apis',lambda:(source,task))
    monkeypatch.setattr(m.raw,'validate_all',lambda value:{'specifications':publics})
    class Audit:
        def update_run(self,**kwargs):pass
        def export(self):pass
        def record(self,table,value):nodes.append(deepcopy(value));return len(nodes)-1
        def update_record(self,table,index,value):node_updates.append((index,deepcopy(value)))
        def task(self,identity,**values):task_updates.append((identity,deepcopy(values)))
    @contextmanager
    def monitor(out,phase):
        events.append('panel:'+phase)
        yield Audit(),'http://127.0.0.1:0/'
        events.append('closed:'+phase)
    monkeypatch.setattr(m,'monitor',monitor)
    return SimpleNamespace(batch=batch,reused=reused,rows=candidate_rows,raw=raw,source=source,task=task,calls=calls,events=events,
        nodes=nodes,node_updates=node_updates,task_updates=task_updates)


def test_prepare_freezes_all_nine_then_cold_validates_original_C01_only(m,fixed,tmp_path):
    out=tmp_path/'prepared';record=m.prepare(fixed.batch,out,reuse_C01_source=fixed.reused)
    f=m.validate_prepared(out)
    assert f['case_order']==m.ORDER and len(f['cases'])==9
    assert f['max_new_actual_LO_calls']==69 and f['new_source_calls']==24 and f['task_calls']==45
    assert f['max_parallel_cases']==2 and f['reused_original_source_calls']==3
    assert fixed.calls==[('source_validate','FM-C01')]
    assert fixed.events[0]=='panel:prepare_audit'
    assert all(not Path(row['source_directory']).exists() and not Path(row['task_directory']).exists() for row in f['cases'])
    assert m.reference(record['path'])==record


@pytest.mark.parametrize('problem',['partial','duplicate','reorder','failed_case','model_spent','changed_reuse_case'])
def test_no_filtering_resample_or_cross_case_reuse(m,fixed,tmp_path,problem):
    batch=m.read(fixed.batch)
    if problem=='partial':batch['cases'].pop()
    elif problem=='duplicate':batch['cases'][1]=deepcopy(batch['cases'][0])
    elif problem=='reorder':batch['cases'].reverse()
    elif problem=='failed_case':batch['cases'][2]['passed']=False
    elif problem=='model_spent':batch['actual_model_calls']=1
    else:
        prep=m.read(m.read(fixed.reused)['preparation']);prep['case_id']='FM-C02'
        changed=store(m,tmp_path/'wrong_source_preparation.json',prep);source=m.read(fixed.reused);source['preparation']=changed
        fixed.reused=store(m,tmp_path/'wrong_source.json',source)
    changed=store(m,tmp_path/'changed_reference_batch.json',batch)
    with pytest.raises((ValueError,KeyError)):m.prepare(changed,tmp_path/'rejected',reuse_C01_source=fixed.reused)
    assert not any(name.endswith('execute') for name,_ in fixed.calls)


def test_passed_reuse_boolean_does_not_skip_genuine_replay(m,fixed,tmp_path,monkeypatch):
    monkeypatch.setattr(fixed.source,'validate_source',lambda value:(_ for _ in ()).throw(ValueError('No actual source evidence')))
    with pytest.raises(ValueError,match='No actual source'):m.prepare(fixed.batch,tmp_path/'held',reuse_C01_source=fixed.reused)
    assert (tmp_path/'held/preparation_failure.json').exists()


@pytest.mark.parametrize('identity',['FM-C01','FM-C02'])
def test_independent_worker_chain_reuses_C01_and_never_repeats_financial_forward(m,fixed,tmp_path,identity):
    out=tmp_path/'prepared';m.prepare(fixed.batch,out,reuse_C01_source=fixed.reused);store(m,out/'started.json',{'master':True})
    fixed.calls.clear();assert m.worker(out,identity)==0
    row=m.read(out/'cases'/identity/'worker_terminal.json')
    assert row['passed'] and row['actual_new_LO_calls']=={'started':5 if identity=='FM-C01' else 8,'completed':5 if identity=='FM-C01' else 8,'complete':True}
    assert ('source_prepare',identity) in fixed.calls if identity!='FM-C01' else not any(name=='source_prepare' for name,_ in fixed.calls)
    assert fixed.calls[-2:]==[('task_prepare',identity),('task_execute',identity)]
    with pytest.raises(FileExistsError):m.worker(out,identity)


def test_source_failure_stops_task_and_retains_exact_source_failure(m,fixed,tmp_path,monkeypatch):
    out=tmp_path/'prepared';m.prepare(fixed.batch,out,reuse_C01_source=fixed.reused);store(m,out/'started.json',{'master':True})
    def fail(directory):
        store(m,Path(directory)/'source_manifest.json',{'passed':False,'actual_LO_calls_started':1,'actual_LO_calls_completed':1})
        raise RuntimeError('TEST_ONLY source failed')
    monkeypatch.setattr(fixed.source,'execute_prepared',fail);fixed.calls.clear()
    assert m.worker(out,'FM-C02')==1
    terminal=m.read(out/'cases/FM-C02/worker_terminal.json')
    assert not terminal['passed'] and 'source_manifest' in terminal['records']
    assert terminal['actual_new_LO_calls']=={'started':1,'completed':1,'complete':True}
    assert not any(name=='task_execute' for name,_ in fixed.calls)


def test_master_panel_precedes_validation_and_scheduler_never_exceeds_two(m,fixed,tmp_path,monkeypatch):
    out=tmp_path/'prepared';m.prepare(fixed.batch,out,reuse_C01_source=fixed.reused);fixed.events.clear()
    launched=[];active=set();maximum=[0]
    class Process:
        def __init__(self,argv,**kwargs):
            assert fixed.events[0]=='panel:run_audit'
            self.identity=argv[-1];self.pid=100+len(launched);self.returncode=None;self.polls=0
            launched.append(self.identity);active.add(self.identity);maximum[0]=max(maximum[0],len(active))
            store(m,out/'cases'/self.identity/'worker_terminal.json',{'passed':True,
                'actual_new_LO_calls':{'started':5 if self.identity=='FM-C01' else 8,'completed':5 if self.identity=='FM-C01' else 8,'complete':True}})
        def poll(self):
            self.polls+=1
            if self.polls==1:return None
            self.returncode=0;active.discard(self.identity);return 0
        def wait(self):return 0
    monkeypatch.setattr(m.subprocess,'Popen',Process);monkeypatch.setattr(m.time,'sleep',lambda _:None)
    terminal=m.read(m.execute_prepared(out))
    assert launched==m.ORDER and maximum[0]==2 and terminal['passed']
    assert terminal['actual_new_LO_calls']=={'complete':True,'started':69,'completed':69}
    assert len(fixed.nodes)==9 and all(row['status']=='running' and row['duration_ms']==0 for row in fixed.nodes)
    completed=[row for _,row in fixed.node_updates if row['status']=='completed']
    assert len(completed)==9 and all(row['duration_ms']>=0 for row in completed)
    assert any(row['status']=='running' and row['duration_ms']>=0 for _,row in fixed.node_updates)
    assert [identity for identity,row in fixed.task_updates if row['status']=='engineering']==m.ORDER
    assert [identity for identity,row in fixed.task_updates if row['status']=='engineering_passed']==m.ORDER
    assert all(row['status']!='qualified' for _,row in fixed.task_updates)
    assert (m.RESERVATIONS/(m.schema.CONTRACT_SHA256+'.json')).exists()
    with pytest.raises(ValueError,match='first batch execution'):m.execute_prepared(out)
    assert len(launched)==9


def test_provider_pin_drift_rejects_without_editing_old_code(m,monkeypatch):
    monkeypatch.setattr(m,'SOURCE_SHA','0'*64)
    with pytest.raises(ValueError,match='providers changed'):m.apis()


def test_actual_final_source_task_pins_and_recipe_import_without_cold_calls(m):
    source,task=m.apis()
    assert source.SOURCE_KIND=='independently_checked_operating_reports_financial_cohort_source_v1'
    assert task.SOURCE_SHA==m.SOURCE_SHA and task.SOURCE_KIND==source.SOURCE_KIND
    assert task.STAGES==('FM_input1','FM_input2','equivalent','FM_missed_root','extra_change')
    recipe=m.recipes()
    assert recipe[str(m.SOURCE)]['sha256']==m.SOURCE_SHA and recipe[str(m.TASK)]['sha256']==m.TASK_SHA


def test_completed_C01_task_reuse_is_genuine_and_makes_no_new_native_calls(m,fixed,tmp_path):
    task_kind='complete_operating_reports_financial_cohort_FM_task_engineering'
    fixed.task.TERMINAL_KIND=task_kind
    tf=store(m,tmp_path/'C01_task_preparation.json',{'case_id':'FM-C01','source_manifest':fixed.reused,'raw_inventory':fixed.raw})
    terminal=store(m,tmp_path/'C01_task_terminal.json',{'kind':task_kind,'passed':True,'preparation':tf,
        'actual_LO_calls_started':5,'actual_LO_calls_completed':5})
    out=tmp_path/'prepared'
    m.prepare(fixed.batch,out,reuse_C01_source=fixed.reused,reuse_C01_task=terminal)
    f=m.validate_prepared(out)
    assert f['task_calls']==40 and f['max_new_actual_LO_calls']==64 and f['reused_original_task_calls']==5
    store(m,out/'started.json',{'master':True});fixed.calls.clear()
    assert m.worker(out,'FM-C01')==0
    row=m.read(out/'cases/FM-C01/worker_terminal.json')
    assert row['records']['task_terminal']==terminal
    assert row['actual_new_LO_calls']=={'started':0,'completed':0,'complete':True}
    assert fixed.calls==[('source_validate','FM-C01')]


def test_task_reuse_pass_flag_cannot_replace_genuine_validator(m,fixed,tmp_path,monkeypatch):
    fixed.task.TERMINAL_KIND='complete_operating_reports_financial_cohort_FM_task_engineering'
    tf=store(m,tmp_path/'task_preparation.json',{'case_id':'FM-C01','source_manifest':fixed.reused,'raw_inventory':fixed.raw})
    terminal=store(m,tmp_path/'task_terminal.json',{'kind':fixed.task.TERMINAL_KIND,'passed':True,'preparation':tf})
    monkeypatch.setattr(fixed.task,'validate_completed',lambda value:(_ for _ in ()).throw(ValueError('incomplete actual controls')))
    with pytest.raises(ValueError,match='actual controls'):
        m.prepare(fixed.batch,tmp_path/'held',reuse_C01_source=fixed.reused,reuse_C01_task=terminal)
    assert not fixed.calls or all(name=='source_validate' for name,_ in fixed.calls)


