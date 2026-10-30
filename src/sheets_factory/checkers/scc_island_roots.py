"""Private SCC counterfactual own-value witnesses in two unchanged contexts.

Edges point from a formula to its inputs. The complete union ancestor closure
of all roots contains each root's ENTIRE SCC, exactly as in the full workbook
union graph: every vertex on a path from a root is in that closure. If an input
outside C could read the root, root -> input -> root would put it in C. Thus
the SCC's external boundary cannot read the root and can use the stationary
original business context. Each independent island copies the complete C at
the same coordinates, changes only its designated root, and redirects every
internal reference to that island. Other edited roots retain the base context.

This proves local fixed-point own-value lower bounds, not 2N complete workbook
executions. Two stable passes do NOT prove a unique fixed point, independence
of initialization, or convergence/error-freedom of counterfactual downstream
SCCs. Source financial uniqueness is never transferred to a mutation. Full
goal/input stability, financial correctness and complete-D checks are separate.

The first adapter rejects mixed internal/external ranges, whole-range rewrites,
dynamic references, unresolved names, array formulas/literals, implicit
intersection, and positional/unknown functions in the dependency closure and
islands. Unrelated immutable business definitions are retained. No frontier is
truncated.
"""
from __future__ import annotations

from copy import copy, deepcopy
import hashlib
import json
from pathlib import Path
import re
import time

import openpyxl
from openpyxl.formula import Tokenizer
from openpyxl.utils.cell import quote_sheetname, range_boundaries

from .native_error_probe import exact_typed_value
from .separated_roots import _cell_definition, _formula_tokens, _names
from .shadow_roots import _cache, _groups, _pure, _visibility, qualify_scalar_shadow
from .native_error_dependencies import validate_static_reference_syntax
from ..workbook.compare import normalize_value
from ..workbook.profile import formula_references


_CELL = re.compile(r'[A-Z]{1,3}[1-9][0-9]*$')
_PREFIX = '__SCI_'


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def _label(key):
    return key[0] + '!' + key[1]


def _settings(book):
    return {name: getattr(book.calculation, name, None) for name in (
        'iterate', 'iterateCount', 'iterateDelta', 'fullPrecision', 'refMode')}


def _same_business(left, right, roots=()):
    """Allow ordinary LO quoting, never an altered intersection or calculation."""
    if (left.sheetnames != right.sheetnames or left.epoch != right.epoch
            or _names(left) != _names(right) or _visibility(left) != _visibility(right)
            or _settings(left) != _settings(right)):
        raise ValueError('Business structure, names or calculation settings differ')
    if _settings(left)['fullPrecision'] is False:
        raise ValueError('Precision-as-displayed is unsupported')
    count = 0
    for sheet in left:
        other = right[sheet.title]
        for coordinate in set(sheet._cells) | set(other._cells):
            a, b = sheet._cells.get(coordinate), other._cells.get(coordinate)
            if (a is None or a.value is None) and (b is None or b.value is None):
                continue
            key = sheet.title, (a or b).coordinate
            if key in roots:
                continue
            if a is None or b is None or _cell_definition(a) != _cell_definition(b):
                raise ValueError('Non-root definition differs at ' + _label(key))
            if a.data_type == 'f' and isinstance(a.value, str) and a.value != b.value:
                if any(validate_static_reference_syntax(x) for x in (a.value, b.value)):
                    raise ValueError('Unproven formula equivalence at ' + _label(key))
            count += 1
    return count


def strongly_connected_components(graph):
    """Iterative Kosaraju, including self-loops, without Python recursion limits."""
    if any(parent not in graph for parents in graph.values() for parent in parents):
        raise ValueError('Incomplete union graph: dependency frontier omitted')
    seen, order = set(), []
    for start in sorted(graph):
        if start in seen:
            continue
        seen.add(start)
        stack = [(start, iter(sorted(graph[start])))]
        while stack:
            vertex, iterator = stack[-1]
            child = next(iterator, None)
            if child is None:
                stack.pop()
                order.append(vertex)
            elif child not in seen:
                seen.add(child)
                stack.append((child, iter(sorted(graph[child]))))
    reverse = {key: set() for key in graph}
    for key, parents in graph.items():
        for parent in parents:
            reverse[parent].add(key)
    seen, result = set(), []
    for start in reversed(order):
        if start in seen:
            continue
        component, pending = set(), [start]
        seen.add(start)
        while pending:
            vertex = pending.pop()
            component.add(vertex)
            for child in reverse[vertex] - seen:
                seen.add(child)
                pending.append(child)
        result.append(frozenset(component))
    return result


