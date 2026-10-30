from datetime import datetime
import importlib.util
from pathlib import Path
from zipfile import ZipFile

import openpyxl
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('_semantic_engineering_entry',ROOT/'scripts/prepare_semantic_graph_engineering.py')
entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)


def source(tmp_path):
    path=tmp_path/'source.xlsx';book=openpyxl.Workbook();s=book.active;s.title='Operating Operations'
    s['A1']='provided';s['A2']=True;s['A3']=datetime(2027,1,1)
    s['C4']=10;s['D4']=20;s['C3']='=SUM(C4:D4)'
    book.create_sheet('Provided Context')['C1']='=1+2'
    book.save(path);book.close();return path


def test_raw_injection_changes_only_declared_financial_definition_and_preserves_original(tmp_path):
    before=source(tmp_path);original=before.read_bytes();after=tmp_path/'new.xlsx'
    edits=[{'sheet':'Operating Operations','cell':'C3','before':'=SUM(C4:D4)','after':'=MAX(C4:D4)'}]
    proof=entry.inject_formulas(before,after,edits)
    assert proof['passed']and proof['all_before_after_assertions_verified']
    assert proof['all_outside_definitions_and_typed_literals_unchanged']
    assert proof['mutated_root_cached_values_removed']and proof['exact_formula_edit_set']
    assert before.read_bytes()==original
    with ZipFile(after)as archive:
        target=entry._paths(archive)['Operating Operations']
        tree=entry.ET.fromstring(archive.read(target))
        cell=next(c for c in tree.findall('.//m:sheetData/m:row/m:c',entry.NS)if c.get('r')=='C3')
        assert cell.find('m:v',entry.NS)is None
    with pytest.raises(FileExistsError):entry.inject_formulas(before,after,edits)


def test_before_assertion_and_duplicate_roots_fail_without_silently_repairing_source(tmp_path):
    before=source(tmp_path);original=before.read_bytes()
    edit={'sheet':'Operating Operations','cell':'C3','before':'=AVERAGE(C4:D4)','after':'=MAX(C4:D4)'}
    with pytest.raises(ValueError,match='Original formula assertion'):
        entry.inject_formulas(before,tmp_path/'bad.xlsx',[edit])
    assert before.read_bytes()==original and(tmp_path/'bad.xlsx').exists()
    with pytest.raises(ValueError,match='Duplicate'):
        entry.inject_formulas(before,tmp_path/'dup.xlsx',[edit,edit])
    assert not(tmp_path/'dup.xlsx').exists()
