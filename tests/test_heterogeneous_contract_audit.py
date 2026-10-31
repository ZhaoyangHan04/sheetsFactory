"""Audit corruption tests. Cached XML here is synthetic UNIT data, not LO evidence."""
from copy import deepcopy
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import openpyxl
import pytest
from openpyxl.utils.datetime import to_excel

from sheets_factory.workbook.heterogeneous_contracts import validate as audit


def ref(cell):
    return "'Forecast'!$"+cell[0]+"$"+cell[1:]


@pytest.fixture
def case(tmp_path):
    spec = {'opening_pence':100, 'when':'2028-02-01', 'rate_p12':10000000000}
    sha = audit.canonical_sha(spec)
    result = {'specification_sha256':sha, 'amount_pence':200,
        'vintage':{'entries':[{'origin_month':'2028-01-01','opening':250,
            'expired':0,'used':50,'created':0,'closing':200}]}}
    money = {'sheet':'Forecast','cell':'B1','formula':'=$A$1*2',
        'expression':['mul',ref('A1'),2], 'expected_path':['amount_pence'],
        'kind':'money_pence','worksheet_scale':100}
    bindings = {'binding_version':1, 'specification_sha256':sha, 'sheetnames':['Forecast'],
        'formula_count':2, 'financial_bindings':[money],
        'arithmetic_bindings':[deepcopy(money), {'sheet':'Forecast','cell':'C1',
            'formula':'=YEAR($A$2)','expression':['year',ref('A2')]}],
        'input_bindings':[
            {'sheet':'Forecast','cell':'A1','path':['opening_pence'],'kind':'money_pence',
                'worksheet_scale':100,'stored_value':1},
            {'sheet':'Forecast','cell':'A2','path':['when'],'kind':'date',
                'worksheet_scale':1,'epoch':'1900','stored_value':int(to_excel(datetime(2028,2,1)))},
            {'sheet':'Forecast','cell':'A3','path':['rate_p12'],'kind':'rate_p12',
                'worksheet_scale':10**12,'stored_value':.01}],
        'literal_bindings':[{'sheet':'Forecast','cell':'D1','kind':'text','value':'Terms'}]}
    book = openpyxl.Workbook(); sheet = book.active; sheet.title='Forecast'
    sheet['A1']=1; sheet['A2']=datetime(2028,2,1);sheet['A3']=.01;sheet['D1']='Terms'
    sheet['B1']=money['formula'];sheet['C1']='=YEAR($A$2)'
    path=tmp_path/'UNIT_unrecalculated.xlsx';book.save(path);book.close()
    return path,spec,result,bindings


def cached_fixture(path, *, b1='2', c1='2028', btype=None, extra=None, move_formula=False):
    """Inject explicit test-only caches, never count this as a calculation."""
    out=path.with_name('UNIT_synthetic_cached.xlsx')
    with ZipFile(path) as source, ZipFile(out,'w') as target:
        for item in source.infolist():
            raw=source.read(item.filename)
            if item.filename=='xl/worksheets/sheet1.xml':
                root=ET.fromstring(raw); ns={'x':root.tag.split('}')[0][1:]}
                for cell in root.findall('.//x:c',ns):
                    if cell.attrib['r'] in ('B1','C1'):
                        value=cell.find('x:v',ns)
                        if value is None:value=ET.SubElement(cell,'{'+ns['x']+'}v')
                        value.text=b1 if cell.attrib['r']=='B1' else c1
                    if cell.attrib['r']=='B1':
                        if btype:cell.set('t',btype)
                        if move_formula:cell.set('r','B2')
                if move_formula:
                    moved=root.find('.//x:c[@r="B2"]',ns)
                    root.find('x:sheetData/x:row[@r="1"]',ns).remove(moved)
                    root.find('x:sheetData/x:row[@r="2"]',ns).append(moved)
                if extra:
                    row=ET.SubElement(root.find('x:sheetData',ns),'{'+ns['x']+'}row',{'r':'5'})
                    cell=ET.SubElement(row,'{'+ns['x']+'}c',{'r':'E5'})
                    ET.SubElement(cell,'{'+ns['x']+'}v').text=extra
                raw=ET.tostring(root)
            target.writestr(item,raw)
    return out


def test_valid_full_unit_fixture_is_not_claimed_as_recalculation(case):
    path,spec,result,bindings=case
    report=audit.audit_workbook(cached_fixture(path),spec,result,bindings)
    assert report['passed'] and report['all_values_checked']
    assert report['physical_formulas_checked']==2 and report['financial_journal_fields_checked']==1
    assert not report['recalculation_performed'] and not report['source_admission_claimed'] and not report['qualified']
    assert report['audited_file']['sha256'] and report['independent_result_sha256']


def test_uncalculated_file_cannot_pass(case):
    path,spec,result,bindings=case
    report=audit.audit_workbook(path,spec,result,bindings)
    assert not report['passed'] and report['mismatch_count']==2


@pytest.mark.parametrize('amount',['2.01','1.99','2.005','garbage'])
def test_wrong_posted_money_is_rejected(case,amount):
    path,spec,result,bindings=case
    if amount=='garbage':
        with pytest.raises((ValueError,TypeError)):
            audit.audit_workbook(cached_fixture(path,b1=amount),spec,result,bindings)
    else:
        assert not audit.audit_workbook(cached_fixture(path,b1=amount),spec,result,bindings)['passed']


