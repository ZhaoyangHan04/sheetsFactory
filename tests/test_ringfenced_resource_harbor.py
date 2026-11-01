"""Tiny real exports and isolated runtime loading; no Docker, LO or model calls."""
import ast
from copy import deepcopy
import difflib
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tomllib

import openpyxl
import pytest

from sheets_factory.evaluation import ringfenced_resource_harbor as m
from sheets_factory.evaluation import ringfenced_streaming_verifier as runtime
from sheets_factory.evaluation import resource_streaming_verifier as old_runtime
from sheets_factory.workbook.resource_engine import load_runtime_profile as original_loader


@pytest.fixture
def task(tmp_path):
    path=tmp_path/'task';(path/'public').mkdir(parents=True);(path/'private').mkdir()
    for relative,number in [('public/input.xlsx',10),('private/goal.xlsx',20)]:
        book=openpyxl.Workbook();book.active.title='Model';book.active['A1']='Public cash policy'
        book.active['B2']=number;book.active['C2']=True;book.active['C2'].number_format='General'
        book.active['D2']='N/A';book.create_sheet('Historical')['A1']=100
        book.save(path/relative);book.close()
    (path/'public/instruction.md').write_bytes(b'Restore the investment model. Preserve inputs and save /app/output.xlsx.\n')
    return path


@pytest.fixture
def exported(task,tmp_path):
    audit=tmp_path/'private_cap.json'
    path=m.export_resource_harbor(task,tmp_path/'export',
        {'task_id':'ring-toy','mode':'debugging','revision':0,'revision_hash':'a'*64},audit_path=audit)
    return path,audit


def rehash(path):
    manifest=json.loads((path/'export_manifest.json').read_text())
    manifest['files']={p.relative_to(path).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in path.rglob('*')if p.is_file()and p.name!='export_manifest.json'}
    (path/'export_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')


def test_real17_export_preserves_ring_identity_core_payload_and_private_cap_audit(exported,task):
    path,audit=exported
    binding=m.inspect_resource_export(path,audit_path=audit)
    assert m.inspect_export(path)==m.inspect_resource_export(path)==binding
    profile=m.load_runtime_profile();contract=binding['resource_runtime']
    assert profile['id']=='ringfenced_pair_source_v1'and contract['profile']==profile
    assert profile['limits']=={'source_physical_formulas':2600000,'max_profile_cells':3600000,
        'max_dependency_closure_cells':3600000,'full_target_cells':3200000,'truncate':False}
    assert len([p for p in path.rglob('*')if p.is_file()])==17
    assert contract['recipe']==m.recipes()
    assert contract['recipe']['verifier_wrapper']['sha256']==m.RUNTIME_SHA256
    assert contract['recipe']['resource_exporter_base']['sha256']==m.RESOURCE_EXPORT_SHA256
    assert contract['recipe']['worker_cap_exporter_base']['sha256']==m.CAP_EXPORT_SHA256
    assert contract['recipe']['exporter']==m._reference(m.__file__)
    assert contract['profile_binding']==m._reference(m.PROFILE)
    assert contract['actual_container_resources_verified']is contract['quality_or_difficulty_certified']is False
    assert contract['harbor_pid_limit_configured']is False
    assert (path/'instruction.md').read_bytes()==(task/'public/instruction.md').read_bytes()
    assert (path/'tests/reference.xlsx').read_bytes()==(task/'private/goal.xlsx').read_bytes()
    assert (path/'environment/input.xlsx').read_bytes()==(task/'public/input.xlsx').read_bytes()
    for folder,filename in [('environment','resource_runner.py'),('tests','verify.py')]:
        assert (path/folder/filename).read_bytes()==Path(runtime.__file__).read_bytes()
        assert runtime.load_profile(path/folder/'runtime_profile.json')==profile
        assert (path/folder/'Dockerfile').read_bytes().splitlines()[1]==b'ENV MAX_CONCURRENCY=2'
    config=tomllib.loads((path/'task.toml').read_text())
    assert config['environment']['cpus']==config['verifier']['environment']['cpus']==2
    assert config['environment']['memory_mb']==config['verifier']['environment']['memory_mb']==32768
    assert config['agent']['timeout_sec']==14400 and config['verifier']['timeout_sec']==2400
    evidence=json.loads(audit.read_text())
    assert evidence['implementation']['adapter']==m._reference(m.__file__)
    assert evidence['implementation']['base_worker_cap_exporter']['sha256']==m.CAP_EXPORT_SHA256
    assert len(evidence['unchanged_payload_files'])==14


