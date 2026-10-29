"""Exercise the real process boundary with deterministic executable fixtures."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch
from jsonschema import Draft202012Validator, ValidationError

from sheets_factory.core.audit import AuditStore
from sheets_factory.llm import CodexCLI, CodexError
from sheets_factory.llm.schemas import diagnosis_output_schema


class CodexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run = self.root / "outputs" / "test"
        self.audit = AuditStore(self.run, {"id": "run-test"})
        self.key = "test-secret-not-for-audit"
        self.secrets = self.root / ".secrets"
        self.secrets.mkdir()
        (self.secrets / "api_key").write_text(self.key)
        (self.secrets / "metadata.json").write_text(json.dumps({"urls": ["http://127.0.0.1:9999"]}))
        self.stub = self.root / "codex-stub"
        self.config = {"binary": str(self.stub), "max_parallel_calls": 2}
        self.write_stub("""
import json,sys
sys.stdin.read()
print(json.dumps({'type':'thread.started','thread_id':'thread-1'}),flush=True)
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'{"ok":true}'}}),flush=True)
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':40,'output_tokens':10,'reasoning_output_tokens':3}}),flush=True)
""")

    def tearDown(self):
        self.audit.db.close()
        self.temp.cleanup()

    def write_stub(self, code):
        self.stub.write_text("#!/usr/bin/python3\n" + code)
        self.stub.chmod(0o755)

    def backend(self):
        return CodexCLI(self.root, self.run, self.audit, self.config)

    def records(self):
        return self.audit.snapshot()["llm_calls"]

    def test_complete_parses_and_audits_real_child_process(self):
        self.assertEqual(self.backend().complete("Return JSON", "planner", "task-1", "plan"), {"ok": True})
        record = self.records()[0]
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["model"], "gpt-6-sol")
        self.assertEqual(record["reasoning_effort"], "high")
        self.assertEqual(record["input_tokens"], 100)
        self.assertEqual(record["cached_input_tokens"], 40)
        self.assertEqual(record["usage"]["reasoning_output_tokens"], 3)
        directory = Path(record["record_path"])
        self.assertTrue((directory / "events.jsonl").is_file())
        self.assertEqual(json.loads((directory / "final_reply.txt").read_text()), {"ok": True})
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual([e["kind"] for e in self.audit.events()][0], "llm.started")

    def test_model_parameters_and_api_key_are_not_process_arguments(self):
        backend = self.backend()
        command = backend._build_command(self.root / "public", "http://localhost:9999/v1", False, "call")
        self.assertEqual(command[0], str(self.stub))
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ephemeral", command)
        self.assertIn('model_reasoning_effort="high"', command)
        self.assertIn('model_providers.factory.wire_api="responses"', command)
        self.assertNotIn(self.key, " ".join(command))
        self.assertEqual(command[-1], "-")

    def test_concurrent_role_overrides_are_local_and_audited(self):
        self.config["roles"] = {
            "planner": {"model": "planner-model", "reasoning_effort": "high", "timeout_seconds": 15},
            "public_diagnostician": {"model": "review-model", "reasoning_effort": "xhigh", "timeout_seconds": 20},
        }
        backend = self.backend()
        commands = []
        original = backend._build_command

        def capture(*args, **kwargs):
            command = original(*args, **kwargs)
            commands.append(command)
            return command

        with patch.object(backend, "_build_command", side_effect=capture):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda role: backend.complete("prompt", role), ["planner", "public_diagnostician"]))
        self.assertEqual(results, [{"ok": True}, {"ok": True}])
        records = {r["role"]: r for r in self.records()}
        self.assertEqual(records["planner"]["model"], "planner-model")
        self.assertEqual(records["planner"]["timeout_seconds"], 15)
        self.assertEqual(records["public_diagnostician"]["model"], "review-model")
        self.assertEqual(records["public_diagnostician"]["reasoning_effort"], "xhigh")
        self.assertEqual(backend.model, "gpt-6-sol")
        self.assertEqual(backend.reasoning, "high")
        actual = {c[c.index("-m") + 1]: c for c in commands}
        self.assertIn('model_reasoning_effort="high"', actual["planner-model"])
        self.assertIn('model_reasoning_effort="xhigh"', actual["review-model"])

    def test_explicit_timeout_overrides_role_and_role_overrides_global(self):
        self.config.update({"timeout_seconds": 50, "roles": {"planner": {"timeout_seconds": 10}}})
        backend = self.backend()
        self.assertEqual(backend._role_settings("planner")["timeout_seconds"], 10)
        self.assertEqual(backend._role_settings("planner", 8)["timeout_seconds"], 8)
        self.assertEqual(backend._role_settings("other")["timeout_seconds"], 50)
        self.assertEqual(backend._role_settings("other")["model"], "gpt-6-sol")

    def test_isolated_command_exposes_only_workspace_and_binary(self):
        backend = self.backend()
        public = self.root / "public"
        command = backend._build_command(public, "http://localhost:9999/v1", True, "call-test")
        self.assertEqual(command[:3], ["docker", "run", "--rm"])
        mounts = [command[i + 1] for i, item in enumerate(command) if item == "--volume"]
        self.assertEqual(mounts, [str(public) + ":/workspace:rw", str(self.stub) + ":/usr/local/bin/codex:ro"])
        self.assertIn("no-new-privileges", command)
        self.assertIn("DAC_OVERRIDE", command)
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
        env_args = [command[i + 1] for i, item in enumerate(command) if item == "--env"]
        self.assertEqual(env_args, ["SHEETS_FACTORY_API_KEY"])
        self.assertNotIn(self.key, " ".join(command))
        self.assertNotIn(str(self.secrets), " ".join(command))

    def test_proxy_environment_removed_without_repurposing_home(self):
        with patch.dict(os.environ, {"HTTP_PROXY": "proxy", "https_proxy": "proxy", "ALL_PROXY": "proxy", "HOME": "/unchanged"}):
            env = self.backend()._environment(self.key)
        self.assertNotIn("HTTP_PROXY", env)
        self.assertNotIn("https_proxy", env)
        self.assertNotIn("ALL_PROXY", env)
        self.assertEqual(env["HOME"], "/unchanged")
        self.assertEqual(env["SHEETS_FACTORY_API_KEY"], self.key)

    def test_code_mode_sibling_is_mounted_read_only_when_available(self):
        sibling = self.stub.with_name("codex-code-mode-host")
        sibling.write_text("public native tool")
        command = self.backend()._build_command(self.root / "public", "http://localhost:9999/v1", True, "call-test")
        mounts = [command[i + 1] for i, item in enumerate(command) if item == "--volume"]
        self.assertIn(str(sibling) + ":/usr/local/bin/codex-code-mode-host:ro", mounts)
        self.assertEqual(len(mounts), 3)

    def test_timeout_preserves_partial_known_usage(self):
        self.write_stub("""
