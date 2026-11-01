"""Explicit synthetic-only tests of waterfall admission and frozen v6 attempts."""
import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
from types import FunctionType, SimpleNamespace
from zipfile import ZipFile, ZIP_STORED

import openpyxl
import pytest

ROOT=Path(__file__).resolve().parents[1]
ENTRY=ROOT/'scripts/prepare_waterfall_portfolios_development.py'
IO_APPENDIX=b'\n---\nFile paths: read /app/input.xlsx and save the completed workbook to /app/output.xlsx.\n'


def test_production_entry_stays_fail_closed_until_exact_task_validator_is_frozen():
    tree=ast.parse(ENTRY.read_bytes())
    pin=next(n.value.value for n in tree.body if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=='TASK_VALIDATOR_SHA' for t in n.targets))
    spec=importlib.util.spec_from_file_location('_waterfall_actual_pin_only_test',ENTRY)
    module=importlib.util.module_from_spec(spec)
    if len(pin)!=64:
        with pytest.raises(ValueError,match='task8 feature must be frozen'):spec.loader.exec_module(module)
    else:
        assert hashlib.sha256((ROOT/'scripts/validate_waterfall_portfolios_tasks.py').read_bytes()).hexdigest()==pin
        spec.loader.exec_module(module)
        assert module._N['validation_driver']().TERMINAL_KIND=='complete_waterfall_portfolios_task_engineering'


def synthetic_entry():
    """Set only the test namespace's pin; never edit or activate production admission."""
    tree=ast.parse(ENTRY.read_bytes());count=0
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='TASK_VALIDATOR_SHA' for t in node.targets):
            node.value=ast.Constant(hashlib.sha256((ROOT/'scripts/validate_waterfall_portfolios_tasks.py').read_bytes()).hexdigest());count+=1
    assert count==1
    namespace={'__name__':'_TEST_ONLY_waterfall_development_fixture','__file__':str(ENTRY)}
    exec(compile(ast.fix_missing_locations(tree),str(ENTRY),'exec'),namespace)
    return SimpleNamespace(**namespace)


