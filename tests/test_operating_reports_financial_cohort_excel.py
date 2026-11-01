from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from openpyxl import load_workbook
import pytest

from sheets_factory.workbook.operating_reports_financial_cohort_v1 import excel, schema


def toy(layout='quarter_columns',seed=202711201):
    public={'kind':schema.KIND,'version':1,'dimension_mode':'toy','seed':seed,'years':list(schema.YEARS),
        'base_currency':'GBP','provenance':'new hypothetical service businesses; no official workbook seed',
        'public_policy':'Supplied costs are positive deductions. Forecast associate results are income-positive.',
        'distribution':{'year':2027,'profit_percent':'20','cagr_percent':'8','q4_yoy_percent':'5'},
        'divisions':['Advisory'],'entities':[{'id':'E001','name':'Alder Amberwick Advisory','division':'Advisory',
        'line_order':'statement_first','layout':layout,'money_unit':'GBP','rate_unit':'percent_units',
        'statement_sign':'positive_deductions','forecast_reference':'same_quarter_last_year',
        'driver_form_by_year':{'2026':'level_multiple','2027':'level_multiple'},
        'opening':{'cash':'1000','investment':'200','debt':'100','capital':'1000','retained_earnings':'100'},
        'actual_sales':dict(zip(schema.QUARTERS[:4],('100','110','120','130'))),
        'forecast_sales':{p:'1.1' for p in schema.QUARTERS[4:]},'direct_cost_rate':'50',
        'cash_opex':{p:'10' for p in schema.QUARTERS},'annual_interest_rate':'8','parent_tax_rate':'25',
        'associate_results':dict(zip(schema.QUARTERS,['0']*4+['5','-3','7','-2']*2))}]}
    return public


@pytest.fixture(autouse=True)
def final_schema_only(monkeypatch):
    # Unit toy construction is not a genuine source/material admission.
    if excel.SCHEMA_SHA=='PENDING_COHORT_SCHEMA_PIN':
        monkeypatch.setattr(excel,'SCHEMA_SHA',excel.reference(schema.__file__)['sha256'])


def read(record):
    data=Path(record['path']).read_bytes()
    assert hashlib.sha256(data).hexdigest()==record['sha256'] and len(data)==record['bytes']
    return json.loads(data)


@pytest.mark.parametrize('layout',schema.LAYOUTS)
def test_all_six_layouts_FM_masks_NA_history_facts_and_empty_caches(tmp_path,layout):
    public=toy(layout);before=deepcopy(public);out=tmp_path/layout
    candidate=read(excel.emit(public,out));binding=read(candidate['bindings']);plan=read(candidate['view_plans'])
    assert public==before and read(candidate['specification'])==public
    assert candidate['kind']==excel.KIND and candidate['candidate_id']=='FM-C01'
    assert set(candidate['views'])=={'financial_modeling'} and plan['mode_order']==['financial_modeling']
    assert plan['FM_mask']==excel.forecast_keys(public)
    assert not (out/'debugging_input.xlsx').exists() and 'DBG_faults' not in plan
    assert candidate['matching_growth_formulas']==8
    assert candidate['financial_forwards']==candidate['actual_LO_calls']==candidate['model_calls']==0
    assert candidate['qualified'] is False and candidate['old_C00_failure_or_qualification_inherited'] is False
    source=load_workbook(candidate['source']['path']);fm=load_workbook(candidate['views']['financial_modeling']['input']['path'])
    mask={binding['financial'][key]['sheet']+'!'+binding['financial'][key]['cell'] for key in plan['FM_mask']}
    try:
        assert source.sheetnames==fm.sheetnames and source.calculation.iterate is not True
        formulas={ws.title+'!'+cell.coordinate for ws in source for cell in ws._cells.values() if cell.data_type=='f'}
        remaining={ws.title+'!'+cell.coordinate for ws in fm for cell in ws._cells.values() if cell.data_type=='f'}
        assert remaining==formulas-mask and len(formulas)==candidate['formula_count']
        for ws in source:
            for cell in ws._cells.values():
                point=ws.title+'!'+cell.coordinate
                assert fm[ws.title][cell.coordinate].value==(None if point in mask else cell.value)
        for key,kind in schema.points(public):
            row=binding['financial'][key];cell=source[row['sheet']][row['cell']]
            if kind=='boolean':assert cell.number_format=='General'
            if kind=='text':assert cell.data_type!='f' and fm[row['sheet']][row['cell']].value==cell.value
    finally:source.close();fm.close()
    for record in (candidate['source'],candidate['views']['financial_modeling']['input']):
        with ZipFile(record['path']) as archive:
            for name in archive.namelist():
                if name.startswith('xl/worksheets/sheet') and name.endswith('.xml'):
                    for cell in ET.fromstring(archive.read(name)).iter('{*}c'):
                        if cell.find('{*}f') is not None:
                            assert cell.find('{*}v') is None or cell.find('{*}v').text in (None,'')


