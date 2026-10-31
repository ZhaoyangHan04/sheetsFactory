"""The specialized builder changes definitions, not source qualification gates."""
import ast
import copy
import dis
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/build_specialized_heterogeneous_source.py"
UPSTREAM = ROOT / "scripts/build_heterogeneous_source.py"
loader = importlib.util.spec_from_file_location("specialized_heterogeneous_source_unit", SCRIPT)
builder = importlib.util.module_from_spec(loader)
loader.loader.exec_module(builder)


@pytest.fixture
def output():
    path = ROOT / "outputs/tmp" / ("UNIT-specialized-heterogeneous-source-" + uuid4().hex)
    yield path
    if path.exists():
        shutil.rmtree(path)


def upstream_ast():
    return ast.parse(UPSTREAM.read_bytes())


def function(tree, name):
    return next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)


def test_exact_ast_equivalence_except_the_five_authorized_changes():
    original = upstream_ast()
    changed = builder.specialized_builder_ast(UPSTREAM.read_bytes())
    # Reverse precisely the permitted changes. Equality checks every other AST
    # node, including all mathematical, resource and first-attempt guards.
    for node in changed.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in {"PREPARED_KIND", "SOURCE_KIND"}:
                old = next(n for n in original.body if isinstance(n, ast.Assign)
                           and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name)
                node.value = copy.deepcopy(old.value)
    recipes = function(changed, "recipes")
    extra = recipes.body.pop(-2)
    assert isinstance(extra, ast.AugAssign) and extra.target.id == "paths"
    assert [n.right.value for n in extra.value.elts] == [
        "scripts/build_heterogeneous_source.py",
        "src/sheets_factory/workbook/heterogeneous_contracts/specialized_excel.py",
        "src/sheets_factory/workbook/heterogeneous_contracts/policy_specialization.py",
    ]
    execute = function(changed, "execute_prepared")
    imports = next(n for n in execute.body if isinstance(n, ast.ImportFrom))
    assert [(a.name, a.asname) for a in imports.names] == [
        ("specialized_excel", "excel"), ("ledger", None), ("validate", None)]
    imports.names[0] = ast.alias(name="excel", asname=None)
    kinds = [v for n in ast.walk(execute) if isinstance(n, ast.Dict)
             for k, v in zip(n.keys, n.values) if isinstance(k, ast.Constant) and k.value == "source_kind"]
    assert len(kinds) == 1 and kinds[0].value == "hypothetical_policy_specialized_heterogeneous_contracts_source"
    kinds[0].value = "hypothetical_heterogeneous_contracts_source"
    assert ast.dump(changed, include_attributes=False) == ast.dump(original, include_attributes=False)


def test_upstream_identity_changes_fail_before_transformation():
    source = UPSTREAM.read_bytes()
    assert hashlib.sha256(source).hexdigest() == builder.UPSTREAM_SHA256
    with pytest.raises(ValueError, match="frozen original"):
        builder.specialized_builder_ast(source + b"\n")


def test_actual_execute_bytecode_uses_specialized_excel_and_original_financial_oracles():
    instructions = list(dis.get_instructions(builder.execute_prepared))
    assert [i.argval for i in instructions if i.opname == "IMPORT_FROM"] == [
        "specialized_excel", "ledger", "validate"]
    assert "expected_values" in builder.execute_prepared.__code__.co_names
    assert "audit_workbook" in builder.execute_prepared.__code__.co_names
    assert "compare_typed_caches" in builder.execute_prepared.__code__.co_names


def test_recipe_binds_wrapper_original_builder_and_both_new_components():
    recipe = builder.recipes()
    original = upstream_ast()
    old_recipes = copy.deepcopy(function(original, "recipes"))
    namespace = dict(builder.__dict__, __file__=str(UPSTREAM))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[old_recipes], type_ignores=[])), str(UPSTREAM), "exec"), namespace)
    expected = namespace["recipes"]()
    expected.update({str(p): builder.reference(p)["sha256"] for p in [
        SCRIPT,
        ROOT / "src/sheets_factory/workbook/heterogeneous_contracts/specialized_excel.py",
        ROOT / "src/sheets_factory/workbook/heterogeneous_contracts/policy_specialization.py",
    ]})
    assert len(recipe) == 18 and recipe == expected
    assert recipe[str(UPSTREAM)] == builder.UPSTREAM_SHA256
    assert recipe[str(SCRIPT)] == builder.reference(SCRIPT)["sha256"]


