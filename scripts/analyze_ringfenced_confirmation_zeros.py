#!/usr/bin/env python3
"""Append conservative evidence for completed, under-budget confirmation zeros."""
from __future__ import annotations

import argparse
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT/'src'))
from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard.server import DashboardServer
from sheets_factory.evaluation import mixed_business_resource_observer as observer
from sheets_factory.evaluation import mixed_business_resources
from sheets_factory.workbook.linear_capital_ringfenced_pairs.contract import reference as ref, read, require

ENTRY = ROOT/'scripts/run_ringfenced_replacement_confirmation.py'
SOURCE = ROOT/'scripts/build_cached_ringfenced_pair_source_revision2.py'
SUPPORT = ROOT/'scripts/diagnose_ringfenced_business_attempts.py'
PINS = {ENTRY: 'bde7c4963159ddeb5c7e11b3bd62dde992753d9c447b2e61583755dd6feaa04f',
    SOURCE: '08b6e3055178f5516de71eaeb4e5cbb82f56adfe78f394a7a70e0c5bff5ed855',
    SUPPORT: 'd3f18a86ba04af8e8e8abc48ee25a71bc76dd58aa65d4cdb89a175a7c09c21da',
    Path(observer.__file__): '135ecb36f52914ccf18850c463fe82bb65eee54ea9dff2f74245b5d245223ef8',
    Path(mixed_business_resources.__file__): '2aff5520ef5d589d31a0faaa69278df1debe6ae26f44c9797cc3e0853e725eae'}
BOOLEAN_POINT = 'Group reporting!B6'


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream: json.dump(value, stream, indent=2, allow_nan=False); stream.write('\n')
    return ref(path)


def load(path, name):
    require(ref(path)['sha256'] == PINS[path], 'A frozen confirmation-analysis dependency changed')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def recipes():
    for path, digest in PINS.items(): require(ref(path)['sha256'] == digest, 'A frozen analysis provider changed')
    return [ref(__file__), *[ref(path) for path in PINS]]


def disposition(row):
    """An auxiliary analysis never changes the original primary score."""
    attempt, score = row['actual_attempt'], row['score']; clock = attempt.get('tool_time') or {}
    raw = attempt.get('raw_verifier_reward', attempt.get('reward'))
    require(row['resources'].get('passed') is row['resources'].get('complete') is True
        and attempt.get('status') == 'scored', 'HOLD: incomplete native result or actual resources')
    require(clock.get('state') in ('verified', 'verified_conservative_bound', 'verified_owned_overlap_bound',
        'verified_tool_budget_lower_bound') and clock.get('policy_version') == 6
        and clock.get('budget_seconds') == 1800 and clock.get('strict_less_than') is True
        and clock.get('model_response_time_included') is False and clock.get('parallel_executions') == 'sum',
        'HOLD: the original strict v6 timing evidence is incomplete')
    exact = clock.get('cumulative_tool_seconds')
    lower = exact if exact is not None else clock.get('cumulative_lower_bound_seconds')
    upper = exact if exact is not None else clock.get('cumulative_upper_bound_seconds')
    finite = lambda value: type(value) in (int, float) and Decimal(str(value)).is_finite()
    if attempt.get('failure_kind') == 'cumulative_tool_budget_exhausted' and clock.get('passed') is False:
        require(finite(lower) and lower >= 1800 and score.get('state') == 'known_tool_budget_failure'
            and score.get('effective_reward') == 0, 'HOLD: budget failure lacks its original verified lower bound')
        return 'skip_verified_budget_failure'
    require(not attempt.get('failure_kind') and clock.get('passed') is True and finite(upper) and upper < 1800
        and type(raw) in (int, float) and raw in (0, 1) and score.get('state') == 'complete'
        and score.get('effective_reward') == raw, 'HOLD: incomplete original score or under-budget evidence')
    return 'skip_primary_success' if raw == 1 else 'analyze_complete_primary_zero'


