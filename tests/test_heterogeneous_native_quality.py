"""Scoped truth, public policy and normal-factory boundary regressions."""
import json
from pathlib import Path
from types import SimpleNamespace

from openpyxl import Workbook
import pytest
import yaml

from sheets_factory.pipelines import heterogeneous_native_quality as pipeline
from sheets_factory.task_adapters import heterogeneous_native_quality as nodes

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def configuration(monkeypatch):
    import subprocess
    def forbidden(*args, **kwargs):
        pytest.fail('Pure quality configuration must not start an external service')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    config = yaml.safe_load((ROOT/'config/pipelines/heterogeneous_native_quality_v1.yaml').read_text())
    config.update(project_root=str(ROOT), run_dir='/unused/pure-preparation')
    config[pipeline.SETTING] = pipeline.setting()
    config['pipeline'] = {'node_registry': str(pipeline.REGISTRY)}
    return config


def test_default_normal_configuration_requires_all_twelve_supported_checks(configuration):
    profile = pipeline.validate_configuration(configuration)
    assert profile['id'] == 'entity_group_large_v2'


@pytest.mark.parametrize('change', ['skip_check', 'wrong_policy', 'no_harbor', 'private_inline',
    'cpu', 'memory', 'truncated_profile', 'implicit_seed', 'extra_candidate', 'wrong_registry'])
def test_unsafe_configuration_cannot_silently_enter_normal_factory(configuration, change):
    c = configuration
    if change == 'skip_check': c['diagnosis']['selection']['exclude'] = ['Q04']
    elif change == 'wrong_policy': c['diagnosis']['reference_evidence_policy'] = 'independent_public_recovery'
    elif change == 'no_harbor': c['harbor']['execute_controls'] = False
    elif change == 'private_inline': c['diagnosis']['execution']['reference_evidence_transport'] = 'inline'
    elif change == 'cpu': c['agents']['container_cpus'] = 16
    elif change == 'memory': c['agents']['container_memory'] = '64g'
    elif change == 'truncated_profile': c['construction']['analysis_limits']['max_profile_cells'] = 100
    elif change == 'implicit_seed': c['run']['seed_path'] = '/some/other/files'
    elif change == 'extra_candidate': c['run']['max_candidates_per_seed'] = 2
    else: c['pipeline']['node_registry'] = 'config/nodes.yaml'
    with pytest.raises(ValueError):
        pipeline.validate_configuration(c)


@pytest.mark.parametrize('value', [None, {}, {'passed': True, 'qualified': False},
    SimpleNamespace(passed=True), object.__new__(pipeline.NativeScopeAdmission)])
def test_persisted_flags_and_fabricated_objects_are_not_actual_admissions(value):
    with pytest.raises(ValueError):
        pipeline.admission(value)


def test_both_templates_keep_the_ordinary_recovery_trajectory_and_diagnosis_nodes(configuration):
    from sheets_factory.core.node import BaseNode
    registry = yaml.safe_load(pipeline.REGISTRY.read_text())['nodes']
    assert registry['diagnose'] == 'sheets_factory.nodes.quality:DiagnoseNode'
    assert registry['trajectory'] == 'sheets_factory.nodes.quality:TrajectoryNode'
    assert registry['independent_recovery'] == 'sheets_factory.nodes.quality:RecoveryNode'
    for mode in configuration['run']['targets']:
        template = yaml.safe_load((ROOT/'src/sheets_factory/pipelines/templates'/f'{mode}.yaml').read_text())
        for names in template['phases'].values():
            for name in names:
                location, _, attribute = registry[name].partition(':')
                imported = __import__(location, fromlist=[attribute])
                assert isinstance(getattr(imported, attribute)(), BaseNode)


@pytest.fixture
def scoped_goal(tmp_path):
    path = tmp_path/'goal.xlsx'
    book = Workbook(); book.active.title = 'Business'
    book['Business']['A1'] = 'Financial output'
    book['Business']['B1'] = 42.125
    book['Business']['B2'] = 'Current period policy'
    book.create_sheet('Provided Context')['A1'] = '#DIV/0!'
    book.save(path); book.close()
    from sheets_factory.workbook import heterogeneous_review_tasks as task
    observed = task.helper().snapshot(path)
    rows = [{'sheet': 'Business', 'cell': address, 'expected': observed['cells']['Business'][address]['primary']}
        for address in ('B1', 'B2')]
    scope = tmp_path/'coverage.json'; scope.write_text(json.dumps({'expected_typed_values': rows}))
    proof = {'mode': 'financial_modeling', 'independent_scope': pipeline.reference(scope),
        'workbook': pipeline.reference(path), 'actual_validation': {'opaque_test_identity': 1}}
    value = SimpleNamespace(helper=SimpleNamespace(validation_driver=lambda: SimpleNamespace(task=task)),
        evidence={'delta': {'expected_fixed_errors': [['Provided Context', 'A1', '#DIV/0!']]}})
    return path, proof, value, rows


