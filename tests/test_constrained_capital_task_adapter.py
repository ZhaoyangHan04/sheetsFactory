"""D02 adapter fixtures; no real source, optimisation, LO, model or Harbor."""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest
import yaml

from sheets_factory.core.node import TaskContext
from sheets_factory.task_adapters import constrained_capital_allocation as adapter
from sheets_factory.task_adapters import scaled_capital_allocation as original
from sheets_factory.pipelines import constrained_capital_admission as admission

ROOT=Path(__file__).resolve().parents[1]
definition=importlib.util.spec_from_file_location('_D02_shared_adapter_fixture',ROOT/'tests/test_scaled_capital_task_adapter.py')
old_tests=importlib.util.module_from_spec(definition);definition.loader.exec_module(old_tests)


@pytest.fixture(autouse=True)
def only_test_helper_binding(monkeypatch):
    # This is a test-helper variable, not the production D01 module namespace.
    monkeypatch.setattr(old_tests,'adapter',adapter)


@pytest.fixture(scope='module')
def financial_fixture(tmp_path_factory):
    """Full physical scope of =1 placeholders, not a financial source workbook."""
    folder=tmp_path_factory.mktemp('D02_scope_placeholders');book=openpyxl.Workbook()
    book.remove(book.active)
    money=book.create_sheet('Fixture money');decisions=book.create_sheet('Investment Plan');support=book.create_sheet('Exact Arithmetic')
    financial=[];choices=[];helpers=[]
    for i in range(25511):
        address='A'+str(i+1);money[address]='=1'
        financial.append({'sheet':money.title,'cell':address,'formula':'=1','target_eligible':True})
    for i in range(30):
        address='B'+str(i+3);decisions[address]='=1'
        choices.append({'sheet':decisions.title,'cell':address,'formula':'=1','project_id':'P'+str(i+1).zfill(2),'target_eligible':True})
    for i in range(51972):
        address='B'+str(i+1);support[address]='=1'
        helpers.append({'sheet':support.title,'cell':address,'formula':'=1','target_eligible':False,'value_protected':False,'plan_dependent':i<8772})
    source=folder/'scope_placeholder.xlsx';book.save(source);book.close()
    binding={'UNIT_FIXTURE_NOT_FINANCIAL_SOURCE':True,'financial_bindings':financial,'decision_bindings':choices,
        'arithmetic_bindings':helpers,'formula_count':77513,'gold_plan_supplied':True}
    contract=adapter.public_contract('30-D02');markdown=folder/'contract.md';markdown.write_text(adapter.contract_markdown(contract))
    proof={'workbook':adapter.reference(source),'source_manifest':old_tests.write_new(folder/'not_a_source_manifest.json',{'UNIT_FIXTURE':True}),
        'profile_id':'30-D02','project_count':30,'bindings':old_tests.write_new(folder/'bindings.json',binding),
        'public_candidate_contract':old_tests.write_new(folder/'contract.json',contract),
        'public_contract_artifacts':{'candidate_contract_markdown':adapter.reference(markdown)},
        'runtime_profile':adapter.reference(adapter.PROFILE)}
    return SimpleNamespace(folder=folder,binding=binding,source=source,proof=proof,markdown=markdown.read_text())


def dependencies(monkeypatch,proof):return old_tests.install_dependencies(monkeypatch,proof)
def context(path,case):return old_tests.context(path,case)


def test_complete_D02_targets_common_plan_contract_and_normal_instruction(financial_fixture,tmp_path,monkeypatch):
    case=financial_fixture;sessions=dependencies(monkeypatch,case.proof)
    ctx=context(tmp_path/'task',case);session=object();ctx.data['_constrained_admission_session']=session
    result=adapter.ConstrainedCapitalAllocationPlanNode().execute(ctx);plan=result['plan']
    assert sessions==[session] and len(plan['edits'])==25541 and 'mask_ranges' not in plan
    assert plan['family_adapter']['id']=='constrained_capital_common_plan_FM_v1'
    assert plan['family_adapter']['provided_arithmetic_count']==51972
    assert plan['family_adapter']['plan_dependent_support_count']==8772
    assert plan['family_adapter']['helper_values_are_protected'] is False and plan['family_adapter']['full_workbook_D_required'] is True
    assert {(r['sheet'],r['cell']) for r in plan['edits']}=={(r['sheet'],r['cell']) for r in case.binding['financial_bindings']+case.binding['decision_bindings']}
    assert case.markdown in plan['public_instruction'] and adapter.CLAUSES['financial_modeling'] in plan['public_instruction']
    ctx.data.update(result,input=case.source);(ctx.revision_dir/'public').mkdir(parents=True)
    instruction=adapter.normal.InstructionNode().execute(ctx)['instruction']
    assert case.markdown in instruction
    for field in adapter.public_contract('30-D02')['annual_fields']:assert '`'+field+'`' in instruction
    assert '_constrained_admission_session' not in result['source_assessment']


