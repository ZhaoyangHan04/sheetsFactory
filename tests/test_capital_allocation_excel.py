"""Offline integer-expression calibration; these tests make no LO claims."""
import ast
from collections import defaultdict, deque
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import math
import random
import re
import sys
from types import SimpleNamespace

import openpyxl
import pytest

from sheets_factory.workbook.capital_allocation.excel import ExactArithmetic, SCALE, expression_formula, emit_capital_allocation_workbook
from sheets_factory.workbook.capital_allocation.validate import evaluate_integer_expression, expected_cells, audit_capital_allocation_workbook
from sheets_factory.workbook.capital_allocation.spec import PROJECT_IDS, SCENARIO_IDS, YEARS, RAW_ANCESTORS
from sheets_factory.workbook.capital_allocation.ledger import simulate
from sheets_factory.task_adapters.public_workbook_scope import reference, write_new

ROOT = Path(__file__).resolve().parents[1]
_entry_spec = importlib.util.spec_from_file_location('_capital_allocation_source_test', ROOT / 'scripts/build_capital_allocation_source.py')
builder = importlib.util.module_from_spec(_entry_spec); _entry_spec.loader.exec_module(builder)


class FloatConstants(ast.NodeTransformer):
    def visit_Constant(self, node):
        return ast.copy_location(ast.Constant(float(node.value)), node) if type(node.value) in (int, float) else node

    def visit_Call(self, node):
        node = self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == 'IF':
            return ast.copy_location(ast.IfExp(node.args[0], node.args[1], node.args[2]), node)
        return node


def evaluate_float_formulas(book, inputs):
    """Evaluate the emitted elementary formulas with binary64 operations.

    This checks generated formula text independently of the expression audit;
    it is neither a LibreOffice receipt nor a source verification.
    """
    values = dict(inputs)
    pattern = re.compile(r"'(?:[^']|'')+'!\$?[A-Z]{1,3}\$?[1-9][0-9]*")
    functions = {'ABS': abs, 'INT': math.floor, 'MOD': lambda a, b: a % b,
                 'IF': lambda predicate, yes, no: yes if predicate else no, 'MIN': min, 'MAX': max}
    for row in book['Arithmetic'].iter_rows(min_row=3):
        cell = row[1]
        if cell.value is None: continue
        formula = pattern.sub(lambda match: repr(float(values[match.group()])), cell.value[1:])
        expression = FloatConstants().visit(ast.parse(formula, mode='eval'))
        ast.fix_missing_locations(expression)
        value = eval(compile(expression, '<offline arithmetic calibration>', 'eval'), {'__builtins__': {}}, functions)
        values["'Arithmetic'!$B$" + str(cell.row)] = value
    return values


def build_math():
    book = openpyxl.Workbook(); book.active.title = 'Inputs'
    return book, ExactArithmetic(book.create_sheet('Arithmetic'))


