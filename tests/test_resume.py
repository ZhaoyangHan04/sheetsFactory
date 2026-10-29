from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest
import yaml

from sheets_factory.core.audit import AuditStore
from sheets_factory.reporting import read_run
from sheets_factory.resume import (ProducerLease, ResumeError, assert_resume_allowed, candidate_task_id,
    filter_new_work_items, normalize_extra_manifest, prepare_resume, remaining_quotas, restore_target_claims)


def make_run(tmp_path, status='shortfall'):
    run = tmp_path / 'run'
    audit = AuditStore(run, {'id': 'same-run', 'status': status, 'started_at': '2026-10-29T12:00:00Z',
                             'wall_seconds': 100, 'code_revision': 'original-code'})
    audit.task('fm-' + 'a' * 12, source_id='a' * 64, mode='financial_modeling', status='qualified',
               revision=2, content_repairs=2, evidence_rounds=1, infrastructure_retries=2, targets=[['Forecast', 'B1']])
    audit.task('dbg-' + 'b' * 12, source_id='b' * 64, mode='debugging', status='ready', revision=0,
               targets=[['Summary', 'C2']])
    audit.task('fm-' + 'c' * 12, source_id='c' * 64, mode='financial_modeling', status='rejected',
               revision=3, content_repairs=3, evidence_rounds=2, infrastructure_retries=2)
    config = {'run': {'targets': {'financial_modeling': 20, 'debugging': 20}, 'max_steps': 3,
                     'max_evidence_rounds_per_revision': 2, 'infrastructure_retries_per_stage': 2, 'max_sources': 70},
              'run_dir': str(run), 'project_root': str(tmp_path), 'agents': {'model': 'gpt-6-sol', 'reasoning_effort': 'high'},
              'dashboard': {'host': '127.0.0.1', 'port': 0},
              'engine': {'image': 'test-no-calculation', 'timeout_seconds': 10}}
    (run / 'resolved_config.yaml').write_text(yaml.safe_dump(config))
    return run, audit, config


def no_producer(*args):
    return []


def test_extra_manifest_joins_selected_files_with_separate_business_evidence(tmp_path):
    source = tmp_path / 'roi.xls'
    source.write_bytes(b'fixture-for-manifest-hash-only')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = tmp_path / 'research.json'
    manifest.write_text(json.dumps({'selected': [{'local_path': str(source), 'sha256': digest}],
        'finance_evidence': {'sources': [{'source_sha256': digest, 'financial_modeling_eligible': True,
            'scenario_required': True, 'safe_modules': ['ROI'], 'source_business_issues': ['Unit evidence required']}]}}))
    normalized = normalize_extra_manifest(manifest)
    evidence = normalized['selected'][0]['finance_evidence']
    assert evidence['financial_modeling_eligible'] is True
    assert evidence['scenario_required'] is True
    assert evidence['source_business_issues'] == ['Unit evidence required']


def test_terminal_continuation_preserves_identity_tasks_and_all_budgets(tmp_path):
    run, original, config = make_run(tmp_path)
    before = original.snapshot()['tasks']
    with prepare_resume(run, current_code_revision='phase2-code', producer_probe=no_producer) as session:
        assert session.audit.run['id'] == 'same-run'
        assert session.audit.run['started_at'] == '2026-10-29T12:00:00Z'
        assert session.audit.run['previous_wall_seconds'] == 100
        assert session.audit.snapshot()['tasks'] == before
        assert session.config['run']['max_steps'] == 3
        assert len(session.target_claims) == 2
        assert session.existing_task_ids == {task['id'] for task in before}
        assert remaining_quotas(session.previous_snapshot, config['run']['targets']) == {'financial_modeling': 19, 'debugging': 19}
        assert len(session.audit.run['code_history']) == 2
        kinds = [event['kind'] for event in session.audit.events()]
        assert 'run.resumed' in kinds and 'run.amended' in kinds


