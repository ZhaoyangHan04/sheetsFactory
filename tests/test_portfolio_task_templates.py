"""Authoring fixtures have injected caches; these are not real LO proofs."""
import hashlib
import importlib.util
from pathlib import Path

import openpyxl
import pytest

from test_project_task_templates import build_project, _write_fixture_caches
from sheets_factory.nodes.construction import compile_mask_ranges
from sheets_factory.workbook.derived_gold.portfolio_tasks import propose_portfolio_task


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def portfolio(build_project, tmp_path):
    source = build_project()
    raw = openpyxl.load_workbook(source)
    cached = openpyxl.load_workbook(source, data_only=True)
    spec = importlib.util.spec_from_file_location('portfolio_builder_fixture', ROOT / 'scripts/build_portfolio_source.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    book = openpyxl.Workbook()
    book.remove(book.active)
    numeric = []
    for prefix in ['T01', 'T02']:
        mapping = {name: prefix + ' ' + name for name in raw.sheetnames}
        for name in raw.sheetnames:
            target = book.create_sheet(mapping[name])
            for cell in raw[name]._cells.values():
                if cell.value is None:
                    continue
                copied = target[cell.coordinate]
                copied.value = builder.rewrite_formula(cell.value, mapping) if cell.data_type == 'f' else cell.value
                copied.number_format = cell.number_format
                value = cached[name][cell.coordinate].value
                if cell.data_type == 'f' and isinstance(value, (int, float)) and not isinstance(value, bool):
                    numeric.append({'address': target.title + '!' + cell.coordinate,
                                    'expected_independent': str(value), 'kind': 'money'})
    book.create_sheet('Portfolio Index')['A1'] = 'Wholly owned; no intercompany transactions.'
    for name in ['Group Statements', 'Group Summary']:
        sheet = book.create_sheet(name)
        sheet['C1'] = "='T01 Calendar'!C3"
        sheet['C1'].number_format = 'yyyy-mm-dd'
        sheet['A2'] = 'Consolidated cash'
        sheet['C2'] = "=SUM('T01 Cash Flow'!C12,'T02 Cash Flow'!C12)"
    path = tmp_path / 'portfolio_authoring_fixture.xlsx'
    book.save(path)
    for item in [raw, cached, book]:
        item.close()
    _write_fixture_caches(path, numeric)
    return path


def test_portfolio_modeling_selects_complete_entity_and_group_families(portfolio):
    before = hashlib.sha256(portfolio.read_bytes()).hexdigest()
    plan = propose_portfolio_task(portfolio, 'financial_modeling')
    compiled = compile_mask_ranges(plan, portfolio, 'financial_modeling', {'construction': {
        'max_edit_count': {'financial_modeling': 100000},
        'analysis_limits': {'max_mask_ranges': 256}}})
    assert len(compiled['edits']) > 9000
    assert {'T01 Operations', 'T02 Tax Vintages', 'Group Statements', 'Group Summary'} <= set(plan['target_sheets'])
    book = openpyxl.load_workbook(portfolio)
    for edit in compiled['edits']:
        cell = book[edit['sheet']][edit['cell']]
        assert not cell.is_date
        assert cell.data_type == 'f' and cell.value == edit['before']
        assert not edit['sheet'].endswith(('Scenario', 'Source Inputs', 'Calendar', 'Read Me'))
    assert not any(edit['cell'] == 'C1' for edit in compiled['edits'] if edit['sheet'].startswith('Group '))
    assert hashlib.sha256(portfolio.read_bytes()).hexdigest() == before
    book.close()


def test_debugging_proposes_whole_active_facility_families_with_exact_before(portfolio):
    before = hashlib.sha256(portfolio.read_bytes()).hexdigest()
    plan = propose_portfolio_task(portfolio, 'debugging')
    assert len(plan['edits']) == 72
    assert {edit['sheet'] for edit in plan['edits']} == {'T01 Debt', 'T02 Debt'}
    book = openpyxl.load_workbook(portfolio)
    for edit in plan['edits']:
        assert book[edit['sheet']][edit['cell']].value == edit['before']
        assert edit['after'] != edit['before'] and edit['after'].startswith('=')
        assert edit['sheet'].split()[0] in edit['after']
    assert not plan.get('mask_ranges')
    assert hashlib.sha256(portfolio.read_bytes()).hexdigest() == before
    book.close()


@pytest.mark.parametrize('sheet', ['Portfolio Index', 'Group Statements', 'T02 Read Me'])
def test_incomplete_portfolio_or_missing_policies_is_rejected(portfolio, sheet):
    book = openpyxl.load_workbook(portfolio)
    del book[sheet]
    book.save(portfolio)
    book.close()
    with pytest.raises(ValueError):
        propose_portfolio_task(portfolio, 'financial_modeling')


def test_unknown_task_mode_is_rejected(portfolio):
    with pytest.raises(ValueError, match='Unsupported'):
        propose_portfolio_task(portfolio, 'other')
