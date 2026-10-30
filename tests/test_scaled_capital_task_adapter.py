"""Prospective thirty-project adapter tests: no actual search, LO or model."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import openpyxl
import pytest
import yaml

from sheets_factory.core.node import TaskContext
from sheets_factory.task_adapters import scaled_capital_allocation as adapter
from sheets_factory.task_adapters.public_workbook_scope import reference,write_new
from sheets_factory.workbook.capital_allocation_scaled.excel import emit_capital_allocation_workbook
from sheets_factory.workbook.capital_allocation_scaled.catalog import build_spec,public_contract,contract_markdown
from sheets_factory.workbook.capital_allocation_scaled.spec import project_ids

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def financial_fixture(tmp_path_factory):
    folder=tmp_path_factory.mktemp('scaled-capital-offline30')
    public=build_spec('30-D01');ids=project_ids(30)
    book=openpyxl.Workbook();book.remove(book.active)
    binding=emit_capital_allocation_workbook(book,public,dict.fromkeys(ids,1))
    source=folder/'source.xlsx';book.save(source)
    nonempty_count=sum(cell.value is not None for sheet in book for cell in sheet._cells.values())
    book.close()
    contract=public_contract('30-D01')
    contract_ref=write_new(folder/'candidate_contract.json',contract)
    markdown=folder/'candidate_contract.md';markdown.write_text(contract_markdown(contract))
    manifest=write_new(folder/'source_manifest.json',{'fixture_only':'Not a financially admitted source'})
    proof={'workbook':reference(source),'source_manifest':manifest,'profile_id':'30-D01','project_count':30,
        'bindings':write_new(folder/'bindings.json',binding),'public_candidate_contract':contract_ref,
        'public_contract_artifacts':{'candidate_contract_markdown':reference(markdown)},
        'runtime_profile':reference(adapter.PROFILE)}
    return SimpleNamespace(folder=folder,public=public,binding=binding,source=source,proof=proof,
        nonempty_count=nonempty_count,markdown=markdown.read_text())


def install_dependencies(monkeypatch,proof):
    sessions=[]
    def verified(value,*,session=None):
        assert value==proof;sessions.append(session);return deepcopy(proof)
    stub=SimpleNamespace(__file__=__file__,verify_admitted_proof=verified)
    monkeypatch.setattr(adapter,'source_admission',lambda:stub)
    monkeypatch.setattr(adapter,'public_recovery',lambda:SimpleNamespace(__file__=__file__,
        validate_kernel_preparation=lambda value:{'explicit_mock_kernel_validation_boundary':True}))
    return sessions


def context(folder,case):
    return TaskContext(run_id='offline-only',task_id='scaled-fm30-fixture',mode='financial_modeling',
        source=case.source,directory=folder,config={adapter.SETTING:adapter.setting(),
            'construction':{'instruction_style':'business_brief','max_edit_count':{'financial_modeling':100000},
                'analysis_limits':{'max_profile_cells':500000,'max_dependency_closure_cells':500000,
                    'per_formula_reference_cells':50000,'max_mask_ranges':1024}},
            'recovery':{'compiler_backend':adapter.BACKEND,'replay_timeout_seconds':7200,
                'public_kernel_preparation':reference(__file__)},
            'diagnosis':{'reference_evidence_policy':'independent_public_recovery'}},
        audit=SimpleNamespace(emit=lambda *a,**kw:None),llm=None,engine=None,
        data={'baseline':case.source,'finance_evidence':{'financial_seed_verified':True,
            'financial_modeling_eligible':True,'source_manifest':case.proof['source_manifest'],
            'audited_source_binding':deepcopy(case.proof)}})


def test_complete_thirty_plan_targets_and_exact_public_contract_in_normal_instruction(financial_fixture,tmp_path,monkeypatch):
    case=financial_fixture;sessions=install_dependencies(monkeypatch,case.proof)
    ctx=context(tmp_path/'task',case);session=object();ctx.data['_scaled_admission_session']=session
    result=adapter.ScaledCapitalAllocationPlanNode().execute(ctx);plan=result['plan']
    assert sessions==[session]
    assert len(plan['edits'])==25541 and 'mask_ranges' not in plan
    targets=case.binding['financial_bindings']+case.binding['decision_bindings']
    assert {(e['sheet'],e['cell']) for e in plan['edits']}=={(e['sheet'],e['cell']) for e in targets}
    assert len(case.binding['financial_bindings'])==25511
    assert case.binding['formula_count']==77513 and case.nonempty_count<500000
    assert len(case.binding['decision_bindings'])==30 and len(case.binding['arithmetic_bindings'])==51972
    assert [e['project_id'] for e in case.binding['decision_bindings']]==list(project_ids(30))
    assert plan['family_adapter']['helper_values_are_protected'] is False
    assert plan['family_adapter']['full_workbook_D_required'] is True
    assert case.markdown in plan['public_instruction'] and len(case.markdown.encode())==13861
    assert str(case.proof['bindings']['path']) not in plan['public_instruction']
    ctx.data.update(result,input=case.source)
    (ctx.revision_dir/'public').mkdir(parents=True)
    instruction=adapter.normal.InstructionNode().execute(ctx)['instruction']
    assert case.markdown in instruction
    for key in ('annual_fields','project_fields','vintage_fields','summary_fields'):
        for name in public_contract('30-D01')[key]:assert '`'+name+'`' in instruction
    assert adapter.CLAUSES['financial_modeling'] in instruction
    assert result['source_assessment']['financial_evidence']==ctx.data['finance_evidence']
    assert '_scaled_admission_session' not in result['source_assessment']


@pytest.mark.parametrize('change',['short_decisions','reordered','protected_support','masked_helper','missing_financial','repeat_target','no_gold'])
def test_complete_target_scope_rejects_old18_or_any_reduced_inventory(financial_fixture,change):
    binding=deepcopy(financial_fixture.binding)
    if change=='short_decisions':binding['decision_bindings']=binding['decision_bindings'][:18]
    if change=='reordered':binding['decision_bindings'].reverse()
    if change=='protected_support':binding['arithmetic_bindings'][0]['value_protected']=True
    if change=='masked_helper':binding['arithmetic_bindings'][0]['target_eligible']=True
    if change=='missing_financial':binding['financial_bindings'].pop()
    if change=='repeat_target':binding['financial_bindings'][1]=deepcopy(binding['financial_bindings'][0])
    if change=='no_gold':binding['gold_plan_supplied']=False
    with pytest.raises(ValueError):adapter._targets(binding)


def mask_copy(source,destination,binding):
    book=openpyxl.load_workbook(source)
    for item in binding['financial_bindings']+binding['decision_bindings']:book[item['sheet']][item['cell']]=None
    book.save(destination);book.close()


def inject_cache(path,sheet,address,value):
    with ZipFile(path) as archive:
        members={item.filename:(item,archive.read(item.filename)) for item in archive.infolist()}
        name=adapter._paths(archive)[sheet]
    root=ET.fromstring(members[name][1])
    cell=next(c for c in root.findall('.//m:sheetData/m:row/m:c',adapter.NS) if c.get('r')==address)
    node=cell.find('m:v',adapter.NS)
    if node is None:node=ET.SubElement(cell,'{'+adapter.NS['m']+'}v')
    node.text=str(value)
    members[name]=(members[name][0],ET.tostring(root,encoding='utf-8'))
    with ZipFile(path,'w',ZIP_DEFLATED) as archive:
        for info,raw in members.values():archive.writestr(info,raw)


def test_actual_mask_copy_clears_all_plan_dependent_support_without_changing_definitions(financial_fixture,tmp_path):
    case=financial_fixture;draft=tmp_path/'masked.xlsx';mask_copy(case.source,draft,case.binding)
    receipt=adapter.audit_input_helper_caches(case.source,draft,case.binding)
    assert receipt['passed'] is True and receipt['masked_financial_and_decision_count']==25541
    assert receipt['provided_helper_formula_count']==51972
    expected=sum(e.get('plan_dependent') is True for e in case.binding['arithmetic_bindings'])
    assert expected>0 and receipt['plan_dependent_caches_cleared_count']==expected
    helper=next(e for e in case.binding['arithmetic_bindings'] if e.get('plan_dependent') is True)
    inject_cache(draft,helper['sheet'],helper['cell'],12345)
    with pytest.raises(ValueError,match='gold cached value'):
        adapter.audit_input_helper_caches(case.source,draft,case.binding)


def test_original_normal_bodies_and_indexed_streaming_globals_are_exact():
    adapter.validate_copies()
    from sheets_factory.workbook.profile_indexed import profile_workbook
    from sheets_factory.evaluation.streaming_delta import compare_workbooks
    assert adapter.profile_workbook is profile_workbook and adapter.compare_workbooks is compare_workbooks
    assert adapter.construction_contract is adapter.normal.construction_contract
    registry=yaml.safe_load((ROOT/'config/task_adapters/scaled_capital_allocation_nodes.yaml').read_text())['nodes']
    assert len(registry)==11
    assert registry['precheck']=='sheets_factory.nodes.construction:ControlsNode'
    assert registry['instruction']=='sheets_factory.nodes.construction:InstructionNode'
    assert registry['trajectory']=='sheets_factory.nodes.quality:TrajectoryNode'
    assert registry['independent_recovery'].endswith(':ScaledCapitalAllocationRecoveryNode')


@pytest.mark.parametrize('name,ordinary',[('Plan',adapter.normal.PlanNode),('Profile',adapter.normal.ProfileNode),
    ('Construct',adapter.normal.ConstructNode),('Diagnose',adapter.quality.DiagnoseNode),('Export',adapter.quality.ExportNode)])
def test_no_optin_retains_normal_nodes(monkeypatch,name,ordinary):
    monkeypatch.setattr(ordinary,'execute',lambda self,ctx:{'ordinary':name})
    assert getattr(adapter,'ScaledCapitalAllocation'+name+'Node')().execute(SimpleNamespace(config={}))=={'ordinary':name}


@pytest.mark.parametrize('change',['bool_version','18dimension','RAMv1','wrong_backend','wrong_timeout','missing_kernel'])
def test_explicit_resource_policy_and_recovery_cannot_fall_back(financial_fixture,tmp_path,monkeypatch,change):
    install_dependencies(monkeypatch,financial_fixture.proof);ctx=context(tmp_path/'task',financial_fixture)
    if change=='bool_version':ctx.config[adapter.SETTING]['version']=True
    if change=='18dimension':ctx.config[adapter.SETTING]['project_count']=18
    if change=='RAMv1':ctx.config[adapter.SETTING]=adapter.setting(ROOT/'config/runtime_profiles/entity_group_large_v1.yaml')
    if change=='wrong_backend':ctx.config['recovery']['compiler_backend']='capital_allocation_integer'
    if change=='wrong_timeout':ctx.config['recovery']['replay_timeout_seconds']=120
    if change=='missing_kernel':ctx.config['recovery'].pop('public_kernel_preparation')
    with pytest.raises(ValueError):adapter.enabled(ctx)


def test_private_source_or_session_not_accepted_as_public_contract(financial_fixture,tmp_path,monkeypatch):
    proof=deepcopy(financial_fixture.proof)
    public=public_contract('30-D01');public['blank_policy']='Infer missing fields yourself.'
    proof['public_candidate_contract']=write_new(tmp_path/'wrong_contract.json',public)
    with pytest.raises(ValueError,match='public candidate and field contract'):
        adapter._propose_from_checked_proof(financial_fixture.source,proof)


def test_export_cannot_trust_verified_flag_without_family_witness(monkeypatch):
    monkeypatch.setattr(adapter,'enabled',lambda ctx:True)
    monkeypatch.setattr(adapter,'context_proof',lambda ctx:{})
    monkeypatch.setattr(adapter,'valid_scaled_capital_recovery_witness',lambda *a:False)
    monkeypatch.setattr(adapter,'export_resource_harbor',lambda *a,**kw:pytest.fail('Unbound witness cannot export'))
    with pytest.raises(ValueError,match='strictly bound'):
        adapter.ScaledCapitalAllocationExportNode().execute(SimpleNamespace(data={'recovery':{'verified':True}}))


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
    result=adapter.ScaledCapitalAllocationDiagnoseNode().execute(ctx)['diagnosis']
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
    result=adapter.ScaledCapitalAllocationExportNode().execute(ctx)
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
    ctx.data.update(adapter.ScaledCapitalAllocationPlanNode().execute(ctx))
    called=[]
    def core(self,context):
        called.append(context)
        draft=context.revision_dir/'private/mutated_unrecalculated.xlsx';draft.parent.mkdir(parents=True,exist_ok=True)
        mask_copy(source,draft,case.binding)
        return {'input':draft,'goal':source,'delta':adapter.compare_workbooks(draft,source,source)}
    monkeypatch.setattr(adapter.ScaledCapitalAllocationConstructNode,'_execute_normal',core)
    # This explicit core boundary replaces a guarded static copy. Its original
    # AST is verified separately; no production source or computation is claimed.
    monkeypatch.setattr(adapter,'validate_copies',lambda:None)
    result=adapter.ScaledCapitalAllocationConstructNode().execute(ctx)
    assert called==[ctx]
    assert result['scaled_capital_input_scope']['changed_helper_count']==1
    assert result['scaled_capital_input_scope']['complete_required_D_count']==1
    assert result['scaled_capital_input_scope']['no_helper_values_excluded_from_required_D'] is True
    ctx.data['plan']['edits'].pop()
    with pytest.raises(ValueError,match='physical target scope changed'):
        adapter.ScaledCapitalAllocationConstructNode().execute(ctx)
    assert called==[ctx]


def test_actual_registry_loads_all_normal_routes_with_real_recovery_class(financial_fixture,tmp_path,monkeypatch):
    from sheets_factory.core.pipeline import BasePipeline
    install_dependencies(monkeypatch,financial_fixture.proof)
    ctx=context(tmp_path/'task',financial_fixture)
    config=deepcopy(ctx.config)
    config.update(project_root=str(ROOT),run_dir=str(tmp_path),
        pipeline={'node_registry':'config/task_adapters/scaled_capital_allocation_nodes.yaml'},
        run={'targets':{'financial_modeling':1,'debugging':0}})
    class Startup(BasePipeline):
        def run(self):return False
    pipeline=Startup(config)
    assert len(pipeline.node_registry)==11
    nodes={name:pipeline.load_node(name) for name in pipeline.node_registry}
    assert type(nodes['independent_recovery']).__name__=='ScaledCapitalAllocationRecoveryNode'
    assert nodes['independent_recovery'].__class__.__module__=='sheets_factory.workbook.capital_allocation_scaled.public_recovery'
    assert pipeline.templates['financial_modeling']['phases']['revision']==[
        'construct','instruction','precheck','independent_recovery','trajectory','diagnose']
