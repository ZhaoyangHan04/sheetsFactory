#!/usr/bin/env python3
"""Cold-build a new synthetic pair and independent expectations; no services."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sheets_factory.workbook import independent_controls_candidate as candidate
from sheets_factory.workbook import independent_controls_oracle as oracle


def expected_targets(targets, ledger):
    lookup = {(r["entity"], r["operating"], r["financing"], r["year"]): r["values"] for r in ledger["rows"]}
    return [{"sheet": t["sheet"], "cell": t["cell"], "expected": {"type": "number", "value": lookup[t["entity"], t["operating"], t["financing"], t["year"]][t["field"]]}} for t in targets]


def prepare(public, output):
    public = candidate.validate(public); output = Path(output).absolute()
    candidate.require(output == output.resolve() and not output.exists(), "Use one fresh absolute research directory")
    output.mkdir(parents=True); private = output / "private"; private.mkdir()
    config_ref = candidate.write_new(private / "assumptions.json", public)
    emitted = candidate.emit(public, private / "formula_gold.xlsx")
    inventory = candidate.write_new(private / "target_inventory.json", {"kind": "independent_controls_financial_target_inventory", "version": 1, "targets": emitted["financial_targets"], "all_crossed_states": emitted["layout"]})
    fm_edits = [{"sheet": t["sheet"], "cell": t["cell"], "before": t["before"], "after": None} for t in emitted["financial_targets"]]
    plans = {}
    for mode, edits in (("FM", fm_edits), ("DBG", emitted["debug_mutations"])):
        plans[mode] = candidate.write_new(private / f"{mode}_plan.json", {"kind": "independent_controls_candidate_view_plan", "version": 1, "mode": mode, "source": emitted["source"], "target_inventory": inventory, "edits": edits, "fault_families": dict(Counter(e.get("family", "financial_family_mask") for e in edits)), "frozen_before_any_actual_engine_or_model": True})
    # Both plans are now frozen. This pure ledger is independently implemented;
    # none of its financial functions or expected values enters the emitter.
    ledgers = {"reference": oracle.compute(deepcopy(public)), "control_coupling_only": oracle.compute(deepcopy(public), couple_controls=True), "bridge_double_count_only": oracle.compute(deepcopy(public), double_count_new_debt=True), "combined_DBG": oracle.compute(deepcopy(public), couple_controls=True, double_count_new_debt=True)}
    ledger_refs = {name: candidate.write_new(private / (name + "_ledger.json"), ledger) for name, ledger in ledgers.items()}
    expectations = {name: expected_targets(emitted["financial_targets"], ledger) for name, ledger in ledgers.items()}
    expected_ref = candidate.write_new(private / "expected_typed_targets.json", {"kind": "independent_controls_candidate_expected_typed_targets", "version": 1, "targets": expectations["reference"], "actual_engine_confirmation": "pending", "formula_caches_populated_from_oracle": False})
    impacts = {}
    for name, rows in expectations.items():
        if name == "reference": continue
        changed = [{"sheet": wanted["sheet"], "cell": wanted["cell"], "expected": wanted["expected"], "counterfactual": actual["expected"]} for wanted, actual in zip(expectations["reference"], rows) if Decimal(wanted["expected"]["value"]) != Decimal(actual["expected"]["value"])]
        impacts[name] = {"pure_business_counterfactual_changed_targets": changed, "count": len(changed), "actual_native_D": "not_measured"}
    candidate.require(impacts["control_coupling_only"]["count"] > 0 and impacts["bridge_double_count_only"]["count"] > 0, "Both proposed fault families must have nonempty independently predicted financial impact")
    impact_ref = candidate.write_new(private / "predicted_fault_impacts.json", {"kind": "independent_controls_predicted_fault_impacts", "version": 1, "impacts": impacts, "predicted_is_not_actual_D": True, "actual_engine_or_model_calls": 0})
    materials = {}
    for mode, edits in (("FM", fm_edits), ("DBG", emitted["debug_mutations"])):
        directory = output / mode; directory.mkdir()
        source = emitted["source"]; original = candidate.reference(source["path"])
        book = candidate.materialize(source["path"], directory / "input.xlsx", edits)
        candidate.require(candidate.reference(source["path"]) == original, "Gold bytes must remain unchanged")
        instruction = directory / "instruction.txt"; instruction.open("x").write(candidate.public_brief(public, mode))
        materials[mode] = {"kind": "uncalculated_independent_controls_candidate_view", "version": 1, "mode": mode, "public_input": book, "public_instruction": candidate.reference(instruction), "private_plan": plans[mode], "private_expected_targets": expected_ref, "qualified": False, "task_actual_validation": "pending"}
        candidate.write_new(private / (mode + "_material.json"), materials[mode])
    prospective = {"kind": "prepared_independent_controls_financial_candidate_pair", "version": 1,
        "public_assumptions": config_ref, "gold": emitted["source"], "target_inventory": inventory,
        "plans": plans, "materials": materials, "independent_ledgers": ledger_refs,
        "expected_typed_targets": expected_ref, "predicted_fault_impacts": impact_ref,
        "dimensions": {"entities": len(public["entities"]), "periods": public["periods"], "operating": len(public["operating"]), "financing": len(public["financing"]), "crossed_states_per_entity": len(public["operating"]) * len(public["financing"]), "financial_output_targets": len(emitted["financial_targets"])},
        "prospective_value_scoring_contract": {"all_listed_numeric_targets_required": True, "blank_is_not_numeric_zero": True, "currency_quantum": "0.01", "formula_text_scoring": False, "counterfactual_crossed_states_are_actual_target_cells": True},
        "transfer_hypothesis": "Independent controls can be incorrectly coupled while diagonal scenario self-checks pass. Coherent mixed-state financial outputs and a debt-bridge fault test the hypothesis; no model result is known.",
        "source_provenance": {"synthetic_from_explicit_assumptions": True, "official_or_legacy_workbooks_used_as_seed": [], "external_financial_kernel_imported": False},
        "no_circular_interest_assumption": True, "formula_gold_and_inputs_uncalculated": True,
        "financial_source_actual_validation": "pending", "actual_full_D_and_five_controls": "pending",
        "hardness_validated": False, "qualified": False, "actual_LO_model_solver_Harbor_network_calls": 0,
        "recipes": candidate.recipes()}
    return candidate.write_new(output / "preparation.json", prospective)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=candidate.CONFIG)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = prepare(candidate.load(args.config), args.output)
    print(json.dumps(result, sort_keys=True)); return result


if __name__ == "__main__": main()