@pytest.fixture
def factory(tmp_path,monkeypatch):
    m=synthetic_entry();namespace=m._N;old=namespace['history_helper']();history_ns=dict(vars(old))
    roots=(tmp_path/'TEST_ONLY_history/difficulty',tmp_path/'TEST_ONLY_history/research')
    for root in roots:root.mkdir(parents=True)
    history_ns['HISTORY_ROOTS']=roots
    for name,value in list(history_ns.items()):
        if isinstance(value,FunctionType) and value.__globals__ is vars(old):
            fn=FunctionType(value.__code__,history_ns,name,value.__defaults__,value.__closure__)
            fn.__kwdefaults__=deepcopy(value.__kwdefaults__);history_ns[name]=fn
    history=SimpleNamespace(**history_ns);cold=[];original_loader=namespace['validation_driver']
    marker=tmp_path/'TEST_ONLY_mock_cold_validator.json';marker.write_text('{"TEST_ONLY":true}\n')
    def completed(value):
        cold.append(value);actual=m.read(value)
        if actual.get('TEST_ONLY_reject'):raise ValueError('Synthetic cold validator rejects before all services')
        return actual
    monkeypatch.setitem(namespace,'history_helper',lambda:history)
    monkeypatch.setitem(namespace,'validation_driver',lambda:SimpleNamespace(validate_completed=completed,recipes=lambda:{str(marker):m.ref(marker)}))
    monkeypatch.setattr(m.runner,'run_evaluation',lambda *a,**k:pytest.fail('No native model calls in these pure fixtures'))
    monkeypatch.setitem(namespace,'verify_local_base_image',lambda *a,**k:pytest.fail('No Docker/image calls in pure preparation'))
    def book(path,value,repacked):
        path.parent.mkdir(parents=True,exist_ok=True);w=openpyxl.Workbook();s=w.active;s.title='Investor bridge'
        s['A1']='TEST ONLY: posted pence and declared signed fund cash use';s['B1']=value;w.save(path);w.close()
        if repacked:
            with ZipFile(path) as z:parts=[(x.filename,z.read(x.filename)) for x in z.infolist()]
            with ZipFile(path,'w',ZIP_STORED) as z:
                z.comment=b'TEST_ONLY_logically_identical_repack'
                for name,data in parts:z.writestr(name,data)
        return m.ref(path)
    def make(name='TEST_ONLY_first',*,repacked=False,actual_changes=None,prepared_changes=None,candidate_changes=None,raw_changes=None):
        folder=tmp_path/name;folder.mkdir();goal=book(folder/'goal.xlsx',100,repacked);views={};modes={}
        for mode in m.MODES:
            instruction=folder/(mode+'.md');instruction.write_bytes(b'Complete the declared forecast fund and investor reports under the Read Me policies.\n')
            views[mode]={'instruction':m.ref(instruction)}
            modes[mode]={'input':book(folder/(mode+'.xlsx'),None if mode=='financial_modeling' else 99,repacked),
                'goal':goal,'instruction':m.ref(instruction),'complete_D_count':170640 if mode=='financial_modeling' else 3500,
                'controls':{'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}}
        raw={'TEST_ONLY':'No production financial contract or cached source proof',
            'funds':[{'id':f'F{i:03}'} for i in range(1,25)],'years':list(range(2025,2045)),
            'scenario_ids':['BASE','DOWN','UP'],'dimension_mode':'production',**(raw_changes or {})}
        raw_ref=m.write(folder/'original_raw.json',raw)
        copy=folder/'emitter_raw_copy.json';copy.write_text(json.dumps(raw,separators=(',',':')))
        # Hash pin overrides exist only in this synthetic namespace. Both raw
        # identities and every shape/field gate in production code still run.
        m._checked_engineering.__globals__['RAW_SHA']=raw_ref['sha256']
        m._checked_engineering.__globals__['SPECIFICATION_SHA']=m.canonical(raw)
        candidate=m.write(folder/'candidate.json',{'kind':'pure_waterfall_portfolios_native_emission','version':1,
            'qualified':False,'specification':m.ref(copy),'specification_sha256':m.canonical(raw),'views':views,
            'sheet_count':100,'formula_count':189600,'FM_mask_count':170640,'DBG_root_count':1296,**(candidate_changes or {})})
        source=m.write(folder/'source_manifest.json',{'TEST_ONLY':'mocked source3 consumed only by mocked cold gate'})
        prepared=m.write(folder/'task_preparation.json',{'kind':'prepared_waterfall_portfolios_task_engineering','version':1,
            'source_manifest':source,'financial_target_count':189600,'forecast_mask_count':170640,'DBG_formula_root_count':1296,
            'specification':raw_ref,'candidate_preparation':candidate,'genuine_goal':goal,**(prepared_changes or {})})
        actual=m.write(folder/'task_terminal.json',{'kind':'complete_waterfall_portfolios_task_engineering','version':1,
            'passed':True,'actual_LO_calls_started':8,'actual_LO_calls_completed':8,'qualified':False,'normal_all12_QA_passed':False,
            'source_manifest':source,'preparation':prepared,'records':{'modes':modes},**(actual_changes or {})})
        return SimpleNamespace(m=m,root=folder,output=folder/'TEST_ONLY_snapshot',actual=actual,candidate=candidate,
            raw=raw_ref,modes=modes,cold=cold,history=history,original_loader=original_loader)
    return make


def test_both_genuine_gate_calls_and_seventeen_file_v6_material_bytes(factory):
    c=factory();m=c.m;f=m.read(m.prepare(c.actual,c.output))
    assert len(c.cold)==1 and f['both_materials_frozen_before_any_model'] is True
    assert f['model']=='gpt-6.1-sol' and f['reasoning_effort']=='xhigh' and f['effective_outer_retries']==0
    assert f['execution_budget']=={'version':1,'elapsed_policy':'operational_guard','elapsed_guard_seconds':14400,'tool_budget_seconds':1800}
    assert f['model_calls_during_preparation']==f['LO_calls_during_preparation']==f['solver_calls']==0
    assert not f['qualified'] and not f['normal_all12_QA_passed'] and not f['difficulty_claimed']
    for mode,row in f['modes'].items():
        folder=Path(row['export_directory']);source=m.read(row['source_view'])
        assert len([p for p in folder.rglob('*') if p.is_file()])==17
        assert (folder/'environment/input.xlsx').read_bytes()==m.checked(c.modes[mode]['input']).read_bytes()
        assert (folder/'tests/reference.xlsx').read_bytes()==m.checked(c.modes[mode]['goal']).read_bytes()
        assert (folder/'instruction.md').read_bytes()==m.checked(row['original_instruction']).read_bytes()+IO_APPENDIX
        assert not (folder/'environment/reference.xlsx').exists()
        assert source['tool_time_policy_version']==6 and source['tool_time_policy']==dict(m.runner.POLICY_V6)
        assert source['kind']=='waterfall_portfolios_24_prequality_development_source_v6'
        assert source['tasks'][0]['source_id']==c.raw['sha256']
        assert all((folder/role/'Dockerfile').read_text().count('ENV MAX_CONCURRENCY=2')==1 for role in ('environment','tests'))
    assert m.validate_prepared(c.output)==f and len(c.cold)==2


@pytest.mark.parametrize('change',[{'kind':'complete_fixed_operating_reports_200_task_engineering'},{'version':2},{'passed':False},
    {'actual_LO_calls_started':7},{'actual_LO_calls_completed':7},{'qualified':True},{'normal_all12_QA_passed':True},{'TEST_ONLY_reject':True}])
def test_no_old_family_partial_or_qualified_terminal_enters(factory,change):
    c=factory(actual_changes=change)
    with pytest.raises(ValueError):c.m.prepare(c.actual,c.output)
    assert len(c.cold)==1 and not c.output.exists()


@pytest.mark.parametrize('which,change',[
    ('prepared',{'financial_target_count':80640}),('prepared',{'forecast_mask_count':62322}),('prepared',{'DBG_formula_root_count':200}),
    ('prepared',{'kind':'prepared_fixed_operating_reports_200_task_engineering'}),
    ('candidate',{'formula_count':657}),('candidate',{'FM_mask_count':189600}),('candidate',{'DBG_root_count':4}),
    ('candidate',{'sheet_count':99}),('candidate',{'kind':'prepared_unverified_fixed_operating_reports_200_pair'}),
    ('raw',{'dimension_mode':'toy'}),('raw',{'years':[2025,2026]}),('raw',{'scenario_ids':['BASE','UP','DOWN']}),
    ('raw',{'funds':[{'id':'F001'}]}),
])
def test_exact_full_raw_dimensions_and_complete_projection_scope(factory,which,change):
    kwargs={which+'_changes':change};c=factory(**kwargs)
    with pytest.raises(ValueError):c.m.prepare(c.actual,c.output)
    assert not c.output.exists()


@pytest.mark.parametrize('identity',['RAW_SHA','SPECIFICATION_SHA'])
def test_original_raw_byte_and_semantic_pins_are_both_mandatory(factory,identity):
    c=factory();c.m._checked_engineering.__globals__[identity]='0'*64
    with pytest.raises(ValueError,match='original 24 funds'):c.m.prepare(c.actual,c.output)


def test_separate_emitter_raw_copy_is_not_a_silent_substitute_for_original_raw(factory):
    c=factory();candidate=c.m.read(c.candidate)
    assert candidate['specification']['sha256']!=c.raw['sha256']
    actual,selected=c.m._checked_engineering(c.actual)
    assert selected['specification']==c.raw and selected['views']==candidate['views']
    assert c.m.read(candidate['specification'])==c.m.read(c.raw)


def test_even_test_namespace_requires_exact_current_validator_bytes(factory,monkeypatch):
    c=factory();monkeypatch.setitem(c.m._N,'VALIDATOR_SHA','0'*64)
    with pytest.raises(ValueError,match='genuine v2 engineering validator'):c.original_loader()
    assert not c.cold and not c.output.exists()


@pytest.mark.parametrize('problem',['FM_D','DBG_D','control','instruction','goal','missing_mode'])
def test_every_material_full_D_control_goal_and_original_request_is_bound(factory,problem):
    c=factory();value=c.m.read(c.actual);material=value['records']['modes']['financial_modeling']
    if problem=='FM_D':material['complete_D_count']-=1
    elif problem=='DBG_D':value['records']['modes']['debugging']['complete_D_count']=0
    elif problem=='control':value['records']['modes']['debugging']['controls']['missed_root']=1
    elif problem=='instruction':material['instruction']=c.m.write(c.root/'changed.md',{'not':'original public instruction'})
    elif problem=='goal':material['goal']=material['input']
    else:value['records']['modes'].pop('debugging')
    ref=c.m.write(c.root/'wrong_actual.json',value)
    with pytest.raises(ValueError):c.m.prepare(ref,c.output)


def test_material_clock_or_policy_mutation_cannot_enter_future_attempt(factory):
    c=factory();m=c.m;f=m.read(m.prepare(c.actual,c.output))
    path=Path(f['modes']['debugging']['source_view']['path']);source=m.read(path);source['tool_time_policy_version']=5
    path.write_text(json.dumps(source));f['modes']['debugging']['source_view']=m.ref(path)
    (c.output/'probe_manifest.json').write_text(json.dumps(f))
    with pytest.raises(ValueError,match='v6'):m.validate_prepared(c.output)


def test_repacking_or_renaming_never_resets_permanent_material_attempt(factory):
    first=factory();second=factory('TEST_ONLY_repacked',repacked=True);m=first.m
    left=m.read(m.prepare(first.actual,first.output));right=m.read(m.prepare(second.actual,second.output));mode='financial_modeling'
    assert left['modes'][mode]['material_task_version']==right['modes'][mode]['material_task_version']
    started=m.reserve(first.output,left,mode,first.root/'evaluation')
    with pytest.raises(ValueError,match='permanent first attempt'):m.reserve(second.output,right,mode,second.root/'evaluation')
    assert m.read(m.read(started)['reservation'])['no_resampling_after_success_failure_or_infrastructure'] is True


def test_same_material_race_has_exactly_one_reservation(factory):
    c=factory();m=c.m;f=m.read(m.prepare(c.actual,c.output));mode='debugging'
    def reserve(i):
        try:return m.reserve(c.output,f,mode,c.root/('evaluation_'+str(i)))
        except ValueError:return None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(reserve,range(2)))
    assert sum(row is not None for row in results)==1
    directory=c.history.HISTORY_ROOTS[0]/'.native_development_material_reservations'
    assert len(list(directory.glob('*.json')))==1


def test_two_modes_reserve_concurrently_without_a_global_cold_lock(factory):
    c=factory();m=c.m;f=m.read(m.prepare(c.actual,c.output))
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda mode:m.reserve(c.output,f,mode,c.root/mode),m.MODES))
    assert {m.read(row)['mode'] for row in results}==set(m.MODES)
    directory=c.history.HISTORY_ROOTS[0]/'.native_development_material_reservations'
    assert len(list(directory.glob('*.lock')))==2 and not (directory/'launch.lock').exists()


