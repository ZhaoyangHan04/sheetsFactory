"""Independent business identities for the fixed NYU 343-cell descendant scope.

No Excel expression is executed. The 97 additional business values are derived
from literal public inputs and the 112 previously independent financial anchors.
The other 134 values transfer an anchor through exact scalar aliases only.
Original workbooks and caches are read, never changed.
"""
from __future__ import annotations

from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import re

import openpyxl

from .compare import normalize_value

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT/'outputs/research/hardness_iteration/external_sources/normalized/nyu_fcffsimpleginzu.xlsx'
SOURCE_SHA256 = '3efc53bc23c002d4ab994c0add4b4991da4d7c6c072bbc0af465ce428c9ecfcf'
ANCHOR_REPORT = ROOT/'outputs/research/hardness_iteration/external_sources/nyu_dcf_module_business_review.json'
ANCHOR_REPORT_SHA256 = '1337199356c6e8863877cfdd8a86c3f9fa9eae9fe1b736c07d4202a765e9e324'
SCOPE = ROOT/'outputs/research/nyu_scope_audit_97_prospective_20261031T143300Z/scope.json'
SCOPE_SHA256 = '268d7f733a2f24f2257d085b388ed96d0acb00356976e7cd94ef9de331879655'
TEXT_PATCHES = SCOPE.with_name('proposed_text_patches.json')
TEXT_PATCHES_SHA256 = '5eb57a8463fe8103cb57ad18bb9f4eed1bbae3f7fe7f0e06f57c88e9f0c0790f'
V = 'Valuation output'
NO_FLAGS = ('B16', 'B17', 'B37', 'B45', 'B48', 'B51', 'B56', 'B59', 'B61', 'B64', 'B67', 'B70')
NUMERIC_INPUTS = ('B11', 'B12', 'B14', 'B15', 'B18', 'B19', 'B20', 'B21', 'B22', 'B23', 'B24', 'B34', 'B54')
PUBLIC_INPUTS = (*NO_FLAGS, *NUMERIC_INPUTS, 'B53', 'B57')
YEARS = tuple('CDEFGHIJKL')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def reference(path):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_file() and not path.is_symlink(), 'Use a real canonical file')
    data = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def checked(record):
    require(type(record) is dict and set(record) == {'path', 'sha256', 'bytes'}
        and type(record['bytes']) is int, 'A complete artifact reference is required')
    require(reference(record['path']) == record, 'A fixed audit artifact changed')
    return Path(record['path'])


def pinned(path, digest):
    record = reference(path)
    require(record['sha256'] == digest, 'The fixed NYU source, scope, or independent anchor evidence changed')
    return record


def number(value):
    require(type(value) in (int, float, Decimal), 'An independently supplied finite number is required')
    result = Decimal(str(value))
    require(result.is_finite(), 'A nonfinite financial value is unsupported')
    return result


def ratio(numerator, denominator):
    require(denominator != 0, 'The declared financial ratio has a zero denominator')
    return numerator/denominator


def address(sheet, cell):
    return sheet+'!'+cell


def business_addresses():
    result = {address('Input sheet', cell) for cell in ('J34', 'J35', 'J36')}
    result |= {address(V, cell) for cell in ('M3', 'M5', 'N5', 'N8', 'B23', 'B35', 'M40')}
    result |= {address(V, col+'10') for col in (*YEARS, 'M')}
    result |= {address(V, col+str(row)) for col in YEARS for row in (39, 40)}
    result |= {address('Stories to Numbers', cell) for cell in ('F12', 'D13', 'F13', 'B27', 'D33', 'D36', 'D39')}
    result |= {address('Stories to Numbers', col+str(row)) for row in range(17, 28) for col in ('D', 'G')}
    result |= {address('Valuation as picture', cell) for cell in ('P9', 'P10', 'O17', 'O19', 'B30')}
    result |= {address('Valuation as picture', col+'29') for col in 'EFGHIJKLMNO'}
    result |= {address('Diagnostics', cell) for cell in ('B21', 'C21', 'B22', 'C22', 'C23', 'C27', 'D27', 'E27', 'C31', 'B36', 'B37')}
    require(len(result) == 97, 'The fixed business census changed')
    return result


