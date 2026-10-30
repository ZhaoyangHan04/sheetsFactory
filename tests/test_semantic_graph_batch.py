"""Batch admission tests use explicit schema fixtures, never financial sources."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    '_semantic_graph_batch_tests', ROOT / 'scripts/prepare_semantic_graph_batch.py')
entry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(entry)


def document(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False))
    return entry.ref(path)


@pytest.fixture
def foundation(tmp_path, monkeypatch):
    """No fixture workbook can pass the real financial/engineering validators."""
    policy_path = ROOT / 'config/task_adapters/composite_semantic_graph_v3.json'
    policy = json.loads(policy_path.read_text())
    fixed_code = tmp_path / 'fixture_batch_recipe.py'
    fixed_code.write_text('# schema-only unit fixture, not a source adapter\n')
    monkeypatch.setattr(entry, 'recipe_files', lambda: {str(fixed_code): entry.sha(fixed_code)})
    scope_validations = []

    def scope_validator(scope, edits):
        assert scope['unit_fixture_only'] is True
        assert len(edits) == scope['prospective_nonzero_roots'] == 1
        scope_validations.append(edits)

    monkeypatch.setattr(entry, 'validate_scope_inventory', scope_validator)
    sources, profiles, handoffs, results = [], [], [], []
    for profile in entry.ORDER:
        directory = tmp_path / 'originals' / profile
        directory.mkdir(parents=True)
        original, presented = directory / 'original.xlsx', directory / 'presented.xlsx'
        original.write_bytes(('unit fixture original:' + profile).encode())
        presented.write_bytes(('unit fixture presented:' + profile).encode())
        original_manifest = document(directory / 'original_manifest.json', {'unit_fixture_only': True})
        public_scenarios = document(directory / 'public_scenarios.json', {'unit_fixture_only': True})
        source_manifest = document(directory / 'source_manifest.json', {
            'unit_fixture_only': True, 'public_scenarios': public_scenarios})
        dummy_audit = document(directory / 'dummy_audit.json', {'unit_fixture_only': True})
        financial = document(directory / 'financial.json', {'unit_fixture_only': True,
            'source': entry.ref(presented), 'original_source': entry.ref(original),
            'original_manifest': original_manifest, 'actual_stability': dummy_audit,
            'original_independent_audits': {'fixture_only': dummy_audit},
            'financial_validation_method': 'unit_fixture_not_a_financial_audit'})
        scope = document(directory / 'scope.json', {'unit_fixture_only': True,
            'prospective_nonzero_roots': 1, 'family_count': 879})
        timing = document(directory / 'timing.json', {'unit_fixture_only': True})
        binding = {'source': entry.ref(presented), 'source_manifest': source_manifest,
            'scope_inventory': scope, 'financial_admission': financial,
            'public_input_priority_audit': timing}
        handoff = document(directory / 'handoff.json', {'unit_fixture_only': True,
            'source_binding': binding})
        edits = [{'sheet': 'UNIT_FIXTURE_ONLY', 'cell': 'C1', 'before': '=1', 'after': '=2'}]
        report = {'unit_fixture_only': True, 'offline_compile_complete': True,
            'adapter': entry.PROVIDER_ID, 'source': binding['source'], 'policy': policy,
            'scope_inventory_sha256': entry.canonical(json.loads(Path(scope['path']).read_text())),
            'root_count': 1, 'compiled_root_count': 1, 'unsatisfied_roots': [],
            'family_count': 879, 'edits': edits, 'edits_sha256': entry.canonical(edits),
            'mutation_provider_recipe': {'mutation_provider': {
                **entry.ref(entry.PROVIDER), 'bytes': entry.PROVIDER.stat().st_size}}}
        report_ref = document(directory / 'compilation.json', report)
        result = {'profile_id': profile, 'offline_compile_complete': True, 'root_count': 1,
            'compiled_root_count': 1, 'unsatisfied_root_count': 0, 'family_count': 879,
            'edits_sha256': entry.canonical(edits), 'compilation': report_ref}
        sources.append({'profile_id': profile, **binding})
        profiles.append({'profile_id': profile, 'original_source': entry.ref(original)})
        handoffs.append({'profile_id': profile, 'handoff': handoff})
        results.append(result)
    source_batch = document(tmp_path / 'source_batch.json', {
        'status': 'source_foundation_batch_complete', 'original_order': list(entry.ORDER),
        'source_failures': [], 'certified_sources': handoffs, 'profiles': profiles})
    index = document(tmp_path / 'source_index.json', {
        'kind': 'source_foundation_bindings_only_no_question_admission',
        'original_order': list(entry.ORDER), 'source_original_ancestors': 2,
        'derived_presentation_source_count': 10, 'source_bindings': sources,
        'batch_manifest': source_batch})
    offline = document(tmp_path / 'offline_batch.json', {
        'kind': 'offline_v3_complete_scope_compile_batch', 'all_complete': True,
        'original_order': ['PRIMARY', *entry.ORDER], 'policy': policy,
        'results': [{'profile_id': 'PRIMARY', 'unit_fixture_only': True}, *results]})
    return SimpleNamespace(index=Path(index['path']), offline=Path(offline['path']),
        policy=policy_path, validations=scope_validations, fixed_code=fixed_code)


def prepare_fixture(tmp_path, foundation):
    output = tmp_path / 'batch'
    entry.prepare(output, foundation.index, foundation.offline, foundation.policy)
    return output


class FixtureAudit:
    def __init__(self, *args, **kwargs):
        self.snapshot = lambda: {}
        self.events = lambda: []
        self.emitted = []

    def update_run(self, **kwargs):
        pass

    def emit(self, kind, **payload):
        self.emitted.append((kind, payload))

    def export(self):
        pass


class FixturePanel:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        return 'http://fixture-only.invalid/'

    def stop(self):
        pass


@pytest.fixture
def worker(monkeypatch):
    """A fake subprocess tests orchestration only; it executes no LO or model."""
    calls = []
    failed = set()
    admissions = []
    monkeypatch.setattr(entry, 'AuditStore', FixtureAudit)
    monkeypatch.setattr(entry, 'DashboardServer', FixturePanel)

    def run(command, **kwargs):
        assert command[1] == str(entry.WORKER)
        arguments = dict(zip(command[2::2], command[3::2]))
        output = Path(arguments['--output'])
        profile = output.parent.name
        assert kwargs['env']['TMPDIR'] == str(output / 'temporary')
        assert kwargs['check'] is False
        calls.append({'profile_id': profile, 'command': command, 'environment': kwargs['env']})
        output.mkdir()
        (output / 'temporary').mkdir()
        if profile in failed:
            document(output / 'failure_receipt.json', {'unit_fixture_only': True, 'failed': True})
            document(output / 'engine_calls.json', [])
            return SimpleNamespace(returncode=2)
        report_path = Path(arguments['--offline-report'])
        report = json.loads(report_path.read_text())
        policy_path = Path(arguments['--policy'])
        provider = {'id': entry.PROVIDER_ID, 'implementation': entry.ref(entry.PROVIDER),
            'policy': {**entry.ref(policy_path), 'bytes': policy_path.stat().st_size},
            'policy_sha256': entry.canonical(json.loads(policy_path.read_text())),
            'offline_compilation': entry.ref(report_path)}
        document(output / 'recipe_start.json', {'fixture_only': entry.ref(entry.PROVIDER)})
        document(output / 'plan.json', {'edits': report['edits']})
        (output / 'input.xlsx').write_bytes(('unit fixture input:' + profile).encode())
        (output / 'second_pass.xlsx').write_bytes(('unit fixture input:' + profile).encode())
        document(output / 'engine_calls.json', [
            {'phase': 'mutant_normalize', 'completed': True, 'duration_seconds': 1},
            {'phase': 'mutant_second_recalculation', 'completed': True, 'duration_seconds': 2}])
        document(output / 'engineering_receipt.json', {'unit_fixture_only': True,
            'mutation_provider': provider, 'actual_LO_recalculations': 2})
        return SimpleNamespace(returncode=0)

    def validate_seed(seed, setting):
        # This deliberately cannot be used outside this monkeypatched fixture.
        assert seed['profile_id'] in entry.ORDER
        assert seed['source_kind'] == entry.SOURCE_KIND
        assert entry.read(setting['bindings'])['sources'][seed['sha256']] == seed['semantic_graph_binding']
        assert len(json.loads((Path(seed['engineering_probe']['path']).parent / 'engine_calls.json').read_text())) == 2
        admissions.append(seed['profile_id'])
        return {'unit_fixture_only': True, 'workbook': seed['semantic_graph_binding']['source']}

    monkeypatch.setattr(entry.subprocess, 'run', run)
    monkeypatch.setattr(entry, 'validate_seed', validate_seed)
    return SimpleNamespace(calls=calls, failed=failed, admissions=admissions)


def test_prepare_freezes_all_ten_without_processes_or_engines(tmp_path, foundation, monkeypatch):
    monkeypatch.setattr(entry.subprocess, 'run', lambda *a, **k: pytest.fail('preparation dispatched a child'))
    before = {p: p.read_bytes() for p in (tmp_path / 'originals').rglob('*') if p.is_file()}
    output = prepare_fixture(tmp_path, foundation)
    frozen = entry.validate_prepared(output)
    assert frozen['profile_order'] == list(entry.ORDER)
    assert len(frozen['cases']) == len(foundation.validations) == 10
    assert frozen['actual_LO_calls'] == frozen['actual_model_calls'] == 0
    assert frozen['planned_actual_LO_calls'] == 20
    assert frozen['source_original_ancestors'] == 2
    assert frozen['derived_presentation_source_count'] == 10
    assert not (output / 'run.sqlite').exists()
    assert not (output / 'cases').exists()
    assert all(p.read_bytes() == contents for p, contents in before.items())
    assert not any(case['profile_id'] == 'PRIMARY' for case in frozen['cases'])


@pytest.mark.parametrize('problem', ['reverse', 'missing', 'duplicate', 'source_sha', 'policy', 'partial_report', 'scope'])
def test_prepare_rejects_source_or_scope_substitution(tmp_path, foundation, problem):
    index = json.loads(foundation.index.read_text())
    offline = json.loads(foundation.offline.read_text())
    if problem == 'reverse':
        index['source_bindings'].reverse()
    elif problem == 'missing':
        index['source_bindings'].pop()
    elif problem == 'duplicate':
        index['source_bindings'][1] = deepcopy(index['source_bindings'][0])
    elif problem == 'source_sha':
        index['source_bindings'][0]['source']['sha256'] = '0' * 64
    else:
        result = offline['results'][1]
        path = Path(result['compilation']['path'])
        report = json.loads(path.read_text())
        if problem == 'policy':
            report['policy']['seed'] += 1
        elif problem == 'partial_report':
            report['edits'] = []
            report['edits_sha256'] = entry.canonical([])
        elif problem == 'scope':
            report['scope_inventory_sha256'] = '0' * 64
        document(path, report)
        result['compilation'] = entry.ref(path)
        result['edits_sha256'] = report['edits_sha256']
    document(foundation.index, index)
    document(foundation.offline, offline)
    with pytest.raises(ValueError):
        prepare_fixture(tmp_path, foundation)
    assert not (tmp_path / 'batch').exists()


@pytest.mark.parametrize('workers', [0, 3, True, 1.5])
def test_worker_limit_rejects_non_integer_and_over_parallel_execution(tmp_path, foundation, workers):
    with pytest.raises(ValueError, match='workers must be 1 or 2'):
        entry.prepare(tmp_path / 'bad', foundation.index, foundation.offline, foundation.policy, workers=workers)


def test_completed_pool_keeps_all_ten_order_ancestry_and_separate_provider(tmp_path, foundation, worker):
    output = prepare_fixture(tmp_path, foundation)
    result_ref = entry.execute_prepared(output)
    result = entry.validate_completed(output)
    assert result_ref == entry.ref(output / 'batch_manifest.json')
    assert result['kind'] == entry.POOL_KIND and result['status'] == 'completed'
    assert len(worker.calls) == 10
    assert len({call['environment']['TMPDIR'] for call in worker.calls}) == 10
    assert sorted(worker.admissions) == sorted(list(entry.ORDER) * 2)
    manifest = entry.read(result['seed_manifest'])
    assert [seed['profile_id'] for seed in manifest['selected']] == list(entry.ORDER)
    assert [seed['original_source']['sha256'] for seed in manifest['selected']] == result['original_source_order']
    assert [seed['sha256'] for seed in manifest['selected']] == result['presented_source_order']
    assert result['attempted_actual_LO_calls'] == result['completed_actual_LO_calls'] == 20
    assert result['known_completed_LO_duration_seconds'] == 30
    assert result['source_original_ancestors'] == 2
    assert result['derived_presentation_source_count'] == 10
    assert result['qualified'] is False and result['task_count'] == 0
    for seed in manifest['selected']:
        assert seed.get('task_adapter') is None
        assert seed['semantic_graph_binding']['source_presentation_adapter'] == entry.SOURCE_ADAPTER
        assert seed['mutation_provider']['id'] == entry.PROVIDER_ID
        assert seed['finance_evidence']['audited_source_binding']['unit_fixture_only'] is True
    with pytest.raises(ValueError, match='already started'):
        entry.execute_prepared(output)


def test_one_failed_worker_keeps_failure_and_admits_no_nine_source_subset(tmp_path, foundation, worker):
    output = prepare_fixture(tmp_path, foundation)
    worker.failed.add(entry.ORDER[2])
    with pytest.raises(ValueError, match='no partial pool'):
        entry.execute_prepared(output)
    result = entry.read(entry.ref(output / 'batch_manifest.json'))
    assert result['status'] == 'failed'
    assert entry.read(result['seed_manifest'])['selected'] == []
    assert len(result['worker_records']) == len(worker.calls) == 10
    assert sum(record['completed'] for record in result['worker_records']) == 9
    assert result['attempted_actual_LO_calls'] == 18
    assert result['completed_actual_LO_calls'] == 18
    assert not worker.admissions
    failed = Path(entry.validate_prepared(output)['cases'][2]['case_directory'])
    assert (failed / 'failure_receipt.json').exists()
    assert (failed.parent / 'worker_terminal.json').exists()
    with pytest.raises(ValueError, match='complete fixed-ten'):
        entry.validate_completed(output)


def test_execution_enforces_two_independent_child_process_slots(tmp_path, foundation, worker, monkeypatch):
    output = prepare_fixture(tmp_path, foundation)
    original_run = entry.subprocess.run
    lock = threading.Lock()
    counts = {'active': 0, 'maximum': 0}

    def overlapping_child(*args, **kwargs):
        with lock:
            counts['active'] += 1
            counts['maximum'] = max(counts['maximum'], counts['active'])
        try:
            time.sleep(0.02)
            return original_run(*args, **kwargs)
        finally:
            with lock:
                counts['active'] -= 1

    monkeypatch.setattr(entry.subprocess, 'run', overlapping_child)
    entry.execute_prepared(output)
    assert counts == {'active': 0, 'maximum': 2}
    assert len(worker.calls) == 10


def test_financial_or_engineering_admission_failure_does_not_create_selected_pool(tmp_path, foundation, worker, monkeypatch):
    output = prepare_fixture(tmp_path, foundation)
    monkeypatch.setattr(entry, 'validate_seed', lambda *a, **k: (_ for _ in ()).throw(ValueError('missing real proof')))
    with pytest.raises(ValueError, match='no partial pool'):
        entry.execute_prepared(output)
    result = entry.read(entry.ref(output / 'batch_manifest.json'))
    assert entry.read(result['seed_manifest'])['selected'] == []
    assert entry.read(result['failure'])['reason'] == 'missing real proof'
    assert len(worker.calls) == 10


def test_missing_or_malformed_engine_records_stay_unknown_in_failure_accounting(tmp_path, foundation, worker, monkeypatch):
    output = prepare_fixture(tmp_path, foundation)
    original = entry.subprocess.run

    def malformed(*args, **kwargs):
        result = original(*args, **kwargs)
        command = args[0]
        directory = Path(command[command.index('--output') + 1])
        if directory.parent.name == entry.ORDER[0]:
            (directory / 'engine_calls.json').write_text('not JSON')
        return result

    monkeypatch.setattr(entry.subprocess, 'run', malformed)
    with pytest.raises(ValueError, match='no partial pool'):
        entry.execute_prepared(output)
    result = entry.read(entry.ref(output / 'batch_manifest.json'))
    assert result['attempted_actual_LO_calls'] is None
    assert result['known_attempted_actual_LO_calls'] == 18
    assert result['engine_call_record_unknown_profiles'] == [entry.ORDER[0]]
    assert entry.read(result['seed_manifest'])['selected'] == []


@pytest.mark.parametrize('changed', ['source', 'recipe', 'case_path', 'order', 'count'])
def test_prepared_batch_rejects_changes_before_any_dispatch(tmp_path, foundation, worker, changed):
    output = prepare_fixture(tmp_path, foundation)
    frozen_path = output / 'frozen_inventory.json'
    frozen = json.loads(frozen_path.read_text())
    if changed == 'source':
        Path(frozen['cases'][0]['source_binding']['source']['path']).write_bytes(b'changed')
    elif changed == 'recipe':
        foundation.fixed_code.write_text('# changed\n')
    elif changed == 'case_path':
        frozen['cases'][0]['case_directory'] = str(tmp_path / 'elsewhere')
    elif changed == 'order':
        frozen['cases'].reverse()
    else:
        frozen['count'] = 9
    document(frozen_path, frozen)
    with pytest.raises(ValueError):
        entry.execute_prepared(output)
    assert not worker.calls


@pytest.mark.parametrize('changed', ['subset', 'worker', 'provider', 'ancestry', 'proof', 'quality_claim'])
def test_completed_pool_fails_closed_on_missing_or_changed_evidence(tmp_path, foundation, worker, changed):
    output = prepare_fixture(tmp_path, foundation)
    entry.execute_prepared(output)
    result_path = output / 'batch_manifest.json'
    result = json.loads(result_path.read_text())
    manifest_path = Path(result['seed_manifest']['path'])
    manifest = json.loads(manifest_path.read_text())
    if changed == 'subset':
        manifest['selected'].pop()
    elif changed == 'worker':
        result['worker_records'][0]['completed'] = False
    elif changed == 'provider':
        manifest['selected'][0]['mutation_provider']['id'] = entry.SOURCE_ADAPTER
    elif changed == 'ancestry':
        manifest['selected'][0]['original_source'] = manifest['selected'][1]['original_source']
    elif changed == 'proof':
        manifest['selected'][0]['finance_evidence']['audited_source_binding'] = {'missing': True}
    else:
        result['normal_construct_five_controls_recovery_12QA_Harbor_required'] = False
    document(manifest_path, manifest)
    result['seed_manifest'] = entry.ref(manifest_path)
    document(result_path, result)
    with pytest.raises(ValueError):
        entry.validate_completed(output)


def test_default_cli_prepares_only_and_execution_is_explicit(tmp_path, foundation, monkeypatch):
    monkeypatch.setattr(entry, 'execute_prepared', lambda *a, **k: pytest.fail('implicit execution'))
    output = tmp_path / 'cli'
    entry.main(['--output', str(output), '--source-foundation-index', str(foundation.index),
        '--offline-batch-manifest', str(foundation.offline), '--policy', str(foundation.policy)])
    assert (output / 'frozen_inventory.json').exists()
    with pytest.raises(SystemExit) as error:
        entry.main(['--prepared', str(output), '--run', '--validate-completed'])
    assert error.value.code == 2


def test_production_entry_imports_the_existing_strict_admission_and_worker():
    assert entry.validate_seed.__module__ == 'sheets_factory.pipelines.semantic_graph_admission'
    assert entry.WORKER == ROOT / 'scripts/prepare_semantic_graph_engineering.py'
    recipe = entry.recipe_files()
    assert recipe[str(entry.WORKER)] == entry.sha(entry.WORKER)
    assert recipe[str(entry.PROVIDER)] == entry.sha(entry.PROVIDER)
