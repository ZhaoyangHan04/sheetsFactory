"""Hand-built tax queues and payment-date witnesses for independent B."""
from copy import deepcopy
from fractions import Fraction as F
import ast
import inspect

import pytest

from sheets_factory.workbook.tax_vintage_bridge_v2 import oracle_b as b, spec
from sheets_factory.workbook.operating_reports_200 import schema


def public(*members):
    if not members:
        members=({"id":"E001"},)
    entities=[]
    for changes in members:
        e={"id":"E001","name":"Hypothetical tax queue example","division":"Advisory",
            "layout":"quarter_columns","line_order":"statement_first","money_unit":"GBP",
            "rate_unit":"percent_units","statement_sign":"positive_deductions",
            "forecast_reference":"same_quarter_last_year","driver_form_by_year":{"2026":"change_rate","2027":"change_rate"},
            "opening":{"cash":"1000","investment":"200","debt":"100","capital":"1000","retained_earnings":"100"},
            "actual_sales":dict.fromkeys(schema.QUARTERS[:4],"100"),"forecast_sales":dict.fromkeys(schema.QUARTERS[4:],"0"),
            "direct_cost_rate":"25","cash_opex":dict.fromkeys(schema.QUARTERS,"10"),
            "annual_interest_rate":"4","parent_tax_rate":"20","associate_results":dict.fromkeys(schema.QUARTERS,"0")}
        e.update(changes);entities.append(e)
    base={"kind":schema.KIND,"version":1,"dimension_mode":"toy","seed":schema.SEED,"years":list(schema.YEARS),
        "base_currency":"GBP","provenance":"new hypothetical service businesses; no official workbook seed",
        "public_policy":"Hypothetical operating and distribution contract.",
        "distribution":{"year":2027,"profit_percent":"20","cagr_percent":"8","q4_yoy_percent":"5"},
        "divisions":["Advisory"],"entities":entities}
    investment={e["id"]:{"method":"equity","tax_class":"recognized","feed_scale":1,
        "direction_by_year":dict.fromkeys(("2025","2026","2027"),"income_positive"),
        "share_postings":dict.fromkeys(schema.QUARTERS,"0"),"cash_receipts":dict.fromkeys(schema.QUARTERS,"0"),
        "receipt_kind":dict.fromkeys(schema.QUARTERS,"dividend")} for e in entities}
    tax={e["id"]:{"opening_lots":[{"lot_id":f"O{i+1:02d}","origin_index":-8+2*i,
        "last_eligible_index":(0,2,5,8)[i],"ordinary":"0","investment":"0"} for i in range(4)],
        "terms":[{"effective_index":0,"ordinary_cap_bp":10000,"investment_cap_bp":10000,"carry_quarters":4,"cash_tax_lag":2},
                 {"effective_index":6,"ordinary_cap_bp":10000,"investment_cap_bp":10000,"carry_quarters":8,"cash_tax_lag":1}]}
        for e in entities}
    return {"kind":spec.KIND,"case_id":"T01","bridge":{"kind":"associate_bridge_business_spec_v1","case_id":"B05","base":base,"policies":investment},"tax_policies":tax}


def value(result,index,field,identity="E001",layer="economic_exact_values"):
    period=spec.QUARTERS[index] if type(index) is int else index
    return F(result[layer][f"{identity}/{period}/{field}"]["value"])


def test_fifo_uses_origin_then_identifier_not_physical_lot_order():
    data=public();lots=data["tax_policies"]["E001"]["opening_lots"]
    for lot,amount in zip(lots,["40","20","10","0"]):lot["ordinary"]=amount
    lots.reverse();before=deepcopy(data);out=b.solve(data)
    assert data==before
    assert value(out,0,"loss_ordinary_used")==64
    assert value(out,0,"tax_lot_O01_ordinary_used")==40
    assert value(out,0,"tax_lot_O02_ordinary_used")==20
    assert value(out,0,"tax_lot_O03_ordinary_used")==4
    assert value(out,0,"loss_ordinary_close")==6
    assert value(out,0,"current_tax")==0
    assert value(out,1,"loss_ordinary_used")==6
    assert value(out,1,"current_tax")==F("11.6")


