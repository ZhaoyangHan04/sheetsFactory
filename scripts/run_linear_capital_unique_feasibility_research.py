#!/usr/bin/env python3
"""Research-only M01 uniqueness feasibility probes; original v1 stays failed."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from sheets_factory.workbook.linear_capital_portfolio import unique_feasibility_research as query
from sheets_factory.workbook.linear_capital_portfolio import finance_crosscheck

ORIGINAL = ROOT/'outputs/research/linear_intermediate_competitive_reference_triple_actual_20261031T084500Z/M01'
COLD = ROOT/'outputs/research/linear_M01_completed_nonoptimal_readonly_20261031T102700Z/receipt.json'
COLD_SHA256 = '56dcb5a73e59b5ddb2785c18466ae63ba003e6d10c046f6bac1ffddef3ecdf57'
runtime = query.make_runtime()
require = query.require


def original_entry():
    definition = importlib.util.spec_from_file_location('_original_producer_reference_readonly', ROOT/'scripts/run_linear_capital_producer_reference.py')
    value = importlib.util.module_from_spec(definition); definition.loader.exec_module(value)
    return value


def ref(path): return runtime.reference(path)
def read(record):
    if isinstance(record, (str, Path)): record = ref(record)
    require(ref(record['path']) == record, 'A frozen research artifact changed')
    return runtime._read(record['path'])


def recipes():
    original = original_entry()
    paths = [Path(__file__), Path(query.__file__), ROOT/'tests/test_linear_capital_unique_feasibility_research.py']
    return {**original.recipes(), **{str(p): ref(p) for p in paths}}


def ancestry():
    """Revalidate the completed original best and both complete financial matrices."""
    original = original_entry()
    require(ref(COLD)['sha256'] == COLD_SHA256, 'The approved cold M01 review changed')
    cold = read(COLD)
    require(cold['unproven_uniqueness'] is True and cold['qualified'] is False and cold['task_count'] == 0,
        'The original failed-reference boundary changed')
    terminal = read(ORIGINAL/'terminal.json'); preparation = read(terminal['preparation'])
    require(terminal['passed'] is False, 'The frozen original v1 outcome must remain failed')
    finance = original._checked_finance(preparation['financial_crosscheck'])
    best = original.validate_solver_receipt(preparation['best_preparation'], terminal['solver_receipts']['best'],
        model=finance['models']['B'], backend='cp_sat')
    require(best['checked_optimal'] is True and best['solver']['status'] == 'OPTIMAL', 'The original best must be independently checked OPTIMAL')
    require(read(terminal['solver_validations']['best']) == best, 'The retained original best validation differs from its fresh read-only check')
    winner = best['solver']['plan']; objective = best['solver']['objective_pence']
    require(objective == 795934597 and sum(winner.values()) == 93, 'The approved M01 original winner changed')
    declarations = {side: query.query(model, winner) for side, model in finance['model_values'].items()}
    require(all(v['original_binary_variables'] == 240 and v['original_le_rows'] == 881 and v['threshold_pence'] == objective
        for v in declarations.values()), 'Both complete 240-flag / 881-row query matrices are required')
    financial = finance_crosscheck.compare_plans(finance['public'], finance['A'], finance['B'],
        [{'id': 'original_winner', 'plan': winner}], require_feasible=True)
    require(financial['passed'] is True, 'The independently checked complete winner financial postings differ')
    return {'cold_readonly_receipt': ref(COLD), 'original_failed_terminal': ref(ORIGINAL/'terminal.json'),
        'original_preparation': terminal['preparation'], 'original_best_preparation': preparation['best_preparation'],
        'original_best_terminal': terminal['solver_receipts']['best'], 'original_best_validation': terminal['solver_validations']['best'],
        'financial_crosscheck': finance['terminal'], 'models': finance['models'],
        'specification': finance['specification'], 'raw_preparation': finance['raw_preparation'],
        'universe_A': finance['universe_A'], 'universe_B': finance['universe_B'],
        'winner': winner, 'objective_pence': objective, 'queries': declarations,
        'winner_financial_comparison': financial}, finance


def prepare_existing_memo(output, memo):
    # The directory may contain only the already-written prospective memo.
    output = Path(output).absolute(); memo = Path(memo).absolute()
    require(output == output.resolve() and output.is_relative_to(ROOT/'outputs/research') and output.is_dir()
        and memo == output/'memo.md' and set(p.name for p in output.iterdir()) == {'memo.md'},
        'The fresh research directory may initially contain only memo.md')
    lineage, _ = ancestry()
    jobs = {backend: runtime.prepare(lineage['models'][side]['path'], output/'jobs'/backend,
        backend=backend, time_limit_seconds=900, exclude_plan=lineage['winner'])
        for backend, side in (('cp_sat', 'B'), ('scip', 'A'))}
    freeze = {'kind': 'prospective_'+query.KIND, 'version': 1, 'integration_revision': 2, 'ancestry': lineage,
        'memo': ref(memo), 'recipes': recipes(), 'jobs': jobs,
        'probe_order': ['cp_sat', 'scip'], 'maximum_actual_engineering_probes': 2,
        'native_seconds_per_probe': 900, 'cpus': 16, 'memory_bytes': 32*1024**3,
        'pids_limit': 256, 'network': 'none', 'image_id': runtime.IMAGE_ID,
        'retries': 0, 'actual_solver_calls': 0, 'model_calls': 0, 'LO_calls': 0, 'source_calls': 0,
        'root_review_required_before_execution': True, 'original_v1_reference_passed': False,
        'exact_runner_objective': None, 'exact_gap_pence': None, 'formal_global_certificate': False,
        'source_quality_or_difficulty_certified': False, 'qualified': False, 'task_count': 0}
    return runtime._write(output/'freeze.json', freeze)


def validate_prepared(output):
    output = Path(output).absolute(); freeze = read(output/'freeze.json')
    require(freeze['kind'] == 'prospective_'+query.KIND and freeze['version'] == 1
        and type(freeze.get('integration_revision')) is int and freeze['integration_revision'] == 2 and freeze['recipes'] == recipes(),
        'The prospective research implementation changed')
    lineage, finance = ancestry()
    require(freeze['ancestry'] == lineage and ref(freeze['memo']['path']) == freeze['memo'] and freeze['probe_order'] == ['cp_sat', 'scip']
        and freeze['maximum_actual_engineering_probes'] == 2 and freeze['retries'] == 0,
        'The prospective ancestry, query order, or maximum attempts changed')
    expected = {'native_seconds_per_probe': 900, 'cpus': 16, 'memory_bytes': 32*1024**3,
        'pids_limit': 256, 'network': 'none', 'image_id': runtime.IMAGE_ID,
        'actual_solver_calls': 0, 'model_calls': 0, 'LO_calls': 0, 'source_calls': 0,
        'root_review_required_before_execution': True, 'original_v1_reference_passed': False,
        'exact_runner_objective': None, 'exact_gap_pence': None, 'formal_global_certificate': False,
        'source_quality_or_difficulty_certified': False, 'qualified': False, 'task_count': 0}
    require(all(type(freeze.get(k)) is type(v) and freeze[k] == v for k, v in expected.items()), 'The research resource or proof boundary changed')
    for backend, side in (('cp_sat', 'B'), ('scip', 'A')):
        job = runtime.validate_prepared(Path(freeze['jobs'][backend]['path']).parent)
        require(ref(output/'jobs'/backend/'preparation.json') == freeze['jobs'][backend]
            and job['model_input'] == lineage['models'][side]
            and job['request']['backend'] == backend and job['request']['exclude_plan'] == lineage['winner'],
            'The frozen query matrix, backend, or complete winner changed')
    return freeze, finance


def validate_actual(freeze, finance, backend, receipt):
    """Read retained resources and exact A/B rows before accepting a conclusion."""
    value = read(receipt); job_ref = freeze['jobs'][backend]; job = read(job_ref)
    require(value['kind'] == 'execution_'+query.KIND and value['preparation'] == job_ref
        and value.get('actual_resources_verified') is True and type(value.get('exit_code')) is int and value['exit_code'] == 0
        and value.get('oom_killed') is False and value['image_id'] == runtime.IMAGE_ID,
        'The native query did not complete with verified actual resources')
    folder = Path(job_ref['path']).parent; cid = value['container_id']
    before, after = (read(folder/name) for name in ('host_before.json', 'host_after.json'))
    runtime.validate_resources(before, cid, Path(job['bundle'])); runtime.validate_resources(after, cid, Path(job['bundle']))
    require(before['Name'] == after['Name'] == '/sf-unique-query-'+job['request']['nonce']
        and before['State']['Status'] == 'created' and before['State']['Running'] is False
        and after['State']['Status'] == 'exited' and after['State']['Running'] is False
        and type(after['State']['ExitCode']) is int and after['State']['ExitCode'] == 0 and after['State']['OOMKilled'] is False,
        'The exact owned query container state changed')
    cleanup = read(value['cleanup'])
    require(cleanup['owned_container_id'] == cid and cleanup['removed_and_absent_with_daemon_reachable'] is True
        and cleanup['returncode'] == 0 and cleanup['absence_inspect']['returncode'] != 0
        and 'no such object' in cleanup['absence_inspect']['stderr'].lower()
        and cleanup['daemon_image_check']['returncode'] == 0 and cleanup['daemon_image_check']['stdout'].strip() == runtime.IMAGE_ID,
        'The exact owned container cleanup was not verified')
    current = runtime._inventory(Path(job['bundle']))
    require(current == value['complete_job_inventory'] and current == value['retained_job_inventory']
        and all(current.get(k) == v for k, v in job['bundle_inventory'].items()), 'The retained native evidence changed')
    solver = read(value['solver_result'])
    checks = {side: query.check_result(model, {**solver, 'query': freeze['ancestry']['queries'][side]}, freeze['ancestry']['winner'])
        for side, model in finance['model_values'].items()}
    # The original solver result must carry its own (non-substituted) exact matrix query.
    side = 'B' if backend == 'cp_sat' else 'A'
    require(solver['query'] == freeze['ancestry']['queries'][side] and value['matrix_result_check'] == checks[side],
        'The native result query or exact matrix check differs')
    financial = None
    if solver['plan'] is not None:
        financial = finance_crosscheck.compare_plans(finance['public'], finance['A'], finance['B'],
            [{'id': 'alternative', 'plan': solver['plan']}], require_feasible=True)
        require(financial['passed'] is True, 'The alternative complete independent financial postings differ')
    return {'backend': backend, 'terminal': receipt, 'native_result': value['solver_result'],
        'checks': checks, 'alternative_financial_comparison': financial}


def execute_prepared(output, reviewed_sha256):
    from sheets_factory.core.audit import AuditStore
    from sheets_factory.dashboard import DashboardServer
    from sheets_factory.resume import ProducerLease
    output = Path(output).absolute(); freeze_ref = ref(output/'freeze.json')
    require(reviewed_sha256 == freeze_ref['sha256'], 'Execution requires the exact freeze SHA reviewed by the root agent')
    freeze, finance = validate_prepared(output)
    require(not (output/'started.json').exists(), 'Preserve the first research attempt; no retry is authorized')
    lease = ProducerLease(output).acquire()
    try:
        require(not (output/'started.json').exists(), 'Preserve the first research attempt; no retry is authorized')
    except BaseException:
        lease.release()
        raise
    audit = server = progress = None; validations = {}; receipts = {}; failure = None
    clock = time.monotonic(); started_at = runtime._now(); dashboard_url = None
    backend_statuses = {backend: 'pending' for backend in freeze['probe_order']}
    backend_durations = {}; backend_progress = {}; nodes = {}; stage = {'value': 'starting_research_run'}
    cleanup_errors = []
    try:
        runtime._write(output/'started.json', {'reviewed_freeze_sha256': reviewed_sha256, 'at': started_at,
            'producer_pid': os.getpid()})
        audit = AuditStore(output/'audit', {'id': output.name, 'name': 'M01 research uniqueness feasibility queries',
            'status': 'running', 'target_count': 0, 'producer_active': True, 'producer_pid': os.getpid()})
        server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=0)
        dashboard_url = server.start()
        runtime._write(output/'dashboard.json', {'dashboard_url': dashboard_url, 'freeze': freeze_ref})
        audit.update_run(dashboard_url=dashboard_url, active_stage=stage['value'], backend_statuses=backend_statuses,
            backend_duration_seconds=backend_durations)
        for backend in freeze['probe_order']:
            nodes[backend] = audit.record('nodes', {'node': 'research_uniqueness_'+backend, 'backend': backend,
                'status': 'pending', 'duration_ms': 0})
        audit.export()
        print(json.dumps({'dashboard_url': dashboard_url, 'output': str(output), 'producer_pid': os.getpid()}), flush=True)
        for backend in freeze['probe_order']:
            backend_clock = time.monotonic(); backend_statuses[backend] = 'running'
            stage['value'] = 'research_query_'+backend
            audit.update_run(active_stage=stage['value'], backend_statuses=backend_statuses)
            audit.update_record('nodes', nodes[backend], {'status': 'running', 'started_at': runtime._now(), 'stage': stage['value']})
            progress = runtime._Progress(audit, output/'jobs'/backend, backend, backend_clock, nodes[backend], stage)
            progress.start()
            try:
                receipts[backend] = runtime.execute_prepared(output/'jobs'/backend)
                stage['value'] = 'validating_research_query_'+backend
                audit.update_run(active_stage=stage['value']); audit.export()
                validations[backend] = validate_actual(freeze, finance, backend, receipts[backend])
                backend_statuses[backend] = validations[backend]['checks']['A']['status']
            except runtime.OptimizationRuntimeError as error:
                backend_statuses[backend] = 'execution_failed'
                if error.receipt: receipts[backend] = error.receipt
                raise
            except BaseException:
                backend_statuses[backend] = 'execution_failed'
                raise
            finally:
                backend_durations[backend] = time.monotonic() - backend_clock
                stopped = progress.stop()
                backend_progress[backend] = {'thread_stopped': stopped, 'errors': progress.errors, 'interval_seconds': 15}
                require(stopped, 'The research run progress thread did not stop')
                progress = None
                audit.update_record('nodes', nodes[backend], {'status': backend_statuses[backend],
                    'duration_ms': round(backend_durations[backend]*1000), 'finished_at': runtime._now()})
                audit.update_run(backend_statuses=backend_statuses, backend_duration_seconds=backend_durations)
                audit.export()
        states = [v['checks']['A']['status'] for v in validations.values()]
        require(not ('research_unique_by_native_infeasibility' in states and 'research_ambiguous_tied_optimum' in states),
            'Independent feasibility backends disagree')
    except BaseException as error:
        failure = {'type': type(error).__name__, 'error': str(error)}
    finally:
        # Attempt every owned cleanup even if an earlier cleanup raises.
        for name, close in (
            ('progress_stop', lambda: require(progress.stop(), 'The research run progress thread did not stop') if progress else None),
            ('audit_finish', lambda: (audit.update_run(status='failed' if failure else 'completed', producer_active=False,
                active_stage='research_failed' if failure else 'research_completed', finished_at=runtime._now()), audit.export()) if audit else None),
            ('dashboard_stop', lambda: server.stop() if server else None),
            ('audit_db_close', lambda: audit.db.close() if audit else None),
            ('producer_lease_release', lease.release)):
            try: close()
            except BaseException as error:
                cleanup_errors.append({'stage': name, 'type': type(error).__name__, 'error': str(error)})
        if cleanup_errors and failure is None: failure = cleanup_errors[0]
    terminal = {'kind': query.KIND, 'version': 1, 'freeze': freeze_ref, 'solver_receipts': receipts,
        'validations': validations, 'execution_failed': failure is not None, 'failure': failure,
        'dashboard_url': dashboard_url, 'started_at': started_at, 'finished_at': runtime._now(),
        'elapsed_seconds': time.monotonic()-clock, 'backend_statuses': backend_statuses,
        'backend_duration_seconds': backend_durations, 'backend_progress': backend_progress, 'lifecycle_cleanup_errors': cleanup_errors,
        'unique_by_native_infeasibility': failure is None and any(v['checks']['A']['unique_by_native_infeasibility'] for v in validations.values()),
        'ambiguous_tied_optimum': failure is None and any(v['checks']['A']['ambiguous_tied_optimum'] for v in validations.values()),
        'original_v1_reference_passed': False, 'exact_runner_objective': None, 'exact_gap_pence': None,
        'formal_global_certificate': False, 'source_quality_or_difficulty_certified': False,
        'model_calls': 0, 'LO_calls': 0, 'source_calls': 0, 'qualified': False, 'task_count': 0}
    return runtime._write(output/'terminal.json', terminal)


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'validate', 'run'):
        child = sub.add_parser(name); child.add_argument('--output', type=Path, required=True)
        if name == 'run': child.add_argument('--review-freeze-sha256', required=True)
    args = parser.parse_args()
    if args.command == 'prepare': result = prepare_existing_memo(args.output, args.output/'memo.md')
    elif args.command == 'validate':
        freeze, _ = validate_prepared(args.output)
        result = {'validated': True, 'freeze': ref(args.output/'freeze.json'), 'actual_solver_calls': 0}
    else: result = execute_prepared(args.output, args.review_freeze_sha256)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__': main()
