from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from sheets_factory.workbook.heterogeneous_contracts.ledger import simulate
from sheets_factory.workbook.heterogeneous_contracts.spec import (
    ASSET_FIELDS, ENTITY_FIELDS, GROUP_FIELDS, LOAN_FIELDS, SCALE, load_spec,
)

ROOT = Path(__file__).resolve().parents[1]


def specification(loan_type="BULLET_QUARTERLY_ACCRUAL", periods=3):
    source = json.loads((ROOT / "config/heterogeneous_contracts/prototype_v1.json").read_text())
    s = copy.deepcopy(source)
    s["dimension_mode"] = "toy"
    s["months"] = source["months"][:periods]
    s["scenario_ids"] = ["S01"]
    s["scenarios"] = [{"id":"S01","name":"Hand calculation", "monthly_schedule":[
        {"month":m,"revenue_factor_p12":SCALE,"opex_factor_p12":SCALE,"annual_rate_spread_p12":0}
        for m in s["months"]]}]
    e = copy.deepcopy(source["entities"][0])
    e.update(opening_cash_pence=2000,opening_restricted_cash_pence=0,
             opening_paid_in_capital_pence=1800,opening_retained_earnings_pence=0,
             opening_tax_payable_pence=0,minimum_cash_pence=2000,reserve_target_pence=0,
             additional_lp_commitment_pence=10000,tax_policy="CASH_COUPON_QUARTERLY",
             tax_rate_p12=0,interest_cap_fraction_p12=300000000000,interest_carry_months=2,
             loss_carry_months=2,dscr_policy="QUARTERLY_LAGGED",dscr_threshold_p12=SCALE,
             opening_trap=False,opening_cure_count=0,opening_interest_carry=[],opening_tax_losses=[])
    s["entities"] = [e]
    s["loans"] = [{"id":"L01","entity_id":"E01","type":loan_type,
        "opening_principal_pence":1200,"opening_accrued_interest_pence":0,
        "terms":[{"id":"L01@2027-01-01","effective_month":"2027-01-01",
            "annual_rate_p12":SCALE,"day_count":"ACT_360","local_limit_pence":1200,
            "maturity_date":"2028-12-31","draw_cutoff_month":None if loan_type=="LEVEL_PRINCIPAL_MONTHLY" else "2027-03-01",
            "optional_repayment_fraction_p12":0,
            "next_coupon_month":"2027-03-01" if loan_type=="BULLET_QUARTERLY_ACCRUAL" else None}]}]
    s["assets"] = [{"id":"A01","entity_id":"E01","description":"Opening equipment",
        "commission_month":"2026-01-01","original_cost_pence":1000,
        "opening_accumulated_depreciation_pence":0,"useful_life_months":100,"capex_category":"GROWTH"}]
    s["operating_inputs"] = {"E01":[{"month":m,"base_cash_revenue_pence":0,"base_cash_opex_pence":0} for m in s["months"]]}
    s["group"].update(bank_funding_priority=["E01"],shared_margin_priority=["E01"],lp_funding_priority=["E01"],
                     additional_lp_commitment_pence=10000,shared_bank_limit_schedule=[{"effective_month":"2027-01-01","limit_pence":10000}])
    return s


def rows(s):
    return simulate(s)["scenarios"]["S01"]["entities"]["E01"]["monthly"]


def test_quarterly_accrual_is_liability_until_coupon_not_cash_interest():
    r = rows(specification())
    assert [x["interest_accrual"] for x in r] == [103,93,103]
    assert [x["cash_coupon"] for x in r] == [0,0,299]
    assert [x["interest_payable_close"] for x in r] == [103,196,0]
    assert [x["net_income"] for x in r] == [-113,-103,-113]
    assert [x["lp_call"] for x in r] == [0,0,299]
    assert [x["cash_close"] for x in r] == [2000,2000,2000]


def test_monthly_bullet_settles_coupon_each_month():
    r = rows(specification("BULLET_MONTHLY"))
    assert [x["cash_coupon"] for x in r] == [103,93,103]
    assert all(x["interest_payable_close"] == 0 for x in r)


