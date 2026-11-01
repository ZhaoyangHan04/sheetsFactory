"""Inspect only the two exact resource profiles used by the business cohort."""
from __future__ import annotations

import json
from pathlib import Path
from copy import deepcopy
from . import resource_harbor as retained
from . import ringfenced_resource_harbor as paired
from ..workbook.resource_engine import load_runtime_profile as load_retained

IDS = ('entity_group_large_v2', 'ringfenced_pair_source_v1')


def _value(value):
    if isinstance(value, (str, Path)):
        import yaml
        p = Path(value)
        if p.is_symlink() or not p.is_file():
            raise ValueError('The observed runtime profile must be a real file')
        return yaml.safe_load(p.read_text())
    return deepcopy(value)


def load_runtime_profile(value):
    raw = _value(value)
    if type(raw) is not dict or raw.get('id') not in IDS:
        raise ValueError('Only the two declared business resource profiles are allowed')
    loader = paired.load_runtime_profile if raw['id'] == IDS[1] else load_retained
    return loader(value)


def inspect_resource_export(directory, *, audit_path=None):
    directory = Path(directory)
    profile = load_runtime_profile(json.loads((directory/'environment/runtime_profile.json').read_text()))
    if profile['id'] == IDS[1]:
        return paired.inspect_resource_export(directory, audit_path=audit_path)
    if audit_path is not None:
        from .thread_capped_harbor_export import inspect_resource_export as capped
        return capped(directory, audit_path=audit_path)
    return retained.inspect_resource_export(directory)


inspect_export = inspect_resource_export