def mismatch_points(diagnostic):
    require(diagnostic.get('reward') == 0 and diagnostic.get('reason') == 'value_or_modified_set_mismatch'
        and not diagnostic.get('differences_truncated') and not diagnostic.get('truncated'),
        'HOLD: complete native modified-set diagnostics are required')
    result = set()
    for key in ('missing_changes', 'extra_changes', 'wrong_values'):
        values = diagnostic.get(key)
        require(type(values) is list and all(type(v) is str and '!' in v for v in values)
            and len(values) == len(set(values)), 'HOLD: diagnostic coordinates are incomplete or duplicated')
        result.update(values)
    require(bool(result), 'HOLD: no native mismatch positions exist')
    return result


def _typed(cell):
    if cell is None or cell.get('value') is None or cell.get('value') == '': return 'missing', None
    value = cell['value']
    if cell.get('data_type') == 'e': return 'invalid', value
    if type(value) is bool: return 'boolean', value
    if type(value) in (int, float):
        return ('number', value) if Decimal(str(value)).is_finite() else ('invalid', str(value))
    return 'text', str(value)


def classify(diagnostic, goal, output, *, output_recalculated=False):
    """Only literal O values, or a fresh verified O calculation, prove values."""
    points = mismatch_points(diagnostic); differences = []; unresolved = []
    for point in sorted(points):
        expected = goal.get(point); actual = output.get(point)
        et, ev = _typed(expected); at, av = _typed(actual)
        formula = actual is not None and actual.get('formula') is not None
        if formula and (av is None or not output_recalculated):
            unresolved.append({'coordinate': point, 'reason': 'formula_cache_empty' if av is None else 'saved_formula_cache_is_not_native_proof'})
            continue
        if et in ('missing', 'invalid'):
            unresolved.append({'coordinate': point, 'reason': 'native_healthy_goal_value_unavailable'}); continue
        if at not in ('missing', 'invalid') and et != at and point != BOOLEAN_POINT: at = 'invalid'
        differences.append({'coordinate': point, 'expected_type': et, 'expected': ev, 'actual_type': at, 'actual': av})
    material = [r for r in differences if r['coordinate'] != BOOLEAN_POINT and r['expected_type'] == r['actual_type'] == 'number'
        and abs(Decimal(str(r['expected']))-Decimal(str(r['actual']))) > Decimal('0.01')]
    coverage = [r for r in differences if r['coordinate'] != BOOLEAN_POINT and r['actual_type'] in ('missing', 'invalid')]
    kind = None
    if points == {BOOLEAN_POINT} and not diagnostic['missing_changes'] and not diagnostic['extra_changes'] and len(differences) == 1:
        r = differences[0]
        if r['expected_type'] == 'boolean' and r['expected'] is True and r['actual_type'] == 'number' \
                and type(r['actual']) in (int, float) and r['actual'] == 1: kind = 'pure_reporting_boolean_only'
    if kind is None and material: kind = 'material_business_value_failure'
    if kind is None and coverage: kind = 'coverage_failure'
    complete_coverage = not unresolved and len(differences) == len(points)
    if kind is None and complete_coverage and all(r['expected_type'] == r['actual_type'] == 'number'
        and Decimal(0) < abs(Decimal(str(r['expected']))-Decimal(str(r['actual']))) <= Decimal('0.01') for r in differences):
        kind = 'pure_numeric_rounding_only'
    return {'classification': kind or 'HOLD', 'complete': kind is not None, 'differences': differences,
        'native_mismatch_count': len(points), 'full_mismatch_coverage': complete_coverage, 'unresolved': unresolved,
        'classification_policy': 'Conservative technical-only allowance for complete numeric differences of at most 0.01 native cell units; not a proved rounding cause',
        'rounding_cause_proved': False,
        'concrete_nonboundary_witness_count': len(material)+len(coverage)}


def point_values(path, points, support):
    requested = {}
    for point in points:
        sheet, address = point.rsplit('!', 1); requested.setdefault(sheet, set()).add(address)
    result = {}; reader = support._load(support.SUPPORT, '_confirmation_zero_sheet_reader')
    book = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    try:
        sheets = {s.title: s for s in book.worksheets}
        for name, wanted in requested.items():
            if name not in sheets: continue
            cells, _ = reader.sheet_cells(sheets[name])
            for (row, column), cell in cells.items():
                address = get_column_letter(column)+str(row)
                if address in wanted: result[name+'!'+address] = cell
    finally: book.close()
    return result


