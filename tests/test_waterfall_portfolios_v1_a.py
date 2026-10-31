from copy import deepcopy
from decimal import Decimal
from fractions import Fraction

import pytest

from sheets_factory.workbook.waterfall_portfolios_v1 import oracle_a as a, raw, schema


def toy(*,years=(2027,),paid=10000,receipts=20000,rate=1000,compound=False):
    p=raw.build_spec(dimension_mode='toy',years=list(years))
    f=p['funds'][0]
    f.update(preferred_rate_bp=rate,compound_unpaid_preference=compound,base_gp_carry_bp=2000,
        call_month=1,opening_cash_pence=0,opening_investment_book_cost_pence=paid,
        opening_unreturned_capital_pence=paid,opening_unpaid_preference_pence=0,
        opening_cumulative_lp_paid_in_pence=paid,opening_cumulative_lp_distributions_pence=0,
        opening_cumulative_lp_profit_pence=0,opening_cumulative_gp_profit_pence=0)
    for period in f['scenarios'][0]['periods']:
        for key in schema.PERIOD_MONEY_FIELDS:period[key]=0
        period['operating_receipts_pence']=receipts
        period['call_date']=f"{period['year']}-01-01"
    return p


def row(p,year=None):
    result=a.solve(p)
    return result['rows'][f"F001/BASE/{year or p['years'][0]}"],result


def test_hand_cash_sufficient_waterfall_with_catchup_and_promote():
    r,result=row(toy())
    expected={'capital_paid':10000,'preference_accrual':1000,'preference_paid':1000,
        'after_capital_cash':10000,'after_preference_cash':9000,
        'catchup_entitlement':250,'catchup_paid':250,'after_catchup_cash':8750,
        'tier1_cash':1875,'tier1_lp':1500,'tier1_gp':375,
        'tier2_cash':6875,'tier2_lp':4813,'tier2_gp':2062,
        'tier3_cash':0,'lp_total_distribution':17313,'gp_total_distribution':2687,
        'fund_total_distribution':20000,'closing_cash':0,'closing_unreturned_capital':0,'closing_unpaid_preference':0}
    assert {key:r[key] for key in expected}==expected
    assert all(r[key]==0 for key in schema.INVARIANT_FIELDS)
    assert r['lp_distribution_multiple']=={'numerator':17313,'denominator':10000}
    assert result['proof']['declared_forecast_fault_count']==1
    assert result['proof']['forecast_faults'][0]['immediate_impact_pence']==2000


def test_capital_shortfall_does_not_pay_an_entitlement_or_invent_finance():
    r,_=row(toy(receipts=4000))
    assert r['capital_paid']==4000 and r['preference_paid']==0 and r['catchup_paid']==0
    assert r['closing_unreturned_capital']==6000 and r['closing_unpaid_preference']==1000
    assert r['fund_total_distribution']==4000 and r['capital_and_pref_shortfall'] is True


def test_preference_shortfall_carries_independently_of_capital():
    r,_=row(toy(receipts=10500))
    assert r['capital_paid']==10000 and r['preference_paid']==500
    assert r['closing_unreturned_capital']==0 and r['closing_unpaid_preference']==500
    assert r['catchup_entitlement']==125 and r['catchup_paid']==0


def test_actual_year_zero_preference_despite_positive_declared_future_rate():
    r,result=row(toy(years=(2025,),receipts=5000,rate=1000,compound=True))
    assert r['preference_accrual']==r['preference_entitlement']==r['preference_paid']==0
    assert result['proof']['state_counts']['historical_zero_preference']==1
    assert result['proof']['forecast_faults']==[]


def test_leap_year_new_call_and_opening_unpaid_accrual_once():
    p=toy(years=(2028,),paid=1000,receipts=0,compound=True)
    f=p['funds'][0]; f.update(call_month=4,opening_unpaid_preference_pence=50)
    period=f['scenarios'][0]['periods'][0];period.update(call_date='2028-04-01',lp_call_pence=100)
    r,_=row(p)
    # Opening1000*366 + new100*275 + opening unpaid50*366;10%;Actual/365 =>112.82p ->113p.
    assert r['preference_accrual']==113
    assert r['capital_entitlement']==1100 and r['capital_paid']==100
    assert r['closing_unreturned_capital']==1000 and r['closing_unpaid_preference']==163
    assert r['cumulative_lp_paid_in']==1100


def test_simple_preference_excludes_opening_unpaid_and_compound_includes_it():
    p=toy(years=(2028,),paid=1000,receipts=0)
    p['funds'][0]['opening_unpaid_preference_pence']=1000
    simple,_=row(p)
    p['funds'][0]['compound_unpaid_preference']=True
    compounded,_=row(p)
    assert simple['preference_accrual']==100 and compounded['preference_accrual']==201


def test_no_compounding_of_current_period_preference_before_next_period():
    p=toy(years=(2027,2028),paid=10000,receipts=0,compound=True)
    result=a.solve(p)
    first=result['rows']['F001/BASE/2027'];second=result['rows']['F001/BASE/2028']
    assert first['preference_accrual']==1000
    #10000 capital plus1000 prior preference,366/365*10%=1103.0137p, not current-on-current.
    assert second['preference_accrual']==1103 and second['closing_unpaid_preference']==2103


@pytest.mark.parametrize('gap,gp_bp,expected',[(1,3000,(2,1,1)),(1,2000,(1,1,0)),(5,3000,(7,5,2)),(0,4000,(0,0,0))])
def test_tier_endpoint_largest_cash_has_no_lp_penny_overshoot(gap,gp_bp,expected):
    got=a._tier(Decimal(100),Decimal(gap),Decimal(gp_bp),a._Safety())
    assert tuple(map(int,got))==expected


