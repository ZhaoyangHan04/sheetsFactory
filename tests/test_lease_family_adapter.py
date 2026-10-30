from pathlib import Path
from decimal import Decimal
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import openpyxl
from openpyxl.worksheet.formula import ArrayFormula
import pytest

from sheets_factory.task_adapters.lease_family import (
    MAIN, NS, discover_families, present_active_schedules,
    propose_debugging_task, compare_exact_typed, _paths, _mutate,
)
from sheets_factory.task_adapters.presentation_source import verify_formula_allowlist, project_lease_zero_bindings


def fixture_book(tmp_path, *, bool_zero=False, date_zero=False, donor=False):
    path = tmp_path / 'original.xlsx'
    w = openpyxl.Workbook()
    w.active.title = 'Cover'
    w.active['A1'] = 'Unchanged published context'
    w.active['B1'] = 123.456789
    inputs = w.create_sheet('Lease Inputs')
    inputs['A5'], inputs['C5'] = 'lease id', 'P01'
    calendar = w.create_sheet('Lease Calendar')
    for c in range(3, 7):
        calendar.cell(2, c, c-2)
    w.create_sheet('Lease Read Me')['A1'] = 'Public business policies and contract definitions.'
    s = w.create_sheet('Lease P01')
    labels = {3: 'active flag', 14: 'annual discount rate', 15: 'lease monthly discount rate',
              16: 'lease current end month', 23: 'lease pv at measurement',
              27: 'rou after measurement', 28: 'liability after measurement',
              30: 'lease book depreciation', 31: 'lease book interest', 32: 'nominal contract payment'}
    values = {}
    for r, label in labels.items():
        s.cell(r, 1, label)
    for col in range(3, 7):
        c = openpyxl.utils.get_column_letter(col)
        for r in (3, 14, 15, 16, 27, 28):
            s.cell(r, col, 1 if r == 3 else 10)
        formulas = {
            23: f'=IF({c}3=1,ROUND(100/(1+{c}15)^(4-{c}$2+1),2),0)',
            30: f'=IF({c}3=1,IF({c}$2={c}16,{c}27,MIN({c}27,10)),0)',
            31: f'=IF({c}3=1,ROUND({c}28*{c}15,2),0)',
            32: f"=IF({c}3=1,ROUND('Lease Inputs'!$C$9*ROUND(12,2),2),0)",
        }
        for r, f in formulas.items():
            s.cell(r, col, f)
            values[s.cell(r, col).coordinate] = (100 if r == 23 and col == 3 else
                0 if (r == 23 or col == 6) else 10 if r == 30 else 1 if r == 31 else 12)
    if date_zero:
        s['F31'].number_format = 'yyyy-mm-dd'
    if donor:
        other = w.create_sheet('Other')
        other['C31'] = ArrayFormula(ref='C31', text='=IF(C3=1,ROUND(C28*C15,2),0)')
    w.save(path)
    w.close()
    rewritten = tmp_path / 'cached.xlsx'
    with ZipFile(path) as zin, ZipFile(rewritten, 'x') as zout:
        paths = _paths(zin)
        for info in zin.infolist():
            raw = zin.read(info.filename)
            if info.filename == paths['Lease P01']:
                root = ET.fromstring(raw)
                for cell in root.findall('.//m:sheetData/m:row/m:c', NS):
                    if cell.get('r') not in values:
                        continue
                    v = cell.find('m:v', NS)
                    if v is None:
                        v = ET.SubElement(cell, '{' + MAIN + '}v')
                    v.text = str(values[cell.get('r')])
                    if bool_zero and cell.get('r') == 'F31':
                        cell.set('t', 'b')
                raw = ET.tostring(root)
            zout.writestr(info, raw)
    return rewritten


