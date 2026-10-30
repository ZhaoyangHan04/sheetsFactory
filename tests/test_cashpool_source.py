"""Financial invariants, binding contracts and nonlocal cashpool feedback."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import pytest
from sheets_factory.workbook.cashpool.ledger import simulate_pool

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def inputs():
    spec=json.loads((ROOT/'config/derived_cashpool_v1.json').read_text())
    source=json.loads((ROOT/spec['verified_source_manifest']).read_text());ledgers={};public={}
    for entity in source['entities']:
        i=entity['id'];v=json.loads(Path(entity['ledger']['path']).read_text())
        for row in v['monthly']:
            row['net_income']=Decimal(row['net_income']);row['dividend']=Decimal(row['dividend'])
        v['valuation']['equity_exit']=Decimal(v['valuation']['equity_exit'])
        ledgers[i]=v;public[i]=json.loads(Path(entity['public_scenario']['path']).read_text())
    return spec,ledgers,public


def test_four_contracts_actually_bind_and_all_journals_reconcile(inputs):
    result=simulate_pool(*inputs)
    assert all(result['checks'][key] is True for key in ('all_double_entry_balanced','all_subsidiary_balances','all_treasury_balances','all_group_balances','all_group_cash_balances','all_group_income_eliminations','no_balance_plug'))
    assert all(result['regimes'][key] for key in inputs[0]['required_regimes'])
    assert result['regimes']['nav_cap_binding']==[4]
    assert any(month<36 for month in result['regimes']['nav_margin_payment'])
    assert any(month<36 for month in result['regimes']['term_locked_borrowing'])
    assert all(row['balance_check']==row['income_elimination_check']==row['cash_check']==0 for row in result['group'])
    assert all(row['cash_close']==row['loan_close']==row['deposit_close']==row['investment_close']==row['note_close']==row['equity']==0 for row in result['monthly'][-1].values())
    assert result['treasury'][-1]['treasury']['bank_close']==0
    assert all(Decimal(entry['amount'])>0 for entry in result['journal'])


def test_nav_margin_call_is_real_capital_not_unlisted_cash_plug(inputs):
    result=simulate_pool(*inputs)
    row=result['monthly'][3]['P4']
    assert row['loan_request']>row['loan_advance']==row['loan_capacity']>0
    assert row['capital_cash']>0 and row['capital_contribution']==row['capital_cash']
    next_month=result['monthly'][4]['P4']
    assert next_month['margin_required']>0 and next_month['capital_margin']>0
    assert next_month['called_close']<=Decimal(inputs[0]['members'][3]['capital_commitment'])
    broken=deepcopy(inputs[0]);broken['members'][3]['capital_commitment']=0
    with pytest.raises(ValueError,match='financial constraints'):simulate_pool(broken,*inputs[1:])


def test_term_deposit_is_not_used_as_available_loan_repayment_cash(inputs):
    result=simulate_pool(*inputs)
    row=result['monthly'][8]['P3']
    assert row['deposit_open']>0 and row['deposit_available']==0
    assert row['term_return']==0 and row['loan_advance']>0
    assert result['monthly'][12]['P3']['term_return']>0


def test_one_members_liquidity_changes_treasury_future_interest(inputs):
    baseline=simulate_pool(*inputs)
    alternative=deepcopy(inputs[0]);alternative['members'][0]['opening_cash']=1500000
    changed=simulate_pool(alternative,*inputs[1:])
    assert changed['treasury'][0]['treasury']['bank_close']>baseline['treasury'][0]['treasury']['bank_close']
    assert changed['treasury'][1]['treasury']['bank_interest']>baseline['treasury'][1]['treasury']['bank_interest']
    assert changed['group'][1]['net_income']!=baseline['group'][1]['net_income']
