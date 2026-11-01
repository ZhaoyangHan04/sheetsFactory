"""Integer economics and saved-output lifecycle; all native calls are mocked."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil

import openpyxl
import pytest

ROOT=Path(__file__).resolve().parents[1]
loader=importlib.util.spec_from_file_location('_test_ring_economics',ROOT/'scripts/diagnose_ringfenced_business_attempts.py')
m=importlib.util.module_from_spec(loader);loader.loader.exec_module(m)
REAL_ADMIT=m._admit


@pytest.fixture
def context():
    ids=[f'P{i:03d}'for i in range(1,361)];rows=[]
    # Synthetic scope fixture: one active capacity, remaining rows are explicit
    # tautologies. This tests the complete941-row checker, not a production gold.
    for family,count in m.model_a.PRODUCTION_COUNTS.items():
        for i in range(count):
            coefficients=[0]*360;limit=0
            if family=='initial_sponsor_equity':coefficients[:2]=[1,1];limit=1
            rows.append({'id':family+f':{i:03d}','family':family,'scenario_id':None,'year':None,
                'coefficients':coefficients,'limit':limit})
    rows.sort(key=lambda x:x['id']);assert len(rows)==941
    model={'kind':m.model_a.KIND,'version':2,'project_ids':ids,'objective_pence':[100,80]+[-1]*358,
        'rows':rows,'specification_sha256':'a'*64,'universe_sha256':'b'*64}
    winner={pid:int(pid=='P001')for pid in ids}
    economics={'winner_plan':{i:dict(winner)for i in m.MANDATES},'winner_objective_pence':200,
        'gap_pence':1,'local':{i:{'winner_objective_pence':100,'gap_pence':1}for i in m.MANDATES}}
    return {'models':{i:{'A':deepcopy(model),'B':deepcopy(model)}for i in m.MANDATES},'economics':economics,
        'portfolio_sheets':{'M01':'Mandate1 Portfolio','M02':'Mandate2 Portfolio'},
        'sheetnames':['Mandate1 Portfolio','Mandate2 Portfolio','Group reporting'],
        'group_sheet':'Group reporting','group_points':{'gate':'B6','objective':'B7'},'guard_refs':[]}


def choices(context,kind):
    result=deepcopy(context['economics']['winner_plan'])
    if kind in('suboptimal','both_suboptimal'):
        result['M01']['P001']=0;result['M01']['P002']=1
        if kind=='both_suboptimal':result['M02']['P001']=0;result['M02']['P002']=1
    elif kind=='infeasible':result['M01']['P002']=1
    return result


def workbook(path,context,plans,*,bad_choice=None,bad_label=False,cache_error=False,extra_sheet=False):
    book=openpyxl.Workbook();book.remove(book.active);total=0;feasible=True
    for identity in m.MANDATES:
        sheet=book.create_sheet(context['portfolio_sheets'][identity]);plan=plans[identity]
        check=m.model_a.check_plan(context['models'][identity]['A'],plan);total+=check['objective_pence'];feasible&=check['feasible']
        sheet['B3']=1;sheet['B369']=int(check['feasible']);sheet['B370']=check['objective_pence']if check['feasible']else None
        for row,pid in enumerate(context['models'][identity]['A']['project_ids'],6):
            sheet.cell(row,1,pid);sheet.cell(row,2,plan[pid])
        if identity=='M01':
            if bad_choice is not None:sheet['B6']=bad_choice
            if bad_label:sheet['A6']='FOREIGN'
            if cache_error:sheet['B370']=999
    sheet=book.create_sheet('Group reporting');sheet['B6']=feasible;sheet['B6'].number_format='General'
    sheet['B7']=total if feasible else None
    if extra_sheet:book.create_sheet('Extra')
    path.parent.mkdir(parents=True,exist_ok=True);book.save(path);book.close();return m.reference(path)


@pytest.mark.parametrize('kind,expected,objective,gap',[('optimal','optimal',200,0),('suboptimal','feasible_suboptimal',180,20),
    ('both_suboptimal','feasible_suboptimal',160,40),('infeasible','infeasible',280,None)])
def test_full720_choices1882_rows_have_exact_hand_calculated_economic_classification(context,kind,expected,objective,gap):
    value=m.evaluate_plans(context['models'],choices(context,kind),context['economics'])
    assert value['classification']==expected and value['objective_pence']==objective and value['economic_shortfall_pence']==gap
    assert value['complete_choice_count']==720 and value['integer_rows_checked']==1882
    assert sum(len(x['rows'])for x in value['mandates'].values())==1882
    assert all(x['A_B_exact_agreement']for x in value['mandates'].values())
    assert value['new_solver_calls']==value['new_financial_forwards']==0 and value['all_financial_fields_certified']is False
    if kind=='infeasible':
        failed=value['mandates']['M01']['failed_rows'];assert len(failed)==1 and failed[0]['slack']==-1


@pytest.mark.parametrize('fault',['nonbinary','boolean','missing_choice','missing_mandate','short_rows','model_disagreement',
    'objective_above_certificate','alternate_tied_winner','contradicts_runner_gap','wrong_total'])
def test_incomplete_or_contradictory_models_are_rejected_not_called_suboptimal(context,fault):
    plans=choices(context,'optimal');models=deepcopy(context['models']);cert=deepcopy(context['economics'])
    if fault=='nonbinary':plans['M01']['P001']=.5
    elif fault=='boolean':plans['M01']['P001']=True
    elif fault=='missing_choice':plans['M01'].pop('P001')
    elif fault=='missing_mandate':plans.pop('M02')
    elif fault=='short_rows':models['M01']['A']['rows'].pop()
    elif fault=='model_disagreement':models['M01']['B']['objective_pence'][0]=101
    elif fault=='objective_above_certificate':cert['local']['M01']['winner_objective_pence']=99
    elif fault=='alternate_tied_winner':cert['winner_plan']['M01']['P003']=1
    elif fault=='contradicts_runner_gap':
        plans=choices(context,'suboptimal');cert['local']['M01']['gap_pence']=21
    else:cert['winner_objective_pence']=201
    with pytest.raises(ValueError):m.evaluate_plans(models,plans,cert)


@pytest.mark.parametrize('bad',[.5,True,'1','',2])
def test_nonbinary_saved_values_are_coverage_not_constraint_failures(tmp_path,context,bad):
    path=tmp_path/'bad.xlsx';workbook(path,context,choices(context,'optimal'),bad_choice=bad)
    value=m.extract_choices(path,context)
    assert value['coverage_issues']and value['coverage_issues'][0]['reason']=='missing_or_nonbinary_choice'
    assert len(value['plans']['M01'])==359


def test_project_identity_and_control_cache_are_distinguished_from_plan_economics(tmp_path,context):
    plans=choices(context,'optimal');path=tmp_path/'label.xlsx';workbook(path,context,plans,bad_label=True)
    assert m.extract_choices(path,context)['coverage_issues'][0]['reason']=='project_identity_mismatch'
    path=tmp_path/'cache.xlsx';workbook(path,context,plans,cache_error=True,extra_sheet=True)
    read=m.extract_choices(path,context);economics=m.evaluate_plans(context['models'],read['plans'],context['economics'])
    assert economics['classification']=='optimal'and not read['coverage_issues']
    assert read['structure_issues']and m.cache_consistency(economics,read['cached_controls'])
    assert economics['all_financial_fields_certified']is False


@pytest.mark.parametrize('lower,upper,passed,effective,state,expected',[
    (10,10,True,0,'complete','within_budget'),(1799,1799,True,1,'complete','within_budget'),
    (1800,1800,False,0,'known_tool_budget_failure','known_budget_failure'),
    (1801,2000,False,0,'known_tool_budget_failure','known_budget_failure'),
    (1799,1801,None,None,'unknown','unknown'),(None,None,None,None,'unknown','unknown'),
    (1800,1800,True,0,'complete','unknown')])
def test_original_strict_v6_budget_boundary_is_separate_from_economic_failure(lower,upper,passed,effective,state,expected):
    row={'actual_attempt':{'tool_time':{'policy_version':6,'budget_seconds':1800,'strict_less_than':True,
        'lower_bound_seconds':lower,'upper_bound_seconds':upper,'passed':passed}},'score':{'effective_reward':effective,'state':state}}
    assert m.budget_status(row)==expected


@pytest.fixture
def run_fixture(tmp_path,monkeypatch,context):
    def put(name,value):return m.write(tmp_path/name,value)
    tasks=[];rows={};selected={};plans=choices(context,'suboptimal')
    for mode in('financial_modeling','debugging'):
        identity='test-ring-'+mode;result_path=tmp_path/identity/'result.json'
        result=put(identity+'/result.json',{'TEST_ONLY':True,'task_name':'sheetsfactory/'+identity,'finished_at':'2026-11-01T08:00:00Z',
            'exception_info':None,'verifier_result':{'rewards':{'reward':0}}})
        workbook(result_path.parent/'artifacts/app/output.xlsx',context,plans)
        tasks.append({'task_id':identity,'mode':mode})
        rows[identity]={'task_id':identity,'mode':mode,'actual_attempt':{'status':'scored','result_file':result['path'],
            'result_sha256':result['sha256'],'raw_verifier_reward':0,'tool_time':{'policy_version':6,'budget_seconds':1800,
                'strict_less_than':True,'lower_bound_seconds':10,'upper_bound_seconds':10,'passed':True}},
            'score':{'state':'complete','effective_reward':0},'resources':{'passed':True,'complete':True,'result':result,'trial_config':{}}}
        selected[identity]={'task_directory':'TEST_ONLY'}
    source=put('source.json',{'TEST_ONLY_mock_source_boundary':True})
    context['certificate']=put('certificate.json',{'TEST_ONLY_mock_certificate_boundary':True})
    batch={'source':source,'tasks':tasks};terminal={'TEST_ONLY_mock_attempt_boundary':True}
    br=put('batch.json',batch);tr=put('terminal.json',terminal)
    monkeypatch.setattr(m,'_admit',lambda a,b:(batch,terminal,rows,selected,{'observation_receipts':[]},context))
    monkeypatch.setattr(m,'validate_trial_observations',lambda *a,**kw:{'passed':True,'complete':True})
    monkeypatch.setattr(m,'resource_check',lambda *a,**kw:{'TEST_ONLY_mock_resource_boundary':True})
    monkeypatch.setattr(m,'owned_absence',lambda r:{'all_owned_containers_absent':True,'daemon_reachable':True})
    class Audit:
        def __init__(self,*a,**kw):self.db=self
        def __getattr__(self,name):return lambda *a,**kw:None
    class Panel:
        def __init__(self,*a,**kw):pass
        def start(self):return 'TEST_ONLY://no-service'
        def stop(self):pass
    monkeypatch.setattr(m,'AuditStore',Audit);monkeypatch.setattr(m,'DashboardServer',Panel)
    calls=[]
    class Engine:
        def __init__(self,root,profile,*,role,receipt_directory):
            assert profile==m.PROFILE and role=='verifier';self.folder=receipt_directory
        def recalculate(self,source,destination):
            calls.append((source,destination));destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,destination)
            self.receipt=put('receipt'+str(len(calls))+'.json',{'TEST_ONLY_mock_native_boundary':True,
                'source':m.reference(source),'output':m.reference(destination)})
            return destination
        def metadata(self):return {'actual_resource_receipts':[self.receipt]}
    monkeypatch.setattr(m,'engine_class',lambda:Engine)
    return locals()


def test_once_per_output_full_integer_diagnosis_preserves_original_scores(run_fixture):
    f=run_fixture;before=deepcopy(f['rows']);result=m.read(m.run(f['br']['path'],f['tr']['path'],f['tmp_path']/'diagnosis'))
    assert result['actual_verifier_LO_calls']==result['actual_verifier_LO_calls_started']==len(f['calls'])==2
    assert result['business_qualified_count']==2 and result['unknown_count']==0
    assert result['new_solver_calls']==result['new_model_calls']==result['new_source_LO_calls']==result['new_financial_forwards']==0
    assert f['rows']==before and result['original_scores_modified']is False
    for row in result['records']:
        evidence=m.read(row['evidence']);assert evidence['classification']=='feasible_suboptimal'
        assert evidence['complete_choice_count']==720 and evidence['integer_rows_checked']==1882
        assert evidence['economic_shortfall_pence']==20 and evidence['original_attempt']['raw_verifier_reward']==0


@pytest.mark.parametrize('case',['success','budget','timing_unknown','no_output','nonbinary','resource_unknown','optimal_cache_error'])
def test_success_budget_coverage_unknown_and_financial_cache_failure_are_not_false_suboptimal_qualification(run_fixture,case):
    f=run_fixture
    for identity,row in f['rows'].items():
        output=Path(row['actual_attempt']['result_file']).parent/'artifacts/app/output.xlsx'
        if case=='success':
            row['actual_attempt']['raw_verifier_reward']=row['score']['effective_reward']=1
            path=Path(row['actual_attempt']['result_file']);value=json.loads(path.read_text());value['verifier_result']['rewards']['reward']=1
            path.write_text(json.dumps(value));record=m.reference(path);row['actual_attempt']['result_sha256']=record['sha256'];row['resources']['result']=record
        elif case=='budget':
            row['actual_attempt']['tool_time'].update(passed=False,lower_bound_seconds=1800,upper_bound_seconds=1800)
            row['score'].update(state='known_tool_budget_failure',effective_reward=0)
        elif case=='timing_unknown':
            row['actual_attempt']['tool_time']['passed']=None;row['score'].update(state='unknown',effective_reward=None)
        elif case=='no_output':output.unlink()
        elif case=='nonbinary':workbook(output,f['context'],f['plans'],bad_choice=.5)
        elif case=='resource_unknown':row['resources']['complete']=False
        else:workbook(output,f['context'],choices(f['context'],'optimal'),cache_error=True)
    result=m.read(m.run(f['br']['path'],f['tr']['path'],f['tmp_path']/case))
    assert result['business_qualified_count']==0
    if case in('budget','no_output','resource_unknown'):assert not f['calls']
    if case=='budget':
        assert all(r['budget_status']=='known_budget_failure'and r['classification']=='unknown'for r in result['records'])
        assert result['unknown_count']==0
    elif case in('timing_unknown','no_output','nonbinary','resource_unknown'):assert result['unknown_count']==2
    elif case=='optimal_cache_error':
        assert all(r['classification']=='optimal'for r in result['records'])
        assert all(m.read(r['evidence'])['cache_consistency_issues']for r in result['records'])
    else:assert all(m.read(r['evidence'])['quality_conflict']for r in result['records'])


def test_native_output_failure_is_retained_with_no_retry(run_fixture,monkeypatch):
    f=run_fixture;calls=[]
    class Engine:
        def __init__(self,*a,**kw):pass
        def recalculate(self,*a):calls.append(1);raise RuntimeError('TEST_ONLY output failure')
    monkeypatch.setattr(m,'engine_class',lambda:Engine);out=f['tmp_path']/'failed'
    with pytest.raises(RuntimeError,match='output failure'):m.run(f['br']['path'],f['tr']['path'],out)
    failure=json.loads((out/'failure.json').read_text())
    assert len(calls)==failure['actual_verifier_LO_calls_started']==1
    assert failure['actual_verifier_LO_calls_completed']==failure['outer_retries']==0
    assert not(out/'terminal.json').exists()


def test_economic_contradiction_is_unknown_and_never_a_false_model_zero(run_fixture):
    f=run_fixture;f['context']['economics']['local']['M01']['winner_objective_pence']=50
    terminal=m.read(m.run(f['br']['path'],f['tr']['path'],f['tmp_path']/'contradiction'))
    assert terminal['unknown_count']==2 and terminal['business_qualified_count']==0
    assert all(r['classification']=='unknown'for r in terminal['records'])
    assert len(f['calls'])==2 and all(m.read(r['evidence'])['business_failure_evidence']is None for r in terminal['records'])


def test_unverified_owned_cleanup_is_retained_as_failure_not_success(run_fixture,monkeypatch):
    f=run_fixture;monkeypatch.setattr(m,'owned_absence',lambda refs:{'all_owned_containers_absent':False,'daemon_reachable':True})
    out=f['tmp_path']/'cleanup-failure'
    with pytest.raises(ValueError,match='cleanup is incomplete'):m.run(f['br']['path'],f['tr']['path'],out)
    assert len(f['calls'])==1 and not(out/'terminal.json').exists()
    failure=json.loads((out/'failure.json').read_text());assert failure['owned_cleanup_evidence']


@pytest.fixture
def admission(tmp_path,monkeypatch,context):
    number=0
    def put(name,value):
        nonlocal number
        number+=1;return m.write(tmp_path/(str(number)+'-'+name),value)
    source=put('source.json',{'TEST_ONLY_mock_fixed_source_admission':True});certificate=put('certificate.json',{'TEST_ONLY':True})
    goal=workbook(tmp_path/'source3.xlsx',context,choices(context,'optimal'))
    context.update(goal=goal,certificate=certificate)
    monkeypatch.setattr(m,'_source',lambda value:context)
    monkeypatch.setattr(m.exports,'inspect_resource_export',lambda directory,**kw:{'TEST_ONLY':str(directory)})
    resource_calls=[];monkeypatch.setattr(m,'resource_check',lambda *a:resource_calls.append(a))
    tasks=[];selected=[];rows=[];native={};inherited=[]
    for mode,prefix in [('financial_modeling','FM'),('debugging','DBG')]:
        identity='admit-'+prefix;directory=tmp_path/'exports'/identity
        (directory/'environment').mkdir(parents=True);(directory/'tests').mkdir()
        shutil.copyfile(goal['path'],directory/'tests/reference.xlsx')
        retained=workbook(tmp_path/(prefix+'-input2.xlsx'),context,choices(context,'suboptimal'))
        shutil.copyfile(retained['path'],directory/'environment/input.xlsx');native[prefix+'_input2']=retained
        receipt=put('input-receipt.json',{'TEST_ONLY':True})
        inherited.append({'role':prefix+'_input2','input':retained,'output':retained,'actual_resource_evidence':{'terminal':receipt}})
        engineering=put('engineering.json',{'TEST_ONLY_mock_whole3M_audit':True,'passed':True,'source':source,'source_certificate':certificate,
            'given_literals_unchanged':True,'sheet_structure_unchanged':True,'native_two_input_typed_stability':True,
            'full_source_formula_count':2494958,'native_error_count':0,
            'actual_programmatic_controls':{k:{'reward':v}for k,v in {'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}.items()}})
        cap=put('cap.json',{'TEST_ONLY':True});binding={'TEST_ONLY':str(directory)}
        task={'task_id':identity,'mode':mode,'task_directory':str(directory),'source_id':goal['sha256'],
            'worker_cap_audit':cap,'harbor_export_binding':binding,'individual_engineering':engineering}
        tasks.append(task);selected.append({'task_id':identity,'harbor_export_binding':binding,'task_checksum':identity})
        result=put('result.json',{'task_name':'sheetsfactory/'+identity,'exception_info':None,'finished_at':'2026-11-01T08:00:00Z',
            'verifier_result':{'rewards':{'reward':0}}})
        rows.append({'task_id':identity,'mode':mode,'actual_attempt':{'status':'scored','task_checksum':identity,
            'result_file':result['path'],'result_sha256':result['sha256'],'raw_verifier_reward':0}})
    chain=put('controls.json',{'kind':'completed_original_R2_01_four_remaining_controls_revision2','passed':True,'source':source,
        'new_LO_calls':4,'results':native,'inherited_input_calls':inherited})
    batch={'kind':'individually_engineered_business_revision_batch','version':1,'count':2,'source':source,
        'tasks':tasks,'selected_task_ids':[t['task_id']for t in tasks],'actual_control_chain':chain}
    br=put('batch.json',batch)
    prepared=put('prepared.json',{'kind':'prepared_business_revision_native_frontier_v1','phase':'development','batches':[br],'tasks':tasks})
    selection=put('selection.json',{'phase':'development','model':'gpt-6.1-sol','reasoning_effort':'xhigh','n_attempts':1,
        'tool_time_policy_version':6,'infrastructure_retry_policy':{'max_retries':0},'tasks':selected})
    resources=put('resources.json',{'observation_receipts':[]})
    terminal={'kind':'business_revision_native_frontier_terminal_v1','version':1,'phase':'development','outer_retries':0,
        'prepared':prepared,'selection':selection,'resources':resources,'results':rows}
    tr=put('terminal.json',terminal)
    return locals()


def test_original_material_and_source_control_lineage_are_bound_before_output_calls(admission):
    f=admission
    admitted=REAL_ADMIT(f['br'],f['tr'])
    assert admitted[0]==f['batch']and len(f['resource_calls'])==2
    assert len(admitted[-1]['guard_refs'])==9


@pytest.mark.parametrize('fault',['foreign_material','goal_drift','input_drift','control_source','control_incomplete',
    'wrong_source_id','engineering_source','engineering_certificate','engineering_controls','engineering_scope',
    'result_reward','selection_retry','selection_policy'])
def test_foreign_or_changed_admission_evidence_is_rejected(admission,fault):
    f=admission;batch=deepcopy(f['batch']);terminal=deepcopy(f['terminal']);put=f['put']
    if fault=='foreign_material':
        prepared=m.read(terminal['prepared']);prepared['batches']=[];terminal['prepared']=put('foreign-prepared.json',prepared)
    elif fault in('goal_drift','input_drift'):
        path=Path(batch['tasks'][0]['task_directory'])/('tests/reference.xlsx'if fault=='goal_drift'else'environment/input.xlsx')
        path.write_bytes(path.read_bytes()+b'changed')
    elif fault.startswith('control_'):
        value=m.read(batch['actual_control_chain'])
        if fault=='control_source':value['source']=f['certificate']
        else:value['new_LO_calls']=3
        batch['actual_control_chain']=put('bad-control.json',value)
    elif fault=='wrong_source_id':batch['tasks'][0]['source_id']='0'*64
    elif fault.startswith('engineering_'):
        task=batch['tasks'][0];value=m.read(task['individual_engineering'])
        if fault=='engineering_source':value['source']=f['certificate']
        elif fault=='engineering_certificate':value['source_certificate']=f['source']
        elif fault=='engineering_controls':value['actual_programmatic_controls']['nop']['reward']=1
        else:value['full_source_formula_count']=1
        task['individual_engineering']=put('bad-engineering.json',value)
    elif fault=='result_reward':
        row=terminal['results'][0];value=m.read(m.reference(row['actual_attempt']['result_file']));value['verifier_result']['rewards']['reward']=1
        record=put('changed-result.json',value);row['actual_attempt'].update(result_file=record['path'],result_sha256=record['sha256'])
    else:
        value=m.read(terminal['selection'])
        if fault=='selection_retry':value['infrastructure_retry_policy']['max_retries']=1
        else:value['tool_time_policy_version']=5
        terminal['selection']=put('bad-selection.json',value)
    if batch!=f['batch']:
        br=put('changed-batch.json',batch);prepared=m.read(terminal['prepared']);prepared['batches']=[br];prepared['tasks']=batch['tasks']
        terminal['prepared']=put('rebound-prepared.json',prepared)
    else:br=f['br']
    with pytest.raises(ValueError):REAL_ADMIT(br,put('changed-terminal.json',terminal))


def test_retained_real_R2_certificate_models_have720choices1882rows_and_exact_runner_pure_readonly():
    path=ROOT/'outputs/research/ringfenced_pair_R2_01_task8_revision2_conditional_20261101T030000Z/prepared/preparation.json'
    if not path.exists():pytest.skip('The retained real R2 evidence is not installed')
    f=m.read(m.reference(path));context=m._source(f['source_manifest']);cert=context['economics']
    winner=m.evaluate_plans(context['models'],cert['winner_plan'],cert)
    runner=m.evaluate_plans(context['models'],cert['canonical_runner_plan'],cert)
    assert winner['classification']=='optimal'and winner['objective_pence']==2375617125
    assert runner['classification']=='feasible_suboptimal'and runner['economic_shortfall_pence']==2843
    assert winner['integer_rows_checked']==runner['integer_rows_checked']==1882
    assert winner['complete_choice_count']==runner['complete_choice_count']==720
    assert m.reference(f['source_manifest']['path'])==f['source_manifest']