def test_complete_family_presentation_keeps_all_other_parts_and_values(tmp_path):
    source = fixture_book(tmp_path)
    target = tmp_path / 'presented.xlsx'
    receipt = present_active_schedules(source, target)
    assert receipt['converted_formula_count'] == 6
    assert receipt['selected_for_tasks'] is False
    assert compare_exact_typed(source, target, public_note=receipt['public_note'])['passed'] is True
    allowlist = verify_formula_allowlist(source, target, receipt['conversions'])
    assert allowlist['passed'] is True
    assert allowlist['removed_zero_formula_count'] == 6
    with ZipFile(source) as a, ZipFile(target) as b:
        for name in a.namelist():
            if name not in receipt['changed_package_parts']:
                assert a.read(name) == b.read(name)
    w = openpyxl.load_workbook(target)
    assert w['Lease P01']['F31'].value == 0
    assert w['Lease P01']['F31'].data_type != 'f'
    assert w['Lease P01']['C31'].data_type == 'f'
    w.close()


def test_every_remaining_family_member_is_a_root_and_no_donor_survives(tmp_path):
    source = fixture_book(tmp_path)
    target = tmp_path / 'presented.xlsx'
    present_active_schedules(source, target)
    plan = propose_debugging_task(target)
    assert len(plan['edits']) == 10
    assert plan['family_adapter']['counts_by_family'] == {
        'measurement_pv': 1, 'depreciation': 3, 'interest': 3, 'nominal_payment': 3}
    assert plan['family_adapter']['correct_full_template_donors_remaining'] == 0
    assert plan['family_adapter']['status'] == 'planned_not_activity_proven'
    assert all(e['before'] != e['after'] for e in plan['edits'])
    assert all(not e['after'].startswith('=ROUND((' + e['before'][1:]) for e in plan['edits'])


def test_unmaterialized_zeros_fail_instead_of_silently_dropping_roots(tmp_path):
    source = fixture_book(tmp_path)
    with pytest.raises(ValueError, match='unpresented zero'):
        propose_debugging_task(source)


@pytest.mark.parametrize('kwargs', [{'bool_zero': True}, {'date_zero': True}])
def test_boolean_and_date_zeros_are_not_monetary_presentation_inputs(tmp_path, kwargs):
    source = fixture_book(tmp_path, **kwargs)
    with pytest.raises(ValueError, match='Finite numeric monetary'):
        present_active_schedules(source, tmp_path / 'bad.xlsx')


def test_correct_array_donor_on_another_sheet_rejects_the_task(tmp_path):
    source = fixture_book(tmp_path, donor=True)
    target = tmp_path / 'presented.xlsx'
    present_active_schedules(source, target)
    with pytest.raises(ValueError, match='correct family template remains'):
        propose_debugging_task(target)


def test_root_bound_rejects_complete_family_instead_of_truncating(tmp_path):
    source = fixture_book(tmp_path)
    target = tmp_path / 'presented.xlsx'
    present_active_schedules(source, target)
    with pytest.raises(ValueError, match='configured bound'):
        propose_debugging_task(target, {'max_roots': 9})


def test_exact_value_transfer_does_not_round_subcent_values(tmp_path):
    a, b = tmp_path / 'a.xlsx', tmp_path / 'b.xlsx'
    w = openpyxl.Workbook()
    w.active['A1'] = 0.001
    w.save(a)
    w.active['A1'] = 0.002
    w.save(b)
    w.close()
    assert compare_exact_typed(a, b)['passed'] is False


def test_zero_projection_requires_fresh_independent_zero_and_complete_bindings():
    binding = {'cell_bindings': [
        {'sheet': 'Lease P01', 'cell': 'C31', 'source': ['lease_monthly', 'P01', 1, 'interest']}],
        'literal_controls': []}
    conversions = [{'sheet': 'Lease P01', 'cell': 'C31'}]
    ledger = {'lease_monthly': {'P01': [{'interest': Decimal('0.00')}]}}
    projected, checks = project_lease_zero_bindings(binding, conversions, ledger)
    assert projected['cell_bindings'] == []
    assert projected['literal_controls'] == [{'sheet': 'Lease P01', 'cell': 'C31', 'value': 0}]
    assert len(checks) == 1 and len(binding['cell_bindings']) == 1
    ledger['lease_monthly']['P01'][0]['interest'] = Decimal('0.01')
    with pytest.raises(ValueError, match='nonzero'):
        project_lease_zero_bindings(binding, conversions, ledger)
    ledger['lease_monthly']['P01'][0]['interest'] = Decimal('0.00')
    with pytest.raises(ValueError, match='Every presented zero'):
        project_lease_zero_bindings(binding, conversions + [{'sheet': 'Lease P01', 'cell': 'D31'}], ledger)


