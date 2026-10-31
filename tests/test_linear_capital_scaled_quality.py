"""N360 normal integration with tiny values and explicit mocked trust boundaries."""
import ast
from copy import deepcopy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import openpyxl
import pytest
import yaml

from sheets_factory.pipelines import linear_capital_scaled_quality as q
from sheets_factory.pipelines import linear_capital_quality as old_q
from sheets_factory.task_adapters import linear_capital_scaled as a
from sheets_factory.workbook import linear_capital_scaled_public_recovery as recovery
from sheets_factory.workbook.linear_capital_scaled import task_views
from sheets_factory.workbook.heterogeneous_contracts.validate import compare_typed_caches
from sheets_factory.evaluation.streaming_delta import compare_workbooks
from sheets_factory.evaluation.streaming_verifier import compare_files

ROOT=Path(__file__).resolve().parents[1]


def load(name,path):
    loader=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module);return module


entry=load('_scaled_normal_entry_test',ROOT/'scripts/run_linear_capital_scaled_quality.py')
public_fixtures=load('_scaled_normal_vendor_fixtures',ROOT/'tests/test_linear_capital_scaled_public_recovery.py')
vendor=public_fixtures.vendor


def write(path,value):
    path.write_text(json.dumps(value));return q.reference(path)


@pytest.fixture
def provider(tmp_path):
    for name,data in [('source.xlsx',b'explicit fake financial source'),('child.txt',b'bound resource fixture')]:
        (tmp_path/name).write_bytes(data)
    public=write(tmp_path/'raw.json',{'explicit_mock_financial_boundary':True})
    bindings=write(tmp_path/'bindings.json',{'rows':[]});profile=write(tmp_path/'profile.json',{'fixture':True})
    evidence=write(tmp_path/'evidence.json',{'resource':q.reference(tmp_path/'child.txt')})
    manifest=write(tmp_path/'source_manifest.json',{'kind':'fixture_validated_scaled_source','version':1,
        'source_financially_verified':True,'workbook':q.reference(tmp_path/'source.xlsx'),
        'public_specification':public,'bindings':bindings,'runtime_profile':profile,
        'evidence':evidence,'source_recipe_sha256':{}})
    module=tmp_path/'provider.py'
    module.write_text("""import json
from pathlib import Path
SOURCE_KIND='fixture_validated_scaled_source'
calls=0
def validate_source(record):
 global calls
 calls+=1
 value=json.loads(Path(record['path']).read_text())
 if value.get('source_financially_verified') is not True: raise ValueError('not independently verified')
 return value
def validate_actual_call(*args): raise AssertionError('no services')
def runtime(*args): raise AssertionError('no services')
""")
    row={'id':'fixture','module':{**q.reference(module),'path':str(module.relative_to(ROOT))},
        'source_kind':'fixture_validated_scaled_source','api_version':1,'functions':{
            'validate_source':'validate_source','validate_actual_call':'validate_actual_call','runtime':'runtime'}}
    registry=write(tmp_path/'providers.json',{'kind':'linear_capital_scaled_source_provider_registry',
        'version':2,'providers':[row]})
    return tmp_path,manifest,registry,row


# Reuse the exact tiny seven-role value fixture, changing only explicit identities.
# This is test data construction, not a source/service admission implementation.
fixture_path=ROOT/'tests/test_linear_capital_quality_view_admission.py'
tree=ast.parse(fixture_path.read_text());tree.body=[node for node in tree.body
    if isinstance(node,ast.FunctionDef) and node.name in {'book','_binding','completed_view'}]
class FixtureIdentity(ast.NodeTransformer):
    def visit_Dict(self,node):
        keys={k.value:i for i,k in enumerate(node.keys) if isinstance(k,ast.Constant)}
        if 'kind' in keys:
            value=node.values[keys['kind']]
            if isinstance(value,ast.Constant) and value.value in {
                'prepared_linear_capital_task_view_actual_validation','linear_capital_task_view_actual_validation'}:
                node.values[keys['version']]=ast.Constant(2)
        return self.generic_visit(node)
    def visit_Constant(self,node):
        kinds={'planned_unverified_linear_capital_task_view':'planned_unverified_linear_capital_scaled_task_view',
            'materialized_unverified_linear_capital_task_view':'materialized_unverified_linear_capital_scaled_task_view',
            'prepared_linear_capital_task_view_actual_validation':'prepared_linear_capital_scaled_task_view_actual_validation',
            'linear_capital_task_view_actual_validation':'linear_capital_scaled_task_view_actual_validation'}
        if type(node.value) is str and node.value in kinds:node.value=kinds[node.value]
        return node
