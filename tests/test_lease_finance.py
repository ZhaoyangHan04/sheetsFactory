from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from sheets_factory.workbook.lease_finance.contract import load_lease_spec, validate_lease_spec
from sheets_factory.workbook.lease_finance.ledger import simulate_lease
from sheets_factory.workbook.lease_finance.excel import emit_lease_workbook
from sheets_factory.workbook.lease_finance.validate import audit_lease_workbook

ROOT=Path(__file__).resolve().parents[1]


def simple(frequency=1, rate='0', direct='12', end=12):
    source=load_lease_spec(ROOT/'config/derived_lease_contract_v1.json')
    lease=deepcopy(source['leases'][0])
    lease.update(start_month=1,end_month=end,payment_frequency=frequency,monthly_base_rent='100',
                 initial_direct_cost=direct,annual_discount_rate=rate,fixed_step_rate='0',
                 fixed_step_months=12,index_floor_factor='0.1',index_cap_factor='1.05',events=[])
    source['leases']=[lease]
    return source


def event(month,kind,*,index=None,rate=None,end=None,retention=None,fee='0'):
    return {'month':month,'kind':kind,'index_ratio':index,'annual_discount_rate':rate,
            'new_end_month':end,'retention_fraction':retention,'cash_fee':fee}


def test_zero_rate_direct_cost_cash_and_book_bridge_close_exactly():
    result=simulate_lease(simple());rows=result['lease_monthly']['P01']
    assert rows[0]['lease_pv_at_measurement']==Decimal('1200')
    assert rows[0]['lease_rou_close']==Decimal('1111')
    assert rows[0]['lease_liability_close']==Decimal('1100')
    assert rows[0]['lease_cash_rent']==Decimal('112')
    assert rows[0]['lease_taxable_adjustment']==Decimal('-11')
    assert rows[11]['lease_rou_close']==rows[11]['lease_liability_close']==0
    assert result['annual'][2024]['lease_cash_rent']==Decimal('1212')
    assert all(result['checks'].values())


def test_quarterly_arrears_have_no_month1_payment_and_true_discounted_timing():
    spec=simple(3,'0.12','0');result=simulate_lease(spec);rows=result['lease_monthly']['P01']
    r=rows[0]['lease_monthly_discount_rate']
    expected=sum((Decimal(300)/(1+r)**p for p in [3,6,9,12]),Decimal(0)).quantize(Decimal('.01'))
    assert rows[0]['lease_pv_at_measurement']==expected
    assert rows[0]['lease_recurring_rent']==rows[1]['lease_recurring_rent']==0
    assert rows[2]['lease_recurring_rent']==300
    assert rows[11]['lease_liability_close']==0


def test_partial_then_full_termination_gains_include_fees_and_close_assets():
    spec=simple(direct='120');spec['leases'][0]['events']=[
        event(7,'partial_termination',retention='0.5',fee='10'),
        event(10,'termination',retention='0',fee='20')]
    result=simulate_lease(spec);rows=result['lease_monthly']['P01']
    assert rows[6]['lease_termination_gain_loss']==Decimal('-40')
    assert rows[6]['lease_cash_rent']==60 and rows[6]['lease_book_expense']==95
    assert rows[9]['lease_termination_gain_loss']==Decimal('-35')
    assert rows[9]['lease_cash_rent']==20 and rows[9]['lease_rou_close']==rows[9]['lease_liability_close']==0
    assert all(r['lease_cash_rent']==0 for r in rows[10:])
    assert all(result['checks'].values())


def test_index_floor_and_rate_zero_are_explicit_remeasurements_and_no_future_index_lookahead():
    spec=simple(rate='0.1',end=24,direct='0');spec['leases'][0]['events']=[event(13,'index',index='0.01',rate='0')]
    result=simulate_lease(spec);rows=result['lease_monthly']['P01']
    plain=deepcopy(spec);plain['leases'][0]['events']=[]
    assert rows[0]['lease_pv_at_measurement']==simulate_lease(plain)['lease_monthly']['P01'][0]['lease_pv_at_measurement']
    assert rows[12]['lease_index_factor']==Decimal('0.1')
    assert rows[12]['lease_monthly_discount_rate']==0 and rows[12]['lease_pv_at_measurement']==120
    assert rows[12]['event_rate_changed']==1
    assert all(result['checks'].values())


def test_negative_rou_adjustment_is_floored_with_gain_without_balance_plug():
    spec=simple(rate='0.20',end=120,direct='0');spec['leases'][0]['events']=[event(61,'index',index='0.1')]
    result=simulate_lease(spec);row=result['lease_monthly']['P01'][60]
    assert row['lease_rou_close']==0 and row['lease_termination_gain_loss']>0
    assert row['lease_liability_close']>0 and row['lease_journal_bridge']==0


def test_four_different_contracts_all_terminal_and_annual_timing_reconcile():
    result=simulate_lease(load_lease_spec(ROOT/'config/derived_lease_contract_v1.json'))
    assert list(result['annual'])==list(range(2024,2044))
    assert all(result['checks'].values())
    assert result['annual'][2043]['lease_cash_rent']>0
    assert result['annual'][2043]['lease_rou_close']==result['annual'][2043]['lease_liability_close']==0
    assert result['annual'][2024]['lease_rou_open']==0


@pytest.mark.parametrize('defect',['missing','cycle','late','negative','eventnull'])
def test_invalid_or_missing_contract_inputs_do_not_receive_defaults(defect):
    spec=simple()
    if defect=='missing':del spec['leases'][0]['monthly_base_rent']
    elif defect=='cycle':spec['leases'][0]['payment_frequency']=5
    elif defect=='late':spec['leases'][0]['end_month']=241
    elif defect=='negative':spec['leases'][0]['annual_discount_rate']='-0.01'
    else:spec['leases'][0]['events']=[event(7,'partial_termination',retention=None)]
    with pytest.raises(ValueError):validate_lease_spec(spec)


def test_excel_full_horizon_no_embedded_journal_values_append_and_complete_audit(tmp_path):
    spec=load_lease_spec(ROOT/'config/derived_lease_contract_v1.json');before=deepcopy(spec)
    book=openpyxl.Workbook();book.active.title='Existing';book.active['A1']='preserve'
    path=tmp_path/'leases.xlsx';bindings=emit_lease_workbook(spec,path,workbook=book)
    assert spec==before and book['Existing']['A1'].value=='preserve'
    assert len(bindings['annual_refs'])==20
    assert bindings['annual_refs'][2043]['lease_cash_rent'].startswith("'Lease Annual'!")
    assert book['Lease Calendar']['C1'].number_format == 'yyyy-mm-dd'
    assert book['Lease P04']['C1'].number_format == 'yyyy-mm-dd'
    pv=book['Lease P04']['AA23'].value
    assert any('$IH$2' in c.value for row in book['Lease P04'] for c in row if c.data_type=='f')
    assert all(isinstance(book[b['sheet']][b['cell']].value,str) for b in bindings['cell_bindings'])
    result=audit_lease_workbook(path,spec,simulate_lease(spec),bindings)
    assert result['complete_formula_coverage'] is True
    assert result['passed'] is False and result['mismatch_count']==bindings['formula_count']  # No LO was run.
    book['Lease Inputs']['C10']=999
    book.save(path)
    assert audit_lease_workbook(path,spec,simulate_lease(spec),bindings)['control_mismatch_count']>0
