"""Bounded public wording repair and real controller contracts; no LO/models."""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from sheets_factory.core.node import TaskContext
from sheets_factory.pipelines.factory import FactoryPipeline
from sheets_factory.resume import candidate_task_id, plan_external_repairs, assert_resume_allowed, ResumeError
from sheets_factory.task_adapters import capital_allocation as original
from sheets_factory.task_adapters import capital_public_schema as policy
from sheets_factory.task_adapters.public_workbook_scope import reference, write_new, canonical

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('_capital_schema_entry_tests', ROOT / 'scripts/resume_capital_public_schema_quality.py')
entry = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(entry)


def test_schema_is_an_instruction_only_addition_without_a_solution():
    plan = {'title_if_present': 'unchanged metadata', 'public_instruction': 'Complete the existing forecast.',
            'public_rules': ['Supplied financial rules'], 'edits': [{'cell': 'B3', 'before': '=1', 'after': None}],
            'family_adapter': {'unchanged': True}, 'scenario_inputs': []}
    before = deepcopy(plan); result = policy.append_schema(plan)
    assert plan == before
    assert result['public_instruction'] == plan['public_instruction'] + '\n\n' + policy.CLAUSE
    assert {k: v for k, v in result.items() if k != 'public_instruction'} == {k: v for k, v in plan.items() if k != 'public_instruction'}
    assert 'rows 3–5 represent S01–S03' in policy.CLAUSE
    assert 'unweighted candidate asset schedules' in policy.CLAUSE
    assert '24052' not in policy.CLAUSE and 'best plan' not in policy.CLAUSE
    with pytest.raises(ValueError, match='already explicit'): policy.append_schema(result)


def test_registry_retains_every_original_route_and_all_mandatory_gates():
    original_nodes = yaml.safe_load((ROOT / 'config/task_adapters/capital_allocation_nodes.yaml').read_text())['nodes']
    actual = yaml.safe_load((ROOT / 'config/task_adapters/capital_public_schema_nodes.yaml').read_text())['nodes']
    assert actual == policy.registry_nodes(original_nodes)
    assert {k for k in original_nodes if actual[k] != original_nodes[k]} == {'repair'}
    assert len(actual) == 11
    assert actual['construct'] == 'sheets_factory.task_adapters.capital_allocation:CapitalAllocationConstructNode'
    assert actual['precheck'] == 'sheets_factory.nodes.construction:ControlsNode'


