"""Pure independent-business checks; no workbook, engine, model or optimizer."""
from copy import deepcopy
from fractions import Fraction as F
from itertools import combinations

import pytest

from sheets_factory.workbook.operating_metrics_regime import spec, oracle_a, oracle_b, audit


def single(identity="ALDER"):
    public = spec.default_spec()
    public["entities"] = [e for e in public["entities"] if e["id"] == identity]
    return public


def both(public):
    left, right = oracle_a.solve(public), oracle_b.solve(public)
    assert audit.compare_results(public, left, right)["passed"]
    return left["exact_values"], left["display_values"]


def test_complete_default_all_values_and_pairwise_crossed_reports():
    public = spec.default_spec()
    axes = ("layout", "money_unit", "sales_basis")
    for first, second in combinations(axes, 2):
        assert len({(e[first], e[second]) for e in public["entities"]}) == 4
    values, typed = both(public)
    assert len(values) == len(typed) == len(audit.expected_keys(public)) == 2052
    assert [values[f"{name}/FY2027/distribution_eligible"] for name in ("ALDER", "BEACON", "CEDAR", "DELTA")] == [True, False, True, False]
    assert all(F(v) == 0 for e in public["entities"] for v in e["associate_results"][:4])
    assert all(any(F(v) > 0 for v in e["associate_results"][4:]) and any(F(v) < 0 for v in e["associate_results"][4:]) for e in public["entities"])
    assert "already held" in public["public_policy"]["associate"]
    assert not ({"formula", "mask", "target_cells"} & set(public))


def test_associate_sign_is_independently_determined_when_history_is_zero():
    values, _ = both(single())
    assert values["ALDER/2025Q1/net_income"] == F("21.375")
    assert values["ALDER/2025Q1/reported_associate_line"] == 0
    assert values["ALDER/2026Q1/core_net_income"] == F("24.75")
    assert values["ALDER/2026Q1/net_income"] == F("27.75")
    assert values["ALDER/2026Q2/core_net_income"] == 18
    assert values["ALDER/2026Q2/net_income"] == 16
    for period in ("2026Q1", "2026Q2"):
        core = values[f"ALDER/{period}/core_net_income"]
        share = values[f"ALDER/{period}/associate_income"]
        wrong_historical_operator = core - share
        assert values[f"ALDER/{period}/net_income"] - wrong_historical_operator == 2 * share


def test_yoy_qoq_multiple_and_index_have_different_meanings():
    values, typed = both(single())
    prefix = "ALDER/2026Q2/"
    assert values[prefix + "revenue"] == 90
    assert values[prefix + "yoy_percent"] == -10
    assert values[prefix + "qoq_percent"] == F(-200, 11)
    assert values[prefix + "prior_year_multiple"] == F(9, 10)
    assert values[prefix + "prior_year_index"] == 90
    assert typed[prefix + "qoq_percent"]["value"] == "-18.18"
    assert values["ALDER/2025Q1/qoq_percent"] == spec.NA
    assert values["ALDER/2025Q4/yoy_percent"] == spec.NA


def test_cross_year_revenue_bases_are_not_interchangeable():
    values, _ = both(spec.default_spec())
    assert values["BEACON/2026Q1/revenue"] == 255000  # same quarter LY, not Q4.
    assert values["DELTA/2026Q1/revenue"] == 336  # preceding Q4, not Q1 LY.
    assert values["DELTA/2026Q1/yoy_percent"] == F(260, 3)
    assert values["DELTA/2026Q1/qoq_percent"] == 60


def test_exact_cagr_equality_cash_equity_and_non_cash_investment():
    values, typed = both(single())
    assert values["ALDER/FY2027/cagr_percent"] == ("cagr_percent", F(729, 625), 2)
    assert typed["ALDER/FY2027/cagr_percent"] == {"type": "number", "value": "8.00"}
    assert values["ALDER/FY2027/net_income"] == F("114.964")
    assert values["ALDER/FY2027/dividend"] == F("22.9928")
    assert values["ALDER/FY2027/closing_cash"] == F("755.9712")
    assert values["ALDER/FY2027/closing_investment"] == 211
    assert values["ALDER/FY2027/closing_retained_earnings"] == F("366.9712")
    assert values["ALDER/FY2027/total_assets"] == F("966.9712")


def test_gate_uses_unrounded_cagr_endpoint_not_display():
    public = single()
    public["entities"][0]["forecast_sales_assumptions"][4] = "16.639999"
    values, typed = both(public)
    assert typed["ALDER/FY2027/cagr_percent"]["value"] == "8.00"
    assert values["ALDER/FY2027/distribution_eligible"] is False
    assert values["ALDER/FY2027/dividend"] == 0


@pytest.mark.parametrize("last,eligible", [("5", True), ("4.999999", False)])
def test_q4_gate_equality_and_nearby_display_alias(last, eligible):
    public = single()
    public["entities"][0]["forecast_sales_assumptions"][4:] = ["30", "30", "30", last]
    values, typed = both(public)
    assert typed["ALDER/2027Q4/yoy_percent"]["value"] == "5.00"
    assert values["ALDER/FY2027/distribution_eligible"] is eligible


