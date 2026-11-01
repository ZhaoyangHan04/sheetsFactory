import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('remaining_controls_revision2', ROOT/'scripts/resume_ringfenced_pair_task8_remaining_revision2.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def test_same_original_private_engine_accepts_exact_real_ringprofile_without_calculation(tmp_path):
    # The engine constructor only validates the profile and creates a receipt directory.
    # It does not inspect Docker or calculate a workbook.
    folder = ROOT/'outputs/tmp'/tmp_path.name/'constructor_receipts'
    engine = m.engine_class()(ROOT, m.v1.PROFILE, role='source', receipt_directory=folder)
    assert engine.profile_binding == m.ref(m.v1.PROFILE)
    assert engine.profile['id'] == 'ringfenced_pair_source_v1'
    assert engine.profile['limits']['source_physical_formulas'] == 2600000
    assert engine.profile['docker_resources']['source'] == {'cpus': 2, 'memory_bytes': 34359738368, 'pids_limit': 256}
    assert engine.metadata()['actual_resource_receipts'] == []


def test_private_engine_rejects_changed_hardware_or_business_cell_limits(tmp_path):
    import yaml
    original = yaml.safe_load(m.v1.PROFILE.read_text())
    original['limits']['source_physical_formulas'] += 1
    with pytest.raises(ValueError, match='Only the prospectively fixed'):
        m.engine_class()(ROOT, original, role='source', receipt_directory=ROOT/'outputs/tmp'/tmp_path.name/'rejected')


def test_controls_only_executes_remaining_calls_and_finalizer_has_no_native_call():
    tree = ast.parse(Path(m.__file__).read_text())
    controls = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'controls')
    final = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'finalize')
    native = [n for n in ast.walk(controls) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'recalculate']
    assert len(native) == 1
    loop = next(n for n in ast.walk(controls) if isinstance(n, ast.For) and any(x is native[0] for x in ast.walk(n)))
    assert ast.unparse(loop.iter) == 'enumerate(v1.REMAINING, 5)'
    assert not [n for n in ast.walk(final) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ('recalculate', 'solve', 'complete')]


def test_failed_first_revision_is_preserved_and_controls_terminal_is_explicit():
    text = Path(m.__file__).read_text()
    assert "prior_zero_call_failure': ref(ZERO_CALL_FAILURE)" in text
    assert "write(output/'controls_terminal.json'" in text
    assert "original_records_modified': False" in text
    assert "read(terminal)" in text