def test_day_count_365f_differs_from_360():
    s = specification()
    s["loans"][0]["terms"][0]["day_count"] = "ACT_365F"
    assert [x["interest_accrual"] for x in rows(s)] == [102,92,102]


def test_interest_uses_one_final_round_not_rounded_rate():
    s = specification("BULLET_MONTHLY",1)
    s["loans"][0]["opening_principal_pence"] = 1
    s["entities"][0]["opening_paid_in_capital_pence"] = 2999
    # 1p * 100% *31/360 = .086...p, not a pre-rounded monthly numerator.
    assert rows(s)[0]["interest_accrual"] == 0


def test_new_month_end_draw_does_not_earn_current_month_interest():
    s = specification("BULLET_MONTHLY")
    s["loans"][0]["opening_principal_pence"] = 0
    s["loans"][0]["terms"][0]["local_limit_pence"] = 2000
    s["entities"][0]["opening_paid_in_capital_pence"] = 3000
    s["assets"].append({"id":"A02","entity_id":"E01","description":"Expansion",
        "commission_month":"2027-01-01","original_cost_pence":1000,
        "opening_accumulated_depreciation_pence":0,"useful_life_months":100,"capex_category":"GROWTH"})
    r = rows(s)
    assert r[0]["bank_draw"] == 1000 and r[0]["interest_accrual"] == 0
    assert r[1]["principal_open"] == 1000 and r[1]["interest_accrual"] == 78


def test_level_principal_recast_and_maturity_residual_are_exact():
    s = specification("LEVEL_PRINCIPAL_MONTHLY")
    t = s["loans"][0]["terms"][0]
    t["maturity_date"] = "2027-06-30"
    amendment = dict(t,id="L01@2027-02-01",effective_month="2027-02-01",maturity_date="2027-03-31")
    s["loans"][0]["terms"].append(amendment)
    result = simulate(s)["scenarios"]["S01"]
    loan = result["loans"]["L01"]["monthly"]
    assert [x["recast_instalment"] for x in loan] == [200,500,500]
    assert [x["scheduled_principal"] for x in loan] == [200,500,500]
    assert [x["interest_accrual"] for x in loan] == [103,78,43]
    assert loan[-1]["principal_close"] == 0


def test_off_cycle_maturity_settles_all_accrued_and_is_last_test():
    s = specification()
    s["entities"][0]["dscr_policy"] = "MONTHLY_CURRENT"
    s["loans"][0]["terms"][0]["maturity_date"] = "2027-02-28"
    r = rows(s)
    assert r[0]["cash_coupon"] == 0
    assert r[1]["cash_coupon"] == 196 and r[1]["scheduled_principal"] == 1200
    assert r[1]["test_applicable"] == 1 and r[1]["facility_closed_next"] == 1
    assert r[2]["test_applicable"] == 0 and r[2]["test_pass"] is None and r[2]["dscr_ratio_millionths"] is None
    assert r[2]["trap_next"] == 0 and r[2]["cure_next"] == 0


def test_coupon_amendment_preserves_opening_accrual():
    s = specification()
    t = dict(s["loans"][0]["terms"][0],id="L01@2027-02-01",effective_month="2027-02-01",next_coupon_month="2027-02-01")
    s["loans"][0]["terms"].append(t)
    r = rows(s)
    assert [x["cash_coupon"] for x in r] == [0,196,0]
    assert [x["interest_payable_close"] for x in r] == [103,0,103]


def test_tax_basis_cash_coupon_and_book_accrual_differ():
    a = specification()
    b = copy.deepcopy(a)
    b["entities"][0]["tax_policy"] = "ACCRUAL_MONTHLY"
    assert [x["eligible_current_interest"] for x in rows(a)] == [0,0,299]
    assert [x["eligible_current_interest"] for x in rows(b)] == [103,93,103]


def test_quarterly_tax_is_payable_until_cash_settlement():
    s = specification()
    s["loans"][0]["terms"][0]["annual_rate_p12"] = 0
    s["entities"][0]["tax_rate_p12"] = SCALE//4
    for r in s["operating_inputs"]["E01"]: r["base_cash_revenue_pence"] = 100
    r = rows(s)
    assert [x["current_tax_expense"] for x in r] == [23,23,23]  # 90p*.25 =22.5p
    assert [x["cash_tax"] for x in r] == [0,0,69]
    assert [x["tax_payable_close"] for x in r] == [23,46,0]


