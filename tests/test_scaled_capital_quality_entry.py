"""Entry boundary tests use explicit fake source proofs, never production services."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
descriptor = importlib.util.spec_from_file_location('_scaled_quality_entry_test', ROOT / 'scripts/run_scaled_capital_quality.py')
entry = importlib.util.module_from_spec(descriptor)
descriptor.loader.exec_module(entry)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return entry.reference(path)


def configuration():
    return {'run': {'targets': {'financial_modeling': 10, 'debugging': 10}, 'max_steps': 3,
        'max_evidence_rounds_per_revision': 2, 'infrastructure_retries_per_stage': 2,
        'max_additional_trials_per_revision': 0, 'continuation_id': 'prior', 'resume_existing_task_ids': ['prior-task']},
        'agents': {'model': 'gpt-6-sol', 'reasoning_effort': 'high', 'trajectory_timeout_seconds': 600,
            'roles': {role: {'model': 'gpt-6-sol', 'reasoning_effort': 'high', 'timeout_seconds': timeout}
                for role, timeout in [('public_diagnostician', 600), ('reference_diagnostician', 2400)]}},
        'construction': {'root_impact_validation': 'shadow_roots'}, 'pipeline': {},
        'recovery': {'compiler_backend': 'prior'}, 'engine': {'timeout_seconds': 300},
        'diagnosis': {'selection': {'include': 'all', 'exclude': []}}, 'harbor': {'execute_controls': True},
        'capital_allocation_task': {'prior': True}, 'public_input_priority': {'prior': True}}


@pytest.fixture
def case(tmp_path, monkeypatch):
    book = tmp_path / 'source.fixture'
    book.write_bytes(b'Explicit test double for complete source admission; not an Excel proof')
    public = entry.catalog.build_spec('30-D01')
    rows = [{'profile_id': pid, 'spec': write(tmp_path / (pid + '.json'), entry.catalog.build_spec(pid))}
            for pid in entry.catalog.PROFILE_ORDER]
    manifest = write(tmp_path / 'catalog.json', {'kind': 'generated_scaled_capital_allocation_public_specs',
        'status': 'completed_public_primitives_only', 'prospective_first_strong_profile': '30-D01',
        'profile_order': list(entry.catalog.PROFILE_ORDER), 'selection_uses_model_outcomes': False, 'specifications': rows})
    # Only the catalog file identity is replaced in these entry boundary tests.
    # Production requires the independently frozen full catalog and real source admission.
    monkeypatch.setattr(entry, 'CATALOG_SHA256', manifest['sha256'])
    source = write(tmp_path / 'source.json', {'source_recipe_sha256': {}})
    public_ref = next(row['spec'] for row in rows if row['profile_id'] == '30-D01')
    proof = {'workbook': entry.reference(book), 'source_manifest': source, 'public_specification': public_ref,
        'runtime_profile': entry.reference(entry.PROFILE), 'artifact_sha256': {str(book): entry.reference(book)['sha256']}}
    monkeypatch.setattr(entry.admission, 'validate_source', lambda value, **kwargs: deepcopy(proof))
    monkeypatch.setattr(entry.admission, 'verify_admitted_proof', lambda value, **kwargs: value if value == proof else pytest.fail('Proof changed'))
    kernel = write(tmp_path / 'kernel.json', {'kind': 'explicit_fixture_not_an_actual_compilation'})
    monkeypatch.setattr(entry.public_recovery, 'validate_kernel_preparation', lambda value: entry.read(value))
    base = tmp_path / 'base'
    write(base / 'preflight_manifest.json', {'recipe_sha256': {}})
    (base / 'resolved_config.yaml').write_text(yaml.safe_dump(configuration()))
    return SimpleNamespace(tmp=tmp_path, book=book, source=source, proof=proof,
        catalog=manifest, public=public, rows=rows, kernel=kernel, base=base, output=tmp_path / 'quality')


def prepare(case):
    return entry.prepare(case.source['path'], case.catalog['path'], case.base, case.output,
                         public_kernel_preparation=case.kernel)


def test_entry_preserves_source_actual_identity_and_protected_budgets(case):
    frozen_ref = prepare(case)
    frozen, config, proof = entry.validate_prepared(case.output)
    assert entry.reference(case.output / 'preflight_manifest.json')['sha256'] == frozen_ref['sha256']
    assert proof == case.proof and frozen['actual_models'] == frozen['actual_LO_calls'] == 0
    assert frozen['targets'] == {'financial_modeling': 1, 'debugging': 0}
    assert frozen['profile_id'] == '30-D01' and frozen['development_only'] is True
    assert config['recovery']['public_kernel_preparation'] == case.kernel
    assert frozen['kernel_compilation_performed_by_entry'] is False
    assert config['recovery']['replay_timeout_seconds'] == 7200
    assert config['agents']['container_memory'] == '32g' and config['agents']['container_cpus'] == 2
    assert config['construction']['analysis_limits']['max_profile_cells'] == 500000
    assert config['run']['max_steps'] == 3 and config['run']['max_additional_trials_per_revision'] == 0
    assert 'capital_allocation_task' not in config and 'public_input_priority' not in config
    assert 'continuation_id' not in config['run'] and entry.read(config['public_workbook_scope']['manifest'])['tasks'] == {}
    seed = entry.read(frozen['prepared_seed_manifest'])['selected'][0]
    entry.validate_seed(seed, proof)
    assert seed['profile_id'] == '30-D01' and seed['modes'] == ['financial_modeling']
    assert not (case.output / 'run.sqlite').exists()


@pytest.mark.parametrize('field', ['model', 'checks', 'replay', 'memory', 'Harbor', 'targets', 'kernel'])
def test_config_changes_cannot_weaken_independent_normal_checks(case, field):
    prepare(case)
    _, config, _ = entry.validate_prepared(case.output)
    if field == 'model': config['agents']['model'] = 'another'
    elif field == 'checks': config['diagnosis']['selection']['exclude'] = ['Q04']
    elif field == 'replay': config['recovery']['replay_timeout_seconds'] = 1800
    elif field == 'memory': config['agents']['container_memory'] = '8g'
    elif field == 'Harbor': config['harbor']['execute_controls'] = False
    elif field == 'targets': config['run']['targets'] = {'financial_modeling': 0, 'debugging': 1}
    else: config['recovery'].pop('public_kernel_preparation')
    with pytest.raises((ValueError, KeyError)):
        entry.validate_configuration(config)


def test_confirmation_source_cannot_be_relabelled_as_first_development(case):
    confirmation = entry.catalog.build_spec('30-G01')
    with pytest.raises(ValueError, match='first development source'):
        entry.validate_first_catalog(case.catalog['path'], confirmation)


def test_compilation_receipt_tampering_invalidates_prepared_run(case):
    prepare(case)
    Path(case.kernel['path']).write_text('{"changed":"compile identity"}')
    with pytest.raises(ValueError, match='changed'):
        entry.validate_prepared(case.output)


def test_unrelated_prior_financial_proof_is_not_admitted(case):
    stale = write(case.tmp / 'prior.json', {'unused': 1})
    Path(stale['path']).write_text('{"unused":2}')
    (case.base / 'preflight_manifest.json').write_text(json.dumps({'recipe_sha256': {}, 'prior_source': stale}))
    prepare(case)
    frozen, _, _ = entry.validate_prepared(case.output)
    assert stale['path'] not in frozen['source_artifacts_sha256']
    assert frozen['base_configuration_provenance']['prior_source_proofs_reused'] is False


def test_new_digests_do_not_allow_source_identity_or_mode_drift(case):
    prepare(case)
    frozen, _, proof = entry.validate_prepared(case.output)
    seed = entry.read(frozen['prepared_seed_manifest'])['selected'][0]
    seed['modes'] = ['debugging']
    with pytest.raises(ValueError, match='exact task routing'):
        entry.validate_seed(seed, proof)


def test_existing_run_prevents_any_new_service(tmp_path, monkeypatch):
    (tmp_path / 'run.sqlite').write_bytes(b'previous audit')
    monkeypatch.setattr(entry, 'validate_prepared', lambda value, **kwargs: ({}, {}, {}))
    monkeypatch.setattr(entry.cohort, 'prepared_host_runtime', lambda value: ({}, False))
    from contextlib import nullcontext
    monkeypatch.setattr(entry.cohort, 'host_temporary_environment', lambda *a, **kw: nullcontext({}))
    monkeypatch.setattr(entry.cohort, 'ProducerLease', lambda value: pytest.fail('No lease before old audit rejection'))
    with pytest.raises(ValueError, match='producer already started'):
        entry.execute_prepared(tmp_path)


def test_cli_validation_does_not_compile_or_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(entry, 'validate_prepared', lambda value: ({}, {}, {}))
    monkeypatch.setattr(entry, 'execute_prepared', lambda *a, **kw: pytest.fail('Unexpected actual services'))
    assert entry.main(['--prepared', str(tmp_path)]) == 0
    with pytest.raises(ValueError, match='Prepare and review'):
        entry.main(['--run', '--output', str(tmp_path)])


@pytest.mark.parametrize('engine_failure', [False, True])
def test_owned_run_finalizes_audit_lease_panel_and_temporary_environment(case, monkeypatch, engine_failure):
    prepare(case)
    import os
    import sqlite3
    import tempfile
    previous_tmp = tempfile.tempdir
    events = []
    class Engine:
        def __init__(self, root, profile, *, role, receipt_directory):
            assert root == ROOT and profile == str(entry.PROFILE)
            assert role == 'source' and receipt_directory == case.output / 'resource_receipts'
            assert os.environ['TMPDIR'] == str(case.output / 'temporary')
            events.append('engine')
        def metadata(self):
            if engine_failure:
                raise RuntimeError('Explicit fixture engine setup failure')
            return {'image_id': entry.admission.IMAGE_ID}
    class Dashboard:
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            events.append('panel_start')
            return 'http://127.0.0.1:0/'
        def stop(self):
            events.append('panel_stop')
    class LLM:
        def __init__(self, *args):
            events.append('LLM_fixture')
        def _credentials(self):
            pass
    class Factory:
        def __init__(self, config, audit, llm, engine, *, admitted_proof, admission_session):
            assert admitted_proof == case.proof
            assert isinstance(admission_session, entry.admission.ReferenceSession)
        def run(self):
            events.append('run_boundary_only')
            return False
    monkeypatch.setattr(entry, 'ResourceLibreOfficeEngine', Engine)
    monkeypatch.setattr(entry.cohort, 'DashboardServer', Dashboard)
    monkeypatch.setattr(entry.cohort, 'CohortCodex', LLM)
    monkeypatch.setattr(entry.admission, 'ScaledCapitalFactory', Factory)
    if engine_failure:
        with pytest.raises(RuntimeError, match='fixture engine setup failure'):
            entry.execute_prepared(case.output)
        assert 'LLM_fixture' not in events
    else:
        assert entry.execute_prepared(case.output) == 2
        assert events.index('engine') < events.index('LLM_fixture') < events.index('run_boundary_only')
    assert events[-1] == 'panel_stop' and tempfile.tempdir == previous_tmp
    assert json.loads((case.output / 'producer.lock').read_text())['status'] == 'released'
    with sqlite3.connect(case.output / 'run.sqlite') as database:
        run = json.loads(database.execute("select value from state where key='run'").fetchone()[0])
    assert run['producer_active'] is False