@pytest.mark.parametrize('families', [[], ['unknown'], ['interest', 'interest']])
def test_family_selection_is_explicit_and_unique(tmp_path, families):
    source = fixture_book(tmp_path)
    w = openpyxl.load_workbook(source)
    try:
        with pytest.raises(ValueError, match='family selection'):
            discover_families(w, {'families': families})
    finally:
        w.close()


def test_zero_rate_contract_uses_a_payment_unit_error_not_a_harmless_timing_error():
    w = openpyxl.Workbook()
    c = w.active['AA23']
    c.value = "=IF(AA6=1,ROUND(SUMPRODUCT(100*'Lease Inputs'!$F$9)/(1+AA15)^(240-AA$2+1),2),0)"
    context = {'monthly_rate': 15}
    policy = {'profile': 'contract_conditioned_v2', 'annual_rate': 0,
              'payment_frequency': 6, 'input_column': 6}
    wrong = _mutate('measurement_pv', c, context, policy)
    assert "*'Lease Inputs'!$F$9" not in wrong
    assert '^(240-AA$2+1)' in wrong
    assert round(100 * 6 / (1 + 0) ** 216, 2) != round(100 / (1 + 0) ** 216, 2)
    c = w.active['AF32']
    c.value = "=IF(AF3=1,ROUND('Lease Inputs'!$F$9*ROUND(35000,2),2),0)"
    assert _mutate('nominal_payment', c, context, policy) == '=IF(AF3=1,ROUND(ROUND(35000,2),2),0)'
    w.close()


def test_v2_declares_nominal_interest_shortcut_and_preserves_positive_rate_timing():
    w = openpyxl.Workbook()
    context = {'active': 3, 'liability': 28, 'annual_rate': 14, 'monthly_rate': 15}
    c = w.active['C31']
    c.value = '=IF(C3=1,ROUND(C28*C15,2),0)'
    assert _mutate('interest', c, context, {'profile': 'contract_conditioned_v2'}) == '=IF(C3=1,ROUND(C28*C14/12,2),0)'
    assert _mutate('interest', c, context) == '=IF(C3=1,ROUND(C28*C14,2),0)'
    c = w.active['C23']
    c.value = '=IF(C6=1,ROUND(100/(1+C15)^(240-C$2+1),2),0)'
    result = _mutate('measurement_pv', c, context,
        {'profile': 'contract_conditioned_v2', 'annual_rate': .06, 'payment_frequency': 1, 'input_column': 3})
    assert '^(240-C$2)' in result
    w.close()


def test_zero_rate_monthly_contract_rejects_instead_of_dropping_a_root():
    w = openpyxl.Workbook()
    c = w.active['C32']
    c.value = "=ROUND('Lease Inputs'!$C$9*ROUND(35000,2),2)"
    with pytest.raises(ValueError, match='multi-month'):
        _mutate('nominal_payment', c, {}, {'profile': 'contract_conditioned_v2',
            'annual_rate': 0, 'payment_frequency': 1, 'input_column': 3})
    w.close()


def test_unknown_mutation_profile_rejects(tmp_path):
    source = fixture_book(tmp_path)
    w = openpyxl.load_workbook(source)
    try:
        with pytest.raises(ValueError, match='mutation profile'):
            discover_families(w, {'mutation_profile': 'invented'})
    finally:
        w.close()
