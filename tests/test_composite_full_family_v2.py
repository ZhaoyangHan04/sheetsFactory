from copy import copy
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import openpyxl
import pytest

from sheets_factory.task_adapters import composite_full_family_v2 as full
from sheets_factory.task_adapters.lease_family import MAIN, NS, _paths


def workbook_with_caches(tmp_path, *, boolean=False, alias=False):
    raw, cached = tmp_path/'raw.xlsx', tmp_path/'cached.xlsx'
    w=openpyxl.Workbook()
    s=w.active;s.title='Lease P01'
    s['A17']='lease ROU open';s['A18']='lease liability open'
    s['C17']='=10';s['C18']='=0'
    if alias:
        s['C17']='=C40';s['A40']='lease rou close';s['C40']=10
        s['A41']='lease liability close';s['C41']=20
    s=w.create_sheet('Partner Waterfall');s['A29']='lp_xirr'
    s['C29']='=IF(FALSE(),.15,"")';s['E29']='=IF(TRUE(),.15,"")'
    w.create_sheet('Partner Contract')['A1']='Contract'
    w.save(raw);w.close()
    values={'Lease P01':{'C17':'10','C18':'0'},'Partner Waterfall':{'C29':'','E29':'.15'}}
    with ZipFile(raw)as zin,ZipFile(cached,'x')as zout:
        paths=_paths(zin)
        for info in zin.infolist():
            data=zin.read(info.filename)
            sheet=next((s for s,p in paths.items()if p==info.filename),None)
            if sheet in values:
                root=ET.fromstring(data)
                for cell in root.findall('.//m:sheetData/m:row/m:c',NS):
                    if cell.get('r')not in values[sheet]:continue
                    value=cell.find('m:v',NS)
                    if value is None:value=ET.SubElement(cell,'{'+MAIN+'}v')
                    value.text=values[sheet][cell.get('r')]
                    if sheet=='Partner Waterfall'and cell.get('r')=='C29':cell.set('t','str')
                    if boolean and sheet=='Lease P01'and cell.get('r')=='C18':cell.set('t','b')
                data=ET.tostring(root)
            zout.writestr(copy(info),data)
    return cached


def proposal(*args):
    return {'mask_ranges':[{'sheet':'Lease P01','range':'C17:C18'},
                           {'sheet':'Partner Waterfall','range':'E29'}]}


def test_complete_graph_counts_every_numeric_slot_and_reports_legal_xirr_reference(tmp_path,monkeypatch):
    source=workbook_with_caches(tmp_path)
    monkeypatch.setattr(full,'propose_task',proposal)
    result=full.inventory_complete_graph(source)
    assert result['formula_slots']==3
    assert result['prospective_nonzero_roots']==2
    assert result['counts_by_algorithm']['lease']=={'finite_numeric_nonzero':1,'exact_numeric_zero':1}
    assert len(result['provided_nullable_return_templates'])==1
    assert result['provided_nullable_return_templates'][0]['cell']=='C29'
    assert result['global_correct_donor_absence_claimed']is False
    assert not any('Nullable' in x for x in result['construction_blockers'])
    assert result['selected']==[]and result['actual_LO_executions']==0


def test_full_scope_bound_rejects_instead_of_slicing_roots(tmp_path,monkeypatch):
    source=workbook_with_caches(tmp_path)
    monkeypatch.setattr(full,'propose_task',proposal)
    with pytest.raises(ValueError,match='no prefix or subset'):
        full.inventory_complete_graph(source,max_roots=1)


def test_boolean_zero_is_not_a_monetary_presentation_slot(tmp_path,monkeypatch):
    source=workbook_with_caches(tmp_path,boolean=True)
    monkeypatch.setattr(full,'propose_task',proposal)
    with pytest.raises(ValueError,match='Unsupported typed'):
        full.inventory_complete_graph(source)


def test_missing_mutation_coverage_cannot_emit_a_partial_task(tmp_path,monkeypatch):
    source=workbook_with_caches(tmp_path)
    monkeypatch.setattr(full,'propose_task',proposal)
    with pytest.raises(ValueError,match='bound original full-scope inventory'):
        full.propose_complete_debugging_task(source)


def test_missing_field_mappings_return_all_failures_without_partial_plan(tmp_path,monkeypatch):
    source=workbook_with_caches(tmp_path)
    monkeypatch.setattr(full,'propose_task',lambda *args:{'mask_ranges':[{'sheet':'Lease P01','range':'C17'}]})
    scope=full.inventory_complete_graph(source)
    with pytest.raises(full.IncompleteMutationCoverage)as caught:
        full.compile_complete_mutation(source,scope)
    assert caught.value.report['compiled_root_count']==0
    assert caught.value.report['unsatisfied_roots'][0]['cell']=='C17'
    assert caught.value.report['selected']==[]


@pytest.mark.parametrize('field,before,after,mechanism',[
    ('annual cash flow','=ROUND(SUM(C3:F3),2)','=ROUND(AVERAGE(C3:F3),2)','monetary_aggregation_average'),
    ('capital closing','=ROUND(C3+C4-C5,2)','=ROUND(C3-C4-C5,2)','financial_component_posting_sign'),
    ('annual equity irr','=(1+IRR(C3:N3))^12-1','=(1+IRR(C3:N3))^1-1','return_annualisation'),
    ('lp_xirr','=IF(K36=1,ROUND(XIRR($B$27:K27,$B$2:K$2),12),"")',
     '=IF(K36=1,ROUND(XIRR($B$28:K28,$B$2:K$2),12),"")','partner_return_cashflow'),
])
def test_definition_grammar_changes_financial_operand_not_complete_wrapper(field,before,after,mechanism):
    book=openpyxl.Workbook();sheet=book.active;sheet.title='Partner Waterfall';sheet['A3']=field;sheet['C3']=before
    actual,kind,_=full._field_fault({'field':field},sheet['C3'],book,lease_groups={})
    assert actual==after and kind==mechanism
    assert before[1:]not in actual[1:]


