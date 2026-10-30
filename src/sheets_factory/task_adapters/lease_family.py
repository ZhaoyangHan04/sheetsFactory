"""Complete lease monetary families; no financial reference computation.

The presentation pass replaces only exact finite numeric zero formula caches.
The task pass changes every remaining selected formula. It never removes an
inactive proposed root to make an activity certificate pass.
"""
from __future__ import annotations

from collections import Counter
from copy import copy
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import openpyxl
from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter, range_boundaries

MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
NS = {'m': MAIN}
FAMILIES = {
    'measurement_pv': {'label': 'lease pv at measurement',
                       'fault': 'Treat contractual end-of-period lease payments as payments in advance.'},
    'depreciation': {'label': 'lease book depreciation',
                     'fault': 'Recompute a rolling remaining-life charge with an extra depreciation period.'},
    'interest': {'label': 'lease book interest',
                 'fault': 'Apply the stated annual effective discount rate as a monthly interest rate.'},
    'nominal_payment': {'label': 'nominal contract payment',
                        'fault': 'Report a one-period discounted amount as nominal contractual payment.'},
}
NOTE = ('Schedule presentation: inactive entries in the selected monetary schedules are provided as fixed numeric '
        'zeros. These entries have the same values as the fully calculated contractual schedules. Preserve provided '
        'constants and assumptions, and correct inconsistent financial formulas using the business briefs and contracts.')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha(path), 'bytes': path.stat().st_size}


def _label(value):
    return re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).strip()


def _row(sheet, name):
    found = [c.row for c in sheet['A'] if _label(c.value) == name]
    if len(found) != 1:
        raise ValueError('An exact public field is required: ' + sheet.title + '/' + name)
    return found[0]


def _families(policy):
    if policy.get('mutation_profile', 'original_v1') not in {'original_v1', 'contract_conditioned_v2'}:
        raise ValueError('Unknown declared lease mutation profile')
    names = policy.get('families', list(FAMILIES))
    if (not isinstance(names, list) or not names or len(names) != len(set(names))
            or any(n not in FAMILIES for n in names)):
        raise ValueError('Unknown, empty or duplicate lease family selection')
    limit = policy.get('max_roots', 100000)
    if type(limit) is not int or not 1 <= limit <= 100000:
        raise ValueError('max_roots must be an integer from1 to100000')
    return names


def discover_families(book, policy=None):
    policy = policy or {}
    names = _families(policy)
    inputs = book['Lease Inputs']
    identity_row = _row(inputs, 'lease id')
    identity_cells = [c for c in inputs[identity_row][2:] if c.value is not None]
    ids = [c.value for c in identity_cells]
    if not ids or any(not isinstance(v, str) for v in ids) or len(ids) != len(set(ids)):
        raise ValueError('Distinct public lease contract identities required')
    periods = [c.column for c in book['Lease Calendar'][2][2:] if type(c.value) in (int, float)]
    if not periods or periods != list(range(3, max(periods) + 1)):
        raise ValueError('A complete contiguous public lease calendar is required')
    result = []
    for identity_cell in identity_cells:
        identity = identity_cell.value
        sheet = book['Lease ' + identity]
        rows = {key: _row(sheet, label) for key, label in {
            'active': 'active flag', 'end': 'lease current end month',
            'rou': 'rou after measurement', 'liability': 'liability after measurement',
            'annual_rate': 'annual discount rate', 'monthly_rate': 'lease monthly discount rate',
        }.items()}
        for family in names:
            row = _row(sheet, FAMILIES[family]['label'])
            result.append({'family': family, 'sheet': sheet.title, 'row': row,
                           'columns': periods, 'context_rows': rows,
                           'input_column': identity_cell.column})
    return result


def _paths(archive):
    wb = ET.fromstring(archive.read('xl/workbook.xml'))
    rel = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
    targets = {r.get('Id'): r.get('Target') for r in rel}
    relationship = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
    result = {}
    for sheet in wb.find('m:sheets', NS):
        target = targets[sheet.get(relationship)]
        result[sheet.get('name')] = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
    return result


