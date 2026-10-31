"""Publication timing tests are pure and never launch a task or service."""
import ast
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from sheets_factory.evaluation import clock_resource_publication as v3
from sheets_factory.evaluation import clock_resource_publication_v4 as v4
from sheets_factory.evaluation import clock_resource_frontier_v4 as runner

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_v4_publication_clock_fixture', ROOT/'tests/test_tool_time_clock_bounds.py')
fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)


def require(ok, message):
    if not ok: raise ValueError(message)


def bound(tmp_path):
    paths, data = fixture.fixture(tmp_path, parallel=True)
    fixture.tools(data)[1]['item']['duration'] = fixture.duration(1_000_000_000)
    data['native'][1]['payload']['input'] = 'text(ALL_TOOLS.filter(x=>/file/i.test(x.name+" "+x.description)));'+data['native'][1]['payload']['input']
    fixture.save(paths, data)
    receipt = runner.account_trial_tool_time_v4(paths['result'])
    assert receipt['passed'] and receipt['measurement_branch'] == 'complete_proven_owned_overlap', receipt.get('problems')
    names = ('tool_time_clock_bounds_v4.py', 'tool_time_clock_bounds.py', 'tool_time.py')
    recipe = {'src/sheets_factory/evaluation/'+n: v3.reference(ROOT/'src/sheets_factory/evaluation'/n) for n in names}
    backend = SimpleNamespace(runner=runner, cohort={'publication_recipe': recipe})
    return paths, receipt, backend


class Release:
    @staticmethod
    def _file(path, within, tracked):
        path = Path(path)
        require(path.is_relative_to(within), 'Escaped trial')
        record = v3.reference(path); tracked[str(path)] = record['sha256']
        return path.read_bytes()


def test_exact_generic_quality_score_and_copy_bodies_remain_identical():
    old = {n.name: n for n in v3.publisher_ast().body if isinstance(n, ast.FunctionDef)}
    new = {n.name: n for n in v4.publisher_ast().body if isinstance(n, ast.FunctionDef)}
    for name in old.keys()-{'_frozen_tool_time_policy', '_track_tool_time_evidence', '_validate_confirmation'}:
        assert ast.dump(new[name]) == ast.dump(old[name]), name
    assert not hasattr(v4.publisher_namespace(), 'ResourcePublicationBackend')


def test_old_selection_cannot_be_reinterpreted():
    assert v4._policy_v4({'tool_time_policy_version': 4, 'tool_time_policy': runner.POLICY_V4}, require) == runner.POLICY_V4
    for version in (1, 2, 3, True, None):
        with pytest.raises(ValueError):
            v4._policy_v4({'tool_time_policy_version': version, 'tool_time_policy': runner.POLICY_V4}, require)


def test_full_bound_is_reproduced_from_raw_trace_and_tracks_all_six_inputs(tmp_path):
    paths, timing, backend = bound(tmp_path); tracked = {}; bases = []
    evidence = v4._track_v4(timing, paths['result'], tracked, backend,
        lambda value, *_: bases.append(value) or {}, Release, require)
    assert len(tracked) == 6 and evidence['clock_bound_is_exact'] is False
    assert len(bases) == 2 and bases[1]['state'] == 'unknown'
    projected = v4._project_v4(timing, evidence, require)
    assert projected['cumulative_tool_seconds'] is projected['cumulative_tool_nanoseconds'] is None
    assert projected['cumulative_upper_bound_ns'] == timing['cumulative_upper_bound_ns']
    assert projected['policy_version'] == 4


@pytest.mark.parametrize('change', ['upper', 'exact', 'code', 'receipt', 'old_backend'])
def test_tampered_or_unproved_bound_refuses(tmp_path, change):
    paths, timing, backend = bound(tmp_path)
    if change == 'upper': timing['complete_owned_overlap_receipt']['cumulative_upper_bound_ns'] -= 1
    elif change == 'exact': timing['cumulative_tool_seconds'] = 2.22
    elif change == 'code': backend.cohort['publication_recipe']['src/sheets_factory/evaluation/tool_time.py']['sha256'] = '0'*64
    elif change == 'receipt': timing['complete_owned_overlap_receipt']['coverage']['native_tool_count'] += 1
    elif change == 'old_backend': backend.runner = SimpleNamespace(POLICY_V3=v3._POLICY_V3)
    with pytest.raises(ValueError): v4._track_v4(timing, paths['result'], {}, backend, lambda *_: {}, Release, require)


def test_missing_complete_tail_stays_unknown_and_cannot_publish(tmp_path):
    paths, data = fixture.fixture(tmp_path, parallel=True)
    fixture.tools(data)[1]['item']['duration'] = fixture.duration(1_000_000_000)
    data['stream'] = data['stream'][:-1]; fixture.save(paths, data)
    timing = runner.account_trial_tool_time_v4(paths['result'])
    assert timing['state'] == 'unknown'
    with pytest.raises(ValueError):
        v4._track_v4(timing, paths['result'], {}, SimpleNamespace(runner=runner), lambda *_: {}, Release, require)


def test_earlier_exact_proof_is_retained_without_score_or_admission_adapter(monkeypatch):
    old = {'policy_version': 3, 'method': 'old', 'measurement_branch': 'unchanged_exact_or_stop_bound',
           'state': 'verified', 'passed': True, 'base_policy_v2_receipt': {'state': 'verified'}}
    timing = {**old, 'policy_version': 4, 'method': runner.POLICY_V4['measurement'],
              'measurement_branch': 'unchanged_v3_exact_or_bound', 'base_policy_v3_receipt': old}
    seen = []
    def tracker(value, result, tracked, context, *args):
        assert not hasattr(context, 'validate_task')
        assert context.runner.POLICY_V3 == v3._POLICY_V3
        seen.append(value); return {'retained': True}
    monkeypatch.setattr(v3, '_track_v3', tracker)
    backend = SimpleNamespace(runner=runner, cohort={})
    assert v4._track_v4(timing, ROOT/'result.json', {}, backend, None, None, require) == {'retained': True}
    assert seen == [old]
    tampered = deepcopy(timing); tampered['state'] = 'bounded'
    with pytest.raises(ValueError): v4._track_v4(tampered, ROOT/'result.json', {}, backend, None, None, require)
