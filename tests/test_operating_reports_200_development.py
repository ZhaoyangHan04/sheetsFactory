"""Service-free fixed200 snapshots, durable attempts and v6 protocol boundaries."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import fcntl
import importlib.util
import json
from pathlib import Path
from types import FunctionType, SimpleNamespace
from zipfile import ZipFile, ZIP_STORED

import openpyxl
import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def factory(tmp_path,monkeypatch):
    path=ROOT/'scripts/prepare_operating_reports_200_development.py'
    spec=importlib.util.spec_from_file_location('_test_fixed200_development',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    genuine=m.validation_driver();old=m.history_helper();namespace=dict(vars(old));roots=(tmp_path/'history/difficulty',tmp_path/'history/research')
    for root in roots:root.mkdir(parents=True)
    namespace['HISTORY_ROOTS']=roots
    for name,value in list(namespace.items()):
        if isinstance(value,FunctionType) and value.__globals__ is vars(old):
            fn=FunctionType(value.__code__,namespace,name,value.__defaults__,value.__closure__)
            fn.__kwdefaults__=deepcopy(value.__kwdefaults__);namespace[name]=fn
    history=SimpleNamespace(**namespace);cold=[]
    def completed(value):
        cold.append(value);actual=m.read(value)
        if actual.get('TEST_ONLY_reject'):raise ValueError('Genuine cold engineering rejection')
        return actual
    monkeypatch.setattr(m,'history_helper',lambda:history)
    monkeypatch.setattr(m,'validation_driver',lambda:SimpleNamespace(validate_completed=completed,recipes=genuine.recipes))
    monkeypatch.setattr(m.runner,'run_evaluation',lambda *a,**k:pytest.fail('No model calls in pure preparation'))
    monkeypatch.setattr(m,'verify_local_base_image',lambda *a,**k:pytest.fail('No Docker calls in pure preparation'))
    def book(path,value,repacked):
        path.parent.mkdir(parents=True,exist_ok=True);w=openpyxl.Workbook();s=w.active;s.title='Quarterly reports'
        s['A1']='Original Read Me policies apply';s['B1']=value;w.save(path);w.close()
        if repacked:
            with ZipFile(path) as z:members=[(item.filename,z.read(item.filename)) for item in z.infolist()]
            with ZipFile(path,'w',ZIP_STORED) as z:
                z.comment=b'No logical workbook change'
                for name,data in members:z.writestr(name,data)
        return m.ref(path)
    def make(name='first',*,repacked=False,actual_changes=None,prepared_changes=None,candidate_changes=None):
        folder=tmp_path/name;folder.mkdir();goal=book(folder/'goal.xlsx',100,repacked);views={};modes={}
        for mode in m.MODES:
            instruction=folder/(mode+'.md');instruction.write_bytes(b'Complete all forecast reports using the public Read Me conventions.\n')
            views[mode]={'instruction':m.ref(instruction)}
            modes[mode]={'input':book(folder/(mode+'.xlsx'),None if mode=='financial_modeling' else 99,repacked),
                'goal':goal,'instruction':m.ref(instruction),'complete_D_count':62322 if mode=='financial_modeling' else 4500,
                'controls':{'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}}
        public={'TEST_ONLY':'public fixed production facts'};monkeypatch.setattr(m,'_SPECIFICATION_SHA',m.canonical(public))
        raw=m.write(folder/'specification.json',public)
        candidate=m.write(folder/'candidate.json',{'kind':'prepared_unverified_fixed_operating_reports_200_pair','version':1,
            'qualified':False,'specification':raw,'views':views,**(candidate_changes or {})})
        source=m.write(folder/'source.json',{'kind':'TEST_ONLY_source3_boundary'})
        prepared=m.write(folder/'task_preparation.json',{'kind':'prepared_fixed_operating_reports_200_task_engineering','version':1,
            'source_manifest':source,'financial_target_count':62322,'independent_business_field_count':93510,
            'DBG_formula_root_count':200,'specification':raw,'candidate_preparation':candidate,'genuine_goal':goal,
            **(prepared_changes or {})})
        actual=m.write(folder/'task_terminal.json',{'kind':'complete_fixed_operating_reports_200_task_engineering','version':1,
            'passed':True,'actual_LO_calls_started':8,'actual_LO_calls_completed':8,'qualified':False,'normal_all12_QA_passed':False,
            'source_manifest':source,'preparation':prepared,'records':{'modes':modes},**(actual_changes or {})})
        return SimpleNamespace(m=m,root=folder,output=folder/'snapshot',actual=actual,candidate=candidate,modes=modes,cold=cold,history=history)
    return make


def test_shared_two_mode_v6_real17_export_has_original_bytes_and_private_goal(factory):
    c=factory();m=c.m;f=m.read(m.prepare(c.actual,c.output))
    assert len(c.cold)==1 and f['both_materials_frozen_before_any_model'] is True
    assert f['mode_order']==list(m.MODES) and f['model']=='gpt-6.1-sol' and f['reasoning_effort']=='xhigh'
    assert f['execution_budget']=={'version':1,'elapsed_policy':'operational_guard','elapsed_guard_seconds':14400,'tool_budget_seconds':1800}
    assert f['effective_outer_retries']==0 and not f['qualified'] and not f['normal_all12_QA_passed'] and not f['difficulty_claimed']
    for mode,row in f['modes'].items():
        export=Path(row['export_directory']);source=m.read(row['source_view'])
        assert len([p for p in export.rglob('*') if p.is_file()])==17
        assert (export/'environment/input.xlsx').read_bytes()==m.checked(c.modes[mode]['input']).read_bytes()
        assert (export/'tests/reference.xlsx').read_bytes()==m.checked(c.modes[mode]['goal']).read_bytes()
        original=m.checked(row['original_instruction']).read_bytes()
        assert (export/'instruction.md').read_bytes()==original+b'\n---\nFile paths: read /app/input.xlsx and save the completed workbook to /app/output.xlsx.\n'
        assert not (export/'environment/reference.xlsx').exists()
        assert not Path(row['worker_cap_audit']['path']).is_relative_to(export)
        assert source['tool_time_policy_version']==6 and source['tool_time_policy']==dict(m.runner.POLICY_V6)
        assert source['kind']=='fixed_operating_reports_200_prequality_development_source_v6'
        for role in ('environment','tests'):
            assert (export/role/'Dockerfile').read_text().count('ENV MAX_CONCURRENCY=2')==1
    assert m.validate_prepared(c.output)==f and len(c.cold)==2


@pytest.mark.parametrize('change',[{'kind':'complete_operating_metrics_regime_task_engineering'}, {'version':2},
    {'actual_LO_calls_started':7},{'actual_LO_calls_completed':7},{'passed':False},{'qualified':True},{'TEST_ONLY_reject':True}])
def test_only_genuine_complete_own_family_terminal_is_admitted(factory,change):
    c=factory(actual_changes=change)
    with pytest.raises(ValueError):c.m.prepare(c.actual,c.output)
    assert not c.output.exists() and len(c.cold)==1


@pytest.mark.parametrize('change',[{'financial_target_count':1368},{'independent_business_field_count':2052},
    {'DBG_formula_root_count':4},{'kind':'prepared_operating_metrics_regime_task_engineering'}])
def test_fixed_full_business_and_mask_scope_cannot_shrink(factory,change):
    c=factory(prepared_changes=change)
    with pytest.raises(ValueError):c.m.prepare(c.actual,c.output)


def test_wrong_raw_identity_or_any_control_failure_rejected(factory):
    c=factory();m=c.m;m._SPECIFICATION_SHA='0'*64
    with pytest.raises(ValueError,match='fixed200'):m.prepare(c.actual,c.output)
    m._SPECIFICATION_SHA=m.canonical(m.read(m.read(c.candidate)['specification']))
    value=m.read(c.actual);value['records']['modes']['debugging']['controls']['missed_root']=1
    path=c.root/'wrong_control.json';path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='full-D'):m.prepare(m.ref(path),c.output)


def test_original_export_or_v6_policy_mutation_fails_cold(factory):
    c=factory();m=c.m;f=m.read(m.prepare(c.actual,c.output));mode='debugging'
    source_path=Path(f['modes'][mode]['source_view']['path']);source=m.read(source_path);source['tool_time_policy_version']=5
    source_path.write_text(json.dumps(source));f['modes'][mode]['source_view']=m.ref(source_path)
    (c.output/'probe_manifest.json').write_text(json.dumps(f))
    with pytest.raises(ValueError,match='v6'):m.validate_prepared(c.output)


def test_renamed_repacked_material_keeps_one_permanent_attempt(factory):
    c=factory();d=factory('renamed',repacked=True);m=c.m
    left=m.read(m.prepare(c.actual,c.output));right=m.read(m.prepare(d.actual,d.output));mode='financial_modeling'
    assert left['modes'][mode]['material_task_version']==right['modes'][mode]['material_task_version']
    assert c.modes[mode]['input']['sha256']!=d.modes[mode]['input']['sha256']
    started=m.reserve(c.output,left,mode,c.root/'evaluation')
    with pytest.raises(ValueError,match='permanent first attempt'):m.reserve(d.output,right,mode,d.root/'evaluation')
    assert m.read(m.read(started)['reservation'])['no_resampling_after_success_failure_or_infrastructure'] is True


def test_two_modes_reserve_concurrently_and_only_same_material_lock_can_wait(factory):
    c=factory();m=c.m;f=m.read(m.prepare(c.actual,c.output))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda mode:m.reserve(c.output,f,mode,c.root/mode),m.MODES))
    assert {m.read(row)['mode'] for row in results}==set(m.MODES)
    directory=Path(c.history.HISTORY_ROOTS[0])/'.native_development_material_reservations'
    assert len(list(directory.glob('*.lock')))==2 and not (directory/'launch.lock').exists()


def test_same_material_lock_timeout_does_not_reserve_or_launch(factory,monkeypatch):
    c=factory();m=c.m;f=m.read(m.prepare(c.actual,c.output));mode='debugging'
    identity=f['modes'][mode]['material_task_version'];core={k:identity[k] for k in ('mode','input_definitions','input_values','goal_values','instruction_sha256')}
    directory=Path(c.history.HISTORY_ROOTS[0])/'.native_development_material_reservations';directory.mkdir()
    lock=directory/(m.canonical(core)+'.lock');monkeypatch.setattr(m,'_LOCK_WAIT_SECONDS',.01)
    with lock.open('w') as held:
        fcntl.flock(held.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(ValueError,match='wait expired'):m.reserve(c.output,f,mode,c.root/'evaluation')
    assert not list(directory.glob('*.json')) and not (c.output/(mode+'_development_started.json')).exists()


@pytest.mark.parametrize('failure,timing,effective',[(None,True,1),('cumulative_tool_budget_exhausted',False,0),('incomplete_tool_timing',None,None)])
def test_raw_success_never_overrides_budget_failure_or_clock_unknown(factory,failure,timing,effective):
    c=factory();score=c.m.effective_score({'status':'scored','raw_verifier_reward':1,'failure_kind':failure,'tool_time':{'passed':timing}},
        {'status':'completed'},{'passed':True,'complete':True})
    assert score['raw_verifier_reward']==1 and score['effective_reward']==effective


def test_pair_dispatch_uses_exactly_two_processes_and_never_retries(factory,monkeypatch):
    c=factory();m=c.m;f=m.read(m.prepare(c.actual,c.output));calls=[]
    import subprocess
    class Child:
        def __init__(self,command,**kwargs):self.pid=123+len(calls);self.command=command;calls.append((command,kwargs))
        def wait(self):return 0
    monkeypatch.setattr(subprocess,'Popen',Child)
    monkeypatch.setattr(m,'validate_prepared',lambda path:f)
    output=c.root/'execution';result=m.read(m.run_pair(c.output,output))
    assert len(calls)==2 and result['exit_codes']==dict.fromkeys(m.MODES,0)
    assert [command[command.index('--mode')+1] for command,_ in calls]==list(m.MODES)
    assert all(command[2]=='run-development' and kwargs['cwd']==m.ROOT for command,kwargs in calls)
    with pytest.raises(ValueError,match='fresh pair'):m.run_pair(c.output,output)
    assert len(calls)==2


def test_dispatch_failure_preserves_first_child_and_exact_failure_without_retry(factory,monkeypatch):
    c=factory();m=c.m;f=m.read(m.prepare(c.actual,c.output));calls=[];waited=[];failures=[]
    import subprocess
    class Child:
        pid=123
        def wait(self):waited.append(True);return 0
    def launch(command,**kwargs):
        calls.append(command)
        if len(calls)==2:raise OSError('Test-only second process launch failure')
        return Child()
    monkeypatch.setattr(subprocess,'Popen',launch)
    monkeypatch.setattr(m,'validate_prepared',lambda path:f)
    monkeypatch.setattr(m,'_persist_failure',lambda folder,error:failures.append((folder,str(error))))
    output=c.root/'execution'
    with pytest.raises(OSError,match='Test-only'):m.run_pair(c.output,output)
    assert len(calls)==2 and waited==[True] and len(failures)==1
    retained=m.read(output/'pair_dispatch_terminal.json')
    assert retained['launched_modes']==['financial_modeling'] and retained['both_processes_exited_zero'] is False
