from copy import deepcopy
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

from openpyxl import Workbook, load_workbook
import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('remaining_r2_controls', ROOT/'scripts/resume_ringfenced_pair_task8_remaining_v1.py')
m = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(m)


def book(path, cells, caches=None):
    wb = Workbook(); ws = wb.active; ws.title = 'Model'
    for address, value in cells.items():
        ws[address] = value
    wb.save(path); wb.close()
    if caches:
        with ZipFile(path) as source:
            members = {name: source.read(name) for name in source.namelist()}
        tree = ET.fromstring(members['xl/worksheets/sheet1.xml'])
        for cell in tree.iter(m.NS+'c'):
            if cell.attrib['r'] in caches:
                old = cell.find(m.NS+'v')
                if old is None:
                    old = ET.SubElement(cell, m.NS+'v')
                old.text = str(caches[cell.attrib['r']])
        members['xl/worksheets/sheet1.xml'] = ET.tostring(tree)
        with ZipFile(path, 'w', ZIP_DEFLATED) as target:
            for name, value in members.items():
                target.writestr(name, value)
    return m.ref(path)


class Audit:
    def update_run(self, **values):
        pass
    def export(self):
        pass


def case(tmp_path):
    healthy = {'A1': 'Source facts', 'B1': 10, 'B2': '=B1*2', 'B3': '=100+B2', 'B4': 1}
    goal = book(tmp_path/'goal.xlsx', healthy, {'B2': 20, 'B3': 120})
    results = {}
    for name in ('FM_input1', 'FM_input2'):
        results[name] = book(tmp_path/(name+'.xlsx'), {'A1': 'Source facts', 'B1': 10})
    for name in ('DBG_input1', 'DBG_input2'):
        values = {**healthy, 'B2': '=B1*3', 'B4': 0}
        results[name] = book(tmp_path/(name+'.xlsx'), values, {'B2': 30, 'B3': 130})
    results['equivalent'] = book(tmp_path/'equivalent.xlsx', {**healthy, 'B2': '=0+(B1*2)'}, {'B2': 20, 'B3': 120})
    results['FM_missed_root'] = book(tmp_path/'FM_missed_root.xlsx', {k: v for k, v in healthy.items() if k != 'B2'}, {'B3': 120})
    results['DBG_missed_root'] = book(tmp_path/'DBG_missed_root.xlsx', {**healthy, 'B2': '=B1*3'}, {'B2': 30, 'B3': 130})
    results['extra_change'] = book(tmp_path/'extra_change.xlsx', {**healthy, 'A1': 'Source facts [control]'}, {'B2': 20, 'B3': 120})
    plan = {'sheetnames': ['Model'], 'FM_mask': {'Model': ['B2', 'B3', 'B4']},
            'DBG_faults': [{'sheet': 'Model', 'cell': 'B2', 'after': '=B1*3'}],
            'DBG_choices': [{'sheet': 'Model', 'cell': 'B4', 'after': 0}]}
    f = {'definition': m.write(tmp_path/'plan.json', plan), 'genuine_goal': goal, 'source_formula_count': 2,
         'financial_target_count': 3, 'source_manifest': {'test_only': True}}
    return f, results


def test_full_union_controls_and_complete_D_match_frozen_grader(tmp_path):
    f, results = case(tmp_path)
    actual = m.audit_complete(f, results, tmp_path, Audit())
    for mode, prefix in zip(m.MODES, ('FM', 'DBG')):
        item = actual[mode]
        assert item['complete_primary_difference'] == ['Model!B2', 'Model!B3', 'Model!B4']
        assert item['complete_primary_difference_count'] == 3
        assert item['native_two_input_typed_stability'] is True
        for role, result in (('oracle', f['genuine_goal']), ('nop', results[prefix+'_input2']),
                             ('equivalent', results['equivalent']), ('missed_root', results[prefix+'_missed_root']),
                             ('extra_change', results['extra_change'])):
            reference = m.grader.compare_files(results[prefix+'_input2']['path'], f['genuine_goal']['path'], result['path'])
            evidence = item['actual_programmatic_controls'][role]
            assert evidence['reward'] == reference['reward']
            assert evidence['expected_change_count'] == reference['expected_change_count']
            assert evidence['actual_change_count'] == reference['actual_change_count']
            assert evidence['missing_change_count'] == len(reference['missing_changes'])
            assert evidence['extra_change_count'] == len(reference['extra_changes'])
            assert evidence['wrong_value_count'] == len(reference['wrong_values'])


@pytest.mark.parametrize('mutation', ['raw_fact', 'retained_formula', 'missing_mask', 'changed_choice', 'native_error', 'unstable'])
def test_real_input_contract_defects_rejected(tmp_path, mutation):
    f, results = case(tmp_path)
    target = Path(results['DBG_input2']['path'])
    healthy = {'A1': 'Source facts', 'B1': 10, 'B2': '=B1*3', 'B3': '=100+B2', 'B4': 0}
    cache = {'B2': 30, 'B3': 130}
    if mutation == 'raw_fact': healthy['B1'] = 11
    if mutation == 'retained_formula': healthy['B3'] = '=200+B2'
    if mutation == 'missing_mask':
        target = Path(results['FM_input2']['path']); healthy = {'A1': 'Source facts', 'B1': 10, 'B2': 0}; cache = {}
    if mutation == 'changed_choice': healthy['B4'] = 1
    if mutation == 'native_error': healthy['B3'] = '#DIV/0!'; cache = {'B2': 30}
    if mutation == 'unstable': cache['B3'] = 131
    role = 'FM_input2' if mutation == 'missing_mask' else 'DBG_input2'
    results[role] = book(target, healthy, cache)
    with pytest.raises(ValueError):
        m.audit_complete(f, results, tmp_path, Audit())


