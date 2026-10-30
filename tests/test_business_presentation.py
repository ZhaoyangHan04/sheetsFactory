"""A short public business brief changes text, never model economics."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import openpyxl
import pytest

from sheets_factory.workbook.derived_gold.excel import emit_workbook
from sheets_factory.workbook.derived_gold.ledger import simulate
from sheets_factory.workbook.derived_gold.presentation import apply_public_presentation, project_business_brief
from sheets_factory.workbook.derived_gold.spec import ANCHORS, resolve_spec

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def financial_spec(tmp_path):
    config = json.loads((ROOT / "config/derived_advanced_tax_project_v1.json").read_text())
    values = {"revenue": 34124, "ebit": 7040, "da": 1527, "tax_rate": .25,
              "debt_rate": .0509, "equity_rate": .09110305231829893, "growth": .04}
    book = openpyxl.Workbook()
    book.remove(book.active)
    for key, (sheet, cell, _) in ANCHORS.items():
        if sheet not in book:
            book.create_sheet(sheet)
        book[sheet][cell] = values[key]
    source = tmp_path / "explicit_public_anchor_fixture.xlsx"
    book.save(source)
    config["source"]["local_path"] = str(source)
    config["source"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(config))
    return resolve_spec(tmp_path, path)


def test_projection_is_deterministic_bounded_and_has_no_hidden_full_contract(financial_spec):
    original = deepcopy(financial_spec)
    projected = project_business_brief(financial_spec)
    assert projected == project_business_brief(financial_spec)
    assert financial_spec == original
    assert projected["presentation_style"] == "business_brief"
    assert 400 <= len(" ".join(projected["public_rules"]).split()) <= 600
    # Removing the sole intentional metadata/text differences recovers the
    # exact original spec. No second, hidden copy of full procedural rules.
    stripped = deepcopy(projected)
    stripped.pop("presentation_style")
    stripped["public_rules"] = original["public_rules"]
    assert stripped == original
    for rule in original["public_rules"]:
        assert rule not in json.dumps(projected)
    words = " ".join(projected["public_rules"])
    for forbidden in ("row 7", "rows 63", "Apply this exact priority", "(1)", "(2)",
                      "nol_v", "interest_v", "test_passed", "current_interest_deducted"):
        assert forbidden not in words


def test_brief_retains_custom_business_policy_without_formula_recipe(financial_spec):
    text = " ".join(project_business_brief(financial_spec)["public_rules"]).lower()
    for policy in ("half up", "actual calendar days", "closing less opening", "fixed cent-rounded",
                   "without cumulative-rounding redistribution", "original cent-rounded ordinary-annuity",
                   "fees apply to ev", "unrounded discounted-flow sum", "annualize periodic monthly irr",
                   "two consecutive passes cure", "non-tests carry state", "without payoff resets",
                   "before optional repayment", "closing lock", "support capped", "fully funded",
                   "sweep remains allowed while locked", "reserve once at par", "without january expiry",
                   "without first-year proration", "third service year exhausts", "oldest carry first",
                   "expire nol", "fifo", "creation-year closing vintage", "future vintages are zero",
                   "without allowance or netting", "separately cent-rounded", "dtl change less dta change",
                   "cash cfo deducts current tax only", "indirect cfo adds deferred expense back",
                   "no additional owner-sale adjustment"):
        assert policy in text
    assert "no deferred taxes" not in text


def test_projection_preserves_every_financial_cell_formula_and_independent_ledger(financial_spec, tmp_path):
    projected = project_business_brief(financial_spec)
    full_path, brief_path = tmp_path / "full.xlsx", tmp_path / "brief.xlsx"
    full_bindings = emit_workbook(financial_spec, full_path)
    brief_bindings = emit_workbook(projected, brief_path)
    assert full_bindings == brief_bindings
    full = openpyxl.load_workbook(full_path, data_only=False)
    brief = openpyxl.load_workbook(brief_path, data_only=False)
    assert full.sheetnames == brief.sheetnames
    for ws in full:
        if ws.title == "Read Me":
            continue  # Only instruction text and its paragraph numbers change.
        cells = {c.coordinate: (c.value, c.data_type, c.number_format) for c in ws._cells.values()}
        other = {c.coordinate: (c.value, c.data_type, c.number_format) for c in brief[ws.title]._cells.values()}
        assert cells == other, ws.title
    full.close()
    brief.close()
    assert simulate(financial_spec) == simulate(projected)


def test_absent_full_and_unknown_style_behaviors(financial_spec):
    assert apply_public_presentation(financial_spec) is financial_spec
    assert apply_public_presentation(financial_spec, "full") is financial_spec
    with pytest.raises(ValueError, match="Unknown public presentation"):
        apply_public_presentation(financial_spec, "short_but_unspecified")


def test_simple_tax_and_disabled_options_have_matching_business_policy(financial_spec):
    spec = deepcopy(financial_spec)
    spec["advanced_tax_parameters"]["advanced_tax_enabled"] = 0
    spec["covenant_parameters"]["covenant_enabled"] = 0
    result = project_business_brief(spec)
    text = " ".join(result["public_rules"])
    assert "NOL does not expire" in text
    assert "there are no deferred taxes" in text
    assert "Quarter-end tests" not in text
    assert "Recognize gross DTA" not in text
    assert len(text.split()) <= 600


@pytest.mark.parametrize("config_name", ["derived_advanced_tax_brief_v1.json", "derived_covenant_brief_v1.json"])
def test_opt_in_configs_declare_only_actual_presentation_style(config_name):
    config = json.loads((ROOT / "config" / config_name).read_text())
    assert config["public_presentation"] == "business_brief"
    assert not any(key in config for key in ("user_request", "conversation", "instruction_origin"))


def test_builder_applies_configured_projection_before_financial_paths(tmp_path, monkeypatch):
    module_spec = importlib.util.spec_from_file_location("brief_builder_test", ROOT / "scripts/build_derived_gold.py")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"public_presentation": "business_brief"}))
    seed = {"parameters": {}, "public_rules": ["A longer procedural rule"]}
    monkeypatch.setattr(module, "resolve_spec", lambda *args: seed)
    class StopAfterObservedSpec(Exception):
        pass
    def observe(spec):
        assert spec["presentation_style"] == "business_brief"
        assert spec["public_rules"] != seed["public_rules"]
        assert "A longer procedural rule" not in json.dumps(spec)
        raise StopAfterObservedSpec
    monkeypatch.setattr(module, "simulate", observe)
    with pytest.raises(StopAfterObservedSpec):
        module.build(tmp_path, config, tmp_path / "not_created")
    assert not (tmp_path / "not_created").exists()
