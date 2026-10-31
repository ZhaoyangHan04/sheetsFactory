from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def fixture_cache(source_path, target, typed_values):
    """Explicit unit-test caches, never evidence of a native calculation."""
    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    with ZipFile(source_path) as original, ZipFile(target, 'x', ZIP_DEFLATED) as output:
        book = ET.fromstring(original.read('xl/workbook.xml'))
        rels = {row.attrib['Id']: row.attrib['Target'] for row in ET.fromstring(original.read('xl/_rels/workbook.xml.rels'))}
        parts = {}
        for sheet in book.find(ns + 'sheets'):
            part = rels[sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']]
            parts[part.lstrip('/') if part.startswith('/') else 'xl/' + part] = sheet.attrib['name']
        for item in original.infolist():
            data = original.read(item.filename)
            if item.filename in parts:
                tree = ET.fromstring(data)
                for cell in tree.iter(ns + 'c'):
                    if cell.find(ns + 'f') is None: continue
                    for value in list(cell.findall(ns + 'v')): cell.remove(value)
                    point = parts[item.filename] + '!' + cell.attrib['r']
                    if point not in typed_values: continue
                    row = typed_values[point]
                    if row['type'] == 'boolean': cell.attrib['t'] = 'b'; value = str(int(row['value']))
                    else: cell.attrib['t'] = 'n'; value = row['value']
                    ET.SubElement(cell, ns + 'v').text = value
                data = ET.tostring(tree)
            output.writestr(item, data)


@pytest.fixture(scope='module')
def task():
    return load(ROOT / 'scripts/validate_operating_reports_200_tasks.py', '_test_fixed200_task8')


@pytest.fixture
def sample(task, tmp_path):
    helper = load(ROOT / 'tests/test_operating_reports_200.py', '_fixed200_task8_public_fixture')
    public = helper.toy(); directory = tmp_path / 'emission'; task.source.excel.emit(public, directory)
    bindings = json.loads((directory / 'private_bindings.json').read_text())
    plans = json.loads((directory / 'view_plans.json').read_text())
    expected, _ = task.source.crosscheck(public, bindings)
    definition = task.source.source_definition(directory / 'source_uncalculated.xlsx', bindings, public)
    definition['FM_mask_points'] = sorted(bindings['financial'][key]['sheet'] + '!' + bindings['financial'][key]['cell'] for key in plans['FM_mask'])
    definition['DBG_root_points'] = sorted(row['sheet'] + '!' + row['cell'] for row in plans['DBG_faults'].values())
    goal = tmp_path / 'mock_goal.xlsx'; fixture_cache(directory / 'source_uncalculated.xlsx', goal, expected)
    return public, directory, bindings, plans, expected, definition, goal


def test_forecast_inventory_is_business_derived_and_omits_NA(task, sample):
    public, _, _, plans, _, _, _ = sample
    assert task.forecast_keys(public) == set(plans['FM_mask'])
    assert all('/2025' not in key and '/FY2025' not in key for key in task.forecast_keys(public))
    assert 'E001/FY2027/distribution_eligible' in task.forecast_keys(public)
    assert 'PORTFOLIO/FY2027/distribution_eligible' not in task.forecast_keys(public)


def fm_input(task, sample, path):
    _, directory, _, _, expected, definition, _ = sample
    fixture_cache(directory / 'financial_modeling_input.xlsx', path,
                  {key: value for key, value in expected.items() if key not in definition['FM_mask_points']})


def test_FM_preserves_all_history_and_nonapplicable_values(task, sample, tmp_path):
    *_, expected, definition, _ = sample; path = tmp_path / 'fm.xlsx'; fm_input(task, sample, path)
    task.verify_definitions(path, definition, blank=True)
    task.verify_input_caches(path, expected, blank=True, definition=definition)
    observed = task.snapshot(path, expected)['values']
    assert all(point not in observed for point in definition['FM_mask_points'])
    assert all(observed[point] == value for point, value in expected.items() if point not in definition['FM_mask_points'])


def test_FM_rejects_missing_historical_cache(task, sample, tmp_path):
    _, directory, _, _, expected, definition, _ = sample
    history = next(point for point in definition['formulas'] if point not in definition['FM_mask_points'])
    caches = {point: value for point, value in expected.items() if point not in definition['FM_mask_points'] and point != history}
    path = tmp_path / 'missing_history.xlsx'; fixture_cache(directory / 'financial_modeling_input.xlsx', path, caches)
    with pytest.raises(ValueError, match='historical'): task.verify_input_caches(path, expected, blank=True, definition=definition)


def test_FM_rejects_an_unmasked_forecast_formula(task, sample, tmp_path):
    _, _, _, _, _, definition, goal = sample
    path = tmp_path / 'partly_masked.xlsx'
    missing = definition['FM_mask_points'][0]
    actions = {tuple(point.rsplit('!', 1)): ('blank', None) for point in definition['FM_mask_points'] if point != missing}
    task.transform(goal, path, actions)
    with pytest.raises(ValueError, match='formula scope'): task.verify_definitions(path, definition, blank=True)


@pytest.mark.parametrize('change', ['NA', 'given_fact', 'label'])
def test_task_protection_covers_NA_facts_and_labels(task, sample, tmp_path, change):
    _, directory, bindings, _, _, definition, _ = sample
    if change == 'NA': point = next(p for p, row in definition['literals'].items() if row['type'] == 'text' and row['value'].startswith('n/a'))
    elif change == 'given_fact':
        row = next(iter(bindings['provided_facts'].values())); point = row['sheet'] + '!' + row['cell']
    else: point = 'ReadMe!A1'
    path = tmp_path / ('changed_' + change + '.xlsx')
    task.transform(directory / 'financial_modeling_input.xlsx', path, {tuple(point.rsplit('!', 1)): ('text', 'changed')})
    with pytest.raises(ValueError, match='Provided'): task.verify_definitions(path, definition, blank=True)


def test_DBG_requires_every_root_to_have_primary_value_impact(task, sample, tmp_path):
    _, directory, _, plans, expected, definition, _ = sample
    dbg = deepcopy(definition)
    for row in plans['DBG_faults'].values(): dbg['formulas'][row['sheet'] + '!' + row['cell']] = row['faulty_formula']
    values = deepcopy(expected)
    for point in definition['DBG_root_points']: values[point] = {'type': 'number', 'value': '999999'}
    path = tmp_path / 'dbg.xlsx'; fixture_cache(directory / 'debugging_input.xlsx', path, values)
    task.verify_definitions(path, dbg); task.verify_input_caches(path, expected, blank=False, definition=definition)
    unchanged = tmp_path / 'root_does_nothing.xlsx'; fixture_cache(directory / 'debugging_input.xlsx', unchanged, expected)
    with pytest.raises(ValueError, match='real primary2dp'): task.verify_input_caches(unchanged, expected, blank=False, definition=definition)


def test_DBG_bool_cannot_be_replaced_with_numeric_one(task, sample, tmp_path):
    _, directory, _, _, expected, definition, _ = sample
    values = deepcopy(expected); point = next(k for k, v in values.items() if v['type'] == 'boolean')
    values[point] = {'type': 'number', 'value': '1'}
    path = tmp_path / 'numeric_bool.xlsx'; fixture_cache(directory / 'debugging_input.xlsx', path, values)
    with pytest.raises(ValueError, match='type changed'): task.verify_input_caches(path, expected, blank=False, definition=definition)


def test_primary_grading_accepts_equivalent_formula_and_rejects_missed_value(task, sample, tmp_path):
    _, _, _, _, expected, definition, goal = sample
    fm = tmp_path / 'fm.xlsx'; fm_input(task, sample, fm)
    point = definition['DBG_root_points'][0]; coord = tuple(point.rsplit('!', 1))
    formula = definition['formulas'][point]
    equivalent = tmp_path / 'equivalent.xlsx'; task.transform(goal, equivalent, {coord: ('formula', '=0+(' + formula.lstrip('=') + ')')})
    cached = tmp_path / 'equivalent_cached.xlsx'; fixture_cache(equivalent, cached, expected)
    assert task.compare_complete(fm, goal, cached, expected)['reward'] == 1
    missing = tmp_path / 'missing.xlsx'; task.transform(goal, missing, {coord: ('blank', None)})
    assert task.compare_complete(fm, goal, missing, expected)['reward'] == 0


def test_source_failure_cannot_allocate_task_inputs(task, monkeypatch, tmp_path):
    monkeypatch.setattr(task.source, 'validate_source', lambda value: {'kind': task.source.SOURCE_KIND, 'passed': False})
    output = ROOT / 'outputs' / 'tmp' / (tmp_path.name + '_must_not_allocate_task8')
    assert not output.exists()
    with pytest.raises(ValueError, match='genuine complete'): task.prepare({}, output)
    assert not output.exists()


def test_isolated_task8_keeps_all_stages_and_current_callbacks(task):
    assert task.STAGES == ('FM_input1', 'FM_input2', 'DBG_input1', 'DBG_input2', 'equivalent', 'FM_missed_root', 'DBG_missed_root', 'extra_change')
    assert task.execute_prepared.__globals__['verify_input_caches'] is task.verify_input_caches
    assert task.validate_completed.__globals__['verify_definitions'] is task.verify_definitions
    assert task.execute_prepared.__globals__['source'].SOURCE_KIND == 'independently_checked_fixed_operating_reports_200_source_revision2'
