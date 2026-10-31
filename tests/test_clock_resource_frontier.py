"""Only a new explicit selection can use the conservative complete-clock route."""
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import openpyxl
import pytest

from sheets_factory.evaluation import frontier, resource_frontier as resource
from sheets_factory.evaluation import clock_resource_frontier as v3
from sheets_factory.evaluation.resource_harbor import export_resource_harbor, inspect_resource_export
from sheets_factory.evaluation.tool_time_bounds import POLICY_V2

ROOT = Path(__file__).resolve().parents[1]
BUDGET = {'version': 1, 'elapsed_policy': 'operational_guard', 'elapsed_guard_seconds': 14400, 'tool_budget_seconds': 1800}


@pytest.fixture
def exported(tmp_path):
    task = tmp_path/'actual'; (task/'public').mkdir(parents=True); (task/'private').mkdir()
    book = openpyxl.Workbook(); book.active['A1'] = 10
    book.save(task/'public/input.xlsx'); book.active['A1'] = 20
    book.save(task/'private/goal.xlsx'); book.close()
    (task/'public/instruction.md').write_text('Set the supplied number to twenty. Save /app/output.xlsx.')
    output = tmp_path/'export/task-one'
    export_resource_harbor(task, output, {'task_id': 'task-one', 'revision': 0, 'revision_hash': 'fixture',
        'mode': 'debugging'}, runtime_profile=ROOT/'config/runtime_profiles/entity_group_large_v2.yaml')
    manifest = {'selected_task_ids': ['task-one'], 'execution_budget': deepcopy(BUDGET),
        'tool_time_policy_version': 3, 'tasks': [{'task_id': 'task-one', 'mode': 'debugging',
        'task_directory': str(output), 'revision': 0, 'revision_hash': 'fixture',
        'harbor_export_binding': inspect_resource_export(output), 'execution_budget': deepcopy(BUDGET)}]}
    path = tmp_path/'source.json'; path.write_text(json.dumps(manifest))
    return path


def selection(exported, tmp_path):
    return v3.freeze_selection(exported, tmp_path/'selection', phase='development')


def test_new_selection_freezes_explicit_v3_with_all_old_execution_contracts(exported, tmp_path):
    frozen = selection(exported, tmp_path)
    assert frozen['tool_time_policy_version'] == 3
    assert frozen['tool_time_policy'] == v3.POLICY_V3
    assert frozen['n_attempts'] == 1 and frozen['model'] == 'gpt-6.1-sol' and frozen['reasoning_effort'] == 'xhigh'
    assert frozen['execution_budget'] == BUDGET and frozen['timeout_seconds'] == 14400
    assert frozen['prompt'] == resource.PROMPT == frontier.PROMPT
    assert frozen['tasks'][0]['tool_time_policy'] == v3.POLICY_V3
    assert len(v3.TASK_FILES) == 17 and v3.TASK_FILES == resource.TASK_FILES
    assert v3.POLICY_V3['budget_seconds'] == 1800 and v3.POLICY_V3['strict_less_than'] is True
    assert v3.POLICY_V3['complete_clock_upper_at_budget'] == 'unknown_not_failure'


@pytest.mark.parametrize('version', [None, 1, 2, True, '3', 4])
def test_cannot_reinterpret_missing_or_old_source_policy(exported, tmp_path, version):
    source = json.loads(exported.read_text())
    if version is None:
        source.pop('tool_time_policy_version')
    else:
        source['tool_time_policy_version'] = version
    exported.write_text(json.dumps(source))
    with pytest.raises(v3.FrontierError, match='explicit prospective'):
        selection(exported, tmp_path)
    assert not (tmp_path/'selection/selection_manifest.json').exists()


def test_legacy_runners_and_policies_are_not_modified(exported, tmp_path):
    assert resource.adapted_ast is not v3.adapted_ast
    source = json.loads(exported.read_text()); source['tool_time_policy_version'] = 2
    exported.write_text(json.dumps(source))
    old = resource.freeze_selection(exported, tmp_path/'old', phase='development')
    assert old['tool_time_policy_version'] == 2 and old['tool_time_policy'] == POLICY_V2
    assert POLICY_V2['version'] == 2 and 'complete_clock_measurement' not in POLICY_V2
    assert frontier.TOOL_TIME_POLICY.get('version', 1) == 1


