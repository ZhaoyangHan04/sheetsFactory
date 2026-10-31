"""New public N360 parsing/bundles and mocked replay; no actual services."""
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys

import openpyxl
import pytest

from sheets_factory.workbook import linear_capital_public_recovery as original
from sheets_factory.workbook import linear_capital_scaled_public_recovery as recovery
from sheets_factory.workbook.linear_capital_scaled import spec,excel,finance,model_b

ROOT=Path(__file__).resolve().parents[1]
descriptor=importlib.util.spec_from_file_location('_scaled_public_tiny_inputs',ROOT/'tests/test_linear_capital_portfolio_ledger.py')
inputs=importlib.util.module_from_spec(descriptor);descriptor.loader.exec_module(inputs)


@pytest.fixture
def public_book(tmp_path):
    raw=inputs.fixture(projects=2,years=4,scenarios=3)
    raw.update(kind=spec.SPEC_KIND,version=2)
    raw['exclusivity_groups']=[{'id':'SITE1','description':'Alternative developments','project_ids':['P001','P002']}]
    raw['prerequisites']=[{'id':'ENABLE1','dependent':'P002','prerequisite':'P001','business_reason':'Enable project'}]
    public=spec.load_spec(raw);path=tmp_path/'public.xlsx';binding=excel.emit_workbook(path,public,plan=None)
    brief=tmp_path/'instruction.md';brief.write_text('Complete the supplied native financial model. Save /app/output.xlsx.\n')
    return public,path,binding,brief


def comparable(public):
    value=deepcopy(public);value.pop('provenance');return value


def edit(path,sheet,cell,value):
    book=openpyxl.load_workbook(path);book[sheet][cell]=value;book.save(path);book.close()


def test_public_parse_new_identity_every_primitive_without_forward(public_book,monkeypatch):
    public,path,_,brief=public_book
    def prohibited(*a,**k):raise AssertionError('No financial or solver execution during parsing')
    monkeypatch.setattr(finance,'build_universe_a',prohibited);monkeypatch.setattr(finance,'build_universe_b',prohibited)
    monkeypatch.setattr(finance,'simulate_b',prohibited);monkeypatch.setattr(model_b,'build_model',prohibited)
    monkeypatch.setattr(model_b,'solve_cp_sat',prohibited)
    actual=recovery.parse_public_workbook(path,instruction_path=brief)
    assert comparable(actual)==comparable(public)
    assert actual['kind']==spec.SPEC_KIND and actual['version']==2
    assert actual['provenance']['ancestor_sha256']==[]
    assert original.SETTING=='linear_capital_portfolio' and recovery.SETTING=='linear_capital_scaled'


def test_old_240_production_is_not_reinterpreted_as_new_toy(public_book,monkeypatch):
    _,path,_,_=public_book
    # Inspect the exact bounded parser branches without emitting a production
    # workbook or generating a new actual raw source.
    tree=recovery.adapted_ast();parse=next(n for n in tree.body if getattr(n,'name',None)=='_parse_book')
    source=ast.unparse(parse)
    assert '_rows(projects, 2, 360)' in source and '_rows(sites, 2, 60)' in source
    assert '_rows(prereqs, 2, 120)' in source and "'production' if n == 360 else 'toy'" in source
    assert recovery.PUBLIC_TABLE_BOUNDS==recovery.TABLE_BOUNDS
    assert recovery.TABLE_BOUNDS['Projects']==(388,22)
    assert recovery.TABLE_BOUNDS['ResourceUse']==(362,362)
    assert recovery.TABLE_BOUNDS['Sites']==(63,7) and recovery.TABLE_BOUNDS['Prerequisites']==(123,5)
    raw=inputs.fixture(projects=2,years=1,scenarios=1);raw.update(kind=spec.SPEC_KIND,version=2)
    raw['project_ids']=[f'P{i:03}' for i in range(1,241)]
    with pytest.raises(ValueError):spec.load_spec(raw)


