"""Offline typed serialization and restricted-selector proofs. Zero actual LO."""
from copy import deepcopy
from datetime import datetime
import importlib.util
from pathlib import Path
from xml.etree import ElementTree as ET
import pytest
import openpyxl
from openpyxl.utils.datetime import CALENDAR_MAC_1904, CALENDAR_WINDOWS_1900

spec=importlib.util.spec_from_file_location('_v8_offline_fixtures',Path(__file__).with_name('test_scc_island_roots_v8.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
scc=fixtures.scc
NS=fixtures.NS


def scalar_file(tmp_path,value,*,epoch=CALENDAR_WINDOWS_1900,date_serial=None):
    path=tmp_path/'source.xlsx';book=openpyxl.Workbook();book.active.title='Inputs';book.epoch=epoch
    cell=book['Inputs']['A1'];cell.value=value
    if isinstance(value,str):cell.data_type='s'
    if date_serial is not None:cell.number_format='yyyy-mm-dd hh:mm:ss.000'
    book.save(path);book.close()
    if date_serial is not None:
        fixtures.patch_cell(path,1,'A1',cached=date_serial)
    return path


def snapshot(path,target):
    definitions=openpyxl.load_workbook(path);values=openpyxl.load_workbook(path,data_only=True)
    try:
        descriptor=scc._typed_boundary(definitions['Inputs']['A1'],values['Inputs']['A1'],
            scc._raw_cells(path).get(('Inputs','A1')),definitions.epoch)
        definitions.create_sheet('__SCI_R_0000')
        scc._assign_boundary(definitions['__SCI_R_0000']['A1'],values['Inputs']['A1'],descriptor)
        definitions.save(target)
        record={'source_cell':['Inputs','A1'],'snapshot_cell':['__SCI_R_0000','A1'],'descriptor':descriptor}
        scc._preserve_raw_date_serials(target,[record])
        return descriptor
    finally:definitions.close();values.close()


def check_snapshot(path,descriptor):
    definitions=openpyxl.load_workbook(path);values=openpyxl.load_workbook(path,data_only=True)
    try:scc._check_boundary(descriptor,definitions['__SCI_R_0000']['A1'],values['__SCI_R_0000']['A1'],
        scc._raw_cells(path)['__SCI_R_0000','A1'],definitions.epoch)
    finally:definitions.close();values.close()


@pytest.mark.parametrize('value',[False,True,0,1,'FALSE','1','=SUM(1,2)','  λ\t文字  ','2024-01-01'])
def test_typed_literal_roundtrip_preserves_type_and_prevents_formula_coercion(tmp_path,value):
    source=scalar_file(tmp_path,value);target=tmp_path/'snapshot.xlsx';descriptor=snapshot(source,target)
    check_snapshot(target,descriptor)
    book=openpyxl.load_workbook(target)
    try:
        assert book['__SCI_R_0000']['A1'].data_type!='f'
        assert type(book['__SCI_R_0000']['A1'].value) is type(value)
        assert book['__SCI_R_0000']['A1'].value==value
    finally:book.close()


@pytest.mark.parametrize('epoch',[CALENDAR_WINDOWS_1900,CALENDAR_MAC_1904])
@pytest.mark.parametrize('serial',['59','60','61','45000.123456789123456'])
def test_date_original_binary_serial_epoch_and_style_survive_without_datetime_roundtrip(tmp_path,epoch,serial):
    source=scalar_file(tmp_path,datetime(2024,1,1),epoch=epoch,date_serial=serial)
    target=tmp_path/'snapshot.xlsx';descriptor=snapshot(source,target);check_snapshot(target,descriptor)
    assert descriptor['raw_date_serial']==serial
    assert descriptor['date_serial_binary64']==float(serial).hex()
    assert scc._raw_cells(target)['__SCI_R_0000','A1']['v_text']==serial


@pytest.mark.parametrize('defect',['epoch','style','raw_serial','boolean_to_number','text_to_formula'])
def test_snapshot_type_epoch_style_and_raw_serial_tampering_rejects(tmp_path,defect):
    value={'boolean_to_number':True,'text_to_formula':'=1+1'}.get(defect,datetime(2024,1,1))
    source=scalar_file(tmp_path,value,date_serial='60' if isinstance(value,datetime) else None)
    target=tmp_path/'snapshot.xlsx';descriptor=snapshot(source,target)
    if defect=='raw_serial':fixtures.patch_cell(target,2,'A1',cached='59')
    else:
        b=openpyxl.load_workbook(target)
        if defect=='epoch':b.epoch=CALENDAR_MAC_1904
        elif defect=='style':b['__SCI_R_0000']['A1'].number_format='0.00'
        elif defect=='boolean_to_number':b['__SCI_R_0000']['A1']=1
        else:b['__SCI_R_0000']['A1']='=1+1'
        b.save(target);b.close()
    with pytest.raises(ValueError):check_snapshot(target,descriptor)


@pytest.mark.parametrize('value',[None,''])
def test_blank_and_empty_text_are_still_rejected(tmp_path,value):
    source=scalar_file(tmp_path,value)
    with pytest.raises(ValueError,match='Blank|missing'):
        snapshot(source,tmp_path/'snapshot.xlsx')


@pytest.mark.parametrize('formula',['=ISFORMULA(A1)','=CELL("type",A1)','=FORMULATEXT(A1)','=INFO("system")'])
def test_metadata_introspection_remains_forbidden(formula):
    with pytest.raises(ValueError):scc._pure(formula,'S!B1')


@pytest.mark.parametrize('value',[True,'plain text',datetime(2024,1,1)])
def test_typed_boundaries_complete_six_offline_fixture_recalculations(tmp_path,value):
    original={'A1':'=Inputs!B1+N(Inputs!E30)'};changed={'A1':'=Inputs!B1*2+N(Inputs!E30)'}
    paths=fixtures.fixture(tmp_path,original=original,changed=changed,extra_inputs={'E30':value})
    proof=fixtures.prove(tmp_path,paths)
    assert proof['passed'],proof.get('reason')
    assert proof['actual_LO_execution_count']==6
    assert scc.validate_scc_island_root_certificate(proof,*paths)==proof['root_impacts']
    assert any(r['descriptor']['kind']!='number' for r in proof['contexts'][0]['fixed_point_residual']['typed_boundary_records'])


@pytest.mark.parametrize('defect',['kind','cachetype','style','epoch','serial','mapping','coverage'])
def test_persisted_typed_descriptor_tamper_rejects_even_if_digest_recomputed(tmp_path,defect):
    paths=fixtures.fixture(tmp_path);proof=fixtures.prove(tmp_path,paths);assert proof['passed']
    residual=proof['contexts'][0]['fixed_point_residual'];records=residual['typed_boundary_records']
    if defect=='mapping':records[0]['snapshot_cell'][1]='Z99'
    elif defect=='coverage':records.pop()
    else:
        descriptor=records[0]['descriptor']
        descriptor[{'kind':'kind','cachetype':'source_raw_cache_type','style':'style_semantics_sha256','epoch':'epoch','serial':'raw_date_serial'}[defect]]='TAMPER'
    residual['frozen_values_sha256']=scc._digest([[scc._label(tuple(r['source_cell'])),r['descriptor']] for r in records])
    with pytest.raises(ValueError):scc.validate_scc_island_root_certificate(proof,*paths)


def index_books(tmp_path,*,month=7,selector='6',array_values=(.5,.6,.75,1,1,1),guarded=True):
    path=tmp_path/'index.xlsx';book=openpyxl.Workbook();book.active.title='Calendar';book.create_sheet('Scenario')
    book['Calendar']['C2']='='+str(month);book['Scenario']['B6']=int(selector)
    for row,value in enumerate(array_values,7):book['Scenario'].cell(row,2,value)
    index="INDEX('Scenario'!$B$7:$B$12,'Calendar'!C2-'Scenario'!$B$6)"
    formula=("=IF('Calendar'!C2<='Scenario'!$B$6,0,IF('Calendar'!C2>'Scenario'!$B$6+6,1,"+index+'))') if guarded else '='+index
    book['Calendar']['C8']=formula;book.save(path);book.close()
    fixtures.patch_cell(path,1,'C2',cached=month)
    result=0 if month<=int(selector) else 1 if month>int(selector)+6 else array_values[month-int(selector)-1]
    fixtures.patch_cell(path,1,'C8',cached=result)
    if isinstance(result,(str,bool)):
        def typed_cache(name,raw):
            if name!='xl/worksheets/sheet1.xml':return raw
            tree=ET.fromstring(raw)
            cell=next(c for c in tree.iter(NS+'c') if c.attrib['r']=='C8')
            cell.attrib['t']='b' if isinstance(result,bool) else 'str'
            cell.find(NS+'v').text=('1' if result else '0') if isinstance(result,bool) else result
            return ET.tostring(tree)
        fixtures.rewrite(path,typed_cache)
    second=tmp_path/'combined.xlsx';second.write_bytes(path.read_bytes())
    books=[openpyxl.load_workbook(path),openpyxl.load_workbook(second)]
    values=[openpyxl.load_workbook(path,data_only=True),openpyxl.load_workbook(second,data_only=True)]
    return path,second,books,values


def index_proof(books,values,*,roots=(),context=0):
    text=books[context]['Calendar']['C8'].value
    return scc._constant_index_ancestor(text,('Calendar','C8'),*books,values,set(roots),context,50000)


@pytest.mark.parametrize('month',range(1,37))
def test_all_thirty_six_actual_index_pattern_positions_have_proven_constant_branches(tmp_path,month):
    _,_,books,values=index_books(tmp_path,month=month)
    try:
        rewritten,proof=index_proof(books,values)
        expected='=0' if month<=6 else '=1' if month>12 else "='Scenario'!B"+str(month)
        assert rewritten==expected
        assert proof['selector_decided_from_cache'] is False
        assert proof['business_formula_rewritten'] is False
        assert len(proof['index_calls'][0]['entire_original_array'])==6
        assert proof['index_calls'][0]['used']==(7<=month<=12)
        assert len(proof['guards'])==(1 if month<=6 else 2)
    finally:
        for b in books+values:b.close()


@pytest.mark.parametrize('defect',['root_index','changed_selector','root_controlled_selector','cache_contradiction','dynamic_selector','formula_selector_function','fractional_selector','live_out_of_range','horizontal_array'])
def test_index_restricted_extension_rejects_unproven_or_dynamic_cases(tmp_path,defect):
    _,_,books,values=index_books(tmp_path,month=1 if defect=='live_out_of_range' else 7,guarded=defect!='live_out_of_range')
    roots=set()
    try:
        if defect=='root_index':roots.add(('Calendar','C8'))
        elif defect=='changed_selector':books[1]['Scenario']['B6']=5
        elif defect=='root_controlled_selector':
            for b in books:b['Scenario']['B6']='=Scenario!B5';b['Scenario']['B5']=6
            for b in values:b['Scenario']['B5']=6
            roots.add(('Scenario','B5'))
        elif defect=='cache_contradiction':values[0]['Calendar']['C2']=8
        elif defect=='dynamic_selector':
            for b in books:b['Calendar']['C8']="=INDEX('Scenario'!$B$7:$B$12,RAND())"
        elif defect=='formula_selector_function':
            for b in books:b['Calendar']['C2']='=SUM(6,1)'
        elif defect=='fractional_selector':
            for b in books:b['Calendar']['C2']='=7.5'
        elif defect=='horizontal_array':
            for b in books:b['Calendar']['C8']="=INDEX('Scenario'!$B$7:$G$7,1)"
        with pytest.raises(ValueError):index_proof(books,values,roots=roots)
    finally:
        for b in books+values:b.close()


def test_index_selected_text_or_boolean_preserves_typed_dependency_not_numeric_coercion(tmp_path):
    _,_,books,values=index_books(tmp_path,array_values=('label',True,.75,1,1,1))
    try:
        rewritten,proof=index_proof(books,values)
        assert rewritten=="='Scenario'!B7"
        assert proof['index_calls'][0]['selected_typed_value']==['string','label']
    finally:
        for b in books+values:b.close()


def test_opt_in_index_union_retains_entire_original_array_and_dead_guard_refs(tmp_path):
    _,_,books,values=index_books(tmp_path,month=30)
    try:
        for b in books:b['Calendar']['A1']='=C8*2'
        books[1]['Calendar']['A1']='=C8*3'
        for i,b in enumerate(values):b['Calendar']['A1']=2 if i==0 else 3
        edits=[{'sheet':'Calendar','cell':'A1','before':'=C8*2','after':'=C8*3'}]
        with pytest.raises(ValueError,match='INDEX'):
            scc._union_plan(*books,values,edits,max_cells=100,max_edges=1000,per_formula=100)
        graph,expanded,_,_,receipt=scc._union_plan(*books,values,edits,max_cells=100,max_edges=1000,
            per_formula=100,allow_constant_index_ancestors=True)
        assert graph['Calendar','C8'] >= {('Scenario','B'+str(row)) for row in range(6,13)}
        assert ('Calendar','C2') in graph['Calendar','C8']
        assert expanded[0,('Calendar','C8')]=='=1'
        assert receipt['constant_INDEX_extension']['proof_count']==2
        assert receipt['constant_INDEX_extension']['all_original_references_retained'] is True
    finally:
        for b in books+values:b.close()


def full_index_paths(tmp_path,month=7):
    goal,combined,books,values=index_books(tmp_path,month=month)
    for b in books+values:b.close()
    amount=0 if month<=6 else 1 if month>12 else (.5,.6,.75,1,1,1)[month-7]
    for path,factor in ((goal,2),(combined,3)):
        book=openpyxl.load_workbook(path);book['Calendar']['A1']='=C8*'+str(factor);book.save(path);book.close()
        fixtures.patch_cell(path,1,'C2',cached=month);fixtures.patch_cell(path,1,'C8',cached=amount)
        fixtures.patch_cell(path,1,'A1',cached=amount*factor)
    return goal,combined,[{'sheet':'Calendar','cell':'A1','before':'=C8*2','after':'=C8*3'}]


@pytest.mark.parametrize('month',[7,30])
def test_index_opt_in_six_fixture_calls_and_persisted_source_proof_replay(tmp_path,month):
    paths=full_index_paths(tmp_path,month);proof=fixtures.prove(tmp_path,paths,allow_constant_index_ancestors=True)
    assert proof['passed'],proof.get('reason')
    assert proof['actual_LO_execution_count']==6
    assert scc.validate_scc_island_root_certificate(proof,*paths)==proof['root_impacts']
    assert proof['union_graph']['constant_INDEX_extension']['proof_count']==2


@pytest.mark.parametrize('defect',['selector','guard','array','anchor','omit','enabled'])
def test_index_proof_tamper_rejected_even_after_proof_digest_recomputed(tmp_path,defect):
    paths=full_index_paths(tmp_path);proof=fixtures.prove(tmp_path,paths,allow_constant_index_ancestors=True)
    assert proof['passed'],proof.get('reason')
    extension=proof['union_graph']['constant_INDEX_extension'];record=extension['proofs'][0]
    if defect=='selector':record['index_calls'][0]['row']=2
    elif defect=='guard':record['guards'][0]['selected_argument']=1
    elif defect=='array':record['index_calls'][0]['entire_original_array'][0]['original_typed_cache']=['number','999']
    elif defect=='anchor':record['anchor']='Calendar!A1'
    elif defect=='omit':extension['proofs'].pop()
    else:extension['enabled']=False
    extension['proofs_sha256']=scc._digest(extension['proofs'])
    with pytest.raises(ValueError):scc.validate_scc_island_root_certificate(proof,*paths)


@pytest.mark.parametrize('cache_encoding',['empty_string','missing','error'])
def test_formula_empty_missing_or_error_cache_is_never_coerced_to_blank_literal(tmp_path,cache_encoding):
    path=tmp_path/'formula_boundary.xlsx';book=openpyxl.Workbook();book.active.title='Inputs'
    book['Inputs']['A1']='=""';book.save(path);book.close()
    def patch(name,payload):
        if name!='xl/worksheets/sheet1.xml':return payload
        tree=ET.fromstring(payload);cell=next(tree.iter(NS+'c'));value=cell.find(NS+'v')
        if cache_encoding=='missing':
            if value is not None:cell.remove(value)
        else:
            cell.attrib['t']='e' if cache_encoding=='error' else 'str'
            if value is None:value=ET.SubElement(cell,NS+'v')
            value.text='#N/A' if cache_encoding=='error' else ''
        return ET.tostring(tree)
    fixtures.rewrite(path,patch)
    with pytest.raises(ValueError):snapshot(path,tmp_path/'snapshot.xlsx')


def test_iso_date_encoding_is_explicitly_unsupported(tmp_path):
    source=tmp_path/'iso.xlsx';book=openpyxl.Workbook();book.active.title='Inputs';book.iso_dates=True
    book['Inputs']['A1']=datetime(2024,1,1);book.save(source);book.close()
    with pytest.raises(ValueError,match='date cache encoding'):snapshot(source,tmp_path/'snapshot.xlsx')


@pytest.mark.parametrize('formula',['=7/2','=9007199254740992+1','=ABS(7)','=Calendar!C2'])
def test_selector_noninteger_overflow_function_and_cycle_are_rejected(tmp_path,formula):
    _,_,books,values=index_books(tmp_path)
    try:
        for b in books:b['Calendar']['C2']=formula
        with pytest.raises(ValueError):index_proof(books,values)
    finally:
        for b in books+values:b.close()
