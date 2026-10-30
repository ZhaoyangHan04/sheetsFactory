#!/usr/bin/env python3
"""Prepare the first fixed-plan entity source; only --run emits or recalculates.

Preparation consumes a completed forward report and a complete count-only
compiler receipt. It creates no production workbook and executes no ledger.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from uuid import uuid4

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

import openpyxl
import yaml
from sheets_factory.core.audit import AuditStore, utcnow
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.task_adapters.public_workbook_scope import checked_bytes, reference, require, write_new
from sheets_factory.task_adapters.lease_family import compare_exact_typed
from sheets_factory.workbook.entity_group.spec import load_spec
from sheets_factory.workbook.entity_group.excel import emit_entity_group_workbook
from sheets_factory.workbook.entity_group.validate import audit_entity_group_workbook
from sheets_factory.workbook.engine import LibreOfficeEngine

IMAGE = 'sheetsfactory-lo:24.2-iterative-openpyxl315-v1'
IMAGE_ID = 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
KIND = 'prepared_first_hypothetical_fixed_plan_entity_group_source'
MAX_FORMULAS = 1_000_000
MAX_FORMULA_LENGTH = 8192
CATALOG = ROOT / 'config/entity_group_catalog_v1.json'
CORE = ROOT / 'src/sheets_factory/workbook/entity_group'


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def read(record):
    value = json.loads(checked_bytes(record if isinstance(record, dict) else reference(record)))
    require(isinstance(value, dict), 'A source receipt must be a JSON object')
    return value


def load_profile(record):
    if record is None:
        return None
    from sheets_factory.workbook.resource_engine import load_runtime_profile
    profile = load_runtime_profile(yaml.safe_load(checked_bytes(record)))
    require(profile['image'] == {'tag': IMAGE, 'id': IMAGE_ID},
            'The source resource profile must retain the exact approved runtime')
    return profile


def formula_limit(profile):
    return MAX_FORMULAS if profile is None else profile['limits']['source_physical_formulas']


def recipes(profile=None):
    # Deliberately explicit: future catalog/sizing orchestration is not a new
    # numerical dependency of an already prepared financial source.
    paths = [CORE / name for name in ('__init__.py', 'spec.py', 'ledger.py', 'excel.py', 'validate.py')]
    paths += [Path(__file__).resolve(), ROOT / 'src/sheets_factory/workbook/engine.py',
        ROOT / 'src/sheets_factory/task_adapters/lease_family.py',
        ROOT / 'src/sheets_factory/task_adapters/public_workbook_scope.py',
        ROOT / 'src/sheets_factory/core/audit.py', ROOT / 'src/sheets_factory/dashboard/server.py',
        ROOT / 'src/sheets_factory/resume.py']
    if profile is not None:
        paths += [ROOT / 'src/sheets_factory/workbook/resource_engine.py']
    return {str(path): reference(path)['sha256'] for path in paths}


def check_recipes(expected, profile=None):
    require(expected == recipes(profile), 'The prepared entity financial execution recipe changed')


def track_references(value, collected=None):
    """Check declared references; do not reinterpret historical JSON receipts."""
    collected = {} if collected is None else collected
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            checked_bytes(value)
            require(value['path'] not in collected or collected[value['path']] == value['sha256'],
                    'Conflicting entity source artifact identities')
            collected[value['path']] = value['sha256']
        for child in value.values(): track_references(child, collected)
    elif isinstance(value, list):
        for child in value: track_references(child, collected)
    return collected


def validate_count_receipt(record, specification, public, profile=None):
    receipt = read(record)
    require(receipt.get('kind') == 'entity_group_G01_full_count_only_engineering'
            and receipt.get('status') == 'completed'
            and type(receipt.get('revision')) is int and receipt['revision'] >= 1,
            'A completed full first-profile count-only receipt is required')
    require(receipt['public_spec']['sha256'] == specification['sha256']
            and read(receipt['public_spec']) == public, 'The count belongs to another public specification')
    track_references(receipt)
    declared = {item['path']: item['sha256'] for item in receipt['recipe']}
    require(all(declared.get(str(CORE / name)) == reference(CORE / name)['sha256']
                for name in ('spec.py', 'excel.py')), 'The count used another schema or emitter')
    count = receipt['count']
    require(count.get('kind') == 'entity_group_complete_formula_count_only'
            and type(count.get('version')) is int and count['version'] == 1
            and count.get('dimension_mode') == 'production'
            and all(type(count.get(key)) is int and count[key] == expected for key, expected in
                    (('entity_count', 24), ('month_count', 120), ('scenario_count', 3)))
            and count.get('truncated', False) is False,
            'The complete, untruncated 24-entity/120-month/3-scenario count is required')
    limit = formula_limit(profile)
    require(type(count.get('physical_formula_count')) is int and 0 < count['physical_formula_count'] <= limit,
            'The completed compiler count exceeds the selected physical-formula admission limit')
    require(type(count.get('within_one_million_physical_formulas')) is bool
            and count['within_one_million_physical_formulas'] == (count['physical_formula_count'] <= MAX_FORMULAS),
            'The historical one-million-formula count flag contradicts the full count')
    require(type(count.get('maximum_formula_length')) is int
            and 0 < count['maximum_formula_length'] <= MAX_FORMULA_LENGTH
            and isinstance(count.get('worksheet_rows'), dict) and count['worksheet_rows']
            and all(type(value) is int and 0 < value <= 1048576 for value in count['worksheet_rows'].values()),
            'The complete count exceeds an Excel formula-length or worksheet-row limit')
    for key in ('physical_nonempty_cells', 'logical_output_binding_count', 'maximum_expression_depth',
                'public_primitive_count', 'worksheet_count', 'formula_text_characters'):
        require(type(count.get(key)) is int and count[key] > 0, 'The full count lacks ' + key)
    require(count['worksheet_count'] == len(count['worksheet_rows'])
            and count['physical_nonempty_cells'] >= count['physical_formula_count']
            and count['formula_text_characters'] >= count['physical_formula_count'],
            'The complete compiler geometry is internally inconsistent')
    for key in ('complete_expression_stream_sha256', 'complete_logical_binding_stream_sha256'):
        require(isinstance(count.get(key), str) and re.fullmatch('[0-9a-f]{64}', count[key]),
                'The full count lacks its complete expression or binding stream')
    for item in (receipt, count):
        require(item.get('production_workbook_materialized') is False and item.get('ledger_execution') is False
                and all(type(item.get(key)) is int and item[key] == 0 for key in ('LO_calls', 'model_calls', 'task_count'))
                and item.get('qualified') is False, 'Count-only provenance or zero-call status changed')
    return deepcopy(count)


def validate_catalog(record, specification, public):
    from sheets_factory.workbook.entity_group import catalog
    manifest = read(record)
    require(manifest.get('kind') == 'predeclared_entity_group_public_specs'
            and type(manifest.get('version')) is int and manifest['version'] == 1
            and manifest.get('profile_order') == [f'G{i:02d}' for i in range(1, 11)]
            and manifest.get('selection_uses_model_outcomes') is False
            and manifest.get('selected') == [] and manifest.get('qualified') is False
            and all(type(manifest.get(key)) is int and manifest[key] == 0 for key in
                    ('ledger_executions', 'workbook_engine_calls', 'model_calls', 'source_workbooks', 'task_count')),
            'The original zero-call fixed-ten entity catalog is required')
    rows = manifest['specifications']
    require([row['profile_id'] for row in rows] == manifest['profile_order']
            and manifest['catalog'] == reference(CATALOG), 'The fixed entity catalog or profile order changed')
    declared = catalog.load_catalog(CATALOG)
    require(public == catalog.build_spec('G01', declared) and rows[0]['spec']['sha256'] == specification['sha256'],
            'Only the predeclared first raw primitive specification G01 is admitted')
    for row in rows: checked_bytes(row['spec'])
    # Provenance scripts are immutable snapshots, rather than live numerical
    # dependencies. New catalog orchestration cannot invalidate source maths.
    for item in manifest['recipe']:
        checked_bytes(item['snapshot'])
        require(item['snapshot']['sha256'] == item['original']['sha256'], 'A catalog snapshot differs')
    return manifest


def validate_forward(specification, public, terminal_record, evidence_record):
    from sheets_factory.workbook.entity_group.catalog import reachability_evidence
    terminal = read(terminal_record)
    started_ref = reference(Path(terminal_record['path']).parent / 'started.json')
    started = read(started_ref)
    require(all(terminal.get(key) == value for key, value in started.items())
            and terminal.get('completed') is True and terminal.get('feasible') is True
            and terminal['source']['sha256'] == specification['sha256']
            and read(terminal['source']) == public
            and terminal.get('production_workbook_created') is False
            and terminal.get('other_profiles_executed') is False
            and all(type(terminal.get(key)) is int and terminal[key] == 0 for key in ('workbook_engine_calls', 'model_calls')),
            'The original completed, zero-workbook first-profile integer execution is required')
    for name in ('spec.py', 'ledger.py', '__init__.py'):
        snapshot = terminal['recipe'][name]; checked_bytes(snapshot)
        require(snapshot['sha256'] == reference(CORE / name)['sha256'], 'The independent ledger implementation changed')
    track_references(terminal)
    ledger = read(terminal['result']); evidence = read(evidence_record)
    require(ledger.get('kind') == 'entity_group_integer_forward_ledger'
            and ledger.get('dimension_mode') == 'production'
            and ledger.get('spec_sha256') == canonical(public) and ledger.get('fixed_plan') == public['fixed_plan']
            and ledger.get('feasible') is True and ledger.get('optimisation_performed') is False
            and set(ledger.get('scenarios', {})) == {'S01', 'S02', 'S03'}
            and all(row.get('feasible') is True and row.get('first_funding_gap') is None for row in ledger['scenarios'].values()),
            'All three complete scenarios must be feasible for the supplied fixed plan')
    reproduced = reachability_evidence(public, ledger)
    require(evidence == reproduced and evidence.get('passed') is True
            and evidence.get('feasible') is True and evidence.get('independent_financial_audit') is False
            and evidence.get('spec_sha256') == canonical(public) and evidence.get('result_sha256') == canonical(ledger),
            'All fourteen mechanisms need actual dated economic observations in the bound report')
    require(all(s.get('entity_months_checked') == 2880
                and s.get('all_entities_economically_active') is True
                and s.get('all_mechanisms_with_dated_economic_evidence') is True
                and len(s.get('mechanisms', {})) == 14
                and all(m.get('active') is True and type(m.get('count')) is int and m['count'] > 0
                        and m.get('witnesses') for m in s['mechanisms'].values())
                for s in evidence['scenarios'].values()), 'Incomplete dated entity or mechanism coverage')
    return {'terminal': terminal_record, 'started': started_ref, 'result': terminal['result'],
            'reachability': evidence_record}, ledger


def prepare(specification, output, *, catalog_manifest, forward_terminal, reachability_evidence, count_receipt,
            runtime_profile=None):
    output = Path(output).absolute()
    require(output == output.resolve() and not output.exists() and output.is_relative_to(Path('/data')),
            'Use a fresh non-symlink source directory under /data')
    spec_ref = reference(specification); public = load_spec(read(spec_ref))
    require(public['dimension_mode'] == 'production' and len(public['entities']) == 24
            and len(public['months']) == 120 and len(public['scenarios']) == 3,
            'Only the complete production dimensions are admitted')
    profile_ref = reference(runtime_profile) if runtime_profile is not None else None
    profile = load_profile(profile_ref)
    frozen_recipe = recipes(profile)
    catalog_ref, terminal_ref, evidence_ref, count_ref = map(reference,
        (catalog_manifest, forward_terminal, reachability_evidence, count_receipt))
    count = validate_count_receipt(count_ref, spec_ref, public, profile)
    catalog = validate_catalog(catalog_ref, spec_ref, public)
    forward, _ = validate_forward(spec_ref, public, terminal_ref, evidence_ref)
    check_recipes(frozen_recipe, profile)
    output.mkdir(parents=True)
    policy = CORE / 'catalog.py'; snapshot = output / 'private/declaration_policy.py'
    snapshot.parent.mkdir(parents=True); snapshot.write_bytes(policy.read_bytes())
    specification_ref = write_new(output / 'public/spec.json', public)
    evidence = {'raw_public_specification': spec_ref, 'catalog_manifest': catalog_ref,
        'catalog_configuration': catalog['catalog'], 'forward': forward, 'count_receipt': count_ref,
        'declaration_policy_snapshot': reference(snapshot)}
    if profile_ref is not None:
        evidence['runtime_profile'] = profile_ref
    artifacts = track_references(evidence)
    track_references(read(terminal_ref), artifacts)
    track_references(read(forward['started']), artifacts)
    for row in catalog['specifications']: track_references(row['spec'], artifacts)
    for item in catalog['recipe']: track_references(item['snapshot'], artifacts)
    track_references(read(count_ref), artifacts)
    return write_new(output / 'preparation.json', {'kind': KIND, 'version': 1, 'profile_id': 'G01',
        'public_specification': specification_ref, 'public_spec_sha256': canonical(public),
        'evidence': evidence, 'artifact_sha256': artifacts, 'resource_count': count,
        'formula_admission_limit': formula_limit(profile), 'formula_length_limit': MAX_FORMULA_LENGTH,
        'runtime_profile': profile,
        'future_profile_closure_and_target_counts_not_claimed_by_source_preparation': True,
        'recipe_sha256': frozen_recipe, 'provided_plan_is_protected': True, 'optimisation_performed': False,
        'provenance': catalog['provenance'], 'synthetic_profile_count': 10, 'selected_specification_count': 1,
        'raw_ancestor_hashes_are_provenance_only_not_new_source_workbook_counts': True,
        'production_workbook_materialized': False, 'ledger_executions': 0, 'actual_LO_recalculations': 0,
        'model_calls': 0, 'quality_or_difficulty_certified': False, 'qualified': False, 'task_count': 0})


def validate_prepared(output):
    output = Path(output).absolute(); require(output == output.resolve(), 'A source directory cannot use symlinks')
    frozen = read(reference(output / 'preparation.json'))
    profile = load_profile(frozen.get('evidence', {}).get('runtime_profile'))
    require(frozen.get('kind') == KIND and type(frozen.get('version')) is int and frozen['version'] == 1
            and frozen.get('profile_id') == 'G01' and frozen.get('production_workbook_materialized') is False
            and frozen.get('provided_plan_is_protected') is True and frozen.get('optimisation_performed') is False
            and frozen.get('formula_admission_limit') == formula_limit(profile)
            and frozen.get('runtime_profile') == profile
            and frozen.get('formula_length_limit') == MAX_FORMULA_LENGTH
            and all(type(frozen.get(key)) is int and frozen[key] == 0 for key in
                    ('ledger_executions', 'actual_LO_recalculations', 'model_calls', 'task_count')),
            'An unchanged, admitted zero-workbook source preparation is required')
    check_recipes(frozen['recipe_sha256'], profile); track_references(frozen['evidence'])
    for path, digest in frozen['artifact_sha256'].items():
        require(reference(path)['sha256'] == digest, 'An admitted source evidence artifact changed')
    public = load_spec(read(frozen['public_specification']))
    require(canonical(public) == frozen['public_spec_sha256']
            and public == read(frozen['evidence']['raw_public_specification']), 'The prepared public primitives changed')
    count = validate_count_receipt(frozen['evidence']['count_receipt'], frozen['evidence']['raw_public_specification'], public, profile)
    require(count == frozen['resource_count'], 'The complete resource admission changed')
    ledger = read(frozen['evidence']['forward']['result'])
    require(ledger.get('feasible') is True and ledger.get('spec_sha256') == canonical(public)
            and canonical(ledger) == read(frozen['evidence']['forward']['reachability'])['result_sha256'],
            'The independently executed forward report changed')
    return frozen, public, ledger


@contextmanager
def data_temporary(output):
    output = Path(output).absolute(); directory = output / 'temporary'
    require(output.is_relative_to(Path('/data')) and directory == directory.resolve(), 'Source temporary files must stay under /data')
    directory.mkdir(parents=True, exist_ok=True)
    previous, existed, cache = os.environ.get('TMPDIR'), 'TMPDIR' in os.environ, tempfile.tempdir
    try:
        with tempfile.TemporaryFile(dir=directory) as stream: stream.write(b'entity-group-write-check')
        os.environ['TMPDIR'] = str(directory); tempfile.tempdir = str(directory)
        yield directory
    finally:
        if existed: os.environ['TMPDIR'] = previous
        else: os.environ.pop('TMPDIR', None)
        tempfile.tempdir = cache


@contextmanager
def phase(audit, name):
    started = time.monotonic()
    audit.task('entity-group-source', mode='source_build', status='running', node=name)
    record = audit.record('nodes', {'task_id': 'entity-group-source', 'revision': 0, 'node_id': name,
        'status': 'running', 'started_at': utcnow(), 'model_calls': 0, 'tokens': 0})
    audit.emit('source.phase.started', node_id=name, model_calls=0, tokens=0)
    try:
        yield
    except BaseException as error:
        audit.update_record('nodes', record, {'status': 'failed', 'duration_ms': round((time.monotonic() - started) * 1000),
            'error_type': type(error).__name__, 'error': str(error)})
        raise
    else:
        audit.update_record('nodes', record, {'status': 'completed', 'duration_ms': round((time.monotonic() - started) * 1000)})


def stream_sha(values):
    digest = hashlib.sha256()
    for value in values:
        digest.update(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode() + b'\n')
    return digest.hexdigest()


def validate_emission(book, binding, count, profile=None):
    formulas = binding['formula_bindings']
    actual = [cell for sheet in book for cell in sheet._cells.values() if cell.data_type == 'f']
    require(binding.get('kind') == 'entity_group_independent_excel_bindings'
            and binding.get('fixed_plan_provided_and_protected') is True
            and binding.get('optimisation_performed') is False
            and binding.get('formula_count') == len(formulas) == len(actual) == count['physical_formula_count']
            and len(binding['output_bindings']) == count['logical_output_binding_count']
            and stream_sha(formulas) == count['complete_expression_stream_sha256']
            and stream_sha(binding['output_bindings']) == count['complete_logical_binding_stream_sha256']
            and all((item['sheet'], item['cell'], item['formula'])
                    == (cell.parent.title, cell.coordinate, cell.value) for item, cell in zip(formulas, actual)),
            'The actual complete emission differs from the admitted compiler streams')
    require(sum(cell.value is not None for sheet in book for cell in sheet._cells.values()) == count['physical_nonempty_cells']
            and {sheet.title: sheet.max_row for sheet in book} == count['worksheet_rows']
            and max(map(lambda cell: len(cell.value), actual)) <= MAX_FORMULA_LENGTH
            and len(actual) <= formula_limit(profile), 'The actual workbook exceeds its admitted resource geometry')


def source_engine(profile, attempt):
    if profile is None:
        return LibreOfficeEngine(ROOT, IMAGE, 300)
    from sheets_factory.workbook.resource_engine import ResourceLibreOfficeEngine
    return ResourceLibreOfficeEngine(ROOT, profile, role='source', receipt_directory=attempt / 'resource_receipts')


def validate_resources(runtime, profile, *, completed_calls):
    """Certify only source calls whose actual containers were inspected."""
    require(runtime.get('image_id') == IMAGE_ID and runtime.get('network') == 'none',
            'The actual source runtime differs')
    if profile is None:
        return
    require(runtime.get('role') == 'source' and runtime.get('runtime_profile') == profile
            and runtime.get('requested_resources') == profile['docker_resources']['source']
            and runtime.get('agent_and_other_roles_applied_by_this_engine') is False
            and type(runtime.get('actual_calculation_calls_recorded')) is int
            and runtime['actual_calculation_calls_recorded'] == completed_calls
            and len(runtime.get('actual_resource_receipts', [])) == completed_calls,
            'The explicit source resource profile or actual call count differs')
    for record in runtime['actual_resource_receipts']:
        call = read(record)
        require(call.get('kind') == 'resource_bound_libreoffice_call'
                and call.get('status') == 'completed' and call.get('role') == 'source'
                and call.get('image_id') == IMAGE_ID and call.get('actual_resources_verified') is True
                and call.get('requested_resources') == profile['docker_resources']['source']
                and call.get('actual_resources') == {
                    'cpus_nanoseconds': profile['docker_resources']['source']['cpus'] * 10**9,
                    'memory_bytes': profile['docker_resources']['source']['memory_bytes'],
                    'pids_limit': profile['docker_resources']['source']['pids_limit']},
                'An actual source container resource receipt is missing or differs')
        track_references(call)


def _execute(output, frozen, public, ledger, attempt, audit, calls):
    profile = load_profile(frozen.get('evidence', {}).get('runtime_profile'))
    with data_temporary(output) as temporary:
        with phase(audit, 'emit_complete_fixed_plan_workbook'):
            book = openpyxl.Workbook(); book.remove(book.active)
            try:
                binding = emit_entity_group_workbook(book, public, max_formulas=formula_limit(profile), allow_production=True)
                require(binding['public_spec'] == public, 'The emitted public contract differs')
                validate_emission(book, binding, frozen['resource_count'], profile)
                raw = attempt / 'raw_source.xlsx'; book.save(raw)
            finally: book.close()
            binding_ref = write_new(attempt / 'bindings.json', binding)
        engine = source_engine(profile, attempt)
        require(engine.ensure_image() == IMAGE_ID, 'The source needs the exact pinned runtime image')
        runtime = engine.metadata()
        validate_resources(runtime, profile, completed_calls=0)
        current, versions, reports = raw, [], []
        for index in range(1, 4):
            destination = attempt / f'calculated_pass{index}.xlsx'
            call = {'index': index, 'input': reference(current), 'destination': str(destination),
                'started_at': utcnow(), 'completed': False, 'image_id': IMAGE_ID, 'network': 'none'}
            if profile is not None:
                call['runtime_profile'] = frozen['evidence']['runtime_profile']
                call['requested_source_resources'] = deepcopy(profile['docker_resources']['source'])
                call['workbook_file_timeout_seconds'] = profile['timeouts']['workbook_file_seconds']
            calls.append(call)
            call['started_receipt'] = write_new(attempt / f'engine_call{index}_started.json', call)
            with phase(audit, f'actual_LO_pass{index}'):
                started = time.monotonic()
                try:
                    actual = engine.recalculate(current, destination)
                    require(Path(actual).resolve() == destination.resolve(), 'The actual engine output destination differs')
                    if profile is not None:
                        runtime = engine.metadata()
                        validate_resources(runtime, profile, completed_calls=index)
                        call['actual_resource_receipt'] = runtime['actual_resource_receipts'][-1]
                        resource = read(call['actual_resource_receipt'])
                        require(resource['source'] == reference(current) and resource['output'] == reference(actual)
                                and resource['destination'] == str(destination.resolve()),
                                'The actual resource receipt belongs to another input or output')
                    call.update(completed=True, output=reference(actual))
                except BaseException as error:
                    call.update(error_type=type(error).__name__, error=str(error)); raise
                finally:
                    if profile is not None and 'actual_resource_receipt' not in call:
                        # Failed calculations retain the engine's independent
                        # terminal resource evidence too. Absence remains
                        # explicit; it cannot qualify a completed source.
                        try:
                            records = engine.metadata().get('actual_resource_receipts', [])
                            if len(records) == index:
                                terminal = read(records[-1])
                                require(terminal.get('destination') == str(destination.resolve()),
                                        'Failed resource evidence belongs to another calculation')
                                call['actual_resource_receipt'] = records[-1]
                        except Exception as resource_error:
                            call['resource_receipt_binding_error'] = str(resource_error)
                    call['seconds'] = time.monotonic() - started
                    call['terminal_receipt'] = write_new(attempt / f'engine_call{index}_terminal.json', call)
            with phase(audit, f'independent_full_field_audit{index}'):
                report = audit_entity_group_workbook(actual, public, ledger, binding)
                reports.append(write_new(attempt / f'financial_audit{index}.json', {'workbook': reference(actual), **report}))
                require(report.get('passed') is True and report.get('all_independent_journal_fields_covered') is True
                        and report.get('physical_formulas_checked') == binding['formula_count']
                        and report.get('all_scenarios_feasible') is True
                        and not report.get('mismatches') and not report.get('control_mismatches'),
                        'Actual caches, public primitives, definitions or complete financial coverage failed')
            versions.append(Path(actual)); current = actual
        with phase(audit, 'two_further_complete_value_stability_checks'):
            stability = {'first_against_goal': compare_exact_typed(versions[0], versions[1]),
                         'second_against_goal': compare_exact_typed(versions[0], versions[2])}
            stability['stable'] = all(row['passed'] for row in stability.values())
            stability_ref = write_new(attempt / 'stability.json', stability)
            require(stability['stable'], 'The complete actual source is not stable in both further passes')
        validate_prepared(output)
        manifest = {'kind': 'independently_verified_hypothetical_fixed_plan_entity_group_source', 'version': 1,
            'status': 'source_verified_not_task_or_difficulty_qualified', 'profile_id': 'G01',
            'workbook': reference(versions[0]), 'local_path': str(versions[0]),
            'derived_workbook_sha256': reference(versions[0])['sha256'],
            'public_specification': frozen['public_specification'], 'source_preparation': reference(output / 'preparation.json'),
            'source_recipe_sha256': frozen['recipe_sha256'], 'independent_ledger': frozen['evidence']['forward']['result'],
            'forward_execution': frozen['evidence']['forward'], 'resource_count_receipt': frozen['evidence']['count_receipt'],
            'count': frozen['resource_count'], 'bindings': binding_ref, 'financial_audits': reports,
            'financial_audit_passed': True, 'stability': stability_ref, 'engine_calls': calls, 'runtime': runtime,
            'runtime_profile': frozen.get('evidence', {}).get('runtime_profile'),
            'agent_and_verifier_resource_application_still_pending': profile is not None,
            'host_temporary_directory': str(temporary), 'provided_plan_is_protected': True,
            'optimisation_performed': False, 'entity_count': 24, 'month_count': 120, 'scenario_count': 3,
            'provenance': frozen['provenance'], 'synthetic_profile_count': 10, 'selected_specification_count': 1,
            'raw_ancestor_hashes_are_provenance_only_not_new_source_workbook_counts': True,
            'actual_LO_recalculations': 3, 'model_calls': 0, 'ledger_executions_during_build': 0,
            'task_input_and_complete_D_not_built': True, 'five_controls_recovery_quality_Harbor_pending': True,
            'quality_or_difficulty_certified': False, 'qualified': False, 'task_count': 0}
        return write_new(output / 'seed_manifest.json', manifest)


def execute_prepared(output, *, port=0):
    output = Path(output).absolute(); frozen, public, ledger = validate_prepared(output)
    require(not (output / 'seed_manifest.json').exists(), 'Never overwrite an actual verified source')
    lease = ProducerLease(output).acquire()
    attempt = output / 'private/build_attempts' / uuid4().hex
    audit, server, status, calls, started = None, None, 'failed', [], time.monotonic()
    try:
        require(not (output / 'seed_manifest.json').exists(), 'Never overwrite an actual verified source')
        attempt.mkdir(parents=True)
        audit = AuditStore(attempt / 'audit', {'id': attempt.name, 'name': 'Fixed-plan entity source engineering',
            'target_count': 0, 'status': 'running', 'producer_pid': os.getpid(), 'producer_active': True,
            'model_calls': 0, 'tokens': 0, 'qualified': False})
        server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port)
        url = server.start(); audit.update_run(dashboard_url=url)
        print(json.dumps({'source_attempt': str(attempt), 'dashboard_url': url, 'model_calls': 0, 'tokens': 0}), flush=True)
        result = _execute(output, frozen, public, ledger, attempt, audit, calls)
        status = 'source_verified'
        audit.task('entity-group-source', mode='source_build', status=status, node='completed')
        write_new(attempt / 'terminal.json', {'status': status, 'source_manifest': result, 'calls': calls,
            'seconds': time.monotonic() - started, 'engineering_time_excluded_from_solver_trial': True})
        return result
    except BaseException as error:
        if attempt.exists() and not (attempt / 'terminal.json').exists():
            write_new(attempt / 'terminal.json', {'status': 'failed', 'error_type': type(error).__name__,
                'error': str(error), 'calls': calls, 'all_partial_artifacts_preserved': True,
                'seconds': time.monotonic() - started, 'qualified': False, 'task_count': 0})
        raise
    finally:
        try:
            if audit is not None:
                try: audit.update_run(status=status, producer_active=False, wall_seconds=time.monotonic() - started)
                finally: audit.export()
        finally:
            try:
                if server is not None: server.stop()
            finally:
                try:
                    if audit is not None: audit.db.close()
                finally: lease.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('spec', 'output', 'catalog-manifest', 'forward-terminal', 'reachability-evidence', 'count-receipt', 'runtime-profile', 'prepared'):
        parser.add_argument('--' + flag, type=Path)
    parser.add_argument('--run', action='store_true'); parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    inputs = (args.spec, args.output, args.catalog_manifest, args.forward_terminal, args.reachability_evidence, args.count_receipt)
    if args.prepared:
        require(not any(inputs) and args.runtime_profile is None, 'Choose fresh preparation or an already prepared source')
        if args.run: result = execute_prepared(args.prepared, port=args.port)
        else:
            validate_prepared(args.prepared)
            result = {'validated': str(args.prepared), 'production_workbooks_created': 0, 'LO_calls': 0, 'model_calls': 0}
    else:
        require(not args.run and all(inputs), 'Prepare all frozen source evidence before explicit --prepared --run')
        result = prepare(args.spec, args.output, catalog_manifest=args.catalog_manifest,
            forward_terminal=args.forward_terminal, reachability_evidence=args.reachability_evidence,
            count_receipt=args.count_receipt, runtime_profile=args.runtime_profile)
    print(json.dumps(result, indent=2)); return 0


if __name__ == '__main__': raise SystemExit(main())
