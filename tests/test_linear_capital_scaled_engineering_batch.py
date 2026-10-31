"""Pure orchestration tests; real source/view admission remains in frozen helpers."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def entry():
    descriptor = importlib.util.spec_from_file_location('_pass10_test', ROOT/'scripts/prepare_linear_capital_scaled_engineering_batch.py')
    module = importlib.util.module_from_spec(descriptor); descriptor.loader.exec_module(module)
    return module


@pytest.fixture
def batch(tmp_path, monkeypatch):
    module = entry(); events = []; failure = {'source': None, 'cold': False}
    def reference(path):
        path = Path(path).resolve(); raw = path.read_bytes()
        return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    def read(value):
        if isinstance(value, dict):
            assert reference(value['path']) == value, 'Changed referenced bytes'
            value = value['path']
        return json.loads(Path(value).read_text())
    def write(path, value):
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value)); return reference(path)
    def exclusive_write(path, value):
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x') as stream: json.dump(value, stream)
        return reference(path)
    runtime = write(tmp_path/'profile.yaml', {'pinned': '2CPU32'}); rows = []; reuse = {}
    for i in range(1, 21):
        pid = f'L360-P{i:02d}'; passed = pid in module.ORDER
        spec = write(tmp_path/pid/'spec.json', {'N': 360})
        proof = write(tmp_path/pid/'reference.json', {'kind': 'linear_capital_scaled_producer16_best_runner_dual_financial_reference',
            'version': 2, 'passed': passed, 'specification': spec})
        terminal = write(tmp_path/pid/'worker.json', {'passed': passed, 'terminal': proof})
        rows.append({'profile_id': pid, 'passed': passed, 'worker_terminal': terminal})
        if i > 2: continue
        source = write(tmp_path/pid/'source.json', {'kind': 'independently_verified_linear_capital_scaled_native_source',
            'independent_reference': proof, 'runtime_profile': runtime})
        modes = {mode: write(tmp_path/pid/f'{mode}.json', {'passed': True, 'mode': mode, 'source_admission': source})
            for mode in ('financial_modeling', 'debugging')}
        pair = write(tmp_path/pid/'pair.json', {'kind': 'linear_capital_scaled_pool_view_pair_actual_validation', 'version': 2,
            'passed': True, 'profile_id': pid, 'source_provider': 'scaled360', 'source_manifest': source,
            'validation_terminals': modes, 'LO_call_count_exact': 18})
        reuse[pid] = {'source_manifest': source, 'pair_terminal': pair, 'mode_terminals': modes}
    rejected = [r['profile_id'] for r in rows if not r['passed']]
    aggregate = write(tmp_path/'reference20.json', {'kind': 'scaled_producer16_fixed_twenty_reference_batch_terminal',
        'profile_order': [r['profile_id'] for r in rows], 'profiles': rows, 'accepted_profiles': module.ORDER, 'rejected_profiles': rejected})
    audit = write(tmp_path/'audit.json', {'aggregate': aggregate, 'all_native_phase_resource_exit_and_owned_cleanup_checks_passed': True})
    config = tmp_path/'config.json'
    write(config, {'kind': module.KIND, 'version': 1, 'profile_order': module.ORDER, 'rejected_profiles_retained': rejected,
        'reference_batch': aggregate, 'reference_completed_audit': audit, 'runtime_profile': runtime,
        'max_parallel_profiles': 2, 'retries': 0, 'reuse': reuse})
    monkeypatch.setattr(module, 'DEFAULT', config)
    script = tmp_path/'frozen_helper.py'; script.write_text('frozen helper')
    provider = write(tmp_path/'providers.json', {'scaled360': True})
    def source_prepare(spec, proof, output, *, profile):
        output = Path(output); events.append(('source_prepare', output.parent.name))
        assert (output.parents[2]/'setup.json').exists(), 'All profile paths must freeze first'
        return write(output/'preparation.json', {'independent_reference': proof, 'original_specification': reference(spec), 'runtime_profile': reference(profile)})
    def source_execute(output):
        output = Path(output); pid = output.parent.name; events.append(('source_3LO', pid))
        if failure['source'] == pid: raise RuntimeError('retained source failure')
        return write(output/'source.json', {'profile': pid})
    class Session:
        def __init__(self, source):
            self.source = source; events.append(('cold_source', source)); self.validator = self
        def validate_completed(self, terminal):
            events.append(('cold_view', terminal))
            if failure['cold']: raise ValueError('genuine cold admission failed')
            return read(terminal)
    def pair_prepare(source, output, *, session):
        assert session.source == source; events.append(('pair_prepare', str(output)))
        return write(Path(output)/'preparation.json', {'source_manifest': source})
    def pair_execute(output, *, session):
        events.append(('pair_18LO', str(output)))
        return write(Path(output)/'terminal.json', {'passed': True, 'source_manifest': session.source})
    source = SimpleNamespace(reference=reference, read=read, write=exclusive_write, recipes=lambda: {str(script): reference(script)['sha256']},
        prepare=source_prepare, execute_prepared=source_execute)
    pair = SimpleNamespace(__file__=str(script), POOL=script, quality=SimpleNamespace(DEFAULT_PROVIDERS=Path(provider['path'])),
        frozen_dependencies=lambda: None, _module=lambda path: SimpleNamespace(recipes=lambda: {}),
        PairSession=Session, prepare=pair_prepare, execute_prepared=pair_execute)
    monkeypatch.setattr(module, 'apis', lambda: (source, pair))
    return SimpleNamespace(module=module, output=tmp_path/'prepared', config=config, events=events, failure=failure,
        read=read, write=write, ref=reference, source=source, pair=pair)


def prepare(batch):
    return batch.module.prepare(batch.output, batch.config)


def test_prepare_freezes_all_profiles_before_eight_zero_service_source_preparations(batch):
    record = prepare(batch); cfg, rows, frozen = batch.module.validate(batch.output)
    assert record == batch.ref(batch.output/'prospective.json')
    assert [r['profile_id'] for r in rows] == batch.module.ORDER
    assert len(cfg['rejected_profiles_retained']) == 10 and len(frozen['source_preparations']) == 8
    assert batch.events == [('source_prepare', pid) for pid in batch.module.ORDER[2:]]
    assert all(frozen[key] == 0 for key in ('LO_calls', 'model_calls', 'solver_calls', 'Harbor_calls'))
    assert frozen['qualified'] is False and frozen['reuse_requires_genuine_cold_admission_at_run']
    assert not (batch.output/'started.json').exists()


@pytest.mark.parametrize('mutation', ['missing_profile', 'old240', 'reject_admitted', 'missing_mode', 'reference_changed'])
def test_inventory_refuses_scope_old_schema_and_reuse_substitutions(batch, mutation):
    cfg = batch.read(batch.config)
    if mutation == 'missing_profile': cfg['profile_order'].pop()
    elif mutation == 'missing_mode': cfg['reuse']['L360-P01']['mode_terminals'].pop('debugging')
    else:
        aggregate = batch.read(cfg['reference_batch']); row = aggregate['profiles'][0]
        worker = batch.read(row['worker_terminal']); proof = batch.read(worker['terminal'])
        if mutation == 'old240': proof['kind'] = 'linear_capital_independent_best_runner_reference'
        elif mutation == 'reject_admitted': row['passed'] = False
        else: proof['specification']['sha256'] = '0'*64
        worker['terminal'] = batch.write(worker['terminal']['path'], proof)
        row['worker_terminal'] = batch.write(row['worker_terminal']['path'], worker)
        cfg['reference_batch'] = batch.write(cfg['reference_batch']['path'], aggregate)
        audit = batch.read(cfg['reference_completed_audit']); audit['aggregate'] = cfg['reference_batch']
        cfg['reference_completed_audit'] = batch.write(cfg['reference_completed_audit']['path'], audit)
    batch.write(batch.config, cfg)
    with pytest.raises((ValueError, AssertionError)): prepare(batch)


def test_prepared_input_mutation_and_cross_profile_preparation_are_rejected(batch):
    prepare(batch); frozen = batch.read(batch.output/'prospective.json'); key = batch.module.ORDER[2]
    frozen['source_preparations'][key] = frozen['source_preparations'][batch.module.ORDER[3]]
    batch.write(batch.output/'prospective.json', frozen)
    with pytest.raises(ValueError, match='changed profile'): batch.module.validate(batch.output)


def test_reuse_requires_real_cold_source_and_both_view_calls_without_LO(batch):
    prepare(batch); batch.events.clear(); batch.write(batch.output/'started.json', {'dashboard_url': 'mock'})
    assert batch.module.worker(batch.output, 'L360-P01') == 0
    assert [e[0] for e in batch.events] == ['cold_source', 'cold_view', 'cold_view']
    terminal = batch.read(batch.output/'profiles/L360-P01/worker_terminal.json')
    assert terminal['passed'] and terminal['reused_without_LO'] and terminal['qualified'] is False
    with pytest.raises(FileExistsError): batch.module.worker(batch.output, 'L360-P01')


def test_cold_failure_preserved_and_no_reuse_recalculation_fallback(batch):
    prepare(batch); batch.events.clear(); batch.failure['cold'] = True
    batch.write(batch.output/'started.json', {'dashboard_url': 'mock'})
    assert batch.module.worker(batch.output, 'L360-P02') == 1
    terminal = batch.read(batch.output/'profiles/L360-P02/worker_terminal.json')
    assert terminal['error']['type'] == 'ValueError' and not terminal['stages'][-1]['passed']
    assert [e[0] for e in batch.events] == ['cold_source', 'cold_view']


def test_fresh_profile_uses_one_session_and_unchanged_source_then_pair_calls(batch):
    prepare(batch); batch.events.clear(); batch.write(batch.output/'started.json', {'dashboard_url': 'mock'})
    assert batch.module.worker(batch.output, 'L360-P07') == 0
    assert [e[0] for e in batch.events] == ['source_3LO', 'cold_source', 'pair_prepare', 'pair_18LO']
    terminal = batch.read(batch.output/'profiles/L360-P07/worker_terminal.json')
    assert len(terminal['stages']) == 4 and all(s['passed'] and s['elapsed_seconds'] >= 0 for s in terminal['stages'])


def test_multiple_stages_use_real_exclusive_upstream_writer_and_immutable_receipts(batch, monkeypatch):
    real_source = entry().apis()[0]
    monkeypatch.setattr(batch.source, 'write', real_source.write)
    prepare(batch); batch.write(batch.output/'started.json', {'dashboard_url': 'mock'})
    assert batch.module.worker(batch.output, 'L360-P07') == 0
    folder = batch.output/'profiles/L360-P07'; terminal = batch.read(folder/'worker_terminal.json')
    assert len(terminal['stages']) == 4
    assert len(list((folder/'stages').glob('*_started.json'))) == 4
    assert len(list((folder/'stages').glob('*_terminal.json'))) == 4
    assert not (folder/'phase.json').exists() and not (folder/'stages.json').exists()
    for stage in terminal['stages']:
        assert batch.read(stage['terminal'])['started'] == stage['started'] and stage['passed']
    assert terminal['passed'] and terminal['model_calls'] == terminal['solver_calls'] == 0


def test_failed_source_stops_only_case_and_retains_no_retry(batch):
    prepare(batch); batch.events.clear(); batch.failure['source'] = 'L360-P07'
    batch.write(batch.output/'started.json', {'dashboard_url': 'mock'})
    assert batch.module.worker(batch.output, 'L360-P07') == 1
    assert batch.events == [('source_3LO', 'L360-P07')]
    assert not batch.read(batch.output/'profiles/L360-P07/worker_terminal.json')['passed']
    with pytest.raises(FileExistsError): batch.module.worker(batch.output, 'L360-P07')


def test_parent_dashboard_precedes_two_isolated_children_all_failures_retained(batch, monkeypatch):
    from sheets_factory import dashboard
    prepare(batch); launches = []; active = set(); maximum = [0]
    class Panel:
        def __init__(self, *a, **kw): pass
        def start(self): return 'http://mock-total-dashboard'
        def stop(self): pass
    class Process:
        def __init__(self, command, **kw):
            assert batch.read(batch.output/'started.json')['dashboard_url'] == 'http://mock-total-dashboard'
            self.profile = command[-1]; self.pid = len(launches)+100; self.returncode = None
            launches.append(command); active.add(self.profile); maximum[0] = max(maximum[0], len(active))
        def poll(self):
            if self.returncode is None:
                self.returncode = 1 if self.profile == 'L360-P07' else 0
                batch.write(batch.output/'profiles'/self.profile/'worker_terminal.json', {'passed': self.returncode == 0})
                active.remove(self.profile)
            return self.returncode
        def wait(self): return self.poll()
    monkeypatch.setattr(dashboard, 'DashboardServer', Panel)
    monkeypatch.setattr(batch.module.subprocess, 'Popen', Process)
    monkeypatch.setattr(batch.module.time, 'sleep', lambda seconds: None)
    terminal = batch.read(batch.module.execute(batch.output))
    assert maximum[0] == 2 and [c[-1] for c in launches] == batch.module.ORDER
    assert all(c[1].endswith('prepare_linear_capital_scaled_engineering_batch.py') and '--worker' in c for c in launches)
    assert len(terminal['profiles']) == 10 and not terminal['passed'] and terminal['retries'] == 0
    assert [r['profile_id'] for r in terminal['profiles'] if not r['passed']] == ['L360-P07']
    with pytest.raises(ValueError, match='first execution'): batch.module.execute(batch.output)


def test_cli_requires_separate_preparation_and_run(batch):
    with pytest.raises(ValueError, match='Prepare first'):
        batch.module.main(['--output', str(batch.output), '--run'])
