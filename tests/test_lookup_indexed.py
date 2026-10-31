"""Equivalent complete analyses with bounded worksheet lookup work."""
from copy import deepcopy
from datetime import date
import hashlib
from pathlib import Path
import socket
import subprocess
import zipfile
from xml.etree import ElementTree as E

import openpyxl
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.workbook.workbook import Workbook
import pytest

from sheets_factory.workbook import lookup_indexed as indexed


@pytest.fixture(autouse=True)
def no_services(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError('Reader tests must not start services')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)


def workbook(path, *, sheets=3, formulas=4):
    book = openpyxl.Workbook()
    book.active.title = 'Inputs'
    source = book['Inputs']
    for address, value in {'A1': 6, 'A2': 0.125, 'B1': True, 'B2': date(2026, 1, 1),
                           'C1': 'n/a (no comparative)', 'C2': 'Quarter 1'}.items():
        source[address] = value
    source['D1'] = '=1/0'
    report = book.create_sheet("Report's ! table")
    report['A1'] = '=Inputs!A1*2'
    report['A2'] = '=SUM(Inputs!A1:A2)'
    report['A3'] = '=IF(FALSE,Inputs!D1,Inputs!A1)'
    report['A4'] = '=Inputs!A1*Rate'
    book.defined_names.add(DefinedName('Rate', attr_text="'Inputs'!$A$2"))
    for number in range(5, formulas + 1):
        report.cell(number, 1, '=Inputs!A1+' + str(number))
    for number in range(sheets - 2):
        extra = book.create_sheet('Other ' + str(number))
        extra['A1'] = 'Protected unrelated label ' + str(number)
    book.save(path)
    book.close()
    # Toy-only physical caches, including a real error, for reader equivalence.
    ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path) as source_zip:
        members = {name: source_zip.read(name) for name in source_zip.namelist()}
    for name, data in list(members.items()):
        if not name.startswith('xl/worksheets/sheet') or not name.endswith('.xml'):
            continue
        root = E.fromstring(data)
        for cell in root.findall('.//s:c', ns):
            if cell.find('s:f', ns) is None:
                continue
            value = cell.find('s:v', ns)
            if value is None:
                value = E.SubElement(cell, '{' + ns['s'] + '}v')
            if name == 'xl/worksheets/sheet1.xml':
                cell.set('t', 'e')
                value.text = '#DIV/0!'
            else:
                value.text = {'A1': '12', 'A2': '6.125', 'A3': '6', 'A4': '0.75'}.get(cell.attrib['r'], '20')
        members[name] = E.tostring(root)
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as target:
        for name, data in members.items():
            target.writestr(name, data)
    return path


def test_index_preserves_objects_order_charts_and_nonstring_lookup_behavior():
    book = openpyxl.Workbook()
    book.active.title = 'First'
    chart = book.create_chartsheet('Chart')
    book.create_sheet('Last')
    view = indexed.WorkbookLookupIndex(book)
    assert view.sheetnames == book.sheetnames
    assert book.sheetnames == view.sheetnames
    assert view.sheetnames[:] == book.sheetnames
    assert list(view.sheetnames) == book.sheetnames
    assert view['First'] is book['First']
    assert view['Chart'] is chart
    assert view.defined_names is book.defined_names
    for name in ('First', 'first', 'missing', [], None):
        assert (name in view.sheetnames) == (name in book.sheetnames)
    for name in ('missing', None, []):
        with pytest.raises(Exception) as original:
            book[name]
        with pytest.raises(type(original.value)) as actual:
            view[name]
        assert str(actual.value) == str(original.value)
    # Malformed duplicate titles retain the original first-match search order.
    chart._WorkbookChild__title = 'First'
    other = indexed.WorkbookLookupIndex(book)
    assert other['First'] is book['First'] is book.worksheets[0]


def test_typed_required_values_and_complete_ancestor_census_are_identical(tmp_path):
    path = workbook(tmp_path / 'typed.xlsx')
    before = path.read_bytes()
    labels = ["Report's ! table!A1", "Report's ! table!A2", "Report's ! table!A3",
              "Report's ! table!A4", 'Inputs!B1', 'Inputs!B2', 'Inputs!C1', 'Inputs!Z99']
    assert indexed._required_values(path, labels) == indexed.original_probe._required_values(path, labels)
    expected = indexed.original_probe._full_closure_candidates(path, labels, [], 100)
    assert indexed._full_closure_candidates(path, labels, [], 100) == expected
    assert expected[0] == [{'sheet': 'Inputs', 'cell': 'D1', 'cached_error': '#DIV/0!', 'formula': '=1/0'}]
    assert path.read_bytes() == before


