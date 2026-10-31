"""N360 capacity-first B model; unchanged Decimal and CP-SAT operators."""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path
from collections import Counter as _Counter

from . import spec as _spec

UPSTREAM_SHA256 = '972e640060ba14d545e20907014a892be76c83675c9d00a354ee7098f693e6c4'
MODEL_KIND = 'linear_capital_scaled_direct_binary_integer_model'
VERSION = 2


def upstream_path():
    local = _Path(__file__).with_name('frozen_model_b.py')
    return local if local.is_file() else _Path(__file__).resolve().parents[1]/'linear_capital_portfolio/model_b.py'


def adapted_ast():
    path = upstream_path(); raw = path.read_bytes()
    _spec.require(_hashlib.sha256(raw).hexdigest() == UPSTREAM_SHA256, 'The unchanged B model implementation differs')
    tree = _ast.parse(raw, filename=str(path)); counts = {}
    replacements = {"model['version'] == 1":"model['version'] == 2",
        '1 <= len(ids) <= 240':'len(ids) in (1, 2, 3, 4, 360)', 'expected == 881':'expected == 941',
        '1 <= threads <= 2':'1 <= threads <= 16'}
    def mark(key): counts[key] = counts.get(key, 0)+1
    class Adapt(_ast.NodeTransformer):
        def visit_Assign(self, node):
            if any(isinstance(n, _ast.Name) and n.id == 'MODEL_KIND' for n in node.targets):
                _spec.require(isinstance(node.value, _ast.Constant)
                    and node.value.value == 'linear_capital_portfolio_direct_binary_integer_model', 'The B model identity changed')
                node.value = _ast.Constant(MODEL_KIND); mark('kind')
            return self.generic_visit(node)
        def visit_Compare(self, node):
            text = _ast.unparse(node)
            if text in replacements:
                mark(text); return _ast.parse(replacements[text], mode='eval').body
            return self.generic_visit(node)
        def visit_ImportFrom(self, node):
            if node.level == 1 and node.module is None and [a.name for a in node.names] == ['ledger']:
                mark('financial_import'); return None
            return node
        def visit_FunctionDef(self, node):
            node = self.generic_visit(node)
            if node.name == 'build_model':
                node.body.insert(1, _ast.ImportFrom(module='finance',
                    names=[_ast.alias(name='build_universe_b', asname='_scaled_forward')], level=1))
                mark('lazy_financial_import')
            if node.name == 'validate_model':
                _spec.require(isinstance(node.body[-1], _ast.Return)
                    and _ast.unparse(node.body[-1].value) == 'deepcopy(model)', 'The B complete validator return changed')
                # A source may not omit a row after compilation. This is only a
                # complete schema census; all integer financial/solver math is unchanged.
                node.body[-1:-1] = _ast.parse("if len(ids) == 360:\n    require(len(model['rows']) == 941 and _SCALED_COUNTER(r['family'] for r in model['rows']) == _SCALED_PRODUCTION_COUNTS, 'The complete N360 model requires all 941 business rows')").body
                mark('complete_production_census')
            return node
        def visit_Call(self, node):
            if _ast.unparse(node.func) == 'ledger.simulate_universe':
                node.func = _ast.Name(id='_scaled_forward', ctx=_ast.Load()); mark('financial_call')
            return self.generic_visit(node)
        def visit_Dict(self, node):
            keys = [n.value if isinstance(n, _ast.Constant) else None for n in node.keys]
            if all(k in keys for k in ('kind','version','project_ids','objective_pence')):
                index = keys.index('version'); _spec.require(isinstance(node.values[index], _ast.Constant)
                    and node.values[index].value == 1, 'The B canonical model version changed')
                node.values[index] = _ast.Constant(VERSION); mark('version')
            return self.generic_visit(node)
        def visit_Constant(self, node):
            if node.value == 'The reference uses at most the declared two CPU workers':
                node.value = 'The reference uses at most sixteen explicitly resource-bound CPU workers'; mark('thread_message')
            return node
    tree = Adapt().visit(tree)
    expected = {'kind':1,'financial_import':1,'lazy_financial_import':1,'financial_call':1,
        'complete_production_census':1,'version':1,'thread_message':1, **{key:1 for key in replacements}}
    _spec.require(counts == expected, 'The exact N360 B identity/import/dimension substitutions changed')
    return _ast.fix_missing_locations(tree)


_namespace = {'__name__':__name__+'._frozen', '__package__':__package__, '__file__':str(upstream_path()),
    '_SCALED_COUNTER':_Counter, '_SCALED_PRODUCTION_COUNTS':_spec.PRODUCTION_COUNTS}
exec(compile(adapted_ast(), str(upstream_path()), 'exec'), _namespace)
for _name, _value in _namespace.items():
    if not _name.startswith('__') and _name not in ('_SCALED_COUNTER','_SCALED_PRODUCTION_COUNTS'): globals()[_name] = _value


def source_files():
    return {'model_b':_Path(__file__), 'frozen_model_b':upstream_path(),
        'spec':_Path(_spec.__file__), 'frozen_spec':_spec.upstream_path()}
