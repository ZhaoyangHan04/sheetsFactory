"""Toy source audits and mocked lifecycle; no production source calls."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from xml.etree import ElementTree as X
from zipfile import ZipFile,ZIP_DEFLATED

import openpyxl
import pytest

from sheets_factory.workbook.operating_reports_financial_cohort_v1 import schema,oracles,excel

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def m():
    spec=importlib.util.spec_from_file_location('_test_cohort_source',ROOT/'scripts/build_operating_reports_financial_cohort_source.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def store(m,path,value):
    path.write_text(json.dumps(value,indent=2)+'\n');return m.reference(path)


@pytest.fixture
def sample(m,tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('_cohort_source_toy',ROOT/'tests/test_operating_reports_financial_cohort_v1.py')
    fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures);public=fixtures.toy()
    candidate_ref=excel.emit(public,tmp_path/'emission');candidate=m.read(candidate_ref);bindings=m.read(candidate['bindings'])
    a,b=oracles.solve_A(public),oracles.solve_B(public);comparison=m.compare_stored(public,a,b)
    raw=store(m,tmp_path/'original_raw.json',public);inventory=store(m,tmp_path/'TEST_ONLY_inventory.json',{'fixture':True})
    monkeypatch.setattr(m.raw,'validate_all',lambda value:{'inventory':{'cases':[{'candidate_id':'FM-C01','specification':raw}]},'specifications':{'FM-C01':public}})
    forwards={}
    for implementation,result in [('A',a),('B',b)]:
        started=store(m,tmp_path/('started_'+implementation+'.json'),{'kind':'once_operating_reports_financial_cohort_forward_started','version':1,
            'implementation':implementation,'case_id':'FM-C01','raw_inventory':inventory,'specification':raw,
            'recipe':schema.recipes(),'financial_forward_limit':1,'outer_retries':0,'started_at':'2026-11-01T00:00:00+00:00'})
        result_ref=store(m,tmp_path/('result_'+implementation+'.json'),result)
        forwards[implementation]=store(m,tmp_path/('forward_'+implementation+'.json'),{
            'kind':'complete_once_operating_reports_financial_cohort_forward','version':1,'implementation':implementation,
            'case_id':'FM-C01','raw_inventory':inventory,'specification':raw,'recipe':schema.recipes(),
            'financial_forward_calls':1,'outer_retries':0,'qualified':False,'elapsed_seconds':0.1,'started':started,'result':result_ref})
    envelope=store(m,tmp_path/'comparison.json',{'kind':'stored_operating_reports_financial_cohort_AB_comparison','version':1,
        'case_id':'FM-C01','raw_inventory':inventory,'specification':raw,'A':forwards['A'],'B':forwards['B'],
        'comparison':comparison,'new_financial_forwards':0})
    f={'kind':m.KIND,'version':1,'case_id':'FM-C01','raw_inventory':inventory,'specification':raw,'bindings':candidate['bindings'],
        'financial_evidence':{'forward_A':forwards['A'],'forward_B':forwards['B'],'comparison':envelope}}
    expected,projected=m._crosscheck_prepared(f);definition=m.source_definition(candidate['source']['path'],bindings,public)
    cold=tmp_path/'cold.xlsx';m.clear_all_formula_caches(candidate['source']['path'],cold)
    return {'public':public,'candidate':candidate,'bindings':bindings,'f':f,'expected':expected,'projected':projected,'definition':definition,'cold':cold}


def test_complete_toy_maps_CAGR_bridges_physical_union_without_forward(m,sample,monkeypatch):
    monkeypatch.setattr(oracles,'solve_A',lambda *a,**k:pytest.fail('No source forward'))
    monkeypatch.setattr(oracles,'solve_B',lambda *a,**k:pytest.fail('No source forward'))
    expected,projected=m._crosscheck_prepared(sample['f'])
    assert expected==sample['expected'] and projected==sample['projected']
    assert projected['complete_comparison']['points']==len(expected)==1230
    assert projected['complete_comparison']['CAGR_proofs_per_oracle']==6
    assert projected['new_financial_forwards']==0 and projected['qualified'] is False
    census=m.fm_census(sample['public'],sample['candidate'],sample['bindings'])
    assert census['report_positions']==1230 and census['FM_mask']==816 and census['formula_caches']==0
    assert census['provided_fact_fields']==56 and census['native_calls']==0
    assert m.audit_workbook(sample['cold'],sample['definition'],expected,empty_caches=True)['passed']
    assert m._formula_cache_count(sample['cold'])==0


@pytest.mark.parametrize('fault',['forward_repeat','Boolean_call_count','wrong_implementation','wrong_case','wrong_raw','stale_recipe',
    'missing_started','bad_limit','bad_timestamp','partial_result','wrong_CAGR','nonzero_bridge','comparison_flag_only'])
def test_complete_once_forward_and_full_financial_proof_required(m,sample,fault):
    f=deepcopy(sample['f']);a=m.read(f['financial_evidence']['forward_A']);start=m.read(a['started'])
    if fault=='forward_repeat':a['financial_forward_calls']=2
    elif fault=='Boolean_call_count':a['financial_forward_calls']=True
    elif fault=='wrong_implementation':a['implementation']='B'
    elif fault=='wrong_case':a['case_id']='FM-C02'
    elif fault=='wrong_raw':a['specification']=sample['candidate']['specification']
    elif fault=='stale_recipe':a['recipe']={}
    elif fault=='missing_started':Path(a['started']['path']).unlink()
    elif fault in ('bad_limit','bad_timestamp'):
        if fault=='bad_limit':start['financial_forward_limit']=2
        else:start['started_at']='2026-11-01T00:00:00'
        a['started']=store(m,Path(a['started']['path']).with_name('changed_start.json'),start)
    elif fault in ('partial_result','wrong_CAGR','nonzero_bridge'):
        result=m.read(a['result'])
        if fault=='partial_result':result['raw_cell_exact_values'].pop(next(iter(result['raw_cell_exact_values'])))
        elif fault=='wrong_CAGR':next(iter(result['cagr_proofs'].values()))['upper_raw']='-100'
        else:result['reconciliation_checks']['cash_bridge_residuals'][next(iter(result['reconciliation_checks']['cash_bridge_residuals']))]='1'
        a['result']=store(m,Path(a['result']['path']).with_name('changed_result.json'),result)
    else:
        envelope=m.read(f['financial_evidence']['comparison']);envelope['comparison']={'passed':True}
        f['financial_evidence']['comparison']=store(m,Path(f['financial_evidence']['comparison']['path']).with_name('only_flag.json'),envelope)
    if fault!='comparison_flag_only':
        f['financial_evidence']['forward_A']=store(m,Path(sample['f']['financial_evidence']['forward_A']['path']).with_name('changed_forward.json'),a)
        envelope=m.read(f['financial_evidence']['comparison']);envelope['A']=f['financial_evidence']['forward_A']
        f['financial_evidence']['comparison']=store(m,Path(f['financial_evidence']['comparison']['path']).with_name('changed_comparison.json'),envelope)
    with pytest.raises((ValueError,KeyError,OSError)):m._crosscheck_prepared(f)


@pytest.mark.parametrize('fault',['missing_report','duplicate_report','wrong_NA_role','missing_fact','wrong_fact','missing_context','changed_policy'])
def test_complete_bindings_exact_raw_facts_and_policy_required(m,sample,fault):
    binding=deepcopy(sample['bindings'])
    if fault=='missing_report':binding['financial'].pop(next(iter(binding['financial'])))
    elif fault=='duplicate_report':
        keys=list(binding['financial']);binding['financial'][keys[1]]=binding['financial'][keys[0]]
    elif fault=='wrong_NA_role':next(row for row in binding['financial'].values() if row['role']=='given_NA')['role']='report'
    elif fault=='missing_fact':binding['provided_facts'].pop(next(iter(binding['provided_facts'])))
    elif fault=='wrong_fact':next(iter(binding['provided_facts'].values()))['value']='999'
    elif fault=='missing_context':binding['provided_context'].pop('ReadMe!A1')
    else:binding['provided_context']['ReadMe!A3']['value']='Another financial policy'
    with pytest.raises((ValueError,KeyError)):m.source_definition(sample['candidate']['source']['path'],binding,sample['public'])


def test_FM_census_rejects_plan_omission_and_unplanned_extra(m,sample,tmp_path):
    plans=m.read(sample['candidate']['view_plans']);plans['FM_mask'].pop()
    changed=deepcopy(sample['candidate']);changed['view_plans']=store(m,tmp_path/'wrong_plan.json',plans)
    with pytest.raises(ValueError,match='complete FM-only'):m.fm_census(sample['public'],changed,sample['bindings'])
    book=openpyxl.load_workbook(sample['candidate']['views']['financial_modeling']['input']['path']);book['ReadMe']['Z99']='extra'
    path=tmp_path/'extra.xlsx';book.save(path);book.close();cold=tmp_path/'extra_cold.xlsx';m.clear_all_formula_caches(path,cold)
    changed=deepcopy(sample['candidate']);changed['views']['financial_modeling']['input']=m.reference(cold)
    with pytest.raises(ValueError):m.fm_census(sample['public'],changed,sample['bindings'])


def test_seeded_cache_and_numeric_boolean_cannot_pass(m,sample,tmp_path):
    ns='{'+m._N['NS']+'}';source=sample['cold'];expected=sample['expected']
    names={}
    with ZipFile(source) as archive:
        rels=X.fromstring(archive.read('xl/_rels/workbook.xml.rels'));targets={r.attrib['Id']:r.attrib['Target'].lstrip('/') for r in rels}
        for row in X.fromstring(archive.read('xl/workbook.xml')).find(ns+'sheets'):
            target=targets[row.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
            names[target if target.startswith('xl/') else 'xl/'+target]=row.attrib['name']
    def cache(out,numeric_bool):
        with ZipFile(source) as original,ZipFile(out,'x',ZIP_DEFLATED) as target:
            for item in original.infolist():
                content=original.read(item.filename)
                if item.filename in names:
                    tree=X.fromstring(content)
                    for cell in tree.iter(ns+'c'):
                        if cell.find(ns+'f') is None:continue
                        wanted=expected[names[item.filename]+'!'+cell.attrib['r']];v=X.SubElement(cell,ns+'v')
                        if wanted['type']=='boolean':cell.set('t','n' if numeric_bool else 'b');v.text='1' if wanted['value'] else '0'
                        else:cell.set('t','n');v.text=wanted['value']
                    content=X.tostring(tree)
                target.writestr(item,content)
    good=tmp_path/'cached.xlsx';cache(good,False)
    assert m.audit_workbook(good,sample['definition'],expected)['passed']
    bad=tmp_path/'numeric_bool.xlsx';cache(bad,True)
    assert not m.audit_workbook(bad,sample['definition'],expected)['passed']
    assert m._formula_cache_count(good)==len(sample['definition']['formulas'])
    with pytest.raises(ValueError):m.audit_workbook(good,sample['definition'],expected,empty_caches=True)


def test_common_lifecycle_private_namespace_resource_and_helper_closure(m):
    assert m.execute_prepared.__globals__ is m._N and m._N['audit_workbook'] is m.audit_workbook
    assert m._N['KIND']==m.KIND and m._N['SOURCE_KIND']==m.SOURCE_KIND
    assert m._N['STAGES']==('source1','source2','source3')
    assert m.source_definition.__globals__['schema'] is schema and m.compare_stored.__globals__['s'] is schema
    assert m._scaffold.KIND=='prepared_waterfall_portfolios_cold_source3'
    _,profile=m.runtime(m.PROFILE)
    assert profile['docker_resources']['source']=={'cpus':2,'memory_bytes':32*1024**3,'pids_limit':256}
    assert profile['timeouts']['workbook_file_seconds']==600 and profile['solver_tool_budget']['seconds']==1800
    assert str(Path(excel.__file__).resolve()) in m.recipes() and m._N['_formula_cache_count'] is m._formula_cache_count


def test_prepare_panel_precedes_cold_failure_without_native_calls(m,tmp_path,monkeypatch):
    seen=[]
    class Server:
        def __init__(self,*a,**k):pass
        def start(self):seen.append('panel');return 'http://127.0.0.1:0/'
        def stop(self):seen.append('closed')
    monkeypatch.setitem(m._N,'DashboardServer',Server)
    def fail(*a):seen.append('cold');raise ValueError('TEST_ONLY missing all-nine proof')
    monkeypatch.setattr(m.raw,'validate_all',fail)
    out=tmp_path/'prepare'
    with pytest.raises((ValueError,OSError)):m.prepare(tmp_path/'none',out,raw_inventory=tmp_path/'missing',case_id='FM-C01',forward_A='unused',forward_B='unused',comparison='unused')
    assert seen[0]=='panel' and seen[-1]=='closed'
    assert (out/'preparation_failure.json').exists() and not (out/'preparation.json').exists() and not list(out.glob('*.xlsx'))


def test_old_source_or_pass_boolean_does_not_admit(m,tmp_path):
    for index,kind in enumerate(('independently_checked_fixed_operating_reports_200_source',m.SOURCE_KIND)):
        record=store(m,tmp_path/f'fake{index}.json',{'kind':kind,'version':1,'passed':True})
        with pytest.raises((ValueError,KeyError)):m.validate_completed(record)


@pytest.mark.parametrize('failure',['none','first_call','cleanup'])
def test_three_call_chain_full_typed_stabilities_cleanup_and_no_retry(m,sample,tmp_path,monkeypatch,failure):
    import shutil
    # Build a cached toy fixture directly; this is never a LibreOffice result.
    ns='{'+m._N['NS']+'}';cached=tmp_path/'synthetic_cached.xlsx'
    with ZipFile(sample['cold']) as original,ZipFile(cached,'x',ZIP_DEFLATED) as target:
        names={};rels=X.fromstring(original.read('xl/_rels/workbook.xml.rels'));lookup={r.attrib['Id']:r.attrib['Target'].lstrip('/') for r in rels}
        for sheet in X.fromstring(original.read('xl/workbook.xml')).find(ns+'sheets'):
            part=lookup[sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
            names[part if part.startswith('xl/') else 'xl/'+part]=sheet.attrib['name']
        for item in original.infolist():
            content=original.read(item.filename)
            if item.filename in names:
                tree=X.fromstring(content)
                for cell in tree.iter(ns+'c'):
                    if cell.find(ns+'f') is None:continue
                    wanted=sample['expected'][names[item.filename]+'!'+cell.attrib['r']];value=X.SubElement(cell,ns+'v')
                    cell.set('t','b' if wanted['type']=='boolean' else 'n')
                    value.text=('1' if wanted['value'] else '0') if wanted['type']=='boolean' else wanted['value']
                content=X.tostring(tree)
            target.writestr(item,content)
    out=tmp_path/'mocked_source3';out.mkdir();profile,profile_value=m.runtime(m.PROFILE)
    f={**sample['f'],'specification_sha256':schema.canonical_sha256(sample['public']),'cold_start':m.reference(sample['cold']),
        'definition':store(m,out/'definition.json',sample['definition']),'expected':store(m,out/'expected.json',sample['expected']),
        'independent_comparison':store(m,out/'projection.json',sample['projected']),'runtime_profile':profile,'runtime_profile_value':profile_value}
    store(m,out/'preparation.json',f);events=[];calls=[];history=[]
    class Server:
        def __init__(self,*a,**k):pass
        def start(self):events.append('panel');return 'http://127.0.0.1:0/'
        def stop(self):events.append('panel_closed')
    class Engine:
        def __init__(self,*a,**k):pass
        def ensure_image(self):events.append('mock_image')
        def recalculate(self,source,destination):
            calls.append((source,destination))
            if failure=='first_call':raise ValueError('TEST_ONLY first-call failure')
            shutil.copyfile(cached,destination)
            receipt=store(m,out/('fake_resource'+str(len(calls))+'.json'),{
                'source':m.reference(source),'output':m.reference(destination),'container_id':f'{len(calls):064x}'})
            history.append(receipt);return destination
        def metadata(self):return {'actual_resource_receipts':history}
    def validate(call,receipt,frozen):
        return {'terminal':receipt,'container_id':m.read(receipt)['container_id'],'TEST_ONLY_mock_resource':True}
    def cleanup(rows):
        return {'all_owned_containers_absent':failure!='cleanup','daemon_reachable':True,
            'owned':[{'full_id':r['actual_resource_evidence']['container_id'],'absent':failure!='cleanup'} for r in rows]}
    def cold_validate(path):events.append('cold');return f
    for key,value in {'DashboardServer':Server,'ThreadCappedResourceLibreOfficeEngine':Engine,
        'validate_prepared':cold_validate,'_crosscheck_prepared':lambda _: (sample['expected'],sample['projected']),
        'validate_call':validate,'owned_absence':cleanup}.items():monkeypatch.setitem(m._N,key,value)
    if failure=='none':
        ref=m.execute_prepared(out);terminal=m.validate_completed(ref)
        assert terminal['passed'] and terminal['actual_LO_calls_started']==terminal['actual_LO_calls_completed']==3
        assert len(calls)==3 and terminal['new_financial_forwards']==0 and terminal['memoized_independent_ledgers']
        assert all(key in terminal['records'] for key in ('source1_to_source2','source2_to_source3','cleanup'))
    else:
        with pytest.raises(RuntimeError,match='preserve the first'):m.execute_prepared(out)
        terminal=m.read(out/'source_manifest.json')
        assert terminal['passed'] is False and terminal['actual_LO_calls_started']==(1 if failure=='first_call' else 3)
        assert terminal['failure'] and terminal['qualified'] is False
    assert events[0]=='panel' and events[1]=='cold' and events.index('panel_closed')>events.index('cold')
    count=len(calls)
    with pytest.raises(ValueError,match='No retries'):m.execute_prepared(out)
    assert len(calls)==count


