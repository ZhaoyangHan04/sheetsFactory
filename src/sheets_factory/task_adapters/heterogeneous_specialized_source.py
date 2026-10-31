"""Cold admission of a newly audited policy-specialized source.

The complete existing source-admission implementation is executed in a private
namespace. Only its source-builder path and admitted manifest kind differ; all
three audit chains, current recipes, resources and typed-stability checks stay.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

_TEMPLATE = Path(__file__).resolve().with_name('heterogeneous_financial_view.py')
_TEMPLATE_SHA256 = '1cef92418a75fe5b408c5e225e3506e2b0bb5670814753c46f1bce323c8b88b3'


def admission_ast():
    raw = _TEMPLATE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != _TEMPLATE_SHA256:
        raise ValueError('The frozen complete source-admission implementation changed')
    tree = ast.parse(raw, filename=str(_TEMPLATE))
    changed = set()
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        name = node.targets[0].id
        if name == 'SOURCE_KIND':
            if not isinstance(node.value, ast.Constant) or node.value.value != 'independently_verified_heterogeneous_contract_source':
                raise ValueError('The frozen admission kind differs')
            node.value.value = 'independently_verified_policy_specialized_heterogeneous_contract_source'
            changed.add(name)
        if name == 'SOURCE_BUILDER':
            expected = ast.parse("SOURCE_BUILDER = ROOT / 'scripts/build_heterogeneous_source.py'").body[0]
            if ast.dump(node, include_attributes=False) != ast.dump(expected, include_attributes=False):
                raise ValueError('The frozen source-builder path differs')
            node.value = ast.parse("ROOT / 'scripts/build_specialized_heterogeneous_source.py'", mode='eval').body
            changed.add(name)
    if changed != {'SOURCE_KIND', 'SOURCE_BUILDER'}:
        raise ValueError('Both bounded source-admission substitutions are required')
    return ast.fix_missing_locations(tree)


def _admission():
    namespace = {'__name__': __package__ + '._specialized_admission',
        '__package__': __package__, '__file__': str(_TEMPLATE)}
    exec(compile(admission_ast(), str(_TEMPLATE), 'exec'), namespace)
    return namespace


def load_source(value):
    """Return complete cold-checked source, primitives, graph and audit journal.

    This performs file/hash verification only, with no financial forward,
    optimization, workbook materialization, calculation engine or model call.
    """
    namespace = _admission()
    result = namespace['_load_source'](value)
    proof = result[0]
    proof['specialized_admission_implementation'] = namespace['reference'](__file__)
    proof['unmodified_admission_template'] = namespace['reference'](_TEMPLATE)
    return result


def validate_source(value):
    return load_source(value)[0]
