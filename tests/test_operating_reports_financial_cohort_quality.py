"""Service-free FM admissions, normal controls, reporting and resource transport."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from sheets_factory.pipelines import operating_reports_financial_cohort_quality as pipeline
from sheets_factory.task_adapters import operating_reports_financial_cohort_quality as nodes
from sheets_factory.workbook.linear_capital_ringfenced_group import contract as files
from test_reference_review_reporting import reviewed_run
from test_reference_evidence_policy import context as reference_context
from test_heterogeneous_native_quality import resource_run as legacy_resources

ROOT=Path(__file__).resolve().parents[1]


def entry():
    descriptor=importlib.util.spec_from_file_location('_cohort_FM_normal_test',ROOT/'scripts/run_operating_reports_financial_cohort_quality.py')
    module=importlib.util.module_from_spec(descriptor);descriptor.loader.exec_module(module);return module


def configuration(output):
    result=yaml.safe_load(pipeline.CONFIG.read_text())
    result.update(project_root=str(ROOT),run_dir=str(output),pipeline={'node_registry':str(pipeline.REGISTRY)})
    result[pipeline.SETTING]=pipeline.setting();return result


@pytest.fixture
def boundary(tmp_path,monkeypatch):
    """Only genuine cold admission is mocked; no native or financial calls."""
    def save(name,value):return files.write(tmp_path/name,value)
    def raw(name,value):
        path=tmp_path/name;path.write_bytes(value);return files.reference(path)
    public={'kind':pipeline.schema.KIND,'seed':202711201,'dimension_mode':'production','public_policy':'Declared local policy.'}
    public_ref=save('specification.json',public);points=['Report!A'+str(i) for i in range(1,62323)]
    definition=save('definition.json',{'FM_mask_points':points,'formulas':{p:'=1' for p in points},
        'literals':{'Inputs!A1':7},'sheetnames':['Report','Inputs']})
    other=save('bound.json',{'fixture':'trusted-cold-boundary-only'})
    inp=raw('input.xlsx',b'public input');goal=raw('goal.xlsx',b'private goal')
    business=raw('instruction.md',b'B'*402+b'\n')
    material={'input':inp,'goal':goal,'instruction':business,'complete_D_count':62322,
        'controls':{'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0},
        'full_D_controls':{name:other for name in ('oracle','nop','equivalent','missed_root','extra_change')}}
    prepared={'kind':'prepared_operating_reports_financial_cohort_FM_task_engineering','version':1,
        'case_id':'FM-C01','mode_order':['financial_modeling'],'financial_target_count':62322,
        'independent_business_field_count':93510,'formula_count':88676,'report_NA_count':4834,
        'genuine_goal':goal,'specification':public_ref,'definition':definition,'source_definition':definition,
        'expected':other,'bindings':other,'candidate_preparation':other,'raw_inventory':other,
        'planned_inputs':{name:raw(name+'.xlsx',name.encode()) for name in ('equivalent','FM_missed_root','extra_change')},
        'runtime_profile':files.reference(pipeline.PROFILE)}
    prep_ref=save('preparation.json',prepared)
    actual={'kind':'complete_operating_reports_financial_cohort_FM_task_engineering','version':1,'passed':True,
        'actual_LO_calls_started':5,'actual_LO_calls_completed':5,'normal_all12_QA_passed':False,'qualified':False,
        'preparation':prep_ref,'source_manifest':other,'records':{'modes':{'financial_modeling':material}}}
    terminal=save('terminal.json',actual);calls=[]
    def validate(ref):calls.append(ref);return deepcopy(actual)
    def read(ref):return deepcopy(prepared) if ref==prep_ref else files.read(ref)
    helper=SimpleNamespace(validate_completed=validate,read=read,checked=files.checked,write=files.write,
        recipes=lambda:{other['path']:other},source=SimpleNamespace())
    monkeypatch.setattr(pipeline,'boundary',lambda:helper)
    monkeypatch.setattr(pipeline.schema,'validate_spec',lambda obj:obj)
    return SimpleNamespace(actual=actual,terminal=terminal,prepared=prepared,helper=helper,calls=calls,
        other=other,business=business,material=material,artifacts=tmp_path/'admission')


def admitted(f):return pipeline.FinancialCohortAdmission(f.terminal,artifact_directory=f.artifacts,create=True)


def test_genuine_gate_byte_preservation_and_distinct_current_material(boundary):
    f=boundary;live=admitted(f);proof=pipeline.admission(live)
    assert f.calls==[f.terminal] and proof['case_id']=='FM-C01'
    assert files.checked(proof['instruction']).read_bytes()==files.checked(f.business).read_bytes()+pipeline.IO_APPENDIX
    assert len(files.checked(proof['instruction']).read_bytes())==494
    assert proof['independent_scope_count']==93510 and proof['complete_D_count']==62322
    assert not proof['original_dev_and_normal_scores_transferred'] and not proof['qualified']
    assert 'first_development_material_identity' not in proof
    for fake in (proof,object.__new__(pipeline.FinancialCohortAdmission)):
        with pytest.raises(ValueError,match='JSON, fabricated'):pipeline.admission(fake)
    cold=pipeline.FinancialCohortAdmission(f.terminal,artifact_directory=f.artifacts)
    assert pipeline.admission(cold)==proof and len(f.calls)==2
    Path(proof['instruction']['path']).write_bytes(b'changed')
    with pytest.raises(ValueError):pipeline.admission(live)
    with pytest.raises(ValueError,match='rendered business brief'):pipeline.FinancialCohortAdmission(f.terminal,artifact_directory=f.artifacts)


@pytest.mark.parametrize('problem',['old_family','failed','missing_call','case','scope','formula_scope','NA_scope','mode','D','controls','profile','brief'])
def test_no_partial_header_old_family_or_wrong_raw_case_admission(boundary,problem):
    f=boundary
    if problem=='old_family':f.actual['kind']='complete_fixed_operating_reports_200_task_engineering_revision2'
    elif problem=='failed':f.actual['passed']=False
    elif problem=='missing_call':f.actual['actual_LO_calls_completed']=4
    elif problem=='case':f.prepared['case_id']='FM-C02'
    elif problem=='scope':f.prepared['independent_business_field_count']-=1
    elif problem=='formula_scope':f.prepared['formula_count']-=1
    elif problem=='NA_scope':f.prepared['report_NA_count']-=1
    elif problem=='mode':f.actual['records']['modes']['debugging']=f.material
    elif problem=='D':f.material['complete_D_count']-=1
    elif problem=='controls':f.material['controls']['nop']=1
    elif problem=='profile':f.prepared['runtime_profile']=f.other
    else:Path(f.business['path']).write_bytes(b'changed')
    with pytest.raises(ValueError):admitted(f)


def test_cold_failure_and_in_memory_mutation_fail_closed(boundary):
    f=boundary;live=admitted(f);live.evidence['actual']['passed']=False
    with pytest.raises(ValueError,match='evidence changed in memory'):pipeline.admission(live)
    def reject(_):raise ValueError('genuine source/task cold rejection')
    f.helper.validate_completed=reject
    with pytest.raises(ValueError,match='genuine source/task'):pipeline.FinancialCohortAdmission(f.terminal,artifact_directory=f.artifacts)


def test_all_twelve_checks_ordinary_model_registry_and_isolation(tmp_path):
    from sheets_factory.checkers import DiagnosisRunner
    config=configuration(tmp_path);profile=pipeline.validate_configuration(config)
    assert profile['docker_resources']['agent']=={'cpus':2,'memory_bytes':32*1024**3,'pids_limit':256}
    assert set(DiagnosisRunner(ROOT).resolve(config)['enabled_check_ids'])=={f'Q{i:02d}' for i in range(1,13)}
    registry=yaml.safe_load(pipeline.REGISTRY.read_text())['nodes']
    assert len(registry)==11 and registry['independent_recovery']=='sheets_factory.nodes.quality:RecoveryNode'
    assert registry['trajectory']=='sheets_factory.nodes.quality:TrajectoryNode'
    assert nodes.PLAN_ADAPTATION_COUNTS=={'material':1,'label':1}
    assert pipeline.NativeQualityFactory.run_phase.__code__ is pipeline.base.NativeQualityFactory.run_phase.__code__
    assert pipeline.NativeQualityFactory.run_phase.__globals__ is not pipeline.base.NativeQualityFactory.run_phase.__globals__
    assert nodes.ConstructNode.execute.__code__ is nodes.frozen.ConstructNode.execute.__code__
    assert nodes.ConstructNode.execute.__globals__ is not nodes.frozen.ConstructNode.execute.__globals__
    assert pipeline.base.SETTING=='heterogeneous_native_quality'


@pytest.mark.parametrize('problem',['check','policy','Harbor','DBG','model','concurrency','filter','transport'])
def test_configuration_cannot_reduce_normal_quality(tmp_path,problem):
    config=configuration(tmp_path)
    if problem=='check':config['diagnosis']['selection']['exclude']=['Q04']
    elif problem=='policy':config['diagnosis']['reference_evidence_policy']='independent_public_recovery'
    elif problem=='Harbor':config['harbor']['execute_controls']=False
    elif problem=='DBG':config['run']['targets']['debugging']=1
    elif problem=='model':config['agents']['model']='gpt-6.1-sol'
    elif problem=='concurrency':config['run']['max_parallel_sources']=3
    elif problem=='filter':config['run']['source_filter']='a different seed'
    else:config['diagnosis']['execution']['reference_evidence_transport']='none'
    with pytest.raises(ValueError):pipeline.validate_configuration(config)


def test_plan_has_dynamic_identity_and_complete_forecast_scope(boundary):
    live=admitted(boundary);proof=pipeline.admission(live);plan=nodes.canonical_plan(live)
    assert len(plan['edits'])==62322 and all(v['after'] is None for v in plan['edits'])
    assert plan['family_adapter']['material_identity']==proof['material_identity']
    assert plan['public_instruction'].encode()==files.checked(proof['instruction']).read_bytes()
    assert plan['scenario_inputs']==[] and plan['public_rules']==['Declared local policy.']
    assert not plan['family_adapter']['normal_quality_or_score_inherited']


def test_prepare_warm_and_cold_are_same_immutable_inventory_without_services(boundary,tmp_path,monkeypatch):
    f=boundary;module=entry();out=tmp_path/'normal'
    def configure(path,destination,proofs):
        config=configuration(destination);config['run'].update(targets={'financial_modeling':len(proofs),'debugging':0},
            max_sources=len(proofs),max_parallel_sources=1,seed_manifest=str(destination/'seed_manifest.json'))
        config['host_runtime']={'fixture':'zero-service'};return config
    monkeypatch.setitem(module._namespace,'configure',configure)
    monkeypatch.setitem(module._namespace,'recipes',lambda *args:{f.other['path']:f.other['sha256']})
    monkeypatch.setattr(module,'execute_prepared',lambda *a,**k:pytest.fail('No actual quality services in prepare'))
    ref=module.prepare([f.terminal],out);frozen=files.read(ref)
    assert frozen['count']==1 and frozen['targets']=={'financial_modeling':1,'debugging':0}
    assert all(frozen[k]==0 for k in ('actual_models','actual_LO_calls','actual_Harbor_jobs','task_count'))
    assert len(f.calls)==1 and module.validate_prepared(out)[0]==frozen and len(f.calls)==1
    module._namespace['_SESSIONS'].clear();checked,config,admissions=module.validate_prepared(out)
    assert checked==frozen and len(f.calls)==2
    seed=files.read(frozen['prepared_seed_manifest'])['selected'][0]
    assert seed['modes']==['financial_modeling'] and not seed['finance_evidence']['debugging_eligible']
    assert 'cohort business fields' in seed['finance_evidence']['financial_evidence_scope']
    factory=pipeline.NativeQualityFactory(config,SimpleNamespace(update_run=lambda **kwargs:None),None,None,admissions=admissions)
    loaded=factory.load_seeds()[0]
    assert all(loaded[key]==value for key,value in seed.items()) and isinstance(factory.load_node('diagnose'),nodes.DiagnoseNode)
    assert factory.load_node('independent_recovery').__class__.__module__=='sheets_factory.nodes.quality'


@pytest.mark.parametrize('clean',[True,False])
def test_three_current_normal_calculations_and_owned_cleanup_still_required(boundary,tmp_path,monkeypatch,clean):
    f=boundary;live=admitted(f);proof=pipeline.admission(live);history=[];calls=[];saved={}
    class Engine:
        def metadata(self):return {'actual_resource_receipts':history[:]}
        def recalculate(self,source,output):
            calls.append(source);output.write_bytes(b'only a mocked native control')
            history.append(files.write(tmp_path/(str(len(calls))+'_resource.json'),{'fixture':True}))
    f.helper.source.validate_call=lambda call,record,frozen:{'container_id':str(call['index'])*64,'terminal':record}
    f.helper.source.owned_absence=lambda rows:{'all_owned_containers_absent':clean,'daemon_reachable':True,
        'owned':[{'full_id':v['actual_resource_evidence']['container_id'],'absent':True} for v in rows]}
    def compare(source,goal,output):
        return {'reward':0 if Path(output)==Path(proof['input']['path']) or Path(output).stem in ('missed_root','extra_change') else 1}
    monkeypatch.setattr(nodes.base,'compare_files',compare)
    ctx=SimpleNamespace(config=configuration(tmp_path),mode='financial_modeling',source=Path(proof['workbook']['path']),
        data={'_native_scope_admission':live,'input':Path(proof['input']['path']),'goal':Path(proof['goal']['path']),'revision_hash':'current'},
        revision_dir=tmp_path/'revision',engine=Engine(),save=lambda name,row:saved.update({name:row}))
    if clean:assert nodes.ControlsNode().execute(ctx)['controls']=={name:{'reward':v} for name,v in nodes.REWARDS.items()}
    else:
        with pytest.raises(ValueError,match='owned-cleanup'):nodes.ControlsNode().execute(ctx)
        assert 'local_controls.json' not in saved
    assert calls==[files.checked(f.prepared['planned_inputs'][name]) for name in ('equivalent','FM_missed_root','extra_change')]


@pytest.mark.parametrize('problem',[None,'unreleasable','stale_binding','missing_Q04','disabled_Q12'])
def test_original_complete_supported_reference_gate_remains_decisive(reference_context,problem):
    from test_reference_evidence_policy import diagnose
    report=diagnose(reference_context);reference_context.data['diagnosis']=report
    if problem=='unreleasable':report['releasable']=False
    elif problem=='stale_binding':report['reference_binding']={'stale':True}
    elif problem=='missing_Q04':report['assessments']['Q04']['evidence']=[]
    elif problem=='disabled_Q12':report['enabled_check_ids'].remove('Q12')
    if problem:
        with pytest.raises(ValueError):nodes.validate_reference_export(reference_context)
    else:
        assert nodes.validate_reference_export(reference_context)['passed']
        assert not report['reference_review']['independent_public_recovery']


@pytest.fixture
def resource_case(tmp_path,monkeypatch):
    r=legacy_resources.__wrapped__(tmp_path,monkeypatch);checker=r.runner.validate_trial_observations;r.runner=entry()
    monkeypatch.setitem(r.runner._namespace,'validate_trial_observations',checker)
    for path in r.results:
        result=json.loads(path.read_text());agent=result['agent_info']['name']
        thin={'task':{**result['config']['task'],'source':'SpreadsheetEval'},'trial_name':path.parent.name,
            'trials_dir':str(path.parent.parent),'job_id':'job-'+agent}
        rich={**deepcopy(thin),'agent':{'name':agent}}
        if agent=='nop':thin['agent']={'name':'nop'}
        path.with_name('config.json').write_text(json.dumps(thin));result['config']=rich;path.write_text(json.dumps(result))
    return r


@pytest.mark.parametrize('shape',['base5','rich7'])
def test_real_resource_package_accepts_exact_base_and_rich_bindings(resource_case,shape):
    from sheets_factory.evaluation.resource_harbor import inspect_resource_export
    r=resource_case
    if shape=='rich7':
        binding=inspect_resource_export(r.original);r.audit.task('unit-task',harbor_export_binding=binding)
        batch=json.loads(r.batch.read_text());batch['export_bindings'][binding['task_name']]=binding;r.batch.write_text(json.dumps(batch))
    report=r.runner.validate_normal_resources(r.out,r.audit,r.observer)
    assert report['passed'] and report['qualified_tasks_checked']==1 and len(r.calls)==2
    assert r.runner.RESOURCE_ADAPTATION_COUNTS=={'agent_identity':1,'resource_binding':2}


@pytest.mark.parametrize('problem',['missing_observer','observer_role','binding_extra','binding_partial','wrong_agent','wrong_reward','resource_package'])
def test_actual_resource_gap_quarantines_only_original_and_retains_raw_rewards(resource_case,monkeypatch,problem):
    r=resource_case;observer=r.observer
    if problem=='missing_observer':observer=None
    elif problem=='observer_role':monkeypatch.setitem(r.runner._namespace,'validate_trial_observations',lambda *a,**k:{'passed':False,'complete':False})
    elif problem in ('binding_extra','binding_partial'):
        task=r.audit.snapshot()['tasks'][0];binding=deepcopy(task['harbor_export_binding'])
        if problem=='binding_extra':binding['unreviewed']='value'
        else:binding.pop('revision')
        r.audit.task('unit-task',harbor_export_binding=binding)
        batch=json.loads(r.batch.read_text());batch['export_bindings'][binding['task_name']]=binding;r.batch.write_text(json.dumps(batch))
    elif problem=='resource_package':(r.original/'tests/runtime_profile.json').write_text('{}')
    else:
        path=r.results[0];result=json.loads(path.read_text())
        if problem=='wrong_agent':result['agent_info']['name']='nop'
        else:result['verifier_result']['rewards']['reward']=0
        path.write_text(json.dumps(result))
    before={str(p):p.read_bytes() for p in r.results}
    report=r.runner.validate_normal_resources(r.out,r.audit,observer)
    assert not report['passed'] and report['missing_evidence_is_not_model_zero']
    assert before=={str(p):p.read_bytes() for p in r.results}
    task=r.audit.snapshot()['tasks'][0]
    assert task['status']=='infrastructure_failed' and task['harbor_controls'] is None
    assert not r.original.exists() and r.staged.exists()


def summarized_review(fixture,module,compact):
    root,run,audit,ctx=fixture;base=ctx.revision_dir
    context_path=base/'private/reference_evidence_context.json';context=json.loads(context_path.read_text())
    context['complete_test_inventory']=list(range(12 if compact else 2))
    context_path.write_text(json.dumps(context));receipt_path=base/'private/reference_review.json'
    receipt=json.loads(receipt_path.read_text());receipt['artifacts']['reference_evidence_context.json']={
        'path':str(context_path.resolve()),'sha256':hashlib.sha256(context_path.read_bytes()).hexdigest()}
    receipt_path.write_text(json.dumps(receipt));diagnosis_path=base/'private/diagnosis.json';diagnosis=json.loads(diagnosis_path.read_text())
    diagnosis['reference_review']=receipt
    evidence_path=next(base.glob('diagnostic_private-*/evidence.json'));evidence=json.loads(evidence_path.read_text())
    private=evidence['private'];private['reference_review_context']=context
    transport=module.reference_evidence.reference_review_evidence(private,base/'private/review_artifacts')
    evidence.update(private=transport['private_summary'],private_evidence=transport)
    evidence_path.write_text(json.dumps(evidence))
    stable={k:v for k,v in evidence.items() if k!='diagnostic_run_id'}
    for batch in diagnosis['llm_batches']:
        if batch['visibility']=='review':batch['payload_digest']=hashlib.sha256(json.dumps(stable,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
    diagnosis_path.write_text(json.dumps(diagnosis))
    return SimpleNamespace(root=root,run=run,audit=audit,ctx=ctx,context=context,evidence=evidence,
        evidence_path=evidence_path,diagnosis=diagnosis,diagnosis_path=diagnosis_path)


@pytest.mark.parametrize('compact',[False,True])
def test_private_reporter_validates_genuine_full_and_compact_transport_without_old_globals(reviewed_run,compact):
    module=entry();r=summarized_review(reviewed_run,module,compact)
    before={str(p):p.read_bytes() for p in r.ctx.revision_dir.rglob('*') if p.is_file()}
    report=module.generate_report(r.run,project_root=r.root)
    assert report['yield']['verified_qualified']==1 and report['tasks'][0]['reference_validation']['verified']
    assert report['tasks'][0]['independent_recovery']['verified'] is False
    assert before=={str(p):p.read_bytes() for p in r.ctx.revision_dir.rglob('*') if p.is_file()}
    assert module.reference_review.__globals__ is not module.reporting._reference_review.__globals__
    if compact:assert not module.reporting._reference_review(r.run,r.audit.snapshot()['tasks'][0])['verified']


@pytest.mark.parametrize('problem',['full','compact','inventory','binding','no_summary','duplicate_fragment'])
def test_reporter_rejects_changed_full_compact_inventory_or_binding(reviewed_run,problem):
    module=entry();r=summarized_review(reviewed_run,module,True);evidence=r.evidence
    if problem=='compact':evidence['private']['reference_review_context']['complete_test_inventory']['count']-=1
    elif problem=='inventory':evidence['private_evidence']['field_inventory']['reference_review_context']['sha256']='0'*64
    elif problem=='binding':evidence['private']['goal_sha256']='0'*64
    elif problem=='no_summary':evidence['private_evidence']['summary_is_not_a_quality_verdict']=False
    else:
        record=evidence['private_evidence']['full_artifact'];path=Path(record['path']);private=json.loads(path.read_text())
        if problem=='full':private['reference_review_context']['complete_test_inventory'][0]=999
        else:private['other']={'reference_review_context':r.context}
        path.write_bytes(module.reference_evidence._bytes(private));record.update(files.reference(path))
    evidence_path=r.evidence_path;evidence_path.write_text(json.dumps(evidence))
    stable={k:v for k,v in evidence.items() if k!='diagnostic_run_id'}
    for batch in r.diagnosis['llm_batches']:
        if batch['visibility']=='review':batch['payload_digest']=hashlib.sha256(json.dumps(stable,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
    r.diagnosis_path.write_text(json.dumps(r.diagnosis))
    report=module.generate_report(r.run,project_root=r.root)
    assert report['yield']['reported_qualified']==1 and report['yield']['verified_qualified']==0
    assert not report['tasks'][0]['reference_validation']['verified']


def test_cli_panel_precedes_cold_work_and_same_process_run_uses_prepared_session(tmp_path,monkeypatch):
    from contextlib import contextmanager
    module=entry();events=[]
    @contextmanager
    def monitor(*a,**k):
        events.append('panel');yield {'passed':False,'inner_exit_code':None}
    monkeypatch.setattr(module,'admission_monitor',monitor)
    monkeypatch.setattr(module,'prepare',lambda *a,**k:events.append('prepare'))
    monkeypatch.setattr(module,'execute_prepared',lambda *a,**k:events.append('run') or 0)
    assert module.main(['--actual-terminal','/genuine','--output',str(tmp_path/'normal'),'--run'])==0
    assert events==['panel','prepare','run']


def test_real_cloned_monitor_opens_lease_panel_before_work_and_closes_exact_resources(tmp_path,monkeypatch):
    module=entry();ns=module.admission_monitor.__wrapped__.__globals__;events=[]
    class Audit:
        def __init__(self,*args):self.db=SimpleNamespace(close=lambda:events.append('closed'))
        def snapshot(self):return {}
        def events(self,*args):return []
        def update_run(self,**kwargs):pass
        def export(self):pass
    class Panel:
        def __init__(self,*a,**k):pass
        def start(self):events.append('panel');return 'http://fixture.invalid'
        def stop(self):events.append('stopped')
    class Lease:
        def __init__(self,*a):pass
        def acquire(self):events.append('lease');return self
        def release(self):events.append('released')
    monkeypatch.setitem(ns,'AuditStore',Audit);monkeypatch.setitem(ns,'DashboardServer',Panel);monkeypatch.setitem(ns,'ProducerLease',Lease)
    out=tmp_path/'normal'
    with module.admission_monitor(out,'prepare',declared_count=9) as state:
        assert events==['lease','panel'] and not out.exists();events.append('cold');state['passed']=True
    assert events==['lease','panel','cold','stopped','closed','released']
    terminal=files.read(next(tmp_path.glob('normal_prepare_monitor_*/terminal.json')))
    assert terminal['kind']=='financial_cohort_FM_normal_admission_outer_monitor' and terminal['inner_passed']
    assert terminal['qualified'] is False and terminal['monitor_does_not_launch_native_models_or_LO']
