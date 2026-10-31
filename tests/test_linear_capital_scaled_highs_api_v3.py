"""API-v3 diagnostic export contracts only; no native instance or solver."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import FunctionType

import pytest

from sheets_factory.workbook.linear_capital_scaled import highs_engineering_api_v2 as previous
from sheets_factory.workbook.linear_capital_scaled import highs_engineering_api_v3 as engine
from sheets_factory.workbook.linear_capital_scaled import highs_runtime_api_v3 as adapter
from test_linear_capital_scaled_highs_api_v2 import runtime_case as v2_runtime_fixture, status_api, ref, dump
from test_linear_capital_scaled_highs_engineering import matrix

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('status,content,passes',[('ok','LP bytes',True),('warning','LP bytes',True),
    ('error','LP bytes',False),('ok',None,False),('warning','',False),(None,'LP bytes',False)])
def test_export_accepts_only_ok_or_warning_with_nonempty_fresh_file_and_records_status(monkeypatch,tmp_path,status,content,passes):
    native,_=status_api(monkeypatch)
    def exported(path):
        native.calls.append(('export_status',status))
        if content is not None:Path(path).write_text(content)
        return status
    native.writeModel=exported
    if passes:
        result=engine.solve_highs(matrix(),log_path=tmp_path/'native.log',model_path=tmp_path/'native.lp')
        assert result['native_model_export_status']==status and result['native_model_export_bytes']==len(content)
        assert result['plan']=={'P001':0,'P002':1} and result['objective_pence']==9_000_007
        assert result['parameters']==previous.PARAMETERS and result['exact_integer_check']['all_integer_rows_checked']==4
        assert native.run_count==1 and result['checked_optimal'] is False
    else:
        with pytest.raises(ValueError,match='native diagnostic model export') as error:
            engine.solve_highs(matrix(),log_path=tmp_path/'native.log',model_path=tmp_path/'native.lp')
        assert str(status) in str(error.value) and native.run_count==0
    assert ('setMaximize_None',) not in native.calls and ('changeObjectiveSense','MAXIMIZE') in native.calls


def test_old_v2_warned_export_rejects_without_any_search(monkeypatch,tmp_path):
    native,_=status_api(monkeypatch)
    def warning(path):Path(path).write_text('valid diagnostic LP');return 'warning'
    native.writeModel=warning
    with pytest.raises(ValueError,match='native engineering model or option was rejected'):
        previous.solve_highs(matrix(),log_path=tmp_path/'old.log',model_path=tmp_path/'old.lp')
    assert native.run_count==0


def test_all_pure_coefficient_transforms_and_integer_audits_match_v2():
    for model in (matrix(),matrix(production=360),matrix(legacy=True,production=240)):
        assert engine.scaled_model(model)==previous.scaled_model(model)
        assert engine.exact_plan_check(model,[0]*len(model['project_ids']))==previous.exact_plan_check(model,[0]*len(model['project_ids']))


@pytest.fixture
def runtime_case(tmp_path,monkeypatch):
    # Reuse the exact mock-data builder in a new globals dictionary. No old
    # module globals are patched and no native packages are imported.
    function=v2_runtime_fixture.__wrapped__;namespace={**function.__globals__,'adapter':adapter}
    return FunctionType(function.__code__,namespace,function.__name__)(tmp_path,monkeypatch)


def test_complete_seven_file_native_package_imports_portably(runtime_case,tmp_path):
    runtime,lock,probe,model,parent=runtime_case;output=tmp_path/'native';runtime.prepare(model['path'],output)
    frozen=runtime.validate_prepared(output)
    assert frozen['version']==3 and frozen['kind'].endswith('_api_v3')
    assert set(frozen['source_code'])=={'spec.py','frozen_spec.py','model_a.py','frozen_model_a.py',
        'highs_engineering.py','highs_engineering_api_v2.py','frozen_highs_engineering.py'}
    code="import sys,json;sys.dont_write_bytecode=True;sys.path.insert(0,sys.argv[1]);from portfolio import highs_engineering as e;m=json.load(open(sys.argv[2]));assert e.API_VERSION==3;assert e.exact_plan_check(m,[0,1,1])['objective_pence']==13;assert 'highspy' not in sys.modules;print('portable API-v3 PASS')"
    result=subprocess.run([sys.executable,'-I','-c',code,str(output/'job_bundle'),model['path']],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert runtime.validate_prepared(output)==frozen and 'portable API-v3 PASS' in result.stdout
    assert frozen['request']['time_limit_seconds']==800 and frozen['resources']['cpus']==2


@pytest.fixture
def entry_case(runtime_case,monkeypatch,tmp_path):
    runtime,lock,probe,model,parent=runtime_case
    path=ROOT/'scripts/run_linear_capital_scaled_highs_screen_api_v3.py';descriptor=importlib.util.spec_from_file_location('_api_v3_entry_case',path)
    entry=importlib.util.module_from_spec(descriptor);descriptor.loader.exec_module(entry)
    monkeypatch.setattr(entry,'TINY_ROOT',Path(model['path']).parent);monkeypatch.setattr(entry,'TINY_MODEL_SHA256',model['sha256'])
    monkeypatch.setattr(entry,'TINY_PARENT_SHA256',parent['sha256']);monkeypatch.setattr(entry.highs_runtime,'build_runtime',lambda *a:runtime)
    failure1=dump(tmp_path/'failure1.json',{'owned_cleanup_passed':True,'native_api_attempts':1,'native_run_reached':False,'P01_started':False})
    failure2=dump(tmp_path/'failure2.json',{'owned_cleanup_passed':True,'cumulative_lineage_native_Highs_instances':2,
        'cumulative_lineage_native_run_calls':0,'cumulative_lineage_optimizer_searches':0,'both_P01_versions_unstarted':True})
    monkeypatch.setattr(entry,'FAILURES',tuple((row['path'],row['sha256']) for row in (failure1,failure2)))
    tiny=tmp_path/'tiny';entry.prepare_tiny(tiny,vendor_lock=lock['path'],dependency_probe=probe['path'])
    return entry,runtime,tiny


def test_both_prior_failures_are_immutable_and_cannot_be_a_v3_pass(entry_case):
    entry,runtime,tiny=entry_case;frozen,_,_=entry.checked_tiny_prospective(tiny)
    assert frozen['version']==3 and frozen['kind'].endswith('_api_v3')
    assert frozen['api_compatibility_parent_failures']==entry._prior_failure() and len(entry._prior_failure())==2
    old=deepcopy(frozen);old['version']=2;old['kind']='prepared_fixed_scaled_highs2_three_project_api_smoke_api_v2'
    folder=tiny.parent/'previous';dump(folder/'prospective.json',old)
    with pytest.raises(ValueError):entry.checked_tiny_prospective(folder)
    Path(entry.FAILURES[1][0]).write_text('{}')
    with pytest.raises(ValueError,match='immutable prior'):entry.checked_tiny_prospective(tiny)


def test_new_v3_attempt_preserves_failure_and_forbids_repetition(entry_case,monkeypatch):
    entry,runtime,tiny=entry_case;calls=[]
    def failed(output):calls.append(output);raise RuntimeError('Explicit mocked API-v3 failure')
    monkeypatch.setattr(runtime,'execute_prepared',failed)
    with pytest.raises(RuntimeError):entry.execute_tiny(tiny)
    with pytest.raises(ValueError,match='no retries'):entry.execute_tiny(tiny)
    with pytest.raises(ValueError,match='failed API smoke'):entry.checked_tiny_completed(tiny)
    assert calls==[tiny/'native'] and entry.read(tiny/'tiny_failure.json')['retry_authorized'] is False


def test_frozen_v2_layers_still_match_reviewed_hashes():
    assert ref(engine.api_v2_path())['sha256']==engine.API_V2_SHA256
    assert ref(adapter.V2_PATH)['sha256']==adapter.V2_SHA256
    assert ref(ROOT/'scripts/run_linear_capital_scaled_highs_screen_api_v2.py')['sha256']=='36e4ffe9b4fa2c1160e876756ae93b9cd25320b210331d9822e9fabc096208c4'
