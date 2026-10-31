"""Pure fixture and mocked lifecycle tests; no Docker, native calculation or UI."""
from contextlib import nullcontext
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as E
from zipfile import ZipFile, ZIP_DEFLATED

from openpyxl import Workbook
import pytest

from sheets_factory.workbook.linear_capital_ringfenced_group import contract as c
from sheets_factory.workbook.linear_capital_ringfenced_group import group_report, stream_composition as core

ROOT = Path(__file__).resolve().parents[1]
S = '{'+core.S+'}'


@pytest.fixture
def task():
    path = ROOT/'scripts/run_ringfenced_group_source_pilot.py'
    spec = importlib.util.spec_from_file_location('_test_ringfenced_source_pilot', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def rewrite(path, destination, callback):
    with ZipFile(path) as source, ZipFile(destination, 'x', ZIP_DEFLATED) as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename.endswith('.xml'):
                root = E.fromstring(data)
                if callback(info.filename, root): data = E.tostring(root)
            target.writestr(info, data)
    return destination


@pytest.fixture
def fixture(task, tmp_path):
    donors = []; reports = []
    for index, (identity, prefix) in enumerate(core.FIXED, 1):
        book = Workbook(); sheet = book.active; sheet.title = 'GroupSummary'
        sheet['A1'] = 'Cash amounts / GBP pence'; sheet['A2'] = True; sheet['A3'] = 'n/a - provided'
        values = {}
        for si, sid in enumerate(c.SCENARIOS):
            annual = []
            for year in c.YEARS:
                row = {'year': year, 'fiscal_year': 2026+year}
                for fi, field in enumerate(c.GROUP_FIELDS, 3):
                    amount = index*100000+si*10000+year*100+fi
                    if field == 'net_lp_cashflow': amount = -amount
                    row[field] = amount; sheet.cell(4+si*20+year, fi, amount)
                annual.append(row)
            values[sid] = {'annual': annual}
        sheet['H1'] = '=C5*2'
        portfolio = book.create_sheet('Portfolio'); portfolio['B3'] = 1; portfolio['B369'] = 1; portfolio['B370'] = index*1000
        original = tmp_path/(identity+'_uncached.xlsx'); book.save(original); book.close()
        cached_value = 2*(index*100000+103)
        def cache_local(name, root, value=cached_value):
            if name == 'xl/worksheets/sheet1.xml':
                node = next(x for x in root.iter(S+'c') if x.get('r') == 'H1')
                node.find(S+'v').text = str(value); return True
        path = rewrite(original, tmp_path/(identity+'.xlsx'), cache_local)
        donors.append({'id': identity, 'display_name': 'Mandate '+str(index), 'prefix': prefix, 'workbook': c.reference(path)})
        reports.append(values)
    composed = core.compose_toy(donors, tmp_path/'locals.xlsx')
    contexts = [{'id': identity, 'profile_id': profile, 'specification': {'path': '/fixture/'+identity, 'sha256': '0'*64, 'bytes': 0}}
        for identity, profile in zip(c.MANDATE_ORDER, c.PROFILE_ORDER)]
    public = c.public_contract(contexts)
    combined = {sid: {'annual': [{'year': year, 'fiscal_year': 2026+year,
        **{field: sum(report[sid]['annual'][year-1][field] for report in reports) for field in c.GROUP_FIELDS}}
        for year in c.YEARS]} for sid in c.SCENARIOS}
    certificate = {'mathematical_composition_certified': True, 'new_group_source_admitted': False,
        'composition': {'unique_best': True, 'winner_objective_pence': 10000, 'winner_report': combined}}
    emitted = group_report.append_report(composed, public, tmp_path/'cold.xlsx')
    plan = group_report.plan(public, composed); expected = group_report.expectations(certificate, plan)
    frozen = {'local_composition': c.write(tmp_path/'local.json', composed), 'donors': donors,
        'report_plan': c.write(tmp_path/'plan.json', plan), 'report_expected': c.write(tmp_path/'expected.json', expected),
        'defined_names': [], 'geometry': emitted['geometry']}
    def native_cache(name, root):
        changed = False
        for node in root.iter(S+'c'):
            if node.find(S+'f') is None: continue
            if name.endswith('ringfenced_group_reporting.xml'):
                value = expected[node.get('r')]
                if value['type'] == 'boolean': node.set('t', 'b'); text = '1'
                else: text = value['value']
            else:
                index = int(name.split('/')[2].removeprefix('M'))
                text = str(2*(index*100000+103))
            E.SubElement(node, S+'v').text = text; changed = True
        return changed
    native = rewrite(tmp_path/'cold.xlsx', tmp_path/'native.xlsx', native_cache)
    return frozen, tmp_path/'cold.xlsx', native, composed, certificate


def test_complete_streamed_cold_and_native_audits(task, fixture):
    frozen, cold, native, _, _ = fixture
    clear = task.audit_workbook(cold, frozen, cold=True)
    actual = task.audit_workbook(native, frozen)
    assert clear['passed'] and clear['cold_formula_caches_physically_absent']
    assert actual['passed'] and actual['cells_checked'] == frozen['geometry']['nonempty']
    assert actual['formulas_checked'] == 306 and actual['native_error_count'] == 0


@pytest.mark.parametrize('change', ['given', 'formula', 'report', 'boolean_type', 'native_error', 'names'])
def test_complete_audit_rejects_actual_semantic_or_definition_changes(task, fixture, tmp_path, change):
    frozen, _, native, _, _ = fixture
    changed = False
    def mutate(name, root):
        nonlocal changed
        if changed: return False
        if change == 'names' and name == 'xl/workbook.xml':
            names = root.find(S+'definedNames')
            if names is None: names = E.SubElement(root, S+'definedNames')
            E.SubElement(names, S+'definedName', name='Extra').text = '1'
            changed = True; return True
        for node in root.iter(S+'c'):
            report = name.endswith('ringfenced_group_reporting.xml')
            if change == 'given' and not report and node.get('r') == 'C5': node.find(S+'v').text = '999'
            elif change == 'formula' and not report and node.get('r') == 'H1': node.find(S+'f').text = 'C5*3'
            elif change == 'report' and report and node.get('r') == 'C10': node.find(S+'v').text = '999'
            elif change == 'boolean_type' and report and node.get('r') == 'B6': node.attrib.pop('t'); node.find(S+'v').text = '1'
            elif change == 'native_error' and report and node.get('r') == 'C10': node.set('t', 'e'); node.find(S+'v').text = '#NUM!'
            else: continue
            changed = True; return True
        return False
    altered = rewrite(native, tmp_path/(change+'.xlsx'), mutate)
    result = task.audit_workbook(altered, frozen)
    assert changed and not result['passed'] and result['mismatch_count'] > 0


def test_financial_two_decimals_accept_noise_but_given_literals_stay_exact(task, fixture, tmp_path):
    frozen, _, native, _, _ = fixture
    def mutate(name, root):
        if '/funds/M01/' not in name: return False
        for node in root.iter(S+'c'):
            if node.get('r') == 'H1': node.find(S+'v').text = '200206.004'; return True
        return False
    altered = rewrite(native, tmp_path/'noise.xlsx', mutate)
    assert task.audit_workbook(altered, frozen)['passed']


def test_empty_physical_cache_node_is_not_a_cold_start(task, fixture, tmp_path):
    frozen, cold, _, _, _ = fixture
    def mutate(name, root):
        if not name.endswith('ringfenced_group_reporting.xml'): return False
        node = next(x for x in root.iter(S+'c') if x.find(S+'f') is not None)
        E.SubElement(node, S+'v'); return True
    changed = rewrite(cold, tmp_path/'empty_v.xlsx', mutate)
    with pytest.raises(ValueError, match='physical cold formula cache'): task.audit_workbook(changed, frozen, cold=True)


def test_complete_census_rejects_omission_even_within_caps(task, fixture):
    frozen, cold, _, _, _ = fixture
    frozen['geometry']['nonempty'] += 1
    with pytest.raises(ValueError, match='exact complete source census'): task.audit_workbook(cold, frozen, cold=True)


@pytest.mark.parametrize('field', ['memory', 'time', 'pid', 'budget', 'image', 'truncate', 'cap', 'boolean_version', 'float_cpu'])
def test_profile_allows_only_fixed_geometry_and_identity(task, field):
    profile = task.load_profile()
    if field == 'memory': profile['docker_resources']['source']['memory_bytes'] *= 2
    elif field == 'time': profile['timeouts']['workbook_file_seconds'] += 1
    elif field == 'pid': profile['docker_resources']['agent']['pids_limit'] += 1
    elif field == 'budget': profile['solver_tool_budget']['seconds'] += 1
    elif field == 'image': profile['image']['id'] = 'sha256:'+'0'*64
    elif field == 'truncate': profile['limits']['truncate'] = True
    elif field == 'boolean_version': profile['version'] = True
    elif field == 'float_cpu': profile['docker_resources']['source']['cpus'] = 2.0
    else: profile['limits']['source_physical_formulas'] += 1
    with pytest.raises(ValueError, match='hardware/time/budget unchanged'): task.load_profile(profile)


def test_isolated_resource_constructor_preserves_old_globals_without_docker(task, tmp_path, monkeypatch):
    old_loader, old_class = task.resource_base.load_runtime_profile, task.cap_base.ThreadCappedResourceLibreOfficeEngine
    monkeypatch.setattr(task.resource_base.LibreOfficeEngine, '_run', lambda *args, **kwargs: pytest.fail('No Docker allowed'))
    cap = task.engines()
    engine = cap.ThreadCappedResourceLibreOfficeEngine(tmp_path, task.PROFILE, role='source', receipt_directory=tmp_path/'receipts')
    assert engine.timeout_seconds == 600 and engine.profile['docker_resources']['source']['memory_bytes'] == 32*1024**3
    assert task.resource_base.load_runtime_profile is old_loader and task.cap_base.ThreadCappedResourceLibreOfficeEngine is old_class
    with pytest.raises(ValueError, match='Unsupported prospective runtime profile'): old_loader(task.PROFILE)


def mock_lifecycle(task, tmp_path, monkeypatch, *, bad_stage=None):
    output = tmp_path/'prepared'; output.mkdir(); cold = output/'cold.xlsx'; cold.write_bytes(b'cold')
    c.write(output/'preparation.json', {'fixture': True})
    frozen = {'cold_start': c.reference(cold), 'recipe': {}, 'donors': []}
    calls = []; stability = []; history = []
    monkeypatch.setattr(task, 'validate_prepared', lambda _: frozen)
    monkeypatch.setattr(task, 'recipes', lambda: {})
    class Audit:
        def __init__(self, *args): self.db = SimpleNamespace(close=lambda: None)
        def update_run(self, **kwargs): pass
        def export(self): pass
        def snapshot(self): return {}
        def events(self, *args): return []
    class Panel:
        def __init__(self, *args, **kwargs): pass
        def start(self): return 'http://fixture.invalid'
        def stop(self): pass
    class Engine:
        def __init__(self, *args, **kwargs): pass
        def ensure_image(self): return 'fixture'
        def recalculate(self, source, destination):
            index = len(calls)+1; calls.append((source, destination)); destination.write_bytes(('native'+str(index)).encode())
            history.append(c.write(output/(str(index)+'_resource.json'), {'source': c.reference(source), 'container_id': f'{index:064x}'}))
            return destination
        def metadata(self): return {'actual_resource_receipts': history}
    def evidence(call, record, frozen, *, resource_validator):
        actual = c.read(record)
        assert actual['source'] == call['input']
        return {'terminal': record, 'container_id': actual['container_id']}
    def absence(rows):
        return {'all_owned_containers_absent': True, 'daemon_reachable': True,
            'owned': [{'full_id': row['actual_resource_evidence']['container_id'], 'absent': True} for row in rows]}
    helper = SimpleNamespace(stage=lambda *args: nullcontext(), owned_absence=absence,
        resource_support=lambda: SimpleNamespace(validate_actual_call=lambda *args: None))
    monkeypatch.setattr(task, 'support', lambda: helper)
    monkeypatch.setattr(task, 'engines', lambda: SimpleNamespace(ThreadCappedResourceLibreOfficeEngine=Engine, validate_capped_call=evidence))
    monkeypatch.setattr(task, 'AuditStore', Audit); monkeypatch.setattr(task, 'DashboardServer', Panel)
    monkeypatch.setattr(task, 'audit_workbook', lambda path, frozen: {'passed': Path(path).stem != bad_stage})
    def compare(left, goal, right): stability.append((left, goal, right)); return {'reward': 1}
    monkeypatch.setattr(task.sparse, 'compare_files', compare)
    return output, calls, stability


def test_three_chained_calls_two_stabilities_full_completed_replay_and_no_retry(task, tmp_path, monkeypatch):
    output, calls, stability = mock_lifecycle(task, tmp_path, monkeypatch)
    terminal_ref = task.execute_prepared(output); terminal = c.read(terminal_ref)
    assert terminal['passed'] and terminal['LO_calls'] == terminal['actual_calls_completed'] == 3
    assert len(calls) == 3 and len(stability) == 2
    assert calls[1][0] == calls[0][1] and calls[2][0] == calls[1][1]
    assert task.validate_completed(terminal_ref) == terminal
    with pytest.raises(ValueError, match='zero retries'): task.execute_prepared(output)
    assert len(calls) == 3
    terminal['records']['cleanup'] = c.write(output/'bad_cleanup.json', {'all_owned_containers_absent': True,
        'daemon_reachable': True, 'owned': [{'full_id': '0'*64, 'absent': True}]*3})
    changed = c.write(output/'bad_terminal.json', terminal)
    with pytest.raises(ValueError, match='Cleanup must cover exactly'): task.validate_completed(changed)


def test_first_bad_native_audit_stops_without_later_calls_and_preserves_failure(task, tmp_path, monkeypatch):
    output, calls, stability = mock_lifecycle(task, tmp_path, monkeypatch, bad_stage='source1')
    with pytest.raises(RuntimeError, match='preserve terminal'): task.execute_prepared(output)
    terminal = c.read(output/'terminal.json')
    assert not terminal['passed'] and len(calls) == terminal['LO_calls'] == 1 and stability == []
    assert 'failure_cleanup' in terminal['records'] and terminal['actual_calls_completed'] == 1


def test_reservation_race_rechecks_after_lease_without_replacing_previous_attempt(task, tmp_path, monkeypatch):
    output, calls, _ = mock_lifecycle(task, tmp_path, monkeypatch)
    released = []
    class Lease:
        def __init__(self, path): pass
        def acquire(self): c.write(output/'started.json', {'original_attempt': True}); return self
        def release(self): released.append(True)
    monkeypatch.setattr(task, 'ProducerLease', Lease)
    with pytest.raises(ValueError, match='zero retries'): task.execute_prepared(output)
    assert released == [True] and calls == [] and not (output/'terminal.json').exists()
    assert c.read(output/'started.json') == {'original_attempt': True}


def test_finalizer_failure_writes_failed_terminal_instead_of_losing_evidence(task, tmp_path, monkeypatch):
    output, calls, _ = mock_lifecycle(task, tmp_path, monkeypatch)
    class BadPanel:
        def __init__(self, *args, **kwargs): pass
        def start(self): return 'http://fixture.invalid'
        def stop(self): raise OSError('fixture panel shutdown')
    monkeypatch.setattr(task, 'DashboardServer', BadPanel)
    with pytest.raises(RuntimeError, match='preserve terminal'): task.execute_prepared(output)
    terminal = c.read(output/'terminal.json')
    assert len(calls) == 3 and terminal['failure']['type'] == 'FinalizationFailure' and terminal['finalization_errors']


@pytest.mark.parametrize('problem', ['failed_certificate', 'partial_composition', 'wrong_lineage'])
def test_prepare_rejects_partial_or_wrong_whole_evidence_before_allocation(task, tmp_path, monkeypatch, problem):
    certificate = {'path': '/not/read', 'sha256': '0'*64, 'bytes': 0}
    def validate(_):
        if problem == 'failed_certificate': raise ValueError('Genuine certificate rejected')
        return {'donors': []}
    monkeypatch.setattr(task.composition, 'validate_certificate', validate)
    local = {'kind': 'uncalculated_ringfenced_group_stream_composition', 'prototype_toy_only': False,
        'sheet_count': 1479 if problem == 'partial_composition' else 1480,
        'geometry': {'formulas': 4989312, 'nonempty': 7094264, 'targets': 6088752},
        'ancestry': {'composition_certificate': {'other': True}}, 'donors': []}
    local_ref = c.write(tmp_path/'local.json', local); destination = tmp_path/'new_pilot'
    with pytest.raises(ValueError): task.prepare(certificate, local_ref, destination)
    assert not destination.exists()


def test_prepare_run_combination_rejects_before_any_preparation(task, monkeypatch):
    monkeypatch.setattr(task, 'prepare', lambda *args: pytest.fail('Must reject before allocation'))
    with pytest.raises(ValueError, match='separate command'): task.main(['--certificate', '/c', '--local-composition', '/l', '--output', '/o', '--run'])
