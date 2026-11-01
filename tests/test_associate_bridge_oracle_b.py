"""Exact hand-ledger checks for the independently implemented bridge B."""
from copy import deepcopy
from fractions import Fraction as F
import ast
import inspect

import pytest

from sheets_factory.workbook.associate_bridge_v1 import oracle_b as b
from sheets_factory.workbook.operating_reports_200 import schema, oracle_b as old_b


def entity(identity="E001", **changes):
    item = {"id": identity, "name": "Hypothetical bridge example", "division": "Advisory",
        "layout": "quarter_columns", "line_order": "statement_first", "money_unit": "GBP",
        "rate_unit": "percent_units", "statement_sign": "positive_deductions",
        "forecast_reference": "same_quarter_last_year",
        "driver_form_by_year": {"2026": "change_rate", "2027": "change_rate"},
        "opening": {"cash": "1000", "investment": "200", "debt": "100", "capital": "1000", "retained_earnings": "100"},
        "actual_sales": dict.fromkeys(schema.QUARTERS[:4], "100"),
        "forecast_sales": dict.fromkeys(schema.QUARTERS[4:], "0"), "direct_cost_rate": "25",
        "cash_opex": dict.fromkeys(schema.QUARTERS, "10"), "annual_interest_rate": "4", "parent_tax_rate": "20",
        "associate_results": dict.fromkeys(schema.QUARTERS, "0")}
    item.update(changes)
    return item


def public(*entities):
    members = list(entities or [entity()])
    base = {"kind": schema.KIND, "version": 1, "dimension_mode": "toy", "seed": schema.SEED,
        "years": list(schema.YEARS), "base_currency": "GBP",
        "provenance": "new hypothetical service businesses; no official workbook seed",
        "public_policy": "Hypothetical contractual reporting and distribution assumptions.",
        "distribution": {"year": 2027, "profit_percent": "20", "cagr_percent": "8", "q4_yoy_percent": "5"},
        "divisions": list(dict.fromkeys(e["division"] for e in members)), "entities": members}
    policies = {e["id"]: {"method": "equity", "tax_class": "exempt", "feed_scale": 1,
        "direction_by_year": dict.fromkeys(("2025", "2026", "2027"), "income_positive"),
        "share_postings": dict.fromkeys(schema.QUARTERS, "0"),
        "cash_receipts": dict.fromkeys(schema.QUARTERS, "0"),
        "receipt_kind": dict.fromkeys(schema.QUARTERS, "dividend")} for e in members}
    return {"kind": "associate_bridge_business_spec_v1", "case_id": "B01", "base": base, "policies": policies}


def exact(result, period, field, identity="E001", layer="economic_exact_values"):
    return F(result[layer][f"{identity}/{period}/{field}"]["value"])


def event(data, *, method="equity", tax="exempt", posting="10", receipt="3", kind="dividend", quarter="2026Q1"):
    policy = data["policies"]["E001"]
    policy.update(method=method, tax_class=tax)
    policy["share_postings"][quarter] = posting
    policy["cash_receipts"][quarter] = receipt
    policy["receipt_kind"][quarter] = kind
    return data


def test_equity_receipt_is_not_double_counted_and_closing_journal_reconciles():
    data = event(public()); before = deepcopy(data); out = b.solve(data)
    assert data == before
    expected = {"pretax_before_associate": 64, "current_tax": F("12.8"),
        "core_net_income": F("51.2"), "associate_income": 10, "net_income": F("61.2"),
        "operating_cash_flow": F("54.2"), "closing_cash": 1259,
        "closing_investment": 207, "closing_retained_earnings": 366,
        "total_assets": 1466, "total_liabilities_equity": 1466}
    for field, value in expected.items():
        assert exact(out, "2026Q1", field) == value
    assert out["kind"] == "associate_bridge_values_v1"
    assert out["specification_sha256"] == schema.canonical_sha256(data)
    assert out["reconciliation_checks"]["passed"]
    assert all(v == "0" for k, rows in out["reconciliation_checks"].items()
               if k.endswith("_residuals") for v in rows.values())


@pytest.mark.parametrize("method,tax,expected_tax,recognized", [
    ("equity", "exempt", "12.8", "10"), ("equity", "recognized", "14.8", "10"),
    ("equity", "cash_dividends", "13.4", "10"), ("cost", "exempt", "12.8", "3"),
    ("cost", "recognized", "13.4", "3"), ("cost", "cash_dividends", "13.4", "3")])