@pytest.fixture
def repair_context(tmp_path):
    source = tmp_path / 'source.xlsx'; source.write_bytes(b'Explicit non-workbook source-identity boundary fixture')
    source_ref = reference(source); task_id = 'fm-' + source_ref['sha256'][:12]
    input_path = tmp_path / 'old_input.xlsx'; input_path.write_bytes(b'Explicit public byte-binding boundary fixture')
    instruction = tmp_path / 'instruction.md'; instruction.write_text('Original public instruction.')
    plan = {'public_instruction': instruction.read_text(), 'public_rules': ['Existing financial policy'],
        'scenario_inputs': [], 'edits': [{'sheet': 'Fixture only', 'cell': 'A' + str(i + 1),
            'before': '=1', 'after': None} for i in range(19049)],
        'family_adapter': {'id': original.ADAPTER_ID, 'physical_target_count': 19049,
            'financial_target_count': 19031, 'decision_target_count': 18}}
    plan_ref = write_new(tmp_path / 'plan.json', plan)
    issue = {'issue_id': 'Q02-public-schema-fixture', 'problem_id': 'Q02', 'route_id': 'R02', 'certainty': 'confirmed'}
    diagnosis = write_new(tmp_path / 'diagnosis.json', {'issues': []})
    review = write_new(tmp_path / 'review.json', {'issues': [issue], 'LLM_assessments_synthesized': False})
    evidence = {'financial_seed_verified': True, 'financial_modeling_eligible': True,
                'audited_source_binding': {'full_financial_audits': ['complete immutable audit fixture'],
                                           'source_manifest': {'all_original_fields': True}}}
    auth = {'revision': 0, 'revision_hash': hashlib.sha256(input_path.read_bytes() + instruction.read_bytes()).hexdigest(),
        'source_sha256': source_ref['sha256'], 'plan': plan_ref, 'input': reference(input_path),
        'instruction': reference(instruction), 'goal': source_ref, 'baseline': source_ref,
        'diagnosis': diagnosis, 'program_review': review, 'authorized_issue_ids': [issue['issue_id']]}
    manifest = {'kind': policy.KIND, 'version': 1, 'clause': policy.CLAUSE,
        'quality_or_difficulty_certified': False, 'forensic_receipts': [review],
        'sources': {source_ref['sha256']: {'source': source_ref, 'financial_evidence': evidence}},
        'tasks': {task_id: auth}}
    manifest_path = tmp_path / 'policy.json'; manifest_ref = write_new(manifest_path, manifest)
    ctx = TaskContext('offline-test', task_id, 'financial_modeling', source, tmp_path / 'task',
        {policy.SETTING: policy.setting(manifest_ref)}, None, None, None, revision=0,
        data={'baseline': source, 'plan': plan, 'finance_evidence': evidence,
              'diagnosis': {'issues': [issue]}, 'repair_routes': [{**issue, 'route_class': 'repair'}]})
    return SimpleNamespace(ctx=ctx, manifest=manifest, manifest_path=manifest_path, auth=auth, source=source,
                           evidence=evidence, issue=issue, old_plan=deepcopy(plan))


def test_authorized_repair_preserves_19049_targets_and_restores_full_source_assessment(repair_context):
    case = repair_context; ctx = case.ctx
    result = policy.CapitalPublicSchemaRepairNode().execute(ctx)
    assert len(result['next_plan']['edits']) == 19049
    assert {k: v for k, v in result['next_plan'].items() if k != 'public_instruction'} == {
        k: v for k, v in case.old_plan.items() if k != 'public_instruction'}
    assert ctx.data['plan'] == case.old_plan == policy.read(case.auth['plan'])
    assert result['source_assessment'] == policy.source_assessment(case.evidence)
    assert result['source_assessment']['financial_evidence'] is not case.evidence
    receipt = json.loads((ctx.revision_dir / 'private/capital_public_schema_repair.json').read_bytes())
    assert receipt['changed_plan_fields'] == ['public_instruction'] and receipt['old_diagnostics_cleared'] is False
    assert 'title' not in result['next_plan']


def test_restored_assessment_is_exactly_original_capital_plan_behavior(repair_context, monkeypatch):
    case = repair_context
    monkeypatch.setattr(original, '_context', lambda ctx: {'source_manifest': {}, 'workbook': {}})
    monkeypatch.setattr(original, '_propose_from_checked_proof', lambda *args: {'edits': []})
    old_ctx = SimpleNamespace(data={'baseline': case.source, 'finance_evidence': case.evidence}, save=lambda *a: None)
    result = original.CapitalAllocationPlanNode().execute(old_ctx)
    assert policy.source_assessment(case.evidence) == result['source_assessment']


@pytest.mark.parametrize('change,match', [
    ('revision', 'exact authorized'), ('boolean_revision', 'exact authorized'),
    ('source', 'bytes or SHA'), ('evidence', 'finance evidence'),
    ('assessment', 'source facts'), ('target_count', 'original plan'), ('route', 'exact authorized'),
])
def test_repair_fails_closed_on_changed_authorization_or_business_context(repair_context, change, match):
    case = repair_context; ctx = case.ctx
    if change == 'revision': ctx.revision = 1
    if change == 'boolean_revision': ctx.revision = False
    if change == 'source': case.source.write_bytes(b'Changed source')
    if change == 'evidence': ctx.data['finance_evidence'] = {'summary_only': True}
    if change == 'assessment': ctx.data['source_assessment'] = {'different_business_fact': True}
    if change == 'target_count': ctx.data['plan']['edits'].pop()
    if change == 'route': ctx.data['repair_routes'][0]['route_id'] = 'R03'
    with pytest.raises(ValueError, match=match): policy.CapitalPublicSchemaRepairNode().execute(ctx)


