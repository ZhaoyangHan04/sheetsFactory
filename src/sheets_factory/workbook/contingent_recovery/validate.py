"""Independently audit actual caches against the posted contingent-rent journal."""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import json
import math

import openpyxl

from .contract import validate_spec

D = Decimal
FINANCIAL_FIELDS = {'total_recovery_entitlement', 'variable_lease_cash', 'variable_lease_allowance',
                    'variable_book_expense', 'variable_tax_deduction'} | {'variable_rents.' + identity for identity in ('P01', 'P02', 'P03', 'P04')}
CONTRACT_FIELDS = {'active', 'rate', 'threshold', 'annual_cap', 'rounding_quantum', 'rounding_mode'}


def annual_results(programme_ledger):
    rows = programme_ledger['contingent_recovery']['annual']
    if isinstance(rows, dict):
        result = {int(year): row for year, row in rows.items()}
    elif isinstance(rows, list):
        result = {int(row['year']): row for row in rows}
        if len(result) != len(rows):
            raise ValueError('Duplicate independent contingent journal reporting years')
    else:
        raise ValueError('Explicit independent contingent annual journal is required')
    if set(result) != set(range(2024, 2044)):
        raise ValueError('The independent contingent journal must cover all twenty years')
    return result


def _money_matches(observed, expected):
    if isinstance(observed, bool) or not isinstance(observed, (int, float)) or not math.isfinite(observed):
        return False
    observed, expected = D(str(observed)), D(str(expected))
    return (abs(observed - expected) < D('.005')
            and observed.quantize(D('.01'), rounding=ROUND_HALF_UP) == expected.quantize(D('.01'), rounding=ROUND_HALF_UP))


def _provided_matches(observed, expected, field):
    if field == 'active':
        return type(observed) is bool and observed is expected
    if field == 'rounding_mode':
        return type(observed) is str and observed == expected
    if isinstance(observed, bool) or not isinstance(observed, (int, float)) or not math.isfinite(observed):
        return False
    expected = D(str(expected))
    return abs(D(str(observed)) - expected) <= max(D('1e-12'), abs(expected) * D('1e-14'))


def _field(result, field):
    if field.startswith('variable_rents.'):
        return result['variable_rents'][field.split('.')[1]]
    return result[field]


