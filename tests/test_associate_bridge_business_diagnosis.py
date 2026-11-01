"""Submission-only diagnostic lifecycle; all native calls below are mocks."""
import importlib.util
import json
from pathlib import Path
import shutil

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_test_bridge_diagnosis', ROOT/'scripts/diagnose_associate_bridge_business_attempts.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    def put(name, value): return m.write(tmp_path/name, value)
    def book(name, number):
        path = tmp_path/name; path.parent.mkdir(parents=True, exist_ok=True)
        w = openpyxl.Workbook(); w.active.title = 'Report'; w.active['A1'] = 'Public facts'; w.active['B2'] = number
        w.save(path); w.close(); return m.reference(path)
    goal = book('source3.xlsx',100); original_input = book('input.native.xlsx',0)
    spec_ref = put('specification.json', {'kind':'associate_bridge_business_spec_v1','case_id':'B04',
        'base':{'entities':[{'id':'E001','money_unit':'GBP'}]}})
    bindings = put('bindings.json', {'financial': {'E001/2027Q1/net_income': {'sheet':'Report','cell':'B2','role':'report'}}})
    goal_receipt = put('source-receipt.json', {'TEST_ONLY':True,'status':'completed','source':goal,'output':goal})
    audit = put('source-audit.json', {'passed':True,'all_financial_fields_checked':93510,'unresolved_mismatches':[],'native_errors':[]})
    ledger = put('ledger.json', {'TEST_ONLY': True})
    comparison = put('comparison.json', {'full_financial_fields':93510,'complete_economic_raw_and_primary_values_equal':True})
    source = put('source.json', {'kind':'independently_verified_associate_bridge_business_source_v1',
        'passed':True,'case_id':'B04','actual_LO_calls_completed':3,'complete_AB_financial_fields':93510,
        'goal':goal,'specification':spec_ref,'bindings':bindings,'recipe':[],
        'independent_records':{'A':ledger,'B':ledger,'independent_comparison':comparison},
        'actual_LO_calls':[{'index':i,'workbook':goal,'audit':audit,
            'native_metadata':{'actual_resource_receipts':[goal_receipt]}} for i in (1,2,3)]})
    tasks=[]; rows=[]; selected=[]
    for mode in ('financial_modeling','debugging'):
        tid='test-'+mode; directory=tmp_path/'exports'/tid
        (directory/'tests').mkdir(parents=True); (directory/'environment').mkdir()
        shutil.copyfile(goal['path'],directory/'tests/reference.xlsx')
        shutil.copyfile(original_input['path'],directory/'environment/input.xlsx')
        input_receipt=put(tid+'/input-receipt.json',{'TEST_ONLY':True,'source':original_input,'output':original_input})
        engineering=put(tid+'/individual.json',{'source':source,'native_call_metadata':{'actual_resource_receipts':[input_receipt]}})
        result=put('native/'+tid+'/result.json',{'TEST_ONLY':True,'task_name':'sheetsfactory/'+tid,
            'exception_info':None,'finished_at':'2026-11-01T06:00:00Z','verifier_result':{'rewards':{'reward':0}}})
        book('native/'+tid+'/artifacts/app/output.xlsx',90)
        task={'task_id':tid,'mode':mode,'variant_id':mode,'task_directory':str(directory),
            'source_id':goal['sha256'],'harbor_export_binding':{'TEST_ONLY':tid},'individual_engineering':engineering}
        config=put(tid+'/trial-config.json',{'TEST_ONLY':True})
        rows.append({'task_id':tid,'mode':mode,'actual_attempt':{'task_id':tid,'status':'scored',
            'raw_verifier_reward':0,'result_file':result['path'],'result_sha256':result['sha256'],'task_checksum':tid},
            'resources':{'passed':True,'complete':True,'trial_config':config,'result':result},
            'score':{'effective_reward':0,'state':'complete'}})
        selected.append({'task_id':tid,'task_checksum':tid,'harbor_export_binding':task['harbor_export_binding'],
                         'task_directory':str(directory)})
        tasks.append(task)
    batch=put('engineered_batch.json',{'kind':'individually_engineered_business_revision_batch','version':1,
        'count':2,'tasks':tasks,'selected_task_ids':[t['task_id'] for t in tasks],'source':source})
    prepared=put('prepared.json',{'kind':'prepared_business_revision_native_frontier_v1',
        'phase':'development','batches':[batch],'tasks':tasks})
    selection=put('selection.json',{'tasks':selected,'phase':'development','model':'gpt-6.1-sol',
        'reasoning_effort':'xhigh','n_attempts':1,'tool_time_policy_version':6,
        'infrastructure_retry_policy':{'max_retries':0}})
    resources=put('actual-resources.json',{'passed':True,'complete':True,'observation_receipts':[]})
    terminal=put('frontier-terminal.json',{'kind':'business_revision_native_frontier_terminal_v1','version':1,'phase':'development',
        'outer_retries':0,'prepared':prepared,'selection':selection,'resources':resources,'results':rows})
    monkeypatch.setattr(m,'validate_trial_observations',lambda *a,**kw:{'passed':True,'complete':True})
    class Audit:
        def __init__(self,*a,**kw): self.db=self
        def __getattr__(self,name): return lambda *a,**kw: None
    class Dashboard:
        def __init__(self,*a,**kw):pass
        def start(self):return 'TEST_ONLY://no-service'
        def stop(self):pass
    monkeypatch.setattr(m,'AuditStore',Audit);monkeypatch.setattr(m,'DashboardServer',Dashboard)
    return {'put':put,'book':book,'batch':batch,'terminal':terminal,'tasks':tasks,'rows':rows,'root':tmp_path}


