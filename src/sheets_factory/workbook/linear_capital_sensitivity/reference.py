"""Nine fixed CP600 best/runner references; all execution is explicit.

Financial postings are cold-validated once and reused. Every case must pass;
limited or rejected cases remain in the aggregate without retries or filtering.
"""
import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time

from ..linear_capital_scaled import reference as original, finance
from . import contract, oracle_a, oracle_b, runtime600 as runtime

ROOT = Path(__file__).resolve().parents[4]
ENTRY = ROOT / 'scripts/run_linear_capital_sensitivity_reference.py'
PROSPECTIVE_SHA = '540ee24c0747fe4a2aaf941dd2348207b1ef7b395ff4c2e7fb2243188cbba763'
BASE_REFERENCE_SHA = '6b38f264f3dc3c3e06213768eaa50c5944ab3bac5ab643150d1d5260b115a44c'
PREPARED = 'prepared_fixed_nine_case_CP600_best_runner_reference'
KIND = 'complete_fixed_nine_case_CP600_best_runner_reference'
CASE_KIND = 'fixed_sensitivity_case_CP600_best_runner_reference'
TIME_LIMIT = 600
require = contract.require
spec = contract.spec


def _gate_ast():
    require(runtime.reference(original.__file__)['sha256'] == BASE_REFERENCE_SHA,
            'The original exact producer receipt gates changed')
    tree = original._gate_ast(); hits = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == '/sf-scaled-producer16-integer-':
            node.value = '/sf-sensitivity9-CP600-'; hits += 1
    require(hits == 1, 'The exact owned-container name gate changed')
    return ast.fix_missing_locations(tree)


exec(compile(_gate_ast(), __file__, 'exec'), globals())


def recipes():
    paths = [Path(__file__), Path(runtime.__file__), runtime.PROFILE, ENTRY,
        Path(contract.__file__), Path(oracle_a.__file__), Path(oracle_b.__file__),
        Path(original.__file__), Path(runtime.base.__file__),
        ROOT / 'scripts/run_linear_capital_producer_reference.py',
        ROOT / 'scripts/run_linear_capital_reference.py',
        ROOT / 'src/sheets_factory/workbook/linear_capital_portfolio/producer_optimization_runtime.py',
        ROOT / 'src/sheets_factory/workbook/linear_capital_portfolio/optimization_runtime.py',
        *runtime._source_files().values()]
    return {**original.finance_recipes(), **{str(p): reference(p) for p in paths}}


def _checked_input(value):
    record = reference(value) if isinstance(value, (str, Path)) else value
    require(record['sha256'] == PROSPECTIVE_SHA, 'Use the exact all-nine prospective P02 reuse declaration')
    prospective = read(record); _refs(prospective)
    require(prospective['case_order'] == [c['id'] for c in contract.CASES]
            and prospective['version'] == 2 and prospective['future_native_searches_started'] == 0,
            'The whole ordered case inventory must precede every native preparation')
    declaration = read(prospective['contract'])
    # Original cold full A/B scope comparison and all posted diagnostic plans;
    # this helper does not execute either financial forward or a service.
    shared = original._checked_finance(prospective['financial_terminal'])
    contract.validate_contract(shared['public'], declaration)
    left = oracle_a.build_cases(shared['public'], shared['model_values']['A'], declaration)
    right = oracle_b.build_cases(shared['public'], shared['model_values']['B'], declaration)
    cases = []
    for a, b in zip(left['cases'], right['cases'], strict=True):
        require(a['case'] == b['case'] and all(a['model'][k] == b['model'][k]
                for k in a['model'] if k != 'universe_sha256'), 'The complete independent case matrices differ')
        cases.append({'case': a['case'], 'A': a['model'], 'B': b['model']})
    return {'prospective': record, 'declaration': declaration, 'shared': shared, 'cases': cases}


