#!/usr/bin/env python3
"""Recalculate native task views and verify full deltas and local controls."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback

import openpyxl
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from sheets_factory.core.audit import AuditStore, utcnow
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.evaluation.streaming_delta import compare_workbooks
from sheets_factory.evaluation.streaming_verifier import compare_files, _sparse_cells
from sheets_factory.workbook.heterogeneous_contracts.validate import compare_typed_caches

KIND = 'linear_capital_task_view_actual_validation'
REWARDS = {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}
SOURCE_PROVIDERS = {
    'standard': ('build_linear_capital_source.py', 'independently_verified_linear_capital_native_source'),
    'producer16': ('build_linear_capital_producer_source.py', 'independently_verified_linear_capital_producer16_native_source'),
}


def _provider(provider):
    if type(provider) is not str or provider not in SOURCE_PROVIDERS:
        raise ValueError('Unknown fixed source provider')
    return SOURCE_PROVIDERS[provider]


def _record_provider(value):
    path = value['path'] if isinstance(value, dict) else value
    record = json.loads(Path(path).read_text())
    if type(record) is not dict:
        raise ValueError('An explicit source provider record is required')
    provider = record.get('source_provider')
    _provider(provider)
    return provider


def source_support(provider='standard'):
    path = ROOT/'scripts'/_provider(provider)[0]
    descriptor = importlib.util.spec_from_file_location('_linear_task_source_support_'+provider, path)
    module = importlib.util.module_from_spec(descriptor)
    descriptor.loader.exec_module(module)
    return module


def required_roles(mode, families=()):
    if mode not in ('financial_modeling', 'debugging'): raise ValueError('Unknown task mode')
    prefix = ['same_temporary_plan_baseline', *['isolated_'+name for name in families]] if mode == 'debugging' else []
    return [*prefix, 'goal_reference', 'input_pass1', 'input_pass2', 'input_pass3',
        'control_equivalent', 'control_missed_root', 'control_extra_change']


def recipes(provider='standard'):
    support = source_support(provider)
    from sheets_factory.workbook.linear_capital_portfolio import task_views
    files = [Path(__file__), Path(task_views.__file__), ROOT/'src/sheets_factory/evaluation/streaming_delta.py',
        ROOT/'src/sheets_factory/evaluation/streaming_verifier.py', ROOT/'src/sheets_factory/workbook/compare.py']
    return {**support.recipes(), **{str(path.resolve()): support.reference(path)['sha256'] for path in files}}


def _view(source_ref, view_ref, provider='standard'):
    expected_kind = _provider(provider)[1]
    helper = source_support(provider)
    helper.require(helper.read(source_ref).get('kind') == expected_kind, 'The explicit source provider does not match the source kind')
    source = helper.validate_source(source_ref)
    view = helper.read(view_ref)
    source_bindings = helper.read(source['bindings'])
    from sheets_factory.workbook.linear_capital_portfolio import task_views
    helper.require(view['kind'] == 'materialized_unverified_linear_capital_task_view' and view['version'] == 1
        and type(view['version']) is int and view['mode'] in ('financial_modeling', 'debugging') and view['source'] == source['workbook']
        and view['specification_sha256'] == source_bindings['specification_sha256'],
        'The unverified material view is not bound to the admitted source')
    plan = helper.read(view['plan'])
    task_views._check_plan(plan)
    helper.require(plan['source'] == source['workbook']
        and plan['bindings_canonical_sha256'] == helper.canonical(source_bindings)
        and plan['sheetnames'] == view['sheetnames']
        and plan['specification_sha256'] == view['specification_sha256']
        and plan['mode'] == view['mode'] and plan['plan_sha256'] == view['plan_sha256']
        and view['recipe'] == plan['recipe'] == task_views._recipe(), 'The exact task-view recipe or plan changed')
    for key in ('input', 'goal', 'instruction'):
        helper.checked(view[key])
    helper.require(Path(view['instruction']['path']).read_text() == plan['instruction']
        and view['goal']['sha256'] == source['workbook']['sha256']
        and view['goal']['bytes'] == source['workbook']['bytes'], 'The public instruction or exact source goal changed')
    if view['mode'] == 'debugging':
        helper.checked(view['temporary_plan_only'])
        helper.require(list(view['family_inputs']) == list(task_views.FAMILIES), 'All frozen policy counterfactuals are required')
        for record in view['family_inputs'].values(): helper.checked(record)
    else:
        helper.require(not view['family_inputs'] and view['temporary_plan_only'] is None, 'A modeling view has unexpected debugging variants')
    return source, view, plan


def prepare(source_manifest, view_manifest, output, *, source_provider='standard'):
    helper = source_support(source_provider)
    source_ref = source_manifest if isinstance(source_manifest, dict) else helper.reference(source_manifest)
    view_ref = view_manifest if isinstance(view_manifest, dict) else helper.reference(view_manifest)
    source, view, plan = _view(source_ref, view_ref, source_provider)
    output = helper._output(output, fresh=True); output.mkdir(parents=True)
    return helper.write(output/'preparation.json', {'kind': 'prepared_'+KIND, 'version': 1,
        'created_at': utcnow(), 'source_provider': source_provider, 'source_admission': source_ref, 'materialized_view': view_ref,
        'mode': view['mode'], 'recipe': recipes(source_provider), 'runtime_profile': source['runtime_profile'],
        'runtime_profile_value': helper.runtime(source['runtime_profile']['path'])[1],
        'required_stage_roles': required_roles(view['mode'], view['family_inputs']),
        'model_calls': 0, 'LO_calls': 0, 'qualified': False})


def validate_prepared(output):
    output = Path(output).resolve(strict=True)
    provider = _record_provider(output/'preparation.json'); helper = source_support(provider)
    frozen = helper.read(output/'preparation.json')
    helper.require(frozen['kind'] == 'prepared_'+KIND and type(frozen['version']) is int and frozen['version'] == 1
        and all(type(frozen[k]) is int and frozen[k] == 0 for k in ('model_calls', 'LO_calls'))
        and frozen['qualified'] is False and frozen['recipe'] == recipes(provider), 'The actual-task validation recipe changed')
    source, view, plan = _view(frozen['source_admission'], frozen['materialized_view'], provider)
    helper.require(frozen['mode'] == view['mode']
        and frozen['required_stage_roles'] == required_roles(view['mode'], view['family_inputs'])
        and frozen['runtime_profile'] == source['runtime_profile']
        and frozen['runtime_profile_value'] == helper.runtime(source['runtime_profile']['path'])[1], 'Validation scope or runtime changed')
    return frozen, source, view, plan



def _workbook_binding(input_ref, goal_ref, output_ref):
    return {'input': input_ref, 'goal': goal_ref, 'output': output_ref}


def _complete_delta(input_ref, goal_ref, output_ref, provider='standard'):
    helper = source_support(provider)
    result = compare_workbooks(helper.checked(input_ref), helper.checked(goal_ref), helper.checked(output_ref))
    result['workbook_binding'] = _workbook_binding(input_ref, goal_ref, output_ref)
    return result


def _control_comparison(input_ref, goal_ref, output_ref, provider='standard'):
    helper = source_support(provider)
    result = compare_files(helper.checked(input_ref), helper.checked(goal_ref), helper.checked(output_ref))
    result['workbook_binding'] = _workbook_binding(input_ref, goal_ref, output_ref)
    return result


def _require_complete_delta(report, binding, provider='standard'):
    helper = source_support(provider)
    helper.require(report.get('workbook_binding') == binding and type(report.get('reward')) is int and report['reward'] == 1
        and report.get('structure_ok') is True
        and type(report.get('expected_change_count')) is int and report['expected_change_count'] > 0
        and type(report.get('actual_change_count')) is int and report['actual_change_count'] == report['expected_change_count']
        and len(report['expected_changes']) == len(set(report['expected_changes'])) == report['expected_change_count']
        and report['expected_changes'] == report['actual_changes']
        and not report['missing_changes'] and not report['extra_changes'] and not report['wrong_values'],
        'A complete nonempty delta bound to the exact input/goal/output is required')


def _require_typed_stability(report, left, right, provider='standard'):
    helper = source_support(provider)
    helper.require(report.get('left') == left and report.get('right') == right and report.get('passed') is True
        and report.get('entire_value_union_checked') is True and report.get('money_quantization_applied') is False
        and type(report.get('union_cells_checked')) is int and report['union_cells_checked'] > 0
        and type(report.get('typed_value_mismatches')) is int and report['typed_value_mismatches'] == 0,
        'A complete typed value union bound to the exact workbook pair is required')


def execute_prepared(output):
    output = Path(output).absolute()
    frozen, source, view, plan = validate_prepared(output)
    provider = frozen['source_provider']; helper = source_support(provider)
    helper.require(not (output/'started.json').exists(), 'Preserve the first validation attempt')
    lease = ProducerLease(output).acquire(); audit = server = thread = None
    stop = threading.Event(); clock = time.monotonic(); stage = 'starting'; calls = []; failure = None; records = {}
    manifest = {'kind': KIND, 'version': 1, 'passed': False, 'mode': view['mode'],
        'source_provider': provider,
        'source_admission': frozen['source_admission'], 'materialized_view': frozen['materialized_view']}
    try:
        audit = AuditStore(output/'audit', {'id': output.name, 'name': 'Native task controls and complete deltas',
            'status': 'running', 'producer_pid': os.getpid(), 'producer_active': True, 'target_count': 0})
        server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=0); url = server.start()
        helper.write(output/'started.json', {'preparation': helper.reference(output/'preparation.json'), 'at': utcnow(), 'dashboard_url': url})
        audit.update_run(dashboard_url=url)
        print(json.dumps({'dashboard_url': url, 'output': str(output)}), flush=True)
        def heartbeat():
            while not stop.wait(15):
                audit.update_run(active_stage=stage, elapsed_seconds=time.monotonic()-clock,
                    actual_LO_calls_started=len(calls), actual_LO_calls_completed=sum(c['completed'] for c in calls)); audit.export()
        thread = threading.Thread(target=heartbeat, daemon=True); thread.start()
        with helper._resource_support().data_temporary(output):
            engine = helper.ResourceLibreOfficeEngine(ROOT, source['runtime_profile']['path'], role='source', receipt_directory=output/'engine_resources')
            engine.ensure_image()
            def recalc(record, role):
                nonlocal stage
                stage = role; start = time.monotonic(); destination = output/(role+'.xlsx')
                call = {'index': len(calls)+1, 'role': role, 'input': record, 'started_at': utcnow(), 'completed': False}
                calls.append(call); helper.write(output/(role+'_started.json'), dict(call))
                try:
                    path = engine.recalculate(helper.checked(record), destination)
                    call.update(completed=True, output=helper.reference(path), elapsed_seconds=time.monotonic()-start)
                    history = engine.metadata()['actual_resource_receipts']
                    helper.require(len(history) == len(calls), 'An unrecorded actual calculation occurred')
                    call['actual_resource_evidence'] = helper.validate_actual_call(call, history[-1], frozen)
                finally:
                    call['finished_at'] = utcnow(); call['terminal_receipt'] = helper.write(output/(role+'_terminal.json'), dict(call))
                    audit.record('nodes', {'node': role, 'status': 'completed' if call['completed'] else 'failed',
                        'duration_ms': (time.monotonic()-start)*1000}); audit.export()
                print(json.dumps({'completed_LO_stage': role, 'elapsed_seconds': call['elapsed_seconds']}), flush=True)
                return call['output']
            effects = {}; baseline = None
            if view['mode'] == 'debugging':
                baseline = recalc(view['temporary_plan_only'], 'same_temporary_plan_baseline')
                for family, record in view['family_inputs'].items():
                    actual = recalc(record, 'isolated_'+family)
                    delta = _complete_delta(baseline, actual, actual, provider)
                    ref = helper.write(output/(family+'_observable_effect.json'), {'family': family,
                        'same_temporary_plan_baseline': baseline, 'counterfactual': actual, 'complete_delta': delta})
                    effects[family] = ref
                    _require_complete_delta(delta, _workbook_binding(baseline, actual, actual), provider)
            goal = recalc(view['goal'], 'goal_reference')
            stable_goal = {**compare_typed_caches(helper.checked(view['goal']), helper.checked(goal)), 'left': view['goal'], 'right': goal}
            records['goal_stability'] = helper.write(output/'source_goal_exact_stability.json', stable_goal)
            _require_typed_stability(stable_goal, view['goal'], goal, provider)
            versions = []; current = view['input']
            for index in (1, 2, 3):
                current = recalc(current, 'input_pass'+str(index)); versions.append(current)
            stable = []
            for index, right in enumerate(versions[1:], 2):
                report = compare_typed_caches(helper.checked(versions[0]), helper.checked(right))
                stable.append(helper.write(output/('input_typed_stability_'+str(index)+'.json'),
                    {'left': versions[0], 'right': right, 'comparison': report}))
                _require_typed_stability({**report,'left':versions[0],'right':right}, versions[0], right, provider)
            delta = _complete_delta(versions[0], goal, goal, provider)
            complete_D = helper.write(output/'complete_D.json', delta)
            _require_complete_delta(delta, _workbook_binding(versions[0], goal, goal), provider)
            changed = set(delta['expected_changes'])
            candidates = plan['masked_targets'] if view['mode'] == 'financial_modeling' else plan['formula_edits']
            primary = {(row['sheet'], row['cell']) for row in candidates if row['sheet']+'!'+row['cell'] in changed}
            book = openpyxl.load_workbook(helper.checked(goal), read_only=True, data_only=True)
            try:
                first = next((sheet.title, get_column_letter(key[1])+str(key[0]), cell['value'])
                    for sheet in book for key, cell in _sparse_cells(sheet)
                    if (sheet.title, get_column_letter(key[1])+str(key[0])) in primary and type(cell['value']) in (int, float))
            finally: book.close()
            controls = {'oracle': goal, 'nop': versions[0]}; reports = {}; rewards = {}; raw_controls = {}
            for name in ('equivalent', 'missed_root', 'extra_change'):
                book = openpyxl.load_workbook(helper.checked(goal), keep_links=False)
                try:
                    if name == 'equivalent': book[first[0]][first[1]] = '='+str(first[2])+'+0'
                    elif name == 'missed_root': book[first[0]][first[1]] = None
                    else:
                        cell = book.worksheets[0]['A1']; helper.require(type(cell.value) is str, 'A protected public title is required')
                        cell.value += ' changed'
                    raw = output/(name+'.raw.xlsx'); book.save(raw)
                finally: book.close()
                raw_controls[name] = helper.reference(raw)
                controls[name] = recalc(raw_controls[name], 'control_'+name)
            for name, record in controls.items():
                report = _control_comparison(versions[0], goal, record, provider)
                reports[name] = helper.write(output/(name+'_comparison.json'), report); rewards[name] = report['reward']
                helper.require(report['reward'] == REWARDS[name], 'A local positive/negative control failed: '+name)
            controls_evidence = helper.write(output/'local_controls.json', {'rewards': rewards, 'reports': reports,
                'workbooks': controls, 'raw_control_inputs':raw_controls, 'observable_primary': {'sheet': first[0], 'cell': first[1]}, 'actual_Harbor_jobs': 0})
            helper.require([call['role'] for call in calls] == frozen['required_stage_roles'], 'The actual complete calculation inventory differs')
            validate_prepared(output)
            manifest.update(passed=True, input=versions[0], goal=goal, instruction=view['instruction'],
                complete_D=complete_D, typed_stabilities=stable, individual_effects=effects,
                temporary_plan_baseline=baseline, local_controls=rewards, controls_evidence=controls_evidence,
                goal_stability=records['goal_stability'], source_original_unchanged=True,
                source_goal_copy=view['goal'], source_workbook=source['workbook'])
    except BaseException as error:
        failure = error
        records['failure'] = helper.write(output/'failure.json', {'stage': stage, 'type': type(error).__name__,
            'error': str(error), 'traceback': traceback.format_exc()})
    finally:
        stop.set()
        if thread: thread.join(timeout=1)
        manifest.update(preparation=helper.reference(output/'preparation.json'), actual_LO_calls=calls,
            required_stage_roles=frozen['required_stage_roles'], records=records, finished_at=utcnow(),
            elapsed_seconds=time.monotonic()-clock, model_calls=0, actual_Harbor_jobs=0, qualified=False,
            all_twelve_quality_checks_passed=False, difficulty_certified=False)
        terminal = helper.write(output/'terminal.json', manifest)
        if audit:
            audit.update_run(status='passed' if failure is None else 'failed', producer_active=False, terminal_receipt=terminal); audit.export()
        if server: server.stop()
        if audit: audit.db.close()
        lease.release()
    print(json.dumps({'terminal': terminal, 'passed': failure is None}), flush=True)
    if failure: raise RuntimeError('Task controls failed; preserve '+terminal['path']) from failure
    return terminal


def validate_completed(value):
    provider = _record_provider(value); helper = source_support(provider)
    ref = value if isinstance(value, dict) else helper.reference(value)
    result = helper.read(ref)
    helper.require(result['kind'] == KIND and type(result['version']) is int and result['version'] == 1 and result['passed'] is True, 'A completed actual task validation is required')
    output = Path(result['preparation']['path']).parent
    frozen, source, view, plan = validate_prepared(output)
    helper.require(helper.reference(output/'preparation.json') == result['preparation']
        and result['source_admission'] == frozen['source_admission'] and result['materialized_view'] == frozen['materialized_view']
        and result['source_provider'] == frozen['source_provider']
        and result['mode'] == view['mode'] and result['required_stage_roles'] == frozen['required_stage_roles'], 'Actual task ancestry changed')
    calls = result['actual_LO_calls']
    helper.require([call['role'] for call in calls] == frozen['required_stage_roles']
        and [call['index'] for call in calls] == list(range(1, len(calls)+1)), 'The complete actual task calculation inventory changed')
    byrole = {}
    for call in calls:
        helper.require(call['completed'] is True and helper.read(call['terminal_receipt']) == {k:v for k,v in call.items() if k != 'terminal_receipt'}, 'An actual call did not complete or its receipt changed')
        helper.checked(call['input']); helper.checked(call['output'])
        evidence = helper.validate_actual_call(call, call['actual_resource_evidence']['terminal'], frozen)
        helper.require(evidence == call['actual_resource_evidence'], 'Actual task resource evidence changed')
        byrole[call['role']] = call
    helper.require(byrole['goal_reference']['input'] == view['goal'] and byrole['goal_reference']['output'] == result['goal']
        and byrole['input_pass1']['input'] == view['input'] and byrole['input_pass1']['output'] == result['input']
        and byrole['input_pass2']['input'] == result['input']
        and byrole['input_pass3']['input'] == byrole['input_pass2']['output'], 'Actual reference/input chains changed')
    delta = helper.read(result['complete_D'])
    _require_complete_delta(delta, _workbook_binding(result['input'],result['goal'],result['goal']), provider)
    helper.require(len(result['typed_stabilities']) == 2, 'Both input stability comparisons are required')
    _require_typed_stability(helper.read(result['goal_stability']), view['goal'], result['goal'], provider)
    for index, record in enumerate(result['typed_stabilities'], 2):
        pair = helper.read(record); report = pair['comparison']
        _require_typed_stability({**report,'left':pair['left'],'right':pair['right']}, result['input'],byrole['input_pass'+str(index)]['output'], provider)
    controls = helper.read(result['controls_evidence'])
    helper.require(result['local_controls'] == controls['rewards'] == REWARDS, 'All five actual local controls are required')
    for name, reward in REWARDS.items():
        report = helper.read(controls['reports'][name])
        helper.require(type(report.get('reward')) is int and report['reward'] == reward
            and report.get('workbook_binding') == _workbook_binding(result['input'],result['goal'],controls['workbooks'][name]),
            'A real local control comparison changed or refers to a different workbook pair')
        helper.checked(controls['workbooks'][name])
        expected = result['goal'] if name == 'oracle' else result['input'] if name == 'nop' else byrole['control_'+name]['output']
        helper.require(controls['workbooks'][name] == expected, 'The actual control output changed')
        if name in ('equivalent','missed_root','extra_change'):
            helper.checked(controls['raw_control_inputs'][name])
            helper.require(byrole['control_'+name]['input'] == controls['raw_control_inputs'][name], 'An actual control used the wrong raw mutation input')
    helper.require(set(result['individual_effects']) == set(view['family_inputs']), 'A frozen family effect was omitted')
    if view['mode'] == 'debugging':
        base = byrole['same_temporary_plan_baseline']
        helper.require(base['input'] == view['temporary_plan_only'] and base['output'] == result['temporary_plan_baseline'], 'The same-plan diagnostic baseline changed')
        for family, record in result['individual_effects'].items():
            effect = helper.read(record); call = byrole['isolated_'+family]
            helper.require(call['input'] == view['family_inputs'][family] and effect['counterfactual'] == call['output']
                and effect['same_temporary_plan_baseline'] == base['output'], 'A single-family effect is missing or uses the winner-plan baseline')
            _require_complete_delta(effect['complete_delta'], _workbook_binding(base['output'],call['output'],call['output']), provider)
    else:
        helper.require(result['temporary_plan_baseline'] is None, 'A modeling validation cannot inherit a debugging baseline')
    helper.require(result['instruction'] == view['instruction'] and result['source_goal_copy'] == view['goal']
        and result['source_workbook'] == source['workbook'] and result['source_original_unchanged'] is True
        and result['qualified'] is False and type(result['model_calls']) is int and result['model_calls'] == 0
        and type(result['actual_Harbor_jobs']) is int and result['actual_Harbor_jobs'] == 0
        and result['all_twelve_quality_checks_passed'] is False and result['difficulty_certified'] is False,
        'The prequality validation scope changed')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('prepare'); p.add_argument('--source-manifest', type=Path, required=True)
    p.add_argument('--view-manifest', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--source-provider', choices=tuple(SOURCE_PROVIDERS), default='standard')
    p = commands.add_parser('run'); p.add_argument('--prepared', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare': print(json.dumps(prepare(args.source_manifest, args.view_manifest, args.output, source_provider=args.source_provider)), flush=True)
    else: execute_prepared(args.prepared)