def test_boolean_policy_version_is_rejected(repair_context):
    case = repair_context; case.manifest['version'] = True
    case.manifest_path.write_text(json.dumps(case.manifest))
    case.ctx.config[policy.SETTING] = policy.setting(reference(case.manifest_path))
    with pytest.raises(ValueError, match='policy changed'): policy.CapitalPublicSchemaRepairNode().execute(case.ctx)


@pytest.mark.parametrize('unrelated', [True, False])
def test_missing_optin_or_unrelated_issue_keeps_ordinary_repair(repair_context, monkeypatch, unrelated):
    case = repair_context
    if unrelated: case.ctx.data['repair_routes'][0]['problem_id'] = 'Q04'
    else: case.ctx.config = {}
    monkeypatch.setattr(policy.RepairNode, 'execute', lambda self, ctx: {'ordinary_route': True})
    assert policy.CapitalPublicSchemaRepairNode().execute(case.ctx) == {'ordinary_route': True}


def test_controller_copy_matches_original_except_the_one_display_lookup():
    entry.validate_controller_copy()
    assert 'DISPLAY_TITLE' in entry.CapitalSchemaFactory._execute_context.__code__.co_names


def test_actual_context_reaches_ready_without_mutating_a_titleless_plan(tmp_path):
    records, phases = [], []
    audit = SimpleNamespace(emit=lambda *a, **kw: None, task=lambda *a, **kw: records.append(kw))
    instance = object.__new__(entry.CapitalSchemaFactory)
    instance.config = {'run': {'max_steps': 3}}
    instance.audit, instance.reference_validation_method = audit, 'independent_public_recovery'
    instance._checkpoint = lambda: None; instance._claim_targets = lambda ctx: None
    def run_phase(ctx, phase):
        phases.append(phase)
        if phase == 'revision':
            ctx.data['diagnosis'] = {'releasable': True, 'issues': [], 'routes': [], 'coverage': {}}
        if phase == 'export': ctx.data['export_dir'] = tmp_path / 'export'
    instance.run_phase = run_phase
    plan = {'public_instruction': 'Public text', 'edits': [{'unchanged': True}]}
    ctx = TaskContext('offline', 'fm-context', 'financial_modeling', tmp_path / 'fixture.xlsx', tmp_path,
        instance.config, audit, None, None, data={'plan': deepcopy(plan), 'recovery': {'verified': True}})
    instance._execute_context(ctx)
    assert phases == ['revision', 'export']
    assert records[-1]['status'] == 'ready' and records[-1]['title'] == entry.DISPLAY_TITLE
    assert records[-1]['harbor_controls'] is None
    assert ctx.data['plan'] == plan and 'title' not in ctx.data['plan']
    with pytest.raises(KeyError, match='title'): FactoryPipeline._execute_context(instance, ctx)


