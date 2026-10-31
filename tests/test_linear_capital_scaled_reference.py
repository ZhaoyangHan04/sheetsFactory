"""N360 code, exact tiny matrices and mocked lifecycles; no actual services."""
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sheets_factory.workbook.linear_capital_portfolio import optimization_runtime as old
from sheets_factory.workbook.linear_capital_portfolio import producer_optimization_runtime as previous
from sheets_factory.workbook.linear_capital_scaled import optimization_runtime as runtime
from sheets_factory.workbook.linear_capital_scaled import reference as entry
from sheets_factory.workbook.linear_capital_scaled import spec
from test_linear_capital_optimization_runtime import services

ROOT=Path(__file__).resolve().parents[1]


def matrix():
    return {'kind':runtime.MODEL_KIND,'version':2,'project_ids':['P001','P002'],
        'objective_pence':[7,4],'rows':[{'id':'initial_sponsor_equity','family':'initial_sponsor_equity',
        'scenario_id':None,'year':None,'coefficients':[2,1],'limit':2}],
        'specification_sha256':'1'*64,'universe_sha256':'2'*64}


def production_matrix():
    model=matrix();model['project_ids']=[f'P{i:03}' for i in range(1,361)]
    model['objective_pence']=[7,4]+[0]*358
    rows=[]
    for family,count in spec.PRODUCTION_COUNTS.items():
        for index in range(count):
            rows.append({'id':family+':'+str(index).zfill(4),'family':family,'scenario_id':None,
                'year':None,'coefficients':[0]*360,'limit':0})
    model['rows']=sorted(rows,key=lambda row:row['id']);return model


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value)+'\n')
    return runtime.reference(path)


def test_new_runtime_namespace_has_new_identity_and_old_resource_contract():
    assert runtime.MODEL_KIND=='linear_capital_scaled_direct_binary_integer_model'
    assert runtime.PREPARATION_KIND=='prepared_private_linear_capital_scaled_producer16_solver'
    assert set(runtime.BACKENDS)=={'cp_sat'}
    assert set(previous.BACKENDS)=={'cp_sat'} and set(old.BACKENDS)=={'cp_sat','scip'}
    assert old.validate_model.__globals__ is not runtime.validate_model.__globals__
    assert runtime.PROFILE==previous.PROFILE and runtime.profile_reference()==previous.profile_reference()
    assert len(runtime._source_files())==6
    assert 'finance.py' not in runtime._source_files()
    runtime.validate_model(production_matrix())


@pytest.mark.parametrize('change',['old_kind','old_version','N240','N359','lost_row','wrong_family','overflow'])
def test_new_matrix_identity_and_complete_census_cannot_be_reinterpreted(change):
    model=production_matrix()
    if change=='old_kind':model['kind']='linear_capital_portfolio_direct_binary_integer_model'
    if change=='old_version':model['version']=1
    if change in {'N240','N359'}:
        n=240 if change=='N240' else 359
        model['project_ids']=model['project_ids'][:n];model['objective_pence']=model['objective_pence'][:n]
        for row in model['rows']:row['coefficients']=row['coefficients'][:n]
    if change=='lost_row':model['rows'].pop()
    if change=='wrong_family':model['rows'][0]['family']='other'
    if change=='overflow':model['objective_pence'][0]=2**53
    with pytest.raises(ValueError):runtime.validate_model(model)


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    vendor=tmp_path/'vendor';vendor.mkdir();(vendor/'dummy.py').write_text('# Exact mocked package boundary\n')
    monkeypatch.setattr(runtime,'VENDOR_SITE_PACKAGES',vendor)
    monkeypatch.setattr(runtime,'VENDOR_ROOTS',{'dummy.py'})
    model=dump(tmp_path/'model.json',matrix())
    def make(name='job',excluded=None):
        output=tmp_path/name
        ref=runtime.prepare(model['path'],output,backend='cp_sat',time_limit_seconds=3600,
            exclude_plan=excluded,vendor_site_packages=vendor)
        return output,ref
    make.model=model;return make


