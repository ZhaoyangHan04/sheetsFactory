"""Complete independent-journal bindings and actual cache audit for a close.

The expression interpreter uses Python integers. It is not an Excel engine;
offline expression agreement is kept distinct from an actual cache audit.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
import re

import openpyxl
from openpyxl.formula.tokenizer import Tokenizer

from .spec import PHASES, RULES, SCALE, load_spec

REFERENCE = re.compile(r"^'((?:[^']|'')+)'!\$([A-Z]+)\$([1-9][0-9]*)$")


def formula_signature(formula):
    """Allow exact numeric spelling changes; keep every other token strict."""
    return [(token.type, token.subtype, Decimal(token.value)
        if token.type == 'OPERAND' and token.subtype == 'NUMBER' else token.value)
        for token in Tokenizer(formula).items if token.type != 'WHITE-SPACE']


def _path(root, path):
    for part in path: root = root[part]
    return root


def _location(reference):
    match = REFERENCE.fullmatch(reference)
    if not match: raise ValueError('An explicit local workbook reference is required')
    return match[1].replace("''", "'"), match[2] + match[3]


def evaluate_expression(expression, values):
    """A separate exact-integer interpreter; no emitter or ledger helper calls."""
    if type(expression) in (int, bool): return int(expression)
    if isinstance(expression, str): return values[expression] if REFERENCE.fullmatch(expression) else expression
    if not isinstance(expression, (list, tuple)) or not expression: raise ValueError('Unsupported accounting expression')
    op, *args = expression
    if op == 'if': return evaluate_expression(args[1] if evaluate_expression(args[0], values) else args[2], values)
    if op == 'and': return int(all(evaluate_expression(arg, values) for arg in args))
    if op == 'or': return int(any(evaluate_expression(arg, values) for arg in args))
    numbers = [evaluate_expression(arg, values) for arg in args]
    if op == 'sum': return sum(numbers)
    if op == 'sub': return numbers[0] - numbers[1]
    if op == 'mul': return numbers[0] * numbers[1]
    if op == 'min': return min(numbers)
    if op == 'max': return max(numbers)
    if op == 'abs': return abs(numbers[0])
    if op == 'lt': return int(numbers[0] < numbers[1])
    if op == 'le': return int(numbers[0] <= numbers[1])
    if op == 'eq': return int(numbers[0] == numbers[1])
    if op == 'ge': return int(numbers[0] >= numbers[1])
    if op == 'floordiv': return numbers[0] // numbers[1]
    if op == 'ceildiv': return -(-numbers[0] // numbers[1])
    if op == 'mod': return numbers[0] % numbers[1]
    if op in ('rounddiv', 'round_product'):
        numerator, denominator = (numbers[0], numbers[1]) if op == 'rounddiv' else (numbers[0] * numbers[1], SCALE)
        if denominator <= 0: raise ValueError('A rounding denominator must be positive')
        answer = (2 * abs(numerator) + denominator) // (2 * denominator)
        return -answer if numerator < 0 else answer
    if op == 'product_whole': return numbers[0] * numbers[1] // SCALE
    if op == 'product_remainder': return numbers[0] * numbers[1] % SCALE
    raise ValueError('Unsupported independent expression: ' + str(op))


def expected_values(specification, ledger, bindings):
    """Check every emitted physical expression and every public ledger field."""
    public = load_spec(specification)
    if bindings.get('public_spec') != public or ledger.get('fixed_plan') != public['fixed_plan']:
        raise ValueError('The provided fixed plan or primitive specification differs')
    values = {}; formula_cells = set()
    for item in bindings['input_bindings']:
        value = _path(public, item['path'])
        if value != item['value'] or type(value) is not type(item['value']): raise ValueError('A public primitive binding changed')
        if type(value) is bool:
            if (item.get('encoding') != 'public_boolean_as_binary_integer'
                    or type(item.get('stored_value')) is not int or item['stored_value'] != int(value)):
                raise ValueError('The explicit public Boolean-to-binary input encoding differs')
        elif (item.get('encoding') != 'identity' or type(item.get('stored_value')) is not type(value)
                or item['stored_value'] != value):
            raise ValueError('A non-Boolean primitive cannot change its literal type or encoding')
        from .excel import _ref
        values[_ref(item['sheet'], item['cell'])] = item['stored_value']
    for item in bindings['formula_bindings']:
        key = (item['sheet'], item['cell'])
        if key in formula_cells: raise ValueError('A physical formula binding repeats')
        formula_cells.add(key)
        from .excel import _ref, expression_formula
        if item['formula'] != '=' + expression_formula(item['expression']): raise ValueError('Formula text differs from its auditable expression')
        result = evaluate_expression(item['expression'], values)
        if type(result) is int and abs(result) >= 2**53: raise ValueError('An actual physical numeric value exceeds exact binary64 range')
        if type(result) not in (int, str): raise ValueError('A physical expression has unsupported type')
        values[_ref(*key)] = result
    covered = set(); monetary = 0; queue_count = 0
    for binding in bindings['output_bindings']:
        path = tuple(binding['path']); expected = _path(ledger, path)
        if binding['encoding'] == 'scalar':
            actual = values[binding['reference']]
            expected = int(expected) if type(expected) is bool else expected
            if actual != expected: raise ValueError('Independent journal mismatch at ' + repr(path) + ': ' + repr(actual) + ' != ' + repr(expected))
            covered.add(path); monetary += binding['monetary'] is True
        elif binding['encoding'] == 'exact_integer_pair':
            whole, remainder = values[binding['whole']], values[binding['remainder']]
            if type(whole) is not int or type(remainder) is not int or not 0 <= remainder < SCALE:
                raise ValueError('A large exact FX numerator has an invalid representation')
            if whole * SCALE + remainder != expected: raise ValueError('Independent exact FX numerator differs: ' + repr(path))
            covered.add(path); monetary += 1
        elif binding['encoding'] == 'queues':
            queue_count += 1; mi = path[-1]; identity = path[-3]
            entity = next(e for e in public['entities'] if e['id'] == identity)
            for kind, ledger_prefix in (('interest', 'interest'), ('tax', 'tax_loss')):
                live = {item['origin']: values[item['reference']] for item in binding[kind]}
                prior = {item['origin']: values[item['reference']] for item in binding['prior_' + kind]}
                if any(type(value) is not int or value < 0 for value in (*live.values(), *prior.values())):
                    raise ValueError('A FIFO vintage is negative or not integer minor units')
                carry = entity[kind + '_carry_months']; months = public['months']
                closing = [{'vintage_month': months[origin], 'balance_minor': amount} for origin, amount in sorted(live.items()) if amount]
                expired = [{'vintage_month': months[origin], 'amount_minor': amount} for origin, amount in sorted(prior.items()) if mi - origin > carry and amount]
                used = [{'vintage_month': months[origin], 'amount_minor': amount - live.get(origin, 0)}
                    for origin, amount in sorted(prior.items()) if mi - origin <= carry and amount - live.get(origin, 0)]
                fields = {('interest_live_vintages' if kind == 'interest' else 'tax_live_vintages'): closing,
                    ledger_prefix + '_expired': expired,
                    ('interest_used_events' if kind == 'interest' else 'tax_loss_used_events'): used}
                for field, actual in fields.items():
                    if actual != expected[field]: raise ValueError('Independent bounded FIFO events differ: ' + repr((*path, field)))
                    covered.add((*path, field))
                if len(live) > carry + 1: raise ValueError('The vintage window exceeds its contractual carry plus current origin')
        else: raise ValueError('Unknown output binding encoding')
    required = set()
    for sid, scenario in ledger['scenarios'].items():
        prefix = ('scenarios', sid)
        for identity, entity in scenario['entities'].items():
            for index, row in enumerate(entity['monthly']):
                for field, value in row.items():
                    if field == 'month': continue
                    if field == 'residuals':
                        required.update((*prefix, 'entities', identity, 'monthly', index, field, name) for name in value)
                    else: required.add((*prefix, 'entities', identity, 'monthly', index, field))
        for identity, rows in scenario['projects'].items():
            required.update((*prefix, 'projects', identity, index, field) for index, row in enumerate(rows) for field in row if field != 'month')
        for identity, rows in scenario['intercompany'].items():
            required.update((*prefix, 'intercompany', identity, index, field) for index, row in enumerate(rows)
                for field in row if field not in ('month', 'loan_id', 'currency', 'lender_id', 'borrower_id'))
        required.update((*prefix, 'group_monthly', index, field) for index, row in enumerate(scenario['group_monthly'])
            for field in row if field not in ('month', 'fiscal_year'))
        required.update((*prefix, 'fiscal_years', index, field) for index, row in enumerate(scenario['fiscal_years'])
            for field in row if field not in ('months', 'fiscal_year'))
    if covered != required:
        raise ValueError('Independent full-field coverage differs; missing=' + repr(sorted(required - covered)[:12]) + '; extra=' + repr(sorted(covered - required)[:12]))
    return {'values': values, 'logical_fields_checked': len(covered), 'monetary_bindings': monetary,
        'bounded_queue_periods_checked': queue_count, 'physical_formulas_checked': len(formula_cells),
        'all_independent_journal_fields_covered': True}


def audit_entity_group_workbook(path, specification, ledger, bindings):
    """Audit actual engine caches; an unrecalculated formula workbook fails."""
    checked = expected_values(specification, ledger, bindings)
    definitions = openpyxl.load_workbook(path, keep_links=False)
    cache = openpyxl.load_workbook(path, data_only=True, keep_links=False)
    mismatches, controls = [], []
    try:
        if definitions.sheetnames != bindings['worksheet_order'] or cache.sheetnames != bindings['worksheet_order']:
            controls.append('worksheet_names_or_order')
        actual_formulas = {(sheet.title, cell.coordinate) for sheet in definitions for cell in sheet._cells.values() if cell.data_type == 'f'}
        bound_formulas = {(item['sheet'], item['cell']) for item in bindings['formula_bindings']}
        if actual_formulas != bound_formulas: controls.append('physical_formula_scope')
        for item in bindings['input_bindings']:
            cell = definitions[item['sheet']][item['cell']]
            if cell.data_type == 'f' or cell.value != item['stored_value'] or type(cell.value) is not type(item['stored_value']):
                controls.append('input:' + item['sheet'] + '!' + item['cell'])
            if definitions[item['sheet']].cell(cell.row, 1).value != '/'.join(map(str, item['path'])):
                controls.append('input_label:' + item['sheet'] + '!' + item['cell'])
        contract = definitions['Group Contract']
        parts = [contract.cell(row, 2).value for row in range(2, contract.max_row + 1)]
        if any(contract.cell(row, 1).value != 'JSON part ' + str(row - 1)
                or contract.cell(row, 2).data_type == 'f' for row in range(2, contract.max_row + 1)):
            controls.append('public_contract_labels')
        if json.loads(''.join(parts)) != bindings['public_spec']: controls.append('public_contract')
        actual_rules = [row[1].value for row in definitions['Group Rules'].iter_rows(min_row=2)]
        if actual_rules != list(PHASES) + list(RULES): controls.append('public_policy')
        from .excel import _ref
        for item in bindings['formula_bindings']:
            cell = definitions[item['sheet']][item['cell']]
            value = cache[item['sheet']][item['cell']].value
            expected = checked['values'][_ref(item['sheet'], item['cell'])]
            # Engine display integers may be floats, but Boolean/date/string
            # substitutes cannot stand in for a numeric posting.
            typed = (type(value) in (int, float) and not isinstance(value, bool) and value == expected) if type(expected) is int else type(value) is str and value == expected
            definition_matches = cell.data_type == 'f' and formula_signature(cell.value) == formula_signature(item['formula'])
            if not definition_matches or not typed:
                mismatches.append({'sheet': item['sheet'], 'cell': item['cell'], 'actual': value, 'expected': expected,
                    'definition_matches': definition_matches})
        return {key: value for key, value in checked.items() if key != 'values'} | {
            'passed': not controls and not mismatches, 'cache_audit': 'actual_workbook_formula_values_required',
            'mismatches': mismatches, 'control_mismatches': controls,
            'provided_fixed_plan_verified': True, 'optimisation_performed': False,
            'all_scenarios_feasible': ledger['feasible'],
            'financially_consistent_diagnostic_infeasibility_is_not_source_qualification': True,
            'quality_or_difficulty_certified': False, 'qualified': False, 'task_count': 0}
    finally:
        definitions.close(); cache.close()