def _union_plan(original, combined, values, edits, *, max_cells, max_edges, per_formula):
    roots = {(e['sheet'], e['cell']) for e in edits}
    graph, expanded, bounds, functions = {}, {}, {}, set()
    groups = [_groups(book) for book in (original, combined)]
    pending, cache, edge_count = list(roots), {}, 0
    while pending:
        key = pending.pop()
        if key in graph:
            continue
        if len(graph) >= max_cells:
            raise ValueError('Complete union dependency cell bound exceeded')
        sheet, address = key
        if sheet not in original or sheet not in combined:
            raise ValueError('Missing dependency sheet at ' + _label(key))
        graph[key] = set()
        for context, book in enumerate((original, combined)):
            cell = book[sheet][address]
            if any(a <= cell.column <= c and b <= cell.row <= d
                   for a, b, c, d in groups[context][sheet]):
                raise ValueError('Array formula group at ' + _label(key))
            _cache(values[context][sheet][address], formula=cell.data_type == 'f')
            if cell.data_type != 'f':
                continue
            if not isinstance(cell.value, str):
                raise ValueError('Array or nonordinary formula at ' + _label(key))
            refs = formula_references(cell.value, sheet, workbook=book, cache=cache,
                max_expansion=per_formula, include_resolved_formula=True)
            if not refs['fully_supported']:
                raise ValueError('Unresolved union dependency at ' + _label(key) + ': ' + str(refs['unsupported']))
            text = refs['resolved_formula']
            _pure(text, _label(key))
            # Validate every ancestor, including formulas that stay in the
            # business context. No unreviewed implicit intersection is admitted.
            qualify_scalar_shadow(text, sheet)
            if any(t.type == 'ARRAY' for t in Tokenizer(text).items):
                raise ValueError('Array literal in dependency closure at ' + _label(key))
            expanded[context, key] = text
            bounds[context, key] = refs.get('bounded_ranges', [])
            functions.update(t.value[:-1].upper() for t in Tokenizer(text).items
                             if t.type == 'FUNC' and t.subtype == 'OPEN')
            graph[key].update((r['sheet'], r['cell']) for r in refs['references'])
        edge_count += len(graph[key])
        if edge_count > max_edges:
            raise ValueError('Complete union dependency edge bound exceeded')
        pending.extend(graph[key] - graph.keys())
    components = strongly_connected_components(graph)
    membership = {key: component for component in components for key in component}
    return graph, expanded, bounds, membership, {
        'state': 'complete', 'scope': 'complete_union_transitive_ancestor_closure_of_all_roots',
        'closure_cells': len(graph), 'dependency_edges': edge_count,
        'complete_root_SCCs_equal_full_workbook_union_SCCs': True,
        'all_before_after_formulas_and_reference_branches_included': True,
        'frontier_omitted': False, 'SCC_count': len(components),
        'cyclic_SCC_count': sum(len(c) > 1 or next(iter(c)) in graph[next(iter(c))] for c in components),
        'functions': sorted(functions), 'graph_sha256': _digest([
            [_label(k), sorted(map(_label, v))] for k, v in sorted(graph.items())])}


def _remap(text, component, sheets, workbook, per_formula):
    """Keep range geometry; an unrepresentable mixed range is never split."""
    result = []
    for token in Tokenizer(text).items:
        value = token.value
        if token.type == 'OPERAND' and token.subtype == 'RANGE':
            refs = formula_references('=' + value, next(iter(component))[0],
                workbook=workbook, max_expansion=per_formula)
            if not refs['fully_supported'] or not refs['references']:
                raise ValueError('Unresolved island reference')
            keys = {(r['sheet'], r['cell']) for r in refs['references']}
            internal = keys & component
            if internal and internal != keys:
                raise ValueError('Mixed SCC/internal-external range requires an explicit boundary mirror')
            if internal:
                sheet, address = value.rsplit('!', 1)
                sheet = sheet[1:-1].replace("''", "'") if sheet.startswith("'") else sheet
                value = quote_sheetname(sheets[sheet]) + '!' + address
        result.append(value)
    return '=' + ''.join(result)


def _all_values(formulas, values, names):
    """Sparse full used area: explicit formula blanks and every nonempty value."""
    result = {}
    for name in names:
        keys = {k for k, c in formulas[name]._cells.items() if c.value is not None}
        keys.update(k for k, c in values[name]._cells.items() if c.value is not None)
        for row, col in keys:
            cell = values[name].cell(row, col)
            result[name, cell.coordinate] = exact_typed_value(cell)
    return result


