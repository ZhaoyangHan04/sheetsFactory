#!/usr/bin/env python3
"""Prepare or explicitly launch one recovery of the exact ended M02 DBG trial.

Preparation and validation are cold: they read and hash finished evidence only.
No model, spreadsheet engine, optimizer, Harbor job, container or extra UI starts.
The separate run-development command is the sole launch entry. It preserves the
old first-attempt contract and every old byte; a recovery is not a new material.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))

from sheets_factory.evaluation import clock_resource_frontier as original_runner
from sheets_factory.evaluation import native_transport_frontier as runner
from sheets_factory.evaluation.budget import validate_selection_execution_budget
from sheets_factory.evaluation.resource_frontier import TASK_FILES, MODEL, EFFORT

descriptor = importlib.util.spec_from_file_location('_frozen_linear_first_attempt',
    ROOT/'scripts/prepare_linear_capital_development.py')
first = importlib.util.module_from_spec(descriptor); descriptor.loader.exec_module(first)
require, canonical, reference, checked, read, write = (
    first.require, first.canonical, first.reference, first.checked, first.read, first.write)

KIND = 'bounded_linear_capital_native_transport_recovery'
PARENT_TERMINAL_SHA256 = '62cefd334f71b94eb2829dcd7ed79902516eaa8bc88ed0d5f275e569dc82c115'
PARENT_PROBE_SHA256 = '87322d2738dd045bf4e12fea2a52f02ae5933a0f75a2830729691baf3530a4f5'
PARENT_DIAGNOSTIC_SHA256 = 'a7915751a77ab0b5ff9f51e9a41017045dbf7133da0bac91ea3d2f831b4a9201'
HISTORY_ROOTS = first.HISTORY_ROOTS
POLICY = {'version': 1, 'max_documented_recoveries_per_material': 1,
    'scored_attempts_per_material': 1, 'never_recover_scored': True,
    'exact_completed_parent_required': True, 'allow_missing_persisted_attempt': False,
    'unknown_or_timing_only_failure_eligible': False, 'phase': 'development',
    'old_effective_infrastructure_retries_preserved': 0,
    'inherited_runner_retry_allowance_is_not_authorization': True,
    'transport_change_is_resilience_mitigation_not_proven_root_cause_fix': True}


def recipes():
    paths = [Path(__file__), Path(runner.__file__), runner.PROFILE_PATH,
        Path(sys.modules[original_runner.Codex.__module__].__file__)]
    return {str(path.resolve()): reference(path)['sha256'] for path in paths}


def _tree(path):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_dir()
        and not any(p.is_symlink() for p in path.rglob('*')), 'A complete real artifact tree is required')
    return {p.relative_to(path).as_posix(): reference(p) for p in sorted(path.rglob('*')) if p.is_file()}


def _score_is_unscored(score):
    require(isinstance(score, dict) and score.get('overall_pass_at_1') is None
        and type(score.get('scored_tasks')) is int and score['scored_tasks'] == 0
        and score.get('total_tasks') == 1 and score.get('infrastructure_errors') == 1
        and score.get('incomplete_timing_evidence') == 0 and score.get('operational_guard_stops') == 0
        and score.get('tool_budget_failures') == 0,
        'Only an unscored infrastructure failure is eligible; neither model zero nor one may recover')


def _first_snapshot(probe_ref):
    """Cold-check the frozen first snapshot without relaxing its no-retry API."""
    frozen = read(probe_ref)
    require(probe_ref['sha256'] == PARENT_PROBE_SHA256 and frozen.get('kind') == first.KIND
        and type(frozen.get('schema_version')) is int and frozen['schema_version'] == 1
        and frozen.get('recipe_sha256') == first.recipes(), 'The exact frozen original preparation changed')
    first.verify_mapping(frozen['source_artifacts_sha256'])
    identity = frozen['material_task_version']
    require(identity.get('sha256') == canonical({k:v for k,v in identity.items() if k != 'sha256'})
        and identity.get('mode') == 'debugging', 'The frozen native debugging material identity changed')
    require(frozen.get('model') == MODEL and frozen.get('reasoning_effort') == EFFORT
        and frozen.get('execution_budget') == first.BUDGET and frozen.get('timeout_seconds') == 14400
        and frozen.get('tool_time_policy_version') == 3 and frozen.get('tool_time_policy') == first.POLICY_V3
        and type(frozen.get('effective_infrastructure_retries')) is int
        and frozen['effective_infrastructure_retries'] == 0 and frozen.get('qualified') is False
        and frozen.get('task_count') == 0 and frozen.get('quality_gates_pending') == first.PENDING
        and len(frozen.get('tasks', [])) == 1,
        'The original single-attempt development contract changed')
    validate_selection_execution_budget(frozen)
    task = frozen['tasks'][0]
    require(frozen['selected_task_ids'] == [task['task_id']]
        and task['task_id'] == 'dbg-linear-'+identity['sha256'][:16]
        and type(task.get('revision')) is int and task['revision'] == 0
        and task['revision_hash'] == identity['sha256'] and task['mode'] == 'debugging'
        and task.get(first.CAP_FIELD) == first.CAP_VALUE
        and task['local_controls'] == first.CONTROL_REWARDS,
        'The original task, revision, cap or controls changed')
    inventory = _tree(task['task_directory'])
    require(set(inventory) == set(TASK_FILES) and len(inventory) == 17
        and inventory == frozen['resource_task_inventory']
        and first.inspect_resource_export(task['task_directory'], audit_path=frozen['thread_cap_export_audit'])
            == task['harbor_export_binding'], 'The original seventeen-file export changed')
    partition = first.history_partition(frozen['selection_history_inventory'])
    require(partition['model_selections'] == frozen['prior_model_selection_inventory']
        and partition['nonmodel_preparations'] == frozen['nonmodel_preparation_inventory'],
        'The original complete history partition changed')
    return frozen


def assess_parent(terminal, diagnostic):
    """Bind genuine completed trial, native terminal stream error and no answer."""
    terminal_ref, diagnostic_ref = checked(terminal), checked(diagnostic)
    require(terminal_ref['sha256'] == PARENT_TERMINAL_SHA256
        and diagnostic_ref['sha256'] == PARENT_DIAGNOSTIC_SHA256,
        'Only the exact documented completed M02 DBG transport failure may recover')
    ended, diagnosis = read(terminal_ref), read(diagnostic_ref)
    require(ended.get('kind') == first.KIND+'_first_attempt_terminal'
        and ended.get('status') == 'infrastructure_failed' and ended.get('phase') == 'development'
        and ended.get('qualified') is False and ended.get('effective_infrastructure_retries') == 0,
        'The original attempt is not an ended unscored infrastructure failure')
    _score_is_unscored(ended.get('score'))
    started_ref = checked(ended['started']); started = read(started_ref)
    require(started.get('kind') == first.KIND+'_first_attempt_started'
        and started.get('effective_infrastructure_retries') == 0
        and started.get('phase') == 'development' and started.get('concurrency') == 1
        and started.get('model') == MODEL and started.get('reasoning_effort') == EFFORT,
        'The original first-attempt reservation changed')
    probe_ref = checked(started['prepared_snapshot']); frozen = _first_snapshot(probe_ref)
    require(started['material_task_version'] == frozen['material_task_version'], 'The original material lineage changed')
    evaluation_ref, selection_ref = checked(ended['evaluation_manifest']), checked(ended['selection_manifest'])
    evaluation, selection = read(evaluation_ref), read(selection_ref)
    evaluation_dir = Path(evaluation_ref['path']).parent
    require(selection_ref['path'] == str(evaluation_dir/'selection_manifest.json')
        and evaluation_ref['path'] == str(evaluation_dir/'evaluation_manifest.json')
        and started['evaluation_output'] == str(evaluation_dir)
        and selection['source_manifest'] == {k:probe_ref[k] for k in ('path','sha256')}
        and evaluation['selection_manifest'] == {k:selection_ref[k] for k in ('path','sha256')}
        and evaluation.get('status') == 'infrastructure_failed'
        and evaluation.get('finished_at') and evaluation.get('failure_kind') is None
        and evaluation.get('phase') == selection.get('phase') == 'development'
        and evaluation.get('infrastructure_retries') == []
        and evaluation.get('score') == ended['score'] and evaluation.get('gate_passed') is False,
        'The genuine completed evaluation, selection or first-attempt parent changed')
    _score_is_unscored(evaluation['score'])
    original_runner._selection_execution_budget(selection, evaluation)
    require(selection.get('model') == evaluation.get('model') == MODEL
        and selection.get('reasoning_effort') == evaluation.get('reasoning_effort') == EFFORT
        and selection.get('n_attempts') == evaluation.get('n_attempts') == 1
        and len(selection.get('tasks', [])) == 1
        and selection.get('prompt') == original_runner.PROMPT
        and selection.get('prompt_sha256') == evaluation.get('prompt_sha256')
        and not (evaluation_dir/'private/early_stop.json').exists(),
        'The original request, native model or single-attempt contract changed')
    source_task, task = frozen['tasks'][0], selection['tasks'][0]
    require(selection['selected_task_ids'] == frozen['selected_task_ids']
        and all(task.get(k) == source_task.get(k) for k in
            ('task_id','mode','revision','revision_hash','source_id','harbor_export_binding'))
        and Path(task['task_directory']) == evaluation_dir/'snapshot/SpreadsheetEval'/task['task_id'],
        'The original trial refers to changed task material')
    inventory = _tree(task['task_directory'])
    require(set(inventory) == set(TASK_FILES)
        and {k:(v['sha256'],v['bytes']) for k,v in inventory.items()} ==
            {k:(v['sha256'],v['bytes']) for k,v in frozen['resource_task_inventory'].items()}
        and original_runner.inspect_export(task['task_directory']) == task['harbor_export_binding']
        and original_runner.dirhash(task['task_directory'], 'sha256') == task['task_checksum'],
        'The actual completed trial export differs from the original exact seventeen files')
    attempts, infrastructure_history = original_runner.collect_attempts(evaluation_dir, selection,
        include_infrastructure_history=True)
    require(len(attempts) == len(infrastructure_history) == 1
        and attempts == evaluation.get('attempts') and infrastructure_history == evaluation.get('infra_history')
        and attempts[0].get('status') == 'infrastructure_error'
        and attempts[0].get('reward') is None
        and attempts[0].get('failure_kind') == 'NonZeroAgentExitCodeError'
        and attempts[0].get('job_name') == 'frontier-pass1',
        'A valid, unknown, duplicate or timing-only attempt cannot be recovered')
    attempt = attempts[0]; result_ref = reference(attempt['result_file']); result = read(result_ref)
    trial = Path(result_ref['path']).parent
    require(result_ref['sha256'] == attempt['result_sha256'] and result.get('finished_at')
        and (result.get('exception_info') or {}).get('exception_type') == 'NonZeroAgentExitCodeError'
        and (result.get('agent_execution') or {}).get('finished_at')
        and ((result.get('verifier_result') or {}).get('rewards') or {}).get('reward') == 0,
        'The completed native failure is absent, still running, valid or raw one')
    receipt = original_runner.assess_infrastructure_retry(attempt)
    stream_ref = reference(trial/'agent/codex.txt')
    require(receipt.get('eligible') is True and receipt.get('reason') == 'terminal_provider_failure'
        and receipt.get('evidence_sha256') == stream_ref['sha256'], 'No genuine terminal native provider error was certified')
    failures = []
    for line in Path(stream_ref['path']).read_text().splitlines():
        try: event = json.loads(line)
        except ValueError: continue
        if event.get('type') == 'turn.failed': failures.append((event.get('error') or {}).get('message'))
    require(failures == ['stream disconnected before completion: error sending request'],
        'Only the documented terminal stream/request failure is eligible')
    diagnostics_ref = reference(trial/'verifier/diagnostics.json'); diagnostics = read(diagnostics_ref)
    require(diagnostics.get('reward') == 0 and diagnostics.get('reason') == 'verification_error'
        and diagnostics.get('error_type') == 'ValueError'
        and diagnostics.get('error') == 'Submitted workbook is missing or a symlink'
        and diagnostics.get('recalculation_calls') == []
        and (trial/'verifier/reward.txt').read_text().strip() in {'0','0.0'}
        and not any(p.is_file() and p.name in {'output.xlsx','submitted.xlsx'} for p in trial.rglob('*')),
        'A submitted or scored answer cannot be retried as a missing-output infrastructure failure')
    require(diagnosis.get('completed_attempt_terminal') == terminal_ref
        and diagnosis.get('actual_harbor_result') == result_ref
        and diagnosis.get('native_public_event_stream') == stream_ref
        and diagnosis.get('harbor_exception_type') == 'NonZeroAgentExitCodeError',
        'The diagnostic does not bind this actual native failure')
    local_sources = diagnosis.get('local_source_bindings')
    expected_sources = {str(ROOT/'src/sheets_factory/evaluation/frontier.py'), str(Path(original_runner.__file__)),
        str(ROOT/'src/sheets_factory/llm/codex.py'), str(Path(sys.modules[original_runner.Codex.__module__].__file__))}
    require(isinstance(local_sources, list) and len(local_sources) == 4
        and {row.get('path') for row in local_sources} == expected_sources,
        'The diagnostic must bind the exact local provider and installed agent implementations')
    for row in local_sources: checked(row)
    native = (selection.get('execution_provenance') or {}).get('native_cli') or {}
    native_ref = reference(native['path'])
    require(native_ref['sha256'] == native.get('sha256') and isinstance(native.get('version'), str),
        'The original native CLI binary changed')
    session_ref = checked(diagnosis['native_session'])
    require(Path(session_ref['path']).is_relative_to(trial/'agent/sessions'), 'The native usage session is outside this trial')
    # Preserve first-attempt token usage exactly; it is never hidden by recovery.
    usage = deepcopy(result.get('agent_result'))
    require(usage == attempt.get('agent_result') and isinstance(usage, dict)
        and all(type(usage.get(k)) is int and usage[k] >= 0
            for k in ('n_input_tokens','n_output_tokens','n_cache_tokens')),
        'Complete original native token usage must be retained')
    lineage = {'terminal': terminal_ref, 'started': started_ref, 'probe_manifest': probe_ref,
        'evaluation_manifest': evaluation_ref, 'selection_manifest': selection_ref,
        'transport_diagnostic': diagnostic_ref, 'actual_trial_result': result_ref,
        'native_stream': stream_ref, 'native_session': session_ref, 'verifier_diagnostics': diagnostics_ref,
        'diagnostic_local_source_bindings': local_sources, 'native_cli_binary': native_ref,
        'original_native_cli_reported_version': native['version'],
        'first_attempt_usage': usage, 'parent_attempt': deepcopy(attempt),
        'evaluation_artifact_inventory': _tree(evaluation_dir)}
    return frozen, lineage


def _same_material(selection, task, identity):
    previous = first._historical_identity(selection, task)
    if previous is not None:
        return previous['sha256'] == identity['sha256']
    directory = task.get('task_directory')
    if not directory: return False
    folder = Path(directory); instruction = folder/'instruction.md'
    if not instruction.is_file() or reference(instruction)['sha256'] != identity['instruction_sha256']:
        return False
    source, goal = folder/'environment/input.xlsx', folder/'tests/reference.xlsx'
    require(source.is_file() and goal.is_file(), 'Matching historical material bytes are missing')
    return (first.workbook_identity(source, formulas=True) == identity['input_definitions']
        and first.workbook_identity(source) == identity['input_values']
        and first.workbook_identity(goal) == identity['goal_values'])


def history(identity, parent_selection, *, own_manifest=None, own_selection=None):
    """Retain every history entry; permit only the exact first-failure parent."""
    records = []; seen = set(); parent_seen = False
    for root in HISTORY_ROOTS:
        root = Path(root).absolute()
        require(root == root.resolve(), 'History roots must be real paths')
        if not root.exists(): continue
        for path in sorted(root.rglob('recovery_manifest.json')):
            if own_manifest is not None and path == Path(own_manifest): continue
            candidate = read(path)
            require(candidate.get('kind') == KIND, 'An unknown recovery reservation requires review')
            require(candidate.get('material_task_version', {}).get('sha256') != identity['sha256'],
                'This material already has a recovery reservation; multiple parents or recoveries are forbidden')
        for path in sorted(root.rglob('selection_manifest.json')):
            if str(path) in seen: continue
            seen.add(str(path)); record = reference(path); selection = read(record)
            is_model, tasks = first._history_tasks(selection)
            if record == parent_selection:
                require(not parent_seen, 'Multiple original parents were found'); parent_seen = True
            else:
                if own_selection is not None and path == Path(own_selection):
                    # A run may be audited afterwards, but it remains spent.
                    require(selection.get('source_manifest', {}).get('path') == str(own_manifest),
                        'The recovery selection does not bind its own immutable manifest')
                else:
                    for task in tasks if is_model else ():
                        if task.get('mode') == identity['mode']:
                            require(not _same_material(selection, task, identity),
                                'Another selection already used this material; never skip, rename or retry a valid attempt')
            records.append(record)
    require(parent_seen, 'The exact original first-attempt selection must remain in complete history')
    return records


def _destination(output):
    output = Path(output).absolute()
    require(output == output.resolve()
        and any(output.is_relative_to(Path(p).absolute()) for p in HISTORY_ROOTS),
        'Keep the recovery reservation in a standard searched history root')
    return output


@contextmanager
def _lock():
    root = Path(HISTORY_ROOTS[0]).absolute(); root.mkdir(parents=True, exist_ok=True)
    path = root/'.bounded_native_transport_recovery.lock'
    require(root == root.resolve() and not path.is_symlink(), 'The recovery history lock must be real')
    with path.open('a') as handle:
        try: fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error: raise ValueError('Another bounded recovery operation is active') from error
        yield


def prepare(terminal, diagnostic, output):
    output = _destination(output)
    with _lock():
        require(not output.exists(), 'Use a fresh recovery preparation; preserve all old evidence')
        frozen, lineage = assess_parent(terminal, diagnostic)
        current_history = history(frozen['material_task_version'], lineage['selection_manifest'])
        bindings = deepcopy(frozen['source_artifacts_sha256'])
        first.bind_references([lineage, current_history], bindings)
        bindings.update(recipes()); first.verify_mapping(bindings)
        require(current_history == history(frozen['material_task_version'], lineage['selection_manifest']),
            'History changed during the cold preparation')
        # Reuse the exact original seventeen-file export; run_evaluation makes
        # its usual isolated snapshot. No task rename, regeneration or re-export.
        manifest = {'kind': KIND, 'schema_version': 1, 'frozen_at': datetime.now(timezone.utc).isoformat(),
            'phase': 'development', 'parent': lineage, 'recovery_policy': deepcopy(POLICY),
            'recovery_index': 1, 'effective_infrastructure_retries': 1,
            'material_task_version': deepcopy(frozen['material_task_version']),
            'selected_task_ids': deepcopy(frozen['selected_task_ids']), 'tasks': deepcopy(frozen['tasks']),
            'model': MODEL, 'reasoning_effort': EFFORT, 'execution_budget': deepcopy(first.BUDGET),
            'timeout_seconds': 14400, 'tool_time_policy_version': 3, 'tool_time_policy': deepcopy(first.POLICY_V3),
            'native_transport_profile': runner.transport_profile(), 'recipe_sha256': recipes(),
            'runtime_profile': frozen['runtime_profile'], 'resource_task_inventory': frozen['resource_task_inventory'],
            'thread_cap_export_audit': frozen['thread_cap_export_audit'],
            'history_roots': [str(Path(p).absolute()) for p in HISTORY_ROOTS],
            'selection_history_inventory': current_history,
            'source_artifacts_sha256': bindings, 'qualified': False, 'task_count': 0,
            'quality_gates_pending': deepcopy(first.PENDING),
            'new_LO_calls': 0, 'new_optimizer_calls': 0, 'new_model_calls': 0, 'new_Harbor_jobs': 0}
        validate_selection_execution_budget(manifest)
        manifest['manifest_integrity_sha256'] = canonical(manifest)
        return write(output/'recovery_manifest.json', manifest)


def validate_prepared(prepared, *, allow_started=False):
    prepared = _destination(prepared); path = prepared/'recovery_manifest.json'; frozen = read(path)
    require(frozen.get('manifest_integrity_sha256') == canonical(
        {k:v for k,v in frozen.items() if k != 'manifest_integrity_sha256'}),
        'The immutable recovery manifest changed')
    require(frozen.get('kind') == KIND and type(frozen.get('schema_version')) is int
        and frozen['schema_version'] == 1 and frozen.get('recipe_sha256') == recipes()
        and frozen.get('recovery_policy') == POLICY and frozen.get('phase') == 'development'
        and type(frozen.get('recovery_index')) is int and frozen['recovery_index'] == 1
        and type(frozen.get('effective_infrastructure_retries')) is int and frozen['effective_infrastructure_retries'] == 1
        and frozen.get('native_transport_profile') == runner.transport_profile()
        and frozen.get('history_roots') == [str(Path(p).absolute()) for p in HISTORY_ROOTS],
        'The immutable one-recovery contract, transport profile, recipes or searched history changed')
    first.verify_mapping(frozen['source_artifacts_sha256'])
    original, lineage = assess_parent(frozen['parent']['terminal'], frozen['parent']['transport_diagnostic'])
    require(frozen['parent'] == lineage, 'The entire first-attempt artifact lineage changed')
    for key in ('material_task_version','selected_task_ids','tasks','runtime_profile','resource_task_inventory',
                'thread_cap_export_audit','execution_budget','timeout_seconds','tool_time_policy','tool_time_policy_version',
                'model','reasoning_effort','quality_gates_pending'):
        require(frozen.get(key) == original.get(key), 'The recovery changed the original material or execution contract: '+key)
    require(frozen.get('qualified') is False and frozen.get('task_count') == 0
        and all(type(frozen.get(k)) is int and frozen[k] == 0 for k in
            ('new_LO_calls','new_optimizer_calls','new_model_calls','new_Harbor_jobs')),
        'Cold preparation cannot claim new calls or qualification')
    validate_selection_execution_budget(frozen)
    started = prepared/'recovery_started.json'
    own_selection = None
    if started.exists():
        require(allow_started, 'This recovery was already reserved for launch; no second recovery is authorized')
        begun = read(started)
        require(begun.get('recovery_manifest') == reference(path), 'The launched recovery manifest changed')
        own_selection = Path(begun['evaluation_output'])/'selection_manifest.json'
    current = history(frozen['material_task_version'], lineage['selection_manifest'], own_manifest=path,
        own_selection=own_selection)
    prior = {r['path']:r for r in current}
    require(all(prior.get(r['path']) == r for r in frozen['selection_history_inventory']),
        'A prior history entry disappeared or changed')
    require(all(frozen['source_artifacts_sha256'].get(r['path']) == r['sha256']
        for r in frozen['selection_history_inventory']), 'The complete frozen history is not bound')
    return frozen, current


def run_development(prepared, output, *, port=0):
    """Explicit future launch only; starts the normal runner UI after cold checks."""
    prepared = _destination(prepared); destination = _destination(output)
    with _lock():
        frozen, current_history = validate_prepared(prepared)
        require(not destination.exists() and not destination.is_relative_to(prepared)
            and not prepared.is_relative_to(destination), 'Use a fresh separate recovery evaluation directory')
        partition = first.history_partition(current_history)
        started = write(prepared/'recovery_started.json', {'kind': KIND+'_started',
            'at': datetime.now(timezone.utc).isoformat(),
            'recovery_manifest': reference(prepared/'recovery_manifest.json'),
            'evaluation_output': str(destination), 'parent_terminal': frozen['parent']['terminal'],
            'material_task_version': frozen['material_task_version'], 'recovery_index': 1,
            'phase': 'development', 'concurrency': 1, 'selection_history_inventory': current_history,
            'first_attempt_usage': frozen['parent']['first_attempt_usage'], 'qualified': False})
    # The durable started receipt spends the only recovery even if launch fails.
    # Releasing the global lock lets unrelated cold preparations run; they still
    # reject this material's immutable reservation and started receipt.
    from sheets_factory.evaluation.resource_observer import ResourceObserver
    import yaml
    backend = yaml.safe_load((ROOT/'config/llm.yaml').read_text()) or {}
    backend.update(model=MODEL, reasoning_effort=EFFORT, binary=frozen['parent']['native_cli_binary']['path'],
        roles={'trace_agent': {'model': MODEL, 'reasoning_effort': EFFORT}})
    observer = None
    try:
        with ResourceObserver(destination) as observer:
            result = runner.run_evaluation(prepared/'recovery_manifest.json', destination, phase='development',
                concurrency=1, project_root=ROOT, backend_config=backend, port=port,
                prior_selections=[r['path'] for r in partition['model_selections']])
        # Parent records remain unchanged after execution, including original
        # unscored result, full native token usage and zero-retry terminal.
        first.verify_mapping(frozen['source_artifacts_sha256'])
        return write(prepared/'recovery_terminal.json', {'kind': KIND+'_terminal', 'started': started,
            'evaluation_manifest': reference(destination/'evaluation_manifest.json'),
            'selection_manifest': reference(destination/'selection_manifest.json'),
            'resource_observation_receipt': observer.receipt,
            'resource_observation_finalization_error': observer.finalization_error,
            'parent_terminal': frozen['parent']['terminal'],
            'first_attempt_usage': frozen['parent']['first_attempt_usage'],
            'status': result['status'], 'score': result['score'], 'phase': 'development',
            'recovery_index': 1, 'effective_infrastructure_retries': 1, 'qualified': False,
            'further_recovery_authorized': False})
    except BaseException as error:
        write(prepared/'recovery_failure.json', {'kind': KIND+'_failure', 'started': started,
            'error_type': type(error).__name__, 'all_partial_artifacts_preserved': True,
            'parent_terminal': frozen['parent']['terminal'], 'qualified': False,
            'failure_is_not_model_zero': True, 'further_recovery_authorized': False,
            'resource_observation_receipt': getattr(observer, 'receipt', None)})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('assess', 'prepare'):
        sub = commands.add_parser(name)
        sub.add_argument('--parent-terminal', type=Path, required=True)
        sub.add_argument('--transport-diagnostic', type=Path, required=True)
        if name == 'prepare': sub.add_argument('--output', type=Path, required=True)
    sub = commands.add_parser('validate'); sub.add_argument('--prepared', type=Path, required=True)
    sub = commands.add_parser('run-development'); sub.add_argument('--prepared', type=Path, required=True)
    sub.add_argument('--output', type=Path, required=True); sub.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    if args.command == 'assess':
        frozen, lineage = assess_parent(args.parent_terminal, args.transport_diagnostic)
        records = history(frozen['material_task_version'], lineage['selection_manifest'])
        result = {'eligible': True, 'parent_terminal': lineage['terminal'],
            'material_task_version': frozen['material_task_version'], 'first_attempt_usage': lineage['first_attempt_usage'],
            'preserved_history_entries': len(records), 'recovery_policy': POLICY,
            'native_transport_profile': runner.transport_profile(), 'new_model_calls': 0, 'new_Harbor_jobs': 0}
    elif args.command == 'prepare':
        result = prepare(args.parent_terminal, args.transport_diagnostic, args.output)
    elif args.command == 'validate':
        frozen, records = validate_prepared(args.prepared)
        result = {'valid': True, 'recovery_manifest': reference(args.prepared/'recovery_manifest.json'),
            'preserved_history_entries': len(records), 'qualified': frozen['qualified']}
    else: result = run_development(args.prepared, args.output, port=args.port)
    print(json.dumps(result, indent=2, ensure_ascii=False)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