def prepare(prospective, output):
    output = Path(output).absolute()
    require(output == output.resolve() and output.is_relative_to(ROOT / 'outputs') and not output.exists(),
            'Use a fresh private nine-case reference directory')
    inputs = _checked_input(prospective); runtime.profile_reference(); before = recipes()
    output.mkdir(parents=True); inventory = []
    try:
        for row in inputs['cases']:
            folder = output / 'cases' / row['case']['id']; folder.mkdir(parents=True)
            models = {side: write(folder / ('model_' + side + '.json'), row[side]) for side in ('A', 'B')}
            inventory.append({'case': row['case'], 'models': models,
                'model_logical_sha256': {side: _sha(row[side]) for side in ('A', 'B')}})
        # This is immutable BEFORE the first runtime.prepare/vendor copy.
        all_models = write(output / 'all_nine_model_inventory.json', {'case_order': [c['id'] for c in contract.CASES],
            'cases': inventory, 'recipe': before, 'profile': runtime.profile_reference(),
            'prospective': inputs['prospective'], 'native_preparations_started': 0, 'native_calls': 0})
        jobs = {row['case']['id']: runtime.prepare(row['models']['B']['path'],
            output / 'cases' / row['case']['id'] / 'jobs/best', backend='cp_sat', time_limit_seconds=600)
            for row in inventory}
        require(recipes() == before, 'Implementation changed during zero-service preparation')
        return write(output / 'preparation.json', {'kind': PREPARED, 'version': 1,
            'prospective': inputs['prospective'], 'all_nine_models': all_models, 'best_preparations': jobs,
            'case_order': [c['id'] for c in contract.CASES], 'recipe': before,
            'profile': runtime.profile_reference(), 'max_parallel_cases': 2, 'maximum_native_job_invocations': 18,
            'automatic_retries': 0, 'cardinality_admission': False, 'financial_forward_calls': 0,
            'native_solver_calls': 0, 'LO_calls': 0, 'model_calls': 0, 'qualified': False})
    except BaseException as error:
        write(output / 'preparation_failure.json', {'error_type': type(error).__name__, 'error': str(error),
            'all_partial_artifacts_preserved': True, 'native_solver_calls': 0}); raise


def _job_preparation(record, model, excluded):
    value = _checked_preparation(record, model, 'cp_sat', excluded)
    require(value['producer_profile'] == runtime.profile_reference()
            and value['operational_timeout_seconds'] == 720, 'Keep the exact CP600/operational720 producer contract')
    return value


def validate_prepared(output):
    output = Path(output).absolute(); frozen = read(output / 'preparation.json')
    require(frozen.get('kind') == PREPARED and type(frozen.get('version')) is int and frozen['version'] == 1
            and frozen['recipe'] == recipes() and frozen['profile'] == runtime.profile_reference()
            and frozen['case_order'] == [c['id'] for c in contract.CASES]
            and frozen['max_parallel_cases'] == 2 and frozen['maximum_native_job_invocations'] == 18
            and type(frozen['automatic_retries']) is int and frozen['automatic_retries'] == 0
            and frozen['cardinality_admission'] is False and frozen['qualified'] is False
            and all(type(frozen[k]) is int and frozen[k] == 0
                    for k in ('financial_forward_calls', 'native_solver_calls', 'LO_calls', 'model_calls')),
            'The fixed nine-case preparation or execution boundary changed')
    inputs = _checked_input(frozen['prospective']); inventory = read(frozen['all_nine_models'])
    require(inventory['case_order'] == frozen['case_order'] and inventory['recipe'] == frozen['recipe']
            and inventory['profile'] == frozen['profile'] and inventory['prospective'] == frozen['prospective']
            and inventory['native_preparations_started'] == inventory['native_calls'] == 0
            and len(inventory['cases']) == 9 and set(frozen['best_preparations']) == set(frozen['case_order']),
            'The complete model inventory must be frozen before any native preparation')
    for row, actual in zip(inventory['cases'], inputs['cases'], strict=True):
        identity = row['case']['id']; require(row['case'] == actual['case'], 'Case identity or order changed')
        for side in ('A', 'B'):
            require(read(row['models'][side]) == actual[side]
                    and row['model_logical_sha256'][side] == _sha(actual[side]), 'A fixed case matrix changed')
        _job_preparation(frozen['best_preparations'][identity], row['models']['B'], None)
    return frozen, inputs, inventory


