import ast
from copy import deepcopy
import hashlib

import pytest

from sheets_factory.task_adapters import heterogeneous_specialized_source as subject


def test_only_two_declarations_differ_from_complete_frozen_admission():
    raw = subject._TEMPLATE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == subject._TEMPLATE_SHA256
    expected = ast.parse(raw)
    actual = subject.admission_ast()
    source = {n.targets[0].id: n for n in expected.body if isinstance(n, ast.Assign)
        and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}
    restored = deepcopy(actual)
    for i, node in enumerate(restored.body):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in ('SOURCE_KIND', 'SOURCE_BUILDER'):
            restored.body[i] = deepcopy(source[node.targets[0].id])
    assert ast.dump(restored, include_attributes=False) == ast.dump(expected, include_attributes=False)


def test_rejects_any_change_to_upstream_before_adapting(monkeypatch, tmp_path):
    altered = tmp_path / 'altered.py'
    altered.write_bytes(subject._TEMPLATE.read_bytes() + b'\n')
    monkeypatch.setattr(subject, '_TEMPLATE', altered)
    with pytest.raises(ValueError, match='frozen complete'):
        subject.admission_ast()


def test_private_namespace_points_to_new_builder_without_mutating_parent():
    from sheets_factory.task_adapters import heterogeneous_financial_view as original
    current = subject._admission()
    assert current['SOURCE_BUILDER'].name == 'build_specialized_heterogeneous_source.py'
    assert current['SOURCE_KIND'] == 'independently_verified_policy_specialized_heterogeneous_contract_source'
    assert original.SOURCE_BUILDER.name == 'build_heterogeneous_source.py'
    assert original.SOURCE_KIND == 'independently_verified_heterogeneous_contract_source'


def test_rejects_an_old_or_incomplete_manifest(tmp_path):
    manifest = tmp_path / 'manifest.json'
    manifest.write_text('{"kind":"independently_verified_heterogeneous_contract_source","version":1}')
    with pytest.raises(ValueError, match='completed independently verified'):
        subject.validate_source(manifest)
