from __future__ import annotations
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def entry():
    path = ROOT/'scripts/prepare_operating_reports_200_development_revision2.py'
    spec = importlib.util.spec_from_file_location('_test_fixed200_first_development_revision2',path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

def test_new_admission_driver_is_frozen_and_both_recipes_remain_bound(entry):
    assert entry.KIND == 'prequality_fixed_operating_reports_200_development_pair_v6_revision2'
    assert entry._VALIDATOR.name == 'validate_operating_reports_200_tasks_revision2.py'
    assert hashlib.sha256(entry._VALIDATOR.read_bytes()).hexdigest() == entry._NEW_VALIDATOR_SHA
    recipes = entry.recipes()
    assert str(entry._FROZEN_DEV) in recipes
    assert str(entry._VALIDATOR) in recipes
    assert recipes[str(entry._VALIDATOR)]['sha256'] == entry._NEW_VALIDATOR_SHA
    assert entry._ns['recipes'] is entry.recipes

def test_modified_validator_cannot_enter_shared_lifecycle(entry,monkeypatch):
    monkeypatch.setattr(entry,'_NEW_VALIDATOR_SHA','0'*64)
    with pytest.raises(ValueError,match='validator changed'):
        entry._revision_ast()

def test_modified_original_development_lifecycle_cannot_be_rebound(entry,monkeypatch):
    monkeypatch.setattr(entry,'_FROZEN_SHA','0'*64)
    with pytest.raises(ValueError,match='first-attempt lifecycle changed'):
        entry._revision_ast()

def test_original_task_terminal_cannot_be_admitted_as_repaired_task(entry,monkeypatch):
    observed = []
    original = {'kind':'complete_fixed_operating_reports_200_task_engineering','passed':True,
                'actual_LO_calls_started':8,'actual_LO_calls_completed':8,'version':1,
                'qualified':False,'normal_all12_QA_passed':False}
    monkeypatch.setitem(entry._ns,'validation_driver',lambda:SimpleNamespace(validate_completed=lambda value:original))
    monkeypatch.setitem(entry._ns,'read',lambda value:observed.append(value))
    with pytest.raises(ValueError,match='genuine complete'):
        entry._checked_engineering('UNVERIFIED_UNIT_FIXTURE_ONLY')
    assert observed == []

def test_only_IO_paths_are_appended_to_original_public_brief(entry,tmp_path):
    path = tmp_path/'brief.md'; path.write_bytes(b'Complete the portfolio forecasts.\n')
    candidate = {'views':{'financial_modeling':{'instruction':entry.ref(path)}}}
    original,rendered = entry._instruction(candidate,'financial_modeling')
    assert original == path.read_bytes()
    assert rendered == original+b'\n---\nFile paths: read /app/input.xlsx and save the completed workbook to /app/output.xlsx.\n'
    assert b'goal' not in rendered and b'fault_design' not in rendered