def present_active_schedules(source, destination, policy=None):
    """Patch OOXML only; caller must execute and validate the new source."""
    policy = policy or {}
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError('Presentation output exists; do not overwrite')
    formulas = openpyxl.load_workbook(source, keep_links=False)
    values = openpyxl.load_workbook(source, data_only=True, keep_links=False)
    try:
        families = discover_families(formulas, policy)
        conversions, by_sheet = [], {}
        for group in families:
            for col in group['columns']:
                cell = formulas[group['sheet']].cell(group['row'], col)
                cache = values[group['sheet']][cell.coordinate]
                if cell.data_type != 'f':
                    raise ValueError('Presentation requires the original complete formula family: ' + group['sheet'] + '!' + cell.coordinate)
                if (type(cache.value) not in (int, float) or not math.isfinite(cache.value)
                        or cache.is_date or cache.data_type == 'e'):
                    raise ValueError('Finite numeric monetary formula cache required')
                if cache.value != 0:
                    continue
                item = {'sheet': group['sheet'], 'cell': cell.coordinate, 'family': group['family'],
                        'original_formula': cell.value, 'original_cached_value': cache.value,
                        'provided_value': 0, 'reason': 'Exact source-audited finite numeric zero; inactive monetary schedule entry.'}
                conversions.append(item)
                by_sheet.setdefault(group['sheet'], {})[cell.coordinate] = item
        note_row = formulas['Lease Read Me'].max_row + 2
        note_address = 'A' + str(note_row)
        with ZipFile(source) as original:
            paths = _paths(original)
            modified = {paths[name] for name in by_sheet} | {paths['Lease Read Me']}
            with ZipFile(destination, 'x') as output:
                for info in original.infolist():
                    raw = original.read(info.filename)
                    name = next((n for n, p in paths.items() if p == info.filename), None)
                    if info.filename in modified:
                        root = ET.fromstring(raw)
                        pending = dict(by_sheet.get(name, {}))
                        for cell in root.findall('.//m:sheetData/m:row/m:c', NS):
                            if cell.get('r') not in pending:
                                continue
                            old = pending.pop(cell.get('r'))
                            formula = cell.find('m:f', NS)
                            value = cell.find('m:v', NS)
                            if formula is None or value is None or Decimal(value.text) != 0:
                                raise ValueError('OOXML zero assertion differs from the typed cache')
                            if cell.get('t') in ('b', 'd', 'e', 's', 'str', 'inlineStr'):
                                raise ValueError('Only finite numeric zeros can be materialized')
                            root_formula = '=' + (formula.text or '')
                            if root_formula != old['original_formula']:
                                raise ValueError('OOXML formula assertion differs')
                            cell.remove(formula)
                            cell.set('t', 'n')
                            value.text = '0'
                        if pending:
                            raise ValueError('Not every declared zero formula was found')
                        if name == 'Lease Read Me':
                            row = ET.SubElement(root.find('m:sheetData', NS), '{' + MAIN + '}row', r=str(note_row))
                            c = ET.SubElement(row, '{' + MAIN + '}c', r=note_address, t='inlineStr')
                            ET.SubElement(ET.SubElement(c, '{' + MAIN + '}is'), '{' + MAIN + '}t').text = NOTE
                            dim = root.find('m:dimension', NS)
                            if dim is not None:
                                _, _, end_col, _ = range_boundaries(dim.get('ref'))
                                dim.set('ref', 'A1:' + get_column_letter(end_col) + str(note_row))
                        raw = ET.tostring(root, encoding='utf-8')
                    output.writestr(copy(info), raw)
            # This is an actual byte comparison, including all31 original source worksheets.
            with ZipFile(destination) as output:
                unchanged = [i.filename for i in original.infolist() if i.filename not in modified]
                if any(original.read(p) != output.read(p) for p in unchanged):
                    raise ValueError('Unselected workbook package part changed')
        return {'version': 1, 'status': 'unvalidated_presentation_only', 'source': ref(source),
                'raw_presentation': ref(destination), 'conversions': conversions,
                'converted_formula_count': len(conversions), 'changed_package_parts': sorted(modified),
                'unchanged_package_part_count': len(unchanged),
                'public_note': {'sheet': 'Lease Read Me', 'cell': note_address, 'value': NOTE},
                'family_selection': families, 'financial_validation_passed': False,
                'selected_for_tasks': False, 'qualified': False}
    finally:
        formulas.close()
        values.close()


