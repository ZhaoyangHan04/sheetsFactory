"""Hand cases for the independent exact-rational crossholding oracle."""
from copy import deepcopy
from fractions import Fraction as F

import pytest

from sheets_factory.workbook.equity_income_group import fraction_oracle as oracle
from sheets_factory.workbook.equity_income_group.spec import ENTITY_METRICS, GROUP_METRICS, build_spec


def hand_spec():
    public = build_spec(entities=2, quarters=3, scenarios=2)
    public["ownership"] = [["0", "0.1"], ["0.2", "0"]]
    for row in public["entities"]:
        row.update(tax_rate="0.25", annual_interest_rate="0", debt="0", opening_cash="1000",
                   opening_ppe="100", opening_investment="100", opening_retained="0",
                   paid_in_capital="1200", opening_loss="0")
    for case in public["scenarios"]:
        case["inputs"] = {
            "E01": [{"revenue": "120", "cash_opex": "10", "depreciation": "10", "capex": "20"},
                    {"revenue": "0", "cash_opex": "110", "depreciation": "10", "capex": "0"},
                    {"revenue": "200", "cash_opex": "10", "depreciation": "10", "capex": "20"}],
            "E02": [{"revenue": "70", "cash_opex": "10", "depreciation": "10", "capex": "20"},
                    {"revenue": "0", "cash_opex": "60", "depreciation": "10", "capex": "0"},
                    {"revenue": "170", "cash_opex": "10", "depreciation": "10", "capex": "20"}],
        }
    return public


def test_two_taxable_entities_have_hand_solved_exact_cycle():
    answer = oracle.solve_simultaneous([100, 50], [[0, F(1, 10)], [F(1, 5), 0]], [F(1, 4)] * 2, [0, 0])
    assert answer["net_income"] == (F(62250, 791), F(39000, 791))
    assert answer["pretax_profit"] == (F(83000, 791), F(52000, 791))
    assert answer["equity_income"] == (F(3900, 791), F(12450, 791))
    assert answer["current_tax"] == (F(20750, 791), F(13000, 791))
    assert answer["closing_loss"] == (0, 0)
    assert answer["solver"]["valid_regime_mask"] == 3


def test_every_regime_is_tested_even_when_the_first_is_valid(monkeypatch):
    original = oracle._solve_linear_system
    calls = []
    def observed(matrix, rhs):
        calls.append((matrix, rhs))
        return original(matrix, rhs)
    monkeypatch.setattr(oracle, "_solve_linear_system", observed)
    answer = oracle.solve_simultaneous([-100, -50], [[0, F(1, 10)], [F(1, 5), 0]], [F(1, 4)] * 2, [0, 0])
    assert len(calls) == 4
    assert [row["mask"] for row in answer["solver"]["regime_checks"]] == [0, 1, 2, 3]
    assert answer["solver"]["valid_regime_mask"] == 0
    assert sum(row["canonical_regime_matches"] for row in answer["solver"]["regime_checks"]) == 1
    assert answer["net_income"] == (-F(750, 7), -F(500, 7))
    assert answer["closing_loss"] == (F(750, 7), F(500, 7))


def test_exact_loss_boundary_is_inactive_including_zero_tax_rate():
    answer = oracle.solve_simultaneous([90, 100], [[0, F(1, 10)], [0, 0]], [F(1, 4), 0], [100, 0])
    assert answer["pretax_profit"] == (100, 100)
    assert answer["net_income"] == (100, 100)
    assert answer["tax_active"] == (False, True)
    assert answer["current_tax"] == (0, 0)
    assert answer["solver"]["valid_regime_mask"] == 2
    assert answer["solver"]["valid_regime_count"] == 1


def test_rate_one_and_asymmetric_ownership_do_not_require_iteration():
    answer = oracle.solve_simultaneous([100, 50], [[0, F(7, 20)], [0, 0]], [1, 0], [10, 0])
    assert answer["net_income"] == (10, 50)
    assert answer["pretax_profit"] == (F(235, 2), 50)
    assert answer["current_tax"] == (F(215, 2), 0)
    assert answer["solver"]["regimes_checked"] == 4


@pytest.mark.parametrize("value,expected", [(F(1, 200), "0.01"), (-F(1, 200), "-0.01"),
    (F(12345, 1000), "12.35"), (-F(12345, 1000), "-12.35"),
    (F(1, 3000), "0.00"), (-F(1, 3000), "-0.00"), (F(99999999999, 100), "999999999.99")])
def test_display_is_exact_half_up_only_at_display_boundary(value, expected):
    assert oracle.display(value) == expected


