"""Composite masks are exact numeric families, not whole-sheet erasures."""
from datetime import datetime
import hashlib

import openpyxl
from openpyxl.utils.cell import range_boundaries
import pytest

from sheets_factory.nodes.construction import compile_mask_ranges
from sheets_factory.workbook.composite_finance.tasks import (
    propose_task, _is_date_formula, _PROVIDED, _REGULATORY, _OPERATING, _HOLDING,
)


def _fixture(tmp_path):
    book = openpyxl.Workbook()
    book.remove(book.active)
    for index in range(31):
        book.create_sheet(f'Official {index:02d}')['C3'] = '=17*19'
    targets = ['Lease Contract-A', 'Lease Contract-B', 'Lease Monthly', 'Lease Annual',
               *_REGULATORY, *('Operating ' + name for name in _OPERATING), *_HOLDING]
    for name in [*_PROVIDED, *targets, 'Model Input Contracts']:
        if name not in book:
            book.create_sheet(name)
    for name in ('Lease Read Me', 'Reopener Brief', 'Operating Read Me', 'Holding Brief'):
        book[name]['A3'] = 'This hypothetical model follows the explicit public business policies supplied with its assumptions and original reporting calendar.'
    book['Lease Inputs']['A5'] = 'lease id'
    book['Lease Inputs']['C5'] = 'Contract-A'
    book['Lease Inputs']['D5'] = 'Contract-B'
    book['Lease Inputs']['A8'] = 'end month'
    book['Lease Inputs']['C8'] = 240
    book['Operating Scenario']['B3'] = 71
    book['Operating Scenario']['B4'] = '=B3*12'
    book['Lease Calendar']['C1'] = '=DATE(2023,4,1)'
    book['Lease Calendar']['C2'] = '=1'
    book['Lease Calendar']['C3'] = '=2024'
    book['Model Input Contracts']['B4'] = '{"primitive_policy":"provided"}'
    expected = set()
    for name in targets:
        sheet = book[name]
        sheet['A1'] = name
        sheet['C1'] = '=DATE(2023,4,1)'
        sheet['C1'].number_format = 'yyyy-mm-dd'
        sheet['C2'] = '=1' if name.startswith('Lease ') else 2024
        for row in (3, 4, 6):
            sheet.cell(row, 1, f'financial field {row}')
            for column in (3, 4, 6):
                sheet.cell(row, column, '=71*12')
                expected.add((name, sheet.cell(row, column).coordinate))
        # A hole containing an input must not disappear inside a rectangle.
        sheet['E3'] = 71
        sheet['C7'] = '=DATE(2024,3,31)'
        sheet['C7'].number_format = 'yyyy-mm-dd'
    annual = book['Operating Annual Statements']
    annual['A8'], annual['A9'] = 'Start date', 'End date'
    for address in ('C8', 'C9'):
        annual[address] = '=DATE(2027,1,1)'
        # These public date labels remain protected even with a General style.
    equity = book['Operating Equity Value']
    equity['B11'] = '=IRR(C3:D3)'
    expected.add((equity.title, 'B11'))
    bridge = book['Holding Operating Link']
    for row in (3, 4, 6):
        bridge.cell(row, 1, '=DATE(2027,1,1)')
        bridge.cell(row, 1).number_format = 'yyyy-mm-dd'
        bridge.cell(row, 2, '=2027')
    path = tmp_path / 'source.xlsx'
    book.save(path)
    book.close()
    return path, expected


def _targets(plan):
    result = set()
    for rectangle in plan['mask_ranges']:
        left, top, right, bottom = range_boundaries(rectangle['range'])
        for row in range(top, bottom + 1):
            for column in range(left, right + 1):
                coordinate = openpyxl.utils.get_column_letter(column) + str(row)
                key = rectangle['sheet'], coordinate
                assert key not in result, 'Overlapping generated mask ranges'
                result.add(key)
    return result


