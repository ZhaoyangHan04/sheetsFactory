"""Two-entity three-month formula tests. No production workbook or LO calls."""
import ast
from copy import deepcopy
import importlib.util
import json
import math
from pathlib import Path
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import openpyxl
import pytest

from sheets_factory.workbook.entity_group import excel
from sheets_factory.workbook.entity_group.ledger import simulate
from sheets_factory.workbook.entity_group.validate import audit_entity_group_workbook, expected_values, evaluate_expression, formula_signature
from sheets_factory.workbook.entity_group.spec import SCALE

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('_group_hand_fixtures', ROOT / 'tests/test_entity_group_ledger.py')
hand = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(hand)


def test_formula_identity_allows_only_exact_number_token_spelling_changes():
    assert formula_signature('=A1*1000000000000000000') == formula_signature('=A1*1E+018')
    assert formula_signature('=A1*1000000000000000001') != formula_signature('=A1*1E+018')
    assert formula_signature('=A1*1000000000000000000') != formula_signature('=A2*1E+018')
    assert formula_signature('=A1*1000000000000000000') != formula_signature('=A1+1E+018')


def emitted(spec=None, maximum=1_000_000):
    spec = hand.specification() if spec is None else spec
    book = openpyxl.Workbook(); book.remove(book.active)
    binding = excel.emit_entity_group_workbook(book, spec, max_formulas=maximum)
    return spec, book, binding


class Floats(ast.NodeTransformer):
    def visit_Constant(self, node):
        return ast.copy_location(ast.Constant(float(node.value)), node) if type(node.value) is int else node

    def visit_Call(self, node):
        node = self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == 'IF':
            return ast.copy_location(ast.IfExp(node.args[0], node.args[1], node.args[2]), node)
        return node


def actual_formula_value(formula, values):
    """Binary64 calibration of the emitted text, independent of the exact AST.

    This evaluator is a unit-test tool, not an actual spreadsheet runtime.
    """
    refs = re.compile(r"'(?:[^']|'')+'!\$[A-Z]+\$[1-9][0-9]*")
    formula = refs.sub(lambda match: repr(float(values[match.group()])) if type(values[match.group()]) is int else repr(values[match.group()]), formula[1:])
    formula = re.sub(r'(?<![<>=!])=(?!=)', '==', formula.replace('<>', '!='))
    tree = Floats().visit(ast.parse(formula, mode='eval')); ast.fix_missing_locations(tree)
    environment = {'ABS': abs, 'INT': math.floor, 'MOD': lambda a, b: a % b,
        'MIN': min, 'MAX': max, 'AND': lambda *a: all(a), 'OR': lambda *a: any(a),
        'ROUND': lambda value, digits: math.copysign(math.floor(abs(value) + .5), value)}
    return eval(compile(tree, '<binary64 static accounting>', 'eval'), {'__builtins__': {}}, environment)


def calibrate(spec, binding):
    checked = expected_values(spec, simulate(spec), binding)
    values = {excel._ref(item['sheet'], item['cell']): int(item['value']) if type(item['value']) is bool else item['value']
        for item in binding['input_bindings']}
    for item in binding['formula_bindings']:
        actual = actual_formula_value(item['formula'], values)
        expected = checked['values'][excel._ref(item['sheet'], item['cell'])]
        assert actual == expected, (item['label'], actual, expected)
        values[excel._ref(item['sheet'], item['cell'])] = actual
    return checked


