"""Service-free SG4000 scope, opaque binding and complete normal-quality gates."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import FunctionType, SimpleNamespace

import pytest
import yaml

from sheets_factory.pipelines import operating_reports_debug_classes_quality as pipeline
from sheets_factory.task_adapters import operating_reports_debug_classes_quality as nodes
from sheets_factory.workbook.linear_capital_ringfenced_group import contract as files
from test_reference_review_reporting import reviewed_run
from test_reference_evidence_policy import context as reference_context
import test_operating_reports_financial_cohort_quality as transport

ROOT=Path(__file__).resolve().parents[1]


def entry():
    spec=importlib.util.spec_from_file_location('_SG4000_normal_tests',ROOT/'scripts/run_operating_reports_debug_classes_quality.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def configuration(output):
    config=yaml.safe_load(pipeline.CONFIG.read_text())
    config.update(project_root=str(ROOT),run_dir=str(output),pipeline={'node_registry':str(pipeline.REGISTRY)})
    config[pipeline.SETTING]=pipeline.setting();return config


@pytest.fixture
def boundary(tmp_path,monkeypatch):
    """Mock only the expensive genuine source/task cold gate, not its shape checks."""
    def save(name,value):return files.write(tmp_path/name,value)
    def raw(name,value):
        path=tmp_path/name;path.write_bytes(value);return files.reference(path)
    other=save('artifact.json',{'fixed':'current complete artifact'})
    historical_code=raw('historical_provider.py',b'new current historical-only bytes')
    public_ref=save('specification.json',{'public_policy':'Supplied assumptions and declared periods govern.'})
    inp=raw('input.xlsx',b'fixed actual SG input');goal=raw('goal.xlsx',b'fixed healthy goal')
    brief=raw('brief.md',b'B'*410+b'\n');instruction=raw('instruction.md',Path(brief['path']).read_bytes()+pipeline.IO_APPENDIX)
    faults={};witnesses=[];formulas={}
    for i in range(4000):
        key='E%03d/forecast/%d'%(i%200+1,i);cell='A'+str(i+1);family='associate_presentation_sign' if i<800 else 'ratio_as_quarterly_change'
        faults[key]={'sheet':'Report','cell':cell,'family':family,'healthy_formula':'=1','faulty_formula':'=-1'}
        formulas['Report!'+cell]='=1'
        witnesses.append({'key':key,'family':family,'healthy_primary':{'type':'number','value':'1.00'},
            'wrong_primary':{'type':'number','value':'-1.00'},'healthy_exact':'1','wrong_exact':'-1'})
    plan=save('plans.json',{'DBG_faults':faults})
    impact_value={'witnesses':witnesses,'roots_by_family':{'associate_presentation_sign':800,'ratio_as_quarterly_change':3200},
        'all_roots_exact_nonzero_primary_impact':True,'outside_root_formula_dependents':[],'exact_arithmetic_predicted_D_count':4000}
    impact=save('impact.json',impact_value)
    definition_value={'formulas':formulas,'literals':{'Inputs!A1':7},'sheetnames':['Report','Inputs']}
    definition=save('definition.json',definition_value)
    candidate=save('candidate.json',{name:other for name in ('retained_A','retained_B','raw_generation','emission_receipt')})
    material={'input':inp,'goal':goal,'instruction':brief,'complete_D_count':4000,'controls':deepcopy(pipeline.REWARDS),
        'full_D_controls':{name:other for name in pipeline.REWARDS}}
    prepared={'kind':'prepared_operating_reports_200_debug_classes_task_engineering','version':1,'variant_id':'SG4000',
        'mode_order':['debugging'],'financial_target_count':93510,'independent_business_field_count':93510,
        'DBG_formula_root_count':4000,'formula_count':88676,'report_NA_count':4834,
        'variant_envelope':other,'variant_plans':{'view_plans':plan,'proof':impact},'source_manifest':other,'source_preparation':other,
        'genuine_goal':goal,'candidate_preparation':candidate,'specification':public_ref,'definition':definition,
        'source_definition':definition,'expected':other,'bindings':other,'runtime_profile':files.reference(pipeline.PROFILE),
        'planned_inputs':{name:raw(name+'.xlsx',name.encode()) for name in ('equivalent','DBG_missed_root','extra_change')}}
    prep_ref=save('preparation.json',prepared)
    actual={'kind':'complete_operating_reports_200_debug_classes_task_engineering','version':1,'passed':True,'failure':None,
        'actual_LO_calls_started':5,'actual_LO_calls_completed':5,'normal_all12_QA_passed':False,'qualified':False,
        'preparation':prep_ref,'source_manifest':other,'records':{'modes':{'debugging':material}}}
    actual_ref=save('terminal.json',actual)
    development={'input':inp,'goal':goal,'original_instruction':brief,'rendered_instruction':instruction,
        'material_task_version':{'sha256':pipeline.FIRST_MATERIAL}}
    # The old snapshot is immutable provenance. Its unused global code inventory
    # deliberately names a now-different provider; it is not an active import.
    dev=save('probe.json',{'modes':{'debugging':development},'selection_history':[{
        'historical_provider':{**historical_code,'sha256':'0'*64}}]})
    for name,value in {'TERMINAL_SHA':actual_ref['sha256'],'DEV_PROBE':Path(dev['path']),'DEV_PROBE_SHA':dev['sha256'],
        'ENVELOPE_SHA':other['sha256'],'PLAN_SHA':plan['sha256'],'IMPACT_SHA':impact['sha256'],'SOURCE_SHA':other['sha256'],
        'INPUT_SHA':inp['sha256'],'GOAL_SHA':goal['sha256'],'BUSINESS_SHA':brief['sha256'],'INSTRUCTION_SHA':instruction['sha256']}.items():
        monkeypatch.setattr(pipeline,name,value)
    documents={prep_ref['path']:prepared,impact['path']:impact_value,plan['path']:{'DBG_faults':faults},
        definition['path']:definition_value,dev['path']:{'modes':{'debugging':development}}}
    calls=[]
    def validate(ref):calls.append(ref);return deepcopy(actual)
    def read(ref):return deepcopy(documents.get(ref['path'],files.read(ref)))
    helper=SimpleNamespace(validate_completed=validate,read=read,checked=files.checked,write=files.write,
        recipes=lambda:{other['path']:other},source=SimpleNamespace(schema=SimpleNamespace(canonical_sha256=lambda _:pipeline.SPECIFICATION_SHA)))
    monkeypatch.setattr(pipeline,'boundary',lambda:helper)
    return SimpleNamespace(actual=actual,terminal=actual_ref,prepared=prepared,material=material,helper=helper,calls=calls,
        plan=faults,impact=impact_value,definition=definition_value,development=development,other=other,dev=dev,
        documents=documents,brief=brief,instruction=instruction,historical_code=historical_code)


def admitted(f):return pipeline.DebugClassesAdmission(f.terminal)


def test_exact_spent_SG4000_material_complete_scope_and_opaque_type(boundary):
    f=boundary;live=admitted(f);proof=pipeline.admission(live)
    assert f.calls==[f.terminal] and proof['mode']=='debugging' and proof['complete_D_count']==4000
    assert proof['independent_scope_count']==93510 and proof['first_development_material_identity']==pipeline.FIRST_MATERIAL
    assert Path(proof['instruction']['path']).read_bytes()==Path(f.brief['path']).read_bytes()+pipeline.IO_APPENDIX
    assert len(Path(proof['instruction']['path']).read_bytes())==502
    assert not proof['original_dev_and_normal_scores_transferred'] and not proof['qualified']
    for fake in (proof,object.__new__(pipeline.DebugClassesAdmission)):
        with pytest.raises(ValueError,match='JSON, fabricated'):pipeline.admission(fake)
    assert pipeline.admission(admitted(f))==proof and len(f.calls)==2


@pytest.mark.parametrize('problem',['old_family','failed','partial_call','scope','formula','NA','variant','root_count','mode','D','controls','source','profile','input','goal','brief','identity','rendered','overlap','zero','missing_witness','extra_dependent','wrong_family'])
def test_partial_foreign_changed_or_inactive_scope_cannot_admit(boundary,problem):
    f=boundary
    if problem=='old_family':f.actual['kind']='complete_fixed_operating_reports_200_task_engineering_revision2'
    elif problem=='failed':f.actual['passed']=False
    elif problem=='partial_call':f.actual['actual_LO_calls_completed']=4
    elif problem=='scope':f.prepared['independent_business_field_count']-=1
    elif problem=='formula':f.prepared['formula_count']-=1
    elif problem=='NA':f.prepared['report_NA_count']-=1
    elif problem=='variant':f.prepared['variant_id']='S800'
    elif problem=='root_count':f.prepared['DBG_formula_root_count']=800
    elif problem=='mode':f.actual['records']['modes']['financial_modeling']=f.material
    elif problem=='D':f.material['complete_D_count']=3999
    elif problem=='controls':f.material['controls']['missed_root']=1
    elif problem=='source':f.prepared['source_manifest']={**f.other,'sha256':'0'*64}
    elif problem=='profile':f.prepared['runtime_profile']=f.other
    elif problem=='input':f.material['input']={**f.material['input'],'sha256':'0'*64}
    elif problem=='goal':f.material['goal']={**f.material['goal'],'sha256':'0'*64}
    elif problem=='brief':Path(f.brief['path']).write_bytes(b'changed')
    elif problem=='identity':f.development['material_task_version']['sha256']='0'*64
    elif problem=='rendered':Path(f.instruction['path']).write_bytes(b'changed')
    elif problem=='overlap':list(f.plan.values())[1].update(cell='A1')
    elif problem=='zero':f.impact['witnesses'][0]['wrong_primary']=f.impact['witnesses'][0]['healthy_primary']
    elif problem=='missing_witness':f.impact['witnesses'].pop()
    elif problem=='extra_dependent':f.impact['outside_root_formula_dependents']=['Elsewhere!A1']
    else:f.impact['roots_by_family']['associate_presentation_sign']-=1
    with pytest.raises(ValueError):admitted(f)


def test_historical_only_drift_is_documentary_current_material_provider_and_memory_drift_reject(boundary):
    f=boundary;live=admitted(f)
    scope=live.evidence['dependency_scope']
    assert not scope['historical_snapshot_is_current_code_inventory']
    assert str(f.historical_code['path']) not in live.references.files
    Path(f.historical_code['path']).write_bytes(b'a later unrelated historical-only version')
    assert pipeline.admission(live)
    Path(f.other['path']).write_text('{"changed_current_artifact":true}')
    with pytest.raises(ValueError,match='artifact changed'):pipeline.admission(live)


def test_current_provider_and_interpreted_large_payload_stay_guarded(boundary,tmp_path):
    f=boundary;code=tmp_path/'provider.py';code.write_text('CURRENT=1\n');code_ref=files.reference(code)
    f.helper.recipes=lambda:{code_ref['path']:code_ref};live=admitted(f)
    code.write_text('CURRENT=2\n')
    with pytest.raises(ValueError):pipeline.admission(live)


def test_genuine_validator_failure_and_live_memory_tampering_remain_fail_closed(boundary):
    f=boundary;live=admitted(f);live.evidence['impact']['witnesses'][0]['wrong_exact']='1'
    with pytest.raises(ValueError,match='in memory'):pipeline.admission(live)
    def fail(_):raise ValueError('genuine task/source cold failure')
    f.helper.validate_completed=fail
    with pytest.raises(ValueError,match='genuine task/source'):admitted(f)


def test_all4000_canonical_faults_healthy_definitions_and_no_public_repair_hints(boundary):
    live=admitted(boundary);plan=nodes.canonical_plan(live)
    assert plan['mode']=='debugging' and len(plan['edits'])==4000
    assert all(v['before']=='=1' and v['after']=='=-1' for v in plan['edits'])
    assert plan['public_instruction'].encode()==Path(boundary.instruction['path']).read_bytes()
    assert plan['scenario_inputs']==[] and plan['public_rules']==['Supplied assumptions and declared periods govern.']
    assert not plan['family_adapter']['normal_quality_or_score_inherited']
    boundary.definition['literals']['Report!A1']=1
    with pytest.raises(ValueError,match='given field'):nodes.canonical_plan(live)


def test_all_twelve_reference_checks_ordinary_model_isolated_globals_and_DBG_registry(tmp_path):
    from sheets_factory.checkers import DiagnosisRunner
    config=configuration(tmp_path);profile=pipeline.validate_configuration(config)
    assert profile['docker_resources']['source']['pids_limit']==256
    assert set(DiagnosisRunner(ROOT).resolve(config)['enabled_check_ids'])=={f'Q{i:02d}' for i in range(1,13)}
    registry=yaml.safe_load(pipeline.REGISTRY.read_text())['nodes']
    assert len(registry)==11 and registry['independent_recovery']=='sheets_factory.nodes.quality:RecoveryNode'
    assert registry['trajectory']=='sheets_factory.nodes.quality:TrajectoryNode'
    assert pipeline.NativeQualityFactory.run_phase.__code__ is pipeline.base.NativeQualityFactory.run_phase.__code__
    assert pipeline.NativeQualityFactory.run_phase.__globals__ is not pipeline.base.NativeQualityFactory.run_phase.__globals__
    assert nodes.DiagnoseNode.execute.__code__ is nodes.frozen.DiagnoseNode.execute.__code__
    assert nodes.DiagnoseNode.execute.__globals__ is not nodes.frozen.DiagnoseNode.execute.__globals__
    assert nodes.frozen.pipeline.SETTING=='operating_reports_200_reference_quality'


@pytest.mark.parametrize('problem',['check','policy','Harbor','FM','model','concurrency','filter','transport'])
def test_no_quality_condition_can_be_reduced(tmp_path,problem):
    config=configuration(tmp_path)
    if problem=='check':config['diagnosis']['selection']['exclude']=['Q04']
    elif problem=='policy':config['diagnosis']['reference_evidence_policy']='independent_public_recovery'
    elif problem=='Harbor':config['harbor']['execute_controls']=False
    elif problem=='FM':config['run']['targets']['financial_modeling']=1
    elif problem=='model':config['agents']['model']='gpt-6.1-sol'
    elif problem=='concurrency':config['run']['max_parallel_sources']=2
    elif problem=='filter':config['run']['source_filter']='another source'
    else:config['diagnosis']['execution']['reference_evidence_transport']='none'
    with pytest.raises(ValueError):pipeline.validate_configuration(config)


def test_prepare_and_warm_cold_validation_zero_services_preserve_exact_spent_bytes(boundary,tmp_path,monkeypatch):
    f=boundary;module=entry();out=tmp_path/'normal'
    monkeypatch.setitem(module._namespace,'configure',lambda p,o,proofs:{**configuration(o),
        'run':{**configuration(o)['run'],'seed_manifest':str(o/'seed_manifest.json')},'host_runtime':{'fixture':'no services'}})
    monkeypatch.setitem(module._namespace,'recipes',lambda *a:{f.other['path']:f.other['sha256']})
    monkeypatch.setattr(module,'execute_prepared',lambda *a,**k:pytest.fail('No services in preparation'))
    ref=module.prepare([f.terminal],out);frozen=files.read(ref)
    assert frozen['targets']=={'financial_modeling':0,'debugging':1} and frozen['count']==1
    assert all(frozen[k]==0 for k in ('actual_models','actual_LO_calls','actual_Harbor_jobs','task_count'))
    assert len(f.calls)==1 and module.validate_prepared(out)[0]==frozen and len(f.calls)==1
    module._namespace['_SESSIONS'].clear();assert module.validate_prepared(out)[0]==frozen and len(f.calls)==2
    seed=files.read(frozen['prepared_seed_manifest'])['selected'][0]
    assert seed['modes']==['debugging'] and not seed['finance_evidence']['financial_modeling_eligible']
    assert seed['finance_evidence']['debugging_eligible']
    factory=pipeline.NativeQualityFactory(module.validate_prepared(out)[1],SimpleNamespace(update_run=lambda **k:None),None,None,
        admissions=module.validate_prepared(out)[2])
    assert factory.load_seeds()[0]['modes']==['debugging'] and isinstance(factory.load_node('diagnose'),nodes.DiagnoseNode)


@pytest.mark.parametrize('clean',[True,False])
def test_three_new_actual_normal_control_calls_with_DBG_missed_root_and_exact_owned_cleanup(boundary,tmp_path,monkeypatch,clean):
    f=boundary;live=admitted(f);proof=pipeline.admission(live);history=[];calls=[];saved={}
    class Engine:
        def metadata(self):return {'actual_resource_receipts':history[:]}
        def recalculate(self,source,output):
            calls.append(source);output.write_bytes(b'mocked native result')
            history.append(files.write(tmp_path/(str(len(calls))+'_resource.json'),{'mock':True}))
    f.helper.source.validate_call=lambda call,ref,p:{'container_id':str(call['index'])*64,'terminal':ref}
    f.helper.source.owned_absence=lambda rows:{'all_owned_containers_absent':clean,'daemon_reachable':True,
        'owned':[{'full_id':r['actual_resource_evidence']['container_id'],'absent':True} for r in rows]}
    monkeypatch.setattr(nodes.base,'compare_files',lambda s,g,o:{'reward':0 if Path(o)==Path(proof['input']['path'])
        or Path(o).stem in ('missed_root','extra_change') else 1})
    ctx=SimpleNamespace(config=configuration(tmp_path),mode='debugging',source=Path(proof['workbook']['path']),
        data={'_native_scope_admission':live,'input':Path(proof['input']['path']),'goal':Path(proof['goal']['path']),'revision_hash':'current'},
        revision_dir=tmp_path/'revision',engine=Engine(),save=lambda name,row:saved.update({name:row}))
    if clean:assert nodes.ControlsNode().execute(ctx)['controls']=={name:{'reward':v} for name,v in nodes.REWARDS.items()}
    else:
        with pytest.raises(ValueError,match='owned-cleanup'):nodes.ControlsNode().execute(ctx)
        assert 'local_controls.json' not in saved
    assert calls==[files.checked(f.prepared['planned_inputs'][name]) for name in ('equivalent','DBG_missed_root','extra_change')]


@pytest.mark.parametrize('problem',[None,'missing','extra','native_error'])
def test_construction_requires_entire4000_D_and93510_independent_goal(boundary,tmp_path,monkeypatch,problem):
    f=boundary;live=admitted(f);proof=pipeline.admission(live);plan=nodes.canonical_plan(live)
    labels=sorted('Report!A'+str(i+1) for i in range(4000))
    if problem=='missing':labels.pop()
    if problem=='extra':labels.append('Other!B1');labels.sort()
    monkeypatch.setattr(nodes.base,'compare_workbooks',lambda *a:{'reward':1,'expected_changes':labels})
    monkeypatch.setattr(nodes.base,'evaluate_native_risk_guard',lambda *a,**k:{'blocking':False})
    monkeypatch.setattr(nodes.base,'profile_workbook',lambda *a,**k:{'truncated':False})
    audited=[]
    f.helper.source.audit_workbook=lambda *a:audited.append(a) or {'passed':problem!='native_error',
        'all_financial_fields_checked':93510,'native_errors':['bad'] if problem=='native_error' else []}
    expected={label:{'type':'number','value':'1'} for label in labels}
    expected.update({'Given!'+str(i):{} for i in range(93510-len(expected))})
    old_read=f.helper.read
    f.helper.read=lambda ref:expected if ref==f.prepared['expected'] else old_read(ref)
    saved={};ctx=SimpleNamespace(config=configuration(tmp_path),mode='debugging',source=Path(proof['workbook']['path']),
        data={'_native_scope_admission':live,'plan':plan},revision_dir=tmp_path/'revision',revision=0,save=lambda n,v:saved.update({n:v}))
    if problem:
        with pytest.raises(ValueError):nodes.ConstructNode().execute(ctx)
    else:
        result=nodes.ConstructNode().execute(ctx)
        assert result['construction_validation']['full_D_count']==4000 and len(result['root_impacts'])==4000
        assert len(audited)==1 and saved['native_error_probe.json']['independent_fields_checked']==93510


# Exercise the exact repaired transport/resource bytecode through this NEW entry.
def rebound(function):
    return FunctionType(function.__code__,{**function.__globals__,'entry':entry},function.__name__,function.__defaults__,function.__closure__)


@pytest.fixture
def resource_case(tmp_path,monkeypatch):
    return rebound(transport.resource_case.__wrapped__)(tmp_path,monkeypatch)


@pytest.mark.parametrize('shape',['base5','rich7'])
def test_real_resource_package_keeps_sparse_rich_identity_and_export_binding(resource_case,shape):
    transport.test_real_resource_package_accepts_exact_base_and_rich_bindings(resource_case,shape)


@pytest.mark.parametrize('problem',['missing_observer','observer_role','binding_extra','binding_partial','wrong_agent','wrong_reward','resource_package'])
def test_actual_Harbor_resource_gaps_remain_unknown_not_model_zero(resource_case,monkeypatch,problem):
    transport.test_actual_resource_gap_quarantines_only_original_and_retains_raw_rewards(resource_case,monkeypatch,problem)


@pytest.mark.parametrize('compact',[False,True])
def test_exact_full_or_compact_private_transport_with_actual_reference_receipt(reviewed_run,compact):
    rebound(transport.test_private_reporter_validates_genuine_full_and_compact_transport_without_old_globals)(reviewed_run,compact)


@pytest.mark.parametrize('problem',['full','compact','inventory','binding','no_summary','duplicate_fragment'])
def test_changed_full_context_summary_or_receipt_binding_rejects(reviewed_run,problem):
    rebound(transport.test_reporter_rejects_changed_full_compact_inventory_or_binding)(reviewed_run,problem)


@pytest.mark.parametrize('problem',[None,'unreleasable','stale_binding','missing_Q04','disabled_Q12'])
def test_all12_supported_reference_evidence_gate_still_required(reference_context,problem):
    transport.test_original_complete_supported_reference_gate_remains_decisive(reference_context,problem)


def test_early_panel_precedes_long_cold_admission_before_any_services(tmp_path,monkeypatch):
    module=entry();events=[]
    @contextmanager
    def monitor(*a,**k):events.append('panel');yield {'passed':False}
    monkeypatch.setattr(module,'admission_monitor',monitor)
    monkeypatch.setattr(module,'prepare',lambda *a,**k:events.append('cold_prepare'))
    monkeypatch.setattr(module,'execute_prepared',lambda *a,**k:events.append('normal_run') or 0)
    assert module.main(['--actual-terminal','/genuine','--output',str(tmp_path/'normal'),'--run'])==0
    assert events==['panel','cold_prepare','normal_run']


def test_real_cloned_outer_monitor_opens_and_closes_owned_lease_panel(tmp_path,monkeypatch):
    # Reuse the tested real monitor lifecycle with this entry and its new label.
    module=entry();ns=module.admission_monitor.__wrapped__.__globals__;events=[]
    class Audit:
        def __init__(self,*a):self.db=SimpleNamespace(close=lambda:events.append('closed'))
        def snapshot(self):return {}
        def events(self,*a):return []
        def update_run(self,**k):pass
        def export(self):pass
    class Panel:
        def __init__(self,*a,**k):pass
        def start(self):events.append('panel');return 'http://fixture.invalid'
        def stop(self):events.append('stopped')
    class Lease:
        def __init__(self,*a):pass
        def acquire(self):events.append('lease');return self
        def release(self):events.append('released')
    for key,value in [('AuditStore',Audit),('DashboardServer',Panel),('ProducerLease',Lease)]:monkeypatch.setitem(ns,key,value)
    with module.admission_monitor(tmp_path/'normal','prepare',declared_count=1) as state:
        assert events==['lease','panel'];events.append('cold');state['passed']=True
    assert events==['lease','panel','cold','stopped','closed','released']
    record=files.read(next(tmp_path.glob('normal_prepare_monitor_*/terminal.json')))
    assert record['kind']=='SG4000_debugging_normal_admission_outer_monitor' and record['inner_passed']
    assert record['monitor_does_not_launch_native_models_or_LO'] and not record['qualified']
