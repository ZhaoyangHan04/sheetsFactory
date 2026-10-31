"""Fresh resource exports with the same explicit LO worker cap in both roles.

The base exporter and verifier stay unchanged. An external audit retains the
original export manifest and Dockerfile text; exactly two ENV lines are added.
This module certifies export bytes only, never actual container execution.
"""
from __future__ import annotations

from copy import deepcopy
import difflib
import hashlib
import json
from pathlib import Path

from . import resource_harbor as base

BASE_SHA256 = '38f625e9f74dd51ef61c66b986bb4e68bf183d8ab7d5a7acbf9dc77acec28a40'
CAP_FIELD = 'libreoffice_worker_cap'
CAP_VALUE = 'MAX_CONCURRENCY=2'
ENV_LINE = b'ENV MAX_CONCURRENCY=2\n'
DOCKERFILES = ('environment/Dockerfile', 'tests/Dockerfile')
verify_local_base_image = base.verify_local_base_image


def _require(value, message):
    if not value:
        raise ValueError(message)


def _reference(value):
    p = Path(value).absolute()
    _require(p == p.resolve() and p.is_file(), 'An exact real export audit file is required')
    digest = hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024**2), b''): digest.update(block)
    return {'path': str(p), 'sha256': digest.hexdigest(), 'bytes': p.stat().st_size}


def _checked(value):
    if isinstance(value, dict):
        _require(set(value) == {'path','sha256','bytes'} and type(value['bytes']) is int
                 and _reference(value['path']) == value, 'An export audit reference changed')
        return value
    return _reference(value)


def _implementation():
    upstream = _reference(base.__file__)
    _require(upstream['sha256'] == BASE_SHA256, 'The bound resource exporter changed')
    return {'adapter': _reference(__file__), 'base_exporter': upstream}


