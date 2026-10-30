"""Complete-value differential cases; no model or spreadsheet engine calls."""
from datetime import datetime, timedelta
from pathlib import Path
import random
from zipfile import ZipFile, ZIP_DEFLATED

from openpyxl import Workbook
from openpyxl.utils.datetime import CALENDAR_MAC_1904
import pytest

from sheets_factory.evaluation import standalone_verifier as original
from sheets_factory.evaluation import streaming_verifier as streaming


def books(directory, *, date_epoch=False):
    paths = []
    for name in ('input', 'goal', 'output'):
        book = Workbook()
        book.active.title = 'Financial Model'
        book.create_sheet('Contract')
        if date_epoch:
            book.epoch = CALENDAR_MAC_1904
        sheet = book.active
        sheet['A1'] = 'Forecast'
        sheet['B2'] = 100 if name == 'input' else 125
        sheet['D3'] = datetime(2024, 3, 31, 12, 34, 56)
        sheet['D4'] = timedelta(hours=30, seconds=1)
        sheet['D4'].number_format = '[h]:mm:ss'
        sheet['F3'] = '#DIV/0!'
        sheet['G3'] = True
        sheet['H3'] = ''
        sheet.merge_cells('A7:C7')
        book['Contract']['A1'] = 'Preserve me'
        path = directory / (name + '.xlsx')
        book.save(path)
        paths.append(path)
    return paths


def edit(path, coordinate, value, number_format=None):
    from openpyxl import load_workbook
    book = load_workbook(path)
    cell = book.active[coordinate]
    cell.value = value
    if number_format:
        cell.number_format = number_format
    book.save(path)
    book.close()


def parity(paths):
    actual = streaming.compare_files(*paths)
    assert actual == original.compare_files(*paths)
    return actual


@pytest.mark.parametrize('date_epoch', [False, True])
def test_correct_complete_change_set_and_dates(tmp_path, date_epoch):
    paths = books(tmp_path, date_epoch=date_epoch)
    result = parity(paths)
    assert result == {'reward': 1, 'reason': 'matched', 'expected_change_count': 1,
        'actual_change_count': 1, 'missing_changes': [], 'extra_changes': [], 'wrong_values': []}


@pytest.mark.parametrize('value,extra', [(100, None), (124, None), (125, 9), (124, False)])
def test_missed_wrong_and_extra_edits_remain_strict(tmp_path, value, extra):
    paths = books(tmp_path)
    edit(paths[2], 'B2', value)
    if extra is not None:
        edit(paths[2], 'Z25', extra)
    result = parity(paths)
    assert result['reward'] == 0
    assert result['expected_change_count'] == 1


@pytest.mark.parametrize('coordinate,value,number_format', [
    ('D3', 45382.52425925926, 'General'),
    ('B2', 125, 'yyyy-mm-dd'),
    ('G3', 1, 'General'),
    ('F3', '#N/A', 'General'),
    ('AA10', -0.004, '0.00'),
])
def test_reference_type_controls_dates_and_other_typed_values(tmp_path, coordinate, value, number_format):
    paths = books(tmp_path)
    edit(paths[2], coordinate, value, number_format)
    parity(paths)


def test_sheet_order_still_matters(tmp_path):
    from openpyxl import load_workbook
    paths = books(tmp_path)
    book = load_workbook(paths[2]); book.move_sheet('Contract', offset=-1)
    book.save(paths[2]); book.close()
    assert parity(paths)['reason'] == 'sheet_structure_mismatch'


def replace_dimension(path):
    import re
    with ZipFile(path) as source:
        content = {name: source.read(name) for name in source.namelist()}
    sheet = 'xl/worksheets/sheet1.xml'
    content[sheet] = re.sub(rb'<dimension ref="[^"]+"', b'<dimension ref="A1:A1"', content[sheet])
    with ZipFile(path, 'w', ZIP_DEFLATED) as destination:
        for name, data in content.items():
            destination.writestr(name, data)


def test_sparse_last_excel_cell_and_false_dimensions_do_not_truncate_or_expand(tmp_path):
    paths = books(tmp_path)
    edit(paths[2], 'XFD1048576', 'unexpected')
    for path in paths:
        replace_dimension(path)
    result = parity(paths)
    assert result['extra_changes'] == ['Financial Model!XFD1048576']
    assert result['reward'] == 0


def test_many_different_sparse_triplets_match_the_existing_semantics(tmp_path):
    from openpyxl import load_workbook
    generator = random.Random(6419)
    values = [None, '', False, True, -1.005, 0.004, 5.125, 'Policy', '#VALUE!', 0, 45123]
    for case in range(8):
        directory = tmp_path / str(case); directory.mkdir()
        paths = books(directory)
        for path in paths:
            book = load_workbook(path)
            for index in range(24):
                book.active.cell(row=20 + index * 7, column=1 + index % 8,
                                 value=generator.choice(values))
            book.save(path); book.close()
        parity(paths)


def test_reader_does_not_use_the_rectangular_row_iterator(tmp_path, monkeypatch):
    from openpyxl.worksheet._read_only import ReadOnlyWorksheet
    paths = books(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('The sparse grader must not pad rectangular rows')
    monkeypatch.setattr(ReadOnlyWorksheet, '_cells_by_row', forbidden)
    assert streaming.compare_files(*paths)['reward'] == 1


def test_existing_verifier_was_not_replaced_and_new_module_is_standalone(tmp_path):
    import runpy
    path = Path(streaming.__file__)
    standalone = runpy.run_path(str(path), run_name='standalone_sparse_grader')
    paths = books(tmp_path)
    assert standalone['compare_files'](*paths)['reward'] == 1
    assert standalone['normalize'](-1.005) == ('number', '-1.01')


def test_chart_sheet_has_no_cells_but_keeps_structural_order(tmp_path):
    from openpyxl import load_workbook
    from openpyxl.chart import BarChart, Reference
    paths = books(tmp_path)
    for path in paths:
        book = load_workbook(path)
        chart = BarChart()
        chart.add_data(Reference(book.active, min_col=2, min_row=2, max_row=2))
        book.create_chartsheet('Chart').add_chart(chart)
        book.save(path); book.close()
    assert parity(paths)['reward'] == 1


def test_sparse_sources_are_closed_if_value_validation_fails(tmp_path, monkeypatch):
    from openpyxl.worksheet._read_only import ReadOnlyWorksheet
    paths = books(tmp_path)
    sources = []
    get_source = ReadOnlyWorksheet._get_source
    def tracked(sheet):
        source = get_source(sheet); sources.append(source)
        return source
    def invalid(*args):
        raise ValueError('deliberate invalid value')
    monkeypatch.setattr(ReadOnlyWorksheet, '_get_source', tracked)
    monkeypatch.setattr(streaming, '_normalized_cell', invalid)
    with pytest.raises(ValueError, match='deliberate invalid value'):
        streaming.compare_files(*paths)
    assert sources and all(source.closed for source in sources)


def test_payload_in_a_merged_nonanchor_matches_normal_reader_semantics(tmp_path):
    paths = books(tmp_path)
    with ZipFile(paths[2]) as source:
        content = {name: source.read(name) for name in source.namelist()}
    worksheet = 'xl/worksheets/sheet1.xml'
    original_row = b'<row r="7"></row>'
    assert original_row in content[worksheet]
    content[worksheet] = content[worksheet].replace(original_row,
        b'<row r="7"><c r="B7" t="n"><v>777</v></c></row>')
    with ZipFile(paths[2], 'w', ZIP_DEFLATED) as destination:
        for name, data in content.items():
            destination.writestr(name, data)
    assert parity(paths)['reward'] == 1
