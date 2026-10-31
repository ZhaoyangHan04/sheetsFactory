"""Focused pure/mocked tests for native comparison and the three-call gate."""
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import pytest
from openpyxl import Workbook
from openpyxl.utils.datetime import CALENDAR_MAC_1904


@pytest.fixture
def v():
    path=Path(__file__).resolve().parents[1]/"scripts/validate_heterogeneous_native_review_pack.py"
    spec=importlib.util.spec_from_file_location("review_pack_native_validation_test",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def book(tmp_path,name,value=1.234567,*,epoch=False,date_serial=None,formula=None,errors=False):
    wb=Workbook();ws=wb.active;ws.title="Business"
    if epoch:wb.epoch=CALENDAR_MAC_1904
    ws["A1"]=value;ws["B1"]="Retained financial text";ws["C1"]=True
    if date_serial is not None:ws["D1"]=date_serial;ws["D1"].number_format="mmm-yy"
    if formula is not None:ws["E1"]="="+formula
    if errors:
        for i in range(1,13):ws.cell(i,6,"#DIV/0!")
    path=tmp_path/(name+".xlsx");wb.save(path)
    if formula is not None:
        def cache(parts):
            root=ET.fromstring(parts["xl/worksheets/sheet1.xml"])
            cell=next(c for c in root.findall('.//{*}c') if c.get('r')=='E1');cell.find('{*}v').text='1.23'
            parts["xl/worksheets/sheet1.xml"]=ET.tostring(root)
        patch(path,cache)
    return path


def patch(path,callback):
    with ZipFile(path) as z:parts={n:z.read(n) for n in z.namelist()}
    callback(parts)
    with ZipFile(path,"w",ZIP_DEFLATED) as z:
        for n,b in parts.items():z.writestr(n,b)


def test_raw_float_noise_is_retained_and_primary_is_not_called_exact(v,tmp_path):
    a=v.snapshot(book(tmp_path,"a",1.23000000000001));b=v.snapshot(book(tmp_path,"b",1.23000000000002))
    result=v.compare_snapshots(a,b)
    assert result["passed"] and result["raw_numeric_difference_count"]==1
    assert not result["raw_numeric_equality"] and not result["exact_numeric_equivalence_claimed"]
    assert result["raw_numeric_differences"][0]["exact_decimal_difference"]=="1E-14"


@pytest.mark.parametrize("a,b",[(1.2349,1.235),(-1.2349,-1.235),(0.0049,0.005)])
def test_two_decimal_half_up_boundary_changes_fail(v,tmp_path,a,b):
    report=v.compare_snapshots(v.snapshot(book(tmp_path,"a",a)),v.snapshot(book(tmp_path,"b",b)))
    assert not report["passed"] and report["primary_value_mismatch_count"]==1


def test_negative_rounded_zero_matches_taskbook_empty_contract(v,tmp_path):
    a=v.snapshot(book(tmp_path,"a",-0.0001));b=v.snapshot(book(tmp_path,"b",0.0001))
    assert v.compare_snapshots(a,b)["passed"]
    assert a["cells"]["Business"]["A1"]["primary"]=={"type":"number","value":"0.00"}
    assert "Missing cell" in v.CONTRACT["empty_primary"]


def test_date_epochs_compare_same_calendar_and_reject_one_day_change(v,tmp_path):
    a=v.snapshot(book(tmp_path,"a",epoch=True,date_serial=44592))
    b=v.snapshot(book(tmp_path,"b",date_serial=46054));c=v.snapshot(book(tmp_path,"c",date_serial=46055))
    assert v.compare_snapshots(a,b)["passed"] and not v.compare_snapshots(a,c)["passed"]
    assert a["cells"]["Business"]["D1"]["primary"]=={"type":"datetime","value":"2026-02-01T00:00:00.000"}


@pytest.mark.parametrize("address,newtype,newvalue",[("B1","str","Changed business text"),("C1","n","1"),("F1","e","#VALUE!")])
def test_text_boolean_and_error_semantics_are_exact(v,tmp_path,address,newtype,newvalue):
    a=book(tmp_path,"a",errors=True);b=tmp_path/"b.xlsx";shutil.copyfile(a,b)
    def change(parts):
        root=ET.fromstring(parts["xl/worksheets/sheet1.xml"]);c=next(x for x in root.findall('.//{*}c') if x.get('r')==address)
        c.set('t',newtype)
        for child in list(c):c.remove(child)
        ET.SubElement(c,'{'+v.merge.S+'}v').text=newvalue;parts["xl/worksheets/sheet1.xml"]=ET.tostring(root)
    patch(b,change)
    result=v.compare_snapshots(v.snapshot(a),v.snapshot(b))
    assert not result["passed"] and result["primary_value_mismatch_count"]==1


def test_all_twelve_errors_are_checked_and_unexpected_new_error_fails(v,tmp_path):
    a=book(tmp_path,"a",errors=True);b=tmp_path/"b.xlsx";shutil.copyfile(a,b)
    same=v.compare_snapshots(v.snapshot(a),v.snapshot(b));assert same["passed"] and len(same["expected_errors"])==12
    def change(parts):
        root=ET.fromstring(parts["xl/worksheets/sheet1.xml"]);c=next(x for x in root.findall('.//{*}c') if x.get('r')=='A1');c.set('t','e');c.find('{*}v').text='#DIV/0!';parts["xl/worksheets/sheet1.xml"]=ET.tostring(root)
    patch(b,change);report=v.compare_snapshots(v.snapshot(a),v.snapshot(b))
    assert not report["passed"] and len(report["actual_errors"])==13 and not report["error_coordinates_and_codes_unchanged"]


def test_formula_identity_is_independent_of_equal_cached_value(v,tmp_path):
    a=v.snapshot(book(tmp_path,"a",formula="SUM(A1:A1)"));b=v.snapshot(book(tmp_path,"b",formula="SUM(A1:A2)"))
    result=v.compare_snapshots(a,b)
    assert not result["passed"] and result["primary_value_mismatch_count"]==0 and result["formula_or_literal_identity_mismatch_count"]==1


def test_formula_quoting_and_case_are_the_only_accepted_normalization(v,tmp_path):
    a=v.snapshot(book(tmp_path,"a",formula="SUM(Business!A1)"));b=v.snapshot(book(tmp_path,"b",formula="sum('Business'!A1)"))
    assert v.compare_snapshots(a,b)["passed"]
    b["cells"]["Business"]["E1"]["is_formula"]=False;b["cells"]["Business"]["E1"]["formula"]=None
    assert not v.compare_snapshots(a,b)["passed"]


@pytest.mark.parametrize("failure_at,expected_calls",[(1,1),(2,2),(3,3),(None,3)])
def test_prior_full_pass_gates_every_subsequent_call(v,tmp_path,failure_at,expected_calls):
    good=book(tmp_path,"good",errors=True);bad=book(tmp_path,"bad",999,errors=True)
    expectation=v.snapshot(good);out=tmp_path/"attempt";out.mkdir();calls=[]
    def perform(index,source,destination):
        calls.append((index,source,destination));shutil.copyfile(bad if failure_at==index else good,destination)
    frozen={"emission_workbook":{"path":str(good)}}
    if failure_at:
        with pytest.raises(ValueError,match="no downstream"):
            v.comparison_sequence(frozen,expectation,expectation,out,perform)
    else:
        reports=v.comparison_sequence(frozen,expectation,expectation,out,perform)
        assert len(reports)==3 and all(v.read(r)["passed"] for r in reports)
    assert len(calls)==expected_calls
    if len(calls)>1:assert calls[1][1]==calls[0][2]
    assert (out/("pass"+str(expected_calls)+"_full_equivalence.json")).exists()


def test_entire_sparse_union_rejects_new_values(v,tmp_path):
    a=v.snapshot(book(tmp_path,"a"));b=json.loads(json.dumps(a));b["cells"]["Business"]["XFD1048576"]={"primary":{"type":"string","value":"unexpected"},"formula":None,"is_formula":False,"raw_numeric_text":None}
    report=v.compare_snapshots(a,b)
    assert not report["passed"] and report["full_sparse_union_cells_checked"]==4


def test_unknown_array_native_output_is_not_silently_accepted(v,tmp_path):
    path=book(tmp_path,"array",formula="A1")
    def change(parts):
        root=ET.fromstring(parts["xl/worksheets/sheet1.xml"]);root.find('.//{*}f').set('t','array');parts["xl/worksheets/sheet1.xml"]=ET.tostring(root)
    patch(path,change)
    with pytest.raises(ValueError,match="shared/array"):
        v.snapshot(path)


def test_cleanup_proof_requires_exact_cid_absence_and_reachable_pinned_daemon(v,monkeypatch):
    cid="d"*64;commands=[]
    def run(command,**kwargs):
        commands.append(command)
        if command[:3]==["docker","image","inspect"]:return SimpleNamespace(returncode=0,stdout=v.IMAGE+"\n",stderr="")
        return SimpleNamespace(returncode=1,stdout="",stderr="Error: No such object: "+cid)
    monkeypatch.setattr(v.subprocess,"run",run)
    assert v.owned_cleanup(cid)["removed_and_absent_with_daemon_reachable"]
    assert len(commands)==3 and all(cid in c or v.IMAGE in c for c in commands)
    with pytest.raises(ValueError,match="Full owned CID"):
        v.owned_cleanup("short")


def test_daemon_failure_does_not_count_as_absence(v,monkeypatch):
    cid="e"*64
    monkeypatch.setattr(v.subprocess,"run",lambda *a,**kw:SimpleNamespace(returncode=1,stdout="",stderr="Cannot connect to the Docker daemon"))
    assert not v.owned_cleanup(cid)["removed_and_absent_with_daemon_reachable"]


def test_prior_started_record_prevents_any_engine_or_ui_call(v,tmp_path,monkeypatch):
    out=tmp_path/"prepared";out.mkdir();(out/"execution_started.json").write_text('{}');(out/"prospective.json").write_text('{}')
    events=[]
    class Lease:
        def __init__(self,*a):pass
        def acquire(self):events.append("acquire");return self
        def release(self):events.append("release")
    monkeypatch.setattr(v,"ProducerLease",Lease)
    monkeypatch.setattr(v,"validate_prepared",lambda *a:pytest.fail("cold validation must not follow prior start"))
    monkeypatch.setattr(v,"ObservedEngine",lambda *a,**kw:pytest.fail("no native engine"))
    monkeypatch.setattr(v,"DashboardServer",lambda *a,**kw:pytest.fail("no UI"))
    with pytest.raises(RuntimeError,match="preserve"):
        v.execute_prepared(out)
    terminals=list((out/"private/attempts").glob('*/terminal.json'));assert len(terminals)==1
    terminal=json.loads(terminals[0].read_text());assert terminal["LO_calls_started"]==0 and terminal["outer_retries"]==0
    assert events==["acquire","release"]
