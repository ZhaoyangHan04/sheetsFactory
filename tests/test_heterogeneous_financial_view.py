"""Tiny synthetic projection tests: no source certificates, real forecasts or LO."""
from copy import deepcopy
from datetime import datetime
import json

import openpyxl
import pytest

from sheets_factory.task_adapters import heterogeneous_financial_view as view


def row(field='revenue', *, sheet='S01 Entity Close', cell='D2', kind='money_pence', scale=100,
        path=None, origin=None, vintage_field=None):
    r = {'sheet':sheet,'cell':cell,'expected_path':path or ['scenarios','S01','entities','E01','monthly',0,field],
        'kind':kind,'worksheet_scale':scale,'formula':'=1','expression':1,'semantic_owner':[], 'is_complete_answer':kind=='money_pence'}
    if origin is not None:r.update(vintage_origin=origin,vintage_field=vintage_field)
    return r


def public():
    return {'months':['2024-01-01','2024-02-01'],'scenario_ids':['S01'],
        'entities':[{'id':'E01','opening_interest_carry':[],'opening_tax_losses':[{'origin_month':'2023-12-01','amount_pence':100}]}],
        'loans':[{'id':'L01','entity_id':'E01'}],'assets':[{'id':'A01','entity_id':'E01'}]}


def bindings(rows):return {'financial_bindings':rows}


def fixture_plan():
    # These are hand-specified synthetic values, not emitted business forecasts.
    rows=[row(),row('test_pass',cell='D3',kind='nullable_flag',scale=1),
          row('loss_close',cell='D4'),row('bank_draw',cell='D5')]
    positions=view._place_targets(rows,public())
    for p,v in zip(positions,[123.45,None,0,67.89]):p['reference_value']=view._typed(v)
    declared=view.policy()
    return {'months':public()['months'],'scenario_ids':['S01'],
        'sheet_order':['Calendar','Contract Notes']+['S01 '+x for x in declared['forecast_views']],
        'provided_cells':[{'sheet':'Calendar','cell':'A1','value':view._typed(datetime(2024,1,1)),'number_format':'mmm-yy'},
            {'sheet':'Contract Notes','cell':'A1','value':view._typed('Public business policies'),'number_format':'General'}],
        'forecast_targets':positions,'engineering_only_fixture_not_source_proof':True}


def save_fixture(tmp_path,plan=None):
    plan=plan or fixture_plan();paths=[]
    for masked,name in [(True,'input.xlsx'),(False,'goal.xlsx')]:
        book=view._book_from_plan(plan,masked=masked);path=tmp_path/name
        try:book.save(path)
        finally:book.close()
        paths.append(path)
    return plan,*paths


def test_default_off_before_source_read(monkeypatch,tmp_path):
    monkeypatch.setattr(view,'_load_source',lambda _:pytest.fail('Default-off route read a source'))
    assert view.setting()['enabled'] is False
    with pytest.raises(view.ViewError,match='default off'):view.build_view_plan(tmp_path/'absent')
    with pytest.raises(view.ViewError,match='default off'):view.materialize_view({},tmp_path/'out')


@pytest.mark.parametrize('flag',[1,'true',None])
def test_setting_requires_actual_bool(flag):
    with pytest.raises(view.ViewError):view.setting(enabled=flag)


def test_offline_census_is_explicitly_not_source_certificate():
    p=view.policy();assert p['offline_prototype_census_not_source_certificate']['declared_numeric_business_slots']==100296
    assert p['future_derived_term_ids_displayed'] is False


@pytest.mark.parametrize('kind',['completed_math_probe','independently_verified_heterogeneous_contract_source'])
def test_manifest_booleans_and_offline_count_cannot_admit(tmp_path,kind):
    p=tmp_path/'source.json';p.write_text(json.dumps({'kind':kind,'version':1,
        'status':'source_verified_not_task_quality_or_difficulty_qualified','financial_audit_passed':True,'actual_LO_recalculations':3}))
    with pytest.raises(view.ViewError):view.validate_source(p)


def test_only_primary_business_aliases_selected_and_zero_not_filtered():
    rows=[row(),row(sheet='S01 Calculations',cell='B2',scale=1),
          row('test_pass',cell='D3',kind='nullable_flag',scale=1),
          row('term_id',cell='D4',kind='text',scale=1),row('month',cell='D5',kind='date',scale=1)]
    result=view.select_business_bindings(bindings(rows))
    assert [r['cell'] for r in result['targets']]==['D2','D3']
    assert len(result['omitted_metadata'])==2 and result['selection_consults_values'] is False
    assert result['source_or_quality_certificate'] is False


