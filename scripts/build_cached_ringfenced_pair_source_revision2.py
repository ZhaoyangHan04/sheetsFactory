#!/usr/bin/env python3
"""Bind the completed cached-source recipe to the streaming callback contract."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import FunctionType

BASE = Path(__file__).resolve().with_name('build_cached_ringfenced_pair_source.py')
BASE_SHA = '13b9ba6663a611bb866e98351a118e314658f2d6eec7db4d6a628e9367653958'
if hashlib.sha256(BASE.read_bytes()).hexdigest() != BASE_SHA:
    raise ValueError('The original frozen cached-source recipe changed')
loader = importlib.util.spec_from_file_location('_cached_ringfenced_source_frozen_base', BASE)
base = importlib.util.module_from_spec(loader); loader.loader.exec_module(base)


def formula_rename(formula, sheets, names=None, *, local_sheet=None, defined_name=False):
    base.require(not names and not defined_name, 'These fully witnessed donor sources contain no defined names')
    return base.formula_rename(formula, sheets, local_sheet=local_sheet)


def fast_stream_formula(text, donor, sheet=None, *, defined=False):
    # All donor formula syntax is already witnessed by the immutable full-ten
    # parse. The frozen rewriter proves a byte-exact inverse for every new name
    # substitution. Repeating a full grammar parse here adds no new check.
    result = formula_rename(text, donor['sheet_map'], donor['names'], local_sheet=sheet, defined_name=defined)
    base.require(len(result) <= 8192, 'A namespaced formula exceeds the Excel length limit')
    return result


def composer():
    value = namespace['base_composer']()
    # Mutate only the new private cloned namespace returned by the frozen base.
    value.__globals__['_formula'] = fast_stream_formula
    return value


def recipes():
    return [base.ref(__file__), base.ref(BASE), *base.recipes()[1:]]


namespace = dict(vars(base))
namespace.update(__file__=__file__, __name__=__name__)
for name, value in vars(base).items():
    if isinstance(value, FunctionType) and value.__globals__ is vars(base):
        clone = FunctionType(value.__code__, namespace, name, value.__defaults__, value.__closure__)
        clone.__kwdefaults__ = value.__kwdefaults__; namespace[name] = clone
namespace.update(base_composer=namespace['composer'], composer=composer, recipes=recipes, formula_rename=formula_rename)
for name, value in namespace.items():
    if not name.startswith('__') and name not in {'base', 'namespace', 'BASE', 'BASE_SHA'}:
        globals()[name] = value

if __name__ == '__main__':
    namespace['main']()