def test_expiry_and_fifo_use_are_separate_from_current_creation():
    s = specification()
    e = s["entities"][0]
    e.update(tax_rate_p12=SCALE//4,interest_carry_months=1,loss_carry_months=1,
             opening_interest_carry=[{"origin_month":"2026-12-01","amount_pence":20}],
             opening_tax_losses=[{"origin_month":"2026-11-01","amount_pence":50},{"origin_month":"2026-12-01","amount_pence":30}])
    s["operating_inputs"]["E01"][0]["base_cash_revenue_pence"] = 100
    r = rows(s)[0]
    assert (r["interest_old_used"],r["interest_current_allowed"]) == (20,0)
    assert (r["taxable_before_losses"],r["loss_expired"],r["loss_used"],r["taxable_after_losses"],r["current_tax_expense"]) == (70,50,30,40,10)


def test_fifo_competition_consumes_older_origin_first():
    s = specification()
    s["entities"][0].update(interest_carry_months=3,opening_interest_carry=[
        {"origin_month":"2026-11-01","amount_pence":20},{"origin_month":"2026-12-01","amount_pence":40}])
    s["operating_inputs"]["E01"][0]["base_cash_revenue_pence"] = 100
    q = simulate(s)["scenarios"]["S01"]["interest_vintages"]["E01"]["monthly"][0]
    assert q["used"] == 30 and q["closing"] == 30
    assert [(v["origin_month"],v["used"],v["closing"]) for v in q["entries"]] == [("2026-11-01",20,0),("2026-12-01",10,30)]


def test_carry_one_retains_previous_month_then_expires_at_age_two():
    s = specification()
    s["entities"][0].update(interest_carry_months=1,loss_carry_months=1,
        opening_interest_carry=[{"origin_month":"2026-12-01","amount_pence":20}],
        opening_tax_losses=[{"origin_month":"2026-12-01","amount_pence":30}])
    z = simulate(s)["scenarios"]["S01"]
    iq=z["interest_vintages"]["E01"]["monthly"]
    tq=z["loss_vintages"]["E01"]["monthly"]
    assert (iq[0]["expired"],iq[0]["closing"],iq[1]["expired"]) == (0,20,20)
    assert (tq[0]["expired"],tq[1]["expired"]) == (0,30)
    assert next(v for v in tq[1]["entries"] if v["origin_month"]=="2027-01-01")["closing"] == 10


def test_tested_zero_debt_service_has_blank_ratio_but_nonblank_pass():
    s = specification()
    s["entities"][0]["dscr_policy"] = "MONTHLY_CURRENT"
    r = rows(s)[0]
    assert (r["test_applicable"],r["dscr_ratio_millionths"],r["test_pass"]) == (1,None,1)


def test_quarterly_non_test_fields_are_na_but_rolling_cash_is_real():
    s = specification()
    for r in s["operating_inputs"]["E01"]: r["base_cash_revenue_pence"] = 100
    r = rows(s)
    assert [x["test_applicable"] for x in r] == [0,0,1]
    assert [x["dscr_window_cfads"] for x in r] == [100,200,300]
    assert r[0]["test_pass"] is None and r[1]["dscr_ratio_millionths"] is None


def test_monthly_breach_applies_now_quarterly_breach_next_month():
    s = specification("BULLET_MONTHLY")
    s["entities"][0]["dscr_policy"] = "MONTHLY_CURRENT"
    r = rows(s)
    assert (r[0]["trap_open"],r[0]["trap_operative"],r[0]["trap_next"]) == (0,1,1)
    q = rows(specification())[-1]
    assert (q["test_pass"],q["trap_open"],q["trap_operative"],q["trap_next"]) == (0,0,0,1)


