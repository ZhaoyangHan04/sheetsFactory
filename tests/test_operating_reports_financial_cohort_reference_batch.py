"""Exercise durable batch ordering and failure retention without financial forwards."""
from collections import Counter
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def batch(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('_cohort_reference_batch_test',
        ROOT/'scripts/run_operating_reports_financial_cohort_reference_batch.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    state = {'raw_calls': 0, 'validated': False, 'fail_forward': None, 'fail_comparison': None}
    monkeypatch.setattr(module, 'RESERVATION_ROOT', tmp_path/'permanent')
    monkeypatch.setattr(module.schema, 'recipes', lambda: {})
    monkeypatch.setattr(module.excel, 'recipes', lambda: {})

    class Panel:
        def __init__(self, *args, **kwargs): pass
        def start(self):
            calls.append(('panel', 'started'))
            return 'http://127.0.0.1:1/'
        def stop(self): calls.append(('panel', 'stopped'))

    monkeypatch.setattr(module, 'DashboardServer', Panel)

    def freeze(output):
        assert calls[0] == ('panel', 'started')
        state['raw_calls'] += 1
        output.mkdir()
        cases = []
        for index in range(1, 10):
            identity = f'FM-C{index:02d}'
            public = {'case_id': identity, 'seed': 202711200+index}
            record = module.write(output/(identity+'.json'), public)
            cases.append({'candidate_id': identity, 'specification': record})
        return module.write(output/'raw_inventory.json', {'cases': cases})

    def validate(record):
        inventory = json.loads(Path(record['path']).read_text())
        assert len(inventory['cases']) == 9
        publics = {row['candidate_id']: json.loads(Path(row['specification']['path']).read_text())
                   for row in inventory['cases']}
        assert all(Path(row['specification']['path']).is_file() for row in inventory['cases'])
        state['validated'] = True
        return {'inventory': inventory, 'specifications': publics}

    monkeypatch.setattr(module.raw, 'freeze_all', freeze)
    monkeypatch.setattr(module.raw, 'validate_all', validate)

    def solver(implementation):
        def solve(public, *, raw_inventory):
            assert state['raw_calls'] == 1 and state['validated']
            assert len(json.loads(Path(raw_inventory['path']).read_text())['cases']) == 9
            calls.append((implementation, public['case_id']))
            if state['fail_forward'] == (implementation, public['case_id']):
                raise ValueError('TEST_ONLY retained independent failure')
            return {'case_id': public['case_id'], 'implementation': implementation}
        return solve

    monkeypatch.setattr(module.oracles, 'solve_A', solver('A'))
    monkeypatch.setattr(module.oracles, 'solve_B', solver('B'))

    def compare(public, left, right):
        assert left == {'case_id': public['case_id'], 'implementation': 'A'}
        assert right == {'case_id': public['case_id'], 'implementation': 'B'}
        calls.append(('compare', public['case_id']))
        return {'passed': state['fail_comparison'] != public['case_id'],
                'differences': ['TEST_ONLY mismatch'] if state['fail_comparison'] == public['case_id'] else []}

    def emit(public, output):
        calls.append(('emit', public['case_id']))
        output.mkdir()
        return module.write(output/'receipt.json', {'case_id': public['case_id'], 'TEST_ONLY': True})

    monkeypatch.setattr(module, 'full_compare', compare)
    monkeypatch.setattr(module.excel, 'emit', emit)
    return module, calls, state


def read(record):
    return json.loads(Path(record['path']).read_text())


def test_all_nine_frozen_before_each_once_forward_and_stored_receipts_join(batch, tmp_path):
    module, calls, state = batch
    result = read(module.run(tmp_path/'batch'))
    assert result['passed'] is True and result['passed_cases'] == 9
    assert result['financial_forwards_started'] == 18
    assert result['actual_LO_calls'] == result['actual_model_calls'] == 0
    assert Counter(name for name, _ in calls) == {'panel': 2, 'A': 9, 'B': 9, 'compare': 9, 'emit': 9}
    assert state['raw_calls'] == 1
    for row in result['cases']:
        comparison = read(row['comparison'])
        assert comparison['new_financial_forwards'] == 0
        assert comparison['A'] == row['forwards']['A'] and comparison['B'] == row['forwards']['B']
        for implementation in ('A', 'B'):
            receipt = read(row['forwards'][implementation])
            started = read(receipt['started'])
            assert receipt['case_id'] == started['case_id'] == row['case_id']
            assert receipt['implementation'] == started['implementation'] == implementation
            assert receipt['financial_forward_calls'] == started['financial_forward_limit'] == 1
            assert receipt['outer_retries'] == started['outer_retries'] == 0
            assert receipt['raw_inventory'] == started['raw_inventory'] == result['raw_inventory']


def test_independent_failure_is_retained_and_not_retried_or_replaced(batch, tmp_path):
    module, calls, state = batch
    state['fail_forward'] = ('A', 'FM-C02')
    result = read(module.run(tmp_path/'batch'))
    assert result['passed'] is False and result['passed_cases'] == 8
    assert result['financial_forwards_started'] == 18
    assert calls.count(('A', 'FM-C02')) == calls.count(('B', 'FM-C02')) == 1
    assert ('emit', 'FM-C02') not in calls
    failure = json.loads((tmp_path/'batch/FM-C02/independent_A/failure.json').read_text())
    assert failure['retry_permitted'] is False and failure['financial_forward_calls'] == 1


def test_stored_disagreement_keeps_both_first_results_and_skips_emission(batch, tmp_path):
    module, calls, state = batch
    state['fail_comparison'] = 'FM-C03'
    result = read(module.run(tmp_path/'batch'))
    row = result['cases'][2]
    assert result['passed_cases'] == 8 and row['passed'] is False
    assert set(row['forwards']) == {'A', 'B'}
    assert ('emit', 'FM-C03') not in calls
    assert calls.count(('compare', 'FM-C03')) == 1
    assert Path(row['failure']['path']).is_file()


def test_renaming_output_cannot_repeat_the_same_cohort(batch, tmp_path):
    module, calls, state = batch
    module.run(tmp_path/'first')
    previous = list(calls)
    with pytest.raises(FileExistsError):
        module.run(tmp_path/'renamed')
    assert state['raw_calls'] == 1
    assert calls[len(previous):] == [('panel', 'started'), ('panel', 'stopped')]
    retained = json.loads((tmp_path/'renamed/batch_failure.json').read_text())
    assert retained['financial_forwards_started'] == 0 and retained['retry_permitted'] is False
