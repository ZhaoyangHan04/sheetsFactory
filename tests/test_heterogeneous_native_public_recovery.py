"""Tiny native formula books only: no journal execution, Calc, Docker or models."""
import ast
from copy import deepcopy
import inspect
import json
from pathlib import Path

import openpyxl
import pytest

from sheets_factory.workbook import heterogeneous_native_public_recovery as recovery
from sheets_factory.workbook.heterogeneous_contracts import spec, specialized_excel

ROOT = Path(__file__).resolve().parents[1]


def tiny_spec():
    # Public construction primitives used solely to emit one tiny unit fixture.
    # No source manifest, expected workbook, journal or cached answer is read.
    raw = json.loads((ROOT / 'config/heterogeneous_contracts/prototype_v2.json').read_text())
    raw['dimension_mode'] = 'toy'; raw['months'] = raw['months'][:3]
    raw['scenario_ids'] = ['S01']; raw['scenarios'] = raw['scenarios'][:1]
    raw['scenarios'][0]['monthly_schedule'] = raw['scenarios'][0]['monthly_schedule'][:3]
    raw['entities'] = raw['entities'][:1]
    raw['entities'][0]['tax_policy'] = 'CASH_COUPON_QUARTERLY'
    raw['entities'][0]['dscr_policy'] = 'QUARTERLY_LAGGED'
    raw['loans'] = raw['loans'][:1]; raw['loans'][0]['type'] = 'BULLET_QUARTERLY_ACCRUAL'
    raw['loans'][0]['terms'] = raw['loans'][0]['terms'][:1]
    raw['loans'][0]['terms'][0]['next_coupon_month'] = '2027-03-01'
    raw['assets'] = raw['assets'][:2]
    raw['assets'][1].update(commission_month='2027-01-01', original_cost_pence=5, useful_life_months=2)
    raw['operating_inputs'] = {'E01': raw['operating_inputs']['E01'][:3]}
    for key in ('bank_funding_priority', 'shared_margin_priority', 'lp_funding_priority'):
        raw['group'][key] = ['E01']
    raw['group']['shared_bank_limit_schedule'] = raw['group']['shared_bank_limit_schedule'][:1]
    return spec.load_spec(raw)


@pytest.fixture(scope='module')
def baseline(tmp_path_factory):
    directory = tmp_path_factory.mktemp('tiny-native-source-not-a-real-source')
    book = openpyxl.Workbook(); public = tiny_spec()
    bindings = specialized_excel.emit_heterogeneous_workbook(book, public)
    path = directory / 'unit.xlsx'; book.save(path); book.close()
    return path, public, bindings


def mutate(baseline, tmp_path, operation):
    source = tmp_path / 'public.xlsx'
    book = openpyxl.load_workbook(baseline[0])
    try:
        operation(book)
        book.save(source)
    finally:
        book.close()
    return source


def financial(bindings, field, domain='entities'):
    return next(r for r in bindings['financial_bindings'] if r['cell'].startswith('B')
        and len(r['expected_path']) == 7 and r['expected_path'][2] == domain
        and r['expected_path'][-1] == field)


def test_parser_reads_native_headers_without_fabricating_asset_note(baseline):
    book = openpyxl.load_workbook(baseline[0], data_only=False)
    try:
        parsed = recovery.parse_public_inputs(book)
        assert parsed['months'] == baseline[1]['months']
        assert parsed['entities'] == baseline[1]['entities']
        assert parsed['loans'] == baseline[1]['loans']
        assert parsed['assets'] == baseline[1]['assets']
        assert parsed['operating_inputs'] == baseline[1]['operating_inputs']
        assert not any(row[0] == 'Asset depreciation' for row in book['Contract Notes'].values)
        assert book.sheetnames == recovery.native_sheetnames(['S01'])
        assert len(book.sheetnames) == 20
    finally:
        book.close()


def test_tiny_public_repair_rebuilds_formulas_preserves_every_supplied_literal_and_style(baseline, tmp_path):
    row = financial(baseline[2], 'cash_tax')
    source = mutate(baseline, tmp_path, lambda b: setattr(b[row['sheet']][row['cell']], 'value', '=123'))
    before_ref = recovery.reference(source)
    output, report = tmp_path / 'output.xlsx', tmp_path / 'report.json'
    instruction = tmp_path / 'instruction.md'; instruction.write_text('Repair formula errors using the supplied contracts.')
    result = recovery.recover_public(source, output, report, instruction)
    assert recovery.reference(source) == before_ref
    assert result == json.loads(report.read_text())
    assert result['lexically_different_formula_count'] == 1
    assert result['complete_formula_count'] == baseline[2]['formula_count']
    assert result['asset_policy']['all_asset_periods_and_scenarios_covered'] is True
    assert result['asset_policy']['computed_caches_used'] is False
    assert result['shared_source_Excel_reconstruction'] is True
    assert not result['third_independent_financial_implementation']
    assert not result['private_goal_spec_bindings_defect_list_or_cached_answers_used']
    assert result['actual_LO_calls'] == 0 and result['actual_isolated_replay_verified'] is False
    a = openpyxl.load_workbook(source); b = openpyxl.load_workbook(output)
    try:
        assert a.sheetnames == b.sheetnames
        assert recovery._literal_inventory(a) == recovery._literal_inventory(b)
        assert b[row['sheet']][row['cell']].value == row['formula']
        for sheet in a:
            for cell in sheet._cells.values():
                other = b[sheet.title][cell.coordinate]
                assert cell.number_format == other.number_format
                assert cell._style == other._style
    finally:
        a.close(); b.close()


@pytest.mark.parametrize('field', ['depreciation', 'capex', 'nbv_open', 'accumulated_depreciation_open',
    'cost_close', 'accumulated_depreciation_close', 'nbv_close'])
