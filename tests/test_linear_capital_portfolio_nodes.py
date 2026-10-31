"""Normal node route tests use tiny books and zero external services."""
from copy import deepcopy
import importlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import shutil

import openpyxl
import pytest
import yaml

from sheets_factory.task_adapters import linear_capital_portfolio as a
from sheets_factory.pipelines import linear_capital_quality as q

loader=importlib.util.spec_from_file_location('_linear_node_admission_fixtures',Path(__file__).with_name('test_linear_capital_quality_view_admission.py'))
f=importlib.util.module_from_spec(loader);loader.loader.exec_module(f)
provider=f.provider
completed_view=f.completed_view


def test_explicit_setting_and_strict_diagnosis_copy_keep_normal_twelve_check_body():
    assert a.validate_setting(a.setting())['adapter']==a.ADAPTER_ID
    a.validate_diagnose_copy()
    source=Path(a.__file__).read_text()
    assert "elif not valid_linear_capital_recovery_witness(ctx, ctx.data['recovery'])" in source


def test_registry_loads_every_normal_route_and_preserves_all_trajectories():
    nodes=yaml.safe_load(a.REGISTRY.read_text())['nodes']
    assert set(nodes)=={'normalize','profile','plan','construct','instruction','precheck','independent_recovery','trajectory','diagnose','repair','export'}
    assert nodes['trajectory']=='sheets_factory.nodes.quality:TrajectoryNode'
    for key,value in nodes.items():
        module,name=value.split(':');instance=getattr(importlib.import_module(module),name)()
        assert instance.node_id==key


@pytest.fixture
def context(completed_view,monkeypatch):
    root,source,terminal,_,_=completed_view
    session=q.LinearViewAdmission(source,terminal,provider_id='fixture');p=session.guard()
    revision=root/'task/revisions/000';revision.mkdir(parents=True)
    baseline=root/'baseline.xlsx';shutil.copyfile(p['goal']['path'],baseline)
    profile={'truncated':False,'errors':[],'external_references':[],'formula_count':2,'nonempty_sheet_count':4,'sheet_count':4,'sheets':[]}
    ctx=SimpleNamespace(config={a.SETTING:{'runtime_profile':p['runtime_profile'],'provider_registry':p['provider_registry']},
        'project_root':str(q.ROOT),'run_dir':str(root/'run')},mode='financial_modeling',source=Path(p['workbook']['path']),
        revision_dir=revision,revision=0,task_id='normal-tiny',directory=revision.parent.parent,engine=SimpleNamespace(),
        data={'_linear_admission':session,'baseline':baseline,'engine_report':{'engine':{}},'profile':profile})
    saved={}
    def save(name,value):
        saved[name]=deepcopy(value)
        path=revision/'private'/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,default=str));return path
    ctx.save=save;ctx.saved=saved
    monkeypatch.setattr(a,'enabled',lambda unused:True)
    return ctx,session


def test_context_checks_actual_copied_bytes_and_source_identity(context):
    ctx,session=context
    assert a.context_proof(ctx)['mode']=='financial_modeling'
    ctx.data['baseline'].write_bytes(b'wrong copied baseline')
    with pytest.raises(ValueError,match='copied'):a.context_proof(ctx)


def test_plan_preserves_literal_financial_zero_and_has_no_public_private_answers(context):
    ctx,session=context
    session.plan['masked_targets'].append({'sheet':'Sheet','cell':'A3','before':0})
    plan=a.canonical_plan(session)
    assert {'sheet':'Sheet','cell':'A3','before':0,'after':None,
        'reason':'Complete the financial model and common investment choices.'} in plan['edits']
    assert plan['public_instruction']==session.plan['instruction'] and plan['public_rules']==list(a.excel.PUBLIC_RULES)
    assert 'winner' not in plan['public_instruction'] and 'private' not in plan['public_instruction']
    assert plan['family_adapter']['individual_or_marginal_root_activity_claimed'] is False


def test_construct_and_instruction_bind_actual_full_D_without_claiming_new_LO(context,monkeypatch):
    ctx,session=context;ctx.data['plan']=a.canonical_plan(session)
    monkeypatch.setattr(a,'evaluate_native_risk_guard',lambda *args,**kwargs:{'blocking':False,'state':'clear'})
    def probe(**kwargs):
        assert kwargs['max_dependency_cells']==3_000_000
        assert kwargs['required_delta']==session.delta['expected_changes']
        return {'blocking':False,'state':'not_applicable','complete_closure_checked':True}
    monkeypatch.setattr(a,'probe_native_errors',probe)
    monkeypatch.setattr(a,'profile_workbook',lambda *args,**kwargs:{'truncated':False,'errors':[]})
    result=a.LinearConstructNode().execute(ctx);ctx.data.update(result)
    assert result['delta']['expected_changes']==['Sheet!A2']
    assert result['root_impacts']==[] and result['construction_validation']['actual_new_LO_calls_by_construct']==0
    assert result['construction_validation']['individual_or_marginal_root_activity_claimed'] is False
    rendered=a.LinearInstructionNode().execute(ctx)
    assert rendered['instruction']==session.plan['instruction']
    assert rendered['instruction_path'].read_text()==rendered['instruction']


