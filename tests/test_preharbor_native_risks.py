"""Late facts are checked offline without rerunning valid Harbor controls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from test_harbor_batches import create_export, fake_controls, setup_factory, task


def fixture(tmp_path, monkeypatch, *, task_id='fm-late', revision=1, changes=None):
    factory, audit = setup_factory(tmp_path)
    registry = tmp_path / 'current_risks.json'
    registry.write_text(json.dumps({'sources': []}))
    factory.config['native_risks'] = {'registry_path': str(registry)}
    calls = []
    monkeypatch.setattr('sheets_factory.pipelines.factory.run_controls', fake_controls(calls))
    export = create_export(tmp_path, audit, task_id, revision=revision)
    private = tmp_path / 'tasks' / task_id / 'revisions' / f'{revision:03d}' / 'private'
    private.mkdir(parents=True)
    delta = {'expected_changes': ['Sheet!A1'] if changes is None else changes,
             'goal_sheets': ['IncorrectCachedName'], 'target_roots': ['Sheet!Z1']}
    (private / 'expected_delta.json').write_text(json.dumps(delta))
    # Stale construct-time evidence must not hide facts discovered later.
    (private / 'native_risk_guard.json').write_text(json.dumps({'state': 'clear', 'blocking': False}))
    audit.task(task_id, content_repairs=2, evidence_rounds=3, infrastructure_retries=1)
    return factory, audit, calls, registry, export, private


def register(registry, *, source='a' * 64, cell='A1', sheet='Sheet', certainty='confirmed'):
    registry.write_text(json.dumps({'sources': [{'source_sha256': source, 'risks': [{
        'risk_id': 'late-period-error', 'certainty': certainty,
        'unsafe_regions': [{'sheet': sheet, 'range': cell}],
        'evidence': ['Annual input was subtracted from monthly output at this exact cell.']}]}]}))


def test_late_confirmed_risk_blocks_ready_before_any_harbor_call(tmp_path, monkeypatch):
    factory, audit, calls, registry, export, private = fixture(tmp_path, monkeypatch)
    register(registry)
    factory._validate_exports()
    current = task(audit, 'fm-late')
    assert current['status'] == 'rejected' and not calls
    assert not export.exists()
    assert list((tmp_path / 'rejected_exports').glob('fm-late-native-*'))
    assert current['issues'][-1]['problem_id'] == 'Q09'
    assert current['issues'][-1]['route_id'] == 'R09'
    assert current['issues'][-1]['affected_cells'] == ['Sheet!A1']
    receipt = current['preharbor_native_risk_guard']
    assert receipt['revision'] == 1 and receipt['revision_hash'] == current['revision_hash']
    assert receipt['source_sha256'] == 'a' * 64
    assert receipt['registry_sha256'] == hashlib.sha256(registry.read_bytes()).hexdigest()
    assert receipt['expected_delta_sha256'] == hashlib.sha256((private / 'expected_delta.json').read_bytes()).hexdigest()
    assert receipt['goal_sheet_names'] == ['Sheet']  # Actual goal, not cached delta metadata.
    assert Path(receipt['receipt_path']).is_file()
    assert not (tmp_path / 'harbor_batches').exists()


def test_qualified_withdrawal_keeps_historical_proof_and_budgets(tmp_path, monkeypatch):
    factory, audit, calls, registry, export, private = fixture(tmp_path, monkeypatch)
    baseline = {p.name: p.read_bytes() for p in private.iterdir()}
    factory._validate_exports()
    original = deepcopy(task(audit, 'fm-late'))
    proof_bytes = {key: Path(value['result_file']).read_bytes()
                   for key, value in original['harbor_controls'].items()}
    register(registry)
    factory._validate_exports()
    factory._validate_exports()  # Rejected versions cannot be silently reopened.
    current = task(audit, 'fm-late')
    assert len(calls) == 1 and current['status'] == 'rejected'
    assert audit.snapshot()['metrics']['qualified'] == 0
    assert current['harbor_controls'] is None and current['harbor_export_binding'] is None
    assert current['historical_harbor_controls'] == original['harbor_controls']
    assert current['historical_harbor_export_binding'] == original['harbor_export_binding']
    assert current['native_risk_withdrawals'][0]['previous_status'] == 'qualified'
    for field in ['revision', 'revision_hash', 'content_repairs', 'evidence_rounds', 'infrastructure_retries']:
        assert current[field] == original[field]
    assert baseline == {p.name: p.read_bytes() for p in private.iterdir()}
    for key, value in original['harbor_controls'].items():
        assert Path(value['result_file']).read_bytes() == proof_bytes[key]
    summary = json.loads((tmp_path / 'harbor_controls.json').read_text())
    assert summary['per_task'] == {} and summary['export_bindings'] == {}
    assert summary['complete'] is False
    assert summary['native_risk_withdrawals'][0]['cumulative_controls'] == original['harbor_controls']
    assert len(summary['batches']) == 1


@pytest.mark.parametrize('risk', [
    {'cell': 'Z1'},  # A fixed/upstream/target-root cell outside actual D is not a defect in D.
    {'source': 'b' * 64},  # Source identity is a complete exact SHA, not a name/prefix.
    {'source': 'a' * 63},
    {'certainty': 'suspected'},
    {'sheet': 'IncorrectCachedName'},  # Cached sheet_names do not validate a nonexistent sheet.
])
def test_disjoint_or_unconfirmed_facts_preserve_qualified_proof(tmp_path, monkeypatch, risk):
    factory, audit, calls, registry, export, _ = fixture(tmp_path, monkeypatch)
    factory._validate_exports()
    original = deepcopy(task(audit, 'fm-late'))
    register(registry, **risk)
    factory._validate_exports()
    factory._validate_exports()
    current = task(audit, 'fm-late')
    assert len(calls) == 1 and current['status'] == 'qualified'
    assert export.is_dir()
    assert current['harbor_controls'] == original['harbor_controls']
    assert current['harbor_export_binding'] == original['harbor_export_binding']
    assert not current['preharbor_native_risk_guard']['blocking']
    assert current['preharbor_native_risk_guard']['registry_sha256'] != original['preharbor_native_risk_guard']['registry_sha256']
    # Identical rechecks are idempotent and still read the registry first.
    checks = [event for event in audit.events() if event['kind'] == 'preharbor.native_risk_checked']
    assert len(checks) == 2


def test_full_delta_catches_nonroot_downstream_cell(tmp_path, monkeypatch):
    factory, audit, calls, registry, _, _ = fixture(
        tmp_path, monkeypatch, changes={'Sheet!A1': {'input': 0, 'goal': 21}, 'Sheet!B9': {'input': 1, 'goal': 2}})
    register(registry, cell='B8:C10')
    factory._validate_exports()
    current = task(audit, 'fm-late')
    assert current['status'] == 'rejected' and not calls
    assert current['issues'][-1]['affected_cells'] == ['Sheet!B9']
    assert current['preharbor_native_risk_guard']['full_delta_size'] == 2


def test_missing_delta_is_unknown_and_does_not_invent_intersection(tmp_path, monkeypatch):
    factory, audit, calls, registry, _, private = fixture(tmp_path, monkeypatch)
    factory._validate_exports()
    original = deepcopy(task(audit, 'fm-late')['harbor_controls'])
    (private / 'expected_delta.json').unlink()
    register(registry)
    factory._validate_exports()
    current = task(audit, 'fm-late')
    assert current['status'] == 'qualified' and len(calls) == 1
    assert current['harbor_controls'] == original
    assert current['preharbor_native_risk_guard']['state'] == 'unknown'
    assert not current['preharbor_native_risk_guard']['blocking']
