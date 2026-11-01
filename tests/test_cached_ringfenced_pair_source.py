from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location('cached_ringfenced_source', ROOT/'scripts/build_cached_ringfenced_pair_source.py')
m = importlib.util.module_from_spec(loader); loader.loader.exec_module(m)


@pytest.mark.parametrize('formula', [
    "=ROUND(('P001'!$B$35*SUM(Projects!$M$2,Scenarios!$D$5))/10000,0)",
    '=IF(SUMPRODUCT(--((Projects!$C$2:$C$361="R01")),Projects!$M$2:$M$361)>0,1,0)',
    '=IF(Projects!A1="Projects!A1",P001!B2,0)',
    '=IF(P001!A1="He said ""P001!A1""",Projects!B3,0)',
    "='Owner''s report'!A1+Projects!B1",
])
def test_qualifier_rename_is_exact_and_protects_excel_strings(formula):
    mapping = {key: 'P07 - '+key for key in ('P001', 'Projects', 'Scenarios', "Owner's report")}
    actual = m.formula_rename(formula, mapping)
    assert 'P07 - ' in actual
    for value in ('"R01"', '"Projects!A1"', '"He said ""P001!A1"""'):
        if value in formula:
            assert value in actual
    assert '[[' not in actual


@pytest.mark.parametrize('formula', [
    '=OtherMandate!A1', "='[private.xlsx]Projects'!A1", '=[private.xlsx]Projects!A1',
    '=Projects:Scenarios!A1', "='Projects:Scenarios'!A1",
])
def test_rename_rejects_external_cross_mandate_and_3d_references(formula):
    with pytest.raises(ValueError):
        m.formula_rename(formula, {'Projects': 'P07 - Projects', 'Scenarios': 'P07 - Scenarios'})


def test_rename_requires_bijection():
    with pytest.raises(ValueError):
        m.formula_rename('=A!A1+B!A1', {'A': 'Merged', 'B': 'Merged'})


def test_fast_rewriter_agrees_with_full_frozen_parser_on_production_formula_examples():
    strict = m.stream_composition._N['syntax'].rewrite_formula
    mapping = {key: 'P07 - '+key for key in ('P001', 'Projects', 'Scenarios', 'Portfolio')}
    formulas = [
        "=ROUND((('P001'!$B$35*SUM('Projects'!$M$2,'Scenarios'!$D$5))/10000),0)",
        '=IF(Portfolio!$B$1,SUMPRODUCT(Projects!$M$2:$M$361,Projects!$N$2:$N$361,--((Projects!$C$2:$C$361="R01"))),0)',
        "=IF('P001'!B3=0,0,SUM('P001'!B4:B9))",
    ]
    for formula in formulas:
        assert m.dual.same_formula(m.formula_rename(formula, mapping), strict(formula, mapping, local_sheet='P001'))


def matrix():
    ids = [f'P{i:03d}' for i in range(1, 361)]
    row = {'id': 'constraint', 'coefficients': [1]*360, 'limit': 200}
    model = {'project_ids': ids, 'rows': [deepcopy(row) for _ in range(941)], 'objective_pence': list(range(1, 361))}
    plan = {key: int(i < 100) for i, key in enumerate(ids)}
    return model, plan, sum(range(1, 101))


def test_exact_matrix_checks_all_original_integer_rows_and_objective():
    model, plan, objective = matrix()
    result = m.exact_matrix(model, plan, objective)
    assert result == {'rows_checked': 941, 'coefficients_checked': 338760, 'objective_pence': objective, 'passed': True}


@pytest.mark.parametrize('mutation', ['infeasible', 'objective', 'missing_row', 'float_coefficient', 'missing_choice', 'nonbinary_choice'])
def test_exact_matrix_does_not_accept_only_a_solver_pass_flag(mutation):
    model, plan, objective = matrix()
    if mutation == 'infeasible': model['rows'][0]['limit'] = 99
    if mutation == 'objective': objective += 1
    if mutation == 'missing_row': model['rows'].pop()
    if mutation == 'float_coefficient': model['rows'][0]['coefficients'][0] = 1.0
    if mutation == 'missing_choice': del plan['P001']
    if mutation == 'nonbinary_choice': plan['P001'] = True
    with pytest.raises(ValueError):
        m.exact_matrix(model, plan, objective)