def test_two_observed_passes_release_only_following_month():
    s = specification("BULLET_MONTHLY")
    e = s["entities"][0]
    e.update(opening_trap=True,opening_restricted_cash_pence=500,reserve_target_pence=500,
             opening_paid_in_capital_pence=2300,dscr_policy="MONTHLY_CURRENT")
    for r in s["operating_inputs"]["E01"]: r["base_cash_revenue_pence"] = 300
    r = rows(s)
    assert [(x["trap_operative"],x["trap_next"],x["cure_next"]) for x in r] == [(1,1,1),(1,0,2),(0,0,0)]
    assert r[0]["reserve_released"] == r[1]["reserve_released"] == 0
    assert r[2]["reserve_released"] == 500


def test_quarterly_cure_counter_does_not_advance_in_two_non_test_months():
    s = specification()
    e=s["entities"][0]
    e.update(opening_trap=True,opening_cure_count=1,opening_restricted_cash_pence=500,
             opening_paid_in_capital_pence=2300,reserve_target_pence=500)
    for x in s["operating_inputs"]["E01"]:x["base_cash_revenue_pence"] = 300
    r=rows(s)
    assert [x["test_applicable"] for x in r] == [0,0,1]
    assert [x["cure_next"] for x in r] == [1,1,2]
    assert r[2]["trap_operative"] == 1 and r[2]["trap_next"] == 0


def test_finite_capital_shortfall_is_infeasible_without_breaking_accounts():
    s = specification("BULLET_MONTHLY")
    s["loans"][0]["terms"][0]["local_limit_pence"] = 1200
    s["entities"][0]["additional_lp_commitment_pence"] = 1
    s["group"]["additional_lp_commitment_pence"] = 1
    result = simulate(s)
    assert not result["feasible"]
    r = result["scenarios"]["S01"]["entities"]["E01"]["monthly"]
    assert r[0]["lp_call"] == 1 and r[0]["funding_gap"] == 102
    assert all(x["balance_sheet_check"] == x["cash_check"] == 0 for x in r)


def test_unbalanced_opening_is_not_repaired_with_equity_plug():
    s = specification()
    s["entities"][0]["opening_paid_in_capital_pence"] += 1
    with pytest.raises(ArithmeticError,match="opening trial"):
        simulate(s)


@pytest.mark.parametrize("field,value",[("opening_cash_pence",True),("tax_rate_p12",1),("opening_trap",1)])
def test_schema_rejects_boolean_money_unrepresentable_rate_or_untyped_flag(field,value):
    s = specification()
    s["entities"][0][field] = value
    with pytest.raises(ValueError): load_spec(s)


def test_schema_rejects_negative_effective_interest_and_bad_maturity():
    s = specification()
    s["loans"][0]["terms"][0]["annual_rate_p12"] = 0
    s["scenarios"][0]["monthly_schedule"][0]["annual_rate_spread_p12"] = -1000000
    with pytest.raises(ValueError,match="effective rate"): load_spec(s)
    s = specification()
    s["loans"][0]["terms"][0]["maturity_date"] = "2027-02-27"
    with pytest.raises(ValueError,match="month end"): load_spec(s)


def test_toy_mode_cannot_silently_expand_or_omit_calendar():
    s = specification()
    s["months"][1] = "2027-04-01"
    with pytest.raises(ValueError,match="consecutive"): load_spec(s)


def test_public_schema_and_result_fields_are_complete_and_inputs_unchanged():
    s = specification()
    original = copy.deepcopy(s)
    result = simulate(s)["scenarios"]["S01"]
    assert s == original
    assert set(result["entities"]["E01"]["monthly"][0]) == set(ENTITY_FIELDS)
    assert set(result["assets"]["A01"]["monthly"][0]) == set(ASSET_FIELDS)
    assert set(result["loans"]["L01"]["monthly"][0]) == set(LOAN_FIELDS)
    assert set(result["group_monthly"][0]) == set(GROUP_FIELDS)
    for kind in ("interest_vintages","loss_vintages"):
        for q in result[kind]["E01"]["monthly"]:
            assert isinstance(q["entries"],list)
            assert len({v["origin_month"] for v in q["entries"]}) == len(q["entries"])
            assert all(all(type(v[k]) is int and v[k] >= 0 for k in ("opening","expired","used","created","closing")) for v in q["entries"])


