"""Focused API-v2 regression and portable cold checks; no native optimizer."""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from sheets_factory.workbook.linear_capital_scaled import highs_engineering as old_engine
from sheets_factory.workbook.linear_capital_scaled import highs_engineering_api_v2 as engine
from sheets_factory.workbook.linear_capital_scaled import highs_runtime_api_v2 as adapter
from test_linear_capital_scaled_highs_engineering import matrix, mocked

ROOT=Path(__file__).resolve().parents[1]


def ref(path):
    path=Path(path).resolve();raw=path.read_bytes()
    return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return ref(path)


def status_api(monkeypatch,*,rejected=False):
    native,created=mocked(monkeypatch)
    def no_status():native.calls.append(('setMaximize_None',));return None
    def low_level(sense):native.calls.append(('changeObjectiveSense',sense));return 'error' if rejected else 'ok'
    native.setMaximize=no_status;native.changeObjectiveSense=low_level
    sys.modules['highspy'].ObjSense=type('Sense',(),{'kMaximize':'MAXIMIZE'})
    return native,created


def test_observed_convenience_None_fails_old_route_before_search(monkeypatch,tmp_path):
    native,_=status_api(monkeypatch)
    with pytest.raises(ValueError,match='native engineering model or option was rejected'):
        old_engine.solve_highs(matrix(),log_path=tmp_path/'old.log',model_path=tmp_path/'old.lp')
    assert ('setMaximize_None',) in native.calls and native.run_count==0


@pytest.mark.parametrize('rejected',[False,True])
def test_api_v2_uses_low_level_status_and_still_rejects_native_error(monkeypatch,tmp_path,rejected):
    native,_=status_api(monkeypatch,rejected=rejected)
    if rejected:
        with pytest.raises(ValueError,match='native engineering model or option was rejected'):
            engine.solve_highs(matrix(),log_path=tmp_path/'new.log',model_path=tmp_path/'new.lp')
        assert native.run_count==0
    else:
        result=engine.solve_highs(matrix(),log_path=tmp_path/'new.log',model_path=tmp_path/'new.lp')
        assert native.run_count==1 and result['plan']=={'P001':0,'P002':1}
        assert result['objective_pence']==9_000_007 and result['exact_integer_check']['all_integer_rows_checked']==4
        assert result['parameters']==old_engine.PARAMETERS and result['checked_optimal'] is False
    assert ('changeObjectiveSense','MAXIMIZE') in native.calls and ('setMaximize_None',) not in native.calls


def test_only_one_original_math_call_changes_and_all_pure_results_match():
    original=ast.parse(engine.upstream_path().read_bytes());expected=deepcopy(original)
    class Expected(ast.NodeTransformer):
        def visit_Call(self,node):
            if ast.unparse(node)=='native.setMaximize()':return ast.parse('native.changeObjectiveSense(hs.ObjSense.kMaximize)',mode='eval').body
            return self.generic_visit(node)
    assert ast.dump(engine.adapted_ast())==ast.dump(Expected().visit(expected))
    for model in (matrix(),matrix(production=360),matrix(legacy=True,production=240)):
        assert engine.scaled_model(model)==old_engine.scaled_model(model)
        assert engine.exact_plan_check(model,[0]*len(model['project_ids']))==old_engine.exact_plan_check(model,[0]*len(model['project_ids']))


