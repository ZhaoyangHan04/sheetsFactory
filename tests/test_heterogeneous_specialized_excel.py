"""Tiny uncalculated native books; no independent journal, LO or source run."""
import ast
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from openpyxl import Workbook
import pytest

from sheets_factory.workbook.heterogeneous_contracts import excel as original
from sheets_factory.workbook.heterogeneous_contracts import policy_specialization as compiler
from sheets_factory.workbook.heterogeneous_contracts import specialized_excel as specialized
from sheets_factory.workbook.heterogeneous_contracts.spec import SCALE,load_spec


def toy(types=('BULLET_MONTHLY','BULLET_QUARTERLY_ACCRUAL')):
    months=['2027-01-01','2027-02-01','2027-03-01'];ids=[f'E{i+1:02d}' for i in range(len(types))]
    s={'schema_version':1,'kind':'hypothetical_heterogeneous_contracts_private_construction_spec',
       'dimension_mode':'toy','start_month':months[0],'months':months,'scenario_ids':['S01'],'currency':'GBP','rate_scale':SCALE,
       'entities':[],'loans':[],'assets':[],'operating_inputs':{},'scenarios':[],
       'group':{'name':'Small structural portfolio','bank_funding_priority':ids,'shared_margin_priority':ids,
         'lp_funding_priority':ids,'additional_lp_commitment_pence':100000000,
         'shared_bank_limit_schedule':[{'effective_month':months[0],'limit_pence':3000000*len(ids)}]}}
    for i,(eid,typ) in enumerate(zip(ids,types)):
        s['entities'].append({'id':eid,'name':'Public entity '+eid,'functional_currency':'GBP',
          'opening_cash_pence':2000000,'opening_restricted_cash_pence':0,'opening_paid_in_capital_pence':1000000,
          'opening_retained_earnings_pence':0,'opening_tax_payable_pence':0,'opening_interest_carry':[],
          'opening_tax_losses':[],'minimum_cash_pence':100000,'reserve_target_pence':200000,
          'additional_lp_commitment_pence':100000000,'tax_policy':'ACCRUAL_MONTHLY' if i%2==0 else 'CASH_COUPON_QUARTERLY',
          'tax_rate_p12':250000000000,'interest_cap_fraction_p12':300000000000,'interest_carry_months':2,
          'loss_carry_months':2,'dscr_policy':'MONTHLY_CURRENT' if i%2==0 else 'QUARTERLY_LAGGED',
          'dscr_threshold_p12':1150000000000,'opening_trap':False,'opening_cure_count':0})
        lid=f'L{i+1:02d}'
        s['loans'].append({'id':lid,'entity_id':eid,'type':typ,'opening_principal_pence':1000000,
          'opening_accrued_interest_pence':0,'terms':[{'id':lid+'@'+months[0],'effective_month':months[0],
          'annual_rate_p12':120000000000,'day_count':'ACT_365F','local_limit_pence':3000000,
          'maturity_date':'2028-12-31','draw_cutoff_month':None if typ=='LEVEL_PRINCIPAL_MONTHLY' else '2028-09-01',
          'optional_repayment_fraction_p12':0,'next_coupon_month':months[2] if typ=='BULLET_QUARTERLY_ACCRUAL' else None}]})
        s['operating_inputs'][eid]=[{'month':m,'base_cash_revenue_pence':1000000,'base_cash_opex_pence':600000} for m in months]
    s['scenarios']=[{'id':'S01','name':'Public scenario','monthly_schedule':[{'month':m,'revenue_factor_p12':SCALE,
        'opex_factor_p12':SCALE,'annual_rate_spread_p12':0} for m in months]}]
    return load_spec(s)


def emit(public=None):
    book=Workbook();bindings=specialized.emit_heterogeneous_workbook(book,toy() if public is None else public)
    return book,bindings


def key(row):return row['sheet'],row['cell']


