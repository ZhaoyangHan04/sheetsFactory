from copy import deepcopy
import hashlib
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from xml.etree import ElementTree as X
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.formatting.rule import FormulaRule
from openpyxl.packaging.custom import StringProperty
import pytest

from sheets_factory.workbook.linear_capital_ringfenced_group import stream_composition as stream


def fixture(path, number=13, prefix='P01 - ', identity='M01'):
    book = Workbook(); sheet = book.active; sheet.title = 'Data'
    other = book.create_sheet("Other's")
    sheet['A1'] = number; sheet['A1'].number_format = '0.0000'
    sheet['A1'].font = Font(color='FFCC0000' if number == 13 else 'FF0000CC')
    sheet['A2'] = True; sheet['A2'].number_format = 'General'
    sheet['A3'] = 'n/a (provided)'; sheet['A4'] = 'rich given text'
    sheet['B1'] = "='Other''s'!$A$1+LocalRate+A1"
    other['A1'] = number+1; other['A2'] = number+2
    other['B1'] = '=Data!A1*2'
    sheet['C1'] = 'business context'; sheet['C1'].hyperlink = 'https://example.invalid/policy'
    sheet['C2'] = 'go'; sheet['C2'].hyperlink = "#'Other''s'!A1"
    book.defined_names.add(DefinedName('LocalRate', attr_text="'Other''s'!$A$1"))
    sheet.add_data_validation(DataValidation(type='list', formula1="'Other''s'!$A$1:$A$2"))
    sheet.data_validations.dataValidation[0].add('D1')
    sheet.conditional_formatting.add('A1', FormulaRule(formula=["'Other''s'!A1>0"], fill=PatternFill('solid', fgColor='FFFFFF00')))
    sheet.print_area = 'A1:D3'
    book.custom_doc_props.append(StringProperty(name='business_note', value='Mandate note '+str(number)))
    book.save(path); book.close()
    with ZipFile(path) as archive: parts = {n: archive.read(n) for n in archive.namelist()}
    root = X.fromstring(parts['xl/worksheets/sheet1.xml'])
    string = root.find(".//{"+stream.S+"}c[@r='A4']")
    for child in list(string): string.remove(child)
    string.set('t', 's'); X.SubElement(string, '{'+stream.S+'}v').text = '0'
    parts['xl/worksheets/sheet1.xml'] = X.tostring(root)
    for part in ['xl/worksheets/sheet1.xml', 'xl/worksheets/sheet2.xml']:
        root = X.fromstring(parts[part])
        for cell in root.iter('{'+stream.S+'}c'):
            if cell.find('{'+stream.S+'}f') is not None:
                for child in list(cell.findall('{'+stream.S+'}v')): cell.remove(child)
                X.SubElement(cell, '{'+stream.S+'}v').text = '999.5'
        parts[part] = X.tostring(root)
    parts['xl/sharedStrings.xml'] = ('<sst xmlns="'+stream.S+'"><si><r><rPr><b/></rPr><t>rich given text</t></r></si></sst>').encode()
    root = X.fromstring(parts['xl/_rels/workbook.xml.rels'])
    X.SubElement(root, '{'+stream.P+'}Relationship', Id='strings', Type=stream.R+'/sharedStrings', Target='sharedStrings.xml')
    parts['xl/_rels/workbook.xml.rels'] = X.tostring(root)
    root = X.fromstring(parts['[Content_Types].xml'])
    X.SubElement(root, '{'+stream.C+'}Override', PartName='/xl/sharedStrings.xml', ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml')
    parts['[Content_Types].xml'] = X.tostring(root)
    rewrite_zip(path, parts)
    return {'id': identity, 'display_name': 'Mandate '+identity, 'prefix': prefix, 'workbook': stream.reference(path)}


def rewrite_zip(path, parts):
    with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
        for name, data in parts.items(): archive.writestr(name, data)


def donors(tmp_path):
    return [fixture(tmp_path/'one.xlsx'), fixture(tmp_path/'two.xlsx', 17, 'P02 - ', 'M02')]


def test_complete_toy_references_names_styles_sst_hyperlinks_and_cache_clear(tmp_path):
    original = donors(tmp_path); before = deepcopy(original)
    result = stream.compose_toy(original, tmp_path/'combined.xlsx')
    assert original == before and all(stream.reference(d['workbook']['path']) == d['workbook'] for d in original)
    assert result['geometry']['formulas'] == 4 and result['sheet_count'] == 4
    assert sum(w['cleared_formula_value_nodes'] for d in result['donors'] for w in d['worksheets']) == 4
    assert result['all_derived_formula_caches_cleared'] and result['retained_given_literals_NA_booleans_unchanged']
    assert result['new_group_source_admitted'] is False and result['LO_model_solver_Harbor_calls'] == 0
    book = load_workbook(tmp_path/'combined.xlsx', data_only=False)
    cached = load_workbook(tmp_path/'combined.xlsx', data_only=True)
    try:
        assert book.sheetnames == ['P01 - Data', "P01 - Other's", 'P02 - Data', "P02 - Other's"]
        for prefix, n in [('P01', 13), ('P02', 17)]:
            sheet = book[prefix+' - Data']
            assert sheet['B1'].value == "='"+prefix+" - Other''s'!$A$1+"+prefix+'__LocalRate+A1'
            assert book[prefix+" - Other's"]['B1'].value == "='"+prefix+" - Data'!A1*2"
            assert cached[prefix+' - Data']['B1'].value is None
            assert sheet['A1'].value == n and sheet['A1'].number_format == '0.0000'
            assert sheet['A2'].value is True and sheet['A2'].number_format == 'General'
            assert sheet['A3'].value == 'n/a (provided)' and sheet['A4'].value == 'rich given text'
            assert sheet['A1'].font.color.rgb == ('FFCC0000' if n == 13 else 'FF0000CC')
            assert sheet['C1'].hyperlink.target == 'https://example.invalid/policy'
            assert sheet['C2'].hyperlink.target == "#'"+prefix+" - Other''s'!A1"
            assert sheet.data_validations.dataValidation[0].formula1 == "'"+prefix+" - Other''s'!$A$1:$A$2"
            assert book.defined_names[prefix+'__LocalRate'].attr_text == "'"+prefix+" - Other''s'!$A$1"
            assert sheet.print_area == "'"+prefix+" - Data'!$A$1:$D$3"
            rule = next(iter(sheet.conditional_formatting._cf_rules.values()))[0]
            assert rule.formula == ["'"+prefix+" - Other''s'!A1>0"]
            assert rule.dxf.fill.fgColor.rgb == 'FFFFFF00'
        assert book['P01 - Data']['A1'].style_id != book['P02 - Data']['A1'].style_id
        assert book.custom_doc_props['M01__business_note'].value == 'Mandate note 13'
        assert book.custom_doc_props['M02__business_note'].value == 'Mandate note 17'
    finally: book.close(); cached.close()
    with ZipFile(tmp_path/'combined.xlsx') as archive:
        sst = X.fromstring(archive.read('xl/sharedStrings.xml'))
        assert len(sst) == 2 and all(node.find('.//{'+stream.S+'}b') is not None for node in sst)
        for name in archive.namelist():
            if '/worksheets/sheet' in name and name.endswith('.xml'):
                root = X.fromstring(archive.read(name))
                assert all(c.find('{'+stream.S+'}v') is None for c in root.iter('{'+stream.S+'}c') if c.find('{'+stream.S+'}f') is not None)
    mapped = stream.rekey_binding('M02', {'sheet': 'Data', 'cell': 'B1', 'expected_path': ['group', 'profit']}, result)
    assert mapped == {'sheet': 'P02 - Data', 'cell': 'B1', 'expected_path': ['group', 'profit'], 'fund_id': 'M02'}


@pytest.mark.parametrize('case', ['array', 'shared', 'dynamic', 'unknown_part', 'bad_style', 'bad_sst', 'theme', 'epoch', 'missing_part', 'missing_relationship'])
def test_unsupported_or_corrupt_package_holds_without_final_output(tmp_path, case):
    rows = donors(tmp_path); path = Path(rows[1]['workbook']['path'])
    with ZipFile(path) as archive: parts = {n: archive.read(n) for n in archive.namelist()}
    sheet = X.fromstring(parts['xl/worksheets/sheet1.xml'])
    formula = sheet.find('.//{'+stream.S+'}f')
    if case == 'array': formula.set('t', 'array')
    elif case == 'shared': formula.set('t', 'shared'); formula.set('si', '0')
    elif case == 'dynamic': formula.text = 'INDIRECT("A1")'
    elif case == 'bad_style': sheet.find('.//{'+stream.S+'}c').set('s', '9999')
    elif case == 'bad_sst': sheet.find(".//{"+stream.S+"}c[@r='A4']/{"+stream.S+'}v').text = '9999'
    elif case == 'unknown_part': parts['xl/drawings/drawing1.xml'] = b'<unhandled/>'
    elif case == 'missing_part': parts.pop('xl/sharedStrings.xml')
    elif case == 'missing_relationship': parts.pop('xl/worksheets/_rels/sheet1.xml.rels')
    elif case == 'theme': parts['xl/theme/theme1.xml'] += b' '
    elif case == 'epoch':
        wb = X.fromstring(parts['xl/workbook.xml']); wb.find('{'+stream.S+'}workbookPr').set('date1904', '1'); parts['xl/workbook.xml'] = X.tostring(wb)
    parts['xl/worksheets/sheet1.xml'] = X.tostring(sheet)
    rewrite_zip(path, parts); rows[1]['workbook'] = stream.reference(path)
    with pytest.raises((ValueError, stream.syntax.UnsupportedWorkbook)):
        stream.compose_toy(rows, tmp_path/'held.xlsx')
    assert not (tmp_path/'held.xlsx').exists()
    assert not list(tmp_path.glob('.ringfenced-compose-*'))


def test_bounds_namespace_and_fresh_output_are_fail_closed(tmp_path, monkeypatch):
    rows = donors(tmp_path)
    with pytest.raises(ValueError, match='namespace'):
        stream.sheet_map('P01 - ', ['Data', 'DATA'])
    with pytest.raises(ValueError, match='bounds'):
        stream.sheet_map('P01 - ', ['A'*30])
    monkeypatch.setattr(stream, 'LIMITS', {'formulas': 1, 'nonempty': 7500000, 'targets': 6400000})
    with pytest.raises(ValueError, match='geometry'):
        stream.compose_toy(rows, tmp_path/'held.xlsx')
    assert not (tmp_path/'held.xlsx').exists()
    existing = tmp_path/'existing.xlsx'; existing.write_bytes(b'unchanged')
    with pytest.raises(ValueError, match='fresh'):
        stream.compose_toy(rows, existing)
    assert existing.read_bytes() == b'unchanged'


def test_toy_gate_rejects_many_sheets_before_any_output(tmp_path):
    rows = donors(tmp_path); path = Path(rows[1]['workbook']['path'])
    book = load_workbook(path)
    for index in range(3): book.create_sheet('Extra'+str(index))
    book.save(path); book.close(); rows[1]['workbook'] = stream.reference(path)
    with pytest.raises(ValueError, match='four sheets'):
        stream.compose_toy(rows, tmp_path/'held.xlsx')
    assert not (tmp_path/'held.xlsx').exists()


def test_production_always_calls_genuine_composition_gate_before_output(tmp_path, monkeypatch):
    from sheets_factory.workbook.linear_capital_ringfenced_group import composition
    def reject(value): raise ValueError('genuine certificate rejected')
    monkeypatch.setattr(composition, 'validate_certificate', reject)
    with pytest.raises(ValueError, match='genuine certificate'):
        stream.compose({'passed': True}, tmp_path/'held.xlsx')
    assert not (tmp_path/'held.xlsx').exists()


def test_expected_census_rejects_omissions_even_when_below_caps(tmp_path):
    rows = donors(tmp_path)
    with pytest.raises(ValueError, match='donor census'):
        stream._compose(rows, tmp_path/'held.xlsx', mode='toy', toy=True,
            expected_census={'formulas': 5, 'nonempty': 22, 'sheets': 4})
    assert not (tmp_path/'held.xlsx').exists()


def test_old_merger_and_profile_are_not_modified():
    assert hashlib.sha256(Path(stream.syntax.__file__).read_bytes()).hexdigest() == stream.MERGER_SHA256
    profile = Path(__file__).resolve().parents[1]/'config/runtime_profiles/entity_group_large_v2.yaml'
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == '4ecc79fe954b9e2965a15d2f0c8965a39394f621ae9808f02fcf88965f446b9b'


def test_full_given_union_and_local_coordinates_preserved(tmp_path):
    rows = donors(tmp_path); result = stream.compose_toy(rows, tmp_path/'all.xlsx')
    merged = load_workbook(tmp_path/'all.xlsx', data_only=False)
    try:
        for donor, report in zip(rows, result['donors']):
            source = load_workbook(donor['workbook']['path'], data_only=False)
            try:
                for sheet in source:
                    target = merged[report['sheet_map'][sheet.title]]
                    before = {cell.coordinate: cell for row in sheet for cell in row if cell.value is not None}
                    after = {cell.coordinate: cell for row in target for cell in row if cell.value is not None}
                    assert set(before) == set(after)
                    for point, cell in before.items():
                        if cell.data_type != 'f':
                            assert type(cell.value) is type(after[point].value) and cell.value == after[point].value
                            assert cell.number_format == after[point].number_format
            finally: source.close()
    finally: merged.close()


def test_many_rows_use_the_same_bounded_row_path_with_no_shared_strings(tmp_path):
    rows = []
    for number, identity, prefix in [(1, 'M01', 'P01 - '), (2, 'M02', 'P02 - ')]:
        path = tmp_path/(identity+'.xlsx'); book = Workbook(); sheet = book.active; sheet.title = 'Operating'
        for row in range(1, 1001):
            sheet.cell(row, 1, row*number); sheet.cell(row, 2, '=A'+str(row)+'*2'); sheet.cell(row, 3, row % 2 == 0)
        book.save(path); book.close()
        rows.append({'id': identity, 'display_name': identity, 'prefix': prefix, 'workbook': stream.reference(path)})
    result = stream.compose_toy(rows, tmp_path/'many.xlsx')
    assert result['geometry'] == {'formulas': 2000, 'nonempty': 6000, 'targets': 2000}
    assert all(report['worksheets'][0]['maximum_row_cells'] == 3 for report in result['donors'])
    cached = load_workbook(tmp_path/'many.xlsx', data_only=True, read_only=True)
    try:
        assert cached['P02 - Operating']['A1000'].value == 2000
        assert cached['P02 - Operating']['B1000'].value is None
        assert cached['P02 - Operating']['C1000'].value is True
    finally: cached.close()
