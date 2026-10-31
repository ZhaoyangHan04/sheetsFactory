"""No-service preparation, real temporary audit DB, and small physical XML tests."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as X
from zipfile import ZipFile, ZIP_DEFLATED

from openpyxl import Workbook
import pytest

ROOT = Path(__file__).resolve().parents[1]
CERTIFICATE = ROOT / 'outputs/research/ringfenced_P01_P02_P07_P09_pure_20261031T224404Z/cold_certificate/certificate.json'


@pytest.fixture
def task():
    path = ROOT / 'scripts/compose_ringfenced_group_pilot.py'
    spec = importlib.util.spec_from_file_location('_test_ringfenced_pure_pilot', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.fixture
def small_receipt(task, tmp_path):
    donors = []
    for i in (1, 2):
        book = Workbook(); sheet = book.active; sheet.title = 'Report'
        sheet['A1'] = 'n/a - provided'; sheet['A2'] = True; sheet['A3'] = 15
        sheet['A4'] = '=A3*2'; sheet['B4'] = '=SUM(A3,1)'
        file = tmp_path / f'donor{i}.xlsx'; book.save(file); book.close()
        donors.append({'id': f'M0{i}', 'prefix': f'P0{i} - ', 'workbook': task.c.reference(file)})
    return task.core.compose_toy(donors, tmp_path / 'toy_composed.xlsx')


def test_physical_audit_streams_all_caches_counts_and_provided_semantics(task, small_receipt):
    census = {**{key: small_receipt['geometry'][key] for key in ('formulas', 'nonempty')}, 'sheets': 2}
    progress = []
    result = task.audit_workbook(small_receipt, expected=census, progress=progress.append)
    assert result['census'] == census and result['all_formula_caches_physically_empty'] is True
    assert result['all_donor_given_semantic_digests_match'] is True
    assert result['given_cells_checked'] == 6 and len(progress) == 2
    assert result['source_classification'] is False


def alter_package(task, receipt, destination, change):
    with ZipFile(receipt['output']['path']) as src, ZipFile(destination, 'x', ZIP_DEFLATED) as out:
        changed = False
        for info in src.infolist():
            data = src.read(info.filename)
            if not changed and '/worksheets/sheet' in info.filename and info.filename.endswith('.xml'):
                root = X.fromstring(data)
                if change == 'cache':
                    cell = next(node for node in root.iter(task.S + 'c') if node.find(task.S + 'f') is not None)
                    X.SubElement(cell, task.S + 'v').text = '30'
                else:
                    cell = next(node for node in root.iter(task.S + 'c') if node.get('r') == 'A3')
                    cell.find(task.S + 'v').text = '16'
                data = X.tostring(root); changed = True
            out.writestr(info, data)
    result = deepcopy(receipt); result['output'] = task.c.reference(destination); return result


@pytest.mark.parametrize('change,match', [('cache', 'cache must be absent'), ('given', 'supplied literal')])
def test_physical_audit_rejects_seeded_cache_or_changed_given_value(task, small_receipt, tmp_path, change, match):
    changed = alter_package(task, small_receipt, tmp_path / (change + '.xlsx'), change)
    census = {**{key: small_receipt['geometry'][key] for key in ('formulas', 'nonempty')}, 'sheets': 2}
    with pytest.raises(ValueError, match=match): task.audit_workbook(changed, expected=census)


def test_under_cap_omission_is_rejected_by_exact_physical_census(task, small_receipt):
    census = {**{key: small_receipt['geometry'][key] for key in ('formulas', 'nonempty')}, 'sheets': 3}
    with pytest.raises(ValueError, match='full physical census'): task.audit_workbook(small_receipt, expected=census)


def test_shared_string_NA_semantics_remain_identical_after_streaming_merge(task, tmp_path):
    donors = []
    for i in (1, 2):
        original = tmp_path / f'inline{i}.xlsx'; book = Workbook(); book.active['A1'] = 'n/a - supplied'; book.active['B1'] = '=1+1'
        book.save(original); book.close(); target = tmp_path / f'shared{i}.xlsx'
        with ZipFile(original) as src, ZipFile(target, 'x', ZIP_DEFLATED) as out:
            for info in src.infolist():
                data = src.read(info.filename)
                if info.filename == 'xl/worksheets/sheet1.xml':
                    root = X.fromstring(data); cell = next(n for n in root.iter(task.S + 'c') if n.get('r') == 'A1')
                    cell.set('t', 's'); cell.remove(cell.find(task.S + 'is')); X.SubElement(cell, task.S + 'v').text = '0'; data = X.tostring(root)
                elif info.filename == 'xl/_rels/workbook.xml.rels':
                    root = X.fromstring(data); X.SubElement(root, '{http://schemas.openxmlformats.org/package/2006/relationships}Relationship',
                        Id='rIdSST', Type=task.R.strip('{}') + '/sharedStrings', Target='sharedStrings.xml'); data = X.tostring(root)
                elif info.filename == '[Content_Types].xml':
                    root = X.fromstring(data); X.SubElement(root, '{http://schemas.openxmlformats.org/package/2006/content-types}Override',
                        PartName='/xl/sharedStrings.xml', ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml'); data = X.tostring(root)
                out.writestr(info, data)
            out.writestr('xl/sharedStrings.xml', '<sst xmlns="' + task.S.strip('{}') + '" count="1" uniqueCount="1"><si><t>n/a - supplied</t></si></sst>')
        donors.append({'id': f'M0{i}', 'prefix': f'P0{i} - ', 'workbook': task.c.reference(target)})
    receipt = task.core.compose_toy(donors, tmp_path / 'shared_result.xlsx')
    assert task.audit_workbook(receipt, expected={'sheets': 2, 'formulas': 2, 'nonempty': 4})['all_donor_given_semantic_digests_match'] is True


def test_real_metadata_preparation_is_zero_cold_replay_and_zero_emission(task, monkeypatch, tmp_path):
    monkeypatch.setattr(task, 'ROOT', tmp_path)
    monkeypatch.setattr(task, 'composition', SimpleNamespace(validate_certificate=lambda *_: pytest.fail('No cold replay during preparation')))
    output = tmp_path / 'outputs' / 'prepared'
    record = task.prepare(CERTIFICATE, output)
    value = task.validate_prepared(output)
    assert task.c.read(record) == value and value['workbooks_written'] == 0
    assert value['native_solver_LO_model_Harbor_calls'] == 0
    assert value['expected_census'] == {'sheets': 1480, 'formulas': 4989312, 'nonempty': 7094264}
    assert not (output / 'locals_uncalculated.xlsx').exists()


def test_wrong_certificate_ref_fails_before_preparation_allocation(task, monkeypatch, tmp_path):
    monkeypatch.setattr(task, 'ROOT', tmp_path)
    fake = tmp_path / 'passed.json'; fake.write_text('{"passed":true}')
    output = tmp_path / 'outputs' / 'must_not_exist'
    with pytest.raises(ValueError, match='exact fixed first-four'): task.prepare(fake, output)
    assert not output.exists()


def test_recipe_mutation_rejects_prepared_record(task, monkeypatch, tmp_path):
    monkeypatch.setattr(task, 'ROOT', tmp_path); output = tmp_path / 'outputs' / 'prepared'
    task.prepare(CERTIFICATE, output)
    f = task.c.read(output / 'preparation.json'); f['expected_census']['formulas'] -= 1
    (output / 'preparation.json').write_text(json.dumps(f))
    with pytest.raises(ValueError, match='scope changed'): task.validate_prepared(output)


def mock_run(task, monkeypatch, tmp_path, *, cold_error=False, compose_error=False, export_error=False):
    monkeypatch.setattr(task, 'ROOT', tmp_path)
    expected = task.c.read(CERTIFICATE); calls = []
    def cold(value):
        calls.append('genuine_cold')
        if cold_error: raise ValueError('The genuine fourth local proof failed')
        return deepcopy(expected)
    monkeypatch.setattr(task, 'composition', SimpleNamespace(validate_certificate=cold))
    monkeypatch.setattr(task, 'DashboardServer', lambda *a, **kw: SimpleNamespace(start=lambda: 'unit-test-no-http-service', stop=lambda: None))
    original_core = task.core
    def emit(donors, output, **kw):
        calls.append('compose')
        assert calls == ['genuine_cold', 'compose']
        assert donors == expected['donors'] and kw['expected_census'] == task.EXPECTED
        assert kw['target_count'] == 6088752 and kw['mode'] == 'goal'
        if compose_error: raise ValueError('Unit emission failed after the genuine gate')
        Path(output).write_bytes(b'UNIT MOCK; this is not a certified workbook')
        return {'output': task.c.reference(output), 'donors': [], 'geometry': task.EXPECTED, 'unit_mock': True}
    monkeypatch.setattr(task, 'core', SimpleNamespace(__file__=original_core.__file__, syntax=original_core.syntax,
        FIXED=original_core.FIXED, _compose=emit, compose=lambda *_: pytest.fail('Never replay cold validation through public compose twice')))
    monkeypatch.setattr(task, 'audit_workbook', lambda value, progress=None: {'unit_mock': True, 'census': task.EXPECTED})
    if export_error:
        base = task.AuditStore
        class BrokenExport(base):
            def export(self): raise OSError('Unit audit projection export failed')
        monkeypatch.setattr(task, 'AuditStore', BrokenExport)
    output = tmp_path / 'outputs' / 'run'
    task.prepare(CERTIFICATE, output)
    return output, calls


def test_same_process_calls_genuine_gate_once_then_core_and_real_audit_db(task, monkeypatch, tmp_path):
    output, calls = mock_run(task, monkeypatch, tmp_path)
    terminal_ref = task.execute_prepared(output); terminal = task.c.read(terminal_ref)
    assert calls == ['genuine_cold', 'compose'] and terminal['passed'] is True
    assert terminal['native_solver_LO_model_Harbor_calls'] == terminal['model_input_tokens'] == terminal['model_output_tokens'] == 0
    assert terminal['source_classification'] is terminal['new_group_source_admitted'] is terminal['qualified'] is False
    summary = json.loads((output / 'audit/summary.json').read_text())
    assert summary['metrics']['llm_calls'] == summary['metrics']['total_tokens'] == 0
    assert len(summary['nodes']) == 3 and all(n['status'] == 'complete' for n in summary['nodes'])
    assert json.loads((output / 'producer.lock').read_text())['status'] == 'released'
    old = terminal_ref['sha256']
    with pytest.raises(ValueError, match='No retries'): task.execute_prepared(output)
    assert task.c.reference(output / 'terminal.json')['sha256'] == old and calls == ['genuine_cold', 'compose']


@pytest.mark.parametrize('where', ['cold', 'compose'])
def test_failure_terminal_and_original_reservation_are_retained(task, monkeypatch, tmp_path, where):
    output, calls = mock_run(task, monkeypatch, tmp_path, cold_error=where == 'cold', compose_error=where == 'compose')
    with pytest.raises(RuntimeError, match='retain the attempt'): task.execute_prepared(output)
    terminal = task.c.read(output / 'terminal.json')
    assert terminal['passed'] is False and terminal['failure']['type'] == 'ValueError'
    assert not (output / 'locals_uncalculated.xlsx').exists()
    assert calls == (['genuine_cold'] if where == 'cold' else ['genuine_cold', 'compose'])
    assert (output / 'attempt_reserved.json').exists()
    assert json.loads((output / 'producer.lock').read_text())['status'] == 'released'


def test_projection_export_failure_still_writes_final_terminal(task, monkeypatch, tmp_path):
    output, _ = mock_run(task, monkeypatch, tmp_path, export_error=True)
    terminal = task.c.read(task.execute_prepared(output))
    assert terminal['audit_export_errors'] and (output / 'audit/run.sqlite').is_file()
    assert terminal['source_classification'] is False


def test_zero_service_cli_does_not_run_until_explicit_flag(task, monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(task, 'prepare', lambda certificate, output: seen.append((certificate, output)) or {})
    monkeypatch.setattr(task, 'execute_prepared', lambda *_a, **_kw: pytest.fail('No run flag, no emission'))
    assert task.main(['--certificate', str(CERTIFICATE), '--output', str(tmp_path)]) == 0
    assert seen == [(CERTIFICATE, tmp_path)]
