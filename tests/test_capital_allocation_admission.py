"""Capital quality admission/startup tests: no services, LO, or models."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from sheets_factory.pipelines import capital_allocation_admission as admission
from sheets_factory.task_adapters.public_workbook_scope import reference, write_new
from sheets_factory.workbook.capital_allocation.catalog import generate_specs

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('_capital_quality_entry_tests', ROOT / 'scripts/run_capital_allocation_quality.py')
entry = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(entry)


def catalog(tmp_path):
    original = ROOT / 'config/capital_allocation_catalog_v1.json'
    rows = []
    generated = generate_specs(json.loads(original.read_bytes()))
    for candidate in generated:
        rows.append({'profile_id': candidate['profile_id'], 'spec': write_new(
            tmp_path / (candidate['profile_id'] + '.json'), candidate['spec'])})
    manifest = write_new(tmp_path / 'catalog_manifest.json', {
        'kind': 'generated_hypothetical_public_capital_allocation_specs', 'version': 1,
        'count': 10, 'catalog': reference(original), 'specifications': rows,
        'selection_uses_model_outcomes': False, 'actual_enumerated_plans': 0, 'LO_calls': 0, 'model_calls': 0})
    return manifest, generated


def test_predeclared_first_source_is_not_selected_from_results(tmp_path):
    manifest, specs = catalog(tmp_path)
    assert entry.validate_first_catalog(manifest['path'], specs[0]['spec']) == manifest
    with pytest.raises(ValueError, match='first specification K01'):
        entry.validate_first_catalog(manifest['path'], specs[1]['spec'])
    altered = deepcopy(specs[0]['spec']); altered['minimum_cash_pence'] += 1
    with pytest.raises(ValueError, match='first specification K01'):
        entry.validate_first_catalog(manifest['path'], altered)


def test_admission_rejects_offline_or_unverified_sources_before_book_reads(tmp_path):
    record = write_new(tmp_path / 'not_verified.json', {'kind': 'prepared_single_hypothetical_capital_allocation_source',
        'financial_audit_passed': True, 'actual_LO_recalculations': 0, 'qualified': False})
    with pytest.raises(ValueError, match='actual independently audited'):
        admission.validate_source(record)


def test_recursive_proof_bindings_reject_same_shape_changed_bytes(tmp_path):
    payload = write_new(tmp_path / 'audit.json', {'passed': True, 'checked_cells': 100})
    parent = write_new(tmp_path / 'source.json', {'audit': payload})
    artifacts = entry.bind_transitive(parent)
    assert artifacts[payload['path']] == payload['sha256']
    Path(payload['path']).write_text(json.dumps({'passed': True, 'checked_cells': 101}))
    with pytest.raises(ValueError, match='bytes or SHA'):
        entry.bind_transitive(parent)


def test_normal_preparation_routes_exact_source_without_starting_services(tmp_path, monkeypatch):
    manifest, specs = catalog(tmp_path)
    book = tmp_path / 'placeholder.xlsx'; book.write_bytes(b'offline source-validation boundary fixture')
    spec_ref = write_new(tmp_path / 'source_spec.json', specs[0]['spec'])
    source_ref = write_new(tmp_path / 'source_manifest.json', {'source_recipe_sha256': {}})
    proof = {'validation_method': admission.METHOD, 'workbook': reference(book), 'source_manifest': source_ref,
             'public_specification': spec_ref, 'quality_or_difficulty_certified': False}
    monkeypatch.setattr(admission, 'validate_source', lambda record: proof)
    provider_code = tmp_path / 'adapter.py'; provider_code.write_text('# offline adapter boundary\n')
    recovery_code = tmp_path / 'recovery.py'; recovery_code.write_text('# offline recovery boundary\n')
    provider = SimpleNamespace(__file__=str(provider_code), SETTING='capital_allocation_task',
        setting=lambda: {'version': 1, 'fixture': 'source validation and registry are mocked'},
        validate_setting=lambda value: None)
    recovery = SimpleNamespace(__file__=str(recovery_code))
    real_import = entry.importlib.import_module
    monkeypatch.setattr(entry.importlib, 'import_module', lambda name: provider if name == 'sheets_factory.task_adapters.capital_allocation'
        else recovery if name == 'sheets_factory.workbook.capital_allocation.public_recovery' else real_import(name))
    registry = tmp_path / 'registry.yaml'; registry.write_text('version: 1\nnodes: {}\n')
    monkeypatch.setattr(entry, 'REGISTRY', registry)
    base = tmp_path / 'base'; base.mkdir()
    write_new(base / 'preflight_manifest.json', {'recipe_sha256': {}})
    config = {'run': {'targets': {'financial_modeling': 10, 'debugging': 10},
        'max_steps': 3, 'max_evidence_rounds_per_revision': 2, 'infrastructure_retries_per_stage': 2,
        'max_additional_trials_per_revision': 0, 'continuation_id': 'old', 'resume_existing_task_ids': ['old-task']},
        'agents': {'model': 'gpt-6-sol', 'reasoning_effort': 'high'}, 'construction': {}, 'pipeline': {},
        'recovery': {'compiler_backend': 'composite_journal'},
        'engine': {'timeout_seconds': 300},
        'diagnosis': {'selection': {'include': 'all', 'exclude': []}}, 'harbor': {'execute_controls': True},
        'public_input_priority': {'old': 'must be removed'}}
    (base / 'resolved_config.yaml').write_text(yaml.safe_dump(config))
    output = tmp_path / 'new_quality'
    frozen_ref = entry.prepare(source_ref['path'], manifest['path'], base, output)
    frozen, prepared, restored = entry.validate_prepared(output)
    assert reference(output / 'preflight_manifest.json') == frozen_ref and restored == proof
    assert frozen['actual_models'] == frozen['actual_LO_calls'] == frozen['actual_full_enumerations'] == 0
    assert prepared['run']['targets'] == entry.TARGETS
    assert 'continuation_id' not in prepared['run'] and 'public_input_priority' not in prepared
    assert prepared['recovery'] == {'compiler_backend': 'capital_allocation_integer', 'replay_timeout_seconds': 1800}
    assert prepared['diagnosis']['execution']['reference_evidence_transport'] == 'audited_summary'
    assert not (output / 'run.sqlite').exists()
    # Use the actual inherited Factory loader, preserving its real manifest contract.
    instance = object.__new__(admission.CapitalAllocationFactory)
    instance.config, instance.targets, instance.admitted_proof = prepared, entry.TARGETS, proof
    instance.audit = SimpleNamespace(update_run=lambda **kw: None)
    seeds = instance.load_seeds()
    assert seeds[0]['survey']['normalized_path'] == str(book)
    assert seeds[0]['finance_evidence']['audited_source_binding'] == proof
    assert entry.read(prepared['public_workbook_scope']['manifest'])['tasks'] == {}


def test_factory_preserves_source_and_baseline_identity_after_each_phase(tmp_path, monkeypatch):
    path = tmp_path / 'source.xlsx'; path.write_bytes(b'exact original')
    baseline = tmp_path / 'baseline.xlsx'; baseline.write_bytes(path.read_bytes())
    proof = {'workbook': reference(path)}
    instance = object.__new__(admission.CapitalAllocationFactory); instance.admitted_proof = proof
    context = SimpleNamespace(source=path, data={'baseline': baseline, 'source_id': proof['workbook']['sha256']})
    monkeypatch.setattr(admission.FactoryPipeline, 'run_phase', lambda *a: None)
    instance.run_phase(context, 'normalize')
    baseline.write_bytes(b'changed by normalization')
    with pytest.raises(ValueError, match='Normalization changed'):
        instance.run_phase(context, 'normalize')


def test_cli_requires_explicit_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(entry, 'validate_prepared', lambda *a: ({}, {}, {}))
    monkeypatch.setattr(entry, 'execute_prepared', lambda *a, **kw: pytest.fail('Unexpected actual service/model call'))
    assert entry.main(['--prepared', str(tmp_path)]) == 0
    with pytest.raises(ValueError, match='Prepare a new'):
        entry.main(['--run', '--output', str(tmp_path)])


def test_existing_database_cannot_be_replayed_as_fresh_run(tmp_path, monkeypatch):
    (tmp_path / 'run.sqlite').write_bytes(b'existing')
    monkeypatch.setattr(entry, 'validate_prepared', lambda *a: ({}, {}, {}))
    monkeypatch.setattr(entry.cohort, 'prepared_host_runtime', lambda *a: ({}, False))
    class Host:
        def __enter__(self): return {}
        def __exit__(self, *a): return False
    monkeypatch.setattr(entry.cohort, 'host_temporary_environment', lambda *a, **kw: Host())
    monkeypatch.setattr(entry.cohort, 'ProducerLease', lambda *a: pytest.fail('Existing database must block services before acquiring lease'))
    with pytest.raises(ValueError, match='already started'):
        entry.execute_prepared(tmp_path)
