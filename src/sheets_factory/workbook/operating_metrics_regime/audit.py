"""Complete pure A/B census; this does not certify native workbooks or tasks."""
from __future__ import annotations

from fractions import Fraction

from . import spec


def expected_keys(public):
    spec.validate_spec(public)
    keys = set()
    for identity in [e["id"] for e in public["entities"]] + ["PORTFOLIO"]:
        for index in range(12):
            fields = (*spec.FLOW_FIELDS, *spec.STOCK_FIELDS, *spec.QUARTER_METRICS,
                *(spec.REPORTED_FIELDS if identity != "PORTFOLIO" else ()))
            for field in fields:
                keys.add(f"{identity}/{2025 + index // 4}Q{index % 4 + 1}/{field}")
        for year in spec.YEARS:
            fields = (*spec.FLOW_FIELDS, *spec.STOCK_FIELDS, *spec.ANNUAL_METRICS,
                *(("distribution_eligible",) if identity != "PORTFOLIO" else ()))
            keys.update(f"{identity}/FY{year}/{field}" for field in fields)
    return keys


def _same_value(left, right):
    return type(left) is type(right) and left == right


def compare_results(public, left, right):
    keys = expected_keys(public)
    problems = []
    for label, result in (("A", left), ("B", right)):
        if result.get("kind") != "operating_metrics_regime_oracle_values" or result.get("version") != 1:
            problems.append({"oracle": label, "reason": "unknown_oracle_schema"})
        if result.get("specification_sha256") != spec.canonical_sha256(public):
            problems.append({"oracle": label, "reason": "wrong_specification_binding"})
        for section in ("exact_values", "display_values"):
            present = set(result.get(section, {}))
            if present != keys:
                problems.append({"oracle": label, "section": section,
                    "missing": sorted(keys - present), "extra": sorted(present - keys)})
    for section in ("exact_values", "display_values"):
        for key in sorted(keys & set(left.get(section, {})) & set(right.get(section, {}))):
            if not _same_value(left[section][key], right[section][key]):
                problems.append({"section": section, "key": key, "reason": "independent_values_disagree"})
    for label, result in (("A", left), ("B", right)):
        algebraic = {key for key, value in result.get("exact_values", {}).items() if isinstance(value, tuple)}
        if set(result.get("cagr_proofs", {})) != algebraic:
            problems.append({"oracle": label, "reason": "incomplete_cagr_proof_census"})
        for key, value in result.get("exact_values", {}).items():
            if isinstance(value, tuple):
                if len(value) != 3 or value[0] != "cagr_percent" or type(value[1]) is not Fraction or value[1] <= 0 or value[2] != 2:
                    problems.append({"oracle": label, "key": key, "reason": "unknown_algebraic_value"})
                    continue
                proof = result.get("cagr_proofs", {}).get(key, {})
                try:
                    lower = Fraction(proof["root_lower"])
                    upper = Fraction(proof.get("root_upper", proof.get("root_upper_exclusive")))
                    if not (0 <= lower <= upper and lower * lower <= value[1] <= upper * upper):
                        raise ValueError("Invalid root enclosure")
                except (ValueError, TypeError, KeyError, ZeroDivisionError):
                    problems.append({"oracle": label, "key": key, "reason": "invalid_cagr_root_enclosure"})
            elif type(value) not in (Fraction, bool, str):
                problems.append({"oracle": label, "key": key, "reason": "inexact_or_unknown_value_type"})
    return {"kind": "pure_operating_metrics_regime_independent_crosscheck", "version": 1,
        "passed": not problems, "specification_sha256": spec.canonical_sha256(public),
        "expected_complete_value_count": len(keys), "problems": problems,
        "native_engineering_validated": False, "model_difficulty_measured": False,
        "new_LO_model_optimizer_Harbor_network_calls": 0}


def crosscheck(public):
    from . import oracle_a, oracle_b
    left, right = oracle_a.solve(public), oracle_b.solve(public)
    return compare_results(public, left, right)