import json,time,sys
sys.stdin.read()
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':5,'output_tokens':2}}),flush=True)
time.sleep(20)
""")
        with self.assertRaises(CodexError):
            self.backend().complete("prompt", "planner", timeout=0.15)
        self.assertEqual(self.records()[0]["input_tokens"], 5)

    def test_invalid_json_is_failure_but_usage_is_kept(self):
        self.write_stub("""
import json,sys
sys.stdin.read()
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'not JSON'}}))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':4,'output_tokens':2}}))
""")
        with self.assertRaises(CodexError):
            self.backend().complete("prompt", "planner")
        record = self.records()[0]
        self.assertEqual(record["failure_kind"], "invalid_json")
        self.assertEqual(record["input_tokens"], 4)

    def test_timeout_records_unknown_usage_and_terminates_child(self):
        self.write_stub("import time,sys\nsys.stdin.read()\ntime.sleep(20)\n")
        with self.assertRaises(CodexError) as error:
            self.backend().complete("prompt", "planner", timeout=0.1)
        self.assertTrue(error.exception.call_id)
        record = self.records()[0]
        self.assertEqual(record["failure_kind"], "timeout")
        self.assertIsNone(record["input_tokens"])
        self.assertLess(record["duration_ms"], 3000)

    def test_nonzero_exit_preserves_known_usage_and_private_stderr(self):
        self.write_stub("""
import json,sys
sys.stdin.read()
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':4,'output_tokens':1}}))
print('failure detail',file=sys.stderr)
sys.exit(7)
""")
        with self.assertRaises(CodexError):
            self.backend().complete("prompt", "planner")
        record = self.records()[0]
        self.assertEqual(record["returncode"], 7)
        self.assertEqual(record["input_tokens"], 4)
        self.assertIn("failure detail", (Path(record["record_path"]) / "stderr.txt").read_text())

    def test_missing_credentials_also_get_audited(self):
        (self.secrets / "api_key").unlink()
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(CodexError):
                self.backend().complete("prompt", "planner")
        self.assertEqual(self.records()[0]["status"], "failed")
        self.assertIsNone(self.records()[0]["input_tokens"])

    def test_secrets_are_redacted_from_raw_events_stderr_and_audit(self):
        self.write_stub("""
