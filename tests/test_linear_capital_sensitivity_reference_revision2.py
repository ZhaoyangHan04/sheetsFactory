"""Pure native-import/integer checks and real local audit; no services."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from sheets_factory.workbook.linear_capital_sensitivity import (
    reference_revision2 as ref, runtime_scip3600 as runtime, backend_scip as backend)


def matrix():
    rows=[]
    for family,count in ref.contract.spec.PRODUCTION_COUNTS.items():
        for i in range(count):rows.append({'id':family+':'+str(i).zfill(3),'family':family,
            'scenario_id':None,'year':None,'coefficients':[0]*360,'limit':100})
    return {'kind':'linear_capital_scaled_direct_binary_integer_model','version':2,
        'project_ids':[f'P{i:03d}' for i in range(1,361)],'objective_pence':[-1]*360,
        'rows':sorted(rows,key=lambda r:r['id']),'specification_sha256':'a'*64,'universe_sha256':'b'*64}


def store(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);return ref.write(path,value)


def test_policy_root_vendor_backend_and_frozen_original_namespaces():
    old=runtime.base.prepare
    runtime.adapted_ast();backend.adapted_ast();ref._gate_ast();ref._case_ast()
    assert runtime.base.prepare is old
    assert runtime.ROOT==Path(__file__).resolve().parents[1]
    assert runtime.VENDOR_SITE_PACKAGES==runtime.ROOT/'outputs/tmp/linear-solver-914-py312/lib/python3.12/site-packages'
    assert runtime.DISTRIBUTIONS['pyscipopt']=='6.0.0' and runtime.DISTRIBUTIONS['numpy']=='1.26.4'
    assert set(runtime.BACKENDS)=={'scip'} and len(runtime._source_files())==7
    assert runtime.policy()['producer']=={'cpus':16,'memory_bytes':32*1024**3,'pids_limit':256,
        'threads':16,'network':'none','backend':'scip','solver_seconds_per_attempt':3600,
        'operational_timeout_seconds':3720,'relative_gap':0,'absolute_gap':0,'feasibility_tolerance':1e-9,'automatic_retries':0}
    assert runtime.policy()['maximum_new_native_searches']==2
    assert runtime.policy()['maximum_historical_searches']==19
    assert runtime.policy()['admitted_proofs_required']==18
    assert runtime.policy()['prior_incumbent_or_warm_hint'] is False
    runtime.profile_reference()


def test_portable_seven_file_backend_imports_without_finance_or_optimizer(tmp_path):
    package=tmp_path/'portfolio';package.mkdir();(package/'__init__.py').write_text('')
    for name,path in runtime._source_files().items():shutil.copyfile(path,package/name)
    source="""import sys,json
