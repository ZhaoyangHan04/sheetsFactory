"""Private reference orchestration fixtures only; no production solver call."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from sheets_factory.workbook.linear_capital_portfolio import optimization_runtime as runtime
from test_linear_capital_optimization_runtime import prepared, mock_execution, services

ROOT=Path(__file__).resolve().parents[1]
definition=importlib.util.spec_from_file_location('linear_reference_test_entry',ROOT/'scripts/run_linear_capital_reference.py')
entry=importlib.util.module_from_spec(definition);definition.loader.exec_module(entry)


@pytest.mark.parametrize('backend',['scip','cp_sat'])
def test_full_mocked_runtime_resource_cleanup_and_exact_result_validation(prepared,monkeypatch,backend):
    monkeypatch.setattr(entry,'TIME_LIMIT',3)
    output,prep=prepared(backend=backend)
    state,commands=mock_execution(output,monkeypatch)
    receipt=runtime.execute_prepared(output)
    result=entry.validate_solver_receipt(prep,receipt,model=runtime.reference(prepared.model),backend=backend)
    assert result['checked_optimal'] is True
    assert result['matrix_result_check']['exact_matrix_plan_check']['all_integer_rows_checked']==1
    assert result['host_before']['bytes']>0 and result['host_after']['bytes']>0
    assert state['released'] and state['cleaned']


@pytest.mark.parametrize('change',['resources','owned_cleanup','native_parameters'])
def test_independent_replay_validator_rejects_rebound_bad_receipts(prepared,monkeypatch,change):
    monkeypatch.setattr(entry,'TIME_LIMIT',3)
    output,prep=prepared();mock_execution(output,monkeypatch)
    terminal_ref=runtime.execute_prepared(output);terminal=entry.read(terminal_ref)
    if change=='resources':
        path=output/'host_after.json';value=runtime._read(path);value['Memory']=8*1024**3;path.write_text(json.dumps(value))
    elif change=='owned_cleanup':
        path=Path(terminal['cleanup']['path']);value=runtime._read(path)
        value['daemon_image_check']['returncode']=1;path.write_text(json.dumps(value));terminal['cleanup']=runtime.reference(path)
    else:
        path=Path(terminal['solver_result']['path']);value=runtime._read(path)
        value['parameters']['limits/gap']=0.01;path.write_text(json.dumps(value));terminal['solver_result']=runtime.reference(path)
        current=runtime._inventory(output/'job_bundle');terminal['retained_job_inventory']=current;terminal['complete_job_inventory']=current
    (output/'terminal.json').write_text(json.dumps(terminal));terminal_ref=runtime.reference(output/'terminal.json')
    with pytest.raises((ValueError,RuntimeError)):
        entry.validate_solver_receipt(prep,terminal_ref,model=runtime.reference(prepared.model),backend='scip')


def checked(plan,objective,optimal=True):
    return {'checked_optimal':optimal,'solver':{'plan':plan,'objective_pence':objective}}


@pytest.mark.parametrize('change',['limited','different_best','different_objective','bool_plan','bool_objective','winner_not_excluded'])
def test_winner_and_runner_agreement_fail_closed(change):
    ids=['P001','P002'];winner={'P001':1,'P002':0};a=checked(winner,7);b=deepcopy(a);excluded=None
    if change=='limited':b['checked_optimal']=False
    elif change=='different_best':b['solver']['plan']={'P001':0,'P002':1}
    elif change=='different_objective':b['solver']['objective_pence']=8
    elif change=='bool_plan':b['solver']['plan']['P001']=True
    elif change=='bool_objective':a['solver']['objective_pence']=b['solver']['objective_pence']=True
    else:excluded=winner
    with pytest.raises(ValueError):entry._agreement(a,b,ids,winner=excluded)


def test_runner_plans_can_differ_at_same_second_best_objective():
    ids=['P001','P002'];winner={'P001':1,'P002':1}
    assert entry._agreement(checked({'P001':1,'P002':0},5),checked({'P001':0,'P002':1},5),ids,winner=winner)[0]==5


def orchestration(tmp_path,monkeypatch,*,limited=False,active_best=False):
    """Explicitly replace financial/runtime boundaries; no real proof is made."""
    output=tmp_path/'outer';output.mkdir()
    declared=entry.write(output/'preparation.json',{'test_only_fake_financial_and_runtime_boundary':True})
    ids=[f'P{i:03d}' for i in range(1,241)];winner={pid:int(i<107) for i,pid in enumerate(ids)}
    runner_a=deepcopy(winner);runner_a['P001']=0;runner_a['P108']=1
    runner_b=deepcopy(winner);runner_b['P002']=0;runner_b['P109']=1
    raw=tmp_path/'fixture.json';raw.write_text('{"test_fixture":true}');ref=entry.reference(raw)
    finance={'terminal':ref,'specification':ref,'raw_preparation':ref,'universe_A':ref,'universe_B':ref,
        'models':{'A':ref,'B':ref},'public':{'project_ids':ids},'A':{'fixture':'A'},'B':{'fixture':'B'}}
    jobs={}
    for side in ('A','B'):
        folder=tmp_path/(side+'_best');folder.mkdir();jobs[side]=entry.write(folder/'preparation.json',{'side':side,'phase':'best'})
        if active_best:entry.write(folder/'started.json',{'still_active_fixture':True})
        else:entry.write(folder/'terminal.json',{'side':side,'phase':'best'})
    frozen={'best_preparations':jobs,'private_density_gate':{'minimum':80,'maximum':160,'public_cardinality_constraint':False},
        'recipe':{str(raw):ref}}
    monkeypatch.setattr(entry,'validate_prepared',lambda _: (frozen,finance))
    calls=[]
    def prepare(model,folder,*,backend,time_limit_seconds,exclude_plan):
        assert time_limit_seconds==3600 and exclude_plan==winner
        side='A' if backend=='scip' else 'B';folder=Path(folder);folder.mkdir(parents=True)
        calls.append(('prepare',side));return entry.write(folder/'preparation.json',{'side':side,'phase':'runner'})
    def execute(folder):
        value=runtime._read(Path(folder)/'preparation.json');calls.append(('execute',value['side']))
        return entry.write(Path(folder)/'terminal.json',value)
    def validate(preparation,terminal,*,model,backend,exclude_plan):
        value=entry.read(terminal);side,phase=value['side'],value['phase']
        plan=winner if phase=='best' else runner_a if side=='A' else runner_b
        return checked(plan,1000 if phase=='best' else 999,not(limited and phase=='best'))
    def plans(public,a,b,choices,*,require_feasible):
        assert require_feasible is True and [p['id'] for p in choices]==['winner','runner_A','runner_B']
        return {'passed':True,'plans':[{'id':p['id'],'A':{'objective_pence':1000 if p['id']=='winner' else 999},
            'B':{'objective_pence':1000 if p['id']=='winner' else 999}} for p in choices],
            'test_only_fake_financial_boundary':True}
    monkeypatch.setattr(runtime,'prepare',prepare);monkeypatch.setattr(runtime,'execute_prepared',execute)
    monkeypatch.setattr(entry,'validate_solver_receipt',validate)
    monkeypatch.setattr(entry.finance_crosscheck,'compare_plans',plans)
    state=services(monkeypatch)
    return output,calls,state,winner


def test_adopts_first_terminal_best_jobs_without_rerun_then_two_runners_and_full_envelope(tmp_path,monkeypatch):
    output,calls,state,winner=orchestration(tmp_path,monkeypatch)
    terminal=entry.execute_prepared(output);value=entry.read(terminal)
    assert value['passed'] and value['winner_plan']==winner and value['selected_project_count']==107
    assert value['winner_objective_pence']==1000 and value['runner_objective_pence']==999 and value['gap_pence']==1
    assert sorted(calls)==[('execute','A'),('execute','B'),('prepare','A'),('prepare','B')]
    assert set(value['solver_receipts'])=={'A_best','B_best','A_runner','B_runner'}
    assert value['solver_status_is_not_formal_certificate'] is True
    assert state['released'] and state['closed'] and state['stopped']
    assert entry.validate_completed(terminal)==value
    value['gap_pence']=0;Path(terminal['path']).write_text(json.dumps(value))
    with pytest.raises(ValueError,match='gap'):entry.validate_completed(entry.reference(terminal['path']))


@pytest.mark.parametrize('case',['limited','active'])
def test_stops_after_limited_or_active_first_jobs_without_runner_or_retry(tmp_path,monkeypatch,case):
    output,calls,state,_=orchestration(tmp_path,monkeypatch,limited=case=='limited',active_best=case=='active')
    result=entry.read(entry.execute_prepared(output))
    assert result['passed'] is False and calls==[]
    assert state['released'] and state['closed'] and state['stopped']
    assert (output/'failure.json').is_file()
    with pytest.raises(ValueError):entry.execute_prepared(output)


def test_terminal_write_failure_still_releases_lease_and_closes_services(tmp_path,monkeypatch):
    output,calls,state,_=orchestration(tmp_path,monkeypatch)
    original=entry.write
    def fail(path,value):
        if Path(path)==output/'terminal.json':raise OSError('explicit test filesystem failure')
        return original(path,value)
    monkeypatch.setattr(entry,'write',fail)
    with pytest.raises(OSError):entry.execute_prepared(output)
    assert state['released'] and state['closed'] and state['stopped']


def test_prospective_first_pair_manifest_binds_exact_models_and_first_preparations(tmp_path,monkeypatch):
    data=tmp_path/'model.json';data.write_text('{"fixture":true}');model=entry.reference(data)
    job_a=tmp_path/'A.json';job_a.write_text('{"first":"A"}')
    job_b=tmp_path/'B.json';job_b.write_text('{"first":"B"}')
    finance={'terminal':model,'models':{'A':model,'B':model}}
    payload={'kind':'prospective_first_pair_of_linear_capital_best_jobs','version':1,'financial_crosscheck':model,
        'models':finance['models'],'per_job_limit_seconds':3600,'agent_tool_budget_unchanged':True,
        'automatic_retry_or_retune':False,'best_preparations':{'A':entry.reference(job_a),'B':entry.reference(job_b)}}
    record=entry.write(tmp_path/'first_pair.json',payload)
    assert entry._adopted_best(record,finance)[1]==payload['best_preparations']
    data.write_text('{"changed":true}')
    with pytest.raises(ValueError):entry._adopted_best(record,finance)


def test_cli_prepare_does_not_execute_solver(tmp_path,monkeypatch):
    monkeypatch.setattr(entry,'prepare',lambda *args,**kwargs:{'explicit_fixture_only':True})
    monkeypatch.setattr(entry,'execute_prepared',lambda *_:pytest.fail('CLI preparation started a solver'))
    assert entry.main(['prepare','--finance-terminal','fixture.json','--output',str(tmp_path/'fresh')])==0
