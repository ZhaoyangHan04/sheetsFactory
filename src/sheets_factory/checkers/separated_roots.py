"""Sound lower-bound root impacts from static separation and actual caches.

Callers supply the *actual*, already LibreOffice-recalculated combined input
and goal. This module performs no recalculation and claims no individual or
marginal execution. Complete-D comparison and financial validation remain
separate gates. A changed root itself witnesses both effects when neither its
original nor mutated ancestor closure can read any edited root.
"""
from __future__ import annotations

from collections import deque
import hashlib
import json
from pathlib import Path
import re

import openpyxl
from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils.cell import range_boundaries

from .native_error_dependencies import validate_static_reference_syntax
from .native_error_probe import exact_typed_value
from ..workbook.compare import _normalized_values
from ..workbook.profile import formula_references
from ..workbook.static_references import static_formula_text


_CELL = re.compile(r"[A-Z]{1,3}[1-9][0-9]*$")
# Only deterministic, explicitly referenced functions are admitted. Unknown
# add-ins, environment/data functions and reference construction fail closed.
_PURE_FUNCTIONS = set("""
ABS ACOS ACOSH AND ASIN ASINH ATAN ATAN2 ATANH AVERAGE AVERAGEIF AVERAGEIFS
CEILING CEILING.MATH CEILING.PRECISE CHAR CHOOSE CLEAN CODE COLUMN COLUMNS
CONCAT CONCATENATE COS COSH COUNT COUNTA COUNTBLANK COUNTIF COUNTIFS DATE
DATEDIF DATEVALUE DAY DAYS DAYS360 DB DDB DEGREES DOLLAR EFFECT EDATE EOMONTH
EVEN EXACT EXP FALSE FIND FIXED FLOOR FLOOR.MATH FLOOR.PRECISE FV HLOOKUP
HOUR IF IFERROR IFNA INDEX INT IPMT IRR ISBLANK ISERR ISERROR ISEVEN ISLOGICAL
ISNA ISNONTEXT ISNUMBER ISODD ISREF ISTEXT LARGE LEFT LEN LN LOG LOG10 LOOKUP
LOWER MATCH MAX MAXIFS MID MIN MINIFS MINUTE MOD MONTH MROUND N NA NETWORKDAYS
NETWORKDAYS.INTL NOMINAL NOT NPER NPV ODD OR PI PMT POWER PPMT PRODUCT PROPER
PV QUOTIENT RADIANS RATE REPLACE REPT RIGHT ROUND ROUNDDOWN ROUNDUP ROW ROWS
SEARCH SECOND SIGN SIN SINH SMALL SQRT SUBSTITUTE SUBTOTAL SUM SUMIF SUMIFS
SUMPRODUCT SUMSQ TAN TANH TEXT TEXTJOIN TIME TIMEVALUE TRIM TRUE TRUNC UPPER
VALUE VLOOKUP WEEKDAY WEEKNUM WORKDAY WORKDAY.INTL XIRR XLOOKUP XMATCH XNPV
XOR YEAR YEARFRAC
""".split())


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _label(key):
    return key[0] + '!' + key[1]


def _formula_tokens(formula):
    """Canonicalize only lexical Excel equivalents, never arithmetic."""
    result = []
    for token in Tokenizer(formula).items:
        if token.type == 'WHITE-SPACE':
            continue
        value = token.value
        if token.type == 'OPERAND' and token.subtype == 'RANGE':
            if '!' in value:
                sheet, address = value.rsplit('!', 1)
                if sheet.startswith("'") and sheet.endswith("'"):
                    sheet = sheet[1:-1].replace("''", "'")
                value = (sheet.casefold(), address.upper())
            else:
                value = value.upper()
        elif token.type == 'FUNC' or token.subtype == 'LOGICAL':
            value = value.upper()
        result.append((token.type, token.subtype, value))
    return result


def _cell_definition(cell):
    if cell.data_type == 'f':
        value = cell.value
        if isinstance(value, str):
            return ['formula', _formula_tokens(value)]
        # Formula groups outside the analyzed closure must also be unchanged.
        return ['formula_group', type(value).__name__, dict(vars(value))]
    return exact_typed_value(cell)


def _names(book):
    return [(scope, key, dict(vars(value)))
        for scope, values in [(None, book.defined_names),
                              *((sheet.title, sheet.defined_names) for sheet in book)]
        for key, value in sorted(values.items())]


