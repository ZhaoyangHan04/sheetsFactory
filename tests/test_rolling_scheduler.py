"""Offline rolling-admission and Harbor serialization contracts.

These tests use real temporary SQLite audits. Producer phases and Harbor's
calculation body are fixed control-flow fixtures, never model or LO substitutes.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import multiprocessing
from pathlib import Path
import threading

import pytest
import yaml

from sheets_factory.core.audit import AuditStore
from sheets_factory.pipelines.factory import FactoryPipeline
from sheets_factory.reporting import read_run
from sheets_factory.resume import ResumeError, candidate_task_id, prepare_resume


ROOT = Path(__file__).resolve().parents[1]
FM, DBG = "financial_modeling", "debugging"


def seed_fixture(directory, name, *, modes=None):
    source = directory / (name + ".xls")
    source.write_bytes(("Scheduling identity fixture: " + name).encode())
    return {"local_path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "modes": modes or [FM, DBG], "finance_evidence": {"financial_modeling_eligible": True},
            "debugging_eligible": True}


class OfflineFactory(FactoryPipeline):
    """Exercise the controller while recording all source/task transitions."""

    def __init__(self, config, audit, seeds, execute=None, reject_at_harbor=()):
        super().__init__(config, audit, None, None)
        self.fixture_seeds, self.execute_fixture = seeds, execute
        self.reject_at_harbor = set(reject_at_harbor)
        self.source_activity, self.source_events, self.task_events = {}, [], []
        self.validation_calls = []
        self.fixture_lock = threading.Lock()

    def load_seeds(self):
        return deepcopy(self.fixture_seeds)

    def run_phase(self, context, phase):
        assert phase == "preparation", "The offline fixture must not invoke real producer nodes"
        self.audit.task(context.task_id, status="running")

    def _execute_context(self, context, **kwargs):
        with self.fixture_lock:
            self.task_events.append((context.task_id, context.mode, context.data["variant"]))
        if self.execute_fixture:
            self.execute_fixture(context)
        else:
            self.audit.task(context.task_id, status="ready", node="harbor_pending")

    def process_source(self, seed):
        source = seed["sha256"]
        with self.fixture_lock:
            self.source_activity[source] = self.source_activity.get(source, 0) + 1
            assert self.source_activity[source] == 1, "Two variants of the same source ran concurrently"
            self.source_events.append(("start", source, seed.get("variant", 0)))
        try:
            return super().process_source(seed)
        finally:
            with self.fixture_lock:
                self.source_activity[source] -= 1
                self.source_events.append(("end", source, seed.get("variant", 0)))

    def _validate_exports_locked(self):
        ready = [task for task in self.audit.snapshot()["tasks"] if task.get("status") == "ready"]
        self.validation_calls.append([task["id"] for task in ready])
        for task in ready:
            rejected = task["id"] in self.reject_at_harbor
            self.reject_at_harbor.discard(task["id"])
            self.audit.task(task["id"], status="rejected" if rejected else "qualified",
                            node="harbor_failed" if rejected else "complete")


@pytest.fixture
def factory_builder(tmp_path):
    audits = []

    def build(seeds=(), *, targets=None, scheduler="rolling", variants=3, workers=2,
              execute=None, reject_at_harbor=()):
        directory = tmp_path / ("run-" + str(len(audits)))
        config = {"project_root": str(ROOT), "run_dir": str(directory),
                  "run": {"targets": targets or {FM: 2, DBG: 2}, "max_steps": 3,
                          "max_evidence_rounds_per_revision": 2, "infrastructure_retries_per_stage": 2,
                          "max_parallel_sources": workers, "max_candidates_per_seed": variants,
                          "variant_modes": list(targets or {FM: 2, DBG: 2})}, "harbor": {"concurrency": 1}}
        if scheduler is not None:
            config["run"]["scheduler"] = scheduler
        audit = AuditStore(directory, {"id": "offline-rolling-" + str(len(audits))})
        audits.append(audit)
        return OfflineFactory(config, audit, list(seeds), execute, reject_at_harbor), audit

    yield build
    for audit in audits:
        audit.db.close()


def tasks_by_id(audit):
    return {task["id"]: task for task in audit.snapshot()["tasks"]}


def test_atomic_admission_counts_ready_inflight_union_and_release_is_idempotent(factory_builder):
    factory, audit = factory_builder(targets={FM: 2})
    barrier = threading.Barrier(8)

    def compete(index):
        barrier.wait(timeout=5)
        return index, factory.reserve(FM, "fm-admit-" + str(index))

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(compete, range(8)))
    admitted = ["fm-admit-" + str(index) for index, accepted in results if accepted]
    assert len(admitted) == 2
    assert set(factory.inflight_tasks) == set(admitted)
    # One worker publishes ready before its finally releases its permit.
    audit.task(admitted[0], mode=FM, status="ready")
    factory._release_task(FM, admitted[1])
    assert factory.reserve(FM, "fm-replacement"), "ready+inflight overlap consumed the same slot twice"
    assert not factory.reserve(FM, "fm-overflow")
    factory._release_task(FM, admitted[0])
    factory._release_task(FM, admitted[0])
    factory._release_task(FM, "fm-replacement")
    assert factory.inflight_tasks == {}
    assert all(value == 0 for value in factory.active.values())


def test_context_exception_releases_admission(factory_builder, tmp_path, monkeypatch):
    source = seed_fixture(tmp_path, "context-failure", modes=[FM])
    factory, _ = factory_builder([source], targets={FM: 1})

    def broken_context(*args):
        raise OSError("Fixture context creation failed")

    monkeypatch.setattr(factory, "_context", broken_context)
    try:
        factory.process_task(source, FM)
    except OSError as exc:
        assert "context creation" in str(exc)
    assert factory.inflight_tasks == {}
    assert factory.active[FM] == 0
    assert factory.reserve(FM, "fm-after-context-failure")
    factory._release_task(FM, "fm-after-context-failure")


def test_quota_deferred_does_not_create_task_and_same_id_can_retry(factory_builder, tmp_path):
    source = seed_fixture(tmp_path, "deferred", modes=[FM])
    factory, audit = factory_builder([source], targets={FM: 1})
    assert factory.reserve(FM, "fm-held-permit")
    task_id = candidate_task_id(source, FM)
    result = factory.process_task(source, FM)
    assert result == {"task_id": task_id, "status": "quota_deferred"}
    assert task_id not in tasks_by_id(audit)
    assert not (Path(factory.config["run_dir"]) / "tasks" / task_id).exists()
    factory._release_task(FM, "fm-held-permit")
    assert factory.process_task(source, FM) == {"task_id": task_id, "status": "processed"}
    assert tasks_by_id(audit)[task_id]["status"] == "ready"


def test_existing_task_budgets_are_frozen_and_new_variant_has_new_identity(factory_builder, tmp_path):
    source = seed_fixture(tmp_path, "old-task", modes=[FM])
    factory, audit = factory_builder([source], targets={FM: 1})
    task_id = candidate_task_id(source, FM)
    audit.task(task_id, source_id=source["sha256"], mode=FM, status="rejected", revision=3,
               content_repairs=3, evidence_rounds=2, infrastructure_retries=2,
               error="EXHAUSTED: historical fixture")
    before = deepcopy(tasks_by_id(audit)[task_id])
    assert not factory.reserve(FM, task_id)
    assert factory.process_task(source, FM) == {"task_id": task_id, "status": "skipped_existing"}
    assert tasks_by_id(audit)[task_id] == before
    variant = {**source, "variant": 1}
    new_id = candidate_task_id(variant, FM)
    assert factory.process_task(variant, FM)["status"] == "processed"
    assert new_id != task_id and tasks_by_id(audit)[new_id]["variant"] == 1
    assert tasks_by_id(audit)[task_id] == before


def test_rolling_advances_fast_source_before_straggler_and_serializes_same_sha(factory_builder, tmp_path):
    fast = seed_fixture(tmp_path, "fast", modes=[FM])
    slow = seed_fixture(tmp_path, "slow", modes=[FM])
    slow_started, release_slow, fast_variant_started = (threading.Event() for _ in range(3))

    def execute(context):
        if context.source.name == "slow.xls":
            slow_started.set()
            assert release_slow.wait(8), "Test failed to release the straggler"
        elif context.data["variant"] == 1:
            assert slow_started.wait(5)
            fast_variant_started.set()
        context.audit.task(context.task_id, status="ready", node="harbor_pending")

    factory, audit = factory_builder([fast, slow], targets={FM: 3}, execute=execute)
    with ThreadPoolExecutor(max_workers=1) as controller:
        work = controller.submit(factory._construct_rolling, [fast, slow])
        try:
            assert fast_variant_started.wait(5), "Rolling waited for the unrelated slow source"
            assert ("end", slow["sha256"], 0) not in factory.source_events
        finally:
            release_slow.set()
        submitted = work.result(timeout=8)
    assert submitted == 3
    assert factory.source_events.index(("end", fast["sha256"], 0)) < factory.source_events.index(
        ("start", fast["sha256"], 1))
    assert sum(task["status"] == "ready" for task in audit.snapshot()["tasks"]) == 3
    assert factory.inflight_tasks == {} and all(count == 0 for count in factory.source_activity.values())


def test_same_source_next_variant_waits_for_both_sequential_modes(factory_builder, tmp_path):
    source = seed_fixture(tmp_path, "two-mode-source")
    modeling_finished, debugging_started, debugging_finished, release_debugging, variant_started = (
        threading.Event() for _ in range(5))

    def execute(context):
        variant = context.data["variant"]
        if variant == 0 and context.mode == DBG:
            assert modeling_finished.is_set(), "Source modes did not run sequentially"
            debugging_started.set()
            assert release_debugging.wait(8), "Test failed to release the second mode"
        if variant == 1:
            assert modeling_finished.is_set() and debugging_finished.is_set(), (
                "The next variant entered before the entire previous source job completed")
            variant_started.set()
        context.audit.task(context.task_id, status="ready", node="harbor_pending")
        if variant == 0:
            (modeling_finished if context.mode == FM else debugging_finished).set()

    factory, audit = factory_builder([source], targets={FM: 2, DBG: 2}, variants=2, execute=execute)
    with ThreadPoolExecutor(max_workers=1) as controller:
        work = controller.submit(factory._construct_rolling, [source])
        try:
            assert debugging_started.wait(5)
            assert modeling_finished.is_set()
            assert not variant_started.wait(0.15), "A free worker started a sibling variant during debugging"
        finally:
            release_debugging.set()
        assert variant_started.wait(5)
        submitted = work.result(timeout=8)
    assert submitted == 2
    assert factory.source_events == [("start", source["sha256"], 0), ("end", source["sha256"], 0),
                                     ("start", source["sha256"], 1), ("end", source["sha256"], 1)]
    assert [(mode, variant) for _, mode, variant in factory.task_events] == [(FM, 0), (DBG, 0), (FM, 1), (DBG, 1)]
    assert len(audit.snapshot()["tasks"]) == 4


def test_mode_deficits_exhaust_finite_variants_without_extra_satisfied_mode_tasks(factory_builder, tmp_path):
    source = seed_fixture(tmp_path, "finite")

    def execute(context):
        context.audit.task(context.task_id, status="rejected" if context.mode == FM else "ready")

    factory, audit = factory_builder([source], targets={FM: 2, DBG: 1}, variants=3, execute=execute)
    assert not factory.run()
    tasks = audit.snapshot()["tasks"]
    assert len([task for task in tasks if task["mode"] == FM]) == 3
    assert len([task for task in tasks if task["mode"] == DBG]) == 1
    assert next(task for task in tasks if task["mode"] == DBG)["status"] == "qualified"
    assert audit.run["status"] == "shortfall"
    assert factory.inflight_tasks == {}


def test_run_validates_existing_ready_before_admitting_new_work(factory_builder, tmp_path):
    old_source = seed_fixture(tmp_path, "existing-ready", modes=[FM])
    new_source = seed_fixture(tmp_path, "new-admission", modes=[FM])
    factory, audit = factory_builder([new_source], targets={FM: 2})
    # Set after initialization: this test exercises run ordering, not restoring
    # target claims from a real completed producer's workbook artifacts.
    factory.config["run"]["continuation_id"] = "offline-continuation"
    existing = candidate_task_id(old_source, FM)
    old_proof = {"fixture_proof": {"oracle": 1, "nop": 0, "revision": 2}}
    old_binding = {"task_id": existing, "revision": 2, "revision_hash": "fixture-old-revision"}
    audit.task(existing, source_id=old_source["sha256"], mode=FM, status="ready", revision=2,
               content_repairs=2, evidence_rounds=1, infrastructure_retries=2,
               harbor_controls=old_proof, harbor_export_binding=old_binding)
    original_validate = factory._validate_exports_locked
    original_load = factory.load_seeds
    ordering = []

    def validate():
        if not factory.validation_calls:
            assert not factory.task_events, "New production began before existing ready exports were validated"
            ordering.append("validate-existing")
        original_validate()

    def load():
        assert ordering == ["validate-existing"], "Seeds loaded before continuation prevalidation"
        ordering.append("load-seeds")
        return original_load()

    factory._validate_exports_locked = validate
    factory.load_seeds = load
    assert factory.run()
    assert factory.validation_calls[0] == [existing]
    assert ordering == ["validate-existing", "load-seeds"]
    new_task_id = candidate_task_id(new_source, FM)
    assert [task_id for task_id, _, _ in factory.task_events] == [new_task_id]
    tasks = tasks_by_id(audit)
    assert tasks[existing]["status"] == tasks[new_task_id]["status"] == "qualified"
    assert {key: tasks[existing][key] for key in ("revision", "content_repairs", "evidence_rounds", "infrastructure_retries")} == {
        "revision": 2, "content_repairs": 2, "evidence_rounds": 1, "infrastructure_retries": 2}
    assert tasks[existing]["harbor_controls"] == old_proof
    assert tasks[existing]["harbor_export_binding"] == old_binding


def test_harbor_rejection_reopens_deficit_and_fills_with_new_variant(factory_builder, tmp_path):
    source = seed_fixture(tmp_path, "harbor-refill", modes=[FM])
    first = candidate_task_id(source, FM)
    second = candidate_task_id({**source, "variant": 1}, FM)
    factory, audit = factory_builder([source], targets={FM: 1}, variants=2, reject_at_harbor=[first])
    assert factory.run()
    tasks = tasks_by_id(audit)
    assert tasks[first]["status"] == "rejected"
    assert tasks[second]["status"] == "qualified"
    assert [task_id for task_id, _, _ in factory.task_events] == [first, second]
    assert [first] in factory.validation_calls and [second] in factory.validation_calls
    assert audit.run["status"] == "completed"


def test_async_quota_deferred_mode_refills_original_variant_after_harbor_rejection(factory_builder, tmp_path):
    source_a = seed_fixture(tmp_path, "deferred-source-a")
    source_b = seed_fixture(tmp_path, "deferred-source-b")
    a_fm, a_dbg = (candidate_task_id(source_a, mode) for mode in (FM, DBG))
    b_fm, b_dbg = (candidate_task_id(source_b, mode) for mode in (FM, DBG))
    b_debugging_ready, first_validation_finished = threading.Event(), threading.Event()

    def execute(context):
        if context.task_id == a_fm:
            # A holds one FM permit while B completes its entire source job.
            assert b_debugging_ready.wait(8), "B never published the competing debugging task"
        elif context.task_id == a_dbg:
            assert first_validation_finished.is_set(), "Deferred A debugging ran before Harbor released its quota"
            assert context.data["variant"] == 0
        context.audit.task(context.task_id, status="ready", node="harbor_pending")
        if context.task_id == b_dbg:
            b_debugging_ready.set()

    factory, audit = factory_builder([source_a, source_b], targets={FM: 2, DBG: 1},
                                     variants=2, execute=execute, reject_at_harbor=[b_dbg])
    original_validate = factory._validate_exports_locked

    def validate():
        first = not factory.validation_calls
        if first:
            # The quota refusal must not create a task or consume its v0 ID.
            assert a_dbg not in tasks_by_id(audit)
            assert not (Path(factory.config["run_dir"]) / "tasks" / a_dbg).exists()
            deferred = [event for event in audit.events() if event["kind"] == "scheduler.quota_deferred"]
            assert any(event.get("task_id") == a_dbg for event in deferred)
        original_validate()
        if first:
            assert tasks_by_id(audit)[b_dbg]["status"] == "rejected"
            first_validation_finished.set()

    factory._validate_exports_locked = validate
    assert factory.run()
    tasks = tasks_by_id(audit)
    assert set(tasks) == {a_fm, a_dbg, b_fm, b_dbg}
    assert not any("-v1" in task_id for task_id in tasks)
    assert factory.task_events.count((a_fm, FM, 0)) == 1
    assert factory.task_events.count((a_dbg, DBG, 0)) == 1
    assert len(factory.task_events) == 4, "Refill repeated completed tasks or admitted an unnecessary variant"
    assert set(factory.validation_calls[0]) == {a_fm, b_fm, b_dbg}
    assert factory.validation_calls[1:] == [[a_dbg]]
    assert {mode: sum(task["mode"] == mode and task["status"] == "qualified" for task in tasks.values())
            for mode in (FM, DBG)} == {FM: 2, DBG: 1}
    assert tasks[b_dbg]["status"] == "rejected"
    assert audit.run["source_variant_jobs"] == 3  # A v0, B v0, then only A's missing v0 mode.
    assert factory.inflight_tasks == {} and factory.busy_sources == set()


def test_default_scheduler_keeps_batch_path(factory_builder, tmp_path, monkeypatch):
    source = seed_fixture(tmp_path, "batch-default", modes=[FM])
    factory, _ = factory_builder([source], targets={FM: 1}, scheduler=None)
    original_batch = factory._construct_batch
    batches = []

    def batch(seeds):
        batches.append([item["sha256"] for item in seeds])
        return original_batch(seeds)

    monkeypatch.setattr(factory, "_construct_batch", batch)
    monkeypatch.setattr(factory, "_construct_rolling", lambda *_: pytest.fail("Default entered rolling scheduler"))
    assert factory.run()
    assert batches == [[source["sha256"]]]


def test_harbor_validation_lock_serializes_threads_and_releases_after_error(factory_builder):
    first, _ = factory_builder(targets={FM: 1})
    # Separate instances share the run path, as standalone validators do.
    second = FactoryPipeline(first.config, first.audit, None, None)
    entered_first, release_first, entered_second = (threading.Event() for _ in range(3))

    def failing_body():
        entered_first.set()
        assert release_first.wait(5)
        raise RuntimeError("Fixture Harbor body failed")

    first._validate_exports_locked = failing_body
    second._validate_exports_locked = entered_second.set
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(first._validate_exports)
        assert entered_first.wait(5)
        two = pool.submit(second._validate_exports)
        try:
            assert not entered_second.wait(0.15), "Concurrent validator entered the locked body"
        finally:
            release_first.set()
        with pytest.raises(RuntimeError, match="Harbor body failed"):
            one.result(timeout=5)
        two.result(timeout=5)
    assert entered_second.is_set()


def _process_harbor_lock(config, entered, release):
    """A separate-process validator must use the same filesystem lease."""
    audit = AuditStore(Path(config["run_dir"]), {"id": "process-lock-fixture"})
    try:
        factory = FactoryPipeline(config, audit, None, None)

        def body():
            entered.set()
            assert release.wait(8), "Parent did not release process lock fixture"

        factory._validate_exports_locked = body
        factory._validate_exports()
    finally:
        audit.db.close()


@pytest.mark.skipif("fork" not in multiprocessing.get_all_start_methods(), reason="Requires POSIX flock processes")
def test_harbor_validation_lock_serializes_independent_processes(factory_builder):
    factory, _ = factory_builder(targets={FM: 1})
    mp = multiprocessing.get_context("fork")
    entered_first, release_first, entered_second, release_second = (mp.Event() for _ in range(4))
    first = mp.Process(target=_process_harbor_lock, args=(factory.config, entered_first, release_first))
    second = mp.Process(target=_process_harbor_lock, args=(factory.config, entered_second, release_second))
    first.start()
    try:
        assert entered_first.wait(5)
        second.start()
        assert not entered_second.wait(0.2), "The lock was only local to one process"
        release_first.set()
        assert entered_second.wait(5)
    finally:
        release_first.set()
        release_second.set()
        first.join(timeout=8)
        if second.pid is not None:
            second.join(timeout=8)
        for process in (first, second):
            if process.is_alive():
                process.terminate()
                process.join(timeout=3)
    assert first.exitcode == 0 and second.exitcode == 0


def resume_fixture(tmp_path):
    directory = tmp_path / "resume-run"
    audit = AuditStore(directory, {"id": "rolling-resume-fixture", "status": "shortfall"})
    proof = {"fixture_immutable_proof": {"oracle": 1, "nop": 0, "revision": 2}}
    audit.task("fm-" + "a" * 12, mode=FM, source_id="a" * 64, status="qualified", revision=2,
               content_repairs=2, evidence_rounds=1, infrastructure_retries=2, harbor_controls=proof,
               targets=[["Forecast", "B1"]])
    audit.task("dbg-" + "b" * 12, mode=DBG, source_id="b" * 64, status="rejected", revision=3,
               content_repairs=3, evidence_rounds=2, infrastructure_retries=2)
    config = {"project_root": str(ROOT), "run_dir": str(directory),
              "run": {"targets": {FM: 20, DBG: 20}, "max_steps": 3,
                      "max_evidence_rounds_per_revision": 2, "infrastructure_retries_per_stage": 2,
                      "max_sources": 20}, "agents": {"model": "gpt-6-sol", "reasoning_effort": "high"}}
    (directory / "resolved_config.yaml").write_text(yaml.safe_dump(config))
    before = deepcopy(audit.snapshot()["tasks"])
    audit.db.close()
    return directory, config, before


def test_resume_can_switch_to_rolling_without_resetting_budgets_or_bound_proofs(tmp_path):
    directory, config, before = resume_fixture(tmp_path)
    with prepare_resume(directory, config_patch={"run": {"scheduler": "rolling"}},
                        producer_probe=lambda *_: []) as session:
        assert session.config["run"]["scheduler"] == "rolling"
        assert session.audit.run["scheduler"] == "rolling"
        assert session.audit.snapshot()["tasks"] == before
        for key in ("max_steps", "max_evidence_rounds_per_revision", "infrastructure_retries_per_stage"):
            assert session.config["run"][key] == config["run"][key]
        amended = next(event for event in session.audit.events() if event["kind"] == "run.amended")
        assert amended["scheduler_before"] == "source_batches"
        assert amended["scheduler_after"] == "rolling"


@pytest.mark.parametrize("scheduler", ["rollng", "parallel", "", None, 3, True])
def test_resume_rejects_unknown_scheduler_without_amending_run(tmp_path, scheduler):
    directory, config, before = resume_fixture(tmp_path)
    with pytest.raises(ResumeError, match="scheduler|Scheduler"):
        prepare_resume(directory, config_patch={"run": {"scheduler": scheduler}}, producer_probe=lambda *_: [])
    assert yaml.safe_load((directory / "resolved_config.yaml").read_text()) == config
    snapshot = read_run(directory)
    assert snapshot["tasks"] == before and snapshot["run"]["status"] == "shortfall"
