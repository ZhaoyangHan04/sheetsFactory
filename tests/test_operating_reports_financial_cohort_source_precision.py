"""Typing-only OOXML/ledger fixtures. No oracle forwards or native services."""
from copy import deepcopy
from decimal import Decimal,localcontext
from fractions import Fraction as F
from xml.etree import ElementTree as X
from zipfile import ZipFile,ZIP_DEFLATED

import pytest
from sheets_factory.workbook.operating_reports_financial_cohort_v1 import schema as s,source_precision as p

def decimal(q):
    q=F(q)
    with localcontext()as ctx:ctx.prec=90;return format(Decimal(q.numerator)/Decimal(q.denominator),'f')

@pytest.fixture
def sample(tmp_path):
    e={'id':'E001','name':'Typing-only fixture','division':'Advisory','layout':s.LAYOUTS[0],'line_order':s.LINE_ORDERS[0],
        'money_unit':'GBP','rate_unit':'percent_units','statement_sign':s.SIGN_BASES[0],'forecast_reference':s.REFERENCES[0],
        'driver_form_by_year':{'2026':'money_delta','2027':'money_delta'},
        'opening':{k:'0'for k in('cash','investment','debt','capital','retained_earnings')},
        'actual_sales':{q:'1'for q in s.QUARTERS[:4]},'forecast_sales':{q:'0'for q in s.QUARTERS[4:]},
        'cash_opex':{q:'0'for q in s.QUARTERS},'associate_results':{q:'0'for q in s.QUARTERS},
        'direct_cost_rate':'0','annual_interest_rate':'0','parent_tax_rate':'0'}
    public={'kind':s.KIND,'version':1,'dimension_mode':'toy','seed':s.ALLOWED_SEEDS[0],'years':list(s.YEARS),
        'base_currency':'GBP','provenance':'new hypothetical service businesses; no official workbook seed',
        'public_policy':'Typing fixture only; not an independently calculated business result.',
        'distribution':{'year':2027,'profit_percent':'20','cagr_percent':'8','q4_yoy_percent':'5'},'divisions':['Advisory'],'entities':[e]}
    return {'public':public,'path':tmp_path/'fixture.xlsx'}

def fixture(sample,money='GBP',rate='percent_units'):
    public=deepcopy(sample['public']);public['entities'][0].update(money_unit=money,rate_unit=rate)
    digest=s.canonical_sha256(public);bindings={'kind':'private_operating_reports_200_bindings','version':1,
        'specification_sha256':digest,'financial':{},'provided_facts':{},'provided_context':{}}
    result={'kind':s.RESULT_KIND,'version':1,'specification_sha256':digest,'economic_exact_values':{},
        'raw_cell_exact_values':{},'typed_2dp_values':{},'cagr_proofs':{},'reconciliation_checks':{}}
    cells={}
    for i,(key,kind)in enumerate(s.points(public),1):
        local=key.startswith('E001/');m=money if local else'GBP';r=rate if local else'percent_units';point='Report!A'+str(i)
        bindings['financial'][key]={'sheet':'Report','cell':'A'+str(i),'role':'given_NA'if kind=='text'else'report','money_unit':m,'rate_unit':r}
        if kind=='number':
            exact={'kind':'rational','value':'0'};typed={'type':'number','value':'0.00'};cells[point]=('number','0')
            if key.endswith('/cagr_percent'):
                year=int(key.split('/')[1][2:]);unit={'fraction':'100','percent_units':'1','basis_points':'1/100'}[r]
                exact={'kind':'cagr','endpoint_ratio':'1','years':year-2025,'percent_units_per_raw_unit':unit}
                result['cagr_proofs'][key]={'endpoint_ratio':'1','years':year-2025,'percent_units_per_raw_unit':unit,
                    'lower_raw':'0','upper_raw':'0','rounded':'0.00'}
        else:
            value=False if kind=='boolean'else s.GROUP_NA if key.endswith('/distribution_eligible')else s.NA
            exact={'kind':kind,'value':value};typed={'type':kind,'value':value};cells[point]=(kind,value)
        result['raw_cell_exact_values'][key]=exact;result['economic_exact_values'][key]=deepcopy(exact)
        if exact['kind']=='cagr':result['economic_exact_values'][key]['percent_units_per_raw_unit']='1'
        result['typed_2dp_values'][key]=typed
    return public,bindings,result,cells

