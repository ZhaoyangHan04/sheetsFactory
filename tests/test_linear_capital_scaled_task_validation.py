"""N360 validator orchestration with tiny XLSX and mocked resource boundaries."""
from copy import deepcopy
from contextlib import nullcontext
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location('linear_task_validation_test_entry', ROOT/'scripts/validate_linear_capital_scaled_task_view.py')
entry = importlib.util.module_from_spec(loader); loader.loader.exec_module(entry)
from sheets_factory.workbook.linear_capital_scaled import task_views


def ref(path):
    path=Path(path).resolve(); data=path.read_bytes()
    return {'path':str(path),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f:json.dump(value,f,indent=2);f.write('\n')
    return ref(path)


def checked(record):
    if ref(record['path'])!=record:raise ValueError('Frozen artifact changed')
    return Path(record['path'])


def read(value):
    return json.loads((checked(value) if isinstance(value,dict) else Path(value)).read_text())


def require(value,message):
    if not value:raise ValueError(message)


def workbook(path,values):
    book=openpyxl.Workbook();s=book.active;s.title='Model'
    s['A1']='Provided title / unit GBP pence'
    for cell,value in values.items():s[cell]=value
    book.save(path);book.close();return ref(path)


@pytest.fixture
def tiny_run(tmp_path,monkeypatch):
    """Source admission and calculation receipts are explicitly unit mocks."""
    state={'source_admissions':0,'engine_calls':[]}
    source_goal=workbook(tmp_path/'unit_source_goal.xlsx',{'A2':20,'A3':30,'A4':40,'B2':1})
    profile=write(tmp_path/'mock_profile.json',{'test_mock_no_real_resource_claim':True})
    source_bindings=write(tmp_path/'mock_source_bindings.json',{'specification_sha256':'s'*64})
    source_manifest={'kind':entry.SOURCE_PROVIDERS['scaled360'][1],'workbook':source_goal,'bindings':source_bindings,'runtime_profile':profile}
    source_ref=write(tmp_path/'mock_source_admission.json',source_manifest)
    def validate_source(value):
        assert value==source_ref;state['source_admissions']+=1;return source_manifest
    def actual(call,resource_record,frozen):
        receipt=read(resource_record)
        require(receipt['kind']=='TEST_MOCK_NO_ACTUAL_LO' and receipt['input']==call['input']
            and receipt['output']==call['output'],'Mock actual-call identity differs')
        return {'terminal':resource_record,'test_mock_no_actual_resource_claim':True}
    support=SimpleNamespace(reference=ref,checked=checked,read=read,write=write,require=require,
        validate_source=validate_source,canonical=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest(),_output=lambda p,fresh=False:Path(p),
        runtime=lambda p:(ref(p),{'test_mock':True}),recipes=lambda:{'unit_mock_'+state.get('expected_provider','scaled360'):'a'*64},
        _resource_support=lambda:SimpleNamespace(data_temporary=lambda p:nullcontext(),validate_actual_call=actual))
    def support_loader(provider='scaled360'):
        entry._provider(provider)
        state.setdefault('support_providers',[]).append(provider)
        return support
    monkeypatch.setattr(entry,'source_support',support_loader)
    # This test exercises the task-validation orchestration, not the independently
    # tested complete task-plan compiler or source financial admission.
    monkeypatch.setattr(task_views,'_check_plan',lambda p:require(p['source']==source_goal,'Wrong source plan'))
    class Engine:
        def __init__(self,*args,receipt_directory,**kwargs):self.directory=Path(receipt_directory);self.directory.mkdir();self.history=[]
        def ensure_image(self):return 'TEST_MOCK_NO_DOCKER'
        def recalculate(self,source,destination):
            state['engine_calls'].append(Path(destination).stem)
            before=ref(source);book=openpyxl.load_workbook(source)
            for sheet in book:
                for row in sheet:
                    for cell in row:
                        if cell.data_type=='f':
                            # Only literal unit control expressions are supported;
                            # this is not a financial calculation implementation.
                            terms=cell.value[1:].split('+')
                            assert all(term.isdigit() for term in terms)
                            cell.value=sum(map(int,terms))
            book.save(destination);book.close()
            record=write(self.directory/(str(len(self.history))+'.json'),
                {'kind':'TEST_MOCK_NO_ACTUAL_LO','input':before,'output':ref(destination)})
            self.history.append(record);return Path(destination)
        def metadata(self):return {'actual_resource_receipts':self.history}
    support.ResourceLibreOfficeEngine=Engine
    support.validate_actual_call=actual
    # Actual AuditStore writes only the tiny mock-run evidence. The panel remains
    # mocked, so tests open no service and execute no Docker or model.
    class Dashboard:
        def __init__(self,*args,**kwargs):pass
        def start(self):return 'http://127.0.0.1:12345/'
        def stop(self):pass
    monkeypatch.setattr(entry,'DashboardServer',Dashboard)
    def make(mode,provider='scaled360'):
        nonlocal source_ref
        state['expected_provider']=provider
        if provider!='scaled360':
            source_manifest['kind']=entry.SOURCE_PROVIDERS[provider][1]
            source_ref=write(tmp_path/'mock_producer_source_admission.json',source_manifest)
        folder=tmp_path/mode;folder.mkdir()
        instruction='Unit financial model; preserve provided facts.\n'
        ip=folder/'instruction.md';ip.write_text(instruction)
        goal=folder/'goal.xlsx';goal.write_bytes(Path(source_goal['path']).read_bytes())
        families={};temporary=None
        if mode=='financial_modeling':
            inp=workbook(folder/'input.xlsx',{'A2':None,'A3':None,'A4':None,'B2':None})
            targets=[{'sheet':'Model','cell':c} for c in ('A2','A3','A4','B2')];edits=[]
        else:
            inp=workbook(folder/'input.xlsx',{'A2':25,'A3':37,'A4':49,'B2':0})
            targets=[];edits=[{'sheet':'Model','cell':c} for c in ('A2','A3','A4')]
            temporary=workbook(folder/'same_plan.xlsx',{'A2':20,'A3':30,'A4':40,'B2':0})
            for family,cell,wrong in zip(task_views.FAMILIES,('A2','A3','A4'),(25,37,49)):
                values={'A2':20,'A3':30,'A4':40,'B2':0};values[cell]=wrong
                families[family]=workbook(folder/(family+'.xlsx'),values)
        plan={'bindings_canonical_sha256':support.canonical(read(source_bindings)),'source':source_goal,'sheetnames':['Model'],'specification_sha256':'s'*64,'mode':mode,
            'plan_sha256':'p'*64,'recipe':task_views._recipe(),'instruction':instruction,'masked_targets':targets,'formula_edits':edits}
        plan_ref=write(folder/'plan.json',plan)
        view={'kind':'materialized_unverified_linear_capital_scaled_task_view','version':1,'mode':mode,'source':source_goal,
            'specification_sha256':'s'*64,'plan':plan_ref,'plan_sha256':'p'*64,'recipe':plan['recipe'],
            'input':inp,'goal':ref(goal),'instruction':ref(ip),'family_inputs':families,'temporary_plan_only':temporary,'sheetnames':['Model']}
        view_ref=write(folder/'view.json',view)
        state.update(source_ref=source_ref, view_ref=view_ref, plan_ref=plan_ref)
        output=folder/'validation'
        prepared=entry.prepare(source_ref['path'],view_ref['path'],output,source_provider=provider)
        terminal=entry.execute_prepared(output)
        return output,terminal,state
    return make


def mutate_terminal(terminal,name,change):
    result=read(terminal);change(result)
    return write(Path(terminal['path']).parent/(name+'.json'),result)


@pytest.mark.parametrize('provider',['scaled360'])
@pytest.mark.parametrize('mode,count',[('financial_modeling',7),('debugging',11)])
def test_exact_role_inventory_real_tiny_D_and_five_controls_with_mock_engine(tiny_run,mode,count,provider):
    output,terminal,state=tiny_run(mode,provider)
    result=entry.validate_completed(terminal)
    assert result['kind']==entry.KIND and result['version']==2
    assert read(output/'preparation.json')['version']==2
    assert result['passed'] is True and result['local_controls']==entry.REWARDS
    assert len(state['engine_calls'])==count
    assert state['engine_calls']==entry.required_roles(mode,task_views.FAMILIES if mode=='debugging' else ())
    assert len(read(result['complete_D'])['expected_changes'])>0
    assert state['source_admissions']>=4
    assert result['all_twelve_quality_checks_passed'] is result['difficulty_certified'] is False
    assert result['actual_Harbor_jobs']==result['model_calls']==0
    assert result['source_provider']==read(output/'preparation.json')['source_provider']==provider
    assert set(state['support_providers'])=={provider}
    if mode=='debugging':
        for item in result['individual_effects'].values():
            effect=read(item)
            assert effect['complete_delta']['expected_change_count']==1
            assert effect['same_temporary_plan_baseline']==result['temporary_plan_baseline']
    with pytest.raises(ValueError):entry.execute_prepared(output)


@pytest.mark.parametrize('target',['full_D_pair','goal_stability_pair','raw_control_input','control_report_pair','input_chain','foreign_resources','missing_call','false_quality','role_order','unexpected_debug_baseline'])
def test_cold_validation_rejects_cross_task_or_incomplete_evidence(tiny_run,target):
    output,terminal,_=tiny_run('financial_modeling')
    def change(result):
        if target=='full_D_pair':
            delta=read(result['complete_D']);delta['workbook_binding']['input']=result['goal']
            result['complete_D']=write(output/'wrong_D_pair.json',delta)
        if target=='goal_stability_pair':
            stable=read(result['goal_stability']);stable['left']=result['input']
            result['goal_stability']=write(output/'wrong_goal_stability.json',stable)
        if target=='raw_control_input':
            controls=read(result['controls_evidence']);controls['raw_control_inputs']['equivalent']=result['goal']
            result['controls_evidence']=write(output/'wrong_raw_control.json',controls)
        if target=='control_report_pair':
            controls=read(result['controls_evidence']);report=read(controls['reports']['nop'])
            report['workbook_binding']['goal']=result['input']
            controls['reports']['nop']=write(output/'wrong_control_pair_report.json',report)
            result['controls_evidence']=write(output/'wrong_control_pair_evidence.json',controls)
        if target in ('input_chain','foreign_resources'):
            call=next(c for c in result['actual_LO_calls'] if c['role']=='input_pass2')
            resource=read(call['actual_resource_evidence']['terminal'])
            resource['input']=result['goal']
            call['actual_resource_evidence']['terminal']=write(output/'wrong_resource_binding.json',resource)
            if target=='input_chain':call['input']=result['goal']
            call['terminal_receipt']=write(output/'wrong_input_call_terminal.json',{k:v for k,v in call.items() if k!='terminal_receipt'})
        if target=='unexpected_debug_baseline':result['temporary_plan_baseline']=result['goal']
        if target=='missing_call':result['actual_LO_calls'].pop()
        if target=='false_quality':result['all_twelve_quality_checks_passed']=True
        if target=='role_order':result['actual_LO_calls'][1],result['actual_LO_calls'][2]=result['actual_LO_calls'][2],result['actual_LO_calls'][1]
    bad=mutate_terminal(terminal,'wrong_'+target,change)
    with pytest.raises(ValueError):entry.validate_completed(bad)


@pytest.mark.parametrize('target',['winner_basis','zero_effect','omitted_family','delta_pair'])
def test_debug_family_effects_require_nonempty_same_temporary_plan_basis(tiny_run,target):
    output,terminal,_=tiny_run('debugging')
    def change(result):
        family=task_views.FAMILIES[0]
        if target=='omitted_family':result['individual_effects'].pop(family);return
        effect=read(result['individual_effects'][family])
        if target=='winner_basis':effect['same_temporary_plan_baseline']=result['goal']
        elif target=='delta_pair':effect['complete_delta']['workbook_binding']['input']=result['goal']
        else:effect['complete_delta'].update(expected_change_count=0,actual_change_count=0,expected_changes=[],actual_changes=[])
        result['individual_effects'][family]=write(output/'wrong_family_effect.json',effect)
    bad=mutate_terminal(terminal,'wrong_'+target,change)
    with pytest.raises(ValueError):entry.validate_completed(bad)


def test_complete_typed_guard_rejects_pass_only_empty_scope():
    a={'path':'a','sha256':'a','bytes':1};b={'path':'b','sha256':'b','bytes':1}
    with pytest.raises(ValueError):entry._require_typed_stability({'passed':True,'left':a,'right':b},a,b)


def test_unknown_mode_is_not_silently_treated_as_modeling():
    with pytest.raises(ValueError):entry.required_roles('unknown')


def test_view_plan_cannot_rebind_different_private_financial_locators(tiny_run):
    output,_,state=tiny_run('financial_modeling')
    plan=read(state['plan_ref']);plan['bindings_canonical_sha256']='0'*64
    changed_plan=write(output/'different_binding_plan.json',plan)
    view=read(state['view_ref']);view['plan']=changed_plan
    changed_view=write(output/'different_binding_view.json',view)
    with pytest.raises(ValueError,match='recipe or plan'):
        entry._view(state['source_ref'],changed_view)


@pytest.mark.parametrize('provider',[None,True,{},'../arbitrary.py','unknown'])
def test_fixed_registry_rejects_unknown_provider_before_import(monkeypatch,provider):
    monkeypatch.setattr(entry.importlib.util,'spec_from_file_location',lambda *a:pytest.fail('Unknown provider caused an import'))
    with pytest.raises(ValueError,match='Unknown fixed source provider'):
        entry.source_support(provider)


@pytest.mark.parametrize('provider',['scaled360'])
def test_selected_provider_import_is_lazy_and_fixed(monkeypatch,provider):
    calls=[];module=SimpleNamespace()
    descriptor=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda value:calls.append(('exec',value))))
    def descriptor_for(name,path):
        calls.append(('path',name,path));return descriptor
    monkeypatch.setattr(entry.importlib.util,'spec_from_file_location',descriptor_for)
    monkeypatch.setattr(entry.importlib.util,'module_from_spec',lambda value:module)
    assert entry.source_support(provider) is module
    assert calls==[('path','_linear_task_source_support_'+provider,entry.ROOT/'scripts'/entry.SOURCE_PROVIDERS[provider][0]),('exec',module)]