import json,os,sys
sys.stdin.read()
secret=os.environ['SHEETS_FACTORY_API_KEY']
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps({'secret':secret})}}))
print(secret,file=sys.stderr)
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}}))
""")
        result = self.backend().complete("prompt", "planner")
        self.assertEqual(result["secret"], "[REDACTED]")
        for path in (self.run / "llm_calls").rglob("*"):
            if path.is_file():
                self.assertNotIn(self.key, path.read_text())
        self.assertNotIn(self.key, json.dumps(self.records()))

    def test_refuses_mounting_entire_project_as_public_workspace(self):
        with self.assertRaises(CodexError) as error:
            self.backend().complete("prompt", "public", workspace=self.root, isolated=True)
        self.assertIn("dedicated public workspace", str(error.exception))

    def test_fenced_json_object_accepted_but_arrays_rejected(self):
        from sheets_factory.llm.codex import _decode_object
        self.assertEqual(_decode_object('```json\n{"ok":true}\n```'), {"ok": True})
        with self.assertRaises(ValueError):
            _decode_object("[]")

    def test_optional_schema_is_passed_to_cli_and_persisted_privately(self):
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
                  "required": ["ok"], "additionalProperties": False}
        backend = self.backend()
        commands = []
        build = backend._build_command

        def capture(*args, **kwargs):
            command = build(*args, **kwargs)
            commands.append(command)
            return command

        with patch.object(backend, "_build_command", side_effect=capture):
            self.assertEqual(backend.complete("prompt", "planner", output_schema=schema), {"ok": True})
        command = commands[0]
        path = Path(command[command.index("--output-schema") + 1])
        self.assertEqual(json.loads(path.read_text()), schema)
        self.assertEqual(path.parent, Path(self.records()[0]["record_path"]))
        self.assertTrue(self.records()[0]["output_schema_enabled"])
        self.assertEqual(len(self.records()[0]["output_schema_sha256"]), 64)

    def test_no_schema_leaves_native_command_unchanged(self):
        command = self.backend()._build_command(self.root / "public", "http://localhost/v1", False, "call")
        self.assertNotIn("--output-schema", command)

    def test_isolated_schema_maps_only_public_workspace_file_and_is_cleaned(self):
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
                  "required": ["ok"], "additionalProperties": False}
        source = self.secrets / "response_schema.json"
        source.write_text(json.dumps(schema))
        workspace = self.root / "public"
        workspace.mkdir()
        backend = self.backend()
        actual_commands, staged_paths = [], []
        build = backend._build_command

        def fixture_command(work, endpoint, isolated, name, **kwargs):
            actual = build(work, endpoint, isolated, name, **kwargs)
            actual_commands.append(actual)
            mapped = Path(actual[actual.index("--output-schema") + 1])
            self.assertEqual(mapped.parent, Path("/workspace"))
            staged = work / mapped.name
            staged_paths.append(staged)
            self.assertEqual(json.loads(staged.read_text()), schema)
            return [str(self.stub)]

        with patch.object(backend, "_build_command", side_effect=fixture_command), patch("subprocess.run"):
            self.assertEqual(backend.complete("prompt", "public", workspace=workspace, isolated=True,
                                              output_schema=source), {"ok": True})
        command = actual_commands[0]
        mounts = [command[i + 1] for i, item in enumerate(command) if item == "--volume"]
        self.assertEqual(len(mounts), 2)
        self.assertFalse(any(str(self.secrets) in mount for mount in mounts))
        self.assertNotIn(str(source), command)
        self.assertTrue(all(not path.exists() for path in staged_paths))

    def test_reply_schema_failure_keeps_known_usage(self):
        schema = {"type": "object", "properties": {"marker": {"type": "string"}},
                  "required": ["marker"], "additionalProperties": False}
        with self.assertRaises(CodexError):
            self.backend().complete("prompt", "planner", output_schema=schema)
        self.assertEqual(self.records()[0]["failure_kind"], "output_schema_validation")
        self.assertEqual(self.records()[0]["input_tokens"], 100)

    def test_external_schema_refs_and_secret_enums_are_rejected_before_process(self):
        for schema in [{"type": "object", "$ref": "file:///private/goal.json"},
                       {"type": "object", "properties": {"value": {"enum": [self.key]}}}]:
            with self.subTest(schema_kind="external_ref" if "$ref" in schema else "secret"):
                with patch("subprocess.Popen") as process:
                    with self.assertRaises(CodexError):
                        self.backend().complete("prompt", "public", output_schema=schema)
                    process.assert_not_called()
        for record in self.records():
            self.assertEqual(record["failure_kind"], "invalid_output_schema")
            self.assertNotIn(self.key, json.dumps(record))

    def test_diagnosis_schema_requires_every_assigned_id_without_extra_checks(self):
        assigned = ["Q04", "Q06", "Q09"]
        schema = diagnosis_output_schema(assigned)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        result = {"assessments": {check: {"check_id": check, "state": "unknown", "reason": "No workbook", "evidence": []}
                                   for check in assigned}, "issues": [], "evidence_requests": []}
        validator.validate(result)
        del result["assessments"]["Q09"]
        with self.assertRaises(ValidationError):
            validator.validate(result)
        result["assessments"]["Q09"] = {"check_id": "Q06", "state": "unknown", "reason": "wrong ID", "evidence": []}
        with self.assertRaises(ValidationError):
            validator.validate(result)
        for invalid in [[], ["Q04", "Q04"], ["private/goal.xlsx"]]:
            with self.assertRaises(ValueError):
                diagnosis_output_schema(invalid)


if __name__ == "__main__":
    unittest.main()
