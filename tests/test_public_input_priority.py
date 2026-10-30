"""Offline routing/binding tests; fixture receipts do not certify financial truth."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from sheets_factory.core.audit import AuditStore
from sheets_factory.core.node import TaskContext
from sheets_factory.reporting import read_run
from sheets_factory.resume import ResumeError
from sheets_factory.task_adapters import public_input_priority as policy

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('priority_resume',ROOT/'scripts/resume_public_contract_quality.py')
entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
    return policy.ref(path)


def fixture_source(folder):
    folder.mkdir(parents=True)
    book=folder/'source.xlsx';book.write_bytes(b'Offline binding fixture; not an actual financial audit')
    source=policy.ref(book)
    finding={'profile_id':'fixture','source':source,'confirmed_conflict':True,'source_unchanged':True}
    scan=dump(folder/'scan.json',{'findings':[finding]})
    annual={str(year):{'year':year,'variable_rent_total':'100.00','mapped_variable_rent_total':'100.00',
        'unique_fixed_point':True,'proof':{'unique_on_entire_contractual_grid':True,'endpoint_coalescence':True,
        'lower_fixed_point':'100.00','upper_fixed_point':'100.00'}} for year in range(2024,2044)}
    original=dump(folder/'original_programme.json',{'contingent_recovery':{'annual':annual}})
    source_manifest=dump(folder/'source_manifest.json',{'fixture':True})
    scenarios=dump(folder/'scenarios.json',{'fixture':True})
    bindings=dump(folder/'bindings.json',{'fixture':True})
    actual=dump(folder/'actual.json',{'passed':True,'checked_cells':180,'mismatches':[],'control_mismatches':[]})
    proof=dump(folder/'proof.json',{'source':source,'source_manifest':source_manifest,'public_scenarios':scenarios,
        'original_programme_ledger':original,'programme_bindings':bindings,'annual_results':annual,
        'all_twenty_years_equal_original':True,'actual_reference_audit':actual})
    record=dump(folder/'record.json',{'source':source,'source_scan':scan,'finding':finding,'numeric_reference_proof':proof,
        'confirmed_conflict':True,'labelled_and_JSON_inputs_agree':True,'reference_matches_numeric_policy':True})
    return {'book':book,'identity':source['sha256'],'record':record,'scan':scan,'proof':proof,
            'original':original,'source_manifest':source_manifest}


@pytest.fixture
def context(tmp_path):
    source=fixture_source(tmp_path/'source');identity=source['identity'];task='fm-'+identity[:12]
    folder=tmp_path/'task';private=folder/'revisions/000/private';public=private.parent/'public'
    private.mkdir(parents=True);public.mkdir()
    plan={'public_instruction':'Complete the provided workbook.','public_rules':['Keep the supplied values.'],
          'edits':[{'sheet':'Forecast','cell':'B1','before':'=A1*2','after':None}],
          'scenario_inputs':[],'reference_evidence':['Original independent reference']}
    plan_ref=dump(private/'plan.json',plan)
    input_file=public/'input.xlsx';input_file.write_bytes(b'masked public fixture')
    instruction=public/'instruction.md';instruction.write_text('Original public instruction\n')
    revision_hash=hashlib.sha256(input_file.read_bytes()+instruction.read_bytes()).hexdigest()
    issue={'issue_id':'old-Q02','problem_id':'Q02','certainty':'confirmed','claim':'A claim-lag public ambiguity',
           'route_id':'R02','evidence':['fixture'],'severity':'blocker'}
    diagnosis={'task_revision_hash':revision_hash,'issues':[issue],'releasable':False,
               'assessments':{'Q02':{'state':'flagged'},'Q04':{'state':'unknown'}}}
    diagnosis_ref=dump(private/'diagnosis.json',diagnosis)
    new_issue=entry.review_issue(task,0,revision_hash,source['record'])
    review=dump(tmp_path/'review.json',{'task_id':task,'revision':0,'issues':[new_issue]})
    auth={'revision':0,'source_sha256':identity,'revision_hash':revision_hash,'plan':plan_ref,
        'baseline':policy.ref(source['book']),'goal':policy.ref(source['book']),'input':policy.ref(input_file),
        'instruction':policy.ref(instruction),'diagnosis':diagnosis_ref,'program_review':review,
        'authorized_issue_ids':['old-Q02',new_issue['issue_id']]}
    manifest={'kind':'public_input_priority_binding','rule':policy.RULE,'sources':{identity:source['record']},'tasks':{task:auth}}
    manifest_path=tmp_path/'policy_binding.json';manifest_ref=dump(manifest_path,manifest)
    config={policy.POLICY:{'version':1,'rule':policy.RULE,'manifest':manifest_ref}}
    ctx=TaskContext('offline',task,'financial_modeling',source['book'],folder,config,None,None,None,
        data={'source_id':identity,'plan':deepcopy(plan),'diagnosis':deepcopy(diagnosis),
              'repair_routes':[{'issue_id':'old-Q02','problem_id':'Q02','route_id':'R02','route_class':'repair'}]})
    return ctx,source,manifest,manifest_path


def rebind(context):
    ctx,source,manifest,path=context
    ctx.config[policy.POLICY]['manifest']=dump(path,manifest)


def test_rule_changes_only_public_rules_and_is_idempotent(context):
    ctx,*_=context;original=deepcopy(ctx.data['plan'])
    result=policy.append_rule(original)
    assert result['public_rules'][-1]==policy.RULE and original==ctx.data['plan']
    assert {k:v for k,v in result.items() if k!='public_rules'}=={k:v for k,v in original.items() if k!='public_rules'}
    assert policy.append_rule(result)==result


def test_wrapped_plan_calls_original_planner_then_adds_explicit_rule(context,monkeypatch):
    ctx,*_=context;original={'plan':deepcopy(ctx.data['plan']),'source_assessment':{'fixture':True}}
    called=[]
    monkeypatch.setattr(policy.PlanNode,'execute',lambda self,c:called.append(c) or original)
    result=policy.PriorityPlanNode().execute(ctx)
    assert called==[ctx] and result['source_assessment']==original['source_assessment']
    assert policy.RULE in result['plan']['public_rules'] and policy.RULE not in original['plan']['public_rules']


def test_unbound_source_uses_original_planner_without_policy(context,monkeypatch):
    ctx,*_=context;ctx.config={};marker={'plan':{'original':True}}
    monkeypatch.setattr(policy.PlanNode,'execute',lambda self,c:marker)
    assert policy.PriorityPlanNode().execute(ctx) is marker


def test_changed_source_rejects_before_original_planner_or_model(context,monkeypatch):
    ctx,source,*_=context;source['book'].write_bytes(b'changed')
    monkeypatch.setattr(policy.PlanNode,'execute',lambda *a:pytest.fail('Source binding must fail first'))
    with pytest.raises(ValueError,match='Changed'):
        policy.PriorityPlanNode().execute(ctx)


@pytest.mark.parametrize('defect',['missing_year','unequal_endpoint','reference_mismatch','failed_cache_audit'])
def test_numeric_reference_proof_cannot_be_replaced_by_a_passed_boolean(context,defect):
    ctx,source,manifest,path=context
    proof=policy.read(source['proof'])
    if defect=='missing_year':proof['annual_results'].pop('2036')
    elif defect=='unequal_endpoint':proof['annual_results']['2036']['proof']['upper_fixed_point']='200.00'
    elif defect=='reference_mismatch':proof['annual_results']['2036']['variable_rent_total']='200.00'
    else:
        audit=policy.read(proof['actual_reference_audit']);audit['passed']=False
        proof['actual_reference_audit']=dump(Path(proof['actual_reference_audit']['path']),audit)
    proof_ref=dump(Path(source['proof']['path']),proof)
    record=policy.read(source['record']);record['numeric_reference_proof']=proof_ref
    manifest['sources'][source['identity']]=dump(Path(source['record']['path']),record);rebind(context)
    with pytest.raises(ValueError):policy.binding(ctx)


def test_priority_repair_preserves_old_diagnosis_plan_and_numeric_goal(context):
    ctx,source,manifest,path=context
    before_plan=deepcopy(ctx.data['plan']);before_diag=deepcopy(ctx.data['diagnosis']);before_goal=source['book'].read_bytes()
    result=policy.PriorityRepairNode().execute(ctx)
    assert policy.RULE in result['next_plan']['public_rules']
    assert ctx.data['plan']==before_plan and ctx.data['diagnosis']==before_diag and source['book'].read_bytes()==before_goal
    receipt=json.loads((ctx.revision_dir/'private/public_input_priority_repair.json').read_text())
    assert receipt['old_diagnostic_clearance_claimed'] is False and receipt['requires_full_new_revision_quality'] is True


@pytest.mark.parametrize('problem',['Q04','Q11','Q12'])
def test_unrelated_confirmed_issue_is_delegated_to_original_repair(context,monkeypatch,problem):
    ctx,*_=context;ctx.data['repair_routes'].append({'issue_id':'unrelated','problem_id':problem,'route_class':'repair'})
    marker={'next_plan':None};called=[]
    monkeypatch.setattr(policy.RepairNode,'execute',lambda self,c:called.append(c) or marker)
    assert policy.PriorityRepairNode().execute(ctx) is marker and called==[ctx]


def authorize_q04(context):
    ctx,source,manifest,path=context;auth=manifest['tasks'][ctx.task_id]
    diagnosis=policy.read(auth['diagnosis'])
    diagnosis['issues'].append({'issue_id':'old-Q04','problem_id':'Q04','certainty':'confirmed',
        'claim':'Two different fixed points under the public terms','severity':'blocker'})
    auth['diagnosis']=dump(Path(auth['diagnosis']['path']),diagnosis)
    auth['authorized_issue_ids'].append('old-Q04')
    audit=dump(path.parent/'counter_numeric_audit.json',{'offline_fixture':True})
    counter={'source_sha256':source['identity'],'diagnosis_sha256':auth['diagnosis']['sha256'],
        'related_issue_ids':['old-Q04'],'numeric_counterexample_audit':audit,
        'Q04_counterexample_does_not_establish_source_nonuniqueness':True}
    auth['counterexample_review']=dump(path.parent/'counter_review.json',counter)
    ctx.data['repair_routes']=[{'issue_id':'old-Q04','problem_id':'Q04','route_id':'R04','route_class':'repair'}]
    rebind(context)
    return auth,counter


def test_q04_with_numeric_counter_review_still_uses_original_repair(context,monkeypatch):
    ctx,*_=context;auth,counter=authorize_q04(context)
    before=Path(auth['diagnosis']['path']).read_bytes()
    marker={'next_plan':None};called=[]
    monkeypatch.setattr(policy.RepairNode,'execute',lambda self,c:called.append(c) or marker)
    assert policy.PriorityRepairNode().execute(ctx) is marker and called==[ctx]
    assert Path(auth['diagnosis']['path']).read_bytes()==before


@pytest.mark.parametrize('defect',['problem_relabel','route_relabel'])
def test_q04_cannot_be_relabelled_as_a_public_priority_q02(context,defect):
    ctx,*_=context;auth,counter=authorize_q04(context)
    ctx.data['repair_routes'][0]['problem_id']='Q02'
    ctx.data['repair_routes'][0]['route_id']='R02' if defect=='problem_relabel' else 'R04'
    auth['counterexample_review']=dump(Path(auth['counterexample_review']['path']),counter);rebind(context)
    with pytest.raises(ValueError):policy.PriorityRepairNode().execute(ctx)


@pytest.mark.parametrize('field',['task_id','revision','revision_hash'])
def test_program_review_must_match_exact_closed_task_and_revision(context,field):
    ctx,source,manifest,path=context;auth=manifest['tasks'][ctx.task_id]
    review=policy.read(auth['program_review']);review['issues'][0][field]='wrong'
    auth['program_review']=dump(Path(auth['program_review']['path']),review);rebind(context)
    with pytest.raises(ValueError,match='revision binding'):policy.PriorityRepairNode().execute(ctx)


@pytest.mark.parametrize('table_value',[2,True,'1'])
def test_fresh_source_audit_rejects_labelled_json_disagreement_before_numeric_replay(tmp_path,monkeypatch,table_value):
    import openpyxl
    from sheets_factory.workbook.lease_finance import ledger
    folder=tmp_path/'source';folder.mkdir();book_path=folder/'source.xlsx'
    book=openpyxl.Workbook();book.active.title='Model Input Contracts'
    book.create_sheet('Reopener Inputs');book.create_sheet('Reopener Brief')
    programme={'parameters':{'claim_lag_years':1}}
    book['Model Input Contracts']['B5']=json.dumps(programme)
    book['Reopener Inputs']['A33']='claim lag years';book['Reopener Inputs']['B33']=table_value
    text='A two-year collection lag applies. A claim first becomes collectible two years after its creation.'
    book['Reopener Brief']['A21']=text;book.save(book_path);book.close()
    scenarios=dump(folder/'scenarios.json',{'programme':programme})
    manifest=dump(folder/'manifest.json',{'public_scenarios':scenarios});source=policy.ref(book_path)
    finding={'source':source,'source_unchanged':True,'confirmed_conflict':True,
        'structured_parameter':{'sheet':'Model Input Contracts','cell':'B5','value':1},
        'labelled_input':{'sheet':'Reopener Inputs','label_cell':'A33','value_cell':'B33','label':'claim lag years','value':1},
        'narrative':{'sheet':'Reopener Brief','cell':'A21','text':text}}
    scan=dump(folder/'scan.json',{'findings':[finding]})
    seed={'local_path':str(book_path),'sha256':source['sha256'],'source_manifest':manifest}
    monkeypatch.setattr(ledger,'simulate_lease',lambda *a,**k:pytest.fail('Contradictory public numeric inputs must fail first'))
    with pytest.raises(ValueError,match='labelled and JSON'):policy.audit_source(seed,scan,tmp_path/'audit')


@pytest.mark.parametrize('defect',['stale_revision','plan','goal','revision_hash'])
def test_changed_closed_revision_cannot_get_deterministic_repair(context,defect):
    ctx,source,manifest,path=context;auth=manifest['tasks'][ctx.task_id]
    if defect=='stale_revision':ctx.revision=1
    elif defect=='plan':ctx.data['plan']['edits'][0]['cell']='B2'
    elif defect=='goal':
        alternate=source['book'].with_name('different_goal.xlsx');alternate.write_bytes(b'different goal')
        auth['goal']=policy.ref(alternate)
    else:auth['revision_hash']='0'*64
    rebind(context)
    with pytest.raises(ValueError):policy.PriorityRepairNode().execute(ctx)


def test_registry_changes_only_plan_and_repair_and_preserves_phase_order():
    entry.validate_registry()
    registry=yaml.safe_load(entry.REGISTRY.read_text())['nodes'];original=yaml.safe_load((ROOT/'config/nodes.yaml').read_text())['nodes']
    assert {k for k in registry if registry[k]!=original[k]}=={'plan','repair'}
    template=yaml.safe_load((ROOT/'src/sheets_factory/pipelines/templates/financial_modeling.yaml').read_text())
    assert template['phases']['revision']==['construct','instruction','precheck','independent_recovery','trajectory','diagnose']


def test_missing_diagnosis_template_is_program_only_and_never_a_quality_pass():
    issue=entry.review_issue('fm-offline',0,'a'*64,{'path':'/fixture','sha256':'b'*64})
    report=entry.program_only_diagnosis('fm-offline',0,'a'*64,issue)
    assert report['program_only'] is True and report['releasable'] is False
    assert report['assessments']['Q02']['state']=='flagged'
    assert all(v['state']=='unknown' for k,v in report['assessments'].items() if k!='Q02')
    assert len(report['coverage']['unknown_check_ids'])==11


def make_run(tmp_path,monkeypatch,*,diagnosis_exists=True,status='cancelled'):
    source=fixture_source(tmp_path/'source');run=tmp_path/'run';run.mkdir()
    task='fm-'+source['identity'][:12];private=run/'tasks'/task/'revisions/000/private';public=private.parent/'public'
    private.mkdir(parents=True);public.mkdir()
    source_proof={'workbook':policy.ref(source['book'])}
    seed={'sha256':source['identity'],'local_path':str(source['book']),'source_manifest':source['source_manifest'],
          'finance_evidence':{'audited_source_binding':source_proof},'modes':['financial_modeling']}
    seeds=run/'seed_manifest.json';dump(seeds,{'selected':[seed]})
    plan={'public_instruction':'Complete model','public_rules':['Original rule'],'edits':[{'sheet':'Forecast','cell':'B1'}],'scenario_inputs':[]}
    dump(private/'plan.json',plan)
    baseline=run/'sources'/source['identity'][:12]/'baseline.xlsx';baseline.parent.mkdir(parents=True);baseline.write_bytes(source['book'].read_bytes())
    (private/'goal.xlsx').write_bytes(source['book'].read_bytes());(public/'input.xlsx').write_bytes(b'input fixture')
    (public/'instruction.md').write_text('Instruction fixture')
    revision_hash=hashlib.sha256((public/'input.xlsx').read_bytes()+(public/'instruction.md').read_bytes()).hexdigest()
    if diagnosis_exists:dump(private/'diagnosis.json',{'task_revision_hash':revision_hash,'issues':[],'releasable':True})
    config={'project_root':str(ROOT),'run_dir':str(run),'run':{'targets':{'financial_modeling':10,'debugging':10},
        'seed_manifest':str(seeds),'max_steps':3,'max_evidence_rounds_per_revision':2,'infrastructure_retries_per_stage':2,
        'max_additional_trials_per_revision':0,'max_sources':20,'max_parallel_sources':2,'scheduler':'rolling'},
        'agents':{'model':'gpt-6-sol','reasoning_effort':'high'},'engine':{'timeout_seconds':1},
        'host_runtime':entry.cohort.host_runtime_settings(run)}
    (run/'resolved_config.yaml').write_text(yaml.safe_dump(config))
    frozen={'recipe_sha256':{str(ROOT/'config/nodes.yaml'):policy.sha(ROOT/'config/nodes.yaml')},
        'source_artifacts_sha256':{str(source['book']):source['identity']},'prepared_seed_manifest':policy.ref(seeds),
        'host_runtime':deepcopy(config['host_runtime'])}
    dump(run/'preflight_manifest.json',frozen)
    audit=AuditStore(run,{'id':'offline','status':status,'producer_active':False,'wall_seconds':1})
    audit.task(task,source_id=source['identity'],mode='financial_modeling',status='cancelled',revision=0)
    monkeypatch.setattr(entry,'DEFAULT_STRONG_MANIFESTS',())
    monkeypatch.setattr(entry.cohort,'validate_seed',lambda s:source_proof)
    monkeypatch.setattr(entry,'audit_source',lambda s,scan,out:source['record'])
    return run,audit,source,task,private,config


@pytest.mark.parametrize('exists',[True,False])
def test_prepare_only_writes_new_evidence_and_never_takes_live_lease(tmp_path,monkeypatch,exists):
    run,audit,source,task,private,config=make_run(tmp_path,monkeypatch,diagnosis_exists=exists,status='constructing')
    before=(run/'resolved_config.yaml').read_bytes();old=(private/'diagnosis.json').read_bytes() if exists else None
    monkeypatch.setattr(entry.ProducerLease,'acquire',lambda self:pytest.fail('Preparation must not acquire the producer lease'))
    output=tmp_path/'prepared';frozen=entry.prepare(run,source['scan']['path'],output)
    assert frozen['actual_models']==frozen['actual_LO_calls']==0 and frozen['qualified']==0
    assert (run/'resolved_config.yaml').read_bytes()==before
    assert (private/'diagnosis.json').read_bytes()==old if exists else not (private/'diagnosis.json').exists()
    assert frozen['repair_task_ids']==[task]
    assert bool(frozen['missing_diagnoses']) is not exists
    assert entry.validate_prepared(output)==frozen


def test_active_run_is_rejected_before_missing_diagnosis_is_materialized(tmp_path,monkeypatch):
    run,audit,source,task,private,config=make_run(tmp_path,monkeypatch,diagnosis_exists=False,status='constructing')
    output=tmp_path/'prepared';entry.prepare(run,source['scan']['path'],output)
    with pytest.raises(ResumeError,match='terminal'):entry.execute(output)
    assert not (private/'diagnosis.json').exists()


def test_existing_diagnosis_is_never_overwritten_by_missing_template(tmp_path,monkeypatch):
    run,audit,source,task,private,config=make_run(tmp_path,monkeypatch,diagnosis_exists=False)
    output=tmp_path/'prepared';entry.prepare(run,source['scan']['path'],output)
    dump(private/'diagnosis.json',{'new_actual_diagnosis':True});before=(private/'diagnosis.json').read_bytes()
    with pytest.raises(ValueError,match='now exists'):entry.validate_prepared(output)
    assert (private/'diagnosis.json').read_bytes()==before


def test_explicit_terminal_continuation_archives_before_after_and_keeps_quotas_budgets(tmp_path,monkeypatch):
    run,audit,source,task,private,config=make_run(tmp_path,monkeypatch,diagnosis_exists=False)
    output=tmp_path/'prepared';frozen=entry.prepare(run,source['scan']['path'],output)
    old_config=(run/'resolved_config.yaml').read_bytes();old_preflight=(run/'preflight_manifest.json').read_bytes()
    class NoModelBackend:
        def __init__(self,*a,**k):pass
        def _credentials(self):pass
    class NoEngine:
        def __init__(self,*a,**k):pass
        def metadata(self):return {'image_id':entry.cohort.IMAGE_ID}
    class Dashboard:
        def __init__(self,*a,**k):pass
        def start(self):return 'http://offline.test/'
        def stop(self):pass
    observed=[]
    class Pipeline:
        def __init__(self,c,a,llm,engine):observed.append(c);self.audit=a
        def run(self):self.audit.update_run(status='shortfall');return False
    monkeypatch.setattr(entry.cohort,'CohortCodex',NoModelBackend);monkeypatch.setattr(entry.cohort,'LibreOfficeEngine',NoEngine)
    monkeypatch.setattr(entry.cohort,'DashboardServer',Dashboard);monkeypatch.setattr(entry.cohort,'AuditedSourceFactory',Pipeline)
    assert entry.execute(output)==2
    after=yaml.safe_load((run/'resolved_config.yaml').read_text());before=yaml.safe_load(old_config)
    assert after['run']['targets']==before['run']['targets'] and after['agents']==before['agents']
    assert all(after['run'][k]==before['run'][k] for k in entry.PROTECTED_BUDGETS)
    assert after['pipeline']['node_registry']==str(entry.REGISTRY)
    assert (run/'preflight_manifest.json').read_bytes()==old_preflight
    reports=list((run/'private/resume').glob('resolved_config_*_*.yaml'));assert len(reports)==2
    program=json.loads((private/'diagnosis.json').read_text());assert program['program_only'] and not program['releasable']
    addendum=json.loads(next((run/'runtime_supplements').glob('public_priority_continuation_*.json')).read_text())
    assert addendum['config_before']['sha256']!=addendum['config_after']['sha256']
    assert addendum['old_diagnostics_cleared'] is False and addendum['original_preparation_config_hash_is_historical'] is True
    assert observed and read_run(run)['run']['producer_active'] is False


def test_cli_default_only_prepares_and_never_executes(tmp_path,monkeypatch):
    run,audit,source,task,private,config=make_run(tmp_path,monkeypatch)
    monkeypatch.setattr(entry,'execute',lambda *a,**k:pytest.fail('Explicit --run is required'))
    output=tmp_path/'prepared'
    assert entry.main(['--run-directory',str(run),'--source-audit',source['scan']['path'],'--output',str(output)])==0
