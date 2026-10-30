"""Offline adapter contracts; no production workbook, LO job or model."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import threading

import openpyxl
import pytest
import yaml

from sheets_factory.task_adapters import entity_group as adapter
from sheets_factory.pipelines import entity_group_contract as contract
from sheets_factory.pipelines import entity_group_admission as admission
from sheets_factory.task_adapters.public_workbook_scope import reference, write_new
from sheets_factory.workbook.entity_group.excel import emit_entity_group_workbook
from sheets_factory.workbook.entity_group.validate import evaluate_expression

ROOT = Path(__file__).resolve().parents[1]


def config():
    return {adapter.SETTING: adapter.setting(ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml'), 'construction': {'max_edit_count': {'debugging': 200000},
        'analysis_limits': {'max_profile_cells': 3000000, 'max_dependency_closure_cells': 3000000}},
        'recovery': {'compiler_backend': 'entity_group_public_integer_shared_compiler', 'replay_timeout_seconds': 7200}}


def test_explicit_complete_contract_preserves_all_other_normal_gates():
    adapter.validate_copies()
    value = config(); before = deepcopy(value)
    result = contract.construction_contract('debugging', value)
    assert value == before
    assert result['source_requirements']['max_profile_cells'] == 3000000
    assert result['dependency_requirements']['max_dependency_closure_cells'] == 3000000
    assert result['modes']['debugging']['edit_count']['max'] == 200000
    assert result['modes']['debugging']['activity_contract'] == adapter.METHOD
    assert result['modes']['debugging']['each_root_requires_individual_and_combined_marginal_impact'] is False
    assert result['dependency_requirements']['no_native_calculation_errors_in_required_D'] is True
    assert result['reference_scope']['complete_recalculated_changed_value_set'] is True
    value.pop(adapter.SETTING)
    with pytest.raises(ValueError, match='analysis limit'):
        contract.construction_contract('debugging', value)
    assert contract.construction_contract('debugging', {}) == adapter.normal.construction_contract('debugging', {})


@pytest.mark.parametrize('change', ['lower_profile', 'too_many_edits', 'bool_version'])
def test_no_truncation_or_unapproved_edit_ceiling(change):
    value = config()
    if change == 'lower_profile': value['construction']['analysis_limits']['max_profile_cells'] = 500000
    if change == 'too_many_edits': value['construction']['max_edit_count']['debugging'] = 200001
    if change == 'bool_version': value[adapter.SETTING]['version'] = True
    with pytest.raises(ValueError): contract.construction_contract('debugging', value)


def test_new_task_rejects_legacy_resource_fallback_before_any_node_work():
    value = {adapter.SETTING: adapter.setting(ROOT / 'config/runtime_profiles/entity_group_large_v1.yaml')}
    ctx = SimpleNamespace(config=value, mode='debugging')
    with pytest.raises(ValueError, match='explicitly bound v2'):
        adapter.enabled(ctx)
    assert adapter.enabled(SimpleNamespace(config=config(), mode='debugging')) is True


@pytest.mark.parametrize('field,value', [('compiler_backend', 'llm'), ('replay_timeout_seconds', 120),
                                       ('replay_timeout_seconds', True)])
def test_new_family_cannot_silently_use_old_recovery_budget_or_backend(field, value):
    selected = config(); selected['recovery'][field] = value
    with pytest.raises(ValueError, match='public-only entity recovery'):
        adapter.enabled(SimpleNamespace(config=selected, mode='debugging'))


def test_explicit_indexed_and_streaming_dependencies_original_joint_proof():
    from sheets_factory.workbook.profile_indexed import profile_workbook
    from sheets_factory.evaluation.streaming_delta import compare_workbooks
    from sheets_factory.nodes.scc_activity import SCCConstructNode
    assert adapter.profile_workbook is profile_workbook
    assert adapter.compare_workbooks is compare_workbooks
    assert adapter.EntityGroupConstructNode._prove_activity is SCCConstructNode._prove_activity
    registry = yaml.safe_load((ROOT / 'config/task_adapters/entity_group_nodes.yaml').read_text())['nodes']
    assert len(registry) == 11
    assert registry['precheck'] == 'sheets_factory.nodes.joint_controls:JointObservableControlsNode'
    assert registry['instruction'] == 'sheets_factory.nodes.construction:InstructionNode'
    assert registry['trajectory'] == 'sheets_factory.nodes.quality:TrajectoryNode'
    assert registry['independent_recovery'] == 'sheets_factory.workbook.entity_group_public_recovery:EntityGroupRecoveryNode'


def test_real_pipeline_constructor_loads_every_normal_phase_without_services():
    from sheets_factory.core.pipeline import BasePipeline
    class Startup(BasePipeline):
        def run(self): return False
    value = config(); value.update(project_root=str(ROOT),
        pipeline={'node_registry': 'config/task_adapters/entity_group_nodes.yaml'},
        run={'targets': {'financial_modeling': 0, 'debugging': 1}})
    pipeline = Startup(value)
    assert len(pipeline.node_registry) == 11
    phases = pipeline.templates['debugging']['phases']
    assert phases['revision'] == ['construct', 'instruction', 'precheck', 'independent_recovery', 'trajectory', 'diagnose']
    assert phases['diagnosis_retry'] == ['diagnose']


R = {name: "'Example'!$B$" + str(i + 1) for i, name in enumerate(
    ('principal', 'rate', 'tax_after', 'tax_before', 'tax_rate', 'expense', 'capacity', 'old_interest',
     'limit', 'collateral', 'nav', 'required', 'commitment', 'called', 'cash', 'floor', 'equity', 'trap', 'reserve', 'passed'))}


@pytest.mark.parametrize('field,expression,numbers,correct,bugged', [
    ('bank_interest', ['round_product', R['principal'], R['rate']], {'principal': 100000, 'rate': 10**10}, 1000, 83),
    ('current_tax', ['round_product', R['tax_after'], R['tax_rate']], {'tax_after': 100, 'tax_before': 200, 'tax_rate': 2*10**11}, 20, 40),
    ('interest_current_allowed', ['min', R['expense'], ['max', ['sub', R['capacity'], R['old_interest']], 0]],
        {'expense': 100, 'capacity': 100, 'old_interest': 70}, 30, 100),
    ('borrowing_base', ['if', 0, 0, ['min', R['limit'], R['collateral']]], {'limit': 100, 'collateral': 50, 'nav': 100}, 50, 100),
    ('capital_call', ['min', R['required'], ['sub', R['commitment'], R['called']]], {'required': 80, 'commitment': 100, 'called': 40}, 60, 80),
    ('distribution', ['min', ['max', ['sub', R['cash'], R['floor']], 0], ['max', R['equity'], 0]],
        {'cash': 150, 'floor': 100, 'equity': 100}, 50, 100),
    ('reserve_released', ['if', R['trap'], 0, R['reserve']], {'trap': 1, 'reserve': 80, 'passed': 1}, 0, 80),
])
def test_each_mutation_changes_a_real_financial_policy_on_hand_case(field, expression, numbers, correct, bugged):
    refs = {'taxable_before_loss': R['tax_before'], 'certified_nav_close': R['nav'], 'covenant_passed': R['passed']}
    values = {R[name]: number for name, number in numbers.items()}
    original = deepcopy(expression)
    mutated = adapter.mutate_expression(field, expression, refs)
    assert expression == original
    assert evaluate_expression(original, values) == correct
    assert evaluate_expression(mutated, values) == bugged
    with pytest.raises(ValueError, match='shape changed'):
        adapter.mutate_expression(field, ['sum', 1, 2], refs)


@pytest.fixture
def small_source(tmp_path):
    loader = importlib.util.spec_from_file_location('_entity_adapter_hand_fixture', ROOT / 'tests/test_entity_group_ledger.py')
    hand = importlib.util.module_from_spec(loader); loader.loader.exec_module(hand)
    public = hand.specification(); book = openpyxl.Workbook(); book.remove(book.active)
    bindings = emit_entity_group_workbook(book, public)
    from sheets_factory.workbook.entity_group.ledger import simulate
    source = tmp_path / 'small_source.xlsx'; book.save(source); book.close()
    proof = {'bindings': write_new(tmp_path / 'bindings.json', bindings),
        'public_specification': write_new(tmp_path / 'public.json', public),
        'independent_ledger': write_new(tmp_path / 'independent_ledger.json', simulate(public)),
        'source_manifest': {'fixture': 'no actual source admission'}, 'financial_audits': [], 'workbook': reference(source)}
    return SimpleNamespace(public=public, bindings=bindings, source=source, proof=proof)


def test_complete_small_inventory_is_deterministic_and_not_model_selected(small_source):
    case = small_source; original = case.source.read_bytes()
    first = adapter.propose_from_checked_proof(case.source, case.proof)
    assert adapter.propose_from_checked_proof(case.source, case.proof) == first
    assert case.source.read_bytes() == original
    assert first['title'] and 'mask_ranges' not in first and first['scenario_inputs'] == []
    assert first['family_adapter']['physical_formula_mutation_count'] == 126
    assert all(row['complete_logical_field_bindings'] == 18 and row['selected'] == 18
               for row in first['family_adapter']['complete_predeclared_policy_inventory'].values())
    assert first['family_adapter']['mutations_truncated'] is False
    assert first['family_adapter']['selection_uses_model_outcomes'] is False
    assert 'do not add' in first['public_instruction'].lower()
    assert set(first['public_rules']).isdisjoint(adapter.POLICIES.values())
    assert {item['mutation_policy'] for item in first['edits']} == set(adapter.POLICIES)


def test_actual_factory_claim_route_does_not_treat_debug_plan_as_FM_mask(small_source):
    from sheets_factory.pipelines.factory import FactoryPipeline
    plan = adapter.propose_from_checked_proof(small_source.source, small_source.proof)
    pipeline = object.__new__(FactoryPipeline)
    pipeline.config = {'run': {'max_target_overlap': .8}}
    pipeline.lock, pipeline.target_claims = threading.Lock(), {}
    recorded = []
    pipeline.audit = SimpleNamespace(snapshot=lambda: {'tasks': []},
        task=lambda *args, **kwargs: recorded.append(kwargs))
    ctx = SimpleNamespace(task_id='offline-only', mode='debugging',
        data={'plan': plan, 'source_id': small_source.proof['workbook']['sha256']})
    pipeline._claim_targets(ctx)
    assert recorded[-1]['target_fingerprint'] == ctx.data['target_fingerprint']
    assert len(recorded[-1]['targets']) == 126
    assert ctx.data['plan'] is plan and 'mask_ranges' not in plan


@pytest.mark.parametrize('change', ['source_formula', 'row_label', 'missing_logical_field'])
def test_inventory_rejects_source_or_complete_binding_drift(small_source, tmp_path, change):
    case = small_source; binding = deepcopy(case.bindings)
    if change == 'source_formula':
        book = openpyxl.load_workbook(case.source)
        cell = adapter.propose_from_checked_proof(case.source, case.proof)['edits'][0]
        book[cell['sheet']][cell['cell']] = '=42'; book.save(case.source); book.close()
    elif change == 'row_label':
        first = next(item for item in binding['formula_bindings'] if item['label'].endswith('/bank_interest'))
        first['label'] = first['label'].replace('E01', 'E99')
    else:
        binding['output_bindings'] = [item for item in binding['output_bindings']
            if not (item['encoding'] == 'scalar' and item['path'][-1] == 'current_tax')]
    if change != 'source_formula': case.proof['bindings'] = write_new(tmp_path / 'drifted_bindings.json', binding)
    with pytest.raises((ValueError, KeyError)): adapter.propose_from_checked_proof(case.source, case.proof)


@pytest.mark.parametrize('name,ordinary', [('Profile', adapter.normal.ProfileNode), ('Plan', adapter.normal.PlanNode),
    ('Construct', adapter.normal.ConstructNode), ('Repair', adapter.quality.RepairNode),
    ('Diagnose', adapter.quality.DiagnoseNode), ('Export', adapter.quality.ExportNode)])
def test_without_opt_in_ordinary_nodes_are_unchanged(monkeypatch, name, ordinary):
    monkeypatch.setattr(ordinary, 'execute', lambda self, ctx: {'ordinary': name})
    assert getattr(adapter, 'EntityGroup' + name + 'Node')().execute(SimpleNamespace(config={})) == {'ordinary': name}


def test_partial_or_failed_engineering_manifest_never_admits(tmp_path):
    with pytest.raises(ValueError): admission.validate_source(write_new(tmp_path / 'partial.json', {'kind': admission.SOURCE_KIND}))
    with pytest.raises(ValueError): admission.validate_source(write_new(tmp_path / 'failed.json', {
        'kind': admission.SOURCE_KIND, 'version': 1, 'status': 'source_verified_not_task_or_difficulty_qualified',
        'profile_id': 'G01', 'provided_plan_is_protected': True, 'optimisation_performed': False,
        'financial_audit_passed': False, 'quality_or_difficulty_certified': False, 'qualified': False, 'task_count': 0}))


def test_admitted_proof_binds_current_implementation_and_all_source_artifacts(tmp_path, monkeypatch):
    artifact = tmp_path / 'source.fixture'; artifact.write_bytes(b'File-integrity unit boundary, not an XLSX proof.')
    ref = reference(artifact)
    proof = {'kind': admission.KIND, 'version': 1, 'admission_implementation': reference(admission.__file__),
        'financial_seed_verified': True, 'artifact_sha256': {ref['path']: ref['sha256']},
        'source_manifest': ref, 'workbook': ref, 'bindings': ref, 'runtime_profile': ref}
    with pytest.raises(ValueError): admission.verify_admitted_proof(proof)
    # The full-admission boundary is mocked only to isolate the rehash guard;
    # a handmade flag and implementation digest above did not admit anything.
    monkeypatch.setattr(admission, 'validate_source', lambda value: deepcopy(proof))
    assert admission.verify_admitted_proof(proof) is proof
    artifact.write_bytes(b'Changed')
    with pytest.raises(ValueError): admission.verify_admitted_proof(proof)


@pytest.mark.parametrize('valid_witness', [False, True])
def test_strict_family_witness_gate_cannot_be_bypassed_by_verified_boolean(tmp_path, monkeypatch, valid_witness):
    checks = [f'Q{i:02d}' for i in range(1, 13)]
    class Runner:
        catalog = {}
        def __init__(self, *args): pass
        def diagnose(self, bundle, traces, controls, review, config, **kwargs):
            assert bundle['private']['source_assessment'] == {'full': 'original private financial evidence'}
            assert 'source_assessment' not in bundle['public']
            return {'issues': [], 'routes': [], 'releasable': True, 'enabled_check_ids': checks,
                'assessments': {key: {'state': 'clear', 'reason': 'Mock backend boundary'} for key in checks},
                'coverage': {}, 'scope': 'all_twelve_test_fixture'}
        def resolve(self, config): return {'difficulty_deferred': False}
    monkeypatch.setattr(adapter, 'enabled', lambda ctx: True)
    monkeypatch.setattr(adapter, 'context_proof', lambda ctx: {})
    monkeypatch.setattr(adapter, 'validate_reference_policy_selection', lambda config: 'independent_public_recovery')
    monkeypatch.setattr(adapter, 'valid_entity_group_recovery_witness', lambda ctx, candidate: valid_witness)
    monkeypatch.setattr(adapter, 'DiagnosisRunner', Runner)
    monkeypatch.setattr(adapter, 'route_issues', lambda issues, *args: [{'issue_id': item['issue_id']} for item in issues])
    monkeypatch.setattr(adapter, 'prompt', lambda *args: 'Fixture diagnosis prompt')
    monkeypatch.setattr(adapter, 'candidate_difficulty_context', lambda config: {})
    path = tmp_path / 'input.fixture'; path.write_bytes(b'Public fixture only')
    profile = {'sheet_count': 6, 'nonempty_sheet_count': 6, 'formula_count': 2802,
        'errors': [], 'external_references': [], 'sheets': []}
    data = {'instruction': 'Public fixture', 'public_profile': profile, 'profile': profile,
        'input': path, 'goal': path, 'revision_hash': 'test_revision',
        'plan': {'public_rules': ['Public policy'], 'edits': []}, 'construction_validation': {},
        'delta': {}, 'root_impacts': [], 'recovery': {'verified': True},
        'source_assessment': {'full': 'original private financial evidence'}, 'traces': [],
        'controls': {}, 'engine_report': {}}
    audit = SimpleNamespace(task=lambda *a, **kw: None, emit=lambda *a, **kw: None)
    ctx = SimpleNamespace(config={'agents': {}, 'project_root': str(ROOT), 'diagnosis': {}}, data=data,
        task_id='offline-fixture', revision=0, mode='debugging', llm=SimpleNamespace(model='No actual model'), audit=audit,
        save=lambda *a, **kw: None)
    result = adapter.EntityGroupDiagnoseNode().execute(ctx)['diagnosis']
    assert set(result['assessments']) == set(checks)
    assert result['mandatory_gates']['independent_recovery']['passed'] is valid_witness
    assert result['releasable'] is valid_witness
    assert bool(result['issues']) is not valid_witness


def test_export_rejects_unbound_family_witness_before_writing(monkeypatch):
    monkeypatch.setattr(adapter, 'enabled', lambda ctx: True)
    monkeypatch.setattr(adapter, 'context_proof', lambda ctx: {})
    monkeypatch.setattr(adapter, 'valid_entity_group_recovery_witness', lambda *args: False)
    monkeypatch.setattr(adapter, 'export_resource_harbor', lambda *a, **kw: pytest.fail('No export with invalid witness'))
    with pytest.raises(ValueError, match='strictly bound'):
        adapter.EntityGroupExportNode().execute(SimpleNamespace(data={'recovery': {'verified': True}}))


def test_export_records_actual_base_tag_binding_before_resource_export(tmp_path, monkeypatch):
    events, saved = [], []
    monkeypatch.setattr(adapter, 'enabled', lambda ctx: True)
    monkeypatch.setattr(adapter, 'context_proof', lambda ctx: {})
    monkeypatch.setattr(adapter, 'valid_entity_group_recovery_witness', lambda *args: True)
    actual = {'actual_local_image_verified': True, 'actual_container_resources_verified': False}
    def verify(profile): events.append(('verify', profile)); return actual
    def export(*args, **kwargs): events.append(('export', kwargs['runtime_profile']))
    monkeypatch.setattr(adapter, 'verify_local_base_image', verify)
    monkeypatch.setattr(adapter, 'export_resource_harbor', export)
    monkeypatch.setattr(adapter, 'inspect_resource_export', lambda path: {
        'task_id': 'offline-only', 'revision': 0, 'revision_hash': 'current'})
    task = tmp_path / 'task'; task.mkdir()
    value = config(); value.update(run_dir=str(tmp_path), project_root=str(ROOT),
        engine={'image': 'sheetsfactory-lo:24.2-iterative-openpyxl315-v1'})
    ctx = SimpleNamespace(config=value, directory=task, revision_dir=task / 'revisions/000',
        source=tmp_path / 'source.fixture', task_id='offline-only', mode='debugging', revision=0,
        data={'source_id': 'a'*64, 'revision_hash': 'current', 'recovery': {'verified': True}},
        save=lambda name, value: saved.append((name, value)))
    result = adapter.EntityGroupExportNode().execute(ctx)
    assert [item[0] for item in events] == ['verify', 'export']
    assert events[0][1] == events[1][1] == value[adapter.SETTING]['runtime_profile']['path']
    assert saved == [('entity_group_actual_local_base_image.json', actual)]
    assert result['export_dir'] == tmp_path / 'SpreadsheetEval/offline-only'


@pytest.fixture
def source_protocol(tmp_path, monkeypatch):
    """Explicit fake source-builder boundary, not a financial/source proof."""
    profile_ref = reference(ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml')
    profile = adapter.load_runtime_profile(profile_ref['path'])
    public = {'fixed_plan': {'PUBLIC_TEST_ONLY': 1}}
    pub = write_new(tmp_path / 'public.json', public)
    ledger = {'feasible': True, 'fixed_plan': public['fixed_plan']}
    ledger_ref = write_new(tmp_path / 'ledger.json', ledger)
    reachability = write_new(tmp_path / 'activation.json', {'passed': True, 'feasible': True,
        'scenarios': {sid: {'entity_months_checked': 2880, 'all_entities_economically_active': True,
            'all_mechanisms_with_dated_economic_evidence': True,
            'mechanisms': {str(i): {'active': True, 'count': 1, 'witnesses': ['Explicit fake protocol witness']}
                for i in range(14)}} for sid in ('S01', 'S02', 'S03')}})
    count = {'physical_formula_count': 3, 'physical_nonempty_cells': 9,
        'logical_output_binding_count': 3, 'binding_encodings': {'scalar': 1, 'exact_integer_pair': 1, 'queues': 1}}
    count_ref = write_new(tmp_path / 'count.json', count)
    frozen = {'recipe_sha256': {}, 'public_specification': pub, 'runtime_profile': profile,
        'resource_count': count, 'evidence': {'runtime_profile': profile_ref, 'count_receipt': count_ref,
            'forward': {'result': ledger_ref, 'reachability': reachability}}}
    preparation = write_new(tmp_path / 'preparation.json', frozen)
    builder = SimpleNamespace(validate_prepared=lambda path: (frozen, public, ledger),
        load_profile=lambda record: profile, validate_resources=lambda *a, **kw: None)
    monkeypatch.setattr(admission, 'source_builder', lambda: builder)
    calls, audits, resources = [], [], []
    raw = tmp_path / 'raw_protocol.fixture'; raw.write_bytes(b'Explicit fake engine-input boundary')
    previous = reference(raw)
    for index in range(1, 4):
        path = tmp_path / f'pass{index}.fixture'; path.write_bytes(f'Explicit fake engine-output {index}'.encode())
        output = reference(path)
        started = {'index': index, 'input': previous, 'destination': str(path), 'completed': False,
            'image_id': admission.IMAGE_ID, 'network': 'none', 'runtime_profile': profile_ref,
            'workbook_file_timeout_seconds': 600, 'requested_source_resources': profile['docker_resources']['source']}
        started_ref = write_new(tmp_path / f'started{index}.json', started)
        resource = write_new(tmp_path / f'resource{index}.json', {
            'source': previous, 'output': output, 'destination': str(path)})
        call = {**started, 'completed': True, 'started_receipt': started_ref,
            'actual_resource_receipt': resource, 'output': output}
        terminal = write_new(tmp_path / f'terminal{index}.json', call)
        call['terminal_receipt'] = terminal
        calls.append(call); resources.append(resource)
        audits.append(write_new(tmp_path / f'audit{index}.json', {'workbook': output, 'passed': True,
            'all_independent_journal_fields_covered': True, 'all_scenarios_feasible': True,
            'provided_fixed_plan_verified': True, 'optimisation_performed': False,
            'physical_formulas_checked': 3, 'logical_fields_checked': 8, 'mismatches': [], 'control_mismatches': []}))
        previous = output
    stable = {'passed': True, 'sheet_names_equal': True, 'mismatches': [], 'checked_existing_value_cells': 9}
    stability = write_new(tmp_path / 'stability.json', {'stable': True,
        'first_against_goal': stable, 'second_against_goal': stable})
    binding = write_new(tmp_path / 'binding.json', {'fixture': 'no real workbook or field calculation'})
    manifest = {'kind': admission.SOURCE_KIND, 'version': 1, 'profile_id': 'G01',
        'status': 'source_verified_not_task_or_difficulty_qualified', 'provided_plan_is_protected': True,
        'optimisation_performed': False, 'financial_audit_passed': True,
        'quality_or_difficulty_certified': False, 'qualified': False, 'task_count': 0,
        'entity_count': 24, 'month_count': 120, 'scenario_count': 3, 'actual_LO_recalculations': 3,
        'model_calls': 0, 'ledger_executions_during_build': 0, 'source_preparation': preparation,
        'source_recipe_sha256': {}, 'public_specification': pub, 'forward_execution': frozen['evidence']['forward'],
        'independent_ledger': ledger_ref, 'resource_count_receipt': count_ref, 'count': count,
        'runtime_profile': profile_ref, 'runtime': {'actual_resource_receipts': resources},
        'workbook': calls[0]['output'], 'local_path': calls[0]['output']['path'],
        'derived_workbook_sha256': calls[0]['output']['sha256'], 'engine_calls': calls,
        'financial_audits': audits, 'stability': stability, 'bindings': binding}
    return SimpleNamespace(path=tmp_path, manifest=manifest, frozen=frozen)


def test_complete_source_protocol_requires_all_chains_and_revalidates_proof(source_protocol):
    case = source_protocol
    record = write_new(case.path / 'manifest.json', case.manifest)
    proof = admission.validate_source(record)
    assert proof['logical_fields_checked'] == 8
    assert proof['qualified'] is False and proof['task_count'] == 0
    assert admission.verify_admitted_proof(proof) == proof
    forged = deepcopy(proof); forged['logical_fields_checked'] = 1
    with pytest.raises(ValueError, match='cannot be replaced'):
        admission.verify_admitted_proof(forged)


@pytest.mark.parametrize('change', ['missing_call', 'missing_audit', 'wrong_reference', 'wrong_count', 'failed_audit'])
def test_source_protocol_rejects_missing_or_false_actual_evidence(source_protocol, change):
    case = source_protocol; manifest = deepcopy(case.manifest)
    if change == 'missing_call': manifest['engine_calls'].pop()
    if change == 'missing_audit': manifest['financial_audits'].pop()
    if change == 'wrong_reference': manifest['workbook'] = manifest['engine_calls'][-1]['output']
    if change == 'wrong_count': manifest['count']['physical_formula_count'] += 1
    if change == 'failed_audit':
        audit = admission.read(manifest['financial_audits'][1]); audit['passed'] = False
        manifest['financial_audits'][1] = write_new(case.path / 'bad_audit.json', audit)
    with pytest.raises(ValueError):
        admission.validate_source(write_new(case.path / 'invalid_manifest.json', manifest))


def cached_workbook(path, cache):
    """Write numeric formula caches in a fresh offline fixture, without Calc."""
    from zipfile import ZipFile
    import xml.etree.ElementTree as ET
    main = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    with ZipFile(path) as archive:
        members = [(info, archive.read(info.filename)) for info in archive.infolist()]
    with ZipFile(path, 'w') as archive:
        for info, raw in members:
            if info.filename in cache:
                tree = ET.fromstring(raw)
                for cell in tree.iter(main + 'c'):
                    if cell.attrib['r'] in cache[info.filename]:
                        assert cell.find(main + 'f') is not None
                        node = cell.find(main + 'v')
                        if node is None: node = ET.SubElement(cell, main + 'v')
                        node.text = str(cache[info.filename][cell.attrib['r']])
                raw = ET.tostring(tree, encoding='utf-8')
            archive.writestr(info, raw)


@pytest.fixture
def cached_two_root_workbook(tmp_path):
    source = tmp_path / 'source.xlsx'
    book = openpyxl.Workbook(); book.active.title = 'Inputs'; book['Inputs']['A1'] = 10
    sheet = book.create_sheet('Close'); sheet['B1'] = '=Inputs!A1*2'; sheet['B2'] = '=Inputs!A1*4'
    book.save(source); book.close()
    cached_workbook(source, {'xl/worksheets/sheet2.xml': {'B1': 20, 'B2': 40}})
    return source


def test_native_error_probe_only_expands_the_complete_closure_ceiling(cached_two_root_workbook, tmp_path):
    source = cached_two_root_workbook
    common = {'goal': source, 'required_delta': ['Close!B1', 'Close!B2'], 'candidates': [],
        'engine': None, 'source_sha256': reference(source)['sha256'], 'plan': {}, 'revision': 0,
        'immutable_files': {'source': source}}
    old = contract.original_native_probe.probe_native_errors(**common,
        directory=tmp_path / 'original_probe', max_dependency_cells=3000000)
    assert old['state'] == 'unknown' and old['blocking'] is True
    actual = contract.probe_native_errors(**common, directory=tmp_path / 'family_probe', max_dependency_cells=3000000)
    assert actual['state'] == 'not_applicable' and actual['blocking'] is False
    assert actual['full_dependency_closure_cells'] == 3 and actual['immutable_unchanged'] is True
    assert actual['probes'] == [] and actual['business_correctness_certificate'] is False
    rejected = contract.probe_native_errors(**common, directory=tmp_path / 'oversized_probe', max_dependency_cells=3000001)
    assert rejected['state'] == 'unknown' and rejected['blocking'] is True
    assert adapter.probe_native_errors is contract.probe_native_errors
    contract.validate_upstream_validator()


def test_real_construct_context_reaches_full_native_probe_with_three_million_scope(
        cached_two_root_workbook, tmp_path, monkeypatch):
    """Real node body/XLSX/D/probe; only calculation and joint proof are isolated."""
    import json
    import shutil
    from sheets_factory.core.node import TaskContext
    source = cached_two_root_workbook; source_before = reference(source)
    class FakeEngine:
        calls = 0
        def recalculate(self, raw, output):
            self.calls += 1
            shutil.copy2(raw, output)
            cached_workbook(output, {'xl/worksheets/sheet2.xml': {'B1': 30, 'B2': 50}})
            return output
    engine = FakeEngine(); events = []
    configuration = config(); configuration['project_root'] = str(ROOT)
    plan = {'public_instruction': 'Correct the supplied existing formulas.', 'public_rules': ['Use supplied public rates.'],
        'reference_evidence': ['Offline hand case: 10 times 2 and 4.'], 'edits': [
            {'sheet': 'Close', 'cell': 'B1', 'before': '=Inputs!A1*2', 'after': '=Inputs!A1*3'},
            {'sheet': 'Close', 'cell': 'B2', 'before': '=Inputs!A1*4', 'after': '=Inputs!A1*5'}]}
    ctx = TaskContext(run_id='offline-only', task_id='small-native-probe-smoke', mode='debugging', source=source,
        directory=tmp_path / 'task', config=configuration,
        audit=SimpleNamespace(emit=lambda *args, **kwargs: events.append((args, kwargs))),
        llm=None, engine=engine, data={'baseline': source, 'source_id': source_before['sha256'], 'plan': plan})
    proofs = []
    def joint_boundary(self, context, binding, goal, input_file, draft, edits, delta, private, validation):
        probe = validation['native_error_probe']
        assert probe['analysis_limits']['max_dependency_closure_cells'] == 3000000
        assert probe['state'] == 'not_applicable' and probe['blocking'] is False
        assert probe['full_dependency_closure_cells'] == 3 and probe['immutable_unchanged'] is True
        assert probe['probes'] == [] and probe['business_correctness_certificate'] is False
        assert set(delta['expected_changes']) == {'Close!B1', 'Close!B2'}
        proofs.append(probe)
        return []
    monkeypatch.setattr(adapter.EntityGroupConstructNode, '_prove_activity', joint_boundary)
    # Bypass only production source admission; no handmade source proof is admitted.
    result = adapter.EntityGroupConstructNode()._execute_scc(ctx, {'activity_contract': adapter.METHOD})
    assert engine.calls == 1 and len(proofs) == 1
    assert reference(source) == source_before
    assert result['construction_validation']['dependency_closure_cells'] == 3
    assert result['delta']['expected_change_count'] == 2 and result['root_impacts'] == []
    persisted = json.loads((ctx.revision_dir / 'private/native_error_probe.json').read_text())
    assert persisted == proofs[0]
    assert result['public_profile']['analysis_limits']['max_profile_cells'] == 3000000
    assert any(args == ('native_error_probe.result',) and data['blocking'] is False for args, data in events)