@pytest.mark.parametrize('status', ['constructing', 'harbor_validation', 'resuming', 'initializing'])
def test_active_run_cannot_be_resumed(tmp_path, status):
    run, audit, config = make_run(tmp_path, status)
    with pytest.raises(ResumeError, match='terminal'):
        prepare_resume(run, producer_probe=no_producer)
    assert read_run(run)['run']['status'] == status


def test_live_producer_and_unfinished_context_are_refused(tmp_path):
    run, audit, config = make_run(tmp_path)
    with pytest.raises(ResumeError, match='still alive'):
        prepare_resume(run, producer_probe=lambda *args: [1234])
    audit.task('fm-interrupted', source_id='d' * 64, mode='financial_modeling', status='running', revision=2)
    with pytest.raises(ResumeError, match='Interrupted'):
        prepare_resume(run, producer_probe=no_producer)
    assert read_run(run)['tasks'][-1]['revision'] == 2


def test_nonblocking_producer_lease_prevents_two_writers(tmp_path):
    run, audit, config = make_run(tmp_path)
    with ProducerLease(run):
        with pytest.raises(ResumeError, match='lease'):
            ProducerLease(run).acquire()
    with ProducerLease(run):
        pass


@pytest.mark.parametrize('patch', [
    {'run': {'max_steps': 4}}, {'run': {'max_evidence_rounds_per_revision': 0}},
    {'run': {'targets': {'financial_modeling': 21, 'debugging': 20}}},
    {'agents': {'model': 'different-model'}}, {'run_dir': '/another-run'}])
def test_budget_quota_model_or_identity_changes_are_not_silent(tmp_path, patch):
    run, audit, config = make_run(tmp_path)
    with pytest.raises(ResumeError):
        prepare_resume(run, config_patch=patch, producer_probe=no_producer)
    assert yaml.safe_load((run / 'resolved_config.yaml').read_text()) == config
    assert read_run(run)['run']['status'] == 'shortfall'


def test_only_new_seed_or_variant_ids_are_scheduled(tmp_path):
    run, audit, config = make_run(tmp_path)
    snapshot = read_run(run)
    seed = {'local_path': '/unused/source.xls', 'sha256': 'a' * 64}
    items = filter_new_work_items([seed], snapshot, ['financial_modeling', 'debugging'])
    assert items[0]['modes'] == ['debugging']
    assert not filter_new_work_items([{'sha256': 'c' * 64, 'modes': ['financial_modeling']}], snapshot, ['financial_modeling'])
    variant = {**seed, 'variant': 1}
    assert candidate_task_id(variant, 'financial_modeling').endswith('-v1')
    assert filter_new_work_items([variant], snapshot, ['financial_modeling'])[0]['variant'] == 1


def test_extra_sources_are_hash_checked_frozen_and_added_without_new_run(tmp_path):
    run, audit, config = make_run(tmp_path)
    source = tmp_path / 'new.xls'
    source.write_bytes(b'explicit source fixture; not a workbook calculation test')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = tmp_path / 'fallback.json'
    manifest.write_text(json.dumps({'sources': [{'source_path': str(source), 'source_sha256': digest,
        'financial_modeling_eligible': True, 'safe_modules': ['Cash flow']}]}))
    with prepare_resume(run, extra_manifest=manifest, producer_probe=no_producer) as session:
        assert session.audit.run['id'] == 'same-run'
        saved = Path(session.config['run']['additional_seed_manifests'][0])
        data = json.loads(saved.read_text())
        assert data['selected'][0]['sha256'] == digest
        assert data['selected'][0]['finance_evidence']['financial_modeling_eligible'] is True
        assert session.config['run']['max_sources'] == 71
        assert saved.is_relative_to(run)


def test_changed_source_hash_is_rejected_before_resumption(tmp_path):
    run, audit, config = make_run(tmp_path)
    source = tmp_path / 'new.xlsx'
    source.write_bytes(b'changed bytes')
    manifest = tmp_path / 'fallback.json'
    manifest.write_text(json.dumps({'selected': [{'local_path': str(source), 'sha256': 'f' * 64}]}))
    with pytest.raises(ResumeError, match='hash mismatch'):
        prepare_resume(run, extra_manifest=manifest, producer_probe=no_producer)
    assert read_run(run)['run']['status'] == 'shortfall'


