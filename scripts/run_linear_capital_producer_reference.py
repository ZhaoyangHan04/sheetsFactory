#!/usr/bin/env python3
"""Private producer16 best/runner reference over two checked financial matrices.

One CP-SAT search proves each status. The two financial implementations and
integer matrices are independent; this does not claim a second global search.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from sheets_factory.workbook.linear_capital_portfolio import spec, finance_crosscheck
from sheets_factory.workbook.linear_capital_portfolio import producer_optimization_runtime as runtime

KIND = 'linear_capital_producer16_best_runner_dual_financial_reference'
PREPARED = 'prepared_linear_capital_producer16_best_runner_dual_financial_reference'
TIME_LIMIT = 3600
BACKENDS = {'A': 'scip', 'B': 'cp_sat'}  # Only identifies the independent frozen matrices.
UPSTREAM_SHA256 = '1ea0ec5287a15731bdd8d38270f3ae514fabf2f0754ac1347aaeb93e51fd28c3'
require = spec.require


def validation_ast():
    """Reuse exact read-only gates, with private worker/resources/name changes."""
    path = ROOT/'scripts/run_linear_capital_reference.py'; raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == UPSTREAM_SHA256, 'The frozen reference validation gates changed')
    wanted = {'reference', 'read', 'write', '_sha', '_refs', '_checked_finance',
        '_checked_preparation', 'validate_solver_receipt'}
    tree = ast.parse(raw); tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    require({n.name for n in tree.body} == wanted, 'A frozen reference gate is missing')
    counts = {'threads': 0, 'resources': 0, 'name': 0}
    class Adapt(ast.NodeTransformer):
        def visit_Compare(self, node):
            if ast.unparse(node) in ("request['threads'] == 2", "transport['threads'] == 2", "solver['threads'] == 2"):
                node.comparators[0] = ast.Constant(16); counts['threads'] += 1
            return self.generic_visit(node)
        def visit_Dict(self, node):
            for i, key in enumerate(node.keys):
                if isinstance(key, ast.Constant) and key.value == 'cpus' and isinstance(node.values[i], ast.Constant) and node.values[i].value == 2:
                    node.values[i] = ast.Constant(16); counts['resources'] += 1
            return self.generic_visit(node)
        def visit_Constant(self, node):
            if node.value == '/sf-private-integer-':
                node.value = '/sf-producer16-integer-'; counts['name'] += 1
            return node
    tree = Adapt().visit(tree)
    require(counts == {'threads': 3, 'resources': 1, 'name': 1}, 'The exact producer reference-gate substitutions changed')
    return ast.fix_missing_locations(tree)


exec(compile(validation_ast(), __file__, 'exec'), globals())


def recipes():
    paths = [Path(__file__), ROOT/'scripts/run_linear_capital_reference.py',
        Path(runtime.__file__), runtime.PROFILE, Path(spec.__file__), Path(finance_crosscheck.__file__),
        Path(runtime.__file__).with_name('optimization_runtime.py'), *runtime._source_files().values()]
    return {str(p): reference(p) for p in paths}


def _profile():
    return {'producer_profile': runtime.profile_reference(), 'image_id': runtime.IMAGE_ID,
        'cpus': 16, 'threads': 16, 'memory_bytes': 32*1024**3, 'pids_limit': 256,
        'network': 'none', 'private_solver_seconds': TIME_LIMIT,
        'agent_and_verifier_cpus_unchanged': 2, 'agent_tool_budget_seconds_unchanged': 1800}


def prepare(finance_terminal, output):
    finance = _checked_finance(finance_terminal); output = Path(output).absolute()
    require(output == output.resolve() and output.is_relative_to(ROOT/'outputs') and not output.exists(),
        'Use a fresh private producer directory')
    output.mkdir(parents=True)
    try:
        best = runtime.prepare(finance['models']['B']['path'], output/'jobs/best', backend='cp_sat', time_limit_seconds=TIME_LIMIT)
        return write(output/'preparation.json', {'kind': PREPARED, 'version': 1,
            'financial_crosscheck': finance['terminal'], 'best_preparation': best, 'recipe': recipes(),
            'runtime_profile': _profile(), 'private_density_gate': {
                'minimum': 80, 'maximum': 160, 'public_cardinality_constraint': False},
            'global_search_implementation_count': 1, 'independent_financial_implementations': 2,
            'independent_integer_matrices': 2, 'retries': 0, 'solver_calls': 0, 'model_calls': 0, 'qualified': False})
    except BaseException as error:
        write(output/'preparation_failure.json', {'error_type': type(error).__name__, 'error': str(error),
            'all_partial_artifacts_preserved': True, 'actual_solver_calls': 0}); raise


def validate_prepared(output):
    output = Path(output).absolute(); frozen = read(output/'preparation.json')
    require(frozen.get('kind') == PREPARED and type(frozen.get('version')) is int and frozen['version'] == 1
        and frozen['recipe'] == recipes() and frozen['runtime_profile'] == _profile()
        and frozen['retries'] == 0 and type(frozen['retries']) is int and frozen['qualified'] is False
        and frozen['private_density_gate'] == {'minimum': 80, 'maximum': 160, 'public_cardinality_constraint': False}
        and type(frozen['global_search_implementation_count']) is int and frozen['global_search_implementation_count'] == 1
        and frozen['independent_financial_implementations'] == 2
        and frozen['independent_integer_matrices'] == 2 and frozen['solver_calls'] == frozen['model_calls'] == 0,
        'The private producer reference preparation changed')
    finance = _checked_finance(frozen['financial_crosscheck'])
    job = _checked_preparation(frozen['best_preparation'], finance['models']['B'], 'cp_sat', None)
    require(job['producer_profile'] == runtime.profile_reference(), 'The producer profile was not frozen before execution')
    return frozen, finance


def _checked_job(job, terminal, finance, excluded):
    require(read(job)['producer_profile'] == runtime.profile_reference(), 'The actual job producer profile changed')
    value = validate_solver_receipt(job, terminal, model=finance['models']['B'], backend='cp_sat', exclude_plan=excluded)
    require(value['checked_optimal'] is True, 'A limited or incomplete producer solve is not an optimal reference')
    solver = value['solver']
    # The same exact plan is checked independently against both complete matrices.
    matrices = {side: runtime.check_result(model, solver, excluded) for side, model in finance['model_values'].items()}
    require(all(row['checked_optimal'] is True and row['exact_matrix_plan_check']['all_integer_rows_checked'] == 881
        for row in matrices.values()), 'Both complete independent 881-row matrices are required')
    return value, matrices


def _financial(finance, winner, runner, objective, runner_objective):
    result = finance_crosscheck.compare_plans(finance['public'], finance['A'], finance['B'],
        [{'id': 'winner', 'plan': winner}, {'id': 'runner', 'plan': runner}], require_feasible=True)
    require(result['passed'] is True and result['require_group_feasible'] is True,
        'The complete independent best/runner financial checks failed')
    require(result['plans'][0]['A']['objective_pence'] == objective
        and result['plans'][1]['A']['objective_pence'] == runner_objective,
        'The native integer objectives differ from the complete financial postings')
    return result


def execute_prepared(output):
    from sheets_factory.core.audit import AuditStore
    from sheets_factory.dashboard import DashboardServer
    from sheets_factory.resume import ProducerLease
    output = Path(output).absolute(); frozen, finance = validate_prepared(output)
    require(not (output/'started.json').exists(), 'Preserve the first producer attempt; no retry is authorized')
    lease = ProducerLease(output).acquire(); audit = server = None; failure = None
    clock = time.monotonic(); receipts = {}; validations = {}; matrices = {}; terminal = None
    envelope = {'kind': KIND, 'version': 1, 'passed': False, 'preparation': reference(output/'preparation.json'),
        'financial_crosscheck': finance['terminal']}
    try:
        audit = AuditStore(output/'audit', {'id': output.name, 'status': 'running', 'target_count': 0,
            'name': 'Private producer16 global best and runner, independent A/B finance', 'producer_active': True})
        server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=0); url = server.start()
        write(output/'started.json', {'preparation': reference(output/'preparation.json'),
            'at': datetime.now(timezone.utc).isoformat(), 'dashboard_url': url})
        audit.update_run(dashboard_url=url); audit.export(); print(json.dumps({'dashboard_url': url, 'output': str(output)}), flush=True)
        def solve(name, job, excluded):
            audit.update_run(active_stage=name); audit.export()
            folder = Path(job['path']).parent
            require(not (folder/'started.json').exists(), 'A producer job has already started; do not rerun it')
            try:
                receipt = runtime.execute_prepared(folder)
            except BaseException as error:
                if getattr(error, 'receipt', None): receipts[name] = error.receipt
                raise
            receipts[name] = receipt
            checked, cross = _checked_job(job, receipt, finance, excluded)
            validations[name] = write(output/(name+'_validation.json'), checked)
            matrices[name] = cross
            return checked['solver']
        best = solve('best', frozen['best_preparation'], None)
        winner = best['plan']; selected = sum(winner.values())
        require(80 <= selected <= 160, 'The prospective private source-density gate failed')
        runner_job = runtime.prepare(finance['models']['B']['path'], output/'jobs/runner', backend='cp_sat',
            time_limit_seconds=TIME_LIMIT, exclude_plan=winner)
        runner_ref = write(output/'runner_preparation.json', {'runner_preparation': runner_job, 'complete_excluded_plan': winner})
        runner = solve('runner', runner_job, winner)
        objective, other = best['objective_pence'], runner['objective_pence']
        require(type(objective) is int and type(other) is int and objective-other >= 1,
            'A unique best requires a positive posted-pence complete-plan runner gap')
        financial = _financial(finance, winner, runner['plan'], objective, other)
        financial_ref = write(output/'reference_validation.json', financial)
        envelope.update(passed=True, specification=finance['specification'], specification_sha256=spec.canonical_sha256(finance['public']),
            raw_preparation=finance['raw_preparation'], universe_A=finance['universe_A'], universe_B=finance['universe_B'],
            model_A=finance['models']['A'], model_B=finance['models']['B'], solver_receipts=receipts,
            solver_validations=validations, matrix_crosschecks=matrices, runner_preparation=runner_ref,
            winner_plan=winner, winner_objective_pence=objective, runner_plan=runner['plan'],
            runner_objective_pence=other, gap_pence=objective-other, unique_best=True,
            selected_project_count=selected, selection_density_passed=True, private_density_gate=frozen['private_density_gate'],
            reference_validation=financial_ref, runtime_profile=_profile(),
            global_search_implementation_count=1, independent_second_global_search_claimed=False,
            independent_financial_implementations=2, independent_integer_matrices=2,
            solver_status_is_not_formal_certificate=True, source_or_quality_or_difficulty_certified=False,
            model_calls=0, LO_calls=0, qualified=False, task_count=0)
        _refs(frozen['recipe'])
    except BaseException as error:
        failure = error
        envelope.update(error_type=type(error).__name__, error=str(error), solver_receipts=receipts,
            solver_validations=validations, matrix_crosschecks=matrices, runtime_profile=_profile(),
            source_or_quality_or_difficulty_certified=False, model_calls=0, LO_calls=0, qualified=False, task_count=0)
        write(output/'failure.json', {'error_type': type(error).__name__, 'error': str(error),
            'all_actual_attempts_preserved': True, 'retry_authorized': False, 'failure_is_not_model_zero': True})
    finally:
        try:
            envelope.update(finished_at=datetime.now(timezone.utc).isoformat(), elapsed_seconds=time.monotonic()-clock)
            terminal = write(output/'terminal.json', envelope)
            if audit: audit.update_run(status='passed' if failure is None else 'failed', producer_active=False); audit.export()
        finally:
            try:
                if server: server.stop()
            finally:
                try:
                    if audit: audit.db.close()
                finally: lease.release()
    return terminal


def validate_completed(value):
    record = reference(value) if isinstance(value, (str, Path)) else value; result = read(record)
    require(result.get('kind') == KIND and type(result.get('version')) is int and result['version'] == 1
        and result.get('passed') is True, 'A complete producer16 global reference is required')
    output = Path(result['preparation']['path']).parent; frozen, finance = validate_prepared(output)
    require(result['preparation'] == reference(output/'preparation.json')
        and result['financial_crosscheck'] == finance['terminal'] and result['specification'] == finance['specification']
        and result['raw_preparation'] == finance['raw_preparation'] and result['universe_A'] == finance['universe_A']
        and result['universe_B'] == finance['universe_B'] and result['model_A'] == finance['models']['A']
        and result['model_B'] == finance['models']['B'] and result['specification_sha256'] == spec.canonical_sha256(finance['public']),
        'The independent financial and matrix ancestry changed')
    require(set(result['solver_receipts']) == set(result['solver_validations']) == {'best', 'runner'},
        'Exactly one best and one complete-plan-excluded runner attempt are required')
    winner = spec.validate_plan(finance['public'], result['winner_plan'])
    declaration = read(result['runner_preparation'])
    require(declaration['complete_excluded_plan'] == winner, 'The full winner exclusion changed')
    checked = {}; matrices = {}
    for name, job in (('best', frozen['best_preparation']), ('runner', declaration['runner_preparation'])):
        checked[name], matrices[name] = _checked_job(job, result['solver_receipts'][name], finance, None if name == 'best' else winner)
        require(read(result['solver_validations'][name]) == checked[name], 'A runtime validation receipt changed')
    best, runner = checked['best']['solver'], checked['runner']['solver']
    require(result['matrix_crosschecks'] == matrices and best['plan'] == winner and runner['plan'] == result['runner_plan']
        and type(result['winner_objective_pence']) is int and result['winner_objective_pence'] == best['objective_pence']
        and type(result['runner_objective_pence']) is int and result['runner_objective_pence'] == runner['objective_pence']
        and type(result['gap_pence']) is int and result['gap_pence'] == best['objective_pence']-runner['objective_pence'] >= 1
        and result['unique_best'] is True, 'The global best/runner or positive integer gap changed')
    expected = _financial(finance, winner, runner['plan'], best['objective_pence'], runner['objective_pence'])
    require(read(result['reference_validation']) == expected, 'The complete A/B best/runner financial checks changed')
    require(type(result['selected_project_count']) is int and result['selected_project_count'] == sum(winner.values())
        and 80 <= sum(winner.values()) <= 160 and result['selection_density_passed'] is True
        and result['private_density_gate'] == frozen['private_density_gate'], 'The private source-density gate changed')
    require(result['runtime_profile'] == _profile() and result['global_search_implementation_count'] == 1
        and type(result['global_search_implementation_count']) is int and result['independent_second_global_search_claimed'] is False
        and result['independent_financial_implementations'] == result['independent_integer_matrices'] == 2
        and result['solver_status_is_not_formal_certificate'] is True and result['source_or_quality_or_difficulty_certified'] is False
        and result['qualified'] is False and all(type(result[k]) is int and result[k] == 0 for k in ('model_calls', 'LO_calls', 'task_count')),
        'The private reference resource or proof boundary changed')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare'); p.add_argument('--finance-terminal', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    for name in ('run', 'validate', 'validate-completed'):
        p = sub.add_parser(name); p.add_argument('--receipt' if name == 'validate-completed' else '--prepared', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == 'prepare': result = prepare(args.finance_terminal, args.output)
    elif args.command == 'run': result = execute_prepared(args.prepared)
    elif args.command == 'validate': validate_prepared(args.prepared); result = {'validated': str(args.prepared), 'actual_solver_calls': 0}
    else: result = validate_completed(args.receipt)
    print(json.dumps(result, indent=2)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
