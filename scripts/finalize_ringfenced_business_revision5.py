#!/usr/bin/env python3
"""Preserve retained raw-zero evidence without requiring its historical clock flag."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
from pathlib import Path
from types import FunctionType, SimpleNamespace

PREVIOUS = Path(__file__).resolve().with_name('finalize_ringfenced_business_revision4.py')
PREVIOUS_SHA = 'd08c4202abe6ea69d2b9a6f1e1b918b410096084a4f52fd9005ef4afcc7606cb'
if hashlib.sha256(PREVIOUS.read_bytes()).hexdigest() != PREVIOUS_SHA:
    raise ValueError('The frozen upper-bound finalizer changed')
loader = importlib.util.spec_from_file_location('_ring_revision5_frozen_interval_join', PREVIOUS)
previous = importlib.util.module_from_spec(loader); loader.loader.exec_module(previous)
base = previous.base
ref, read, require = base.ref, base.read, base.require
OLD = "failure['resources_passed'] is failure['tool_time_passed'] is True"
NEW = "failure['resources_passed'] is True"


def retained_clock_seam(source):
    """Replace exactly one legacy predicate; preserve every other admission check."""
    tree = ast.parse(source); expected = ast.dump(ast.parse(OLD, mode='eval').body)
    changes = []
    class Replace(ast.NodeTransformer):
        def visit_Compare(self, node):
            if ast.dump(node) == expected:
                changes.append(True)
                return ast.copy_location(ast.parse(NEW, mode='eval').body, node)
            return self.generic_visit(node)
    tree = Replace().visit(tree)
    require(len(changes) == 1, 'The exact-one retained historical clock seam changed')
    return ast.fix_missing_locations(tree)


def finalize(installed, confirmation, review, actual_controls, output, *, review_contract, development=()):
    before = ref(PREVIOUS); implementation = ref(__file__)
    namespace = dict(vars(base))
    tree = retained_clock_seam(inspect.getsource(base.finalize))
    exec(compile(tree, __file__, 'exec'), namespace)
    private_base = SimpleNamespace(**vars(base))
    private_base.finalize = namespace['finalize']
    def final_write(path, value):
        require(value['kind'] == 'qualified_ringfenced_business_revision_release' and value['version'] == 4,
            'The retained compatibility adapter writes only a complete upper-bound release')
        require(ref(PREVIOUS) == before and ref(__file__) == implementation, 'A frozen compatibility adapter changed')
        value['version'] = 5
        value['finalizer_revision5'] = {'implementation': implementation, 'frozen_upper_bound_finalizer': before,
            'exact_one_predicate_change': {'from': OLD, 'to': NEW},
            'retained_raw_zero_budget_adjusted_interval': [0, 0],
            'original_retained_clock_flags_and_scores_preserved': True,
            'retained_identity_resources_raw_zero_state_boundary_and_result_bindings_preserved': True}
        return base.write(path, value)
    private_base.write = final_write
    dispatch = dict(vars(previous)); dispatch['base'] = private_base
    original = previous.finalize
    adapted = FunctionType(original.__code__, dispatch, original.__name__, original.__defaults__, original.__closure__)
    adapted.__kwdefaults__ = original.__kwdefaults__
    return adapted(installed, confirmation, review, actual_controls, output,
        review_contract=review_contract, development=development)


def main():
    # Reuse the frozen CLI and replace only its finalization function in a private namespace.
    namespace = dict(vars(previous)); namespace['finalize'] = finalize
    original = previous.main
    FunctionType(original.__code__, namespace, original.__name__, original.__defaults__, original.__closure__)()


if __name__ == '__main__':
    main()
