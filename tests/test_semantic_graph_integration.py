"""Separate V3-provider routing keeps actual source validation and normal phases."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest
import yaml

from sheets_factory.pipelines import semantic_graph_admission as admission
from sheets_factory.pipelines.semantic_graph_factory import SemanticGraphFactory
from sheets_factory.pipelines.factory import FactoryPipeline
from sheets_factory.nodes.scc_activity import SCCConstructNode
from sheets_factory.core.node import TaskRejected
from sheets_factory.task_adapters.composite_semantic_family_v3 import compile_semantic_report
from sheets_factory.task_adapters.lease_family import ref
from sheets_factory.task_adapters.public_input_priority import canonical,write
from sheets_factory.task_adapters.public_workbook_scope import CLAUSES

ROOT=Path(__file__).resolve().parents[1]
REGISTRY=ROOT/'config/task_adapters/semantic_graph_nodes_v3.yaml'


@pytest.fixture
def fixture_binding(tmp_path,monkeypatch):
    # Unit routing fixture only: financial auditing is separately delegated and
    # asserted below. This fixture is never a production selected seed.
    book=openpyxl.Workbook();s=book.active;s.title='Operating Operations'
    s['A3']='annual cash flow';s['C3']='=SUM(C4:D4)';s['C4']=10;s['D4']=20
    source=tmp_path/'source.xlsx';book.save(source);book.close()
    scope={'schema_version':2,'adapter':admission.SOURCE_ADAPTER,'family_count':1,'formula_slots':1,
        'prospective_nonzero_roots':1,'source':ref(source),'families':[{'algorithm':'operating',
            'sheet':'Operating Operations','row':3,'field':'annual cash flow','role':'aggregate',
            'cells':[{'cell':'C3','source_kind':'finite_numeric_nonzero',
                      'formula_sha256':hashlib.sha256(b'=SUM(C4:D4)').hexdigest()}]}]}
    scope_path=tmp_path/'scope.json';write(scope_path,scope)
    policy={'adapter':admission.PROVIDER_ID,'seed':19,'max_roots':100000,'compound_nonalias_definitions':True}
    policy_path=tmp_path/'policy.json';write(policy_path,policy)
    implementation=ref(ROOT/'src/sheets_factory/task_adapters/composite_semantic_family_v3.py')
    report=compile_semantic_report(source,scope,policy)
    report['mutation_provider_recipe']={'mutation_provider':implementation}
    report_path=tmp_path/'report.json';write(report_path,report)
    dummy=tmp_path/'financial.json';write(dummy,{'unit_fixture_only':True})
    provider={'id':admission.PROVIDER_ID,'implementation':implementation,'policy':ref(policy_path),
        'policy_sha256':canonical(policy),'offline_compilation':ref(report_path)}
    binding={'kind':'financial_source_with_separate_semantic_mutation_provider',
        'source_presentation_adapter':admission.SOURCE_ADAPTER,'source':ref(source),
        'source_manifest':ref(dummy),'financial_admission':ref(dummy),'scope_inventory':ref(scope_path),
        'public_input_priority_audit':ref(dummy),'mutation_provider':provider,'root_count':1,
        'edits_sha256':report['edits_sha256']}
    monkeypatch.setattr(admission,'validate_financial_admission',lambda b:{'separate_actual_validation_stub':True})
    monkeypatch.setattr(admission,'validate_presented_numeric_timing',lambda r,b:None)
    manifest=tmp_path/'bindings.json';write(manifest,{'kind':'semantic_graph_v3_source_and_provider_bindings',
        'version':1,'sources':{binding['source']['sha256']:binding}})
    setting={'enabled':True,'version':1,'contract':admission.JOINT_METHOD,
             'nodes':admission.node_binding(),'bindings':ref(manifest)}
    return binding,setting,report


def context_for(tmp_path,binding,setting):
    saved={}
    def save(name,value):saved[name]=deepcopy(value);return tmp_path/name
    return SimpleNamespace(source=Path(binding['source']['path']),mode='debugging',revision=0,
        config={admission.SETTING:setting},data={'baseline':Path(binding['source']['path']),
            'finance_evidence':{'mutation_provider':binding['mutation_provider'],
                'full_graph_financial_admission':binding['financial_admission'],
                'source_presentation_adapter':admission.SOURCE_ADAPTER,
                'semantic_graph_binding':binding}},save=save,saved=saved)


def test_provider_validation_delegates_financial_source_and_timing_without_relabelling(fixture_binding,monkeypatch):
    binding,setting,report=fixture_binding;seen=[]
    monkeypatch.setattr(admission,'validate_financial_admission',lambda b:seen.append(('financial',b['financial_admission'])))
    monkeypatch.setattr(admission,'validate_presented_numeric_timing',lambda r,b:seen.append(('timing',r)))
    before=deepcopy(binding)
    compiler,policy=admission.validate_source_and_provider(binding)
    assert compiler.ADAPTER_ID==admission.PROVIDER_ID and policy['adapter']==admission.PROVIDER_ID
    assert seen==[('financial',binding['financial_admission']),('timing',binding['public_input_priority_audit'])]
    assert binding==before and binding['source_presentation_adapter']!=binding['mutation_provider']['id']


@pytest.mark.parametrize('problem',['provider_id','source_id','edits_hash','root_count','report_hash'])
def test_provider_binding_fails_closed_on_identity_or_complete_scope_mismatch(fixture_binding,problem):
    binding,_,_=fixture_binding;broken=deepcopy(binding)
    if problem=='provider_id':broken['mutation_provider']['id']=admission.SOURCE_ADAPTER
    if problem=='source_id':broken['source_presentation_adapter']=admission.PROVIDER_ID
    if problem=='edits_hash':broken['edits_sha256']='0'*64
    if problem=='root_count':broken['root_count']=2
    if problem=='report_hash':broken['mutation_provider']['offline_compilation']['sha256']='0'*64
    with pytest.raises(ValueError):admission.validate_source_and_provider(broken)


def test_plan_node_calls_actual_bound_compiler_and_removes_only_empty_FM_metadata(tmp_path,fixture_binding):
    binding,setting,report=fixture_binding;ctx=context_for(tmp_path,binding,setting)
    result=admission.SemanticGraphPlanNode().execute(ctx);plan=result['plan']
    assert'mask_ranges'not in plan
    assert canonical(plan['edits'])==binding['edits_sha256']==report['edits_sha256']
    assert plan['family_adapter']['id']==admission.PROVIDER_ID
    assert plan['family_adapter']['root_proof_route']==admission.JOINT_METHOD
    assert CLAUSES['debugging']in plan['public_instruction']
    assert 'semantic_graph_plan_binding.json'in ctx.saved
    assert ctx.saved['semantic_graph_plan_binding.json']['source_presentation_adapter']==admission.SOURCE_ADAPTER
    assert ctx.saved['semantic_graph_plan_binding.json']['empty_FM_only_mask_field_removed']is True


def test_explicit_provider_cannot_fall_back_when_setting_or_source_binding_missing(tmp_path,fixture_binding):
    binding,setting,_=fixture_binding;ctx=context_for(tmp_path,binding,setting);ctx.config={}
    with pytest.raises(ValueError,match='requires its separate'):admission.validate_context_binding(ctx,require_plan=False)
    ctx.config={admission.SETTING:{**setting,'version':False}}
    with pytest.raises(ValueError):admission.validate_context_binding(ctx,require_plan=False)


def test_construct_inherits_ordinary_joint_body_and_root_proof_without_copying(monkeypatch):
    expected={'source_binding':{'test':True},'activity_contract':admission.JOINT_METHOD}
    ctx=object();seen=[]
    monkeypatch.setattr(admission,'validate_context_binding',lambda c:expected)
    monkeypatch.setattr(SCCConstructNode,'_execute_scc',lambda self,c,b:seen.append((c,b))or {'ordinary_joint_body':True})
    assert admission.SemanticGraphConstructNode().execute(ctx)=={'ordinary_joint_body':True}
    assert seen==[(ctx,expected)]
    assert '_prove_activity'not in admission.SemanticGraphConstructNode.__dict__
    assert '_execute_scc'not in admission.SemanticGraphConstructNode.__dict__


def test_construct_never_silently_bypasses_bad_admission(monkeypatch):
    def invalid(ctx):raise ValueError('missing evidence')
    monkeypatch.setattr(admission,'validate_context_binding',invalid)
    with pytest.raises(TaskRejected,match='Q06'):admission.SemanticGraphConstructNode().execute(object())


def test_new_Factory_claims_every_debug_root_using_original_overlap_logic(tmp_path,fixture_binding,monkeypatch):
    binding,setting,_=fixture_binding;ctx=context_for(tmp_path,binding,setting)
    ctx.data.update(admission.SemanticGraphPlanNode().execute(ctx));ctx.data['plan']['mask_ranges']=[]
    expected=deepcopy(ctx.data['plan']['edits']);seen=[]
    monkeypatch.setattr(FactoryPipeline,'_claim_targets',lambda self,c:seen.append(deepcopy(c.data['plan']))or 'claimed')
    factory=object.__new__(SemanticGraphFactory)
    assert factory._claim_targets(ctx)=='claimed'
    assert len(seen)==1 and'mask_ranges'not in seen[0]and seen[0]['edits']==expected
    assert 'semantic_factory_empty_mask_compatibility.json'in ctx.saved


def test_registry_preserves_all_normal_quality_nodes_and_has_separate_v3_route():
    nodes=yaml.safe_load(REGISTRY.read_text())['nodes']
    base=yaml.safe_load((ROOT/'config/task_adapters/scc_activity_nodes.yaml').read_text())['nodes']
    assert nodes['plan'].endswith(':SemanticGraphPlanNode')and nodes['construct'].endswith(':SemanticGraphConstructNode')
    for name in ['normalize','profile','instruction','precheck','independent_recovery','trajectory','diagnose','export']:
        assert nodes[name]==base[name]
    assert nodes['repair']=='sheets_factory.task_adapters.public_workbook_scope:ScopeRepairNode'