def exact_typed_values(path):
    """No cent rounding, date coercion or Boolean/numeric equivalence."""
    book = openpyxl.load_workbook(path, data_only=True, keep_links=False)
    result = {}
    try:
        for sheet in book:
            for cell in sheet._cells.values():
                value = cell.value
                if value is None or value == '':
                    continue
                if cell.data_type == 'e':
                    kind = ('error', str(value))
                elif isinstance(value, bool):
                    kind = ('boolean', value)
                elif isinstance(value, (int, float, Decimal)):
                    number = Decimal(str(value))
                    if not number.is_finite():
                        raise ValueError('Nonfinite value in exact typed comparison')
                    kind = ('number', str(number.normalize()) if number else '0')
                elif isinstance(value, (date, datetime, time)):
                    kind = (type(value).__name__, value.isoformat())
                elif isinstance(value, timedelta):
                    kind = ('timedelta', str(value.total_seconds()))
                else:
                    kind = ('string', str(value))
                result[(sheet.title, cell.coordinate)] = kind
        return result, book.sheetnames[:]
    finally:
        book.close()


def compare_exact_typed(original, completed, *, public_note=None):
    before, names = exact_typed_values(original)
    after, other_names = exact_typed_values(completed)
    allowed = {}
    if public_note:
        key = (public_note['sheet'], public_note['cell'])
        if key in before:
            raise ValueError('Presentation note must occupy a previously empty cell')
        allowed[key] = ('string', public_note['value'])
    mismatches = [{'sheet': s, 'cell': a, 'before': before.get((s, a)), 'after': after.get((s, a))}
                  for s, a in sorted(before.keys() | after.keys())
                  if after.get((s, a)) != (allowed.get((s, a)) if (s, a) in allowed else before.get((s, a)))]
    return {'passed': names == other_names and not mismatches, 'sheet_names_equal': names == other_names,
            'checked_existing_value_cells': len(before), 'mismatches': mismatches,
            'public_note_only_metadata_exception': public_note,
            'comparison': 'Exact typed numeric Decimal(str(cache)) values; no grading/cent normalization.'}


def _canonical(formula, coordinate):
    canonical = Translator(formula, origin=coordinate).translate_formula('ZZ1000')
    return re.sub(r"('Lease Inputs'!)\$?[A-Z]+(?=\$?\d)", r'\1INPUT', canonical).replace(' ', '').upper()


def _mutate(family, cell, context, business=None):
    c, before = get_column_letter(cell.column), cell.value
    business = business or {}
    if business.get('profile') == 'contract_conditioned_v2':
        if family == 'interest':
            # A nominal annual-to-monthly shortcut replaces the contractual
            # effective-rate conversion. No intact correct formula is wrapped.
            return f'=IF({c}{context["active"]}=1,ROUND({c}{context["liability"]}*{c}{context["annual_rate"]}/12,2),0)'
        if business['annual_rate'] == 0 and family in {'measurement_pv', 'nominal_payment'}:
            if business['payment_frequency'] <= 1:
                raise ValueError('Zero-rate omission fault needs a multi-month contractual payment frequency')
            source = "'Lease Inputs'!$" + get_column_letter(business['input_column']) + '$9'
            if family == 'measurement_pv':
                token = '*' + source + ')/(1+' + c + str(context['monthly_rate']) + ')'
                replacement = ')/(1+' + c + str(context['monthly_rate']) + ')'
            else:
                token, replacement = 'ROUND(' + source + '*ROUND(', 'ROUND(ROUND('
            if before.count(token) != 1:
                raise ValueError('Unsupported zero-rate contractual payment-frequency template')
            return before.replace(token, replacement)
    if family == 'measurement_pv':
        token = '-' + c + '$2+1'
        if before.count(token) != 1:
            raise ValueError('Unsupported measurement timing template')
        return before.replace(token, '-' + c + '$2')
    if family == 'depreciation':
        return f'=IF({c}{context["active"]}=1,ROUND({c}{context["rou"]}/({c}{context["end"]}-{c}$2+2),2),0)'
    if family == 'interest':
        return f'=IF({c}{context["active"]}=1,ROUND({c}{context["liability"]}*{c}{context["annual_rate"]},2),0)'
    if family == 'nominal_payment':
        suffix = ',2),0)'
        if not before.endswith(suffix):
            raise ValueError('Unsupported contractual cash template')
        return before[:-len(suffix)] + f'/(1+{c}{context["monthly_rate"]})' + suffix
    raise ValueError('Unknown monetary family')