def test_construct_rejects_changed_financial_edit_but_accepts_only_brief_repair(context,monkeypatch):
    ctx,session=context;ctx.data['plan']=a.canonical_plan(session)
    ctx.data['plan']['edits'][0]['after']=999
    with pytest.raises(ValueError,match='new actual view'):a.LinearConstructNode().execute(ctx)


def test_profile_prompt_is_bounded_examples_while_full_profile_is_unchanged():
    cells=[{'cell':f'A{i}','formula':'=1','cached_value':1,'row_labels':[],'column_labels':[]} for i in range(1,50)]
    value={'sheet_count':1,'nonempty_sheet_count':1,'formula_count':49,'errors':[],'external_references':[],
        'sheets':[{'name':'Business','state':'visible','nonempty_cells':49,'formula_count':49,'cells':cells}]}
    before=deepcopy(value);compact=a.compact_profile(value)
    assert value==before and len(compact['sheets'][0]['formulas'])==1
    assert compact['examples_are_not_complete_target_or_audit_coverage']


@pytest.mark.parametrize('failed_omission',[False,True])
def test_normal_controls_are_three_real_engine_boundaries_plus_five_grades_with_failures_retained(context,monkeypatch,failed_omission):
    ctx,session=context;proof=session.guard();public=ctx.revision_dir/'public';private=ctx.revision_dir/'private'
    public.mkdir();private.mkdir();source=public/'input.xlsx';goal=private/'goal.xlsx'
    shutil.copyfile(proof['input']['path'],source);shutil.copyfile(proof['goal']['path'],goal)
    ctx.data.update(input=source,goal=goal,delta=session.delta,revision_hash='normal-revision')
    metadata={'actual_resource_receipts':[]};executed=[]
    class Engine:
        def metadata(self):return metadata
        def recalculate(self,raw,destination):
            executed.append(raw.name);b=openpyxl.load_workbook(raw)
            if b.active['A2'].value=='=1+0':b.active['A2']=1
            if failed_omission and 'missed_root' in raw.name:b.active['A2']=1
            b.save(destination);b.close();metadata['actual_resource_receipts'].append({'fixture':raw.name});return destination
    ctx.engine=Engine()
    monkeypatch.setattr(a,'load_runtime_profile',lambda path:{'fixture':True})
    monkeypatch.setattr(session.source.helper,'validate_actual_call',lambda call,receipt,settings:{'bound':receipt})
    if failed_omission:
        with pytest.raises(ValueError,match='actual normal'):a.LinearControlsNode().execute(ctx)
    else:
        result=a.LinearControlsNode().execute(ctx)
        assert {k:v['reward'] for k,v in result['controls'].items()}==a.REWARDS
    records=list((private/'controls').glob('attempt_*/attempt.json'));assert len(records)==1
    observed=json.loads(records[0].read_text())
    assert observed['completed'] is (not failed_omission) and len(observed['actual_LO_calls'])==3
    assert len(executed)==3


def test_export_requires_strict_witness_before_any_image_or_export_operation(context,monkeypatch):
    ctx,_=context
    monkeypatch.setattr(a,'valid_linear_capital_recovery_witness',lambda *args:False)
    monkeypatch.setattr(a,'verify_local_base_image',lambda *args:(_ for _ in ()).throw(AssertionError('No image service')))
    with pytest.raises(ValueError,match='current complete isolated'):a.LinearExportNode().execute(ctx)


def test_export_binds_the_same_private_audit_to_keyword_only_inspection(context,monkeypatch):
    ctx,session=context
    ctx.config['engine']={'image':'fixture-image'}
    ctx.data.update(source_id=session.guard()['workbook']['sha256'],revision_hash='normal-revision')
    expected_audit=ctx.revision_dir/'private/linear_harbor_worker_cap.json'
    operations=[]
    monkeypatch.setattr(a,'valid_linear_capital_recovery_witness',lambda *args:True)
    monkeypatch.setattr(a,'verify_local_base_image',lambda *args:{'fixture':True})
    def export(revision,destination,metadata,project_root,*,runtime_profile,audit_path):
        assert revision==ctx.revision_dir and audit_path==expected_audit
        operations.append(('export',destination,audit_path))
    def inspect(destination,*,audit_path):
        assert audit_path==expected_audit
        operations.append(('inspect',destination,audit_path))
        return {'task_id':ctx.task_id,'revision_hash':ctx.data['revision_hash']}
    monkeypatch.setattr(a,'export_resource_harbor',export)
    monkeypatch.setattr(a,'inspect_resource_export',inspect)
    result=a.LinearExportNode().execute(ctx)
    assert [row[0] for row in operations]==['export','inspect']
    assert operations[0][1:]==operations[1][1:]==(result['export_dir'],expected_audit)
    assert ctx.saved['linear_resource_export_binding.json']['revision_hash']=='normal-revision'


def test_repair_financial_content_holds_before_model_call(context):
    ctx,_=context
    ctx.data.update(repair_routes=[{'issue_id':'wrong-finance','route_class':'repair','problem_id':'Q04'}],
        diagnosis={'issues':[{'issue_id':'wrong-finance','certainty':'confirmed'}]})
    with pytest.raises(a.TaskRejected,match='newly admitted'):a.LinearRepairNode().execute(ctx)