def test_two_outputs_only_are_recalculated_once_and_original_scores_preserved(fixture, monkeypatch):
    f=fixture; calls=[]; analyses=[]
    class Engine:
        def __init__(self,root,profile,*,role,receipt_directory):
            assert role=='verifier' and profile==m.PROFILE;self.receipt_directory=receipt_directory
        def recalculate(self,source,destination):
            calls.append((source,destination));destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,destination)
            self.receipt=m.write(self.receipt_directory/'receipt.json',{'TEST_ONLY':True,
                'source':m.reference(source),'output':m.reference(destination),'container_id':str(len(calls))*64})
            return destination
        def metadata(self):return {'actual_resource_receipts':[self.receipt]}
    def analyze(*args,**kw):
        analyses.append(kw);assert args[0]['Report!B2']==['number','0.00']
        assert args[1]['Report!B2']==['number','100.00'] and args[2]['Report!B2']==['number','90.00']
        assert kw['raw_reference']['Report!B2']=='100' and kw['raw_output']['Report!B2']=='90'
        return {'state':'diagnosed','business_failure_evidence':True,'business_qualified':True,
            'economic_witnesses':[{'TEST_ONLY':True}],'category_counts':{'recognition':1}}
    monkeypatch.setattr(m,'ThreadCappedResourceLibreOfficeEngine',Engine)
    monkeypatch.setattr(m.business,'analyze',analyze)
    monkeypatch.setattr(m,'owned_absence',lambda r:{'all_owned_containers_absent':True,'daemon_reachable':True})
    before=m.read(f['terminal']);out=f['root']/'diagnosis'
    result=m.read(m.run(f['batch']['path'],f['terminal']['path'],out))
    assert len(calls)==len(analyses)==result['actual_verifier_LO_calls']==2
    assert result['new_source_LO_calls']==result['new_model_calls']==result['new_financial_forwards']==0
    assert result['business_qualified_count']==2 and result['primary_rewards_modified'] is False
    assert m.read(f['terminal'])==before
    for row in result['records']:
        report=m.read(row['evidence']);assert report['original_raw_reward']==0
        assert report['original_effective_score']=={'effective_reward':0,'state':'complete'}


def test_no_saved_output_is_coverage_unknown_without_native_call_or_fabricated_zero(fixture, monkeypatch):
    f=fixture
    for row in f['rows']:
        (Path(row['actual_attempt']['result_file']).parent/'artifacts/app/output.xlsx').unlink()
    monkeypatch.setattr(m,'ThreadCappedResourceLibreOfficeEngine',lambda *a,**kw:pytest.fail('No O means no native call'))
    result=m.read(m.run(f['batch']['path'],f['terminal']['path'],f['root']/'no-outputs'))
    assert result['unknown_count']==2 and result['business_qualified_count']==result['actual_verifier_LO_calls']==0
    assert all(r['state']=='coverage_unknown' and r['business_qualified'] is None for r in result['records'])


@pytest.mark.parametrize('fault',['unscored','missing_resource','wrong_reward','foreign_task','other_batch','source_incomplete'])
def test_admission_rejects_foreign_or_incomplete_evidence_before_recalculation(fixture,fault):
    f=fixture;terminal=m.read(f['terminal']);batch=m.read(f['batch']);row=terminal['results'][0]
    if fault=='unscored':row['actual_attempt']['status']='evidence_incomplete'
    elif fault=='missing_resource':row['resources']['complete']=False
    elif fault=='wrong_reward':row['actual_attempt']['raw_verifier_reward']=1
    elif fault=='foreign_task':
        native=m.read(row['resources']['result']);native['task_name']='sheetsfactory/other'
        record=f['put']('foreign-result.json',native);row['resources']['result']=record
        row['actual_attempt'].update(result_file=record['path'],result_sha256=record['sha256'])
    elif fault=='other_batch':batch['selected_task_ids'].reverse()
    else:
        source=m.read(batch['source']);source['actual_LO_calls_completed']=2
        batch['source']=f['put']('partial-source.json',source)
    br=f['put']('changed-batch.json',batch) if fault in ('other_batch','source_incomplete') else f['batch']
    if fault=='source_incomplete':
        prepared=m.read(terminal['prepared']);prepared['batches']=[br];prepared['tasks']=batch['tasks']
        terminal['prepared']=f['put']('changed-prepared.json',prepared)
    tr=f['put']('changed-terminal.json',terminal)
    with pytest.raises(ValueError):m._admit(br,tr)


