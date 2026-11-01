"""Tax-source diagnostics use complete evidence; native boundaries below are mocks."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location('_test_tax_diagnosis', ROOT/'scripts/diagnose_tax_vintage_business_attempts.py')
m = importlib.util.module_from_spec(loader); loader.loader.exec_module(m)


def load(path, name):
    loader = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(loader); loader.loader.exec_module(module); return module


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    sequence = 0
    def put(name, value):
        nonlocal sequence
        sequence += 1
        return m._N['write'](tmp_path/(str(sequence)+'-'+name), value)
    fields = {'net_income':100, 'cash_tax_paid':20, 'tax_payable_close':30,
        'tax_ordinary_after_losses':40, 'tax_investment_after_losses':50,
        'tax_lot_C00_ordinary_used':2, 'reported_current_tax':20}
    financial = {f'E001/2027Q1/{field}': {'sheet':'Report','cell':'B'+str(i+2),
        'role':'report','money_unit':'GBP_thousands'} for i,field in enumerate(fields)}
    financial['PORTFOLIO/2027Q1/net_income'] = {'sheet':'Report','cell':'C2','role':'report','money_unit':'GBP'}
    financial['E001/2027Q1/cagr'] = {'sheet':'Report','cell':'C3','role':'given_NA','money_unit':'GBP_thousands'}
    values = {f'E001/2027Q1/{field}':value for field,value in fields.items()}
    values.update({'PORTFOLIO/2027Q1/net_income':100000,'E001/2027Q1/cagr':'N/A'})
    def book(name, overrides=None):
        path = tmp_path/name; path.parent.mkdir(parents=True,exist_ok=True)
        workbook = openpyxl.Workbook(); sheet = workbook.active; sheet.title='Report'
        sheet['A1']='TEST_ONLY hypothetical tax records'
        for key,value in {**values, **(overrides or {})}.items():sheet[financial[key]['cell']]=value
        workbook.save(path); workbook.close(); return m.reference(path)
    def receipt(name, source, output, *, role='source'):
        cid='a'*64
        value = {'TEST_ONLY_mock_native_boundary':True,'kind':'resource_bound_libreoffice_call','role':role,
            'status':'completed','source':source,'output':output,'started_at':'2026-11-01T07:00:00Z',
            'finished_at':'2026-11-01T07:00:01Z','container_id':cid,
            'actual_resources_verified':True,'thread_cap_verified':True,
            'actual_resources':{'cpus_nanoseconds':2_000_000_000,'memory_bytes':32*1024**3,'pids_limit':256},
            'thread_cap_before':{'container_id':cid,'values':['MAX_CONCURRENCY=2']},
            'thread_cap_after':{'container_id':cid,'values':['MAX_CONCURRENCY=2'],'exit_code_observed':'0'}}
        for key,filename in [('implementation','resource_engine.py'),('upstream_engine','engine.py'),
                             ('thread_cap_adapter','thread_capped_resource_engine.py')]:
            value[key]=m.reference(ROOT/'src/sheets_factory/workbook'/filename)
        return put(name,value)
    identities = tuple(f'T{i:02d}'for i in range(1,9))
    public = {'kind':'tax_vintage_bridge_business_spec_v2','case_id':'T01',
        'bridge':{'base':{'entities':[{'id':'E001','money_unit':'GBP_thousands'}]}}}
    # Only the public inventory/shape boundary is replaced; no business forward is invoked.
    real_spec=m.spec
    monkeypatch.setattr(m,'spec',SimpleNamespace(CASE_IDS=identities,RESULT_KIND=real_spec.RESULT_KIND,
        validate=lambda p:p,points=lambda p:((key,'text'if values[key]=='N/A'else'number')for key in values),
        canonical_sha256=real_spec.canonical_sha256))
    raw=[]
    for case in identities:
        p={**deepcopy(public),'case_id':case};r=put(case+'.json',p)
        raw.append({'case_id':case,'specification':r,'canonical_sha256':m.spec.canonical_sha256(p)})
    public_ref=raw[0]['specification']
    cohort=put('raw.json',{'kind':'frozen_raw_tax_vintage_bridge_business_cases_v2','count':8,'cases':raw,
        'fixed_before_financial_oracle_and_model':True,'spec_implementation':m.reference(m.SPEC_FILE)})
    bindings=put('bindings.json',{'financial':financial,'provided_facts':{}})
    ledger={'kind':m.spec.RESULT_KIND,'specification_sha256':m.spec.canonical_sha256(public),
        'typed_2dp_values':{key:{'type':'text'if value=='N/A'else'number',
             'value':value if value=='N/A'else f'{value:.2f}'}for key,value in values.items()},
        'raw_cell_exact_values':{key:{'kind':'text'if value=='N/A'else'rational','value':str(value)}for key,value in values.items()},
        'economic_exact_values':{key:{'kind':'text'if value=='N/A'else'rational','value':str(value)}for key,value in values.items()},
        'reconciliation_checks':{'passed':True}}
    independent={'A':put('A.json',ledger),'B':put('B.json',deepcopy(ledger)),
        'independent_comparison':put('comparison.json',{'passed':True,'full_financial_fields':len(values),
             'complete_economic_raw_and_primary_values_equal':True})}
    cold=book('cold.xlsx');previous=cold;calls=[]
    for index in (1,2,3):
        goal=book(f'source{index}.xlsx')
        audit=put('audit.json',{'passed':True,'all_financial_fields_checked':len(values),
            'native_errors':[],'unresolved_mismatches':[]})
        calls.append({'index':index,'workbook':goal,'audit':audit,
            'native_metadata':{'actual_resource_receipts':[receipt('source-receipt.json',previous,goal)]}})
        previous=goal
    source={'kind':'independently_verified_tax_vintage_bridge_business_source_v2','passed':True,'case_id':'T01',
        'raw_cohort':cohort,'specification':public_ref,'bindings':bindings,'goal':goal,
        'independent_records':independent,'complete_AB_financial_fields':len(values),
        'actual_LO_calls_completed':3,'actual_LO_calls':calls,'recipe':[m.reference(m.SPEC_FILE)]}
    source_ref=put('source.json',source)
    tasks=[];rows=[];selected=[]
    for mode in ('financial_modeling','debugging'):
        identity='test-tax-'+mode;directory=tmp_path/'exports'/identity
        (directory/'tests').mkdir(parents=True);(directory/'environment').mkdir()
        shutil.copyfile(goal['path'],directory/'tests/reference.xlsx')
        native_input=book(identity+'/input.native.xlsx',{'E001/2027Q1/net_income':0})
        shutil.copyfile(native_input['path'],directory/'environment/input.xlsx')
        input_receipt=receipt('input-receipt.json',native_input,native_input)
        engineering=put('engineering.json',{'source':source_ref,
            'native_call_metadata':{'actual_resource_receipts':[input_receipt]}})
        result=put(identity+'/result.json',{'task_name':'sheetsfactory/'+identity,'exception_info':None,
            'finished_at':'2026-11-01T07:01:00Z','verifier_result':{'rewards':{'reward':0}}})
        submitted=Path(result['path']).parent/'artifacts/app/output.xlsx'
        submitted.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(book(identity+'/saved.xlsx',{'E001/2027Q1/cash_tax_paid':10})['path'],submitted)
        task={'task_id':identity,'mode':mode,'variant_id':'T01-'+mode,'task_directory':str(directory),
            'source_id':goal['sha256'],'harbor_export_binding':{'TEST_ONLY':identity},'individual_engineering':engineering}
        tasks.append(task)
        rows.append({'task_id':identity,'mode':mode,'actual_attempt':{'status':'scored','raw_verifier_reward':0,
            'result_file':result['path'],'result_sha256':result['sha256'],'task_checksum':identity},
            'score':{'effective_reward':0,'state':'complete'},'resources':{'passed':True,'complete':True,
                'result':result,'trial_config':put('config.json',{'TEST_ONLY':True})}})
        selected.append({'task_id':identity,'task_checksum':identity,'task_directory':str(directory),
            'harbor_export_binding':task['harbor_export_binding']})
    batch=put('batch.json',{'kind':'individually_engineered_business_revision_batch','version':1,'count':2,
        'tasks':tasks,'selected_task_ids':[t['task_id']for t in tasks],'source':source_ref})
    prepared=put('prepared.json',{'kind':'prepared_business_revision_native_frontier_v1','phase':'development',
        'batches':[batch],'tasks':tasks})
    selection=put('selection.json',{'phase':'development','model':'gpt-6.1-sol','reasoning_effort':'xhigh',
        'n_attempts':1,'tool_time_policy_version':6,'infrastructure_retry_policy':{'max_retries':0},'tasks':selected})
    resources=put('resources.json',{'passed':True,'complete':True,'observation_receipts':[]})
    terminal=put('terminal.json',{'kind':'business_revision_native_frontier_terminal_v1','version':1,
        'phase':'development','outer_retries':0,'prepared':prepared,'selection':selection,'resources':resources,'results':rows})
    class Audit:
        def __init__(self,*a,**kw):self.db=self
        def __getattr__(self,name):return lambda *a,**kw:None
    class Dashboard:
        def __init__(self,*a,**kw):pass
        def start(self):return 'TEST_ONLY://no-service'
        def stop(self):pass
    monkeypatch.setitem(m._N,'AuditStore',Audit);monkeypatch.setitem(m._N,'DashboardServer',Dashboard)
    monkeypatch.setitem(m._N,'validate_trial_observations',lambda *a,**kw:{'passed':True,'complete':True})
    monkeypatch.setitem(m._N,'owned_absence',lambda r:{'all_owned_containers_absent':True,'daemon_reachable':True})
    return locals()


def test_dynamic_scope_is_complete_and_not_fixed_to_old93510(fixture):
    f=fixture
    assert m._source_scope(f['source'])==len(f['financial'])==9
    batch,terminal,rows,source=m._N['_admit'](f['batch'],f['terminal'])
    assert source==f['source']and len(rows)==2


@pytest.mark.parametrize('fault',['bindings_missing','bindings_extra','bindings_field_alias','bindings_entity_alias','duplicate_physical',
    'A_typed_missing','A_raw_missing','B_economic_missing','both_drop_same',
    'A_B_value_conflict','ledger_wrong_spec','ledger_wrong_kind','ledger_unreconciled',
    'source_count','comparison_count','comparison_not_passed','audit1_count','audit2_count',
    'audit3_count','audit_error','source_calls2','source_order','source_wrong_kind',
    'source_wrong_case','raw_foreign_spec','raw_case_missing','raw_not_frozen',
    'receipt_incomplete','receipt_unchained','receipt_wrong_output','receipt_wrong_cpu',
    'receipt_wrong_cap','receipt_wrong_engine','receipt_wrong_role','receipt_ambiguous','goal_not_source3'])
def test_scope_and_all_three_actual_source_proofs_reject_incomplete_evidence(fixture,fault):
    f=fixture;s=deepcopy(f['source']);put=f['put'];key='E001/2027Q1/net_income'
    if fault.startswith('bindings')or fault=='duplicate_physical':
        value=m.read(s['bindings'])
        if fault=='bindings_missing':value['financial'].pop(key)
        elif fault=='bindings_extra':value['financial']['E001/2027Q1/unknown']=dict(value['financial'][key],cell='Z9')
        elif fault=='bindings_field_alias':value['financial']['E001/2027Q1/tax_lot_C00_ordinary_used']['field']='net_income'
        elif fault=='bindings_entity_alias':value['financial'][key]['entity_id']='PORTFOLIO'
        else:value['financial']['PORTFOLIO/2027Q1/net_income']['cell']=value['financial'][key]['cell']
        s['bindings']=put('bad-bindings.json',value)
    elif fault in ('A_typed_missing','A_raw_missing','B_economic_missing','A_B_value_conflict',
                   'ledger_wrong_spec','ledger_wrong_kind','ledger_unreconciled'):
        side='B'if fault.startswith('B_')else'A';value=m.read(s['independent_records'][side])
        if fault=='A_typed_missing':value['typed_2dp_values'].pop(key)
        elif fault=='A_raw_missing':value['raw_cell_exact_values'].pop(key)
        elif fault=='B_economic_missing':value['economic_exact_values'].pop(key)
        elif fault=='A_B_value_conflict':value['raw_cell_exact_values'][key]['value']='99'
        elif fault=='ledger_wrong_spec':value['specification_sha256']='0'*64
        elif fault=='ledger_wrong_kind':value['kind']='old-values'
        else:value['reconciliation_checks']['passed']=False
        s['independent_records'][side]=put('bad-ledger.json',value)
    elif fault=='both_drop_same':
        value=m.read(s['bindings']);value['financial'].pop(key);s['bindings']=put('short-bindings.json',value)
        for side in ('A','B'):
            value=m.read(s['independent_records'][side])
            for name in ('economic_exact_values','raw_cell_exact_values','typed_2dp_values'):value[name].pop(key)
            s['independent_records'][side]=put('short-ledger.json',value)
        s['complete_AB_financial_fields']-=1
    elif fault=='source_count':s['complete_AB_financial_fields']=93510
    elif fault.startswith('comparison'):
        value=m.read(s['independent_records']['independent_comparison'])
        value['full_financial_fields'if fault=='comparison_count'else'passed']=93510 if fault=='comparison_count'else False
        s['independent_records']['independent_comparison']=put('bad-comparison.json',value)
    elif fault.startswith('audit'):
        index=int(fault[5])-1 if fault!='audit_error'else 0;call=s['actual_LO_calls'][index]
        value=m.read(call['audit'])
        if fault=='audit_error':value['native_errors']=['Report!Z1']
        else:value['all_financial_fields_checked']=93510
        call['audit']=put('bad-audit.json',value)
    elif fault=='source_calls2':s['actual_LO_calls']=s['actual_LO_calls'][:2];s['actual_LO_calls_completed']=2
    elif fault=='source_order':s['actual_LO_calls'].reverse()
    elif fault=='source_wrong_kind':s['kind']='independently_verified_associate_bridge_business_source_v1'
    elif fault=='source_wrong_case':s['case_id']='T02'
    elif fault.startswith('raw_'):
        value=m.read(s['raw_cohort'])
        if fault=='raw_foreign_spec':value['cases'][0]['specification']=value['cases'][1]['specification']
        elif fault=='raw_case_missing':value['cases'].pop()
        else:value['fixed_before_financial_oracle_and_model']=False
        s['raw_cohort']=put('bad-cohort.json',value)
    elif fault=='goal_not_source3':s['goal']=s['actual_LO_calls'][0]['workbook']
    else:
        call=s['actual_LO_calls'][1];value=m.read(call['native_metadata']['actual_resource_receipts'][0])
        if fault=='receipt_incomplete':value['actual_resources_verified']=False
        elif fault=='receipt_unchained':value['source']=s['actual_LO_calls'][2]['workbook']
        elif fault=='receipt_wrong_output':value['output']=s['actual_LO_calls'][2]['workbook']
        elif fault=='receipt_wrong_cpu':value['actual_resources']['cpus_nanoseconds']=4_000_000_000
        elif fault=='receipt_wrong_cap':value['thread_cap_after']['values']=['MAX_CONCURRENCY=4']
        elif fault=='receipt_wrong_engine':value['implementation']['sha256']='0'*64
        elif fault=='receipt_wrong_role':value['role']='verifier'
        r=put('bad-receipt.json',value);call['native_metadata']['actual_resource_receipts']=[r,r]if fault=='receipt_ambiguous'else[r]
    with pytest.raises((ValueError,KeyError)):m._source_scope(s)


def test_one_output_calculation_each_complete_maps_and_original_scores_unchanged(fixture,monkeypatch):
    f=fixture;calls=[]
    class Engine:
        def __init__(self,root,profile,*,role,receipt_directory):
            assert role=='verifier'and profile==m._N['PROFILE'];self.folder=receipt_directory
        def recalculate(self,source,destination):
            calls.append((source,destination));destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,destination)
            self.receipt=f['receipt']('output-receipt.json',m.reference(source),m.reference(destination),role='verifier')
            return destination
        def metadata(self):return {'actual_resource_receipts':[self.receipt]}
    monkeypatch.setitem(m._N,'ThreadCappedResourceLibreOfficeEngine',Engine)
    before=m.read(f['terminal']);out=f['tmp_path']/'diagnosis'
    terminal=m.read(m.run(f['batch']['path'],f['terminal']['path'],out))
    assert len(calls)==terminal['actual_verifier_LO_calls']==terminal['actual_verifier_LO_calls_started']==2
    assert terminal['business_qualified_count']==2 and terminal['unknown_count']==0
    assert terminal['new_model_calls']==terminal['new_financial_forwards']==terminal['new_source_LO_calls']==0
    assert terminal['primary_rewards_modified']is False and m.read(f['terminal'])==before
    for row in terminal['records']:
        value=m.read(row['evidence']);witness,=value['economic_witnesses']
        assert witness['field']=='cash_tax_paid'and witness['absolute_difference_gbp']=='10000'
        scales=m.read(value['provenance']['entity_money_scales'])
        assert scales=={'E001':1000,'PORTFOLIO':1}
        assert value['original_effective_score']=={'effective_reward':0,'state':'complete'}
        assert value['primary_wrong_count']==1 and value['owned_cleanup']['all_owned_containers_absent']


def test_no_output_remains_unknown_and_starts_no_calculation(fixture,monkeypatch):
    f=fixture
    for row in f['rows']:(Path(row['actual_attempt']['result_file']).parent/'artifacts/app/output.xlsx').unlink()
    monkeypatch.setitem(m._N,'ThreadCappedResourceLibreOfficeEngine',lambda *a,**kw:pytest.fail('No O means no native call'))
    terminal=m.read(m.run(f['batch']['path'],f['terminal']['path'],f['tmp_path']/'no-output'))
    assert terminal['unknown_count']==2 and terminal['actual_verifier_LO_calls']==0
    assert all(row['business_qualified']is None for row in terminal['records'])


def test_output_failure_is_recorded_without_retry(fixture,monkeypatch):
    f=fixture;calls=[]
    class Engine:
        def __init__(self,*a,**kw):pass
        def recalculate(self,*a):calls.append(1);raise RuntimeError('TEST_ONLY native failure')
    monkeypatch.setitem(m._N,'ThreadCappedResourceLibreOfficeEngine',Engine)
    out=f['tmp_path']/'failed'
    with pytest.raises(RuntimeError,match='native failure'):m.run(f['batch']['path'],f['terminal']['path'],out)
    value=json.loads((out/'failure.json').read_text())
    assert len(calls)==value['actual_verifier_LO_calls_started']==1
    assert value['actual_verifier_LO_calls_completed']==value['outer_retries']==0
    assert not(out/'terminal.json').exists()


def test_change_to_independent_ledger_during_output_calls_cannot_reach_terminal(fixture,monkeypatch):
    f=fixture;calls=[]
    class Engine:
        def __init__(self,*a,**kw):pass
        def recalculate(self,source,destination):
            calls.append(1);destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,destination)
            self.receipt=f['receipt']('mutation-output-receipt.json',m.reference(source),m.reference(destination),role='verifier')
            if len(calls)==2:
                path=Path(f['source']['independent_records']['A']['path'])
                path.write_bytes(path.read_bytes()+b'\n')
            return destination
        def metadata(self):return {'actual_resource_receipts':[self.receipt]}
    monkeypatch.setitem(m._N,'ThreadCappedResourceLibreOfficeEngine',Engine)
    out=f['tmp_path']/'changed-during-diagnosis'
    with pytest.raises(ValueError,match='Evidence reference'):
        m.run(f['batch']['path'],f['terminal']['path'],out)
    failure=json.loads((out/'failure.json').read_text())
    assert len(calls)==failure['actual_verifier_LO_calls_completed']==2
    assert len(failure['completed_records'])==2 and not(out/'terminal.json').exists()


@pytest.mark.parametrize('field,category',list(m.ADDITIONAL_CORE_FIELDS.items()))
def test_only_four_declared_new_core_fields_can_supply_material_economic_witness(tmp_path,field,category):
    old=load(ROOT/'tests/test_business_failure_evidence.py','_tax_business_fixture')
    b=old.bundle.__wrapped__(tmp_path)(field=field,scale=1000)
    evidence=m._N['business'].analyze(b['maps']['input']['typed'],b['maps']['reference']['typed'],b['maps']['output']['typed'],
        bindings=b['bindings'],entity_money_scales=b['entity_money_scales'],provenance=b['provenance'],original_reward=0,
        raw_reference=b['maps']['reference']['raw_numeric'],raw_output=b['maps']['output']['raw_numeric'])
    assert evidence['business_qualified']is True and evidence['category_counts']=={category:1}
    assert evidence['economic_witnesses'][0]['absolute_difference_gbp']=='10000'


@pytest.mark.parametrize('field',['tax_lot_O01_ordinary_used','tax_lot_C00_investment_close',
    'loss_ordinary_used','loss_investment_expired','reported_current_tax','qoq_percent'])
def test_lot_only_and_presentation_errors_do_not_supply_core_difficulty(tmp_path,field):
    old=load(ROOT/'tests/test_business_failure_evidence.py','_tax_helper_fixture')
    b=old.bundle.__wrapped__(tmp_path)(field=field)
    evidence=m._N['business'].analyze(b['maps']['input']['typed'],b['maps']['reference']['typed'],b['maps']['output']['typed'],
        bindings=b['bindings'],entity_money_scales=b['entity_money_scales'],provenance=b['provenance'],original_reward=0,
        raw_reference=b['maps']['reference']['raw_numeric'],raw_output=b['maps']['output']['raw_numeric'])
    assert evidence['state']=='diagnosed'and evidence['business_qualified']is False
    assert len(evidence['excluded_differences'])==1 and not evidence['economic_witnesses']


@pytest.mark.parametrize('case',['success','boundary','no_raw','wrong_type'])
def test_new_core_field_retains_success_noise_and_unknown_policy(tmp_path,case):
    old=load(ROOT/'tests/test_business_failure_evidence.py','_tax_core_policy_fixture')
    kwargs={'field':'cash_tax_paid'}
    if case=='boundary':kwargs.update(goal=.045,output=.0449999999999999,scale=1000000)
    elif case=='wrong_type':kwargs.update(output='incorrect text')
    b=old.bundle.__wrapped__(tmp_path)(**kwargs)
    evidence=m._N['business'].analyze(b['maps']['input']['typed'],b['maps']['reference']['typed'],b['maps']['output']['typed'],
        bindings=b['bindings'],entity_money_scales=b['entity_money_scales'],provenance=b['provenance'],
        original_reward=1 if case=='success'else 0,
        raw_reference=None if case=='no_raw'else b['maps']['reference']['raw_numeric'],
        raw_output=b['maps']['output']['raw_numeric'])
    if case=='no_raw':
        assert evidence['state']=='unknown'and evidence['business_qualified']is None
    else:
        assert evidence['state']=='diagnosed'and evidence['business_qualified']is False
        if case=='success':assert evidence['original_reward']==1 and evidence['quality_issues']
        elif case=='boundary':assert evidence['primary_wrong_count']==1 and not evidence['economic_witnesses']
        else:assert evidence['quality_issues']and not evidence['economic_witnesses']


def test_private_field_map_and_native_lifecycle_do_not_mutate_frozen_original():
    before=dict(m.original.CORE_FIELDS);old=load(m.BASE,'_tax_immutable_driver')
    assert set(m._N['business'].analyze.__globals__['CORE_FIELDS'])-set(before)==set(m.ADDITIONAL_CORE_FIELDS)
    assert not(set(before)&set(m.ADDITIONAL_CORE_FIELDS))and m.original.CORE_FIELDS==before
    for name in ('_maps','owned_absence'):
        assert m._N[name].__code__.co_code==getattr(old,name).__code__.co_code
        assert m._N[name].__code__.co_consts==getattr(old,name).__code__.co_consts
    assert m._N['PINS']==old.PINS and m._N is not old.run.__globals__
    recipe=m._N['recipes']()
    assert m.reference(m.SPEC_FILE)in recipe and m.reference(m.BASE)in recipe