@pytest.mark.parametrize('mutation',['duplicate_path','duplicate_cell','unknown_alias','wrong_scale','bool_scale','unknown_kind'])
def test_structural_alias_tamper_rejected(mutation):
    rows=[row()]
    if mutation=='duplicate_path':rows.append(row(cell='D3'))
    elif mutation=='duplicate_cell':rows.append(row('ebitda'))
    elif mutation=='unknown_alias':rows.append(row(sheet='S01 Unexplained',cell='B2'))
    elif mutation=='wrong_scale':rows[0]['worksheet_scale']=1
    elif mutation=='bool_scale':rows[0].update(kind='flag',worksheet_scale=True)
    else:rows[0]['kind']='quotient_remainder'
    with pytest.raises(view.ViewError):view.select_business_bindings(bindings(rows))


def test_queue_total_exclusion_has_explicit_entity_account_alias():
    total=row(sheet='S01 Calculations',cell='B8',scale=1,
        path=['scenarios','S01','loss_vintages','E01','monthly',0,'closing'])
    result=view.select_business_bindings(bindings([row('loss_close'),total]))
    assert result['counts']['business_targets']==1
    assert result['explicit_queue_total_aliases'][0]['business_alias']['expected_path'][-1]=='loss_close'
    with pytest.raises(view.ViewError):view.select_business_bindings(bindings([row(),total]))


def test_unknown_unpaired_support_cannot_disappear():
    support=row('unexplained',sheet='S01 Calculations',cell='B8',scale=1)
    with pytest.raises(view.ViewError):view.select_business_bindings(bindings([row(),support]))


def test_loan_and_entity_distinct_paths_are_real_schedule_aliases():
    rows=[row('principal_close'),row('principal_close',sheet='S01 Loan Close',cell='D3',
        path=['scenarios','S01','loans','L01','monthly',0,'principal_close'])]
    result=view.select_business_bindings(bindings(rows));positions=view._place_targets(result['targets'],public())
    assert len(positions)==2 and positions[0]['descriptors'][0]=='E01' and positions[1]['descriptors'][0]=='L01'


def test_term_ids_never_become_forecast_descriptors():
    result=view.select_business_bindings(bindings([row(),row('term_id',cell='D8',kind='text',scale=1)]))
    positions=view._place_targets(result['targets'],public())
    assert len(positions)==1 and 'term_id' not in str(positions[0]['descriptors'])


def test_fifo_layout_has_only_public_origins_and_no_future_padding():
    r=row(sheet='S01 Loss FIFO',origin='2023-12-01',vintage_field='closing',
        path=['scenarios','S01','loss_vintages','E01','monthly',0])
    p=view._place_targets([r],public())[0]
    assert p['cell']=='H4' and p['descriptors']==['E01','2023-12-01','2024-01-01']
    r['vintage_origin']='2020-01-01'
    with pytest.raises(view.ViewError):view._place_targets([r],public())


@pytest.mark.parametrize('time',[True,-1,2])
def test_group_month_index_is_not_bool_or_out_of_bounds(time):
    r=row(sheet='S01 Group Close',path=['scenarios','S01','group_monthly',time,'cash_close'])
    with pytest.raises(view.ViewError):view._place_targets([r],public())


@pytest.mark.parametrize('value',[True,float('nan'),float('inf'),{'not':'a cell'},'/data/private/ref.json','{"secret":1}'])
def test_raw_literals_reject_bool_nonfinite_json_and_private_paths(value):
    with pytest.raises(view.ViewError):view._typed(value)


def test_tiny_written_view_preserves_inputs_masks_zero_and_has_no_helpers(tmp_path):
    plan,ip,gp=save_fixture(tmp_path)
    audit=view.validate_view(plan,ip,gp)
    assert audit['declared_business_slots']==4 and audit['expected_changed_value_count_before_actual_normalization']==3
    assert audit['actual_LO_calls']==0 and audit['source_or_quality_certified'] is False
    input_book=openpyxl.load_workbook(ip);goal=openpyxl.load_workbook(gp)
    try:
        assert input_book['Calendar']['A1'].value==datetime(2024,1,1)
        for r in plan['forecast_targets']:
            assert input_book[r['sheet']][r['cell']].value is None
            assert goal[r['sheet']][r['cell']].value==view._untyped(r['reference_value'])
        assert all(c.data_type!='f' for b in (input_book,goal) for s in b for c in s._cells.values())
        assert not any('Calculations' in s for s in input_book.sheetnames)
    finally:input_book.close();goal.close()