def _unchanged_definitions(goal, combined, roots):
    if goal.sheetnames != combined.sheetnames or goal.epoch != combined.epoch:
        raise ValueError('workbook structure or date epoch differs')
    if _names(goal) != _names(combined):
        raise ValueError('defined names differ outside formula edits')
    if getattr(goal.calculation, 'iterate', False) or getattr(combined.calculation, 'iterate', False):
        raise ValueError('iterative workbook calculation is unsupported')
    if getattr(goal.calculation, 'fullPrecision', None) is False or getattr(combined.calculation, 'fullPrecision', None) is False:
        raise ValueError('precision-as-displayed calculation is unsupported')
    count = 0
    for sheet in goal:
        other = combined[sheet.title]
        for coordinate in set(sheet._cells) | set(other._cells):
            left, right = sheet._cells.get(coordinate), other._cells.get(coordinate)
            # Formatting-only cells do not change the calculation graph.
            if (left is None or left.value is None) and (right is None or right.value is None):
                continue
            address = (left or right).coordinate
            if (sheet.title, address) in roots:
                continue
            if left is None or right is None or _cell_definition(left) != _cell_definition(right):
                raise ValueError('non-root formula or literal differs: ' + sheet.title + '!' + address)
            count += 1
    return count


def _finite_cache(cell, *, formula=False):
    value = exact_typed_value(cell)
    if value[0] == 'error':
        raise ValueError('cached error: ' + cell.coordinate)
    if formula and cell.value is None:
        raise ValueError('missing formula cache: ' + cell.coordinate)
    return value


def _graph(book, cached, roots, *, max_cells, max_edges, per_formula_cells):
    """Build every root ancestor, with no branch narrowing or dropped refs."""
    pending = list(sorted(roots))
    formula_groups = {}
    for sheet in book:
        groups = []
        for cell in sheet._cells.values():
            if cell.data_type == 'f' and not isinstance(cell.value, str):
                ref = getattr(cell.value, 'ref', None)
                try:
                    bounds = range_boundaries(ref)
                    if bounds != (cell.column, cell.row, cell.column, cell.row):
                        groups.append(bounds)
                except (ValueError, TypeError):
                    # An unbounded group cannot support a static proof.
                    groups.append((1, 1, 16384, 1048576))
        formula_groups[sheet.title] = groups
    visited, adjacency, parse_cache, parents, origins = set(), {}, {}, {}, {}
    for root in roots:
        parents[root], origins[root] = None, root
    coverage = {'state': 'checking', 'root_count': len(roots), 'closure_cells': 0,
        'formula_cells': 0, 'dependency_edges': 0, 'resolved_name_occurrences': 0,
        'bounded_whole_ranges': 0, 'unsupported': [], 'root_ancestor_paths': [],
        'coverage': 'complete union of all edited-root ancestor closures',
        'all_reference_branches_included': True, 'branch_narrowing_used': False}
    try:
        while pending:
            key = pending.pop()
            if key in visited:
                continue
            visited.add(key)
            if len(visited) > max_cells:
                raise ValueError('dependency closure cell bound exceeded')
            sn, address = key
            if sn not in book.sheetnames:
                raise ValueError('missing dependency sheet: ' + sn)
            cell, value = book[sn][address], cached[sn][address]
            if any(left <= cell.column <= right and top <= cell.row <= bottom
                   for left, top, right, bottom in formula_groups[sn]):
                raise ValueError('unsupported formula group in dependency closure: ' + _label(key))
            _finite_cache(value, formula=cell.data_type == 'f')
            adjacency[key] = set()
            if cell.data_type != 'f':
                continue
            coverage['formula_cells'] += 1
            text = static_formula_text(cell)
            refs = formula_references(text, sn, max_expansion=per_formula_cells,
                workbook=book, cache=parse_cache, include_resolved_formula=True)
            if not refs['fully_supported']:
                raise ValueError('unsupported dependency at ' + _label(key) + ': ' + str(refs['unsupported']))
            expanded = refs['resolved_formula']
            syntax = validate_static_reference_syntax(expanded)
            if syntax:
                raise ValueError(syntax + ' at ' + _label(key))
            for token in Tokenizer(expanded).items:
                if token.type == 'FUNC' and token.subtype == 'OPEN':
                    name = token.value[:-1].upper()
                    if name not in _PURE_FUNCTIONS:
                        raise ValueError('unsupported or nondeterministic function ' + name + ' at ' + _label(key))
                if token.type == 'OPERAND' and token.subtype == 'ERROR':
                    raise ValueError('formula error literal at ' + _label(key))
            coverage['resolved_name_occurrences'] += len(refs.get('resolved_names', []))
            coverage['bounded_whole_ranges'] += len(refs.get('bounded_ranges', []))
            for ref in refs['references']:
                target = (ref['sheet'], ref['cell'])
                adjacency[key].add(target)
                if target in roots:
                    path, cursor = [key], key
                    while parents.get(cursor) is not None:
                        cursor = parents[cursor]
                        path.append(cursor)
                    path.reverse()
                    path.append(target)
                    coverage['root_ancestor_paths'].append([_label(item) for item in path])
                    raise ValueError('edited root is an ancestor of an edited root: ' + ' -> '.join(map(_label, path)))
                if target not in parents:
                    parents[target], origins[target] = key, origins[key]
                pending.append(target)
            coverage['dependency_edges'] += len(adjacency[key])
            if coverage['dependency_edges'] > max_edges:
                raise ValueError('dependency edge bound exceeded')
        # A cycle not containing an edit can still make root values stateful.
        indegree = {key: 0 for key in adjacency}
        for children in adjacency.values():
            for child in children:
                indegree[child] += 1
        ready = deque(key for key, count in indegree.items() if count == 0)
        removed = 0
        while ready:
            key = ready.popleft()
            removed += 1
            for child in adjacency[key]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if removed != len(adjacency):
            raise ValueError('cycle in root dependency closure')
        coverage['state'] = 'proven'
        coverage['acyclic'] = True
        coverage['no_edited_root_ancestor'] = True
        coverage['graph_sha256'] = _json_digest([
            [_label(key), sorted(_label(child) for child in children)]
            for key, children in sorted(adjacency.items())])
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        coverage.update(state='rejected', reason=str(exc), acyclic=False,
                        no_edited_root_ancestor=False)
        coverage['unsupported'].append(str(exc))
    coverage['closure_cells'] = len(visited)
    return coverage, visited


