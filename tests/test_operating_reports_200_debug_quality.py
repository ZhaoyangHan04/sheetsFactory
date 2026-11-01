"""Service-free checks for the exact original C00 debugging normal entry."""
from contextlib import contextmanager
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import FunctionType,SimpleNamespace

import pytest
import yaml

from sheets_factory.pipelines import operating_reports_200_debug_quality as pipeline
from sheets_factory.task_adapters import operating_reports_200_debug_quality as nodes
from sheets_factory.workbook.linear_capital_ringfenced_group import contract as files
from test_reference_review_reporting import reviewed_run
from test_reference_evidence_policy import context as reference_context
import test_operating_reports_financial_cohort_quality as transport
import test_operating_reports_debug_classes_quality as classes

ROOT=Path(__file__).resolve().parents[1]


def entry():
    spec=importlib.util.spec_from_file_location('_C00_debug_normal_tests',ROOT/'scripts/run_operating_reports_200_debug_quality.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def configuration(output):
    config=yaml.safe_load(pipeline.CONFIG.read_text())
    config.update(project_root=str(ROOT),run_dir=str(output),pipeline={'node_registry':str(pipeline.REGISTRY)})
    config[pipeline.SETTING]=pipeline.setting();return config


@pytest.fixture
def boundary(tmp_path,monkeypatch):
    def save(name,value):return files.write(tmp_path/name,value)
    def raw(name,value):
        path=tmp_path/name;path.write_bytes(value);return files.reference(path)
    other=save('artifact.json',{'fixed':'current complete artifact'})
    historical_code=raw('historical_provider.py',b'later unrelated provider')
    spec=save('specification.json',{'public_policy':'Supplied assumptions and declared periods govern.'})
    inp=raw('input.xlsx',b'exact C00 debugging workbook');goal=raw('goal.xlsx',b'exact healthy goal')
    brief=raw('brief.md',b'B'*410+b'\n');instruction=raw('instruction.md',Path(brief['path']).read_bytes()+pipeline.IO_APPENDIX)
    faults={};witnesses=[];formulas={}
    for i in range(200):
        key=f'E{i+1:03}/forecast/root';cell='A'+str(i+1);family=list(pipeline.FAMILIES)[i//50]
        faults[key]={'sheet':'Report','cell':cell,'family':family,'healthy_formula':'=1','faulty_formula':'=-1'}
        formulas['Report!'+cell]='=1';witnesses.append({'key':key,'family':family,
            'expected_primary':{'type':'number','value':'1.00'},'wrong_root_primary':'-1.00',
            'healthy_root_exact':'1','wrong_root_exact':'-1'})
    plan=save('plans.json',{'DBG_faults':faults})
    impact_value={'passed':True,'witnesses':witnesses,'total_roots_primary_impact_proved':200,
        'all93510_original_A_B_points_unchanged':True,'healthy_source_formulas_and_values_unchanged':True,
        'public_facts_and_policies_unchanged':True}
    impact=save('impact.json',impact_value)
    definition_value={'formulas':formulas,'literals':{'Inputs!A1':7},'sheetnames':['Report','Inputs'],
        'DBG_root_points':sorted(formulas)}
    definition=save('definition.json',definition_value)
    candidate=save('candidate.json',{name:other for name in ('retained_A','retained_B','raw_generation','emission_receipt')})
    lineage_value={'revised_view_plans':plan,'pure_design_proof':impact,'fault_design':other}
    lineage=save('lineage.json',lineage_value)
    labels=sorted('Report!A'+str(i+1) for i in range(18240))
    nop_value={'comparison':{'reward':0,'expected_change_count':18240,'actual_change_count':0,
        'missing_changes':labels,'extra_changes':[],'wrong_values':labels}}
    nop=save('nop.json',nop_value)
    material={'input':inp,'goal':goal,'instruction':brief,'complete_D_count':18240,
        'controls':deepcopy(pipeline.REWARDS),'full_D_controls':{name:(nop if name=='nop'else other)for name in pipeline.REWARDS}}
    prepared={'kind':'prepared_fixed_operating_reports_200_task_engineering_revision2','version':1,
        'mode_order':['financial_modeling','debugging'],'financial_target_count':62322,'independent_business_field_count':93510,
        'DBG_formula_root_count':200,'task_fault_lineage':lineage,'source_manifest':other,'source_preparation':other,
        'genuine_goal':goal,'candidate_preparation':candidate,'specification':spec,'definition':definition,
        'DBG_definition':definition,'source_definition':definition,'expected':other,'bindings':other,
        'runtime_profile':files.reference(pipeline.PROFILE),
        'planned_inputs':{name:raw(name+'.xlsx',name.encode())for name in ('equivalent','DBG_missed_root','extra_change')}}
    prep_ref=save('preparation.json',prepared)
    actual={'kind':'complete_fixed_operating_reports_200_task_engineering_revision2','version':1,'passed':True,'failure':None,
        'actual_LO_calls_started':8,'actual_LO_calls_completed':8,'source_LO_calls_reused':3,'task_fault_lineage':lineage,
        'normal_all12_QA_passed':False,'qualified':False,'preparation':prep_ref,'source_manifest':other,
        'records':{'modes':{'debugging':material,'financial_modeling':deepcopy(material)}}}
    actual_ref=save('terminal.json',actual)
    development={'input':inp,'goal':goal,'original_instruction':brief,'rendered_instruction':instruction,
        'material_task_version':{'sha256':pipeline.FIRST_MATERIAL}}
    dev=save('probe.json',{'modes':{'debugging':development},'selection_history':[{
        'historical_provider':{**historical_code,'sha256':'0'*64}}]})
    for name,value in {'TERMINAL_SHA':actual_ref['sha256'],'DEV_PROBE':Path(dev['path']),'DEV_PROBE_SHA':dev['sha256'],
        'LINEAGE_SHA':lineage['sha256'],'PLAN_SHA':plan['sha256'],'IMPACT_SHA':impact['sha256'],'SOURCE_SHA':other['sha256'],
        'INPUT_SHA':inp['sha256'],'GOAL_SHA':goal['sha256'],'BUSINESS_SHA':brief['sha256'],'INSTRUCTION_SHA':instruction['sha256']}.items():
        monkeypatch.setattr(pipeline,name,value)
    documents={prep_ref['path']:prepared,lineage['path']:lineage_value,impact['path']:impact_value,
        plan['path']:{'DBG_faults':faults},definition['path']:definition_value,dev['path']:{'modes':{'debugging':development}},nop['path']:nop_value}
    calls=[]
    def validate(ref):calls.append(ref);return deepcopy(actual)
    def read(ref):return deepcopy(documents.get(ref['path'],files.read(ref)))
    helper=SimpleNamespace(validate_completed=validate,read=read,checked=files.checked,write=files.write,
        recipes=lambda:{other['path']:other},source=SimpleNamespace(schema=SimpleNamespace(canonical_sha256=lambda _:pipeline.SPECIFICATION_SHA)))
    monkeypatch.setattr(pipeline,'boundary',lambda:helper)
    return SimpleNamespace(actual=actual,terminal=actual_ref,prepared=prepared,material=material,helper=helper,calls=calls,
        plan=faults,impact=impact_value,definition=definition_value,development=development,other=other,
        documents=documents,brief=brief,instruction=instruction,historical_code=historical_code,labels=labels,nop=nop_value)


def admitted(f):return pipeline.OperatingReportsDebugAdmission(f.terminal)


def test_exact_original_debug_material_and_no_FM_or_development_score_inheritance(boundary):
    f=boundary;live=admitted(f);proof=pipeline.admission(live)
    assert f.calls==[f.terminal] and proof['mode']=='debugging' and proof['complete_D_count']==18240
    assert proof['physical_root_count']==200 and proof['independent_scope_count']==93510
    assert proof['first_development_material_identity']==pipeline.FIRST_MATERIAL
    assert len(Path(proof['instruction']['path']).read_bytes())==502
    assert not proof['original_dev_and_normal_scores_transferred'] and not proof['qualified']
    for fake in (proof,object.__new__(pipeline.OperatingReportsDebugAdmission)):
        with pytest.raises(ValueError,match='JSON, fabricated'):pipeline.admission(fake)


@pytest.mark.parametrize('problem',['family','failed','partial_call','source_calls','scope','FM_mask','lineage','plan','root_count',
    'mode','D','controls','source','profile','input','goal','brief','identity','rendered','overlap','zero','missing_witness','family_count',
    'root_points','D_missing','D_extra','D_omit_root'])
def test_wrong_incomplete_or_changed_material_cannot_admit(boundary,problem):
    f=boundary
    if problem=='family':f.actual['kind']='complete_operating_reports_200_debug_classes_task_engineering'
    elif problem=='failed':f.actual['passed']=False
    elif problem=='partial_call':f.actual['actual_LO_calls_completed']=7
    elif problem=='source_calls':f.actual['source_LO_calls_reused']=2
    elif problem=='scope':f.prepared['independent_business_field_count']-=1
    elif problem=='FM_mask':f.prepared['financial_target_count']-=1
    elif problem=='lineage':f.prepared['task_fault_lineage']={**f.prepared['task_fault_lineage'],'sha256':'0'*64}
    elif problem=='plan':f.documents[f.prepared['task_fault_lineage']['path']]['revised_view_plans']={**f.other,'sha256':'0'*64}
    elif problem=='root_count':f.prepared['DBG_formula_root_count']=199
    elif problem=='mode':f.actual['records']['modes'].pop('financial_modeling')
    elif problem=='D':f.material['complete_D_count']=18239
    elif problem=='controls':f.material['controls']['missed_root']=1
    elif problem=='source':f.prepared['source_manifest']={**f.other,'sha256':'0'*64}
    elif problem=='profile':f.prepared['runtime_profile']=f.other
    elif problem=='input':f.material['input']={**f.material['input'],'sha256':'0'*64}
    elif problem=='goal':f.material['goal']={**f.material['goal'],'sha256':'0'*64}
    elif problem=='brief':Path(f.brief['path']).write_bytes(b'changed')
    elif problem=='identity':f.development['material_task_version']['sha256']='0'*64
    elif problem=='rendered':Path(f.instruction['path']).write_bytes(b'changed')
    elif problem=='overlap':list(f.plan.values())[1].update(cell='A1')
    elif problem=='zero':f.impact['witnesses'][0]['wrong_root_primary']='1.00'
    elif problem=='missing_witness':f.impact['witnesses'].pop()
    elif problem=='family_count':f.impact['witnesses'][0]['family']='ratio_as_change'
    elif problem=='root_points':f.definition['DBG_root_points'].pop()
    elif problem=='D_missing':f.nop['comparison']['missing_changes'].pop()
    elif problem=='D_extra':f.nop['comparison']['extra_changes'].append('Inputs!A1')
    else:f.nop['comparison']['missing_changes'].remove('Report!A1');f.nop['comparison']['missing_changes'].append('Other!B1')
    with pytest.raises(ValueError):admitted(f)


def test_current_references_and_memory_stay_guarded_documentary_history_is_scoped(boundary):
    f=boundary;live=admitted(f)
    assert not live.evidence['dependency_scope']['historical_snapshot_is_current_code_inventory']
    Path(f.historical_code['path']).write_bytes(b'later historical-only version')
    assert pipeline.admission(live)
    live.evidence['full_D'].pop()
    with pytest.raises(ValueError,match='in memory'):pipeline.admission(live)


def test_genuine_cold_failure_cannot_be_replaced_by_json_pass(boundary):
    def fail(_):raise ValueError('genuine cold task/source rejection')
    boundary.helper.validate_completed=fail
    with pytest.raises(ValueError,match='genuine cold'):admitted(boundary)


def test_complete_canonical200_edits_and_no_new_public_repair_hints(boundary):
    live=admitted(boundary);plan=nodes.canonical_plan(live)
    assert len(plan['edits'])==200 and plan['family_adapter']['complete_D_count']==18240
    assert plan['public_instruction'].encode()==Path(boundary.instruction['path']).read_bytes()
    assert plan['scenario_inputs']==[] and not plan['family_adapter']['normal_quality_or_score_inherited']
    boundary.definition['literals']['Report!A1']=1
    with pytest.raises(ValueError,match='given field'):nodes.canonical_plan(live)


@pytest.mark.parametrize('problem',[None,'missing','extra','native_error'])
def test_construction_covers_entire18240_closure_and93510_independent_fields(boundary,tmp_path,monkeypatch,problem):
    f=boundary;live=admitted(f);proof=pipeline.admission(live);plan=nodes.canonical_plan(live);labels=f.labels[:]
    if problem=='missing':labels.pop()
    if problem=='extra':labels.append('Other!B1');labels.sort()
    monkeypatch.setattr(nodes.base,'compare_workbooks',lambda *a:{'reward':1,'expected_changes':labels})
    monkeypatch.setattr(nodes.base,'evaluate_native_risk_guard',lambda *a,**k:{'blocking':False})
    monkeypatch.setattr(nodes.base,'profile_workbook',lambda *a,**k:{'truncated':False})
    audited=[]
    f.helper.source.audit_workbook=lambda *a:audited.append(a) or {'passed':problem!='native_error',
        'all_financial_fields_checked':93510,'native_errors':['bad']if problem=='native_error'else[]}
    expected={label:{'type':'number','value':'1'}for label in labels}
    expected.update({'Given!'+str(i):{}for i in range(93510-len(expected))})
    old_read=f.helper.read;f.helper.read=lambda ref:expected if ref==f.prepared['expected']else old_read(ref)
    saved={};ctx=SimpleNamespace(config=configuration(tmp_path),mode='debugging',source=Path(proof['workbook']['path']),
        data={'_native_scope_admission':live,'plan':plan},revision_dir=tmp_path/'revision',revision=0,save=lambda n,v:saved.update({n:v}))
    if problem:
        with pytest.raises(ValueError):nodes.ConstructNode().execute(ctx)
    else:
        out=nodes.ConstructNode().execute(ctx)
        assert out['construction_validation']['full_D_count']==18240 and len(out['root_impacts'])==200
        assert len(audited)==1 and saved['native_error_probe.json']['independent_fields_checked']==93510


def rebound(function):
    return FunctionType(function.__code__,{**function.__globals__,'entry':entry,'pipeline':pipeline,'nodes':nodes,
        'configuration':configuration,'admitted':admitted},function.__name__,function.__defaults__,function.__closure__)


@pytest.mark.parametrize('clean',[True,False])
def test_three_genuine_normal_calls_and_owned_cleanup(boundary,tmp_path,monkeypatch,clean):
    rebound(classes.test_three_new_actual_normal_control_calls_with_DBG_missed_root_and_exact_owned_cleanup)(
        boundary,tmp_path,monkeypatch,clean)


def test_prepare_warm_cold_validation_and_exact_unmodified_bytes(boundary,tmp_path,monkeypatch):
    f=boundary;module=entry();out=tmp_path/'normal'
    monkeypatch.setitem(module._namespace,'configure',lambda p,o,proofs:{**configuration(o),
        'run':{**configuration(o)['run'],'seed_manifest':str(o/'seed_manifest.json')},'host_runtime':{'fixture':'no services'}})
    monkeypatch.setitem(module._namespace,'recipes',lambda *a:{f.other['path']:f.other['sha256']})
    monkeypatch.setattr(module,'execute_prepared',lambda *a,**k:pytest.fail('No services in preparation'))
    r=module.prepare([f.terminal],out);frozen=files.read(r)
    assert frozen['targets']=={'financial_modeling':0,'debugging':1} and frozen['count']==1
    assert all(frozen[k]==0 for k in ('actual_models','actual_LO_calls','actual_Harbor_jobs','task_count'))
    assert len(f.calls)==1 and module.validate_prepared(out)[0]==frozen and len(f.calls)==1
    module._namespace['_SESSIONS'].clear();assert module.validate_prepared(out)[0]==frozen and len(f.calls)==2
    seed=files.read(frozen['prepared_seed_manifest'])['selected'][0]
    assert seed['modes']==['debugging'] and not seed['finance_evidence']['financial_modeling_eligible']
    factory=pipeline.NativeQualityFactory(module.validate_prepared(out)[1],SimpleNamespace(update_run=lambda **k:None),None,None,
        admissions=module.validate_prepared(out)[2])
    assert isinstance(factory.load_node('diagnose'),nodes.DiagnoseNode)


def test_all12_registry_ordinary_model_and_private_namespaces(tmp_path):
    from sheets_factory.checkers import DiagnosisRunner
    cfg=configuration(tmp_path);pipeline.validate_configuration(cfg)
    assert set(DiagnosisRunner(ROOT).resolve(cfg)['enabled_check_ids'])=={f'Q{i:02d}'for i in range(1,13)}
    registry=yaml.safe_load(pipeline.REGISTRY.read_text())['nodes'];assert len(registry)==11
    assert registry['independent_recovery']=='sheets_factory.nodes.quality:RecoveryNode'
    assert registry['trajectory']=='sheets_factory.nodes.quality:TrajectoryNode'
    assert nodes.DiagnoseNode.execute.__code__ is nodes.frozen.DiagnoseNode.execute.__code__
    assert nodes.DiagnoseNode.execute.__globals__ is not nodes.frozen.DiagnoseNode.execute.__globals__
    assert nodes.frozen.pipeline.SETTING=='operating_reports_200_reference_quality'


@pytest.mark.parametrize('problem',['check','policy','Harbor','FM','model','concurrency','filter','transport'])
def test_every_normal_gate_is_preserved(tmp_path,problem):
    rebound(classes.test_no_quality_condition_can_be_reduced)(tmp_path,problem)


@pytest.fixture
def resource_case(tmp_path,monkeypatch):return rebound(transport.resource_case.__wrapped__)(tmp_path,monkeypatch)


@pytest.mark.parametrize('shape',['base5','rich7'])
def test_actual_resource_binding_shapes(resource_case,shape):
    transport.test_real_resource_package_accepts_exact_base_and_rich_bindings(resource_case,shape)


@pytest.mark.parametrize('problem',['missing_observer','observer_role','binding_extra','binding_partial','wrong_agent','wrong_reward','resource_package'])
def test_actual_resource_gaps_stay_unknown(resource_case,monkeypatch,problem):
    transport.test_actual_resource_gap_quarantines_only_original_and_retains_raw_rewards(resource_case,monkeypatch,problem)


@pytest.mark.parametrize('compact',[False,True])
def test_complete_or_audited_summary_private_context(reviewed_run,compact):
    rebound(transport.test_private_reporter_validates_genuine_full_and_compact_transport_without_old_globals)(reviewed_run,compact)


@pytest.mark.parametrize('problem',['full','compact','inventory','binding','no_summary','duplicate_fragment'])
def test_context_or_receipt_tamper_rejects(reviewed_run,problem):
    rebound(transport.test_reporter_rejects_changed_full_compact_inventory_or_binding)(reviewed_run,problem)


@pytest.mark.parametrize('problem',[None,'unreleasable','stale_binding','missing_Q04','disabled_Q12'])
def test_supported_reference_gate_stays_decisive(reference_context,problem):
    transport.test_original_complete_supported_reference_gate_remains_decisive(reference_context,problem)


def test_panel_precedes_cold_admission_and_services(tmp_path,monkeypatch):
    rebound(classes.test_early_panel_precedes_long_cold_admission_before_any_services)(tmp_path,monkeypatch)
