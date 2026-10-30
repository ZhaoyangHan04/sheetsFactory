"""Preflight rejection must precede any model call or source construction."""
import importlib.util
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('_portfolio_probe_preparation',ROOT/'scripts/prepare_portfolio_probe.py')
API=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(API)


@pytest.mark.parametrize('status,passed,selected',[
    ('prepared_pending_real_LO',False,[]),
    ('financially_verified_planning_seed',False,[{}]),
    ('financially_verified_planning_seed',True,[]),
])
def test_unverified_or_missing_selected_source_cannot_enter_construction(tmp_path,monkeypatch,status,passed,selected):
    path=tmp_path/'manifest.json'
    path.write_text(json.dumps({'status':status,'financial_audit_passed':passed,'selected':selected}))
    monkeypatch.setattr(API,'AuditStore',lambda *args:pytest.fail('Preflight must reject before creating a run'))
    monkeypatch.setattr(API,'LibreOfficeEngine',lambda *args:pytest.fail('Unverified sources must not invoke LO'))
    with pytest.raises(ValueError,match='LO-verified'):API.prepare(path,tmp_path/'probe')
    assert not (tmp_path/'probe').exists()


def test_actual_selected_source_bytes_are_checked_before_creating_a_run(tmp_path,monkeypatch):
    book=tmp_path/'changed.xlsx';book.write_bytes(b'changed source')
    path=tmp_path/'manifest.json';path.write_text(json.dumps({'status':'financially_verified_planning_seed',
        'financial_audit_passed':True,'selected':[{'local_path':str(book),'sha256':'0'*64}]}))
    monkeypatch.setattr(API,'AuditStore',lambda *args:pytest.fail('Changed source must reject before creating a run'))
    with pytest.raises(ValueError,match='SHA mismatch'):API.prepare(path,tmp_path/'probe')


def test_probe_preparation_has_a_hard_no_model_boundary():
    with pytest.raises(RuntimeError,match='cannot invoke a model'):API.NoModelCalls().complete
