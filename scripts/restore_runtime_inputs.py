#!/usr/bin/env python3
"""Restore hash-bound local inputs from the small, tracked runtime asset bundle.

Historical code retains its original paths and hashes. This command recreates
only the seven declared inputs, and never replaces existing content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import uuid


ASSET_DIRECTORY = 'runtime/assets/document_inputs'
MANIFEST = ASSET_DIRECTORY + '/manifest.json'
TARGETS = frozenset({
    'src/sheets_factory/workbook/derived_regulatory/POLICY.md',
    'src/sheets_factory/workbook/lease_finance/CONTRACT.md',
    'docs/linear_capital_portfolio_contract.md',
    'docs/spreadsheet_failure_analysis_prompt.md',
    'docs/independent_controls_candidate.md',
    'docs/heterogeneous_native_review_pack.md',
    'docs/linear_capital_scaled_highs_screen.md',
})


class RestorationError(ValueError):
    """The declared bundle or an existing local input is unsafe or different."""


def _parts(value):
    if (type(value) is not str or not value or '\\' in value
            or PurePosixPath(value).is_absolute()
            or PurePosixPath(value).as_posix() != value
            or any(not re.fullmatch(r'[A-Za-z0-9_.-]+', part)
                   or part in ('.', '..') for part in value.split('/'))):
        raise RestorationError('Runtime input paths must be normalized relative paths')
    return value.split('/')


def _directory(root_fd, parts, *, create=False):
    """Open each directory relative to a retained descriptor; reject symlinks."""
    current = os.dup(root_fd)
    try:
        for part in parts:
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=current)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, mode=0o755, dir_fd=current)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=current)
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


def _read_at(parent_fd, name):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=parent_fd)
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise RestorationError('Runtime inputs must be regular files')
        return stream.read()


def _read(root_fd, relative, *, optional=False):
    parts = _parts(relative)
    try:
        parent_fd = _directory(root_fd, parts[:-1])
    except FileNotFoundError:
        if optional:
            return None
        raise
    try:
        try:
            return _read_at(parent_fd, parts[-1])
        except FileNotFoundError:
            if optional:
                return None
            raise
    finally:
        os.close(parent_fd)


def _unique_object(pairs):
    value = {}
    for key, child in pairs:
        if key in value:
            raise RestorationError('Duplicate runtime manifest fields are invalid')
        value[key] = child
    return value


def _validated_bundle(root_fd):
    manifest = json.loads(_read(root_fd, MANIFEST), object_pairs_hook=_unique_object)
    if (type(manifest) is not dict or set(manifest) != {'version', 'kind', 'entries'}
            or type(manifest['version']) is not int or manifest['version'] != 1
            or manifest['kind'] != 'local_runtime_document_inputs'
            or type(manifest['entries']) is not list):
        raise RestorationError('Unsupported runtime input manifest')
    entries = manifest['entries']
    if len(entries) != len(TARGETS):
        raise RestorationError('The complete seven-input bundle is required')
    seen_targets, seen_sources, bundle = set(), set(), []
    for entry in entries:
        if type(entry) is not dict or set(entry) != {'target', 'source', 'sha256', 'bytes'}:
            raise RestorationError('Runtime input fields differ')
        target, source = entry['target'], entry['source']
        _parts(target)
        source_parts = _parts(source)
        if (target not in TARGETS or target in seen_targets or source in seen_sources
                or source_parts[:-1] != ASSET_DIRECTORY.split('/')
                or not source_parts[-1].endswith('.txt')
                or type(entry['sha256']) is not str
                or not re.fullmatch(r'[0-9a-f]{64}', entry['sha256'])
                or type(entry['bytes']) is not int or entry['bytes'] <= 0):
            raise RestorationError('Runtime input identity or path differs')
        payload = _read(root_fd, source)
        if (len(payload) != entry['bytes']
                or hashlib.sha256(payload).hexdigest() != entry['sha256']):
            raise RestorationError('A bundled runtime input differs from its manifest')
        existing = _read(root_fd, target, optional=True)
        if existing is not None and existing != payload:
            raise RestorationError('An existing runtime input differs; no files were replaced')
        seen_targets.add(target)
        seen_sources.add(source)
        bundle.append((target, payload, existing is not None))
    if seen_targets != TARGETS:
        raise RestorationError('The complete seven-input bundle is required')
    return bundle


def _restore(root_fd, target, payload):
    parts = _parts(target)
    parent_fd = _directory(root_fd, parts[:-1], create=True)
    temporary = '.sheets-factory-runtime-' + uuid.uuid4().hex
    created = False
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o644, dir_fd=parent_fd)
        created = True
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # link() publishes complete bytes without replacing any existing file.
            os.link(temporary, parts[-1], src_dir_fd=parent_fd, dst_dir_fd=parent_fd,
                    follow_symlinks=False)
            return True
        except FileExistsError:
            if _read_at(parent_fd, parts[-1]) != payload:
                raise RestorationError('An existing runtime input differs; no files were replaced')
            return False
    finally:
        if created:
            os.unlink(temporary, dir_fd=parent_fd)
        os.close(parent_fd)


def restore_runtime_inputs(project_root):
    """Validate all inputs before writing; return counts without content or paths."""
    root = Path(project_root).absolute()
    try:
        if root != root.resolve(strict=True) or not root.is_dir():
            raise RestorationError('Use a real project directory without symlink components')
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise RestorationError('Use a real project directory without symlink components') from error
    try:
        bundle = _validated_bundle(root_fd)
        restored = 0
        for target, payload, exists in bundle:
            if not exists:
                restored += int(_restore(root_fd, target, payload))
        return {'restored': restored, 'unchanged': len(bundle) - restored, 'total': len(bundle)}
    except OSError as error:
        raise RestorationError('Runtime input paths must contain real directories and regular files') from error
    finally:
        os.close(root_fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path,
                        default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        result = restore_runtime_inputs(args.project_root)
    except (RestorationError, json.JSONDecodeError, UnicodeError) as error:
        print('Runtime input restoration failed: ' + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