def book(path,cells):
    root=X.Element('{'+p.S+'}worksheet');data=X.SubElement(root,'{'+p.S+'}sheetData')
    for point,(kind,value)in cells.items():
        address=point.split('!')[1];row=X.SubElement(data,'{'+p.S+'}row',r=address[1:])
        cell=X.SubElement(row,'{'+p.S+'}c',r=address,t={'number':'n','boolean':'b','text':'inlineStr','error':'e'}[kind])
        if kind=='text':X.SubElement(X.SubElement(cell,'{'+p.S+'}is'),'{'+p.S+'}t').text=str(value)
        else:X.SubElement(cell,'{'+p.S+'}v').text=('1'if value else'0')if kind=='boolean'else str(value)
    with ZipFile(path,'w',ZIP_DEFLATED)as z:
        z.writestr('xl/workbook.xml',f'<workbook xmlns="{p.S}" xmlns:r="{p.R}"><sheets><sheet name="Report" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml',X.tostring(root))
    return p.reference(path)

def point(bindings,key):
    row=bindings['financial'][key];return row['sheet']+'!'+row['cell']

def set_expected(result,key,raw,economic,typed):
    result['raw_cell_exact_values'][key]={'kind':'rational','value':str(F(raw))}
    result['economic_exact_values'][key]={'kind':'rational','value':str(F(economic))}
    result['typed_2dp_values'][key]={'type':'number','value':typed}

@pytest.mark.parametrize('money,scale',[('GBP',1),('GBP_thousands',1000),('GBP_millions',1000000)])
def test_complete_inventory_currency_conversion_and_real_one_cent_rejection(sample,money,scale):
    public,bindings,result,cells=fixture(sample,money);key='E001/2026Q1/revenue';pt=point(bindings,key)
    cells[pt]=('number',decimal(F(1,20000*scale)))
    audit=p.audit_workbook(book(sample['path'],cells),public,bindings,result)
    assert audit['passed'] and audit['checked_financial_fields']==len(list(s.points(public)))==1230
    assert audit['source_or_resource_or_quality_admission']is False and audit['E05_E06_grader_changed']is False
    for sign in(-1,1):
        cells[pt]=('number',decimal(F(sign,100*scale)))
        rejected=p.audit_workbook(book(sample['path'],cells),public,bindings,result)
        assert rejected['mismatches'][0]['reason']=='source-only numeric bound exceeded'

@pytest.mark.parametrize('rate,scale',[('fraction',F(1)),('percent_units',F(1,100)),('basis_points',F(1,10000))])
def test_rate_units_have_same_tight_dimensionless_contract_and_reject_one_bp(sample,rate,scale):
    public,bindings,result,cells=fixture(sample,rate=rate);key='E001/2026Q1/yoy_percent';pt=point(bindings,key)
    cells[pt]=('number',decimal(F(1,2*10**12)/scale))
    assert p.audit_workbook(book(sample['path'],cells),public,bindings,result)['passed']
    for sign in(-1,1):
        cells[pt]=('number',decimal(F(sign,10000)/scale))
        assert not p.audit_workbook(book(sample['path'],cells),public,bindings,result)['passed']

@pytest.mark.parametrize('field,scale',[('prior_year_multiple',F(1)),('prior_year_index',F(1,100))])
def test_index_and_multiple_convert_to_base_one(sample,field,scale):
    public,bindings,result,cells=fixture(sample);pt=point(bindings,'E001/2026Q1/'+field)
    cells[pt]=('number',decimal(F(1,2*10**12)/scale));assert p.audit_workbook(book(sample['path'],cells),public,bindings,result)['passed']
    cells[pt]=('number',decimal(F(1,10000)/scale));assert not p.audit_workbook(book(sample['path'],cells),public,bindings,result)['passed']

@pytest.mark.parametrize('key,raw,typed,actual',[('E001/2026Q1/revenue','-201/200','-1.01','-1.00499999999999'),
    ('E001/2025Q3/qoq_percent','-5/8','-0.63','-0.624999999999998')])
def test_half_boundary_is_reported_without_source_or_primary_score_rewrite(sample,key,raw,typed,actual):
    public,bindings,result,cells=fixture(sample);factor=F(1,100)if key.endswith('_percent')else F(1)
    set_expected(result,key,raw,F(raw)*factor*100 if key.endswith('_percent')else raw,typed)
    cells[point(bindings,key)]=('number',actual);audit=p.audit_workbook(book(sample['path'],cells),public,bindings,result)
    assert audit['passed'] and len(audit['round_boundary_differences'])==1
    assert audit['round_boundary_differences'][0]['oracle_2dp']==typed
    assert audit['policy']['round_boundary_only_failure_is_difficulty_evidence']is False

