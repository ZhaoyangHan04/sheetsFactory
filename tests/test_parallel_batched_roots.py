"""The parallel scheduler preserves actual batch evidence and failure accounting."""
from pathlib import Path
import threading

import openpyxl
import pytest

from sheets_factory.checkers.parallel_batched_roots import prove_parallel_batched_root_impacts
from sheets_factory.nodes.construction import construction_contract
from test_batched_root_impacts import case, ArithmeticFixtureEngine


def prove(case, **overrides):
    book = openpyxl.load_workbook(case['goal'])
    for edit in case['edits']:
        book[edit['sheet']][edit['cell']] = edit['after']
    raw = case['directory'] / 'combined_raw.xlsx'
    book.save(raw)
    book.close()
    combined = case['engine'].recalculate(raw, case['directory'] / 'combined.xlsx')
    case['engine'].calls.clear()
    args = dict(goal=case['goal'], combined_input=combined, edits=case['edits'],
        batches=case['batches'], engine=case['engine'], directory=case['directory'] / 'proof')
    args.update(overrides)
    before = case['goal'].read_bytes(), combined.read_bytes()
    result = prove_parallel_batched_root_impacts(**args)
    assert before == (case['goal'].read_bytes(), combined.read_bytes())
    return result


def test_independent_batches_really_overlap_and_both_contexts_remain_required(case):
    barrier, lock = threading.Barrier(2), threading.Lock()
    class ConcurrentFixtureEngine(ArithmeticFixtureEngine):
        def __init__(self):
            super().__init__()
            self.live, self.maximum = 0, 0

        def recalculate(self, source, destination):
            with lock:
                self.live += 1
                self.maximum = max(self.maximum, self.live)
            try:
                barrier.wait(timeout=5)
                return super().recalculate(source, destination)
            finally:
                with lock:
                    self.live -= 1
    engine = ConcurrentFixtureEngine()
    result = prove(case, engine=engine, concurrency=2)
    assert result['passed'] is True
    assert engine.maximum == 2
    assert result['actual_batch_LO_execution_count'] == result['actual_batch_LO_started_count'] == len(engine.calls) == 4
    assert result['individual_root_LO_executions'] == result['individual_marginal_LO_executions'] == 0
    assert [r['root_index'] for r in result['root_impacts']] == [0, 1, 2, 3]
    assert all(r['combined_marginal']['base'] == 'full_combined_mutation' for r in result['root_impacts'])
    assert all(r['combined_marginal']['edits_reversed'] for r in result['root_impacts'])


def test_full_context_inactive_root_rejects_entire_parallel_certificate(case):
    case['edits'][1]['after'] = '=C1+1+(C1-30)'
    result = prove(case, concurrency=2)
    assert not result['passed'] and result['root_impacts'] == []
    assert result['batches'][1]['individual']['passed'] is True
    assert result['batches'][1]['combined_marginal']['passed'] is False
    assert result['actual_batch_LO_execution_count'] == len(case['engine'].calls) == 4


def test_engine_failure_waits_for_started_work_and_preserves_failed_call_counts(case):
    class FailedFixtureEngine:
        def recalculate(self, source, destination):
            raise RuntimeError('explicit fixture engine failure')
    result = prove(case, engine=FailedFixtureEngine(), concurrency=2)
    assert result['state'] == 'execution_error'
    assert result['passed'] is False and result['root_impacts'] == []
    assert result['actual_batch_LO_execution_count'] == 0
    assert result['actual_batch_LO_started_count'] >= 1
    assert all(r['state'] in {'execution_error', 'not_started_after_failure'} for r in result['batches'])


def test_first_failure_stops_admitting_later_batches(case):
    result = prove(case, batches=[[0, 1], [2], [3]], concurrency=1)
    assert not result['passed']
    assert result['actual_batch_LO_execution_count'] == 1
    assert result['batches'][1]['state'] == result['batches'][2]['state'] == 'not_started_after_failure'


@pytest.mark.parametrize('value', [True, 0, 5, 1.5])
def test_invalid_parallel_limit_is_rejected_before_engine_calls(case, value):
    result = prove(case, concurrency=value)
    assert not result['passed'] and case['engine'].calls == []
    with pytest.raises(ValueError, match='root_impact_concurrency'):
        construction_contract('debugging', {'construction': {'root_impact_concurrency': value}})


def test_serial_execution_remains_the_default():
    assert construction_contract('debugging', {})['root_impact_concurrency'] == 1
