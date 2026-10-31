"""The development adapter is tested without actual financial/source execution."""
import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    definition = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(module)
    return module


builder = load('unit_heterogeneous_v3_development', 'prepare_heterogeneous_view_v3_development.py')
previous = load('unit_heterogeneous_original_development', 'prepare_heterogeneous_view_development.py')


def test_all_calculation_control_export_and_quality_ast_unchanged():
    old = ast.parse(builder._TEMPLATE.read_text())
    new = builder.adapted_ast()
    oldf = {n.name: n for n in old.body if isinstance(n, ast.FunctionDef)}
    newf = {n.name: n for n in new.body if isinstance(n, ast.FunctionDef)}
    assert oldf.keys() == newf.keys()
    permitted = {'recipes', 'prepare', 'check_preparation', 'freeze_snapshot'}
    for name in oldf.keys() - permitted:
        assert ast.dump(oldf[name]) == ast.dump(newf[name]), name
    assert builder.CONTROL_REWARDS == previous.CONTROL_REWARDS
    assert builder.BUDGET == previous.BUDGET
    assert builder.PENDING == previous.PENDING


def test_reversing_only_declared_substitutions_recovers_entire_original_ast():
    old = ast.parse(builder._TEMPLATE.read_text())
    new = builder.adapted_ast()
    for n in new.body:
        if isinstance(n, ast.ImportFrom) and n.module == 'sheets_factory.task_adapters':
            assert [(i.name, i.asname) for i in n.names] == [('heterogeneous_financial_view_v3', 'view')]
            n.names = [ast.alias(name='heterogeneous_financial_view', asname='view')]
        if isinstance(n, ast.FunctionDef) and n.name == 'recipes':
            addition = ast.dump(ast.parse('paths.extend(_recipe_extra_paths())').body[0])
            matches = [i for i, line in enumerate(n.body) if ast.dump(line) == addition]
            assert len(matches) == 1
            del n.body[matches[0]]
    reverse = {'prepared_heterogeneous_business_view_v3_development':
        'prepared_heterogeneous_business_view_development',
        'prequality_heterogeneous_business_view_v3_development':
        'prequality_heterogeneous_business_view_development',
        'fm-heterogeneous-v3-H01-': 'fm-heterogeneous-H01-'}
    class Undo(ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, str) and node.value in reverse:
                node.value = reverse[node.value]
            return node
    assert ast.dump(Undo().visit(new)) == ast.dump(old)


def test_complete_ancestor_and_own_recipes_are_present():
    files = builder.recipes()
    expected = [ROOT / 'scripts' / f for f in [
        'prepare_heterogeneous_view_development.py',
        'prepare_heterogeneous_view_v2_development.py',
        'prepare_heterogeneous_view_v3_development.py']]
    expected += [ROOT / 'src/sheets_factory/task_adapters' / f for f in [
        'heterogeneous_financial_view.py', 'heterogeneous_financial_view_v2.py',
        'heterogeneous_financial_view_v3.py']]
    expected += [ROOT / 'config/task_adapters' / f for f in [
        'heterogeneous_financial_view_v1.json', 'heterogeneous_financial_view_v2.json',
        'heterogeneous_financial_view_v3.json']]
    assert all(str(p) in files for p in expected)
    assert files[str(builder._TEMPLATE)] == builder._TEMPLATE_SHA256
    assert builder.view.ADAPTER_ID == 'heterogeneous_business_financial_view_v3'
    assert builder.view.setting()['enabled'] is False
    assert builder.view.public_brief() == previous.view.public_brief()


def test_frozen_original_sha_disagreement_fails_before_source_or_engine(monkeypatch):
    monkeypatch.setattr(builder, '_TEMPLATE_SHA256', '0' * 64)
    with pytest.raises(ValueError, match='predecessor development builder changed'):
        builder.adapted_ast()


@pytest.mark.parametrize('kind', ['prepared_heterogeneous_business_view_development',
    'prepared_heterogeneous_business_view_v2_development'])
def test_older_preparation_cannot_enter_v3_execution(monkeypatch, tmp_path, kind):
    helper = builder.support()
    monkeypatch.setattr(helper, 'read', lambda _: {'kind': kind, 'recipe': builder.recipes()})
    monkeypatch.setattr(builder, 'support', lambda: helper)
    monkeypatch.setattr(builder.view, 'validate_source',
        lambda _: pytest.fail('Prior revision must fail before source admission'))
    with pytest.raises(ValueError, match='frozen development recipe changed'):
        builder.check_preparation(tmp_path)


def test_tiny_prepare_uses_v3_identity_zero_execution(monkeypatch, tmp_path):
    # Explicit admission test double; this creates only a fixture preparation,
    # never a workbook, actual source certificate or task.
    source = tmp_path / 'UNIT.json'
    source.write_text('{}')
    helper = builder.support()
    monkeypatch.setattr(helper, '_output', lambda path, **_: Path(path))
    monkeypatch.setattr(builder, 'support', lambda: helper)
    monkeypatch.setattr(builder.view, 'validate_source', lambda _: {'UNIT_not_source_proof': True})
    output = tmp_path / 'UNIT-prepared'
    ref = builder.prepare(source, output)
    record = helper.read(ref)
    assert record['kind'] == 'prepared_heterogeneous_business_view_v3_development'
    assert record['model_calls'] == record['new_LO_calls'] == record['task_count'] == 0
    assert record['qualified'] is False
    assert not list(output.rglob('*.xlsx'))


def test_cli_does_not_execute_without_explicit_run(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(builder, 'prepare', lambda *a: calls.append('prepare') or {'UNIT': True})
    monkeypatch.setattr(builder, 'execute_prepared', lambda *a, **k: pytest.fail('No explicit run'))
    builder.main(['--source-manifest', 'UNIT.json', '--output', str(tmp_path / 'UNIT')])
    assert calls == ['prepare']