def test_rejected_title_failure_is_eligible_for_actual_bounded_external_repair(tmp_path):
    source = tmp_path / 'source.xlsx'; source.write_bytes(b'Offline identity fixture, not a financial workbook')
    seed = {'sha256': reference(source)['sha256'], 'local_path': str(source), 'variant': 0}
    task_id = candidate_task_id(seed, 'financial_modeling')
    manifest = write_new(tmp_path / 'seeds.json', {'selected': [seed]})
    run = tmp_path / 'run'; private = run / 'tasks' / task_id / 'revisions/000/private'; private.mkdir(parents=True)
    write_new(private / 'plan.json', {'public_instruction': 'Old schema', 'edits': []})
    write_new(private / 'diagnosis.json', {'issues': []})
    baseline = run / 'sources' / seed['sha256'][:12] / 'baseline.xlsx'; baseline.parent.mkdir(parents=True)
    baseline.write_bytes(source.read_bytes())
    review = write_new(tmp_path / 'review.json', {'task_id': task_id, 'revision': 0, 'issues': [{
        'issue_id': 'Q02-actual-schema', 'problem_id': 'Q02', 'route_id': 'R02', 'certainty': 'confirmed',
        'claim': 'Missing public reporting schema', 'evidence': ['Offline numbered evidence fixture']}]})
    snapshot = {'run': {'status': 'shortfall', 'producer_active': False}, 'nodes': [], 'calls': [],
        'tasks': [{'id': task_id, 'mode': 'financial_modeling', 'status': 'rejected', 'revision': 0,
                   'source_id': seed['sha256'], 'variant': 0, 'error': "'title'"}]}
    config = {'project_root': str(ROOT), 'run': {'max_steps': 3, 'seed_manifest': manifest['path']}}
    original = deepcopy(snapshot)
    assert_resume_allowed(run, snapshot, producer_probe=lambda *args: [])
    result = plan_external_repairs(run, snapshot, config, [task_id], [review['path']])
    assert len(result) == 1 and result[0]['revision'] == 0 and result[0]['routes'][0]['route_id'] == 'R02'
    assert snapshot == original and config['run']['max_steps'] == 3
    exhausted = deepcopy(snapshot); exhausted['tasks'][0]['revision'] = 3
    with pytest.raises(ResumeError, match='budget exhausted'):
        plan_external_repairs(run, exhausted, config, [task_id], [review['path']])
    with pytest.raises(ResumeError, match='still alive'):
        assert_resume_allowed(run, snapshot, producer_probe=lambda *args: [123])


def test_cli_does_not_resume_or_start_models_without_explicit_run(tmp_path, monkeypatch):
    monkeypatch.setattr(entry, 'validate_prepared', lambda *args: {'offline': True})
    monkeypatch.setattr(entry, 'execute', lambda *args, **kw: pytest.fail('Unexpected execution'))
    monkeypatch.setattr(entry, 'prepare_resume', lambda *args, **kw: pytest.fail('Unexpected resume transition'))
    assert entry.main(['--prepared', str(tmp_path)]) == 0
    with pytest.raises(ValueError, match='Prepare a terminal'):
        entry.main(['--run', '--run-directory', str(tmp_path)])


@pytest.fixture
def forensic_case(tmp_path, monkeypatch):
    input_path, goal, instruction = (tmp_path / name for name in ('input.xlsx', 'goal.xlsx', 'instruction.md'))
    input_path.write_bytes(b'Public input byte fixture'); goal.write_bytes(b'Reference byte fixture')
    instruction.write_text('Public incomplete schema fixture')
    revision_hash = hashlib.sha256(input_path.read_bytes() + instruction.read_bytes()).hexdigest()
    goal_ref = reference(goal); task_id = 'fm-' + goal_ref['sha256'][:12]
    selection = write_new(tmp_path / 'selection.json', {'tasks': [{'task_id': task_id, 'revision': 0,
        'revision_hash': revision_hash, 'source_id': goal_ref['sha256']}]})
    first_payload = {'kind': 'capital_K01_first_development_independent_readonly_forensic', 'version': 1,
        'same_plan': True, 'prior_proof_best_plan_matches': True, 'annual_financial_mismatches': [],
        'selected_project_mismatches': [], 'new_model_calls': 0, 'new_LO_calls': 0, 'frozen_files_modified': False,
        'selection_manifest': selection, 'original_files': {'input': reference(input_path), 'goal': goal_ref},
        'public_instruction': reference(instruction)}
    forensic = write_new(tmp_path / 'machine.json', first_payload)
    final_payload = {'kind': 'capital_K01_first_development_forensic_completion', 'version': 1,
        'original_forensic_receipt': forensic, 'public_summary_roles_not_labelled': True,
        'public_unweighted_candidate_project_convention_not_explicit': True,
        'public_contract_clarity_blocks_release_difficulty_claim': True,
        'tax_actual_mismatches': [], 'tax_gold_mismatches': [], 'filled_outside_authorized_targets': [],
        'new_model_calls': 0, 'new_LO_calls': 0, 'frozen_files_modified': False}
    completion = write_new(tmp_path / 'completion.json', final_payload)
    # The production entry has hard-coded reviewed real receipt SHAs. Tests
    # explicitly replace these constants only for isolated hash-bound fixtures.
    monkeypatch.setattr(entry, 'FORENSIC_SHA', forensic['sha256'])
    monkeypatch.setattr(entry, 'COMPLETION_SHA', completion['sha256'])
    return SimpleNamespace(forensic=forensic, completion=completion, first_payload=first_payload,
        final_payload=final_payload, args={'task_id': task_id, 'revision': 0, 'revision_hash': revision_hash,
        'input_ref': reference(input_path), 'goal_ref': goal_ref, 'instruction_ref': reference(instruction)})


