"""Fresh runner policy, raw rewards, strict boundaries and old-run isolation."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from sheets_factory.evaluation import linear_capital_scaled_frontier_v5 as old
from sheets_factory.evaluation import linear_capital_scaled_frontier_v6 as new
from sheets_factory.evaluation import tool_time_clock_bounds_v6 as clocks


def test_exact_prior_code_and_globals_are_unchanged():
    assert hashlib.sha256(Path(old.__file__).read_bytes()).hexdigest() == new.PRIOR_SHA256
    assert old._namespace['POLICY_V5']['version'] == 5
    assert 'POLICY_V6' not in old._namespace
    assert new._namespace is not old._namespace
    assert new.LocalCodex.__module__ == new.__name__
    assert new.POLICY_V6 == clocks.POLICY_V6
    assert new.POLICY_V6['version'] == 6
    new.verify_dependencies()


def test_original_budget_transport_and_outer_retry_contract_remains():
    text = ast.unparse(new.adapted_ast())
    assert "timing_version == 6" in text
    assert "selection.get('tool_time_policy_version') == 6" in text
    assert "'max_retries': 0" in text
    assert "'n_attempts': 1" in text
    assert 'version-five runner' not in text
    assert 'frontier_v5:LocalCodex' not in text
    assert new.transport_profile() == old.transport_profile()
    assert new.TASK_FILES == old.TASK_FILES


def test_v5_source_is_rejected_before_selection_or_any_execution(tmp_path):
    source = tmp_path/'source.json'
    source.write_text(json.dumps({'native_transport_profile': new.transport_profile(),
        'tool_time_policy_version': 5, 'timeout_seconds': 14400}))
    with pytest.raises(new._namespace['FrontierError'], match='prospective.*version=6'):
        new.freeze_selection(source, tmp_path/'evaluation', phase='development')
    assert not (tmp_path/'evaluation').exists()


@pytest.mark.parametrize('state,passed,raw,expected,status,failure', [
    ('verified', True, 1, 1, 'scored', None),
    ('verified', True, 0, 0, 'scored', None),
    ('verified', False, 1, 0, 'scored', 'cumulative_tool_budget_exhausted'),
    ('verified_tool_budget_lower_bound', False, 1, 0, 'scored', 'cumulative_tool_budget_exhausted'),
    ('verified_owned_overlap_bound', True, 1, 1, 'scored', None),
    ('unknown', None, 1, None, 'evidence_incomplete', 'native_tool_timing_incomplete'),
    ('verified_owned_overlap_bound', None, 1, None, 'evidence_incomplete', 'native_tool_timing_incomplete'),
])
def test_clock_result_is_applied_without_changing_raw_reward(monkeypatch, tmp_path,
        state, passed, raw, expected, status, failure):
    invocations = []
    def measure(result, **kwargs):
        invocations.append((result, kwargs))
        return {'state': state, 'passed': passed, 'policy_version': 6}
    monkeypatch.setitem(new._namespace, 'account_trial_tool_time_v6', measure)
    entry = {'status': 'scored', 'reward': raw, 'result_file': str(tmp_path/'result.json')}
    result = new.apply_tool_time_policy(entry, {'tool_time_policy': deepcopy(new.POLICY_V6)})
    assert result['raw_verifier_reward'] == raw
    assert result['reward'] == expected and result['status'] == status
    assert result.get('failure_kind') == failure
    assert result['tool_time']['policy_version'] == 6
    assert len(invocations) == 1 and invocations[0][1]['budget_seconds'] == 1800


def test_legacy_policy_cannot_be_applied_by_new_runner(tmp_path):
    with pytest.raises(new._namespace['FrontierError'], match='version-six'):
        new.apply_tool_time_policy({'status': 'scored', 'reward': 1,
            'result_file': str(tmp_path/'result.json')}, {'tool_time_policy': old.POLICY_V5})


def test_ordinary_infrastructure_failure_stays_unknown_and_unmeasured(monkeypatch):
    def unexpected(*a, **kw):
        pytest.fail('An incomplete ordinary infrastructure result must not be scored')
    monkeypatch.setitem(new._namespace, 'account_trial_tool_time_v6', unexpected)
    entry = {'status': 'evidence_incomplete', 'reward': None, 'failure_kind': 'native_transport_failed'}
    assert new.apply_tool_time_policy(entry, {'tool_time_policy': new.POLICY_V6}) == entry
