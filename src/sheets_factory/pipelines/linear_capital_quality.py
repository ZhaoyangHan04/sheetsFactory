"""Explicit native linear-portfolio source admission.

Source validators execute once in a cold process. Later nodes use an opaque
in-process object and content-bound file guards, never a persisted pass flag.
This module does not start engines, models, optimizers or Harbor services.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import stat
import sys
import weakref

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROVIDERS = ROOT / 'config/task_adapters/linear_capital_source_providers_v1.json'
_ACTIVE_SOURCES = weakref.WeakSet()
_MODULES = {}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _fingerprint(path):
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink()
        and path == path.resolve(), 'A real nonsymlink artifact is required')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
        info.st_ctime_ns, info.st_mode, info.st_nlink)


def reference(value):
    path = Path(value).absolute()
    before = _fingerprint(path)
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(4 * 1024**2), b''):
            digest.update(block)
    require(_fingerprint(path) == before, 'An artifact changed while hashing')
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': before[2]}


class References:
    """Content-check once, then rehash any changed filesystem identity."""
    def __init__(self):
        self.files = {}
        self.fingerprints = {}
        self._json_seen = set()
        self.large_json_leaves = []

    def check(self, record):
        require(type(record) is dict and set(record) == {'path', 'sha256', 'bytes'}
            and type(record['path']) is str and type(record['bytes']) is int and record['bytes'] >= 0
            and type(record['sha256']) is str and re.fullmatch('[0-9a-f]{64}', record['sha256']),
            'A complete SHA256/bytes/path reference is required')
        path = Path(record['path'])
        require(path.is_absolute(), 'Artifact references must use absolute paths')
        current = _fingerprint(path)
        prior = self.files.get(str(path))
        require(prior is None or prior == record, 'Conflicting references name one physical file')
        if self.fingerprints.get(str(path)) != current:
            require(reference(path) == record, 'A bound artifact changed: ' + str(path))
            self.fingerprints[str(path)] = current
        self.files[str(path)] = deepcopy(record)
        return path

    def walk(self, value):
        if isinstance(value, dict):
            if set(value) == {'path', 'sha256', 'bytes'}:
                self.check(value)
            else:
                for item in value.values():
                    self.walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self.walk(item)

    def guard(self):
        for record in tuple(self.files.values()):
            self.check(record)

    def discover(self, record):
        """Follow small evidence records; large financial payloads stay opaque.

        Large tables are guarded by their complete byte SHA. A consumer that
        interprets references inside such a payload must also walk that parsed
        object. No large financial table is decoded just to guard its bytes.
        """
        path = self.check(record)
        if path.suffix.lower() != '.json' or str(path) in self._json_seen:
            return
        self._json_seen.add(str(path))
        if record['bytes'] > 2 * 1024**2:
            self.large_json_leaves.append(deepcopy(record))
            return
        value = self.read(record)
        def descend(item):
            if isinstance(item, dict):
                if set(item) == {'path', 'sha256', 'bytes'}:
                    self.discover(item)
                else:
                    for nested in item.values():
                        descend(nested)
            elif isinstance(item, (tuple, list)):
                for nested in item:
                    descend(nested)
        descend(value)

    def read(self, value):
        record = value if isinstance(value, dict) else reference(value)
        path = self.check(record)
        result = json.loads(path.read_text(encoding='utf-8'))
        self.check(record)
        return result


def _load_provider(record, references):
    path = references.check(record)
    require(path.suffix == '.py' and path.is_relative_to(ROOT),
        'A provider must be an explicitly frozen local Python module')
    key = (str(path), record['sha256'])
    if key not in _MODULES:
        name = '_linear_quality_provider_' + record['sha256']
        definition = importlib.util.spec_from_file_location(name, path)
        require(definition is not None and definition.loader is not None, 'The provider cannot be loaded')
        module = importlib.util.module_from_spec(definition)
        sys.modules[name] = module
        definition.loader.exec_module(module)
        references.check(record)
        _MODULES[key] = module
    return _MODULES[key]


def _configured_module(record):
    require(type(record) is dict and set(record) == {'path', 'sha256', 'bytes'}
        and type(record['path']) is str, 'An explicit project-relative provider module is required')
    name = record['path']
    require(name and '\\' not in name and not Path(name).is_absolute()
        and all(part not in ('', '.', '..') for part in name.split('/')),
        'Provider modules must use canonical project-relative paths without traversal')
    path = ROOT / name
    require(path == path.resolve() and path.is_relative_to(ROOT),
        'Provider modules cannot escape the checkout or use symlinks')
    return {**record, 'path': str(path)}


class SourceProviders:
    """A frozen registry is the only way to add a source-validator provider."""
    def __init__(self, value=DEFAULT_PROVIDERS):
        self.references = References()
        self.reference = value if isinstance(value, dict) else reference(value)
        registry = self.references.read(self.reference)
        require(type(registry) is dict and registry.get('kind') == 'linear_capital_source_provider_registry'
            and type(registry.get('version')) is int and registry['version'] == 1,
            'The explicit linear source-provider registry is required')
        rows = registry.get('providers')
        require(type(rows) is list and bool(rows), 'At least one explicit provider is required')
        self.providers = {}
        for row in rows:
            require(type(row) is dict and set(row) == {'id', 'module', 'source_kind', 'api_version', 'functions'}
                and type(row['id']) is str and re.fullmatch('[a-z][a-z0-9_]*', row['id'])
                and row['id'] not in self.providers and type(row['source_kind']) is str and row['source_kind']
                and type(row['api_version']) is int and row['api_version'] == 1
                and row['functions'] == {'validate_source': 'validate_source',
                    'validate_actual_call': 'validate_actual_call', 'runtime': 'runtime'},
                'An explicit unique provider with the version-one source API is required')
            row = {**row, 'module': _configured_module(row['module'])}
            self.references.check(row['module'])
            self.providers[row['id']] = deepcopy(row)

    def load(self, provider_id):
        self.references.guard()
        require(type(provider_id) is str and provider_id in self.providers,
            'Unknown provider; freeze a new explicit registry before extending it')
        row = self.providers[provider_id]
        module = _load_provider(row['module'], self.references)
        require(getattr(module, 'SOURCE_KIND', None) == row['source_kind']
            and all(callable(getattr(module, name, None)) for name in row['functions'].values()),
            'The frozen provider does not implement its declared source API/kind')
        return deepcopy(row), module


class LinearSourceAdmission:
    """One real cold source validation; guard calls never repeat that validation."""
    def __init__(self, source_manifest, *, provider_id, provider_registry=DEFAULT_PROVIDERS):
        self.providers = provider_registry if isinstance(provider_registry, SourceProviders) else SourceProviders(provider_registry)
        self.provider, self.helper = self.providers.load(provider_id)
        self.provider_id = provider_id
        self.references = References()
        self.source_manifest = source_manifest if isinstance(source_manifest, dict) else reference(source_manifest)
        self.references.check(self.source_manifest)
        # The provider is trusted code only after its exact module SHA and API
        # were checked. No manifest flag or caller-supplied proof bypasses it.
        source = self.helper.validate_source(deepcopy(self.source_manifest))
        require(type(source) is dict and source.get('kind') == self.provider['source_kind']
            and type(source.get('version')) is int and source['version'] == 1
            and source.get('source_financially_verified') is True,
            'The actual provider did not validate a complete financial source')
        for name in ('workbook', 'public_specification', 'bindings', 'runtime_profile'):
            require(type(source.get(name)) is dict, 'The complete source lacks ' + name)
        self.references.walk(source)
        for record in tuple(self.references.files.values()):
            self.references.discover(record)
        self.references.check(self.source_manifest)
        self.references.check(self.provider['module'])
        for path, digest in source.get('source_recipe_sha256', {}).items():
            record = reference(path)
            require(record['sha256'] == digest, 'A financial source recipe changed')
            self.references.check(record)
        self.proof = deepcopy(source)
        self.cold_source_validation_count = 1
        _ACTIVE_SOURCES.add(self)

    def guard(self):
        require(self in _ACTIVE_SOURCES, 'A live opaque source admission is required')
        self.providers.references.guard()
        self.references.guard()
        return deepcopy(self.proof)


def require_source_admission(value):
    require(type(value) is LinearSourceAdmission and value in _ACTIVE_SOURCES,
        'Persisted JSON flags cannot replace a live cold source admission')
    return value.guard()
