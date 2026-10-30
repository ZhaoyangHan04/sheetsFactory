"""Independent integer support checks for the capital-allocation workbook."""
from __future__ import annotations

from datetime import date, datetime
import json
import math
import re

import openpyxl
from openpyxl.formula import Tokenizer


def evaluate_integer_expression(expression, values):
    """Use Python integers, independently of the Excel formula implementation."""
    if type(expression) is int:
        return expression
    if isinstance(expression, str):
        result = values[expression]
        if type(result) is not int:
            raise ValueError('Every arithmetic reference must bind an exact integer')
        return result
    if not isinstance(expression, (tuple, list)) or not expression:
        raise ValueError('Malformed independent integer expression')
    operation, *arguments = expression
    if operation == 'if':
        if len(arguments) != 3:
            raise ValueError('Malformed conditional integer expression')
        return evaluate_integer_expression(arguments[1] if evaluate_integer_expression(arguments[0], values)
                                           else arguments[2], values)
    if operation == 'empty' and not arguments: return None
    args = [evaluate_integer_expression(value, values) for value in arguments]
    if operation == 'sum': return sum(args)
    if operation == 'mul':
        result = 1
        for value in args: result *= value
        return result
    if operation == 'abs' and len(args) == 1: return abs(args[0])
    if len(args) == 2:
        left, right = args
        if operation == 'sub': return left - right
        if operation == 'lt': return left < right
        if operation == 'le': return left <= right
        if operation == 'ge': return left >= right
        if operation == 'eq': return left == right
        if operation == 'floordiv': return left // right
        if operation == 'mod': return left % right
        if operation == 'rounddiv':
            if right <= 0: raise ValueError('A positive posting divisor is required')
            return (1 if left >= 0 else -1) * ((2 * abs(left) + right) // (2 * right))
    if operation == 'min' and args: return min(args)
    if operation == 'max' and args: return max(args)
    if operation == 'and' and args: return all(args)
    if operation == 'or' and args: return any(args)
    raise ValueError('Unsupported independent integer expression')


def _path(value, path):
    for part in path: value = value[part]
    return value


def _reference(sheet, cell):
    return "'" + sheet.replace("'", "''") + "'!" + re.sub(r'([A-Z]+)([0-9]+)', r'$\1$\2', cell)


def expected_cells(spec, plan, ledger, bindings):
    """Bind financial outputs to the independent journal, not Excel evaluation."""
    from .spec import (ANNUAL_FIELDS, PROJECT_FIELDS, PROJECT_IDS, SCENARIO_IDS,
                       VINTAGE_FIELDS, YEARS, load_spec, validate_plan)
    spec, plan = load_spec(spec), validate_plan(plan)
    if ledger.get('plan') != plan or bindings.get('public_spec') != spec:
        raise ValueError('The public specification or common plan differs')
    financial_paths = {('feasible',), ('objective_pence',)}
    for identity in SCENARIO_IDS:
        financial_paths.update(('scenarios', identity, field) for field in ('feasible', 'diagnostic_npv_pence', 'npv_pence'))
        financial_paths.update(('scenarios', identity, 'annual', index, field) for index in range(len(YEARS)) for field in ANNUAL_FIELDS)
        financial_paths.update(('scenarios', identity, 'project_flows', project, index, field)
            for project in PROJECT_IDS for index in range(len(YEARS)) for field in PROJECT_FIELDS)
        financial_paths.update(('scenarios', identity, 'tax_vintages', index, field)
            for index in range(len(YEARS)**2) for field in VINTAGE_FIELDS)
    supplied_paths = [tuple(item['expected_path']) for item in bindings['financial_bindings']]
    if set(supplied_paths) != financial_paths or len(supplied_paths) != len(financial_paths):
        raise ValueError('Complete independent financial and tax-vintage coverage is required')
    decisions = [item['project_id'] for item in bindings['decision_bindings']]
    if set(decisions) != set(PROJECT_IDS) or len(decisions) != len(PROJECT_IDS):
        raise ValueError('Exactly eighteen distinct common decisions are required')
    values = {}
    for item in bindings['input_bindings']:
        value = _path(spec, item['path'])
        if type(value) is int: values[_reference(item['sheet'], item['cell'])] = value
    for item in bindings['decision_bindings']:
        values[_reference(item['sheet'], item['cell'])] = plan[item['project_id']]
    for item in bindings['financial_bindings']:
        value = _path(ledger, item['expected_path'])
        if item['kind'] == 'flag': value = int(value)
        if value is not None and type(value) is not int:
            raise ValueError('Independent financial postings must be integer pence')
        values[_reference(item['sheet'], item['cell'])] = value
    for item in bindings['arithmetic_bindings']:
        from .excel import expression_formula
        if item.get('target_eligible') is not False or item.get('value_protected') is not False:
            raise ValueError('Provided exact arithmetic cannot become an FM target')
        if item.get('formula') != '=' + expression_formula(item['expression']):
            raise ValueError('The declared arithmetic expression and formula differ')
        value = evaluate_integer_expression(item['expression'], values)
        if type(value) is not int or abs(value) >= 2**53:
            raise ValueError('An integer arithmetic support cell exceeds exact binary64 range')
        values[_reference(item['sheet'], item['cell'])] = value
    return values


def _formula_tokens(formula):
    return [(token.type, token.subtype, token.value) for token in Tokenizer(formula).items if token.type != 'WHITE-SPACE']


def audit_capital_allocation_workbook(path, spec, plan, ledger, bindings):
    """Check complete actual formula caches, inputs, definitions and public rules.

    An unrecalculated workbook fails. This audit validates one provided plan;
    it certifies neither global optimality nor uniqueness of that plan.
    """
    from .spec import RULES, load_spec, validate_plan
    spec, plan = load_spec(spec), validate_plan(plan)
    expected = expected_cells(spec, plan, ledger, bindings)
    definitions = openpyxl.load_workbook(path, data_only=False, keep_links=False)
    caches = openpyxl.load_workbook(path, data_only=True, keep_links=False)
    checks, mismatches, controls = [], [], []
    try:
        structure = definitions.sheetnames == caches.sheetnames == bindings['sheet_names']
        formula_records = bindings['financial_bindings'] + bindings['arithmetic_bindings']
        formula_records += [{**item, 'formula': '=' + str(plan[item['project_id']])} for item in bindings['decision_bindings']]
        bound = {(item['sheet'], item['cell']) for item in formula_records}
        actual = {(sheet.title, cell.coordinate) for sheet in definitions for cell in sheet._cells.values() if cell.data_type == 'f'}
        complete = actual == bound and len(bound) == len(formula_records)
        for item in formula_records:
            address = _reference(item['sheet'], item['cell'])
            definition = definitions[item['sheet']][item['cell']]
            observed = caches[item['sheet']][item['cell']].value
            value = expected[address]
            matched = (observed in (None, '') if value is None else
                type(observed) in (int, float) and math.isfinite(observed) and observed == value)
            formula_matches = definition.data_type == 'f' and _formula_tokens(definition.value) == _formula_tokens(item['formula'])
            record = {'address': address, 'expected_independent': value, 'observed': observed,
                      'matched': matched, 'formula_matches': formula_matches}
            checks.append(record)
            if not matched or not formula_matches: mismatches.append(record)
        literal_locations = set()
        for item in bindings['literal_bindings']:
            key = item['sheet'], item['cell']; literal_locations.add(key)
            value = definitions[key[0]][key[1]].value
            if item['kind'] == 'date':
                if isinstance(value, datetime): value = value.date()
                value = value.isoformat() if isinstance(value, date) else value
            valid_type = (isinstance(definitions[key[0]][key[1]].value, (date, datetime))
                          if item['kind'] == 'date' else type(value).__name__ == item['kind'])
            if value != item['value'] or not valid_type:
                controls.append({'address': _reference(*key), 'reason': 'A supplied literal or calendar changed'})
        actual_literals = {(sheet.title, cell.coordinate) for sheet in definitions for cell in sheet._cells.values()
                           if cell.value is not None and cell.data_type != 'f'}
        if actual_literals != literal_locations or len(literal_locations) != len(bindings['literal_bindings']):
            controls.append({'reason': 'Provided literal coverage is incomplete or duplicated'})
        for item in bindings['input_bindings']:
            observed = definitions[item['sheet']][item['cell']].value
            value = _path(spec, item['path'])
            if type(observed) is not type(value) or observed != value:
                controls.append({'address': _reference(item['sheet'], item['cell']), 'reason': 'A public primitive differs'})
        try:
            public = json.loads(''.join(definitions[item['sheet']][item['cell']].value for item in bindings['public_spec_chunks']))
        except (TypeError, ValueError): public = None
        if public != spec: controls.append({'reason': 'The complete public JSON specification differs'})
        rules = [definitions[item['sheet']][item['cell']].value for item in bindings['public_rule_cells']]
        if rules != list(RULES): controls.append({'reason': 'The public accounting rules differ'})
        all_feasible = ledger.get('feasible') is True and all(row.get('feasible') is True and row.get('all_journals_balance') is True
                                                           for row in ledger['scenarios'].values())
        passed = structure and complete and not mismatches and not controls and all_feasible
        return {'passed': passed, 'workbook_structure_verified': structure, 'formula_count': len(actual),
            'checked_cells': len(checks), 'all_formula_cells_independently_covered': complete,
            'financial_formula_count': len(bindings['financial_bindings']),
            'provided_arithmetic_formula_count': len(bindings['arithmetic_bindings']),
            'decision_formula_count': len(bindings['decision_bindings']),
            'mismatches': mismatches, 'control_mismatches': controls, 'cell_checks': checks,
            'all_scenarios_feasible': all_feasible, 'all_journals_balance': all_feasible,
            'optimality_or_uniqueness_certified': False}
    finally:
        definitions.close(); caches.close()