def bind_original_rows(actual, selected, resources):
    """Match terminal rows to immutable runner attempts and actual verifier rewards."""
    evaluation = read(actual['evaluation'])
    require(not evaluation.get('infrastructure_retries') and not evaluation.get('infra_history')
        and resources.get('passed') is resources.get('complete') is True
        and resources['selection'] == actual['selection'] and resources['evaluation'] == actual['evaluation'],
        'HOLD: original evaluation/resource binding is incomplete')
    attempts = evaluation['attempts']; rows = actual['results']; snapshots = selected['tasks']
    require(len(attempts) == len(rows) == len(snapshots) == 10
        and len({r['task_id'] for r in attempts}) == len({r['task_id'] for r in rows}) == len({r['task_id'] for r in snapshots}) == 10,
        'HOLD: preserve exactly ten unique original attempts and snapshots')
    by_id = {r['task_id']: r for r in attempts}; trial_resources = resources['trials']
    for row in rows:
        identity = row['task_id']; attempt = row['actual_attempt']
        require(by_id.get(identity) == attempt, 'HOLD: terminal row differs from its immutable original evaluation attempt')
        result_ref = ref(attempt['result_file']); result = read(result_ref)
        raw = attempt.get('raw_verifier_reward', attempt.get('reward'))
        actual_reward = result['verifier_result']['rewards']['reward']
        bound = [r for r in trial_resources if r.get('result') == result_ref]
        require(result_ref['sha256'] == attempt['result_sha256'] and result.get('task_name') == 'sheetsfactory/'+identity
            and result.get('exception_info') is None and result.get('finished_at')
            and type(raw) in (int, float) and raw in (0, 1)
            and type(actual_reward) in (int, float) and actual_reward == raw
            and len(bound) == 1 and bound[0] == row['resources'],
            'HOLD: actual result identity, reward or resource binding changed')
    return evaluation


def admit(prepared, terminal):
    entry = load(ENTRY, '_confirmation_zero_fixed_cohort')
    directory = Path(prepared).parent if Path(prepared).is_file() else Path(prepared)
    frozen = entry.validate_prepared(directory); prepared_ref = ref(directory/'prepared.json')
    terminal_ref = ref(terminal); actual = read(terminal_ref)
    require(actual['kind'] == entry.TERMINAL_KIND and actual['version'] == 1 and actual['phase'] == 'confirmation'
        and actual['prepared'] == prepared_ref and actual['outer_retries'] == 0,
        'HOLD: require the exact original frozen confirmation terminal')
    selected = read(actual['selection']); resources = read(actual['resources'])
    require(selected['phase'] == 'confirmation' and selected['model'] == 'gpt-6.1-sol'
        and selected['reasoning_effort'] == 'xhigh' and selected['n_attempts'] == 1
        and selected['tool_time_policy_version'] == 6 and selected['infrastructure_retry_policy']['max_retries'] == 0,
        'HOLD: the native confirmation protocol changed')
    bind_original_rows(actual, selected, resources)
    tasks = {r['task_id']: r for r in frozen['tasks']}; rows = {r['task_id']: r for r in actual['results']}
    snapshots = {r['task_id']: r for r in selected['tasks']}
    require(len(tasks) == len(rows) == len(actual['results']) == len(snapshots) == 10 and set(rows) == set(tasks) == set(snapshots),
        'HOLD: keep all ten frozen confirmation materials')
    source_by_task = {}; guard_refs = [prepared_ref, terminal_ref, actual['selection'], actual['evaluation'], actual['resources']]
    provider = None; support = load(SUPPORT, '_confirmation_zero_native_support')
    for batch_ref in frozen['batches']:
        batch = read(batch_ref); source_ref = batch['source']; source = read(source_ref)
        if source_ref['sha256'] == support.SOURCE_SHA:
            proof = support._source(source_ref); goal = proof['goal']; guard_refs += proof['guard_refs']
        else:
            provider = provider or load(SOURCE, '_confirmation_zero_cached_source')
            source = provider.validate_completed(source_ref); goal = source['source']
        for task in batch['tasks']: source_by_task[task['task_id']] = {'source': source_ref, 'goal': goal}
        guard_refs += [batch_ref, source_ref, goal]
    for identity, task in tasks.items():
        attempt = rows[identity]['actual_attempt']; staged = Path(snapshots[identity]['task_directory'])
        require(task['mode'] == rows[identity]['mode'] and snapshots[identity]['task_checksum'] == attempt['task_checksum']
            and snapshots[identity]['harbor_export_binding'] == task['harbor_export_binding'], 'HOLD: actual snapshot identity changed')
        require(mixed_business_resources.inspect_resource_export(staged) == task['harbor_export_binding'],
            'HOLD: the exact actual seventeen-file snapshot changed')
        goal = source_by_task[identity]['goal']
        require(all(ref(staged/'tests/reference.xlsx')[k] == goal[k] for k in ('sha256', 'bytes')),
            'HOLD: snapshot goal differs from its complete three-call native source')
        result_ref = ref(attempt['result_file']); require(result_ref['sha256'] == attempt['result_sha256'], 'HOLD: actual result changed')
        guard_refs.append(result_ref)
    return {'prepared': prepared_ref, 'terminal': terminal_ref, 'actual': actual, 'tasks': tasks, 'rows': rows,
        'snapshots': snapshots, 'resources': resources, 'sources': source_by_task, 'guards': guard_refs, 'support': support}


