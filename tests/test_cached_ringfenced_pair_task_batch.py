"""Small real OOXML/export fixtures; native/source boundaries are explicit mocks."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from xml.etree import ElementTree as X
from zipfile import ZipFile, ZIP_DEFLATED

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location('cached_pair_tasks', ROOT/'scripts/build_cached_ringfenced_pair_task_batch.py')
m = importlib.util.module_from_spec(loader); loader.loader.exec_module(m)
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def caches(path, values):
    with ZipFile(path) as archive: parts = {name: archive.read(name) for name in archive.namelist()}
    for number, title in enumerate(('A', 'B', 'Group reporting'), 1):
        name = 'xl/worksheets/sheet'+str(number)+'.xml'; tree = X.fromstring(parts[name])
        for cell in tree.iter(NS+'c'):
            key = (title, cell.attrib['r'])
            if key not in values: continue
            for node in list(cell.findall(NS+'v')): cell.remove(node)
            value = values[key]
            if type(value) is bool: cell.set('t', 'b'); value = int(value)
            X.SubElement(cell, NS+'v').text = str(value)
        parts[name] = X.tostring(tree)
    with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
        for name, data in parts.items(): archive.writestr(name, data)


def book(path, *, bad=False):
    wb = openpyxl.Workbook(); wb.remove(wb.active)
    for name in ('A', 'B'):
        ws = wb.create_sheet(name)
        for point, value in {'A1': 'Supplied capital', 'B1': 10, 'A2': 'N/A', 'B2': '=B1*3' if bad else '=B1*2',
            'A3': 'Complete', 'B3': '=TRUE()', 'A4': 'Choice', 'B4': 0 if bad else 1}.items(): ws[point] = value
    ws = wb.create_sheet('Group reporting')
    for point, value in {'A1': 'Consolidated cash', 'B1': '=SUM(A!B2,B!B2)', 'A2': 'Complete', 'B2': '=AND(A!B3,B!B3)'}.items(): ws[point] = value
    wb.save(path); wb.close()
    values = {(name, 'B2'): 30 if bad else 20 for name in ('A', 'B')}
    values.update({(name, 'B3'): True for name in ('A', 'B')}); values.update({('Group reporting', 'B1'): 60 if bad else 40, ('Group reporting', 'B2'): True})
    caches(path, values); return m.ref(path)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    goal = book(tmp_path/'goal.xlsx'); dbg = book(tmp_path/'debug.native.xlsx', bad=True)
    mask = {'A': ['B2', 'B3', 'B4'], 'B': ['B2', 'B3', 'B4'], 'Group reporting': ['B1', 'B2']}
    plan = {'pair_id': 'R2-02', 'genuine_goal': goal, 'sheetnames': ['A', 'B', 'Group reporting'], 'FM_mask': mask,
        'FM_target_count': 8, 'DBG_formula_root_count': 2, 'DBG_choice_count': 2,
        'DBG_faults': [{'sheet': name, 'cell': 'B2', 'before': '=B1*2', 'after': '=B1*3'} for name in ('A', 'B')],
        'DBG_choices': [{'sheet': name, 'cell': 'B4', 'before': 1, 'after': 0} for name in ('A', 'B')],
        'whole_views_contract': m.write(tmp_path/'whole.json', {'fixed': True})}
    fm = tmp_path/'FM.native.xlsx'; m.task_views.transform(goal['path'], fm, m.task_views.actions(plan, m.MODES[0]))
    monkeypatch.setattr(m, 'COUNTS', {'formulas': 6, 'nonempty': 20, 'targets': 8})
    return {'plan': plan, 'actual': {m.MODES[0]: m.ref(fm), m.MODES[1]: dbg}, 'goal': goal}


class Audit:
    def __init__(self): self.events = []
    def update_run(self, **value): self.events.append(value)
    def export(self): pass


def mutate(path, sheet, point, value, *, style=None, merge=False):
    wb = openpyxl.load_workbook(path)
    wb[sheet][point] = value
    if style: wb[sheet][point].number_format = style
    if merge: wb[sheet].merge_cells('A1:B1')
    wb.save(path); wb.close()


def test_whole_union_audit_checks_both_modes_and_propagated_group_fields_once(fixture):
    audit = Audit(); result = m.audit_inputs(fixture['plan'], fixture['actual'], audit)
    assert result[m.MODES[0]]['complete_primary_difference_count'] == 8
    assert result[m.MODES[1]]['complete_primary_difference_count'] == 5
    for row in result.values():
        assert row['full_physical_union_count'] == 20 and row['full_source_formula_count'] == 6
        assert row['actual_Harbor_controls_pending'] and row['normal_all12_pending']
        assert row['native_two_input_typed_stability'] is None and row['synthetic_controls_reexecuted'] is False
    assert [row['worksheets_completed'] for row in audit.events] == [1, 2, 3]


@pytest.mark.parametrize('fault', ['given', 'formula', 'bool_type', 'NA', 'style', 'error', 'merge', 'extra', 'missing_target'])
def test_full_union_rejects_given_formula_layout_error_and_outside_scope_changes(fixture, fault):
    path = Path(fixture['actual'][m.MODES[1]]['path'])
    if fault == 'given': mutate(path, 'A', 'B1', 11)
    if fault == 'formula': mutate(path, 'A', 'B3', '=FALSE()')
    if fault == 'bool_type': mutate(path, 'A', 'B1', True)
    if fault == 'NA': mutate(path, 'A', 'A2', None)
    if fault == 'style': mutate(path, 'A', 'B1', 10, style='0.000')
    if fault == 'error': mutate(path, 'A', 'B2', '#DIV/0!')
    if fault == 'merge': mutate(path, 'A', 'B1', 10, merge=True)
    if fault == 'extra': mutate(path, 'A', 'C8', 1)
    if fault == 'missing_target': fixture['plan']['FM_mask']['A'].append('Z99'); fixture['plan']['FM_target_count'] += 1
    with pytest.raises(ValueError): m.audit_inputs(fixture['plan'], fixture['actual'], Audit())


def test_cache_clearing_transform_preserves_bool_na_context_and_given_source(fixture, tmp_path):
    before = m.ref(fixture['goal']['path'])
    for mode in m.MODES:
        output = tmp_path/(mode+'.xlsx')
        result = m.task_views.transform(before['path'], output, m.task_views.actions(fixture['plan'], mode))
        assert result['all_other_member_bytes_preserved'] and result['all_formula_caches_absent']
        count = m.task_views.cold_cache_census(output)
        assert count == (0 if mode == m.MODES[0] else 6)
        wb = openpyxl.load_workbook(output, read_only=True, data_only=True)
        assert wb['A']['A2'].value == 'N/A' and type(wb['A']['B1'].value) is int
        wb.close()
    assert m.ref(before['path']) == before


@pytest.fixture
def flow(fixture, tmp_path, monkeypatch):
    root = tmp_path/'root'; root.mkdir(); monkeypatch.setattr(m, 'ROOT', root)
    source = m.write(tmp_path/'source.json', {'kind': 'synthetic_mocked_source_boundary'})
    certificate = m.write(tmp_path/'certificate.json', {'mocked': True})
    instructions = {}
    for mode in m.MODES:
        path = tmp_path/(mode+'.md'); path.write_text('Complete the investment schedules.\n'); instructions[mode] = m.ref(path)
    definition = deepcopy(fixture['plan']); sf = {'certificate': certificate}
    admission = {'pair_id': 'R2-02', 'preparation': source}
    state = {'count': 0, 'closed': 0, 'events': [], 'receipts': [], 'fail_at': None}
    monkeypatch.setattr(m, 'recipes', lambda: {'frozen_fixture': True})
    monkeypatch.setattr(m, 'FIRST_FIVE', Path(source['path']))
    monkeypatch.setattr(m, 'admit', lambda record: (admission, sf, definition, instructions, [source]))
    class Engine:
        def __init__(self, *args, **kwargs): pass
        def recalculate(self, before, after):
            state['count'] += 1
            if state['count'] == state['fail_at']: raise RuntimeError('retained simulated native failure')
            mode = m.MODES[state['count']-1]
            shutil.copyfile(fixture['actual'][mode]['path'], after)
            state['receipts'].append(m.write(tmp_path/('receipt'+str(state['count'])+'.json'), {'container_id': str(state['count'])*64}))
            return after
        def metadata(self): return {'actual_resource_receipts': list(state['receipts'])}
    monkeypatch.setattr(m.helpers, 'engine_class', lambda: Engine)
    monkeypatch.setattr(m.dual, 'resource_check', lambda record, **kw: {'receipt': record, 'container_id': m.read(record)['container_id']})
    monkeypatch.setattr(m.dual, 'owned_cleanup', lambda values: {'passed': True, 'all_owned_containers_absent': True, 'owned': values})
    class Panel:
        def __init__(self, *args, **kwargs): pass
        def start(self): state['events'].append('panel_before_admit'); return 'http://127.0.0.1:1/'
        def stop(self): state['closed'] += 1
    monkeypatch.setattr(m.dual, 'DashboardServer', Panel)
    return fixture, source, tmp_path/'out', state


def test_two_call_workflow_exports_real17_files_without_claiming_new_five_controls(flow):
    fixture, source, output, state = flow
    terminal = m.read(m.run(source, output))
    assert state['count'] == 2 and state['closed'] == 1
    assert terminal['count'] == 2 and terminal['actual_LO_calls_completed'] == 2
    assert terminal['synthetic_control_calls'] == 0 and terminal['new_model_solver_financial_forward_Harbor_calls'] == 0
    assert terminal['actual_Harbor_controls_pending'] and terminal['normal_all12_pending']
    assert m.read(output/'plans_frozen.json')['actual_new_input_LO_limit'] == 2
    for task in terminal['tasks']:
        folder = Path(task['task_directory'])
        assert len([p for p in folder.rglob('*') if p.is_file()]) == 17
        assert m.export.inspect_resource_export(folder, audit_path=task['worker_cap_audit']) == task['harbor_export_binding']
        engineering = m.read(task['individual_engineering'])
        assert engineering['actual_programmatic_controls'] is None
        assert engineering['retained_local_controls_are_design_witnesses_only']
        assert engineering['native_error_count'] == 0
        assert (folder/'tests/reference.xlsx').read_bytes() == Path(fixture['goal']['path']).read_bytes()
    assert m.read(output/'owned_resources_absent.json')['all_owned_containers_absent']
    with pytest.raises(ValueError): m.run(source, output)


@pytest.mark.parametrize('failed_call', [1, 2])
def test_native_failure_is_retained_once_with_no_model_zero_or_retry(flow, failed_call):
    _, source, output, state = flow; state['fail_at'] = failed_call
    with pytest.raises(RuntimeError): m.run(source, output)
    failure = m.read(output/'failure.json')
    assert state['count'] == failed_call and failure['actual_LO_calls_started'] == failed_call
    assert failure['outer_retries'] == 0 and failure['failure_is_not_model_zero']
    assert not (output/'engineered_batch.json').exists()
    if failed_call == 2: assert failure['owned_cleanup'] is not None


def test_final_artifact_mutation_prevents_batch_admission(flow, monkeypatch):
    _, source, output, _ = flow; original = m.export.inspect_resource_export; count = []
    def inspect(*args, **kwargs):
        result = original(*args, **kwargs); count.append(result)
        if len(count) == 2: Path(source['path']).write_text('{}')
        return result
    monkeypatch.setattr(m.export, 'inspect_resource_export', inspect)
    with pytest.raises(ValueError, match='immutable'): m.run(source, output)
    assert not (output/'engineered_batch.json').exists()


def test_first_panel_precedes_potentially_long_source_admission(flow, monkeypatch):
    _, source, output, state = flow
    original = m.admit
    def admitted(record):
        assert state['events'] == ['panel_before_admit']; return original(record)
    monkeypatch.setattr(m, 'admit', admitted)
    m.run(source, output)


def test_permanent_pair_reservation_prevents_second_run_in_fresh_directory(flow):
    _, source, output, state = flow; m.run(source, output)
    with pytest.raises(FileExistsError): m.run(source, output.parent/'another')
    assert state['count'] == 2


@pytest.fixture
def admission(tmp_path, monkeypatch):
    def artifact(name, value): return m.write(tmp_path/(name+'.json'), value)
    arbitrary = artifact('proof', {'proof': 'explicit fixture, actual source boundary mocked'})
    original = artifact('original', {})
    profiles = ['L360-P02', 'L360-P07']; public = artifact('public', {'mandates': [{'local_profile_id': p} for p in profiles]})
    prospective = artifact('prospective', {'fixed': True})
    design = artifact('design', {'original_whole_pair_pool': prospective, 'new_pairs': [{'id': 'R2-02', 'profiles': profiles}]})
    monkeypatch.setattr(m, 'FIRST_FIVE', Path(design['path'])); monkeypatch.setattr(m, 'FIRST_FIVE_SHA', design['sha256'])
    instructions = {}
    for mode, text in zip(m.MODES, (m.task_views.FM_BRIEF, m.task_views.DBG_BRIEF)):
        path = tmp_path/(mode+'.md'); path.write_text(text); instructions[mode] = m.ref(path)
    rows = []
    for index, profile in enumerate(profiles):
        fm = artifact(profile+'fm', {'mode': m.MODES[0]}); dbg = artifact(profile+'dbg', {'mode': m.MODES[1]})
        point = {'sheet': 'P001', 'cell': 'B36'}
        controls = artifact(profile+'control', {'observable_primary': point,
            'rewards': {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}})
        rows.append({'profile_id': profile, 'views': {m.MODES[0]: {'plan': fm}, m.MODES[1]: {'plan': dbg}},
            'control_primary': point, 'control_evidence': controls})
    pool = artifact('pool', {'kind': m.task_views.POOL_KIND, 'version': 1, 'counts': m.COUNTS,
        'mode_order': list(m.MODES), 'prospective': prospective, 'donors': rows})
    Path(original['path']).unlink(); original = artifact('original', {'whole_views_contract': pool, 'instruction_bytes': instructions})
    monkeypatch.setattr(m, 'ORIGINAL_PREPARATION', Path(original['path'])); monkeypatch.setattr(m, 'ORIGINAL_PREPARATION_SHA', original['sha256'])
    donor = [{'id': 'M0'+str(i), 'workbook': arbitrary} for i in (1, 2)]
    cert = artifact('certificate', {'prospective': prospective, 'pair_id': 'R2-02', 'contract': public, 'donors': donor})
    sf = artifact('preparation', {'certificate': cert, 'geometry': {key: m.COUNTS[key] for key in ('formulas', 'nonempty', 'targets')},
        'public_contract': public, 'local_composition': artifact('local', {'donors': donor}), 'report_plan': arbitrary, 'recipe': [arbitrary]})
    source = artifact('source', {'kind': 'completed_cached_ringfenced_pair_source_v1', 'version': 1,
        'pair_id': 'R2-02', 'passed': True, 'failure': None, 'preparation': sf, 'source': arbitrary,
        'actual_calls_started': 3, 'actual_calls_completed': 3, 'LO_calls': 3, 'records': {'audit': arbitrary},
        'actual_calls': [{'input': arbitrary, 'output': arbitrary, 'actual_resource_evidence': {'terminal': arbitrary}}]*3})
    state = {'validations': 0, 'compiled': 0}
    def validated(record): state['validations'] += 1; return m.read(record)
    monkeypatch.setattr(m, 'source_provider', lambda: SimpleNamespace(validate_completed=validated))
    def compiled(selected, local, report):
        state['compiled'] += 1
        assert len(selected) == 2 and len(local['donors']) == 2
        return {'sheetnames': ['A', 'B', 'Group reporting'], 'FM_mask': {}, 'DBG_faults': [], 'DBG_choices': [],
            'control_root': None, 'FM_target_count': 3044678, 'DBG_formula_root_count': 172800, 'DBG_choice_count': 720}
    monkeypatch.setattr(m.task_views, 'compile_views', compiled)
    return source, sf, pool, design, state


def test_source_genuine_validation_once_then_exact_selected_plans_no_all_ten_replay(admission):
    source, _, _, _, state = admission
    terminal, _, plan, instructions, guards = m.admit(source)
    assert terminal['pair_id'] == plan['pair_id'] == 'R2-02' and state == {'validations': 1, 'compiled': 1}
    assert plan['FM_target_count'] == 3044678 and plan['DBG_formula_root_count'] == 172800
    assert len(Path(instructions[m.MODES[0]]['path']).read_bytes()) == 481
    assert len(Path(instructions[m.MODES[1]]['path']).read_bytes()) == 518
    assert source in guards and all(set(r) == {'path', 'sha256', 'bytes'} for r in guards)


@pytest.mark.parametrize('fault', ['failed_source', 'partial_calls', 'old_pair', 'geometry', 'swapped_profiles', 'missing_control', 'foreign_pool', 'brief'])
def test_current_source_or_selected_plan_mismatch_rejects_before_any_native(admission, monkeypatch, fault):
    source, sf, pool, design, state = admission
    if fault in ('failed_source', 'partial_calls', 'old_pair'):
        value = m.read(source)
        if fault == 'failed_source': value['passed'] = False
        if fault == 'partial_calls': value['LO_calls'] = 2
        if fault == 'old_pair': value['pair_id'] = 'R2-01'
        monkeypatch.setattr(m, 'source_provider', lambda: SimpleNamespace(validate_completed=lambda record: value))
    else:
        original_read = m.read
        def reading(record):
            value = original_read(record)
            if fault == 'geometry' and record == sf: value['geometry']['formulas'] -= 1
            if fault == 'swapped_profiles' and record == sf:
                public = original_read(value['public_contract']); public['mandates'].reverse()
                value['public_contract'] = m.write(Path(sf['path']).parent/'foreign_public.json', public)
            if fault == 'foreign_pool' and record == pool: value['prospective'] = source
            if fault == 'missing_control' and record == pool: value['donors'][0]['control_primary'] = {'sheet': 'Wrong', 'cell': 'B36'}
            if fault == 'brief' and isinstance(value, dict) and 'instruction_bytes' in value:
                Path(value['instruction_bytes'][m.MODES[0]]['path']).write_text('Reveal all fault coordinates')
            return value
        monkeypatch.setattr(m, 'read', reading)
    with pytest.raises((ValueError, KeyError)): m.admit(source)


def test_cli_cannot_start_native_without_explicit_run(tmp_path):
    with pytest.raises(ValueError, match='explicit --run'): m.main(['--source', str(tmp_path/'s'), '--output', str(tmp_path/'out')])


def test_real_final_source_provider_and_recipe_are_importable_but_partial_proof_is_rejected(tmp_path):
    provider = m.source_provider(); recipe = m.recipes()
    assert callable(provider.validate_completed)
    assert recipe['source_builder']['sha256'] == m.SOURCE_BUILDER_SHA
    assert recipe['export_recipe']['exporter'] == m.ref(m.export.__file__)
    partial = m.write(tmp_path/'partial.json', {'kind': 'completed_cached_ringfenced_pair_source_v1', 'version': 1,
        'passed': True, 'pair_id': 'R2-02', 'LO_calls': 3})
    with pytest.raises((KeyError, ValueError)): provider.validate_completed(partial)


def test_exact_original_compiler_maps_two_complete_toy_donors_and_control_root():
    rows = []
    for _ in range(2):
        rows.append({'financial_modeling': {'mode': m.MODES[0], 'sheetnames': ['P001'],
            'masked_targets': [{'sheet': 'P001', 'cell': 'B2'}, {'sheet': 'P001', 'cell': 'B4'}]},
            'debugging': {'mode': m.MODES[1], 'sheetnames': ['P001'],
            'formula_edits': [{'sheet': 'P001', 'cell': 'B2', 'before': '=B1*2', 'after': '=B1*3'}],
            'choice_edits': [{'sheet': 'P001', 'cell': 'B4', 'before': 1, 'after': 0}]},
            'control_primary': {'sheet': 'P001', 'cell': 'B2'}})
    composed = {'donors': [{'id': 'M01', 'sheet_map': {'P001': 'P02 - P001'}},
        {'id': 'M02', 'sheet_map': {'P001': 'P07 - P001'}}]}
    plan = m.task_views.compile_views(rows, composed, {'sheet': 'Group reporting', 'financial': ['B1', 'B2']}, toy=True)
    assert plan['FM_target_count'] == 6 and plan['DBG_formula_root_count'] == 2 and plan['DBG_choice_count'] == 2
    assert plan['control_root']['sheet'] == 'P02 - P001'
    assert set(m.task_views.actions(plan, m.MODES[1])) == {'P02 - P001', 'P07 - P001'}


def test_source_provider_wrong_bytes_reject_before_import(tmp_path, monkeypatch):
    path = tmp_path/'provider.py'; path.write_text("raise AssertionError('must not import')")
    monkeypatch.setattr(m, 'SOURCE_BUILDER', path)
    with pytest.raises(ValueError, match='dependency'): m.source_provider()