def _checked_job(job, receipt, row, excluded):
    _job_preparation(job, row['models']['B'], excluded)
    checked = validate_solver_receipt(job, receipt, model=row['models']['B'], backend='cp_sat', exclude_plan=excluded)
    actual = read(receipt)
    require(checked['checked_optimal'] is True and actual['private_reference_time_limit_seconds'] == 600
            and actual['operational_timeout_seconds'] == 720, 'A limited native result cannot become optimal gold')
    solver = checked['solver']; plan = solver['plan']; independent = {}
    for side, module in (('A', contract.model_a), ('B', contract.model_b)):
        model = read(row['models'][side]); check = module.check_plan(model, plan, exclude_plan=excluded)
        require(len(model['rows']) == 941 and check['objective_pence'] == solver['objective_pence']
                and len(check['rows']) >= 941 and all(r['passed'] for r in check['rows'])
                and [r['id'] for r in check['rows'][:941]] == [r['id'] for r in model['rows']],
                'Every original integer row and exact objective must pass independent A/B checks')
        independent[side] = check
    return {'native': checked, 'independent_integer_checks': independent}


def _financial_projection(inputs, row, winner, runner):
    shared = inputs['shared']; public = deepcopy(shared['public']); limits = public['shared_limits']
    for item in read(row['models']['B'])['rows']:
        if item['id'] == 'initial_sponsor_equity': limits['initial_sponsor_equity_pence'] = item['limit']
        elif item['family'] == 'resource':
            _, resource, sid, year = item['id'].split(':')
            limits['resource_capacity_units'][resource][sid][year] = item['limit']
    require(spec.canonical_sha256(public) == read(row['models']['B'])['specification_sha256'],
            'Only the declared shared RHS changes may enter a financial projection')
    # Use the two frozen independent aggregation paths over their original
    # posted universes. Do not relabel a universe SHA or rerun financial code.
    result = finance._module('finance_crosscheck')._compare_plans(public, shared['A'], shared['B'],
        [{'id': 'winner', 'plan': winner}, {'id': 'runner', 'plan': runner}], True)
    require(result['passed'] is True and result['require_group_feasible'] is True
            and result['additional_financial_forwards'] == 0, 'Complete A/B selected financial postings must agree')
    return {'base_universe_A': shared['universe_A'], 'base_universe_B': shared['universe_B'],
            'case_specification_sha256': spec.canonical_sha256(public), 'comparison': result}