@pytest.mark.parametrize('value',[False,1.5,'=1',None])
def test_public_primitive_type_cannot_be_synthesized(public_book,value):
    _,path,_,_=public_book;edit(path,'Projects','E2',value)
    with pytest.raises(ValueError):recovery.parse_public_workbook(path)


@pytest.mark.parametrize('attack',['missing_sheet','order','policy','resource_gap','overbound','extra_target'])
def test_native_schema_and_geometry_fail_closed(public_book,tmp_path,attack):
    public,path,_,_=public_book
    book=openpyxl.load_workbook(path)
    if attack=='missing_sheet':del book['Limits']
    if attack=='order':book._sheets[1],book._sheets[2]=book._sheets[2],book._sheets[1]
    if attack=='policy':book['ContractNotes']['A3']='Different policy'
    if attack=='resource_gap':book['ResourceUse']['C1']=None
    if attack=='overbound':book['Projects']['A389']='Extra candidate'
    if attack=='extra_target':book['Portfolio']['XFD100']='Undeclared helper'
    book.save(path);book.close()
    with pytest.raises(ValueError):
        if attack=='extra_target':recovery.write_reconstructed_model(path,tmp_path/'out.xlsx',public,{'P001':0,'P002':0})
        else:recovery.parse_public_workbook(path)


def test_formula_reconstruction_preserves_inputs_and_uses_new_compiler(public_book,tmp_path):
    public,path,binding,_=public_book
    target=binding['financial_bindings'][0];edit(path,target['sheet'],target['cell'],'=999')
    before=recovery.reference(path);destination=tmp_path/'recovered.xlsx'
    result=recovery.write_reconstructed_model(path,destination,recovery.parse_public_workbook(path),{'P001':0,'P002':0})
    assert result['shared_Excel_compiler'] is True and result['common_choices']==2
    assert recovery.reference(path)==before
    after=openpyxl.load_workbook(destination,data_only=False)
    try:assert after[target['sheet']][target['cell']].value==target['formula']
    finally:after.close()


def test_public_program_is_standalone_generic_new_namespace_only():
    source=recovery.public_program_source();compile(source,'public_program.py','exec')
    assert 'from portfolio import spec,finance,model_b,excel' in source
    assert 'sheets_factory' not in source and 'context_proof' not in source
    assert 'goal.xlsx' not in source and 'specification.json' not in source
    assert 'finance.simulate_b' in source and 'ledger.simulate' not in source
    assert 'public_native_linear_capital_scaled_reconstruction' in source


@pytest.fixture
def vendor(tmp_path,monkeypatch):
    root=tmp_path/'generic_vendor';root.mkdir();(root/'generic_package').mkdir()
    (root/'generic_package/__init__.py').write_text('# Exact unit fixture only\n')
    metadata=root/'generic_package-1.0.dist-info';metadata.mkdir()
    (metadata/'METADATA').write_text('Name: generic-package\nVersion: 1.0\n')
    support=recovery.runtime_support
    monkeypatch.setattr(support,'VENDOR_SITE_PACKAGES',root)
    monkeypatch.setattr(support,'VENDOR_ROOTS',{'generic_package','generic_package-1.0.dist-info'})
    monkeypatch.setattr(support,'DISTRIBUTIONS',{'generic_package':'1.0'})
    recovery._RUNTIME_SESSIONS.clear();return root


