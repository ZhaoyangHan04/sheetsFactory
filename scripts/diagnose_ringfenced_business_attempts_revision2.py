#!/usr/bin/env python3
"""Append historical resource evidence without changing the original R2 result."""
from __future__ import annotations

from copy import deepcopy
import ast
import hashlib
import importlib.util
import inspect
from pathlib import Path
from types import FunctionType

_ROOT = Path(__file__).resolve().parents[1]
_BASE = _ROOT/'scripts/diagnose_ringfenced_business_attempts.py'
_BASE_SHA = 'd3f18a86ba04af8e8e8abc48ee25a71bc76dd58aa65d4cdb89a175a7c09c21da'
if hashlib.sha256(_BASE.read_bytes()).hexdigest() != _BASE_SHA:
    raise ValueError('The original frozen saved-output diagnostic changed')
_loader = importlib.util.spec_from_file_location('_original_R2_saved_output_diagnostic', _BASE)
_original = importlib.util.module_from_spec(_loader); _loader.loader.exec_module(_original)
for _name, _value in vars(_original).items():
    if not _name.startswith('__'): globals()[_name] = _value
for _name, _value in vars(_original).items():
    if isinstance(_value, FunctionType) and _value.__globals__ is vars(_original):
        _clone = FunctionType(_value.__code__, globals(), _name, _value.__defaults__, _value.__closure__)
        _clone.__kwdefaults__ = _value.__kwdefaults__; globals()[_name] = _clone

from sheets_factory.evaluation import ringfenced_observation_supplement as supplement
SUPPLEMENT_SHA = 'f7b8557e7829afc990d768dda4b4314b951bbb91a0d5236529dd7702fea4c219'
validate_trial_observations = supplement.validate_trial_observations
_original_recipes = recipes
_original_admit = _admit
_original_write = write


def recipes():
    require(reference(_BASE)['sha256'] == _BASE_SHA and reference(supplement.__file__)['sha256'] == SUPPLEMENT_SHA,
        'The frozen resource-only diagnosis revision changed')
    return [*_original_recipes(), reference(_BASE), reference(supplement.__file__), *[
        value for value in supplement.recipes().values() if isinstance(value, dict)]]


def _admit(batch_ref, terminal_ref):
    batch, terminal, original_rows, selected, resources, context = _original_admit(batch_ref, terminal_ref)
    rows = deepcopy(original_rows); context = dict(context); supplemental = {}
    for identity, row in rows.items():
        attempt = row['actual_attempt']; result_path = attempt.get('result_file')
        if not result_path or attempt.get('status') != 'scored': continue
        result_ref = reference(result_path)
        require(result_ref['sha256'] == attempt['result_sha256'], 'The original actual result changed')
        proof = supplement.supplement_trial(Path(result_path).with_name('config.json'), result_ref,
            receipts=resources['observation_receipts'], expected_task_directory=selected[identity]['task_directory'])
        supplemental[identity] = {'original_resources': deepcopy(row['resources']), 'supplement': proof}
        row['resources'] = deepcopy(proof['supplemental_validation'])
    context['historical_resource_supplements'] = supplemental
    # No score, raw reward, timing, source, input, goal or original manifest is
    # projected. The extra proof only controls access to economic diagnosis.
    return batch, terminal, rows, selected, resources, context


def write(path, value):
    if Path(path).name == 'economic_evidence.json':
        value = {**value, 'resource_validation_method': 'append-only stopped historical observer supplement',
            'original_v6_resource_unknown_not_regraded': True}
    if Path(path).name == 'terminal.json':
        value = {**value, 'supplemental_diagnosis_revision': 2,
            'original_native_terminal_and_resources_and_score_unchanged': True}
    return _original_write(path, value)


_tree = ast.parse(inspect.getsource(_original.run)); _function = _tree.body[0]
_inserted = 0
for _node in ast.walk(_function):
    if not isinstance(_node, ast.For): continue
    for _index, _item in enumerate(tuple(_node.body)):
        if isinstance(_item, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'evidence' for target in _item.targets):
            _node.body.insert(_index+1, ast.parse("evidence['historical_resource_supplement'] = context['historical_resource_supplements'].get(identity)").body[0])
            _inserted += 1
require(_inserted == 1, 'The original economic-evidence annotation seam changed')
exec(compile(ast.fix_missing_locations(_tree), __file__, 'exec'), globals())


if __name__ == '__main__': main()