def _case(output, frozen, inputs, row, audit=None):
    identity = row['case']['id']; folder = output / 'cases' / identity
    require(not (folder / 'started.json').exists(), 'No case retry or overwrite is allowed')
    write(folder / 'started.json', {'case': row['case'], 'preparation': reference(output / 'preparation.json')})
    start = time.monotonic(); receipts = {}; checks = {}; invocations = 0
    terminal = {'kind': CASE_KIND, 'version': 1, 'passed': False, 'case': row['case'], 'models': row['models']}
    try:
        def solve(phase, job, excluded):
            nonlocal invocations
            if audit: audit.emit('sensitivity.phase.started', case=identity, phase=phase); audit.export()
            write(folder / (phase + '_phase_started.json'), {'case': identity, 'phase': phase,
                'job': job, 'at': datetime.now(timezone.utc).isoformat()})
            phase_start = time.monotonic(); invocations += 1
            try: receipt = runtime.execute_prepared(Path(job['path']).parent)
            except BaseException as error:
                if getattr(error, 'receipt', None): receipts[phase] = error.receipt
                raise
            receipts[phase] = receipt
            checked = _checked_job(job, receipt, row, excluded)
            checks[phase] = write(folder / (phase + '_validation.json'), checked)
            write(folder / (phase + '_phase_completed.json'), {'job': job, 'receipt': receipt,
                'elapsed_seconds': time.monotonic() - phase_start})
            return checked['native']['solver']
        best = solve('best', frozen['best_preparations'][identity], None)
        winner = best['plan']
        runner_job = runtime.prepare(row['models']['B']['path'], folder / 'jobs/runner',
            backend='cp_sat', time_limit_seconds=600, exclude_plan=winner)
        terminal['runner_preparation'] = runner_job
        runner = solve('runner', runner_job, winner)
        gap = best['objective_pence'] - runner['objective_pence']
        require(type(gap) is int and gap >= 1 and runner['plan'] != winner,
                'Each case needs a unique best and whole-winner-excluded positive penny gap')
        projected = _financial_projection(inputs, row, winner, runner['plan'])
        require(all(projected['comparison']['plans'][i][side]['objective_pence'] == solver['objective_pence']
                for i, solver in enumerate((best, runner)) for side in ('A', 'B')),
                'The exact native objective differs from selected A/B financial postings')
        terminal.update(passed=True, winner_plan=winner, winner_objective_pence=best['objective_pence'],
            runner_plan=runner['plan'], runner_objective_pence=runner['objective_pence'], gap_pence=gap,
            financial_projection=write(folder / 'financial_projection.json', projected))
    except BaseException as error:
        terminal.update(error_type=type(error).__name__, error=str(error), retry_authorized=False)
    terminal.update(solver_receipts=receipts, validations=checks, native_job_invocations=invocations,
        elapsed_seconds=time.monotonic()-start, reference_is_not_source_or_quality_or_difficulty=True,
        financial_forwards=0, LO_calls=0, model_calls=0, qualified=False)
    return write(folder / 'terminal.json', terminal)


