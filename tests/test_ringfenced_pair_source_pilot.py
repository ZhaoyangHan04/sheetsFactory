"""Pure lifecycle/resource guards, no native processes or production workbooks."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def module():
    p=ROOT/'scripts/run_ringfenced_pair_source_pilot.py';s=importlib.util.spec_from_file_location('_pair_source_test',p)
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def test_geometry_is_only_profile_change_and_all_hardware_time_budget_stays_original(module):
    p=module.load_profile()
    assert p['limits']=={'source_physical_formulas':2600000,'max_profile_cells':3600000,
        'max_dependency_closure_cells':3600000,'full_target_cells':3200000,'truncate':False}
    assert all(v=={'cpus':2,'memory_bytes':32*1024**3,'pids_limit':256} for v in p['docker_resources'].values())
    assert p['timeouts']=={'workbook_file_seconds':600,'verifier_total_seconds':2400}
    assert p['solver_tool_budget']=={'seconds':1800,'strict_less_than':True,'exclude_model_response_time':True,'parallel_executions':'sum'}
    assert p['image']['id']=='sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
    for change in ('hardware','timeout','geometry'):
        bad=deepcopy(p)
        if change=='hardware':bad['docker_resources']['source']['cpus']=4
        elif change=='timeout':bad['timeouts']['workbook_file_seconds']=1200
        else:bad['limits']['full_target_cells']=3200001
        with pytest.raises(ValueError,match='identity may differ'):module.load_profile(bad)


def test_actual_resource_classes_are_private_and_bound_only_to_new_loader(module):
    cap=module._N['engines']()
    assert cap.base is not module._N['resource_base']
    assert cap.base.load_runtime_profile is module.load_profile
    assert cap.ThreadCappedResourceLibreOfficeEngine is not module._N['cap_base'].ThreadCappedResourceLibreOfficeEngine
    assert cap.base.ResourceLibreOfficeEngine is not module._N['resource_base'].ResourceLibreOfficeEngine


def test_new_source_kinds_and_entire_ancestor_recipe_are_explicit(module):
    r=module.recipes()
    assert r[str(module.UPSTREAM)]['sha256']==module.UPSTREAM_SHA
    assert module.KIND=='prepared_two_ringfenced_pair_source_engineering_pilot'
    assert module.TERMINAL_KIND=='completed_two_ringfenced_pair_source_engineering_pilot'
    for name in ('contract','composition','stream_composition','group_report'):
        assert str(Path(module._N[name].__file__).resolve()) in r
    for path,digest in module._N['PINS'].items():assert r[str(path)]['sha256']==digest


def test_genuine_source3_and_completed_resource_validator_bytecode_are_unchanged(module):
    p=module.UPSTREAM;s=importlib.util.spec_from_file_location('_old_pair_pilot_test',p)
    old=importlib.util.module_from_spec(s);s.loader.exec_module(old)
    for name in ('execute_prepared','validate_completed','audit_workbook','engines'):
        assert module._N[name].__code__.co_code==getattr(old,name).__code__.co_code
    assert module._N['STAGES']==('source1','source2','source3')
    assert old.PROFILE.name=='ringfenced_group_source_pilot_v1.yaml'
    assert old.load_profile()['limits']['source_physical_formulas']==5200000


def test_parent_panel_precedes_cold_operation_and_preserves_failure_without_services(module,tmp_path,monkeypatch):
    events=[]
    class Audit:
        def __init__(self,path,*a):path.mkdir(parents=True);self.db=SimpleNamespace(close=lambda:events.append('close'))
        def snapshot(self):return {}
        def events(self):return []
        def update_run(self,**k):events.append(k.get('status',k.get('phase','update')))
        def export(self):pass
    class Panel:
        def __init__(self,*a,**k):pass
        def start(self):events.append('panel');return 'http://unit.invalid/'
        def stop(self):events.append('stop')
    monkeypatch.setitem(module._N,'AuditStore',Audit);monkeypatch.setitem(module._N,'DashboardServer',Panel)
    def fail():events.append('cold');raise ValueError('whole proof rejected')
    out=tmp_path/'out'
    with pytest.raises(ValueError,match='whole proof'):module._observed('source_prepare',out,fail)
    assert events.index('panel')<events.index('cold')
    assert (tmp_path/'out_source_prepare_audit/failure.json').exists() and not out.exists()
    with pytest.raises(ValueError,match='first command'):module._observed('source_prepare',out,lambda:pytest.fail('retry'))


def test_prepare_and_run_dispatch_only_frozen_genuine_private_functions(module,tmp_path,monkeypatch):
    seen=[]
    monkeypatch.setattr(module,'_observed',lambda label,out,op:(seen.append(label),op())[1])
    monkeypatch.setitem(module._N,'prepare',lambda *args:('prepared',args))
    monkeypatch.setitem(module._N,'execute_prepared',lambda *args:('ran',args))
    assert module.prepare('certificate','composition',tmp_path/'out')[0]=='prepared'
    assert module.execute_prepared(tmp_path/'out')[0]=='ran'
    assert seen==['source_prepare','source_execute']