def test_generic_runtime_copy_bundles_every_frozen_kernel_and_only_public_material(vendor,public_book,tmp_path,monkeypatch):
    _,path,_,brief=public_book
    def prohibited(*a,**k):raise AssertionError('No services or financial forward during preparation')
    monkeypatch.setattr(model_b,'build_model',prohibited);monkeypatch.setattr(model_b,'solve_cp_sat',prohibited)
    monkeypatch.setattr(finance,'simulate_b',prohibited)
    prepared=recovery.prepare_public_runtime(tmp_path/'prepared');frozen=recovery.validate_public_runtime(prepared)
    assert frozen['version']==2 and frozen['normal_quality_opaque_admission_available'] is True
    assert frozen['model_calls']==frozen['solver_calls']==frozen['financial_forwards']==frozen['LO_calls']==0
    kernels=set(recovery._runtime_source_files())
    assert kernels=={'spec.py','finance.py','model_b.py','excel.py','frozen_spec.py','frozen_model_b.py',
        'frozen_excel.py','frozen_candidate_a.py','frozen_ledger.py','frozen_finance_crosscheck.py'}
    bundle=tmp_path/'bundle';initial=recovery.prepare_public_bundle(path,brief.read_text(),prepared,bundle,nonce='f'*32)
    assert not any(name.endswith(('goal.xlsx','specification.json','model.json','bindings.json','view_plan.json')) for name in initial)
    code='import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from public_program import parse_public_workbook;p=parse_public_workbook(Path(sys.argv[1])/"input.xlsx");print(json.dumps({"kind":p["kind"],"version":p["version"],"N":len(p["project_ids"])}))'
    done=subprocess.run([sys.executable,'-I','-B','-c',code,str(bundle)],capture_output=True,text=True,timeout=20)
    assert done.returncode==0,done.stderr
    assert json.loads(done.stdout)=={'kind':spec.SPEC_KIND,'version':2,'N':2}
    assert recovery.inventory(bundle)==initial


@pytest.mark.parametrize('attack',['version','old_kind','extra_private','source_mutation','missing_frozen'])
def test_runtime_inventory_and_code_guards(vendor,tmp_path,attack):
    ref=recovery.prepare_public_runtime(tmp_path/'prepared');frozen=json.loads(Path(ref['path']).read_text())
    directory=Path(frozen['directory'])
    if attack=='version':frozen['version']=1
    if attack=='old_kind':frozen['kind']='prepared_public_linear_capital_recovery_runtime'
    if attack=='extra_private':(directory/'goal.xlsx').write_bytes(b'not authorized')
    if attack=='source_mutation':(vendor/'generic_package/__init__.py').write_text('changed')
    if attack=='missing_frozen':(directory/'portfolio/frozen_excel.py').unlink()
    if attack in {'version','old_kind'}:
        changed=tmp_path/'forged.json';changed.write_text(json.dumps(frozen));ref=recovery.reference(changed)
    with pytest.raises((ValueError,FileNotFoundError)):recovery.validate_public_runtime(ref)


def host_receipt(directory,*,before=True):
    c=recovery.default_offline_configuration()
    return {'Id':'a'*64,'Image':recovery.IMAGE,'NanoCpus':16*10**9,'Memory':c['memory_bytes'],
        'PidsLimit':256,'NetworkMode':'none','Privileged':False,'CapDrop':['ALL'],
        'CapAdd':['CAP_DAC_OVERRIDE'],'SecurityOpt':['no-new-privileges'],'User':'0',
        'MaxConcurrency':'MAX_CONCURRENCY=2','Entrypoint':['/usr/bin/python3'],'Cmd':['-B','/app/run.py'],
        'WorkingDir':'/app','Mounts':[{'Type':'bind','RW':True,'Source':str(directory.resolve()),'Destination':'/app'}],
        'State':{'Status':'created' if before else 'exited','Running':False,'OOMKilled':False,'ExitCode':0}}


@pytest.fixture
def replay_setup(tmp_path,monkeypatch):
    profile={'docker_resources':{'agent':{'cpus':2,'memory_bytes':32*1024**3,'pids_limit':256}}}
    profile_ref={'path':'/not-mounted-profile','sha256':'b'*64,'bytes':1}
    ctx=SimpleNamespace(config={'recovery':{'offline_public_recovery':recovery.default_offline_configuration()}})
    monkeypatch.setattr(recovery,'_settings',lambda unused:(profile,profile_ref,{}, {'inventory':{}}))
    directory=tmp_path/'public';directory.mkdir();(directory/'input.xlsx').write_bytes(b'public only')
    attempt=tmp_path/'attempt';attempt.mkdir()
    result={'replay':{'nonce':'f'*32,'initial_files':recovery.inventory(directory)}}
    return ctx,directory,attempt,result