def derive_business(public_inputs, independent_anchors):
    """Small cash, capital, return and value model; accepts no formula strings."""
    require(set(public_inputs) == set(PUBLIC_INPUTS), 'The complete literal public input scope is required')
    require(all(type(public_inputs[key]) is str and public_inputs[key] == 'No' for key in NO_FLAGS)
        and public_inputs['B53'] == 'V' and type(public_inputs['B57']) is int and public_inputs['B57'] == 1,
        'This bounded audit requires the original explicit mode flags and one-year lag')
    with localcontext() as context:
        context.prec = 50
        p = {key: number(public_inputs[key]) for key in NUMERIC_INPUTS}
        a = {key: number(value) for key, value in independent_anchors.items()}
        get = lambda cell: a[address(V, cell)]
        require(p['B11'] > 0 and p['B21'] > 0 and p['B22'] > 0,
            'This snapshot requires positive revenue, shares and quoted price')
        capital = p['B14']+p['B15']-p['B18']
        require(capital > 0, 'A positive base invested-capital balance is required')
        base_capital = capital
        base_nopat = p['B12']*(1-p['B23']) if p['B12'] > 0 else p['B12']
        growth = p['B34']  # Public overrides are all No: stable growth is the stated risk-free rate.
        terminal_revenue = get('L3')*(1+growth)
        terminal_ebit = get('L5')*(1+growth)  # Year-ten operating margin persists in the terminal year.
        terminal_roic = get('L12')  # Public no-excess-return policy: mature ROIC equals year-ten WACC.
        terminal_reinvestment_rate = ratio(growth, terminal_roic)
        out = {}
        def put(sheet, cell, value):
            key = address(sheet, cell)
            require(key not in out, 'A business identity was assigned twice')
            out[key] = value
        put(V, 'M3', terminal_revenue)
        put(V, 'M5', terminal_ebit)
        put(V, 'N5', terminal_ebit-p['B12'])
        put(V, 'N8', sum((get(col+'8') for col in YEARS), Decimal(0))+get('M8'))
        put(V, 'M40', terminal_roic)
        # Loss carryforwards increase by operating losses and are consumed by positive EBIT.
        losses = Decimal(0)
        annual_roic = []
        for col in (*YEARS, 'M'):
            ebit = get(col+'5') if col != 'M' else terminal_ebit
            losses = max(Decimal(0), losses-ebit)
            put(V, col+'10', losses)
            if col != 'M':
                annual_roic.append(ratio(get(col+'7'), capital))
                put(V, col+'40', annual_roic[-1])
                capital += get(col+'8')
                put(V, col+'39', capital)
        # Distress proceeds remain a meaningful disclosed value even when failure probability is zero.
        put(V, 'B23', get('B21')*p['B54'])
        price_to_value = ratio(p['B22'], get('B33'))
        put(V, 'B35', price_to_value)
        incremental_return = ratio(get('L7')-base_nopat, capital-base_capital)
        for cell, value in [('J34', terminal_revenue), ('J35', terminal_ebit), ('J36', annual_roic[-1])]:
            put('Input sheet', cell, value)
        for cell, value in [('F12', terminal_reinvestment_rate), ('D13', incremental_return), ('F13', terminal_roic), ('B27', terminal_revenue)]:
            put('Stories to Numbers', cell, value)
        for row, col in zip(range(17, 28), (*YEARS, 'M')):
            put('Stories to Numbers', 'D'+str(row), get(col+'5') if col != 'M' else terminal_ebit)
            put('Stories to Numbers', 'G'+str(row), get(col+'7')-get(col+'8'))
        equity = get('B24')-p['B15']-p['B20']+p['B18']+p['B19']
        put('Stories to Numbers', 'D33', Decimal(0))  # No probability of failure: no distress adjustment.
        put('Stories to Numbers', 'D36', equity)
        put('Stories to Numbers', 'D39', ratio(equity, p['B21']))  # No employee-option dilution.
        for cell, value in [('P9', terminal_roic), ('P10', terminal_reinvestment_rate), ('O17', terminal_revenue), ('O19', terminal_ebit), ('B30', price_to_value-1)]:
            put('Valuation as picture', cell, value)
        for col, value in zip('EFGHIJKLMNO', [*annual_roic, terminal_roic]):
            put('Valuation as picture', col+'29', value)
        operating_pv = sum((get(col+'7')*get(col+'13') for col in YEARS), Decimal(0))
        reinvestment_pv = sum((get(col+'8')*get(col+'13') for col in YEARS), Decimal(0))
        put('Diagnostics', 'B21', operating_pv)
        put('Diagnostics', 'C21', ratio(operating_pv, operating_pv))
        put('Diagnostics', 'B22', reinvestment_pv)
        put('Diagnostics', 'C22', ratio(reinvestment_pv, operating_pv))
        put('Diagnostics', 'C23', ratio(operating_pv-reinvestment_pv, operating_pv))
        put('Diagnostics', 'C27', incremental_return)
        put('Diagnostics', 'D27', annual_roic[-1])
        put('Diagnostics', 'E27', terminal_roic)
        put('Diagnostics', 'C31', ratio(Decimal(1), get('L13'))**(Decimal(1)/10)-1)
        value_to_price = ratio(get('B33'), p['B22'])
        put('Diagnostics', 'B36', value_to_price)
        # These thresholds and messages are a fixed reporting convention, not a valuation assumption.
        put('Diagnostics', 'B37', 'Value seems high. See below' if value_to_price > 2 else
            'Value seems low. See below' if value_to_price < Decimal('0.5') else ' ')
        require(set(out) == business_addresses(), 'The independent business implementation must cover exactly all97 cells')
        return out