def test_expire_before_use_and_last_eligible_quarter_is_inclusive():
    data=public();policy=data["tax_policies"]["E001"]
    policy["opening_lots"][0].update(ordinary="40",last_eligible_index=-1)
    policy["opening_lots"][1].update(ordinary="20",last_eligible_index=0)
    policy["terms"][0]["ordinary_cap_bp"]=5000
    out=b.solve(data)
    assert value(out,0,"loss_ordinary_expired")==40
    assert value(out,0,"loss_ordinary_used")==20
    assert value(out,0,"tax_ordinary_after_losses")==44
    assert value(out,0,"current_tax")==F("8.8")


def test_negative_investment_pool_cannot_reduce_positive_ordinary_tax():
    data=public();p=data["bridge"]["policies"]["E001"]
    p["share_postings"]["2026Q1"]="-10";p["share_postings"]["2026Q2"]="8"
    data["tax_policies"]["E001"]["terms"][0]["investment_cap_bp"]=5000
    out=b.solve(data)
    assert value(out,4,"tax_investment_before_losses")==-10
    assert value(out,4,"tax_investment_after_losses")==0
    assert value(out,4,"loss_investment_created")==10
    assert value(out,4,"tax_lot_C04_investment_used")==0
    assert value(out,4,"current_tax")==F("12.8")
    assert value(out,5,"loss_investment_used")==4
    assert value(out,5,"tax_lot_C04_investment_close")==6
    assert value(out,5,"current_tax")==F("13.6")


def test_ordinary_pool_losses_and_balances_do_not_offset_investment_income():
    data=public({"id":"E001","cash_opex":dict.fromkeys(schema.QUARTERS,"75")})
    data["bridge"]["policies"]["E001"]["share_postings"]["2026Q1"]="100"
    out=b.solve(data)
    assert value(out,4,"tax_ordinary_before_losses")==-1
    assert value(out,4,"loss_ordinary_close")==5
    assert value(out,4,"loss_ordinary_used")==0
    assert value(out,4,"tax_investment_after_losses")==100
    assert value(out,4,"current_tax")==20


def test_birth_carry_locks_expiry_even_after_later_policy_extension():
    data=public();p=data["bridge"]["policies"]["E001"]
    p["share_postings"]["2026Q1"]="-10";p["share_postings"]["2027Q2"]="10"
    out=b.solve(data)
    assert value(out,8,"tax_lot_C04_investment_close")==10
    assert value(out,9,"loss_investment_expired")==10
    assert value(out,9,"loss_investment_used")==0
    assert value(out,9,"tax_lot_C04_investment_close")==0
    assert value(out,9,"current_tax")==F("14.8")


def test_assessed_due_is_locked_when_lag_changes_two_to_one():
    out=b.solve(public())
    assert value(out,6,"cash_tax_paid")==F("12.8")
    assert value(out,7,"cash_tax_paid")==F("25.6")
    assert value(out,7,"tax_payable_close")==F("12.8")


def test_lag_extension_creates_no_payment_quarter_and_preserves_terminal_payable():
    data=public();terms=data["tax_policies"]["E001"]["terms"]
    terms[0]["cash_tax_lag"]=1;terms[1]["cash_tax_lag"]=2
    out=b.solve(data)
    assert value(out,6,"cash_tax_paid")==F("12.8")
    assert value(out,7,"cash_tax_paid")==0
    assert value(out,11,"tax_payable_close")==F("25.6")
    assert value(out,11,"closing_cash")==1640
    assert value(out,11,"net_income")==F("51.2")
    assert value(out,11,"total_assets")==1840
    assert value(out,11,"total_liabilities_equity")==1840