@pytest.mark.parametrize('failure',[None,'create','resources','timeout'])
def test_only_owned_public_mount_replay_cleanup_and_normal_exit(replay_setup,monkeypatch,failure):
    ctx,directory,attempt,result=replay_setup;commands=[];inspections=0
    def fake(command,**kwargs):
        nonlocal inspections
        commands.append(command)
        if command[:2]==['docker','create']:
            assert command[command.index('--cpus')+1]=='16'
            assert command[command.index('--network')+1]=='none'
            assert command[command.index('--volume')+1]==str(directory.resolve())+':/app:rw'
            assert command[command.index('--name')+1].startswith('sheetsfactory-linear-scaled-public-')
            return SimpleNamespace(returncode=1 if failure=='create' else 0,stdout='unowned-name' if failure=='create' else 'a'*64+'\n',stderr='')
        if command[:2]==['docker','inspect']:
            inspections+=1;actual=host_receipt(directory,before=inspections==1)
            if failure=='resources':actual['Memory']=2*1024**3
            return SimpleNamespace(returncode=0,stdout=json.dumps(actual),stderr='')
        if command[:2]==['docker','start']:
            if failure=='timeout':raise subprocess.TimeoutExpired(command,7200)
            for name in recovery.GENERATED_FILES:(directory/name).write_bytes(b'generated')
            return SimpleNamespace(returncode=0)
        if command[:3]==['docker','rm','--force']:return SimpleNamespace(returncode=0,stdout='',stderr='')
        raise AssertionError(command)
    monkeypatch.setattr(recovery.subprocess,'run',fake)
    if failure:
        with pytest.raises((ValueError,subprocess.TimeoutExpired)):recovery._execute_replay(ctx,directory,attempt,result)
    else:
        recovery._execute_replay(ctx,directory,attempt,result)
        assert result['replay']['completed'] and result['replay']['actual_resources_verified']
        assert result['replay']['model_resources_claimed_verified'] is False
        assert result['replay']['operational_replay_budget_is_model_tool_budget'] is False
    removes=[c for c in commands if c[:3]==['docker','rm','--force']]
    assert removes==([] if failure=='create' else [['docker','rm','--force','a'*64]])


def test_strict_two_LO_full_D_and_typed_witness_code_is_retained():
    before=ast.parse(recovery.UPSTREAM.read_bytes());after=recovery.adapted_ast()
    old={n.name:n for n in before.body if isinstance(n,ast.FunctionDef)}
    new={n.name:n for n in after.body if isinstance(n,ast.FunctionDef)}
    for name in ('_execute_replay','_host_valid','_normal_container_state','default_offline_configuration',
                 'validate_offline_configuration','_artifacts'):
        assert ast.dump(old[name])==ast.dump(new[name])
    validation=ast.unparse(new['_execution_valid'])
    assert 'len(calls) == 2' in validation and 'entire_value_union_checked' in validation
    assert "stable.get('money_quantization_applied') is False" in validation
    witness=ast.unparse(new['valid_linear_capital_scaled_recovery_witness'])
    assert "comparison.get('reward') == 1" in witness and 'attempt.sha256' in witness
    assert '_linear_admission' not in validation and '_admission_source(ctx)' in validation


def test_unknown_or_old_opaque_admission_is_rejected_without_old_fallback():
    ctx=SimpleNamespace(config={},data={'_linear_admission':SimpleNamespace(source=object())})
    assert recovery.NORMAL_QUALITY_INTEGRATION_AVAILABLE is True
    with pytest.raises(ValueError,match='explicit family route'):recovery._source_binding(ctx)
    with pytest.raises(ValueError,match='explicit family route'):recovery._admission_source(ctx)
    ctx.data={}
    with pytest.raises(ValueError,match='explicit family route'):recovery._admission_source(ctx)
    node=object.__new__(recovery.LinearCapitalScaledRecoveryNode)
    with pytest.raises(recovery.ScaledPublicAdmissionUnavailable,match='Explicit N360'):node.execute(ctx)
    assert recovery.valid_linear_capital_scaled_recovery_witness(ctx,{'verified':True}) is False


