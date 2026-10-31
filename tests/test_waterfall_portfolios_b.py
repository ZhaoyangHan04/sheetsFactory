from copy import deepcopy
from datetime import date
from fractions import Fraction
import ast
from pathlib import Path

import pytest

from sheets_factory.workbook.waterfall_portfolios_v1 import oracle_b as b, schema


def terms(**changes):
    value = {'lp1_share_bp':3500, 'preferred_rate_bp':600, 'compound_unpaid_preference':False,
        'base_gp_carry_bp':2000, 'promote_gp_bp':[2000,3000,4000],
        'lp_distribution_multiple_threshold_bp':[12500,17500]}
    value.update(changes)
    return value


def state(**changes):
    value = {'cash':0,'unreturned_capital':0,'unpaid_preference':0,'cumulative_lp_paid_in':1000,
        'cumulative_lp_distributions':0,'cumulative_lp_profit':0,'cumulative_gp_profit':0}
    value.update(changes)
    return value


def period(year=2027, **changes):
    value = {'year':year,'call_date':f'{year}-01-01',**{k:0 for k in schema.PERIOD_MONEY_FIELDS}}
    value.update(changes)
    return value


def toy():
    years = [2025,2026,2027,2028]
    funds = []
    for number in (1,2):
        fund = {'id':f'F{number:03d}','number':number,'type':schema.FUND_TYPES[number-1],
            'layout':schema.LAYOUTS[number-1],
            'fund_ledger_sign':'signed_cash_uses' if number==1 else 'positive_deduction_uses',
            **terms(compound_unpaid_preference=number==2), 'call_month':1,'commitment_pence':100000,
            'opening_cash_pence':10000,'opening_investment_book_cost_pence':0,
            'opening_unreturned_capital_pence':10000,'opening_unpaid_preference_pence':0,
            'opening_cumulative_lp_paid_in_pence':10000,'opening_cumulative_lp_distributions_pence':0,
            'opening_cumulative_lp_profit_pence':0,'opening_cumulative_gp_profit_pence':0,'scenarios':[]}
        for scenario in ('BASE','UP'):
            fund['scenarios'].append({'id':scenario,'periods':[period(y,reserve_pence=9000,
                realization_receipts_pence=(100000 if scenario=='BASE' else 120000) if y==2028 else 0) for y in years]})
        funds.append(fund)
    return {'kind':schema.SPEC_KIND,'version':1,'dimension_mode':'toy',
        'contract':{'path':str(schema.CONTRACT_PATH),'sha256':schema.CONTRACT_SHA256,'bytes':15174},
        'contract_sha256':schema.CONTRACT_SHA256,'seed':1,'years':years,'historical_years':[2025,2026],
        'scenario_ids':['BASE','UP'],'funds':funds}


@pytest.mark.parametrize(('value','expected'),[(Fraction(1,2),1),(Fraction(-1,2),-1),
    (Fraction(149,100),1),(Fraction(150,100),2),(Fraction(-150,100),-2),(0,0),(3,3)])
def test_independent_exact_posting_ties_away(value, expected):
    assert b.round_pence(value)==expected


@pytest.mark.parametrize('bad',[True,False,0.5,'1'])
def test_float_boolean_and_string_are_not_posting_inputs(bad):
    with pytest.raises(ValueError):b.round_pence(bad)