@pytest.fixture
def runtime_case(tmp_path,monkeypatch):
    vendor=tmp_path/'vendor';source=tmp_path/'approved_numpy';vendor.mkdir();source.mkdir();inventory={};old={}
    for name in adapter.VENDOR_ROOTS:
        path=vendor/name/'fixture.txt';path.parent.mkdir();path.write_text('UNIT BYTES, NOT INSTALLED PACKAGES')
        name=str(path.relative_to(vendor));inventory[name]=ref(path)
        if name.startswith('numpy'):
            old_path=source/name;old_path.parent.mkdir(exist_ok=True);old_path.write_bytes(path.read_bytes());old[name]=ref(old_path)
    wheel=tmp_path/'fixture.whl';wheel.write_bytes(b'UNIT WHEEL')
    monkeypatch.setattr(adapter,'WHEEL_SHA256',ref(wheel)['sha256']);monkeypatch.setattr(adapter,'WHEEL_BYTES',wheel.stat().st_size)
    monkeypatch.setattr(adapter,'APPROVED_NUMPY_ROOT',source)
    metadata=dump(tmp_path/'official.json',{'info':{'name':'highspy','version':'1.15.1'},
        'urls':[{'url':adapter.WHEEL_URL,'digests':{'sha256':adapter.WHEEL_SHA256},'size':adapter.WHEEL_BYTES}]})
    lock=dump(tmp_path/'lock.json',{'kind':'prepared_isolated_highs_numpy_vendor','version':1,
        'distributions':adapter.DISTRIBUTIONS,'vendor_root':str(vendor),'package_roots':sorted(adapter.VENDOR_ROOTS),
        'wheel_sha256':adapter.WHEEL_SHA256,'wheel_url':adapter.WHEEL_URL,'wheel':ref(wheel),'official_metadata':metadata,
        'vendor_inventory':inventory,'numpy_source_inventory':old})
    cid='d'*64;actual={'Id':cid,'Image':'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043',
        'NanoCpus':2*10**9,'Memory':32*1024**3,'PidsLimit':256,'NetworkMode':'none','ReadOnly':True,
        'Mounts':[{'Source':str(vendor),'Destination':'/vendor','RW':False}]}
    probe=dump(tmp_path/'probe.json',{'passed':True,'optimizer_calls':0,'native_solver_instantiated':False,'vendor_lock':lock,
        'image_id':actual['Image'],'container_id':cid,'imported':{'versions':adapter.DISTRIBUTIONS,
            'paths':{'numpy':'/vendor/numpy/__init__.py','highspy':'/vendor/highspy/__init__.py'}},
        'before':{**actual,'State':{'Status':'created'}},'after':{**actual,'State':{'Status':'exited','Running':False,'ExitCode':0,'OOMKilled':False}},'cleanup':{'passed':True}})
    runtime=adapter.build_runtime(lock['path'],probe['path'])
    model={'kind':'linear_capital_scaled_direct_binary_integer_model','version':2,'project_ids':['P001','P002','P003'],
        'objective_pence':[11,7,6],'rows':[{'id':name,'family':name.split(':')[0],'scenario_id':None,'year':None,'coefficients':coefficients,'limit':limit}
            for name,coefficients,limit in [('exclusivity:site',[1,0,1],1),('prerequisite:dependency',[0,-1,1],0),('resource:budget',[2,1,1],2)]],
        'specification_sha256':'a'*64,'universe_sha256':'b'*64}
    model_ref=dump(tmp_path/'passing/model.json',model);parent=dump(tmp_path/'passing/terminal.json',{'passed':True})
    return runtime,lock,probe,model_ref,parent


def test_native_bundle_imports_portably_with_frozen_original_engine(runtime_case,tmp_path):
    runtime,lock,probe,model,parent=runtime_case;output=tmp_path/'native';runtime.prepare(model['path'],output)
    frozen=runtime.validate_prepared(output)
    assert frozen['version']==2 and frozen['kind'].endswith('_api_v2')
    assert set(frozen['source_code'])=={'spec.py','frozen_spec.py','model_a.py','frozen_model_a.py','highs_engineering.py','frozen_highs_engineering.py'}
    assert frozen['request']['time_limit_seconds']==800 and frozen['resources']['cpus']==2 and frozen['network']=='none'
    package=output/'job_bundle';code="import sys,json;sys.dont_write_bytecode=True;sys.path.insert(0,sys.argv[1]);from portfolio import highs_engineering as e;model=json.load(open(sys.argv[2]));assert e.API_VERSION==2;assert e.exact_plan_check(model,[0,1,1])['objective_pence']==13;assert 'highspy' not in sys.modules;print('portable API-v2 import PASS')"
    completed=subprocess.run([sys.executable,'-I','-c',code,str(package),model['path']],capture_output=True,text=True,timeout=30)
    assert completed.returncode==0,completed.stderr
    assert 'portable API-v2 import PASS' in completed.stdout
    assert not list(package.rglob('__pycache__'))
    assert runtime.validate_prepared(output)==frozen
    (package/'portfolio/frozen_highs_engineering.py').write_text('changed')
    with pytest.raises(ValueError):runtime.validate_prepared(output)


