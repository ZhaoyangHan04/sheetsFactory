"""Private SCC counterfactual own-value witnesses in two unchanged contexts.

Edges point from a formula to its inputs. The complete union ancestor closure
of all roots contains each root's ENTIRE SCC, exactly as in the full workbook
union graph: every vertex on a path from a root is in that closure. If an input
outside C could read the root, root -> input -> root would put it in C. Thus
the SCC's external boundary cannot read the root and can use the stationary
original business context. Cyclic islands copy the complete C at the same
coordinates and redirect internal references to that island. A singleton with
no union self-loop uses one shared private scalar sheet: every reference is
qualified, and the scalar/position-independent guard applies to all ancestors.
Only the designated root changes; other edited roots retain the base context.

This proves local fixed-point own-value lower bounds, not 2N complete workbook
executions. Two stable passes do NOT prove a unique fixed point, independence
of initialization, or convergence/error-freedom of counterfactual downstream
SCCs. Source financial uniqueness is never transferred to a mutation. Full
goal/input stability, financial correctness and complete-D checks are separate.

Residual members remain finite non-date numbers. External snapshots preserve
nonempty text, Boolean values and raw numeric date serials with their original
epoch, formatting and cache types. Blank/formula-empty coercions are rejected.
An independent opt-in admits only ancestor INDEX/IF patterns whose integer
selectors and guards are proven from transitively unchanged literal definitions.
All original branch/array references remain in the graph; only private formula
copies are simplified. Dynamic references, arrays, implicit intersection,
mixed internal/external ranges, metadata introspection and unproven positional
or reference-return functions remain rejected. No frontier is truncated.
"""
from __future__ import annotations

from copy import copy, deepcopy
import hashlib
import json
import math
from decimal import Decimal
from pathlib import Path
import posixpath
import re
import time
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import openpyxl
from openpyxl.formula import Tokenizer
from openpyxl.utils.cell import quote_sheetname, range_boundaries, get_column_letter

from .native_error_probe import exact_typed_value
from .separated_roots import _cell_definition, _formula_tokens, _names
from .shadow_roots import _cache, _groups, _pure, _visibility, qualify_scalar_shadow
from .native_error_dependencies import validate_static_reference_syntax
from ..workbook.compare import normalize_value
from ..workbook.profile import formula_references


_CELL = re.compile(r'[A-Z]{1,3}[1-9][0-9]*$')
_PREFIX = '__SCI_'
_DAG = _PREFIX + 'DAG'
_METHOD = 'two_context_typed_boundary_compact_DAG_complete_cyclic_SCC_own_value_witness_v8'
_BOUNDARY_DOMAIN = 'finite_numeric_SCC_typed_nonempty_external_boundaries_v1'
_XML = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


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


def _index_ast(text):
    """A deliberately small grammar, not a general Excel evaluator."""
    tokens = [t for t in Tokenizer(text).items if t.type != 'WHITE-SPACE']
    position = 0
    priorities = {'=': 1, '<>': 1, '<': 1, '<=': 1, '>': 1, '>=': 1,
                  '+': 2, '-': 2, '*': 3, '/': 3}
    def expression(minimum=0):
        nonlocal position
        if position >= len(tokens):
            raise ValueError('Missing constant INDEX expression')
        token = tokens[position]; position += 1
        if token.type == 'OPERATOR-PREFIX' and token.value in ('+', '-'):
            left = ('unary', token.value, expression(4))
        elif token.type == 'PAREN' and token.subtype == 'OPEN':
            left = expression()
            if position >= len(tokens) or tokens[position].type != 'PAREN' or tokens[position].subtype != 'CLOSE':
                raise ValueError('Unbalanced constant INDEX expression')
            position += 1
        elif token.type == 'OPERAND' and token.subtype in ('NUMBER', 'LOGICAL', 'TEXT', 'RANGE'):
            left = (token.subtype.lower(), token.value)
        elif token.type == 'FUNC' and token.subtype == 'OPEN' and token.value[:-1].upper() in ('IF', 'INDEX'):
            name, arguments = token.value[:-1].upper(), []
            while True:
                arguments.append(expression())
                if position >= len(tokens):
                    raise ValueError('Unclosed restricted INDEX function')
                current = tokens[position]; position += 1
                if current.type == 'FUNC' and current.subtype == 'CLOSE':
                    break
                if current.type != 'SEP' or current.subtype != 'ARG':
                    raise ValueError('Unsupported restricted INDEX argument')
            left = ('call', name, tuple(arguments))
        else:
            raise ValueError('Unsupported constant INDEX token: ' + token.value)
        while position < len(tokens):
            token = tokens[position]
            priority = priorities.get(token.value) if token.type == 'OPERATOR-INFIX' else None
            if priority is None or priority < minimum:
                break
            position += 1
            left = ('binary', token.value, left, expression(priority + 1))
        return left
    result = expression()
    if position != len(tokens):
        raise ValueError('Unconsumed restricted INDEX expression')
    return result


