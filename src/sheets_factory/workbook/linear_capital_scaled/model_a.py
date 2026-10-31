"""N360 direct binary A model with unchanged financial/SCIP operators."""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

from . import spec as _spec

UPSTREAM_SHA256 = 'b8d4c354795e774fbee03bd1401cc8e426d7e238eecac24182530f463eedc907'
KIND = 'linear_capital_scaled_direct_binary_integer_model'
VERSION = 2


def upstream_path():
    local = _Path(__file__).with_name('frozen_model_a.py')
    return local if local.is_file() else _Path(__file__).resolve().parents[1]/'linear_capital_portfolio/model_a.py'


def adapted_ast():
    path = upstream_path(); raw = path.read_bytes()
    _spec.require(_hashlib.sha256(raw).hexdigest() == UPSTREAM_SHA256, 'The unchanged A model implementation differs')
    tree = _ast.parse(raw, filename=str(path)); counts = {}
    replacements = {
        "model['version'] == 1": "model['version'] == 2",
        'len(ids) in (1, 2, 3, 4, 240)': 'len(ids) in (1, 2, 3, 4, 360)',
        'len(ids) == 240': 'len(ids) == 360',
        'len(rows) == 881': 'len(rows) == 941',
        '1 <= threads <= 2': '1 <= threads <= 16',
    }
    def mark(key): counts[key] = counts.get(key, 0)+1
    class Adapt(_ast.NodeTransformer):
        def visit_Assign(self, node):
            names = [n.id for n in node.targets if isinstance(n, _ast.Name)]
            if names == ['KIND']:
                _spec.require(isinstance(node.value, _ast.Constant)
                    and node.value.value == 'linear_capital_portfolio_direct_binary_integer_model', 'The A model identity changed')
                node.value = _ast.Constant(KIND); mark('kind')
            elif names == ['PRODUCTION_COUNTS']:
                node.value = _ast.parse('dict(_SCALED_PRODUCTION_COUNTS)', mode='eval').body; mark('counts')
            return self.generic_visit(node)
        def visit_Compare(self, node):
            text = _ast.unparse(node)
            if text in replacements:
                mark(text); return _ast.parse(replacements[text], mode='eval').body
            return self.generic_visit(node)
        def visit_ImportFrom(self, node):
            if node.level == 1 and node.module is None and [a.name for a in node.names] == ['candidate_a']:
                mark('financial_import')
                return _ast.ImportFrom(module='finance', names=[_ast.alias(name='build_universe_a', asname='_scaled_forward')], level=1)
            return node
        def visit_Call(self, node):
            if _ast.unparse(node.func) == 'candidate_a.simulate_universe':
                node.func = _ast.Name(id='_scaled_forward', ctx=_ast.Load()); mark('financial_call')
            return self.generic_visit(node)
        def visit_Dict(self, node):
            keys = [n.value if isinstance(n, _ast.Constant) else None for n in node.keys]
            if all(k in keys for k in ('kind','version','project_ids','objective_pence')):
                index = keys.index('version'); _spec.require(isinstance(node.values[index], _ast.Constant)
                    and node.values[index].value == 1, 'The A canonical model version changed')
                node.values[index] = _ast.Constant(VERSION); mark('version')
            return self.generic_visit(node)
        def visit_Constant(self, node):
            if node.value == 'The complete production model requires all 881 business constraints':
                node.value = 'The complete production model requires all 941 business constraints'; mark('message')
            elif node.value == 'One or two solver threads are required':
                node.value = 'One to sixteen explicitly resource-bound solver threads are required'; mark('thread_message')
            return node
    tree = Adapt().visit(tree)
    expected = {'kind':1,'counts':1,'financial_import':1,'financial_call':1,'version':1,'message':1,'thread_message':1,
        **{key:1 for key in replacements}}
    _spec.require(counts == expected, 'The exact N360 A identity/import/dimension substitutions changed')
    return _ast.fix_missing_locations(tree)


_namespace = {'__name__':__name__+'._frozen', '__package__':__package__, '__file__':str(upstream_path()),
    '_SCALED_PRODUCTION_COUNTS':_spec.PRODUCTION_COUNTS}
exec(compile(adapted_ast(), str(upstream_path()), 'exec'), _namespace)
for _name, _value in _namespace.items():
    if not _name.startswith('__') and _name != '_SCALED_PRODUCTION_COUNTS': globals()[_name] = _value


def source_files():
    return {'model_a':_Path(__file__), 'frozen_model_a':upstream_path(),
        'spec':_Path(_spec.__file__), 'frozen_spec':_spec.upstream_path()}
