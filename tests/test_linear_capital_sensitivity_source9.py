"""Small independent financial/formula census and mocked admission; no services."""
from copy import deepcopy
from fractions import Fraction
import importlib.util
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import openpyxl
import pytest

from sheets_factory.workbook.linear_capital_scaled import finance, model_a, model_b
from sheets_factory.workbook.linear_capital_sensitivity import contract, excel9, source9

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    descriptor = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(descriptor); descriptor.loader.exec_module(value); return value


inputs = module('_sensitivity9_hand_inputs', ROOT/'tests/test_linear_capital_portfolio_ledger.py')
interpreter = module('_sensitivity9_exact_formula_interpreter', ROOT/'tests/test_linear_capital_portfolio_excel.py')


@pytest.fixture(scope='module')
def joined():
    raw = inputs.fixture(projects=3, years=5, scenarios=3)
    raw.update(kind=contract.spec.SPEC_KIND, version=contract.spec.SPEC_VERSION)
    raw['projects'][1].update(debt_policy='BULLET', operating_start_year=2,
        revenue_growth_factor_bp=10300, depreciation_years=4)
    raw['scenarios'][1]['revenue_factors_bp']['3'] = 8500
    raw['exclusivity_groups'] = [{'id': 'SITE', 'description': 'Two alternatives', 'project_ids': ['P001', 'P002']}]
    raw['prerequisites'] = [{'id': 'LINK', 'dependent': 'P003', 'prerequisite': 'P001', 'business_reason': 'Shared access connection'}]
    public = contract.spec.load_spec(raw)
    # Tiny host financial forwards only. No production generation or engine.
    universes = {'A': finance.build_universe_a(public), 'B': finance.build_universe_b(public)}
    base = {'A': model_a.build_model(public), 'B': model_b.build_model(public)}
    models = {}; plans = {}; results = {s: {'projects': universes[s]['projects'], 'cases': {}} for s in ('A', 'B')}
    comparison = finance._module('finance_crosscheck')
    for index, case in enumerate(contract.CASES):
        identity = case['id']; revised = deepcopy(public); limits = revised['shared_limits']
        limits['initial_sponsor_equity_pence'] = limits['initial_sponsor_equity_pence'] * case['budget_percent']//100
        for resource, scenarios in limits['resource_capacity_units'].items():
            for sid, years in scenarios.items():
                for year in years: years[year] = years[year]*case['capacity_percent']//100
        models[identity] = {}
        for side in ('A', 'B'):
            model = deepcopy(base[side]); model['specification_sha256'] = contract.spec.canonical_sha256(revised)
            for row in model['rows']:
                if row['family'] == 'initial_sponsor_equity': row['limit'] = row['limit']*case['budget_percent']//100
                elif row['family'] == 'resource': row['limit'] = row['limit']*case['capacity_percent']//100
            models[identity][side] = model
        plans[identity] = {'P001': 1, 'P002': 0, 'P003': index % 2}
        projected = comparison._compare_plans(revised, universes['A'], universes['B'],
            [{'id': 'winner', 'plan': plans[identity]}], True)
        assert projected['passed']
        for side in ('A', 'B'): results[side]['cases'][identity] = projected['plans'][0][side]
    return {'public': public, 'case_models': models, 'plans': plans, 'results': results,
        'case_order': [c['id'] for c in contract.CASES]}


@pytest.fixture
def book(tmp_path, joined):
    path = tmp_path/'goal.xlsx'
    binding = excel9.emit_workbook(path, joined['public'], joined['case_models'], joined['plans'])
    return path, binding