def test_published_copy_must_match_actual_native_receipt_bytes(fixture):
    f=fixture;task=f['tasks'][0];engineering=m.read(task['individual_engineering']);receipt=engineering['native_call_metadata']['actual_resource_receipts'][-1]
    published=Path(task['task_directory'])/'environment/input.xlsx';published.write_bytes(b'changed')
    with pytest.raises(ValueError,match='Published workbook'):
        m._maps(receipt,published,f['root']/'never-mapped')


def test_output_native_failure_is_retained_and_not_retried(fixture,monkeypatch):
    f=fixture;calls=[]
    class Engine:
        def __init__(self,*a,**kw):pass
        def recalculate(self,*a):calls.append(1);raise RuntimeError('TEST_ONLY native failed')
    monkeypatch.setattr(m,'ThreadCappedResourceLibreOfficeEngine',Engine)
    out=f['root']/'failed'
    with pytest.raises(RuntimeError,match='native failed'):m.run(f['batch']['path'],f['terminal']['path'],out)
    failure=json.loads((out/'failure.json').read_text())
    assert len(calls)==failure['actual_verifier_LO_calls_started']==1
    assert failure['actual_verifier_LO_calls_completed']==0 and failure['outer_retries']==0
    assert failure['primary_rewards_modified'] is False


@pytest.mark.parametrize('cleanup_ok',[True,False])
def test_auxiliary_unknown_is_not_zero_and_cleanup_unknown_cannot_pass(fixture,monkeypatch,cleanup_ok):
    f=fixture;calls=[]
    class Engine:
        def __init__(self,*a,receipt_directory,**kw):self.directory=receipt_directory
        def recalculate(self,source,destination):
            calls.append(1);destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,destination)
            self.receipt=m.write(self.directory/'receipt.json',{'TEST_ONLY':True,'source':m.reference(source),
                'output':m.reference(destination),'container_id':'a'*64});return destination
        def metadata(self):return {'actual_resource_receipts':[self.receipt]}
    monkeypatch.setattr(m,'ThreadCappedResourceLibreOfficeEngine',Engine)
    monkeypatch.setattr(m.business,'analyze',lambda *a,**kw:{'state':'unknown',
        'business_failure_evidence':None,'business_qualified':None,'economic_witnesses':[]})
    monkeypatch.setattr(m,'owned_absence',lambda r:{'all_owned_containers_absent':cleanup_ok,'daemon_reachable':True})
    out=f['root']/'aux-unknown'
    if cleanup_ok:
        terminal=m.read(m.run(f['batch']['path'],f['terminal']['path'],out))
        assert terminal['unknown_count']==2 and terminal['business_qualified_count']==0 and len(calls)==2
    else:
        with pytest.raises(ValueError,match='cleanup'):m.run(f['batch']['path'],f['terminal']['path'],out)
        assert len(calls)==1 and (out/'failure.json').exists() and not (out/'terminal.json').exists()


def test_retained_actual_B04_goal_receipt_and_complete_map_shape_readonly(tmp_path):
    path=ROOT/'outputs/research/associate_bridge_B04_engineering_20261101T063500Z/engineered_batch.json'
    if not path.exists():pytest.skip('Retained actual B04 engineering is not installed')
    record=m.reference(path)
    assert record['sha256']=='07bf6043ee08902534a1637384ed7491226008ccec26c58d34af3147828cbcfe'
    batch=m.read(record);source=m.read(batch['source'])
    assert source['case_id']=='B04' and source['complete_AB_financial_fields']==93510
    assert [c['index'] for c in source['actual_LO_calls']]==[1,2,3]
    for call in source['actual_LO_calls']:
        audit=m.read(call['audit'])
        assert audit['all_financial_fields_checked']==93510 and not audit['unresolved_mismatches']
    last=source['actual_LO_calls'][-1]['native_metadata']['actual_resource_receipts'][-1]
    maps,proof=m._maps(last,source['goal']['path'],tmp_path/'actual-goal-maps')
    assert len(maps['typed'])>=93510 and len(maps['raw_numeric'])>0
    assert proof['native_receipt']==last and proof['recalculated_workbook']==source['goal']
    assert m.reference(path)==record