def test_source_namespaces_are_new_but_profile_image_regimes_and_defaults_stay_frozen():
    assert builder.PREPARED_KIND == "prepared_policy_specialized_heterogeneous_contract_source"
    assert builder.SOURCE_KIND == "independently_verified_policy_specialized_heterogeneous_contract_source"
    assert builder.DEFAULT_PROFILE == ROOT / "config/runtime_profiles/entity_group_large_v2.yaml"
    assert len(builder.REQUIRED_REGIMES) == 26
    assert builder.IMAGE["id"] == "sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043"


@pytest.mark.parametrize("loan_type", ["BULLET_MONTHLY", "LEVEL_PRINCIPAL_MONTHLY", "BULLET_QUARTERLY_ACCRUAL"])
def test_tiny_specialized_definitions_pass_the_unchanged_independent_full_math_audit(loan_type):
    # Reuse only the existing three-month raw primitive fixture. The specialized
    # emitter receives no journal, and the independent audit checks every AST.
    fixture_loader = importlib.util.spec_from_file_location(
        "heterogeneous_excel_raw_fixture_for_specialized_builder",
        ROOT / "tests/test_heterogeneous_contract_excel.py")
    fixture = importlib.util.module_from_spec(fixture_loader)
    fixture_loader.loader.exec_module(fixture)
    from openpyxl import Workbook
    from sheets_factory.workbook.heterogeneous_contracts import ledger, specialized_excel, validate
    public = fixture.toy(loan_type=loan_type, tax_policy="CASH_COUPON_QUARTERLY", dscr_policy="QUARTERLY_LAGGED")
    forward = ledger.simulate(public)
    book = Workbook()
    try:
        bindings = specialized_excel.emit_heterogeneous_workbook(book, public)
        builder.validate_public_policy_bindings(bindings, specialized_excel.PUBLIC_NOTES)
        expected = validate.expected_values(public, forward, bindings)
        geometry = builder.geometry(book, bindings, expected, builder.load_runtime_profile(builder.DEFAULT_PROFILE))
        assert len(expected["definitions"]) == len(bindings["arithmetic_bindings"]) == bindings["formula_count"]
        assert len(expected["financial"]) == len(bindings["financial_bindings"]) > 0
        assert geometry["physical_formula_count"] == bindings["formula_count"]
        assert geometry["truncated"] is False
        assert bindings["cached_financial_values_written"] is bindings["independent_ledger_imported"] is False
    finally:
        book.close()


def forbid_execution(monkeypatch):
    from sheets_factory.workbook.heterogeneous_contracts import ledger, specialized_excel
    def forbidden(*_a, **_k):
        pytest.fail("Preparation must not execute finance, emit a workbook or create an engine")
    monkeypatch.setattr(ledger, "simulate", forbidden)
    monkeypatch.setattr(specialized_excel, "emit_heterogeneous_workbook", forbidden)
    monkeypatch.setattr(builder, "ResourceLibreOfficeEngine", forbidden)


def prepare_unit(output, monkeypatch):
    forbid_execution(monkeypatch)
    return builder.prepare(ROOT / "config/heterogeneous_contracts/prototype_v2.json", output, allow_prototype=True)


def test_preparation_and_readonly_validation_are_zero_execution_and_bind_full_recipes(output, monkeypatch):
    record = prepare_unit(output, monkeypatch)
    frozen, public = builder.validate_prepared(record["path"])
    assert frozen["kind"] == builder.PREPARED_KIND
    assert frozen["recipe"] == builder.recipes() and len(frozen["recipe"]) == 18
    assert frozen["scope"] == {"entities": 6, "months": 24, "scenarios": 3}
    assert frozen["required_regimes"] == list(builder.REQUIRED_REGIMES)
    assert frozen["LO_calls"] == frozen["model_calls"] == frozen["task_count"] == 0
    assert frozen["source_workbook_materialized"] is frozen["ledger_execution"] is frozen["qualified"] is False
    assert public["dimension_mode"] == "prototype_6_24_3"
    assert not list(output.rglob("*.xlsx")) and not (output / "source_manifest.json").exists()