@pytest.mark.parametrize('change',['short_decisions','reordered','protected_support','masked_helper','missing_financial','repeat_target','no_gold'])
def test_full_target_scope_does_not_shrink_or_protect_helpers(financial_fixture,change):
    old_tests.test_complete_target_scope_rejects_old18_or_any_reduced_inventory(financial_fixture,change)


def test_all_helper_caches_physically_clear_and_cannot_contain_gold(financial_fixture,tmp_path):
    old_tests.test_actual_mask_copy_clears_all_plan_dependent_support_without_changing_definitions(financial_fixture,tmp_path)


@pytest.mark.parametrize('change',['bool_version','18dimension','RAMv1','wrong_backend','wrong_timeout','missing_kernel'])
def test_explicit_resources_public_recovery_and_complete_source_policy_remain_strict(financial_fixture,tmp_path,monkeypatch,change):
    old_tests.test_explicit_resource_policy_and_recovery_cannot_fall_back(financial_fixture,tmp_path,monkeypatch,change)


def test_D01_proof_is_not_relabelled_as_D02(financial_fixture,tmp_path,monkeypatch):
    proof=deepcopy(financial_fixture.proof);proof['profile_id']='30-D01'
    dependencies(monkeypatch,proof);case=SimpleNamespace(source=financial_fixture.source,proof=proof)
    with pytest.raises(ValueError,match='complete first-source'):adapter.context_proof(context(tmp_path/'task',case))


def test_whole_adapter_AST_diff_is_limited_to_declared_identity_and_import_bindings():
    transformed,counts=adapter.transformed_adapter_ast()
    expected=ast.parse(adapter.TEMPLATE_PATH.read_text())
    # Reverse exactly the declared edits and compare every other AST node.
    literals={v:k for k,v in adapter._LITERAL_BINDINGS.items()};names={v:k for k,v in adapter._NODE_BINDINGS.items()}
    class Undo(ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value) is str and node.value in literals:node.value=literals[node.value]
            return node
        def visit_Name(self,node):
            if node.id in names:node.id=names[node.id]
            return node
        def visit_ClassDef(self,node):
            if node.name in names:node.name=names[node.name]
            return self.generic_visit(node)
        def visit_ImportFrom(self,node):
            if node.module=='workbook.capital_allocation_scaled.constrained_catalog' and node.level==2:
                node.module='workbook.capital_allocation_scaled.catalog'
            return node
    assert ast.dump(Undo().visit(transformed))==ast.dump(expected)
    assert counts['30-D01']==4 and counts['class_names']==5 and counts['node_references']==3
    adapter.validate_copies()
    assert original.ADAPTER_ID=='scaled_capital_common_plan_FM_v1'
    assert original.setting()['profile_id']=='30-D01' and adapter.setting()['profile_id']=='30-D02'
    assert hashlib.sha256(adapter.TEMPLATE_PATH.read_bytes()).hexdigest()==adapter.TEMPLATE_SHA256
    assert hashlib.sha256(adapter.RECOVERY_TEMPLATE_PATH.read_bytes()).hexdigest()==adapter.RECOVERY_TEMPLATE_SHA256


