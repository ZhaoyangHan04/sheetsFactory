"""Small exact financial checks for the isolated N360 renderer and task views."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import openpyxl
import pytest

from sheets_factory.workbook.linear_capital_portfolio import (
    candidate_a, excel as old_excel, ledger, spec as old_spec, task_views as old_views)
from sheets_factory.workbook.linear_capital_scaled import excel, spec, task_views

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    definition = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(definition); definition.loader.exec_module(result)
    return result


inputs = module('_scaled_excel_hand_inputs', ROOT/'tests/test_linear_capital_portfolio_ledger.py')
interpreter = module('_scaled_excel_exact_interpreter', ROOT/'tests/test_linear_capital_portfolio_excel.py')


def fixture():
    original = inputs.fixture(projects=2, years=5, scenarios=3)
    original['projects'][0].update(depreciation_years=3, revenue_growth_factor_bp=10500,
        opex_growth_factor_bp=10250, discount_rate_bp=750)
    original['projects'][1].update(debt_policy='BULLET', operating_start_year=2)
    original['scenarios'][1]['revenue_factors_bp']['3'] = 8500
    original['exclusivity_groups'] = [{'id':'SITE', 'description':'Alternative developments',
        'project_ids':['P001', 'P002']}]
    scaled = deepcopy(original); scaled.update(version=spec.SPEC_VERSION, kind=spec.SPEC_KIND)
    return original, spec.load_spec(scaled)


def cells(path):
    book = openpyxl.load_workbook(path, data_only=False)
    try:
        return book.sheetnames, {(s.title,c.coordinate):c.value for s in book
            for row in s for c in row if c.value is not None}
    finally: book.close()


def test_every_scaled_toy_formula_matches_two_independent_original_financial_journals(tmp_path):
    original, public = fixture(); plan = {'P001':1, 'P002':0}
    a, b = candidate_a.simulate(original, plan), ledger.simulate(original, plan)
    bindings = excel.emit_workbook(tmp_path/'source.xlsx', public, plan=plan)
    values = interpreter.evaluate(bindings, public, plan)
    assert bindings['kind'] == excel.BINDING_KIND
    assert bindings['formula_count'] > 0 and bindings['dimensions'] == {'projects':2,'scenarios':3,'years':5}
    assert bindings['constraint_count'] == spec.expected_constraint_count(public)
    for row in bindings['financial_bindings']:
        expected_a, expected_b = interpreter.expected(row,a), interpreter.expected(row,b)
        assert expected_a == expected_b
        assert values[row['sheet'],row['cell']] == expected_a
    assert any(r['formula'] is None and r['expression'] == 0 for r in bindings['financial_bindings'])
    assert not bindings['financial_implementation_executed']
    assert not bindings['optimization_executed']
    assert not bindings['financial_source_or_difficulty_certified']


@pytest.mark.parametrize('mode', ['financial_modeling','debugging'])
def test_complete_masks_and_primary_faults_preserve_supplied_cells_and_goal(tmp_path, mode):
    _, public = fixture(); path = tmp_path/'source.xlsx'
    bindings = excel.emit_workbook(path, public, plan={'P001':1,'P002':0})
    original_bytes = path.read_bytes(); names, before = cells(path)
    plan = task_views.plan_task_view(path, public, bindings, mode=mode)
    result = task_views.materialize_view(plan, tmp_path/mode)
    after_names, after = cells(result['input']['path'])
    assert after_names == names
    for row in plan['provided_cells']:
        assert after[row['sheet'],row['cell']] == row['value']
        assert type(after[row['sheet'],row['cell']]) is type(row['value'])
    assert Path(result['goal']['path']).read_bytes() == original_bytes == path.read_bytes()
    assert result['kind'] == 'materialized_unverified_linear_capital_scaled_task_view'
    if mode == 'financial_modeling':
        expected = {(r['sheet'],r['cell']) for domain in ('financial_bindings','arithmetic_bindings','decision_bindings')
            for r in bindings[domain]}
        assert set(before)-set(after) == expected
        assert not any(type(v) is str and v.startswith('=') for v in after.values())
    else:
        assert all(plan['family_physical_edit_counts'][f] > 0 for f in task_views.FAMILIES)
        _, baseline = cells(result['temporary_plan_only']['path'])
        edits = {(r['sheet'],r['cell']):r for r in plan['formula_edits']}
        assert {k for k in set(after)|set(baseline) if after.get(k) != baseline.get(k)} == set(edits)
        for family, artifact in result['family_inputs'].items():
            _, variant = cells(artifact['path'])
            assert {k for k in set(variant)|set(baseline) if variant.get(k) != baseline.get(k)} == {
                k for k,r in edits.items() if r['family'] == family}
    assert not result['actual_controls_verified']
    assert not result['quality_recovery_Harbor_difficulty_certified']
    assert result['new_financial_forwards_optimizer_LO_models'] == 0
    assert {p.name for p in (tmp_path/mode/'public').iterdir()} == {'input.xlsx','instruction.md'}


def test_namespace_recipe_binds_both_frozen_implementations_and_never_changes_originals():
    assert len(old_spec.PROJECT_IDS) == 240 and len(spec.PROJECT_IDS) == 360
    assert task_views.FM_INSTRUCTION == old_views.FM_INSTRUCTION
    assert task_views.DBG_INSTRUCTION == old_views.DBG_INSTRUCTION
    assert old_excel.emit_workbook.__defaults__ is None
    assert old_excel.emit_workbook.__kwdefaults__['max_formulas'] == 1_000_000
    assert excel.emit_workbook.__kwdefaults__['max_formulas'] == 1_500_000
    bound = {r['path']:r['sha256'] for r in task_views._recipe()}
    assert bound[str(excel.UPSTREAM)] == excel.UPSTREAM_SHA256
    assert bound[str(task_views.UPSTREAM)] == task_views.UPSTREAM_SHA256


@pytest.mark.parametrize('adapter', [excel,task_views])
def test_any_upstream_drift_fails_before_execution(tmp_path, monkeypatch, adapter):
    altered = tmp_path/'changed.py'; altered.write_bytes(adapter.UPSTREAM.read_bytes()+b'\n')
    monkeypatch.setattr(adapter,'UPSTREAM',altered)
    with pytest.raises(ValueError,match='frozen'): adapter.adapted_ast()


def test_original_and_scaled_binding_kinds_are_not_interchangeable(tmp_path):
    original, public = fixture(); path = tmp_path/'source.xlsx'
    bindings = excel.emit_workbook(path, public, plan={'P001':1,'P002':0})
    wrong = deepcopy(bindings); wrong['kind'] = 'linear_capital_portfolio_native_excel_bindings'
    with pytest.raises(ValueError,match='source identity'):
        task_views.plan_task_view(path, public, wrong, mode='financial_modeling')
    assert old_spec.load_spec(original)['version'] == 1
    with pytest.raises(ValueError,match='Unknown portfolio'): old_spec.load_spec(public)
    with pytest.raises(ValueError,match='Unknown portfolio'): spec.load_spec(original)