def test_current_cap_changes_without_rewriting_old_loss_expiry():
    data=public();lots=data["tax_policies"]["E001"]["opening_lots"]
    lots[3].update(investment="100",last_eligible_index=11)
    p=data["bridge"]["policies"]["E001"];p["share_postings"]["2026Q2"]="10";p["share_postings"]["2026Q3"]="10"
    terms=data["tax_policies"]["E001"]["terms"];terms[0]["investment_cap_bp"]=3000;terms[1]["investment_cap_bp"]=8000
    out=b.solve(data)
    assert value(out,5,"loss_investment_used")==3
    assert value(out,6,"loss_investment_used")==8


def test_report_money_scale_and_group_tax_sum_without_cross_entity_relief():
    data=public({"id":"E001","cash_opex":dict.fromkeys(schema.QUARTERS,"75")},
                {"id":"E002","money_unit":"GBP_thousands"})
    out=b.solve(data)
    assert value(out,0,"current_tax","E001")==0
    assert value(out,0,"current_tax","E002")==12800
    assert value(out,0,"current_tax","PORTFOLIO")==12800
    assert value(out,0,"tax_payable_close","E002",layer="raw_cell_exact_values")==F("12.8")
    assert value(out,"FY2025","current_tax","E002")==51200
    assert value(out,"FY2025","tax_payable_close","E002")==25600
    assert "E001/FY2025/tax_lot_O01_ordinary_close" not in out["typed_2dp_values"]


def test_all_new_journals_reconcile_and_future_slots_are_zero():
    out=b.solve(public())
    assert out["kind"]==spec.RESULT_KIND
    assert all(v=="0" for name,rows in out["reconciliation_checks"].items() if name.endswith("_residuals") for v in rows.values())
    for pool in spec.POOLS:
        assert value(out,0,f"tax_lot_C11_{pool}_used")==0
        assert value(out,0,f"tax_lot_C11_{pool}_close")==0


@pytest.mark.parametrize("fault",["negative_opening","missing_lot","bad_lag","boolean_cap","missing_terms","wrong_case"])
def test_invalid_terms_or_vintages_fail_before_inventing_fallbacks(fault):
    data=public();policy=data["tax_policies"]["E001"]
    if fault=="negative_opening":policy["opening_lots"][0]["ordinary"]="-1"
    elif fault=="missing_lot":policy["opening_lots"].pop()
    elif fault=="bad_lag":policy["terms"][0]["cash_tax_lag"]=0
    elif fault=="boolean_cap":policy["terms"][0]["ordinary_cap_bp"]=True
    elif fault=="missing_terms":policy["terms"].pop()
    else:data["bridge"]["case_id"]="B01"
    with pytest.raises(ValueError):b.solve(data)


def test_new_b_only_reuses_v1_b_solve_and_reads_no_a_excel_or_service():
    tree=ast.parse(inspect.getsource(b))
    assert all("oracle_a" not in ast.unparse(node) and "openpyxl" not in ast.unparse(node)
        for node in ast.walk(tree) if isinstance(node,(ast.Import,ast.ImportFrom)))
    calls=[node.func.attr for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
        and isinstance(node.func.value,ast.Name) and node.func.value.id=="bridge_b"]
    assert calls==["solve"]


@pytest.mark.parametrize("case_id",spec.CASE_IDS)
def test_complete_fixed_toy_union_agrees_with_independent_decimal_a(case_id):
    from sheets_factory.workbook.tax_vintage_bridge_v2 import oracle_a
    from sheets_factory.workbook.associate_bridge_v1 import spec as bridge_spec
    base=public({"id":"E001"},{"id":"E002","money_unit":"GBP_thousands"})["bridge"]["base"]
    for e in base["entities"]:
        e["associate_results"]={q:"0" if q.startswith("2025") else ("-5" if q.endswith("Q2") else "5") for q in spec.QUARTERS}
    bridge=bridge_spec.build(base,spec.bridge_case(case_id));data=spec.build(bridge,case_id)
    left=oracle_a.solve(data);right=b.solve(data)
    for layer in ("economic_exact_values","raw_cell_exact_values","typed_2dp_values"):
        assert left[layer]==right[layer]
    assert set(right["typed_2dp_values"])==set(dict(spec.points(data)))
