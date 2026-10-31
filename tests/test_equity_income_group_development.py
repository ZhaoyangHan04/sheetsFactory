"""Pure two-mode snapshots with a mocked genuine family engineering boundary."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import FunctionType, SimpleNamespace
from zipfile import ZipFile, ZIP_STORED

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def factory(tmp_path, monkeypatch):
    p = ROOT/'scripts/prepare_equity_income_group_development.py'
    s = importlib.util.spec_from_file_location('_test_equity_development', p)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    genuine = m.validation_driver(); original = m.history_helper(); private = dict(vars(original))
    roots = (tmp_path/'history/difficulty', tmp_path/'history/research')
    for root in roots: root.mkdir(parents=True)
    private['HISTORY_ROOTS'] = roots
    for name, value in list(private.items()):
        if isinstance(value, FunctionType) and value.__globals__ is vars(original):
            bound = FunctionType(value.__code__, private, name, value.__defaults__, value.__closure__)
            bound.__kwdefaults__ = deepcopy(value.__kwdefaults__); private[name] = bound
    history = SimpleNamespace(**private); cold = []
    def completed(value):
        cold.append(value); actual = m.read(value)
        if actual.get('TEST_ONLY_cold_rejection'): raise ValueError('Mocked genuine cold engineering rejection')
        return actual
    monkeypatch.setattr(m, 'history_helper', lambda: history)
    monkeypatch.setattr(m, 'validation_driver', lambda: SimpleNamespace(validate_completed=completed, recipes=genuine.recipes))
    monkeypatch.setattr(m.runner, 'run_evaluation', lambda *a, **k: pytest.fail('Preparation cannot launch a model'))
    monkeypatch.setattr(m, 'verify_local_base_image', lambda *a, **k: pytest.fail('Preparation cannot inspect Docker'))
    def book(path, value, repacked=False):
        path.parent.mkdir(parents=True, exist_ok=True); w = openpyxl.Workbook(); sh = w.active; sh.title = 'Statements'
        sh['A1'] = 'Read Me policy applies'; sh['B1'] = value; w.save(path); w.close()
        if repacked:
            with ZipFile(path) as z: members = [(item, z.read(item.filename)) for item in z.infolist()]
            with ZipFile(path, 'w', ZIP_STORED) as z:
                z.comment = b'Equivalent material, different ZIP bytes'
                for item, raw in members: z.writestr(item.filename, raw)
        return m.ref(path)
    def make(name='first', *, repacked=False, terminal_changes=None, candidate_changes=None):
        folder = tmp_path/name; folder.mkdir(); goal = book(folder/'goal.xlsx', 100, repacked)
        modes = {}; views = {}
        for mode in m.MODES:
            instruction = folder/(mode+'.md')
            instruction.write_text('Complete the forecast statements. Use the business policies in Read Me.\n')
            views[mode] = {'instruction': m.ref(instruction)}
            modes[mode] = {'input': book(folder/(mode+'.xlsx'), None if mode == 'financial_modeling' else 99, repacked),
                'goal': goal, 'instruction': m.ref(instruction), 'complete_D_count': 1,
                'controls': {'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}}
        raw = m.write(folder/'specification.json', {'kind':'TEST_ONLY_public_business_inputs'})
        candidate = m.write(folder/'candidate.json', {'kind':'prepared_unverified_synthetic_equity_income_group_pair',
            'version':1, 'source_type':'new_synthetic', 'official_workbook_seed_used':False,
            'dimensions':{'entities':6,'quarters':12,'scenarios':3}, 'specification':raw, 'views':views, **(candidate_changes or {})})
        source = m.write(folder/'source.json', {'kind':'TEST_ONLY_mocked_genuine_source3'})
        prepared = m.write(folder/'engineering_preparation.json', {'kind':'prepared_equity_income_group_task_engineering',
            'version':1, 'source_manifest':source, 'financial_target_count':6048, 'DBG_formula_root_count':216,
            'candidate_preparation':candidate, 'genuine_goal':goal})
        actual = m.write(folder/'engineering_terminal.json', {'kind':'complete_equity_income_group_task_engineering', 'version':1,
            'passed':True, 'actual_LO_calls_started':8, 'actual_LO_calls_completed':8, 'qualified':False,
            'normal_all12_QA_passed':False, 'source_manifest':source, 'preparation':prepared,
            'records':{'modes':modes}, **(terminal_changes or {})})
        return SimpleNamespace(module=m, root=folder, actual=actual, candidate=candidate,
            modes=modes, output=folder/'snapshot', history=history, cold=cold)
    return make


def test_both_snapshots_use_real_seventeen_file_exports_v4_and_original_public_bytes(factory):
    c = factory(); m = c.module; frozen = m.read(m.prepare(c.actual, c.output))
    assert len(c.cold) == 1 and frozen['both_materials_frozen_before_any_model'] is True
    assert frozen['mode_order'] == list(m.MODES)
    assert frozen['model'] == 'gpt-6.1-sol' and frozen['reasoning_effort'] == 'xhigh'
    assert frozen['effective_outer_retries'] == 0
    assert frozen['execution_budget'] == {'version':1,'elapsed_policy':'operational_guard','elapsed_guard_seconds':14400,'tool_budget_seconds':1800}
    assert not frozen['qualified'] and not frozen['normal_all12_QA_passed'] and not frozen['difficulty_claimed']
    for mode, record in frozen['modes'].items():
        export = Path(record['export_directory'])
        assert len([p for p in export.rglob('*') if p.is_file()]) == 17
        assert (export/'environment/input.xlsx').read_bytes() == m.checked(c.modes[mode]['input']).read_bytes()
        assert (export/'tests/reference.xlsx').read_bytes() == m.checked(c.modes[mode]['goal']).read_bytes()
        original = m.checked(record['original_instruction']).read_bytes()
        assert (export/'instruction.md').read_bytes() == original+b'\n---\nFile paths: read /app/input.xlsx and save the completed workbook to /app/output.xlsx.\n'
        assert m.inspect_resource_export(export, audit_path=record['worker_cap_audit']) == record['export_binding']
        source = m.read(record['source_view'])
        assert source['tool_time_policy_version'] == 4 and source['tool_time_policy'] == dict(m.runner.POLICY_V4)
        assert source['kind'] == 'synthetic_equity_income_group_prequality_development_source_v4'
        assert source['source_kind'] == 'synthetic_equity_income_management_group'
        assert 'linear_capital' not in source['kind']
        assert not Path(record['worker_cap_audit']['path']).is_relative_to(export)
    assert m.validate_prepared(c.output) == frozen and len(c.cold) == 2


@pytest.mark.parametrize('change', [
    {'kind':'period_boundary_actual_shared_engineering_validation_v2','version':2},
    {'kind':'complete_equity_income_group_task_engineering','version':2},
    {'actual_LO_calls_completed':7}, {'qualified':True}, {'TEST_ONLY_cold_rejection':True},
])
def test_wrong_family_incomplete_or_json_success_cannot_bypass_cold_gate(factory, change):
    c = factory(terminal_changes=change)
    with pytest.raises(ValueError): c.module.prepare(c.actual, c.output)
    assert len(c.cold) == 1 and not c.output.exists()


@pytest.mark.parametrize('change', [{'official_workbook_seed_used':True}, {'source_type':'old_native_source'},
    {'dimensions':{'entities':1,'quarters':1,'scenarios':1}}])
def test_first_material_scope_rejects_other_sources_and_toys(factory, change):
    c = factory(candidate_changes=change)
    with pytest.raises(ValueError): c.module.prepare(c.actual, c.output)


def test_modified_export_and_policy_drift_fail_closed(factory):
    c = factory(); m = c.module; frozen = m.read(m.prepare(c.actual, c.output))
    path = Path(frozen['modes']['debugging']['export_directory'])/'environment/input.xlsx'
    path.write_bytes(path.read_bytes()+b'changed')
    with pytest.raises(ValueError): m.validate_prepared(c.output)


def test_shared_durable_reservation_prevents_renamed_or_repacked_retry(factory):
    first = factory('first'); other = factory('renamed', repacked=True); m = first.module
    left = m.read(m.prepare(first.actual, first.output)); right = m.read(m.prepare(other.actual, other.output))
    mode = 'financial_modeling'
    assert left['modes'][mode]['material_task_version'] == right['modes'][mode]['material_task_version']
    assert first.modes[mode]['input']['sha256'] != other.modes[mode]['input']['sha256']
    started = m.reserve(first.output, left, mode, first.root/'evaluation')
    reservation = m.read(started)['reservation']
    with pytest.raises(ValueError, match='permanent first attempt'):
        m.reserve(other.output, right, mode, other.root/'evaluation')
    assert m.checked(reservation).exists()
    assert m.read(reservation)['no_resampling_after_success_failure_or_infrastructure'] is True


def test_both_modes_reserve_concurrently_under_one_global_lock(factory):
    c = factory(); m = c.module; frozen = m.read(m.prepare(c.actual, c.output))
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = [f.result() for f in [pool.submit(m.reserve, c.output, frozen, mode, c.root/('evaluation_'+mode)) for mode in m.MODES]]
    assert {m.read(r)['mode'] for r in result} == set(m.MODES)
    assert len({m.read(r)['reservation']['path'] for r in result}) == 2


@pytest.mark.parametrize('failure,passed,effective', [(None,True,1),('cumulative_tool_budget_exhausted',False,0),('incomplete_tool_timing',None,None)])
def test_raw_reward_is_separate_from_time_and_infrastructure_eligibility(factory, failure, passed, effective):
    c = factory(); score = c.module.effective_score({'status':'scored','raw_verifier_reward':1,'failure_kind':failure,'tool_time':{'passed':passed}},
        {'status':'completed'}, {'passed':True,'complete':True})
    assert score['raw_verifier_reward'] == 1 and score['effective_reward'] == effective
