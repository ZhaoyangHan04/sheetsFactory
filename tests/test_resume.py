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