def test_exact_families_without_inputs_dates_periods_or_official_formulas(tmp_path):
    path, expected = _fixture(tmp_path)
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    plan = propose_task(path)
    assert _targets(plan) == expected
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original
    assert plan['scenario_inputs'] == plan['edits'] == []
    assert {name for name, _ in expected} == set(plan['target_sheets'])
    assert not any(name.startswith('Official ') for name, _ in expected)
    assert all(not name.startswith('Official ') for name in plan['target_sheets'])
    assert any(item.startswith("'Model Input Contracts'!") for item in plan['protected_inputs'])
    assert any(item.startswith("'Operating Scenario'!") for item in plan['protected_inputs'])


def test_normal_compiler_uses_source_formula_assertions_and_no_literal_masks(tmp_path):
    path, expected = _fixture(tmp_path)
    plan = propose_task(path, mode='financial_modeling')
    compiled = compile_mask_ranges(plan, path, 'financial_modeling', {
        'construction': {'max_edit_count': {'financial_modeling': 200000},
                         'analysis_limits': {'max_mask_ranges': 1024}}})
    assert {(edit['sheet'], edit['cell']) for edit in compiled['edits']} == expected
    assert all(edit['before'] == '=71*12' or edit['before'] == '=IRR(C3:D3)'
               for edit in compiled['edits'])
    assert all(edit['after'] is None for edit in compiled['edits'])
    assert plan['edits'] == []


def test_public_text_has_complete_goals_and_no_answers_or_calculation_recipe(tmp_path):
    path, _ = _fixture(tmp_path)
    plan = propose_task(path)
    text = plan['public_instruction']
    assert 60 <= len(text.split()) <= 100
    assert all(term in text.lower() for term in ('lease', 'tax', 'parent', 'consolidated', 'currencies', 'output'))
    assert isinstance(plan['public_rules'], list) and len(plan['public_rules']) == 1
    assert not any(term in text for term in ('=71', '852', '/workspace/', 'C3', 'SUM(', 'ROUND('))
    assert 'correctness' not in str(plan['reference_evidence']).lower()


@pytest.mark.parametrize('mode', ['debugging', 'other', None])
def test_unimplemented_modes_are_explicitly_rejected(tmp_path, mode):
    path, _ = _fixture(tmp_path)
    with pytest.raises(ValueError, match='financial_modeling only'):
        propose_task(path, mode=mode)


@pytest.mark.parametrize('change,message', [
    ('missing', 'missing sheets'), ('empty', 'calculation family'),
    ('duplicate_lease', 'unique public lease'), ('unknown_lease', 'Unrecognized lease'),
    ('policy', 'public business policies'), ('date_label', 'start date'),
])
def test_unrecognized_or_incomplete_models_fail_closed(tmp_path, change, message):
    path, _ = _fixture(tmp_path)
    book = openpyxl.load_workbook(path)
    if change == 'missing':
        del book['Holding Consolidated']
    elif change == 'empty':
        for cell in book['Reopener Claims']._cells.values():
            if cell.data_type == 'f' and cell.row > 2:
                cell.value = None
    elif change == 'duplicate_lease':
        book['Lease Inputs']['D5'] = 'Contract-A'
    elif change == 'unknown_lease':
        book.create_sheet('Lease Hidden New Product')['C3'] = '=1'
    elif change == 'policy':
        book['Holding Brief']['A3'] = None
    elif change == 'date_label':
        book['Operating Annual Statements']['A8'] = 'Unknown period'
    book.save(path)
    book.close()
    before = path.read_bytes()
    with pytest.raises(ValueError, match=message):
        propose_task(path)
    assert path.read_bytes() == before


def test_cached_date_typing_preserves_general_style_formula():
    book = openpyxl.Workbook()
    source = book.active['C3']
    source.value = '=DATE(2024,3,31)'
    cached = book.create_sheet()['C3']
    cached.value = datetime(2024, 3, 31)
    cached.number_format = 'General'
    assert source.number_format == 'General' and not source.is_date
    assert _is_date_formula(source, cached)
    cached.value = 120.01
    assert not _is_date_formula(source, cached)
    book.close()
