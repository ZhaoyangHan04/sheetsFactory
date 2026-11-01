"""The revised materials retain the frozen native mutation protocol."""
import importlib.util
import json
from pathlib import Path

from sheets_factory.workbook.tax_vintage_bridge_v2 import excel

def module(path, name):
    loader = importlib.util.spec_from_file_location(name,path)
    result = importlib.util.module_from_spec(loader); loader.loader.exec_module(result)
    return result

ROOT = Path(__file__).resolve().parents[1]
driver = module(ROOT/'scripts/build_tax_vintage_bridge_business_batch.py','_tax_vintage_builder_test')
inputs = module(Path(__file__).with_name('test_tax_vintage_bridge_v2_excel.py'),'_tax_vintage_builder_inputs')


def test_full_mask_and_business_mutations_preserve_every_public_fact(tmp_path):
    public = inputs.public()
    excel.emit(public,tmp_path/'source')
    b = json.loads((tmp_path/'source/private_bindings.json').read_text())
    source = tmp_path/'source/source_uncalculated.xlsx'
    scan = driver._N['scan']; original = scan(source,formulas=True)
    fm = driver.plan(public,b,original,'financial_modeling')
    assert set(fm['mask_points']) == set(original['formulas'])
    driver._N['emit_input'](source,original,fm,tmp_path/'fm.xlsx')
    masked = scan(tmp_path/'fm.xlsx',formulas=True)
    assert not masked['formulas'] and masked['literals'] == original['literals']
    debug = driver.plan(public,b,original,'debugging')
    assert debug['injected_formula_count'] > 0
    assert all(x['semantic_key'].split('/')[1].startswith(('2026','2027')) for x in debug['faults'].values())
    assert {x['family'] for x in debug['faults'].values()} == {'register_order_used_as_FIFO','expiry_boundary_and_term_reaged'}
    driver._N['emit_input'](source,original,debug,tmp_path/'debug.xlsx')
    changed = scan(tmp_path/'debug.xlsx',formulas=True)
    assert changed['literals'] == original['literals']
    assert changed['sheetnames'] == original['sheetnames']
    assert set(changed['formulas']) == set(original['formulas'])
    actual = {p for p in changed['formulas'] if changed['formulas'][p] != original['formulas'][p]}
    assert actual == set(debug['faults'])


def test_assessment_lag_bug_targets_a_real_term_transition(tmp_path):
    public = inputs.public('T03')
    excel.emit(public,tmp_path/'source')
    b = json.loads((tmp_path/'source/private_bindings.json').read_text())
    original = driver._N['scan'](tmp_path/'source/source_uncalculated.xlsx',formulas=True)
    debug = driver.plan(public,b,original,'debugging')
    lag_faults = [x for x in debug['faults'].values() if x['family'] == 'assessment_lag_replaced_by_current_lag']
    assert lag_faults
    assert any(x['semantic_key'] == 'E001/2026Q3/cash_tax_paid' for x in lag_faults)
    assert all(x['faulty_formula'].startswith('=') for x in debug['faults'].values())
