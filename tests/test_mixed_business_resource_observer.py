"""Real tiny exports plus simulated actual role observations; no Docker calls."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

from sheets_factory.evaluation import mixed_business_resource_observer as mixed
from sheets_factory.evaluation import mixed_business_resources as resources
from sheets_factory.evaluation import ringfenced_resource_harbor as ring

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_mixed_observer_existing_daemon_fixtures',ROOT/'tests/test_resource_observer.py')
fixtures = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixtures)
obs = SimpleNamespace(**mixed._namespace)


@pytest.fixture(params=['entity_group_large_v2','ringfenced_pair_source_v1'])
def family(request,monkeypatch,tmp_path):
    monkeypatch.setattr(fixtures,'observer',obs)
    if request.param == 'ringfenced_pair_source_v1':
        monkeypatch.setattr(fixtures,'PROFILE',ring.PROFILE)
        monkeypatch.setattr(fixtures,'export_resource_harbor',lambda *a,**kw:ring.export_resource_harbor(*a,**kw,audit_path=tmp_path/'cap.json'))
    f = fixtures.family.__wrapped__(tmp_path)
    f.profile = fixtures.PROFILE
    return f


def test_both_actual_roles_pass_full_internal_export_validation(family):
    original = obs._reference(family.trial/'result.json')
    watch, daemon = fixtures.collect(family)
    result = fixtures.check(family,watch)
    assert result['passed'] is result['complete'] is True
    assert result['roles_observed'] == ['agent','verifier']
    assert result['runtime_profile']['value']['id'] == resources.load_runtime_profile(family.profile)['id']
    assert original == obs._reference(family.trial/'result.json')
    assert mixed.validate_observation_receipt(family.run,family.selection,family.evaluation)['passed'] is True
    assert all('Env' not in str(command) for command,_ in daemon.commands)


@pytest.mark.parametrize('defect',['wrong_cpu','wrong_ram','missing_verifier','unrelated_image'])
def test_mixed_profiles_do_not_relax_actual_resource_checks(family,defect):
    daemon = fixtures.Daemon(family)
    if defect == 'wrong_cpu': daemon.capacity={'agent':{'NanoCpus':4*10**9}}
    if defect == 'wrong_ram': daemon.capacity={'verifier':{'Memory':64*1024**3}}
    if defect == 'missing_verifier': daemon.roles=['agent']
    if defect == 'unrelated_image': daemon.ancestry=False
    watch,_ = fixtures.collect(family,daemon)
    result = fixtures.check(family,watch)
    assert result['passed'] is False


@pytest.mark.parametrize('defect',['unknown_id','more_cpu','more_ram','thread_change'])
def test_declared_profile_dispatch_is_exact(defect):
    value=deepcopy(ring.load_runtime_profile())
    if defect=='unknown_id':value['id']='arbitrary_large_profile'
    if defect=='more_cpu':value['docker_resources']['agent']['cpus']=4
    if defect=='more_ram':value['docker_resources']['verifier']['memory_bytes']*=2
    if defect=='thread_change':value['unapproved_threads']=4
    with pytest.raises((ValueError,KeyError)):
        resources.load_runtime_profile(value)


def test_exact_root_commands_and_all_twenty_assertions_remain_unchanged():
    spec=importlib.util.spec_from_file_location('_mixed_controls_test',ROOT/'scripts/run_mixed_business_root_harbor_controls.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    assert m.namespace['COMMANDS']=={role:['harbor','run','-p','SpreadsheetEval','-a',role] for role in ('oracle','nop')}
    assert m.namespace['ResourceObserver'] is mixed.ResourceObserver
    assert m.namespace['validate_trial_observations'] is mixed.validate_trial_observations
    import ast
    original=ast.parse(m.BASE.read_text());adapted=m.adapted_ast()
    for a,b in zip(original.body,adapted.body):
        if isinstance(a,(ast.FunctionDef,ast.ClassDef)):
            assert ast.dump(a)==ast.dump(b)