def test_reuse_and_implicit_prototype_optin_are_rejected_and_failure_preserved(output, monkeypatch):
    forbid_execution(monkeypatch)
    with pytest.raises(ValueError, match="allow-prototype"):
        builder.prepare(ROOT / "config/heterogeneous_contracts/prototype_v2.json", output)
    failure = builder.read(output / "preparation_failure.json")
    assert failure["LO_calls"] == failure["model_calls"] == failure["task_count"] == 0
    assert failure["qualified"] is False
    with pytest.raises(ValueError, match="fresh"):
        builder.prepare(ROOT / "config/heterogeneous_contracts/prototype_v2.json", output, allow_prototype=True)


@pytest.mark.parametrize("change", ["old_namespace", "recipe", "original_spec", "scope", "regimes", "resource_policy"])
def test_changed_preparation_cannot_run(output, monkeypatch, change):
    record = prepare_unit(output, monkeypatch)
    frozen = builder.read(record)
    if change == "old_namespace":
        frozen["kind"] = "prepared_heterogeneous_contract_source"
    elif change == "recipe":
        frozen["recipe"].pop(str(UPSTREAM))
        frozen["recipe_sha256"] = builder.canonical(frozen["recipe"])
    elif change == "original_spec":
        frozen["original_specification"]["sha256"] = "0" * 64
    elif change == "scope":
        frozen["scope"]["entities"] -= 1
    elif change == "regimes":
        frozen["required_regimes"].pop()
    elif change == "resource_policy":
        frozen["runtime_profile_value"]["docker_resources"]["source"]["memory_bytes"] = 8 * 1024**3
    # Only a UNIT fixture is changed. Original source/specification files stay untouched.
    Path(record["path"]).write_text(json.dumps(frozen), encoding="utf-8")
    with pytest.raises(ValueError):
        builder.validate_prepared(output)


def test_execution_failure_preserves_first_attempt_and_releases_lease_before_any_engine(output, monkeypatch):
    prepare_unit(output, monkeypatch)
    from sheets_factory.workbook.heterogeneous_contracts import ledger
    def fail(_):
        raise RuntimeError("UNIT stops before independent finance; no source calculation")
    monkeypatch.setattr(ledger, "simulate", fail)
    with pytest.raises(RuntimeError, match="UNIT stops"):
        builder.execute_prepared(output)
    marker = builder.reference(output / "execution_started.json")
    terminals = list(output.glob("private/attempts/*/terminal.json"))
    assert len(terminals) == 1
    terminal = builder.read(terminals[0])
    assert terminal["status"] == "failed" and terminal["all_partial_artifacts_preserved"] is True
    assert terminal["engine_calls"] == [] and terminal["model_calls"] == terminal["task_count"] == 0
    assert builder.read(output / "producer.lock")["status"] == "released"
    assert not list(output.rglob("*.xlsx")) and not (output / "source_manifest.json").exists()
    with pytest.raises(ValueError, match="already started"):
        builder.execute_prepared(output)
    assert builder.reference(output / "execution_started.json") == marker
    assert list(output.glob("private/attempts/*/terminal.json")) == terminals


@pytest.mark.parametrize("run", [False, True])
def test_cli_prepares_only_by_default_and_executes_only_with_explicit_run(output, monkeypatch, run):
    calls = []
    monkeypatch.setattr(builder, "prepare", lambda *a, **k: calls.append(("prepare", a, k)) or {"UNIT": "prepared"})
    monkeypatch.setattr(builder, "execute_prepared", lambda *a, **k: calls.append(("execute", a, k)) or {"UNIT": "executed"})
    arguments = ["--spec", "UNIT.json", "--output", str(output), "--allow-prototype"]
    builder.main(arguments + (["--run"] if run else []))
    assert [c[0] for c in calls] == (["prepare", "execute"] if run else ["prepare"])


def test_prepared_cli_without_run_only_validates_and_cannot_override_options(output, monkeypatch):
    calls = []
    monkeypatch.setattr(builder, "validate_prepared", lambda p: calls.append(p))
    monkeypatch.setattr(builder, "execute_prepared", lambda *_a, **_k: pytest.fail("Readonly CLI executed a source"))
    result = builder.main(["--prepared", str(output)])
    assert calls == [output] and result["LO_calls"] == result["model_calls"] == 0
    with pytest.raises(ValueError, match="frozen options"):
        builder.main(["--prepared", str(output), "--spec", "different.json"])