def test_changed_asset_rules_are_not_silently_assumed_or_repaired(baseline, tmp_path, field):
    row = financial(baseline[2], field, 'assets')
    source = mutate(baseline, tmp_path, lambda b: setattr(b[row['sheet']][row['cell']], 'value', '=0'))
    with pytest.raises(recovery.PublicRecoveryError, match='asset formula'):
        recovery.recover_public(source, tmp_path / 'out.xlsx', tmp_path / 'report.json')
    assert not (tmp_path / 'out.xlsx').exists()


def test_rounding_clamp_and_final_residual_policy_is_observed_in_public_formula(baseline):
    book = openpyxl.load_workbook(baseline[0])
    try:
        rows = [r for r in baseline[2]['financial_bindings'] if r['cell'].startswith('B')
            and r['expected_path'][2] == 'assets' and r['expected_path'][-1] == 'depreciation']
        assert len(rows) == 6
        assert all('ROUND(' in book[r['sheet']][r['cell']].value
            and 'MIN(' in book[r['sheet']][r['cell']].value and '<=' in book[r['sheet']][r['cell']].value
            for r in rows)
        result = recovery.attest_public_asset_rules(book, book, baseline[2])
        assert result['asset_financial_roots'] == 108  # 2 assets ×3 months ×9 fields ×2 aliases.
        assert result['complete_definition_formulas_checked'] >= 108
        assert all(ref.startswith(("'Asset Register'!", "'Calendar'!")) for ref in result['native_input_leaves'])
    finally:
        book.close()


@pytest.mark.parametrize('corrupt', ['native_formula', 'raw_bool', 'policy', 'extra_asset_note',
    'extra_formula', 'missing_formula', 'sheet_order', 'header'])
def test_public_schema_geometry_and_policy_fail_closed(baseline, tmp_path, corrupt):
    def change(book):
        if corrupt == 'native_formula': book['Asset Register']['E2'] = '=1'
        elif corrupt == 'raw_bool': book['Entity Policies']['M2'] = False
        elif corrupt == 'policy': book['Contract Notes']['B2'] = 'Different assumptions'
        elif corrupt == 'extra_asset_note':
            row = book['Contract Notes'].max_row + 1
            book['Contract Notes'].cell(row, 1, 'Asset depreciation')
            book['Contract Notes'].cell(row, 2, 'A synthetic explanation')
        elif corrupt == 'extra_formula': book['Input Calculations']['Z999'] = '=1'
        elif corrupt == 'missing_formula':
            r = financial(baseline[2], 'cash_tax'); book[r['sheet']][r['cell']] = 0
        elif corrupt == 'sheet_order': book._sheets[-1], book._sheets[-2] = book._sheets[-2], book._sheets[-1]
        else: book['Facility Terms']['A1'] = 'Private program field dictionary'
    source = mutate(baseline, tmp_path, change)
    with pytest.raises(recovery.PublicRecoveryError):
        recovery.recover_public(source, tmp_path / 'out.xlsx', tmp_path / 'report.json')
    assert not (tmp_path / 'out.xlsx').exists()


def test_existing_or_alias_output_paths_rejected_before_reconstruction(baseline, tmp_path):
    with pytest.raises(recovery.PublicRecoveryError, match='Fresh distinct'):
        recovery.recover_public(baseline[0], baseline[0], tmp_path / 'report.json')
    output = tmp_path / 'out.xlsx'; output.write_text('Retain existing failure')
    with pytest.raises(recovery.PublicRecoveryError, match='Fresh distinct'):
        recovery.recover_public(baseline[0], output, tmp_path / 'report.json')
    assert output.read_text() == 'Retain existing failure'


@pytest.mark.parametrize('name', ['output', 'report'])
def test_dangling_output_or_report_alias_is_not_a_fresh_regular_path(baseline, tmp_path, name):
    output, report = tmp_path / 'out.xlsx', tmp_path / 'report.json'
    target = tmp_path / 'uncreated'
    (output if name == 'output' else report).symlink_to(target)
    with pytest.raises(recovery.PublicRecoveryError, match='Fresh distinct'):
        recovery.recover_public(baseline[0], output, report)
    assert not target.exists()


@pytest.mark.parametrize('dependency', ['parser', 'lexical', 'financial'])
def test_exact_parser_and_financial_implementation_guards(monkeypatch, baseline, tmp_path, dependency):
    if dependency == 'parser':
        monkeypatch.setattr(recovery, 'PARSER_SHA256', '0' * 64)
    elif dependency == 'lexical':
        monkeypatch.setattr(recovery, 'LEXICAL_SHA256', '0' * 64)
    else:
        monkeypatch.setattr(recovery, 'SHARED_SHA256', dict(recovery.SHARED_SHA256,
            **{'heterogeneous_contracts/excel.py': '0' * 64}))
    with pytest.raises(recovery.PublicRecoveryError, match='changed'):
        recovery.recover_public(baseline[0], tmp_path / 'out.xlsx', tmp_path / 'report.json')


def test_pure_parser_ast_contains_no_financial_execution_or_private_input_route():
    tree = recovery.pure_parser_ast()
    assert {n.name for n in tree.body if isinstance(n, ast.FunctionDef)} == {
        '_text', '_integer', '_day', '_rows', '_parse_book'}
    assert not any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(tree))
    assert list(inspect.signature(recovery.recover_public).parameters) == [
        'source', 'destination', 'report', 'instruction_path']
    source = ast.parse(Path(recovery.__file__).read_text())
    assert not any(isinstance(n, ast.Attribute) and n.attr in ('simulate', 'recalculate', 'Popen')
        for n in ast.walk(source))
    assert all('ledger' not in (n.module or '') for n in ast.walk(source) if isinstance(n, ast.ImportFrom))