def test_penny_depreciation_clamps_and_final_residual_cannot_be_negative():
    s = specification()
    s["assets"][0].update(original_cost_pence=2,useful_life_months=4,commission_month="2027-01-01")
    s["entities"][0]["opening_paid_in_capital_pence"] = 800
    r = simulate(s)["scenarios"]["S01"]["assets"]["A01"]["monthly"]
    assert [v["depreciation"] for v in r] == [0,1,1]
    assert all(v["nbv_close"] >= 0 for v in r)


def two_entity_specification():
    s = specification("BULLET_MONTHLY")
    e = copy.deepcopy(s["entities"][0]); e["id"] = "E02"
    l = copy.deepcopy(s["loans"][0]); l.update(id="L02",entity_id="E02")
    for t in l["terms"]:t["id"] = "L02@"+t["effective_month"]
    a = copy.deepcopy(s["assets"][0]); a.update(id="A02",entity_id="E02")
    s["entities"].append(e);s["loans"].append(l);s["assets"].append(a)
    s["operating_inputs"]["E02"] = copy.deepcopy(s["operating_inputs"]["E01"])
    for key in ("bank_funding_priority","shared_margin_priority","lp_funding_priority"):
        s["group"][key] = ["E02","E01"]
    return s


def test_shared_margin_priority_changes_later_interest_not_current_interest():
    s = two_entity_specification()
    for l in s["loans"]:
        l["type"] = "BULLET_QUARTERLY_ACCRUAL"
        l["terms"][0]["next_coupon_month"] = "2027-03-01"
    s["group"]["shared_bank_limit_schedule"][0]["limit_pence"] = 1800
    z = simulate(s)["scenarios"]["S01"]["entities"]
    assert z["E02"]["monthly"][0]["shared_margin_principal"] == 600
    assert z["E01"]["monthly"][0]["shared_margin_principal"] == 0
    assert z["E02"]["monthly"][0]["interest_accrual"] == z["E01"]["monthly"][0]["interest_accrual"] == 103
    assert z["E02"]["monthly"][1]["interest_accrual"] == 47


def test_shared_drawing_headroom_and_capital_priority_are_actual_nonlocal_flows():
    s = two_entity_specification()
    for e,l in zip(s["entities"],s["loans"]):
        e["opening_paid_in_capital_pence"] = 3000
        l["opening_principal_pence"] = 0
        l["terms"][0]["local_limit_pence"] = 2000
    for i,e in enumerate(s["entities"],3):
        s["assets"].append({"id":f"A{i:02d}","entity_id":e["id"],"description":"Expansion",
            "commission_month":"2027-01-01","original_cost_pence":1000,
            "opening_accumulated_depreciation_pence":0,"useful_life_months":100,"capex_category":"GROWTH"})
    s["group"]["shared_bank_limit_schedule"][0]["limit_pence"] = 1000
    z = simulate(s)["scenarios"]["S01"]["entities"]
    assert (z["E02"]["monthly"][0]["bank_draw"],z["E01"]["monthly"][0]["bank_draw"]) == (1000,0)
    assert (z["E02"]["monthly"][0]["lp_call"],z["E01"]["monthly"][0]["lp_call"]) == (0,1000)


def test_scenarios_reset_without_shared_mutable_finance_or_fifo_state():
    s = specification()
    s["scenario_ids"] = ["S01","S02"]
    z = copy.deepcopy(s["scenarios"][0]);z["id"] = "S02";s["scenarios"].append(z)
    out = simulate(s)["scenarios"]
    assert out["S01"] == out["S02"]
    out["S01"]["entities"]["E01"]["monthly"][0]["cash_close"] += 1
    assert out["S02"]["entities"]["E01"]["monthly"][0]["cash_close"] == 2000


def test_schema_rejects_unsupported_term_and_reopening_after_maturity():
    s = specification()
    s["loans"][0]["terms"][0]["hidden_repayment"] = 10
    with pytest.raises(ValueError,match="keys"):
        load_spec(s)
    s = specification()
    t=s["loans"][0]["terms"][0];t["maturity_date"]="2027-01-31"
    s["loans"][0]["terms"].append(dict(t,id="L01@2027-02-01",effective_month="2027-02-01",maturity_date="2027-03-31",next_coupon_month="2027-03-01"))
    with pytest.raises(ValueError,match="reopened"):
        load_spec(s)
