"""Offline complete-scope formula tests; no source producer, LO or model."""
import ast
import builtins
from copy import deepcopy
import dis
import importlib.util
import inspect
from pathlib import Path
import re

import openpyxl
import pytest

from sheets_factory.workbook.capital_allocation import excel as old_excel
from sheets_factory.workbook.capital_allocation_scaled import excel
from sheets_factory.workbook.capital_allocation_scaled.spec import load_spec, project_ids

ROOT = Path(__file__).resolve().parents[1]
fixture_spec = importlib.util.spec_from_file_location('scaled_emitter_math_fixture', ROOT / 'tests/test_capital_allocation_excel.py')
fixture = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(fixture)


def public(count):
    value = fixture.specification()
    for i in range(18, count):
        project = deepcopy(value['projects'][0])
        project['id'] = f'P{i+1:02d}'
        value['projects'].append(project)
    return load_spec(value)


def book():
    result = openpyxl.Workbook()
    result.remove(result.active)
    return result


def reference(sheet, address):
    return "'" + sheet + "'!" + re.sub(r'([A-Z]+)([0-9]+)', r'$\1$\2', address)


def get_path(value, path):
    for part in path:
        value = value[part]
    return value


def test_copied_financial_scenario_loop_AST_equals_frozen_original():
    def financial_loop(function):
        parsed = ast.parse(inspect.getsource(function))
        return next(node for node in ast.walk(parsed)
                    if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple)
                    and [getattr(n, 'id', '') for n in node.target.elts] == ['scenario_index', 'identity'])
    assert ast.dump(financial_loop(excel.emit_capital_allocation_workbook), include_attributes=False) == ast.dump(
        financial_loop(old_excel.emit_capital_allocation_workbook), include_attributes=False)
    assert excel.ExactArithmetic is old_excel.ExactArithmetic
    assert excel.expression_formula is old_excel.expression_formula
    assert 'PROJECT_IDS' not in [n.name for n in ast.walk(ast.parse(inspect.getsource(excel.emit_capital_allocation_workbook))) if isinstance(n, ast.alias)]
    assert not any(isinstance(n, ast.Constant) and type(n.value) is int and n.value == 18
                   for n in ast.walk(ast.parse(inspect.getsource(excel.emit_capital_allocation_workbook))))


def test_all_module_and_nested_function_global_names_are_bound():
    def check(code):
        for instruction in dis.get_instructions(code):
            if instruction.opname in ('LOAD_GLOBAL', 'LOAD_NAME'):
                assert instruction.argval in vars(excel) or hasattr(builtins, instruction.argval), instruction.argval
        for constant in code.co_consts:
            if inspect.iscode(constant):
                check(constant)
    for function in vars(excel).values():
        if inspect.isfunction(function) and function.__module__ == excel.__name__:
            check(function.__code__)


@pytest.mark.parametrize('count', [26, 28, 30])
def test_full_dynamic_scope_and_explicit_public_schema_from_first_template(count):
    workbook = book()
    bindings = excel.emit_capital_allocation_workbook(workbook, public(count))
    assert len(bindings['decision_bindings']) == count
    assert [row['project_id'] for row in bindings['decision_bindings']] == list(project_ids(count))
    assert all(workbook[row['sheet']][row['cell']].value is None for row in bindings['decision_bindings'])
    assert bindings['formula_count'] == 1980 * count + 18083
    assert bindings['formula_count'] == sum(c.data_type == 'f' for s in workbook for c in s._cells.values())
    assert len(bindings['financial_bindings']) == 540 * count + 9311
    assert len(bindings['arithmetic_bindings']) == 1440 * count + 8772
    assert bindings['public_rules'] == list(excel.PUBLIC_RULES)
    assert 'eighteen' not in ' '.join(bindings['public_rules'])
    assert all(workbook[row['sheet']][row['cell']].value == rule
               for row, rule in zip(bindings['public_rule_cells'], excel.PUBLIC_RULES))
    summary = workbook['Capital Summary']
    assert 'Feasible flag' in summary['B2'].value
    assert 'Diagnostic LP NPV' in summary['C2'].value
    assert 'Feasible LP NPV' in summary['D2'].value
    assert 'B7' in summary['A7'].value and 'D7' in summary['A7'].value
    for sid in ('S01', 'S02', 'S03'):
        assert str(count) in workbook[sid + ' Projects']['A1'].value
        assert 'UNWEIGHTED' in workbook[sid + ' Projects']['A1'].value
        assert len(bindings['project_refs'][sid]) == count
        assert 'certified_nav' in bindings['project_refs'][sid][f'P{count:02d}'][2043]
    assert bindings['gold_optimizer_proof_checked_by_emitter'] is False
    assert bindings['source_or_quality_or_difficulty_certified'] is False
    assert bindings['gold_plan_supplied'] is False
    assert bindings['arithmetic_support_values_are_protected'] is False
    assert bindings['complete_required_D_includes_changed_arithmetic_helpers'] is True
    workbook.close()


