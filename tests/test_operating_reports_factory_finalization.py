"""Release scoring must reproduce the immutable fresh confirmation evidence."""
import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1]/'scripts/finalize_operating_reports_factory_release.py'
spec = importlib.util.spec_from_file_location('factory_finalization_test', PATH)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


def fixture(passes=4):
    rows = []
    for i in range(20):
        reward = int(i < passes)
        rows.append({'task_id': str(i), 'mode': 'financial_modeling' if i < 10 else 'debugging', 'variant_id': str(i),
            'actual_attempt': {'status': 'scored', 'raw_verifier_reward': reward, 'failure_kind': None,
                'tool_time': {'passed': True, 'cumulative_tool_seconds': 100}, 'result_sha256': 'r'+str(i), 'task_checksum': 't'+str(i)},
            'resources': {'passed': True, 'complete': True}, 'score': {'effective_reward': reward, 'state': 'complete'},
            'material_identity': {'sha256': 'm'+str(i)}})
    return {'kind': 'operating_reports_factory_frontier_terminal_v6', 'phase': 'confirmation', 'outer_retries': 0, 'results': rows}


def test_exact_threshold_passes_and_fifth_success_does_not():
    assert module.confirmation_scores(fixture(), [str(i) for i in range(20)])[1] == .2
    with pytest.raises(ValueError, match='exceeds'):
        module.confirmation_scores(fixture(5), [str(i) for i in range(20)])


@pytest.mark.parametrize('fault', ['phase', 'unknown_clock', 'infra', 'resources', 'altered_score'])
def test_incomplete_or_reinterpreted_evidence_never_releases(fault):
    terminal = fixture(0); row = terminal['results'][0]
    if fault == 'phase': terminal['phase'] = 'development'
    if fault == 'unknown_clock': row['actual_attempt']['tool_time']['passed'] = None
    if fault == 'infra': row['actual_attempt']['failure_kind'] = 'NetworkConnectionError'
    if fault == 'resources': row['resources']['passed'] = False
    if fault == 'altered_score': row['score']['effective_reward'] = 1
    with pytest.raises(ValueError):
        module.confirmation_scores(terminal, [str(i) for i in range(20)])


def test_caches_are_not_added_twice_to_token_consumption():
    result = module.usage([{'agent_result': {'n_input_tokens': 100, 'n_output_tokens': 10, 'n_cache_tokens': 90}}])
    assert result['known_input_tokens'] == 100
    assert result['known_output_tokens'] == 10
    assert result['known_cached_input_tokens'] == 90
    assert result['unknown_usage_attempts'] == 0
