#!/usr/bin/env python3
"""Freeze ten N360 sources/pairs; only a later --prepared --run starts LO."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
DEFAULT = ROOT/'config/research/linear_capital_scaled_engineering_pass10_v1.json'
ORDER = [f'L360-P{i:02d}' for i in (1, 2, 7, 9, 10, 14, 16, 17, 18, 20)]
KIND = 'fixed_scaled_pass10_source_and_engineering_pair_batch'
_APIS = None

def apis():
    global _APIS
    if _APIS is None:
        modules = []
        for name in ('build_linear_capital_scaled_source', 'prepare_linear_capital_scaled_cached_view_pair'):
            descriptor = importlib.util.spec_from_file_location('_pass10_'+name, ROOT/'scripts'/f'{name}.py')
            module = importlib.util.module_from_spec(descriptor); descriptor.loader.exec_module(module); modules.append(module)
        _APIS = tuple(modules)
    return _APIS

def require(value, message):
    if not value: raise ValueError(message)

def ref(path): return apis()[0].reference(path)
def read(value): return apis()[0].read(value)
def write(path, value): return apis()[0].write(path, value)
def now(): return datetime.now(timezone.utc).isoformat()
def claim(path, value):
    with Path(path).open('x') as stream: json.dump(value, stream)
    return ref(path)

def recipe():
    source, pair = apis(); pair.frozen_dependencies()
    return {**source.recipes(), **pair._module(pair.POOL).recipes(),
        **{str(p): ref(p)['sha256'] for p in (Path(__file__).resolve(), Path(pair.__file__), pair.quality.DEFAULT_PROVIDERS)}}

def inventory(config, output):
    cfg = read(config); batch = read(cfg['reference_batch']); audit = read(cfg['reference_completed_audit'])
    require(cfg == read(DEFAULT) and cfg['kind'] == KIND and cfg['profile_order'] == ORDER
        and cfg['max_parallel_profiles'] == 2 and cfg['retries'] == 0, 'Use the fixed ten-profile contract')
    require(batch['kind'] == 'scaled_producer16_fixed_twenty_reference_batch_terminal'
        and batch['profile_order'] == [f'L360-P{i:02d}' for i in range(1, 21)]
        and batch['accepted_profiles'] == ORDER and batch['rejected_profiles'] == cfg['rejected_profiles_retained']
        and audit['aggregate'] == cfg['reference_batch'] and audit['all_native_phase_resource_exit_and_owned_cleanup_checks_passed'] is True,
        'The complete original twenty outcomes and bounded native audit are required')
    require(ref(cfg['runtime_profile']['path']) == cfg['runtime_profile'], 'The source runtime profile changed'); rows = []
    for actual in batch['profiles']:
        worker = read(actual['worker_terminal'])
        require(worker['passed'] is actual['passed'], 'A retained reference outcome changed')
        if actual['profile_id'] not in ORDER: continue
        proof = read(worker['terminal']); pid = actual['profile_id']; reused = cfg['reuse'].get(pid)
        require(actual['passed'] is proof['passed'] is True and proof['kind'] == 'linear_capital_scaled_producer16_best_runner_dual_financial_reference'
            and proof['version'] == 2, 'Only genuine N360 strict reference passes enter source preparation')
        read(proof['specification'])
        if reused:
            source = read(reused['source_manifest']); pair = read(reused['pair_terminal'])
            require(source['kind'] == 'independently_verified_linear_capital_scaled_native_source'
                and source['independent_reference'] == worker['terminal'] and source['runtime_profile'] == cfg['runtime_profile']
                and pair['passed'] is True and pair['version'] == 2 and pair['profile_id'] == pid
                and pair['kind'] in ('linear_capital_scaled_pool_view_pair_actual_validation', 'linear_capital_scaled_cached_pool_view_pair_actual_validation')
                and pair['source_provider'] == 'scaled360' and pair['source_manifest'] == reused['source_manifest']
                and pair['validation_terminals'] == reused['mode_terminals'] and pair['LO_call_count_exact'] == 18,
                'Existing source/pair lineage changed; hashes alone never confer admission')
            require(set(reused['mode_terminals']) == {'financial_modeling', 'debugging'}, 'Both existing modes must be retained')
            for mode, terminal in reused['mode_terminals'].items():
                value = read(terminal)
                require(value['mode'] == mode and value['source_admission'] == reused['source_manifest'], 'A reused view changed source')
        rows.append({'profile_id': pid, 'reference': worker['terminal'], 'specification': proof['specification'],
            'reuse': reused, 'source_directory': str(output/'profiles'/pid/'source'), 'pair_directory': str(output/'profiles'/pid/'pair')})
    require([row['profile_id'] for row in rows] == ORDER and set(cfg['reuse']) == set(ORDER[:2]), 'No filtering, substitutions or extra reuse')
    return cfg, rows

def prepare(output, config=DEFAULT):
    output = Path(output).resolve(); require(not output.exists(), 'Use a fresh output; failed preparations are retained')
    cfg, rows = inventory(config, output); output.mkdir(parents=True)
    setup = write(output/'setup.json', {'configuration': ref(config), 'profiles': rows, 'recipe': recipe(),
        'runtime_profile': cfg['runtime_profile'], 'qualified': False, 'LO_calls': 0, 'model_calls': 0, 'solver_calls': 0})
    preparations = {}
    try:
        for row in rows:
            (output/'profiles'/row['profile_id']).mkdir(parents=True)
            if not row['reuse']:
                preparations[row['profile_id']] = apis()[0].prepare(row['specification']['path'], row['reference'],
                    row['source_directory'], profile=cfg['runtime_profile']['path'])
        return write(output/'prospective.json', {'kind': KIND, 'version': 1, 'setup': setup, 'source_preparations': preparations,
            'reuse_requires_genuine_cold_admission_at_run': True, 'LO_calls': 0, 'model_calls': 0, 'solver_calls': 0,
            'Harbor_calls': 0, 'qualified': False, 'normal_quality_or_difficulty_certified': False})
    except BaseException as error:
        write(output/'preparation_failure.json', {'error': str(error), 'traceback': traceback.format_exc(), 'completed_preparations': preparations}); raise

def validate(output):
    output = Path(output).resolve(); frozen = read(output/'prospective.json'); setup = read(frozen['setup'])
    cfg, rows = inventory(setup['configuration'], output)
    require(frozen['kind'] == KIND and frozen['version'] == 1 and setup['profiles'] == rows
        and setup['recipe'] == recipe() and set(frozen['source_preparations']) == set(ORDER[2:]), 'Frozen setup or source mapping changed')
    for row in rows:
        if row['reuse']: continue
        record = frozen['source_preparations'][row['profile_id']]; prepared = read(record)
        require(record == ref(Path(row['source_directory'])/'preparation.json') and prepared['independent_reference'] == row['reference']
            and prepared['original_specification'] == row['specification'] and prepared['runtime_profile'] == cfg['runtime_profile'], 'A source preparation changed profile or inputs')
    return cfg, rows, frozen

def worker(output, pid):
    output = Path(output).resolve(); _, rows, _ = validate(output); row = next(r for r in rows if r['profile_id'] == pid)
    require((output/'started.json').exists(), 'The total dashboard must start before profile work')
    folder = output/'profiles'/pid; claim(folder/'worker_started.json', {'pid': os.getpid(), 'at': now()})
    records = {}; stages = []; clock = time.monotonic(); error = None
    def stage(name, operation):
        tick = time.monotonic(); write(folder/'phase.json', {'stage': name, 'started_at': now()})
        try: return operation()
        finally:
            stages.append({'stage': name, 'passed': sys.exc_info()[0] is None, 'elapsed_seconds': time.monotonic()-tick, 'finished_at': now()})
            write(folder/'stages.json', stages)
    try:
        source, pair = apis(); reused = row['reuse']
        records['source_manifest'] = reused['source_manifest'] if reused else stage('source_3LO_and_full_audits', lambda: source.execute_prepared(row['source_directory']))
        session = stage('genuine_cold_source_admission', lambda: pair.PairSession(records['source_manifest']))
        if reused:
            for mode, terminal in reused['mode_terminals'].items():
                result = stage('cold_existing_'+mode, lambda terminal=terminal: session.validator.validate_completed(terminal))
                require(result['passed'] is True, 'A reused view failed its genuine completed validator')
            records['pair_terminal'] = reused['pair_terminal']
        else:
            records['pair_preparation'] = stage('pair_prepare', lambda: pair.prepare(records['source_manifest'], row['pair_directory'], session=session))
            records['pair_terminal'] = stage('pair_7plus11LO_fullD_controls_and_cold', lambda: pair.execute_prepared(row['pair_directory'], session=session))
        require(read(records['pair_terminal'])['passed'] is True, 'Only a completed actual pair can pass engineering')
    except BaseException as failure: error = {'type': type(failure).__name__, 'error': str(failure), 'traceback': traceback.format_exc()}
    terminal = write(folder/'worker_terminal.json', {'profile_id': pid, 'passed': error is None, 'records': records,
        'stages': stages, 'elapsed_seconds': time.monotonic()-clock, 'error': error, 'reused_without_LO': row['reuse'] is not None,
        'prospective': ref(output/'prospective.json'), 'retries': 0, 'model_calls': 0, 'solver_calls': 0, 'Harbor_calls': 0,
        'qualified': False, 'normal_quality_or_difficulty_certified': False})
    print(json.dumps(terminal), flush=True); return 0 if error is None else 1

def execute(output):
    from sheets_factory.core.audit import AuditStore
    from sheets_factory.dashboard import DashboardServer
    from sheets_factory.resume import ProducerLease
    output = Path(output).resolve(); cfg, rows, _ = validate(output)
    require(not (output/'started.json').exists(), 'Preserve the first execution; retries are disabled')
    lease = ProducerLease(output).acquire(); audit = server = None; active = {}; done = {}; pending = list(rows); clock = time.monotonic()
    try:
        audit = AuditStore(output/'audit', {'id': output.name, 'name': 'N360 ten source and engineering pairs', 'status': 'running', 'target_count': 0})
        server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=0); url = server.start()
        claim(output/'started.json', {'dashboard_url': url, 'pid': os.getpid(), 'prospective': ref(output/'prospective.json'), 'at': now()})
        print(json.dumps({'dashboard_url': url, 'pid': os.getpid(), 'output': str(output)}), flush=True)
        while pending or active:
            while pending and len(active) < cfg['max_parallel_profiles']:
                row = pending.pop(0); pid = row['profile_id']; folder = output/'profiles'/pid
                stdout = (folder/'stdout.txt').open('x'); stderr = (folder/'stderr.txt').open('x')
                command = [sys.executable, str(Path(__file__).resolve()), '--prepared', str(output), '--worker', pid]
                process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr)
                launcher = write(folder/'launcher.json', {'pid': process.pid, 'command': command, 'started_at': now()})
                active[pid] = process, stdout, stderr, launcher
            for pid, (process, stdout, stderr, launcher) in list(active.items()):
                if process.poll() is None: continue
                stdout.close(); stderr.close(); folder = output/'profiles'/pid; path = folder/'worker_terminal.json'
                terminal = ref(path) if path.exists() else None
                done[pid] = {'profile_id': pid, 'passed': process.returncode == 0 and terminal is not None and read(terminal)['passed'],
                    'returncode': process.returncode, 'terminal': terminal, 'launcher': launcher, 'stdout': ref(folder/'stdout.txt'), 'stderr': ref(folder/'stderr.txt')}
                audit.record('nodes', {'node': pid, 'status': 'completed' if done[pid]['passed'] else 'failed', 'receipt': terminal}); del active[pid]
            live = {}
            for pid in active:
                try: live[pid] = read(output/'profiles'/pid/'phase.json')
                except (OSError, ValueError): live[pid] = {'stage': 'starting'}
                for nested in (output/'profiles'/pid).glob('*/**/audit/summary.json'):
                    try: live[pid][str(nested.relative_to(output/'profiles'/pid))] = read(nested)['run']
                    except (OSError, ValueError, KeyError): pass
            audit.update_run(dashboard_url=url, producer_active=True, producer_pid=os.getpid(), active_profiles=live,
                completed_profiles=len(done), elapsed_seconds=time.monotonic()-clock); audit.export(); time.sleep(.5)
        terminal = write(output/'terminal.json', {'kind': KIND+'_terminal', 'version': 1, 'profiles': [done[p] for p in ORDER],
            'passed': all(d['passed'] for d in done.values()), 'prospective': ref(output/'prospective.json'), 'retries': 0,
            'elapsed_seconds': time.monotonic()-clock, 'model_calls': 0, 'solver_calls': 0, 'Harbor_calls': 0, 'qualified': False})
        audit.update_run(status='completed', producer_active=False, terminal=terminal); audit.export(); return terminal
    except BaseException as error:
        write(output/'orchestration_failure.json', {'error': str(error), 'traceback': traceback.format_exc(),
            'completed': done, 'active_owned_pids': {p: v[0].pid for p, v in active.items()}, 'undispatched': pending})
        if audit: audit.update_run(status='failed', producer_active=False); audit.export()
        raise
    finally:
        for process, stdout, stderr, _ in active.values(): process.wait(); stdout.close(); stderr.close()
        if server: server.stop()
        if audit: audit.db.close()
        lease.release()

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path); parser.add_argument('--config', type=Path, default=DEFAULT)
    parser.add_argument('--prepared', type=Path); parser.add_argument('--run', action='store_true'); parser.add_argument('--worker', choices=ORDER)
    args = parser.parse_args(argv)
    if args.prepared:
        require(args.output is None and args.config == DEFAULT, 'Frozen batches cannot receive replacement setup')
        if args.worker: return worker(args.prepared, args.worker)
        result = execute(args.prepared) if args.run else {'validated': bool(validate(args.prepared)), 'LO_calls': 0}
    else:
        require(args.output is not None and not args.run and not args.worker, 'Prepare first; actual work requires a separate --prepared --run')
        result = prepare(args.output, args.config)
    print(json.dumps(result)); return 0

if __name__ == '__main__': raise SystemExit(main())
