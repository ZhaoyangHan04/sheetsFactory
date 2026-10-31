"""New opt-in routing only; genuine admissions are exercised with pure fixtures."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from sheets_factory.checkers import DiagnosisRunner
from sheets_factory.nodes import quality
from sheets_factory.task_adapters.reference_receipt_diagnosis import ReferenceReceiptDiagnosisNode
from test_linear_capital_scaled_reference_quality import completed_view
from test_linear_capital_scaled_quality import provider, completed_view as legacy_completed_view

ROOT = Path(__file__).resolve().parents[1]


def entry():
    spec = importlib.util.spec_from_file_location('_receipt_quality_entry_test',
        ROOT/'scripts/run_linear_capital_scaled_receipt_quality.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def configuration(module):
    config = yaml.safe_load(module.DEFAULT_CONFIG.read_text())
    config.update(project_root=str(ROOT), pipeline={'node_registry': str(module.REGISTRY)},
        recovery={'compiler_backend': 'reference_review', 'public_solver_required': False,
            'public_solver_attempted': False})
    config[module.adapter.SETTING] = module.adapter.setting()
    return config


def test_only_diagnose_route_changes_and_original_opaque_types_and_code_remain():
    module = entry(); config = configuration(module)
    old = yaml.safe_load(module._original_adapter.REGISTRY.read_text())['nodes']
    new = yaml.safe_load(module.REGISTRY.read_text())['nodes']
    assert old.keys() == new.keys() and [key for key in old if old[key] != new[key]] == ['diagnose']
    assert module.pipeline.LinearSourceAdmission is module._original_pipeline.LinearSourceAdmission
    assert module.pipeline.LinearViewAdmission is module._original_pipeline.LinearViewAdmission
    factory = module.pipeline.LinearCapitalQualityFactory
    original = module._original_pipeline.LinearCapitalQualityFactory
    assert factory.__init__.__code__ is original.__init__.__code__
    assert factory.__init__.__globals__ is not original.__init__.__globals__
    assert original.__init__.__globals__['validate_configuration'] is module._original_pipeline.validate_configuration
    for method in ('run', 'load_seeds', 'run_phase', '_claim_targets'):
        assert getattr(factory, method) is getattr(original, method)
    assert module.execute_prepared.__code__ is module._upstream.execute_prepared.__code__
    assert module._namespace['validate_normal_resources'].__code__ is module._upstream.validate_normal_resources.__code__
    assert module.validate_configuration(config)['id'] == 'entity_group_large_v2'
    assert set(DiagnosisRunner(ROOT).resolve(config)['enabled_check_ids']) == {f'Q{i:02d}' for i in range(1,13)}
    # The original adapter setting retains its actual old implementation binding;
    # the separate new registry is explicit, not disguised as the old registry.
    assert config[module.adapter.SETTING]['node_registry']['path'] == str(module._original_adapter.REGISTRY)
    assert config['pipeline']['node_registry'] == str(module.REGISTRY)


@pytest.mark.parametrize('change', ['wrong_registry', 'old_history_inherited', 'missing_Q12', 'no_Harbor', 'wrong_CPU'])
def test_new_configuration_rejects_any_additional_relaxation(change):
    module = entry(); config = configuration(module)
    if change == 'wrong_registry': config['pipeline']['node_registry'] = str(module._original_adapter.REGISTRY)
    elif change == 'old_history_inherited': config['reference_receipt_revision']['prior_normal_clear_or_qualified_inherited'] = True
    elif change == 'missing_Q12': config['diagnosis']['selection']['include'].remove('Q12')
    elif change == 'no_Harbor': config['harbor']['execute_controls'] = False
    else: config['agents']['container_cpus'] = 16
    with pytest.raises(ValueError): module.validate_configuration(config)


def test_registry_rejects_a_second_node_change(monkeypatch, tmp_path):
    module = entry(); value = yaml.safe_load(module.REGISTRY.read_text())
    value['nodes']['precheck'] = value['nodes']['diagnose']
    changed = tmp_path/'invalid_registry.yaml'; changed.write_text(yaml.safe_dump(value))
    monkeypatch.setattr(module, 'REGISTRY', changed)
    with pytest.raises(ValueError, match='Only the explicitly checked'):
        module.validate_registry()


def test_zero_service_preparation_cold_reload_and_factory_load_new_node(completed_view, tmp_path, monkeypatch):
    module = entry(); _, source, terminal, _, _ = completed_view
    # Existing tiny source fixture has an intentionally fake resource profile.
    # Actual configuration/resource rejection is tested above; no service runs.
    monkeypatch.setattr(module._original_pipeline, 'validate_configuration', lambda config: {'fixture': True})
    monkeypatch.setattr(module, 'execute_prepared', lambda *a, **k: pytest.fail('No services'))
    out = tmp_path/'fresh_receipt_quality'
    record = module.prepare(source.source_manifest, terminal, out,
        source_provider='fixture', provider_registry=source.providers.reference)
    module._PREPARED_SESSIONS.clear()
    frozen, config, admissions = module.validate_prepared(out)
    assert record == module.reference(out/'preflight_manifest.json') and frozen['kind'] == module.KIND
    assert frozen['qualified'] is False and frozen['prior_source_or_task_quality_transferred'] is False
    assert frozen['existing_development_score_transferred'] is False
    assert all(frozen[key] == 0 for key in ('actual_models', 'actual_LO_calls', 'actual_solver_calls', 'actual_Harbor_jobs'))
    assert not (out/'run.sqlite').exists() and not (out/'started.json').exists()
    mapping = frozen['recipe_sha256']
    assert all(str(path) in mapping for path in (module.REGISTRY, module.DEFAULT_CONFIG,
        module.UPSTREAM, Path(module.__file__), Path(module.receipt_node.__file__), module._original_adapter.REGISTRY))
    assert all(record['path'] in mapping for record in config['reference_receipt_revision']['prior_evidence'])
    assert config['reference_receipt_revision']['retained_undispatched_profiles'] == [
        'L360-P07','L360-P09','L360-P10','L360-P14','L360-P16','L360-P17','L360-P18','L360-P20']
    factory = module.pipeline.LinearCapitalQualityFactory(config, SimpleNamespace(), None,
        SimpleNamespace(), admissions=admissions)
    assert type(factory.load_node('diagnose')) is ReferenceReceiptDiagnosisNode
    assert type(factory.load_node('independent_recovery')) is quality.RecoveryNode
    assert type(factory.load_node('trajectory')) is quality.TrajectoryNode
    assert factory.templates['financial_modeling']['phases']['revision'] == [
        'construct','instruction','precheck','independent_recovery','trajectory','diagnose']


def test_cli_does_not_start_services_during_preparation(tmp_path):
    module = entry()
    with pytest.raises(ValueError, match='Prepare and review'):
        module.main(['--source-manifest', 'source', '--validation-terminal', 'terminal',
            '--output', str(tmp_path/'forbidden'), '--run'])
    assert not (tmp_path/'forbidden').exists()