@pytest.mark.parametrize('mutation',['missing','extra_field','duplicate_position','wrong_unit','extra_binding_field','unknown_raw_kind','missing_CAGR','bad_CAGR_interval'])
def test_partial_or_unknown_field_unit_type_or_interval_never_passes(sample,mutation):
    public,bindings,result,cells=fixture(sample);key='E001/2026Q1/revenue'
    if mutation=='missing':bindings['financial'].pop(key)
    elif mutation=='extra_field':bindings['financial']['E001/2026Q1/unknown']=deepcopy(bindings['financial'][key])
    elif mutation=='duplicate_position':bindings['financial'][key]['cell']=bindings['financial']['E001/2025Q1/revenue']['cell']
    elif mutation=='wrong_unit':bindings['financial'][key]['money_unit']='USD'
    elif mutation=='extra_binding_field':bindings['financial'][key]['unrecognized']=True
    elif mutation=='unknown_raw_kind':result['raw_cell_exact_values'][key]['kind']='float'
    elif mutation=='missing_CAGR':result['cagr_proofs'].pop('E001/FY2027/cagr_percent')
    else:result['cagr_proofs']['E001/FY2027/cagr_percent']['lower_raw']='1/10'
    with pytest.raises((ValueError,KeyError)):p.audit_workbook(book(sample['path'],cells),public,bindings,result)

@pytest.mark.parametrize('kind,value',[('number','0'),('text','False'),('error','#VALUE!')])
def test_bool_is_never_numeric_or_textual(sample,kind,value):
    public,bindings,result,cells=fixture(sample);cells[point(bindings,'E001/FY2027/distribution_eligible')]=(kind,value)
    assert not p.audit_workbook(book(sample['path'],cells),public,bindings,result)['passed']

@pytest.mark.parametrize('key,replacement',[('E001/2025Q1/yoy_percent',('text','wrong NA')),
    ('E001/2026Q1/revenue',('text','0')),('E001/2026Q1/revenue',('error','#DIV/0!'))])
def test_text_numeric_types_and_native_errors_remain_exact(sample,key,replacement):
    public,bindings,result,cells=fixture(sample);cells[point(bindings,key)]=replacement
    assert not p.audit_workbook(book(sample['path'],cells),public,bindings,result)['passed']

@pytest.mark.parametrize('raw',['NaN','Infinity','-Infinity'])
def test_nonfinite_never_receives_an_accuracy_tolerance(sample,raw):
    public,bindings,result,cells=fixture(sample);cells[point(bindings,'E001/2026Q1/revenue')]=('number',raw)
    with pytest.raises(ValueError):p.audit_workbook(book(sample['path'],cells),public,bindings,result)

def test_missing_or_unbound_physical_cell_and_mutated_ref_fail(sample):
    public,bindings,result,cells=fixture(sample);key='E001/2026Q1/revenue';pt=point(bindings,key)
    missing=dict(cells);missing.pop(pt);assert not p.audit_workbook(book(sample['path'],missing),public,bindings,result)['passed']
    extra={**cells,'Report!B9999':('number','0')};assert not p.audit_workbook(book(sample['path'],extra),public,bindings,result)['passed']
    record=book(sample['path'],cells);sample['path'].write_bytes(sample['path'].read_bytes()+b'changed')
    with pytest.raises(ValueError,match='bytes changed'):p.audit_workbook(record,public,bindings,result)

@pytest.mark.parametrize('rate',['fraction','percent_units','basis_points'])
def test_CAGR_uses_original_interval_not_only_rounded_target(sample,rate):
    public,bindings,result,cells=fixture(sample,rate=rate);key='E001/FY2027/cagr_percent';scale={'fraction':F(1),'percent_units':F(1,100),'basis_points':F(1,10000)}[rate]
    cells[point(bindings,key)]=('number',decimal(F(1,2*10**12)/scale));assert p.audit_workbook(book(sample['path'],cells),public,bindings,result)['passed']
    cells[point(bindings,key)]=('number',decimal(F(1,10**9)/scale));assert not p.audit_workbook(book(sample['path'],cells),public,bindings,result)['passed']