def _numeric(cell):
    value = _cache(cell, formula=False)
    if cell.is_date or value[0] != 'number':
        raise ValueError('Residual snapshots require finite non-date numeric SCC/boundary caches at '
                         + cell.parent.title + '!' + cell.coordinate)
    return value


def _frozen_residual(context, base, source, directory, calculate, *, per_formula, max_cells):
    """Evaluate F(x) once using only frozen numeric SCC and boundary values."""
    formulas = openpyxl.load_workbook(source, keep_links=False)
    values = openpyxl.load_workbook(source, data_only=True, keep_links=False)
    expected = context['expected_formulas']; snapshots = {}; replacements = {}
    frozen = {}; output = directory / (context['kind'] + '_fixed_point_residual_actual.xlsx')
    raw = directory / (context['kind'] + '_fixed_point_residual_raw.xlsx')
    try:
        for key, text in expected.items():
            _numeric(values[key[0]][key[1]])
            pieces = []
            for token in Tokenizer(text).items:
                value = token.value
                if token.type == 'OPERAND' and token.subtype == 'RANGE':
                    refs = formula_references('=' + value, key[0], workbook=formulas,
                                              max_expansion=per_formula)
                    if not refs['fully_supported'] or not refs['references']:
                        raise ValueError('Unresolved residual reference')
                    name, address = value.rsplit('!', 1)
                    name = name[1:-1].replace("''", "'") if name.startswith("'") else name
                    if name not in snapshots:
                        snapshots[name] = f'{_PREFIX}R_{len(snapshots):04x}'
                    for ref in refs['references']:
                        boundary = ref['sheet'], ref['cell']
                        cell = values[boundary[0]][boundary[1]]
                        frozen[boundary] = _numeric(cell)
                        if len(frozen) > max_cells:
                            raise ValueError('Complete residual snapshot cell bound exceeded')
                    value = quote_sheetname(snapshots[name]) + '!' + address
                pieces.append(value)
            replacements[key] = '=' + ''.join(pieces)
        for target in snapshots.values():
            formulas.create_sheet(target)
        for (name, address), expected_value in frozen.items():
            cell = formulas[snapshots[name]][address]
            cell.value = values[name][address].value
            cell._style = copy(values[name][address]._style)
        for (name, address), text in replacements.items():
            formulas[name][address] = text
        formulas.save(raw)
        target_values = {key: _numeric(values[key[0]][key[1]]) for key in expected}
    finally:
        formulas.close(); values.close()
    # Serialization must itself preserve the exact frozen typed numbers.
    frozen_book = openpyxl.load_workbook(raw, data_only=True, keep_links=False)
    try:
        for (name, address), value in frozen.items():
            if _numeric(frozen_book[snapshots[name]][address]) != value:
                raise ValueError('Frozen residual cache changed during numeric serialization')
    finally:
        frozen_book.close()
    calculate(raw, output, context['kind'], 'fixed_point_residual')
    actual = openpyxl.load_workbook(output, keep_links=False)
    cached = openpyxl.load_workbook(output, data_only=True, keep_links=False)
    try:
        if actual.sheetnames != base.sheetnames + context['private_sheets'] + list(snapshots.values()):
            raise ValueError('Residual worksheet inventory differs')
        expected_keys = set(replacements) | {(snapshots[name], address) for name, address in frozen}
        actual_keys = {(name, cell.coordinate) for name in context['private_sheets'] + list(snapshots.values())
                       for cell in actual[name]._cells.values() if cell.value is not None}
        if actual_keys != expected_keys:
            raise ValueError('Residual private cell inventory differs')
        for (name, address), value in frozen.items():
            cell = actual[snapshots[name]][address]
            if cell.data_type == 'f' or _numeric(cached[snapshots[name]][address]) != value:
                raise ValueError('Frozen numeric residual boundary changed')
        observed = {}
        for key, text in replacements.items():
            cell = actual[key[0]][key[1]]
            if cell.data_type != 'f' or _formula_tokens(cell.value) != _formula_tokens(text):
                raise ValueError('Residual formula binding differs')
            observed[key] = _numeric(cached[key[0]][key[1]])
        if observed != target_values:
            raise ValueError('Actual frozen fixed-point residual F(x) differs from x')
        business = _all_values(actual, cached, base.sheetnames)
        if business != context['business_values']:
            raise ValueError('Residual changed exact typed business values')
        for name in context['private_sheets'] + list(snapshots.values()):
            actual.remove(actual[name])
        _same_business(base, actual)
        return {'passed': True, 'all_SCC_members_exact_Fx_equal_x': True,
            'all_referenced_boundaries_frozen': True, 'snapshot_value_domain': 'finite_non_date_numeric_only',
            'frozen_cell_count': len(frozen), 'SCC_member_count': len(observed),
            'frozen_values_sha256': _digest([[_label(k), v] for k, v in sorted(frozen.items())]),
            'SCC_values_sha256': _digest([[_label(k), v] for k, v in sorted(observed.items())]),
            'raw_path': str(raw), 'raw_sha256': _sha(raw), 'actual_path': str(output), 'actual_sha256': _sha(output),
            'all_business_exact_typed_values_unchanged': True}
    finally:
        actual.close(); cached.close()