def test_cli_continues_same_audit_and_accumulates_wall_time_without_models(tmp_path, monkeypatch):
    import sheets_factory.cli as cli
    from types import SimpleNamespace
    run, original, config = make_run(tmp_path)
    before = original.snapshot()['tasks']
    monkeypatch.setattr(cli, '__file__', str(tmp_path / 'src/sheets_factory/cli.py'))
    monkeypatch.setattr(cli.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(stdout='phase-two-code'))
    class Dashboard:
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            return 'http://127.0.0.1:1/'
        def stop(self):
            pass
    class LLM:
        model, reasoning = 'gpt-6-sol', 'high'
        def __init__(self, *args, **kwargs):
            pass
        def _credentials(self):
            return None
    class Engine:
        def __init__(self, *args, **kwargs):
            pass
        def metadata(self):
            return {'fixture': 'no real calculation or API'}
    class Pipeline:
        def __init__(self, config, audit, *args):
            self.audit = audit
        def run(self):
            self.audit.update_run(status='shortfall')
            return False
    monkeypatch.setattr(cli, 'DashboardServer', Dashboard)
    monkeypatch.setattr(cli, 'CodexCLI', LLM)
    monkeypatch.setattr(cli, 'LibreOfficeEngine', Engine)
    monkeypatch.setattr(cli, 'FactoryPipeline', Pipeline)
    assert cli.main(['--resume', str(run), '--headless', '--exit-on-finish']) == 2
    result = read_run(run)
    assert result['run']['id'] == 'same-run'
    assert result['run']['wall_seconds'] >= 100
    assert result['run']['resume_count'] == 1
    assert result['run']['producer_active'] is False
    assert result['tasks'] == before


def test_factory_restores_claims_merges_supplement_and_never_reopens_old_tasks(tmp_path):
    from sheets_factory.pipelines.factory import FactoryPipeline
    root = Path(__file__).resolve().parents[1]
    run, original, config = make_run(tmp_path)
    (tmp_path / 'config').mkdir()
    for name in ('checkers.yaml', 'routes.yaml'):
        shutil.copy2(root / 'config' / name, tmp_path / 'config' / name)
    original_manifest = tmp_path / 'original.json'
    original_manifest.write_text(json.dumps({'selected': [{'sha256': 'a' * 64, 'local_path': '/unused/original.xls'}],
        'unique_workbooks_inspected': 720, 'download_url': 'https://example.test/euses', 'archive_sha256': 'archive'}))
    config['run']['seed_manifest'] = str(original_manifest)
    config['pipeline'] = {'node_registry': str(root / 'config/nodes.yaml'),
        'templates': {mode: str(root / 'src/sheets_factory/pipelines/templates' / (mode + '.yaml'))
                      for mode in config['run']['targets']}}
    (run / 'resolved_config.yaml').write_text(yaml.safe_dump(config))
    source = tmp_path / 'fallback.xls'
    source.write_bytes(b'fixture source bytes, no calculation or API')
    manifest = tmp_path / 'fallback.json'
    manifest.write_text(json.dumps({'selected': [{'local_path': str(source), 'financial_modeling_eligible': True}]}))
    before = original.snapshot()['tasks']
    with prepare_resume(run, extra_manifest=manifest, producer_probe=no_producer) as session:
        pipeline = FactoryPipeline(session.config, session.audit, None, None)
        assert len(pipeline.target_claims) == 2
        seeds = pipeline.load_seeds()
        added = next(seed for seed in seeds if seed['local_path'] == str(source))
        assert added['finance_evidence']['financial_modeling_eligible'] is True
        pipeline.reserve = lambda *args: pytest.fail('Existing task must be skipped before reservation')
        pipeline.process_task({'sha256': 'a' * 64, 'local_path': '/unused/original.xls'}, 'financial_modeling')
        pipeline.process_task({'sha256': 'c' * 64, 'local_path': '/unused/rejected.xls'}, 'financial_modeling')
        assert session.audit.snapshot()['tasks'] == before


