from copy import deepcopy
import ast
import importlib.util
import inspect
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
s = importlib.util.spec_from_file_location('ring_retained_clock_seam_v5', ROOT/'scripts/finalize_ringfenced_business_revision5.py')
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)


def predicate(tree, target):
    expected = ast.dump(ast.parse(target, mode='eval').body)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'require':
            if any(ast.dump(item) == expected for item in ast.walk(node.args[0])):
                return compile(ast.Expression(node.args[0]), '<retained-predicate>', 'eval')
    raise AssertionError('Retained predicate not found')


def toy():
    actual = {'reward': 0, 'raw_verifier_reward': 0, 'state': 'complete', 'result_sha256': 'same'}
    return {'task': {'task_id': 'F11'}, 'result': actual, 'old': {'F11': deepcopy(actual)},
        'failure': {'boundary_only': False, 'resources_passed': True, 'tool_time_passed': None,
            'actual_result': {'sha256': 'same'}}}


def test_exact_one_seam_changes_only_the_historical_clock_predicate():
    source = inspect.getsource(m.base.finalize)
    expected = ast.parse(source.replace(m.OLD, m.NEW))
    actual = m.retained_clock_seam(source)
    assert ast.dump(actual) == ast.dump(expected)
    env = toy()
    assert eval(predicate(actual, m.NEW), {}, env)
    assert not eval(predicate(ast.parse(source), m.OLD), {}, env)


@pytest.mark.parametrize('source', ['def f():\n return True\n', 'def f():\n return ('+m.OLD+') and ('+m.OLD+')\n'])
def test_changed_or_duplicated_legacy_seam_holds(source):
    with pytest.raises(ValueError, match='exact-one'): m.retained_clock_seam(source)


def test_raw_identity_resources_complete_state_boundary_and_result_hash_are_still_required():
    code = predicate(m.retained_clock_seam(inspect.getsource(m.base.finalize)), m.NEW)
    for key, value in [('reward', 1), ('raw_verifier_reward', 1), ('state', 'unknown'), ('result_sha256', 'different')]:
        env = toy(); env['result'][key] = value; env['old']['F11'] = deepcopy(env['result'])
        assert not eval(code, {}, env)
    for key, value in [('boundary_only', True), ('resources_passed', False)]:
        env = toy(); env['failure'][key] = value
        assert not eval(code, {}, env)
    env = toy(); env['old']['F11']['reward'] = 1
    assert not eval(code, {}, env)
    for clock in (None, False, True):
        env = toy(); env['failure']['tool_time_passed'] = clock
        assert eval(code, {}, env)


def test_private_dispatch_appends_provenance_without_changing_frozen_globals(tmp_path, monkeypatch):
    original_base = m.previous.base; original_write = m.base.write
    def frozen_flow(installed, confirmation, review, actual_controls, output, *, review_contract, development=()):
        return base.write(output, {'kind': 'qualified_ringfenced_business_revision_release', 'version': 4,
            'original_retained_clock_flag': None, 'original_raw_reward': 0})
    monkeypatch.setattr(m.previous, 'finalize', frozen_flow)
    target = tmp_path/'toy_release.json'
    result = m.read(m.finalize(None, None, None, None, target, review_contract=None))
    assert result['version'] == 5 and result['original_retained_clock_flag'] is None and result['original_raw_reward'] == 0
    assert result['finalizer_revision5']['original_retained_clock_flags_and_scores_preserved']
    assert m.previous.base is original_base and m.base.write is original_write


def test_actual_f11_retained_zero_accepts_the_existing_immutable_record_without_rewriting_its_clock():
    installed = ROOT/'outputs/research/ringfenced_business_revision_publication_20261101T085000Z/installed.json'
    if not installed.is_file(): pytest.skip('Local immutable F11 evidence is not distributed with pure tests')
    staged = m.read(m.read(installed)['staged']); history = m.read(staged['retained_history'])
    previous = m.read(history['previous_release']); old = {r['task_id']: r for r in previous['tasks']}
    task = next(t for t in history['tasks'] if t['variant_id'] == 'F11')
    before = deepcopy(task); original = m.ref(Path(staged['retained_history']['path']))
    assert task['original_failure_analysis']['tool_time_passed'] is not True
    env = {'task': task, 'old': old, 'result': task['original_release_result'], 'failure': task['original_failure_analysis']}
    source = inspect.getsource(m.base.finalize)
    assert not eval(predicate(ast.parse(source), m.OLD), {}, env)
    assert eval(predicate(m.retained_clock_seam(source), m.NEW), {}, env)
    assert task == before and m.ref(Path(staged['retained_history']['path'])) == original
