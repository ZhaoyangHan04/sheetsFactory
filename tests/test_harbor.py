from datetime import date, datetime
import json
import shutil
import tomllib

from openpyxl import Workbook, load_workbook
import pytest

from sheets_factory.evaluation.harbor import export_harbor
from sheets_factory.evaluation.standalone_verifier import compare_files, normalize


def write(path, target):
    workbook = Workbook()
    workbook.active.title = "Model"
    workbook.active["A1"] = 10
    workbook.active["B1"] = target
    hidden = workbook.create_sheet("Hidden")
    hidden.sheet_state = "hidden"
    hidden["A1"] = "protected"
    workbook.save(path)


def test_value_comparison_checks_exact_delta_and_hidden_changes(tmp_path):
    baseline, goal, output = [tmp_path / f"{n}.xlsx" for n in ("input", "goal", "output")]
    write(baseline, None)
    write(goal, 20)
    shutil.copyfile(goal, output)
    assert compare_files(baseline, goal, output)["reward"] == 1
    assert compare_files(baseline, goal, baseline)["reward"] == 0
    book = load_workbook(output)
    book["Hidden"]["Z90"] = 99
    book.save(output)
    result = compare_files(baseline, goal, output)
    assert result["reward"] == 0
    assert "Hidden!Z90" in result["extra_changes"]


def test_added_sheet_and_wrong_target_fail(tmp_path):
    paths = [tmp_path / f"{name}.xlsx" for name in ("i", "g", "o")]
    write(paths[0], 0)
    write(paths[1], 20)
    write(paths[2], 21)
    assert compare_files(*paths)["wrong_values"] == ["Model!B1"]
    workbook = load_workbook(paths[2])
    workbook.create_sheet("Unexpected")
    workbook.save(paths[2])
    assert compare_files(*paths)["reason"] == "sheet_structure_mismatch"


def test_same_value_format_change_does_not_redefine_expected_type(tmp_path):
    baseline, goal, output = [tmp_path / f"{name}.xlsx" for name in ("i", "g", "o")]
    write(baseline, 0)
    write(goal, 45000)
    shutil.copyfile(goal, output)
    workbook = load_workbook(output)
    workbook["Model"]["B1"].number_format = "yyyy-mm-dd"
    workbook.save(output)
    assert compare_files(baseline, goal, output)["reward"] == 1


def test_normalization_keeps_types_and_numeric_strings():
    assert normalize(True) != normalize(1)
    assert normalize("001") != normalize(1)
    assert normalize(None) == normalize("")
    assert normalize(1.005) == ("number", "1.01")
    assert normalize(-1.005) == ("number", "-1.01")
    assert normalize(date(2024, 1, 1)) == normalize(datetime(2024, 1, 1))
    with pytest.raises(ValueError):
        normalize(float("nan"))


def test_export_preserves_private_boundary_and_loads_real_harbor_schema(tmp_path):
    task = tmp_path / "source"
    (task / "public").mkdir(parents=True)
    (task / "private").mkdir()
    write(task / "public/input.xlsx", None)
    write(task / "private/goal.xlsx", 20)
    (task / "public/instruction.md").write_text("Restore projected revenue using the public workbook rules.")
    target = export_harbor(task, tmp_path / "export", {"task_id": "fixture-1", "mode": "financial_modeling"})
    config = tomllib.loads((target / "task.toml").read_text())
    assert config["verifier"]["environment_mode"] == "separate"
    assert config["artifacts"] == ["/app/output.xlsx"]
    assert not (target / "environment/reference.xlsx").exists()
    assert (target / "solution/reference.xlsx").exists()
    assert (target / "tests/reference.xlsx").exists()
    assert "COPY . /tests/" in (target / "tests/Dockerfile").read_text()
    assert "/logs/verifier/reward.txt" in (target / "tests/test.sh").read_text()
    assert (target / "export_manifest.json").is_file()
    harbor = pytest.importorskip("harbor.models.task.task")
    loaded = harbor.Task(target)
    assert loaded.name == "sheetsfactory/fixture-1"
    assert loaded.is_valid_dir(target)
