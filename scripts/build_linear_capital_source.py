#!/usr/bin/env python3
"""Prepare and explicitly certify one independently solved native source.

Preparation emits no workbook and runs no finance, solver, LO or model. The
explicit execution path requires all three resource-bound recalculations,
complete A/B cache audits and two complete typed stability comparisons.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from decimal import Decimal
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import threading
import time
import traceback
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.core.audit import AuditStore, utcnow
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.workbook.linear_capital_portfolio import spec
from sheets_factory.workbook.resource_engine import load_runtime_profile, validate_workload_counts
from sheets_factory.workbook.thread_capped_resource_engine import ThreadCappedResourceLibreOfficeEngine as ResourceLibreOfficeEngine, validate_capped_call

PREPARED_KIND = 'prepared_linear_capital_native_source'
SOURCE_KIND = 'independently_verified_linear_capital_native_source'
DEFAULT_PROFILE = ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml'
IMAGE_ID = 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'


def require(value, message):
    if not value: raise ValueError(message)


def reference(path):
    p = Path(path).absolute()
    require(p == p.resolve() and p.is_file() and not p.is_symlink(), 'A real nonsymlink artifact is required')
    before = p.stat(); digest = hashlib.sha256()
    with p.open('rb') as stream:
        for part in iter(lambda: stream.read(4 * 1024**2), b''): digest.update(part)
    after = p.stat()
    require((before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
        (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'Artifact changed during hashing')
    return {'path': str(p), 'sha256': digest.hexdigest(), 'bytes': after.st_size}


def checked(ref):
    require(isinstance(ref, dict) and set(ref) == {'path', 'sha256', 'bytes'}
        and type(ref['bytes']) is int and ref['bytes'] >= 0 and reference(ref['path']) == ref,
        'The complete artifact reference changed')
    return Path(ref['path'])


def read(value):
    path = checked(value) if isinstance(value, dict) else checked(reference(value))
    def pairs(items):
        result = {}
        for key, child in items:
            require(key not in result, 'Duplicate JSON key'); result[key] = child
        return result
    value = json.loads(path.read_text(), object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON number')))
    require(isinstance(value, dict), 'An object artifact is required')
    return value


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write('\n')
    return reference(path)


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _module(path, name):
    loader = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(loader); loader.loader.exec_module(module)
    return module


def _reference_provider():
    return _module(ROOT / 'scripts/run_linear_capital_reference.py', '_linear_source_reference_admission')


def _resource_support():
    return _module(ROOT / 'scripts/build_heterogeneous_source.py', '_linear_source_generic_resource_support')


def validate_actual_call(call, runtime_record, frozen):
    return validate_capped_call(call, runtime_record, frozen,
        resource_validator=_resource_support().validate_actual_call)


def recipes():
    files = [Path(__file__), ROOT / 'scripts/run_linear_capital_reference.py',
        ROOT / 'scripts/build_heterogeneous_source.py']
    files += [ROOT / 'src/sheets_factory/workbook/linear_capital_portfolio' / name for name in
        ('spec.py', 'candidate_a.py', 'ledger.py', 'finance_crosscheck.py', 'model_a.py', 'model_b.py',
         'optimization_runtime.py', 'excel.py', 'formula_identity.py')]
    files += [ROOT / 'src/sheets_factory' / name for name in ('core/audit.py', 'dashboard/server.py', 'resume.py',
        'workbook/resource_engine.py', 'workbook/thread_capped_resource_engine.py', 'workbook/engine.py', 'workbook/uno_recalculate.py',
        'workbook/heterogeneous_contracts/validate.py', 'task_adapters/heterogeneous_formula_identity.py')]
    return {str(path.resolve()): reference(path)['sha256'] for path in files}


def _output(path, *, fresh=False):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_relative_to(ROOT / 'outputs')
        and path.is_relative_to(Path('/data')), 'Use a real project output directory on /data')
    if fresh: require(not path.exists(), 'Preserve prior preparations and failures')
    return path


def runtime(profile):
    record = reference(profile); value = load_runtime_profile(profile)
    require(value['id'] == 'entity_group_large_v2' and value['image']['id'] == IMAGE_ID
        and all(item == {'cpus': 2, 'memory_bytes': 32 * 1024**3, 'pids_limit': 256}
                for item in value['docker_resources'].values()), 'The pinned 2CPU/32GiB/PID256 resource profile is required')
    return record, value


def _validate_reference(reference_result, public):
    ref = reference_result if isinstance(reference_result, dict) else reference(reference_result)
    checked(ref)
    result = _reference_provider().validate_completed(ref)
    require(result['kind'] == 'linear_capital_independent_best_runner_reference' and result['passed'] is True,
        'A complete actual independent best-and-runner reference is required')
    require(spec.load_spec(read(result['specification'])) == public
        and result['specification_sha256'] == spec.canonical_sha256(public), 'Reference primitives differ')
    winner = spec.validate_plan(public, result['winner_plan'])
    require(result['unique_best'] is True and type(result['gap_pence']) is int and result['gap_pence'] >= 1
        and result['winner_objective_pence'] - result['runner_objective_pence'] == result['gap_pence'],
        'The actual independent solutions do not establish a unique posted optimum')
    count = sum(winner.values())
    require(result['selected_project_count'] == count and 80 <= count <= 160
        and result['selection_density_passed'] is True and result['solver_status_is_not_formal_certificate'] is True,
        'The prospectively declared private selection-density or proof boundary differs')
    return ref, result


def prepare(specification, reference_result, output, *, profile=DEFAULT_PROFILE):
    """Freeze existing actual prerequisites, without emitting or executing."""
    original = reference(specification); public = spec.load_spec(read(original))
    require(public['dimension_mode'] == 'production', 'A toy is not a production source')
    ref, proof = _validate_reference(reference_result, public)
    require(original['sha256'] == proof['specification']['sha256']
        and original['bytes'] == proof['specification']['bytes'], 'Use the exact predeclared raw specification bytes')
    profile_ref, policy = runtime(profile); recipe = recipes()
    output = _output(output, fresh=True); output.mkdir(parents=True)
    private = output / 'private'; private.mkdir()
    copied = private / 'specification.json'; shutil.copyfile(checked(original), copied)
    require(reference(copied)['sha256'] == original['sha256'], 'Primitive copy changed')
    return write(output / 'preparation.json', {'kind': PREPARED_KIND, 'version': 1, 'created_at': utcnow(),
        'original_specification': original, 'private_specification': reference(copied),
        'specification_sha256': spec.canonical_sha256(public), 'independent_reference': ref,
        'independent_reference_canonical_sha256': canonical(proof), 'winner_plan': proof['winner_plan'],
        'winner_objective_pence': proof['winner_objective_pence'], 'runtime_profile': profile_ref,
        'runtime_profile_value': policy, 'recipe': recipe, 'recipe_sha256': canonical(recipe),
        'source_workbook_materialized': False, 'additional_financial_forwards': 0, 'optimizer_calls': 0,
        'LO_calls': 0, 'model_calls': 0, 'task_count': 0, 'qualified': False})


def validate_prepared(output):
    output = _output(output)
    frozen = read(output / 'preparation.json')
    require(frozen['kind'] == PREPARED_KIND and type(frozen['version']) is int and frozen['version'] == 1
        and frozen['recipe'] == recipes() and frozen['recipe_sha256'] == canonical(frozen['recipe']), 'The frozen source recipe changed')
    require(frozen['source_workbook_materialized'] is False and frozen['additional_financial_forwards'] == 0
        and frozen['optimizer_calls'] == frozen['LO_calls'] == frozen['model_calls'] == frozen['task_count'] == 0
        and frozen['qualified'] is False, 'A prepared source cannot inherit execution or task claims')
    public = spec.load_spec(read(frozen['private_specification']))
    require(public['dimension_mode'] == 'production', 'A toy is not a production source')
    checked(frozen['original_specification'])
    require(frozen['private_specification']['sha256'] == frozen['original_specification']['sha256']
        and frozen['specification_sha256'] == spec.canonical_sha256(public), 'Frozen source primitives differ')
    _, proof = _validate_reference(frozen['independent_reference'], public)
    require(canonical(proof) == frozen['independent_reference_canonical_sha256']
        and proof['winner_plan'] == frozen['winner_plan'] and proof['winner_objective_pence'] == frozen['winner_objective_pence'],
        'The independently certified reference changed')
    require(runtime(checked(frozen['runtime_profile'])) == (frozen['runtime_profile'], frozen['runtime_profile_value']), 'Resource profile changed')
    return frozen, public, proof


def expected_results(proof):
    """Join only already verified independent postings and plan aggregations."""
    universes = [read(proof['universe_' + side]) for side in ('A', 'B')]
    validation = read(proof['reference_validation'])
    require(validation.get('kind') == 'posted_universe_plan_aggregation_crosscheck'
        and validation.get('passed') is True and validation.get('require_group_feasible') is True
        and validation.get('plan_count') == 3 and [r['id'] for r in validation['plans']] == ['winner', 'runner_A', 'runner_B'],
        'The complete winner and both runner financial aggregations are required')
    winner = validation['plans'][0]
    require(winner['plan'] == proof['winner_plan'] and winner['passed'] is True
        and not winner['errors'] and not winner['differences'], 'The winner financial aggregation is incomplete')
    result = []
    for side, universe in zip(('A', 'B'), universes):
        require(winner[side]['feasible'] is True and winner[side]['objective_pence'] == proof['winner_objective_pence'], 'Winner finance differs from the optimum')
        result.append({**universe, **winner[side], 'plan': proof['winner_plan']})
    return tuple(result)


def _at(value, path):
    for key in path:
        require(isinstance(value, (dict, list)) and (type(key) is str if isinstance(value, dict) else type(key) is int),
            'A private financial locator has an invalid path')
        require(key in value if isinstance(value, dict) else 0 <= key < len(value), 'A private locator is out of bounds')
        value = value[key]
    return value


def _financial_value(result, binding):
    value = _at(result, binding['expected_path'])
    if 'vintage_field' in binding:
        require(isinstance(value, list), 'A complete sparse vintage list is required')
        rows = {}
        for row in value:
            require(isinstance(row, dict) and set(row) == {'year', 'fiscal_year', 'origin_year', *spec.VINTAGE_FIELDS}
                and type(row['year']) is int and type(row['origin_year']) is int and 1 <= row['origin_year'] <= row['year']
                and all(type(row[f]) is int and row[f] >= 0 for f in spec.VINTAGE_FIELDS), 'An invalid tax-loss vintage cannot be treated as zero')
            identity = row['year'], row['origin_year']
            require(identity not in rows, 'Duplicate tax-loss vintage identity'); rows[identity] = row
        identity = binding['vintage_year'], binding['origin_year']
        require(all(type(v) is int for v in identity) and 1 <= identity[1] <= identity[0], 'A bound vintage identity is invalid')
        require(binding['vintage_field'] in spec.VINTAGE_FIELDS, 'Unknown vintage field')
        value = rows.get(identity, {}).get(binding['vintage_field'], 0)
    if 'constraint_id' in binding:
        require(isinstance(value, list), 'The full business constraint list is required')
        rows = {row['id']: row for row in value}
        require(len(rows) == len(value) and binding['constraint_id'] in rows, 'A business constraint is missing or duplicated')
        require(binding['constraint_field'] in ('lhs', 'limit', 'slack', 'passed'), 'Unknown financial constraint field')
        value = rows[binding['constraint_id']][binding['constraint_field']]
    kind = binding['kind']
    require(binding.get('worksheet_scale') == 1, 'This source uses native integer pence, not hidden scaling')
    if kind == 'flag':
        require(type(value) is bool or type(value) is int and value in (0, 1), 'An explicit financial flag is required')
        return int(value)
    if value is None:
        require(kind == 'nullable_money_pence', 'Only an inapplicable NPV may be blank')
        return None
    require(kind in ('money_pence', 'integer', 'nullable_money_pence') and type(value) is int
        and abs(value) < spec.EXACT_LIMIT, 'An exact independently posted financial integer is required')
    return value


def _typed(value):
    if value is None or value == '' and type(value) is str: return ('empty', None)
    if type(value) is bool: return ('bool', value)
    if type(value) in (int, float, Decimal):
        number = Decimal(str(value)); require(number.is_finite(), 'Nonfinite workbook cache')
        return ('number', number)
    return ('text', value)


def expected_values(public, result_a, result_b, bindings, plan):
    """Resolve every formula through both independent forward results."""
    require(bindings.get('binding_version') == 1 and bindings.get('specification_sha256') == spec.canonical_sha256(public)
        and bindings.get('financial_expected_values_embedded') is False
        and bindings.get('financial_implementation_executed') is False and bindings.get('optimization_executed') is False,
        'The emitter must supply definitions and private locators, not financial answers')
    plan = spec.validate_plan(public, plan)
    values, formulas = {}, {}
    def add(binding, value):
        point = binding['sheet'], binding['cell']; require(point not in values, 'A physical expected binding is duplicated'); values[point] = value
    for row in bindings['input_bindings']: add(row, _at(public, row['path']))
    for row in bindings['literal_bindings']: add(row, row['value'])
    require([row['project_id'] for row in bindings['decision_bindings']] == public['project_ids'], 'The entire shared decision vector is required')
    for row in bindings['decision_bindings']:
        require(row['value'] == plan[row['project_id']] and type(row['value']) is int, 'Source choice differs from the explicit independently solved winner')
        add(row, row['value'])
    financial = {(r['sheet'], r['cell']): r for r in bindings['financial_bindings']}
    require(len(financial) == len(bindings['financial_bindings']), 'A financial formula locator is duplicated')
    resolved = {}
    for point, row in financial.items():
        av, bv = _financial_value(result_a, row), _financial_value(result_b, row)
        require(type(av) is type(bv) and av == bv, 'Independent financial expectations disagree')
        resolved[point] = av
        if row.get('formula') is None:
            require(point in values and _typed(values[point]) == _typed(av),
                'A static financial literal disagrees with its independent financial posting')
    derived_points = []
    for row in bindings['arithmetic_bindings']:
        point = row['sheet'], row['cell']; require(point not in formulas, 'A formula definition is duplicated'); formulas[point] = row['formula']
        if point in financial:
            require(row == financial[point] and row['formula'] is not None, 'Arithmetic and financial definition identities differ')
            add(row, resolved[point])
        else:
            derived_points.append(point)
            require(point == ('Portfolio', 'B3') and row.get('expected_derivation') == {'kind': 'complete_binary_decisions', 'project_ids': public['project_ids']},
                'An unsupported physical formula has no independent financial coverage')
            add(row, int(len(plan) == len(public['project_ids']) and all(type(v) is int and v in (0, 1) for v in plan.values())))
    require(derived_points == [('Portfolio', 'B3')], 'Exactly the input-only plan-completeness formula is allowed without a financial locator')
    require(all(p in formulas if r.get('formula') is not None else p in values for p,r in financial.items())
        and len(formulas) == bindings['formula_count'], 'All physical formulas must have complete independent coverage')
    return {'values': values, 'formulas': formulas, 'financial_locator_count': len(financial),
        'financial_formula_count': sum(r.get('formula') is not None for r in financial.values()), 'formula_count': len(formulas)}


def audit_workbook(workbook, public, result_a, result_b, bindings, plan, raw_literals):
    import openpyxl
    from sheets_factory.workbook.linear_capital_portfolio.formula_identity import formula_signature
    expected = expected_values(public, result_a, result_b, bindings, plan)
    formula_book = openpyxl.load_workbook(workbook, read_only=True, data_only=False, keep_links=False)
    cache_book = openpyxl.load_workbook(workbook, read_only=True, data_only=True, keep_links=False)
    differences, errors, actual_formula, actual_nonempty = [], [], {}, set()
    try:
        require(formula_book.sheetnames == cache_book.sheetnames == bindings['sheetnames'], 'Full worksheet order changed')
        for sheet in formula_book:
            for row in sheet:
                for cell in row:
                    if cell.value is None: continue
                    point = sheet.title, cell.coordinate; actual_nonempty.add(point)
                    if cell.data_type == 'f': actual_formula[point] = cell.value
        require(set(actual_formula) == set(expected['formulas']) and all(formula_signature(actual_formula[p]) == formula_signature(f)
            for p, f in expected['formulas'].items()), 'The complete physical formula scope or lexical definition changed')
        observed = {}
        for sheet in cache_book:
            for row in sheet:
                for cell in row:
                    if cell.value is None: continue
                    point = sheet.title, cell.coordinate; observed[point] = cell.value
                    if cell.data_type == 'e': errors.append({'sheet': sheet.title, 'cell': cell.coordinate, 'error': cell.value})
        for point, wanted in expected['values'].items():
            actual = observed.get(point)
            if _typed(actual) != _typed(wanted): differences.append({'sheet': point[0], 'cell': point[1], 'expected': wanted, 'actual': actual})
        require(actual_nonempty == set(expected['values']), 'A physical input, label, decision or formula is missing or extra')
        for point, wanted in raw_literals.items():
            if _typed(observed.get(point)) != wanted:
                differences.append({'sheet': point[0], 'cell': point[1], 'claim': 'Provided literal/date/unit changed', 'expected': str(wanted), 'actual': observed.get(point)})
        return {'kind': 'complete_linear_capital_native_workbook_A_B_audit', 'passed': not differences and not errors,
            'audited_file': reference(workbook), 'specification_sha256': spec.canonical_sha256(public),
            'bindings_sha256': canonical(bindings), 'expected_A_sha256': canonical(result_a), 'expected_B_sha256': canonical(result_b),
            'all_physical_formulas_checked': len(expected['formulas']), 'all_financial_locators_checked': expected['financial_locator_count'],
            'all_expected_values_checked': len(expected['values']), 'public_literals_checked': len(raw_literals),
            'native_error_count': len(errors), 'native_errors': errors, 'mismatch_count': len(differences),
            'mismatches': differences, 'all_values_checked': True, 'differences_truncated': False,
            'money_quantization_applied': False, 'additional_financial_forwards': 0,
            'source_or_task_or_difficulty_certified_by_this_audit': False}
    finally: formula_book.close(); cache_book.close()




def validate_audit(report, workbook, public, result_a, result_b, bindings, raw_literals):
    expected_count = sum(len(bindings[key]) for key in ('input_bindings', 'literal_bindings', 'decision_bindings', 'arithmetic_bindings'))
    require(report.get('kind') == 'complete_linear_capital_native_workbook_A_B_audit'
        and report.get('passed') is True and report.get('all_values_checked') is True
        and report.get('audited_file') == reference(workbook)
        and report.get('specification_sha256') == spec.canonical_sha256(public)
        and report.get('bindings_sha256') == canonical(bindings)
        and report.get('expected_A_sha256') == canonical(result_a) and report.get('expected_B_sha256') == canonical(result_b)
        and report.get('all_physical_formulas_checked') == bindings['formula_count']
        and report.get('all_financial_locators_checked') == len(bindings['financial_bindings'])
        and report.get('all_expected_values_checked') == expected_count
        and report.get('public_literals_checked') == len(raw_literals)
        and report.get('native_error_count') == report.get('mismatch_count') == 0
        and report.get('native_errors') == report.get('mismatches') == []
        and report.get('money_quantization_applied') is False and report.get('differences_truncated') is False,
        'A complete independent A/B financial, literal, formula and cache audit is required')
    return True


def financial_locator_coverage(public, bindings):
    """Check the entire declared business layout, including provided zeroes."""
    required = set()
    for pid in public['project_ids']:
        for sid in public['scenario_ids']:
            root = ('projects', pid, 'scenarios', sid)
            required.update((root + ('t0', field),) for field in spec.T0_FIELDS)
            required.update((root + ('annual', yi, field),) for yi, _ in enumerate(public['years'])
                for field in ('operating_active', 'feasible', *spec.ANNUAL_FIELDS))
            required.update((root + (field,),) for field in ('feasible', 'npv_pence'))
            required.update((root + ('tax_vintages',), year, origin, field)
                for year in public['years'] for origin in range(max(1, year-4), year+1) for field in spec.VINTAGE_FIELDS)
    required.update((('group', 'scenarios', sid, 'annual', yi, field),)
        for sid in public['scenario_ids'] for yi, _ in enumerate(public['years']) for field in spec.GROUP_FIELDS)
    identities = ['initial_sponsor_equity']
    for sid in public['scenario_ids']:
        for year in public['years']:
            identities.extend([f'annual_new_lp:{sid}:{year}', f'annual_debt_close:{sid}:{year}'])
            identities.extend(f'resource:{resource}:{sid}:{year}' for resource in public['resource_ids'])
    for family in ('region', 'sector'):
        identities.extend(f'{family}_exposure:{label}:{year}' for label in public[family+'_ids'] for year in public['years'])
    identities.extend('exclusivity:'+row['id'] for row in public['exclusivity_groups'])
    identities.extend('prerequisite:'+row['id'] for row in public['prerequisites'])
    required.update((('constraints',), identity, field) for identity in identities for field in ('lhs', 'limit', 'slack', 'passed'))
    required.update(((field,),) for field in ('feasible', 'objective_pence', 'all_standalone_feasible'))
    actual = set()
    for row in bindings['financial_bindings']:
        path = tuple(row['expected_path'])
        key = ((path, row['vintage_year'], row['origin_year'], row['vintage_field']) if 'vintage_field' in row else
            (path, row['constraint_id'], row['constraint_field']) if 'constraint_id' in row else (path,))
        actual.add(key)
    missing, extra = required-actual, actual-required
    require(not missing and not extra, 'The complete project, tax-vintage, group or capacity financial field census differs')
    return {'kind': 'complete_linear_capital_business_field_coverage', 'required_distinct_fields': len(required),
        'actual_distinct_fields': len(actual), 'physical_financial_bindings': len(bindings['financial_bindings']),
        'missing': 0, 'extra': 0, 'all_candidates_periods_scenarios_and_effective_vintages': True,
        'financial_postings_recalculated': False}


def raw_geometry(workbook, public, bindings, expected, policy):
    import openpyxl
    coverage = financial_locator_coverage(public, bindings)
    book = openpyxl.load_workbook(workbook, read_only=False, data_only=False, keep_links=False)
    try:
        require(book.sheetnames == bindings['sheetnames'] and not book._external_links, 'The native source must be self-contained')
        literals, actual, cells, longest = {}, {}, 0, 0
        for sheet in book:
            require(sheet.max_row <= 1048576 and sheet.max_column <= 16384, 'Worksheet bounds exceeded')
            for cell in sheet._cells.values():
                if cell.value is None: continue
                cells += 1; point = sheet.title, cell.coordinate
                if cell.data_type == 'f':
                    actual[point] = cell.value; longest = max(longest, len(cell.value))
                    require('[' not in cell.value and not re.search(r'\b(?:WEBSERVICE|RTD|HYPERLINK)\s*\(', cell.value, re.I), 'External formula dependencies are not permitted')
                else:
                    literals[point] = _typed(cell.value)
                    if type(cell.value) is str and cell.value.lstrip().startswith(('{', '[')):
                        try: payload = json.loads(cell.value)
                        except (ValueError, TypeError): payload = None
                        require(not isinstance(payload, (dict, list)), 'Do not publish a prejoined programmatic input payload')
        require(actual == expected['formulas'] and 0 < longest <= 8192 and cells == len(expected['values']), 'The complete uncached workbook geometry differs')
        limits = validate_workload_counts(policy, {'source_physical_formulas': len(actual), 'max_profile_cells': cells,
            'max_dependency_closure_cells': len(expected['values']), 'full_target_cells': len(bindings['financial_bindings']) + len(bindings['decision_bindings'])})
        require(bindings['public_rules'] == list(__import__('sheets_factory.workbook.linear_capital_portfolio.excel', fromlist=['PUBLIC_RULES']).PUBLIC_RULES), 'Native public rules differ')
        return literals, {'kind': 'complete_native_linear_capital_source_geometry', 'physical_formula_count': len(actual),
            'nonempty_cells': cells, 'maximum_formula_length': longest, 'resource_limits': limits, 'truncated': False,
            'all_formula_expected_values_independent_A_B': True, 'self_contained_native_inputs': True,
            'complete_business_field_coverage': coverage}
    finally: book.close()


@contextmanager
def _stage(audit, name):
    start = time.monotonic(); node = audit.record('nodes', {'node': name, 'status': 'running', 'started_at': utcnow(), 'duration_ms': 0})
    audit.update_run(active_stage=name); audit.export()
    try: yield
    finally:
        audit.update_record('nodes', node, {'status': 'completed' if sys.exc_info()[0] is None else 'failed', 'duration_ms': 1000*(time.monotonic()-start), 'finished_at': utcnow()}); audit.export()


def execute_prepared(output, *, port=0):
    from sheets_factory.workbook.linear_capital_portfolio import excel
    from sheets_factory.workbook.heterogeneous_contracts.validate import compare_typed_caches
    output = _output(output)
    require(not (output / 'execution_started.json').exists(), 'No automatic source retry is permitted')
    lease = ProducerLease(output).acquire(); audit = server = thread = None
    stop = threading.Event(); start = time.monotonic(); calls = []; status = 'failed'; failure = None
    attempt = output / 'private/attempts' / uuid.uuid4().hex; attempt.mkdir(parents=True)
    records = {}; stage_name = {'value': 'starting'}
    try:
        audit = AuditStore(attempt / 'audit', {'id': attempt.name, 'name': 'Native linear capital source', 'status': 'running',
            'target_count': 0, 'producer_active': True, 'producer_pid': os.getpid(), 'qualified': 0})
        server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port); url = server.start()
        records['started'] = write(attempt / 'started.json', {'preparation': reference(output / 'preparation.json'),
            'started_at': utcnow(), 'dashboard_url': url, 'producer_pid': os.getpid()})
        write(output / 'execution_started.json', {'first_attempt_only': True, 'started': records['started']})
        audit.update_run(dashboard_url=url)
        print(json.dumps({'dashboard_url': url, 'attempt': str(attempt), 'started': records['started']}), flush=True)
        def heartbeat():
            while not stop.wait(15): audit.update_run(elapsed_seconds=time.monotonic()-start, actual_stage=stage_name['value']); audit.export()
        thread = threading.Thread(target=heartbeat, daemon=True); thread.start()
        with _resource_support().data_temporary(output):
            with _stage(audit, 'validate_frozen_reference_and_recipe'):
                stage_name['value'] = 'validate_frozen_reference_and_recipe'
                frozen, public, proof = validate_prepared(output)
                a, b = expected_results(proof)
                records['independent_A_result'] = write(attempt / 'independent_A_expected.json', a)
                records['independent_B_result'] = write(attempt / 'independent_B_expected.json', b)
            with _stage(audit, 'emit_complete_native_formula_workbook'):
                stage_name['value'] = 'emit_complete_native_formula_workbook'
                raw = attempt / 'raw.xlsx'
                bindings = excel.emit_workbook(raw, public, plan=frozen['winner_plan'],
                    max_formulas=frozen['runtime_profile_value']['limits']['source_physical_formulas'])
                expected = expected_values(public, a, b, bindings, frozen['winner_plan'])
                literals, geometry = raw_geometry(raw, public, bindings, expected, frozen['runtime_profile_value'])
                records['bindings'] = write(attempt / 'bindings.json', bindings)
                records['geometry'] = write(attempt / 'geometry.json', geometry)
                del expected
            engine = ResourceLibreOfficeEngine(ROOT, frozen['runtime_profile']['path'], role='source', receipt_directory=attempt / 'engine_resources')
            engine.ensure_image(); versions = []; audits = []
            current = raw
            for index in (1, 2, 3):
                with _stage(audit, 'actual_LO_' + str(index)):
                    stage_name['value'] = 'actual_LO_' + str(index)
                    destination = attempt / ('pass' + str(index) + '.xlsx')
                    call = {'index': index, 'input': reference(current), 'started_at': utcnow(), 'completed': False}; calls.append(call)
                    call['started_receipt'] = write(attempt / ('LO' + str(index) + '_started.json'), dict(call))
                    tick = time.monotonic()
                    try:
                        current = Path(engine.recalculate(current, destination)); call.update(completed=True, output=reference(current), elapsed_seconds=time.monotonic()-tick)
                        history = engine.metadata()['actual_resource_receipts']; require(len(history) == index, 'An extra or missing LO call occurred')
                        call['actual_resource_evidence'] = validate_actual_call(call, history[-1], frozen)
                    finally:
                        call['finished_at'] = utcnow(); call['terminal_receipt'] = write(attempt / ('LO' + str(index) + '_terminal.json'), dict(call))
                        audit.update_run(actual_LO_calls_started=len(calls), actual_LO_calls_completed=sum(c['completed'] for c in calls))
                with _stage(audit, 'complete_A_B_cache_audit_' + str(index)):
                    stage_name['value'] = 'complete_A_B_cache_audit_' + str(index)
                    report = audit_workbook(current, public, a, b, bindings, frozen['winner_plan'], literals)
                    audits.append(write(attempt / ('audit_pass' + str(index) + '.json'), report))
                    validate_audit(report, current, public, a, b, bindings, literals)
                versions.append(current)
            with _stage(audit, 'two_complete_typed_stability_comparisons'):
                stage_name['value'] = 'two_complete_typed_stability_comparisons'
                stable = [{'left': reference(versions[0]), 'right': reference(v), 'comparison': compare_typed_caches(versions[0], v)} for v in versions[1:]]
                records['stability'] = write(attempt / 'complete_stability.json', {'comparisons': stable, 'passed': all(r['comparison']['passed'] for r in stable)})
                require(all(r['comparison']['passed'] for r in stable), 'The full typed cache union is unstable')
            with _stage(audit, 'final_source_and_recipe_binding'):
                stage_name['value'] = 'final_source_and_recipe_binding'
                validate_prepared(output)
                source = output / 'source.xlsx'; shutil.copyfile(versions[0], source)
                require(reference(source)['sha256'] == reference(versions[0])['sha256'], 'Verified source copy changed')
                manifest = {'kind': SOURCE_KIND, 'version': 1, 'status': 'source_verified_not_task_or_difficulty_qualified',
                    'workbook': reference(source), 'local_path': str(source), 'derived_workbook_sha256': reference(source)['sha256'],
                    'public_specification': frozen['private_specification'], 'independent_reference': frozen['independent_reference'],
                    'financial_crosscheck': proof['financial_crosscheck'], 'runtime_profile': frozen['runtime_profile'],
                    'source_preparation': reference(output / 'preparation.json'), 'source_recipe_sha256': frozen['recipe'],
                    'source_copy': {'from': reference(versions[0]), 'to': reference(source), 'same_bytes': True},
                    'bindings': records['bindings'], 'geometry': records['geometry'], 'independent_A_expected': records['independent_A_result'],
                    'independent_B_expected': records['independent_B_result'], 'financial_audits': audits,
                    'actual_engine_calls': calls, 'stability': records['stability'], 'winner_plan_private': frozen['winner_plan'],
                    'winner_objective_pence_private': frozen['winner_objective_pence'], 'raw_ancestor_sha256': public['provenance']['ancestor_sha256'],
                    'original_ancestor_count': len(set(public['provenance']['ancestor_sha256'])), 'derived_source_count': 1,
                    'source_financially_verified': True, 'additional_financial_forwards': 0, 'optimizer_calls': 0,
                    'LO_calls': 3, 'model_calls': 0, 'task_count': 0, 'qualified': False,
                    'source_admission_inherited_from_engineering': False, 'normal_task_quality_passed': False, 'difficulty_qualified': False}
                records['source_manifest'] = write(output / 'source_manifest.json', manifest)
                status = 'source_verified'
    except BaseException as error:
        failure = error; records['failure'] = write(attempt / 'failure.json', {'error_type': type(error).__name__, 'error': str(error), 'traceback': traceback.format_exc()})
    finally:
        stop.set()
        if thread: thread.join(timeout=1)
        terminal = write(attempt / 'terminal.json', {'kind': 'linear_capital_native_source_build_terminal', 'status': status,
            'finished_at': utcnow(), 'elapsed_seconds': time.monotonic()-start, 'records': records, 'actual_LO_calls': calls,
            'all_partial_and_failed_artifacts_preserved': True, 'model_calls': 0, 'task_count': 0, 'qualified': False})
        if audit: audit.update_run(status=status, producer_active=False, terminal=terminal); audit.export()
        if server: server.stop()
        if audit: audit.db.close()
        lease.release()
    print(json.dumps({'terminal': terminal, 'status': status}), flush=True)
    if failure: raise RuntimeError('Source verification failed; preserve ' + terminal['path']) from failure
    return records['source_manifest']


def validate_source(value):
    """Read-only actual-source admission; no emission, solve or recalculation.

    Existing complete audit receipts bind exact workbook bytes and the frozen
    audit implementation. This validates those receipts without claiming a
    fresh financial forward or repeating the three actual source calls.
    """
    manifest_ref = value if isinstance(value, dict) else reference(value)
    manifest = read(manifest_ref)
    require(manifest.get('kind') == SOURCE_KIND and type(manifest.get('version')) is int and manifest['version'] == 1
        and manifest.get('status') == 'source_verified_not_task_or_difficulty_qualified'
        and manifest.get('source_financially_verified') is True, 'A completed actual native source is required')
    output = Path(manifest['source_preparation']['path']).parent
    frozen, public, proof = validate_prepared(output)
    require(manifest['source_preparation'] == reference(output/'preparation.json')
        and manifest['source_recipe_sha256'] == frozen['recipe']
        and manifest['public_specification'] == frozen['private_specification']
        and manifest['independent_reference'] == frozen['independent_reference']
        and manifest['financial_crosscheck'] == proof['financial_crosscheck']
        and manifest['runtime_profile'] == frozen['runtime_profile'], 'The source ancestry or current code recipe differs')
    source = checked(manifest['workbook'])
    require(source == output/'source.xlsx' and manifest['local_path'] == str(source)
        and manifest['derived_workbook_sha256'] == manifest['workbook']['sha256'], 'The actual source identity changed')
    a, b = expected_results(proof)
    require(canonical(read(manifest['independent_A_expected'])) == canonical(a)
        and canonical(read(manifest['independent_B_expected'])) == canonical(b), 'Independent financial expectation files changed')
    bindings = read(manifest['bindings']); expected = expected_values(public, a, b, bindings, frozen['winner_plan'])
    coverage = financial_locator_coverage(public, bindings)
    geometry = read(manifest['geometry'])
    require(geometry['physical_formula_count'] == len(expected['formulas'])
        and geometry['nonempty_cells'] == len(expected['values'])
        and 0 < geometry['maximum_formula_length'] <= 8192 and geometry['truncated'] is False
        and geometry['complete_business_field_coverage'] == coverage and geometry['self_contained_native_inputs'] is True,
        'Complete native source geometry or business-field coverage differs')
    calls, audits = manifest['actual_engine_calls'], manifest['financial_audits']
    require(len(calls) == len(audits) == 3 and [c['index'] for c in calls] == [1,2,3], 'Exactly three actual complete calls and audits are required')
    literal_count = sum(len(bindings[k]) for k in ('input_bindings','literal_bindings','decision_bindings'))
    # Only its length is used in validate_audit; actual public literals were all
    # checked against both raw input bindings and raw geometry by each audit.
    literal_census = dict.fromkeys(range(literal_count))
    for index, (call, audit_ref) in enumerate(zip(calls, audits)):
        require(call['completed'] is True and read(call['terminal_receipt']) == {k:v for k,v in call.items() if k!='terminal_receipt'},
            'An actual source call terminal changed')
        if index: require(call['input'] == calls[index-1]['output'], 'The three actual source calls are not chained')
        evidence = validate_actual_call(call, call['actual_resource_evidence']['terminal'], frozen)
        require(evidence == call['actual_resource_evidence'], 'Actual source resource evidence differs')
        validate_audit(read(audit_ref), checked(call['output']), public, a, b, bindings, literal_census)
    copied = manifest['source_copy']
    require(copied == {'from':calls[0]['output'],'to':manifest['workbook'],'same_bytes':True}
        and copied['from']['sha256'] == copied['to']['sha256'] and copied['from']['bytes'] == copied['to']['bytes'],
        'The source copy is not byte-identical to the independently audited first pass')
    stability = read(manifest['stability'])
    require(stability.get('passed') is True and len(stability['comparisons']) == 2, 'Both complete typed stability comparisons are required')
    for pair, call in zip(stability['comparisons'],calls[1:]):
        report = pair['comparison']
        require(pair['left'] == calls[0]['output'] and pair['right'] == call['output']
            and report.get('passed') is True and report.get('typed_value_mismatches') == 0
            and report.get('entire_value_union_checked') is True and report.get('money_quantization_applied') is False
            and type(report.get('union_cells_checked')) is int and report['union_cells_checked'] >= geometry['nonempty_cells'],
            'Complete exact typed source stability evidence differs')
    require(manifest['winner_plan_private'] == proof['winner_plan']
        and manifest['winner_objective_pence_private'] == proof['winner_objective_pence']
        and manifest['raw_ancestor_sha256'] == public['provenance']['ancestor_sha256']
        and manifest['original_ancestor_count'] == len(set(public['provenance']['ancestor_sha256']))
        and manifest['derived_source_count'] == 1 and manifest['LO_calls'] == 3
        and all(type(manifest[k]) is int and manifest[k] == 0 for k in ('model_calls','task_count','optimizer_calls','additional_financial_forwards'))
        and manifest['qualified'] is False and manifest['source_admission_inherited_from_engineering'] is False
        and manifest['normal_task_quality_passed'] is False and manifest['difficulty_qualified'] is False,
        'Source-only proof boundaries or original-ancestor counts changed')
    attempt = Path(audits[0]['path']).parent
    require(attempt.is_relative_to(output/'private/attempts') and re.fullmatch('[0-9a-f]{32}', attempt.name), 'A fresh owned source attempt is required')
    terminal = read(attempt/'terminal.json')
    require(terminal['kind'] == 'linear_capital_native_source_build_terminal' and terminal['status'] == 'source_verified'
        and terminal['records']['source_manifest'] == manifest_ref and terminal['actual_LO_calls'] == calls,
        'The source did not terminate with the exact completed immutable manifest')
    return manifest



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path); parser.add_argument('--reference', type=Path)
    parser.add_argument('--output', type=Path); parser.add_argument('--profile', type=Path, default=DEFAULT_PROFILE)
    parser.add_argument('--prepared', type=Path); parser.add_argument('--run', action='store_true'); parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    if args.prepared:
        require(args.spec is None and args.reference is None and args.output is None, 'Choose an existing preparation or a new source')
        result = execute_prepared(args.prepared, port=args.port) if args.run else reference(args.prepared / 'preparation.json')
    else:
        require(args.spec is not None and args.reference is not None and args.output is not None, 'Provide --spec --reference --output')
        result = prepare(args.spec, args.reference, args.output, profile=args.profile)
        if args.run: result = execute_prepared(args.output, port=args.port)
    print(json.dumps(result), flush=True)
