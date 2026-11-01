"""Pure batch wiring, real exports and permanent reservations, without models."""
from contextlib import contextmanager
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

from sheets_factory.evaluation.thread_capped_harbor_export import export_resource_harbor

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def entry(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location('_factory_frontier_test', ROOT / 'scripts/run_operating_reports_factory_frontier.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    @contextmanager
    def monitor(*args, **kwargs):
        yield SimpleNamespace(task=lambda *a, **k: None, update_run=lambda *a, **k: None, export=lambda: None)

    monkeypatch.setattr(m, 'monitor', monitor)
    monkeypatch.setattr(m, 'RESERVATIONS', tmp_path / 'permanent')
    monkeypatch.setattr(m, 'OLD_RESERVATIONS', (tmp_path / 'old_permanent',))
    monkeypatch.setattr(m.runner, 'execute_evaluation', lambda *a, **k: pytest.fail('No native model in pure tests'))
    return m


@pytest.fixture
def batch(entry, tmp_path):
    m = entry
    goal = tmp_path / 'goal.xlsx'
    w = openpyxl.Workbook()
    w.active['A1'] = 'Public facts'
    w.active['B1'] = 100
    w.save(goal)
    w.close()

    def build(name='batch', counts=(2, 1), offset=0):
        folder = tmp_path / name
        plans = [{'mode': mode, 'plan': {'variant_id': f'{mode}-{i}'}}
                 for mode, count in zip(m.MODES, counts) for i in range(count)]
        frozen = m.write(folder / 'plans.json', {'execution_budget': m.BUDGET,
            'runtime_profile': m.ref(m.PROFILE), 'plans': plans})
        tasks = []
        for mode, count in zip(m.MODES, counts):
            for i in range(count):
                key = f'{name}-{mode}-{i}'
                base = folder / key
                (base / 'material/public').mkdir(parents=True)
                (base / 'material/private').mkdir()
                w = openpyxl.Workbook()
                w.active['A1'] = 'Public facts'
                w.active['B1'] = i + offset
                w.save(base / 'material/public/input.xlsx')
                w.close()
                (base / 'material/private/goal.xlsx').write_bytes(goal.read_bytes())
                (base / 'material/public/instruction.md').write_text('Complete the financial schedule. Save /app/output.xlsx.')
                audit = base / 'cap.json'
                export = export_resource_harbor(base / 'material', folder / 'SpreadsheetEval' / key,
                    {'task_id': key, 'mode': mode, 'revision': 0, 'revision_hash': 'a' * 64},
                    ROOT, runtime_profile=m.PROFILE, audit_path=audit)
                engineering = m.write(base / 'individual.json', {'TEST_ONLY': True, 'passed': True,
                    'native_error_count': 0, 'given_literals_unchanged': True, 'sheet_structure_unchanged': True,
                    'complete_primary_difference_count': 1, 'complete_primary_difference': ['Sheet!B1']})
                tasks.append({'task_id': key, 'mode': mode, 'revision': 0, 'revision_hash': 'a' * 64,
                    'source_id': m.ref(goal)['sha256'], 'task_directory': str(export),
                    'harbor_export_binding': m.inspect_resource_export(export, audit_path=audit),
                    'execution_budget': deepcopy(m.BUDGET), 'variant_id': f'{mode}-{i}',
                    'individual_engineering': engineering, 'worker_cap_audit': m.ref(audit), 'plan_freeze': frozen})
        record = m.write(folder / 'batch.json', {'kind': 'individually_engineered_operating_report_batch',
            'version': 1, 'count': len(tasks), 'tasks': tasks, 'selected_task_ids': [t['task_id'] for t in tasks]})
        return SimpleNamespace(ref=record, tasks=tasks, folder=folder, goal=goal)
    return build


def test_real_exports_source_v6_and_shared_goal_identity_cache(entry, batch, monkeypatch, tmp_path):
    m = entry
    b = batch()
    helper = m.helper()
    original = helper.workbook_identity
    calls = []
    def count(path, **kwargs):
        calls.append((m.ref(path)['sha256'], kwargs.get('formulas', False)))
        return original(path, **kwargs)
    monkeypatch.setattr(helper, 'workbook_identity', count)
    out = tmp_path / 'prepared'
    f = m.read(m.prepare([b.ref], out))
    source = m.read(f['source'])
    assert source['tool_time_policy_version'] == 6 and source['tool_time_policy'] == m.runner.POLICY_V6
    assert source['execution_budget'] == m.BUDGET and not source['qualified']
    assert calls.count((m.ref(b.goal)['sha256'], False)) == 1
    before = len(calls)
    assert m.validate_prepared(out) == f and len(calls) == before
    m._SESSIONS.clear()
    assert m.validate_prepared(out) == f and len(calls) > before
    selection = m.runner.freeze_selection(f['source']['path'], tmp_path / 'native_snapshot', phase='development')
    assert len(selection['tasks']) == 3 and selection['n_attempts'] == 1
    assert selection['infrastructure_retry_policy']['max_retries'] == 0
    assert selection['model'] == 'gpt-6.1-sol' and selection['reasoning_effort'] == 'xhigh'
    assert selection['tool_time_policy_version'] == 6 and selection['timeout_seconds'] == 14400


@pytest.mark.parametrize('change', ['export', 'budget', 'native_errors', 'incomplete_delta', 'goal', 'plan'])
def test_changed_or_unsupported_task_rejects_before_models(entry, batch, tmp_path, change):
    m = entry
    b = batch()
    task = b.tasks[0]
    if change == 'export':
        (Path(task['task_directory']) / 'instruction.md').write_text('Changed instruction')
    elif change == 'budget':
        task['execution_budget']['tool_budget_seconds'] = 2000
    elif change in ('native_errors', 'incomplete_delta'):
        doc = m.read(task['individual_engineering'])
        doc['native_error_count' if change == 'native_errors' else 'complete_primary_difference_count'] = 2
        task['individual_engineering'] = m.write(b.folder / 'different_individual.json', doc)
    elif change == 'goal':
        task['source_id'] = '0' * 64
    else:
        doc = m.read(task['plan_freeze'])
        doc['plans'] = []
        task['plan_freeze'] = m.write(b.folder / 'other_plan.json', doc)
    with pytest.raises(ValueError):
        m.check_task(task)


def test_alias_material_phase_reservations_and_old_registry_remain_decisive(entry, batch, tmp_path):
    m = entry
    a, b = batch('one'), batch('renamed')
    ar = m.prepare([a.ref], tmp_path / 'one_prepared')
    br = m.prepare([b.ref], tmp_path / 'renamed_prepared')
    left, right = m.read(ar), m.read(br)
    assert {v['sha256'] for v in left['materials'].values()} == {v['sha256'] for v in right['materials'].values()}
    reservations = m.reserve(ar, left)
    assert len(reservations) == 3
    with pytest.raises(ValueError, match='already reserved'):
        m.reserve(br, right)
    c = batch('old', offset=10)
    cr = m.prepare([c.ref], tmp_path / 'old_prepared')
    frozen = m.read(cr)
    identity = next(iter(frozen['materials'].values()))
    m.write(m.OLD_RESERVATIONS[0] / (identity['sha256'] + '.json'), {'retained': 'earlier actual attempt'})
    with pytest.raises(ValueError, match='earlier development'):
        m.reserve(cr, frozen)


def test_confirmation_freezes_exact20_with_bound_development(entry, batch, tmp_path):
    m = entry
    b = batch('full', (10, 10))
    dev = m.read(m.prepare([b.ref], tmp_path / 'development'))
    selection = m.write(tmp_path / 'selection.json', {'TEST_ONLY': 'retained selection'})
    evaluation = m.write(tmp_path / 'evaluation.json', {'TEST_ONLY': 'retained actual results'})
    terminal = m.write(tmp_path / 'development_terminal.json', {'kind': m.TERMINAL_KIND, 'phase': 'development',
        'selection': selection, 'evaluation': evaluation,
        'results': [{'material_identity': identity, 'actual_attempt': {'TEST_ONLY': 'one recorded attempt'}}
                    for identity in dev['materials'].values()]})
    frozen = m.read(m.prepare([b.ref], tmp_path / 'confirmation', phase='confirmation', development=terminal))
    assert len(frozen['tasks']) == 20 and frozen['selection_frozen_before_model']
    assert not frozen['qualified'] and frozen['development'] == terminal
    m.reserve(m.ref(tmp_path / 'confirmation/prepared.json'), frozen)
    with pytest.raises(ValueError, match='already reserved'):
        m.reserve(m.ref(tmp_path / 'confirmation/prepared.json'), frozen)
    with pytest.raises(ValueError, match='exactly ten'):
        m.prepare([b.ref], tmp_path / 'too_few', phase='confirmation',
                  task_ids=[t['task_id'] for t in b.tasks[:-1]], development=terminal)


@pytest.mark.parametrize('raw,failure,timing,valid,effective,state', [
    (0, None, True, True, 0, 'complete'), (1, None, True, True, 1, 'complete'),
    (1, 'cumulative_tool_budget_exhausted', False, True, 0, 'known_tool_budget_failure'),
    (0, 'incomplete_tool_timing', None, True, None, 'unknown'),
    (0, None, True, False, None, 'unknown'), (None, 'environment_failure', True, True, None, 'unknown'),
])
def test_individual_raw_clock_and_resource_layers_stay_distinct(entry, raw, failure, timing, valid, effective, state):
    score = entry.effective_score({'raw_verifier_reward': raw, 'status': 'scored',
        'failure_kind': failure, 'tool_time': {'passed': timing}}, {'passed': valid, 'complete': valid})
    assert score['raw_verifier_reward'] == raw and score['effective_reward'] == effective and score['state'] == state


def test_run_uses_one_batch_observer_and_preserves_valid_sibling_results(entry, batch, monkeypatch, tmp_path):
    m = entry
    b = batch('run_fixture', (1, 0))
    out = tmp_path / 'run_prepared'
    m.prepare([b.ref], out)
    observed = []
    class Observer:
        def __init__(self, directory):
            self.directory = directory
            self.receipt = None
        def __enter__(self):
            observed.append(self.directory)
            return self
        def __exit__(self, *args):
            self.receipt = m.write(out / 'TEST_ONLY_observer.json', {'mock': 'no Docker'})

    trials = []
    def native(source, directory, **kwargs):
        assert kwargs['concurrency'] == 16 and callable(kwargs['execute'])
        selection = m.runner.freeze_selection(source, directory, phase=kwargs['phase'])
        result = m.write(directory / 'TEST_ONLY_result.json', {'mock': 'no model'})
        trials.append({'result': result, 'passed': True, 'complete': True})
        evaluation = {'status': 'infrastructure_failed', 'failure_kind': 'sibling_infrastructure_example',
            'attempts': [{'task_id': selection['tasks'][0]['task_id'], 'result_sha256': result['sha256'],
                'result_file': result['path'], 'status': 'scored', 'raw_verifier_reward': 0,
                'failure_kind': None, 'tool_time': {'passed': True}}], 'infrastructure_retries': []}
        m.write(directory / 'evaluation_manifest.json', evaluation)
        return evaluation

    monkeypatch.setattr(m, 'ResourceObserver', Observer)
    monkeypatch.setattr(m.runner, 'run_evaluation', native)
    monkeypatch.setattr(m, 'validate_observation_receipt', lambda *a: {'passed': True, 'complete': True, 'trials': trials})
    result = m.read(m.run(out))
    assert observed == [out / 'evaluation']
    assert result['results'][0]['score']['effective_reward'] == 0
    assert result['results'][0]['resources']['result'] == trials[0]['result']
    assert not result['qualified'] and not result['normal_quality_transferred'] and result['outer_retries'] == 0