def test_first_five_selection_and_three_native_source_calls_are_fixed():
    import ast
    assert m.FIRST_FIVE == ('R2-01', 'R2-02', 'R2-03', 'R2-04', 'R2-05')
    tree = ast.parse(Path(m.__file__).read_text())
    run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'run')
    calls = [node for node in ast.walk(run) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'recalculate']
    assert len(calls) == 1
    loop = next(node for node in ast.walk(run) if isinstance(node, ast.For) and any(child is calls[0] for child in ast.walk(node)))
    assert ast.unparse(loop.iter) == '(1, 2, 3)'
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ('solve', 'forward', 'optimize')]


def test_native_source_audit_preserves_complete_raw_number_types():
    assert m.raw_cell({'value': 1, 'data_type': 'n'}) == m.raw_cell({'value': 1.0, 'data_type': 'n'})
    assert m.raw_cell({'value': True, 'data_type': 'b'}) != m.raw_cell({'value': 1, 'data_type': 'n'})
    assert m.raw_cell({'value': 'NA', 'data_type': 's'}) == ('s', 'NA')
    assert m.raw_cell({'value': 1.00001, 'data_type': 'n'}) != m.raw_cell({'value': 1, 'data_type': 'n'})


def test_independent_arithmetic_proofs_may_differ_but_all_business_fields_must_agree():
    a = {'npv_pence': 1200, 'annual': [{'tax': 30, 'closing_debt': 4}], 'npv_exact': '1200/1', 'arithmetic_safety': True}
    b = {'npv_pence': 1200, 'annual': [{'tax': 30, 'closing_debt': 4}], 'npv_unrounded_decimal': '1200.0', 'arithmetic_bounds': []}
    assert m.same_business_values(a, b)
    b['annual'][0]['tax'] = 31
    assert not m.same_business_values(a, b)
    b['annual'][0]['tax'] = 30
    b['unexpected_business_field'] = 0
    assert not m.same_business_values(a, b)


def test_r2_01_is_never_rebuilt(tmp_path):
    with pytest.raises(ValueError, match='existing completed source'):
        m.prepare('R2-01', tmp_path/'duplicate')


def small_source(tmp_path, monkeypatch, mutation=None, cold=False):
    from openpyxl import Workbook
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile, ZIP_DEFLATED
    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    def write_book(path, sheets, caches):
        wb = Workbook(); wb.remove(wb.active)
        for name, values in sheets.items():
            ws = wb.create_sheet(name)
            for key, value in values.items(): ws[key] = value
        wb.save(path); wb.close()
        with ZipFile(path) as source:
            parts = {key: source.read(key) for key in source.namelist()}
        for i, name in enumerate(sheets, 1):
            key = f'xl/worksheets/sheet{i}.xml'; tree = ET.fromstring(parts[key])
            for cell in tree.iter(ns+'c'):
                address = cell.attrib['r']
                if (name, address) in caches:
                    value = cell.find(ns+'v')
                    if value is None: value = ET.SubElement(cell, ns+'v')
                    value.text = str(caches[name, address])
            parts[key] = ET.tostring(tree)
        with ZipFile(path, 'w', ZIP_DEFLATED) as target:
            for key, value in parts.items(): target.writestr(key, value)
        return m.ref(path)
    local = {'A1': 'Given context', 'B1': 10, 'B2': '=B1*2', 'A2': 'NA', 'B3': True}
    donors = []
    for name in ('A', 'B'):
        donors.append({'id': name, 'workbook': write_book(tmp_path/(name+'.xlsx'), {'Model': local}, {('Model', 'B2'): 20})})
    combined = {'A - Model': deepcopy(local), 'B - Model': deepcopy(local),
                m.group_report.SHEET: {'A1': 'Group report', 'B1': "=SUM('A - Model'!B2,'B - Model'!B2)"}}
    cache = {} if cold else {('A - Model', 'B2'): 20, ('B - Model', 'B2'): 20, (m.group_report.SHEET, 'B1'): 40}
    if mutation == 'literal': combined['A - Model']['B1'] = 10.00001
    if mutation == 'formula': combined['A - Model']['B2'] = '=B1*3'
    if mutation == 'cross_mandate': combined['A - Model']['B2'] = "='B - Model'!B1*2"
    if mutation == 'cached_value': cache['A - Model', 'B2'] = 21
    if mutation == 'raw_value': cache['A - Model', 'B2'] = 20.00001
    if mutation == 'boolean': combined['A - Model']['B3'] = 1
    if mutation == 'error': combined['A - Model']['B2'] = '#DIV/0!'
    if mutation == 'group': cache[m.group_report.SHEET, 'B1'] = 41
    if mutation == 'missing_cell': del combined['A - Model']['A2']
    out = write_book(tmp_path/'composed.xlsx', combined, cache)
    f = {'donors': donors, 'local_composition': m.write(tmp_path/'local.json', {'donors': [
        {'sheet_map': {'Model': name+' - Model'}} for name in ('A', 'B')]}),
        'report_plan': m.write(tmp_path/'plan.json', {'formulas': {'B1': combined[m.group_report.SHEET]['B1']}, 'literals': {'A1': 'Group report'}}),
        'report_expected': m.write(tmp_path/'expected.json', {'B1': {'type': 'number', 'value': '40'}})}
    monkeypatch.setattr(m, 'GEOMETRY', {'formulas': 3, 'nonempty': 12, 'targets': 3})
    return out, f


