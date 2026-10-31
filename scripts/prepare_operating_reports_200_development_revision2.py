#!/usr/bin/env python3
"""First fixed200 v6 pair after explicit task-fault revision2 admission."""
from __future__ import annotations
import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parents[1]
_FROZEN_DEV = _ROOT/'scripts/prepare_operating_reports_200_development.py'
_FROZEN_SHA = 'd6cd3b7aebedfb7aebe632217585951838eb28e0fe38d03fab4277fe47f0e6f3'
_NEW_VALIDATOR_SHA = '9b09e434e0cbe0dfbb7b97d825bb8b457167558fc8f72be50234a2a9010763ee'

def _revision_ast():
    validator = _ROOT/'scripts/validate_operating_reports_200_tasks_revision2.py'
    if len(_NEW_VALIDATOR_SHA) != 64 or _hashlib.sha256(validator.read_bytes()).hexdigest() != _NEW_VALIDATOR_SHA:
        raise ValueError('The exact admitted task-fault revision2 validator changed')
    data = _FROZEN_DEV.read_bytes()
    if _hashlib.sha256(data).hexdigest() != _FROZEN_SHA:
        raise ValueError('The original fixed200 v6 first-attempt lifecycle changed')
    replacements = {
        'scripts/validate_operating_reports_200_tasks.py': 'scripts/validate_operating_reports_200_tasks_revision2.py',
        'b4d8376ec90df5d145f9f10889cfbaac393a12d0c94ac8bbccd1a19d8a72cae5': _NEW_VALIDATOR_SHA,
        'complete_fixed_operating_reports_200_task_engineering': 'complete_fixed_operating_reports_200_task_engineering_revision2',
        'prepared_fixed_operating_reports_200_task_engineering': 'prepared_fixed_operating_reports_200_task_engineering_revision2',
        'prequality_fixed_operating_reports_200_development_pair_v6': 'prequality_fixed_operating_reports_200_development_pair_v6_revision2',
    }
    counts = {key:0 for key in replacements}; counts['main'] = 0
    class Adapt(_ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value) is str and node.value in replacements:
                counts[node.value] += 1; node.value = replacements[node.value]
            return node
        def visit_If(self,node):
            if _ast.unparse(node.test) == "__name__ == '__main__'":
                counts['main'] += 1; return None
            return self.generic_visit(node)
    tree = Adapt().visit(_ast.parse(data))
    if any(value != 1 for value in counts.values()):
        raise ValueError('The exact fixed200 development revision2 binding changed: '+str(counts))
    return _ast.fix_missing_locations(tree)

_ns = {'__name__':'_isolated_fixed200_development_revision2','__file__':__file__}
exec(compile(_revision_ast(),__file__,'exec'),_ns)
_original_recipes = _ns['recipes']

def recipes():
    return {**_original_recipes(),str(_FROZEN_DEV):_ns['ref'](_FROZEN_DEV)}

_ns['recipes'] = recipes
for _name,_value in _ns.items():
    if not _name.startswith('__'): globals().setdefault(_name,_value)

if __name__ == '__main__': raise SystemExit(main())
