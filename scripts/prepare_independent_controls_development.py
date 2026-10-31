#!/usr/bin/env python3
"""Freeze a genuine independent-controls pair; execute each first trial explicitly.

The immutable period entry supplies the already-tested export, clock, history,
reservation and resource lifecycle in a private namespace. Only family schema,
instruction binding and recipe identity change here. No period admission runs.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.workbook import independent_controls_candidate as synthetic

UPSTREAM = ROOT / 'scripts/prepare_period_boundary_development.py'
UPSTREAM_SHA256 = '44d87bf6fb55fde4a1b29a444ad32d472b7ebe3d7ba8379ce2395bdbf9301c2d'
VALIDATOR = ROOT / 'scripts/validate_independent_controls_candidate.py'
VALIDATOR_SHA = '10a281ec140d5c8fab5f2098009fb9d9db21f6653447cae6f3ad0df21b058538'
KIND = 'prequality_synthetic_independent_controls_development_pair'
TERMINAL_KIND = 'prequality_independent_controls_native_first_attempt_terminal'
MODES = ('financial_modeling', 'debugging')
MODE_KEYS = {'financial_modeling': 'FM', 'debugging': 'DBG'}
EXPECTED_D = {'financial_modeling': 546, 'debugging': 203}
CONTROL_REWARDS = {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}


def _require(value, message):
    if not value: raise ValueError(message)


def _ref(path):
    path = Path(path).absolute()
    _require(path == path.resolve() and path.is_file(), 'Use a real nonsymlink file')
    data = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def _read(value):
    if isinstance(value, dict):
        _require(_ref(value['path']) == value, 'Frozen independent-controls evidence changed')
        value = value['path']
    return json.loads(Path(value).read_text())


def validation_driver():
    _require(_ref(VALIDATOR)['sha256'] == VALIDATOR_SHA, 'The frozen genuine independent-controls validator changed')
    spec = importlib.util.spec_from_file_location('_independent_controls_completed_engineering', VALIDATOR)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def _checked_engineering(value):
    actual = validation_driver().validate_completed(value)
    _require(actual.get('kind') == 'independent_controls_actual_shared_engineering_validation' and actual.get('version') == 1
        and actual.get('passed') is True and actual.get('actual_LO_calls_started') == actual.get('actual_LO_calls_completed') == 10
        and actual.get('qualified') is False, 'Only the genuine independent-controls ten-call terminal is admitted')
    prepared = _read(actual['preparation']); candidate = _read(prepared['candidate_manifest'])
    _require(candidate.get('kind') == 'prepared_independent_controls_financial_candidate_pair' and candidate.get('version') == 1
        and candidate.get('dimensions', {}).get('financial_output_targets') == 546
        and prepared.get('expected_FM_D') == 546 and prepared.get('expected_DBG_D') == 203
        and candidate.get('qualified') is False and candidate.get('actual_LO_model_solver_Harbor_network_calls') == 0,
        'The genuine 546-target /203-change synthetic candidate identity is required')
    _require(set(actual['records']['modes']) == set(MODES), 'Both completed genuine modes are required')
    outputs = {call['role']: call['output'] for call in actual['actual_calls']}
    _require(set(outputs) == set(validation_driver().STAGES), 'The ten genuine stage outputs are required')
    for mode in MODES:
        material = actual['records']['modes'][mode]
        _require(material['complete_D_count'] == EXPECTED_D[mode] and material['controls'] == CONTROL_REWARDS
            and material['input'] == outputs[MODE_KEYS[mode] + '_input2'] and material['goal'] == outputs['goal2'],
            'Use the stable actual input/goal and complete full-D controls of this family')
    return actual, candidate


def _instruction(candidate, mode):
    public = synthetic.validate(_read(candidate['public_assumptions']))
    material = candidate['materials'][MODE_KEYS[mode]]
    _require(material.get('kind') == 'uncalculated_independent_controls_candidate_view' and material.get('version') == 1
        and material.get('mode') == MODE_KEYS[mode] and material.get('qualified') is False, 'The original genuine mode instruction must remain bound')
    source = material['public_instruction']
    _require(_ref(source['path']) == source, 'The original prototype public request changed')
    original = Path(source['path']).read_bytes()
    _require(original == synthetic.public_brief(public, MODE_KEYS[mode]).encode(), 'Preserve the original concise business request exactly')
    appendix = b'\n---\nFile paths: read /app/input.xlsx and save the completed workbook to /app/output.xlsx.\n'
    return original, original + appendix


def _namespace():
    source = UPSTREAM.read_bytes()
    _require(hashlib.sha256(source).hexdigest() == UPSTREAM_SHA256, 'The frozen development lifecycle changed')
    replacements = {
        'synthetic_period_boundary_financial_portfolio': ('synthetic_independent_controls_financial_candidate', 2),
        'synthetic_period_boundary_prequality_development_source': ('independent_controls_prequality_development_source', 2),
        'period-boundary-': ('independent-controls-', 1),
        'period_boundary_permanent_material_first_attempt_reservation': ('independent_controls_permanent_material_first_attempt_reservation', 1),
        'prequality_period_boundary_native_first_attempt_terminal': (TERMINAL_KIND, 1),
    }
    counts = {key: 0 for key in replacements}
    edits = {'removed_domain_import': 0, 'removed_domain_functions': 0, 'removed_domain_constants': 0,
             'public_assumptions_binding': 0, 'original_mode_instruction_binding': 0}
    class Family(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module == 'sheets_factory.workbook.period_boundary_portfolio.spec':
                _require([a.name for a in node.names] == ['BRIEFS'], 'Unexpected old domain import')
                edits['removed_domain_import'] += 1; return None
            return node
        def visit_FunctionDef(self, node):
            if node.name in {'validation_driver', '_checked_engineering', '_instruction'}:
                edits['removed_domain_functions'] += 1; return None
            return self.generic_visit(node)
        def visit_Assign(self, node):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in {'KIND', 'VALIDATOR', 'VALIDATOR_SHA'}:
                edits['removed_domain_constants'] += 1; return None
            return self.generic_visit(node)
        def visit_Constant(self, node):
            if isinstance(node.value, str) and node.value in replacements:
                counts[node.value] += 1
                return ast.copy_location(ast.Constant(replacements[node.value][0]), node)
            return node
        def visit_Subscript(self, node):
            if (isinstance(node.value, ast.Subscript) and isinstance(node.value.value, ast.Name)
                and node.value.value.id == 'candidate' and isinstance(node.value.slice, ast.Constant)
                and node.value.slice.value == 'instructions' and isinstance(node.slice, ast.Name) and node.slice.id == 'mode'):
                edits['original_mode_instruction_binding'] += 1
                return ast.copy_location(ast.parse("candidate['materials'][MODE_KEYS[mode]]['public_instruction']", mode='eval').body, node)
            if isinstance(node.value, ast.Name) and node.value.id == 'candidate' and isinstance(node.slice, ast.Constant) and node.slice.value == 'source_specification':
                edits['public_assumptions_binding'] += 1
                return ast.copy_location(ast.parse("candidate['public_assumptions']", mode='eval').body, node)
            return self.generic_visit(node)
    tree = Family().visit(ast.parse(source, filename=str(UPSTREAM)))
    _require(counts == {key: value[1] for key, value in replacements.items()}
        and edits == {'removed_domain_import': 1, 'removed_domain_functions': 3, 'removed_domain_constants': 3,
                      'public_assumptions_binding': 2, 'original_mode_instruction_binding': 1}, 'Unexpected frozen lifecycle structure; no broad fallback')
    namespace = {'__name__': '_isolated_independent_controls_development', '__file__': str(Path(__file__).resolve()),
        'KIND': KIND, 'MODE_KEYS': MODE_KEYS, 'validation_driver': validation_driver,
        '_checked_engineering': _checked_engineering, '_instruction': _instruction}
    exec(compile(ast.fix_missing_locations(tree), str(UPSTREAM), 'exec'), namespace)
    original_recipes = namespace['recipes']
    def bound_recipes():
        _require(_ref(UPSTREAM)['sha256'] == UPSTREAM_SHA256, 'The frozen development lifecycle changed')
        result = original_recipes()
        for path in (UPSTREAM, ROOT / 'tests/test_independent_controls_development.py'):
            result[str(path.resolve())] = _ref(path)
        return result
    namespace['recipes'] = bound_recipes
    namespace['family_adapter_proof'] = {'constant_replacements': counts, 'schema_rebindings': edits}
    return namespace


_PRIVATE = _namespace()
for _name in ('prepare', 'validate_prepared', 'reserve', 'effective_score', 'run_development', 'main',
              'ref', 'checked', 'read', 'write', 'recipes', 'history_helper', 'content_identity', 'canonical'):
    globals()[_name] = _PRIVATE[_name]
BUDGET = _PRIVATE['BUDGET']
PROFILE = _PRIVATE['PROFILE']

if __name__ == '__main__': raise SystemExit(main())