@pytest.mark.parametrize('cold', [False, True])
def test_complete_source_auditor_checks_new_finance_and_protected_context(tmp_path, monkeypatch, cold):
    out, f = small_source(tmp_path, monkeypatch, cold=cold)
    actual = m.audit_source(out['path'], f, cold=cold)
    assert actual['cells_checked'] == 12 and actual['formulas_checked'] == 3
    assert actual['provided_literals_exact'] and actual['native_error_count'] == 0
    assert len(actual['raw_value_sha256']) == len(actual['typed_value_sha256']) == 64


@pytest.mark.parametrize('mutation', ['literal', 'formula', 'cross_mandate', 'cached_value', 'raw_value', 'boolean', 'error', 'group', 'missing_cell'])
def test_complete_source_auditor_rejects_actual_corruptions(tmp_path, monkeypatch, mutation):
    out, f = small_source(tmp_path, monkeypatch, mutation=mutation)
    with pytest.raises(ValueError):
        m.audit_source(out['path'], f)


def test_append_only_receipt_writer_creates_parents_but_never_overwrites(tmp_path):
    target = tmp_path/'new'/'nested'/'receipt.json'
    record = m.write(target, {'value': 1})
    assert m.read(record) == {'value': 1}
    with pytest.raises(FileExistsError): m.write(target, {'value': 2})
    assert m.read(record) == {'value': 1}


