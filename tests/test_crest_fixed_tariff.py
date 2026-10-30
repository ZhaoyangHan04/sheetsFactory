from pathlib import Path
import importlib.util
import math

import openpyxl
from openpyxl.comments import Comment
from openpyxl.worksheet.formula import DataTableFormula
import pytest

MODULE = Path(__file__).resolve().parents[1] / 'scripts/build_crest_fixed_tariff.py'
_spec = importlib.util.spec_from_file_location('crest_fixed_tariff', MODULE)
crest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crest)


def execution():
    grids = []
    for name, lo, step in [('coarse', 0, 10), ('integer', 30, 1), ('tenth', 32, .1)]:
        values = [{'rate_cents_per_kwh': lo + i * step, 'npv_dollars': (lo + i * step - 32.05) * 1000}
                  for i in range(11)]
        bracket = next((values[i], values[i+1]) for i in range(10)
                       if values[i]['npv_dollars'] < 0 < values[i+1]['npv_dollars'])
        grids.append({'stage': name, 'values': values, 'lower': bracket[0], 'upper': bracket[1]})
    return {'grids': grids, 'computed_tariff_cents_per_kwh': 32.05, 'base_target_npv_dollars': 0,
            'final_formula_snapshot': [{'sheet': 'Cash Flow', 'cell': 'G55', 'observed_error': 0,
              'observed_numeric': 0, 'observed_string': 'NA',
              'observed_result_type': "<Enum instance com.sun.star.table.CellContentType ('TEXT')>"}]}


def source_file(tmp_path):
    source = tmp_path / 'source.xlsx'
    book = openpyxl.Workbook(); sheet = book.active; sheet.title = 'Cash Flow'
    sheet['G72'] = '=AVERAGE(R204:S204)'
    sheet['G20'] = '=2+3'; sheet['G20'].comment = Comment('Original policy note', 'Publisher')
    sheet['F54'] = -100; sheet['G54'] = 10
    sheet['G55'] = '=IF(ISERROR(IRR($F54:G54)),"NA",IRR($F54:G54))'
    for col in ('G', 'K', 'O'):
        for row in range(205, 216): sheet[f'{col}{row}'] = row * 2
        sheet[f'{col}205'] = DataTableFormula(ref=f'{col}205:{col}215', r1='G72', dt2D='0', dtr='0')
    book.save(source); book.close()
    return source


@pytest.mark.parametrize('flows', [[-100, 230, -132], [0, 0], [1, 2], [-1, -2],
                                    [True, -1, 2], [-1, float('nan')], [-1, float('inf')], [-1, '2']])
def test_rejects_unproved_irr_roots(flows):
    with pytest.raises(ValueError): crest.unique_irr(flows)


def test_unique_irr_has_independent_root_with_zero_flow():
    proof = crest.unique_irr([-100, 0, 121])
    assert proof['sign_changes'] == 1
    assert abs(proof['unique_root'] - .1) < 1e-12
    assert abs(proof['npv_residual']) < 1e-10


def test_exact_calibration_coverage_and_values():
    values = crest.calibration_values(execution(), 205)
    assert set(values) == {f'{c}{r}' for c in ('G','K','O') for r in range(205,216)}
    assert len(values) == 33
    assert values['G205'] == pytest.approx(-32050,abs=1e-9)


def test_rejects_incomplete_or_nonfinite_calibration():
    data = execution(); data['grids'][1]['values'].pop()
    with pytest.raises(ValueError): crest.calibration_values(data,205)
    data = execution(); data['grids'][0]['values'][0]['npv_dollars'] = math.nan
    with pytest.raises(ValueError): crest.calibration_values(data,205)


def test_calibration_helpers_follow_measured_brackets():
    values = crest.expected_calibration_formulas(execution(),205)
    assert values['J205'] == 30
    assert values['J215'] == 40
    assert values['N205'] == 32
    assert values['N215'] == 33
    assert values['R204'] == 32
    assert abs(values['S204'] - 32.1) < 1e-12
    assert values['G204'] == 0


