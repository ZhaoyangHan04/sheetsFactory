"""Conservative native-error exclusions plus observed LO sensitivity evidence.

Finite sentinels do not prove that a formula never reads an error. Every path
must first be excluded by the narrow fixed-selector dependency certificates.
All probes use fresh private clones; formal source and goal files stay intact.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import time as clock

import openpyxl

from .native_error_dependencies import dependency_error_reach, validate_static_reference_syntax
from ..workbook.profile import formula_references


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def exact_typed_value(cell):
    """Preserve error, boolean, empty, text and unrounded numeric distinctions."""
    value = cell.value
    if cell.data_type == 'e':
        return ['error', str(value)]
    if value is None:
        return ['empty', None]
    if isinstance(value, bool):
        return ['boolean', value]
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError('nonfinite required value at ' + cell.coordinate)
        return ['number', str(number.normalize())]
    if isinstance(value, (datetime, date, time)):
        return [type(value).__name__, value.isoformat()]
    if isinstance(value, timedelta):
        return ['timedelta', str(value.total_seconds())]
    if not isinstance(value, str):
        raise ValueError('unsupported required value type at ' + cell.coordinate)
    return ['string', value]


def _required_values(path, labels):
    book = openpyxl.load_workbook(path, data_only=True, keep_links=False)
    try:
        result = {}
        for label in labels:
            sheet, address = label.rsplit('!', 1)
            if sheet not in book.sheetnames or not re.fullmatch(r'[A-Z]{1,3}[1-9][0-9]*', address):
                raise ValueError('invalid required output: ' + label)
            result[label] = exact_typed_value(book[sheet][address])
        return result, book.sheetnames[:]
    finally:
        book.close()


def _full_closure_candidates(goal, labels, candidates, max_cells):
    """Inspect all D ancestors, including ancestors unique to downstream D."""
    book = openpyxl.load_workbook(goal, keep_links=False)
    values = openpyxl.load_workbook(goal, data_only=True, keep_links=False)
    try:
        found = {(c['sheet'], c['cell']): dict(c) for c in candidates}
        pending = [tuple(label.rsplit('!', 1)) for label in labels]
        visited = set()
        while pending:
            key = pending.pop()
            if key in visited:
                continue
            visited.add(key)
            if len(visited) > max_cells:
                raise ValueError('full required-D dependency closure exceeds supported limit')
            sheet, address = key
            if sheet not in book.sheetnames:
                raise ValueError('Q10: missing sheet in full required-D closure')
            cell, cached = book[sheet][address], values[sheet][address]
            if cached.data_type == 'e':
                found[key] = {'sheet': sheet, 'cell': address, 'cached_error': cached.value,
                              'formula': cell.value if cell.data_type == 'f' else None}
            if cell.data_type != 'f':
                continue
            if not isinstance(cell.value, str) or re.search(r'\b(?:NOW|TODAY|RAND|RANDBETWEEN)\s*\(', cell.value, re.I):
                raise ValueError('Q10: unsupported or volatile full required-D dependency')
            references = formula_references(cell.value, sheet)
            if not references['fully_supported']:
                raise ValueError('Q10: unresolved full required-D dependency')
            syntax_problem = validate_static_reference_syntax(cell.value)
            if syntax_problem:
                raise ValueError('Q10: ' + syntax_problem + ' in full required-D closure')
            pending.extend((r['sheet'], r['cell']) for r in references['references'])
        # Recheck passed candidates against this exact goal; stale evidence is not accepted.
        for sheet, address in found:
            if sheet not in values.sheetnames or values[sheet][address].data_type != 'e':
                raise ValueError('candidate is not an actual cached error in the bound goal')
        return [found[key] for key in sorted(found)], len(visited)
    finally:
        book.close()
        values.close()


def probe_native_errors(*, goal, required_delta, candidates, engine, directory,
                        source_sha256, plan, revision, immutable_files=None,
                        engine_metadata=None, max_candidates=64, max_dependency_cells=20000):
    """Return a persisted, blocking-by-default receipt; never certify business logic."""
    goal, directory = Path(goal), Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    labels = sorted(set(required_delta))
    files = dict(immutable_files or {})
    files['goal'] = goal
    before = {name: {'path': str(Path(path).resolve()), 'sha256': _digest(path)}
              for name, path in files.items()}
    receipt = {'version': 1, 'classification': 'current_scenario_sensitivity_evidence',
        'business_correctness_certificate': False, 'requires_Q04_Q09_review': True,
        'state': 'unknown', 'blocking': True, 'problem_id': 'Q09', 'route_id': 'R09',
        'certainty': 'suspected', 'revision': revision, 'source_sha256': source_sha256,
        'goal_sha256': before['goal']['sha256'], 'plan_sha256': _json_digest(plan),
        'required_delta': labels, 'required_delta_sha256': _json_digest(labels),
        'immutable_before': before, 'engine': engine_metadata or {'backend': type(engine).__name__},
        'candidates': [], 'probes': []}
    started = clock.monotonic()
    try:
        if not labels:
            raise ValueError('complete required-D set is empty')
        expected, sheets = _required_values(goal, labels)
        receipt['required_typed_values_sha256'] = _json_digest(expected)
        errors = [label for label, value in expected.items() if value[0] == 'error']
        if errors:
            receipt.update(state='observed_contamination', certainty='confirmed', problem_id='Q04',
                route_id='R04', reason='Actual goal errors occur in complete required D', goal_error_cells=errors)
            return receipt
        if 'source' in before and before['source']['sha256'] != source_sha256:
            raise ValueError('bound source SHA differs from actual immutable source')
        candidates, count = _full_closure_candidates(goal, labels, candidates, max_dependency_cells)
        receipt.update(candidates=candidates, full_dependency_closure_cells=count)
        if not candidates:
            receipt.update(state='not_applicable', blocking=False,
                reason='No cached native errors in the complete required-D dependency closure')
            return receipt
        if len(candidates) > max_candidates:
            raise ValueError('native-error candidate probe limit exceeded')
        reach = dependency_error_reach(goal, labels, candidates, max_cells=max_dependency_cells)
        receipt['dependency_certificates'] = reach
        remaining = {label: errors for label, errors in reach['per_delta_errors'].items() if errors}
        receipt['uncertified_paths'] = remaining
        # Different finite, coordinate-bound weights prevent the equal-sentinel
        # cancellation that can hide mutually masked errors in a joint probe.
        weights = {}
        for index, candidate in enumerate(candidates):
            label = candidate['sheet'] + '!' + candidate['cell']
            weights[label] = (index + 1) * 1000000 + int(hashlib.sha256(label.encode()).hexdigest()[:8], 16) % 900000 + .125
        assignments = []
        for label, value in weights.items():
            assignments.extend([('single', {label: value}), ('single', {label: -value})])
        assignments.extend([('joint', weights), ('joint', {label: -value for label, value in weights.items()})])
        for index, (kind, replacements) in enumerate(assignments):
            run = directory / f'probe_{index:03d}'
            run.mkdir(exist_ok=True)
            raw, output = run / 'input.xlsx', run / 'recalculated.xlsx'
            probe = {'kind': kind, 'assignments': replacements, 'input': str(raw), 'output': str(output)}
            receipt['probes'].append(probe)
            probe_start = clock.monotonic()
            try:
                # Always clone the pristine goal, never a preceding probe result.
                book = openpyxl.load_workbook(goal, keep_links=False)
                try:
                    for label, value in replacements.items():
                        sheet, address = label.rsplit('!', 1)
                        book[sheet][address] = value
                    book.save(raw)
                finally:
                    book.close()
                probe['input_sha256'] = _digest(raw)
                engine.recalculate(raw, output)
                probe['output_sha256'] = _digest(output)
                actual, actual_sheets = _required_values(output, labels)
                changed = {label: {'before': expected[label], 'after': actual[label]}
                           for label in labels if expected[label] != actual[label]}
                probe.update(required_typed_values_sha256=_json_digest(actual), changed_values=changed,
                             structure_ok=actual_sheets == sheets, state='unchanged' if not changed else 'changed')
                if changed or actual_sheets != sheets:
                    receipt.update(state='observed_required_D_change', certainty='confirmed',
                        causal_attribution='error_sensitivity_or_recalculation_instability_not_distinguished',
                        reason='A recalculated native-error probe has changed required-D typed values or sheet structure; inactivity is not established')
                    return receipt
            except Exception as exc:
                probe.update(state='unknown', error_type=type(exc).__name__, error=str(exc)[:500])
                raise ValueError('Unable to execute or inspect a native-error probe') from exc
            finally:
                probe['duration_ms'] = round((clock.monotonic() - probe_start) * 1000)
        if reach['state'] != 'verified' or remaining:
            receipt['reason'] = 'Not every candidate-to-required-D path has a narrow program certificate; unchanged sentinels cannot clear it'
        else:
            receipt.update(state='current_scenario_inactive', blocking=False,
                reason='All candidate paths excluded by narrow certificates and every single/joint LO probe leaves full typed D unchanged')
    except Exception as exc:
        receipt.update(reason=str(exc)[:500], error_type=type(exc).__name__)
        if str(exc).startswith('Q10:'):
            receipt.update(problem_id='Q10', route_id='R10')
    finally:
        after = {name: _digest(path) if Path(path).is_file() else None for name, path in files.items()}
        receipt['immutable_after'] = after
        receipt['immutable_unchanged'] = all(after[name] == item['sha256'] for name, item in before.items())
        if not receipt['immutable_unchanged']:
            receipt.update(state='unknown', blocking=True, reason='An immutable formal artifact changed during probing')
        receipt['duration_ms'] = round((clock.monotonic() - started) * 1000)
        (directory / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False))
    return receipt