def completed_fixture(tmp_path, monkeypatch):
    import json
    profile = tmp_path/'profile.yaml'; profile.write_text('contract: test\n')
    design = m.write(tmp_path/'design.json', {'fixed': True})
    prospective = m.write(tmp_path/'pool.json', {'fixed': True})
    monkeypatch.setattr(m, 'PROFILE', profile)
    monkeypatch.setattr(m, 'DESIGN', Path(design['path']))
    monkeypatch.setattr(m, 'DESIGN_SHA', design['sha256'])
    monkeypatch.setattr(m, 'PROSPECTIVE', Path(prospective['path']))
    monkeypatch.setattr(m, 'recipes', lambda: [])
    monkeypatch.setattr(m, 'GEOMETRY', {'nonempty': 12, 'formulas': 3, 'targets': 3})
    monkeypatch.setattr(m.dual, 'resource_check', lambda record, **kw: m.read(record))
    dummy = m.write(tmp_path/'dummy.json', {'fixed': True})
    public = m.write(tmp_path/'public.json', {'pair_id': 'R2-02'})
    cold = m.write(tmp_path/'cold.json', {'value': 'cold'})
    cert = m.write(tmp_path/'cert.json', {'pair_id': 'R2-02', 'contract': public, 'prospective': prospective,
        'cohort_design': design, 'recipe': [], 'mathematical_composition_certified': True,
        'independent_group_arithmetic_implementations': 2, 'cached_complete_local_reference_count': 2,
        'cached_complete_local_source_count': 2})
    cold_audit = m.write(tmp_path/'cold_audit.json', {'passed': True, 'audited_file': cold,
        'cold_formula_caches_empty': True, 'cells_checked': 12, 'formulas_checked': 3})
    f = {'kind': m.KIND, 'pair_id': 'R2-02', 'geometry': m.GEOMETRY, 'recipe': [],
         'runtime_profile': m.ref(profile), 'runtime_profile_value': {'contract': 'test'},
         'stage_order': ['source1', 'source2', 'source3'], 'required_actual_calls': 3, 'retry': 0,
         'local_optimizer_or_financial_forward_or_native_replays': 0, 'certificate': cert, 'public_contract': public,
         'cold_start': cold, 'local_composition': dummy, 'report_plan': dummy, 'report_expected': dummy,
         'report_emission': dummy, 'cold_audit': cold_audit,
         'donors': [{'workbook': dummy, 'source_manifest': dummy, 'reference': dummy}]*2}
    preparation = m.write(tmp_path/'preparation.json', f)
    m.write(tmp_path/'started.json', {'preparation': preparation, 'recipe': [], 'daemon_before_id': 'daemon'})
    calls = []; records = {}; previous = cold; owned = []
    for index in (1, 2, 3):
        name = f'source{index}'; out = m.write(tmp_path/(name+'.json'), {'index': index})
        resource = m.write(tmp_path/(name+'_resource.json'), {'container_id': str(index)*64})
        call = {'index': index, 'role': name, 'input': previous, 'output': out, 'completed': True,
                'actual_resource_evidence': {'terminal': resource, 'container_id': str(index)*64}}
        calls.append(call); owned.append({'receipt': resource, 'container_id': str(index)*64, 'absent': True})
        records[name+'_call'] = m.write(tmp_path/(name+'_call.json'), call)
        records[name+'_audit'] = m.write(tmp_path/(name+'_audit.json'), {'passed': True, 'audited_file': out,
            'cold_formula_caches_empty': False, 'cells_checked': 12, 'formulas_checked': 3, 'native_error_count': 0,
            'mismatch_count': 0, 'provided_literals_exact': True,
            'all_local_financial_values_checked_against_retained_AB_native_sources': True,
            'all_new_group_fields_checked_against_two_independent_compositions': True,
            'raw_value_sha256': 'a'*64, 'typed_value_sha256': 'b'*64})
        if index > 1:
            records[f'source{index-1}_to_{name}'] = m.write(tmp_path/f'stability{index}.json', {'passed': True,
                'raw_and_primary_complete_stability': True, 'left': previous, 'right': out,
                'raw_sha256': 'a'*64, 'typed_sha256': 'b'*64})
        previous = out
    records['cleanup'] = m.write(tmp_path/'cleanup.json', {'passed': True, 'all_owned_containers_absent': True,
        'same_daemon_before_after': True, 'daemon_id': 'daemon', 'owned': owned})
    # Resource checking returns its bound reference for cleanup matching.
    monkeypatch.setattr(m.dual, 'resource_check', lambda record, **kw: {'container_id': m.read(record)['container_id'], 'receipt': record})
    result = {'kind': m.TERMINAL_KIND, 'version': 1, 'passed': True, 'failure': None,
        'source_financially_verified': True, 'pair_id': 'R2-02', 'actual_calls_started': 3,
        'actual_calls_completed': 3, 'LO_calls': 3, 'retry': 0,
        'new_local_optimizer_financial_forward_or_native_replays': 0, 'model_solver_Harbor_calls': 0,
        'preparation': preparation, 'certificate': cert, 'specification': public,
        'local_composition': dummy, 'actual_calls': calls, 'source': previous, 'records': records}
    return result


def test_completed_admission_checks_evidence_and_returns_original_manifest(tmp_path, monkeypatch):
    value = completed_fixture(tmp_path, monkeypatch)
    record = m.write(tmp_path/'terminal.json', value)
    assert m.validate_completed(record) == value


@pytest.mark.parametrize('mutation', ['call_order', 'final_output', 'missing_call', 'audit_scope', 'stability',
    'resource_container', 'cleanup_missing', 'cleanup_unknown', 'daemon', 'recipe', 'wrong_pair'])
