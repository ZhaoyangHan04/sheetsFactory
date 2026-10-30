"""Complete profile parity and bounded preceding-label lookups; no LO/models."""
from datetime import date, datetime
from pathlib import Path
import json
import time

from openpyxl import Workbook
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.formula import ArrayFormula
import pytest

from sheets_factory.workbook import profile as original
from sheets_factory.workbook import profile_indexed as indexed


def fixture_book(path):
    book = Workbook()
    sheet = book.active; sheet.title = 'Forecast North'
    for row in range(1, 9):
        for column in range(1, 9):
            if (row + column) % 3 == 0:
                sheet.cell(row, column, f'Label {row}/{column}')
            else:
                sheet.cell(row, column, row * 10 + column)
    sheet['C2'] = datetime(2024, 3, 31, 12, 15)
    sheet['C4'] = date(2025, 3, 31)
    sheet['D4'] = False
    sheet['B9'] = '#DIV/0!'
    sheet['I2'] = '=SUM(B2:C3)'
    sheet['I3'] = '=RevenueInputs+1'
    sheet['I4'] = '=OFFSET(B2,1,0)'
    sheet['I5'] = "='[external.xlsx]Other'!A1"
    sheet['I6'] = '=SUM('
    sheet['K2'] = ArrayFormula(ref='K2:K3', text='=SUM(B2:B3)')
    sheet.merge_cells('A11:D11'); sheet['A11'] = 'Merged label'
    sheet['XFD20'] = 'Distant label'
    book.defined_names.add(DefinedName('RevenueInputs', attr_text="'Forecast North'!$B$2:$C$3"))
    other = book.create_sheet('Contract')
    other.sheet_state = 'hidden'
    other['A1'] = 'Terms'; other['B2'] = "='Forecast North'!B2"
    book.create_sheet('Empty')
    book.save(path); book.close()
    return path


@pytest.mark.parametrize('max_cells', [0, 1, 5, 50, 10000])
@pytest.mark.parametrize('reference_limit', [1, 32])
def test_complete_profile_fields_match_original(tmp_path, max_cells, reference_limit):
    path = fixture_book(tmp_path / 'mixed.xlsx')
    expected = original.profile_workbook(path, max_cells, per_formula_reference_cells=reference_limit)
    actual = indexed.profile_workbook(path, max_cells, per_formula_reference_cells=reference_limit)
    assert actual == expected
    assert set(actual) == set(expected)
    assert json.loads(json.dumps(actual)) == json.loads(json.dumps(expected))


def test_row_and_column_labels_select_last_three_strict_predecessors(tmp_path):
    book = Workbook(); sheet = book.active
    for coordinate, value in {'A1': 'first', 'C1': 'second', 'E1': 'third', 'G1': 'fourth',
                              'I1': 'fifth', 'J1': 10, 'A2': 'row two', 'A3': date(2024, 1, 1),
                              'A4': True, 'A5': '=1', 'A6': 'row six', 'A7': 70}.items():
        sheet[coordinate] = value
    path = tmp_path / 'labels.xlsx'; book.save(path); book.close()
    actual = indexed.profile_workbook(path)
    assert actual == original.profile_workbook(path)
    cells = {cell['cell']: cell for cell in actual['sheets'][0]['cells']}
    assert [label['cell'] for label in cells['J1']['row_labels']] == ['E1', 'G1', 'I1']
    assert [label['cell'] for label in cells['I1']['row_labels']] == ['C1', 'E1', 'G1']
    assert [label['cell'] for label in cells['A7']['column_labels']] == ['A2', 'A3', 'A6']
    assert cells['A1']['row_labels'] == cells['A1']['column_labels'] == []


def test_lookup_only_reads_a_bounded_cell_slice():
    class Cells:
        def __getitem__(self, key):
            assert isinstance(key, slice)
            assert key.stop - key.start <= 3
            return tuple(range(key.start, key.stop))
    positions = tuple(range(1, 34001))
    assert indexed._preceding((positions, Cells()), 34001) == (33997, 33998, 33999)
    assert indexed._preceding((positions, Cells()), 3) == (0, 1)
    assert indexed._preceding((positions, Cells()), 1) == ()


def test_34000_label_rows_have_complete_independently_checked_predecessors(tmp_path):
    count = 34000
    book = Workbook(); sheet = book.active; sheet.title = 'Exact Arithmetic'
    for row in range(1, count + 1):
        sheet.cell(row, 1, f'Public arithmetic {row}')
        sheet.cell(row, 2, row)
    path = tmp_path / '34000_labels.xlsx'; book.save(path); book.close()
    started = time.perf_counter()
    actual = indexed.profile_workbook(path, count * 2)
    seconds = time.perf_counter() - started
    assert actual['cells_emitted'] == actual['nonempty_cells'] == count * 2
    assert actual['formula_count'] == 0 and actual['truncated'] is False
    assert actual['sheets'][0]['max_row'] == count
    for cell in actual['sheets'][0]['cells']:
        row = int(cell['cell'][1:])
        if cell['cell'].startswith('A'):
            expected = [{'cell': f'A{prior}', 'value': f'Public arithmetic {prior}'}
                        for prior in range(max(1, row - 3), row)]
            assert cell['column_labels'] == expected
            assert cell['row_labels'] == []
        else:
            assert cell['row_labels'] == [{'cell': f'A{row}', 'value': f'Public arithmetic {row}'}]
            assert cell['column_labels'] == []
    print(json.dumps({'kind': 'indexed_profile_34000_label_offline_measurement',
                      'label_rows': count, 'profile_cells': count * 2, 'wall_seconds': round(seconds, 6),
                      'old_34000_label_profiler_executed': False, 'LO_calls': 0, 'model_calls': 0}))


def test_original_profiler_is_a_separate_unchanged_implementation():
    assert Path(indexed.__file__) != Path(original.__file__)
    assert indexed.profile_workbook is not original.profile_workbook
    assert indexed.formula_references is original.formula_references
    assert indexed.json_value is original.json_value
