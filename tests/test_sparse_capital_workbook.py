"""Offline test workbooks only. No source producer, search, LO, model or fake cache."""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

from sheets_factory.workbook.capital_allocation import excel as arithmetic
from sheets_factory.workbook.capital_allocation_scaled import excel as original_excel
from sheets_factory.workbook.capital_allocation_scaled import validate as original_validate
from sheets_factory.workbook.capital_allocation_scaled import spec as original_spec
from sheets_factory.workbook.capital_allocation_sparse import excel, ledger, spec, validate

ROOT = Path(__file__).resolve().parents[1]


def helper(name, filename):
    definition = importlib.util.spec_from_file_location(name, ROOT / 'tests' / filename)
    module = importlib.util.module_from_spec(definition); definition.loader.exec_module(module)
    return module


financial = helper('_sparse_workbook_fixed_plan_fixture', 'test_sparse_capital_spec_ledger.py')
formula = helper('_sparse_workbook_binary64_test_parser', 'test_capital_allocation_excel.py')


def empty_book():
    result = openpyxl.Workbook(); result.remove(result.active); return result


def path_value(value, path):
    for part in path: value = value[part]
    return value


def ref(item):
    return validate._reference(item['sheet'], item['cell'])


@pytest.fixture(scope='module', params=[40, 48, 56])
def emitted(request, tmp_path_factory):
    n = request.param
    public = financial.financed(financial.specification(n))
    public['tax_rate_p12'] = spec.SCALE // 4
    choices = financial.plan(public, f'P{n:02d}')
    forward = ledger.simulate(public, choices)
    book = empty_book()
    bindings = excel.emit_capital_allocation_workbook(book, public, choices)
    expected = validate.expected_cells(public, choices, forward, bindings)
    directory = tmp_path_factory.mktemp('TEST_uncalculated_sparse_' + str(n))
    filename = directory / ('TEST_uncalculated_n' + str(n) + '.xlsx')
    book.save(filename)
    result = SimpleNamespace(n=n, public=public, choices=choices, forward=forward,
        book=book, bindings=bindings, expected=expected, path=filename)
    yield result
    book.close()


def test_full_dynamic_field_counts_sheets_and_physical_formulas_have_no_truncation(emitted):
    n, book, binding = emitted.n, emitted.book, emitted.bindings
    assert len(book.sheetnames) == 15 and book.sheetnames == binding['sheet_names']
    assert len(binding['financial_bindings']) == 540 * n + 9311
    assert len(binding['decision_bindings']) == n
    assert len(binding['arithmetic_bindings']) == 1440 * n + 8772
    assert binding['formula_count'] == 1981 * n + 18083
    physical = {(sheet.title, cell.coordinate) for sheet in book for cell in sheet._cells.values() if cell.data_type == 'f'}
    bound = binding['financial_bindings'] + binding['decision_bindings'] + binding['arithmetic_bindings']
    assert len(physical) == len(bound) == binding['formula_count']
    assert physical == {(item['sheet'], item['cell']) for item in bound}
    assert len(emitted.expected) == len(physical) + sum(type(path_value(emitted.public, item['path'])) is int
                                                  for item in binding['input_bindings'])
    assert binding['gold_optimizer_proof_checked_by_emitter'] is False
    assert binding['independent_financial_audit_performed'] is False
    assert binding['source_or_quality_or_difficulty_certified'] is False
    assert binding['optimisation_performed'] is False
    assert binding['arithmetic_support_values_are_protected'] is False
    assert binding['task_input_requires_actual_recalculation_and_audit'] is True
    assert binding['complete_required_D_includes_changed_arithmetic_helpers'] is True


def test_all_fifty_six_boundary_financial_paths_match_independent_fixed_plan_and_binary64_text(emitted):
    values = formula.evaluate_forward_formula_text(emitted.book)
    for binding in emitted.bindings['financial_bindings']:
        independent = path_value(emitted.forward, binding['expected_path'])
        value = int(independent) if type(independent) is bool else '' if independent is None else independent
        assert values[ref(binding)] == value, binding['expected_path']
    for binding in emitted.bindings['arithmetic_bindings']:
        expected = emitted.expected[ref(binding)]
        assert type(expected) is int and abs(expected) < 2**53
        assert values[ref(binding)] == expected, binding['label']
        assert binding['target_eligible'] is False and binding['value_protected'] is False
    for sid in spec.SCENARIO_IDS:
        refs = emitted.bindings['project_refs'][sid]
        assert len(refs) == emitted.n and len(refs[f'P{emitted.n:02d}']) == 20
        assert values[refs['P01'][2024]['capex']] == 100
        assert values[refs[f'P{emitted.n:02d}'][2024]['capex']] == 180
        assert values[emitted.bindings['annual_refs'][sid][2024]['capex']] == 180
    financial.assert_conserved(emitted.forward)