@pytest.mark.parametrize('provider',['scaled360'])
def test_recipes_use_only_selected_provider_closure(monkeypatch,provider):
    calls=[]
    def support(name='scaled360'):
        calls.append(name)
        return SimpleNamespace(recipes=lambda:{'/selected/'+name: name},reference=ref)
    monkeypatch.setattr(entry,'source_support',support)
    recipe=entry.recipes(provider)
    assert calls==[provider] and recipe['/selected/'+provider]==provider
    assert '/selected/producer16' not in recipe
    assert not any('build_linear_capital_producer_source.py' in p for p in recipe if provider=='scaled360')


def test_source_kind_is_bound_to_explicit_provider_before_source_validation(tiny_run):
    _,_,state=tiny_run('financial_modeling')
    manifest=read(state['source_ref']);manifest['kind']='independently_verified_linear_capital_native_source'
    wrong=write(Path(state['source_ref']['path']).parent/'different_source_kind.json',manifest)
    with pytest.raises(ValueError,match='source provider does not match'):
        entry._view(wrong,state['view_ref'])


@pytest.mark.parametrize('field',['missing','unknown','changed'])
def test_cold_terminal_rejects_missing_or_cross_provider_binding(tiny_run,field):
    _,terminal,_=tiny_run('financial_modeling')
    def change(result):
        if field=='missing':result.pop('source_provider')
        else:result['source_provider']='unregistered' if field=='unknown' else 'producer16'
    bad=mutate_terminal(terminal,'bad_provider_'+field,change)
    with pytest.raises(ValueError):
        entry.validate_completed(bad)


