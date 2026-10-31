import ast
from copy import deepcopy
import importlib.util
from pathlib import Path

from openpyxl import Workbook, load_workbook
import pytest


@pytest.fixture
def subject():
    path = Path(__file__).resolve().parents[1] / 'scripts/prepare_specialized_debugging_development.py'
    definition = importlib.util.spec_from_file_location('_specialized_debugging_test', path)
    module = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(module)
    return module


def test_full_resource_export_ast_has_only_explicit_identity_substitutions(subject):
    expected = next(n for n in ast.parse(subject.TEMPLATE.read_bytes()).body
        if isinstance(n, ast.FunctionDef) and n.name == 'freeze_snapshot')
    actual = deepcopy(subject.frozen_export_ast().body[0])
    reversed_values = {'dbg-heterogeneous-specialized-H01-': 'fm-heterogeneous-H01-',
        'debugging': 'financial_modeling', 'heterogeneous-specialized-source.xlsx': 'heterogeneous-native-business-source.xlsx',
        'prequality_specialized_heterogeneous_debugging_development': 'prequality_heterogeneous_business_view_development'}
    class Restore(ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, str) and node.value in reversed_values:
                node.value = reversed_values[node.value]
            return node
    actual = Restore().visit(actual)
    assert ast.dump(actual, include_attributes=False) == ast.dump(expected, include_attributes=False)


def test_actual_mutant_only_changes_explicit_formulas_and_accepts_redundant_sheet_quotes(subject, tmp_path):
    source = tmp_path/'source.xlsx'; output = tmp_path/'mutant.xlsx'
    book = Workbook(); book.active.title = 'Calc'; book.create_sheet('Calendar')
    book['Calendar']['D2'] = 1
    book['Calc']['A1'] = 'fixed assumption'; book['Calc']['A2'] = 123.45
    book['Calc']['B2'] = '=IF(Calendar!$D$2,7,0)'
    book['Calc']['B2'].number_format = '0.00'
    book['Calc']['B3'] = '=B2+1'; book.save(source); book.close()
    edits = [{'sheet': 'Calc', 'cell': 'B2', 'before_formula': "=IF('Calendar'!$D$2,7,0)",
        'after_formula': '=IF(Calendar!$D$2,8,0)'}]
    subject._mutant(source, output, edits)
    result = load_workbook(output)
    try:
        assert result.sheetnames == ['Calc','Calendar']
        assert result['Calc']['B2'].value == edits[0]['after_formula']
        assert result['Calc']['B2'].number_format == '0.00'
        assert result['Calc']['B3'].value == '=B2+1'
        assert result['Calc']['A1'].value == 'fixed assumption'
        assert result['Calc']['A2'].value == 123.45
    finally:
        result.close()


@pytest.mark.parametrize('before', ['=IF(Calendar!D2,7,0)', '=IF(Calendar!$D$3,7,0)', '=IF(Calendar!$D$2,8,0)'])
def test_semantic_or_absolute_reference_change_rejects_before_output(subject, tmp_path, before):
    source = tmp_path/'source.xlsx'; output = tmp_path/'never.xlsx'
    book = Workbook(); book.active.title = 'Calc'; book['Calc']['B2'] = '=IF(Calendar!$D$2,7,0)'
    book.save(source); book.close()
    with pytest.raises(ValueError, match='complete bound definition'):
        subject._mutant(source, output, [{'sheet':'Calc','cell':'B2','before_formula':before,'after_formula':'=1'}])
    assert not output.exists()


def test_every_new_executable_component_is_in_recipe(subject):
    inventory = subject.recipes()
    for name in ('heterogeneous_formula_identity.py','heterogeneous_specialized_source.py',
                 'heterogeneous_specialized_debugging.py'):
        assert any(Path(path).name == name for path in inventory)
    assert subject.BUDGET['tool_budget_seconds'] == 1800
    assert subject.BUDGET['elapsed_guard_seconds'] == 14400
    assert subject.CONTROL_REWARDS == {'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}


def test_unverified_source_never_reaches_execution_and_preserves_rejection(subject, tmp_path, monkeypatch):
    import json
    manifest = tmp_path/'unverified.json'
    manifest.write_text('{"kind":"independently_verified_heterogeneous_contract_source","version":1}')
    output = tmp_path/'rejected-preparation'
    def forbidden(*args, **kwargs):
        raise AssertionError('Preparation must not construct a calculation engine')
    monkeypatch.setattr(subject, 'ResourceLibreOfficeEngine', forbidden)
    with pytest.raises(ValueError, match='completed independently verified'):
        subject.prepare(manifest, output)
    failure = json.loads((output/'preparation_failure.json').read_text())
    assert failure['status'] == 'failed' and failure['model_calls'] == 0 and failure['qualified'] is False
    assert not (output/'started.json').exists()
    with pytest.raises(ValueError, match='fresh directory'):
        subject.prepare(manifest, output)