def repair_case(tmp_path, revision=2, problem='Q03'):
    run, audit, config = make_run(tmp_path)
    root = Path(__file__).resolve().parents[1]
    (tmp_path / 'config').mkdir(exist_ok=True)
    for name in ('routes.yaml', 'checkers.yaml'):
        shutil.copy2(root / 'config' / name, tmp_path / 'config' / name)
    source = tmp_path / 'original-model.xls'
    source.write_bytes(b'original immutable fixture source; not a real calculation test')
    source_id = hashlib.sha256(source.read_bytes()).hexdigest()
    task_id = candidate_task_id({'sha256': source_id}, 'financial_modeling')
    private = run / 'tasks' / task_id / 'revisions' / f'{revision:03d}' / 'private'
    private.mkdir(parents=True)
    plan = {'title': 'Fixture forecast', 'public_instruction': 'Preserve all other values.',
            'public_rules': ['Revenue is public rate times volume.'],
            'edits': [{'sheet': 'Forecast', 'cell': f'B{row}', 'before': '=Inputs!B1*2', 'after': None}
                      for row in range(1, 7)]}
    (private / 'plan.json').write_text(json.dumps(plan))
    (private / 'diagnosis.json').write_text(json.dumps({'issues': [], 'releasable': True, 'routes': []}))
    baseline = run / 'sources' / source_id[:12] / 'baseline.xlsx'
    baseline.parent.mkdir(parents=True)
    baseline.write_bytes(b'immutable normalized fixture baseline')
    issue = {'issue_id': task_id + '-external-' + problem, 'problem_id': problem, 'certainty': 'confirmed',
             'severity': 'blocker', 'claim': 'Dependent values must recalculate despite preservation wording.',
             'evidence': [{'cell': 'Forecast!C1', 'input': 0, 'goal': 20}],
             'route_id': 'R' + problem[1:], 'revision': revision}
    (private.parents[2] / 'external_quality_review.json').write_text(json.dumps(issue))
    audit.task(task_id, mode='financial_modeling', source_id=source_id, status='qualified',
               revision=revision, content_repairs=revision, evidence_rounds=1, infrastructure_retries=2,
               targets=[['Forecast', f'B{row}'] for row in range(1, 7)],
               harbor_controls={'oracle': {'reward': 1, 'matched': True}, 'nop': {'reward': 0, 'matched': True}})
    export = run / 'SpreadsheetEval' / task_id
    export.mkdir(parents=True)
    (export / 'historical.txt').write_text('old revision control proof, not valid for the new revision')
    manifest = tmp_path / 'sources.json'
    manifest.write_text(json.dumps({'selected': [{'local_path': str(source), 'sha256': source_id}],
        'unique_workbooks_inspected': 720, 'download_url': 'fixture', 'archive_sha256': 'fixture'}))
    config['run']['seed_manifest'] = str(manifest)
    config['pipeline'] = {'node_registry': str(root / 'config/nodes.yaml'),
        'templates': {mode: str(root / 'src/sheets_factory/pipelines/templates' / (mode + '.yaml'))
                      for mode in config['run']['targets']}}
    (run / 'resolved_config.yaml').write_text(yaml.safe_dump(config))
    return run, audit, config, task_id, private, baseline, issue


def test_explicit_external_repair_holds_quota_and_preserves_historical_proof(tmp_path):
    run, original, config, task_id, private, baseline, issue = repair_case(tmp_path)
    before = deepcopy(next(task for task in original.snapshot()['tasks'] if task['id'] == task_id))
    with prepare_resume(run, repair_tasks=[task_id], producer_probe=no_producer) as session:
        current = next(task for task in session.audit.snapshot()['tasks'] if task['id'] == task_id)
        assert current['status'] == 'repair_pending'
        assert current['revision'] == current['content_repairs'] == 2
        assert current['evidence_rounds'] == 1 and current['infrastructure_retries'] == 2
        assert current['harbor_controls'] is None
        assert not (run / 'SpreadsheetEval' / task_id).exists()
        assert Path(current['historical_export'], 'historical.txt').is_file()
        spec = json.loads(Path(session.config['run']['external_repair_manifest']).read_text())[0]
        assert spec['previous_task'] == before
        assert spec['issues'][0]['issue_id'] == issue['issue_id']
        assert remaining_quotas(session.audit.snapshot(), config['run']['targets'])['financial_modeling'] == 19