def certify_separated_roots(*, goal, combined_input, edits,
                            max_dependency_cells=20000,
                            per_formula_reference_cells=5000,
                            max_dependency_edges=None):
    """Return a fail-closed certificate and proven *lower-bound* impacts.

    Files must already contain actual LO caches. This function cannot prove
    their execution provenance; its caller retains that engine receipt. Only
    ordinary formula edits are supported. No fallback, workbook write, solver
    or recalculation is performed here.
    """
    receipt = {'version': 1, 'passed': False, 'blocking': True, 'state': 'rejected',
        'proof_method': 'separated_roots_with_actual_combined_LO_values',
        'business_correctness_certificate': False, 'root_impacts': [], 'graphs': {},
        'individual_LO_executions': 0, 'marginal_LO_executions': 0,
        'combined_cache_provenance': 'caller-supplied actual already-recalculated workbook; engine receipt retained by caller',
        'counts_are_lower_bounds': True}
    books = []
    try:
        for name, value, upper in [('max_dependency_cells', max_dependency_cells, 500000),
                                  ('per_formula_reference_cells', per_formula_reference_cells, 50000)]:
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError('invalid ' + name)
        if max_dependency_edges is None:
            max_dependency_edges = max(10000, max_dependency_cells * 20)
        if type(max_dependency_edges) is not int or not 1 <= max_dependency_edges <= 10000000:
            raise ValueError('invalid max_dependency_edges')
        receipt['analysis_limits'] = {'max_dependency_closure_cells': max_dependency_cells,
            'per_formula_reference_cells': per_formula_reference_cells,
            'max_dependency_edges': max_dependency_edges}
        paths = {'goal': Path(goal), 'combined_input': Path(combined_input)}
        for name, path in paths.items():
            if not path.is_file() or path.is_symlink():
                raise ValueError('missing or symlink ' + name)
            receipt[name + '_sha256'] = _digest(path)
            receipt[name + '_path'] = str(path.resolve())
        if not isinstance(edits, list) or not edits:
            raise ValueError('nonempty edits list required')
        receipt['edits_sha256'] = _json_digest(edits)
        for path in (paths['goal'], paths['combined_input']):
            books.append(openpyxl.load_workbook(path, keep_links=False))
            books.append(openpyxl.load_workbook(path, data_only=True, keep_links=False))
        original, original_values, mutated, mutated_values = books
        roots = set()
        for edit in edits:
            if not isinstance(edit, dict):
                raise ValueError('invalid edit assertion')
            sn, address = edit.get('sheet'), edit.get('cell')
            if not isinstance(sn, str) or not isinstance(address, str) or not _CELL.fullmatch(address):
                raise ValueError('invalid edit coordinate')
            _, _, right, bottom = range_boundaries(address)
            if right > 16384 or bottom > 1048576:
                raise ValueError('edit coordinate outside Excel bounds')
            key = sn, address
            if key in roots or sn not in original.sheetnames or sn not in mutated.sheetnames:
                raise ValueError('duplicate or missing edit root')
            roots.add(key)
            before, after = edit.get('before'), edit.get('after')
            if not all(isinstance(value, str) and value.startswith('=') for value in (before, after)):
                raise ValueError('formula before/after assertions required at ' + _label(key))
            left, right_cell = original[sn][address], mutated[sn][address]
            if not all(cell.data_type == 'f' and isinstance(cell.value, str) for cell in (left, right_cell)):
                raise ValueError('ordinary formula root required at ' + _label(key))
            if _formula_tokens(left.value) != _formula_tokens(before):
                raise ValueError('before formula assertion mismatch at ' + _label(key))
            if _formula_tokens(right_cell.value) != _formula_tokens(after):
                raise ValueError('after formula assertion mismatch at ' + _label(key))
            if _formula_tokens(before) == _formula_tokens(after):
                raise ValueError('unchanged formula assertion at ' + _label(key))
        receipt['root_count'] = len(roots)
        receipt['unchanged_non_root_definition_count'] = _unchanged_definitions(original, mutated, roots)
        closures = {}
        for name, book, values in [('original', original, original_values),
                                   ('mutated', mutated, mutated_values)]:
            coverage, closure = _graph(book, values, roots, max_cells=max_dependency_cells,
                max_edges=max_dependency_edges, per_formula_cells=per_formula_reference_cells)
            receipt['graphs'][name] = coverage
            closures[name] = closure
        failed = [name for name, graph in receipt['graphs'].items() if graph['state'] != 'proven']
        if failed:
            raise ValueError('root separation not proven in ' + ', '.join(failed))
        for sn, address in (closures['original'] | closures['mutated']) - roots:
            left = _finite_cache(original_values[sn][address], formula=original[sn][address].data_type == 'f')
            right = _finite_cache(mutated_values[sn][address], formula=mutated[sn][address].data_type == 'f')
            if left != right:
                raise ValueError('non-root ancestor cache differs despite unchanged definitions: ' + sn + '!' + address)
        receipt['unchanged_ancestor_cache_values_verified'] = True
        impacts = []
        for sn, address in sorted(roots):
            label, key = sn + '!' + address, (sn, address)
            expected, actual = original_values[sn][address], mutated_values[sn][address]
            exact_goal, exact_combined = _finite_cache(expected, formula=True), _finite_cache(actual, formula=True)
            hints = {key: (expected.value, expected.data_type)}
            left = _normalized_values(hints, original_values.epoch, hints)[key]
            right = _normalized_values({key: (actual.value, actual.data_type)}, mutated_values.epoch, hints)[key]
            if left == right:
                raise ValueError('root has no normalized observed value change: ' + label)
            evidence = {'root': label, 'goal_value': list(left), 'combined_value': list(right),
                'exact_goal_value': exact_goal, 'exact_combined_value': exact_combined,
                'root_value_differs_after_grader_normalization': True,
                'formula_assertions_passed': True,
                'original_and_mutated_ancestor_closures_exclude_all_edited_roots': True}
            marginal = {'expected_change_count': 1, 'expected_changes': [label],
                'counts_are_lower_bounds': True, 'actual_LO_execution': False,
                'proof_method': 'separated_dependency_graph_and_actual_combined_value_change'}
            impacts.append({'expected_change_count': 1, 'expected_changes': [label],
                'counts_are_lower_bounds': True, 'actual_LO_execution': False,
                'proof_method': marginal['proof_method'], 'evidence': evidence,
                'combined_marginal': marginal})
        # Detect concurrent artifact changes; certificates bind the actual bytes.
        for name, path in paths.items():
            if _digest(path) != receipt[name + '_sha256']:
                raise ValueError('workbook changed during proof: ' + name)
        if _json_digest(edits) != receipt['edits_sha256']:
            raise ValueError('edit assertions changed during proof')
        receipt.update(passed=True, blocking=False, state='proven', root_impacts=impacts,
            guarantee='Each edited root itself changes under its mutation alone and when restored from the combined mutation, because both ancestor closures exclude all roots and every other definition is unchanged.')
    except Exception as exc:
        receipt.update(passed=False, blocking=True, state='rejected', reason=str(exc),
                       error_type=type(exc).__name__, root_impacts=[])
    finally:
        for book in books:
            book.close()
    return receipt