def test_offscope_error_does_not_invalidate_independently_correct_task_values(scoped_goal):
    goal, proof, value, _ = scoped_goal
    receipt = nodes.scoped_native_evidence(value, proof, goal, ['Business!B1', 'Business!B2'], 3)
    assert receipt['blocking'] is False and receipt['independent_fields_checked'] == 2
    assert receipt['retained_offscope_errors'] == [['Provided Context', 'A1', '#DIV/0!']]
    assert receipt['revision'] == 3 and receipt['goal'] == pipeline.reference(goal)
    assert receipt['whole_source_business_correctness_certified'] is False
    assert receipt['complete_syntactic_dependency_exclusion_claimed'] is False


@pytest.mark.parametrize('change', ['wrong_number', 'wrong_text', 'uncovered_delta', 'new_error', 'changed_error'])
def test_scoped_financial_certificate_rejects_wrong_or_uncovered_outputs(scoped_goal, change):
    goal, proof, value, rows = scoped_goal
    labels = ['Business!B1']
    if change in ('wrong_number', 'wrong_text'):
        index = 0 if change == 'wrong_number' else 1
        rows[index]['expected']['value'] = '999.00' if index == 0 else 'Stale example policy'
        Path(proof['independent_scope']['path']).write_text(json.dumps({'expected_typed_values': rows}))
        proof['independent_scope'] = pipeline.reference(proof['independent_scope']['path'])
    elif change == 'uncovered_delta': labels.append('Provided Context!B5')
    elif change == 'changed_error': value.evidence['delta']['expected_fixed_errors'][0][2] = '#N/A'
    else:
        from openpyxl import load_workbook
        book = load_workbook(goal); book['Provided Context']['A2'] = '#N/A'; book.save(goal); book.close()
    with pytest.raises(ValueError):
        nodes.scoped_native_evidence(value, proof, goal, labels, 0)


def test_late_source_change_blocks_context_before_work(scoped_goal, monkeypatch):
    goal, proof, value, _ = scoped_goal
    proof.update(input=pipeline.reference(goal), goal=pipeline.reference(goal))
    monkeypatch.setattr(nodes, 'admission', lambda _: proof)
    monkeypatch.setattr(nodes, 'setting', lambda: {'fixture': True})
    ctx = SimpleNamespace(config={pipeline.SETTING: {'fixture': True}}, source=goal,
        mode='financial_modeling', data={'_native_scope_admission': value})
    nodes.context(ctx)
    goal.write_bytes(goal.read_bytes()+b'changed')
    with pytest.raises(ValueError, match='source or task mode'):
        nodes.context(ctx)


def test_wrong_financial_repair_requires_a_new_actual_task_version(monkeypatch):
    from sheets_factory.core.node import TaskRejected
    monkeypatch.setattr(nodes, 'context', lambda _: (None, {}))
    ctx = SimpleNamespace(data={'repair_routes': [{'route_class': 'repair', 'issue_id': 'truth', 'problem_id': 'Q04'}],
        'diagnosis': {'issues': [{'issue_id': 'truth', 'certainty': 'confirmed'}]}})
    with pytest.raises(TaskRejected, match='newly validated'):
        nodes.NativeRepairNode().execute(ctx)


def test_export_cannot_inherit_a_stale_review(monkeypatch):
    monkeypatch.setattr(nodes, 'context', lambda _: (None, {}))
    monkeypatch.setattr(nodes.quality, 'validate_reference_policy_selection', lambda _: 'reference_review')
    monkeypatch.setattr(nodes.quality, 'reference_revision_binding', lambda _: {'current': 2})
    ctx = SimpleNamespace(config={}, data={'diagnosis': {'releasable': True,
        'reference_review': {'passed': True, 'binding': {'current': 1}}}})
    with pytest.raises(ValueError, match='current supported'):
        nodes.NativeExportNode().execute(ctx)
