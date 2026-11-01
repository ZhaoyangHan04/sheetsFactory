"""Replay stopped historical ring observations with the correct strict inspector.

The original observer, receipts, resources, scores and model results remain
unchanged. This module does not collect observations or start containers.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
from types import FunctionType

from . import ringfenced_resource_observer as original
from . import resource_observer as base
from . import ringfenced_resource_harbor as exporter

ORIGINAL_SHA = '922a5c7ab464b0dddbf09f1d8e6ee32236526e29b68d6b512198be8c9c77e390'
BASE_SHA = 'f4c4e08cae274551ec6cfa5c31b2efcd70b7352e7d90d2f8e9ccfc67300fa456'
EXPORTER_SHA = '85bf055c9233d0d82193de0f6eb0d9adb6c6b4173bdea5cff60a128d94060733'
reference = original._namespace['_reference']
read = original._namespace['_read']
require = original._namespace['_require']


def recipes():
    for module, expected in ((original, ORIGINAL_SHA), (base, BASE_SHA), (exporter, EXPORTER_SHA)):
        require(reference(module.__file__)['sha256'] == expected, 'A frozen historical resource provider changed')
    return {'supplement_checker': reference(__file__), 'original_receipt_observer': reference(original.__file__),
        'original_base_observer': reference(base.__file__), 'strict_ring_export_inspector': reference(exporter.__file__),
        'method': 'read-only stopped-receipt replay; exactly one internal inspector import correction'}


recipes()
_namespace = dict(original._namespace)
for _name, _function in original._namespace.items():
    if isinstance(_function, FunctionType) and _function.__globals__ is original._namespace:
        _clone = FunctionType(_function.__code__, _namespace, _name, _function.__defaults__, _function.__closure__)
        _clone.__kwdefaults__ = _function.__kwdefaults__; _namespace[_name] = _clone
require(_namespace['__file__'] == original.__file__, 'Preserve the original stopped observer implementation identity')
_tree = ast.parse(Path(base.__file__).read_text())
_function = next(node for node in _tree.body if isinstance(node, ast.FunctionDef) and node.name == 'validate_trial_observations')
_imports = [node for node in ast.walk(_function) if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module == 'resource_harbor']
require(len(_imports) == 1 and [(a.name, a.asname) for a in _imports[0].names] == [('inspect_resource_export', None)],
    'The exact historical internal inspector seam changed')
_imports[0].module = 'ringfenced_resource_harbor'
exec(compile(ast.fix_missing_locations(ast.Module(body=[_function], type_ignores=[])), original.__file__, 'exec'), _namespace)
def validate_trial_observations(*args, **kwargs):
    recipe = recipes(); result = _namespace['validate_trial_observations'](*args, **kwargs)
    require(recipes() == recipe, 'The supplemental validation recipe changed')
    return result


def validate_observation_receipt(*args, **kwargs):
    recipe = recipes(); result = _namespace['validate_observation_receipt'](*args, **kwargs)
    require(recipes() == recipe, 'The supplemental observation recipe changed')
    return result


def supplement_trial(trial_config, result, *, receipts, expected_profile=None, expected_task_directory=None):
    """Return separate original and supplemental checks of the same evidence."""
    recipe = recipes()
    config_ref = reference(trial_config) if isinstance(trial_config, (str, Path)) else trial_config
    result_ref = reference(result) if isinstance(result, (str, Path)) else result
    receipt_refs = [reference(r) if isinstance(r, (str, Path)) else r for r in receipts]
    kwargs = {'receipts': receipt_refs, 'expected_profile': expected_profile, 'expected_task_directory': expected_task_directory}
    before = original._namespace['validate_trial_observations'](config_ref, result_ref, **kwargs)
    after = validate_trial_observations(config_ref, result_ref, **kwargs)
    for record in [config_ref, result_ref, *receipt_refs]:
        require(reference(record['path']) == record, 'Historical resource evidence changed during replay')
    require(recipes() == recipe, 'The supplemental checker recipe changed during replay')
    return {'kind': 'readonly_historical_ringfenced_resource_supplement', 'version': 1,
        'trial_config': config_ref, 'result': result_ref, 'observation_receipts': receipt_refs,
        'original_validation': deepcopy(before), 'supplemental_validation': deepcopy(after), 'recipe': recipe,
        'original_observer_implementation': recipe['original_receipt_observer'],
        'original_results_or_receipts_or_scores_modified': False, 'new_observer_or_container_calls': 0,
        'missing_evidence_is_not_a_model_failure': True}
