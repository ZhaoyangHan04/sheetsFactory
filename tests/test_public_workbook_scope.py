"""Offline scope/routing tests. Dummy receipts never certify financial truth."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from sheets_factory.core.node import TaskContext, TaskRejected
from sheets_factory.pipelines.factory import FactoryPipeline
from sheets_factory.task_adapters import public_input_priority as priority
from sheets_factory.task_adapters import public_workbook_scope as scope

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_scope_entry_test', ROOT / 'scripts/resume_public_workbook_scope_quality.py')
entry = importlib.util.module_from_spec(spec); spec.loader.exec_module(entry)


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')
    return scope.reference(path)


@pytest.fixture
def fixture(tmp_path):
    source = tmp_path / 'source.xlsx'
    source.write_bytes(b'Offline source identity fixture, not a financial workbook')
    source_ref = scope.reference(source); identity = source_ref['sha256']
    task_id = 'fm-' + identity[:12]
    run = tmp_path / 'run'; private = run / 'tasks' / task_id / 'revisions/001/private'
    public = private.parent / 'public'; private.mkdir(parents=True); public.mkdir()
    baseline = run / 'sources' / identity[:12] / 'baseline.xlsx'
    baseline.parent.mkdir(parents=True); baseline.write_bytes(source.read_bytes())
    goal = private / 'goal.xlsx'; goal.write_bytes(source.read_bytes())
    masked = public / 'input.xlsx'; masked.write_bytes(b'Offline masked fixture')
    instruction = public / 'instruction.md'; instruction.write_text('Preserve inputs, existing structure and unrelated formulas; allow dependent results to recalculate.\n')
    revision_hash = hashlib.sha256(masked.read_bytes() + instruction.read_bytes()).hexdigest()
    plan = {'public_instruction': 'Complete the missing financial formulas in the supplied model.',
        'public_rules': [priority.RULE], 'target_sheets': ['Forecast'],
        'edits': [{'sheet': 'Forecast', 'cell': 'C3', 'before': '=B3*2', 'after': None}],
        'scenario_inputs': [], 'reference_evidence': ['Private reference stays private']}
    plan_ref = dump(private / 'plan.json', plan)
    old_issue = {'issue_id': 'retained-Q04', 'problem_id': 'Q04', 'certainty': 'suspected',
                 'claim': 'Unrelated evidence question', 'evidence': ['offline fixture']}
    diagnosis = {'task_revision_hash': revision_hash, 'issues': [old_issue],
                 'assessments': {'Q04': {'state': 'unknown'}}, 'releasable': False}
    diagnosis_ref = dump(private / 'diagnosis.json', diagnosis)
    verifier = ROOT / 'src/sheets_factory/evaluation/standalone_verifier.py'
    assessment = {'kind': 'independent_private_public_instruction_scope_forensic_addendum',
        'task_id': task_id, 'revision': 1, 'revision_hash': revision_hash,
        'diagnostic_topic': 'Q03_public_instruction_vs_verifier_scope',
        'finding': 'supported_material_ambiguity', 'supported_ambiguity': True,
        'public_instruction': scope.reference(instruction), 'verifier_binding': scope.reference(verifier)}
    review_ref = dump(tmp_path / 'scope_review.json', assessment)
    issue = entry.issue_for(task_id, 1, revision_hash, review_ref, scope.reference(instruction))
    program_ref = dump(tmp_path / 'program_review.json', {'task_id': task_id, 'revision': 1,
        'revision_hash': revision_hash, 'issues': [issue]})
    auth = {'revision': 1, 'revision_hash': revision_hash, 'source_sha256': identity,
        'plan': plan_ref, 'baseline': scope.reference(baseline), 'goal': scope.reference(goal),
        'input': scope.reference(masked), 'instruction': scope.reference(instruction),
        'diagnosis': diagnosis_ref, 'program_review': program_ref,
        'authorized_issue_ids': [issue['issue_id']]}
    manifest = {'kind': 'public_workbook_scope_binding', 'version': 1, 'clauses': scope.CLAUSES,
        'sources': {identity: {'source': source_ref}}, 'tasks': {task_id: auth},
        'quality_or_difficulty_certified': False}
    manifest_path = tmp_path / 'scope_binding.json'; manifest_ref = dump(manifest_path, manifest)
    config = {scope.POLICY: {'version': 1, 'manifest': manifest_ref}, 'run': {'max_steps': 3}}
    current = deepcopy(diagnosis); current['issues'].append(issue)
    ctx = TaskContext('offline', task_id, 'financial_modeling', source, run / 'tasks' / task_id,
        config, None, None, None, revision=1, data={'source_id': identity, 'plan': deepcopy(plan),
        'diagnosis': current, 'repair_routes': [{'issue_id': issue['issue_id'], 'problem_id': 'Q03',
            'route_id': 'R03', 'route_class': 'repair'}]})
    return SimpleNamespace(ctx=ctx, source=source, source_ref=source_ref, identity=identity,
        task_id=task_id, run=run, private=private, public=public, plan=plan, diagnosis=diagnosis,
        issue=issue, manifest=manifest, manifest_path=manifest_path, assessment=assessment,
        review_ref=review_ref, auth=auth, revision_hash=revision_hash)


def rebind(fixture):
    fixture.ctx.config[scope.POLICY]['manifest'] = dump(fixture.manifest_path, fixture.manifest)


@pytest.mark.parametrize('mode', ['financial_modeling', 'debugging'])
def test_clause_is_explicit_without_private_answers_or_change_set(fixture, mode):
    original = deepcopy(fixture.plan)
    result = scope.append_scope(original, mode)
    assert 'worksheet names and order' in result['public_instruction']
    assert 'Do not add helper cells' in result['public_instruction']
    assert 'dependent formula results to recalculate' in result['public_instruction']
    assert 'C3' not in scope.CLAUSES[mode] and 'Private reference' not in scope.CLAUSES[mode]
    assert 'missing financial formulas identified by this task' in scope.CLAUSES['financial_modeling']
    assert 'every blank in the ranges' not in result['public_instruction']
    assert {k: v for k, v in result.items() if k != 'public_instruction'} == {
        k: v for k, v in original.items() if k != 'public_instruction'}
    assert original == fixture.plan
    assert scope.append_scope(result, mode) == result


def test_plan_composes_existing_priority_and_preserves_private_assessment(fixture, monkeypatch):
    called = []
    expected = {'plan': deepcopy(fixture.plan), 'source_assessment': {'private': 'unchanged'}}
    monkeypatch.setattr(scope.PriorityPlanNode, 'execute', lambda self, ctx: called.append(ctx) or expected)
    result = scope.ScopePlanNode().execute(fixture.ctx)
    assert called == [fixture.ctx] and result['source_assessment'] is expected['source_assessment']
    assert result['plan']['public_rules'] == [priority.RULE]
    assert result['plan']['public_instruction'].endswith(scope.CLAUSES['financial_modeling'])
    assert expected['plan'] == fixture.plan


def test_invalid_optin_fails_before_planner(fixture, monkeypatch):
    fixture.manifest['version'] = True; rebind(fixture)
    monkeypatch.setattr(scope.PriorityPlanNode, 'execute', lambda *args: pytest.fail('Planner must not run'))
    with pytest.raises(ValueError, match='policy or clauses'):
        scope.ScopePlanNode().execute(fixture.ctx)


@pytest.mark.parametrize('field,value', [('version', True), ('quality_or_difficulty_certified', True),
    ('clauses', {'financial_modeling': 'Changed scope'})])
def test_bound_policy_tampering_is_rejected(fixture, field, value):
    fixture.manifest[field] = value; rebind(fixture)
    with pytest.raises(ValueError):
        scope.binding(fixture.ctx)


def test_legacy_plan_and_repair_delegate_without_scope(fixture, monkeypatch):
    fixture.ctx.config.pop(scope.POLICY)
    monkeypatch.setattr(scope.PriorityPlanNode, 'execute', lambda self, ctx: {'sentinel': 'priority-plan'})
    monkeypatch.setattr(scope.PriorityRepairNode, 'execute', lambda self, ctx: {'sentinel': 'priority-repair'})
    assert scope.ScopePlanNode().execute(fixture.ctx) == {'sentinel': 'priority-plan'}
    assert scope.ScopeRepairNode().execute(fixture.ctx) == {'sentinel': 'priority-repair'}


def test_exact_q03_changes_only_instruction_and_retains_old_issues(fixture):
    before = {path: Path(path).read_bytes() for path in [fixture.source, fixture.private / 'plan.json',
        fixture.private / 'diagnosis.json', fixture.public / 'instruction.md', fixture.public / 'input.xlsx']}
    diagnosis = deepcopy(fixture.ctx.data['diagnosis'])
    result = scope.ScopeRepairNode().execute(fixture.ctx)['next_plan']
    assert result == scope.append_scope(fixture.plan, 'financial_modeling')
    assert fixture.ctx.revision == 1 and fixture.ctx.data['plan'] == fixture.plan
    assert fixture.ctx.data['diagnosis'] == diagnosis
    assert all(Path(path).read_bytes() == raw for path, raw in before.items())
    receipt = json.loads((fixture.private / 'public_workbook_scope_repair.json').read_text())
    assert receipt['changed_plan_fields'] == ['public_instruction']
    assert receipt['requires_full_new_revision_quality'] and not receipt['reuse_old_harbor_controls']
    assert receipt['old_diagnostics_cleared'] is False


@pytest.mark.parametrize('problem', ['Q02', 'Q04', 'Q11'])
def test_other_problems_keep_normal_priority_repair(fixture, monkeypatch, problem):
    fixture.ctx.data['repair_routes'][0]['problem_id'] = problem
    monkeypatch.setattr(scope.PriorityRepairNode, 'execute', lambda self, ctx: {'normal': problem})
    assert scope.ScopeRepairNode().execute(fixture.ctx) == {'normal': problem}


@pytest.mark.parametrize('mutation', ['revision', 'source', 'plan', 'input', 'diagnosis', 'route', 'certainty', 'review_header'])
def test_negative_binding_and_route_cases_fail_closed(fixture, mutation):
    if mutation == 'revision': fixture.ctx.revision = 2
    elif mutation == 'source': fixture.source.write_bytes(b'Tampered source')
    elif mutation == 'plan': fixture.ctx.data['plan']['public_rules'].append('Unsupported rule')
    elif mutation == 'input': (fixture.public / 'input.xlsx').write_bytes(b'Tampered input')
    elif mutation == 'diagnosis': (fixture.private / 'diagnosis.json').write_text('{}')
    elif mutation == 'route': fixture.ctx.data['repair_routes'][0]['route_id'] = 'R04'
    elif mutation == 'certainty': fixture.ctx.data['diagnosis']['issues'][-1]['certainty'] = 'suspected'
    elif mutation == 'review_header':
        program = scope.read(fixture.auth['program_review']); program['revision_hash'] = '0' * 64
        fixture.auth['program_review'] = dump(Path(fixture.auth['program_review']['path']), program)
        rebind(fixture)
    with pytest.raises((ValueError, TaskRejected)):
        scope.ScopeRepairNode().execute(fixture.ctx)


def test_symlink_and_bad_byte_count_rejected(fixture, tmp_path):
    link = tmp_path / 'source-link.xlsx'; link.symlink_to(fixture.source)
    record = {**fixture.source_ref, 'path': str(link)}
    with pytest.raises(ValueError, match='Unsafe'):
        scope.checked_bytes(record)
    with pytest.raises(ValueError, match='bytes or SHA'):
        scope.checked_bytes({**fixture.source_ref, 'bytes': fixture.source_ref['bytes'] + 1})


def test_same_public_wording_transfers_only_scope_and_stale_same_task_rejected(fixture):
    assert entry.scope_review(fixture.review_ref, 'another-task', 99, 'a' * 64,
        scope.reference(fixture.public / 'instruction.md'),
        verifier_contract=scope.reference(ROOT / 'src/sheets_factory/evaluation/standalone_verifier.py'))['task_id'] == fixture.task_id
    with pytest.raises(ValueError, match='another task revision'):
        entry.scope_review(fixture.review_ref, fixture.task_id, 2, fixture.revision_hash,
            scope.reference(fixture.public / 'instruction.md'),
            verifier_contract=scope.reference(ROOT / 'src/sheets_factory/evaluation/standalone_verifier.py'))
    other = fixture.public / 'other.md'; other.write_text('Different public scope')
    with pytest.raises(ValueError, match='different public instruction'):
        entry.scope_review(fixture.review_ref, 'another-task', 99, 'a' * 64, scope.reference(other),
            verifier_contract=scope.reference(ROOT / 'src/sheets_factory/evaluation/standalone_verifier.py'))


def test_factory_consumes_new_revision_and_preserves_all_noninstruction_fields(fixture):
    factory = object.__new__(FactoryPipeline); factory.config = {'run': {'max_steps': 3}}
    factory._checkpoint = lambda: None
    def run_phase(ctx, phase):
        assert phase == 'repair'
        ctx.data.update(scope.ScopeRepairNode().execute(ctx))
    factory.run_phase = run_phase
    factory._apply_repair(fixture.ctx, fixture.ctx.data['repair_routes'])
    assert fixture.ctx.revision == 2
    assert fixture.ctx.data['plan'] == scope.append_scope(fixture.plan, 'financial_modeling')


def test_registry_preserves_every_mandatory_node_and_full_graph_provider():
    base = yaml.safe_load((ROOT / 'config/task_adapters/public_input_priority_nodes.yaml').read_text())['nodes']
    selected = scope.registry_nodes(base)
    assert selected == yaml.safe_load(entry.REGISTRY.read_text())['nodes']
    assert {k: v for k, v in selected.items() if k not in {'plan', 'repair'}} == {
        k: v for k, v in base.items() if k not in {'plan', 'repair'}}
    joint = yaml.safe_load((ROOT / 'config/task_adapters/scc_activity_nodes.yaml').read_text())['nodes']
    composed = scope.registry_nodes(joint)
    assert composed['plan'] == scope.FULL_GRAPH_PLAN_NODE
    assert composed['construct'] == joint['construct']
    assert {k: v for k, v in composed.items() if k not in {'plan', 'repair'}} == {
        k: v for k, v in joint.items() if k not in {'plan', 'repair'}}
    with pytest.raises(ValueError, match='Unknown'):
        scope.registry_nodes({**joint, 'plan': 'unknown:Provider'})


def test_full_graph_wrapper_calls_original_provider_once(fixture, monkeypatch):
    from sheets_factory.pipelines.scc_activity_admission import FullGraphSCCPlanNode
    fixture.ctx.mode = 'debugging'; calls = []
    expected = {'plan': deepcopy(fixture.plan), 'source_assessment': {'joint': 'unchanged'}}
    monkeypatch.setattr(FullGraphSCCPlanNode, 'execute', lambda self, ctx: calls.append(ctx) or expected)
    result = scope.ScopeFullGraphPlanNode().execute(fixture.ctx)
    assert calls == [fixture.ctx]
    assert result['plan'] == scope.append_scope(fixture.plan, 'debugging')
    assert result['source_assessment'] is expected['source_assessment']


def test_program_only_basis_has_no_borrowed_clearance(fixture):
    basis = entry.unknown_repair_basis(fixture.task_id, 1, fixture.revision_hash, fixture.issue)
    assert len(basis['enabled_check_ids']) == 12 and not basis['releasable']
    assert basis['assessments']['Q03']['state'] == 'flagged'
    assert all(row['state'] == 'unknown' for code, row in basis['assessments'].items() if code != 'Q03')
    assert not basis['quality_recovery_or_difficulty_pass_claimed']


def test_cli_prepared_run_validates_once_inside_execute(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(entry, 'validate_prepared', lambda *args: pytest.fail('Duplicate CLI validation'))
    monkeypatch.setattr(entry, 'execute', lambda output, port=0: calls.append((output, port)) or 0)
    assert entry.main(['--prepared', str(tmp_path), '--run', '--port', '1234']) == 0
    assert calls == [(tmp_path, 1234)]


def test_cli_plan_only_never_executes_or_starts_models(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(entry, 'validate_prepared', lambda output: calls.append(output))
    monkeypatch.setattr(entry, 'execute', lambda *args, **kwargs: pytest.fail('Plan-only execution forbidden'))
    assert entry.main(['--prepared', str(tmp_path)]) == 0
    assert calls == [tmp_path]


def test_cli_rejects_replacing_frozen_preparation(tmp_path):
    with pytest.raises(ValueError, match='replace frozen bindings'):
        entry.main(['--prepared', str(tmp_path), '--task-id', 'another-task'])


def test_normal_template_still_requires_controls_recovery_trace_and_diagnostics():
    phases = yaml.safe_load((ROOT / 'src/sheets_factory/pipelines/templates/financial_modeling.yaml').read_text())['phases']
    assert phases['revision'] == ['construct', 'instruction', 'precheck', 'independent_recovery', 'trajectory', 'diagnose']
    assert phases['diagnosis_retry'] == ['diagnose']


def test_scope_transfer_requires_identical_frozen_grader(fixture, tmp_path):
    other = tmp_path / 'different_grader.py'; other.write_text('A different grading scope')
    with pytest.raises(ValueError, match='grader contract differ'):
        entry.scope_review(fixture.review_ref, 'another-task', 2, 'a' * 64,
            scope.reference(fixture.public / 'instruction.md'), verifier_contract=scope.reference(other))


@pytest.fixture
def preparation(fixture, monkeypatch, tmp_path):
    proof = {'workbook': fixture.source_ref}
    seeds = dump(fixture.run / 'seed_manifest.json', {'selected': [{
        'sha256': fixture.identity, 'local_path': str(fixture.source), 'variant': 0,
        'finance_evidence': {'audited_source_binding': proof}}]})
    config = {'project_root': str(ROOT), 'run_dir': str(fixture.run),
        'pipeline': {'node_registry': str(ROOT / 'config/task_adapters/public_input_priority_nodes.yaml')},
        'run': {'targets': {'financial_modeling': 10, 'debugging': 10}, 'max_steps': 3,
            'seed_manifest': seeds['path'], 'max_evidence_rounds_per_revision': 2,
            'infrastructure_retries_per_stage': 1, 'max_additional_trials_per_revision': 0},
        'agents': {'model': 'gpt-6-sol', 'reasoning_effort': 'high'},
        'diagnosis': {'selection': {'include': 'all', 'exclude': []},
            'execution': {'reference_evidence_transport': 'audited_summary'}}}
    (fixture.run / 'resolved_config.yaml').write_text(yaml.safe_dump(config))
    dump(fixture.run / 'preflight_manifest.json', {'fixture': 'Original admission, not financial proof'})
    snapshot = {'run': {'status': 'cancelled'}, 'tasks': [{'id': fixture.task_id,
        'status': 'ready', 'revision': 1, 'content_repairs': 1, 'source_id': fixture.identity}]}
    original_ref = scope.reference(ROOT / 'config/nodes.yaml')
    monkeypatch.setattr(entry.priority, 'original_recipe', lambda run: {
        'recipe_sha256': {original_ref['path']: original_ref['sha256']}})
    monkeypatch.setattr(entry, 'read_run', lambda run: snapshot)
    admitted = []
    monkeypatch.setattr(entry.cohort, 'validate_seed', lambda seed: admitted.append(seed['sha256']) or proof)
    monkeypatch.setattr(entry.cohort, 'CohortCodex', lambda *a, **k: pytest.fail('Preparation cannot start a model'))
    monkeypatch.setattr(entry.cohort, 'LibreOfficeEngine', lambda *a, **k: pytest.fail('Preparation cannot start LO'))
    return SimpleNamespace(fixture=fixture, config=config, snapshot=snapshot,
        admitted=admitted, output=tmp_path / 'scope_preparation')


def test_actual_prepare_is_append_only_freezes_complete_bindings_and_all12(preparation):
    p = preparation; f = p.fixture
    old = {path: path.read_bytes() for path in f.run.rglob('*') if path.is_file()}
    frozen = entry.prepare(f.run, [Path(f.review_ref['path'])], p.output, task_ids=[f.task_id])
    assert frozen['repair_task_ids'] == [f.task_id] and p.admitted == [f.identity]
    assert frozen['actual_models'] == frozen['actual_LO_calls'] == frozen['qualified'] == 0
    assert len(frozen['checker_plan']['enabled_check_ids']) == 12
    assert frozen['targets'] == {'financial_modeling': 10, 'debugging': 10}
    assert frozen['diagnosis_configuration'] == p.config['diagnosis']
    assert not frozen['missing_diagnoses']
    assert all(path.read_bytes() == raw for path, raw in old.items())
    assert entry.validate_prepared(p.output) == frozen
    patch = scope.read(frozen['config_patch'])
    assert set(patch) == {'pipeline', scope.POLICY}
    assert priority.POLICY not in patch  # Existing priority setting is retained by merge.


def test_prepare_rejects_disabled_diagnostic(preparation):
    p = preparation; config = deepcopy(p.config)
    config['diagnosis']['selection']['exclude'] = ['Q03']
    (p.fixture.run / 'resolved_config.yaml').write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError, match='all twelve'):
        entry.prepare(p.fixture.run, [Path(p.fixture.review_ref['path'])], p.output)


def test_prepared_evidence_tamper_is_rejected_even_with_same_claim(preparation):
    p = preparation; f = p.fixture
    entry.prepare(f.run, [Path(f.review_ref['path'])], p.output)
    changed = deepcopy(f.assessment); changed['note'] = 'Changed bytes but finding still says supported'
    Path(f.review_ref['path']).write_text(json.dumps(changed))
    with pytest.raises(ValueError, match='bytes or SHA'):
        entry.validate_prepared(p.output)


def test_missing_diagnosis_only_creates_new_unknown_template_during_prepare(preparation):
    p = preparation; f = p.fixture
    diagnosis_path = f.private / 'diagnosis.json'; diagnosis_path.unlink()
    p.snapshot['tasks'][0]['status'] = 'cancelled'
    frozen = entry.prepare(f.run, [Path(f.review_ref['path'])], p.output)
    assert not diagnosis_path.exists() and len(frozen['missing_diagnoses']) == 1
    template = scope.read(frozen['missing_diagnoses'][0]['template'])
    assert template['assessments']['Q04']['state'] == 'unknown'
    assert not template['releasable']
    assert entry.validate_prepared(p.output) == frozen


def test_arriving_real_diagnosis_requires_fresh_preparation(preparation):
    p = preparation; f = p.fixture
    diagnosis_path = f.private / 'diagnosis.json'; diagnosis_path.unlink()
    p.snapshot['tasks'][0]['status'] = 'cancelled'
    entry.prepare(f.run, [Path(f.review_ref['path'])], p.output)
    dump(diagnosis_path, f.diagnosis)
    with pytest.raises(ValueError, match='Diagnosis arrived'):
        entry.validate_prepared(p.output)


def test_prepare_cannot_replace_custom_construct_registry(preparation):
    p = preparation; f = p.fixture
    p.config['pipeline']['node_registry'] = str(ROOT / 'config/task_adapters/scc_activity_nodes.yaml')
    (f.run / 'resolved_config.yaml').write_text(yaml.safe_dump(p.config))
    with pytest.raises(ValueError, match='custom Construct'):
        entry.prepare(f.run, [Path(f.review_ref['path'])], p.output)