def test_recovery_class_AST_changes_only_host_admission_session_and_class_identity():
    tree,counts=adapter.transformed_recovery_ast();node=tree.body[0]
    node.name='ScaledCapitalAllocationRecoveryNode'
    class Undo(ast.NodeTransformer):
        def visit_ImportFrom(self,n):
            if n.module=='pipelines.constrained_capital_admission' and n.level==3:n.module='pipelines.scaled_capital_admission'
            return n
        def visit_Constant(self,n):
            if n.value=='_constrained_admission_session':n.value='_scaled_admission_session'
            return n
    original_class=next(n for n in ast.parse(adapter.RECOVERY_TEMPLATE_PATH.read_text()).body
        if isinstance(n,ast.ClassDef) and n.name=='ScaledCapitalAllocationRecoveryNode')
    assert ast.dump(Undo().visit(node))==ast.dump(original_class)
    assert counts=={'admission_import':1,'session_key':1}
    old=adapter.public_recovery()
    assert adapter._recovery_namespace['_profile'] is old._profile
    assert adapter._recovery_namespace['compile_public_scaled_capital_recovery'] is old.compile_public_scaled_capital_recovery
    assert adapter._recovery_namespace['valid_scaled_capital_recovery_witness'] is old.valid_scaled_capital_recovery_witness


def test_new_recovery_node_calls_D02_admission_with_D02_live_session_before_any_backend(monkeypatch):
    class Boundary(Exception):pass
    calls=[];session=object();proof={'unit_fixture':True}
    def verify(value,*,session=None):calls.append((value,session));raise Boundary()
    monkeypatch.setattr(admission,'verify_admitted_proof',verify)
    monkeypatch.setitem(adapter._recovery_namespace,'validate_kernel_preparation',lambda value:{'unit_fixture':True})
    ctx=SimpleNamespace(config={adapter.SETTING:adapter.setting(),
        'diagnosis':{'reference_evidence_policy':'independent_public_recovery'},
        'recovery':{'compiler_backend':adapter.BACKEND,'replay_timeout_seconds':7200,'public_kernel_preparation':{'unit_fixture':True}}},
        data={'finance_evidence':{'audited_source_binding':proof},'_constrained_admission_session':session})
    with pytest.raises(Boundary):adapter.ConstrainedCapitalAllocationRecoveryNode().execute(ctx)
    assert calls==[(proof,session)]


@pytest.mark.parametrize('kind',['Plan','Profile','Construct','Diagnose','Export','Recovery'])
def test_no_optin_delegates_to_the_ordinary_nodes(monkeypatch,kind):
    old={'Plan':adapter.normal.PlanNode,'Profile':adapter.normal.ProfileNode,'Construct':adapter.normal.ConstructNode,
        'Diagnose':adapter.quality.DiagnoseNode,'Export':adapter.quality.ExportNode,'Recovery':adapter.public_recovery().RecoveryNode}[kind]
    monkeypatch.setattr(old,'execute',lambda self,ctx:{'normal':kind})
    assert getattr(adapter,'ConstrainedCapitalAllocation'+kind+'Node')().execute(SimpleNamespace(config={}))=={'normal':kind}


def test_registry_loads_eleven_real_nodes_and_preserves_normal_revision_pipeline(tmp_path):
    from sheets_factory.core.pipeline import BasePipeline
    registry='config/task_adapters/constrained_capital_allocation_nodes.yaml'
    nodes=yaml.safe_load((ROOT/registry).read_text())['nodes'];assert len(nodes)==11
    for key,expected in {'normalize':'sheets_factory.nodes.construction:NormalizeNode',
        'instruction':'sheets_factory.nodes.construction:InstructionNode','precheck':'sheets_factory.nodes.construction:ControlsNode',
        'trajectory':'sheets_factory.nodes.quality:TrajectoryNode','repair':'sheets_factory.nodes.quality:RepairNode'}.items():assert nodes[key]==expected
    class Startup(BasePipeline):
        def run(self):return False
    pipeline=Startup({'project_root':str(ROOT),'run_dir':str(tmp_path),'pipeline':{'node_registry':registry},
        'run':{'targets':{'financial_modeling':1,'debugging':0}}})
    loaded={key:pipeline.load_node(key) for key in pipeline.node_registry}
    assert type(loaded['independent_recovery']).__name__=='ConstrainedCapitalAllocationRecoveryNode'
    assert loaded['independent_recovery'].__class__.__module__==adapter.__name__
    assert pipeline.templates['financial_modeling']['phases']['revision']==[
        'construct','instruction','precheck','independent_recovery','trajectory','diagnose']


