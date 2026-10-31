"""Pure configuration/opaque-boundary tests and mocked normal-control lifecycle."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from sheets_factory.pipelines import operating_reports_200_quality as pipeline
from sheets_factory.task_adapters import operating_reports_200_quality as nodes
from sheets_factory.workbook.linear_capital_ringfenced_group import contract as files

ROOT = Path(__file__).resolve().parents[1]


def configuration(tmp_path):
    config = yaml.safe_load((ROOT/'config/pipelines/operating_reports_200_quality_v1.yaml').read_text())
    config.update(project_root=str(ROOT), run_dir=str(tmp_path))
    config[pipeline.SETTING] = pipeline.setting(); config['pipeline'] = {'node_registry': str(pipeline.REGISTRY)}
    return config


def entry_module():
    definition = importlib.util.spec_from_file_location('_test_fixed200_normal_entry', ROOT/'scripts/run_operating_reports_200_quality.py')
    module = importlib.util.module_from_spec(definition); definition.loader.exec_module(module); return module


@pytest.fixture
def mocked_cold_boundary(tmp_path, monkeypatch):
    """Replace ONLY the expensive trusted cold validator; never native services."""
    def save(name, value): return files.write(tmp_path/name, value)
    def raw(name, value):
        path = tmp_path/name; path.write_bytes(value); return files.reference(path)
    public_ref = save('public.json', {'public_policy': 'Hypothetical business policy.'})
    points = ['Report!A'+str(i) for i in range(1, 62323)]
    definition = {'FM_mask_points': points, 'formulas': {point: '=1' for point in points}, 'literals': {'Inputs!A1': 7},
        'sheetnames': ['Report', 'Inputs']}
    definition_ref = save('definition.json', definition)
    expected_ref = save('expected.json', {point: {'type': 'number', 'value': '1'} for point in points})
    other = save('bound.json', {'unchanged': True})
    inp, goal = raw('input.xlsx', b'unchanged input'), raw('goal.xlsx', b'unchanged goal')
    business = raw('brief.md', b'B'*402+b'\n')
    rendered = raw('rendered.md', files.checked(business).read_bytes()+pipeline.IO_APPENDIX)
    controls = {name: other for name in ('oracle', 'nop', 'equivalent', 'missed_root', 'extra_change')}
    material = {'input': inp, 'goal': goal, 'instruction': business, 'complete_D_count': 62322,
        'controls': {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}, 'full_D_controls': controls}
    planned = {name: raw(name+'.xlsx', name.encode()) for name in ('equivalent', 'FM_missed_root', 'extra_change')}
    prepared = {'kind': 'prepared_fixed_operating_reports_200_task_engineering_revision2', 'version': 1,
        'financial_target_count': 62322, 'independent_business_field_count': 93510, 'genuine_goal': goal,
        'specification': public_ref, 'definition': definition_ref, 'source_definition': definition_ref,
        'expected': expected_ref, 'bindings': other, 'candidate_preparation': other, 'planned_inputs': planned,
        'runtime_profile': files.reference(pipeline.PROFILE)}
    prep_ref = save('task_preparation.json', prepared)
    actual = {'kind': 'complete_fixed_operating_reports_200_task_engineering_revision2', 'version': 1, 'passed': True,
        'actual_LO_calls_started': 8, 'actual_LO_calls_completed': 8, 'normal_all12_QA_passed': False, 'qualified': False,
        'preparation': prep_ref, 'source_manifest': other, 'records': {'modes': {'financial_modeling': material}}}
    actual_ref = save('task_terminal.json', actual)
    dev = {'modes': {'financial_modeling': {'input': inp, 'goal': goal, 'original_instruction': business,
        'rendered_instruction': rendered, 'material_task_version': {'sha256': pipeline.FIRST_MATERIAL}}}}
    dev_ref = save('probe.json', dev)
    monkeypatch.setattr(pipeline, 'TERMINAL_SHA', actual_ref['sha256'])
    monkeypatch.setattr(pipeline, 'DEV_PROBE', Path(dev_ref['path']))
    monkeypatch.setattr(pipeline, 'DEV_PROBE_SHA', dev_ref['sha256'])
    cold_calls = []
    def validate(value): cold_calls.append(value); return deepcopy(actual)
    helper = SimpleNamespace(read=files.read, checked=files.checked, write=files.write,
        validate_completed=validate, recipes=lambda: {other['path']: other},
        source=SimpleNamespace(schema=SimpleNamespace(canonical_sha256=lambda _: pipeline.SPECIFICATION_SHA)))
    monkeypatch.setattr(pipeline, 'boundary', lambda: helper)
    return SimpleNamespace(actual=actual, actual_ref=actual_ref, helper=helper, cold_calls=cold_calls,
        prepared=prepared, dev=dev, dev_ref=dev_ref, business=business, rendered=rendered, other=other)


def test_opaque_admission_runs_genuine_gate_once_and_guards_all_first_material_bytes(mocked_cold_boundary):
    f = mocked_cold_boundary; value = pipeline.OperatingReportsAdmission(f.actual_ref)
    proof = pipeline.admission(value)
    assert f.cold_calls == [f.actual_ref] and proof['mode'] == 'financial_modeling'
    assert proof['independent_scope_count'] == 93510 and proof['complete_D_count'] == 62322
    assert files.checked(proof['instruction']).read_bytes() == files.checked(proof['original_business_instruction']).read_bytes()+pipeline.IO_APPENDIX
    assert proof['original_dev_and_normal_scores_transferred'] is False
    pipeline.admission(value); assert len(f.cold_calls) == 1
    with pytest.raises(ValueError, match='Persisted JSON'): pipeline.admission(proof)
    with pytest.raises(ValueError, match='Persisted JSON'): pipeline.admission(object.__new__(pipeline.OperatingReportsAdmission))
    Path(f.rendered['path']).write_bytes(b'changed public request')
    with pytest.raises(ValueError, match='bound artifact changed'): pipeline.admission(value)


@pytest.mark.parametrize('problem', ['v1', 'failed', 'partial', 'scope', 'full_D', 'controls', 'brief', 'input'])
def test_rejects_wrong_family_partial_proof_or_changed_first_material(mocked_cold_boundary, problem):
    f = mocked_cold_boundary
    if problem == 'v1': f.actual['kind'] = 'complete_fixed_operating_reports_200_task_engineering'
    elif problem == 'failed': f.actual['passed'] = False
    elif problem == 'partial': f.actual['actual_LO_calls_completed'] = 7
    elif problem == 'scope': f.prepared['independent_business_field_count'] = 93509
    elif problem == 'full_D': f.actual['records']['modes']['financial_modeling']['complete_D_count'] -= 1
    elif problem == 'controls': f.actual['records']['modes']['financial_modeling']['controls']['nop'] = 1
    elif problem == 'brief': Path(f.rendered['path']).write_bytes(b'different brief')
    else: f.actual['records']['modes']['financial_modeling']['input'] = f.other
    if problem == 'scope':
        old_read = f.helper.read
        f.helper.read = lambda ref: deepcopy(f.prepared) if ref == f.actual['preparation'] else old_read(ref)
    with pytest.raises(ValueError): pipeline.OperatingReportsAdmission(f.actual_ref)


def test_cold_failure_is_not_a_stored_pass_or_zero_service_admission(mocked_cold_boundary):
    f = mocked_cold_boundary
    def fail(_): raise ValueError('Cold full source proof rejected')
    f.helper.validate_completed = fail
    with pytest.raises(ValueError, match='Cold full source'): pipeline.OperatingReportsAdmission(f.actual_ref)


def test_in_memory_evidence_and_proof_mutations_are_rejected(mocked_cold_boundary):
    value = pipeline.OperatingReportsAdmission(mocked_cold_boundary.actual_ref)
    value.evidence['actual']['passed'] = False
    with pytest.raises(ValueError, match='evidence changed in memory'): pipeline.admission(value)
    other = pipeline.OperatingReportsAdmission(mocked_cold_boundary.actual_ref); other.proof['complete_D_count'] -= 1
    with pytest.raises(ValueError, match='live exact fixed200'): pipeline.admission(other)


def test_all_twelve_default_checks_and_reference_policy_are_retained(tmp_path):
    config = configuration(tmp_path); profile = pipeline.validate_configuration(config)
    assert profile['docker_resources']['source'] == {'cpus': 2, 'memory_bytes': 32*1024**3, 'pids_limit': 256}
    from sheets_factory.checkers import DiagnosisRunner
    assert set(DiagnosisRunner(ROOT).resolve(config)['enabled_check_ids']) == {f'Q{i:02d}' for i in range(1,13)}
    registry = yaml.safe_load(pipeline.REGISTRY.read_text())['nodes']
    assert registry['independent_recovery'] == 'sheets_factory.nodes.quality:RecoveryNode'
    assert registry['trajectory'] == 'sheets_factory.nodes.quality:TrajectoryNode'


@pytest.mark.parametrize('change', ['missing_check', 'other_policy', 'nop_disabled', 'DBG', 'model', 'memory', 'filter'])
def test_config_cannot_reduce_quality_or_switch_materials(tmp_path, change):
    config = configuration(tmp_path)
    if change == 'missing_check': config['diagnosis']['selection']['exclude'] = ['Q08']
    elif change == 'other_policy': config['diagnosis']['reference_evidence_policy'] = 'independent_public_recovery'
    elif change == 'nop_disabled': config['harbor']['execute_controls'] = False
    elif change == 'DBG': config['run']['targets']['debugging'] = 1
    elif change == 'model': config['agents']['model'] = 'gpt-6.1-sol'
    elif change == 'memory': config['agents']['container_memory'] = '64g'
    else: config['run']['source_filter'] = 'another-source'
    with pytest.raises(ValueError): pipeline.validate_configuration(config)


def test_exact_private_plan_keeps_all_masked_forecasts_and_public_brief_unchanged(mocked_cold_boundary):
    f = mocked_cold_boundary; value = pipeline.OperatingReportsAdmission(f.actual_ref)
    plan = nodes.canonical_plan(value)
    assert len(plan['edits']) == 62322 and all(row['after'] is None for row in plan['edits'])
    assert plan['public_instruction'].encode() == files.checked(f.rendered).read_bytes()
    assert plan['public_rules'] == ['Hypothetical business policy.']
    assert plan['scenario_inputs'] == [] and plan['family_adapter']['normal_quality_or_score_inherited'] is False
    assert 'Report!A1' not in plan['public_instruction']


def test_no_old_namespaces_or_module_globals_are_monkeypatched():
    assert pipeline.NativeQualityFactory.run_phase.__code__ is pipeline.base.NativeQualityFactory.run_phase.__code__
    assert pipeline.NativeQualityFactory.run_phase.__globals__ is not pipeline.base.NativeQualityFactory.run_phase.__globals__
    assert nodes.NormalizeNode.execute.__code__ is nodes.base.NativeNormalizeNode.execute.__code__
    assert nodes.NormalizeNode.execute.__globals__ is not nodes.base.NativeNormalizeNode.execute.__globals__
    assert pipeline.base.SETTING == 'heterogeneous_native_quality'


def test_diagnose_reuses_strict_receipt_body_after_new_context_gate(mocked_cold_boundary, tmp_path, monkeypatch):
    value = pipeline.OperatingReportsAdmission(mocked_cold_boundary.actual_ref)
    config = configuration(tmp_path)
    ctx = SimpleNamespace(config=config, mode='financial_modeling', source=Path(value.proof['workbook']['path']),
        data={'_native_scope_admission': value})
    seen = []
    monkeypatch.setattr(nodes.receipt.ReferenceReceiptDiagnosisNode, '_execute_diagnose', lambda self, context: seen.append(context) or {'strict_receipt': True})
    assert nodes.DiagnoseNode().execute(ctx) == {'strict_receipt': True} and seen == [ctx]
    ctx.mode = 'debugging'
    with pytest.raises(ValueError, match='Only the fixed exact FM'): nodes.DiagnoseNode().execute(ctx)


def test_unchanged_strict_receipt_schema_rejects_stale_binding_not_financial_scores():
    from sheets_factory.task_adapters import reference_receipt_diagnosis as receipt
    schema = receipt.diagnosis_output_schema(['Q01','Q02','Q03','Q04'])
    assert schema['properties']['assessments']['properties']['Q04']['anyOf'][0]['properties']['evidence']['maxItems'] == 1
    assessment = {'Q04': {'state': 'clear', 'reason': 'reviewed', 'evidence': ['reference_review_json:'+json.dumps({
        'binding': {'task_revision_hash': 'stale'}, 'business_evidence': ['Inspected policy'],
        'financial_validation_checks': [{'check': 'identity', 'method': 'exact arithmetic', 'passed': True, 'evidence': ['one']}]
    })]}}
    assert receipt._q04_problems({'assessments': assessment}, {'task_revision_hash':'current'})


def test_content_repair_cannot_silently_change_spent_first_attempt(mocked_cold_boundary, tmp_path):
    value = pipeline.OperatingReportsAdmission(mocked_cold_boundary.actual_ref)
    ctx = SimpleNamespace(config=configuration(tmp_path), mode='financial_modeling', source=Path(value.proof['workbook']['path']),
        data={'_native_scope_admission': value})
    with pytest.raises(nodes.TaskRejected, match='explicitly new checked revision'): nodes.RepairNode().execute(ctx)


@pytest.mark.parametrize('cleanup_ok', [True, False])
def test_current_normal_controls_run_exactly_three_native_calls_and_reuse_no_clear_flags(mocked_cold_boundary, tmp_path, monkeypatch, cleanup_ok):
    f = mocked_cold_boundary; value = pipeline.OperatingReportsAdmission(f.actual_ref); history = []; calls = []; saved = {}
    class Engine:
        def metadata(self): return {'actual_resource_receipts': history[:]}
        def recalculate(self, source, output):
            calls.append((source, output)); output.write_bytes(b'native mock control')
            history.append(files.write(tmp_path/(str(len(calls))+'_resource.json'), {'fixture': True})); return output
    f.helper.source.validate_call = lambda call, record, frozen: {'terminal': record, 'resource_profile': frozen['runtime_profile'],
        'container_id': str(call['index'])*64}
    f.helper.source.owned_absence = lambda calls: {'all_owned_containers_absent': cleanup_ok, 'daemon_reachable': True,
        'owned': [{'full_id':row['actual_resource_evidence']['container_id'],'absent':True} for row in calls]}
    def compare(source, goal, output):
        name = Path(output).stem
        return {'reward': 0 if Path(output) == Path(value.proof['input']['path']) or name in ('missed_root','extra_change') else 1}
    monkeypatch.setattr(nodes.base, 'compare_files', compare)
    revision = tmp_path/'revision'; (revision/'private').mkdir(parents=True)
    ctx = SimpleNamespace(config=configuration(tmp_path), mode='financial_modeling', source=Path(value.proof['workbook']['path']),
        data={'_native_scope_admission': value, 'input': Path(value.proof['input']['path']), 'goal': Path(value.proof['goal']['path']), 'revision_hash':'current'},
        revision_dir=revision, engine=Engine(), save=lambda name, record: saved.update({name:record}))
    if cleanup_ok:
        assert nodes.ControlsNode().execute(ctx)['controls'] == {name:{'reward':reward} for name,reward in nodes.REWARDS.items()}
    else:
        with pytest.raises(ValueError, match='exact owned-cleanup proof'): nodes.ControlsNode().execute(ctx)
        assert 'local_controls.json' not in saved
    assert len(calls) == 3 and [source for source,_ in calls] == [files.checked(f.prepared['planned_inputs'][name]) for name in ('equivalent','FM_missed_root','extra_change')]
    assert all('actual_resource_evidence' in saved['normal_control_'+name+'.json'] for name in ('equivalent','missed_root','extra_change'))


def test_export_enforces_all_supported_reference_checks_before_export(mocked_cold_boundary, tmp_path, monkeypatch):
    value = pipeline.OperatingReportsAdmission(mocked_cold_boundary.actual_ref); exported = []
    ctx = SimpleNamespace(config=configuration(tmp_path), mode='financial_modeling', source=Path(value.proof['workbook']['path']),
        data={'_native_scope_admission': value, 'plan': {'public_instruction':files.checked(value.proof['instruction']).read_text()}})
    monkeypatch.setattr(nodes, '_export', lambda *args: exported.append(True))
    def reject(_): raise ValueError('Missing supported Q01-Q04 or all12')
    monkeypatch.setattr(nodes, 'validate_reference_export', reject)
    with pytest.raises(ValueError, match='Missing supported'): nodes.ExportNode().execute(ctx)
    assert exported == []


def test_entry_reuses_actual_harbor_observer_withdrawal_and_separate_run_guard(monkeypatch):
    entry = entry_module()
    assert entry.validate_normal_resources.__code__ is entry._base.validate_normal_resources.__code__
    assert entry.execute_prepared.__code__ is entry._base.execute_prepared.__code__
    with pytest.raises(ValueError, match='Only the observed fixed FM'): entry.prepare('/t','/o',mode='debugging')
    monkeypatch.setattr(entry, 'prepare', lambda *args, **kwargs: pytest.fail('No preparation before separate-run guard'))
    with pytest.raises(ValueError, match='separate --prepared --run'): entry.main(['--validation-terminal','/t','--output','/o','--run'])


def test_zero_service_preflight_keeps_exact_single_FM_inventory_and_real_cold_replay(mocked_cold_boundary, tmp_path, monkeypatch):
    f = mocked_cold_boundary; entry = entry_module(); output = tmp_path/'normal'
    def configure(path, destination, proofs):
        result = configuration(destination); result['run']['seed_manifest'] = str(destination/'seed_manifest.json')
        result['host_runtime'] = {'fixture': 'no-service host settings'}; return result
    monkeypatch.setitem(entry._namespace, 'configure', configure)
    monkeypatch.setitem(entry._namespace, 'recipes', lambda config, admissions: {f.other['path']:f.other['sha256']})
    prepared_ref = entry.prepare(f.actual_ref, output)
    frozen = files.read(prepared_ref); assert frozen['count'] == 1
    assert frozen['targets'] == {'financial_modeling':1,'debugging':0}
    assert frozen['actual_models'] == frozen['actual_LO_calls'] == frozen['actual_Harbor_jobs'] == 0
    seed = files.read(frozen['prepared_seed_manifest'])['selected'][0]
    assert seed['modes'] == ['financial_modeling'] and seed['finance_evidence']['debugging_eligible'] is False
    assert seed['finance_evidence']['financial_evidence_scope'] == '93510 independent fixed200 business fields'
    assert len(f.cold_calls) == 1
    assert entry.validate_prepared(output)[0] == frozen and len(f.cold_calls) == 1
    entry._namespace['_SESSIONS'].clear()
    checked, config, admissions = entry.validate_prepared(output)
    assert checked == frozen and len(f.cold_calls) == 2
    audit = SimpleNamespace(update_run=lambda **kwargs: None)
    factory = pipeline.NativeQualityFactory(config, audit, None, None, admissions=admissions)
    assert factory.load_seeds()[0]['modes'] == ['financial_modeling']
    assert isinstance(factory.load_node('diagnose'), nodes.DiagnoseNode)
    context = SimpleNamespace(source=Path(admissions[0].proof['workbook']['path']), mode='financial_modeling', data={})
    monkeypatch.setattr(pipeline.base.FactoryPipeline, 'run_phase', lambda self, ctx, phase: 'generic phase')
    assert factory.run_phase(context, 'construct') == 'generic phase'
    assert context.data['_native_scope_admission'] is admissions[0]


@pytest.mark.parametrize('operation', ['prepare','validate','run'])
def test_monitor_panel_and_lease_start_before_cold_admission(tmp_path, monkeypatch, operation):
    entry = entry_module(); seen = []
    class Audit:
        def __init__(self, *args): self.db = SimpleNamespace(close=lambda: seen.append('db closed'))
        def snapshot(self): return {}
        def events(self, *args): return []
        def update_run(self, **kwargs): pass
        def export(self): pass
    class Panel:
        def __init__(self, *args, **kwargs): pass
        def start(self): seen.append('panel started'); return 'http://fixture.invalid'
        def stop(self): seen.append('panel stopped')
    class Lease:
        def __init__(self, *args): pass
        def acquire(self): seen.append('lease acquired'); return self
        def release(self): seen.append('lease released')
    monkeypatch.setattr(entry, 'AuditStore', Audit); monkeypatch.setattr(entry, 'DashboardServer', Panel); monkeypatch.setattr(entry, 'ProducerLease', Lease)
    destination = tmp_path/'normal'
    with entry.admission_monitor(destination, operation) as state:
        assert seen == ['lease acquired','panel started'] and not destination.exists()
        seen.append('cold admission'); state['passed'] = True
    assert seen[-3:] == ['panel stopped','db closed','lease released']
    terminals = list(tmp_path.glob('normal_'+operation+'_monitor_*/terminal.json'))
    result = files.read(terminals[0]); assert result['inner_passed'] and result['qualified'] is False
