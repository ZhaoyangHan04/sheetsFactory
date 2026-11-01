"""All original whole-view tests, plus exact private R3-provider boundaries."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'tests/test_ringfenced_pair_tasks.py'
spec=importlib.util.spec_from_file_location('_frozen_original_pair_task_tests',path)
original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
toy=original.toy;material=original.material
for name,value in vars(original).items():
    if name.startswith('test_'):globals()[name]=value


@pytest.fixture(scope='module')
def entry():
    path=ROOT/'scripts/validate_ringfenced_pair_tasks_revision2.py'
    spec=importlib.util.spec_from_file_location('_test_R3_pair_tasks',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_exact_R3_source_and_explicit_new_task_kinds(entry):
    assert entry.SOURCE.name=='run_ringfenced_pair_session_revision3.py'
    assert entry.SOURCE_SHA=='b3cc7cc25c667a997614f81c3411810e2bea30f8a5d1cd346f9e8d92e892d3af'
    assert entry.SOURCE_KIND==entry.session.TERMINAL_KIND=='completed_two_ringfenced_pair_source_same_process_session_revision3'
    assert entry.KIND.endswith('_revision2') and entry.TERMINAL_KIND.endswith('_revision2')
    assert entry._P['SOURCE_KIND']==entry.SOURCE_KIND
    assert entry.previous.SOURCE_KIND=='completed_two_ringfenced_pair_source_same_process_session'


def test_old_opaque_source_and_globals_are_not_mutated(entry):
    assert entry.source is not entry.previous.source
    assert entry._P['source'] is entry._N['source'] is entry.source
    for name in ('prepare','validate_prepared','verify_definitions','verify_input_caches','_genuine'):
        assert getattr(entry,name).__code__ is getattr(entry.previous,name).__code__
        assert getattr(entry,name).__globals__ is entry._P
        assert getattr(entry,name).__globals__ is not vars(entry.previous)
    for name in ('execute_prepared','validate_completed'):
        assert getattr(entry,name).__code__ is getattr(entry.previous,name).__code__
        assert getattr(entry,name).__globals__ is entry._N
        assert getattr(entry,name).__globals__ is not entry.previous._N


def test_recipe_binds_both_entries_and_only_new_source_provider(entry):
    value=entry.recipes()
    assert value[str(entry.FROZEN)]['sha256']==entry.FROZEN_SHA
    assert value[str(entry.SOURCE)]['sha256']==entry.SOURCE_SHA
    assert str(Path(entry.__file__).resolve()) in value
    assert value==entry._N['recipes']()
    assert entry.previous.recipes()!=value


def test_legacy_source_PASS_cannot_enter_revision2(entry,tmp_path,monkeypatch):
    ref=entry.write(tmp_path/'old_PASS.json',{'kind':entry.previous.SOURCE_KIND,'version':1,'passed':True,
        'actual_calls_started':3,'actual_calls_completed':3,'LO_calls':3})
    monkeypatch.setattr(entry.session,'validate_completed',lambda *a,**k:pytest.fail('legacy source reached actual provider'))
    with pytest.raises(ValueError,match='genuine completed'):entry._genuine(ref)


def test_corrupted_new_source_code_is_rejected_without_fallback(entry,tmp_path):
    path=tmp_path/'provider.py';path.write_text("raise RuntimeError('must never import')\n")
    with pytest.raises(ValueError,match='provider changed'):entry._load(path,'0'*64,'_never_imported')
