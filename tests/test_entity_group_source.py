"""Source admission/orchestration tests with explicit fake engine boundaries.

No production workbook, integer ledger, Docker job or model is executed here.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from sheets_factory.task_adapters.public_workbook_scope import reference, write_new

ROOT = Path(__file__).resolve().parents[1]
_location = importlib.util.spec_from_file_location('_entity_source_tests', ROOT / 'scripts/build_entity_group_source.py')
entry = importlib.util.module_from_spec(_location); _location.loader.exec_module(entry)


@pytest.fixture
def core(tmp_path, monkeypatch):
    directory = tmp_path / 'numeric_core'; directory.mkdir()
    for name in ('__init__.py', 'spec.py', 'ledger.py', 'excel.py', 'validate.py', 'catalog.py'):
        (directory / name).write_text('# isolated source-orchestration boundary fixture\n')
    monkeypatch.setattr(entry, 'CORE', directory)
    return directory


@pytest.fixture
def count_case(tmp_path, core):
    public = {'fixture': 'schema-independent count receipt test'}
    spec = write_new(tmp_path / 'public.json', public)
    count = {'kind': 'entity_group_complete_formula_count_only', 'version': 1,
        'dimension_mode': 'production', 'entity_count': 24, 'month_count': 120, 'scenario_count': 3,
        'physical_formula_count': 1, 'logical_output_binding_count': 1, 'physical_nonempty_cells': 3,
        'worksheet_count': 1, 'worksheet_rows': {'S01 Close': 2}, 'maximum_expression_depth': 2,
        'maximum_formula_length': 4, 'public_primitive_count': 1, 'formula_text_characters': 4,
        'complete_expression_stream_sha256': 'a' * 64, 'complete_logical_binding_stream_sha256': 'b' * 64,
        'within_one_million_physical_formulas': True, 'production_workbook_materialized': False,
        'ledger_execution': False, 'LO_calls': 0, 'model_calls': 0, 'qualified': False, 'task_count': 0}
    receipt = {'kind': 'entity_group_G01_full_count_only_engineering', 'revision': 2, 'status': 'completed',
        'public_spec': spec, 'recipe': [reference(core / name) for name in ('spec.py', 'excel.py')],
        'count': count, 'production_workbook_materialized': False, 'ledger_execution': False,
        'LO_calls': 0, 'model_calls': 0, 'qualified': False, 'task_count': 0}
    return SimpleNamespace(public=public, spec=spec, count=count, receipt=receipt, directory=tmp_path)


def test_complete_count_is_checked_without_emitting_or_executing(count_case, monkeypatch):
    case = count_case
    monkeypatch.setattr(entry, 'emit_entity_group_workbook', lambda *a, **kw: pytest.fail('Count validation cannot emit'))
    record = write_new(case.directory / 'count.json', case.receipt)
    assert entry.validate_count_receipt(record, case.spec, case.public) == case.count


@pytest.mark.parametrize('location,key,value,match', [
    ('count', 'physical_formula_count', 1_273_134, 'physical-formula'),
    ('count', 'physical_formula_count', True, 'physical-formula'),
    ('count', 'within_one_million_physical_formulas', False, 'one-million'),
    ('count', 'maximum_formula_length', 8193, 'formula-length'),
    ('count', 'truncated', True, 'untruncated'),
    ('count', 'complete_expression_stream_sha256', '', 'stream'),
    ('count', 'worksheet_rows', {'Close': 1048577}, 'worksheet-row'),
    ('count', 'worksheet_count', 2, 'inconsistent'),
    ('count', 'scenario_count', 2, '3-scenario'),
    ('count', 'production_workbook_materialized', True, 'zero-call'),
    ('receipt', 'status', 'running', 'completed'),
    ('receipt', 'revision', True, 'completed'),
    ('receipt', 'LO_calls', 1, 'zero-call'),
])
def test_count_completion_does_not_relax_source_admission(count_case, location, key, value, match):
    case = count_case; payload = deepcopy(case.receipt)
    (payload['count'] if location == 'count' else payload)[key] = value
    record = write_new(case.directory / 'negative_count.json', payload)
    with pytest.raises(ValueError, match=match): entry.validate_count_receipt(record, case.spec, case.public)


def test_count_requires_exact_same_spec_and_current_emitter(count_case, core):
    case = count_case
    record = write_new(case.directory / 'count.json', case.receipt)
    other = write_new(case.directory / 'other.json', {'other': 1})
    with pytest.raises(ValueError, match='another public'): entry.validate_count_receipt(record, other, {'other': 1})
    (core / 'excel.py').write_text('# changed emitter\n')
    with pytest.raises(ValueError, match='bytes or SHA'): entry.validate_count_receipt(record, case.spec, case.public)


@pytest.fixture
def large_profile():
    return yaml.safe_load((ROOT / 'config/runtime_profiles/entity_group_large_v1.yaml').read_text())


def test_explicit_large_profile_admits_complete_count_and_keeps_legacy_limit(count_case, large_profile):
    case = count_case; payload = deepcopy(case.receipt)
    payload['count'].update(physical_formula_count=1_100_346, physical_nonempty_cells=2_222_012,
        formula_text_characters=484_510_227, within_one_million_physical_formulas=False)
    record = write_new(case.directory / 'complete_large_count.json', payload)
    with pytest.raises(ValueError, match='physical-formula'):
        entry.validate_count_receipt(record, case.spec, case.public)
    assert entry.validate_count_receipt(record, case.spec, case.public, large_profile) == payload['count']
    payload['count']['physical_formula_count'] = 2_000_001
    record = write_new(case.directory / 'too_large.json', payload)
    with pytest.raises(ValueError, match='physical-formula'):
        entry.validate_count_receipt(record, case.spec, case.public, large_profile)


def test_profile_requires_exact_runtime_and_new_recipe_binding(tmp_path, core, large_profile):
    record = write_new(tmp_path / 'profile.json', large_profile)
    assert entry.load_profile(record) == large_profile
    assert entry.formula_limit(None) == 1_000_000
    assert entry.formula_limit(large_profile) == 2_000_000
    assert str(ROOT / 'src/sheets_factory/workbook/resource_engine.py') not in entry.recipes()
    assert str(ROOT / 'src/sheets_factory/workbook/resource_engine.py') in entry.recipes(large_profile)
    other = deepcopy(large_profile); other['image']['id'] = 'sha256:' + 'a' * 64
    with pytest.raises(ValueError, match='approved runtime'):
        entry.load_profile(write_new(tmp_path / 'other_profile.json', other))
    Path(record['path']).write_bytes(Path(record['path']).read_bytes() + b'\n')
    with pytest.raises(ValueError, match='bytes or SHA'):
        entry.load_profile(record)


def test_source_engine_opt_in_uses_real_resource_adapter_without_starting_Docker(tmp_path, large_profile):
    engine = entry.source_engine(large_profile, tmp_path / 'attempt')
    from sheets_factory.workbook.resource_engine import ResourceLibreOfficeEngine
    assert isinstance(engine, ResourceLibreOfficeEngine)
    assert engine.role == 'source' and engine.timeout_seconds == 600
    assert engine.profile == large_profile
    assert engine.receipt_directory == tmp_path / 'attempt/resource_receipts'
    assert not list(engine.receipt_directory.iterdir())
    legacy = entry.source_engine(None, tmp_path / 'legacy')
    assert type(legacy) is entry.LibreOfficeEngine and legacy.timeout_seconds == 300


@pytest.mark.parametrize('tamper', [None, 'stream', 'geometry', 'physical_formula'])
def test_real_small_emission_matches_complete_count_before_any_engine_call(tamper):
    location = importlib.util.spec_from_file_location('_entity_source_small_hand_spec', ROOT / 'tests/test_entity_group_ledger.py')
    hand = importlib.util.module_from_spec(location); location.loader.exec_module(hand)
    from sheets_factory.workbook.entity_group.excel import count_entity_group_formulas
    public = hand.specification()
    count = count_entity_group_formulas(public)
    book = entry.openpyxl.Workbook(); book.remove(book.active)
    try:
        binding = entry.emit_entity_group_workbook(book, public)
        if tamper == 'stream': count['complete_logical_binding_stream_sha256'] = '0' * 64
        if tamper == 'geometry': count['physical_nonempty_cells'] += 1
        if tamper == 'physical_formula':
            first = binding['formula_bindings'][0]; book[first['sheet']][first['cell']] = '=42'
        if tamper:
            with pytest.raises(ValueError): entry.validate_emission(book, binding, count)
        else:
            entry.validate_emission(book, binding, count)
    finally:
        book.close()


def resource_runtime(profile, receipts):
    return {'image_id': entry.IMAGE_ID, 'network': 'none', 'role': 'source', 'runtime_profile': profile,
        'requested_resources': profile['docker_resources']['source'],
        'agent_and_other_roles_applied_by_this_engine': False, 'actual_resource_receipts': receipts,
        'actual_calculation_calls_recorded': len(receipts)}


def test_source_resource_metadata_does_not_certify_any_unexecuted_role(large_profile):
    runtime = resource_runtime(large_profile, [])
    entry.validate_resources(runtime, large_profile, completed_calls=0)
    with pytest.raises(ValueError, match='call count'):
        entry.validate_resources(runtime, large_profile, completed_calls=1)
    runtime['agent_and_other_roles_applied_by_this_engine'] = True
    with pytest.raises(ValueError, match='resource profile'):
        entry.validate_resources(runtime, large_profile, completed_calls=0)


@pytest.mark.parametrize('change', ['unverified', 'wrong_memory', 'wrong_role', 'failed', 'stale_sha'])
def test_successful_source_requires_actual_inspected_resources(tmp_path, large_profile, change):
    call = {'kind': 'resource_bound_libreoffice_call', 'status': 'completed', 'role': 'source',
        'image_id': entry.IMAGE_ID, 'actual_resources_verified': True,
        'requested_resources': large_profile['docker_resources']['source'],
        'actual_resources': {'cpus_nanoseconds': 2 * 10**9, 'memory_bytes': 8 * 1024**3, 'pids_limit': 256}}
    if change == 'unverified': call['actual_resources_verified'] = False
    if change == 'wrong_memory': call['actual_resources']['memory_bytes'] = 2 * 1024**3
    if change == 'wrong_role': call['role'] = 'agent'
    if change == 'failed': call['status'] = 'failed'
    record = write_new(tmp_path / 'actual_resource.json', call)
    if change == 'stale_sha': Path(record['path']).write_bytes(Path(record['path']).read_bytes() + b'\n')
    with pytest.raises(ValueError):
        entry.validate_resources(resource_runtime(large_profile, [record]), large_profile, completed_calls=1)


def test_explicit_numerical_recipe_ignores_unrelated_future_orchestration(core):
    original = entry.recipes()
    (core / 'future_sizing.py').write_text('# new unrelated helper\n')
    (core / 'catalog.py').write_text('# changed catalog orchestration\n')
    assert entry.recipes() == original
    (core / 'ledger.py').write_text('# changed financial contract\n')
    with pytest.raises(ValueError, match='financial execution recipe'): entry.check_recipes(original)


@pytest.fixture
def prepared_case(tmp_path, core, monkeypatch):
    # Full numeric/source admissions have independent tests. Here they are
    # replaced explicitly to exercise orchestration without a production emit.
    public = {'dimension_mode': 'production', 'entities': list(range(24)),
              'months': list(range(120)), 'scenarios': list(range(3))}
    spec = write_new(tmp_path / 'spec.json', public)
    catalog = write_new(tmp_path / 'catalog_manifest.json', {'boundary_fixture': True})
    terminal = write_new(tmp_path / 'terminal.json', {'boundary_fixture': True})
    started = write_new(tmp_path / 'started.json', {'boundary_fixture': True})
    ledger = write_new(tmp_path / 'forward.json', {'feasible': True, 'spec_sha256': entry.canonical(public)})
    evidence = write_new(tmp_path / 'reachability.json', {'result_sha256': entry.canonical(entry.read(ledger))})
    count_ref = write_new(tmp_path / 'count.json', {'boundary_fixture': True})
    count = {'physical_formula_count': 1, 'logical_output_binding_count': 1, 'physical_nonempty_cells': 3,
             'worksheet_rows': {'Close': 2}, 'maximum_formula_length': 4}
    forward = {'terminal': terminal, 'started': started, 'result': ledger, 'reachability': evidence}
    monkeypatch.setattr(entry, 'load_spec', lambda value: value)
    monkeypatch.setattr(entry, 'validate_catalog', lambda *args: {'catalog': catalog, 'recipe': [],
        'specifications': [{'spec': spec}], 'provenance': {'kind': 'explicit_orchestration_test_fixture'}})
    monkeypatch.setattr(entry, 'validate_forward', lambda *args: (forward, entry.read(ledger)))
    monkeypatch.setattr(entry, 'validate_count_receipt', lambda *args: count)
    output = tmp_path / 'prepared'
    return SimpleNamespace(public=public, spec=spec, catalog=catalog, terminal=terminal, evidence=evidence,
        count_ref=count_ref, count=count, output=output, ledger=ledger)


def prepare_fixture(case):
    return entry.prepare(case.spec['path'], case.output, catalog_manifest=case.catalog['path'],
        forward_terminal=case.terminal['path'], reachability_evidence=case.evidence['path'], count_receipt=case.count_ref['path'])


def test_prepare_creates_no_workbook_and_preserves_full_provenance(prepared_case, monkeypatch):
    case = prepared_case
    monkeypatch.setattr(entry.openpyxl, 'Workbook', lambda *a, **kw: pytest.fail('Preparation cannot materialize a workbook'))
    monkeypatch.setattr(entry, 'LibreOfficeEngine', lambda *a, **kw: pytest.fail('Preparation cannot create an engine'))
    record = prepare_fixture(case)
    frozen, public, ledger = entry.validate_prepared(case.output)
    assert reference(case.output / 'preparation.json') == record
    assert frozen['production_workbook_materialized'] is False
    assert frozen['actual_LO_recalculations'] == frozen['model_calls'] == frozen['ledger_executions'] == 0
    assert not list(case.output.rglob('*.xlsx'))
    assert public == case.public and ledger == entry.read(case.ledger)
    assert 'source_ancestor_unique_count' not in frozen
    assert frozen['raw_ancestor_hashes_are_provenance_only_not_new_source_workbook_counts'] is True
    with pytest.raises(ValueError, match='fresh'): prepare_fixture(case)


def test_large_preparation_binds_profile_without_inventing_future_workload_counts(prepared_case, large_profile):
    case = prepared_case; record = write_new(case.output.parent / 'runtime_profile.json', large_profile)
    entry.prepare(case.spec['path'], case.output, catalog_manifest=case.catalog['path'],
        forward_terminal=case.terminal['path'], reachability_evidence=case.evidence['path'],
        count_receipt=case.count_ref['path'], runtime_profile=record['path'])
    frozen, _, _ = entry.validate_prepared(case.output)
    assert frozen['formula_admission_limit'] == 2_000_000
    assert frozen['runtime_profile'] == large_profile
    assert frozen['evidence']['runtime_profile'] == record
    assert frozen['future_profile_closure_and_target_counts_not_claimed_by_source_preparation'] is True
    assert 'workload_counts' not in frozen
    assert not list(case.output.rglob('*.xlsx'))
    Path(record['path']).write_text('{}')
    with pytest.raises(ValueError, match='bytes or SHA'):
        entry.validate_prepared(case.output)


def test_prepared_full_report_and_numerical_code_tampering_are_rejected(prepared_case, core):
    case = prepared_case; prepare_fixture(case)
    path = Path(case.ledger['path']); original = path.read_bytes(); path.write_bytes(original + b'\n')
    with pytest.raises(ValueError, match='bytes or SHA'): entry.validate_prepared(case.output)
    path.write_bytes(original)
    (core / 'validate.py').write_text('# altered independent audit\n')
    with pytest.raises(ValueError, match='financial execution recipe'): entry.validate_prepared(case.output)


def install_fake_services(monkeypatch, events):
    class FakeLease:
        def __init__(self, *args): pass
        def acquire(self): events.append('lease.acquire'); return self
        def release(self): events.append('lease.release')
    class FakeAudit:
        def __init__(self, *args): self.db = SimpleNamespace(close=lambda: events.append('db.close'))
        def task(self, *args, **kwargs): pass
        def record(self, *args): return 1
        def update_record(self, *args): pass
        def emit(self, *args, **kwargs): pass
        def update_run(self, **kwargs): pass
        def export(self): events.append('audit.export')
        def snapshot(self): return {}
        def events(self, after=0): return []
    class FakeServer:
        def __init__(self, *args, **kwargs): pass
        def start(self): events.append('server.start'); return 'http://unit-test.invalid/'
        def stop(self): events.append('server.stop')
    monkeypatch.setattr(entry, 'ProducerLease', FakeLease)
    monkeypatch.setattr(entry, 'AuditStore', FakeAudit)
    monkeypatch.setattr(entry, 'DashboardServer', FakeServer)
    return FakeAudit, FakeServer


@pytest.mark.parametrize('failure', ['engine', 'audit', 'stability', None])
@pytest.mark.parametrize('use_large_profile', [False, True])
def test_actual_call_receipts_and_failures_are_preserved_without_real_engine(tmp_path, monkeypatch, failure,
                                                                           use_large_profile, large_profile):
    events = []; install_fake_services(monkeypatch, events)
    output = tmp_path / 'source'; output.mkdir()
    frozen = {'public_specification': write_new(tmp_path / 'spec.json', {}), 'recipe_sha256': {},
        'resource_count': {}, 'evidence': {'forward': {'result': write_new(tmp_path / 'ledger.json', {}),
            'reachability': write_new(tmp_path / 'evidence.json', {})}, 'count_receipt': write_new(tmp_path / 'count.json', {})},
        'provenance': {'kind': 'unit_test_only'}}
    if use_large_profile:
        frozen['evidence']['runtime_profile'] = write_new(tmp_path / 'resource_profile.json', large_profile)
    write_new(output / 'preparation.json', frozen)
    monkeypatch.setattr(entry, 'validate_prepared', lambda *args: (frozen, {}, {}))
    monkeypatch.setattr(entry, 'validate_emission', lambda *args: None)
    def emit(book, public, **kwargs):
        assert kwargs == {'max_formulas': 2_000_000 if use_large_profile else 1_000_000, 'allow_production': True}
        sheet = book.create_sheet('Test double'); sheet['A1'] = '=1'
        return {'public_spec': {}, 'formula_count': 1}
    monkeypatch.setattr(entry, 'emit_entity_group_workbook', emit)
    class FakeEngine:
        def __init__(self, profile, attempt): self.index, self.profile, self.attempt, self.receipts = 0, profile, attempt, []
        def ensure_image(self): return entry.IMAGE_ID
        def metadata(self):
            base = {'image_id': entry.IMAGE_ID, 'network': 'none', 'test_double': True}
            if self.profile is not None:
                base.update(role='source', runtime_profile=self.profile,
                    requested_resources=self.profile['docker_resources']['source'],
                    agent_and_other_roles_applied_by_this_engine=False,
                    actual_resource_receipts=self.receipts[:], actual_calculation_calls_recorded=len(self.receipts))
            return base
        def recalculate(self, source, destination):
            self.index += 1
            # The started receipt must already exist before any attempt starts.
            started = destination.parent / f'engine_call{self.index}_started.json'
            assert started.exists() and entry.read(reference(started))['completed'] is False
            failed = failure == 'engine' and self.index == 2
            if not failed: destination.write_bytes(Path(source).read_bytes())
            if self.profile is not None:
                resource = {'kind': 'resource_bound_libreoffice_call', 'status': 'failed' if failed else 'completed',
                    'role': 'source', 'image_id': entry.IMAGE_ID, 'actual_resources_verified': True,
                    'requested_resources': self.profile['docker_resources']['source'],
                    'actual_resources': {'cpus_nanoseconds': 2 * 10**9, 'memory_bytes': 8 * 1024**3, 'pids_limit': 256},
                    'source': reference(source), 'destination': str(destination.resolve())}
                if not failed: resource['output'] = reference(destination)
                self.receipts.append(write_new(self.attempt / f'fake_resource{self.index}_terminal.json', resource))
            if failed: raise RuntimeError('explicit fake engine failure')
            events.append('fake.engine'); return destination
    monkeypatch.setattr(entry, 'source_engine', FakeEngine)
    monkeypatch.setattr(entry, 'audit_entity_group_workbook', lambda *args: {
        'passed': failure != 'audit', 'all_independent_journal_fields_covered': True,
        'physical_formulas_checked': 1, 'all_scenarios_feasible': True, 'mismatches': [], 'control_mismatches': []})
    monkeypatch.setattr(entry, 'compare_exact_typed', lambda *args: {'passed': failure != 'stability'})
    if failure:
        with pytest.raises((RuntimeError, ValueError)): entry.execute_prepared(output)
    else:
        result = entry.execute_prepared(output); assert entry.read(result)['actual_LO_recalculations'] == 3
    attempts = list((output / 'private/build_attempts').iterdir()); assert len(attempts) == 1
    terminal = entry.read(reference(attempts[0] / 'terminal.json'))
    assert terminal['status'] == ('failed' if failure else 'source_verified')
    assert terminal['calls']
    for call in terminal['calls']:
        started = entry.read(call['started_receipt']); actual_terminal = entry.read(call['terminal_receipt'])
        assert started['completed'] is False
        assert actual_terminal == {k: v for k, v in call.items() if k != 'terminal_receipt'}
        if use_large_profile:
            assert call['workbook_file_timeout_seconds'] == 600
            assert call['requested_source_resources'] == large_profile['docker_resources']['source']
            assert entry.read(call['actual_resource_receipt'])['role'] == 'source'
    if failure == 'engine':
        assert len(terminal['calls']) == 2 and terminal['calls'][1]['completed'] is False
    assert events[-3:] == ['server.stop', 'db.close', 'lease.release']
    assert (output / 'seed_manifest.json').exists() is (failure is None)
    if failure is None and use_large_profile:
        manifest = entry.read(reference(output / 'seed_manifest.json'))
        assert manifest['runtime']['actual_calculation_calls_recorded'] == 3
        assert manifest['agent_and_verifier_resource_application_still_pending'] is True


@pytest.mark.parametrize('broken', ['update', 'export', 'server', 'close'])
def test_cleanup_always_releases_producer_lease(tmp_path, monkeypatch, broken):
    events = []; audit, server = install_fake_services(monkeypatch, events)
    output = tmp_path / 'source'; output.mkdir()
    monkeypatch.setattr(entry, 'validate_prepared', lambda *args: ({}, {}, {}))
    monkeypatch.setattr(entry, '_execute', lambda *args: (_ for _ in ()).throw(ValueError('explicit build failure')))
    def fail(): raise RuntimeError('explicit fake cleanup failure')
    if broken == 'update': monkeypatch.setattr(audit, 'update_run', lambda *args, **kwargs: fail())
    if broken == 'export': monkeypatch.setattr(audit, 'export', lambda *args: fail())
    if broken == 'server': monkeypatch.setattr(server, 'stop', lambda *args: fail())
    if broken == 'close':
        original = audit.__init__
        def init(self, *args): original(self, *args); self.db.close = fail
        monkeypatch.setattr(audit, '__init__', init)
    with pytest.raises((ValueError, RuntimeError)): entry.execute_prepared(output)
    assert events[-1] == 'lease.release'


def test_cli_never_runs_without_explicit_run(monkeypatch, tmp_path):
    monkeypatch.setattr(entry, 'validate_prepared', lambda *args: ({}, {}, {}))
    monkeypatch.setattr(entry, 'execute_prepared', lambda *args, **kwargs: pytest.fail('Unexpected actual run'))
    assert entry.main(['--prepared', str(tmp_path)]) == 0
    with pytest.raises(ValueError, match='Prepare all'): entry.main(['--run', '--spec', str(tmp_path)])
