"""Public-only tiny parser/compiler tests; optimizer services are stubbed."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import openpyxl
import pytest

from sheets_factory.workbook import linear_capital_public_recovery as recovery
from sheets_factory.workbook.linear_capital_portfolio import excel, ledger, model_b

ROOT=Path(__file__).resolve().parents[1]
loader=importlib.util.spec_from_file_location('_linear_public_recovery_hand_inputs',ROOT/'tests/test_linear_capital_portfolio_ledger.py')
inputs=importlib.util.module_from_spec(loader);loader.loader.exec_module(inputs)


@pytest.fixture
def public_book(tmp_path):
    public=inputs.fixture(projects=2,years=4,scenarios=3)
    public['exclusivity_groups']=[{'id':'SITE1','description':'Choose an alternative site','project_ids':['P001','P002']}]
    public['prerequisites']=[{'id':'ENABLE1','dependent':'P002','prerequisite':'P001','business_reason':'Enable the site'}]
    path=tmp_path/'public.xlsx';binding=excel.emit_workbook(path,public,plan=None)
    brief=tmp_path/'instruction.md';brief.write_text('Complete the provided financial model and common portfolio. Save /app/output.xlsx.\n')
    return public,path,binding,brief


def edit(path,sheet,cell,value):
    book=openpyxl.load_workbook(path);book[sheet][cell]=value;book.save(path);book.close()


def comparable(public):
    result=deepcopy(public);result.pop('provenance');return result


def test_roundtrip_every_public_financial_primitive_without_any_financial_forward(public_book,monkeypatch):
    public,path,_,brief=public_book
    def prohibited(*a,**k):raise AssertionError('No financial/solver call during parsing')
    monkeypatch.setattr(ledger,'simulate',prohibited);monkeypatch.setattr(ledger,'simulate_universe',prohibited)
    monkeypatch.setattr(model_b,'build_model',prohibited);monkeypatch.setattr(model_b,'solve_cp_sat',prohibited)
    actual=recovery.parse_public_workbook(path,instruction_path=brief)
    assert comparable(actual)==comparable(public)
    assert actual['provenance']['ancestor_sha256']==[]


def test_every_financial_formula_or_value_is_ignored_as_a_primitive(public_book):
    public,path,binding,_=public_book
    book=openpyxl.load_workbook(path)
    for row in binding['financial_bindings']:book[row['sheet']][row['cell']]='=999999999'
    book.save(path);book.close()
    assert comparable(recovery.parse_public_workbook(path))==comparable(public)


@pytest.mark.parametrize('name',recovery.INPUT_SHEETS)
def test_missing_provided_table_fails_closed(public_book,name):
    _,path,_,_=public_book;book=openpyxl.load_workbook(path);del book[name];book.save(path);book.close()
    with pytest.raises(ValueError):recovery.parse_public_workbook(path)


@pytest.mark.parametrize('value',[True,1.5,'=1+1',None])
def test_provided_money_cannot_be_boolean_float_formula_or_missing(public_book,value):
    _,path,_,_=public_book;edit(path,'Projects','E2',value)
    with pytest.raises(ValueError):recovery.parse_public_workbook(path)


def test_public_contract_rules_are_mandatory(public_book):
    _,path,_,_=public_book;edit(path,'ContractNotes','A3','Use another unstated policy')
    with pytest.raises(ValueError,match='financial policies'):recovery.parse_public_workbook(path)


def test_duplicate_scenario_or_incomplete_resource_cartesian_scope_reject(public_book):
    _,path,_,_=public_book;edit(path,'Scenarios','C3','revenue factors bp')
    with pytest.raises(ValueError,match='duplicated'):recovery.parse_public_workbook(path)


def test_missing_resource_year_is_not_silently_filled(public_book):
    _,path,_,_=public_book;edit(path,'ResourceUse','C1',None)
    with pytest.raises(ValueError):recovery.parse_public_workbook(path)


def test_changed_order_or_unbounded_input_table_reject(public_book):
    _,path,_,_=public_book;book=openpyxl.load_workbook(path);book._sheets[1],book._sheets[2]=book._sheets[2],book._sheets[1];book.save(path);book.close()
    with pytest.raises(ValueError,match='order'):recovery.parse_public_workbook(path)


@pytest.mark.parametrize('text',['','x'*(128*1024+1)])
def test_current_brief_is_required_and_bounded(public_book,text):
    _,path,_,brief=public_book;brief.write_text(text)
    with pytest.raises(ValueError,match='brief'):recovery.parse_public_workbook(path,instruction_path=brief)


def test_masked_or_wrong_formulas_rebuild_with_shared_compiler_and_preserve_provided_cells(public_book,tmp_path,monkeypatch):
    public,path,binding,_=public_book
    book=openpyxl.load_workbook(path)
    targets={(r['sheet'],r['cell']) for key in ('financial_bindings','arithmetic_bindings') for r in binding[key]}
    for s,c in targets:book[s][c]=None
    book.save(path);book.close()
    monkeypatch.setattr(model_b,'solve_cp_sat',lambda *a,**k:(_ for _ in ()).throw(AssertionError('No solve')))
    destination=tmp_path/'recovered.xlsx';plan={'P001':0,'P002':0}
    report=recovery.write_reconstructed_model(path,destination,recovery.parse_public_workbook(path),plan)
    assert report['physical_formulas']==binding['formula_count']
    assert report['shared_Excel_compiler'] and not report['independent_formula_implementation']
    output=openpyxl.load_workbook(destination,data_only=False)
    assert output['Portfolio']['B6'].value==output['Portfolio']['B7'].value==0
    assert sum(c.data_type=='f' for s in output for row in s for c in row)==binding['formula_count']
    output.close()


def test_rebuild_refuses_modified_provided_cells_or_extra_public_helpers(public_book,tmp_path):
    public,path,_,_=public_book;edit(path,'Projects','E2',999)
    with pytest.raises(ValueError,match='provided'):recovery.write_reconstructed_model(path,tmp_path/'out.xlsx',public,{'P001':0,'P002':0})


def test_rebuild_refuses_new_out_of_scope_data(public_book,tmp_path):
    public,path,_,_=public_book;edit(path,'Portfolio','XFD100','leaked helper')
    with pytest.raises(ValueError,match='outside'):recovery.write_reconstructed_model(path,tmp_path/'out.xlsx',public,{'P001':0,'P002':0})


@pytest.mark.parametrize('status',['FEASIBLE','UNKNOWN','INFEASIBLE'])
def test_public_recovery_never_calls_limit_or_feasible_an_optimum(public_book,tmp_path,monkeypatch,status):
    _,path,_,brief=public_book
    monkeypatch.setattr(recovery,'solve_public_model',lambda *a,**k:{'status':status,'checked_optimal':False})
    with pytest.raises(ValueError,match='checked optimum'):
        recovery.recover_public(path,tmp_path/'out.xlsx',tmp_path/'report.json',instruction_path=brief,time_limit_seconds=1)
    assert not (tmp_path/'out.xlsx').exists()


def test_explicit_recovery_stubbed_solver_exact_rows_and_shared_finance_disclosure(public_book,tmp_path,monkeypatch):
    _,path,_,brief=public_book
    def solved(matrix,**kwargs):
        assert kwargs['time_limit_seconds']==1 and kwargs['threads']==16
        assert kwargs['log_path'].name=='solver.log' and kwargs['model_path'].name=='native_model.pbtxt'
        plan={pid:0 for pid in matrix['project_ids']};check=model_b.check_plan(matrix,plan)
        return {'status':'OPTIMAL','checked_optimal':True,'plan':plan,'objective_pence':0,'exact_plan_check':check}
    monkeypatch.setattr(recovery,'solve_public_model',solved)
    report=recovery.recover_public(path,tmp_path/'out.xlsx',tmp_path/'report.json',instruction_path=brief,time_limit_seconds=1)
    assert report['shared_Decimal_B'] and report['shared_Excel_compiler']
    assert not report['third_independent_ledger'] and not report['second_independent_global_proof']
    assert json.loads((tmp_path/'report.json').read_text())==report


def test_extracted_public_program_has_no_factory_or_private_provider_imports():
    source=recovery.public_program_source();compile(source,'public_program.py','exec')
    assert 'from portfolio import spec,ledger,model_b,excel' in source
    assert 'SourceAdmission' not in source and 'validate_source' not in source and 'source_manifest' not in source
    assert 'reference.xlsx' not in source and 'bindings.json' not in source


def test_complete_twenty_year_calendar_and_project_header_order_are_public(tmp_path):
    public=inputs.fixture(projects=1,years=20,scenarios=3)
    public['projects']=[dict(reversed(list(public['projects'][0].items())))]
    path=tmp_path/'calendar.xlsx';excel.emit_workbook(path,public,plan=None)
    assert comparable(recovery.parse_public_workbook(path))==comparable(public)


def test_offline_budget_is_explicit_and_distinct_from_model_resources():
    value=recovery.default_offline_configuration()
    assert value['cpus']==value['solver_threads']==16
    assert value['solver_seconds']==3600 and value['replay_timeout_seconds']==7200
    assert recovery.validate_offline_configuration(value)==value
    for key,wrong in [('cpus',True),('solver_threads',17),('solver_seconds',0),('image_id','latest')]:
        bad={**value,key:wrong}
        with pytest.raises(ValueError):recovery.validate_offline_configuration(bad)


def test_solver_adapter_changes_only_worker_guard_and_never_mutates_original(monkeypatch,tmp_path):
    original=Path(model_b.__file__).read_bytes()
    # Passing the resource guard must reach the lazy solver import. No optimizer
    # is imported or run in this test.
    def stopped():raise RuntimeError('Stopped before solver import')
    monkeypatch.setattr(model_b,'_solver',stopped)
    public=inputs.fixture(projects=1,years=1,scenarios=1)
    matrix=model_b.build_model(public)
    with pytest.raises(RuntimeError,match='Stopped before'):
        recovery.solve_public_model(matrix,time_limit_seconds=1,threads=16,log_path=None,model_path=None)
    with pytest.raises(ValueError,match='sixteen'):
        recovery.solve_public_model(matrix,time_limit_seconds=1,threads=17,log_path=None,model_path=None)
    assert Path(model_b.__file__).read_bytes()==original


@pytest.fixture
def tiny_runtime(tmp_path,monkeypatch):
    from sheets_factory.workbook.linear_capital_portfolio import optimization_runtime as support
    source=tmp_path/'approved';source.mkdir()
    (source/'generic_package').mkdir();(source/'generic_package/__init__.py').write_text('# approved generic package\n')
    metadata=source/'generic_package-1.0.dist-info';metadata.mkdir()
    (metadata/'METADATA').write_text('Name: generic-package\nVersion: 1.0\n')
    monkeypatch.setattr(support,'VENDOR_SITE_PACKAGES',source)
    monkeypatch.setattr(support,'VENDOR_ROOTS',{'generic_package','generic_package-1.0.dist-info'})
    monkeypatch.setattr(support,'DISTRIBUTIONS',{'generic_package':'1.0'})
    recovery._RUNTIME_SESSIONS.clear()
    return source


def test_preparation_is_only_generic_code_copy_and_isolated_public_import(tiny_runtime,public_book,tmp_path,monkeypatch):
    import subprocess,sys
    public,path,_,brief=public_book
    def prohibited(*a,**k):raise AssertionError('No optimization or finance in runtime preparation')
    monkeypatch.setattr(model_b,'solve_cp_sat',prohibited);monkeypatch.setattr(model_b,'build_model',prohibited)
    prepared=recovery.prepare_public_runtime(tmp_path/'prepared')
    record=recovery.validate_public_runtime(prepared)
    assert record['solver_calls']==record['model_calls']==record['LO_calls']==record['financial_forwards']==0
    bundle=tmp_path/'public';nonce='1'*32
    initial=recovery.prepare_public_bundle(path,brief.read_text(),prepared,bundle,nonce=nonce)
    assert set(initial)==set(record['inventory'])|{'input.xlsx','instruction.md','public_nonce.txt',
        'offline_recovery.json','run.py','public_inventory.json'}
    assert not any(name.endswith(('bindings.json','specification.json','goal.xlsx','plan.json')) for name in initial)
    # A separate isolated interpreter imports the exact copied public package.
    # It performs parsing only; no financial or solver helper is invoked.
    command=[sys.executable,'-I','-B','-c',
        'import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);'
        'from public_program import parse_public_workbook;'
        'p=parse_public_workbook(Path(sys.argv[1])/"input.xlsx",instruction_path=Path(sys.argv[1])/"instruction.md");'
        'print(json.dumps({"projects":len(p["project_ids"]),"years":len(p["years"])}))',str(bundle)]
    done=subprocess.run(command,cwd=tmp_path,capture_output=True,text=True,timeout=20)
    assert done.returncode==0,done.stderr
    assert json.loads(done.stdout)=={'projects':2,'years':4}
    assert recovery.inventory(bundle)==initial


@pytest.mark.parametrize('attack',['missing_root','wrong_source','wrong_version'])
def test_runtime_validation_rejects_forged_partial_or_wrong_vendor(tiny_runtime,tmp_path,attack):
    prepared=recovery.prepare_public_runtime(tmp_path/'prepared')
    value=json.loads(Path(prepared['path']).read_text());directory=Path(value['directory'])
    if attack=='missing_root':
        for name in list(value['vendor_sources']):
            if name.startswith('generic_package/'):
                (directory/'vendor'/name).unlink();value['vendor_sources'].pop(name)
    elif attack=='wrong_source':
        name=next(iter(value['vendor_sources']));copy=tmp_path/'alternate';copy.write_bytes(Path(value['vendor_sources'][name]['path']).read_bytes())
        value['vendor_sources'][name]=recovery.reference(copy)
    else:
        name='generic_package-1.0.dist-info/METADATA'
        (tiny_runtime/name).write_text('Name: generic-package\nVersion: 9.0\n')
        (directory/'vendor'/name).write_bytes((tiny_runtime/name).read_bytes())
        value['vendor_sources'][name]=recovery.reference(tiny_runtime/name)
    value['inventory']=recovery.inventory(directory)
    changed=recovery._write(tmp_path/'forged.json',value)
    with pytest.raises(ValueError):recovery.validate_public_runtime(changed)


def test_opaque_runtime_guard_rechecks_mutated_source_bytes(tiny_runtime,tmp_path):
    prepared=recovery.prepare_public_runtime(tmp_path/'prepared');recovery.validate_public_runtime(prepared)
    (tiny_runtime/'generic_package/__init__.py').write_text('changed approved bytes\n')
    with pytest.raises(ValueError,match='changed'):recovery.validate_public_runtime(prepared)


def host_receipt(directory,*,before=True,owned='a'*64):
    c=recovery.default_offline_configuration()
    return {'Id':owned,'Image':recovery.IMAGE,'NanoCpus':c['cpus']*10**9,'Memory':c['memory_bytes'],
        'PidsLimit':c['pids_limit'],'NetworkMode':'none','Privileged':False,'CapDrop':['ALL'],
        'CapAdd':['CAP_DAC_OVERRIDE'],'SecurityOpt':['no-new-privileges'],'User':'0',
        'MaxConcurrency':'MAX_CONCURRENCY=2','Entrypoint':['/usr/bin/python3'],'Cmd':['-B','/app/run.py'],
        'WorkingDir':'/app','Mounts':[{'Type':'bind','RW':True,'Source':str(directory.resolve()),'Destination':'/app'}],
        'State':{'Status':'created' if before else 'exited','Running':False,'OOMKilled':False,'ExitCode':0}}


@pytest.fixture
def replay_setup(tmp_path,monkeypatch):
    from types import SimpleNamespace
    profile={'docker_resources':{'agent':{'cpus':2,'memory_bytes':32*1024**3,'pids_limit':256}}}
    profile_ref={'path':'/no-private-runtime-profile','sha256':'b'*64,'bytes':1}
    ctx=SimpleNamespace(config={'recovery':{'offline_public_recovery':recovery.default_offline_configuration()}})
    monkeypatch.setattr(recovery,'_settings',lambda unused:(profile,profile_ref,{}, {'inventory':{}}))
    directory=tmp_path/'public';directory.mkdir();(directory/'input.xlsx').write_bytes(b'public-only')
    attempt=tmp_path/'attempt';attempt.mkdir()
    result={'replay':{'nonce':'f'*32,'initial_files':recovery.inventory(directory)}}
    return ctx,directory,attempt,result


@pytest.mark.parametrize('failure',['create','resources','timeout'])
def test_only_proven_owned_container_is_cleaned_on_failure(replay_setup,monkeypatch,failure):
    import subprocess
    from types import SimpleNamespace
    ctx,directory,attempt,result=replay_setup;commands=[]
    def fake(command,**kwargs):
        commands.append(command)
        if command[:2]==['docker','create']:
            return SimpleNamespace(returncode=1 if failure=='create' else 0,stdout='name already exists' if failure=='create' else 'a'*64+'\n',stderr='')
        if command[:2]==['docker','inspect']:
            actual=host_receipt(directory)
            if failure=='resources':actual['Memory']=2*1024**3
            return SimpleNamespace(returncode=0,stdout=json.dumps(actual),stderr='')
        if command[:2]==['docker','start']:raise subprocess.TimeoutExpired(command,7200)
        if command[:3]==['docker','rm','--force']:return SimpleNamespace(returncode=0,stdout='',stderr='')
        raise AssertionError(command)
    monkeypatch.setattr(recovery.subprocess,'run',fake)
    with pytest.raises((ValueError,subprocess.TimeoutExpired)):recovery._execute_replay(ctx,directory,attempt,result)
    assert json.loads((attempt/'replay_terminal.json').read_text())['completed'] is False
    removes=[c for c in commands if c[:3]==['docker','rm','--force']]
    assert removes==([] if failure=='create' else [['docker','rm','--force','a'*64]])
    if failure=='create':assert not any(c[:2]==['docker','start'] for c in commands)


def test_actual_replay_records_distinct_offline_resources_and_normal_owned_exit(replay_setup,monkeypatch):
    from types import SimpleNamespace
    ctx,directory,attempt,result=replay_setup;inspections=0
    def fake(command,**kwargs):
        nonlocal inspections
        if command[:2]==['docker','create']:
            assert command[command.index('--cpus')+1]=='16'
            assert 'MAX_CONCURRENCY=2' in command and 'PYTHONDONTWRITEBYTECODE=1' in command
            return SimpleNamespace(returncode=0,stdout='a'*64+'\n',stderr='')
        if command[:2]==['docker','inspect']:
            inspections+=1;return SimpleNamespace(returncode=0,stdout=json.dumps(host_receipt(directory,before=inspections==1)),stderr='')
        if command[:2]==['docker','start']:
            for name in recovery.GENERATED_FILES:(directory/name).write_bytes(b'generated')
            return SimpleNamespace(returncode=0)
        if command[:3]==['docker','rm','--force']:return SimpleNamespace(returncode=0,stdout='',stderr='')
        raise AssertionError(command)
    monkeypatch.setattr(recovery.subprocess,'run',fake)
    recovery._execute_replay(ctx,directory,attempt,result)
    replay=result['replay']
    assert replay['completed'] and replay['actual_resources_verified']
    assert replay['offline_recovery_resources']['cpus']==16
    assert replay['model_resources_claimed_verified'] is False
    assert replay['operational_replay_budget_is_model_tool_budget'] is False
    assert replay['cleanup']=={'owned_full_id':'a'*64,'returncode':0}


@pytest.fixture
def cold_execution(public_book,tmp_path,monkeypatch):
    from types import SimpleNamespace
    from sheets_factory.workbook.heterogeneous_contracts.validate import compare_typed_caches
    public,input_path,_,brief=public_book
    revision=tmp_path/'revision';revision.mkdir();attempt=revision/'private/recovery_attempts/attempt_000000';attempt.mkdir(parents=True)
    nonce='f'*32;directory=revision/('linear-recovery-replay-'+nonce);directory.mkdir()
    import shutil
    shutil.copyfile(input_path,directory/'input.xlsx')
    (directory/'instruction.md').write_text(brief.read_text());(directory/'public_nonce.txt').write_text(nonce+'\n')
    (directory/'run.py').write_text(recovery._RUNNER)
    offline=recovery.default_offline_configuration();recovery._write(directory/'offline_recovery.json',offline)
    initial=recovery.inventory(directory)
    recovery._write(directory/'public_inventory.json',{name:{k:r[k] for k in ('sha256','bytes')} for name,r in initial.items()})
    initial=recovery.inventory(directory)
    profile={'docker_resources':{'agent':{'cpus':2,'memory_bytes':32*1024**3,'pids_limit':256}}}
    profile_ref={'path':'/not-mounted-profile','sha256':'b'*64,'bytes':1}
    ctx=SimpleNamespace(revision_dir=revision,config={'recovery':{'offline_public_recovery':offline}},
        data={'input':str(input_path),'instruction':brief.read_text()})
    monkeypatch.setattr(recovery,'_settings',lambda unused:(profile,profile_ref,{}, {'inventory':{}}))
    monkeypatch.setattr(recovery,'_source_binding',lambda unused:{})
    replay={'directory':str(directory),'nonce':nonce,'initial_files':initial,'container_id':'a'*64,
        'completed':True,'actual_resources_verified':True,'public_information_unchanged':True,
        'returncode':0,'runtime_profile':profile_ref,'command':recovery._command(ctx,directory,nonce),
        'cleanup':{'owned_full_id':'a'*64,'returncode':0},'offline_recovery_resources':offline,
        'model_runtime_profile':profile_ref,'model_resources_claimed_verified':False}
    for name,before in [('host_before',True),('host_after',False)]:
        replay[name]=recovery._write(attempt/(name+'.json'),host_receipt(directory,before=before))
    report={'kind':'public_native_linear_capital_reconstruction','passed':True,
        'public_financial_specification_sha256':recovery.spec.canonical_sha256(recovery.parse_public_workbook(input_path)),
        'project_count':len(public['project_ids']),'scenario_count':len(public['scenario_ids']),'year_count':len(public['years']),
        'checked_optimal':True,'all_standalone_feasible':True,'shared_Decimal_B':True,'shared_Excel_compiler':True,
        'third_independent_ledger':False,'second_independent_global_proof':False,
        'objective_pence':0,'offline_solver':{'threads':16,'time_limit_seconds':3600},'offline_recovery_is_model_attempt':False}
    recovery._write(directory/'public_recovery_report.json',report)
    recovery._write(directory/'native_solver.json',{'status':'OPTIMAL','checked_optimal':True,'exact_plan_check':{'passed':True},
        'objective_pence':0,'threads':16,'time_limit_seconds':3600})
    for name in ('native_model.pbtxt','native_model.pbtxt.parameters.pbtxt','solver.log'):(directory/name).write_text('generic evidence\n')
    for path in (directory/'recovered.xlsx',attempt/'calculated_pass1.xlsx',attempt/'recovered.xlsx'):
        b=openpyxl.Workbook();b.active['A1']=1;b.save(path);b.close()
    evidence={'terminal':{'fixture':'resource'}}
    class Helper:
        def validate_actual_call(self,call,terminal,preparation):
            assert terminal==evidence['terminal'] and preparation['runtime_profile']==profile_ref
            return evidence
    ctx.data['_linear_admission']=SimpleNamespace(source=SimpleNamespace(helper=Helper()))
    calls=[];source=directory/'recovered.xlsx'
    for index,destination in enumerate((attempt/'calculated_pass1.xlsx',attempt/'recovered.xlsx'),1):
        calls.append({'index':index,'completed':True,'input':recovery.reference(source),
            'output':recovery.reference(destination),'actual_resource_evidence':evidence})
        source=destination
    recovery._write(attempt/'stability.json',compare_typed_caches(attempt/'calculated_pass1.xlsx',attempt/'recovered.xlsx'))
    result={'attempt_record_path':str(attempt/'attempt.json'),'replay':replay,'recalculations':calls}
    def seal():
        replay['final_files']=recovery.inventory(directory)
        terminal=attempt/'replay_terminal.json'
        if terminal.exists():terminal.unlink()
        replay.pop('terminal',None);replay['terminal']=recovery._write(terminal,deepcopy(replay))
    seal()
    return ctx,result,seal


def test_cold_actual_execution_revalidates_normal_states_resources_and_stability(cold_execution):
    ctx,result,_=cold_execution
    assert recovery._execution_valid(ctx,result) is True


@pytest.mark.parametrize('name,key,value',[
    ('host_before','Status','running'),('host_before','Running',True),
    ('host_after','Status','running'),('host_after','Running',True),
    ('host_after','ExitCode',False),('host_after','ExitCode',1),('host_after','OOMKilled',True)])
def test_cold_validator_rejects_rebound_abnormal_actual_container_state(cold_execution,name,key,value):
    ctx,result,seal=cold_execution;path=Path(result['replay'][name]['path'])
    payload=json.loads(path.read_text());payload['State'][key]=value;path.write_text(json.dumps(payload))
    result['replay'][name]=recovery.reference(path);seal()
    with pytest.raises(ValueError,match='normal process states'):recovery._execution_valid(ctx,result)


def test_cold_validator_rejects_rebound_false_stability_summary(cold_execution):
    ctx,result,seal=cold_execution
    path=Path(result['recalculations'][0]['output']['path'])
    b=openpyxl.load_workbook(path);b.active['A1']=2;b.save(path);b.close()
    new=recovery.reference(path);result['recalculations'][0]['output']=new;result['recalculations'][1]['input']=new
    # Deliberately retain the old passed summary while all outer file refs are
    # refreshed. The cold validator must independently compare the whole union.
    seal()
    with pytest.raises(ValueError,match='typed union is unstable'):recovery._execution_valid(ctx,result)


def test_strict_witness_does_not_accept_persisted_verified_flag_or_other_revision(tmp_path):
    from types import SimpleNamespace
    ctx=SimpleNamespace(revision_dir=tmp_path,data={'revision_hash':'current'})
    assert not recovery.valid_linear_capital_recovery_witness(ctx,{'verified':True})
    assert not recovery.valid_linear_capital_recovery_witness(ctx,{'verified':True,'task_revision_hash':'old',
        'usage_calls':[],'usage_attribution':'not_applicable_programmatic'})


def test_strict_witness_cold_validation_then_opaque_guard_rejects_later_file_change(cold_execution,monkeypatch):
    import hashlib,shutil
    from sheets_factory.evaluation import streaming_delta
    ctx,result,_=cold_execution;ctx.data.update(revision_hash='revision-current',goal=ctx.data['input'])
    result.update(verified=True,task_revision_hash='revision-current',usage_calls=[],usage_attribution='not_applicable_programmatic')
    source=Path(result['recalculations'][-1]['output']['path']);canonical=ctx.revision_dir/'private/recovered.xlsx';shutil.copyfile(source,canonical)
    expected={'reward':1,'complete':'mocked only final private scoring boundary'}
    result['comparison']=expected
    monkeypatch.setattr(streaming_delta,'compare_workbooks',lambda *a:expected)
    monkeypatch.setattr(recovery,'_binding',lambda context,candidate:{'canonical':recovery.reference(canonical)})
    monkeypatch.setattr(recovery,'_artifacts',lambda context,candidate:{'calculated_pass2':source,'recovered':canonical})
    result['witness_binding']=recovery._binding(ctx,result)
    record=Path(result['attempt_record_path']);raw=(json.dumps(result,indent=2)+'\n').encode();record.write_bytes(raw)
    checksum=hashlib.sha256(raw).hexdigest();record.with_name('attempt.sha256').write_text(checksum+'\n')
    result['attempt_record_sha256']=checksum
    recovery._WITNESSES.clear()
    assert recovery.valid_linear_capital_recovery_witness(ctx,result) is True
    # The second pass uses only the opaque process-bound guard, never a flag
    # supplied by JSON. A changed canonical answer invalidates that same guard.
    assert recovery.valid_linear_capital_recovery_witness(ctx,result) is True
    canonical.write_bytes(b'changed output')
    assert recovery.valid_linear_capital_recovery_witness(ctx,result) is False


def test_generic_recovery_without_explicit_family_delegates_ordinary_node(tmp_path,monkeypatch):
    from types import SimpleNamespace
    expected={'recovery':{'ordinary':True}}
    monkeypatch.setattr(recovery.RecoveryNode,'execute',lambda self,context:expected)
    assert recovery.LinearCapitalRecoveryNode().execute(SimpleNamespace(config={})) is expected
