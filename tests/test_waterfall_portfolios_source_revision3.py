from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from xml.etree import ElementTree as X
from zipfile import ZIP_DEFLATED, ZipFile

import openpyxl
import pytest


ROOT=Path(__file__).resolve().parents[1]
S='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


@pytest.fixture(scope='module')
def module():
    path=ROOT/'scripts/build_waterfall_portfolios_source_revision3.py'
    loader=importlib.util.spec_from_file_location('_test_waterfall_source_revision3',path)
    value=importlib.util.module_from_spec(loader);loader.loader.exec_module(value)
    return value


def fixture_book(module,*,constant_booleans=False):
    book=openpyxl.Workbook();book.active.title='Financial'
    book['Financial']['A1']='=2+3';book['Financial']['A2']='=OR(FALSE(),FALSE())'
    book['Financial']['B1']='Given operating context'
    for point,wanted in module.GIVEN_BOOLEANS.items():
        sheet,cell=point.rsplit('!',1)
        if sheet not in book.sheetnames:book.create_sheet(sheet)
        book[sheet][cell]=('=TRUE()' if wanted['value'] else '=FALSE()') if constant_booleans else wanted['value']
    definition={'sheetnames':book.sheetnames,'formulas':{
        'Financial!A1':'=2+3','Financial!A2':'=OR(FALSE(),FALSE())'},
        'literals':{**deepcopy(module.GIVEN_BOOLEANS),
            'Financial!B1':{'type':'text','value':'Given operating context'}},
        'provided_financial_inputs':{}}
    expected={'Financial!A1':{'type':'number','value':'5'},
              'Financial!A2':{'type':'boolean','value':False}}
    return book,definition,expected


def save_native_fixture(book,path,expected,*,wrong_cache=None):
    uncached=path.with_name(path.stem+'_uncached.xlsx');book.save(uncached)
    order=list(book.sheetnames);wanted=dict(expected)
    for sheet in book:
        for cell in sheet._cells.values():
            if cell.data_type=='f' and cell.value in ('=TRUE()','=FALSE()'):
                wanted[sheet.title+'!'+cell.coordinate]={'type':'boolean','value':cell.value=='=TRUE()'}
    if wrong_cache:wanted.update(wrong_cache)
    with ZipFile(uncached) as source,ZipFile(path,'x',ZIP_DEFLATED) as target:
        for item in source.infolist():
            raw=source.read(item.filename)
            if item.filename.startswith('xl/worksheets/sheet') and item.filename.endswith('.xml'):
                index=int(item.filename.rsplit('sheet',1)[1][:-4])-1;root=X.fromstring(raw)
                for cell in root.iter(S+'c'):
                    if cell.find(S+'f') is None:continue
                    value=wanted[order[index]+'!'+cell.get('r')]
                    for child in list(cell):
                        if child.tag in (S+'v',S+'is'):cell.remove(child)
                    cell.set('t','b' if value['type']=='boolean' else 'n')
                    X.SubElement(cell,S+'v').text=('1' if value['value'] else '0') if value['type']=='boolean' else value['value']
                raw=X.tostring(root)
            target.writestr(item,raw)


def test_original_literal_and_native_constant_shapes_are_separate_and_read_only(module):
    for native in (False,True):
        book,definition,_=fixture_book(module,constant_booleans=native)
        before={s.title:{c.coordinate:(c.data_type,c.value) for c in s._cells.values()} for s in book}
        report=module.classify_formula_scope(book,definition)
        assert report['financial_formulas']==definition['formulas']
        assert report['physical_formula_count']==(50 if native else 2)
        assert len(report['provided_boolean_constant_formulas'])==(48 if native else 0)
        assert all(v in ('=TRUE()','=FALSE()') for v in report['provided_boolean_constant_formulas'].values())
        assert before=={s.title:{c.coordinate:(c.data_type,c.value) for c in s._cells.values()} for s in book}
        book.close()


@pytest.mark.parametrize('bad',['=TRUE()+0','= FALSE()','=FALSE(0)','=_xlfn.FALSE()',
    '=INDIRECT("A1")','=1=0',0,1,'FALSE'])
def test_boolean_compatibility_is_not_a_general_formula_or_numeric_allowlist(module,bad):
    book,definition,_=fixture_book(module)
    point=next(p for p,v in module.GIVEN_BOOLEANS.items() if v['value'] is False)
    sheet,cell=point.rsplit('!',1);book[sheet][cell]=bad
    with pytest.raises(ValueError,match='given Boolean'):module.classify_formula_scope(book,definition)
    book.close()


def test_opposite_boolean_constant_and_literal_both_reject(module):
    for value in (True,'=TRUE()'):
        book,definition,_=fixture_book(module)
        point=next(p for p,v in module.GIVEN_BOOLEANS.items() if v['value'] is False)
        sheet,cell=point.rsplit('!',1);book[sheet][cell]=value
        with pytest.raises(ValueError,match='given Boolean'):module.classify_formula_scope(book,definition)
        book.close()


def test_missing_point_and_mutated_or_extended_boolean_definition_reject(module):
    book,definition,_=fixture_book(module)
    point=next(iter(module.GIVEN_BOOLEANS));sheet,cell=point.rsplit('!',1)
    del book[sheet][cell]
    with pytest.raises(ValueError,match='missing'):module.classify_formula_scope(book,definition)
    for change in ('value','extra','missing'):
        original=deepcopy(definition)
        if change=='value':original['literals'][point]['value']=not original['literals'][point]['value']
        elif change=='extra':original['literals']['Financial!C1']={'type':'boolean','value':False}
        else:original['literals'].pop(point)
        with pytest.raises(ValueError,match='exact48'):module.classify_formula_scope(book,original)
    book.close()


