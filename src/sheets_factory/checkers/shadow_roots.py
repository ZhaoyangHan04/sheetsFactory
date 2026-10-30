"""Lower-bound individual and marginal impacts from two private actual replays.

Only a complete, pure, static original/mutated UNION DAG is accepted. For each
root, its parents cannot depend on that root in either context. Moving a
scalar-safe AFTER formula into the original model therefore evaluates its
mutation-alone own value; moving BEFORE into the combined model evaluates its
restoration-alone own value. Roots may depend on other roots. The certificate
does not claim complete changed sets or executions of individual counterfactual
workbooks, and does not certify financial correctness or difficulty.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import time

import openpyxl
from openpyxl.formula import Tokenizer
from openpyxl.utils.cell import range_boundaries
from openpyxl.xml.functions import tostring

from .native_error_dependencies import validate_static_reference_syntax
from .native_error_probe import exact_typed_value
from .separated_roots import _formula_tokens, _unchanged_definitions, _PURE_FUNCTIONS
from ..workbook.compare import normalize_value
from ..workbook.composite_finance.activity import qualify_original_formula, _POSITIONAL
from ..workbook.profile import formula_references
from ..workbook.static_references import static_formula_text

_SHADOW = '_Private Root Witness'
_CELL = re.compile(r'[A-Z]{1,3}[1-9][0-9]*$')
_REDUCERS = {'SUM', 'AVERAGE', 'MIN', 'MAX', 'COUNT', 'COUNTA', 'PRODUCT', 'SUMSQ'}
_RANGE_ARGUMENTS = {'SUMIF': lambda i: i in (0, 2), 'AVERAGEIF': lambda i: i in (0, 2),
    'SUMIFS': lambda i: i == 0 or i % 2 == 1,
    'AVERAGEIFS': lambda i: i == 0 or i % 2 == 1,
    'COUNTIF': lambda i: i == 0, 'COUNTIFS': lambda i: i % 2 == 0,
    'COUNTBLANK': lambda i: i == 0, 'NPV': lambda i: i >= 1,
    'XNPV': lambda i: i in (1, 2), 'IRR': lambda i: i == 0,
    'XIRR': lambda i: i in (0, 1), 'ROWS': lambda i: i == 0,
    'COLUMNS': lambda i: i == 0, 'MATCH': lambda i: i == 1,
    'XMATCH': lambda i: i == 1, 'VLOOKUP': lambda i: i == 1,
    'HLOOKUP': lambda i: i == 1, 'LOOKUP': lambda i: i in (1, 2)}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def _label(key):
    return key[0] + '!' + key[1]


def _pure(text, label):
    problem = validate_static_reference_syntax(text)
    if problem:
        raise ValueError(problem + ' at ' + label)
    for token in Tokenizer(text).items:
        if token.type == 'FUNC' and token.subtype == 'OPEN':
            name = token.value[:-1].upper()
            if name in _POSITIONAL or name not in _PURE_FUNCTIONS:
                raise ValueError('Position-dependent, volatile, dynamic or unknown dependency function ' + name + ' at ' + label)
        if token.type == 'OPERAND' and token.subtype == 'ERROR':
            raise ValueError('Formula error literal at ' + label)


def qualify_scalar_shadow(formula, sheet):
    """Reject implicit intersection in addition to explicit positional functions.

    SUMPRODUCT forces array evaluation. Other admitted range operands must be
    the complete argument of a known scalar reducer/lookup, in its array role.
    INDEX/CHOOSE can return references and are conservatively rejected at roots.
    These restrictions apply to moved root formulas, not financial algorithms.
    """
    qualified = qualify_original_formula(formula, sheet)
    syntax = validate_static_reference_syntax(qualified)
    if syntax:
        raise ValueError(syntax)
    tokens = Tokenizer(qualified).items
    frames, ranges = [], []
    for index, token in enumerate(tokens):
        if token.type == 'FUNC' and token.subtype == 'OPEN':
            name = token.value[:-1].upper()
            if name in {'INDEX', 'CHOOSE', 'XLOOKUP', 'SUBTOTAL'}:
                raise ValueError('Reference/array-context function is not eligible for scalar shadows: ' + name)
            frames.append({'kind': 'FUNC', 'name': name, 'argument': 0, 'start': index + 1})
        elif token.type in ('PAREN', 'ARRAY') and token.subtype == 'OPEN':
            if token.type == 'ARRAY':
                raise ValueError('Array literals require an explicit scalar shadow adapter')
            frames.append({'kind': token.type})
        elif token.type == 'SEP' and token.subtype == 'ARG':
            if not frames or frames[-1]['kind'] != 'FUNC':
                raise ValueError('Ambiguous formula argument context')
            frame = frames[-1]
            for record in ranges:
                if record.get('frame') is frame and record.get('stop') is None:
                    record['stop'] = index
            frame['argument'] += 1
            frame['start'] = index + 1
        elif token.subtype == 'CLOSE' and token.type in ('FUNC', 'PAREN', 'ARRAY'):
            if not frames or frames[-1]['kind'] != token.type:
                raise ValueError('Unbalanced shadow expression')
            frame = frames.pop()
            for record in ranges:
                if record.get('frame') is frame and record.get('stop') is None:
                    record['stop'] = index
        elif token.type == 'OPERAND' and token.subtype == 'RANGE':
            address = token.value.rsplit('!', 1)[-1]
            if ':' not in address:
                continue
            if any(frame.get('name') == 'SUMPRODUCT' for frame in frames):
                continue
            if not frames or frames[-1]['kind'] != 'FUNC':
                raise ValueError('Implicit intersection or unconsumed range at shadow root')
            frame = frames[-1]
            name, argument = frame['name'], frame['argument']
            if name not in _REDUCERS and not _RANGE_ARGUMENTS.get(name, lambda i: False)(argument):
                raise ValueError('Range in non-scalar or implicit-intersection function argument')
            ranges.append({'frame': frame, 'start': frame['start'], 'stop': None, 'index': index})
    if frames:
        raise ValueError('Unbalanced shadow expression')
    for record in ranges:
        if record['stop'] is None:
            raise ValueError('Unclosed scalar range argument')
        significant = [i for i in range(record['start'], record['stop']) if tokens[i].type != 'WHITE-SPACE']
        if significant != [record['index']]:
            raise ValueError('Array arithmetic outside explicit SUMPRODUCT is not scalar-shadow eligible')
    return qualified


def _visibility(book):
    return [(sheet.title, sheet.sheet_state, sorted(str(r) for r in sheet.merged_cells.ranges),
        sorted((key, bool(dim.hidden)) for key, dim in sheet.row_dimensions.items() if dim.hidden),
        sorted((key, bool(dim.hidden)) for key, dim in sheet.column_dimensions.items() if dim.hidden),
        tostring(sheet.auto_filter.to_tree())) for sheet in book]


def _same_definitions(left, right, roots):
    count = _unchanged_definitions(left, right, roots)
    if _visibility(left) != _visibility(right):
        raise ValueError('Provided sheet visibility, merges or filters differ')
    # The shared lexical comparison intentionally tolerates LO sheet quoting.
    # A changed whitespace intersection must never pass that normalization.
    for sheet in left:
        other = right[sheet.title]
        for key, cell in sheet._cells.items():
            if ((sheet.title, cell.coordinate) not in roots and cell.data_type == 'f'
                    and isinstance(cell.value, str)):
                counterpart = other._cells.get(key)
                if counterpart is not None and counterpart.value != cell.value:
                    for text in (cell.value, counterpart.value):
                        if validate_static_reference_syntax(text):
                            raise ValueError('Unproven non-root formula lexical equivalence: ' + sheet.title + '!' + cell.coordinate)
    return count


def _groups(book):
    result = {}
    for sheet in book:
        bounds = []
        for cell in sheet._cells.values():
            if cell.data_type != 'f' or isinstance(cell.value, str):
                continue
            try:
                box = range_boundaries(cell.value.ref)
                if box != (cell.column, cell.row, cell.column, cell.row):
                    bounds.append(box)
            except (ValueError, TypeError, AttributeError):
                bounds.append((1, 1, 16384, 1048576))
        result[sheet.title] = bounds
    return result


def _cache(cell, *, formula=False):
    result = exact_typed_value(cell)
    if result[0] == 'error' or (formula and result[0] == 'empty'):
        raise ValueError('Error or missing formula cache at ' + cell.parent.title + '!' + cell.coordinate)
    return result


def _union_graph(original, mutated, original_values, mutated_values, edits, *, max_cells, max_edges, per_formula_cells):
    roots = {(edit['sheet'], edit['cell']): edit for edit in edits}
    pending, graph, parse_cache = list(roots), {}, {}
    groups = _groups(original)
    functions, formula_count, resolved_names, edge_count = set(), 0, 0, 0
    while pending:
        key = pending.pop()
        if key in graph:
            continue
        if len(graph) >= max_cells:
            raise ValueError('Complete union dependency cell bound exceeded; no frontier is omitted')
        sn, address = key
        if sn not in original or sn not in mutated:
            raise ValueError('Unresolved dependency sheet at ' + _label(key))
        cell = original[sn][address]
        if any(left <= cell.column <= right and top <= cell.row <= bottom
               for left, top, right, bottom in groups[sn]):
            raise ValueError('Unsupported multi-cell formula group at ' + _label(key))
        for book, values in ((original, original_values), (mutated, mutated_values)):
            _cache(values[sn][address], formula=book[sn][address].data_type == 'f')
        graph[key] = set()
        if cell.data_type != 'f':
            continue
        formula_count += 1
        formulas = [roots[key]['before'], roots[key]['after']] if key in roots else [static_formula_text(cell)]
        for text in formulas:
            refs = formula_references(text, sn, workbook=original, max_expansion=per_formula_cells,
                                      cache=parse_cache, include_resolved_formula=True)
            if not refs['fully_supported']:
                raise ValueError('Unresolved complete dependency at ' + _label(key) + ': ' + str(refs['unsupported']))
            expanded = refs['resolved_formula']
            _pure(expanded, _label(key))
            resolved_names += len(refs.get('resolved_names', []))
            functions.update(token.value[:-1].upper() for token in Tokenizer(expanded).items
                             if token.type == 'FUNC' and token.subtype == 'OPEN')
            graph[key].update((ref['sheet'], ref['cell']) for ref in refs['references'])
        edge_count += len(graph[key])
        if edge_count > max_edges:
            raise ValueError('Complete union dependency edge bound exceeded; no frontier is omitted')
        pending.extend(graph[key] - graph.keys())
    indegree = dict.fromkeys(graph, 0)
    for dependencies in graph.values():
        for key in dependencies:
            indegree[key] += 1
    ready = deque(key for key, count in indegree.items() if count == 0)
    removed = 0
    while ready:
        key = ready.popleft()
        removed += 1
        for parent in graph[key]:
            indegree[parent] -= 1
            if indegree[parent] == 0:
                ready.append(parent)
    if removed != len(graph):
        raise ValueError('Cycle in original/mutated UNION graph')
    return {'state': 'proven', 'acyclic': True, 'closure_cells': len(graph),
        'formula_cells': formula_count, 'dependency_edges': edge_count,
        'all_reference_branches_included': True, 'all_before_after_formulas_included': True,
        'frontier_omitted': False, 'resolved_name_occurrences': resolved_names,
        'all_ancestor_functions_pure_and_position_independent': True, 'functions': sorted(functions),
        'root_dependencies_on_other_roots_allowed': True,
        'graph_sha256': _json_sha([[_label(key), sorted(_label(parent) for parent in parents)]
                                 for key, parents in sorted(graph.items())])}


def _exact_values(book, names):
    return {(name, cell.coordinate): exact_typed_value(cell)
        for name in names for cell in book[name]._cells.values() if cell.value is not None}


def prove_shadow_root_impacts(*, goal, combined_input, edits, engine, directory,
                             max_dependency_cells=20000, per_formula_reference_cells=5000,
                             max_dependency_edges=None):
    """Execute two shadow contexts and return a fail-closed family certificate.

    All scratch workbooks stay in a fresh private directory. The caller retains
    goal/input provenance and still performs complete-D/native/control/quality
    checks. Failure never returns partially proven root impacts or a fallback.
    """
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    receipt = {'version': 1, 'passed': False, 'blocking': True, 'state': 'checking',
        'proof_method': 'two_actual_scalar_shadow_contexts_under_complete_union_DAG',
        'root_impacts': [], 'root_checks': [], 'contexts': [], 'engine_calls': [],
        'actual_LO_started_count': 0, 'actual_LO_execution_count': 0,
        'individual_root_LO_executions': 0, 'individual_marginal_LO_executions': 0,
        'counts_are_lower_bounds': True, 'complete_per_root_changed_sets_claimed': False,
        'business_correctness_certificate': False, 'difficulty_claimed': False,
        'model_calls': 0, 'private_witness_exported': False,
        'implementation_sha256': _sha(__file__)}
    books, executing = [], False
    try:
        for value, upper, name in ((max_dependency_cells, 500000, 'max_dependency_cells'),
            (per_formula_reference_cells, 50000, 'per_formula_reference_cells')):
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError('Invalid ' + name)
        if max_dependency_edges is None:
            max_dependency_edges = max(10000, 20 * max_dependency_cells)
        if type(max_dependency_edges) is not int or not 1 <= max_dependency_edges <= 10000000:
            raise ValueError('Invalid max_dependency_edges')
        paths = {'goal': Path(goal), 'combined_input': Path(combined_input)}
        for name, path in paths.items():
            if path.is_symlink() or not path.is_file():
                raise ValueError('Missing or symlink ' + name)
            paths[name] = path.resolve()
            receipt[name + '_path'] = str(paths[name])
            receipt[name + '_sha256'] = _sha(path)
        if paths['goal'] == paths['combined_input']:
            raise ValueError('Distinct original and combined contexts are required')
        if not isinstance(edits, list) or not edits:
            raise ValueError('Nonempty debugging formula edits required')
        receipt['edits_sha256'] = _json_sha(edits)
        private_edits = deepcopy(edits)
        metadata = engine.metadata()
        if (metadata.get('backend') != 'libreoffice_uno_docker' or metadata.get('network') != 'none'
                or not re.fullmatch(r'sha256:[a-f0-9]{64}', metadata.get('image_id', ''))):
            raise ValueError('Hash-pinned network-isolated actual LibreOffice engine required')
        receipt['engine'] = metadata
        receipt['analysis_limits'] = {'max_dependency_cells': max_dependency_cells,
            'per_formula_reference_cells': per_formula_reference_cells, 'max_dependency_edges': max_dependency_edges}
        for path in paths.values():
            books.append(openpyxl.load_workbook(path, keep_links=False))
            books.append(openpyxl.load_workbook(path, data_only=True, keep_links=False))
        original, original_values, mutated, mutated_values = books
        if any(name.casefold() == _SHADOW.casefold() for name in original.sheetnames):
            raise ValueError('Reserved private witness worksheet already exists')
        roots, qualified = set(), {'individual': [], 'combined_marginal': []}
        for index, edit in enumerate(private_edits):
            if not isinstance(edit, dict):
                raise ValueError('Invalid root assertion')
            sn, address = edit.get('sheet'), edit.get('cell')
            if not isinstance(sn, str) or not isinstance(address, str) or not _CELL.fullmatch(address):
                raise ValueError('Invalid root coordinate')
            _, _, right, bottom = range_boundaries(address)
            if right > 16384 or bottom > 1048576:
                raise ValueError('Root outside Excel bounds')
            key = sn, address
            if key in roots or sn not in original or sn not in mutated:
                raise ValueError('Duplicate or missing root')
            roots.add(key)
            for book, values, field in ((original, original_values, 'before'), (mutated, mutated_values, 'after')):
                text = edit.get(field)
                cell, cached = book[sn][address], values[sn][address]
                if (cell.data_type != 'f' or not isinstance(cell.value, str)
                        or not isinstance(text, str) or not text.startswith('=')
                        or _formula_tokens(cell.value) != _formula_tokens(text)):
                    raise ValueError(field + ' formula assertion mismatch at ' + _label(key))
                if cell.is_date or cached.is_date or _cache(cached, formula=True)[0] != 'number':
                    raise ValueError('Finite non-date numeric root required at ' + _label(key))
            if _formula_tokens(edit['before']) == _formula_tokens(edit['after']):
                raise ValueError('Unchanged root formula at ' + _label(key))
            qualified['individual'].append(qualify_scalar_shadow(edit['after'], sn))
            qualified['combined_marginal'].append(qualify_scalar_shadow(edit['before'], sn))
        receipt['root_count'] = len(roots)
        receipt['unchanged_non_root_definition_count'] = _same_definitions(original, mutated, roots)
        receipt['union_graph'] = _union_graph(original, mutated, original_values, mutated_values,
            private_edits, max_cells=max_dependency_cells, max_edges=max_dependency_edges,
            per_formula_cells=per_formula_reference_cells)
        context_values = {}
        for kind, base_name, formula_book, value_book in (
                ('individual', 'goal', original, original_values),
                ('combined_marginal', 'combined_input', mutated, mutated_values)):
            for name, path in paths.items():
                if _sha(path) != receipt[name + '_sha256']:
                    raise ValueError('Context workbook changed during shadow proof: ' + name)
            witness = formula_book.create_sheet(_SHADOW)
            witness.append(['Private root identity', 'Private counterfactual formula'])
            for index, edit in enumerate(private_edits):
                witness.cell(index + 2, 1, edit['sheet'] + '!' + edit['cell'])
                witness.cell(index + 2, 2, qualified[kind][index])
            raw = directory / (kind + '_shadow_raw.xlsx')
            actual = directory / (kind + '_shadow_actual.xlsx')
            formula_book.save(raw)
            formula_book.remove(witness)
            call = {'purpose': kind + '_own_value_counterfactuals', 'context': base_name,
                'context_sha256': receipt[base_name + '_sha256'], 'raw_path': str(raw),
                'raw_sha256': _sha(raw), 'actual_execution_started': True,
                'actual_execution_completed': False}
            receipt['engine_calls'].append(call)
            receipt['actual_LO_started_count'] += 1
            call_start = time.monotonic()
            executing = True
            try:
                engine.recalculate(raw, actual)
                call.update(actual_execution_completed=True, output_path=str(actual), output_sha256=_sha(actual))
                receipt['actual_LO_execution_count'] += 1
            finally:
                call['duration_ms'] = round((time.monotonic() - call_start) * 1000)
            executing = False
            actual_formula = openpyxl.load_workbook(actual, keep_links=False)
            actual_values = openpyxl.load_workbook(actual, data_only=True, keep_links=False)
            try:
                if actual_formula.sheetnames != [*formula_book.sheetnames, _SHADOW]:
                    raise ValueError('Private shadow altered business worksheet structure')
                observed = []
                for index in range(len(private_edits)):
                    cell = actual_formula[_SHADOW].cell(index + 2, 2)
                    if cell.data_type != 'f' or _formula_tokens(static_formula_text(cell)) != _formula_tokens(qualified[kind][index]):
                        raise ValueError('Actual shadow formula does not match its qualified assertion')
                    cached = actual_values[_SHADOW].cell(index + 2, 2)
                    value = _cache(cached, formula=True)
                    if cached.is_date or value[0] != 'number':
                        raise ValueError('Nonfinite or nonnumeric actual scalar shadow result')
                    observed.append({'exact': value, 'normalized': list(normalize_value(cached.value, cached.data_type))})
                actual_formula.remove(actual_formula[_SHADOW])
                _same_definitions(formula_book, actual_formula, set())
                before = _exact_values(value_book, formula_book.sheetnames)
                after = _exact_values(actual_values, formula_book.sheetnames)
                if before != after:
                    different = sorted(_label(key) for key in before.keys() | after.keys() if before.get(key) != after.get(key))
                    receipt['business_value_changes'] = {'context': base_name, 'count': len(different), 'cells': different}
                    raise ValueError('Private shadow changed exact typed business-sheet values')
                context_values[kind] = observed
                receipt['contexts'].append({'kind': kind, 'base': base_name,
                    'all_business_definitions_unchanged': True, 'all_business_exact_typed_values_unchanged': True,
                    'business_value_count': len(before), 'business_values_sha256': _json_sha([
                        [_label(key), value] for key, value in sorted(before.items())]),
                    'shadow_count': len(observed), 'actual_LO_call_index': len(receipt['engine_calls']) - 1})
            finally:
                actual_formula.close()
                actual_values.close()
        impacts = []
        for index, edit in enumerate(private_edits):
            sn, address = edit['sheet'], edit['cell']
            label = sn + '!' + address
            original_cell, combined_cell = original_values[sn][address], mutated_values[sn][address]
            left = list(normalize_value(original_cell.value, original_cell.data_type))
            right = list(normalize_value(combined_cell.value, combined_cell.data_type))
            individual, marginal = context_values['individual'][index], context_values['combined_marginal'][index]
            check = {'root_index': index, 'root': label, 'individual_active': left != individual['normalized'],
                'combined_marginal_active': right != marginal['normalized'],
                'goal_normalized_value': left, 'after_in_original_parents': individual,
                'combined_normalized_value': right, 'before_in_combined_parents': marginal,
                'exact_goal_value': exact_typed_value(original_cell),
                'exact_combined_value': exact_typed_value(combined_cell)}
            receipt['root_checks'].append(check)
            lower = {'expected_change_count': 1, 'expected_changes': [label],
                'counts_are_lower_bounds': True, 'actual_individual_LO_execution': False,
                'actual_context_shadow_LO_execution': True,
                'proof_method': 'actual_scalar_shadow_value_and_complete_union_DAG'}
            impacts.append({**lower, 'root_index': index, 'evidence': check,
                'combined_marginal': {**lower, 'edits_reversed': True, 'base': 'full_combined_mutation'}})
        if any(not check['individual_active'] or not check['combined_marginal_active'] for check in receipt['root_checks']):
            raise ValueError('At least one root lacks normalized individual or full-context own-value activity')
        for name, path in paths.items():
            if _sha(path) != receipt[name + '_sha256']:
                raise ValueError('Context workbook changed during shadow proof: ' + name)
        if _json_sha(edits) != receipt['edits_sha256']:
            raise ValueError('Caller edit assertions changed during shadow proof')
        receipt.update(passed=True, blocking=False, state='proven', root_impacts=impacts,
            guarantee='Every root changes its own graded numeric value when mutated alone on the original baseline and restored alone in the full combined mutation. Two actual scalar-shadow contexts and an exact-context-invariant pure union DAG prove these nonempty lower bounds; no individual workbook execution or complete changed set is claimed.')
    except Exception as exc:
        receipt.update(passed=False, blocking=True, state='execution_error' if executing else 'rejected',
            reason=str(exc), error_type=type(exc).__name__, root_impacts=[])
    finally:
        for book in books:
            book.close()
    receipt['duration_ms'] = round((time.monotonic() - started) * 1000)
    _write(directory / 'shadow_roots_certificate.json', receipt)
    return receipt