def test_every_physical_formula_and_financial_value_matches_two_independent_ledgers(book, joined):
    path, bindings = book; expected = source9.expected_values(joined, bindings)
    # Supply each case's independently chosen literal decisions to the generic
    # exact test interpreter; its arithmetic does not use an emitter calculator.
    inputs = {**bindings, 'literal_bindings': bindings['literal_bindings'] +
        [dict(row) for row in bindings['decision_bindings']], 'decision_bindings': []}
    actual = interpreter.evaluate(inputs, joined['public'], None)
    assert len(expected['formulas']) == bindings['formula_count']
    assert len(actual) == len(expected['values'])
    for point, value in expected['values'].items(): assert actual[point] == value, point
    assert bindings['shared_project_ledger_copies'] == 1 and bindings['project_sheet_count'] == 3
    assert bindings['choice_count'] == 27 and bindings['case_cash_rows'] == 9*3*5
    assert bindings['case_constraint_rows'] == 9*contract.spec.expected_constraint_count(joined['public'])
    assert not bindings['financial_expected_values_embedded'] and not bindings['actual_engine_validated']
    with ZipFile(path) as archive:
        formulas = 0
        for name in archive.namelist():
            if name.startswith('xl/worksheets/sheet') and name.endswith('.xml'):
                for cell in ET.fromstring(archive.read(name)).findall('{*}sheetData/{*}row/{*}c'):
                    if cell.find('{*}f') is not None:
                        formulas += 1; value = cell.find('{*}v'); assert value is None or value.text is None
        assert formulas == bindings['formula_count']


def test_nonapplicable_fields_are_provided_NA_and_no_old_single_gold_plan_exists(book, joined):
    path, bindings = book; workbook = openpyxl.load_workbook(path)
    assert 'Portfolio' not in workbook.sheetnames and 'GroupSummary' not in workbook.sheetnames
    assert len([s for s in workbook.sheetnames if s in joined['public']['project_ids']]) == 3
    assert bindings['provided_NA_literal_count'] > 0
    for row in workbook['CaseRHS']:
        assert all(c.value is not None for c in row)
    for row in workbook['CaseChecks']:
        assert all(c.value is not None for c in row)
    assert not any('intentionally blank' in str(c.value) for row in workbook['ContractNotes'] for c in row)
    assert all(r.get('case_id') in joined['case_order'] for r in bindings['decision_bindings'])
    workbook.close()


@pytest.mark.parametrize('mode', ['financial_modeling', 'debugging'])
def test_views_preserve_all_facts_NAs_and_remove_all_gold_choice_vectors(book, joined, tmp_path, mode):
    path, bindings = book; before_bytes = path.read_bytes()
    edits = excel9.materialize_view(path, tmp_path/mode, bindings, joined['public'], mode=mode)
    goal = openpyxl.load_workbook(path); public = openpyxl.load_workbook(tmp_path/mode/'public/input.xlsx')
    financial = {(r['sheet'], r['cell']) for r in bindings['financial_bindings']}
    for r in bindings['input_bindings'] + bindings['literal_bindings']:
        if (r['sheet'], r['cell']) not in financial:
            assert public[r['sheet']][r['cell']].value == goal[r['sheet']][r['cell']].value
    for r in bindings['decision_bindings']:
        assert public[r['sheet']][r['cell']].value == (None if mode == 'financial_modeling' else 0)
    if mode == 'financial_modeling':
        assert not any(c.data_type == 'f' for s in public for row in s for c in row)
    else:
        assert all(any(e['family'] == family for e in edits['formula_edits']) for family in excel9.FAMILIES)
        assert len(edits['choice_edits']) == 27
        for identity in joined['case_order']:
            rows = [r for r in bindings['decision_bindings'] if r['case_id'] == identity]
            assert [public[r['sheet']][r['cell']].value for r in rows] != list(joined['plans'][identity].values())
    assert set(p.name for p in (tmp_path/mode/'public').iterdir()) == {'input.xlsx', 'instruction.md'}
    assert path.read_bytes() == before_bytes and edits['actual_full_D_controls_or_stability_verified'] is False
    goal.close(); public.close()


@pytest.mark.parametrize('change', ['missing_case', 'changed_rhs', 'changed_coefficients'])
def test_emitter_rejects_incomplete_case_pool_or_changed_economics(joined, tmp_path, change):
    models = deepcopy(joined['case_models']); case = joined['case_order'][0]
    if change == 'missing_case': models.pop(case)
    elif change == 'changed_rhs': models[case]['A']['rows'][0]['limit'] += 1
    else: models[case]['A']['objective_pence'][0] += 1
    with pytest.raises(ValueError): excel9.emit_workbook(tmp_path/'bad.xlsx', joined['public'], models, joined['plans'])