def test_all_method_and_tax_classes_have_independent_hand_tax_base(method,tax,expected_tax,recognized):
    out = b.solve(event(public(), method=method, tax=tax))
    assert exact(out,"2026Q1","current_tax") == F(expected_tax)
    assert exact(out,"2026Q1","associate_income") == F(recognized)
    assert exact(out,"2026Q1","net_income") == 64-F(expected_tax)+F(recognized)
    assert exact(out,"2026Q1","operating_cash_flow") == 67-F(expected_tax)
    assert exact(out,"2026Q1","closing_investment") == (207 if method == "equity" else 200)


@pytest.mark.parametrize("method,recognized,investment", [("equity",10,207),("cost",0,197)])
def test_capital_return_is_cash_and_investment_recovery_not_cost_income(method,recognized,investment):
    out = b.solve(event(public(),method=method,tax="cash_dividends",kind="capital_return"))
    assert exact(out,"2026Q1","current_tax") == F("12.8")
    assert exact(out,"2026Q1","associate_income") == recognized
    assert exact(out,"2026Q1","closing_investment") == investment
    assert exact(out,"2026Q1","operating_cash_flow") == F("54.2")
    assert exact(out,"2026Q1","net_income") == F("51.2")+recognized


def test_feed_direction_scale_and_local_receipts_decode_through_distinct_units():
    data = event(public(entity(money_unit="GBP_thousands")),posting="-0.01",receipt="3")
    policy = data["policies"]["E001"]
    policy["feed_scale"] = 1000000
    policy["direction_by_year"]["2026"] = "charge_credit"
    policy["share_postings"]["2027Q1"] = "-0.01"
    out = b.solve(data)
    assert exact(out,"2026Q1","associate_income") == 10000
    assert exact(out,"2026Q1","associate_income",layer="raw_cell_exact_values") == 10
    assert exact(out,"2026Q1","operating_cash_flow",layer="raw_cell_exact_values") == F("54.2")
    assert exact(out,"2026Q1","closing_investment",layer="raw_cell_exact_values") == 207
    assert exact(out,"2027Q1","associate_income") == -10000


def test_recognized_losses_reduce_tax_base_but_never_create_a_tax_credit():
    out = b.solve(event(public(),tax="recognized",posting="-100",receipt="0"))
    assert exact(out,"2026Q1","current_tax") == 0
    assert exact(out,"2026Q1","net_income") == -36
    assert exact(out,"2026Q1","operating_cash_flow") == 64


def test_cost_method_does_not_recognize_even_large_share_postings():
    out = b.solve(event(public(),method="cost",tax="recognized",posting="999999",receipt="3"))
    assert exact(out,"2026Q1","associate_income") == 3
    assert exact(out,"2026Q1","closing_investment") == 200
    assert exact(out,"2026Q1","current_tax") == F("13.4")


def test_annual_totals_closing_balances_and_weighted_group_margin():
    data = public(entity(),entity("E002",money_unit="GBP_thousands"))
    event(data)
    data["policies"]["E002"]["method"] = "cost"
    data["policies"]["E002"]["cash_receipts"]["2026Q1"] = "2"
    out = b.solve(data)
    assert exact(out,"FY2026","net_income") == F("214.8")
    assert exact(out,"FY2026","closing_cash") == exact(out,"2026Q4","closing_cash")
    income = F("61.2")+F("53200")
    assert exact(out,"2026Q1","net_income","PORTFOLIO") == income
    assert exact(out,"2026Q1","net_margin_percent","PORTFOLIO") == income*100/100100
    assert exact(out,"2026Q1","net_income","DIV_ADVISORY") == income
    assert out["typed_2dp_values"]["PORTFOLIO/FY2027/distribution_eligible"] == {"type":"text","value":schema.GROUP_NA}


def test_owner_distribution_uses_new_recognized_annual_profit_and_cash_bridge():
    e=entity(direct_cost_rate="0",parent_tax_rate="0",annual_interest_rate="0",
        cash_opex=dict.fromkeys(schema.QUARTERS,"0"),forecast_sales=dict.fromkeys(schema.QUARTERS[4:],"8"))
    data=event(public(e),posting="10",receipt="3",quarter="2027Q4")
    out=b.solve(data)
    income=F(11664,25)+10
    assert exact(out,"FY2027","net_income")==income
    assert exact(out,"2027Q4","dividend")==income/5
    assert out["typed_2dp_values"]["E001/FY2027/distribution_eligible"]=={"type":"boolean","value":True}
    assert exact(out,"FY2027","closing_cash")==1000+400+432+F(11664,25)+3-income/5
    assert exact(out,"FY2027","closing_investment")==207


