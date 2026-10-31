"""Service-free tests of the explicit new task-stage design boundary."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.fixture
def task():
    return load(ROOT / 'scripts/validate_operating_reports_200_tasks_revision2.py', '_test_fixed200_task8_revision2')


@pytest.fixture
def lineage(task, monkeypatch, tmp_path):
    def save(name, value):
        return task.write(tmp_path / name, value)
    plans = save('old_plan.json', {'FM_mask': ['E001/2026Q1/revenue'], 'DBG_faults': {}})
    bindings = save('bindings.json', {'financial': {}})
    public = save('public.json', {'synthetic': True})
    A, B = save('A.json', {}), save('B.json', {})
    goal = save('goal_placeholder.json', {'this_is_not_a_workbook': True})
    candidate = {'view_plans': plans, 'bindings': bindings, 'specification': public,
                 'retained_A': A, 'retained_B': B, 'views': {'original': True}}
    candidate_ref = save('candidate.json', candidate)
    original = save('definition.json', {})
    expected = save('expected.json', {})
    source_preparation = save('source_preparation.json', {'candidate_manifest': candidate_ref,
        'bindings': bindings, 'specification': public, 'definition': original, 'expected': expected})
    source_ref = save('source.json', {'kind': task.source.SOURCE_KIND, 'passed': True,
                                    'source': goal, 'preparation': source_preparation})
    old = save('old_preparation.json', {'candidate_preparation': candidate_ref,
        'source_preparation': source_preparation, 'source_manifest': source_ref, 'genuine_goal': goal})
    failed = save('old_failed_terminal.json', {'passed': False, 'preparation': old,
                                              'source_manifest': source_ref, 'actual_LO_calls_completed': 3})
    revised = save('new_plan.json', {'FM_mask': ['E001/2026Q1/revenue'], 'DBG_faults': {}, 'revision': 2})
    proof = save('pure_proof.json', {'unit_test_stub': True, 'not_actual_evidence': True})
    frozen = {'kind': task.design.KIND, 'version': 2, 'view_plans': revised, 'proof': proof,
              'specification': public, 'bindings': bindings, 'retained_A': A, 'retained_B': B,
              'original_view_plans': plans, 'ancestry': {'original_candidate': candidate_ref,
                  'unchanged_source_manifest': source_ref, 'unchanged_genuine_goal': goal,
                  'failed_task8': failed, 'failed_preparation': old, 'healthy_renderer': task.reference(task.DESIGN_PATH)}}
    design_ref = save('fault_design.json', frozen)
    replayed = []
    def replay(record, candidate=None):
        replayed.append((deepcopy(record), deepcopy(candidate)))
        assert task.read(record)['ancestry']['original_candidate'] == candidate_ref
        if candidate != task.read(candidate_ref): raise ValueError('Use the entire genuine original candidate')
        return task.read(task.read(record)['view_plans'])
    monkeypatch.setattr(task, 'design', SimpleNamespace(validate_revision=replay))
    return SimpleNamespace(save=save, design=design_ref, frozen=frozen, candidate=candidate,
        candidate_ref=candidate_ref, source_ref=source_ref, goal=goal, source_preparation=source_preparation,
        actual=task.read(source_ref), sf=task.read(source_preparation), replayed=replayed, tmp=tmp_path)


def test_counted_seams_and_original_source_are_unchanged(task):
    assert task.reference(task.UPSTREAM)['sha256'] == 'b4d8376ec90df5d145f9f10889cfbaac393a12d0c94ac8bbccd1a19d8a72cae5'
    assert task.ADAPTATION_COUNTS == {'plan_reads': 2, 'prepared_lineage': 1, 'kind': 1, 'terminal_kind': 1}
    assert task.TERMINAL_ADAPTATION_COUNTS == {'terminal_lineage': 1, 'execute_cache_arguments': 2, 'dashboard_title': 1}
    assert task.STAGES == ('FM_input1', 'FM_input2', 'DBG_input1', 'DBG_input2',
                           'equivalent', 'FM_missed_root', 'DBG_missed_root', 'extra_change')
    assert task.source.SOURCE_KIND == 'independently_checked_fixed_operating_reports_200_source_revision2'
    assert task.execute_prepared.__globals__['validate_prepared'] is task.validate_prepared
    assert task._base_completed.__globals__['validate_prepared'] is task.validate_prepared
    assert task._base_validate.__globals__['read'] is task.read
    assert task._base_prepare.__globals__['read'] is task.read
    assert task._runtime['verify_input_caches'] is task._private['verify_input_caches']


def test_import_does_not_rebind_the_old_module(task):
    original = load(task.UPSTREAM, '_unchanged_fixed200_task8_for_revision2_test')
    assert original.KIND != task.KIND and original.TERMINAL_KIND != task.TERMINAL_KIND
    assert original.execute_prepared.__globals__['validate_prepared'] is original.validate_prepared
    assert '_task_fault_plan' not in original._ns and '_task_fault_plan' not in original.prepare.__globals__


def test_plan_hook_requires_context_and_full_genuine_replay(task, lineage):
    with pytest.raises(ValueError, match='pre-frozen'): task._task_fault_plan(lineage.candidate)
    token = task._DESIGN_CONTEXT.set(lineage.design)
    try:
        assert task._task_fault_plan(lineage.candidate) == lineage.frozen['view_plans']
        assert lineage.replayed == [(lineage.design, lineage.candidate)]
        with pytest.raises(ValueError, match='entire genuine'): task._task_fault_plan({'view_plans': lineage.candidate['view_plans']})
    finally: task._DESIGN_CONTEXT.reset(token)


def test_changed_design_implementation_is_rejected(task, lineage, monkeypatch):
    monkeypatch.setattr(task, 'DESIGN_SHA256', '0' * 64)
    token = task._DESIGN_CONTEXT.set(lineage.design)
    try:
        with pytest.raises(ValueError, match='implementation changed'): task._task_fault_plan(lineage.candidate)
        assert not lineage.replayed
    finally: task._DESIGN_CONTEXT.reset(token)


def test_lineage_binds_failure_source_candidate_and_exact_recipes(task, lineage):
    out = lineage.tmp / 'new_task'; out.mkdir()
    token = task._DESIGN_CONTEXT.set(lineage.design)
    try: record = task._freeze_task_lineage(lineage.candidate, lineage.actual, lineage.sf, out)
    finally: task._DESIGN_CONTEXT.reset(token)
    value = task.read(record)
    assert value['original_candidate'] == lineage.candidate_ref
    assert value['failed_task8'] == lineage.frozen['ancestry']['failed_task8']
    assert value['unchanged_genuine_goal'] == lineage.goal
    assert value['actual_task_validation_inherited'] is False
    assert value['recipe'] == task.recipes()
    assert str(task.UPSTREAM) in value['recipe'] and str(task.DESIGN_PATH) in value['recipe']
    assert value['qualified'] is value['normal_all12_QA_passed'] is False


@pytest.mark.parametrize('field', ['unchanged_source_manifest', 'unchanged_genuine_goal', 'original_candidate'])
def test_lineage_rejects_changed_originals(task, lineage, field):
    changed = deepcopy(lineage.frozen); changed['ancestry'][field] = lineage.save(field + '.json', {'different': True})
    ref = lineage.save('wrong_' + field + '.json', changed)
    with pytest.raises(ValueError, match='exact healthy'):
        task._lineage_value(ref, lineage.candidate_ref, lineage.source_ref, lineage.goal, lineage.source_preparation)


def test_source_failure_rejects_before_output_allocation(task, lineage, monkeypatch, tmp_path):
    monkeypatch.setattr(task.source, 'validate_source', lambda _: {'kind': task.source.SOURCE_KIND, 'passed': False})
    output = ROOT / 'outputs/tmp' / (tmp_path.name + '_revision2_source_must_fail')
    with pytest.raises(ValueError, match='genuine complete'): task.prepare(lineage.source_ref, output, fault_design=lineage.design)
    assert not output.exists() and task._DESIGN_CONTEXT.get() is None


def test_real_prepare_uses_new_design_hook_before_allocating_inputs(task, lineage, monkeypatch, tmp_path):
    monkeypatch.setattr(task.source, 'validate_source', lambda _: lineage.actual)
    monkeypatch.setattr(task.source, 'validate_prepared', lambda _: lineage.sf)
    def reject(*args, **kwargs): raise ValueError('Full design replay rejected the unit fixture')
    monkeypatch.setattr(task, 'design', SimpleNamespace(validate_revision=reject))
    output = ROOT / 'outputs/tmp' / (tmp_path.name + '_revision2_design_must_fail')
    with pytest.raises(ValueError, match='Full design replay rejected'):
        task.prepare(lineage.source_ref, output, fault_design=lineage.design)
    assert not output.exists() and task._DESIGN_CONTEXT.get() is None


def prepared_fixture(task, lineage, output):
    output.mkdir()
    value = task._lineage_value(lineage.design, lineage.candidate_ref, lineage.source_ref, lineage.goal, lineage.source_preparation)
    record = task.write(output / 'task_fault_lineage.json', value)
    frozen = {'kind': task.KIND, 'version': 1, 'task_fault_lineage': record,
              'candidate_preparation': lineage.candidate_ref, 'source_manifest': lineage.source_ref,
              'source_preparation': lineage.source_preparation, 'genuine_goal': lineage.goal}
    task.write(output / 'preparation.json', frozen)
    return frozen


def test_cold_validation_restores_design_context_and_replays_current_candidate(task, lineage, monkeypatch):
    output = lineage.tmp / 'prepared'; frozen = prepared_fixture(task, lineage, output)
    def checked_base(folder):
        assert folder == output
        assert task._DESIGN_CONTEXT.get() == lineage.design
        task._task_fault_plan(lineage.candidate)
        return frozen
    monkeypatch.setattr(task, '_base_validate', checked_base)
    assert task.validate_prepared(output) == frozen
    assert lineage.replayed[-1] == (lineage.design, lineage.candidate)
    assert task._DESIGN_CONTEXT.get() is None


def test_missing_lineage_cannot_validate(task, lineage):
    out = lineage.tmp / 'missing_lineage'; out.mkdir()
    task.write(out / 'preparation.json', {'kind': task.KIND, 'version': 1})
    with pytest.raises(KeyError, match='task_fault_lineage'): task.validate_prepared(out)


def test_old_prepared_kind_is_rejected_by_original_full_validation(task, lineage):
    output = lineage.tmp / 'old_kind'; frozen = prepared_fixture(task, lineage, output)
    frozen['kind'] = 'prepared_fixed_operating_reports_200_task_engineering'
    # Explicit fixture mutation is not an actual frozen preparation.
    (output / 'preparation.json').write_text(json.dumps(frozen))
    with pytest.raises(ValueError, match='scope or recipe'): task.validate_prepared(output)


def test_lineage_byte_mutation_is_detected(task, lineage):
    output = lineage.tmp / 'mutated'; frozen = prepared_fixture(task, lineage, output)
    Path(frozen['task_fault_lineage']['path']).write_text('{}')
    with pytest.raises(ValueError): task.validate_prepared(output)


def test_execute_failure_still_writes_terminal_with_bound_lineage(task, lineage, monkeypatch):
    output = lineage.tmp / 'execute'; frozen = prepared_fixture(task, lineage, output)
    monkeypatch.setattr(task, '_base_validate', lambda _: frozen)
    runtime = task.execute_prepared.__globals__
    fake_audit = SimpleNamespace(update_run=lambda **kw: None, export=lambda: None,
                                 snapshot=lambda: {}, events=lambda: [], db=SimpleNamespace(close=lambda: None))
    monkeypatch.setitem(runtime, 'AuditStore', lambda *a, **kw: fake_audit)
    monkeypatch.setitem(runtime, 'DashboardServer', lambda *a, **kw: SimpleNamespace(start=lambda: 'unit-test-no-server', stop=lambda: None))
    monkeypatch.setitem(runtime, 'ProducerLease', lambda *a: SimpleNamespace(acquire=lambda: SimpleNamespace(release=lambda: None)))
    monkeypatch.setattr(task.source, 'stage', lambda *a, **kw: nullcontext())
    def fail_source(_): raise ValueError('Unit source cold proof failure; no engine was constructed')
    monkeypatch.setattr(task.source, 'validate_source', fail_source)
    monkeypatch.setitem(runtime, 'ThreadCappedResourceLibreOfficeEngine', lambda *a, **kw: pytest.fail('No native engine may be created'))
    with pytest.raises(RuntimeError, match='preserve original'): task.execute_prepared(output)
    terminal = task.read(output / 'terminal.json')
    assert terminal['kind'] == task.TERMINAL_KIND and terminal['passed'] is False
    assert terminal['actual_LO_calls_started'] == terminal['actual_LO_calls_completed'] == 0
    assert terminal['task_fault_lineage'] == frozen['task_fault_lineage']
    assert terminal['source_manifest'] == lineage.source_ref and terminal['retry'] == 0


def test_completed_validation_does_not_accept_a_different_lineage(task, lineage, monkeypatch):
    output = lineage.tmp / 'completed'; frozen = prepared_fixture(task, lineage, output)
    monkeypatch.setattr(task, 'validate_prepared', lambda _: frozen)
    wrong = lineage.save('wrong_lineage.json', {})
    terminal = lineage.save('wrong_terminal.json', {'preparation': task.reference(output / 'preparation.json'), 'task_fault_lineage': wrong})
    with pytest.raises(ValueError, match='lost its task-design lineage'): task.validate_completed(terminal)


def test_cli_preparation_does_not_execute(task, lineage, monkeypatch):
    seen = []
    monkeypatch.setattr(task, 'prepare', lambda source, output, *, fault_design: seen.append((source, output, fault_design)) or {})
    monkeypatch.setattr(task, 'execute_prepared', lambda *a: pytest.fail('Preparation cannot call the engine'))
    output = lineage.tmp / 'cli'
    assert task.main(['--source-manifest', lineage.source_ref['path'], '--fault-design', lineage.design['path'], '--output', str(output)]) == 0
    assert seen == [(Path(lineage.source_ref['path']), output, Path(lineage.design['path']))]


def test_context_is_separate_for_concurrent_preparations(task, lineage):
    other = deepcopy(lineage.frozen); other['view_plans'] = lineage.save('other_plan.json', {'revision': 'other'})
    other_ref = lineage.save('other_design.json', other)
    def lookup(record):
        token = task._DESIGN_CONTEXT.set(record)
        try: return task._task_fault_plan(lineage.candidate)
        finally: task._DESIGN_CONTEXT.reset(token)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lookup, [lineage.design, other_ref])) == [lineage.frozen['view_plans'], other['view_plans']]
    assert task._DESIGN_CONTEXT.get() is None


def test_unknown_plan_read_shape_fails_closed(task, tmp_path, monkeypatch):
    raw = task.UPSTREAM.read_text().replace("plans = read(candidate['view_plans'])", "plans = read(candidate['other'])", 1)
    altered = tmp_path / 'altered_ancestor.py'; altered.write_text(raw)
    monkeypatch.setattr(task, 'UPSTREAM', altered)
    monkeypatch.setattr(task, 'UPSTREAM_SHA256', hashlib.sha256(altered.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match='read changed shape'): task._namespace()
