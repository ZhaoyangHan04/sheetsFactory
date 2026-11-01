"""Public policy, encoded feeds and cold formula coverage in rendered cases."""
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from openpyxl import load_workbook
import pytest

from sheets_factory.workbook.associate_bridge_v1 import spec, excel

HELPERS = Path(__file__).with_name('test_associate_bridge_oracle_b.py')
loader = importlib.util.spec_from_file_location('_bridge_excel_test_inputs', HELPERS)
fixture = importlib.util.module_from_spec(loader); loader.loader.exec_module(fixture)


@pytest.mark.parametrize('case', ('B01', 'B04', 'B05'))
def test_policy_feed_units_cash_receipts_and_cold_scope(tmp_path, case):
    base = fixture.public(fixture.entity(), fixture.entity('E002', layout='quarter_rows',
        money_unit='GBP_thousands', statement_sign='signed_contributions'))['base']
    public = spec.build(base, case)
    receipt = excel.emit(public, tmp_path/'emitted')
    bindings = json.loads(Path(receipt['bindings']['path']).read_text())
    workbook = load_workbook(tmp_path/'emitted/source_uncalculated.xlsx', data_only=False)
    try:
        assert len(workbook.sheetnames) == 6
        assert 'charge/(credit)' in workbook['ReadMe']['A5'].value.lower()
        assert 'Capital returns do not create income' in workbook['ReadMe']['A6'].value
        for identity, policy in public['policies'].items():
            for period in spec.QUARTERS:
                for field, expected in [('associate_results', policy['share_postings'][period]),
                                        ('investment_cash_receipt', policy['cash_receipts'][period])]:
                    item = bindings['provided_facts'][identity+'/'+field+'/'+period]
                    cell = workbook[item['sheet']][item['cell']]
                    assert float(cell.value) == float(expected)
                    assert 'income-positive result' not in workbook[item['sheet']].cell(cell.row, 1).value
            row = bindings['financial'][identity+'/2026Q1/operating_cash_flow']
            formula = workbook[row['sheet']][row['cell']].value
            cash = bindings['provided_facts'][identity+'/investment_cash_receipt/2026Q1']
            assert cash['cell'] in formula
        formulas = sum(c.data_type == 'f' for ws in workbook for c in ws._cells.values())
        assert formulas == receipt['formulas']
    finally:
        workbook.close()
    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    with ZipFile(tmp_path/'emitted/source_uncalculated.xlsx') as archive:
        count = 0
        for name in archive.namelist():
            if not name.startswith('xl/worksheets/') or not name.endswith('.xml'):
                continue
            for cell in ET.fromstring(archive.read(name)).iter(ns+'c'):
                if cell.find(ns+'f') is not None:
                    value = cell.find(ns+'v')
                    assert value is None or not value.text
                    count += 1
        assert count == formulas


def test_cost_capital_return_formula_does_not_recognize_income(tmp_path):
    public = spec.build(fixture.public()['base'], 'B05')
    # B05 E001 is equity; E002 is cost. Include both and test one capital event.
    base = fixture.public(fixture.entity(), fixture.entity('E002'))['base']
    public = spec.build(base, 'B05'); excel.emit(public, tmp_path/'emitted')
    b = json.loads((tmp_path/'emitted/private_bindings.json').read_text())
    wb = load_workbook(tmp_path/'emitted/source_uncalculated.xlsx', data_only=False)
    try:
        policy = public['policies']['E002']; assert policy['method'] == 'cost'
        period = next(p for p in spec.QUARTERS[4:] if policy['receipt_kind'][p] == 'capital_return')
        item = b['financial']['E002/'+period+'/associate_income']
        assert wb[item['sheet']][item['cell']].value == '=0'
        item = b['financial']['E002/'+period+'/closing_investment']
        cash = b['provided_facts']['E002/investment_cash_receipt/'+period]
        assert '-'+"'"+cash['sheet']+"'!"+cash['cell'] in wb[item['sheet']][item['cell']].value
    finally:
        wb.close()