def test_all_input_literals_public_schema_and_declared_cell_limits_are_complete(emitted):
    bindings, book = emitted.bindings, emitted.book
    assert [r['project_id'] for r in bindings['decision_bindings']] == list(spec.project_ids(emitted.n))
    assert all(book[r['sheet']][r['cell']].value == '=' + str(emitted.choices[r['project_id']])
               for r in bindings['decision_bindings'])
    assert all(book[r['sheet']][r['cell']].value == path_value(emitted.public, r['path'])
               for r in bindings['input_bindings'])
    public = json.loads(''.join(book[r['sheet']][r['cell']].value for r in bindings['public_spec_chunks']))
    assert public == emitted.public and all(len(book[r['sheet']][r['cell']].value) <= 30000 for r in bindings['public_spec_chunks'])
    assert bindings['public_rules'] == list(excel.PUBLIC_RULES)
    assert 'eighteen' not in ' '.join(bindings['public_rules'])
    for sid in spec.SCENARIO_IDS:
        assert str(emitted.n) in book[sid + ' Projects']['A1'].value and 'UNWEIGHTED' in book[sid + ' Projects']['A1'].value
    for sheet in book:
        assert sheet.max_row <= 1048576 and sheet.max_column <= 16384
        assert all(len(cell.value) <= 8192 for cell in sheet._cells.values() if cell.data_type == 'f')
    assert book['Capital Summary']['B2'].value == 'Feasible flag: 1 yes, 0 no'
    assert 'Diagnostic LP NPV' in book['Capital Summary']['C2'].value
    assert emitted.bindings['emitter_recipe']['sparse_dimension_template']['financial_AST_changes'] == 0


def test_serialized_fixture_has_no_invented_formula_caches_or_gold_numeric_mask(emitted):
    cached = openpyxl.load_workbook(emitted.path, data_only=True, read_only=True)
    try:
        # The ZIP stores only uncalculated test formulas. Never insert fake v caches.
        for name in ('Investment Plan', 'S01 Annual', 'Exact Arithmetic', 'Capital Summary'):
            assert all(cell.value is None for row in cached[name].iter_rows(min_row=3, min_col=2)
                       for column, cell in enumerate(row, start=2) if column > (2 if name == 'S01 Annual' else 1))
    finally: cached.close()
    assert all(len(str(mask)) <= 1 for mask in emitted.choices.values())
    assert 'mask' not in emitted.bindings['public_spec']


def test_full_expected_mapping_rejects_missing_duplicate_or_protected_targets(emitted):
    binding = deepcopy(emitted.bindings)
    binding['financial_bindings'].pop()
    with pytest.raises(ValueError, match='Complete independent financial'):
        validate.expected_cells(emitted.public, emitted.choices, emitted.forward, binding)
    binding = deepcopy(emitted.bindings)
    binding['financial_bindings'].append(binding['financial_bindings'][0])
    with pytest.raises(ValueError, match='Complete independent financial'):
        validate.expected_cells(emitted.public, emitted.choices, emitted.forward, binding)
    binding = deepcopy(emitted.bindings); binding['arithmetic_bindings'][0]['value_protected'] = True
    with pytest.raises(ValueError, match='Provided exact arithmetic'):
        validate.expected_cells(emitted.public, emitted.choices, emitted.forward, binding)


def test_unrecalculated_test_file_is_not_a_passing_actual_value_audit(emitted):
    if emitted.n != 40: return
    report = validate.audit_capital_allocation_workbook(emitted.path, emitted.public,
        emitted.choices, emitted.forward, emitted.bindings)
    assert report['passed'] is False and report['mismatches']
    assert report['formula_count'] == report['checked_cells'] == 1981 * 40 + 18083
    assert report['all_formula_cells_independently_covered'] is True
    assert report['control_mismatches'] == [] and report['optimality_or_uniqueness_certified'] is False


