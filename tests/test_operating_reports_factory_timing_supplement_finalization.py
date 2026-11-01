"""One complete append-only timing proof must not weaken any other attempt."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('_factory_supplement_consumer_test',
    ROOT / 'scripts/finalize_operating_reports_factory_with_timing_supplement.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    def put(name, value):
        return m.write(tmp_path / name, value)
    native = put('result.json', {'task_name': 'sheetsfactory/' + m.TASK,
        'exception_info': None, 'finished_at': '2026-11-01T05:33:13Z',
        'verifier_result': {'rewards': {'reward': 0}}})
    monkeypatch.setattr(m, 'RESULT_SHA', native['sha256'])
    rows = []
    for i in range(20):
        tid = m.TASK if i == 0 else 'task-' + str(i)
        rows.append({'task_id': tid, 'mode': 'financial_modeling' if i < 10 else 'debugging',
            'variant_id': str(i), 'material_identity': {'sha256': 'material-' + str(i)},
            'actual_attempt': {'status': 'scored', 'failure_kind': None,
                'task_id': tid, 'mode': 'financial_modeling' if i < 10 else 'debugging', 'reward': 0,
                'raw_verifier_reward': 0, 'result_file': native['path'],
                'result_sha256': native['sha256'], 'task_checksum': 'checksum-' + str(i),
                'tool_time': {'passed': True, 'cumulative_tool_seconds': 100}},
            'resources': {'passed': True, 'complete': True},
            'score': {'effective_reward': 0, 'state': 'complete',
                'infrastructure_unknown_is_not_model_zero': True}})
    prior = {'passed': None, 'state': 'unknown', 'policy_version': 6,
             'problems': ['Unsupported local result use or callback']}
    rows[0]['actual_attempt'].update(status='evidence_incomplete',
        failure_kind='native_tool_timing_incomplete', reward=None, tool_time=prior)
    rows[0]['score'].update(state='unknown', effective_reward=None)
    resources = put('resources.json', {'passed': True, 'complete': True, 'observation_receipts': []})
    original = {'kind': 'operating_reports_factory_frontier_terminal_v6', 'phase': 'confirmation',
        'outer_retries': 0, 'resources': resources, 'results': rows}
    selection = {'tasks': [{'task_id': r['task_id'], 'mode': r['mode']} for r in rows],
        'phase': 'confirmation', 'execution_budget': {}}
    original['selection'] = put('selection.json', selection)
    old_score, old_gate = m._summarize(selection, [r['actual_attempt'] for r in rows])
    evaluation = {'phase': 'confirmation', 'status': 'infrastructure_failed',
        'finished_at': '2026-11-01T05:39:00Z', 'failure_kind': None, 'infra_history': [],
        'infrastructure_retries': [], 'n_attempts': 1, 'gate_passed': old_gate,
        'selection_manifest': {k: original['selection'][k] for k in ('path', 'sha256')},
        'attempts': [r['actual_attempt'] for r in rows], 'score': old_score}
    original['evaluation'] = put('evaluation.json', evaluation)
    monkeypatch.setattr(m, 'EVALUATION_SHA', original['evaluation']['sha256'])
    original_ref = put('original.json', original)
    monkeypatch.setattr(m, 'ORIGINAL_CONFIRMATION_SHA', original_ref['sha256'])
    session = put('session.jsonl', {'unit_test_only': True})
    wrappers = [{'call_id': 'call-' + str(i), 'code_sha256': 'unchanged',
        'new_display_only': False, 'unchanged_primitive_dispatches': True, 'primitive_count': 1}
        for i in range(22)]
    wrappers[0].update(code_sha256=m.DISPLAY_SHA, new_display_only=True,
        unchanged_primitive_dispatches=None, primitive_count=2)
    coverage = {'native_tool_count': 24, 'stream_tool_count': 24, 'static_launch_count': 24,
        'unknown_dispatch_count': 0, 'all_primitives_uniquely_owned': True,
        'wrapper_call_count': 22, 'wrapper_output_count': 22,
        **{k: True for k in ['native_stream_ordered_signatures_status_and_exits_equal',
        'all_intervals_in_agent_window', 'all_parallel_primitive_uppers_summed',
        'all_uncovered_wrapper_time_retained', 'disagreeing_clock_items_never_credit_overlap']}}
    clock = {'passed': True, 'complete': True, 'budget_seconds': 1800,
        'strict_less_than': True, 'parallel_executions': 'sum', 'model_response_time_included': False,
        'cumulative_lower_bound_ns': 107_000_000_000, 'cumulative_upper_bound_ns': 127_000_000_000,
        'cumulative_lower_bound_seconds': '107', 'cumulative_upper_bound_seconds': '127',
        'coverage': coverage, 'tools': [{'id': str(i)} for i in range(24)],
        'wrappers': deepcopy(wrappers), 'problems': [], 'result_file': native, 'artifacts': [session]}
    supplement = {'kind': 'readonly_F11_supplemental_complete_tool_time_evidence', 'version': 1,
        'task_id': m.TASK, 'result': native, 'original_confirmation': original_ref,
        'material_identity': rows[0]['material_identity'], 'retained_trial_resources': rows[0]['resources'],
        'original_v6_tool_time': prior,
        'wrapper_comparison': {'wrapper_count': 22, 'v6_already_recognized': 21,
            'new_display_wrappers': 1, 'wrappers': wrappers, 'sessions': [session]},
        'supplemental_clock': clock, 'recipes': [], 'original_v6_unknown_preserved': True,
        'original_scores_modified': False, 'new_native_calls': 0, 'new_model_calls': 0}
    return original, original_ref, supplement, put


def test_complete_projection_preserves_original_unknown_policy_and_other_nineteen(evidence):
    original, record, supplement, _ = evidence
    before = deepcopy(original)
    projected = m._projection(original, record, supplement)
    assert original == before
    assert m.read(record) == before
    assert projected['results'][1:] == before['results'][1:]
    target = projected['results'][0]
    assert target['actual_attempt']['raw_verifier_reward'] == 0
    assert target['score'] == {'state': 'complete', 'effective_reward': 0,
        'infrastructure_unknown_is_not_model_zero': True}
    base = m._load(m.FINALIZER)
    rows, mean = base.confirmation_scores(projected, [r['task_id'] for r in projected['results']])
    assert len(rows) == 20 and mean == 0
    with pytest.raises(ValueError, match='complete resource and scoring evidence'):
        base.confirmation_scores(original, [r['task_id'] for r in original['results']])


@pytest.mark.parametrize('defect', ['original_ref', 'foreign_result', 'material', 'resources',
    'other_unknown', 'other_failure', 'raw_reward', 'wrapper_sha', 'wrapper_duplicate',
    'changed_old_dispatch', 'missing_primitive', 'missing_stream', 'fanout_unknown',
    'nonunique_owner', 'missing_tail', 'parallel_wall', 'model_time', 'at_threshold',
    'straddles_threshold', 'lower_above_upper', 'uncounted_wrapper', 'score_modified'])
def test_partial_foreign_or_over_budget_evidence_never_projects(evidence, defect):
    original, record, s, _ = evidence
    o, s = deepcopy(original), deepcopy(s)
    row = o['results'][0]; clock = s['supplemental_clock']
    if defect == 'original_ref': s['original_confirmation']['sha256'] = 'other'
    elif defect == 'foreign_result': s['result']['sha256'] = 'other'
    elif defect == 'material': s['material_identity']['sha256'] = 'other'
    elif defect == 'resources': s['retained_trial_resources']['passed'] = False
    elif defect == 'other_unknown': o['results'][1]['score'].update(state='unknown', effective_reward=None)
    elif defect == 'other_failure': row['actual_attempt']['failure_kind'] = 'NetworkConnectionError'
    elif defect == 'raw_reward': row['actual_attempt']['raw_verifier_reward'] = 1
    elif defect == 'wrapper_sha': s['wrapper_comparison']['wrappers'][0]['code_sha256'] = 'other'
    elif defect == 'wrapper_duplicate': s['wrapper_comparison']['wrappers'][1]['call_id'] = 'call-0'
    elif defect == 'changed_old_dispatch': s['wrapper_comparison']['wrappers'][1]['unchanged_primitive_dispatches'] = False
    elif defect == 'missing_primitive': clock['tools'].pop()
    elif defect == 'missing_stream': clock['coverage']['stream_tool_count'] = 23
    elif defect == 'fanout_unknown': clock['coverage']['unknown_dispatch_count'] = 1
    elif defect == 'nonunique_owner': clock['coverage']['all_primitives_uniquely_owned'] = False
    elif defect == 'missing_tail': clock['complete'] = False
    elif defect == 'parallel_wall': clock['parallel_executions'] = 'wall'
    elif defect == 'model_time': clock['model_response_time_included'] = True
    elif defect == 'at_threshold': clock['cumulative_upper_bound_ns'] = 1_800_000_000_000
    elif defect == 'straddles_threshold': clock['cumulative_upper_bound_ns'] = 1_900_000_000_000
    elif defect == 'lower_above_upper': clock['cumulative_lower_bound_ns'] = 200_000_000_000
    elif defect == 'uncounted_wrapper': clock['wrappers'].pop()
    else: s['original_scores_modified'] = True
    with pytest.raises(ValueError):
        m._projection(o, record, s)


def test_native_session_mutation_and_exception_are_rejected(evidence):
    original, record, supplement, _ = evidence
    session = Path(supplement['wrapper_comparison']['sessions'][0]['path'])
    session.write_text('changed')
    with pytest.raises(ValueError, match='source, session or stream'):
        m._projection(original, record, supplement)


def test_aggregate_timing_status_is_strictly_projected_and_score_recomputed(evidence):
    original, record, supplement, _ = evidence
    projected = m._projection(original, record, supplement)
    evaluation_ref, before, interpreted = m._evaluation_projection(original, projected)
    assert before['status'] == 'infrastructure_failed' and before['score']['scored_tasks'] == 19
    assert before['score']['incomplete_timing_evidence'] == 1
    assert interpreted['status'] == 'completed' and interpreted['score']['scored_tasks'] == 20
    assert interpreted['score']['incomplete_timing_evidence'] == 0
    assert interpreted['score']['overall_pass_at_1'] == 0 and interpreted['gate_passed'] is True
    assert interpreted['attempts'][1:] == before['attempts'][1:]
    assert m.read(evaluation_ref) == before


@pytest.mark.parametrize('defect', ['nonempty_history', 'retry', 'runtime_failure', 'missing_attempt',
    'foreign_attempt', 'different_selection', 'changed_aggregate', 'changed_timing_count'])
def test_unrelated_evaluation_failure_is_not_blindly_overridden(evidence, monkeypatch, defect):
    original, record, supplement, put = evidence
    projected = m._projection(original, record, supplement)
    evaluation = m.read(original['evaluation'])
    if defect == 'nonempty_history': evaluation['infra_history'] = [{'unrelated': 'failure'}]
    elif defect == 'retry': evaluation['infrastructure_retries'] = [{'retry': 1}]
    elif defect == 'runtime_failure': evaluation['failure_kind'] = 'snapshot_changed'
    elif defect == 'missing_attempt': evaluation['attempts'].pop()
    elif defect == 'foreign_attempt': evaluation['attempts'][1]['result_sha256'] = 'foreign'
    elif defect == 'different_selection': evaluation['selection_manifest']['sha256'] = 'foreign'
    elif defect == 'changed_aggregate': evaluation['score']['infrastructure_errors'] = 1
    else: evaluation['score']['incomplete_timing_evidence'] = 2
    original['evaluation'] = put('changed-evaluation.json', evaluation)
    monkeypatch.setattr(m, 'EVALUATION_SHA', original['evaluation']['sha256'])
    with pytest.raises(ValueError):
        m._evaluation_projection(original, projected)


def test_private_finalizer_provenance_seam_does_not_mutate_original_module():
    ordinary = m._load(m.FINALIZER)
    annotated = m._load(m.FINALIZER, annotate_release=lambda row: row.update(test_provenance=True))
    assert '_annotate_release' not in ordinary.finalize.__globals__
    assert annotated['finalize'].__globals__['_annotate_release'] is not None
    assert ordinary.confirmation_scores.__code__ is not annotated['confirmation_scores'].__code__
    assert m.reference(m.FINALIZER)['sha256'] == m.PINS[m.FINALIZER]
    assert m.reference(m.QUALITY)['sha256'] == m.PINS[m.QUALITY]


def test_supplement_provider_is_exact_pinned_and_exposes_genuine_replay():
    provider = m._load(m.SUPPLEMENT)
    assert callable(provider.validate_supplement)
    assert m.reference(m.SUPPLEMENT)['sha256'] == m.PINS[m.SUPPLEMENT]


def test_final_workflow_replays_once_preserves_flags_and_annotates_both_outputs(evidence, tmp_path, monkeypatch):
    original, record, supplement, put = evidence
    supplement_ref = put('supplement.json', supplement)
    calls = []
    quality = SimpleNamespace(read=m.read)
    namespace = {'read': m.read}
    exec('def check(record, ids):\n data=read(record)\n return {r["task_id"]:r for r in data["results"]}\n', namespace)
    quality._confirmation = namespace['check']
    def build(*args):
        rows = quality._confirmation(record, [])
        assert all(r['score']['state'] == 'complete' for r in rows.values())
        return {'kind': 'operating_report_factory_final_quality_join', 'passed': True, 'task_count': 20}
    quality.build = build
    def fake_load(path, *, annotate_release=None):
        if path == m.SUPPLEMENT:
            def replay(ref):
                calls.append(ref)
                return m.read(ref)
            return SimpleNamespace(validate_supplement=replay)
        if path == m.QUALITY: return quality
        def score(terminal, selected):
            assert terminal['results'][0]['score']['state'] == 'complete'
            return [], 0
        private = {'confirmation_scores': score, 'read_ref': m.read}
        def finish(cohort, confirmation, qpath, controls, output):
            private['confirmation_scores'](m.read(record), [])
            assert private['read_ref'](original['evaluation'])['status'] == 'completed'
            value = {'kind': 'qualified_operating_report_factory_release', 'qualified': True,
                     'confirmation': record, 'quality': m.reference(qpath)}
            annotate_release(value)
            return m.write(output, value)
        private['finalize'] = finish
        return private
    monkeypatch.setattr(m, '_load', fake_load)
    released = m.finalize('cohort', 'fm', 'dbg', 'controls', record['path'], supplement_ref['path'],
        tmp_path/'release.json', quality_output=tmp_path/'new-quality.json')
    assert len(calls) == 1
    for path in [released['path'], tmp_path/'new-quality.json']:
        data = json.loads(Path(path).read_text())
        assert data['version'] == 2
        assert data['timing_interpretation']['original_confirmation'] == record
        assert data['timing_interpretation']['timing_supplement'] == supplement_ref
        assert data['timing_interpretation']['original_v6_unknown_preserved'] is True
    assert m.read(record) == original


def test_retained_actual_F11_projection_shape_without_services():
    base = ROOT/'outputs/research/operating_reports_factory_delivery_20261101T050700Z/confirmation/terminal.json'
    supplement = ROOT/'outputs/research/operating_reports_factory_F11_timing_supplement_20261101T054200Z/receipt.json'
    if not base.exists() or not supplement.exists(): pytest.skip('Retained production evidence not installed')
    actual_spec = importlib.util.spec_from_file_location('_actual_supplement_shape', Path(m.__file__))
    actual = importlib.util.module_from_spec(actual_spec); actual_spec.loader.exec_module(actual)
    before = actual.reference(base)
    projection = actual._projection(actual.read(before), before, actual.read(actual.reference(supplement)))
    eval_ref, old_eval, interpreted = actual._evaluation_projection(actual.read(before), projection)
    assert old_eval['status'] == 'infrastructure_failed' and interpreted['status'] == 'completed'
    assert interpreted['score']['scored_tasks'] == 20 and interpreted['score']['overall_pass_at_1'] == 0
    assert actual.read(eval_ref) == old_eval
    rows, mean = actual._load(actual.FINALIZER).confirmation_scores(projection, [r['task_id'] for r in projection['results']])
    assert len(rows) == 20 and mean == 0
    assert actual.reference(base) == before