def test_capped_endpoint_matches_exhaustive_small_integer_search():
    for gp in (2000,3000,4000,5000):
        for cash in range(50):
            for limit in range(20):
                candidates=[x for x in range(cash+1) if (2*x*(10000-gp)+10000)//20000<=limit]
                expected=max(candidates)
                total,lp,paid_gp=b.capped_tier(cash,limit,gp)
                assert total==expected
                assert lp+paid_gp==total and lp<=limit
                if total<cash:assert (2*(total+1)*(10000-gp)+10000)//20000>limit
    assert b.capped_tier(100,1,5000)==(2,1,1)


def test_exact_calendar_leap_year_new_call_and_opening_only_compounding():
    opening=state(unreturned_capital=10000,unpaid_preference=1000)
    raw=period(2028,call_date='2028-07-01',lp_call_pence=10000,asset_investment_pence=10000)
    row,next_state,proof=b.calculate_period(terms(preferred_rate_bp=1000,compound_unpaid_preference=True),raw,opening)
    assert proof['days_in_period']==366 and proof['called_capital_days']==184
    assert row['preference_accrual']==1607
    assert row['closing_unpaid_preference']==2607
    assert next_state['unpaid_preference']==2607
    simple=b.calculate_period(terms(preferred_rate_bp=1000),raw,opening)[0]
    assert simple['preference_accrual']==1507
    assert opening['unpaid_preference']==1000


def test_historical_zero_rate_overrides_contract_rate_and_keeps_old_entitlement():
    row,_,_=b.calculate_period(terms(preferred_rate_bp=10000,compound_unpaid_preference=True),
        period(2025),state(unreturned_capital=1000,unpaid_preference=50),historical=True)
    assert row['preference_accrual']==0 and row['preference_entitlement']==50


def test_priority_order_uses_paid_preference_and_retains_unpaid_balances():
    row,next_state,_=b.calculate_period(terms(preferred_rate_bp=0),period(realization_receipts_pence=150),
        state(unreturned_capital=100,unpaid_preference=200))
    assert [row[k] for k in ('capital_paid','preference_paid','after_capital_cash','after_preference_cash')]==[100,50,50,0]
    assert row['lp_profit_before_catchup']==50
    assert row['catchup_entitlement']==13 and row['catchup_paid']==0
    assert next_state['unpaid_preference']==150 and next_state['unreturned_capital']==0
    assert row['capital_and_pref_shortfall'] is True
    assert all(row[k]==0 for k in schema.INVARIANT_FIELDS)


def test_cumulative_catchup_excludes_principal_and_uses_previous_gp_profit():
    row,_,_=b.calculate_period(terms(preferred_rate_bp=0),period(realization_receipts_pence=1000),
        state(unpaid_preference=100,cumulative_lp_paid_in=1000))
    assert row['catchup_entitlement']==25 and row['catchup_paid']==25
    assert row['tier1_cash']==875 and row['tier1_lp']==700 and row['tier1_gp']==175
    assert row['lp_total_distribution']==800 and row['gp_total_distribution']==200
    assert row['cumulative_lp_profit']==800 and row['cumulative_gp_profit']==200
    past=b.calculate_period(terms(preferred_rate_bp=0),period(realization_receipts_pence=1000),
        state(unpaid_preference=100,cumulative_lp_paid_in=1000,cumulative_gp_profit=30))[0]
    assert past['catchup_entitlement']==0


@pytest.mark.parametrize(('previous_lp','tier','lp','gp'),[(125,2,7,3),(175,3,6,4)])
def test_exact_dpi_threshold_equality_enters_next_tier(previous_lp,tier,lp,gp):
    row,_,_=b.calculate_period(terms(preferred_rate_bp=0),period(realization_receipts_pence=10),
        state(cumulative_lp_paid_in=100,cumulative_lp_distributions=previous_lp,
              cumulative_lp_profit=previous_lp-100,cumulative_gp_profit=100))
    assert row[f'tier{tier}_cash']==10
    assert row[f'tier{tier}_lp']==lp and row[f'tier{tier}_gp']==gp
    assert row['tier1_cash']==0


def test_promotes_use_rounded_paid_in_thresholds_and_sequential_balancing():
    row,_,proof=b.calculate_period(terms(preferred_rate_bp=0),period(realization_receipts_pence=100),
        state(cumulative_lp_paid_in=101,cumulative_lp_distributions=125,
              cumulative_lp_profit=24,cumulative_gp_profit=100))
    assert proof['tier_thresholds_pence']==[126,177]
    assert row['tier1_cash']==1 and row['tier1_lp']==1
    assert row['tier2_lp']==51
    assert row['tier1_cash']+row['tier2_cash']+row['tier3_cash']==100
    assert row['fund_total_distribution']==100


def test_lp_classes_receive_one_rounded_aggregate_share_and_balance_pence():
    row,_,_=b.calculate_period(terms(preferred_rate_bp=0),period(lp_call_pence=1),state())
    assert row['lp1_call']==0 and row['lp2_call']==1
    assert row['lp1_distribution']==0 and row['lp2_distribution']==1
    assert row['lp1_net_cashflow']+row['lp2_net_cashflow']+row['gp_net_cashflow']==0
    assert row['recipient_cash_residual']==0


def test_affordable_reserve_and_terminal_shortfall_do_not_create_cash():
    row,_,_=b.calculate_period(terms(),period(2044,reserve_pence=10),state(cash=5,unreturned_capital=100))
    assert row['cash_before_distribution']==5 and row['available_cash']==0
    assert row['closing_cash']==5 and row['fund_total_distribution']==0
    terminal=b.calculate_period(terms(preferred_rate_bp=0),period(2044,reserve_pence=0),
        state(cash=5,unreturned_capital=100))[0]
    assert terminal['capital_paid']==5 and terminal['closing_unreturned_capital']==95
    assert terminal['fund_total_distribution']==5 and terminal['capital_and_pref_shortfall'] is True


def test_negative_cash_rejects_without_loan_or_replacement():
    with pytest.raises(ValueError,match='Negative fund cash'):
        b.calculate_period(terms(),period(operating_cost_pence=1),state())


def test_complete_toy_census_aggregates_scenario_reset_and_immutability():
    public=toy();before=deepcopy(public);result=b.solve(public)
    assert public==before
    assert result['implementation']=='B' and result['specification_sha256']==schema.canonical_sha256(public)
    assert len(result['row_order'])==16 and len(result['rows'])==16
    assert len(result['aggregate_order'])==8
    assert result['row_order']==[f'F{n:03d}/{s}/{y}' for n in (1,2) for s in ('BASE','UP') for y in public['years']]
    for key,row in result['rows'].items():
        assert set(row)==set(schema.ROW_FIELDS)|{'lp_distribution_multiple','capital_and_pref_shortfall'}
        assert all(type(row[f]) is int for f in schema.ROW_FIELDS)
        assert all(row[f]==0 for f in schema.INVARIANT_FIELDS)
        assert row['lp_distribution_multiple']=={'numerator':row['cumulative_lp_distributions'],'denominator':row['cumulative_lp_paid_in']}
    for scenario in ('BASE','UP'):
        assert result['rows'][f'F001/{scenario}/2025']['opening_cash']==10000
    assert result['rows']['F002/BASE/2028']['preference_accrual']>result['rows']['F001/BASE/2028']['preference_accrual']
    for key,aggregate in result['aggregates'].items():
        assert set(aggregate)==set(schema.AGGREGATE_FIELDS)
        for f in schema.AGGREGATE_FIELDS:
            assert aggregate[f]==sum(result['rows'][f'F{n:03d}/{key}'][f] for n in (1,2))
    assert result['proof']['row_monetary_value_count']==896
    assert result['proof']['aggregate_monetary_value_count']==160
    assert result['proof']['all_posted_and_declared_integer_intermediates_below_2_to_53'] is True
    assert result['proof']['new_solver_LO_model_Harbor_calls']==0


@pytest.mark.parametrize('mutation',[
    lambda p:p.update(contract_sha256='0'*64),
    lambda p:p['funds'][0]['scenarios'][0]['periods'].pop(),
    lambda p:p['funds'][0]['scenarios'][0]['periods'][0].update(lp_call_pence=True),
    lambda p:p['funds'][0]['scenarios'][0]['periods'][0].update(lp_call_pence=0.5),
    lambda p:p['funds'][0]['scenarios'][0]['periods'][0].update(call_date='2025-02-01'),
    lambda p:p.update(dimension_mode='production')])
def test_incomplete_wrong_bound_or_noninteger_public_inputs_reject(mutation):
    public=toy();mutation(public)
    with pytest.raises(ValueError):b.solve(public)


def test_b_imports_only_shape_vocabulary_and_standard_exact_arithmetic():
    source=Path(b.__file__).read_text();tree=ast.parse(source)
    imports=[node for node in ast.walk(tree) if isinstance(node,(ast.Import,ast.ImportFrom))]
    names=[]
    for node in imports:
        if isinstance(node,ast.Import):names.extend(a.name for a in node.names)
        elif node.module:names.append(node.module)
        else:names.extend(a.name for a in node.names)
    assert set(names)=={'__future__','datetime','fractions','schema'}
    assert 'Decimal' not in source and 'oracle_a' not in source and 'eval(' not in source