@pytest.mark.parametrize('fault',['old_id','version_bool','memory','cpu','pid','timeout','budget','parallel',
    'strict_bool','geometry','truncate','image','image_tag','extra','missing'])
def test_both_loaders_reject_any_profile_change(tmp_path,fault):
    p=m.load_runtime_profile()
    if fault=='old_id':p['id']='entity_group_large_v2'
    elif fault=='version_bool':p['version']=True
    elif fault=='memory':p['docker_resources']['agent']['memory_bytes']=8*1024**3
    elif fault=='cpu':p['docker_resources']['source']['cpus']=4
    elif fault=='pid':p['docker_resources']['verifier']['pids_limit']=257
    elif fault=='timeout':p['timeouts']['workbook_file_seconds']=601
    elif fault=='budget':p['solver_tool_budget']['seconds']=1801
    elif fault=='parallel':p['solver_tool_budget']['parallel_executions']='wall'
    elif fault=='strict_bool':p['solver_tool_budget']['strict_less_than']=1
    elif fault=='geometry':p['limits']['source_physical_formulas']=2600001
    elif fault=='truncate':p['limits']['truncate']=True
    elif fault=='image':p['image']['id']='sha256:'+'0'*64
    elif fault=='image_tag':p['image']['tag']='unapproved-image'
    elif fault=='extra':p['unknown']='x'
    else:p.pop('image')
    path=tmp_path/'profile.json';path.write_text(json.dumps(p))
    with pytest.raises(ValueError):runtime.load_profile(path)
    with pytest.raises(ValueError):m.load_runtime_profile(p)


def test_approved_profile_has_independent_return_value_and_symlinks_are_rejected(tmp_path):
    original=m.load_runtime_profile();changed=m.load_runtime_profile(original)
    changed['id']='mutated'
    assert original==m.load_runtime_profile()and original['id']=='ringfenced_pair_source_v1'
    alias=tmp_path/'alias.yaml';alias.symlink_to(m.PROFILE)
    with pytest.raises(ValueError,match='real file'):m.load_runtime_profile(alias)
    jsonpath=tmp_path/'profile.json';jsonpath.write_text(json.dumps(original));link=tmp_path/'link.json';link.symlink_to(jsonpath)
    with pytest.raises(ValueError,match='regular file'):runtime.load_profile(link)


def test_standalone_runtime_needs_no_factory_import_and_keeps_comparison_core(exported):
    path,audit=exported
    code=('import json,runpy; from pathlib import Path; '
        'n=runpy.run_path('+repr(str(path/'tests/verify.py'))+'); '
        'p=n["load_profile"]('+repr(str(path/'tests/runtime_profile.json'))+'); '
        'c=n["comparison_core"](); '
        'print(json.dumps({"profile":p["id"],"core":c.__name__}))')
    result=subprocess.run([sys.executable,'-I','-c',code],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)=={'profile':'ringfenced_pair_source_v1','core':'sheetsfactory_streaming_core'}
    assert len([p for p in path.rglob('*')if p.is_file()])==17
    m.inspect_resource_export(path,audit_path=audit)


@pytest.mark.parametrize('oracle',[True,False])
def test_standalone_verifier_retains_actual_three_call_protocol_and_numeric_primary_contract(exported,tmp_path,oracle):
    path,audit=exported;ns=runpy.run_path(str(path/'tests/verify.py'));calls=[]
    def recalculate(source,destination,timeout=600):
        assert timeout==600;calls.append((source,destination));shutil.copyfile(source,destination)
    ns['main'].__globals__['recalculate']=recalculate
    output=tmp_path/'output.xlsx';shutil.copyfile(path/('tests/reference.xlsx'if oracle else'environment/input.xlsx'),output)
    reward=tmp_path/'reward.txt';report=tmp_path/'report.json'
    ns['main'](['--input',str(path/'tests/original_input.xlsx'),'--goal',str(path/'tests/reference.xlsx'),
        '--output',str(output),'--profile',str(path/'tests/runtime_profile.json'),'--reward',str(reward),'--report',str(report)])
    detail=json.loads(report.read_text())
    assert len(calls)==3 and int(reward.read_text())==int(oracle)
    assert all(c['completed']and c['timeout_seconds']==600 for c in detail['recalculation_calls'])
    assert detail['resource_contract']['profile_id']=='ringfenced_pair_source_v1'
    assert detail['resource_contract']['solver_tool_budget']['seconds']==1800
    assert detail['resource_contract']['requested_verifier_resources']['pids_limit']==256
    assert detail['resource_contract']['actual_container_resources_verified']is False


