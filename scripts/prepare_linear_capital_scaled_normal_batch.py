#!/usr/bin/env python3
"""Freeze ten normal reviews; --prepared --run waits for actual engineering."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
DEFAULT = ROOT/'config/research/linear_capital_scaled_normal_pass10_v1.json'
ORDER = [f'L360-P{i:02d}' for i in (1, 2, 7, 9, 10, 14, 16, 17, 18, 20)]
MODES = ['financial_modeling', 'debugging']
KIND = 'fixed_scaled_pass10_normal_reference_review_batch'
_ENTRY = None

def require(value, message):
    if not value: raise ValueError(message)

def now(): return datetime.now(timezone.utc).isoformat()
def ref(path):
    path = Path(path).resolve(); raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
def read(value):
    if isinstance(value, dict):
        require(ref(value['path']) == value, 'A bound artifact changed'); value = value['path']
    return json.loads(Path(value).read_text())
def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream: json.dump(value, stream, indent=2, allow_nan=False); stream.write('\n')
    return ref(path)
def entry(configuration):
    global _ENTRY
    require(ref(configuration['normal_entry']['path']) == configuration['normal_entry'], 'The frozen normal entry changed')
    if _ENTRY is None:
        definition = importlib.util.spec_from_file_location('_pass10_normal_entry', configuration['normal_entry']['path'])
        _ENTRY = importlib.util.module_from_spec(definition); definition.loader.exec_module(_ENTRY)
    return _ENTRY

def recipe(cfg, setup):
    from sheets_factory.dashboard import read_only
    normal = entry(cfg); config = normal.yaml.safe_load(Path(cfg['normal_configuration']['path']).read_text())
    require(config['diagnosis']['selection'] == {'include': cfg['all_twelve_checks_required'], 'exclude': []}
        and config['diagnosis']['reference_evidence_policy'] == 'reference_review'
        and config['agents']['model'] == 'gpt-6-sol' and config['agents']['reasoning_effort'] == 'high',
        'The full frozen normal reference-review policy is required')
    return {**setup['recipe'], **normal.recipes(config, []),
        **{str(p.resolve()): ref(p)['sha256'] for p in (Path(__file__), DEFAULT, Path(cfg['normal_entry']['path']),
            Path(cfg['normal_configuration']['path']), normal.pipeline.DEFAULT_PROVIDERS, Path(read_only.__file__))}}

def inventory(config, output):
    cfg = read(config); require(cfg == read(DEFAULT) and cfg['kind'] == KIND and cfg['version'] == 1
        and cfg['profile_order'] == ORDER and cfg['mode_order'] == MODES and cfg['source_provider'] == 'scaled360'
        and cfg['max_parallel_profiles'] == 2 and cfg['outer_retries'] == 0
        and cfg['all_twelve_checks_required'] == [f'Q{i:02d}' for i in range(1, 13)]
        and cfg['reference_evidence_policy'] == 'reference_review' and cfg['engineering_or_prior_quality_inherited'] is False,
        'Use the fixed ten-profile normal contract')
    engineering = read(cfg['engineering_prospective']); setup = read(engineering['setup'])
    require(engineering['kind'] == 'fixed_scaled_pass10_source_and_engineering_pair_batch'
        and engineering['version'] == 1 and [r['profile_id'] for r in setup['profiles']] == ORDER,
        'The fixed N360 engineering inventory changed')
    require(ref(cfg['normal_configuration']['path']) == cfg['normal_configuration'], 'The normal configuration changed')
    external = cfg['external_P01']; old = read(external['preflight'])
    require(external['profile_id'] == ORDER[0] and external['monitor_only'] is True
        and Path(external['preflight']['path']) == Path(external['prepared_directory'])/'preflight_manifest.json'
        and old['kind'] == 'prepared_complete_native_linear_capital_scaled_reference_quality'
        and old['version'] == 2 and old['count'] == 2 and old['targets'] == dict.fromkeys(MODES, 1)
        and old['configuration_input'] == cfg['normal_configuration'], 'P01 must remain its existing original two-mode attempt')
    base = Path(cfg['engineering_prospective']['path']).parent
    rows = [{**r, 'engineering_worker_path': str(base/'profiles'/r['profile_id']/'worker_terminal.json'),
        'normal_directory': str(output/'profiles'/r['profile_id']/'normal')} for r in setup['profiles']]
    return cfg, setup, rows

def prepare(output, config=DEFAULT):
    output = Path(output).resolve(); require(not output.exists(), 'Preserve previous preparations')
    cfg, setup, rows = inventory(config, output); output.mkdir(parents=True)
    return write(output/'prospective.json', {'kind': KIND, 'version': 1, 'configuration': ref(config),
        'engineering_setup': read(cfg['engineering_prospective'])['setup'], 'profiles': rows, 'recipe': recipe(cfg, setup),
        'actual_input_references_bound_only_after_engineering_completion': True,
        'actual_models': 0, 'actual_LO_calls': 0, 'actual_Harbor_jobs': 0, 'solver_calls': 0, 'qualified': False})

def validate(output):
    output = Path(output).resolve(); frozen = read(output/'prospective.json'); cfg, setup, rows = inventory(frozen['configuration'], output)
    require(frozen['kind'] == KIND and frozen['version'] == 1 and frozen['profiles'] == rows
        and frozen['engineering_setup'] == read(cfg['engineering_prospective'])['setup']
        and frozen['recipe'] == recipe(cfg, setup), 'The frozen batch setup changed')
    for path, digest in frozen['recipe'].items(): require(ref(path)['sha256'] == digest, 'A frozen dependency changed: '+path)
    return cfg, rows, frozen

def completed_inputs(cfg, row):
    path = Path(row['engineering_worker_path'])
    if not path.exists(): return None
    try: worker = read(path)
    except json.JSONDecodeError: return None  # A live producer may still be writing its terminal.
    require(worker['profile_id'] == row['profile_id'] and worker['prospective'] == cfg['engineering_prospective']
        and worker['passed'] is True, 'The fixed engineering case failed or changed')
    source_ref = worker['records']['source_manifest']; pair_ref = worker['records']['pair_terminal']
    source, pair = read(source_ref), read(pair_ref)
    require(source['kind'] == 'independently_verified_linear_capital_scaled_native_source'
        and source['independent_reference'] == row['reference']
        and read(source['source_preparation'])['original_specification'] == row['specification']
        and pair['kind'] in ('linear_capital_scaled_pool_view_pair_actual_validation', 'linear_capital_scaled_cached_pool_view_pair_actual_validation')
        and pair['version'] == 2 and pair['passed'] is True and pair['profile_id'] == row['profile_id']
        and pair['source_provider'] == 'scaled360' and pair['source_manifest'] == source_ref
        and set(pair['validation_terminals']) == set(MODES) and pair['LO_call_count_exact'] == 18,
        'Require the exact source and both complete actual N360 engineering views')
    selections = []
    for mode in MODES:
        terminal = pair['validation_terminals'][mode]; value = read(terminal)
        require(value['mode'] == mode and value['passed'] is True and value['source_admission'] == source_ref,
            'A completed view changed source or mode')
        selections.append({'source_manifest': source_ref, 'validation_terminal': terminal, 'source_provider': 'scaled360'})
    return {'engineering_worker': ref(path), 'source_manifest': source_ref, 'pair_terminal': pair_ref, 'selections': selections}

def stage(folder, index, name, operation):
    tick = time.monotonic(); prefix = Path(folder)/'stages'/f'{index:02d}_{name}'
    started = write(str(prefix)+'_started.json', {'stage': name, 'at': now(), 'pid': os.getpid()})
    try: return operation()
    finally: write(str(prefix)+'_terminal.json', {'started': started, 'passed': sys.exc_info()[0] is None, 'elapsed_seconds': time.monotonic()-tick})

def worker(output, pid):
    cfg, rows, frozen = validate(output); require(pid != ORDER[0] and (Path(output)/'started.json').exists(), 'P01 is monitor-only; start the parent dashboard first')
    row = next(r for r in rows if r['profile_id'] == pid); folder = Path(output)/'profiles'/pid
    records = {}; error = None; status = None; clock = time.monotonic()
    write(folder/'worker_started.json', {'pid': os.getpid(), 'at': now()})
    try:
        inputs = completed_inputs(cfg, row); require(inputs is not None, 'Wait for genuine engineering completion')
        records['actual_inputs'] = write(folder/'actual_inputs.json', {**inputs, 'normal_recipe': frozen['recipe'], 'at': now()})
        normal = entry(cfg)
        records['preflight'] = stage(folder, 0, 'same_process_cold_prepare_both_modes', lambda: normal.prepare_many(inputs['selections'], row['normal_directory']))
        status = stage(folder, 1, 'normal_all12_and_actual_Harbor', lambda: normal.execute_prepared(row['normal_directory']))
        summary = Path(row['normal_directory'])/'summary.json'
        require(summary.exists(), 'The normal lifecycle omitted its final audit')
        final = read(summary)['run']
        require(final.get('finished_at') and final.get('producer_active') is False and final.get('exit_code') == status,
            'The normal lifecycle did not finalize its actual status')
        records['normal_summary'] = ref(summary)
    except BaseException as failure: error = {'type': type(failure).__name__, 'error': str(failure), 'traceback': traceback.format_exc()}
    summary = Path(row['normal_directory'])/'summary.json'
    if summary.exists(): records['normal_summary'] = ref(summary)
    write(folder/'worker_terminal.json', {'profile_id': pid, 'passed': error is None and status == 0,
        'normal_exit_code': status, 'records': records, 'error': error, 'elapsed_seconds': time.monotonic()-clock,
        'outer_retries': 0, 'qualified': False, 'prior_quality_inherited': False})
    return 0 if error is None and status == 0 else 1

def external_state(cfg):
    external = cfg['external_P01']; stat = Path('/proc')/str(external['pid'])/'stat'; alive = False
    try:
        fields = stat.read_text().rsplit(')', 1)[1].split()
        alive = fields[0] not in ('Z', 'X') and fields[19] == external['process_start_ticks']
    except (OSError, IndexError): pass
    summary = Path(external['prepared_directory'])/'summary.json'; value = None
    try: value = read(summary)
    except (OSError, ValueError): pass
    if alive: return None, {'stage': 'external_original_P01', 'pid': external['pid'], 'normal_run': value.get('run') if value else None}
    complete = bool(value and value['run'].get('finished_at') and value['run'].get('producer_active') is False)
    return {'profile_id': ORDER[0], 'passed': complete and value['run'].get('exit_code') == 0,
        'normal_summary': ref(summary) if complete else None, 'monitor_only': True,
        'error': None if complete else 'Original P01 process ended without a final normal audit', 'qualified': False}, None

def aggregate_snapshot(base, cfg, rows):
    """Project real child audits; never open a writer or persist child state."""
    from sheets_factory.dashboard.read_only import ReadOnlyAuditView
    tasks = {}; calls = {}; attempts = []; children = []
    for row in rows:
        pid = row['profile_id']
        directory = Path(cfg['external_P01']['prepared_directory'] if pid == ORDER[0] else row['normal_directory']).resolve()
        record = {'profile_id': pid, 'directory': str(directory), 'scope': 'normal_quality_only'}
        if not (directory/'run.sqlite').is_file():
            children.append({**record, 'audit_status': 'not_created'}); continue
        try: child = ReadOnlyAuditView(directory).snapshot()
        except (OSError, ValueError, sqlite3.Error) as error:
            children.append({**record, 'audit_status': 'unavailable', 'error_type': type(error).__name__}); continue
        children.append({**record, 'audit_status': 'read_only', 'run': child['run']})
        for index, task in enumerate(child['tasks']):
            identity = str(directory)+':'+str(task.get('id') or ('row-'+str(index)))
            tasks[identity] = {**task, 'id': identity, 'source_task_id': task.get('id'), 'normal_profile': pid, 'normal_run': str(directory)}
        for index, call in enumerate(child['llm_calls']):
            identity = str(directory)+':'+str(call.get('call_id') or ('row-'+str(index)))
            calls[identity] = {**call, 'call_id': identity, 'source_call_id': call.get('call_id'),
                'normal_profile': pid, 'normal_run': str(directory), 'stage': pid+'/'+str(call.get('stage') or 'unassigned_llm')}
        for index, node in enumerate(child.get('node_attempts', child['nodes'])):
            name = node.get('node_id', node.get('node', 'unknown'))
            attempts.append({**node, 'node_id': pid+'/'+name, 'node': pid+'/'+name,
                'normal_profile': pid, 'normal_run': str(directory), 'source_node_index': index})
    tasks, calls = list(tasks.values()), list(calls.values())
    qualified = [task for task in tasks if task.get('status') == 'qualified']
    sources = {task['source_id'] for task in tasks if task.get('source_id')}
    productive = {task['source_id'] for task in qualified if task.get('source_id')}
    inputs = sum(c.get('input_tokens') or 0 for c in calls); outputs = sum(c.get('output_tokens') or 0 for c in calls)
    unknown = sum(c.get('input_tokens') is None or c.get('output_tokens') is None for c in calls)
    unavailable = sum(c['audit_status'] == 'unavailable' for c in children)
    metrics = {**base['metrics'], 'input_tokens': inputs, 'output_tokens': outputs, 'total_tokens': inputs+outputs,
        'cached_input_tokens': sum(c.get('cached_input_tokens') or 0 for c in calls), 'llm_calls': len(calls),
        'unknown_usage_calls': unknown, 'active_llm_calls': sum(c.get('status') == 'running' for c in calls),
        'unfinished_llm_calls': sum(bool(c.get('completion_missing')) for c in calls), 'unavailable_child_audits': unavailable,
        'usage_completeness': 'known_lower_bound_with_unknowns' if unknown or unavailable else 'current_recorded_census',
        'usage_scope': 'Recorded input plus output; cached input and reasoning are subsets. Normal quality only.',
        'candidates': len(tasks), 'qualified': len(qualified), 'unique_seeds': len(sources), 'productive_seeds': len(productive),
        'ready': sum(t.get('status') == 'ready' for t in tasks), 'rejected': sum(t.get('status') == 'rejected' for t in tasks),
        'candidate_conversion': len(qualified)/len(tasks) if tasks else None,
        'source_conversion': len(productive)/len(sources) if sources else None,
        'tasks_per_seed': len(qualified)/len(sources) if sources else None,
        'cumulative_node_seconds': sum(n.get('duration_ms') or 0 for n in attempts)/1000}
    metrics.update(known_recorded_input_tokens=inputs, known_recorded_output_tokens=outputs,
        known_recorded_total_tokens=inputs+outputs, known_recorded_llm_calls=len(calls))
    if unavailable:
        metrics.update(input_tokens=None, output_tokens=None, total_tokens=None)
    run = {**base['run'], 'name': 'N360 normal quality — formal release pending'+(' — usage census incomplete' if unavailable else ''), 'target_count': 20,
        'qualified': len(qualified), 'child_normal_runs': children, 'formal_release_inferred': False,
        **{mode: sum(t.get('mode') == mode for t in qualified) for mode in MODES}}
    return {**base, 'run': run, 'metrics': metrics, 'tasks': tasks, 'llm_calls': calls,
        'nodes': ReadOnlyAuditView._stages(attempts, calls), 'node_attempts': attempts,
        'viewer': {'read_only_children': True, 'counts_scope': 'normal_quality_only', 'formal_release_inferred': False}}

def execute(output):
    from sheets_factory.core.audit import AuditStore
    from sheets_factory.dashboard import DashboardServer
    from sheets_factory.resume import ProducerLease
    output = Path(output).resolve(); cfg, rows, _ = validate(output)
    require(not (output/'started.json').exists(), 'Preserve the first execution; outer retries are disabled')
    lease = ProducerLease(output).acquire(); audit = server = None; active = {}; done = {}; pending = rows[1:]; clock = time.monotonic()
    try:
        class TotalAudit(AuditStore):
            def snapshot(self): return aggregate_snapshot(super().snapshot(), cfg, rows)
        audit = TotalAudit(output/'audit', {'id': output.name, 'status': 'waiting_engineering', 'target_count': 20})
        server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=0); url = server.start()
        write(output/'started.json', {'dashboard_url': url, 'pid': os.getpid(), 'prospective': ref(output/'prospective.json'), 'at': now()})
        print(json.dumps({'dashboard_url': url, 'pid': os.getpid(), 'output': str(output)}), flush=True)
        while pending or active or ORDER[0] not in done:
            external, external_live = external_state(cfg)
            if external is not None and ORDER[0] not in done:
                external['observation'] = write(output/'profiles'/ORDER[0]/'external_terminal.json', external); done[ORDER[0]] = external
            for row in list(pending):
                if len(active) + (ORDER[0] not in done) >= cfg['max_parallel_profiles']: break
                pid = row['profile_id']; folder = output/'profiles'/pid
                try:
                    inputs = completed_inputs(cfg, row)
                    if inputs is None:
                        base = Path(cfg['engineering_prospective']['path']).parent
                        require(not (base/'terminal.json').exists(), 'Engineering batch ended without this case terminal')
                        continue
                except BaseException as error:
                    path = Path(row['engineering_worker_path'])
                    terminal = write(folder/'engineering_failure.json', {'profile_id': pid, 'error': str(error),
                        'engineering_worker': ref(path) if path.exists() else None, 'qualified': False})
                    done[pid] = {'profile_id': pid, 'passed': False, 'terminal': terminal}; pending.remove(row); continue
                stdout = (folder/'stdout.txt'); stdout.parent.mkdir(parents=True, exist_ok=True)
                out_stream, err_stream = stdout.open('x'), (folder/'stderr.txt').open('x')
                command = [sys.executable, str(Path(__file__).resolve()), '--prepared', str(output), '--worker', pid]
                process = subprocess.Popen(command, cwd=ROOT, stdout=out_stream, stderr=err_stream)
                launcher = write(folder/'launcher.json', {'pid': process.pid, 'command': command, 'at': now()})
                active[pid] = process, out_stream, err_stream, launcher; pending.remove(row)
            for pid, (process, stdout, stderr, launcher) in list(active.items()):
                if process.poll() is None: continue
                stdout.close(); stderr.close(); folder = output/'profiles'/pid; path = folder/'worker_terminal.json'
                terminal = ref(path) if path.exists() else None
                done[pid] = {'profile_id': pid, 'passed': process.returncode == 0 and terminal is not None and read(terminal)['passed'],
                    'terminal': terminal, 'returncode': process.returncode, 'launcher': launcher}
                audit.record('nodes', {'node': pid, 'status': 'completed' if done[pid]['passed'] else 'failed', 'receipt': terminal}); del active[pid]
            live = {ORDER[0]: external_live} if external_live else {}
            for pid in active:
                folder = output/'profiles'/pid
                try: live[pid] = read(sorted((folder/'stages').glob('*_started.json'))[-1])
                except (OSError, ValueError, IndexError): live[pid] = {'stage': 'starting'}
                try: live[pid]['normal_run'] = read(folder/'normal/summary.json')['run']
                except (OSError, ValueError, KeyError): pass
            audit.update_run(dashboard_url=url, producer_active=True, active_profiles=live, waiting_engineering=[r['profile_id'] for r in pending],
                completed_profiles=len(done), elapsed_seconds=time.monotonic()-clock); audit.export(); time.sleep(.5)
        terminal = write(output/'terminal.json', {'kind': KIND+'_terminal', 'version': 1, 'profiles': [done[p] for p in ORDER],
            'passed': all(d['passed'] for d in done.values()), 'prospective': ref(output/'prospective.json'),
            'elapsed_seconds': time.monotonic()-clock, 'outer_retries': 0, 'qualified': False, 'prior_quality_inherited': False})
        audit.update_run(status='completed', producer_active=False, terminal=terminal); audit.export(); return terminal
    except BaseException as error:
        write(output/'orchestration_failure.json', {'error': str(error), 'traceback': traceback.format_exc(), 'completed': done,
            'active_owned_pids': {p: v[0].pid for p, v in active.items()}, 'undispatched': pending})
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
        require(args.output is None and args.config == DEFAULT, 'Use the existing frozen setup')
        if args.worker: return worker(args.prepared, args.worker)
        result = execute(args.prepared) if args.run else {'validated': bool(validate(args.prepared)), 'actual_services': 0}
    else:
        require(args.output is not None and not args.run and not args.worker, 'Prepare first; actual work requires --prepared --run')
        result = prepare(args.output, args.config)
    print(json.dumps(result)); return 0

if __name__ == '__main__': raise SystemExit(main())