@pytest.mark.parametrize('provider', ['standard', 'producer16'])
def test_old_family_provider_names_are_not_admission_routes(provider):
    with pytest.raises(ValueError, match='Unknown fixed source provider'):
        entry._provider(provider)


@pytest.mark.parametrize('version', [1, True, 3])
def test_scaled_actual_envelope_rejects_old_or_ambiguous_versions(tiny_run, version):
    _, terminal, _ = tiny_run('financial_modeling')
    bad = mutate_terminal(terminal, 'wrong_version_'+str(version), lambda value: value.update(version=version))
    with pytest.raises(ValueError, match='completed actual task validation'):
        entry.validate_completed(bad)


def test_exact_recipe_closure_and_ast_do_not_mutate_original_driver():
    before = entry.UPSTREAM.read_bytes()
    recipe = entry.recipes()
    assert recipe[str(entry.UPSTREAM.resolve())] == entry.UPSTREAM_SHA256
    assert str(ROOT/'scripts/build_linear_capital_scaled_source.py') in recipe
    assert str(ROOT/'src/sheets_factory/workbook/linear_capital_scaled/task_views.py') in recipe
    assert entry.SOURCE_PROVIDERS == {'scaled360': ('build_linear_capital_scaled_source.py',
        'independently_verified_linear_capital_scaled_native_source')}
    assert entry.UPSTREAM.read_bytes() == before


def test_cli_has_no_provider_override_or_confirmation_routes():
    for arguments in (['prepare', '--source-provider', 'standard'], ['confirmation'], ['resume']):
        with pytest.raises(SystemExit): entry.main(arguments)


def test_frozen_upstream_hash_is_rechecked_after_import(tmp_path, monkeypatch):
    changed = tmp_path/'changed_original.py'; changed.write_bytes(entry.UPSTREAM.read_bytes()+b'\n')
    monkeypatch.setattr(entry, 'UPSTREAM', changed)
    with pytest.raises(ValueError, match='frozen complete actual task validator'):
        entry.adapted_ast()