def test_only_counted_specific_ast_functions_change():
    before, after = resource.adapted_ast(), v3.adapted_ast()
    assert len(before.body) == len(after.body)
    changed = []
    for left, right in zip(before.body, after.body):
        if ast.dump(left) != ast.dump(right):
            changed.append(left.name)
    assert changed == ['_selection_execution_budget', '_runtime_provenance', 'freeze_selection',
                       '_matches_execution', 'apply_tool_time_policy', '_job_config', 'execute_evaluation']
    for name in ['classify_result', 'review_agent_timeout', 'summarize', 'assess_infrastructure_retry',
                 'collect_attempts', 'run_evaluation', 'resume_infrastructure']:
        left = next(n for n in before.body if getattr(n, 'name', None) == name)
        right = next(n for n in after.body if getattr(n, 'name', None) == name)
        assert ast.dump(left) == ast.dump(right)


def test_new_native_class_path_and_harbor_retry_zero(exported, tmp_path):
    selected = selection(exported, tmp_path)
    config = v3._job_config(tmp_path, selected, concurrency=1, binary=Path('/native/codex'), base_url='http://invalid')
    actual = config.model_dump(mode='json')
    assert actual['agents'][0]['import_path'] == 'sheets_factory.evaluation.clock_resource_frontier:LocalCodex'
    assert actual['agents'][0]['override_timeout_sec'] == 14400
    assert actual['agents'][0]['model_name'] == 'gpt-6.1-sol'
    assert actual['agents'][0]['kwargs']['reasoning_effort'] == 'xhigh'
    assert actual['retry']['max_retries'] == 0 and actual['n_attempts'] == 1
    selected['tool_time_policy'] = deepcopy(POLICY_V2); selected['tool_time_policy_version'] = 2
    with pytest.raises(v3.FrontierError, match='cannot be reinterpreted'):
        v3._job_config(tmp_path, selected, concurrency=1, binary=Path('/native/codex'), base_url='http://invalid')


def test_v3_provenance_binds_both_frozen_parsers_and_resource_adapter(tmp_path):
    proof = v3._runtime_provenance(ROOT, tmp_path/'missing-native')
    assert proof['runner']['path'] == str(Path(v3.__file__).resolve())
    assert proof['clock_bound_parser']['sha256'] == v3.CLOCK_PARSER_SHA256
    assert proof['resource_ast_adapter']['sha256'] == v3.RESOURCE_ADAPTER_SHA256
    assert proof['frozen_frontier']['sha256'] == resource.UPSTREAM_SHA256
    assert 'tool_time_parser' in proof and 'tool_time_bounds' in proof


def test_dependency_drift_rejects_before_running(monkeypatch):
    monkeypatch.setattr(v3, 'CLOCK_PARSER_SHA256', '0'*64)
    with pytest.raises(ValueError, match='dependency changed'):
        v3.adapted_ast()


def fake_receipt(state, passed, **more):
    return {'state': state, 'passed': passed, 'cumulative_tool_seconds': None, **more}


@pytest.mark.parametrize('state,passed', [('verified', True), ('verified', False), ('bounded', True), ('bounded', False), ('bounded', None)])
def test_exact_and_old_stop_bound_are_retained_without_clock_fallback(monkeypatch, state, passed):
    base = fake_receipt(state, passed)
    monkeypatch.setattr(v3, '_base_bounds', lambda *a, **k: deepcopy(base))
    monkeypatch.setattr(v3, '_clock_bound', lambda *a, **k: pytest.fail('Known old result must not use fallback'))
    out = v3.account_trial_tool_time_v3('unused')
    assert out['state'] == state and out['passed'] is passed and out['base_policy_v2_receipt'] == base
    assert out['measurement_branch'] == 'unchanged_exact_or_stop_bound' and out['policy_version'] == 3


@pytest.mark.parametrize('reward', [0, 1])
def test_complete_underbudget_clock_bound_preserves_raw_reward(monkeypatch, tmp_path, reward):
    base = fake_receipt('unknown', None, problems=['clock mismatch'])
    clock = fake_receipt('verified_conservative_bound', True, cumulative_exact_ns=None, cumulative_upper_bound_ns=1799_000_000_000)
    monkeypatch.setattr(v3, '_base_bounds', lambda *a, **k: deepcopy(base))
    monkeypatch.setattr(v3, '_clock_bound', lambda *a, **k: deepcopy(clock))
    entry = {'status': 'scored', 'reward': reward, 'failure_kind': None, 'result_file': str(tmp_path/'result.json')}
    out = v3.apply_tool_time_policy(entry, {'tool_time_policy': deepcopy(v3.POLICY_V3)})
    assert out['status'] == 'scored' and out['reward'] == out['raw_verifier_reward'] == reward
    assert out['tool_time']['cumulative_exact_ns'] is None and out['tool_time']['cumulative_tool_seconds'] is None
    assert out['tool_time']['base_policy_v2_receipt'] == base
    assert out['tool_time']['complete_clock_receipt'] == clock


