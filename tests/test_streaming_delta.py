"""Exact old/new construction-delta parity, including every changed address."""
from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
import random

import openpyxl
from openpyxl.utils.datetime import CALENDAR_MAC_1904
import pytest

from sheets_factory.evaluation import streaming_delta as streaming
from sheets_factory.workbook.compare import compare_workbooks as legacy

_spec = importlib.util.spec_from_file_location('_stream_delta_workbook_fixtures', Path(__file__).with_name('test_streaming_verifier.py'))
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)


def parity(paths):
    expected, actual = legacy(*paths), streaming.compare_workbooks(*paths)
    assert actual == expected
    return actual


@pytest.mark.parametrize('epoch', (False, True))
def test_full_legacy_schema_dates_errors_and_required_coordinate_lists(tmp_path, epoch):
    paths = fixture.books(tmp_path, date_epoch=epoch)
    result = parity(paths)
    assert result['reward'] == 1
    assert result['expected_changes'] == result['actual_changes'] == ['Financial Model!B2']


@pytest.mark.parametrize('candidate,extra', ((100, None), (124, None), (125, 0), (124, False)))
def test_missed_extra_and_wrong_are_complete_and_strict(tmp_path, candidate, extra):
    paths = fixture.books(tmp_path)
    fixture.edit(paths[2], 'B2', candidate)
    if extra is not None:
        fixture.edit(paths[2], 'Z25', extra)
    assert parity(paths)['reward'] == 0


def test_input_type_wins_even_when_goal_type_differs(tmp_path):
    paths = fixture.books(tmp_path)
    fixture.edit(paths[0], 'B2', 45382)
    fixture.edit(paths[1], 'B2', datetime(2024, 3, 31), 'yyyy-mm-dd')
    fixture.edit(paths[2], 'B2', 45382)
    result = parity(paths)
    assert result['expected_change_count'] == result['actual_change_count'] == 0
    assert result['reward'] == 1


def test_different_workbook_epochs_use_trusted_duration_and_calendar_hints(tmp_path):
    paths = fixture.books(tmp_path)
    book = openpyxl.load_workbook(paths[2])
    book.epoch = CALENDAR_MAC_1904
    book.save(paths[2]); book.close()
    assert parity(paths)['reward'] == 1


def test_missing_and_additional_sheets_still_return_every_delta(tmp_path):
    paths = fixture.books(tmp_path)
    book = openpyxl.load_workbook(paths[2])
    del book['Contract']
    book.create_sheet('New Sheet')['A4'] = 7
    book.save(paths[2]); book.close()
    result = parity(paths)
    assert result['structure_ok'] is False
    assert 'New Sheet!A4' in result['extra_changes']
    assert 'Contract!A1' in result['extra_changes']


def test_sparse_last_cell_ignores_misleading_dimensions(tmp_path, monkeypatch):
    from openpyxl.worksheet._read_only import ReadOnlyWorksheet
    paths = fixture.books(tmp_path)
    fixture.edit(paths[2], 'XFD1048576', 'unexpected')
    for path in paths:
        fixture.replace_dimension(path)
    def forbidden(*args, **kwargs):
        raise AssertionError('A complete sparse comparison must not expand a rectangle')
    monkeypatch.setattr(ReadOnlyWorksheet, '_cells_by_row', forbidden)
    result = parity(paths)
    assert result['extra_changes'] == ['Financial Model!XFD1048576']


def test_random_sparse_typed_triplets_have_exact_dictionary_parity(tmp_path):
    generator = random.Random(831991)
    values = [None, '', False, True, -1.005, 0.004, 5.125, 'Policy', '#VALUE!', 0, 45123,
              datetime(2024, 3, 31), timedelta(days=2)]
    for index in range(10):
        directory = tmp_path / str(index); directory.mkdir()
        paths = fixture.books(directory)
        for path in paths:
            book = openpyxl.load_workbook(path)
            for row in range(24):
                book.active.cell(20 + row * 7, 1 + row % 8, generator.choice(values))
            book.save(path); book.close()
        parity(paths)


def test_parse_errors_are_explicit_and_all_open_streams_close(tmp_path, monkeypatch):
    from openpyxl.worksheet._read_only import ReadOnlyWorksheet
    paths = fixture.books(tmp_path)
    opened, original = [], ReadOnlyWorksheet._get_source
    def tracked(sheet):
        stream = original(sheet); opened.append(stream); return stream
    def invalid(*args):
        raise ValueError('deliberate invalid value')
    monkeypatch.setattr(ReadOnlyWorksheet, '_get_source', tracked)
    monkeypatch.setattr(streaming, '_normalize', invalid)
    result = streaming.compare_workbooks(*paths)
    assert result == {'reward': 0, 'error': 'ValueError', 'detail': 'deliberate invalid value'}
    assert opened and all(stream.closed for stream in opened)


def test_chart_structure_and_merged_nonanchor_use_normal_reader_semantics(tmp_path):
    from zipfile import ZipFile, ZIP_DEFLATED
    from openpyxl.chart import BarChart, Reference
    paths = fixture.books(tmp_path)
    for path in paths:
        book = openpyxl.load_workbook(path)
        chart = BarChart()
        chart.add_data(Reference(book.active, min_col=2, min_row=2, max_row=2))
        book.create_chartsheet('Chart').add_chart(chart)
        book.save(path); book.close()
    with ZipFile(paths[2]) as source:
        content = {name: source.read(name) for name in source.namelist()}
    key = 'xl/worksheets/sheet1.xml'
    content[key] = content[key].replace(b'<row r="7"></row>',
        b'<row r="7"><c r="B7" t="n"><v>777</v></c></row>')
    with ZipFile(paths[2], 'w', ZIP_DEFLATED) as destination:
        for name, value in content.items():
            destination.writestr(name, value)
    assert parity(paths)['reward'] == 1