def test_only_33_calibrations_tariff_and_proved_failed_irr_change(tmp_path):
    source = source_file(tmp_path); original_sha = crest.sha(source)
    out = tmp_path / 'derived.xlsx'
    audit = crest.create_derived(source,out,'solar',execution())
    book = openpyxl.load_workbook(out,data_only=False)
    assert book['Cash Flow']['G20'].value == '=2+3'
    assert book['Cash Flow']['G20'].comment.text == 'Original policy note'
    assert book['Cash Flow']['G72'].value == 32.05
    assert len([e for e in audit['edits'] if e['kind']=='provided_calibration_snapshot']) == 33
    assert len([e for e in audit['edits'] if e['kind']=='unique_irr_numerical_fallback']) == 1
    assert 'IFERROR(IRR($F54:G54),IRR($F54:G54,-0.9))' in book['Cash Flow']['G55'].value
    assert not any(c.value.__class__.__name__=='DataTableFormula' for s in book for c in s._cells.values())
    assert audit['exact_calibration_cell_count'] == 33
    assert set(audit['formula_changed_cells']) == {'Cash Flow!G72','Cash Flow!G55',
           'Cash Flow!G205','Cash Flow!K205','Cash Flow!O205'}
    numeric_originals = [e['original_formula_or_value'] for e in audit['edits']
                         if e['kind']=='provided_calibration_snapshot' and e['original_type']=='n']
    assert numeric_originals and all(isinstance(v,int) for v in numeric_originals)
    assert 'do not apply' in book['Fixed PPA Scenario']['A3'].value
    assert crest.sha(source) == original_sha
    book.close()


def test_successful_default_irr_formula_is_unchanged(tmp_path):
    source=source_file(tmp_path); data=execution()
    data['final_formula_snapshot'][0].update(observed_numeric=-.9,observed_string='-90%',
        observed_result_type="<Enum instance com.sun.star.table.CellContentType ('VALUE')>")
    audit=crest.create_derived(source,tmp_path/'derived.xlsx','solar',data)
    assert not audit['irr_proofs']
    assert 'Cash Flow!G55' not in audit['formula_changed_cells']


def test_additional_table_range_is_rejected(tmp_path):
    source=source_file(tmp_path); book=openpyxl.load_workbook(source)
    book['Cash Flow']['S205']=DataTableFormula(ref='S205:S215',r1='G72',dt2D='0',dtr='0')
    with pytest.raises(ValueError,match='33-cell'):crest.table_cells(book,205)
    book.close()


def test_serialization_cannot_change_protected_financial_formula(tmp_path,monkeypatch):
    source=source_file(tmp_path); save=openpyxl.workbook.workbook.Workbook.save
    def corrupt(book,path):
        if Path(path).name=='derived.xlsx':book['Cash Flow']['G20']='=999'
        return save(book,path)
    monkeypatch.setattr(openpyxl.workbook.workbook.Workbook,'save',corrupt)
    with pytest.raises(ValueError,match='Protected source cell'):
        crest.create_derived(source,tmp_path/'derived.xlsx','solar',execution())


def test_build_refuses_overwrite_and_original_sha_mismatch(tmp_path):
    existing=tmp_path/'existing';existing.mkdir()
    with pytest.raises(FileExistsError):crest.build(tmp_path,tmp_path/'missing.xlsx',existing,'solar')
    source=source_file(tmp_path);out=tmp_path/'rejected'
    with pytest.raises(ValueError,match='source SHA'):crest.build(MODULE.parents[1],source,out,'solar')
    assert (out/'failure.json').exists()
    assert not (out/'manifest.json').exists()


def test_numeric_input_precision_and_all_policy_notes_are_preserved(tmp_path):
    import zipfile
    import xml.etree.ElementTree as ET
    source=source_file(tmp_path)
    book=openpyxl.load_workbook(source);book['Cash Flow']['AE6']=.15122328571428573;book.save(source);book.close()
    temp=tmp_path/'precise.xlsx'
    ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(source) as old,zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as new:
        for name in old.namelist():
            payload=old.read(name)
            if name=='xl/worksheets/sheet1.xml':
                tree=ET.fromstring(payload)
                next(c for c in tree.findall('.//m:c',ns) if c.attrib['r']=='AE6').find('m:v',ns).text='0.15122328571428573'
                payload=ET.tostring(tree,encoding='utf-8',xml_declaration=True)
            new.writestr(name,payload)
    temp.replace(source)
    audit=crest.create_derived(source,tmp_path/'derived.xlsx','solar',execution())
    result=openpyxl.load_workbook(tmp_path/'derived.xlsx')
    assert result['Cash Flow']['AE6'].value==.15122328571428573
    assert audit['preserved_numeric_input_precision']==[{'sheet':'Cash Flow','cell':'AE6',
        'serialized_value':'0.1512232857142857','restored_original_value':.15122328571428573}]
    assert result['Cash Flow']['G20'].comment.text=='Original policy note'
    result.close()


def test_text_formula_cannot_become_zero_in_irr_proof(tmp_path):
    source=source_file(tmp_path);book=openpyxl.load_workbook(source)
    book['Cash Flow']['F54']='="text"';book.save(source);book.close()
    data=execution();data['final_formula_snapshot'].append({'sheet':'Cash Flow','cell':'F54',
        'observed_error':0,'observed_numeric':0,'observed_string':'text',
        'observed_result_type':"<Enum instance com.sun.star.table.CellContentType ('TEXT')>"})
    with pytest.raises(ValueError,match='finite numeric result'):
        crest.create_derived(source,tmp_path/'derived.xlsx','solar',data)
