#!/usr/bin/env python3
"""Freeze native eight-business development; only run-development calls a model."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
from types import FunctionType

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from openpyxl import load_workbook
from sheets_factory.evaluation.budget import validate_selection_execution_budget
from sheets_factory.evaluation.native_transport_frontier import POLICY_V3, transport_profile, PROFILE_PATH
from sheets_factory.evaluation.resource_frontier import TASK_FILES, MODEL, EFFORT
from sheets_factory.evaluation.thread_capped_harbor_export import (
    CAP_FIELD, CAP_VALUE, export_resource_harbor, inspect_resource_export, verify_local_base_image)
from sheets_factory.evaluation.streaming_verifier import _sparse_cells, normalize
from sheets_factory.task_adapters.heterogeneous_formula_identity import formula_signature
from sheets_factory.workbook.resource_engine import load_runtime_profile
from sheets_factory.evaluation.streaming_delta import compare_workbooks

KIND = 'prequality_heterogeneous_native_review_development'
VERSION = 2
NATIVE_VERSION = 2
MATERIAL_KIND = 'materialized_unverified_heterogeneous_review_task_view'
ACTUAL_KIND = 'heterogeneous_review_task_view_actual_validation'
PREPARED_KIND = 'prepared_heterogeneous_review_task_view'
CONTROL_REWARDS = {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}
BUDGET = {'version': 1, 'elapsed_policy': 'operational_guard', 'elapsed_guard_seconds': 14400, 'tool_budget_seconds': 1800}
PENDING = ['independent_recovery_policy_and_public_sufficiency', 'all_12_quality_checks', 'normal_Factory_nodes',
    'normal_ExportNode', 'actual_Harbor_oracle_and_nop', 'fresh_final_cohort_confirmation']
HISTORY_ROOTS = (ROOT/'outputs/difficulty', ROOT/'outputs/research')
SHARED = ROOT/'scripts/prepare_linear_capital_scaled_development.py'
SHARED_SHA256 = '29a575da6dde372a1290af0737c77433ded3515202f8e3f8e8db9f6d3e525329'
VALIDATOR = ROOT/'scripts/validate_heterogeneous_review_task_pair_v2.py'
VALIDATOR_SHA256 = 'e2218698be941478eeafe98c4f4dcd9950ff886921454aebdd9d507c7b1e3b83'
NATIVE_DEPENDENCIES = {
    str(ROOT/'src/sheets_factory/workbook/heterogeneous_review_tasks_v2.py'): 'fb509c6387825783393d80e7b19c4233fce3f7cedfa52ef3d5fa41608f64ba3b',
    str(ROOT/'config/heterogeneous_review_tasks_v2.json'): 'c05b126a869db5d7eecad55dae9ef148f402b56b2e127c98b49507b7844a1ad9',
    str(ROOT/'src/sheets_factory/workbook/heterogeneous_review_tasks.py'): 'c0432c67ed821448b5b26ee650e597987cd00f2aa5fdef9753b9143834187327',
    str(ROOT/'scripts/validate_heterogeneous_review_task_pair.py'): '3a5d1eefc5a6d02646a0d12145b2da41609bd626e2a8a8e7867681a9de949d6e',
    str(ROOT/'config/heterogeneous_review_tasks_v1.json'): 'c8c8e09813077b071812e35d36a58875bd324263ec4bf47dfcde691c7d3f731c',
    str(ROOT/'scripts/prepare_heterogeneous_review_task_pair_v2.py'): 'ad0fa75f7fa49613b1b8af6f1aadbbfbd1b842d8b745dec33df7f0f7d20360b0',
    str(ROOT/'tests/test_heterogeneous_review_tasks_v2.py'): '3d19f61d28bf2aef58a5fbacc3ae70891e3431db4510092e8089c292d60f0ef7',
}
_DRIVER = None


def _reuse_frozen_boundaries():
    require_raw = SHARED.read_bytes()
    if SHARED != SHARED.resolve() or hashlib.sha256(require_raw).hexdigest() != SHARED_SHA256:
        raise ValueError('The frozen development/export/history boundary changed')
    descriptor = importlib.util.spec_from_file_location('_native_development_frozen_shared', SHARED)
    module = importlib.util.module_from_spec(descriptor)
    descriptor.loader.exec_module(module)
    names = ('require', 'canonical', 'reference', 'checked', 'read', 'write', 'verify_mapping',
        'bind_references', 'workbook_identity', '_historical_identity', '_historical_reference',
        '_history_tasks', 'history_partition', 'run_development', '_run_once')
    for name in names:
        original = getattr(module, name)
        if not isinstance(original, FunctionType) or original.__closure__ is not None:
            raise ValueError('An unsupported shared function cannot be isolated')
        bound = FunctionType(original.__code__, globals(), name, original.__defaults__)
        bound.__kwdefaults__ = deepcopy(original.__kwdefaults__)
        globals()[name] = bound


_reuse_frozen_boundaries()


def validation_driver():
    global _DRIVER
    require(type(VALIDATOR_SHA256) is str and re.fullmatch('[0-9a-f]{64}', VALIDATOR_SHA256)
        and reference(VALIDATOR)['sha256'] == VALIDATOR_SHA256,
        'The exact new native cold validator must be frozen before development admission')
    require(all(reference(path)['sha256'] == digest for path, digest in NATIVE_DEPENDENCIES.items()),
        'The complete native task module and fixed prospective configuration changed')
    if _DRIVER is None:
        descriptor = importlib.util.spec_from_file_location('_heterogeneous_native_development_cold_validator', VALIDATOR)
        _DRIVER = importlib.util.module_from_spec(descriptor)
        descriptor.loader.exec_module(_DRIVER)
    require(callable(getattr(_DRIVER, 'validate_completed', None)) and _DRIVER.ACTUAL_KIND == ACTUAL_KIND
        and _DRIVER.task.MATERIAL_KIND == MATERIAL_KIND and type(_DRIVER.task.VERSION) is int and _DRIVER.task.VERSION == NATIVE_VERSION,
        'The genuine new completed validator and material namespace are required')
    return _DRIVER


def _native_recipe_bindings(records):
    require(type(records) is dict and bool(records), 'The native recipe reference map is required')
    result = {}
    for name, record in records.items():
        require(type(name) is str, 'A native recipe name must identify its referenced path')
        bound = checked(record)
        path = Path(name) if Path(name).is_absolute() else ROOT/name
        require(path.resolve() == Path(bound['path']), 'A native recipe label differs from its complete reference')
        bind_references(bound, result)
    verify_mapping(result)
    return result


def recipes():
    driver = validation_driver()
    from sheets_factory.evaluation import native_transport_frontier
    native_transport_frontier.adapted_ast()
    files = [Path(__file__), SHARED, SHARED.with_name('prepare_linear_capital_development.py'),
        VALIDATOR, *map(Path, NATIVE_DEPENDENCIES), Path(native_transport_frontier.__file__), PROFILE_PATH,
        ROOT/'src/sheets_factory/evaluation/clock_resource_frontier.py',
        ROOT/'src/sheets_factory/evaluation/tool_time_clock_bounds.py',
        ROOT/'src/sheets_factory/evaluation/resource_frontier.py', ROOT/'src/sheets_factory/evaluation/frontier.py',
        ROOT/'src/sheets_factory/evaluation/resource_harbor.py',
        ROOT/'src/sheets_factory/evaluation/thread_capped_harbor_export.py',
        ROOT/'src/sheets_factory/evaluation/resource_streaming_verifier.py',
        ROOT/'src/sheets_factory/evaluation/resource_observer.py',
        ROOT/'src/sheets_factory/task_adapters/heterogeneous_formula_identity.py']
    inherited = _native_recipe_bindings(driver.task.recipes())
    return {**inherited, **{str(path.resolve()): reference(path)['sha256'] for path in files}}


def bind_evidence(value, mapping, seen=None):
    """Bind the full native evidence graph; large payloads remain complete SHA leaves."""
    seen = set() if seen is None else seen
    if isinstance(value, dict):
        if set(value) == {'path', 'sha256', 'bytes'}:
            record = checked(value)
            bind_references(record, mapping)
            if record['path'] not in seen and Path(record['path']).suffix.lower() == '.json' and record['bytes'] <= 2*1024**2:
                seen.add(record['path'])
                bind_evidence(json.loads(Path(record['path']).read_bytes()), mapping, seen)
        else:
            for child in value.values():
                bind_evidence(child, mapping, seen)
    elif isinstance(value, (list, tuple)):
        for child in value:
            bind_evidence(child, mapping, seen)


def material_identity(actual, plan, delta):
    content = {'version': 1, 'mode': actual['mode'],
        'input_definitions': workbook_identity(actual['input']['path'], formulas=True),
        'input_values': workbook_identity(actual['input']['path']),
        'goal_values': workbook_identity(actual['goal']['path']),
        'instruction_sha256': actual['instruction']['sha256'],
        'scope_sha256': canonical({'financial_scope': plan['financial_scope'],
            'faults': plan['faults'], 'complete_expected_changes': delta['expected_changes']})}
    return {**content, 'sha256': canonical(content)}


def _same_content(previous, current):
    keys = ('mode', 'input_definitions', 'input_values', 'goal_values', 'instruction_sha256')
    return all(key in previous and previous[key] == current[key] for key in keys)


def selection_history(identity, roots=None):
    records, seen = [], set()
    for root in HISTORY_ROOTS if roots is None else roots:
        root = Path(root).absolute()
        require(root == root.resolve(), 'History roots must be real paths')
        if not root.exists():
            continue
        for path in sorted(root.rglob('selection_manifest.json')):
            if str(path) in seen:
                continue
            seen.add(str(path))
            selection = read(path)
            model, tasks = _history_tasks(selection)
            if model and 'source_manifest' in selection:
                # Bind every declared source, including the other mode's history.
                # Missing source metadata is legacy-compatible; malformed metadata
                # cannot turn a recorded identity into an unknown prior attempt.
                _historical_reference(selection['source_manifest'])
            for task in tasks if model else ():
                if task.get('mode') != identity['mode']:
                    continue
                previous = _historical_identity(selection, task)
                if previous is not None:
                    require(previous['sha256'] != identity['sha256'] and not _same_content(previous, identity),
                        'This material already has a model selection; do not resample or rename it')
                directory = task.get('task_directory')
                if directory:
                    folder = Path(directory)
                    instruction = folder/'instruction.md'
                    if instruction.is_file() and reference(instruction)['sha256'] == identity['instruction_sha256']:
                        source, goal = folder/'environment/input.xlsx', folder/'tests/reference.xlsx'
                        require(source.is_file() and goal.is_file(), 'Matching historical material is missing')
                        same = workbook_identity(source, formulas=True) == identity['input_definitions'] \
                            and workbook_identity(source) == identity['input_values'] and workbook_identity(goal) == identity['goal_values']
                        require(not same, 'Equivalent historical material already has a selection; no resampling')
            records.append(reference(path))
    return records


def checked_material(validation_manifest):
    actual_ref = checked(validation_manifest)
    actual = validation_driver().validate_completed(actual_ref)  # Real cold validation; persisted flags do not replace it.
    require(actual.get('kind') == ACTUAL_KIND and type(actual.get('version')) is int and actual['version'] == NATIVE_VERSION
        and actual.get('status') == 'passed' and actual.get('qualified') is False
        and actual.get('mode') in ('financial_modeling', 'debugging'), 'Only the genuine new actual native task validation qualifies')
    material_ref, preparation_ref = checked(actual['material']), checked(actual['preparation'])
    material, preparation = read(material_ref), read(preparation_ref)
    raw_material = read(preparation['material'])
    completed_material = {**raw_material, 'public_input': actual['input'], 'private_goal': actual['goal'],
        'expected_delta': actual['complete_actual_D'], 'raw_public_input': raw_material['public_input'],
        'actual_validation_completed': True}
    require(material.get('kind') == MATERIAL_KIND and type(material.get('version')) is int and material['version'] == NATIVE_VERSION
        and material.get('qualified') is False and type(material.get('module_count')) is int and material['module_count'] == 8
        and preparation.get('kind') == PREPARED_KIND and type(preparation.get('version')) is int and preparation['version'] == NATIVE_VERSION
        and preparation.get('phase') == 'development' and preparation.get('maximum_external_LO_calls') == 7
        and type(preparation.get('outer_retries')) is int and preparation['outer_retries'] == 0
        and material == completed_material
        and actual['mode'] == material['mode'] == preparation['mode'], 'The old, partial, or foreign material namespace is forbidden')
    source_ref = checked(actual['source_presentation'])
    require(Path(source_ref['path']).suffix.lower() == '.xlsx'
        and source_ref == material['source_presentation'] == preparation['source_presentation']
        and material['instruction'] == actual['instruction'] == preparation['instruction']
        and all(material[key] == raw_material[key] for key in
            ('kind', 'version', 'mode', 'instruction', 'review_scope', 'source_presentation', 'source_lineage', 'module_count', 'qualified'))
        and material['raw_public_input'] == raw_material['public_input'] == preparation['input'] == actual['raw_input']
        and material['public_input'] == actual['input'] and material['private_goal'] == actual['goal']
        and material['expected_delta'] == actual['expected_delta'] == actual['complete_actual_D']
        and material.get('actual_validation_completed') is True,
        'The genuine source presentation, material or instruction ancestry changed')
    for key in ('input', 'goal', 'instruction', 'expected_delta', 'independent_scope_coverage',
                'complete_actual_D', 'controls', 'stability', 'runtime_profile'):
        checked(actual[key])
    plan = read(material['review_scope'])
    require(plan['mode'] == actual['mode'] and preparation['plan'] == material['review_scope']
        and len(plan['financial_scope']) == 766 and len({tuple(x) for x in plan['financial_scope']}) == 766,
        'Exactly the original complete independent766 scope is required')
    coverage = read(actual['independent_scope_coverage'])
    require(coverage.get('passed') is True and len(coverage['expected_typed_values']) == 766
        and {(row['sheet'], row['cell']) for row in coverage['expected_typed_values']} == {tuple(point) for point in plan['financial_scope']}
        and actual['independent_scope_coverage'] == preparation['independent_scope_coverage'],
        'The complete independent financial scope must pass its genuine native validator')
    alias_ref = checked(actual['text_alias_cache_proof'])
    alias = read(alias_ref)
    expected_aliases = {
        'H6': ('G10', 'Margins improve, aided by cloud business & continued economies of scale.',
            'Operating margin remains at the stated base-year level.'),
        'K6': ('G12', "Maintained at Amazon's current level",
            'Given industry sales / capital; terminal reinvestment rate.'),
    }
    aliases = alias['aliases']
    require(alias_ref == preparation['text_alias_cache_proof']
        and alias.get('kind') == 'declared_two_direct_text_alias_cache_transfers'
        and type(alias.get('version')) is int and alias['version'] == NATIVE_VERSION
        and alias['source'] == preparation['source'] and alias['presentation'] == source_ref
        and type(alias.get('numeric_caches_changed')) is int and alias['numeric_caches_changed'] == 0
        and alias.get('all_other_cell_subtrees_unchanged_except_six_literals_and_two_caches') is True
        and type(aliases) is list and len(aliases) == 2 and {row['cell'] for row in aliases} == set(expected_aliases),
        'Only the corrected v2 two-alias text cache transfer proof is permitted')
    for row in aliases:
        target, old, new = expected_aliases[row['cell']]
        require(row['sheet'] == 'DCF - Valuation as picture' and row['source_sheet'] == 'DCF - Stories to Numbers'
            and row['source_cell'] == target and row['unchanged_direct_formula'] == "'DCF - Stories to Numbers'!"+target
            and row['original_typed_cache'] == {'type': 'string', 'value': old}
            and row['expected_typed_cache'] == {'type': 'string', 'value': new}
            and row.get('outside_financial_scope766') is True and row.get('formula_preserved') is True
            and (row['sheet'], row['cell']) not in {tuple(point) for point in plan['financial_scope']},
            'An undeclared alias cache, formula, text or financial expectation changed')
    controls = read(actual['controls'])
    require(controls.get('kind') == 'heterogeneous_review_five_actual_controls'
        and type(controls.get('version')) is int and controls['version'] == NATIVE_VERSION
        and controls.get('passed') is True and controls.get('rewards') == CONTROL_REWARDS
        and all(type(controls['rewards'][name]) is int for name in CONTROL_REWARDS),
        'All five complete actual controls are required')
    calls = actual['actual_LO_calls']
    require(type(calls) is list and len(calls) == 7 and all(call.get('completed') is True for call in calls)
        and [call['index'] for call in calls] == list(range(1, 8))
        and [call['stage'] for call in calls] == ['input1', 'input2', 'goal1', 'goal2', 'equivalent', 'missed_root', 'extra_change']
        and calls[0]['output'] == actual['input'] and calls[2]['output'] == actual['goal'],
        'Exactly seven normal actual calculations and stable export bytes are required')
    delta = read(actual['complete_actual_D'])
    changes = delta['expected_changes']
    labels = [row['sheet']+'!'+row['cell'] for row in changes]
    require(delta.get('kind') == 'complete_heterogeneous_review_task_actual_D'
        and type(delta.get('version')) is int and delta['version'] == NATIVE_VERSION and delta['mode'] == actual['mode']
        and type(delta.get('actual_change_count')) is int and delta['actual_change_count'] == len(changes) > 0
        and len(set(labels)) == len(labels) and delta.get('all_independently_covered') is True
        and delta.get('all_eight_families_nonempty') is True and len(delta['family_effect_counts']) == 8
        and all(type(count) is int and count > 0 for count in delta['family_effect_counts'].values())
        and delta.get('known_protected_points_disjoint') is True and delta.get('full_sparse_union_compared') is True,
        'The entire actual D must be nonempty, independently covered and complete')
    observed = compare_workbooks(actual['input']['path'], actual['goal']['path'], actual['goal']['path'])
    require(observed.get('reward') == 1 and observed.get('structure_ok') is True
        and observed['expected_changes'] == sorted(labels),
        'The exported stable input/goal bytes must reproduce the complete actual D')
    require(all(actual.get(key) is False for key in
        ('source_admitted', 'normal_12QA_passed', 'public_recovery_passed', 'Harbor_passed', 'final20_qualified'))
        and all(type(actual.get(key)) is int and actual[key] == 0 for key in
            ('model_calls', 'solver_calls', 'Harbor_calls', 'outer_retries')),
        'Engineering validation cannot inherit normal quality, source or model qualification')
    profile_ref = checked(actual['runtime_profile'])
    profile = load_runtime_profile(profile_ref['path'])
    require(profile['image']['id'] == 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
        and all(profile['docker_resources'][role] == {'cpus': 2, 'memory_bytes': 32*1024**3, 'pids_limit': 256}
            for role in ('source', 'agent', 'verifier')), 'The pinned same2CPU32GiB resource contract changed')
    identity = material_identity(actual, plan, delta)
    return {'actual_ref': actual_ref, 'actual': actual, 'material_ref': material_ref, 'material': material,
        'preparation_ref': preparation_ref, 'preparation': preparation, 'source_ref': source_ref,
        'plan': plan, 'delta': delta, 'alias_ref': alias_ref, 'profile_ref': profile_ref, 'profile': profile, 'identity': identity}


def _prepare(validation_manifest, output):
    output = Path(output).absolute()
    require(output == output.resolve() and not output.exists(), 'Use a fresh real development directory')
    evidence = checked_material(validation_manifest)
    actual, identity = evidence['actual'], evidence['identity']
    history = selection_history(identity)
    bindings = recipes()
    bind_evidence([evidence['actual_ref'], evidence['material_ref'], evidence['preparation_ref']], bindings)
    bind_references(history, bindings)
    output.mkdir(parents=True)
    task_id = ('fm' if actual['mode'] == 'financial_modeling' else 'dbg')+'-heterogeneous-native-'+identity['sha256'][:16]
    task = output/'task'
    (task/'public').mkdir(parents=True)
    (task/'private').mkdir()
    for record, destination in [(actual['input'], task/'public/input.xlsx'), (actual['goal'], task/'private/goal.xlsx'),
            (actual['instruction'], task/'public/instruction.md')]:
        checked(record)
        shutil.copyfile(record['path'], destination)
        require(reference(destination)['sha256'] == record['sha256'], 'The copied task differs from the actual validated bytes')
    base = write(output/'actual_local_base_image.json', verify_local_base_image(evidence['profile_ref']['path']))
    metadata = {'task_id': task_id, 'mode': actual['mode'], 'source_id': evidence['source_ref']['sha256'],
        'source_kind': KIND, 'revision': 0, 'revision_hash': identity['sha256'],
        'difficulty_status': 'prequality_development_probe', 'base_image': evidence['profile']['image']['id'], CAP_FIELD: CAP_VALUE}
    exported = output/'SpreadsheetEval'/task_id
    audit_path = output/'thread_cap_export_audit.json'
    export_resource_harbor(task, exported, metadata, ROOT, runtime_profile=evidence['profile_ref']['path'], audit_path=audit_path)
    cap_audit = reference(audit_path)
    export_binding = inspect_resource_export(exported, audit_path=cap_audit)
    inventory = {path.relative_to(exported).as_posix(): reference(path) for path in exported.rglob('*') if path.is_file()}
    require(set(inventory) == set(TASK_FILES) and len(inventory) == 17, 'Exactly all17 standard export files are mandatory')
    require((exported/'instruction.md').read_bytes() == Path(actual['instruction']['path']).read_bytes()
        and reference(exported/'environment/input.xlsx')['sha256'] == actual['input']['sha256']
        and reference(exported/'tests/reference.xlsx')['sha256'] == actual['goal']['sha256'],
        'The public instruction/input and private reference must retain exact actual task bytes')
    bind_evidence([base, cap_audit, *inventory.values()], bindings)
    verify_mapping(bindings)
    late_history = selection_history(identity)
    require(all(record in late_history for record in history), 'Frozen historical evidence changed during export')
    bind_references(late_history, bindings)
    partition = history_partition(late_history)
    record = {**metadata, 'task_directory': str(exported), 'harbor_export_binding': export_binding,
        'local_controls': deepcopy(CONTROL_REWARDS), 'execution_budget': deepcopy(BUDGET),
        'timeout_seconds': 14400, 'tool_time_policy': deepcopy(POLICY_V3)}
    manifest = {'kind': KIND, 'schema_version': VERSION, 'family': 'heterogeneous_native_review',
        'phase': 'development', 'native_transport_profile': transport_profile(),
        'source_kind': KIND, 'frozen_at': datetime.now(timezone.utc).isoformat(),
        'source_presentation': evidence['source_ref'], 'materialized_view': evidence['material_ref'],
        'actual_task_validation': evidence['actual_ref'], 'actual_task_validation_version': NATIVE_VERSION,
        'text_alias_cache_proof': evidence['alias_ref'], 'selected_task_ids': [task_id], 'tasks': [record],
        'material_task_version': identity, 'model': MODEL, 'reasoning_effort': EFFORT,
        'execution_budget': deepcopy(BUDGET), 'timeout_seconds': 14400,
        'tool_time_policy': deepcopy(POLICY_V3), 'tool_time_policy_version': 3,
        'runtime_profile': evidence['profile_ref'], 'source_artifacts_sha256': bindings, 'recipe_sha256': recipes(),
        'resource_task_inventory': inventory, 'actual_local_base_image': base, 'thread_cap_export_audit': cap_audit,
        'actual_validation_LO_calls_retained': 7, 'independent_financial_scope_count': 766,
        'complete_changed_value_set_count': evidence['delta']['actual_change_count'],
        'local_controls': deepcopy(CONTROL_REWARDS), 'actual_Harbor_controls_status': 'pending',
        'history_roots': [str(path.resolve()) for path in HISTORY_ROOTS],
        'history_exclusion': {'path': str((ROOT/'outputs/tmp').resolve()), 'reason': 'Offline test fixtures'},
        'selection_history_inventory': late_history, 'prior_model_selection_inventory': partition['model_selections'],
        'nonmodel_preparation_inventory': partition['nonmodel_preparations'], 'quality_gates_pending': list(PENDING),
        'normal_six_nodes_executed_or_inherited': False, 'normal_ExportNode_executed': False,
        'effective_infrastructure_retries': 0, 'raw_zero_is_provisional_until_full_quality': True,
        'raw_one_stops_unchanged_version_expansion': True, 'source_financial_audit_is_not_task_quality': True,
        'qualified': False, 'task_count': 0, 'new_LO_calls': 0, 'new_optimizer_calls': 0,
        'new_model_calls': 0, 'new_Harbor_jobs': 0}
    validate_selection_execution_budget(manifest)
    return write(output/'probe_manifest.json', manifest)


def prepare(validation_manifest, output):
    existed = Path(output).exists()
    try:
        return _prepare(validation_manifest, output)
    except BaseException as error:
        path = Path(output)
        if not existed and path.is_dir() and not (path/'probe_manifest.json').exists():
            write(path/'preparation_failure.json', {'kind': KIND+'_failure', 'error_type': type(error).__name__,
                'error': str(error), 'partial_artifacts_preserved': True, 'qualified': False,
                'new_LO_calls': 0, 'new_model_calls': 0, 'new_Harbor_jobs': 0})
        raise


def validate_prepared(output):
    output = Path(output).absolute()
    require(output == output.resolve(), 'A real prepared directory is required')
    frozen = read(output/'probe_manifest.json')
    require(frozen.get('kind') == KIND and type(frozen.get('schema_version')) is int
        and frozen['schema_version'] == VERSION and frozen.get('family') == 'heterogeneous_native_review'
        and frozen['recipe_sha256'] == recipes(), 'The new native preparation or code recipe changed')
    verify_mapping(frozen['source_artifacts_sha256'])
    partition = history_partition(frozen['selection_history_inventory'])
    require(frozen['prior_model_selection_inventory'] == partition['model_selections']
        and frozen['nonmodel_preparation_inventory'] == partition['nonmodel_preparations']
        and all(frozen['source_artifacts_sha256'].get(record['path']) == record['sha256'] for record in frozen['selection_history_inventory']),
        'The complete frozen model/nonmodel history partition changed')
    evidence = checked_material(frozen['actual_task_validation'])
    actual, identity = evidence['actual'], evidence['identity']
    require(frozen['source_presentation'] == evidence['source_ref'] and frozen['materialized_view'] == evidence['material_ref']
        and frozen['material_task_version'] == identity and frozen['runtime_profile'] == evidence['profile_ref']
        and type(frozen['actual_task_validation_version']) is int and frozen['actual_task_validation_version'] == NATIVE_VERSION
        and frozen['text_alias_cache_proof'] == evidence['alias_ref'],
        'The actual source, material, resources or content identity changed')
    require(frozen['model'] == MODEL == 'gpt-6.1-sol' and frozen['reasoning_effort'] == EFFORT == 'xhigh'
        and frozen['tool_time_policy_version'] == 3 and frozen['tool_time_policy'] == POLICY_V3
        and frozen['execution_budget'] == BUDGET and frozen['timeout_seconds'] == 14400
        and type(frozen['effective_infrastructure_retries']) is int and frozen['effective_infrastructure_retries'] == 0
        and frozen['qualified'] is False and type(frozen['task_count']) is int and frozen['task_count'] == 0
        and frozen['quality_gates_pending'] == PENDING and frozen['native_transport_profile'] == transport_profile()
        and frozen['phase'] == 'development' and frozen['actual_validation_LO_calls_retained'] == 7
        and frozen['independent_financial_scope_count'] == 766
        and frozen['history_roots'] == [str(path.resolve()) for path in HISTORY_ROOTS]
        and frozen['normal_six_nodes_executed_or_inherited'] is False and frozen['normal_ExportNode_executed'] is False
        and frozen['actual_Harbor_controls_status'] == 'pending'
        and frozen['local_controls'] == CONTROL_REWARDS
        and all(type(frozen['local_controls'][key]) is int for key in CONTROL_REWARDS)
        and all(type(frozen[key]) is int and frozen[key] == 0 for key in
            ('new_LO_calls', 'new_optimizer_calls', 'new_model_calls', 'new_Harbor_jobs')),
        'The frozen one-attempt development contract changed')
    validate_selection_execution_budget(frozen)
    require(len(frozen['tasks']) == 1 and frozen['selected_task_ids'] == [frozen['tasks'][0]['task_id']], 'Only one fixed task is permitted')
    task = frozen['tasks'][0]
    task_id = ('fm' if actual['mode'] == 'financial_modeling' else 'dbg')+'-heterogeneous-native-'+identity['sha256'][:16]
    directory = output/'SpreadsheetEval'/task_id
    require(task['task_id'] == task_id and task['task_directory'] == str(directory)
        and type(task['revision']) is int and task['revision'] == 0 and task['revision_hash'] == identity['sha256']
        and task['source_id'] == evidence['source_ref']['sha256'] and task['source_kind'] == KIND
        and task['mode'] == actual['mode'] and task.get(CAP_FIELD) == CAP_VALUE
        and task['local_controls'] == CONTROL_REWARDS and all(type(task['local_controls'][key]) is int for key in CONTROL_REWARDS)
        and frozen['thread_cap_export_audit']['path'] == str(output/'thread_cap_export_audit.json')
        and task['harbor_export_binding'] == inspect_resource_export(directory, audit_path=frozen['thread_cap_export_audit']),
        'The full thread-capped export binding changed')
    current = {path.relative_to(directory).as_posix(): reference(path) for path in directory.rglob('*') if path.is_file()}
    require(set(current) == set(TASK_FILES) and current == frozen['resource_task_inventory'], 'The exact17-file export inventory changed')
    history = selection_history(identity)
    require(all(record in history for record in frozen['selection_history_inventory']), 'Frozen history is missing or changed')
    return frozen


def _reserve_first_attempt(prepared, frozen, destination, started_value):
    """Keep a durable content reservation even when the first launch fails."""
    require(bool(HISTORY_ROOTS), 'Full declared history roots are required')
    root = Path(HISTORY_ROOTS[0]).absolute()
    require(root == root.resolve(), 'The global material reservation root must be real')
    root.mkdir(parents=True, exist_ok=True)
    directory = root/'.native_development_material_reservations'
    require(directory == directory.resolve(), 'The shared material reservation directory must be real')
    directory.mkdir(exist_ok=True)
    descriptor = os.open(directory/'launch.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a') as lock:
        # Different FM/DBG materials may wait for this short registration section,
        # then execute concurrently. A same-material loser retains the winner.
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        require(validate_prepared(prepared) == frozen, 'The frozen material changed before launch registration')
        identity = frozen['material_task_version']
        current = selection_history(identity)
        require(all(record in current for record in frozen['selection_history_inventory']), 'Frozen history changed under the global lock')
        partition = history_partition(current)
        launch_value = {**started_value, 'selection_history_inventory': current,
            'prior_model_selection_inventory': partition['model_selections'],
            'nonmodel_preparation_inventory': partition['nonmodel_preparations']}
        # Paths, scope declaration names and family-version labels do not buy a new attempt.
        core = {key: identity[key] for key in ('mode', 'input_definitions', 'input_values', 'goal_values', 'instruction_sha256')}
        reservation_path = directory/(canonical(core)+'.json')
        require(not reservation_path.exists() and not reservation_path.is_symlink(),
            'Equivalent material already has a reserved first attempt; no retry or renamed snapshot is permitted')
        reservation = write(reservation_path, {'kind': KIND+'_material_first_attempt_reservation', 'version': VERSION,
            'content_material_identity': core, 'material_task_version': identity,
            'prepared_snapshot': reference(prepared/'probe_manifest.json'), 'evaluation_output': str(destination),
            'started_value': launch_value, 'selection_history_inventory': current,
            'prior_model_selection_inventory': partition['model_selections'],
            'nonmodel_preparation_inventory': partition['nonmodel_preparations'],
            'native_transport_profile': transport_profile(), 'effective_infrastructure_retries': 0, 'qualified': False})
        return write(prepared/'development_started.json', {**launch_value, 'material_reservation': reservation})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    entry = commands.add_parser('prepare')
    entry.add_argument('--validation-manifest', type=Path, required=True)
    entry.add_argument('--output', type=Path, required=True)
    entry = commands.add_parser('validate')
    entry.add_argument('--prepared', type=Path, required=True)
    entry = commands.add_parser('run-development')
    entry.add_argument('--prepared', type=Path, required=True)
    entry.add_argument('--output', type=Path, required=True)
    entry.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    if args.command == 'prepare':
        result = prepare(args.validation_manifest, args.output)
    elif args.command == 'validate':
        result = validate_prepared(args.prepared)
    else:
        require(0 <= args.port <= 65535, 'Use a valid local dashboard port')
        result = run_development(args.prepared, args.output, port=args.port)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