def test_complete_state_and_management_eliminations_match_hand_first_quarter():
    result = oracle.solve(hand_spec())
    period = result["scenarios"][0]["periods"][0]
    first, second, group = period["entities"]["E01"], period["entities"]["E02"], period["group"]
    assert first["net_income"] == F(62250, 791)
    assert first["closing_cash"] == 990 + F(58350, 791)
    assert first["closing_ppe"] == 110
    assert first["closing_investment"] == 100 + F(3900, 791)
    assert first["closing_retained"] == F(62250, 791)
    assert second["closing_cash"] == 990 + F(26550, 791)
    assert group["external_net_income"] == F(84900, 791)
    assert group["equity_income_elimination"] == -F(16350, 791)
    assert group["investment_elimination"] == -(200 + F(16350, 791))
    assert group["assets"] == 2200 + F(84900, 791)
    assert group["assets"] == group["liabilities_and_capital"]
    assert result["scenarios"][0]["periods"] == result["scenarios"][1]["periods"]
    for case in result["scenarios"]:
        previous = None
        for quarter in case["periods"]:
            assert set(quarter["group"]) == set(GROUP_METRICS)
            assert all(type(v) is F for v in quarter["group"].values())
            for eid, row in quarter["entities"].items():
                assert set(row) == set(ENTITY_METRICS)
                assert all(type(v) is F for v in row.values())
                assert row["balance_residual"] == 0
                if previous:
                    for state in ("cash", "ppe", "investment", "retained", "loss"):
                        assert row["opening_" + state] == previous["entities"][eid]["closing_" + state]
            previous = quarter
    # Exact income fractions persist into the next period; display never feeds state.
    assert result["scenarios"][0]["periods"][1]["entities"]["E01"]["opening_retained"] == F(62250, 791)
    assert result["actual_LO_calls"] == result["model_calls"] == 0
    assert result["qualified"] is False


def test_losses_created_then_used_with_no_inter_entity_tax_sharing():
    public = hand_spec()
    public["ownership"] = [["0", "0"], ["0", "0"]]
    result = oracle.solve(public)
    quarters = result["scenarios"][0]["periods"]
    assert quarters[1]["entities"]["E01"]["closing_loss"] == 120
    assert quarters[1]["entities"]["E02"]["closing_loss"] == 70
    assert quarters[2]["entities"]["E01"]["taxable_profit"] == 60
    assert quarters[2]["entities"]["E02"]["taxable_profit"] == 80
    assert quarters[2]["entities"]["E01"]["current_tax"] == 15
    assert quarters[2]["entities"]["E02"]["current_tax"] == 20


@pytest.mark.parametrize("field", ["cash", "ppe", "investment"])
def test_negative_ending_asset_is_rejected_without_funding_plug(field):
    public = hand_spec()
    public["entities"][0]["opening_" + field] = "0"
    public["entities"][0]["paid_in_capital"] = "200" if field == "cash" else "1100"
    if field == "cash":
        public["scenarios"][0]["inputs"]["E01"][0]["capex"] = "1000"
    elif field == "ppe":
        public["scenarios"][0]["inputs"]["E01"][0]["capex"] = "0"
    else:
        public["scenarios"][0]["inputs"]["E02"][0]["revenue"] = "0"
        public["scenarios"][0]["inputs"]["E02"][0]["cash_opex"] = "100"
    with pytest.raises(ValueError, match="Negative ending"):
        oracle.solve(public)


@pytest.mark.parametrize("args", [([1], [[F(1, 10)]], [0], [0]),
    ([1, 1], [[0, F(9, 25)], [0, 0]], [0, 0], [0, 0]),
    ([1], [[0]], [F(11, 10)], [0]), ([1], [[0]], [0], [-1]),
    ([True], [[0]], [0], [0]), ([1.0], [[0]], [0], [0])])
def test_noncontractual_core_inputs_fail_closed(args):
    with pytest.raises(ValueError):
        oracle.solve_simultaneous(*args)


def test_complete_default_fixture_has_all_regimes_exact_and_scenarios_reset():
    public = build_spec()
    before = deepcopy(public)
    result = oracle.solve(public)
    assert public == before
    assert len(result["scenarios"]) == 3
    assert len(result["scenarios"][0]["periods"]) == 12
    for case in result["scenarios"]:
        assert case["periods"][0]["entities"]["E01"]["opening_cash"] == 25000
        for quarter in case["periods"]:
            assert quarter["solver"]["regimes_checked"] == 64
            assert quarter["solver"]["valid_regime_count"] == 1
            assert all(quarter["group"][field] == 0 for field in
                       ("balance_residual", "profit_reconciliation_residual", "cash_reconciliation_residual"))
