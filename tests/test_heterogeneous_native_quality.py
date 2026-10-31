"""Scoped truth, public policy and normal-factory boundary regressions."""
import json
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from openpyxl import Workbook
import pytest
import yaml

from sheets_factory.pipelines import heterogeneous_native_quality as pipeline
from sheets_factory.task_adapters import heterogeneous_native_quality as nodes
from test_reference_evidence_policy import context as reference_context, diagnose as rediagnose
from test_reference_review_reporting import reviewed_run

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
    assert receipt['goal_sha256'] == pipeline.reference(goal)['sha256']
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


def test_native_scoped_receipt_passes_the_real_immutable_reporting_boundary(reviewed_run, tmp_path):
    from sheets_factory.workbook import heterogeneous_review_tasks as task
    from sheets_factory.reporting import generate_report
    root, run, _, ctx = reviewed_run
    snapshot = task.helper().snapshot(ctx.data['goal'])
    scope = tmp_path/'reporting_scope.json'
    scope.write_text(json.dumps({'expected_typed_values': [{'sheet': 'Sheet', 'cell': 'A1',
        'expected': snapshot['cells']['Sheet']['A1']['primary']}]}))
    proof = {'mode': 'financial_modeling', 'workbook': pipeline.reference(ctx.source),
        'independent_scope': pipeline.reference(scope), 'actual_validation': {'offline_fixture': True}}
    value = SimpleNamespace(helper=SimpleNamespace(validation_driver=lambda: SimpleNamespace(task=task)),
        evidence={'delta': {'expected_fixed_errors': []}})
    receipt = nodes.scoped_native_evidence(value, proof, ctx.data['goal'], ctx.data['delta']['expected_changes'], ctx.revision)
    ctx.save('native_error_probe.json', receipt)
    rediagnose(ctx)
    report = generate_report(run, project_root=root)
    assert report['yield']['verified_qualified'] == 1
    assert report['tasks'][0]['reference_validation']['verified'] is True
    assert report['consistency_warnings'] == []


@pytest.fixture
def resource_run(tmp_path, monkeypatch):
    """Wrapper fixtures only; existing observer tests certify its own checker."""
    import shutil
    from dirhash import dirhash
    from sheets_factory.core.audit import AuditStore
    from sheets_factory.evaluation.resource_harbor import export_resource_harbor
    from sheets_factory.evaluation.harbor import inspect_export
    spec = importlib.util.spec_from_file_location('_normal_native_resource_boundary_test',
        ROOT/'scripts/run_heterogeneous_native_quality.py')
    runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
    revision = tmp_path/'revision'
    for folder, value in [('public', 1), ('private', 2)]:
        (revision/folder).mkdir(parents=True)
        book = Workbook(); book.active['A1'] = value
        book.save(revision/folder/('input.xlsx' if folder == 'public' else 'goal.xlsx')); book.close()
    (revision/'public/instruction.md').write_text('Offline gate fixture.')
    out = tmp_path/'run'; original = out/'SpreadsheetEval/unit-task'
    export_resource_harbor(revision, original, {'task_id': 'unit-task'}, runtime_profile=pipeline.PROFILE)
    staging = out/'harbor_batches/fixed-batch/SpreadsheetEval'
    staged = staging/'unit-task'; shutil.copytree(original, staged)
    binding = inspect_export(original); name = binding['task_name']
    jobs = out/'harbor_jobs/fixed-batch'; controls = {}; results = []
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value)+'\n')
    for agent, reward in [('oracle', 1), ('nop', 0)]:
        directory = jobs/(agent+'__Fixture')
        config = {'trial_name': directory.name, 'task': {'path': str(staged)}, 'agent': {'name': agent}}
        result = {'trial_name': directory.name, 'task_name': name, 'config': config,
            'agent_info': {'name': agent}, 'verifier_result': {'rewards': {'reward': reward}},
            'exception_info': None, 'task_checksum': dirhash(staged, 'sha256')}
        write(directory/'config.json', config); write(directory/'result.json', result)
        results.append(directory/'result.json')
        controls[agent] = {'task_name': name, 'reward': reward, 'expected': reward, 'matched': True,
            'result_file': str(directory/'result.json'), 'exception_info': None}
    summary = jobs/'control_summary.json'; write(summary, {'per_task': {name: controls}})
    batch = staging.parent/'batch_manifest.json'
    write(batch, {'jobs_dir': str(jobs), 'staging': str(staging), 'task_ids': ['unit-task'],
        'export_bindings': {name: binding}})
    audit = AuditStore(out, {'id': 'offline-resource-gate'})
    audit.task('unit-task', mode='financial_modeling', source_id='offline-resource-source', status='qualified',
        harbor_controls=controls, harbor_export_binding=binding, harbor_summary_path=str(summary))
    observation = tmp_path/'offline_observation.json'; write(observation, {'fixture': True})
    calls = []
    def check(config, result, **options):
        calls.append((config, result, options))
        assert options['expected_task_directory'] == staged
        assert options['expected_profile'] == pipeline.PROFILE
        return {'passed': True, 'complete': True}
    monkeypatch.setattr(runner, 'validate_trial_observations', check)
    return SimpleNamespace(runner=runner, out=out, audit=audit, original=original,
        staged=staged, batch=batch, results=results, observer=pipeline.reference(observation), calls=calls)


def test_actual_resource_wrapper_binds_both_roles_to_the_fixed_staged_export(resource_run):
    r = resource_run
    result = r.runner.validate_normal_resources(r.out, r.audit, r.observer)
    assert result['passed'] is True and result['qualified_tasks_checked'] == 1
    assert len(r.calls) == 2 and r.original.exists()
    current = r.audit.snapshot()['tasks'][0]
    assert current['status'] == 'qualified'
    assert current['control_observation_receipts'] == {'oracle': [r.observer], 'nop': [r.observer]}


@pytest.mark.parametrize('change', ['missing_observer', 'actual_role_mismatch', 'wrong_stage', 'wrong_agent', 'wrong_reward'])
def test_resource_gap_withdraws_acceptance_and_preserves_raw_rewards(resource_run, monkeypatch, change):
    r = resource_run; receipt = r.observer
    if change == 'missing_observer': receipt = None
    elif change == 'actual_role_mismatch':
        monkeypatch.setattr(r.runner, 'validate_trial_observations', lambda *a, **k: {'passed': False, 'complete': False})
    elif change == 'wrong_stage':
        data = json.loads(r.batch.read_text()); data['staging'] = str(r.out/'another_stage')
        r.batch.write_text(json.dumps(data))
    else:
        path = r.results[0]; data = json.loads(path.read_text())
        if change == 'wrong_agent': data['agent_info']['name'] = 'another-agent'
        else: data['verifier_result']['rewards']['reward'] = 0
        path.write_text(json.dumps(data))
    before = {str(path): path.read_bytes() for path in r.results}
    result = r.runner.validate_normal_resources(r.out, r.audit, receipt)
    assert result['passed'] is False and result['infrastructure_task_ids'] == ['unit-task']
    assert before == {str(path): path.read_bytes() for path in r.results}
    current = r.audit.snapshot()['tasks'][0]
    assert current['status'] == 'infrastructure_failed' and current['harbor_controls'] is None
    assert current['harbor_export_binding'] is None and current['historical_harbor_controls']
    assert not r.original.exists() and (r.out/'quarantined_exports/unit-task-resource-observation').exists()
    assert result['missing_evidence_is_not_model_zero'] is True
