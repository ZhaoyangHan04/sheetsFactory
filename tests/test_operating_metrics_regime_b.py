"""Hand arithmetic and exact gate/rounding boundaries for independent oracle B."""
from copy import deepcopy
from fractions import Fraction as F
import ast
from pathlib import Path

import pytest

from sheets_factory.workbook.operating_metrics_regime import oracle_b as b
from sheets_factory.workbook.operating_metrics_regime.spec import default_spec, NA


def hand_public(layout="expense_columns",unit="GBP",basis="yoy_percent"):
    public=default_spec();entity=deepcopy(public["entities"][0]);public["entities"]=[entity]
    entity.update(id="HAND",layout=layout,money_unit=unit,sales_basis=basis,actual_revenue=["100"]*4,
        forecast_sales_assumptions=["0"]*8 if basis=="yoy_percent" else ["1"]*8,
        direct_cost_percent="20",quarterly_fixed_opex=["10"]*12,annual_interest_percent="4",
        tax_percent="25",associate_results=["0"]*4+["10","-5"]+["0"]*6)
    entity["opening"]={"cash":"500","investment":"200","debt":"100","capital":"500","retained_earnings":"100"}
    return public


def test_hand_income_associate_sign_and_cash_balance_are_independent():
    public=hand_public();before=deepcopy(public);values=b.solve(public)["exact_values"]
    assert public==before
    get=lambda period,field:values[f"HAND/{period}/{field}"]
    assert get("2026Q1","operating_profit")==70
    assert get("2026Q1","interest")==1
    assert get("2026Q1","current_tax")==F(69,4)
    assert get("2026Q1","core_net_income")==F(207,4)
    assert get("2026Q1","net_income")==F(247,4)
    assert get("2026Q1","reported_associate_line")==10
    assert get("2026Q1","closing_cash")==500+5*F(207,4)
    assert get("2026Q1","closing_investment")==210
    assert get("2026Q1","closing_retained_earnings")==100+5*F(207,4)+10
    assert get("2026Q2","associate_income")==-5
    assert get("2026Q2","net_income")==F(187,4)
    for period in [f"{y}Q{q}" for y in range(2025,2028) for q in range(1,5)]:
        assert get(period,"total_assets")==get(period,"total_liabilities_equity")
    assert get("FY2027","distribution_eligible") is False


def test_layout_signs_change_reported_lines_without_changing_business_state():
    positive=b.solve(hand_public())["exact_values"];signed=b.solve(hand_public("signed_rows"))["exact_values"]
    for field in ("direct_cost","operating_expense","interest","current_tax"):
        key="HAND/2026Q1/reported_"+field
        assert positive[key]==-signed[key]
    for field in ("net_income","closing_cash","closing_investment","reported_associate_line"):
        assert positive["HAND/2026Q1/"+field]==signed["HAND/2026Q1/"+field]
    assert positive["HAND/2025Q4/reported_associate_line"]==0
    assert positive["HAND/2026Q1/net_income"]!=positive["HAND/2026Q1/core_net_income"]-10


def test_sequential_multiple_crosses_year_boundary_and_growth_is_not_ratio():
    public=hand_public(basis="qoq_multiple");entity=public["entities"][0]
    entity["actual_revenue"]=["50","60","70","80"];entity["forecast_sales_assumptions"]=["1.1"]*8
    values=b.solve(public)["exact_values"]
    assert values["HAND/2026Q1/revenue"]==88
    assert values["HAND/2026Q1/qoq_percent"]==10
    assert values["HAND/2026Q1/yoy_percent"]==76
    assert values["HAND/2026Q1/prior_year_multiple"]==F(44,25)
    assert values["HAND/2026Q1/prior_year_index"]==176
    assert values["HAND/2025Q1/qoq_percent"]==NA
    assert values["HAND/2025Q4/yoy_percent"]==NA
    assert values["HAND/FY2025/cagr_percent"]==NA


@pytest.mark.parametrize("value,expected",[(F(1,200),"0.01"),(-F(1,200),"-0.01"),
    (F(2469,200),"12.35"),(-F(2469,200),"-12.35"),(F(1,100000),"0.00"),(-F(1,100000),"-0.00")])
def test_exact_numeric_half_away_display(value,expected):
    assert b.display(value)==expected


@pytest.mark.parametrize("growth,expected",[(F(12345,1000),"12.35"),(-F(12345,1000),"-12.35"),
    (F(12345,1000)-F(1,10**10),"12.34"),(-F(12345,1000)+F(1,10**10),"-12.34"),
    (F(0),"0.00"),(-F(1,10**6),"-0.00"),(F(8),"8.00")])
def test_cagr_halfway_and_negative_zero_use_exact_squares(growth,expected):
    ratio=(1+growth/100)**2;text,proof=b.cagr_display(ratio)
    assert text==expected
    assert F(proof["root_lower"])**2<=ratio<F(proof["root_upper_exclusive"])**2
    assert proof["display"]==expected


