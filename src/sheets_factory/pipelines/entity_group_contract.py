"""Explicit complete-scope contract for the opt-in entity-group family.

The physical edit ceiling remains the existing 200,000. Only complete profile
and dependency-closure capacity expand under the SHA-bound large profile.
The target validator below is an exact static copy of the original validator.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import inspect
import hashlib
import json
from pathlib import Path
import time as clock
import math
import re
import textwrap

import openpyxl
import yaml

from ..nodes import construction as normal
from ..core.node import TaskRejected
from ..task_adapters.public_workbook_scope import checked_bytes, require
from ..workbook import formula_references
from ..workbook.static_references import static_formula_text, StaticReferenceError
from ..checkers.native_error_dependencies import validate_static_reference_syntax, dependency_error_reach
from ..checkers import native_error_probe as original_native_probe
from ..checkers.native_error_probe import _digest, _json_digest, _required_values, _full_closure_candidates
from ..workbook.resource_engine import load_runtime_profile

SETTING = 'entity_group_task'
METHOD = 'full_workbook_joint_repair'


def construction_contract(mode=None, config=None):
    config = config or {}
    value = config.get(SETTING)
    if value is None:
        return normal.construction_contract(mode, config)
    require(isinstance(value, dict) and value.get('enabled') is True
            and type(value.get('version')) is int and value['version'] == 1,
            'The explicit entity family contract is required')
    profile = load_runtime_profile(yaml.safe_load(checked_bytes(value['runtime_profile'])))
    limits = config.get('construction', {}).get('analysis_limits', {})
    expected = {'max_profile_cells': profile['limits']['max_profile_cells'],
                'max_dependency_closure_cells': profile['limits']['max_dependency_closure_cells']}
    require(all(type(limits.get(key)) is int and limits[key] == cap for key, cap in expected.items()),
            'The entity family requires complete explicit three-million-cell analysis without truncation')
    base = deepcopy(config)
    for key in expected:
        base['construction']['analysis_limits'].pop(key)
    result = normal.construction_contract(mode, base)
    result['version'] = 3
    result['resource_profile_id'] = profile['id']
    result['source_requirements']['max_profile_cells'] = expected['max_profile_cells']
    result['dependency_requirements']['max_dependency_closure_cells'] = expected['max_dependency_closure_cells']
    result['modes']['debugging']['each_root_requires_individual_and_combined_marginal_impact'] = False
    result['modes']['debugging']['activity_contract'] = METHOD
    result['reference_scope']['all_nonroot_changed_values_still_required'] = True
    return result


def validate_upstream_validator():
    before = ast.parse(textwrap.dedent(inspect.getsource(normal.validate_plan)))
    after = ast.parse(textwrap.dedent(inspect.getsource(validate_plan)))
    require(ast.dump(before) == ast.dump(after),
            'The entity target validator must retain every original rule and gate')
    before = ast.parse(textwrap.dedent(inspect.getsource(original_native_probe.probe_native_errors)))
    after = ast.parse(textwrap.dedent(inspect.getsource(probe_native_errors)))
    class ClosureBound(ast.NodeTransformer):
        count = 0
        def visit_Constant(self, node):
            if type(node.value) is int and node.value == 500000:
                self.count += 1
                return ast.copy_location(ast.Constant(value=3000000), node)
            return node
    substitution = ClosureBound(); before = substitution.visit(before)
    require(substitution.count == 1 and ast.dump(before) == ast.dump(after),
            'The entity native-error probe may change only its explicit complete-closure ceiling')


def validate_plan(plan, baseline, mode, config=None):
    edits = plan.get('edits', [])
    contract = construction_contract(mode, config)
    bounds = contract['modes'][mode]['edit_count']
    if len(edits) < bounds['min'] or len(edits) > bounds['max']:
        raise TaskRejected('Q06: target group size outside supported construction contract '
                           f'(mode={mode}, actual={len(edits)}, min={bounds["min"]}, max={bounds["max"]})')
    if not plan.get('public_instruction') or not plan.get('public_rules') or not plan.get('reference_evidence'):
        raise TaskRejected('Q01/Q04: missing public derivation rules or reference evidence')
    book = openpyxl.load_workbook(baseline, data_only=False, keep_links=False)
    values = openpyxl.load_workbook(baseline, data_only=True, keep_links=False)
    seen, involved, visited, cross_edges = set(), set(), set(), set()
    native_errors = {}
    meaningful_targets = 0
    reference_cache = {}
    expansion = contract['dependency_requirements']['per_formula_reference_cells']

    def resolved_dependencies(sheet_name, address, source_cell):
        try:
            formula_text = static_formula_text(source_cell)
        except StaticReferenceError as exc:
            raise TaskRejected(f'Q10: unresolved dependency at {sheet_name}!{address}: {exc}') from exc
        if re.search(r'\b(?:NOW|TODAY|RAND|RANDBETWEEN)\s*\(', formula_text, re.I):
            raise TaskRejected('Q10: unsupported or volatile formula in target dependency closure')
        dependencies = formula_references(formula_text, sheet_name, max_expansion=expansion,
            workbook=book, cache=reference_cache, include_resolved_formula=True)
        if (not dependencies['fully_supported']
                or validate_static_reference_syntax(dependencies['resolved_formula'])):
            raise TaskRejected(f'Q10: unresolved target dependency closure at {sheet_name}!{address}')
        return dependencies

    def inspect_dependencies(sheet_name, address):
        pending = [(sheet_name, address)]
        while pending:
            key = pending.pop()
            if key in visited:
                continue
            visited.add(key)
            if len(visited) > contract['dependency_requirements']['max_dependency_closure_cells']:
                raise TaskRejected('Target dependency closure exceeds supported analysis scope')
            current_sheet, current_address = key
            if current_sheet not in book.sheetnames:
                raise TaskRejected('Q10: target dependency references a missing sheet')
            source_cell = book[current_sheet][current_address]
            if values[current_sheet][current_address].data_type == 'e':
                native_errors[key] = {'sheet': current_sheet, 'cell': current_address,
                    'cached_error': values[current_sheet][current_address].value,
                    'formula': source_cell.value if source_cell.data_type == 'f' else None}
            if source_cell.data_type != 'f':
                continue
            dependencies = resolved_dependencies(current_sheet, current_address, source_cell)
            for reference in dependencies['references']:
                involved.add(reference['sheet'])
                if reference['sheet'] != current_sheet:
                    cross_edges.add((current_sheet, current_address, reference['sheet'], reference['cell']))
                target = (reference['sheet'], reference['cell'])
                if target not in visited:
                    pending.append(target)
    try:
        for edit in edits:
            key = (edit['sheet'], edit['cell'])
            if key in seen or key[0] not in book.sheetnames:
                raise TaskRejected('Q06: duplicate or nonexistent edit')
            seen.add(key)
            cell = book[key[0]][key[1]]
            if cell.data_type != 'f' or not isinstance(cell.value, str) or cell.value != edit['before']:
                raise TaskRejected('Q06: before assertion does not match actual original formula at ' + str(key))
            refs = resolved_dependencies(key[0], key[1], cell)
            value = values[key[0]][key[1]]
            if value.data_type == 'e' or value.value is None:
                raise TaskRejected('Q04: target has no valid recalculated reference value')
            if isinstance(value.value, float) and not math.isfinite(value.value):
                raise TaskRejected('Q04: nonfinite target value')
            if isinstance(value.value, (int, float)) and not isinstance(value.value, bool) and abs(value.value) > .005:
                meaningful_targets += 1
            inspect_dependencies(key[0], key[1])
            involved.add(key[0])
            for ref in refs['references']:
                involved.add(ref['sheet'])
                if ref['sheet'] not in values.sheetnames:
                    raise TaskRejected('Q10: direct input references a missing sheet')
            if mode == 'financial_modeling' and edit.get('after') is not None:
                raise TaskRejected('Modeling mask may only clear approved formulas')
            if mode == 'debugging' and (not isinstance(edit.get('after'), str) or not edit['after'].startswith('=') or edit['after'] == edit['before']):
                raise TaskRejected('Debugging requires an actual formula mutation')
        if len(involved) < 2 or not cross_edges:
            raise TaskRejected('Task does not involve a real cross-sheet calculation')
        if not meaningful_targets:
            raise TaskRejected('All targets are zero or nonnumeric; an explicit populated scenario is required')
    finally:
        book.close(); values.close()
    return {'edit_count': len(edits), 'dependency_sheets': sorted(involved), 'before_assertions_passed': True,
            'dependency_closure_cells': len(visited), 'cross_sheet_edges': sorted(cross_edges),
            'meaningful_nonzero_targets': meaningful_targets,
            'native_error_candidates': [native_errors[key] for key in sorted(native_errors)],
            'native_error_candidates_provisional': bool(native_errors),
            'native_error_policy': 'all paths require narrow certificates; actual full-D LO sensitivity probes are additional evidence, not business correctness'}


def probe_native_errors(*, goal, required_delta, candidates, engine, directory,
                        source_sha256, plan, revision, immutable_files=None,
                        engine_metadata=None, max_candidates=64, max_dependency_cells=20000,
                        per_formula_reference_cells=5000):
    """Return a persisted, blocking-by-default receipt; never certify business logic."""
    goal, directory = Path(goal), Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    labels = sorted(set(required_delta))
    files = dict(immutable_files or {})
    files['goal'] = goal
    before = {name: {'path': str(Path(path).resolve()), 'sha256': _digest(path)}
              for name, path in files.items()}
    receipt = {'version': 1, 'classification': 'current_scenario_sensitivity_evidence',
        'business_correctness_certificate': False, 'requires_Q04_Q09_review': True,
        'state': 'unknown', 'blocking': True, 'problem_id': 'Q09', 'route_id': 'R09',
        'certainty': 'suspected', 'revision': revision, 'source_sha256': source_sha256,
        'goal_sha256': before['goal']['sha256'], 'plan_sha256': _json_digest(plan),
        'required_delta': labels, 'required_delta_sha256': _json_digest(labels),
        'immutable_before': before, 'engine': engine_metadata or {'backend': type(engine).__name__},
        'candidates': [], 'probes': []}
    receipt['analysis_limits'] = {'max_dependency_closure_cells': max_dependency_cells,
                                  'per_formula_reference_cells': per_formula_reference_cells}
    started = clock.monotonic()
    try:
        if type(max_dependency_cells) is not int or not 1 <= max_dependency_cells <= 3000000:
            raise ValueError('Invalid native-probe dependency closure bound')
        if type(per_formula_reference_cells) is not int or not 1 <= per_formula_reference_cells <= 50000:
            raise ValueError('Invalid native-probe per-formula reference bound')
        if not labels:
            raise ValueError('complete required-D set is empty')
        expected, sheets = _required_values(goal, labels)
        receipt['required_typed_values_sha256'] = _json_digest(expected)
        errors = [label for label, value in expected.items() if value[0] == 'error']
        if errors:
            receipt.update(state='observed_contamination', certainty='confirmed', problem_id='Q04',
                route_id='R04', reason='Actual goal errors occur in complete required D', goal_error_cells=errors)
            return receipt
        if 'source' in before and before['source']['sha256'] != source_sha256:
            raise ValueError('bound source SHA differs from actual immutable source')
        candidates, count = _full_closure_candidates(goal, labels, candidates, max_dependency_cells,
                                                    per_formula_reference_cells)
        receipt.update(candidates=candidates, full_dependency_closure_cells=count)
        if not candidates:
            receipt.update(state='not_applicable', blocking=False,
                reason='No cached native errors in the complete required-D dependency closure')
            return receipt
        if len(candidates) > max_candidates:
            raise ValueError('native-error candidate probe limit exceeded')
        reach = dependency_error_reach(goal, labels, candidates, max_cells=max_dependency_cells,
                                       per_formula_reference_cells=per_formula_reference_cells)
        receipt['dependency_certificates'] = reach
        remaining = {label: errors for label, errors in reach['per_delta_errors'].items() if errors}
        receipt['uncertified_paths'] = remaining
        # Different finite, coordinate-bound weights prevent the equal-sentinel
        # cancellation that can hide mutually masked errors in a joint probe.
        weights = {}
        for index, candidate in enumerate(candidates):
            label = candidate['sheet'] + '!' + candidate['cell']
            weights[label] = (index + 1) * 1000000 + int(hashlib.sha256(label.encode()).hexdigest()[:8], 16) % 900000 + .125
        assignments = []
        for label, value in weights.items():
            assignments.extend([('single', {label: value}), ('single', {label: -value})])
        assignments.extend([('joint', weights), ('joint', {label: -value for label, value in weights.items()})])
        for index, (kind, replacements) in enumerate(assignments):
            run = directory / f'probe_{index:03d}'
            run.mkdir(exist_ok=True)
            raw, output = run / 'input.xlsx', run / 'recalculated.xlsx'
            probe = {'kind': kind, 'assignments': replacements, 'input': str(raw), 'output': str(output)}
            receipt['probes'].append(probe)
            probe_start = clock.monotonic()
            try:
                # Always clone the pristine goal, never a preceding probe result.
                book = openpyxl.load_workbook(goal, keep_links=False)
                try:
                    for label, value in replacements.items():
                        sheet, address = label.rsplit('!', 1)
                        book[sheet][address] = value
                    book.save(raw)
                finally:
                    book.close()
                probe['input_sha256'] = _digest(raw)
                engine.recalculate(raw, output)
                probe['output_sha256'] = _digest(output)
                actual, actual_sheets = _required_values(output, labels)
                changed = {label: {'before': expected[label], 'after': actual[label]}
                           for label in labels if expected[label] != actual[label]}
                probe.update(required_typed_values_sha256=_json_digest(actual), changed_values=changed,
                             structure_ok=actual_sheets == sheets, state='unchanged' if not changed else 'changed')
                if changed or actual_sheets != sheets:
                    receipt.update(state='observed_required_D_change', certainty='confirmed',
                        causal_attribution='error_sensitivity_or_recalculation_instability_not_distinguished',
                        reason='A recalculated native-error probe has changed required-D typed values or sheet structure; inactivity is not established')
                    return receipt
            except Exception as exc:
                probe.update(state='unknown', error_type=type(exc).__name__, error=str(exc)[:500])
                raise ValueError('Unable to execute or inspect a native-error probe') from exc
            finally:
                probe['duration_ms'] = round((clock.monotonic() - probe_start) * 1000)
        if reach['state'] != 'verified' or remaining:
            receipt['reason'] = 'Not every candidate-to-required-D path has a narrow program certificate; unchanged sentinels cannot clear it'
        else:
            receipt.update(state='current_scenario_inactive', blocking=False,
                reason='All candidate paths excluded by narrow certificates and every single/joint LO probe leaves full typed D unchanged')
    except Exception as exc:
        receipt.update(reason=str(exc)[:500], error_type=type(exc).__name__)
        if str(exc).startswith('Q10:'):
            receipt.update(problem_id='Q10', route_id='R10')
    finally:
        after = {name: _digest(path) if Path(path).is_file() else None for name, path in files.items()}
        receipt['immutable_after'] = after
        receipt['immutable_unchanged'] = all(after[name] == item['sha256'] for name, item in before.items())
        if not receipt['immutable_unchanged']:
            receipt.update(state='unknown', blocking=True, reason='An immutable formal artifact changed during probing')
        receipt['duration_ms'] = round((clock.monotonic() - started) * 1000)
        (directory / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False))
    return receipt
