"""Cold source3 preparation and lifecycle tests with all services mocked."""
import importlib.util
import json
from pathlib import Path
import shutil

import openpyxl
import pytest

from sheets_factory.workbook.operating_metrics_regime import excel,spec

ROOT=Path(__file__).resolve().parents[1]


def module():
    description=importlib.util.spec_from_file_location('_test_operating_source',ROOT/'scripts/build_operating_metrics_regime_source.py')
    result=importlib.util.module_from_spec(description);description.loader.exec_module(result);return result


@pytest.fixture
def prepared(tmp_path):
    m=module();candidate=excel.build_views(tmp_path/'candidate');out=tmp_path/'source'
    ref=m.prepare(candidate,out)
    return m,candidate,out,m.read(ref)


def test_prepare_is_zero_service_and_complete_unseeded_copy(prepared):
    m,candidate,out,f=prepared
    assert m.validate_prepared(out)==f
    assert f['kind']==m.KIND and f['actual_LO_calls']==f['model_calls']==0
    assert f['required_actual_LO_calls']==3 and f['stage_order']==['source1','source2','source3']
    assert m._formula_cache_count(f['cold_start']['path'])==0
    assert len(m.read(f['expected']))==2052
    report=m.read(f['cold_start_audit'])
    assert report['passed'] and report['physical_formulas_checked']==1967
    assert report['all_financial_fields_checked']==2052 and report['provided_financial_input_fields_checked']==199
    assert f['cold_start']['sha256']==m.read(candidate)['cold_source_input']['sha256']
    assert not (out/'started.json').exists()
    assert m.execute_prepared.__globals__ is m._ns
    assert m._ns['spec'] is spec


def test_exact_resource_profile_and_frozen_dependency_closure(prepared):
    m,_,_,f=prepared
    assert f['runtime_profile_value']['image']['id']==m._ns['IMAGE']
    assert f['runtime_profile_value']['docker_resources']['source']=={'cpus':2,'memory_bytes':32*1024**3,'pids_limit':256}
    assert m.reference(m.UPSTREAM)['sha256']==m.UPSTREAM_SHA
    assert str(m.UPSTREAM) in f['recipe'] and str(Path(m.__file__).resolve()) in f['recipe']


def test_family_and_output_reuse_fail_closed(prepared,tmp_path):
    m,candidate,out,_=prepared
    with pytest.raises(ValueError):m.prepare(candidate,out)
    forged=m.read(candidate);forged['kind']='prepared_unverified_synthetic_equity_income_group_pair'
    wrong=m.write(tmp_path/'wrong.json',forged)
    with pytest.raises(ValueError):m.prepare(wrong,tmp_path/'wrong_source')


def test_all_financial_values_and_booleans_audited_from_unverified_serialization(prepared):
    m,candidate,_,f=prepared
    definition=m.read(f['definition']);expected=m.read(f['expected']);goal=m.read(candidate)['goal']
    report=m.audit_workbook(goal['path'],definition,expected)
    assert report['passed'] and report['all_financial_fields_checked']==2052
    assert {v['type'] for v in expected.values()}=={'number','text','boolean'}
    with pytest.raises(ValueError):m.audit_workbook(f['cold_start']['path'],definition,expected)


def test_wrong_native_cache_is_rejected_without_changing_the_formula(prepared,tmp_path):
    m,candidate,_,f=prepared;p=m.read(candidate);bindings=m.read(p['bindings'])
    first=next(b for b in bindings['bindings'] if b['key']=='ALDER/2026Q1/revenue')
    def wrong(cell):cell.find('{*}v').text='999'
    changed=tmp_path/'wrong_cache.xlsx'
    excel._rewrite(p['goal']['path'],changed,{first['sheet']:{first['cell']:wrong}})
    report=m.audit_workbook(changed,m.read(f['definition']),m.read(f['expected']))
    assert report['passed'] is False and len(report['mismatches'])==1