def test_complete_template_AST_and_original_module_globals_remain_unchanged():
    for current, previous in ((excel, original_excel), (validate, original_validate)):
        raw = Path(previous.__file__).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == current.DIMENSION_TEMPLATE_SHA256
        assert ast.dump(current.dimension_template_ast(), include_attributes=False) == ast.dump(ast.parse(raw.decode()), include_attributes=False)
        assert current.dimension_template_binding()['new_namespace'] == 'sheets_factory.workbook.capital_allocation_sparse'
        assert current.dimension_template_binding()['original_module_globals_changed'] is False
    assert excel._dimension_original_emit.__globals__ is vars(excel)
    assert original_excel.emit_capital_allocation_workbook.__globals__ is vars(original_excel)
    assert validate._dimension_original_expected.__globals__ is vars(validate)
    assert original_validate.expected_cells.__globals__ is vars(original_validate)
    assert excel.ExactArithmetic is arithmetic.ExactArithmetic and excel.expression_formula is arithmetic.expression_formula
    assert original_spec.PROJECT_COUNTS == (18, 26, 28, 30)
    assert excel.project_ids is spec.project_ids


@pytest.mark.parametrize('module', [excel, validate])
def test_template_drift_cannot_be_used_after_import(tmp_path, monkeypatch, module):
    wrong = tmp_path / 'changed_template.py'
    wrong.write_bytes(module.DIMENSION_TEMPLATE_PATH.read_bytes() + b'\n# changed fixture, never the original\n')
    monkeypatch.setattr(module, 'DIMENSION_TEMPLATE_PATH', wrong)
    with pytest.raises(ValueError, match='frozen dynamic financial'):
        module.dimension_template_binding()


def test_blank_decision_template_and_invalid_plan_do_not_embed_a_selected_plan(tmp_path):
    public = financial.specification(40); book = empty_book()
    for wrong in ({}, {**financial.plan(public), 'P40': True}, dict.fromkeys(original_spec.project_ids(30), 0)):
        with pytest.raises(ValueError, match='complete common integer'):
            excel.emit_capital_allocation_workbook(book, public, wrong)
        assert book.sheetnames == []
    bindings = excel.emit_capital_allocation_workbook(book, public)
    assert bindings['formula_count'] == 1980 * 40 + 18083
    assert bindings['gold_plan_supplied'] is False
    assert all(book[r['sheet']][r['cell']].value is None for r in bindings['decision_bindings'])
    book.close()


def test_largest_dimension_high_primitive_products_stay_exact_and_bounded():
    public = financial.specification(56)
    public.update(opening_cash_pence=10**11, lp_commitment_pence=10**11, facility_limit_pence=10**11,
                  tax_rate_p12=spec.SCALE, advance_rate_p12=spec.SCALE)
    for project in public['projects']:
        project.update(acquisition_cost_pence=10**9, depreciation_years=20, sale_year=2043,
            annual_revenue_pence={str(year): 0 if year == 2024 else 10**9 for year in spec.YEARS},
            annual_opex_pence={str(year): 0 if year == 2024 else 10**9 for year in spec.YEARS},
            sale_proceeds_pence=10**9)
    for scenario in public['scenarios']:
        for field in ('revenue_factors_p12', 'opex_factors_p12', 'nav_factors_p12', 'sale_factors_p12'):
            scenario[field] = financial.annual(3 * spec.SCALE)
        scenario['bank_rates_p12'] = financial.annual(spec.SCALE)
    choices = {p['id']: 1 for p in public['projects']}
    forward = ledger.simulate(public, choices)
    book = empty_book(); bindings = excel.emit_capital_allocation_workbook(book, public, choices)
    expected = validate.expected_cells(public, choices, forward, bindings)
    helpers = [expected[ref(r)] for r in bindings['arithmetic_bindings']]
    assert all(type(value) is int and abs(value) < 2**53 for value in helpers)
    assert max(helpers) == 3 * 10**15
    assert len(helpers) == 89412 and bindings['formula_count'] == 129019
    financial.assert_conserved(forward); book.close()
