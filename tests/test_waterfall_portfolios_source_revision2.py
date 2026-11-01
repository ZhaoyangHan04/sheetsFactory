import importlib.util
from pathlib import Path
from xml.etree import ElementTree as X
from zipfile import ZipFile, ZIP_DEFLATED

import pytest


ROOT=Path(__file__).resolve().parents[1]
S='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


@pytest.fixture
def module():
    path=ROOT/'scripts/build_waterfall_portfolios_source_revision2.py'
    loader=importlib.util.spec_from_file_location('_test_waterfall_source_revision2',path)
    value=importlib.util.module_from_spec(loader);loader.loader.exec_module(value)
    return value


def worksheet(path,cache):
    xml='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><f>SUM(B1:B2)</f>'+cache+'</c><c r="A2"><v>99</v></c></row></sheetData></worksheet>'
    with ZipFile(path,'x',ZIP_DEFLATED) as archive:archive.writestr('xl/worksheets/sheet1.xml',xml)
    return path


@pytest.mark.parametrize('cache',['','<v/>','<v></v>'])
def test_original_allows_only_absent_or_empty_scalar_value_placeholder(module,tmp_path,cache):
    source=worksheet(tmp_path/'original.xlsx',cache)
    assert module.unseeded_original(source)==1
    if cache:
        with pytest.raises(ValueError,match='physical formula cache'):module._P['_physical_empty'](source)
    else:assert module._P['_physical_empty'](source)==1


@pytest.mark.parametrize('cache',['<v>0</v>','<v>1</v>','<v>-1</v>','<v>0.00</v>',
    '<v> </v>','<v flag="x"/>','<v><value/></v>','<is/>','<is><t>answer</t></is>','<v/><v/>'])
def test_any_actual_cached_number_text_inline_or_noncanonical_placeholder_rejects(module,tmp_path,cache):
    source=worksheet(tmp_path/'bad.xlsx',cache)
    with pytest.raises(ValueError):module.unseeded_original(source)


def test_frozen_clearance_removes_placeholder_and_actual_native_input_stays_physically_strict(module,tmp_path):
    source=worksheet(tmp_path/'original.xlsx','<v/>');cold=tmp_path/'cold.xlsx'
    assert module.unseeded_original(source)==1
    report=module._P['clear_all_formula_caches'](source,cold)
    assert report['all_formula_caches_cleared']==1 and report['financial_formula_or_literal_edits']==0
    assert module._P['_physical_empty'](cold)==1
    with ZipFile(cold) as archive:
        root=X.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        cells={c.get('r'):c for c in root.iter(S+'c')}
        assert cells['A1'].find(S+'f').text=='SUM(B1:B2)'
        assert cells['A1'].find(S+'v') is None and cells['A1'].find(S+'is') is None
        assert cells['A2'].find(S+'v').text=='99'


def test_both_original_checks_are_narrowly_rebound_and_both_cold_checks_retained(module):
    for name in ('prepare','validate_prepared'):
        names=module._P[name].__code__.co_names
        assert '_unseeded_original' in names and '_physical_empty' in names
    assert module._P['_unseeded_original'] is module.unseeded_original
    assert module.KIND==module._P['KIND']==module._P['_N']['KIND']
    assert module.SOURCE_KIND==module._P['SOURCE_KIND']==module._P['_N']['SOURCE_KIND']
    assert 'revision2' in module.KIND and 'revision2' in module.SOURCE_KIND
    assert module._P['_N']['recipes'] is module.recipes
    assert module._P['_N']['validate_prepared'] is module._P['validate_prepared']


def test_revision_recipe_binds_old_entry_new_entry_and_entire_first_failure_lineage(module):
    recipe=module.recipes()
    assert recipe[str(module.UPSTREAM.resolve())]['sha256']==module.UPSTREAM_SHA
    for path,digest in ((module.FAILURE,module.FAILURE_SHA),(module.FAILURE_PROSPECTIVE,module.FAILURE_PROSPECTIVE_SHA),
                        (module.FAILURE_CENSUS,module.FAILURE_CENSUS_SHA)):
        assert recipe[str(path.resolve())]['sha256']==digest
    assert recipe[str(Path(module.__file__).resolve())]==module.reference(module.__file__)
    assert module.reference(module.UPSTREAM)['sha256']=='09223a654ce5231d83d15b292f299d6ffab9f0b0e1151dbe24eba9af187cc69e'


def test_task_facade_exports_only_actual_revision2_bound_source_helpers(module):
    assert module._N is module._P['_N']
    assert module._N['recipes'] is module.recipes
    assert module._N['validate_prepared'] is module.validate_prepared
    for name in ('AuditStore','DashboardServer','formula_signature','ThreadCappedResourceLibreOfficeEngine',
                 'validate_call','audit_workbook','source_definition','clear_all_formula_caches','owned_absence'):
        assert name in module._N
    assert module._N['SOURCE_KIND']==module.SOURCE_KIND


def test_frozen_first_script_drift_rejects_before_any_preparation(module,tmp_path,monkeypatch):
    copy=tmp_path/'changed.py';copy.write_bytes(module.UPSTREAM.read_bytes()+b'\n')
    monkeypatch.setattr(module,'UPSTREAM',copy)
    with pytest.raises(ValueError,match='frozen first'):module._load()


def test_original_kind_cannot_be_relabelled_as_revision2_source_pass(module,tmp_path):
    old=tmp_path/'old.json';old.write_text('{"kind":"independently_checked_waterfall_portfolios_cold_source3","version":1,"passed":true}')
    with pytest.raises(ValueError):module.validate_source(old)