_ALIAS = re.compile(r"^=(?:(?:'((?:[^']|'')+)'|([^'!]+))!)?\$?([A-Z]+)\$?([1-9][0-9]*)$")


def scalar_alias(formula, current_sheet):
    require(type(formula) is str, 'An exact scalar alias formula is required')
    match = _ALIAS.fullmatch(formula)
    require(match is not None, 'Only exact scalar aliases may transfer an independently audited value')
    sheet = (match[1].replace("''", "'") if match[1] else match[2]) or current_sheet
    return address(sheet, match[3]+match[4])


def identity_transfers(alias_rows, independent_anchors, formula_lookup):
    result, proofs = {}, []
    for row in alias_rows:
        start = address(row['sheet'], row['cell'])
        seen, chain, current = set(), [], start
        while current not in independent_anchors:
            require(current not in seen, 'A scalar alias chain is circular')
            seen.add(current)
            sheet, _ = current.rsplit('!', 1)
            formula = formula_lookup(current)
            target = scalar_alias(formula, sheet)
            chain.append({'from': current, 'formula': formula, 'to': target})
            current = target
        require(current == address(row['alias_of']['sheet'], row['alias_of']['cell']),
            'The alias chain no longer ends at its exact independently audited anchor')
        result[start] = independent_anchors[current]
        proofs.append({'address': start, 'independent_anchor': current, 'exact_scalar_chain': chain,
            'identity_transfer_only': True, 'financial_expression_evaluated': False})
    require(len(result) == len(alias_rows), 'Duplicate aliases cannot inflate the coverage count')
    return result, proofs


