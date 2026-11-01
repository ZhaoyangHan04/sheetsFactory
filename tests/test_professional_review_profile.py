"""Check the new review profile without source admission or external calls."""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from sheets_factory.checkers import DiagnosisRunner
from sheets_factory.nodes.construction import prompt


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/pipelines/operating_reports_200_debug_quality_context_v1.yaml"
BASE = ROOT / "config/pipelines/operating_reports_200_debug_quality_v1.yaml"
PROMPT = ROOT / "prompts/diagnosis_professional_review_v1.md"
ENTRY = ROOT / "scripts/run_operating_reports_200_debug_quality.py"


@pytest.fixture
def entry(monkeypatch):
    spec = importlib.util.spec_from_file_location("_professional_profile_test", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def forbidden(*args, **kwargs):
        pytest.fail("This profile test must not start admission or services")

    monkeypatch.setattr(module.pipeline, "boundary", forbidden)
    monkeypatch.setattr(module, "execute_prepared", forbidden)
    monkeypatch.setattr(module.generic.runtime.cohort, "host_runtime_settings",
                        lambda output: {"fixture": "no external health check"})
    return module


def configured(entry, output):
    proofs = [{"workbook": {"sha256": "a" * 64}, "mode": "debugging"}]
    return entry._namespace["configure"](CONFIG, output, proofs)


def test_only_the_prompt_selection_differs_from_the_original_profile():
    base = yaml.safe_load(BASE.read_text())
    selected = yaml.safe_load(CONFIG.read_text())
    expected = deepcopy(base)
    expected["prompt_overrides"]["diagnosis.md"] = PROMPT.name
    assert selected == expected
    assert DiagnosisRunner(ROOT).resolve(selected)["enabled_check_ids"] == [
        f"Q{i:02d}" for i in range(1, 13)
    ]


def test_real_configuration_and_node_loader_select_the_new_prompt(entry, tmp_path):
    config = configured(entry, tmp_path / "normal")
    loaded = prompt(SimpleNamespace(config=config), "diagnosis.md")
    assert loaded == PROMPT.read_text()
    assert config["prompt_overrides"]["diagnosis.md"] == PROMPT.name
    assert entry.pipeline.validate_configuration(config)["image"]["id"].startswith("sha256:")
    assert config["diagnosis"]["reference_evidence_policy"] == "reference_review"
    assert config["diagnosis"]["execution"]["reference_evidence_transport"] == "audited_summary"


def test_actual_recipe_pins_the_selected_prompt_and_rejects_a_changed_pin(entry, tmp_path):
    config = configured(entry, tmp_path / "normal")
    recipes = entry.recipes(config, [])
    expected = hashlib.sha256(PROMPT.read_bytes()).hexdigest()
    assert recipes[str(PROMPT.resolve())] == expected
    assert str(ROOT / "prompts/diagnosis_business.md") not in recipes
    assert entry.reference(CONFIG)["sha256"] == hashlib.sha256(CONFIG.read_bytes()).hexdigest()
    entry.generic.runtime.guard_recipes(recipes)
    changed = {**recipes, str(PROMPT.resolve()): "0" * 64}
    with pytest.raises(ValueError, match="normal quality dependency changed"):
        entry.generic.runtime.guard_recipes(changed)


@pytest.mark.parametrize("change", ["missing_check", "policy", "private_transport", "Harbor", "resources"])
def test_existing_mandatory_gates_still_reject_weakened_configuration(entry, tmp_path, change):
    config = configured(entry, tmp_path / "normal")
    if change == "missing_check":
        config["diagnosis"]["selection"]["exclude"] = ["Q12"]
    elif change == "policy":
        config["diagnosis"]["reference_evidence_policy"] = "independent_public_recovery"
    elif change == "private_transport":
        config["diagnosis"]["execution"]["reference_evidence_transport"] = "complete_inline"
    elif change == "Harbor":
        config["harbor"]["execute_controls"] = False
    else:
        config["agents"]["container_cpus"] = 1
    with pytest.raises(ValueError):
        entry.pipeline.validate_configuration(config)


def test_existing_cli_passes_the_explicit_profile_without_starting_services(entry, monkeypatch, tmp_path):
    observed = []

    @contextmanager
    def monitor(*args, **kwargs):
        yield {}

    def prepare(terminals, output, *, config_path):
        observed.append((terminals, output, config_path))
        return {"fixture": "no source admission"}

    monkeypatch.setattr(entry, "admission_monitor", monitor)
    monkeypatch.setattr(entry, "prepare", prepare)
    terminal = tmp_path / "terminal.json"
    output = tmp_path / "normal"
    assert entry.main(["--actual-terminal", str(terminal), "--output", str(output),
                       "--config", str(CONFIG)]) == 0
    assert observed == [([terminal], output, CONFIG)]