@pytest.mark.parametrize('role',['environment','tests'])
@pytest.mark.parametrize('fault',['missing','wrong','duplicate','misplaced'])
def test_no_audit_inspector_still_requires_both_exact_cap_lines(exported,role,fault):
    path,audit=exported;p=path/role/'Dockerfile';raw=p.read_bytes()
    if fault=='missing':raw=raw.replace(m._C.ENV_LINE,b'')
    elif fault=='wrong':raw=raw.replace(m._C.ENV_LINE,b'ENV MAX_CONCURRENCY=3\n')
    elif fault=='duplicate':raw=raw.replace(m._C.ENV_LINE,m._C.ENV_LINE*2)
    else:raw=raw.replace(m._C.ENV_LINE,b'')+m._C.ENV_LINE
    p.write_bytes(raw);rehash(path)
    with pytest.raises(ValueError,match='single second-line'):m.inspect_export(path)


@pytest.mark.parametrize('fault',['metadata','runtime','core','profile','extra_file','foreign_audit'])
def test_rehashed_export_cannot_replace_recipe_payload_profile_or_inventory(exported,tmp_path,fault):
    path,audit=exported
    if fault=='metadata':
        manifest=json.loads((path/'export_manifest.json').read_text());manifest['metadata'][m.CAP_FIELD]='MAX_CONCURRENCY=3'
        (path/'export_manifest.json').write_text(json.dumps(manifest))
    elif fault=='runtime':
        p=path/'tests/verify.py';p.write_bytes(p.read_bytes()+b'\n# changed runtime\n')
    elif fault=='core':
        p=path/'tests/streaming_core.py';p.write_bytes(p.read_bytes()+b'\n# changed comparison\n')
    elif fault=='profile':
        p=path/'tests/runtime_profile.json';value=json.loads(p.read_text());value['id']='entity_group_large_v2';p.write_text(json.dumps(value))
    elif fault=='extra_file':(path/'extra.txt').write_text('eighteenth file')
    else:
        value=json.loads(audit.read_text());value['export_directory']=str(tmp_path/'another');audit.write_text(json.dumps(value))
    rehash(path)
    with pytest.raises(ValueError):m.inspect_resource_export(path,audit_path=audit if fault=='foreign_audit'else None)


def test_external_audit_remains_exact_and_cannot_move_inside_export(task,tmp_path,exported):
    path,audit=exported;record=m._reference(audit);audit.write_text(audit.read_text()+'\n')
    with pytest.raises(ValueError):m.inspect_resource_export(path,audit_path=record)
    destination=tmp_path/'bad-export'
    with pytest.raises(ValueError,match='outside the seventeen'):
        m.export_resource_harbor(task,destination,audit_path=destination/'audit.json')
    assert not destination.exists()


def test_original_namespaces_remain_closed_and_calculation_bodies_unchanged():
    with pytest.raises(ValueError):original_loader(m.PROFILE)
    assert m.original.load_runtime_profile is original_loader
    assert m.original.resource_streaming_verifier is old_runtime
    assert m.original_cap.base is m.original
    assert m._B is not m.original and m._C is not m.original_cap
    for name in ('comparison_core','recalculate','_contract','main'):
        old=getattr(old_runtime,name);new=getattr(runtime,name)
        assert old.__code__.co_code==new.__code__.co_code and old.__code__.co_consts==new.__code__.co_consts
    assert m._reference(m.original.__file__)['sha256']==m.RESOURCE_EXPORT_SHA256
    assert m._reference(m.original_cap.__file__)['sha256']==m.CAP_EXPORT_SHA256
    assert m._reference(old_runtime.__file__)['sha256']==runtime.UPSTREAM_RESOURCE_RUNTIME_SHA256