def test_setting_binds_current_new_implementation_and_both_unchanged_templates():
    value=adapter.setting();assert value['adapter']=='constrained_capital_common_plan_FM_v1'
    assert value['implementation']==adapter.reference(adapter.__file__)
    assert value['source_admission']==adapter.reference(admission.__file__)
    assert value['constrained_template_binding']['ordinary_gates_unchanged'] is True
    assert value['constrained_template_binding']['adapter_template']['sha256']==adapter.TEMPLATE_SHA256
    assert value['constrained_template_binding']['recovery_template']['sha256']==adapter.RECOVERY_TEMPLATE_SHA256
    assert adapter.validate_setting(value)==value


# The following runtime boundary fixtures mirror the frozen ordinary adapter
# tests with explicit new class names. All backends remain mocked.
reference=adapter.reference
install_dependencies=dependencies
mask_copy=old_tests.mask_copy
inject_cache=old_tests.inject_cache


def test_export_cannot_trust_verified_flag_without_family_witness(monkeypatch):
    monkeypatch.setattr(adapter,'enabled',lambda ctx:True)
    monkeypatch.setattr(adapter,'context_proof',lambda ctx:{})
    monkeypatch.setattr(adapter,'valid_scaled_capital_recovery_witness',lambda *a:False)
    monkeypatch.setattr(adapter,'export_resource_harbor',lambda *a,**kw:pytest.fail('Unbound witness cannot export'))
    with pytest.raises(ValueError,match='strictly bound'):
        adapter.ConstrainedCapitalAllocationExportNode().execute(SimpleNamespace(data={'recovery':{'verified':True}}))

@pytest.mark.parametrize('valid',[False,True])
def test_all_twelve_reviews_retain_strict_family_recovery_gate(tmp_path,monkeypatch,valid):
    checks=[f'Q{i:02d}' for i in range(1,13)]
    class Runner:
        catalog={}
        def __init__(self,*args):pass
        def diagnose(self,bundle,traces,controls,review,config,**kwargs):
            assert bundle['private']['source_assessment']=={'complete':'private source proof'}
            assert 'source_assessment' not in bundle['public']
            return {'issues':[],'routes':[],'releasable':True,'enabled_check_ids':checks,
                'assessments':{q:{'state':'clear','reason':'Explicit mocked backend boundary'} for q in checks},
                'coverage':{},'scope':'all_twelve_offline_boundary'}
        def resolve(self,config):return {'difficulty_deferred':False}
    monkeypatch.setattr(adapter,'enabled',lambda ctx:True)
    monkeypatch.setattr(adapter,'context_proof',lambda ctx:{})
    monkeypatch.setattr(adapter,'valid_scaled_capital_recovery_witness',lambda *args:valid)
    monkeypatch.setattr(adapter,'DiagnosisRunner',Runner)
    monkeypatch.setattr(adapter,'route_issues',lambda issues,*args:[{'issue_id':i['issue_id']} for i in issues])
    monkeypatch.setattr(adapter,'prompt',lambda *args:'Offline prompt')
    monkeypatch.setattr(adapter,'candidate_difficulty_context',lambda config:{})
    source=tmp_path/'input.fixture';source.write_bytes(b'Public fixture only')
    profile={'sheet_count':15,'nonempty_sheet_count':15,'formula_count':77513,'errors':[],
        'external_references':[],'sheets':[]}
    ctx=SimpleNamespace(config={'agents':{},'project_root':str(ROOT),'diagnosis':{}},
        task_id='offline-fm30',mode='financial_modeling',revision=0,
        audit=SimpleNamespace(task=lambda *a,**kw:None,emit=lambda *a,**kw:None),
        llm=SimpleNamespace(model='No model launched'),save=lambda *a,**kw:None,
        data={'instruction':'Public fixture','public_profile':profile,'profile':profile,'input':source,'goal':source,
            'revision_hash':'fixture','plan':{'edits':[],'public_rules':['Public contract']},'delta':{},
            'construction_validation':{},'root_impacts':[],'controls':{},'traces':[],'engine_report':{},
            'source_assessment':{'complete':'private source proof'},'recovery':{'verified':True}})
    result=adapter.ConstrainedCapitalAllocationDiagnoseNode().execute(ctx)['diagnosis']
    assert set(result['assessments'])==set(checks)
    assert result['mandatory_gates']['independent_recovery']['passed'] is valid
    assert result['releasable'] is valid