def _prepare(goal, combined_input, edits, directory, *, max_dependency_cells,
             max_dependency_edges, per_formula_reference_cells, max_island_cells, max_island_sheets):
    for number, maximum, label in ((max_dependency_cells, 500000, 'dependency cells'),
            (max_dependency_edges, 10000000, 'dependency edges'),
            (per_formula_reference_cells, 50000, 'per-formula cells'),
            (max_island_cells, 5000000, 'island cells'), (max_island_sheets, 10000, 'island sheets')):
        if type(number) is not int or not 1 <= number <= maximum:
            raise ValueError('Invalid bound: ' + label)
    paths = {'goal': Path(goal), 'combined_input': Path(combined_input)}
    for name, path in paths.items():
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or symlink context: ' + name)
        paths[name] = path.resolve()
    if paths['goal'] == paths['combined_input']:
        raise ValueError('Distinct original and combined contexts are required')
    if not isinstance(edits, list) or not edits:
        raise ValueError('Nonempty formula edits are required')
    source_hashes = {name: _sha(path) for name, path in paths.items()}
    implementation_hash = _sha(__file__)
    books = []
    try:
        for path in paths.values():
            books.extend((openpyxl.load_workbook(path, keep_links=False),
                          openpyxl.load_workbook(path, data_only=True, keep_links=False)))
        original, original_values, combined, combined_values = books
        business_names = original.sheetnames[:]
        roots = set()
        for edit in edits:
            if not isinstance(edit, dict):
                raise ValueError('Invalid formula edit')
            key = edit.get('sheet'), edit.get('cell')
            if (not isinstance(key[0], str) or not isinstance(key[1], str)
                    or not _CELL.fullmatch(key[1]) or key in roots
                    or key[0] not in original or key[0] not in combined):
                raise ValueError('Duplicate, invalid or missing root')
            _, _, col, row = range_boundaries(key[1])
            if col > 16384 or row > 1048576:
                raise ValueError('Root exceeds Excel coordinates')
            roots.add(key)
            for book, values, field in ((original, original_values, 'before'),
                                         (combined, combined_values, 'after')):
                cell, value = book[key[0]][key[1]], values[key[0]][key[1]]
                if (cell.data_type != 'f' or not isinstance(cell.value, str)
                        or not isinstance(edit.get(field), str)
                        or _formula_tokens(cell.value) != _formula_tokens(edit[field])):
                    raise ValueError('Root formula assertion differs: ' + field)
                if value.is_date or _cache(value, formula=True)[0] != 'number':
                    raise ValueError('Finite non-date numeric root required')
            if _formula_tokens(edit['before']) == _formula_tokens(edit['after']):
                raise ValueError('Unchanged root formula')
        unchanged = _same_business(original, combined, roots)
        if any(name.casefold().startswith(_PREFIX.casefold()) for name in original.sheetnames):
            raise ValueError('Reserved private island sheet prefix already exists')
        graph, expanded, bounds, membership, graph_receipt = _union_plan(original, combined,
            (original_values, combined_values), edits, max_cells=max_dependency_cells,
            max_edges=max_dependency_edges, per_formula=per_formula_reference_cells)
        if graph_receipt['cyclic_SCC_count'] and (
                _settings(original)['iterate'] is not True
                or type(_settings(original)['iterateCount']) is not int
                or _settings(original)['iterateCount'] < 1
                or not isinstance(_settings(original)['iterateDelta'], (int, float))
                or _settings(original)['iterateDelta'] <= 0):
            raise ValueError('Cyclic islands require explicit copied iteration settings')
        clone_count = sum(len(membership[key]) for key in roots)
        sheet_count = sum(len({s for s, _ in membership[key]}) for key in roots)
        if clone_count > max_island_cells or sheet_count > max_island_sheets:
            raise ValueError('Complete SCC island allocation bound exceeded')
        contexts, root_plans = [], []
        for index, edit in enumerate(edits):
            key = edit['sheet'], edit['cell']; component = membership[key]
            root_plans.append({'root_index': index, 'root': _label(key),
                'SCC_cells': sorted(map(_label, component)), 'SCC_size': len(component),
                'cyclic': len(component) > 1 or key in graph[key],
                'external_boundary': sorted(map(_label, set().union(*(graph[k] for k in component)) - component))})
        for context, (kind, book, values) in enumerate((
                ('individual', original, original_values), ('combined_marginal', combined, combined_values))):
            expected, locations, added = {}, [], []
            try:
                for index, edit in enumerate(edits):
                    root = edit['sheet'], edit['cell']; component = membership[root]
                    mapping = {name: f'{_PREFIX}{index:04x}_{original.sheetnames.index(name):03x}'
                               for name in sorted({s for s, _ in component})}
                    for target in mapping.values():
                        book.create_sheet(target); added.append(target)
                    for key in sorted(component):
                        # Only this root takes the opposite context formula.
                        selected = 1 - context if key == root else context
                        if bounds.get((selected, key)):
                            raise ValueError('Whole-row/column rewrite is analysis-only, not an island formula')
                        text = qualify_scalar_shadow(expanded[selected, key], key[0])
                        text = _remap(text, component, mapping, book, per_formula_reference_cells)
                        destination = book[mapping[key[0]]][key[1]]
                        destination.value = text
                        destination._style = copy(book[key[0]][key[1]]._style)
                        expected[mapping[key[0]], key[1]] = text
                    locations.append((mapping[root[0]], root[1]))
                raw = directory / (kind + '_scc_islands_raw.xlsx')
                book.save(raw)
                contexts.append({'kind': kind, 'base': 'goal' if context == 0 else 'combined_input',
                    'raw_path': raw, 'private_sheets': added[:], 'expected_formulas': expected,
                    'root_locations': locations, 'business_values': _all_values(book, values, business_names)})
            finally:
                for name in added:
                    book.remove(book[name])
        summary = {'version': 1, 'state': 'planned_unexecuted', 'passed': False, 'blocking': True,
            'proof_directory': str(directory),
            'proof_method': 'two_context_complete_union_SCC_island_own_value_witness',
            'root_count': len(roots), 'union_graph': graph_receipt, 'root_SCCs': root_plans,
            'unchanged_non_root_definition_count': unchanged, 'copied_calculation_settings': _settings(original),
            'private_island_formula_count_per_context': clone_count, 'private_sheet_count_per_context': sheet_count,
            'counts_are_lower_bounds': True, 'complete_per_root_changed_sets_claimed': False,
            'full_counterfactual_convergence_claimed': False, 'counterfactual_uniqueness_claimed': False,
            'source_uniqueness_transferred_to_mutants': False, 'business_correctness_certificate': False,
            'difficulty_claimed': False, 'individual_root_LO_executions': 0, 'individual_marginal_LO_executions': 0,
            'actual_LO_execution_count': 0, 'actual_LO_started_count': 0, 'model_calls': 0,
            'private_witness_exported': False, 'root_impacts': [], 'root_checks': [], 'engine_calls': [],
            'implementation_sha256': implementation_hash, 'edits_sha256': _digest(edits),
            'analysis_limits': {'max_dependency_cells': max_dependency_cells,
                'max_dependency_edges': max_dependency_edges,
                'per_formula_reference_cells': per_formula_reference_cells,
                'max_island_cells': max_island_cells, 'max_island_sheets': max_island_sheets},
            **{name + '_sha256': value for name, value in source_hashes.items()},
            **{name + '_path': str(path) for name, path in paths.items()}}
        if any(_sha(paths[name]) != value for name, value in source_hashes.items()):
            raise ValueError('Source context changed while preparing islands')
        if _sha(__file__) != implementation_hash:
            raise ValueError('Checker implementation changed while preparing islands')
        return books, contexts, summary
    except Exception:
        for book in books:
            book.close()
        raise


