"""Own-family schema, real exports and isolated first-attempt safeguards."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
from types import FunctionType, SimpleNamespace
import zipfile

import openpyxl
import pytest

# Import the inherited runner before the service guard: its installed directory
# hashing dependency performs a read-only local Git version probe on first load.
from sheets_factory.evaluation import native_transport_frontier as _loaded_runner

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_services(monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('No model, office or network service in pure development tests')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)


@pytest.fixture
def factory(tmp_path, monkeypatch):
    descriptor = importlib.util.spec_from_file_location('_test_independent_control_development', ROOT / 'scripts/prepare_independent_controls_development.py')
    module = importlib.util.module_from_spec(descriptor); descriptor.loader.exec_module(module)
    genuine = module.validation_driver(); original_history = module.history_helper(); private = dict(original_history.__dict__)
    roots = (tmp_path / 'history/difficulty', tmp_path / 'history/research')
    for root in roots: root.mkdir(parents=True)
    private['HISTORY_ROOTS'] = roots
    for name, value in list(private.items()):
        if isinstance(value, FunctionType) and value.__globals__ is original_history.__dict__:
            bound = FunctionType(value.__code__, private, name, value.__defaults__, value.__closure__)
            bound.__kwdefaults__ = deepcopy(value.__kwdefaults__); private[name] = bound
    history = SimpleNamespace(**private); cold_calls = []
    def validate_completed(value):
        cold_calls.append(value); actual = module.read(value)
        if actual.get('TEST_ONLY_cold_rejection'): raise ValueError('Explicit mocked genuine validator rejection')
        return actual
    mocked_driver = SimpleNamespace(validate_completed=validate_completed, recipes=genuine.recipes, STAGES=genuine.STAGES)
    monkeypatch.setattr(module, 'validation_driver', lambda: mocked_driver)
    monkeypatch.setitem(module._PRIVATE, 'validation_driver', lambda: mocked_driver)
    monkeypatch.setitem(module._PRIVATE, 'history_helper', lambda: history)
    monkeypatch.setattr(module, 'history_helper', lambda: history)
    monkeypatch.setattr(module._PRIVATE['runner'], 'run_evaluation', lambda *a, **k: pytest.fail('Cold prepare cannot start a model'))
    monkeypatch.setitem(module._PRIVATE, 'verify_local_base_image', lambda *a, **k: pytest.fail('Cold prepare cannot inspect Docker'))
    def book(path, value, repacked=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        workbook = openpyxl.Workbook(); sheet = workbook.active; sheet.title = 'Operations'
        sheet['A1'] = 'Provided policy'; sheet['B1'] = value; sheet['C1'] = datetime(2028, 2, 29)
        workbook.save(path); workbook.close()
        if repacked:
            with zipfile.ZipFile(path) as source: members = [(p, source.read(p.filename)) for p in source.infolist()]
            with zipfile.ZipFile(path, 'w', zipfile.ZIP_STORED) as output:
                output.comment = b'Only packaging changes; first-attempt identity must persist'
                for item, data in members: output.writestr(item.filename, data)
        return module.ref(path)
    def make(name='first', repacked=False, **changes):
        folder = tmp_path / name; folder.mkdir(); goal = book(folder / 'goal.xlsx', 100, repacked)
        modes = {mode: {'input': book(folder / (mode + '.xlsx'), None if mode == 'financial_modeling' else 99, repacked),
            'goal': goal, 'complete_D_count': module.EXPECTED_D[mode], 'controls': deepcopy(module.CONTROL_REWARDS)} for mode in module.MODES}
        public = module.synthetic.load(); assumptions = module.write(folder / 'assumptions.json', public); materials = {}
        for mode in module.MODES:
            key = module.MODE_KEYS[mode]; path = folder / (mode + '.md'); path.write_bytes(module.synthetic.public_brief(public, key).encode())
            materials[key] = {'kind': 'uncalculated_independent_controls_candidate_view', 'version': 1, 'mode': key,
                'public_instruction': module.ref(path), 'qualified': False}
        candidate = module.write(folder / 'candidate.json', {'kind': 'prepared_independent_controls_financial_candidate_pair', 'version': 1,
            'dimensions': {'financial_output_targets': 546}, 'public_assumptions': assumptions, 'materials': materials,
            'qualified': False, 'actual_LO_model_solver_Harbor_network_calls': 0})
        prepared = module.write(folder / 'engineering_preparation.json', {'candidate_manifest': candidate, 'expected_FM_D': 546, 'expected_DBG_D': 203})
        outputs = {name: modes['financial_modeling']['input'] if name.startswith('FM_input') else modes['debugging']['input'] if name.startswith('DBG_input') else goal for name in genuine.STAGES}
        actual = module.write(folder / 'engineering_terminal.json', {'kind': 'independent_controls_actual_shared_engineering_validation', 'version': 1,
            'passed': True, 'actual_LO_calls_started': 10, 'actual_LO_calls_completed': 10, 'qualified': False,
            'preparation': prepared, 'actual_calls': [{'role': name, 'output': outputs[name]} for name in genuine.STAGES], 'records': {'modes': modes}, **changes})
        return SimpleNamespace(module=module, root=folder, actual=actual, candidate=candidate, modes=modes, output=folder / 'snapshot',
            cold_calls=cold_calls, history=history, mocked_driver=mocked_driver)
    return make


def test_genuine_family_both_actual_inputs_real_17_file_exports_no_calls(factory):
    c = factory(); m = c.module; frozen = m.read(m.prepare(c.actual, c.output))
    assert frozen['kind'] == 'prequality_synthetic_independent_controls_development_pair'
    assert frozen['both_materials_frozen_before_any_model'] and frozen['mode_order'] == list(m.MODES)
    assert frozen['model_calls_during_preparation'] == frozen['LO_calls_during_preparation'] == frozen['effective_outer_retries'] == 0
    assert frozen['model'] == 'gpt-6.1-sol' and frozen['reasoning_effort'] == 'xhigh'
    assert frozen['execution_budget'] == {'version': 1, 'elapsed_policy': 'operational_guard', 'elapsed_guard_seconds': 14400, 'tool_budget_seconds': 1800}
    assert not frozen['qualified'] and not frozen['normal_all12_QA_passed'] and frozen['public_recovery_pending']
    assert m.read(c.candidate)['kind'] == 'prepared_independent_controls_financial_candidate_pair'
    for mode, material in frozen['modes'].items():
        export = Path(material['export_directory']); original = m.checked(material['original_instruction']).read_bytes()
        assert len([p for p in export.rglob('*') if p.is_file()]) == 17
        assert (export / 'environment/input.xlsx').read_bytes() == m.checked(c.modes[mode]['input']).read_bytes()
        assert (export / 'tests/reference.xlsx').read_bytes() == m.checked(c.modes[mode]['goal']).read_bytes()
        assert (export / 'instruction.md').read_bytes() == original + b'\n---\nFile paths: read /app/input.xlsx and save the completed workbook to /app/output.xlsx.\n'
        assert m._PRIVATE['inspect_resource_export'](export, audit_path=material['worker_cap_audit']) == material['export_binding']
        source = m.read(material['source_view']); task = source['tasks'][0]
        assert source['kind'] == 'independent_controls_prequality_development_source'
        assert source['source_kind'] == 'synthetic_independent_controls_financial_candidate'
        assert task['source_id'] == m.read(c.candidate)['public_assumptions']['sha256']
        assert material['task_id'].startswith(('fm-independent-controls-', 'dbg-independent-controls-'))
        assert source['native_transport_profile']['provider_overrides'] == {'stream_max_retries': 8}
    assert m.validate_prepared(c.output) == frozen and len(c.cold_calls) == 2


@pytest.mark.parametrize('changes', [
    {'kind': 'period_boundary_actual_shared_engineering_validation_v2', 'version': 2},
    {'kind': 'independent_controls_actual_shared_engineering_validation', 'version': 2},
    {'actual_LO_calls_completed': 9}, {'actual_LO_calls_started': 11}, {'qualified': True}, {'TEST_ONLY_cold_rejection': True}])
def test_old_or_fabricated_json_flags_do_not_bypass_cold_admission(factory, changes):
    c = factory(**changes)
    with pytest.raises(ValueError): c.module.prepare(c.actual, c.output)
    assert c.cold_calls == [c.actual] and not c.output.exists()


@pytest.mark.parametrize('tamper', ['candidate_kind', 'dimension', 'expected_D', 'stable_input', 'mode_controls', 'instruction'])
def test_exact_own_family_scope_stable_records_and_original_brief_required(factory, tamper):
    c = factory(); m = c.module; actual = m.read(c.actual); candidate = m.read(c.candidate); prep = m.read(actual['preparation'])
    if tamper == 'candidate_kind': candidate['kind'] = 'offline_synthetic_period_boundary_candidate'
    elif tamper == 'dimension': candidate['dimensions']['financial_output_targets'] = 657
    elif tamper == 'expected_D': prep['expected_DBG_D'] = 397
    elif tamper == 'stable_input': actual['records']['modes']['debugging']['input'] = actual['records']['modes']['financial_modeling']['input']
    elif tamper == 'mode_controls': actual['records']['modes']['debugging']['controls']['missed_root'] = 1
    else:
        instruction = Path(candidate['materials']['FM']['public_instruction']['path']); instruction.write_text('A different request\n')
        candidate['materials']['FM']['public_instruction'] = m.ref(instruction)
    Path(c.candidate['path']).write_text(json.dumps(candidate)); prep['candidate_manifest'] = m.ref(c.candidate['path'])
    Path(actual['preparation']['path']).write_text(json.dumps(prep)); actual['preparation'] = m.ref(actual['preparation']['path'])
    Path(c.actual['path']).write_text(json.dumps(actual))
    with pytest.raises(ValueError): m.prepare(m.ref(c.actual['path']), c.output)
    assert not c.output.exists()


def test_export_and_original_instruction_byte_tampering_rejected(factory):
    c = factory(); m = c.module; frozen = m.read(m.prepare(c.actual, c.output))
    path = Path(frozen['modes']['financial_modeling']['export_directory']) / 'environment/input.xlsx'
    path.write_bytes(path.read_bytes() + b'changed archive')
    with pytest.raises(ValueError): m.validate_prepared(c.output)


def test_immutable_lifecycle_hash_and_exact_family_transform_no_old_admission(factory, monkeypatch):
    c = factory(); m = c.module
    assert m._PRIVATE['_checked_engineering'] is m._checked_engineering
    assert m._PRIVATE['_instruction'] is m._instruction and 'BRIEFS' not in m._PRIVATE
    assert m._PRIVATE['family_adapter_proof']['schema_rebindings']['removed_domain_functions'] == 3
    monkeypatch.setattr(m, 'UPSTREAM_SHA256', '0' * 64)
    with pytest.raises(ValueError, match='lifecycle changed'): m._namespace()
    with pytest.raises(ValueError, match='lifecycle changed'): m.recipes()


def test_permanent_logical_identity_blocks_renamed_repacked_repeat(factory):
    a = factory('first'); b = factory('repacked', repacked=True); m = a.module
    first = m.read(m.prepare(a.actual, a.output)); second = m.read(m.prepare(b.actual, b.output))
    for mode in m.MODES:
        assert first['modes'][mode]['material_task_version'] == second['modes'][mode]['material_task_version']
        assert a.modes[mode]['input']['sha256'] != b.modes[mode]['input']['sha256']
    started = m.reserve(a.output, first, 'financial_modeling', a.root / 'evaluation')
    reservation = m.read(started)['reservation']; old = m.checked(reservation).read_bytes()
    assert m.read(reservation)['kind'] == 'independent_controls_permanent_material_first_attempt_reservation'
    with pytest.raises(ValueError, match='permanent first attempt'): m.reserve(b.output, second, 'financial_modeling', b.root / 'evaluation')
    assert m.checked(reservation).read_bytes() == old and not (b.output / 'financial_modeling_development_started.json').exists()


def test_same_material_double_launch_race_exactly_one_and_two_modes_independent(factory):
    c = factory(); m = c.module; f = m.read(m.prepare(c.actual, c.output))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(m.reserve, c.output, f, 'financial_modeling', c.root / ('evaluation' + str(i))) for i in range(2)]
        completed = []
        for future in futures:
            try: completed.append(future.result())
            except ValueError as error: assert 'permanent first attempt' in str(error)
    assert len(completed) == 1
    dbg = m.reserve(c.output, f, 'debugging', c.root / 'evaluation_debugging')
    assert m.read(dbg)['reservation']['path'] != m.read(completed[0])['reservation']['path']


def historical(c, name, *, mode='debugging', identity=None):
    m = c.module
    source = m.write(c.history.HISTORY_ROOTS[0] / name / 'source.json', {'material_task_version': identity} if identity else {'tasks': []})
    return m.write(c.history.HISTORY_ROOTS[0] / name / 'selection_manifest.json', {'tasks': [{'task_checksum': 'a' * 64, 'mode': mode}], 'source_manifest': source})


def test_append_only_unrelated_selections_captured_in_permanent_started_history(factory):
    c = factory(); m = c.module; old = historical(c, 'before')
    f = m.read(m.prepare(c.actual, c.output)); added = historical(c, 'after')
    assert old in f['selection_history_inventory'] and added not in f['selection_history_inventory']
    assert m.validate_prepared(c.output) == f
    started = m.read(m.reserve(c.output, f, 'financial_modeling', c.root / 'evaluation'))
    assert set(r['path'] for r in started['prior_model_selections']) == {old['path'], added['path']}
    reservation = m.read(started['reservation'])
    assert reservation['selection_history_inventory'] == started['history']
    assert reservation['prior_model_selection_inventory'] == started['prior_model_selections']


@pytest.mark.parametrize('tamper', ['same_material', 'changed_old', 'missing_old', 'corrupt_new'])
def test_history_same_material_or_corrupt_missing_evidence_rejected(factory, tamper):
    c = factory(); m = c.module; old = historical(c, 'before'); f = m.read(m.prepare(c.actual, c.output))
    if tamper == 'same_material': historical(c, 'new', mode='financial_modeling', identity=f['modes']['financial_modeling']['material_task_version'])
    elif tamper == 'changed_old': Path(old['path']).write_text('{"tasks":[]}')
    elif tamper == 'missing_old': Path(old['path']).unlink()
    else:
        new = historical(c, 'corrupt'); Path(new['path']).write_text('{"tasks":"malformed"}')
    with pytest.raises(ValueError): m.reserve(c.output, f, 'financial_modeling', c.root / 'evaluation')
    assert not (c.output / 'financial_modeling_development_started.json').exists()


@pytest.mark.parametrize('failure,clock,resources,effective,state', [
    (None, True, True, 1, 'complete'), ('cumulative_tool_budget_exhausted', False, True, 0, 'known_tool_budget_failure'),
    ('incomplete_tool_timing', None, True, None, 'unknown'), (None, True, False, None, 'unknown')])
def test_raw_reward_clock_and_resource_unknowns_remain_separate(factory, failure, clock, resources, effective, state):
    c = factory(); score = c.module.effective_score({'status': 'scored', 'raw_verifier_reward': 1, 'failure_kind': failure, 'tool_time': {'passed': clock}},
        {'status': 'completed'}, {'passed': resources, 'complete': resources})
    assert score['raw_verifier_reward'] == 1 and score['effective_reward'] == effective and score['state'] == state
