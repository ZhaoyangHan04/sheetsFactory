#!/usr/bin/env python3
"""Persist the four remaining controls before a separate, zero-call export."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT/'src'))
V1 = ROOT/'scripts/resume_ringfenced_pair_task8_remaining_v1.py'
V1_SHA = '4133d3d5bf01cdd5b60802a9807af510c62455f1055f8b7f70f46da0220b7305'
PILOT = ROOT/'scripts/run_ringfenced_pair_source_pilot.py'
PILOT_SHA = '3be90b1ff63dd11808448263f5d097ea79b73283c14e1d9a6e367a1228a07dc2'
ZERO_CALL_FAILURE = ROOT/'outputs/research/ringfenced_R2_01_remaining4_actual_20261101T072500Z/failure.json'


def load(path, wanted, name):
    if hashlib.sha256(path.read_bytes()).hexdigest() != wanted:
        raise ValueError('A frozen continuation dependency changed')
    definition = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(definition); definition.loader.exec_module(module)
    return module


v1 = load(V1, V1_SHA, '_frozen_R2_finite_continuation_v1')
ref, read, write, require = v1.ref, v1.read, v1.write, v1.require


def engine_class():
    """Use the same private, strict profile loader as the genuine R2 source."""
    pilot = load(PILOT, PILOT_SHA, '_R2_genuine_private_profile_engine')
    return pilot._N['engines']().ThreadCappedResourceLibreOfficeEngine


def recipes():
    return [ref(__file__), ref(V1), ref(PILOT), ref(v1.PROFILE)]


def controls(output, *, port=0):
    output = Path(output).absolute(); require(output == output.resolve() and not output.exists(), 'Preserve previous continuation directories')
    f, inherited, results, admission = v1.preflight()
    prior = read(ZERO_CALL_FAILURE)
    require(prior['type'] == 'ValueError' and prior['reason'] == 'Unsupported prospective runtime profile'
            and not list(ZERO_CALL_FAILURE.parent.glob('native_receipts/*.started.json')), 'The prior failure was not the known zero-call profile rejection')
    output.mkdir(parents=True)
    audit = v1.AuditStore(output/'audit', {'id': output.name, 'name': 'Four remaining original ringfenced controls', 'status': 'running', 'target_count': 0})
    server = v1.DashboardServer(audit.snapshot, audit.events, port=port); url = server.start(); started = time.monotonic()
    print(json.dumps({'dashboard_url': url, 'pid': __import__('os').getpid()}), flush=True)
    audit.update_run(dashboard_url=url)
    calls = []; observations = list(admission['inherited_resource_observations']); engine = None
    stop = threading.Event()
    def heartbeat():
        while not stop.wait(15):
            audit.update_run(elapsed_seconds=time.monotonic()-started, actual_LO_calls_completed=len(calls)); audit.export()
    thread = threading.Thread(target=heartbeat, daemon=True); thread.start()
    try:
        frozen = recipes()
        daemon = subprocess.run(['docker', 'info', '--format', '{{.ID}}'], capture_output=True, text=True, check=True).stdout.strip()
        prospective = write(output/'prospective.json', {'kind': 'append_only_original_R2_01_remaining_four_controls_revision2', 'version': 1,
            'admission': admission, 'recipe': frozen, 'prior_zero_call_failure': ref(ZERO_CALL_FAILURE), 'daemon_before_id': daemon,
            'stage_order': list(v1.REMAINING), 'new_LO_calls_maximum': 4, 'new_source_solver_model_Harbor_calls': 0,
            'original_records_modified': False, 'retries': 0})
        engine = engine_class()(ROOT, v1.PROFILE, role='source', receipt_directory=output/'native_receipts')
        for index, role in enumerate(v1.REMAINING, 5):
            audit.update_run(stage='actual_'+role); audit.export()
            before = f['planned_inputs'][role]; tick = time.monotonic()
            actual = engine.recalculate(before['path'], output/(role+'.xlsx')); after = ref(actual)
            receipt = engine.metadata()['actual_resource_receipts'][-1]
            observation = v1.resource_check(receipt, source=before, output=after); observations.append(observation)
            call = {'index': index, 'role': role, 'input': before, 'output': after, 'completed': True,
                    'elapsed_seconds': time.monotonic()-tick, 'native_resource_receipt': receipt}
            calls.append(call); results[role] = after
            write(output/(role+'_completed.json'), call)
            print(json.dumps({'actual_call_completed': role, 'new_completed_calls': len(calls)}), flush=True)
        cleanup = v1.owned_cleanup(observations)
        require(cleanup['daemon_id'] == daemon, 'The owned cleanup belongs to another Docker daemon')
        require(recipes() == frozen and v1.preflight()[0] == f, 'The original source, inputs or continuation changed')
        record = write(output/'controls_terminal.json', {'kind': 'completed_original_R2_01_four_remaining_controls_revision2', 'version': 1,
            'passed': True, 'prospective': prospective, 'original_preparation': admission['original_preparation'],
            'source': f['source_manifest'], 'unique_optimum_certificate': admission['certificate'],
            'inherited_input_calls': inherited, 'new_calls': calls, 'results': results,
            'actual_resource_observations': observations, 'owned_cleanup': write(output/'owned_cleanup.json', cleanup),
            'new_LO_calls': 4, 'inherited_source_calls': 3, 'inherited_input_call_count': 4,
            'new_model_solver_source_Harbor_calls': 0, 'qualified': False, 'old_records_modified': False,
            'complete_value_and_export_stage_pending': True, 'duration_seconds': time.monotonic()-started})
        audit.update_run(status='completed', stage='controls_complete', actual_LO_calls_completed=4)
        return record
    except BaseException as error:
        write(output/'failure.json', {'type': type(error).__name__, 'reason': str(error), 'new_completed_calls': len(calls),
                                     'qualified': False, 'failure_is_not_model_zero': True})
        if engine is not None:
            for receipt in engine.metadata()['actual_resource_receipts']:
                value = read(receipt)
                if value.get('container_id') and receipt not in [item['receipt'] for item in observations]:
                    observations.append({'receipt': receipt, 'container_id': value['container_id']})
        try:
            write(output/'failure_owned_cleanup.json', v1.owned_cleanup(observations))
        except Exception as cleanup_error:
            write(output/'cleanup_unknown.json', {'type': type(cleanup_error).__name__, 'reason': str(cleanup_error)})
        audit.update_run(status='failed', stage='control_failure'); raise
    finally:
        stop.set(); thread.join(timeout=1); audit.export(); server.stop(); audit.db.close()


def finalize(terminal, output, *, port=0):
    """No workbook recalculation, source admission, optimizer or model call."""
    from sheets_factory.evaluation import ringfenced_resource_harbor as export
    output = Path(output).absolute(); require(output == output.resolve() and not output.exists(), 'Use a fresh zero-call export namespace')
    actual = read(terminal); f, inherited, original_results, admission = v1.preflight()
    require(actual['kind'] == 'completed_original_R2_01_four_remaining_controls_revision2' and actual['passed'] is True
            and actual['source'] == f['source_manifest'] and actual['original_preparation'] == admission['original_preparation']
            and actual['inherited_input_calls'] == inherited and actual['new_LO_calls'] == 4
            and [value['role'] for value in actual['new_calls']] == list(v1.REMAINING), 'The completed four-control chain changed')
    require(all(actual['results'][key] == value for key, value in original_results.items()), 'Original actual input bindings changed')
    for value in actual['results'].values():
        require(ref(value['path']) == value, 'An actual input/control changed before full comparison')
    for call in actual['new_calls']:
        v1.resource_check(call['native_resource_receipt'], source=call['input'], output=call['output'])
    cleanup = read(actual['owned_cleanup']); require(cleanup['passed'] and cleanup['all_owned_containers_absent'], 'The four-control cleanup is incomplete')
    output.mkdir(parents=True)
    audit = v1.AuditStore(output/'audit', {'id': output.name, 'name': 'Ringfenced full-value audit and export', 'status': 'running', 'target_count': 2})
    server = v1.DashboardServer(audit.snapshot, audit.events, port=port); url = server.start(); started = time.monotonic()
    print(json.dumps({'dashboard_url': url, 'pid': __import__('os').getpid()}), flush=True); audit.update_run(dashboard_url=url)
    try:
        record = {'controls_terminal': ref(terminal), 'original_preparation': admission['original_preparation'],
                  'recipe': recipes(), 'export_adapter': ref(export.__file__), 'execution_budget': v1.BUDGET,
                  'runtime_profile': ref(v1.PROFILE), 'new_LO_model_solver_Harbor_calls': 0}
        frozen = write(output/'prospective.json', record)
        modes = v1.audit_complete(f, actual['results'], output, audit)
        plans = write(output/'plans_frozen.json', {**record, 'plans': [{'mode': mode,
            'plan': {'variant_id': 'R2-01-'+prefix}} for mode, prefix in zip(v1.MODES, ('FM', 'DBG'))]})
        tasks = []
        for mode, prefix in zip(v1.MODES, ('FM', 'DBG')):
            folder = output/'private'/('R2-01-'+prefix); material = folder/'materialized'
            (material/'public').mkdir(parents=True); (material/'private').mkdir()
            native = actual['results'][prefix+'_input2']; goal = f['genuine_goal']; instruction = f['instruction_bytes'][mode]
            for source, destination in ((native, material/'public/input.xlsx'), (goal, material/'private/goal.xlsx'),
                                        (instruction, material/'public/instruction.md')):
                shutil.copyfile(source['path'], destination)
            signature = hashlib.sha256(json.dumps({'mode': mode, 'input': native['sha256'], 'goal': goal['sha256'],
                'instruction': instruction['sha256']}, sort_keys=True).encode()).hexdigest()
            task_id = ('fm-' if prefix == 'FM' else 'dbg-')+'ringfenced-r2-01-'+signature[:20]
            individual = write(folder/'individual_engineering.json', {**modes[mode], 'continuation': frozen,
                'source_certificate': admission['certificate'], 'actual_resources': actual['actual_resource_observations'], 'owned_cleanup': actual['owned_cleanup']})
            cap = folder/'worker_cap.json'
            directory = export.export_resource_harbor(material, output/'SpreadsheetEval'/task_id,
                {'task_id': task_id, 'mode': mode, 'revision': 0, 'revision_hash': signature, 'variant_id': 'R2-01-'+prefix,
                 'source_kind': 'unchanged_ringfenced_pair_finite_task8_continuation', 'difficulty_status': 'development_pending'},
                ROOT, runtime_profile=v1.PROFILE, audit_path=cap)
            task = {'task_id': task_id, 'mode': mode, 'revision': 0, 'revision_hash': signature, 'source_id': goal['sha256'],
                    'task_directory': str(directory), 'variant_id': 'R2-01-'+prefix, 'execution_budget': v1.BUDGET,
                    'harbor_export_binding': export.inspect_resource_export(directory, audit_path=cap),
                    'worker_cap_audit': ref(cap), 'individual_engineering': individual, 'plan_freeze': plans}
            tasks.append(task); write(folder/'task_record.json', task)
        require(recipes() == record['recipe'] and ref(export.__file__) == record['export_adapter'], 'The export recipe changed during finalization')
        terminal = write(output/'engineered_batch.json', {'kind': 'individually_engineered_business_revision_batch', 'version': 1,
            'count': 2, 'tasks': tasks, 'selected_task_ids': [task['task_id'] for task in tasks], 'source': f['source_manifest'], 'source_count': 1,
            'qualified': False, 'business_difficulty_evidence_pending': True, 'actual_LO_calls_completed': 0,
            'inherited_source_calls': 3, 'inherited_input_calls': 4, 'inherited_remaining_control_calls': 4,
            'control_terminal': actual['prospective'], 'actual_control_chain': record['controls_terminal'],
            'new_LO_model_solver_Harbor_calls': 0, 'duration_seconds': time.monotonic()-started})
        audit.update_run(status='completed', stage='engineering_complete'); return terminal
    except BaseException as error:
        write(output/'failure.json', {'type': type(error).__name__, 'reason': str(error), 'new_LO_model_solver_Harbor_calls': 0, 'qualified': False})
        audit.update_run(status='failed', stage='export_failed'); raise
    finally:
        audit.export(); server.stop(); audit.db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('controls'); p.add_argument('--output', type=Path, required=True); p.add_argument('--port', type=int, default=0)
    p = sub.add_parser('finalize'); p.add_argument('--controls-terminal', type=Path, required=True); p.add_argument('--output', type=Path, required=True); p.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    result = controls(args.output, port=args.port) if args.command == 'controls' else finalize(args.controls_terminal, args.output, port=args.port)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