@pytest.mark.parametrize('typ',['BULLET_MONTHLY','LEVEL_PRINCIPAL_MONTHLY','BULLET_QUARTERLY_ACCRUAL'])
def test_complete_tiny_source_financial_metadata_units_and_definitions(typ):
    public=toy((typ,));baseline=Workbook();old=original.emit_heterogeneous_workbook(baseline,public)
    book,new=emit(public)
    assert [compiler._identity(r) for r in new['financial_bindings']]==[compiler._identity(r) for r in old['financial_bindings']]
    assert new['input_bindings']==old['input_bindings']
    assert new['public_notes']==old['public_notes']==list(specialized.PUBLIC_NOTES)
    assert new['phases']==old['phases']==list(specialized.PHASES)
    assert book.sheetnames==baseline.sheetnames==new['sheetnames']
    assert book.calculation==baseline.calculation
    assert new['formula_count']<=old['formula_count']
    assert new['specialized_materialization']['financial_equivalence_verified'] is False
    assert new['specialized_materialization']['actual_LO_calls']==0
    assert not new['specialized_materialization']['source_or_task_qualified']
    assert specialized.validate_materialized_structure(book,new)['financial_physical_roots']==len(old['financial_bindings'])


def test_all_retained_formulas_materialized_and_dead_helpers_empty_without_archive():
    public=toy();baseline=Workbook();old=original.emit_heterogeneous_workbook(baseline,public)
    expected,report=compiler.specialize_bindings(old,enabled=True)
    book,new=emit(public)
    actual={(s.title,c.coordinate):c.value for s in book.worksheets for c in s._cells.values() if c.data_type=='f'}
    assert actual=={key(r):r['formula'] for r in expected['arithmetic_bindings']}
    removed={key(r) for r in old['arithmetic_bindings']}-set(actual)
    old_lit={key(r):r for r in old['literal_bindings']};new_lit={key(r):r for r in new['literal_bindings']}
    assert removed and report['pruned_arithmetic_count']==len(removed)
    for sheet,cell in removed:
        assert book[sheet][cell].value is None
    for sheet,cell in old_lit.keys()-new_lit.keys():assert book[sheet][cell].value is None
    assert not book.defined_names and not book._external_links
    assert book.sheetnames==old['sheetnames']
    assert not new['specialized_materialization']['original_templates_saved_or_materialized_as_archive']
    assert new['implementation']['path'].endswith('/specialized_excel.py')


def test_monthly_calendar_template_removed_but_legitimate_quarter_calendar_retained():
    book,new=emit();arith={compiler._reference(r):r for r in new['arithmetic_bindings']}
    literals={key(r):r['value'] for r in new['literal_bindings']}
    def helper(eid,label):
        result=[r for r in new['arithmetic_bindings'] if r['cell'].startswith('B')
            and literals.get((r['sheet'],'A'+r['cell'][1:]))==eid+' 2027-01-01 '+label]
        assert len(result)==1
        return result[0]
    monthly=helper('E01','coupon due');quarter=helper('E02','coupon due')
    def selected_date_dependencies(row):
        return [arith[r] for r in compiler._refs(row['expression']) if r in arith
                and str(literals.get((arith[r]['sheet'],'A'+arith[r]['cell'][1:]),'')).endswith('effective next_coupon_month')]
    assert selected_date_dependencies(monthly)==[]
    assert len(selected_date_dependencies(quarter))==1
    assert new['specialized_materialization']['geometry']['all_financial_roots_and_references_present']


def test_native_primitives_labels_formats_notes_and_configuration_unchanged():
    public=toy();baseline=Workbook();old=original.emit_heterogeneous_workbook(baseline,public)
    book,new=emit(public)
    for row in new['input_bindings']+new['literal_bindings']:
        first=baseline[row['sheet']][row['cell']];second=book[row['sheet']][row['cell']]
        assert specialized._typed(second.value)==specialized._typed(first.value)
        assert second.data_type==first.data_type and specialized._style(second)==specialized._style(first)
    assert book['Entity Policies']['J2'].number_format==original.MONEY_FORMAT
    assert new['specialized_materialization']['unmodified_cells_styles_and_configuration_preserved']


