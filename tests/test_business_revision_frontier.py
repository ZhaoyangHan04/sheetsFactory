"""Fresh-source native development wiring; no services or model execution."""
from contextlib import contextmanager
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


OLD_TESTS = load(ROOT/'tests/test_operating_reports_factory_frontier.py', '_business_revision_fixture_helpers')


@pytest.fixture
def entry(monkeypatch, tmp_path):
    m = load(ROOT/'scripts/run_business_revision_frontier.py', '_business_revision_test')
    @contextmanager
    def monitor(*args, **kwargs):
        yield SimpleNamespace(task=lambda *a, **k: None, update_run=lambda *a, **k: None, export=lambda: None)
    monkeypatch.setitem(m._N, 'monitor', monitor)
    monkeypatch.setitem(m._N, 'RESERVATIONS', tmp_path/'permanent')
    monkeypatch.setitem(m._N, 'OLD_RESERVATIONS', (tmp_path/'old_permanent',))
    monkeypatch.setattr(m.runner, 'execute_evaluation', lambda *a, **kw: pytest.fail('No model in pure tests'))
    return m


@pytest.fixture
def batch(entry, tmp_path):
    legacy = OLD_TESTS.batch.__wrapped__(entry, tmp_path)
    def build(name='batch', counts=(5, 5), offset=0):
        result = legacy(name, counts, offset)
        record = entry.read(result.ref)
        record['kind'] = entry.BATCH_KIND
        result.ref = entry.write(result.folder/'business_revision_batch.json', record)
        return result
    return build


def test_real_new_goal_batches_freeze_all10_without_old_source_identity(entry, batch, tmp_path):
    left = batch('new_source_a', (5, 0))
    book = openpyxl.load_workbook(left.goal)
    book.active['B1'] = 350
    book.save(left.goal); book.close()
    right = batch('new_source_b', (0, 5))
    assert left.tasks[0]['source_id'] != right.tasks[0]['source_id']
    out = tmp_path/'prepared'
    prepared = entry.read(entry.prepare([left.ref, right.ref], out))
    assert prepared['kind'] == entry.KIND and prepared['phase'] == 'development'
    assert len(prepared['tasks']) == 10 and len(prepared['materials']) == 10
    assert {r['source_id'] for r in prepared['tasks']} == {left.tasks[0]['source_id'], right.tasks[0]['source_id']}
    assert entry.read(prepared['source'])['kind'] == entry.SOURCE_KIND
    assert prepared['recipe']['frozen_generic_base']['sha256'] == entry.BASE_SHA
    assert not prepared['qualified'] and prepared['model_calls'] == prepared['LO_calls'] == 0
    assert entry.validate_prepared(out) == prepared
    selection = entry.runner.freeze_selection(prepared['source']['path'], tmp_path/'selection', phase='development')
    assert selection['model'] == 'gpt-6.1-sol' and selection['reasoning_effort'] == 'xhigh'
    assert selection['tool_time_policy_version'] == 6 and selection['n_attempts'] == 1
    assert selection['execution_budget'] == entry.BUDGET and selection['timeout_seconds'] == 14400
    assert selection['infrastructure_retry_policy']['max_retries'] == 0


@pytest.mark.parametrize('count', [0, 9, 21])
def test_small_batch_contract_rejects_unfrozen_candidate_counts_before_export(entry, tmp_path, count):
    record = entry.write(tmp_path/f'count-{count}.json', {'kind': entry.BATCH_KIND, 'version': 1,
        'count': count, 'tasks': [{'task_id': str(i)} for i in range(count)],
        'selected_task_ids': [str(i) for i in range(count)]})
    with pytest.raises(ValueError, match='ten through twenty'):
        entry.prepare([record], tmp_path/'never-created')


def test_old_batch_kind_cannot_masquerade_as_new_business_revision(entry, batch, tmp_path):
    b = batch(); doc = entry.read(b.ref); doc['kind'] = 'individually_engineered_operating_report_batch'
    legacy = entry.write(tmp_path/'legacy.json', doc)
    with pytest.raises(ValueError, match='new business-revision'):
        entry.prepare([legacy], tmp_path/'never-prepared')


@pytest.mark.parametrize('fault', ['goal', 'budget', 'errors', 'scope', 'facts', 'export', 'plan'])
def test_new_source_cannot_bypass_original_material_and_engineering_checks(entry, batch, fault):
    b = batch(); task = deepcopy(b.tasks[0])
    if fault == 'goal': task['source_id'] = 'wrong'
    elif fault == 'budget': task['execution_budget']['tool_budget_seconds'] = 1801
    elif fault == 'export': (Path(task['task_directory'])/'instruction.md').write_text('Changed after export')
    elif fault == 'plan':
        data = entry.read(task['plan_freeze']); data['plans'] = []
        task['plan_freeze'] = entry.write(b.folder/'changed-plan.json', data)
    else:
        data = entry.read(task['individual_engineering'])
        if fault == 'errors': data['native_error_count'] = 1
        elif fault == 'scope': data['complete_primary_difference_count'] = 2
        else: data['given_literals_unchanged'] = False
        task['individual_engineering'] = entry.write(b.folder/'changed-audit.json', data)
    with pytest.raises(ValueError): entry.check_task(task)


