"""Source-admission unit checks; no actual source, optimization or LO claim."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import json

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location('linear_source_test_entry', ROOT / 'scripts/build_linear_capital_source.py')
source = importlib.util.module_from_spec(loader); loader.loader.exec_module(source)


def fixture():
    public = {'project_ids': ['P001'], 'asset_cost': 20}
    plan = {'P001': 1}
    result = {'projects': {'P001': {'npv_pence': 7, 'feasible': True, 'tax_vintages': [
        {'year': 1, 'fiscal_year': 2027, 'origin_year': 1, 'opening': 0, 'expired': 0, 'used': 0, 'created': 4, 'closing': 4}]}},
        'constraints': [{'id': 'capacity', 'lhs': 20, 'limit': 25, 'slack': 5, 'passed': True}]}
    financial = [
        {'sheet': 'Portfolio', 'cell': 'C3', 'formula': '=7', 'expected_path': ['projects', 'P001', 'npv_pence'], 'kind': 'money_pence', 'worksheet_scale': 1},
        {'sheet': 'Portfolio', 'cell': 'B4', 'formula': '=1', 'expected_path': ['projects', 'P001', 'feasible'], 'kind': 'flag', 'worksheet_scale': 1},
        {'sheet': 'Portfolio', 'cell': 'B5', 'formula': '=5', 'expected_path': ['constraints'], 'constraint_id': 'capacity', 'constraint_field': 'slack', 'kind': 'integer', 'worksheet_scale': 1},
        {'sheet': 'Portfolio', 'cell': 'B6', 'formula': None, 'expected_path': ['projects', 'P001', 'tax_vintages'], 'vintage_year': 2, 'origin_year': 2,
            'vintage_field': 'closing', 'kind': 'money_pence', 'worksheet_scale': 1},
    ]
    extra = {'sheet': 'Portfolio', 'cell': 'B3', 'formula': '=1', 'expected_derivation': {'kind': 'complete_binary_decisions', 'project_ids': ['P001']}}
    binding = {'binding_version': 1, 'specification_sha256': source.spec.canonical_sha256(public),
        'financial_expected_values_embedded': False, 'financial_implementation_executed': False, 'optimization_executed': False,
        'input_bindings': [{'sheet': 'Inputs', 'cell': 'A1', 'path': ['asset_cost'], 'kind': 'integer'}],
        'literal_bindings': [{'sheet': 'Portfolio', 'cell': 'A1', 'value': 'Cash / GBP pence', 'kind': 'text'},
            {'sheet': 'Portfolio', 'cell': 'B6', 'value': 0, 'kind': 'integer'}],
        'decision_bindings': [{'sheet': 'Portfolio', 'cell': 'B2', 'project_id': 'P001', 'value': 1}],
        'financial_bindings': financial, 'arithmetic_bindings': financial[:3] + [extra],
        'formula_count': 4, 'sheetnames': ['Inputs', 'Portfolio']}
    return public, plan, result, binding


def test_complete_formula_and_static_financial_literal_coverage():
    public, plan, result, binding = fixture()
    expected = source.expected_values(public, result, deepcopy(result), binding, plan)
    assert expected['formula_count'] == 4 and expected['financial_locator_count'] == 4
    assert expected['financial_formula_count'] == 3
    assert expected['values']['Portfolio', 'B4'] == 1
    assert type(expected['values']['Portfolio', 'B4']) is int
    assert expected['values']['Portfolio', 'B6'] == 0
    assert expected['values']['Portfolio', 'B3'] == 1


def test_all_independent_financial_postings_must_agree():
    public, plan, a, binding = fixture(); b = deepcopy(a)
    b['projects']['P001']['npv_pence'] = 8
    with pytest.raises(ValueError, match='disagree'):
        source.expected_values(public, a, b, binding, plan)


def test_constraint_matching_uses_unique_identity_not_position():
    _, _, result, binding = fixture()
    result['constraints'].insert(0, {'id': 'other', 'slack': 99})
    assert source._financial_value(result, binding['financial_bindings'][2]) == 5
    result['constraints'].append(deepcopy(result['constraints'][1]))
    with pytest.raises(ValueError, match='duplicated'):
        source._financial_value(result, binding['financial_bindings'][2])


@pytest.mark.parametrize('bad', ['duplicate', 'negative', 'missing', 'bool'])
def test_invalid_sparse_vintage_cannot_be_treated_as_zero(bad):
    _, _, result, binding = fixture(); vintage = result['projects']['P001']['tax_vintages']
    if bad == 'duplicate': vintage.append(deepcopy(vintage[0]))
    if bad == 'negative': vintage[0]['closing'] = -1
    if bad == 'missing': del vintage[0]['used']
    if bad == 'bool': vintage[0]['closing'] = True
    with pytest.raises(ValueError): source._financial_value(result, binding['financial_bindings'][3])


def test_provided_static_zero_must_equal_independent_zero():
    public, plan, a, binding = fixture()
    binding['literal_bindings'][1]['value'] = 1
    with pytest.raises(ValueError, match='static financial literal'):
        source.expected_values(public, a, deepcopy(a), binding, plan)


@pytest.mark.parametrize('mutation', ['duplicate_formula', 'missing_locator', 'unknown_derived', 'missing_decision', 'wrong_choice', 'wrong_scale'])
def test_no_formula_or_choice_can_escape_complete_coverage(mutation):
    public, plan, a, binding = fixture()
    if mutation == 'duplicate_formula': binding['arithmetic_bindings'].append(deepcopy(binding['arithmetic_bindings'][0]))
    if mutation == 'missing_locator': binding['financial_bindings'].pop(0)
    if mutation == 'unknown_derived': binding['arithmetic_bindings'][-1]['expected_derivation'] = {'kind': 'cached_answer'}
    if mutation == 'missing_decision': binding['decision_bindings'] = []
    if mutation == 'wrong_choice': binding['decision_bindings'][0]['value'] = 0
    if mutation == 'wrong_scale': binding['financial_bindings'][0]['worksheet_scale'] = 100
    with pytest.raises(ValueError): source.expected_values(public, a, deepcopy(a), binding, plan)


def test_flags_and_empty_npvs_have_explicit_type_rules():
    _, _, result, binding = fixture()
    flag = binding['financial_bindings'][1]
    assert source._financial_value(result, flag) == 1
    result['projects']['P001']['feasible'] = '1'
    with pytest.raises(ValueError): source._financial_value(result, flag)
    nullable = {**binding['financial_bindings'][0], 'kind': 'nullable_money_pence'}
    result['projects']['P001']['npv_pence'] = None
    assert source._financial_value(result, nullable) is None
    with pytest.raises(ValueError): source._financial_value(result, binding['financial_bindings'][0])
    assert source._typed(False) != source._typed(0)
    assert source._typed(1.0) == source._typed(1)
    assert source._typed('') == source._typed(None)


def test_raw_uncached_workbook_cannot_pass_as_actual_cache_audit(tmp_path):
    public, plan, result, binding = fixture()
    book = openpyxl.Workbook(); book.active.title = 'Inputs'; book.create_sheet('Portfolio')
    expected = source.expected_values(public, result, deepcopy(result), binding, plan)
    for (sheet, cell), value in expected['values'].items():
        book[sheet][cell] = expected['formulas'].get((sheet, cell), value)
    file = tmp_path / 'uncached_unit_fixture.xlsx'; book.save(file); book.close()
    report = source.audit_workbook(file, public, result, deepcopy(result), binding, plan,
        {('Inputs', 'A1'): source._typed(20), ('Portfolio', 'A1'): source._typed('Cash / GBP pence'),
         ('Portfolio', 'B2'): source._typed(1), ('Portfolio', 'B6'): source._typed(0)})
    assert report['passed'] is False and report['mismatch_count'] == 4
    assert report['all_physical_formulas_checked'] == 4 and report['all_financial_locators_checked'] == 4
    assert report['additional_financial_forwards'] == 0


def test_unbound_physical_formula_is_rejected(tmp_path):
    public, plan, result, binding = fixture()
    book = openpyxl.Workbook(); book.active.title = 'Inputs'; book.create_sheet('Portfolio')
    for (sheet, cell), value in source.expected_values(public, result, result, binding, plan)['values'].items():
        book[sheet][cell] = value
    for row in binding['arithmetic_bindings']: book[row['sheet']][row['cell']] = row['formula']
    book['Portfolio']['Z99'] = '=123'
    file = tmp_path / 'extra_formula_unit_fixture.xlsx'; book.save(file); book.close()
    with pytest.raises(ValueError, match='scope'):
        source.audit_workbook(file, public, result, result, binding, plan, {})


def test_prepare_rejects_missing_actual_reference_before_any_output(monkeypatch, tmp_path):
    public = {'dimension_mode': 'production'}
    original = tmp_path / 'unit_stub.json'; original.write_text(json.dumps(public))
    monkeypatch.setattr(source.spec, 'load_spec', lambda value: value)
    called = []
    def no_actual(*args): called.append(True); raise ValueError('Actual independent prerequisite missing')
    monkeypatch.setattr(source, '_validate_reference', no_actual)
    output = ROOT / 'outputs/tmp/source_unit_missing_prerequisite'
    with pytest.raises(ValueError, match='prerequisite'):
        source.prepare(original, 'missing_reference', output)
    assert called == [True] and not output.exists()


def test_prepare_has_no_implicit_finance_emission_solver_or_engine():
    import ast, inspect
    tree = ast.parse(inspect.getsource(source.prepare))
    calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not any(any(x in name for x in ('simulate', 'recalculate', 'emit_workbook', 'solve_', 'execute_prepared')) for name in calls)
    text = (ROOT / 'scripts/build_linear_capital_source.py').read_text()
    assert "for index in (1, 2, 3)" in text
    assert "versions[1:]" in text
    assert "source_admission_inherited_from_engineering': False" in text


def test_references_reject_symlink_and_duplicate_json(tmp_path):
    p = tmp_path / 'record.json'; p.write_text('{"a":1,"a":2}')
    with pytest.raises(ValueError, match='Duplicate'): source.read(p)
    link = tmp_path / 'link.json'; link.symlink_to(p)
    with pytest.raises(ValueError, match='nonsymlink'): source.reference(link)


def test_complete_tiny_native_emitter_locators_match_two_independent_financial_results(tmp_path):
    from sheets_factory.workbook.linear_capital_portfolio import excel, candidate_a, ledger
    toy_loader = importlib.util.spec_from_file_location('linear_source_hand_toy_fixture', ROOT / 'tests/test_linear_capital_portfolio_ledger.py')
    toy = importlib.util.module_from_spec(toy_loader); toy_loader.loader.exec_module(toy)
    public = toy.fixture(projects=2, years=3, scenarios=2)
    plan = {'P001': 1, 'P002': 0}
    a, b = candidate_a.simulate(public, plan), ledger.simulate(public, plan)
    path = tmp_path / 'two_project_unit_fixture_not_source.xlsx'
    bindings = excel.emit_workbook(path, public, plan=plan, max_formulas=10000)
    expected = source.expected_values(public, a, b, bindings, plan)
    assert expected['formula_count'] == bindings['formula_count']
    assert expected['financial_locator_count'] == len(bindings['financial_bindings'])
    assert sum(row['formula'] is None for row in bindings['financial_bindings']) > 0
    _, policy = source.runtime(source.DEFAULT_PROFILE)
    literals, geometry = source.raw_geometry(path, public, bindings, expected, policy)
    assert geometry['truncated'] is False and geometry['physical_formula_count'] == bindings['formula_count']
    assert geometry['self_contained_native_inputs'] is True and literals
    # The unit fixture is deliberately uncached, not an actual audited source.
    report = source.audit_workbook(path, public, a, b, bindings, plan, literals)
    assert report['passed'] is False and report['mismatch_count'] > 0


def test_missing_required_financial_field_is_not_hidden_by_consistent_physical_bindings(tmp_path):
    from sheets_factory.workbook.linear_capital_portfolio import excel
    toy_loader = importlib.util.spec_from_file_location('linear_source_census_unit_fixture', ROOT / 'tests/test_linear_capital_portfolio_ledger.py')
    toy = importlib.util.module_from_spec(toy_loader); toy_loader.loader.exec_module(toy)
    public = toy.fixture(projects=1, years=2, scenarios=1)
    binding = excel.emit_workbook(tmp_path / 'tiny_native_field_census.xlsx', public, plan={'P001': 1}, max_formulas=10000)
    report = source.financial_locator_coverage(public, binding)
    assert report['required_distinct_fields'] == report['actual_distinct_fields']
    removed = next(r for r in binding['financial_bindings'] if r['expected_path'][-1:] == ['bank_interest'])
    binding['financial_bindings'] = [r for r in binding['financial_bindings'] if r['expected_path'] != removed['expected_path']]
    with pytest.raises(ValueError, match='field census'):
        source.financial_locator_coverage(public, binding)


def test_only_the_disclosed_input_completeness_cell_can_use_derived_expectations():
    public, plan, result, binding = fixture()
    binding['arithmetic_bindings'][-1]['cell'] = 'Z99'
    with pytest.raises(ValueError, match='unsupported'):
        source.expected_values(public, result, result, binding, plan)


def test_no_unknown_vintage_origin_or_constraint_field_can_be_used_as_zero():
    _, _, result, binding = fixture()
    vintage = deepcopy(binding['financial_bindings'][3]); vintage['origin_year'] = 3
    with pytest.raises(ValueError, match='identity'):
        source._financial_value(result, vintage)
    constraint = deepcopy(binding['financial_bindings'][2]); constraint['constraint_field'] = 'id'
    with pytest.raises(ValueError, match='constraint field'):
        source._financial_value(result, constraint)


@pytest.mark.parametrize('field,value', [('all_values_checked', False), ('all_physical_formulas_checked', 3),
    ('all_financial_locators_checked', 3), ('public_literals_checked', 0), ('native_error_count', 1),
    ('mismatch_count', 1), ('money_quantization_applied', True), ('differences_truncated', True),
    ('expected_A_sha256', '0'*64)])
def test_completed_audit_metadata_is_bound_to_all_actual_scopes_and_independent_results(tmp_path, field, value):
    # A synthetic receipt tests the validator only; this is not a cached workbook
    # and the test does not assert that financial audit or actual LO occurred.
    public, plan, result, binding = fixture()
    file = tmp_path / 'receipt_validator_only_not_a_workbook.bin'; file.write_bytes(b'unit validation artifact')
    literals = {('Inputs', 'A1'): source._typed(20)}
    report = {'kind': 'complete_linear_capital_native_workbook_A_B_audit', 'passed': True,
        'all_values_checked': True, 'audited_file': source.reference(file),
        'specification_sha256': source.spec.canonical_sha256(public), 'bindings_sha256': source.canonical(binding),
        'expected_A_sha256': source.canonical(result), 'expected_B_sha256': source.canonical(result),
        'all_physical_formulas_checked': 4, 'all_financial_locators_checked': 4,
        'all_expected_values_checked': 8, 'public_literals_checked': 1,
        'native_error_count': 0, 'mismatch_count': 0, 'native_errors': [], 'mismatches': [],
        'money_quantization_applied': False, 'differences_truncated': False}
    assert source.validate_audit(report, file, public, result, result, binding, literals)
    report[field] = value
    with pytest.raises(ValueError, match='complete independent'):
        source.validate_audit(report, file, public, result, result, binding, literals)


def test_readonly_source_admission_rejects_pending_before_any_parent_or_runtime_work(tmp_path, monkeypatch):
    path = tmp_path / 'pending_not_source.json'
    path.write_text(json.dumps({'kind': source.SOURCE_KIND, 'version': 1,
        'status': 'pending', 'source_financially_verified': False}))
    monkeypatch.setattr(source, 'validate_prepared', lambda *a: pytest.fail('Pending is not a completed source'))
    with pytest.raises(ValueError, match='completed actual'):
        source.validate_source(path)


def test_current_native_source_recipe_includes_every_used_financial_and_reference_dependency():
    recipe = source.recipes()
    assert str(ROOT / 'scripts/run_linear_capital_reference.py') in recipe
    assert str(ROOT / 'scripts/build_heterogeneous_source.py') in recipe
    for name in ('spec.py', 'candidate_a.py', 'ledger.py', 'finance_crosscheck.py', 'model_a.py',
        'model_b.py', 'optimization_runtime.py', 'excel.py'):
        assert str(ROOT / 'src/sheets_factory/workbook/linear_capital_portfolio' / name) in recipe
    assert str(ROOT / 'src/sheets_factory/workbook/resource_engine.py') in recipe
    assert str(ROOT / 'src/sheets_factory/task_adapters/heterogeneous_formula_identity.py') in recipe
