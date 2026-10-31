"""No engine/model/optimizer services are used by these interface tests."""
import json
import os
from pathlib import Path

import pytest

from sheets_factory.pipelines import linear_capital_quality as admission


def write(path, value):
    path.write_text(json.dumps(value))
    return admission.reference(path)


def module_record(path):
    record=admission.reference(path)
    return {**record,'path':str(path.relative_to(admission.ROOT))}


@pytest.fixture
def provider(tmp_path):
    # pytest --basetemp is deliberately below /data/.../outputs/tmp.
    root = tmp_path
    payload = root/'source.xlsx';payload.write_bytes(b'uncached fixture bytes')
    primitive = write(root/'raw.json', {'provided': 1})
    binding = write(root/'bindings.json', {'rows': []})
    profile = write(root/'profile.json', {'fixture': True})
    child = root/'child.txt';child.write_text('original resource proof')
    nested = write(root/'evidence.json', {'resource': admission.reference(child)})
    proof = {'kind':'fixture_validated_linear_source','version':1,'source_financially_verified':True,
        'workbook':admission.reference(payload),'public_specification':primitive,'bindings':binding,
        'runtime_profile':profile,'evidence':nested,'source_recipe_sha256':{}}
    manifest = write(root/'source_manifest.json', proof)
    module = root/'provider.py'
    module.write_text("""import json
from pathlib import Path
SOURCE_KIND='fixture_validated_linear_source'
calls=0
def validate_source(record):
 global calls
 calls+=1
 value=json.loads(Path(record['path']).read_text())
 if value.get('source_financially_verified') is not True: raise ValueError('not independently verified')
 return value
def validate_actual_call(*args): raise AssertionError('no actual call is allowed')
def runtime(*args): raise AssertionError('no runtime service is allowed')
""")
    row={'id':'fixture','module':module_record(module),'source_kind':proof['kind'],'api_version':1,
        'functions':{'validate_source':'validate_source','validate_actual_call':'validate_actual_call','runtime':'runtime'}}
    registry = write(root/'providers.json', {'kind':'linear_capital_source_provider_registry','version':1,'providers':[row]})
    return root, manifest, registry, row


def test_one_cold_validation_then_only_guards(provider, monkeypatch):
    _, manifest, registry, _ = provider
    # No subprocess entry is permitted, even during provider loading.
    import subprocess
    monkeypatch.setattr(subprocess,'run',lambda *a,**k: (_ for _ in ()).throw(AssertionError('service call')))
    session=admission.LinearSourceAdmission(manifest,provider_id='fixture',provider_registry=registry)
    assert session.helper.calls == 1
    for _ in range(5):
        assert admission.require_source_admission(session)['workbook']
    assert session.helper.calls == session.cold_source_validation_count == 1


def test_persisted_boolean_and_unregistered_object_do_not_admit(provider):
    with pytest.raises(ValueError,match='Persisted'):
        admission.require_source_admission({'admitted':True})
    fake=object.__new__(admission.LinearSourceAdmission)
    with pytest.raises(ValueError,match='Persisted'):
        admission.require_source_admission(fake)


def test_returned_proof_is_not_mutable_session_state(provider):
    _, manifest, registry, _=provider
    session=admission.LinearSourceAdmission(manifest,provider_id='fixture',provider_registry=registry)
    first=session.guard();first['workbook']['sha256']='0'*64
    assert session.guard()['workbook']['sha256'] != '0'*64


@pytest.mark.parametrize('filename',['source.xlsx','child.txt','provider.py','source_manifest.json'])
def test_guard_rejects_current_bytes_or_transitive_evidence_changes(provider,filename):
    root,manifest,registry,_=provider
    session=admission.LinearSourceAdmission(manifest,provider_id='fixture',provider_registry=registry)
    path=root/filename; old=path.stat(); data=path.read_bytes()
    path.write_bytes(bytes([data[0]^1])+data[1:])
    os.utime(path,ns=(old.st_atime_ns,old.st_mtime_ns))
    with pytest.raises(ValueError,match='changed'):
        session.guard()


