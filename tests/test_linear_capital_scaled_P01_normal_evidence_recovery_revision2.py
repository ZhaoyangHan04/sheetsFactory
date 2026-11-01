"""Only absent/zero WAL compatibility changes; stored-run checks stay strict."""
import ast
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


@pytest.fixture
def stored(tmp_path,monkeypatch):
    fixtures=load('tests/test_linear_capital_scaled_P01_normal_evidence_recovery.py','_recovery_v2_stored_run_fixtures')
    old,run,tasks,contexts,calls=fixtures.stored.__wrapped__(tmp_path,monkeypatch)
    m=load('scripts/recover_linear_capital_scaled_P01_normal_evidence_revision2.py','_test_P01_recovery_v2')
    for name in ('RUN','PROPOSAL','validate_trial_observations'):
        monkeypatch.setitem(m._N,name,getattr(old,name))
    return m,run,tasks,contexts,calls,fixtures


@pytest.mark.parametrize('empty_wal',[False,True])
def test_complete_same_stored_proof_passes_without_writing_sqlite_or_original_artifacts(stored,tmp_path,empty_wal):
    m,run,_,_,calls,fixtures=stored
    if empty_wal:(run/'run.sqlite-wal').write_bytes(b'')
    (run/'run.sqlite-shm').write_bytes(b'S'*32768)
    before=fixtures.tree(run);out=tmp_path/'fresh_v2'
    prospective=m.prepare(out);f=json.loads(Path(prospective['path']).read_text())
    assert f['version']==2 and f['kind'].endswith('_revision2')
    assert f['sqlite_snapshot']['wal']['exists'] is empty_wal
    assert f['prior_recovery_lineage']==m.LINEAGE and not calls
    certificate=m.certify(out);result=json.loads(Path(certificate['path']).read_text())
    assert result['version']==2 and result['kind'].endswith('_revision2')
    assert result['evidence_recovered'] is True and len(calls)==4
    assert result['sqlite_snapshot_at_preparation']==result['sqlite_snapshot_at_exit']==f['sqlite_snapshot']
    assert result['SQLite_database_or_sidecar_write_delete_checkpoint_performed'] is False
    assert result['qualified'] is result['formal_release'] is result['original_statuses_changed'] is False
    assert fixtures.tree(run)==before
    with pytest.raises(ValueError,match='first certificate'):m.certify(out)


@pytest.mark.parametrize('content',[b'x',b'\x00'*32,b'SQLite format 3\x00'+b'\x00'*100])
def test_any_nonempty_wal_rejects_before_preparation(stored,tmp_path,content):
    m,run,_,_,calls,fixtures=stored;(run/'run.sqlite-wal').write_bytes(content);before=fixtures.tree(run)
    out=tmp_path/'must_not_exist'
    with pytest.raises(ValueError,match='exact zero-byte regular WAL'):m.prepare(out)
    assert not out.exists() and not calls and fixtures.tree(run)==before


@pytest.mark.parametrize('name',['run.sqlite-wal','run.sqlite-shm'])
def test_sidecar_symlinks_are_never_accepted(stored,tmp_path,name):
    m,run,_,_,calls,_=stored;target=tmp_path/'empty_target';target.write_bytes(b'')
    (run/name).symlink_to(target)
    with pytest.raises(ValueError,match='nonsymlink'):m.prepare(tmp_path/'no_symlink')
    assert not calls and target.read_bytes()==b''


@pytest.mark.parametrize('mutation',['created','removed','nonempty','mtime','shm','database'])
def test_frozen_sidecar_existence_stat_hash_and_database_cannot_drift(stored,tmp_path,mutation):
    m,run,_,_,calls,_=stored;wal=run/'run.sqlite-wal';shm=run/'run.sqlite-shm'
    if mutation!='created':wal.write_bytes(b'')
    shm.write_bytes(b'S'*32768);out=tmp_path/'prepared';m.prepare(out)
    if mutation=='created':wal.write_bytes(b'')
    elif mutation=='removed':wal.unlink()
    elif mutation=='nonempty':wal.write_bytes(b'x')
    elif mutation=='mtime':
        info=wal.stat();os.utime(wal,ns=(info.st_atime_ns,info.st_mtime_ns+1000000000))
    elif mutation=='shm':shm.write_bytes(b'T'*32768)
    else:(run/'run.sqlite').write_bytes(b'changed database bytes')
    with pytest.raises((ValueError,OSError)):m.validate_prepared(out)
    assert not calls and not (out/'started.json').exists()


def test_immutable_sqlite_connection_and_exit_guard_preserve_exact_empty_wal(stored,tmp_path,monkeypatch):
    m,run,_,_,_,fixtures=stored;(run/'run.sqlite-wal').write_bytes(b'');out=tmp_path/'prepared';m.prepare(out)
    frozen,access=m.validate_prepared(out);calls=[];original=m._N['sqlite3'].connect
    def connect(database_uri,**kwargs):
        calls.append((database_uri,kwargs));assert database_uri.endswith('?mode=ro&immutable=1') and kwargs=={'uri':True}
        return original(database_uri,**kwargs)
    monkeypatch.setattr(m._N['sqlite3'],'connect',connect)
    before=fixtures.tree(run);assert len(m._tasks(access))==2;access.guard()
    assert len(calls)==1 and fixtures.tree(run)==before
    info=(run/'run.sqlite-wal').stat();os.utime(run/'run.sqlite-wal',ns=(info.st_atime_ns,info.st_mtime_ns+1000000000))
    with pytest.raises(ValueError,match='metadata changed'):access.guard()


@pytest.mark.parametrize('problem',['stale_Q04','wrong_goal','resource_incomplete'])
def test_original_quality_and_actual_resource_rejections_are_unchanged(stored,tmp_path,monkeypatch,problem):
    m,run,_,contexts,_,_=stored;(run/'run.sqlite-wal').write_bytes(b'');out=tmp_path/'prepared';m.prepare(out)
    frozen,access=m.validate_prepared(out)
    if problem=='stale_Q04':
        path=contexts[0].revision_dir/'private/diagnosis.json';value=json.loads(path.read_text())
        value['assessments']['Q04']['evidence']=[];path.write_text(json.dumps(value))
    elif problem=='wrong_goal':(contexts[0].revision_dir/'private/goal.xlsx').write_bytes(b'wrong')
    else:monkeypatch.setitem(m._N,'validate_trial_observations',lambda *a,**k:{'passed':False,'complete':False})
    with pytest.raises(ValueError):m._recover(frozen,access)


def test_frozen_v1_bytes_and_all_review_export_logic_stay_identical():
    m=load('scripts/recover_linear_capital_scaled_P01_normal_evidence_revision2.py','_v2_ast_integrity')
    assert m.reference(m.FROZEN)['sha256']==m.FROZEN_SHA
    old=ast.parse(m.FROZEN.read_bytes());new=m.adapted_ast()
    for name in ('_review','_export','certify','strict_entry','_proposal'):
        left=next(n for n in old.body if isinstance(n,ast.FunctionDef) and n.name==name)
        right=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name==name)
        assert ast.dump(left,include_attributes=False)==ast.dump(right,include_attributes=False)
    for record in m.LINEAGE.values():assert m.reference(record['path'])==record