@pytest.mark.parametrize('problem', ['upper bound equals budget', 'unknown wrapper', 'missing tail', 'status mismatch'])
def test_unproved_clock_is_incomplete_not_scored_failure_or_retry(monkeypatch, tmp_path, problem):
    monkeypatch.setattr(v3, '_base_bounds', lambda *a, **k: fake_receipt('unknown', None))
    monkeypatch.setattr(v3, '_clock_bound', lambda *a, **k: fake_receipt('unknown', None, problems=[problem]))
    out = v3.apply_tool_time_policy({'status': 'scored', 'reward': 1, 'failure_kind': None,
        'result_file': str(tmp_path/'result.json')}, {'tool_time_policy': deepcopy(v3.POLICY_V3)})
    assert out['status'] == 'evidence_incomplete' and out['reward'] is None and out['raw_verifier_reward'] == 1
    assert out['failure_kind'] == 'native_tool_timing_incomplete'
    with pytest.raises(v3.FrontierError, match='never be retried'):
        v3.assess_infrastructure_retry(out)


def test_real_exact_exhaustion_still_scores_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(v3, '_base_bounds', lambda *a, **k: fake_receipt('verified', False, cumulative_tool_seconds=1800))
    monkeypatch.setattr(v3, '_clock_bound', lambda *a, **k: pytest.fail('No fallback'))
    out = v3.apply_tool_time_policy({'status': 'scored', 'reward': 1, 'failure_kind': None,
        'result_file': str(tmp_path/'result.json')}, {'tool_time_policy': deepcopy(v3.POLICY_V3)})
    assert out['reward'] == 0 and out['raw_verifier_reward'] == 1
    assert out['failure_kind'] == 'cumulative_tool_budget_exhausted'


def test_operational_guard_with_no_normal_tail_cannot_become_model_failure(monkeypatch, exported, tmp_path):
    selected = selection(exported, tmp_path)
    monkeypatch.setattr(v3, '_base_bounds', lambda *a, **k: fake_receipt('unknown', None))
    monkeypatch.setattr(v3, '_clock_bound', lambda *a, **k: fake_receipt('unknown', None, problems=['No task_complete']))
    entry = {'status': 'evidence_incomplete', 'reward': None, 'raw_verifier_reward': 0,
             'failure_kind': 'operational_elapsed_guard_reached', 'result_file': str(tmp_path/'result.json')}
    out = v3.apply_tool_time_policy(entry, selected)
    assert out['status'] == 'evidence_incomplete' and out['reward'] is None
    assert out['failure_kind'] == 'operational_elapsed_guard_reached'


def test_summary_counts_bound_as_valid_but_never_as_exact_seconds():
    selected = {'tasks': [{'task_id': 'one', 'mode': 'financial_modeling'}], 'phase': 'development'}
    attempts = [{'status': 'scored', 'reward': 1, 'mode': 'financial_modeling',
                 'tool_time': fake_receipt('verified_conservative_bound', True)}]
    score, passed = v3.summarize(selected, attempts)
    assert score['scored_tasks'] == 1 and score['overall_pass_at_1'] == 1 and passed is False
    assert score['cumulative_tool_seconds'] is None and score['timed_attempts'] == 0


def test_confirmation_still_requires_ten_per_mode(exported, tmp_path):
    with pytest.raises(v3.FrontierError, match='at least ten'):
        v3.freeze_selection(exported, tmp_path/'confirm', phase='confirmation')


def test_entry_retains_observer_and_single_strongest_contract_without_calling_service(monkeypatch, exported, tmp_path):
    path = ROOT/'scripts/evaluate_clock_resource_difficulty.py'
    spec = importlib.util.spec_from_file_location('clock_entry_test', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    calls = []
    class Observer:
        receipt = {'fixture': True}
        finalization_error = None
        def __init__(self, output): calls.append(('observer', output))
        def __enter__(self): return self
        def __exit__(self, *args): pass
    def execute(source, output, **kwargs):
        calls.append(('execute', source, output, kwargs))
        return {'status': 'completed', 'score': {'fixture': True}, 'gate_passed': False}
    monkeypatch.setattr(module, 'ResourceObserver', Observer)
    monkeypatch.setattr(module, 'run_evaluation', execute)
    assert module.main(['--release-manifest', str(exported), '--output-dir', str(tmp_path/'run'),
                        '--phase', 'development', '--max-infrastructure-retries', '0']) == 0
    kwargs = calls[1][3]
    assert kwargs['concurrency'] == 1
    assert kwargs['backend_config']['model'] == 'gpt-6.1-sol'
    assert kwargs['backend_config']['reasoning_effort'] == 'xhigh'