def test_tax_report_sign_does_not_reverse_economic_associate_income():
    out=b.solve(event(public(entity(statement_sign="signed_contributions")),tax="recognized"))
    assert exact(out,"2026Q1","reported_current_tax")==F("-14.8")
    assert exact(out,"2026Q1","reported_associate_line")==10
    assert exact(out,"2025Q1","reported_associate_line")==0


def test_unchanged_revenue_growth_cagr_and_complete_inventory_match_original_b():
    data=event(public());original=old_b.solve(data["base"]);out=b.solve(data)
    assert set(out["economic_exact_values"])==set(dict(schema.points(data["base"])))
    assert out["cagr_proofs"]==original["cagr_proofs"]
    unchanged=("revenue","yoy_percent","qoq_percent","prior_year_multiple","prior_year_index",
               "yoy_sales_delta","qoq_sales_delta","annual_sales_delta","cagr_percent")
    for key in out["economic_exact_values"]:
        if key.split("/")[-1] in unchanged:
            for layer in ("economic_exact_values","raw_cell_exact_values","typed_2dp_values"):
                assert out[layer][key]==original[layer][key]


@pytest.mark.parametrize("fault",["negative_receipt","historical_posting","historical_cash","missing_quarter","unknown_tax","bad_scale","missing_entity","negative_investment"])
def test_invalid_bridge_inputs_fail_without_inventing_business_assumptions(fault):
    data=public();policy=data["policies"]["E001"]
    if fault=="negative_receipt":policy["cash_receipts"]["2026Q1"]="-1"
    elif fault=="historical_posting":policy["share_postings"]["2025Q1"]="1"
    elif fault=="historical_cash":policy["cash_receipts"]["2025Q1"]="1"
    elif fault=="missing_quarter":policy["share_postings"].pop("2026Q1")
    elif fault=="unknown_tax":policy["tax_class"]="tax_credit"
    elif fault=="bad_scale":policy["feed_scale"]=True
    elif fault=="missing_entity":data["policies"].clear()
    else:policy["cash_receipts"]["2026Q1"]="201"
    with pytest.raises(ValueError):b.solve(data)


def test_bridge_implementation_reads_no_oracle_a_workbook_or_service():
    tree=ast.parse(inspect.getsource(b))
    imports=[node for node in ast.walk(tree) if isinstance(node,(ast.Import,ast.ImportFrom))]
    assert all("oracle_a" not in ast.unparse(node) and "openpyxl" not in ast.unparse(node) for node in imports)
    operating_calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call)
        and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name)
        and node.func.value.id=="operating_b"]
    assert [node.func.attr for node in operating_calls]==["solve"]


def fixed_case_base():
    associates={q:"0" if q.startswith("2025") else "5" for q in schema.QUARTERS}
    members=[entity(associate_results=associates),
        entity("E002",money_unit="GBP_thousands",rate_unit="basis_points",
               direct_cost_rate="2500",parent_tax_rate="2000",annual_interest_rate="400",
               statement_sign="signed_contributions",associate_results=associates),
        entity("E003",money_unit="GBP_millions",rate_unit="fraction",
               direct_cost_rate="0.25",parent_tax_rate="0.2",annual_interest_rate="0.04",
               associate_results=associates)]
    return public(*members)["base"]


@pytest.mark.parametrize("case_id",[f"B{i:02d}" for i in range(1,9)])
def test_all_fixed_toy_cases_keep_complete_union_and_independent_zero_bridges(case_id):
    from sheets_factory.workbook.associate_bridge_v1 import spec
    data=spec.build(fixed_case_base(),case_id);before=deepcopy(data)
    out=b.solve(data)
    assert data==before
    assert set(out["typed_2dp_values"])==set(dict(schema.points(data["base"])))
    assert all(value=="0" for name,rows in out["reconciliation_checks"].items()
               if name.endswith("_residuals") for value in rows.values())
    assert out["specification_sha256"]==spec.canonical_sha256(data)


@pytest.mark.parametrize("case_id",[f"B{i:02d}" for i in range(1,9)])
def test_full_union_matches_independently_implemented_oracle_a_on_fixed_toys(case_id):
    from sheets_factory.workbook.associate_bridge_v1 import spec,oracle_a
    data=spec.build(fixed_case_base(),case_id)
    expected=oracle_a.solve(data);actual=b.solve(data)
    assert expected["specification_sha256"]==actual["specification_sha256"]
    for layer in ("economic_exact_values","raw_cell_exact_values","typed_2dp_values"):
        assert actual[layer]==expected[layer]