@pytest.mark.parametrize('defect,match', [('suspected', 'No confirmed'), ('missing_route', 'explicit repair route'),
    ('stale', 'Stale'), ('evidence', 'numbered evidence'), ('nonrepair', 'content-repair')])
def test_external_repair_requires_current_confirmed_numbered_repair_evidence(tmp_path, defect, match):
    run, audit, config, task_id, private, baseline, issue = repair_case(tmp_path)
    if defect == 'suspected': issue['certainty'] = 'suspected'
    if defect == 'missing_route': del issue['route_id']
    if defect == 'stale': issue['revision'] = 0
    if defect == 'evidence': issue['evidence'] = []
    if defect == 'nonrepair': issue.update(problem_id='Q12', route_id='R12')
    (private.parents[2] / 'external_quality_review.json').write_text(json.dumps(issue))
    with pytest.raises(ResumeError, match=match):
        prepare_resume(run, repair_tasks=[task_id], producer_probe=no_producer)
    assert read_run(run)['run']['status'] == 'shortfall'
    assert (run / 'SpreadsheetEval' / task_id / 'historical.txt').is_file()


def test_external_repair_cannot_reset_exhausted_content_budget(tmp_path):
    run, audit, config, task_id, private, baseline, issue = repair_case(tmp_path, revision=3)
    with pytest.raises(ResumeError, match='budget exhausted'):
        prepare_resume(run, repair_tasks=[task_id], producer_probe=no_producer)
    task = next(task for task in read_run(run)['tasks'] if task['id'] == task_id)
    assert task['revision'] == task['content_repairs'] == 3


def test_only_positive_agent_concurrency_can_change_model_and_roles_stay_fixed(tmp_path):
    run, audit, config = make_run(tmp_path)
    with prepare_resume(run, config_patch={'agents': {'max_parallel_calls': 8}}, producer_probe=no_producer) as session:
        assert session.config['agents']['max_parallel_calls'] == 8
        amendment = next(event for event in session.audit.events() if event['kind'] == 'run.amended')
        assert amendment['max_parallel_calls_after'] == 8
        assert session.config['agents']['model'] == 'gpt-6-sol'
    for patch in ({'max_parallel_calls': 0}, {'reasoning_effort': 'xhigh'}, {'roles': {'planner': 'other'}}):
        # An unsuccessful startup is terminalized explicitly in this fixture.
        AuditStore(run, {**read_run(run)['run'], 'status': 'shortfall', 'producer_active': False})
        with pytest.raises(ResumeError):
            prepare_resume(run, config_patch={'agents': patch}, producer_probe=no_producer)