def _constant_index_ancestor(text, key, original, combined, values, roots, context, per_formula):
    """Prove integer selectors/guards from unchanged literal definitions only.

    The full original dependency graph is retained by the caller. Only private
    witness formula copies use this partial evaluation. No cached selector is
    used to choose a branch or an array element.
    """
    if key in roots:
        raise ValueError('INDEX is permitted only at immutable ancestors, never edited roots')
    if _cell_definition(original[key[0]][key[1]]) != _cell_definition(combined[key[0]][key[1]]):
        raise ValueError('INDEX ancestor definition must be unchanged in both contexts')
    tree = _index_ast(text); definitions = {}; active_stack = set(); index_specs = {}; guards = []
    def finite_integer(value):
        if type(value) is not int or abs(value) > 2**53:
            raise ValueError('Constant INDEX arithmetic must remain exact binary64 integers')
        return value
    def reference(token, anchor):
        refs = formula_references('=' + token, anchor, workbook=original,
            max_expansion=per_formula, include_resolved_formula=True)
        if not refs['fully_supported'] or len(refs['references']) != 1 or ':' in token:
            raise ValueError('Constant selector requires one explicit static cell')
        r = refs['references'][0]; return r['sheet'], r['cell']
    def same_cache(result, cell):
        expected = ['boolean', result] if type(result) is bool else ['number', str(Decimal(result).normalize())]
        if cell.is_date or exact_typed_value(cell) != expected:
            raise ValueError('Constant selector formula-cache contradiction at ' + cell.parent.title + '!' + cell.coordinate)
    def constant(node, anchor):
        kind = node[0]
        if kind == 'number':
            number = Decimal(node[1])
            if not number.is_finite() or number != number.to_integral_value():
                raise ValueError('Noninteger constant INDEX selector/guard arithmetic')
            return finite_integer(int(number))
        if kind == 'logical':
            return node[1].upper() == 'TRUE'
        if kind == 'range':
            dependency = reference(node[1], anchor)
            if dependency in roots or dependency in active_stack:
                raise ValueError('Constant INDEX selector reaches an edited root or a cycle')
            before, after = original[dependency[0]][dependency[1]], combined[dependency[0]][dependency[1]]
            if _cell_definition(before) != _cell_definition(after):
                raise ValueError('Constant INDEX selector definition changes between contexts')
            active_stack.add(dependency)
            try:
                if before.data_type == 'f':
                    if not isinstance(before.value, str):
                        raise ValueError('Nonordinary constant selector definition')
                    result = constant(_index_ast(before.value), dependency[0])
                elif type(before.value) is bool:
                    result = before.value
                elif type(before.value) in (int, float) and not before.is_date:
                    result = constant(('number', str(before.value)), dependency[0])
                else:
                    raise ValueError('Selector is not transitively defined by immutable literal integers')
                for cached in values:
                    same_cache(result, cached[dependency[0]][dependency[1]])
                definitions[_label(dependency)] = {'definition': _cell_definition(before),
                    'original_cache': exact_typed_value(values[0][dependency[0]][dependency[1]]),
                    'combined_cache': exact_typed_value(values[1][dependency[0]][dependency[1]]),
                    'computed_constant': result}
                return result
            finally:
                active_stack.remove(dependency)
        if kind == 'unary':
            operand = constant(node[2], anchor); finite_integer(operand)
            return finite_integer(operand if node[1] == '+' else -operand)
        if kind == 'binary':
            left, right = constant(node[2], anchor), constant(node[3], anchor); op = node[1]
            if op in ('=', '<>', '<', '<=', '>', '>='):
                if type(left) is not type(right):
                    raise ValueError('Mixed Boolean/numeric constant INDEX comparison')
                return {'=': lambda: left == right, '<>': lambda: left != right,
                    '<': lambda: left < right, '<=': lambda: left <= right,
                    '>': lambda: left > right, '>=': lambda: left >= right}[op]()
            finite_integer(left); finite_integer(right)
            if op == '/' and (right == 0 or left % right):
                raise ValueError('Inexact constant INDEX division')
            return finite_integer({'+': lambda: left+right, '-': lambda: left-right,
                '*': lambda: left*right, '/': lambda: left//right}[op]())
        raise ValueError('Dynamic or function-based INDEX selector/guard is unsupported')
    def collect(node):
        if node[0] == 'call':
            name, args = node[1], node[2]
            if name == 'IF':
                if len(args) != 3:
                    raise ValueError('Restricted IF requires three explicit arguments')
            else:
                if len(args) not in (2, 3) or args[0][0] != 'range':
                    raise ValueError('Restricted INDEX requires one explicit finite vertical array')
                token = args[0][1]
                refs = formula_references('=' + token, key[0], workbook=original, max_expansion=per_formula)
                if not refs['fully_supported'] or not refs['references'] or '!' not in token:
                    raise ValueError('Unresolved finite INDEX array')
                name_token, address = token.rsplit('!', 1)
                name_token = name_token[1:-1].replace("''", "'") if name_token.startswith("'") else name_token
                left, top, right, bottom = range_boundaries(address)
                if left != right:
                    raise ValueError('First restricted INDEX adapter accepts vertical arrays only')
                row = constant(args[1], key[0]); finite_integer(row)
                column = constant(args[2], key[0]) if len(args) == 3 else 1
                if type(column) is not int or column != 1:
                    raise ValueError('Restricted INDEX requires scalar column one')
                selected = (name_token, f'{get_column_letter(left)}{top+row-1}') if 1 <= row <= bottom-top+1 else None
                array = [(r['sheet'], r['cell']) for r in refs['references']]
                index_specs[node] = {'array': token, 'geometry': [left,top,right,bottom], 'row': row, 'column': column,
                    'selected_reference': None if selected is None else _label(selected),
                    'selected_typed_value': None if selected is None else exact_typed_value(values[context][selected[0]][selected[1]]),
                    'entire_original_array': [{'cell': _label(p),
                        'original_definition': _cell_definition(original[p[0]][p[1]]),
                        'combined_definition': _cell_definition(combined[p[0]][p[1]]),
                        'original_typed_cache': exact_typed_value(values[0][p[0]][p[1]]),
                        'combined_typed_cache': exact_typed_value(values[1][p[0]][p[1]])} for p in array],
                    'used': False}
            for argument in args:
                collect(argument)
        elif node[0] in ('binary', 'unary'):
            for child in node[2:]:
                collect(child)
    collect(tree)
    if not index_specs:
        raise ValueError('Restricted INDEX extension requires an actual INDEX call')
    def partial(node):
        kind = node[0]
        if kind == 'call' and node[1] == 'IF':
            condition = constant(node[2][0], key[0])
            if type(condition) not in (bool, int):
                raise ValueError('Nonconstant IF guard around INDEX')
            selected = 1 if bool(condition) else 2
            guards.append({'original_guard_expression': node[2][0], 'computed_guard': condition,
                           'selected_argument': selected, 'eliminated_expression': node[2][3-selected]})
            return partial(node[2][selected])
        if kind == 'call' and node[1] == 'INDEX':
            record = index_specs[node]
            if record['selected_reference'] is None:
                raise ValueError('Live INDEX selector is outside its finite array')
            record['used'] = True
            sheet, address = record['selected_reference'].rsplit('!',1)
            return '=' + quote_sheetname(sheet) + '!' + address
        if kind in ('number', 'logical', 'text'):
            return '=' + node[1]
        if kind == 'range':
            dependency = reference(node[1], key[0])
            return '=' + quote_sheetname(dependency[0]) + '!' + dependency[1]
        raise ValueError('Only constant IF/INDEX scalar ancestor patterns are admitted')
    rewritten = partial(tree)
    # The selected scalar's current cache is checked as evidence, never used to
    # establish a selector/guard. This catches contradictory source caches.
    result_node = _index_ast(rewritten)
    if result_node[0] == 'range':
        selected = reference(result_node[1], key[0])
        expected = exact_typed_value(values[context][selected[0]][selected[1]])
    elif result_node[0] == 'text':
        expected = ['string', result_node[1][1:-1].replace('""','"')]
    else:
        scalar = constant(result_node, key[0])
        expected = ['boolean',scalar] if type(scalar) is bool else ['number',str(Decimal(scalar).normalize())]
    if expected[0] == 'empty' or exact_typed_value(values[context][key[0]][key[1]]) != expected:
        raise ValueError('Restricted INDEX ancestor formula-cache contradiction')
    proof = {'anchor': _label(key), 'context': context, 'original_formula': text,
        'anchor_definition': _cell_definition((original,combined)[context][key[0]][key[1]]),
        'anchor_typed_cache': exact_typed_value(values[context][key[0]][key[1]]),
        'rewritten_private_formula': rewritten, 'constant_definitions': definitions,
        'guards': guards, 'index_calls': list(index_specs.values()),
        'all_original_array_selector_guard_references_retained': True,
        'selector_decided_from_cache': False, 'business_formula_rewritten': False}
    return rewritten, proof


def _union_plan(original, combined, values, edits, *, max_cells, max_edges, per_formula,
                allow_constant_index_ancestors=False):
    roots = {(e['sheet'], e['cell']) for e in edits}
    graph, expanded, bounds, functions = {}, {}, {}, set()
    groups = [_groups(book) for book in (original, combined)]
    pending, cache, edge_count = list(roots), {}, 0
    index_proofs = []
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
            if allow_constant_index_ancestors and any(t.type == 'FUNC' and t.subtype == 'OPEN'
                    and t.value[:-1].upper() == 'INDEX' for t in Tokenizer(text).items):
                private_text, proof = _constant_index_ancestor(text, key, original, combined,
                    values, roots, context, per_formula)
                index_proofs.append(proof)
            else:
                private_text = text
            qualify_scalar_shadow(private_text, sheet)
            if any(t.type == 'ARRAY' for t in Tokenizer(text).items):
                raise ValueError('Array literal in dependency closure at ' + _label(key))
            expanded[context, key] = private_text
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
        'all_ancestor_formulas_scalar_static_position_independent': True,
        'frontier_omitted': False, 'SCC_count': len(components),
        'cyclic_SCC_count': sum(len(c) > 1 or next(iter(c)) in graph[next(iter(c))] for c in components),
        'constant_INDEX_extension': {'version': 1, 'enabled': allow_constant_index_ancestors,
            'scope': 'ancestor_only_transitively_immutable_exact_integer_selectors_and_IF_guards',
            'proofs': sorted(index_proofs, key=lambda p: (p['anchor'],p['context'])),
            'proofs_sha256': _digest(sorted(index_proofs, key=lambda p: (p['anchor'],p['context']))),
            'proof_count': len(index_proofs),
            'all_original_references_retained': True, 'business_definitions_rewritten': False},
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


def _raw_cells(path):
    """Bind original OOXML scalar caches; datetime decoding loses serial bits."""
    result = {}
    with ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        relations = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        targets = {item.attrib['Id']: item.attrib['Target'] for item in relations}
        for sheet in workbook.find(_XML + 'sheets'):
            rid = sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
            path = posixpath.normpath(posixpath.join('xl', targets[rid])).lstrip('/')
            for cell in ET.fromstring(archive.read(path)).iter(_XML + 'c'):
                value, formula = cell.find(_XML + 'v'), cell.find(_XML + 'f')
                result[sheet.attrib['name'], cell.attrib['r']] = {
                    'attributes': dict(cell.attrib), 'v_present': value is not None,
                    'v_text': None if value is None else value.text,
                    'formula': None if formula is None else formula.text,
                    'formula_attributes': None if formula is None else dict(formula.attrib)}
    return result


def _style_signature(cell):
    # Style IDs may be renumbered by an office engine. Bind the source ID array
    # as provenance and compare the actual resolved formatting semantics.
    return _digest({'number_format': cell.number_format,
        **{name: ET.tostring(copy(getattr(cell, name)).to_tree(), encoding='unicode')
           for name in ('font', 'fill', 'border', 'alignment', 'protection')},
        'quotePrefix': bool(cell.quotePrefix), 'pivotButton': bool(cell.pivotButton)})


def _typed_boundary(definition, cached, raw, epoch):
    value = _cache(cached, formula=definition.data_type == 'f')
    if value[0] in ('empty', 'error') or (value[0] == 'string' and not value[1]):
        raise ValueError('Blank, empty-string or missing formula boundary is unsupported at '
                         + cached.parent.title + '!' + cached.coordinate)
    if raw is None:
        raise ValueError('Original typed boundary OOXML cache is missing')
    result = {'typed_value': value, 'epoch': epoch.isoformat(),
        'source_definition_sha256': _digest(_cell_definition(definition)),
        'source_cell_type': definition.data_type, 'source_cache_cell_type': cached.data_type,
        'source_raw_cache_type': raw['attributes'].get('t', 'n'),
        'source_OOXML_sha256': _digest(raw),
        'source_style_array': list(cached._style) if cached._style else None,
        'style_semantics_sha256': _style_signature(cached), 'number_format': cached.number_format}
    if cached.is_date:
        # First version accepts the numeric serial encoding. ISO date strings,
        # durations and unknown calendar encodings are not silently converted.
        if (value[0] not in ('datetime', 'date', 'time')
                or result['source_raw_cache_type'] != 'n' or not raw['v_present']):
            raise ValueError('Unsupported date cache encoding')
        try:
            serial = float(raw['v_text'])
        except (ValueError, TypeError):
            raise ValueError('Invalid original date serial') from None
        if not math.isfinite(serial):
            raise ValueError('Nonfinite original date serial')
        result.update(kind='date_serial', raw_date_serial=raw['v_text'],
                      date_serial_binary64=serial.hex(), literal_encoding='numeric_serial_with_original_date_style')
    elif value[0] == 'number':
        result.update(kind='number', literal_encoding='number')
    elif value[0] == 'boolean':
        result.update(kind='boolean', literal_encoding='boolean')
    elif value[0] == 'string':
        result.update(kind='text', literal_encoding='explicit_literal_text')
    else:
        raise ValueError('Unsupported frozen boundary scalar type: ' + value[0])
    return result


def _assign_boundary(target, source, descriptor):
    target.value = (float(descriptor['raw_date_serial']) if descriptor['kind'] == 'date_serial'
                    else source.value)
    if descriptor['kind'] == 'text':
        target.data_type = 's'  # A leading '=' remains text, never a formula.
    target._style = copy(source._style)


def _check_boundary(descriptor, definition, cached, raw, epoch):
    if (definition.data_type == 'f' or raw is None or raw['formula'] is not None
            or epoch.isoformat() != descriptor['epoch']
            or _style_signature(cached) != descriptor['style_semantics_sha256']
            or cached.number_format != descriptor['number_format']
            or exact_typed_value(cached) != descriptor['typed_value']):
        raise ValueError('Frozen typed boundary value/type/style/epoch changed')
    kind = descriptor['kind']; encoded = raw['attributes'].get('t', 'n')
    if kind == 'date_serial':
        try:
            serial = float(raw['v_text'])
        except (ValueError, TypeError):
            raise ValueError('Frozen raw date serial missing') from None
        if (encoded != 'n' or not cached.is_date or not math.isfinite(serial)
                or serial.hex() != descriptor['date_serial_binary64']):
            raise ValueError('Frozen exact original date serial changed')
    elif kind == 'number':
        if encoded != 'n' or cached.is_date or _numeric(cached) != descriptor['typed_value']:
            raise ValueError('Frozen numeric boundary type changed')
    elif kind == 'boolean':
        if encoded != 'b' or cached.data_type != 'b' or type(cached.value) is not bool:
            raise ValueError('Frozen Boolean boundary type changed')
    elif kind == 'text':
        if encoded not in ('s', 'inlineStr', 'str') or cached.data_type != 's' or not isinstance(cached.value, str):
            raise ValueError('Frozen text boundary type changed')
    else:
        raise ValueError('Unknown typed boundary descriptor')


def _preserve_raw_date_serials(path, records):
    """Avoid openpyxl's floating-point serialization rounding a date serial."""
    dates = {tuple(r['snapshot_cell']): r['descriptor']['raw_date_serial']
             for r in records if r['descriptor']['kind'] == 'date_serial'}
    if not dates:
        return
    with ZipFile(path) as source:
        entries = [(entry, source.read(entry.filename)) for entry in source.infolist()]
    book = openpyxl.load_workbook(path, read_only=True)
    try:
        names = book.sheetnames[:]
    finally:
        book.close()
    temporary = Path(path).with_suffix('.date_serials.tmp')
    with ZipFile(temporary, 'w') as target:
        for entry, payload in entries:
            match = re.fullmatch(r'xl/worksheets/sheet([1-9][0-9]*)\.xml', entry.filename)
            if match:
                name = names[int(match.group(1))-1]
                selected = {address: value for (sheet, address), value in dates.items() if sheet == name}
                if selected:
                    tree = ET.fromstring(payload)
                    found = set()
                    for cell in tree.iter(_XML + 'c'):
                        address = cell.attrib['r']
                        if address in selected:
                            value = cell.find(_XML + 'v')
                            if value is None or cell.find(_XML + 'f') is not None:
                                raise ValueError('Date snapshot is not an explicit scalar literal')
                            cell.attrib['t'] = 'n'; value.text = selected[address]; found.add(address)
                    if found != set(selected):
                        raise ValueError('Date snapshot coordinates are missing')
                    payload = ET.tostring(tree)
            target.writestr(entry, payload)
    temporary.replace(path)


def _frozen_residual(context, base, source, directory, calculate, *, per_formula, max_cells, max_sheets):
    """Evaluate numeric F(x) once using exactly typed frozen scalar boundaries."""
    formulas = openpyxl.load_workbook(source, keep_links=False)
    values = openpyxl.load_workbook(source, data_only=True, keep_links=False)
    source_raw = _raw_cells(source)
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
                        frozen[boundary] = _typed_boundary(formulas[boundary[0]][boundary[1]], cell,
                            source_raw.get(boundary), formulas.epoch)
                        if len(frozen) + len(expected) > max_cells:
                            raise ValueError('Complete residual snapshot cell bound exceeded')
                    value = quote_sheetname(snapshots[name]) + '!' + address
                pieces.append(value)
            replacements[key] = '=' + ''.join(pieces)
        if len(context['private_sheets']) + len(snapshots) > max_sheets:
            raise ValueError('Complete residual snapshot sheet bound exceeded')
        if (len(snapshots) != context['residual_snapshot_sheet_count']
                or len(frozen) != context['residual_snapshot_cell_count']):
            raise ValueError('Actual residual allocation differs from its complete static plan')
        for target in snapshots.values():
            formulas.create_sheet(target)
        for (name, address), expected_value in frozen.items():
            cell = formulas[snapshots[name]][address]
            _assign_boundary(cell, values[name][address], expected_value)
        for (name, address), text in replacements.items():
            formulas[name][address] = text
        formulas.save(raw)
        records = [{'source_cell': list(key), 'snapshot_cell': [snapshots[key[0]], key[1]],
                    'descriptor': value} for key, value in sorted(frozen.items())]
        _preserve_raw_date_serials(raw, records)
        target_values = {key: _numeric(values[key[0]][key[1]]) for key in expected}
    finally:
        formulas.close(); values.close()
    # Serialization must preserve exact scalar types, date serials and styles.
    frozen_book = openpyxl.load_workbook(raw, data_only=True, keep_links=False)
    frozen_definitions = openpyxl.load_workbook(raw, keep_links=False)
    frozen_raw = _raw_cells(raw)
    try:
        for (name, address), value in frozen.items():
            key = snapshots[name], address
            _check_boundary(value, frozen_definitions[key[0]][key[1]],
                frozen_book[key[0]][key[1]], frozen_raw.get(key), frozen_book.epoch)
    finally:
        frozen_book.close(); frozen_definitions.close()
    calculate(raw, output, context['kind'], 'fixed_point_residual')
    actual = openpyxl.load_workbook(output, keep_links=False)
    cached = openpyxl.load_workbook(output, data_only=True, keep_links=False)
    actual_raw = _raw_cells(output)
    try:
        if actual.sheetnames != base.sheetnames + context['private_sheets'] + list(snapshots.values()):
            raise ValueError('Residual worksheet inventory differs')
        expected_keys = set(replacements) | {(snapshots[name], address) for name, address in frozen}
        actual_keys = {(name, cell.coordinate) for name in context['private_sheets'] + list(snapshots.values())
                       for cell in actual[name]._cells.values() if cell.value is not None}
        if actual_keys != expected_keys:
            raise ValueError('Residual private cell inventory differs')
        for (name, address), value in frozen.items():
            key = snapshots[name], address
            _check_boundary(value, actual[key[0]][key[1]], cached[key[0]][key[1]],
                            actual_raw.get(key), actual.epoch)
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
            'all_referenced_boundaries_frozen': True, 'snapshot_value_domain': _BOUNDARY_DOMAIN,
            'typed_boundary_records': records, 'source_path': str(source), 'source_sha256': _sha(source),
            'all_boundary_serializations_exact': True, 'all_boundary_types_styles_epoch_exact_after_LO': True,
            'frozen_cell_count': len(frozen), 'SCC_member_count': len(observed),
            'actual_snapshot_sheet_count': len(snapshots),
            'actual_total_private_sheet_count': len(context['private_sheets']) + len(snapshots),
            'actual_total_private_cell_count': len(expected) + len(frozen),
            'frozen_values_sha256': _digest([[_label(k), v] for k, v in sorted(frozen.items())]),
            'SCC_values_sha256': _digest([[_label(k), v] for k, v in sorted(observed.items())]),
            'raw_path': str(raw), 'raw_sha256': _sha(raw), 'actual_path': str(output), 'actual_sha256': _sha(output),
            'all_business_exact_typed_values_unchanged': True}
    finally:
        actual.close(); cached.close()


def _validate_typed_residual(residual, context, source):
    """Reconstruct every descriptor from the actual second-pass workbook."""
    if (residual.get('source_path') != str(source)
            or residual.get('source_sha256') != _sha(source)
            or residual.get('all_boundary_serializations_exact') is not True
            or residual.get('all_boundary_types_styles_epoch_exact_after_LO') is not True):
        raise ValueError('Typed residual source or serialization binding differs')
    books = []
    try:
        paths = (source, residual['raw_path'], residual['actual_path'])
        for path in paths:
            books.extend((openpyxl.load_workbook(path, keep_links=False),
                          openpyxl.load_workbook(path, data_only=True, keep_links=False)))
        source_book, source_values, raw_book, raw_values, actual_book, actual_values = books
        raw_metadata = [_raw_cells(path) for path in paths]
        records = residual.get('typed_boundary_records')
        if not isinstance(records, list) or len(records) != residual.get('frozen_cell_count'):
            raise ValueError('Complete typed boundary records required')
        required = set()
        for name in context['private_sheets']:
            for cell in source_book[name]._cells.values():
                if cell.data_type == 'f':
                    refs = formula_references(cell.value, name, workbook=source_book,
                        max_expansion=50000)
                    if not refs['fully_supported']:
                        raise ValueError('Unresolved typed receipt source reference')
                    required.update((r['sheet'],r['cell']) for r in refs['references'])
        observed, snapshot_keys, frozen, mapping = set(), set(), {}, {}
        for record in records:
            key, target = tuple(record['source_cell']), tuple(record['snapshot_cell'])
            if (len(key) != 2 or len(target) != 2 or key in observed or target in snapshot_keys
                    or target[1] != key[1] or not re.fullmatch(r'__SCI_R_[a-f0-9]{4}', target[0])):
                raise ValueError('Typed snapshot mapping aliases or changes original coordinates')
            if key[0] in mapping and mapping[key[0]] != target[0]:
                raise ValueError('One boundary sheet maps to multiple snapshots')
            if key[0] not in mapping and target[0] in mapping.values():
                raise ValueError('Distinct boundary sheets alias one snapshot')
            mapping[key[0]] = target[0]; observed.add(key); snapshot_keys.add(target)
            descriptor = _typed_boundary(source_book[key[0]][key[1]], source_values[key[0]][key[1]],
                raw_metadata[0].get(key), source_book.epoch)
            if record.get('descriptor') != descriptor:
                raise ValueError('Typed boundary descriptor differs from exact actual source cache')
            for definitions, caches, metadata in ((raw_book,raw_values,raw_metadata[1]),
                                                  (actual_book,actual_values,raw_metadata[2])):
                _check_boundary(descriptor, definitions[target[0]][target[1]], caches[target[0]][target[1]],
                                metadata.get(target), caches.epoch)
            frozen[key] = descriptor
        if (observed != required or _digest([[_label(k),v] for k,v in sorted(frozen.items())])
                != residual.get('frozen_values_sha256')):
            raise ValueError('Complete frozen typed reference coverage or digest differs')
    finally:
        for book in books:
            book.close()


def _prepare(goal, combined_input, edits, directory, *, max_dependency_cells,
             max_dependency_edges, per_formula_reference_cells, max_island_cells, max_island_sheets,
             allow_constant_index_ancestors=False):
    if type(allow_constant_index_ancestors) is not bool:
        raise ValueError('Constant INDEX extension requires an explicit Boolean opt-in')
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
            max_edges=max_dependency_edges, per_formula=per_formula_reference_cells,
            allow_constant_index_ancestors=allow_constant_index_ancestors)
        # Reject unsupported domains before the first actual engine execution.
        # A new mutant can change a cache type, so the residual checks again.
        referenced = set().union(*(graph[k] for root in roots for k in membership[root]))
        members = set().union(*(membership[root] for root in roots))
        for context, (book, values) in enumerate(((original,original_values),(combined,combined_values))):
            raw = _raw_cells(paths['goal' if context == 0 else 'combined_input'])
            for key in members:
                _numeric(values[key[0]][key[1]])
            for key in referenced:
                _typed_boundary(book[key[0]][key[1]], values[key[0]][key[1]], raw.get(key), book.epoch)
        if graph_receipt['cyclic_SCC_count'] and (
                _settings(original)['iterate'] is not True
                or type(_settings(original)['iterateCount']) is not int
                or _settings(original)['iterateCount'] < 1
                or not isinstance(_settings(original)['iterateDelta'], (int, float))
                or _settings(original)['iterateDelta'] <= 0):
            raise ValueError('Cyclic islands require explicit copied iteration settings')
        compact = {key for key in roots if len(membership[key]) == 1 and key not in graph[key]}
        clone_count = sum(len(membership[key]) for key in roots)
        sheet_count = bool(compact) + sum(len({s for s, _ in membership[key]}) for key in roots - compact)
        if len(edits) + 1 > 1048576:
            raise ValueError('Compact DAG witness row bound exceeded')
        if clone_count > max_island_cells or sheet_count > max_island_sheets:
            raise ValueError('Complete SCC island allocation bound exceeded')
        contexts, root_plans = [], []
        for index, edit in enumerate(edits):
            key = edit['sheet'], edit['cell']; component = membership[key]
            root_plans.append({'root_index': index, 'root': _label(key),
                'SCC_cells': sorted(map(_label, component)), 'SCC_size': len(component),
                'cyclic': len(component) > 1 or key in graph[key],
                'union_self_loop': key in graph[key],
                'witness_layout': 'compact_DAG_scalar' if key in compact else 'complete_cyclic_SCC',
                'external_boundary': sorted(map(_label, set().union(*(graph[k] for k in component)) - component))})
        for context, (kind, book, values) in enumerate((
                ('individual', original, original_values), ('combined_marginal', combined, combined_values))):
            expected, locations, added = {}, [], []
            try:
                if compact:
                    book.create_sheet(_DAG); added.append(_DAG)
                for index, edit in enumerate(edits):
                    root = edit['sheet'], edit['cell']; component = membership[root]
                    if root in compact:
                        selected = 1 - context
                        if bounds.get((selected, root)):
                            raise ValueError('Whole-row/column rewrite is analysis-only, not a compact formula')
                        text = qualify_scalar_shadow(expanded[selected, root], root[0])
                        if graph[root] & component:
                            raise ValueError('Compact DAG root unexpectedly has an internal dependency')
                        address = 'B' + str(index + 2)
                        destination = book[_DAG][address]; destination.value = text
                        destination._style = copy(book[root[0]][root[1]]._style)
                        expected[_DAG, address] = text
                        locations.append((_DAG, address))
                        root_plans[index]['private_root'] = [_DAG, address]
                        root_plans[index]['private_members'] = [[_DAG, address]]
                        root_plans[index]['member_mapping'] = [{'business_cell': _label(root),
                            'private_sheet': _DAG, 'private_cell': address}]
                        continue
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
                    root_plans[index]['private_root'] = [mapping[root[0]], root[1]]
                    root_plans[index]['private_members'] = [[mapping[name], address] for name, address in sorted(component)]
                    root_plans[index]['member_mapping'] = [{'business_cell': _label((name, address)),
                        'private_sheet': mapping[name], 'private_cell': address} for name, address in sorted(component)]
                referenced = set()
                for key, text in expected.items():
                    refs = formula_references(text, key[0], workbook=book,
                        max_expansion=per_formula_reference_cells)
                    if not refs['fully_supported']:
                        raise ValueError('Unresolved complete residual allocation')
                    referenced.update((r['sheet'], r['cell']) for r in refs['references'])
                residual_sheet_count = len({name for name, _ in referenced})
                if len(added) + residual_sheet_count > max_island_sheets:
                    raise ValueError('Complete SCC/DAG plus residual sheet allocation bound exceeded')
                if len(expected) + len(referenced) > max_island_cells:
                    raise ValueError('Complete SCC/DAG plus residual cell allocation bound exceeded')
                raw = directory / (kind + '_scc_islands_raw.xlsx')
                book.save(raw)
                contexts.append({'kind': kind, 'base': 'goal' if context == 0 else 'combined_input',
                    'raw_path': raw, 'private_sheets': added[:], 'expected_formulas': expected,
                    'root_locations': locations, 'business_values': _all_values(book, values, business_names),
                    'residual_snapshot_sheet_count': residual_sheet_count,
                    'residual_snapshot_cell_count': len(referenced),
                    'total_private_sheet_count_with_residual': len(added) + residual_sheet_count,
                    'total_private_cell_count_with_residual': len(expected) + len(referenced)})
            finally:
                for name in added:
                    book.remove(book[name])
        summary = {'version': 8, 'state': 'planned_unexecuted', 'passed': False, 'blocking': True,
            'proof_directory': str(directory),
            'proof_method': _METHOD,
            'root_count': len(roots), 'union_graph': graph_receipt, 'root_SCCs': root_plans,
            'typed_boundary_policy': {'version': 1, 'domain': _BOUNDARY_DOMAIN,
                'SCC_members_finite_numeric_only': True, 'formula_empty_and_blank_rejected': True,
                'date_epoch_raw_serial_cachetype_style_bound': True},
            'witness_layout': {'version': 1, 'kind': 'compact_DAG_and_complete_cyclic_SCC',
                'compact_DAG_root_count': len(compact), 'cyclic_root_count': len(roots - compact),
                'compact_shared_sheet': _DAG if compact else None,
                'actual_private_sheet_count_per_context': sheet_count,
                'actual_private_member_count_per_context': clone_count,
                'maximum_private_sheet_count_with_residual': max(x['total_private_sheet_count_with_residual'] for x in contexts),
                'maximum_private_cell_count_with_residual': max(x['total_private_cell_count_with_residual'] for x in contexts),
                'mapping_sha256': _digest(root_plans)},
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
        max_dependency_edges=10000000, max_island_cells=1000000, max_island_sheets=1024,
        allow_constant_index_ancestors=False):
    """Write a fresh, unexecuted plan and two raw contexts; never assert proof."""
    directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=False)
    books, contexts, summary = _prepare(goal, combined_input, deepcopy(edits), directory,
        max_dependency_cells=max_dependency_cells, max_dependency_edges=max_dependency_edges,
        per_formula_reference_cells=per_formula_reference_cells, max_island_cells=max_island_cells,
        max_island_sheets=max_island_sheets, allow_constant_index_ancestors=allow_constant_index_ancestors)
    try:
        summary['contexts'] = [{'kind': c['kind'], 'base': c['base'], 'raw_path': str(c['raw_path']),
            'raw_sha256': _sha(c['raw_path']), 'private_sheets': c['private_sheets'],
            'root_locations': c['root_locations'],
            'residual_snapshot_sheet_count': c['residual_snapshot_sheet_count'],
            'residual_snapshot_cell_count': c['residual_snapshot_cell_count'],
            'total_private_sheet_count_with_residual': c['total_private_sheet_count_with_residual'],
            'total_private_cell_count_with_residual': c['total_private_cell_count_with_residual']} for c in contexts]
        _write(directory / 'scc_island_plan.json', summary)
        return summary
    finally:
        for book in books:
            book.close()