def _write(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream: stream.write(data)
    return _reference(path)


def _inventory(path):
    return {p.relative_to(path).as_posix(): {k:v for k,v in _reference(p).items() if k!='path'}
            for p in sorted(path.rglob('*')) if p.is_file()}


def _capped(raw):
    _require(raw.startswith(b'FROM ') and b'\n' in raw and b'MAX_CONCURRENCY' not in raw,
             'The uncapped base Dockerfile must have a first FROM line and no worker-cap declaration')
    before, remainder = raw.split(b'\n',1)
    return before+b'\n'+ENV_LINE+remainder


def _audit_location(audit_path, export):
    path = Path(audit_path).absolute()
    _require(path == path.resolve() and not path.is_relative_to(export), 'Keep the export audit outside the seventeen-file export')
    return path


def export_resource_harbor(task_dir, export_dir, metadata=None, project_root=None,
                           runtime_profile=base.DEFAULT_PROFILE, *, audit_path):
    recipe = _implementation()
    destination = Path(export_dir).absolute()
    audit = _audit_location(audit_path,destination)
    evidence_dir = audit.with_name(audit.stem+'_evidence')
    _require(not audit.exists() and not evidence_dir.exists(), 'Preserve previous export audits and their original bytes')
    metadata = deepcopy(metadata or {})
    _require(CAP_FIELD not in metadata or metadata[CAP_FIELD] == CAP_VALUE, 'The worker-cap metadata must be the exact fixed string')
    metadata[CAP_FIELD] = CAP_VALUE
    result = base.export_resource_harbor(task_dir,destination,metadata,project_root,runtime_profile)
    before_inventory = _inventory(result)
    _require(len(before_inventory) == 17, 'A complete original seventeen-file export is required')
    original = (result/'export_manifest.json').read_bytes()
    original_ref = _write(evidence_dir/'export_manifest.original.json',original)
    manifest = json.loads(original); changes = {}
    for relative in DOCKERFILES:
        file = result/relative; raw = file.read_bytes(); after = _capped(raw)
        before = _write(evidence_dir/(relative.split('/')[0]+'.Dockerfile.before'),raw)
        file.write_bytes(after)
        changes[relative] = {'before': before, 'after': _reference(file),
            'unified_diff': ''.join(difflib.unified_diff(raw.decode().splitlines(keepends=True),
                after.decode().splitlines(keepends=True),fromfile=relative+'.before',tofile=relative+'.after'))}
        manifest['files'][relative] = changes[relative]['after']['sha256']
    (result/'export_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    record = {'kind': 'thread_capped_resource_harbor_export_audit', 'version': 1,
        'export_directory': str(result), 'implementation': recipe, 'worker_cap': CAP_VALUE,
        'original_manifest': original_ref, 'transformed_manifest': _reference(result/'export_manifest.json'),
        'original_inventory': before_inventory, 'dockerfile_changes': changes,
        'unchanged_payload_files': sorted(set(before_inventory)-set(DOCKERFILES)-{'export_manifest.json'}),
        'actual_container_resources_verified': False, 'quality_or_difficulty_certified': False}
    _write(audit,(json.dumps(record,indent=2)+'\n').encode())
    inspect_resource_export(result,audit_path=audit)
    return result


def inspect_resource_export(export_dir, *, audit_path):
    binding = base.inspect_resource_export(export_dir)
    export = Path(export_dir).resolve(); ref = _checked(audit_path)
    _audit_location(ref['path'],export)
    audit = json.loads(Path(ref['path']).read_text())
    _require(audit.get('kind') == 'thread_capped_resource_harbor_export_audit'
        and type(audit.get('version')) is int and audit['version'] == 1
        and audit.get('export_directory') == str(export) and audit.get('implementation') == _implementation()
        and audit.get('worker_cap') == CAP_VALUE and audit.get('actual_container_resources_verified') is False
        and audit.get('quality_or_difficulty_certified') is False, 'The fixed worker-cap export audit changed')
    original_ref = _checked(audit['original_manifest'])
    _audit_location(original_ref['path'],export)
    original = json.loads(Path(original_ref['path']).read_text())
    current_ref = _checked(audit['transformed_manifest'])
    _require(current_ref == _reference(export/'export_manifest.json'), 'The capped manifest must belong to this exact export')
    manifest = json.loads((export/'export_manifest.json').read_text())
    _require(original['metadata'].get(CAP_FIELD) == CAP_VALUE
        and manifest['metadata'].get(CAP_FIELD) == CAP_VALUE
        and {k:v for k,v in original.items() if k!='files'} == {k:v for k,v in manifest.items() if k!='files'},
        'Cap metadata must be an exact string present before export; all other metadata stays unchanged')
    before_inventory = audit['original_inventory']; current_inventory = _inventory(export)
    _require(set(before_inventory) == set(current_inventory) and len(current_inventory) == 17
        and before_inventory['export_manifest.json'] == {k:v for k,v in original_ref.items() if k!='path'}
        and set(original['files']) == set(manifest['files']) == set(current_inventory)-{'export_manifest.json'}
        and set(audit['dockerfile_changes']) == set(DOCKERFILES), 'The complete original/capped file inventories differ')
    unchanged = sorted(set(current_inventory)-set(DOCKERFILES)-{'export_manifest.json'})
    _require(audit['unchanged_payload_files'] == unchanged
        and all(before_inventory[p] == current_inventory[p] and original['files'][p] == manifest['files'][p]
                == current_inventory[p]['sha256'] for p in unchanged), 'An export payload outside the two Dockerfiles changed')
    for relative in DOCKERFILES:
        change = audit['dockerfile_changes'][relative]
        before_ref = _checked(change['before']); _audit_location(before_ref['path'],export)
        after_ref = _checked(change['after'])
        raw = Path(before_ref['path']).read_bytes(); after = (export/relative).read_bytes()
        expected_diff = ''.join(difflib.unified_diff(raw.decode().splitlines(keepends=True),
            after.decode().splitlines(keepends=True),fromfile=relative+'.before',tofile=relative+'.after'))
        _require(before_inventory[relative] == {k:v for k,v in before_ref.items() if k!='path'}
            and original['files'][relative] == before_ref['sha256']
            and after_ref == _reference(export/relative) and manifest['files'][relative] == after_ref['sha256']
            and after == _capped(raw) and after.splitlines()[1] == ENV_LINE.rstrip(b'\n')
            and change['unified_diff'] == expected_diff, 'Only the exact single ENV line may change in each role')
    # Keep the ordinary frontier's exact export-binding shape. The caller binds
    # the additional private cap audit separately in its preparation manifest.
    return binding