exec(compile(ast.fix_missing_locations(FixtureIdentity().visit(tree)),str(fixture_path),'exec'),globals())


def test_all_frozen_upstream_bytes_and_exact_new_namespace_substitutions():
    for module in (q,a,entry):
        assert hashlib.sha256(module.UPSTREAM.read_bytes()).hexdigest()==module.UPSTREAM_SHA256
        module.adapted_ast()
    assert q.LinearSourceAdmission is not old_q.LinearSourceAdmission
    assert q.LinearViewAdmission is not old_q.LinearViewAdmission
    assert a.validate_setting(a.setting())['version']==2
    assert entry.KIND=='prepared_complete_native_linear_capital_scaled_normal_quality'
    assert q.TASK_VALIDATOR_SHA256=='64af9d3e3b7ba7cfbd460cdad47d30dd9641cdb81e74c298137232d8a3611542'
    assert q.NORMAL_SOURCE_KIND!='audited_native_linear_capital_source_with_actual_task_views'


def test_production_provider_registry_is_exactly_new_scaled_source_only():
    registry=q.SourceProviders();row,helper=registry.load('scaled360')
    assert row['source_kind']=='independently_verified_linear_capital_scaled_native_source'
    assert helper.SOURCE_KIND==row['source_kind']
    assert Path(row['module']['path']).name=='build_linear_capital_scaled_source.py'
    for old in ('standard','producer16'):
        with pytest.raises(ValueError,match='Unknown provider'):registry.load(old)
    with pytest.raises(ValueError):q.SourceProviders(old_q.DEFAULT_PROVIDERS)


def test_one_cold_source_then_complete_seven_role_view_checks(completed_view):
    _,source,terminal,_,checked=completed_view
    live=q.LinearViewAdmission(source,terminal,provider_id='fixture');proof=live.guard()
    assert source.helper.calls==source.cold_source_validation_count==1
    assert len(checked)==7 and proof['full_D_count']==1 and proof['version']==2
    assert proof['kind']=='admitted_complete_native_linear_capital_scaled_task_view'
    assert not any(proof[k] for k in ('qualified','all_twelve_quality_checks_passed','recovery_certified',
        'Harbor_certified','difficulty_certified','prior_difficulty_transferred'))
    for _ in range(3):live.guard()
    assert source.helper.calls==1
    with pytest.raises(ValueError):old_q.require_view_admission(live)
    with pytest.raises(ValueError):q.require_view_admission({'passed':True})
    with pytest.raises(ValueError):q.require_view_admission(object.__new__(q.LinearViewAdmission))


@pytest.mark.parametrize('attack',['old_kind','old_version','missing_call','wrong_control','changed_raw_child'])
def test_complete_current_protocol_cannot_inherit_old_or_partial_evidence(completed_view,attack):
    root,source,terminal,result,_=completed_view
    if attack=='old_kind':result['kind']='linear_capital_task_view_actual_validation'
    if attack=='old_version':result['version']=1
    if attack=='missing_call':result['actual_LO_calls'].pop()
    if attack=='wrong_control':result['local_controls']={**result['local_controls'],'missed_root':1}
    if attack=='changed_raw_child':(root/'child.txt').write_bytes(b'changed source evidence')
    terminal=write(Path(terminal['path']),result)
    with pytest.raises(ValueError):q.LinearViewAdmission(source,terminal,provider_id='fixture')


def test_unrelated_cached_references_do_not_change_admitted_proof(completed_view,tmp_path):
    _,source,terminal,_,_=completed_view
    first=q.LinearViewAdmission(source,terminal,provider_id='fixture').guard()
    unrelated=tmp_path/'unrelated.txt';unrelated.write_text('not source evidence')
    source.references.check(q.reference(unrelated))
    second=q.LinearViewAdmission(source,terminal,provider_id='fixture').guard()
    assert first==second and str(unrelated) not in json.dumps(second)


def test_every_normal_node_and_all_twelve_numbered_checks_stay_available():
    a.validate_diagnose_copy()
    nodes=yaml.safe_load(a.REGISTRY.read_text())['nodes']
    assert len(nodes)==11 and nodes['trajectory']=='sheets_factory.nodes.quality:TrajectoryNode'
    assert nodes['independent_recovery'].endswith('linear_capital_scaled_public_recovery:LinearCapitalScaledRecoveryNode')
    for node,value in nodes.items():
        module,name=value.split(':');assert getattr(importlib.import_module(module),name)().node_id==node
    before=yaml.safe_load((ROOT/'config/pipelines/linear_capital_quality_v1.yaml').read_text())
    after=yaml.safe_load(entry.DEFAULT_CONFIG.read_text());before['run']['name']=after['run']['name']
    assert before==after
    assert after['diagnosis']['selection']=={'include':'all','exclude':[]}
    assert after['agents']['roles']['reference_diagnostician']['timeout_seconds']==2400


