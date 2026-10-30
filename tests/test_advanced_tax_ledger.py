"""Independent posted-cent tax vintage and journal tests; no Excel calculator."""

from copy import deepcopy
from decimal import Decimal as D

import pytest

from sheets_factory.workbook.derived_gold.ledger import (
    _AnnualTaxState, _advanced_tax_config, _parameters, simulate,
)


def tax_parameters(**changes):
    values = {
        "advanced_tax_enabled": 1,
        "initial_tax_rate_y1": ".50", "initial_tax_rate_y2": ".30",
        "initial_tax_rate_y3": ".20", "refresh_tax_rate_y1": ".60",
        "refresh_tax_rate_y2": ".30", "refresh_tax_rate_y3": ".10",
        "interest_deduction_ebitda_fraction": ".30", "nol_carryforward_years": 1,
    }
    return {**values, **changes}


def spec(advanced=True):
    result = {"parameters": {
        "cash_ebitda_margin": ".251054975970",
        "annual_equity_discount_rate": ".121103052318",
        "loan_a_annual_rate": ".0609", "loan_b_annual_rate": ".0809",
        "revolver_annual_rate": ".0909",
    }}
    if advanced:
        result["advanced_tax_parameters"] = tax_parameters()
    return result


def state(*, tax_overrides=None, **parameters):
    p = _parameters(spec())
    p.update({"initial_asset_cost": D(0), "refresh_capex": D(0),
              "initial_asset_service_month": 1, "refresh_paid_month": 13,
              "refresh_service_month": 13})
    p.update({key: D(value) if key in {
        "initial_asset_cost", "refresh_capex", "tax_rate", "nol_utilization_cap",
    } else value for key, value in parameters.items()})
    tax = _advanced_tax_config({"advanced_tax_parameters": tax_parameters(**(tax_overrides or {}))}, p)
    return _AnnualTaxState(p, tax)


def close(tax, year, *, ebitda="0", interest="0", book_depreciation="0",
          ppe="0", acquired="0"):
    return tax.close_year(year, ebitda=D(ebitda), cash_interest=D(interest),
                          book_depreciation=D(book_depreciation), book_net_ppe=D(ppe),
                          acquired_cost=D(acquired))


def test_disabled_advanced_tax_preserves_every_existing_output():
    old = spec(False)
    disabled = deepcopy(old)
    disabled["advanced_tax_parameters"] = tax_parameters(advanced_tax_enabled=0)
    assert simulate(disabled) == simulate(old)
    assert "tax_annual" not in simulate(old)
    assert "current_tax" not in simulate(old)["monthly"][0]


@pytest.mark.parametrize("changes", [
    {"initial_tax_rate_y1": ".51"}, {"initial_tax_rate_y1": "-.1"},
    {"refresh_tax_rate_y3": "NaN"}, {"interest_deduction_ebitda_fraction": "1.1"},
    {"advanced_tax_enabled": 2}, {"advanced_tax_enabled": True},
    {"nol_carryforward_years": 0}, {"nol_carryforward_years": "1.5"},
])
def test_advanced_tax_parameters_reject_invalid_contract(changes):
    s = spec()
    s["advanced_tax_parameters"].update(changes)
    with pytest.raises(ValueError):
        simulate(s)


@pytest.mark.parametrize("name", ["opening_nol", "opening_retained"])
def test_advanced_tax_has_no_undisclosed_opening_tax_attributes(name):
    s = spec()
    s["parameters"][name] = "1"
    with pytest.raises(ValueError, match="zero opening NOL and retained"):
        simulate(s)


def test_advanced_tax_requires_exact_complete_parameter_object():
    s = spec()
    del s["advanced_tax_parameters"]["initial_tax_rate_y1"]
    with pytest.raises(ValueError, match="Nine explicit"):
        simulate(s)
    s = spec()
    s["advanced_tax_parameters"]["extra"] = 1
    with pytest.raises(ValueError, match="Nine explicit"):
        simulate(s)


def test_interest_fifo_deducts_oldest_carry_before_current_interest():
    tax = state(tax_overrides={"interest_deduction_ebitda_fraction": ".50"})
    one = close(tax, 1, interest="100")
    two = close(tax, 2, ebitda="100", interest="100")
    three = close(tax, 3, ebitda="200", interest="100")
    assert one["interest_cf_close"] == D("100")
    assert two["interest_v1_used"] == D("50")
    assert two["current_interest_deducted"] == 0
    assert two["interest_v1_close"] == D("50")
    assert two["interest_v2_close"] == D("100")
    assert three["interest_v1_used"] == three["interest_v2_used"] == D("50")
    assert three["current_interest_deducted"] == 0
    assert three["interest_v2_close"] == D("50")
    assert three["interest_v3_close"] == D("100")
    assert three["interest_deduction"] == three["interest_capacity"] == D("100")
    assert all(tax.checks.values())


def test_current_interest_uses_only_capacity_after_carried_interest():
    tax = state(tax_overrides={"interest_deduction_ebitda_fraction": ".50"})
    one = close(tax, 1, ebitda="100", interest="120")
    two = close(tax, 2, ebitda="200", interest="80")
    three = close(tax, 3, ebitda="400", interest="10")
    assert one["interest_cf_close"] == D("70")
    assert one["deferred_tax_expense"] == D("-17.50")
    assert one["book_tax"] == D("-5.00")  # current charge 12.50 less deferred benefit 17.50
    assert two["interest_cf_used"] == D("70")
    assert two["current_interest_deducted"] == D("30")
    assert two["current_interest_carried"] == D("50")
    assert two["deferred_tax_expense"] == D("5.00")
    assert three["interest_deduction"] == D("60")
    assert three["interest_cf_close"] == 0
    assert three["deferred_tax_expense"] == D("12.50")