@pytest.mark.parametrize('variant', ['bilateral_FIFO', 'FX_contention', 'FX_margin', 'cure', 'future_event', 'March_boundary', 'real_funding_gap'])
def test_complete_independent_expression_and_binary64_formula_text_agree_on_hand_cases(variant):
    spec = hand.cross_currency_spec() if variant.startswith('FX') else hand.specification()
    if variant == 'FX_margin':
        for term in spec['bank_terms']: term['maturity_month'] = '2024-04-01'
        for scenario in spec['scenarios']: scenario['fx_gbp_p12']['USD'][hand.MONTHS[2]] = 3 * SCALE
    if variant == 'cure':
        spec['entities'][0].update(opening_trap=True, opening_restricted_minor=7)
    if variant == 'future_event':
        original = spec['intercompany_terms'][0]
        spec['intercompany_terms'].append({**original, 'effective_month': hand.MONTHS[1], 'monthly_rate_p12': SCALE // 5})
        spec['intercompany_terms'].reverse()
    if variant == 'March_boundary':
        replacements = dict(zip(hand.MONTHS, ('2024-02-01', '2024-03-01', '2024-04-01')))
        def replace(value):
            if isinstance(value, dict): return {replacements.get(key, key): replace(child) for key, child in value.items()}
            if isinstance(value, list): return [replace(child) for child in value]
            return replacements.get(value, value) if isinstance(value, str) else value
        spec = replace(spec)
    if variant == 'real_funding_gap': spec['intercompany_terms'][0]['limit_minor'] = 50
    spec, book, binding = emitted(spec)
    result = calibrate(spec, binding)
    assert result['all_independent_journal_fields_covered'] is True
    assert result['bounded_queue_periods_checked'] == 18
    assert result['logical_fields_checked'] >= 2300
    assert binding['fixed_plan_provided_and_protected'] is True
    assert binding['actual_LO_calls'] == 0 and binding['qualified'] is False
    assert len(binding['formula_bindings']) == len({(x['sheet'], x['cell']) for x in binding['formula_bindings']})
    assert len(binding['formula_bindings']) < len(binding['output_bindings']) + 600
    if variant == 'real_funding_gap': assert simulate(spec)['feasible'] is False
    book.close()


@pytest.mark.parametrize('amount,factor', [(1, SCALE // 2), (-1, SCALE // 2), (10**14 - 1, 10 * SCALE - 1),
    (-10**14 + 1, 10 * SCALE - 1), (10**14 - 1, 4 * SCALE - 17), (13, SCALE // 13)])
def test_exact_postings_and_large_FX_pairs_do_not_use_inexact_huge_doubles(amount, factor):
    a, b = "'Inputs'!$A$1", "'Inputs'!$B$1"
    values = {a: amount, b: factor}
    for operation in ('round_product', 'product_whole', 'product_remainder'):
        expression = (operation, a, b)
        actual = actual_formula_value('=' + excel.expression_formula(expression), values)
        assert actual == evaluate_expression(expression, values)
    assert amount * factor == int(actual_formula_value('=' + excel.expression_formula(('product_whole', a, b)), values)) * SCALE + int(actual_formula_value('=' + excel.expression_formula(('product_remainder', a, b)), values))


def test_general_FX_long_division_and_three_factor_collateral_are_exact_at_bounds():
    spec, book, _ = emitted()
    helper_book = openpyxl.Workbook(); helper_book.remove(helper_book.active)
    emitter = excel._Emitter(helper_book, spec, 10000); emitter.sheet = helper_book.create_sheet('Test')
    amount, fx = "'Group Inputs'!$A$1", "'Group Inputs'!$A$2"
    numerator, denominator = 23_999_999_999_999, 999_999_999_983
    values = {amount: numerator, fx: denominator}
    for ceiling in (False, True):
        expression = emitter.scale_divide(amount, fx, denominator, numerator, 'general_FX', ceiling=ceiling)
        result = emitter.put(expression, 'capacity')
        for item in emitter.formulas:
            actual = actual_formula_value(item['formula'], values)
            assert actual == evaluate_expression(item['expression'], values), item['label']
            values[excel._ref(item['sheet'], item['cell'])] = int(actual)
        expected = -(-numerator * SCALE // denominator) if ceiling else numerator * SCALE // denominator
        assert values[result] == expected
    a, b, c = "'Group Inputs'!$A$3", "'Group Inputs'!$A$4", "'Group Inputs'!$A$5"
    values.update({a: 99_999_999_999_999, b: SCALE - 1, c: SCALE - 3})
    result = emitter.put(emitter.triple(a, b, c, 'collateral'), 'posted_collateral')
    for item in emitter.formulas:
        actual = actual_formula_value(item['formula'], values)
        assert actual == evaluate_expression(item['expression'], values)
        values[excel._ref(item['sheet'], item['cell'])] = int(actual)
    n = values[a] * values[b] * values[c]
    assert values[result] == (2 * n + SCALE**2) // (2 * SCALE**2)
    book.close(); helper_book.close()


def test_emitter_uses_only_public_primitives_and_formula_budget_fails_without_truncation():
    tree = ast.parse(Path(excel.__file__).read_text())
    modules = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any('ledger' in name or 'search' in name for name in modules)
    with pytest.raises(ValueError, match='budget was exceeded'): emitted(maximum=50)
    spec = hand.specification(); spec['dimension_mode'] = 'production'
    with pytest.raises(ValueError): emitted(spec)


def test_count_only_compiles_the_same_complete_toy_without_materializing_a_workbook(monkeypatch):
    spec, book, binding = emitted()
    physical_cells = sum(cell.value is not None for sheet in book for cell in sheet._cells.values())
    expected_max = max(len(item['formula']) for item in binding['formula_bindings'])
    def forbidden(*args, **kwargs): raise AssertionError('Count-only must not create an openpyxl workbook')
    monkeypatch.setattr(openpyxl, 'Workbook', forbidden)
    count = excel.count_entity_group_formulas(spec)
    assert count['physical_formula_count'] == binding['formula_count']
    assert count['logical_output_binding_count'] == len(binding['output_bindings'])
    assert count['physical_nonempty_cells'] == physical_cells
    assert count['maximum_formula_length'] == expected_max
    assert count['maximum_expression_depth'] > 1
    assert len(count['complete_expression_stream_sha256']) == len(count['complete_logical_binding_stream_sha256']) == 64
    assert count['production_workbook_materialized'] is False and count['ledger_execution'] is False
    assert count['LO_calls'] == count['model_calls'] == 0
    book.close()


@pytest.mark.parametrize('fault', ['drop_field', 'wrong_money', 'bad_residual', 'hide_queue', 'alter_fixed_plan'])
def test_full_field_audit_rejects_missing_financial_fields_and_wrong_journal(fault):
    spec, book, binding = emitted(); ledger = simulate(spec)
    if fault == 'drop_field':
        binding['output_bindings'] = [x for x in binding['output_bindings'] if x['path'][-1] != 'current_tax']
    if fault == 'wrong_money': ledger['scenarios']['S01']['entities']['E02']['monthly'][2]['current_tax'] += 1
    if fault == 'bad_residual': ledger['scenarios']['S01']['entities']['E02']['monthly'][2]['residuals']['net_assets'] = 1
    if fault == 'hide_queue': ledger['scenarios']['S01']['entities']['E02']['monthly'][1]['interest_live_vintages'] = []
    if fault == 'alter_fixed_plan': ledger['fixed_plan']['P01'] = 1
    with pytest.raises(ValueError): expected_values(spec, ledger, binding)
    book.close()


def test_unrecalculated_caches_fail_and_cached_fixture_tampering_is_detected(tmp_path):
    spec, book, binding = emitted(); path = tmp_path / 'unrecalculated.xlsx'; book.save(path); book.close()
    ledger = simulate(spec)
    missing = audit_entity_group_workbook(path, spec, ledger, binding)
    assert missing['passed'] is False and missing['mismatches']
    assert missing['logical_fields_checked'] == 2376
    # A parser-only cached XML fixture is explicitly not an actual LO receipt.
    values = expected_values(spec, ledger, binding)['values']
    with ZipFile(path) as archive: records = {item.filename: (item, archive.read(item)) for item in archive.infolist()}
    namespace = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    for sheet_index, sheet in enumerate(openpyxl.load_workbook(path).sheetnames, 1):
        name = 'xl/worksheets/sheet' + str(sheet_index) + '.xml'
        root = ET.fromstring(records[name][1])
        for cell in root.findall('.//m:sheetData/m:row/m:c', namespace):
            if cell.find('m:f', namespace) is None: continue
            value = values[excel._ref(sheet, cell.get('r'))]
            cached = cell.find('m:v', namespace)
            if cached is None: cached = ET.SubElement(cell, '{' + namespace['m'] + '}v')
            if type(value) is str: cell.set('t', 'str')
            cached.text = str(value)
        records[name] = records[name][0], ET.tostring(root, encoding='utf-8', xml_declaration=True)
    cached_path = tmp_path / 'offline_cached_fixture.xlsx'
    with ZipFile(cached_path, 'w', ZIP_DEFLATED) as archive:
        for item, raw in records.values(): archive.writestr(item, raw)
    report = audit_entity_group_workbook(cached_path, spec, ledger, binding)
    assert report['passed'] is True and report['quality_or_difficulty_certified'] is False
    altered = openpyxl.load_workbook(cached_path)
    literal = next(x for x in binding['input_bindings'] if x['path'] == ['fixed_plan', 'P02'])
    altered[literal['sheet']][literal['cell']] = 0; changed = tmp_path / 'changed.xlsx'; altered.save(changed); altered.close()
    report = audit_entity_group_workbook(changed, spec, ledger, binding)
    assert report['passed'] is False and report['control_mismatches']