def test_exact_decoder_rules_and_readable_brief_have_no_old_qualification(tmp_path):
    public=toy();out=tmp_path/'exact';candidate=read(excel.emit(public,out))
    rules=excel.rules(public);proof=read(candidate['rendering_proof']);bindings=read(candidate['bindings'])
    assert proof['matching_growth_fields']==len(rules)==8
    assert proof['public_policy_and_facts_changed'] is proof['financial_intermediate_rounding'] is proof['hidden_epsilon'] is False
    assert proof['specification_sha256']==schema.canonical_sha256(public)
    for key,rule in rules.items():
        assert Fraction(rule['given_decimal'])==Fraction(rule['N'],rule['D'])
        assert max(map(abs,rule['integer_terms']))<2**53
        assert Fraction(rule['distance_to_nearest_half_integer_lower_bound'])>0
        assert proof['rules'][key]['report_binding']==bindings['financial'][key]
    brief=Path(candidate['views']['financial_modeling']['instruction']['path']).read_bytes()
    assert brief==excel.BRIEF.encode() and len(brief)==403
    assert candidate['formula_helper_bytecode_unchanged'] and candidate['finite_decimal_rules_bytecode_unchanged']
    assert candidate['source_caches_seeded'] is False
    assert candidate['recipe'][str(Path(excel.__file__).resolve())]==excel.reference(excel.__file__)
    assert not any('failed' in path or 'failure' in path for path in candidate['recipe'])


def test_private_function_namespaces_and_mutable_labels_do_not_patch_original():
    first,revised=excel._namespace(toy());second,_=excel._namespace(toy(seed=202711202))
    assert first['_formula'].__code__ is excel.original._formula.__code__
    assert revised['rules'].__code__ is excel.decoder.rules.__code__
    assert first['_formula'].__globals__ is first and first is not vars(excel.original)
    assert revised['rules'].__globals__ is revised and revised is not vars(excel.decoder)
    assert first['s'] is not second['s'] and first['s'].SEED!=second['s'].SEED
    original=excel.original.LABELS['revenue'];first['LABELS']['revenue']='private test label'
    assert excel.original.LABELS['revenue']==original and second['LABELS']['revenue']==original


def test_old_material_or_unfrozen_provider_cannot_render(tmp_path,monkeypatch):
    public=toy();public['seed']=202711200
    with pytest.raises(ValueError):excel.emit(public,tmp_path/'old')
    assert not (tmp_path/'old').exists()
    monkeypatch.setattr(excel,'SCHEMA_SHA','0'*64)
    with pytest.raises(ValueError,match='pinned'):excel.emit(toy(),tmp_path/'bad_provider')
    assert not (tmp_path/'bad_provider').exists()


def test_existing_output_is_not_overwritten(tmp_path):
    out=tmp_path/'existing';out.mkdir();marker=out/'keep';marker.write_bytes(b'first attempt')
    with pytest.raises(FileExistsError):excel.emit(toy(),out)
    assert marker.read_bytes()==b'first attempt'