@pytest.mark.parametrize('value,type_',[('#VALUE!','e'),('1','b')])
def test_errors_and_excel_boolean_flags_do_not_become_numbers(case,value,type_):
    path,spec,result,bindings=case
    report=audit.audit_workbook(cached_fixture(path,b1=value,btype=type_),spec,result,bindings)
    assert not report['passed']
    assert report['native_error_count']==int(type_=='e')


def test_extra_value_is_not_ignored(case):
    path,spec,result,bindings=case
    report=audit.audit_workbook(cached_fixture(path,extra='42'),spec,result,bindings)
    assert not report['passed'] and report['mismatch_count']==1


def test_same_formula_count_at_wrong_coordinate_is_rejected(case):
    path,spec,result,bindings=case
    with pytest.raises(audit.ValidationError,match='positions'):
        audit.audit_workbook(cached_fixture(path,move_formula=True),spec,result,bindings)


def test_foreign_spec_or_independent_journal_is_rejected(case):
    _,spec,result,bindings=case
    result['specification_sha256']='0'*64
    with pytest.raises(audit.ValidationError,match='exact same'):
        audit.expected_values(spec,result,bindings)


def test_wrong_financial_definition_cannot_certify_itself(case):
    _,spec,result,bindings=case
    result['amount_pence']=201
    with pytest.raises(audit.ValidationError,match='independent journal'):
        audit.expected_values(spec,result,bindings)


def test_missing_or_cyclic_dependency_is_rejected(case):
    _,spec,result,bindings=case
    row=bindings['arithmetic_bindings'][1]
    row['expression']=['sum',ref('Z1')]
    with pytest.raises(audit.ValidationError,match='not bound'):
        audit.expected_values(spec,result,bindings)
    row['expression']=['sum',ref('C1')]
    with pytest.raises(audit.ValidationError,match='cycle'):
        audit.expected_values(spec,result,bindings)


def test_mismatched_alias_and_duplicate_bindings_are_rejected(case):
    _,spec,result,bindings=case
    bindings['financial_bindings'][0]['formula']='=123'
    with pytest.raises(audit.ValidationError,match='alias'):
        audit.expected_values(spec,result,bindings)
    bindings['financial_bindings'][0]['formula']='=$A$1*2'
    bindings['arithmetic_bindings'].append(deepcopy(bindings['arithmetic_bindings'][0]))
    with pytest.raises(audit.ValidationError,match='exactly one'):
        audit.expected_values(spec,result,bindings)


def test_native_input_rate_must_round_trip_to_private_integer(case):
    _,spec,result,bindings=case
    bindings['input_bindings'][2]['stored_value']=.010000000001
    with pytest.raises(audit.ValidationError,match='round-trip'):
        audit.expected_values(spec,result,bindings)


def test_sparse_vintage_zero_projection_requires_complete_month(case):
    _,_,result,bindings=case
    row=deepcopy(bindings['financial_bindings'][0]);row.update(
        expected_path=['vintage'],vintage_origin='2028-01-01',vintage_field='closing')
    assert audit._financial_value(result,row)==200
    row['vintage_origin']='2028-02-01'
    assert audit._financial_value(result,row)==0
    result['vintage']={}
    with pytest.raises(audit.ValidationError,match='complete sparse'):
        audit._financial_value(result,row)


def test_sparse_vintage_duplicates_and_broken_bridge_are_rejected(case):
    _,_,result,bindings=case
    row=deepcopy(bindings['financial_bindings'][0]);row.update(
        expected_path=['vintage'],vintage_origin='2028-01-01',vintage_field='closing')
    result['vintage']['entries'].append(deepcopy(result['vintage']['entries'][0]))
    with pytest.raises(audit.ValidationError,match='duplicated'):
        audit._financial_value(result,row)
    result['vintage']['entries'].pop();result['vintage']['entries'][0]['closing']=201
    with pytest.raises(audit.ValidationError,match='bridge'):
        audit._financial_value(result,row)


@pytest.mark.parametrize('expr,value',[
    (['rounddiv',1,2],1),(['rounddiv',-1,2],-1),(['rounddiv',-3,2],-2),
    (['ceildiv',-3,2],-1),(['floordiv',-3,2],-2),(['mod',-3,2],1),
    (['product_whole',-1,10**12+1],-2),(['product_remainder',-1,10**12+1],10**12-1),
    (['round_product',1,5*10**11],1),(['round_product',-1,5*10**11],-1),
    (['if',0,['div',1,0],7],7),(['div',1,3],Fraction(1,3)),
    (['year',46812],2028),(['month',46812],2),
])
def test_exact_arithmetic_boundaries_and_lazy_branch(expr,value):
    assert audit._evaluate(expr,{})==value


def test_flags_are_exact_and_nullable_does_not_equal_zero():
    assert not audit._matches(Fraction(49,100),Fraction(0),{'worksheet_scale':1,'kind':'flag'})
    assert not audit._matches(Fraction(0),'')
    assert audit._projection(None,{'kind':'nullable_flag','worksheet_scale':1})==''
    with pytest.raises(audit.ValidationError,match='nonnullable'):
        audit._projection(None,{'kind':'flag','worksheet_scale':1})


def test_unsupported_expression_and_large_posting_fail_closed(case):
    with pytest.raises(audit.ValidationError,match='Unsupported arithmetic'):
        audit._evaluate(['unapproved',1,2],{})
    with pytest.raises(audit.ValidationError,match='integer envelope'):
        audit._projection(2**53,{'kind':'money_pence','worksheet_scale':100})
