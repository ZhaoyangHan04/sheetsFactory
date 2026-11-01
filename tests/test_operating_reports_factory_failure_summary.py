import importlib.util
import json
from pathlib import Path
import pytest

PATH = Path(__file__).resolve().parents[1] / 'scripts/summarize_operating_reports_factory_failures.py'
spec = importlib.util.spec_from_file_location('factory_failure_summary_test', PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


@pytest.fixture
def data(tmp_path):
    tasks, results = [], []
    for mode in ('financial_modeling', 'debugging'):
        for i in range(10):
            ident = f'{mode}-{i}'
            tasks.append({'task_id': ident, 'mode': mode, 'variant_id': str(i),
                          'harbor_export_binding': {'task_name': 'sheetsfactory/' + ident}})
            native = write(tmp_path / ident / 'result.json', {'task_name': 'sheetsfactory/' + ident,
                'trial_name': ident + '__trial', 'verifier_result': {'rewards': {'reward': 0}}})
            write(native.parent / 'verifier/diagnostics.json', {'expected_change_count': 3,
                'actual_change_count': 3, 'missing_changes': [], 'extra_changes': [],
                'wrong_values': sorted(m.BOUNDARIES)})
            results.append({'task_id': ident, 'mode': mode, 'score': {'raw_verifier_reward': 0, 'effective_reward': 0},
                'resources': {'passed': True}, 'actual_attempt': {'task_id': ident, 'mode': mode,
                'result_file': str(native), 'result_sha256': m.reference(native)['sha256'],
                'trial_name': ident + '__trial', 'tool_time': {'passed': True}}})
    cohort = write(tmp_path / 'cohort.json', {'kind': 'frozen_operating_report_factory_confirmation_cohort',
        'tasks': tasks, 'selected_task_ids': [t['task_id'] for t in tasks]})
    terminal = write(tmp_path / 'terminal.json', {'kind': 'operating_reports_factory_frontier_terminal_v6',
        'phase': 'confirmation', 'results': results})
    bindings = write(tmp_path / 'bindings.json', {'financial': {
        'E057/2026Q1/yoy_percent': {'sheet': 'E057 Glenmere Facilities', 'cell': 'M68'},
        'E097/2026Q3/qoq_percent': {'sheet': 'E097 Valecrest Analytics', 'cell': 'H30'},
        **{f'E001/period{i}/reported_associate_line': {'sheet': 'Entity', 'cell': f'A{i}'} for i in range(1, 801)}}})
    return terminal, cohort, bindings


def test_complete_exact_twenty_and_boundary_labels(data):
    z = m.summarize(*data)
    assert z['count'] == 20 and z['raw_rewards'] == {'0': 20}
    assert all(r['boundary_only'] for r in z['rows'])
    assert all(r['wrong_fields'] == {'qoq_percent': 1, 'yoy_percent': 1} for r in z['rows'])
    assert not z['scores_modified'] and not z['financial_trace_cause_inferred']
    assert z['evidence']['bindings'] == m.reference(data[2])


def test_802_field_classification_is_not_trace_attribution(data):
    p = data[0].parent / 'financial_modeling-0/verifier/diagnostics.json'
    z = json.loads(p.read_text()); z['wrong_values'] += [f'Entity!A{i}' for i in range(1, 801)];write(p, z)
    r = m.summarize(*data)['rows'][0]
    assert r['wrong_value_count'] == 802 and not r['boundary_only']
    assert r['wrong_fields']['reported_associate_line'] == 800
    assert not r['trace_causality_established']


def test_one_known_position_or_extra_change_is_not_boundary_only(data):
    p = data[0].parent / 'financial_modeling-0/verifier/diagnostics.json'
    z = json.loads(p.read_text());z['extra_changes'] = ['Read Me!A1'];write(p,z)
    r = m.summarize(*data)['rows'][0]
    assert not r['boundary_only'] and r['extra_fields'] == {'__unmapped__': 1}
    z['extra_changes'] = [];z['wrong_values'] = [sorted(m.BOUNDARIES)[0]];write(p,z)
    assert not m.summarize(*data)['rows'][0]['boundary_only']


def test_missing_diagnostic_remains_unknown(data):
    (data[0].parent / 'financial_modeling-0/verifier/diagnostics.json').unlink()
    r = m.summarize(*data)['rows'][0]
    assert r['pattern'] == 'diagnostics_missing_unknown'
    assert r['wrong_value_count'] is None and not r['boundary_only']


@pytest.mark.parametrize('change', ['phase', 'missing', 'duplicate', 'mode', 'attempt_id', 'trial', 'result_sha'])
def test_wrong_phase_identity_or_result_binding_rejected(data, change):
    p = data[0];z = json.loads(p.read_text())
    if change == 'phase': z['phase'] = 'development'
    elif change == 'missing': z['results'].pop()
    elif change == 'duplicate': z['results'][-1] = z['results'][0]
    elif change == 'mode': z['results'][0]['mode'] = 'debugging'
    elif change == 'attempt_id': z['results'][0]['actual_attempt']['task_id'] = 'alias'
    elif change == 'trial': z['results'][0]['actual_attempt']['trial_name'] = 'foreign'
    elif change == 'result_sha': z['results'][0]['actual_attempt']['result_sha256'] = '0' * 64
    write(p,z)
    with pytest.raises(ValueError): m.summarize(*data)


def test_full_reference_descriptor_checks_binding_mutation(data):
    descriptor = write(data[0].parent/'bindings_ref.json', m.reference(data[2]))
    assert m.summarize(data[0], data[1], descriptor)['evidence']['bindings_descriptor'] == m.reference(descriptor)
    write(data[2], {'financial': {}})
    with pytest.raises(ValueError, match='reference changed'):
        m.summarize(data[0], data[1], descriptor)


def test_physical_key_vocabulary_and_duplicate_rejected():
    assert m.binding_index({'financial': {'Sheet!A1': {'semantic_key': 'E/2027Q1/net_income'}}}) == {'Sheet!A1':'net_income'}
    with pytest.raises(ValueError):
        m.binding_index({'financial': {'E/P/a': {'sheet':'X','cell':'A1'},'E/P/b': {'sheet':'X','cell':'A1'}}})


def test_duplicate_diagnostic_positions_rejected(data):
    p = data[0].parent / 'financial_modeling-0/verifier/diagnostics.json'
    z = json.loads(p.read_text());z['wrong_values'] *= 2;write(p,z)
    with pytest.raises(ValueError):m.summarize(*data)


def test_raw_reward_is_checked_against_native_evidence(data):
    p = data[0];z = json.loads(p.read_text());z['results'][0]['score']['raw_verifier_reward'] = 1;write(p,z)
    with pytest.raises(ValueError, match='Native reward'):
        m.summarize(*data)