@pytest.mark.parametrize('count', [18, 26, 30])
def test_all_financial_fields_and_last_project_sensitivity_match_independent_Decimal(count):
    from sheets_factory.workbook.capital_allocation_scaled.ledger import simulate
    value = public(count)
    ids = project_ids(count)
    plan = {identity: int(identity in ('P01', ids[-1])) for identity in ids}
    independent = simulate(value, plan)
    workbook = book()
    bindings = excel.emit_capital_allocation_workbook(workbook, value, plan)
    assert bindings['formula_count'] == 1981 * count + 18083
    assert bindings['formula_count'] == sum(c.data_type == 'f' for s in workbook for c in s._cells.values())
    actual = fixture.evaluate_forward_formula_text(workbook)
    for binding in bindings['financial_bindings']:
        expected = get_path(independent, binding['expected_path'])
        expected = int(expected) if type(expected) is bool else '' if expected is None else expected
        assert actual[reference(binding['sheet'], binding['cell'])] == expected, binding['expected_path']
    for sid in ('S01', 'S02', 'S03'):
        # A deselected project still has its full, nonzero candidate schedule.
        capex = bindings['project_refs'][sid]['P02'][2024]['capex']
        last_capex = bindings['project_refs'][sid][ids[-1]][2024]['capex']
        assert actual[capex] == actual[last_capex] == 180
        annual_capex = bindings['annual_refs'][sid][2024]['capex']
        assert actual[annual_capex] == 360  # Includes last-project selection.
        # Independent last-project-only toggle changes the actual aggregate,
        # while its unweighted candidate schedule remains identical.
        without_last = dict(plan)
        without_last[ids[-1]] = 0
        alternative = simulate(value, without_last)
        assert alternative['scenarios'][sid]['annual'][0]['capex'] == 180
    assert len(bindings['project_refs']['S01']) == count
    workbook.close()


def test_public_template_has_no_selected_plan_or_cached_financial_answers(tmp_path):
    workbook = book()
    bindings = excel.emit_capital_allocation_workbook(workbook, public(26))
    path = tmp_path / 'offline_uncalculated_template.xlsx'
    workbook.save(path)
    workbook.close()
    cached = openpyxl.load_workbook(path, data_only=True)
    assert all(cached[b['sheet']][b['cell']].value is None for b in
               bindings['decision_bindings'] + bindings['financial_bindings'] + bindings['arithmetic_bindings'])
    cached.close()


@pytest.mark.parametrize('plan', [dict.fromkeys(project_ids(18), 0),
    {**dict.fromkeys(project_ids(26), 0), 'P26': True}, dict.fromkeys(project_ids(26), 2)])
def test_incomplete_or_noninteger_plan_fails_before_emission(plan):
    workbook = book()
    with pytest.raises(ValueError, match='complete common integer'):
        excel.emit_capital_allocation_workbook(workbook, public(26), plan)
    assert workbook.sheetnames == []
    workbook.close()


def test_upstream_drift_fails_instead_of_reusing_unreviewed_math(monkeypatch):
    workbook = book()
    monkeypatch.setattr(excel, 'UPSTREAM_EXCEL_SHA256', '0' * 64)
    with pytest.raises(ValueError, match='reused arithmetic'):
        excel.emit_capital_allocation_workbook(workbook, public(26))
    assert workbook.sheetnames == []
    workbook.close()
