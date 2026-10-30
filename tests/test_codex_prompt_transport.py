"""Prompt-transport process tests with an explicitly fake executable backend.

The executable only records its input and emits deterministic fixture events.
No test invokes a real model, provider API, Docker container, or evaluation.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sheets_factory.core.audit import AuditStore
from sheets_factory.llm import CodexCLI, CodexError


_FAKE_BACKEND = r'''
import hashlib,json,os,pathlib,re,stat,sys,time
incoming=sys.stdin.read()
work=pathlib.Path.cwd()
match=re.search(r"(?:/workspace/)?\.factory_request_[A-Za-z0-9_-]+\.txt", incoming)
reference=match.group(0) if match else None
staged=(work/pathlib.Path(reference).name) if reference else None
body=staged.read_text(encoding="utf-8") if staged else incoming
observation={
    "fixture_only":True,"stdin":incoming,"content":body,"reference":reference,
    "workspace":str(work),"sha256":hashlib.sha256(body.encode("utf-8")).hexdigest(),
    "chars":len(body),"bytes":len(body.encode("utf-8")),
    "mode":stat.S_IMODE(staged.stat().st_mode) if staged else None,
    "staged_name":staged.name if staged else None,
}
if WAIT_FOR_PEER:
    deadline=time.monotonic()+4
    while time.monotonic()<deadline:
        names=sorted(p.name for p in work.glob(".factory_request_*.txt"))
        if len(names)>=2:
            observation["concurrent_staged_names"]=names
            break
        time.sleep(.01)
    else:
        raise RuntimeError("Fake concurrency fixture did not observe two staged requests")
(work/(".fixture_transport_probe_"+str(os.getpid())+".json")).write_text(
    json.dumps(observation,ensure_ascii=False),encoding="utf-8")
print(json.dumps({"type":"turn.completed","usage":{"input_tokens":100,
    "cached_input_tokens":40,"output_tokens":10,"reasoning_output_tokens":3}}),flush=True)
if ECHO_SECRET:
    print(os.environ["SHEETS_FACTORY_API_KEY"],file=sys.stderr,flush=True)
if FAILURE_MODE=="timeout":
    time.sleep(30)
elif FAILURE_MODE=="nonzero":
    print("deterministic fake-backend exit",file=sys.stderr,flush=True)
    sys.exit(7)
print(json.dumps({"type":"item.completed","item":{"type":"agent_message",
    "text":json.dumps({"ok":True})}}),flush=True)
'''


class _Harness:
    def __init__(self, root: Path):
        self.root = root
        self.run = root / "outputs" / "fixture_run"
        self.audit = AuditStore(self.run, {"id": "fake-prompt-transport-only"})
        self.key = "synthetic-transport-secret-never-a-real-credential"
        secret_dir = root / ".secrets"
        secret_dir.mkdir()
        (secret_dir / "api_key").write_text(self.key)
        self.stub = root / "explicit_fake_codex_backend"
        self.public = root / "dedicated_public_workspace"
        self.public.mkdir()
        self.write_backend()

    def write_backend(self, *, failure="", wait_for_peer=False, echo_secret=False):
        settings = (f"FAILURE_MODE={failure!r}\nWAIT_FOR_PEER={wait_for_peer!r}\n"
                    f"ECHO_SECRET={echo_secret!r}\n")
        self.stub.write_text(f"#!{sys.executable}\n" + settings + _FAKE_BACKEND)
        self.stub.chmod(0o755)

    def backend(self, **settings):
        return CodexCLI(self.root, self.run, self.audit, {
            "binary": str(self.stub), "max_parallel_calls": 2,
            "base_url": "http://127.0.0.1:9/v1", **settings,
        })

    def records(self):
        return self.audit.snapshot()["llm_calls"]

    @staticmethod
    def observations(work):
        return [json.loads(path.read_text()) for path in sorted(work.glob(".fixture_transport_probe_*.json"))]


@pytest.fixture
def harness(tmp_path, monkeypatch):
    # Do not inherit a real credential or endpoint into the fixture process.
    monkeypatch.delenv("SHEETS_FACTORY_API_KEY", raising=False)
    monkeypatch.delenv("SHEETS_FACTORY_BASE_URL", raising=False)
    helper = _Harness(tmp_path)
    yield helper
    helper.audit.db.close()


@contextmanager
def _fake_isolation_command(backend, stub):
    """Capture real command construction, then run only the local fake process."""
    original = backend._build_command
    captures = []

    def build(work, endpoint, isolated, name, **kwargs):
        actual = original(work, endpoint, isolated, name, **kwargs)
        captures.append({
            "command": actual, "work": work, "isolated": isolated,
            "staged": list(work.glob(".factory_request_*.txt")),
        })
        return [str(stub)]

    with patch.object(backend, "_build_command", side_effect=build), patch(
        "sheets_factory.llm.codex.subprocess.run", return_value=SimpleNamespace(returncode=0)
    ):
        yield captures


def _audit_transport(record, *, kind, threshold, model_input=None):
    directory = Path(record["record_path"])
    request = json.loads((directory / "request.json").read_text())
    result = json.loads((directory / "result.json").read_text())
    body = (directory / "prompt.txt").read_text(encoding="utf-8")
    transport = request["prompt_transport"]
    actual_input = body if model_input is None else model_input
    assert result["prompt_transport"] == transport
    assert transport["kind"] == kind
    assert transport["sha256"] == sha256(actual_input.encode("utf-8")).hexdigest()
    assert transport["chars"] == len(actual_input)
    assert transport["bytes"] == len(actual_input.encode("utf-8"))
    assert transport["audit_sha256"] == sha256(body.encode("utf-8")).hexdigest()
    assert transport["threshold_chars"] == threshold
    required = {"kind", "sha256", "chars", "bytes", "audit_sha256", "threshold_chars"}
    assert set(transport) == required | ({"path"} if kind == "workspace_file" else set())
    assert "Return exactly one JSON object as your final response" in body
    return body, transport


def test_small_prompt_keeps_full_stdin_and_records_default_threshold(harness):
    backend = harness.backend()
    assert backend.complete("Small explicit fixture prompt", "planner", workspace=harness.public) == {"ok": True}
    record = harness.records()[0]
    body, transport = _audit_transport(record, kind="stdin", threshold=262144)
    observation, = harness.observations(harness.public)
    assert observation["fixture_only"] is True
    assert observation["stdin"] == body == observation["content"]
    assert observation["reference"] is None
    assert not list(harness.public.glob(".factory_request_*.txt"))
    assert "path" not in transport


def test_threshold_counts_unicode_characters_instead_of_utf8_bytes(harness):
    backend = harness.backend(prompt_stdin_max_chars=256)
    backend.complete("汉" * 100, "planner", workspace=harness.public)
    body, _ = _audit_transport(harness.records()[0], kind="stdin", threshold=256)
    assert len(body) <= 256 < len(body.encode("utf-8"))
    observation, = harness.observations(harness.public)
    assert observation["stdin"] == body


def test_small_credential_text_preserves_legacy_stdin_but_distinguishes_clean_audit_hash(harness):
    backend = harness.backend(prompt_stdin_max_chars=4096)
    backend.complete("Small synthetic credential fixture: " + harness.key, "planner", workspace=harness.public)
    observation, = harness.observations(harness.public)
    body, transport = _audit_transport(harness.records()[0], kind="stdin", threshold=4096,
                                       model_input=observation["stdin"])
    assert harness.key in observation["stdin"]
    assert harness.key not in body and "[REDACTED]" in body
    assert transport["sha256"] != transport["audit_sha256"]
    assert observation["reference"] is None


@pytest.mark.parametrize("extra_characters", [0, 1])
def test_complete_uses_stdin_at_exact_threshold_and_file_above_it(harness, extra_characters):
    # Derive the actual complete() suffix from its audit rather than omitting it
    # or copying the production suffix into a separate expected implementation.
    harness.backend().complete("", "planner", workspace=harness.public)
    before = harness.records()
    suffix = (Path(before[0]["record_path"]) / "prompt.txt").read_text()
    threshold = 128 + len(suffix)
    prompt = "x" * (128 + extra_characters)
    harness.backend(prompt_stdin_max_chars=threshold).complete(prompt, "planner", workspace=harness.public)
    record, = [row for row in harness.records() if row["call_id"] != before[0]["call_id"]]
    body, transport = _audit_transport(record, kind="workspace_file" if extra_characters else "stdin",
                                       threshold=threshold)
    assert body == prompt + suffix
    assert transport["chars"] == threshold + extra_characters
    assert not list(harness.public.glob(".factory_request_*.txt"))


def test_raw_oversize_prompt_stages_even_when_redaction_makes_clean_text_shorter(harness):
    prompt = harness.key * 10
    harness.backend(prompt_stdin_max_chars=256).complete(prompt, "planner", workspace=harness.public)
    body, transport = _audit_transport(harness.records()[0], kind="workspace_file", threshold=256)
    observation, = harness.observations(harness.public)
    assert len(prompt) > 256 >= len(body)
    assert observation["content"] == body
    assert harness.key not in observation["content"]
    assert transport["sha256"] == transport["audit_sha256"]
    assert not list(harness.public.glob(".factory_request_*.txt"))


@pytest.mark.parametrize("isolated", [False, True])
def test_large_unicode_prompt_stages_only_clean_text_with_same_sha(harness, isolated):
    harness.write_backend(echo_secret=True)
    backend = harness.backend(prompt_stdin_max_chars=128)
    prompt = "经营🙂α\n" * 100 + harness.key
    with _fake_isolation_command(backend, harness.stub) as captures:
        assert backend.complete(prompt, "planner", workspace=harness.public, isolated=isolated) == {"ok": True}
    record = harness.records()[0]
    body, transport = _audit_transport(record, kind="workspace_file", threshold=128)
    expected_name = f".factory_request_{record['call_id']}.txt"
    assert transport["path"] == ("/workspace/" if isolated else "") + expected_name
    observation, = harness.observations(harness.public)
    assert observation["reference"] == transport["path"]
    assert observation["content"] == body
    assert observation["sha256"] == transport["sha256"]
    assert transport["sha256"] == transport["audit_sha256"]
    assert observation["bytes"] == transport["bytes"] > transport["chars"]
    assert observation["mode"] == 0o600
    assert len(observation["stdin"].encode("utf-8")) < 2048
    assert harness.key not in body
    assert "[REDACTED]" in body and "经营🙂α" in body
    assert harness.key not in observation["stdin"]
    assert captures[0]["staged"] == [harness.public / expected_name]
    assert not (harness.public / expected_name).exists()
    assert (Path(record["record_path"]) / "prompt.txt").is_file()
    for path in Path(record["record_path"]).rglob("*"):
        if path.is_file():
            assert harness.key not in path.read_text()
    assert harness.key not in json.dumps(harness.records())


def test_more_than_one_mebibyte_uses_short_stdin_and_preserves_full_private_audit(harness):
    # >1MiB UTF-8 and >the default character threshold, without a real model.
    prompt = "Large deterministic fixture\n" + "汉🙂" * 170000
    backend = harness.backend()
    backend.complete(prompt, "planner", workspace=harness.public)
    body, transport = _audit_transport(harness.records()[0], kind="workspace_file", threshold=262144)
    observation, = harness.observations(harness.public)
    assert transport["bytes"] > 1024 * 1024
    assert body.startswith(prompt)
    assert observation["content"] == body
    assert len(observation["stdin"].encode("utf-8")) < 2048
    assert not list(harness.public.glob(".factory_request_*.txt"))


def test_nonisolated_default_private_work_uses_relative_pointer_and_cleans_it(harness):
    backend = harness.backend(prompt_stdin_max_chars=32)
    backend.complete("Private planning fixture " * 30, "planner")
    record = harness.records()[0]
    _, transport = _audit_transport(record, kind="workspace_file", threshold=32)
    work = Path(record["workspace"])
    assert work == Path(record["record_path"]) / "work"
    assert Path(transport["path"]).parent == Path(".")
    observation, = harness.observations(work)
    assert observation["reference"] == transport["path"]
    assert not (work / transport["path"]).exists()


def test_isolated_prompt_and_schema_never_mount_private_call_directory(harness):
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "required": ["ok"], "additionalProperties": False}
    private_schema = harness.root / ".secrets" / "fixture_schema.json"
    private_schema.write_text(json.dumps(schema))
    backend = harness.backend(prompt_stdin_max_chars=64)
    with _fake_isolation_command(backend, harness.stub) as captures:
        backend.complete("Public prompt fixture " * 30, "public", workspace=harness.public,
                         isolated=True, output_schema=private_schema)
    record = harness.records()[0]
    _, transport = _audit_transport(record, kind="workspace_file", threshold=64)
    command = captures[0]["command"]
    mounts = [command[i + 1] for i, item in enumerate(command) if item == "--volume"]
    assert mounts == [str(harness.public) + ":/workspace:rw", str(harness.stub) + ":/usr/local/bin/codex:ro"]
    assert not any(str(Path(record["record_path"])) in mount for mount in mounts)
    assert not any(str(harness.root / ".secrets") in mount for mount in mounts)
    assert str(private_schema) not in command
    schema_reference = Path(command[command.index("--output-schema") + 1])
    assert schema_reference.parent == Path("/workspace")
    assert Path(transport["path"]).parent == Path("/workspace")
    assert not (harness.public / schema_reference.name).exists()
    assert not list(harness.public.glob(".factory_request_*.txt"))


@pytest.mark.parametrize("failure", ["launch", "nonzero", "timeout"])
def test_failed_large_call_cleans_staged_file_and_keeps_audit(harness, failure):
    harness.write_backend(failure=failure)
    backend = harness.backend(prompt_stdin_max_chars=64)
    with _fake_isolation_command(backend, harness.stub) as captures:
        if failure == "launch":
            with patch("sheets_factory.llm.codex.subprocess.Popen", side_effect=OSError("fixture launch failure")):
                with pytest.raises(CodexError):
                    backend.complete("Failure fixture " * 80, "planner", workspace=harness.public)
        else:
            with pytest.raises(CodexError):
                backend.complete("Failure fixture " * 80, "planner", workspace=harness.public,
                                 timeout=0.25 if failure == "timeout" else 5)
    record = harness.records()[0]
    body, transport = _audit_transport(record, kind="workspace_file", threshold=64)
    assert record["status"] == "failed"
    assert captures[0]["staged"]
    assert all(not path.exists() for path in captures[0]["staged"])
    assert not list(harness.public.glob(".factory_request_*.txt"))
    assert body.startswith("Failure fixture ")
    if failure == "timeout":
        assert record["failure_kind"] == "timeout"
        assert record["input_tokens"] == 100
    elif failure == "nonzero":
        assert record["returncode"] == 7
        assert record["input_tokens"] == 100
    else:
        assert record["input_tokens"] is None
    assert transport["path"] == f".factory_request_{record['call_id']}.txt"


def test_cleanup_failure_is_audited_as_failure_instead_of_success(harness):
    backend = harness.backend(prompt_stdin_max_chars=64)
    original_unlink = Path.unlink

    def refuse_staged_unlink(path, *args, **kwargs):
        if path.parent == harness.public and path.name.startswith(".factory_request_"):
            raise OSError("explicit fixture cleanup failure")
        return original_unlink(path, *args, **kwargs)

    with patch.object(Path, "unlink", new=refuse_staged_unlink):
        with pytest.raises(CodexError):
            backend.complete("Cleanup fixture " * 80, "planner", workspace=harness.public)
    record = harness.records()[0]
    _audit_transport(record, kind="workspace_file", threshold=64)
    assert record["status"] == "failed"
    assert record["failure_kind"] == "prompt_transport_cleanup"
    remaining, = harness.public.glob(".factory_request_*.txt")
    assert "explicit fixture cleanup failure" in record["error"]
    # Restore the deliberately refused cleanup after the assertion; this is a
    # temporary fixture file, not a tolerated orphan in the product path.
    remaining.unlink()


@pytest.mark.parametrize("collision_kind", ["file", "symlink"])
def test_staging_is_exclusive_and_never_overwrites_or_unlinks_existing_path(harness, collision_kind):
    backend = harness.backend(prompt_stdin_max_chars=64)
    call_id = "c" * 32
    collision = harness.public / f".factory_request_{call_id}.txt"
    victim = harness.public / "existing_fixture.txt"
    victim.write_text("existing content must survive")
    if collision_kind == "file":
        collision.write_text("existing content must survive")
    else:
        collision.symlink_to(victim)
    with patch("sheets_factory.llm.codex.uuid.uuid4", return_value=SimpleNamespace(hex=call_id)), patch(
        "sheets_factory.llm.codex.subprocess.Popen"
    ) as process:
        with pytest.raises(CodexError):
            backend.complete("Exclusive staging fixture " * 30, "planner", workspace=harness.public)
    process.assert_not_called()
    assert collision.exists()
    assert collision.read_text() == "existing content must survive"
    assert victim.read_text() == "existing content must survive"
    assert collision.is_symlink() is (collision_kind == "symlink")


@pytest.mark.parametrize("large", [False, True])
def test_transport_preserves_usage_schema_and_role_overrides(harness, large):
    backend = harness.backend(prompt_stdin_max_chars=256, roles={
        "planner": {"model": "explicit-fixture-model", "reasoning_effort": "xhigh", "timeout_seconds": 7},
    })
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "required": ["ok"], "additionalProperties": False}
    prompt = "Fixture request " * (100 if large else 1)
    with _fake_isolation_command(backend, harness.stub) as captures:
        assert backend.complete(prompt, "planner", workspace=harness.public, output_schema=schema) == {"ok": True}
    record = harness.records()[0]
    _audit_transport(record, kind="workspace_file" if large else "stdin", threshold=256)
    assert record["model"] == "explicit-fixture-model"
    assert record["reasoning_effort"] == "xhigh"
    assert record["timeout_seconds"] == 7
    assert record["input_tokens"] == 100
    assert record["cached_input_tokens"] == 40
    assert record["output_tokens"] == 10
    assert record["usage"]["reasoning_output_tokens"] == 3
    assert record["output_schema_enabled"] is True
    command = captures[0]["command"]
    assert command[command.index("-m") + 1] == "explicit-fixture-model"
    assert 'model_reasoning_effort="xhigh"' in command
    assert "--output-schema" in command
    assert backend.model == "gpt-6-sol" and backend.reasoning == "high"


@pytest.mark.parametrize("threshold", [1, 262144, 524288])
def test_integer_threshold_bounds_are_accepted_without_a_process(harness, threshold):
    with patch("sheets_factory.llm.codex.subprocess.Popen") as process:
        harness.backend(prompt_stdin_max_chars=threshold)
    process.assert_not_called()


@pytest.mark.parametrize("threshold", [0, -1, 524289, True, False, 1.0, 262144.0, "262144", None])
def test_invalid_thresholds_are_rejected_without_a_process(harness, threshold):
    with patch("sheets_factory.llm.codex.subprocess.Popen") as process:
        with pytest.raises(ValueError):
            harness.backend(prompt_stdin_max_chars=threshold)
    process.assert_not_called()


def test_concurrent_large_requests_have_distinct_owned_files_and_contents(harness):
    harness.write_backend(wait_for_peer=True)
    backend = harness.backend(prompt_stdin_max_chars=64)
    prompts = ["Concurrent-A-汉🙂" * 100, "Concurrent-B-β" * 100]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda text: backend.complete(text, "planner", workspace=harness.public), prompts))
    assert results == [{"ok": True}, {"ok": True}]
    records = harness.records()
    assert len(records) == 2
    expected = {}
    for record in records:
        body, transport = _audit_transport(record, kind="workspace_file", threshold=64)
        expected[transport["path"]] = (body, transport["sha256"])
    assert len(expected) == 2
    observations = harness.observations(harness.public)
    assert len(observations) == 2
    for observation in observations:
        body, digest = expected[observation["reference"]]
        assert observation["content"] == body
        assert observation["sha256"] == digest
        assert observation["mode"] == 0o600
        assert set(observation["concurrent_staged_names"]) == set(expected)
    assert not list(harness.public.glob(".factory_request_*.txt"))