@pytest.fixture
def entry_case(runtime_case,monkeypatch,tmp_path):
    runtime,lock,probe,model,parent=runtime_case
    path=ROOT/'scripts/run_linear_capital_scaled_highs_screen_api_v2.py';descriptor=importlib.util.spec_from_file_location('_api_v2_entry_case',path)
    entry=importlib.util.module_from_spec(descriptor);descriptor.loader.exec_module(entry)
    monkeypatch.setattr(entry,'TINY_ROOT',Path(model['path']).parent);monkeypatch.setattr(entry,'TINY_MODEL_SHA256',model['sha256'])
    monkeypatch.setattr(entry,'TINY_PARENT_SHA256',parent['sha256']);monkeypatch.setattr(entry.highs_runtime,'build_runtime',lambda *a:runtime)
    failure=dump(tmp_path/'original_failure.json',{'native_api_attempts':1,'native_run_reached':False,'P01_started':False,'owned_cleanup_passed':True})
    monkeypatch.setattr(entry,'FAILURE_PATH',Path(failure['path']));monkeypatch.setattr(entry,'FAILURE_SHA256',failure['sha256'])
    tiny=tmp_path/'tiny';entry.prepare_tiny(tiny,vendor_lock=lock['path'],dependency_probe=probe['path'])
    return entry,runtime,tiny


def test_new_tiny_identity_parent_failure_and_complete_recipe_are_cold_bound(entry_case):
    entry,runtime,tiny=entry_case;frozen,_,_=entry.checked_tiny_prospective(tiny)
    assert frozen['kind'].endswith('_api_v2') and frozen['version']==2
    assert frozen['api_compatibility_parent_failure']==entry._prior_failure()
    for path in (entry.ADAPTER_UPSTREAM,adapter.ADAPTER_UPSTREAM,engine.upstream_path(),Path(engine.__file__)):
        assert str(path.resolve()) in frozen['recipe']
    assert runtime.validate_prepared(tiny/'native')['version']==2


def test_prior_failure_cannot_count_as_new_tiny_pass_and_new_failure_is_once_only(entry_case,monkeypatch):
    entry,runtime,tiny=entry_case;calls=[]
    old=entry.read(tiny/'prospective.json');old['version']=1;old['kind']='prepared_fixed_scaled_highs2_three_project_api_smoke'
    previous=tiny.parent/'previous';dump(previous/'prospective.json',old)
    with pytest.raises(ValueError):entry.checked_tiny_prospective(previous)
    def failed(output):calls.append(output);raise RuntimeError('Explicit mocked API-v2 native failure')
    monkeypatch.setattr(runtime,'execute_prepared',failed)
    with pytest.raises(RuntimeError):entry.execute_tiny(tiny)
    assert entry.read(tiny/'tiny_failure.json')['retry_authorized'] is False
    with pytest.raises(ValueError,match='no retries'):entry.execute_tiny(tiny)
    with pytest.raises(ValueError,match='failed API smoke'):entry.checked_tiny_completed(tiny)
    assert calls==[tiny/'native']


def test_all_old_files_remain_exactly_frozen():
    for path,expected in {
        'src/sheets_factory/workbook/linear_capital_scaled/highs_engineering.py':'d9c2c42e01475232b024c09a3d353d5e7ad14bcf679be17398ce24b5fd78b2cd',
        'src/sheets_factory/workbook/linear_capital_scaled/highs_runtime.py':'b37ca2f1ad1a9eb98fc2bb527de9c67b8a3b35a2c331e6e1b7a2bf16881de0b3',
        'scripts/run_linear_capital_scaled_highs_screen.py':'563f2b0a1f9f3910421a40bdb30476a39a643c2cb0b61967d0257fdf6d04c7b1',
        'tests/test_linear_capital_scaled_highs_runtime.py':'7d922777f008b4f2da6c3f985513115fee44d15868ab1e0167c73577a4673a12',
        'docs/linear_capital_scaled_highs_screen.md':'0b59f03622373a23c4f809ff53216de3eb510ceb11884288a528995ae61d04fb'}.items():
        assert ref(ROOT/path)['sha256']==expected


@pytest.mark.parametrize('layer',['engine','runtime','driver'])
def test_upstream_hash_guards_are_rechecked_after_import(tmp_path,monkeypatch,layer):
    if layer=='engine':
        original=engine.upstream_path();module=engine
    elif layer=='runtime':
        original=adapter.ADAPTER_UPSTREAM;module=adapter
    else:
        path=ROOT/'scripts/run_linear_capital_scaled_highs_screen_api_v2.py';descriptor=importlib.util.spec_from_file_location('_api_v2_hash_case',path)
        module=importlib.util.module_from_spec(descriptor);descriptor.loader.exec_module(module);original=module.ADAPTER_UPSTREAM
    changed=tmp_path/'changed.py';changed.write_bytes(original.read_bytes()+b'\n')
    if layer=='engine':monkeypatch.setattr(module,'upstream_path',lambda:changed)
    else:monkeypatch.setattr(module,'ADAPTER_UPSTREAM',changed)
    with pytest.raises(ValueError,match='frozen pre-API-v2'):module.adapted_ast()