def test_external_review_requires_both_exact_machine_receipts_without_synthesizing_QA(forensic_case):
    case = forensic_case
    artifacts = entry.validate_forensic_basis(case.forensic, case.completion, **case.args)
    assert artifacts[case.forensic['path']] == case.forensic['sha256']
    assert artifacts[case.completion['path']] == case.completion['sha256']
    issue = entry.issue_for(case.args['task_id'], 0, case.args['revision_hash'], case.forensic, case.completion, case.args['instruction_ref'])
    assert issue['problem_id'] == 'Q02' and issue['route_id'] == 'R02'
    assert 'assessments' not in issue and 'releasable' not in issue


@pytest.mark.parametrize('change', ['receipt_hash', 'revision', 'revision_hash', 'task', 'instruction', 'goal'])
def test_actual_review_cannot_transfer_to_another_hash_or_revision(forensic_case, change):
    case = forensic_case; args = deepcopy(case.args); forensic = deepcopy(case.forensic)
    if change == 'receipt_hash': forensic['sha256'] = '0' * 64
    if change == 'revision': args['revision'] = 1
    if change == 'revision_hash': args['revision_hash'] = '0' * 64
    if change == 'task': args['task_id'] = 'fm-other'
    if change in ('instruction', 'goal'): args[change + '_ref']['sha256'] = '0' * 64
    with pytest.raises(ValueError): entry.validate_forensic_basis(forensic, case.completion, **args)


def test_missing_completed_public_schema_finding_cannot_authorize_a_repair(forensic_case, monkeypatch):
    case = forensic_case; payload = deepcopy(case.final_payload)
    payload['public_summary_roles_not_labelled'] = False
    path = Path(case.completion['path']); path.write_text(json.dumps(payload))
    changed = reference(path); monkeypatch.setattr(entry, 'COMPLETION_SHA', changed['sha256'])
    with pytest.raises(ValueError, match='finding is absent'):
        entry.validate_forensic_basis(case.forensic, changed, **case.args)