def test_preparation_is_only_exact_source_vendor_copy_and_standalone_import(prepared,monkeypatch):
    monkeypatch.setattr(runtime,'_command',lambda *a,**k:pytest.fail('No services in preparation'))
    output,ref=prepared();frozen=runtime.validate_prepared(output)
    assert frozen['version']==2 and frozen['request']['threads']==16
    assert frozen['resources']=={'cpus':16,'memory_bytes':32*1024**3,'pids_limit':256}
    assert frozen['network']=='none' and frozen['request']['time_limit_seconds']==3600
    assert frozen['solver_calls']==frozen['model_calls']==0
    code="import sys;sys.dont_write_bytecode=True;sys.path.insert(0,sys.argv[1]);import portfolio.model_a as a;import portfolio.model_b as b;print(a.KIND);print('portfolio.finance' in sys.modules)"
    result=subprocess.run([sys.executable,'-I','-c',code,str(output/'job_bundle')],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert result.stdout=='linear_capital_scaled_direct_binary_integer_model\nFalse\n'
    assert runtime.validate_prepared(output)==frozen


@pytest.mark.parametrize('change',['version','CPU','threads','time','profile','bundle'])
def test_frozen_job_guards(prepared,change):
    output,ref=prepared();frozen=runtime._read(ref['path'])
    if change=='version':frozen['version']=1
    if change=='CPU':frozen['resources']['cpus']=2
    if change=='threads':frozen['request']['threads']=2
    if change=='time':frozen['request']['time_limit_seconds']=1800
    if change=='profile':frozen['producer_profile']['sha256']='0'*64
    if change=='bundle':(output/'job_bundle/portfolio/frozen_model_b.py').unlink()
    Path(ref['path']).write_text(json.dumps(frozen))
    with pytest.raises(ValueError):runtime.validate_prepared(output)


def mock_run(output,monkeypatch,*,fault=None,limited=False):
    state=services(monkeypatch);frozen=runtime.validate_prepared(output);bundle=output/'job_bundle';cid='a'*64
    commands=[]
    def inspect():
        return {'Id':cid,'Name':'/sf-scaled-producer16-integer-'+frozen['request']['nonce'],
            'Image':runtime.IMAGE_ID,'NanoCpus':(2 if fault=='CPU' else 16)*10**9,
            'Memory':32*1024**3,'PidsLimit':256,'NetworkMode':'none','Privileged':False,
            'CapDrop':['ALL'],'CapAdd':['DAC_OVERRIDE'],'SecurityOpt':['no-new-privileges'],
            'Mounts':[{'Type':'bind','Source':str(bundle),'Destination':'/app','RW':True}],
            'User':'0','WorkingDir':'/app','Entrypoint':['/usr/bin/python3'],'Cmd':['/app/run.py'],
            'State':{'Status':'exited' if state.get('attached') else 'created','Running':False,'ExitCode':0,'OOMKilled':False}}
    def command(args,*,timeout=30):
        commands.append(args)
        if args[:3]==['docker','image','inspect']:return subprocess.CompletedProcess(args,0,runtime.IMAGE_ID+'\n','')
        if args[:2]==['docker','create']:
            assert args[args.index('--cpus')+1]=='16';return subprocess.CompletedProcess(args,0,cid+'\n','')
        if args[:2]==['docker','inspect']:
            return subprocess.CompletedProcess(args,1,'','Error: no such object') if state.get('cleaned') else subprocess.CompletedProcess(args,0,json.dumps(inspect()),'')
        if args[:2]==['docker','rm']:state['cleaned']=True;return subprocess.CompletedProcess(args,0,cid,'')
        raise AssertionError(args)
    def attach(args,stdout,stderr,timeout):
        assert timeout==3720;state['attached']=True;stdout.write_text('Explicit mocked native result\n');stderr.write_text('')
        solver={'checked_optimal':not limited,'status':'FEASIBLE' if limited else 'OPTIMAL',
            'plan':{'P001':1,'P002':1 if fault=='row' else 0},'objective_pence':11 if fault=='row' else 7,
            'exclude_plan':frozen['request']['exclude_plan'],'model_sha256':frozen['model_canonical_sha256'],
            'specification_sha256':matrix()['specification_sha256'],'universe_sha256':matrix()['universe_sha256'],
            'gap_parameters':{'relative':0,'absolute':0},'threads':2 if fault=='workers' else 16,'time_limit_seconds':3600}
        dump(bundle/'solver_result.json',solver)
        dump(bundle/'runtime_result.json',{'completed':True,'backend':'cp_sat','financial_forward_executed':False,
            'model_canonical_sha256':frozen['model_canonical_sha256'],'threads':16,'gap_requested':0,
            'distribution_versions':runtime.DISTRIBUTIONS})
        for name in ('solver.log','native_model.pbtxt','native_model.pbtxt.parameters.pbtxt'):(bundle/name).write_text('Explicit mocked native artifact\n')
        return subprocess.CompletedProcess(args,0)
    monkeypatch.setattr(runtime,'_command',command);monkeypatch.setattr(runtime,'_attach',attach)
    return state,commands


def test_mocked_native_execution_retains_exact_row_resource_cleanup_and_receipt_gates(prepared,monkeypatch):
    output,ref=prepared();state,commands=mock_run(output,monkeypatch)
    terminal=runtime.execute_prepared(output)
    checked=entry.validate_solver_receipt(ref,terminal,model=prepared.model,backend='cp_sat')
    assert checked['checked_optimal'] is True
    assert checked['matrix_result_check']['exact_matrix_plan_check']['all_integer_rows_checked']==1
    assert state['cleaned'] and state['released'] and state['closed'] and state['stopped']
    assert runtime._read(terminal['path'])['version']==2
    with pytest.raises(ValueError):runtime.execute_prepared(output)


@pytest.mark.parametrize('fault',['CPU','workers','row'])
def test_mocked_native_failure_cannot_admit_reference(prepared,monkeypatch,fault):
    output,ref=prepared();state,_=mock_run(output,monkeypatch,fault=fault)
    with pytest.raises(runtime.OptimizationRuntimeError) as error:runtime.execute_prepared(output)
    assert runtime._read(error.value.receipt['path'])['status']=='execution_failed'
    assert state['cleaned'] and state['released']


def test_limited_incumbent_is_preserved_but_not_reference(prepared,monkeypatch):
    output,ref=prepared();mock_run(output,monkeypatch,limited=True)
    terminal=runtime.execute_prepared(output)
    checked=entry.validate_solver_receipt(ref,terminal,model=prepared.model,backend='cp_sat')
    assert checked['checked_optimal'] is False
    assert runtime._read(terminal['path'])['status']=='reference_not_proven_optimal'


def test_both_complete_independent_matrices_are_required(tmp_path,monkeypatch):
    fake=dump(tmp_path/'job.json',{'producer_profile':runtime.profile_reference()})
    model=production_matrix();model['rows'][0]['coefficients'][0]=1;model['rows'][0]['limit']=1
    plan={pid:int(i==0) for i,pid in enumerate(model['project_ids'])}
    solver={'checked_optimal':True,'status':'OPTIMAL','plan':plan,'objective_pence':7}
    monkeypatch.setattr(entry,'validate_solver_receipt',lambda *a,**k:{'checked_optimal':True,'solver':solver})
    finance={'models':{'B':fake},'model_values':{'A':model,'B':deepcopy(model)}}
    _,checks=entry._checked_job(fake,fake,finance,None)
    assert set(checks)=={'A','B'}
    assert all(v['exact_matrix_plan_check']['all_integer_rows_checked']==941 for v in checks.values())
    finance['model_values']['B']['rows'][0]['limit']=0
    with pytest.raises(ValueError,match='violates'):entry._checked_job(fake,fake,finance,None)


def outer_fixture(tmp_path,monkeypatch,*,limited=False,tie=False):
    output=tmp_path/'reference';output.mkdir();ids=[f'P{i:03}' for i in range(1,361)]
    winner={pid:int(i<140) for i,pid in enumerate(ids)};runner=deepcopy(winner);runner['P001']=0
    boundary=dump(tmp_path/'offline_boundary.json',{'explicit_mock_finance':True})
    finance={'terminal':boundary,'specification':boundary,'raw_preparation':boundary,'universe_A':boundary,
        'universe_B':boundary,'models':{'A':boundary,'B':boundary},'public':{'project_ids':ids},
        'A':{},'B':{}}
    frozen={'best_preparation':dump(output/'jobs/best/preparation.json',{'phase':'best'}),
        'private_density_gate':{'minimum':120,'maximum':240,'public_cardinality_constraint':False},'recipe':{}}
    dump(output/'preparation.json',{'explicit_offline_boundary':True})
    monkeypatch.setattr(entry,'validate_prepared',lambda _:(frozen,finance));calls=[]
    def prepare(model,folder,**kwargs):
        assert kwargs['exclude_plan']==winner and kwargs['backend']=='cp_sat' and kwargs['time_limit_seconds']==3600
        calls.append('prepare_runner');return dump(folder/'preparation.json',{'phase':'runner'})
    def execute(folder):
        phase=entry.read(folder/'preparation.json')['phase'];calls.append(phase)
        return dump(folder/'terminal.json',{'phase':phase})
    def checked(job,terminal,finance,excluded):
        phase=entry.read(job)['phase']
        if phase=='best' and limited:raise ValueError('A limited producer solve is not an optimal reference')
        solver={'plan':winner if phase=='best' else runner,'objective_pence':100 if phase=='best' or tie else 99,'checked_optimal':True}
        return {'checked_optimal':True,'solver':solver},{'A':{'checked_optimal':True},'B':{'checked_optimal':True}}
    monkeypatch.setattr(runtime,'prepare',prepare);monkeypatch.setattr(runtime,'execute_prepared',execute)
    monkeypatch.setattr(entry,'_checked_job',checked);monkeypatch.setattr(entry,'_financial',lambda *args:{'passed':True})
    services(monkeypatch);return output,calls,winner


@pytest.mark.parametrize('limited,tie',[(False,False),(True,False),(False,True)])
def test_best_and_complete_excluded_runner_gate_unchanged(tmp_path,monkeypatch,limited,tie):
    output,calls,winner=outer_fixture(tmp_path,monkeypatch,limited=limited,tie=tie)
    ref=entry.execute_prepared(output);terminal=entry.read(ref)
    assert terminal['version']==2 and terminal['qualified'] is False and terminal['task_count']==0
    assert terminal['passed'] is (not limited and not tie)
    if limited:assert calls==['best'] and not (output/'runner_preparation.json').exists()
    else:
        assert calls==['best','prepare_runner','runner']
        assert entry.read(output/'runner_preparation.json')['complete_excluded_plan']==winner
    if not limited and not tie:
        assert terminal['gap_pence']==1 and terminal['unique_best'] is True
        assert terminal['selected_project_count']==140 and terminal['global_search_implementation_count']==1


def test_old_scope_finance_and_frozen_dependency_drift_rejected(tmp_path,monkeypatch):
    ref=dump(tmp_path/'old.json',{'kind':'linear_capital_full_financial_crosscheck','version':1,'passed':True})
    with pytest.raises(ValueError):entry._checked_finance(ref)
    monkeypatch.setattr(runtime,'FROZEN_PRODUCER_SHA256','0'*64)
    with pytest.raises(ValueError,match='dependency changed'):runtime.adapted_ast()
    with pytest.raises(ValueError,match='dependency changed'):runtime.profile_reference()


def finance_fixture(tmp_path,monkeypatch):
    """Fake completed-finance boundary; test cold transport without a forward."""
    public={'dimension_mode':'production','project_ids':[f'P{i:03}' for i in range(1,361)]}
    public_ref=dump(tmp_path/'specification.json',public)
    raw=dump(tmp_path/'raw.json',{'specification':public_ref,'specification_sha256':spec.canonical_sha256(public),
        'diagnostic_plans':[{'id':'explicit_mock_diagnostic','plan':{}}]})
    universes={side:{'explicit_mock_forward':side} for side in ('A','B')}
    models={side:production_matrix() for side in ('A','B')}
    for side in models:
        models[side]['specification_sha256']=spec.canonical_sha256(public)
        models[side]['universe_sha256']=entry._sha(universes[side])
    financial={'passed':True,'explicit_mock_complete_comparison':True}
    plans={'passed':True,'explicit_mock_plan_comparison':True}
    envelope={'kind':entry.FINANCE_KIND,'version':2,'passed':True,'qualified':False,
        'optimizer_calls':0,'LO_calls':0,'model_calls':0,'recipe':entry.finance_recipes(),
        'specification':public_ref,'raw_preparation':raw,
        'complete_financial_comparison':dump(tmp_path/'financial.json',financial),
        'all_predeclared_plan_comparison':dump(tmp_path/'plans.json',plans),
        'complete_matrix_comparison':dump(tmp_path/'matrices.json',{'passed':True})}
    for side in ('A','B'):
        envelope['universe_'+side]=dump(tmp_path/('universe_'+side+'.json'),universes[side])
        envelope['model_'+side]=dump(tmp_path/('model_'+side+'.json'),models[side])
    monkeypatch.setattr(entry.spec,'load_spec',lambda value:value)
    monkeypatch.setattr(entry.spec,'expected_constraint_count',lambda value:941)
    monkeypatch.setattr(entry.finance_crosscheck,'compare_universes',lambda *args:financial)
    monkeypatch.setattr(entry.finance_crosscheck,'compare_plans',lambda *args:plans)
    return envelope,models


def test_persisted_finance_terminal_matches_new_driver_direct_ref_schema(tmp_path,monkeypatch):
    envelope,models=finance_fixture(tmp_path,monkeypatch)
    ref=dump(tmp_path/'terminal.json',envelope);cold=entry._checked_finance(ref)
    assert cold['terminal']==ref and cold['model_values']==models
    assert len(cold['public']['project_ids'])==360 and all(len(m['rows'])==941 for m in cold['model_values'].values())


@pytest.mark.parametrize('change',['inner_kind','version','bool_calls','missing_comparison','matrix_scope','matrix_ancestry','matrix_difference'])
def test_cold_finance_evidence_rejects_incomplete_or_wrong_scope(tmp_path,monkeypatch,change):
    envelope,models=finance_fixture(tmp_path,monkeypatch)
    if change=='inner_kind':envelope['kind']='independent_scaled_linear_capital_financial_crosscheck'
    if change=='version':envelope['version']=1
    if change=='bool_calls':envelope['model_calls']=False
    if change=='missing_comparison':envelope.pop('complete_financial_comparison')
    if change in {'matrix_scope','matrix_ancestry','matrix_difference'}:
        model=models['B']
        if change=='matrix_scope':model['rows'].pop()
        if change=='matrix_ancestry':model['universe_sha256']='f'*64
        if change=='matrix_difference':model['objective_pence'][0]=8
        envelope['model_B']=dump(tmp_path/'model_B.json',model)
    with pytest.raises((ValueError,KeyError)):
        entry._checked_finance(dump(tmp_path/'terminal.json',envelope))


def test_cli_exposes_frozen_source_builder_api():
    path=ROOT/'scripts/run_linear_capital_scaled_reference.py'
    descriptor=importlib.util.spec_from_file_location('_scaled_reference_cli_test',path)
    cli=importlib.util.module_from_spec(descriptor);descriptor.loader.exec_module(cli)
    for name in ('KIND','PREPARED','recipes','_checked_finance','prepare','validate_prepared','execute_prepared','validate_completed'):
        assert getattr(cli,name)==getattr(entry,name)
    assert cli.KIND=='linear_capital_scaled_producer16_best_runner_dual_financial_reference'
