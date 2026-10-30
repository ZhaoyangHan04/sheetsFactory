"""Independent finite-grid debt sizing proof and real Excel feedback graph."""

from copy import deepcopy
from decimal import Decimal as D, localcontext
import hashlib
import json
from pathlib import Path

import openpyxl
import pytest

from sheets_factory.workbook import formula_references
from sheets_factory.workbook.derived_gold.excel import emit_workbook
from sheets_factory.workbook.derived_gold.ledger import simulate, _unit_annuity_factor
from sheets_factory.workbook.derived_gold.spec import ANCHORS, resolve_spec, cyclic_financing_rule
from sheets_factory.workbook.derived_gold.validate import audit_workbook, ledger_invariants_pass


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def contract(tmp_path):
    recipe = json.loads((ROOT / "config/derived_circular_debt_project_v1.json").read_text())
    book = openpyxl.Workbook()
    book.remove(book.active)
    values = {"revenue": 34124, "ebit": 7040, "da": 1527, "tax_rate": .25,
              "debt_rate": .0509, "equity_rate": .09110305231829893, "growth": .04}
    for key, (sheet, cell, _) in ANCHORS.items():
        if sheet not in book:
            book.create_sheet(sheet)
        book[sheet][cell] = values[key]
    anchor = tmp_path / "test_source_anchor.xlsx"
    book.save(anchor)
    book.close()
    recipe["source"]["local_path"] = str(anchor)
    recipe["source"]["sha256"] = hashlib.sha256(anchor.read_bytes()).hexdigest()
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(recipe))
    return resolve_spec(tmp_path, path), recipe, path


def test_entire_tranche_grid_certifies_one_interior_feasible_fixed_point(contract):
    result = simulate(contract[0])
    sizing = result["debt_sizing"]
    proof = result["cyclic_financing_proof"]
    assert proof["grid_points_checked"] == 14001
    assert proof["fixed_points"] == [D("11129000")]
    assert sizing["sized_principal"] == D("11129000")
    assert sizing["equity_paid_in"] == D("13871000")
    assert sizing["debt_capacity"] == D("11129081.06")
    assert proof["mapping_monotone"] is proof["all_tranches_feasible"] is proof["principal_interior"] is True
    assert proof["projection_full_journal_comparisons"] == 5
    assert all(path[-1] == sizing["sized_principal"] for path in proof["endpoint_paths"])
    assert proof["endpoint_paths"][0][0] == 0
    assert proof["endpoint_paths"][1][0] == D("14000000")
    assert all(left <= right for left, right in zip(proof["endpoint_paths"][0], proof["endpoint_paths"][0][1:]))
    assert all(left >= right for left, right in zip(proof["endpoint_paths"][1], proof["endpoint_paths"][1][1:]))
    assert ledger_invariants_pass(result["checks"])
    assert sum(result["opening_trial_balance"].values()) == 0
    assert all(row["balance_check"] == 0 and row["cfo_direct"] == row["cfo_indirect"] for row in result["monthly"])


def test_selected_financing_has_effective_tax_feedback_not_a_constant_cap(contract):
    result = simulate(contract[0])
    assert result["cyclic_financing_proof"]["adjacent_tranche_year3_cash_tax_response"] == D("19.59")
    assert result["cyclic_financing_proof"]["adjacent_tranche_year3_cfads_response"] == D("19.59")
    assert result["debt_sizing"]["year3_cash_tax"] == D("1027551.25")
    assert result["debt_sizing"]["sized_principal"] < result["debt_sizing"]["bankcap"]


def test_adjacent_multiple_fixed_points_are_rejected_instead_of_chosen(contract):
    spec = deepcopy(contract[0])
    spec["cyclic_financing_parameters"]["target_dscr"] = "2.699779"
    with pytest.raises(ValueError, match="2 fixed points"):
        simulate(spec)


@pytest.mark.parametrize("dscr", ["1", "1000000"])
def test_trivial_bank_cap_or_zero_debt_solutions_are_rejected(contract, dscr):
    spec = deepcopy(contract[0])
    spec["cyclic_financing_parameters"]["target_dscr"] = dscr
    with pytest.raises(ValueError, match="interior"):
        simulate(spec)


def test_tax_free_case_is_not_claimed_to_have_effective_feedback(contract):
    spec = deepcopy(contract[0])
    spec["parameters"]["tax_rate"] = "0"
    with pytest.raises(ValueError, match="effective current-tax/CFADS feedback"):
        simulate(spec)


def test_insufficient_cash_or_revolver_usage_cannot_enter_certified_grid(contract):
    spec = deepcopy(contract[0])
    spec["parameters"].update(opening_cash="1000000", equity_paid_in="6000000")
    with pytest.raises(ValueError, match="(?i)(revolving|funding|nonmonotone)"):
        simulate(spec)


@pytest.mark.parametrize("change", [
    {"enabled": True}, {"enabled": 2}, {"target_dscr": "0"}, {"tranche": "0"},
    {"bankcap": "25000001"}, {"tranche": "1000.001"}, {"tranche": ".01"},
])
def test_independent_ledger_rejects_invalid_cyclic_contract(contract, change):
    spec = deepcopy(contract[0])
    spec["cyclic_financing_parameters"].update(change)
    with pytest.raises(ValueError):
        simulate(spec)