def test_metadata_only_change_is_rehashed_and_preserves_admission(provider):
    root,manifest,registry,_=provider
    session=admission.LinearSourceAdmission(manifest,provider_id='fixture',provider_registry=registry)
    path=root/'source.xlsx';info=path.stat();os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns+1))
    assert session.guard()['source_financially_verified'] is True
    assert session.helper.calls == 1


def test_unknown_provider_and_wrong_kind_reject(provider):
    root,manifest,registry,row=provider
    with pytest.raises(ValueError,match='Unknown provider'):
        admission.LinearSourceAdmission(manifest,provider_id='auto_discovered',provider_registry=registry)
    row['source_kind']='different'
    other=write(root/'other_registry.json',{'kind':'linear_capital_source_provider_registry','version':1,'providers':[row]})
    with pytest.raises(ValueError,match='API/kind'):
        admission.SourceProviders(other).load('fixture')


@pytest.mark.parametrize('field,value',[('version',True),('version',2)])
def test_registry_versions_are_exact_integers(provider,field,value):
    root,_,_,row=provider
    record=write(root/'bad_registry.json',{'kind':'linear_capital_source_provider_registry',field:value,'providers':[row]})
    with pytest.raises(ValueError):admission.SourceProviders(record)


def test_wrong_module_hash_and_duplicate_provider_reject(provider):
    root,_,_,row=provider
    row['module']['sha256']='0'*64
    record=write(root/'bad_hash.json',{'kind':'linear_capital_source_provider_registry','version':1,'providers':[row]})
    with pytest.raises(ValueError,match='changed'):admission.SourceProviders(record)
    row['module']=module_record(root/'provider.py')
    record=write(root/'duplicate.json',{'kind':'linear_capital_source_provider_registry','version':1,'providers':[row,row]})
    with pytest.raises(ValueError,match='unique provider'):admission.SourceProviders(record)


def test_actual_default_registry_loads_only_code_and_declared_kinds():
    providers=admission.SourceProviders()
    assert set(providers.providers)=={'standard','producer16'}
    for provider_id in providers.providers:
        row,module=providers.load(provider_id)
        assert module.SOURCE_KIND==row['source_kind']
        assert callable(module.validate_source)


def test_symlink_artifacts_reject(tmp_path):
    source=tmp_path/'file';source.write_text('x');link=tmp_path/'link';link.symlink_to(source)
    with pytest.raises(ValueError,match='nonsymlink'):admission.reference(link)


def test_provider_registry_moves_to_a_different_checkout(provider,monkeypatch):
    root,_,_,row=provider
    checkout=root/'moved_checkout';checkout.mkdir();(checkout/'scripts').mkdir()
    original=root/'provider.py';copied=checkout/'scripts/provider.py';copied.write_bytes(original.read_bytes())
    row['module']={**admission.reference(copied),'path':'scripts/provider.py'}
    registry=write(checkout/'providers.json',{'kind':'linear_capital_source_provider_registry','version':1,'providers':[row]})
    monkeypatch.setattr(admission,'ROOT',checkout)
    descriptor,module=admission.SourceProviders(registry).load('fixture')
    assert descriptor['module']['path']==str(copied)
    assert module.__file__==str(copied)


@pytest.mark.parametrize('path',['../provider.py','scripts/../provider.py','/data/provider.py','./provider.py'])
def test_module_paths_reject_escape_absolute_and_dot(provider,path):
    root,_,_,row=provider;row['module']['path']=path
    registry=write(root/'bad_path.json',{'kind':'linear_capital_source_provider_registry','version':1,'providers':[row]})
    with pytest.raises(ValueError,match='project-relative'):
        admission.SourceProviders(registry)


def test_provider_module_symlink_is_rejected(provider):
    root,_,_,row=provider;link=root/'linked.py';link.symlink_to(root/'provider.py')
    row['module']['path']=str(link.relative_to(admission.ROOT))
    registry=write(root/'symlink_registry.json',{'kind':'linear_capital_source_provider_registry','version':1,'providers':[row]})
    with pytest.raises(ValueError,match='symlinks'):admission.SourceProviders(registry)