def audit(*, observed_ref=None, sheet_prefix=''):
    """Read-only scoped numeric audit, with explicit presentation/policy bounds."""
    refs = {'source': pinned(SOURCE, SOURCE_SHA256), 'anchor_report': pinned(ANCHOR_REPORT, ANCHOR_REPORT_SHA256),
        'prospective_scope': pinned(SCOPE, SCOPE_SHA256), 'required_text_patches': pinned(TEXT_PATCHES, TEXT_PATCHES_SHA256),
        'auditor': reference(__file__), 'typed_comparison': reference(Path(__file__).with_name('compare.py'))}
    scope = json.loads(checked(refs['prospective_scope']).read_text())
    closure = json.loads(checked(scope['original_closure']).read_text())
    refs['original_closure'] = scope['original_closure']
    require(scope['complete_scope_frozen_before_expected_value_computation'] is True
        and len(scope['audited_core112']) == 112 and len(scope['additional_alias_only_chains134']) == 134
        and {address(row['sheet'], row['cell']) for row in scope['additional_other97']} == business_addresses(),
        'The complete prospective112+134+97 scope is required')
    report = json.loads(checked(refs['anchor_report']).read_text())
    candidates = [item for item in report['sources'] if item['normalized_sha256'] == SOURCE_SHA256]
    require(len(candidates) == 1 and candidates[0]['all_checks_match'] is True, 'The original independent financial anchor source differs')
    anchors = {row['address']: Decimal(row['independent_expected']) for row in candidates[0]['independent_checks']}
    require(set(anchors) == {address(row['sheet'], row['cell']) for row in scope['audited_core112']}
        and len(anchors) == 112, 'Exactly112 distinct independently audited anchor values are required')
    formula_book = openpyxl.load_workbook(SOURCE, data_only=False, keep_links=False)
    source_book = openpyxl.load_workbook(SOURCE, data_only=True, keep_links=False)
    observed = refs['source'] if observed_ref is None else observed_ref
    checked(observed)
    observed_book = openpyxl.load_workbook(observed['path'], data_only=True, keep_links=False)
    try:
        public = {}
        for cell in PUBLIC_INPUTS:
            raw = formula_book['Input sheet'][cell]
            require(raw.data_type != 'f', 'A public business input must be an original provided literal')
            public[cell] = raw.value
        for row in [*scope['additional_other97'], *scope['additional_alias_only_chains134']]:
            require(formula_book[row['sheet']][row['cell']].value == row['formula'], 'A frozen formula identity changed')
        business = derive_business(public, anchors)
        def lookup(key):
            sheet, cell = key.rsplit('!', 1)
            return formula_book[sheet][cell].value
        transferred, proofs = identity_transfers(scope['additional_alias_only_chains134'], anchors, lookup)
        expected = {**anchors, **business, **transferred}
        require(len(expected) == 343 and set(expected) == {
            address(row['sheet'], row['cell']) for row in closure['full_static_reverse_closure343']},
            'The entire fixed343 scope must be covered exactly once')
        rows = []
        for key, value in sorted(expected.items()):
            sheet, cell = key.rsplit('!', 1)
            source_cell = source_book[sheet][cell]
            actual = observed_book[sheet_prefix+sheet][cell]
            typed = normalize_value(value)
            rows.append({'address': key, 'expected': str(value) if isinstance(value, Decimal) else value,
                'expected_typed': typed, 'source_cached_typed': normalize_value(source_cell.value, source_cell.data_type),
                'observed_cached_typed': normalize_value(actual.value, actual.data_type),
                'source_matches': normalize_value(source_cell.value, source_cell.data_type) == typed,
                'observed_matches': normalize_value(actual.value, actual.data_type) == typed})
        patch = json.loads(checked(refs['required_text_patches']).read_text())
        require(all(formula_book[row['sheet']][row['cell']].value == row['original_typed_text']
            for row in patch['patches']), 'The declared source presentation exception changed')
    finally:
        formula_book.close()
        source_book.close()
        observed_book.close()
    return {'kind': 'independent_NYU_fixed343_scoped_numeric_business_audit', 'version': 1,
        'references': refs, 'observed': observed, 'sheet_prefix': sheet_prefix,
        'coverage': {'previous_independent_anchors': 112, 'new_business_cells': 97, 'exact_scalar_alias_transfers': 134, 'total': 343},
        'all_scoped_numeric_checks_passed': all(row['source_matches'] and row['observed_matches'] for row in rows),
        'checks': rows, 'expected_typed_by_original_address': {row['address']: row['expected_typed'] for row in rows},
        'scalar_identity_transfer_proofs': proofs, 'public_literal_inputs': public,
        'business_rules': ['Invested capital equals provided equity plus debt less cash; annual reinvestment adds to capital.',
            'Annual ROIC uses NOPAT divided by beginning-of-year capital.',
            'Terminal revenue and EBIT grow at the disclosed stable rate with year-ten margin unchanged.',
            'Stable ROIC equals year-ten cost of capital under the original no-excess-return flag.',
            'Incremental return is NOPAT change through year10 per total reinvestment booked in years1-10.',
            'PV of operating earnings and reinvestment are separately discounted annual business flows.',
            'Equity deducts debt and minority interests and adds cash and non-operating assets; options and failure are off.',
            'Price/value and value/price diagnostics use the original provided quotation and independently audited intrinsic value.'],
        'presentation_exceptions_require_new_task_corrections': patch['patches'],
        'diagnostic_public_rule': patch['diagnostic_public_rule'],
        'diagnostic_horizon_unique_from_lag_alone': False,
        'financial_expressions_evaluated_or_replayed': False,
        'original112_scope_not_replaced': True, 'whole1231_or4430_formula_certificate': False,
        'new_LO_calls': 0, 'new_model_calls': 0, 'new_solver_calls': 0, 'new_Harbor_calls': 0,
        'workbook_writes': 0, 'task_or_difficulty_qualification': False, 'qualified': False}