@pytest.mark.parametrize('failure,timing,wanted',[(None,True,1),('cumulative_tool_budget_exhausted',False,0),('incomplete_tool_timing',None,None)])
def test_v6_unknown_is_never_zero_and_proven_budget_failure_is_zero(factory,failure,timing,wanted):
    m=factory().m
    actual=m.effective_score({'status':'scored','raw_verifier_reward':1,'failure_kind':failure,'tool_time':{'passed':timing}},
        {'status':'completed'},{'passed':True,'complete':True})
    assert actual['raw_verifier_reward']==1 and actual['effective_reward']==wanted


def test_dispatch_starts_only_two_independent_processes_once(factory,monkeypatch):
    import subprocess
    c=factory();m=c.m;f=m.read(m.prepare(c.actual,c.output));calls=[]
    class Child:
        def __init__(self,command,**kwargs):self.pid=100+len(calls);calls.append((command,kwargs))
        def wait(self):return 0
    monkeypatch.setattr(subprocess,'Popen',Child);monkeypatch.setitem(m._N,'validate_prepared',lambda path:f)
    out=c.root/'dispatch';result=m.read(m.run_pair(c.output,out))
    assert len(calls)==2 and result['exit_codes']==dict.fromkeys(m.MODES,0)
    assert [argv[argv.index('--mode')+1] for argv,_ in calls]==list(m.MODES)
    assert all(Path(argv[1])==ENTRY and kwargs['cwd']==m.ROOT for argv,kwargs in calls)
    with pytest.raises(ValueError,match='fresh pair'):m.run_pair(c.output,out)
    assert len(calls)==2
