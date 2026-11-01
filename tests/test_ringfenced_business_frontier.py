"""Larger cell limits retain the original timing, resource and phase contract."""
from contextlib import contextmanager
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest
import yaml

ROOT=Path(__file__).resolve().parents[1]
def load(path,name):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
fixtures=load(ROOT/'tests/test_business_revision_frontier.py','_ringfenced_frontier_fixtures')


@pytest.fixture
def entry(monkeypatch,tmp_path):
    m=load(ROOT/'scripts/run_ringfenced_business_frontier.py','_ringfenced_frontier_test')
    @contextmanager
    def monitor(*args,**kwargs):
        yield SimpleNamespace(task=lambda *a,**k:None,update_run=lambda *a,**k:None,export=lambda:None)
    monkeypatch.setitem(m.protocol._N,'monitor',monitor)
    monkeypatch.setitem(m.protocol._N,'RESERVATIONS',tmp_path/'reservations')
    monkeypatch.setitem(m.protocol._N,'OLD_RESERVATIONS',(tmp_path/'old',))
    monkeypatch.setattr(fixtures.OLD_TESTS,'export_resource_harbor',m.resources.export_resource_harbor)
    return m


def test_actual_resource_export_freezes_with_declared_larger_profile(entry,tmp_path):
    factory=fixtures.batch.__wrapped__(entry.protocol,tmp_path)
    batch=factory('ringfenced',(1,1))
    prepared=entry.protocol.read(entry.prepare([batch.ref],tmp_path/'prepared'))
    assert len(prepared['tasks'])==2 and prepared['phase']=='development'
    assert prepared['recipe']['profile']==entry.protocol.ref(entry.PROFILE)
    assert prepared['recipe']['ringfenced_development_entry']==entry.protocol.ref(entry.__file__)
    assert entry.protocol.validate_prepared(tmp_path/'prepared')==prepared
    assert prepared['outer_retries']==0 and prepared['attempts_per_task']==1
    assert entry.protocol._N['RESERVATIONS']==tmp_path/'reservations'
    selection=entry.runner.freeze_selection(prepared['source']['path'],tmp_path/'native-selection',phase='development')
    assert selection['n_attempts']==1 and selection['tool_time_policy_version']==6
    assert selection['infrastructure_retry_policy']['max_retries']==0
    assert selection['model']=='gpt-6.1-sol' and selection['reasoning_effort']=='xhigh'
    observed=entry.observer._namespace['_profile_for_task'](batch.tasks[0]['task_directory'])
    assert observed['value']['id']=='ringfenced_pair_source_v1'


def test_cell_limits_do_not_raise_hardware_or_solver_time(entry):
    declared=yaml.safe_load(entry.PROFILE.read_text())
    ordinary=yaml.safe_load((ROOT/'config/runtime_profiles/entity_group_large_v2.yaml').read_text())
    for key in ('image','docker_resources','timeouts','solver_tool_budget'):
        assert declared[key]==ordinary[key]
    assert declared['limits']['source_physical_formulas']==2600000
    assert entry.protocol.BUDGET['tool_budget_seconds']==1800
    assert entry.protocol._N['check_task'].__globals__['PROFILE']==entry.PROFILE


def test_wrong_plan_profile_is_rejected_instead_of_relabelled(entry,tmp_path):
    factory=fixtures.batch.__wrapped__(entry.protocol,tmp_path);batch=factory('wrong',(1,1))
    task=batch.tasks[0].copy();plan=entry.protocol.read(task['plan_freeze'])
    plan['runtime_profile']=entry.protocol.ref(ROOT/'config/runtime_profiles/entity_group_large_v2.yaml')
    task['plan_freeze']=entry.protocol.write(tmp_path/'wrong-plan.json',plan)
    with pytest.raises(ValueError,match='predeclared engineering plan'):
        entry.protocol.check_task(task)


def test_profile_byte_changes_stop_before_preparation(entry,monkeypatch,tmp_path):
    monkeypatch.setattr(entry,'PROFILE_SHA','0'*64)
    with pytest.raises(ValueError,match='resource profile changed'):
        entry.prepare([],tmp_path/'never-created')
    assert not (tmp_path/'never-created').exists()