@pytest.mark.parametrize('tamper',['provided_literal','extra_helper','missing_zero','formula','sheet_order','nullable_filled'])
def test_complete_projection_validation_fails_closed_on_changes(tmp_path,tamper):
    plan,ip,gp=save_fixture(tmp_path);book=openpyxl.load_workbook(gp)
    if tamper=='provided_literal':book['Contract Notes']['A1']='Changed policy'
    elif tamper=='extra_helper':book['Calendar']['Z9']=1
    elif tamper=='missing_zero':
        r=plan['forecast_targets'][2];book[r['sheet']][r['cell']]=None
    elif tamper=='formula':
        r=plan['forecast_targets'][0];book[r['sheet']][r['cell']]='=123.45'
    elif tamper=='sheet_order':book.move_sheet('Calendar',offset=1)
    else:
        r=plan['forecast_targets'][1];book[r['sheet']][r['cell']]=0
    book.save(gp);book.close()
    with pytest.raises(view.ViewError):view.validate_view(plan,ip,gp)


def covenant_forward(applies,service,cfads,passed,ratio):
    r={'test_applicable':applies,'dscr_window_debt_service':service,'dscr_window_cfads':cfads,
        'test_pass':passed,'dscr_ratio_millionths':ratio}
    return {'scenarios':{'S01':{'entities':{'E01':{'monthly':[deepcopy(r),deepcopy(r)]}}}}}


@pytest.mark.parametrize('args',[(0,10,20,None,None),(1,0,0,1,None),(1,0,-1,0,None),(1,10,0,0,0)])
def test_public_nullable_encodings_include_applicable_numeric_zero(args):
    view._check_nullable_policy(public(),covenant_forward(*args))


@pytest.mark.parametrize('args',[(0,10,20,0,None),(0,0,0,None,0),(1,0,0,None,None),(1,0,-1,1,None),(1,10,0,None,None)])
def test_non_test_and_zero_service_na_contradictions_rejected(args):
    with pytest.raises(view.ViewError):view._check_nullable_policy(public(),covenant_forward(*args))


def test_public_brief_is_completion_scope_without_solution_hints():
    text=view.public_brief()
    assert 'including zero' in text and 'numeric 0/1' in text and 'policy-defined blank' in text
    assert '/app/input.xlsx' in text and '/app/output.xlsx' in text
    assert all(s not in text for s in ['expected_path','quotient','remainder','source_manifest','test_pass=','formula for'])


def cache_fixture(tmp_path, *, wrong_business_value=False, wrong_alias=False):
    # A literal-only, hand-written tiny reader fixture. This is deliberately not
    # a calculated source and has no source manifest or admission certificate.
    book=openpyxl.Workbook();book.remove(book.active)
    for name in ['Contract Notes','Calendar','S01 Entity Close','S01 Calculations']:book.create_sheet(name)
    book['Contract Notes']['A1']='Provided policy'
    book['Calendar']['A1']=datetime(2024,1,1);book['Calendar']['A1'].number_format='mmm-yy'
    book['S01 Entity Close']['D2']=123.46 if wrong_business_value else 123.45
    book['S01 Entity Close']['D3']=1
    book['S01 Calculations']['B8']=70 if wrong_alias else 100
    path=tmp_path/'hand_cache_fixture.xlsx';book.save(path);book.close()
    financial=[row(),row('loss_close',cell='D3')]
    total=row(sheet='S01 Calculations',cell='B8',scale=1,
        path=['scenarios','S01','loss_vintages','E01','monthly',0,'closing'])
    result=view.select_business_bindings(bindings(financial+[total]))
    positions=view._place_targets(result['targets'],public())
    forward={'scenarios':{'S01':{'entities':{'E01':{'monthly':[{'revenue':12345,'loss_close':100}]}},
        'loss_vintages':{'E01':{'monthly':[{'closing':70 if wrong_alias else 100}]}}}}}
    return path,positions,result['explicit_queue_total_aliases'],forward


def test_hand_cached_business_value_is_not_divided_by_pence_scale_twice(tmp_path):
    path,positions,aliases,forward=cache_fixture(tmp_path)
    inputs=view._cached_source(path,['Contract Notes','Calendar'],positions,aliases,forward)
    assert positions[0]['reference_value']==['number','123.45']
    assert positions[1]['reference_value']==['number','1.00']
    calendar=next(r for r in inputs if r['sheet']=='Calendar')
    assert calendar['value']==['datetime','2024-01-01T00:00:00'] and calendar['number_format']=='mmm-yy'


@pytest.mark.parametrize('field',['wrong_business_value','wrong_alias'])
def test_hand_cached_posting_or_queue_alias_mismatch_rejected(tmp_path,field):
    path,positions,aliases,forward=cache_fixture(tmp_path,**{field:True})
    with pytest.raises(view.ViewError):view._cached_source(path,['Contract Notes','Calendar'],positions,aliases,forward)