def test_new_namespace_keeps_shared_factory_permanent_reservations(entry, batch, tmp_path):
    b = batch(); prepared_ref = entry.prepare([b.ref], tmp_path/'prepared')
    prepared = entry.read(prepared_ref)
    old = load(entry.BASE, '_business_revision_original_reservation_test')
    old.RESERVATIONS = entry._N['RESERVATIONS']; old.OLD_RESERVATIONS = entry._N['OLD_RESERVATIONS']
    # An earlier factory entry can reserve the same logical material. The new
    # namespace must see that exact shared phase slot, regardless of task names.
    old.reserve(prepared_ref, prepared)
    with pytest.raises(ValueError, match='already reserved'):
        entry._N['reserve'](prepared_ref, prepared)


def test_cold_validation_rejects_changed_export_and_confirmation_phase(entry, batch, tmp_path):
    b = batch(); out = tmp_path/'prepared'; prepared_ref = entry.prepare([b.ref], out)
    frozen = entry.read(prepared_ref)
    frozen['phase'] = 'confirmation'
    (out/'prepared.json').write_text(entry._N['json'].dumps(frozen))
    with pytest.raises(ValueError, match='development phase only'):
        entry.validate_prepared(out)


def test_private_clone_preserves_frozen_runtime_and_original_namespaces(entry):
    old = load(entry.BASE, '_business_revision_original_code_test')
    assert old.KIND == 'prepared_operating_reports_factory_frontier_v6'
    assert entry._N['KIND'] == entry.KIND
    assert entry._BASE_RUN.__code__.co_code == old.run.__code__.co_code
    assert entry.effective_score.__code__.co_code == old.effective_score.__code__.co_code
    assert entry._N is not old.prepare.__globals__
    assert old.RESERVATIONS == ROOT/'outputs/difficulty/.factory_native_phase_reservations_v1'
    assert entry.recipes()['frozen_generic_base']['sha256'] == entry.BASE_SHA


@pytest.mark.parametrize('reward,failure,timing,valid,effective', [
    (0, None, True, True, 0), (1, None, True, True, 1),
    (1, 'cumulative_tool_budget_exhausted', False, True, 0),
    (0, 'native_tool_timing_incomplete', None, True, None),
    (0, None, True, False, None)])
def test_resource_timing_unknowns_never_become_model_zeros(entry, reward, failure, timing, valid, effective):
    row = entry.effective_score({'status': 'scored', 'raw_verifier_reward': reward,
        'failure_kind': failure, 'tool_time': {'passed': timing}}, {'passed': valid, 'complete': valid})
    assert row['effective_reward'] is effective


def test_one_observer_single_native_dispatch_retains_missing_sibling_unknown(entry, batch, tmp_path, monkeypatch):
    b = batch(); out = tmp_path/'prepared'; entry.prepare([b.ref], out)
    observed = []; trials = []
    class Observer:
        def __init__(self, directory): self.directory = directory; self.receipt = None
        def __enter__(self): observed.append(self.directory); return self
        def __exit__(self, *args): self.receipt = entry.write(out/'mock_observer.json', {'TEST_ONLY': True})
    def native(source, directory, **kw):
        assert kw['concurrency'] == 10
        selection = entry.runner.freeze_selection(source, directory, phase=kw['phase'])
        attempts = []
        for task in selection['tasks'][:-1]:
            result = entry.write(directory/(task['task_id']+'.json'), {'TEST_ONLY': True, 'task_id': task['task_id']})
            trials.append({'result': result, 'passed': True, 'complete': True})
            attempts.append({'task_id': task['task_id'], 'result_sha256': result['sha256'],
                'status': 'scored', 'raw_verifier_reward': 0, 'failure_kind': None, 'tool_time': {'passed': True}})
        evaluation = {'status': 'infrastructure_failed', 'failure_kind': 'one_missing_sibling',
            'attempts': attempts, 'infrastructure_retries': []}
        entry.write(directory/'evaluation_manifest.json', evaluation)
        return evaluation
    monkeypatch.setitem(entry._N, 'ResourceObserver', Observer)
    monkeypatch.setattr(entry.runner, 'run_evaluation', native)
    monkeypatch.setitem(entry._N, 'validate_observation_receipt', lambda *a: {'passed': True, 'complete': True, 'trials': trials})
    terminal = entry.read(entry.run(out))
    assert observed == [out/'evaluation'] and terminal['kind'] == entry.TERMINAL_KIND
    assert len(terminal['results']) == 10 and terminal['outer_retries'] == 0
    assert sum(r['score']['effective_reward'] == 0 for r in terminal['results']) == 9
    assert sum(r['score']['effective_reward'] is None for r in terminal['results']) == 1
    assert not terminal['qualified'] and not terminal['normal_quality_transferred']
