"""Run the native Codex CLI with an explicit provider and isolated public agents."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any


NATIVE_CODEX = "/data/home/zhaoyanghan/.local/share/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex"


class CodexError(RuntimeError):
    """A failed call whose diagnostics and any known usage were persisted."""

    def __init__(self, message: str, call_id: str = "", record_path: str = ""):
        super().__init__(message)
        self.call_id = call_id
        self.record_path = record_path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode_object(reply: str) -> dict:
    reply = reply.strip()
    match = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", reply, re.S | re.I)
    if match:
        reply = match.group(1).strip()
    value = json.loads(reply)
    if not isinstance(value, dict):
        raise ValueError("Codex final response must be a JSON object")
    return value


class CodexCLI:
    """Model calls with private raw records and public audit summaries.

    ``complete`` returns the final parsed JSON object. ``attempt`` runs a
    tool-using agent in an actual Docker filesystem boundary and returns its
    reply, raw events and usage; it does not score whether the agent solved it.
    """

    def __init__(self, project_root: Path, run_dir: Path, audit: Any, config: dict):
        self.project_root = Path(project_root).resolve()
        self.run_dir = Path(run_dir).resolve()
        self.audit = audit
        self.config = dict(config)
        self.model = self.config.get("model", "gpt-6-sol")
        self.reasoning = self.config.get("reasoning_effort", "high")
        self.binary = Path(self.config.get("binary", NATIVE_CODEX)).expanduser().resolve()
        self.image = self.config.get("container_image", "sheetsfactory-lo:24.2")
        self.env_key = self.config.get("provider_env_key", "SHEETS_FACTORY_API_KEY")
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", self.env_key):
            raise ValueError("Provider environment variable name is invalid")
        self.provider = self.config.get("provider", "factory")
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", self.provider):
            raise ValueError("Provider name is invalid")
        slots = int(self.config.get("max_parallel_calls", 4))
        if slots < 1:
            raise ValueError("max_parallel_calls must be positive")
        self._slots = threading.BoundedSemaphore(slots)

    def _role_settings(self, role: str, timeout: int | None = None) -> dict:
        """Resolve call-local settings without changing defaults shared by threads."""
        overrides = self.config.get("roles", {}).get(role, {})
        resolved = {
            "model": overrides.get("model", self.model),
            "reasoning_effort": overrides.get("reasoning_effort", self.reasoning),
            "timeout_seconds": timeout if timeout is not None else overrides.get(
                "timeout_seconds", self.config.get("timeout_seconds", 300)),
        }
        if not isinstance(resolved["model"], str) or not resolved["model"].strip():
            raise ValueError("Role model must be a nonempty string")
        if not isinstance(resolved["reasoning_effort"], str) or not resolved["reasoning_effort"].strip():
            raise ValueError("Role reasoning effort must be a nonempty string")
        if not isinstance(resolved["timeout_seconds"], (int, float)) or resolved["timeout_seconds"] <= 0:
            raise ValueError("Role timeout must be positive")
        return resolved

    def _path(self, setting: str, default: str) -> Path:
        value = Path(self.config.get(setting, default)).expanduser()
        return value if value.is_absolute() else self.project_root / value

    def _credentials(self) -> tuple[str, str]:
        key = os.environ.get(self.env_key)
        if not key:
            key = self._path("api_key_file", ".secrets/api_key").read_text().strip()
        if not key or "\n" in key or "\r" in key:
            raise ValueError("API credential is missing or malformed")
        base = os.environ.get("SHEETS_FACTORY_BASE_URL") or self.config.get("base_url")
        if not base:
            metadata = json.loads(self._path("endpoint_metadata_file", ".secrets/metadata.json").read_text())
            urls = metadata.get("urls", [])
            if not urls:
                raise ValueError("Provider endpoint is not configured")
            base = urls[0]
        base = str(base).rstrip("/")
        if not base.startswith(("http://", "https://")):
            raise ValueError("Provider endpoint must use HTTP or HTTPS")
        return key, base if base.endswith("/v1") else base + "/v1"

    def _environment(self, key: str) -> dict[str, str]:
        # Native Codex must bypass the desktop wrapper and inherited proxy.
        env = {k: v for k, v in os.environ.items() if not k.upper().endswith("_PROXY") and k.upper() != "PROXY"}
        env[self.env_key] = key
        return env

    def _build_command(self, workspace: Path, endpoint: str, isolated: bool, name: str,
                       *, model: str | None = None, reasoning: str | None = None) -> list[str]:
        cli = ["/usr/local/bin/codex" if isolated else str(self.binary), "exec",
               "--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check",
               "--json", "--color", "never", "-m", model or self.model]
        settings = {
            "model_reasoning_effort": reasoning or self.reasoning,
            "model_provider": self.provider,
            f"model_providers.{self.provider}.name": self.provider,
            f"model_providers.{self.provider}.base_url": endpoint,
            f"model_providers.{self.provider}.env_key": self.env_key,
            f"model_providers.{self.provider}.wire_api": "responses",
        }
        for key, value in settings.items():
            cli.extend(["-c", key + "=" + json.dumps(value)])
        if isolated:
            cli += ["--dangerously-bypass-approvals-and-sandbox", "-C", "/workspace", "-"]
            public_tools = []
            code_host = self.binary.with_name("codex-code-mode-host")
            if code_host.is_file():
                public_tools += ["--volume", str(code_host) + ":/usr/local/bin/codex-code-mode-host:ro"]
            return ["docker", "run", "--rm", "-i", "--name", name,
                    "--network", "host", "--cap-drop", "ALL", "--cap-add", "DAC_OVERRIDE",
                    "--security-opt", "no-new-privileges", "--user", "0:0",
                    "--memory", str(self.config.get("container_memory", "2g")),
                    "--cpus", str(self.config.get("container_cpus", 2)),
                    "--pids-limit", "256", "--tmpfs", "/tmp:rw,nosuid,nodev,size=1g",
                    "--env", self.env_key,
                    "--volume", str(workspace) + ":/workspace:rw",
                    "--volume", str(self.binary) + ":/usr/local/bin/codex:ro",
                    *public_tools,
                    "--workdir", "/workspace", "--entrypoint", "/usr/local/bin/codex",
                    self.image, *cli[1:]]
        return cli + ["--sandbox", "read-only", "-c", 'approval_policy="never"', "-C", str(workspace), "-"]

    def complete(self, prompt: str, role: str, task_id: str = "", stage: str = "",
                 workspace: Path | None = None, isolated: bool = False, timeout: int | None = None) -> dict:
        final_prompt = prompt + "\n\nReturn exactly one JSON object as your final response, without commentary."
        result = self._invoke(final_prompt, role, task_id, stage, workspace, isolated, timeout, True)
        return result["parsed"]

    def attempt(self, prompt: str, workspace: Path, taskid: str = "", stage: str = "trajectory",
                timeout: int | None = None, **kwargs) -> dict:
        task_id = kwargs.pop("task_id", taskid)
        if kwargs:
            raise TypeError("Unexpected attempt arguments: " + ", ".join(kwargs))
        return self._invoke(prompt, "trace_agent", task_id, stage, workspace, True, timeout, False)

    def _invoke(self, prompt: str, role: str, task_id: str, stage: str,
                workspace: Path | None, isolated: bool, timeout: int | None, expect_json: bool) -> dict:
        with self._slots:
            return self._invoke_slot(prompt, role, task_id, stage, workspace, isolated, timeout, expect_json)

    def _invoke_slot(self, prompt: str, role: str, task_id: str, stage: str,
                     workspace: Path | None, isolated: bool, timeout: int | None, expect_json: bool) -> dict:
        settings = self._role_settings(role, timeout)
        timeout = settings["timeout_seconds"]
        call_id = uuid.uuid4().hex
        directory = self.run_dir / "llm_calls" / "private" / call_id
        directory.mkdir(parents=True, mode=0o700)
        directory.chmod(0o700)
        started = _now()
        clock = time.monotonic()
        events: list[dict] = []
        usage = None
        reply = ""
        parsed = None
        key = ""
        process = None
        container_name = "sf-codex-" + call_id[:20]
        error = None
        interrupted = False
        failure_kind = None
        returncode = None
        stderr_parts: list[str] = []
        threads: list[threading.Thread] = []

        def clean(value):
            if isinstance(value, str):
                return value.replace(key, "[REDACTED]") if key else value
            if isinstance(value, dict):
                return {k: clean(v) for k, v in value.items()}
            if isinstance(value, list):
                return [clean(v) for v in value]
            return value

        request = {"call_id": call_id, "role": role, "task_id": task_id, "stage": stage,
                   "model": settings["model"], "reasoning_effort": settings["reasoning_effort"],
                   "isolated": isolated, "started_at": started, "timeout_seconds": timeout}
        self.audit.emit("llm.started", **request)
        try:
            if not self.binary.is_file() or not os.access(self.binary, os.X_OK):
                raise ValueError("Configured native Codex binary is not executable")
            key, endpoint = self._credentials()
            work = Path(workspace).resolve() if workspace else directory / "work"
            if isolated and (work in [self.project_root, self.run_dir] or work in self.project_root.parents):
                raise ValueError("Isolated agents require a dedicated public workspace")
            work.mkdir(parents=True, exist_ok=True)
            request.update({"endpoint": endpoint, "workspace": str(work)})
            (directory / "request.json").write_text(json.dumps(request, indent=2))
            (directory / "prompt.txt").write_text(clean(prompt))
            command = self._build_command(work, endpoint, isolated, container_name,
                                          model=settings["model"], reasoning=settings["reasoning_effort"])
            process = subprocess.Popen(command, cwd=work, env=self._environment(key),
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding="utf-8", errors="replace", start_new_session=True)

            def read_stdout():
                with (directory / "events.jsonl").open("w") as stream:
                    for line in process.stdout:
                        line = clean(line)
                        stream.write(line)
                        stream.flush()
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        if not isinstance(event, dict):
                            continue
                        events.append(event)
                        item = event.get("item")
                        self.audit.emit("llm.progress", call_id=call_id, role=role, task_id=task_id,
                                        stage=stage, event_type=event.get("type"),
                                        item_type=item.get("type") if isinstance(item, dict) else None)

            def read_stderr():
                with (directory / "stderr.txt").open("w") as stream:
                    for line in process.stderr:
                        line = clean(line)
                        stderr_parts.append(line)
                        stream.write(line)
                        stream.flush()

            threads = [threading.Thread(target=read_stdout, daemon=True),
                       threading.Thread(target=read_stderr, daemon=True)]
            for thread in threads:
                thread.start()
            try:
                process.stdin.write(prompt)
                process.stdin.close()
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                failure_kind = "timeout"
                raise CodexError(f"Codex call exceeded {timeout}s")
            finally:
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=10)
                for thread in threads:
                    thread.join(timeout=10)
            for event in events:
                if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
                    current = event["usage"]
                    if usage is None:
                        usage = {}
                    for field, value in current.items():
                        if isinstance(value, (int, float)) and not isinstance(value, bool):
                            usage[field] = usage.get(field, 0) + value
                item = event.get("item") or {}
                if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                    reply = item.get("text", "")
            if returncode:
                failure_kind = "process_exit"
                raise CodexError(f"Codex exited with status {returncode}")
            if not reply.strip():
                failure_kind = "missing_reply"
                raise CodexError("Codex produced no final response")
            if expect_json:
                try:
                    parsed = _decode_object(reply)
                except (ValueError, TypeError) as exc:
                    failure_kind = "invalid_json"
                    raise CodexError("Codex final response was not a valid JSON object") from exc
        except KeyboardInterrupt:
            error = "Codex call cancelled"
            failure_kind = "cancelled"
            interrupted = True
        except Exception as exc:
            error = clean(str(exc))
            failure_kind = failure_kind or "execution_error"
        finally:
            if isolated and process is not None:
                try:
                    subprocess.run(["docker", "rm", "--force", container_name],
                                   capture_output=True, timeout=20, env=self._environment(key))
                except (OSError, subprocess.SubprocessError):
                    pass
            # On timeouts, preserve any usage received before interruption.
            if usage is None:
                completed = [e.get("usage") for e in events
                             if e.get("type") == "turn.completed" and isinstance(e.get("usage"), dict)]
                if completed:
                    usage = {}
                    for entry in completed:
                        for name, value in entry.items():
                            if isinstance(value, (int, float)) and not isinstance(value, bool):
                                usage[name] = usage.get(name, 0) + value
            if not reply:
                messages = [e.get("item", {}).get("text", "") for e in events
                            if e.get("type") == "item.completed"
                            and e.get("item", {}).get("type") == "agent_message"]
                if messages:
                    reply = messages[-1]
            elapsed = round((time.monotonic() - clock) * 1000)
            record = {**request, "status": "failed" if error else "completed", "finished_at": _now(),
                      "duration_ms": elapsed, "returncode": returncode, "usage": usage,
                      "input_tokens": usage.get("input_tokens") if usage else None,
                      "output_tokens": usage.get("output_tokens") if usage else None,
                      "cached_input_tokens": usage.get("cached_input_tokens") if usage else None,
                      "record_path": str(directory), "failure_kind": failure_kind, "error": error}
            (directory / "final_reply.txt").write_text(clean(reply))
            (directory / "result.json").write_text(json.dumps(clean(record), ensure_ascii=False, indent=2))
            self.audit.record("calls", clean(record))
            self.audit.emit("llm.failed" if error else "llm.completed", call_id=call_id, role=role,
                            task_id=task_id, stage=stage, duration_ms=elapsed,
                            input_tokens=record["input_tokens"], output_tokens=record["output_tokens"],
                            cached_input_tokens=record["cached_input_tokens"],
                            failure_kind=failure_kind, error=error)
            if process is not None:
                for stream in [process.stdin, process.stdout, process.stderr]:
                    if stream is not None:
                        stream.close()
        if interrupted:
            raise KeyboardInterrupt
        if error:
            raise CodexError(error, call_id, str(directory))
        return {"reply": reply, "events": events, "usage": usage, "parsed": parsed,
                "call_id": call_id, "duration_ms": elapsed, "record_path": str(directory)}
