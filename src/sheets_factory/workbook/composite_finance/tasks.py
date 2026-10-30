"""Deterministic completion plans for the documented composite finance model.

This adapter selects calculation definitions, not answers. Recognition and mask
coverage do not certify financial correctness, controls, quality or difficulty;
those remain the normal pipeline's independent, executed checks.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
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


def propose_task(baseline: Path, mode: str = 'financial_modeling') -> dict:
    """Return a standard FM proposal, without editing or evaluating the workbook.

    The adapter deliberately rejects debugging: cross-module mutation semantics
    need their own root-impact proof rather than reusing this completion mask.
    """
    if mode != 'financial_modeling':
        raise ValueError('Composite task template currently supports financial_modeling only')
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
        targets = [*lease_names, 'Lease Monthly', 'Lease Annual', *_REGULATORY,
                   *('Operating ' + name for name in _OPERATING), *_HOLDING]
        cached = openpyxl.load_workbook(Path(baseline), data_only=True, keep_links=False)
        masks = []
        for name in targets:
            sheet = book[name]
            excluded_rows = {1, 2} if (name.startswith('Lease ') or name.startswith('Reopener ')
                                             or name in _HOLDING) else {1}
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