def test_unit_payment_factor_is_unrounded_and_satisfies_nominal_annuity(contract):
    with localcontext() as context:
        context.prec = 60
        rate = D(contract[0]["parameters"]["loan_a_annual_rate"]) / 12
        factor = _unit_annuity_factor(rate, 60)
        balance = D(1)
        for _ in range(60):
            balance = balance * (1 + rate) - factor
        assert abs(balance) < D("1e-55")
        assert factor != factor.quantize(D(".01"))
        assert _unit_annuity_factor(D(0), 60) == D(1) / 60


def test_disabled_opt_in_preserves_complete_existing_model_and_spec(contract, tmp_path):
    _, recipe, path = contract
    disabled = deepcopy(recipe)
    disabled["cyclic_financing_parameters"]["enabled"] = 0
    path.write_text(json.dumps(disabled))
    off = resolve_spec(tmp_path, path)
    del disabled["cyclic_financing_parameters"]
    path.write_text(json.dumps(disabled))
    old = resolve_spec(tmp_path, path)
    assert off == old
    assert simulate(off) == simulate(old)
    a, b = tmp_path / "off.xlsx", tmp_path / "old.xlsx"
    assert emit_workbook(off, a) == emit_workbook(old, b)
    left, right = openpyxl.load_workbook(a), openpyxl.load_workbook(b)
    assert left.sheetnames == right.sheetnames
    for name in left.sheetnames:
        assert [(cell.coordinate, cell.value, cell.number_format) for row in left[name] for cell in row] == [
            (cell.coordinate, cell.value, cell.number_format) for row in right[name] for cell in row]
    left.close()
    right.close()


def test_excel_contains_real_economic_feedback_and_iterative_settings(contract, tmp_path):
    spec = contract[0]
    path = tmp_path / "circular_unrecalculated.xlsx"
    bindings = emit_workbook(spec, path)
    book = openpyxl.load_workbook(path)
    principal = ("Scenario", "B" + str(bindings["parameter_rows"]["loan_a_principal"]))
    assert book[principal[0]][principal[1]].value == "='DebtSizing'!$B$8"
    assert book["Scenario"].cell(bindings["parameter_rows"]["equity_paid_in"], 2).value == "='DebtSizing'!$B$9"
    assert "Cash Flow" in book["DebtSizing"]["B2"].value
    assert "Debt" in book["DebtSizing"]["B2"].value
    assert "Assets" in book["DebtSizing"]["B2"].value
    assert book.calculation.iterate is True
    assert book.calculation.iterateCount == 10000
    assert book.calculation.iterateDelta == 1e-9
    # Find an actual formula-reference path back to the sizing principal.
    pending = [principal]
    seen = set()
    cycle_found = False
    while pending:
        sheet, address = pending.pop()
        if (sheet, address) in seen:
            continue
        seen.add((sheet, address))
        value = book[sheet][address]
        if value.data_type != "f":
            continue
        for dependency in formula_references(value.value, sheet)["references"]:
            target = (dependency["sheet"], dependency["cell"])
            if target == principal and len(seen) > 1:
                cycle_found = True
            if target[0] in book:
                pending.append(target)
    assert cycle_found
    assert len(seen) > 100
    book.close()


def test_every_new_formula_is_independently_bound_without_raw_workbook_qualification(contract, tmp_path):
    spec = contract[0]
    path = tmp_path / "circular_unrecalculated.xlsx"
    bindings = emit_workbook(spec, path)
    result = simulate(spec)
    audit = audit_workbook(path, spec, result, bindings)
    assert audit["all_formula_cells_independently_covered"]
    assert not audit["uncovered_formulas"]
    assert audit["all_ledger_invariants_passed"]
    assert not audit["passed"]  # no actual LO calculation has occurred
    new_cells = {item["address"] for item in audit["cell_checks"] if item["address"].startswith("DebtSizing!")}
    assert new_cells == {"DebtSizing!B" + str(row) for row in range(2, 13)}
    for flag in ("cyclic_financing_unique_fixed_point", "cyclic_financing_endpoint_convergence",
                 "cyclic_financing_grid_feasible", "cyclic_financing_tax_feedback", "cyclic_financing_projection_matches"):
        broken = deepcopy(result["checks"])
        broken[flag] = False
        assert not ledger_invariants_pass(broken)


def test_public_circular_policy_is_short_complete_and_has_no_solution_algorithm(contract):
    rule = cyclic_financing_rule()
    assert len(rule.split()) < 80
    for word in ("CFO", "interest", "DSCR", "unit-annuity", "cents", "tranche", "Equity", "cap"):
        assert word in rule
    assert not any(term in rule.lower() for term in ("iterate", "solver", "fixed point", "11129000"))
    assert contract[0]["public_contract_version"] == 8
    assert contract[0]["status"] == "experimental_seed_not_a_qualified_task"
