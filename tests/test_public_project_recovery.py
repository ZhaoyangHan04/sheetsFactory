"""Public-only standalone replay tests; numeric caches are explicit fixtures."""

import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import openpyxl
import pytest

from test_project_task_templates import build_project, _write_fixture_caches
from sheets_factory.workbook.derived_gold.ledger import simulate
from sheets_factory.workbook.derived_gold.public_recovery import compile_public_project_recovery
from sheets_factory.workbook.derived_gold.spec import resolve_spec
from sheets_factory.workbook.derived_gold.validate import audit_workbook


FINANCIAL = {"Operations", "Assets", "Debt", "Tax", "Cash Flow", "Balance Sheet",
             "Equity Value", "Annual Statements", "Covenants", "Tax Vintages"}
PROTECTED = {"Read Me", "Source Inputs", "Scenario", "Calendar"}


def _expected(source):
    spec = resolve_spec(source.parent, source.parent / "scenario.json")
    public = openpyxl.load_workbook(source)
    positions = {cell.value: cell.row for row in public["Scenario"] for cell in row
                 if cell.column == 1 and isinstance(cell.value, str)}
    spec["parameters"] = dict(sorted(spec["parameters"].items(), key=lambda item:
                                      positions["ramp_1" if item[0] == "ramp_factors" else item[0]]))
    public.close()
    # Emitter metadata is used by the test assessor, never by the replay.
    from sheets_factory.workbook.derived_gold.excel import emit_workbook
    bindings_path = source.parent / "assessor_metadata_fixture.xlsx"
    bindings = emit_workbook(spec, bindings_path)
    ledger = simulate(spec)
    checks = audit_workbook(source, spec, ledger, bindings)["cell_checks"]
    return spec, bindings, checks


def _mask_financial(path, checks, *, debugging=False):
    book = openpyxl.load_workbook(path)
    for sheet in FINANCIAL & set(book.sheetnames):
        for row in book[sheet]:
            for cell in row:
                if cell.data_type != "f" or cell.is_date or cell.row == 1:
                    continue
                if sheet == "Equity Value" and cell.row == 15:
                    continue
                if sheet == "Annual Statements" and cell.row in {4, 5}:
                    continue
                cell.value = "=0" if debugging else None
    book.save(path)
    book.close()
    _write_fixture_caches(path, checks)


def _run_public(source, destination_folder):
    destination_folder.mkdir(parents=True)
    public = destination_folder / "input.xlsx"
    shutil.copy2(source, public)
    output = destination_folder / "output.xlsx"
    program = compile_public_project_recovery().replace('"/workspace/input.xlsx"', repr(str(public)))
    program = program.replace('"/workspace/output.xlsx"', repr(str(output)))
    replay = destination_folder / "replay.py"
    replay.write_text(program)
    driver = destination_folder / "driver.py"
    # Audit enforcement allows reading exactly the supplied public XLSX.  It
    # rejects any source anchor, goal, reference workbook or external XLSX read.
    driver.write_text(
        "import json, pathlib, runpy, sys\n"
        "reads=[]\n"
        "allowed=" + repr(str(public)) + "\n"
        "def check(event,args):\n"
        " if event=='open' and isinstance(args[0],str) and args[0].endswith('.xlsx'):\n"
        "  mode=args[1]\n"
        "  if isinstance(mode,str) and mode.startswith('r'):\n"
        "   actual=str(pathlib.Path(args[0]).resolve())\n"
        "   if actual != allowed: raise RuntimeError('Private workbook access: '+actual)\n"
        "   reads.append(actual)\n"
        "sys.addaudithook(check)\n"
        "runpy.run_path(" + repr(str(replay)) + ",run_name='__main__')\n"
        "print(json.dumps(reads))\n")
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run([sys.executable, "-I", str(driver)], cwd=destination_folder,
                            env=environment, capture_output=True, text=True, timeout=30)
    return result, public, output


