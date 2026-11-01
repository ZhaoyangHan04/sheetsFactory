import importlib.util
from pathlib import Path
import json
from openpyxl import Workbook
import pytest

ROOT=Path(__file__).resolve().parents[1]
def load():
 s=importlib.util.spec_from_file_location('_bounded_quality_review_test',ROOT/'scripts/run_ringfenced_bounded_quality_review.py')
 m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def test_public_projection_uses_actual_inputs_not_private_gold(tmp_path):
 m=load();book=Workbook();book.active.title='P01 - ContractNotes';book.active['A1']='Interest uses opening debt'
 s=book.create_sheet('P01 - Projects');s['A1']='Project';s['A2']='P001';s['B2']=100
 s=book.create_sheet('P01 - P001');s['A1']='Forecast';s['B2']='=A2*3'
 s=book.create_sheet('P01 - Portfolio');s['B3']=None
 s=book.create_sheet('Group reporting');s['A1']='Group forecast'
 path=tmp_path/'input.xlsx';book.save(path);book.close()
 before=m.ref(path);p=m.projection(path)
 assert m.ref(path)==before and p['sheet_count']==5 and p['visibility']=='public_input_definitions'
 assert p['sections']['P01 - ContractNotes']['full_policy_sheet'] is True
 assert p['sections']['P01 - P001']['cells'][1]['value']=='=A2*3'
 assert 'reference_cases' not in p
 assert p['sheet_categories']['candidate']==1


def test_policy_notes_are_never_silently_truncated(tmp_path):
 m=load();w=Workbook();w.active.title='P01 - ContractNotes';w.active['A401']='A required policy at row401'
 p=tmp_path/'long_policy.xlsx';w.save(p);w.close()
 with pytest.raises(ValueError,match='complete policy sheet'):m.projection(p)


def test_visibility_and_all_twelve_assignments_are_explicit():
 m=load()
 for mode in m._N['MODES']:
  a=m.prompt(mode,'public');b=m.prompt(mode,'reference')
  assert json.loads(a.split('assigned_check_ids=')[-1])==m._N['PUBLIC']
  assert json.loads(b.split('assigned_check_ids=')[-1])==m._N['PRIVATE']
  assert 'No reference, expected financial values' in a
  assert 'Q05/Q11/Q12' in b and 'unknown' in b
  assert 'not full tables' in a
 assert len(set(m._N['PUBLIC'])|set(m._N['PRIVATE']))==12


def test_recovery_is_a_new_identity_and_keeps_original_lifecycle():
 m=load()
 assert m.KIND!='actual_five_ringfenced_pairs_shared_quality_review_v1'
 assert m._N['PROFILE']==m.PROFILE
 assert m.KIND in m._N['run'].__code__.co_consts
 assert m._N['run'].__globals__['prompt'] is m.prompt
 assert 720 in m._N['run'].__code__.co_consts


def test_previous_frozen_source_change_stops_before_dispatch(monkeypatch):
 m=load();monkeypatch.setattr(m,'PRIOR_SHA','0'*64)
 with pytest.raises(ValueError,match='admission changed'):m.module()


def test_prior_preparation_must_match_actual_previous_dispatch(tmp_path,monkeypatch):
 m=load();prepared=tmp_path/'prepared.json';prepared.write_text('{"tasks":[]}')
 monkeypatch.setattr(m,'PRIOR_PREPARED',prepared)
 dispatch=tmp_path/'dispatch.json';dispatch.write_text(json.dumps({'prepared':m.ref(prepared)}))
 previous={'dispatch':m.ref(dispatch)}
 assert m.previous_material(previous)=={'tasks':[]}
 prepared.write_text('{"tasks":[{"task_id":"same-id-different-material"}]}')
 with pytest.raises(ValueError,match='dispatched material preparation changed'):m.previous_material(previous)