sys.path.insert(0,sys.argv[1])
import portfolio.model_a as a
import portfolio.model_b as b
model=json.loads(__import__('pathlib').Path(sys.argv[2]).read_text());a.validate_model(model);b.validate_model(model)
assert not hasattr(a,'build_model')
assert not any('finance' in k or 'pyscipopt' in k for k in sys.modules)
assert a.check_plan(model,dict.fromkeys(model['project_ids'],0))['constraints_checked']==941
print('pure-portable-import-pass')
"""
    model_path=tmp_path/'model.json';model_path.write_text(json.dumps(matrix()))
    result=subprocess.run([sys.executable,'-I','-c',source,str(tmp_path),str(model_path)],
        capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='pure-portable-import-pass'


@pytest.mark.parametrize('change',['rows','ids','family','kind'])
def test_runtime_rejects_partial_or_foreign_matrix(change):
    model=matrix()
    if change=='rows':model['rows'].pop()
    elif change=='ids':model['project_ids'].pop()
    elif change=='family':model['rows'][0]['family']='exclusivity'
    else:model['kind']='linear_capital_dimension_probe_direct_binary_integer_model_n720'
    with pytest.raises(ValueError):runtime.validate_model(model)


def test_only_exact_dedup_and_zero_tautology_are_omitted_without_raw_mutation():
    model={'rows':[{'id':'a','coefficients':[1000001,-2000002],'limit':3000003},
        {'id':'duplicate','coefficients':[1000001,-2000002],'limit':3000003},
        {'id':'tautology','coefficients':[0,0],'limit':0},
        {'id':'infeasible_zero','coefficients':[0,0],'limit':-1},
        {'id':'small','coefficients':[11,-22],'limit':33}]}
    before=deepcopy(model);rows,omitted=backend.solver_rows(model)
    assert model==before and [r['id'] for r in rows]==['a','infeasible_zero','small']
    assert omitted==[{'id':'duplicate','reason':'exact_duplicate'},{'id':'tautology','reason':'zero_tautology'}]
    assert [r['positive_solver_scale'] for r in rows]==[100000,1,1000]
    for row in rows:
        raw=next(r for r in model['rows'] if r['id']==row['id'])
        assert row['limit']==raw['limit']/row['positive_solver_scale']


@pytest.mark.parametrize('change',['status','bound','binary','gap','bool'])
def test_native_float_display_or_near_binary_cannot_prove_optimal(change):
    model=matrix();plan=dict.fromkeys(model['project_ids'],0)
    result={'checked_optimal':True,'completed':True,'raw_status':'optimal','objective_pence':0,
        'plan':plan,'native_solution_values':[0.0]*360,'native_objective':0.0,'primal_bound':0.0,'dual_bound':0.0,'gap':0.0}
    result['native_bound_precision']=backend.bound_diagnostics(result)
    backend.strict_evidence(result,model)
    if change=='status':result['raw_status']='timelimit'
    elif change=='bound':result['dual_bound']=1e-8
    elif change=='binary':result['native_solution_values'][0]=0.00000001
    elif change=='gap':result['gap']=1e-10
    else:result['native_solution_values'][0]=False
    result['native_bound_precision']=backend.bound_diagnostics(result)
    with pytest.raises(ValueError):runtime.check_result(model,result)


def original_fixture(tmp_path,monkeypatch):
    root=tmp_path/'original';prepared=store(root/'preparation.json',{'fixture':True})
    order=[c['id'] for c in ref.contract.CASES];records={};rows=[];observed=[]
    for case in ref.contract.CASES:
        identity=case['id'];models={side:store(root/'cases'/identity/('model_'+side+'.json'),matrix()) for side in ('A','B')}
        row={'case':case,'models':models};rows.append(row)
        if identity==ref.FIXED_CASE:
            solver=store(root/'failed_solver.json',{'status':'FEASIBLE','checked_optimal':False})
            native=store(root/'failed_native.json',{'solver_result':solver})
            actual={'passed':False,'native_job_invocations':1,'solver_receipts':{'best':native},'models':models,'case':case}
        else:actual={'fixture':True}
        records[identity]=store(root/'cases'/identity/'terminal.json',actual)
        observed.append({'case_id':identity,'terminal':records[identity]})
    observation=store(tmp_path/'observation.json',{'original_preparation':prepared,'passed':False,
        'original_parent_exit_code':1,'original_parent_outer_terminal_exists':False,'cases_passed':8,'cases_rejected':1,
        'known_native_job_invocations':17,'last_case_FEASIBLE_is_not_optimal_gold':True,
        'runner_not_started_after_failed_best':True,'all9case_terminals_retained':observed})
    frozen={'case_order':order,'best_preparations':{},'all_nine_models':store(tmp_path/'inventory.json',{'fixture':True})}
    incoming={'original_preparation':prepared,'observation':observation,'frozen':frozen,
        'inputs':{'fixture':True},'inventory':{'case_order':order,'cases':rows},
        'original_cases':records,'retained':{k:v for k,v in records.items() if k!=ref.FIXED_CASE}}
    monkeypatch.setattr(ref,'ORIGINAL_PREPARATION_SHA',prepared['sha256'])
    monkeypatch.setattr(ref,'OBSERVATION_SHA',observation['sha256'])
    monkeypatch.setattr(ref.prior,'validate_prepared',lambda _: (frozen,incoming['inputs'],incoming['inventory']))
    return incoming


def test_prior_complete_observation_calls_every_retained_proof_and_never_failed_winner(tmp_path,monkeypatch):
    incoming=original_fixture(tmp_path,monkeypatch);calls=[]
    monkeypatch.setattr(ref,'_checked_case',lambda actual,row,*args,**kwargs:calls.append(row['case']['id']))
    checked=ref._checked_original(incoming['original_preparation'],incoming['observation'])
    assert calls==[c for c in incoming['frozen']['case_order'] if c!=ref.FIXED_CASE]
    assert checked['original_cases']==incoming['original_cases'] and len(checked['retained'])==8
    monkeypatch.setattr(ref,'OBSERVATION_SHA','0'*64)
    with pytest.raises(ValueError):ref._checked_original(incoming['original_preparation'],incoming['observation'])


def test_whole_ancestry_is_frozen_before_the_only_new_native_preparation(tmp_path,monkeypatch):
    incoming=original_fixture(tmp_path,monkeypatch);output=tmp_path/'outputs/new';calls=[]
    monkeypatch.setattr(ref,'ROOT',tmp_path);monkeypatch.setattr(ref,'recipes',lambda:{})
    monkeypatch.setattr(ref,'_checked_original',lambda *args:incoming)
    def prepare(model,folder,**kwargs):
        prospective=ref.read(output/'prospective.json')
        assert prospective['ordered_all_nine_models']==incoming['inventory']['cases']
        assert prospective['retained_complete_cases']==incoming['retained']
        assert prospective['original_all_nine_case_terminals']==incoming['original_cases']
        assert prospective['new_searches_before_this_inventory']==0 and not prospective['prior_incumbent_input']
        assert model==incoming['inventory']['cases'][-1]['models']['A']['path']
        assert kwargs=={'backend':'scip','time_limit_seconds':3600}
        calls.append(folder);return store(folder/'preparation.json',{'fixture':True})
    monkeypatch.setattr(runtime,'prepare',prepare)
    monkeypatch.setattr(runtime,'execute_prepared',lambda *_:pytest.fail('No execution during prepare'))
    result=ref.read(ref.prepare(incoming['original_preparation'],incoming['observation'],output))
    assert len(calls)==1 and set(result['best_preparations'])=={ref.FIXED_CASE}
    assert result['native_solver_calls']==0 and not (output/'started.json').exists()
    with pytest.raises(ValueError):ref.prepare(incoming['original_preparation'],incoming['observation'],output)


@pytest.mark.parametrize('failure',['best_limited','runner_limited','tie','pass'])
def test_new_case_conditional_runner_has_full_exclusion_and_exact_gap(tmp_path,monkeypatch,failure):
    folder=tmp_path/'cases'/ref.FIXED_CASE;model=matrix()
    row={'case':ref.contract.CASES[-1],'models':{s:store(folder/('model_'+s+'.json'),model) for s in ('A','B')}}
    store(tmp_path/'preparation.json',{'fixture':True});job=store(folder/'jobs/best/preparation.json',{'fixture':True})
    frozen={'best_preparations':{ref.FIXED_CASE:job}};winner=dict.fromkeys(model['project_ids'],0)
    other=dict(winner);other['P001']=1;calls=[];preps=[]
    def execute(path):calls.append(path);return store(path/'terminal.json',{'fixture':True})
    def prepare(path,output,**kwargs):
        assert path==row['models']['A']['path']
        assert kwargs=={'backend':'scip','time_limit_seconds':3600,'exclude_plan':winner}
        preps.append(output);return store(output/'preparation.json',{'fixture':True})
    def checked(job,receipt,row,excluded):
        if failure=='best_limited' or failure=='runner_limited' and excluded is not None:raise ValueError('Not OPTIMAL')
        return {'native':{'solver':{'plan':winner if excluded is None else other,
            'objective_pence':0 if excluded is None or failure=='tie' else -1}}}
    monkeypatch.setattr(runtime,'execute_prepared',execute);monkeypatch.setattr(runtime,'prepare',prepare)
    monkeypatch.setitem(ref._case.__globals__,'_checked_job',checked)
    monkeypatch.setitem(ref._case.__globals__,'_financial_projection',lambda *_:{'comparison':{'plans':[
        {'A':{'objective_pence':0},'B':{'objective_pence':0}},
        {'A':{'objective_pence':-1},'B':{'objective_pence':-1}}]}})
    result=ref.read(ref._case(tmp_path,frozen,{},row))
    assert result['passed'] is (failure=='pass')
    assert result['native_job_invocations']==len(calls)==(1 if failure=='best_limited' else 2)
    assert len(preps)==(0 if failure=='best_limited' else 1)
    assert result['version']==2 and result['models']==row['models'] and not result['qualified']
    with pytest.raises(ValueError):ref._case(tmp_path,frozen,{},row)


@pytest.mark.parametrize('export_failure',[False,True])
def test_real_audit_nine_case_parent_writes_terminal_despite_dashboard_export_failure(tmp_path,monkeypatch,export_failure):
    from sheets_factory.core.audit import AuditStore
    from sheets_factory import dashboard
    incoming=original_fixture(tmp_path,monkeypatch);output=tmp_path/'outputs/run'
    preparation=store(output/'preparation.json',{'fixture':True});state={'started':False,'calls':0}
    monkeypatch.setattr(ref,'validate_prepared',lambda _: ({},incoming))
    class Server:
        def __init__(self,*args,**kwargs):pass
        def start(self):state['started']=True;return 'mock://no-socket'
        def stop(self):pass
    monkeypatch.setattr(dashboard,'DashboardServer',Server)
    if export_failure:
        def fail_export(self):raise OSError('fixture read-only dashboard export failure')
        monkeypatch.setattr(AuditStore,'export',fail_export)
    def case(output,frozen,inputs,row,audit):
        assert state['started'];state['calls']+=1
        audit.emit('fixture.new.case');audit.export()
        return store(output/'cases'/ref.FIXED_CASE/'terminal.json',
                     {'passed':True,'native_job_invocations':2,'mock_no_native_calls':True})
    monkeypatch.setattr(ref,'_case',case)
    receipt=ref.execute_prepared(output);result=ref.read(receipt)
    assert state['calls']==1 and result['passed'] is True and result['preparation']==preparation
    assert len(result['cases'])==9 and result['new_native_job_invocations']==2
    assert result['historical_native_job_invocations']==19 and result['admitted_proofs']==18
    assert bool(result['dashboard_errors']) is export_failure
    import sqlite3
    db=sqlite3.connect(output/'audit/run.sqlite')
    assert db.execute('SELECT count(*) FROM tasks').fetchone()[0]==9
    tasks=[json.loads(row[0]) for row in db.execute('SELECT payload FROM tasks')]
    assert {r['id'] for r in tasks}==set(incoming['frozen']['case_order'])
    assert all(r['status']=='passed' for r in tasks);db.close()
    with pytest.raises(ValueError):ref.execute_prepared(output)


def test_runtime_exact_check_rechecks_every_row_and_whole_exclusion(tmp_path,monkeypatch):
    model=matrix();row={'models':{s:store(tmp_path/(s+'.json'),model) for s in ('A','B')}}
    plan=dict.fromkeys(model['project_ids'],0);excluded=dict(plan);excluded['P001']=1
    receipt=store(tmp_path/'native.json',{'private_reference_time_limit_seconds':3600,'operational_timeout_seconds':3720})
    monkeypatch.setattr(ref,'_job_preparation',lambda *args:None)
    monkeypatch.setattr(ref,'validate_solver_receipt',lambda *args,**kwargs:{'checked_optimal':True,'solver':{'plan':plan,'objective_pence':0}})
    result=ref._checked_job(None,receipt,row,excluded)
    assert len(result['independent_integer_checks']['A']['rows'])==942
    assert len(result['independent_integer_checks']['B']['rows'])==941
    assert result['independent_integer_checks']['B']['excluded_plan_distinct'] is True
    monkeypatch.setattr(ref,'validate_solver_receipt',lambda *args,**kwargs:{'checked_optimal':False})
    with pytest.raises(ValueError):ref._checked_job(None,receipt,row,None)


def test_pass_flag_and_missing_original_failure_cannot_admit_a_reference(tmp_path):
    fake={'kind':ref.KIND,'version':2,'passed':True,'all_cases_retained':True,'qualified':False,
        'reference_is_not_source_or_quality_or_difficulty':True,'automatic_retries':0,
        'financial_forwards':0,'LO_calls':0,'model_calls':0,'new_native_job_invocations':2,
        'original_native_job_invocations':16,'historical_native_job_invocations':18,'admitted_proofs':18}
    with pytest.raises(ValueError):ref.validate_completed(store(tmp_path/'fake.json',fake))