def test_loss_has_no_current_tax_credit_or_distribution_but_can_reduce_equity():
    public = single()
    e = public["entities"][0]
    e["quarterly_fixed_opex"] = ["60"] * 12
    e["associate_results"][8:] = ["-30"] * 4
    values, _ = both(public)
    assert values["ALDER/2025Q1/pretax_before_associate"] < 0
    assert values["ALDER/2025Q1/current_tax"] == 0
    assert values["ALDER/FY2027/net_income"] < 0
    assert values["ALDER/FY2027/distribution_eligible"] is False
    assert values["ALDER/FY2027/dividend"] == 0
    assert values["ALDER/FY2027/closing_investment"] == 84


def test_complete_statement_rollforwards_and_portfolio_unit_conversion():
    public = spec.default_spec()
    values, _ = both(public)
    for e in public["entities"]:
        cash, investment, retained = (F(e["opening"][k]) for k in ("cash", "investment", "retained_earnings"))
        for i in range(12):
            prefix = f'{e["id"]}/{2025+i//4}Q{i%4+1}/'
            assert values[prefix + "closing_cash"] - cash == values[prefix + "operating_cash_flow"] - values[prefix + "dividend"]
            assert values[prefix + "closing_investment"] - investment == values[prefix + "associate_income"]
            assert values[prefix + "closing_retained_earnings"] - retained == values[prefix + "net_income"] - values[prefix + "dividend"]
            assert values[prefix + "total_assets"] == values[prefix + "total_liabilities_equity"]
            cash, investment, retained = (values[prefix + k] for k in ("closing_cash", "closing_investment", "closing_retained_earnings"))
    total = sum(values[f'{e["id"]}/2026Q1/revenue'] * (1000 if e["money_unit"] == "GBP_thousands" else 1) for e in public["entities"])
    assert total == values["PORTFOLIO/2026Q1/revenue"]
    assert values["PORTFOLIO/2026Q1/net_margin_percent"] == 100 * values["PORTFOLIO/2026Q1/net_income"] / total


def test_reported_expense_signs_follow_layout_and_not_money_unit():
    public = spec.default_spec()
    values, _ = both(public)
    for e in public["entities"]:
        sign = 1 if e["layout"] == "expense_columns" else -1
        assert values[f'{e["id"]}/2026Q1/reported_direct_cost'] == sign * values[f'{e["id"]}/2026Q1/direct_cost']
        assert values[f'{e["id"]}/2026Q1/reported_associate_line'] == F(e["associate_results"][4])


@pytest.mark.parametrize("ratio,expected", [(F(121,100),"10.00"),(F(81,100),"-10.00"),(F(2),"41.42"),((1+F(1,20000))**2,"0.01"),((1-F(1,20000))**2,"-0.01")])
def test_independent_cagr_rounding_positive_negative_and_halfway(ratio, expected):
    assert oracle_a.cagr_display(ratio)[0] == oracle_b.cagr_display(ratio)[0] == expected


def test_input_is_immutable_and_default_calls_do_not_share_mutable_values():
    public = spec.default_spec(); before = deepcopy(public)
    both(public)
    assert public == before
    spec.default_spec()["public_policy"]["units"] = "changed"
    assert spec.default_spec() == before


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(unknown=True),
    lambda s: s["entities"][0]["actual_revenue"].__setitem__(0, "0"),
    lambda s: s["entities"][0]["actual_revenue"].__setitem__(0, 1.0),
    lambda s: s["entities"][0]["forecast_sales_assumptions"].__setitem__(0, "-100"),
    lambda s: s["entities"][0]["associate_results"].__setitem__(0, "1"),
    lambda s: s["entities"][0]["opening"].update(cash="1"),
    lambda s: s["public_policy"].update(associate="Unstated acquisition"),
])
def test_ambiguous_or_invalid_public_inputs_fail_closed(mutation):
    public = single(); mutation(public)
    with pytest.raises(ValueError):
        spec.validate_spec(public)


@pytest.mark.parametrize("failure", ["cash", "investment"])
def test_impossible_ending_assets_rejected_by_both_oracles(failure):
    public = single()
    if failure == "cash":
        public["entities"][0]["quarterly_fixed_opex"][0] = "600"
    else:
        public["entities"][0]["associate_results"][4] = "-201"
    for oracle in (oracle_a, oracle_b):
        with pytest.raises(ValueError):
            oracle.solve(public)


@pytest.mark.parametrize("tamper", ["missing", "extra", "value", "proof"])
def test_crosscheck_requires_complete_values_and_root_evidence(tamper):
    public = single(); left=oracle_a.solve(public); right=oracle_b.solve(public)
    key = "ALDER/2026Q1/revenue"
    if tamper == "missing": right["exact_values"].pop(key)
    elif tamper == "extra": right["display_values"]["OTHER/cell"] = {"type":"number","value":"0.00"}
    elif tamper == "value": right["exact_values"][key] += F(1, 10000)
    else: right["cagr_proofs"] = {}
    assert audit.compare_results(public, left, right)["passed"] is False