def test_export_records_actual_base_image_before_resource_export(tmp_path,monkeypatch):
    events=[];saved=[]
    monkeypatch.setattr(adapter,'enabled',lambda ctx:True)
    monkeypatch.setattr(adapter,'context_proof',lambda ctx:{})
    monkeypatch.setattr(adapter,'valid_scaled_capital_recovery_witness',lambda *args:True)
    actual={'actual_local_image_verified':True,'actual_container_resources_verified':False}
    def base(path):events.append(('actual_tag',path));return actual
    def export(*args,**kwargs):events.append(('export',kwargs['runtime_profile']))
    monkeypatch.setattr(adapter,'verify_local_base_image',base)
    monkeypatch.setattr(adapter,'export_resource_harbor',export)
    monkeypatch.setattr(adapter,'inspect_resource_export',lambda path:{'task_id':'offline-fm30','revision':0,'revision_hash':'current'})
    task=tmp_path/'task';task.mkdir()
    ctx=SimpleNamespace(config={'project_root':str(ROOT),'run_dir':str(tmp_path),adapter.SETTING:{'runtime_profile':reference(adapter.PROFILE)},
        'engine':{'image':'sheetsfactory-lo:24.2-iterative-openpyxl315-v1'}},
        source=tmp_path/'source.fixture',directory=task,revision_dir=task/'revisions/000',
        task_id='offline-fm30',revision=0,mode='financial_modeling',data={'source_id':'a'*64,'revision_hash':'current','recovery':{'verified':True}},
        save=lambda name,value:saved.append((name,value)))
    result=adapter.ConstrainedCapitalAllocationExportNode().execute(ctx)
    assert [event[0] for event in events]==['actual_tag','export']
    assert events[0][1]==events[1][1]==str(adapter.PROFILE)
    assert saved==[('scaled_capital_actual_local_base_image.json',actual)]
    assert result['export_dir']==tmp_path/'SpreadsheetEval/offline-fm30'

def test_construct_postcheck_preserves_complete_D_including_unmasked_support(financial_fixture,tmp_path,monkeypatch):
    """Core body is isolated here; this is not an actual LO/source witness."""
    import shutil
    case=financial_fixture
    source=tmp_path/'source.xlsx';shutil.copy2(case.source,source)
    helper=next(e for e in case.binding['arithmetic_bindings'] if e.get('plan_dependent') is True)
    inject_cache(source,helper['sheet'],helper['cell'],2)
    proof=deepcopy(case.proof);proof['workbook']=reference(source)
    local=SimpleNamespace(source=source,proof=proof)
    install_dependencies(monkeypatch,proof)
    ctx=context(tmp_path/'task',local)
    ctx.data.update(adapter.ConstrainedCapitalAllocationPlanNode().execute(ctx))
    called=[]
    def core(self,context):
        called.append(context)
        draft=context.revision_dir/'private/mutated_unrecalculated.xlsx';draft.parent.mkdir(parents=True,exist_ok=True)
        mask_copy(source,draft,case.binding)
        return {'input':draft,'goal':source,'delta':adapter.compare_workbooks(draft,source,source)}
    monkeypatch.setattr(adapter.ConstrainedCapitalAllocationConstructNode,'_execute_normal',core)
    # This explicit core boundary replaces a guarded static copy. Its original
    # AST is verified separately; no production source or computation is claimed.
    monkeypatch.setattr(adapter,'validate_copies',lambda:None)
    result=adapter.ConstrainedCapitalAllocationConstructNode().execute(ctx)
    assert called==[ctx]
    assert result['scaled_capital_input_scope']['changed_helper_count']==1
    assert result['scaled_capital_input_scope']['complete_required_D_count']==1
    assert result['scaled_capital_input_scope']['no_helper_values_excluded_from_required_D'] is True
    ctx.data['plan']['edits'].pop()
    with pytest.raises(ValueError,match='physical target scope changed'):
        adapter.ConstrainedCapitalAllocationConstructNode().execute(ctx)
    assert called==[ctx]
