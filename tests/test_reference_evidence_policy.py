"""Offline policy/controller receipts; no real solver, LO or Harbor qualification."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import openpyxl
import pytest
from dirhash import dirhash

from sheets_factory.core.node import TaskContext
from sheets_factory.nodes import quality
from sheets_factory.workbook.compare import compare_workbooks
from sheets_factory.workbook.profile import profile_workbook
from sheets_factory.evaluation.harbor import export_harbor, inspect_export

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('policy_package_release', ROOT / 'scripts/package_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class Audit:
    def emit(self, *args, **kwargs):
        pass
    def task(self, *args, **kwargs):
        pass


class Reviewer:
    model = 'offline-review-fixture'
    def __init__(self):
        self.calls = []
        self.change = None

    def complete(self, instruction, **options):
        work = Path(options['workspace'])
        payload = json.loads((work / 'evidence.json').read_text())
        self.calls.append(payload)
        checks = {check: {'state': 'clear', 'reason': 'Declared offline policy-controller observation',
            'evidence': ['Explicit offline fixture; not a model quality conclusion']}
            for check in payload['assigned_check_ids']}
        if payload['visibility'] == 'public_only':
            assert not (work / 'reference.xlsx').exists()
            assert 'private' not in payload
        if 'Q04' in checks:
            binding = payload['private']['reference_review_requirements']['binding']
            assert hashlib.sha256((work / 'reference.xlsx').read_bytes()).hexdigest() == binding['goal_sha256']
            receipt = {'binding': binding, 'business_evidence': ['Offline fixture public A1 policy'],
                'financial_validation_checks': [{'check': 'Offline fixture arithmetic', 'method': '1+1=2',
                    'passed': True, 'evidence': ['Offline declared A1=2, not execution evidence']} ]}
            checks['Q04']['evidence'] = [quality.REFERENCE_REVIEW_PREFIX + json.dumps(receipt)]
        if self.change:
            self.change(checks)
        return {'assessments': checks, 'issues': [], 'evidence_requests': []}


def workbook(path, value, extra=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    book = openpyxl.Workbook()
    book.active['A1'] = value
    if extra:
        book.active['B2'] = 'unexpected'
    book.save(path)
    book.close()


@pytest.fixture
def context(tmp_path):
    task = tmp_path / 'task'
    base = task / 'revisions/000'
    source, goal = base / 'public/input.xlsx', base / 'private/goal.xlsx'
    workbook(source, 1)
    workbook(goal, 2)
    instruction = 'Offline policy fixture: set A1 to 2.'
    (source.parent / 'instruction.md').write_text(instruction)
    reviewer = Reviewer()
    ctx = TaskContext('offline', 'fm-offline', 'financial_modeling', source, task,
        {'project_root': str(ROOT), 'agents': {'timeout_seconds': 1},
         'diagnosis': {'difficulty_deferred': True, 'reference_evidence_policy': 'reference_review'}},
        Audit(), reviewer, None)
    delta = compare_workbooks(source, goal, goal)
    controls = {}
    for name, value, extra in [('oracle', 2, False), ('nop', 1, False),
                                ('equivalent', 2, False), ('missed_root', 1, False), ('extra_change', 2, True)]:
        output = base / 'private/controls' / (name + '.xlsx')
        workbook(output, value, extra)
        controls[name] = compare_workbooks(source, goal, output)
    ctx.data.update(input=source, goal=goal, instruction=instruction,
        revision_hash=hashlib.sha256(source.read_bytes() + instruction.encode()).hexdigest(),
        public_profile=profile_workbook(source), profile=profile_workbook(source),
        plan={'public_rules': ['Offline declared A1 policy'], 'edits': []},
        construction_validation={'offline_fixture': True}, delta=delta, root_impacts=[],
        controls=controls, traces=[{'events': []}], source_assessment={'offline_business_policy': 'A1 is2'},
        engine_report={'normalization_ok': True, 'recalculation_ok': True, 'stable': True})
    ctx.save('edit_validation.json', ctx.data['construction_validation'])
    ctx.save('expected_delta.json', delta)
    ctx.save('native_error_probe.json', {'blocking': False, 'revision': 0,
        'goal_sha256': hashlib.sha256(goal.read_bytes()).hexdigest(), 'required_delta': delta['expected_changes']})
    ctx.save('native_risk_guard.json', {'blocking': False})
    ctx.save('local_controls.json', controls)
    return ctx


def diagnose(ctx):
    ctx.data.update(quality.RecoveryNode().execute(ctx))
    return quality.DiagnoseNode().execute(ctx)['diagnosis']


def test_policy_default_and_unknown_values():
    assert quality.reference_evidence_policy({}) == 'independent_public_recovery'
    for policy in ('skip', '', None, False, [], {}):
        with pytest.raises(ValueError, match='reference_evidence_policy'):
            quality.reference_evidence_policy({'diagnosis': {'reference_evidence_policy': policy}})


@pytest.mark.parametrize('disabled', [f'Q{n:02d}' for n in range(1, 13)])
def test_reference_review_cannot_disable_any_diagnostic(context, disabled):
    context.config['diagnosis']['selection'] = {'include': 'all', 'exclude': [disabled]}
    with pytest.raises(ValueError, match='all twelve'):
        quality.RecoveryNode().execute(context)
    assert context.llm.calls == []


def test_recovery_skip_is_honest_hash_bound_and_makes_no_backend_call(context):
    result = quality.RecoveryNode().execute(context)['recovery']
    assert result['verified'] is False and result['public_information_only'] is False
    assert result['status'] == 'not_applicable' and result['skipped'] is True
    assert result['binding'] == quality.reference_revision_binding(context)
    assert result['usage_calls'] == [] and context.llm.calls == []
    assert not (context.revision_dir / 'private/recovery_attempts').exists()
    assert 'program' not in result and 'comparison' not in result


def test_reference_review_has_all_checks_supported_and_no_false_recovery_claim(context):
    report = diagnose(context)
    assert report['releasable']
    assert len(report['enabled_check_ids']) == 12
    assert all(report['assessments'][check]['state'] == 'clear' for check in quality.REFERENCE_REVIEW_CHECKS)
    assert report['assessments']['Q08']['state'] == 'not_applicable'
    assert report['reference_validation_method'] == 'reference_review'
    assert report['reference_review']['independent_public_recovery'] is False
    assert report['reference_review']['passed'] is True
    assert len(context.llm.calls) == 2


@pytest.mark.parametrize('check', quality.REFERENCE_REVIEW_CHECKS)
@pytest.mark.parametrize('state', ['unknown', 'not_applicable'])
def test_mandatory_public_and_financial_reviews_cannot_be_na_or_unknown(context, check, state):
    def change(checks):
        if check in checks:
            checks[check]['state'] = state
    context.llm.change = change
    report = diagnose(context)
    assert not report['releasable']
    assert not report['mandatory_gates']['reference_review']['passed']


def test_reference_review_rejects_q04_without_independent_financial_support(context):
    def change(checks):
        if 'Q04' in checks:
            checks['Q04']['evidence'] = ['The source contains a formula, so it must be correct.']
    context.llm.change = change
    assert not diagnose(context)['releasable']


@pytest.mark.parametrize('failure', ['failed_calculation', 'empty_method', 'absent_business', 'stale_instruction'])
def test_q04_receipt_must_contain_real_supported_current_calculations(context, failure):
    report = diagnose(context)
    assessment = report['assessments']['Q04']
    receipt = json.loads(assessment['evidence'][0][len(quality.REFERENCE_REVIEW_PREFIX):])
    if failure == 'failed_calculation':
        receipt['financial_validation_checks'][0]['passed'] = False
    elif failure == 'empty_method':
        receipt['financial_validation_checks'][0]['method'] = ''
    elif failure == 'absent_business':
        receipt['business_evidence'] = []
    else:
        receipt['binding']['instruction_sha256'] = '0' * 64
    assessment['evidence'] = [quality.REFERENCE_REVIEW_PREFIX + json.dumps(receipt)]
    assert not quality.reference_review_assessments(report, quality.reference_revision_binding(context))['passed']


def test_stale_public_or_goal_binding_cannot_pass_assessment_or_package(context):
    report = diagnose(context)
    current = quality.reference_revision_binding(context)
    stale = deepcopy(current)
    stale['goal_sha256'] = '0' * 64
    assert not quality.reference_review_assessments(report, stale)['passed']
    (context.data['input']).write_bytes(b'changed public input')
    with pytest.raises(ValueError, match='stale public revision'):
        quality.reference_revision_binding(context)


def validate_review(ctx, report):
    return release._validate_reference_review(ctx.revision_dir, ctx.task_id, ctx.revision, report,
        ctx.data['recovery'], Path(ctx.data['input']).read_bytes(), ctx.data['instruction'].encode(),
        Path(ctx.data['goal']).read_bytes(), {})


def test_package_reference_review_checks_actual_local_controls_and_current_evidence(context):
    report = diagnose(context)
    receipt, comparison = validate_review(context, report)
    assert receipt['verified_public_recovery'] is False
    assert receipt['financial_check_count'] == 1
    assert comparison['expected_changes'] == ['Sheet!A1']
    workbook(context.revision_dir / 'private/controls/equivalent.xlsx', 99)
    with pytest.raises(release.ReleaseError, match='local control differs'):
        validate_review(context, report)


@pytest.mark.parametrize('failure', ['bad_Q04', 'stale_goal', 'stale_artifact', 'disabled_check', 'fake_verified'])
def test_package_reference_review_refuses_false_or_stale_proof(context, failure):
    report = diagnose(context)
    if failure == 'bad_Q04':
        report['assessments']['Q04']['state'] = 'not_applicable'
    elif failure == 'stale_goal':
        workbook(context.data['goal'], 9)
    elif failure == 'stale_artifact':
        context.save('edit_validation.json', {'changed': True})
    elif failure == 'disabled_check':
        report['enabled_check_ids'].remove('Q04')
    else:
        context.data['recovery']['verified'] = True
    with pytest.raises(release.ReleaseError):
        validate_review(context, report)


def test_complete_export_validation_requires_current_private_goal_and_both_review_receipts(context, tmp_path):
    # Persisted Harbor records below are explicitly offline controller fixtures.
    # No container or agent is launched or claimed by this test.
    run = tmp_path / 'offline_run'
    directory = run / 'tasks' / context.task_id
    directory.parent.mkdir(parents=True)
    shutil.move(str(context.directory), directory)
    context.directory = directory
    base = context.revision_dir
    context.data['input'] = base / 'public/input.xlsx'
    context.data['goal'] = base / 'private/goal.xlsx'
    context.source = context.data['input']
    diagnose(context)
    export = run / 'SpreadsheetEval' / context.task_id
    export_harbor(base, export, {'task_id': context.task_id, 'mode': context.mode,
        'source_id': 'offline-source', 'revision': 0, 'revision_hash': context.data['revision_hash']})
    binding = inspect_export(export)
    proof = {}
    for agent, reward in [('oracle', 1), ('nop', 0)]:
        path = run / 'offline_control_fixtures' / context.task_id / agent / 'trial/result.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'offline_fixture': True, 'task_name': binding['task_name'],
            'verifier_result': {'rewards': {'reward': reward}}, 'exception_info': None,
            'task_checksum': dirhash(export, 'sha256'), 'task_id': {'path': str(export)},
            'agent_info': {'name': agent}, 'config': {'agent': {'name': agent}, 'task': {'path': str(export)}}}))
        proof[agent] = {'task_name': binding['task_name'], 'reward': reward, 'expected': reward,
            'matched': True, 'exception_info': None, 'result_file': str(path)}
    (run / 'offline_control_fixtures' / context.task_id / 'control_summary.json').write_text(json.dumps({
        'offline_fixture': True, 'export_root': str(run / 'SpreadsheetEval'), 'per_task': {binding['task_name']: proof}}))
    task = {'id': context.task_id, 'mode': context.mode, 'source_id': 'offline-source',
        'revision': 0, 'harbor_controls': proof, 'harbor_export_binding': binding}
    result = release._validate_task(run, task, {}, project_root=ROOT, reference_policy='reference_review')
    assert result['reference_validation_method'] == 'reference_review'
    assert result['independent_recovery']['verified'] is False
    assert result['diagnosis']['public_diagnosis_evidence']
    assert result['diagnosis']['reviewed_reference_evidence']
    assert 'reviewed_recovery_evidence' not in result['diagnosis']
    workspace = next(base.glob('diagnostic_private-*'))
    workbook(workspace / 'reference.xlsx', 99)
    with pytest.raises(release.ReleaseError, match='different goal or context'):
        release._validate_task(run, task, {}, project_root=ROOT, reference_policy='reference_review')