def test_alias_fault_uses_actual_related_account_without_answer_offset():
    book=openpyxl.Workbook();sheet=book.active;sheet.title='Lease P01'
    sheet['A17']='lease rou open';sheet['C17']='=B40'
    sheet['A40']='lease rou close';sheet['A41']='lease liability close'
    actual,kind,reason=full._field_fault({'field':'lease rou open'},sheet['C17'],book,lease_groups={})
    assert actual=='=B41'and kind=='related_account_misclassification'
    assert 'lease liability close'in reason


def test_full_scope_rejects_changed_source_formula_hash(tmp_path,monkeypatch):
    source=workbook_with_caches(tmp_path)
    monkeypatch.setattr(full,'propose_task',lambda *args:{'mask_ranges':[{'sheet':'Lease P01','range':'C17'}]})
    scope=full.inventory_complete_graph(source)
    scope['families'][0]['cells'][0]['formula_sha256']='0'*64
    with pytest.raises(full.IncompleteMutationCoverage)as caught:
        full.compile_complete_mutation(source,scope)
    assert 'identity differs'in caught.value.report['unsatisfied_roots'][0]['reason']


def test_scope_duplicate_members_are_not_silently_deduplicated(tmp_path,monkeypatch):
    source=workbook_with_caches(tmp_path)
    monkeypatch.setattr(full,'propose_task',lambda *args:{'mask_ranges':[{'sheet':'Lease P01','range':'C17'}]})
    scope=full.inventory_complete_graph(source)
    scope['families'][0]['cells'].append(dict(scope['families'][0]['cells'][0]))
    with pytest.raises(ValueError,match='Duplicate'):
        full.compile_complete_mutation(source,scope)


def test_complete_api_emits_bound_normal_plan_only_for_exact_full_coverage(tmp_path,monkeypatch):
    source=workbook_with_caches(tmp_path,alias=True)
    monkeypatch.setattr(full,'propose_task',lambda *args:{'mask_ranges':[{'sheet':'Lease P01','range':'C17'}]})
    scope=full.inventory_complete_graph(source)
    plan=full.compile_complete_mutation(source,scope,{'adapter':full.ADAPTER_ID,'max_roots':100000})
    assert plan['edits'][0]['after']=='=C41'
    assert plan['family_adapter']['root_count']==1
    assert plan['family_adapter']['edits_sha256']==full.canonical_sha(plan['edits'])
    assert plan['family_adapter']['id']==full.ADAPTER_ID
    assert plan['family_adapter']['status']=='planned_not_activity_proven'
    assert plan['family_adapter']['qualified']is False


def test_full_presentation_changes_only_exact_zero_and_preserves_nullable_formula(tmp_path,monkeypatch):
    from sheets_factory.task_adapters.composite_full_presentation_v2 import present_complete_zero_schedules
    from sheets_factory.task_adapters.lease_family import compare_exact_typed
    from sheets_factory.task_adapters.presentation_source import verify_formula_allowlist
    source=workbook_with_caches(tmp_path)
    monkeypatch.setattr(full,'propose_task',proposal)
    scope=full.inventory_complete_graph(source)
    destination=tmp_path/'presented.xlsx'
    report=present_complete_zero_schedules(source,destination,scope)
    assert report['converted_formula_count']==1
    assert compare_exact_typed(source,destination,public_note=report['public_note'])['passed']
    assert verify_formula_allowlist(source,destination,report['conversions'])['passed']
    w=openpyxl.load_workbook(destination)
    assert w['Lease P01']['C18'].value == 0 and w['Lease P01']['C18'].data_type != 'f'
    assert w['Partner Waterfall']['C29'].data_type=='f'
    w.close()
    with pytest.raises(ValueError,match='immutable'):
        present_complete_zero_schedules(source,destination,scope)


def test_full_presentation_rejects_foreign_scope_source(tmp_path,monkeypatch):
    from sheets_factory.task_adapters.composite_full_presentation_v2 import present_complete_zero_schedules
    source=workbook_with_caches(tmp_path)
    monkeypatch.setattr(full,'propose_task',proposal)
    scope=full.inventory_complete_graph(source)
    scope['source']['sha256']='0'*64
    with pytest.raises(ValueError,match='not bound'):
        present_complete_zero_schedules(source,tmp_path/'out.xlsx',scope)


def test_complete_operand_guard_observes_token_boundaries():
    assert not full._retains_complete_operand('=C3','=C30')
    assert full._retains_complete_operand('=C3+C4','=ROUND((C3+C4)*2,2)')


@pytest.mark.parametrize('sheet,label,role',[
    ('Lease P01','rou after measurement','measurement'),
    ('Reopener Claims','2030 close','vintage'),
    ('Operating Tax Vintages','interest v2 used','vintage'),
    ('Holding Statements','claims_collateral','funding'),
    ('Partner Waterfall','lp_return_of_capital','distribution'),
    ('Operating Equity Value','annual equity irr','return'),
])
def test_fault_design_roles_are_business_specific(sheet,label,role):
    assert full.field_role(sheet,label)==role