def test_debugging_keeps_all_eleven_actual_roles_and_same_plan_family_value_checks():
    protocol=q._task_validator(q.References())
    families={name:{} for name in task_views.FAMILIES}
    assert len(protocol.required_roles('financial_modeling',{}))==7
    roles=protocol.required_roles('debugging',families)
    assert len(roles)==11 and roles.count('same_temporary_plan_baseline')==1
    assert all('isolated_'+family in roles for family in families)
    tree=q.adapted_ast()
    klass=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LinearViewAdmission')
    check=next(n for n in klass.body if isinstance(n,ast.FunctionDef) and n.name=='_recheck_values')
    assert "baseline = result['temporary_plan_baseline']" in ast.unparse(check)
    assert "effect['complete_delta'] == delta(baseline, counter, counter)" in ast.unparse(check)


@pytest.fixture
def context(completed_view,monkeypatch):
    root,source,terminal,_,_=completed_view;session=q.LinearViewAdmission(source,terminal,provider_id='fixture')
    proof=session.guard();revision=root/'task/revisions/000';revision.mkdir(parents=True)
    baseline=root/'baseline.xlsx';shutil.copyfile(proof['goal']['path'],baseline)
    ctx=SimpleNamespace(config={a.SETTING:{'runtime_profile':proof['runtime_profile'],'provider_registry':proof['provider_registry']},
        'project_root':str(ROOT),'run_dir':str(root/'run')},mode='financial_modeling',source=Path(proof['workbook']['path']),
        revision_dir=revision,revision=0,task_id='scaled-tiny',directory=revision.parent.parent,
        data={'_linear_scaled_admission':session,'baseline':baseline,'engine_report':{'engine':{}},
            'finance_evidence':{'financial_seed_verified':True}},engine=SimpleNamespace())
    def save(name,value):
        path=revision/'private'/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,default=str));return path
    ctx.save=save;monkeypatch.setattr(a,'enabled',lambda ctx:True)
    return ctx,session


def test_normal_construct_preserves_complete_D_and_only_accepts_instruction_repair(context,monkeypatch):
    ctx,session=context;ctx.data['plan']=a.canonical_plan(session)
    monkeypatch.setattr(a,'evaluate_native_risk_guard',lambda *a,**k:{'blocking':False})
    monkeypatch.setattr(a,'probe_native_errors',lambda **k:{'blocking':False})
    monkeypatch.setattr(a,'profile_workbook',lambda *a,**k:{'truncated':False})
    result=a.LinearConstructNode().execute(ctx);ctx.data.update(result)
    assert result['delta']['expected_changes']==['Sheet!A2']
    assert result['construction_validation']['actual_new_LO_calls_by_construct']==0
    rendered=a.LinearInstructionNode().execute(ctx)
    assert rendered['instruction_path'].read_text()==session.plan['instruction']
    ctx.data['plan']['edits'][0]['after']=999
    with pytest.raises(ValueError,match='new actual view'):a.LinearConstructNode().execute(ctx)


def test_public_recovery_only_accepts_new_live_context_and_exact_current_bytes(context,monkeypatch):
    ctx,session=context;proof=session.guard()
    ctx.data.update(input=Path(proof['input']['path']),goal=Path(proof['goal']['path']))
    monkeypatch.setattr(recovery,'_settings',lambda unused:({},proof['runtime_profile'],{},{}))
    assert recovery._admission_source(ctx) is session.source
    assert recovery._source_binding(ctx)['view_plan']==proof['view_plan']
    old=ctx.data.pop('_linear_scaled_admission');ctx.data['_linear_admission']=old
    with pytest.raises(ValueError):recovery._admission_source(ctx)
    ctx.data['_linear_scaled_admission']=old;ctx.data['finance_evidence']['financial_seed_verified']=False
    with pytest.raises(ValueError,match='admitted financial source'):recovery._source_binding(ctx)


