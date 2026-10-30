#!/usr/bin/env python3
"""Prepare the fixed ten V3 engineering sources; execution requires --run."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from sheets_factory.core.audit import AuditStore, utcnow
from sheets_factory.dashboard import DashboardServer
from sheets_factory.pipelines.semantic_graph_admission import (
    JOINT_METHOD, PROVIDER_ID, SOURCE_ADAPTER, SOURCE_KIND, node_binding,
    validate_seed, validate_setting,
)
from sheets_factory.pipelines.scc_activity_admission import validate_scope_inventory
from sheets_factory.task_adapters.composite_semantic_family_v3 import validate_policy
from sheets_factory.task_adapters.public_input_priority import (
    canonical, checked, read, ref, require, sha, write,
)

ORDER = (
    'C01-cpi-cap-preference', 'C02-interest-cap-tax-transfer',
    'C06-reserve-claim-haircut', 'C07-premises-extension-variable-tail',
    'C08-fifo-lag-lp-share', 'C09-early-disallowance-current-tax',
    'C10-dsra-fixed-step-gp-catchup', 'C11-capital-split-capped-rent',
    'C12-equipment-shorter-tail', 'C13-nominal-inflation-loss-boundary',
)
PREPARED_KIND = 'prepared_fixed_ten_semantic_graph_v3_engineering_batch'
POOL_KIND = 'semantic_graph_v3_fixed_ten_engineering_seed_pool'
WORKER = ROOT / 'scripts/prepare_semantic_graph_engineering.py'
PROVIDER = ROOT / 'src/sheets_factory/task_adapters/composite_semantic_family_v3.py'
SOURCE_KEYS = ('source', 'source_manifest', 'scope_inventory',
               'financial_admission', 'public_input_priority_audit')


def recipe_files():
    """Bind this entry and its existing execution/admission implementations."""
    names = (
        'scripts/prepare_semantic_graph_engineering.py',
        'src/sheets_factory/pipelines/semantic_graph_admission.py',
        'src/sheets_factory/pipelines/scc_activity_admission.py',
        'src/sheets_factory/pipelines/presented_numeric_timing.py',
        'src/sheets_factory/pipelines/joint_repair_activity.py',
        'src/sheets_factory/task_adapters/composite_semantic_family_v3.py',
        'src/sheets_factory/task_adapters/composite_full_family_v2.py',
        'src/sheets_factory/task_adapters/lease_family.py',
        'src/sheets_factory/task_adapters/public_input_priority.py',
        'src/sheets_factory/workbook/engine.py',
        'src/sheets_factory/workbook/profile.py',
        'src/sheets_factory/workbook/compare.py',
    )
    paths = [Path(__file__).resolve(), *(ROOT / name for name in names)]
    return {str(path): sha(path) for path in paths}


def _checked(record, artifacts=None):
    path = checked(record)
    if 'bytes' in record:
        require(type(record['bytes']) is int and record['bytes'] == path.stat().st_size,
                'A declared source artifact byte count differs')
    if artifacts is not None:
        key = str(path)
        require(key not in artifacts or artifacts[key] == record['sha256'],
                'A path has conflicting frozen identities')
        artifacts[key] = record['sha256']
    return path


def _indexed(rows, order, label):
    require(isinstance(rows, list) and len(rows) == len(order)
            and [row.get('profile_id') for row in rows] == list(order),
            label + ' must contain the complete predeclared source order')
    return {row['profile_id']: row for row in rows}


def _same_artifact(left, right):
    """Older refs omit optional byte counts; both still require exact SHA/path."""
    return _checked(left) == _checked(right) and left['sha256'] == right['sha256']


def _check_hashes(frozen):
    for group in ('source_artifacts_sha256', 'recipe_sha256'):
        for path, digest in frozen[group].items():
            require(sha(path) == digest, 'A frozen batch artifact changed: ' + path)
    require(frozen['recipe_sha256'] == recipe_files(),
            'The prepared batch execution or admission recipe changed')


def prepare(output, source_foundation_index, offline_batch_manifest, policy_file, *, workers=2):
    """Freeze all ten inputs without launching a process, engine or model."""
    output = Path(output).resolve()
    require(not output.exists(), 'Use a fresh batch output directory')
    require(type(workers) is int and 1 <= workers <= 2, 'Engineering workers must be 1 or 2')
    artifacts = {}
    foundation_ref, offline_ref, policy_ref = map(ref, (
        source_foundation_index, offline_batch_manifest, policy_file))
    for record in (foundation_ref, offline_ref, policy_ref):
        _checked(record, artifacts)
    foundation, offline, policy = map(read, (foundation_ref, offline_ref, policy_ref))
    validate_policy(policy)
    require(foundation.get('kind') == 'source_foundation_bindings_only_no_question_admission'
            and foundation.get('original_order') == list(ORDER)
            and foundation.get('source_original_ancestors') == 2
            and foundation.get('derived_presentation_source_count') == 10,
            'The source foundation is not the original fixed ten-source pool')
    source_rows = _indexed(foundation.get('source_bindings'), ORDER, 'Source foundation')
    batch_ref = foundation['batch_manifest']
    source_batch = read(batch_ref)
    _checked(batch_ref, artifacts)
    require(source_batch.get('status') == 'source_foundation_batch_complete'
            and source_batch.get('original_order') == list(ORDER)
            and source_batch.get('source_failures') == [],
            'The existing source certification batch is incomplete')
    handoffs = _indexed(source_batch.get('certified_sources'), ORDER, 'Certified handoffs')
    originals = _indexed(source_batch.get('profiles'), ORDER, 'Original source lineage')
    require(offline.get('kind') == 'offline_v3_complete_scope_compile_batch'
            and offline.get('all_complete') is True
            and offline.get('original_order') == ['PRIMARY', *ORDER]
            and offline.get('policy') == policy,
            'The original complete V3 compilation batch or policy differs')
    reports = _indexed(offline.get('results'), ('PRIMARY', *ORDER), 'Offline reports')
    cases = []
    for profile in ORDER:
        row, result = source_rows[profile], reports[profile]
        require(set(row) == {'profile_id', *SOURCE_KEYS}, 'Unexpected source-binding schema')
        source = {key: deepcopy(row[key]) for key in SOURCE_KEYS}
        for record in source.values():
            _checked(record, artifacts)
        handoff_ref = handoffs[profile]['handoff']
        handoff = read(handoff_ref)
        _checked(handoff_ref, artifacts)
        require(handoff.get('source_binding') == source,
                'The source handoff differs from the certified index')
        report_ref = result['compilation']
        report = read(report_ref)
        _checked(report_ref, artifacts)
        inventory = read(source['scope_inventory'])
        require(result.get('offline_compile_complete') is True
                and result.get('unsatisfied_root_count') == 0
                and result.get('root_count') == result.get('compiled_root_count')
                and report.get('offline_compile_complete') is True
                and report.get('adapter') == PROVIDER_ID
                and report.get('source') == source['source']
                and report.get('policy') == policy
                and report.get('scope_inventory_sha256') == canonical(inventory)
                and type(result.get('root_count')) is int and result['root_count'] > 0
                and report.get('root_count') == result['root_count']
                and report.get('compiled_root_count') == result['root_count']
                and len(report.get('edits', [])) == result['root_count']
                and report.get('unsatisfied_roots') == []
                and report.get('family_count') == result.get('family_count') == 879
                and canonical(report['edits']) == result.get('edits_sha256') == report.get('edits_sha256'),
                'A source lacks its complete unchanged V3 compilation')
        validate_scope_inventory(inventory, report['edits'])
        require(_same_artifact(report['mutation_provider_recipe']['mutation_provider'], ref(PROVIDER)),
                'The offline report was produced by another mutation provider')
        for record in report['mutation_provider_recipe'].values():
            _checked(record, artifacts)
        financial = read(source['financial_admission'])
        original = originals[profile]['original_source']
        _checked(original, artifacts)
        original_manifest = financial['original_manifest']
        _checked(original_manifest, artifacts)
        require(financial.get('source') == source['source']
                and financial.get('original_source') == original,
                'Original financial source ancestry is not explicitly bound')
        cases.append({'profile_id': profile, 'source_handoff': handoff_ref,
            'source_binding': source, 'offline_compilation': report_ref,
            'original_source': original, 'original_source_manifest': original_manifest,
            'root_count': result['root_count'], 'edits_sha256': result['edits_sha256'],
            'case_directory': str(output / 'cases' / profile / 'engineering')})
    require(len({case['source_binding']['source']['sha256'] for case in cases}) == 10,
            'The declared ten presented source hashes must be distinct')
    frozen = {'kind': PREPARED_KIND, 'version': 1, 'prepared_at': utcnow(),
        'source_foundation_index': foundation_ref, 'offline_batch_manifest': offline_ref,
        'policy': policy_ref, 'workers': workers, 'profile_order': list(ORDER),
        'original_source_order': [case['original_source']['sha256'] for case in cases],
        'presented_source_order': [case['source_binding']['source']['sha256'] for case in cases],
        'count': 10, 'cases': cases, 'source_original_ancestors': 2,
        'derived_presentation_source_count': 10,
        'total_physical_roots': sum(case['root_count'] for case in cases),
        'source_artifacts_sha256': artifacts, 'recipe_sha256': recipe_files(),
        'planned_actual_LO_calls': 20, 'actual_LO_calls': 0, 'actual_model_calls': 0,
        'no_filter_subset_or_replacement': True, 'qualified': False, 'task_count': 0}
    output.mkdir(parents=True)
    write(output / 'frozen_inventory.json', frozen)
    return ref(output / 'frozen_inventory.json')


def validate_prepared(output):
    output = Path(output).resolve()
    frozen = read(ref(output / 'frozen_inventory.json'))
    require(frozen.get('kind') == PREPARED_KIND and frozen.get('version') == 1
            and frozen.get('count') == 10 and frozen.get('profile_order') == list(ORDER)
            and type(frozen.get('workers')) is int and 1 <= frozen['workers'] <= 2
            and frozen.get('source_original_ancestors') == 2
            and frozen.get('derived_presentation_source_count') == 10
            and frozen.get('planned_actual_LO_calls') == 20
            and frozen.get('actual_LO_calls') == frozen.get('actual_model_calls') == 0
            and frozen.get('qualified') is False and frozen.get('task_count') == 0,
            'Unexpected fixed-ten V3 engineering preparation')
    _indexed(frozen['cases'], ORDER, 'Frozen engineering cases')
    require([case['original_source']['sha256'] for case in frozen['cases']] == frozen['original_source_order']
            and [case['source_binding']['source']['sha256'] for case in frozen['cases']] == frozen['presented_source_order']
            and len(set(frozen['presented_source_order'])) == 10
            and sum(case['root_count'] for case in frozen['cases']) == frozen['total_physical_roots']
            and all(case['case_directory'] == str(output / 'cases' / case['profile_id'] / 'engineering')
                    for case in frozen['cases']),
            'The fixed-ten source identity, root scope or output path changed')
    _check_hashes(frozen)
    return frozen


def _entry(case, policy_ref):
    directory = Path(case['case_directory'])
    probe_ref = ref(directory / 'engineering_receipt.json')
    probe = read(probe_ref)
    binding = deepcopy(case['source_binding'])
    binding.update(kind='financial_source_with_separate_semantic_mutation_provider',
        source_presentation_adapter=SOURCE_ADAPTER,
        mutation_provider=deepcopy(probe['mutation_provider']),
        root_count=case['root_count'], edits_sha256=case['edits_sha256'],
        engineering_execution_recipe=ref(directory / 'recipe_start.json'))
    require(_same_artifact(probe['mutation_provider']['policy'], policy_ref)
            and _same_artifact(probe['mutation_provider']['offline_compilation'], case['offline_compilation']),
            'An actual engineering case used another declared policy or offline report')
    source = binding['source']
    entry = {'source_kind': SOURCE_KIND, 'local_path': str(checked(source)),
        'sha256': source['sha256'], 'modes': ['debugging'], 'variant': 0,
        'profile_id': case['profile_id'], 'original_source': deepcopy(case['original_source']),
        'original_source_manifest': deepcopy(case['original_source_manifest']),
        'source_manifest': binding['source_manifest'], 'mutation_provider': binding['mutation_provider'],
        'semantic_graph_binding': binding, 'engineering_probe': probe_ref,
        'finance_evidence': {'ancestor_recipe_snapshots': {}}}
    return entry, binding


def _validate_entries(frozen):
    entries, bindings = [], {}
    for case in frozen['cases']:
        entry, binding = _entry(case, frozen['policy'])
        entries.append(entry)
        bindings[entry['sha256']] = binding
    return entries, {'kind': 'semantic_graph_v3_source_and_provider_bindings',
                     'version': 1, 'sources': bindings}


def _complete_evidence(entry, proof):
    binding = entry['semantic_graph_binding']
    financial = read(binding['financial_admission'])
    manifest = read(binding['source_manifest'])
    entry['finance_evidence'].update(financial_seed_verified=True,
        financial_modeling_eligible=False, debugging_eligible=True,
        source_business_issues=[], source_presentation_adapter=SOURCE_ADAPTER,
        mutation_provider=entry['mutation_provider'], semantic_graph_binding=binding,
        audited_source_binding=proof, full_graph_financial_admission=binding['financial_admission'],
        source_manifest=binding['source_manifest'], public_scenarios=manifest['public_scenarios'],
        source_stability=financial['actual_stability'],
        independent_financial_audits=financial['original_independent_audits'],
        complete_independent_reference_audits=financial['original_independent_audits'],
        financial_validation_method=financial['financial_validation_method'])


def _run_case(case, frozen, audit):
    directory = Path(case['case_directory'])
    parent = directory.parent
    parent.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, str(WORKER), '--output', str(directory),
        '--source-handoff', str(checked(case['source_handoff'])),
        '--offline-report', str(checked(case['offline_compilation'])),
        '--policy', str(checked(frozen['policy'])), '--port', '0']
    environment = os.environ.copy()
    environment['TMPDIR'] = str(directory / 'temporary')
    record = {'profile_id': case['profile_id'], 'started_at': utcnow(),
        'command': command, 'temporary_directory': environment['TMPDIR'], 'completed': False}
    write(parent / 'worker_start.json', record)
    audit.emit('batch.case.started', profile_id=case['profile_id'], output=str(directory))
    started = time.monotonic()
    try:
        _check_hashes(frozen)
        with (parent / 'worker.stdout.jsonl').open('x') as stdout, (parent / 'worker.stderr.txt').open('x') as stderr:
            result = subprocess.run(command, cwd=ROOT, env=environment, stdout=stdout, stderr=stderr, check=False)
        record.update(returncode=result.returncode, completed_at=utcnow(),
                      elapsed_seconds=time.monotonic() - started)
        require(result.returncode == 0, 'The frozen per-source engineering worker failed')
        entry, _ = _entry(case, frozen['policy'])
        probe = read(entry['engineering_probe'])
        record.update(completed=True, engineering_receipt=entry['engineering_probe'],
            actual_LO_calls=probe['actual_LO_recalculations'])
    except Exception as error:
        record.update(completed=False, completed_at=utcnow(),
            elapsed_seconds=time.monotonic() - started,
            error_type=type(error).__name__, error=str(error))
    write(parent / 'worker_terminal.json', record)
    audit.emit('batch.case.completed' if record['completed'] else 'batch.case.failed',
               profile_id=case['profile_id'], receipt=ref(parent / 'worker_terminal.json'))
    audit.export()
    return record


def _execution_counts(frozen):
    calls, unknown = [], []
    for case in frozen['cases']:
        path = Path(case['case_directory']) / 'engine_calls.json'
        if path.is_file():
            try:
                rows = json.loads(path.read_text())
                require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows),
                        'Malformed engine call records')
                calls.extend({'profile_id': case['profile_id'], **call} for call in rows)
            except (ValueError, TypeError, OSError):
                unknown.append(case['profile_id'])
        elif path.parent.parent.joinpath('worker_start.json').exists():
            unknown.append(case['profile_id'])
    return {'attempted_actual_LO_calls': None if unknown else len(calls),
        'known_attempted_actual_LO_calls': len(calls),
        'engine_call_record_unknown_profiles': unknown,
        'completed_actual_LO_calls': sum(call.get('completed') is True for call in calls),
        'known_completed_LO_duration_seconds': sum(call['duration_seconds'] for call in calls
            if call.get('completed') is True and type(call.get('duration_seconds')) in (int, float)),
        'LO_duration_unknown_count': sum(type(call.get('duration_seconds')) not in (int, float) for call in calls)}


def execute_prepared(output, *, port=0):
    """Run exactly one attempt per declared source, without selecting a subset."""
    output = Path(output).resolve()
    frozen = validate_prepared(output)
    require(not (output / 'run.sqlite').exists() and not (output / 'batch_manifest.json').exists(),
            'This immutable engineering batch has already started')
    require(all(not Path(case['case_directory']).parent.exists() for case in frozen['cases']),
            'A declared worker output already exists; use a fresh batch')
    audit = AuditStore(output, {'id': output.name, 'kind': PREPARED_KIND,
        'status': 'engineering', 'target_source_count': 10, 'qualified': 0,
        'model_calls_permitted': False})
    panel = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port)
    url = panel.start()
    audit.update_run(producer_active=True, producer_pid=os.getpid(), dashboard_url=url)
    print(json.dumps({'output': str(output), 'pid': os.getpid(), 'dashboard': url}), flush=True)
    started = time.monotonic()
    records, error = {}, None
    try:
        with ThreadPoolExecutor(max_workers=frozen['workers']) as executor:
            futures = {executor.submit(_run_case, case, frozen, audit): case['profile_id']
                       for case in frozen['cases']}
            try:
                for future in as_completed(futures):
                    record = future.result()
                    records[record['profile_id']] = record
                    audit.update_run(completed_source_workers=len(records),
                        failed_source_workers=sum(not row['completed'] for row in records.values()))
            except BaseException:
                for future in futures:
                    future.cancel()
                raise
        _check_hashes(frozen)
        require(len(records) == 10 and all(record['completed'] for record in records.values()),
                'The complete declared ten-source engineering batch did not pass')
        entries, binding_manifest = _validate_entries(frozen)
        write(output / 'mutation_source_bindings.json', binding_manifest)
        setting = {'enabled': True, 'version': 1, 'contract': JOINT_METHOD,
                   'nodes': node_binding(), 'bindings': ref(output / 'mutation_source_bindings.json')}
        validate_setting(setting)
        for entry in entries:
            _complete_evidence(entry, validate_seed(entry, setting))
        counts = _execution_counts(frozen)
        require(counts['attempted_actual_LO_calls'] == counts['completed_actual_LO_calls'] == 20
                and not counts['engine_call_record_unknown_profiles'],
                'The actual engine execution records are not complete for all ten sources')
        write(output / 'engineering_index.json', {'kind': 'fixed_ten_actual_v3_engineering_index',
            'profile_order': list(ORDER), 'cases': [{'profile_id': entry['profile_id'],
                'source': entry['semantic_graph_binding']['source'],
                'original_source': entry['original_source'],
                'engineering_probe': entry['engineering_probe']} for entry in entries],
            'qualified': False, 'task_count': 0})
        write(output / 'seed_manifest.json', {'schema_version': 1, 'kind': POOL_KIND,
            'selected': entries, 'unique_workbooks_inspected': 10,
            'download_url': 'derived-fixed-ten-semantic-provider-v3-engineering-pool',
            'archive_sha256': None, 'development_only': True, 'model_scores_consulted': False,
            'source_original_ancestors': 2, 'derived_presentation_source_count': 10,
            'profile_order': list(ORDER), 'original_source_order': frozen['original_source_order'],
            'presented_source_order': frozen['presented_source_order'],
            'quality_recovery_difficulty_certified': False, 'qualified': False, 'task_count': 0})
    except BaseException as exception:
        error = {'error_type': type(exception).__name__, 'reason': str(exception)}
        write(output / 'batch_failure.json', {**error, 'records': records,
            'qualified': False, 'task_count': 0, 'model_calls': 0})
        if not (output / 'seed_manifest.json').exists():
            write(output / 'seed_manifest.json', {'schema_version': 1, 'kind': POOL_KIND,
                'selected': [], 'unique_workbooks_inspected': 10,
                'download_url': 'derived-fixed-ten-semantic-provider-v3-engineering-pool',
                'archive_sha256': None, 'status': 'failed', 'source_original_ancestors': 2,
                'derived_presentation_source_count': 10, 'qualified': False, 'task_count': 0})
    finally:
        artifact_map = deepcopy(frozen['source_artifacts_sha256'])
        for path in output.rglob('worker_terminal.json'):
            artifact_map[str(path)] = sha(path)
        result = {'kind': POOL_KIND, 'version': 1, 'status': 'completed' if error is None else 'failed',
            'count': 10, 'frozen_inventory': ref(output / 'frozen_inventory.json'),
            'profile_order': list(ORDER), 'original_source_order': frozen['original_source_order'],
            'presented_source_order': frozen['presented_source_order'],
            'source_original_ancestors': 2, 'derived_presentation_source_count': 10,
            'seed_manifest': ref(output / 'seed_manifest.json'),
            'recipe_sha256': frozen['recipe_sha256'], 'source_artifacts_sha256': artifact_map,
            'worker_records': [records.get(profile, {'profile_id': profile, 'completed': False}) for profile in ORDER],
            'model_calls': 0, 'question_QA_calls': 0, 'strong_calls': 0,
            'normal_construct_five_controls_recovery_12QA_Harbor_required': True,
            'qualified': False, 'task_count': 0, **_execution_counts(frozen)}
        if error is None:
            result.update(mutation_source_bindings=ref(output / 'mutation_source_bindings.json'),
                semantic_graph_mutation=setting, engineering_index=ref(output / 'engineering_index.json'))
        else:
            result['failure'] = ref(output / 'batch_failure.json')
        write(output / 'batch_manifest.json', result)
        audit.update_run(status=result['status'], producer_active=False, finished_at=utcnow(),
                         elapsed_seconds=time.monotonic() - started, **_execution_counts(frozen))
        audit.export()
        panel.stop()
    require(error is None, 'The fixed-ten engineering batch failed; no partial pool was admitted')
    return ref(output / 'batch_manifest.json')


def validate_completed(output):
    """Re-read all ten financial admissions and real engineering proofs."""
    output = Path(output).resolve()
    frozen = validate_prepared(output)
    result = read(ref(output / 'batch_manifest.json'))
    require(result.get('kind') == POOL_KIND and result.get('status') == 'completed'
            and result.get('version') == 1 and result.get('count') == 10
            and result.get('frozen_inventory') == ref(output / 'frozen_inventory.json')
            and result.get('profile_order') == list(ORDER)
            and result.get('original_source_order') == frozen['original_source_order']
            and result.get('presented_source_order') == frozen['presented_source_order']
            and result.get('source_original_ancestors') == 2
            and result.get('derived_presentation_source_count') == 10
            and result.get('attempted_actual_LO_calls') == result.get('completed_actual_LO_calls') == 20
            and result.get('qualified') is False and result.get('task_count') == 0,
            'A complete fixed-ten V3 engineering pool is required')
    require(result['recipe_sha256'] == frozen['recipe_sha256'], 'The completed batch recipe differs')
    require(result.get('seed_manifest') == ref(output / 'seed_manifest.json')
            and result.get('mutation_source_bindings') == ref(output / 'mutation_source_bindings.json')
            and result.get('engineering_index') == ref(output / 'engineering_index.json'),
            'The completed pool outputs must belong to this immutable batch')
    require(all(result.get(key) == 0 for key in ('model_calls', 'question_QA_calls', 'strong_calls'))
            and result.get('normal_construct_five_controls_recovery_12QA_Harbor_required') is True,
            'Engineering cannot certify task quality or contain model executions')
    require(all(result['source_artifacts_sha256'].get(path) == digest
                for path, digest in frozen['source_artifacts_sha256'].items()),
            'The completed batch omitted a frozen source artifact')
    for path, digest in result['source_artifacts_sha256'].items():
        require(sha(path) == digest, 'A completed source artifact changed: ' + path)
    worker_records = result.get('worker_records')
    _indexed(worker_records, ORDER, 'Completed worker records')
    for case, record in zip(frozen['cases'], worker_records):
        terminal = Path(case['case_directory']).parent / 'worker_terminal.json'
        require(record == read(ref(terminal)) and record.get('completed') is True
                and record.get('returncode') == 0,
                'A declared worker lacks its own immutable successful terminal receipt')
    expected_entries, expected_bindings = _validate_entries(frozen)
    require(read(result['mutation_source_bindings']) == expected_bindings,
            'The completed provider/source bindings differ')
    setting = result['semantic_graph_mutation']
    require(setting == {'enabled': True, 'version': 1, 'contract': JOINT_METHOD,
        'nodes': node_binding(), 'bindings': result['mutation_source_bindings']},
        'The completed engineering pool changed its separate mutation setting')
    validate_setting(setting)
    manifest = read(result['seed_manifest'])
    require(manifest.get('kind') == POOL_KIND and manifest.get('source_original_ancestors') == 2
            and manifest.get('derived_presentation_source_count') == 10
            and manifest.get('qualified') is False and manifest.get('task_count') == 0
            and manifest.get('unique_workbooks_inspected') == 10
            and manifest.get('archive_sha256') is None
            and manifest.get('profile_order') == list(ORDER)
            and manifest.get('original_source_order') == frozen['original_source_order']
            and manifest.get('presented_source_order') == frozen['presented_source_order'],
            'The fixed-ten seed pool metadata changed')
    entries = manifest.get('selected')
    _indexed(entries, ORDER, 'Completed selected seeds')
    for actual, expected in zip(entries, expected_entries):
        proof = validate_seed(expected, setting)
        _complete_evidence(expected, proof)
        require(actual == expected, 'A completed selected seed or financial evidence changed')
    index = read(result['engineering_index'])
    require(index == {'kind': 'fixed_ten_actual_v3_engineering_index', 'profile_order': list(ORDER),
        'cases': [{'profile_id': entry['profile_id'], 'source': entry['semantic_graph_binding']['source'],
            'original_source': entry['original_source'], 'engineering_probe': entry['engineering_probe']}
            for entry in entries], 'qualified': False, 'task_count': 0},
        'The completed engineering index differs from the full ordered seed pool')
    counts = _execution_counts(frozen)
    require(counts == {key: result[key] for key in counts}
            and not counts['engine_call_record_unknown_profiles'],
            'The completed actual engine counts differ from per-source call records')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--source-foundation-index', type=Path)
    parser.add_argument('--offline-batch-manifest', type=Path)
    parser.add_argument('--policy', type=Path)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--validate-completed', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    if args.run and args.validate_completed:
        parser.error('--run cannot be combined with --validate-completed')
    if args.prepared:
        if any((args.output, args.source_foundation_index, args.offline_batch_manifest, args.policy)):
            parser.error('--prepared cannot be combined with new preparation inputs')
        output = args.prepared
    else:
        if not all((args.output, args.source_foundation_index, args.offline_batch_manifest, args.policy)):
            parser.error('Preparation requires output, foundation index, offline batch and policy')
        output = args.output
        print(json.dumps(prepare(output, args.source_foundation_index,
            args.offline_batch_manifest, args.policy, workers=args.workers)), flush=True)
    if args.run:
        print(json.dumps(execute_prepared(output, port=args.port)), flush=True)
    elif args.validate_completed:
        print(json.dumps(validate_completed(output)), flush=True)


if __name__ == '__main__':
    main()