def test_frozen_template_drift_stops_public_codegen(monkeypatch):
    monkeypatch.setattr(recovery,'UPSTREAM_SHA256','0'*64)
    with pytest.raises(ValueError,match='template changed'):recovery.adapted_ast()
    with pytest.raises(ValueError,match='template changed'):recovery.public_program_source()


def test_warm_runtime_rechecks_every_frozen_kernel(vendor,tmp_path,monkeypatch):
    ref=recovery.prepare_public_runtime(tmp_path/'prepared');recovery.validate_public_runtime(ref)
    monkeypatch.setattr(spec,'UPSTREAM_SHA256','0'*64)
    with pytest.raises(ValueError,match='specification source differs'):recovery.validate_public_runtime(ref)


@pytest.mark.parametrize('role',['source','agent','verifier'])
def test_source_LO_model_and_verifier_profiles_stay_two_CPU(monkeypatch,role):
    profile={'docker_resources':{name:{'cpus':2,'memory_bytes':32*1024**3,'pids_limit':256}
        for name in ('source','agent','verifier')}}
    monkeypatch.setattr(recovery,'_frozen_settings',lambda unused:(profile,{}, {}, {}))
    assert recovery._settings(object())[0]==profile
    profile['docker_resources'][role]['cpus']=16
    with pytest.raises(ValueError,match='same 2CPU/32GiB'):recovery._settings(object())


@pytest.fixture
def cold_execution(public_book,tmp_path,monkeypatch):
    """Explicit mocked admission/LO evidence, exercising actual cold validators."""
    from sheets_factory.workbook.heterogeneous_contracts.validate import compare_typed_caches
    _,input_path,_,brief=public_book
    revision=tmp_path/'revision';revision.mkdir();attempt=revision/'private/recovery_attempts/attempt_000000';attempt.mkdir(parents=True)
    nonce='f'*32;directory=revision/('linear-scaled-recovery-replay-'+nonce);directory.mkdir()
    import shutil
    shutil.copyfile(input_path,directory/'input.xlsx')
    (directory/'instruction.md').write_text(brief.read_text());(directory/'public_nonce.txt').write_text(nonce+'\n')
    (directory/'run.py').write_text(recovery._RUNNER);offline=recovery.default_offline_configuration()
    recovery._write(directory/'offline_recovery.json',offline)
    initial=recovery.inventory(directory)
    recovery._write(directory/'public_inventory.json',{n:{k:r[k] for k in ('sha256','bytes')} for n,r in initial.items()})
    initial=recovery.inventory(directory)
    profile={'docker_resources':{role:{'cpus':2,'memory_bytes':32*1024**3,'pids_limit':256}
        for role in ('source','agent','verifier')}}
    profile_ref={'path':'/explicit-mocked-not-mounted-profile','sha256':'b'*64,'bytes':1}
    ctx=SimpleNamespace(revision_dir=revision,config={'recovery':{'offline_public_recovery':offline}},
        data={'input':str(input_path),'instruction':brief.read_text()})
    monkeypatch.setattr(recovery,'_settings',lambda unused:(profile,profile_ref,{}, {'inventory':{}}))
    monkeypatch.setattr(recovery,'_source_binding',lambda unused:{'explicit_mock_admission':True})
    replay={'directory':str(directory),'nonce':nonce,'initial_files':initial,'container_id':'a'*64,
        'completed':True,'actual_resources_verified':True,'public_information_unchanged':True,
        'returncode':0,'runtime_profile':profile_ref,'command':recovery._command(ctx,directory,nonce),
        'cleanup':{'owned_full_id':'a'*64,'returncode':0},'offline_recovery_resources':offline,
        'model_runtime_profile':profile_ref,'model_resources_claimed_verified':False}
    for name,before in [('host_before',True),('host_after',False)]:
        replay[name]=recovery._write(attempt/(name+'.json'),host_receipt(directory,before=before))
    parsed=recovery.parse_public_workbook(input_path)
    report={'kind':'public_native_linear_capital_scaled_reconstruction','version':2,'passed':True,
        'public_financial_specification_sha256':spec.canonical_sha256(parsed),
        'project_count':2,'scenario_count':3,'year_count':4,'checked_optimal':True,
        'all_standalone_feasible':True,'shared_Decimal_B':True,'shared_Excel_compiler':True,
        'third_independent_ledger':False,'second_independent_global_proof':False,'objective_pence':0,
        'offline_solver':{'threads':16,'time_limit_seconds':3600},'offline_recovery_is_model_attempt':False}
    recovery._write(directory/'public_recovery_report.json',report)
    recovery._write(directory/'native_solver.json',{'status':'OPTIMAL','checked_optimal':True,
        'exact_plan_check':{'passed':True},'objective_pence':0,'threads':16,'time_limit_seconds':3600})
    for name in ('native_model.pbtxt','native_model.pbtxt.parameters.pbtxt','solver.log'):(directory/name).write_text('Explicit mocked native evidence\n')
    for path in (directory/'recovered.xlsx',attempt/'calculated_pass1.xlsx',attempt/'recovered.xlsx'):
        book=openpyxl.Workbook();book.active['A1']=1;book.save(path);book.close()
    evidence={'terminal':{'explicit_mock_LO_resource_evidence':True}};validated=[]
    class Helper:
        def validate_actual_call(self,call,terminal,preparation):
            assert terminal==evidence['terminal'] and preparation['runtime_profile']==profile_ref
            validated.append(call['index']);return evidence
    monkeypatch.setattr(recovery,'_admission_source',lambda unused:SimpleNamespace(helper=Helper()))
    calls=[];source=directory/'recovered.xlsx'
    for index,destination in enumerate((attempt/'calculated_pass1.xlsx',attempt/'recovered.xlsx'),1):
        calls.append({'index':index,'completed':True,'input':recovery.reference(source),
            'output':recovery.reference(destination),'actual_resource_evidence':evidence});source=destination
    recovery._write(attempt/'stability.json',compare_typed_caches(attempt/'calculated_pass1.xlsx',attempt/'recovered.xlsx'))
    result={'attempt_record_path':str(attempt/'attempt.json'),'replay':replay,'recalculations':calls}
    def seal():
        replay.pop('terminal',None);replay['final_files']=recovery.inventory(directory)
        terminal=attempt/'replay_terminal.json'
        if terminal.exists():terminal.unlink()
        replay['terminal']=recovery._write(terminal,deepcopy(replay))
    seal();return ctx,result,seal,validated


