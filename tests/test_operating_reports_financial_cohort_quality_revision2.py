"""Exact causal-scope correction, including the real retained C01 evidence graph."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import FunctionType,SimpleNamespace

import pytest
import yaml

from sheets_factory.task_adapters import operating_reports_financial_cohort_quality_revision2 as nodes
from sheets_factory.workbook.linear_capital_ringfenced_group import contract as files
import test_operating_reports_financial_cohort_quality as prior

pipeline=nodes.pipeline
ROOT=Path(__file__).resolve().parents[1]
C01=ROOT/'outputs/research/operating_reports_financial_cohort_C01_task5_pilot_20261101T011800Z/prepared/terminal.json'


def entry():
    spec=importlib.util.spec_from_file_location('_cohort_normal_r2_test',ROOT/'scripts/run_operating_reports_financial_cohort_quality_revision2.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def configuration(output):
    value=prior.configuration(output);value[pipeline.SETTING]=pipeline.setting()
    value['pipeline']['node_registry']=str(pipeline.REGISTRY);return value


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    original=prior.boundary.__wrapped__;ns={**original.__globals__,'pipeline':pipeline}
    return FunctionType(original.__code__,ns,original.__name__)(tmp_path,monkeypatch)


def test_distinct_live_admission_preserves_original_full_gate_bytecode_and_material(fixture):
    f=fixture;live=pipeline.FinancialCohortAdmission(f.terminal,artifact_directory=f.artifacts,create=True)
    proof=pipeline.admission(live)
    assert proof['version']==2 and proof['kind']=='opaque_financial_cohort_FM_causal_admission_revision2'
    assert proof['case_id']=='FM-C01' and proof['complete_D_count']==62322 and f.calls==[f.terminal]
    assert proof['dependency_scope']['complete_design_blobs']==nodes.DESIGN_LEAVES
    assert not proof['dependency_scope']['prior_normal_qualification_inherited']
    assert nodes._original_init.__code__.co_code==nodes.old_pipeline.FinancialCohortAdmission.__init__.__code__.co_code
    assert nodes._original_init.__globals__ is nodes._pipe_ns
    for name in ('guard',):
        assert getattr(type(live),name).__code__.co_code==getattr(nodes.old_pipeline.FinancialCohortAdmission,name).__code__.co_code
    for fake in (proof,object.__new__(pipeline.FinancialCohortAdmission)):
        with pytest.raises(ValueError):pipeline.admission(fake)
    with pytest.raises(ValueError):nodes.old_pipeline.admission(live)
    assert nodes.old_pipeline.NativeScopeAdmission is nodes.old_pipeline.FinancialCohortAdmission
    assert files.checked(proof['instruction']).read_bytes()==files.checked(f.business).read_bytes()+pipeline.IO_APPENDIX


def test_only_exact_three_design_refs_stop_recursion_and_remain_whole_hash_guarded(tmp_path,monkeypatch):
    old=files.write(tmp_path/'old_provider.json',{'old':'documentary'})
    p=Path(old['path']);p.write_text('changed historical runtime')
    design=files.write(tmp_path/'design.json',{'literal_parameter':17,'documentary':old})
    current=files.write(tmp_path/'current.json',{'value':42})
    root=files.write(tmp_path/'current_root.json',{'immutable_design':design,'current':current})
    monkeypatch.setattr(nodes,'DESIGN_LEAVES',{design['path']:design})
    refs=nodes.CausalReferences();refs.discover(root)
    assert set(refs.files)=={root['path'],design['path'],current['path']}
    assert refs.design_blob_leaves=={design['path']:design}
    Path(current['path']).write_text('changed current assumption')
    with pytest.raises(ValueError,match='bound artifact changed'):refs.guard()
    # A new reference to the changed design cannot relabel its fixed original SHA.
    Path(design['path']).write_text('changed design parameter')
    with pytest.raises(ValueError,match='design-blob binding'):nodes.CausalReferences().discover(files.reference(design['path']))


def test_no_arbitrary_json_or_unknown_history_edge_is_skipped(tmp_path,monkeypatch):
    leaf=files.write(tmp_path/'mutable.json',{'financial_parameter':9})
    wrapper=files.write(tmp_path/'unrecognized_design.json',{'upstream':leaf})
    Path(leaf['path']).write_text('changed')
    monkeypatch.setattr(nodes,'DESIGN_LEAVES',{})
    with pytest.raises(ValueError,match='bound artifact changed'):nodes.CausalReferences().discover(wrapper)


def test_current_real_C01_graph_reproduces_old_failure_and_guards_all_current_material():
    if not C01.is_file():pytest.skip('Retained actual C01 private integration fixture is unavailable')
    row=files.reference(C01)
    with pytest.raises(ValueError,match='derived_gold/spec.py'):nodes.old_pipeline.References().discover(row)
    refs=nodes.CausalReferences();refs.discover(row);refs.guard()
    assert len(refs.files)>=140 and refs.design_blob_leaves==nodes.DESIGN_LEAVES
    terminal=files.read(row);prep=files.read(terminal['preparation']);source=files.read(terminal['source_manifest'])
    source_prep=files.read(source['preparation']);inventory=files.read(prep['raw_inventory'])
    for case in inventory['cases']:assert refs.files[case['specification']['path']]==case['specification']
    for key in ('expected','definition','source_definition','bindings','specification','genuine_goal'):
        # The live admission also explicitly binds interpreted large objects;
        # discovery deliberately treats the large preparation itself as a leaf.
        refs.check(prep[key])
        assert refs.files[prep[key]['path']]==prep[key]
    for key in ('forward_A','forward_B','comparison'):
        record=source_prep['financial_evidence'][key];assert refs.files[record['path']]==record
    assert not any('/derived_gold/' in path for path in refs.files)


def test_real_C01_admission_shape_and_discovery_with_only_expensive_gate_mocked(tmp_path,monkeypatch):
    if not C01.is_file():pytest.skip('Retained actual C01 private integration fixture is unavailable')
    row=files.reference(C01);actual=files.read(row);helper=pipeline.boundary();calls=[]
    # This tests causal discovery against real data, not native proof or a new approval.
    def cold(ref):calls.append(ref);return deepcopy(actual)
    monkeypatch.setattr(helper,'validate_completed',cold);monkeypatch.setattr(pipeline,'boundary',lambda:helper)
    live=pipeline.FinancialCohortAdmission(row,artifact_directory=tmp_path/'actual_shape_material',create=True)
    proof=pipeline.admission(live)
    assert proof['case_id']=='FM-C01' and calls==[row] and proof['full_nine_raw_inventory']
    assert len(live.references.files)>=150 and live.references.design_blob_leaves==nodes.DESIGN_LEAVES
    assert proof['original_dev_and_normal_scores_transferred'] is False


def test_failed_genuine_cold_gate_is_not_replaced_by_graph_hashes(fixture):
    def reject(_):raise ValueError('original genuine whole source/task cold gate failed')
    fixture.helper.validate_completed=reject
    with pytest.raises(ValueError,match='genuine whole source/task'):
        pipeline.FinancialCohortAdmission(fixture.terminal,artifact_directory=fixture.artifacts,create=True)


@pytest.mark.parametrize('problem',['checks','policy','Harbor','DBG','model','concurrency'])
def test_all_normal_rules_unchanged_and_cannot_be_reduced(tmp_path,problem):
    config=configuration(tmp_path)
    if problem=='checks':config['diagnosis']['selection']['exclude']=['Q12']
    elif problem=='policy':config['diagnosis']['reference_evidence_policy']='independent_public_recovery'
    elif problem=='Harbor':config['harbor']['execute_controls']=False
    elif problem=='DBG':config['run']['targets']['debugging']=1
    elif problem=='model':config['agents']['model']='another-model'
    else:config['run']['max_parallel_sources']=3
    with pytest.raises(ValueError):pipeline.validate_configuration(config)


def test_new_factory_registry_and_original_nodes_have_private_current_admission_globals(tmp_path):
    from sheets_factory.checkers import DiagnosisRunner
    config=configuration(tmp_path);pipeline.validate_configuration(config)
    assert set(DiagnosisRunner(ROOT).resolve(config)['enabled_check_ids'])=={f'Q{i:02d}' for i in range(1,13)}
    for name in ('NormalizeNode','ConstructNode','ControlsNode','DiagnoseNode','ExportNode'):
        new=getattr(nodes,name).execute;old=getattr(nodes.old_nodes,name).execute
        assert new.__code__ is old.__code__ and new.__globals__ is nodes._node_ns and new.__globals__ is not old.__globals__
    assert pipeline.NativeQualityFactory.run_phase.__code__ is nodes.old_pipeline.NativeQualityFactory.run_phase.__code__
    assert nodes.validate_reference_export is nodes.old_nodes.validate_reference_export
    registry=yaml.safe_load(nodes.REGISTRY.read_text())['nodes']
    assert registry['independent_recovery']=='sheets_factory.nodes.quality:RecoveryNode'
    assert registry['trajectory']=='sheets_factory.nodes.quality:TrajectoryNode'


def test_fresh_prepare_cold_reload_and_same_process_entry_bind_revision_only(fixture,tmp_path,monkeypatch):
    f=fixture;module=entry();out=tmp_path/'normal'
    def configure(path,destination,proofs):
        config=configuration(destination);config['run'].update(targets={'financial_modeling':1,'debugging':0},
            max_sources=1,max_parallel_sources=1,seed_manifest=str(destination/'seed_manifest.json'))
        config['host_runtime']={'fixture':'no services'};return config
    monkeypatch.setitem(module._namespace,'configure',configure)
    monkeypatch.setitem(module._namespace,'recipes',lambda *a:{f.other['path']:f.other['sha256']})
    result=files.read(module.prepare([f.terminal],out));assert result['kind']==module.KIND and len(f.calls)==1
    assert module.validate_prepared(out)[0]==result and len(f.calls)==1
    module._namespace['_SESSIONS'].clear();frozen,config,admissions=module.validate_prepared(out)
    assert frozen==result and len(f.calls)==2
    factory=pipeline.NativeQualityFactory(config,SimpleNamespace(update_run=lambda **k:None),None,None,admissions=admissions)
    assert factory.load_seeds()[0]['modes']==['financial_modeling']
    assert isinstance(factory.load_node('diagnose'),nodes.DiagnoseNode)
    assert module.generate_report.__globals__ is module._reporting
    assert module.RESOURCE_ADAPTATION_COUNTS=={'agent_identity':1,'resource_binding':2}
    assert module.reference(module.FROZEN_ENTRY)['sha256']==module.FROZEN_ENTRY_SHA
