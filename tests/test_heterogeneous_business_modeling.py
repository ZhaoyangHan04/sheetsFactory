"""Toy/fake-boundary tests only: no real admission, model, Docker or LO."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest
import yaml

from sheets_factory.task_adapters import heterogeneous_business_modeling as family
from sheets_factory.task_adapters import heterogeneous_financial_view as writer
from sheets_factory.pipelines import heterogeneous_business_quality as pipeline
from sheets_factory.core.node import TaskContext
from sheets_factory.core.audit import AuditStore
from sheets_factory.nodes import construction, quality


class FakeEngine:
    def __init__(self): self.calls = []
    def metadata(self): return {'backend':'hand_fixture_fake_engine','actual_LO_calls':0}
    def recalculate(self, source, destination):
        self.calls.append((Path(source),Path(destination)))
        book = openpyxl.load_workbook(source)
        for sheet in book:
            for row in sheet:
                for cell in row:
                    if cell.data_type == 'f':
                        assert cell.value.startswith('=IF(TRUE(),')
                        value = float(cell.value[len('=IF(TRUE(),'):].split(',',1)[0])
                        cell.value = int(value) if value.is_integer() else value
        book.save(destination);book.close();return Path(destination)


def fixture(tmp_path, monkeypatch):
    # An explicit dependency-injection boundary. This object is not an actual
    # ProjectionAdmission and is never persisted as a real source certificate.
    positions = []
    for i, value in enumerate([123.45,0,1,None,0,4],4):
        positions.append({'sheet':'S01 Statements','cell':'E'+str(i),'descriptor_row':i,
            'descriptors':['E01','Statements','Hand account '+str(i),'GBP'], 'number_format':'0.00',
            'reference_value':writer._typed(value),'source':{'sheet':'Native Report','cell':'D'+str(i),
                'expected_path':['scenarios','S01','entities','E01','monthly',0,'revenue'],
                'kind':'money_pence','worksheet_scale':100,'expression':['ref','Native Calc','B'+str(i)]}})
    plan = {'months':['2027-01-01'],'scenario_ids':['S01'],
        'sheet_order':['Contract Notes','Calendar','Entity Policies','S01 Statements'],
        'provided_cells':[{'sheet':name,'cell':'A1','value':writer._typed(name+' provided'),'number_format':'General'}
            for name in ['Contract Notes','Calendar','Entity Policies']],
        'forecast_targets':positions,'declared_slot_count':len(positions),'original_brief':'Complete all labelled business forecasts.',
        'plan_sha256':'1'*64,'hand_fixture_not_actual_admission':True}
    files = {}
    for masked,name in [(True,'input'),(False,'goal')]:
        book = writer._book_from_plan(plan,masked=masked);p=tmp_path/(name+'.xlsx')
        book.save(p);book.close();files[name]=writer.reference(p)
    native = tmp_path/'native.xlsx'; b=openpyxl.Workbook();b.active['A1']='Hand native source';b.save(native);b.close()
    proof={'native_source':writer.reference(native),'workbook':writer.reference(native),'source_manifest':{'hand_fixture':True},
        'native_source_admission':{'financial_audits':[]},'runtime_profile':writer.reference(family.PROFILE),
        'view_plan_sha256':plan['plan_sha256'],'view_version':3,'actual_projection_engine_calls':[],
        'projection_manifest':{'hand_fixture':True},'declared_business_slots':6,
        'full_D_count':5,**files}
    admission=SimpleNamespace(plan=plan,proof=proof,guard=lambda:proof)
    config={'project_root':str(family.ROOT),'run_dir':str(tmp_path/'run'),
        'construction':{'analysis_limits':{'max_profile_cells':500000}},'native_risks':{}}
    audit=AuditStore(tmp_path/'audit',{'id':'fixture'})
    ctx=TaskContext('fixture','fm-fixture','financial_modeling',native,tmp_path/'task',config,audit,None,FakeEngine())
    ctx.data['_heterogeneous_admission']=admission
    monkeypatch.setattr(family,'enabled',lambda _:True)
    monkeypatch.setattr(family,'context_proof',lambda _:proof)
    return ctx,admission,audit


def test_default_off_delegates_original_nodes(monkeypatch):
    ctx=SimpleNamespace(config={},mode='financial_modeling')
    pairs=[(family.HeterogeneousBusinessNormalizeNode,construction.NormalizeNode),
        (family.HeterogeneousBusinessProfileNode,construction.ProfileNode),
        (family.HeterogeneousBusinessPlanNode,construction.PlanNode),
        (family.HeterogeneousBusinessConstructNode,construction.ConstructNode),
        (family.HeterogeneousBusinessInstructionNode,construction.InstructionNode),
        (family.HeterogeneousBusinessControlsNode,construction.ControlsNode),
        (family.HeterogeneousBusinessDiagnoseNode,quality.DiagnoseNode),
        (family.HeterogeneousBusinessExportNode,quality.ExportNode)]
    for child,parent in pairs:
        monkeypatch.setattr(parent,'execute',lambda self,ctx:{'legacy':True})
        assert child().execute(ctx)=={'legacy':True}


def test_setting_and_registry_all_normal_routes_are_explicit():
    value=family.setting();assert value['enabled'] is True and value['view_version']==3
    assert family.validate_setting(value)==value
    nodes=yaml.safe_load(family.REGISTRY.read_text())['nodes']
    assert len(nodes)==11 and nodes['trajectory']=='sheets_factory.nodes.quality:TrajectoryNode'
    assert nodes['repair']=='sheets_factory.nodes.quality:RepairNode'
    assert nodes['independent_recovery'].endswith(':HeterogeneousBusinessRecoveryNode')
    for node in nodes.values():
        module,cls=node.split(':');assert getattr(__import__(module,fromlist=[cls]),cls)


@pytest.mark.parametrize('change',['bool_version','bad_view','bad_scope','profile'])
def test_changed_family_setting_rejected(change):
    setting=family.setting()
    if change=='bool_version':setting['version']=True
    elif change=='bad_view':setting['view_version']=2
    elif change=='bad_scope':setting['excluded_entity_fields'].append('cash_close')
    else:setting['runtime_profile']['sha256']='0'*64
    with pytest.raises(writer.ViewError):family.validate_setting(setting)


def test_real_TaskContext_runs_literal_normalize_profile_plan_construct_instruction(tmp_path,monkeypatch):
    ctx,admission,audit=fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(family,'native_dependency_provenance',lambda _:{'hand_fixture_not_native_graph_proof':True})
    try:
        for cls in [family.HeterogeneousBusinessNormalizeNode,family.HeterogeneousBusinessProfileNode,
                family.HeterogeneousBusinessPlanNode,family.HeterogeneousBusinessConstructNode,
                family.HeterogeneousBusinessInstructionNode]:cls().run(ctx)
        assert ctx.data['profile']['formula_count']==0
        assert ctx.data['source_id']==admission.proof['native_source']['sha256']
        assert writer.reference(ctx.data['baseline'])['sha256']==admission.proof['goal']['sha256']
        assert ctx.data['construction_validation']['before_must_be_formula'] is False
        assert ctx.data['delta']['expected_change_count']==5
        assert ctx.data['instruction']==admission.plan['original_brief']
        assert 'Missing formula' not in ctx.data['instruction']
        assert len(ctx.data['plan']['edits'])==5 and any(e['before']==0 for e in ctx.data['plan']['edits'])
        assert not ctx.engine.calls
        assert all(n['status']=='completed' for n in audit.snapshot()['nodes'])
    finally:audit.db.close()


def test_all_five_literal_controls_with_fake_engine_boundary(tmp_path,monkeypatch):
    ctx,admission,audit=fixture(tmp_path,monkeypatch)
    try:
        ctx.data.update(input=Path(admission.proof['input']['path']),goal=Path(admission.proof['goal']['path']),
            plan=family.canonical_plan(admission))
        result=family.HeterogeneousBusinessControlsNode().execute(ctx)
        assert {n:r['reward'] for n,r in result['controls'].items()}==pipeline.REWARDS
        assert len(ctx.engine.calls)==3
        assert not any(isinstance(e['before'],str) for e in ctx.data['plan']['edits'])
    finally:audit.db.close()


@pytest.mark.parametrize('mutation',['target','before','scope','raw_input','reference_value'])
def test_literal_plan_or_workbook_tamper_fail_closed(tmp_path,monkeypatch,mutation):
    ctx,admission,audit=fixture(tmp_path,monkeypatch)
    try:
        ctx.data.update(baseline=Path(admission.proof['goal']['path']),source_id=admission.proof['native_source']['sha256'],
            engine_report={'engine':ctx.engine.metadata()},plan=family.canonical_plan(admission))
        if mutation=='target':ctx.data['plan']['edits'][0]['cell']='Z9'
        elif mutation=='before':ctx.data['plan']['edits'][0]['before']=999
        elif mutation=='scope':ctx.data['plan']['family_adapter']['declared_business_slots']=1
        else:
            role='input' if mutation=='raw_input' else 'goal'
            path=Path(admission.proof[role]['path']);book=openpyxl.load_workbook(path)
            book['Calendar']['A1']='Changed' if role=='input' else 'Reference changed';book.save(path);book.close()
        with pytest.raises(writer.ViewError):family.HeterogeneousBusinessConstructNode().execute(ctx)
    finally:audit.db.close()


def test_normal_diagnosis_AST_has_only_strict_family_witness_substitution():
    family.validate_diagnose_copy()


def test_context_proof_rejects_persisted_boolean_instead_of_process_admission():
    ctx=SimpleNamespace(config={family.SETTING:family.setting()},mode='financial_modeling',data={'_heterogeneous_admission':{'verified':True}})
    with pytest.raises(writer.ViewError,match='opaque'):family.context_proof(ctx)


def test_native_dependency_provenance_follows_complete_actual_static_refs(tmp_path):
    rows={'arithmetic_bindings':[{'sheet':'A','cell':'A1','expression':"'B'!$B$1"}],
        'financial_bindings':[],'input_bindings':[{'sheet':'B','cell':'B1','value':1}],'literal_bindings':[]}
    path=tmp_path/'hand_graph.json';path.write_text(json.dumps(rows))
    admission=SimpleNamespace(proof={'native_source_admission':{'bindings':writer.reference(path),'financial_audits':[]}},
        plan={'forecast_targets':[{'source':{'sheet':'A','cell':'A1'}}]})
    result=family.native_dependency_provenance(admission)
    assert result['complete_dependency_closure_cells']==2 and result['native_cross_sheet_edges']==1
    rows['input_bindings']=[];path.write_text(json.dumps(rows))
    with pytest.raises(writer.ViewError,match='unresolved'):family.native_dependency_provenance(admission)


def test_native_dependency_graph_from_real_tiny_emitter_and_specializer(tmp_path):
    # Actual emitter/specializer bytes and reference grammar, without a source
    # certificate, cached values, financial simulation, Docker or LO execution.
    from test_heterogeneous_specialized_excel import toy
    from sheets_factory.workbook.heterogeneous_contracts import excel, policy_specialization
    book = openpyxl.Workbook()
    original = excel.emit_heterogeneous_workbook(book,toy(('BULLET_MONTHLY',)))
    try:
        for rows in (original, policy_specialization.specialize_bindings(original,enabled=True)[0]):
            path=tmp_path/'actual_emitter_bindings.json';path.write_text(json.dumps(rows))
            roots=[{'source':{'sheet':r['sheet'],'cell':r['cell']}} for r in rows['financial_bindings']]
            admission=SimpleNamespace(proof={'native_source_admission':{
                'bindings':writer.reference(path),'financial_audits':[]}},plan={'forecast_targets':roots})
            result=family.native_dependency_provenance(admission)
            assert result['native_cross_sheet_edges'] > 0
            assert result['complete_dependency_closure_cells'] > len(roots)
            assert result['complete_selected_native_alias_count']==len(roots)
            assert result['projected_formula_count']==0
            # An emitted alias with a syntactically valid, unbound reference
            # must fail closed, even if the rest of the graph is valid.
            rows['financial_bindings'][0]['expression']="'Unbound native sheet'!$B$1"
            rows['arithmetic_bindings']=[r for r in rows['arithmetic_bindings']
                if (r['sheet'],r['cell']) != (rows['financial_bindings'][0]['sheet'],rows['financial_bindings'][0]['cell'])]
            path.write_text(json.dumps(rows))
            with pytest.raises(writer.ViewError,match='unresolved'):
                family.native_dependency_provenance(admission)
    finally:book.close()


@pytest.mark.parametrize('kind',['completed_offline_probe','source_verified','prequality_heterogeneous_business_view_v3_development'])
def test_manifest_boolean_or_incomplete_receipt_never_admits(tmp_path,kind):
    path=tmp_path/'bad.json';path.write_text(json.dumps({'kind':kind,'version':1,'passed':True,'actual_LO_calls':7}))
    with pytest.raises((writer.ViewError,KeyError)):pipeline.ProjectionAdmission(path)


def test_entry_prepare_only_and_run_guards_without_services(tmp_path,monkeypatch):
    path=family.ROOT/'scripts/run_heterogeneous_business_quality.py'
    definition=importlib.util.spec_from_file_location('business_entry_unit',path)
    entry=importlib.util.module_from_spec(definition);definition.loader.exec_module(entry)
    monkeypatch.setattr(entry,'execute_prepared',lambda *a,**k:pytest.fail('Unexpected services'))
    monkeypatch.setattr(entry,'prepare',lambda *a,**k:{'fixture_only':True})
    assert entry.main(['--projection-manifest','fixture.json','--base-run','fixture','--output',str(tmp_path/'new')])==0
    with pytest.raises(writer.ViewError):entry.main(['--run','--projection-manifest','fixture.json','--base-run','fixture','--output',str(tmp_path/'new')])


def test_ordinary_Factory_process_and_quota_methods_are_inherited():
    from sheets_factory.pipelines.factory import FactoryPipeline
    assert pipeline.HeterogeneousBusinessFactory.process_task is FactoryPipeline.process_task
    assert pipeline.HeterogeneousBusinessFactory._execute_context is FactoryPipeline._execute_context
    assert pipeline.HeterogeneousBusinessFactory.reserve is FactoryPipeline.reserve


def test_preharbor_rechecks_native_aliases_only_for_actual_projected_D(tmp_path,monkeypatch):
    ctx,admission,audit=fixture(tmp_path,monkeypatch)
    from sheets_factory.pipelines.factory import FactoryPipeline
    ordinary={'blocking':False,'state':'clear','issues':[],'evidence_requests':[],
        'receipt_id':'ordinary','receipt_path':'ordinary-receipt','checked_at':'original'}
    monkeypatch.setattr(FactoryPipeline,'_preharbor_native_risks',lambda *args:deepcopy(ordinary))
    captured={}
    def guard(cells,*args,**kwargs):
        captured['cells']=cells
        return {'blocking':True,'state':'flagged','issues':[{'code':'Q09','source':'actual native alias'}],'evidence_requests':[]}
    monkeypatch.setattr(pipeline,'evaluate_native_risk_guard',guard)
    factory=object.__new__(pipeline.HeterogeneousBusinessFactory)
    factory.config=ctx.config;factory.admission=admission;factory.audit=audit
    try:
        result=factory._preharbor_native_risks({'id':ctx.task_id}, {'revision_hash':'fixture'})
        assert result['blocking'] and result['state']=='flagged' and len(result['issues'])==1
        assert len(captured['cells'])==5 and 'Native Report!D7' not in captured['cells']
        saved=json.loads(Path(result['receipt_path']).read_text())
        assert saved['projected_D_guard_receipt']==ordinary
        assert 'receipt_id' not in saved and result['receipt_id']!='ordinary'
        assert writer.reference(result['receipt_path'])['sha256']==result['receipt_sha256']
    finally:audit.db.close()


def test_prepare_validate_and_real_factory_loader_with_explicit_fake_admission(tmp_path,monkeypatch):
    ctx,hand,audit=fixture(tmp_path,monkeypatch)
    # Only the expensive source-admission boundary is replaced. All entry,
    # configuration, registry, real Factory construction and loading run here.
    class HandAdmission:
        def __init__(self,ref):
            self.plan=deepcopy(hand.plan);self.proof=deepcopy(hand.proof)
            self.proof['projection_manifest']=writer.reference(ref['path'] if isinstance(ref,dict) else ref)
        def guard(self):
            for key in ('native_source','input','goal','runtime_profile','projection_manifest'):
                assert writer.reference(self.proof[key]['path'])==self.proof[key]
            return self.proof
    monkeypatch.setattr(pipeline,'ProjectionAdmission',HandAdmission)
    path=family.ROOT/'scripts/run_heterogeneous_business_quality.py'
    definition=importlib.util.spec_from_file_location('business_entry_actual_route_unit',path)
    entry=importlib.util.module_from_spec(definition);definition.loader.exec_module(entry)
    source=tmp_path/'projection.fixture.json';source.write_text('{"fake_admission_boundary":true}')
    base=tmp_path/'base';base.mkdir()
    (base/'preflight_manifest.json').write_text('{"recipe_sha256":{}}')
    from test_entity_group_quality_entry import base_configuration
    original=base_configuration()
    (base/'resolved_config.yaml').write_text(yaml.safe_dump(original))
    output=tmp_path/'new_quality'
    try:
        frozen_ref=entry.prepare(source,base,output)
        frozen,config,admission=entry.validate_prepared(output)
        assert writer.reference(output/'preflight_manifest.json')==frozen_ref
        assert frozen['actual_models']==frozen['actual_LO_calls']==0
        assert frozen['existing_development_score_transferred'] is False
        assert not (output/'run.sqlite').exists()
        assert config['run']['targets']==pipeline.TARGETS
        assert all(config['run'][key]==original['run'][key] for key in entry.PROTECTED_BUDGETS)
        assert config['host_runtime']['temporary_directory']==str(output/'temporary')
        assert config['prompt_overrides']['diagnosis.md']=='diagnosis_business.md'
        business_prompt=family.ROOT/'prompts/diagnosis_business.md'
        assert frozen['recipe_sha256'][str(business_prompt)]==writer.reference(business_prompt)['sha256']
        factory=pipeline.HeterogeneousBusinessFactory(config,SimpleNamespace(update_run=lambda **kwargs:None),None,None,admission=admission)
        seeds=factory.load_seeds()
        assert seeds[0]['sha256']==hand.proof['native_source']['sha256']
        assert seeds[0]['modes']==['financial_modeling'] and len(factory.node_registry)==11
        assert factory.templates['financial_modeling']['phases']['revision']==[
            'construct','instruction','precheck','independent_recovery','trajectory','diagnose']
        for node in factory.node_registry:factory.load_node(node)
        # Config Boolean counters do not satisfy frozen integer budgets.
        changed=deepcopy(config);changed['run']['max_sources']=True
        with pytest.raises(writer.ViewError):pipeline.validate_configuration(changed)
    finally:audit.db.close()
