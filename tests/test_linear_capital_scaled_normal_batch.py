"""No services: fixed inventory, one-process admissions, and external concurrency."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


@pytest.fixture
def module():
    path = Path(__file__).resolve().parents[1]/'scripts/prepare_linear_capital_scaled_normal_batch.py'
    definition = importlib.util.spec_from_file_location('_test_scaled_normal_batch', path)
    value = importlib.util.module_from_spec(definition); definition.loader.exec_module(value)
    return value


@pytest.fixture
def contract(module, tmp_path, monkeypatch):
    m = module; root = tmp_path/'engineering'; root.mkdir()
    configuration = tmp_path/'normal.yaml'
    configuration.write_text(yaml.safe_dump({'diagnosis': {'selection': {'include': [f'Q{i:02d}' for i in range(1, 13)], 'exclude': []},
        'reference_evidence_policy': 'reference_review'}, 'agents': {'model': 'gpt-6-sol', 'reasoning_effort': 'high'}}))
    dependency = tmp_path/'dependency.py'; dependency.write_text('# frozen\n')
    provider = tmp_path/'providers.json'; provider.write_text('{}\n')
    dummy_entry = tmp_path/'normal_entry.py'; dummy_entry.write_text('# mock boundary\n')
    rows = [{'profile_id': pid, 'reference': {'profile': pid}, 'specification': {'raw': pid}}
            for pid in m.ORDER]
    setup = m.write(root/'setup.json', {'profiles': rows, 'recipe': {str(dependency): m.ref(dependency)['sha256']}})
    engineering = m.write(root/'prospective.json', {'kind': 'fixed_scaled_pass10_source_and_engineering_pair_batch', 'version': 1, 'setup': setup})
    p01 = tmp_path/'existing_P01'; p01.mkdir()
    preflight = m.write(p01/'preflight_manifest.json', {'kind': 'prepared_complete_native_linear_capital_scaled_reference_quality',
        'version': 2, 'count': 2, 'targets': dict.fromkeys(m.MODES, 1), 'configuration_input': m.ref(configuration)})
    cfg = {'kind': m.KIND, 'version': 1, 'engineering_prospective': engineering,
        'profile_order': m.ORDER, 'mode_order': m.MODES, 'source_provider': 'scaled360',
        'normal_entry': m.ref(dummy_entry), 'normal_configuration': m.ref(configuration),
        'max_parallel_profiles': 2, 'outer_retries': 0, 'external_P01': {'profile_id': m.ORDER[0],
            'prepared_directory': str(p01), 'preflight': preflight, 'pid': 987654321,
            'process_start_ticks': '1', 'monitor_only': True},
        'all_twelve_checks_required': [f'Q{i:02d}' for i in range(1, 13)],
        'reference_evidence_policy': 'reference_review', 'engineering_or_prior_quality_inherited': False}
    config = tmp_path/'configuration.json'; m.write(config, cfg); monkeypatch.setattr(m, 'DEFAULT', config)
    normal = SimpleNamespace(yaml=yaml, pipeline=SimpleNamespace(DEFAULT_PROVIDERS=provider), recipes=lambda config, admissions: {})
    monkeypatch.setattr(m, 'entry', lambda c: normal)
    return cfg, config, root, rows, normal


def install_case(m, cfg, row, *, passed=True, source_kind='independently_verified_linear_capital_scaled_native_source', modes=None):
    folder = Path(row['engineering_worker_path']).parent
    prep = m.write(folder/'source_preparation.json', {'original_specification': row['specification']})
    source = m.write(folder/'source.json', {'kind': source_kind, 'source_preparation': prep,
        'independent_reference': row['reference']})
    terminals = {}
    for mode in (m.MODES if modes is None else modes):
        terminals[mode] = m.write(folder/(mode+'.json'), {'mode': mode, 'passed': True, 'source_admission': source})
    pair = m.write(folder/'pair.json', {'kind': 'linear_capital_scaled_cached_pool_view_pair_actual_validation',
        'version': 2, 'passed': True, 'profile_id': row['profile_id'], 'source_provider': 'scaled360',
        'source_manifest': source, 'validation_terminals': terminals, 'LO_call_count_exact': 18})
    return m.write(row['engineering_worker_path'], {'profile_id': row['profile_id'], 'passed': passed,
        'prospective': cfg['engineering_prospective'], 'records': {'source_manifest': source, 'pair_terminal': pair}})


def test_prepare_freezes_all_ten_without_admissions_or_services(module, contract, tmp_path):
    m = module; cfg, config, _, _, normal = contract
    normal.prepare_many = lambda *a, **k: pytest.fail('No cold admission at batch preparation')
    normal.execute_prepared = lambda *a, **k: pytest.fail('No services at batch preparation')
    output = tmp_path/'batch'; prospective = m.prepare(output, config)
    value = m.read(prospective)
    assert [r['profile_id'] for r in value['profiles']] == m.ORDER
    assert value['actual_models'] == value['actual_LO_calls'] == value['actual_Harbor_jobs'] == 0
    assert value['qualified'] is False
    assert value['actual_input_references_bound_only_after_engineering_completion'] is True
    assert m.validate(output)[0] == cfg
    assert not any(p.name == 'normal' for p in output.rglob('*'))


@pytest.mark.parametrize('change', ['order', 'concurrency', 'retry', 'old_provider', 'missing_Q12', 'policy', 'P01_restart'])
def test_fixed_scope_cannot_be_relaxed(module, contract, tmp_path, change):
    m = module; cfg, config, _, _, _ = contract; altered = deepcopy(cfg)
    if change == 'order': altered['profile_order'] = altered['profile_order'][:-1]
    elif change == 'concurrency': altered['max_parallel_profiles'] = 3
    elif change == 'retry': altered['outer_retries'] = 1
    elif change == 'old_provider': altered['source_provider'] = 'standard'
    elif change == 'missing_Q12': altered['all_twelve_checks_required'].pop()
    elif change == 'policy': altered['reference_evidence_policy'] = 'witness_only'
    elif change == 'P01_restart': altered['external_P01']['monitor_only'] = False
    config.write_text(json.dumps(altered))
    with pytest.raises(ValueError): m.prepare(tmp_path/'bad', config)


def test_frozen_recipe_mutation_rejected(module, contract, tmp_path):
    m = module; _, config, _, _, _ = contract; output = tmp_path/'batch'; m.prepare(output, config)
    (tmp_path/'dependency.py').write_text('# changed\n')
    with pytest.raises(ValueError, match='dependency changed'): m.validate(output)


def test_waits_for_missing_or_partial_terminal_then_binds_both_modes(module, contract, tmp_path):
    m = module; cfg, config, _, _, _ = contract; output = tmp_path/'batch'; m.prepare(output, config)
    row = m.validate(output)[1][1]
    assert m.completed_inputs(cfg, row) is None
    path = Path(row['engineering_worker_path']); path.parent.mkdir(parents=True); path.write_text('{"passed":')
    assert m.completed_inputs(cfg, row) is None
    path.unlink(); worker = install_case(m, cfg, row)
    inputs = m.completed_inputs(cfg, row)
    assert inputs['engineering_worker'] == worker
    assert [m.read(s['validation_terminal'])['mode'] for s in inputs['selections']] == m.MODES
    assert all(s['source_provider'] == 'scaled360' for s in inputs['selections'])


@pytest.mark.parametrize('failure', ['engineering_failed', 'old_source', 'one_mode'])
def test_completed_labels_do_not_admit_failed_old_or_incomplete_material(module, contract, tmp_path, failure):
    m = module; cfg, config, _, _, _ = contract; output = tmp_path/'batch'; m.prepare(output, config)
    row = m.validate(output)[1][1]
    install_case(m, cfg, row, passed=failure != 'engineering_failed',
        source_kind='old_240_source' if failure == 'old_source' else 'independently_verified_linear_capital_scaled_native_source',
        modes=m.MODES[:1] if failure == 'one_mode' else None)
    with pytest.raises(ValueError): m.completed_inputs(cfg, row)


def test_worker_keeps_one_opaque_session_and_immutable_two_stage_receipts(module, contract, tmp_path):
    m = module; cfg, config, _, _, normal = contract; output = tmp_path/'batch'; m.prepare(output, config)
    m.write(output/'started.json', {'dashboard_url': 'mock://already_started'})
    row = m.validate(output)[1][1]; install_case(m, cfg, row); calls = []; credential = object(); sessions = {}
    def prepare(selections, destination):
        assert len(selections) == 2 and not sessions
        calls.append(('prepare', id(normal))); sessions[str(destination)] = credential
        return m.write(Path(destination)/'preflight_manifest.json', {'same_process': True})
    def execute(destination):
        assert sessions[str(destination)] is credential
        calls.append(('execute', id(normal)))
        m.write(Path(destination)/'summary.json', {'run': {'finished_at': 'now', 'producer_active': False, 'exit_code': 0}})
        return 0
    normal.prepare_many = prepare; normal.execute_prepared = execute
    assert m.worker(output, row['profile_id']) == 0
    assert calls == [('prepare', id(normal)), ('execute', id(normal))]
    folder = output/'profiles'/row['profile_id']
    assert len(list((folder/'stages').glob('*_started.json'))) == 2
    assert len(list((folder/'stages').glob('*_terminal.json'))) == 2
    actual = m.read(folder/'actual_inputs.json'); assert len(actual['selections']) == 2 and actual['normal_recipe']
    terminal = m.read(folder/'worker_terminal.json')
    assert terminal['passed'] is True and terminal['qualified'] is False and terminal['prior_quality_inherited'] is False
    with pytest.raises(FileExistsError): m.worker(output, row['profile_id'])


def test_worker_retains_cold_failure_and_does_not_execute(module, contract, tmp_path):
    m = module; cfg, config, _, _, normal = contract; output = tmp_path/'batch'; m.prepare(output, config)
    m.write(output/'started.json', {}); row = m.validate(output)[1][1]; install_case(m, cfg, row)
    def fail(*args): raise ValueError('genuine cold admission failed')
    normal.prepare_many = fail; normal.execute_prepared = lambda *a: pytest.fail('Failed admission cannot start services')
    assert m.worker(output, row['profile_id']) == 1
    terminal = m.read(output/'profiles'/row['profile_id']/'worker_terminal.json')
    assert terminal['passed'] is False and 'genuine cold' in terminal['error']['error']
    assert terminal['records']['actual_inputs']


def test_P01_is_never_a_worker_and_monitor_only_reads_files(module, contract, tmp_path):
    m = module; cfg, config, _, _, normal = contract; output = tmp_path/'batch'; m.prepare(output, config)
    m.write(output/'started.json', {})
    normal.prepare_many = lambda *a: pytest.fail('Never rerun P01')
    with pytest.raises(ValueError, match='monitor-only'): m.worker(output, m.ORDER[0])
    p01 = Path(cfg['external_P01']['prepared_directory']); sqlite = p01/'run.sqlite'; sqlite.write_bytes(b'untouched')
    summary = m.write(p01/'summary.json', {'run': {'finished_at': 'now', 'producer_active': False, 'exit_code': 2}})
    before = {p: p.read_bytes() for p in p01.iterdir()}
    value, live = m.external_state(cfg)
    assert live is None and value['monitor_only'] is True and value['passed'] is False
    assert value['normal_summary'] == summary
    assert {p: p.read_bytes() for p in p01.iterdir()} == before


def test_parent_dashboard_precedes_waiting_and_external_P01_occupies_one_slot(module, contract, tmp_path, monkeypatch):
    m = module; cfg, config, _, _, _ = contract; output = tmp_path/'batch'; m.prepare(output, config)
    from sheets_factory.core.audit import AuditStore
    from sheets_factory.dashboard import DashboardServer
    class FakeServer:
        def __init__(self, *a, **k): pass
        def start(self): return 'mock://total-ui'
        def stop(self): pass
    monkeypatch.setattr('sheets_factory.dashboard.DashboardServer', FakeServer)
    monkeypatch.setattr(m, 'external_state', lambda cfg: (None, {'stage': 'original P01 active'}))
    calls = []
    def ready(cfg, row):
        assert m.read(output/'started.json')['dashboard_url'] == 'mock://total-ui'
        calls.append(row['profile_id']); return {'ready': True}
    monkeypatch.setattr(m, 'completed_inputs', ready)
    class FakeProcess:
        pid = 12345; returncode = None
        def poll(self): return None
        def wait(self): self.returncode = 1; return 1
    launched = []
    def launch(command, **kwargs): launched.append(command); return FakeProcess()
    monkeypatch.setattr(m.subprocess, 'Popen', launch)
    class StopAfterFirstLoop(Exception): pass
    monkeypatch.setattr(m.time, 'sleep', lambda seconds: (_ for _ in ()).throw(StopAfterFirstLoop()))
    with pytest.raises(StopAfterFirstLoop): m.execute(output)
    assert len(launched) == 1 and launched[0][-1] == m.ORDER[1]
    assert calls == [m.ORDER[1]]
    assert m.read(output/'orchestration_failure.json')['active_owned_pids'] == {m.ORDER[1]: 12345}
    assert not (Path(cfg['external_P01']['prepared_directory'])/'run.sqlite').exists()


def test_total_snapshot_reads_real_databases_deduplicates_calls_and_retains_unknowns(module, contract, tmp_path):
    from sheets_factory.core.audit import AuditStore
    m = module; cfg, config, _, _, _ = contract; output = tmp_path/'batch'; m.prepare(output, config)
    rows = m.validate(output)[1]; runs = [Path(cfg['external_P01']['prepared_directory']), Path(rows[1]['normal_directory'])]
    children = []
    for directory in runs:
        child = AuditStore(directory, {'id': directory.name, 'status': 'running', 'producer_active': True})
        child.task('same-task', mode='financial_modeling', status='qualified', source_id=str(directory))
        # Identical call ID in two runs must count twice; duplicate records within one run once.
        for _ in range(2): child.record('calls', {'call_id': 'same-call', 'stage': 'Diagnose',
            'input_tokens': 100, 'output_tokens': 20, 'cached_input_tokens': 80, 'reasoning_tokens': 15, 'status': 'completed'})
        child.emit('llm.started', call_id='pending', stage='Trajectory', started_at='2026-10-31T18:00:00+00:00')
        child.record('nodes', {'node': 'Diagnose', 'status': 'completed', 'duration_ms': 1500})
        children.append(child)
    parent = AuditStore(output/'audit', {'id': 'parent', 'target_count': 20})
    before = {directory: (directory/'run.sqlite').read_bytes() for directory in runs}
    try:
        for _ in range(2):
            result = m.aggregate_snapshot(parent.snapshot(), cfg, rows)
            assert result['metrics']['input_tokens'] == 200
            assert result['metrics']['output_tokens'] == 40
            assert result['metrics']['total_tokens'] == 240  # Cached/reasoning subsets are never added.
            assert result['metrics']['cached_input_tokens'] == 160
            assert result['metrics']['llm_calls'] == 4
            assert result['metrics']['unknown_usage_calls'] == result['metrics']['active_llm_calls'] == 2
            assert len(result['tasks']) == result['metrics']['qualified'] == 2
            assert len(result['node_attempts']) == 2
            assert result['metrics']['cumulative_node_seconds'] == 3
            assert result['run']['target_count'] == 20
            assert result['run']['formal_release_inferred'] is False
            assert result['viewer']['counts_scope'] == 'normal_quality_only'
            assert len({c['call_id'] for c in result['llm_calls']}) == 4
        assert {directory: (directory/'run.sqlite').read_bytes() for directory in runs} == before
    finally:
        parent.db.close()
        for child in children: child.db.close()


def test_unavailable_child_audit_is_unknown_not_a_zero_usage_claim(module, contract, tmp_path):
    from sheets_factory.core.audit import AuditStore
    m = module; cfg, config, _, _, _ = contract; output = tmp_path/'batch'; m.prepare(output, config)
    rows = m.validate(output)[1]
    # A new or damaged database can exist before its schema is readable.
    (Path(cfg['external_P01']['prepared_directory'])/'run.sqlite').write_bytes(b'incomplete database')
    parent = AuditStore(output/'audit', {'id': 'parent'})
    try:
        result = m.aggregate_snapshot(parent.snapshot(), cfg, rows)
        assert result['metrics']['total_tokens'] is None
        assert result['metrics']['input_tokens'] is None and result['metrics']['output_tokens'] is None
        assert result['metrics']['unavailable_child_audits'] == 1
        assert result['metrics']['usage_completeness'] == 'known_lower_bound_with_unknowns'
        assert 'usage census incomplete' in result['run']['name']
    finally: parent.db.close()
