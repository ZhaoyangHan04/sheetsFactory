"""Keep all original economic guards under resource-only supplemental replay."""
import ast
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_old = ROOT/'tests/test_ringfenced_business_diagnosis.py'
_text = _old.read_text()
_needle = "ROOT/'scripts/diagnose_ringfenced_business_attempts.py'"
assert _text.count(_needle) == 1
_text = _text.replace(_needle, "ROOT/'scripts/diagnose_ringfenced_business_attempts_revision2.py'")
_context = "context['certificate']=put('certificate.json',{'TEST_ONLY_mock_certificate_boundary':True})"
assert _text.count(_context) == 1
_text = _text.replace(_context, _context+"\n    context['historical_resource_supplements']={}")
_selected = "selected.append({'task_id':identity,'harbor_export_binding':binding,'task_checksum':identity})"
assert _text.count(_selected) == 1
_text = _text.replace(_selected, "selected.append({'task_id':identity,'harbor_export_binding':binding,'task_checksum':identity,'task_directory':str(directory)})")
_row = "rows.append({'task_id':identity,'mode':mode,'actual_attempt':"
assert _text.count(_row) == 1
_text = _text.replace(_row, "Path(result['path']).with_name('config.json').write_text('{}')\n        rows.append({'task_id':identity,'mode':mode,'score':{'state':'complete','effective_reward':0},'resources':{'passed':False,'complete':False},'actual_attempt':")
exec(compile(ast.parse(_text), str(_old), 'exec'), globals())


def test_private_revision_only_changes_resource_gate_and_preserves_original_namespace():
    assert m._original.validate_trial_observations is not m.validate_trial_observations
    assert m._original._admit.__globals__ is vars(m._original)
    assert m._original.run.__globals__ is vars(m._original)
    assert m.evaluate_plans.__code__ is m._original.evaluate_plans.__code__
    assert m.budget_status.__code__ is m._original.budget_status.__code__
    assert m.reference(m._BASE)['sha256'] == m._BASE_SHA
    assert m.reference(m.supplement.__file__)['sha256'] == m.SUPPLEMENT_SHA
    assert m.supplement.validate_trial_observations is m.validate_trial_observations


def test_resource_projection_attaches_same_receipts_and_never_changes_original_score_or_rows(admission, monkeypatch):
    # This is an admission-only fixture with all physical/native boundaries
    # mocked by the unchanged original fixture, not a genuine production run.
    f = admission
    original = m._original_admit(f['br'], f['tr'])
    original_rows = deepcopy(original[2]); before = deepcopy(original)
    proof_calls = []
    def supplement(config, result, **kwargs):
        proof_calls.append((config, result, kwargs))
        return {'TEST_ONLY_mock_supplement_boundary': True,
            'original_validation': {'passed': False, 'complete': False},
            'supplemental_validation': {'passed': True, 'complete': True, 'trial_config': m.reference(config), 'result': result},
            'original_results_or_receipts_or_scores_modified': False}
    monkeypatch.setattr(m, '_original_admit', lambda *args: original)
    monkeypatch.setattr(m.supplement, 'supplement_trial', supplement)
    for row in original_rows.values():
        config = Path(row['actual_attempt']['result_file']).with_name('config.json')
        config.write_text('{}')
    _, _, rows, _, _, context = m._admit(f['br'], f['tr'])
    assert original == before and len(proof_calls) == 2
    for identity, row in rows.items():
        assert row['score'] == original_rows[identity]['score']
        assert row['actual_attempt'] == original_rows[identity]['actual_attempt']
        assert row['resources']['passed'] is True
        assert context['historical_resource_supplements'][identity]['original_resources'] == original_rows[identity]['resources']


def test_evidence_and_terminal_explicitly_retain_unknown_provenance(run_fixture):
    f = run_fixture
    f['context']['historical_resource_supplements'] = {identity: {'original_resources': {'passed': False, 'complete': False},
        'supplement': {'TEST_ONLY_mock': True, 'supplemental_validation': {'passed': True, 'complete': True}}} for identity in f['rows']}
    result = m.read(m.run(f['br']['path'], f['tr']['path'], f['tmp_path']/'supplemental_diagnosis'))
    assert result['supplemental_diagnosis_revision'] == 2 and result['original_native_terminal_and_resources_and_score_unchanged']
    for record in result['records']:
        evidence = m.read(record['evidence'])
        assert evidence['original_v6_resource_unknown_not_regraded']
        assert evidence['historical_resource_supplement']['original_resources']['passed'] is False
        assert evidence['original_score'] == f['rows'][record['task_id']]['score']