@pytest.mark.parametrize('corruption',['extra_template','wrong_formula','missing_financial','primitive','notes','type_bool','external_name'])
def test_complete_structure_recheck_rejects_tampering(corruption):
    book,bindings=emit(toy(('BULLET_MONTHLY',)))
    if corruption=='extra_template':book['Input Calculations']['Z999']='=1+1'
    elif corruption=='wrong_formula':
        r=bindings['arithmetic_bindings'][0];book[r['sheet']][r['cell']]='=999'
    elif corruption=='missing_financial':
        r=bindings['financial_bindings'][0];book[r['sheet']][r['cell']]=None
    elif corruption=='primitive':
        r=next(r for r in bindings['input_bindings'] if r['kind']=='money_pence');book[r['sheet']][r['cell']]=0
    elif corruption=='notes':book['Contract Notes']['B2']='changed policy'
    elif corruption=='type_bool':
        r=next(r for r in bindings['input_bindings'] if r['kind']=='flag');book[r['sheet']][r['cell']]=False
    else:
        from openpyxl.workbook.defined_name import DefinedName
        book.defined_names.add(DefinedName('ArchivedTemplate',attr_text="'Input Calculations'!$A$1"))
    with pytest.raises(ValueError):specialized.validate_materialized_structure(book,bindings)


def test_tiny_saved_book_has_only_declared_formulas_and_no_cached_answers(tmp_path):
    book,bindings=emit(toy(('BULLET_MONTHLY',)))
    path=tmp_path/'tiny-uncalculated.xlsx';book.save(path)
    count=0
    with ZipFile(path) as archive:
        assert not any('externalLink' in name for name in archive.namelist())
        for member in archive.namelist():
            if member.startswith('xl/worksheets/sheet') and member.endswith('.xml'):
                root=ET.fromstring(archive.read(member))
                for cell in root.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c'):
                    formula=cell.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}f')
                    if formula is not None:
                        count+=1
                        cache=cell.find('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v')
                        assert cache is None or cache.text is None
    assert count==bindings['formula_count']


def test_same_api_forwards_full_dimension_opt_in_and_cap_without_running_production(monkeypatch):
    calls=[]
    def stopped(book,public,**kwargs):calls.append(kwargs);raise ValueError('deliberate stopped upstream boundary')
    monkeypatch.setattr(specialized.original,'emit_heterogeneous_workbook',stopped)
    with pytest.raises(ValueError,match='upstream boundary'):
        specialized.emit_heterogeneous_workbook(Workbook(),{},max_formulas=321,allow_production=False)
    assert calls==[{'max_formulas':321,'allow_production':False}]


def test_original_formula_cap_fails_instead_of_truncating():
    with pytest.raises(ValueError,match='formula budget'):
        specialized.emit_heterogeneous_workbook(Workbook(),toy(('BULLET_MONTHLY',)),max_formulas=1)


def test_fresh_book_boundary_preserved():
    book=Workbook();book.active['A1']='old template'
    with pytest.raises(ValueError,match='fresh empty workbook'):
        specialized.emit_heterogeneous_workbook(book,toy(('BULLET_MONTHLY',)))


def test_wrapper_has_no_financial_oracle_or_execution_imports():
    tree=ast.parse(Path(specialized.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node,ast.ImportFrom):assert not any(word in (node.module or '') for word in ('ledger','validate','engine'))
        if isinstance(node,ast.Attribute):assert node.attr not in {'save','simulate','recalculate','Popen'}
    assert specialized.PUBLIC_NOTES is original.PUBLIC_NOTES
    assert specialized.PHASES is original.PHASES
