"""Reference isolation and provenance safeguards for composed financial inputs."""
from datetime import datetime
import hashlib
import json

import openpyxl
import pytest

from sheets_factory.workbook.composite_finance.operating import checked_json, rewrite_formula
from sheets_factory.workbook.composite_finance.build import emit_public_specs, PUBLIC_SHEET
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