def test_fresh_preparation_uses_actual_rejected_route_without_mutating_old_run(forensic_case, tmp_path, monkeypatch):
    case = forensic_case; task_id = case.args['task_id']; source = Path(case.args['goal_ref']['path'])
    run = tmp_path / 'original_run'; private = run / 'tasks' / task_id / 'revisions/000/private'
    public = private.parent / 'public'; private.mkdir(parents=True); public.mkdir()
    (public / 'input.xlsx').write_bytes(Path(case.args['input_ref']['path']).read_bytes())
    (public / 'instruction.md').write_bytes(Path(case.args['instruction_ref']['path']).read_bytes())
    (private / 'goal.xlsx').write_bytes(source.read_bytes())
    baseline = run / 'sources' / case.args['goal_ref']['sha256'][:12] / 'baseline.xlsx'
    baseline.parent.mkdir(parents=True); baseline.write_bytes(source.read_bytes())
    write_new(private / 'plan.json', {'public_instruction': 'Original public text', 'edits': [], 'public_rules': ['Keep supplied financial policies']})
    write_new(private / 'diagnosis.json', {'task_revision_hash': case.args['revision_hash'], 'issues': []})
    source_manifest = write_new(tmp_path / 'source_manifest.json', {'test_validation_boundary': True})
    proof = {'workbook': case.args['goal_ref'], 'source_manifest': source_manifest,
             'validation_method': 'explicit_mocked_source_admission_for_startup_test'}
    seed_manifest = write_new(tmp_path / 'seeds.json', {'selected': [{'sha256': case.args['goal_ref']['sha256'],
        'local_path': str(source), 'variant': 0, 'finance_evidence': {'audited_source_binding': proof,
        'financial_seed_verified': True, 'financial_modeling_eligible': True}}]})
    config = {'project_root': str(ROOT), 'run_dir': str(run), 'run': {'targets': {'financial_modeling': 1, 'debugging': 0},
        'max_steps': 3, 'max_evidence_rounds_per_revision': 2, 'infrastructure_retries_per_stage': 2,
        'max_additional_trials_per_revision': 0, 'seed_manifest': seed_manifest['path']},
        'agents': {'model': 'gpt-6-sol', 'reasoning_effort': 'high'},
        'diagnosis': {'selection': {'include': 'all', 'exclude': []}},
        'recovery': {'compiler_backend': 'capital_allocation_integer', 'replay_timeout_seconds': 1800},
        'pipeline': {'node_registry': str(ROOT / 'config/task_adapters/capital_allocation_nodes.yaml')}}
    (run / 'resolved_config.yaml').write_text(yaml.safe_dump(config)); write_new(run / 'preflight_manifest.json', {'fixture': True})
    snapshot = {'run': {'status': 'shortfall', 'producer_active': False}, 'nodes': [{'task_id': task_id,
        'revision': 0, 'node': 'diagnose', 'status': 'completed'}], 'calls': [],
        'tasks': [{'id': task_id, 'revision': 0, 'mode': 'financial_modeling', 'source_id': case.args['goal_ref']['sha256'],
                   'variant': 0, 'status': 'rejected', 'error': "'title'"}]}
    old_files = {str(p): p.read_bytes() for p in run.rglob('*') if p.is_file()}
    monkeypatch.setattr(entry, 'read_run', lambda path: deepcopy(snapshot))
    monkeypatch.setattr(entry.phase, 'validate_prepared', lambda path: ({'prepared_seed_manifest': seed_manifest,
        'source_manifest': source_manifest, 'recipe_sha256': {}}, deepcopy(config), proof))
    monkeypatch.setattr(entry, 'DiagnosisRunner', lambda root: SimpleNamespace(resolve=lambda cfg: {
        'enabled_check_ids': [f'Q{i:02d}' for i in range(1, 13)]}))
    monkeypatch.setattr(entry, 'prepare_resume', lambda *a, **kw: pytest.fail('Preparation cannot change the producer/audit'))
    output = tmp_path / 'continuation'
    record = entry.prepare(run, case.forensic['path'], case.completion['path'], output)
    frozen = entry.validate_prepared(output)
    assert reference(output / 'preflight_manifest.json') == record
    assert frozen['before_revision'] == 0 and frozen['prepare_resume_called'] is False
    assert frozen['protected_budgets']['max_steps'] == 3
    assert {str(p): p.read_bytes() for p in run.rglob('*') if p.is_file()} == old_files
    review = policy.read(frozen['review_files'][0])
    assert review['LLM_assessments_synthesized'] is False and len(review['issues']) == 1
    assert 'assessments' not in review and review['issues'][0]['problem_id'] == 'Q02'
    patch = policy.read(frozen['config_patch'])
    assert set(patch) == {'pipeline', policy.SETTING}
