"""Tiny matrices and mocked processes only; no native optimizer or container."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

from sheets_factory.workbook.linear_capital_scaled import highs_runtime as adapter, highs_engineering as engineering
from test_linear_capital_optimization_runtime import services
from test_linear_capital_scaled_reference import matrix, production_matrix

ROOT = Path(__file__).resolve().parents[1]


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value))
    return ref(path)


def ref(path):
    path=Path(path).resolve();data=path.read_bytes()
    return {'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    vendor=tmp_path/'vendor';source=tmp_path/'old_approved';source.mkdir();vendor.mkdir()
    old={};inventory={}
    for name in adapter.VENDOR_ROOTS:
        path=vendor/name/'unit_fixture.txt';path.parent.mkdir();path.write_text('EXPLICIT UNIT BYTES; NOT A PACKAGE')
        relative=str(path.relative_to(vendor));inventory[relative]=ref(path)
        if name.startswith('numpy'):
            original=source/relative;original.parent.mkdir(exist_ok=True);original.write_bytes(path.read_bytes());old[relative]=ref(original)
    wheel=tmp_path/'unit.whl';wheel.write_bytes(b'EXPLICIT MOCK WHEEL')
    monkeypatch.setattr(adapter,'WHEEL_SHA256',ref(wheel)['sha256']);monkeypatch.setattr(adapter,'WHEEL_BYTES',wheel.stat().st_size)
    monkeypatch.setattr(adapter,'APPROVED_NUMPY_ROOT',source)
    metadata=dump(tmp_path/'official_metadata.json',{'info':{'name':'highspy','version':'1.15.1'},
        'urls':[{'url':adapter.WHEEL_URL,'digests':{'sha256':adapter.WHEEL_SHA256},'size':adapter.WHEEL_BYTES}]})
    lock=dump(tmp_path/'lock.json',{'kind':'prepared_isolated_highs_numpy_vendor','version':1,
        'vendor_root':str(vendor),'distributions':adapter.DISTRIBUTIONS,'wheel_sha256':adapter.WHEEL_SHA256,
        'wheel_url':adapter.WHEEL_URL,'wheel':ref(wheel),'official_metadata':metadata,
        'package_roots':sorted(adapter.VENDOR_ROOTS),'vendor_inventory':inventory,'numpy_source_inventory':old})
    cid='d'*64
    actual={'Id':cid,'Image':'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043',
        'NanoCpus':2*10**9,'Memory':32*1024**3,'PidsLimit':256,'NetworkMode':'none','ReadOnly':True,
        'Mounts':[{'Source':str(vendor),'Destination':'/vendor','RW':False}]}
    probe=dump(tmp_path/'probe.json',{'passed':True,'optimizer_calls':0,'native_solver_instantiated':False,
        'vendor_lock':lock,'image_id':actual['Image'],'container_id':cid,
        'imported':{'versions':adapter.DISTRIBUTIONS,'paths':{'numpy':'/vendor/numpy/__init__.py','highspy':'/vendor/highspy/__init__.py'}},
        'before':{**actual,'State':{'Status':'created'}},
        'after':{**actual,'State':{'Status':'exited','Running':False,'ExitCode':0,'OOMKilled':False}},'cleanup':{'passed':True}})
    runtime=adapter.build_runtime(lock['path'],probe['path'])
    model_path=tmp_path/'model.json';dump(model_path,matrix())
    output=tmp_path/'native';receipt=runtime.prepare(model_path,output)
    return runtime, output, receipt, lock, probe


def solver_result(runtime, frozen, *, no_candidate=False, model=None, values=None, raw_status=None):
    model=matrix() if model is None else model
    exact=engineering.exact_plan_check(model,[1,0] if values is None else values)
    return {'kind':engineering.SCREEN_KIND,'version':1,'completed':True,'checked_optimal':False,
        'reference_admission':False,'reference_admission_permitted':False,'formal_global_certificate_claimed':False,
        'floating_native_gap_is_not_formal_proof':True,'transformation':engineering.scaled_model(model),
        'raw_status':raw_status or 'HighsModelStatus.kTimeLimit','plan':None if no_candidate else exact['plan'],
        'objective_pence':None if no_candidate else exact['objective_pence'],'exact_integer_check':None if no_candidate else exact,
        'parameters':dict(engineering.PARAMETERS),'threads':2,'time_limit_seconds':800,'incumbent_seed':None,
        'known_objective_cut':None,'exclude_plan':None,'optimizer_calls':1,'retry_count':0,
        'model_sha256':frozen['model_canonical_sha256'],'specification_sha256':model['specification_sha256'],
        'universe_sha256':model['universe_sha256']}


def mock_run(prepared, monkeypatch, fault=None, no_candidate=False, model=None, values=None, raw_status=None):
    runtime,output,*_=prepared;state=services(monkeypatch);frozen=runtime.validate_prepared(output)
    bundle=output/'job_bundle';cid='a'*64;commands=[]
    def actual():
        return {'Id':cid,'Name':'/sf-scaled-highs2-engineering-'+frozen['request']['nonce'],
            'Image':runtime.IMAGE_ID,'NanoCpus':(16 if fault=='cpu' else 2)*10**9,'Memory':32*1024**3,'PidsLimit':256,
            'NetworkMode':'none','Privileged':False,'User':'0','CapDrop':['ALL'],'CapAdd':['DAC_OVERRIDE'],
            'SecurityOpt':['no-new-privileges'],'WorkingDir':'/app','Entrypoint':['/usr/bin/python3'],'Cmd':['/app/run.py'],
            'Mounts':[{'Type':'bind','Source':str(bundle),'Destination':'/app','RW':True}],
            'State':{'Status':'exited' if state.get('attached') else 'created','Running':False,'ExitCode':0,'OOMKilled':False}}
    def command(args, **kwargs):
        commands.append(args)
        if args[:3]==['docker','image','inspect']:return subprocess.CompletedProcess(args,0,runtime.IMAGE_ID+'\n','')
        if args[:2]==['docker','create']:
            assert args[args.index('--cpus')+1]=='2';return subprocess.CompletedProcess(args,0,cid+'\n','')
        if args[:2]==['docker','inspect']:
            return subprocess.CompletedProcess(args,1,'','Error: no such object') if state.get('cleaned') else subprocess.CompletedProcess(args,0,json.dumps(actual()),'')
        if args[:2]==['docker','rm']:
            state['cleaned']=True;return subprocess.CompletedProcess(args,1 if fault=='cleanup' else 0,cid,'')
        if args[:2]==['docker','kill']:state['killed']=True;return subprocess.CompletedProcess(args,0,cid,'')
        raise AssertionError(args)
    def attach(args,stdout,stderr,timeout):
        assert timeout==920 and (output/'started.json').is_file();state['attached']=True
        stdout.write_text('Explicit mock stdout');stderr.write_text('')
        if fault=='timeout':raise subprocess.TimeoutExpired(args,timeout)
        result=solver_result(runtime,frozen,no_candidate=no_candidate,model=model,values=values,raw_status=raw_status)
        if fault=='settings':result['parameters']['threads']=16
        if fault=='seed':result['incumbent_seed']={'P001':1,'P002':0}
        if fault=='audit':result['exact_integer_check']['rows']=[]
        if fault=='transform':result['transformation']['dropped_rows']=[{'unexpected':True}]
        if fault=='proof':result['checked_optimal']=True
        if fault=='ancestry':result['model_sha256']='f'*64
        dump(bundle/'solver_result.json',result)
        dump(bundle/'runtime_result.json',{'completed':True,'backend':'highs','financial_forward_executed':False,
            'model_canonical_sha256':frozen['model_canonical_sha256'],'threads':2,'gap_requested':0,
            'distribution_versions':runtime.DISTRIBUTIONS})
        for name in ('native_model.lp','solver.log'):(bundle/name).write_text('Explicit mock native artifact')
        if fault=='extra':(bundle/'private_gold.json').write_text('{}')
        return subprocess.CompletedProcess(args,0)
    monkeypatch.setattr(runtime,'_command',command);monkeypatch.setattr(runtime,'_attach',attach)
    return state,commands


def test_preparation_only_copies_five_matrix_files_and_exact_vendor(prepared, monkeypatch):
    runtime,output,receipt,*_=prepared
    monkeypatch.setattr(runtime,'_command',lambda *a,**k:pytest.fail('No Docker during preparation'))
    frozen=runtime.validate_prepared(output)
    assert frozen['kind']==adapter.PREPARATION_KIND and frozen['reference_admission'] is False
    assert frozen['solver_calls']==0 and frozen['resources']['cpus']==2
    assert set(frozen['source_code'])==adapter.SOURCE_NAMES
    assert frozen['request']['time_limit_seconds']==800 and frozen['request']['exclude_plan'] is None
    assert not any('finance' in name or 'ledger' in name or 'candidate' in name for name in frozen['source_code'])
    assert not (output/'started.json').exists()


@pytest.mark.parametrize('no_candidate',[False,True])
def test_mocked_limited_engineering_result_never_admits_reference(prepared,monkeypatch,no_candidate):
    runtime,output,*_=prepared;state,commands=mock_run(prepared,monkeypatch,no_candidate=no_candidate)
    terminal=runtime._read(runtime.execute_prepared(output)['path'])
    assert terminal['status']==('engineering_no_exact_feasible_incumbent' if no_candidate else 'engineering_exact_feasible_incumbent')
    assert terminal['reference_admission'] is terminal['hardness_certified'] is terminal['qualified'] is False
    assert terminal['matrix_result_check']['checked_optimal'] is False
    assert state['released'] and state['stopped'] and state['cleaned']
    assert [c for c in commands if c[:2]==['docker','rm']]==[['docker','rm','--force','a'*64]]
    with pytest.raises(ValueError):runtime.execute_prepared(output)


@pytest.mark.parametrize('fault',['cpu','cleanup','timeout','settings','seed','audit','transform','proof','ancestry','extra'])
def test_mocked_failures_preserve_terminal_and_only_owned_cleanup(prepared,monkeypatch,fault):
    runtime,output,*_=prepared;state,commands=mock_run(prepared,monkeypatch,fault=fault)
    with pytest.raises(runtime.OptimizationRuntimeError) as error:runtime.execute_prepared(output)
    assert runtime._read(error.value.receipt['path'])['status']=='execution_failed'
    assert state['cleaned'] and state['released']
    assert len([c for c in commands if c[:2]==['docker','create']])==1


@pytest.mark.parametrize('fault',['800_changed','exclude','old_schema','vendor','lock','probe'])
def test_frozen_input_dependency_and_policy_guards(prepared,fault):
    runtime,output,_,lock,probe=prepared
    if fault=='800_changed':
        with pytest.raises(ValueError):runtime.prepare(output.parent/'model.json',output.parent/'other',time_limit_seconds=801)
        return
    if fault=='exclude':
        with pytest.raises(ValueError):runtime.prepare(output.parent/'model.json',output.parent/'other',exclude_plan={'P001':1,'P002':0})
        return
    if fault=='old_schema':
        model=matrix();model['kind']='linear_capital_portfolio_direct_binary_integer_model';model['version']=1
        with pytest.raises(ValueError):runtime.validate_model(model)
        return
    path=Path(lock['path'] if fault=='lock' else probe['path'] if fault=='probe' else runtime.VENDOR_SITE_PACKAGES/'highspy/unit_fixture.txt')
    path.write_text('changed')
    with pytest.raises((ValueError,json.JSONDecodeError)):runtime.validate_prepared(output)


def test_complete_production_incumbent_audit_retains_all_941_original_rows():
    model=production_matrix();checked=engineering.exact_plan_check(model,[0]*360)
    assert checked['all_integer_rows_checked']==len(checked['rows'])==941
    assert [row['id'] for row in checked['rows']]==[row['id'] for row in model['rows']]


def test_driver_has_only_fixed_p01_prepare_validate_and_explicit_run():
    path=ROOT/'scripts/run_linear_capital_scaled_highs_screen.py';descriptor=importlib.util.spec_from_file_location('_highs_driver_test',path)
    entry=importlib.util.module_from_spec(descriptor);descriptor.loader.exec_module(entry)
    for args in (['prepare','--profile','L360-P02'],['run','--retry'],['resume']):
        with pytest.raises(SystemExit):entry.main(args)
    assert entry.P01_MODEL_SHA256=='4eb747bc7a4f05f6c14f1806aae1a04484da29f2e1d25e5879398355848e4559'
    assert 'solve_highs' in adapter.RUNNER and 'build_model' not in adapter.RUNNER and 'setSolution' not in adapter.RUNNER


def test_fixed_p01_input_reads_terminal_after_structured_finance_guard(tmp_path,monkeypatch):
    path=ROOT/'scripts/run_linear_capital_scaled_highs_screen.py';descriptor=importlib.util.spec_from_file_location('_highs_input_contract',path)
    entry=importlib.util.module_from_spec(descriptor);descriptor.loader.exec_module(entry)
    root=tmp_path/'finance';model=dump(root/'L360-P01/model_B.json',production_matrix())
    spec=dump(root/'L360-P01/spec.json',{'explicit_unit_only':True})
    terminal=dump(root/'L360-P01/terminal.json',{'model_B':model,'specification':spec})
    inventory=dump(root/'inventory.json',{'kind':'completed_scaled_linear_finance_terminal_inventory','version':2,
        'profile_order':entry.PROFILE_ORDER,'profiles':[{'profile_id':pid,'terminal':terminal} for pid in entry.PROFILE_ORDER]})
    monkeypatch.setattr(entry,'FINANCE_ROOT',root);monkeypatch.setattr(entry,'INVENTORY',Path(inventory['path']))
    monkeypatch.setattr(entry,'P01_TERMINAL_SHA256',terminal['sha256']);monkeypatch.setattr(entry,'P01_MODEL_SHA256',model['sha256'])
    monkeypatch.setattr(entry,'P01_SPECIFICATION_SHA256',spec['sha256'])
    calls=[]
    def guard(record):calls.append(record);return {'terminal':record,'models':{'B':model},'model_values':{'B':production_matrix()}}
    monkeypatch.setattr(entry.reference_support,'_checked_finance',guard)
    got=entry.checked_input()
    assert got[0]==inventory and got[1]==terminal and got[2]['model_B']==model
    assert len(got[3]['rows'])==941 and calls==[terminal]


@pytest.fixture
def controller(prepared,monkeypatch):
    runtime,unused,_,lock,probe=prepared
    path=ROOT/'scripts/run_linear_capital_scaled_highs_screen.py';descriptor=importlib.util.spec_from_file_location('_highs_controller_fixture',path)
    entry=importlib.util.module_from_spec(descriptor);descriptor.loader.exec_module(entry)
    fixture=unused.parent/'three_project_fixture'
    tiny_model={'kind':'linear_capital_scaled_direct_binary_integer_model','version':2,
        'project_ids':['P001','P002','P003'],'objective_pence':[11,7,6],
        'rows':[{'id':name,'family':name.split(':')[0],'scenario_id':None,'year':None,'coefficients':coefficients,'limit':limit}
            for name,coefficients,limit in [('exclusivity:site',[1,0,1],1),('prerequisite:dependency',[0,-1,1],0),('resource:budget',[2,1,1],2)]],
        'specification_sha256':'a'*64,'universe_sha256':'b'*64}
    model_ref=dump(fixture/'model.json',tiny_model);parent_ref=dump(fixture/'terminal.json',{'passed':True,'unit_only':True})
    monkeypatch.setattr(entry,'TINY_ROOT',fixture);monkeypatch.setattr(entry,'TINY_MODEL_SHA256',model_ref['sha256'])
    monkeypatch.setattr(entry,'TINY_PARENT_SHA256',parent_ref['sha256'])
    monkeypatch.setattr(entry.highs_runtime,'build_runtime',lambda *a:runtime)
    tiny=unused.parent/'tiny_screen';entry.prepare_tiny(tiny,vendor_lock=lock['path'],dependency_probe=probe['path'])
    ancestry={name:dump(unused.parent/'unit_finance'/f'{name}.json',{'explicit_unit_boundary':True})
        for name in ('specification','raw_preparation','universe_A','universe_B','model_A','complete_financial_comparison',
            'all_predeclared_plan_comparison','complete_matrix_comparison')}
    ancestry['model_B']=ref(unused.parent/'model.json')
    inventory=dump(unused.parent/'unit_inventory.json',{'explicit_unit_boundary':True})
    terminal=dump(unused.parent/'unit_finance_terminal.json',{'explicit_unit_boundary':True})
    monkeypatch.setattr(entry,'checked_input',lambda:(inventory,terminal,ancestry,matrix()))
    p01=unused.parent/'p01_screen'
    entry.prepare(p01,vendor_lock=lock['path'],dependency_probe=probe['path'],tiny_prepared=tiny)
    return entry,runtime,tiny,p01


def test_predeclared_tiny_and_p01_keep_expected_toy_answer_outside_bundle(controller):
    entry,runtime,tiny,p01=controller
    frozen=entry.validate_prepared(p01);tiny_frozen,_,_=entry.checked_tiny_prospective(tiny)
    assert frozen['required_tiny_prospective']==entry.reference(tiny/'prospective.json')
    assert tiny_frozen['expected_plan']=={'P001':0,'P002':1,'P003':1} and tiny_frozen['expected_objective_pence']==13
    for path in (tiny,p01):
        job=runtime._read(path/'native/job_bundle/job.json')
        assert job['time_limit_seconds']==800 and job['exclude_plan'] is None
        assert 'expected_plan' not in job and 'known_objective_cut' not in job
        assert not (path/'native/started.json').exists()


@pytest.mark.parametrize('failed',[False,True])
def test_p01_never_dispatches_before_exact_tiny_pass(controller,monkeypatch,failed):
    entry,runtime,tiny,p01=controller
    monkeypatch.setattr(runtime,'execute_prepared',lambda *a:pytest.fail('P01 dispatched without passing tiny'))
    if failed:dump(tiny/'tiny_failure.json',{'preserved_actual_failure':True})
    with pytest.raises((ValueError,FileNotFoundError)):entry.execute_prepared(p01)
    assert not (p01/'screen_started.json').exists()


def test_controller_dispatch_is_once_only_and_records_exact_tiny_receipt(controller,monkeypatch):
    entry,runtime,tiny,p01=controller;calls=[]
    tiny_receipt=dump(tiny/'tiny_terminal.json',{'explicit_mock_completed_tiny':True})
    monkeypatch.setattr(entry,'checked_tiny_completed',lambda *a:{'explicit_mock_boundary':True})
    def run(output):
        calls.append(output);return dump(output/'terminal.json',{'status':'engineering_exact_feasible_incumbent'})
    monkeypatch.setattr(runtime,'execute_prepared',run)
    result=entry.read(entry.execute_prepared(p01));started=entry.read(p01/'screen_started.json')
    assert result['reference_admission'] is result['hardness_certified'] is result['qualified'] is False
    assert started['required_tiny_terminal']==tiny_receipt and calls==[p01/'native']
    with pytest.raises(ValueError,match='no retry'):entry.execute_prepared(p01)
    assert len(calls)==1


def test_tiny_failure_is_preserved_without_any_automatic_p01_launch(controller,monkeypatch):
    entry,runtime,tiny,p01=controller;calls=[]
    def failure(output):calls.append(output);raise RuntimeError('Explicit native API mock failure')
    monkeypatch.setattr(runtime,'execute_prepared',failure)
    with pytest.raises(RuntimeError):entry.execute_tiny(tiny)
    assert entry.read(tiny/'tiny_failure.json')['retry_authorized'] is False
    with pytest.raises(ValueError,match='failed API smoke'):entry.execute_prepared(p01)
    with pytest.raises(ValueError,match='no retries'):entry.execute_tiny(tiny)
    assert calls==[tiny/'native']


def test_complete_mocked_tiny_api_pass_checks_plan_objective_three_rows_and_owned_cleanup(controller,monkeypatch):
    entry,runtime,tiny,p01=controller;frozen,_,model=entry.checked_tiny_prospective(tiny)
    state,commands=mock_run((runtime,tiny/'native'),monkeypatch,model=model,values=[0,1,1],raw_status='HighsModelStatus.kOptimal')
    terminal=entry.read(entry.execute_tiny(tiny));checked=entry.checked_tiny_completed(tiny)
    assert terminal==checked and checked['passed'] is True and checked['reference_admission'] is False
    assert state['cleaned'] and state['released']
    assert len([args for args in commands if args[:2]==['docker','create']])==1
    assert not (p01/'screen_started.json').exists() and not (p01/'native/started.json').exists()