def test_compiled_program_has_no_numeric_scenario_defaults_or_private_imports():
    program = compile_public_project_recovery()
    tree = ast.parse(program)
    defaults = next(node for node in tree.body if isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Name) and node.target.id == "_DEFAULTS")
    assert all(isinstance(value, ast.Constant) and value.value is None for value in defaults.value.values)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module)
    assert not any(name and ("sheets_factory" in name or "excel" in name) for name in imports)
    assert "emit_workbook" not in program
    assert "goal.xlsx" not in program
    assert "scenario.json" not in program
    assert "30000000" not in program and "20000000" not in program


@pytest.mark.parametrize("version", ["disabled", "v6", "v7"])
@pytest.mark.parametrize("debugging", [False, True])
def test_standalone_public_recovery_restores_every_financial_value(build_project, tmp_path, version, debugging):
    source = build_project(version)
    spec, bindings, checks = _expected(source)
    _mask_financial(source, checks, debugging=debugging)
    protected_before = openpyxl.load_workbook(source)
    before = {name: {cell.coordinate: cell.value for row in protected_before[name] for cell in row}
              for name in PROTECTED}
    protected_before.close()
    result, public, output = _run_public(source, tmp_path / "only_public_replay")
    assert result.returncode == 0, result.stderr
    assert set(json.loads(result.stdout)) == {str(public)}
    assert not (output.parent / "goal.xlsx").exists()
    assert not (output.parent / "scenario.json").exists()
    ledger = simulate(spec)
    assessment = audit_workbook(output, spec, ledger, bindings)
    financial_checks = [item for item in assessment["cell_checks"]
                        if item["address"].rsplit("!", 1)[0] in FINANCIAL and item["kind"] != "date"]
    assert len(financial_checks) > 3000
    assert all(item["passed"] for item in financial_checks), [item for item in financial_checks if not item["passed"]][:4]
    book = openpyxl.load_workbook(output)
    for name, cells in before.items():
        assert {cell.coordinate: cell.value for row in book[name] for cell in row} == cells
    book.close()


def test_recovery_uses_changed_public_economics_and_dynamic_parameter_rows(build_project, tmp_path):
    source = build_project(reorder=True)
    spec, bindings, checks = _expected(source)
    book = openpyxl.load_workbook(source)
    row = next(cell.row for row in book["Scenario"] for cell in row
               if cell.column == 1 and cell.value == "steady_annual_sales")
    book["Scenario"].cell(row, 2, 45000000)
    book.save(source)
    book.close()
    # Update the test assessor from the public assumption, not from outputs.
    expected = deepcopy(spec)
    expected["parameters"]["steady_annual_sales"] = "45000000"
    _mask_financial(source, checks)
    result, _, output = _run_public(source, tmp_path / "changed_economics")
    assert result.returncode == 0, result.stderr
    assessment = audit_workbook(output, expected, simulate(expected), bindings)
    financial = [item for item in assessment["cell_checks"]
                 if item["address"].rsplit("!", 1)[0] in FINANCIAL and item["kind"] != "date"]
    assert all(item["passed"] for item in financial), [item for item in financial if not item["passed"]][:4]


def test_missing_public_assumption_is_not_replaced_by_hidden_defaults(build_project, tmp_path):
    source = build_project()
    _, _, checks = _expected(source)
    book = openpyxl.load_workbook(source)
    row = next(cell.row for row in book["Scenario"] for cell in row
               if cell.column == 1 and cell.value == "steady_annual_sales")
    book["Scenario"].cell(row, 1, "unrecognized input")
    book.save(source)
    book.close()
    _write_fixture_caches(source, checks)
    result, _, output = _run_public(source, tmp_path / "missing_input")
    assert result.returncode != 0
    assert "Missing public project assumption: steady_annual_sales" in result.stderr
    assert not output.exists()


def test_missing_public_business_contract_is_rejected(build_project, tmp_path):
    source = build_project()
    book = openpyxl.load_workbook(source)
    for row in book["Read Me"]:
        for cell in row:
            cell.value = None
    book.save(source)
    book.close()
    result, _, output = _run_public(source, tmp_path / "missing_policy")
    assert result.returncode != 0
    assert "public project business contract is missing" in result.stderr
    assert not output.exists()
