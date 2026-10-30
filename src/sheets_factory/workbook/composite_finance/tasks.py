"""Deterministic completion plans for the documented composite finance model.

This adapter selects calculation definitions, not answers. Recognition and mask
coverage do not certify financial correctness, controls, quality or difficulty;
those remain the normal pipeline's independent, executed checks.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
import json
import math
from pathlib import Path
import re

import openpyxl

from ..derived_gold.task_templates import _formula_rectangles


_REGULATORY = (
    'Reopener RAV', 'Reopener Tax Basis', 'Reopener Claims',
    'Reopener Tax Loss', 'Reopener Statements',
)
_OPERATING = (
    'Operations', 'Assets', 'Debt', 'Tax', 'Cash Flow', 'Balance Sheet',
    'Equity Value', 'Annual Statements', 'Covenants', 'Tax Vintages',
)
_HOLDING = ('Holding Operating Link', 'Holding Statements', 'Holding Consolidated')
_PROVIDED = (
    'Lease Read Me', 'Lease Inputs', 'Lease Events', 'Lease Calendar',
    'Reopener Brief', 'Reopener Inputs', 'Reopener Assets',
    'Operating Read Me', 'Operating Source Inputs', 'Operating Scenario',
    'Operating Calendar', 'Holding Brief', 'Holding Inputs',
)
_LEASE_STATE = frozenset(('active_flag', 'event_flag', 'event_kind_code', 'measurement_flag',
    'event_index_ratio', 'event_new_rate', 'event_rate_changed', 'event_new_end',
    'event_retention_fraction', 'lease_index_factor', 'lease_retained_exposure',
    'annual_discount_rate', 'lease_monthly_discount_rate', 'lease_current_end_month'))
_OPERATING_STATE = frozenset(('year', 'period', 'periods', 'model year', 'month days',
    'start date', 'end date', 'annual discount rate', 'monthly discount rate',
    'optional allocation allowed', 'test due', 'test passed', 'lock open',
    'passes open', 'passes close', 'lock close'))


def _label(value):
    return re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).strip()


def _row(sheet, label):
    matches = [cell.row for cell in sheet['A'] if _label(cell.value) == label]
    if len(matches) != 1:
        raise ValueError(f'Composite model requires one {label!r} label on {sheet.title}')
    return matches[0]


def _lease_sheets(book):
    """Read the public contract identities instead of assuming four lease IDs."""
    sheet = book['Lease Inputs']
    identity_row = _row(sheet, 'lease id')
    identities = [cell.value for cell in sheet[identity_row][2:] if cell.value is not None]
    if (not identities or any(not isinstance(value, str) or not value.strip() for value in identities)
            or len(set(identities)) != len(identities)):
        raise ValueError('Composite model requires unique public lease contract identities')
    names = ['Lease ' + identity for identity in identities]
    if any(name not in book for name in names):
        raise ValueError('Composite model is missing a public lease contract schedule')
    recognized = {*names, 'Lease Read Me', 'Lease Inputs', 'Lease Events',
                  'Lease Calendar', 'Lease Monthly', 'Lease Annual'}
    if any(name.startswith('Lease ') and name not in recognized for name in book.sheetnames):
        raise ValueError('Unrecognized lease schedule requires an explicit template adapter')
    return names


def _is_date_formula(formula_cell, cached_cell):
    # Cached cell typing catches a date even when a normalized formula's style
    # is General. The formula style also works on unrecalculated authoring files.
    return (formula_cell.is_date or cached_cell.is_date
            or isinstance(cached_cell.value, (date, datetime, time, timedelta)))


def _policy_evidence(book):
    evidence = []
    for name in ('Lease Read Me', 'Reopener Brief', 'Operating Read Me', 'Holding Brief'):
        paragraphs = [cell for cell in book[name]._cells.values()
                      if isinstance(cell.value, str) and len(cell.value.split()) >= 8]
        if not paragraphs:
            raise ValueError('Composite model lacks public business policies on ' + name)
        evidence.append(f'Public business policy: {name} ({len(paragraphs)} populated policy paragraphs).')
    return evidence


def _financial_scope(book):
    """Only an explicit public contingent contract opts into the new mask policy."""
    if 'Model Input Contracts' not in book:
        return None
    sheet = book['Model Input Contracts']
    identities = [cell.value for cell in sheet['A'] if cell.value in ('contingent', 'waterfall')]
    if not identities:
        return None
    if 'contingent' not in identities:
        raise ValueError('A waterfall composite requires the explicit contingent financial-only contract revision')
    records = {}
    for row in range(1, sheet.max_row + 1):
        name = sheet.cell(row, 1).value
        if name not in ('lease', 'programme', 'operating', 'holding', 'contingent', 'waterfall'):
            continue
        if name in records:
            raise ValueError('Duplicate public module contract: ' + name)
        try:
            value = json.loads(sheet.cell(row, 2).value)
        except (ValueError, TypeError) as exc:
            raise ValueError('Invalid public module contract: ' + name) from exc
        if not isinstance(value, dict) or not value:
            raise ValueError('Explicit nonempty public module contract required: ' + name)
        records[name] = value
    if not {'lease', 'programme', 'operating', 'holding', 'contingent'}.issubset(records):
        raise ValueError('Financial-only composite requires all five explicit public module contracts')
    from ..lease_finance.excel import FIELDS, ANNUAL_FIELDS
    from ..contingent_recovery.excel import ANNUAL_ROWS, LABELS
    money = {_label(field) for field in FIELDS if field not in _LEASE_STATE}
    scope = {'version': 'composite_financial_only_v3', 'lease_money': money,
             'lease_aggregate_money': {_label(field) for field in ANNUAL_FIELDS},
             'contingent_money': {_label(field) for field in ANNUAL_ROWS} | {_label(text) for text in LABELS.values()},
             'extra_sheets': ['Contingent Annual']}
    if 'waterfall' in records:
        from ..partner_waterfall.contract import FINANCIAL_FIELDS
        from ..partner_waterfall.schema import FIELDS as PARTNER_FIELDS
        scope.update(version='composite_financial_only_v4',
                     partner_money={_label(field) for field in FINANCIAL_FIELDS},
                     partner_provided={_label(field) for field in PARTNER_FIELDS if field not in FINANCIAL_FIELDS})
        scope['extra_sheets'].append('Partner Waterfall')
    for name in scope['extra_sheets']:
        if name not in book:
            raise ValueError('Missing explicit financial-only module schedule: ' + name)
    if 'waterfall' not in records and 'Partner Waterfall' in book:
        raise ValueError('Partner waterfall schedule requires an explicit public waterfall contract')
    return scope


def _financial_output(sheet, cell, scope):
    """Use public field identities; numeric flags alone are not finance outputs."""
    name = sheet.title
    label_cell = sheet._cells.get((cell.row, 1))
    label = _label(label_cell.value if label_cell is not None else None)
    if name.startswith('Lease '):
        allowed = scope['lease_aggregate_money'] if name in ('Lease Monthly', 'Lease Annual') else scope['lease_money']
        if label in allowed:
            return True
        if label in {_label(field) for field in _LEASE_STATE}:
            return False
        raise ValueError('Unrecognized lease calculation field: ' + name + '!' + cell.coordinate)
    if name.startswith('Operating '):
        return label not in _OPERATING_STATE
    if name == 'Partner Waterfall':
        if label in scope['partner_money']:
            return True
        if label in scope['partner_provided']:
            return False
        raise ValueError('Unrecognized partner calculation field: ' + cell.coordinate)
    if name == 'Contingent Annual' and label not in scope['contingent_money']:
        raise ValueError('Unrecognized contingent calculation field: ' + cell.coordinate)
    # Reopener's five schedules, the holding's three schedules, and the nine
    # contingent outputs are monetary schedules. Dates and FY headers are
    # separately protected by their row, column and cached date identities.
    return True


def propose_task(baseline: Path, mode: str = 'financial_modeling') -> dict:
    """Return a standard FM proposal, without editing or evaluating the workbook.

    Debugging delegates to the independent semantic-defect adapter. Its activity
    screen and root-impact certificates remain normal pipeline requirements.
    """
    if mode == 'debugging':
        from .debugging import propose_task as propose_debugging_task
        return propose_debugging_task(baseline, mode=mode)
    if mode != 'financial_modeling':
        raise ValueError('Composite task template supports financial_modeling or debugging only')
    book = openpyxl.load_workbook(Path(baseline), data_only=False, keep_links=False)
    cached = None
    try:
        required = {*_PROVIDED, *_REGULATORY, *_HOLDING, 'Lease Monthly', 'Lease Annual',
                    *('Operating ' + name for name in _OPERATING)}
        missing = sorted(required.difference(book.sheetnames))
        if missing:
            raise ValueError('Unrecognized composite finance model; missing sheets: ' + ', '.join(missing))
        lease_names = _lease_sheets(book)
        evidence = _policy_evidence(book)
        financial_scope = _financial_scope(book)
        targets = [*lease_names, 'Lease Monthly', 'Lease Annual', *_REGULATORY,
                   *('Operating ' + name for name in _OPERATING), *_HOLDING]
        if financial_scope:
            targets.extend(financial_scope['extra_sheets'])
            evidence.append('Financial-only reconstruction scope: nonmonetary event, calendar and contractual state helpers remain provided.')
            for name in ('Contingent Contract', 'Partner Contract'):
                if name in book:
                    paragraphs = [c for c in book[name]._cells.values() if isinstance(c.value, str) and len(c.value.split()) >= 8]
                    if not paragraphs:
                        raise ValueError('Composite model lacks public business policies on ' + name)
                    evidence.append('Public business policy: ' + name + '.')
        cached = openpyxl.load_workbook(Path(baseline), data_only=True, keep_links=False)
        masks = []
        for name in targets:
            sheet = book[name]
            excluded_rows = {1, 2} if (name.startswith('Lease ') or name.startswith('Reopener ')
                                             or name in _HOLDING or name in ('Contingent Annual', 'Partner Waterfall')) else {1}
            if name == 'Operating Annual Statements':
                excluded_rows |= {_row(sheet, label) for label in ('start date', 'end date')}
            cells = set()
            for cell in sheet._cells.values():
                if cell.data_type != 'f' or cell.row in excluded_rows:
                    continue
                # Column A is a date and B is a fiscal identifier, not a missing
                # economic calculation, in this otherwise vertical bridge.
                if name == 'Holding Operating Link' and cell.column <= 2:
                    continue
                cache = cached[name][cell.coordinate]
                if _is_date_formula(cell, cache):
                    continue
                if financial_scope:
                    if not _financial_output(sheet, cell, financial_scope):
                        continue
                    # A nullable displayed XIRR has no numeric reconstruction
                    # target before its public qualification condition holds.
                    if name == 'Partner Waterfall' and _label(sheet.cell(cell.row, 1).value) == 'lp xirr' and cache.value in (None, ''):
                        continue
                    if (type(cache.value) not in (int, float) or not math.isfinite(cache.value)
                            or cache.data_type == 'e'):
                        raise ValueError(f'Finite cached financial output required: {name}!{cell.coordinate}')
                if isinstance(cache.value, str):
                    raise ValueError(f'Non-numeric financial formula requires an explicit adapter: {name}!{cell.coordinate}')
                cells.add((cell.row, cell.column))
            if not cells:
                raise ValueError('Missing complete composite financial calculation family: ' + name)
            ranges = _formula_rectangles(name, cells)
            for item in ranges:
                item['reason'] = 'Complete the connected hypothetical financial calculation family.'
                item['business_rule'] = 'Apply the provided public module policies, original calendars and explicitly stated units.'
            masks.extend(ranges)
        instruction = (
            'Complete the missing calculations in this hypothetical integrated financing model over the reporting periods '
            'shown. Read the Lease, Reopener, Operating and Holding business briefs and use their provided assumptions '
            'and contracts. Restore the lease measurements, capital programme, tax and revenue schedules, operating '
            'project, parent funding and consolidated statements consistently across the modules. Respect their original '
            'calendars, currencies, ownership interests and closing balances. The published regulatory workbook is '
            'provided background; the additional programme follows its stated hypothetical policies. Preserve inputs, '
            'dates, labels and unaffected calculations, and save the completed workbook to the required output path.'
        )
        if financial_scope:
            partnership = ', partnership distributions' if 'partner_money' in financial_scope else ''
            instruction = (
                'Complete the missing financial outputs in this hypothetical integrated financing model over the periods shown. '
                'Use the provided public business briefs, contractual inputs and existing nonmonetary state helpers. '
                'Complete lease measurement and cash flows, regulatory capital and tax recovery, same-year contingent rents, '
                'the operating investment, parent funding' + partnership + ' and consolidated statements consistently. '
                'Respect the original reporting calendars, currencies, ownership interests and closing balances. '
                'The published regulatory workbook supplies background for the separately stated hypothetical programme. '
                'Preserve inputs, dates, labels and provided calculations, and save the completed workbook to the required output path.'
            )
        return {
            'title': 'Complete the integrated capital programme, leases and holding model',
            'business_context': 'A hypothetical regulatory capital programme connected to lease obligations, an operating associate and parent funding.',
            'public_instruction': instruction,
            'public_rules': ['Use the provided inputs and explicit public business policies for each module, including their stated intercompany links and units.'],
            'reference_evidence': evidence,
            'target_sheets': targets, 'involved_sheets': list(book.sheetnames),
            'protected_inputs': [f"'{name.replace(chr(39), chr(39) * 2)}'!{book[name].calculate_dimension()}"
                                 for name in book.sheetnames if name not in targets],
            'scenario_inputs': [], 'edits': [], 'mask_ranges': masks, 'native_issues': [],
        }
    finally:
        book.close()
        if cached is not None:
            cached.close()
