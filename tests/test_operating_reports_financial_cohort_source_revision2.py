"""Pure recovery-protocol mocks; no production forward, native call or server."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def m():
    spec=importlib.util.spec_from_file_location('_test_cohort_source_precision_recovery',ROOT/'scripts/build_operating_reports_financial_cohort_source_revision2.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def store(m,path,value):return m.write(path,value)


def absence(calls):
    return {'all_owned_containers_absent':True,'daemon_reachable':True,'daemon_version':'TEST_ONLY',
        'cleanup_mutations_by_validator':False,'owned':[{'full_id':c['actual_resource_evidence']['container_id'],
            'returncode':1,'stdout':'\n','stderr':'error: no such object: '+c['actual_resource_evidence']['container_id']+'\n','absent':True}for c in calls]}


@pytest.fixture
def retained(m,tmp_path,monkeypatch):
    old=tmp_path/'old';old.mkdir();cold=old/'cold.xlsx';cold.write_bytes(b'TEST_ONLY_CACHE_FREE_BOOK')
    source=old/'source1.xlsx';source.write_bytes(b'TEST_ONLY_NATIVE_OUTPUT')
    profile,profile_value=m.runtime(m.base.PROFILE)
    f={'kind':m.base.KIND,'version':1,'case_id':'FM-C02','specification':store(m,old/'raw.json',{'TEST_ONLY':True}),
        'specification_sha256':'TEST_ONLY','bindings':store(m,old/'bindings.json',{}),
        'expected':store(m,old/'expected.json',{}),'definition':store(m,old/'definition.json',{}),
        'runtime_profile':profile,'runtime_profile_value':profile_value,'cold_start':m.reference(cold),
        'recipe':m.base.recipes(),'stage_order':list(m.STAGES),'required_actual_LO_calls':3,
        'cold_start_is_unseeded':True,'actual_LO_calls':0,'new_financial_forwards':0,'model_calls':0,'qualified':False}
    fref=store(m,old/'preparation.json',f)
    call={'index':1,'role':'source1','input':f['cold_start'],'started_at':'2026-11-01T00:00:00+00:00','completed':False}
    call['started_receipt']=store(m,old/'source1_started.json',dict(call));call.update(completed=True,output=m.reference(source),elapsed_seconds=.1)
    native=store(m,old/'native.json',{'TEST_ONLY':True,'physical_index':1,'legacy':True})
    call['actual_resource_evidence']={'terminal':native,'container_id':'1'*64}
    call['finished_at']='2026-11-01T00:00:01+00:00';call['terminal_receipt']=store(m,old/'source1_terminal.json',dict(call))
    strict={'passed':False,'TEST_ONLY':'old strict source1 audit'}
    fail={'type':'ValueError','message':'Complete independent financial/type/literal audit failed'}
    terminal={'kind':m.base.SOURCE_KIND,'version':1,'passed':False,'failure':fail,'preparation':fref,
        'source':call['output'],'specification':f['specification'],'specification_sha256':f['specification_sha256'],'bindings':f['bindings'],
        'actual_calls':[call],'records':{'source1_audit':store(m,old/'strict.json',strict),
            'failure':store(m,old/'failure.json',fail),'failure_cleanup':store(m,old/'cleanup.json',absence([call]))},
        'actual_LO_calls_started':1,'actual_LO_calls_completed':1,'cold_start_is_unseeded':True,'memoized_independent_ledgers':True,
        'retry':0,'new_financial_forwards':0,'model_calls':0,'solver_calls':0,'Harbor_calls':0,'task_count':0,
        'qualified':False,'normal_all12_QA_passed':False,'difficulty_claimed':False}
    manifest=store(m,old/'source_manifest.json',terminal)
    worker={'case_id':'FM-C02','passed':False,'records':{'source_manifest':manifest,'source_preparation':fref},
        'actual_new_LO_calls':{'started':1,'completed':1,'complete':True}}
    cases=[{'case_id':'FM-C02','passed':False,'terminal':store(m,old/'worker.json',worker)}]
    for number in range(3,10):cases.append({'case_id':f'FM-C{number:02d}','passed':False,'terminal':store(m,old/f'worker{number}.json',{'records':{}})})
    batch={'passed':False,'outer_retries':0,'new_financial_forwards':0,'model_calls':0,'cases':cases}
    monkeypatch.setattr(m,'FAILED_BATCH_REF',store(m,old/'batch.json',batch))
    monkeypatch.setattr(m.base,'validate_prepared',lambda output:deepcopy(f))
    monkeypatch.setattr(m.base,'_stored',lambda frozen:({'TEST_ONLY':True},{},{},{}))
    def resource(call,receipt,frozen):
        record=m.read(receipt)
        assert record['TEST_ONLY']is True
        assert call['index']==(record['physical_index']if record.get('legacy')else record['physical_index']+1)
        return {'terminal':receipt,'container_id':('1'if record.get('legacy')else str(record['physical_index']+1))*64}
    monkeypatch.setattr(m,'validate_call',resource)
    def reconcile(path,frozen,**kwargs):
        return {'kind':'TEST_ONLY_mock_reconciliation','passed':True,'workbook':m.reference(path),
            'original_strict_audit':strict,'retained_round_boundary_count':1,'new_financial_forwards':0}
    monkeypatch.setattr(m,'_reconcile',reconcile)
    class Panel:
        def __init__(self,*args,**kwargs):pass
        def start(self):return 'http://TEST_ONLY_NO_SERVER/'
        def stop(self):pass
    monkeypatch.setitem(m._N,'DashboardServer',Panel)
    return {'f':f,'manifest':manifest,'terminal':terminal,'worker':worker,'batch':batch,'old':old,'resource':resource}


def replacement(m,retained,tmp_path,terminal):
    ref=store(m,tmp_path/'changed_terminal.json',terminal);worker=deepcopy(retained['worker']);worker['records']['source_manifest']=ref
    batch=deepcopy(retained['batch']);batch['cases'][0]['terminal']=store(m,tmp_path/'changed_worker.json',worker)
    m.FAILED_BATCH_REF=store(m,tmp_path/'changed_batch.json',batch);return ref


@pytest.mark.parametrize('fault',['passed','kind','Boolean_count','partial','wrong_failure','wrong_output','missing_cleanup','repeated_call'])
def test_only_genuine_one_call_numeric_failure_can_be_reused(m,retained,tmp_path,fault):
    terminal=deepcopy(retained['terminal'])
    if fault=='passed':terminal['passed']=True
    elif fault=='kind':terminal['kind']='unrelated_source'
    elif fault=='Boolean_count':terminal['actual_LO_calls_started']=True
    elif fault=='partial':terminal['actual_calls'][0]['completed']=False
    elif fault=='wrong_failure':terminal['failure']={'type':'ValueError','message':'Formula or source context changed'}
    elif fault=='wrong_output':terminal['source']=terminal['actual_calls'][0]['input']
    elif fault=='missing_cleanup':terminal['records'].pop('failure_cleanup')
    else:terminal['actual_calls'].append(deepcopy(terminal['actual_calls'][0]))
    changed=replacement(m,retained,tmp_path,terminal)
    with pytest.raises((ValueError,KeyError)):m._retained(changed)


def test_arbitrary_pass_json_or_out_of_batch_source_is_not_a_credential(m,retained,tmp_path):
    with pytest.raises(ValueError):m._retained(store(m,tmp_path/'pass.json',{'passed':True}))


@pytest.mark.parametrize('fault',['permission','wrong_id','populated_stdout','daemon_unknown'])
def test_absence_requires_exact_owned_id_and_real_missing_result(m,retained,fault):
    calls=retained['terminal']['actual_calls'];record=absence(calls)
    if fault=='permission':record['owned'][0]['stderr']='permission denied'
    elif fault=='wrong_id':record['owned'][0]['full_id']='2'*64
    elif fault=='populated_stdout':record['owned'][0]['stdout']='some other container'
    else:record['daemon_reachable']=False
    with pytest.raises(ValueError):m._cleanup(record,calls)


def test_prepare_retains_old_false_audit_without_new_forward_or_native(m,retained,tmp_path,monkeypatch):
    original=Path(retained['manifest']['path']).read_bytes();events=[]
    monkeypatch.setitem(m._N,'ThreadCappedResourceLibreOfficeEngine',lambda *a,**k:pytest.fail('No native engine in prepare'))
    ref=m.prepare(retained['manifest'],tmp_path/'prepared');f=m.validate_prepared(Path(ref['path']).parent)
    assert f['kind']==m.KIND and f['version']==2
    assert f['required_new_native_calls']==2 and f['required_reused_native_calls']==1 and f['required_actual_LO_calls']==3
    assert f['retained_failed_source']==retained['manifest'] and f['original_preparation']==retained['terminal']['preparation']
    assert m.read(f['reused_source1_audit'])['original_strict_audit']['passed']is False
    assert f['E05_E06_grader_changed']is f['old_failure_reclassified']is False
    assert Path(retained['manifest']['path']).read_bytes()==original and events==[]
    with pytest.raises(ValueError):m.prepare(retained['manifest'],tmp_path/'prepared')


@pytest.mark.parametrize('mutation',['policy','recipe','call','original'])
def test_prepared_replay_rejects_policy_recipe_or_ancestry_mutation(m,retained,tmp_path,mutation):
    out=tmp_path/'prepared';ref=m.prepare(retained['manifest'],out);f=m.read(ref)
    if mutation=='policy':f['source_only_policy_sha256']='wrong'
    elif mutation=='recipe':f['recipe']={}
    elif mutation=='call':f['reused_source1_call']['input']=f['reused_source1_call']['output']
    else:f['retained_failed_source']=f['original_preparation']
    Path(ref['path']).unlink();m.write(ref['path'],f)
    with pytest.raises((ValueError,KeyError)):m.validate_prepared(out)


def test_complete_two_fresh_calls_keep_logical_three_chain_and_two_stabilities(m,retained,tmp_path,monkeypatch):
    out=tmp_path/'prepared';m.prepare(retained['manifest'],out);events=[]
    class Engine:
        def __init__(self,*args,**kwargs):self.history=[]
        def ensure_image(self):events.append('pinned_image')
        def recalculate(self,source,destination):
            number=len(self.history)+1;events.append(('native',number,Path(source).name,Path(destination).name))
            Path(destination).write_bytes(Path(source).read_bytes())
            self.history.append(store(m,out/f'TEST_ONLY_native{number}.json',{'TEST_ONLY':True,'physical_index':number}))
            return destination
        def metadata(self):return {'actual_resource_receipts':self.history}
    monkeypatch.setitem(m._N,'ThreadCappedResourceLibreOfficeEngine',Engine)
    monkeypatch.setattr(m,'owned_absence',absence)
    def stable(left,right,expected):events.append(('stability',Path(left).name,Path(right).name));return {'passed':True,'TEST_ONLY':True}
    monkeypatch.setattr(m,'compare_typed',stable)
    ref=m.execute_prepared(out);terminal=m.validate_source(ref)
    assert terminal['new_native_calls_started']==terminal['new_native_calls_completed']==2 and terminal['reused_native_calls']==1
    assert terminal['actual_LO_calls_started']==terminal['actual_LO_calls_completed']==3
    assert [c['role']for c in terminal['actual_calls']]==['source1','source2','source3']
    assert terminal['actual_calls'][0]==retained['terminal']['actual_calls'][0]
    assert [e for e in events if isinstance(e,tuple)and e[0]=='native']==[
        ('native',1,'source1.xlsx','source2.xlsx'),('native',2,'source2.xlsx','source3.xlsx')]
    assert len([e for e in events if isinstance(e,tuple)and e[0]=='stability'])==4 #2actual +2cold replay
    assert m.read(terminal['records']['source1_audit'])['original_strict_audit']['passed']is False
    assert m.read(retained['manifest'])['passed']is False
    with pytest.raises(ValueError,match='No retries'):m.execute_prepared(out)
    changed=deepcopy(terminal);changed['new_native_calls_completed']=1
    with pytest.raises(ValueError):m.validate_source(store(m,tmp_path/'partial_source.json',changed))
    with pytest.raises(ValueError):m.base.validate_source(ref)


@pytest.mark.parametrize('fault',['source2','source3','stability','dashboard_export'])
def test_failure_preserves_new_terminal_and_never_retries_or_adds_third_fresh_call(m,retained,tmp_path,monkeypatch,fault):
    out=tmp_path/'prepared';m.prepare(retained['manifest'],out);events=[]
    class Engine:
        def __init__(self,*args,**kwargs):self.history=[]
        def ensure_image(self):pass
        def recalculate(self,source,destination):
            number=len(self.history)+1;events.append(Path(destination).stem)
            if Path(destination).stem==fault:raise RuntimeError('TEST_ONLY native failure')
            Path(destination).write_bytes(Path(source).read_bytes())
            self.history.append(store(m,out/f'TEST_ONLY_native{number}.json',{'TEST_ONLY':True,'physical_index':number}))
            return destination
        def metadata(self):return {'actual_resource_receipts':self.history}
    monkeypatch.setitem(m._N,'ThreadCappedResourceLibreOfficeEngine',Engine)
    monkeypatch.setattr(m,'owned_absence',absence)
    monkeypatch.setattr(m,'compare_typed',lambda *a,**k:{'passed':fault!='stability','TEST_ONLY':True})
    if fault=='dashboard_export':
        real=m._N['AuditStore']
        class Audit(real):
            def update_run(self,**kwargs):
                value=super().update_run(**kwargs)
                if kwargs.get('producer_active')is False:self.TEST_ONLY_closing=True
                return value
            def export(self,*args,**kwargs):
                if getattr(self,'TEST_ONLY_closing',False):raise RuntimeError('TEST_ONLY final dashboard failure')
                return super().export(*args,**kwargs)
        monkeypatch.setitem(m._N,'AuditStore',Audit)
    with pytest.raises(RuntimeError,match='preserve its new terminal'):m.execute_prepared(out)
    terminal=m.read(out/'source_manifest.json')
    assert terminal['passed']is False and terminal['failure']is not None
    assert terminal['new_native_calls_started']<=2 and terminal['reused_native_calls']==1
    assert events==(['source2']if fault=='source2'else['source2','source3'])
    assert m.read(retained['manifest'])['passed']is False
    with pytest.raises(ValueError,match='No retries'):m.execute_prepared(out)
    with pytest.raises(ValueError):m.validate_source(m.reference(out/'source_manifest.json'))


@pytest.fixture
def audit_case(m,tmp_path,monkeypatch):
    path=tmp_path/'TEST_ONLY.xlsx';path.write_bytes(b'NOT_A_WORKBOOK; ALL_DOWNSTREAM_AUDITS_MOCKED')
    expected={'Report!A1':{'type':'number','value':'1.23'}}
    f={'definition':store(m,tmp_path/'definition.json',{'literals':{'Context!A1':{'type':'text','value':'given'}}}),
        'expected':store(m,tmp_path/'expected.json',expected),'bindings':store(m,tmp_path/'bindings.json',{})}
    strict={'passed':False,'workbook':m.reference(path),'all_financial_fields_checked':93510,'all_derived_values_checked':93510,
        'physical_formulas_checked':88676,'provided_financial_input_fields_checked':11200,'protected_public_literals_checked':1,
        'native_errors':[],'all_formula_caches_empty':False,'qualified':False,
        'mismatches':[{'point':'Report!A1','expected':expected['Report!A1'],'actual':{'type':'number','value':'1.22'}}]}
    raw={'passed':True,'checked_financial_fields':93510,'declared_financial_fields':93510,'policy_sha256':m.POLICY_SHA,
        'round_boundary_differences':[{'point':'Report!A1','within_source_bound':True}]}
    monkeypatch.setattr(m.base,'audit_workbook',lambda *a,**k:deepcopy(strict))
    monkeypatch.setattr(m.precision,'audit_workbook',lambda *a,**k:deepcopy(raw))
    return path,f,strict,raw


def test_only_numeric_boundary_failures_change_source_criterion(m,audit_case):
    path,f,strict,raw=audit_case;result=m._reconcile(path,f,stored=({}, {}, {}, {}))
    assert result['passed']is True and result['original_strict_audit']['passed']is False
    assert result['retained_round_boundary_count']==1 and result['E05_E06_grader_changed']is False


@pytest.mark.parametrize('fault',['context','type','unbound','duplicate','missing_boundary','native_error','formula_count','raw_failure','partial_raw','strict_pass_flag'])
def test_precision_cannot_hide_structural_context_type_errors_or_partial_scope(m,audit_case,fault):
    path,f,strict,raw=audit_case
    if fault=='context':strict['mismatches']=[{'point':'Context!A1','claim':'Supplied context changed'}]
    elif fault=='type':strict['mismatches'][0]['actual']={'type':'boolean','value':True}
    elif fault=='unbound':strict['mismatches'][0]['point']='Other!A1'
    elif fault=='duplicate':strict['mismatches']*=2
    elif fault=='missing_boundary':raw['round_boundary_differences']=[]
    elif fault=='native_error':strict['native_errors']=[{'point':'Report!A1','error':'#DIV/0!'}]
    elif fault=='formula_count':strict['physical_formulas_checked']-=1
    elif fault=='raw_failure':raw['passed']=False
    elif fault=='partial_raw':raw['checked_financial_fields']-=1
    else:strict['passed']=True
    with pytest.raises(ValueError):m._reconcile(path,f,stored=({}, {}, {}, {}))


def test_new_namespace_preserves_every_frozen_original_source_helper(m):
    assert m._N is not m.base._N
    assert m.base._N['KIND']==m.base.KIND and m.base._N['SOURCE_KIND']==m.base.SOURCE_KIND
    assert m._N['KIND']==m.KIND and m._N['SOURCE_KIND']==m.SOURCE_KIND
    assert m._N['ThreadCappedResourceLibreOfficeEngine']is m.base._N['ThreadCappedResourceLibreOfficeEngine']
    recipe=m.recipes()
    assert recipe[str(m.BASE)]['sha256']==m.BASE_SHA
    assert recipe[str(Path(m.precision.__file__).resolve())]['sha256']==m.PRECISION_SHA
