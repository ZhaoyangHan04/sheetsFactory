#!/usr/bin/env python3
"""Build a new, evidence-bound Harbor release without changing its source run.

This command does not run models, controls, or spreadsheet recalculation. It
checks the persisted results and already-recalculated recovery workbook again.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import sys
import tarfile
from uuid import uuid4
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sheets_factory.evaluation.harbor import inspect_export, matched_controls, control_summary_paths
from sheets_factory.reporting import generate_report, read_run
from sheets_factory.workbook.compare import compare_workbooks


MODES = ('financial_modeling', 'debugging')
EXPORT_FILES = frozenset({
    'instruction.md', 'task.toml', 'export_manifest.json',
    'environment/Dockerfile', 'environment/input.xlsx', 'environment/recalculate',
    'solution/solve.sh', 'solution/reference.xlsx', 'tests/Dockerfile',
    'tests/original_input.xlsx', 'tests/reference.xlsx', 'tests/verify.py', 'tests/test.sh',
})
RUNTIME_FILES = frozenset({'Dockerfile', 'uno_recalculate.py'})


class ReleaseError(ValueError):
    """A release prerequisite is missing or changed; no release is published."""


def _require(condition, message):
    if not condition:
        raise ReleaseError(message)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _file(path, within, tracked):
    path, within = Path(path).absolute(), Path(within).resolve()
    _require(path.is_relative_to(within), 'Evidence path is outside its permitted directory')
    _require(not any(part.is_symlink() for part in [path, *path.parents]
                     if part.is_relative_to(within)), 'Symlinks are not permitted in release evidence')
    _require(path.resolve().is_relative_to(within) and path.is_file(),
             'Required release evidence file is missing')
    raw = path.read_bytes()
    digest = _sha(raw)
    previous = tracked.setdefault(str(path), digest)
    _require(previous == digest, 'Evidence changed during validation')
    return raw


def _json(path, within, tracked):
    value = json.loads(_file(path, within, tracked))
    _require(isinstance(value, dict), 'Evidence must be a JSON object')
    return value


def _receipt(path, tracked):
    path = str(Path(path).absolute())
    return {'path': path, 'sha256': tracked[path]}


def select_diverse(tasks, per_mode):
    """Round-robin sorted source groups, with stable variants inside each group."""
    _require(type(per_mode) is int and per_mode > 0, '--per-mode must be a positive integer')
    selected = []
    for mode in MODES:
        groups = defaultdict(list)
        for task in tasks:
            if task.get('mode') == mode:
                _require(bool(task.get('source_id')), 'A selected task lacks a source ID')
                groups[task['source_id']].append(task)
        count = sum(map(len, groups.values()))
        _require(count >= per_mode,
                 f'Insufficient verified {mode} tasks: need {per_mode}, found {count}; no release created')
        for group in groups.values():
            group.sort(key=lambda task: (task.get('variant', 0), task.get('revision', 0), task['id']))
        ordered = [task for index in range(max(map(len, groups.values())))
                   for source in sorted(groups) if index < len(groups[source])
                   for task in [groups[source][index]]]
        selected.extend(ordered[:per_mode])
    return selected


def _check_payload(export, within, tracked, secret_values=()):
    _require(not export.is_symlink() and export.is_dir(), 'Missing Harbor export')
    entries = list(export.rglob('*'))
    _require(not any(path.is_symlink() for path in entries), 'Symlink in Harbor export')
    files = {str(path.relative_to(export)) for path in entries if path.is_file()}
    directories = {str(path.relative_to(export)) for path in entries if path.is_dir()}
    _require(files == EXPORT_FILES and directories == {'environment', 'solution', 'tests'},
             'Unexpected or missing Harbor release files')
    for relative in sorted(files):
        raw = _file(export / relative, within, tracked)
        _require(not any(secret in raw for secret in secret_values), 'Credential found in release payload')
        if relative.endswith('.xlsx'):
            with zipfile.ZipFile(export / relative) as workbook:
                for member in workbook.infolist():
                    _require(not any(secret in workbook.read(member) for secret in secret_values),
                             'Credential found in workbook payload')
    return inspect_export(export)


def _copy_payload(source, target):
    """Copy only the fixed export contract, never newly appeared siblings."""
    target.mkdir(parents=True)
    for relative in sorted(EXPORT_FILES):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, destination)


def _runtime_copy_sources(dockerfile):
    """Require every build-context COPY source to be an explicit allowed file."""
    text = dockerfile.decode().replace('\\\n', ' ')
    sources = set()
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if not parts or parts[0].startswith('#'):
            continue
        instruction = parts[0].upper()
        _require(instruction != 'ADD', 'Runtime recipe ADD is outside the release allowlist')
        if instruction != 'COPY':
            continue
        _require(len(parts) == 2, 'Runtime recipe COPY lacks source files')
        arguments = parts[1].strip()
        if arguments.startswith('['):
            operands = json.loads(arguments)
            _require(isinstance(operands, list) and all(isinstance(item, str) for item in operands),
                     'Invalid runtime COPY JSON syntax')
        else:
            operands = shlex.split(arguments)
            while operands and operands[0].startswith('--'):
                option = operands.pop(0)
                _require(option.startswith(('--chmod=', '--chown=')),
                         'Unsupported runtime COPY option')
        _require(len(operands) >= 2, 'Runtime COPY must have sources and destination')
        for source in operands[:-1]:
            _require(source in RUNTIME_FILES - {'Dockerfile'}, 'Runtime COPY source is outside the allowlist')
            sources.add(source)
    _require(sources == RUNTIME_FILES - {'Dockerfile'}, 'Runtime recipe COPY sources are incomplete')
    return sources


def _prepare_runtime(root, run_dir, tasks, tracked, secret_values):
    """Read a minimal recipe and original run engine evidence, without Docker."""
    recipe_dir = root / 'src/sheets_factory/workbook'
    recipe_files = {name: _file(recipe_dir / name, recipe_dir, tracked) for name in sorted(RUNTIME_FILES)}
    _runtime_copy_sources(recipe_files['Dockerfile'])
    recorded = defaultdict(list)
    for task in tasks:
        diagnosis_path = Path(task['diagnosis']['path'])
        diagnosis = _json(diagnosis_path, run_dir, {})
        engines = [entry.get('engine') for entry in
                   (diagnosis.get('assessments', {}).get('Q10', {}).get('evidence') or [])
                   if isinstance(entry, dict) and isinstance(entry.get('engine'), dict)]
        _require(bool(engines), 'Task diagnosis lacks recorded LibreOffice runtime evidence')
        for engine in engines:
            image, image_id, version = engine.get('image'), engine.get('image_id'), engine.get('version')
            _require(engine.get('backend') == 'libreoffice_uno_docker'
                     and isinstance(image, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:-]*', image)
                     and isinstance(image_id, str) and re.fullmatch(r'sha256:[a-f0-9]{64}', image_id)
                     and isinstance(version, str) and version.startswith('LibreOffice '),
                     'Task diagnosis has incomplete LibreOffice runtime evidence')
            for relative in ('environment/Dockerfile', 'tests/Dockerfile'):
                first_line = (run_dir / 'SpreadsheetEval' / task['task_id'] / relative).read_text().splitlines()[0]
                _require(first_line == 'FROM ' + image, 'Task base image differs from recorded runtime')
            recorded[(image, image_id, version)].append(task['task_id'])
    tags = {identity[0] for identity in recorded}
    _require(len(tags) == 1, 'One release runtime recipe cannot serve multiple base-image tags')
    tag = next(iter(tags))
    metadata = {
        'image_tag': tag,
        'recorded_run_images': [
            {'image': image, 'image_id': image_id, 'libreoffice_version': version,
             'task_ids': sorted(set(ids)), 'evidence': 'persisted task diagnosis assessments.Q10.evidence.engine'}
            for (image, image_id, version), ids in sorted(recorded.items())],
        'recipe_files': {f'runtime/{name}': {'sha256': _sha(data), 'source': str(recipe_dir / name)}
                         for name, data in recipe_files.items()},
        'recipe_provenance': 'Packaging checkout; original image identity comes separately from run evidence.',
        'build_command': f'docker build --network host -t {tag} runtime',
        'image_archive_included': False,
        'bit_identical_rebuild_guaranteed': False,
        'rebuild_note': 'Pinned Ubuntu base and LibreOffice packages; apt dependencies and repository availability '
                        'can change. Rebuilding does not guarantee the recorded image ID.',
    }
    prepare = ('#!/bin/sh\nset -eu\n'
               'release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
               f'docker build --network host -t {shlex.quote(tag)} "$release_dir/runtime"\n').encode()
    identities = '\n'.join(f"- `{entry['image_id']}` — {entry['libreoffice_version']}"
                           for entry in metadata['recorded_run_images'])
    readme = f'''# SpreadsheetEval release

本包包含 {len(tasks)} 道已通过原运行质量检查及 oracle/nop 控制的任务。任务目录与验证时一致；难度门禁仍处于延后阶段。

在解压后的本目录运行以下命令。需要可用的 Docker 和已安装的 Harbor CLI；首次构建需要网络下载 Ubuntu/apt 软件包。

```bash
./prepare_runtime.sh
harbor run --path SpreadsheetEval --agent oracle
harbor run --path SpreadsheetEval --agent nop
```

准备脚本执行 `docker build --network host -t {tag} runtime`。它可以从任何工作目录调用，构建上下文仅含白名单文件。oracle 预期 reward=1，nop 预期 reward=0；命令会在本机重新执行控制。

原运行记录的运行时镜像与 LibreOffice 版本：

{identities}

`release_manifest.json` 的 `runtime` 字段记录原运行镜像、诊断证据来源和每个构建文件的 SHA256。本包默认只提供 recipe，不包含大型镜像归档。Ubuntu 基础镜像已固定 digest，LibreOffice 包已固定版本；apt 间接依赖和仓库可用性可能变化，重新构建不保证与原运行相同的 image ID。如需字节级一致的环境，应另行取得原镜像归档。

`SpreadsheetEval/` 仅包含选中的 Harbor 任务；`solution/` 和 `tests/` 的 reference.xlsx 是必要评测内容。私有诊断、恢复记录和请求日志没有打包；清单仅记录其原证据路径与 SHA256。
'''.encode()
    payload = {**{f'runtime/{name}': data for name, data in recipe_files.items()},
               'prepare_runtime.sh': prepare, 'README.md': readme}
    _require(not any(secret in data for secret in secret_values for data in payload.values()),
             'Credential found in runtime release payload')
    return payload, metadata


def _validate_task(run_dir, task, tracked, secret_values=()):
    task_id = task['id']
    _require(isinstance(task_id, str) and re.fullmatch(r'[A-Za-z0-9._-]+', task_id)
             and task_id not in {'.', '..'}, 'Unsafe task ID')
    revision = task.get('revision', 0)
    _require(type(revision) is int and revision >= 0, 'Invalid task revision')
    base = run_dir / 'tasks' / task_id / 'revisions' / f'{revision:03d}'
    export = run_dir / 'SpreadsheetEval' / task_id
    binding = _check_payload(export, run_dir, tracked, secret_values)
    metadata = _json(export / 'export_manifest.json', run_dir, tracked)['metadata']
    _require(metadata.get('mode') == task.get('mode') and metadata.get('source_id') == task.get('source_id'),
             f'{task_id}: export mode or source differs from audit')
    _require(binding == task.get('harbor_export_binding'), f'{task_id}: Harbor proof binding differs')
    _require(binding['task_id'] == task_id and binding['revision'] == revision
             and bool(binding['revision_hash']), f'{task_id}: Harbor revision does not match current task')
    proof = task.get('harbor_controls')
    _require(matched_controls(proof, task_name=binding['task_name']), f'{task_id}: controls are not matched')
    controls = {}
    for agent, expected in (('oracle', 1), ('nop', 0)):
        result_path = Path(proof[agent].get('result_file', ''))
        actual = _json(result_path, run_dir, tracked)
        rewards = (actual.get('verifier_result') or {}).get('rewards')
        reward = rewards.get('reward') if isinstance(rewards, dict) else None
        if reward is None and isinstance(rewards, dict) and len(rewards) == 1:
            reward = next(iter(rewards.values()))
        _require(actual.get('task_name') == binding['task_name']
                 and type(reward) in (int, float) and reward == expected
                 and not actual.get('exception_info'), f'{task_id}: actual {agent} result does not pass')
        actual_config = actual.get('config') or {}
        _require((actual_config.get('agent') or {}).get('name') == agent
                 and (actual.get('agent_info') or {}).get('name') == agent,
                 f'{task_id}: actual control agent differs')
        staged_path = (actual_config.get('task') or {}).get('path')
        _require(isinstance(staged_path, str) and Path(staged_path).is_absolute(),
                 f'{task_id}: actual control lacks its task path')
        staged = Path(staged_path)
        _require((actual.get('task_id') or {}).get('path') == staged_path,
                 f'{task_id}: actual control task identity differs')
        _require(_check_payload(staged, run_dir, tracked, secret_values) == binding,
                 f'{task_id}: actual control used a different exported revision')
        # Harbor's persisted task_checksum is its SHA256 dirhash. With our exact
        # file allowlist no .harborignore filtering applies. Bind the historical
        # result to the bytes it actually used, not only its reusable task name.
        try:
            from dirhash import dirhash
        except ImportError as error:
            raise ReleaseError('Harbor dirhash dependency is required to verify control checksums') from error
        _require(actual.get('task_checksum') == dirhash(staged, 'sha256'),
                 f'{task_id}: actual control task checksum differs')
        batch_receipts = []
        for ancestor in staged.parents:
            if ancestor == run_dir:
                break
            batch_path = ancestor / 'batch_manifest.json'
            if batch_path.is_file():
                batch = _json(batch_path, run_dir, tracked)
                # Individual tasks can qualify before their batch receipt is
                # final. Do not freeze a receipt that the runner still updates.
                _require(bool(batch.get('finished_at')),
                         f'{task_id}: batch manifest is not finalized')
                _require((batch.get('export_bindings') or {}).get(binding['task_name']) == binding,
                         f'{task_id}: batch manifest binding differs')
                batch_receipts.append(_receipt(batch_path, tracked))
        controls[agent] = {**_receipt(result_path, tracked), 'reward': reward,
                           'agent': agent, 'task_checksum': actual['task_checksum'],
                           'staged_task_directory': str(staged), 'batch_manifests': batch_receipts}
    summaries = []
    for path in control_summary_paths(proof, binding['task_name']):
        summary = _json(path, run_dir, tracked)
        export_root = summary.get('export_root')
        _require(isinstance(export_root, str) and Path(export_root).is_absolute()
                 and all(Path(entry['staged_task_directory']) in {Path(export_root), Path(export_root) / task_id}
                         for entry in controls.values()),
                 f'{task_id}: actual control summary export path differs')
        summaries.append(_receipt(path, tracked))
    _require(bool(summaries), f'{task_id}: missing matching persisted control summary')

    public_input = base / 'public/input.xlsx'
    instruction_path = base / 'public/instruction.md'
    original = _file(public_input, base, tracked)
    instruction_raw = _file(instruction_path, base, tracked)
    instruction = instruction_raw.decode()
    revision_hash = _sha(original + instruction.encode())
    _require(revision_hash == binding['revision_hash'], f'{task_id}: public revision hash differs')
    if task.get('revision_hash'):
        _require(task['revision_hash'] == revision_hash, f'{task_id}: audit revision hash differs')
    expected_instruction = instruction if '/app/output.xlsx' in instruction else (
        instruction + '\n\nRead `/app/input.xlsx` and save the completed workbook to `/app/output.xlsx`.\n')
    _require(_file(export / 'instruction.md', run_dir, tracked).decode() == expected_instruction,
             f'{task_id}: exported instruction differs from current revision')
    for relative in ('environment/input.xlsx', 'tests/original_input.xlsx'):
        _require(_file(export / relative, run_dir, tracked) == original,
                 f'{task_id}: exported input differs from current revision')
    goal_path = base / 'private/goal.xlsx'
    goal = _file(goal_path, base, tracked)
    for relative in ('solution/reference.xlsx', 'tests/reference.xlsx'):
        _require(_file(export / relative, run_dir, tracked) == goal,
                 f'{task_id}: exported goal differs from current revision')

    diagnosis_path = base / 'private/diagnosis.json'
    diagnosis = _json(diagnosis_path, base, tracked)
    enabled = diagnosis.get('enabled_check_ids')
    coverage = diagnosis.get('coverage') or {}
    _require(diagnosis.get('releasable') is True and diagnosis.get('task_revision_hash') == revision_hash
             and bool(diagnosis.get('diagnostic_run_id')) and bool(diagnosis.get('check_plan_hash'))
             and isinstance(enabled, list) and bool(enabled)
             and all((diagnosis.get('assessments', {}).get(check) or {}).get('state')
                     in {'clear', 'flagged', 'not_applicable'} for check in enabled)
             and not any(coverage.get(key) for key in (
                 'blocking_issue_ids', 'unknown_check_ids', 'undispositioned_warning_ids')),
             f'{task_id}: latest diagnosis is missing, stale, or not releasable')
    recovery_path = base / 'private/independent_recovery.json'
    recovery = _json(recovery_path, base, tracked)
    compiler = recovery.get('compiler') or {}
    replay = recovery.get('replay') or {}
    _require(recovery.get('verified') is True and recovery.get('public_information_only') is True
             and replay.get('returncode') == 0 and (recovery.get('comparison') or {}).get('reward') == 1
             and not compiler.get('assumptions_added') and not compiler.get('unresolved_questions'),
             f'{task_id}: independent recovery did not pass')
    if recovery.get('task_revision_hash'):
        _require(recovery['task_revision_hash'] == revision_hash, f'{task_id}: stale recovery revision hash')
    # Older records lack a revision hash. Bind the actual replay inputs, public
    # instruction and program to this revision instead of trusting verified=true.
    workspace = Path(recovery.get('workspace', ''))
    replay_dir = Path(replay.get('directory', ''))
    _require(_file(workspace / 'input.xlsx', base, tracked) == original
             and _file(workspace / 'instruction.md', base, tracked) == instruction_raw
             and _file(replay_dir / 'input.xlsx', base, tracked) == original,
             f'{task_id}: recovery used a different public revision')
    program = recovery.get('program')
    _require(isinstance(program, str) and bool(program) and compiler.get('code') == program
             and _file(workspace / 'recovery.py', base, tracked).decode() == program
             and _file(replay_dir / 'recovery.py', base, tracked).decode() == program,
             f'{task_id}: recovery program binding differs')
    recovered_path = base / 'private/recovered.xlsx'
    _file(recovered_path, base, tracked)
    replay_output = replay_dir / 'output.xlsx'
    _file(replay_output, base, tracked)
    _require(zipfile.is_zipfile(replay_output), f'{task_id}: replay output is not an XLSX workbook')
    for key, path in (('replay_output_sha256', replay_output), ('recovered_sha256', recovered_path)):
        if recovery.get(key):
            _require(recovery[key] == tracked[str(path.absolute())], f'{task_id}: recorded recovery output hash differs')
    comparison = compare_workbooks(public_input, goal_path, recovered_path)
    _require(comparison.get('reward') == 1, f'{task_id}: current recovery workbook does not match goal')
    diagnostic_ids = {diagnosis['diagnostic_run_id']}
    diagnostic_ids.update(batch['origin_diagnostic_run_id'] for batch in diagnosis.get('llm_batches', [])
                          if isinstance(batch, dict) and batch.get('cache_hit') is True
                          and isinstance(batch.get('origin_diagnostic_run_id'), str))
    reviewed_recovery = []
    for evidence_path in sorted(base.glob('diagnostic_private-*/evidence.json')):
        candidate_files = {}
        try:
            evidence = _json(evidence_path, base, candidate_files)
        except (OSError, ValueError):
            continue
        if (evidence.get('visibility') != 'review'
                or evidence.get('diagnostic_run_id') not in diagnostic_ids
                or evidence.get('task_revision_hash') != revision_hash
                or evidence.get('check_plan_hash') != diagnosis['check_plan_hash']):
            continue
        _require((evidence.get('private') or {}).get('independent_recovery') == recovery,
                 f'{task_id}: latest diagnosis reviewed different recovery evidence')
        _require(_file(evidence_path.parent / 'input.xlsx', base, candidate_files) == original
                 and _file(evidence_path.parent / 'instruction.md', base, candidate_files) == instruction_raw,
                 f'{task_id}: diagnostic evidence used a different public revision')
        tracked.update(candidate_files)
        reviewed_recovery.append(_receipt(evidence_path, tracked))
    _require(bool(reviewed_recovery), f'{task_id}: missing diagnosis evidence for current recovery')
    return {
        'task_id': task_id, 'task_name': binding['task_name'], 'mode': task['mode'],
        'source_id': task['source_id'], 'source_file': task.get('source'),
        'variant': task.get('variant', 0), 'revision': revision, 'revision_hash': revision_hash,
        'harbor_export_binding': binding,
        'controls': controls, 'control_summaries': summaries,
        'diagnosis': {**_receipt(diagnosis_path, tracked),
                      'diagnostic_run_id': diagnosis['diagnostic_run_id'],
                      'check_plan_hash': diagnosis['check_plan_hash'],
                      'enabled_check_ids': enabled, 'reviewed_recovery_evidence': reviewed_recovery},
        'independent_recovery': {**_receipt(recovery_path, tracked),
            'recovered_workbook': _receipt(recovered_path, tracked),
            'public_input': _receipt(workspace / 'input.xlsx', tracked),
            'public_instruction': _receipt(workspace / 'instruction.md', tracked),
            'replay_input': _receipt(replay_dir / 'input.xlsx', tracked),
            'replay_program': _receipt(replay_dir / 'recovery.py', tracked),
            'replay_output': _receipt(replay_output, tracked),
            'execution_evidence': 'Persisted successful replay record and artifacts; release does not rerun code.',
            'current_value_comparison_reward': comparison['reward']},
        'payload_files': {relative: tracked[str((export / relative).absolute())] for relative in sorted(EXPORT_FILES)},
    }


def package_release(run_dir, per_mode=10, output_dir=None, *, project_root=None):
    root = Path(project_root or Path(__file__).resolve().parents[1]).resolve()
    run_dir = Path(run_dir).resolve()
    snapshot = read_run(run_dir)
    report = generate_report(run_dir, project_root=root)
    verified = {task['task_id'] for task in report['tasks'] if task.get('verified_qualified') is True}
    candidates = [task for task in snapshot['tasks'] if task.get('status') == 'qualified'
                  and task['id'] in verified]
    selected = select_diverse(candidates, per_mode)
    run_id = snapshot['run'].get('id') or run_dir.name
    _require(isinstance(run_id, str), 'Run ID must be a string')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination = Path(output_dir).absolute() if output_dir else (
        root / 'outputs/releases' / f'{run_dir.name}-{per_mode}x2-{stamp}-{uuid4().hex[:8]}')
    _require(not destination.exists() and not destination.is_symlink(), 'Release output already exists')
    _require(not destination.resolve().is_relative_to(run_dir), 'Release output must be outside the source run')
    tracked = {}
    key_file = root / '.secrets/api_key'
    secrets = [key_file.read_bytes().strip()] if key_file.is_file() else []
    secrets = [secret for secret in secrets if len(secret) >= 12]
    validated = [_validate_task(run_dir, task, tracked, secrets) for task in selected]
    runtime_tracked = {}
    runtime_payload, runtime_metadata = _prepare_runtime(root, run_dir, validated, runtime_tracked, secrets)
    manifest = {
        'schema_version': 1, 'run_id': run_id, 'source_run_directory': str(run_dir),
        'created_at': datetime.now(timezone.utc).isoformat(),
        'release_id': destination.name,
        'selection_policy': 'stable_source_round_robin_then_variant_revision_task_id',
        'requested_per_mode': per_mode, 'task_count': len(validated),
        'counts_by_mode': {mode: sum(task['mode'] == mode for task in validated) for mode in MODES},
        'selected_task_ids': [task['task_id'] for task in validated], 'tasks': validated,
        'runtime': runtime_metadata,
        'release_support_files': {name: _sha(data) for name, data in sorted(runtime_payload.items())},
        'run_snapshot': {'status': snapshot['run'].get('status'),
            'yield': report['yield'], 'sources': report['sources'],
            'difficulty_status': report['run'].get('difficulty_status', 'deferred')},
        'evidence_policy': 'Proof paths and SHA256 only; private evidence and request logs are not packaged.',
    }
    # Only a new sibling staging directory is mutated. Failed checks leave no
    # published release; existing releases and the source run remain untouched.
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.parent / f'.{destination.name}.partial-{uuid4().hex}'
    stage.mkdir(mode=0o700)
    try:
        for task in validated:
            target = stage / 'SpreadsheetEval' / task['task_id']
            _copy_payload(run_dir / 'SpreadsheetEval' / task['task_id'], target)
            _require(_check_payload(target, stage, {}, secrets) == task['harbor_export_binding'],
                     'Copied Harbor export differs')
        for relative, data in runtime_payload.items():
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (stage / 'prepare_runtime.sh').chmod(0o755)
        manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
        _require(not any(secret in manifest_bytes for secret in secrets), 'Credential found in release metadata')
        (stage / 'release_manifest.json').write_bytes(manifest_bytes)
        archive = stage / 'SpreadsheetEval.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            tar.add(stage / 'SpreadsheetEval', arcname='SpreadsheetEval')
            tar.add(stage / 'release_manifest.json', arcname='release_manifest.json')
            tar.add(stage / 'runtime', arcname='runtime')
            tar.add(stage / 'prepare_runtime.sh', arcname='prepare_runtime.sh')
            tar.add(stage / 'README.md', arcname='README.md')
        digest = _sha(archive.read_bytes())
        (stage / 'SpreadsheetEval.tar.gz.sha256').write_text(f'{digest}  SpreadsheetEval.tar.gz\n')
        for path, expected in tracked.items():
            _require(_sha(_file(path, run_dir, {})) == expected, 'Source evidence changed during packaging')
        for path, expected in runtime_tracked.items():
            _require(_sha(_file(path, root / 'src/sheets_factory/workbook', {})) == expected,
                     'Runtime recipe changed during packaging')
        for task in validated:
            _require(_check_payload(run_dir / 'SpreadsheetEval' / task['task_id'], run_dir, {}, secrets)
                     == task['harbor_export_binding'], 'Source export changed during packaging')
            for proof in task['controls'].values():
                from dirhash import dirhash
                staged = Path(proof['staged_task_directory'])
                _require(_check_payload(staged, run_dir, {}, secrets) == task['harbor_export_binding']
                         and dirhash(staged, 'sha256') == proof['task_checksum'],
                         'Control staging changed during packaging')
        latest = {task['id']: task for task in read_run(run_dir)['tasks']}
        _require(all(latest.get(task['id']) == task for task in selected),
                 'Selected task audit changed during packaging; retry with a fresh snapshot')
        # Atomic no-clobber publication on Linux: renameat2 RENAME_NOREPLACE.
        # mkdir + rename could overwrite an empty destination created in between.
        import ctypes
        import errno
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, 'renameat2', None)
        _require(renameat2 is not None, 'Atomic no-overwrite publication is unavailable')
        result = renameat2(-100, bytes(stage), -100, bytes(destination), 1)
        if result != 0:
            error = ctypes.get_errno()
            if error == errno.EEXIST:
                raise ReleaseError('Release output already exists')
            raise OSError(error, 'Release publication failed')
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {'release_directory': str(destination),
            'task_directory': str(destination / 'SpreadsheetEval'),
            'manifest': str(destination / 'release_manifest.json'),
            'archive': str(destination / 'SpreadsheetEval.tar.gz'),
            'sha256_file': str(destination / 'SpreadsheetEval.tar.gz.sha256'),
            'sha256': digest, 'task_count': len(validated), 'counts_by_mode': manifest['counts_by_mode']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path, dest='run_dir')
    parser.add_argument('--per-mode', type=int, default=10)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args(argv)
    try:
        result = package_release(args.run_dir, args.per_mode, args.output_dir)
    except (ReleaseError, OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        # No raw document contents, credentials or provider responses go to stdout.
        print(json.dumps({'error': 'release_refused', 'reason': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