def audit_contingent_workbook(path, spec, programmeledger, bindings):
    """Every raw contingent financial formula needs an independent posted check.

    Public terms, payability flags, dates, separate allowance fractions and the
    complete contract JSON are also checked. An unrecalculated workbook fails.
    The original programme journal must expose the returned cash, allowance and
    total entitlement as its actual annual fields, rather than a parallel report.
    """
    spec = validate_spec(spec)
    expected = annual_results(programmeledger)
    years = {row['year']: row for row in spec['annual_terms']}
    book = openpyxl.load_workbook(path, data_only=True, keep_links=False)
    formulas = openpyxl.load_workbook(path, data_only=False, keep_links=False)
    mismatches, controls, checks = [], [], []
    try:
        names = set(bindings['sheets'].values())
        if not names <= set(book.sheetnames):
            raise ValueError('Contingent workbook sheets are missing')
        actual_formulas = {(ws.title, cell.coordinate) for ws in formulas if ws.title in names
                           for cell in ws._cells.values() if cell.data_type == 'f'}
        records = bindings['cell_bindings']
        bound = {(item['sheet'], item['cell']) for item in records}
        semantic = {(item['year'], item['field']) for item in records}
        expected_semantic = {(year, field) for year in years for field in FINANCIAL_FIELDS}
        complete = (actual_formulas == bound and len(bound) == len(records)
                    and semantic == expected_semantic and len(records) == len(expected_semantic))
        for item in records:
            value = _field(expected[item['year']], item['field'])
            observed = book[item['sheet']][item['cell']].value
            matched = _money_matches(observed, value)
            record = {'address': item['sheet'] + '!' + item['cell'], 'year': item['year'],
                      'field': item['field'], 'expected_independent': str(value), 'observed': observed, 'matched': matched}
            checks.append(record)
            if not matched:
                mismatches.append(record)
        seen_inputs = set()
        required_inputs = {(year, None, 'eligible_fraction') for year in years}
        required_inputs |= {(year, identity, field) for year in years for identity in ('P01', 'P02', 'P03', 'P04') for field in CONTRACT_FIELDS}
        for item in bindings['input_bindings']:
            identity = item.get('lease_id')
            key = (item['year'], identity, item['field'])
            if key in seen_inputs:
                controls.append({'reason': 'duplicate provided input binding', 'key': key})
            seen_inputs.add(key)
            terms = years[item['year']]
            value = terms['eligible_fraction'] if identity is None else next(c for c in terms['contracts'] if c['lease_id'] == identity)[item['field']]
            cell = book[item['sheet']][item['cell']]
            is_formula = formulas[item['sheet']][item['cell']].data_type == 'f'
            if is_formula or not _provided_matches(cell.value, value, item['field']):
                controls.append({'address': item['sheet'] + '!' + item['cell'], 'field': item['field'],
                                 'expected': value, 'observed': cell.value, 'reason': 'provided term differs'})
        if seen_inputs != required_inputs:
            controls.append({'reason': 'provided input bindings are incomplete or contain unrecognized terms'})
        required_calendars = {(year, 'inputs', field) for year in years for field in ('year', 'period_start', 'period_end')}
        required_calendars |= {(year, 'annual', field) for year in years for field in ('year', 'period_end')}
        seen_calendars = set()
        for item in bindings['calendar_bindings']:
            role = next((role for role, name in bindings['sheets'].items() if name == item['sheet']), None)
            seen_calendars.add((item['year'], role, item['field']))
            value = item['year'] if item['field'] == 'year' else (date(item['year'] - 1, 4, 1) if item['field'] == 'period_start' else date(item['year'], 3, 31))
            observed = book[item['sheet']][item['cell']].value
            if isinstance(observed, datetime):
                observed = observed.date()
            if observed != value or formulas[item['sheet']][item['cell']].data_type == 'f':
                controls.append({'address': item['sheet'] + '!' + item['cell'], 'reason': 'provided fiscal calendar differs'})
        if seen_calendars != required_calendars:
            controls.append({'reason': 'provided fiscal calendar bindings are incomplete'})
        location = bindings['public_spec_cell']
        try:
            observed_spec = json.loads(book[location['sheet']][location['cell']].value)
        except (TypeError, ValueError):
            observed_spec = None
        if observed_spec != spec or formulas[location['sheet']][location['cell']].data_type == 'f':
            controls.append({'reason': 'public JSON contract differs from supplied terms'})
        if len(bindings['public_rule_cells']) != len(spec['public_rules']):
            controls.append({'reason': 'public contractual rules are incomplete'})
        else:
            for item, rule in zip(bindings['public_rule_cells'], spec['public_rules']):
                if book[item['sheet']][item['cell']].value != rule:
                    controls.append({'address': item['sheet'] + '!' + item['cell'], 'reason': 'public contractual rule differs'})
        programme_rows = programmeledger['annual']
        if isinstance(programme_rows, dict):
            programme_rows = {int(year): row for year, row in programme_rows.items()}
        elif len(programme_rows) == 20:
            programme_rows = dict(zip(range(2024, 2044), programme_rows))
        else:
            raise ValueError('Actual programme annual journal must cover the same twenty years')
        programme_reconciled = set(programme_rows) == set(years)
        for year in years:
            for programme_field, result_field in [('capital_entitlement', 'total_recovery_entitlement'),
                                                   ('variable_lease_cash', 'variable_lease_cash'),
                                                   ('variable_lease_allowance', 'variable_lease_allowance')]:
                if D(str(programme_rows[year][programme_field])) != D(str(expected[year][result_field])):
                    programme_reconciled = False
        proofs = all(row.get('unique_fixed_point') is True and row.get('proof', {}).get('unique_on_entire_contractual_grid') is True for row in expected.values())
        passed = complete and not mismatches and not controls and programme_reconciled and proofs
        return {'passed': passed, 'formula_count': len(actual_formulas), 'new_formula_count': len(actual_formulas),
            'checked_cells': len(checks), 'complete_formula_coverage': complete,
            'all_formula_cells_independently_covered': complete,
            'mismatch_count': len(mismatches), 'mismatches': mismatches,
            'control_mismatch_count': len(controls), 'control_mismatches': controls,
            'public_parameters_verified': not controls,
            'programme_feedback_reconciled': programme_reconciled,
            'all_twenty_years_uniquely_certified': proofs, 'cell_checks': checks}
    finally:
        book.close()
        formulas.close()