def test_independent_small_endpoint_census_all_three_promote_rates():
    for gp_bp in (2000,3000,4000):
        for gap in range(1,15):
            for cash in range(0,25):
                # Exhaustive integer-penny arithmetic in the test; A uses a strict closed-form endpoint.
                eligible=[n for n in range(cash+1) if (2*n*(10000-gp_bp)+10000)//20000<=gap]
                largest=max(eligible)
                tc,lp,gp=map(int,a._tier(Decimal(cash),Decimal(gap),Decimal(gp_bp),a._Safety()))
                assert tc==largest and lp<=gap and lp+gp==tc


def test_all_three_promote_tiers_advance_at_exact_lp_thresholds():
    r,_=row(toy(receipts=100000))
    assert r['capital_paid']+r['preference_paid']+r['tier1_lp']==12500
    assert r['capital_paid']+r['preference_paid']+r['tier1_lp']+r['tier2_lp']==17500
    assert r['tier1_cash']==1875 and r['tier2_cash']==7143 and r['tier3_cash']>0
    assert r['tier3_lp']+r['tier3_gp']==r['tier3_cash']


def test_class_rounding_applies_to_aggregate_distribution_not_every_priority():
    p=toy(paid=1,receipts=2,rate=10000)
    p['funds'][0]['lp1_share_bp']=5000
    r,_=row(p)
    assert r['capital_paid']==1 and r['preference_paid']==1
    assert r['lp1_distribution']==1 and r['lp2_distribution']==1
    # Rounding half a penny separately for each priority would incorrectly pay LP1 two pennies.
    p['funds'][0]['lp1_share_bp']=3500
    r,_=row(p)
    assert r['lp1_distribution']==1 and r['lp2_distribution']==1


def test_call_split_and_signed_net_cash_do_not_create_a_penny():
    p=toy(paid=100,receipts=0)
    p['funds'][0]['lp1_share_bp']=5000
    period=p['funds'][0]['scenarios'][0]['periods'][0];period.update(lp_call_pence=1,asset_investment_pence=1)
    r,_=row(p)
    assert r['lp1_call']==1 and r['lp2_call']==0
    assert r['lp1_net_cashflow']==-1 and r['lp2_net_cashflow']==0
    assert r['recipient_cash_residual']==0


def test_retained_cash_reserve_is_limited_by_affordability():
    p=toy(receipts=40);p['funds'][0]['scenarios'][0]['periods'][0]['reserve_pence']=50
    r,_=row(p)
    assert r['cash_before_distribution']==40 and r['available_cash']==0 and r['closing_cash']==40
    assert r['fund_total_distribution']==0


def test_terminal_unrecovered_entitlements_are_not_cash_payments():
    p=toy(years=(2044,),receipts=3000)
    r,_=row(p)
    assert r['closing_unreturned_capital']==7000 and r['closing_unpaid_preference']==1003
    assert r['fund_total_distribution']==3000 and r['closing_cash']==0


def test_fund_sign_representation_does_not_change_economics():
    p=toy();base=a.solve(p)
    p['funds'][0]['fund_ledger_sign']='positive_deduction_uses'
    other=a.solve(p)
    assert base['rows']==other['rows'] and base['aggregates']==other['aggregates']
    assert base['specification_sha256']!=other['specification_sha256']


def test_complete_row_and_aggregate_coverage_without_cross_fund_netting():
    p=toy(years=(2027,2028));second=deepcopy(p['funds'][0]);second.update(id='F002',number=2)
    second['scenarios'][0]['periods'][0]['operating_receipts_pence']=1000
    p['funds'].append(second)
    result=a.solve(p)
    assert len(result['rows'])==4 and len(result['aggregates'])==2
    for key,r in result['rows'].items():
        assert set(r)==set(schema.ROW_FIELDS)|{'lp_distribution_multiple','capital_and_pref_shortfall'}
        assert all(type(r[k]) is int for k in schema.ROW_FIELDS)
        assert all(r[k]==0 for k in schema.INVARIANT_FIELDS)
    assert result['aggregates']['BASE/2027']['fund_total_distribution']==21000
    assert result['rows']['F002/BASE/2027']['closing_unreturned_capital']==9000


def test_all_forecast_faults_retained_including_zero_immediate_impact():
    p=toy(years=(2027,2028),receipts=1000)
    result=a.solve(p)
    faults=result['proof']['forecast_faults']
    assert len(faults)==2 and all(x['zero_immediate_impact'] and x['immediate_impact_pence']==0 for x in faults)
    assert len(result['proof']['zero_immediate_impact_roots'])==2


def test_negative_cash_is_rejected_without_overdraft_or_state_mutation():
    p=toy(receipts=0);before=deepcopy(p)
    p['funds'][0]['scenarios'][0]['periods'][0]['operating_cost_pence']=1
    frozen=deepcopy(p)
    with pytest.raises(ValueError,match='Negative unfunded'):a.solve(p)
    assert p==frozen and p!=before


def test_intermediate_bound_is_checked_even_when_posted_result_is_smaller():
    p=toy(paid=1000000000000,receipts=0)
    with pytest.raises(ValueError,match=r'2\*\*53'):a.solve(p)


def test_inconsistent_opening_returned_capital_is_rejected():
    p=toy();p['funds'][0]['opening_unreturned_capital_pence']-=1
    with pytest.raises(ValueError,match='Opening contributed'):a.solve(p)


def test_safety_result_and_no_qualification_or_services():
    r,result=row(toy())
    assert 0<result['proof']['maximum_absolute_integer']<2**53
    assert result['proof']['integer_intermediates_checked']>100
    assert result['proof']['all_residuals_zero'] is True
    assert result['proof']['row_field_count']==56 and result['proof']['aggregate_field_count']==20
    assert result['qualified'] is False and result['model_LO_solver_calls']==0