def test_nol_expires_before_year_three_use_and_writes_off_its_dta():
    tax = state(initial_asset_cost="300", tax_overrides={
        "initial_tax_rate_y1": ".80", "initial_tax_rate_y2": ".10",
        "initial_tax_rate_y3": ".10", "interest_deduction_ebitda_fraction": "0",
    })
    one = close(tax, 1, acquired="300", ppe="300")
    two = close(tax, 2, ebitda="80", acquired="300", ppe="300")
    three = close(tax, 3, ebitda="100", acquired="300", ppe="300")
    assert one["nol_new"] == D("240")
    assert one["nol_v1_open"] == one["nol_v1_used"] == 0
    assert two["nol_use_cap"] == two["nol_v1_used"] == D("40")
    assert two["nol_close"] == D("200")
    assert three["nol_open"] == three["nol_v1_expired"] == D("200")
    assert three["nol_used"] == three["nol_close"] == 0
    assert three["current_tax"] == D("17.50")
    assert three["deferred_tax_expense"] == D("57.50")  # 50 DTA write-off plus 7.50 DTL growth
    assert all(tax.checks.values())


def test_two_year_nol_carry_and_fifo_across_multiple_vintages():
    tax = state(tax_overrides={"nol_carryforward_years": 2})
    one = close(tax, 1, ebitda="-100")
    two = close(tax, 2, ebitda="-50")
    three = close(tax, 3, ebitda="160")
    assert one["nol_new"] == D("100")
    assert two["nol_new"] == D("50")
    assert three["nol_expired"] == 0
    assert three["nol_use_cap"] == D("128")
    assert three["nol_v1_used"] == D("100")
    assert three["nol_v2_used"] == D("28")
    assert three["nol_v2_close"] == D("22")
    assert three["nol_v3_open"] == three["nol_v3_used"] == three["nol_v3_close"] == 0
    assert all(tax.checks.values())


def test_tax_depreciation_is_service_calendar_year_with_final_cent_residual():
    tax = state(initial_asset_cost="0.05", refresh_capex="0.05",
                initial_asset_service_month=12, refresh_paid_month=12, refresh_service_month=13,
                tax_overrides={"initial_tax_rate_y1": ".50", "initial_tax_rate_y2": ".30",
                               "initial_tax_rate_y3": ".20"})
    one = close(tax, 1, acquired=".10")
    two = close(tax, 2, acquired=".10")
    three = close(tax, 3, acquired=".10")
    assert one["initial_tax_depreciation"] == D(".03")  # no December proration
    assert two["initial_tax_depreciation"] == D(".02")
    assert three["initial_tax_depreciation"] == 0  # residual, not another 0.01
    assert one["refresh_tax_depreciation"] == 0
    assert one["tax_basis_close"] == D(".07")  # refresh cost exists before service
    assert two["refresh_tax_depreciation"] == D(".03")
    assert three["refresh_tax_depreciation"] == D(".02")
    assert three["tax_basis_close"] == 0


def test_dta_basis_is_a_separately_rounded_component_without_netting():
    tax = state(initial_asset_cost="100")
    one = close(tax, 1, ebitda="-20", interest="10", acquired="100", ppe="40")
    assert one["tax_basis_close"] == D("50")
    assert one["dta_nol"] == D("17.50")
    assert one["dta_interest"] == D("2.50")
    assert one["dta_basis"] == D("2.50")
    assert one["dta_close"] == D("22.50")
    assert one["dtl_close"] == 0


def test_full_monthly_journal_cash_and_book_tax_reconcile_without_cash_plugs():
    s = spec()
    s["covenant_parameters"] = {
        "covenant_enabled": 1, "covenant_first_test_month": 9,
        "covenant_dscr_threshold": "1.30", "dsra_normal_payment_months": 1,
        "dsra_trap_payment_months": 3,
    }
    result = simulate(s)
    assert len(result["tax_annual"]) == 3
    assert all(value for key, value in result["checks"].items() if key.startswith("tax_"))
    assert result["checks"]["all_balanced"]
    for row in result["monthly"]:
        assert row["assets"] == row["liabilities"] + row["equity"]
        assert row["cfo_direct"] == row["cfo_indirect"]
        assert row["net_income"] == row["ebt"] - row["tax"]
        assert row["tax"] == row["current_tax"] + row["deferred_tax_expense"]
        assert row["nol_close"] == row["nol_open"] - row["nol_expired"] - row["nol_use"] + row["nol_add"]
        assert row["cfads"] == row["cfo_direct"] + row["interest"] - row["capex"]
        if row["period"] % 12:
            assert row["current_tax"] == row["deferred_tax_expense"] == row["nol_expired"] == 0
            assert row["nol_close"] == row["nol_open"]
    for year, annual in enumerate(result["annual"], 1):
        tax = result["tax_annual"][year - 1]
        assert annual["current_tax"] == tax["current_tax"]
        assert annual["tax"] == tax["book_tax"]
        assert annual["interest_cf_close"] == tax["interest_cf_close"]
        assert annual["dta_close"] == tax["dta_close"]
        assert annual["dtl_close"] == tax["dtl_close"]
    assert all(sum(entry["debit_positive_entries"].values()) == 0 for entry in result["journal"])
    deferred_entries = [entry for entry in result["journal"] if entry["label"].startswith("Remeasure")]
    assert deferred_entries
    assert all("cash" not in entry["debit_positive_entries"] for entry in deferred_entries)
    last = result["monthly"][-1]
    valuation = result["valuation"]
    assert valuation["equity_exit"] == (valuation["enterprise_value"] + last["cash_close"] + last["dsra_close"]
                                        - last["loan_a_close"] - last["loan_b_close"] - last["revolver_close"]
                                        - valuation["exit_fee"])