@pytest.mark.parametrize('label', ['missing!A1', 'Inputs!A0', 'Inputs!$A$1', 'Inputs!A1:B2'])
def test_invalid_required_labels_retain_the_original_rejection(tmp_path, label):
    path = workbook(tmp_path / 'bad-label.xlsx')
    with pytest.raises(ValueError) as before:
        indexed.original_probe._required_values(path, [label])
    with pytest.raises(ValueError) as after:
        indexed._required_values(path, [label])
    assert str(before.value) == str(after.value)


@pytest.mark.parametrize('kind', ['closure_limit', 'volatile', 'unknown_sheet', 'unresolved_name', 'stale_candidate'])
def test_complete_closure_blockers_are_not_relaxed(tmp_path, kind):
    path = workbook(tmp_path / 'closure.xlsx')
    candidates = []
    limit = 100
    if kind == 'closure_limit':
        limit = 1
    elif kind == 'stale_candidate':
        candidates = [{'sheet': 'Inputs', 'cell': 'A1'}]
    else:
        book = openpyxl.load_workbook(path)
        book["Report's ! table"]['A1'] = {
            'volatile': '=NOW()', 'unknown_sheet': '=missing!A1',
            'unresolved_name': '=UnknownPolicy',
        }[kind]
        book.save(path)
        book.close()
    args = (path, ["Report's ! table!A1"], candidates, limit)
    with pytest.raises(ValueError) as before:
        indexed.original_probe._full_closure_candidates(*args)
    with pytest.raises(ValueError) as after:
        indexed._full_closure_candidates(*args)
    assert str(before.value) == str(after.value)


def test_complete_profile_values_labels_names_and_dependencies_match(tmp_path):
    path = workbook(tmp_path / 'profile.xlsx', formulas=35)
    original = indexed.original_profile.profile_workbook(path, max_cells=1000)
    actual = indexed.profile_workbook(path, max_cells=1000)
    assert actual == original
    assert actual['truncated'] is False
    assert actual['defined_names']['Rate'] == "'Inputs'!$A$2"
    assert actual['errors'] == [{'sheet': 'Inputs', 'cell': 'D1', 'value': '#DIV/0!'}]
    # The same finite limit still reports truncation instead of hiding it.
    assert indexed.profile_workbook(path, max_cells=8) == indexed.original_profile.profile_workbook(path, max_cells=8)


def test_both_original_probe_limits_and_full_receipt_semantics_remain(tmp_path):
    path = workbook(tmp_path / 'probe.xlsx')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    class NoEngine:
        def recalculate(self, *a, **k):
            raise AssertionError('No-error closure requires no native calculation')
    for label, original, fast, maximum in (
        ('ordinary', indexed.original_probe.probe_native_errors, indexed.probe_native_errors, 100),
        ('large', indexed.original_large_probe.probe_native_errors, indexed.probe_native_errors_large, 600000),
    ):
        args = dict(goal=path, required_delta=["Report's ! table!A1"], candidates=[],
                    engine=NoEngine(), source_sha256=digest, plan={'test': True}, revision=0,
                    immutable_files={'source': path}, max_dependency_cells=maximum)
        old = original(**args, directory=tmp_path / (label + '-old'))
        new = fast(**args, directory=tmp_path / (label + '-new'))
        assert old['state'] == new['state'] == 'not_applicable'
        for value in (old, new):
            value.pop('duration_ms')
        assert old == new
        assert new['full_dependency_closure_cells'] == 2
        assert new['immutable_unchanged'] is True
        assert new['business_correctness_certificate'] is False


def test_worksheet_search_count_no_longer_grows_per_profile_formula(tmp_path, monkeypatch):
    path = workbook(tmp_path / 'many-sheets.xlsx', sheets=80, formulas=120)
    original_getitem = Workbook.__getitem__
    counter = [0]
    def counted(self, key):
        counter[0] += 1
        return original_getitem(self, key)
    monkeypatch.setattr(Workbook, '__getitem__', counted)
    original = indexed.original_profile.profile_workbook(path, max_cells=10000)
    old_count = counter[0]
    counter[0] = 0
    actual = indexed.profile_workbook(path, max_cells=10000)
    assert actual == original
    assert old_count >= 120
    assert counter[0] < old_count // 4


def test_original_function_objects_globals_and_dependency_guards_stay_intact(monkeypatch):
    original = indexed.original_probe._full_closure_candidates
    globals_before = dict(original.__globals__)
    indexed.verify_dependencies()
    assert indexed.original_probe._full_closure_candidates is original
    assert original.__globals__ == globals_before
    key = next(iter(indexed.PINS))
    monkeypatch.setitem(indexed.PINS, key, '0' * 64)
    with pytest.raises(ValueError, match='Frozen complete-analysis dependency'):
        indexed.verify_dependencies()
