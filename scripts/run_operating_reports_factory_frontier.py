#!/usr/bin/env python3
"""Freeze engineered spreadsheet batches and run one native attempt per phase."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard.server import DashboardServer
from sheets_factory.evaluation import linear_capital_scaled_frontier_v6 as runner
from sheets_factory.evaluation import resource_observer, streaming_verifier, thread_capped_harbor_export
from sheets_factory.evaluation.resource_observer import ResourceObserver, validate_observation_receipt
from sheets_factory.evaluation.thread_capped_harbor_export import inspect_resource_export
from sheets_factory.task_adapters import heterogeneous_formula_identity
import yaml

KIND = 'prepared_operating_reports_factory_frontier_v6'
TERMINAL_KIND = 'operating_reports_factory_frontier_terminal_v6'
BUDGET = {'version': 1, 'elapsed_policy': 'operational_guard', 'tool_budget_seconds': 1800, 'elapsed_guard_seconds': 14400}
PROFILE = ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml'
HISTORY = ROOT / 'scripts/prepare_linear_capital_development.py'
HISTORY_SHA = '5bafc37a217545fe96d79a97c834c1439b6b1b859f38efeaa95223e941d51ba4'
RESERVATIONS = ROOT / 'outputs/difficulty/.factory_native_phase_reservations_v1'
OLD_RESERVATIONS = tuple(ROOT / 'outputs' / p / '.native_development_material_reservations' for p in ('difficulty', 'research'))
MODES = ('financial_modeling', 'debugging')
_HELPER = None
_SESSIONS = {}


def require(value, message):
    if not value:
        raise ValueError(message)


def ref(path):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_file(), 'Use a real nonsymlink file')
    before = path.stat()
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            digest.update(block)
    after = path.stat()
    require((before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'A file changed during hashing')
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': after.st_size}


def checked(value):
    if isinstance(value, (str, Path)):
        return ref(value)
    require(type(value) is dict and set(value) == {'path', 'sha256', 'bytes'} and ref(value['path']) == value,
            'A complete artifact reference changed')
    return value


def read(value):
    return json.loads(Path(checked(value)['path']).read_text())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
    return ref(path)


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def helper():
    global _HELPER
    require(ref(HISTORY)['sha256'] == HISTORY_SHA, 'The original logical identity helper changed')
    if _HELPER is None:
        spec = importlib.util.spec_from_file_location('_factory_frontier_pure_identity', HISTORY)
        _HELPER = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_HELPER)
    return _HELPER


def recipes():
    runner.verify_dependencies()
    return {'implementation': ref(__file__), 'identity_helper': ref(HISTORY), 'profile': ref(PROFILE),
            'native_v6': runner._provenance(), 'observer': ref(resource_observer.__file__),
            'export_inspector': ref(thread_capped_harbor_export.__file__),
            'typed_comparison': ref(streaming_verifier.__file__), 'formula_identity': ref(heterogeneous_formula_identity.__file__)}


@contextmanager
def monitor(directory, stage, port=0):
    directory = Path(directory)
    audit = AuditStore(directory, {'id': directory.name, 'status': 'running', 'stage': stage})
    server = DashboardServer(audit.snapshot, audit.events, port=port)
    url = server.start()
    write(directory / 'dashboard.json', {'url': url})
    audit.update_run(dashboard_url=url)
    print(json.dumps({'dashboard_url': url, 'stage': stage}), flush=True)
    try:
        yield audit
    except BaseException as error:
        audit.update_run(status='failed', stage=stage, error_type=type(error).__name__)
        raise
    finally:
        audit.export()
        server.stop()


def material_identity(task, cache):
    directory = Path(task['task_directory'])
    def book(path, formulas=False):
        record = ref(path)
        key = (record['sha256'], record['bytes'], formulas)
        if key not in cache:
            cache[key] = helper().workbook_identity(path, formulas=formulas)
        require(ref(path) == record, 'A workbook changed during logical inspection')
        return deepcopy(cache[key])
    core = {'mode': task['mode'], 'input_definitions': book(directory / 'environment/input.xlsx', True),
            'input_values': book(directory / 'environment/input.xlsx'),
            'goal_values': book(directory / 'tests/reference.xlsx'),
            'instruction_sha256': ref(directory / 'instruction.md')['sha256']}
    return {**core, 'sha256': canonical(core)}


def check_task(task):
    require(task['mode'] in MODES and Path(task['task_id']).name == task['task_id'], 'Use supported categories and safe task IDs')
    require(task['execution_budget'] == BUDGET, 'Every task must retain the strict 1800/14400 budget')
    directory = Path(task['task_directory']).absolute()
    require(directory == directory.resolve() and directory.is_dir()
            and not any(p.is_symlink() for p in directory.rglob('*')), 'Use a complete real task export')
    require({p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()} == runner.TASK_FILES,
            'The export must contain exactly the existing seventeen resource files')
    checked(task['worker_cap_audit'])
    require(inspect_resource_export(directory, audit_path=task['worker_cap_audit']) == task['harbor_export_binding'],
            'The actual resource export or worker cap changed')
    require(ref(directory / 'tests/reference.xlsx')['sha256'] == task['source_id'], 'The healthy goal differs from its declared source')
    engineering = read(task['individual_engineering'])
    require(engineering['passed'] is True and engineering['native_error_count'] == 0
            and engineering['given_literals_unchanged'] is engineering['sheet_structure_unchanged'] is True
            and engineering['complete_primary_difference_count'] == len(engineering['complete_primary_difference']) > 0
            and len(set(engineering['complete_primary_difference'])) == len(engineering['complete_primary_difference']),
            'Keep the genuine complete individual native input audit')
    plans = read(task['plan_freeze'])
    require(plans['execution_budget'] == BUDGET and plans['runtime_profile'] == ref(PROFILE)
            and any(row['mode'] == task['mode'] and row['plan']['variant_id'] == task['variant_id'] for row in plans['plans']),
            'The task must belong to the original predeclared engineering plan')
    return {name: ref(directory / name) for name in sorted(runner.TASK_FILES)}


def prepare(batches, output, *, phase='development', task_ids=None, development=None, port=0):
    output = Path(output).absolute()
    require(output == output.resolve() and not output.exists(), 'Use a fresh private batch preparation')
    require(phase in ('development', 'confirmation'), 'Declare the attempt phase')
    with monitor(output / 'preparation_monitor', 'material_admission', port) as audit:
        before = recipes()
        batch_refs = [checked(b) for b in batches]
        tasks = []
        for record in batch_refs:
            batch = read(record)
            require(batch['kind'] == 'individually_engineered_operating_report_batch' and batch['version'] == 1
                    and batch['count'] == len(batch['tasks'])
                    and batch['selected_task_ids'] == [t['task_id'] for t in batch['tasks']], 'Use complete engineered batch manifests')
            tasks.extend(deepcopy(batch['tasks']))
        require(len({t['task_id'] for t in tasks}) == len(tasks), 'Batch task IDs must be unique')
        requested = list(task_ids) if task_ids is not None else [t['task_id'] for t in tasks]
        require(requested and len(set(requested)) == len(requested) and set(requested) <= {t['task_id'] for t in tasks},
                'Select distinct explicit existing task IDs')
        tasks = [t for t in tasks if t['task_id'] in set(requested)]
        if phase == 'confirmation':
            require(Counter(t['mode'] for t in tasks) == Counter({'financial_modeling': 10, 'debugging': 10}) and development,
                    'Freeze exactly ten tasks per mode with retained development provenance')
        cache, materials, inventories = {}, {}, {}
        for task in tasks:
            audit.task(task['task_id'], mode=task['mode'], status='running', stage='logical_identity')
            inventories[task['task_id']] = check_task(task)
            materials[task['task_id']] = material_identity(task, cache)
            audit.task(task['task_id'], status='ready', stage='frozen_material')
            audit.export()
        require(len({v['sha256'] for v in materials.values()}) == len(tasks), 'Aliases do not create independent candidates')
        development_ref = checked(development) if development else None
        if development_ref:
            prior = read(development_ref)
            require(prior['kind'] == TERMINAL_KIND and prior['phase'] == 'development', 'Bind the completed development phase')
            checked(prior['selection'])
            checked(prior['evaluation'])
            previous = {r['material_identity']['sha256']: r for r in prior['results'] if r.get('actual_attempt')}
            require(all(v['sha256'] in previous for v in materials.values()), 'Each confirmation material needs its original development attempt')
        require(recipes() == before, 'The batch runtime code changed during preparation')
        source = write(output / 'source_manifest.json', {'kind': 'operating_reports_factory_native_source_v6', 'version': 1,
            'tasks': tasks, 'selected_task_ids': [t['task_id'] for t in tasks], 'execution_budget': BUDGET,
            'tool_time_policy_version': 6, 'tool_time_policy': dict(runner.POLICY_V6),
            'native_transport_profile': runner.transport_profile(), 'qualified': False,
            'per_instance_normal_QA_claimed': False, 'shared_semantic_review_and_actual_controls_pending': True})
        frozen = {'kind': KIND, 'version': 1, 'phase': phase, 'batches': batch_refs,
            'source': source, 'tasks': tasks, 'materials': materials, 'export_files': inventories, 'recipe': before,
            'development': development_ref, 'selection_frozen_before_model': True, 'attempts_per_task': 1,
            'model': 'gpt-6.1-sol', 'reasoning_effort': 'xhigh', 'outer_retries': 0, 'qualified': False,
            'shared_goal_identity_cache_entries': len(cache), 'model_calls': 0, 'LO_calls': 0}
        result = write(output / 'prepared.json', frozen)
        _SESSIONS[(str(output), result['sha256'])] = deepcopy(frozen)
        audit.update_run(status='completed', stage='prepared', task_count=len(tasks))
        return result


def validate_prepared(output):
    prepared_ref = ref(Path(output) / 'prepared.json')
    prepared = read(prepared_ref)
    require(prepared['kind'] == KIND and prepared['version'] == 1 and prepared['recipe'] == recipes(), 'The prepared batch or runtime changed')
    for record in prepared['batches']:
        checked(record)
    source = read(prepared['source'])
    require(source['tasks'] == prepared['tasks'] and source['selected_task_ids'] == [t['task_id'] for t in prepared['tasks']]
            and source['execution_budget'] == BUDGET and prepared['phase'] in ('development', 'confirmation')
            and source['tool_time_policy_version'] == 6 and source['tool_time_policy'] == dict(runner.POLICY_V6)
            and source['native_transport_profile'] == runner.transport_profile(), 'The prospective native source changed')
    warm = _SESSIONS.get((str(Path(output).absolute()), prepared_ref['sha256']))
    cache = {}
    for task in prepared['tasks']:
        require(check_task(task) == prepared['export_files'][task['task_id']], 'An exported task changed after freeze')
        require((warm is not None and warm == prepared)
                or material_identity(task, cache) == prepared['materials'][task['task_id']],
                'The complete logical material differs from its frozen identity')
    if prepared['development']:
        checked(prepared['development'])
    return prepared


def reserve(prepared_ref, prepared):
    root = Path(RESERVATIONS).absolute()
    root.mkdir(parents=True, exist_ok=True)
    require(root == root.resolve(), 'Use the real permanent reservation directory')
    paths = []
    with (root / 'phase.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        for task in prepared['tasks']:
            identity = prepared['materials'][task['task_id']]
            core = {k: v for k, v in identity.items() if k != 'sha256'}
            require(canonical(core) == identity['sha256'], 'A logical material identity changed')
            if prepared['phase'] == 'development':
                require(not any((Path(p) / (identity['sha256'] + '.json')).exists() for p in OLD_RESERVATIONS),
                        'This logical material already spent an earlier development reservation')
            path = root / prepared['phase'] / (identity['sha256'] + '.json')
            require(not path.exists() and not path.is_symlink(), 'This material and phase already reserved its one attempt')
            paths.append((path, task, identity))
        return [write(path, {'kind': 'permanent_factory_native_material_phase_reservation', 'version': 1,
            'phase': prepared['phase'], 'task_id': task['task_id'], 'material_identity': identity,
            'prepared': prepared_ref, 'outer_retries': 0, 'no_retry_after_success_failure_or_infrastructure': True})
            for path, task, identity in paths]


def effective_score(attempt, resources):
    raw = attempt.get('raw_verifier_reward', attempt.get('reward'))
    timing = attempt.get('tool_time') or {}
    valid = resources.get('passed') is True and resources.get('complete') is True
    budget = valid and attempt.get('status') == 'scored' and attempt.get('failure_kind') == 'cumulative_tool_budget_exhausted' and timing.get('passed') is False
    complete = valid and attempt.get('status') == 'scored' and not attempt.get('failure_kind') and timing.get('passed') is True and type(raw) in (int, float) and raw in (0, 1)
    return {'raw_verifier_reward': raw, 'effective_reward': 0 if budget else raw if complete else None,
            'state': 'known_tool_budget_failure' if budget else 'complete' if complete else 'unknown',
            'infrastructure_unknown_is_not_model_zero': not budget and not complete}


def run(output, *, concurrency=16, port=0):
    output = Path(output).absolute()
    require(type(concurrency) is int and 1 <= concurrency <= 20, 'Use one through twenty parallel native contexts')
    with monitor(output / 'execution_monitor', 'pre_model_freeze', port) as audit:
        prepared = validate_prepared(output)
        reservation = reserve(ref(output / 'prepared.json'), prepared)
        write(output / 'started.json', {'reservations': reservation, 'concurrency': concurrency, 'phase': prepared['phase'], 'outer_retries': 0})
        evaluation_dir = output / 'evaluation'
        backend = yaml.safe_load((ROOT / 'config/llm.yaml').read_text())
        backend.update(model='gpt-6.1-sol', reasoning_effort='xhigh', roles={'trace_agent': {'model': 'gpt-6.1-sol', 'reasoning_effort': 'xhigh'}})
        audit.update_run(stage='native_evaluation', concurrency=concurrency, tasks=len(prepared['tasks']))

        async def once(directory, selection, trial_audit, *, concurrency, backend_config):
            require(selection['n_attempts'] == 1 and selection['model'] == 'gpt-6.1-sol'
                    and selection['reasoning_effort'] == 'xhigh' and selection['tool_time_policy_version'] == 6
                    and selection['execution_budget'] == BUDGET
                    and selection['infrastructure_retry_policy']['max_retries'] == 0, 'The actual native attempt contract changed')
            await runner.execute_evaluation(directory, selection, trial_audit, concurrency=concurrency, backend_config=backend_config)

        with ResourceObserver(evaluation_dir) as observer:
            evaluation = runner.run_evaluation(prepared['source']['path'], evaluation_dir, phase=prepared['phase'],
                concurrency=concurrency, project_root=ROOT, backend_config=backend, execute=once)
        selection = read(evaluation_dir / 'selection_manifest.json')
        resources = validate_observation_receipt(evaluation_dir, selection, evaluation)
        write(output / 'resources.json', resources)
        require(not evaluation.get('infrastructure_retries'), 'No outer retry may replace an actual first attempt')
        trials = {r.get('result', {}).get('sha256'): r for r in resources.get('trials', [])}
        results = []
        for task in prepared['tasks']:
            attempts = [a for a in evaluation.get('attempts', []) if a.get('task_id') == task['task_id']]
            require(len(attempts) <= 1, 'Only one actual attempt is allowed per selected material')
            attempt = attempts[0] if attempts else {}
            per_trial = trials.get(attempt.get('result_sha256'), {'passed': False, 'complete': False})
            if evaluation.get('failure_kind') == 'snapshot_changed':
                per_trial = {'passed': False, 'complete': False}
            results.append({'task_id': task['task_id'], 'mode': task['mode'], 'variant_id': task['variant_id'],
                'material_identity': prepared['materials'][task['task_id']], 'actual_attempt': attempt,
                'resources': per_trial, 'score': effective_score(attempt, per_trial)})
        result = write(output / 'terminal.json', {'kind': TERMINAL_KIND, 'version': 1, 'phase': prepared['phase'],
            'prepared': ref(output / 'prepared.json'), 'evaluation': ref(evaluation_dir / 'evaluation_manifest.json'),
            'selection': ref(evaluation_dir / 'selection_manifest.json'), 'resource_observation': observer.receipt,
            'resources': ref(output / 'resources.json'), 'results': results, 'outer_retries': 0,
            'qualified': False, 'normal_quality_transferred': False, 'shared_source_does_not_make_independent_sources': True})
        audit.update_run(status='completed', stage='terminal', tasks=len(results))
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--batch', action='append', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--phase', choices=('development', 'confirmation'), default='development')
    p.add_argument('--task-id', action='append')
    p.add_argument('--development', type=Path)
    p.add_argument('--run', action='store_true')
    p.add_argument('--concurrency', type=int, default=16)
    p.add_argument('--port', type=int, default=0)
    p = sub.add_parser('run')
    p.add_argument('--prepared', type=Path, required=True)
    p.add_argument('--concurrency', type=int, default=16)
    p.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    if args.command == 'prepare':
        result = prepare(args.batch, args.output, phase=args.phase, task_ids=args.task_id, development=args.development, port=args.port)
        if args.run:
            result = run(args.output, concurrency=args.concurrency, port=args.port)
    else:
        result = run(args.prepared, concurrency=args.concurrency, port=args.port)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