def test_dual_reader_matches_native_grader_dates_booleans_and_cached_formulas(tmp_path):
    p = tmp_path/'typed.xlsx'
    book(p, {'A1': datetime(2026, 1, 1), 'A2': timedelta(hours=26), 'A3': True,
             'A4': '=SUM(1,2)', 'A5': 'A & B'}, {'A4': 3})
    wb = load_workbook(p, read_only=True, data_only=True)
    try:
        dual, _ = m.sheet_cells(wb.worksheets[0])
        reference = dict(m.grader._sparse_cells(wb.worksheets[0]))
        assert {k: (v['value'], v['data_type']) for k, v in dual.items()} == {k: (v['value'], v['data_type']) for k, v in reference.items()}
        assert dual[(4, 1)]['formula'] == '=SUM(1,2)'
    finally:
        wb.close()


def test_dual_reader_expands_shared_formulas_and_excludes_merged_children(tmp_path):
    p = tmp_path/'shared.xlsx'
    wb = Workbook(); ws = wb.active; ws['A1'] = 'Heading'; ws.merge_cells('A1:C1')
    ws['A2'] = 4; ws['B2'] = '=A2*2'; ws['A3'] = 5; ws['B3'] = '=A3*2'
    wb.save(p); wb.close()
    with ZipFile(p) as source:
        members = {name: source.read(name) for name in source.namelist()}
    tree = ET.fromstring(members['xl/worksheets/sheet1.xml'])
    for cell in tree.iter(m.NS+'c'):
        address = cell.attrib['r']
        if address in ('B2', 'B3'):
            cell.find(m.NS+'f').attrib.update(t='shared', si='0')
            if address == 'B3': cell.find(m.NS+'f').text = None
            cell.find(m.NS+'v').text = '8' if address == 'B2' else '10'
        if address == 'B1':
            ET.SubElement(cell, m.NS+'v').text = '99'
    members['xl/worksheets/sheet1.xml'] = ET.tostring(tree)
    with ZipFile(p, 'w', ZIP_DEFLATED) as target:
        for name, value in members.items(): target.writestr(name, value)
    wb = load_workbook(p, read_only=True, data_only=True)
    try:
        cells, merges = m.sheet_cells(wb.worksheets[0])
        assert cells[(2, 2)]['formula'] == '=A2*2'
        assert cells[(3, 2)]['formula'] == '=A3*2'
        assert (1, 2) not in cells and merges == [(1, 1, 1, 3)]
        assert {k: v['value'] for k, v in cells.items()} == {k: v['value'] for k, v in m.grader._sparse_cells(wb.worksheets[0])}
    finally:
        wb.close()


def test_remaining_stage_inventory_is_fixed_and_spent_calls_are_never_recalculated():
    assert m.SPENT == ('FM_input1', 'FM_input2', 'DBG_input1', 'DBG_input2')
    assert m.REMAINING == ('equivalent', 'FM_missed_root', 'DBG_missed_root', 'extra_change')
    import ast
    tree = ast.parse(Path(m.__file__).read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'recalculate']
    assert len(calls) == 1
    loop = next(n for n in ast.walk(tree) if isinstance(n, ast.For) and any(c is calls[0] for c in ast.walk(n)))
    assert ast.unparse(loop.iter) == 'enumerate(REMAINING, 5)'


def resource_record(tmp_path):
    cid = 'a'*64; when = '2026-11-01T07:00:00+00:00'
    event = {'container_id': cid, 'variable': 'MAX_CONCURRENCY', 'values': ['MAX_CONCURRENCY=2'], 'inspected_at': when}
    d = {'status': 'completed', 'actual_resources_verified': True, 'thread_cap_verified': True,
        'requested_resources': {'cpus': 2, 'memory_bytes': 34359738368, 'pids_limit': 256},
        'actual_resources': {'cpus_nanoseconds': 2000000000, 'memory_bytes': 34359738368, 'pids_limit': 256},
        'container_id': cid, 'profile': m.ref(m.PROFILE), 'image_id': m.read_profile_image(),
        'create_command': ['docker', 'create', '--env', 'MAX_CONCURRENCY=2', m.read_profile_image()],
        'started_at': when, 'finished_at': when, 'thread_cap_before': event,
        'thread_cap_after': {**event, 'exit_code_observed': '0'}}
    return d


@pytest.mark.parametrize('mutation', [None, 'memory', 'pids', 'threads', 'container', 'image', 'status'])
def test_actual_resource_contract_requires_observations(tmp_path, mutation):
    d = resource_record(tmp_path)
    if mutation == 'memory': d['actual_resources']['memory_bytes'] = 1
    if mutation == 'pids': d['actual_resources']['pids_limit'] = 1
    if mutation == 'threads': d['thread_cap_before']['values'] = ['MAX_CONCURRENCY=16']
    if mutation == 'container': d['thread_cap_after']['container_id'] = 'b'*64
    if mutation == 'image': d['image_id'] = 'sha256:'+'b'*64
    if mutation == 'status': d['status'] = 'running'
    record = m.write(tmp_path/'resource.json', d)
    if mutation is None:
        assert m.resource_check(record)['passed'] is True
    else:
        with pytest.raises(ValueError):
            m.resource_check(record)


def test_preflight_cannot_accept_a_renamed_or_different_attempt(tmp_path):
    with pytest.raises(ValueError, match='only the original'):
        m.preflight(tmp_path)