def propose_debugging_task(baseline, policy=None):
    """Return every remaining selected formula as a root, or fail closed."""
    policy = policy or {}
    book = openpyxl.load_workbook(baseline, keep_links=False)
    cached = openpyxl.load_workbook(baseline, data_only=True, keep_links=False)
    try:
        groups = discover_families(book, policy)
        profile = policy.get('mutation_profile', 'original_v1')
        frequency_row = _row(book['Lease Inputs'], 'payment frequency') if profile == 'contract_conditioned_v2' else None
        edits, correct_templates = [], set()
        for group in groups:
            for col in group['columns']:
                cell = book[group['sheet']].cell(group['row'], col)
                value = cached[group['sheet']][cell.coordinate]
                if cell.data_type != 'f':
                    if type(cell.value) not in (int, float) or cell.value != 0:
                        raise ValueError('Only provided numeric zero constants may leave a selected family')
                    continue
                if type(value.value) not in (int, float) or not math.isfinite(value.value) or value.is_date or value.value == 0:
                    raise ValueError('Selected family contains an unpresented zero or invalid monetary formula')
                before = cell.value
                business = {'profile': profile}
                reason = FAMILIES[group['family']]['fault']
                if profile == 'contract_conditioned_v2':
                    annual_rate = cached[group['sheet']].cell(group['context_rows']['annual_rate'], col).value
                    frequency = book['Lease Inputs'].cell(frequency_row, group['input_column']).value
                    if (type(annual_rate) not in (int, float) or not math.isfinite(annual_rate)
                            or type(frequency) is not int or frequency <= 0):
                        raise ValueError('Finite public discount rate and positive integer payment frequency required')
                    business.update(annual_rate=annual_rate, payment_frequency=frequency,
                                    input_column=group['input_column'])
                    if group['family'] == 'interest':
                        reason = 'Use nominal annual rate divided by twelve instead of the contractual effective monthly rate.'
                    elif annual_rate == 0 and group['family'] in {'measurement_pv', 'nominal_payment'}:
                        reason = 'Mistake monthly base rent for the full multi-month contractual periodic payment.'
                after = _mutate(group['family'], cell, group['context_rows'], business)
                if after == before:
                    raise ValueError('A selected family mutation left its original formula intact')
                correct_templates.add(_canonical(before, cell.coordinate))
                edits.append({'sheet': group['sheet'], 'cell': cell.coordinate, 'before': before,
                              'after': after, 'reason': reason,
                              'business_rule': 'Apply the unchanged public lease timing, measurement and monetary posting policies.',
                              'family_id': group['family']})
                cell.value = after
        if not edits or len(edits) > policy.get('max_roots', 100000):
            raise ValueError('Complete selected root family exceeds the configured bound or is empty')
        donors = []
        for sheet in book:
            for cell in sheet._cells.values():
                if cell.data_type != 'f':
                    continue
                formula = cell.value if isinstance(cell.value, str) else getattr(cell.value, 'text', None)
                if not isinstance(formula, str):
                    raise ValueError('A formula object lacks readable donor evidence')
                try:
                    canonical = _canonical(formula, cell.coordinate)
                except Exception as exc:
                    raise ValueError('Whole-workbook donor canonicalization is unsupported') from exc
                if canonical in correct_templates:
                    donors.append({'sheet': sheet.title, 'cell': cell.coordinate})
        if donors:
            raise ValueError('An intact or mutated complete correct family template remains: ' + json.dumps(donors[:5]))
        return {'title': 'Repair complete lease measurement and posting families',
                'public_instruction': 'Audit and repair the inconsistent financial formulas in the lease schedules and linked reporting. Use the provided contracts and business briefs, preserve all provided inputs, fixed inactive entries, dates and unaffected calculations, and save the completed workbook to /app/output.xlsx.',
                'public_rules': ['The supplied contractual policies, currencies, calendars and rounding conventions govern every period.', 'Provided fixed inactive monetary entries are constants and must remain unchanged.'],
                'reference_evidence': ['Independent source financial audits transferred only through complete exact typed value equivalence.', 'Complete selected monetary families, with all remaining formula members mutated.'],
                'edits': edits, 'mask_ranges': [], 'assumptions_added': [],
                'family_adapter': {'id': 'lease_monetary_complete_v1', 'status': 'planned_not_activity_proven',
                    'family_ids': _families(policy), 'mutation_profile': profile, 'root_count': len(edits),
                    'counts_by_family': dict(Counter(e['family_id'] for e in edits)),
                    'correct_full_template_donors_remaining': 0,
                    'donor_scope': 'Whole-workbook exact relative translation plus lease-input-column namespace canonicalization; not a claim of general algebraic equivalence.',
                    'difficulty_measured': False}}
    finally:
        book.close()
        cached.close()
