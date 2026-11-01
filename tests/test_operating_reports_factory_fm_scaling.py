from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import openpyxl
import pytest

from sheets_factory.workbook.operating_reports_200 import factory_fm_scaling as f
from test_operating_reports_200 import toy


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def source():
    spec = importlib.util.spec_from_file_location('_factory_fm_test_source', ROOT/'scripts/build_operating_reports_200_source.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.fixture
def material(tmp_path, source):
    public = toy('reverse_chronology_dashboard'); output = tmp_path/'base'
    source.excel.emit(public, output)
    bindings = json.loads((output/'private_bindings.json').read_text())
    original = json.loads((output/'view_plans.json').read_text())
    goal = output/'source_uncalculated.xlsx'
    definition = source.source_definition(goal, bindings, public)
    return public, bindings, definition, original, goal


def test_twenty_deterministic_plans_retain_full_forecast_and_whole_history_groups(material):
    public, bindings, definition, original, _ = material
    before = deepcopy((public, bindings, definition, original))
    plans = f.design_all(public, bindings, definition, original)
    assert [p['variant_id'] for p in plans] == list(f.VARIANTS)
    assert plans == f.design_all(public, bindings, definition, original)
    assert (public, bindings, definition, original) == before
    growth = {k for k in bindings['financial'] if k.split('/')[1] in (*f.schema.QUARTERS[:4], 'FY2025')
        and k.split('/')[2] in f.GROWTH_FIELDS and bindings['financial'][k]['sheet']+'!'+bindings['financial'][k]['cell'] in definition['formulas']}
    for plan in plans:
        mask = set(plan['mask_keys'])
        assert set(original['FM_mask']) <= mask and growth <= mask
        assert plan['forecast_mask_count'] == len(original['FM_mask'])
        for identity, metric in plan['historical_groups']:
            whole = {k for k in bindings['financial'] if k.split('/')[0] == identity and k.split('/')[2] == metric
                and k.split('/')[1] in (*f.schema.QUARTERS[:4], 'FY2025')
                and bindings['financial'][k]['sheet']+'!'+bindings['financial'][k]['cell'] in definition['formulas']}
            assert whole <= mask
        assert not set(plan['mask_points']) & set(definition['literals'])
        assert not set(plan['mask_points']) & set(definition['provided_financial_inputs'])


@pytest.mark.parametrize('defect', ['missing_forecast', 'duplicate_forecast', 'literal_mask', 'provided_formula', 'unmapped_formula'])
def test_reject_incomplete_or_literal_mask_inputs(material, defect):
    public, bindings, definition, original, _ = material
    if defect == 'missing_forecast': original['FM_mask'].pop()
    elif defect == 'duplicate_forecast': original['FM_mask'].append(original['FM_mask'][0])
    elif defect == 'literal_mask': original['FM_mask'].append(next(k for k in bindings['financial'] if k.endswith('/2025Q1/yoy_percent')))
    elif defect == 'provided_formula': definition['provided_financial_inputs'][next(iter(definition['formulas']))] = {'value': '1'}
    else: definition['formulas']['ReadMe!Z99'] = '=1'
    with pytest.raises(ValueError): f.design(public, bindings, definition, original, 'F01')


def _cells(path):
    result = {}
    with ZipFile(path) as archive:
        for name in archive.namelist():
            if name.startswith('xl/worksheets/sheet') and name.endswith('.xml'):
                tree = ET.fromstring(archive.read(name))
                for cell in tree.iter(f.NS+'c'):
                    result[name, cell.attrib['r']] = ET.tostring(cell)
    return result


def test_emit_changes_exact_mask_cells_preserves_reference_literals_and_other_payload_bytes(material, tmp_path):
    public, bindings, definition, original, goal = material
    plan = f.design(public, bindings, definition, original, 'F07')
    receipt = f.emit(goal, public, bindings, definition, original, plan, tmp_path/'emitted')
    assert (tmp_path/'emitted/reference.xlsx').read_bytes() == goal.read_bytes()
    assert receipt['mask_count'] == plan['mask_count'] and receipt['actual_D_pending']
    before = openpyxl.load_workbook(goal, data_only=False)
    after = openpyxl.load_workbook(tmp_path/'emitted/input.xlsx', data_only=False)
    try:
        changed = set()
        for sheet in before:
            for row in sheet:
                for cell in row:
                    if cell.value != after[sheet.title][cell.coordinate].value:
                        changed.add(sheet.title+'!'+cell.coordinate)
                        assert cell.data_type == 'f' and after[sheet.title][cell.coordinate].value is None
        assert changed == set(plan['mask_points'])
    finally:
        before.close(); after.close()
    before_cells = _cells(goal); after_cells = _cells(tmp_path/'emitted/input.xlsx')
    assert len([k for k in before_cells if before_cells[k] != after_cells[k]]) == plan['mask_count']
    with ZipFile(goal) as a, ZipFile(tmp_path/'emitted/input.xlsx') as b:
        assert a.namelist() == b.namelist()
        for name in a.namelist():
            if name not in receipt['changed_package_members']: assert a.read(name) == b.read(name)
    assert receipt['native_calls'] == receipt['model_calls'] == 0 and receipt['qualified'] is False


def test_cache_and_boolean_cell_mask_does_not_leave_a_value_or_change_neighbor():
    raw = ('<worksheet xmlns="'+f.NS[1:-1]+'"><sheetData><row r="1">'
        '<c r="A1" s="2" t="b"><f>1=1</f><v>1</v></c>'
        '<c r="B1" s="3"><f>2+2</f><v>4</v></c>'
        '<c r="C1" t="inlineStr"><is><t>n/a (no comparative)</t></is></c>'
        '</row></sheetData></worksheet>').encode()
    changed, n = f._masked_sheet(raw, 'Report', {'Report!A1'}, {'formulas': {'Report!A1': '=1=1'}})
    tree = ET.fromstring(changed); a, b, c = list(tree.iter(f.NS+'c'))
    assert n == 1 and a.attrib == {'r': 'A1', 's': '2'} and len(a) == 0
    assert b.find(f.NS+'f').text == '2+2' and b.find(f.NS+'v').text == '4'
    assert c.find(f.NS+'is').find(f.NS+'t').text == 'n/a (no comparative)'
    assert b'<c r="B1" s="3"><f>2+2</f><v>4</v></c>' in changed


def test_prefixed_sheet_and_self_closing_neighbor_are_not_swallowed():
    raw = (b'<ns0:worksheet xmlns:ns0="'+f.NS[1:-1].encode()+b'">'
        b'<ns0:c r="A1" s="2"/><ns0:c r="B1"><ns0:f>3*7</ns0:f><ns0:v>21</ns0:v></ns0:c>'
        b'</ns0:worksheet>')
    result, count = f._masked_sheet(raw, 'Report', {'Report!B1'}, {'formulas': {'Report!B1': '=3*7'}})
    assert count == 1 and b'<ns0:c r="A1" s="2"/>' in result
    cells = list(ET.fromstring(result).iter(f.NS+'c'))
    assert [c.attrib['r'] for c in cells] == ['A1', 'B1'] and len(cells[1]) == 0


def test_dependency_closure_includes_division_range_and_escaped_sheet_consumers():
    physical = {'E/2025Q1/revenue': "Owner's report!A1",
        'E/2025Q1/net_margin_percent': "Owner's report!B1", 'DIV/2025Q1/net_income': 'Division!C1'}
    groups = {('E', 'revenue'): ['E/2025Q1/revenue'],
        ('E', 'net_margin_percent'): ['E/2025Q1/net_margin_percent'], ('DIV', 'net_income'): ['DIV/2025Q1/net_income']}
    definition = {'formulas': {"Owner's report!A1": '=100',
        "Owner's report!B1": "=10/'Owner''s report'!A1", 'Division!C1': "=SUM('Owner''s report'!A1:B1)"}}
    closure, direct, parsed = f._dependency_groups(definition, physical, set(physical), groups)
    assert parsed == 2
    assert closure['E', 'revenue'] == set(groups)
    assert closure['E', 'net_margin_percent'] == {('E', 'net_margin_percent'), ('DIV', 'net_income')}
    assert direct['E', 'revenue'] == {('E', 'net_margin_percent'), ('DIV', 'net_income')}


@pytest.mark.parametrize('problem', ['wrong_formula', 'absent_target', 'literal_target'])
def test_package_mask_requires_the_exact_original_formula(problem):
    raw = b'<worksheet><c r="A1"><f>1+1</f><v>2</v></c></worksheet>'
    points = {'Report!A2'} if problem == 'absent_target' else {'Report!A1'}
    if problem == 'literal_target': raw = b'<worksheet><c r="A1"><v>2</v></c></worksheet>'
    with pytest.raises(ValueError):
        f._masked_sheet(raw, 'Report', points, {'formulas': {'Report!A1': '=9' if problem == 'wrong_formula' else '=1+1'}})


def test_emit_rejects_edited_plan_and_existing_directory(material, tmp_path):
    public, bindings, definition, original, goal = material
    plan = f.design(public, bindings, definition, original, 'F01')
    corrupt = deepcopy(plan); corrupt['mask_points'].pop()
    with pytest.raises(ValueError): f.emit(goal, public, bindings, definition, original, corrupt, tmp_path/'bad')
    assert not (tmp_path/'bad').exists()
    with pytest.raises(ValueError): f.emit(goal, public, bindings, definition, original, plan, tmp_path)