def test_cold_witness_execution_requires_both_actual_call_receipts_and_full_typed_union(cold_execution):
    ctx,result,_,validated=cold_execution
    assert recovery._execution_valid(ctx,result) is True
    assert validated==[1,2]


@pytest.mark.parametrize('attack',['one_LO','wrong_chain','old_report','limited','typed_instability','quantized','extra_private'])
def test_cold_witness_cannot_skip_calls_scopes_or_typed_checks(cold_execution,attack):
    ctx,result,seal,_=cold_execution;directory=Path(result['replay']['directory']);attempt=Path(result['attempt_record_path']).parent
    if attack=='one_LO':result['recalculations'].pop()
    if attack=='wrong_chain':result['recalculations'][1]['input']=recovery.reference(directory/'input.xlsx')
    if attack in {'old_report','limited'}:
        path=directory/('public_recovery_report.json' if attack=='old_report' else 'native_solver.json')
        value=json.loads(path.read_text())
        if attack=='old_report':value['version']=1
        else:value['status']='FEASIBLE';value['checked_optimal']=False
        path.write_text(json.dumps(value))
    if attack in {'typed_instability','quantized'}:
        path=attempt/'stability.json';value=json.loads(path.read_text())
        value['passed' if attack=='typed_instability' else 'money_quantization_applied']=False if attack=='typed_instability' else True
        path.write_text(json.dumps(value))
    if attack=='extra_private':(directory/'goal.xlsx').write_bytes(b'private material is forbidden')
    seal()
    with pytest.raises(ValueError):recovery._execution_valid(ctx,result)
