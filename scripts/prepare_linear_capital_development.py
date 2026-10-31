#!/usr/bin/env python3
"""Freeze one actual native linear-capital task for prequality development.

Preparation validates existing calculations; it starts no LO, optimizer, model
or Harbor control. The optional run command has one fixed development attempt.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from openpyxl import load_workbook
from sheets_factory.evaluation.budget import validate_selection_execution_budget
from sheets_factory.evaluation.clock_resource_frontier import POLICY_V3
from sheets_factory.evaluation.resource_frontier import TASK_FILES, MODEL, EFFORT
from sheets_factory.evaluation.resource_harbor import (
    export_resource_harbor, inspect_resource_export, verify_local_base_image)
from sheets_factory.evaluation.streaming_verifier import _sparse_cells, normalize
from sheets_factory.task_adapters.heterogeneous_formula_identity import formula_signature
from sheets_factory.workbook.resource_engine import load_runtime_profile

KIND = 'prequality_linear_capital_native_development'
CONTROL_REWARDS = {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}
BUDGET = {'version': 1, 'elapsed_policy': 'operational_guard',
          'elapsed_guard_seconds': 14400, 'tool_budget_seconds': 1800}
PENDING = ['public_only_recovery', 'all_12_quality_checks', 'normal_Factory_nodes',
           'normal_ExportNode', 'actual_Harbor_oracle_and_nop', 'fresh_final_cohort_confirmation']
HISTORY_ROOTS = (ROOT/'outputs/difficulty', ROOT/'outputs/research')


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def reference(path):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_file(), 'An artifact must be a real nonsymlink file')
    before = path.stat(); digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(8*1024**2), b''):
            digest.update(block)
    after = path.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
        'An artifact changed during hashing')
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': after.st_size}


def checked(value):
    if isinstance(value, (str, Path)):
        return reference(value)
    require(isinstance(value, dict) and set(value) == {'path', 'sha256', 'bytes'}
        and type(value['bytes']) is int and value['bytes'] >= 0
        and reference(value['path']) == value, 'An exact artifact reference changed')
    return value


def read(value):
    record = checked(value)
    result = json.loads(Path(record['path']).read_bytes())
    require(isinstance(result, dict), 'A JSON evidence object is required')
    return result


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False); handle.write('\n')
    return reference(path)


def validation_driver():
    path = ROOT/'scripts/validate_linear_capital_task_view.py'
    descriptor = importlib.util.spec_from_file_location('_linear_development_actual_validation', path)
    module = importlib.util.module_from_spec(descriptor); descriptor.loader.exec_module(module)
    return module


def recipes():
    driver = validation_driver()
    files = [Path(__file__), ROOT/'src/sheets_factory/evaluation/clock_resource_frontier.py',
        ROOT/'src/sheets_factory/evaluation/tool_time_clock_bounds.py',
        ROOT/'src/sheets_factory/evaluation/resource_frontier.py',
        ROOT/'src/sheets_factory/evaluation/frontier.py',
        ROOT/'src/sheets_factory/evaluation/resource_harbor.py',
        ROOT/'src/sheets_factory/evaluation/resource_streaming_verifier.py',
        ROOT/'src/sheets_factory/evaluation/resource_observer.py',
        ROOT/'src/sheets_factory/task_adapters/heterogeneous_formula_identity.py']
    return {**driver.recipes(), **{str(p.resolve()): reference(p)['sha256'] for p in files}}


def verify_mapping(mapping):
    require(isinstance(mapping, dict) and bool(mapping), 'A complete artifact map is required')
    for path, digest in mapping.items():
        require(type(digest) is str and re.fullmatch('[0-9a-f]{64}', digest)
            and reference(path)['sha256'] == digest, 'A frozen artifact changed: '+path)


def bind_references(value, mapping):
    """Hash declared files without recursively parsing large financial tables."""
    if isinstance(value, dict):
        if {'path', 'sha256', 'bytes'} <= value.keys():
            record = checked({key: value[key] for key in ('path', 'sha256', 'bytes')})
            require(record['path'] not in mapping or mapping[record['path']] == record['sha256'],
                'Conflicting artifact identities')
            mapping[record['path']] = record['sha256']
        for child in value.values():
            bind_references(child, mapping)
    elif isinstance(value, list):
        for child in value:
            bind_references(child, mapping)


def workbook_identity(path, *, formulas=False):
    """Logical full-workbook identity; task renames and ZIP metadata give no retry."""
    before = reference(path); digest = hashlib.sha256(); count = 0
    book = load_workbook(path, read_only=True, data_only=not formulas, keep_links=False)
    try:
        digest.update(json.dumps(book.sheetnames, ensure_ascii=False).encode())
        for sheet in book.worksheets:
            stream = iter(_sparse_cells(sheet))
            try:
                for position, cell in stream:
                    if cell['data_type'] == 'f':
                        require(isinstance(cell['value'], str), 'Array formula identity is unsupported')
                        signature = []
                        for token_type, subtype, token_value in formula_signature(cell['value']):
                            if isinstance(token_value, Decimal):
                                numerator, denominator = token_value.as_integer_ratio()
                                token_value = {'numerator': str(numerator), 'denominator': str(denominator)}
                            signature.append([token_type, subtype, token_value])
                        value = ['formula', signature]
                    elif cell['data_type'] == 'e':
                        value = ['error', cell['value']]
                    else:
                        value = normalize(cell['value'], epoch=book.epoch)
                    # Empty physical formatting cells do not change the task.
                    if value == ('empty', None):
                        continue
                    digest.update(json.dumps([sheet.title, position, value], ensure_ascii=False,
                        separators=(',', ':'), allow_nan=False).encode()+b'\n'); count += 1
            finally:
                stream.close()
    finally:
        book.close()
    require(reference(path) == before, 'A workbook changed during logical identity inspection')
    return {'sha256': digest.hexdigest(), 'complete_nonempty_cells': count}


def material_identity(view, plan, validation, delta):
    """Paths, task names, and packaging are evidence, not material version changes."""
    scope = {'masked_targets': sorted((r['sheet'], r['cell']) for r in plan['masked_targets']),
        'formula_edits': [{k: r[k] for k in ('sheet', 'cell', 'before', 'after', 'family')}
                          for r in plan['formula_edits']],
        'choice_edits': [{k: r[k] for k in ('sheet', 'cell', 'before', 'after')}
                         for r in plan['choice_edits']],
        'complete_expected_changes': delta['expected_changes']}
    content = {'version': 1, 'mode': view['mode'], 'specification_sha256': view['specification_sha256'],
        'input_definitions': workbook_identity(validation['input']['path'], formulas=True),
        'input_values': workbook_identity(validation['input']['path']),
        'goal_values': workbook_identity(validation['goal']['path']),
        'instruction_sha256': validation['instruction']['sha256'], 'scope_sha256': canonical(scope)}
    return {**content, 'sha256': canonical(content)}


def _historical_identity(selection, task):
    source_ref = selection.get('source_manifest')
    if isinstance(source_ref, dict) and {'path', 'sha256'} <= source_ref.keys():
        path = Path(source_ref['path'])
        require(path.is_file() and reference(path)['sha256'] == source_ref['sha256'],
            'A prior selection source manifest is missing or changed')
        source = json.loads(path.read_bytes())
        identity = source.get('material_task_version')
        if isinstance(identity, dict):
            require(identity.get('sha256') == canonical({k: v for k, v in identity.items() if k != 'sha256'}),
                'A historical material task identity is malformed')
            return identity
    return None


def selection_history(identity, roots=None):
    records = []; seen = set()
    for root in HISTORY_ROOTS if roots is None else roots:
        root = Path(root).absolute()
        require(root == root.resolve(), 'History roots must be real paths')
        if not root.exists():
            continue
        for path in sorted(root.rglob('selection_manifest.json')):
            if str(path) in seen:
                continue
            seen.add(str(path)); selection = read(path)
            require(isinstance(selection.get('tasks'), list), 'A historical selection is malformed')
            for task in selection['tasks']:
                require(isinstance(task, dict), 'A historical selected task is malformed')
                if task.get('mode') != identity['mode']:
                    continue
                previous = _historical_identity(selection, task)
                if previous is not None:
                    require(previous['sha256'] != identity['sha256'],
                        'This material task version already has a selection; do not resample or rename it')
                    continue
                # Older versions did not store logical identities. A matching
                # public instruction AND both complete workbooks is still held.
                directory = task.get('task_directory')
                if directory:
                    folder = Path(directory); instruction = folder/'instruction.md'
                    if instruction.is_file() and reference(instruction)['sha256'] == identity['instruction_sha256']:
                        source, goal = folder/'environment/input.xlsx', folder/'tests/reference.xlsx'
                        require(source.is_file() and goal.is_file(), 'Matching historical task bytes are missing')
                        same = (workbook_identity(source, formulas=True) == identity['input_definitions']
                            and workbook_identity(source) == identity['input_values']
                            and workbook_identity(goal) == identity['goal_values'])
                        require(not same, 'This material task version already has a historical selection')
            records.append(reference(path))
    return records


def checked_material(source_manifest, view_manifest, validation_manifest):
    source_ref, view_ref, actual_ref = map(checked, (source_manifest, view_manifest, validation_manifest))
    actual = validation_driver().validate_completed(actual_ref)
    require(actual.get('kind') == 'linear_capital_task_view_actual_validation'
        and type(actual.get('version')) is int and actual['version'] == 1 and actual.get('passed') is True
        and actual.get('source_admission') == source_ref and actual.get('materialized_view') == view_ref,
        'The genuine actual task validation belongs to another source or materialized view')
    source, view = read(source_ref), read(view_ref); plan = read(view['plan'])
    require(view['mode'] == actual['mode'] == plan['mode']
        and actual['mode'] in ('financial_modeling', 'debugging')
        and view['source'] == source['workbook'] and actual['instruction'] == view['instruction']
        and Path(actual['instruction']['path']).read_bytes() == plan['instruction'].encode('utf-8'),
        'The source, mode or exact public business instruction differs')
    require(actual['local_controls'] == CONTROL_REWARDS
        and all(type(actual['local_controls'][key]) is int for key in CONTROL_REWARDS)
        and actual['source_original_unchanged'] is True and actual['qualified'] is False,
        'All five actual local controls and unchanged native source are required')
    delta = read(actual['complete_D'])
    require(delta.get('reward') == 1 and delta.get('structure_ok') is True
        and type(delta.get('expected_change_count')) is int and delta['expected_change_count'] > 0
        and delta.get('expected_changes') == sorted(set(delta.get('expected_changes', [])))
        and len(delta['expected_changes']) == delta['expected_change_count'],
        'The complete expected changed-value set is missing, duplicated or truncated')
    profile_ref = checked(source['runtime_profile']); profile = load_runtime_profile(profile_ref['path'])
    require(profile['docker_resources']['agent'] == profile['docker_resources']['verifier']
        == {'cpus': 2, 'memory_bytes': 32*1024**3, 'pids_limit': 256},
        'The explicit native agent/verifier profile must be 2CPU and 32GiB')
    identity = material_identity(view, plan, actual, delta)
    return source_ref, view_ref, actual_ref, source, view, plan, actual, delta, profile_ref, profile, identity


def _prepare(source_manifest, view_manifest, validation_manifest, output):
    output = Path(output).absolute()
    require(output == output.resolve() and not output.exists(), 'Use a fresh real development directory')
    (source_ref, view_ref, actual_ref, source, view, plan, actual, delta,
        profile_ref, profile, identity) = checked_material(source_manifest, view_manifest, validation_manifest)
    history = selection_history(identity)
    bindings = recipes(); bind_references([source_ref, view_ref, actual_ref, source, view, actual, plan], bindings)
    output.mkdir(parents=True)
    task_id = ('fm' if view['mode'] == 'financial_modeling' else 'dbg')+'-linear-'+identity['sha256'][:16]
    task = output/'task'; (task/'public').mkdir(parents=True); (task/'private').mkdir()
    for record, destination in ((actual['input'], task/'public/input.xlsx'),
            (actual['goal'], task/'private/goal.xlsx'), (actual['instruction'], task/'public/instruction.md')):
        checked(record); shutil.copyfile(record['path'], destination)
        copied = reference(destination)
        require((copied['sha256'], copied['bytes']) == (record['sha256'], record['bytes']),
            'A snapshot copy differs from the actual validated task')
    base = write(output/'actual_local_base_image.json', verify_local_base_image(profile_ref['path']))
    exported = output/'SpreadsheetEval'/task_id
    metadata = {'task_id': task_id, 'mode': view['mode'], 'source_id': source['workbook']['sha256'],
        'source_kind': KIND, 'revision': 0, 'revision_hash': identity['sha256'],
        'difficulty_status': 'prequality_development_probe', 'base_image': profile['image']['id']}
    export_resource_harbor(task, exported, metadata, ROOT, runtime_profile=profile_ref['path'])
    export_binding = inspect_resource_export(exported)
    require(export_binding['task_id'] == task_id and type(export_binding['revision']) is int
        and export_binding['revision'] == 0 and export_binding['revision_hash'] == identity['sha256'],
        'The resource export identity differs')
    inventory = {p.relative_to(exported).as_posix(): reference(p) for p in exported.rglob('*') if p.is_file()}
    require(set(inventory) == set(TASK_FILES) and len(inventory) == 17,
        'The resource export requires exactly all seventeen files')
    require((exported/'instruction.md').read_bytes() == Path(actual['instruction']['path']).read_bytes()
        and reference(exported/'environment/input.xlsx')['sha256'] == actual['input']['sha256']
        and reference(exported/'tests/reference.xlsx')['sha256'] == actual['goal']['sha256'],
        'The exported public instruction/input or private goal changed')
    bind_references([base, *inventory.values()], bindings)
    verify_mapping(bindings)
    late_history = selection_history(identity)
    require(history == late_history, 'Model-selection history changed during preparation')
    record = {**metadata, 'task_directory': str(exported), 'harbor_export_binding': export_binding,
        'local_controls': dict(CONTROL_REWARDS), 'execution_budget': dict(BUDGET),
        'timeout_seconds': 14400, 'tool_time_policy': dict(POLICY_V3)}
    manifest = {'kind': KIND, 'schema_version': 1, 'family': 'linear_capital_portfolio',
        'source_kind': KIND, 'frozen_at': datetime.now(timezone.utc).isoformat(),
        'source_admission': source_ref, 'materialized_view': view_ref, 'actual_task_validation': actual_ref,
        'selected_task_ids': [task_id], 'tasks': [record], 'material_task_version': identity,
        'model': MODEL, 'reasoning_effort': EFFORT, 'execution_budget': dict(BUDGET), 'timeout_seconds': 14400,
        'tool_time_policy': dict(POLICY_V3), 'tool_time_policy_version': 3,
        'runtime_profile': profile_ref, 'source_artifacts_sha256': bindings, 'recipe_sha256': recipes(),
        'resource_task_inventory': inventory, 'actual_local_base_image': base,
        'actual_validation_LO_calls_retained': len(actual['actual_LO_calls']),
        'complete_changed_value_set_count': delta['expected_change_count'],
        'local_controls': dict(CONTROL_REWARDS), 'actual_Harbor_controls_status': 'pending',
        'history_roots': [str(p.resolve()) for p in HISTORY_ROOTS],
        'history_exclusion': {'path': str((ROOT/'outputs/tmp').resolve()),
            'reason': 'Offline test fixtures; no claim to search the entire filesystem'},
        'prior_model_selection_inventory': history, 'quality_gates_pending': list(PENDING),
        'normal_six_nodes_executed_or_inherited': False, 'normal_ExportNode_executed': False,
        'effective_infrastructure_retries': 0, 'unchanged_upstream_resume_allowance_does_not_authorize_resume': True,
        'raw_zero_is_provisional_until_full_quality': True, 'raw_one_stops_unchanged_version_expansion': True,
        'source_financial_audit_is_not_task_quality': True, 'qualified': False, 'task_count': 0,
        'new_LO_calls': 0, 'new_optimizer_calls': 0, 'new_model_calls': 0, 'new_Harbor_jobs': 0}
    validate_selection_execution_budget(manifest)
    return write(output/'probe_manifest.json', manifest)


def prepare(source_manifest, view_manifest, validation_manifest, output):
    existed = Path(output).exists()
    try:
        return _prepare(source_manifest, view_manifest, validation_manifest, output)
    except BaseException as error:
        path = Path(output)
        if not existed and path.is_dir() and not (path/'probe_manifest.json').exists():
            write(path/'preparation_failure.json', {'kind': KIND+'_failure', 'error_type': type(error).__name__,
                'error': str(error), 'partial_artifacts_preserved': True, 'qualified': False,
                'new_LO_calls': 0, 'new_model_calls': 0, 'new_Harbor_jobs': 0})
        raise


def validate_prepared(output):
    output = Path(output).absolute(); require(output == output.resolve(), 'A real prepared directory is required')
    frozen = read(output/'probe_manifest.json')
    require(frozen.get('kind') == KIND and frozen.get('schema_version') == 1
        and type(frozen['schema_version']) is int and frozen['recipe_sha256'] == recipes(),
        'The frozen development preparation or implementation changed')
    verify_mapping(frozen['source_artifacts_sha256'])
    material = checked_material(frozen['source_admission'], frozen['materialized_view'], frozen['actual_task_validation'])
    require(frozen['material_task_version'] == material[-1], 'The material task version changed')
    require(frozen['model'] == MODEL and frozen['reasoning_effort'] == EFFORT
        and frozen['tool_time_policy_version'] == 3 and frozen['tool_time_policy'] == POLICY_V3
        and frozen['execution_budget'] == BUDGET and frozen['timeout_seconds'] == 14400
        and frozen['effective_infrastructure_retries'] == 0 and frozen['qualified'] is False
        and frozen['task_count'] == 0 and frozen['quality_gates_pending'] == PENDING,
        'The single-attempt prequality contract changed')
    validate_selection_execution_budget(frozen)
    require(len(frozen['tasks']) == 1 and frozen['selected_task_ids'] == [frozen['tasks'][0]['task_id']],
        'Only one fixed declared task is permitted')
    task = frozen['tasks'][0]; directory = Path(task['task_directory'])
    expected_id = ('fm' if material[4]['mode'] == 'financial_modeling' else 'dbg')+'-linear-'+material[-1]['sha256'][:16]
    require(directory == output/'SpreadsheetEval'/task['task_id']
        and task['task_id'] == expected_id and type(task.get('revision')) is int and task['revision'] == 0
        and task['source_id'] == material[3]['workbook']['sha256'] and task['source_kind'] == KIND
        and task['mode'] == material[4]['mode'] and task['revision_hash'] == material[-1]['sha256']
        and task['harbor_export_binding'] == inspect_resource_export(directory)
        and task['local_controls'] == CONTROL_REWARDS
        and all(type(task['local_controls'][name]) is int for name in CONTROL_REWARDS),
        'The complete frozen resource task changed')
    current = {p.relative_to(directory).as_posix(): reference(p) for p in directory.rglob('*') if p.is_file()}
    require(set(current) == set(TASK_FILES) and current == frozen['resource_task_inventory'],
        'The complete seventeen-file inventory changed')
    selection_history(material[-1])
    return frozen


def run_development(prepared, evaluation_output, *, port=0):
    """One explicit root-authorized model attempt; no retries or confirmation route."""
    prepared = Path(prepared).absolute()
    require(prepared == prepared.resolve() and prepared.is_dir(), 'A real prepared snapshot is required')
    lock_path = prepared/'.development.lock'
    require(not lock_path.is_symlink(), 'The attempt lock must not be a symlink')
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('This frozen development snapshot already has an active launcher') from error
        return _run_once(prepared, evaluation_output, port=port)


def _run_once(prepared, evaluation_output, *, port):
    frozen = validate_prepared(prepared)
    destination = Path(evaluation_output).absolute()
    require(destination == destination.resolve() and not destination.exists(),
        'Use a fresh evaluation directory; attempts cannot resume or retry here')
    require(not (prepared/'development_started.json').exists(),
        'This snapshot already has a reserved first attempt; no retry or resampling is authorized')
    from sheets_factory.evaluation.clock_resource_frontier import run_evaluation
    from sheets_factory.evaluation.resource_observer import ResourceObserver
    import yaml
    path = ROOT/'config/llm.yaml'; backend = yaml.safe_load(path.read_text()) if path.is_file() else {}
    backend.update(model=MODEL, reasoning_effort=EFFORT,
        roles={'trace_agent': {'model': MODEL, 'reasoning_effort': EFFORT}})
    started = write(prepared/'development_started.json', {'kind': KIND+'_first_attempt_started',
        'at': datetime.now(timezone.utc).isoformat(), 'prepared_snapshot': reference(prepared/'probe_manifest.json'),
        'material_task_version': frozen['material_task_version'], 'evaluation_output': str(destination),
        'model': MODEL, 'reasoning_effort': EFFORT, 'phase': 'development', 'concurrency': 1,
        'effective_infrastructure_retries': 0, 'qualified': False})
    observer = None
    try:
        with ResourceObserver(destination) as observer:
            result = run_evaluation(prepared/'probe_manifest.json', destination, phase='development',
                concurrency=1, project_root=ROOT, backend_config=backend, port=port,
                prior_selections=[r['path'] for r in frozen['prior_model_selection_inventory']])
        terminal = {'kind': KIND+'_first_attempt_terminal', 'started': started,
            'evaluation_manifest': reference(destination/'evaluation_manifest.json'),
            'selection_manifest': reference(destination/'selection_manifest.json'),
            'resource_observation_receipt': observer.receipt,
            'resource_observation_finalization_error': observer.finalization_error,
            'status': result['status'], 'score': result['score'], 'qualified': False,
            'effective_infrastructure_retries': 0, 'phase': 'development'}
        return write(prepared/'development_terminal.json', terminal)
    except BaseException as error:
        write(prepared/'development_failure.json', {'kind': KIND+'_first_attempt_failure',
            'started': started, 'error_type': type(error).__name__, 'error': str(error),
            'resource_observation_receipt': getattr(observer, 'receipt', None),
            'resource_observation_finalization_error': getattr(observer, 'finalization_error', None),
            'failure_is_not_model_zero': True, 'retry_authorized': False,
            'qualified': False, 'all_partial_artifacts_preserved': True})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    prepare_args = sub.add_parser('prepare')
    for name in ('source-manifest', 'view-manifest', 'validation-manifest', 'output'):
        prepare_args.add_argument('--'+name, type=Path, required=True)
    validate_args = sub.add_parser('validate'); validate_args.add_argument('--prepared', type=Path, required=True)
    run_args = sub.add_parser('run-development'); run_args.add_argument('--prepared', type=Path, required=True)
    run_args.add_argument('--output', type=Path, required=True); run_args.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    if args.command == 'prepare':
        result = prepare(args.source_manifest, args.view_manifest, args.validation_manifest, args.output)
    elif args.command == 'validate':
        result = validate_prepared(args.prepared)
    else:
        result = run_development(args.prepared, args.output, port=args.port)
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