@pytest.mark.parametrize('target',['financial','literal','formula'])
def test_complete_audit_rejects_value_fact_or_formula_mutation(prepared,tmp_path,target):
    m,candidate,_,f=prepared;goal=m.read(candidate)['goal'];book=openpyxl.load_workbook(goal['path'])
    definition=m.read(f['definition'])
    if target=='literal':
        point=next(k for k,v in definition['literals'].items() if v['type']=='number')
        sheet,cell=point.rsplit('!',1);book[sheet][cell].value+=1
    else:
        point=next(iter(definition['formulas']));sheet,cell=point.rsplit('!',1)
        book[sheet][cell].value='=123' if target=='formula' else 123
    output=tmp_path/(target+'.xlsx');book.save(output);book.close()
    with pytest.raises(ValueError):m.audit_workbook(output,definition,m.read(f['expected']))


def test_mutated_raw_fact_declaration_rejected(prepared):
    m,candidate,_,_=prepared;p=m.read(candidate);bindings=m.read(p['bindings']);public=m.read(p['specification'])
    bindings['provided_facts'][0]['provided_value']='OTHER'
    with pytest.raises(ValueError):m.source_definition(p['goal']['path'],bindings,public)


def mock_services(monkeypatch,m,candidate,*,fail_second=False):
    ns=m._ns;goal=m.read(candidate)['goal']['path'];calls=[];receipts=[]
    class Engine:
        def __init__(self,*args,**kwargs):pass
        def ensure_image(self):pass
        def recalculate(self,source,output):
            calls.append(str(source))
            if fail_second and len(calls)==2:raise RuntimeError('mock second call failed')
            shutil.copyfile(goal,output)
            receipt=m.write(Path(output).with_suffix('.resource.json'),{'source':m.reference(source),'container_id':str(len(calls))*64})
            receipts.append(receipt);return output
        def metadata(self):return {'actual_resource_receipts':receipts}
    class Server:
        def __init__(self,*args,**kwargs):pass
        def start(self):return 'test://no-network-dashboard'
        def stop(self):pass
    def validate(call,record,frozen):
        return {'container_id':m.read(record)['container_id'],'terminal':record}
    def absence(actual):
        return {'all_owned_containers_absent':True,'daemon_reachable':True,'owned':[{'full_id':c['actual_resource_evidence']['container_id'],'absent':True} for c in actual]}
    monkeypatch.setitem(ns,'ThreadCappedResourceLibreOfficeEngine',Engine)
    monkeypatch.setitem(ns,'DashboardServer',Server)
    monkeypatch.setitem(ns,'validate_call',validate)
    monkeypatch.setitem(ns,'owned_absence',absence)
    return calls


def test_mocked_three_call_lifecycle_and_cold_revalidation(prepared,monkeypatch):
    m,candidate,out,f=prepared;calls=mock_services(monkeypatch,m,candidate)
    terminal=m.execute_prepared(out);result=m.validate_source(terminal)
    assert result['kind']==m.SOURCE_KIND and result['passed'] is True
    assert calls[0]==f['cold_start']['path'] and len(calls)==3
    assert result['actual_LO_calls_started']==result['actual_LO_calls_completed']==3
    assert result['qualified'] is result['normal_all12_QA_passed'] is result['difficulty_claimed'] is False
    with pytest.raises(ValueError):m.execute_prepared(out)


def test_mocked_failure_retains_first_terminal_without_retry(prepared,monkeypatch):
    m,candidate,out,_=prepared;calls=mock_services(monkeypatch,m,candidate,fail_second=True)
    with pytest.raises(RuntimeError):m.execute_prepared(out)
    terminal=m.read(out/'source_manifest.json')
    assert terminal['passed'] is False and len(calls)==2 and terminal['actual_LO_calls_completed']==1
    assert (out/'failure.json').exists() and terminal['retry']==0
    with pytest.raises(ValueError):m.validate_source(out/'source_manifest.json')
    with pytest.raises(ValueError):m.execute_prepared(out)