def analyze(prepared, terminal, output, *, recalculate=(), port=0):
    output = Path(output).absolute(); require(output == output.resolve() and not output.exists(), 'Use a fresh auxiliary analysis directory')
    output.mkdir(parents=True)
    audit = AuditStore(output/'audit', {'id': output.name, 'name': 'Conservative confirmation-zero evidence', 'status': 'running', 'target_count': 10})
    panel = DashboardServer(audit.snapshot, audit.events, port=port); url = panel.start(); print(json.dumps({'dashboard_url': url}), flush=True)
    audit.update_run(dashboard_url=url, stage='frozen_confirmation_admission'); records = []; calls = []; engine = None
    try:
        recipe = recipes(); context = admit(prepared, terminal); support = context['support']
        allowed = set(recalculate); require(len(allowed) == len(recalculate) and allowed <= set(context['tasks']), 'Use unique explicit authorized task IDs')
        prospective = write(output/'prospective.json', {'kind': 'conditional_confirmation_zero_analysis', 'version': 1,
            'prepared': context['prepared'], 'original_terminal': context['terminal'], 'recipe': recipe,
            'explicit_output_recalculation_authorizations': sorted(allowed), 'max_output_calls_per_task': 1,
            'new_input_goal_source_model_solver_calls': 0, 'outer_retries': 0})
        for identity, row in context['rows'].items():
            state = disposition(row)
            if state != 'analyze_complete_primary_zero':
                records.append({'task_id': identity, 'disposition': state, 'analysis': None, 'new_output_LO_calls': 0}); continue
            attempt = row['actual_attempt']; result = ref(attempt['result_file']); trial = Path(result['path']).parent
            actual_result = read(result)
            require(result['sha256'] == attempt['result_sha256'] and actual_result.get('exception_info') is None
                and actual_result.get('finished_at') and actual_result['verifier_result']['rewards']['reward'] == 0,
                'HOLD: the original complete zero result changed')
            diagnostic_ref = ref(trial/'verifier/diagnostics.json'); diagnostic = read(diagnostic_ref); points = mismatch_points(diagnostic)
            checked = observer.validate_trial_observations(trial/'config.json', result,
                receipts=context['resources']['observation_receipts'], expected_task_directory=context['snapshots'][identity]['task_directory'])
            require(checked['passed'] is checked['complete'] is True and checked == row['resources'], 'HOLD: actual mixed-role resource evidence differs')
            saved = ref(trial/'artifacts/app/output.xlsx'); goal = context['sources'][identity]['goal']
            evidence = [context['prepared'], context['terminal'], result, diagnostic_ref, saved, goal,
                context['sources'][identity]['source'], *context['resources']['observation_receipts']]
            g = point_values(goal['path'], points, support); o = point_values(saved['path'], points, support)
            classified = classify(diagnostic, g, o); call_count = 0
            if not classified['complete'] and identity in allowed:
                reservation = ROOT/'outputs/research/.ringfenced_zero_analysis_O_reservations_v1'/(result['sha256']+'.json')
                write(reservation, {'original_result': result, 'exact_saved_output': saved, 'prospective': prospective, 'maximum_calls': 1, 'outer_retries': 0})
                engine = support.engine_class()(ROOT, support.PROFILE, role='verifier', receipt_directory=output/identity/'native_receipts')
                native = ref(engine.recalculate(saved['path'], output/identity/'output.native.xlsx'))
                metadata = engine.metadata(); require(len(metadata['actual_resource_receipts']) == 1, 'Extra output calls are forbidden')
                receipt = metadata['actual_resource_receipts'][0]; calls.append(receipt)
                support.resource_check(receipt, saved, native, 'verifier')
                cleanup = support.owned_absence([receipt]); require(cleanup['daemon_reachable'] and cleanup['all_owned_containers_absent'], 'HOLD: output worker cleanup is incomplete')
                evidence += [native, receipt, write(output/identity/'owned_cleanup.json', cleanup)]
                classified = classify(diagnostic, g, point_values(native['path'], points, support), output_recalculated=True); call_count = 1
            for record in evidence: require(ref(record['path']) == record, 'An original evidence artifact changed')
            artifact = write(output/identity/'analysis.json', {'kind': 'native_confirmation_nonboundary_analysis_v1', 'version': 1,
                'task_id': identity, 'result_sha256': attempt['result_sha256'], 'diagnostics': diagnostic_ref,
                'evidence': evidence, **classified, 'original_score': row['score'], 'original_raw_reward': attempt['raw_verifier_reward'],
                'original_primary_score_modified': False, 'new_output_LO_calls': call_count, 'recipe': recipe})
            records.append({'task_id': identity, 'disposition': state, 'analysis': artifact, 'classification': classified['classification'],
                'complete': classified['complete'], 'new_output_LO_calls': call_count})
            audit.task(identity, status='analyzed' if classified['complete'] else 'HOLD', node=classified['classification']); audit.export()
        require(recipes() == recipe, 'The auxiliary analysis recipe changed')
        for record in context['guards']: require(ref(record['path']) == record, 'A frozen confirmation artifact changed')
        result = write(output/'terminal.json', {'kind': 'complete_ringfenced_confirmation_zero_analysis_bundle', 'version': 1,
            'prospective': prospective, 'records': records, 'analyses': [r['analysis'] for r in records if r['analysis']],
            'actual_output_LO_calls': len(calls), 'new_input_goal_source_model_solver_calls': 0, 'outer_retries': 0,
            'original_scores_modified': False, 'HOLD_count': sum(r.get('complete') is False for r in records)})
        audit.update_run(status='completed', stage='auxiliary_analysis_complete'); return result
    except BaseException as error:
        cleanup = None
        try:
            if engine is not None:
                for receipt in engine.metadata()['actual_resource_receipts']:
                    if receipt not in calls: calls.append(receipt)
            if calls: cleanup = write(output/'failure_owned_cleanup.json', context['support'].owned_absence(calls))
        except Exception as secondary:
            cleanup = write(output/'failure_cleanup_unknown.json', {'type': type(secondary).__name__, 'reason': str(secondary)})
        write(output/'failure.json', {'type': type(error).__name__, 'reason': str(error), 'records': records,
            'actual_output_LO_calls': len(calls), 'owned_cleanup': cleanup, 'outer_retries': 0, 'original_scores_modified': False})
        audit.update_run(status='failed', stage='HOLD'); raise
    finally: audit.export(); panel.stop(); audit.db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('prepared', 'terminal', 'output'): parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--recalculate-output', action='append', default=[], metavar='AUTHORIZED_TASK_ID')
    parser.add_argument('--port', type=int, default=0); args = parser.parse_args(argv)
    print(json.dumps(analyze(args.prepared, args.terminal, args.output, recalculate=args.recalculate_output, port=args.port)))


if __name__ == '__main__': main()
