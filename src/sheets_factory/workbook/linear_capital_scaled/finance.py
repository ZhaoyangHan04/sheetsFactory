"""Two unchanged financial forwards in separate version-two namespaces.

Only the public schema import is rebound. Fraction A never imports Decimal B,
and neither forward consumes the other's posted values or coefficient matrix.
The common comparison functions are read-only checks, not a third ledger.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from types import ModuleType

from . import spec

UPSTREAMS = {
    'candidate_a': 'dae797e3d62cd3e84965c7d3d7edb74ad83ecee113167b2943f581cf4351d322',
    'ledger': 'c97035a85583b6ff82509c5fd1dfe57bdbabfb39fa1b7bf50fa270532add1e7f',
    'finance_crosscheck': 'bd25d57e57ac541dc74971e6ccfc78215be2ceaedc6cc323eb3a2395e82f89b2',
}
_MODULES = {}


def upstream_path(name):
    spec.require(name in UPSTREAMS, 'Unknown frozen financial implementation')
    sibling = Path(__file__).with_name('frozen_'+name+'.py')
    return sibling if sibling.is_file() else Path(__file__).resolve().parents[1]/'linear_capital_portfolio'/(name+'.py')


def adapted_ast(name):
    path = upstream_path(name); raw = path.read_bytes()
    spec.require(hashlib.sha256(raw).hexdigest() == UPSTREAMS[name], 'The unchanged financial implementation differs: '+name)
    tree = ast.parse(raw, filename=str(path))
    imports = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.level]
    spec.require(len(imports) == 1 and imports[0].module == 'spec' and imports[0].level == 1,
        'Only the explicit public schema import may bind the new financial namespace')
    if name == 'finance_crosscheck':
        # The old crosscheck's two imports resolve to the separately loaded
        # unchanged forwards below, never the old package or shared calculator.
        matches = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
            and n.level == 1 and n.module is None and [a.name for a in n.names] == ['candidate_a','ledger']]
        spec.require(len(matches) == 1, 'The exact two-forward comparison import changed')
        class BindForwards(ast.NodeTransformer):
            def visit_ImportFrom(self, node):
                return ast.copy_location(ast.Pass(), node) if node is matches[0] else node
        tree = BindForwards().visit(tree)
    return ast.fix_missing_locations(tree)


def _module(name):
    # Check original bytes even on a warm namespace. No financial results are
    # cached and no original module dictionary is modified.
    tree = adapted_ast(name)
    if name not in _MODULES:
        module = ModuleType(__package__+'._frozen_'+name)
        module.__package__ = __package__; module.__file__ = str(upstream_path(name))
        if name == 'finance_crosscheck':
            module.candidate_a = _module('candidate_a'); module.ledger = _module('ledger')
        exec(compile(tree, module.__file__, 'exec'), module.__dict__)
        _MODULES[name] = module
    return _MODULES[name]


def source_files():
    return {'finance': Path(__file__), 'spec': Path(spec.__file__),
        'frozen_spec': spec.upstream_path(),
        **{'frozen_'+name: upstream_path(name) for name in UPSTREAMS}}


def build_universe_a(public):
    return _module('candidate_a').simulate_universe(public)


def build_universe_b(public):
    return _module('ledger').simulate_universe(public)


simulate_universe_a = build_universe_a
simulate_universe_b = build_universe_b


def simulate_a(public, plan):
    return _module('candidate_a').simulate(public, plan)


def simulate_b(public, plan):
    return _module('ledger').simulate(public, plan)


def compare_universes(public, universe_a, universe_b):
    return _module('finance_crosscheck').compare_universes(public, universe_a, universe_b)


def compare_plans(public, universe_a, universe_b, plans, *, require_feasible=False):
    return _module('finance_crosscheck').compare_plans(public, universe_a, universe_b,
        plans, require_feasible=require_feasible)


def crosscheck(public, plans=None, *, require_feasible=False, progress=None):
    result = _module('finance_crosscheck').crosscheck(public, plans,
        require_feasible=require_feasible, progress=progress)
    # Posted financial/result schemas remain the unchanged generic v1 format.
    # This outer identity explicitly identifies the new source contract.
    return {**result, 'kind':'independent_scaled_linear_capital_financial_crosscheck', 'version':2,
        'financial_policy_changed':False, 'schema_namespace':__package__,
        'frozen_financial_implementations':dict(UPSTREAMS)}
