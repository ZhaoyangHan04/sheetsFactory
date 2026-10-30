"""Planned complete monetary-family faults across six financial algorithms.

This module creates plans only. Cached nonzero amounts are eligibility inputs,
not activity or fixed-point proofs. Cyclic plans cannot use the DAG certificate.
"""
from collections import Counter
from datetime import date, datetime
import math
from pathlib import Path
import re

import openpyxl
from openpyxl.utils import get_column_letter as colname

from .lease_family import discover_families, _row, _canonical, _mutate, ref

FAMILIES = ('lease.measurement_pv', 'lease.depreciation', 'lease.interest',
    'lease.nominal_payment', 'regulatory.real_return', 'operating.loan_interest',
    'holding.claims_haircut', 'contingent.variable_rent', 'waterfall.preference_accrual')
DEFAULT_LEASE_POLICY = {'mutation_profile': 'contract_conditioned_v2',
    'families': ['measurement_pv', 'depreciation', 'interest', 'nominal_payment'], 'max_roots': 100000}


def validate_policy(policy):
    names = policy.get('families', list(FAMILIES))
    if not isinstance(names, list) or set(names) != set(FAMILIES) or len(names) != len(FAMILIES):
        raise ValueError('The six-algorithm prototype requires every declared complete monetary family')
    if type(policy.get('max_roots', 100000)) is not int or not 1 <= policy.get('max_roots', 100000) <= 100000:
        raise ValueError('Complete root bound must be from 1 to 100000')
    return names


def _annual_columns(book, sheet):
    columns = [c.column for c in book[sheet][2][2:]
        if type(c.value) is int and 2024 <= c.value <= 2043 or isinstance(c.value, (date, datetime))]
    if columns != list(range(3, 23)):
        raise ValueError('All twenty public reporting years are required: ' + sheet)
    return columns


def discover_composite_families(book, policy=None):
    policy = policy or {}
    validate_policy(policy)
    result = []
    for group in discover_families(book, DEFAULT_LEASE_POLICY):
        result.append({**group, 'family': 'lease.' + group['family'], 'algorithm': 'lease'})
    definitions = [
        ('regulatory', 'real_return', 'Reopener Statements', ['real return']),
        ('operating', 'loan_interest', 'Operating Debt', ['loan a interest', 'loan b interest', 'revolver interest']),
        ('holding', 'claims_haircut', 'Holding Statements', ['claims after haircut']),
        ('contingent', 'variable_rent', 'Contingent Annual', [f'p0{i} current variable cash rent' for i in range(1, 5)]),
        ('waterfall', 'preference_accrual', 'Partner Waterfall', ['preference accrual']),
    ]
    for algorithm, family, sheet, labels in definitions:
        if algorithm == 'operating':
            header = list(book['Operating Calendar'][1][2:])
            if [c.value for c in header] != ['Month ' + str(i) for i in range(1, 37)]:
                raise ValueError('All thirty-six original operating months are required')
            columns = [c.column for c in header]
        else:
            columns = _annual_columns(book, sheet)
        for label in labels:
            result.append({'algorithm': algorithm, 'family': algorithm + '.' + family,
                'sheet': sheet, 'row': _row(book[sheet], label), 'columns': columns})
    return result


def mutate_composite_cell(group, cell, book, caches):
    family, before, c = group['family'], cell.value, colname(cell.column)
    if family.startswith('lease.'):
        context = group['context_rows']
        rate = caches[group['sheet']].cell(context['annual_rate'], cell.column).value
        frequency = book['Lease Inputs'].cell(_row(book['Lease Inputs'], 'payment frequency'), group['input_column']).value
        business = {'profile': 'contract_conditioned_v2', 'annual_rate': rate,
            'payment_frequency': frequency, 'input_column': group['input_column']}
        if type(rate) not in (int, float) or not math.isfinite(rate) or type(frequency) is not int:
            raise ValueError('Public rate and frequency types are unsupported')
        return _mutate(family.split('.')[1], cell, context, business), 'Apply the declared contract-conditioned lease timing, unit or depreciation-life fault.'
    if family == 'regulatory.real_return':
        opening = _row(book[group['sheet']], 'opening rav real')
        closing = _row(book[group['sheet']], 'closing rav real')
        needle = f"('Reopener Statements'!{c}{opening}+'Reopener Statements'!{c}{closing})/2"
        replacement = f"'Reopener Statements'!{c}{opening}"
        reason = 'Calculate the annual allowed real return on opening RAV instead of the contractual average RAV.'
    elif family == 'operating.loan_interest':
        matches = list(re.finditer(r"('Operating Scenario'!\$B\$\d+)/12", before))
        if len(matches) != 1:
            raise ValueError('Unsupported complete operating interest template')
        needle = matches[0].group(0)
        replacement = '((1+' + matches[0].group(1) + ')^(1/12)-1)'
        reason = 'Treat the supplied nominal annual loan rate as an effective annual rate.'
    elif family == 'holding.claims_haircut':
        matches = list(re.finditer(r"('Reopener Statements'![A-Z]+\d+)\*\(1-('Holding Inputs'![A-Z]+\d+)\)", before))
        if len(matches) != 1:
            raise ValueError('Unsupported complete collateral-haircut template')
        needle = matches[0].group(0)
        replacement = matches[0].group(1) + '/(1+' + matches[0].group(2) + ')'
        reason = 'Interpret the loss haircut as a financing discount denominator.'
    elif family == 'contingent.variable_rent':
        needle = c + '3-'
        replacement = '(' + c + "3*'Contingent Inputs'!" + c + '4)-'
        reason = 'Apply regulatory eligibility to the rent measurement base before the contractual threshold.'
    elif family == 'waterfall.preference_accrual':
        lp = _row(book[group['sheet']], 'lp capital open')
        gp = _row(book[group['sheet']], 'gp capital open')
        needle, replacement = c + str(lp) + '*', '(' + c + str(lp) + '+' + c + str(gp) + ')*'
        reason = 'Accrue the LP preferred return on both partners opening unreturned capital.'
    else:
        raise ValueError('Undeclared composite family')
    if before.count(needle) != 1:
        raise ValueError('The declared financial subexpression is not unique: ' + family)
    return before.replace(needle, replacement), reason


