"""Conservative error reach with narrow, public fixed-selector certificates.

This module does not evaluate branches or certify a workbook's business logic.
Only literal VLOOKUP/INDEX selectors and literal IF conditions narrow refs.
"""
from __future__ import annotations

from pathlib import Path
import re

import openpyxl
from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils.cell import get_column_letter, range_boundaries

from ..workbook.profile import formula_references


_CELL = re.compile(r"\$?[A-Za-z]{1,3}\$?[1-9][0-9]*$")
_RANGE = re.compile(r"\$?[A-Za-z]{1,3}\$?[1-9][0-9]*(?::\$?[A-Za-z]{1,3}\$?[1-9][0-9]*)?$")
_INTEGER = re.compile(r"[1-9][0-9]*$")
_FUNCTION = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*\($")


def validate_static_reference_syntax(formula: str) -> str | None:
    """Reject reference construction that the ordinary A1 parser cannot cover.

    In particular, ``INDEX(...):INDEX(...)`` can include cells outside either
    literal array. Tokenizer encodes its second function as ``:INDEX(``, which
    must not be mistaken for an ordinary function or a fixed INDEX certificate.
    Union and intersection operators are intentionally outside this analyser.
    """
    try:
        tokens = Tokenizer(formula).items
        stack = []
        for index, token in enumerate(tokens):
            if token.type == 'FUNC' and token.subtype == 'OPEN' and not _FUNCTION.fullmatch(token.value):
                return 'compound or unsupported reference-function syntax'
            if token.type == 'OPERATOR-INFIX' and token.value in (',', ':', ' '):
                return 'reference union, range construction or intersection is unsupported'
            if token.type == 'WHITE-SPACE':
                previous = next((item for item in reversed(tokens[:index]) if item.type != 'WHITE-SPACE'), None)
                following = next((item for item in tokens[index + 1:] if item.type != 'WHITE-SPACE'), None)
                ends_reference = previous is not None and (
                    (previous.type == 'OPERAND' and previous.subtype == 'RANGE')
                    or (previous.type in ('FUNC', 'PAREN') and previous.subtype == 'CLOSE'))
                starts_reference = following is not None and (
                    (following.type == 'OPERAND' and following.subtype == 'RANGE')
                    or (following.type in ('FUNC', 'PAREN') and following.subtype == 'OPEN'))
                if ends_reference and starts_reference:
                    return 'reference intersection is unsupported'
            if token.type == 'OPERAND' and token.subtype == 'RANGE':
                address = token.value.rsplit('!', 1)[-1]
                if not _RANGE.fullmatch(address):
                    return 'unresolved or compound reference operand'
                left, top, right, bottom = range_boundaries(address)
                if left > right or top > bottom or right > 16384 or bottom > 1048576:
                    return 'invalid bounded reference'
                if '[' in token.value or ']' in token.value:
                    return 'external or structured reference is unsupported'
                if '!' in token.value and ':' in token.value.rsplit('!', 1)[0]:
                    return 'three-dimensional sheet reference is unsupported'
            if token.subtype == 'OPEN':
                stack.append(token.type)
            elif token.subtype == 'CLOSE':
                if not stack or stack.pop() != token.type:
                    return 'unbalanced formula syntax'
        return 'unbalanced formula syntax' if stack else None
    except Exception:
        return 'unable to parse static reference syntax'


def _coordinate(value):
    if not isinstance(value, str) or not _CELL.fullmatch(value):
        raise ValueError('invalid cell coordinate')
    value = value.replace('$', '').upper()
    left, top, right, bottom = range_boundaries(value)
    if right > 16384 or bottom > 1048576:
        raise ValueError('cell coordinate exceeds workbook limits')
    return value


def _label(key):
    return key[0] + '!' + key[1]


def _narrow_occurrences(tokens):
    """Find exactly parsed fixed selectors, retaining token occurrence identity.

    Function, parenthesis and array frames prevent a nested comma from being
    confused with a VLOOKUP argument separator. Any malformed nesting causes
    the caller to retain the complete ordinary reference set.
    """
    stack, tables, skipped, branches = [], {}, set(), []
    for index, token in enumerate(tokens):
        if token.subtype == 'OPEN':
            stack.append({'type': token.type, 'name': token.value[:-1].upper(),
                          'start': index + 1, 'arguments': []})
        elif token.type == 'SEP' and token.subtype == 'ARG':
            if stack and stack[-1]['type'] == 'FUNC':
                frame = stack[-1]
                frame['arguments'].append(list(range(frame['start'], index)))
                frame['start'] = index + 1
        elif token.subtype == 'CLOSE':
            if not stack or stack[-1]['type'] != token.type:
                raise ValueError('unbalanced formula tokens')
            frame = stack.pop()
            if frame['type'] != 'FUNC':
                continue
            frame['arguments'].append(list(range(frame['start'], index)))
            arguments = [[i for i in arg if tokens[i].type != 'WHITE-SPACE']
                         for arg in frame['arguments']]
            if frame['name'] == 'IF' and len(arguments) in (2, 3):
                condition = arguments[0]
                if (len(condition) == 2 and tokens[condition[0]].type == 'FUNC'
                        and tokens[condition[0]].subtype == 'OPEN'
                        and tokens[condition[0]].value.upper() in ('TRUE(', 'FALSE(')
                        and tokens[condition[1]].type == 'FUNC'
                        and tokens[condition[1]].subtype == 'CLOSE'):
                    literal_text = tokens[condition[0]].value + tokens[condition[1]].value
                    selected = 1 if tokens[condition[0]].value.upper() == 'TRUE(' else 2
                elif len(condition) == 1 and tokens[condition[0]].type == 'OPERAND':
                    literal = tokens[condition[0]]
                    literal_text = literal.value
                    if literal.subtype == 'LOGICAL' and literal.value.upper() in ('TRUE', 'FALSE'):
                        selected = 1 if literal.value.upper() == 'TRUE' else 2
                    elif literal.subtype == 'NUMBER' and literal.value in ('0', '1'):
                        selected = 1 if literal.value == '1' else 2
                    else:
                        continue
                else:
                    continue
                ignored = 2 if selected == 1 else 1
                ignored_tokens = arguments[ignored] if ignored < len(arguments) else []
                skipped.update(ignored_tokens)
                branches.append({'condition': literal_text, 'selected_argument': selected,
                                 'ignored_tokens': ignored_tokens})
                continue
            if frame['name'] not in ('VLOOKUP', 'INDEX'):
                continue
            if ((frame['name'] == 'VLOOKUP' and len(arguments) not in (3, 4))
                    or (frame['name'] == 'INDEX' and len(arguments) not in (2, 3))):
                continue
            table_arg = 1 if frame['name'] == 'VLOOKUP' else 0
            selector_arg = 2 if frame['name'] == 'VLOOKUP' else 1
            table, selector = arguments[table_arg], arguments[selector_arg]
            if len(table) != 1 or len(selector) != 1:
                continue
            table_token, selected_token = tokens[table[0]], tokens[selector[0]]
            if (table_token.type != 'OPERAND' or table_token.subtype != 'RANGE'
                    or selected_token.type != 'OPERAND' or selected_token.subtype != 'NUMBER'
                    or not _INTEGER.fullmatch(selected_token.value)):
                continue
            address = table_token.value.rsplit('!', 1)[-1]
            if not _RANGE.fullmatch(address):
                continue
            left, top, right, bottom = range_boundaries(address)
            if left > right or top > bottom or right > 16384 or bottom > 1048576:
                continue
            selected_index = int(selected_token.value)
            if frame['name'] == 'VLOOKUP':
                if selected_index > right - left + 1:
                    continue
                tables[table[0]] = {'kind': 'vlookup_fixed_key_and_return_columns',
                    'selected_column_index': selected_index, 'left': left,
                    'return_column': left + selected_index - 1}
            else:
                if len(arguments) == 2:
                    if left != right:
                        continue
                    column_index = 1
                else:
                    column = arguments[2]
                    if (len(column) != 1 or tokens[column[0]].type != 'OPERAND'
                            or tokens[column[0]].subtype != 'NUMBER'
                            or not _INTEGER.fullmatch(tokens[column[0]].value)):
                        continue
                    column_index = int(tokens[column[0]].value)
                if selected_index > bottom - top + 1 or column_index > right - left + 1:
                    continue
                tables[table[0]] = {'kind': 'index_fixed_row_and_column',
                    'selected_row_index': selected_index, 'selected_column_index': column_index,
                    'selected_cell': f'{get_column_letter(left + column_index - 1)}{top + selected_index - 1}'}
    if stack:
        raise ValueError('unbalanced formula tokens')
    return tables, skipped, branches


def _references(formula, sheet, key, candidates):
    ordinary = formula_references(formula, sheet)
    fallback = {(ref['sheet'], ref['cell']) for ref in ordinary['references']}
    if not ordinary['fully_supported']:
        return fallback, [], 'unsupported references at ' + _label(key)
    syntax_problem = validate_static_reference_syntax(formula)
    if syntax_problem:
        return fallback, [], syntax_problem + ' at ' + _label(key)
    try:
        tokens = Tokenizer(formula).items
        tables, skipped, branches = _narrow_occurrences(tokens)
    except Exception:
        return fallback, [], None
    references, exclusions = set(), []
    for branch in branches:
        ignored = set()
        for index in branch['ignored_tokens']:
            token = tokens[index]
            if token.type == 'OPERAND' and token.subtype == 'RANGE':
                refs = formula_references('=' + token.value, sheet)['references']
                ignored.update((ref['sheet'], ref['cell']) for ref in refs)
        if branch['ignored_tokens']:
            exclusions.append({'kind': 'if_literal_condition',
                'formula_cell': _label(key), 'formula': formula,
                'condition': branch['condition'], 'selected_argument': branch['selected_argument'],
                'ignored_errors': sorted(_label(item) for item in ignored & candidates),
                'ignored_token_indices': branch['ignored_tokens'],
                'scope': 'Only the unselected argument of this literal IF occurrence.'})
    for index, token in enumerate(tokens):
        if token.type != 'OPERAND' or token.subtype != 'RANGE':
            continue
        if index in skipped:
            continue
        occurrence = formula_references('=' + token.value, sheet)
        if not occurrence['fully_supported']:
            return fallback, [], 'unsupported reference occurrence at ' + _label(key)
        entries = occurrence['references']
        table = tables.get(index)
        if table is None:
            references.update((ref['sheet'], ref['cell']) for ref in entries)
            continue
        ignored = set()
        for ref in entries:
            ref_key = (ref['sheet'], ref['cell'])
            if table['kind'] == 'vlookup_fixed_key_and_return_columns':
                relevant = range_boundaries(ref['cell'])[0] in {table['left'], table['return_column']}
            else:
                relevant = ref['cell'] == table['selected_cell']
            if relevant:
                references.add(ref_key)
            else:
                ignored.add(ref_key)
        if ignored:
            certificate = {'kind': table['kind'],
                'formula_cell': _label(key), 'formula': formula,
                'table': token.value, 'table_token_index': index,
                'table_sheet': entries[0]['sheet'],
                'selected_column_index': table['selected_column_index'],
                'ignored_errors': sorted(_label(item) for item in ignored & candidates),
                'scope': 'This table occurrence only; other references remain relevant.'}
            if table['kind'] == 'vlookup_fixed_key_and_return_columns':
                certificate.update({'key_column': get_column_letter(table['left']),
                                    'return_column': get_column_letter(table['return_column'])})
            else:
                certificate.update({'selected_row_index': table['selected_row_index'],
                                    'selected_cell': entries[0]['sheet'] + '!' + table['selected_cell']})
            exclusions.append(certificate)
    return references, exclusions, None


def dependency_error_reach(goal: Path, delta_labels: list[str], candidates: list[dict],
                           max_cells=20000) -> dict:
    """Find candidate-error ancestors of every actual changed output cell.

    ``verified`` means a complete, bounded conservative dependency traversal.
    It does not mean that reachable errors affect the cached values. Missing
    sheets, unsupported references, cycles and scope overflow remain unknown.
    """
    result = {'state': 'unknown', 'per_delta_errors': {}, 'exclusions': []}
    book = None
    try:
        if type(max_cells) is not int or max_cells < 1:
            raise ValueError('max_cells must be a positive integer')
        book = openpyxl.load_workbook(goal, data_only=False, keep_links=False)
        candidate_keys = set()
        for candidate in candidates:
            key = (candidate['sheet'], _coordinate(candidate['cell']))
            if key[0] not in book.sheetnames:
                raise ValueError('candidate references a missing sheet')
            candidate_keys.add(key)
        roots = {}
        for value in delta_labels:
            sheet, address = value.rsplit('!', 1)
            key = (sheet, _coordinate(address))
            if sheet not in book.sheetnames:
                raise ValueError('changed output references a missing sheet')
            roots[value] = key
        result['per_delta_errors'] = {value: [] for value in roots}
        graph, pending, problems = {}, list(dict.fromkeys(roots.values())), []
        while pending:
            key = pending.pop()
            if key in graph:
                continue
            if len(graph) >= max_cells:
                raise ValueError('dependency closure exceeds max_cells')
            if key[0] not in book.sheetnames:
                raise ValueError('dependency references a missing sheet')
            address = _coordinate(key[1])
            cell = book[key[0]][address]
            references = set()
            if cell.data_type == 'f':
                if not isinstance(cell.value, str):
                    problems.append('unsupported formula object at ' + _label(key))
                else:
                    references, exclusions, problem = _references(cell.value, key[0], key, candidate_keys)
                    result['exclusions'].extend(exclusions)
                    if problem:
                        problems.append(problem)
            graph[key] = references
            pending.extend(sorted(references - graph.keys()))
        result['closure_cells'] = len(graph)
        # Iterative postorder supports long chains without a recursion limit.
        memo, active = {}, set()
        for value, root in roots.items():
            stack = [(root, False)]
            while stack:
                key, completed = stack.pop()
                if key in memo:
                    continue
                if completed:
                    reached = {key} if key in candidate_keys else set()
                    for dependency in graph[key]:
                        reached.update(memo[dependency])
                    memo[key] = reached
                    active.remove(key)
                    continue
                if key in active:
                    raise ValueError('cycle in changed-output dependency closure at ' + _label(key))
                active.add(key)
                stack.append((key, True))
                stack.extend((dependency, False) for dependency in sorted(graph[key], reverse=True)
                             if dependency not in memo)
            result['per_delta_errors'][value] = sorted(_label(key) for key in memo[root])
        if problems:
            result['reason'] = '; '.join(sorted(set(problems)))
        else:
            result['state'] = 'verified'
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        result['reason'] = str(exc)
    finally:
        if book is not None:
            book.close()
    return result
