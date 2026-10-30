"""Opt-in large-workbook Harbor export; the ordinary exporter is unchanged."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tomllib

from . import harbor, resource_streaming_verifier, streaming_verifier
from ..workbook import resource_engine
from ..workbook.resource_engine import DEFAULT_PROFILE, load_runtime_profile

UPSTREAM_HARBOR_SHA256 = '3166295f3af521031b078535465c65b9351b812357c24eea5880b72c88022d33'
RESOURCE_ENGINE_SHA256 = 'cc4fb863740a0fc403a5947a52fa1c2e644b81b75c358e2a3cbf47e7d33a9c8d'
UNO_SHA256 = 'c6b854c4705d12a9d7d1ec36575f0634e50c93290bd62c40634cc826ee41fc41'
RESOURCE_FIELD = 'resource_runtime'


def _reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'bytes': path.stat().st_size}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _upstream():
    for module, digest in ((harbor, UPSTREAM_HARBOR_SHA256), (resource_engine, RESOURCE_ENGINE_SHA256),
                           (streaming_verifier, resource_streaming_verifier.CORE_SHA256)):
        _require(_reference(module.__file__)['sha256'] == digest, 'A bound export/runtime dependency changed')
    uno = Path(resource_engine.__file__).with_name('uno_recalculate.py')
    _require(_reference(uno)['sha256'] == UNO_SHA256, 'The bound UNO calculation changed')
    return {'exporter': _reference(__file__), 'verifier_wrapper': _reference(resource_streaming_verifier.__file__),
            'streaming_comparison': _reference(streaming_verifier.__file__),
            'original_harbor': _reference(harbor.__file__), 'resource_engine': _reference(resource_engine.__file__),
            'uno_recalculate': _reference(uno)}


def _file(task, candidates):
    for relative in candidates:
        candidate = task / relative
        if candidate.is_file():
            _require(not candidate.is_symlink() and candidate.resolve().is_relative_to(task),
                     'Task artifacts must be real files inside their task')
            return candidate
    raise FileNotFoundError('Missing task artifact: ' + ', '.join(candidates))


def _toml(task_id, metadata, profile):
    memory_mb = profile['docker_resources']['agent']['memory_bytes'] // 1024**2
    return (
        'schema_version = "1.3"\nartifacts = ["/app/output.xlsx"]\n\n'
        '[task]\n' + f'name = {json.dumps("sheetsfactory/" + task_id)}\n'
        'authors = [{ name = "ZhaoyangHan04", email = "3319926404@qq.com" }]\n\n'
        '[metadata]\ncategory = "spreadsheet"\n' + f'mode = {json.dumps(metadata.get("mode", "spreadsheet"))}\n'
        + f'difficulty_status = {json.dumps(metadata.get("difficulty_status", "deferred"))}\n\n'
        '[agent]\ntimeout_sec = 14400.0\n\n'
        '[verifier]\ntimeout_sec = 2400.0\nenvironment_mode = "separate"\n\n'
        '[environment]\ncpus = 2\n' + f'memory_mb = {memory_mb}\n'
        'storage_mb = 2048\nnetwork_mode = "no-network"\n\n'
        '[verifier.environment]\ncpus = 2\n' + f'memory_mb = {memory_mb}\n'
        'storage_mb = 2048\nnetwork_mode = "no-network"\n')


def verify_local_base_image(runtime_profile=DEFAULT_PROFILE):
    """Inspect the actual local tag before building; never pull or substitute."""
    profile = load_runtime_profile(runtime_profile)
    command = ['docker', 'image', 'inspect', profile['image']['tag'], '--format', '{{.Id}}']
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    _require(result.returncode == 0 and result.stdout.strip() == profile['image']['id'],
             'The local Dockerfile base tag must resolve to the exact approved image ID')
    return {'kind': 'actual_local_resource_base_image_binding', 'version': 1,
            'command': command, 'base_reference': profile['image']['tag'],
            'expected_image_id': profile['image']['id'], 'actual_image_id': result.stdout.strip(),
            'actual_local_image_verified': True, 'actual_container_resources_verified': False,
            'quality_or_difficulty_certified': False}


def export_resource_harbor(task_dir, export_dir, metadata=None, project_root=None,
                           runtime_profile=DEFAULT_PROFILE):
    """Create a fresh complete export. This does not execute or certify containers."""
    recipe = _upstream()
    profile = load_runtime_profile(runtime_profile)
    task = Path(task_dir).resolve()
    destination = Path(export_dir).absolute()
    _require(destination.resolve() == destination, 'Export paths must not pass through a symlink')
    _require(not destination.exists() or (destination.is_dir() and not any(destination.iterdir())),
             'A resource export must use a fresh empty directory')
    metadata = deepcopy(metadata or {})
    _require(RESOURCE_FIELD not in metadata, 'The resource export contract is generated, not supplied')
    _require(metadata.get('base_image', profile['image']['tag']) in profile['image'].values(),
             'The task image differs from its immutable resource profile')
    inputs = {'input': _file(task, ['public/input.xlsx', 'input.xlsx']),
              'goal': _file(task, ['private/goal.xlsx', 'private/reference.xlsx', 'goal.xlsx']),
              'instruction': _file(task, ['public/instruction.md', 'instruction.md'])}
    task_id = re.sub(r'[^a-zA-Z0-9._-]', '-', metadata.get('task_id', task.name))
    _require(bool(task_id), 'The exported task ID must not be empty')
    contract = {'version': 1, 'profile': profile,
                'profile_binding': (_reference(runtime_profile) if isinstance(runtime_profile, (str, Path)) else
                    {'canonical_sha256': hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}),
                'recipe': recipe, 'source_artifacts': {key: _reference(value) for key, value in inputs.items()},
                'required_controls': ['oracle', 'nop'],
                'execution_budget': dict(resource_streaming_verifier.EXECUTION_BUDGET),
                'operational_guard_is_model_failure': False,
                'actual_container_resources_verified': False,
                'build_base_reference': profile['image']['tag'],
                'required_local_base_image_id': profile['image']['id'],
                'actual_local_base_image_verification_required_before_build': True,
                'harbor_pid_limit_configured': False,
                'pid_limit_note': 'The installed Harbor task schema has no PID-limit field; verify real HostConfig separately.',
                'quality_or_difficulty_certified': False}
    metadata[RESOURCE_FIELD] = contract
    metadata['base_image'] = profile['image']['id']
    for folder in ('environment', 'solution', 'tests'):
        (destination / folder).mkdir(parents=True, exist_ok=True)
    for source, relative in ((inputs['input'], 'environment/input.xlsx'), (inputs['input'], 'tests/original_input.xlsx'),
                             (inputs['goal'], 'solution/reference.xlsx'), (inputs['goal'], 'tests/reference.xlsx')):
        shutil.copy2(source, destination / relative)
    shutil.copy2(resource_streaming_verifier.__file__, destination / 'tests/verify.py')
    shutil.copy2(streaming_verifier.__file__, destination / 'tests/streaming_core.py')
    shutil.copy2(resource_streaming_verifier.__file__, destination / 'environment/resource_runner.py')
    for folder in ('environment', 'tests'):
        (destination / folder / 'runtime_profile.json').write_text(json.dumps(profile, indent=2) + '\n')
    instruction = inputs['instruction'].read_text()
    if '/app/output.xlsx' not in instruction:
        instruction += '\n\nRead `/app/input.xlsx` and save the completed workbook to `/app/output.xlsx`.\n'
    (destination / 'instruction.md').write_text(instruction)
    image_reference = profile['image']['tag']
    (destination / 'environment/Dockerfile').write_text(
        f'FROM {image_reference}\nUSER root\nENTRYPOINT []\nWORKDIR /app\n'
        'COPY input.xlsx /app/input.xlsx\n'
        'COPY resource_runner.py runtime_profile.json /opt/sheetsfactory/\n'
        'COPY --chmod=755 recalculate /usr/local/bin/recalculate\n'
        'RUN --network=none chmod 0755 /usr/local/bin/recalculate\n')
    (destination / 'environment/recalculate').write_text(
        '#!/bin/sh\nexec /usr/bin/python3 /opt/sheetsfactory/resource_runner.py recalculate '
        '"$@" --profile /opt/sheetsfactory/runtime_profile.json\n')
    (destination / 'tests/Dockerfile').write_text(
        f'FROM {image_reference}\nUSER root\nENTRYPOINT []\nWORKDIR /app\nCOPY . /tests/\n')
    (destination / 'solution/solve.sh').write_text(
        '#!/bin/sh\nset -eu\ncp /solution/reference.xlsx /app/output.xlsx\n')
    (destination / 'tests/test.sh').write_text(
        '#!/bin/sh\nset -eu\nmkdir -p /logs/verifier\n'
        '/usr/bin/python3 /tests/verify.py --input /tests/original_input.xlsx '
        '--goal /tests/reference.xlsx --output /app/output.xlsx --profile /tests/runtime_profile.json '
        '--reward /logs/verifier/reward.txt --report /logs/verifier/diagnostics.json\n')
    for relative in ('environment/recalculate', 'solution/solve.sh', 'tests/test.sh'):
        (destination / relative).chmod(0o755)
    (destination / 'task.toml').write_text(_toml(task_id, metadata, profile))
    manifest = {'task_id': task_id, 'metadata': metadata, 'files': {}}
    for path in sorted(destination.rglob('*')):
        if path.is_file():
            manifest['files'][str(path.relative_to(destination))] = _reference(path)['sha256']
    (destination / 'export_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    inspect_resource_export(destination)
    return destination


def inspect_resource_export(export_dir):
    """Keep the original export/control binding and verify the explicit resources."""
    path = Path(export_dir)
    for file in path.rglob('*'):
        _require(not file.is_symlink(), 'Resource exports cannot contain symlinks')
    binding = harbor.inspect_export(path)
    manifest = json.loads((path / 'export_manifest.json').read_text())
    contract = manifest['metadata'].get(RESOURCE_FIELD)
    _require(isinstance(contract, dict) and type(contract.get('version')) is int and contract['version'] == 1,
             'Missing explicit resource export contract')
    profile = load_runtime_profile(contract['profile'])
    _require(contract.get('required_controls') == ['oracle', 'nop']
             and contract.get('actual_container_resources_verified') is False
             and contract.get('harbor_pid_limit_configured') is False
             and contract.get('execution_budget') == resource_streaming_verifier.EXECUTION_BUDGET
             and contract.get('operational_guard_is_model_failure') is False
             and contract.get('quality_or_difficulty_certified') is False,
             'An export cannot certify execution, quality or difficulty')
    _require(contract.get('build_base_reference') == profile['image']['tag']
             and contract.get('required_local_base_image_id') == profile['image']['id']
             and contract.get('actual_local_base_image_verification_required_before_build') is True,
             'The local build tag and exact expected image identity must both remain bound')
    config = tomllib.loads((path / 'task.toml').read_text())
    for name, role in (('agent', config['environment']), ('verifier', config['verifier']['environment'])):
        _require(type(role.get('cpus')) is int and role['cpus'] == 2
                 and type(role.get('memory_mb')) is int
                 and role['memory_mb'] == profile['docker_resources'][name]['memory_bytes'] // 1024**2
                 and role.get('network_mode') == 'no-network', 'Agent/verifier resource configuration differs')
    _require(config['verifier']['timeout_sec'] == 2400
             and config['verifier']['environment_mode'] == 'separate'
             and config['agent']['timeout_sec'] == 14400, 'The phase timeouts differ')
    _require(manifest['metadata'].get('base_image') == profile['image']['id'],
             'The export metadata image differs from its runtime profile')
    recipe = contract['recipe']
    _require(recipe == _upstream(), 'The resource export implementation recipe changed')
    for relative, key in (('tests/verify.py', 'verifier_wrapper'), ('environment/resource_runner.py', 'verifier_wrapper'),
                          ('tests/streaming_core.py', 'streaming_comparison')):
        _require(_reference(path / relative)['sha256'] == recipe[key]['sha256'], 'A packaged implementation differs from its recipe')
    _require(recipe['streaming_comparison']['sha256'] == resource_streaming_verifier.CORE_SHA256
             and recipe['original_harbor']['sha256'] == UPSTREAM_HARBOR_SHA256
             and recipe['resource_engine']['sha256'] == RESOURCE_ENGINE_SHA256,
             'The resource export upstream recipe differs')
    for folder in ('environment', 'tests'):
        _require(json.loads((path / folder / 'runtime_profile.json').read_text()) == profile,
                 'The packaged runtime profile differs')
        _require((path / folder / 'Dockerfile').read_text().startswith('FROM ' + profile['image']['tag'] + '\n'),
                 'Agent/verifier must use the same verified local base reference')
    profile_binding = contract['profile_binding']
    if 'path' in profile_binding:
        _require(profile_binding == _reference(profile_binding['path'])
                 and load_runtime_profile(profile_binding['path']) == profile,
                 'The external resource profile binding changed')
    else:
        _require(profile_binding == {'canonical_sha256': hashlib.sha256(json.dumps(
            profile, sort_keys=True, separators=(',', ':')).encode()).hexdigest()},
            'The resource profile canonical binding differs')
    _require({str(file.relative_to(path / 'environment')) for file in (path / 'environment').rglob('*') if file.is_file()}
             == {'Dockerfile', 'input.xlsx', 'resource_runner.py', 'runtime_profile.json', 'recalculate'},
             'The public environment contains unexpected artifacts')
    _require(_reference(path / 'environment/input.xlsx')['sha256'] == contract['source_artifacts']['input']['sha256']
             and _reference(path / 'tests/original_input.xlsx')['sha256'] == contract['source_artifacts']['input']['sha256']
             and _reference(path / 'tests/reference.xlsx')['sha256'] == contract['source_artifacts']['goal']['sha256']
             and _reference(path / 'solution/reference.xlsx')['sha256'] == contract['source_artifacts']['goal']['sha256'],
             'An exported workbook differs from its task source')
    return {**binding, 'required_controls': ['oracle', 'nop'], RESOURCE_FIELD: contract}
