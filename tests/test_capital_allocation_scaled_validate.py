"""Offline complete-scope audit checks; none are actual LibreOffice evidence."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import openpyxl
import pytest

from sheets_factory.workbook.capital_allocation_scaled.excel import emit_capital_allocation_workbook, PUBLIC_RULES
from sheets_factory.workbook.capital_allocation_scaled.ledger import simulate
from sheets_factory.workbook.capital_allocation_scaled.spec import project_ids
from sheets_factory.workbook.capital_allocation_scaled.validate import (
    audit_capital_allocation_workbook, expected_cells, _reference, _formula_tokens,
)

ROOT = Path(__file__).resolve().parents[1]
_module = importlib.util.spec_from_file_location('_scaled_audit_hand_cases', ROOT / 'tests/test_capital_allocation_ledger.py')
hand = importlib.util.module_from_spec(_module)
_module.loader.exec_module(hand)


def make(count=30):
    spec = hand.specification()
    for index in range(18, count):
        p = deepcopy(spec['projects'][0])
        p['id'] = f'P{index + 1:02d}'
        spec['projects'].append(p)
    plan = {pid: int(pid == f'P{count:02d}') for pid in project_ids(count)}
    book = openpyxl.Workbook()
    book.remove(book.active)
    bindings = emit_capital_allocation_workbook(book, spec, plan)
    return spec, plan, book, bindings, simulate(spec, plan)


@pytest.mark.parametrize('count', (26, 28, 30))
def test_every_new_candidate_and_decision_is_independently_covered(count):
    spec, plan, book, bindings, journal = make(count)
    try:
        values = expected_cells(spec, plan, journal, bindings)
        formulas = [cell for sheet in book for cell in sheet._cells.values() if cell.data_type == 'f']
        assert len(formulas) == bindings['formula_count']
        assert all(_reference(cell.parent.title, cell.coordinate) in values for cell in formulas)
        assert len(bindings['decision_bindings']) == count
        assert bindings['public_rules'] == list(PUBLIC_RULES)
        for sid in ('S01', 'S02', 'S03'):
            for pid in ('P01', f'P{count:02d}'):
                row = next(b for b in bindings['financial_bindings'] if b['expected_path'] ==
                           ['scenarios', sid, 'project_flows', pid, 1, 'revenue'])
                assert values[_reference(row['sheet'], row['cell'])] == 80
            assert journal['scenarios'][sid]['annual'][1]['revenue'] == 80
        assert journal['objective_pence'] == 40
    finally:
        book.close()


@pytest.mark.parametrize('kind', ('tail_project', 'decision', 'duplicate', 'arithmetic_definition'))
def test_full_scope_or_support_definition_corruption_rejected(kind):
    spec, plan, book, binding, journal = make()
    try:
        if kind == 'tail_project':
            binding['financial_bindings'] = [b for b in binding['financial_bindings']
                if not ('project_flows' in b['expected_path'] and 'P30' in b['expected_path'])]
        elif kind == 'decision':
            binding['decision_bindings'].pop()
        elif kind == 'duplicate':
            binding['financial_bindings'].append(binding['financial_bindings'][0])
        else:
            binding['arithmetic_bindings'][0]['formula'] += '+1'
        with pytest.raises(ValueError):
            expected_cells(spec, plan, journal, binding)
    finally:
        book.close()


def test_unrecalculated_formula_file_cannot_be_a_passed_cache_audit(tmp_path):
    spec, plan, book, binding, journal = make()
    path = tmp_path / 'not-recalculated.xlsx'
    book.save(path)
    book.close()
    report = audit_capital_allocation_workbook(path, spec, plan, journal, binding)
    assert report['passed'] is False
    assert report['mismatches']
    assert report['all_formula_cells_independently_covered'] is True
    assert report['decision_formula_count'] == 30
    assert report['optimality_or_uniqueness_certified'] is False


def test_rule_or_literal_changes_remain_audit_failures_without_rewriting_reference(tmp_path):
    spec, plan, book, binding, journal = make(26)
    rule = binding['public_rule_cells'][-1]
    book[rule['sheet']][rule['cell']] = 'Altered public reporting convention'
    path = tmp_path / 'changed-public-contract.xlsx'
    book.save(path)
    book.close()
    report = audit_capital_allocation_workbook(path, spec, plan, journal, binding)
    assert report['passed'] is False
    assert any(c.get('reason') == 'The public accounting rules differ' for c in report['control_mismatches'])
    assert any(c.get('reason') == 'A supplied literal or calendar changed' for c in report['control_mismatches'])


def test_scientific_notation_token_equivalence_preserves_exact_integer_coefficients():
    assert _formula_tokens('=A1*1E+018') == _formula_tokens('=A1*1000000000000000000')
    assert _formula_tokens('=A1*1000000000000000001') != _formula_tokens('=A1*1E+018')
