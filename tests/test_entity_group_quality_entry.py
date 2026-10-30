"""First G01 normal entry contracts: no Docker, models, or production books."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from sheets_factory.pipelines import entity_group_factory as family
from sheets_factory.pipelines import entity_group_admission as admission
from sheets_factory.task_adapters import entity_group as adapter
from sheets_factory.task_adapters.public_workbook_scope import reference, write_new
from sheets_factory.workbook.entity_group.catalog import build_spec, PROFILE_IDS, CONFIG

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('_entity_quality_entry_tests', ROOT / 'scripts/run_entity_group_quality.py')
entry = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(entry)


def catalog(tmp_path):
    rows = [{'profile_id': pid, 'spec': write_new(tmp_path / (pid + '.json'), build_spec(pid))} for pid in PROFILE_IDS]
    manifest = write_new(tmp_path / 'catalog_manifest.json', {'kind': 'predeclared_entity_group_public_specs',
        'version': 1, 'profile_order': list(PROFILE_IDS), 'catalog': reference(CONFIG), 'specifications': rows,
        'selection_uses_model_outcomes': False, 'same_provided_plan_shared_across_scenarios': True,
        'scenario_financing_states_are_independent': True, 'selected': [], 'qualified': False,
        'ledger_executions': 0, 'workbook_engine_calls': 0, 'model_calls': 0, 'source_workbooks': 0, 'task_count': 0})
    return manifest, rows


def base_configuration():
    return {'run': {'targets': {'financial_modeling': 10, 'debugging': 10}, 'max_steps': 3,
        'max_evidence_rounds_per_revision': 2, 'infrastructure_retries_per_stage': 2,
        'max_additional_trials_per_revision': 0, 'continuation_id': 'old', 'resume_existing_task_ids': ['old-task']},
        'agents': {'model': 'gpt-6-sol', 'reasoning_effort': 'high', 'trajectory_timeout_seconds': 600,
            'roles': {role: {'model': 'gpt-6-sol', 'reasoning_effort': 'high', 'timeout_seconds': timeout}
                for role, timeout in [('public_diagnostician', 600), ('reference_diagnostician', 2400)]}},
        'construction': {'root_impact_validation': 'shadow_roots'}, 'pipeline': {},
        'recovery': {'compiler_backend': 'composite_journal'}, 'engine': {'timeout_seconds': 300},
        'diagnosis': {'selection': {'include': 'all', 'exclude': []}}, 'harbor': {'execute_controls': True},
        'public_input_priority': {'old': 'must be removed'}, 'capital_allocation_task': {'old': True}}


@pytest.fixture
def case(tmp_path, monkeypatch):
    manifest, rows = catalog(tmp_path)
    book = tmp_path / 'source.fixture'; book.write_bytes(b'Explicit mocked complete source-admission boundary, not an XLSX proof')
    source_ref = write_new(tmp_path / 'source_manifest.json', {'source_recipe_sha256': {}})
    proof = {'kind': admission.KIND, 'version': 1, 'admission_implementation': reference(admission.__file__),
        'financial_seed_verified': True, 'workbook': reference(book), 'source_manifest': source_ref,
        'public_specification': rows[0]['spec'], 'runtime_profile': reference(entry.PROFILE),
        'artifact_sha256': {str(book): reference(book)['sha256']}, 'qualified': False, 'task_count': 0}
    monkeypatch.setattr(admission, 'validate_source', lambda record: deepcopy(proof))
    monkeypatch.setattr(admission, 'verify_admitted_proof', lambda value: value if value == proof else pytest.fail('Proof changed'))
    base = tmp_path / 'base'; base.mkdir()
    write_new(base / 'preflight_manifest.json', {'recipe_sha256': {}})
    (base / 'resolved_config.yaml').write_text(yaml.safe_dump(base_configuration()))
    return SimpleNamespace(tmp=tmp_path, manifest=manifest, rows=rows, book=book,
        source_ref=source_ref, proof=proof, base=base, output=tmp_path / 'quality')


def test_preparation_and_real_factory_ctor_loader_preserve_normal_routes(case):
    frozen_ref = entry.prepare(case.source_ref['path'], case.manifest['path'], case.base, case.output)
    frozen, config, proof = entry.validate_prepared(case.output)
    assert reference(case.output / 'preflight_manifest.json') == frozen_ref and proof == case.proof
    assert frozen['actual_models'] == frozen['actual_LO_calls'] == 0
    assert frozen['targets'] == {'financial_modeling': 0, 'debugging': 1}
    assert frozen['delivery_targets'] == {'financial_modeling': 10, 'debugging': 10}
    assert config['recovery']['compiler_backend'] == 'entity_group_public_integer_shared_compiler'
    assert config['recovery']['replay_timeout_seconds'] == 7200
    assert config['engine']['timeout_seconds'] == 600
    assert config['agents']['container_memory'] == '32g' and config['agents']['container_cpus'] == 2
    assert config['construction']['analysis_limits']['max_profile_cells'] == 3000000
    assert config['construction']['analysis_limits']['max_dependency_closure_cells'] == 3000000
    assert config['run']['max_steps'] == 3 and config['run']['max_evidence_rounds_per_revision'] == 2
    assert 'continuation_id' not in config['run'] and 'public_input_priority' not in config
    assert 'capital_allocation_task' not in config
    assert entry.read(config['public_workbook_scope']['manifest'])['tasks'] == {}
    assert not (case.output / 'run.sqlite').exists()
    audit = SimpleNamespace(update_run=lambda **kwargs: None)
    factory = family.EntityGroupFactory(config, audit, None, None, admitted_proof=proof)
    seeds = factory.load_seeds()
    assert seeds[0]['modes'] == ['debugging'] and seeds[0]['profile_id'] == 'G01'
    assert seeds[0]['survey']['normalized_path'] == proof['workbook']['path']
    assert seeds[0]['finance_evidence']['audited_source_binding'] == proof
    assert seeds[0]['finance_evidence']['reference_method'] == family.REFERENCE_METHOD
    assert family.EntityGroupFactory._execute_context is family.FactoryPipeline._execute_context
    phases = factory.templates['debugging']['phases']
    assert phases['revision'] == ['construct', 'instruction', 'precheck', 'independent_recovery', 'trajectory', 'diagnose']
    assert len(factory.node_registry) == 11


def test_catalog_is_full_fixed_order_and_first_G01(case):
    assert entry.validate_first_catalog(case.manifest['path'], entry.read(case.rows[0]['spec'])) == case.manifest
    with pytest.raises(ValueError, match='first development source must be G01'):
        entry.validate_first_catalog(case.manifest['path'], entry.read(case.rows[1]['spec']))
    manifest = entry.read(case.manifest); manifest['specifications'].reverse()
    altered = write_new(case.tmp / 'reordered.json', manifest)
    with pytest.raises(ValueError, match='G01..G10 order'):
        entry.validate_first_catalog(altered['path'], entry.read(case.rows[0]['spec']))


def test_partial_engineering_source_rejected_before_any_output(tmp_path):
    # Use real source admission, with no model or workbook attempted.
    source = write_new(tmp_path / 'partial.json', {'kind': admission.SOURCE_KIND, 'actual_LO_recalculations': 1})
    with pytest.raises(ValueError, match='completed, financially audited'):
        entry.prepare(source['path'], tmp_path / 'absent_catalog.json', tmp_path / 'absent_base', tmp_path / 'quality')
    assert not (tmp_path / 'quality').exists()


def test_source_proof_digests_stale_actual_evidence_still_fails(case):
    audit = write_new(case.tmp / 'financial_audit.json', {'passed': True, 'count': 3})
    case.proof['artifact_sha256'][audit['path']] = audit['sha256']
    Path(audit['path']).write_text(json.dumps({'passed': True, 'count': 2}))
    with pytest.raises(ValueError, match='dependency changed'):
        entry.prepare(case.source_ref['path'], case.manifest['path'], case.base, case.output)
    assert not (case.output / 'preflight_manifest.json').exists()


def test_unused_prior_source_stale_does_not_become_entity_proof(case):
    stale = write_new(case.tmp / 'old_family.json', {'old': 1})
    Path(stale['path']).write_text('{"old":2}')
    original = case.base / 'preflight_manifest.json'
    original.write_text(json.dumps({'recipe_sha256': {}, 'unused_prior_source': stale}))
    entry.prepare(case.source_ref['path'], case.manifest['path'], case.base, case.output)
    frozen, _, _ = entry.validate_prepared(case.output)
    assert stale['path'] not in frozen['source_artifacts_sha256']
    assert frozen['base_configuration_provenance']['prior_financial_source_proofs_reused'] is False
    original.write_text(original.read_text() + '\n')
    with pytest.raises(ValueError, match='dependency changed'): entry.validate_prepared(case.output)


@pytest.mark.parametrize('change', ['quota', 'source', 'FM_mode', 'reference_method', 'source_profile'])
def test_real_factory_loader_rejects_misrouted_or_relabelled_source(case, change):
    entry.prepare(case.source_ref['path'], case.manifest['path'], case.base, case.output)
    _, config, proof = entry.validate_prepared(case.output)
    seed = entry.read(reference(case.output / 'seed_manifest.json'))['selected'][0]
    if change == 'source': seed['sha256'] = 'f' * 64
    if change == 'FM_mode': seed['modes'] = ['financial_modeling']
    if change == 'reference_method': seed['finance_evidence']['reference_method'] = 'copied_reference'
    if change == 'source_profile': proof = deepcopy(proof); proof['runtime_profile'] = reference(ROOT/'config/runtime_profiles/entity_group_large_v1.yaml')
    if change == 'quota': config['run']['targets'] = {'financial_modeling': 1, 'debugging': 0}
    if change != 'source_profile' and change != 'quota':
        with pytest.raises(ValueError): family.validate_seed(seed, proof)
    else:
        with pytest.raises(ValueError): family.EntityGroupFactory(config, SimpleNamespace(), None, None, admitted_proof=proof)


def test_phase_boundary_rejects_changed_exact_source_baseline(tmp_path, monkeypatch):
    source = tmp_path / 'source.fixture'; source.write_bytes(b'original bytes')
    baseline = tmp_path / 'baseline.fixture'; baseline.write_bytes(source.read_bytes())
    factory = object.__new__(family.EntityGroupFactory); factory.admitted_proof = {'workbook': reference(source)}
    monkeypatch.setattr(family.FactoryPipeline, 'run_phase', lambda *args: None)
    ctx = SimpleNamespace(source=source, data={'baseline': baseline, 'source_id': reference(source)['sha256']})
    factory.run_phase(ctx, 'preparation')
    baseline.write_bytes(b'changed')
    with pytest.raises(ValueError, match='Normalization changed'): factory.run_phase(ctx, 'revision')


def test_existing_DB_blocks_services_before_acquiring_lease(tmp_path, monkeypatch):
    (tmp_path / 'run.sqlite').write_bytes(b'existing producer audit')
    monkeypatch.setattr(entry, 'validate_prepared', lambda *args: ({}, {}, {}))
    monkeypatch.setattr(entry.cohort, 'prepared_host_runtime', lambda *args: ({}, False))
    class Host:
        def __enter__(self): return {}
        def __exit__(self, *args): return False
    monkeypatch.setattr(entry.cohort, 'host_temporary_environment', lambda *args, **kwargs: Host())
    monkeypatch.setattr(entry.cohort, 'ProducerLease', lambda *args: pytest.fail('Existing DB must block lease/services'))
    with pytest.raises(ValueError, match='already started'): entry.execute_prepared(tmp_path)


def test_cli_default_never_executes_services(tmp_path, monkeypatch):
    monkeypatch.setattr(entry, 'validate_prepared', lambda *args: ({}, {}, {}))
    monkeypatch.setattr(entry, 'execute_prepared', lambda *args, **kwargs: pytest.fail('Unexpected service/model execution'))
    assert entry.main(['--prepared', str(tmp_path)]) == 0
    with pytest.raises(ValueError, match='Prepare and review'): entry.main(['--run', '--output', str(tmp_path)])


@pytest.mark.parametrize('change', ['model', 'check_subset', 'replay_budget', 'old_RAM', 'no_Harbor'])
def test_current_config_cannot_weaken_quality_or_resource_gates(case, change):
    entry.prepare(case.source_ref['path'], case.manifest['path'], case.base, case.output)
    _, config, _ = entry.validate_prepared(case.output)
    if change == 'model': config['agents']['model'] = 'other'
    if change == 'check_subset': config['diagnosis']['selection']['exclude'] = ['Q04']
    if change == 'replay_budget': config['recovery']['replay_timeout_seconds'] = 120
    if change == 'old_RAM': config['agents']['container_memory'] = '8g'
    if change == 'no_Harbor': config['harbor']['execute_controls'] = False
    with pytest.raises(ValueError): family.validate_configuration(config)


@pytest.mark.parametrize('fail_metadata', [False, True])
def test_execution_binds_exact_profile_path_and_releases_every_owned_resource(case, monkeypatch, fail_metadata):
    entry.prepare(case.source_ref['path'], case.manifest['path'], case.base, case.output)
    events = []
    prior_tmp = __import__('tempfile').tempdir
    class Engine:
        def __init__(self, root, profile, *, role, receipt_directory):
            assert root == ROOT and profile == str(entry.PROFILE)
            assert role == 'source' and receipt_directory == case.output / 'resource_receipts'
            assert __import__('os').environ['TMPDIR'] == str(case.output / 'temporary')
            events.append('engine')
        def metadata(self):
            if fail_metadata: raise RuntimeError('Explicit mock runtime setup failure')
            return {'image_id': admission.IMAGE_ID, 'actual_calculation_calls_recorded': 0}
    class LLM:
        def __init__(self, *args): events.append('llm')
        def _credentials(self): events.append('credentials_fixture_only')
    class Dashboard:
        def __init__(self, *args, **kwargs): events.append('dashboard_construct')
        def start(self): events.append('dashboard_start_fixture_only'); return 'http://127.0.0.1:0/'
        def stop(self): events.append('dashboard_stop')
    class Factory:
        def __init__(self, config, audit, llm, engine, *, admitted_proof):
            assert admitted_proof == case.proof
            events.append('factory')
        def run(self): events.append('run_boundary_only'); return False
    monkeypatch.setattr(entry, 'ResourceLibreOfficeEngine', Engine)
    monkeypatch.setattr(entry.cohort, 'CohortCodex', LLM)
    monkeypatch.setattr(entry.cohort, 'DashboardServer', Dashboard)
    monkeypatch.setattr(entry, 'EntityGroupFactory', Factory)
    if fail_metadata:
        with pytest.raises(RuntimeError, match='runtime setup failure'): entry.execute_prepared(case.output)
        assert 'llm' not in events
    else:
        assert entry.execute_prepared(case.output) == 2
        assert events.index('engine') < events.index('llm') < events.index('factory')
    assert events[-1] == 'dashboard_stop'
    assert __import__('tempfile').tempdir == prior_tmp
    assert json.loads((case.output / 'producer.lock').read_text())['status'] == 'released'
    # Real SQLite finalization committed the stop state, while service boundaries
    # above performed no container, network, model, or normal quality operation.
    import sqlite3
    with sqlite3.connect(case.output / 'run.sqlite') as database:
        run = json.loads(database.execute("SELECT value FROM state WHERE key='run'").fetchone()[0])
    assert run['producer_active'] is False
    assert run['exit_code'] == (1 if fail_metadata else 2)


def test_boolean_quotas_do_not_pass_integer_one_contract(case):
    entry.prepare(case.source_ref['path'], case.manifest['path'], case.base, case.output)
    _, config, _ = entry.validate_prepared(case.output)
    config['run']['targets']['debugging'] = True
    with pytest.raises(ValueError, match='fresh predeclared'): family.validate_configuration(config)
