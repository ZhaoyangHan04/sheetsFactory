"""Pure development gates with an explicit mock of actual cold engineering."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
import importlib.util
import json
from pathlib import Path
from types import FunctionType, SimpleNamespace
import zipfile

import openpyxl
import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def factory(tmp_path,monkeypatch):
    descriptor=importlib.util.spec_from_file_location('_test_period_development',ROOT/'scripts/prepare_period_boundary_development.py')
    module=importlib.util.module_from_spec(descriptor);descriptor.loader.exec_module(module)
    genuine=module.validation_driver();original_history=module.history_helper();private=dict(original_history.__dict__)
    roots=(tmp_path/'history/difficulty',tmp_path/'history/research')
    for root in roots:root.mkdir(parents=True)
    private['HISTORY_ROOTS']=roots
    for name,value in list(private.items()):
        if isinstance(value,FunctionType) and value.__globals__ is original_history.__dict__:
            bound=FunctionType(value.__code__,private,name,value.__defaults__,value.__closure__)
            bound.__kwdefaults__=deepcopy(value.__kwdefaults__);private[name]=bound
    history=SimpleNamespace(**private);cold_calls=[]
    def validate_completed(value):
        cold_calls.append(value);actual=module.read(value)
        if actual.get('TEST_ONLY_cold_rejection'):raise ValueError('Explicit mocked real cold validator rejection')
        return actual
    monkeypatch.setattr(module,'history_helper',lambda:history)
    monkeypatch.setattr(module,'validation_driver',lambda:SimpleNamespace(validate_completed=validate_completed,recipes=genuine.recipes))
    monkeypatch.setattr(module.runner,'run_evaluation',lambda *a,**k:pytest.fail('Preparation cannot start a model'))
    monkeypatch.setattr(module,'verify_local_base_image',lambda *a,**k:pytest.fail('Preparation cannot inspect Docker'))
    def dump(path,value):return module.write(path,value)
    def book(path,value,repacked=False):
        path.parent.mkdir(parents=True,exist_ok=True);w=openpyxl.Workbook();s=w.active;s.title='Operations'
        s['A1']='Provided business policy';s['B1']=value;s['C1']=datetime(2028,2,29);w.save(path);w.close()
        if repacked:
            with zipfile.ZipFile(path) as src:members=[(x,src.read(x.filename)) for x in src.infolist()]
            with zipfile.ZipFile(path,'w',zipfile.ZIP_STORED) as dst:
                dst.comment=b'Equivalent repack has a different archive identity'
                for member,body in members:dst.writestr(member.filename,body)
        return module.ref(path)
    def make(name='first',repacked=False,**changes):
        folder=tmp_path/name;folder.mkdir();goal=book(folder/'goal.xlsx',100,repacked)
        modes={mode:{'input':book(folder/(mode+'.xlsx'),None if mode=='financial_modeling' else 99,repacked),'goal':goal} for mode in module.MODES}
        instructions={}
        for mode in module.MODES:
            p=folder/(mode+'.md');p.write_bytes((module.BRIEFS[mode]+'\n').encode());instructions[mode]=module.ref(p)
        source=dump(folder/'public_specification.json',{'kind':'TEST_ONLY_tiny_public_primitives'})
        candidate=dump(folder/'candidate.json',{'kind':'offline_synthetic_period_boundary_candidate','synthetic':True,
            'formula_count':657,'FM_D_count':657,'DBG_D_count':397,'source_specification':source,'instructions':instructions})
        prepared=dump(folder/'engineering_preparation.json',{'candidate_manifest':candidate})
        actual=dump(folder/'engineering_terminal.json',{'kind':'period_boundary_actual_shared_engineering_validation_v2','version':2,
            'passed':True,'actual_LO_calls_completed':10,'qualified':False,'preparation':prepared,'records':{'modes':modes},**changes})
        return SimpleNamespace(module=module,root=folder,actual=actual,candidate=candidate,modes=modes,output=folder/'snapshot',cold_calls=cold_calls,history=history)
    return make


def test_both_materials_real_seventeen_file_exports_preserve_bytes_and_pending_gates(factory):
    c=factory();m=c.module;r=m.prepare(c.actual,c.output);f=m.read(r)
    assert len(c.cold_calls)==1 and f['both_materials_frozen_before_any_model']
    assert f['mode_order']==list(m.MODES) and f['model_calls_during_preparation']==f['LO_calls_during_preparation']==0
    assert not f['qualified'] and not f['normal_all12_QA_passed'] and f['public_recovery_pending']
    assert f['model']=='gpt-6.1-sol' and f['reasoning_effort']=='xhigh' and f['effective_outer_retries']==0
    for mode,record in f['modes'].items():
        exported=Path(record['export_directory']);files=[p for p in exported.rglob('*') if p.is_file()]
        assert len(files)==17
        assert (exported/'environment/input.xlsx').read_bytes()==m.checked(c.modes[mode]['input']).read_bytes()
        assert (exported/'tests/reference.xlsx').read_bytes()==m.checked(c.modes[mode]['goal']).read_bytes()
        original=m.checked(record['original_instruction']).read_bytes();rendered=(exported/'instruction.md').read_bytes()
        assert rendered==original+b'\n---\nFile paths: read /app/input.xlsx and save the completed workbook to /app/output.xlsx.\n'
        assert m.inspect_resource_export(exported,audit_path=record['worker_cap_audit'])==record['export_binding']
        assert not Path(record['worker_cap_audit']['path']).is_relative_to(exported)
    assert m.validate_prepared(c.output)==f and len(c.cold_calls)==2


@pytest.mark.parametrize('changes',[
    {'kind':'period_boundary_actual_shared_engineering_validation','version':1},
    {'kind':'period_boundary_actual_shared_engineering_validation_v2','version':1},
    {'actual_LO_calls_completed':9},{'TEST_ONLY_cold_rejection':True},
])
def test_old_failed_or_incomplete_engineering_cannot_enter_by_json_flags(factory,changes):
    c=factory(**changes)
    with pytest.raises(ValueError):c.module.prepare(c.actual,c.output)
    assert len(c.cold_calls)==1 and not c.output.exists()


def test_modified_export_is_rejected_by_complete_binding(factory):
    c=factory();m=c.module;f=m.read(m.prepare(c.actual,c.output));p=Path(f['modes']['financial_modeling']['export_directory'])/'environment/input.xlsx'
    p.write_bytes(p.read_bytes()+b'changed bytes')
    with pytest.raises(ValueError):m.validate_prepared(c.output)


def test_permanent_content_reservation_blocks_renamed_repacked_attempt(factory):
    first=factory('first');second=factory('renamed',repacked=True);m=first.module
    a=m.read(m.prepare(first.actual,first.output));b=m.read(m.prepare(second.actual,second.output))
    for mode in m.MODES:
        assert a['modes'][mode]['material_task_version']==b['modes'][mode]['material_task_version']
        assert first.modes[mode]['input']['sha256']!=second.modes[mode]['input']['sha256']
    started=m.reserve(first.output,a,'financial_modeling',first.root/'evaluation')
    reservation=m.read(started)['reservation'];assert m.checked(reservation).is_file()
    with pytest.raises(ValueError,match='permanent first attempt'):
        m.reserve(second.output,b,'financial_modeling',second.root/'evaluation')
    assert m.checked(reservation).is_file() and not (second.output/'financial_modeling_development_started.json').exists()


def test_two_modes_can_reserve_concurrently_with_distinct_permanent_materials(factory):
    c=factory();m=c.module;f=m.read(m.prepare(c.actual,c.output))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(m.reserve,c.output,f,mode,c.root/('evaluation_'+mode)) for mode in m.MODES]
        starts=[m.read(future.result()) for future in futures]
    assert {s['mode'] for s in starts}==set(m.MODES)
    assert len({s['reservation']['path'] for s in starts})==2
    assert all(m.read(s['reservation'])['no_resampling_after_success_failure_or_infrastructure'] for s in starts)


@pytest.mark.parametrize('failure,clock,effective,state',[
    (None,True,1,'complete'),('cumulative_tool_budget_exhausted',False,0,'known_tool_budget_failure'),
    ('incomplete_tool_timing',None,None,'unknown'),
])
def test_effective_score_keeps_raw_one_and_clock_eligibility_separate(factory,failure,clock,effective,state):
    c=factory();score=c.module.effective_score({'status':'scored','raw_verifier_reward':1,'failure_kind':failure,'tool_time':{'passed':clock}},
        {'status':'completed'},{'passed':True,'complete':True})
    assert score['raw_verifier_reward']==1 and score['effective_reward']==effective and score['state']==state
