from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location('cached_source_revision2', ROOT/'scripts/build_cached_ringfenced_pair_source_revision2.py')
m = importlib.util.module_from_spec(loader); loader.loader.exec_module(m)


def test_original_frozen_recipe_is_retained_and_new_binding_is_explicit():
    assert m.base.ref(m.BASE)['sha256'] == m.BASE_SHA
    assert m.recipes()[:2] == [m.base.ref(m.__file__), m.base.ref(m.BASE)]
    assert m.namespace['prepare'].__globals__['recipes'] is m.recipes
    assert m.namespace['validate_completed'].__globals__['recipes'] is m.recipes


def test_exact_stream_callback_supports_third_argument_and_keyword_local_sheet():
    donor = {'sheet_map': {'Model': 'Fund A - Model'}, 'names': {}}
    assert m.fast_stream_formula('=Model!A1+2', donor, sheet='Model') == "='Fund A - Model'!A1+2"
    with pytest.raises(ValueError): m.formula_rename('=PrivateName', donor['sheet_map'], {'PrivateName': 'renamed'})


def test_real_stream_composer_consumes_callback_and_emits_exact_formula_cold_cache(tmp_path, monkeypatch):
    donors = []
    for index, prefix in enumerate(('Fund A - ', 'Fund B - ')):
        wb = Workbook(); ws = wb.active; ws.title = 'Model'
        ws['A1'] = 10+index; ws['A2'] = '=Model!A1*2'; ws['B1'] = 'Model!A1 remains text'
        path = tmp_path/f'donor{index}.xlsx'; wb.save(path); wb.close()
        donors.append({'id': f'M0{index+1}', 'prefix': prefix, 'workbook': m.ref(path)})
    def forbidden_parse(*args, **kwargs): raise AssertionError('The retained donor grammar must not be replayed')
    monkeypatch.setattr(m.stream_composition._N['syntax'], '_formula_tokens', forbidden_parse)
    original = m.stream_composition._N['_formula']
    out = tmp_path/'composed.xlsx'
    result = m.composer()(donors, out, mode='toy', toy=True,
        expected_census={'sheets': 2, 'formulas': 2, 'nonempty': 6})
    assert m.stream_composition._N['_formula'] is original
    assert result['geometry'] == {'formulas': 2, 'nonempty': 6, 'targets': 2}
    formula = load_workbook(out, data_only=False); cache = load_workbook(out, data_only=True)
    try:
        for index, prefix in enumerate(('Fund A - ', 'Fund B - ')):
            assert formula[prefix+'Model']['A2'].value == "='"+prefix+"Model'!A1*2"
            assert formula[prefix+'Model']['A1'].value == 10+index
            assert formula[prefix+'Model']['B1'].value == 'Model!A1 remains text'
            assert cache[prefix+'Model']['A2'].value is None
    finally: formula.close(); cache.close()
