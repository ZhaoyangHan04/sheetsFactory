"""Opt-in constant-time worksheet lookup for complete read-only analyses.

No workbook, cell, formula, analysis limit or existing module is changed.
Each index lives for one reader call; those readers never change sheet names.
The original probe and profiling algorithms run in private namespaces.
"""
from __future__ import annotations

import ast
from collections.abc import Sequence
import hashlib
from pathlib import Path
from types import FunctionType

from . import profile_indexed as original_profile
from ..checkers import native_error_probe as original_probe
from ..pipelines import entity_group_contract as original_large_probe

PINS = {
    original_profile.__file__: 'bf8512cbda69fa22365f9e9e18b63fc23830be4c60a54aaf5011654b7e1a0615',
    original_probe.__file__: 'e81f38b303fb55e66a836f7fa4e716f91d8d9448f44d3478820c10b1acfc7a88',
    original_large_probe.__file__: '7c28489ed840148b27ebfbb5d0d835e52db6ae38f41b9264ce7bf8a737ab6f6e',
}


def verify_dependencies():
    for path, digest in PINS.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise ValueError('Frozen complete-analysis dependency changed: ' + path)


class _SheetNames(Sequence):
    """Keep original order and slicing, with exact-string set membership."""
    def __init__(self, names):
        self._names = tuple(names)
        self._members = frozenset(self._names)

    def __len__(self):
        return len(self._names)

    def __getitem__(self, key):
        value = self._names[key]
        return list(value) if isinstance(key, slice) else value

    def __contains__(self, key):
        return key in self._members if type(key) is str else key in self._names

    def __eq__(self, other):
        return list(self._names) == other


class WorkbookLookupIndex:
    """Snapshot sheet lookup only; all returned worksheets are original objects.

    Use only while the workbook's sheet names and order stay fixed. Cell reads
    and named-range resolution retain the same original workbook objects.
    """
    def __init__(self, book):
        self._book = book
        self.sheetnames = _SheetNames(book.sheetnames)
        self._by_title = {}
        # This is the original Workbook.__getitem__ search order, including
        # its first-match behavior for a malformed duplicate title.
        for sheet in book.worksheets + book.chartsheets:
            self._by_title.setdefault(sheet.title, sheet)

    def __getitem__(self, key):
        if type(key) is not str:
            return self._book[key]
        if key not in self._by_title:
            raise KeyError('Worksheet {} does not exist.'.format(key))
        return self._by_title[key]

    def __getattr__(self, name):
        return getattr(self._book, name)


def _reader(module, name):
    """Change only repeated worksheet access and formula context lookup."""
    verify_dependencies()
    nodes = [n for n in ast.parse(Path(module.__file__).read_bytes()).body
             if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(nodes) != 1:
        raise ValueError('Exactly one frozen complete reader is required')
    node = nodes[0]
    if any(isinstance(n, ast.Name) and n.id in
           {'_formula_index', '_value_index', '_cached_index'} for n in ast.walk(node)):
        raise ValueError('Private index names collided with the frozen reader')
    indexes = {'book': '_formula_index', 'values': '_value_index', 'cached': '_cached_index'}
    hits = {'subscript': 0, 'names': 0, 'formula_context': 0, 'setup': 0}

    class Indexed(ast.NodeTransformer):
        def visit_Subscript(self, value):
            if isinstance(value.value, ast.Name) and value.value.id in indexes:
                value.value.id = indexes[value.value.id]
                hits['subscript'] += 1
            return self.generic_visit(value)

        def visit_Attribute(self, value):
            if (isinstance(value.value, ast.Name) and value.value.id in indexes
                    and value.attr == 'sheetnames'):
                value.value.id = indexes[value.value.id]
                hits['names'] += 1
            return self.generic_visit(value)

        def visit_keyword(self, value):
            if value.arg == 'workbook' and isinstance(value.value, ast.Name) and value.value.id == 'book':
                value.value.id = '_formula_index'
                hits['formula_context'] += 1
            return self.generic_visit(value)

    node = Indexed().visit(node)
    tries = [statement for statement in node.body if isinstance(statement, ast.Try)]
    if len(tries) != 1:
        raise ValueError('Frozen reader lifetime changed')
    body = tries[0].body
    if name == 'profile_workbook':
        if not (isinstance(body[0], ast.Assign)
                and ast.unparse(body[0].targets[0]) == 'cached'):
            raise ValueError('Cached profile workbook lifetime changed')
        position = 1
        setup = '_formula_index=WorkbookLookupIndex(book)\n_cached_index=WorkbookLookupIndex(cached)'
    else:
        position = 0
        setup = '_formula_index=WorkbookLookupIndex(book)'
        if name == '_full_closure_candidates':
            setup += '\n_value_index=WorkbookLookupIndex(values)'
    body[position:position] = ast.parse(setup).body
    hits['setup'] += 1
    expected = {'_required_values': {'subscript': 1, 'names': 2, 'formula_context': 0, 'setup': 1},
                '_full_closure_candidates': {'subscript': 3, 'names': 2, 'formula_context': 1, 'setup': 1},
                'profile_workbook': {'subscript': 2, 'names': 0, 'formula_context': 1, 'setup': 1}}
    if hits != expected[name]:
        raise ValueError('Exact worksheet lookup sites changed: ' + name + ' ' + str(hits))
    namespace = {**vars(module), 'WorkbookLookupIndex': WorkbookLookupIndex}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 __file__, 'exec'), namespace)
    return namespace[name]


_required_values = _reader(original_probe, '_required_values')
_full_closure_candidates = _reader(original_probe, '_full_closure_candidates')
profile_workbook = _reader(original_profile, 'profile_workbook')


def _probe(original):
    namespace = {**original.__globals__, '_required_values': _required_values,
                 '_full_closure_candidates': _full_closure_candidates}
    function = FunctionType(original.__code__, namespace, original.__name__, original.__defaults__, original.__closure__)
    function.__kwdefaults__ = original.__kwdefaults__
    return function


# Explicit alternatives. The 500,000/3,000,000 limits remain exactly original.
probe_native_errors = _probe(original_probe.probe_native_errors)
probe_native_errors_large = _probe(original_large_probe.probe_native_errors)
