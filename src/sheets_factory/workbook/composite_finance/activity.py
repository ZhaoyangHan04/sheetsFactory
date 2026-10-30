"""Private joint-activity screening before normal construction certificates.

A shadow is the original formula evaluated against the fully broken model's
parents. A proven union DAG excludes feedback from restoring a root into its
parents. This checks normalized *own-value* activity, not complete per-root
changed sets, financial correctness, final controls or model difficulty.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import time

import openpyxl
from openpyxl.formula import Tokenizer

from ...checkers.separated_roots import _formula_tokens, _PURE_FUNCTIONS
from ..compare import _raw_values, _normalized_values
from ..profile import formula_references
from ..static_references import static_formula_text

_POSITIONAL = {'ROW', 'COLUMN', 'CELL', 'INDIRECT', 'OFFSET', 'INFO', 'ADDRESS',
               'FORMULATEXT', 'SHEET', 'SHEETS', 'NOW', 'TODAY', 'RAND', 'RANDBETWEEN'}
_A1 = re.compile(r'\$?[A-Z]{1,3}\$?[1-9][0-9]*(?::\$?[A-Z]{1,3}\$?[1-9][0-9]*)?$', re.I)
_SHADOW = '_Private Activity Witness'


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def qualify_original_formula(formula: str, sheet: str) -> str:
    """Qualify reference tokens only; preserve strings, anchors and operators."""
    parsed = Tokenizer(formula)
    for token in parsed.items:
        if token.type == 'FUNC' and token.subtype == 'OPEN':
            name = token.value[:-1].upper()
            if name in _POSITIONAL or name not in _PURE_FUNCTIONS:
                raise ValueError('Position-dependent, dynamic or unknown function: ' + name)
        if token.type == 'OPERAND' and token.subtype == 'RANGE' and '!' not in token.value:
            if not _A1.fullmatch(token.value):
                raise ValueError('Unresolved local reference cannot be shadowed')
            token.value = "'" + sheet.replace("'", "''") + "'!" + token.value
    return parsed.render()


def _union_dag(book, edits, *, max_cells, per_formula_cells, max_edges):
    roots = {(edit['sheet'], edit['cell']): edit for edit in edits}
    if len(roots) != len(edits):
        raise ValueError('Duplicate activity roots')
    state, graph, cache, edge_count = {}, {}, {}, 0
    for root in roots:
        pending = [(root, False)]
        while pending:
            node, leaving = pending.pop()
            if leaving:
                state[node] = 2
                continue
            if state.get(node) == 2:
                continue
            if state.get(node) == 1:
                raise ValueError('Cycle in original/mutated union graph')
            state[node] = 1
            if len(state) > max_cells:
                raise ValueError('Activity union cell bound exceeded')
            sn, address = node
            if sn not in book:
                raise ValueError('Missing activity dependency sheet')
            cell = book[sn][address]
            formulas = []
            if cell.data_type == 'f':
                formulas = ([roots[node]['before'], roots[node]['after']] if node in roots
                            else [static_formula_text(cell)])
            dependencies = set()
            for formula in formulas:
                found = formula_references(formula, sn, max_expansion=per_formula_cells,
                                           workbook=book, cache=cache)
                if not found['fully_supported']:
                    raise ValueError('Unresolved activity dependency; single-root execution required')
                dependencies.update((item['sheet'], item['cell']) for item in found['references'])
            graph[node] = sorted(dependencies)
            edge_count += len(dependencies)
            if edge_count > max_edges:
                raise ValueError('Activity union edge bound exceeded')
            pending.append((node, True))
            for dependency in reversed(graph[node]):
                if state.get(dependency) == 1:
                    raise ValueError('Cycle in original/mutated union graph')
                if state.get(dependency) != 2:
                    pending.append((dependency, False))
    return {'state': 'proven', 'acyclic': True, 'all_before_and_after_formulas_included': True,
            'visited_cells': len(graph), 'dependency_edges': edge_count}


def _values(path, hints=None):
    raw, sheets, epoch = _raw_values(Path(path))
    return _normalized_values(raw, epoch, raw if hints is None else hints), raw, sheets


def screen_composite_activity(baseline: Path, proposal: dict, *, engine, directory: Path,
                              max_authoring_attempts: int = 3,
                              max_dependency_cells: int = 500000,
                              per_formula_reference_cells: int = 50000,
                              max_dependency_edges: int = 10000000,
                              execute_fallback: bool = False,
                              authoring_attempt_number: int | None = None) -> dict:
    """Return a private screened plan and hash-bound executed evidence.

    No input file is modified. At most two authoring versions are created: the
    supplied proposal and one bulk-pruned revision. Inactive removals require
    an additional actual calculation proving every original-sheet value stayed
    unchanged. Position-sensitive shadows are recorded for single-root fallback
    and block acceptance until that fallback is explicitly enabled and executed.
    The returned financial input contains no private witness worksheet.
    """
    if type(max_authoring_attempts) is not int or not 1 <= max_authoring_attempts <= 3:
        raise ValueError('max_authoring_attempts must be an integer from one through three')
    bounds = ((max_dependency_cells, 500000), (per_formula_reference_cells, 50000),
              (max_dependency_edges, 10000000))
    if any(type(value) is not int or not 1 <= value <= maximum for value, maximum in bounds):
        raise ValueError('Unsupported activity analysis bound')
    if type(execute_fallback) is not bool:
        raise ValueError('execute_fallback must be boolean')
    inherited = [1]
    for key, field in [('candidate_repair', 'attempt_number'),
                       ('activity_authoring', 'authoring_attempts_used')]:
        if isinstance(proposal.get(key), dict) and field in proposal[key]:
            inherited.append(proposal[key][field])
    if any(type(value) is not int for value in inherited):
        raise ValueError('Inherited authoring attempts must be integers')
    if authoring_attempt_number is None:
        authoring_attempt_number = max(inherited)
    if (type(authoring_attempt_number) is not int
            or not max(inherited) <= authoring_attempt_number <= max_authoring_attempts):
        raise ValueError('Authoring attempt is outside the cumulative configured budget')
    baseline, directory = Path(baseline).resolve(), Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    baseline_sha, proposal_sha = _sha(baseline), _json_sha(proposal)
    original_plan, result_plan = deepcopy(proposal), deepcopy(proposal)
    receipt = {'version': 1, 'kind': 'private_composite_own_value_activity', 'passed': False,
        'blocking': True, 'state': 'checking', 'baseline_sha256': baseline_sha,
        'before_plan_sha256': proposal_sha, 'actual_LO_execution_count': 0,
        'actual_LO_started_count': 0, 'authoring_attempts_used': authoring_attempt_number,
        'implementation_sha256': _sha(__file__),
        'max_authoring_attempts': max_authoring_attempts, 'model_calls': 0,
        'root_records': [], 'fallback_roots': [], 'engine_calls': [],
        'business_correctness_certified': False, 'final_root_impact_certified': False,
        'private_witness_sheet_in_returned_input': False}
    final_input = None

    def calculate(raw, output, purpose):
        started = time.monotonic()
        record = {'purpose': purpose, 'raw_path': str(raw), 'raw_sha256': _sha(raw),
                  'actual_execution_started': True, 'actual_execution_completed': False}
        receipt['engine_calls'].append(record)
        receipt['actual_LO_started_count'] += 1
        try:
            engine.recalculate(raw, output)
            receipt['actual_LO_execution_count'] += 1
            record.update(actual_execution_completed=True, output_path=str(output), output_sha256=_sha(output))
        finally:
            record['duration_ms'] = round((time.monotonic() - started) * 1000)

    try:
        edits = original_plan.get('edits')
        if not isinstance(edits, list) or not edits:
            raise ValueError('Nonempty debugging formula edits required')
        metadata = engine.metadata()
        if (metadata.get('backend') != 'libreoffice_uno_docker' or metadata.get('network') != 'none'
                or not re.fullmatch(r'sha256:[a-f0-9]{64}', metadata.get('image_id', ''))):
            raise ValueError('Activity screening requires a hash-pinned network-isolated actual LibreOffice engine')
        receipt['engine'] = metadata
        book = openpyxl.load_workbook(baseline, keep_links=False)
        try:
            if _SHADOW in book:
                raise ValueError('Reserved private witness sheet already exists')
            seen = set()
            for edit in edits:
                key = edit['sheet'], edit['cell']
                if key in seen:
                    raise ValueError('Duplicate activity roots')
                seen.add(key)
                cell = book[key[0]][key[1]]
                if (cell.data_type != 'f' or not isinstance(cell.value, str) or cell.is_date
                        or _formula_tokens(cell.value) != _formula_tokens(edit['before'])):
                    raise ValueError('Activity root must assert an existing non-date financial formula')
                if (not isinstance(edit.get('after'), str) or not edit['after'].startswith('=')
                        or _formula_tokens(edit['before']) == _formula_tokens(edit['after'])):
                    raise ValueError('An activity root requires a different Excel formula')
            # Record unsupported shadows even when their dynamic references
            # also prevent the stronger union-DAG proof. No such root is deleted.
            for index, edit in enumerate(edits):
                try:
                    qualify_original_formula(edit['before'], edit['sheet'])
                except ValueError as exc:
                    receipt['fallback_roots'].append({'root_index': index,
                        'root': edit['sheet'] + '!' + edit['cell'],
                        'state': 'requires_single_root_fallback', 'reason': str(exc)})
            receipt['union_graph'] = _union_dag(book, edits, max_cells=max_dependency_cells,
                per_formula_cells=per_formula_reference_cells, max_edges=max_dependency_edges)
            for edit in edits:
                book[edit['sheet']][edit['cell']] = edit['after']
            raw = directory / 'combined_v1_raw.xlsx'
            book.save(raw)
        finally:
            book.close()
        combined = directory / 'combined_v1_actual.xlsx'
        calculate(raw, combined, 'original_combined_mutation')
        before_values, hints, original_sheets = _values(combined)
        book = openpyxl.load_workbook(combined, keep_links=False)
        try:
            shadow = book.create_sheet(_SHADOW)
            receipt['fallback_roots'] = []
            shadow.append(['Private root', 'Original formula against current parents'])
            for index, edit in enumerate(edits):
                root = edit['sheet'] + '!' + edit['cell']
                record = {'root_index': index, 'root': root, 'before': edit['before'], 'after': edit['after'],
                          'mechanism': edit.get('mechanism'), 'event_context': edit.get('event_context')}
                try:
                    formula = qualify_original_formula(edit['before'], edit['sheet'])
                except ValueError as exc:
                    record.update(state='requires_single_root_fallback', reason=str(exc))
                    receipt['fallback_roots'].append(record)
                else:
                    address = 'B' + str(index + 2)
                    shadow.cell(index + 2, 1, root)
                    shadow[address] = formula
                    record.update(shadow_cell=address, qualified_before=formula, state='shadow_pending')
                receipt['root_records'].append(record)
            shadow_raw = directory / 'private_shadow_raw.xlsx'
            book.save(shadow_raw)
        finally:
            book.close()
        shadow_actual = directory / 'private_shadow_actual.xlsx'
        calculate(shadow_raw, shadow_actual, 'private_original_formula_shadows')
        shadow_values, _, shadow_sheets = _values(shadow_actual, hints)
        model_values = {key: value for key, value in shadow_values.items() if key[0] != _SHADOW}
        if shadow_sheets != [*original_sheets, _SHADOW] or model_values != before_values:
            raise ValueError('Private witness addition changed original model values or structure')
        receipt['all_original_sheet_values_unchanged_by_shadow'] = True
        for record in receipt['root_records']:
            key = edits[record['root_index']]['sheet'], edits[record['root_index']]['cell']
            current = before_values.get(key)
            if current is None or current[0] != 'number':
                raise ValueError('Activity root has no finite numeric current value')
            record['current_normalized_value'] = list(current)
            if record['state'] == 'requires_single_root_fallback':
                if not execute_fallback:
                    continue
                edit = edits[record['root_index']]
                book = openpyxl.load_workbook(combined, keep_links=False)
                try:
                    book[edit['sheet']][edit['cell']] = edit['before']
                    fallback_raw = directory / f'fallback_{record["root_index"]:03d}_raw.xlsx'
                    book.save(fallback_raw)
                finally:
                    book.close()
                fallback_actual = directory / f'fallback_{record["root_index"]:03d}_actual.xlsx'
                calculate(fallback_raw, fallback_actual, 'single_root_full_context_fallback')
                fallback_values, _, names = _values(fallback_actual, hints)
                if names != original_sheets:
                    raise ValueError('Fallback restoration changed worksheet structure')
                restored = fallback_values.get(key)
                record['activity_method'] = 'actual_single_root_full_context_restoration'
            else:
                restored = shadow_values.get((_SHADOW, record['shadow_cell']))
                record['activity_method'] = 'actual_shadow_original_formula_under_union_DAG'
            if restored is None or restored[0] != 'number':
                raise ValueError('Original-formula restoration has no finite numeric value')
            record.update(restored_normalized_value=list(restored),
                          state='inactive_own_marginal' if current == restored else 'active_own_marginal')
        pending = [r for r in receipt['root_records'] if r['state'] == 'requires_single_root_fallback']
        if pending:
            receipt.update(state='requires_single_root_fallback', reason='No roots removed while required fallback evidence is missing')
        else:
            inactive = {r['root_index'] for r in receipt['root_records'] if r['state'] == 'inactive_own_marginal'}
            receipt['inactive_root_indices'] = sorted(inactive)
            if inactive and authoring_attempt_number >= max_authoring_attempts:
                receipt.update(state='authoring_attempt_limit', reason='An evidenced pruning revision exceeds the configured authoring attempt limit')
            else:
                if inactive:
                    result_plan['edits'] = [edit for i, edit in enumerate(edits) if i not in inactive]
                    if not result_plan['edits']:
                        raise ValueError('Activity screen removed every candidate root')
                    book = openpyxl.load_workbook(combined, keep_links=False)
                    try:
                        for index in inactive:
                            edit = edits[index]
                            book[edit['sheet']][edit['cell']] = edit['before']
                        filtered_raw = directory / 'combined_v2_pruned_raw.xlsx'
                        book.save(filtered_raw)
                    finally:
                        book.close()
                    filtered = directory / 'combined_v2_pruned_actual.xlsx'
                    receipt['authoring_attempts_used'] = authoring_attempt_number + 1
                    calculate(filtered_raw, filtered, 'bulk_inactive_root_removal')
                    filtered_values, _, names = _values(filtered, hints)
                    if names != original_sheets or filtered_values != before_values:
                        raise ValueError('Bulk root removal changed original-sheet normalized values')
                    receipt['all_original_sheet_values_unchanged_after_bulk_removal'] = True
                    final_input = filtered
                    # Old partitions index the old root list and must never be
                    # reused after removal. Normal batching must recompute them.
                    result_plan['activity_authoring'] = {
                        'authoring_attempts_used': authoring_attempt_number + 1,
                        'max_authoring_attempts': max_authoring_attempts,
                        'original_proposal_sha256': proposal_sha,
                        'private_receipt_path': str(directory / 'activity_receipt.json'),
                        'removed_roots': [edits[index]['sheet'] + '!' + edits[index]['cell']
                                          for index in sorted(inactive)],
                        'final_root_impact_certified': False}
                    result_plan.pop('root_impact_batches', None)
                    result_plan.pop('root_impact_batch_planning', None)
                    if isinstance(result_plan.get('semantic_authoring_receipt'), dict):
                        authoring = result_plan['semantic_authoring_receipt']
                        authoring['selected_count'] = len(result_plan['edits'])
                        authoring['mechanism_counts'] = dict(Counter(e.get('mechanism', 'unspecified') for e in result_plan['edits']))
                else:
                    final_input = combined
                    receipt['all_original_sheet_values_unchanged_after_bulk_removal'] = True
                receipt.update(passed=True, blocking=False, state='screened',
                    retained_root_count=len(result_plan['edits']), removed_root_count=len(inactive),
                    after_plan_sha256=_json_sha(result_plan),
                    required_next_step='Normal fresh combined/native checks, recomputed batches and actual individual/full-context marginal certificates, then controls and quality.')
        if _sha(baseline) != baseline_sha or _json_sha(proposal) != proposal_sha:
            raise ValueError('Source or caller proposal changed during activity screening')
    except Exception as exc:
        receipt.update(passed=False, blocking=True, state='rejected', reason=str(exc), error_type=type(exc).__name__)
        final_input = None
    if receipt['passed'] is not True:
        result_plan = original_plan
    _write(directory / 'activity_receipt.json', receipt)
    _write(directory / 'screened_plan.json', result_plan)
    return {'plan': result_plan, 'receipt': receipt,
            'combined_input': str(final_input) if final_input is not None else None,
            'receipt_path': str(directory / 'activity_receipt.json')}