def test_independent_join_and_candidate_stop_before_winner_reads_if_nine_reference_not_genuine(tmp_path, monkeypatch):
    def reject(_): raise ValueError('One case incomplete; no full-nine actual reference')
    monkeypatch.setattr(source9.reference, 'validate_completed', reject)
    monkeypatch.setattr(source9.reference, 'read', lambda _: pytest.fail('No winner cache may be read before genuine admission'))
    with pytest.raises(ValueError): source9.join_reference({'passed': True})
    monkeypatch.setattr(source9.reference, 'ROOT', tmp_path)
    with pytest.raises(ValueError): source9.build_candidate({'passed': True}, tmp_path/'outputs/candidate')
    assert not (tmp_path/'outputs/candidate').exists()


def test_full_expected_scope_rejects_decision_omission_and_A_B_drift(book, joined):
    _, bindings = book
    wrong = deepcopy(bindings); wrong['decision_bindings'].pop()
    with pytest.raises(ValueError): source9.expected_values(joined, wrong)
    changed = deepcopy(joined); case = changed['case_order'][0]
    changed['results']['B']['cases'][case]['objective_pence'] += 1
    with pytest.raises(ValueError): source9.expected_values(changed, bindings)


def test_sparse_vintage_malformed_rows_cannot_be_promoted_to_zero():
    binding = {'expected_path': ['rows'], 'vintage_field': 'closing', 'vintage_year': 4, 'origin_year': 1,
        'kind': 'money_pence', 'worksheet_scale': 1}
    with pytest.raises(ValueError): source9.resolve_expected(binding, {'rows': [{'year': 4, 'origin_year': 1}]})


def test_all_nine_source_join_is_strict_and_allows_repeated_winners(joined, monkeypatch):
    public = joined['public']; winner = dict(joined['plans'][joined['case_order'][0]])
    rows = []; terms = []; projections = {}; values = {}
    constraints = [{'id': str(i), 'passed': True} for i in range(941)]
    for case in contract.CASES:
        identity = case['id']; projection = {'comparison': {'passed': True, 'plan_count': 2, 'plans': [
            {'id': 'winner', 'plan': winner, 'passed': True, 'errors': [], 'differences': [],
             **{side: {'feasible': True, 'objective_pence': 123, 'constraints': constraints} for side in ('A', 'B')}}]}}
        projections[identity] = projection; values['projection_'+identity] = projection
        rows.append({'case': case, 'models': {'A': 'A_'+identity, 'B': 'B_'+identity}})
        values['A_'+identity] = {'test_only': True}; values['B_'+identity] = {'test_only': True}
        values['case_'+identity] = {'case': case, 'passed': True, 'gap_pence': 1, 'winner_plan': winner,
            'runner_plan': dict.fromkeys(public['project_ids'], 0), 'winner_objective_pence': 123,
            'financial_projection': 'projection_'+identity}; terms.append('case_'+identity)
    values.update(preparation={'all_nine_models': 'inventory', 'prospective': 'prospective'},
        inventory={'case_order': joined['case_order'], 'cases': rows},
        prospective={'financial_terminal': 'finance', 'contract': 'contract'}, contract={},
        finance={'specification': 'specification', 'universe_A': 'universe_A', 'universe_B': 'universe_B', 'model_A': 'base_A', 'model_B': 'base_B'},
        specification=public, universe_A={'projects': {'test_only': True}}, universe_B={'projects': {'test_only': True}})
    actual = {'preparation': 'preparation', 'case_order': joined['case_order'], 'cases': terms}
    monkeypatch.setattr(source9.reference, 'validate_completed', lambda _: actual)
    monkeypatch.setattr(source9.reference, 'read', lambda key: values[key])
    monkeypatch.setattr(source9.reference, '_refs', lambda _: None)
    monkeypatch.setattr(source9.reference, '_financial_projection', lambda inputs, row, a, b: projections[row['case']['id']])
    result = source9.join_reference({'test_only_genuine_boundary_mock': True})
    assert result['distinct_winner_vectors'] == 1 and len(result['plans']) == 9
    assert result['different_winners_required'] is False and result['qualified'] is False
    values[terms[0]]['passed'] = False
    with pytest.raises(ValueError): source9.join_reference({'test_only_genuine_boundary_mock': True})
