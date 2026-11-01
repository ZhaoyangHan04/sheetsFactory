"""Isolated ringfenced-pair export/runtime; no old family or module is changed."""
from __future__ import annotations

import ast
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import ModuleType

import yaml

from . import resource_harbor as original
from . import thread_capped_harbor_export as original_cap
from . import ringfenced_streaming_verifier as runtime

ROOT = Path(__file__).resolve().parents[3]
PROFILE = ROOT/'config/runtime_profiles/ringfenced_pair_source_v1.yaml'
DEFAULT_PROFILE = PROFILE
PROFILE_SHA256 = '20fc02fec3aaf4918ece50d18ef9e315ffee9fccce088863f044ebac301a026a'
RESOURCE_EXPORT_SHA256 = '38f625e9f74dd51ef61c66b986bb4e68bf183d8ab7d5a7acbf9dc77acec28a40'
CAP_EXPORT_SHA256 = 'cc3811b250837df5943d8be7982ead23c7c38f443e2f2a9859e1da1d9af646fd'
RUNTIME_SHA256 = '7b6795895adaa6b4ac7a5ec3e4816e8668e3f6cfd0cfb6c4cd1e2c2507706e01'


def _require(value, message):
    if not value:
        raise ValueError(message)


def _reference(value):
    return original_cap._reference(value)


def _guard():
    for path, digest in ((original.__file__, RESOURCE_EXPORT_SHA256),
        (original_cap.__file__, CAP_EXPORT_SHA256), (runtime.__file__, RUNTIME_SHA256), (PROFILE, PROFILE_SHA256)):
        _require(_reference(path)['sha256'] == digest, 'A frozen ringfenced export dependency changed')
    _require(runtime.UPSTREAM_RESOURCE_RUNTIME_SHA256 == _reference(original.resource_streaming_verifier.__file__)['sha256'],
             'The original resource runtime changed')


def load_runtime_profile(value=PROFILE):
    """Keep the real ring identity; never project it to an entity-family ID."""
    _guard()
    if isinstance(value, (str, Path)):
        path = Path(value)
        _require(not path.is_symlink() and path.is_file(), 'The ringfenced profile must be a real file')
        _require(_reference(path)['sha256'] == PROFILE_SHA256, 'The exact ringfenced profile file changed')
        value = yaml.safe_load(path.read_text())
    return runtime.validate_profile(deepcopy(value))


def _resource_namespace():
    _guard()
    tree = ast.parse(Path(original.__file__).read_text()); counts = Counter()
    class Revision(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.level == 2 and node.module == 'workbook.resource_engine':
                _require([(n.name,n.asname)for n in node.names] == [('DEFAULT_PROFILE',None),('load_runtime_profile',None)],
                         'The exact resource profile import changed')
                counts['profile_import'] += 1
                return None
            return node
    tree = Revision().visit(tree)
    _require(counts == Counter(profile_import=1), 'The resource exporter adaptation seam changed')
    module = ModuleType('_private_ringfenced_resource_export')
    module.__dict__.update(__file__=__file__, __package__=__package__, DEFAULT_PROFILE=PROFILE,
                           load_runtime_profile=load_runtime_profile)
    exec(compile(ast.fix_missing_locations(tree), original.__file__, 'exec'), module.__dict__)
    module.resource_streaming_verifier = runtime
    base_upstream = module._upstream
    def upstream():
        _guard()
        return {**base_upstream(), 'resource_exporter_base': _reference(original.__file__),
                'worker_cap_exporter_base': _reference(original_cap.__file__), 'ringfenced_profile': _reference(PROFILE)}
    module._upstream = upstream
    return module


def _cap_namespace(base):
    _guard()
    tree = ast.parse(Path(original_cap.__file__).read_text()); counts = Counter()
    class Revision(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.level == 1 and node.module is None and [(n.name,n.asname)for n in node.names] == [('resource_harbor','base')]:
                counts['base_import'] += 1
                return None
            return node
    tree = Revision().visit(tree)
    _require(counts == Counter(base_import=1), 'The worker-cap exporter adaptation seam changed')
    module = ModuleType('_private_ringfenced_worker_cap_export')
    module.__dict__.update(__file__=__file__, __package__=__package__, base=base)
    exec(compile(ast.fix_missing_locations(tree), original_cap.__file__, 'exec'), module.__dict__)
    def implementation():
        _guard()
        return {'adapter': _reference(__file__), 'base_exporter': _reference(original.__file__),
                'base_worker_cap_exporter': _reference(original_cap.__file__),
                'ringfenced_verifier_wrapper': _reference(runtime.__file__), 'ringfenced_profile': _reference(PROFILE)}
    module._implementation = implementation
    return module


_B = _resource_namespace()
_C = _cap_namespace(_B)
CAP_FIELD, CAP_VALUE = _C.CAP_FIELD, _C.CAP_VALUE
RESOURCE_FIELD = _B.RESOURCE_FIELD


def recipes():
    _guard()
    return _B._upstream()


def export_resource_harbor(task_dir, export_dir, metadata=None, project_root=None,
                           runtime_profile=PROFILE, *, audit_path):
    _guard()
    load_runtime_profile(runtime_profile)
    result = _C.export_resource_harbor(task_dir, export_dir, metadata, project_root,
        runtime_profile, audit_path=audit_path)
    inspect_resource_export(result, audit_path=audit_path)
    return result


def inspect_resource_export(export_dir, *, audit_path=None):
    """Always verify actual cap bytes; an optional private audit adds its replay."""
    _guard()
    binding = _B.inspect_resource_export(export_dir)
    path = Path(export_dir)
    inventory = _C._inventory(path)
    _require(len(inventory) == 17, 'The complete ringfenced export must have exactly seventeen files')
    manifest = json.loads((path/'export_manifest.json').read_text())
    _require(set(manifest['files']) == set(inventory)-{'export_manifest.json'}
        and manifest['metadata'].get(CAP_FIELD) == CAP_VALUE,
        'The complete ringfenced inventory or exact worker-cap metadata changed')
    for relative in _C.DOCKERFILES:
        raw = (path/relative).read_bytes()
        _require(len(raw.splitlines()) > 1 and raw.splitlines()[1] == _C.ENV_LINE.rstrip(b'\n')
            and raw.count(b'MAX_CONCURRENCY') == 1,
            'Each role requires its exact single second-line worker-cap ENV declaration')
    if audit_path is not None:
        _require(_C.inspect_resource_export(path,audit_path=audit_path) == binding,
                 'The private worker-cap audit describes another export')
    _guard()
    return binding


def inspect_export(export_dir):
    return inspect_resource_export(export_dir)


def verify_local_base_image(runtime_profile=PROFILE):
    _guard()
    return _B.verify_local_base_image(runtime_profile)
