"""The batch admission checks must retain the full modified-value contract."""
import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1]/'scripts/build_operating_reports_factory_batch.py'
spec = importlib.util.spec_from_file_location('factory_batch_test', PATH)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


def fixture_values():
    healthy = {'Data!A1': ('number', '100.00'), 'Report!B2': ('number', '0.00'), 'Report!D8': ('number', '2.00')}
    return healthy, {'formulas': {'Report!B2': '=0', 'Report!D8': '=2'}}


def check(observed, *, errors=(), names=('Data', 'Report'), mode='financial_modeling'):
    healthy, definition = fixture_values()
    return module.check_native_input(mode, {'mask_points': ['Report!B2']}, list(names), observed,
        list(errors), ['Data', 'Report'], healthy, definition)


def test_blank_zero_is_an_actual_required_change():
    healthy, _ = fixture_values(); observed = dict(healthy); del observed['Report!B2']
    assert check(observed)['complete_primary_difference'] == ['Report!B2']


def test_full_union_detects_added_hidden_coordinate():
    healthy, _ = fixture_values(); observed = dict(healthy); del observed['Report!B2']
    observed['Data!ZZ1000'] = ('text', 'unexpected')
    with pytest.raises(ValueError, match='supplied facts'):
        check(observed)


def test_given_numeric_string_cannot_be_rewritten_as_number():
    healthy, _ = fixture_values(); observed = dict(healthy); del observed['Report!B2']
    observed['Data!A1'] = ('text', '100.00')
    with pytest.raises(ValueError, match='supplied facts'):
        check(observed)


@pytest.mark.parametrize('kind', ['no_change', 'native_error', 'sheet_structure', 'missed_mask'])
def test_invalid_material_has_no_programmatic_admission(kind):
    healthy, _ = fixture_values(); observed = dict(healthy); errors = (); names = ('Data', 'Report')
    if kind == 'native_error':
        errors = ('Report!B2',); observed['Report!B2'] = ('error', '#DIV/0!')
    if kind == 'sheet_structure':
        names = ('Report', 'Data')
    if kind == 'missed_mask':
        observed['Report!D8'] = ('number', '3.00')
    with pytest.raises(ValueError):
        check(observed, errors=errors, names=names)
