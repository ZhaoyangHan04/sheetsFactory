"""Pure boundary tests; no Docker, LibreOffice, model, or solver calls."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def module():
    path=ROOT/'scripts/validate_period_boundary_candidate_v2.py'
    spec=importlib.util.spec_from_file_location('_test_period_boundary_v2',path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


@pytest.mark.parametrize('message',[
    'error: no such object: {cid}\n','Error: No such object: {cid}\n',
    'NO SUCH CONTAINER: {cid}',' Error: No Such Container: {cid}\n',
])
def test_exact_owned_absence_message_is_case_insensitive(module,monkeypatch,message):
    cid='a'*64;commands=[]
    def run(command,**kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=1,stdout=' \n',stderr=message.format(cid=cid)) if command[1]=='inspect' else SimpleNamespace(returncode=0,stdout='29.1.3\n',stderr='')
    monkeypatch.setattr(module.subprocess,'run',run)
    result=module.owned_absence([{'actual_resource_evidence':{'container_id':cid}}])
    assert result['all_owned_containers_absent'] and result['daemon_reachable']
    assert commands==[['docker','inspect',cid,'--format','{{.Id}}'],['docker','version','--format','{{.Server.Version}}']]
    assert not result['cleanup_mutations_by_validator']


@pytest.mark.parametrize('returncode,stdout,stderr',[
    (1,'','permission denied'),(1,'','Cannot connect to the Docker daemon'),
    (1,'','error: no such object: '+'b'*64),(1,'','error: no such object: '+'a'*63),
    (1,'','error: no such object: '+'a'*64+'\npermission denied'),
    (0,'','error: no such object: '+'a'*64),(1,'a'*64,'error: no such object: '+'a'*64),
])
def test_other_failures_and_other_ids_are_never_absence(module,monkeypatch,returncode,stdout,stderr):
    monkeypatch.setattr(module.subprocess,'run',lambda command,**kwargs:
        SimpleNamespace(returncode=returncode,stdout=stdout,stderr=stderr) if command[1]=='inspect'
        else SimpleNamespace(returncode=0,stdout='29.1.3',stderr=''))
    result=module.owned_absence([{'actual_resource_evidence':{'container_id':'a'*64}}])
    assert not result['all_owned_containers_absent'] and not result['owned'][0]['absent']


def test_absence_without_live_daemon_never_passes_full_cleanup(module,monkeypatch):
    monkeypatch.setattr(module.subprocess,'run',lambda command,**kwargs:
        SimpleNamespace(returncode=1,stdout='',stderr='error: no such object: '+'a'*64) if command[1]=='inspect'
        else SimpleNamespace(returncode=1,stdout='',stderr='connection refused'))
    result=module.owned_absence([{'actual_resource_evidence':{'container_id':'a'*64}}])
    assert result['all_owned_containers_absent'] and not result['daemon_reachable']


@pytest.mark.parametrize('ids',[['short'],['a'*64,'a'*64]])
def test_incomplete_or_duplicate_ownership_is_rejected_before_commands(module,monkeypatch,ids):
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**k:pytest.fail('No command allowed'))
    with pytest.raises(ValueError,match='Distinct full owned'):
        module.owned_absence([{'actual_resource_evidence':{'container_id':cid}} for cid in ids])


def test_versioned_private_namespace_preserves_original_bytes_and_recipe(module,tmp_path):
    assert hashlib.sha256(module.UPSTREAM.read_bytes()).hexdigest()==module.UPSTREAM_SHA256
    assert module._PRIVATE['KIND']==module.KIND=='prepared_period_boundary_shared_engineering_v2'
    assert module.VERSION==2 and len(module.STAGES)==10
    assert module.execute_prepared.__globals__ is module._PRIVATE
    assert module._PRIVATE['owned_absence'] is module.owned_absence
    assert module.TERMINAL_KIND in module.execute_prepared.__code__.co_consts
    assert module.TERMINAL_KIND in module.validate_completed.__code__.co_consts
    assert 'period_boundary_actual_shared_engineering_validation' not in module.validate_completed.__code__.co_consts
    recipe=module.recipes()
    assert recipe[str(module.UPSTREAM)]['sha256']==module.UPSTREAM_SHA256
    assert recipe[str(ROOT/'scripts/validate_period_boundary_candidate_v2.py')]==module.reference(ROOT/'scripts/validate_period_boundary_candidate_v2.py')
    base={'kind':module.KIND,'version':2,'recipe':recipe,'stage_order':list(module.STAGES),'required_actual_LO_calls':10,
        'candidate_manifest':module.reference(module.UPSTREAM),'candidate_bindings':module.reference(module.UPSTREAM),
        'runtime_profile':module.reference(module.UPSTREAM),'planned_inputs':{}}
    path=tmp_path/'preparation.json';path.write_text(json.dumps(base))
    assert module.validate_prepared(tmp_path)==base
    for kind,version in [('prepared_period_boundary_shared_engineering',1),(module.KIND,1)]:
        path.write_text(json.dumps({**base,'kind':kind,'version':version}))
        with pytest.raises(ValueError):module.validate_prepared(tmp_path)
    with pytest.raises(ValueError,match='complete, original ten-call'):
        module.validate_completed({'path':str(path),'sha256':module.reference(path)['sha256'],'bytes':path.stat().st_size})


def test_upstream_drift_fails_closed_before_namespace_execution(module,tmp_path,monkeypatch):
    upstream=tmp_path/'changed.py';upstream.write_text('raise RuntimeError("must not execute")\n')
    monkeypatch.setattr(module,'UPSTREAM',upstream)
    with pytest.raises(ValueError,match='Frozen original'):
        module._namespace()
