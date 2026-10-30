"""Offline orchestration state-machine tests; all scored outcomes are fixtures."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import urllib.request

from dirhash import dirhash
import pytest

from sheets_factory.core.audit import AuditStore, utcnow
from sheets_factory.pipelines.difficulty import DifficultyPipeline, DifficultyError, _write, semantic_task_fingerprint


class FakePanel:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        return 'http://127.0.0.1:9999/'

    def stop(self):
        pass


class OfflinePipeline(DifficultyPipeline):
    def __init__(self, *args, scores=None, shortfall_rounds=(), same_content=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.scores = iter(scores or [.1, .1])
        self.shortfall_rounds = set(shortfall_rounds)
        self.same_content = same_content
        self.generated_configs, self.evaluations, self.publications = [], [], []
        self.tasks_by_directory = {}

    def _dashboard(self):
        self._save()

    def _preflight(self):
        self.secrets = ['PRIVATE_FIXTURE_SECRET_1234567890']

    def _select_seeds(self):
        return [{'sha256': 'a' * 64, 'local_path': '/offline/seeds.xlsx', 'rank_score': 10}]

    def _run_quality(self, config, directory, number):
        self.generated_configs.append(deepcopy(config))
        directory.mkdir(parents=True)
        audit = AuditStore(directory, {'id': 'fixture-quality-' + str(number), 'status': 'completed'})
        self._child(directory, 'quality', number)
        tasks = []
        for mode in ('financial_modeling', 'debugging'):
            for index in range(10):
                task_id = ('fm-' if mode == 'financial_modeling' else 'dbg-') + str(index)
                revision_hash = hashlib.sha256(f'{task_id}-{1 if self.same_content else number}'.encode()).hexdigest()
                item = {'task_id': task_id, 'mode': mode, 'source_id': 'a' * 64, 'revision': 0,
                        'revision_hash': revision_hash, 'harbor_export_binding': {
                            'task_id': task_id, 'task_name': 'sheetsfactory/' + task_id,
                            'revision': 0, 'revision_hash': revision_hash}}
                tasks.append(item)
                private = directory / 'tasks' / task_id / 'revisions/000/private'
                _write(private / 'plan.json', {'title': 'Offline business fixture',
                    'edits': [{'sheet': 'Model', 'cell': 'A1'}]})
                rejected = number in self.shortfall_rounds
                audit.task(task_id, mode=mode, source_id='a' * 64,
                    status='rejected' if rejected else 'qualified', target_fingerprint=revision_hash,
                    targets=[['Model', 'A1']], revision=0,
                    error='Bad fixture PRIVATE_FIXTURE_SECRET_1234567890' if rejected else None)
        audit.record('calls', {'call_id': 'same-call-id-across-children', 'model': 'gpt-6-sol',
            'reasoning_effort': 'high', 'status': 'completed', 'input_tokens': 100,
            'cached_input_tokens': 50, 'output_tokens': 10})
        self.tasks_by_directory[str(directory)] = tasks
        return {'status': 'shortfall' if number in self.shortfall_rounds else 'completed',
                'directory': str(directory), 'snapshot': audit.snapshot()}

    def _package(self, quality, directory):
        tasks = self.tasks_by_directory[str(quality)]
        for item in tasks:
            target = directory / 'SpreadsheetEval' / item['task_id']
            target.mkdir(parents=True)
            (target / 'offline-content.txt').write_text(item['revision_hash'])
        _write(directory / 'release_manifest.json', {'tasks': tasks,
            'selected_task_ids': [task['task_id'] for task in tasks]})
        return {'release_directory': str(directory), 'task_directory': str(directory / 'SpreadsheetEval'),
                'manifest': str(directory / 'release_manifest.json'), 'task_count': len(tasks)}

    def _evaluate(self, manifest, directory, phase, number, priors):
        self.evaluations.append({'phase': phase, 'round': number, 'priors': list(priors)})
        rate = next(self.scores)
        source = json.loads(Path(manifest).read_text())
        directory.mkdir(parents=True)
        audit = AuditStore(directory, {'id': phase + str(number),
                                      'status': 'completed' if rate is not None else 'infrastructure_failed'})
        self._child(directory, phase, number)
        audit.record('calls', {'call_id': 'same-call-id-across-children', 'model': 'gpt-6.1-sol',
            'reasoning_effort': 'xhigh', 'status': 'completed', 'input_tokens': 200,
            'cached_input_tokens': 100, 'output_tokens': 20})
        attempts = []
        for index, item in enumerate(source['tasks']):
            reward = int(index < int((rate or 0) * 20))
            result = directory / 'harbor_jobs/offline' / item['task_id'] / 'result.json'
            _write(result, {'offline_fixture': True, 'task_name': item['harbor_export_binding']['task_name']})
            _write(result.parent / 'agent/trajectory.json', {'steps': [{'source': 'agent',
                'message': 'Used Translator; PRIVATE_FIXTURE_SECRET_1234567890',
                'tool_calls': [{'function_name': 'exec', 'arguments': {'code': 'copy formula'}}]}]})
            attempts.append({**item, 'status': 'scored' if rate is not None else 'infrastructure_error',
                'reward': reward if rate is not None else None, 'result_file': str(result),
                'task_checksum': dirhash(Path(manifest).parent / 'SpreadsheetEval' / item['task_id'], 'sha256')})
        _write(directory / 'selection_manifest.json', {'phase': phase, 'frozen_at': utcnow(),
            'selected_task_ids': source['selected_task_ids'], 'tasks': source['tasks']})
        result = {'status': 'completed' if rate is not None else 'infrastructure_failed',
            'phase': phase, 'attempts': attempts,
            'score': {'overall_pass_at_1': rate, 'total_tasks': 20,
                      'scored_tasks': 20 if rate is not None else 0, 'infrastructure_errors': 0 if rate is not None else 20},
            'gate_passed': phase == 'confirmation' and rate is not None and rate <= .2}
        _write(directory / 'evaluation_manifest.json', result)
        return result

    def _publish(self, release_dir, confirmation_dir):
        self.publications.append((release_dir, confirmation_dir))
        return {'status': 'published', 'offline_fixture': True,
                'manifest': json.loads((Path(release_dir) / 'release_manifest.json').read_text())}

    def _resume_infrastructure(self, directory):
        # The existing runner owns eligibility and retry-count enforcement. This
        # default fixture has an unresolved failure and returns it unchanged.
        return json.loads((directory / 'evaluation_manifest.json').read_text())

    def _version_fingerprints(self, packaged):
        roots = [path for path in Path(packaged['task_directory']).iterdir() if path.is_dir()]
        values = {dirhash(path, 'sha256') for path in roots}
        return {'checksums': values, 'semantic': values}


@pytest.fixture
def pipeline_factory(tmp_path, monkeypatch):
    monkeypatch.setattr('sheets_factory.pipelines.difficulty.HistoricalDashboardServer', FakePanel)
    seed = tmp_path / 'seed-manifest.json'
    _write(seed, {'selected': []})
    config = {'run': {'targets': {'financial_modeling': 10, 'debugging': 10}, 'max_sources': 3,
                      'max_steps': 3, 'max_evidence_rounds_per_revision': 2},
              'agents': {'model': 'gpt-6-sol', 'reasoning_effort': 'high'},
              'difficulty': {'max_rounds': 3}}
    instances = []

    def create(**kwargs):
        current = deepcopy(config)
        current['difficulty'].update(kwargs.pop('settings', {}))
        instance = OfflinePipeline(current, seed, tmp_path / ('iteration-' + str(len(instances))),
                                   project_root=tmp_path, headless=True, **kwargs)
        instances.append(instance)
        return instance

    yield create
    for instance in instances:
        instance.close()


def test_development_feedback_then_new_round_confirmation_and_publication(pipeline_factory):
    pipeline = pipeline_factory(scores=[.6, .1, .1])
    result = pipeline.run()
    assert result['status'] == 'completed'
    assert [item['status'] for item in result['rounds']] == ['development_too_easy', 'published']
    assert [item['phase'] for item in pipeline.evaluations] == ['development', 'development', 'confirmation']
    assert pipeline.generated_configs[1]['generation_feedback']['path'].endswith('001/feedback.json')
    assert pipeline.generated_configs[1]['generation_feedback']['seen_modules']
    assert pipeline.generated_configs[1]['run']['max_steps'] == 3
    feedback = Path(pipeline.generated_configs[1]['generation_feedback']['path']).read_text()
    assert 'PRIVATE_FIXTURE_SECRET_1234567890' not in feedback
    assert '[REDACTED]' in feedback and 'formula_translation_observed' in feedback
    assert len(pipeline.publications) == 1
    assert result['usage']['qualified'] == 20
    assert result['usage']['candidates'] == 40
    assert result['usage']['input_tokens'] == 800
    assert result['usage']['output_tokens'] == 80
    assert result['usage']['total_tokens'] == 880  # Cache is already a subset of input.
    assert result['usage']['cached_input_tokens'] == 400
    pipeline._sync_children()
    assert pipeline.audit.snapshot()['metrics']['total_tokens'] == 880


def test_confirmation_failure_requires_new_generated_content(pipeline_factory):
    pipeline = pipeline_factory(scores=[.1, .5, .1, .1])
    result = pipeline.run()
    assert result['status'] == 'completed'
    assert [item['status'] for item in result['rounds']] == ['confirmation_too_easy', 'published']
    assert [item['round'] for item in pipeline.evaluations if item['phase'] == 'confirmation'] == [1, 2]
    assert pipeline.generated_configs[1]['generation_feedback']['reason'] == 'confirmation_too_easy'
    assert pipeline.evaluations[-1]['priors'][-2].name == 'selection_manifest.json'


def test_old_confirmation_bytes_are_not_retested_until_lucky(pipeline_factory):
    pipeline = pipeline_factory(scores=[.1, .6], same_content=True, settings={'max_rounds': 2})
    result = pipeline.run()
    assert result['status'] == 'budget_exhausted'
    assert [item['status'] for item in result['rounds']] == ['confirmation_too_easy', 'unchanged_confirmation_versions']
    assert len(pipeline.evaluations) == 2 and not pipeline.publications


def test_infrastructure_unknown_never_supplies_zero_or_triggers_full_retry(pipeline_factory):
    pipeline = pipeline_factory(scores=[None])
    result = pipeline.run()
    assert result['status'] == 'infrastructure_failed'
    assert result['rounds'][0]['development']['score']['overall_pass_at_1'] is None
    assert len(pipeline.evaluations) == 1 and not pipeline.publications


def test_proven_infrastructure_recovery_keeps_same_cohort_and_counts_usage(pipeline_factory):
    pipeline = pipeline_factory(scores=[None, .1])
    recovered = []

    def recover(directory):
        recovered.append(directory)
        result = json.loads((directory / 'evaluation_manifest.json').read_text())
        result.update(status='completed')
        result['score'].update(overall_pass_at_1=.1, scored_tasks=20, infrastructure_errors=0)
        result['infrastructure_retries'] = [{'index': 1, 'task_ids': [item['task_id'] for item in result['attempts']]}]
        _write(directory / 'evaluation_manifest.json', result)
        return result

    pipeline._resume_infrastructure = recover
    result = pipeline.run()
    assert result['status'] == 'completed'
    assert len(recovered) == 1 and recovered[0].name == 'development'
    assert [item['phase'] for item in pipeline.evaluations] == ['development', 'confirmation']
    assert len(pipeline.publications) == 1
    assert pipeline.settings.get('max_infrastructure_retries', 2) == 2


def test_interrupted_frontier_does_not_start_infrastructure_recovery(pipeline_factory):
    pipeline = pipeline_factory(scores=[None])
    original = pipeline._evaluate

    def interrupt(*args, **kwargs):
        result = original(*args, **kwargs)
        result['failure_kind'] = 'evaluation_interrupted'
        return result

    pipeline._evaluate = interrupt
    pipeline._resume_infrastructure = lambda _: pytest.fail('An explicit interruption must not restart model work')
    result = pipeline.run()
    assert result['status'] == 'cancelled'
    assert len(pipeline.evaluations) == 1 and not pipeline.publications


def test_quality_shortfall_routes_feedback_without_weakening_gates(pipeline_factory):
    pipeline = pipeline_factory(scores=[.1, .1], shortfall_rounds=[1])
    result = pipeline.run()
    assert result['status'] == 'completed'
    assert result['rounds'][0]['status'] == 'quality_shortfall'
    feedback = pipeline.generated_configs[1]['generation_feedback']
    assert feedback['reason'] == 'quality_shortfall'
    assert 'PRIVATE_FIXTURE_SECRET_1234567890' not in json.dumps(feedback)
    assert pipeline.generated_configs[1]['run']['max_evidence_rounds_per_revision'] == 2
    assert [item['round'] for item in pipeline.evaluations] == [2, 2]


def test_round_budget_stops_explicitly_without_publication(pipeline_factory):
    pipeline = pipeline_factory(scores=[.9, .8], settings={'max_rounds': 2})
    result = pipeline.run()
    assert result['status'] == 'budget_exhausted' and len(result['rounds']) == 2
    assert 'max_rounds' in result['reason'] and not pipeline.publications
    assert result['usage']['total_tokens'] == 660


def test_token_cap_checked_between_stages_retains_real_usage(pipeline_factory):
    pipeline = pipeline_factory(settings={'max_total_tokens': 100})
    result = pipeline.run()
    assert result['status'] == 'budget_exhausted'
    assert result['usage']['total_tokens'] == 110
    assert not pipeline.evaluations and not pipeline.publications
    assert result['rounds'][0]['status'] == 'budget_exhausted'


def test_output_and_old_attempts_are_never_overwritten(pipeline_factory):
    pipeline = pipeline_factory(scores=[.1, .1])
    pipeline.run()
    before = (pipeline.directory / 'difficulty_manifest.json').read_bytes()
    with pytest.raises(DifficultyError, match='already exists'):
        DifficultyPipeline(pipeline.config, pipeline.seed_manifest, pipeline.directory, project_root=pipeline.root)
    assert (pipeline.directory / 'difficulty_manifest.json').read_bytes() == before


def test_real_parent_panel_exposes_stage_and_child_links(pipeline_factory):
    pipeline = pipeline_factory(scores=[.1, .1])
    pipeline._dashboard = lambda: DifficultyPipeline._dashboard(pipeline)
    result = pipeline.run()
    with urllib.request.urlopen(result['dashboard_url'] + 'api/snapshot') as response:
        snapshot = json.load(response)
    with urllib.request.urlopen(result['dashboard_url']) as response:
        html = response.read().decode()
    assert 'difficulty-children' in html
    assert snapshot['run']['child_runs']
    assert snapshot['metrics']['qualified'] == 20
    assert all(child['url'].startswith('http://127.0.0.1:') for child in snapshot['run']['child_runs'])
    assert any(node['node'] == 'fresh_confirmation' for node in snapshot['nodes'])


def test_workbook_repackaging_is_not_a_new_business_version(tmp_path):
    from openpyxl import Workbook, load_workbook
    export = tmp_path / 'task'
    (export / 'environment').mkdir(parents=True)
    (export / 'tests').mkdir()
    (export / 'instruction.md').write_text('Restore the public model and save output.xlsx.')
    for file, value in [('environment/input.xlsx', 1), ('tests/reference.xlsx', 2)]:
        book = Workbook()
        book.active['A1'] = value
        book.save(export / file)
        book.close()
    before = semantic_task_fingerprint(export)
    archive_before = dirhash(export, 'sha256')
    file = export / 'environment/input.xlsx'
    book = load_workbook(file)
    book.properties.creator = 'Another author; business cells unchanged'
    book.save(file)
    book.close()
    assert dirhash(export, 'sha256') != archive_before
    assert semantic_task_fingerprint(export) == before
    book = load_workbook(file)
    book.active['A1'] = 3
    book.save(file)
    book.close()
    assert semantic_task_fingerprint(export) != before
