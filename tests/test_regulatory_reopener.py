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


def lease_interface(spec):
    result={}
    previous_rou=previous_liability=D(0)
    for i,year in enumerate(spec['years']):
        cash=D(45) if i==3 else D(25)
        liability=D(0) if i==3 else D(80)-D(20)*i
        rou=D(75)-D(25)*i
        result[year]={'lease_cash_rent':cash,'lease_book_depreciation':D(25),
            'lease_book_interest':D(5),'lease_termination_gain_loss':D(0),
            'lease_tax_deduction':cash,'lease_regulatory_expense':cash,
            'lease_rou_open':previous_rou,'lease_rou_close':rou,
            'lease_liability_open':previous_liability,'lease_liability_close':liability}
        previous_rou,previous_liability=rou,liability
    return result


def test_optional_lease_changes_tax_claims_cash_and_real_balance_sheet_not_parallel_reports():
    from sheets_factory.workbook.derived_regulatory.ledger import annual_bridge
    spec=simple_spec();spec['parameters']['lease_allowable_fraction']='.8'
    base=simulate(spec);result=simulate(spec,external_lease_annual=lease_interface(spec))
    assert result['lease_integrated'] and all(result['checks'].values())
    first=result['annual'][0]
    assert first['pre_allowance_taxable_profit']==base['annual'][0]['pre_allowance_taxable_profit']-D(5)
    assert first['capital_entitlement']==base['annual'][0]['capital_entitlement']+D(20)
    assert first['owner_capital']==base['annual'][0]['owner_capital']+D(25)
    assert first['total_assets']==D(195) and first['total_liabilities']==D(80)
    assert first['total_equity']==D(115) and first['net_income']==D(-10)
    assert first['lease_liability_close']==D(80) and first['lease_rou_close']==D(75)
    assert all(row['balance_check']==0 and row['cash_check']==0 for row in result['annual'])
    bridge=annual_bridge(spec,result)
    assert bridge[2024]['period_start']=='2023-04-01' and bridge[2024]['period_end']=='2024-03-31'
    assert all(row['cfo']+row['cfi']+row['cff']==row['cash_close'] for row in bridge.values())


def test_external_lease_interface_requires_continuity_journal_identity_and_explicit_public_fraction():
    spec=simple_spec();external=lease_interface(spec)
    with pytest.raises(ValueError,match='explicit public'):simulate(spec,external_lease_annual=external)
    spec['parameters']['lease_allowable_fraction']='1'
    broken=deepcopy(external);broken[2024]['lease_cash_rent']+=1
    with pytest.raises(ValueError,match='journal bridge'):simulate(spec,external_lease_annual=broken)
    broken=deepcopy(external);broken[2025]['lease_rou_open']+=1
    with pytest.raises(ValueError,match='opening balances'):simulate(spec,external_lease_annual=broken)
    broken=deepcopy(external);broken[2024].pop('lease_tax_deduction')
    with pytest.raises(ValueError,match='Incomplete'):simulate(spec,external_lease_annual=broken)


def test_standalone_parent_bridge_explicitly_has_zero_leases_and_reconciles_cash():
    from sheets_factory.workbook.derived_regulatory.ledger import annual_bridge
    spec=simple_spec();result=simulate(spec)
    assert result==simulate(spec,external_lease_annual=None)
    bridge=annual_bridge(spec,result)
    assert all(row['lease_liability_close']==0 and row['lease_rou_close']==0 for row in bridge.values())
    assert all(row['cfo']+row['cfi']+row['cff']==0 for row in bridge.values())
    assert 'lease_integrated' not in result


def emitter_fixture(tmp_path,spec,external=None):
    import openpyxl
    from sheets_factory.workbook.derived_regulatory.excel import create_workbook
    from sheets_factory.workbook.derived_regulatory.ledger import LEASE_FIELDS
    source=tmp_path/'source.xlsx';book=openpyxl.Workbook();book.active.title='Upstream';book.active['A1']=100
    refs={}
    if external is not None:
        sheet=book.create_sheet('Lease Annual')
        for yi,(year,row) in enumerate(external.items(),2):
            refs[year]={}
            for index,key in enumerate(LEASE_FIELDS,2):
                sheet.cell(index,yi,float(row[key]));refs[year][key]="'Lease Annual'!"+sheet.cell(index,yi).coordinate
    book.save(source);book.close()
    prepared=deepcopy(spec)
    for batch in prepared['batches']:
        batch.update(source_address='Upstream!A1',source_millions='.0001',programme_share='1')
    output=tmp_path/'model.xlsx'
    binding=create_workbook(source,prepared,output,'Public hypothetical policy',external_annual_refs=refs if external is not None else None)
    return output,binding


def test_excel_lease_hooks_reference_calculated_lease_cells_and_cover_independent_expected_outputs(tmp_path):
    import openpyxl
    from sheets_factory.workbook.derived_regulatory.validate import expected_cells
    spec=simple_spec();spec['parameters']['lease_allowable_fraction']='.8';external=lease_interface(spec)
    result=simulate(spec,external_lease_annual=external);path,binding=emitter_fixture(tmp_path,spec,external)
    expected=expected_cells(spec,result)
    assert len(expected)==binding['new_formula_count']
    book=openpyxl.load_workbook(path)
    for (sheet,row,col),_ in expected.items():assert book[sheet].cell(row,col).data_type=='f'
    refs=binding['annual_refs'][2024]
    assert 'lease_liability_close' in refs and all(key in refs for key in ('owner_capital','owner_distribution','cfo','cfi','cff','total_equity'))
    from sheets_factory.workbook.derived_regulatory.schema import COMBINED_ANNUAL_FIELDS
    lease_row=3+COMBINED_ANNUAL_FIELDS.index('lease_cash_rent')
    assert book['Reopener Statements'].cell(lease_row,3).value=="='Lease Annual'!B2"
    assert book['Reopener Inputs']['B35'].value==.8
    assert binding['metadata_adapter']==[]
    book.close()


def test_public_lease_amendment_replaces_tax_and_owner_cash_clauses_and_preserves_standalone_policy():
    from sheets_factory.workbook.derived_regulatory.policy import public_policy
    plain=public_policy();combined=public_policy(include_leases=True)
    assert 'less cash debt interest and tax capital allowances.' in plain
    assert 'plus the eligible regulatory lease allowance' in combined
    assert 'less cash debt interest and tax capital allowances.' not in combined
    assert 'including direct costs and termination fees' in combined
    assert 'not an assertion of IFRS cash-flow classification' in combined
