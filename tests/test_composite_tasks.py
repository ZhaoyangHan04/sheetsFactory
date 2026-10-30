"""Composite masks are exact numeric families, not whole-sheet erasures."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

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


@pytest.mark.parametrize('mode', ['other', None])
def test_unimplemented_modes_are_explicitly_rejected(tmp_path, mode):
    path, _ = _fixture(tmp_path)
    with pytest.raises(ValueError, match='financial_modeling or debugging only'):
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


def _financial_fixture(tmp_path, *, waterfall=True):
    """Small public field fixture, with explicit numeric cached outputs."""
    path, _ = _fixture(tmp_path)
    book = openpyxl.load_workbook(path)
    contracts = book['Model Input Contracts']
    for index, name in enumerate(('lease', 'programme', 'operating', 'holding', 'contingent'), 4):
        contracts.cell(index, 1, name)
        contracts.cell(index, 2, json.dumps({'schema_version': 1, 'fixture': name}))
    for name in ('Contingent Inputs', 'Contingent Contract', 'Contingent Annual'):
        book.create_sheet(name)
    book['Contingent Inputs']['C4'] = .85
    book['Contingent Contract']['A3'] = 'Apply the explicit hypothetical current rent terms and total current revenue entitlement supplied in this contract.'
    for row, field in enumerate(('total_recovery_entitlement', 'variable_rents.P01', 'variable_rents.P02',
        'variable_rents.P03', 'variable_rents.P04', 'variable_lease_cash',
        'variable_lease_allowance', 'variable_book_expense', 'variable_tax_deduction'), 3):
        book['Contingent Annual'].cell(row, 1, field)
        book['Contingent Annual'].cell(row, 3, '=71*12')
        book['Contingent Annual'].cell(row, 4, '=71*12')
    for name in ('Lease Contract-A', 'Lease Contract-B', 'Lease Monthly', 'Lease Annual'):
        sheet = book[name]
        for row, field in ((3, 'lease_rou_open'), (4, 'lease_cash_rent'), (6, 'lease_book_interest')):
            sheet.cell(row, 1, field)
        if name not in ('Lease Monthly', 'Lease Annual'):
            for row, field in enumerate(('event_index_ratio', 'lease_current_end_month',
                'measurement_flag', 'annual_discount_rate', 'lease_retained_exposure'), 10):
                sheet.cell(row, 1, field)
                sheet.cell(row, 3, '=1')
    for name, field, row in (('Operating Annual Statements', 'Periods', 11),
        ('Operating Annual Statements', 'Year', 12), ('Operating Tax Vintages', 'Model year', 2),
        ('Operating Covenants', 'test due', 10), ('Operating Cash Flow', 'Optional allocation allowed', 14)):
        book[name].cell(row, 1, field)
        book[name].cell(row, 3, '=1')
    book['Operating Equity Value']['A3'] = 'annual discount rate'
    book['Operating Equity Value']['A4'] = 'monthly discount rate'
    if waterfall:
        from sheets_factory.workbook.partner_waterfall.schema import FIELDS, row as partner_row
        contracts.cell(9, 1, 'waterfall')
        contracts.cell(9, 2, json.dumps({'schema_version': 1, 'fixture': 'waterfall'}))
        for name in ('Partner Inputs', 'Partner Contract', 'Partner Waterfall'):
            book.create_sheet(name)
        book['Partner Inputs']['B3'] = datetime(2023, 4, 1)
        book['Partner Contract']['A3'] = 'Apply the supplied hypothetical partner preference, capital return, catch up and next year carry provisions.'
        sheet = book['Partner Waterfall']
        for field in FIELDS:
            sheet.cell(partner_row(field), 1, field)
            sheet.cell(partner_row(field), 3, '=71*12')
            sheet.cell(partner_row(field), 4, '=71*12')
        for field in ('lp_net_cashflow', 'gp_net_cashflow'):
            sheet.cell(partner_row(field), 2, '=-71')
        sheet['B2'] = datetime(2023, 4, 1)
        sheet['C2'] = datetime(2024, 3, 31)
        sheet['D2'] = datetime(2025, 3, 31)
        sheet.cell(partner_row('lp_xirr'), 3, '=IF(1=0,1,"")')
        sheet.cell(partner_row('lp_xirr'), 4, '=.07')
    book.save(path)
    book.close()
    _set_fixture_caches(path)
    return path


def _set_fixture_caches(path, overrides=None):
    """Set explicit fixture caches only; this does not assert real engine proof."""
    ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(path) as archive:
        files = {item.filename: archive.read(item.filename) for item in archive.infolist()}
    for name, raw in list(files.items()):
        if not name.startswith('xl/worksheets/') or not name.endswith('.xml'):
            continue
        tree = ET.fromstring(raw)
        for cell in tree.findall('.//x:c', ns):
            formula = cell.find('x:f', ns)
            if formula is None:
                continue
            value = cell.find('x:v', ns)
            if value is None:
                value = ET.SubElement(cell, '{' + ns['x'] + '}v')
            value.text = '852'
            if formula.text == 'IF(1=0,1,"")':
                cell.set('t', 'str')
                value.text = None
            if overrides and formula.text in overrides:
                cell.set('t', 'str')
                value.text = overrides[formula.text]
        files[name] = ET.tostring(tree, encoding='utf-8')
    with ZipFile(path, 'w', compression=ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)


def test_explicit_v4_financial_scope_excludes_state_flags_dates_and_nullable_xirr(tmp_path):
    from sheets_factory.workbook.partner_waterfall.contract import FINANCIAL_FIELDS
    from sheets_factory.workbook.partner_waterfall.schema import FIELDS, row as partner_row
    path = _financial_fixture(tmp_path)
    before = path.read_bytes()
    plan = propose_task(path)
    targets = _targets(plan)
    assert path.read_bytes() == before
    for field in FINANCIAL_FIELDS:
        row = partner_row(field)
        assert ('Partner Waterfall', 'D' + str(row)) in targets
        assert (('Partner Waterfall', 'C' + str(row)) in targets) == (field != 'lp_xirr')
    for field in set(FIELDS) - set(FINANCIAL_FIELDS):
        assert ('Partner Waterfall', 'C' + str(partner_row(field))) not in targets
        assert ('Partner Waterfall', 'D' + str(partner_row(field))) not in targets
    for sheet in ('Lease Contract-A', 'Lease Contract-B'):
        assert all((sheet, 'C' + str(row)) not in targets for row in range(10, 15))
        assert (sheet, 'C4') in targets
    for sheet, address in (('Operating Annual Statements', 'C11'),
        ('Operating Annual Statements', 'C12'), ('Operating Tax Vintages', 'C2'),
        ('Operating Covenants', 'C10'), ('Operating Cash Flow', 'C14'),
        ('Operating Equity Value', 'C3'), ('Operating Equity Value', 'C4')):
        assert (sheet, address) not in targets
    assert ('Operating Equity Value', 'B11') in targets
    assert ('Partner Waterfall', 'B27') in targets and ('Partner Waterfall', 'B28') in targets
    assert sum(sheet == 'Contingent Annual' for sheet, _ in targets) == 18
    assert any(item.startswith("'Contingent Inputs'!") for item in plan['protected_inputs'])
    assert any(item.startswith("'Partner Inputs'!") for item in plan['protected_inputs'])
    assert 60 <= len(plan['public_instruction'].split()) <= 100
    assert 'partnership distributions' in plan['public_instruction']
    compiled = compile_mask_ranges(plan, path, 'financial_modeling', {'construction': {
        'max_edit_count': {'financial_modeling': 200000}, 'analysis_limits': {'max_mask_ranges': 1024}}})
    assert {(edit['sheet'], edit['cell']) for edit in compiled['edits']} == targets


def test_contingent_v3_scope_does_not_require_optional_waterfall(tmp_path):
    path = _financial_fixture(tmp_path, waterfall=False)
    plan = propose_task(path)
    assert 'Contingent Annual' in plan['target_sheets']
    assert 'Partner Waterfall' not in plan['target_sheets']
    assert 'partnership distributions' not in plan['public_instruction']
    assert 60 <= len(plan['public_instruction'].split()) <= 100


@pytest.mark.parametrize('change,message', [('missing_record', 'all five'),
    ('invalid_json', 'Invalid public module'), ('duplicate', 'Duplicate public'),
    ('missing_schedule', 'Missing explicit financial'), ('nonnumeric', 'Finite cached')])
def test_financial_only_contract_and_numeric_coverage_fail_closed(tmp_path, change, message):
    path = _financial_fixture(tmp_path)
    book = openpyxl.load_workbook(path)
    if change == 'missing_record':
        book['Model Input Contracts']['A4'] = None
    elif change == 'invalid_json':
        book['Model Input Contracts']['B8'] = '{invalid'
    elif change == 'duplicate':
        book['Model Input Contracts']['A10'] = 'contingent'
        book['Model Input Contracts']['B10'] = '{}'
    elif change == 'missing_schedule':
        del book['Contingent Annual']
    elif change == 'nonnumeric':
        book['Lease Contract-A']['C4'] = '=FINANCIAL_STRING_FIXTURE()'
    book.save(path)
    book.close()
    _set_fixture_caches(path, {'FINANCIAL_STRING_FIXTURE()': 'text output'})
    with pytest.raises(ValueError, match=message):
        propose_task(path)
