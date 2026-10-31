from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def source():
    return load(ROOT / 'scripts/build_operating_reports_200_source.py', '_test_fixed200_source')


@pytest.fixture
def sample(tmp_path, source):
    fixture = load(ROOT / 'tests/test_operating_reports_200.py', '_test_fixed200_public_fixture')
    public = fixture.toy(); directory = tmp_path / 'emission'
    source.excel.emit(public, directory)
    bindings = json.loads((directory / 'private_bindings.json').read_text())
    expected, comparison = source.crosscheck(public, bindings)
    definition = source.source_definition(directory / 'source_uncalculated.xlsx', bindings, public)
    cold = tmp_path / 'cold.xlsx'
    clearance = source._ns['clear_all_formula_caches'](directory / 'source_uncalculated.xlsx', cold)
    return public, directory, bindings, expected, comparison, definition, cold, clearance


def test_real_independent_oracles_and_complete_cold_NA_scope(source, sample):
    public, directory, bindings, expected, comparison, definition, cold, clearance = sample
    assert source.oracle_a.__file__ != source.oracle_b.__file__
    assert comparison['passed'] and comparison['points'] == len(expected) == 1230
    row = bindings['financial']['E001/2026Q1/net_income']
    assert expected[row['sheet'] + '!' + row['cell']] == {'type': 'number', 'value': '37.25'}
    assert clearance['all_formula_caches_cleared'] == len(definition['formulas'])
    report = source.audit_workbook(cold, definition, expected, empty_caches=True)
    assert report['passed'] and report['all_financial_fields_checked'] == 1230
    assert len(definition['provided_financial_inputs']) == 56 and source._formula_cache_count(cold) == 0
    assert any(value['type'] == 'text' for value in expected.values())
    assert any(value['type'] == 'boolean' for value in expected.values())


@pytest.mark.parametrize('change', ['missing_report', 'duplicate_report', 'wrong_NA_role'])
def test_full_financial_binding_census_rejects_corruption(source, sample, change):
    public, _, bindings, *_ = sample; bindings = deepcopy(bindings)
    if change == 'missing_report': bindings['financial'].pop(next(iter(bindings['financial'])))
    elif change == 'duplicate_report':
        keys = list(bindings['financial']); bindings['financial'][keys[1]] = bindings['financial'][keys[0]]
    else:
        key = next(k for k, row in bindings['financial'].items() if row['role'] == 'given_NA')
        bindings['financial'][key]['role'] = 'report'
    with pytest.raises(ValueError): source.crosscheck(public, bindings)


@pytest.mark.parametrize('change', ['missing_fact', 'changed_fact', 'missing_context', 'changed_label'])
def test_source_definition_independently_binds_given_inputs_and_context(source, sample, change):
    public, directory, bindings, *_ = sample; bindings = deepcopy(bindings)
    if change == 'missing_fact': bindings['provided_facts'].pop(next(iter(bindings['provided_facts'])))
    elif change == 'changed_fact': next(iter(bindings['provided_facts'].values()))['value'] = '999'
    elif change == 'missing_context': bindings['provided_context'].pop('ReadMe!A1')
    else: bindings['provided_context']['ReadMe!A1']['value'] = 'A different policy context'
    with pytest.raises(ValueError): source.source_definition(directory / 'source_uncalculated.xlsx', bindings, public)


def test_changed_public_policy_and_calculation_mode_rejected(source, sample, tmp_path):
    public, directory, bindings, *_ = sample
    for name in ('policy', 'circular'):
        book = openpyxl.load_workbook(directory / 'source_uncalculated.xlsx')
        if name == 'policy': book['ReadMe']['A3'] = 'Different tax policy'
        else: book.calculation.iterate = True
        path = tmp_path / (name + '.xlsx'); book.save(path); book.close()
        with pytest.raises(ValueError): source.source_definition(path, bindings, public)