def prove_scc_island_root_impacts(*, goal, combined_input, edits, engine, directory,
        max_dependency_cells=500000, per_formula_reference_cells=50000,
        max_dependency_edges=10000000, max_island_cells=1000000, max_island_sheets=1024,
        allow_constant_index_ancestors=False):
    """Run two passes per context and fail closed on any incomplete local proof.

    Six engine executions validate two contexts: two stable cyclic passes and
    one frozen numerical F(x)=x residual evaluation per context. Caller still
    validates complete original/combined workbooks. No complete individual
    counterfactual replay or global uniqueness is implied.
    """
    directory = Path(directory).resolve(); directory.mkdir(parents=True, exist_ok=False)
    started = time.monotonic(); books = []; executing = False
    receipt = {'version': 8, 'proof_method': _METHOD, 'passed': False, 'blocking': True, 'root_impacts': [],
        'state': 'checking', 'actual_LO_started_count': 0, 'actual_LO_execution_count': 0,
        'engine_calls': [], 'root_checks': [], 'model_calls': 0}
    try:
        books, contexts, receipt = _prepare(goal, combined_input, deepcopy(edits), directory,
            max_dependency_cells=max_dependency_cells, max_dependency_edges=max_dependency_edges,
            per_formula_reference_cells=per_formula_reference_cells, max_island_cells=max_island_cells,
            max_island_sheets=max_island_sheets, allow_constant_index_ancestors=allow_constant_index_ancestors)
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
                per_formula=per_formula_reference_cells, max_cells=max_island_cells, max_sheets=max_island_sheets)
            receipt['contexts'].append({'kind': context['kind'], 'base': context['base'],
                'raw_path': str(context['raw_path']), 'raw_sha256': _sha(context['raw_path']),
                'all_business_definitions_unchanged': True, 'all_business_exact_typed_values_unchanged': True,
                'full_used_area_exact_two_pass_stable': True, 'value_count': len(prior),
                'values_sha256': _digest([[_label(k), v] for k, v in sorted(prior.items())]),
                'private_sheets': context['private_sheets'], 'fixed_point_residual': residual,
                'total_private_sheet_count_with_residual': context['total_private_sheet_count_with_residual'],
                'total_private_cell_count_with_residual': context['total_private_cell_count_with_residual'],
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
    require(c.get('version') == 8 and c.get('proof_method') == _METHOD
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
            and graph.get('all_ancestor_formulas_scalar_static_position_independent') is True
            and graph.get('all_before_after_formulas_and_reference_branches_included') is True,
            'complete union SCC analysis required')
    policy = c.get('typed_boundary_policy', {})
    require(policy == {'version': 1, 'domain': _BOUNDARY_DOMAIN,
            'SCC_members_finite_numeric_only': True, 'formula_empty_and_blank_rejected': True,
            'date_epoch_raw_serial_cachetype_style_bound': True}, 'typed boundary policy differs')
    extension = graph.get('constant_INDEX_extension', {})
    proofs = extension.get('proofs', [])
    require(extension.get('version') == 1 and type(extension.get('enabled')) is bool
            and isinstance(proofs, list) and type(extension.get('proof_count')) is int
            and extension['proof_count'] == len(proofs)
            and extension.get('proofs_sha256') == _digest(proofs)
            and extension.get('all_original_references_retained') is True
            and extension.get('business_definitions_rewritten') is False
            and (extension['enabled'] or not proofs), 'restricted INDEX extension binding differs')
    if proofs:
        books = []
        try:
            for path in (goal,combined_input):
                books.extend((openpyxl.load_workbook(path, keep_links=False),
                              openpyxl.load_workbook(path, data_only=True, keep_links=False)))
            original, original_values, combined, combined_values = books
            roots = {(edit['sheet'],edit['cell']) for edit in edits}
            seen = set()
            for proof in proofs:
                key = tuple(proof['anchor'].rsplit('!',1)); context = proof.get('context')
                require(type(context) is int and context in (0,1) and (context,key) not in seen,
                        'duplicate or invalid INDEX ancestor context')
                seen.add((context,key)); book = (original,combined)[context]
                refs = formula_references(book[key[0]][key[1]].value, key[0], workbook=book,
                    max_expansion=c['analysis_limits']['per_formula_reference_cells'], include_resolved_formula=True)
                require(refs['fully_supported'], 'INDEX source formula is unresolved')
                _, actual_proof = _constant_index_ancestor(refs['resolved_formula'], key, original, combined,
                    (original_values,combined_values), roots, context,
                    c['analysis_limits']['per_formula_reference_cells'])
                require(_digest(actual_proof) == _digest(proof), 'INDEX selector, guard, array or anchor proof changed')
        finally:
            for book in books:
                book.close()
    layout, plans = c.get('witness_layout', {}), c.get('root_SCCs', [])
    require(layout.get('kind') == 'compact_DAG_and_complete_cyclic_SCC'
            and isinstance(plans, list) and len(plans) == len(edits)
            and layout.get('mapping_sha256') == _digest(plans), 'complete witness mapping required')
    count_fields = ('compact_DAG_root_count', 'cyclic_root_count',
        'actual_private_sheet_count_per_context', 'actual_private_member_count_per_context',
        'maximum_private_sheet_count_with_residual', 'maximum_private_cell_count_with_residual')
    require(type(c.get('root_count')) is int
            and all(type(layout.get(key)) is int and layout[key] >= 0 for key in count_fields),
            'witness allocation counts must be integers')
    source = openpyxl.load_workbook(goal, read_only=True, keep_links=False)
    try:
        business_sheets = source.sheetnames[:]
    finally:
        source.close()
    member_keys, private_sheets, compact_count = set(), set(), 0
    for index, (edit, plan) in enumerate(zip(edits, plans)):
        root_label = edit['sheet'] + '!' + edit['cell']
        component, members, mapping = plan.get('SCC_cells', []), plan.get('private_members', []), plan.get('member_mapping', [])
        require(plan.get('root_index') == index and plan.get('root') == root_label
                and type(plan.get('SCC_size')) is int and plan['SCC_size'] == len(component) > 0
                and len(set(component)) == len(component) and root_label in component
                and len(members) == len(mapping) == len(component), 'SCC membership or witness allocation differs')
        own_keys = {tuple(k) for k in members}
        require(len(own_keys) == len(members) and not (own_keys & member_keys)
                and {tuple((m['private_sheet'], m['private_cell'])) for m in mapping} == own_keys
                and sorted(m['business_cell'] for m in mapping) == sorted(component),
                'private members alias or omit a root component')
        root_mapping = next(m for m in mapping if m['business_cell'] == root_label)
        require(plan.get('private_root') == [root_mapping['private_sheet'], root_mapping['private_cell']],
                'root location differs from its member mapping')
        if plan.get('witness_layout') == 'compact_DAG_scalar':
            compact_count += 1
            require(plan.get('cyclic') is False and plan.get('union_self_loop') is False
                    and component == [root_label] and members == [[_DAG, 'B' + str(index+2)]],
                    'compact witness is not a self-loop-free singleton')
        else:
            require(plan.get('witness_layout') == 'complete_cyclic_SCC' and plan.get('cyclic') is True
                    and (len(component) > 1 or plan.get('union_self_loop') is True)
                    and all(m['private_sheet'] != _DAG
                            and m['business_cell'].rsplit('!',1)[0] in business_sheets
                            and m['private_cell'] == m['business_cell'].rsplit('!',1)[1]
                            and m['private_sheet'] == f'{_PREFIX}{index:04x}_{business_sheets.index(m["business_cell"].rsplit("!",1)[0]):03x}'
                            for m in mapping),
                    'cyclic island must retain its complete original coordinates')
        member_keys.update(own_keys); private_sheets.update(k[0] for k in own_keys)
    require(layout.get('compact_DAG_root_count') == compact_count
            and layout.get('cyclic_root_count') == len(edits)-compact_count
            and layout.get('compact_shared_sheet') == (_DAG if compact_count else None)
            and layout.get('actual_private_sheet_count_per_context') == len(private_sheets)
            and layout.get('actual_private_member_count_per_context') == len(member_keys)
            and c.get('private_sheet_count_per_context') == len(private_sheets)
            and c.get('private_island_formula_count_per_context') == len(member_keys),
            'actual compact/cyclic sheet or member counts differ')
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
            and residual.get('snapshot_value_domain') == _BOUNDARY_DOMAIN
            and residual.get('SCC_member_count') == c.get('private_island_formula_count_per_context'),
            'stable exact contexts and full numeric F(x)=x residuals required')
        locations = context.get('root_locations', [])
        require(set(context.get('private_sheets', [])) == private_sheets
                and len(context['private_sheets']) == len(private_sheets)
                and isinstance(locations, list) and all(isinstance(x, (list, tuple)) and len(x) == 2 for x in locations)
                and [tuple(x) for x in locations] == [tuple(p['private_root']) for p in plans],
                'context root or sheet mapping differs')
        require(residual.get('actual_total_private_sheet_count') == context.get('total_private_sheet_count_with_residual')
                and residual.get('actual_total_private_cell_count') == context.get('total_private_cell_count_with_residual')
                and residual['actual_total_private_sheet_count'] <= c['analysis_limits']['max_island_sheets']
                and residual['actual_total_private_cell_count'] <= c['analysis_limits']['max_island_cells'],
                'actual residual allocation exceeds or differs from the frozen budget')
        artifact(residual.get('raw_path', ''), residual.get('raw_sha256'))
        artifact(residual.get('actual_path', ''), residual.get('actual_sha256'))
        pass2 = next(x for x in calls if x['kind'] == context['kind'] and x['pass'] == 2)
        _validate_typed_residual(residual, context, pass2['output_path'])
        actual = openpyxl.load_workbook(pass2['output_path'], keep_links=False)
        try:
            observed = {(name, cell.coordinate) for name in private_sheets
                        for cell in actual[name]._cells.values() if cell.value is not None}
            require(observed == member_keys, 'actual primary witness cell inventory differs')
        finally:
            actual.close()
    require(layout.get('maximum_private_sheet_count_with_residual') == max(
                x['fixed_point_residual']['actual_total_private_sheet_count'] for x in contexts)
            and layout.get('maximum_private_cell_count_with_residual') == max(
                x['fixed_point_residual']['actual_total_private_cell_count'] for x in contexts),
            'maximum actual residual allocation differs')
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
