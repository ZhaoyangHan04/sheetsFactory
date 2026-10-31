#!/usr/bin/env python3
"""Frozen P01–P20 orchestration around the unchanged original producer16 API.

Each profile gets one original best/runner workflow. Rejections and time limits
remain in the ordered result inventory. This entry creates no sources or tasks.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
DEFAULT_CONFIG = ROOT/'config/research/linear_capital_reference_P01_P20_v1.json'
API_PATH = ROOT/'scripts/run_linear_capital_producer_reference.py'
ORDER = [f'P{i:02d}' for i in range(1, 21)]
KIND = 'original_producer16_fixed_twenty_reference_batch'


def load_api():
    definition = importlib.util.spec_from_file_location('_original_twenty_reference_api', API_PATH)
    module = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(module)
    return module


api = load_api()
ref, read, write, require = api.reference, api.read, api.write, api.require


def checked_config(path):
    config = read(path)
    expected = read(DEFAULT_CONFIG)
    require(config == expected, 'Use the complete fixed P01–P20 original-v1 contract')
    require(config['profile_order'] == ORDER and config['max_parallel'] == 4
        and type(config['max_parallel']) is int and config['retries'] == 0
        and type(config['retries']) is int, 'The ordered inventory or no-retry contract changed')
    require(ref(API_PATH)['sha256'] == config['original_api_sha256'], 'The original producer16 API changed')
    resources = config['resources']
    require(resources == {'cpus': 16, 'threads': 16, 'memory_bytes': 32*1024**3,
        'pids_limit': 256, 'network': 'none', 'seconds_per_phase': 3600,
        'image_id': api.runtime.IMAGE_ID}, 'The original producer resource envelope changed')
    lineage = {}
    for key in ('raw_catalog', 'finance_terminal', 'finance_freeze', 'finance_accounting_correction'):
        item = config[key]; current = ref(ROOT/item['path'])
        require(current['sha256'] == item['sha256'], 'The authorized lineage changed: '+key)
        lineage[key] = current
    return config, lineage


def checked_inventory(config, lineage):
    catalog, finance, freeze, correction = [read(lineage[k]) for k in
        ('raw_catalog', 'finance_terminal', 'finance_freeze', 'finance_accounting_correction')]
    require(catalog['profile_order'] == finance['profile_order'] == freeze['profile_order'] == ORDER
        and [p['profile_id'] for p in catalog['profiles']] == ORDER
        and [p['profile_id'] for p in finance['profiles']] == ORDER
        and [p['profile_id'] for p in freeze['profiles']] == ORDER,
        'Every previously frozen profile must appear once in its original order')
    require(finance['passed'] is freeze['passed'] is True and freeze['terminal'] == lineage['finance_terminal']
        and correction['prior_terminal'] == lineage['finance_terminal']
        and correction['prior_freeze'] == lineage['finance_freeze']
        and correction['corrected_total_implementation_universe_calls'] == 80
        and correction['additional_financial_forwards_by_correction'] == 0,
        'The completed finance batch and append-only corrected accounting are required')
    inventory = []
    for raw, actual, frozen in zip(catalog['profiles'], finance['profiles'], freeze['profiles'], strict=True):
        require(actual['passed'] is True and actual['returncode'] == 0, 'All original finance profiles must pass')
        worker = read(actual['worker_terminal'])
        require(worker['passed'] is True and worker['terminal'] == frozen['terminal'], 'Finance terminal ancestry changed')
        require(read(frozen['terminal'])['passed'] is True, 'An original finance check failed')
        require(ref(raw['specification']['path']) == raw['specification']
            and ref(raw['raw_preparation']['path']) == raw['raw_preparation'], 'A fixed raw specification changed')
        inventory.append({'profile_id': raw['profile_id'], 'specification': raw['specification'],
            'raw_preparation': raw['raw_preparation'], 'finance_terminal': frozen['terminal']})
    return inventory


def recipe(config_path):
    return {**api.recipes(), str(Path(__file__).resolve()): ref(__file__),
        str(Path(config_path).resolve()): ref(config_path)}


def prepare(config_path, output):
    config_path = Path(config_path).resolve(); output = Path(output).absolute()
    require(output == output.resolve() and output.is_relative_to(ROOT/'outputs') and not output.exists(),
        'Use a fresh private batch directory')
    config, lineage = checked_config(config_path)
    inventory = checked_inventory(config, lineage)
    output.mkdir(parents=True)
    # This full declaration precedes preparation and every native solver call.
    declaration = write(output/'inventory.json', {'kind': KIND+'_inventory', 'version': 1,
        'profile_order': ORDER, 'profiles': inventory, 'lineage': lineage,
        'reference_policy': config['reference_policy'], 'max_parallel': 4, 'retries': 0,
        'maximum_native_solver_calls': 40, 'actual_solver_calls': 0})
    preparations = {}
    try:
        for row in inventory:
            pid = row['profile_id']; folder = output/'profiles'/pid
            preparations[pid] = api.prepare(row['finance_terminal'], folder)
            api.validate_prepared(folder)
        compatibility = write(output/'zero_service_compatibility.json', {
            'passed': True, 'profile_order': ORDER, 'validated_preparations': preparations,
            'original_api': ref(API_PATH), 'original_runtime_profile': api._profile(),
            'native_solver_calls': 0, 'financial_forward_calls': 0, 'LO_calls': 0,
            'model_calls': 0, 'Harbor_jobs': 0})
        return write(output/'prospective.json', {'kind': KIND, 'version': 1,
            'frozen_at': datetime.now(timezone.utc).isoformat(), 'config': ref(config_path),
            'inventory': declaration, 'profile_order': ORDER, 'preparations': preparations,
            'lineage': lineage, 'recipe': recipe(config_path), 'compatibility': compatibility,
            'reference_policy': config['reference_policy'], 'runtime_profile': api._profile(),
            'max_parallel': 4, 'retries': 0, 'maximum_native_solver_calls': 40,
            'native_solver_calls': 0, 'LO_calls': 0, 'model_calls': 0, 'Harbor_jobs': 0,
            'source_or_task_or_quality_or_difficulty_certified': False, 'qualified': False, 'task_count': 0})
    except BaseException as error:
        write(output/'compatibility_failure.json', {'error_type': type(error).__name__, 'error': str(error),
            'preparations': preparations, 'native_solver_calls': 0, 'all_partial_artifacts_retained': True})
        raise


def validate(output, *, validate_profiles=True):
    output = Path(output).resolve(); prospective = read(output/'prospective.json')
    config, lineage = checked_config(prospective['config'])
    inventory = checked_inventory(config, lineage)
    require(prospective['kind'] == KIND and type(prospective['version']) is int and prospective['version'] == 1
        and prospective['profile_order'] == ORDER and list(prospective['preparations']) == ORDER
        and prospective['max_parallel'] == 4 and type(prospective['max_parallel']) is int
        and prospective['retries'] == 0 and type(prospective['retries']) is int
        and prospective['reference_policy'] == config['reference_policy']
        and prospective['runtime_profile'] == api._profile()
        and prospective['lineage'] == lineage and prospective['recipe'] == recipe(prospective['config']['path']),
        'The prospective batch contract changed')
    declared = read(prospective['inventory'])
    require(declared['profiles'] == inventory and declared['profile_order'] == ORDER,
        'The complete pre-call inventory changed')
    api._refs(prospective)
    if validate_profiles:
        for pid in ORDER:
            folder = output/'profiles'/pid
            require(prospective['preparations'][pid] == ref(folder/'preparation.json'), 'A profile preparation changed')
            api.validate_prepared(folder)
    return prospective


def worker(output, pid):
    output = Path(output).resolve(); require(pid in ORDER, 'Unknown profile')
    frozen = validate(output, validate_profiles=False); folder = output/'profiles'/pid
    clock = time.monotonic(); result = {'profile_id': pid, 'passed': False, 'retry_authorized': False}
    require(not (folder/'worker_terminal.json').exists(), 'Preserve the first profile attempt')
    try:
        terminal = api.execute_prepared(folder); result['terminal'] = terminal
        if read(terminal)['passed'] is True:
            completed = api.validate_completed(terminal)
            result.update(passed=True, gap_pence=completed['gap_pence'],
                selected_project_count=completed['selected_project_count'])
            result['cold_validation'] = write(folder/'cold_completed_validation.json', {
                'passed': True, 'terminal': terminal, 'original_validator': ref(API_PATH),
                'original_v1_best_and_runner_OPTIMAL': True, 'both_complete_matrix_rows_per_phase': 881,
                'independent_financial_implementations': 2, 'additional_financial_forward_calls': 0})
        else:
            result.update(error_type=read(terminal).get('error_type'), error=read(terminal).get('error'))
    except BaseException as error:
        result.update(error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
        if (folder/'terminal.json').exists(): result['terminal'] = ref(folder/'terminal.json')
    result.update(elapsed_seconds=time.monotonic()-clock, prospective=ref(output/'prospective.json'),
        model_calls=0, LO_calls=0, Harbor_jobs=0, source_builds=0, task_count=0, qualified=False,
        source_or_task_or_quality_or_difficulty_certified=False)
    terminal = write(folder/'worker_terminal.json', result)
    print(json.dumps({'profile_id': pid, 'worker_terminal': terminal, 'passed': result['passed']}), flush=True)
    return 0 if result['passed'] else 1


def owned_jobs(folder, *, tolerate_partial=False):
    result = {}
    for phase in ('best', 'runner'):
        job = folder/'jobs'/phase
        if not (job/'started.json').exists(): continue
        row = {'phase_attempt_started': ref(job/'started.json')}
        result[phase] = row
        if (job/'host_before.json').exists():
            try:
                before = (json.loads((job/'host_before.json').read_text()) if tolerate_partial
                    else read(job/'host_before.json'))
            except (OSError, json.JSONDecodeError):
                if tolerate_partial: continue
                raise
            cid = before.get('Id', '')
            require(re.fullmatch('[0-9a-f]{64}', cid) is not None, 'A full owned container identity is required')
            row.update(container_id=cid, host_before=ref(job/'host_before.json'))
        if (job/'terminal.json').exists(): row['terminal'] = ref(job/'terminal.json')
    return result


def execute(output):
    from sheets_factory.core.audit import AuditStore
    from sheets_factory.dashboard import DashboardServer
    from sheets_factory.resume import ProducerLease
    output = Path(output).resolve(); frozen = validate(output)
    require(not (output/'started.json').exists(), 'Preserve the first batch execution; no retry is authorized')
    lease = ProducerLease(output).acquire(); audit = server = None
    active = {}; done = {}; dispatched = []; clock = time.monotonic(); failed = False
    try:
        audit = AuditStore(output/'audit', {'id': output.name, 'name': 'P01–P20 original-v1 best and runner references',
            'status': 'running', 'target_count': 0, 'producer_active': True, 'producer_pid': os.getpid(),
            'profile_order': ORDER, 'max_parallel': 4, 'model_calls': 0})
        server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=0)
        url = server.start(); audit.update_run(dashboard_url=url); audit.export()
        start = write(output/'started.json', {'prospective': ref(output/'prospective.json'),
            'producer_pid': os.getpid(), 'dashboard_url': url, 'at': datetime.now(timezone.utc).isoformat()})
        print(json.dumps({'dashboard_url': url, 'output': str(output), 'producer_pid': os.getpid(), 'started': start}), flush=True)
        last_export = 0
        while len(done) < len(ORDER):
            while len(active) < 4 and len(dispatched) < len(ORDER):
                pid = ORDER[len(dispatched)]; folder = output/'profiles'/pid
                stdout = (folder/'launcher.stdout').open('x'); stderr = (folder/'launcher.stderr').open('x')
                command = [sys.executable, str(Path(__file__).resolve()), 'worker', '--prepared', str(output), '--profile', pid]
                process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr)
                launcher = write(folder/'launcher_started.json', {'pid': process.pid, 'command': command,
                    'profile_id': pid, 'prospective': ref(output/'prospective.json'), 'at': datetime.now(timezone.utc).isoformat()})
                active[pid] = (process, stdout, stderr, launcher); dispatched.append(pid)
                audit.emit('reference.profile_started', profile_id=pid, producer_pid=process.pid, launcher=launcher)
            for pid, (process, stdout, stderr, launcher) in list(active.items()):
                status = process.poll()
                if status is None: continue
                stdout.close(); stderr.close(); folder = output/'profiles'/pid
                record = ref(folder/'worker_terminal.json') if (folder/'worker_terminal.json').exists() else None
                value = read(record) if record else {'passed': False, 'error': 'Worker ended without terminal'}
                done[pid] = {'profile_id': pid, 'returncode': status, 'worker_terminal': record,
                    'passed': status == 0 and value['passed'] is True, 'launcher_started': launcher,
                    'stdout': ref(folder/'launcher.stdout'), 'stderr': ref(folder/'launcher.stderr'),
                    'jobs': owned_jobs(folder)}
                del active[pid]
                audit.emit('reference.profile_completed', profile_id=pid, passed=done[pid]['passed'], worker_terminal=record)
                audit.record('nodes', {'node': pid, 'status': 'completed' if done[pid]['passed'] else 'rejected',
                    'duration_ms': value.get('elapsed_seconds', 0)*1000, 'receipt': record})
                print(json.dumps({'profile_completed': pid, 'passed': done[pid]['passed'], 'completed': len(done)}), flush=True)
            if time.monotonic()-last_export >= 2:
                current = {}
                for pid in active:
                    folder = output/'profiles'/pid
                    try: stage = json.loads((folder/'audit/summary.json').read_text())['run'].get('active_stage', 'starting')
                    except (OSError, ValueError, KeyError): stage = 'starting'
                    current[pid] = {'stage': stage, 'jobs': owned_jobs(folder, tolerate_partial=True)}
                audit.update_run(completed_profiles=len(done), accepted_profiles=sum(p['passed'] for p in done.values()),
                    rejected_profiles=[p for p in ORDER if p in done and not done[p]['passed']],
                    active_profiles=current, dispatched_profile_order=dispatched, elapsed_seconds=time.monotonic()-clock)
                audit.export(); last_export = time.monotonic()
            time.sleep(.25)
        require(dispatched == ORDER and list(sorted(done)) == ORDER, 'Every frozen profile must execute exactly once')
        validate(output, validate_profiles=False)
        rows = [done[pid] for pid in ORDER]
        report = {'kind': KIND+'_terminal', 'version': 1, 'passed': all(p['passed'] for p in rows),
            'prospective': ref(output/'prospective.json'), 'profile_order': ORDER, 'profiles': rows,
            'accepted_profiles': [p['profile_id'] for p in rows if p['passed']],
            'rejected_profiles': [p['profile_id'] for p in rows if not p['passed']],
            'phase_attempts_started': sum(len(p['jobs']) for p in rows),
            'owned_containers_created': sum('container_id' in j for p in rows for j in p['jobs'].values()),
            'all_attempts_and_rejections_retained': True, 'retries': 0, 'max_parallel': 4,
            'elapsed_seconds': time.monotonic()-clock, 'runtime_profile': api._profile(),
            'finance_accounting_correction': frozen['lineage']['finance_accounting_correction'],
            'prior_finance_implementation_universe_calls_corrected': 80,
            'new_financial_forward_calls': 0, 'model_calls': 0, 'LO_calls': 0, 'Harbor_jobs': 0,
            'source_builds': 0, 'task_count': 0, 'qualified': False,
            'source_or_task_or_quality_or_difficulty_certified': False}
        terminal = write(output/'terminal.json', report)
        audit.update_run(status='completed', producer_active=False, terminal_receipt=terminal,
            completed_profiles=20, active_profiles={}); audit.export()
        print(json.dumps({'terminal': terminal, 'accepted': report['accepted_profiles'], 'rejected': report['rejected_profiles']}), flush=True)
        return terminal
    except BaseException as error:
        failed = True
        write(output/'orchestration_failure.json', {'error_type': type(error).__name__, 'error': str(error),
            'traceback': traceback.format_exc(), 'completed': done, 'dispatched_profile_order': dispatched,
            'active_owned_children': {pid: entry[0].pid for pid, entry in active.items()},
            'queued_not_dispatched': ORDER[len(dispatched):], 'no_new_dispatch_after_failure': True})
        for process, stdout, stderr, _ in active.values():
            process.wait(); stdout.close(); stderr.close()
        raise
    finally:
        try:
            if audit and failed: audit.update_run(status='failed', producer_active=False); audit.export()
        finally:
            try:
                if server: server.stop()
            finally:
                try:
                    if audit: audit.db.close()
                finally: lease.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('prepare'); command.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    command.add_argument('--output', type=Path, required=True)
    for name in ('validate', 'run', 'worker'):
        command = commands.add_parser(name); command.add_argument('--prepared', type=Path, required=True)
        if name == 'worker': command.add_argument('--profile', required=True, choices=ORDER)
    args = parser.parse_args(argv)
    if args.command == 'prepare': result = prepare(args.config, args.output)
    elif args.command == 'validate':
        validate(args.prepared); result = {'passed': True, 'native_solver_calls': 0}
    elif args.command == 'worker': return worker(args.prepared, args.profile)
    else: result = execute(args.prepared)
    print(json.dumps(result, indent=2)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
