"""Offline stop boundaries using real SQLite usage and synchronized threads.

The backend below records declared call observations. It does not reconstruct
spreadsheets, return model answers, or stand in for LibreOffice calculation.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import fcntl
import json
from pathlib import Path
import signal
import threading

import pytest

from sheets_factory.checkers import DiagnosisRunner
from sheets_factory.core.audit import AuditStore
from sheets_factory.core.node import BaseNode, CooperativeCancelled
from sheets_factory.nodes.quality import RecoveryNode, TrajectoryNode
from sheets_factory.pipelines.factory import FactoryPipeline, cooperative_sigint
from sheets_factory.reporting import read_run
from sheets_factory.resume import assert_resume_allowed, candidate_task_id
from test_difficulty_pipeline import pipeline_factory
from test_rolling_scheduler import seed_fixture


ROOT = Path(__file__).resolve().parents[1]
FM, DBG = 'financial_modeling', 'debugging'


class ObservedBackend:
    """Hold one admitted call, then persist its explicitly declared usage."""
    model = 'offline-cancellation-observation'

    def __init__(self, audit, *, block=False, slots=1):
        self.audit = audit
        self.config = {'max_parallel_calls': slots}
        self.started, self.release = threading.Event(), threading.Event()
        if not block:
            self.release.set()
        self.calls = []
        self.lock = threading.Lock()

    def _observe(self, method, *, task_id='', **kwargs):
        with self.lock:
            call_id = 'declared-offline-observation-' + str(len(self.calls))
            self.calls.append((method, task_id))
        row = self.audit.record('calls', {'call_id': call_id, 'task_id': task_id,
            'status': 'running', 'model': self.model, 'input_tokens': None})
        self.started.set()
        assert self.release.wait(8), 'Test did not release its admitted backend call'
        self.audit.update_record('calls', row, {'status': 'completed',
            'input_tokens': 100, 'cached_input_tokens': 40, 'output_tokens': 7})
        return {'offline_observation': call_id}

    def complete(self, text, **kwargs):
        return self._observe('complete', **kwargs)

    def attempt(self, text, workspace=None, taskid='', **kwargs):
        return self._observe('attempt', task_id=kwargs.pop('task_id', taskid), **kwargs)


@pytest.fixture
def factory_builder(tmp_path, monkeypatch):
    audits = []

    def build(*, scheduler='rolling', block=False, workers=1, slots=1, stop_event=None):
        directory = tmp_path / ('cancel-run-' + str(len(audits)))
        config = {'project_root': str(ROOT), 'run_dir': str(directory),
            'run': {'scheduler': scheduler, 'targets': {FM: 3, DBG: 2},
                'max_steps': 3, 'max_evidence_rounds_per_revision': 2,
                'infrastructure_retries_per_stage': 2, 'max_parallel_sources': workers,
                'max_candidates_per_seed': 2, 'variant_modes': [FM, DBG]},
            'agents': {'max_parallel_calls': slots, 'timeout_seconds': 10,
                       'trajectory_timeout_seconds': 10}, 'harbor': {'concurrency': 1}}
        audit = AuditStore(directory, {'id': 'offline-cancellation-' + str(len(audits))})
        audits.append(audit)
        backend = ObservedBackend(audit, block=block, slots=slots)
        factory = FactoryPipeline(config, audit, backend, None, stop_event=stop_event)
        return factory, audit, backend

    yield build
    for audit in audits:
        audit.db.close()


def attach_preparation(factory, monkeypatch, nodes):
    mapping = {node.node_id: node for node in nodes}
    monkeypatch.setattr(factory, 'load_node', lambda node_id: mapping[node_id])
    for template in factory.templates.values():
        template['phases']['preparation'] = list(mapping)


class ObserveCall(BaseNode):
    node_id = 'declared_observation'

    def execute(self, context):
        context.audit.task(context.task_id, evidence_rounds=1, infrastructure_retries=2,
                           content_repairs=0)
        observed = context.llm.complete('Record this offline call observation.', task_id=context.task_id)
        context.save('inflight_observation.json', observed)
        return {'inflight_observation': observed}


class ForbiddenLaterNode(BaseNode):
    node_id = 'must_not_start_after_stop'

    def execute(self, context):
        pytest.fail('A later node started after the cooperative stop')


def test_active_call_finishes_and_usage_survives_without_starting_next_node(
        factory_builder, tmp_path, monkeypatch):
    factory, audit, backend = factory_builder(block=True)
    source = seed_fixture(tmp_path, 'active-call', modes=[FM])
    attach_preparation(factory, monkeypatch, [ObserveCall(), ForbiddenLaterNode()])
    monkeypatch.setattr(factory, '_execute_context', lambda context: pytest.fail('Revision started after stop'))
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(factory.process_task, source, FM)
        try:
            assert backend.started.wait(5)
            factory.request_stop('offline-test')
            assert not future.done(), 'Stopping interrupted an admitted backend call'
            assert audit.snapshot()['llm_calls'][0]['status'] == 'running'
        finally:
            backend.release.set()
        future.result(timeout=5)
    snapshot = audit.snapshot()
    task, = snapshot['tasks']
    assert task['status'] == 'cancelled'
    assert (task['content_repairs'], task['evidence_rounds'], task['infrastructure_retries']) == (0, 1, 2)
    assert snapshot['metrics']['total_tokens'] == 107
    assert snapshot['metrics']['cached_input_tokens'] == 40
    assert snapshot['llm_calls'][0]['status'] == 'completed'
    assert [node['node'] for node in snapshot['nodes']] == [ObserveCall.node_id]
    assert snapshot['nodes'][0]['status'] == 'completed'
    observation = Path(factory.config['run_dir']) / 'tasks' / task['id'] / 'revisions/000/private/inflight_observation.json'
    assert json.loads(observation.read_text())['offline_observation']
    assert factory.inflight_tasks == {} and all(value == 0 for value in factory.active.values())
    assert not any(event['kind'] == 'task.rejected' for event in audit.events())


def test_second_call_inside_one_node_is_cancelled_and_node_is_not_recorded_completed(
        factory_builder, tmp_path, monkeypatch):
    factory, audit, backend = factory_builder(block=True)
    source = seed_fixture(tmp_path, 'two-calls', modes=[FM])

    class TwoCalls(BaseNode):
        node_id = 'two_call_node'
        def execute(self, context):
            context.llm.complete('First declared observation.', task_id=context.task_id)
            context.llm.complete('This call must never enter the backend.', task_id=context.task_id)
            pytest.fail('The second model call crossed a stopped admission boundary')

    attach_preparation(factory, monkeypatch, [TwoCalls()])
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(factory.process_task, source, FM)
        try:
            assert backend.started.wait(5)
            factory.request_stop()
        finally:
            backend.release.set()
        future.result(timeout=5)
    snapshot = audit.snapshot()
    assert len(backend.calls) == 1 and snapshot['metrics']['total_tokens'] == 107
    assert snapshot['nodes'][0]['status'] == 'cancelled'
    assert snapshot['tasks'][0]['status'] == 'cancelled'
    assert not any(event['kind'] == 'node.completed' for event in audit.events())


def test_call_waiting_for_a_model_slot_never_enters_backend_after_stop(
        factory_builder, monkeypatch):
    factory, audit, backend = factory_builder(block=True, slots=1)
    queued = threading.Event()
    acquire = factory.llm._slots.acquire

    def observe_admission(*args, **kwargs):
        if backend.started.is_set():
            queued.set()
        return acquire(*args, **kwargs)

    monkeypatch.setattr(factory.llm._slots, 'acquire', observe_admission)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(factory.llm.complete, 'Admitted observation.', task_id='first')
        assert backend.started.wait(5)
        second = executor.submit(factory.llm.complete, 'Queued observation.', task_id='queued')
        try:
            assert queued.wait(5)
            factory.request_stop()
            with pytest.raises(CooperativeCancelled):
                second.result(timeout=3)
            assert not first.done()
        finally:
            backend.release.set()
        first.result(timeout=5)
    assert backend.calls == [('complete', 'first')]
    assert audit.snapshot()['metrics']['total_tokens'] == 107


@pytest.mark.parametrize('node_type', [RecoveryNode, TrajectoryNode])
def test_business_exception_handlers_do_not_swallow_explicit_stop(
        factory_builder, tmp_path, node_type):
    factory, audit, backend = factory_builder()
    source = seed_fixture(tmp_path, 'node-stop-' + node_type.node_id, modes=[FM])
    context = factory._context(source, FM)
    context.data.update(input=context.source, instruction='Offline public instruction.')
    factory.request_stop()
    with pytest.raises(CooperativeCancelled):
        node_type().run(context)
    assert not backend.calls
    assert audit.snapshot()['nodes'][0]['status'] == 'cancelled'


def test_diagnosis_backend_retry_handler_does_not_convert_stop_into_infrastructure_failure(factory_builder):
    factory, _, backend = factory_builder()
    factory.request_stop()
    with pytest.raises(CooperativeCancelled):
        DiagnosisRunner(ROOT).diagnose({'task_id': 'offline', 'public': {}}, [], {},
            lambda payload: factory.llm.complete('No new call.'),
            {'selection': {'include': ['Q01']}})
    assert not backend.calls


@pytest.mark.parametrize('scheduler', ['rolling', 'source_batches'])
def test_scheduler_stops_new_sources_and_sibling_modes_preserving_old_proofs(
        factory_builder, tmp_path, monkeypatch, scheduler):
    factory, audit, backend = factory_builder(scheduler=scheduler, block=True, workers=1)
    sources = [seed_fixture(tmp_path, 'source-' + str(index)) for index in range(2)]
    proof = {'oracle': {'reward': 1, 'matched': True}, 'nop': {'reward': 0, 'matched': True}}
    audit.task('fm-old-verified', mode=FM, source_id='f' * 64, status='qualified',
        revision=2, content_repairs=2, evidence_rounds=1, infrastructure_retries=2, harbor_controls=proof)
    old = deepcopy(audit.snapshot()['tasks'][0])
    monkeypatch.setattr(factory, 'load_seeds', lambda: sources)
    monkeypatch.setattr(factory, '_validate_exports', lambda: pytest.fail('A new Harbor batch started after stop'))
    monkeypatch.setattr(factory, '_execute_context', lambda context: pytest.fail('Revision started after stop'))
    attach_preparation(factory, monkeypatch, [ObserveCall()])
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(factory.run)
        try:
            assert backend.started.wait(5)
            factory.request_stop()
        finally:
            backend.release.set()
        assert future.result(timeout=5) is False
    snapshot = audit.snapshot()
    by_id = {task['id']: task for task in snapshot['tasks']}
    assert snapshot['run']['status'] == 'cancelled'
    assert by_id['fm-old-verified'] == old
    assert set(by_id) == {'fm-old-verified', candidate_task_id(sources[0], FM)}
    assert by_id[candidate_task_id(sources[0], FM)]['status'] == 'cancelled'
    assert len(backend.calls) == 1 and snapshot['metrics']['rejected'] == 0
    assert factory.inflight_tasks == {} and factory.busy_sources == set()
    assert all(value == 0 for value in factory.active.values())


def test_stopped_repair_keeps_original_plan_revision_and_spent_budgets(factory_builder, tmp_path, monkeypatch):
    factory, audit, backend = factory_builder()
    source = seed_fixture(tmp_path, 'repair-stop', modes=[FM])
    context = factory._context(source, FM)
    context.revision = 1
    context.data['plan'] = {'title': 'Existing declared fixture plan'}
    audit.task(context.task_id, revision=1, content_repairs=1, evidence_rounds=2, infrastructure_retries=1)
    before = deepcopy(context.data['plan'])
    monkeypatch.setattr(factory, 'load_node', lambda _: pytest.fail('Repair node started after stop'))
    factory.request_stop()
    with pytest.raises(CooperativeCancelled):
        factory._apply_repair(context, [{'problem_id': 'Q03'}])
    assert context.revision == 1 and context.data['plan'] == before and not backend.calls
    task, = audit.snapshot()['tasks']
    assert (task['content_repairs'], task['evidence_rounds'], task['infrastructure_retries']) == (1, 2, 1)


def test_default_stop_events_are_independent_and_explicit_event_is_shared(factory_builder):
    first, _, _ = factory_builder()
    second, _, _ = factory_builder()
    shared = threading.Event()
    third, _, _ = factory_builder(stop_event=shared)
    first.request_stop()
    assert first.stop_event.is_set() and not second.stop_event.is_set()
    assert third.stop_event is shared
    shared.set()
    with pytest.raises(CooperativeCancelled):
        third._checkpoint()


def test_signal_handlers_are_nested_restored_and_frontier_delegation_is_preserved():
    previous = signal.getsignal(signal.SIGINT)
    event = threading.Event()

    def original(signum, frame):
        raise KeyboardInterrupt('Declared original frontier interrupt handler')

    signal.signal(signal.SIGINT, original)
    try:
        with cooperative_sigint(event):
            cooperative = signal.getsignal(signal.SIGINT)
            with cooperative_sigint(event):
                assert signal.getsignal(signal.SIGINT) is cooperative
                cooperative(signal.SIGINT, None)  # Invoke the callback; do not signal another process.
                assert event.is_set()
            assert signal.getsignal(signal.SIGINT) is cooperative
            with cooperative_sigint(event, delegate=True):
                assert signal.getsignal(signal.SIGINT) is original
                with pytest.raises(KeyboardInterrupt, match='original frontier'):
                    signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
            assert signal.getsignal(signal.SIGINT) is cooperative
        assert signal.getsignal(signal.SIGINT) is original
    finally:
        signal.signal(signal.SIGINT, previous)
    assert signal.getsignal(signal.SIGINT) is previous


def test_signal_context_in_worker_does_not_try_to_install_a_process_handler():
    original = signal.getsignal(signal.SIGINT)
    def worker():
        with cooperative_sigint(threading.Event()):
            return signal.getsignal(signal.SIGINT)
    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(worker).result(timeout=5) is original
    assert signal.getsignal(signal.SIGINT) is original


def test_stop_after_quality_does_not_become_shortfall_or_launch_a_new_round(pipeline_factory):
    pipeline = pipeline_factory(shortfall_rounds=[1])
    original = pipeline._run_quality
    def stopped_quality(*args, **kwargs):
        result = original(*args, **kwargs)
        pipeline.request_stop('offline-quality-completed')
        return result
    pipeline._run_quality = stopped_quality
    result = pipeline.run()
    assert result['status'] == 'cancelled'
    assert len(pipeline.generated_configs) == 1 and not pipeline.evaluations and not pipeline.publications
    assert result['rounds'][0]['status'] == 'cancelled'
    assert not (pipeline.directory / 'rounds/001/feedback.json').exists()
    assert result['usage']['total_tokens'] == 110


@pytest.mark.parametrize('score', [.1, None])
def test_stop_after_development_keeps_scored_evidence_and_starts_no_confirmation_or_recovery(
        pipeline_factory, score):
    pipeline = pipeline_factory(scores=[score])
    original = pipeline._evaluate
    retained = {}
    def stopped_evaluation(*args, **kwargs):
        result = original(*args, **kwargs)
        directory = Path(args[1])
        retained['file'] = directory / 'evaluation_manifest.json'
        retained['bytes'] = retained['file'].read_bytes()
        pipeline.request_stop('offline-development-returned')
        return result
    pipeline._evaluate = stopped_evaluation
    pipeline._resume_infrastructure = lambda _: pytest.fail('Cancellation launched infrastructure recovery')
    result = pipeline.run()
    assert result['status'] == 'cancelled'
    assert [entry['phase'] for entry in pipeline.evaluations] == ['development']
    assert retained['file'].read_bytes() == retained['bytes']
    assert json.loads(retained['bytes'])['score']['overall_pass_at_1'] == score
    assert not pipeline.publications and len(pipeline.generated_configs) == 1
    assert result['usage']['total_tokens'] == 330


def test_stop_after_confirmation_preserves_confirmation_but_blocks_publication(pipeline_factory):
    pipeline = pipeline_factory(scores=[.1, .1])
    original = pipeline._evaluate
    retained = {}
    def stop_before_publication(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[2] == 'confirmation':
            retained['file'] = Path(args[1]) / 'evaluation_manifest.json'
            retained['bytes'] = retained['file'].read_bytes()
            pipeline.request_stop('offline-confirmation-returned')
        return result
    pipeline._evaluate = stop_before_publication
    result = pipeline.run()
    assert result['status'] == 'cancelled' and not pipeline.publications
    assert [entry['phase'] for entry in pipeline.evaluations] == ['development', 'confirmation']
    assert result['final_publication'] is None
    assert retained['file'].read_bytes() == retained['bytes']
    assert json.loads(retained['bytes'])['gate_passed'] is True


def test_cleanly_cancelled_task_is_a_frozen_resume_terminal_with_unchanged_budget_and_evidence(
        factory_builder, tmp_path):
    factory, audit, backend = factory_builder()
    source = seed_fixture(tmp_path, 'closed-cancelled', modes=[FM])
    task_id = candidate_task_id(source, FM)
    historical = {'revision_hash': 'declared-old-revision', 'oracle_reward': 1, 'nop_reward': 0}
    audit.task(task_id, mode=FM, source_id=source['sha256'], status='cancelled', revision=2,
        content_repairs=2, evidence_rounds=1, infrastructure_retries=2,
        historical_harbor_controls=historical,
        evidence_receipts=[{'offline_fixture': 'retained executed observation'}])
    audit.record('nodes', {'task_id': task_id, 'node': 'interrupted_followup', 'status': 'cancelled'})
    audit.record('calls', {'task_id': task_id, 'call_id': 'already-drained', 'status': 'completed',
                           'input_tokens': 100, 'cached_input_tokens': 40, 'output_tokens': 7})
    audit.update_run(status='cancelled', producer_active=False)
    before = deepcopy(audit.snapshot())
    run_dir = Path(factory.config['run_dir'])
    assert_resume_allowed(run_dir, read_run(run_dir), producer_probe=lambda *_: [])
    outcome = factory.process_task(source, FM)
    after = audit.snapshot()
    assert outcome == {'task_id': task_id, 'status': 'skipped_existing'}
    assert after['tasks'] == before['tasks'] and after['nodes'] == before['nodes']
    assert after['llm_calls'] == before['llm_calls'] and not backend.calls
    assert after['metrics']['total_tokens'] == before['metrics']['total_tokens'] == 107


def test_unrelated_systemexit_is_not_swallowed_or_misclassified_as_cooperative_stop(
        factory_builder, tmp_path, monkeypatch):
    factory, audit, backend = factory_builder()
    source = seed_fixture(tmp_path, 'real-fatal-exit', modes=[FM])
    class FatalNode(BaseNode):
        node_id = 'fatal_exit_fixture'
        def execute(self, context):
            raise SystemExit(17)
    attach_preparation(factory, monkeypatch, [FatalNode()])
    monkeypatch.setattr(factory, 'load_seeds', lambda: [source])
    with pytest.raises(SystemExit) as observed:
        factory.run()
    assert observed.value.code == 17
    assert not factory.stop_event.is_set() and not backend.calls
    assert audit.snapshot()['run']['status'] != 'cancelled'
    assert audit.snapshot()['tasks'][0]['status'] not in {'cancelled', 'rejected'}
    assert not any(event['kind'] in {'run.cancelled', 'task.cancelled', 'task.rejected'} for event in audit.events())
    assert factory.inflight_tasks == {} and factory.busy_sources == set()


def test_publication_already_finished_atomically_keeps_its_receipt_when_stop_arrives(pipeline_factory):
    pipeline = pipeline_factory(scores=[.1, .1])
    original = pipeline._publish
    retained = {}
    def completed_then_stopped(*args, **kwargs):
        retained['publication'] = original(*args, **kwargs)
        pipeline.request_stop('offline-atomic-publication-already-completed')
        return retained['publication']
    pipeline._publish = completed_then_stopped
    result = pipeline.run()
    assert result['status'] == 'cancelled'
    assert result['final_publication'] == retained['publication']
    assert result['rounds'][0]['status'] == 'published'
    assert len(pipeline.publications) == 1 and len(pipeline.generated_configs) == 1
    assert [entry['phase'] for entry in pipeline.evaluations] == ['development', 'confirmation']
    assert result['usage']['qualified'] == 20 and result['usage']['total_tokens'] == 550
    saved = json.loads((pipeline.directory / 'difficulty_manifest.json').read_text())
    assert saved['final_publication'] == retained['publication']


def test_waiting_for_harbor_validation_file_lock_is_cancellable_without_acquiring_it(
        factory_builder, monkeypatch):
    factory, _, _ = factory_builder()
    lock_path = Path(factory.config['run_dir']) / 'harbor_validation.lock'
    attempted = threading.Event()
    original_flock = fcntl.flock
    def observed_flock(descriptor, operation):
        if operation & fcntl.LOCK_NB:
            attempted.set()
        return original_flock(descriptor, operation)
    with lock_path.open('a+') as holder:
        original_flock(holder.fileno(), fcntl.LOCK_EX)
        monkeypatch.setattr('sheets_factory.pipelines.factory.fcntl.flock', observed_flock)
        monkeypatch.setattr(factory, '_validate_exports_locked',
                            lambda: pytest.fail('Validation started without owning the held lock'))
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(factory._validate_exports)
                assert attempted.wait(5)
                factory.request_stop()
                with pytest.raises(CooperativeCancelled):
                    future.result(timeout=3)
        finally:
            original_flock(holder.fileno(), fcntl.LOCK_UN)
