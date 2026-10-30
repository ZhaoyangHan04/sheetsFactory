from copy import deepcopy
from decimal import Decimal as D
import json
from pathlib import Path
import pytest
from sheets_factory.workbook.derived_regulatory.ledger import simulate,gross_up
from sheets_factory.workbook.derived_regulatory.schema import ANNUAL_FIELDS


def simple_spec():
    years=list(range(2024,2028))
    return {'years':years,'batches':[{'id':'A','paid_year':2024,'commission_year':2025,
        'regulatory_life':2,'tax_pool':'General','real_cost':'100','nominal_cost':'100'}],
        'parameters':{'gearing':'0','loss_carry_years':1,'loss_use_cap':'.8','claim_lag_years':2,'structures_tax_life':11},
        'annual_inputs':[{'year':year,'price_index':'1','real_wacc':'0','tax_rate':'.25',
            'claim_carry_rate':'0','debt_rate':'.05','collection_cap_nominal':'1000',
            'disallowance_real':'0','general_rate':'1','special_rate':'.06','general_transfer_fraction':'0'} for year in years]}


def test_hand_calculated_commissioning_tax_expiry_and_two_year_cash_lag():
    result=simulate(simple_spec());rows=result['annual']
    assert all(result['checks'].values()) and len(result['journal'])==60
    assert [r['closing_cwip_real'] for r in rows]==[D(100),D(0),D(0),D(0)]
    assert [r['depreciation_real'] for r in rows]==[D(0),D(25),D(50),D(25)]
    assert [r['tax_capital_allowances'] for r in rows]==[D(0),D(50),D(50),D(0)]
    assert rows[1]['losses_created']==D(25) and rows[3]['losses_expired']==D(25)
    assert rows[3]['current_tax_allowance']==D('8.33')
    assert [r['claims_receipts'] for r in rows]==[D(0),D(0),D(0),D(25)]
    assert rows[3]['claims_close']==D('83.33') and rows[3]['owner_distribution']==D('16.67')
    assert rows[3]['total_equity']==D('83.33')
    assert all(sum(entry['debit_positive_entries'].values(),D(0))==0 for entry in result['journal'])


def test_continuous_tax_gross_up_has_distinct_loss_limited_and_utilization_limited_regimes():
    assert gross_up(D(100),D(50),D('.8'),D('.25'))==(D('16.67'),D(50),D(0))
    assert gross_up(D(100),D(100),D('.8'),D('.25'))==(D('5.26'),D('84.21'),D(0))
    assert gross_up(D(-10),D(100),D('.8'),D('.25'))==(D(0),D(0),D(10))


def test_tax_pool_transfer_is_nominal_and_does_not_realize_income_or_modify_total_basis():
    spec=simple_spec();spec['annual_inputs'][2].update(general_transfer_fraction='.3',general_rate='.18')
    spec['annual_inputs'][1]['general_rate']='.18'
    result=simulate(spec);previous=result['tax_batches']['A'][1]
    assert previous['general_close']==D(91)
    assert result['annual'][2]['tax_basis_transfer']==D('27.30')
    current=result['tax_batches']['A'][2]
    assert current['special_close']==D('25.66')
    assert current['general_close']==D('52.23')
    assert current['capital_allowance']==D('13.11')
    assert all(result['checks'].values())


def test_real_disallowance_is_fifo_after_depreciation_without_tax_basis_writeoff():
    spec=simple_spec();spec['batches'].append({**spec['batches'][0],'id':'B','real_cost':'200','nominal_cost':'200'})
    spec['annual_inputs'][1]['disallowance_real']='40'
    result=simulate(spec)
    assert result['rav_batches']['A'][1]['disallowance']==D(40)
    assert result['rav_batches']['B'][1]['disallowance']==D(0)
    assert result['annual'][1]['tax_capital_allowances']==D(150)
    assert result['annual'][1]['disallowance_nominal']==D(40)
    assert all(result['checks'].values())


def test_claim_interest_remains_on_its_vintage_and_receipts_are_fifo_capped():
    spec=simple_spec();spec['annual_inputs'][2]['claim_carry_rate']='.1';spec['annual_inputs'][3]['collection_cap_nominal']='10'
    result=simulate(spec)
    assert result['claim_vintages'][2025][2]['interest']==D('2.50')
    assert result['claim_vintages'][2025][3]['collected']==D(10)
    assert result['claim_vintages'][2026][3]['collected']==D(0)
    assert result['annual'][3]['claims_close']>0
    assert all(result['checks'].values())


def test_schema_covers_all_named_financial_outputs_and_no_missing_full_journal_checks():
    result=simulate(simple_spec())
    assert set(result['annual'][0])==set(ANNUAL_FIELDS)
    assert len(result['checks'])==8 and all(value is True for value in result['checks'].values())
