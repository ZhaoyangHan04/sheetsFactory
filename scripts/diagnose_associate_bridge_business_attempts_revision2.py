#!/usr/bin/env python3
"""Opt-in aggregate-currency completion over the frozen submission-only driver."""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from sheets_factory.evaluation import business_failure_evidence_revision2 as currencies

BASE = ROOT/'scripts/diagnose_associate_bridge_business_attempts.py'
BASE_SHA = '6deae634290bbd76d571704d70faa8d1bf1a56f6a2b1e0c72d959ec413eacf5d'
CURRENCY_SHA = '5d8bd5e3e7401296da96eeb11d1cecf62ad88fdc360d134894e3df8f6873243a'


def _guard():
    currencies.verify_dependencies()
    if hashlib.sha256(BASE.read_bytes()).hexdigest() != BASE_SHA:
        raise ValueError('The frozen associate diagnosis driver changed')
    if currencies.base.reference(currencies.__file__)['sha256'] != CURRENCY_SHA:
        raise ValueError('The aggregate currency helper changed')


def _namespace():
    _guard()
    counts = Counter()
    class Revision(ast.NodeTransformer):
        def visit_Assign(self, node):
            node = self.generic_visit(node)
            if (len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == 'scales' and isinstance(node.value, ast.DictComp)):
                counts['scales'] += 1
                node.value = ast.Call(ast.Name('_complete_money_scales', ast.Load()),
                    [ast.Name('bindings', ast.Load()), node.value], [])
            return node
        def visit_Constant(self, node):
            replacements = {
                'fixed_associate_bridge_saved_submission_diagnosis': 'fixed_associate_bridge_saved_submission_diagnosis_revision2',
                'complete_associate_bridge_auxiliary_business_diagnosis': 'complete_associate_bridge_auxiliary_business_diagnosis_revision2'}
            if isinstance(node.value, str) and node.value in replacements:
                counts[node.value] += 1
                return ast.copy_location(ast.Constant(replacements[node.value]), node)
            return node
    tree = Revision().visit(ast.parse(BASE.read_text(), filename=str(BASE)))
    if counts != Counter({'scales': 1, 'fixed_associate_bridge_saved_submission_diagnosis': 1,
                          'complete_associate_bridge_auxiliary_business_diagnosis': 1}):
        raise ValueError('The exact aggregate scale and revision identity seams changed')
    namespace = {'__name__': '_aggregate_complete_frozen_associate_diagnosis', '__file__': __file__,
                 '_complete_money_scales': currencies.complete_money_scales}
    exec(compile(ast.fix_missing_locations(tree), str(BASE), 'exec'), namespace)
    original_recipes = namespace['recipes']
    def recipes():
        _guard()
        return [*original_recipes(), namespace['reference'](BASE), namespace['reference'](currencies.__file__)]
    namespace['recipes'] = recipes
    return namespace


_N = _namespace()
run = _N['run']
main = _N['main']
if __name__ == '__main__': main()