def test_partial_financial_scope_remains_supported_for_fm_and_rogue_formulas_are_not_hidden(module):
    book,definition,_=fixture_book(module,constant_booleans=True)
    del book['Financial']['A1']
    report=module.classify_formula_scope(book,definition)
    assert report['financial_formulas']=={'Financial!A2':'=OR(FALSE(),FALSE())'}
    assert report['physical_formula_count']==49
    book['Financial']['C1']='=TRUE()'
    report=module.classify_formula_scope(book,definition)
    assert report['financial_formulas']['Financial!C1']=='=TRUE()'
    assert 'Financial!A2' not in report['provided_boolean_constant_formulas']
    book.close()


def test_actual_complete_audit_checks_all_cached_values_and_separates_physical_census(module,tmp_path):
    book,definition,expected=fixture_book(module,constant_booleans=True)
    path=tmp_path/'native.xlsx';save_native_fixture(book,path,expected);book.close()
    audit=module._N['audit_workbook'](path,definition,expected)
    assert audit['passed'] and not audit['mismatches'] and not audit['native_errors']
    assert audit['kind']=='full_independent_waterfall_native_cache_audit_revision3'
    assert audit['physical_formulas_checked']==50
    assert audit['canonical_financial_formulas_checked']==audit['all_derived_values_checked']==2
    assert audit['provided_boolean_constant_formula_count']==48
    assert audit['protected_public_literals_checked']==49


@pytest.mark.parametrize('wrong',[
    {'type':'boolean','value':True},{'type':'number','value':'0'}])
def test_given_constant_cache_is_still_independently_checked_for_exact_type_and_value(module,tmp_path,wrong):
    book,definition,expected=fixture_book(module,constant_booleans=True)
    point=next(p for p,v in module.GIVEN_BOOLEANS.items() if not v['value'])
    path=tmp_path/'wrong_cache.xlsx';save_native_fixture(book,path,expected,wrong_cache={point:wrong});book.close()
    report=module._N['audit_workbook'](path,definition,expected)
    assert not report['passed']
    assert any(r['point']==point for r in report['mismatches'])


def test_financial_operator_mutation_is_not_canonicalized_or_accepted(module,tmp_path):
    book,definition,expected=fixture_book(module,constant_booleans=True)
    book['Financial']['A1']='=2-3'
    path=tmp_path/'wrong_formula.xlsx';save_native_fixture(book,path,expected);book.close()
    with pytest.raises(ValueError,match='financial formula definitions changed'):
        module._N['audit_workbook'](path,definition,expected)


def test_actual_cold_input_still_has_no_formula_cache_or_seeded_result(module,tmp_path):
    book,definition,expected=fixture_book(module)
    source=tmp_path/'original.xlsx';book.save(source);book.close();cold=tmp_path/'cold.xlsx'
    assert module._S['unseeded_original'](source)==2
    module._S['_P']['clear_all_formula_caches'](source,cold)
    assert module._S['_P']['_physical_empty'](cold)==2
    report=module._N['audit_workbook'](cold,definition,expected,empty_caches=True)
    assert report['passed'] and report['provided_boolean_constant_formula_count']==0


def test_new_recipe_binds_all_prior_failures_and_whole_native_census_without_old_edits(module):
    before={p:module._sha(p) for p in (module.UPSTREAM,module._S['UPSTREAM'],module._S['_P']['ANCESTOR'])}
    recipe=module.recipes()
    for path,digest in ((module.UPSTREAM,module.UPSTREAM_SHA),(module.FAILED_SOURCE,module.FAILED_SOURCE_SHA),
                        (module.CENSUS,module.CENSUS_SHA)):
        assert recipe[str(path.resolve())]['sha256']==digest
    assert recipe[str(Path(module.__file__).resolve())]==module.reference(module.__file__)
    assert before=={p:module._sha(p) for p in before}
    assert module._N is module._S['_N']
    assert module._N['recipes'] is module.recipes and module._N['classify_formula_scope'] is module.classify_formula_scope
    assert module._N['validate_prepared'] is module.validate_prepared
    assert module.execute_prepared.__globals__ is module._N
    assert module._N['SOURCE_KIND']==module.SOURCE_KIND and module._N['KIND']==module.KIND
    assert module.KIND.endswith('revision3') and module.SOURCE_KIND.endswith('revision3')


@pytest.mark.parametrize('kind',[
    'independently_checked_waterfall_portfolios_cold_source3',
    'independently_checked_waterfall_portfolios_cold_source3_revision2'])
def test_old_failed_source_kind_or_json_pass_cannot_supply_new_admission(module,tmp_path,kind):
    old=tmp_path/'old.json';old.write_text(json.dumps({'kind':kind,'version':1,'passed':True}))
    with pytest.raises(ValueError,match='genuine complete source3'):module.validate_source(old)


def test_frozen_revision2_drift_rejects_before_any_lifecycle(module,tmp_path,monkeypatch):
    other=tmp_path/'changed.py';other.write_bytes(module.UPSTREAM.read_bytes()+b'\n')
    monkeypatch.setattr(module,'UPSTREAM',other)
    with pytest.raises(ValueError,match='frozen revision2'):module._load()