def plan_scc_island_contexts(*, goal, combined_input, edits, directory,
        max_dependency_cells=500000, per_formula_reference_cells=50000,
        max_dependency_edges=10000000, max_island_cells=1000000, max_island_sheets=1024):
    """Write a fresh, unexecuted plan and two raw contexts; never assert proof."""
    directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=False)
    books, contexts, summary = _prepare(goal, combined_input, deepcopy(edits), directory,
        max_dependency_cells=max_dependency_cells, max_dependency_edges=max_dependency_edges,
        per_formula_reference_cells=per_formula_reference_cells, max_island_cells=max_island_cells,
        max_island_sheets=max_island_sheets)
    try:
        summary['contexts'] = [{'kind': c['kind'], 'base': c['base'], 'raw_path': str(c['raw_path']),
            'raw_sha256': _sha(c['raw_path']), 'private_sheets': c['private_sheets'],
            'root_locations': c['root_locations']} for c in contexts]
        _write(directory / 'scc_island_plan.json', summary)
        return summary
    finally:
        for book in books:
            book.close()


def prove_scc_island_root_impacts(*, goal, combined_input, edits, engine, directory,
        max_dependency_cells=500000, per_formula_reference_cells=50000,
        max_dependency_edges=10000000, max_island_cells=1000000, max_island_sheets=1024):
    """Run two passes per context and fail closed on any incomplete local proof.

    Six engine executions validate two contexts: two stable cyclic passes and
    one frozen numerical F(x)=x residual evaluation per context. Caller still
    validates complete original/combined workbooks. No complete individual
    counterfactual replay or global uniqueness is implied.
    """
    directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=False)
    started = time.monotonic(); books = []; executing = False
    receipt = {'version': 1, 'passed': False, 'blocking': True, 'root_impacts': [],
        'state': 'checking', 'actual_LO_started_count': 0, 'actual_LO_execution_count': 0,
        'engine_calls': [], 'root_checks': [], 'model_calls': 0}
    try:
        books, contexts, receipt = _prepare(goal, combined_input, deepcopy(edits), directory,
            max_dependency_cells=max_dependency_cells, max_dependency_edges=max_dependency_edges,
            per_formula_reference_cells=per_formula_reference_cells, max_island_cells=max_island_cells,
            max_island_sheets=max_island_sheets)
        metadata = engine.metadata()
        if (metadata.get('backend') != 'libreoffice_uno_docker' or metadata.get('network') != 'none'
                or not re.fullmatch(r'sha256:[a-f0-9]{64}', metadata.get('image_id', ''))):
            raise ValueError('Hash-pinned network-isolated LibreOffice engine required')
        receipt.update(engine=metadata, contexts=[])

        def calculate(source, output, kind, pass_index):
            nonlocal executing
            call = {'kind': kind, 'pass': pass_index, 'input_path': str(source),
                'input_sha256': _sha(source), 'output_path': str(output), 'completed': False}
            receipt['engine_calls'].append(call); receipt['actual_LO_started_count'] += 1
            before = time.monotonic(); executing = True
            try:
                engine.recalculate(source, output)
                receipt['actual_LO_execution_count'] += 1
                call.update(completed=True, output_sha256=_sha(output))
            finally:
                call['duration_ms'] = round((time.monotonic() - before) * 1000)
            executing = False

        observed = {}
        for context_index, context in enumerate(contexts):
            base = books[context_index * 2]; source = context['raw_path']; prior = None
            for pass_index in (1, 2):
                output = directory / f'{context["kind"]}_scc_islands_pass{pass_index}.xlsx'
                calculate(source, output, context['kind'], pass_index)
                formulas = openpyxl.load_workbook(output, keep_links=False)
                values = openpyxl.load_workbook(output, data_only=True, keep_links=False)
                try:
                    if formulas.sheetnames != base.sheetnames + context['private_sheets']:
                        raise ValueError('Actual island workbook worksheet structure differs')
                    actual_private = {(name, c.coordinate): c for name in context['private_sheets']
                                      for c in formulas[name]._cells.values() if c.value is not None}
                    if actual_private.keys() != context['expected_formulas'].keys():
                        raise ValueError('Actual island formula inventory differs')
                    for key, cell in actual_private.items():
                        if (cell.data_type != 'f' or not isinstance(cell.value, str)
                                or _formula_tokens(cell.value) != _formula_tokens(context['expected_formulas'][key])):
                            raise ValueError('Actual SCC island formula differs at ' + _label(key))
                        _cache(values[key[0]][key[1]], formula=True)
                    all_values = _all_values(formulas, values, formulas.sheetnames)
                    business_values = _all_values(formulas, values, base.sheetnames)
                    if business_values != context['business_values']:
                        raise ValueError('Private island changed exact typed business values')
                    for name in context['private_sheets']:
                        formulas.remove(formulas[name])
                    _same_business(base, formulas)
                    roots = []
                    for name, address in context['root_locations']:
                        cell = values[name][address]
                        if cell.is_date or _cache(cell, formula=True)[0] != 'number':
                            raise ValueError('Finite non-date numeric island root required')
                        roots.append({'exact': exact_typed_value(cell),
                            'normalized': list(normalize_value(cell.value, cell.data_type))})
                    if prior is not None and prior != all_values:
                        raise ValueError('Two-pass exact full-used-area stability failed')
                    prior = all_values
                    observed[context['kind']] = roots
                finally:
                    formulas.close(); values.close()
                source = output
            residual = _frozen_residual(context, base, source, directory, calculate,
                per_formula=per_formula_reference_cells, max_cells=max_island_cells)
            receipt['contexts'].append({'kind': context['kind'], 'base': context['base'],
                'raw_path': str(context['raw_path']), 'raw_sha256': _sha(context['raw_path']),
                'all_business_definitions_unchanged': True, 'all_business_exact_typed_values_unchanged': True,
                'full_used_area_exact_two_pass_stable': True, 'value_count': len(prior),
                'values_sha256': _digest([[_label(k), v] for k, v in sorted(prior.items())]),
                'private_sheets': context['private_sheets'], 'fixed_point_residual': residual,
                'root_locations': context['root_locations']})
        impacts = []
        for index, edit in enumerate(edits):
            key = edit['sheet'], edit['cell']
            old, new = books[1][key[0]][key[1]], books[3][key[0]][key[1]]
            left, right = (list(normalize_value(c.value, c.data_type)) for c in (old, new))
            individual, marginal = observed['individual'][index], observed['combined_marginal'][index]
            check = {'root_index': index, 'root': _label(key), 'goal_normalized_value': left,
                'combined_normalized_value': right, 'after_in_original_SCC': individual,
                'before_in_combined_SCC': marginal, 'individual_active': left != individual['normalized'],
                'combined_marginal_active': right != marginal['normalized']}
            receipt['root_checks'].append(check)
            lower = {'root_index': index, 'expected_change_count': 1, 'expected_changes': [_label(key)],
                'counts_are_lower_bounds': True, 'actual_individual_LO_execution': False,
                'actual_context_island_LO_execution': True, 'proof_method': receipt['proof_method']}
            impacts.append({**lower, 'evidence': check, 'combined_marginal': {
                **lower, 'edits_reversed': True, 'base': 'full_combined_mutation'}})
        if any(not c['individual_active'] or not c['combined_marginal_active'] for c in receipt['root_checks']):
            raise ValueError('At least one root lacks normalized own-value activity in both contexts')
        for name in ('goal', 'combined_input'):
            if _sha(receipt[name + '_path']) != receipt[name + '_sha256']:
                raise ValueError('Source context changed during proof')
        if _digest(edits) != receipt['edits_sha256']:
            raise ValueError('Caller edit assertions changed during proof')
        if _sha(__file__) != receipt['implementation_sha256']:
            raise ValueError('Checker implementation changed during proof')
        receipt.update(passed=True, blocking=False, state='proven_local_own_value_lower_bounds', root_impacts=impacts)
    except Exception as exc:
        receipt.update(passed=False, blocking=True, state='execution_error' if executing else 'rejected',
            reason=str(exc), error_type=type(exc).__name__, root_impacts=[])
    finally:
        for book in books:
            book.close()
    receipt['duration_ms'] = round((time.monotonic() - started) * 1000)
    _write(directory / 'scc_island_roots_certificate.json', receipt)
    return receipt