def test_completed_admission_rejects_incomplete_or_cross_bound_proofs(tmp_path, monkeypatch, mutation):
    value = completed_fixture(tmp_path, monkeypatch)
    if mutation == 'call_order': value['actual_calls'][0]['index'] = 2
    if mutation == 'final_output': value['source'] = value['actual_calls'][0]['output']
    if mutation == 'missing_call': value['actual_calls'].pop()
    if mutation in ('audit_scope', 'stability', 'cleanup_missing', 'cleanup_unknown', 'daemon'):
        key = {'audit_scope': 'source2_audit', 'stability': 'source1_to_source2',
               'cleanup_missing': 'cleanup', 'cleanup_unknown': 'cleanup', 'daemon': 'cleanup'}[mutation]
        changed = m.read(value['records'][key])
        if mutation == 'audit_scope': changed['cells_checked'] = 11
        if mutation == 'stability': changed['raw_sha256'] = 'c'*64
        if mutation == 'cleanup_missing': changed['owned'].pop()
        if mutation == 'cleanup_unknown': changed['owned'][0]['absent'] = False
        if mutation == 'daemon': changed['daemon_id'] = 'another daemon'
        value['records'][key] = m.write(tmp_path/'changed.json', changed)
    if mutation == 'resource_container': value['actual_calls'][0]['actual_resource_evidence']['container_id'] = 'f'*64
    if mutation in ('recipe', 'wrong_pair'):
        f = m.read(value['preparation'])
        if mutation == 'recipe': f['recipe'] = ['different']
        if mutation == 'wrong_pair': f['pair_id'] = 'R2-03'
        value['preparation'] = m.write(tmp_path/'changed_preparation.json', f)
    record = m.write(tmp_path/'terminal.json', value)
    with pytest.raises(ValueError): m.validate_completed(record)


class FakeAudit:
    def __init__(self, *args, **kwargs):
        from types import SimpleNamespace
        self.db = SimpleNamespace(close=lambda: None)
    def snapshot(self): return {}
    def events(self): return []
    def update_run(self, **kwargs): pass
    def export(self): pass


class FakeDashboard:
    def __init__(self, *args, **kwargs): pass
    def start(self): return 'http://127.0.0.1:1/'
    def stop(self): pass


def test_cli_dashboard_is_started_before_reading_or_composing_sources(tmp_path, monkeypatch):
    order = []
    class Dashboard(FakeDashboard):
        def start(self): order.append('dashboard'); return super().start()
    monkeypatch.setattr(m.dual, 'AuditStore', FakeAudit)
    monkeypatch.setattr(m.dual, 'DashboardServer', Dashboard)
    def fake_prepare(*args): order.append('prepare'); return {'stage': 'prepared'}
    def fake_run(*args): order.append('native'); return {'stage': 'complete'}
    monkeypatch.setattr(m, 'prepare', fake_prepare); monkeypatch.setattr(m, 'run', fake_run)
    m.main(['--pair', 'R2-02', '--output', str(tmp_path/'new_source'), '--run'])
    assert order == ['dashboard', 'prepare', 'native']
    assert not (tmp_path/'new_source').exists()


def test_started_count_and_failed_cleanup_remain_truthful_when_calculation_raises(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import json
    value = completed_fixture(tmp_path, monkeypatch)
    folder = tmp_path/'new_attempt'; folder.mkdir()
    preparation = m.write(folder/'preparation.json', m.read(value['preparation']))
    monkeypatch.setattr(m, 'ROOT', tmp_path)
    monkeypatch.setattr(m.dual, 'AuditStore', FakeAudit)
    monkeypatch.setattr(m.dual, 'DashboardServer', FakeDashboard)
    monkeypatch.setattr(m.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout='daemon\n'))
    class Engine:
        def __init__(self, *args, **kwargs): pass
        def recalculate(self, *args): raise RuntimeError('original native failure')
        def metadata(self): return {'actual_resource_receipts': []}
    monkeypatch.setattr(m.helpers, 'engine_class', lambda: Engine)
    def unknown(*args): raise RuntimeError('absence was not observed')
    monkeypatch.setattr(m.dual, 'owned_cleanup', unknown)
    with pytest.raises(RuntimeError, match='Preserve the failed first source'): m.run(preparation)
    terminal = m.read(folder/'terminal.json')
    assert terminal['actual_calls_started'] == 1
    assert terminal['actual_calls_completed'] == terminal['LO_calls'] == 0
    assert terminal['failure']['message'] == 'original native failure'
    assert not terminal['passed'] and not terminal['source_financially_verified']
    assert m.read(terminal['records']['cleanup_unknown'])['owned_absence_proven'] is False
    assert 'cleanup' not in terminal['records']
    assert (tmp_path/'outputs/research/.cached_ringfenced_pair_source_reservations_v1/R2-02.json').exists()