def rounded_division(numerator, denominator):
    return (1 if numerator >= 0 else -1) * ((abs(numerator) + denominator // 2) // denominator)


@pytest.mark.parametrize('amount,factor', [
    (25_000_000_001, 500_000_000_000), (-25_000_000_001, 500_000_000_000),
    (99_999_999_999_999, SCALE), (1, SCALE // 2 - 1), (1, SCALE // 2),
    (-1, SCALE // 2 + 1), (0, 3 * SCALE), (999_999_999, 2_999_999_999_999)])
def test_double_formula_products_match_exact_integer_half_up(amount, factor):
    book, arithmetic = build_math()
    values = {"'Inputs'!$A$1": amount, "'Inputs'!$B$1": factor}
    target = arithmetic.round_product(tuple(values), 2, 'posted_revenue')
    observed = evaluate_float_formulas(book, values)[target]
    assert observed == rounded_division(amount * factor, SCALE)
    independent = dict(values)
    for item in arithmetic.bindings:
        value = evaluate_integer_expression(item['expression'], independent)
        assert type(value) is int
        independent["'Arithmetic'!$B$" + item['cell'][1:]] = value
    assert independent[target] == observed
    book.close()


def test_three_factor_collateral_has_no_intermediate_rounding():
    randomizer = random.Random(2043)
    cases = [(13, SCALE // 2, SCALE // 2), (99_999_999_999, SCALE - 1, SCALE - 1)]
    cases += [(randomizer.randrange(10**11), randomizer.randrange(SCALE + 1), randomizer.randrange(SCALE + 1))
              for _ in range(20)]
    for amount, advance, remaining_haircut in cases:
        book, arithmetic = build_math()
        values = dict(zip(("'Inputs'!$A$1", "'Inputs'!$B$1", "'Inputs'!$C$1"),
                          (amount, advance, remaining_haircut)))
        target = arithmetic.round_product(tuple(values), 4, 'borrowing_base')
        observed = evaluate_float_formulas(book, values)[target]
        assert observed == rounded_division(amount * advance * remaining_haircut, SCALE**2)
        book.close()


@pytest.mark.parametrize('cashflows,factors', [
    ([1, 1], [SCALE // 2, SCALE // 2]), ([-1, -1], [SCALE // 2, SCALE // 2]),
    ([10, -9], [SCALE // 2 - 1, SCALE // 2 + 1]),
    ([-7, 9, -1], [SCALE, SCALE // 2, SCALE // 3]),
    ([99_999_999_999, -87_654_321_999], [SCALE - 1, SCALE // 3])])
def test_present_value_rounds_only_once_after_signed_sum(cashflows, factors):
    book, arithmetic = build_math(); values = {}
    cash_refs, factor_refs = [], []
    for index, (cash, factor) in enumerate(zip(cashflows, factors), 1):
        cash_ref, factor_ref = "'Inputs'!$A$" + str(index), "'Inputs'!$B$" + str(index)
        values[cash_ref], values[factor_ref] = cash, factor
        cash_refs.append(cash_ref); factor_refs.append(factor_ref)
    target = arithmetic.sum_discounted(cash_refs, factor_refs, 'LP_NPV')
    expected = rounded_division(sum(cash * factor for cash, factor in zip(cashflows, factors)), SCALE)
    assert evaluate_float_formulas(book, values)[target] == expected
    book.close()


def test_time_zero_cash_is_inside_signed_final_half_tie_rounding():
    book, arithmetic = build_math()
    values = {"'Inputs'!$A$1": 1, "'Inputs'!$B$1": SCALE // 2, "'Inputs'!$C$1": 1}
    target = arithmetic.sum_discounted(["'Inputs'!$A$1"], ["'Inputs'!$B$1"], 'LP_NPV', opening="'Inputs'!$C$1")
    assert evaluate_float_formulas(book, values)[target] == -1
    assert rounded_division(SCALE // 2 - SCALE, SCALE) == -1
    book.close()


def test_arithmetic_refuses_dynamic_expressions_and_boolean_literals():
    for expression in (True, 'A1', "'Inputs'!A1:A9", ('indirect', "'Inputs'!A1"), ('if', 1, 2)):
        with pytest.raises(ValueError): expression_formula(expression)
    with pytest.raises(ValueError): evaluate_integer_expression("'Inputs'!$A$1", {"'Inputs'!$A$1": True})


def test_provided_arithmetic_never_selects_or_masks_a_plan():
    book, arithmetic = build_math()
    arithmetic.round_product(("'Inputs'!$A$1", "'Inputs'!$B$1"), 2, 'cash_interest')
    assert all(item['target_eligible'] is False and item['kind'] == 'integer' for item in arithmetic.bindings)
    assert not any(word in str(item).lower() for item in arithmetic.bindings for word in ('solver', 'winner', 'optimal'))
    book.close()


def specification():
    annual = lambda value: {str(year): value for year in YEARS}
    return {'schema_version': 1, 'currency': 'GBP', 'monetary_unit': 'pence', 'years': list(YEARS),
        'opening_cash_pence': 100, 'minimum_cash_pence': 10, 'lp_commitment_pence': 1000,
        'facility_limit_pence': 1000, 'advance_rate_p12': SCALE, 'tax_rate_p12': SCALE // 2,
        'tax_loss_carry_years': 2, 'discount_factors_p12': annual(SCALE),
        'projects': [{'id': identifier, 'commission_year': 2024, 'sale_year': 2029,
            'acquisition_cost_pence': 180, 'depreciation_years': 3,
            'annual_revenue_pence': {**annual(0), '2027': 80, '2029': 100},
            'annual_opex_pence': {**annual(0), '2025': 50, '2026': 1}, 'sale_proceeds_pence': 150}
            for identifier in PROJECT_IDS],
        'scenarios': [{'id': identifier, 'revenue_factors_p12': annual(SCALE),
            'opex_factors_p12': annual(SCALE), 'nav_factors_p12': annual(SCALE),
            'sale_factors_p12': annual(SCALE), 'bank_rates_p12': annual(SCALE // 10),
            'haircuts_p12': {**annual(0), '2026': SCALE * 9 // 10}} for identifier in SCENARIO_IDS],
        'provenance': {'kind': 'synthetic_capital_allocation_extension', 'raw_ancestors': deepcopy(RAW_ANCESTORS)}}


def evaluate_forward_formula_text(book):
    """Topological binary64 toy calibration of every emitted formula, not LO."""
    pattern = re.compile(r"'(?:[^']|'')+'!\$?[A-Z]{1,3}\$?[1-9][0-9]*")
    values, formulas, reverse, pending = {}, {}, defaultdict(list), {}
    for sheet in book:
        for cell in sheet._cells.values():
            key = "'" + sheet.title + "'!" + re.sub(r'([A-Z]+)([0-9]+)', r'$\1$\2', cell.coordinate)
            if cell.data_type == 'f': formulas[key] = cell.value
            else: values[key] = cell.value
    for key, formula in formulas.items():
        dependencies = set(pattern.findall(formula)) & formulas.keys()
        pending[key] = len(dependencies)
        for dependency in dependencies: reverse[dependency].append(key)
    queue = deque(key for key in formulas if pending[key] == 0)
    functions = {'ABS': abs, 'INT': math.floor, 'MOD': lambda a, b: a % b, 'MIN': min, 'MAX': max,
        'AND': lambda *args: all(args), 'OR': lambda *args: any(args),
        'ROUND': lambda amount, places: math.floor(amount + .5) if amount >= 0 else -math.floor(-amount + .5)}
    done = 0
    while queue:
        key = queue.popleft()
        formula = pattern.sub(lambda match: repr(float(values[match.group()])) if type(values[match.group()]) in (int, float)
                              else repr(values[match.group()]), formulas[key][1:])
        formula = re.sub(r'(?<![<>=])=(?!=)', '==', formula)
        tree = FloatConstants().visit(ast.parse(formula, mode='eval')); ast.fix_missing_locations(tree)
        values[key] = eval(compile(tree, '<offline complete forward calibration>', 'eval'), {'__builtins__': {}}, functions)
        done += 1
        for child in reverse[key]:
            pending[child] -= 1
            if pending[child] == 0: queue.append(child)
    assert done == len(formulas), 'The emitted forward accounting contains a circular or unresolved formula'
    return values


def test_complete_forward_formulas_match_independent_journal_fifo_and_terminal(tmp_path):
    spec = specification(); plan = {identity: int(identity == 'P01') for identity in PROJECT_IDS}
    book = openpyxl.Workbook(); book.remove(book.active)
    bindings = emit_capital_allocation_workbook(book, spec, plan)
    ledger = simulate(spec, plan)
    expected = expected_cells(spec, plan, ledger, bindings)
    actual = evaluate_forward_formula_text(book)
    for item in bindings['financial_bindings']:
        key = "'" + item['sheet'] + "'!" + re.sub(r'([A-Z]+)([0-9]+)', r'$\1$\2', item['cell'])
        assert actual[key] == ('' if expected[key] is None else expected[key]), (item['expected_path'], actual[key], expected[key])
    first = ledger['scenarios']['S01']['annual']
    assert first[0]['lp_call'] == 90 and first[1]['bank_draw'] == 50
    assert first[2]['mandatory_margin'] > 0
    assert first[-1]['bank_close'] == first[-1]['cash_close'] == first[-1]['project_book_value'] == 0
    assert any(row['used'] > 0 for row in ledger['scenarios']['S01']['tax_vintages'])
    assert any(row['expired'] > 0 for row in ledger['scenarios']['S01']['tax_vintages'])
    assert len(bindings['decision_bindings']) == 18 and len(bindings['annual_refs']) == 3
    assert bindings['arithmetic_support_values_are_protected'] is False
    assert bindings['plan_dependent_caches_must_be_cleared_before_task_input'] is True
    assert bindings['complete_required_D_includes_changed_arithmetic_helpers'] is True
    assert any(item['plan_dependent'] for item in bindings['arithmetic_bindings'])
    assert any(not item['plan_dependent'] for item in bindings['arithmetic_bindings'])
    assert all(item['value_protected'] is False for item in bindings['arithmetic_bindings'])
    path = tmp_path / 'uncalculated.xlsx'; book.save(path); book.close()
    # An offline expression calibration cannot masquerade as actual Calc caches.
    audit = audit_capital_allocation_workbook(path, spec, plan, ledger, bindings)
    assert audit['all_formula_cells_independently_covered'] and not audit['passed'] and audit['mismatches']
    assert audit['optimality_or_uniqueness_certified'] is False


def test_template_decisions_are_blank_and_contain_no_winner_or_formula_caches(tmp_path):
    book = openpyxl.Workbook(); book.remove(book.active)
    bindings = emit_capital_allocation_workbook(book, specification())
    assert all(book[item['sheet']][item['cell']].value is None for item in bindings['decision_bindings'])
    assert bindings['gold_plan_supplied'] is False and bindings['optimisation_performed'] is False
    path = tmp_path / 'public_template.xlsx'; book.save(path); book.close()
    cached = openpyxl.load_workbook(path, data_only=True)
    assert all(cached[item['sheet']][item['cell']].value is None
               for item in bindings['financial_bindings'] + bindings['arithmetic_bindings'])
    cached.close()


@pytest.mark.parametrize('amount,factor', [(10**9, 3 * SCALE), (999999999, 2999999999999), (1, SCALE // 2)])
def test_compact_project_posting_keeps_full_integer_precision(amount, factor):
    book, arithmetic = build_math(); inputs = {"'Inputs'!$A$1": amount, "'Inputs'!$B$1": factor}
    target = arithmetic.round_project_factor(*inputs, 'project_revenue')
    assert len(arithmetic.bindings) == 6
    assert evaluate_float_formulas(book, inputs)[target] == rounded_division(amount * factor, SCALE)
    book.close()


def test_default_source_preparation_never_searches_or_recalculates(tmp_path, monkeypatch):
    spec = specification(); spec_ref = write_new(tmp_path / 'spec.json', spec)
    ancestors = {}
    for name in RAW_ANCESTORS:
        path = tmp_path / (name + '.raw'); path.write_bytes(('Offline ancestry fixture ' + name).encode())
        ancestors[name] = path
    # Invalid real ancestry must fail before creating an output directory.
    with pytest.raises(ValueError, match='immutable original hash'):
        builder.prepare(spec_ref['path'], tmp_path / 'rejected', ancestors)
    assert not (tmp_path / 'rejected').exists()
    # Substitute only the file-authentication boundary for this synthetic test.
    monkeypatch.setattr(builder, 'RAW_ANCESTORS', {key: reference(path)['sha256'] for key, path in ancestors.items()})
    recipe = {str(Path(builder.__file__).resolve()): reference(builder.__file__)['sha256']}
    monkeypatch.setattr(builder, 'recipes', lambda: recipe)
    monkeypatch.setattr(builder, 'LibreOfficeEngine', lambda *a, **kw: pytest.fail('No actual LO is permitted in preparation'))
    monkeypatch.setattr(builder, 'simulate', lambda *a: pytest.fail('Preparation must not select or replay a winning plan'))
    output = tmp_path / 'prepared'
    record = builder.prepare(spec_ref['path'], output, ancestors)
    frozen, _ = builder.validate_prepared(output)
    assert reference(output / 'preparation.json') == record
    assert frozen['actual_LO_recalculations'] == frozen['actual_enumerated_plans'] == frozen['model_calls'] == 0
    assert frozen['winning_plan_written'] is False
    book = openpyxl.load_workbook(frozen['public_template']['path'])
    assert all(book['Investment Plan'].cell(row, 2).value is None for row in range(3, 21))
    book.close()
    assert not (output / 'seed_manifest.json').exists()


def test_source_cli_does_not_implicitly_execute(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, 'validate_prepared', lambda path: ({}, {}))
    monkeypatch.setattr(builder, 'execute_prepared', lambda *a: pytest.fail('Unexpected actual execution'))
    assert builder.main(['--prepared', str(tmp_path)]) == 0
    with pytest.raises(ValueError, match='Prepare first'):
        builder.main(['--spec', str(tmp_path / 'spec'), '--output', str(tmp_path / 'new'), '--run'])
    with pytest.raises(ValueError, match='independent enumeration'):
        builder.main(['--prepared', str(tmp_path), '--run', '--certificate', str(tmp_path / 'cpp.json')])


@pytest.mark.parametrize('changed', ['full_enumeration', 'toy_only', 'plan_count', 'scenario_year_evaluations', 'gap_pence'])
def test_source_rejects_partial_or_toy_optimum_receipts_before_any_goal(tmp_path, changed):
    receipt = {'passed': True, 'full_enumeration': True, 'toy_only': False, 'unique_best': True,
        'plan_count': 2**18, 'scenario_year_evaluations': 2**18 * 3 * 20, 'gap_pence': 1, 'objective_pence': 0}
    receipt[changed] = {'full_enumeration': False, 'toy_only': True, 'plan_count': True,
        'scenario_year_evaluations': 60, 'gap_pence': 0}[changed]
    record = write_new(tmp_path / 'verification.json', receipt)
    with pytest.raises(ValueError, match='complete independent'):
        builder.validate_independent_optimum(specification(), {}, record['path'])


def test_failed_actual_engine_attempt_is_persisted_before_invocation(tmp_path, monkeypatch):
    """A throwing fake engine checks receipts; this test performs zero LO calls."""
    spec = specification(); plan = {identity: int(identity == 'P01') for identity in PROJECT_IDS}
    ledger = simulate(spec, plan)
    certificate = write_new(tmp_path / 'certificate.json', {'offline': 'stubbed proof boundary'})
    proof = {'unique_best': True, 'plan_count': 2**18, 'gap_pence': 1,
             'best_plan': plan, 'objective_pence': ledger['objective_pence']}
    monkeypatch.setitem(sys.modules, 'sheets_factory.workbook.capital_allocation.search',
                        SimpleNamespace(validate_certificate=lambda *a: proof))
    monkeypatch.setattr(builder, 'validate_independent_optimum', lambda *a: certificate)
    def emit(book, spec, plan): book.create_sheet('Offline Engine Failure'); return {'fixture': True}
    monkeypatch.setattr(builder, 'emit_capital_allocation_workbook', emit)
    attempt = tmp_path / 'attempt'; attempt.mkdir()
    events = []
    audit = SimpleNamespace(task=lambda *a, **kw: None, record=lambda *a: 1,
        update_record=lambda *a, **kw: None, emit=lambda *a, **kw: events.append((a, kw)))
    class FailingEngine:
        def __init__(self, *a): pass
        def ensure_image(self): return builder.IMAGE_ID
        def metadata(self): return {'image_id': builder.IMAGE_ID, 'network': 'none'}
        def recalculate(self, source, destination):
            record = json.loads((attempt / 'engine_call1_started.json').read_bytes())
            assert record['completed'] is False and record['input'] == reference(source)
            raise RuntimeError('deliberate offline engine failure')
    monkeypatch.setattr(builder, 'LibreOfficeEngine', FailingEngine)
    with pytest.raises(RuntimeError, match='deliberate offline'):
        builder._execute_prepared(tmp_path, certificate['path'], certificate['path'], {}, spec, attempt, audit)
    terminal = json.loads((attempt / 'engine_call1_terminal.json').read_bytes())
    receipt = json.loads((attempt / 'terminal.json').read_bytes())
    assert terminal['completed'] is False and terminal['exception_type'] == 'RuntimeError'
    assert terminal['seconds'] >= 0 and len(receipt['calls']) == 1
    assert receipt['calls'][0]['completed'] is False
    assert any(event[0][0] == 'source.phase.failed' for event in events)


def test_actual_run_cleanup_releases_lease_even_when_export_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(builder, 'validate_prepared', lambda *a: ({}, {}))
    released, closed, stopped = [], [], []
    lease = SimpleNamespace(acquire=lambda: lease, release=lambda: released.append(True))
    monkeypatch.setattr(builder, 'ProducerLease', lambda *a: lease)
    audit = SimpleNamespace(update_run=lambda **kw: None, snapshot=lambda: {}, events=lambda: [],
        export=lambda: (_ for _ in ()).throw(RuntimeError('offline export failure')),
        db=SimpleNamespace(close=lambda: closed.append(True)), task=lambda *a, **kw: None)
    monkeypatch.setattr(builder, 'AuditStore', lambda *a: audit)
    server = SimpleNamespace(start=lambda: 'http://offline.test/', stop=lambda: stopped.append(True))
    monkeypatch.setattr(builder, 'DashboardServer', lambda *a, **kw: server)
    monkeypatch.setattr(builder, '_execute_prepared', lambda *a: {'offline': True})
    with pytest.raises(RuntimeError, match='offline export failure'):
        builder.execute_prepared(tmp_path, tmp_path / 'not-read', tmp_path / 'not-read')
    assert released == closed == stopped == [True]
