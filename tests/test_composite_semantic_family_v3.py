"""Offline mutation coverage and graph-safety checks; no engine or model calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import openpyxl
from openpyxl.formula.tokenizer import Tokenizer
import pytest

from sheets_factory.task_adapters import composite_semantic_family_v3 as semantic
from sheets_factory.task_adapters.lease_family import MAIN, NS, _paths


def policy(seed=19):
    return {'adapter':semantic.ADAPTER_ID,'seed':seed,'max_roots':100000,
            'compound_nonalias_definitions':True}


def source_and_scope(tmp_path):
    raw=tmp_path/'raw.xlsx';source=tmp_path/'source.xlsx'
    w=openpyxl.Workbook();s=w.active;s.title='Operating Operations'
    for row,label in [(4,'cash open'),(5,'debt draw'),(6,'cash out'),(7,'cash close'),(8,'total depreciation')]:s.cell(row,1,label)
    for col in ('C','D'):
        for row,value in [(4,10),(5,5),(6,2)]:s[f'{col}{row}']=value
        s[f'{col}7']="=ROUND('Operating Scenario'!B21+'Operating Scenario'!B22-'Operating Scenario'!B13,2)"
    s['C8']=0;s['D8']='=SUM(C4:D4)'
    inp=w.create_sheet('Operating Scenario')
    for row,label,value in [(21,'opening_cash',10),(22,'equity_paid_in',5),(13,'startup_expense',2)]:
        inp.cell(row,1,label);inp.cell(row,2,value)
    p=w.create_sheet('Partner Contract');p['A1']='Unchanged public contract'
    w.save(raw);w.close()
    with ZipFile(raw)as zin,ZipFile(source,'x')as zout:
        paths=_paths(zin)
        for info in zin.infolist():
            data=zin.read(info.filename)
            if info.filename==paths['Operating Operations']:
                doc=ET.fromstring(data)
                for c in doc.findall('.//m:sheetData/m:row/m:c',NS):
                    if c.get('r')not in {'C7','D7','D8'}:continue
                    value=c.find('m:v',NS)
                    if value is None:value=ET.SubElement(c,'{'+MAIN+'}v')
                    value.text='20'if c.get('r')=='D8'else'13'
                data=ET.tostring(doc)
            zout.writestr(info,data)
    b=openpyxl.load_workbook(source)
    families=[]
    for row,field in [(7,'cash close'),(8,'total depreciation')]:
        cells=[]
        for col in ('C','D'):
            c=b['Operating Operations'][f'{col}{row}'];zero=c.value==0
            item={'cell':c.coordinate,'source_kind':'exact_numeric_zero'if zero else'finite_numeric_nonzero'}
            if not zero:item['formula_sha256']=hashlib.sha256(c.value.encode()).hexdigest()
            cells.append(item)
        families.append({'algorithm':'operating','sheet':'Operating Operations','row':row,
                         'field':field,'role':'cash_settlement','cells':cells})
    b.close()
    return source,{'adapter':semantic.SCOPE_ID,'families':families,'prospective_nonzero_roots':3,
                   'source':{'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}}


def test_complete_seeded_compilation_is_deterministic_without_mutating_source(tmp_path):
    source,scope=source_and_scope(tmp_path);before=source.read_bytes()
    r=semantic.compile_semantic_report(source,scope,policy())
    assert r['offline_compile_complete']and r['root_count']==r['compiled_root_count']==3
    assert r['family_count']==2 and r['provided_zero_count']==1
    assert r['unsatisfied_roots']==[]and r['actual_LO_calls']==r['model_calls']==0
    assert r['qualified']is False and r['global_correct_donor_absence_claimed']is False
    assert all(e['after']!=e['before']for e in r['edits'])
    assert all(not semantic._retains_complete_operand(e['before'],e['after'])for e in r['edits'])
    again=semantic.compile_semantic_report(source,scope,policy())
    assert again['edits_sha256']==r['edits_sha256']
    assert source.read_bytes()==before
    variants={semantic.compile_semantic_report(source,scope,policy(seed))['edits_sha256']for seed in range(5)}
    assert len(variants)>1


def test_no_partial_plan_on_formula_identity_or_missing_policy(tmp_path):
    source,scope=source_and_scope(tmp_path)
    scope['families'][0]['cells'][0]['formula_sha256']='0'*64
    scope['families'][0]['cells'][1]['formula_sha256']='1'*64
    with pytest.raises(semantic.SemanticCoverageError)as error:
        semantic.compile_semantic_mutation(source,scope,policy())
    assert len(error.value.report['unsatisfied_roots'])==2
    assert error.value.report['root_count']==3
    assert error.value.report['selected']==[]


def test_no_root_prefix_or_deduplication_is_permitted(tmp_path):
    source,scope=source_and_scope(tmp_path)
    with pytest.raises(ValueError,match='no subset'):
        semantic.compile_semantic_report(source,scope,{**policy(),'max_roots':2})
    scope['families'][0]['cells'].append(deepcopy(scope['families'][0]['cells'][0]))
    with pytest.raises(ValueError,match='duplicate'):
        semantic.compile_semantic_report(source,scope,policy())


@pytest.mark.parametrize('value',[True,False,None,'0',float('inf'),float('nan')])
def test_finite_numeric_filter_does_not_imply_a_money_unit(value):
    w=openpyxl.Workbook();c=w.active['A1'];c.value=value
    assert semantic._money(c)is False


def test_original_graph_is_fully_expanded_and_new_back_edges_are_rejected():
    w=openpyxl.Workbook();s=w.active;s.title='S'
    s['C3']='=C2';s['C4']='=SUM(C3:D3)';s['D3']=2;s['C2']=1
    s['Z3']='=C4';s['AA3']='=Z3';s['C9']='=1'  # outside the ancestor graph
    order=semantic.DependencyOrder(w,{'S!C4','S!Z3','S!AA3'})
    assert order.refs['S!C4']=={'S!C3','S!D3'}
    assert order.allowed('S!C4','S!C3')
    assert order.allowed('S!AA3','S!Z3')
    assert not order.allowed('S!C3','S!C4')
    assert not order.allowed('S!C4','S!C4')
    assert not order.allowed('S!C4','S!C9')
    assert order.allowed('S!C4','S!D3')
    assert semantic._ordered_options('S!C3',[('=C4','wrong','wrong')],order)==[]
    assert order.summary['complete_reference_expansion']is True


def test_existing_economic_scc_makes_no_counterfactual_uniqueness_claim():
    w=openpyxl.Workbook();s=w.active;s.title='S';s['C3']='=C4';s['C4']='=C3';s['C5']='=C3'
    order=semantic.DependencyOrder(w,{'S!C5'})
    assert order.summary['original_cyclic_SCC_count']==1
    assert order.allowed('S!C3','S!C4')
    assert not order.allowed('S!C3','S!C5')
    assert order.summary['erroneous_counterfactual_global_uniqueness_claimed']is False


def test_unsupported_original_dependency_is_rejected_not_ignored():
    w=openpyxl.Workbook();s=w.active;s.title='S';s['C3']='=INDIRECT("D3")'
    with pytest.raises(ValueError,match='Unsupported original'):
        semantic.DependencyOrder(w,{'S!C3'})


def test_vertical_operating_calendar_uses_earlier_rows_not_different_currency_columns():
    w=openpyxl.Workbook();s=w.active;s.title='Holding Operating Link'
    for row in (3,4,5):
        for col in ('C','D','G'):s[f'{col}{row}']=10+row
    s['G6']='=G5';money={f'Holding Operating Link!{c}{r}'for c in ('C','D','G')for r in (3,4,5)}
    order=semantic.DependencyOrder(w,{'Holding Operating Link!G6'})
    opts=semantic._binding_options({'field':'income_gbp'},s['G6'],Tokenizer(s['G6'].value).items,w,w,money,order)
    stale=[o for o in opts if o[1].startswith('stale_')]
    assert stale and all("'Holding Operating Link'!G"in o[0]for o in stale)
    assert not any("'Holding Operating Link'!D5"in o[0]for o in stale)


def test_primitive_money_filter_excludes_rate_and_period_inputs():
    w=openpyxl.Workbook();s=w.active;s.title='Operating Scenario'
    for row,label,value in [(4,'steady_annual_sales',30),(5,'cash_cogs_fraction',.55),
        (6,'construction_months',6),(13,'startup_expense',20),(21,'opening_cash',3),(22,'equity_paid_in',8)]:
        s.cell(row,1,label);s.cell(row,2,value)
    keys=semantic._primitive_money_keys(w,w)
    assert keys=={'Operating Scenario!B4','Operating Scenario!B13','Operating Scenario!B21','Operating Scenario!B22'}


def test_period_denominator_fault_uses_a_labelled_count_not_an_answer_offset():
    w=openpyxl.Workbook();s=w.active;s.title='Operating Operations'
    inp=w.create_sheet('Operating Scenario');inp['A6']='construction_months';inp['B6']=6
    s['C5']="=ROUND(200/'Operating Scenario'!$B$6,2)"
    opts=semantic._definition_options({'field':'startup expense','role':'measurement'},s['C5'],Tokenizer(s['C5'].value).items,set(),w,w)
    assert any(o[1]=='inclusive_financial_period_count'and"/('Operating Scenario'!$B$6+1)"in o[0]for o in opts)
    assert all(not semantic._retains_complete_operand(s['C5'].value,o[0])for o in opts)


def test_simple_round_alias_is_not_misreported_as_a_total_component_fault():
    w=openpyxl.Workbook();s=w.active;s.title='Operating Annual Statements'
    cf=w.create_sheet('Operating Cash Flow');inp=w.create_sheet('Operating Scenario')
    inp['A21']='opening_cash';inp['B21']=10;inp['A22']='equity_paid_in';inp['B22']=20
    cf['A2']='cash open';cf['C2']="=ROUND('Operating Scenario'!B21,2)"
    s['C19']="='Operating Cash Flow'!C2"
    values=deepcopy(w);values['Operating Cash Flow']['C2']=10
    money={'Operating Cash Flow!C2','Operating Scenario!B21','Operating Scenario!B22'}
    order=semantic.DependencyOrder(w,{'Operating Annual Statements!C19'})
    opts=semantic._binding_options({'field':'cash open'},s['C19'],Tokenizer(s['C19'].value).items,w,values,money,order)
    assert not any(o[1]=='component_instead_of_total'for o in opts)
    assert any(o[1]=='related_provided_account'and'!B22'in o[0]for o in opts)


def test_plan_uses_distinct_mutation_provider_without_relabelling_source_admission(tmp_path):
    source,scope=source_and_scope(tmp_path)
    plan=semantic.compile_semantic_mutation(source,scope,policy())
    assert plan['family_adapter']['id']==semantic.ADAPTER_ID
    assert scope['adapter']==semantic.SCOPE_ID
    assert semantic.INPUT_PRIORITY_RULE in plan['public_rules']
    assert plan['reference_evidence']and plan['mask_ranges']==[]
    assert plan['family_adapter']['status']=='planned_not_execution_proven'
    assert plan['family_adapter']['difficulty_measured']is False


def test_v3_repository_policy_is_explicit_and_not_authority_to_execute():
    p=json.loads(Path('config/task_adapters/composite_semantic_graph_v3.json').read_text())
    semantic.validate_policy(p)
    assert p['no_whole_correct_formula_wrapper']and p['no_root_subset_or_truncation']
    assert p['LO_calls_authorized_by_config']is False and p['model_calls_authorized_by_config']is False
