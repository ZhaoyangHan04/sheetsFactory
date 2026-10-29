"""Export genuine Harbor task directories and execute real control jobs."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import tomllib
from uuid import uuid4


def _first_existing(paths):
    for path in paths:
        if path.is_file():
            return path
    raise FileNotFoundError("Missing task artifact; searched: " + ", ".join(map(str, paths)))


def inspect_export(task_dir: str | Path) -> dict:
    """Verify an immutable export and return its control-proof version binding.

    Names come from task.toml, so staging directory names never change namespace.
    A manifest does not certify files until all recorded hashes have been checked.
    """
    task_dir = Path(task_dir)
    manifest_file = task_dir / 'export_manifest.json'
    raw = manifest_file.read_bytes()
    manifest = json.loads(raw)
    if not isinstance(manifest, dict):
        raise ValueError('Export manifest must be a JSON object')
    metadata, files = manifest.get('metadata'), manifest.get('files')
    if not isinstance(metadata, dict) or not isinstance(files, dict) or not files:
        raise ValueError('Export manifest lacks metadata or recorded files')
    for relative, expected in files.items():
        relative_path = Path(relative)
        if relative_path.is_absolute() or '..' in relative_path.parts:
            raise ValueError('Export manifest contains an unsafe file path')
        file = task_dir / relative_path
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise ValueError('Export file is missing or differs from manifest: ' + relative)
    actual = {str(file.relative_to(task_dir)) for file in task_dir.rglob('*')
              if file.is_file() and file.name != 'export_manifest.json'}
    if actual != set(files):
        raise ValueError('Export contains unrecorded or missing files')
    config = tomllib.loads((task_dir / 'task.toml').read_text())
    task_name = config.get('task', {}).get('name')
    if not isinstance(task_name, str) or not task_name:
        raise ValueError('Harbor task.toml lacks a task name')
    return {'task_id': manifest.get('task_id'), 'task_name': task_name,
            'revision': metadata.get('revision'), 'revision_hash': metadata.get('revision_hash'),
            'export_manifest_sha256': hashlib.sha256(raw).hexdigest()}


def matched_controls(proof, *, task_name=None):
    """Require explicit real rewards for both controls; absent results never pass."""
    for agent, expected in (('oracle', 1), ('nop', 0)):
        result = proof.get(agent, {}) if isinstance(proof, dict) else {}
        reward = result.get('reward')
        if (result.get('matched') is not True or type(reward) not in (int, float)
            or reward != expected or result.get('exception_info')
            or (task_name is not None and result.get('task_name') != task_name)):
            return False
    return True


def control_summary_paths(proof, task_name):
    """Locate already persisted summaries supporting an externally bound proof."""
    paths = set()
    for agent in ('oracle', 'nop'):
        result_file = (proof.get(agent) or {}).get('result_file')
        if not result_file:
            continue
        for directory in list(Path(result_file).parents)[:4]:
            candidate = directory / 'control_summary.json'
            try:
                summary = json.loads(candidate.read_text())
                if summary.get('per_task', {}).get(task_name) == proof:
                    paths.add(str(candidate))
            except (OSError, ValueError, AttributeError):
                continue
    return sorted(paths)


def export_harbor(task_dir: str | Path, export_dir: str | Path, metadata: dict | None = None,
                  project_root: str | Path | None = None) -> Path:
    task_dir, export_dir = Path(task_dir), Path(export_dir)
    metadata = metadata or {}
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[3]
    public = task_dir / "public"
    private = task_dir / "private"
    input_file = _first_existing([public / "input.xlsx", task_dir / "input.xlsx"])
    goal_file = _first_existing([private / "goal.xlsx", private / "reference.xlsx", task_dir / "goal.xlsx"])
    instruction_file = _first_existing([public / "instruction.md", task_dir / "instruction.md"])
    for folder in ("environment", "solution", "tests"):
        (export_dir / folder).mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_file, export_dir / "environment/input.xlsx")
    shutil.copy2(input_file, export_dir / "tests/original_input.xlsx")
    shutil.copy2(goal_file, export_dir / "solution/reference.xlsx")
    shutil.copy2(goal_file, export_dir / "tests/reference.xlsx")
    shutil.copy2(Path(__file__).with_name("standalone_verifier.py"), export_dir / "tests/verify.py")
    instruction = instruction_file.read_text()
    if "/app/output.xlsx" not in instruction:
        instruction += "\n\nRead `/app/input.xlsx` and save the completed workbook to `/app/output.xlsx`.\n"
    (export_dir / "instruction.md").write_text(instruction)
    base_image = metadata.get("base_image", "sheetsfactory-lo:24.2")
    if not re.fullmatch(r"[A-Za-z0-9_./:@-]+", base_image):
        raise ValueError("Invalid base image name")
    (export_dir / "environment/Dockerfile").write_text(
        f"FROM {base_image}\nUSER root\nENTRYPOINT []\nWORKDIR /app\n"
        "COPY input.xlsx /app/input.xlsx\n"
        "COPY --chmod=755 recalculate /usr/local/bin/recalculate\n"
    )
    (export_dir / "environment/recalculate").write_text(
        '#!/bin/sh\nexec /usr/bin/python3 /opt/uno_recalculate.py "$@"\n')
    (export_dir / "tests/Dockerfile").write_text(
        f"FROM {base_image}\nUSER root\nENTRYPOINT []\nWORKDIR /app\nCOPY . /tests/\n"
    )
    (export_dir / "solution/solve.sh").write_text(
        "#!/bin/sh\nset -eu\ncp /solution/reference.xlsx /app/output.xlsx\n"
    )
    (export_dir / "tests/test.sh").write_text(
        "#!/bin/sh\nset -eu\nmkdir -p /logs/verifier\n"
        "/usr/bin/python3 /tests/verify.py --input /tests/original_input.xlsx "
        "--goal /tests/reference.xlsx --output /app/output.xlsx "
        "--reward /logs/verifier/reward.txt --report /logs/verifier/diagnostics.json\n"
    )
    (export_dir / "solution/solve.sh").chmod(0o755)
    (export_dir / "tests/test.sh").chmod(0o755)
    task_id = re.sub(r"[^a-zA-Z0-9._-]", "-", metadata.get("task_id", task_dir.name))
    mode = metadata.get("mode", "spreadsheet")
    task_toml = (
        'schema_version = "1.3"\nartifacts = ["/app/output.xlsx"]\n\n'
        '[task]\n' + f'name = {json.dumps("sheetsfactory/" + task_id)}\n'
        'authors = [{ name = "ZhaoyangHan04", email = "3319926404@qq.com" }]\n\n'
        '[metadata]\ncategory = "spreadsheet"\n' + f'mode = {json.dumps(mode)}\n'
        'difficulty_status = "deferred"\n\n'
        '[agent]\ntimeout_sec = 1800.0\n\n'
        '[verifier]\ntimeout_sec = 600.0\nenvironment_mode = "separate"\n\n'
        '[environment]\ncpus = 1\nmemory_mb = 2048\nstorage_mb = 2048\n\n'
        '[verifier.environment]\ncpus = 1\nmemory_mb = 2048\nstorage_mb = 2048\n'
    )
    (export_dir / "task.toml").write_text(task_toml)
    manifest = {"task_id": task_id, "metadata": metadata, "files": {}}
    for path in sorted(export_dir.rglob("*")):
        if path.is_file() and path.name != "export_manifest.json":
            manifest["files"][str(path.relative_to(export_dir))] = hashlib.sha256(path.read_bytes()).hexdigest()
    (export_dir / "export_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return export_dir


def run_controls(export_root: str | Path, output_dir: str | Path | None = None,
                 harbor_executable: str | Path | None = None, concurrency: int = 2,
                 timeout_seconds: int = 7200, event_callback=None) -> dict:
    """Run actual Harbor oracle and nop. No local fallback or synthesized rewards."""
    export_root = Path(export_root).resolve()
    output_dir = Path(output_dir).resolve() if output_dir else export_root.parent / "harbor_control_jobs"
    output_dir.mkdir(parents=True, exist_ok=True)
    harbor = str(harbor_executable or Path(sys.executable).with_name("harbor"))
    control_id = uuid4().hex[:12]
    started = time.monotonic()
    results = {"control_run_id": control_id, "export_root": str(export_root), "agents": {}, "per_task": {}, "complete": False}
    for agent, expected in (("oracle", 1), ("nop", 0)):
        # Never read old trials after a failed command on an existing job name.
        job_name = f"{agent}-controls-{control_id}"
        command = [harbor, "run", "--path", str(export_root), "--agent", agent,
                   "--jobs-dir", str(output_dir), "--job-name", job_name,
                   "--n-concurrent", str(concurrency)]
        if event_callback:
            event_callback({"type": "harbor.control.started", "agent": agent, "command": command})
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds)
        (output_dir / f"{job_name}.stdout.log").write_text(completed.stdout)
        (output_dir / f"{job_name}.stderr.log").write_text(completed.stderr)
        job_dir = output_dir / job_name
        trials = []
        for result_file in job_dir.rglob("result.json"):
            try:
                record = json.loads(result_file.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            # Trial results contain task_name; aggregate job results do not.
            task_name = record.get("task_name")
            if not task_name:
                continue
            rewards = (record.get("verifier_result") or {}).get("rewards")
            actual = rewards.get("reward") if isinstance(rewards, dict) else None
            if actual is None and isinstance(rewards, dict) and len(rewards) == 1:
                actual = next(iter(rewards.values()))
            entry = {"task_name": task_name, "reward": actual, "expected": expected,
                     "matched": actual == expected and not record.get("exception_info"),
                     "result_file": str(result_file), "exception_info": record.get("exception_info")}
            trials.append(entry)
            results["per_task"].setdefault(task_name, {})[agent] = entry
            if event_callback:
                event_callback({"type": "harbor.control.task", "agent": agent, **entry})
        results["agents"][agent] = {"command": command, "returncode": completed.returncode,
                                    "trial_count": len(trials), "trials": trials}
    expected_count = 1 if (export_root / "task.toml").is_file() else sum(
        1 for path in export_root.iterdir() if path.is_dir() and (path / "task.toml").is_file())
    results["expected_task_count"] = expected_count
    results["complete"] = bool(expected_count) and len(results["per_task"]) == expected_count and all(
        set(values) == {"oracle", "nop"} and all(item["matched"] for item in values.values())
        for values in results["per_task"].values())
    results["duration_seconds"] = time.monotonic() - started
    (output_dir / "control_summary.json").write_text(json.dumps(results, indent=2) + "\n")
    return results
