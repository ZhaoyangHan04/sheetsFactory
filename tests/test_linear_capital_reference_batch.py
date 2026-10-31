"""No-service checks for the fixed original-v1 batch and rejection retention."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from test_linear_capital_optimization_runtime import services

ROOT = Path(__file__).resolve().parents[1]
definition = importlib.util.spec_from_file_location('_reference_batch_test', ROOT/'scripts/run_linear_capital_reference_batch.py')
entry = importlib.util.module_from_spec(definition)
definition.loader.exec_module(entry)


@pytest.fixture
def synthetic_lineage(monkeypatch):
    """In-memory finance ancestry; no ignored private output is a test input."""
    original_read, original_ref = entry.read, entry.ref
    config = original_read(entry.DEFAULT_CONFIG); records = {}; values = {}
    def add(path, value, digest='a'*64):
        path = str(path); record = {'path': path, 'sha256': digest, 'bytes': 1}
        records[path] = record; values[path] = value; return record
    lineage = {key: add(entry.ROOT/config[key]['path'], {}, config[key]['sha256']) for key in
        ('raw_catalog', 'finance_terminal', 'finance_freeze', 'finance_accounting_correction')}
    raw = []; actual = []; frozen = []
    for i, pid in enumerate(entry.ORDER, 1):
        specification = add('/explicit_fake/'+pid+'/specification.json', {}, f'{i:064x}')
        preparation = add('/explicit_fake/'+pid+'/preparation.json', {})
        terminal = add('/explicit_fake/'+pid+'/terminal.json', {'passed': True})
        worker = add('/explicit_fake/'+pid+'/worker.json', {'passed': True, 'terminal': terminal})
        raw.append({'profile_id': pid, 'specification': specification, 'raw_preparation': preparation})
        actual.append({'profile_id': pid, 'worker_terminal': worker, 'passed': True, 'returncode': 0})
        frozen.append({'profile_id': pid, 'terminal': terminal})
    values[lineage['raw_catalog']['path']] = {'profile_order': entry.ORDER, 'profiles': raw}
    values[lineage['finance_terminal']['path']] = {'passed': True, 'profile_order': entry.ORDER, 'profiles': actual}
    values[lineage['finance_freeze']['path']] = {'passed': True, 'profile_order': entry.ORDER,
        'profiles': frozen, 'terminal': lineage['finance_terminal']}
    values[lineage['finance_accounting_correction']['path']] = {'prior_terminal': lineage['finance_terminal'],
        'prior_freeze': lineage['finance_freeze'], 'corrected_total_implementation_universe_calls': 80,
        'additional_financial_forwards_by_correction': 0}
    def read(value):
        path = value['path'] if isinstance(value, dict) else str(value)
        return deepcopy(values[path]) if path in values else original_read(value)
    def reference(value):
        return records[str(value)] if str(value) in records else original_ref(value)
    monkeypatch.setattr(entry, 'read', read); monkeypatch.setattr(entry, 'ref', reference)


def test_fixed_configuration_binds_original_api_and_corrected_finance_without_services(monkeypatch, synthetic_lineage):
    monkeypatch.setattr(entry.api.runtime, '_command', lambda *_a, **_k: pytest.fail('No Docker'))
    config, lineage = entry.checked_config(entry.DEFAULT_CONFIG)
    inventory = entry.checked_inventory(config, lineage)
    assert [p['profile_id'] for p in inventory] == entry.ORDER
    assert len({p['specification']['sha256'] for p in inventory}) == 20
    assert config['reference_policy'] == 'original_v1_best_and_complete_winner_excluded_runner_OPTIMAL'
    assert entry.read(lineage['finance_accounting_correction'])['corrected_total_implementation_universe_calls'] == 80


@pytest.mark.parametrize('field,value', [
    ('profile_order', list(reversed(entry.ORDER))), ('profile_order', entry.ORDER[:-1]),
    ('max_parallel', 5), ('retries', 1), ('retries', False),
    ('reference_policy', 'uniqueness_bound'), ('original_api_sha256', '0'*64),
])
def test_config_rejects_filtering_retuning_retries_and_policy_changes(tmp_path, field, value):
    config = entry.read(entry.DEFAULT_CONFIG); config[field] = value
    path = tmp_path/'changed.json'; path.write_text(json.dumps(config))
    with pytest.raises(ValueError): entry.checked_config(path)


@pytest.mark.parametrize('fault', ['finance_order', 'freeze_missing', 'correction_count', 'correction_ancestry'])
def test_inventory_rejects_incomplete_or_misbound_finance(monkeypatch, fault, synthetic_lineage):
    config, lineage = entry.checked_config(entry.DEFAULT_CONFIG)
    target = 'finance_terminal' if fault == 'finance_order' else 'finance_freeze' if fault == 'freeze_missing' else 'finance_accounting_correction'
    altered = deepcopy(entry.read(lineage[target]))
    if fault == 'finance_order': altered['profiles'].reverse()
    elif fault == 'freeze_missing': altered['profiles'].pop()
    elif fault == 'correction_count': altered['corrected_total_implementation_universe_calls'] = 40
    else: altered['prior_terminal'] = lineage['raw_catalog']
    original_read = entry.read
    monkeypatch.setattr(entry, 'read', lambda value: altered if value == lineage[target] else original_read(value))
    with pytest.raises(ValueError): entry.checked_inventory(config, lineage)


def test_nonoptimal_original_terminal_is_retained_without_cold_pass_or_retry(monkeypatch, tmp_path):
    output = tmp_path/'run'; folder = output/'profiles/P01'; folder.mkdir(parents=True)
    entry.write(output/'prospective.json', {'explicit_fake_boundary': True})
    monkeypatch.setattr(entry, 'validate', lambda *_a, **_k: {})
    calls = []
    def execute(actual):
        calls.append(actual)
        return entry.write(folder/'terminal.json', {'passed': False, 'error_type': 'ValueError',
            'error': 'Original best was FEASIBLE; OPTIMAL required'})
    monkeypatch.setattr(entry.api, 'execute_prepared', execute)
    monkeypatch.setattr(entry.api, 'validate_completed', lambda *_a: pytest.fail('No cold pass for rejected reference'))
    assert entry.worker(output, 'P01') == 1
    result = entry.read(folder/'worker_terminal.json')
    assert result['passed'] is False and result['retry_authorized'] is False
    assert result['terminal'] == entry.ref(folder/'terminal.json') and calls == [folder]
    with pytest.raises(ValueError): entry.worker(output, 'P01')


def test_batch_dispatches_all_twenty_once_at_four_and_retains_rejection(monkeypatch, tmp_path):
    output = tmp_path/'run'; output.mkdir()
    entry.write(output/'prospective.json', {'explicit_fake_boundary': True})
    for pid in entry.ORDER: (output/'profiles'/pid).mkdir(parents=True)
    frozen = {'lineage': {'finance_accounting_correction': entry.ref(output/'prospective.json')}}
    monkeypatch.setattr(entry, 'validate', lambda *_a, **_k: frozen)
    state = services(monkeypatch); launched = []; active = set(); peak = []
    class Process:
        def __init__(self, command, **kwargs):
            assert command[2:4] == ['worker', '--prepared']
            self.profile = command[-1]; self.pid = 1000+len(launched); self.polls = 0
            assert self.profile not in launched
            launched.append(self.profile); active.add(self.profile); peak.append(len(active))
            entry.write(output/'profiles'/self.profile/'worker_terminal.json', {
                'passed': self.profile != 'P03', 'explicit_fake_boundary': True, 'elapsed_seconds': 1})
        def poll(self):
            self.polls += 1
            if self.polls == 1: return None
            active.discard(self.profile)
            return int(self.profile == 'P03')
        def wait(self): return self.poll()
    monkeypatch.setattr(entry.subprocess, 'Popen', Process)
    monkeypatch.setattr(entry.time, 'sleep', lambda _: None)
    monkeypatch.setattr(entry, 'owned_jobs', lambda _folder, **_kwargs: {})
    result = entry.read(entry.execute(output))
    assert launched == entry.ORDER and max(peak) == 4 and not active
    assert result['profile_order'] == [p['profile_id'] for p in result['profiles']] == entry.ORDER
    assert result['rejected_profiles'] == ['P03'] and len(result['accepted_profiles']) == 19
    assert result['passed'] is False and result['retries'] == 0
    assert state['released'] and state['closed'] and state['stopped']
    with pytest.raises(ValueError): entry.execute(output)


def test_owned_identity_rejects_partial_id_and_keeps_both_phase_receipts(tmp_path):
    for phase, cid in [('best', 'a'*64), ('runner', 'b'*64)]:
        folder = tmp_path/'jobs'/phase; folder.mkdir(parents=True)
        entry.write(folder/'started.json', {'explicit_fake_boundary': True})
        entry.write(folder/'host_before.json', {'Id': cid})
        entry.write(folder/'terminal.json', {'explicit_fake_boundary': True})
    jobs = entry.owned_jobs(tmp_path)
    assert list(jobs) == ['best', 'runner'] and jobs['runner']['container_id'] == 'b'*64
    (tmp_path/'jobs/runner/host_before.json').write_text(json.dumps({'Id': 'b'*12}))
    with pytest.raises(ValueError): entry.owned_jobs(tmp_path)
    with pytest.raises(ValueError): entry.owned_jobs(tmp_path, tolerate_partial=True)
    (tmp_path/'jobs/runner/host_before.json').write_text('{"Id":')
    assert 'container_id' not in entry.owned_jobs(tmp_path, tolerate_partial=True)['runner']
    with pytest.raises(json.JSONDecodeError): entry.owned_jobs(tmp_path)