@pytest.mark.parametrize('extra_failure', [False, True])
def test_repair_restores_original_source_and_next_revision_without_inheriting_qualification(tmp_path, extra_failure):
    from types import SimpleNamespace
    from sheets_factory.pipelines.factory import FactoryPipeline
    run, original, config, task_id, private, baseline, issue = repair_case(tmp_path)
    closed_plan = (private / 'plan.json').read_bytes()
    with prepare_resume(run, repair_tasks=[task_id], producer_probe=no_producer) as session:
        factory = FactoryPipeline(session.config, session.audit, None, None)
        spec = json.loads(Path(session.config['run']['external_repair_manifest']).read_text())[0]
        seen = []
        def load_node(name):
            def execute(ctx):
                assert name in {'normalize', 'profile'}
                assert ctx.source == Path(spec['seed']['local_path'])
                if name == 'normalize':
                    ctx.data.update(source_id=spec['previous_task']['source_id'], baseline=baseline,
                                    source_cache=baseline.parent)
                else:
                    ctx.data['profile'] = {'fixture': 'read-only source facts'}
            return SimpleNamespace(run=execute)
        def phase(ctx, name):
            seen.append((name, ctx.revision))
            if name == 'repair':
                assert ctx.revision == 2
                assert 'external_repairs' in str(ctx.revision_dir)
                assert issue['issue_id'] in {item['issue_id'] for item in ctx.data['diagnosis']['issues']}
                next_plan = deepcopy(ctx.data['plan'])
                next_plan['public_instruction'] = 'Edit target formulas; allow dependent values to recalculate.'
                ctx.data['next_plan'] = next_plan
            elif name == 'revision':
                assert ctx.revision == 3
                assert ctx.revision_dir == private.parents[1] / '003'
                if extra_failure:
                    ctx.data['diagnosis'] = {'releasable': False,
                        'issues': [{'issue_id': 'new-defect', 'certainty': 'confirmed'}],
                        'routes': [{'issue_id': 'new-defect', 'problem_id': 'Q06', 'route_class': 'repair'}]}
                else:
                    ctx.data['diagnosis'] = {'releasable': True, 'issues': [], 'routes': []}
            elif name == 'export':
                ctx.data['export_dir'] = run / 'SpreadsheetEval' / task_id
            else:
                pytest.fail('No replanning or hidden budget reset permitted')
        factory.load_node, factory.run_phase = load_node, phase
        factory.process_external_repair(spec)
        task = next(task for task in session.audit.snapshot()['tasks'] if task['id'] == task_id)
        assert task['revision'] == task['content_repairs'] == 3
        assert task['source_id'] == spec['previous_task']['source_id']
        assert task['harbor_controls'] is None
        assert seen.count(('repair', 2)) == 1
        assert (private / 'plan.json').read_bytes() == closed_plan
        if extra_failure:
            assert task['status'] == 'rejected' and 'EXHAUSTED' in task['error']
        else:
            assert task['status'] == 'ready'
            assert task['evidence_rounds'] == task['infrastructure_retries'] == 0  # New revision's counters.


def test_q03_repair_cannot_change_workbook_edits_or_baseline(tmp_path):
    from types import SimpleNamespace
    from sheets_factory.pipelines.factory import FactoryPipeline
    run, audit, config, task_id, private, baseline, issue = repair_case(tmp_path)
    with prepare_resume(run, repair_tasks=[task_id], producer_probe=no_producer) as session:
        factory = FactoryPipeline(session.config, session.audit, None, None)
        spec = json.loads(Path(session.config['run']['external_repair_manifest']).read_text())[0]
        def load_node(name):
            def execute(ctx):
                ctx.data.update(source_id=spec['previous_task']['source_id'], baseline=baseline, profile={})
            return SimpleNamespace(run=execute)
        def phase(ctx, name):
            assert name == 'repair'
            proposed = deepcopy(ctx.data['plan'])
            proposed['edits'][0]['before'] = '=999'
            ctx.data['next_plan'] = proposed
        factory.load_node, factory.run_phase = load_node, phase
        factory.process_external_repair(spec)
        task = next(task for task in session.audit.snapshot()['tasks'] if task['id'] == task_id)
        assert task['status'] == 'rejected' and 'instruction-only' in task['error']
        assert task['revision'] == task['content_repairs'] == 2


def test_unstarted_authorized_repair_is_terminalized_without_resetting_budget(tmp_path):
    run, audit, config, task_id, private, baseline, issue = repair_case(tmp_path)
    with prepare_resume(run, repair_tasks=[task_id], producer_probe=no_producer) as session:
        session.audit.update_run(status='failed')  # Simulates a dashboard or credential startup failure.
    snapshot = read_run(run)
    task = next(task for task in snapshot['tasks'] if task['id'] == task_id)
    assert task['status'] == 'rejected' and task['node'] == 'external_repair_not_started'
    assert task['revision'] == task['content_repairs'] == 2
    assert task['evidence_rounds'] == 1 and task['infrastructure_retries'] == 2
    assert_resume_allowed(run, snapshot, no_producer)