def test_seeded_cache_is_rejected_and_all_cache_nodes_are_removed(source, sample, tmp_path):
    _, _, _, expected, _, definition, cold, _ = sample
    poisoned = tmp_path / 'seeded.xlsx'; touched = False
    with ZipFile(cold) as original, ZipFile(poisoned, 'x', ZIP_DEFLATED) as output:
        for item in original.infolist():
            data = original.read(item.filename)
            if not touched and item.filename.startswith('xl/worksheets/sheet') and b'</f>' in data:
                data = data.replace(b'</f>', b'</f><v>123.0</v>', 1); touched = True
            output.writestr(item, data)
    assert touched and source._formula_cache_count(poisoned) == 1
    with pytest.raises(ValueError): source.audit_workbook(poisoned, definition, expected, empty_caches=True)
    cleared = tmp_path / 'cleared.xlsx'; source._ns['clear_all_formula_caches'](poisoned, cleared)
    assert source.audit_workbook(cleared, definition, expected, empty_caches=True)['passed']


def test_formula_and_given_value_mutations_are_detected(source, sample, tmp_path):
    _, _, _, expected, _, definition, cold, _ = sample
    for kind in ('formula', 'literal', 'extra'):
        book = openpyxl.load_workbook(cold)
        if kind == 'formula': point = next(iter(definition['formulas'])); value = '=999'
        elif kind == 'literal': point = 'ReadMe!A1'; value = 'Different supplied title'
        else: point = 'ReadMe!Z99'; value = 'Unapproved extra'
        sheet, cell = point.rsplit('!', 1); book[sheet][cell] = value
        path = tmp_path / (kind + '.xlsx'); book.save(path); book.close()
        clean = tmp_path / (kind + '_unseeded.xlsx')
        source._ns['clear_all_formula_caches'](path, clean); path = clean
        if kind in ('formula', 'extra'):
            with pytest.raises(ValueError): source.audit_workbook(path, definition, expected, empty_caches=True)
        else: assert not source.audit_workbook(path, definition, expected, empty_caches=True)['passed']


def test_preparation_cannot_admit_toy_and_does_not_allocate(source, sample, tmp_path):
    public, directory, *_ = sample
    path = tmp_path / 'toy.json'; path.write_text(json.dumps(public))
    with pytest.raises(ValueError, match='fixed200'):
        source._inputs(path, directory, tmp_path / 'unused_A', tmp_path / 'unused_B')
    assert not (tmp_path / 'unused_A').exists()


@pytest.mark.parametrize('change', ['same_schema_new_name', 'changed_forecast_fact'])
def test_self_consistent_but_unapproved_production_inputs_rejected_first(source, tmp_path, change):
    public = source.raw.build_spec()
    assert source.schema.canonical_sha256(public) == source.SPECIFICATION_SHA256
    if change == 'same_schema_new_name': public['entities'][0]['name'] += ' Revised'
    else: public['entities'][0]['forecast_sales']['2026Q1'] = '999'
    source.schema.validate_spec(public)
    path = tmp_path / 'another200.json'; path.write_text(json.dumps(public))
    with pytest.raises(ValueError, match='original fixed200'):
        source._inputs(path, tmp_path / 'unread_emission', tmp_path / 'unread_A', tmp_path / 'unread_B')
    assert not (tmp_path / 'unread_emission').exists()


def test_original_source_namespace_and_profile_remain_unchanged(source):
    original = load(source.UPSTREAM, '_test_original_unchanged_source3')
    assert original.KIND == 'prepared_equity_income_group_cold_start_source'
    assert original.execute_prepared.__globals__ is not source.execute_prepared.__globals__
    assert source.execute_prepared.__globals__['audit_workbook'] is source.audit_workbook
    assert source.validate_source.__globals__['crosscheck'] is source.crosscheck
    _, profile = source.runtime(source.PROFILE)
    assert profile['docker_resources']['source'] == {'cpus': 2, 'memory_bytes': 34359738368, 'pids_limit': 256}
    assert profile['solver_tool_budget']['seconds'] == 1800
