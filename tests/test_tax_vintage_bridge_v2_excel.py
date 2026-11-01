"""Business boundaries in cold tax schedules before independent native audits."""
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from openpyxl import load_workbook
import pytest
from sheets_factory.workbook.associate_bridge_v1 import spec as bridge
from sheets_factory.workbook.tax_vintage_bridge_v2 import spec, excel

loader = importlib.util.spec_from_file_location('_vintage_excel_inputs',Path(__file__).with_name('test_associate_bridge_oracle_b.py'))
fixture = importlib.util.module_from_spec(loader); loader.loader.exec_module(fixture)


def public(case='T01'):
    base = fixture.public(fixture.entity(), fixture.entity('E002',money_unit='GBP_thousands',layout='quarter_rows'))['base']
    return spec.build(bridge.build(base,spec.bridge_case(case)),case)


@pytest.fixture
def rendered(tmp_path):
    p = public(); receipt = excel.emit(p,tmp_path/'emitted')
    b = json.loads(Path(receipt['bindings']['path']).read_text())
    wb = load_workbook(tmp_path/'emitted/source_uncalculated.xlsx',data_only=False)
    yield p, receipt, b, wb, tmp_path/'emitted/source_uncalculated.xlsx'
    wb.close()


def test_complete_scope_and_no_seeded_reference_caches(rendered):
    p, receipt, b, wb, path = rendered
    assert set(b['financial']) == set(dict(spec.points(p)))
    assert receipt['formulas'] == sum(t != 'text' for _,t in spec.points(p))
    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    with ZipFile(path) as archive:
        formulas = 0
        for name in archive.namelist():
            if name.startswith('xl/worksheets/') and name.endswith('.xml'):
                for target in ET.fromstring(archive.read(name)).iter(ns+'c'):
                    if target.find(ns+'f') is not None:
                        formulas += 1
                        cached = target.find(ns+'v')
                        assert cached is None or not cached.text
        assert formulas == receipt['formulas']


def test_origin_fifo_expiry_last_quarter_and_birth_no_use(rendered):
    p, _, b, wb, _ = rendered
    def value(period,field):
        point = b['financial']['E001/'+period+'/'+field]
        return wb[point['sheet']][point['cell']].value
    def address(period,field):
        return b['financial']['E001/'+period+'/'+field]['cell']
    expiry = b['provided_facts']['E001/tax_opening_O01_last_eligible_index']['cell']
    formula = value('2025Q1','tax_lot_O01_ordinary_used')
    assert '=MIN(IF(0<=' in formula and expiry in formula
    # Even though O04 is displayed above O01, its utilization follows O01, O02, O03.
    formula = value('2025Q1','tax_lot_O04_ordinary_used')
    assert all(address('2025Q1','tax_lot_O0'+str(j)+'_ordinary_used') in formula for j in (1,2,3))
    assert value('2026Q1','tax_lot_C04_investment_used') == '=0'
    assert address('2026Q1','loss_investment_created') in value('2026Q1','tax_lot_C04_investment_close')


def test_assessment_lag_is_locked_before_effective_term_switch(rendered):
    p, _, b, wb, _ = rendered
    policy = p['tax_policies']['E001']; assert policy['terms'][0]['cash_tax_lag'] == 1
    assert policy['terms'][1]['effective_index'] == 6 and policy['terms'][1]['cash_tax_lag'] == 2
    target = b['financial']['E001/2026Q3/cash_tax_paid']
    formula = wb[target['sheet']][target['cell']].value
    old_assessment = b['financial']['E001/2026Q2/current_tax']['cell']
    current_lag_wrong_assessment = b['financial']['E001/2026Q1/current_tax']['cell']
    assert old_assessment in formula
    assert current_lag_wrong_assessment not in formula
    payable = b['financial']['E001/2027Q4/tax_payable_close']
    liability = b['financial']['E001/2027Q4/total_liabilities_equity']
    assert payable['cell'] in wb[liability['sheet']][liability['cell']].value


def test_public_treatment_replaces_conflicting_original_tax_terms(rendered):
    _, _, _, wb, _ = rendered
    text = '\n'.join(str(row[0]) for row in wb['ReadMe'].iter_rows(values_only=True) if row[0])
    assert 'no loss credit, carryforward or deferred tax' not in text
    assert 'current parent tax settle within their quarter' not in text
    assert 'Later lag changes do not reschedule earlier assessments' in text
    assert 'two pools do not offset each other' in text
