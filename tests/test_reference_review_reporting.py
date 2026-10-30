"""Reports distinguish reviewed references from independent public recovery."""
import json
from pathlib import Path
import shutil

import pytest
import yaml

from sheets_factory.core.audit import AuditStore
from sheets_factory.nodes.quality import DiagnoseNode
from sheets_factory.reporting import generate_report, markdown_report, html_report
from test_reference_evidence_policy import context as reference_context, diagnose, workbook


@pytest.fixture
def reviewed_run(reference_context, tmp_path):
    ctx = reference_context
    root = tmp_path / 'project'
    run = root / 'outputs/runs/offline-review-report'
    audit = AuditStore(run, {'id': 'offline-review-report', 'status': 'completed',
        'started_at': '2026-10-30T00:00:00Z', 'finished_at': '2026-10-30T00:00:01Z',
        'wall_seconds': 1, 'difficulty_status': 'deferred'})
    directory = run / 'tasks' / ctx.task_id
    directory.parent.mkdir(parents=True)
    shutil.move(str(ctx.directory), directory)
    ctx.directory = directory
    ctx.data.update(input=ctx.revision_dir / 'public/input.xlsx', goal=ctx.revision_dir / 'private/goal.xlsx')
    ctx.source = ctx.data['input']
    diagnose(ctx)
    config = dict(ctx.config)
    config['run'] = {'targets': {'financial_modeling': 1, 'debugging': 0}}
    (run / 'resolved_config.yaml').write_text(yaml.safe_dump(config))
    audit.task(ctx.task_id, source_id='offline-source', mode='financial_modeling', status='qualified',
        revision=0, revision_hash=ctx.data['revision_hash'], independent_recovery=False,
        reference_validation_method='reference_review', harbor_controls={
            'oracle': {'reward': 1, 'matched': True}, 'nop': {'reward': 0, 'matched': True}})
    return root, run, audit, ctx


def test_current_review_evidence_counts_without_claiming_a_public_recovery(reviewed_run):
    root, run, _, _ = reviewed_run
    report = generate_report(run, project_root=root)
    assert report['yield']['verified_qualified'] == 1
    task = report['tasks'][0]
    assert task['verified_qualified']
    assert task['reference_validation_method'] == 'reference_review'
    assert task['reference_validation']['verified'] is True
    assert task['reference_validation']['status'] == 'passed'
    assert task['independent_recovery']['verified'] is False
    assert task['independent_recovery']['status'] == 'not_applicable'
    assert task['independent_recovery']['public_information_only'] is False
    assert report['run']['reference_evidence_policy'] == 'reference_review'
    for rendered in (markdown_report(report), html_report(report)):
        assert '参考复核：通过（独立恢复未执行）' in rendered
        assert '独立恢复：通过' not in rendered
    assert report['consistency_warnings'] == []


@pytest.mark.parametrize('changed', [
    'goal', 'input', 'instruction', 'context', 'private_goal', 'public_instruction',
    'Q04_evidence', 'missing_receipt', 'disabled_Q01', 'unknown_policy', 'fake_recovery',
])
def test_missing_stale_or_unsupported_review_never_inflates_verified_yield(reviewed_run, changed):
    root, run, _, ctx = reviewed_run
    base = ctx.revision_dir
    if changed in {'goal', 'input'}:
        workbook(ctx.data[changed], 99)
    elif changed == 'instruction':
        (base / 'public/instruction.md').write_text('Changed public policy')
    elif changed == 'context':
        (base / 'private/reference_evidence_context.json').write_text('{}')
    elif changed == 'private_goal':
        workbook(next(base.glob('diagnostic_private-*')) / 'reference.xlsx', 99)
    elif changed == 'public_instruction':
        (next(base.glob('diagnostic_public-*')) / 'instruction.md').write_text('Changed reviewed instruction')
    elif changed == 'Q04_evidence':
        path = base / 'private/diagnosis.json'
        data = json.loads(path.read_text())
        data['assessments']['Q04']['evidence'] = []
        path.write_text(json.dumps(data))
    elif changed == 'missing_receipt':
        (base / 'private/reference_review.json').unlink()
    elif changed in {'disabled_Q01', 'unknown_policy'}:
        path = run / 'resolved_config.yaml'
        data = yaml.safe_load(path.read_text())
        if changed == 'disabled_Q01':
            data['diagnosis']['selection'] = {'include': 'all', 'exclude': ['Q01']}
        else:
            data['diagnosis']['reference_evidence_policy'] = 'unchecked_reference'
        path.write_text(yaml.safe_dump(data))
    else:
        path = base / 'private/independent_recovery.json'
        data = json.loads(path.read_text())
        data['verified'] = True
        path.write_text(json.dumps(data))
    report = generate_report(run, project_root=root)
    assert report['yield']['reported_qualified'] == 1
    assert report['yield']['verified_qualified'] == 0
    assert report['tasks'][0]['reference_validation']['verified'] is False
    assert len(report['consistency_warnings']) == 1


def test_reporting_handles_actual_cached_diagnostic_origins(reviewed_run):
    root, run, _, ctx = reviewed_run
    first = json.loads((ctx.revision_dir / 'private/diagnosis.json').read_text())
    second = DiagnoseNode().execute(ctx)['diagnosis']
    assert first['diagnostic_run_id'] != second['diagnostic_run_id']
    assert all(batch['cache_hit'] for batch in second['llm_batches'])
    report = generate_report(run, project_root=root)
    assert report['yield']['verified_qualified'] == 1
    assert report['tasks'][0]['reference_validation']['verified'] is True


def test_reporting_is_read_only_for_review_receipts_and_task_state(reviewed_run):
    root, run, audit, ctx = reviewed_run
    before = {str(path): path.read_bytes() for path in ctx.revision_dir.rglob('*') if path.is_file()}
    snapshot = audit.snapshot()['tasks']
    generate_report(run, project_root=root)
    assert snapshot == audit.snapshot()['tasks']
    assert before == {str(path): path.read_bytes() for path in ctx.revision_dir.rglob('*') if path.is_file()}
