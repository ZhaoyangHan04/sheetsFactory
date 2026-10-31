"""N360 reference-review gates with explicit mock source/reviewer boundaries."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from sheets_factory.nodes import quality
from sheets_factory.pipelines import linear_capital_scaled_reference_review as pipeline
from sheets_factory.pipelines import linear_capital_scaled_quality as original_pipeline
from sheets_factory.task_adapters import linear_capital_scaled_reference_review as adapter
from sheets_factory.checkers import DiagnosisRunner
from test_linear_capital_scaled_quality import provider, completed_view
from test_reference_evidence_policy import context as reference_context, diagnose, workbook
from test_heterogeneous_native_quality import resource_run

ROOT=Path(__file__).resolve().parents[1]


def entry():
    descriptor=importlib.util.spec_from_file_location('_scaled_reference_quality_entry_tests',ROOT/'scripts/run_linear_capital_scaled_reference_quality.py')
    module=importlib.util.module_from_spec(descriptor);descriptor.loader.exec_module(module)
    return module


@pytest.fixture
def configuration():
    config=yaml.safe_load((ROOT/'config/pipelines/linear_capital_scaled_reference_quality_v1.yaml').read_text())
    config.update(project_root=str(ROOT),pipeline={'node_registry':str(adapter.REGISTRY)},
        recovery={'compiler_backend':'reference_review','public_solver_required':False,'public_solver_attempted':False})
    config[adapter.SETTING]=adapter.setting()
    return config


def test_new_route_preserves_opaque_admissions_and_all_twelve_normal_checks(configuration):
    assert pipeline.LinearSourceAdmission is original_pipeline.LinearSourceAdmission
    assert pipeline.LinearViewAdmission is original_pipeline.LinearViewAdmission
    assert hashlib.sha256(Path(original_pipeline.__file__).read_bytes()).hexdigest()==pipeline.UPSTREAM_SHA256
    pipeline.adapted_ast();adapter.adapted_ast()
    assert pipeline.validate_configuration(configuration)['id']=='entity_group_large_v2'
    setting=adapter.validate_setting(configuration[adapter.SETTING])
    assert setting['reference_evidence_policy']=='reference_review' and setting['independent_public_recovery'] is False
    resolved=DiagnosisRunner(ROOT).resolve(configuration)
    assert set(resolved['enabled_check_ids'])=={f'Q{i:02d}' for i in range(1,13)}
    nodes=yaml.safe_load(adapter.REGISTRY.read_text())['nodes']
    assert len(nodes)==11 and nodes['independent_recovery']=='sheets_factory.nodes.quality:RecoveryNode'
    assert nodes['trajectory']=='sheets_factory.nodes.quality:TrajectoryNode'
    assert nodes['export'].endswith('linear_capital_scaled_reference_review:LinearExportNode')


@pytest.mark.parametrize('change',['skip_Q04','wrong_policy','public_solver','weaker_model','weaker_effort','wrong_cpus','skip_Harbor'])
def test_configuration_cannot_weaken_review_models_resources_or_checks(configuration,change):
    if change=='skip_Q04':configuration['diagnosis']['selection']['exclude']=['Q04']
    elif change=='wrong_policy':configuration['diagnosis']['reference_evidence_policy']='independent_public_recovery'
    elif change=='public_solver':configuration['recovery']['public_solver_required']=True
    elif change=='weaker_model':configuration['agents']['model']='another'
    elif change=='weaker_effort':configuration['agents']['reasoning_effort']='low'
    elif change=='wrong_cpus':configuration['agents']['container_cpus']=16
    else:configuration['harbor']['execute_controls']=False
    with pytest.raises(ValueError):pipeline.validate_configuration(configuration)


def test_ordinary_recovery_honestly_skips_public_solver_without_any_backend(reference_context):
    assert reference_context.llm.calls==[]
    result=quality.RecoveryNode().execute(reference_context)['recovery']
    assert result['status']=='not_applicable' and result['skipped'] is True
    assert result['verified'] is False and result['public_information_only'] is False
    assert result['usage_calls']==[] and reference_context.llm.calls==[]
    assert not (reference_context.revision_dir/'private/recovery_attempts').exists()


def test_current_supported_Q01_Q04_review_passes_the_real_export_guard(reference_context):
    report=diagnose(reference_context);reference_context.data['diagnosis']=report
    assert report['releasable'] and report['reference_review']['passed']
    assert adapter.validate_reference_export(reference_context)['passed'] is True
    assert report['reference_review']['independent_public_recovery'] is False
    with pytest.raises(ValueError,match='never accepts'):
        adapter.valid_linear_capital_recovery_witness(reference_context,{'verified':True})


@pytest.mark.parametrize('change',['not_releasable','stale_binding','stale_receipt','disabled_Q12','unsupported_Q01','unsupported_Q04','mandatory_gate','witness_only','changed_goal'])
def test_export_refuses_stale_unreleasable_or_witness_only_evidence(reference_context,change):
    report=diagnose(reference_context);reference_context.data['diagnosis']=report
    if change=='not_releasable':report['releasable']=False
    elif change=='stale_binding':report['reference_binding']={'previous_revision':True}
    elif change=='stale_receipt':report['reference_review']['binding']={'previous_revision':True}
    elif change=='disabled_Q12':report['enabled_check_ids'].remove('Q12')
    elif change=='unsupported_Q01':report['assessments']['Q01']['state']='unknown'
    elif change=='unsupported_Q04':report['assessments']['Q04']['evidence']=[]
    elif change=='mandatory_gate':report['mandatory_gates']['reference_review']['passed']=False
    elif change=='witness_only':reference_context.data['diagnosis']={'releasable':True,'independent_recovery':{'verified':True}}
    else:workbook(reference_context.data['goal'],999)
    with pytest.raises(ValueError):adapter.validate_reference_export(reference_context)


def test_zero_service_preparation_needs_no_public_runtime_and_cold_guards_exact_view(completed_view,tmp_path,monkeypatch):
    module=entry();_,source,terminal,_,_=completed_view
    # The source fixture deliberately carries a fake profile. Real profile/configuration
    # guards are exercised above; this test isolates the existing opaque admission seam.
    monkeypatch.setattr(pipeline,'validate_configuration',lambda config:{'TEST_ONLY_source_profile':True})
    monkeypatch.setattr(module,'execute_prepared',lambda *a,**k:pytest.fail('No actual services in preparation'))
    output=tmp_path/'normal_reference';record=module.prepare(source.source_manifest,terminal,output,
        source_provider='fixture',provider_registry=source.providers.reference)
    module._PREPARED_SESSIONS.clear()
    frozen,config,admissions=module.validate_prepared(output)
    assert module.reference(output/'preflight_manifest.json')==record
    assert frozen['public_runtime_preparation'] is None and frozen['count']==1 and frozen['qualified'] is False
    assert all(frozen[k]==0 for k in ('actual_models','actual_LO_calls','actual_solver_calls','actual_Harbor_jobs','task_count'))
    assert config['recovery']=={'compiler_backend':'reference_review','public_solver_required':False,'public_solver_attempted':False}
    assert not (output/'run.sqlite').exists()
    assert str(module.RESOURCE_GATE) in frozen['recipe_sha256']
    assert str(Path(adapter.__file__)) in frozen['recipe_sha256']
    factory=pipeline.LinearCapitalQualityFactory(config,SimpleNamespace(),None,SimpleNamespace(),admissions=admissions)
    assert factory.templates['financial_modeling']['phases']['revision']==['construct','instruction','precheck','independent_recovery','trajectory','diagnose']
    assert factory.load_node('independent_recovery').__class__ is quality.RecoveryNode
    assert factory.load_node('trajectory').__class__ is quality.TrajectoryNode
    assert factory.load_node('diagnose').__class__.__module__==adapter.__name__
    with pytest.raises(TypeError,match='public_runtime_preparation'):
        module.prepare(source.source_manifest,terminal,tmp_path/'forbidden_runtime',
            public_runtime_preparation={'verified':True})


def test_real_adopted_resource_gate_requires_both_roles(resource_run,monkeypatch):
    module=entry();r=resource_run;monkeypatch.setattr(module,'_resource_gate',r.runner)
    result=module.validate_normal_resources(r.out,r.audit,r.observer)
    assert result['passed'] and result['qualified_tasks_checked']==1 and len(r.calls)==2
    assert r.audit.snapshot()['tasks'][0]['control_observation_receipts']=={'oracle':[r.observer],'nop':[r.observer]}


def test_missing_actual_resources_withdraws_acceptance_without_rewriting_reward(resource_run,monkeypatch):
    module=entry();r=resource_run;monkeypatch.setattr(module,'_resource_gate',r.runner)
    before={str(path):path.read_bytes() for path in r.results}
    result=module.validate_normal_resources(r.out,r.audit,None)
    assert not result['passed'] and result['missing_evidence_is_not_model_zero']
    assert before=={str(path):path.read_bytes() for path in r.results}
    current=r.audit.snapshot()['tasks'][0]
    assert current['status']=='infrastructure_failed' and current['harbor_controls'] is None
    assert not r.original.exists() and (r.out/'quarantined_exports/unit-task-resource-observation').exists()


def test_cli_cannot_prepare_and_execute_together(tmp_path):
    module=entry()
    with pytest.raises(ValueError,match='Prepare and review'):
        module.main(['--source-manifest','x','--validation-terminal','y','--output',str(tmp_path/'q'),'--run'])
