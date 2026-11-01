"""Pure regression for historical provenance versus current causal providers."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from sheets_factory.task_adapters import operating_reports_200_quality_revision2 as nodes
from sheets_factory.workbook.linear_capital_ringfenced_group import contract as files

pipeline = nodes.pipeline
ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def entry_module():
    return load('scripts/run_operating_reports_200_quality_revision2.py', '_test_fixed200_normal_revision2_entry')


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    legacy = load('tests/test_operating_reports_200_quality.py', '_revision2_original_test_helpers')
    monkeypatch.setattr(legacy, 'pipeline', pipeline)
    monkeypatch.setattr(legacy, 'nodes', nodes)
    monkeypatch.setattr(legacy, 'entry_module', entry_module)
    f = legacy.mocked_cold_boundary.__wrapped__(tmp_path, monkeypatch)
    return f, legacy


def replace_probe(f, change, monkeypatch):
    value = files.read(f.dev_ref); change(value)
    updated = files.write(Path(f.dev_ref['path']).with_name('probe_revision2.json'), value)
    monkeypatch.setattr(pipeline, 'DEV_PROBE', Path(updated['path']))
    monkeypatch.setattr(pipeline, 'DEV_PROBE_SHA', updated['sha256'])
    f.dev_ref = updated
    return updated


def test_documentary_history_drift_is_retained_but_not_a_live_provider(fixture, tmp_path, monkeypatch):
    f, _ = fixture
    provider = tmp_path/'old_provider.py'; provider.write_text('old historical implementation\n')
    stale = files.reference(provider)
    historical = files.write(tmp_path/'historical_receipt.json', {'recipe': {'provider': stale}})
    dev = replace_probe(f, lambda value: value.update(selection_history_inventory=[historical]), monkeypatch)
    provider.write_text('a later unrelated implementation\n')
    # This is the exact old traversal failure, with every historical JSON intact.
    with pytest.raises(ValueError, match='bound artifact changed'):
        pipeline.References().discover(dev)
    value = pipeline.OperatingReportsAdmission(f.actual_ref)
    proof = pipeline.admission(value); scope = proof['dependency_scope']
    assert proof['version'] == 2 and proof['kind'].endswith('_revision2')
    assert scope['historical_snapshot'] == dev
    assert scope['consumed_leaf_refs'] == {key: f.dev['modes']['financial_modeling'][key] for key in nodes.CONSUMED_DEVELOPMENT_KEYS}
    assert str(provider) not in value.references.files
    assert historical['path'] not in value.references.files
    assert json.loads(files.checked(dev).read_text())['selection_history_inventory'] == [historical]
    assert scope['genuine_current_task_source_discovery_unchanged'] is True
    assert scope['genuine_current_task_source_root'] == f.actual_ref
    assert len(f.cold_calls) == 1
    assert set(nodes.ANCESTORS) <= set(scope['current_recipe_sha256'])
    assert all(row['path'] != str(provider) for row in scope['current_guarded_artifacts'])
    # Its complete snapshot bytes remain a current guard despite scoped traversal.
    Path(dev['path']).write_text('{}')
    with pytest.raises(ValueError, match='bound artifact changed'):
        pipeline.admission(value)


@pytest.mark.parametrize('when', ['before', 'after'])
def test_current_causal_provider_drift_still_rejects(fixture, tmp_path, monkeypatch, when):
    f, _ = fixture
    provider = tmp_path/'current_provider.py'; provider.write_text('current source code\n')
    causal = files.reference(provider)
    actual = files.read(f.actual_ref); actual['current_provider'] = causal
    f.actual_ref = files.write(Path(f.actual_ref['path']).with_name('task_terminal_revision2.json'), actual)
    monkeypatch.setattr(pipeline, 'TERMINAL_SHA', f.actual_ref['sha256'])
    if when == 'before':
        provider.write_text('changed causal code\n')
        with pytest.raises(ValueError, match='bound artifact changed'):
            pipeline.OperatingReportsAdmission(f.actual_ref)
    else:
        value = pipeline.OperatingReportsAdmission(f.actual_ref)
        assert causal in value.proof['dependency_scope']['current_guarded_artifacts']
        provider.write_text('changed causal code\n')
        with pytest.raises(ValueError, match='bound artifact changed'):
            pipeline.admission(value)


@pytest.mark.parametrize('key', ['input', 'goal', 'original_instruction', 'rendered_instruction'])
def test_every_consumed_first_material_leaf_is_guarded(fixture, key):
    f, _ = fixture
    value = pipeline.OperatingReportsAdmission(f.actual_ref)
    record = f.dev['modes']['financial_modeling'][key]
    Path(record['path']).write_bytes(b'material drift')
    with pytest.raises(ValueError, match='bound artifact changed'):
        pipeline.admission(value)


def test_material_identity_cannot_be_rebound_via_documentary_boundary(fixture, monkeypatch):
    f, _ = fixture
    replace_probe(f, lambda value: value['modes']['financial_modeling']['material_task_version'].update(sha256='0'*64), monkeypatch)
    with pytest.raises(ValueError, match='first-v6 input'):
        pipeline.OperatingReportsAdmission(f.actual_ref)


def test_no_actual_discovery_or_large_interpreted_payload_is_removed(fixture, monkeypatch):
    f, _ = fixture; calls = []
    original = pipeline.References.discover
    def observe(self, record):
        calls.append(record); return original(self, record)
    monkeypatch.setattr(pipeline.References, 'discover', observe)
    value = pipeline.OperatingReportsAdmission(f.actual_ref)
    assert calls[0] == f.actual_ref and f.dev_ref not in calls
    for key in ('definition','source_definition','expected','bindings','specification','candidate_preparation'):
        assert f.prepared[key]['path'] in value.references.files
    assert value.proof['instruction'] == f.rendered
    assert value.proof['original_business_instruction'] == f.business


@pytest.mark.parametrize('name', [
    'test_cold_failure_is_not_a_stored_pass_or_zero_service_admission',
    'test_in_memory_evidence_and_proof_mutations_are_rejected',
    'test_exact_private_plan_keeps_all_masked_forecasts_and_public_brief_unchanged',
])
def test_unchanged_boundary_regressions(fixture, name):
    f, legacy = fixture; getattr(legacy, name)(f)


@pytest.mark.parametrize('problem', ['v1','failed','partial','scope','full_D','controls','brief','input'])
def test_original_material_and_engineering_negative_gates(fixture, problem):
    f, legacy = fixture
    legacy.test_rejects_wrong_family_partial_proof_or_changed_first_material(f, problem)


def test_factory_nodes_and_receipt_protocol_share_only_new_private_globals(fixture, tmp_path, monkeypatch):
    f, legacy = fixture
    legacy.test_all_twelve_default_checks_and_reference_policy_are_retained(tmp_path)
    legacy.test_diagnose_reuses_strict_receipt_body_after_new_context_gate(f, tmp_path, monkeypatch)
    legacy.test_unchanged_strict_receipt_schema_rejects_stale_binding_not_financial_scores()
    legacy.test_content_repair_cannot_silently_change_spent_first_attempt(f, tmp_path)
    assert pipeline._LIVE is not nodes.old_pipeline._LIVE
    assert pipeline.OperatingReportsAdmission is not nodes.old_pipeline.OperatingReportsAdmission
    assert pipeline.NativeQualityFactory.run_phase.__code__ is nodes.old_pipeline.NativeQualityFactory.run_phase.__code__
    assert pipeline.NativeQualityFactory.run_phase.__globals__ is pipeline.__dict__
    assert nodes.NormalizeNode.execute.__code__ is nodes.old_nodes.NormalizeNode.execute.__code__
    assert nodes.NormalizeNode.execute.__globals__ is not nodes.old_nodes.NormalizeNode.execute.__globals__


@pytest.mark.parametrize('change', ['missing_check','other_policy','nop_disabled','DBG','model','memory','filter'])
def test_original_configuration_cannot_be_weakened(fixture, tmp_path, change):
    _, legacy = fixture; legacy.test_config_cannot_reduce_quality_or_switch_materials(tmp_path, change)


@pytest.mark.parametrize('cleanup_ok', [True, False])
def test_same_three_actual_controls_and_fail_closed_cleanup(fixture, tmp_path, monkeypatch, cleanup_ok):
    f, legacy = fixture
    legacy.test_current_normal_controls_run_exactly_three_native_calls_and_reuse_no_clear_flags(f,tmp_path,monkeypatch,cleanup_ok)


def test_strict_export_gate_precedes_unchanged_harbor_resources(fixture, tmp_path, monkeypatch):
    f, legacy = fixture
    monkeypatch.setitem(nodes._node_ns, '_export', lambda *args: pytest.fail('No export after rejected quality'))
    monkeypatch.setitem(nodes._node_ns, 'validate_reference_export', lambda _: (_ for _ in ()).throw(ValueError('Missing supported Q01-Q04 or all12')))
    legacy.test_export_enforces_all_supported_reference_checks_before_export(f,tmp_path,monkeypatch)
    entry = entry_module()
    assert entry.execute_prepared.__code__ is entry._base.execute_prepared.__code__
    assert entry._gate_replacements == ['strict_trial_agent_identity']
    assert entry.validate_normal_resources.__globals__ is entry._namespace
    assert entry.KIND.endswith('_revision2')
    for path, sha in nodes.ANCESTORS.items(): assert entry.recipes(legacy.configuration(tmp_path),[])[path] == sha


def test_zero_service_prepare_and_fresh_process_replay_use_new_live_gate(fixture, tmp_path, monkeypatch):
    f, legacy = fixture
    legacy.test_zero_service_preflight_keeps_exact_single_FM_inventory_and_real_cold_replay(f,tmp_path,monkeypatch)


@pytest.mark.parametrize('operation', ['prepare','validate','run'])
def test_panel_starts_before_any_long_cold_work(fixture, tmp_path, monkeypatch, operation):
    _, legacy = fixture
    legacy.test_monitor_panel_and_lease_start_before_cold_admission(tmp_path,monkeypatch,operation)


def test_all_frozen_ancestors_stay_exact():
    for path, sha in nodes.ANCESTORS.items(): assert files.reference(path)['sha256'] == sha
    entry = entry_module()
    assert files.reference(entry.FROZEN_ENTRY)['sha256'] == entry.FROZEN_ENTRY_SHA
    assert nodes.old_pipeline.REGISTRY != pipeline.REGISTRY


@pytest.fixture
def resource_run(tmp_path, monkeypatch):
    legacy = load('tests/test_heterogeneous_native_quality.py', '_revision2_resource_test_helpers')
    r = legacy.resource_run.__wrapped__(tmp_path, monkeypatch)
    checker = r.runner.validate_trial_observations
    r.runner = entry_module()
    monkeypatch.setitem(r.runner._namespace, 'validate_trial_observations', checker)
    monkeypatch.setattr(r.runner, 'validate_trial_observations', checker, raising=False)
    for path in r.results:
        result = json.loads(path.read_text()); agent = result['agent_info']['name']
        original = {'task': {**result['config']['task'], 'source': 'SpreadsheetEval'},
            'trial_name': path.parent.name, 'trials_dir': str(path.parent.parent), 'job_id': 'job-'+agent}
        rich = {**deepcopy(original), 'agent': {'name': agent}, 'extra_unconsumed_default': None}
        if agent == 'nop': original['agent'] = {'name': 'nop'}
        path.with_name('config.json').write_text(json.dumps(original))
        result['config'] = rich; path.write_text(json.dumps(result))
    return r, legacy


def test_sparse_oracle_and_explicit_nop_both_retain_real_resource_gate(resource_run):
    r, legacy = resource_run
    before = {str(p): p.read_bytes() for p in r.results for p in (p,p.with_name('config.json'))}
    legacy.test_actual_resource_wrapper_binds_both_roles_to_the_fixed_staged_export(r)
    assert before == {str(p): p.read_bytes() for p in r.results for p in (p,p.with_name('config.json'))}


@pytest.mark.parametrize('change', ['missing_observer','actual_role_mismatch','wrong_stage','wrong_agent','wrong_reward'])
def test_same_resource_rejections_with_sparse_trial_metadata(resource_run, monkeypatch, change):
    r, legacy = resource_run
    if change == 'actual_role_mismatch':
        monkeypatch.setitem(r.runner._namespace, 'validate_trial_observations', lambda *a,**k: {'passed':False,'complete':False})
    legacy.test_resource_gap_withdraws_acceptance_and_preserves_raw_rewards(r,monkeypatch,change)


@pytest.mark.parametrize('problem', ['thin_task','rich_task','task_source','thin_trial','rich_trial','result_trial',
    'thin_trials_dir','rich_trials_dir','physical_trial','job_id','missing_job','rich_agent','agent_info','thin_agent'])
def test_identity_compatibility_is_fail_closed_for_every_binding(resource_run, problem):
    r, _ = resource_run; result_path = r.results[0]; config_path = result_path.with_name('config.json')
    thin = json.loads(config_path.read_text()); result = json.loads(result_path.read_text()); rich = result['config']
    if problem == 'thin_task': thin['task']['path'] = '/other/task'
    elif problem == 'rich_task': rich['task']['path'] = '/other/task'
    elif problem == 'task_source': rich['task']['source'] = 'another source'
    elif problem == 'thin_trial': thin['trial_name'] = 'another_trial'
    elif problem == 'rich_trial': rich['trial_name'] = 'another_trial'
    elif problem == 'result_trial': result['trial_name'] = 'another_trial'
    elif problem == 'thin_trials_dir': thin['trials_dir'] = '/other/jobs'
    elif problem == 'rich_trials_dir': rich['trials_dir'] = '/other/jobs'
    elif problem == 'physical_trial':
        for obj in (thin,rich,result): obj['trial_name'] = 'same_but_wrong_physical_trial'
    elif problem == 'job_id': rich['job_id'] = 'other-job'
    elif problem == 'missing_job': thin.pop('job_id')
    elif problem == 'rich_agent': rich['agent']['name'] = 'nop'
    elif problem == 'agent_info': result['agent_info']['name'] = 'nop'
    else: thin['agent'] = {'name':'nop'}
    config_path.write_text(json.dumps(thin)); result_path.write_text(json.dumps(result))
    before = result_path.read_bytes()
    report = r.runner.validate_normal_resources(r.out,r.audit,r.observer)
    assert report['passed'] is False and report['infrastructure_task_ids'] == ['unit-task']
    assert result_path.read_bytes() == before and not r.original.exists()
    assert report['missing_evidence_is_not_model_zero'] is True


@pytest.mark.parametrize('relative', [
    'oracle-controls-95230943c872/fm-08f2adb105de__rbkFuhy',
    'oracle-controls-95230943c872/dbg-08f2adb105de__GjKBRi5',
    'nop-controls-95230943c872/fm-08f2adb105de__7QA4MYe',
    'nop-controls-95230943c872/dbg-08f2adb105de__xYJNxwd',
])
def test_retained_actual_original_sparse_and_rich_identity_fixture(relative):
    entry = entry_module()
    folder = ROOT/'outputs/research/linear_scaled_P01_reference_receipt_normal_prepared_20261031T195500Z/prepared/harbor_jobs/2ca1afeb342b'/relative
    thin = json.loads((folder/'config.json').read_text()); raw = json.loads((folder/'result.json').read_text())
    # Retain only identity fields for this fixture; never display environment or agent arguments.
    rich = {key:deepcopy(raw['config'][key]) for key in ('task','trial_name','trials_dir','job_id')}
    rich['agent'] = {'name': raw['config']['agent']['name']}
    result = {'config':rich,'trial_name':raw['trial_name'],'agent_info':{'name':raw['agent_info']['name']}}
    wanted = 'oracle' if relative.startswith('oracle') else 'nop'
    assert ('agent' in thin) is (wanted == 'nop')
    assert entry._trial_agent_identity(thin,result,folder/'config.json',Path(thin['task']['path']),wanted) == wanted