def validate_scc_island_root_certificate(certificate, goal, combined_input, edits):
    """Bind a persisted six-call receipt before a future Construct integration."""
    def require(condition, message):
        if not condition:
            raise ValueError('SCC island certificate rejected: ' + message)
    c = certificate
    require(c.get('passed') is True and c.get('blocking') is False
            and c.get('state') == 'proven_local_own_value_lower_bounds', 'incomplete proof')
    require(c.get('proof_method') == 'two_context_complete_union_SCC_island_own_value_witness'
            and type(c.get('actual_LO_execution_count')) is int and c['actual_LO_execution_count'] == 6
            and type(c.get('actual_LO_started_count')) is int and c['actual_LO_started_count'] == 6,
            'six actual recalculations required')
    require(c.get('implementation_sha256') == _sha(__file__), 'checker implementation changed')
    require(c.get('goal_sha256') == _sha(goal) and c.get('combined_input_sha256') == _sha(combined_input)
            and c.get('edits_sha256') == _digest(edits), 'source or edit binding differs')
    require(c.get('root_count') == len(edits) and c.get('counts_are_lower_bounds') is True
            and c.get('complete_per_root_changed_sets_claimed') is False
            and c.get('full_counterfactual_convergence_claimed') is False
            and c.get('counterfactual_uniqueness_claimed') is False
            and c.get('source_uniqueness_transferred_to_mutants') is False,
            'lower-bound scope is incomplete or overstated')
    graph = c.get('union_graph', {})
    require(graph.get('state') == 'complete' and graph.get('frontier_omitted') is False
            and graph.get('complete_root_SCCs_equal_full_workbook_union_SCCs') is True
            and graph.get('all_before_after_formulas_and_reference_branches_included') is True,
            'complete union SCC analysis required')
    declared_root = c.get('proof_directory')
    require(isinstance(declared_root, str) and Path(declared_root).is_absolute()
            and Path(declared_root).is_dir() and not Path(declared_root).is_symlink(),
            'private proof directory required')
    root = Path(declared_root).resolve()

    def artifact(path, digest):
        p = Path(path)
        require(p.is_absolute() and p.is_relative_to(root) and p.is_file()
                and p.resolve().is_relative_to(root)
                and not any(q.is_symlink() for q in (p, *p.parents) if q.is_relative_to(root)),
                'unsafe or missing private artifact')
        require(_sha(p) == digest, 'actual artifact SHA differs')
    expected = [(kind, number) for kind in ('individual', 'combined_marginal')
                for number in (1, 2, 'fixed_point_residual')]
    calls = c.get('engine_calls', [])
    require(isinstance(calls, list) and len(calls) == 6
            and all(isinstance(x, dict) for x in calls)
            and [(x.get('kind'), x.get('pass')) for x in calls] == expected,
            'execution sequence differs')
    for call in calls:
        require(call.get('completed') is True, 'missing completed execution')
        artifact(call.get('input_path', ''), call.get('input_sha256'))
        artifact(call.get('output_path', ''), call.get('output_sha256'))
    contexts = c.get('contexts', [])
    require(len(contexts) == 2 and [x.get('kind') for x in contexts] == ['individual','combined_marginal'],
            'two independent contexts required')
    for context in contexts:
        residual = context.get('fixed_point_residual', {})
        require(all(context.get(k) is True for k in ('all_business_definitions_unchanged',
                'all_business_exact_typed_values_unchanged', 'full_used_area_exact_two_pass_stable'))
            and residual.get('passed') is True and residual.get('all_SCC_members_exact_Fx_equal_x') is True
            and residual.get('all_referenced_boundaries_frozen') is True
            and residual.get('snapshot_value_domain') == 'finite_non_date_numeric_only'
            and residual.get('SCC_member_count') == c.get('private_island_formula_count_per_context'),
            'stable exact contexts and full numeric F(x)=x residuals required')
        artifact(residual.get('raw_path', ''), residual.get('raw_sha256'))
        artifact(residual.get('actual_path', ''), residual.get('actual_sha256'))
    impacts, checks = c.get('root_impacts', []), c.get('root_checks', [])
    require(len(impacts) == len(checks) == len(edits), 'every root requires evidence')
    for index, (edit, impact, check) in enumerate(zip(edits, impacts, checks)):
        label = edit['sheet'] + '!' + edit['cell']
        require(impact.get('root_index') == check.get('root_index') == index
                and check.get('root') == label and impact.get('evidence') == check
                and check.get('individual_active') is True and check.get('combined_marginal_active') is True,
                'root evidence is missing or inactive')
        for proof in (impact, impact.get('combined_marginal', {})):
            require(proof.get('proof_method') == c['proof_method']
                    and proof.get('expected_change_count') == 1 and proof.get('expected_changes') == [label]
                    and proof.get('counts_are_lower_bounds') is True
                    and proof.get('actual_individual_LO_execution') is False
                    and proof.get('actual_context_island_LO_execution') is True,
                    'root lower-bound claim differs')
        require(impact['combined_marginal'].get('edits_reversed') is True
                and impact['combined_marginal'].get('base') == 'full_combined_mutation',
                'full-context marginal proof required')
    return impacts