def execute_prepared(output, *, port=0):
    from sheets_factory.core.audit import AuditStore
    from sheets_factory.dashboard import DashboardServer
    from sheets_factory.resume import ProducerLease
    output = Path(output).absolute(); frozen, inputs, inventory = validate_prepared(output)
    require(not (output / 'started.json').exists(), 'Preserve the sole nine-case attempt; no retries')
    lease = ProducerLease(output).acquire(); audit = server = None; records = {}
    try:
        audit = AuditStore(output / 'audit', {'id': output.name, 'name': 'Nine independent CP600 offline references',
            'status': 'running', 'target_count': 9, 'producer_active': True, 'max_parallel_cases': 2})
        server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port); url = server.start()
        write(output / 'started.json', {'preparation': reference(output / 'preparation.json'), 'dashboard_url': url})
        audit.update_run(dashboard_url=url); audit.export(); print(json.dumps({'dashboard_url': url}), flush=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = {pool.submit(_case, output, frozen, inputs, row, audit): row['case']['id'] for row in inventory['cases']}
            for future in as_completed(pending):
                identity = pending[future]
                try:
                    receipt = future.result()
                except BaseException as error:
                    folder = output / 'cases' / identity
                    receipt = (reference(folder / 'terminal.json') if (folder / 'terminal.json').exists()
                        else write(folder / 'terminal.json', {'kind': CASE_KIND, 'version': 1,
                            'passed': False, 'case_id': identity, 'error_type': type(error).__name__,
                            'error': str(error), 'native_job_invocations': None,
                            'invocation_count_unknown': True, 'retry_authorized': False,
                            'all_partial_artifacts_preserved': True, 'qualified': False}))
                records[identity] = receipt
                audit.record('tasks', {'task_id': identity, 'status': 'passed' if read(receipt)['passed'] else 'rejected'})
                audit.update_run(completed_cases=len(records)); audit.export()
        ordered = [records[identity] for identity in frozen['case_order']]
        passed = all(read(r)['passed'] is True for r in ordered)
        counts = [read(r)['native_job_invocations'] for r in ordered]
        known_invocations = sum(n for n in counts if type(n) is int)
        invocations = known_invocations if all(type(n) is int for n in counts) else None
        require(known_invocations <= 18 and len(ordered) == 9, 'The complete pool exceeds its fixed call inventory')
        result = write(output / 'terminal.json', {'kind': KIND, 'version': 1, 'passed': passed,
            'preparation': reference(output / 'preparation.json'), 'case_order': frozen['case_order'], 'cases': ordered,
            'native_job_invocations': invocations, 'all_cases_retained': True, 'automatic_retries': 0,
            'known_native_job_invocations': known_invocations,
            'financial_forwards': 0, 'LO_calls': 0, 'model_calls': 0, 'qualified': False,
            'reference_is_not_source_or_quality_or_difficulty': True})
        audit.update_run(status='passed' if passed else 'rejected', producer_active=False); audit.export()
        return result
    finally:
        if server: server.stop()
        if audit: audit.db.close()
        lease.release()


def validate_completed(value):
    record = reference(value) if isinstance(value, (str, Path)) else value; result = read(record)
    require(result.get('kind') == KIND and type(result.get('version')) is int and result['version'] == 1
            and result.get('passed') is True and result['all_cases_retained'] is True
            and result['qualified'] is False and type(result['automatic_retries']) is int
            and result['automatic_retries'] == 0
            and result['reference_is_not_source_or_quality_or_difficulty'] is True
            and all(type(result[k]) is int and result[k] == 0 for k in ('financial_forwards', 'LO_calls', 'model_calls')),
            'Only all nine genuine complete best/runner references can be joined')
    output = Path(result['preparation']['path']).parent; frozen, inputs, inventory = validate_prepared(output)
    require(result['preparation'] == reference(output / 'preparation.json') and result['case_order'] == frozen['case_order']
            and len(result['cases']) == 9, 'The final complete ordered inventory changed')
    invocations = 0
    for receipt, row in zip(result['cases'], inventory['cases'], strict=True):
        actual = read(receipt); identity = row['case']['id']; folder = output / 'cases' / identity
        require(receipt == reference(folder / 'terminal.json') and actual['kind'] == CASE_KIND
                and actual['version'] == 1 and actual['passed'] is True and actual['case'] == row['case']
                and actual['models'] == row['models'] and type(actual['native_job_invocations']) is int
                and actual['native_job_invocations'] == 2 and actual['qualified'] is False
                and actual['reference_is_not_source_or_quality_or_difficulty'] is True
                and set(actual['solver_receipts']) == set(actual['validations']) == {'best', 'runner'}
                and all(type(actual[k]) is int and actual[k] == 0 for k in ('financial_forwards', 'LO_calls', 'model_calls')),
                'A failed, missing, substituted or repeated case cannot admit the whole reference')
        best = _checked_job(frozen['best_preparations'][identity], actual['solver_receipts']['best'], row, None)
        winner = best['native']['solver']; runner = _checked_job(actual['runner_preparation'],
            actual['solver_receipts']['runner'], row, winner['plan'])
        other = runner['native']['solver']; gap = winner['objective_pence'] - other['objective_pence']
        require(read(actual['validations']['best']) == best and read(actual['validations']['runner']) == runner
                and actual['winner_plan'] == winner['plan'] and actual['runner_plan'] == other['plan']
                and actual['winner_objective_pence'] == winner['objective_pence']
                and actual['runner_objective_pence'] == other['objective_pence'] and actual['gap_pence'] == gap
                and type(gap) is int and gap >= 1 and other['plan'] != winner['plan'],
                'Every case needs both actual OPTIMAL proofs and an exact positive complete-plan gap')
        projected = _financial_projection(inputs, row, winner['plan'], other['plan'])
        require(read(actual['financial_projection']) == projected
                and all(projected['comparison']['plans'][i][side]['objective_pence'] == solver['objective_pence']
                    for i, solver in enumerate((winner, other)) for side in ('A', 'B')),
                'Cold complete selected-plan financial projection differs')
        invocations += actual['native_job_invocations']
    require(type(result['native_job_invocations']) is int and result['native_job_invocations']
            == result['known_native_job_invocations'] == invocations == 18,
            'Both phases are required in every admitted case')
    return result
