"""Large mask proposals remain asserted, bounded edits of real formulas."""
from copy import deepcopy
import hashlib

from openpyxl import Workbook, load_workbook
import pytest

from sheets_factory.core.node import TaskRejected
from sheets_factory.nodes.construction import compile_mask_ranges, construction_contract


def source(tmp_path, rows=8):
    path = tmp_path / 'source.xlsx'
    book = Workbook()
    book.active.title = 'Forecast'
    book.create_sheet('Inputs')['B1'] = 100
    for row in range(1, rows+1):
        book['Forecast'].cell(row, 1, f'Period {row}')
        book['Forecast'].cell(row, 2, f'=Inputs!B1*{row}')
    book.save(path)
    return path


def proposal(region='A1:C8'):
    return {'edits': [], 'mask_ranges': [{'sheet': 'Forecast', 'range': region,
        'reason': 'Restore the complete multi-period forecast block',
        'business_rule': 'The public period inputs determine each forecast.'}]}


def test_expansion_preserves_source_literals_and_asserts_each_actual_formula(tmp_path):
    path = source(tmp_path)
    original = path.read_bytes()
    draft = proposal()
    compiled = compile_mask_ranges(draft, path, 'financial_modeling')
    assert path.read_bytes() == original
    assert draft == proposal()
    assert [e['cell'] for e in compiled['edits']] == [f'B{i}' for i in range(1, 9)]
    assert [e['before'] for e in compiled['edits']] == [f'=Inputs!B1*{i}' for i in range(1, 9)]
    assert all(e['after'] is None for e in compiled['edits'])
    assert compiled['range_authoring_receipt']['baseline_sha256'] == hashlib.sha256(original).hexdigest()
    assert 'mask_ranges' not in compiled
    assert compile_mask_ranges(compiled, path, 'financial_modeling') == compiled
    book = load_workbook(path)
    assert book['Forecast']['A1'].value == 'Period 1' and book['Forecast']['C1'].value is None
    assert book['Inputs']['B1'].value == 100
    book.close()


def test_large_block_requires_explicit_config_instead_of_changing_old_limits(tmp_path):
    path = source(tmp_path, 100)
    draft = proposal('B1:B100')
    with pytest.raises(TaskRejected, match='maximum=80'):
        compile_mask_ranges(draft, path, 'financial_modeling')
    config = {'construction': {'max_edit_count': {'financial_modeling': 128}}}
    compiled = compile_mask_ranges(draft, path, 'financial_modeling', config)
    assert len(compiled['edits']) == 100
    assert construction_contract()['modes']['financial_modeling']['edit_count']['max'] == 80
    assert construction_contract(config=config)['modes']['financial_modeling']['edit_count']['max'] == 128


@pytest.mark.parametrize('region', ['B0:B3', 'B1:B1048577', 'B1:XFD1048576', 'B3:B1', 'Other!B1:B8', 'A1:A8'])
def test_invalid_or_empty_formula_ranges_cannot_reach_mutation(tmp_path, region):
    path = source(tmp_path)
    before = path.read_bytes()
    with pytest.raises(TaskRejected):
        compile_mask_ranges(proposal(region), path, 'financial_modeling')
    assert path.read_bytes() == before


def test_overlap_and_debugging_range_proposals_are_rejected(tmp_path):
    path = source(tmp_path)
    draft = proposal('B1:B4')
    draft['mask_ranges'].append(deepcopy(draft['mask_ranges'][0]))
    with pytest.raises(TaskRejected, match='overlap'):
        compile_mask_ranges(draft, path, 'financial_modeling')
    with pytest.raises(TaskRejected, match='financial-modeling'):
        compile_mask_ranges(proposal(), path, 'debugging')


@pytest.mark.parametrize('maximum', [0, 5, 4097, True, '800'])
def test_malformed_runtime_limits_are_configuration_errors(maximum):
    with pytest.raises(ValueError):
        construction_contract(config={'construction': {'max_edit_count': {'financial_modeling': maximum}}})