def test_zero_service_prepare_cold_guards_and_real_factory_template_loading(completed_view,vendor,tmp_path,monkeypatch):
    _,source,terminal,_,_=completed_view
    monkeypatch.setattr(q,'validate_configuration',lambda config:{'fixture':True})
    runtime=recovery.prepare_public_runtime(tmp_path/'runtime')
    out=tmp_path/'normal';entry.prepare(source.source_manifest,terminal,out,source_provider='fixture',
        provider_registry=source.providers.reference,public_runtime_preparation=runtime)
    frozen,config,sessions=entry.validate_prepared(out)
    assert frozen['version']==2 and frozen['count']==1 and frozen['qualified'] is False
    assert all(frozen[k]==0 for k in ('actual_models','actual_LO_calls','actual_solver_calls','actual_Harbor_jobs','task_count'))
    assert config[a.SETTING]['version']==2 and not (out/'run.sqlite').exists()
    assert 'linear_scaled_view_admissions' in entry.pipeline.References().read(frozen['prepared_seed_manifest'])['selected'][0]['finance_evidence']
    assert str(q.UPSTREAM) in frozen['recipe_sha256'] and str(a.UPSTREAM) in frozen['recipe_sha256']
    assert str(entry.UPSTREAM) in frozen['recipe_sha256'] and str(q.TASK_VALIDATOR) in frozen['recipe_sha256']
    before=source.helper.calls;entry.validate_prepared(out);assert source.helper.calls==before
    entry._PREPARED_SESSIONS.clear();entry.validate_prepared(out);assert source.helper.calls==before+1
    factory=q.LinearCapitalQualityFactory(config,SimpleNamespace(),None,SimpleNamespace(),admissions=sessions)
    assert factory.templates['financial_modeling']['phases']['revision']==[
        'construct','instruction','precheck','independent_recovery','trajectory','diagnose']
    assert factory.load_node('trajectory').__class__.__module__=='sheets_factory.nodes.quality'


def test_configuration_checks_profile_recovery_and_real_numbered_check_catalog(vendor,tmp_path):
    runtime=recovery.prepare_public_runtime(tmp_path/'runtime')
    proof={'runtime_profile':q.reference(a.PROFILE),'provider_registry':q.reference(q.DEFAULT_PROVIDERS),
        'workbook':{'sha256':'a'*64},'mode':'financial_modeling'}
    config,_=entry._configuration(entry.DEFAULT_CONFIG,tmp_path/'normal',[proof],proof['provider_registry'],runtime)
    assert q.validate_configuration(config)['id']=='entity_group_large_v2'
    bad=deepcopy(config);bad['agents']['container_cpus']=16
    with pytest.raises(ValueError,match='separate'):q.validate_configuration(bad)
    assert config['recovery']['replay_timeout_seconds']==7200
    assert config['recovery']['offline_public_recovery']['cpus']==16


def test_cli_and_isolated_role_worker_cap_remain_explicit_and_unchanged(tmp_path):
    with pytest.raises(ValueError,match='Prepare and review'):
        entry.main(['--source-manifest','x','--validation-terminal','y','--output',str(tmp_path/'q'),
            '--public-runtime-preparation','z','--run'])
    instance=entry.LinearCohortCodex(ROOT,tmp_path,None,{'container_memory':'32g','container_cpus':2})
    parent=entry.cohort.CohortCodex._build_command(instance,tmp_path,'http://localhost/v1',True,'test')
    assert instance._build_command(tmp_path,'http://localhost/v1',True,'test')==parent[:2]+['--env','MAX_CONCURRENCY=2']+parent[2:]


def test_normal_export_keeps_required_external_audit_argument_and_strict_witness(context,monkeypatch):
    ctx,_=context;ctx.data.update(recovery={},source_id='s',revision_hash='r')
    ctx.config['engine']={'image':'sheetsfactory-lo:24.2-iterative-openpyxl315-v1'}
    monkeypatch.setattr(a,'valid_linear_capital_recovery_witness',lambda *args:False)
    monkeypatch.setattr(a,'verify_local_base_image',lambda *args:pytest.fail('No export before a witness'))
    with pytest.raises(ValueError,match='witness'):a.LinearExportNode().execute(ctx)
    monkeypatch.setattr(a,'valid_linear_capital_recovery_witness',lambda *args:True)
    monkeypatch.setattr(a,'verify_local_base_image',lambda *args:{'explicit_mock_image_check':True})
    calls=[]
    def exported(revision,destination,metadata,root,*,runtime_profile,audit_path):
        calls.append((destination,audit_path));destination.mkdir(parents=True)
        assert audit_path==ctx.revision_dir/'private/linear_harbor_worker_cap.json'
    def inspected(destination,*,audit_path):
        assert calls==[(destination,audit_path)]
        return {'task_id':ctx.task_id,'revision_hash':'r'}
    monkeypatch.setattr(a,'export_resource_harbor',exported);monkeypatch.setattr(a,'inspect_resource_export',inspected)
    assert a.LinearExportNode().execute(ctx)['export_dir']==calls[0][0]


