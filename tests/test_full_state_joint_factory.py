"""Offline source dispatch and startup tests. No LO or model calls."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest
import yaml

from sheets_factory.pipelines import full_state_joint_factory as factory
from sheets_factory.task_adapters import full_state_joint_cohort as dispatch
from sheets_factory.task_adapters.public_workbook_scope import reference, write_new

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_mixed_quality_entry_test', ROOT / 'scripts/run_full_state_joint_quality.py')
entry = importlib.util.module_from_spec(spec); spec.loader.exec_module(entry)


def config(backend='semantic_graph_v3'):
    return {dispatch.SETTING: dispatch.setting(debug_backend=backend),
        factory.v3.SETTING: {'fixture': 'v3'}, factory.v2.JOINT_SETTING: {'fixture': 'v2'}}


def source(tmp_path, mode, backend='semantic_graph_v3', index=0):
    path = tmp_path / (mode + str(index) + '.xlsx')
    path.write_bytes(('Offline placeholder ' + mode + str(index)).encode())
    ref = reference(path); proof = {'workbook': ref, 'full_independent_audits': ['preserved']}
    seed = {'local_path': str(path), 'sha256': ref['sha256'], 'variant': 0, 'modes': [mode],
        'source_kind': factory.FM_KIND, 'finance_evidence': {'audited_source_binding': proof}}
    if mode == 'debugging':
        binding = {'financial_admission': {'path': 'offline-placeholder', 'sha256': 'offline'}}
        seed['finance_evidence']['full_graph_financial_admission'] = binding['financial_admission']
        if backend == 'semantic_graph_v3':
            seed.update(source_kind=factory.v3.SOURCE_KIND, semantic_graph_binding=binding,
                mutation_provider={'id': factory.v3.PROVIDER_ID})
            seed['finance_evidence'].update(semantic_graph_binding=binding,
                mutation_provider=seed['mutation_provider'], source_presentation_adapter=factory.v3.SOURCE_ADAPTER)
        else:
            seed.update(source_kind=factory.v2.SOURCE_KIND, scc_activity_binding=binding,
                task_adapter={'id': factory.v2.ADAPTER})
            seed['finance_evidence']['task_adapter'] = seed['task_adapter']
    return seed, proof


@pytest.mark.parametrize('backend', dispatch.BACKENDS)
def test_each_mode_uses_its_original_source_validator(tmp_path, monkeypatch, backend):
    cfg = config(backend); called = []
    fm, fm_proof = source(tmp_path, 'financial_modeling', backend)
    dbg, dbg_proof = source(tmp_path, 'debugging', backend)
    def validate_fm(seed): called.append(('FM', seed)); return fm_proof
    module = factory.v3 if backend == 'semantic_graph_v3' else factory.v2
    name = 'validate_seed' if backend == 'semantic_graph_v3' else 'validate_joint_seed'
    monkeypatch.setattr(module, name, lambda seed, setting: called.append(('DBG', seed)) or dbg_proof)
    assert factory.validate_seed(fm, cfg, validate_fm) == fm_proof
    assert factory.validate_seed(dbg, cfg, validate_fm) == dbg_proof
    assert [name for name, seed in called] == ['FM', 'DBG']


@pytest.mark.parametrize('case', ['flip_modes', 'both_modes', 'variant', 'source_hash', 'proof', 'source_kind'])
def test_fm_source_cannot_be_relabeled_or_lose_evidence(tmp_path, case):
    seed, proof = source(tmp_path, 'financial_modeling')
    if case == 'flip_modes': seed['modes'] = ['debugging']
    elif case == 'both_modes': seed['modes'] = ['financial_modeling', 'debugging']
    elif case == 'variant': seed['variant'] = True
    elif case == 'source_hash': seed['sha256'] = 'changed'
    elif case == 'proof': seed['finance_evidence']['audited_source_binding'] = {'workbook': {}}
    elif case == 'source_kind': seed['source_kind'] = factory.v3.SOURCE_KIND
    with pytest.raises(ValueError):
        factory.validate_seed(seed, config(), lambda seed: proof)


def test_complete20_admission_and_exact_normalization_paths(tmp_path, monkeypatch):
    cfg = config(); seeds = []
    for mode in factory.MODES:
        for index in range(10):
            seed, proof = source(tmp_path, mode, index=index); seeds.append(seed)
    monkeypatch.setattr(factory.FactoryPipeline, 'load_seeds', lambda self: deepcopy(seeds))
    monkeypatch.setattr(factory.v3, 'validate_seed', lambda seed, setting: seed['finance_evidence']['audited_source_binding'])
    instance = object.__new__(factory.FullStateJointFactory)
    instance.config, instance.backend, instance.targets = cfg, 'semantic_graph_v3', dict(entry.TARGETS)
    instance.fm_validator = lambda seed: seed['finance_evidence']['audited_source_binding']
    instance._admitted_paths = {}; events = []
    instance.audit = SimpleNamespace(emit=lambda *a, **kw: events.append((a, kw)))
    result = instance.load_seeds()
    assert len(result) == len(events) == len(instance._admitted_paths) == 20
    assert all(seed['survey']['normalized_path'] == seed['local_path'] for seed in result)
    assert all(event[1]['LO_calls'] == event[1]['model_calls'] == 0 for event in events)


def test_incomplete_pool_rejected_before_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(factory.FactoryPipeline, 'load_seeds', lambda self: [])
    instance = object.__new__(factory.FullStateJointFactory); instance.targets = dict(entry.TARGETS)
    with pytest.raises(ValueError, match='requires ten original FM'):
        instance.load_seeds()


@pytest.mark.parametrize('backend', dispatch.BACKENDS)
def test_repaired_dbg_claim_keeps_normal_target_path(monkeypatch, backend):
    plan = {'family_adapter': {'id': factory.v2.ADAPTER if backend == 'full_graph_v2' else factory.v3.PROVIDER_ID},
        'edits': [{'sheet': 'Model', 'cell': 'C3', 'before': '=1', 'after': '=2'}], 'mask_ranges': []}
    binding = {'scope_inventory': 'offline-inventory'}
    evidence = {'full_state_joint_source_binding': binding, 'semantic_graph_binding': binding}
    saved = {}
    ctx = SimpleNamespace(data={'plan': plan, 'finance_evidence': evidence},
        save=lambda name, value: saved.setdefault(name, value))
    monkeypatch.setattr(factory.v2, 'read', lambda value: {'offline': True})
    monkeypatch.setattr(factory.v2, 'validate_plan_binding', lambda *a: None)
    monkeypatch.setattr(factory.v3, 'validate_plan_binding', lambda *a: None)
    factory.normalize_debug_claim(ctx, backend)
    assert 'mask_ranges' not in ctx.data['plan'] and 'mask_ranges' in plan
    assert ctx.data['plan']['edits'] == plan['edits'] and len(saved) == 1


def test_phase_rechecks_source_and_baseline_bytes(tmp_path, monkeypatch):
    path = tmp_path / 'source.xlsx'; path.write_bytes(b'original')
    expected = reference(path)['sha256']
    instance = object.__new__(factory.FullStateJointFactory)
    instance._admitted_paths = {str(path.resolve()): expected}
    ctx = SimpleNamespace(source=path, data={'baseline': path, 'source_id': expected})
    monkeypatch.setattr(factory.FactoryPipeline, 'run_phase', lambda *a: {'normal': True})
    assert instance.run_phase(ctx, 'normalize') == {'normal': True}
    path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed after admission'):
        instance.run_phase(ctx, 'profile')


def test_incomplete_dbg_preparation_is_not_admitted(tmp_path, monkeypatch):
    monkeypatch.setattr(entry, 'support', lambda *a: SimpleNamespace(validate_completed=lambda path: {
        'kind': 'semantic_graph_v3_fixed_ten_engineering_seed_pool', 'status': 'running', 'count': 10}))
    with pytest.raises(ValueError, match='complete fixed-ten V3'):
        entry.debug_admission(tmp_path, 'semantic_graph_v3')


def test_lineage_uses_financial_admission_not_profile_annotation(tmp_path):
    financial = write_new(tmp_path / 'financial.json', {'original_source': {'sha256': 'actual-original'}})
    original = tmp_path / 'original.xlsx'; original.write_bytes(b'wrong original annotation')
    seed = {'original_source': reference(original), 'semantic_graph_binding': {'financial_admission': financial}}
    with pytest.raises(ValueError, match='lineage differs'):
        entry.original_source_sha(seed, 'semantic_graph_v3')


def test_cli_never_runs_implicitly(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(entry, 'validate_prepared', lambda path: called.append('validate') or ({}, {}))
    monkeypatch.setattr(entry, 'execute_prepared', lambda *a, **kw: pytest.fail('Unexpected services'))
    assert entry.main(['--prepared', str(tmp_path)]) == 0 and called == ['validate']
    with pytest.raises(ValueError, match='Prepare all twenty'):
        entry.main(['--run', '--output', str(tmp_path / 'new')])


def test_existing_database_blocks_services(tmp_path, monkeypatch):
    (tmp_path / 'run.sqlite').write_bytes(b'existing')
    monkeypatch.setattr(entry, 'validate_prepared', lambda path: ({}, {}))
    monkeypatch.setattr(entry.cohort, 'prepared_host_runtime', lambda path: ({}, False))
    class Host:
        def __enter__(self): return {'temporary_directory': str(tmp_path)}
        def __exit__(self, *a): return False
    monkeypatch.setattr(entry.cohort, 'host_temporary_environment', lambda *a, **kw: Host())
    monkeypatch.setattr(entry.cohort, 'ProducerLease', lambda *a: pytest.fail('Lease should not be acquired'))
    with pytest.raises(ValueError, match='existing producer'):
        entry.execute_prepared(tmp_path)


def test_failed_audit_creation_releases_lease(tmp_path, monkeypatch):
    cfg = {'agents': {'model': 'gpt-6-sol', 'reasoning_effort': 'high'}}
    monkeypatch.setattr(entry, 'validate_prepared', lambda path: ({}, cfg))
    monkeypatch.setattr(entry.cohort, 'prepared_host_runtime', lambda path: ({}, False))
    class Host:
        def __enter__(self): return {'temporary_directory': str(tmp_path)}
        def __exit__(self, *a): return False
    monkeypatch.setattr(entry.cohort, 'host_temporary_environment', lambda *a, **kw: Host())
    released = []
    lease = SimpleNamespace(acquire=lambda: lease, release=lambda: released.append(True))
    monkeypatch.setattr(entry.cohort, 'ProducerLease', lambda *a: lease)
    monkeypatch.setattr(entry.cohort, 'AuditStore', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('audit failed')))
    with pytest.raises(RuntimeError, match='audit failed'):
        entry.execute_prepared(tmp_path)
    assert released == [True]


def test_definition_equivalence_preserves_formula_and_date_meaning(tmp_path):
    book = openpyxl.Workbook(); book.active.title = 'Model'
    book.active['A1'] = 1; book.active['B1'] = '=A1+1'
    original, changed = tmp_path / 'original.xlsx', tmp_path / 'changed.xlsx'
    book.save(original); book.active['B1'] = '=A1+2'; book.save(changed); book.close()
    assert factory._definition_state(original) != factory._definition_state(changed)


def test_preparation_feeds_actual_factory_manifest_loader_without_services(tmp_path, monkeypatch):
    """Exercise the real seed-document contract, not a mocked Factory loader."""
    fm_dir = tmp_path / 'fm'; fm_dir.mkdir()
    fm, dbg = [], []
    for index in range(10):
        first, _ = source(tmp_path, 'financial_modeling', index=index)
        first['profile_id'] = 'C' + str(index)
        fm.append(first)
        second, _ = source(tmp_path, 'debugging', index=index)
        second['semantic_graph_binding']['financial_admission'] = write_new(
            tmp_path / ('financial-' + str(index) + '.json'), {'original_source': {'sha256': first['sha256']}})
        second['finance_evidence']['full_graph_financial_admission'] = second['semantic_graph_binding']['financial_admission']
        dbg.append(second)
    fm_order = [seed['sha256'] for seed in fm]
    seed_ref = write_new(fm_dir / 'seed_manifest.json', {'selected': fm})
    batch_ref = write_new(fm_dir / 'batch.json', {'selected': fm, 'model_scores_consulted': False})
    priority = write_new(fm_dir / 'priority.json', {'sources': {key: {} for key in fm_order}, 'tasks': {}})
    base = {'run': {'targets': dict(entry.TARGETS), 'max_candidates_per_seed': 1,
                    'max_steps': 3, 'max_evidence_rounds_per_revision': 2,
                    'infrastructure_retries_per_stage': 2, 'max_additional_trials_per_revision': 0},
        'agents': {'model': 'gpt-6-sol', 'reasoning_effort': 'high'}, 'construction': {},
        'diagnosis': {'selection': {'include': 'all', 'exclude': []}},
        'recovery': {'compiler_backend': 'composite_journal'}, 'harbor': {'execute_controls': True},
        'public_input_priority': {'version': 1, 'manifest': priority}}
    (fm_dir / 'resolved_config.yaml').write_text(yaml.safe_dump(base))
    write_new(fm_dir / 'preflight_manifest.json', {'kind': 'prepared_normal_quality_cohort',
        'mode': 'financial_modeling', 'source_count': 10, 'prepared_seed_manifest': seed_ref,
        'source_batch_manifest': batch_ref, 'recipe_sha256': {}, 'source_artifacts_sha256': {}})
    offline = write_new(tmp_path / 'offline.json', {
        'kind': 'prospective_full_state_FM_fixed_ten_offline_admission', 'source_selection_order': fm_order,
        'all_ten_financial_target_sets_preserved_exactly': True,
        'all_13854_added_states_per_source_originally_audited_and_publicly_recomputable': True})
    pilot = write_new(tmp_path / 'pilot.json', {'physical_missing_formula_count': 60193,
        'tasks': [{'source_id': fm_order[0], 'task_id': 'fm-first'}]})
    monkeypatch.setattr(entry, 'debug_admission', lambda *a: ({}, dbg, {'offline': 'fixture'}))
    monkeypatch.setattr(factory, 'validate_seed', lambda seed, *a: seed['finance_evidence']['audited_source_binding'])
    output = tmp_path / 'mixed'
    frozen = entry.prepare(fm_dir, tmp_path / 'debug', output, debug_backend='semantic_graph_v3',
        offline_admission=offline['path'], pilot_probe=pilot['path'])
    receipt, cfg = entry.validate_prepared(output)
    assert frozen['sha256'] == reference(output / 'preflight_manifest.json')['sha256']
    assert receipt['new_LO_calls'] == receipt['new_model_calls'] == 0
    assert receipt['original_FM_source_order'] == receipt['DBG_original_source_order'] == fm_order
    assert all(entry.read_ref(cfg[name]['manifest'])['tasks'] == {}
               for name in ('public_input_priority', 'public_workbook_scope'))
    instance = object.__new__(factory.FactoryPipeline)
    instance.config, instance.targets = cfg, dict(entry.TARGETS)
    updates = []
    instance.audit = SimpleNamespace(update_run=lambda **kw: updates.append(kw))
    seeds = instance.load_seeds()
    assert [seed['sha256'] for seed in seeds] == fm_order + [seed['sha256'] for seed in dbg]
    assert updates[0]['discovered_sources'] == updates[0]['selected_sources'] == 20
    assert cfg['run']['source_ordering'] == 'manifest' and cfg['run']['max_candidates_per_seed'] == 1