def test_cagr_gate_equal_qualifies_and_displayed_equality_does_not():
    public=hand_public();entity=public["entities"][0]
    entity["associate_results"]=["0"]*12
    entity["forecast_sales_assumptions"]=["0"]*4+["16.64"]*4
    result=b.solve(public);values=result["exact_values"]
    assert result["display_values"]["HAND/FY2027/cagr_percent"]["value"]=="8.00"
    assert values["HAND/FY2027/distribution_eligible"] is True
    assert values["HAND/2027Q4/dividend"]==values["HAND/FY2027/net_income"]*F(1,5)
    entity["forecast_sales_assumptions"]=["0"]*4+["16.63999"]*4
    result=b.solve(public)
    assert result["display_values"]["HAND/FY2027/cagr_percent"]["value"]=="8.00"
    assert result["exact_values"]["HAND/FY2027/distribution_eligible"] is False
    assert result["exact_values"]["HAND/2027Q4/dividend"]==0


def test_q4_yoy_gate_uses_unrounded_exact_change_not_rounded_display():
    public=hand_public();entity=public["entities"][0];entity["associate_results"]=["0"]*12
    entity["forecast_sales_assumptions"]=["0"]*4+["40","40","40","4.999999"]
    result=b.solve(public)
    assert result["display_values"]["HAND/2027Q4/yoy_percent"]["value"]=="5.00"
    assert result["exact_values"]["HAND/FY2027/distribution_eligible"] is False
    entity["forecast_sales_assumptions"][-1]="5"
    assert b.solve(public)["exact_values"]["HAND/FY2027/distribution_eligible"] is True


def test_tax_loss_has_no_credit_or_carryforward_and_positive_income_is_required():
    public=hand_public();entity=public["entities"][0];entity["associate_results"]=["0"]*12
    entity["quarterly_fixed_opex"][4]="100";values=b.solve(public)["exact_values"]
    assert values["HAND/2026Q1/pretax_before_associate"]==-21
    assert values["HAND/2026Q1/current_tax"]==0
    assert values["HAND/2026Q2/current_tax"]==F(69,4)
    entity["opening"].update(cash="20000",capital="20000")
    entity["quarterly_fixed_opex"]=["1000"]*12
    entity["forecast_sales_assumptions"]=["20"]*8
    result=b.solve(public)
    # All growth gates would pass, but annual income is negative.
    assert result["exact_values"]["HAND/FY2027/net_income"]<0
    assert result["exact_values"]["HAND/FY2027/distribution_eligible"] is False


def test_portfolio_converts_money_before_metrics_and_does_not_average_ratios():
    public=hand_public(unit="GBP_thousands");second=deepcopy(public["entities"][0]);second.update(id="OTHER",money_unit="GBP",actual_revenue=["200"]*4)
    public["entities"].append(second);values=b.solve(public)["exact_values"]
    assert values["PORTFOLIO/2025Q1/revenue"]==100200
    total=values["HAND/2025Q1/net_income"]*1000+values["OTHER/2025Q1/net_income"]
    assert values["PORTFOLIO/2025Q1/net_income"]==total
    margin=values["PORTFOLIO/2025Q1/net_margin_percent"]
    assert margin==total/F(100200)*100
    assert margin!=(values["HAND/2025Q1/net_margin_percent"]+values["OTHER/2025Q1/net_margin_percent"])/2


@pytest.mark.parametrize("which",["cash","investment"])
def test_negative_ending_assets_are_rejected_without_funding_plug(which):
    public=hand_public();entity=public["entities"][0]
    if which=="cash":entity["quarterly_fixed_opex"]=["10000"]*12
    else:entity["associate_results"][4]="-201"
    with pytest.raises(ValueError,match="Negative closing"):
        b.solve(public)


def test_default_complete_scope_keeps_exact_states_and_independent_import_boundary():
    result=b.solve(default_spec());values=result["exact_values"]
    assert len(values)==2052 and set(values)==set(result["display_values"])
    assert values["ALDER/FY2027/distribution_eligible"] is True
    assert values["BEACON/FY2027/distribution_eligible"] is False
    assert values["CEDAR/FY2027/distribution_eligible"] is True
    assert values["DELTA/FY2027/distribution_eligible"] is False
    assert values["ALDER/FY2027/cagr_percent"]==("cagr_percent",F(729,625),2)
    assert len(result["cagr_proofs"])==5
    assert all(type(v) in (F,str,bool,tuple) for v in values.values())
    tree=ast.parse(Path(b.__file__).read_text());imports=[n for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom))]
    assert all(getattr(n,"module",None) in ("fractions","math","spec") for n in imports)
    assert not any(isinstance(n,ast.Name) and n.id in ("Decimal","openpyxl","oracle_a") for n in ast.walk(tree))