def test_financial_repair_cannot_modify_the_frozen_source_or_mutation_scope(context):
    from sheets_factory.core.node import TaskRejected
    ctx,_=context
    ctx.data['repair_routes']=[{'route_class':'repair','issue_id':'financial','problem_id':'Q04'}]
    ctx.data['diagnosis']={'issues':[{'issue_id':'financial','certainty':'confirmed'}]}
    with pytest.raises(TaskRejected,match='newly admitted actual source/view'):a.LinearRepairNode().execute(ctx)


def solver_descriptor(tmp_path,*,fault=None):
    bundle=tmp_path/'job_bundle';bundle.mkdir()
    host={}
    for name in ('solver.log','native_model.pbtxt','native_model.pbtxt.parameters.pbtxt'):
        path=bundle/name;path.write_text('Exact explicit mock solver artifact\n');host[name]=q.reference(path)
    solver={'checked_optimal':True,'backend':'ortools_cp_sat','solver_version':'9.14.6206'}
    for field,name in (('log_reference','solver.log'),('model_reference','native_model.pbtxt'),
            ('parameters_reference','native_model.pbtxt.parameters.pbtxt')):
        solver[field]={**host[name],'path':'/app/'+name}
    sref=write(bundle/'solver_result.json',solver);host['solver_result.json']=sref
    rref=write(bundle/'runtime_result.json',{'explicit_mock_runtime':True})
    cleanup=write(tmp_path/'cleanup.json',{'explicit_mock_cleanup':True})
    image='sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
    preparation={'kind':'prepared_private_linear_capital_scaled_producer16_solver','version':2,
        'bundle':str(bundle),'image_id':image,'request':{'backend':'cp_sat'},
        'resources':{'cpus':16,'memory_bytes':32*1024**3,'pids_limit':256}}
    if fault=='old_kind':preparation['kind']='prepared_private_linear_capital_producer16_solver'
    if fault=='old_version':preparation['version']=1
    pref=write(tmp_path/'preparation.json',preparation)
    actual={'Id':'a'*64,'Image':image,'NanoCpus':16*10**9,'Memory':32*1024**3,'PidsLimit':256,'NetworkMode':'none',
        'Mounts':[{'Type':'bind','RW':True,'Source':str(bundle),'Destination':'/app'}],
        'State':{'Status':'created','Running':False,'ExitCode':0,'OOMKilled':False}}
    if fault=='CPU':actual['NanoCpus']=2*10**9
    before=write(tmp_path/'before.json',actual);actual=deepcopy(actual);actual['State']['Status']='exited'
    after=write(tmp_path/'after.json',actual)
    tref=write(tmp_path/'terminal.json',{'kind':'private_linear_capital_scaled_producer16_solver_execution','version':2,
        'status':'reference_optimal_checked','preparation':pref,'solver_result':sref,'runtime_result':rref,'cleanup':cleanup,
        'container_id':'a'*64,'image_id':image,'actual_resources_verified':True,
        'retained_job_inventory':host,'complete_job_inventory':host})
    return {'preparation':pref,'terminal':tref,'host_before':before,'host_after':after,'cleanup':cleanup,
        'solver_result':sref,'runtime_result':rref,'checked_optimal':True,'solver':solver,'matrix_result_check':{}}


def test_new_v2_container_local_descriptors_map_only_to_complete_actual_host_inventory(tmp_path):
    descriptor=solver_descriptor(tmp_path);refs=q.References()
    aliases=refs._solver_artifact_aliases(descriptor)
    assert len(aliases)==3 and len(refs.container_artifact_bindings)==3
    refs.discover(descriptor['solver_result'])
    assert not any(path.startswith('/app/') for path in refs.files)
    with pytest.raises(ValueError,match='unmapped container-local'):q.References().discover(descriptor['solver_result'])


@pytest.mark.parametrize('fault',['old_kind','old_version','CPU'])
def test_old_or_wrong_native_resource_descriptors_are_not_new_source_evidence(tmp_path,fault):
    descriptor=solver_descriptor(tmp_path,fault=fault)
    with pytest.raises(ValueError):q.References()._solver_artifact_aliases(descriptor)
