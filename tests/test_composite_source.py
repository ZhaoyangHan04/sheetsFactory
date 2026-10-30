"""Reference isolation and provenance safeguards for composed financial inputs."""
from datetime import datetime
import hashlib
import json

import openpyxl
import pytest

from sheets_factory.workbook.composite_finance.operating import (checked_json, rewrite_formula,
    clarify_operating_cash_stages, OPERATING_CASH_STAGE_POLICY)
from sheets_factory.workbook.composite_finance.build import emit_public_specs, PUBLIC_SHEET, audit_provided_context
from sheets_factory.workbook.derived_gold.validate import _WorkbookProjection


def test_reference_rewriting_does_not_change_string_literals_or_relative_addresses():
    formula = '=IF(\'T01 Debt\'!$C4="T01 Debt",SUM(\'T01 Tax\'!C3:F3),$B$2)'
    result = rewrite_formula(formula, {'T01 Debt': 'Operating Debt', 'T01 Tax': 'Operating Tax'})
    assert result == '=IF(\'Operating Debt\'!$C4="T01 Debt",SUM(\'Operating Tax\'!C3:F3),$B$2)'


def test_quoted_apostrophes_are_decoded_and_escaped_once():
    assert rewrite_formula("='Owner''s Debt'!$C$2", {"Owner's Debt": "Partner's Debt"}) == "='Partner''s Debt'!$C$2"


@pytest.mark.parametrize('formula', ["='T02 Debt'!C3", "='[other.xlsx]Debt'!C3", "='Debt:Tax'!C3"])
def test_unmapped_cross_entity_external_and_three_dimensional_references_are_rejected(formula):
    with pytest.raises(ValueError, match='unmapped sheet dependency'):
        rewrite_formula(formula, {'T01 Debt': 'Operating Debt'})


def test_operating_evidence_cannot_be_replaced_after_binding(tmp_path):
    path = tmp_path / 'journal.json'
    path.write_text('{"cash":"1.00"}')
    reference = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    assert checked_json(reference)['cash'] == '1.00'
    path.write_text('{"cash":"2.00"}')
    with pytest.raises(ValueError, match='Changed operating evidence'):
        checked_json(reference)


def test_project_audit_projection_keeps_types_and_excludes_other_modules():
    book = openpyxl.Workbook()
    book.active.title = 'Operating Calendar'
    book.active['C3'] = datetime(2027, 1, 1)
    book.create_sheet('Other Model')['A1'] = '=1/0'
    view = _WorkbookProjection(book, {'Calendar': 'Operating Calendar'})
    assert view['Calendar']['C3'].value == datetime(2027, 1, 1)
    assert [sheet.title for sheet in view] == ['Calendar']
    with pytest.raises(KeyError):
        view['Other Model']
    view.close()


def test_project_audit_rejects_aliasing_two_schedules_to_one_sheet():
    book = openpyxl.Workbook()
    with pytest.raises(ValueError, match='injective'):
        _WorkbookProjection(book, {'Debt': 'Sheet', 'Tax': 'Sheet'})


def test_public_input_copy_preserves_assumptions_and_omits_local_provenance():
    book = openpyxl.Workbook()
    emit_public_specs(book, {'programme': {'parameters': {'tax_rate': '.25'},
                                          'source': {'path': '/private/context.xlsx', 'official_url': 'https://example.org/source.xlsx'}}})
    value = json.loads(book[PUBLIC_SHEET]['B4'].value)
    assert value['parameters'] == {'tax_rate': '.25'}
    assert value['source'] == {'official_url': 'https://example.org/source.xlsx'}
    book.close()


def test_added_modules_may_not_change_provided_financial_context(tmp_path):
    source, goal = tmp_path / 'provided.xlsx', tmp_path / 'complete.xlsx'
    book = openpyxl.Workbook()
    book.active.title = 'Cover'
    book.active['G4'] = 'volatile filename metadata'
    book.create_sheet('Original Forecast')['B2'] = 100
    book.save(source)
    book['Cover']['G4'] = 'stable metadata'
    book.create_sheet('New Lease Calculation')['A1'] = 25
    book.save(goal)
    adapters = [{'sheet': 'Cover', 'cell': 'G4'}]
    assert audit_provided_context(source, goal, adapters)['passed']
    book['Original Forecast']['B2'] = 99
    book.save(goal)
    result = audit_provided_context(source, goal, adapters)
    assert not result['passed']
    assert result['mismatches'][0]['address'] == 'Original Forecast!B2'
    with pytest.raises(ValueError, match='nonfinancial'):
        audit_provided_context(source, goal, [{'sheet': 'Original Forecast', 'cell': 'B2'}])
    book.close()


def test_stage_clarification_is_explicit_public_text_without_financial_edits():
    book = openpyxl.Workbook()
    book.active.title = 'Operating Read Me'
    book.active['B1'] = 'Existing public policy'
    book.create_sheet('Operating Cash Flow')['C8'] = '=C2+C3-C6-C7'
    spec = {'public_rules': ['Existing public policy'], 'parameters': {'minimum_cash': '500000'}}
    old_formula = book['Operating Cash Flow']['C8'].value
    adapter = clarify_operating_cash_stages(book, spec, 'Operating Read Me')
    assert spec['parameters'] == {'minimum_cash': '500000'}
    assert book['Operating Cash Flow']['C8'].value == old_formula
    assert book[adapter['sheet']][adapter['cell']].value == spec['public_rules'][-1] == OPERATING_CASH_STAGE_POLICY
    assert 'before DSRA transfers' in OPERATING_CASH_STAGE_POLICY
    assert 'after DSRA transfers and revolver repayment' in OPERATING_CASH_STAGE_POLICY
    with pytest.raises(ValueError, match='already exists'):
        clarify_operating_cash_stages(book, spec, 'Operating Read Me')
    book.close()
