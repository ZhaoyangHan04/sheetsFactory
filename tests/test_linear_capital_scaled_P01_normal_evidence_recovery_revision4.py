"""Stored P01 fixtures; enriched resource contracts must remain fully checked."""
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def stored(tmp_path, monkeypatch):
    fixtures = load('tests/test_linear_capital_scaled_P01_normal_evidence_recovery_revision3.py', '_v4_stored_fixtures')
    original = fixtures.entry.__wrapped__()
    old, run, tasks, contexts, calls, base = fixtures.stored.__wrapped__(tmp_path, monkeypatch, original)
    # Real historical tasks/batch kept only the base identity. The old fixtures
    # used the enriched inspector result and therefore missed this schema seam.
    for task in tasks:
        task['historical_harbor_export_binding'] = {key: value for key, value in task['historical_harbor_export_binding'].items()
                                                   if key not in ('required_controls', 'resource_runtime')}
    batch_path = run / 'harbor_batches' / old.BATCH / 'batch_manifest.json'
    batch = json.loads(batch_path.read_text())
    batch['export_bindings'] = {row['historical_harbor_export_binding']['task_name']: row['historical_harbor_export_binding']
                                for row in tasks}
    base.put(batch_path, batch)
    with sqlite3.connect(run / 'run.sqlite') as connection:
        connection.executemany('UPDATE tasks SET payload=? WHERE id=?', [(json.dumps(task), task['id']) for task in tasks])
    proposal = json.loads(Path(old._N['PROPOSAL']['path']).read_text())
    proposal['anchors'] = {key: old.reference(row['path']) for key, row in proposal['anchors'].items()}
    proposal_path = tmp_path / 'v4_original_proposal.json'
    base.put(proposal_path, proposal)
    monkeypatch.setitem(old._N, 'PROPOSAL', old.reference(proposal_path))
    # Access through exported scalar aliases in the wrapper must use the same
    # synthetic scope as the frozen private implementation.
    for key in ('RUN', 'PROPOSAL'):
        monkeypatch.setattr(old, key, old._N[key])
    m = load('scripts/recover_linear_capital_scaled_P01_normal_evidence_revision4.py', '_v4_recovery_entry')
    monkeypatch.setattr(m, 'OLD', old)
    return m, old, run, tasks, contexts, calls, base


def test_real_base_identity_schema_recovers_all_stored_proof_without_old_writes(stored, tmp_path):
    m, old, run, _, _, calls, base = stored
    before = base.tree(run)
    out = tmp_path / 'new_revision4'
    m.prepare(out)
    assert not calls
    path = Path(m.certify(out)['path'])
    result = json.loads(path.read_text())
    assert result['version'] == 4 and result['evidence_recovered'] is True
    assert result['new_calls'] == {'model': 0, 'LO': 0, 'Harbor': 0, 'Docker': 0}
    assert result['formal_release'] is result['qualified'] is result['original_statuses_changed'] is False
    assert len(calls) == 4 and len(result['audited_summary_transport_checks']) == 2
    assert len(result['resource_export_binding_checks']) == 2
    assert all(row['all_enriched_fields_compared'] for row in result['resource_export_binding_checks'])
    assert all(len(row['identical_original_exports']) == 17 for row in result['tasks'])
    assert base.tree(run) == before
    with pytest.raises(ValueError, match='first certificate'):
        m.certify(out)


@pytest.mark.parametrize('fault', ['base_identity', 'quarantine_contract', 'controls', 'missing_contract', 'extra_field'])
def test_projection_never_discards_resource_or_identity_disagreement(stored, monkeypatch, fault):
    m, old, run, tasks, _, _, _ = stored
    expected = tasks[0]['historical_harbor_export_binding']
    left = {**deepcopy(expected), 'required_controls': ['oracle', 'nop'], 'resource_runtime': {'image': 'synthetic'}}
    right = deepcopy(left)
    if fault == 'base_identity':
        right['revision_hash'] = 'different'
    elif fault == 'quarantine_contract':
        right['resource_runtime']['image'] = 'different'
    elif fault == 'controls':
        left['required_controls'] = right['required_controls'] = ['oracle']
    elif fault == 'missing_contract':
        left.pop('resource_runtime'); right.pop('resource_runtime')
    else:
        left['extra'] = right['extra'] = 'unbound'
    monkeypatch.setattr(old, 'inspect_resource_export', lambda path: left if path == Path('staged') else right)
    with pytest.raises(ValueError):
        m._resource_bound_exports(Path('staged'), Path('quarantine'), expected, old.Access())


@pytest.mark.parametrize('fault', ['stale_Q04', 'resource_incomplete', 'changed_goal', 'quarantined_file', 'nonempty_WAL'])
def test_recovery_preserves_existing_material_quality_resource_and_sqlite_gates(stored, tmp_path, monkeypatch, fault):
    m, old, run, tasks, contexts, _, base = stored
    out = tmp_path / 'reject_case'
    m.prepare(out)
    if fault == 'stale_Q04':
        path = contexts[0].revision_dir / 'private/diagnosis.json'
        value = json.loads(path.read_text()); value['assessments']['Q04']['evidence'] = []
        base.put(path, value)
    elif fault == 'resource_incomplete':
        monkeypatch.setitem(old._N, 'validate_trial_observations', lambda *a, **kw: {'passed': False, 'complete': False})
    elif fault == 'changed_goal':
        (contexts[0].revision_dir / 'private/goal.xlsx').write_bytes(b'changed')
    elif fault == 'quarantined_file':
        (run / 'quarantined_exports' / (tasks[0]['id'] + '-resource-observation') / 'instruction.md').write_text('changed')
    else:
        (run / 'run.sqlite-wal').write_bytes(b'pending')
    before = base.tree(run)
    with pytest.raises(ValueError):
        m.certify(out)
    assert base.tree(run) == before


def test_only_the_export_binding_comparison_changes():
    m = load('scripts/recover_linear_capital_scaled_P01_normal_evidence_revision4.py', '_v4_ast_review')
    original = ast.parse((ROOT / 'scripts/recover_linear_capital_scaled_P01_normal_evidence.py').read_bytes())
    left = next(item for item in original.body if isinstance(item, ast.FunctionDef) and item.name == '_export')
    right = m.export_ast().body[0]
    calls = []

    class Restore(ast.NodeTransformer):
        def visit_Call(self, node):
            if ast.unparse(node) == '_resource_bound_exports(staged, quarantine, expected, access)':
                calls.append(1)
                return ast.parse('inspect_resource_export(staged) == inspect_resource_export(quarantine) == expected').body[0].value
            return self.generic_visit(node)

    assert ast.dump(left, include_attributes=False) == ast.dump(Restore().visit(right), include_attributes=False)
    assert calls == [1]