def propose_composite_debugging_task(baseline, policy=None):
    policy = policy or {}
    validate_policy(policy)
    book = openpyxl.load_workbook(baseline, keep_links=False)
    caches = openpyxl.load_workbook(baseline, data_only=True, keep_links=False)
    try:
        groups = discover_composite_families(book, policy)
        edits, templates, zero_count = [], set(), 0
        for group in groups:
            for column in group['columns']:
                cell = book[group['sheet']].cell(group['row'], column)
                cached = caches[group['sheet']][cell.coordinate]
                if cell.data_type != 'f':
                    if type(cell.value) not in (int, float) or cell.value != 0:
                        raise ValueError('Only audited provided zero constants may leave a complete family')
                    zero_count += 1
                    continue
                if (type(cached.value) not in (int, float) or not math.isfinite(cached.value)
                        or cached.is_date or cached.value == 0):
                    raise ValueError('An unpresented zero or invalid monetary formula remains')
                before = cell.value
                after, reason = mutate_composite_cell(group, cell, book, caches)
                if after == before:
                    raise ValueError('A complete family member was not mutated')
                templates.add(_canonical(before, cell.coordinate))
                edits.append({'sheet': group['sheet'], 'cell': cell.coordinate, 'before': before,
                    'after': after, 'family_id': group['family'], 'algorithm': group['algorithm'],
                    'reason': reason, 'business_rule': 'Apply the unchanged public financial contracts and reporting policies.'})
                cell.value = after
        if not edits or len(edits) > policy.get('max_roots', 100000):
            raise ValueError('Complete families exceed the bound; roots cannot be truncated')
        donors = []
        for sheet in book:
            for cell in sheet._cells.values():
                if cell.data_type != 'f':
                    continue
                formula = cell.value if isinstance(cell.value, str) else getattr(cell.value, 'text', None)
                if not isinstance(formula, str):
                    raise ValueError('Unreadable formula object in full donor audit')
                if _canonical(formula, cell.coordinate) in templates:
                    donors.append(sheet.title + '!' + cell.coordinate)
        if donors:
            raise ValueError('Intact full relative templates remain: ' + repr(donors[:5]))
        return {'title': 'Audit interconnected financial reporting policies',
            'public_instruction': 'Audit and repair inconsistent financial formulas across the financial model. Apply the supplied contracts and business briefs, preserve inputs and fixed inactive monetary entries, and save /app/output.xlsx.',
            'public_rules': ['The supplied timing, eligibility, rate, rounding and funding policies govern all reporting periods.',
                'Provided inactive monetary zeros and the original regulatory context remain unchanged.'],
            'edits': edits, 'mask_ranges': [], 'assumptions_added': [],
            'family_adapter': {'id': 'composite_monetary_complete_v1', 'status': 'planned_not_activity_proven',
                'root_count': len(edits), 'counts_by_algorithm': dict(Counter(e['algorithm'] for e in edits)),
                'counts_by_family': dict(Counter(e['family_id'] for e in edits)), 'provided_zero_count': zero_count,
                'correct_full_relative_templates_remaining': 0, 'root_proof_route': 'mixed_DAG_SCC_pending',
                'actual_LO_executions': 0, 'difficulty_measured': False,
                'limitations': ['No algebraic-equivalence donor absence claim.',
                    'Cyclic roots need two-context local fixed-point residual and own-value activity certificates; no global uniqueness claim for erroneous counterfactuals.',
                    'All remaining members must pass; no individual root can be dropped after a failed proof.']}}
    finally:
        book.close()
        caches.close()
